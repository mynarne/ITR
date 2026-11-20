"""Exercise progress.py against an active local run, partial records and its output index."""
import argparse
import hashlib
import json
import subprocess
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(BASE / "tools"))
import itr
import progress


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def wait_for(func, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = func()
        if value:
            return value
        time.sleep(.02)
    raise AssertionError("저널 상태 대기 시간 초과")


def read_index(path):
    try:
        s = path.read_text(encoding="utf8")
        return json.loads(s[len("window.ITR_PROGRESS("):-3])
    except (FileNotFoundError, ValueError):
        return {}


def tree_hashes(path):
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob("*") if p.is_file()}


def run_args(root, rd, att, prev=None):
    return argparse.Namespace(store=root, round=rd, attempt=att, mode="precision", fixture="broken",
                              corrects=None, retry=None, previous=prev, reason=None, require_pass=False)


def check_project_skip(temp):
    """An actual project child can launch and then explicitly skip with code 77."""
    source, store, out = (temp / name for name in ("skip-project", "skip-records", "skip-view"))
    shutil.copytree(BASE / "examples" / "project", source)
    plan_path = source / "plan.json"
    plan = json.loads(plan_path.read_bytes())
    check = dict(plan["input"]["checks"][0], id="explicit-skip", title="명시적 미실행")
    plan["input"]["checks"] = [check]
    plan["commands"] = {check["id"]: {"argv": ["{python}", "-I", "-B", "-c",
                          "import sys,time; time.sleep(0.8); print('SKIP_OBSERVED'); sys.exit(77)"]}}
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf8")
    cli = [sys.executable, "-B", str(BASE / "tools" / "project.py")]
    target = ["--workspace", str(source), "--plan", str(plan_path)]
    approval = json.loads(subprocess.check_output(cli + ["inspect", *target]))["approval_sha256"]
    watcher = subprocess.Popen([sys.executable, "-B", str(BASE / "tools" / "progress.py"),
                                "--store", str(store), "--out", str(out), "--watch", "--interval", ".02"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        index = out / "progress.index.js"
        wait_for(lambda: read_index(index).get("phase") == "waiting")
        with subprocess.Popen(cli + ["run", *target, "--approve", approval, "--round", "1",
                                     "--store", str(store), "--require-pass"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as writer:
            wait_for(lambda: read_index(index).get("states", {}).get("explicit-skip") == "running"
                     and read_index(index).get("phase") == "live")
            writer.communicate(timeout=12)
            require(writer.returncode == 3, "미실행 게이트가 통과하면 안 됩니다.")
        wait_for(lambda: read_index(index).get("phase") == "sealed")
        v = read_index(index)
        directory = store / "round-0001" / "attempt-0001"
        record = json.loads((directory / "record.json").read_bytes())
        subprocess.run(cli + ["verify", str(directory / "record.json")], capture_output=True, check=True)
        states = [event["state"] for event in record["events"]]
        require(states == ["queued", "running", "not_run"], "종료 77의 원본 저널 전이")
        require(v["decision"] == "not_run" and v["states"] == {"explicit-skip": "not_run"}
                and v["defects"] == 0 and (out / v["report"]).is_file(), "종료 77의 봉인·보고서 불일치")
        evidence = record["evidence"][0]
        data = (directory / evidence["path"]).read_bytes()
        proof = json.loads(data)
        require(hashlib.sha256(data).hexdigest() == evidence["sha256"]
                and record["results"][0]["evidence_ids"] == [evidence["id"]]
                and proof["exit_code"] == 77 and proof["status"] == "not_run"
                and "SKIP_OBSERVED" in proof["stdout"], "종료 77의 증거 또는 관찰값 불일치")
        return {"project_skip_exit": proof["exit_code"], "project_skip_events": states,
                "project_skip_observed_live": True, "project_skip_phase": v["phase"],
                "project_skip_gate": v["decision"], "project_skip_evidence_hash_verified": True}
    finally:
        watcher.terminate()
        watcher.communicate(timeout=8)


def main():
    with tempfile.TemporaryDirectory(prefix="itr-progress-") as tmp:
        temp = Path(tmp); store, out = temp/"records", temp/"view"
        script = BASE/"tools"/"progress.py"
        command = [sys.executable, "-B", str(script), "--store", str(store), "--out", str(out)]
        watch = subprocess.Popen(command + ["--watch", "--interval", ".02"], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.PIPE, text=True)
        index = out/"progress.index.js"
        def until(predicate):
            def next_projection():
                v = read_index(index)
                return v if v and predicate(v) else None
            return wait_for(next_projection)
        try:
            until(lambda v: v["phase"] == "waiting")
            # Hold the three actual independent inspection jobs in the adapter until the watcher sees them.
            original = itr.observe
            release = threading.Event()
            def observed(key, subject):
                if key in {"wb-logic", "wb-contract", "wb-config"}:
                    require(release.wait(10), "병렬 관찰 테스트의 제한 시간 초과")
                return original(key, subject)
            with patch.object(itr, "observe", observed), ThreadPoolExecutor(max_workers=1) as pool:
                writer = pool.submit(itr.run, run_args(store, 1, 1))
                try:
                    active = until(lambda v: v["phase"]=="live" and
                                   sum(s=="running" for s in v["states"].values()) >= 3)
                    require(active["defects"] is None and active["decision"] is None and
                            all(k not in active for k in ("evidence","reviews","results","report","message")),
                            "첫 판정 또는 전역 결함 조기 공개")
                    require("cause_confirmed" not in index.read_text(), "원인이 색인에 노출됨")
                    stale = progress.snapshot(store, stale_after=0)
                    require(stale["phase"]=="unconfirmed" and stale["decision"] is None,
                            "최근 갱신 없는 미완결 시도의 지속 여부가 미확인이어야 함")
                finally:
                    release.set()
                require(writer.result(timeout=12)==0,"실행 생성 실패")
            final = until(lambda v: v["phase"]=="sealed")
            require(final["decision"]=="failed" and final["defects"]==1 and (out/final["report"]).is_file(),
                    "봉인된 결함 또는 보고서 불일치")
            first = store/"round-0001"/"attempt-0001"; old = tree_hashes(first)
            # A normal adapter exception yields the producer's own interruption marker and no COMPLETE.
            actual = itr.observe
            def stop_adapter(key, subject):
                if key=="unit-subtotal":
                    raise RuntimeError("합성 중단 시험")
                return actual(key, subject)
            with patch.object(itr, "observe", stop_adapter):
                try:
                    itr.run(run_args(store, 2, 1, "round-0001/attempt-0001/record.json"))
                    raise AssertionError("중단되지 않은 합성 어댑터")
                except RuntimeError:
                    pass
            aborted = until(lambda v: v["phase"]=="interrupted" and v["round"]==2)
            require(aborted["decision"] is None and aborted["defects"] is None and "report" not in aborted,
                    "미완결 시도가 통과로 표시됨")
            require(tree_hashes(first)==old,"관찰 중 원본 변경")
            args = run_args(store, 2, 2)
            args.retry="round-0002/attempt-0001/reservation.json"
            itr.run(args)
            retried = until(lambda v: v["phase"]=="sealed" and v["round"]==2 and v["attempt"]==2)
            require(retried["report"]!=final["report"] and (out/final["report"]).exists(),
                    "재시도로 첫 화면이 덮어써짐")
            retry_record = json.loads((store/"round-0002"/"attempt-0002"/"record.json").read_bytes())
            require(retried["seq"]==len(retry_record["events"]),"합성 원본과 관찰 이벤트 수 불일치")
            collision = subprocess.run(command + ["--once"], capture_output=True)
            require(collision.returncode!=0,"화면 폴더 충돌 거부 실패")
            sealed = store/"round-0002"/"attempt-0002"
            before = tree_hashes(sealed)
            require(subprocess.run([sys.executable,"-B",str(script),"--store",str(store),"--once","--json"],
                                   capture_output=True).returncode==0,"1회 CLI 조회 실패")
            require(before==tree_hashes(sealed),"조회가 봉인된 시도를 변경")
            skip = check_project_skip(temp)
            print(json.dumps({**skip, "real_writer":True,"concurrent_running":sum(s=="running" for s in active["states"].values()),
                              "terminal_events":retried["seq"],"deduplicated_defects":final["defects"],
                              "stale_unconfirmed":True,"interruption_and_retry":True,"preserved_prior_attempt":True,
                              "final_report_link":True,"output_collision_refused":True}, ensure_ascii=False))
        finally:
            watch.terminate()
            watch.communicate(timeout=8)


if __name__ == "__main__":
    main()
