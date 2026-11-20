"""Run release-candidate project adapter checks on disposable synthetic files only."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

PACKAGE = Path(__file__).resolve().parents[1]
CLI = [sys.executable, "-B", str(PACKAGE / "tools" / "project.py")]
EXAMPLE = PACKAGE / "examples" / "project"
FIRST = "round-0001/attempt-0001/record.json"
RETRY = "round-0001/attempt-0002/record.json"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def json_file(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def tree_bytes(folder):
    return {p.relative_to(folder).as_posix(): checksum(p.read_bytes())
            for p in folder.rglob("*") if p.is_file()}


def cli(args, expected=0):
    # Simulate a legacy parent console without changing the caller's global environment.
    env = {**os.environ, "PYTHONIOENCODING": "cp949", "PYTHONUTF8": "0",
           "ITR_TEST_PARENT_ONLY": "synthetic-parent-value"}
    result = subprocess.run(CLI + list(map(str, args)), encoding="utf-8", env=env,
                            capture_output=True, timeout=45)
    if expected is not None and result.returncode != expected:
        # The published report only needs the operation and code, not local paths/output.
        raise AssertionError(f"{args[0]} produced {result.returncode}, expected {expected}")
    return result


def inspect(workspace, plan):
    data = json.loads(cli(["inspect", "--workspace", workspace, "--plan", plan]).stdout)
    value = data["approval_sha256"]
    require(isinstance(value, str) and len(value) == 64, "inspect approval_sha256")
    return value


def run_args(workspace, plan, store, approved, *rest, round_no=1, attempt=1):
    return ["run", "--workspace", workspace, "--plan", plan, "--approve", approved,
            "--store", store, "--round", round_no, "--attempt", attempt, *rest]


def result_map(record):
    return {item["check_id"]: item["status"] for item in record["results"]}


def verified(path):
    cli(["verify", path])
    record = json_file(path)
    require(record["approval"]["status"] == "not_requested", "separate stakeholder approval")
    for proof in record["evidence"]:
        require(checksum((path.parent / proof["path"]).read_bytes()) == proof["sha256"],
                "independently computed evidence hash")
    return record


def pass_and_approval(root, workspace):
    plan = workspace / "plan.json"
    store = root / "basic-store"
    before = tree_bytes(workspace)
    approved = inspect(workspace, plan)
    cli(run_args(workspace, plan, store, approved, "--require-pass"))
    record = verified(store / FIRST)
    require(result_map(record) == {"stock-ready": "passed", "stock-low": "passed"}, "quickstart statuses")
    require(record["decision"]["status"] == "passed" and record["defects"] == [], "quickstart decision")
    for proof in record["evidence"]:
        output = json_file((store / FIRST).parent / proof["path"])
        marker = json_file(plan)["commands"][proof["check_id"]]["pass_marker"]
        require(output["pass_marker"] == marker and output["pass_marker_seen"] is True and
                marker in output["stdout"], "positive observation matches approved marker")
    require(tree_bytes(workspace) == before, "project checkout unchanged")
    print("PASS 01 · 일반 어댑터로 프로젝트 소유 검사 2개 실행, 기록·증거 검증")

    stale = root / "stale-approval"
    copy_path = workspace / "inventory.py"
    original = copy_path.read_bytes()
    copy_path.write_bytes(original + b"\n# synthetic source change\n")
    try:
        require(inspect(workspace, plan) != approved, "source change modifies approval")
        cli(run_args(workspace, plan, stale, approved), expected=2)
    finally:
        copy_path.write_bytes(original)
    plan_bytes = plan.read_bytes()
    plan.write_bytes(plan_bytes + b"\n")
    try:
        require(inspect(workspace, plan) != approved, "plan bytes modify approval")
        cli(run_args(workspace, plan, stale, approved), expected=2)
    finally:
        plan.write_bytes(plan_bytes)
    require(not (stale / FIRST).parent.exists(), "approval mismatch before reservation")
    require(inspect(workspace, plan) == approved, "restored approval")
    print("PASS 02 · 검토 뒤 소스 또는 계획 변경 시 과거 승인 거부")


def failure_and_history(root, workspace):
    store = root / "defect-store"
    plan = workspace / "plan-defect.json"
    approved = inspect(workspace, plan)
    cli(run_args(workspace, plan, store, approved, "--require-pass"), expected=3)
    path = store / FIRST
    first = verified(path)
    statuses = result_map(first)
    require(statuses == {"stock-ready": "passed", "stock-low": "passed", "stock-zero": "failed"},
            "expected synthetic zero-stock defect")
    defect, = first["defects"]
    require(defect["fingerprint"] == "inventory.zero.label" and defect["check_ids"] == ["stock-zero"],
            "stable defect id and failed observation")
    evidence = {item["id"]: item for item in first["evidence"]}
    payload = "\n".join((path.parent / evidence[key]["path"]).read_text(encoding="utf-8")
                        for key in defect["evidence_ids"])
    require("expected=empty actual=low" in payload, "failed check contains real CLI evidence")
    snapshot = tree_bytes(path.parent)
    print("PASS 03 · 빈 재고 경계 실패, 원래 CLI 출력과 fingerprint 연결")

    arguments = run_args(workspace, plan, store, approved, "--retry", FIRST, attempt=2)
    with ThreadPoolExecutor(max_workers=2) as workers:
        tasks = [workers.submit(cli, arguments, expected=None) for _ in range(2)]
        codes = sorted(task.result().returncode for task in tasks)
    require(codes == [0, 2], "concurrent retry has exactly one winner")
    second = verified(store / RETRY)
    require(second["previous"]["type"] == "retry" and
            second["previous"]["sha256"] == checksum(path.read_bytes()), "retry predecessor bytes")
    require(tree_bytes(path.parent) == snapshot, "first attempt preserved after concurrent retry")
    correction = run_args(workspace, plan, store, approved, "--corrects", RETRY, attempt=3)
    cli(correction, expected=2)
    require(not (store / "round-0001/attempt-0003").exists(), "correction requires reason before reservation")
    correction_reason = "합성 결함 근거를 새 시도에서 재확인"
    cli(correction + ["--reason", correction_reason])
    corrected = verified(store / "round-0001/attempt-0003/record.json")
    require(corrected["previous"]["type"] == "correction" and
            corrected["previous"]["reason"] == correction_reason and
            corrected["previous"]["sha256"] == checksum((store / RETRY).read_bytes()),
            "correction preserves original link and reason")
    print("PASS 04 · 동시 재시도 중 1개만 예약, 사유 없는 정정 거부, 정정 원본 해시 보존")

    damaged = root / "tampered-copy"
    shutil.copytree(store, damaged)
    for key in defect["evidence_ids"][:1]:
        item = (damaged / FIRST).parent / evidence[key]["path"]
        item.write_bytes(item.read_bytes() + b"\nchanged-copy\n")
    cli(["verify", damaged / FIRST], expected=2)
    require(tree_bytes(path.parent) == snapshot, "tamper test changed only the isolated copy")
    print("PASS 05 · 별도 사본의 증거 1개 변조 시 verify 거부")

    source = workspace / "inventory.py"
    original, old_plan = source.read_bytes(), plan.read_bytes()
    try:
        require(b"remaining < 0:" in original, "known synthetic defect")
        source.write_bytes(original.replace(b"remaining < 0:", b"remaining <= 0:"))
        next_plan = json_file(plan)
        next_plan["input"]["revision"] = "inventory-demo-2"
        save(plan, next_plan)
        corrected = inspect(workspace, plan)
        cli(run_args(workspace, plan, store, corrected, "--previous", RETRY, "--require-pass", round_no=2))
        next_record = verified(store / "round-0002/attempt-0001/record.json")
        require(next_record["decision"]["status"] == "passed" and
                result_map(next_record)["stock-zero"] == "passed" and not next_record["defects"],
                "fixed boundary passes its previous regression")
        require(any(item["fingerprint"] == defect["fingerprint"] and item["state"] == "passed_recheck"
                    for item in next_record["extensions"]["regression"]), "per-defect regression history")
        require(next_record["previous"]["sha256"] == checksum((store / RETRY).read_bytes()),
                "new round preserves prior hash")
    finally:
        source.write_bytes(original)
        plan.write_bytes(old_plan)
    require(tree_bytes(path.parent) == snapshot, "first round preserved after fixing synthetic copy")
    print("PASS 06 · 사본에서 경계값 수정 후 새 회차 회귀 통과, 이전 실패 검증 가능")


def derived_check(template, key, **changes):
    item = copy.deepcopy(template)
    item.update(id=key, title=key, depends_on=[], **changes)
    return item


def capability_and_timeout(root, workspace):
    plan = json_file(workspace / "plan.json")
    template = plan["input"]["checks"][0]
    plan["input"]["checks"] = [
        derived_check(template, "device", requires=["synthetic.offline.device"]),
        derived_check(template, "omitted", selected=False),
        derived_check(template, "no-command"),
        derived_check(template, "explicit-skip"),
        derived_check(template, "timed-out"),
    ]
    plan["input"]["capabilities"].append({"id": "synthetic.offline.device", "available": True})
    plan["commands"] = {
        "device": {"argv": ["{python}", "-I", "-B", "checks.py", "regular"]},
        "omitted": {"argv": ["{python}", "-I", "-B", "checks.py", "regular"]},
        "explicit-skip": {"argv": ["{python}", "-I", "-B", "-c", "raise SystemExit(77)"]},
        "timed-out": {"argv": ["{python}", "-I", "-B", "-c", "import time; time.sleep(2)"], "timeout_s": 0.15},
    }
    path = workspace / "qa-states.json"
    save(path, plan)
    store = root / "state-store"
    cli(run_args(workspace, path, store, inspect(workspace, path), "--require-pass"), expected=3)
    record = verified(store / FIRST)
    require(result_map(record) == {"device": "blocked", "omitted": "not_run", "no-command": "not_run",
                                   "explicit-skip": "not_run", "timed-out": "blocked"},
            "unsupported, deselected, unmapped, runner skip and timeout")
    require(record["decision"]["status"] == "blocked" and not record["defects"], "incomplete work kept distinct")
    print("PASS 07 · 미지원 능력 및 시간 초과 차단, 범위 제외·명령 누락·종료 77 미실행")


def absent_positive_observation(root, workspace):
    plan = json_file(workspace / "plan.json")
    template = plan["input"]["checks"][0]
    marker = plan["commands"][template["id"]]["pass_marker"]
    snippets = {
        "empty-output": "pass",
        "unrelated-output": "print('0 tests discovered')",
        "stderr-only": "import sys; print(" + repr(marker) + ", file=sys.stderr)",
    }
    plan["input"]["checks"] = [derived_check(template, key) for key in snippets]
    plan["commands"] = {
        key: {"argv": ["{python}", "-I", "-B", "-c", script], "pass_marker": marker}
        for key, script in snippets.items()
    }
    path = workspace / "qa-witness.json"
    save(path, plan)
    store = root / "witness-store"
    cli(run_args(workspace, path, store, inspect(workspace, path), "--require-pass"), expected=3)
    first = store / FIRST
    record = verified(first)
    require(result_map(record) == {key: "blocked" for key in snippets},
            "empty, unrelated or stderr-only output cannot satisfy the approved stdout condition")
    require(len(record["evidence"]) == len(snippets), "recorded each outcome")
    for proof in record["evidence"]:
        observation = json_file(first.parent / proof["path"])
        require(observation["exit_code"] == 0 and observation["pass_marker_seen"] is False and
                observation["pass_marker"] == marker and marker not in observation["stdout"],
                "successful exit remains blocked without the approved stdout observation")
    print("PASS 09 · 종료 0이어도 stdout이 비거나 무관하거나 마커가 stderr에만 있으면 차단")


def interrupt_and_retry(root, workspace):
    plan = json_file(workspace / "plan.json")
    keep = plan["input"]["checks"][0]
    pending = derived_check(keep, "pause-after-pass")
    pending["depends_on"] = [keep["id"]]
    plan["input"]["checks"] = [keep, pending]
    plan["commands"] = {keep["id"]: plan["commands"][keep["id"]],
                        pending["id"]: {"argv": ["{python}", "-I", "-B", "-c",
                                                 "import time; time.sleep(2)"], "timeout_s": 6}}
    path = workspace / "qa-interrupt.json"
    save(path, plan)
    store = root / "interrupted-store"
    approval = inspect(workspace, path)
    args = list(map(str, run_args(workspace, path, store, approval)))
    process = subprocess.Popen(CLI + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    directory = (store / FIRST).parent
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            events = []
            for event_path in (directory / "events").glob("*.json"):
                try:
                    events.append(json_file(event_path))
                except (ValueError, OSError):
                    continue
            if any(e["check_id"] == pending["id"] and e["state"] == "running" for e in events):
                break
            time.sleep(0.02)
        else:
            raise AssertionError("timeout waiting for durable running transition")
        require(process.poll() is None, "process is still running at interruption")
        process.terminate()
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    require(not (directory / "COMPLETE.json").exists() and (directory / "reservation.json").is_file(),
            "interrupt preserves unsealed reservation")
    require(any((directory / "evidence").rglob("*")), "evidence gathered before interruption survives")
    snapshot = tree_bytes(directory)
    cli(run_args(workspace, path, store, approval, "--retry",
                 "round-0001/attempt-0001/reservation.json", "--require-pass", attempt=2))
    fresh = verified(store / RETRY)
    require(fresh["previous"]["sha256"] == checksum((directory / "reservation.json").read_bytes()),
            "retry linked to partial original")
    require(tree_bytes(directory) == snapshot, "partial attempt unchanged")
    print("PASS 08 · 실행 중 실제 프로세스 중단, 이전 증거·예약 보존 후 새 attempt로 완료")


def output_and_environment(root, workspace):
    plan = json_file(workspace / "plan.json")
    template = plan["input"]["checks"][0]
    korean = "완료 검증"
    scripts = {
        "utf8-isolated": ("import os,tempfile,pathlib; t=pathlib.Path(tempfile.gettempdir()); "
                          "assert t.name=='temp' and t.parent==pathlib.Path.cwd().parent; "
                          "assert all(k not in os.environ for k in "
                          "('ITR_TEST_PARENT_ONLY','USERPROFILE','APPDATA')); "
                          "(t/'sample.txt').write_text('temp'); print(" + repr(korean) + ")", None),
        "boundary": ("import sys; sys.stdout.buffer.write(b'x'*65535+" + repr(korean)
                     + ".encode()); sys.stderr.buffer.write(b'z'*90000)", None),
        "late-cp949": ("import sys; sys.stdout.buffer.write(b'x'*90000+" + repr(korean)
                       + ".encode('cp949')); sys.stderr.buffer.write('보조 출력'.encode('cp949'))", "cp949"),
        "wrong-codec": ("import sys; sys.stdout.buffer.write(" + repr(korean) + ".encode('cp949'))", None),
    }
    plan["input"]["checks"] = [derived_check(template, key) for key in scripts]
    plan["commands"] = {}
    for key, (script, encoding) in scripts.items():
        command = {"argv": ["{python}", "-I", "-B", "-c", script], "pass_marker": korean}
        if encoding:
            command["output_encoding"] = encoding
        plan["commands"][key] = command
    path = workspace / "qa-output.json"
    save(path, plan)
    store = root / "capture"
    approval = inspect(workspace, path)
    cli(run_args(workspace, path, store, approval, "--require-pass"), expected=3)
    record_path = store / FIRST
    record = verified(record_path)
    observed = {proof["check_id"]: json_file(record_path.parent / proof["path"]) for proof in record["evidence"]}
    require(result_map(record) == {"utf8-isolated": "passed", "boundary": "passed",
                                   "late-cp949": "passed", "wrong-codec": "blocked"}, "encoding and capture gates")
    require(korean in observed["utf8-isolated"]["stdout"], "isolated interpreter must emit UTF-8")
    argv = {key: plan["commands"][key]["argv"] for key in ("utf8-isolated", "late-cp949")}
    executable = str(Path(sys.executable).resolve())
    require(observed["utf8-isolated"]["launch_argv"] == [executable, "-X", "utf8", *argv["utf8-isolated"][1:]]
            and observed["late-cp949"]["launch_argv"] == [executable, *argv["late-cp949"][1:]],
            "launch argv must show the actual executable and flags")
    for key, offset, encoding in (("boundary", 65535, "utf-8"), ("late-cp949", 90000, "cp949")):
        output = observed[key]
        require(output["output_encoding"] == encoding and output["stdout_truncated"] is True
                and len(output["stdout"]) <= 65536 and "\ufffd" not in output["stdout"]
                and output["stdout_marker_excerpt"] == {"text": korean, "offset_chars": offset},
                "bounded prefix and observed late marker")
    require(observed["boundary"]["stderr_truncated"] and observed["boundary"]["stderr_bytes"] == 90000
            and observed["late-cp949"]["stderr"] == "보조 출력"
            and not observed["wrong-codec"]["pass_marker_seen"], "both pipes drained using the approved encoding")
    # A changed excerpt fails both raw integrity and a recomputed-but-inconsistent record.
    tampered = root / "capture-tampered"
    shutil.copytree(store, tampered)
    tampered_record = tampered / FIRST
    entry = next(e for e in record["evidence"] if e["check_id"] == "boundary")
    evidence_path = tampered_record.parent / entry["path"]
    changed = observed["boundary"]
    changed["stdout_marker_excerpt"]["offset_chars"] = 0
    save(evidence_path, changed)
    cli(["verify", tampered_record], expected=2)
    entry["sha256"] = checksum(evidence_path.read_bytes())
    save(tampered_record, record)
    save(tampered_record.parent / "COMPLETE.json", {"sha256": checksum(tampered_record.read_bytes())})
    cli(["verify", tampered_record], expected=2)
    print("PASS 10 · 자식 I/O 인코딩 4건, 임시 환경 격리, 긴 이중 출력 및 발췌 증거 검증")


def render_check(record, out, label):
    before = tree_bytes(record.parent)
    subprocess.run([sys.executable, "-B", str(PACKAGE / "views" / "render.py"), str(record), "--out", str(out)],
                   capture_output=True, check=True, timeout=30)
    require(all(label in (out / name).read_text(encoding="utf-8")
                for name in ("report.md", "print.html", "replay.html")), "reports must explain launch metadata")
    require(tree_bytes(record.parent) == before, "render and verify must leave original attempt bytes unchanged")


def evidence_versions(root, workspace):
    # The bundled RC.1 record already predates evidence versioning.
    legacy = PACKAGE / "examples" / "project-runs" / FIRST
    before = tree_bytes(legacy.parent)
    require("실제 실행 인수 미기록" in cli(["verify", legacy]).stdout, "legacy verify must label missing launch data")
    render_check(legacy, root / "legacy-report", "기존 증거 · 실제 실행 인수 미기록")
    require(tree_bytes(legacy.parent) == before, "legacy files unchanged")

    good = root / "basic-store" / FIRST
    require("증거 2.0" in cli(["verify", good]).stdout, "new record uses evidence 2.0")
    render_check(good, root / "new-report", "증거 2.0 · 프로세스 호출 인수 기록")
    partial = root / "missing-launch-field"
    shutil.copytree(good.parent.parent.parent, partial)
    record_path = partial / FIRST
    record = json_file(record_path)
    first = record["evidence"][0]
    evidence = record_path.parent / first["path"]
    incomplete = json_file(evidence)
    del incomplete["launch_argv"]
    save(evidence, incomplete)
    first["sha256"] = checksum(evidence.read_bytes())
    save(record_path, record)
    save(record_path.parent / "COMPLETE.json", {"sha256": checksum(record_path.read_bytes())})
    result = cli(["verify", record_path], expected=2)
    require("필수 키 누락" in result.stderr and "launch_argv" in result.stderr,
            "new evidence schema must reject a missing required field")

    plan = json_file(workspace / "plan.json")
    check = plan["input"]["checks"][0]
    plan["input"]["checks"] = [check]
    plan["commands"] = {check["id"]: {"argv": ["itr-synthetic-missing-executable"]}}
    path = workspace / "qa-pre-launch.json"
    save(path, plan)
    store = root / "pre-launch"
    approved = inspect(workspace, path)
    cli(run_args(workspace, path, store, approved, "--require-pass"), expected=3)
    blocked = store / FIRST
    result = verified(blocked)
    proof = json_file(blocked.parent / result["evidence"][0]["path"])
    require(proof["evidence_schema_version"] == "2.0" and proof["launch_argv"] is None
            and proof["status"] == "blocked" and proof["exit_code"] is None, "blocked before process launch")
    render_check(blocked, root / "pre-launch-report", "증거 2.0 · 프로세스 호출 전 차단")
    print("PASS 11 · 레거시와 증거 2.0을 재검증·재보고, 필수 키 누락 거부, 호출 전 차단 보존")


def main():
    with tempfile.TemporaryDirectory(prefix="itr-project-qa-") as folder:
        root = Path(folder)
        workspace = root / "project"
        shutil.copytree(EXAMPLE, workspace)
        pass_and_approval(root, workspace)
        failure_and_history(root, workspace)
        capability_and_timeout(root, workspace)
        interrupt_and_retry(root, workspace)
        absent_positive_observation(root, workspace)
        output_and_environment(root, workspace)
        evidence_versions(root, workspace)


if __name__ == "__main__":
    main()
