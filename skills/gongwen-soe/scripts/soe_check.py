#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""国有企业专用文书的行业机检（gongwen-soe）。

在通用机检 gongwen_lint.py 之外，补查国企专用文书中能写成规则的问题：
  - 决策程序：先执行后补程序、追认、职代会后置、直接提交决策机构、党委会“决定”经营事项、
    拆分规避集体决策、经理层超授权（SOE-001～007、029）；
  - 对外表述：无出处的“第一”“领先”、绝对化环境声明和合规结论（SOE-008～010）；
  - 对外材料中的未公开信息、商业秘密、经营数据（SOE-011～013、027，只在对外材料中检查）；
  - 材料自带商业秘密标注、处分对象和敏感人员名单的姓名（个人信息，见下“实名识别与遮蔽”）、职工安置方案只听取意见、
    议案预写表决结果、合规报告自称已经董事会审议（SOE-021～028）；
  - 数据表述：比率变化用百分数、同比环比用混（SOE-014、015）；党建成效归因（SOE-016）；
  - 函数检查：议题要件和方案比选（SOE-101、102）、议案要件（SOE-103）、决议出席人数和票数（SOE-104）、
    改革台账状态（SOE-105）、ESG 披露口径（SOE-106）、金额单位（SOE-107，制度标准金额不计）、
    纪要议定事项和前置程序（SOE-108、109）、融合材料“两张皮”（SOE-110）、
    职工切身利益议题缺职代会或工会意见（SOE-111）。

实名识别与遮蔽（SOE-022 处分对象、SOE-023 敏感人员名单）：
  - 识别方式是“锚点 + 候选 + 打分”，由共享模块 gw_names.py 完成：先找能带出姓名的上下文（“给予……处分”“被开除党籍”
    “拟提拔人选名单：”），再在锚点旁取 2～4 字的候选，按“锚点分 + 边界分 + 形态分”打分。总分 >= 6 为高置信，
    用规则级别（SOE-022 为 P0）；总分 = 5 为低置信，降为 P1（如歧义姓的两字名）；< 5 不报。不分内外，只按置信度分级。
  - 全文姓名表：所有被识别的姓名（包括因豁免没报出的）按全文首次出现顺序编号，输出里一律写成〔姓名1〕〔姓名2〕；
    所有规则（含函数检查 SOE-1xx）的 excerpt、context，以及文本和 JSON 输出都经同一张表遮蔽。
    隐私规则自己的 excerpt 保留“锚点 + 占位 + 右侧最多 8 字”，如“对〔姓名1〕给予记过处分。”。
    代称（张某）不进表。(id、行号、遮蔽后摘录、说明) 完全相同的多条合并为一条，带 count。
  - 缺少 gw_names.py、gw_names.json 或 gw_clause.py，或数据文件损坏时，直接按输入错误退出（退出码 2），
    不静默降级——隐私是 P0 红线，“没查成”不能显示成“没检出”。

豁免窗口统一用共享模块 gw_clause.py：整句按 。！？；!?;换行 切；分句再按 ，,、：: 切。窗口有 clause（命中所在分句）、prev（紧邻的前一分句，出处类用）、
chain（命中分句向前并入顿号连着的并列分句，禁止类用：“杜绝先行开工、先行签约”里第二项也在“杜绝”之内）、
lead（分句紧跟冒号时冒号前的引导分句）、prefix（命中前同一分句内 N 个字，默认 8，
规则里用 prefix_window 调整）、sentence（整句，只留给出处、后续程序常在相邻分句的少数规则，如 SOE-008）。
规则 JSON 的 exempt_clause、exempt_chain、exempt_lead、exempt_before、exempt_context 依次对应这些窗口；
exempt_dispose（只看命中所在分句）是处置类的自带词，程序倒置规则（SOE-001）在命中处就近有如实声明时不适用；
【收缩】命中之后的分句不再能豁免（已取消 after 窗口）：处置类只在命中所在分句内生效，出处类在命中所在分句与紧邻的前一分句内生效；
否决、整改、出处写在后一分句的句子会重新被报出（已知代价）：后续分句里若有针对该做法的处置、出处词（后续词同样要过让步、例外、定语、“避免违规”这类目的成分、指他、“此前”这类过去、出处未出具的语境检查，只看规则实际配置的类别），P0 降为 P1 仍报出，suggestion 末尾补“若后文已写明否决、整改或出处，可忽略本条”；处置词在同一分句里时必须针对被命中的做法：在命中之后要紧接（间隔不超过 14 字、没有“并、且、同时、还”等并列词、之后不再带无关宾语），在命中之前要是“否决了……的建议”这样的指称结构，拿不准不豁免；“经自我评价、院内评审、本院认定、初步评价”不算出处；
豁免正则里可写 <<DISPOSE>>（处置类）、<<SOURCE>>（出处类）、<<PROHIBIT>>（禁止类），由共享模块代入。

程序倒置（SOE-001）：除正则外，还用 gw_clause.find_inversions 做“已执行 + 提请或补办”的组合判定
（规则 JSON 顶层 procedure_inversion，七个判定正则全部用共享模块默认口径，本包不覆盖）。组合判定只在议题材料、议案、纪要、决议中生效，
SOE-001 的正则规则本身不限文书类型。【收缩】组合判定的命中一律为 P1（提示性质），P0 只来自 SOE-001 对
“先行开工、补办手续、先……后报批”等明确写法的正则命中（动词里没有“采购”）；单独的“追认”写法由 SOE-002 报 P1。已执行分两档：强档为“已开工建设、已签约、已与……签订合同、已完成……采购安装、已进场施工、已开始施工、
主体工程已完成30%”等；弱档为不带“已”的“于9月开工、投入使用”。已执行成分作定语（已签订的框架协议）、计划于、拟于、战略合作框架协议、
采购管理办法等不判；提请对象是验收、结算、备案、收费标准、管理办法、计划、预算等事后正常事项且没有追认、补办的不判。
如实声明降级只作用于正则命中的 P0：同一句或紧邻的前、后一句有未被否定的肯定式声明（“属于程序倒置”“未履行决策程序”“该做法违反……规定”），
且这三句里没有追认、补办，才降 P1；“不属于、不存在、未发生、杜绝、防止、自查”等否定写法和单独的“如实报告”“如实说明”不算声明；不再有全文级降级。
声明只认“对本事项的直接断言”：主语是“该、本、此、上述、以上 + 项目、事项、做法、情况”或承前省略，声明所在分句以断言收束；疑问（是否）、条件（如、若）、转述（有人认为、……的说法）、指他（其他单位）、“难以认定、谈不上、算不上、未必、所谓、质疑”等写法不算；追认、补办的检查范围是声明所在句及其后两句、倒置句及其前后一句；拿不准不降级（保持 P0）。
命中处就近有声明时，“已整改”“违反”等处置类豁免不适用；声明判断统一调用 gw_clause.Declaration。
P1 的说明文案按 find_inversions 给出的 reason_code 选用，不会出现与原因矛盾的文字。与同一行已有的正则命中合并，保留正则那条的级别与摘录。

已知局限（机检只做能写成规则的部分，其余人工核对）：
  1. 没有锚点就识别不了：单独一句“马建国分管的项目……”不会被当作姓名；只有同一姓名在别处被锚点识别过，才靠全文姓名表遮蔽。
  2. 名字里用了黑名单字、或尾字是地名机构字的姓名会漏报（如“李山”“孙湖”“王会”）。
  3. 少见姓、歧义姓只给 P1，弱语境下漏报；与整词排除词同形的姓名（刘海、林海）没有强证据时漏报；处分对象与处分隔着分句
     （“李建华……已被开除党籍”）识别不了。
  4. “对唐钢给予警告处分”这类缺少人名证据的同形简称报 P1 待确认。显式定义的单位简称也登记并遮蔽，提示中标明定义。紧贴本次出现的前置职务、个人称呼、个人信息括注、自然人列，以及同一框架内的个人专属处分均交回原规则或表格分级，正文名单和普通表仍报 P1。
  5. 名单类锚点按顿号、逗号读到句末，用分号或换行分开的后续名单项读不到；带“·”的姓名、外文名、昵称识别不了。
  6. 全文遮蔽是整串替换，会过度遮蔽（姓名“高明”会把“高明的做法”也遮成占位）。
  7. 文件名：报告头和 JSON 的 file 字段按全文姓名表遮蔽；文件名里写着、正文没有被锚点识别到的姓名遮不住。
  8. 程序倒置组合判定按固定搭配判断，只给 P1；“是否同一事项”只按字面包含判断，被动句、跨段、跨三句以上的写法识别不了，
     不保证穷尽所有换说法，须人工复核。
  9. 否决、整改、出处写在后一分句的句子会被报出，后续分句里有针对该做法的处置词时 P0 降为 P1 并提示，需人工判断；SOE-008 的出处豁免是整句范围（exempt_context），
     与医院 HOS-003（只看命中分句与前一分句）口径不一致。
 10. Markdown 表格中姓名列默认报 P1、有处分或安置等敏感列时报 P0，无姓名类表头或非 Markdown 表格的姓名仍可能漏报。锚点之后由“、”（名单语境下还有“，”）和连词“和、与、及、同、跟”连接的并列链：只要链中任一项已识别，链上其余姓氏开头的 2～4 字项（含与常用词同形的、复姓的）一律登记进姓名表并遮蔽，首项未识别而后项识别时回溯登记首项（宁可多遮，“单亲”“杜鹃花”可能被遮成〔姓名N〕）；边界：整条链上没有任何一项被识别时不登记；并列链之外的同形名、无锚点的姓名仍识别不了；同一锚点下的并列姓名合并成一条（摘录含全部占位符）。姓名表覆盖全部隐私规则，不分文书类型（是否报出仍按文书类型）。

用法：
    python scripts/soe_check.py <文件> [--type 文书] [--external] [--as-of YYYY-MM-DD] [--json] [--strict]
    python scripts/soe_check.py --list-rules

输入 .txt、.md、.docx（docx 需要 python-docx），遇到单独成行的【起草说明】即停止读取。
输出字段与 gongwen_lint.py 一致（file、doc_type、char_count、summary、issues），可以并入核稿意见。
退出码：0 正常；--strict 且存在 P0 时为 1；输入错误（含共享模块缺失）为 2。
只依赖标准库；正则规则在同目录的 soe_rules.json 中，修改规则不必改代码。不访问网络，不写任何文件。
"""
from __future__ import annotations

import argparse
import calendar
import datetime as _dt
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Sequence, Set, Tuple

VERSION = "1.3.6"
_HERE = Path(__file__).resolve().parent
RULES_PATH = _HERE / "soe_rules.json"
LEVELS = ("P0", "P1", "P2")

# 【起草说明】分界行，与 gongwen_lint.py、fact_diff.py 的写法一致
DRAFT_NOTE_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:(?:\*\*|__)\s*)?【起草说明】")

Lines = Sequence[Tuple[int, str]]


class InputError(Exception):
    """输入错误，退出码 2。"""


# ---------------------------------------------------------------------------
# 共享模块：实名识别（gw_names）与分句豁免、程序倒置（gw_clause）。缺文件或数据损坏时按输入错误退出，不静默降级
# ---------------------------------------------------------------------------

def _load_shared(stem: str) -> Any:
    """按文件路径加载同目录的共享模块；模块名按 skill 目录区分，避免同一进程里先后加载多个行业引擎时串用缓存。"""
    path = _HERE / f"{stem}.py"
    if not path.is_file():
        raise InputError(f"缺少 scripts/{stem}.py（共享模块），请重新安装本包或运行 tools/sync_shared.py")
    name = f"_gw_{_HERE.parent.name}_{stem}"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, str(path))
        if spec is None or spec.loader is None:
            raise InputError(f"无法加载共享模块 scripts/{stem}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:  # 模块损坏
            sys.modules.pop(name, None)
            raise InputError(f"共享模块 scripts/{stem}.py 无法加载：{exc}") from exc
    return mod


_SHARED: Dict[str, Any] = {}


def _shared() -> Tuple[Any, Any, Any]:
    """返回 (gw_names, gw_clause, 姓名数据)。数据文件缺失或损坏抛 InputError。"""
    gn = _load_shared("gw_names")
    gc = _load_shared("gw_clause")
    lex = _SHARED.get("lex")
    if lex is None:
        try:
            lex = gn.load_lexicon()
        except gn.LexiconError as exc:
            raise InputError(str(exc)) from exc
        _SHARED["lex"] = lex
    return gn, gc, lex


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
    external_only: bool = False
    exempt: Optional[Pattern[str]] = None            # 整句窗口
    exempt_match: Optional[Pattern[str]] = None      # 命中文字本身
    exempt_clause: Optional[Pattern[str]] = None     # 命中所在分句
    exempt_lead: Optional[Pattern[str]] = None       # 冒号前的引导分句
    exempt_before: Optional[Pattern[str]] = None     # 命中前同一分句内 prefix_window 个字
    exempt_chain: Optional[Pattern[str]] = None      # 命中所在分句并入顿号并列的前面各项（禁止类词放这里）
    exempt_dispose: Optional[Pattern[str]] = None    # 处置类自带词（命中所在分句）；就近有如实声明时不适用
    later_hint: bool = False                         # 规则带处置类、出处类豁免：后续分句里有针对该做法的处置、出处词时报出带提示，P0 降为 P1
    later_kinds: Tuple[str, ...] = ()                # 规则实际配置的豁免类别（dispose、source）：提示与降级只看这些类别的词
    prefix_window: int = 8
    exempt_windows: Dict[str, Pattern[str]] = field(default_factory=dict)  # 交给 gw_clause.is_exempt 的窗口正则
    exempt_windows_declared: Dict[str, Pattern[str]] = field(default_factory=dict)  # 同上，去掉处置类（就近有如实声明时用）
    detector: Optional[str] = None                   # "names"：锚点 + 候选 + 打分的姓名识别
    low_level: Optional[str] = None                  # 低置信（总分 = 5）命中的级别
    anchors: List[Any] = field(default_factory=list)
    hit_examples: List[str] = field(default_factory=list)
    miss_examples: List[str] = field(default_factory=list)
    level_examples: List[Dict[str, str]] = field(default_factory=list)  # [{"text": 例句, "level": 应得级别}]

    def applies(self, doc_type: Optional[str]) -> bool:
        """types 为空时所有文书都查；非空时只在指定文书类型下查。"""
        if not self.types:
            return True
        return doc_type in self.types


@dataclass
class RuleSet:
    types: Tuple[str, ...]
    external_types: Tuple[str, ...]
    rules: List[Rule]
    procedural: Dict[str, Rule]
    inversion: Optional[Dict[str, Any]] = None  # 程序倒置组合判定的配置（procedure_inversion）


# ---------------------------------------------------------------------------
# 规则加载
# ---------------------------------------------------------------------------

def _compile(pattern: Optional[str], rid: str, name: str) -> Optional[Pattern[str]]:
    if not pattern:
        return None
    _gn, gc, _lex = _shared()
    # 豁免正则里的 <<DISPOSE>>、<<SOURCE>>、<<PROHIBIT>> 由共享模块代入，避免在规则文件里重复写长词表
    for token, value in (("<<DISPOSE>>", gc.DISPOSE), ("<<SOURCE>>", gc.SOURCE), ("<<PROHIBIT>>", gc.PROHIBIT_WORDS)):
        pattern = pattern.replace(token, value)
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise InputError(f"规则 {rid} 的 {name} 不是合法的正则表达式：{exc}") from exc


def _union(a: Optional[Pattern[str]], b: Pattern[str]) -> Pattern[str]:
    """两个豁免正则合并成“任一命中”。"""
    return b if a is None else re.compile(f"(?:{a.pattern})|(?:{b.pattern})")


def _level(value: Any, rid: str) -> str:
    if value not in LEVELS:
        raise InputError(f"规则 {rid} 的级别 {value!r} 无效，只能是 P0、P1、P2")
    return str(value)


def _build_rule(item: Dict[str, Any], procedural: bool) -> Rule:
    rid = str(item.get("id") or "").strip()
    if not rid:
        raise InputError("规则缺少 id")
    for key in ("category", "gate", "message", "basis"):
        if not item.get(key):
            raise InputError(f"规则 {rid} 缺少 {key}")
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
        external_only=bool(item.get("external_only")),
        exempt=_compile(item.get("exempt_context"), rid, "exempt_context"),
        exempt_match=_compile(item.get("exempt_match"), rid, "exempt_match"),
        exempt_clause=_compile(item.get("exempt_clause"), rid, "exempt_clause"),
        exempt_lead=_compile(item.get("exempt_lead"), rid, "exempt_lead"),
        exempt_before=_compile(item.get("exempt_before"), rid, "exempt_before"),
        exempt_chain=_compile(item.get("exempt_chain"), rid, "exempt_chain"),
        exempt_dispose=_compile(item.get("exempt_dispose"), rid, "exempt_dispose"),
        prefix_window=int(item.get("prefix_window") or 8),
        later_hint=any(isinstance(v, str) and ("<<DISPOSE>>" in v or "<<SOURCE>>" in v)
                       for k, v in item.items() if k.startswith("exempt")),
        later_kinds=tuple(kind for kind, token in (("dispose", "<<DISPOSE>>"), ("source", "<<SOURCE>>"))
                          if any(isinstance(v, str) and token in v for k, v in item.items() if k.startswith("exempt"))),
        detector=item.get("detector") or None,
        low_level=_level(item["low_level"], rid) if item.get("low_level") else None,
        hit_examples=list(item.get("hit_examples") or []),
        miss_examples=list(item.get("miss_examples") or []),
        level_examples=list(item.get("level_examples") or []),
    )
    for window, attr in (("sentence", "exempt"), ("clause", "exempt_clause"), ("chain", "exempt_chain"),
                         ("lead", "exempt_lead"), ("prefix", "exempt_before")):
        pattern = getattr(rule, attr)
        if pattern is not None:
            rule.exempt_windows[window] = pattern
    rule.exempt_windows_declared = dict(rule.exempt_windows)
    if rule.exempt_dispose is not None:
        rule.exempt_windows["clause"] = _union(rule.exempt_windows.get("clause"), rule.exempt_dispose)
    if not procedural:
        rule.regex = _compile(item.get("pattern"), rid, "pattern")
        if rule.detector not in (None, "names"):
            raise InputError(f"规则 {rid} 的 detector 只能是 names")
        if rule.detector == "names":
            gn, _gc, lex = _shared()
            try:
                rule.anchors = gn.compile_anchors(item.get("name_anchors"), lex)
            except gn.LexiconError as exc:
                raise InputError(f"规则 {rid} 的 name_anchors 有误：{exc}") from exc
            if not rule.anchors:
                raise InputError(f"规则 {rid} 的 detector 为 names，但没有 name_anchors")
        elif rule.regex is None:
            raise InputError(f"规则 {rid} 缺少 pattern")
    return rule


def load_rules(path: Path = RULES_PATH) -> RuleSet:
    """读取规则文件。文件缺失或格式错误时抛出 InputError。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InputError(f"找不到规则文件：{path}") from exc
    except (OSError, ValueError) as exc:
        raise InputError(f"规则文件无法读取或不是合法的 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise InputError("规则文件顶层必须是对象")
    types = tuple(data.get("types") or ())
    external_types = tuple(data.get("external_types") or ())
    rules = [_build_rule(item, False) for item in data.get("rules") or []]
    procedural_list = [_build_rule(item, True) for item in data.get("procedural") or []]
    ids = [r.id for r in rules + procedural_list]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise InputError(f"规则 id 重复：{'、'.join(duplicated)}")
    for rule in rules + procedural_list:
        unknown = [t for t in rule.types if t not in types]
        if unknown:
            raise InputError(f"规则 {rule.id} 的 types 含未登记的文书类型：{'、'.join(unknown)}")
    missing = [rid for rid in PROCEDURAL_IDS if rid not in {r.id for r in procedural_list}]
    if missing:
        raise InputError(f"规则文件缺少函数检查的登记：{'、'.join(missing)}")
    inversion = data.get("procedure_inversion")
    if inversion is not None:
        inversion = _check_inversion_cfg(inversion, rules, types)
    return RuleSet(types=types, external_types=external_types, rules=rules,
                   procedural={r.id: r for r in procedural_list}, inversion=inversion)


INVERSION_KEYS = ("exec", "exec_neg", "prior_ok", "req", "other_obj", "decl", "normalize",
                  "exec_sign", "exec_done", "exec_start", "exec_dated", "post_obj", "decl_neg")

# 程序倒置 P1 的说明文案按 gw_clause.find_inversions 给出的 reason_code 选择，避免 P1 配着与原因矛盾的文字
INVERSION_MESSAGES = {
    "same_sentence": "同一句里既写了“已执行”又写了“提请审议”，请核实是否先执行后上会（组合判定仅作提示）",
    "normalize": "出现“追认”“补办”字样，请核实是否先执行后上会，写清已执行情况、原因和责任",
    "declared": "已如实写明程序倒置，请确认写清已执行情况、原因和责任，由会议决定后续处理；不要写成追认或补办",
    "other_item": "提请事项可能与已执行事项不同（如二期、续签），请核实提请事项本身没有先行实施",
    "adjacent": "“已执行”与“提请审议”在相邻两句，请核实是否先执行后上会",
    "weak_exec": "“于X月开工、投入使用”等写法表明已执行，请核实是否先执行后上会",
}


def _check_inversion_cfg(cfg: Any, rules: List[Rule], types: Sequence[str]) -> Dict[str, Any]:
    """校验顶层 procedure_inversion：rule_id 必须是已登记的正则规则，各正则能编译，types 必须是已登记的文书类型。"""
    if not isinstance(cfg, dict):
        raise InputError("procedure_inversion 必须是对象")
    rid = str(cfg.get("rule_id") or "")
    if rid not in {r.id for r in rules}:
        raise InputError(f"procedure_inversion 的 rule_id {rid!r} 不是已登记的规则")
    unknown = [t for t in (cfg.get("types") or []) if t not in types]
    if unknown:
        raise InputError(f"procedure_inversion 的 types 含未登记的文书类型：{'、'.join(unknown)}")
    for key in INVERSION_KEYS:
        val = cfg.get(key)
        if val is None:
            continue
        if not isinstance(val, str):
            raise InputError(f"procedure_inversion 的 {key} 必须是字符串")
        try:
            re.compile(val)
        except re.error as exc:
            raise InputError(f"procedure_inversion 的 {key} 不是合法的正则表达式：{exc}") from exc
    return cfg


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
        lines = split_lines(text)
    elif suffix == ".docx":
        lines = _read_docx(path)
    else:
        raise InputError(f"不支持的文件类型：{path.suffix or '无扩展名'}。只支持 .txt、.md、.docx。")
    return cut_at_note(lines)


def split_lines(text: str) -> List[Tuple[int, str]]:
    return list(enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), start=1))


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
            # 表格按行转成 Markdown 风格的一行，便于台账检查
            for row in child.iter(qn("w:tr")):
                cells = []
                for cell in row.iter(qn("w:tc")):
                    texts = [Paragraph(p_el, document).text for p_el in cell.iter(p_tag)]
                    cells.append(" ".join(t for t in texts if t).replace("|", "／"))
                number += 1
                lines.append((number, "| " + " | ".join(cells) + " |"))
    return _insert_docx_separators(lines)


def _insert_docx_separators(lines: List[Tuple[int, str]]) -> List[Tuple[int, str]]:
    """docx 表格的第一行之后补一行分隔行，使其能按 Markdown 表格解析。"""
    out: List[Tuple[int, str]] = []
    previous_is_row = False
    for number, text in lines:
        is_row = text.startswith("| ")
        out.append((number, text))
        if is_row and not previous_is_row:
            columns = text.count("|") - 1
            out.append((number, "|" + "---|" * max(columns, 1)))
        previous_is_row = is_row
    return out


def cut_at_note(lines: Lines) -> List[Tuple[int, str]]:
    """只保留【起草说明】之前的正文。"""
    kept: List[Tuple[int, str]] = []
    for number, text in lines:
        if DRAFT_NOTE_RE.match(text):
            break
        kept.append((number, text))
    return kept


# ---------------------------------------------------------------------------
# 公共小工具
# ---------------------------------------------------------------------------

def _clip(text: str, limit: int = 40) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "……"


def _context(text: str, start: int, end: int, width: int = 12) -> str:
    return text[max(0, start - width):min(len(text), end + width)].strip()


def _issue(rule: Rule, level: str, line: int, excerpt: str, context: str = "",
           message: Optional[str] = None, suggestion: Optional[str] = None, hint: bool = False) -> Dict[str, Any]:
    if hint:      # 命中之后的分句里有处置、出处词：收缩后它们不再豁免，提示可能是已写明否决、整改或出处的句子
        base = rule.suggestion if suggestion is None else suggestion
        suggestion = (base.rstrip("。；") + "；" if base else "") + _shared()[1].LATER_HINT + "。"
    data: Dict[str, Any] = {
        "id": rule.id,
        "level": level,
        "category": rule.category,
        "line": line,
        "excerpt": excerpt,
        "message": message or rule.message,
        "suggestion": rule.suggestion if suggestion is None else suggestion,
        "basis": rule.basis,
        "check": "soe",
        "gate": rule.gate,
    }
    if context and context != excerpt:
        data["context"] = context
    return data


def _first_text_line(lines: Lines) -> Tuple[int, str]:
    for number, text in lines:
        if text.strip():
            return number, _clip(text, 30)
    return 1, "（全文）"


CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9}


def to_int(token: str) -> Optional[int]:
    """把阿拉伯数字或一百以内的汉字数字转成整数。"""
    token = token.strip()
    if token.isdigit():
        return int(token)
    if not token or any(ch not in CN_DIGITS and ch != "十" for ch in token):
        return None
    if "十" in token:
        tens, _, ones = token.partition("十")
        tens_value = CN_DIGITS.get(tens, None) if tens else 1
        ones_value = CN_DIGITS.get(ones, None) if ones else 0
        if tens_value is None or ones_value is None:
            return None
        return tens_value * 10 + ones_value
    if len(token) == 1:
        return CN_DIGITS[token]
    return None


NUM = r"([0-9]+|[零〇一二两三四五六七八九十]+)"


# ---------------------------------------------------------------------------
# 正则规则与姓名规则
# ---------------------------------------------------------------------------

def _is_exempt(rule: Rule, text: str, start: int, end: int, declared: bool = False) -> bool:
    """按 gw_clause 的统一窗口判断豁免：sentence、clause、chain、lead、prefix 任一窗口搜到豁免词即豁免。
    declared=True（程序倒置规则、命中处就近有如实声明）时不适用处置类豁免。"""
    windows = rule.exempt_windows_declared if declared else rule.exempt_windows
    if not windows:
        return False
    _gn, gc, _lex = _shared()
    return bool(gc.is_exempt(text, start, end, windows, rule.prefix_window))


def _rule_matches(rule: Rule, text: str, decl: Any = None, line: int = 0):
    """逐个产出通过全部豁免检查的命中。

    豁免分窗口（切分与窗口定义见 gw_clause.py）：exempt_context 看命中所在整句，只留给“出处、证据在相邻分句”的少数规则；
    exempt_clause 只看命中所在分句（含命中跨越的各分句）；exempt_lead 看分句紧跟冒号时冒号前的引导分句（“严禁下列行为：……”）；
    exempt_before 只看命中前同一分句内最近 prefix_window 个字（用于“不包含任何未公开信息”这类前置否定）。
    """
    assert rule.regex is not None
    for match in rule.regex.finditer(text):
        if match.end() == match.start():
            continue
        if rule.exempt_match and rule.exempt_match.search(match.group(0)):
            continue
        near = bool(decl is not None and decl.near_declared(line, match.start()))
        if _is_exempt(rule, text, match.start(), match.end(), declared=near):
            continue
        yield match


def _rule_level(rule: Rule, external: bool) -> str:
    return rule.external_level if (external and rule.external_level) else rule.level


def _applicable(rule: Rule, doc_type: Optional[str], external: bool) -> bool:
    return rule.applies(doc_type) and not (rule.external_only and not external)


def _active_rules(ruleset: RuleSet, doc_type: Optional[str], external: bool) -> List[Rule]:
    """有 pattern 的正则规则。"""
    return [r for r in ruleset.rules if r.regex is not None and _applicable(r, doc_type, external)]


def _name_rules(ruleset: RuleSet) -> List[Rule]:
    """用锚点识别姓名的规则（不论文书类型，姓名表要覆盖全部：别处写的姓名在任何输出里都要遮蔽）。"""
    return [r for r in ruleset.rules if r.detector == "names"]


def check_regex(lines: Lines, doc_type: Optional[str], external: bool, ruleset: RuleSet) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    inversion_id = (ruleset.inversion or {}).get("rule_id")
    _gn, gc, _lex = _shared()
    # 程序倒置规则（SOE-001）的声明判断：命中处就近有如实声明时不适用处置类豁免；就近有声明且无追认、补办时 P0 降 P1
    decl = gc.Declaration([t for _n, t in lines], ruleset.inversion) if ruleset.inversion else None
    for rule in _active_rules(ruleset, doc_type, external):
        level = _rule_level(rule, external)
        is_inv = decl is not None and rule.id == inversion_id
        for idx, (number, text) in enumerate(lines):
            for match in _rule_matches(rule, text, decl if is_inv else None, idx):
                lv = decl.adjust(level, idx, match.start()) if is_inv else level
                # 后续分句里有针对该做法的处置、出处词：不再豁免，但 P0 降为 P1（仍报出要人看），并追加提示
                later = rule.later_hint and gc.later_exemption_words(text, match.start(), match.end(), rule.later_kinds)
                # 程序倒置规则：就近写了追认、补办的，本身就是在补手续，不因后文的处置词降级
                if later and lv == "P0" and not (is_inv and decl.near_normalized(idx, match.start())):
                    lv = "P1"
                issues.append(_issue(rule, lv, number, _clip(match.group(0)),
                                     _context(text, match.start(), match.end()), hint=later))
    return issues


NAME_TAIL = 8  # 姓名规则的摘录：锚点 + 姓名 + 右侧最多 8 字


def scan_names(lines: Lines, ruleset: RuleSet):
    """逐行识别姓名，返回全文姓名表、逐行命中及需要人工核对的表格行。

    姓名表覆盖所有姓名规则的命中（含因豁免、文书类型不适用而没有报出的），按全文首次出现的顺序编号；代称不进表。
    """
    gn, _gc, lex = _shared()
    texts = [text for _number, text in lines]
    organizations = gn.organization_names(texts, lex)
    table = gn.NameTable()
    table_rows = gn.find_table_names(texts, lex, "soe")
    per_line: Dict[int, List[Tuple[Rule, Any]]] = {}
    unknown_rows = []
    rules = _name_rules(ruleset)
    by_id = {rule.id: rule for rule in rules}
    for idx, (_number, text) in enumerate(lines):
        entries = [(rule, hit) for rule in rules
                   for hit in gn.find_names(text, rule.anchors, lex, organizations)]
        row = table_rows.get(idx)
        if row:
            discipline = any(re.search(r"处分|违纪|诫勉|问责", label) for label in row.headers)
            rule = by_id.get("SOE-022" if discipline else "SOE-023")
            if rule is not None:
                for hit in row.hits:
                    gn.grade_abbreviation(hit, lex, organizations)
                    entries.append((rule, hit))
                if row.unrecognized:
                    unknown_rows.append((_number, rule))
        if entries:
            entries.sort(key=lambda e: (e[1].start, e[1].end))
            per_line[idx] = entries
            table.add_hits(hit for _, hit in entries if not (hit.table_only and hit.anchor_start < 0))
    table.add_table_masks(table_rows.values())
    return table, per_line, unknown_rows


def check_names(lines: Lines, doc_type: Optional[str], external: bool,
                per_line: Dict[int, List[Tuple[Rule, Any]]], table: Any) -> List[Dict[str, Any]]:
    """姓名规则的报出：高置信（总分 >= 6）用规则级别，低置信（= 5）用 low_level；代称不报。"""
    gn, _gc, _lex = _shared()
    issues: List[Dict[str, Any]] = []
    for idx, entries in per_line.items():
        number, text = lines[idx]
        # 同一规则、同一锚点下的并列姓名（“名单：张三、李四”）共用一条摘录：从锚点读到最后一个姓名再加右侧上下文，
        # 这样各姓名的摘录完全相同，由 merge_issues 合并成一条并带 count
        group_end: Dict[Tuple[str, int], int] = {}
        group_flags: Dict[Tuple[str, int, str], set] = {}
        reportable = []
        for rule, hit in entries:
            key = (rule.id, hit.anchor_start)
            if hit.anchor_start >= 0:
                group_end[key] = max(group_end.get(key, 0), hit.end)
            if hit.pseudo or hit.table_only or not _applicable(rule, doc_type, external):
                continue
            if hit.anchor_start >= 0 and _is_exempt(rule, text, hit.start, hit.end):
                continue
            high = _rule_level(rule, external)
            level = hit.org_level or (high if hit.score >= gn.SCORE_HIGH else rule.low_level or high)
            reportable.append((rule, hit, level))
            if hit.anchor_start >= 0:
                group_flags.setdefault((*key, level), set()).add(hit.org_hint)
        for rule, hit, level in reportable:
            if hit.anchor_start < 0:
                level = hit.org_level or ("P0" if hit.score >= gn.SCORE_HIGH else "P1")
                issues.append(_issue(rule, level, number, table.placeholder(hit.name), message=hit.org_hint or "表格姓名列出现真实姓名"))
                continue
            a0 = hit.anchor_start if 0 <= hit.anchor_start <= hit.start else hit.start
            key = (rule.id, hit.anchor_start)
            end = group_end[key]
            flags = group_flags[(*key, level)]
            message, suggestion = None, None
            hints = sorted(flags - {""})
            if hints:
                message = "；".join(hints)
                if "" in flags:
                    message = f"{rule.message}；部分对象{message}"
                suggestion = "核对处分对象或名单项是否为个人，确为实名时按规定遮蔽"
            issues.append(_issue(rule, level, number, text[a0:max(end, hit.end) + NAME_TAIL].strip(),
                                 message=message, suggestion=suggestion))
    return issues


def check_inversions(lines: Lines, doc_type: Optional[str], external: bool, ruleset: RuleSet,
                     issues: List[Dict[str, Any]]) -> None:
    """程序倒置组合判定（gw_clause.find_inversions），与同一行已有的同规则正则命中合并：取较高级别，保留正则那条的摘录。"""
    cfg = ruleset.inversion
    if not cfg:
        return
    types = cfg.get("types") or []
    if types and doc_type not in types:
        return
    _gn, gc, _lex = _shared()
    rule = next(r for r in ruleset.rules if r.id == cfg["rule_id"])
    found = gc.find_inversions([text for _n, text in lines], cfg)
    regex_hits = [i for i in issues if i["id"] == rule.id]  # 只与正则命中合并；组合判定之间互不合并
    for inv in found:
        number = lines[inv["line"] - 1][0]
        same = [i for i in regex_hits if i["line"] == number]
        if same:
            for item in same:
                if LEVELS.index(inv["level"]) < LEVELS.index(item["level"]):
                    item["level"] = inv["level"]
            continue
        text = lines[inv["line"] - 1][1]
        message = rule.message
        if inv["level"] != rule.level:
            detail = INVERSION_MESSAGES.get(inv.get("reason_code", ""), inv["reason"])
            message = f"{rule.message}（组合判定：{detail}）"
        issues.append(_issue(rule, inv["level"], number, inv["excerpt"],
                             _context(text, inv["start"], inv["end"]), message=message))


# ---------------------------------------------------------------------------
# 遮蔽：所有规则（含函数检查）输出 excerpt、context、message 前，按全文姓名表把姓名换成〔姓名N〕
# ---------------------------------------------------------------------------

def mask_issues(issues: List[Dict[str, Any]], lines: Lines, table: Any) -> None:
    if not len(table):
        return
    by_number: Dict[int, str] = {}
    for number, text in lines:
        by_number.setdefault(number, text)
    for issue in issues:
        text = by_number.get(issue["line"])
        for key in ("excerpt", "context"):
            if issue.get(key):
                issue[key] = table.mask_excerpt(issue[key], text)
        issue["message"] = table.mask(issue["message"])
        if issue.get("context") == issue.get("excerpt"):
            issue.pop("context", None)


# ---------------------------------------------------------------------------
# 函数检查
# ---------------------------------------------------------------------------

YITI_ELEMENTS = (
    ("背景和依据", re.compile(r"背景|依据|缘由|必要性"), "P1"),
    ("方案", re.compile(r"方案"), "P1"),
    ("需决策事项", re.compile(r"(?:需|提请|请求|拟请|请)[^。\n]{0,12}?(?:决策|审议|研究讨论|决定|审定)|决策事项|审议事项"), "P1"),
    ("前置程序完成情况", re.compile(r"前置|合法合规审查|合规审查|法律审核|法律意见|职代会|职工代表大会|可行性研究|尽职调查|资产评估|专家论证"), "P1"),
    ("风险分析", re.compile(r"风险"), "P2"),
)
OPTION_RE = re.compile(r"方案[一二三四五1-5ＡＢA-Ba-b甲乙丙]|备选方案|比选|比较|两个方案|两种方案|多个方案|几个方案")


def check_yiti(lines: Lines, ruleset: RuleSet) -> List[Dict[str, Any]]:
    text = "\n".join(t for _n, t in lines)
    line, title = _first_text_line(lines)
    issues: List[Dict[str, Any]] = []
    rule = ruleset.procedural["SOE-101"]
    for name, regex, level in YITI_ELEMENTS:
        if not regex.search(text):
            issues.append(_issue(rule, level, line, title, message=f"议题材料缺少要件：{name}"))
    option_rule = ruleset.procedural["SOE-102"]
    if "方案" in text and not OPTION_RE.search(text):
        issues.append(_issue(option_rule, option_rule.level, line, title))
    return issues


YIAN_ELEMENTS = (
    ("提请审议事项", re.compile(r"请审议|提请审议|请予审议|提请董事会审议|提请审议事项")),
    ("决策程序履行情况", re.compile(r"前置|党委|专门委员会|委员会审议|决策程序")),
)


def check_yian(lines: Lines, ruleset: RuleSet) -> List[Dict[str, Any]]:
    text = "\n".join(t for _n, t in lines)
    line, title = _first_text_line(lines)
    rule = ruleset.procedural["SOE-103"]
    return [_issue(rule, rule.level, line, title, message=f"董事会议案缺少要件：{name}")
            for name, regex in YIAN_ELEMENTS if not regex.search(text)]


SHOULD_RE = re.compile(r"应(?:出席|到会|到)(?:会议的?)?(?:董事)?\s*" + NUM + r"\s*(?:人|名|位)")
ACTUAL_RE = re.compile(r"实(?:际)?(?:出席|到会|到)(?:会议的?)?(?:董事)?\s*" + NUM + r"\s*(?:人|名|位)")
# 票数写法：“同意7票，反对0票，弃权0票”“同意票7票，反对票0票”“同意：7票；反对：0票；弃权：0票”；弃权可省略
_VOTE_SEP = r"\s*[，,、；;]?\s*"
_VOTE_COLON = r"\s*[：:]?\s*"
VOTE_RE = re.compile(r"同意(?:票)?" + _VOTE_COLON + NUM + r"\s*票" + _VOTE_SEP + r"反对(?:票)?" + _VOTE_COLON + NUM
                     + r"\s*票(?:" + _VOTE_SEP + r"弃权(?:票)?" + _VOTE_COLON + NUM + r"\s*票)?")
# 上市公司公告常见的写法：7票同意，0票反对，0票弃权
VOTE_RE_ALT = re.compile(NUM + r"\s*票\s*同意" + _VOTE_SEP + NUM + r"\s*票\s*反对(?:" + _VOTE_SEP
                         + NUM + r"\s*票\s*弃权)?")
RECUSE_COUNT_RE = re.compile(r"回避(?:表决)?[^。；\n]{0,6}?" + NUM + r"\s*(?:人|名|位)|" + NUM
                             + r"\s*(?:人|名|位)(?:关联)?(?:董事)?回避")
RECUSE_RE = re.compile(r"回避")
PASSED_RE = re.compile(r"审议通过|通过了|获得通过|予以通过|表决通过")
FAILED_RE = re.compile(r"未通过|未获通过|不予通过|否决|未审议通过")
UNANIMOUS_RE = re.compile(r"全票|一致通过|一致同意")


def _recuse_count(block: str) -> Tuple[bool, Optional[int]]:
    if not RECUSE_RE.search(block):
        return False, 0
    match = RECUSE_COUNT_RE.search(block)
    if match:
        token = next((g for g in match.groups() if g), None)
        if token is not None:
            return True, to_int(token)
    # “关联董事张某、李某回避表决”：按顿号数姓名
    named = re.search(r"(?:关联)?董事([^。；，,\n董]{1,20}?)回避", block)
    if named:
        names = [n for n in re.split(r"[、，,和及]", named.group(1)) if n.strip()]
        if names:
            return True, len(names)
    return True, None


def check_resolution(lines: Lines, ruleset: RuleSet) -> List[Dict[str, Any]]:
    rule = ruleset.procedural["SOE-104"]
    issues: List[Dict[str, Any]] = []
    should: Optional[Tuple[int, int, str]] = None
    actual: Optional[Tuple[int, int, str]] = None
    for number, text in lines:
        if should is None:
            m = SHOULD_RE.search(text)
            if m and to_int(m.group(1)) is not None:
                should = (number, to_int(m.group(1)) or 0, m.group(0))
        if actual is None:
            m = ACTUAL_RE.search(text)
            if m and to_int(m.group(1)) is not None:
                actual = (number, to_int(m.group(1)) or 0, m.group(0))
    first_line, title = _first_text_line(lines)
    if should is None or actual is None:
        issues.append(_issue(rule, "P1", first_line, title,
                             message="决议未写明应出席和实际出席董事人数，无法核对表决",
                             suggestion="按会议记录写明应出席、实际出席（含委托出席）人数；记录没有的不强行补，在起草说明“待补”一行列出"))
    else:
        n_should, n_actual = should[1], actual[1]
        if n_actual > n_should:
            issues.append(_issue(rule, "P0", actual[0], actual[2],
                                 message=f"实际出席 {n_actual} 人多于应出席 {n_should} 人"))
        elif n_should and n_actual * 2 <= n_should:
            issues.append(_issue(rule, "P0", actual[0], actual[2],
                                 message=f"实际出席 {n_actual} 人未超过应出席 {n_should} 人的半数，会议不能举行",
                                 suggestion="核对出席和委托出席情况；人数确实不足的，不写“会议合法有效”，不写“审议通过”"))
    votes_found = False
    block_start = 0
    flat: List[Tuple[int, str]] = list(lines)
    for index, (number, text) in enumerate(flat):
        matches = sorted(list(VOTE_RE.finditer(text)) + list(VOTE_RE_ALT.finditer(text)),
                         key=lambda item: item.start())
        for match in matches:
            votes_found = True
            g_yes, g_no, g_abstain = match.groups()
            yes, no = to_int(g_yes), to_int(g_no)
            abstain = to_int(g_abstain) if g_abstain is not None else 0
            if yes is None or no is None or abstain is None:
                continue
            block_lines = [t for _n, t in flat[block_start:index]] + [text]
            block = "\n".join(block_lines)
            total = yes + no + abstain
            has_recuse, recused = _recuse_count(block)
            excerpt = match.group(0)
            if actual is not None:
                if has_recuse and recused is None:
                    if total > actual[1]:
                        issues.append(_issue(rule, "P0", number, excerpt,
                                             message=f"票数之和 {total} 超过实际出席人数 {actual[1]}"))
                    else:
                        issues.append(_issue(rule, "P2", number, excerpt,
                                             message="有董事回避表决，但没有写明回避人数，无法核对票数",
                                             suggestion="写明回避的董事（职务或“某董事”）和人数"))
                else:
                    expected = actual[1] - (recused or 0)
                    if total != expected:
                        detail = f"实际出席 {actual[1]} 人" + (f"、回避 {recused} 人" if recused else "")
                        issues.append(_issue(rule, "P0", number, excerpt,
                                             message=f"票数之和 {total} 与应参加表决的人数 {expected} 不符（{detail}）"))
            if UNANIMOUS_RE.search(block) and (no or abstain):
                issues.append(_issue(rule, "P0", number, excerpt,
                                     message="写了“全票”“一致”，但表决结果有反对或弃权票"))
            passed = bool(PASSED_RE.search(block)) and not FAILED_RE.search(block)
            # 回避人数不明时无法确定基数，只报上面的 P2，不判是否通过
            if should is not None and passed and not (has_recuse and recused is None):
                base = should[1] - (recused or 0)
                if base and yes * 2 <= base:
                    issues.append(_issue(rule, "P0", number, excerpt,
                                         message=f"同意 {yes} 票未超过{'无关联关系董事' if has_recuse else '全体董事'} {base} 人的半数，不能写“通过”",
                                         suggestion="无回避的，同意票须超过全体董事的半数；有关联董事回避的，同意票须超过无关联关系董事人数的半数"
                                                    "（《公司法》第一百三十九条、第一百八十五条）；确未通过的写“未通过”；章程规定更高比例的按章程"))
            if has_recuse and recused and actual is not None and passed and actual[1] - recused < 3:
                issues.append(_issue(rule, "P1", number, excerpt,
                                     message=f"回避后出席的无关联关系董事只有 {actual[1] - recused} 人，不足三人",
                                     suggestion="出席董事会会议的无关联关系董事人数不足三人的，该事项应提交股东会审议"
                                                "（《公司法》第一百三十九条、第一百八十五条）；国有独资公司按出资人机构的规定"))
            block_start = index + 1
    if not votes_found:
        issues.append(_issue(rule, "P1", first_line, title,
                             message="决议未写表决结果",
                             suggestion="每项议案写“表决结果：同意X票，反对X票，弃权X票”；记录没有的不强行补，在起草说明“待补”一行列出"))
    return issues


TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
ALLOWED_STATUS = ("已完成", "按计划推进", "滞后", "未启动", "持续推进")
EMPTY_CELL_RE = re.compile(r"^(?:|无|-|—|－|/|／|待补|暂无|【待补[^】]*】)$")
DATE_RE = re.compile(r"(\d{4})\s*[年\-./]\s*(\d{1,2})\s*(?:[月\-./]\s*(\d{1,2})\s*日?|月)?")
YEAR_END_RE = re.compile(r"(\d{4})\s*年\s*(?:底|末|年底|年末)")
REASON_RE = re.compile(r"原因|因|由于|受|待|尚未|未能|新时限|调整")


def parse_tables(lines: Lines) -> List[Tuple[List[str], List[Tuple[int, List[str]]]]]:
    """解析 Markdown 表格，返回 [(表头, [(行号, 单元格)])]。"""
    tables = []
    flat = list(lines)
    i = 0
    while i < len(flat) - 1:
        number, text = flat[i]
        if "|" in text and TABLE_SEP_RE.match(flat[i + 1][1]):
            header = _cells(text)
            rows: List[Tuple[int, List[str]]] = []
            j = i + 2
            while j < len(flat) and "|" in flat[j][1] and flat[j][1].strip():
                rows.append((flat[j][0], _cells(flat[j][1])))
                j += 1
            tables.append((header, rows))
            i = j
        else:
            i += 1
    return tables


def _cells(text: str) -> List[str]:
    stripped = text.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [c.strip().replace("**", "") for c in re.split(r"(?<!\\)\|", stripped)]


def _find_col(header: List[str], pattern: str) -> Optional[int]:
    regex = re.compile(pattern)
    for idx, name in enumerate(header):
        if regex.search(name):
            return idx
    return None


QUARTER_RE = re.compile(r"(?:(\d{4})\s*年\s*)?(?:第)?([一二三四1-4])\s*季度")
HALF_RE = re.compile(r"(?:(\d{4})\s*年\s*)?(上半年|年中|下半年|年底|年末|全年)")
MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(?:(\d{1,2})\s*日|底|末)?")
QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def _month_end(year: int, month: int) -> _dt.date:
    return _dt.date(year, month, calendar.monthrange(year, month)[1])


def parse_deadline(cell: str, default_year: Optional[int] = None) -> Optional[_dt.date]:
    """解析完成时限。没写年份的（如“8月31日”“二季度”“年底”）用 default_year 补齐；不给 default_year 时返回 None。"""
    end = YEAR_END_RE.search(cell)
    if end:
        return _dt.date(int(end.group(1)), 12, 31)
    m = DATE_RE.search(cell)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            return None
        if m.group(3):
            try:
                return _dt.date(year, month, int(m.group(3)))
            except ValueError:
                return None
        return _month_end(year, month)
    m = QUARTER_RE.search(cell)
    if m:
        year = int(m.group(1)) if m.group(1) else default_year
        quarter = to_int(m.group(2))
        if year is None or quarter not in QUARTER_END:
            return None
        month, day = QUARTER_END[quarter]
        return _dt.date(year, month, day)
    m = HALF_RE.search(cell)
    if m:
        year = int(m.group(1)) if m.group(1) else default_year
        if year is None:
            return None
        return _dt.date(year, 6, 30) if m.group(2) in ("上半年", "年中") else _dt.date(year, 12, 31)
    m = MONTH_DAY_RE.search(cell)
    if m and default_year is not None:
        month = int(m.group(1))
        if not 1 <= month <= 12:
            return None
        if m.group(2):
            try:
                return _dt.date(default_year, month, int(m.group(2)))
            except ValueError:
                return None
        return _month_end(default_year, month)
    return None


def check_ledger(lines: Lines, ruleset: RuleSet, as_of: _dt.date) -> List[Dict[str, Any]]:
    rule = ruleset.procedural["SOE-105"]
    issues: List[Dict[str, Any]] = []
    tables = [t for t in parse_tables(lines) if _find_col(t[0], r"状态") is not None]
    if not tables:
        line, title = _first_text_line(lines)
        return [_issue(rule, "P1", line, title, message="没有找到带“状态”列的 Markdown 表格",
                       suggestion="台账用 Markdown 表格，列见 references/templates/gaige-taizhang.md 第二部分")]
    for header, rows in tables:
        c_status = _find_col(header, r"状态")
        c_deadline = _find_col(header, r"完成时限|时限|完成时间|计划完成")
        c_evidence = _find_col(header, r"佐证|证明材料|成果材料|支撑材料")
        c_owner = _find_col(header, r"牵头|责任单位|责任部门")
        c_remark = _find_col(header, r"备注|原因")
        c_progress = _find_col(header, r"进展|完成情况")
        c_rate = _find_col(header, r"完成率|进度")
        for number, cells in rows:
            def cell(idx: Optional[int]) -> str:
                return cells[idx] if idx is not None and idx < len(cells) else ""
            status = cell(c_status)
            label = _clip(" | ".join(c for c in cells[:2] if c), 30) or status
            if not status:
                issues.append(_issue(rule, "P1", number, label, message="状态为空"))
                continue
            if "待核实" in status:
                continue
            if status not in ALLOWED_STATUS:
                issues.append(_issue(rule, "P1", number, status,
                                     message=f"状态“{status}”不在约定口径内（已完成、按计划推进、滞后、未启动、持续推进）",
                                     suggestion="按认定标准改为五种状态之一；完成比例写进“进展情况”"))
            if status == "已完成" and c_evidence is not None and EMPTY_CELL_RE.match(cell(c_evidence)):
                issues.append(_issue(rule, "P1", number, label, message="标为“已完成”，但没有佐证材料",
                                     suggestion="写明成果文件名称、文号或纪要期号；没有佐证的不标已完成"))
            deadline = parse_deadline(cell(c_deadline), as_of.year) if c_deadline is not None else None
            if deadline and deadline <= as_of and status not in ("已完成", "滞后"):
                passed_word = "已到" if deadline == as_of else "已过"
                issues.append(_issue(rule, "P1", number, f"{cell(c_deadline)}｜{status}",
                                     message=f"完成时限 {deadline.isoformat()} {passed_word}（统计截止 {as_of.isoformat()}），状态仍为“{status}”",
                                     suggestion="到期未完成的改为“滞后”，备注写原因和新的时限；确已完成的写“已完成”并附佐证"))
            if status == "滞后" and not REASON_RE.search(cell(c_remark) + cell(c_progress)):
                issues.append(_issue(rule, "P2", number, label, message="滞后任务没有写原因和新的时限"))
            if c_owner is not None and EMPTY_CELL_RE.match(cell(c_owner)):
                issues.append(_issue(rule, "P2", number, label, message="牵头部门为空"))
            if c_rate is not None:
                rate = re.search(r"(\d+(?:\.\d+)?)\s*[%％]", cell(c_rate))
                if rate and float(rate.group(1)) > 100:
                    issues.append(_issue(rule, "P1", number, cell(c_rate), message="完成率超过 100%"))
    return issues


ESG_ELEMENTS = (
    ("报告期", re.compile(r"报告期|报告时间范围|时间范围|报告周期|\d{4}年1月1日至")),
    ("报告范围", re.compile(r"报告范围|报告边界|组织范围|覆盖范围|本报告涵盖|涵盖范围|合并(?:财务)?报表范围")),
    ("编制依据", re.compile(r"编制依据|参照《|依据《|按照《|参考《|根据《")),
    ("数据来源和口径", re.compile(r"数据来源|数据说明|数据口径|统计口径|计算方法")),
)


def check_esg(lines: Lines, ruleset: RuleSet) -> List[Dict[str, Any]]:
    text = "\n".join(t for _n, t in lines)
    line, title = _first_text_line(lines)
    rule = ruleset.procedural["SOE-106"]
    return [_issue(rule, rule.level, line, title, message=f"缺少披露口径说明：{name}")
            for name, regex in ESG_ELEMENTS if not regex.search(text)]


MONEY_RE = re.compile(r"\d+(?:\.\d+)?\s*(亿元|万元|千元|元)")
# 制度标准金额（如“5000万元以上的投资须提交党委会前置研究”）是门槛，不是本事项的金额，不计入金额单位统计。
# 认定条件：金额后接“以上”“以下”“以内”（含“及以上”“（含）以上”），或金额前有“超过”“达到”“不足”；
# 并且所在句有“须”“应”“需”“规定”“标准”等规定性用语（“应收”“应付”“供应”“需求”等不算）。
STANDARD_AFTER_RE = re.compile(r"\s*(?:（含）|\(含\))?\s*及?(?:以上|以下|以内)")
STANDARD_BEFORE_RE = re.compile(r"(?:超过|达到|不足)\s*$")
NORMATIVE_RE = re.compile(r"须|需(?!求)|(?<![供相对反适响回呼答效])应(?![收付交税])|规定|标准")
SENTENCE_STOPS = "。！？!?"


def _sentence_at(text: str, start: int, end: int) -> str:
    """取 text 中包含 [start, end) 的那一句（以句号、问号、叹号为界，分号不断句）。"""
    left = max(text.rfind(ch, 0, start) for ch in SENTENCE_STOPS) + 1
    rights = [i for i in (text.find(ch, end) for ch in SENTENCE_STOPS) if i != -1]
    return text[left:min(rights) if rights else len(text)]


def is_standard_amount(text: str, m: "re.Match[str]") -> bool:
    """金额是否为制度规定的标准（门槛）金额。"""
    if not (STANDARD_AFTER_RE.match(text, m.end()) or STANDARD_BEFORE_RE.search(text, 0, m.start())):
        return False
    return bool(NORMATIVE_RE.search(_sentence_at(text, m.start(), m.end())))


def check_money_units(lines: Lines, ruleset: RuleSet) -> List[Dict[str, Any]]:
    rule = ruleset.procedural["SOE-107"]
    counts: Dict[str, int] = {}
    first_seen: Dict[str, Tuple[int, str]] = {}
    for number, text in lines:
        for m in MONEY_RE.finditer(text):
            if is_standard_amount(text, m):
                continue
            unit = m.group(1)
            counts[unit] = counts.get(unit, 0) + 1
            first_seen.setdefault(unit, (number, m.group(0)))
    if len(counts) < 2:
        return []
    order = sorted(first_seen.items(), key=lambda kv: kv[1][0])
    number, excerpt = order[1][1]
    detail = "，".join(f"{u} {counts[u]} 处" for u, _ in order)
    return [_issue(rule, rule.level, number, excerpt, message=f"金额单位不统一（{detail}）")]


DECISION_LINE_RE = re.compile(r"会议(?:议定|同意|原则同意|决定|要求|明确)")
SKIP_DECISION_RE = re.compile(r"暂缓|不同意|不予同意|如下[：:]?\s*$")
OWNER_RE = re.compile(r"由[^。]{0,20}?(?:牵头|负责|组织|落实|办理)|牵头|负责|责任(?:部门|单位)|要求[^。，；]{0,12}?(?:部|室|中心|公司|单位)|【待补")
TIME_RE = re.compile(r"\d{1,2}月\d{1,2}日|\d{1,2}月(?:底|末|中旬|上旬|下旬)|年底|年内|月底|季度末|前完成|前报|时限|每月|每季度|【待补")
MAJOR_RE = re.compile(r"三重一大|对外投资|投资建设|增资|产权转让|股权转让|大额资金|重大项目|并购|资产重组|对外担保"
                      r"|提供[^。；\n]{0,8}?担保|为[^。；\n]{0,10}?担保|担保\s*\d|借款\s*\d|融资\s*\d")
PREPOSITION_RE = re.compile(r"党委(?:会)?(?:已|已经)?(?:前置)?研究|前置研究|提交(?:公司)?党委")
ITEM_HEAD_RE = re.compile(r"^\s*(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）)")


def _minutes_items(lines: List[Tuple[int, str]]) -> List[List[Tuple[int, str]]]:
    """按“一、”“（一）”分议定事项；没有序号的，每行一项。第一个序号前的开头段不算议定事项。"""
    heads = [i for i, (_n, text) in enumerate(lines) if ITEM_HEAD_RE.match(text)]
    if not heads:
        return [[item] for item in lines if item[1].strip()]
    bounds = heads + [len(lines)]
    return [lines[bounds[k]:bounds[k + 1]] for k in range(len(heads))]


def check_minutes(lines: Lines, ruleset: RuleSet) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    rule = ruleset.procedural["SOE-108"]
    for number, text in lines:
        m = DECISION_LINE_RE.search(text)
        if not m or SKIP_DECISION_RE.search(text):
            continue
        missing = []
        if not OWNER_RE.search(text):
            missing.append("责任部门")
        if not TIME_RE.search(text):
            missing.append("时限")
        if missing:
            issues.append(_issue(rule, rule.level, number, _clip(text[m.start():], 30),
                                 message=f"议定事项没有写明{'和'.join(missing)}"))
    major_rule = ruleset.procedural["SOE-109"]
    for item in _minutes_items(list(lines)):
        if PREPOSITION_RE.search("\n".join(t for _n, t in item)):
            continue
        for number, line_text in item:
            m = MAJOR_RE.search(line_text)
            if m:
                issues.append(_issue(major_rule, major_rule.level, number, _clip(m.group(0)),
                                     _context(line_text, m.start(), m.end())))
                break
    return issues


PARTY_RE = re.compile(r"党委|党支部|党总支|党员|党组织|党建|支部|突击队|先锋岗")
RESULT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|个百分点|万元|亿元|元|吨|天|小时|项|个|件|台|套|人次|次|千瓦时|万千瓦时|公里|米)")


def check_fusion(lines: Lines, ruleset: RuleSet) -> List[Dict[str, Any]]:
    rule = ruleset.procedural["SOE-110"]
    party_lines = [n for n, t in lines if PARTY_RE.search(t)]
    if not party_lines:
        return []
    joined = any(PARTY_RE.search(t) and RESULT_RE.search(t) for _n, t in lines)
    if joined:
        return []
    line, title = _first_text_line(lines)
    has_result = any(RESULT_RE.search(t) for _n, t in lines)
    message = rule.message if has_result else "全文没有结果数据，党建做法的作用无从体现"
    return [_issue(rule, rule.level, line, title, message=message)]


STAFF_TRIGGER_RE = re.compile(
    r"(?:职工|员工)?薪酬(?:分配|制度|方案|调整|改革|体系)|工资总额|工资(?:分配|调整|制度)"
    r"|(?:职工|员工|人员)(?:安置|分流|裁减)|安置方案|裁员|内部退养|劳动用工制度"
    r"|(?:职工|员工)福利|福利(?:制度|方案)|休息休假(?:制度|办法|规定|方案)|劳动保护(?!用品|物资|费)"
    r"|涉及职工切身利益|工资标准|薪酬标准"
    r"|(?:职工|员工|全员)绩效(?:考核|分配)(?:办法|制度|方案)"
    r"|(?:制定|修订|修改|审议|出台|废止)[^。；，,\n]{0,6}重要规章制度")
# 表示已履行（或写明未履行）民主程序的搭配；单有“工会”二字（参会人员、活动经费等）不算
STAFF_SATISFIED_RE = re.compile(
    r"职代会|职工代表大会|职工大会"
    r"|(?:征求|听取)[^。；，,\n]{0,8}(?:工会|职工)[^。；，,\n]{0,4}意见"
    r"|工会(?:意见|审议|讨论|同意|通过)|职工意见"
    r"|(?:尚未|未)[^。；，,\n]{0,6}(?:征求|听取)[^。；，,\n]{0,8}(?:工会|职工)")


def check_staff_interest(lines: Lines, ruleset: RuleSet) -> List[Dict[str, Any]]:
    """涉及职工切身利益的议题，全文须写明职代会或工会意见的完成情况（写“尚未”也算写明）。"""
    rule = ruleset.procedural["SOE-111"]
    if any(STAFF_SATISFIED_RE.search(t) for _n, t in lines):
        return []
    for number, text in lines:
        for m in STAFF_TRIGGER_RE.finditer(text):
            if _staff_negated(text, m):
                continue
            return [_issue(rule, rule.level, number, _clip(m.group(0)), _context(text, m.start(), m.end()))]
    return []


# 触发词前 8 字内（同一分句）出现这些词，说明写的是“不涉及”，不触发（“本项目不涉及职工安置”）
STAFF_NEGATION_RE = re.compile(r"不涉及|不含|无|没有|不存在|未涉及")
STAFF_NEGATION_REACH = 8


def _staff_negated(text: str, m: "re.Match[str]") -> bool:
    lo = max(0, m.start() - STAFF_NEGATION_REACH)
    head = re.split(r"[。！？；;，,、：:\n]", text[lo:m.start()])[-1]
    # 触发词本身以“涉及”开头时（涉及职工切身利益），把它的前两个字并进来，才认得出“不涉及”“未涉及”
    return bool(STAFF_NEGATION_RE.search(head + m.group(0)[:2]))


PROCEDURAL_IDS = ("SOE-101", "SOE-102", "SOE-103", "SOE-104", "SOE-105", "SOE-106",
                  "SOE-107", "SOE-108", "SOE-109", "SOE-110", "SOE-111")


def check_procedural(lines: Lines, doc_type: Optional[str], ruleset: RuleSet,
                     as_of: _dt.date) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    if doc_type == "议题材料":
        issues += check_yiti(lines, ruleset)
        issues += check_staff_interest(lines, ruleset)
    if doc_type == "议案":
        issues += check_yian(lines, ruleset)
    if doc_type == "决议":
        issues += check_resolution(lines, ruleset)
    if doc_type == "改革台账":
        issues += check_ledger(lines, ruleset, as_of)
    if doc_type == "ESG报告":
        issues += check_esg(lines, ruleset)
    if doc_type == "纪要":
        issues += check_minutes(lines, ruleset)
    if doc_type == "融合材料":
        issues += check_fusion(lines, ruleset)
    if ruleset.procedural["SOE-107"].applies(doc_type) and doc_type is not None:
        issues += check_money_units(lines, ruleset)
    return issues


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

def check_lines(lines: Lines, doc_type: Optional[str] = None, external: bool = False,
                ruleset: Optional[RuleSet] = None, as_of: Optional[_dt.date] = None) -> List[Dict[str, Any]]:
    """对正文检查，返回 issue 列表（按行号排序）。"""
    ruleset = ruleset or load_rules()
    as_of = as_of or _dt.date.today()
    external = external or doc_type in ruleset.external_types
    gn, _gc, _lex = _shared()
    issues, table = _check_lines_table(lines, doc_type, external, ruleset, as_of)
    return table.mask_output(issues)


def _check_lines_table(lines: Lines, doc_type: Optional[str], external: bool, ruleset: RuleSet,
                       as_of: _dt.date) -> Tuple[List[Dict[str, Any]], Any]:
    """检查正文，返回 (issue 列表, 全文姓名表)；姓名表供文件名遮蔽使用。"""
    gn, _gc, _lex = _shared()
    issues = check_regex(lines, doc_type, external, ruleset)
    table, per_line, unknown_rows = scan_names(lines, ruleset)
    issues.extend(_issue(rule, "P1", number, "", message=gn.TABLE_UNKNOWN_HINT)
                  for number, rule in unknown_rows if _applicable(rule, doc_type, external))
    issues += check_names(lines, doc_type, external, per_line, table)
    check_inversions(lines, doc_type, external, ruleset, issues)
    issues += check_procedural(lines, doc_type, ruleset, as_of)
    mask_issues(issues, lines, table)
    issues = gn.merge_issues(issues)
    issues.sort(key=lambda item: (item["line"], LEVELS.index(item["level"]), item["id"]))
    return issues, table


def build_result(file_name: str, lines: Lines, doc_type: Optional[str], external: bool,
                 ruleset: Optional[RuleSet] = None, as_of: Optional[_dt.date] = None) -> Dict[str, Any]:
    ruleset = ruleset or load_rules()
    if doc_type is not None and doc_type not in ruleset.types:
        raise InputError(f"--type 只能取：{'、'.join(ruleset.types)}")
    as_of = as_of or _dt.date.today()
    is_external = bool(external or doc_type in ruleset.external_types)
    issues, table = _check_lines_table(lines, doc_type, is_external, ruleset, as_of)
    # 文件名也可能写着姓名（“王建国处分材料.docx”）：按全文姓名表遮蔽后再输出；文件名里有、正文没识别到的姓名遮不住（已知局限）
    file_name = table.mask(file_name) if len(table) else file_name
    notes: List[str] = []
    if doc_type is None:
        notes.append("未指定 --type，只执行了不限文书的正则规则；议题要件、决议票数、台账状态等检查没有执行。")
    if not is_external:
        notes.append("未按对外材料检查；对外发布的材料加 --external，查未公开信息、商业秘密和经营数据。")
    notes.append("行业机检只覆盖能写成规则的项目；前置程序是否属实、数据是否与财务快报一致，按 references/review-addon.md 人工核对。")
    result: Dict[str, Any] = {
        "file": file_name,
        "doc_type": doc_type or "未指定",
        "external": is_external,
        "char_count": sum(len(re.sub(r"\s", "", text)) for _n, text in lines),
        "summary": {lv: sum(1 for i in issues if i["level"] == lv) for lv in LEVELS},
        "issues": issues,
        "notes": notes,
        "engine_version": VERSION,
    }
    if doc_type == "改革台账":
        result["as_of"] = as_of.isoformat()
    return table.mask_output(result)


def check_text(text: str, doc_type: Optional[str] = None, external: bool = False,
               file_name: str = "<text>", ruleset: Optional[RuleSet] = None,
               as_of: Optional[_dt.date] = None) -> Dict[str, Any]:
    """检查一段文本（供测试和其他脚本调用）。"""
    return build_result(file_name, cut_at_note(split_lines(text)), doc_type, external, ruleset, as_of)


def check_file(path: Path, doc_type: Optional[str] = None, external: bool = False,
               ruleset: Optional[RuleSet] = None, as_of: Optional[_dt.date] = None) -> Dict[str, Any]:
    return build_result(path.name, read_lines(path), doc_type, external, ruleset, as_of)


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def render_text(result: Dict[str, Any]) -> str:
    unit = "段" if str(result["file"]).lower().endswith(".docx") else "行"
    s = result["summary"]
    scope = "，按对外材料从严" if result.get("external") else ""
    as_of = f"；统计截止 {result['as_of']}" if result.get("as_of") else ""
    out = [
        f"国企行业机检结果：{result['file']}（文书：{result['doc_type']}{scope}{as_of}；正文 {result['char_count']} 字）",
        f"P0 {s['P0']} 处｜P1 {s['P1']} 处｜P2 {s['P2']} 处",
    ]
    if not result["issues"]:
        out += ["", "未发现行业规则问题。"]
    for issue in result["issues"]:
        out.append("")
        out.append(f"[{issue['level']}] 第{issue['line']}{unit}  {issue['id']}  {issue['category']}：{issue['message']}")
        line = f"    原文：{issue['excerpt']}"
        if issue.get("context"):
            line += f"（上下文：{issue['context']}）"
        if issue.get("count", 1) > 1:
            line += f"（同一摘录共 {issue['count']} 处）"
        out.append(line)
        if issue.get("suggestion"):
            out.append(f"    建议：{issue['suggestion']}")
        out.append(f"    依据：{issue['basis']}")
    if result.get("notes"):
        out.append("")
        out.extend(f"提示：{note}" for note in result["notes"])
    return "\n".join(out)


def render_rules(ruleset: RuleSet) -> str:
    out = ["国企行业机检规则清单："]
    for rule in ruleset.rules + list(ruleset.procedural.values()):
        scope = "、".join(rule.types) if rule.types else "全部"
        ext = f"；对外材料 {rule.external_level}" if rule.external_level else ""
        if rule.low_level and rule.low_level != rule.level:
            ext += f"；低置信 {rule.low_level}"
        only = "；只查对外材料" if rule.external_only else ""
        out.append(f"{rule.id}  [{rule.level}{ext}{only}]  {rule.category}：{rule.message}（适用：{scope}）")
    return "\n".join(out)


class _ChineseHelpFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):  # type: ignore[override]
        return super().add_usage(usage, actions, groups, prefix="用法：")


def _parse_date(value: str) -> _dt.date:
    try:
        return _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期格式应为 YYYY-MM-DD，如 2026-09-30") from exc


def build_parser(types: Sequence[str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="soe_check.py",
        description="国有企业专用文书的行业机检：决策程序、表决票数、议题和议案要件、改革台账状态、"
                    "ESG 披露口径、对外表述、未公开信息、数据写法。",
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
                        help="按对外发布材料从严（未公开信息、商业秘密、经营数据、领先类表述）；"
                             "--type ESG报告、对外材料 时自动启用")
    parser.add_argument("--as-of", dest="as_of", type=_parse_date, default=None, metavar="日期",
                        help="改革台账的统计截止日期（YYYY-MM-DD），默认今天")
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
        result = check_file(Path(args.file), args.doc_type, args.external, ruleset, args.as_of)
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
