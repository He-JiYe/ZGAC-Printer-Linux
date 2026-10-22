"""Generate the public two-page A4 sample; no credentials or campus access.

Requires the dev extra and Ubuntu's fonts-droid-fallback package. The embedded
Chinese font's Apache notice and full license travel inside the PDF itself.
"""
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]
FONT = Path('/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf')
FONT_NOTICE = Path('/usr/share/doc/fonts-droid-fallback/copyright')
APACHE_LICENSE = Path('/usr/share/common-licenses/Apache-2.0')
INK, BLUE, MUTED = '#17243b', '#2563eb', '#637087'
WIDTH, HEIGHT = A4
LEFT, RIGHT = 20*mm, WIDTH-20*mm


def text(canvas, x, y, value, size=11, color=INK, font='Chinese'):
    line = canvas.beginText(x, y)
    line.setFillColor(colors.HexColor(color))
    # Droid is a CJK fallback: its Latin/digit glyphs are intentionally absent.
    # Use the standard PDF font for those runs instead of emitting blank glyphs.
    widths = pdfmetrics.getFont('Chinese').face.charWidths
    current, run = None, ''
    for char in value:
        chosen = font
        if font == 'Chinese':
            chosen = 'Chinese' if ord(char) > 127 and widths.get(ord(char), 0) else 'Helvetica'
            if '\u4e00' <= char <= '\u9fff' and chosen != 'Chinese':
                raise ValueError('The embedded font lacks a required Chinese glyph.')
        if chosen != current:
            if run:
                line.textOut(run)
            line.setFont(chosen, size)
            current, run = chosen, ''
        run += char
    line.textOut(run)
    canvas.drawText(line)


def frame(canvas, page):
    canvas.setStrokeColor(colors.HexColor('#c6ced9'))
    canvas.setLineWidth(0.5)
    canvas.rect(15*mm, 15*mm, WIDTH-30*mm, HEIGHT-30*mm)
    text(canvas, LEFT, HEIGHT-25*mm, 'ZGCA / PRINT TEST', 10, BLUE, 'Helvetica-Bold')
    text(canvas, LEFT, 21*mm, '中文字体已嵌入；字体许可随 PDF 附带。', 8, MUTED)
    text(canvas, RIGHT-27*mm, 21*mm, f'A4 / {page} OF 2', 8, MUTED, 'Helvetica')


def section(canvas, y, number, title):
    text(canvas, LEFT, y, number, 10, BLUE, 'Helvetica-Bold')
    text(canvas, LEFT+10*mm, y, title, 12)
    canvas.setStrokeColor(colors.HexColor('#dde3ec'))
    canvas.line(LEFT, y-4*mm, RIGHT, y-4*mm)


def ruler(canvas, x, y):
    canvas.setStrokeColor(colors.HexColor(INK))
    canvas.setLineWidth(0.7)
    canvas.line(x, y, x+100*mm, y)
    for value in range(0, 101, 5):
        length = 4 if value % 10 == 0 else 2
        canvas.line(x+value*mm, y, x+value*mm, y+length*mm)
        if value % 10 == 0:
            text(canvas, x+value*mm-2*mm, y-5*mm, str(value), 8, MUTED, 'Helvetica')


def main():
    if not all(path.is_file() for path in [FONT, FONT_NOTICE, APACHE_LICENSE]):
        raise SystemExit('Install fonts-droid-fallback and keep its system license files before generating the sample.')
    pdfmetrics.registerFont(TTFont('Chinese', str(FONT)))
    output = ROOT/'examples/print-test.pdf'
    output.parent.mkdir(parents=True, exist_ok=True)
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4, pageCompression=1, invariant=1)
    canvas.setTitle('ZGCA print test - A4 two pages')
    canvas.setAuthor('ZGCA Print contributors')
    frame(canvas, 1)
    text(canvas, LEFT, HEIGHT-43*mm, '打印测试页', 26)
    text(canvas, LEFT, HEIGHT-54*mm, '第 1 页：文字、灰阶与尺寸', 12, MUTED)
    text(canvas, LEFT, HEIGHT-65*mm, '首次建议：只打印本页，1 份，黑白，单面。', 10, MUTED)

    section(canvas, HEIGHT-83*mm, '01', '文字与符号')
    text(canvas, LEFT, HEIGHT-96*mm, '中文：学院自助打印，字体清晰，页面完整。', 13)
    text(canvas, LEFT, HEIGHT-107*mm, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 12, font='Helvetica')
    text(canvas, LEFT, HEIGHT-117*mm, 'abcdefghijklmnopqrstuvwxyz', 12, font='Helvetica')
    text(canvas, LEFT, HEIGHT-127*mm, '0123456789  /  1 + 2 = 3  /  @ # % & ( ) [ ]', 12, font='Helvetica')
    text(canvas, LEFT, HEIGHT-138*mm, '标点：，。！？；：“中文”（括号）【方括号】', 11)

    section(canvas, HEIGHT-156*mm, '02', '灰阶、色块与线条')
    y = HEIGHT-176*mm
    for index in range(6):
        value = index/5
        x = LEFT+index*25*mm
        canvas.setFillColor(colors.Color(value, value, value))
        canvas.rect(x, y, 20*mm, 9*mm, fill=1, stroke=0)
        text(canvas, x+3*mm, y-5*mm, f'{round((1-value)*100)}%', 8, MUTED, 'Helvetica')
    for index, color in enumerate(['#e23b3b', '#35a565', '#386bdd', '#e2c33d']):
        canvas.setFillColor(colors.HexColor(color))
        canvas.rect(LEFT+index*25*mm, y-20*mm, 20*mm, 7*mm, fill=1, stroke=0)
    text(canvas, LEFT+104*mm, y-18*mm, '黑白模式下应为灰阶', 9, MUTED)
    canvas.setStrokeColor(colors.black)
    for index, width in enumerate([0.25, 0.5, 1, 2]):
        canvas.setLineWidth(width)
        canvas.line(LEFT+index*40*mm, y-33*mm, LEFT+(index*40+30)*mm, y-33*mm)
        text(canvas, LEFT+index*40*mm, y-39*mm, f'{width:g} pt', 8, MUTED, 'Helvetica')

    section(canvas, 61*mm, '03', '尺寸与裁切')
    ruler(canvas, LEFT, 45*mm)
    text(canvas, LEFT+110*mm, 46*mm, '标尺总长 100 mm', 10, MUTED)
    text(canvas, LEFT, 33*mm, '选择实际大小 / 100% 缩放。外框应完整；缩放会改变标尺长度。', 9, MUTED)
    canvas.showPage()

    frame(canvas, 2)
    text(canvas, LEFT, HEIGHT-43*mm, '双面与顺序测试', 26)
    text(canvas, LEFT, HEIGHT-54*mm, '第 2 页：长边翻转时，本页应保持正向。', 12, MUTED)
    text(canvas, LEFT, HEIGHT-65*mm, '仅测第一页时无需打印本页；本页不包含任何个人信息。', 10, MUTED)
    cx, cy = WIDTH/2, HEIGHT/2+10*mm
    canvas.setFillColor(colors.HexColor(BLUE))
    path = canvas.beginPath()
    path.moveTo(cx, cy+32*mm)
    for x, y in [(cx+18*mm, cy+9*mm), (cx+7*mm, cy+9*mm), (cx+7*mm, cy-17*mm),
                 (cx-7*mm, cy-17*mm), (cx-7*mm, cy+9*mm), (cx-18*mm, cy+9*mm)]:
        path.lineTo(x, y)
    path.close()
    canvas.drawPath(path, fill=1, stroke=0)
    text(canvas, cx-25*mm, cy-35*mm, '此方向朝上', 22)
    text(canvas, cx-28*mm, cy-51*mm, 'PAGE 2 / BACK', 16, MUTED, 'Helvetica-Bold')
    section(canvas, 80*mm, '04', '请在取件后核对')
    for offset, line in enumerate([
        '两页顺序正确，正反面方向符合所选翻转方式。',
        '中文与英文无乱码、无缺字，细线和灰阶可辨认。',
        '页面未缺失、未明显裁切；纸张与份数符合预期。',
    ]):
        text(canvas, LEFT, (66-offset*10)*mm, line, 11)
    canvas.save()

    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(BytesIO(buffer.getvalue())))
    notice = ('Embedded subset: Droid Sans Fallback\n'
              'Subset embedded by ZGCA Print for this test document.\n\n'
              +FONT_NOTICE.read_text()+'\n\n'+APACHE_LICENSE.read_text())
    writer.add_attachment('Droid-font-LICENSE.txt', notice.encode('utf-8'))
    writer.write(output)
    print(output)


if __name__ == '__main__':
    main()
