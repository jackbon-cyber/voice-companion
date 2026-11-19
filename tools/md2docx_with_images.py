"""Markdown -> Word (docx) 转换器：针对本项目文档结构优化
支持：标题层级、表格（含合并首列为表头的简单表格）、代码块、有序/无序列表、
      引用块、加粗、行内代码、水平线、复选框行。
"""
import os
import re
import sys

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm

MONO = "Consolas"
EAST = "微软雅黑"
BODY = "等线"


def set_cjk(run, font_name=BODY, size=None, bold=None, color=None):
    run.font.name = font_name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), font_name)
    rfonts.set(qn("w:ascii"), font_name)
    rfonts.set(qn("w:hAnsi"), font_name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor(*color)


INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")


def add_inline(par, text, base_size=10.5, base_bold=False, mono_color=(0x1F, 0x4E, 0x79)):
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            r = par.add_run(part[2:-2])
            set_cjk(r, BODY, base_size, True)
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            r = par.add_run(part[1:-1])
            set_cjk(r, MONO, base_size - 0.5, base_bold, mono_color)
        else:
            r = par.add_run(part)
            set_cjk(r, BODY, base_size, base_bold)


def is_table_row(line):
    return line.strip().startswith("|") and line.strip().endswith("|")


def split_row(line):
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def is_sep(line):
    return is_table_row(line) and re.fullmatch(r"\|[\s:\-|]+\|", line.strip()) is not None


# 一级标题里带章节编号（1. / ⓪ / 附录 / 第X章）的是"章"，需要与文档名区分开
CIRCLED = "\u2460\u2461\u2462\u2463\u2464\u2465\u2466\u2467\u2468\u24ea\u24eb\u24ec\u24ed\u24ee\u24ef"
CHAPTER_RE = re.compile(
    r"^(?:[0-9]{1,2}\.\s|[" + CIRCLED + r"]|附录|第\s*[0-9一二三四五六七八九十]+\s*[章节節])"
)


def is_chapter(text):
    return bool(CHAPTER_RE.match(text.strip()))


def build(doc, md_text, base_dir="."):
    lines = md_text.split("\n")
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # 分页标记
        if stripped == "<!-- PAGEBREAK -->":
            doc.add_page_break()
            i += 1
            continue

        # 图片：![alt](relative/path.png)
        m_img = re.match(r"^!\[(.*?)\]\((.*?)\)\s*$", stripped)
        if m_img:
            img_path = m_img.group(2)
            if not os.path.isabs(img_path):
                img_path = os.path.join(base_dir, img_path)
            if os.path.exists(img_path):
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(6)
                p.paragraph_format.space_after = Pt(2)
                p.add_run().add_picture(img_path, width=Cm(16.0))
            else:
                p = doc.add_paragraph()
                add_inline(p, "[图片缺失] " + img_path, 10.5)
            i += 1
            continue

        # 代码块：开启围栏可带语言标注（```bash），闭合围栏必须为裸 ```
        if stripped.startswith("```"):
            i += 1
            buf = []
            while i < n:
                cur = lines[i].strip()
                # 裸围栏即闭合；带语言标注的是新的开启围栏，视为内容不闭合
                if cur == "```":
                    i += 1
                    break
                buf.append(lines[i])
                i += 1
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.6)
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.line_spacing = 1.0
            r = p.add_run("\n".join(buf))
            set_cjk(r, MONO, 9)
            r.font.color.rgb = RGBColor(0x1F, 0x1F, 0x1F)
            ppr = p._element.get_or_add_pPr()
            shd = ppr.makeelement(qn("w:shd"), {})
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:fill"), "F4F6F8")
            ppr.append(shd)
            continue

        # 水平线
        if re.fullmatch(r"-{3,}", stripped):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(6)
            ppr = p._element.get_or_add_pPr()
            pbdr = ppr.makeelement(qn("w:pBdr"), {})
            bottom = pbdr.makeelement(qn("w:bottom"), {})
            bottom.set(qn("w:val"), "single")
            bottom.set(qn("w:sz"), "6")
            bottom.set(qn("w:color"), "C9D2DB")
            pbdr.append(bottom)
            ppr.append(pbdr)
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if level == 1 and is_chapter(text):
                # 一级标题 = 章：左对齐，作为 Heading 1
                h = doc.add_heading("", level=1)
                r = h.add_run(text)
                set_cjk(r, EAST, 15, True, (0x14, 0x3D, 0x63))
                h.paragraph_format.space_before = Pt(14)
                h.paragraph_format.space_after = Pt(7)
            elif level == 1:
                # 文档名：居中大标题
                h = doc.add_heading("", level=0)
                h.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r = h.add_run(text)
                set_cjk(r, EAST, 20, True, (0x0F, 0x2E, 0x4C))
                h.paragraph_format.space_before = Pt(18)
                h.paragraph_format.space_after = Pt(12)
            elif level == 2:
                h = doc.add_heading("", level=2)
                r = h.add_run(text)
                set_cjk(r, EAST, 12, True, (0x1F, 0x4E, 0x79))
                h.paragraph_format.space_before = Pt(10)
                h.paragraph_format.space_after = Pt(5)
            else:
                h = doc.add_heading("", level=min(level, 4))
                r = h.add_run(text)
                set_cjk(r, EAST, 11 if level == 3 else 10.5, True, (0x1F, 0x4E, 0x79))
                h.paragraph_format.space_before = Pt(8)
                h.paragraph_format.space_after = Pt(4)
            i += 1
            continue

        # 表格
        if is_table_row(line):
            header = split_row(line)
            i += 1
            if i < n and is_sep(lines[i]):
                i += 1
            rows = []
            while i < n and is_table_row(lines[i]):
                rows.append(split_row(lines[i]))
                i += 1
            cols = len(header)
            table = doc.add_table(rows=1, cols=cols)
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            hdr = table.rows[0].cells
            for c in range(cols):
                hdr[c].text = ""
                p = hdr[c].paragraphs[0]
                add_inline(p, header[c] if c < len(header) else "", 9.5, True)
                for r in p.runs:
                    r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                tcpr = hdr[c]._tc.get_or_add_tcPr()
                shd = tcpr.makeelement(qn("w:shd"), {})
                shd.set(qn("w:val"), "clear")
                shd.set(qn("w:fill"), "1F4E79")
                tcpr.append(shd)
            for row in rows:
                cells = table.add_row().cells
                for c in range(cols):
                    cells[c].text = ""
                    p = cells[c].paragraphs[0]
                    add_inline(p, row[c] if c < len(row) else "", 9.5)
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(4)
            continue

        # 引用块
        if stripped.startswith(">"):
            text = stripped.lstrip(">").strip()
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.8)
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(8)
            add_inline(p, text, 10.5)
            ppr = p._element.get_or_add_pPr()
            pbdr = ppr.makeelement(qn("w:pBdr"), {})
            left = pbdr.makeelement(qn("w:left"), {})
            left.set(qn("w:val"), "single")
            left.set(qn("w:sz"), "18")
            left.set(qn("w:color"), "1F4E79")
            pbdr.append(left)
            ppr.append(pbdr)
            i += 1
            continue

        # 列表
        m = re.match(r"^(\s*)([-*])\s+(.*)$", line)
        if m:
            indent = len(m.group(1))
            body = m.group(3)
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.left_indent = Cm(0.75 + 0.5 * (indent // 2))
            p.paragraph_format.space_after = Pt(2)
            add_inline(p, body, 10.5)
            i += 1
            continue

        m = re.match(r"^(\s*)(\d+)\.\s+(.*)$", line)
        if m:
            indent = len(m.group(1))
            num = m.group(2)
            body = m.group(3)
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.85 + 0.5 * (indent // 3))
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(f"{num}. ")
            set_cjk(r, BODY, 10.5)
            add_inline(p, body, 10.5)
            i += 1
            continue

        # 普通段落
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.25
        add_inline(p, stripped, 10.5)
        i += 1


def add_page_number_footer(section):
    """页脚居中插入 '第 X 页 / 共 Y 页'"""
    footer_p = section.footer.paragraphs[0]
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = footer_p.add_run("第 ")
    set_cjk(r, BODY, 9)

    def field(instr):
        fld = OxmlElement("w:fldSimple")
        fld.set(qn("w:instr"), instr)
        run = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), "18")
        rpr.append(sz)
        run.append(rpr)
        txt = OxmlElement("w:t")
        txt.text = "1"
        run.append(txt)
        fld.append(run)
        footer_p._p.append(fld)

    field("PAGE")
    r = footer_p.add_run(" 页 / 共 ")
    set_cjk(r, BODY, 9)
    field("NUMPAGES")
    r = footer_p.add_run(" 页")
    set_cjk(r, BODY, 9)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        md = f.read()

    doc = Document()
    sec = doc.sections[0]
    sec.left_margin = Cm(2.2)
    sec.right_margin = Cm(2.2)
    sec.top_margin = Cm(2.2)
    sec.bottom_margin = Cm(2.0)
    add_page_number_footer(sec)

    style = doc.styles["Normal"]
    style.font.size = Pt(10.5)
    style.font.name = BODY
    style.element.rPr.rFonts.set(qn("w:eastAsia"), BODY)

    build(doc, md, base_dir=os.path.dirname(os.path.abspath(src)))
    doc.save(dst)
    print(f"OK -> {dst}")


if __name__ == "__main__":
    main()
