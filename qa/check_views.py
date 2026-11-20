"""Compare an ITR record with its Markdown, HTML replay, print view and optional PDF."""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata


STAGES = {
    "unit": "단위", "integration": "통합", "system": "시스템",
    "intersystem": "시스템 간 통합", "acceptance": "인수 시나리오",
}
FINAL = ("passed", "failed", "blocked", "not_run")


class ReadPrint(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.in_main = False

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.in_main = True

    def handle_endtag(self, tag):
        if tag == "main":
            self.in_main = False

    def handle_data(self, data):
        if self.in_main:
            self.parts.append(data)


def compact(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).replace("\u00ad", "")


def require(ok, explanation):
    if not ok:
        raise ValueError(explanation)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("record", type=Path)
    ap.add_argument("directory", type=Path)
    ap.add_argument("--pdf", action="store_true", help="Also verify report.pdf using PyMuPDF")
    args = ap.parse_args()
    raw = args.record.read_bytes()
    record = json.loads(raw)
    digest = sha256(raw).hexdigest()
    directory = args.directory
    replay = (directory / "replay.html").read_text(encoding="utf-8")
    # The renderer writes its canonical payload as a single JSON object.
    pos = replay.index('{"record":')
    payload, _ = json.JSONDecoder().raw_decode(replay[pos:])
    require(payload["record"] == record and payload["digest"] == digest, "replay payload or hash differs")
    markdown = (directory / "report.md").read_text(encoding="utf-8")
    print_reader = ReadPrint()
    print_reader.feed((directory / "print.html").read_text(encoding="utf-8"))
    outputs = {"report.md": compact(markdown), "print.html": compact(" ".join(print_reader.parts))}
    pages = None
    if args.pdf:
        import pymupdf
        with pymupdf.open(directory / "report.pdf") as doc:
            pages = len(doc)
            require(pages > 0, "empty PDF")
            # Drop only the repeated footer produced by qa/print_pdf.py. Keep
            # the full report content, including hashes and every event.
            body = [re.sub(r"\nITR\s*/\s*QA RECORD\n\d+\s*/\s*\d+\s*$", "", page.get_text())
                    for page in doc]
            outputs["report.pdf"] = compact(" ".join(body))
            require(outputs["report.pdf"] == outputs["print.html"], "full PDF body differs from print view")

    created = datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
    local_time = created.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S KST")
    aggregate = len({d["fingerprint"] for d in record["defects"]})
    markers = [digest, f'{record["round"]}차 / 시도 {record["attempt"]}', local_time,
               f"고유 결함 {aggregate}건", *[e["sha256"] for e in record["evidence"]]]
    for file, text in outputs.items():
        for marker in markers:
            require(compact(marker) in text, f"{file} missing {marker!r}")

    results = {result["check_id"]: result["status"] for result in record["results"]}
    for stage, label in STAGES.items():
        counts = Counter(results[c["id"]] for c in record["input"]["checks"] if c["stage"] == stage)
        if not counts:
            continue
        cells = [label, *[str(counts[s]) for s in FINAL]]
        for file, text in outputs.items():
            row = "|".join(cells) if file == "report.md" else "".join(cells)
            require(compact(row) in text, f"{file} missing stage totals {cells!r}")
    print(f"OK {digest} · {len(results)} checks · {aggregate} unique defects"
          + (f" · {pages} PDF pages" if pages else ""))


if __name__ == "__main__":
    main()
