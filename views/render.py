"""Render an ITR 1.0 record without modifying the source attempt. Python 3.9+."""
import argparse
import base64
import hashlib
import html
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
STAGES = {
    "unit": "단위", "integration": "통합", "system": "시스템",
    "intersystem": "시스템 간 통합", "acceptance": "인수 시나리오",
}
STATES = {
    "queued": "대기", "running": "실행 중", "passed": "통과",
    "failed": "실패", "blocked": "차단", "not_run": "미실행",
}
ROLES = {
    "bb_goal": "목표 충족", "bb_context": "사용 맥락", "bb_boundary": "경계 조건",
    "wb_logic": "내부 로직", "wb_contract": "모듈 계약", "wb_config": "구성·설정",
    "runner": "실행기",
}
KINDS = {"goal": "제품 목표", "rule": "선택 스킬 규칙", "requirement": "프로젝트 요구사항"}
APPROVAL = {"not_requested": "요청 전", "pending": "승인 대기", "approved": "승인", "rejected": "반려"}
METHODS = {"inspection": "인스펙션", "execution": "실행 테스트"}
MODES = {"precision": "정밀", "delta": "일상 변경분"}
FINAL = ("passed", "failed", "blocked", "not_run")


def local_time(value):
    if not value:
        return "—"
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("시각에 UTC 오프셋이 필요합니다.")
    return date.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def unique_ids(values):
    return ", ".join(values) or "—"


def previews(record, directory):
    """Embed small verified local artifacts only. Preserve missing artifacts as such."""
    out = {}
    for item in record["evidence"]:
        entry = {}
        try:
            path = (directory / item["path"]).resolve()
            path.relative_to(directory)
            if Path(item["path"]).is_absolute() or path == directory or not path.is_file():
                raise ValueError("로컬 파일 경로 확인 필요")
            if path.stat().st_size > 1_048_576:
                raise ValueError("미리보기 한도 1 MiB 초과")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("SHA-256 불일치")
            if item["kind"] == "capture":
                mime = ("image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else
                        "image/jpeg" if data.startswith(b"\xff\xd8\xff") else "")
                if mime:
                    entry["image"] = "data:" + mime + ";base64," + base64.b64encode(data).decode()
            if not entry:
                snippet = data.decode("utf8")
                entry["text"] = snippet[:1800] + ("\n… (발췌)" if len(snippet) > 1800 else "")
            entry["status"] = "해시 대조 완료"
            extension = record.get("extensions", {})
            if extension.get("adapter") == "itr.local.project.v1":
                version = extension.get("evidence_schema_version")
                if version is None:
                    entry["launch_status"] = "기존 증거 · 실제 실행 인수 미기록"
                else:
                    capture = json.loads(data)
                    if (version not in ("2.0", "2.1") or capture.get("evidence_schema_version") != version
                            or "launch_argv" not in capture):
                        entry["launch_status"] = "실행 증거 버전 또는 인수 확인 필요"
                    elif capture["launch_argv"] is None:
                        entry["launch_status"] = f"증거 {version} · 프로세스 호출 전 차단"
                    else:
                        entry["launch_status"] = f"증거 {version} · 프로세스 호출 인수 기록"
        except (OSError, ValueError, UnicodeError) as exc:
            entry["status"] = ("원본 파일 없음" if isinstance(exc, FileNotFoundError)
                               else "미리보기 없음 · 파일 위치, 인코딩 또는 해시 확인")
        out[item["id"]] = entry
    return out


def report_blocks(r, digest, media):
    inp = r["input"]
    checks = inp["checks"]
    results = {v["check_id"]: v for v in r["results"]}
    defects = r["defects"]
    approval = r["approval"]
    yield "h1", "ITR 검증 보고서"
    yield "p", f'{inp["product"]} · {r["round"]}차 / 시도 {r["attempt"]} · {MODES[inp["mode"]]} 모드'
    yield "dl", [
        ("실행", r["run_id"]), ("생성 시각", local_time(r["created_at"])),
        ("대상 리비전", inp["revision"]), ("원본 SHA-256", digest),
        ("통합 판정", STATES[r["decision"]["status"]]), ("판정 사유", r["decision"]["reason"]),
        ("발주자·사용자 승인", APPROVAL[approval["status"]]),
        ("승인자 / 시각", f'{approval.get("actor") or "—"} / {local_time(approval.get("at"))}'),
        ("승인 범위 / 근거", f'{approval.get("scope") or "—"} / {unique_ids(approval.get("evidence_ids", []))}'),
    ]
    if r["previous"]:
        prior = r["previous"]
        yield "h2", "이전 실행과의 연결"
        yield "dl", [
            ("연결", f'{prior["type"]} · {prior["run_id"]} · {prior["round"]}차 / 시도 {prior["attempt"]}'),
            ("원본 / SHA-256", f'{prior["record_path"]} / {prior["sha256"]}'), ("이유", prior["reason"]),
        ]
    yield "h2", "단계별 검사 결과"
    rows = []
    for stage, label in STAGES.items():
        counts = Counter(results[c["id"]]["status"] for c in checks if c["stage"] == stage)
        if counts:
            rows.append([label, *[str(counts[s]) for s in FINAL]])
    yield "table", (["단계", *[STATES[s] for s in FINAL]], rows)
    yield "p", f'고유 결함 {len({d["fingerprint"] for d in defects})}건 · 동일한 fingerprint는 한 건으로 집계합니다.'
    yield "h2", "고정한 기준"
    for b in inp["baselines"]:
        yield "p", f'{b["id"]} · {KINDS[b["kind"]]} · {b["version"]} — {b["text"]}'
    yield "h2", "실행 환경"
    yield "table", (["능력", "가용 여부"], [[c["id"], "가용" if c["available"] else "미지원"] for c in inp["capabilities"]])
    yield "h2", "검사별 판정"
    for c in checks:
        res = results[c["id"]]
        yield "h3", f'{c["id"]} · {c["title"]} · {STATES[res["status"]]}'
        yield "dl", [
            ("단계 / 역할 / 방법", f'{STAGES[c["stage"]]} / {ROLES[c["role"]]} / {METHODS[c["method"]]}'),
            ("기준", unique_ids(c["criteria"])), ("통과 조건", c["pass_condition"]),
            ("필요 능력", unique_ids(c["requires"])), ("선행 검사", unique_ids(c.get("depends_on", []))),
            ("관찰", res["detail"]), ("증거", unique_ids(res["evidence_ids"])),
        ]
    yield "h2", "결함과 회귀 검사"
    if not defects:
        yield "p", "기록된 결함 0건"
    for d in defects:
        yield "h3", f'{d["id"]} · {d["observed"]}'
        yield "dl", [
            ("같은 결함 식별값", d["fingerprint"]), ("관련 검사", unique_ids(d["check_ids"])),
            ("깨진 기준", unique_ids(d["baseline_ids"])), ("근거", unique_ids(d["evidence_ids"])),
            ("확인된 원인", d["cause_confirmed"] or "미확인"), ("가설", d["hypothesis"] or "기록 없음"),
            ("최소 수정 방향", d["minimal_fix"]), ("다음 회귀 검사", d["next_regression"]),
        ]
    yield "h2", "독립 검토 기록"
    if not r["reviews"]:
        yield "p", "기록된 첫 판정 없음"
    for rev in r["reviews"]:
        yield "p", (f'{ROLES[rev["role"]]} · {STATES[rev["verdict"]]} · {local_time(rev["sealed_at"])} · '
                    f'검사 {unique_ids(rev["check_ids"])} · 증거 {unique_ids(rev["evidence_ids"])}')
    yield "h2", "증거 목록"
    for e in r["evidence"]:
        preview = media[e["id"]]
        yield "h3", f'{e["id"]} · {e["check_id"]} · {e["kind"]}'
        yield "dl", [("경로", e["path"]), ("SHA-256", e["sha256"]), ("미리보기", preview["status"])]
        if "launch_status" in preview:
            yield "p", preview["launch_status"]
        if "text" in preview:
            yield "pre", preview["text"]
        if "image" in preview:
            yield "image", (e["id"], preview["image"])
    yield "h2", "이벤트 이력"
    for ev in r["events"]:
        yield "p", f'{ev["seq"]} · {local_time(ev["at"])} · {ev["check_id"]} · {STATES[ev["state"]]} — {ev["message"]}'


def mdtext(value):
    return re.sub(r"([\\\x60*_{}\[\]()<>|#!~])", r"\\\1", str(value)).replace("\n", " ")


def markdown(blocks):
    parts = []
    for kind, value in blocks:
        if kind in ("h1", "h2", "h3"):
            parts.append("#" * int(kind[1]) + " " + mdtext(value))
        elif kind == "p":
            parts.append(mdtext(value))
        elif kind == "dl":
            parts.append("\n".join(f'- **{mdtext(k)}**　{mdtext(v)}' for k, v in value))
        elif kind == "table":
            head, rows = value
            parts.append("\n".join("| " + " | ".join(mdtext(x) for x in row) + " |" for row in [head, ["---"]*len(head), *rows]))
        elif kind == "pre":
            parts.append("\n".join("    " + line for line in value.splitlines()))
        else:
            parts.append(f'캡처 {mdtext(value[0])} · 인쇄본 및 화면에 포함')
    return "\n\n".join(parts) + "\n"


def print_html(blocks):
    esc = html.escape
    parts = []
    for kind, value in blocks:
        if kind in ("h1", "h2", "h3", "p", "pre"):
            parts.append(f'<{kind}>{esc(str(value))}</{kind}>')
        elif kind == "dl":
            parts.append("<dl>" + "".join(f"<dt>{esc(k)}</dt><dd>{esc(str(v))}</dd>" for k, v in value) + "</dl>")
        elif kind == "table":
            head, rows = value
            parts.append("<table><thead><tr>" + "".join(f"<th>{esc(c)}</th>" for c in head) + "</tr></thead><tbody>")
            parts.extend("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows)
            parts.append("</tbody></table>")
        else:
            parts.append(f'<img alt="{esc(value[0])}" src="{value[1]}">')
    style = """@page{size:A4;margin:16mm 16mm 19mm}*{box-sizing:border-box}
body{max-width:180mm;margin:auto;color:#172b27;font:10pt/1.5 'Noto Sans CJK KR','Malgun Gothic',sans-serif;overflow-wrap:anywhere}
h1{font-size:30pt;letter-spacing:-.05em;margin:0;border-bottom:2pt solid #19473e}
h2{margin:1.5em 0 .4em;font-size:16pt;color:#174d40;border-bottom:1pt solid #ccd6ce}
h3{font-size:11pt;margin:1em 0 .25em}h1,h2,h3{break-after:avoid}p{margin:.5em 0}
dl{margin:0}dt{font-weight:700;color:#4a6057}dd{margin:0 0 .25em}
table{border-collapse:collapse;width:100%;margin:.5em 0}td,th{text-align:left;padding:3pt;border-bottom:.6pt solid #b9c4bc}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f4ef;padding:5pt;font:8pt/1.5 monospace}img{max-width:100%;max-height:125mm}
@media print{dt{break-after:avoid}tr{break-inside:avoid}}"""
    return ('<!doctype html><html lang="ko"><meta charset="utf-8"><title>ITR 검증 보고서</title><style>' +
            style + '</style><body><main>' + '\n'.join(parts) + '</main></body></html>')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("record", type=Path)
    ap.add_argument("--out", required=True, type=Path, help="새 출력 디렉터리")
    args = ap.parse_args()
    record = args.record.resolve()
    out = args.out.resolve()
    if out == record.parent or record.parent in out.parents:
        ap.error("원본 attempt 밖의 새 출력 디렉터리를 지정하세요.")
    raw = record.read_bytes()
    r = json.loads(raw)
    if r["schema_version"] != "1.0":
        ap.error("지원하는 실행 기록 버전은 1.0입니다.")
    digest = hashlib.sha256(raw).hexdigest()
    media = previews(r, record.parent)
    blocks = list(report_blocks(r, digest, media))
    payload = {"record": r, "digest": digest, "previews": media}
    embedded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    replay = (HERE / "replay.template.html").read_text(encoding="utf8").replace("/*__ITR_DATA__*/", embedded)
    files = {"replay.html": replay, "report.md": markdown(blocks), "print.html": print_html(blocks)}
    out.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        with (out / name).open("x", encoding="utf8", newline="\n") as f:
            f.write(content)
    print(f"{out} · {local_time(r['created_at'])} · {digest}")


if __name__ == "__main__":
    main()
