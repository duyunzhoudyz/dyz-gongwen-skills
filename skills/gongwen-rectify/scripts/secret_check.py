#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""保密标识检查：扫描 txt、md、docx、xlsx 中的密级标识和内部标注，命中即退出码 1。

用法：python secret_check.py <文件...>

docx 读取范围：正文段落、表格、页眉、页脚（含首页、奇偶页）、文本框、脚注、尾注、批注，
输出位置带来源标签，如“[页眉(首页)]”“[文本框]”“[表格]”。xlsx 读取单元格文字、批注、
工作表名、页眉页脚。只依赖标准库。

检出（与通用机检 PRI-005/PRI-006、gongwen-profile 的 secret_marks 同一批正则，见 lint_patterns()；字间空白如“机　密”“密 级”均容错）：
  1. 带星号或期限：“秘密★”“★机密”“机密★5年”“机密·5年”“绝密·长期”“机密（10年）”；
  2. 独立成行的密级词：“机密”“【机密】”“机密级”“机密件”“机密文件”“机密　特急”，及其后接“注意保管”“阅后收回”等短语；
  3. 密级标签：“密级：机密”“保密等级：秘密”；
  4. 断言本件密级的句子：“本件为机密级文件”“该文件定为机密”“此件机密，阅后收回”“该稿已标注机密”；
  5. 保密期限的标注形态：“保密期限：10年”“保密期限为10年”（单独成行或所在句极短）、与密级词或星号同行；
  6. 商业秘密标注：“【核心商密】”“密级：商业秘密”“（商密）”；
  7. 内部标注：“工作秘密”“内部资料”“不得外传”“内部使用”“注意保密”等（句中出现也停，比通用机检更严）；
  8. v1.3.0 补入：“密级　秘密”（空白代替冒号）、“保密期限：至2030年12月31日”、标题行开头的方括号密级“【秘密】关于……的通知”、
     “机密（解密时间：2030年1月1日）”、“绝密·启用前”“绝密★启用前”（考试、文件常见的密级标注，按标识处理）。
     方括号必须紧贴密级词：“【秘密载体管理】各部门……”不拦；“密级 的确定应当遵循最小化原则”“保密期限 届满后自行解密”这类叙述不拦。
放行：规范性、条件性、否定性叙述里的密级词，如“对拟定为机密级的事项，由定密责任人审核”“经审查，该事项不应定为机密”
“涉密人员接触机密级文件须经审批”“本材料系秘密投票结果汇总”；并列枚举（绝密级、机密级、秘密级）；制度性的“确定保密期限”
“保密期限届满”“保密期限，除另有规定外，绝密级不超过三十年”；“保密工作”“涉密人员管理”等业务用语。
输出只给位置和命中词，不复述材料内容。

已知局限（闸门宁严勿漏，如实记录）：
  - 表格里单独一格、或文本里单独一行写“机密”“秘密”“绝密”的，一律按独立标注拦截。因此“定密统计台账”这类
    列出各事项密级的表格，每个密级格都会命中，需由用户确认后人工处理（tests/secret/specimens 有台账标本，测试断言当前行为）。
  - 引号内的举例照样拦（通用机检与画像脚本对引号内举例放行，这是三处唯一的口径差别，见 tests/secret/test_three_way.py）。
  - 内部标注词（“内部资料”“注意保密”等）出现在句子中间时只有闸门拦，通用机检不拦，避免规范文书误报。
  - “保密期限为10年”这类标注按“所在句极短”判断：前面超过 10 个字或带逗号、句号的长句不拦（如法规引述）。

退出码：0 未发现；1 发现标识；2 文件无法读取。
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
MAX_XML = 50 * 1024 * 1024

LEVEL = "绝密|机密|秘密"
STAR = "[★☆＊*]"


def _sp(word: str) -> str:
    """允许字间有空白：“机　密”“密 级”。"""
    return "\\s*".join(word)


# 带字间空白容错的密级词；PRI-005/PRI-006 直接使用同一批正则（见 lint_patterns），三处口径一致
LV = "(?:%s)" % "|".join(_sp(x) for x in ("绝密", "机密", "秘密"))
_LABEL = "(?:%s|%s|%s)" % (_sp("密级"), _sp("保密等级"), _sp("秘密等级"))
_NUM = "(?:\\d+|[一二三四五六七八九十]+)"
_TERM = "(?:%s\\s*(?:年|个月)|长期|永久)" % _NUM
_SEP = "[·•・．/／]"
# 枚举并列（“秘密、机密、绝密”“机密和秘密”）不是对本件的标注
_ENUM = "(?!级?\\s*(?:[、和与及或]|[，,]\\s*%s))" % LV
# 句子在此结束：本件密级的断言必须在密级词后收句或接“级/文件/材料”
_END = "(?=$|[。；;，,！!？?）)】\\]\\s]|级|文件|文档|材料|件)"
# 密级词后接管理性、条件性、固定搭配的词，不是在标注本件
_NOT_MGMT = ("(?!进行|投票|会议|地|的|级?(?:的|以上|以下)|(?:文件|文档|材料|件)"
             "(?:管理|保管|清退|登记|传阅|制作|复制|销毁|审批|流转|范围|范畴|的))")
# 本件的指称：必须是“本/该/此/这 + 件/文件/材料/通知/报告……”，“该事项”“此次”之类不算
_SUBJ = "(?<![将把对拟如若凡应须需])(?:本|该|此|这)\\s*(?:份|个)?\\s*(?:件|文件|文档|材料|资料|通知|报告|稿件|稿|函|方案|文稿)"
_VERB = ("(?:(?:已|现|均|被)\\s*)?(?:属于|属|系|是|为|定为|确定为|划为|列为|标注为|标记为|标明为|标为|标注|标记|标明|"
         "密级为|密级是)")

# 保密期限只认标注形态，不拦“确定保密期限”“保密期限届满”“保密期限，除另有规定外，绝密级不超过三十年”等制度性叙述：
#   1. “保密期限：10年”（冒号形态，任意位置）；
#   2. “保密期限为10年”“保密期限 长期”：单独成行或所在句极短（前面不超过10个字且无句读），到期即句末；
#   3. 与密级词紧邻或与星号同行
_KW = _sp("保密期限")
_STAR0 = "[★☆＊]"

# 版头、页眉、页脚常见的独立成行标注：整行只有标注（可有 Markdown 修饰、括号、特急、期限）
_PRE = "^[\\s#*>_`~—\\-·•]*"
_POST = "[\\s#*>_`~—\\-·•]*$"
_URG = "(?:特急|加急|特提|平急|紧急)?"
_OPEN = "[\\[(（【〔［<《「『]*"
_CLOSE = "[\\])）】〕］>》」』]*"
_KIND = "(?:级|级?(?:件|文件|文档|材料|资料))?"
_SUF = "(?:\\s*%s?\\s*%s?\\s*[（(\\[【]?\\s*%s?\\s*%s\\s*[）)\\]】]?)?" % (STAR, _SEP, STAR, _TERM)
_TAILWORD = ("(?:(?:请|务必|须|应|要)?(?:注意|妥善|严格|专人)?(?:保管|保存|保密)|阅后(?:收回|销毁|退回|即毁|归档)|"
             "(?:请勿|不得|严禁)(?:外传|复制|转发|翻印|扩散)|限\\S{0,6}传阅)")

# 内部标注的标注形态（PRI-006 使用）；“内部资料”等词出现在句子里的情形见 GATE_ONLY
_IN_HEAD = ("(?:内部资料|内部文件|内部材料|内部参阅|内部参考|内部传阅|工作秘密|内部使用|不得外传|严禁外传|不得翻印|"
            "注意保密|仅限内部(?:使用|传阅)?|仅供内部(?:参考|使用|参阅|传阅)?)")
_IN_TAIL = ("(?:注意保存|妥善保管|注意保管|不得外传|请勿外传|严禁外传|不得翻印|严禁翻印|不得复制|严禁复制|"
            "不得转发|注意保密)")
_IN_OPEN, _IN_CLOSE = "[（(【\\[]", "[）)】\\]]"

# (类别, 正则源码)：LABEL_PATTERNS 对应 PRI-005，MARK_PATTERNS 对应 PRI-006，GATE_ONLY 只有闸门拦
LABEL_PATTERNS = [
    ("密级标识", "%s\\s*%s" % (LV, STAR)),
    # “★机密”“＊秘密”：星号在前；其后须收句、接期限或“级/件”，不误拦“★秘密载体管理”
    ("密级标识", "%s\\s*%s(?=$|[\\s，,。；;、：:（(\\d一二三四五六七八九十]|级|件|文件|长期|永久)" % (_STAR0, LV)),
    # 密级与期限：“机密 10年”“秘密★5年”“机密·5年”“绝密·长期”
    ("密级与保密期限", "%s\\s*%s?\\s*%s?\\s*%s" % (LV, STAR, _SEP, _TERM)),
    # 带括号的保密期限：机密（10年）、秘密(★5年)、绝密（长期）
    ("密级与保密期限", "%s\\s*[（(\\[【]\\s*%s?\\s*%s\\s*[）)\\]】]" % (LV, STAR, _TERM)),
    # 独立成行：机密、【机密】、机密（10年）、机密级、机密件、机密文件
    ("密级标识", "%s\\s*%s\\s*%s\\s*%s%s\\s*%s\\s*%s\\s*[。.]?%s" % (
        _PRE, _URG, _OPEN, LV, _KIND, _SUF, _CLOSE + "\\s*" + _URG, _POST)),
    # 独立成行后接短语：“机密文件，注意保管”“机密，阅后收回”
    ("密级标识", "%s\\s*%s\\s*%s\\s*%s%s\\s*%s\\s*[，,、；;：:]\\s*%s\\s*[。.]?%s" % (
        _PRE, _URG, _OPEN, LV, _KIND, _CLOSE, _TAILWORD, _POST)),
    # “密级：机密”“保密等级：秘密”；“密级为机密的……”这类条件叙述不算
    ("密级表述", "%s\\s*[：:]\\s*%s" % (_LABEL, LV)),
    ("密级表述", "%s\\s*[为是]\\s*%s(?!级?(?:的|以上|以下))%s" % (_LABEL, LV, _ENUM)),
    # 本件密级的断言：本/该/此/这 + 件/文件/材料……（+ 判断词）+ 密级词，句末或接“级/文件”
    ("密级表述", "%s\\s*[（(]?\\s*(?:%s)?\\s*[）)]?\\s*(?:一份|一件)?\\s*%s%s%s%s" % (
        _SUBJ, _VERB, LV, _END, _NOT_MGMT, _ENUM)),
    ("密级表述", "这\\s*是\\s*(?:一份|一件)\\s*%s%s%s%s" % (LV, _END, _NOT_MGMT, _ENUM)),
    # 已标注：“该稿已标注机密”走上一条；无主语时只认“已/均/被/并 + 标注”或句首的“标注”，不拦“须标注机密”“应定为机密”
    ("密级表述", "(?:^|[，,。；;、\\s（(])(?:已|均|现|被|并)?\\s*(?:标注|标记|标明|标为)\\s*(?:为\\s*)?%s%s%s%s" % (
        LV, _END, _NOT_MGMT, _ENUM)),
    # “密级　秘密”：用空白代替冒号；“密级 的确定应当……”“密级 秘密级、机密级……”这类叙述、枚举不算
    ("密级表述", "%s[^\\S\\n]+%s(?=$|[。；;，,！!？?）)】\\]\\s★☆＊*]|级)%s" % (_LABEL, LV, _ENUM)),
    # 标题行开头的方括号密级标注：“【秘密】关于加强值班工作的通知”；方括号必须紧贴密级词（“【秘密载体管理】……”不算）
    ("密级标识", "%s%s[【\\[（(〔［]\\s*%s%s%s\\s*[】\\]）)〕］]" % (_PRE, _URG, LV, _KIND, _SUF)),
    # “机密（解密时间：2030年1月1日）”“秘密（保密期限：5年）”：括注里写解密时间、保密期限
    ("密级与保密期限", "%s\\s*[（(【\\[]\\s*(?:解密(?:时间|日期|期限)?|保密期限)\\s*[：:][^）)】\\]\\n]{0,24}[）)】\\]]" % LV),
    # “绝密·启用前”“绝密★启用前”：考试、文件常见的密级标注
    ("密级标识", "%s\\s*[★☆＊·•・]?\\s*(?:启用前|开启前)" % LV),
    # 保密期限
    ("保密期限", "%s\\s*[：:]\\s*%s?\\s*%s" % (_KW, STAR, _TERM)),
    # “保密期限：至2030年12月31日”
    ("保密期限", "%s\\s*[：:]\\s*(?:至|到|截至|截止)?\\s*%s?\\s*(?:19|20)\\d\\d\\s*年" % (_KW, STAR)),
    ("保密期限", "^[^。；;，,\\n]{0,10}?%s\\s*[为是]?\\s*%s?\\s*%s\\s*[）)】\\]]?\\s*[。.]?\\s*$" % (_KW, STAR, _TERM)),
    ("保密期限", "(?<!国家)%s级?\\s*%s?\\s*[、，,/／和及与]?\\s*%s|[★☆＊][^\\n“”\"‘’]{0,12}%s|%s[^\\n“”\"‘’]{0,12}[★☆＊]" % (
        LV, STAR, _KW, _KW, _KW)),
    # 商业秘密标注（国企红线）：只认标注形态，不认“加强商业秘密保护”“涉及商业秘密”等叙述
    ("商业秘密标注", "%s\\s*[：:为是]?\\s*(?:核心|普通)?(?:商业秘密|商密)" % _LABEL),
    ("商业秘密标注", "[【\\[]\\s*(?:核心|普通)?(?:商业秘密|商密)\\s*(?:[★☆][^】\\]\\n]{0,20})?\\s*[】\\]]"),
    ("商业秘密标注",
     "[（(]\\s*(?:(?:核心|普通)(?:商业秘密|商密)|商密|(?:商业秘密|商密)\\s*[★☆])[^）)\\n]{0,20}[）)]"),
    ("商业秘密标注", "(?:核心|普通)?(?:商业秘密|商密)\\s*[★☆]"),
    ("商业秘密标注", "%s%s%s(?:核心|普通)?(?:商业秘密|商密)(?:[★☆][^\\n]{0,20}|%s)?%s\\s*%s%s" % (
        _PRE, _URG, _OPEN, _SUF, _CLOSE, _URG, "\\s*[。.]?" + _POST)),
]
MARK_PATTERNS = [
    # “本/此/该 + 材料……属内部文件/工作秘密/仅供内部”
    ("内部标注", "(?:本|此|该)(?:材料|文件|稿件|稿|资料|报告|件)[^。\\n]{0,6}"
                 "(?:内部资料|工作秘密|内部文件|内部材料|内部使用|内部参阅|不得外传|严禁外传|不得翻印|仅供内部)"),
    # 整行只有内部标注，可带括号和“注意保存”“不得翻印”等后缀
    ("内部标注", "^\\s*%s?\\s*%s\\s*%s?(?:\\s*[，,、；;　]?\\s*%s?\\s*%s\\s*%s?)*\\s*[。.]?\\s*$" % (
        _IN_OPEN, _IN_HEAD, _IN_CLOSE, _IN_OPEN, _IN_TAIL, _IN_CLOSE)),
]
# 闸门比通用机检更严：这些词出现在句子里也停（宁严勿漏）。PRI-006 不收，否则“加强内部资料管理”“注意保密”会误报规范文书
GATE_ONLY = [
    ("内部标注", "工作秘密|内部资料|不得外传|严禁外传|内部使用|仅供内部参考|内部参阅|注意保密"),
]
PATTERNS = [(k, re.compile(p)) for k, p in LABEL_PATTERNS + MARK_PATTERNS + GATE_ONLY]


def lint_patterns() -> Dict[str, str]:
    """生成 lint_rules.json 中 PRI-005、PRI-006 的 pattern：与本脚本同源，tests/secret 断言两者一致。"""
    join = lambda items: "|".join("(?:%s)" % p for _, p in items)  # noqa: E731
    return {"PRI-005": join(LABEL_PATTERNS), "PRI-006": join(MARK_PATTERNS)}


Item = Tuple[str, str]  # (位置标签, 文字)


def _root(zf: zipfile.ZipFile, name: str) -> ET.Element:
    if zf.getinfo(name).file_size > MAX_XML:
        raise ValueError("部件过大：" + name)
    return ET.fromstring(zf.read(name))


def _para_text(p: ET.Element) -> str:
    """段落文字：含修订删除的文字（保守起见一并检查）。"""
    parts = []
    for e in p.iter():
        if e.tag in (W + "t", W + "delText"):
            parts.append(e.text or "")
        elif e.tag == W + "tab":
            parts.append("\t")
    return "".join(parts)


def _paragraphs(root: ET.Element, base: str) -> List[Item]:
    """遍历部件内全部段落；文本框、表格内的段落单独标注来源。"""
    out: List[Item] = []
    counter = [0]

    def walk(el: ET.Element, ctx: str) -> None:
        for ch in el:
            if ch.tag == W + "txbxContent":
                walk(ch, "文本框")
            elif ch.tag == W + "tbl":
                walk(ch, ctx if ctx == "文本框" else "表格")
            elif ch.tag == W + "p":
                counter[0] += 1
                text = _para_text(ch)
                if text.strip():
                    if ctx == "正文":
                        label = "%s第%d段" % (base, counter[0]) if base == "正文" else base
                    else:
                        label = ctx if base == "正文" else base + ctx
                    out.append((label, text))
                walk(ch, ctx)
            else:
                walk(ch, ctx)

    walk(root, "正文")
    seen = set()  # mc:AlternateContent 中文本框常有两份相同内容，去重
    uniq = []
    for item in out:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return uniq


def _hf_labels(zf: zipfile.ZipFile) -> Dict[str, str]:
    """部件路径 -> 页眉/页脚标签（区分首页、偶数页）。"""
    labels: Dict[str, str] = {}
    names = set(zf.namelist())
    if "word/document.xml" not in names:
        return labels
    rels = {}
    rp = "word/_rels/document.xml.rels"
    if rp in names:
        for r in _root(zf, rp):
            rels[r.get("Id")] = r.get("Target", "")
    kinds = {"default": "", "first": "(首页)", "even": "(偶数页)"}
    for el in _root(zf, "word/document.xml").iter():
        if el.tag in (W + "headerReference", W + "footerReference"):
            tgt = rels.get(el.get(R + "id"), "").lstrip("/")
            path = tgt if tgt.startswith("word/") else "word/" + tgt
            word = "页眉" if el.tag == W + "headerReference" else "页脚"
            labels.setdefault(path, word + kinds.get(el.get(W + "type", "default"), ""))
    return labels


def extract_docx(path: Path) -> List[Item]:
    """抽取 docx 全部文字，返回 [(位置标签, 文字)]。"""
    items: List[Item] = []
    with zipfile.ZipFile(path) as zf:
        labels = _hf_labels(zf)
        for name in zf.namelist():
            if not re.fullmatch(r"word/[^/]+\.xml", name):
                continue
            base = name[5:-4]
            if name == "word/document.xml":
                items.extend(_paragraphs(_root(zf, name), "正文"))
            elif re.fullmatch(r"(header|footer)\d*", base):
                default = "页眉" if base.startswith("header") else "页脚"
                items.extend(_paragraphs(_root(zf, name), labels.get(name, default)))
            elif base in ("footnotes", "endnotes", "comments"):
                tag = {"footnotes": "脚注", "endnotes": "尾注", "comments": "批注"}[base]
                items.extend(_paragraphs(_root(zf, name), tag))
    return items


def _stext(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(S + "t"))


def extract_xlsx(path: Path) -> List[Item]:
    items: List[Item] = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if not name.startswith("xl/") or not name.endswith(".xml"):
                continue
            if name == "xl/workbook.xml":
                for sh in _root(zf, name).iter(S + "sheet"):
                    items.append(("工作表名", sh.get("name", "")))
            elif name == "xl/sharedStrings.xml":
                for si in _root(zf, name).iter(S + "si"):
                    items.append(("单元格", _stext(si)))
            elif re.fullmatch(r"xl/comments\d*\.xml", name):
                for c in _root(zf, name).iter(S + "comment"):
                    items.append(("批注", _stext(c)))
            elif re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
                sheet = name.rsplit("/", 1)[1][:-4]
                for el in _root(zf, name).iter():
                    tag = el.tag.replace(S, "")
                    if tag in ("oddHeader", "evenHeader", "firstHeader"):
                        items.append(("页眉(%s)" % sheet, el.text or ""))
                    elif tag in ("oddFooter", "evenFooter", "firstFooter"):
                        items.append(("页脚(%s)" % sheet, el.text or ""))
                    elif tag == "is":  # 内联字符串
                        items.append(("单元格(%s)" % sheet, _stext(el)))
    return items


def extract(path: Path) -> List[Item]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return extract_docx(path)
    if suffix == ".xlsx":
        return extract_xlsx(path)
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("gb18030", errors="replace")
    return [("第%d行" % i, line) for i, line in enumerate(text.splitlines(), 1) if line.strip()]


def scan(items: List[Item]) -> List[Tuple[str, str, str]]:
    """返回 [(位置, 类型, 命中词)]。逐段用原文匹配（不做空白折叠），与 PRI-005/PRI-006 的行为一致。"""
    hits = []
    for label, text in items:
        for kind, rx in PATTERNS:
            for m in rx.finditer(text):
                if m.end() > m.start():
                    hits.append((label, kind, m.group(0).strip()))
    return hits


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="检查文件中的保密标识（含页眉页脚、文本框、表格），命中退出码 1。")
    ap.add_argument("files", nargs="+", help="txt、md、docx、xlsx 文件")
    args = ap.parse_args(argv)
    code = 0
    for f in args.files:
        path = Path(f)
        try:
            items = extract(path)
        except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError, KeyError) as exc:
            print("[读取失败] %s：%s" % (path.name, exc))
            code = 2
            continue
        hits = scan(items)
        if not hits:
            print("[未发现保密标识] " + path.name)
            continue
        if code == 0:
            code = 1
        print("[发现保密标识] %s：共 %d 处，请立即停止处理并按保密红线告知用户" % (path.name, len(hits)))
        seen = set()
        for label, kind, word in hits:
            if (label, word) not in seen:
                seen.add((label, word))
                print("  [%s] %s：%s" % (label, kind, word))
        if any(k == "商业秘密标注" for _, k, _ in hits):
            print("  提示：含“商业秘密标注”，按商业秘密红线同样停止处理，不得送入外部模型，请告知用户走合规流程")
    return code


if __name__ == "__main__":
    sys.exit(main())
