"""Minimal synthetic fixture distilling the 'text-box content dropped' gap found
on the real public corpus (`textbox`): a DrawingML text box (`w:drawing` →
`wps:txbx` → `w:txbxContent`) holds block text. The original extractor counted
the drawing as a *figure* and dropped the text inside it.

Authors `textbox.docx`: an intro paragraph + a paragraph whose run contains a
DrawingML text box wrapping the sentence "Boxed warehouse note 42 mm." A correct
extractor must (a) NOT count the text box as a figure and (b) extract its text.
Built per R8/§6.3 — fix Script 1 against this, not the real docs.

Run: guix shell -m evaluation/manifest.scm -- python3 evaluation/tests/fixtures/build_textbox.py
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import docx
from docx.oxml import parse_xml
from docx.oxml.ns import qn

HERE = Path(__file__).resolve().parent
DOCX_PATH = HERE / "textbox.docx"

_TEXTBOX_P = (
    '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
    ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    ' xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
    "<w:r><w:drawing><wp:inline distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\">"
    '<wp:extent cx="2000000" cy="500000"/><wp:docPr id="1" name="TextBox 1"/>'
    '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
    "<wps:wsp><wps:txbx><w:txbxContent>"
    "<w:p><w:r><w:t>Boxed warehouse note 42 mm.</w:t></w:r></w:p>"
    "</w:txbxContent></wps:txbx><wps:bodyPr/></wps:wsp>"
    "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
)


def build() -> None:
    doc = docx.Document()
    doc.add_paragraph("Intro paragraph before the text box.")

    body = doc.element.body
    sectpr = body.find(qn("w:sectPr"))
    p = parse_xml(_TEXTBOX_P)
    if sectpr is not None:
        sectpr.addprevious(p)
    else:
        body.append(p)

    buf = io.BytesIO()
    doc.save(buf)
    src = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    with zipfile.ZipFile(DOCX_PATH, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(src.namelist()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(info, src.read(name))
    print(f"wrote {DOCX_PATH.name} (DrawingML text box with text)")


if __name__ == "__main__":
    build()
