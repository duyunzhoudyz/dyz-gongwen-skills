# -*- coding: utf-8 -*-
"""中小学行业包（gongwen-k12）的本地脱敏与检查工具。

用法：
    python scripts/k12_check.py mask <学生事实表> [--name-col 列名] [--drop-sensitive] [--json]
    python scripts/k12_check.py unmask <评语文件> <对照表.csv> [--json]
    python scripts/k12_check.py comments <评语文件> [--facts 脱敏事实表] [--stage 学段]
                                [--min-chars N] [--max-chars N] [--similarity 0.6]
                                [--person second|third|any] [--json] [--strict]
    python scripts/k12_check.py parents <面向家长的文稿> [--stage 学段] [--json] [--strict]
    python scripts/k12_check.py general <校内综合文书> [--stage 学段] [--json] [--strict]

子命令：
    mask      学生名单或事实表在本机脱敏：姓名换成 S01、S02 编号，删去身份证号、手机号、学号、住址，
              另存脱敏稿和对照表。对照表只留在本机，不交给 AI。屏幕输出不含任何姓名。
              加 --drop-sensitive 时，涉及家庭、健康、处分信息的整句换成“【已略去：……信息】”。
    unmask    把评语中的编号换回姓名，另存“姓名版”。屏幕输出不含任何姓名。
    comments  学生评语批量检查：贬损和标签化用语、考试排名和分数、家庭健康处分等敏感信息、
              身份证号手机号、承诺升学、评语之间雷同、共用套句、篇幅、人称、套话占比、待补标记；
              给了 --facts 时，再与事实表对账（缺评语、无事实依据、数字在事实表中找不到）。
    parents   面向家长文书检查（致家长的一封信、家长会讲话稿、给家长的通知）：要求家长检查批改作业、
              给家长布置作业、公布成绩分数和排名、一二年级书面作业、收费和统一购买、推荐校外培训、
              强制参加课后服务、课后服务讲新课、承诺升学、点名批评学生、要求转发点赞等。
    general   校内综合文书检查（学期计划总结、督导自评、课后服务方案、安全教育和教研记录）：
              公布考试成绩排名、补造台账记录、课后服务讲新课和强制参加、学生隐私外露（K12-G04）。

姓名识别与遮蔽：
    K12-G04 由共享模块 scripts/gw_names.py 识别学生实名：先找“低保家庭学生”“建档立卡户”等敏感身份词作锚点，
    再在锚点旁取候选姓名并打分。得分 6 分及以上为 P0，5 分为 P1；敏感身份词后接“某同学”“王某”等代称，仍为 P0。
    “特困学生：一年级、三年级各2人”这类汇总写法、没有冒号的“名单已报送”不报。
    general、parents 的 excerpt（含 JZ-012“点名批评”）会把识别出的姓名换成〔姓名1〕〔姓名2〕，文本和 --json 输出都生效。
    “、”并列的后项（“周梓涵、吴雨桐等5人”）由共享模块一律登记并遮蔽，即使自身分数不足；宁可多遮，个别非姓名词（单亲、杜鹃花）可能被遮成〔姓名N〕。
    comments 的 label 是教师在本机定位用的标识（编号或姓名），原样保留；只遮蔽 excerpt。
    文件名回显：general、parents、comments 的报告头和 --json 的 file 字段，会把文件名里与正文已识别姓名相同的部分遮蔽
    （“马小明家访记录.txt”显示为“〔姓名1〕家访记录.txt”）。文件名里有、正文没有识别出来的姓名遮不住，
    请在把报告发给别人之前自行改文件名。
    K12-G04 敏感身份词除“低保家庭”“特困”等外，还含“受到（警告、记过等）处分的”后接“学生、同学”的写法
    （“受到警告处分的学生孙浩宇”）；“受到处分的学生名单已按规定报送”这类没有姓名的汇总写法不报。
    已知局限：
    1. 没有敏感身份词等锚点的裸姓名识别不了，只有同一姓名在别处被锚点识别过，才靠全文姓名表遮蔽。
    2. 身份词与姓名之间隔着其他成分（“低保家庭的三年级学生周梓涵”“特困学生，现就读于二班的周梓涵”）识别不了。
    3. 与常用词同形的姓名（刘海、林海、黎明、高峰）只在有强证据时识别（姓名后紧跟“同学”等）；其余写法漏报。
    4. 两字少见姓或歧义姓的姓名、名字里含“会”“山”等非名用字的姓名、名字用字不在常见名用字表里的三字名，
       在词表外的后续动词下可能漏报；全文遮蔽是整串替换，可能多遮。
    5. 带“·”的姓名、外文名、昵称识别不了；“受到处分”的写法只覆盖后接“学生、同学”的情形，
       “该生因打架受到处分”这类写法不报。
    6. 敏感身份词是固定清单：残疾、受助、留守学生、被记过的学生、患病学生、“学生 + 姓名 + 的 + 亲属 + 敏感事件”等不在内，不报。
    7. Markdown 表格中姓名列默认报 P1、有困难类型或心理等敏感列时报 P0，无姓名类表头或非 Markdown 表格的姓名仍可能漏报。锚点之后由“、”（名单语境下还有“，”）和连词“和、与、及、同、跟”连接的并列链：只要链中任一项已识别，链上其余姓氏开头的 2～4 字项（含与常用词同形的、复姓的）一律登记进姓名表并遮蔽，首项未识别而后项识别时回溯登记首项（宁可多遮，“单亲”“杜鹃花”可能被遮成〔姓名N〕）；边界：整条链上没有任何一项被识别时不登记；并列链之外的同形名、无锚点的姓名仍识别不了；同一锚点下的并列姓名合并成一条（摘录含全部占位符）。姓名表覆盖全部隐私规则，不分文书类型（是否报出仍按文书类型）。
    缺少 scripts/gw_names.py 或 gw_names.json、数据损坏时，所有子命令（含 mask、unmask）退出码 2，不静默降级。

输入：.txt、.md、.csv；.docx 需要 python-docx，.xlsx 需要 openpyxl，未安装时给出安装提示并返回 2。
comments、parents 只检查【起草说明】之前的内容。

退出码：0 正常；--strict 时存在 P0 返回 1；输入错误、缺少共享模块返回 2。
只用标准库，不联网；文件一律按 UTF-8 读写；输出文件已存在时加 -v2、-v3，不覆盖。
规则依据见 references/redlines.md 和 references/sources.md。
"""
from __future__ import annotations

import argparse
import csv
import difflib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

VERSION = "1.2.6"
BOUNDARY = "【起草说明】"
# 与 gongwen_lint.py、fact_diff.py 的分界行写法保持一致
DRAFT_NOTE_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:(?:\*\*|__)\s*)?" + re.escape(BOUNDARY))
TEXT_SUFFIXES = (".txt", ".md")
SUPPORTED_SUFFIXES = (".txt", ".md", ".csv", ".docx", ".xlsx")
STAGES = ("义务教育", "高中", "中职")
LEVELS = ("P0", "P1", "P2")

CODE_PREFIX = "S"
CODE_RE = re.compile(r"(?<![A-Za-z0-9])S\d{2,4}(?![0-9])")

# ---------------------------------------------------------------------------
# 依据（详见 references/sources.md）
# ---------------------------------------------------------------------------
B_SHUANGJIAN_4 = "《关于进一步减轻义务教育阶段学生作业负担和校外培训负担的意见》（2021年）第4条"
B_SHUANGJIAN_5 = "《关于进一步减轻义务教育阶段学生作业负担和校外培训负担的意见》（2021年）第5条"
B_SHUANGJIAN_9 = "《关于进一步减轻义务教育阶段学生作业负担和校外培训负担的意见》（2021年）第9条"
B_SHUANGJIAN_10 = "《关于进一步减轻义务教育阶段学生作业负担和校外培训负担的意见》（2021年）第10条"
B_EXAM = "教育部办公厅《关于加强义务教育学校考试管理的通知》（教基厅函〔2021〕34号）"
B_EXAM_2025 = "教育部办公厅《关于进一步加强中小学日常考试管理的通知》（教基厅〔2025〕3号）第14条"
B_MINOR = "《中华人民共和国未成年人保护法》（2020年修订）第四条"
B_BANZHUREN = "《中小学班主任工作规定》（教基一〔2009〕12号）第十一条"
B_JIAOFU = "《中小学教辅材料管理办法》（新广出发〔2015〕45号）"
B_SAFETY_46 = "《中小学幼儿园安全管理办法》（2006年）第四十六条"
B_BUKE = "《严禁中小学校和在职中小学教师有偿补课的规定》（教师〔2015〕5号）"
B_XIETONG = "《关于健全学校家庭社会协同育人机制的意见》（教基〔2022〕7号）"
B_PROFILE = "references/_shared/profiles/units/zhongxiaoxue.md 第八部分第4条、第九部分第4条"   # 人称、套话
B_PROFILE_PRIVACY = "references/_shared/profiles/units/zhongxiaoxue.md 第六部分第1条"
B_PROFILE_COMMENT = "references/_shared/profiles/units/zhongxiaoxue.md 第六部分第6条"         # 千人一面、贬损、标签化
B_LABEL = (B_EXAM + "（考试结果不得用于给学生贴标签）；" + B_BANZHUREN + "（实事求是评定操行）；"
           + B_PROFILE_COMMENT)
B_PROMISE = "references/redlines.md 第九条；references/_shared/profiles/units/zhongxiaoxue.md 第十部分（不承诺升学结果）"
B_GUARDRAIL_1 = "references/_shared/guardrails.md 第一条第3款"
B_GUARDRAIL_2 = "references/_shared/guardrails.md 第二条"
B_LOCAL = "以学校或当地教育部门规定为准"


class InputError(Exception):
    """输入错误：文件不存在、格式不支持、缺少依赖、内容无法识别。返回码 2。"""


# ---------------------------------------------------------------------------
# 共享姓名模块（scripts/gw_names.py + gw_names.json，源文件在仓库 shared/scripts/，由 tools/sync_shared.py 同步）
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent


def _load_shared(stem: str) -> Any:
    """按文件路径加载同目录的共享模块；模块名按 skill 目录区分，避免工具箱同进程加载多个引擎时串用缓存。"""
    path = _HERE / f"{stem}.py"
    if not path.is_file():
        raise InputError(f"缺少 scripts/{stem}.py（共享模块），请重新安装本包或运行 tools/sync_shared.py")
    name = f"_gw_{_HERE.parent.name}_{stem}"
    mod = sys.modules.get(name)
    if mod is None:
        try:
            spec = importlib.util.spec_from_file_location(name, str(path))
            if spec is None or spec.loader is None:
                raise ImportError("无法创建模块说明")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        except Exception as exc:  # 共享模块损坏：按输入错误处理，不静默降级
            sys.modules.pop(name, None)
            raise InputError(f"共享模块 scripts/{stem}.py 无法加载：{exc}") from exc
    return mod


def shared_names() -> Tuple[Any, Any]:
    """返回 (gw_names 模块, 姓名数据)；缺文件或数据损坏抛 InputError（退出码 2）。"""
    mod = _load_shared("gw_names")
    try:
        lex = mod.load_lexicon()
    except mod.LexiconError as exc:
        raise InputError(str(exc)) from exc
    return mod, lex


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def unique_path(path: Path) -> Path:
    """已存在时依次尝试 -v2、-v3……，不覆盖已有文件。"""
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}-v{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError(f"{path.name} 不是 UTF-8 编码的文本，请另存为 UTF-8 后再试") from exc


def _cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return re.sub(r"\s*\n\s*", " ", text)


def parse_md_tables(lines: Sequence[str]) -> List[List[List[str]]]:
    """从文本行中解析 Markdown 表格，跳过分隔行。"""
    tables: List[List[List[str]]] = []
    current: List[List[str]] = []
    for line in list(lines) + [""]:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.count("|") >= 2:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c) and any(cells):
                continue  # 分隔行
            current.append(cells)
        else:
            if current:
                tables.append(current)
                current = []
    return tables


@dataclass
class Document:
    """读入的文件：文本行（不含表格行）与表格。"""
    path: Path
    lines: List[str] = field(default_factory=list)          # 全部文本行（含 Markdown 表格行）
    tables: List[List[List[str]]] = field(default_factory=list)
    kind: str = "text"                                      # text / table / docx
    table_after_paragraph: List[int] = field(default_factory=list)  # Word 表格前的正文段落数


def load_document(path: Path) -> Document:
    if not path.is_file():
        raise InputError(f"找不到文件：{path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise InputError(f"不支持的格式 {suffix}，只支持 {'、'.join(SUPPORTED_SUFFIXES)}")
    doc = Document(path=path)
    if suffix in TEXT_SUFFIXES:
        text = read_text_file(path).replace("\r\n", "\n").replace("\r", "\n")
        doc.lines = text.split("\n")
        doc.tables = parse_md_tables(doc.lines)
        doc.kind = "text"
    elif suffix == ".csv":
        text = read_text_file(path)
        rows = [[_cell(c) for c in row] for row in csv.reader(text.splitlines())]
        doc.tables = [[r for r in rows if any(r)]]
        doc.kind = "table"
    elif suffix == ".docx":
        try:
            import docx  # type: ignore
        except ImportError as exc:
            raise InputError("读取 .docx 需要 python-docx，请先运行：pip install python-docx") from exc
        try:
            d = docx.Document(str(path))
        except Exception as exc:  # 文件损坏或不是 docx
            raise InputError(f"无法读取 {path.name}：{exc}") from exc
        doc.lines = [p.text for p in d.paragraphs]
        paragraphs = 0
        for child in d.element.body.iterchildren():
            if child.tag.endswith("}p"):
                paragraphs += 1
            elif child.tag.endswith("}tbl"):
                doc.table_after_paragraph.append(paragraphs)
        for t in d.tables:
            rows = [[_cell(c.text) for c in r.cells] for r in t.rows]
            doc.tables.append([r for r in rows if any(r)])
        doc.kind = "docx"
    else:  # .xlsx
        try:
            import openpyxl  # type: ignore
        except ImportError as exc:
            raise InputError("读取 .xlsx 需要 openpyxl，请先运行：pip install openpyxl") from exc
        try:
            wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        except Exception as exc:
            raise InputError(f"无法读取 {path.name}：{exc}") from exc
        ws = wb.worksheets[0]
        rows = [[_cell(c) for c in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
        doc.tables = [[r for r in rows if any(r)]]
        doc.kind = "table"
    return doc


def cut_at_boundary(lines: Sequence[str]) -> Tuple[List[str], Optional[int]]:
    for index, line in enumerate(lines):
        if DRAFT_NOTE_RE.match(line):
            return list(lines[:index]), index + 1
    return list(lines), None


def find_column(header: Sequence[str], names: Sequence[str]) -> Optional[int]:
    """按列名查找列：先全等，再包含。"""
    cleaned = [re.sub(r"\s", "", h) for h in header]
    for name in names:
        for i, h in enumerate(cleaned):
            if h == name:
                return i
    for name in names:
        for i, h in enumerate(cleaned):
            if name in h:
                return i
    return None


def mask_digits(text: str) -> str:
    """输出摘录时遮盖长数字，避免把证件号、手机号原样打印出来。"""
    return re.sub(r"\d{6,}", lambda m: m.group(0)[:3] + "*" * (len(m.group(0)) - 5) + m.group(0)[-2:], text)


def mask_names(table: Any, text: str) -> str:
    """用全文姓名表遮蔽摘录里的姓名。摘录两端可能把姓名截断（如“……低保户王小”），
    端点处残留的姓名片段（至少 2 字）也一并换成占位符（实现在共享模块 NameTable.mask_fragment）。"""
    return table.mask_fragment(text)


def excerpt_of(text: str, start: int, end: int, radius: int = 10) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return mask_digits(text[left:right].strip())


# ---------------------------------------------------------------------------
# 个人信息
# ---------------------------------------------------------------------------

ID_RE = re.compile(r"(?<![0-9A-Za-z])\d{17}[\dXx](?![0-9A-Za-z])")
MOBILE_RE = re.compile(r"(?<![0-9])1[3-9]\d{9}(?![0-9])")
STUDENT_ID_HEADERS = ("学号", "学籍号", "考号", "准考证号", "学生卡号")
STUDENT_NO_RE = re.compile(r"(学号|学籍号|考号|准考证号|学生卡号)\s*[：:为是]?\s*[A-Za-z0-9]{4,}")
ADDRESS_RE = re.compile(r"(家庭住址|家庭地址|住址|居住地址)\s*[：:为是]?\s*[^，。；;,\s|]{2,}")
SENSITIVE_HEADER_NAMES = ("学号", "学籍号", "身份证", "证件", "电话", "手机", "联系方式", "住址", "地址",
                          "家长姓名", "监护人", "父亲", "母亲")
NAME_HEADER_NAMES = ("姓名", "学生姓名", "学生", "名字", "name", "Name")
LABEL_HEADER_NAMES = ("编号", "代号", "代称", "学生", "姓名", "学生姓名", "序号", "座号", *STUDENT_ID_HEADERS)
COMMENT_HEADER_NAMES = ("评语", "教师评语", "班主任评语", "寄语", "班主任寄语", "评价")

FAMILY_RE = re.compile(r"单亲|离异|父母离婚|父母分居|留守|低保|贫困户|贫困家庭|建档立卡|困难家庭|家庭困难|家境贫寒|孤儿|事实无人抚养")
HEALTH_RE = re.compile(r"抑郁|焦虑症|多动症|多动障碍|ADHD|自闭症|孤独症|心理疾病|心理问题|心理障碍|精神疾病|精神障碍|病史|残疾|随班就读|特殊教育|智力障碍|读写障碍")
DISCIPLINE_RE = re.compile(r"处分|记过|严重警告|留校察看|劝退|开除学籍|派出所")
# 只用于脱敏时识别和略去，不用于评语检查（“焦虑”等词在评语中另有正常用法）
FAMILY_EXTRA_RE = re.compile(r"去世|病逝|过世|坐牢|服刑|再婚|重组家庭|寄养"
                             r"|跟(?:着)?(?:奶奶|爷爷|外婆|外公|姥姥|姥爷)(?:生活|住|长大)")
HEALTH_EXTRA_RE = re.compile(r"焦虑|心理老师|心理咨询|心理辅导|心理干预|服药|住院")
SENSITIVE_TYPES = (("家庭", (FAMILY_RE, FAMILY_EXTRA_RE)), ("健康", (HEALTH_RE, HEALTH_EXTRA_RE)),
                   ("处分", (DISCIPLINE_RE,)))

# 复姓和单姓来自共享数据 gw_names.json（全集与原脚本内嵌的表相同）。按行识别时首字须在表中或为复姓，
# 避免把“需改进：”之类的栏目当成学生。导入时读不到共享数据则置空，由 main() 和各检查函数统一报错退出（码 2）。
_SHARED_LOAD_ERROR = ""
try:
    _LEX0 = shared_names()[1]
    COMPOUND_SURNAMES = tuple(_LEX0.compound)
    SURNAMES = set(_LEX0.surnames)
except InputError as _exc:
    _SHARED_LOAD_ERROR = str(_exc)
    COMPOUND_SURNAMES = ()
    SURNAMES = set()
NOT_NAMES = {"姓名", "学生", "说明", "备注", "要求", "时间", "地点", "班级", "事实", "表现", "情况",
             "优点", "不足", "建议", "期望", "进步", "特点", "评语", "注意", "附件", "联系人", "主题",
             "目的", "内容", "过程", "结果", "问题", "措施", "总结", "计划", "附", "示例", "格式",
             "需改进", "需要改进", "改进", "缺点", "特长", "爱好", "获奖", "家长", "家长电话", "联系电话",
             "电话", "手机", "学号", "身份证号", "住址", "家庭住址", "优点和不足", "成绩", "原因", "安全",
             "全班", "全体", "来源", "信息", "平时", "文明", "常规", "明天", "今天", "昨天", "关注", "和谐",
             # 表头里的教师和职务（如“班主任：李老师”“班长：……”），不是学生
             "班主任", "副班主任", "任课教师", "教师", "老师", "组长", "小组长", "年级", "学期", "学段",
             "班长", "副班长", "队长", "课代表", "记录人", "主讲", "主持人", "执教"}
# 2～4 字的栏目名常以这些词结尾（如“家长电话”“获奖情况”“兴趣爱好”），按行识别时不当作姓名
NOT_NAME_SUFFIXES = ("情况", "表现", "要求", "说明", "时间", "地点", "方式", "电话", "号码", "证号", "地址",
                     "住址", "内容", "建议", "改进", "爱好", "特长", "成绩", "备注", "意见", "结果", "目标",
                     "措施", "问题", "不足", "优点", "缺点", "评价", "评语", "获奖", "奖励", "职务",
                     "老师", "教师", "委员", "代表", "组长", "班长", "主任")
LINE_NAME_RE = re.compile(
    r"^\s*(?:[（(]?\d{1,3}[）).、．]\s*)?(?P<name>[一-龥]{2,4}|[一-龥]{1,6}·[一-龥]{1,8})\s*[：:]"
)
# 名字部分（如“一鸣”）左右都是汉字、又不是常见的连接字时，多半是成语或普通词语的一部分，不替换
CJK_CHAR_RE = re.compile(r"[一-龥]")
GIVEN_LEFT_OK = set("和与跟同及让请叫给对帮把被向是由替为陪喊教问找带")
GIVEN_RIGHT_OK = set("和与跟同及的是在也都把被给说对很又还就才们等这那有没不能会要想今昨上下每已曾")
# “××：李老师”“××：数学王老师、英语张老师”这类行写的是教师，不是学生
_SUBJECTS = ("语文|数学|英语|科学|音乐|美术|体育|道法|道德与法治|信息科技|信息技术|物理|化学|生物|历史|地理"
             "|政治|心理|劳动|书法")
_TEACHER_ONE = (r"(?:" + _SUBJECTS + r")?(?:" + "|".join(COMPOUND_SURNAMES) + r"|[一-龥])(?:老师|教师)")
TEACHER_VALUE_RE = re.compile(r"^\s*" + _TEACHER_ONE + r"(?:\s*[、，,和及]\s*" + _TEACHER_ONE + r")*\s*[。；;]?\s*$")


def looks_like_name(word: str) -> bool:
    """按行识别时判断“××：”中的××是不是学生姓名。"""
    if word in NOT_NAMES or CODE_RE.fullmatch(word):
        return False
    if "·" in word:
        return True
    if any(word.endswith(s) for s in NOT_NAME_SUFFIXES) and word not in COMPOUND_SURNAMES:
        return False
    gw, lex = shared_names()
    return bool(gw.has_surname_prefix(word, lex))


def sensitive_types(text: str) -> List[str]:
    """返回文字涉及的敏感信息类型：家庭、健康、处分。"""
    return [name for name, regexes in SENSITIVE_TYPES if any(r.search(text) for r in regexes)]


def drop_sensitive_sentences(text: str, counts: Dict[str, int]) -> str:
    """把涉及家庭、健康、处分信息的整句换成“【已略去：……信息】”，计数写入 counts。"""
    parts = re.split(r"([。！？；;!?])", text)
    out: List[str] = []
    for i in range(0, len(parts), 2):
        seg = parts[i]
        delim = parts[i + 1] if i + 1 < len(parts) else ""
        types = sensitive_types(seg)
        if types:
            lead = re.match(r"^\s*", seg).group(0)  # type: ignore[union-attr]
            for t in types:
                counts[t] = counts.get(t, 0) + 1
            out.append(lead + "【已略去：" + "、".join(types) + "信息】" + delim)
        else:
            out.append(seg + delim)
    return "".join(out)


def scrub_pii(text: str) -> Tuple[str, Dict[str, int]]:
    """删去身份证号、手机号、带标签的学号和住址，返回处理后的文字和计数。"""
    counts = {"身份证号": 0, "手机号": 0, "学号等编号": 0, "住址": 0}

    def sub(pattern: re.Pattern, repl, key: str, value: str) -> str:
        new, n = pattern.subn(repl, value)
        counts[key] += n
        return new

    text = sub(STUDENT_NO_RE, lambda m: m.group(1) + "【已删除】", "学号等编号", text)
    text = sub(ID_RE, "【已删除身份证号】", "身份证号", text)
    text = sub(MOBILE_RE, "【已删除手机号】", "手机号", text)
    text = sub(ADDRESS_RE, lambda m: m.group(1) + "【已删除】", "住址", text)
    return text, counts


def given_name(name: str) -> str:
    if "·" in name:
        return name.split("·")[0]
    for surname in COMPOUND_SURNAMES:
        if name.startswith(surname) and len(name) > len(surname):
            return name[len(surname):]
    return name[1:]


def make_code(index: int, width: int) -> str:
    return f"{CODE_PREFIX}{index:0{width}d}"


# ---------------------------------------------------------------------------
# mask：本地脱敏
# ---------------------------------------------------------------------------

def discover_names(doc: Document, name_col: Optional[str]) -> Tuple[List[Tuple[str, int, int]], str]:
    """返回 [(姓名, 表格序号或 -1, 行号)]，以及识别方式。"""
    wanted = (name_col,) if name_col else NAME_HEADER_NAMES
    for t_index, table in enumerate(doc.tables):
        if not table:
            continue
        col = find_column(table[0], wanted)
        if col is None:
            continue
        found = []
        for r_index, row in enumerate(table[1:], start=1):
            if col < len(row):
                value = re.sub(r"\s", "", row[col])
                if value and not CODE_RE.fullmatch(value):
                    found.append((value, t_index, r_index))
        if found:
            return found, "table"
    if name_col:
        raise InputError(f"表格中没有找到名为“{name_col}”的列")
    found = []
    for l_index, line in enumerate(doc.lines):
        if line.strip().startswith("|"):
            continue
        m = LINE_NAME_RE.match(line)
        if m and looks_like_name(m.group("name")) and not TEACHER_VALUE_RE.match(line[m.end():]):
            found.append((m.group("name"), -1, l_index))
    if len(found) >= 2:
        return found, "lines"
    return [], "none"


def build_mask_regex(mapping: Dict[str, str]) -> Optional[re.Pattern]:
    if not mapping:
        return None
    keys = sorted(mapping, key=len, reverse=True)
    return re.compile("|".join(re.escape(k) for k in keys))


def mask_document(path: Path, name_col: Optional[str] = None, drop_sensitive: bool = False) -> dict:
    doc = load_document(path)
    names, how = discover_names(doc, name_col)
    if not names:
        raise InputError(
            "没有识别到学生姓名。表格请用“姓名”作表头（或用 --name-col 指定列名）；"
            "文本请按“姓名：具体表现”每行写一名学生。"
        )
    width = max(2, len(str(len(names))))
    codes: List[str] = []
    first_code: Dict[str, str] = {}
    duplicates = 0
    for index, (name, _t, _r) in enumerate(names, start=1):
        code = make_code(index, width)
        codes.append(code)
        if name in first_code:
            duplicates += 1
        else:
            first_code[name] = code
    # 全文替换表：全名优先；三字及以上姓名的名字（如“小明”）也替换，单字名不替换
    replace_map: Dict[str, str] = dict(first_code)
    for name, code in first_code.items():
        g = given_name(name)
        if len(g) >= 2 and g not in replace_map and g not in NOT_NAMES:
            replace_map[g] = code
    pattern = build_mask_regex(replace_map)
    full_names = set(first_code)

    pii_total = {"身份证号": 0, "手机号": 0, "学号等编号": 0, "住址": 0}
    dropped: Dict[str, int] = {"家庭": 0, "健康": 0, "处分": 0}
    name_hits = 0
    given_skipped = 0
    given_ambiguous = 0

    def substitute(regex: re.Pattern, table: Dict[str, str], value: str) -> str:
        nonlocal name_hits, given_skipped, given_ambiguous

        def repl(m: "re.Match[str]") -> str:
            nonlocal name_hits, given_skipped, given_ambiguous
            key = m.group(0)
            if key not in full_names:  # 只是名字部分：左右都是汉字且不是连接字的，视为词语，不替换
                text, s, e = m.string, m.start(), m.end()
                left = text[s - 1] if s > 0 else ""
                right = text[e] if e < len(text) else ""
                left_word = bool(CJK_CHAR_RE.match(left)) and left not in GIVEN_LEFT_OK
                right_word = bool(CJK_CHAR_RE.match(right)) and right not in GIVEN_RIGHT_OK
                if left_word and right_word:
                    given_skipped += 1
                    return key
                if left_word or right_word:
                    # 一侧与其他汉字相连（如“明月当空”），可能是词语；为保护隐私照常替换，提示人工核对
                    given_ambiguous += 1
            name_hits += 1
            return table[key]

        return regex.sub(repl, value)

    def clean(value: str, row_code: Optional[str] = None, row_name: Optional[str] = None) -> str:
        if drop_sensitive:
            value = drop_sensitive_sentences(value, dropped)
        if row_code and row_name:
            # 本行学生的姓名优先换成本行编号（同名学生各用各的编号）
            local = {row_name: row_code}
            g = given_name(row_name)
            if len(g) >= 2:
                local[g] = row_code
            value = substitute(build_mask_regex(local), local, value)  # type: ignore[arg-type]
        if pattern is not None:
            value = substitute(pattern, replace_map, value)
        value, counts = scrub_pii(value)
        for k, v in counts.items():
            pii_total[k] += v
        return value

    sensitive_codes: List[str] = []

    def note_sensitive(code: str, text: str) -> None:
        if sensitive_types(text) and code not in sensitive_codes:
            sensitive_codes.append(code)

    out_lines: List[str] = []
    if how == "table":
        row_info = {(t, r): (codes[i], names[i][0]) for i, (_n, t, r) in enumerate(names)}
        t_name = names[0][1]
        table_out: List[List[List[str]]] = []
        for t_index, table in enumerate(doc.tables):
            header = table[0] if table else []
            name_idx = find_column(header, (name_col,) if name_col else NAME_HEADER_NAMES) if t_index == t_name else None
            drop_cols = {i for i, h in enumerate(header)
                         if i != name_idx and any(s in re.sub(r"\s", "", h) for s in SENSITIVE_HEADER_NAMES)}
            new_table = []
            for r_index, row in enumerate(table):
                if r_index == 0:
                    new_row = ["编号" if i == name_idx else h for i, h in enumerate(row)]
                    new_table.append(new_row)
                    continue
                code, real = row_info.get((t_index, r_index), (None, None))
                new_row = []
                for c_index, cell in enumerate(row):
                    if c_index == name_idx and code:
                        new_row.append(code)
                        name_hits += 1
                    elif c_index in drop_cols and cell:
                        new_row.append("【已删除】")
                    else:
                        new_row.append(clean(cell, code, real))
                if code:
                    note_sensitive(code, " ".join(row))
                new_table.append(new_row)
            table_out.append(new_table)
        if doc.kind == "text":
            # 文本文件：表格行按新表格重写，其余文字逐行替换
            table_iter = iter(table_out)
            in_table = False
            for line in doc.lines:
                is_row = line.strip().startswith("|") and line.strip().count("|") >= 2
                if is_row:
                    if not in_table:
                        in_table = True
                        out_lines.extend(render_md_table(next(table_iter, [])))
                    continue
                in_table = False
                out_lines.append(clean(line))
        else:
            for line in doc.lines:
                if line.strip():
                    out_lines.append(clean(line))
            for t in table_out:
                if out_lines:
                    out_lines.append("")
                out_lines.extend(render_md_table(t))
    else:
        line_code = {r: (codes[i], names[i][0]) for i, (_n, _t, r) in enumerate(names)}
        for l_index, line in enumerate(doc.lines):
            info = line_code.get(l_index)
            if info:
                code, real = info
                m = LINE_NAME_RE.match(line)
                rest = line[m.end():] if m else line
                prefix = line[:m.start("name")] if m else ""
                new_line = prefix + code + "：" + clean(rest, code, real).lstrip()
                name_hits += 1
                note_sensitive(code, rest)
                out_lines.append(new_line)
            else:
                out_lines.append(clean(line))
        for table in doc.tables if doc.kind == "docx" else []:
            out_lines.append("")
            out_lines.extend(render_md_table([[clean(c) for c in row] for row in table]))

    out_suffix = path.suffix.lower() if path.suffix.lower() in TEXT_SUFFIXES else ".md"
    masked_path = unique_path(path.with_name(f"{path.stem}-脱敏{out_suffix}"))
    map_path = unique_path(path.with_name(f"{path.stem}-对照表.csv"))
    masked_path.write_text("\n".join(out_lines).rstrip("\n") + "\n", encoding="utf-8")
    with map_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["编号", "姓名"])
        for code, (name, _t, _r) in zip(codes, names):
            writer.writerow([code, name])
    return {
        "mode": "mask",
        "file": path.name,
        "students": len(names),
        "name_replacements": name_hits,
        "duplicate_names": duplicates,
        "removed": pii_total,
        "sensitive_codes": sensitive_codes,
        "drop_sensitive": drop_sensitive,
        "dropped": dropped,
        "given_name_skipped": given_skipped,
        "given_name_ambiguous": given_ambiguous,
        "masked_file": str(masked_path),
        "mapping_file": str(map_path),
    }


def render_md_table(table: Sequence[Sequence[str]]) -> List[str]:
    if not table:
        return []
    width = max(len(r) for r in table)
    rows = [list(r) + [""] * (width - len(r)) for r in table]
    out = ["| " + " | ".join(c.replace("|", "／") for c in rows[0]) + " |",
           "|" + "---|" * width]
    for r in rows[1:]:
        out.append("| " + " | ".join(c.replace("|", "／") for c in r) + " |")
    return out


def render_mask_text(report: dict) -> str:
    removed = report["removed"]
    lines = [
        f"已脱敏：识别学生 {report['students']} 名，替换姓名 {report['name_replacements']} 处；"
        f"删除身份证号 {removed['身份证号']} 处、手机号 {removed['手机号']} 处、"
        f"学号等编号 {removed['学号等编号']} 处、住址 {removed['住址']} 处。",
        f"脱敏稿：{report['masked_file']}（交给 AI 使用这一份）",
        f"对照表：{report['mapping_file']}（只保存在本机，不要发给 AI，也不要让 AI 读取）",
    ]
    if report["duplicate_names"]:
        lines.append(f"注意：有 {report['duplicate_names']} 名学生同名，已分别编号，请在对照表中核对。")
    dropped = report.get("dropped", {})
    if report.get("drop_sensitive") and any(dropped.values()):
        detail = "、".join(f"{k}信息 {v} 处" for k, v in dropped.items() if v)
        lines.append(f"已略去：{detail}（整句换成“【已略去：……信息】”）"
                     + (f"，涉及 {'、'.join(report['sensitive_codes'])}" if report["sensitive_codes"] else "") + "。")
    elif report.get("drop_sensitive"):
        lines.append("已略去：没有发现涉及家庭、健康、处分信息的句子。")
    elif report["sensitive_codes"]:
        lines.append("提示：" + "、".join(report["sensitive_codes"])
                     + " 的事实涉及家庭、健康或处分信息，脱敏稿中仍保留。评语和面向家长的材料不写这类内容；"
                     "请加 --drop-sensitive 重新运行，这些句子会换成“【已略去：……信息】”。")
    if report.get("given_name_skipped"):
        lines.append(f"提示：有 {report['given_name_skipped']} 处名字与前后文字连成词语（如成语），未替换，请在脱敏稿中核对。")
    if report.get("given_name_ambiguous"):
        lines.append(f"提示：有 {report['given_name_ambiguous']} 处单独出现的名字与前后的字相连，已换成编号；"
                     "如果其中有成语或普通词语（如“明月当空”），请在本机的脱敏稿中改回。")
    lines.append("提示：家长姓名、单字名的昵称等无法自动识别，交给 AI 之前请再看一遍脱敏稿。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# unmask：还原姓名
# ---------------------------------------------------------------------------

def unmask_document(path: Path, mapping_path: Path) -> dict:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        raise InputError("unmask 只处理 .txt、.md 文件；docx 请先另存为纯文本")
    if not path.is_file():
        raise InputError(f"找不到文件：{path}")
    if not mapping_path.is_file():
        raise InputError(f"找不到对照表：{mapping_path}")
    mapping: Dict[str, str] = {}
    with mapping_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header or find_column(header, ("编号",)) is None:
            raise InputError("对照表第一行须为“编号,姓名”")
        c_code = find_column(header, ("编号",))
        c_name = find_column(header, ("姓名",))
        if c_name is None:
            raise InputError("对照表第一行须为“编号,姓名”")
        for row in reader:
            if len(row) > max(c_code, c_name) and row[c_code].strip():  # type: ignore[arg-type]
                mapping[row[c_code].strip()] = row[c_name].strip()  # type: ignore[index]
    text = read_text_file(path)
    restored = 0
    unknown: List[str] = []

    def repl(m: "re.Match[str]") -> str:
        nonlocal restored
        code = m.group(0)
        if code in mapping:
            restored += 1
            return mapping[code]
        if code not in unknown:
            unknown.append(code)
        return code

    new_text = CODE_RE.sub(repl, text)
    out_path = unique_path(path.with_name(f"{path.stem}-姓名版{path.suffix}"))
    out_path.write_text(new_text, encoding="utf-8")
    return {"mode": "unmask", "file": path.name, "restored": restored,
            "unknown_codes": unknown, "output_file": str(out_path)}


def render_unmask_text(report: dict) -> str:
    lines = [f"已还原 {report['restored']} 处编号，姓名版：{report['output_file']}",
             "姓名版只在本机使用，不要再发给 AI。"]
    if report["unknown_codes"]:
        lines.append("对照表中没有的编号（未还原）：" + "、".join(report["unknown_codes"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 问题记录
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    id: str
    level: str
    category: str
    message: str
    suggestion: str
    basis: str
    label: str = ""
    line: int = 0
    excerpt: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "level": self.level, "category": self.category, "label": self.label,
                "line": self.line, "excerpt": self.excerpt, "message": self.message,
                "suggestion": self.suggestion, "basis": self.basis}


def summarize(issues: Sequence[Issue], marker_text: str) -> dict:
    summary = {lv: sum(1 for i in issues if i.level == lv) for lv in LEVELS}
    summary["markers"] = {
        "待补": len(re.findall(r"【待补[：:]", marker_text)),
        "待核实": len(re.findall(r"【待核实[：:]", marker_text)),
    }
    return summary


BASELINE_EXEMPTIONS = {
    "JZ-003": "旧命中落在同分句直接否定的公布或排名动作内",
    "K12-G01": "旧命中落在同分句直接否定的公布、张贴或排名动作内",
    "JZ-008": "旧命中落在明确面向教师的受训动作内",
    "K12-G04": "旧命中落在同一连续组织角色短语或本人确定主动施助的结构内",
}


def merge_rule_issues(baseline: Sequence[Issue], added: Sequence[Issue] = (),
                      exemptions: Sequence[Issue] = ()) -> List[Issue]:
    """合并同一入口的命中。豁免须点名已登记规则的一条原始命中。"""
    if not added and not exemptions:
        return list(baseline)

    exempt = {id(item) for item in exemptions}
    if exemptions:
        eligible = {id(item) for item in baseline if item.id in BASELINE_EXEMPTIONS}
        if not exempt <= eligible:
            raise ValueError("基线豁免须指向已登记规则的一条原始命中")
    baseline = [item for item in baseline if id(item) not in exempt]

    def key(item: Issue) -> tuple:
        table_unknown = item.id == "K12-G04" and item.message == shared_names()[0].TABLE_UNKNOWN_HINT
        return item.id, item.line, table_unknown

    levels = {}
    for item in baseline:
        group = key(item)
        rank = LEVELS.index(item.level)
        levels[group] = min(rank, levels.get(group, rank))
    upgrades = {}
    for item in added:
        group = key(item)
        rank = LEVELS.index(item.level)
        if rank < levels.get(group, len(LEVELS)):
            levels[group] = rank
            upgrades[group] = item
    # 已有同级命中优先，姓名列人工核对提示独立于实名命中。
    return [item for item in baseline if key(item) not in upgrades] + list(upgrades.values())


# ---------------------------------------------------------------------------
# comments：学生评语检查
# ---------------------------------------------------------------------------

@dataclass
class Entry:
    label: str
    body: str
    line: int
    from_table: bool = False


ENTRY_LABEL_RE = re.compile(
    r"^\s*(?:[（(]?\d{1,3}[）).、．]\s*)?"
    r"(?P<label>S\d{2,4}|学生\s?\d{1,3}|\d{1,3}\s?号|[A-Z]\d{0,3}|[一-龥]{1,3}某{1,2}"
    r"|[一-龥]{2,4}|[一-龥]{1,6}·[一-龥]{1,8})"
    r"\s*(?:[：:]\s*(?P<body>.*))?$"
)
CODE_LIKE_RE = re.compile(r"S\d{2,4}|学生\s?\d{1,3}|\d{1,3}\s?号|[A-Z]\d{0,3}|[一-龥]{1,3}某{1,2}")

INSULT_RE = re.compile(r"笨|蠢|傻|弱智|脑子(?:不好|不行|慢|笨)|没出息|不可救药|无可救药|朽木|废物|垃圾|丢人|丢脸|白痴|智商(?:低|不高|不够|有问题)|懒虫|懒鬼|懒骨头")
LABEL_RE = re.compile(r"差生|后进生|学困生|问题学生|坏学生|坏孩子|捣蛋鬼|调皮鬼|害群之马|屡教不改|不求上进|懒惰|懒散成性|自私自利|品行不端"
                      r"|拖了?[^。；！？\n]{0,4}后腿|(?<!偷)懒(?![惰虫鬼骨])")
# 正当用法：劳动教育中的垃圾分类、废物利用，成语“笨鸟先飞”，以及“不笨”“一点也不懒”之类的否定说法。
# 检查贬损和标签用语前先把这些词盖住（等长替换，位置不变）。
INSULT_OK_RE = re.compile(
    r"垃圾分类|垃圾桶|垃圾箱|垃圾袋|垃圾站|垃圾房|捡垃圾|倒垃圾|清理垃圾|清扫垃圾|垃圾清运|垃圾食品|分类垃圾"
    r"|废物利用|废物回收|变废为宝|废旧|废品|笨鸟先飞|笨重|笨办法|笨功夫|不怕丢脸|不怕丢人|傻傻"
    r"|(?:不|没|从不|从来不|一点也不|一点都不|并不|毫不|再也不|既不)(?:偷)?(?:笨|懒|蠢|傻)"
)


def mask_ok_words(text: str) -> str:
    return INSULT_OK_RE.sub(lambda m: "＿" * len(m.group(0)), text)
RANK_RE = re.compile(
    r"第[一二三四五六七八九十百\d]{1,3}名|名次|排名|排行|倒数第[一二三四五六七八九十\d]{1,3}"
    r"|(?:班级|全班|年级|全年级|全校|全区|全市|全县|班里|班上)(?:第[一二三四五六七八九十\d]{1,3}|前[一二三四五六七八九十\d]{1,3}名?|倒数)"
)
COMPETITION_RE = re.compile(r"比赛|竞赛|运动会|大赛|评比|演讲|征文|跳绳|跑|跳远|跳高|游泳|球|书法|绘画|朗诵|合唱|艺术节|科技节|展演|评选|擂台|小发明")
EXAM_RE = re.compile(r"考试|期中|期末|测试|测验|检测|月考|单元|成绩|分数|总分|平均分|考了|考得|学业|语文|数学|英语|物理|化学")
SCORE_RE = re.compile(r"(?:考了|得了|拿了|总分|平均分|满分|成绩)[^。；！？\n]{0,6}\d{2,3}(?:\.\d)?\s*分|\d{2,3}(?:\.\d)?\s*分(?:的成绩|的好成绩)|进步了?\s*\d{1,3}\s*分|提高了?\s*\d{1,3}\s*分")
PROMISE_RE = re.compile(
    r"(?:一定|必定|必将|保证|肯定)(?:能|会|可以)?(?:考上|考入|升入|考进|被录取)"
    r"|(?:一定|必定|必将|保证|肯定)(?:能|会|可以)?(?:进|上)[^。；！？\n]{0,4}(?:重点|名校|好学校|好初中|好高中|好大学|示范|一中)"
    r"|(?:考上|考入|升入|考进)[^。；！？\n]{0,4}(?:重点|名校|好高中|好大学)")
THIRD_PERSON_RE = re.compile(r"该生|该同学|这名学生|此生|这位同学")
# “他”“她”与“你”同时出现：可能把学生本人写成了第三人称（也可能是指别人，报 P2 请人工确认）
HE_SHE_RE = re.compile(r"(?<![其吉])[他她](?![们人])")
# 奖项和名次：汉字、阿拉伯数字统一后与事实表比对
AWARD_RE = re.compile(r"第[一二两三四五六七八九十\d]{1,3}名|[一二三四五六特\d]等奖|金奖|银奖|铜奖|优秀奖|鼓励奖|冠军|亚军|季军")
AWARD_CLAIM_RE = re.compile(r"获[^。；！？\n]{0,8}(?:奖|名)|荣获|获评|被评为")
# 事实表中这些词不算具体表现
FACT_PLACEHOLDER_RE = re.compile(r"暂未填写|未填写|还没填|没填|暂无|待补|待填|空白|班主任|老师|该生"
                                 r"|成绩|表现|一般|良好|较好|尚可|还行|不错|优秀|中等|较差|无|略|同上")
GENERIC_PHRASES = (
    "尊敬师长", "团结同学", "热爱集体", "关心集体", "遵守纪律", "遵守校规校纪", "积极向上", "学习认真",
    "上课认真听讲", "认真听讲", "按时完成作业", "成绩优异", "品学兼优", "再接再厉", "更上一层楼",
    "继续努力", "取得更大的进步", "取得更好的成绩", "聪明伶俐", "活泼可爱", "乐于助人", "勤奋好学",
    "积极参加各项活动", "热爱劳动", "思想上进", "表现良好", "全面发展", "争取更大进步",
)
MARKER_RE = re.compile(r"【(?:待补|待核实)[：:][^】]*】")
PUNCT_RE = re.compile(r"[\s，。、；：！？“”‘’（）《》【】,.;:!?\"'()\[\]—…·－\-~～]")


def normalize(text: str) -> str:
    return PUNCT_RE.sub("", MARKER_RE.sub("", text))


def count_chars(text: str) -> int:
    """篇幅口径：含标点（与 Word 字数一致），不计空白和【待补】【待核实】标记。"""
    return len(re.sub(r"\s", "", MARKER_RE.sub("", text)))


COMMENT_ID_KEYWORDS = ("学号", "考号", "考生号", "准考证", "学籍", "学生卡号", "证件", "身份证", "手机", "电话",
                       "联系方式", "工号", "编号")
COMMENT_ID_ANNOTATION = r"[（(][^（）()\r\n]+[）)]"
COMMENT_ID_VALUE = r"[A-Za-z0-9]+(?:(?:[ \t]*[-－–_]+[ \t]*|[ \t]+)[A-Za-z0-9]+)*"
COMMENT_FILENAME_ID_RE = re.compile(r"[A-Za-z0-9]+(?:[-－–][A-Za-z0-9]+)*")
COMMENT_ID_LIST_SEPARATOR = r"[ \t]*[、,，和与/及][ \t]*"
COMMENT_ID_LABEL = "(?:" + "|".join(COMMENT_ID_KEYWORDS) + r")(?:号码|号|码)?"
COMMENT_TAGGED_ID_RE = re.compile(
    rf"(?<!〔){COMMENT_ID_LABEL}[ \t]*(?:{COMMENT_ID_ANNOTATION}[ \t]*)?[为是]?[ \t]*[：:]?[ \t]*"
    rf"(?P<values>{COMMENT_ID_VALUE}(?:{COMMENT_ID_LIST_SEPARATOR}{COMMENT_ID_VALUE})*)"
)
COMMENT_ID_SPLIT_RE = re.compile(COMMENT_ID_LIST_SEPARATOR)
COMMENT_RAW_LABEL_RE = re.compile(rf"^\s*(?P<number>{COMMENT_ID_VALUE})[ \t]*[：:]")
COMMENT_NUMBER_GAP = r"(?:[ \t]*[-－–][ \t]*|[ \t]+)?"
COMMENT_FORMATTED_ID_RE = re.compile(
    rf"(?<![A-Za-z0-9])[GLgl]?\d{{6}}{COMMENT_NUMBER_GAP}\d{{8}}{COMMENT_NUMBER_GAP}\d{{3}}[\dXx](?![A-Za-z0-9])"
)
COMMENT_MOBILE_RE = re.compile(rf"(?<!\d)1[3-9]\d{COMMENT_NUMBER_GAP}\d{{4}}{COMMENT_NUMBER_GAP}\d{{4}}(?!\d)")
COMMENT_LONG_ID_RE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]{1,2}\d{6,}[A-Za-z0-9]*|\d{6,})(?![A-Za-z0-9])")
COMMENT_LOCAL_CODE_RE = re.compile(r"S[0-9]{2,4}")
COMMENT_NUMBER_TOKEN_RE = re.compile(r"〔编号\d+〕")
COMMENT_OUTPUT_TOKEN_RE = re.compile(r"(〔(?:编号|姓名)\d+〕)")
COMMENT_TABLE_SEPARATOR_RE = re.compile(r"\|?\s*:?-{2,}:?(?:\s*\|\s*:?-{2,}:?)+\s*\|?")
COMMENT_QUANTITY_UNIT_RE = re.compile(
    r"[ \t]*(?:\.\d|分(?!组|班)|公里|公斤|小时|分钟|秒钟|平方米|"
    r"[%％元块角年月日时秒次本篇项个张名班人位米克升字下步余多题道圈遍场天周万千百"
    r"件页册份条段节课回期届首幅枚套组队瓶支斤吨倍岁点颗层户宗级])"
)
COMMENT_DATE_RE = re.compile(r"(?<!\d)\d{4}[-/]\d{1,2}[-/]\d{1,2}(?!\d)")
COMMENT_MIXED_VALUE_RE = re.compile(rf"(?<!\d)\d{{4}}/\d{{1,2}}/\d{{1,2}}(?!\d)|{COMMENT_ID_VALUE}")
COMMENT_PRIVACY_RULES = ((ID_RE, "身份证号"), (MOBILE_RE, "手机号"), (STUDENT_NO_RE, "学号等编号"))


def _comment_tables(doc: Document) -> List[List[List[str]]]:
    if doc.kind != "text":
        return doc.tables
    lines, _ = cut_at_boundary(doc.lines)
    # 普通入口沿用原表格解析。编号表也接受 Markdown 省略行首竖线的写法。
    for index, line in enumerate(lines[:-1]):
        if "|" not in line or not COMMENT_TABLE_SEPARATOR_RE.fullmatch(lines[index + 1].strip()):
            continue
        if not any(_comment_id_column(cell) for cell in line.split("|")):
            continue
        for row in range(index, len(lines)):
            text = lines[row].strip()
            if "|" not in text:
                break
            lines[row] = text if text.startswith("|") else "|" + text
    return parse_md_tables(lines)


def _comment_id_column(header: str) -> bool:
    header = re.sub(r"\s", "", header)
    return any(keyword in header for keyword in COMMENT_ID_KEYWORDS)


def _comment_mixed_id_column(header: str) -> bool:
    header = re.sub(r"\s", "", header)
    main = re.split(r"[（(]", header, maxsplit=1)[0]
    return _comment_id_column(header) and ("姓名" in header or main in ("学生", "同学"))


def _comment_label_column(header: Sequence[str]) -> Optional[int]:
    label = find_column(header, LABEL_HEADER_NAMES)
    if label is not None:
        return label
    return next((i for i, cell in enumerate(header) if _comment_id_column(cell)), None)


def _comment_tagged_values(text: str):
    for match in COMMENT_TAGGED_ID_RE.finditer(text):
        start = match.start("values")
        for separator in COMMENT_ID_SPLIT_RE.finditer(text, start, match.end("values")):
            yield start, separator.start()
            start = separator.end()
        end = match.end("values")
        if COMMENT_QUANTITY_UNIT_RE.match(text, end):
            # 并列末项可能已进入普通句子。空格分隔的尾部数量也保留。
            tail = re.search(r"(?:^|[ \t]+)\d+$", text[start:end])
            if tail:
                end = start + tail.start()
        if start < end:
            yield start, end


def _comment_mixed_values(text: str):
    for match in COMMENT_MIXED_VALUE_RE.finditer(text):
        if not (match[0].isdigit() and COMMENT_QUANTITY_UNIT_RE.match(text, match.end())):
            yield match.span()


def _comment_raw_label(text: str):
    match = COMMENT_RAW_LABEL_RE.match(text)
    if match:
        value = match["number"]
        if (len(re.sub(r"\s", "", value)) >= 4 and any(c.isdigit() for c in value)
                and not CODE_LIKE_RE.fullmatch(value) and not COMMENT_DATE_RE.fullmatch(value)):
            return match
    return None


def _comment_date(value: str) -> bool:
    if COMMENT_DATE_RE.fullmatch(value):
        return True
    if not re.fullmatch(r"(?:19|20)\d{6}", value):
        return False
    try:
        date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except ValueError:
        return False
    return True


def _comment_bare_ids(text: str):
    # 由调用方优先采用较长的跨度，避免把完整学籍号或分段号拆开。
    for regex in (COMMENT_FORMATTED_ID_RE, COMMENT_MOBILE_RE, COMMENT_LONG_ID_RE):
        for match in regex.finditer(text):
            if match[0].isdigit() and (
                _comment_date(match[0])
                or COMMENT_QUANTITY_UNIT_RE.match(text, match.end())
                or re.search(r"\d\.$", text[max(0, match.start() - 2):match.start()])
            ):
                continue
            yield match.span()


def _comment_alias(value: str) -> bool:
    return (not COMMENT_LOCAL_CODE_RE.fullmatch(value)
            and (any(c.isdigit() for c in value) or bool(re.fullmatch(r"[A-Za-z0-9]{4,}", value))))


def _comment_privacy_evidence(text: str):
    """按基线先删待补标记，再用原三条正则取证。映射回输入供净化后摘录定位。"""
    marker_spans = [m.span() for m in MARKER_RE.finditer(text)]
    body = MARKER_RE.sub("", text) if marker_spans else text

    def original(index: int) -> int:
        for start, end in marker_spans:
            if start > index:
                break
            index += end - start
        return index

    for regex, category in COMMENT_PRIVACY_RULES:
        match = regex.search(body)
        if match:
            yield category, original(match.start()), original(match.end() - 1) + 1


class CommentNumbers:
    """只在输入边界登记和替换编号，评语与事实表使用同一张编号表。"""

    def __init__(self) -> None:
        self.forms: Dict[str, str] = {}
        self.filename_parts: Dict[str, str] = {}
        self.aliases: Optional[re.Pattern] = None

    def token(self, value: str, *, structured: bool = False) -> str:
        if COMMENT_LOCAL_CODE_RE.fullmatch(value):
            return value
        token = self.forms.setdefault(value, f"〔编号{len(self.forms) + 1}〕")
        if structured and _comment_alias(value):
            for match in COMMENT_FILENAME_ID_RE.finditer(value):
                part = match[0]
                if len(part) >= 4 and any(c.isdigit() for c in part):
                    self.filename_parts.setdefault(part, token)
        return token

    def register(self, text: str) -> None:
        for start, end in _comment_tagged_values(text):
            self.token(text[start:end], structured=True)
        match = _comment_raw_label(text)
        if match:
            self.token(match["number"])

    def prepare(self) -> None:
        aliases = build_mask_regex({value: token for value, token in self.forms.items() if _comment_alias(value)})
        if aliases:
            self.aliases = re.compile(rf"(?<![A-Za-z0-9])(?:{aliases.pattern})(?![A-Za-z0-9])")

    def clean(self, text: str, *, filename: bool = False, label: bool = False, mixed: bool = False,
              privacy_hits: Optional[List[Tuple[str, int, int]]] = None) -> str:
        spans = [m.span() for m in COMMENT_OUTPUT_TOKEN_RE.finditer(text)]
        replacements = []

        def replace(start: int, end: int, token: Optional[str] = None) -> None:
            if COMMENT_LOCAL_CODE_RE.fullmatch(text, start, end):
                return
            if any(start < right and left < end for left, right in spans):
                return
            spans.append((start, end))
            replacements.append((start, end, token or self.token(text[start:end])))

        if label and text in self.forms and _comment_alias(text):
            return self.forms[text]

        if mixed:
            for start, end in _comment_mixed_values(text):
                replace(start, end)
        if not filename:
            for start, end in _comment_tagged_values(text):
                replace(start, end)
        aliases = (build_mask_regex({value: token for value, token in self.forms.items() if _comment_alias(value)})
                   if filename else self.aliases)
        candidates = [] if filename else [(start, end, None) for start, end in _comment_bare_ids(text)]
        if aliases is not None:
            dates = [] if filename else list(COMMENT_DATE_RE.finditer(text))
            for match in aliases.finditer(text):
                if not filename and match[0].isdigit() and (
                    _comment_date(match[0]) or COMMENT_QUANTITY_UNIT_RE.match(text, match.end())
                ):
                    continue
                if any(date.start() <= match.start() and match.end() <= date.end() for date in dates):
                    continue
                candidates.append((*match.span(), self.forms[match[0]]))
        if filename:
            candidates.extend((*m.span(), self.filename_parts[m[0]]) for m in COMMENT_FILENAME_ID_RE.finditer(text)
                              if m[0] in self.filename_parts)
        def priority(span: Tuple[int, int, Optional[str]]) -> tuple:
            start, end, token = span
            return start - end, start, token is None

        for start, end, token in sorted(candidates, key=priority):
            replace(start, end, token)

        parts = []
        last = 0
        replacements.sort()
        for start, end, token in replacements:
            parts.extend((text[last:start], token))
            last = end
        parts.append(text[last:])
        cleaned = "".join(parts)
        if privacy_hits is not None:
            def position(index: int, *, right: bool = False) -> int:
                delta = 0
                for start, end, token in replacements:
                    if index <= start:
                        break
                    if index < end:
                        return start + delta + (len(token) if right else 0)
                    delta += len(token) - (end - start)
                return index + delta

            for category, start, end in _comment_privacy_evidence(text):
                privacy_hits.append((category, position(start), position(end, right=True)))
        return cleaned


def _comment_register_table(numbers: CommentNumbers, tables: List[List[List[str]]]) -> None:
    for table in tables:
        if not table:
            continue
        for col, header in enumerate(table[0]):
            for row in table[1:]:
                if col >= len(row) or not row[col]:
                    continue
                if _comment_mixed_id_column(header):
                    for start, end in _comment_mixed_values(row[col]):
                        numbers.token(row[col][start:end], structured=True)
                elif _comment_id_column(header):
                    numbers.token(row[col], structured=True)
                else:
                    numbers.register(row[col])


def _comment_clean_tables(numbers: CommentNumbers, tables: List[List[List[str]]]) -> List[List[List[str]]]:
    def clean_cell(cell: str, header: str) -> str:
        if _comment_mixed_id_column(header):
            return numbers.clean(cell, mixed=True)
        if cell and _comment_id_column(header):
            return numbers.token(cell)
        return numbers.clean(cell)

    return [[table[0], *[
        [clean_cell(cell, table[0][i] if i < len(table[0]) else "") for i, cell in enumerate(row)]
        for row in table[1:]
    ]] for table in tables if table]


def _comment_table_names(tables: List[List[List[str]]], gw: Any, lex: Any) -> list:
    rows = []
    for header, *cells in tables:
        # 共享扫描器读取净化后的姓名部分，包括编号写在“姓名”之前的混合表头。
        names_header = ["姓名" if _comment_mixed_id_column(cell) else cell for cell in header]
        lines = render_md_table([names_header, *cells])
        rows.extend(gw.find_table_names([COMMENT_NUMBER_TOKEN_RE.sub(" ", line) for line in lines],
                                       lex, "k12").values())
    return rows


def _load_comment_document(path: Path) -> Document:
    try:
        return load_document(path)
    except (InputError, OSError, csv.Error) as exc:
        # 读取失败时还没有可用于遮蔽的编号表，文件名和库报错可能包含输入。
        raise InputError("无法读取评语或事实表，请核对文件路径、格式和编码") from exc


def parse_comment_entries(doc: Document, tables: List[List[List[str]]]) -> List[Entry]:
    lines, _ = cut_at_boundary(doc.lines)
    # 1. 表格：有“评语”列的优先
    for table in tables:
        if not table:
            continue
        c_comment = find_column(table[0], COMMENT_HEADER_NAMES)
        if c_comment is None:
            continue
        c_label = _comment_label_column([h if i != c_comment else "" for i, h in enumerate(table[0])])
        entries = []
        for r_index, row in enumerate(table[1:], start=1):
            body = row[c_comment] if c_comment < len(row) else ""
            label = row[c_label] if c_label is not None and c_label < len(row) else f"第{r_index}条"
            if body.strip():
                entries.append(Entry(label=label.strip() or f"第{r_index}条", body=body.strip(),
                                     line=r_index + 1, from_table=True))
        if entries:
            return entries
    # 2. 文本：“编号：评语”，或编号独占一行、评语在下一段
    entries: List[Entry] = []
    current: Optional[Entry] = None
    paragraphs: List[Tuple[int, str]] = []
    for index, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            if current is not None and current.body:
                current = None  # 一段评语结束
            continue
        if line.startswith("|") or line.startswith("#"):
            continue
        m = ENTRY_LABEL_RE.match(line)
        if m and m.group("label") not in NOT_NAMES:
            has_colon = m.group("body") is not None
            # 没有冒号、独占一行的，只认编号式标签（S01、3号、学生5、张某），避免把小标题当成学生
            if has_colon or CODE_LIKE_RE.fullmatch(m.group("label")):
                current = Entry(label=m.group("label"), body=(m.group("body") or "").strip(), line=index)
                entries.append(current)
                continue
        private = _comment_raw_label(line)
        if private:
            current = Entry(private["number"], line[private.end():].strip(), index)
            entries.append(current)
            continue
        if current is not None:
            current.body += line
        else:
            paragraphs.append((index, line))
    if entries:
        return entries
    # 3. 没有编号：每段一条
    return [Entry(label=f"第{i}条", body=text, line=ln) for i, (ln, text) in enumerate(paragraphs, start=1)]


CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CN_NUM_RE = re.compile(r"[一二两三四五六七八九十]{1,3}(?=[次本篇项个名场天周首幅件枚节课回期届张份套道人位条])")


def cn_to_int(text: str) -> Optional[int]:
    if not text:
        return None
    if "十" in text:
        left, _, right = text.partition("十")
        tens = CN_DIGITS.get(left, 1) if left else 1
        ones = CN_DIGITS.get(right, 0) if right else 0
        if (left and left not in CN_DIGITS) or (right and right not in CN_DIGITS):
            return None
        return tens * 10 + ones
    if len(text) == 1 and text in CN_DIGITS:
        return CN_DIGITS[text]
    return None


def numbers_in(text: str) -> List[str]:
    return re.findall(r"\d+(?:\.\d+)?", COMMENT_OUTPUT_TOKEN_RE.sub(" ", MARKER_RE.sub("", text)))


def fact_numbers(text: str) -> set:
    found = set(numbers_in(text))
    for m in CN_NUM_RE.finditer(text):
        value = cn_to_int(m.group(0))
        if value is not None:
            found.add(str(value))
    return found


def award_tokens(text: str) -> Dict[str, str]:
    """奖项和名次统一写法（第二名→第2名，一等奖→1等奖）到原文的映射。"""
    found: Dict[str, str] = {}
    for m in AWARD_RE.finditer(MARKER_RE.sub("", text)):
        raw = m.group(0)

        def to_digit(n: "re.Match[str]") -> str:
            value = cn_to_int(n.group(0))
            return str(value) if value is not None else n.group(0)

        key = re.sub(r"[一二两三四五六七八九十]{1,3}", to_digit, raw)
        found.setdefault(key, raw)
    return found


def fact_is_empty(text: str) -> bool:
    """事实表条目只有空白、占位词或“成绩一般”之类的笼统评价，没有具体表现。"""
    rest = normalize(COMMENT_NUMBER_TOKEN_RE.sub(" ", text))
    for phrase in GENERIC_PHRASES:
        rest = rest.replace(phrase, "")
    rest = FACT_PLACEHOLDER_RE.sub("", rest)
    return len(rest) < 3


def parse_facts(doc: Document, tables: List[List[List[str]]]) -> Dict[str, str]:
    lines, _ = cut_at_boundary(doc.lines)
    for table in tables:
        if not table:
            continue
        c_label = _comment_label_column(table[0])
        if c_label is None:
            continue
        facts: Dict[str, str] = {}
        for row in table[1:]:
            if c_label < len(row) and row[c_label].strip():
                label = re.sub(r"\s", "", row[c_label])
                others = " ".join(c for i, c in enumerate(row) if i != c_label)
                facts[label] = (facts.get(label, "") + " " + others).strip()
        if facts:
            return facts
    facts = {}
    current = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("|") or line.startswith("#"):
            continue
        m = ENTRY_LABEL_RE.match(line)
        if m and m.group("label") not in NOT_NAMES and m.group("body") is not None:
            current = m.group("label")
            facts[current] = (facts.get(current, "") + " " + m.group("body")).strip()
        elif (private := _comment_raw_label(line)):
            current = private["number"]
            facts[current] = (facts.get(current, "") + " " + line[private.end():]).strip()
        elif current:
            facts[current] += " " + line
    if not facts:
        raise InputError("事实表中没有识别到学生编号：表格请用“编号”作表头，文本请按“S01：具体表现”每行一名学生")
    return facts


def _window(text: str, start: int, end: int, before: int, after: int) -> str:
    """命中位置前后、同一句之内的文字。"""
    left = text[max(0, start - before):start]
    right = text[end:end + after]
    left = re.split(r"[。！？；!?;]", left)[-1]
    right = re.split(r"[。！？；!?;]", right)[0]
    return left + text[start:end] + right


def check_comments(path: Path, facts_path: Optional[Path] = None, stage: str = "义务教育",
                   min_chars: int = 50, max_chars: int = 300, similarity: float = 0.6,
                   person: str = "second", shared_threshold: int = 3) -> dict:
    """学生评语批量检查。表格姓名在整个报告中遮蔽，文本实名标签保留本机定位。"""
    gw, _lex = shared_names()
    doc = _load_comment_document(path)
    raw_tables = _comment_tables(doc)
    entries = parse_comment_entries(doc, raw_tables)
    if not entries:
        raise InputError("没有识别到评语。请按“S01：评语”每行一名学生，或用带“评语”列的表格")
    facts_doc = _load_comment_document(facts_path) if facts_path is not None else None
    raw_fact_tables = _comment_tables(facts_doc) if facts_doc is not None else []
    numbers = CommentNumbers()
    for source, tables in ((doc, raw_tables), (facts_doc, raw_fact_tables)):
        _comment_register_table(numbers, tables)
        if source is not None:
            for line in cut_at_boundary(source.lines)[0]:
                numbers.register(line)
    for entry in entries:
        numbers.register(entry.body)
    numbers.prepare()

    # 保留旧 PY-005 的识别证据。规则和摘录只读取净化后的内容。
    privacy_by_line: Dict[int, List[Tuple[str, int, int]]] = {}
    # 篇幅统计基于输入字符数，避免占位符长短改变原来的篇幅门槛。
    entry_chars = {entry.line: count_chars(entry.body) for entry in entries}
    comment_tables = _comment_clean_tables(numbers, raw_tables)
    table_labels = ({e.line: e.label for e in parse_comment_entries(doc, comment_tables)}
                    if entries[0].from_table else {})
    for entry in entries:
        examples: List[Tuple[str, int, int]] = []
        entry.body = numbers.clean(entry.body, privacy_hits=examples)
        if entry.from_table:
            entry.label = table_labels[entry.line]
        elif not looks_like_name(entry.label):
            entry.label = numbers.clean(entry.label, label=True)
        privacy_by_line[entry.line] = examples
    fact_tables = _comment_clean_tables(numbers, raw_fact_tables)
    facts = {}
    if facts_doc is not None:
        for label, body in parse_facts(facts_doc, fact_tables).items():
            key = numbers.clean(label, label=True)
            facts[key] = (facts.get(key, "") + " " + numbers.clean(body)).strip()
    filename = numbers.clean(path.name, filename=True)

    table = gw.NameTable()
    comment_rows = _comment_table_names(comment_tables, gw, _lex)
    table_rows = comment_rows + _comment_table_names(fact_tables, gw, _lex)
    for row in table_rows:
        table.add_hits(hit for hit in row.hits if not hit.table_only)
    for e in entries:
        label = re.sub(r"\s", "", e.label)
        if 2 <= len(label) <= 4 and not CODE_LIKE_RE.fullmatch(label) and looks_like_name(label):
            table.add(label)
        for _, name in _g04_analyze(COMMENT_NUMBER_TOKEN_RE.sub(" ", e.body))[1]:
            table.add(name)
    table.add_table_masks(table_rows)
    names = build_mask_regex(dict.fromkeys(table.names(), ""))
    protected = re.compile(COMMENT_OUTPUT_TOKEN_RE.pattern + ("|" + names.pattern if names else ""))

    def excerpt(text: str, start: int, end: int, radius: int = 10) -> str:
        left, right = max(0, start - radius), min(len(text), end + radius)
        for match in protected.finditer(text):
            if match.start() < right and match.end() > left:
                left, right = min(left, match.start()), max(right, match.end())
        return text[left:right].strip()

    compulsory = stage == "义务教育"
    issues: List[Issue] = []

    def add(entry: Entry, id_: str, level: str, category: str, message: str, suggestion: str,
            basis: str, excerpt: str = "") -> None:
        issues.append(Issue(id=id_, level=level, category=category, message=message, suggestion=suggestion,
                            basis=basis, label=entry.label, line=entry.line, excerpt=excerpt))

    marker_only = set()                     # 只写了【待补】的条目，不与事实表对账
    for e in entries:
        body = e.body
        if not body.strip():
            marker_only.add(e.label)
            add(e, "PY-012", "P1", "缺评语", "这一条只有编号，没有评语正文", "补写评语，或写【待补：该生的具体表现】",
                B_GUARDRAIL_2)
            continue
        if MARKER_RE.fullmatch(body.strip()) or (MARKER_RE.search(body) and len(normalize(body)) < 10):
            marker_only.add(e.label)
            add(e, "PY-013", "P2", "待补", "这条评语缺事实，待教师补充具体表现后再写",
                "补充该生本学期两三件具体表现", B_GUARDRAIL_2, excerpt(body, 0, 30, 0))
            continue
        body = MARKER_RE.sub("", body)  # 【待补】【待核实】标记内的说明文字不参与下面的检查
        word_body = mask_ok_words(body)
        for m in INSULT_RE.finditer(word_body):
            add(e, "PY-001", "P0", "贬损用语", f"评语出现贬损性用语“{m.group(0)}”",
                "删去，改写为具体行为和可操作的建议", B_MINOR + "（尊重未成年人人格尊严）；" + B_PROFILE_COMMENT,
                excerpt(body, m.start(), m.end()))
            break
        for m in LABEL_RE.finditer(word_body):
            add(e, "PY-002", "P1", "标签化", f"评语给学生贴标签“{m.group(0)}”",
                "改写为具体行为，如“这学期有三次值日没做完就先走了”", B_LABEL,
                excerpt(body, m.start(), m.end()))
            break
        for m in RANK_RE.finditer(body):
            ctx = _window(body, m.start(), m.end(), 15, 8)
            if COMPETITION_RE.search(ctx):
                continue
            if EXAM_RE.search(ctx):
                add(e, "PY-003", "P0" if compulsory else "P1", "考试排名",
                    "评语写了考试成绩排名" + ("；义务教育学校考试结果不排名、不公布" if compulsory else ""),
                    "删去排名，改写为学习习惯或进步的具体表现", B_EXAM if compulsory else B_LOCAL,
                    excerpt(body, m.start(), m.end()))
            else:
                add(e, "PY-003", "P2", "疑似排名", "出现名次或排名表述，请确认不是考试排名",
                    "是比赛获奖的，写明比赛名称；是考试排名的，删去", B_EXAM,
                    excerpt(body, m.start(), m.end()))
            break
        m = SCORE_RE.search(body)
        if m:
            add(e, "PY-004", "P1" if compulsory else "P2", "考试分数",
                "评语写了具体考试分数" + ("；义务教育学校考试实行等级评价" if compulsory else ""),
                "改为等级或进步的具体表现，如“计算题的错误明显减少”", B_EXAM if compulsory else B_LOCAL,
                excerpt(body, m.start(), m.end()))
        for cat, start, end in privacy_by_line[e.line]:
            add(e, "PY-005", "P0", "个人信息", f"评语中出现{cat}", "删去", B_GUARDRAIL_1, excerpt(e.body, start, end))
        for regex, cat in ((FAMILY_RE, "家庭情况"), (HEALTH_RE, "健康或特殊教育需求"), (DISCIPLINE_RE, "违纪处分")):
            m = regex.search(body)
            if m:
                add(e, "PY-006", "P0", "敏感信息", f"评语写了{cat}（“{m.group(0)}”）",
                    "评语不写家庭经济、家庭结构、健康、处分等信息，删去或改为当面沟通",
                    B_MINOR + "（保护未成年人隐私权和个人信息）；" + B_PROFILE_PRIVACY,
                    excerpt(body, m.start(), m.end()))
        m = PROMISE_RE.search(body)
        if m:
            add(e, "PY-014", "P1", "承诺升学", "评语对升学结果作出承诺或预测",
                "改为对学习方法和习惯的具体期望", B_PROMISE, excerpt(body, m.start(), m.end()))
        n_chars = entry_chars[e.line]
        if (min_chars and n_chars < min_chars) or (max_chars and n_chars > max_chars):
            add(e, "PY-009", "P2", "篇幅", f"评语 {n_chars} 字（含标点），不在 {min_chars}～{max_chars} 字之间",
                "按学校统一要求调整篇幅", B_LOCAL)
        if person == "second" and "你" not in body:
            add(e, "PY-010", "P2", "人称", "评语没有用第二人称“你”",
                "学生评语一般用第二人称，直接对学生说", B_PROFILE)
        elif person == "third" and "你" in body:
            add(e, "PY-010", "P2", "人称", "学校要求第三人称，评语中出现了“你”", "统一人称", B_LOCAL)
        if person != "third" and "你" in body:
            m = THIRD_PERSON_RE.search(body) or HE_SHE_RE.search(body)
            if m:
                add(e, "PY-010", "P2", "人称", f"同一条评语中“你”和“{m.group(0)}”混用",
                    "统一为第二人称；“他”“她”指其他同学的，不必改", B_PROFILE,
                    excerpt(body, m.start(), m.end()))
        generic_len = sum(len(p) * body.count(p) for p in GENERIC_PHRASES)
        if n_chars >= 30 and generic_len / max(n_chars, 1) >= 0.35:
            add(e, "PY-011", "P2", "套话", "套话占比高，缺少只属于这名学生的具体表现",
                "换成事实表中的具体事例：做了什么、在哪件事上、有什么变化", B_PROFILE)

    # 雷同：两两比较
    pairs = []
    normed = [normalize(re.sub(re.escape(e.label), "", e.body)) for e in entries]
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            a, b = normed[i], normed[j]
            if len(a) < 20 or len(b) < 20:
                continue
            sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
            if sm.real_quick_ratio() < similarity or sm.quick_ratio() < similarity:
                continue
            ratio = sm.ratio()
            if ratio >= similarity:
                pairs.append({"a": entries[i].label, "b": entries[j].label, "ratio": round(ratio, 2)})
                issues.append(Issue(
                    id="PY-007", level="P1", category="雷同",
                    message=f"{entries[i].label} 与 {entries[j].label} 相似度 {ratio:.2f}，读起来像同一条评语",
                    suggestion="按各自的事实重写其中一条，开头和建议都要不同", basis=B_PROFILE_COMMENT,
                    label=entries[j].label, line=entries[j].line))
    # 共用套句
    sentence_owner: Dict[str, List[str]] = {}
    sentence_excerpt: Dict[str, str] = {}
    for e in entries:
        seen = set()
        for sent in re.split(r"[。！？；!?;\n]", e.body):
            key = normalize(sent)
            if len(key) >= 8 and key not in seen:
                seen.add(key)
                sentence_owner.setdefault(key, []).append(e.label)
                if key not in sentence_excerpt:
                    sentence_excerpt[key] = sent
    threshold = max(2, shared_threshold)
    for key, owners in sentence_owner.items():
        if len(owners) >= threshold:
            issues.append(Issue(
                id="PY-008", level="P2", category="共用套句",
                message=f"同一句话出现在 {len(owners)} 条评语中：{'、'.join(owners[:8])}{'等' if len(owners) > 8 else ''}",
                suggestion="最多保留两处，其余换成各自的具体期望", basis=B_PROFILE_COMMENT,
                label=owners[0], excerpt=excerpt(sentence_excerpt[key], 0, 30, 0)))

    # 与事实表对账
    if facts_path is not None:
        labels = [re.sub(r"\s", "", e.label) for e in entries]
        for label in facts:
            if label not in labels:
                issues.append(Issue(id="PY-015", level="P1", category="对账", label=label,
                                    message=f"事实表中有 {label}，评语中没有", suggestion="补写这名学生的评语",
                                    basis=B_GUARDRAIL_2))
        for e, label in zip(entries, labels):
            if label not in facts:
                if not label.startswith("第"):
                    add(e, "PY-015", "P1", "对账", f"事实表中没有 {label}，这条评语缺少事实依据",
                        "补充事实，或改为【待补：该生的具体表现】", B_GUARDRAIL_2)
                continue
            if e.label in marker_only:
                continue
            fact = facts[label]
            if fact_is_empty(fact):
                add(e, "PY-015", "P1", "对账", f"事实表中 {label} 没有具体表现，评语缺少依据",
                    "这条只写【待补：该生本学期两三件具体表现】，等教师补充事实后再写", B_GUARDRAIL_2,
                    excerpt(fact, 0, 20, 0))
                continue
            body = MARKER_RE.sub("", e.body)
            known = fact_numbers(fact)
            missing_nums = set()
            for num in numbers_in(body):
                if num not in known:
                    missing_nums.add(num)
                    add(e, "PY-016", "P1", "对账", f"数字“{num}”在该生的事实表中找不到",
                        "删去，或请教师补进事实表", B_GUARDRAIL_2, num)
            fact_awards = award_tokens(fact)
            award_reported = False
            for key, raw in award_tokens(body).items():
                if key in fact_awards or any(n in missing_nums for n in re.findall(r"\d+", key)):
                    continue
                award_reported = True
                add(e, "PY-017", "P1", "对账", f"奖项或名次“{raw}”在该生的事实表中找不到",
                    "核对奖项名称和等级，事实表中没有的删去", B_GUARDRAIL_2, raw)
            m = AWARD_CLAIM_RE.search(body)
            if m and not award_reported and not re.search(r"奖|名|获|评|称号", fact):
                add(e, "PY-017", "P1", "对账", "评语写了获奖或评选，该生的事实表中没有获奖记录",
                    "删去，或请教师补进事实表", B_GUARDRAIL_2, excerpt(body, m.start(), m.end()))
            for q in re.findall(r"[《“]([^》”]{2,30})[》”]", body):
                if q not in fact:
                    add(e, "PY-017", "P2", "对账", f"引号或书名号中的“{q}”在该生的事实表中找不到",
                        "核对作品、奖项、活动名称，事实表中没有的删去", B_GUARDRAIL_2, q)

    def mask_input_names(value: str, *, fragment: bool = False) -> str:
        parts = COMMENT_OUTPUT_TOKEN_RE.split(value)
        mask = table.mask_fragment if fragment else table.mask
        return "".join(mask(part) if i % 2 == 0 else part for i, part in enumerate(parts))

    for it in issues:
        it.excerpt = mask_input_names(it.excerpt, fragment=True)
    marker_text = "\n".join(e.body for e in entries)
    issues.sort(key=lambda i: (LEVELS.index(i.level), i.line))
    result = {
        "mode": "comments",
        "file": mask_input_names(filename),  # 文件名里与正文已识别姓名相同的部分也遮蔽
        "stage": stage,
        "entry_count": len(entries),
        "summary": summarize(issues, marker_text),
        "entries": [{"label": e.label, "line": e.line, "chars": entry_chars[e.line]} for e in entries],
        "similar_pairs": pairs,
        "issues": [i.to_dict() for i in issues],
    }
    if table_rows:
        # 仅保护纯文本评语的实名标签及其在动态提示里的引用。
        local = {e.label for e in entries if not e.from_table}
        names = build_mask_regex(dict.fromkeys(table.names(), ""))
        pattern = re.compile(r"〔(?:编号|姓名)\d+〕" + ("|" + names.pattern if names else ""))

        def mask_label(value: str) -> str:
            return pattern.sub(lambda m: m[0] if m[0] in local or COMMENT_OUTPUT_TOKEN_RE.fullmatch(m[0])
                               else table.placeholder(m[0]), value)

        for key in ("entries", "issues", "similar_pairs"):
            for item in result[key]:
                for field in ("label", "a", "b", "message"):
                    if field in item:
                        item[field] = mask_label(item[field])
    return result


# ---------------------------------------------------------------------------
# parents：面向家长文书检查
# ---------------------------------------------------------------------------

# “个别同学”“部分同学”之类不是点名
NON_NAME_WORDS = ("个别", "部分", "有的", "有些", "一些", "少数", "多数", "全体", "各位", "广大", "其他", "其余",
                  "这位", "那位", "某位", "几名", "两名", "三名", "几位", "本班", "班上", "班里", "我班", "全班",
                  "很多", "不少", "男", "女", "男生", "女生", "新", "请", "让", "和", "的",
                  "们班", "我们班", "你们班", "他们班", "各班", "每班", "同班", "该班", "班")
NEG_RE = re.compile(
    r"不(?:得|要|再|会|需|必|准|允许|应|能|用|搞|组织|安排|布置|公布|排名|收取|收|强制|统一|推荐|讲|上|签|批改|检查|给|向)"
    r"|严禁|禁止|无需|无须|免费|免收|杜绝|避免|拒绝|勿|未|没有|不予"
)
PARENT_SUBJECT_RE = re.compile(r"家长|您|父母|监护人|爸爸|妈妈|亲子")
TEACHER_SUBJECT_END_RE = re.compile(r"(?:老师|教师|学校|班主任)[^，,]{0,4}$")
COMPETITION_SKIP_RE = re.compile(r"比赛|竞赛|运动会|大赛|评比|艺术节|科技节|合唱|演讲|征文|联赛")
# “年级第一次”“全区第一批”“七年级第一学期”之类不是名次
RANK_TAIL_OK = r"(?![一二三四五六七八九十\d次天周日个期批届课节排行年月号季轮场项条学单章阶部段组])"


@dataclass
class ParentRule:
    id: str
    level: str               # 义务教育阶段的级别
    level_other: str         # 高中、中职的级别；"skip" 表示不查
    category: str
    pattern: re.Pattern
    message: str
    suggestion: str
    basis: str
    negation: bool = True
    need_subject: bool = False          # 命中前 14 字内须出现家长、您等主语
    exclude_teacher: bool = False       # 命中前紧挨着老师、学校等主语时不报（如“老师会批改孩子的作业”）
    sentence_must: Optional[re.Pattern] = None       # 所在句须出现
    clause_must: Optional[re.Pattern] = None         # 所在分句（逗号、分号之间）须出现
    sentence_skip: Optional[re.Pattern] = None       # 所在句出现即不报
    paragraph_lacks: Optional[re.Pattern] = None     # 所在段出现即不报（如已写明依据）


PARENT_RULES: Tuple[ParentRule, ...] = (
    ParentRule("JZ-001", "P0", "P1", "家长批改作业",
               re.compile(r"(?:检查|批改|批阅|订正|改正|核对)[^。；！？\n]{0,6}(?:作业|试卷|练习|默写|听写)"),
               "要求家长检查、批改作业", "删去；作业由教师批改，家长只需关注孩子的作息和情绪",
               B_SHUANGJIAN_4, need_subject=True),
    # 面向家长的材料默认读者是家长：“检查作业……签字”“批改孩子的作业”不写主语也是对家长提要求
    ParentRule("JZ-001", "P0", "P1", "家长批改作业",
               re.compile(r"(?:检查|批改|批阅|订正|核对)[^。；！？\n]{0,10}(?:作业|试卷|练习|默写|听写)[^。；！？\n]{0,12}签(?:字|名)"),
               "要求家长检查作业并签字", "删去；作业由教师批改，家长只需关注孩子的作息和情绪",
               B_SHUANGJIAN_4, exclude_teacher=True),
    ParentRule("JZ-001", "P0", "P1", "家长批改作业",
               re.compile(r"(?:检查|批改|批阅|订正)(?:一下|好)?(?:孩子|孩子们|子女|小孩)的?[^。；！？\n]{0,4}(?:作业|试卷|练习|默写|听写)"),
               "要求家长检查、批改孩子的作业", "删去；作业由教师批改，家长只需关注孩子的作息和情绪",
               B_SHUANGJIAN_4, exclude_teacher=True),
    ParentRule("JZ-001", "P0", "P1", "家长批改作业",
               re.compile(r"(?:家长|父母|监护人)[^。；！？\n]{0,6}签(?:字|名)"),
               "要求家长在作业、试卷上签字，属于变相要求家长检查作业", "删去签字要求",
               B_SHUANGJIAN_4, sentence_must=re.compile(r"作业|试卷|练习|默写|听写|错题")),
    ParentRule("JZ-002", "P0", "P1", "给家长布置作业",
               re.compile(r"(?:家长|亲子)作业|给家长布置|家长[^。；！？\n]{0,4}完成[^。；！？\n]{0,6}(?:作业|任务单)"),
               "给家长布置作业", "删去；需要家长配合的，写成具体的生活事项，如按时作息、陪伴运动",
               B_SHUANGJIAN_4),
    ParentRule("JZ-002", "P1", "P2", "变相布置作业",
               re.compile(r"(?:拍照|拍视频|录视频|录音|视频)[^。；！？\n]{0,8}(?:上传|发到|发至|发送|打卡)"
                          r"|(?:拍照|拍视频|录视频|录音)[^。；！？\n]{0,8}发给|每日打卡|每天打卡|打卡上传"),
               "要求家长拍照、录视频上传或打卡，属于变相给家长布置作业", "删去打卡和上传要求",
               B_SHUANGJIAN_4, sentence_skip=re.compile(r"回执|请假|假条|证明|收据|发票|报名表|缴费凭证")),
    ParentRule("JZ-003", "P0", "P1", "公布成绩排名",
               re.compile(r"(?:公布|发布|晒|通报|张贴|发到家长群|发在家长群|在家长群)[^。；！？\n]{0,12}(?:成绩|分数|排名|名次)"
                          r"|(?:成绩|分数|排名|名次|成绩单)[^。；！？\n]{0,8}(?:发到|发在|发至|发进|公布在|公布到|晒到|晒在|贴在|上传到|上传至)"
                          r"[^。；！？\n]{0,3}(?:家长群|班级群|班群|微信群|QQ群|群里|群内|公告栏|宣传栏)"
                          r"|(?:成绩|分数|考试)[^。；！？\n]{0,6}(?:排名|排行|名次)"
                          r"|(?:班级|年级|全班|全年级|全区|全校|全市|全县|班里|班上)"
                          r"(?:第[一二三四五六七八九十\d]{1,3}名?|前[一二三四五六七八九十\d]{1,3}名?|倒数第?[一二三四五六七八九十\d]{1,3}名?)"
                          + RANK_TAIL_OK),
               "公布或传播考试成绩、排名", "删去；考试结果以适当方式单独告知学生和家长",
               B_EXAM, sentence_skip=COMPETITION_SKIP_RE),
    ParentRule("JZ-003", "P0", "P1", "公布成绩排名",
               re.compile(r"(?:平均分|均分|成绩|分数|考试|考得|及格率|优秀率|语文|数学|英语|物理|化学|生物|历史|地理|科学)"
                          r"[^。；！？\n]{0,6}倒数第?[一二三四五六七八九十\d]{1,3}名?" + RANK_TAIL_OK),
               "公布或传播考试成绩、排名", "删去；考试结果以适当方式单独告知学生和家长",
               B_EXAM, sentence_skip=COMPETITION_SKIP_RE),
    ParentRule("JZ-014", "P0", "P1", "公布分数",
               re.compile(r"(?:考了|只考了|才考了|考出了?|得了|拿了|总分|平均分|均分|成绩(?:为|是|达到)?)[^。；！？\n]{0,6}?"
                          r"\d{2,3}(?:\.\d{1,2})?\s*多?\s*分(?!钟)"
                          r"|(?:平均分|均分)\s*(?:为|是|达到|达|有)?\s*\d{2,3}(?:\.\d{1,2})?(?![\d%％])"),
               "面向家长的材料写出了学生或班级的考试分数", "删去分数；考试结果实行等级评价，以适当方式单独告知",
               B_EXAM + "；" + B_EXAM_2025,
               sentence_skip=re.compile(COMPETITION_SKIP_RE.pattern + r"|体质|体测|体育测试|以上为|以下为|评为|计为|等级划分")),
    ParentRule("JZ-004", "P1", "skip", "低年级书面作业",
               re.compile(r"书面作业|家庭作业|试卷|练习卷|抄写"),
               "小学一、二年级不布置家庭书面作业", "删去书面作业安排，可改为阅读、运动、劳动等非书面活动",
               B_SHUANGJIAN_5, clause_must=re.compile(r"一年级|二年级|一、二年级|一二年级|低年级|低段")),
    ParentRule("JZ-005", "P2", "P2", "作业总量",
               re.compile(r"(?:\d+|[一二三四五六七八九十两几])\s*(?:[-－~～至到]\s*\d+)?\s*(?:套|张|份)[^。；！？\n]{0,4}(?:试卷|练习卷|卷子|习题|练习)"),
               "按套、按张布置试卷练习，请核对书面作业总量和完成时长", "核对是否超过书面作业时长要求",
               B_SHUANGJIAN_5, negation=False),
    ParentRule("JZ-006", "P0", "P1", "强制收费购买",
               re.compile(r"(?:统一|集体|必须|务必|一律|全体)[^。；！？\n]{0,6}(?:购买|订购|征订|订阅|缴纳|交纳|缴费|交费|办理[^。；！？\n]{0,4}保险)"),
               "强制或变相强制收费、购买（教辅、保险、校服、报刊等）",
               "改为自愿，写明依据；教辅自愿购买，学生意外伤害保险由监护人自愿购买",
               B_JIAOFU + "；" + B_SAFETY_46, sentence_skip=re.compile(r"自愿")),
    ParentRule("JZ-007", "P1", "P1", "收费依据",
               re.compile(r"收取|缴纳|交纳|缴费|交费|收费|代收|元/人|元／人|每人\s*\d+\s*元|每生\s*\d+\s*元"),
               "涉及收费，正文没有写明收费依据", "写明依据文件名称和文号、收费标准和自愿原则；依据由用户提供",
               "收费须有政策依据，" + B_LOCAL + "（references/redlines.md 第五条）",
               paragraph_lacks=re.compile(r"根据|按照|依据|〔\d{4}〕|《[^》]*(?:通知|办法|规定|意见|标准|批复)》")),
    ParentRule("JZ-008", "P0", "P0", "推荐校外培训",
               re.compile(r"(?:推荐|介绍|组织|动员|建议)[^。；！？\n]{0,18}(?:校外培训|培训班|辅导班|补习班|补课班|培训机构)"),
               "学校或教师推荐、组织学生参加校外培训", "删去",
               B_BUKE),
    ParentRule("JZ-009", "P1", "skip", "强制课后服务",
               re.compile(r"(?:必须|一律|全体|所有学生|务必|均须|均需)[^。；！？\n]{0,8}参加[^。；！？\n]{0,6}课后服务|课后服务[^。；！？\n]{0,6}(?:强制|必须参加)"),
               "课后服务写成强制参加", "写明自愿参加、家长申请", B_SHUANGJIAN_9),
    ParentRule("JZ-010", "P0", "skip", "课后服务讲新课",
               re.compile(r"课后服务[^。！？\n]{0,15}(?:讲新课|上新课|讲授新课|新授课)"),
               "利用课后服务时间讲新课", "删去；课后服务用于作业辅导和素质拓展", B_SHUANGJIAN_10),
    ParentRule("JZ-011", "P1", "P1", "承诺升学",
               PROMISE_RE, "对升学结果作出承诺", "改为学校将采取的具体措施", B_PROMISE),
    ParentRule("JZ-011", "P1", "P1", "承诺升学",
               re.compile(r"保证[^。；！？\n]{0,6}(?:提分|升学率|升学|上线|录取)"),
               "对提分、升学率作出承诺", "改为学校将采取的具体措施", B_PROMISE),
    ParentRule("JZ-012", "P1", "P1", "点名批评",
               re.compile(r"(?P<who>[一-龥]{1,3})同学(?!们)[^。；！？\n]{0,20}(?:违纪|批评|不及格|倒数|处分|打架|抄袭|作弊|不交作业|成绩差"
                          r"|拖了?[^。；！？\n]{0,4}后腿|只考了|才考了|屡教不改)"),
               "面向家长的材料点名批评学生", "删去姓名，改为面向全体的提醒；个别问题单独与家长沟通",
               B_MINOR + "（尊重人格尊严、保护隐私）", negation=False),
    ParentRule("JZ-013", "P2", "P2", "转发点赞",
               re.compile(r"转发|点赞|投票|关注[^。；！？\n]{0,6}公众号|下载[^。；！？\n]{0,8}(?:App|APP|app|客户端|软件)"),
               "要求家长转发、点赞、投票或下载 App", "非必要的删去；确需使用的说明用途",
               B_XIETONG + "（规范家长通讯群组信息发布）", need_subject=True),
)


def _who_name(line: str, start: int, end: int, lex: Any) -> str:
    """JZ-012 点名批评里“XX同学”的 XX：复姓被截在前面时补回一个字；代称、单字、字母不登记。"""
    who = line[start:end]
    if start > 0 and line[start - 1:start + 1] in lex.compound:
        who = line[start - 1:end]
    if len(who) < 2 or "某" in who or not re.fullmatch(r"[一-龥]+", who):
        return ""
    return who


def _clause_of(text: str, start: int, end: int) -> str:
    left = re.split(r"[。！？；!?;，,]", text[:start])[-1]
    right = re.split(r"[。！？；!?;，,]", text[end:])[0]
    return left + text[start:end] + right


def _sentence_of(text: str, start: int, end: int) -> str:
    left = re.split(r"[。！？；!?;]", text[:start])[-1]
    right = re.split(r"[。！？；!?;]", text[end:])[0]
    return left + text[start:end] + right


def check_parents(path: Path, stage: str = "义务教育") -> dict:
    """面向家长文书检查。识别出的学生姓名（敏感身份锚点、JZ-012 点名批评）进全文姓名表，excerpt 统一遮蔽。"""
    gw, lex = shared_names()
    table = gw.NameTable()
    doc = load_document(path)
    if doc.kind == "table":
        lines = [" ".join(row) for table in doc.tables for row in table]
    else:
        lines, _ = cut_at_boundary(doc.lines)
    compulsory = stage == "义务教育"
    issues: List[Issue] = []
    table_rows = gw.find_table_names(lines, lex, "k12")
    seen = set()
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        names = _g04_analyze(line)[1]
        row = table_rows.get(index - 1)
        if row:
            issues.extend(_table_name_issues(row, table, index, names, gw))
        else:
            for _, name in names:
                table.add(name)
        for rule in PARENT_RULES:
            level = rule.level if compulsory else rule.level_other
            if level == "skip":
                continue
            for m in rule.pattern.finditer(line):
                sentence = _sentence_of(line, m.start(), m.end())
                before = re.split(r"[。！？；!?;，,]", line[:m.start()])[-1][-12:]
                if rule.negation and NEG_RE.search(before + m.group(0)):
                    continue
                if rule.need_subject or rule.exclude_teacher:
                    head = re.split(r"[。！？；!?;]", line[:m.start()])[-1][-14:]
                    if rule.need_subject and not PARENT_SUBJECT_RE.search(head) and not head.endswith("请"):
                        continue
                    if TEACHER_SUBJECT_END_RE.search(head):
                        continue
                if rule.sentence_must and not rule.sentence_must.search(sentence):
                    continue
                who = m.groupdict().get("who")
                if who is not None and any(who.endswith(w) for w in NON_NAME_WORDS):
                    continue
                if rule.clause_must and not rule.clause_must.search(_clause_of(line, m.start(), m.end())):
                    continue
                if rule.sentence_skip and rule.sentence_skip.search(sentence):
                    continue
                if rule.paragraph_lacks and rule.paragraph_lacks.search(line):
                    continue
                key = (rule.id, index)
                if key in seen:
                    continue
                seen.add(key)
                if who is not None:
                    given = _who_name(line, m.start("who"), m.end("who"), lex)
                    if given:
                        table.add(given)
                issues.append(Issue(id=rule.id, level=level, category=rule.category, message=rule.message,
                                    suggestion=rule.suggestion, basis=rule.basis, line=index,
                                    excerpt=excerpt_of(line, m.start(), m.end(), 12)))
                break
    issues = merge_rule_issues(issues)
    table.add_table_masks(table_rows.values())
    for it in issues:
        it.excerpt = mask_names(table, it.excerpt)
    issues.sort(key=lambda i: (LEVELS.index(i.level), i.line))
    return table.mask_output({
        "mode": "parents",
        "file": table.mask(path.name),  # 文件名里与正文已识别姓名相同的部分也遮蔽
        "stage": stage,
        "summary": summarize(issues, "\n".join(lines)),
        "issues": [i.to_dict() for i in issues],
    })


G04_RULE = (
    "K12-G04", "P0", "P0", "学生隐私",
    None,  # 由 _g04_analyze 按“锚点 + 候选姓名 + 打分”判定
    "校内计划总结或自评材料中疑似外露学生家庭、健康或处分等敏感隐私",
    "删去具体学生姓名与敏感背景关联，确需说明整体情况的改用汇总人数",
    "《未成年人保护法》第四条；gongwen-k12 references/redlines.md 第一条",
)

GENERAL_RULES = (
    (
        "K12-G01", "P0", "P1", "考试排名",
        re.compile(r"(?:公布|张贴|通报|公示)[^。；，,\n]{0,8}?(?:考试成绩|成绩排名|名次|分数)|按(?:考试)?成绩(?:分班|排座|排名)"),
        "义务教育阶段不得公布学生考试成绩或按成绩排名、分班",
        "改为陈述整体教学改进措施与学习习惯变化，删去分数与排名表述",
        "教基厅函〔2021〕34号；gongwen-k12 references/redlines.md 第二条",
    ),
    (
        "K12-G02", "P0", "P0", "记录真实",
        re.compile(r"(?:补造|倒签|补写|突击补齐)[^。；，,\n]{0,8}?(?:台账|记录|教研记录|安全记录|家访记录|听课记录)"),
        "疑似存在补造或倒签迎检台账/活动记录的表述",
        "严禁补造未开展活动的记录或倒签日期，按实际开展情况如实登记",
        "gongwen-k12 references/redlines.md 第八条；guardrails 第六条",
    ),
    (
        "K12-G03", "P0", "P1", "课后服务",
        re.compile(r"课后服务[^。；，,\n]{0,12}?(?:讲授新课|统一讲新课|必须全部参加|强制参加|一律参加)"),
        "课后服务不得讲授新课，也不得强制或变相强制学生参加",
        "写明自愿报名原则，课后服务用于作业辅导、阅读、体育、艺术等素质拓展活动",
        "中办发〔2021〕40号；gongwen-k12 references/redlines.md 第六条",
    ),
    G04_RULE,
)


# ---------------------------------------------------------------------------
# K12 学生隐私识别（K12-G04）：敏感身份锚点 + 共享模块 gw_names 的候选与打分
# ---------------------------------------------------------------------------

# 敏感身份词。“低保”后接金、政策、标准等是政策用语，不是指人
K12_SENS = (r"(?:受(?:到|过)[^，。；]{0,4}处分的?(?=学生|同学|儿童|子女|[一-龥]{2,3}同学)|低保户|低保家庭|低保(?!金|政策|标准|对象|资金|工作)|建档立卡户?|特困(?:供养)?|困难家庭|家庭经济困难"
            r"|单亲家庭|离异家庭|留守儿童|孤儿|抑郁症|多动症|自闭症|违纪处分|受过处分)")
# 前锚点分两档：身份词 + 角色名词（学生、同学、子女、儿童、家庭学生）4 分；身份词后直接接姓名 3 分
# （后者不含逗号分隔，防“家庭经济困难，母亲长期无业”被当成身份词 + 姓名）
K12_ROLE = K12_SENS + r"(?:的)?(?:学生|同学|子女|儿童|家庭学生)[：:，,\s]{0,2}"
K12_BARE = K12_SENS + r"(?:的)?[：:\s]{0,2}"
# 名单锚点：“敏感身份……名单：”“敏感身份……3名：”之后的冒号名单，按“、”“，”逐项判姓名
K12_LIST = K12_SENS + r"[^。；;：:\n]{0,12}?(?:名单(?:如下|为)?|\d+\s*[名人位])\s*[：:]\s*"
# 后锚点：“同学”前面的姓名（“同学们”不算），分数低一档，须与敏感身份词同在一个分句才报
K12_POST = r"(?=同学(?!们))"
K12_SENS_RE = re.compile(K12_SENS)
_K12_CLAUSE_SEP_RE = re.compile(r"[。！？；!?;，,、：:\n]")
_K12_SENT_END_RE = re.compile(r"[。！？；!?;]")
# “张某”“王某某”“某同学”“A同学”这类代称：敏感身份词后面 10 字内出现即报 P0（沿用旧口径）
_K12_PSEUDO_CACHE: Dict[str, "re.Pattern[str]"] = {}
_K12_ANCHOR_CACHE: Dict[str, list] = {}


def _k12_pseudo_re(lex: Any) -> "re.Pattern[str]":
    cached = _K12_PSEUDO_CACHE.get("re")
    if cached is None:
        chars = "".join(sorted(lex.surnames))
        cached = re.compile(K12_SENS + r"[^。；，,\n]{0,10}?(?:某同学|[A-Za-z]同学|[" + re.escape(chars) + r"]某{1,2})")
        _K12_PSEUDO_CACHE["re"] = cached
    return cached


def _k12_anchors(gw: Any) -> Tuple[list, list]:
    cached = _K12_ANCHOR_CACHE.get("a")
    if cached is None:
        try:
            front = gw.compile_anchors({"prefix": [{"re": K12_ROLE, "strength": 4}, {"re": K12_BARE, "strength": 3}],
                                        "list": [{"re": K12_LIST, "strength": 3}]})
            post = gw.compile_anchors({"postfix": [{"re": K12_POST, "strength": 2}]})
        except gw.LexiconError as exc:
            raise InputError(str(exc)) from exc
        cached = [front, post]
        _K12_ANCHOR_CACHE["a"] = cached
    return cached[0], cached[1]


def _clause_bounds(line: str, pos: int) -> Tuple[int, int]:
    """pos 所在分句（按。！？；，、：切）的起止。"""
    left = 0
    for m in _K12_CLAUSE_SEP_RE.finditer(line, 0, pos):
        left = m.end()
    m = _K12_CLAUSE_SEP_RE.search(line, pos)
    return left, (m.start() if m else len(line))


def _g04_analyze(line: str) -> Tuple[List[dict], List[Tuple[int, str]]]:
    """K12-G04 单行识别。返回 (候选问题, 要登记进全文姓名表的姓名)。

    候选问题字段：start、end（摘录起止，含锚点）、score（代称记 9）、pseudo。
    姓名表登记：前锚点、名单识别出的真名，以及与敏感身份词同分句的“XX同学”；即使因前置否定词不报，也登记。"""
    gw, lex = shared_names()
    front, post = _k12_anchors(gw)
    cands: List[dict] = []
    names: List[Tuple[int, str]] = []

    front_hits = gw.find_names(line, front, lex)
    spans: Dict[int, int] = {}
    for h in front_hits:
        if not h.pseudo:
            spans[h.anchor_start] = max(spans.get(h.anchor_start, 0), h.end)
    for h in front_hits:
        if h.pseudo:
            cands.append({"start": h.anchor_start, "end": h.end, "score": 9, "pseudo": True})
            continue
        names.append((h.start, h.name))
        if h.table_only:    # 并列后项：只进姓名表（遮蔽用），摘录由首个姓名的 spans 一并延伸到它
            continue
        cands.append({"start": h.anchor_start, "end": spans[h.anchor_start], "score": h.score, "pseudo": False})

    for h in gw.find_names(line, post, lex):
        lo, hi = _clause_bounds(line, h.start)
        sens = K12_SENS_RE.search(line, lo, hi)
        if sens is None:
            continue
        end = min(h.end + 2, len(line))
        if h.pseudo:
            cands.append({"start": min(sens.start(), h.start), "end": max(sens.end(), end), "score": 9, "pseudo": True})
            continue
        names.append((h.start, h.name))
        cands.append({"start": min(sens.start(), h.start), "end": max(sens.end(), end), "score": h.score,
                      "pseudo": False})

    for m in _k12_pseudo_re(lex).finditer(line):
        cands.append({"start": m.start(), "end": m.end(), "score": 9, "pseudo": True})
    return cands, names


def _g04_pick(line: str, cands: Sequence[dict], rule_level: str) -> Optional[Tuple[str, str]]:
    """去掉前置否定的候选后，按级别取最重、位置最前的一条，返回 (级别, 未遮蔽的摘录)。"""
    best: Optional[Tuple[int, int, str, dict]] = None
    for c in cands:
        if not c["pseudo"] and c["score"] < 5:
            continue
        before = re.split(r"[。！？；!?;，,]", line[:c["start"]])[-1][-12:]
        if NEG_RE.search(before + line[c["start"]:c["end"]]):
            continue
        level = rule_level if (c["pseudo"] or c["score"] >= 6) else "P1"
        key = (LEVELS.index(level), c["start"])
        if best is None or key < (best[0], best[1]):
            best = (key[0], key[1], level, c)
    if best is None:
        return None
    c = best[3]
    tail = line[c["end"]:c["end"] + 8]
    m = _K12_SENT_END_RE.search(tail)
    if m:
        tail = tail[:m.end()]
    return best[2], mask_digits((line[c["start"]:c["end"]] + tail).strip())


def _table_name_issues(row: Any, table: Any, line: int, prose_names: Sequence[Tuple[int, str]], gw: Any) -> List[Issue]:
    rid, _lv_c, _lv_o, category, _pattern, _message, suggest, basis = G04_RULE
    positions = list(prose_names) + [(hit.start, hit.name) for hit in row.hits if not hit.table_only]
    for _, name in sorted(positions):
        table.add(name)
    issues = []
    reported = [hit for hit in row.hits if not hit.table_only]
    if reported:
        level = "P0" if max(hit.score for hit in reported) >= gw.SCORE_HIGH else "P1"
        shown = sorted([*prose_names, *((h.start, h.name) for h in reported)])
        excerpt = "、".join(dict.fromkeys(table.placeholder(name) for _, name in shown))
        issues.append(Issue(id=rid, level=level, category=category, message="表格姓名列出现真实姓名",
                            suggestion=suggest, basis=basis, line=line, excerpt=excerpt))
    if row.unrecognized:
        issues.append(Issue(id=rid, level="P1", category=category, message=gw.TABLE_UNKNOWN_HINT,
                            suggestion=suggest, basis=basis, line=line, excerpt=""))
    return issues


def check_general(path: Path, stage: str = "义务教育") -> dict:
    """校内综合文书检查（学期计划总结、督导自评、课后服务方案、安全教育/教研记录）。

    K12-G04 由 _g04_analyze 识别学生实名（锚点 + 打分）；识别出的姓名进全文姓名表，所有 excerpt 在输出前统一遮蔽。"""
    gw, lex = shared_names()
    doc = load_document(path)
    if doc.kind == "table":
        lines = [" ".join(row) for table in doc.tables for row in table]
    else:
        lines, _ = cut_at_boundary(doc.lines)
    compulsory = stage == "义务教育"
    issues: List[Issue] = []
    table = gw.NameTable()
    table_rows = gw.find_table_names(lines, lex, "k12")
    seen = set()
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        for rid, lv_c, lv_o, cat, pat, msg, sug, basis in GENERAL_RULES:
            level = lv_c if compulsory else lv_o
            if pat is None:  # K12-G04：锚点 + 候选姓名 + 打分
                cands, names = _g04_analyze(line)
                row = table_rows.get(index - 1)
                picked = _g04_pick(line, cands, level)
                if row:
                    table_issues = _table_name_issues(row, table, index, names, gw)
                    has_name = any(not hit.table_only for hit in row.hits)
                    if has_name and picked is not None and LEVELS.index(picked[0]) < LEVELS.index(table_issues[0].level):
                        table_issues[0].level = picked[0]
                    issues.extend(table_issues)
                    if has_name:
                        continue
                for _, name in names:
                    table.add(name)
                if picked is not None and (rid, index) not in seen:
                    seen.add((rid, index))
                    issues.append(Issue(id=rid, level=picked[0], category=cat, message=msg,
                                        suggestion=sug, basis=basis, line=index, excerpt=picked[1]))
                continue
            for m in pat.finditer(line):
                before = re.split(r"[。！？；!?;，,]", line[:m.start()])[-1][-12:]
                if NEG_RE.search(before + m.group(0)):
                    continue
                key = (rid, index)
                if key in seen:
                    continue
                seen.add(key)
                issues.append(Issue(id=rid, level=level, category=cat, message=msg,
                                    suggestion=sug, basis=basis, line=index,
                                    excerpt=excerpt_of(line, m.start(), m.end(), 12)))
                break
    issues = merge_rule_issues(issues)
    table.add_table_masks(table_rows.values())
    for it in issues:  # 全文姓名表定稿后再统一遮蔽，保证后文单独出现的姓名也被遮住
        it.excerpt = mask_names(table, it.excerpt)
    issues.sort(key=lambda i: (LEVELS.index(i.level), i.line))
    return table.mask_output({
        "mode": "general",
        "file": table.mask(path.name),  # 文件名里与正文已识别姓名相同的部分也遮蔽
        "stage": stage,
        "summary": summarize(issues, "\n".join(lines)),
        "issues": [i.to_dict() for i in issues],
    })


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

COMMENT_RULES = (
    ("PY-001", ("P0",), "评语用语贬损学生"),
    ("PY-002", ("P1",), "评语用标签代替对具体行为的描述"),
    ("PY-003", ("P0", "P1", "P2"), "评语写出考试排名或疑似考试名次"),
    ("PY-004", ("P1", "P2"), "评语写出考试分数"),
    ("PY-005", ("P0",), "评语含身份证号、手机号或学号"),
    ("PY-006", ("P0",), "评语提及家庭、健康或处分敏感信息"),
    ("PY-007", ("P1",), "两条评语相似度达到指定阈值"),
    ("PY-008", ("P2",), "同一句套话在多条评语中出现"),
    ("PY-009", ("P2",), "评语篇幅超出指定字数范围"),
    ("PY-010", ("P2",), "评语人称不合要求或混用人称"),
    ("PY-011", ("P2",), "评语套话占比过高"),
    ("PY-012", ("P1",), "只有标签，缺评语正文"),
    ("PY-013", ("P2",), "评语只有或主要是待补、待核实占位"),
    ("PY-014", ("P1",), "评语承诺或预测升学结果"),
    ("PY-015", ("P1",), "对账时标签不对应，或事实表无具体表现"),
    ("PY-016", ("P1",), "评语数字在事实表中找不到"),
    ("PY-017", ("P1", "P2"), "评语奖项、名次或引号内名称在事实表中找不到"),
)
COMMENT_STAGE_LEVELS = {
    "PY-003": (("P0", "P2"), ("P1", "P2"), ("P1", "P2")),
    "PY-004": (("P1",), ("P2",), ("P2",)),
}


def rule_catalog() -> dict:
    order = (*LEVELS, "skip")
    rules: Dict[str, dict] = {}

    def add(rid: str, command: str, stage_levels: Sequence[Sequence[str]], condition: str) -> None:
        rule = rules.setdefault(rid, {"id": rid, "commands": [], "levels": set(), "stage_levels": {}, "condition": []})
        if command not in rule["commands"]:
            rule["commands"].append(command)
        stages = rule["stage_levels"].setdefault(command, {})
        for stage, levels in zip(STAGES, stage_levels):
            stages.setdefault(stage, set()).update(levels)
            rule["levels"].update(levels)
        if condition not in rule["condition"]:
            rule["condition"].append(condition)

    for rid, levels, condition in COMMENT_RULES:
        add(rid, "comments", COMMENT_STAGE_LEVELS.get(rid, (levels,) * len(STAGES)), condition)
    for rule in PARENT_RULES:
        add(rule.id, "parents", ((rule.level,), (rule.level_other,), (rule.level_other,)), rule.message)
    for rid, lv_c, lv_o, _cat, pattern, message, _suggestion, _basis in GENERAL_RULES:
        if pattern is None:  # G04 的低置信度候选和未识别表格值都可能给 P1
            add(rid, "general", ((lv_c, "P1"), (lv_o, "P1"), (lv_o, "P1")), message)
        else:
            add(rid, "general", ((lv_c,), (lv_o,), (lv_o,)), message)
    for command in ("parents", "general"):
        add(G04_RULE[0], command, (("P0", "P1"),) * len(STAGES),
            "表格姓名列含实名或需要人工核对的值")
    for rule in rules.values():
        rule["levels"] = sorted(rule["levels"], key=order.index)
        rule["condition"] = "；".join(rule["condition"])
        for stages in rule["stage_levels"].values():
            for stage, levels in stages.items():
                stages[stage] = sorted(levels, key=order.index)
    return {"rules": [rules[rid] for rid in sorted(rules)]}


def render_rule_catalog(catalog: dict) -> str:
    lines = [f"中小学专检规则（{len(catalog['rules'])} 条，skip 表示该学段跳过）"]
    for rule in catalog["rules"]:
        stages = []
        for command, levels in rule["stage_levels"].items():
            stages.append(command + " " + " ".join(f"{stage}={'/'.join(levels[stage])}" for stage in STAGES))
        lines.append(f"{rule['id']} | {', '.join(rule['commands'])} | {'/'.join(rule['levels'])} | "
                     + "；".join(stages) + " | " + rule["condition"])
    return "\n".join(lines)


def render_check_text(report: dict) -> str:
    s = report["summary"]
    titles = {"comments": "学生评语检查", "parents": "面向家长文书检查", "general": "校内综合文书检查"}
    title = titles.get(report["mode"], "中小学文书检查")
    head = f"{title}：{report['file']}（学段：{report['stage']}"
    if report["mode"] == "comments":
        head += f"，共 {report['entry_count']} 条"
    head += "）"
    lines = [head, f"P0 {s['P0']} 条，P1 {s['P1']} 条，P2 {s['P2']} 条；"
                   f"待补 {s['markers']['待补']} 处，待核实 {s['markers']['待核实']} 处"]
    for item in report["issues"]:
        where = item["label"] or f"第 {item['line']} 行"
        if item["label"] and item["line"]:
            where += f"（第 {item['line']} 行）"
        text = f"[{item['level']}] {item['id']} {where} {item['category']}：{item['message']}"
        if item["excerpt"]:
            text += f"。原文：“{item['excerpt']}”"
        text += f"。建议：{item['suggestion']}。依据：{item['basis']}"
        lines.append(text)
    if not report["issues"]:
        if report["mode"] == "comments":
            lines.append("未发现问题。机检只覆盖能写成规则的项目，评语是否因人而异、事实是否准确，仍需人工通读。")
        else:
            lines.append("未发现问题。机检只覆盖能写成规则的项目，时间、收费标准、政策依据是否与通知原文一致，仍需人工核对。")
    return "\n".join(lines)


def _setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


class _ChineseHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        return super().add_usage(usage, actions, groups, "用法：" if prefix is None else prefix)


def _ratio(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("须为 0 到 1 之间的小数") from exc
    if not 0 < number <= 1:
        raise argparse.ArgumentTypeError("须为 0 到 1 之间的小数")
    return number


def _sub(subparsers, name: str, help_text: str) -> argparse.ArgumentParser:
    p = subparsers.add_parser(name, help=help_text, description=help_text,
                              formatter_class=_ChineseHelpFormatter, add_help=False)
    p._optionals.title = "选项"
    p._positionals.title = "参数"
    p.add_argument("-h", "--help", action="help", help="显示本帮助信息并退出")
    return p


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="k12_check.py",
        description="中小学行业包的本地脱敏与检查工具：学生事实表脱敏和还原、学生评语检查、面向家长文书检查、校内综合文书检查。",
        epilog="退出码：0 正常；1 使用 --strict 且存在 P0；2 输入错误或缺少共享模块。",
        formatter_class=_ChineseHelpFormatter, add_help=False,
    )
    parser._optionals.title = "选项"
    parser._positionals.title = "参数"
    parser.add_argument("-h", "--help", action="help", help="显示本帮助信息并退出")
    parser.add_argument("--version", action="version", version=f"k12_check.py {VERSION}", help="显示版本号")
    parser.add_argument("--list-rules", action="store_true", help="列出专检规则与学段级别")
    parser.add_argument("--json", dest="list_json", action="store_true", help="配合 --list-rules 输出 JSON")
    sub = parser.add_subparsers(dest="command", title="子命令", metavar="子命令")

    p = _sub(sub, "mask", "学生名单或事实表本地脱敏：姓名换成 S01 等编号，另存脱敏稿和对照表")
    p.add_argument("file", help="学生事实表（.txt、.md、.csv、.docx、.xlsx）")
    p.add_argument("--name-col", help="姓名所在列的表头，默认自动识别“姓名”“学生姓名”“学生”")
    p.add_argument("--drop-sensitive", action="store_true",
                   help="涉及家庭、健康、处分信息的整句换成“【已略去：……信息】”（写评语和家长材料时建议加上）")
    p.add_argument("--json", action="store_true", help="以 JSON 格式输出")

    p = _sub(sub, "unmask", "把评语中的编号换回姓名，另存姓名版")
    p.add_argument("file", help="带编号的评语文件（.txt、.md）")
    p.add_argument("mapping", help="mask 生成的对照表（.csv）")
    p.add_argument("--json", action="store_true", help="以 JSON 格式输出")

    p = _sub(sub, "comments", "学生评语批量检查")
    p.add_argument("file", help="评语文件（.txt、.md、.csv、.docx、.xlsx）")
    p.add_argument("--facts", help="脱敏后的学生事实表，用于对账")
    p.add_argument("--stage", choices=STAGES, default="义务教育", help="学段，默认义务教育")
    p.add_argument("--min-chars", type=int, default=50, help="每条评语最少字数（含标点），默认 50，0 表示不查")
    p.add_argument("--max-chars", type=int, default=300, help="每条评语最多字数（含标点），默认 300，0 表示不查")
    p.add_argument("--similarity", type=_ratio, default=0.6, help="两条评语相似度达到该值即报雷同，默认 0.6")
    p.add_argument("--person", choices=("second", "third", "any"), default="second",
                   help="人称要求：second 第二人称（默认）、third 第三人称、any 不查")
    p.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    p.add_argument("--strict", action="store_true", help="存在 P0 时返回 1")

    p = _sub(sub, "parents", "面向家长文书检查（致家长的一封信、家长会讲话稿、给家长的通知）")
    p.add_argument("file", help="文稿（.txt、.md、.docx）")
    p.add_argument("--stage", choices=STAGES, default="义务教育", help="学段，默认义务教育")
    p.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    p.add_argument("--strict", action="store_true", help="存在 P0 时返回 1")

    p = _sub(sub, "general", "校内综合文书检查（学期计划总结、督导自评、课后服务方案、安全/教研记录）")
    p.add_argument("file", help="文稿（.txt、.md、.docx）")
    p.add_argument("--stage", choices=STAGES, default="义务教育", help="学段，默认义务教育")
    p.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    p.add_argument("--strict", action="store_true", help="存在 P0 时返回 1")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    _setup_console()
    parser = make_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    if args.list_rules and not args.command:
        report = rule_catalog()
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.list_json else render_rule_catalog(report))
        return 0
    if args.list_rules or args.list_json:
        print("错误：顶层 --list-rules [--json] 须单独运行", file=sys.stderr)
        return 2
    if not args.command:
        parser.print_help()
        return 2
    try:
        shared_names()  # 缺共享模块或数据损坏：所有子命令（含 mask、unmask）统一退出码 2，不静默降级
        if args.command == "mask":
            report = mask_document(Path(args.file), args.name_col, args.drop_sensitive)
            text = render_mask_text(report)
        elif args.command == "unmask":
            report = unmask_document(Path(args.file), Path(args.mapping))
            text = render_unmask_text(report)
        elif args.command == "comments":
            report = check_comments(Path(args.file), Path(args.facts) if args.facts else None, args.stage,
                                    args.min_chars, args.max_chars, args.similarity, args.person)
            text = render_check_text(report)
        elif args.command == "general":
            report = check_general(Path(args.file), args.stage)
            text = render_check_text(report)
        else:
            report = check_parents(Path(args.file), args.stage)
            text = render_check_text(report)
    except InputError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else text)
    if getattr(args, "strict", False) and report.get("summary", {}).get("P0", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
