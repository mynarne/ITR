"""Pin a trusted local plan, its explicitly listed files, and selected executable images."""
import hashlib
import json
import os
import platform
import shutil
import sys
from pathlib import Path

from itr_store import digest, encoded, keyed, need, safe_file
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "schemas"))
from validate import read_json, validate

MAX_SOURCE_BYTES = 64 * 1024 * 1024
OUTPUT_ENCODINGS = {"utf-8", "cp949"}
EXECUTION_POLICY = "itr.local.process.v2"
EVIDENCE_SCHEMA_VERSION = "2.1"
# 2.0 stored the resolved executable path; 2.1 stores the plan name and binds the path by hash only.
EVIDENCE_SCHEMA_VERSIONS = ("2.0", EVIDENCE_SCHEMA_VERSION)


def system_path():
    directories = [str(Path(sys.executable).absolute().parent)]
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot")
        if system_root:
            directories.append(str(Path(system_root) / "System32"))
    else:
        directories.extend(os.defpath.split(os.pathsep))
    return os.pathsep.join(dict.fromkeys(p for p in directories if Path(p).is_absolute()))


SYSTEM_PATH = system_path()


def executable(name):
    if name == "{python}":
        return sys.executable
    path = Path(name)
    if os.name != "nt":
        return shutil.which(name, path=SYSTEM_PATH)
    # Python 3.9–3.11 shutil.which can search the current directory on Windows.
    if path.is_absolute():
        return str(path) if path.suffix.lower() == ".exe" and path.is_file() else None
    name = name if path.suffix else name + ".exe"
    if Path(name).suffix.lower() != ".exe":
        return None
    return next((str(Path(folder) / name) for folder in SYSTEM_PATH.split(os.pathsep)
                 if (Path(folder) / name).is_file()), None)


def executable_path_hash(path):
    return digest(path.encode("utf-8", errors="surrogatepass"))


def file_hash(path):
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def stable(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode("utf-8"))


def plan_checks(inputs):
    validate(inputs, "input")
    checks = keyed(inputs["checks"], "id")
    baselines = keyed(inputs["baselines"], "id")
    caps = keyed(inputs["capabilities"], "id")
    ready = set()
    for key, check in checks.items():
        need(set(check["requires"]) <= caps.keys() and set(check["criteria"]) <= baselines.keys(),
             f"{key} 기준·능력 참조 오류")
        need(set(check.get("depends_on", [])) <= checks.keys(), f"{key} 선행 검사 참조 오류")
    while len(ready) < len(checks):
        next_layer = {k for k, c in checks.items() if k not in ready and set(c.get("depends_on", [])) <= ready}
        need(next_layer, "검사 계획에 순환이 있습니다.")
        ready.update(next_layer)
    return checks


def probe(key):
    system = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(platform.system(), "unknown")
    return key == "local_command" or key == "os." + system


def inspect(workspace, plan_path):
    workspace = workspace.resolve(strict=True)
    need(workspace.is_dir(), "작업공간 디렉터리가 필요합니다.")
    need(plan_path.is_file() and plan_path.stat().st_size <= 1024 * 1024, "계획은 1 MiB 이하 JSON 파일입니다.")
    # Parse the same bytes that enter approval, even if the source path changes during inspection.
    raw = plan_path.read_bytes()
    def pairs(items):
        obj = dict(items)
        need(len(items) == len(obj), "계획에 중복 JSON 키가 있습니다.")
        return obj
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    need(isinstance(data, dict) and set(data) == {"adapter_version", "input", "files", "commands", "standards"}
         and data["adapter_version"] == "1.0", "프로젝트 어댑터 계획 1.0 형식 오류")
    checks = plan_checks(data["input"])
    need(isinstance(data["standards"], list) and all(isinstance(s, dict) and
         set(s) == {"edition", "applied", "reason"} and isinstance(s["applied"], bool)
         and all(isinstance(s[k], str) and s[k].strip() for k in ["edition", "reason"])
         for s in data["standards"]), "표준 선택은 edition, applied, reason을 사용합니다.")
    paths = data["files"]
    need(isinstance(paths, list) and paths and all(isinstance(p, str) for p in paths)
         and len(paths) == len(set(paths)), "명시적으로 고정할 고유 파일 목록이 필요합니다.")
    payloads, specs, total = {}, [], 0
    for name in sorted(paths):
        path = safe_file(workspace, name)
        need(path.is_file(), f"일반 파일 필요 · {name}")
        need(path.stat().st_size <= MAX_SOURCE_BYTES - total, "고정 파일 합계는 64 MiB 이하입니다.")
        with path.open("rb") as stream:
            body = stream.read(MAX_SOURCE_BYTES - total + 1)
        total += len(body)
        need(total <= MAX_SOURCE_BYTES, "고정 파일 크기 한도 초과")
        payloads[name] = body
        specs.append({"path": name, "sha256": digest(body), "executable": bool(path.stat().st_mode & 0o111)})
    commands = data["commands"]
    need(isinstance(commands, dict) and set(commands) <= checks.keys(), "검사별 commands 객체가 필요합니다.")
    programs, actual_paths, hashes = {}, {}, {}
    for key, command in commands.items():
        need(isinstance(command, dict) and "argv" in command and
             set(command) <= {"argv", "timeout_s", "fingerprint", "pass_marker", "output_encoding"}, f"{key} 명령 키 오류")
        encoding = command.get("output_encoding", "utf-8")
        need(isinstance(encoding, str) and encoding in OUTPUT_ENCODINGS, f"{key} 출력 인코딩 오류")
        argv = command["argv"]
        need(isinstance(argv, list) and argv and all(isinstance(v, str) and "\x00" not in v for v in argv)
             and argv[0], f"{key} argv는 인수 문자열 배열입니다.")
        timeout = command.get("timeout_s", 30)
        need(type(timeout) in (int, float) and 0.05 <= timeout <= 3600, f"{key} timeout_s는 0.05~3600입니다.")
        if "pass_marker" in command:
            marker = command["pass_marker"]
            need(isinstance(marker, str) and marker.strip() and len(marker.encode("utf-8")) <= 256
                 and not any(c in marker for c in ("\n", "\r", "\x00", "\ufffd")),
                 f"{key} pass_marker는 줄바꿈·NUL·대체 문자 없는 1~256 UTF-8 바이트의 증거 문자열입니다.")
        if "fingerprint" in command:
            need(isinstance(command["fingerprint"], str) and command["fingerprint"].strip(), f"{key} fingerprint 오류")
        name = argv[0]
        if name in programs:
            continue
        if name.startswith("./"):
            rel = name[2:]
            need(rel in payloads, "프로젝트 로컬 실행 파일은 files에 고정해야 합니다.")
            programs[name] = (None if os.name == "nt" and Path(rel).suffix.lower() != ".exe"
                              else digest(payloads[rel]))
            actual_paths[name] = None
            continue
        need(name == "{python}" or Path(name).is_absolute() or (not Path(name).drive and all(c not in name for c in ("/", "\\"))),
             "도구 이름, 절대 실행 파일, ./프로젝트-도구 또는 {python}이 필요합니다.")
        resolved = executable(name)
        if resolved:
            path = Path(resolved).resolve(strict=True)
            if path not in hashes:
                hashes[path] = file_hash(path)
            programs[name], actual_paths[name] = hashes[path], str(path)
        else:
            programs[name], actual_paths[name] = None, None
    capabilities = [{**cap, "available": cap["available"] and probe(cap["id"])} for cap in data["input"]["capabilities"]]
    input_snapshot = {**data["input"], "capabilities": capabilities}
    binding = dict(plan_sha256=digest(raw), files=specs, executables=programs,
                   workspace_sha256=digest(os.fsencode(str(workspace))), capabilities=capabilities,
                   execution_policy=EXECUTION_POLICY, evidence_schema_version=EVIDENCE_SCHEMA_VERSION,
                   launch_os=os.name, executable_paths_sha256={
                       name: executable_path_hash(path) if path is not None else None
                       for name, path in actual_paths.items()})
    approval = {"approval_sha256": stable(binding), **binding}
    return data, raw, input_snapshot, approval, payloads, actual_paths
