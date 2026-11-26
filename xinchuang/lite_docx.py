#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零依赖国标轻量排版、docx 纯标准库提取与空白公文模板生成（只依赖 Python 标准库，不联网）。

定位：
  面向没有 python-docx / lxml 的国产信创电脑（如龙芯 loongarch64、精简版银河麒麟/统信 UOS、
  无管理员权限装包的内网机），提供不依赖任何第三方库的：
  1. 轻量 GB/T 9704-2012 排版（页面、边距、22×28 文档网格、标准字体、各级标题、落款对齐、奇偶页页码）；
  2. 纯标准库 .docx 文本提取（正文、表格、页眉页脚，供涉密检测/脱敏/核稿直接读取 Word 文件）；
  3. 免宏、免 Python 的五套 GB/T 9704 空白公文模板生成（xinchuang/templates/）。

用法：
  python3 xinchuang/lite_docx.py 正文.txt -o 成稿.docx [--unit-fonts preset:fangzheng-gbk]
  python3 xinchuang/lite_docx.py --templates xinchuang/templates
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parent.parent
_FMT_SCRIPTS = str(ROOT / "skills" / "gongwen-format" / "scripts")
if _FMT_SCRIPTS not in sys.path:
    sys.path.insert(0, _FMT_SCRIPTS)

import gw_fonts  # noqa: E402
import gw_layout  # noqa: E402

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ZIP_DATE = (2026, 1, 1, 0, 0, 0)
MAX_XML_BYTES = 50 * 1024 * 1024
MAX_DOCX_PARTS = 200


# ---------------------------------------------------------------------------
# 纯标准库 .docx 文本提取（正文、表格、页眉页脚）
# ---------------------------------------------------------------------------

def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _read_xml_part(zf: zipfile.ZipFile, name: str) -> ET.Element:
    info = zf.getinfo(name)
    if info.file_size > MAX_XML_BYTES:
        raise ValueError(f"docx 内部部件过大：{name}")
    return ET.fromstring(zf.read(name))


def _para_text(p_el: ET.Element) -> str:
    buf: List[str] = []
    for node in p_el.iter():
        tag = _local_tag(node.tag)
        if tag == "t" and node.text:
            buf.append(node.text)
        elif tag == "tab":
            buf.append("\t")
        elif tag in ("br", "cr"):
            buf.append("\n")
    return "".join(buf)


def _extract_part_lines(root: ET.Element) -> Tuple[List[str], int]:
    """按文档顺序提取段落与表格行，返回 (文本行列表, 表格数)。"""
    lines: List[str] = []
    tables = 0
    body = None
    for child in root:
        if _local_tag(child.tag) == "body":
            body = child
            break
    container = body if body is not None else root
    for child in container:
        tag = _local_tag(child.tag)
        if tag == "p":
            lines.append(_para_text(child))
        elif tag == "tbl":
            tables += 1
            for tr in child:
                if _local_tag(tr.tag) != "tr":
                    continue
                cells: List[str] = []
                for tc in tr:
                    if _local_tag(tc.tag) != "tc":
                        continue
                    cell_parts = [_para_text(p).strip() for p in tc if _local_tag(p.tag) == "p"]
                    cells.append(" ".join(x for x in cell_parts if x))
                if any(cells):
                    lines.append(" | ".join(cells))
    return lines, tables


def read_docx_text(raw: bytes) -> Dict[str, object]:
    """零依赖读取 .docx 正文、表格和页眉页脚文字，返回结构化字典。"""
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = zf.namelist()
        if len(names) > MAX_DOCX_PARTS:
            raise ValueError("docx 内部文件数过多，已拒绝读取")
        if "word/document.xml" not in names:
            raise ValueError("缺少 word/document.xml，不是有效的 .docx 文件")
        body_lines, table_count = _extract_part_lines(_read_xml_part(zf, "word/document.xml"))
        hf_lines: List[str] = []
        for name in sorted(names):
            if re.fullmatch(r"word/(?:header|footer)\d*\.xml", name):
                part_lines, _ = _extract_part_lines(_read_xml_part(zf, name))
                for line in part_lines:
                    stripped = line.strip()
                    if stripped:
                        hf_lines.append(stripped)
    body_text = "\n".join(body_lines).strip("\n")
    hf_text = "\n".join(hf_lines)
    full_text = (hf_text + "\n" + body_text).strip() if hf_text else body_text
    return {
        "body": body_text,
        "headers_footers": hf_text,
        "full": full_text,
        "paragraphs": len(body_lines),
        "tables": table_count,
    }


# ---------------------------------------------------------------------------
# 纯标准库 GB/T 9704 轻量 OOXML 生成
# ---------------------------------------------------------------------------

def _mm_to_twips(mm: float) -> int:
    return int(round(mm * 1440 / 25.4))


def _pt_to_twips(pt: float) -> int:
    return int(round(pt * 20))


def _pv(params: dict, dotted: str):
    node = params
    for key in dotted.split("."):
        node = node[key]
    return node["value"] if isinstance(node, dict) and "value" in node else node


def _rpr_xml(font: str, size_pt: float, *, bold: bool = False, color: Optional[str] = None) -> str:
    ef = xml_escape(font, {'"': "&quot;"})
    half = int(round(size_pt * 2))
    parts = [
        f'<w:rFonts w:ascii="{ef}" w:hAnsi="{ef}" w:eastAsia="{ef}" w:cs="{ef}" w:hint="eastAsia"/>'
    ]
    if bold:
        parts.append("<w:b/><w:bCs/>")
    if color:
        parts.append(f'<w:color w:val="{xml_escape(color)}"/>')
    parts.append(f'<w:sz w:val="{half}"/><w:szCs w:val="{half}"/>')
    return "<w:rPr>" + "".join(parts) + "</w:rPr>"


def _run_xml(text: str, font: str, size_pt: float, *, bold: bool = False, color: Optional[str] = None) -> str:
    rpr = _rpr_xml(font, size_pt, bold=bold, color=color)
    escaped = xml_escape(text)
    space_attr = ' xml:space="preserve"' if (text.startswith(" ") or text.endswith(" ") or "  " in text) else ""
    return f"<w:r>{rpr}<w:t{space_attr}>{escaped}</w:t></w:r>"


def _ppr_xml(
    *,
    align: str = "both",
    line_exact_pt: Optional[float] = 28.9,
    line_single: bool = False,
    before_pt: float = 0.0,
    after_pt: float = 0.0,
    first_line_chars: float = 0.0,
    hanging_chars: float = 0.0,
    left_chars: float = 0.0,
    right_chars: float = 0.0,
    char_pt: float = 16.0,
    write_chars_attr: bool = True,
    outline: Optional[int] = None,
    snap: bool = True,
    keep_next: bool = False,
    style_id: Optional[str] = None,
    border_bottom: Optional[Tuple[int, str, int]] = None,
    border_top: Optional[Tuple[int, str, int]] = None,
) -> str:
    parts: List[str] = []
    if style_id:
        parts.append(f'<w:pStyle w:val="{xml_escape(style_id)}"/>')
    if keep_next:
        parts.append("<w:keepNext/>")
    if border_bottom or border_top:
        bdr = ["<w:pBdr>"]
        if border_top:
            sz, col, sp = border_top
            bdr.append(f'<w:top w:val="single" w:sz="{sz}" w:space="{sp}" w:color="{col}"/>')
        if border_bottom:
            sz, col, sp = border_bottom
            bdr.append(f'<w:bottom w:val="single" w:sz="{sz}" w:space="{sp}" w:color="{col}"/>')
        bdr.append("</w:pBdr>")
        parts.append("".join(bdr))
    if not snap:
        parts.append('<w:snapToGrid w:val="0"/>')

    # 间距
    before_tw = _pt_to_twips(before_pt)
    after_tw = _pt_to_twips(after_pt)
    if line_exact_pt is not None:
        line_tw = _pt_to_twips(line_exact_pt)
        parts.append(f'<w:spacing w:before="{before_tw}" w:after="{after_tw}" w:line="{line_tw}" w:lineRule="exact"/>')
    elif line_single:
        parts.append(f'<w:spacing w:before="{before_tw}" w:after="{after_tw}" w:line="240" w:lineRule="auto"/>')

    # 缩进
    unit = char_pt * 20.0
    ind_attrs = [
        f'w:left="{int(round(left_chars * unit))}"',
        f'w:right="{int(round(right_chars * unit))}"',
    ]
    if hanging_chars > 0:
        ind_attrs.append(f'w:hanging="{int(round(hanging_chars * unit))}"')
    elif first_line_chars > 0:
        ind_attrs.append(f'w:firstLine="{int(round(first_line_chars * unit))}"')
    else:
        ind_attrs.append('w:firstLine="0"')
    if write_chars_attr and hanging_chars <= 0:
        ind_attrs.append(f'w:leftChars="{int(round(left_chars * 100))}"')
        ind_attrs.append(f'w:rightChars="{int(round(right_chars * 100))}"')
        ind_attrs.append(f'w:firstLineChars="{int(round(first_line_chars * 100))}"')
    parts.append("<w:ind " + " ".join(ind_attrs) + "/>")

    jc_map = {"left": "left", "center": "center", "right": "right", "justify": "both", "both": "both"}
    parts.append(f'<w:jc w:val="{jc_map[align]}"/>')
    if outline is not None:
        parts.append(f'<w:outlineLvl w:val="{outline}"/>')
    return "<w:pPr>" + "".join(parts) + "</w:pPr>"


def _content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
        '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
        '<Override PartName="/word/footer2.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
        "</Types>\n"
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>\n"
    )


def _doc_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
        '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer2.xml"/>'
        "</Relationships>\n"
    )


def _settings_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:settings xmlns:w="{W_NS}">'
        "<w:evenAndOddHeaders/>"
        '<w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat>'
        "</w:settings>\n"
    )


def _styles_xml(fonts: Dict[str, str], line_pt: float) -> str:
    body_font = fonts["仿宋"]
    title_font = fonts["小标宋"]
    h1_font = fonts["黑体"]
    h2_font = fonts["楷体"]
    line_tw = _pt_to_twips(line_pt)

    def _font_rpr(fn: str, sz: float) -> str:
        return _rpr_xml(fn, sz)

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:styles xmlns:w="{W_NS}">'
        "<w:docDefaults>"
        "<w:rPrDefault>"
        f'<w:rPr><w:rFonts w:ascii="{xml_escape(body_font)}" w:hAnsi="{xml_escape(body_font)}" '
        f'w:eastAsia="{xml_escape(body_font)}" w:cs="{xml_escape(body_font)}" w:hint="eastAsia"/>'
        '<w:sz w:val="32"/><w:szCs w:val="32"/>'
        '<w:lang w:val="en-US" w:eastAsia="zh-CN" w:bidi="ar-SA"/></w:rPr>'
        "</w:rPrDefault>"
        "<w:pPrDefault/>"
        "</w:docDefaults>"
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/><w:qFormat/>'
        f'<w:pPr><w:widowControl w:val="0"/><w:autoSpaceDE w:val="0"/><w:autoSpaceDN w:val="0"/>'
        f'<w:spacing w:before="0" w:after="0" w:line="{line_tw}" w:lineRule="exact"/>'
        '<w:jc w:val="both"/></w:pPr>'
        f"{_font_rpr(body_font, 16.0)}"
        "</w:style>"
        '<w:style w:type="paragraph" w:styleId="GongwenTitle">'
        '<w:name w:val="公文标题"/><w:basedOn w:val="Normal"/><w:qFormat/>'
        f'{_ppr_xml(align="center", line_exact_pt=line_pt, snap=False)}'
        f"{_font_rpr(title_font, 22.0)}"
        "</w:style>"
        '<w:style w:type="paragraph" w:styleId="Heading1">'
        '<w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:qFormat/>'
        f'{_ppr_xml(align="both", line_exact_pt=line_pt, first_line_chars=2, outline=0, keep_next=True)}'
        f"{_font_rpr(h1_font, 16.0)}"
        "</w:style>"
        '<w:style w:type="paragraph" w:styleId="Heading2">'
        '<w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:qFormat/>'
        f'{_ppr_xml(align="both", line_exact_pt=line_pt, first_line_chars=2, outline=1, keep_next=True)}'
        f"{_font_rpr(h2_font, 16.0)}"
        "</w:style>"
        '<w:style w:type="paragraph" w:styleId="Heading3">'
        '<w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:qFormat/>'
        f'{_ppr_xml(align="both", line_exact_pt=line_pt, first_line_chars=2, outline=2)}'
        f"{_font_rpr(body_font, 16.0)}"
        "</w:style>"
        '<w:style w:type="paragraph" w:styleId="Heading4">'
        '<w:name w:val="heading 4"/><w:basedOn w:val="Normal"/><w:qFormat/>'
        f'{_ppr_xml(align="both", line_exact_pt=line_pt, first_line_chars=2, outline=3)}'
        f"{_font_rpr(body_font, 16.0)}"
        "</w:style>"
        "</w:styles>\n"
    )


def _footer_xml(fonts: Dict[str, str], params: dict, *, align: str) -> str:
    pn = params["elements"]["page_number"]
    font = fonts[pn["font"]]
    size = float(_pv(params, f"sizes_pt.{pn['size']}"))
    dash = pn["dash"]
    side = float(pn["side_chars"])
    after_pt = float(_pv(params, "page.page_number_space_after_pt"))
    ppr = _ppr_xml(
        align=align,
        line_exact_pt=None,
        line_single=True,
        before_pt=0.0,
        after_pt=after_pt,
        left_chars=side if align == "left" else 0.0,
        right_chars=side if align == "right" else 0.0,
        char_pt=size,
        write_chars_attr=False,
        snap=False,
    )
    rpr = _rpr_xml(font, size)
    runs = (
        _run_xml(f"{dash} ", font, size)
        + f'<w:r>{rpr}<w:fldChar w:fldCharType="begin"/></w:r>'
        + f'<w:r>{rpr}<w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        + f'<w:r>{rpr}<w:fldChar w:fldCharType="separate"/></w:r>'
        + _run_xml("1", font, size)
        + f'<w:r>{rpr}<w:fldChar w:fldCharType="end"/></w:r>'
        + _run_xml(f" {dash}", font, size)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:ftr xmlns:w="{W_NS}"><w:p>{ppr}{runs}</w:p></w:ftr>\n'
    )


def _sectpr_xml(params: dict) -> str:
    w = _mm_to_twips(_pv(params, "page.width_mm"))
    h = _mm_to_twips(_pv(params, "page.height_mm"))
    top = _mm_to_twips(_pv(params, "page.margin_top_mm"))
    bottom = _mm_to_twips(_pv(params, "page.margin_bottom_mm"))
    left = _mm_to_twips(_pv(params, "page.margin_left_mm"))
    right = _mm_to_twips(_pv(params, "page.margin_right_mm"))
    header = _mm_to_twips(_pv(params, "page.header_distance_mm"))
    footer = _mm_to_twips(_pv(params, "page.footer_distance_mm"))
    grid_type = _pv(params, "grid.doc_grid_type")
    pitch = _pv(params, "grid.doc_grid_line_pitch_twips")
    char_space = _pv(params, "grid.doc_grid_char_space")
    return (
        "<w:sectPr>"
        f'<w:footerReference w:type="default" r:id="rId3"/>'
        f'<w:footerReference w:type="even" r:id="rId4"/>'
        f'<w:pgSz w:w="{w}" w:h="{h}" w:code="9"/>'
        f'<w:pgMar w:top="{top}" w:right="{right}" w:bottom="{bottom}" w:left="{left}" '
        f'w:header="{header}" w:footer="{footer}" w:gutter="0"/>'
        f'<w:docGrid w:type="{grid_type}" w:linePitch="{pitch}" w:charSpace="{char_space}"/>'
        "</w:sectPr>"
    )


def _pack_docx(paragraphs_xml: Sequence[str], fonts: Dict[str, str], params: dict) -> bytes:
    line_pt = float(_pv(params, "grid.line_spacing_pt"))
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}"><w:body>'
        + "".join(paragraphs_xml)
        + _sectpr_xml(params)
        + "</w:body></w:document>\n"
    )
    parts = [
        ("[Content_Types].xml", _content_types_xml()),
        ("_rels/.rels", _root_rels_xml()),
        ("word/_rels/document.xml.rels", _doc_rels_xml()),
        ("word/settings.xml", _settings_xml()),
        ("word/styles.xml", _styles_xml(fonts, line_pt)),
        ("word/footer1.xml", _footer_xml(fonts, params, align="right")),
        ("word/footer2.xml", _footer_xml(fonts, params, align="left")),
        ("word/document.xml", doc_xml),
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for arc, content in parts:
            info = zipfile.ZipInfo(arc, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            zf.writestr(info, content.encode("utf-8"), compresslevel=9)
    return buf.getvalue()


def _blank_p(line_pt: float) -> str:
    return f"<w:p>{_ppr_xml(align='both', line_exact_pt=line_pt)}</w:p>"


def _title_p(lines: Sequence[str], font: str, line_pt: float) -> str:
    ppr = _ppr_xml(align="center", line_exact_pt=line_pt, snap=False, style_id="GongwenTitle")
    runs: List[str] = []
    for i, line in enumerate(lines):
        runs.append(_run_xml(line, font, 22.0))
        if i < len(lines) - 1:
            runs.append("<w:r><w:br/></w:r>")
    return f"<w:p>{ppr}{''.join(runs)}</w:p>"


def _heading_p(
    text: str,
    role: str,
    split: int,
    fonts: Dict[str, str],
    line_pt: float,
) -> str:
    role_font = {"h1": fonts["黑体"], "h2": fonts["楷体"], "h3": fonts["仿宋"], "h4": fonts["仿宋"]}[role]
    outline = {"h1": 0, "h2": 1, "h3": 2, "h4": 3}[role]
    style_id = {"h1": "Heading1", "h2": "Heading2", "h3": "Heading3", "h4": "Heading4"}[role]
    end = len(text) if split is None or split < 0 else min(split, len(text))
    standalone = end >= len(text) and text.rstrip()[-1:] not in "。；！？.;!?"
    ppr = _ppr_xml(
        align="both",
        line_exact_pt=line_pt,
        first_line_chars=2.0,
        outline=outline,
        keep_next=standalone,
        style_id=style_id,
    )
    if end < len(text):
        runs = _run_xml(text[:end], role_font, 16.0) + _run_xml(text[end:], fonts["仿宋"], 16.0)
    else:
        runs = _run_xml(text, role_font, 16.0)
    return f"<w:p>{ppr}{runs}</w:p>"


Place = Tuple[str, float, float]  # (对齐, 左缩进字数, 右缩进字数)


def _signature_places(sig_texts: Sequence[str], date_text: str, width: float = 28.0) -> Tuple[Place, Place]:
    """按 GB/T 9704-2012 7.3.5.2（不加盖印章）计算署名与成文日期的定位，与 gw_format.py 口径一致。

    轻量版不处理印章，一律按不加盖印章排：署名右空二字；成文日期首字比署名首字右移二字（用左缩进定位）；
    日期加二字后比署名更长时，日期右对齐、右空二字，署名相应左移。
    只有署名或只有日期时，该行右对齐、右空二字。"""
    r_sig, shift = 2.0, 2.0
    right_only: Place = ("right", 0.0, r_sig)
    if not sig_texts or not date_text:
        return right_only, right_only
    w_max = max(gw_layout.text_width_chars(t) for t in sig_texts)
    dw = gw_layout.text_width_chars(date_text)
    if w_max <= 0 or dw <= 0:
        return right_only, right_only
    if dw + shift > w_max:
        start = max(0.0, width - r_sig - dw - shift)
        return ("left", round(start, 2), 0.0), ("right", 0.0, r_sig)
    start = max(0.0, width - r_sig - w_max)
    return ("left", round(start, 2), 0.0), ("left", round(start + shift, 2), 0.0)


def build_lite_docx(
    lines: Sequence[str],
    *,
    unit_fonts: Optional[str] = None,
    font_check: bool = True,
) -> Tuple[bytes, Dict[str, object]]:
    """纯标准库生成符合 GB/T 9704-2012 基础版式的 .docx 字节流和排版报告。"""
    params = gw_fonts.load_params()
    if unit_fonts:
        parsed_unit = gw_fonts.parse_unit_fonts(unit_fonts, params)
        params = gw_fonts.apply_unit_fonts(params, parsed_unit)
    if font_check:
        installed, method = gw_fonts.installed_fonts()
        fonts, check = gw_fonts.resolve_fonts(params, installed, method)
    else:
        fonts = dict(params["fonts"]["standard"])
        check = {"font_status": "unchecked", "missing_fonts": []}

    cleaned = [line for line in lines]
    if not any(x.strip() for x in cleaned):
        raise ValueError("正文为空，无法排版")

    parsed = gw_layout.parse_lines(cleaned)
    line_pt = float(_pv(params, "grid.line_spacing_pt"))
    body_font = fonts["仿宋"]
    title_font = fonts["小标宋"]
    kai_font = fonts["楷体"]

    # 预提取署名和成文日期文字，用于按 7.3.5.2（不加盖印章）定位
    sig_items = [it for it in parsed.items if it.role == "signature"]
    date_items = [it for it in parsed.items if it.role == "date"]
    sig_place, date_place = _signature_places(
        [it.text for it in sig_items],
        date_items[-1].text if date_items else "",
        float(_pv(params, "grid.chars_per_line")),
    )

    paras: List[str] = []
    seen_title = False
    for idx, item in enumerate(parsed.items):
        role = item.role
        text = item.text
        if role == "blank":
            continue
        if role == "issuer":
            ppr = _ppr_xml(align="center", line_exact_pt=36.0, snap=False)
            paras.append(f"<w:p>{ppr}{_run_xml(text, title_font, 32.0, color='FF0000')}</w:p>")
        elif role == "docno":
            ppr = _ppr_xml(
                align="center",
                line_exact_pt=line_pt,
                snap=False,
                border_bottom=(12, "FF0000", 11),
            )
            paras.append(f"<w:p>{ppr}{_run_xml(text, body_font, 16.0)}</w:p>")
            paras.append(_blank_p(line_pt))
        elif role == "title":
            seen_title = True
            paras.append(_title_p(gw_layout.break_title(text), title_font, line_pt))
            # 标题下空一行（紧跟副标题/题注时移到副标题之后）
            nxt = parsed.items[idx + 1].role if idx + 1 < len(parsed.items) else ""
            if nxt not in ("subtitle", "title_note"):
                paras.append(_blank_p(line_pt))
        elif role == "subtitle":
            ppr = _ppr_xml(align="center", line_exact_pt=line_pt, snap=False)
            paras.append(f"<w:p>{ppr}{_run_xml(text, kai_font, 16.0)}</w:p>")
            nxt = parsed.items[idx + 1].role if idx + 1 < len(parsed.items) else ""
            if nxt != "title_note":
                paras.append(_blank_p(line_pt))
        elif role == "title_note":
            ppr = _ppr_xml(align="center", line_exact_pt=line_pt, snap=False)
            paras.append(f"<w:p>{ppr}{_run_xml(text, body_font, 16.0)}</w:p>")
            paras.append(_blank_p(line_pt))
        elif role in ("recipient", "salutation"):
            ppr = _ppr_xml(align="left", line_exact_pt=line_pt, first_line_chars=0.0)
            paras.append(f"<w:p>{ppr}{_run_xml(text, body_font, 16.0)}</w:p>")
        elif role in ("h1", "h2", "h3", "h4"):
            paras.append(_heading_p(text, role, item.split, fonts, line_pt))
        elif role == "attachment":
            if item.first:
                paras.append(_blank_p(line_pt))
                ppr = _ppr_xml(align="both", line_exact_pt=line_pt, left_chars=5.0, hanging_chars=3.0)
            else:
                ppr = _ppr_xml(align="both", line_exact_pt=line_pt, left_chars=5.0)
            paras.append(f"<w:p>{ppr}{_run_xml(text, body_font, 16.0)}</w:p>")
        elif role == "signature":
            paras.append(_blank_p(line_pt))
            ppr = _ppr_xml(align=sig_place[0], line_exact_pt=line_pt, left_chars=sig_place[1], right_chars=sig_place[2])
            paras.append(f"<w:p>{ppr}{_run_xml(text, body_font, 16.0)}</w:p>")
        elif role == "date":
            if not sig_items:
                paras.append(_blank_p(line_pt))
            ppr = _ppr_xml(align=date_place[0], line_exact_pt=line_pt, left_chars=date_place[1], right_chars=date_place[2])
            paras.append(f"<w:p>{ppr}{_run_xml(text, body_font, 16.0)}</w:p>")
        elif role == "note":
            ppr = _ppr_xml(align="both", line_exact_pt=line_pt, first_line_chars=2.0)
            paras.append(f"<w:p>{ppr}{_run_xml(text, body_font, 16.0)}</w:p>")
        elif role in ("cc", "print", "banji_main"):
            ppr = _ppr_xml(
                align="left",
                line_exact_pt=24.0,
                left_chars=1.0,
                char_pt=14.0,
                write_chars_attr=False,
                snap=False,
                border_top=(12, "000000", 4) if role == "cc" else None,
            )
            paras.append(f"<w:p>{ppr}{_run_xml(text, body_font, 14.0)}</w:p>")
        else:
            ppr = _ppr_xml(align="both", line_exact_pt=line_pt, first_line_chars=2.0)
            paras.append(f"<w:p>{ppr}{_run_xml(text, body_font, 16.0)}</w:p>")

    raw = _pack_docx(paras, fonts, params)
    report: Dict[str, object] = {
        "mode": "lite_stdlib",
        "paragraphs": len(paras),
        "has_title": seen_title,
        "fonts": fonts,
        "font_check": check,
        "detected": parsed.detected,
        "warnings": parsed.warnings,
    }
    return raw, report


def render_lite_report(report: Dict[str, object]) -> str:
    lines = [
        "轻量排版完成（纯 Python 标准库，不依赖 python-docx / lxml）",
        "已套用：A4 纸张、页边距（上37/下35/左28/右26 mm）、每页22行×每行28字网格、标准字体、各级标题层次、无印章落款（署名右空二字，成文日期首字比署名首字右移二字，日期较长时日期右空二字、署名相应左移）与奇偶页码。",
        f"共生成 {report['paragraphs']} 段。",
    ]
    if report.get("detected"):
        lines.append("识别要素：" + "；".join(str(x) for x in report["detected"][:8]))
    fc = report.get("font_check")
    if isinstance(fc, dict) and fc.get("font_status") != "unchecked":
        lines.append(gw_fonts.status_line(fc, "下方"))
        notice = gw_fonts.render_notice(fc)
        if notice:
            lines.append(notice)
    lines.append("说明：复杂红头套打、联合行文、Markdown 表格和完整版记表格需安装 python-docx，或改用 xinchuang/templates/ 空白模板与 WPS 手动微调。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 免宏免 Python 的五套 GB/T 9704 空白公文模板生成
# ---------------------------------------------------------------------------

def _template_specs(fonts: Dict[str, str], line_pt: float) -> List[Tuple[str, str, List[str]]]:
    fs = fonts["仿宋"]
    xbs = fonts["小标宋"]
    ht = fonts["黑体"]
    kt = fonts["楷体"]

    def p_body(text: str) -> str:
        return f"<w:p>{_ppr_xml(align='both', line_exact_pt=line_pt, first_line_chars=2.0)}{_run_xml(text, fs, 16.0)}</w:p>"

    def p_left(text: str) -> str:
        return f"<w:p>{_ppr_xml(align='left', line_exact_pt=line_pt)}{_run_xml(text, fs, 16.0)}</w:p>"

    def p_right(text: str) -> str:
        return f"<w:p>{_ppr_xml(align='right', line_exact_pt=line_pt, right_chars=2.0)}{_run_xml(text, fs, 16.0)}</w:p>"

    def p_h1(text: str) -> str:
        return f"<w:p>{_ppr_xml(align='both', line_exact_pt=line_pt, first_line_chars=2.0, outline=0, keep_next=True, style_id='Heading1')}{_run_xml(text, ht, 16.0)}</w:p>"

    def p_h2(text: str) -> str:
        return f"<w:p>{_ppr_xml(align='both', line_exact_pt=line_pt, first_line_chars=2.0, outline=1, keep_next=True, style_id='Heading2')}{_run_xml(text, kt, 16.0)}</w:p>"

    def p_red_issuer(text: str) -> str:
        return f"<w:p>{_ppr_xml(align='center', line_exact_pt=40.0, before_pt=20.0, snap=False)}{_run_xml(text, xbs, 36.0, color='FF0000')}</w:p>"

    def p_red_rule_docno(text: str) -> str:
        return (
            f"<w:p>{_ppr_xml(align='center', line_exact_pt=line_pt, snap=False, border_bottom=(12, 'FF0000', 11))}"
            f"{_run_xml(text, fs, 16.0)}</w:p>"
        )

    def p_banji(cc: str, prt: str) -> List[str]:
        return [
            _blank_p(line_pt),
            f"<w:p>{_ppr_xml(align='left', line_exact_pt=24.0, left_chars=1.0, char_pt=14.0, write_chars_attr=False, snap=False, border_top=(12, '000000', 4), border_bottom=(6, '000000', 4))}{_run_xml(cc, fs, 14.0)}</w:p>",
            f"<w:p>{_ppr_xml(align='left', line_exact_pt=24.0, left_chars=1.0, char_pt=14.0, write_chars_attr=False, snap=False, border_bottom=(12, '000000', 4))}{_run_xml(prt, fs, 14.0)}</w:p>",
        ]

    return [
        (
            "01-白头公文模板.docx",
            "通知、请示、报告、函、批复等通用白头公文（已设页面、22×28 网格、各级样式、奇偶页码）",
            [
                _title_p(["关于【此处填写公文标题】的通知"], xbs, line_pt),
                _blank_p(line_pt),
                p_left("各有关单位："),
                p_body("【此处粘贴正文首段。正文已设为仿宋_GB2312 三号、固定行距 28.9 磅、首行缩进 2 字符。】"),
                p_h1("一、【一级标题：黑体三号】"),
                p_h2("（一）【二级标题：楷体_GB2312 三号】"),
                p_body("1.【三级标题与正文：仿宋_GB2312 三号】"),
                _blank_p(line_pt),
                p_right("某单位名称（替换为本机关全称）"),
                p_right("2026年11月　日"),
            ],
        ),
        (
            "02-红头公文模板.docx",
            "带红色发文机关标志、发文字号、红色分隔线与版记占位的红头文件模板",
            [
                p_red_issuer("【此处填写发文机关名称】文件"),
                _blank_p(line_pt),
                p_red_rule_docno("【机关代字】〔2026〕【序号】号"),
                _blank_p(line_pt),
                _blank_p(line_pt),
                _title_p(["关于【此处填写公文标题】的通知"], xbs, line_pt),
                _blank_p(line_pt),
                p_left("各有关单位："),
                p_body("【此处粘贴正文。如为上行文请示/报告，发文字号行改为居左空一字并在右侧加“签发人：姓名”（姓名用楷体_GB2312）。】"),
                p_h1("一、【一级标题】"),
                p_body("【正文内容】"),
                _blank_p(line_pt),
                p_right("某单位名称（替换为本机关全称）"),
                p_right("2026年11月　日"),
            ] + p_banji("抄送：【抄送机关】。", "【印发机关名称】　　　　　　　　　　　　2026年【月】月【日】日印发"),
        ),
        (
            "03-会议纪要模板.docx",
            "会议纪要格式（纪要标志、期号、分隔线、议定事项与出席/列席占位）",
            [
                p_red_issuer("【此处填写会议名称】纪要"),
                _blank_p(line_pt),
                p_red_rule_docno("〔2026〕第【期号】期"),
                _blank_p(line_pt),
                p_body("2026年【月】月【日】日，【主持人姓名及职务】主持召开【会议名称】，专题研究【议题概要】。现将会议议定事项纪要如下："),
                p_h1("一、【议定事项一】"),
                p_body("会议听取了【单位/部门】关于【事项】的汇报，原则同意【具体意见】，由【牵头单位】负责落实，【时限】前完成。"),
                _blank_p(line_pt),
                p_body("出席：【人员名单】。"),
                p_body("列席：【人员名单】。"),
            ] + p_banji("抄送：【抄送范围】。", "【印发机关名称】　　　　　　　　　　　　2026年【月】月【日】日印发"),
        ),
        (
            "04-内部签报模板.docx",
            "内设部门向本单位领导呈报的内部签报模板（一签一事、请示事项与倾向意见占位）",
            [
                _title_p(["关于【此处填写签报事项】的签报"], xbs, line_pt),
                _blank_p(line_pt),
                p_left("【分管/主要领导姓名及职务】："),
                p_body("【简述事由与背景，开门见山。】"),
                p_body("经研究，拟【此处写明本部门倾向性处理意见和经费/人员/时限安排】。"),
                p_body("妥否，请批示。"),
                _blank_p(line_pt),
                p_right("某内设部门（替换为本部门名称）"),
                p_right("2026年11月　日"),
                p_body("（联系人：【姓名】，联系电话：【电话】）"),
            ],
        ),
        (
            "05-综合材料模板.docx",
            "年终总结、汇报材料、调研报告、讲话稿等常用材料（含四级标题样式示范与导航窗格大纲）",
            [
                _title_p(["【此处填写材料标题】"], xbs, line_pt),
                f"<w:p>{_ppr_xml(align='center', line_exact_pt=line_pt, snap=False)}{_run_xml('——【副标题，无则删去本行】', kt, 16.0)}</w:p>",
                _blank_p(line_pt),
                p_body("【导语：直奔主题，交代时间段、核心任务和总体成效，不写空泛形势铺垫。】"),
                p_h1("一、【一级标题：黑体三号】"),
                p_h2("（一）【二级标题：楷体_GB2312 三号】"),
                p_body("1.【三级标题：仿宋_GB2312 三号】正文内容。"),
                p_body("（1）【四级标题：仿宋_GB2312 三号】正文内容。"),
                p_h1("二、【下一部分：存在问题或下一步打算】"),
                p_body("【正文内容】"),
            ],
        ),
    ]


def generate_templates(out_dir: Path) -> List[Path]:
    """在指定目录生成 5 套免宏免 Python 的 GB/T 9704 空白公文模板与 README.md。"""
    params = gw_fonts.load_params()
    fonts = dict(params["fonts"]["standard"])
    line_pt = float(_pv(params, "grid.line_spacing_pt"))
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    specs = _template_specs(fonts, line_pt)
    for fname, _desc, paras in specs:
        dest = out_dir / fname
        dest.write_bytes(_pack_docx(paras, fonts, params))
        written.append(dest)
    readme_lines = [
        "# 免宏免 Python 的 GB/T 9704 空白公文模板",
        "",
        "适用场景：单位电脑没有装 Python，同时信息中心禁用了 WPS 宏。直接用 WPS 文字或永中 Office 打开对应 `.docx` 模板，把文字粘贴进来并选择「只保留文本」，即可沿用国家标准版面。",
        "",
        "模板已预置：A4 纸张、页边距（上 37 / 下 35 / 左 28 / 右 26 mm）、每页 22 行 × 每行 28 字文档网格、奇偶页页码（四号宋体一字线）、国标各级标题样式（在 WPS 样式栏可直接点选「公文标题」「标题 1」「标题 2」「正文」）。",
        "",
        "| 文件 | 适用场景 |",
        "|---|---|",
    ]
    for fname, desc, _ in specs:
        readme_lines.append(f"| `{fname}` | {desc} |")
    readme_lines += [
        "",
        "> 提示：本模板不随附商用字体文件，请确保本机已安装仿宋_GB2312、楷体_GB2312、黑体、方正小标宋简体、宋体（安装指引见 `skills/gongwen-format/references/xinchuang.md`）。本单位制度明文要求方正 GBK 字体族的，打开模板后全选修改对应样式字体即可。",
        "",
    ]
    readme = out_dir / "README.md"
    readme.write_bytes(("\n".join(readme_lines)).encode("utf-8"))
    written.append(readme)
    return written


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="零依赖国标轻量排版与空白公文模板生成（纯 Python 标准库）。")
    ap.add_argument("input", nargs="?", type=Path, help="纯文本正文文件（.txt / .md）")
    ap.add_argument("-o", "--output", type=Path, help="输出的 .docx 路径")
    ap.add_argument("--unit-fonts", default="", help=gw_fonts.UNIT_FONTS_HELP)
    ap.add_argument("--templates", type=Path, help="生成 5 套空白公文模板到指定目录")
    args = ap.parse_args(argv)

    if args.templates:
        paths = generate_templates(args.templates)
        print(f"已生成 {len(paths)} 个模板文件到：{args.templates}")
        return 0

    if not args.input or not args.input.is_file():
        print("错误：请提供存在的正文文件（.txt / .md），或使用 --templates 生成空白模板。", file=sys.stderr)
        return 2
    lines, notes = gw_layout.read_body_text(args.input)
    for note in notes:
        print("提示：" + note)
    try:
        raw, report = build_lite_docx(lines, unit_fonts=args.unit_fonts or None)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    out = args.output or args.input.with_suffix(".docx")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    print(f"已写入：{out}")
    print(render_lite_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
