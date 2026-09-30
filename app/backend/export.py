"""Rendered Markdown draft -> Word document (python-docx)."""

import io
import re

from docx import Document
from docx.shared import Pt

_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _add_runs(paragraph, text):
    pos = 0
    for m in _BOLD.finditer(text):
        if m.start() > pos:
            paragraph.add_run(text[pos:m.start()])
        paragraph.add_run(m.group(1)).bold = True
        pos = m.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


def to_docx(title, subtitle_lines, markdown, footer=""):
    doc = Document()
    doc.styles["Normal"].font.name = "Arial"
    doc.styles["Normal"].font.size = Pt(11)
    doc.add_heading(title, level=0)
    for line in subtitle_lines:
        p = doc.add_paragraph()
        p.add_run(line).bold = True
    for block in re.split(r"\n\s*\n", markdown.strip()):
        lines = block.splitlines()
        if all(l.lstrip().startswith(("- ", "* ")) for l in lines if l.strip()):
            for l in lines:
                if l.strip():
                    _add_runs(doc.add_paragraph(style="List Bullet"), l.lstrip()[2:])
            continue
        first = lines[0]
        heading = re.match(r"^(#{1,4})\s+(.*)", first)
        if heading:
            doc.add_heading(heading.group(2), level=min(len(heading.group(1)), 3))
            lines = lines[1:]
        if lines:
            _add_runs(doc.add_paragraph(), " ".join(l.strip() for l in lines))
    if footer:
        doc.add_paragraph().add_run(footer).italic = True
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
