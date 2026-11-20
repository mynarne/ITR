"""Typeset a sealed ITR record as a concise A4 report using the optional PDF runtime."""

from collections import Counter
from hashlib import sha256
from itertools import zip_longest
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "schemas"), str(ROOT / "views")]
from render import APPROVAL, FINAL, KINDS, METHODS, MODES, STAGES, STATES, local_time, previews, unique_ids
from validate import read_json, validate

INK = (0.13, 0.12, 0.11)
DIM = (0.34, 0.32, 0.29)
RULE = (0.70, 0.67, 0.62)
FONT_DIR = ROOT / "assets" / "fonts"
STATUS_LABELS = {**STATES, "blocked": "차단", "not_run": "미실행"}


def visible_text(text):
    # Keep line wrapping and extraction predictable for UTF-8 text with tabs.
    return str(text).expandtabs(4).replace("\r\n", "\n").replace("\r", "\n")


class Sheet:
    def __init__(self, pdf):
        self.pdf = pdf
        self.paper = pdf.paper_rect("A4")
        self.doc = pdf.open()
        self.font = pdf.Font(fontfile=str(FONT_DIR / "Pretendard-Regular.ttf"))
        self.heading_font = pdf.Font(fontfile=str(FONT_DIR / "Pretendard-SemiBold.ttf"))
        self.expected = []
        self.left = 52.0
        self.right = self.paper.width - self.left
        self.width = self.right - self.left
        self.value_x = self.left + 128
        self.value_width = self.right - self.value_x
        self.bottom = self.paper.height - 62
        self.context = "검사 결과"

    def new_page(self, cover=False):
        self.page = self.doc.new_page(width=self.paper.width, height=self.paper.height)
        self.expected.append([])
        self.line(self.left, 36, "ITR  /  품질 검증", 9, strong=True)
        running = "요약" if cover else self.context
        self.line(self.right - self.measure(running, 8.5), 36, running, 8.5, DIM)
        self.horizontal(54)
        self.y = 67

    def measure(self, value, size, strong=False):
        font = self.heading_font if strong else self.font
        return font.text_length(value, fontsize=size)

    def line(self, x, top, text, size=10, color=INK, *, strong=False):
        if not text:
            return
        font = self.heading_font if strong else self.font
        for char in set(text):
            if not font.has_glyph(ord(char)):
                raise ValueError(f"Pretendard does not cover U+{ord(char):04X}. No output created.")
        writer = self.pdf.TextWriter(self.paper)
        writer.append((x, top + size), text, font=font, fontsize=size)
        writer.write_text(self.page, color=color)
        self.expected[self.page.number].append(text)

    def horizontal(self, top, weight=0.5):
        self.page.draw_line((self.left, top), (self.right, top), color=RULE, width=weight)

    def wrap(self, text, size, width, strong=False):
        font = self.heading_font if strong else self.font
        for segment in visible_text(text).split("\n"):
            segment = segment.strip()
            if not segment:
                yield ""
                continue
            widths = font.char_lengths(segment, fontsize=size)
            start, edge, last_space, used = 0, 0, -1, 0.0
            while edge < len(segment):
                if used + widths[edge] <= width or edge == start:
                    if segment[edge].isspace():
                        last_space = edge
                    used += widths[edge]
                    edge += 1
                    continue
                split = last_space if last_space > start else edge
                yield segment[start:split].rstrip()
                start = split
                while start < len(segment) and segment[start].isspace():
                    start += 1
                edge, last_space, used = start, -1, 0.0
            if start < len(segment):
                yield segment[start:]

    def cover_text(self, x, top, text, size, width, lines=1, color=INK, *, strong=False):
        parts = list(self.wrap(text, size, width, strong))
        if len(parts) > lines:
            last = parts[lines - 1]
            while last and self.measure(last + "…", size, strong) > width:
                last = last[:-1]
            parts = [*parts[:lines - 1], last.rstrip() + "…"]
        for i, part in enumerate(parts):
            self.line(x, top + i * (size + 4), part, size, color, strong=strong)

    def room(self, height):
        if self.y + height > self.bottom:
            self.new_page()

    def text(self, text, size=10, color=INK, gap=4, *, strong=False):
        for line in self.wrap(text, size, self.width, strong):
            self.room(size + 5)
            self.line(self.left, self.y, line, size, color, strong=strong)
            self.y += size + 4
        self.y += gap

    def section(self, title):
        self.context = title
        self.room(74)
        self.y += 8
        self.horizontal(self.y)
        self.y += 9
        self.text(title, 15, gap=9, strong=True)

    def item(self, title):
        # Leave room for a title and its first detail before starting a row.
        self.room(56)
        self.text(title, 11, gap=3, strong=True)

    def field_lines(self, label, value, size=9.5):
        labels = self.wrap(label, 9.5, self.value_x - self.left - 14)
        values = self.wrap(value, size, self.value_width)
        return zip_longest(labels, values, fillvalue="")

    def field(self, label, value, *, size=9.5):
        for key, part in self.field_lines(label, value, size):
            self.room(15)
            self.line(self.left, self.y, key, 9.5, DIM)
            self.line(self.value_x, self.y, part, size)
            self.y += 13.5
        self.y += 4

    def stage_table(self, checks, keyed):
        columns = [0, 160, 240, 320, 400]
        rows = []
        for key, name in STAGES.items():
            counts = Counter(keyed[c["id"]]["status"] for c in checks if c["stage"] == key)
            if counts:
                rows.append([name, *[str(counts[status]) for status in FINAL]])
        self.room((len(rows) + 1) * 23 + 9)
        for idx, row in enumerate([["단계", "통과", "실패", "차단", "미실행"], *rows]):
            for col, value in zip(columns, row):
                self.line(self.left + 6 + col, self.y + 5, value, 9, strong=idx == 0)
            self.y += 23
            self.horizontal(self.y, weight=0.85 if idx == 0 else 0.5)
        self.y += 11

    def finish(self, output):
        total = len(self.doc)
        for i, page in enumerate(self.doc):
            self.page = page
            top = self.paper.height - 47
            self.horizontal(top)
            number = f"{i + 1:02d} / {total:02d}"
            self.line(self.right - self.measure(number, 8), top + 8, number, 8, DIM)

        # Fail before creating a file if any printed text was dropped or changed.
        self.doc.set_metadata({"title": "ITR | QA report", "producer": "ITR / PyMuPDF",
                               "keywords": "itr-layout=reader | Pretendard v1.3.9"})
        data = self.doc.tobytes(deflate=True, garbage=4)
        self.doc.close()
        def compact(text):
            return re.sub(r"\s+", "", text)
        with self.pdf.open(stream=data, filetype="pdf") as rendered:
            for page, expected in zip(rendered, self.expected):
                if compact(page.get_text()) != compact("".join(expected)):
                    raise ValueError(f"PDF page {page.number + 1} failed text round-trip. No output created.")
        with output.open("xb") as handle:
            handle.write(data)
        return total


def summary(sheet, record):
    inp, approval, decision = record["input"], record["approval"], record["decision"]
    defects = record["defects"]
    counts = Counter(item["status"] for item in record["results"])
    selected = sum(check.get("selected", True) for check in inp["checks"])
    x, width = sheet.left, sheet.width
    value_x, value_width = sheet.value_x, sheet.value_width
    sheet.new_page(cover=True)
    sheet.line(x, 77, "품질 검증 보고서", 31, strong=True)
    sheet.cover_text(x, 128, inp["product"], 14, width, lines=2)
    sheet.cover_text(x, 166, f'{record["round"]}차 / 시도 {record["attempt"]}  ·  {local_time(record["created_at"])}',
                     9.5, width, color=DIM)

    sheet.horizontal(195, weight=0.8)
    sheet.line(x, 209, "최종 기술 판정", 10, DIM)
    sheet.line(value_x, 205, STATUS_LABELS[decision["status"]], 17, strong=True)
    sheet.line(x, 239, "발주자·사용자 승인", 10, DIM)
    sheet.line(value_x, 237, APPROVAL[approval["status"]], 11.5, strong=True)
    sheet.line(x, 263, "판정 근거", 9.5, DIM)
    sheet.cover_text(value_x, 263, decision["reason"], 9.5, value_width, lines=2)

    sheet.line(x, 308, "전체 검사 집계", 11, strong=True)
    sheet.horizontal(329)
    metrics = [(STATUS_LABELS[key], counts[key]) for key in FINAL]
    metrics.append(("고유 결함", len({item["fingerprint"] for item in defects})))
    for index, (label, count) in enumerate(metrics):
        cell = x + index * (width / len(metrics))
        sheet.line(cell + 8, 339, label, 9.5, DIM)
        sheet.line(cell + 8, 359, str(count), 13, strong=True)
    sheet.horizontal(386)

    sheet.line(x, 407, "검증 대상과 범위", 13, strong=True)
    sheet.line(x, 434, "검사 범위", 9.5, DIM)
    sheet.cover_text(value_x, 433, f'{MODES[inp["mode"]]} 모드  ·  전체 {len(inp["checks"])}건  ·  선택 {selected}건',
                     10.5, value_width)
    sheet.line(x, 458, "대상 리비전", 9.5, DIM)
    sheet.cover_text(value_x, 457, inp["revision"], 9.5, value_width)

    sheet.horizontal(500)
    sheet.line(x, 517, "주요 결함과 다음 조치", 13, strong=True)
    if not defects:
        sheet.line(value_x, 546, "기록된 결함 없음", 10.5)
    for i, defect in enumerate(defects[:2]):
        top = 546 + 76 * i
        sheet.cover_text(x, top, defect["id"], 10.5, value_x - x - 12, strong=True)
        sheet.cover_text(value_x, top, defect["observed"], 10.5, value_width, lines=2)
        action = defect.get("minimal_fix") or defect.get("next_regression")
        sheet.line(x, top + 32, "다음 조치", 9.5, DIM)
        sheet.cover_text(value_x, top + 31, action or "기록 없음", 9.5, value_width, lines=2)
    if len(defects) > 2:
        sheet.line(value_x, 704, f"결함 상세에 나머지 {len(defects) - 2}건이 있습니다.", 9, DIM)

    pending = [item for item in record["results"] if item["status"] in {"blocked", "not_run"}]
    if pending and len(defects) <= 1:
        top = 643 if defects else 586
        sheet.horizontal(top)
        sheet.line(x, top + 16, "차단과 미실행", 13, strong=True)
        for i, item in enumerate(pending[:2]):
            y = top + 43 + i * 20
            sheet.line(x, y, STATUS_LABELS[item["status"]], 9.5, DIM)
            sheet.cover_text(value_x, y, item["detail"], 9.5, value_width)
        if len(pending) > 2:
            sheet.line(value_x, top + 84, f"검사 결과에 나머지 {len(pending) - 2}건이 있습니다.", 9, DIM)


def detail(sheet, record, digest, media):
    inp = record["input"]
    checks = inp["checks"]
    results = {item["check_id"]: item for item in record["results"]}
    sheet.new_page()
    sheet.section("검사 결과")
    sheet.stage_table(checks, results)
    for check in checks:
        outcome = results[check["id"]]
        status = outcome["status"]
        sheet.item(f'{STATUS_LABELS[status]}  |  {check["title"]}')
        sheet.field("검사", f'{check["id"]}  /  {STAGES[check["stage"]]}  /  {METHODS[check["method"]]}')
        sheet.field("통과 조건", check["pass_condition"])
        sheet.text(outcome["detail"], 10)
        sheet.field("기준 / 근거", f'{unique_ids(check["criteria"])}  /  {unique_ids(outcome["evidence_ids"])}')
        sheet.y += 5

    if record["defects"]:
        sheet.section("결함과 다음 조치")
    for defect in record["defects"]:
        sheet.item(defect["id"] + "  |  " + defect["observed"])
        for label, value in (("확인된 원인", defect.get("cause_confirmed")), ("가설", defect.get("hypothesis")),
                             ("다음 조치", defect.get("minimal_fix")), ("다음 회귀 검사", defect.get("next_regression"))):
            if value:
                sheet.field(label, value)
        sheet.field("기준 / 근거", f'{unique_ids(defect["baseline_ids"])}  /  {unique_ids(defect["evidence_ids"])}')
        sheet.y += 5

    sheet.section("실행 환경과 한계")
    if not inp["capabilities"]:
        sheet.text("기록된 실행 능력 없음", 10, DIM)
    for capability in inp["capabilities"]:
        sheet.field("지원" if capability["available"] else "미지원", capability["id"])
    for check in checks:
        outcome = results[check["id"]]
        if outcome["status"] in {"blocked", "not_run"}:
            sheet.field(STATUS_LABELS[outcome["status"]] + " / " + check["id"], outcome["detail"])
    for criterion in inp["baselines"]:
        sheet.field(f'{criterion["id"]} / {KINDS[criterion["kind"]]} {criterion["version"]}', criterion["text"])

    sheet.section("근거와 검증 식별자")
    if not record["evidence"]:
        sheet.text("기록된 근거 없음", 10, DIM)
    for item in record["evidence"]:
        preview = media[item["id"]]
        title = f'{item["id"]}  |  {item["check_id"]}'
        rows = [("원본", item["path"]), ("SHA-256", item["sha256"]), ("파일 대조", preview["status"])]
        if "launch_status" in preview:
            rows.append(("실행 인수", preview["launch_status"]))
        if results[item["check_id"]]["status"] == "failed" and "text" in preview:
            # Use only an intact, hash-matched structured observation.
            try:
                observation = json.loads(preview["text"])
            except ValueError:
                observation = {}
            if isinstance(observation, dict):
                for key, label in (("expected", "기대값"), ("observed", "실제값")):
                    if key in observation:
                        value = observation[key]
                        rows.append((label, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)))
        height = sum(13.5 * len(list(sheet.field_lines(label, value))) + 4 for label, value in rows)
        if height < 190:
            sheet.room(height + 26)
        sheet.item(title)
        for label, value in rows:
            sheet.field(label, value)
        sheet.y += 4

    sheet.section("원본 기록과 승인")
    sheet.field("검증 대상", inp["product"])
    sheet.field("실행 ID", record["run_id"])
    revision = inp["revision"]
    revision_size = 9 if re.fullmatch(r"sha256:[0-9a-f]{64}", revision) else 9.5
    sheet.field("대상 리비전", revision, size=revision_size)
    sheet.field("record.json SHA-256", digest)
    sheet.field("기술 판정 사유", record["decision"]["reason"])
    approval = record["approval"]
    sheet.field("발주자·사용자 승인", APPROVAL[approval["status"]])
    if approval.get("actor"):
        sheet.field("승인자 / 시각", f'{approval["actor"]}  /  {local_time(approval.get("at"))}')
    if approval.get("scope"):
        sheet.field("승인 범위", approval["scope"])
    if approval.get("evidence_ids"):
        sheet.field("승인 근거", unique_ids(approval["evidence_ids"]))
    if record.get("previous"):
        previous = record["previous"]
        sheet.field("이전 기록", f'{previous["type"]}  /  {previous["record_path"]}')
        sheet.field("이전 SHA-256", previous["sha256"])


def convert_reader(pymupdf, source, output):
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    source, output = source.resolve(), output.resolve()
    if source.parent == output.parent or source.parent in output.parents:
        raise ValueError("Reader PDF needs a new path outside the source attempt.")
    raw = source.read_bytes()
    digest = sha256(raw).hexdigest()
    record = json.loads(raw)
    validate(record)
    if source.name != "record.json" or read_json(source.with_name("COMPLETE.json"))["sha256"] != digest:
        raise ValueError("Reader PDF requires a sealed record with a matching SHA-256.")
    sheet = Sheet(pymupdf)
    summary(sheet, record)
    detail(sheet, record, digest, previews(record, source.parent))
    return sheet.finish(output)
