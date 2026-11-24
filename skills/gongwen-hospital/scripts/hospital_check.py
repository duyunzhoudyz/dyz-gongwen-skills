#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""医院专用文书的行业机检（gongwen-hospital）。

在通用机检 gongwen_lint.py 之外，补查医院行业中能写成规则的问题：
  - 疗效保证、治愈率百分之百、最高级和领先表述（HOS-001～003，对外材料升级）；
  - 决策程序：党政联席会议代替党委会议（HOS-004），议题涉及“三重一大”却没有党委会议程序（HOS-005）；
  - 指数写法：CMI 等指数和天数用“百分点”（HOS-006），CMI 带百分号（HOS-007）；
  - 指标名称不规范（HOS-008～015）；
  - 引用已废止的依据（HOS-016、017）；
  - 根因分析把原因落在个人品质、把直接原因当根本原因、写入处理处罚（HOS-018～020）；
  - 患者隐私、当事人信息、编码与医保、程序倒置与追认、廉洁表述、评审结论、对外敏感事项（HOS-030～039）。
    全部规则共 39 条（37 条规则 + 2 条程序性规则）。

隐私识别（HOS-030～032）：不再靠“姓氏字 + 后续字”的裸正则，而是“锚点 + 候选 + 打分”。
  锚点是能带出姓名的上下文（“患者”“12床”“当班护士”“投诉人”，或姓名后面的“（住院号……）”）；
  在锚点旁取 2～4 字的候选，总分 = 锚点分 + 边界分 + 形态分。总分 >= 6 为高置信，按规则级别报 P0；
  总分 == 5 为低置信，报 P1；< 5 不报，也不进姓名表。识别逻辑、姓氏与排除词数据在共享模块
  gw_names.py、gw_names.json（唯一事实源在仓库 shared/scripts/，各 skill 里的副本用 tools/sync_shared.py 同步，勿手改）。
  缺少共享模块或数据损坏时直接报错退出（退出码 2），不做静默降级：“查不了”不能显示成“未检出”。
  “张某”这类代称不进姓名表；“张某 + 床号”的组合红线仍由 HOS-030 的 pattern 判断。

遮蔽：全文所有已识别姓名（含因豁免没报出的）按首次出现顺序编号，写成〔姓名1〕〔姓名2〕；
  所有规则（包括程序性规则）的 excerpt、context、回显的文件名，以及文本输出和 JSON 输出，统一经 NameTable.mask 替换，
  同一个姓名在全文任何一行出现都以同一个编号显示。隐私规则自己的 excerpt 是“锚点 + 占位符 + 右侧最多 8 字”，
  不再整段替换；5 位以上的连续数字（住院号等）显示为×××。
  (id, 行号, excerpt, message) 完全相同的命中合并成一条，加 count 字段。

豁免统一调用共享模块 gw_clause.py，按命中位置算出七个窗口：
  clause（命中所在分句，按逗号、顿号、冒号及句末标点切分）、chain（命中分句向前并入顿号连着的并列分句，禁止、否定类用）、
  prev（紧邻的前一分句）、lead（命中分句紧接冒号时，冒号前的引导分句）、
  prefix（命中前同一分句内 prefix_window 个字，默认 8）、chain_prefix（同上，可跨顿号）、sentence（整句）。
  规则 JSON 的 exempt_context（整句）、exempt_clause（分句）、exempt_chain（顿号并列的分句串）、
  exempt_prev_clause（分句或前一分句）、exempt_lead、prefix_negation 各对应一个窗口；
  exempt_dispose（只看命中所在分句）是处置类的自带词，与 exempt_categories 里的 dispose 一样，程序倒置规则在就近有如实声明时不适用；
  【收缩】命中之后的分句不再能豁免（取消 after 窗口）：处置类只在命中所在分句内生效，出处类在命中所在分句与紧邻的前一分句内生效；
  否决、整改、出处写在后一分句的句子会重新被报出（已知代价）：后续分句里若有针对该做法的处置、出处词（后续词同样要过让步、例外、定语、“避免违规”这类目的成分、指他、“此前”这类过去、出处未出具的语境检查，只看规则实际配置的类别），P0 降为 P1 仍报出，suggestion 末尾补“若后文已写明否决、整改或出处，可忽略本条”；处置词在同一分句里时必须针对被命中的做法：在命中之后要紧接（间隔不超过 14 字、没有“并、且、同时、还”等并列词、之后不再带无关宾语），在命中之前要是“否决了……的建议”这样的指称结构，拿不准不豁免；“经自我评价、院内评审、本院认定、初步评价”不算出处；
  exempt_categories 直接引用 gw_clause 的豁免词类别（prohibit 禁止、negation 否定事实、investigate 调查引述、
  dispose 处置定性、source 出处、target 目标、title 称号），各类别的生效窗口由共享模块统一规定。
  程序性规则的 satisfied_negation 看命中前同一分句内的 8 个字；satisfied_scope 为 adjacent 时只在触发句和相邻句里找。

程序倒置（HOS-034）：除正则外，规则文件顶层的 procedure_inversion 启用 gw_clause.find_inversions 的组合判定——
  【收缩】组合判定的命中一律为 P1（提示性质），P0 只来自本规则对“先行开工、先行采购、补办手续、先……后报批”等明确写法的正则命中；
  单独的“追认”写法由 HOS-035 报 P1。
  message 按原因（find_inversions 的 reason_code）给：same_sentence 同句既有已执行又有提请、declared 如实声明、other_item 提请事项可能是另一事项
  （二期、续签、新购、创建；“已建成的”这类定语不算已执行）、adjacent 已执行与提请在相邻两句、weak_exec 只有“于X月开工”没有“已”字、
  normalize 出现追认补办字样；提请对象是验收、结算、备案、收费标准、管理办法、计划、预算等事后正常事项且没有追认、补办的不报。
  如实声明降级只作用于正则命中的 P0：同一句或紧邻的前、后一句有未被否定的肯定式声明（“属于程序倒置”“以上程序倒置情况”“该做法违反了…规定”
  “未经…审议程序”），且这三句里没有追认、补办，才降 P1；“不属于、不存在、未发生、杜绝、防止、自查”等否定写法和单独的“如实报告、如实说明”不算声明。
  声明只认“对本事项的直接断言”：主语是“该、本、此、上述、以上 + 项目、事项、做法、情况”或承前省略，声明所在分句以断言收束；疑问（是否）、条件（如、若）、转述（有人认为、……的说法）、指他（其他单位）、“难以认定、谈不上、算不上、未必、所谓、质疑”等写法不算；追认、补办的检查范围是声明所在句及其后两句、倒置句及其前后一句；拿不准不降级（保持 P0）。
  不再有全文级降级。命中处就近有声明时，“已整改”“违反”等处置类豁免不适用，改按声明降 P1。
  与同一行已有的正则命中合并成一条（保留正则那条的级别与摘录）。声明判断统一调用 gw_clause.Declaration。

用法：
    python scripts/hospital_check.py <文件> [--type 文书] [--external] [--json] [--strict]
    python scripts/hospital_check.py --list-rules

输入 .txt、.md、.docx（docx 需要 python-docx），遇到单独成行的【起草说明】即停止读取。
输出字段与 gongwen_lint.py 一致（file、doc_type、char_count、summary、issues），summary 同样含 markers
（【待补】【待核实】计数，开发规范第 8 节），可以并入核稿意见。
退出码：0 正常；--strict 且存在 P0 时为 1；输入错误（含共享模块缺失）为 2。
只依赖标准库；规则在同目录的 hospital_rules.json 中，修改规则不必改代码。

已知局限（隐私识别是启发式检查，定稿前仍须人工通读）：
  1. 没有锚点就识别不了：单独一句“据张丽丽回忆”“张丽丽当晚独自值守”、没有表头锚点的表格姓名列；
     只有同一姓名在别处被锚点识别过，才靠全文姓名表遮蔽。
  2. 右边界不再一票否决：标点、身份括注、时间词、亲属或所属词、功能字都算证据；右侧是词表外的普通汉字时，
     三字名看名字用字是否在常见名用字表里（报 P1），两字名不报。所以两字名在弱锚点（患者、医师、护士）后接普通动词
     （“患者张伟病情加重”）不报；三字名若名字用字不在常见名用字表里、又没有右边界证据，也不报。
  3. 软字（和、会、年、日、时、芷、之、向、从、以、于、无）只许出现在三字名里：两字名含软字（王会、张会）漏报；
     弱锚点加软字名加普通动词（“王和平建议”“马会芳牵头”）不报。名字含向、从、以、于的三字名（宋向东、赵从军、郑以诚、胡于江）在强锚点下识别；
     “患者向医生反映”“患者从家中带来药物”“患者以头痛为主诉”“患者于昨日出院”这类功能字用法不报。
  4. 与整词排除词同形的姓名（刘海、林海、黎明、高峰）没有强证据（性别、住院号括注，职务称谓）时漏报；
     以前缀排除词起首的姓名（如“胡子轩”）、尾字是地名机构字的姓名（周行、赵桥）、名字含非名用字的姓名（黄镇）漏报。
  5. 少见姓、歧义姓（如“宁”“安”“管”）只给 P1 或要求标点、括注边界，弱语境下漏报。
  6. 第三字恰在名用字表且与后字不构成常见二字词时，可能多取一字；带“·”的姓名、外文名、昵称识别不了。
  7. 全文遮蔽是整串替换，会过度遮蔽（姓名“高明”会把“高明的做法”也遮掉）。
  8. 用“，”并列的后续姓名只在名单语境（锚点以冒号结尾，如“患者：张三，李四”）才读得到；其他语境（“患者张三，李四到场”）读不到。
     “、”并列不受限制，并列项后可跳过不超过 12 字的括注（“赵立新（主治医师）、钱敏（住院医师）”）。
  9. 文件名回显（报告头和 JSON 的 file 字段）经全文姓名表遮蔽：文件名里有、正文没识别到的姓名遮不住。
 10. 程序倒置“是否同一事项”只按字面包含判断，被动、跨段的写法识别不了，不保证穷尽换说法；
     出处、处置类豁免只看词面的让步词、例外词和否定，不理解语义。
 11. 常见名用字表和常见二字词表来自本仓库的规范文档，在其他领域可能漂移；references、SKILL.md 的文字有改动后，
     常见二字词表须用 tools/build_name_lexicon.py --update 重新生成并人工过目。
 12. Markdown 表格中，姓名列按同表敏感列分为 P0 和 P1。无姓名类表头、非 Markdown 表格、“患者家属 + 姓名”（“患者家属王淑芬”）仍可能漏报。
 13. 锚点之后由“、”（名单语境下还有“，”）和连词“和、与、及、同、跟”连接的并列链：只要链中任一项已识别，链上其余姓氏开头的 2～4 字项（含与常用词同形的、复姓的）一律登记进姓名表并遮蔽，首项未识别而后项识别时回溯登记首项（宁可多遮，“单亲”“杜鹃花”可能被遮成〔姓名N〕）；边界：整条链上没有任何一项被识别时不登记；并列链之外的同形名、无锚点的姓名仍识别不了；同一锚点下的并列姓名合并成一条（摘录含全部占位符）。姓名表覆盖全部隐私规则，不分文书类型（是否报出仍按文书类型）。
 14. HOS-033 只认“为指标调整编码”的写法，“目的在前”的写法（“为提升病例组合指数，建议……填写为主要诊断”）不报。
 15. 否决、整改、出处写在后一分句的句子会被报出（见上“收缩”），后续分句里有针对该做法的处置、出处词时 P0 降为 P1 并提示，需人工判断；
     程序倒置的组合判定只给 P1。
各语境下的召回率不写单一数字，见 tests/names 与 tests/hospital 的测试输出。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Sequence, Tuple

VERSION = "1.3.3"
_HERE = Path(__file__).resolve().parent
RULES_PATH = _HERE / "hospital_rules.json"
LEVELS = ("P0", "P1", "P2")
EXTERNAL_TYPE = "对外宣传"

# 【起草说明】分界行，与 gongwen_lint.py、fact_diff.py 的写法一致
DRAFT_NOTE_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:(?:\*\*|__)\s*)?【起草说明】")
# summary.markers 计数，与 gongwen_lint.py 的 TODO_MARK_RE、VERIFY_MARK_RE 写法一致（全角冒号）
TODO_MARK_RE = re.compile(r"【待补：[^】\n]*】")
VERIFY_MARK_RE = re.compile(r"【待核实：[^】\n]*】")
# 隐私规则摘录里，姓名右侧最多带出的字数；5 位以上连续数字（住院号等）不原样显示
RIGHT_TAIL = 8
LONG_DIGITS_RE = re.compile(r"\d{5,}")
DETECTORS = ("pattern", "names")
# 同一姓名同一位置被多条隐私规则报出时，级别相同保留哪一条：有床号 HOS-030，岗位角色词 HOS-032，其余 HOS-031
NAME_RULE_PRIORITY = {"HOS-030": 0, "HOS-032": 1, "HOS-031": 2}


class InputError(Exception):
    """输入错误，退出码 2。"""


# ---------------------------------------------------------------------------
# 共享模块（姓名识别、分句豁免）：缺文件或数据损坏时报错，不做静默降级
# ---------------------------------------------------------------------------

def _load_shared(stem: str):
    """按文件路径加载同目录的共享模块；模块名按 skill 目录区分，工具箱同进程加载多个引擎时不串用缓存。"""
    path = _HERE / f"{stem}.py"
    if not path.is_file():
        raise InputError(f"缺少 scripts/{stem}.py（共享模块），请重新安装本包或运行 tools/sync_shared.py")
    name = f"_gw_{_HERE.parent.name}_{stem}"
    mod = sys.modules.get(name)
    if mod is None:
        try:
            spec = importlib.util.spec_from_file_location(name, str(path))
            if spec is None or spec.loader is None:
                raise InputError(f"无法加载共享模块 scripts/{stem}.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        except InputError:
            sys.modules.pop(name, None)
            raise
        except Exception as exc:  # 语法错误、导入错误等：同样是安装不完整
            sys.modules.pop(name, None)
            raise InputError(f"共享模块 scripts/{stem}.py 无法加载：{exc}") from exc
    return mod


@dataclass
class SharedKit:
    names: Any      # gw_names
    clause: Any     # gw_clause
    lexicon: Any    # gw_names.Lexicon


_KIT: Optional[SharedKit] = None


def shared_kit() -> SharedKit:
    global _KIT
    if _KIT is None:
        names = _load_shared("gw_names")
        clause = _load_shared("gw_clause")
        try:
            lexicon = names.load_lexicon()
        except Exception as exc:  # LexiconError：数据文件缺失、损坏
            raise InputError(str(exc)) from exc
        _KIT = SharedKit(names, clause, lexicon)
    return _KIT


@dataclass
class Rule:
    id: str
    category: str
    gate: str
    level: str
    message: str
    suggestion: str
    basis: str
    types: Tuple[str, ...] = ()
    regex: Optional[Pattern[str]] = None
    external_level: Optional[str] = None
    detector: str = "pattern"  # pattern：正则；names：锚点 + 候选 + 打分（可同时带 pattern，用于“代称 + 床号”）
    low_level: Optional[str] = None  # names：低置信（总分恰为 5）使用的级别
    anchors: List[Any] = field(default_factory=list)
    exempt_map: Dict[str, Pattern[str]] = field(default_factory=dict)  # 窗口名 -> 豁免正则
    exempt_map_declared: Dict[str, Pattern[str]] = field(default_factory=dict)  # 同上，去掉处置类（命中处就近有如实声明时用）
    prefix_window: int = 8
    trigger: Optional[Pattern[str]] = None
    satisfied: Optional[Pattern[str]] = None
    negation: Optional[Pattern[str]] = None
    satisfied_scope: str = "document"  # document：全文任一处；adjacent：触发句同一句或相邻句
    mask_excerpt: bool = False
    later_hint: bool = False  # 规则带处置类、出处类豁免：后续分句里有针对该做法的处置、出处词时报出带提示，P0 降为 P1
    later_kinds: Tuple[str, ...] = ()  # 规则实际配置的豁免类别（dispose、source）：提示与降级只看这些类别的词
    hit_examples: List[str] = field(default_factory=list)
    miss_examples: List[str] = field(default_factory=list)
    level_examples: List[Dict[str, str]] = field(default_factory=list)  # [{"text":…, "level":"P1"}]

    def applies(self, doc_type: Optional[str]) -> bool:
        """types 为空时所有文书都查；非空时只在指定文书类型下查。"""
        if not self.types:
            return True
        return doc_type in self.types


@dataclass
class Inversion:
    rule_id: str
    types: Tuple[str, ...]
    cfg: Dict[str, Any]


@dataclass
class RuleSet:
    types: Tuple[str, ...]
    rules: List[Rule]
    procedural: List[Rule]
    kit: SharedKit
    inversion: Optional[Inversion] = None


# ---------------------------------------------------------------------------
# 规则加载
# ---------------------------------------------------------------------------

def _compile(pattern: Optional[str], rid: str, name: str) -> Optional[Pattern[str]]:
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise InputError(f"规则 {rid} 的 {name} 不是合法的正则表达式：{exc}") from exc


def _level(value: Any, rid: str) -> str:
    if value not in LEVELS:
        raise InputError(f"规则 {rid} 的级别 {value!r} 无效，只能是 P0、P1、P2")
    return str(value)


# 规则 JSON 的豁免字段 -> 生效的窗口（窗口定义见 gw_clause）
EXEMPT_FIELDS = (
    ("exempt_context", ("sentence",)),
    ("exempt_clause", ("clause",)),
    ("exempt_chain", ("chain",)),
    ("exempt_prev_clause", ("clause", "prev")),
    ("exempt_lead", ("lead",)),
    ("prefix_negation", ("prefix",)),
)


def _build_exempt(item: Dict[str, Any], rid: str, kit: SharedKit, declared: bool = False) -> Dict[str, Pattern[str]]:
    """规则的豁免窗口表。declared=True 时去掉处置类（exempt_dispose 和类别 dispose），
    供程序倒置规则在命中处就近有如实声明时使用。"""
    parts: Dict[str, List[str]] = {}
    for key, windows in EXEMPT_FIELDS:
        pat = item.get(key)
        if not pat:
            continue
        _compile(pat, rid, key)
        for win in windows:
            parts.setdefault(win, []).append(pat)
    dispose = item.get("exempt_dispose")
    if dispose:
        _compile(dispose, rid, "exempt_dispose")
        if not declared:
            parts.setdefault("clause", []).append(dispose)
    cats = item.get("exempt_categories") or []
    if not isinstance(cats, list):
        raise InputError(f"规则 {rid} 的 exempt_categories 必须是列表")
    for cat in cats:
        spec = kit.clause.CATEGORY_SPEC.get(cat)
        if spec is None:
            raise InputError(f"规则 {rid} 的 exempt_categories 含未知类别：{cat}；可选：{'、'.join(kit.clause.CATEGORIES)}")
        if declared and cat == "dispose":
            continue
        for win, words in spec.items():
            parts.setdefault(win, []).append(words)
    return {win: re.compile("|".join(f"(?:{p})" for p in ps)) for win, ps in parts.items()}


def _later_kinds(item: Dict[str, Any]) -> Tuple[str, ...]:
    """规则实际配置的豁免类别：exempt_categories 里的 dispose、source，exempt_dispose（处置类），豁免正则里引用的 <<DISPOSE>>、<<SOURCE>>。"""
    cats = item.get("exempt_categories") or []
    kinds = []
    if "dispose" in cats or item.get("exempt_dispose") or any(
            isinstance(v, str) and "<<DISPOSE>>" in v for k, v in item.items() if k.startswith("exempt")):
        kinds.append("dispose")
    if "source" in cats or any(isinstance(v, str) and "<<SOURCE>>" in v for k, v in item.items() if k.startswith("exempt")):
        kinds.append("source")
    return tuple(kinds)


def _build_rule(item: Dict[str, Any], procedural: bool, kit: SharedKit) -> Rule:
    rid = str(item.get("id") or "").strip()
    if not rid:
        raise InputError("规则缺少 id")
    for key in ("category", "gate", "message", "basis"):
        if not item.get(key):
            raise InputError(f"规则 {rid} 缺少 {key}")
    detector = str(item.get("detector") or "pattern")
    if detector not in DETECTORS:
        raise InputError(f"规则 {rid} 的 detector 只能是 {'、'.join(DETECTORS)}")
    prefix_window = item.get("prefix_window", 8)
    if not isinstance(prefix_window, int) or isinstance(prefix_window, bool) or prefix_window < 0:
        raise InputError(f"规则 {rid} 的 prefix_window 必须是非负整数")
    rule = Rule(
        id=rid,
        category=item["category"],
        gate=item["gate"],
        level=_level(item.get("level"), rid),
        message=item["message"],
        suggestion=item.get("suggestion", ""),
        basis=item["basis"],
        types=tuple(item.get("types") or ()),
        external_level=_level(item["external_level"], rid) if item.get("external_level") else None,
        detector=detector,
        low_level=_level(item["low_level"], rid) if item.get("low_level") else None,
        exempt_map=_build_exempt(item, rid, kit),
        exempt_map_declared=_build_exempt(item, rid, kit, declared=True),
        prefix_window=prefix_window,
        later_hint=bool(_later_kinds(item)),
        later_kinds=_later_kinds(item),
        mask_excerpt=bool(item.get("mask_excerpt")),
        hit_examples=list(item.get("hit_examples") or []),
        miss_examples=list(item.get("miss_examples") or []),
        level_examples=[dict(x) for x in item.get("level_examples") or []],
    )
    for example in rule.level_examples:
        if not isinstance(example.get("text"), str) or example.get("level") not in LEVELS:
            raise InputError(f"规则 {rid} 的 level_examples 每项须有 text 和 level（P0、P1、P2）")
    if procedural:
        rule.trigger = _compile(item.get("trigger"), rid, "trigger")
        rule.satisfied = _compile(item.get("satisfied"), rid, "satisfied")
        rule.negation = _compile(item.get("satisfied_negation"), rid, "satisfied_negation")
        rule.satisfied_scope = str(item.get("satisfied_scope") or "document")
        if rule.satisfied_scope not in ("document", "adjacent"):
            raise InputError(f"程序性规则 {rid} 的 satisfied_scope 只能是 document 或 adjacent")
        if rule.trigger is None or rule.satisfied is None:
            raise InputError(f"程序性规则 {rid} 须同时有 trigger 和 satisfied")
        return rule
    rule.regex = _compile(item.get("pattern"), rid, "pattern")
    if detector == "names":
        if not item.get("name_anchors"):
            raise InputError(f"规则 {rid} 的 detector 为 names，须有 name_anchors")
        if rule.low_level is None:
            raise InputError(f"规则 {rid} 的 detector 为 names，须有 low_level")
        try:
            rule.anchors = kit.names.compile_anchors(item["name_anchors"])
        except Exception as exc:  # AnchorError：锚点配置有误
            raise InputError(f"规则 {rid} 的 name_anchors 有误：{exc}") from exc
    elif rule.regex is None:
        raise InputError(f"规则 {rid} 缺少 pattern")
    return rule


def _build_inversion(data: Any, types: Tuple[str, ...], rules: List[Rule]) -> Optional[Inversion]:
    if not data:
        return None
    if not isinstance(data, dict):
        raise InputError("procedure_inversion 必须是对象")
    rule_id = str(data.get("rule_id") or "")
    if rule_id not in {r.id for r in rules}:
        raise InputError(f"procedure_inversion 的 rule_id {rule_id!r} 不是已登记的规则")
    inv_types = tuple(data.get("types") or ())
    unknown = [t for t in inv_types if t not in types]
    if unknown:
        raise InputError(f"procedure_inversion 的 types 含未登记的文书类型：{'、'.join(unknown)}")
    for key in ("exec", "exec_neg", "prior_ok", "req", "other_obj", "decl", "normalize"):
        if data.get(key):
            _compile(data[key], rule_id, f"procedure_inversion.{key}")
    return Inversion(rule_id=rule_id, types=inv_types, cfg=dict(data))


def load_rules(path: Path = RULES_PATH) -> RuleSet:
    """读取规则文件。规则文件、共享模块缺失或格式错误时抛出 InputError。"""
    kit = shared_kit()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InputError(f"找不到规则文件：{path}") from exc
    except (OSError, ValueError) as exc:
        raise InputError(f"规则文件无法读取或不是合法的 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise InputError("规则文件顶层必须是对象")
    types = tuple(data.get("types") or ())
    rules = [_build_rule(item, False, kit) for item in data.get("rules") or []]
    procedural = [_build_rule(item, True, kit) for item in data.get("procedural") or []]
    ids = [r.id for r in rules + procedural]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise InputError(f"规则 id 重复：{'、'.join(duplicated)}")
    for rule in rules + procedural:
        unknown = [t for t in rule.types if t not in types]
        if unknown:
            raise InputError(f"规则 {rule.id} 的 types 含未登记的文书类型：{'、'.join(unknown)}")
    inversion = _build_inversion(data.get("procedure_inversion"), types, rules)
    return RuleSet(types=types, rules=rules, procedural=procedural, kit=kit, inversion=inversion)


# ---------------------------------------------------------------------------
# 输入读取
# ---------------------------------------------------------------------------

def read_lines(path: Path) -> List[Tuple[int, str]]:
    """读取文件，返回 [(行号或段落序号, 文本)]，到【起草说明】为止。"""
    if not path.is_file():
        raise InputError(f"文件不存在：{path}")
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md", ".markdown", ".text"):
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw.decode("gb18030")
            except UnicodeDecodeError as exc:
                raise InputError("无法识别文件编码，请另存为 UTF-8 后重试。") from exc
        lines = list(enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), start=1))
    elif suffix == ".docx":
        lines = _read_docx(path)
    else:
        raise InputError(f"不支持的文件类型：{path.suffix or '无扩展名'}。只支持 .txt、.md、.docx。")
    return cut_at_note(lines)


def _read_docx(path: Path) -> List[Tuple[int, str]]:
    try:
        import docx  # type: ignore
        from docx.oxml.ns import qn  # type: ignore
        from docx.text.paragraph import Paragraph  # type: ignore
    except ImportError as exc:
        raise InputError("读取 .docx 需要 python-docx，请先运行：pip install python-docx") from exc
    try:
        document = docx.Document(str(path))
    except Exception as exc:  # 损坏或加密的文件
        raise InputError(f"无法打开 docx 文件：{exc}") from exc
    lines: List[Tuple[int, str]] = []
    number = 0
    p_tag, tbl_tag = qn("w:p"), qn("w:tbl")
    for child in document.element.body.iterchildren():
        if child.tag == p_tag:
            number += 1
            lines.append((number, Paragraph(child, document).text))
        elif child.tag == tbl_tag:
            for p_el in child.iter(p_tag):
                number += 1
                lines.append((number, Paragraph(p_el, document).text))
    return lines


def cut_at_note(lines: Sequence[Tuple[int, str]]) -> List[Tuple[int, str]]:
    """只保留【起草说明】之前的正文。"""
    kept: List[Tuple[int, str]] = []
    for number, text in lines:
        if DRAFT_NOTE_RE.match(text):
            break
        kept.append((number, text))
    return kept


# ---------------------------------------------------------------------------
# 检查
# ---------------------------------------------------------------------------

def _clip(text: str, limit: int = 40) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "……"


class _Masker:
    """全文姓名表的遮蔽器：截取片段时不切开姓名，再整体替换成〔姓名N〕（截取与遮蔽由共享模块 NameTable.cut 完成）。"""

    def __init__(self, table: Any) -> None:
        self.table = table

    def cut(self, text: str, start: int, end: int) -> str:
        return self.table.cut(text, start, end)

    def privacy_excerpt(self, text: str, start: int, end: int) -> str:
        """隐私规则的摘录：[start, end) 加右侧最多 RIGHT_TAIL 字，姓名换成占位符，长数字不原样显示。"""
        tail_end = min(len(text), end + RIGHT_TAIL)
        while 0 < tail_end < len(text) and text[tail_end - 1].isdigit() and text[tail_end].isdigit():
            tail_end += 1  # 不把一串长数字（住院号等）截成半截显示
        out = self.cut(text, start, tail_end).strip()
        return _clip(LONG_DIGITS_RE.sub("×××", out), 60)


def _is_exempt(rule: Rule, kit: SharedKit, text: str, start: int, end: int, declared: bool = False) -> bool:
    """规则的各类豁免，统一用 gw_clause 的窗口：分句、顿号并列分句串、前一分句、引导分句、命中前若干字、整句（没有后续分句窗口）。
    declared=True（程序倒置规则、命中处就近有如实声明）时不适用处置类豁免。"""
    mapping = rule.exempt_map_declared if declared else rule.exempt_map
    if not mapping:
        return False
    return kit.clause.is_exempt(text, start, end, mapping, rule.prefix_window)


# 程序倒置组合判定降为 P1 时，按原因（gw_clause.find_inversions 的 reason_code）给 message；P0 沿用规则自带的 message
INVERSION_P1_MESSAGES = {
    "same_sentence": "同一句里既写了“已执行”又写了“提请审议”，请核实是否先执行后上会（组合判定仅作提示）",
    "normalize": "出现“追认”“补办”字样，请核实是否先执行后上会，写清已执行情况、原因和责任",
    "declared": "已如实写明程序倒置，请确认写清已执行情况、原因和责任，由会议决定后续处理；不要写成追认或补办",
    "other_item": "提请事项可能与已执行事项不同（如二期、续签），请核实提请事项本身没有先行实施",
    "adjacent": "“已执行”与“提请审议”在相邻两句，请核实是否先执行后上会",
    "weak_exec": "“于X月开工、投入使用”等写法表明已执行，请核实是否先执行后上会",
}


def _inversion_message(rule: Rule, level: str, reason_code: str) -> str:
    """HOS-034 的 message：P0 用规则自带的；P1（组合判定，或正则 P0 经声明降级）时按原因给。"""
    if level == "P0":
        return rule.message
    return INVERSION_P1_MESSAGES.get(reason_code, INVERSION_P1_MESSAGES["adjacent"])


def _issue(rule: Rule, level: str, line: int, excerpt: str, context: str = "",
           message: Optional[str] = None, hint: bool = False) -> Dict[str, Any]:
    suggestion = rule.suggestion
    if hint:      # 命中之后的分句里有处置、出处词：收缩后它们不再豁免，提示可能是已写明否决、整改或出处的句子
        suggestion = (suggestion.rstrip("。；") + "；" if suggestion else "") + shared_kit().clause.LATER_HINT + "。"
    data: Dict[str, Any] = {
        "id": rule.id,
        "level": level,
        "category": rule.category,
        "line": line,
        "excerpt": excerpt,
        "message": message or rule.message,
        "suggestion": suggestion,
        "basis": rule.basis,
        "check": "hospital",
        "gate": rule.gate,
    }
    if context and context != excerpt:
        data["context"] = context
    return data


def _adjacent_window(text: str, start: int, end: int, kit: SharedKit) -> Tuple[int, int]:
    """触发句及其前后各一个非空句子合起来的范围（句子按 gw_clause 的整句切分）。"""
    sents = [(a, b) for a, b in kit.clause.split_sentences(text) if text[a:b].strip()]
    if not sents:
        return 0, len(text)
    k = 0
    for i, (a, _b) in enumerate(sents):
        if a <= start:
            k = i
    lo = sents[k - 1][0] if k > 0 else sents[k][0]
    hi = sents[k + 1][1] if k + 1 < len(sents) else sents[k][1]
    return lo, max(hi, end)


def _is_satisfied(rule: Rule, kit: SharedKit, text: str, start: int = 0, end: Optional[int] = None) -> bool:
    """程序性规则：触发句同一句或相邻句里有一处未被否定的 satisfied 命中即算满足。

    satisfied_negation 只看命中处之前、同一分句内的 8 个字（gw_clause 的 prefix 窗口），
    如“尚未提交党委会议”“未经党委会议”“须经院领导确认”“待确认”不算已满足。
    """
    if rule.satisfied is None:
        return False
    end = len(text) if end is None else end
    if rule.satisfied_scope == "adjacent":
        lo, hi = _adjacent_window(text, start, end, kit)
    else:
        lo, hi = 0, len(text)
    for match in rule.satisfied.finditer(text, lo, hi):
        if rule.negation is None:
            return True
        before = kit.clause.compute_windows(text, match.start(), match.end(), 8).prefix
        if not rule.negation.search(before):
            return True
    return False


def check_lines(lines: Sequence[Tuple[int, str]], doc_type: Optional[str] = None,
                external: bool = False, ruleset: Optional[RuleSet] = None) -> List[Dict[str, Any]]:
    """对正文逐行检查，返回 issue 列表（按行号排序）。"""
    issues, table = _check_lines(lines, doc_type, external, ruleset)
    return table.mask_output(issues)


def _check_lines(lines: Sequence[Tuple[int, str]], doc_type: Optional[str] = None,
                 external: bool = False, ruleset: Optional[RuleSet] = None) -> Tuple[List[Dict[str, Any]], Any]:
    """check_lines 的实现；同时返回全文姓名表（供文件名回显遮蔽）。"""
    ruleset = ruleset or load_rules()
    kit = ruleset.kit
    external = external or doc_type == EXTERNAL_TYPE
    applicable = [r for r in ruleset.rules if r.applies(doc_type)]
    texts = [text for _n, text in lines]

    # 第一遍：识别全文姓名（含因豁免不报的），按首次出现顺序编号。代称（张某）不进表，低于 5 分的不进表
    # 姓名表覆盖全部隐私（姓名类）规则，不分文书类型（与国企一致）：不适用于当前文书类型的规则识别出的姓名也要遮蔽，是否报出仍按类型
    issues: List[Dict[str, Any]] = []
    detections: List[Tuple[int, int, int, Rule, Any]] = []
    for order, rule in enumerate(ruleset.rules):
        if rule.id == "HOS-031":
            for idx, row in kit.names.find_table_names(texts, kit.lexicon, "hospital").items():
                detections.extend((idx, hit.start, order, rule, hit) for hit in row.hits)
                if row.unrecognized and rule.applies(doc_type):
                    issues.append(_issue(rule, "P1", lines[idx][0], "", message=kit.names.TABLE_UNKNOWN_HINT))
        if not rule.anchors:
            continue
        for idx, (_number, text) in enumerate(lines):
            for hit in kit.names.find_names(text, rule.anchors, kit.lexicon):
                detections.append((idx, hit.start, order, rule, hit))
    detections.sort(key=lambda d: (d[0], d[1], d[2]))
    table = kit.names.NameTable()
    for _idx, _start, _order, _rule, hit in detections:
        if not hit.pseudo:
            table.add(hit.name)
    masker = _Masker(table)

    inv = ruleset.inversion
    inv_active = inv is not None and (not inv.types or doc_type in inv.types)
    decl = kit.clause.Declaration(texts, dict(inv.cfg, rule_id=inv.rule_id)) if inv_active and inv is not None else None

    # 姓名类命中：高置信（总分 >= 6）用规则级别，低置信（== 5）用 low_level。
    # 同一姓名、同一位置被 HOS-030、031、032 里多条规则报出时去重，只留一条：级别最高的；级别相同留语义最贴切的
    # （有床号 HOS-030，岗位角色词 HOS-032，其余 HOS-031）
    picked: Dict[Tuple[int, int, int], Tuple[int, int, Dict[str, Any]]] = {}
    # 同一规则、同一锚点下的并列姓名（“当事护士刘佳、李娜两人……”）共用一条摘录：从锚点读到最后一个姓名（含只登记的后项），
    # 各姓名的摘录相同，由 merge_issues 合并成一条并带 count
    group_end: Dict[Tuple[int, str, int], int] = {}
    for idx, _start, _order, rule, hit in detections:
        if hit.anchor_start >= 0:
            gkey = (idx, rule.id, hit.anchor_start)
            group_end[gkey] = max(group_end.get(gkey, 0), hit.end)
    for idx, _start, _order, rule, hit in detections:
        if hit.pseudo or hit.table_only or not rule.applies(doc_type):    # 代称不报；并列后项（table_only）只进姓名表用于遮蔽；不适用于当前文书类型的规则只登记不报
            continue
        number, text = lines[idx]
        from_table = hit.anchor_start < 0
        if not from_table and _is_exempt(rule, kit, text, hit.start, hit.end):
            continue
        level = rule.level if hit.score >= kit.names.SCORE_HIGH else (rule.low_level or rule.level)
        anchor_start = hit.anchor_start if 0 <= hit.anchor_start <= hit.start else hit.start
        ex_end = hit.end
        if anchor_start == hit.anchor_start:
            ex_end = max(hit.end, group_end.get((idx, rule.id, hit.anchor_start), hit.end))
        if from_table:
            issue = _issue(rule, level, number, table.placeholder(hit.name), message="表格姓名列出现真实姓名")
        else:
            issue = _issue(rule, level, number, masker.privacy_excerpt(text, anchor_start, ex_end))
        key = (idx, hit.start, hit.end)
        rank = (LEVELS.index(level), NAME_RULE_PRIORITY.get(rule.id, len(NAME_RULE_PRIORITY)))
        old = picked.get(key)
        if old is None or rank < old[:2]:
            picked[key] = (rank[0], rank[1], issue)
    issues.extend(v[2] for v in picked.values())

    # 正则命中（含 HOS-030 里“代称 + 床号”的组合红线）
    for rule in applicable:
        if rule.regex is None:
            continue
        level0 = rule.external_level if (external and rule.external_level) else rule.level
        for idx, (number, text) in enumerate(lines):
            for match in rule.regex.finditer(text):
                if match.end() == match.start():
                    continue
                is_inv = decl is not None and inv is not None and rule.id == inv.rule_id
                near = bool(is_inv and decl.near_declared(idx, match.start()))
                if _is_exempt(rule, kit, text, match.start(), match.end(), declared=near):
                    continue
                level = level0
                message = None
                if is_inv:
                    level = decl.adjust(level, idx, match.start())
                    if level != level0:  # 声明降级（就近有肯定式声明）
                        message = _inversion_message(rule, level, "declared")
                # 后续分句里有针对该做法的处置、出处词：不再豁免，但 P0 降为 P1（仍报出要人看），并追加提示
                hint = rule.later_hint and kit.clause.later_exemption_words(text, match.start(), match.end(), rule.later_kinds)
                # 程序倒置规则：就近写了追认、补办的，本身就是在补手续，不因后文的处置词降级
                if hint and level == "P0" and not (is_inv and decl.near_normalized(idx, match.start())):
                    level = "P1"
                if rule.mask_excerpt:
                    issues.append(_issue(rule, level, number, masker.privacy_excerpt(text, match.start(), match.end()), hint=hint))
                else:
                    issues.append(_issue(rule, level, number,
                                         _clip(masker.cut(text, match.start(), match.end())),
                                         masker.cut(text, match.start() - 12, match.end() + 12).strip(),
                                         message, hint=hint))

    # 程序倒置：同一句“已执行”加“提请或补办”的组合判定，与同一行已有的正则命中合并（取较高级别，保留正则那条的摘录）
    if inv_active and inv is not None:
        inv_rule = next((r for r in applicable if r.id == inv.rule_id), None)
        if inv_rule is not None:
            for res in kit.clause.find_inversions(texts, dict(inv.cfg, rule_id=inv.rule_id)):
                idx = int(res["line"]) - 1
                number, text = lines[idx]
                if _is_exempt(inv_rule, kit, text, res["start"], res["end"], declared=bool(res.get("declared"))):
                    continue
                same = [i for i in issues if i["id"] == inv_rule.id and i["line"] == number]
                code = str(res.get("reason_code") or "p0")
                if same:
                    for item in same:
                        if LEVELS.index(res["level"]) < LEVELS.index(item["level"]):
                            item["level"] = res["level"]
                            item["message"] = _inversion_message(inv_rule, res["level"], code)
                    continue
                issues.append(_issue(inv_rule, res["level"], number,
                                     _clip(masker.cut(text, res["start"], res["end"])),
                                     masker.cut(text, res["start"] - 12, res["end"] + 12).strip(),
                                     _inversion_message(inv_rule, res["level"], code)))

    # 程序性规则：全文是否有满足条件的表述
    full_text = "\n".join(text for _number, text in lines)
    offsets: List[int] = []
    pos = 0
    for _number, text in lines:
        offsets.append(pos)
        pos += len(text) + 1
    for rule in ruleset.procedural:
        if not rule.applies(doc_type) or rule.trigger is None or rule.satisfied is None:
            continue
        for (number, text), offset in zip(lines, offsets):
            match = rule.trigger.search(text)
            if match and not _is_satisfied(rule, kit, full_text, offset + match.start(), offset + match.end()):
                issues.append(_issue(rule, rule.level, number,
                                     masker.cut(text, match.start(), match.end()),
                                     masker.cut(text, match.start() - 12, match.end() + 12).strip()))
                break

    issues = kit.names.merge_issues(issues)
    issues.sort(key=lambda item: (item["line"], LEVELS.index(item["level"]), item["id"]))
    return issues, table


def check_text(text: str, doc_type: Optional[str] = None, external: bool = False,
               file_name: str = "<text>", ruleset: Optional[RuleSet] = None) -> Dict[str, Any]:
    """检查一段文本（供测试和其他脚本调用）。"""
    lines = list(enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), start=1))
    return build_result(file_name, cut_at_note(lines), doc_type, external, ruleset)


def check_file(path: Path, doc_type: Optional[str] = None, external: bool = False,
               ruleset: Optional[RuleSet] = None) -> Dict[str, Any]:
    return build_result(path.name, read_lines(path), doc_type, external, ruleset)


def build_result(file_name: str, lines: Sequence[Tuple[int, str]], doc_type: Optional[str],
                 external: bool, ruleset: Optional[RuleSet] = None) -> Dict[str, Any]:
    ruleset = ruleset or load_rules()
    if doc_type is not None and doc_type not in ruleset.types:
        raise InputError(f"--type 只能取：{'、'.join(ruleset.types)}")
    issues, table = _check_lines(lines, doc_type, external, ruleset)
    file_name = table.mask(str(file_name))  # 文件名里的已识别姓名一并遮蔽（正文没识别到的遮不住）
    notes: List[str] = []
    if doc_type is None:
        notes.append("未指定 --type，只限某类文书的规则（如根因分析写法、议题程序）没有执行。")
    notes.append("行业机检只覆盖能写成规则的项目；数据溯源、口径、前置程序是否属实，按 references/review-addon.md 人工核对。")
    summary: Dict[str, Any] = {lv: sum(1 for i in issues if i["level"] == lv) for lv in LEVELS}
    summary["markers"] = {
        "待补": sum(len(TODO_MARK_RE.findall(text)) for _n, text in lines),
        "待核实": sum(len(VERIFY_MARK_RE.findall(text)) for _n, text in lines),
    }
    return table.mask_output({
        "file": file_name,
        "doc_type": doc_type or "未指定",
        "external": bool(external or doc_type == EXTERNAL_TYPE),
        "char_count": sum(len(re.sub(r"\s", "", text)) for _n, text in lines),
        "summary": summary,
        "issues": issues,
        "notes": notes,
        "engine_version": VERSION,
    })


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def render_text(result: Dict[str, Any]) -> str:
    unit = "段" if str(result["file"]).lower().endswith(".docx") else "行"
    s = result["summary"]
    scope = "，按对外材料从严" if result.get("external") else ""
    out = [
        f"行业机检结果：{result['file']}（文书：{result['doc_type']}{scope}；正文 {result['char_count']} 字）",
        f"P0 {s['P0']} 处｜P1 {s['P1']} 处｜P2 {s['P2']} 处",
    ]
    markers = s.get("markers") or {}
    if markers.get("待补") or markers.get("待核实"):
        out.append(f"待补 {markers.get('待补', 0)} 处、待核实 {markers.get('待核实', 0)} 处，定稿前补齐")
    if not result["issues"]:
        out += ["", "未发现行业规则问题。"]
    for issue in result["issues"]:
        out.append("")
        out.append(f"[{issue['level']}] 第{issue['line']}{unit}  {issue['id']}  {issue['category']}：{issue['message']}")
        line = f"    原文：{issue['excerpt']}"
        if issue.get("context"):
            line += f"（上下文：{issue['context']}）"
        if issue.get("count", 1) > 1:
            line += f"（该行同样的命中共 {issue['count']} 处）"
        out.append(line)
        if issue.get("suggestion"):
            out.append(f"    建议：{issue['suggestion']}")
        out.append(f"    依据：{issue['basis']}")
    if result.get("notes"):
        out.append("")
        out.extend(f"提示：{note}" for note in result["notes"])
    return "\n".join(out)


def render_rules(ruleset: RuleSet) -> str:
    out = ["行业机检规则清单："]
    for rule in ruleset.rules + ruleset.procedural:
        scope = "、".join(rule.types) if rule.types else "全部"
        ext = f"；对外材料 {rule.external_level}" if rule.external_level else ""
        out.append(f"{rule.id}  [{rule.level}{ext}]  {rule.category}：{rule.message}（适用：{scope}）")
    return "\n".join(out)


class _ChineseHelpFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):  # type: ignore[override]
        return super().add_usage(usage, actions, groups, prefix="用法：")


def build_parser(types: Sequence[str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hospital_check.py",
        description="医院专用文书的行业机检：疗效表述、决策程序、指数写法、指标名称、过时依据、根因分析写法、患者隐私、当事人信息、编码与医保、程序倒置、廉洁表述、评审结论、敏感事项。",
        epilog="退出码：0 正常；--strict 且存在 P0 时为 1；输入错误为 2。docx 输入时“行号”为段落序号。",
        add_help=False,
        formatter_class=_ChineseHelpFormatter,
    )
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    parser.add_argument("file", nargs="?", help="待检查文件（.txt、.md、.docx），遇到【起草说明】行即停止读取")
    parser.add_argument("--type", dest="doc_type", default=None, metavar="文书",
                        help="文书类型：" + "、".join(types) + "。不填时只执行不限文书的规则")
    parser.add_argument("--external", action="store_true",
                        help="按对外发布材料从严（疗效、领先类表述升级）；--type 对外宣传 时自动启用")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--strict", action="store_true", help="存在 P0 时返回 1")
    parser.add_argument("--list-rules", action="store_true", help="列出全部规则后退出")
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass
    try:
        ruleset = load_rules()
    except InputError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    parser = build_parser(ruleset.types)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    if args.list_rules:
        print(render_rules(ruleset))
        return 0
    if not args.file:
        print("错误：请指定待检查的文件", file=sys.stderr)
        return 2
    try:
        result = check_file(Path(args.file), args.doc_type, args.external, ruleset)
    except InputError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_text(result))
    if args.strict and result["summary"]["P0"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
