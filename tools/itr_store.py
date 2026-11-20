"""Local append-only attempt storage and integrity checks for the ITR demo."""
import hashlib
import importlib.util
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
TERMINAL = {"passed", "failed", "blocked", "not_run"}
ATTEMPT_FILE = re.compile(r"round-(\d{4,})/attempt-(\d{4,})/(record|reservation)\.json")


def now():
    return datetime.now(KST).isoformat(timespec="microseconds")


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fresh(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def need(condition, message):
    if not condition:
        raise ValueError(message)


def safe_file(root, rel):
    parts = rel.split("/")
    need(all(part not in ("", ".", "..") and ":" not in part and "\\" not in part
             and all(ord(char) >= 32 for char in part) for part in parts), f"잘못된 경로 {rel}")
    path = root
    for part in parts:
        path = path / part
        need(not path.is_symlink(), f"심볼릭 링크 경로 {rel}")
    return path


def names(round_no, attempt):
    return f"round-{round_no:04d}/attempt-{attempt:04d}"


def predecessor(root, rel, kind, reason, round_no, attempt, historical=False):
    need(reason and reason.strip(), "원본 링크와 사유가 모두 필요합니다.")
    match = ATTEMPT_FILE.fullmatch(rel)
    need(match is not None, "이력 경로는 저장소 기준 round-N/attempt-N/record.json 또는 reservation.json입니다.")
    old_round, old_attempt = map(int, match.groups()[:2])
    need(rel == names(old_round, old_attempt) + "/" + match[3] + ".json", "비표준 원본 경로")
    if kind == "regression":
        need(old_round < round_no and attempt == 1, "회귀는 앞 회차에서 새 회차의 첫 시도로 연결합니다.")
    else:
        need(old_round == round_no and old_attempt < attempt, "재시도·정정은 같은 회차의 앞선 시도에 연결합니다.")
    path = safe_file(root, rel)
    if match[3] == "reservation":
        need(kind == "retry" and (historical or not (path.parent / "COMPLETE.json").exists()),
             "예약 참조는 미완결 시도의 재시도에만 사용할 수 있습니다.")
    data = path.read_bytes()
    source = json.loads(data)
    need((source["round"], source["attempt"]) == (old_round, old_attempt), "원본 식별자 불일치")
    if match[3] == "record":
        need(load(path.parent / "COMPLETE.json")["sha256"] == digest(data), "원본 기록 해시 불일치")
    return {"run_id": source["run_id"], "round": old_round, "attempt": old_attempt,
            "type": kind, "reason": reason, "record_path": rel, "sha256": digest(data)}


def gate(checks, results):
    selected = {check["id"] for check in checks if check.get("selected", True)}
    statuses = {r["status"] for r in results if r["check_id"] in selected}
    for state in ("failed", "blocked", "not_run"):
        if state in statuses:
            return state
    return "passed" if statuses else "not_run"


def keyed(rows, key):
    result = {row[key]: row for row in rows}
    need(len(result) == len(rows), f"중복 식별자 {key}")
    return result


def schema_validate(record):
    validator_file = Path(__file__).resolve().parents[1] / "schemas" / "validate.py"
    spec = importlib.util.spec_from_file_location("itr_schema_validate", validator_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.validate(record)


def verify(record_path):
    directory = record_path.parent
    root = directory.parent.parent
    record = load(record_path)
    schema_validate(record)
    need(directory == root / names(record["round"], record["attempt"]), "회차·시도 경로 불일치")
    marker = load(safe_file(directory, "COMPLETE.json"))
    need(marker["sha256"] == digest(record_path.read_bytes()), "봉인된 기록 해시 불일치")
    for key, value in load(safe_file(directory, "context.json")).items():
        need(record["extensions"].get(key) == value, "사전 고정한 실행 맥락 불일치")
    frozen = load(safe_file(directory, "input.json"))
    need(frozen == record["input"], "입력 스냅샷 불일치")
    reservation = load(safe_file(directory, "reservation.json"))
    need(all(reservation[k] == record[k] for k in ("run_id", "round", "attempt", "created_at", "previous")),
         "예약과 최종 기록 불일치")
    previous = record["previous"]
    if previous:
        actual = predecessor(root, previous["record_path"], previous["type"], previous["reason"],
                             record["round"], record["attempt"], historical=True)
        need(actual == previous, "원본 참조 또는 원본 바이트가 변경되었습니다.")
    need(record["attempt"] == 1 or previous is not None, "재시도 이력 누락")
    need(record["input"]["revision"] == "sha256:" + digest(safe_file(directory, "subject.py").read_bytes()),
         "고정된 합성 제품 리비전 불일치")

    checks = keyed(frozen["checks"], "id")
    baselines = keyed(frozen["baselines"], "id")
    capabilities = keyed(frozen["capabilities"], "id")
    results = keyed(record["results"], "check_id")
    evidence = keyed(record["evidence"], "id")
    need(checks.keys() == results.keys(), "계획과 결과 목록 불일치")
    for item in evidence.values():
        need(item["check_id"] in checks, "증거 검사 참조 누락")
        need(digest(safe_file(directory, item["path"]).read_bytes()) == item["sha256"], "증거 해시 불일치")
    transitions = {None: {"queued"}, "queued": {"running", "blocked", "not_run"},
                   "running": {"passed", "failed", "blocked"}}
    states = {}
    for seq, event in enumerate(record["events"], 1):
        need(event == load(safe_file(directory, f"events/{seq:04d}.json")), "원본 이벤트 불일치")
        key = event["check_id"]
        need(key in checks and event["seq"] == seq, "이벤트 순번/검사 불일치")
        need(event["state"] in transitions.get(states.get(key), ()), "잘못된 이벤트 전이")
        states[key] = event["state"]
    for key, check in checks.items():
        result = results[key]
        need(set(check["criteria"]) <= baselines.keys() and set(check["requires"]) <= capabilities.keys()
             and set(check.get("depends_on", [])) <= checks.keys(), "검사 계획 참조 누락")
        need(set(check.get("depends_on", [])) <= checks.keys(), "선행 검사 참조 누락")
        need(states.get(key) == result["status"], "마지막 이벤트와 판정 불일치")
        need(all(e in evidence and evidence[e]["check_id"] == key for e in result["evidence_ids"]),
             "판정 증거의 생성 검사 불일치")
        if not check.get("selected", True):
            need(result["status"] == "not_run", "선택하지 않은 검사에 실행 판정이 있습니다.")
        elif any(not capabilities[c]["available"] for c in check["requires"]):
            need(result["status"] == "blocked", "필수 능력 미지원 검사는 차단입니다.")
        if result["status"] in {"passed", "failed"}:
            need(all(results[parent]["status"] == "passed" for parent in check.get("depends_on", [])),
                 "선행 검사 실패/미실행 상태에서 실행 판정")
    defects = keyed(record["defects"], "id")
    keyed(record["defects"], "fingerprint")
    for defect in defects.values():
        need(set(defect["check_ids"]) <= checks.keys() and set(defect["baseline_ids"]) <= baselines.keys()
             and set(defect["evidence_ids"]) <= evidence.keys(), "결함 참조 누락")
        need(all(evidence[e]["check_id"] in defect["check_ids"] for e in defect["evidence_ids"]),
             "결함 증거와 관측 검사 불일치")
    failed = {key for key, result in results.items() if result["status"] == "failed"}
    need(failed == {key for defect in defects.values() for key in defect["check_ids"]},
         "실패 관측과 결함 집합 불일치")
    reviews = keyed(record["reviews"], "role")
    roles = {c["role"] for c in checks.values() if c["role"] != "runner" and c["selected"]}
    need(roles == reviews.keys(), "선택한 역할의 독립 1차 판정 누락")
    for role, review in reviews.items():
        need(review == load(safe_file(directory, "reviews/" + role + ".json")), "독립 봉인 판정 불일치")
        need(all(key in checks and checks[key]["role"] == role for key in review["check_ids"]),
             "1차 판정 소유 역할 불일치")
        need(review["check_ids"] and all(results[key]["status"] == review["verdict"] for key in review["check_ids"]),
             "1차 판정과 해당 합성 관측 불일치")
        expected_proof = {e for key in review["check_ids"] for e in results[key]["evidence_ids"]}
        need(set(review["evidence_ids"]) == expected_proof, "검토 증거 참조 누락")
    need(set(record["approval"].get("evidence_ids", [])) <= evidence.keys(), "승인 증거 참조 누락")
    need(gate(frozen["checks"], record["results"]) == record["decision"]["status"], "기술 게이트 불일치")
    return record
