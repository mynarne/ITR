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


def stable(value):
    return checksum(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                               separators=(",", ":")).encode("utf-8"))


def strings(value):
    if isinstance(value, dict):
        return [s for item in value.values() for s in strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in strings(item)]
    return [value] if isinstance(value, str) else []


def rewrite_copy(record_path, target, mutate, version=None):
    """Copy a sealed store, edit every evidence file and recompute all hashes so only the contract can reject it."""
    shutil.copytree(record_path.parent.parent.parent, target)
    path = target / FIRST
    folder, record = path.parent, json_file(path)
    for entry in record["evidence"]:
        evidence = folder / entry["path"]
        observation = json_file(evidence)
        if version:
            observation["evidence_schema_version"] = version
        mutate(observation)
        save(evidence, observation)
        entry["sha256"] = checksum(evidence.read_bytes())
    if version:
        approval = json_file(folder / "approval.json")
        approval.pop("approval_sha256")
        approval["evidence_schema_version"] = version
        approval = {"approval_sha256": stable(approval), **approval}
        save(folder / "approval.json", approval)
        reservation = json_file(folder / "reservation.json")
        reservation["approval_sha256"] = approval["approval_sha256"]
        save(folder / "reservation.json", reservation)
        record["extensions"].update(approval_sha256=approval["approval_sha256"], evidence_schema_version=version)
    save(path, record)
    save(folder / "COMPLETE.json", {"sha256": checksum(path.read_bytes())})
    return path


def absolute_launch_path(observation):
    observation["launch_argv"][0] = str(Path(sys.executable).resolve())


def as_evidence_20_with_hash(observation):
    as_evidence_20(observation)
    observation["launch_executable_sha256"] = "0" * 64


def as_evidence_20(observation):
    # Published evidence 2.0 stored the resolved executable path and had no separate path hash.
    observation.pop("launch_executable_sha256")
    if observation["launch_argv"] is not None:
        absolute_launch_path(observation)


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
    path_hash = checksum(executable.encode("utf-8", "surrogatepass"))
    require(observed["utf8-isolated"]["launch_argv"] == ["{python}", "-X", "utf8", *argv["utf8-isolated"][1:]]
            and observed["late-cp949"]["launch_argv"] == argv["late-cp949"]
            and all(o["launch_executable_sha256"] == path_hash for o in observed.values()),
            "launch argv must show flags and bind the resolved executable by hash only")
    require(not any(executable in s for o in observed.values() for s in strings(o)),
            "shared evidence must not contain the resolved executable path")
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
    require("증거 2.1" in cli(["verify", good]).stdout, "new record uses evidence 2.1")
    render_check(good, root / "new-report", "증거 2.1 · 프로세스 호출 인수 기록")
    leaked = rewrite_copy(good, root / "absolute-path-in-2.1", absolute_launch_path)
    require("실제 실행 인수 기록 불일치" in cli(["verify", leaked], expected=2).stderr,
            "evidence 2.1 must reject an absolute executable path")
    published = rewrite_copy(good, root / "evidence-2.0", as_evidence_20, version="2.0")
    require("증거 2.0" in cli(["verify", published]).stdout, "evidence 2.0 records keep their original rules")
    render_check(published, root / "evidence-2.0-report", "증거 2.0 · 프로세스 호출 인수 기록")
    mixed = rewrite_copy(good, root / "evidence-2.0-with-2.1-field", as_evidence_20_with_hash, version="2.0")
    require("2.1 전용" in cli(["verify", mixed], expected=2).stderr, "evidence 2.0 must not carry the 2.1 path hash")
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
    require(proof["evidence_schema_version"] == "2.1" and proof["launch_argv"] is None
            and proof["launch_executable_sha256"] is None
            and proof["status"] == "blocked" and proof["exit_code"] is None, "blocked before process launch")
    render_check(blocked, root / "pre-launch-report", "증거 2.1 · 프로세스 호출 전 차단")
    print("PASS 11 · 레거시·증거 2.0·2.1 재검증·재보고, 2.1 절대 경로와 필수 키 누락 거부, 호출 전 차단 보존")



def standards_mapping(root, workspace):
    """Plan 1.1: each check names the standards that fit its purpose; uncovered catalog items stay visible."""
    plan = json_file(workspace / "plan.json")
    ux = {"ref": "ISO/IEC 25010:2023", "items": ["interaction_capability.operability"]}

    def legacy(p):
        p["adapter_version"] = "1.0"

    def untagged(p):
        del p["input"]["checks"][0]["standards"]

    def no_technique(p):
        p["input"]["checks"][0]["standards"] = p["input"]["checks"][0]["standards"][:1]

    def no_model(p):
        p["input"]["checks"][0]["standards"] = p["input"]["checks"][0]["standards"][1:]

    def unknown_item(p):
        p["input"]["checks"][0]["standards"][0]["items"] = ["functional_suitability.speed"]

    def not_applied(p):
        p["input"]["checks"][0]["standards"].append({"ref": "ISO/IEC 25019:2023", "items": ["beneficialness.suitability"]})

    def unused(p):
        p["standards"].append({"edition": "ISO/IEC 25012:2008", "applied": True, "reason": "데이터 품질 검사 예정"})

    def part_items(p):
        p["standards"].append({"edition": "ISO 9241-171:2025", "applied": True, "reason": "접근성"})
        p["input"]["checks"][0]["standards"].append({"ref": "ISO 9241-171:2025", "items": ["principle.keyboard"]})

    def ux_without_9241(p):
        p["input"]["checks"][0]["standards"][0] = ux

    def acceptance_without_context(p):
        p["input"]["checks"][0]["stage"] = "acceptance"

    def invented_9241(p):
        p["standards"].append({"edition": "ISO 9241-999:1900", "applied": True, "reason": "없는 부"})
        p["input"]["checks"][0]["standards"][0] = ux
        p["input"]["checks"][0]["standards"].append({"ref": "ISO 9241-999:1900", "items": []})

    def applied_only_on_deferred(p):
        for s in p["standards"]:
            if s["edition"] == "ISO/IEC 20246:2017":
                s.update(applied=True, reason="인스펙션 예정")
        deferred = dict(p["input"]["checks"][0], id="deferred-review", title="보류 인스펙션", method="inspection",
                        selected=False, standards=[p["input"]["checks"][0]["standards"][0],
                                                   {"ref": "ISO/IEC 20246:2017", "items": ["review_type.inspection"]}])
        p["input"]["checks"].append(deferred)

    def item_with_newline(p):
        p["standards"].append({"edition": "EXT-SAFETY-1", "applied": True, "reason": "분야 표준"})
        p["input"]["checks"][0]["standards"].append({"ref": "EXT-SAFETY-1", "items": ["hazard\n"]})

    cases = [(legacy, "1.1"), (untagged, "적용 표준"), (no_technique, "29119-4"), (no_model, "품질 모델"),
             (unknown_item, "항목 오류"), (not_applied, "적용하지 않은 표준"), (unused, "연결된 검사가 없습니다"),
             (part_items, "부 단위"), (ux_without_9241, "ISO 9241"), (acceptance_without_context, "인수·사용 맥락"),
             (invented_9241, "ISO 9241"), (applied_only_on_deferred, "연결된 검사가 없습니다"),
             (item_with_newline, "항목 이름 형식")]
    for change, message in cases:
        trial = copy.deepcopy(plan)
        change(trial)
        trial_path = workspace / f"qa-standards-{change.__name__}.json"
        save(trial_path, trial)
        result = cli(["inspect", "--workspace", workspace, "--plan", trial_path], expected=2)
        require(message in result.stderr, f"standards rule {change.__name__} must reject before approval")

    listing = cli(["standards"]).stdout
    items = cli(["standards", "--ref", "ISO 9241-110:2020"]).stdout
    require("ISO/IEC 25010:2023" in listing and "부 단위" in listing and "principle.controllability" in items
            and "ISO/IEC 25012:2008" not in items, "standards listing must show refs and the requested items")
    cli(["standards", "--ref", "ISO 9218"], expected=2)
    cli(["standards", "--ref", ""], expected=2)
    # A deferred acceptance check may name an edition this attempt does not apply.
    deferred = copy.deepcopy(plan)
    later = dict(deferred["input"]["checks"][0], id="later-acceptance", title="보류 인수", stage="acceptance", selected=False)
    later["standards"] = [{"ref": "ISO/IEC 25019:2023", "items": ["beneficialness.suitability"]}, *later["standards"]]
    deferred["input"]["checks"].append(later)
    deferred_path = workspace / "qa-standards-deferred.json"
    save(deferred_path, deferred)
    inspect(workspace, deferred_path)
    # A UX check with ISO 9241 and an acceptance check with quality in use pass inspect, run and verify.
    good = copy.deepcopy(plan)
    good["standards"] += [
        {"edition": "ISO 9241-110:2020", "applied": True, "reason": "조작 흐름을 상호작용 원칙으로 판정한다."},
        {"edition": "ISO 9241-11:2018", "applied": True, "reason": "담당자의 과업 효과성을 확인한다."}]
    for s in good["standards"]:
        if s["edition"] == "ISO/IEC 25019:2023":
            s.update(applied=True, reason="담당자가 재고 상태를 알아볼 수 있는지 인수 시나리오로 확인한다.")
    first, second = good["input"]["checks"]
    first["standards"] = [ux, {"ref": "ISO 9241-110:2020", "items": ["principle.controllability"]},
                          {"ref": "ISO/IEC/IEEE 29119-4:2021", "items": ["specification_based.scenario_testing"]}]
    second.update(stage="acceptance")
    second["standards"] = [{"ref": "ISO/IEC 25019:2023", "items": ["beneficialness.suitability"]},
                           {"ref": "ISO 9241-11:2018", "items": ["usability.effectiveness"]},
                           *second["standards"]]
    good_path = workspace / "qa-standards-good.json"
    save(good_path, good)
    store = root / "standards-store"
    cli(run_args(workspace, good_path, store, inspect(workspace, good_path), "--require-pass"))
    record_path = store / FIRST
    record = verified(record_path)
    require(record["input"]["checks"][0]["standards"] == first["standards"], "standards are frozen with the input")
    render_check(record_path, root / "standards-report", "적용 표준")
    report = (root / "standards-report" / "report.md").read_text(encoding="utf-8")
    require("표준 대응" in report and "검사 없는 항목" in report and "performance\\_efficiency.time\\_behaviour" in report
            and "ISO 9241-110:2020" in report, "report must show coverage and uncovered catalog items")

    # The attempt keeps its own catalog copy; a changed copy fails verification.
    tampered = root / "standards-tampered"
    shutil.copytree(store, tampered)
    catalog = tampered / "round-0001" / "attempt-0001" / "standards.json"
    catalog.write_bytes(catalog.read_bytes().replace(b"functional_correctness", b"functional_correctnesz", 1))
    require("표준 목록 해시 불일치" in cli(["verify", tampered / FIRST], expected=2).stderr,
            "verify must reject a changed standards catalog")
    subprocess.run([sys.executable, "-B", str(PACKAGE / "views" / "render.py"), str(tampered / FIRST),
                    "--out", str(root / "standards-tampered-report")], capture_output=True, check=True, timeout=30)
    shown = (root / "standards-tampered-report" / "report.md").read_text(encoding="utf-8")
    require("표준 목록 확인 필요" in shown and "검사 없는 항목" not in shown,
            "reports must not trust a catalog copy that does not match the approval")
    print("PASS 12 · 용도별 표준 대응 규칙 13건 거부, 보류 검사 허용, UX·인수 검사의 9241·25019 대응, "
          "검사 없는 항목 보고, 표준 목록 변조의 검증·보고서 거부")

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
        standards_mapping(root, workspace)


if __name__ == "__main__":
    # Korean result lines must not crash a non-UTF-8 console (e.g. cp1252 on Windows runners).
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    main()
