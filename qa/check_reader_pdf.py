"""Check the A4 reader profile without changing any source attempt."""

from hashlib import sha256
from pathlib import Path
import json
import shutil
import tempfile

import pymupdf

from reader_pdf import convert_reader

ROOT = Path(__file__).resolve().parents[1]
FAILED = ROOT / "examples/runs/round-0001/attempt-0001/record.json"
BLOCKED = ROOT / "examples/runs/round-0002/attempt-0001/record.json"
PASSED = ROOT / "examples/project-runs/round-0001/attempt-0001/record.json"
REGULAR = "Pretendard-Regular"
SEMIBOLD = "Pretendard-SemiBold"


def fingerprints(directory):
    return {file.relative_to(directory): sha256(file.read_bytes()).digest()
            for file in directory.rglob("*") if file.is_file()}


def compact(text):
    return "".join(text.split())


def inspect(source, output, cover_tokens, metrics):
    original = fingerprints(source.parent)
    count = convert_reader(pymupdf, source, output)
    with pymupdf.open(output) as document:
        assert len(document) == count >= 2
        cover = compact(document[0].get_text())
        assert all(compact(token) in cover for token in cover_tokens)
        embedded = {
            xref: document.extract_font(xref)[3]
            for xref in {row[0] for page in document for row in page.get_fonts()}
        }
        originals = {p.read_bytes() for p in (ROOT / "assets" / "fonts").glob("Pretendard-*.ttf")}
        assert len(embedded) == len(originals) == 2 and set(embedded.values()) == originals
        spans = []
        content = []
        for page in document:
            assert page.rect == pymupdf.paper_rect("A4") and page.rotation == 0
            assert f"{page.number + 1:02d}/{count:02d}" in compact(page.get_text())
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    x0, y0, x1, y1 = line["bbox"]
                    assert x0 >= 44 and x1 <= page.rect.width - 44
                    assert y0 >= 32 and y1 <= page.rect.height - 20
                    for span in line["spans"]:
                        assert span["font"] in {REGULAR, SEMIBOLD}
                        value = compact(span["text"])
                        spans.append((page.number, span["font"], value, span["size"]))
                        if 54 < y0 < page.rect.height - 62:
                            content.append(value)
        assert any(row[:3] == (0, SEMIBOLD, "품질검증보고서") for row in spans)
        assert any(page > 0 and font == REGULAR and value == "발주자·사용자승인"
                   for page, font, value, _ in spans)
        assert [value for page, font, value, size in spans
                if page == 0 and font == SEMIBOLD and size == 13 and value.isdecimal()] == metrics
        body = "".join(content)
    assert compact("record.json SHA-256") in body
    assert sha256(source.read_bytes()).hexdigest() in body
    assert fingerprints(source.parent) == original
    return count, body


def main():
    with tempfile.TemporaryDirectory(prefix="itr-reader-pdf-") as temp:
        root = Path(temp)
        failed = root / "failed.pdf"
        fail_pages, fail = inspect(FAILED, failed, (
            "최종 기술 판정", "실패", "발주자·사용자 승인", "요청 전",
            "전체 검사 집계", "D-001", "무료 배송 비교식에 같은 금액을 포함한다.",
            "차단", "미실행"), ["7", "2", "1", "1", "1"])
        assert "10,000원주문에배송비3,000원이청구됨." in fail
        assert "기대값[3000,0,0]" in fail and "실제값[3000,3000,0]" in fail
        with pymupdf.open(failed) as document:
            assert any(span["font"] == REGULAR and compact(span["text"]) == "10,000원주문에배송비3,000원이청구됨."
                       for page in document for block in page.get_text("dict")["blocks"]
                       for line in block.get("lines", []) for span in line["spans"])

        pass_pages, passed = inspect(PASSED, root / "passed.pdf", (
            "최종 기술 판정", "통과", "요청 전", "기록된 결함 없음"), ["2", "0", "0", "0", "0"])
        assert "기존증거·실제실행인수미기록" in passed

        block_pages, _ = inspect(BLOCKED, root / "blocked.pdf", (
            "최종 기술 판정", "차단", "기록된 결함 없음", "미실행"), ["9", "0", "1", "1", "0"])

        # Exercise long tokens and empty sections with a new synthetic attempt.
        copy = root / "stress-attempt"
        shutil.copytree(PASSED.parent, copy)
        source = copy / "record.json"
        record = json.loads(source.read_bytes())
        token = "QA검산9" * 225 + "Tail-END"
        record["input"]["revision"] = token
        record["input"]["checks"][0]["pass_condition"] = token + " 한영 혼용 − 경계"
        record["evidence"] = []
        record["reviews"] = []
        record["input"]["capabilities"] = []
        record["decision"] = {"status": "not_run", "reason": "합성 서식 시험에서 검사 실행을 제외했다."}
        record["events"] = []
        for check, outcome in zip(record["input"]["checks"], record["results"]):
            check["selected"] = False
            check["requires"] = []
            outcome.update(status="not_run", detail="합성 서식 검증용으로 실행 범위에서 제외.", evidence_ids=[])
            for status in ("queued", "not_run"):
                record["events"].append({"seq": len(record["events"]) + 1, "at": record["created_at"],
                                         "check_id": check["id"], "state": status, "message": outcome["detail"]})
        raw = json.dumps(record, ensure_ascii=False).encode("utf-8")
        source.write_bytes(raw)
        (copy / "COMPLETE.json").write_text(json.dumps({"sha256": sha256(raw).hexdigest()}), encoding="utf-8")
        long_pages, report = inspect(source, root / "long.pdf", ("기록된 결함 없음", "리비전"),
                                     ["0", "0", "0", "2", "0"])
        assert token in report and "한영혼용−경계" in report and "기록된근거없음" in report
        assert "기록된실행능력없음" in report

        old = failed.read_bytes()
        try:
            convert_reader(pymupdf, FAILED, failed)
        except FileExistsError:
            pass
        else:
            raise AssertionError("reader profile must never replace a PDF")
        assert failed.read_bytes() == old
        try:
            convert_reader(pymupdf, source, copy / "report.pdf")
        except ValueError:
            pass
        else:
            raise AssertionError("reader profile must keep outputs outside source attempts")
        print(f"reader profiles: failed {fail_pages}, passed {pass_pages}, blocked {block_pages}, long {long_pages}")


if __name__ == "__main__":
    main()
