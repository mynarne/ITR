"""Optional offline Chromium gate for a trusted ITR replay. Requires Playwright and Chromium."""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys


class CheckFailure(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise CheckFailure(reason)


def check_view(page, width, expected, output):
    record = expected["record"]
    checks = record["input"]["checks"]
    states = {}
    concurrent = None
    for i, item in enumerate(record["events"], 1):
        states[item["check_id"]] = item["state"]
        if concurrent is None and list(states.values()).count("running") >= 2:
            concurrent = i
    require(concurrent is not None, "Gate fixture requires a cursor with concurrent checks.")
    failures = [r["check_id"] for r in record["results"] if r["status"] == "failed"]
    require(failures, "Gate fixture requires an observed failure.")
    cards = page.locator("#board .card")
    require(cards.count() == len(checks), "Missing check cards.")
    require(page.locator("#board .flow path[marker-end]").count() ==
            sum(len(c.get("depends_on", [])) for c in checks), "Missing dependency connectors.")
    require(page.locator("#reduce").is_checked(), "System reduced-motion preference not applied.")
    seek = page.locator("#seek")
    seek.focus()
    seek.press("Home")
    for _ in range(concurrent):
        seek.press("ArrowRight")
    require(int(seek.input_value()) == concurrent, "Timeline cursor mismatch.")
    page.locator("#reduce").uncheck()
    page.locator("#play").click()
    # CSS is evaluated inside a real layout engine, with a running replay clock.
    motions = cards.evaluate_all("""els => els.map(el => [
        el.dataset.state, getComputedStyle(el).animationName,
        getComputedStyle(el, '::after').animationName])""")
    active = [entry for entry in motions if entry[0] == "running"]
    require(len(active) >= 2, "No parallel active cards when playback started.")
    require(all(a == "breathe" and b == "trace" for _, a, b in active), "Missing pulse or light point.")
    require(all(a == "none" and b == "none" for state, a, b in motions if state != "running"),
            "Inactive card is animated.")
    page.locator("#reduce").check()
    require(all(v == "none" for v in cards.evaluate_all("""els => els.flatMap(el =>
        [getComputedStyle(el).animationName,getComputedStyle(el,'::after').animationName])""")),
            "Reduced motion was not honored.")
    # Capture scroll before and after a real timer tick, without a user scroll action.
    def scroll():
        return page.evaluate("() => [scrollX,scrollY,document.querySelector('.scroller').scrollLeft]")
    origin = scroll()
    cursor = seek.input_value()
    page.wait_for_function("v => document.querySelector('#seek').value !== v", arg=cursor, timeout=4000)
    require(scroll() == origin, "Playback moved the viewport without an explicit jump.")
    page.locator("#end").click()
    require(page.locator("#current").is_disabled(), "Current-work button should be disabled at completion.")
    card = next(c for c in checks if c["id"] == failures[0])
    page.get_by_role("button", name=card["title"] + " · 실패", exact=False).click()
    details = page.locator("#details").inner_text()
    for marker in ("깨진 목표", "로그·캡처", "확인된 원인", "가설", "최소 수정 방향", "다음 회귀 검사"):
        require(marker in details, f"Missing failure detail {marker}")
    unique = len({d["fingerprint"] for d in record["defects"]})
    require(page.locator("#defect-total").inner_text() == str(unique), "Defect count differs.")
    results = {r["check_id"]: r["status"] for r in record["results"]}
    for row in page.locator("#stage-counts tbody tr").all():
        stage = row.get_attribute("data-stage")
        counts = Counter(results[c["id"]] for c in checks if c["stage"] == stage)
        for cell in row.locator("td").all():
            require(cell.inner_text() == str(counts[cell.get_attribute("data-status")]),
                    f"Unexpected {stage} count")
    require(page.evaluate("document.documentElement.scrollWidth <= innerWidth"),
            "Page overflows viewport outside the designated scrolling regions.")
    page.screenshot(path=str(output / f"replay-{width}.png"), full_page=True, animations="disabled")
    return {"viewport_width": width, "parallel_cards": len(active), "defects": unique,
            "motion_checked": True, "unsolicited_scroll": False}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("replay", type=Path)
    ap.add_argument("--out", required=True, type=Path, help="New observation directory outside the package")
    ap.add_argument("--chromium", help="Path to the local Chromium/Chrome executable")
    args = ap.parse_args()
    replay = args.replay.resolve(strict=True)
    out = args.out.resolve()
    project = Path(__file__).resolve().parents[1]
    if out == project or project in out.parents:
        ap.error("Choose a new observation directory outside the package.")
    out.mkdir(parents=True, exist_ok=False)
    report = {"target": replay.name, "sha256": hashlib.sha256(replay.read_bytes()).hexdigest(),
              "at": datetime.now(timezone(timedelta(hours=9))).isoformat(), "renderer": "Chromium",
              "status": "blocked", "observations": []}
    try:
        from playwright.sync_api import sync_playwright
        executable = args.chromium or shutil.which("chromium") or shutil.which("google-chrome")
        require(executable, "Local Chromium unavailable.")
        with sync_playwright() as p:
            with p.chromium.launch(executable_path=executable, chromium_sandbox=True) as browser:
                report["browser_version"] = browser.version
                for width, height in ((1366, 900), (390, 844)):
                    with browser.new_context(offline=True, viewport={"width": width, "height": height},
                                             reduced_motion="reduce", locale="ko-KR",
                                             timezone_id="Asia/Seoul") as ctx:
                        page = ctx.new_page()
                        page.goto(replay.as_uri(), wait_until="load")
                        report["status"] = "failed"
                        page.locator("#board .card").first.wait_for(timeout=8000)
                        source = json.loads(page.locator("#source").text_content())
                        report["observations"].append(check_view(page, width, source, out))
                report["status"] = "passed"
    except Exception as exc:
        raw = str(exc).encode("utf-8")
        # Raw local logs can contain temporary profile paths. The shareable
        # report identifies the full local log solely by its digest.
        with (out / "browser-error.private.log").open("xb") as target:
            target.write(raw)
        report["source_log_sha256"] = hashlib.sha256(raw).hexdigest()
        if "socket() failed: Operation not permitted" in str(exc):
            report["reason_code"] = "CHROMIUM_SOCKET_DENIED"
            report["reason"] = "Chromium process initialization: socket() failed: Operation not permitted."
        elif isinstance(exc, ModuleNotFoundError):
            report["reason_code"] = "DEPENDENCY_UNAVAILABLE"
            report["reason"] = "Optional browser dependency unavailable."
        elif isinstance(exc, CheckFailure):
            report["reason_code"] = "CHECK_FAILED"
            report["reason"] = str(exc)
        else:
            report["reason_code"] = "BROWSER_GATE_ERROR"
            report["reason"] = "Browser gate could not complete. See the private local log."
    with (out / "browser-check.json").open("x", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
    print(report["status"], out / "browser-check.json")
    return {"passed": 0, "failed": 1, "blocked": 2}[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
