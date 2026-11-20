"""ITR local synthetic runner. Python 3.9+, standard library, offline."""
import sys
sys.dont_write_bytecode = True

import argparse
import json
import os
import subprocess
import threading
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from itr_fixture import observe, plan, subject_bytes
from itr_store import (digest, encoded, fresh, gate, load, names, need, now,
                       predecessor, safe_file, schema_validate, verify)


class Journal:
    """Serialize event order and preserve each transition before proceeding."""
    def __init__(self, directory):
        self.path = directory / "events"
        self.path.mkdir()
        self.events = []
        self.lock = threading.Lock()

    def emit(self, key, state, message):
        with self.lock:
            seq = len(self.events) + 1
            event = dict(seq=seq, at=now(), check_id=key, state=state, message=message)
            fresh(self.path / f"{seq:04d}.json", encoded(event))
            self.events.append(event)


def execute(check, subject, journal, unavailable, prereq_failed=False):
    key, role = check["id"], check["role"]
    proof = None
    if not check["selected"]:
        status = "not_run"
        detail = "선택적 장부 연동은 이번 범위에서 제외." if key == "link-ledger" else "배송 기준 변경분의 선택 범위 밖."
    elif unavailable or prereq_failed:
        status = "blocked"
        detail = "필수 실행 능력 미제공 · " + ", ".join(unavailable) if unavailable else "선행 검사 통과 증거 부족."
    else:
        journal.emit(key, "running", "고정된 입력으로 검사 시작.")
        try:
            expected, actual, trace = observe(key, subject)
            status = "passed" if expected == actual else "failed"
            detail = "관찰값이 고정된 통과 조건과 일치." if status == "passed" else {
                "bb-boundary": "10,000원 주문에 배송비 3,000원이 청구됨.",
                "wb-logic": "shipping의 무료 배송 비교식에서 경계값이 제외됨.",
            }.get(key, "실제 관찰값이 통과 조건과 다름.")
            report = dict(check_id=key, condition=check["pass_condition"], trace=trace,
                          expected=expected, observed=actual, status=status)
        except (OSError, subprocess.SubprocessError, KeyError, TypeError, SyntaxError, ValueError, StopIteration) as err:
            status, detail = "blocked", f"어댑터가 관찰을 완료하지 못했습니다 · {type(err).__name__}: {err}"
            report = dict(check_id=key, condition=check["pass_condition"], status=status, error=detail)
        path = "evidence/" + key + ".json"
        data = encoded(report)
        fresh(subject.parent / path, data)
        proof = dict(id="EV-" + key, check_id=key, kind="review" if check["method"] == "inspection" else "log",
                     path=path, sha256=digest(data))
    evidence_ids = [proof["id"]] if proof else []
    result = dict(check_id=key, status=status, detail=detail, evidence_ids=evidence_ids)
    review = None
    if role != "runner" and check["selected"]:
        review = dict(role=role, check_ids=[key], verdict=status, evidence_ids=evidence_ids, sealed_at=now())
        fresh(subject.parent / "reviews" / (role + ".json"), encoded(review))
    journal.emit(key, status, detail)
    return result, proof, review


def findings(results, checks):
    failed = {r["check_id"]: r for r in results if r["status"] == "failed"}
    groups = []
    boundary = [k for k in ("bb-boundary", "wb-logic") if k in failed]
    if boundary:
        groups.append(dict(
            id="D-001", fingerprint="receipt.shipping.threshold.inclusive", check_ids=boundary,
            baseline_ids=["G-TOTAL", "R-FREE"], evidence_ids=[e for k in boundary for e in failed[k]["evidence_ids"]],
            observed="무료 배송 기준인 10,000원에서 경계 조건이 어긋난다.",
            cause_confirmed="shipping 조건식이 subtotal > 10000이어서 같은 금액을 제외한다." if "wb-logic" in boundary else None,
            hypothesis=None if "wb-logic" in boundary else "비교식에서 같은 금액을 제외했을 가능성이 있다.",
            minimal_fix="무료 배송 비교식에 같은 금액을 포함한다.",
            next_regression="bb-boundary 및 wb-logic으로 9,999·10,000·10,001원 사례와 소스 조건을 재검사한다."))
    for key in sorted(failed.keys() - set(boundary)):
        groups.append(dict(id="D-" + key, fingerprint="receipt." + key, check_ids=[key],
                           baseline_ids=checks[key]["criteria"], evidence_ids=failed[key]["evidence_ids"],
                           observed=failed[key]["detail"], cause_confirmed=None, hypothesis=None,
                           minimal_fix="기대값과 실제값의 차이를 먼저 원본 증거에서 좁힌다.",
                           next_regression=checks[key]["pass_condition"]))
    return groups


def run_context(mode, variant):
    mappings = [
        ("ISO/IEC 25010:2023", True, "영수증 기능 정확성을 입력·기대 금액으로 관찰한다."),
        ("ISO/IEC 25019:2023", True, "소액 구매자 및 현장 직원의 과업을 명시한다. 실기기 사용자 경험은 미확인이다."),
        ("ISO/IEC/IEEE 29119-1:2022", True, "검사 수준과 결과 상태의 뜻을 팀이 공통으로 사용한다."),
        ("ISO/IEC/IEEE 29119-2:2021", True, "계획·환경 능력·실행·판정을 별도로 기록한다."),
        ("ISO/IEC/IEEE 29119-3:2021", True, "각 검사 계획에 결과, 증거, 결함 식별자를 연결한다."),
        ("ISO/IEC/IEEE 29119-4:2021", True, "무료 배송 경계 양옆의 9,999·10,000·10,001원을 조사한다."),
        ("ISO/IEC 20246:2017", True, "배송 비교식, 계약, 설정을 소스 산출물 검토로 구분한다."),
        ("ISO/IEC 25040:2024", False, "이번 단일 합성 제품 회차는 고정 목표·측정값·판정만으로 평가 범위를 기술한다."),
    ]
    return {"adapter": "itr.local.synthetic.v1", "fixture": variant,
            "review_model": "isolated-input deterministic functions; six roles simulated locally",
            "scope_reason": "배송 경계 변경, 이전 결함 및 결제 경로의 선행 검사" if mode == "delta"
                            else "전체 합성 계획과 현장 실기기 능력 확인",
            "standards": [dict(edition=title, applied=applied, reason=reason)
                          for title, applied, reason in mappings]}


def regression_history(root, link, results, defects):
    if not link or not link["record_path"].endswith("/record.json"):
        return []
    prior = load(safe_file(root, link["record_path"]))
    outcomes = {r["check_id"]: r["status"] for r in results}
    current = {d["fingerprint"] for d in defects}
    history = []
    for defect in prior["defects"]:
        tested = {key: outcomes.get(key, "not_run") for key in defect["check_ids"]}
        if defect["fingerprint"] in current:
            state = "reobserved"
        elif all(status == "passed" for status in tested.values()):
            state = "passed_recheck"
        else:
            state = "inconclusive"
        history.append(dict(fingerprint=defect["fingerprint"], source_run=link["run_id"], source_defect=defect["id"],
                            checks=tested, state=state))
    return history


def run(args):
    need(args.round >= 1 and args.attempt >= 1, "회차와 시도 번호는 1 이상의 정수입니다.")
    root = args.store.resolve()
    root.mkdir(parents=True, exist_ok=True)
    link = None
    for kind, rel in [("correction", args.corrects), ("retry", args.retry), ("regression", args.previous)]:
        if rel:
            reason = args.reason if kind == "correction" else args.reason or ("합성 수정 후 회귀" if kind == "regression" else "동일 회차 재실행")
            link = predecessor(root, rel, kind, reason, args.round, args.attempt)
    need(args.round == 1 or link, "두 번째 이후 회차의 첫 시도에는 --previous가 필요합니다.")
    source = subject_bytes(args.fixture)
    if link and link["type"] in {"retry", "correction"}:
        old_input = safe_file(root, link["record_path"]).parent / "input.json"
        if old_input.exists():
            need(load(old_input)["revision"] == "sha256:" + digest(source),
                 "같은 회차의 합성 제품 리비전 변경은 불가합니다. 새 회차와 --previous를 사용하세요.")
    need(args.attempt == 1 or link, "새 attempt에는 --retry 또는 --corrects 원본 경로가 필요합니다.")
    need(link or not args.reason, "--reason은 원본 링크와 함께 사용합니다.")
    directory = safe_file(root, names(args.round, args.attempt))
    directory.parent.mkdir(exist_ok=True)
    directory.mkdir(exist_ok=False)  # Exactly one concurrent writer acquires the attempt.
    header = dict(run_id="itr-" + uuid.uuid4().hex, round=args.round, attempt=args.attempt,
                  created_at=now(), previous=link)
    fresh(directory / "reservation.json", encoded(header))
    try:
        frozen = plan(args.mode, source)
        subject = directory / "subject.py"
        context = run_context(args.mode, args.fixture)
        fresh(directory / "context.json", encoded(context))
        fresh(directory / "input.json", encoded(frozen))
        fresh(subject, source)
        (directory / "evidence").mkdir()
        (directory / "reviews").mkdir()
        journal = Journal(directory)
        checks = {row["id"]: row for row in frozen["checks"]}
        available = {c["id"] for c in frozen["capabilities"] if c["available"]}
        for key in checks:
            journal.emit(key, "queued", "고정된 검사 계획에 등록.")
        completed = {}
        # Release each ready layer. Role functions consume only their assigned check and the subject.
        # A dependent task waits for the preceding layer, including its separately sealed verdicts.
        with ThreadPoolExecutor(max_workers=6) as pool:
            while len(completed) < len(checks):
                ready = [c for key, c in checks.items() if key not in completed
                         and all(p in completed for p in c["depends_on"])]
                need(ready, "검사 의존성 순환")
                pending = {}
                for check in ready:
                    unmet = [c for c in check["requires"] if c not in available]
                    prereq_failed = any(completed[p][0]["status"] != "passed" for p in check["depends_on"])
                    pending[check["id"]] = pool.submit(execute, check, subject, journal, unmet, prereq_failed)
                completed.update({key: future.result() for key, future in pending.items()})
        outcomes = [completed[key] for key in checks]
        results = [r for r, _, _ in outcomes]
        state = gate(frozen["checks"], results)
        selected = Counter(r["status"] for r in results if checks[r["check_id"]]["selected"])
        reason = (f"선택한 검사 {sum(selected.values())}건 중 통과 {selected['passed']}, 실패 {selected['failed']}, "
                  f"차단 {selected['blocked']}, 미실행 {selected['not_run']}. "
                  "우선순위는 실패 → 차단 → 미실행 → 통과.")
        defects = findings(results, checks)
        history = regression_history(root, link, results, defects)
        record = {**header, "schema_version": "1.0", "input": frozen, "events": journal.events,
                  "results": results, "evidence": [e for _, e, _ in outcomes if e],
                  "defects": defects, "reviews": [v for _, _, v in outcomes if v],
                  "approval": {"status": "not_requested", "actor": None, "at": None},
                  "decision": {"status": state, "reason": reason},
                  "extensions": {**context, "regression": history}}
        schema_validate(record)
        data = encoded(record)
        fresh(directory / "record.json", data)
        fresh(directory / "COMPLETE.json", encoded({"sha256": digest(data)}))
    except BaseException as err:
        # Preserve partial evidence/reservation even on interrupted or failed serialization.
        fresh(directory / "interruption.json", encoded({"at": now(), "error": type(err).__name__, "detail": str(err)}))
        raise
    print(f"{record['created_at']} KST · {state} · {directory / 'record.json'}")
    return 3 if args.require_pass and state != "passed" else 0


def main():
    cli = argparse.ArgumentParser(description="ITR · 합성 영수증 QA / 로컬 기록 검증")
    sub = cli.add_subparsers(dest="command", required=True)
    runner = sub.add_parser("run", help="새 회차 또는 새 시도에 합성 검사를 기록")
    runner.add_argument("--store", type=Path, default=Path("itr-runs"))
    runner.add_argument("--round", type=int, required=True)
    runner.add_argument("--attempt", type=int, default=1)
    runner.add_argument("--mode", choices=["precision", "delta"], default="precision")
    runner.add_argument("--fixture", choices=["broken", "fixed"], default="broken")
    links = runner.add_mutually_exclusive_group()
    links.add_argument("--previous", help="회귀의 이전 회차 기록 (저장소 기준 상대 경로)")
    links.add_argument("--retry", help="같은 회차 원본 기록 또는 중단 시 reservation.json")
    links.add_argument("--corrects", help="정정할 같은 회차의 원본 record.json")
    runner.add_argument("--reason")
    runner.add_argument("--require-pass", action="store_true", help="선택 검사 게이트 미통과 시 종료 3")
    check = sub.add_parser("verify", help="로컬 데모 기록의 스키마·원본·증거·결함·게이트 검증")
    check.add_argument("record", type=Path)
    latest = sub.add_parser("latest", help="완결된 최신 로컬 기록 확인")
    latest.add_argument("--store", type=Path, default=Path("itr-runs"))
    args = cli.parse_args()
    if args.command == "run":
        return run(args)
    if args.command == "verify":
        record = verify(args.record.absolute())
        print(f"검증 통과 · {record['run_id']} · {record['created_at']} KST")
        return 0
    candidates = []
    for marker in args.store.glob("round-*/attempt-*/COMPLETE.json"):
        rd, att = marker.parent.parent.name[6:], marker.parent.name[8:]
        if rd.isdigit() and att.isdigit():
            candidates.append((int(rd), int(att), marker.parent / "record.json"))
    need(candidates, "완결된 기록이 없습니다.")
    path = max(candidates)[2].absolute()
    verify(path)
    print(path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ITR · {error}", file=sys.stderr)
        sys.exit(2)
