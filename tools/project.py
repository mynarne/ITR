"""Inspect, explicitly approve, run and verify local project QA. No external services."""
import sys
sys.dont_write_bytecode = True

import argparse
import hmac
import os
import signal
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from itr import Journal
from itr_store import digest, encoded, fresh, gate, load, names, need, now, predecessor, safe_file
from project_plan import EVIDENCE_SCHEMA_VERSION, inspect, stable, validate
from project_process import run_command
from project_verify import verify_project


def decision(states):
    return next((s for s in ["failed", "blocked", "not_run", "passed"] if s in states), "not_run")


def one(check, number, command, bundle, journal, missing, parent_status, stop):
    _, _, _, binding, payloads, actual_paths = bundle
    key = check["id"]
    proof = None
    if not check.get("selected", True):
        status, why = "not_run", "고정된 계획의 선택 범위 밖."
    elif missing:
        status, why = "blocked", "필수 능력 미지원 · " + ", ".join(missing)
    elif parent_status:
        status, why = "blocked", "선행 검사 미통과 · " + ", ".join(parent_status)
    elif not command:
        status, why = "not_run", "승인된 실행 명령이 지정되지 않았습니다."
    else:
        journal.emit(key, "running", "승인된 로컬 명령의 작업 사본을 준비합니다.")
        report = {"evidence_schema_version": binding["evidence_schema_version"], "argv": command["argv"],
                  "launch_argv": None, "exit_code": None}
        try:
            status, why = run_command(command, binding, payloads, actual_paths, stop, report)
        except OSError as error:
            status, why = "blocked", f"로컬 실행 환경 오류 · {error.__class__.__name__}"
            report.update(finished_at=now(), error=why)
        if "pass_marker" in command:
            marker = command["pass_marker"]
            seen = marker in report.get("stdout", "") or report.get("stdout_marker_excerpt", {}).get("text") == marker
            report.update(pass_marker=marker, pass_marker_seen=seen)
            if status == "passed" and not seen:
                status, why = "blocked", "종료 코드 0이지만 stdout에서 지정한 통과 증거 문구를 확인하지 못했습니다."
        report.update(check_id=key, pass_condition=check["pass_condition"], status=status, detail=why)
        content = encoded(report)
        path = f"evidence/{number:04d}.json"
        fresh(journal.path.parent / path, content)
        proof = {"id": f"EV-{number:04d}", "check_id": key, "kind": "review" if check["method"] == "inspection" else "log",
                 "path": path, "sha256": digest(content)}
    result = dict(check_id=key, status=status, detail=why, evidence_ids=[proof["id"]] if proof else [])
    journal.emit(key, status, why)
    return result, proof


def merged_defects(checks, commands, results):
    groups = {}
    for outcome in results:
        if outcome["status"] != "failed":
            continue
        key = outcome["check_id"]
        fingerprint = commands[key].get("fingerprint", "check:" + key)
        if fingerprint not in groups:
            groups[fingerprint] = dict(id=f"D-{len(groups)+1:03d}", fingerprint=fingerprint,
                                       check_ids=[], baseline_ids=[], evidence_ids=[], observed="",
                                       cause_confirmed=None, hypothesis=None,
                                       minimal_fix="실패 증거의 최초 기대값·실제값 차이를 확인해 해당 경로만 수정한다.",
                                       next_regression="")
        group = groups[fingerprint]
        group["check_ids"].append(key)
        group["baseline_ids"] = list(dict.fromkeys([*group["baseline_ids"], *checks[key]["criteria"]]))
        group["evidence_ids"].extend(outcome["evidence_ids"])
        group["observed"] = "실패 종료 코드 1을 관찰한 검사 · " + ", ".join(group["check_ids"])
        group["next_regression"] = "같은 통과 조건과 입력으로 재검사 · " + ", ".join(group["check_ids"])
    return list(groups.values())


def run(args, stop):
    need(args.round > 0 and args.attempt > 0 and 1 <= args.jobs <= 32, "회차·시도는 양수, 동시 작업 수는 1~32입니다.")
    bundle = inspect(args.workspace, args.plan)
    plan, raw, inputs, binding, payloads, _ = bundle
    need(hmac.compare_digest(binding["approval_sha256"], args.approve),
         "승인 지문 불일치. inspect의 파일·명령·능력과 승인 지문을 확인하세요.")
    root = args.store.resolve()
    root.mkdir(parents=True, exist_ok=True)
    link = None
    for kind, ref in [("correction", args.corrects), ("retry", args.retry), ("regression", args.previous)]:
        if ref:
            reason = args.reason if kind == "correction" else args.reason or ("프로젝트 회귀" if kind == "regression" else "동일 회차 재실행")
            link = predecessor(root, ref, kind, reason, args.round, args.attempt)
    need(args.round == 1 or link, "두 번째 이후 회차는 이전 회차 링크가 필요합니다.")
    need(args.attempt == 1 or link, "재시도 또는 정정 원본 링크가 필요합니다.")
    need(link or not args.reason, "사유에는 원본 링크가 필요합니다.")
    scope = {"product": inputs["product"], "revision": inputs["revision"], "files_sha256": stable(binding["files"])}
    if link:
        original = safe_file(root, link["record_path"]).parent
        reservation = load(safe_file(original, "reservation.json"))
        need(reservation.get("project_scope", {}).get("product") == inputs["product"], "다른 제품 이력 참조")
        if link["type"] in {"retry", "correction"}:
            need(reservation["project_scope"] == scope, "제품·고정 파일 변경은 다음 회차에 기록하세요.")
            if link["type"] == "retry":
                need(reservation["approval_sha256"] == args.approve, "재시도 계획 변경은 정정 또는 새 회차에 기록하세요.")
    directory = safe_file(root, names(args.round, args.attempt))
    directory.parent.mkdir(exist_ok=True)
    directory.mkdir(exist_ok=False)
    header = dict(run_id="itr-" + uuid.uuid4().hex, round=args.round, attempt=args.attempt,
                  created_at=now(), previous=link)
    fresh(directory / "reservation.json", encoded({**header, "project_scope": scope, "approval_sha256": args.approve}))
    try:
        fresh(directory / "plan.json", raw)
        fresh(directory / "input.json", encoded(inputs))
        fresh(directory / "approval.json", encoded(binding))
        for name, data in payloads.items():
            output = directory / "sources" / name
            output.parent.mkdir(parents=True, exist_ok=True)
            fresh(output, data)
        (directory / "evidence").mkdir()
        (directory / "reviews").mkdir()
        journal = Journal(directory)
        checks = {c["id"]: c for c in inputs["checks"]}
        numbered = {key: idx for idx, key in enumerate(checks, 1)}
        available = {c["id"] for c in inputs["capabilities"] if c["available"]}
        for key in checks:
            journal.emit(key, "queued", "승인된 검사를 등록했습니다.")
        outcomes, reviews = {}, {}
        role_checks = {}
        for key, check in checks.items():
            role = check["role"]
            if role != "runner" and check.get("selected", True):
                role_checks.setdefault(role, []).append(key)
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            while len(outcomes) < len(checks):
                if stop.is_set():
                    raise InterruptedError("중단 요청")
                ready = [c for key, c in checks.items() if key not in outcomes
                         and all(k in outcomes for k in c.get("depends_on", []))]
                pending = {}
                for check in ready:
                    key = check["id"]
                    missing = [c for c in check["requires"] if c not in available]
                    deps = [k for k in check.get("depends_on", []) if outcomes[k][0]["status"] != "passed"]
                    pending[key] = pool.submit(one, check, numbered[key], plan["commands"].get(key), bundle,
                                               journal, missing, deps, stop)
                outcomes.update({k: job.result() for k, job in pending.items()})
                if stop.is_set():
                    raise InterruptedError("중단 요청")
                for role, keys in role_checks.items():
                    if role in reviews or not all(k in outcomes for k in keys):
                        continue
                    rows = [outcomes[k][0] for k in keys]
                    review = dict(role=role, check_ids=keys, verdict=decision({r["status"] for r in rows}),
                                  evidence_ids=[e for r in rows for e in r["evidence_ids"]], sealed_at=now())
                    fresh(directory / "reviews" / (role + ".json"), encoded(review))
                    reviews[role] = review
        results = [outcomes[k][0] for k in checks]
        evidence = [outcomes[k][1] for k in checks if outcomes[k][1]]
        state = gate(inputs["checks"], results)
        defects = merged_defects(checks, plan["commands"], results)
        history = []
        if link and link["record_path"].endswith("/record.json"):
            prior = load(safe_file(root, link["record_path"]))
            tracked = {r["fingerprint"]: list(r["checks"]) for r in prior["extensions"].get("regression", [])}
            tracked.update({d["fingerprint"]: d["check_ids"] for d in prior["defects"]})
            current = {d["fingerprint"] for d in defects}
            for fingerprint, keys in tracked.items():
                observations = {k: outcomes[k][0]["status"] if k in outcomes else "not_run" for k in keys}
                result = "reobserved" if fingerprint in current else (
                    "passed_recheck" if set(observations.values()) == {"passed"} else "inconclusive")
                history.append(dict(fingerprint=fingerprint, source_run=link["run_id"], checks=observations, state=result))
        record = {**header, "schema_version": "1.0", "input": inputs, "events": journal.events, "results": results,
                  "evidence": evidence, "defects": defects, "reviews": list(reviews.values()),
                  "approval": {"status": "not_requested", "actor": None, "at": None},
                  "decision": {"status": state, "reason": "선택한 검사 기준의 기술 판정. 실패, 차단, 미실행, 통과의 순으로 집계."},
                  "extensions": {"adapter": "itr.local.project.v1", "approval_sha256": args.approve,
                                 "evidence_schema_version": binding["evidence_schema_version"],
                                 "standards": plan["standards"], "regression": history}}
        validate(record)
        content = encoded(record)
        fresh(directory / "record.json", content)
        fresh(directory / "COMPLETE.json", encoded({"sha256": digest(content)}))
    except BaseException as error:
        fresh(directory / "interruption.json", encoded({"at": now(), "error": type(error).__name__, "detail": str(error)}))
        raise
    print(f"{header['created_at']} KST · {state} · {directory / 'record.json'}")
    return 3 if args.require_pass and state != "passed" else 0


def main():
    parser = argparse.ArgumentParser(description="ITR · 승인한 로컬 프로젝트 검사")
    sub = parser.add_subparsers(dest="command", required=True)
    inspector = sub.add_parser("inspect")
    runner = sub.add_parser("run")
    for p in [inspector, runner]:
        p.add_argument("--workspace", required=True, type=Path)
        p.add_argument("--plan", required=True, type=Path)
    runner.add_argument("--approve", required=True)
    runner.add_argument("--store", type=Path, default=Path("itr-runs"))
    runner.add_argument("--round", type=int, required=True)
    runner.add_argument("--attempt", type=int, default=1)
    runner.add_argument("--jobs", type=int, default=4)
    refs = runner.add_mutually_exclusive_group()
    refs.add_argument("--previous")
    refs.add_argument("--corrects")
    refs.add_argument("--retry")
    runner.add_argument("--reason")
    runner.add_argument("--require-pass", action="store_true")
    verifier = sub.add_parser("verify")
    verifier.add_argument("record", type=Path)
    args = parser.parse_args()
    if args.command == "inspect":
        plan, _, inputs, binding, _, _ = inspect(args.workspace, args.plan)
        print(encoded({**binding, "product": inputs["product"], "revision": inputs["revision"],
                       "mode": inputs["mode"], "commands": plan["commands"]}).decode("utf-8"), end="")
        return 0
    if args.command == "verify":
        data = verify_project(args.record.absolute())
        version = data["extensions"].get("evidence_schema_version")
        note = (f"증거 {EVIDENCE_SCHEMA_VERSION} · 실행 인수 필드 확인" if version == EVIDENCE_SCHEMA_VERSION
                else "기존 증거 · 실제 실행 인수 미기록")
        print(f"검증 통과 · {data['run_id']} · {data['created_at']} KST · {note}")
        return 0
    stop = threading.Event()
    old = {}
    for sig in [signal.SIGINT, signal.SIGTERM]:
        old[sig] = signal.signal(sig, lambda *_: stop.set())
    try:
        return run(args, stop)
    finally:
        for sig, previous in old.items():
            signal.signal(sig, previous)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as err:
        print(f"ITR · {err}", file=sys.stderr)
        sys.exit(2)
