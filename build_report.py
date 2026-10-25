"""Optional report renderer; inference uses only Python's standard library."""
import argparse
import re
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle

ROOT = Path(__file__).resolve().parent


def inline(text):
    text = escape(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--font-dir', type=Path, required=True)
    args = parser.parse_args()
    for name, filename in [('Body', 'DejaVuSans.ttf'), ('BodyBold', 'DejaVuSans-Bold.ttf')]:
        pdfmetrics.registerFont(TTFont(name, str(args.font_dir / filename)))
    pdfmetrics.registerFontFamily('Body', normal='Body', bold='BodyBold')
    body = ParagraphStyle('Body', fontName='Body', fontSize=8.55, leading=12.1,
                          textColor=colors.HexColor('#202938'), spaceAfter=7)
    h1 = ParagraphStyle('Title', parent=body, fontName='BodyBold', fontSize=17,
                        leading=23, spaceAfter=14, textColor=colors.HexColor('#173656'))
    h2 = ParagraphStyle('Heading', parent=body, fontName='BodyBold', fontSize=10.2,
                        leading=14, spaceBefore=5, spaceAfter=7, keepWithNext=True)
    cell = ParagraphStyle('Cell', parent=body, fontSize=7.4, leading=10, spaceAfter=0)
    doc = SimpleDocTemplate(str(ROOT/'REPORT.pdf'), pagesize=A4,
                            leftMargin=39, rightMargin=39, topMargin=35, bottomMargin=38,
                            title='Постобработка OCR паспорта РФ', author='')
    parts = (ROOT/'REPORT.md').read_text(encoding='utf-8').split('\n\n')
    flow = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part == '<!-- PAGEBREAK -->':
            flow.append(PageBreak())
        elif part.startswith('# '):
            flow.append(Paragraph(inline(part[2:]), h1))
        elif part.startswith('## '):
            flow.append(Paragraph(inline(part[3:]), h2))
        elif part.startswith('|'):
            rows = [[Paragraph(inline(c.strip()), cell) for c in row.strip('|').split('|')]
                    for row in part.splitlines() if not re.match(r'^\|[-: |]+\|$', row)]
            table = Table(rows, colWidths=[210, 48, 60, 104, 95], repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8eef5')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f7fa')]),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]))
            flow.extend([table, Spacer(1, 10)])
        elif part.startswith('- '):
            for line in part.splitlines():
                flow.append(Paragraph(inline(line), ParagraphStyle('Source', parent=body, fontSize=7.0, leading=9.5)))
        else:
            flow.append(Paragraph(inline(part.replace('\n', ' ')), body))
    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor('#c8d2df'))
        canvas.line(39, 29, A4[0]-39, 29)
        canvas.setFont('Body', 7)
        canvas.setFillColor(colors.HexColor('#5b6778'))
        canvas.drawString(39, 18, 'OCR паспорта РФ | состояние на 01.10.2026')
        canvas.drawRightString(A4[0]-39, 18, str(doc.page))
    doc.build(flow, onFirstPage=footer, onLaterPages=footer)


if __name__ == '__main__':
    main()
