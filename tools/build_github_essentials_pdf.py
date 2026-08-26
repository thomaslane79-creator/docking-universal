#!/usr/bin/env python3
"""Build the GitHub essentials PDF from its maintained Markdown source."""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
)


NAVY = colors.HexColor("#17324d")
BLUE = colors.HexColor("#1678ad")
TEAL = colors.HexColor("#07877e")
PALE = colors.HexColor("#eaf5f3")
CODE_BG = colors.HexColor("#f1f4f7")
TEXT = colors.HexColor("#1d2730")


def inline_markup(value: str) -> str:
    value = html.escape(value, quote=False)
    value = re.sub(r"\[([^]]+)\]\(([^)]+)\)", r'<link href="\2" color="#1678ad">\1</link>', value)
    value = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    return value


def parse_markdown(source: Path, styles: dict[str, ParagraphStyle]):
    lines = source.read_text(encoding="utf-8").splitlines()
    story = []
    paragraph: list[str] = []
    code: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if paragraph:
            story.append(Paragraph(inline_markup(" ".join(part.strip() for part in paragraph)), styles["BodyText"] ))
            story.append(Spacer(1, 0.08 * inch))
            paragraph.clear()

    for line in lines:
        if line.startswith("```"):
            flush_paragraph()
            if in_code:
                story.append(Preformatted("\n".join(code), styles["Code"]))
                story.append(Spacer(1, 0.12 * inch))
                code.clear()
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
            continue
        if line.strip() == "<!-- pagebreak -->":
            flush_paragraph()
            story.append(PageBreak())
            continue
        if not line.strip():
            flush_paragraph()
            continue
        if line.startswith("# "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line[2:]), styles["Title"]))
            story.append(HRFlowable(width="100%", thickness=1.4, color=TEAL, spaceAfter=10))
        elif line.startswith("## "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line[3:]), styles["Heading2"]))
        elif line.startswith("### "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line[4:]), styles["Heading3"]))
        elif line.startswith("- "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line[2:]), styles["Bullet"], bulletText="•"))
        else:
            paragraph.append(line)
    flush_paragraph()
    return story


def build(source: Path, output: Path) -> None:
    sample = getSampleStyleSheet()
    styles = {
        "Title": ParagraphStyle("Title", parent=sample["Title"], fontName="Helvetica-Bold", fontSize=28, leading=32, textColor=NAVY, alignment=TA_LEFT, spaceAfter=12),
        "Heading2": ParagraphStyle("Heading2", parent=sample["Heading2"], fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=NAVY, spaceBefore=10, spaceAfter=8),
        "Heading3": ParagraphStyle("Heading3", parent=sample["Heading3"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=BLUE, spaceBefore=7, spaceAfter=5),
        "BodyText": ParagraphStyle("BodyText", parent=sample["BodyText"], fontName="Helvetica", fontSize=10.2, leading=14.2, textColor=TEXT, spaceAfter=2),
        "Bullet": ParagraphStyle("Bullet", parent=sample["BodyText"], fontName="Helvetica", fontSize=10.2, leading=14.2, textColor=TEXT, leftIndent=16, firstLineIndent=-8, bulletIndent=4, spaceAfter=5),
        "Code": ParagraphStyle("Code", parent=sample["Code"], fontName="Courier", fontSize=8.8, leading=12, leftIndent=12, rightIndent=12, borderColor=colors.HexColor("#c6d2dc"), borderWidth=0.5, borderPadding=8, backColor=CODE_BG, spaceBefore=3, spaceAfter=5),
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(output), pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch, topMargin=0.72 * inch, bottomMargin=0.62 * inch, title="GitHub Essentials for Docking Universal", author="Docking Universal")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")

    def decorate(canvas, document):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, letter[1] - 0.16 * inch, letter[0], 0.16 * inch, stroke=0, fill=1)
        canvas.setStrokeColor(colors.HexColor("#cbd5dd"))
        canvas.line(doc.leftMargin, 0.43 * inch, letter[0] - doc.rightMargin, 0.43 * inch)
        canvas.setFillColor(colors.HexColor("#526270"))
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(doc.leftMargin, 0.28 * inch, "Docking Universal — GitHub essentials for scientific users")
        canvas.drawRightString(letter[0] - doc.rightMargin, 0.28 * inch, f"Page {document.page}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="standard", frames=[frame], onPage=decorate)])
    doc.build(parse_markdown(source, styles))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("docs/github-essentials.md"))
    parser.add_argument("--out", type=Path, default=Path("docs/assets/github-essentials-for-docking-universal.pdf"))
    args = parser.parse_args()
    build(args.source, args.out)


if __name__ == "__main__":
    main()
