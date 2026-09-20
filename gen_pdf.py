# -*- coding: utf-8 -*-
"""将「软件开发文档.md」渲染为 PDF，并附系统架构流程图 + E2EE 数据流流程图。

用法：.venv/bin/python gen_pdf.py
"""
import os
import sys

# 引用 pdf skill 的中文字体 helper
sys.path.insert(0, os.path.expanduser("~/.qclaw/skills/pdf/scripts"))
from setup_chinese_pdf import setup_chinese_pdf  # noqa: E402

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.enums import TA_CENTER, TA_LEFT  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    KeepTogether, Flowable,
)
from reportlab.graphics.shapes import (  # noqa: E402
    Drawing, Rect, String, Line, Polygon, Group,
)

HERE = os.path.dirname(os.path.abspath(__file__))
MD_PATH = os.path.join(HERE, "软件开发文档.md")
OUT_PATH = os.path.join(HERE, "软件开发文档.pdf")

cn_font, base_styles = setup_chinese_pdf()

# ---------- 样式 ----------
styles = {}
styles["title"] = ParagraphStyle("t", parent=base_styles["Title"], fontSize=22,
                                 leading=28, alignment=TA_CENTER, spaceAfter=6)
styles["subtitle"] = ParagraphStyle("s", parent=base_styles["Normal"], fontSize=10,
                                    textColor=colors.HexColor("#666666"),
                                    alignment=TA_CENTER, spaceAfter=18)
styles["h1"] = ParagraphStyle("h1", parent=base_styles["Heading1"], fontSize=16,
                              leading=22, spaceBefore=16, spaceAfter=8,
                              textColor=colors.HexColor("#1a3c6e"))
styles["h2"] = ParagraphStyle("h2", parent=base_styles["Heading2"], fontSize=13,
                              leading=18, spaceBefore=12, spaceAfter=6,
                              textColor=colors.HexColor("#2c5282"))
styles["h3"] = ParagraphStyle("h3", parent=base_styles["Heading3"], fontSize=11.5,
                              leading=16, spaceBefore=8, spaceAfter=4,
                              textColor=colors.HexColor("#3b5f8a"))
styles["body"] = ParagraphStyle("b", parent=base_styles["Normal"], fontSize=10,
                                leading=16, spaceAfter=6)
styles["bullet"] = ParagraphStyle("bl", parent=styles["body"], leftIndent=16,
                                  bulletIndent=4, spaceAfter=3)
styles["num"] = ParagraphStyle("n", parent=styles["body"], leftIndent=16, spaceAfter=3)
styles["code"] = ParagraphStyle("c", parent=base_styles["Code"], fontSize=8.5,
                                leading=11.5, backColor=colors.HexColor("#f5f5f5"),
                                borderPadding=6, spaceBefore=4, spaceAfter=8)
styles["quote"] = ParagraphStyle("q", parent=styles["body"],
                                 leftIndent=14, textColor=colors.HexColor("#555555"))
styles["cell"] = ParagraphStyle("cell", parent=base_styles["Normal"], fontSize=8.5,
                                leading=12)
styles["cellhead"] = ParagraphStyle("ch", parent=styles["cell"], textColor=colors.white)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------- 流程图绘制 ----------
def _box(d, x, y, w, h, text, fill, text_color=colors.white, font_size=9):
    d.add(Rect(x, y, w, h, rx=6, ry=6, fillColor=fill,
               strokeColor=colors.HexColor("#2c3e50"), strokeWidth=1))
    d.add(String(x + w / 2, y + h / 2 - font_size / 2 + 1, text,
                 fontName=cn_font, fontSize=font_size, fillColor=text_color,
                 textAnchor="middle"))


def _arrow(d, x1, y1, x2, y2, color=colors.HexColor("#555555")):
    d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=1.2))
    # 箭头
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    for da in (math.pi - 0.4, math.pi + 0.4):
        ax = x2 + 7 * math.cos(ang + da)
        ay = y2 + 7 * math.sin(ang + da)
        d.add(Line(x2, y2, ax, ay, strokeColor=color, strokeWidth=1.2))


def draw_arch_diagram():
    """系统架构流程图。"""
    W, H = 480, 330
    d = Drawing(W, H)
    blue = colors.HexColor("#2c5282")
    green = colors.HexColor("#2f855a")
    orange = colors.HexColor("#c05621")
    slate = colors.HexColor("#4a5568")

    # 第一层：浏览器
    _box(d, 40, 260, 400, 46, "", blue)
    _box(d, 46, 268, 190, 30, "浏览器（前端）", blue, font_size=10)
    _box(d, 240, 268, 194, 30, "Web Crypto 加密模块", green, font_size=9)
    _box(d, 240, 238, 194, 24, "AES-GCM / RSA-OAEP / PBKDF2", slate, font_size=8)

    _arrow(d, 240, 260, 240, 226)
    d.add(String(260, 244, "HTTPS (TLS 传输层)", fontName=cn_font, fontSize=8.5,
                 fillColor=colors.HexColor("#555555")))

    # 第二层：服务端
    _box(d, 40, 150, 400, 52, "", green)
    _box(d, 46, 158, 150, 36, "FastAPI 应用", green, font_size=10)
    _box(d, 204, 158, 110, 18, "认证 / 路由", slate, font_size=8)
    _box(d, 204, 176, 110, 18, "文件处理", slate, font_size=8)
    _box(d, 320, 158, 114, 18, "后台清理线程", orange, font_size=8)
    _box(d, 320, 176, 114, 18, "密码学工具", slate, font_size=8)

    _arrow(d, 240, 150, 240, 120)
    _arrow(d, 140, 150, 120, 96)
    _arrow(d, 340, 150, 360, 96)

    # 第三层：存储
    _box(d, 40, 70, 180, 36, "SQLite 数据库", orange, font_size=9)
    d.add(String(130, 58, "app.db（元数据 + 审计）", fontName=cn_font, fontSize=8,
                 fillColor=colors.HexColor("#555555"), textAnchor="middle"))
    _box(d, 260, 70, 180, 36, "磁盘密文存储", slate, font_size=9)
    d.add(String(350, 58, "*.bin（AES-GCM 密文）", fontName=cn_font, fontSize=8,
                 fillColor=colors.HexColor("#555555"), textAnchor="middle"))

    _box(d, 40, 20, 400, 24, "服务端永不接触明文 / 明文 fileKey", colors.HexColor("#9b2c2c"), font_size=9)
    return d


def draw_e2ee_diagram():
    """E2EE 数据流流程图（上传 / 下载 / 共享）。"""
    W, H = 480, 470
    d = Drawing(W, H)
    blue = colors.HexColor("#2c5282")
    green = colors.HexColor("#2f855a")
    purple = colors.HexColor("#6b46c1")
    slate = colors.HexColor("#4a5568")
    red = colors.HexColor("#9b2c2c")

    d.add(String(240, H - 12, "端到端加密（E2EE）核心数据流", fontName=cn_font,
                 fontSize=13, fillColor=colors.HexColor("#1a3c6e"), textAnchor="middle"))

    # —— 上传流程 ——
    d.add(String(30, H - 40, "① 上传流程", fontName=cn_font, fontSize=11,
                 fillColor=blue, textAnchor="start"))
    _box(d, 30, H - 108, 150, 40, "明文文件", slate, font_size=9)
    _box(d, 210, H - 108, 240, 40, "浏览器生成随机 fileKey\nAES-256-GCM 加密 → 密文", green, font_size=8)
    _box(d, 30, H - 180, 150, 40, "随机 fileKey", purple, font_size=9)
    _box(d, 210, H - 180, 240, 40, "用自己的 RSA 公钥\nOAEP 封装 fileKey → wrapped_key", blue, font_size=8)
    _box(d, 30, H - 252, 420, 36, "上传到服务端：密文 + wrapped_key + iv + 元数据", slate, font_size=9)

    _arrow(d, 180, H - 88, 210, H - 88)
    _arrow(d, 105, H - 108, 105, H - 140)
    _arrow(d, 105, H - 140, 210, H - 160)

    # —— 下载流程 ——
    d.add(String(30, H - 300, "② 下载流程", fontName=cn_font, fontSize=11,
                 fillColor=blue, textAnchor="start"))
    _box(d, 30, H - 336, 180, 30, "服务端返回密文 + wrapped_key", slate, font_size=8)
    _box(d, 230, H - 336, 220, 30, "口令派生 KEK → 解密私钥", purple, font_size=8)
    _box(d, 30, H - 390, 180, 30, "私钥解封 fileKey", purple, font_size=8)
    _box(d, 230, H - 390, 220, 30, "fileKey + iv 解密密文 → 明文", green, font_size=8)

    _arrow(d, 210, H - 321, 230, H - 321)
    _arrow(d, 120, H - 336, 120, H - 360)
    _arrow(d, 210, H - 375, 230, H - 375)

    # —— 共享流程 ——
    d.add(String(30, H - 428, "③ 多接收方共享", fontName=cn_font, fontSize=11,
                 fillColor=blue, textAnchor="start"))
    _box(d, 30, H - 462, 200, 28, "Owner 解封 fileKey", purple, font_size=8)
    _box(d, 250, H - 462, 200, 28, "用接收方公钥重新封装 fileKey", blue, font_size=8)
    _arrow(d, 230, H - 448, 250, H - 448)
    d.add(String(240, H - 470, "每个有权用户各自独立封装一份 fileKey", fontName=cn_font,
                 fontSize=8, fillColor=red, textAnchor="middle"))
    return d


class DiagramFlowable(Flowable):
    def __init__(self, drawing):
        super().__init__()
        self.d = drawing
        self.width = drawing.width
        self.height = drawing.height

    def wrap(self, availWidth, availHeight):
        self.width = min(self.d.width, availWidth)
        self.height = self.d.height
        return self.width, self.height

    def draw(self):
        self.canv.saveState()
        self.canv.translate((self.canv._pagesize[0] - self.d.width) / 2
                            if False else 0, 0)
        self.d.drawOn(self.canv, 0, 0)
        self.canv.restoreState()


# ---------- Markdown 渲染 ----------
def render_markdown(lines):
    story = []
    i = 0
    n = len(lines)

    # 封面标题
    story.append(Paragraph("内网加密文件传输系统", styles["title"]))
    story.append(Paragraph("软件开发文档（SDD）· v0.2.0", styles["subtitle"]))
    story.append(Spacer(1, 8))

    while i < n:
        line = lines[i].rstrip("\n")

        # 代码块
        if line.strip().startswith("```"):
            buf = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i].rstrip("\n"))
                i += 1
            i += 1  # 跳过结束 ```
            code = "\n".join(buf)
            story.append(Paragraph("<br/>".join(esc(l) for l in code.split("\n")),
                                   styles["code"]))
            continue

        # 表格
        if line.strip().startswith("|") and i + 1 < n and \
           lines[i + 1].strip().startswith("|") and \
           set(lines[i + 1].strip().replace("|", "").replace("-", "").replace(":", "").strip()) == set():
            tbl = [line]
            i += 1
            # 跳过分隔行
            while i < n and lines[i].strip().startswith("|"):
                tbl.append(lines[i])
                i += 1
            story.append(build_table(tbl))
            story.append(Spacer(1, 8))
            continue

        s = line.strip()

        # 标题
        if s.startswith("#### "):
            story.append(Paragraph(esc(s[5:]), styles["h3"]))
        elif s.startswith("### "):
            story.append(Paragraph(esc(s[4:]), styles["h3"]))
        elif s.startswith("## "):
            story.append(Paragraph(esc(s[3:]), styles["h2"]))
        elif s.startswith("# "):
            story.append(Paragraph(esc(s[2:]), styles["h1"]))
        # 分隔线
        elif s == "---":
            story.append(Spacer(1, 6))
        # 引用
        elif s.startswith("> "):
            story.append(Paragraph(esc(s[2:]), styles["quote"]))
        # 无序列表
        elif s.startswith("- "):
            story.append(Paragraph("• " + inline(s[2:]), styles["bullet"]))
        # 有序列表
        elif len(s) >= 3 and s[0].isdigit() and s[1] == "." and s[2] == " ":
            story.append(Paragraph(esc(s), styles["num"]))
        # 复选框
        elif s.startswith("- [ ]") or s.startswith("- [x]"):
            mark = "☑" if s.startswith("- [x]") else "☐"
            story.append(Paragraph(mark + " " + inline(s[6:]), styles["bullet"]))
        elif s == "":
            pass
        else:
            story.append(Paragraph(inline(s), styles["body"]))
        i += 1

    return story


def inline(s):
    """处理行内代码与加粗。"""
    import re
    # 行内代码 `x`
    s = re.sub(r"`([^`]+)`", r'<font face="Courier" size="8.5">\1</font>', s)
    # 加粗 **x**
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    return esc(s)


def build_table(lines):
    def cells(row):
        return [c.strip() for c in row.strip().strip("|").split("|")]

    header = cells(lines[0])
    data = [cells(l) for l in lines[1:]]
    ncol = len(header)

    # 可用宽度 A4 - 边距
    avail = 595 - 90
    colw = avail / ncol

    head_cells = [Paragraph(inline(h), styles["cellhead"]) for h in header]
    rows = [head_cells]
    for row in data:
        r = []
        for j in range(ncol):
            v = row[j] if j < len(row) else ""
            r.append(Paragraph(inline(v), styles["cell"]))
        rows.append(r)

    t = Table(rows, colWidths=[colw] * ncol, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c5282")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
    ]))
    return t


def main():
    with open(MD_PATH, encoding="utf-8") as f:
        lines = f.readlines()

    story = render_markdown(lines)

    # 在文档末尾追加流程图（单独一页）
    story.append(PageBreak())
    story.append(Paragraph("附录 C：系统架构流程图", styles["h1"]))
    story.append(Spacer(1, 6))
    story.append(DiagramFlowable(draw_arch_diagram()))
    story.append(Spacer(1, 20))
    story.append(Paragraph("附录 D：E2EE 数据流流程图", styles["h1"]))
    story.append(Spacer(1, 6))
    story.append(DiagramFlowable(draw_e2ee_diagram()))

    doc = SimpleDocTemplate(OUT_PATH, pagesize=A4,
                            leftMargin=45, rightMargin=45,
                            topMargin=45, bottomMargin=45,
                            title="内网加密文件传输系统 软件开发文档",
                            author="AI Engineer")
    doc.build(story)
    print("PDF saved:", OUT_PATH)
    print("size:", os.path.getsize(OUT_PATH), "bytes")


if __name__ == "__main__":
    main()
