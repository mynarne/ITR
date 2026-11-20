"""Supervise one trusted command in a fresh copy; bound retained output while draining both pipes."""
import codecs
import os
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from itr_store import fresh, now
from project_plan import SYSTEM_PATH, executable_path_hash, file_hash

LIMIT = 64 * 1024


def stop_tree(process):
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        system_root = os.environ.get("SystemRoot", "")
        taskkill = Path(system_root) / "System32" / "taskkill.exe"
        if system_root and taskkill.is_file():
            try:
                subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               env={"SystemRoot": system_root}, timeout=3, check=False)
            except (OSError, subprocess.SubprocessError):
                pass
        if process.poll() is None:
            process.kill()


def collect(stream, output, encoding, marker=None):
    decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
    tail, offset = "", 0
    overlap = len(marker) - 1 if marker else 0
    try:
        while True:
            block = stream.read(16384)
            output["bytes"] += len(block)
            output["data"].extend(block[:max(0, LIMIT - len(output["data"]))])
            if marker and "match" not in output:
                text = decoder.decode(block, final=not block)
                window = tail + text
                index = window.find(marker)
                if index >= 0:
                    output["match"] = {"text": window[index:index+len(marker)],
                                       "offset_chars": offset - len(tail) + index}
                offset += len(text)
                tail = window[-overlap:] if overlap else ""
            if not block:
                break
    except OSError:
        output["read_error"] = True
    finally:
        stream.close()


def child_environment(temp, encoding):
    # Keep the search path controlled and keep temporary data inside this invocation.
    env = {"PATH": SYSTEM_PATH, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": encoding,
           "TEMP": str(temp), "TMP": str(temp), "TMPDIR": str(temp)}
    if os.name == "nt":
        env.update({k: os.environ[k] for k in ("SystemRoot", "WINDIR") if k in os.environ})
    return env


def launch_flags(command):
    # -I and -E ignore PYTHONIOENCODING. Make default UTF-8 explicit on the approved interpreter.
    utf8 = command["argv"][0] == "{python}" and command.get("output_encoding", "utf-8") == "utf-8"
    return ["-X", "utf8"] if utf8 else []


def run_command(command, binding, payloads, actual_paths, stop, report):
    argv = command["argv"]
    flags = launch_flags(command)
    encoding = command.get("output_encoding", "utf-8")
    report.update(started_at=now(), finished_at=None, elapsed_s=None, stdout="", stderr="",
                  retained_limit_per_stream=LIMIT, output_encoding=encoding, stdout_bytes=0,
                  stderr_bytes=0, stdout_truncated=False, stderr_truncated=False)
    begin = time.monotonic()
    status, reason = "blocked", "실행기를 시작하지 못했습니다."
    with tempfile.TemporaryDirectory(prefix="itr-project-case-") as work:
        # One canonical path for the child: on macOS /var is a symlink to /private/var.
        base = Path(work).resolve()
        cwd, temp = base / "work", base / "temp"
        cwd.mkdir()
        temp.mkdir()
        for spec in binding["files"]:
            target = cwd / spec["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            fresh(target, payloads[spec["path"]])
            if spec["executable"] and os.name == "posix":
                target.chmod(0o700)
        name = argv[0]
        approved = binding["executables"][name]
        exe = str(cwd / name[2:]) if name.startswith("./") else actual_paths[name]
        if not approved or not exe or file_hash(Path(exe)) != approved:
            report.update(finished_at=now(), elapsed_s=round(time.monotonic() - begin, 6))
            return "blocked", "승인한 실행 파일이 없거나 지문이 바뀌었습니다."
        env = child_environment(temp, encoding)
        streams = [{"data": bytearray(), "bytes": 0}, {"data": bytearray(), "bytes": 0}]
        process = None
        threads = []
        try:
            if stop.is_set():
                return "blocked", "실행 전 중단 요청."
            # Shared evidence keeps the plan's program name; the resolved path is bound only by its hash.
            report["launch_argv"] = [name, *flags, *argv[1:]]
            report["launch_executable_sha256"] = None if name.startswith("./") else executable_path_hash(exe)
            process = subprocess.Popen([exe, *flags, *argv[1:]], shell=False, cwd=cwd, env=env,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=os.name == "posix")
            markers = (command.get("pass_marker"), None)
            for pipe, result, marker in zip((process.stdout, process.stderr), streams, markers):
                reader = threading.Thread(target=collect, args=(pipe, result, encoding, marker), daemon=True)
                reader.start()
                threads.append(reader)
            deadline = time.monotonic() + command.get("timeout_s", 30)
            while process.poll() is None:
                if stop.is_set():
                    reason = "실행 중 중단 요청."
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = "제한 시간 초과."
                    break
                try:
                    process.wait(timeout=min(remaining, 0.05))
                except subprocess.TimeoutExpired:
                    pass
            else:
                code = process.returncode
                status, reason = {0: ("passed", "승인한 테스트 명령이 정상 종료했습니다."),
                                  1: ("failed", "승인한 테스트 명령이 실패를 보고했습니다."),
                                  77: ("not_run", "테스트 명령이 검사를 건너뛰었습니다(77).")}.get(
                                      code, ("blocked", f"판정 계약 밖의 종료 코드 {code}."))
        except OSError as error:
            reason = f"명령 시작 또는 실행 오류 · {error.__class__.__name__}"
        finally:
            if process is not None:
                if process.poll() is None:
                    stop_tree(process)
                try:
                    report["exit_code"] = process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    status, reason = "blocked", "실행기 종료 확인 실패."
                # Reap children of a finished test, including quiet background processes.
                # The isolated POSIX process group belongs to this test invocation alone.
                if os.name == "posix":
                    stop_tree(process)
                for t in threads:
                    t.join(timeout=1.0)
                if any(t.is_alive() for t in threads):
                    stop_tree(process)
                    for t in threads:
                        t.join(timeout=0.5)
                    status, reason = "blocked", "명령 종료 후 열린 자식 출력 스트림이 남았습니다."
            if any(o.get("read_error") for o in streams):
                if status == "passed":
                    status, reason = "blocked", "하위 프로세스의 출력 스트림을 끝까지 읽지 못했습니다."
                report["output_read_error"] = True
            for key, output in zip(("stdout", "stderr"), streams):
                count, data = output["bytes"], bytes(output["data"])
                truncated = count > LIMIT
                decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
                report[key] = decoder.decode(data, final=not truncated)
                report[key + "_bytes"] = count
                report[key + "_truncated"] = truncated
            match = streams[0].get("match")
            if match and match["text"] not in report["stdout"] and report["stdout_truncated"]:
                report["stdout_marker_excerpt"] = match
            report.update(finished_at=now(), elapsed_s=round(time.monotonic() - begin, 6))
    return status, reason
