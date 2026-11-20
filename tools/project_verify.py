"""Verify a local adapter archive offline. No project command executes during verification."""
from pathlib import Path

from itr_store import digest, gate, keyed, names, need, predecessor, safe_file
from project_plan import plan_checks, read_json, stable, validate


def verify_project(path):
    folder, root = path.parent, path.parent.parent.parent
    need(path.name == "record.json" and path == safe_file(root, path.relative_to(root).as_posix()), "원본 기록 경로 오류")
    def read(rel):
        return read_json(safe_file(folder, rel))
    record = read("record.json")
    validate(record)
    need(path.parent == root / names(record["round"], record["attempt"]), "회차 경로 불일치")
    need(digest(path.read_bytes()) == read("COMPLETE.json")["sha256"], "원본 기록 해시 불일치")
    need(record["extensions"]["adapter"] == "itr.local.project.v1", "일반 로컬 프로젝트 어댑터 기록이 아닙니다.")
    frozen, binding, plan, reservation = read("input.json"), read("approval.json"), read("plan.json"), read("reservation.json")
    need(frozen == record["input"], "고정 입력과 최종 입력 불일치")
    need(binding["approval_sha256"] == stable({k:v for k,v in binding.items() if k != "approval_sha256"})
         == reservation["approval_sha256"] == record["extensions"]["approval_sha256"], "실행 승인 지문 불일치")
    need(binding["plan_sha256"] == digest(safe_file(folder, "plan.json").read_bytes()), "고정 계획 바이트 불일치")
    need(set(plan["files"]) == {s["path"] for s in binding["files"]}, "입력 파일 목록 불일치")
    need(record["extensions"]["standards"] == plan["standards"], "표준 선택 근거 불일치")
    need(frozen == {**plan["input"], "capabilities": binding["capabilities"]}, "계획·실행 능력 고정 불일치")
    for item in binding["files"]:
        need(digest(safe_file(folder, "sources/" + item["path"]).read_bytes()) == item["sha256"], "고정 파일 해시 불일치")
    need(reservation["project_scope"] == dict(product=frozen["product"], revision=frozen["revision"],
                                              files_sha256=stable(binding["files"])), "제품 리비전 범위 불일치")
    need(all(reservation[key] == record[key] for key in ["round", "attempt", "run_id", "previous", "created_at"]),
         "예약 및 기록 불일치")
    link = record["previous"]
    if link:
        actual = predecessor(root, link["record_path"], link["type"], link["reason"],
                             record["round"], record["attempt"], historical=True)
        need(actual == link, "이력 참조 불일치")
        old = read_json(safe_file(root, link["record_path"]).parent / "reservation.json")
        need(old["project_scope"]["product"] == frozen["product"], "다른 제품 회차")
        if link["type"] in {"correction", "retry"}:
            need(old["project_scope"] == reservation["project_scope"], "동일 회차 제품 리비전 불일치")
        if link["type"] == "retry":
            need(old["approval_sha256"] == binding["approval_sha256"], "재시도 승인 지문 불일치")
    else:
        need(record["round"] == 1 and record["attempt"] == 1, "이력 참조 누락")

    checks, results = plan_checks(frozen), keyed(record["results"], "check_id")
    proof = keyed(record["evidence"], "id")
    need(checks.keys() == results.keys(), "계획 및 결과 목록 불일치")
    need(set(binding["executables"]) == {c["argv"][0] for c in plan["commands"].values()}, "승인 실행기 목록 불일치")
    states, starts, ends = {}, {}, {}
    transitions = {None: {"queued"}, "queued": {"running", "not_run", "blocked"},
                   "running": {"passed", "failed", "blocked", "not_run"}}
    for n, event in enumerate(record["events"], 1):
        key, state = event["check_id"], event["state"]
        need(event == read(f"events/{n:04d}.json") and event["seq"] == n, "원본 이벤트 또는 순번 불일치")
        need(key in checks and state in transitions.get(states.get(key), ()), "이벤트 전이 오류")
        states[key] = state
        if state == "running":
            starts[key] = n
        elif state != "queued":
            ends[key] = n
    need(len(list((folder / "events").glob("*.json"))) == len(record["events"]), "원본 이벤트 개수 불일치")
    available = {c["id"] for c in frozen["capabilities"] if c["available"]}
    for key in checks:
        check, outcome = checks[key], results[key]
        status, ids = outcome["status"], outcome["evidence_ids"]
        need(states.get(key) == status, "마지막 이벤트와 결과 불일치")
        deps = check.get("depends_on", [])
        if not check.get("selected", True):
            need(status == "not_run" and key not in starts, "선택하지 않은 검사 실행")
        elif not set(check["requires"]) <= available or any(results[k]["status"] != "passed" for k in deps):
            need(status == "blocked" and key not in starts, "미충족 선행 조건 또는 능력")
        elif key not in plan["commands"]:
            need(status == "not_run" and key not in starts, "명령 없는 검사 결과 오류")
        else:
            need(key in starts and all(ends[p] < starts[key] for p in deps), "실행 이벤트·의존 관계 오류")
        need(bool(ids) == (key in starts) and len(ids) <= 1, "실행 증거 개수 오류")
        for ident in ids:
            evidence = proof[ident]
            source = safe_file(folder, evidence["path"])
            need(evidence["check_id"] == key and digest(source.read_bytes()) == evidence["sha256"], "증거 해시·소유자 불일치")
            obs = read_json(source)
            need(obs["status"] == status and obs["check_id"] == key and obs["argv"] == plan["commands"][key]["argv"]
                 and obs["pass_condition"] == check["pass_condition"] and obs["detail"] == outcome["detail"],
                 "실행 증거·판정 불일치")
            if "pass_marker" in plan["commands"][key]:
                literal = plan["commands"][key]["pass_marker"]
                seen = literal in obs.get("stdout", "")
                need(obs.get("pass_marker") == literal and obs.get("pass_marker_seen") is seen
                     and (status != "passed" or seen), "통과 증거 문구와 stdout 불일치")
            if status != "blocked":
                need(obs["exit_code"] == {"passed":0, "failed":1, "not_run":77}[status], "종료 코드와 판정 불일치")
    need(set(proof) == {e for r in results.values() for e in r["evidence_ids"]}, "참조가 없는 증거")
    groups = {}
    for key, outcome in results.items():
        if outcome["status"] == "failed":
            fp = plan["commands"][key].get("fingerprint", "check:" + key)
            groups.setdefault(fp, []).append(key)
    defects = keyed(record["defects"], "fingerprint")
    keyed(record["defects"], "id")
    need(groups.keys() == defects.keys(), "결함 중복 제거 또는 누락")
    for fp, keys in groups.items():
        defect = defects[fp]
        need(set(defect["check_ids"]) == set(keys) and set(defect["evidence_ids"]) ==
             {e for key in keys for e in results[key]["evidence_ids"]} and set(defect["baseline_ids"]) ==
             {b for key in keys for b in checks[key]["criteria"]}, "결함의 검사·목표·증거 참조 불일치")
    expected_roles = {}
    for key, check in checks.items():
        if check["role"] != "runner" and check.get("selected", True):
            expected_roles.setdefault(check["role"], []).append(key)
    reviews = keyed(record["reviews"], "role")
    need(reviews.keys() == expected_roles.keys(), "선택된 역할별 검토 누락")
    for role, keys in expected_roles.items():
        entry = reviews[role]
        need(read("reviews/" + role + ".json") == entry and set(entry["check_ids"]) == set(keys), "독립 검토 원본 불일치")
        statuses = {results[k]["status"] for k in keys}
        expected = next(s for s in ("failed", "blocked", "not_run", "passed") if s in statuses)
        need(entry["verdict"] == expected and set(entry["evidence_ids"]) ==
             {e for key in keys for e in results[key]["evidence_ids"]}, "독립 판정 근거 불일치")
    need(record["approval"] == {"status":"not_requested", "actor":None, "at":None}, "로컬 명령으로 인수 승인 불가")
    need(record["decision"]["status"] == gate(frozen["checks"], record["results"]), "기술 게이트 불일치")
    return record
