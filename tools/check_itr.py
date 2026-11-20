"""Exercise the local offline adapter only. All test stores are new temporary directories."""
import sys
sys.dont_write_bytecode = True

import json
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import itr
from itr_store import digest, encoded, load, names, verify


def expect(ok, why):
    if not ok:
        raise AssertionError(why)


def invoke(*args, expected=0):
    command = [sys.executable, "-B", str(Path(__file__).with_name("itr.py")), *map(str, args)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=30)
    if expected is not None:
        expect(result.returncode == expected, f"{args}\nexit {result.returncode}\n{result.stderr}")
    return result


def snapshot(directory):
    return {p.relative_to(directory).as_posix(): digest(p.read_bytes())
            for p in directory.rglob("*") if p.is_file()}


def passed(label):
    print("PASS · " + label)


def suite(root):
    store = root / "runs"
    def rel(r, a=1):
        return names(r, a) + "/record.json"
    def run(r, a=1, *flags, expected=0):
        return invoke("run", "--store", store, "--round", r, "--attempt", a, *flags, expected=expected)

    run(1, 1, "--fixture", "broken", "--require-pass", expected=3)
    first = verify(store / rel(1))
    statuses = {r["check_id"]: r["status"] for r in first["results"]}
    expect(set(statuses.values()) == {"passed", "failed", "blocked", "not_run"}, "네 상태")
    expect(statuses["bb-goal"] == "passed" and first["approval"]["status"] == "not_requested", "인수와 승인")
    expect(first["decision"]["status"] == "failed" and statuses["system-device"] == "blocked", "실패/차단")
    expect(statuses["link-ledger"] == "not_run", "선택적 장부")
    expect(len(first["reviews"]) == 6 and len(first["defects"]) == 1
           and len(first["defects"][0]["check_ids"]) == 2, "독립 검토와 결함 중복 제거")
    expect(len(first["extensions"]["standards"]) == 8, "적용 근거")
    passed("합성 제품 실제 검사 · 네 상태 · 역할 봉인 6건 · 같은 결함 관측 2건 통합 · 승인 분리")

    original = snapshot((store / rel(1)).parent)
    run(1, 1, expected=2)
    run(1, 2, "--corrects", rel(1), expected=2)
    run(1, 2, "--retry", rel(1), "--fixture", "fixed", expected=2)
    run(2, 1, "--fixture", "fixed", expected=2)
    expect(not (store / names(1, 2)).exists() and not (store / names(2, 1)).exists(), "예약 전 거부")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, 1, 2, "--retry", rel(1), expected=None) for _ in range(2)]
        codes = sorted(f.result().returncode for f in futures)
    expect(codes == [0, 2], f"동시 시도 {codes}")
    second_attempt = verify(store / rel(1, 2))
    expect(second_attempt["extensions"]["regression"][0]["state"] == "reobserved", "회귀 결함 재관찰")
    expect(original == snapshot((store / rel(1)).parent), "첫 시도 전체 바이트 보존")
    passed("동시 작성 2개 중 1개만 예약 · 충돌/정정 사유/리비전 변경 거부 · 첫 시도 전체 보존")

    run(2, 1, "--previous", rel(1, 2), "--fixture", "fixed")
    corrected_product = verify(store / rel(2))
    expect(corrected_product["decision"]["status"] == "blocked" and not corrected_product["defects"],
           "수정 이후에도 실기기 차단")
    tracking = corrected_product["extensions"]["regression"][0]
    expect(tracking["state"] == "passed_recheck" and set(tracking["checks"].values()) == {"passed"},
           "회귀 검사 통과 근거")
    before = snapshot((store / rel(2)).parent)
    run(2, 2, "--corrects", rel(2), "--reason", "변경 영향 범위를 정정", "--fixture", "fixed",
        "--mode", "delta", "--require-pass")
    delta = verify(store / rel(2, 2))
    expect(delta["decision"]["status"] == "passed" and any(r["status"] == "not_run" for r in delta["results"]),
           "선택된 검사만 통과")
    expect(delta["previous"]["reason"] == "변경 영향 범위를 정정"
           and delta["previous"]["sha256"] == digest((store / rel(2)).read_bytes()), "정정 원본 해시")
    expect(before == snapshot((store / rel(2)).parent) and original == snapshot((store / rel(1)).parent),
           "정정 전후 원본들 보존")
    expect(Path(invoke("latest", "--store", store).stdout.strip()) == store / rel(2, 2), "완결된 최신 기록")
    passed("회차 회귀 · 결함별 재검사 통과 · 잔여 차단 · 일상 범위 통과 · 정정 링크와 원본 해시")

    damaged = root / "damaged"
    shutil.copytree(store, damaged)
    evidence_path = damaged / names(1, 1) / first["evidence"][0]["path"]
    evidence_path.write_bytes(b"changed copy")
    invoke("verify", damaged / rel(1), expected=2)
    event_path = damaged / names(2, 1) / "events" / "0001.json"
    event = load(event_path)
    event["message"] += " altered"
    event_path.write_bytes(encoded(event))
    invoke("verify", damaged / rel(2), expected=2)
    expect(original == snapshot((store / rel(1)).parent), "손상 검사는 별도 복제본에서만 실행")
    passed("증거 바이트 변조 및 원본 이벤트 변경을 복제본에서 탐지")

    partial = root / "partial"
    flags = ["itr", "run", "--store", str(partial), "--round", "1"]
    # Inject a finalization error *after* execution to check durable evidence and retry behavior.
    with patch.object(sys, "argv", flags), patch.object(itr, "schema_validate", side_effect=ValueError("fixture interrupt")):
        try:
            itr.main()
        except ValueError as failure:
            expect(str(failure) == "fixture interrupt", "의도한 중단")
        else:
            raise AssertionError("중단이 발생해야 합니다.")
    aborted = partial / names(1, 1)
    expect((aborted / "interruption.json").exists() and not (aborted / "COMPLETE.json").exists(), "미완결 예약")
    expect(any((aborted / "evidence").iterdir()), "중단 이전 증거 지속성")
    invoke("latest", "--store", partial, expected=2)
    partial_snapshot = snapshot(aborted)
    invoke("run", "--store", partial, "--round", 1, "--attempt", 2, "--retry", names(1, 1) + "/reservation.json")
    verify(partial / rel(1, 2))
    expect(partial_snapshot == snapshot(aborted), "미완결 시도 보존")
    passed("완결 전 오류 주입 · 실패 기록/이미 생긴 증거 보존 · 최신 기록 제외 · 새 시도로 복구")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="itr-qa-") as isolated:
        suite(Path(isolated))
    print("ITR 로컬 합성 회귀 검사 완료.")
