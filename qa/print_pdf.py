"""Convert a local ITR print.html to a new A4 PDF (optional: PyMuPDF)."""

import argparse
from io import BytesIO
from pathlib import Path
import html
import re
import unicodedata

from check_views import ReadPrint, compact


def wrap_pre(match):
    """Fold preformatted evidence by display width for the MuPDF print engine."""
    text = html.unescape(match.group(1))
    folded = []
    width = 0
    for char in text:
        cells = 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
        if char == "\n":
            width = 0
        else:
            if width + cells > 76:
                folded.append("\n")
                width = 0
            width += cells
        folded.append(char)
    return "<pre>" + html.escape("".join(folded)) + "</pre>"


FLOW_CSS = (
    "body{font-family:sans-serif;color:#172b27}h1,h2{color:#174d40}"
    "h2{border-bottom:0.5pt solid #c8d1c7}th{text-align:left}"
    "pre{font:8pt monospace}img{max-width:100%}"
)


def render_story(pymupdf, markup, sheet, body):
    story = pymupdf.Story(markup, em=10)
    stream = BytesIO()
    writer = pymupdf.DocumentWriter(stream)
    more = True
    pages = 0
    while more:
        device = writer.begin_page(sheet)
        more, occupied = story.place(body)
        if more and occupied[3] <= body.y0:
            raise ValueError("HTML layout made no progress.")
        story.draw(device)
        writer.end_page()
        pages += 1
        if pages >= 1000:
            raise ValueError("PDF exceeds the supported 999 pages.")
    writer.close()

    return stream.getvalue(), pages


def convert(source: Path, output: Path) -> int:
    try:
        import pymupdf
    except ImportError as exc:
        raise SystemExit("This optional export requires PyMuPDF.") from exc

    if output.exists():
        raise FileExistsError(output)
    source_html = source.read_text(encoding="utf-8")
    parser = ReadPrint()
    parser.feed(source_html)
    expected = compact(" ".join(parser.parts))
    if not expected:
        raise ValueError("ITR print HTML is missing its report body.")

    # MuPDF Story can skip a block across a page boundary in some combinations
    # of heading sizes, margins and table layout. Verify all characters before
    # publishing. Retry with simpler typography while keeping the exact HTML body.
    sheet = pymupdf.paper_rect("A4")
    body = sheet + (44, 42, -44, -49)
    markup = re.sub(r"<pre>(.*?)</pre>", wrap_pre, source_html, flags=re.DOTALL)
    flow = re.sub(r"<style>.*?</style>", "<style>" + FLOW_CSS + "</style>", markup,
                  count=1, flags=re.DOTALL)
    for layout, candidate in (("source", markup), ("simple-flow", flow)):
        rendered, pages = render_story(pymupdf, candidate, sheet, body)
        with pymupdf.open(stream=rendered, filetype="pdf") as draft:
            actual = compact(" ".join(page.get_text() for page in draft))
        if actual == expected:
            break
    else:
        raise ValueError("PDF layout omitted or altered report text; no output was created.")

    with pymupdf.open(stream=rendered, filetype="pdf") as document:
        document.set_metadata({"title": "ITR | QA record", "producer": "ITR / PyMuPDF",
                               "keywords": "itr-layout=" + layout})
        for page in document:
            page.draw_line((44, sheet.height - 37), (sheet.width - 44, sheet.height - 37),
                           color=(0.75, 0.79, 0.79), width=0.5)
            page.insert_text((44, sheet.height - 24), "ITR  /  QA RECORD",
                             fontsize=8, color=(0.22, 0.29, 0.3))
            page.insert_textbox(pymupdf.Rect(sheet.width - 151, sheet.height - 32,
                                             sheet.width - 44, sheet.height - 14),
                                f"{page.number + 1} / {len(document)}", fontsize=8,
                                align=pymupdf.TEXT_ALIGN_RIGHT, color=(0.22, 0.29, 0.3))
        # MuPDF embeds its Korean fallback face. Keep its original glyph mapping.
        payload = document.tobytes(garbage=4, deflate=True)
    with output.open("xb") as target:
        target.write(payload)
    return pages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("audit", "reader"), default="audit",
                        help="audit reads print.html; reader reads a sealed record.json")
    parser.add_argument("source", type=Path, help="Local print.html or sealed record.json")
    parser.add_argument("output", type=Path, help="New PDF file")
    args = parser.parse_args()
    if args.profile == "reader":
        try:
            import pymupdf
        except ImportError as exc:
            raise SystemExit("This optional export requires PyMuPDF.") from exc
        from reader_pdf import convert_reader
        pages = convert_reader(pymupdf, args.source, args.output)
    else:
        pages = convert(args.source, args.output)
    print(f"{args.output} ({pages} pages)")


if __name__ == "__main__":
    main()
