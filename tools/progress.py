"""Watch an ITR local journal. Python 3.9+, standard library, no network or credentials."""
import argparse
import hashlib
import json
import os
import re
import sys
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
TERMINAL = {"passed", "failed", "blocked", "not_run"}
NEXT = {None: {"queued"}, "queued": {"running", "blocked", "not_run"},
        "running": {"passed", "failed", "blocked", "not_run"}}
PHASE = {"waiting": "실행 대기", "preparing": "시도 초기화", "live": "저널 관찰 중",
         "unconfirmed": "갱신 대기 · 실행 지속 미확인", "synchronizing": "기록 작성 확인 중",
         "interrupted": "중단 · 미완결", "invalid": "기록 대조 필요 · 미완결",
         "sealed": "최종 기록 봉인"}
MAX_GAP = 20.0
PAGE = Path(__file__).resolve().parents[1] / "views" / "progress.html"


def kst(epoch):
    return datetime.fromtimestamp(epoch, KST).isoformat(timespec="milliseconds")


def local_bytes(directory, name):
    path = directory / name
    if path.is_symlink():
        raise ValueError(f"심볼릭 링크를 읽을 수 없습니다 · {path.name}")
    return path.read_bytes()


def local_json(directory, name):
    return json.loads(local_bytes(directory, name))


def numbered(directory, prefix):
    if not directory.exists():
        return []
    pattern = re.compile(re.escape(prefix) + r"([0-9]{4,})$")
    options = []
    for p in directory.iterdir():
        match = pattern.fullmatch(p.name)
        if match and not p.is_symlink() and p.is_dir():
            index = int(match.group(1))
            if p.name == f"{prefix}{index:04d}":
                options.append((index, p))
    return sorted(options, reverse=True)


def latest(store):
    for rd, folder in numbered(store, "round-"):
        attempts = numbered(folder, "attempt-")
        if attempts:
            attempt, directory = attempts[0]
            return rd, attempt, directory
    return None


def last_write_phase(recent, stamp, now, limit):
    return recent if now - stamp <= limit else "unconfirmed"


def offset_time(value):
    if not isinstance(value, str) or datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("UTC 오프셋이 있는 이벤트 시각 필요")
    return value


def snapshot(store, stale_after=MAX_GAP):
    """Return a public projection. Never emit private observations, logs or first verdict files."""
    clock = time.time()
    directory = None
    view = dict(phase="waiting", run_id=None, round=None, attempt=None, product="", revision="",
                created_at=None, last_event_at=None, seq=0, checks=[], states={}, decision=None, defects=None)
    try:
        target = latest(store)
        if not target:
            return view
        rd, att, directory = target
        view.update(phase="preparing", round=rd, attempt=att)
        if not (directory / "reservation.json").exists():
            view["phase"] = last_write_phase("preparing", directory.stat().st_mtime, clock, stale_after)
            return view
        header = local_json(directory, "reservation.json")
        if (header["round"], header["attempt"]) != (rd, att):
            raise ValueError("예약과 시도 경로 불일치")
        view.update(run_id=header["run_id"], created_at=offset_time(header["created_at"]))
        interruption = directory / "interruption.json"
        if not (directory / "input.json").exists():
            view["phase"] = ("interrupted" if interruption.exists() else
                             last_write_phase("preparing", directory.stat().st_mtime, clock, stale_after))
            return view
        inp = local_json(directory, "input.json")
        view["product"], view["revision"] = inp["product"], inp["revision"]
        keys = ("id", "title", "role", "stage", "method", "depends_on")
        checks = [{k: c[k] for k in keys if k in c} for c in inp["checks"]]
        ids = {c["id"] for c in checks}
        if len(ids) != len(checks):
            raise ValueError("중복 검사 ID")
        view["checks"] = checks
        sealed_at_start = (directory / "COMPLETE.json").exists()
        journal = directory / "events"
        if journal.is_symlink():
            raise ValueError("저널 링크 거부")
        flags, raw_events = view["states"], []
        freshness = (directory / "reservation.json").stat().st_mtime
        if journal.is_dir():
            names = sorted((int(p.stem), p.name) for p in journal.iterdir()
                           if re.fullmatch(r"[0-9]{4,}\.json", p.name))
            for expected, (number, name) in enumerate(names, 1):
                if number != expected or name != f"{expected:04d}.json":
                    raise ValueError("연속되지 않은 저널")
                event = local_json(journal, name)
                key, state = event["check_id"], event["state"]
                if key not in ids or event["seq"] != expected or state not in NEXT.get(flags.get(key), set()):
                    raise ValueError("검사 전이 또는 순번 불일치")
                raw_events.append(event)
                flags[key] = state
                view["seq"], view["last_event_at"] = expected, offset_time(event["at"])
                freshness = (journal / name).stat().st_mtime
        if interruption.exists():
            view["phase"] = "interrupted"
            return view
        if not sealed_at_start:
            view["phase"] = last_write_phase("live", freshness, clock, stale_after)
            return view
        raw = local_bytes(directory, "record.json")
        if local_json(directory, "COMPLETE.json")["sha256"] != hashlib.sha256(raw).hexdigest():
            raise ValueError("완료 표식 해시 불일치")
        final = json.loads(raw)
        results = {result["check_id"]: result["status"] for result in final["results"]}
        if (final["run_id"] != header["run_id"] or final["input"] != inp or final["events"] != raw_events
                or set(flags) != ids or results != flags or len(final["results"]) != len(checks)
                or any(s not in TERMINAL for s in flags.values())):
            raise ValueError("입력·최종 기록·저널 불일치")
        selected = {flags[c["id"]] for c in inp["checks"] if c.get("selected", True)}
        gate = next((s for s in ("failed", "blocked", "not_run", "passed") if s in selected), "not_run")
        if gate != final["decision"]["status"]:
            raise ValueError("기술 판정과 검사 상태 불일치")
        view.update(phase="sealed", decision=gate,
                    defects=len({d["fingerprint"] for d in final["defects"]}))
    except (FileNotFoundError, json.JSONDecodeError):
        # Exclusive-create writers can be observed between file creation and flush.
        view["phase"] = "synchronizing"
        if directory is not None:
            try:
                entries = [directory, directory/"events", directory/"COMPLETE.json"]
                stamp = max(p.stat().st_mtime for p in entries if p.exists() and not p.is_symlink())
                view["phase"] = last_write_phase("synchronizing", stamp, clock, stale_after)
            except (OSError, ValueError):
                pass
    except (PermissionError, OSError, KeyError, ValueError, TypeError):
        view["phase"] = "invalid"
    return view


def publish(out, view, watching, interval, stopped=False):
    payload = dict(view, observed_at=kst(time.time()), watching=watching, stopped=stopped,
                   heartbeat_ms=max(4500, round(interval*4500)))
    # JS string escapes keep the classic script parseable across browsers; data never becomes markup.
    script = "window.ITR_PROGRESS(" + json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + ");\n"
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf8", dir=out, prefix=".progress-",
                                         delete=False) as temp:
            temp_name = temp.name
            temp.write(script)
        os.replace(temp_name, out / "progress.index.js")
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def sealed_report(out, store, view, cache):
    if view["phase"] != "sealed":
        return
    key = (view["round"], view["attempt"], view["run_id"])
    if key not in cache:
        rd, att = key[:2]
        folder = f"reports/round-{rd:04d}-attempt-{att:04d}"
        source = store / f"round-{rd:04d}" / f"attempt-{att:04d}" / "record.json"
        proc = subprocess.run([sys.executable, "-B", str(PAGE.with_name("render.py")),
                               str(source), "--out", str(out / folder)], capture_output=True)
        cache[key] = folder + "/replay.html" if proc.returncode == 0 else None
    view["report"] = cache[key]


def setup_out(out, store):
    if out == store or store in out.parents:
        raise ValueError("화면은 실행 저장소 밖의 새 출력 폴더에 만듭니다.")
    out.mkdir(parents=True, exist_ok=False)
    with (out / "index.html").open("xb") as f:
        f.write(PAGE.read_bytes())


def main():
    parser = argparse.ArgumentParser(description="ITR 로컬 진행 관찰 · 기본은 1회 조회")
    parser.add_argument("--store", type=Path, default=Path("itr-runs"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--watch", action="store_true", help="새 시도와 진행을 계속 관찰, 종료 Ctrl+C")
    mode.add_argument("--once", action="store_true", help="한 번만 조회 (기본)")
    parser.add_argument("--out", type=Path, help="브라우저 화면 전용 새 폴더")
    parser.add_argument("--interval", type=float, default=.35, help="조회 간격(초), 기본 0.35")
    parser.add_argument("--json", action="store_true", help="상태 변경마다 JSON 한 줄")
    args = parser.parse_args()
    if not .02 <= args.interval <= 60:
        parser.error("--interval은 0.02~60초입니다.")
    store = args.store.resolve()
    out = args.out.resolve() if args.out else None
    if out:
        setup_out(out, store)
        print("진행 화면 · " + str(out / "index.html"), file=sys.stderr, flush=True)
    previous, published, view = None, 0.0, None
    reports = {}
    try:
        while True:
            view = snapshot(store)
            if out:
                sealed_report(out, store, view, reports)
            if out and (previous != view or time.monotonic()-published >= 1.0):
                publish(out, view, args.watch, args.interval)
                published = time.monotonic()
            if view != previous:
                if args.json:
                    print(json.dumps(view, ensure_ascii=False), flush=True)
                else:
                    runs = [k for k,v in view["states"].items() if v == "running"]
                    status = " · 진행 확인 " + ", ".join(runs) if view["phase"] == "live" and runs else ""
                    target = f'{view["round"]}차 시도 {view["attempt"]} · ' if view["round"] else ""
                    print(f'{kst(time.time())} KST · {target}{PHASE[view["phase"]]} · 이벤트 {view["seq"]}{status}', flush=True)
                previous = view
            if not args.watch:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        if out and view is not None:
            publish(out, view, False, args.interval, stopped=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print(f"ITR · {error}", file=sys.stderr)
        sys.exit(2)
