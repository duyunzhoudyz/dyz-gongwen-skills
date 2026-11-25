#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实名识别共享模块（锚点 + 候选 + 打分），医院、国企、中小学三个行业专检共用。

源文件位于仓库 shared/scripts/，各 skill 中的副本由 tools/sync_shared.py 生成，请勿在副本上手改。
姓氏、排除词等数据在同目录的 gw_names.json，同样由 sync_shared.py 同步。

识别思路：不靠“姓氏 + 1～2 个字”的裸正则，而是先找“锚点”（患者、护士、给予……处分、
低保家庭学生等能带出姓名的上下文），再在锚点旁取 2～4 字的候选，按“锚点分 + 边界分 + 形态分”打分：
  总分 >= 6 为高置信（用规则级别，如 P0）；总分 == 5 为低置信（用 low_level，如 P1）；< 5 不报。
右边界打分：身份括注、同志、同学 3 分；标点、行尾、强边界词、时间词、亲属词 2 分；功能字（三字名 2 分，两字名 1 分）、弱边界词 1 分；
机构或地名尾字、数字、字母一票否决；其他汉字记为“未知”（UNK）：不再否决，改由名字用字（常见名用字表）、常见二字词和姓氏档次决定
  （三字名：名字用字须全在常见名用字表里且“末字 + 后一字”不是常见二字词，常见姓或复姓加 1 分；两字名：名字用字在表里加 1 分）。

强证据（R3 级右边界、职务称谓左边界、并列名单内）下，前缀类排除词（“孙子”“夏天”“杨梅”）不否决名字用字都在常见名用字表里的三字候选
（“孙子豪”“夏天宇”“杨梅芳”）；两字候选仍按原规则。歧义姓（常、关、祝、焦、单、管、安……）的三字名在锚点分 >= 3 时按常见姓打分，
两字名仍要求右边界是标点或身份括注。

软字（soft_given_chars：和会年日时芷之向从以于无）只许出现在三字名里（形态分减 1）：名字第二字是“向、从、以、于”的三字名（宋向东、赵从军、郑以诚、胡于江）
在强锚点下识别，“患者向医生反映”“患者从家中带来药物”这类功能字用法靠边界与名字用字表挡掉。三字及以上候选以“行、会、家”收尾（邓景行）时，
这几个字同时是机构地名尾字，平时一票否决，但在强证据、并列名单内或右侧是明确边界（标点、并列连词、功能字）时放行；
“均、皆、都、也、又、还、仍”是副词，不并入前面的姓名（“王磊均已接受约谈”不取“王磊均”）。

并列链：锚点之后由“、”（名单语境下还有“，”）和连词“和、与、及、同、跟”连接的姓名项。首项识别后，后面的项先按原打分（够 5 分照常报），
不够的形态合法就只登记进姓名表（NameHit.table_only，不单独报问题）；再不行用宽松取项（姓氏含复姓开头的 2～4 字、右侧是明确收尾，
不看排除词，所以与常用词同形的“杨柳、苏醒、方圆、田野、叶子”和复姓名也登记）；夹在中间的非姓名项（年级、班名）跳过。
首项没识别（与常用词同形、复姓表外等）、而后面的项识别了：回溯，首项也登记（处分框架、名单引导词同理）。连词“和与及同跟”连接的两个姓名
都登记，连词不并入前一个姓名（“程鹏和邓景行”不取“程鹏和”）；连词之后的一项取项从严。边界：整条链上没有任何一项被识别时不登记；
无锚点、并列链之外的同形名仍识别不了。
NameTable.mask 还会把“已登记姓名 + 、 + 姓氏开头的 2～3 字 + 并列尾巴（、等 两人 同志 分别 标点）”里没登记的后项也遮蔽（宁可多遮）。

Markdown 表格以姓名类表头作锚点，同表出现行业敏感列时报高置信。国企可传入全文识别出的单位简称；
有严格简称定义或末字形似单位简称的候选仍登记遮蔽。缺少本处人证时降为 P1，有人证时沿用规则或表格级别。

本模块只做识别、编号遮蔽和结果去重，不读文件、不联网，只用标准库（re、json、pathlib、dataclasses）。
数据缺失或损坏时抛 LexiconError，由引擎转成输入错误（退出码 2），不做静默降级。
"""
from __future__ import annotations

import json
import re
from bisect import bisect_left
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, NamedTuple, Optional, Pattern, Sequence, Tuple

SCORE_LOW, SCORE_HIGH = 5, 6
VETO = -9
DATA_PATH = Path(__file__).with_name("gw_names.json")

ANCHOR_KINDS = ("prefix", "postfix", "list", "frame")
_CJK_RE = re.compile(r"^[一-鿿]+$")
_DIGITS = set("0123456789０１２３４５６７８９")
# 右边界：这些符号紧跟在姓名后面，算“句读成立”
_PUNCT_END = set("，,。；;：:、！!？?）)】]》”\"'’ \t　（(")
# 左边界：这些符号在姓名前面，算“句读成立”
_PUNCT_START = set("，,。；;：:、！!？?（(【[《“\"‘'）) \t　")
_SENT_END = "。！？；;!?\n"
# 身份括注、性别、同志、同学（“同学们”不算）：姓名后接这些时右边界 3 分
R3 = (r"[（(]\s*(?:住院号|病案号|病历号|ID号|门诊号|床号|\d{1,3}\s*床|男|女|工号)"
      r"|[，,]\s*(?:男|女)(?:性)?\s*(?:[，,、。（(]|\d)|同志|同学(?!们)")
R3_RE = re.compile(R3)
# 右边界：时间词、亲属或所属词（2 分）；功能字（三字名 2 分，两字名 1 分，不要放宽，更宽会多出“原记录”“费用能”类误报）
TIME = (r"(?:[昨今前明次当翌同本上下近该][日天晚夜晨午早月年周期学]|近期|近日|凌晨|上午|下午|中午|晚上|夜间|晚间|入院"
        r"|术前|术中|术后|生前|此前|此后|目前|随后)")
KIN = r"(?:家属|家人|家长|父亲|母亲|妻子|丈夫|儿子|女儿|本人|之(?:父|母|子|女|妻|夫))"
FUNC1 = frozenset("在于从向把被将已曾正仍也都均又再就才还因由经对的与和及等系是为称诉未不没说")
# 机构或地名尾字：出现在姓名候选右侧时一票否决（“雷锋班”“焦裕禄班”“李渡镇”）
ORG_END = frozenset("局镇村县乡区市省厂站队办委部处室司社组矿港店场庄屯营寨堡集湾街路寺坡沟班校")
TIME_RE = re.compile(TIME)
KIN_RE = re.compile(KIN)
UNK = -5  # 右边界既不是证据也不否决（后面接普通汉字）
# 歧义姓里“像人名”的那几个：三字名在强锚点下按常见姓处理。“和、向、来、平……”这类同时是功能字或常用字的歧义姓不在内，
# 三字候选的右边界仍须是标点或身份括注（防“单亲家庭学生和家庭经济困难学生”被读成姓名“和家庭”）
AMBIG_NAMELIKE = frozenset("常关祝焦单管安康宁")
# 于 + 数字（“于3月”“于九月”）是时间表述，不是姓名
_DATE_LIKE_RE = re.compile(r"^于[〇零一二三四五六七八九十]")
# 并列后的人数词：“王磊、李娜两人均……”里，“两人”是右边界，“李娜两”不是三字名
PEOPLE_RE = re.compile(r"[二两三四五六七八九十几]人|[二两三四五六七八九十几][名位]")
_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")
_ITEM_TAIL_RE = re.compile(r"(?:同志|同学|先生|女士)$")
_ETC_TAIL_RE = re.compile(r"等(?:\d+|[一二三四五六七八九十]+)?[人名位]*$")
_MD_PIPE_RE = re.compile(r"\\.|(?P<pipe>\|)")
_MD_SEPARATOR_RE = re.compile(r":?-+:?")
_MD_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_MD_HEADER_MARKS_RE = re.compile(r"[\s*_\x60~]")
_TABLE_PUBLIC_RE = re.compile(r"获奖|奖项|表彰|值班|授课|主讲")
_TABLE_DUTY_RE = re.compile(r"整改|任务|问题|台账|措施|时限|部门")
_TABLE_ID_NOTE_RE = re.compile(r"\d+\s*岁|(?:^|[（(，,、：:])\s*[男女](?:性)?\s*(?:$|[，,、）)])|工号|身份证|党龄|年龄|性别|出生|职务|(?<!\d)(?:\d{17}[\dXx]|\d{15})(?!\d)|[0-9]{4}\s*年生")
# 严格简称定义使用封闭的单位通名白名单。“场所、布局、入院”的末字不能证明是单位；
# 单字厂局院所仅在“单位全称”字段已声明对象类型时接受，其他未收录的通名走人工确认。
_ORG_TYPE = (r"股份有限公司|有限责任公司|有限公司|集团公司|总公司|分公司|集团|中心|委员会|银行|合作社"
             r"|制造厂|加工厂|机械厂|电机厂|发电厂|钢铁厂|冶炼厂|水泥厂|化工厂|分厂|总厂"
             r"|管理局|矿务局|税务局|公安局|教育局|财政局|审计局|卫生局|分局|总局"
             r"|医院|法院|检察院|研究院|设计院|科学院|研究所|事务所|审计所|派出所|卫生所")
_ORG_ALIAS_RE = re.compile(
    r"(?:(?<=[一-鿿）)]{2})(?:" + _ORG_TYPE + r")|单位全称\s*[：:]\s*[一-鿿]{2,}[厂局院所])"
    r"[”’》]?\s*[（(，,]?\s*以下简称\s*[：:]?\s*[“\"‘'（(《]?\s*([一-鿿]{2,3})(?=\s*(?:[”\"’'》）)，,。；;]|$))")
_PERSON_TITLE = (r"(?:相关责任人|直接责任人|责任人|当事人|负责人|副?总经理(?:助理)?|副?董事长"
                 r"|(?:党委|纪委|党组|支部)?副?书记|党委委员|工会主席|董事|监事"
                 r"|副?(?:主任|经理|部长|处长|科长)|副?总(?:监|工程师|会计师|经济师|法律顾问|审计师)"
                 r"|副?[局厂院所队站组班]长|主管|专员|员工|职工|干部|会计|出纳|工程师|技术员|业务员|采购员)")
_LIST_TITLE_RE = re.compile(_PERSON_TITLE + r"\s*")
_NOTE_TITLE_RE = re.compile(_PERSON_TITLE + r"(?!部|处|科|室|大会|代表大会)")
_PERSON_TITLE_END_RE = re.compile(_PERSON_TITLE + "$")
_EMPLOYMENT_RE = re.compile(r"(?:离|退|调|转|下|待|在|返)岗|任职|卸任|离任|调任|退休|离休|内退|停职")
_TABLE_UNIT_PREFIX_RE = re.compile(r"^(?:[一-鿿]+?(?:部门|中心|公司|集团|科|部|处|室))")
_TABLE_PREFIX_RE = re.compile(r"^(?:原|时任|现任)?" + _PERSON_TITLE)
_TABLE_NOTE_PAIRS = dict(zip("（(【[《〈{｛〔「『", "）)】]》〉}｝〕」』"))
_TABLE_TOKEN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U000323af]+")
_TABLE_CLASS_RE = re.compile(r"(?:[一二三四五六七八九十\d]+年级|[高初][一二三])(?:[（(]\d+[）)]班)?")
_TABLE_PLACEHOLDER_RE = re.compile(r"〔姓名\d+〕|(?<!\w)(?:(?:共计?|合计|小计|总计)?[\d一二两三四五六七八九十百]+人|N/A)(?!\w)|[-‐‑‒–—―－]+", re.I)
_TABLE_DEPT_END = ("部", "处", "科", "室", "组", "队", "班", "中心", "学院", "办", "病区", "部门", "公司", "集团")
_TABLE_LINK_RE = re.compile(r"\[([^]\n]+)\]\((?:[^()\n]|\([^()\n]*\))*\)")
_TABLE_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9:._-]*)(?=[\s/>])(?:[^<>\"']|\"[^\"]*\"|'[^']*')*>")
_TABLE_INLINE_RE = re.compile(r"(\*{1,3}|_{1,3}|~~|\x60+)([^\n]+?)\1")
_TABLE_SUFFIX_RE = re.compile(r"(?:等[一二两三四五六七八九十百]*[人名位]*|同志|同学|先生|女士)+$")
TABLE_UNKNOWN_HINT = "姓名列内容未能识别，请人工核对"
# 原框架的形态准入保持不变。新增处分只给已入框的同形简称定级，不能据此把地名当姓名。
_FRAME_SHAPE_ACTION = (r"(?:党内(?:严重)?警告|严重警告|留党察看|撤销党内职务|政务(?:警告|记大?过|降级|撤职|开除)"
                  r"|撤职|免职|开除|诫勉谈话)")
_FRAME_SHAPE_ACTION_RE = re.compile(r"\s*(?:同志)?(?:\s*[（(][^）)]*[）)])?\s*(?:分别)?\s*"
                               r"(?:被给予|被处以|受到|被|给予|进行(?:了)?|予以|作出)?\s*" + _FRAME_SHAPE_ACTION)
DEFINED_ABBREVIATION_HINT = "文内已定义为单位简称，如确指单位可忽略"
ABBREVIATION_HINT = "可能是单位简称，请人工确认"
_HANG_RE = re.compile(r"[、，,：:（(]([一-鿿]{1,2})$")   # 摘录末尾“分隔符 + 1～2 个汉字”：可能是被截断的姓名
_PAREN_SKIP_MAX = 12   # 并列项之间可跳过的括注最大字数
CONNECT = "和与及同跟"          # 并列连词：“程鹏和邓景行”“张三与李四”
NAME_TAIL_OK = frozenset("行会家")   # 既是机构地名尾字、又常作名字末字（邓景行、周家）：三字及以上候选在强证据、并列名单或右边界是标点时不因它否决
ADV_TAIL = frozenset("均皆都也又还仍")   # 常跟在姓名后面的副词：三字及以上候选以它收尾、且后面是功能字时，它是副词不是名字用字
CHAIN_CLOSER_RE = re.compile(r"分别|皆|各|共同|一起|均")   # 并列名单收尾词（右边界）


class LexiconError(Exception):
    """数据文件缺失、损坏，或锚点配置有误。引擎应转成输入错误（退出码 2）。"""


class AnchorError(LexiconError):
    """锚点配置有误。"""


@dataclass(frozen=True)
class Lexicon:
    version: str
    surnames_common: FrozenSet[str]
    surnames_rare: FrozenSet[str]
    compound: Tuple[str, ...]
    ambiguous: FrozenSet[str]
    nongiven: FrozenSet[str]
    place_end: FrozenSet[str]
    place_end_2char: FrozenSet[str]
    stopwords: Tuple[str, ...]
    right_strong: Tuple[str, ...]
    right_weak: Tuple[str, ...]
    left_words: Tuple[str, ...]
    # 以下为 1.1.0 新增
    given: FrozenSet[str] = frozenset()          # 常见名用字（given_chars）
    soft_given: FrozenSet[str] = frozenset()     # 软字（和会年日时芷之）：只允许出现在三字名（或复姓名）里，形态分减 1
    stopwords_exact: FrozenSet[str] = frozenset()  # 整词排除词：只屏蔽“候选 == 词”，出现强证据时放行
    word_bigrams: FrozenSet[str] = frozenset()   # 常见二字词（开发期工具从规范文档统计）
    # 按首字建的排除词索引，加载时生成
    stop_index: Mapping[str, Tuple[str, ...]] = field(default_factory=dict, compare=False, repr=False)
    table_names: FrozenSet[str] = frozenset()
    table_public: FrozenSet[str] = frozenset()
    table_nonnames: FrozenSet[str] = frozenset()
    table_sensitive: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    personal_actions: FrozenSet[str] = frozenset()
    org_abbr_end: FrozenSet[str] = frozenset()
    frame_collectives: FrozenSet[str] = frozenset()
    office_modifiers: FrozenSet[str] = frozenset()

    @property
    def surnames(self) -> FrozenSet[str]:
        return self.surnames_common | self.surnames_rare


@dataclass
class Anchor:
    kind: str  # prefix | postfix | list | frame
    regex: Pattern[str]
    strength: int
    suffix: bool = False  # 仅 frame 用：姓名组前面可能带多余汉字，取组的后 N 字作候选
    label: str = ""
    # 仅 suffix 型 frame 用：候选左侧不是行首、标点、左边界词时，text[:候选起点] 还可以靠这个正则放行（调用方提供的职务称谓，
    # 如“总经理”“董事长”）。正则要以 $ 结尾。
    left_ok: Optional[Pattern[str]] = None


@dataclass
class NameHit:
    start: int
    end: int
    name: str
    score: int
    pseudo: bool
    anchor: str
    anchor_start: int = -1  # 正文锚点起点；后锚点为姓名自身起点，表格命中为 -1
    table_only: bool = False  # 并列后项：形态合法但分数不足 SCORE_LOW，只登记进姓名表（用于遮蔽），引擎不要单独报问题
    org_level: str = ""
    org_hint: str = ""
    person_evidence: bool = False


class TableNameRow(NamedTuple):
    headers: Tuple[str, ...]
    hits: List[NameHit]
    unrecognized: bool = False


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------

_LEX_CACHE: Dict[str, Lexicon] = {}


def _need_str(data: Mapping[str, Any], key: str) -> str:
    val = data.get(key)
    if not isinstance(val, str) or not val:
        raise LexiconError(f"姓名数据文件缺少字符串字段：{key}")
    return val


def _need_list(data: Mapping[str, Any], key: str) -> Tuple[str, ...]:
    val = data.get(key)
    if not isinstance(val, list) or not val or not all(isinstance(x, str) and x for x in val):
        raise LexiconError(f"姓名数据文件缺少字符串列表字段：{key}")
    return tuple(val)


# 数据文件各项的最小规模：低于下限视为数据被截断或误改，直接拒绝加载（不做静默降级）
MIN_SIZES: Dict[str, int] = {
    "surnames_common": 200, "surnames_rare": 100, "compound": 15, "ambiguous": 15, "nongiven_chars": 100,
    "soft_given_chars": 5, "given_chars": 400, "place_end": 30, "place_end_2char": 5, "stopwords": 800,
    "stopwords_exact": 50, "right_strong": 20, "right_weak": 10, "left_words": 20, "word_bigrams": 2000,
    "table_names": 8, "table_public": 4, "table_nonnames": 4, "org_abbr_end": 20, "personal_actions": 16,
    "frame_collectives": 2, "office_modifiers": 4,
    "table_sensitive_hospital": 5, "table_sensitive_soe": 4, "table_sensitive_k12": 5,
}
# 哨兵：这些最基本的数据必须在
SENTINELS = (("surnames_common", "王"), ("surnames_common", "李"), ("compound", "欧阳"))


def _need_counts(data: Mapping[str, Any]) -> Mapping[str, Any]:
    val = data.get("counts")
    if not isinstance(val, dict) or not val:
        raise LexiconError("姓名数据文件缺少 counts 字段（各数据项的条数，用于发现数据被截断或误改）")
    return val


def load_lexicon(path: Optional[Path] = None) -> Lexicon:
    """读取并校验姓名数据；结果按路径缓存。"""
    p = Path(path) if path is not None else DATA_PATH
    key = str(p)
    cached = _LEX_CACHE.get(key)
    if cached is not None:
        return cached
    if not p.is_file():
        raise LexiconError(f"缺少姓名数据文件 {p.name}（共享数据），请重新安装本包或运行 tools/sync_shared.py")
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise LexiconError(f"姓名数据文件 {p.name} 无法读取或不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise LexiconError(f"姓名数据文件 {p.name} 顶层必须是对象")
    common = frozenset(_need_str(data, "surnames_common"))
    rare = frozenset(_need_str(data, "surnames_rare"))
    compound = _need_list(data, "compound")
    ambiguous = frozenset(_need_str(data, "ambiguous"))
    nongiven = frozenset(_need_str(data, "nongiven_chars"))
    soft_given = frozenset(_need_str(data, "soft_given_chars"))
    given = frozenset(_need_str(data, "given_chars"))
    place_end = frozenset(_need_str(data, "place_end"))
    place_end_2 = frozenset(_need_str(data, "place_end_2char"))
    stopwords = _need_list(data, "stopwords")
    stop_exact = _need_list(data, "stopwords_exact")
    right_strong = _need_list(data, "right_strong")
    right_weak = _need_list(data, "right_weak")
    left_words = _need_list(data, "left_words")
    bigram_list = _need_str(data, "word_bigrams").split()
    table_names = frozenset(_need_list(data, "table_names"))
    table_public = frozenset(_need_list(data, "table_public"))
    table_nonnames = frozenset(_need_list(data, "table_nonnames"))
    personal_actions = frozenset(_need_list(data, "personal_actions"))
    frame_collectives = frozenset(_need_list(data, "frame_collectives"))
    office_modifiers = frozenset(_need_list(data, "office_modifiers"))
    org_abbr_end = frozenset(_need_str(data, "org_abbr_end"))
    table_sensitive = {domain: _need_list(data, "table_sensitive_" + domain) for domain in ("hospital", "soe", "k12")}

    # 规模下限与 counts 一致性
    sizes = {
        "surnames_common": len(common), "surnames_rare": len(rare), "compound": len(compound),
        "ambiguous": len(ambiguous), "nongiven_chars": len(nongiven), "soft_given_chars": len(soft_given),
        "given_chars": len(given), "place_end": len(place_end), "place_end_2char": len(place_end_2),
        "stopwords": len(stopwords), "stopwords_exact": len(stop_exact), "right_strong": len(right_strong),
        "right_weak": len(right_weak), "left_words": len(left_words), "word_bigrams": len(set(bigram_list)),
        "table_names": len(table_names), "table_public": len(table_public), "table_nonnames": len(table_nonnames),
        "org_abbr_end": len(org_abbr_end), "personal_actions": len(personal_actions),
        "frame_collectives": len(frame_collectives), "office_modifiers": len(office_modifiers),
        **{"table_sensitive_" + domain: len(set(words)) for domain, words in table_sensitive.items()},
    }
    for name, floor in MIN_SIZES.items():
        if sizes[name] < floor:
            raise LexiconError(f"姓名数据有误：{name} 只有 {sizes[name]} 项，低于最小规模 {floor}（数据可能被截断）")
    counts = _need_counts(data)
    for name in sizes:
        if counts.get(name) != sizes[name]:
            raise LexiconError(f"姓名数据有误：counts.{name} 记录 {counts.get(name)} 项，实际 {sizes[name]} 项（数据被改动但 counts 未更新）")
    for name, ch in SENTINELS:
        pool = {"surnames_common": common, "compound": set(compound)}[name]
        if ch not in pool:
            raise LexiconError(f"姓名数据有误：{name} 里缺少哨兵项“{ch}”")

    if common & rare:
        raise LexiconError("姓名数据有误：常见姓与少见姓有重叠：" + "".join(sorted(common & rare)))
    if any(len(c) != 2 for c in compound):
        raise LexiconError("姓名数据有误：复姓必须是 2 个字")
    if not ambiguous <= (common | rare):
        raise LexiconError("姓名数据有误：歧义姓必须是常见姓或少见姓的子集")
    if given & nongiven or soft_given & nongiven or given & soft_given:
        raise LexiconError("姓名数据有误：常见名用字、软字、非名用字三者必须互不重叠")
    if any(len(w) != 2 or not _CJK_RE.match(w) for w in bigram_list):
        raise LexiconError("姓名数据有误：word_bigrams 的每一项必须是 2 个汉字")
    compound_set = set(compound)
    for w in list(stopwords) + list(stop_exact):
        if not (w[0] in common or w[0] in rare or w[:2] in compound_set):
            raise LexiconError(f"姓名数据有误：排除词“{w}”不以姓氏字或复姓开头")
    index: Dict[str, List[str]] = {}
    for w in stopwords:
        index.setdefault(w[0], []).append(w)
    lex = Lexicon(
        version=str(data.get("version", "")), surnames_common=common, surnames_rare=rare, compound=compound,
        ambiguous=ambiguous, nongiven=nongiven, place_end=place_end, place_end_2char=place_end_2,
        stopwords=stopwords, right_strong=right_strong, right_weak=right_weak, left_words=left_words,
        given=given, soft_given=soft_given, stopwords_exact=frozenset(stop_exact), word_bigrams=frozenset(bigram_list),
        stop_index={k: tuple(v) for k, v in index.items()},
        table_names=table_names, table_public=table_public, table_nonnames=table_nonnames,
        table_sensitive=table_sensitive, org_abbr_end=org_abbr_end, personal_actions=personal_actions,
        frame_collectives=frame_collectives, office_modifiers=office_modifiers,
    )
    _LEX_CACHE[key] = lex
    return lex


# ---------------------------------------------------------------------------
# 锚点
# ---------------------------------------------------------------------------

def compile_anchors(spec: Optional[Mapping[str, Any]], lex: Optional[Lexicon] = None) -> List[Anchor]:
    """读规则 JSON 的 name_anchors：{"prefix":[{"re":..,"strength":3}], "postfix":[..], "list":[..], "frame":[..]}。"""
    if not spec:
        return []
    if not isinstance(spec, Mapping):
        raise AnchorError("name_anchors 必须是对象")
    out: List[Anchor] = []
    for kind, items in spec.items():
        if kind not in ANCHOR_KINDS:
            raise AnchorError(f"name_anchors 含未知类型：{kind}")
        if not isinstance(items, list):
            raise AnchorError(f"name_anchors.{kind} 必须是列表")
        for item in items:
            if not isinstance(item, Mapping) or not isinstance(item.get("re"), str):
                raise AnchorError(f"name_anchors.{kind} 的每项必须有字符串字段 re")
            strength = item.get("strength", 3)
            if not isinstance(strength, int) or isinstance(strength, bool):
                raise AnchorError(f"name_anchors.{kind} 的 strength 必须是整数")
            pattern = item["re"]
            if "<<OFFICE_MODIFIERS>>" in pattern:
                # 框架的姓名右边界和候选排除共用同一份任职修饰词。
                modifiers = sorted((lex or load_lexicon()).office_modifiers, key=lambda w: (-len(w), w))
                pattern = pattern.replace("<<OFFICE_MODIFIERS>>", "(?:" + "|".join(map(re.escape, modifiers)) + ")")
            try:
                regex = re.compile(pattern)
            except re.error as exc:
                raise AnchorError(f"name_anchors.{kind} 的正则无法编译：{exc}") from exc
            if kind == "frame" and "n" not in regex.groupindex:
                raise AnchorError("frame 类锚点的正则必须含命名分组 (?P<n>…) 作为姓名组")
            left_ok = None
            if item.get("left_ok"):
                if kind != "frame" or not item.get("suffix"):
                    raise AnchorError("left_ok 只能用于 suffix 型 frame 锚点")
                try:
                    left_ok = re.compile(str(item["left_ok"]))
                except re.error as exc:
                    raise AnchorError(f"name_anchors.{kind} 的 left_ok 无法编译：{exc}") from exc
            out.append(Anchor(kind=kind, regex=regex, strength=strength, suffix=bool(item.get("suffix")),
                              label=str(item.get("label", "")), left_ok=left_ok))
    return out


# ---------------------------------------------------------------------------
# 候选形态
# ---------------------------------------------------------------------------

class _Shape(NamedTuple):
    pseudo: bool      # 代称（王某）
    form: int         # 形态分（已含软字、整词排除词的减分）
    given_ok: bool    # 名字用字全在常见名用字表（含软字）里；右边界为 UNK 的三字名以此为门槛
    bonus: int        # 右边界为 UNK 时的加分：三字名看姓氏档次，两字名看名字用字是否在常见名用字表里
    ambiguous: bool   # 歧义姓
    exact: bool       # 与整词排除词同形（只有强证据时才会走到这里）


def _shape(word: str, lex: Lexicon, evidence: bool = False, common_ambig: bool = False,
           mask_only: bool = False, chain: bool = False, tail_ok: bool = False) -> Optional[_Shape]:
    """候选形态判定；不是姓名形态返回 None。

    evidence=True 表示有强证据（R3 右边界、后锚点、职务称谓左边界）：
      - 与整词排除词（stopwords_exact）同形的候选放行，形态分减 1；
      - 三字候选的名字用字都在常见名用字表（given_chars，不含软字）里时，前缀类排除词（stopwords）不否决
        （“张大伟”“王冠宇”“孙子豪”）；两字候选仍按原规则。
    chain=True 表示候选处于已识别姓名的并列名单内：对前缀类排除词的放行与 evidence 相同，但不放行整词排除词
      （“特困学生：张三丰、高一、高二”里的“高一”“高二”仍不是姓名）。
    common_ambig=True（锚点分 >= 3）：歧义姓的三字名按常见姓处理（“常秀芳”“关晓峰”）；两字名不受影响。
    mask_only=True（并列后项只登记进姓名表、不报问题）：强证据下两字候选也可放行前缀排除词（“王芳、杜鹃”的“杜鹃”），名字用字仍须都是常见名用字。
    tail_ok=True（候选右侧是标点、并列连词或框架边界）：与 evidence、chain 一样，允许三字及以上候选以“行、会、家”收尾（邓景行、周玉家），
    这几个字同时是机构地名尾字，平时一票否决。"""
    n = len(word)
    if n < 2 or n > 4 or not _CJK_RE.match(word):
        return None
    if n == 2 and word in lex.compound:      # 复姓本身（“欧阳”）不是姓名
        return None
    if n >= 3 and word[:2] in lex.compound:
        compound, given = True, word[2:]
    elif n <= 3 and (word[0] in lex.surnames_common or word[0] in lex.surnames_rare):
        compound, given = False, word[1:]
    else:
        return None
    if given in ("某", "某某"):
        return _Shape(True, 1, True, 0, False, False)
    if any(ch in lex.nongiven for ch in given):
        return None
    soft = any(ch in lex.soft_given for ch in given)
    if soft and n == 2:        # 软字只允许出现在三字名（或复姓名）里，两字名里出现直接拒绝
        return None
    if word[-1] in lex.place_end:
        if not (n >= 3 and word[-1] in NAME_TAIL_OK and (evidence or chain or tail_ok)):
            return None
    if n == 2 and word[-1] in lex.place_end_2char:
        return None
    hit_sw = [sw for sw in lex.stop_index.get(word[0], ()) if word.startswith(sw)]
    if hit_sw:
        # 强证据放行：三字候选（并列后项只登记时也含两字候选）、名字用字都是常见名用字、且命中的排除词都只是两字前缀
        # （张大、孙子、夏天）；排除词本身就有三个字（金银花）是整词，仍然否决
        if not ((evidence or chain) and (n == 3 or (mask_only and n == 2)) and all(ch in lex.given for ch in given)
                and all(len(sw) <= 2 for sw in hit_sw)):
            return None
    if _DATE_LIKE_RE.match(word):
        return None
    exact = word in lex.stopwords_exact
    if exact and not evidence:
        return None
    first = word[0]
    ambiguous = (not compound) and first in lex.ambiguous
    if ambiguous and n == 3 and common_ambig and first in AMBIG_NAMELIKE:
        ambiguous = False      # 强锚点下的歧义姓三字名按常见姓处理；下面按 surnames_common 打分
    if compound:
        form = 2
    elif ambiguous:
        form = 0 if n == 3 else -1
    elif first in lex.surnames_common:
        form = 2 if n == 3 else 1
    else:
        form = 1 if n == 3 else 0
    if soft:
        form -= 1
    if exact:
        form -= 1
    given_ok = all(ch in lex.given or ch in lex.soft_given for ch in given)
    if n == 2:
        bonus = 1 if given in lex.given else 0
    else:
        bonus = 1 if (not soft and (compound or (first in lex.surnames_common and not ambiguous))) else 0
    return _Shape(False, form, given_ok, bonus, ambiguous, exact)


def looks_like_name(word: str, lex: Lexicon) -> bool:
    """无上下文的形态判定：2～4 字、姓氏开头、名字部分合理、不是排除词或地名机构。代称（王某）也算。"""
    return _shape(word, lex) is not None


def has_surname_prefix(word: str, lex: Lexicon) -> bool:
    """仅判断是否以姓氏开头（单姓，或复姓且后面还有字），不做其他形态检查。供需要沿用旧口径的调用方使用。"""
    if not word:
        return False
    if word[0] in lex.surnames_common or word[0] in lex.surnames_rare:
        return True
    return any(word.startswith(c) and len(word) > len(c) for c in lex.compound)


# ---------------------------------------------------------------------------
# 边界
# ---------------------------------------------------------------------------

def right_score(text: str, end: int, lex: Lexicon, name_len: int = 3) -> int:
    """姓名右侧边界分。

    3：身份括注、同志、同学；2：标点、行尾、强边界词（含“等”）、时间词、亲属或所属词、功能字（三字名）；
    1：弱边界词、功能字（两字名）；VETO：机构或地名尾字、数字、字母和其他符号；UNK：后面是其他汉字（不否决，由调用方按名字用字等判断）。
    name_len 是候选的字数，只影响功能字的分数。"""
    if R3_RE.match(text, end):
        return 3
    if end >= len(text):
        return 2
    ch = text[end]
    if ch in _PUNCT_END:
        return 2
    rest = text[end:]
    if any(rest.startswith(w) for w in lex.right_strong):
        return 2
    if not rest.startswith("同学们") and (TIME_RE.match(text, end) or KIN_RE.match(text, end) or PEOPLE_RE.match(text, end)):
        return 2
    if ch in FUNC1:
        return 2 if name_len >= 3 else 1
    if any(rest.startswith(w) for w in lex.right_weak):
        return 1
    if ch in ORG_END:
        return VETO
    if "一" <= ch <= "鿿":
        return UNK
    return VETO


def _multi_boundary_at(text: str, pos: int, lex: Lexicon) -> bool:
    """pos 处是否起始一个两字以上的右边界词（如“主诉”“近期”“家属”）。候选的末字若正好是它的首字，说明候选多取了一个字。"""
    rest = text[pos:]
    if any(len(w) >= 2 and rest.startswith(w) for w in lex.right_strong + lex.right_weak):
        return True
    return bool(TIME_RE.match(text, pos) or KIN_RE.match(text, pos) or PEOPLE_RE.match(text, pos))


def left_score(text: str, start: int, lex: Lexicon) -> int:
    """姓名左侧边界分：行首或标点 2；左边界词 1；紧挨数字一票否决；其他 0。"""
    if start <= 0:
        return 2
    prev = text[start - 1]
    if prev in _DIGITS:
        return VETO
    if prev in _PUNCT_START:
        return 2
    head = text[:start]
    if any(head.endswith(w) for w in lex.left_words):
        return 1
    return 0


# ---------------------------------------------------------------------------
# 识别
# ---------------------------------------------------------------------------

def _put(out: Dict[Tuple[int, int], NameHit], hit: NameHit) -> None:
    key = (hit.start, hit.end)
    old = out.get(key)
    if old is None or (hit.score, hit.person_evidence) > (old.score, old.person_evidence):
        out[key] = hit


def _punct_boundary(text: str, end: int) -> bool:
    """end 处是标点、行尾或身份括注（不是靠动词撑起来的边界）。"""
    return end >= len(text) or text[end] in _PUNCT_END or bool(R3_RE.match(text, end))


def _starts_name(text: str, pos: int, lex: Lexicon) -> bool:
    """pos 处是否像一个姓名的开头：姓氏字（或复姓）开头，后面至少还有一个汉字。"""
    if pos + 1 >= len(text):
        return False
    if text[pos:pos + 2] in lex.compound:
        return pos + 2 < len(text) and bool(_CJK_RE.match(text[pos + 2]))
    return (text[pos] in lex.surnames) and bool(_CJK_RE.match(text[pos + 1]))


def _prefix_candidate(text: str, s: int, length: int, strength: int, lex: Lexicon,
                      chain: bool = False) -> Optional[Tuple[str, int, bool]]:
    """前锚点后取 length 个字作候选，按“锚点分 + 右边界分 + 形态分”打分。返回 (候选, 得分, 是否代称)；候选不成立返回 None。

    代称只在“锚点分 + 右边界分 >= 4”时成立；非代称不在这里判 >= 5，由调用方判。
    右边界为 UNK（后面接普通汉字）时：三字及以上的名字，名字用字须全在常见名用字表里；
    候选末字与后一字不能构成常见二字词（“孙丽责任心”不能取“孙丽责”）；然后按 _Shape.bonus 加分。
    chain=True 表示候选在已识别姓名的并列名单内（强证据，等同 R3 级右边界对前缀排除词的放行）。"""
    e = s + length
    if e > len(text):
        return None
    word = text[s:e]
    rs = right_score(text, e, lex, length)
    if rs == VETO:
        return None
    if length > 2 and word[-1] in ADV_TAIL and e < len(text) and text[e] in FUNC1:
        return None      # “王磊均已接受约谈”“澹台静均已……”：均、皆、都、也、又、还、仍是副词，不并入前面的姓名
    if length > 2 and word[-1] in CONNECT and _starts_name(text, e, lex):
        return None      # “程鹏和邓景行”：连词“和与及同跟”不并入前一个姓名，后面紧跟另一个姓名时按并列处理
    tail_ok = rs >= 2 or _punct_boundary(text, e) or (e < len(text) and text[e] in CONNECT)
    sh = _shape(word, lex, evidence=(rs == 3), common_ambig=(strength >= 3), chain=chain, tail_ok=tail_ok)
    if sh is None:
        return None
    if length > 2 and _multi_boundary_at(text, e - 1, lex):
        return None
    if sh.pseudo:
        base = strength + (0 if rs == UNK else rs)
        return (word, base + sh.form, True) if base >= 4 else None
    if sh.ambiguous and not (rs == 3 or _punct_boundary(text, e)):
        return None      # 歧义姓：右边界必须是标点或身份括注
    if rs == UNK:
        if length > 2 and not sh.given_ok:
            return None
        if e < len(text) and text[e - 1:e + 1] in lex.word_bigrams:
            return None
        rs = sh.bonus
    return word, strength + rs + sh.form, False


def _lengths(text: str, s: int, lex: Lexicon) -> Tuple[int, ...]:
    """前锚点后候选的试取长度：单姓只可能是 3、2 字；复姓开头先试 4 字（“欧阳明月”不能被截成“欧阳明”），再 3、2 字。"""
    return (4, 3, 2) if text[s:s + 2] in lex.compound else (3, 2)


def _scan_prefix(text: str, a: Anchor, lex: Lexicon, out: Dict[Tuple[int, int], NameHit]) -> None:
    for m in a.regex.finditer(text):
        s = m.end()
        recognized = False
        for length in _lengths(text, s, lex):
            got = _prefix_candidate(text, s, length, a.strength, lex)
            if got is None:
                continue
            word, score, pseudo = got
            if pseudo:
                _put(out, NameHit(s, s + length, word, score, True, m.group(0), m.start()))
                recognized = True
                break
            if score >= SCORE_LOW:
                _put(out, NameHit(s, s + length, word, score, False, m.group(0), m.start()))
                _chain_prefix(text, a, lex, out, m, s + length)
                recognized = True
                break
        if not recognized:
            _backfill_head(text, a, lex, out, m, s)


def _backfill_head(text: str, a: Anchor, lex: Lexicon, out: Dict[Tuple[int, int], NameHit],
                   m: "re.Match[str]", s: int) -> None:
    """首项没有识别（与常用词同形、复姓表外等）、而后面的并列项识别出来了：回溯，把首项也登记进姓名表。
    只看锚点后紧跟的一项，且它后面（可隔括注）紧跟“、”或连词；并列链里至少有一项按正常打分够报，才算数。"""
    head = _lenient_item(text, s, lex)
    if not head:
        return
    cur = _skip_paren(text, s + len(head))
    if cur >= len(text) or text[cur] not in "、，," + CONNECT:
        return
    tmp: Dict[Tuple[int, int], NameHit] = {}
    _chain_prefix(text, a, lex, tmp, m, s + len(head))
    if any(not h.table_only for h in tmp.values()):
        _put(out, NameHit(s, s + len(head), head, SCORE_LOW - 1, False, m.group(0), m.start(), True))
        for key, h in tmp.items():
            _put(out, h)


def _skip_paren(text: str, pos: int) -> int:
    """pos 处是不超过 _PAREN_SKIP_MAX 字的括注时，返回括注之后的位置；否则原样返回。"""
    if pos < len(text) and text[pos] in "（(":
        for k in range(pos + 1, min(len(text), pos + 2 + _PAREN_SKIP_MAX)):
            if text[k] in "）)":
                return k + 1
    return pos


_CHAIN_MAX_ITEMS = 8                                  # 一串并列最多往后看的项数
_CHAIN_ITEM_RE = re.compile(r"[一-鿿]{1,8}")           # “、”后面的一项（用于跳过非姓名项）
_CHAIN_GRADES = frozenset(("高一", "高二", "高三", "初一", "初二", "初三"))
_CHAIN_NOT_NAME_END = ("年级", "老师", "主任", "校长")   # 整项兜底时不当姓名的结尾（张老师、李主任）


def _whole_item_name(text: str, pos: int, lex: Lexicon) -> str:
    """整项兜底：“、”后的整项（后面紧跟“、，。；等”、括注或行尾）是 2～3 字、姓氏开头、不是年级称谓和教师称谓时，当作姓名
    （赵桥、张河这类形态判定放不过的少见写法）。整词排除词和地名机构尾字的写法（梁平、金山、黄镇）只有后面跟括注或“等N人”才算。
    只在已识别出一个姓名的并列名单后面用，目的是不漏遮，代价是个别非姓名项也可能被遮。"""
    m = _CHAIN_ITEM_RE.match(text, pos)
    if m is None:
        return ""
    item, m_end = m.group(0), m.end()
    if item.endswith("等") and len(item) > 1:       # “张河等5人”
        item, m_end = item[:-1], m_end - 1
    if not 2 <= len(item) <= 3 or item in _CHAIN_GRADES or not has_surname_prefix(item, lex):
        return ""
    if item.endswith(_CHAIN_NOT_NAME_END):
        return ""
    after = text[m_end:m_end + 1]
    if after and after not in "、，,。；;（(等":
        return ""
    if item in lex.stopwords_exact or item[-1] in ORG_END:
        if not (after in ("（", "(") or re.match(r"等\d", text[m_end:m_end + 2])):
            return ""
    return item


def _lenient_item(text: str, nxt: int, lex: Lexicon, need_punct: bool = False) -> str:
    """并列链里的宽松取项：姓氏（含复姓）开头的 2～4 字，右侧必须是明确的收尾（标点、并列连词、功能字、人数词、“分别、均”等），
    不做排除词、整词排除词（杨柳、苏醒、方圆、田野、叶子）和姓氏档次判断，所以与常用词同形的名字也能取到。
    三字及以上还要名字用字都在常见名用字表里（或右侧是标点），防止把“杨柳均”取成三字名。取不到返回空串。
    need_punct：只认标点、行尾、身份括注收尾（“，”并列用）。"""
    if nxt >= len(text):
        return ""
    compound = text[nxt:nxt + 2] in lex.compound
    if not compound and text[nxt] not in lex.surnames:
        return ""
    for length in ((4, 3) if compound else (3, 2)):
        e = nxt + length
        if e > len(text):
            continue
        word = text[nxt:e]
        if not _CJK_RE.match(word):
            continue
        given = word[2:] if compound else word[1:]
        if any(ch in lex.nongiven for ch in given):
            continue
        if word in _CHAIN_GRADES or word.endswith(_CHAIN_NOT_NAME_END):
            continue
        if word[-1] in lex.place_end and not (length >= 3 and word[-1] in NAME_TAIL_OK):
            continue
        punct = _punct_boundary(text, e) or text[e:e + 1] in CONNECT
        if need_punct and not punct:
            continue
        if not punct:
            rs = right_score(text, e, lex, length)
            if rs == VETO or (rs == UNK and not CHAIN_CLOSER_RE.match(text, e)):
                continue
        if length >= 3:
            if _multi_boundary_at(text, e - 1, lex):
                continue
            if not punct and not all(ch in lex.given or ch in lex.soft_given for ch in given):
                continue
        if e < len(text) and not punct and text[e - 1:e + 1] in lex.word_bigrams:
            continue
        return word
    return ""


def _chain_item(text: str, nxt: int, strength: int, lex: Lexicon, comma: bool,
                strict: bool = False) -> Optional[Tuple[str, int, bool]]:
    """并列名单里 nxt 处的一项：返回 (姓名, 分数, 仅登记)；不是姓名形态返回 None。
    先按前锚点同一套打分（分数 >= 5 照常报）；不够时降低门槛：形态合法（姓氏开头 2～4 字、过排除词与黑名单）、
    右侧不是否决边界、末字与后一字不构成常用二字词，就只登记进姓名表（仅登记，不单独报）；再不行是宽松取项（_lenient_item，
    不看排除词，与常用词同形的名字也登记）；最后是整项兜底。strict=True（连词“和与及同跟”后面的一项）不用宽松取项和整项兜底。"""
    lens = _lengths(text, nxt, lex)
    for length in lens:
        got = _prefix_candidate(text, nxt, length, strength, lex, chain=True)
        if got is None or got[2]:
            continue
        if comma and not _punct_boundary(text, nxt + length):
            continue
        if got[1] >= SCORE_LOW:
            return got[0], got[1], False
    for length in lens:
        e = nxt + length
        if e > len(text):
            continue
        word = text[nxt:e]
        rs = right_score(text, e, lex, length)
        if rs == VETO:
            continue
        sh = _shape(word, lex, evidence=(rs == 3), common_ambig=True, mask_only=True, chain=True, tail_ok=True)
        if sh is None or sh.pseudo:
            continue
        if comma and not _punct_boundary(text, e):
            continue
        if length > 2 and _multi_boundary_at(text, e - 1, lex):
            continue
        if e < len(text) and text[e - 1:e + 1] in lex.word_bigrams:
            continue
        return word, SCORE_LOW - 1, True
    if strict:
        # 连词“和与及同跟”前面已经是识别出的姓名：后面与常用词同形的整词（“林梓萌和高峰”）也算姓名，只登记
        for length in (3, 2):
            word = text[nxt:nxt + length]
            if len(word) != length or not _CJK_RE.match(word):
                continue
            same_form = word in lex.stopwords_exact or word in lex.stop_index.get(word[0], ())      # 田野、苏醒、方圆、高峰
            if not same_form or word[0] not in lex.surnames or any(ch in lex.nongiven for ch in word[1:]):
                continue
            if not (nxt + length < len(text) and text[nxt + length - 1:nxt + length + 1] in lex.word_bigrams):
                return word, SCORE_LOW - 1, True
        return None
    lenient = _lenient_item(text, nxt, lex, need_punct=comma)
    if lenient:
        return lenient, SCORE_LOW - 1, True
    if not comma:
        whole = _whole_item_name(text, nxt, lex)
        if whole:
            return whole, SCORE_LOW - 1, True
    return None


def _chain_prefix(text: str, a: Anchor, lex: Lexicon, out: Dict[Tuple[int, int], NameHit],
                  m: "re.Match[str]", end: int) -> None:
    """前锚点命中后，若姓名后面（可隔一个不超过 12 字的括注）紧跟“、”并列，继续读后面的并列姓名
    （如“特困学生：张三、李四”“周梓涵（三年级）、吴雨桐（五年级）”“患者王磊、李娜两人均出现输液反应”）。

    每一项先按前锚点同一套打分（够 5 分照常报）；不够的，形态合法就降低门槛只登记进姓名表（NameHit.table_only，用于遮蔽，
    不单独报问题）；夹在中间的非姓名项（“周梓涵、三年级、吴雨桐”里的“三年级”）跳过，继续看后面的项（最多 8 项）。
    名单语境下也认“，”并列（“特困学生：张三，李四”）：锚点以冒号结尾，或本串已经用过“、”。“，”并列的后一项必须以标点、
    行尾收尾（不靠动词撑边界）且是姓名形态，不是姓名就停下，所以“患者王建国，男，56岁”里的“男”不会被当成并列姓名。"""
    cur = end
    listy = m.group(0).rstrip().endswith(("：", ":"))
    for _ in range(_CHAIN_MAX_ITEMS):
        cur = _skip_paren(text, cur)
        if cur >= len(text) or text[cur] not in "、，," + CONNECT:
            return
        strict = text[cur] in CONNECT      # “程鹏和邓景行”：连词后面的一项按并列处理，但取项从严
        comma = text[cur] in "，,"
        if comma and not listy:
            return
        nxt = cur + 1
        got = _chain_item(text, nxt, a.strength, lex, comma, strict)
        if got is None:
            if comma or strict:
                return
            run = _CHAIN_ITEM_RE.match(text, nxt)      # 非姓名项（年级、班名）：跳过，好接着看下一项
            if run is None:
                return
            cur = _skip_paren(text, run.end())
            if text[cur:cur + 1] in ("班", "级", "组"):    # “七年级（2）班”“高一（3）班”：括注后的班、级、组一并跳过
                cur += 1
            continue
        word, score, table_only = got
        _put(out, NameHit(nxt, nxt + len(word), word, score, False, m.group(0), m.start(), table_only))
        cur = nxt + len(word)
        if not comma and not strict:
            listy = True


def _scan_postfix(text: str, a: Anchor, lex: Lexicon, out: Dict[Tuple[int, int], NameHit]) -> None:
    for m in a.regex.finditer(text):
        pos = m.start()
        for length in (4, 3, 2):
            s = pos - length
            if s < 0:
                continue
            word = text[s:pos]
            sh = _shape(word, lex, evidence=True, common_ambig=(a.strength >= 3))      # 后锚点本身就是强证据
            if sh is None:
                continue
            left = left_score(text, s, lex)
            if left == VETO:
                continue
            base = a.strength + left
            tag = text[pos:pos + 8]
            if sh.pseudo:
                if base >= 4:
                    _put(out, NameHit(s, pos, word, base + sh.form, True, tag, s))
                    break
                continue
            score = base + sh.form
            if score >= SCORE_LOW:
                _put(out, NameHit(s, pos, word, score, False, tag, s))
                break


def _split_connect(text: str, ps: int, pe: int, lex: Lexicon, connectors: str = CONNECT) -> List[Tuple[int, int]]:
    """姓名组里的一段 [ps, pe)：段内有连词“和与及同跟”、且两侧都是 2 字以上、右侧以姓氏开头时，从连词处拆开（“程鹏和邓景行”）；
    “张和平”这类连词在姓名中间（左侧只有 1 个字）的不拆。"""
    pieces = []
    for k in range(ps + 2, pe - 2):
        if k < ps + 2 or text[k] not in connectors or not _starts_name(text, k + 1, lex):
            continue
        if connectors != CONNECT and not _list_item_like_name(text[ps:k], lex):
            continue
        pieces.append((ps, k))
        ps = k + 1
    return pieces + [(ps, pe)]


def _frame_left(a: Anchor, text: str, start: int, lex: Lexicon) -> int:
    """suffix 型 frame 的左边界：0 不成立；1 成立（行首、标点、左边界词）；2 候选前面是调用方给的职务称谓（Anchor.left_ok，强证据）。
    “邓小平理论受到警告处分”取出的“平理论”前面紧挨着“小”，“王府井百货……”取出的“井百货”前面紧挨着“府”，都不成立。"""
    if a.left_ok is not None and a.left_ok.search(text[:start]):
        return 2
    return 1 if left_score(text, start, lex) >= 1 else 0


def _scan_frame(text: str, a: Anchor, lex: Lexicon, out: Dict[Tuple[int, int], NameHit],
                organizations: FrozenSet[str] = frozenset()) -> None:
    for m in a.regex.finditer(text):
        gs, ge = m.span("n")
        group = m.group("n")
        parts = m.groupdict()
        # 只取同一个处分框架里的动作。“撤销某人党内职务”的宾语在姓名后。
        action = (parts.get("action") or "") + (parts.get("object") or "")
        prefixed_action = (parts.get("prefix") or "") + action
        personal_action = action in lex.personal_actions or prefixed_action in lex.personal_actions
        shape_evidence = bool(_FRAME_SHAPE_ACTION_RE.match(text, ge))
        if a.suffix:
            # 姓名组里可以有“、”并列（“给予刘凤英、陈素珍党内警告处分”）：逐项取后 4、3、2 字作候选
            pieces: List[Tuple[int, int]] = []
            pos = gs
            for part in group.split("、"):
                if part:
                    pieces.extend(_split_connect(text, pos, pos + len(part), lex))
                pos += len(part) + 1
        else:
            pieces = [(gs, ge)]
        # 任职修饰词只排除在“撤销……党内职务”的宾语位置，避免影响别处的同形姓名。
        excluded = lex.frame_collectives | lex.office_modifiers if parts.get("object") else lex.frame_collectives
        pieces = [(ps, pe) for ps, pe in pieces if text[ps:pe] not in excluded]
        got_pieces: List[bool] = []
        for ps, pe in pieces:
            if a.suffix:
                ends = [pe]
                if parts.get("office") and pe == m.start("office"):
                    # “欧阳原任”拆开只剩复姓。短候选不成名时，再试原来的完整姓名。
                    ends.append(m.end("office"))
                cands = [(end - length, end) for end in ends for length in (4, 3, 2) if ps <= end - length < pe]
            else:
                cands = [(ps, pe)]
            got_one = False
            for s, e in cands:
                word = text[s:e]
                if word in excluded:
                    continue
                left = _frame_left(a, text, s, lex) if a.suffix else 1
                if s == gs and parts.get("object"):
                    left = 1  # “撤销〔姓名〕党内职务”的前置动词已确定左边界。
                if left == 0 and s > 0 and text[s - 1] in CONNECT:
                    left = 1       # 并列连词之后的一项
                if left == 0:
                    continue
                sh = _shape(word, lex, evidence=(shape_evidence or word in organizations or left == 2 or _personal_context(text[:s], text[e:])),
                            common_ambig=(a.strength >= 3),
                            tail_ok=True)      # 姓名组由框架正则圈定，右侧就是边界
                if sh is None:
                    continue
                score = a.strength + 3 + sh.form
                tag = text[m.start():s]
                # 超过旧框架 16 字的括注仅在人证或个人专属处分成立时支持高置信。
                if len(parts.get("note") or "") > 18 and not personal_action and not _personal_context(text[:s], text[e:]):
                    score = min(score, SCORE_LOW)
                if sh.pseudo:
                    _put(out, NameHit(s, e, word, score, True, tag, m.start()))
                    got_one = True
                    break
                if score >= SCORE_LOW:
                    _put(out, NameHit(s, e, word, score, False, tag, m.start(), person_evidence=personal_action))
                    got_one = True
                    break
            got_pieces.append(got_one)
        if a.suffix and len(pieces) > 1 and any(got_pieces):
            _frame_backfill(text, a, lex, out, m, pieces, got_pieces, personal_action, excluded)


def _frame_backfill(text: str, a: Anchor, lex: Lexicon, out: Dict[Tuple[int, int], NameHit], m: "re.Match[str]",
                    pieces: List[Tuple[int, int]], got_pieces: List[bool], personal_action: bool,
                    excluded: FrozenSet[str]) -> None:
    """处分框架里的并列姓名：有一项识别出来，其余项（与常用词同形的“白云、夏天、黎明”、复姓表外等）一律登记进姓名表。
    第 2 项起，整段就是姓名；第 1 项前面可能带着“相关责任人”之类的字，从末尾取 4、3、2 字，左边界要成立。"""
    for k, ((ps, pe), got) in enumerate(zip(pieces, got_pieces)):
        if got:
            continue
        if k > 0:
            word = text[ps:pe]
            if _list_item_like_name(word, lex):
                _put(out, NameHit(ps, pe, word, SCORE_LOW - 1, False, text[m.start():ps], m.start(), True, person_evidence=personal_action))
            continue
        for length in (4, 3, 2):
            st = pe - length
            if st < ps:
                continue
            word = text[st:pe]
            if word in excluded or _frame_left(a, text, st, lex) == 0 or not _list_item_like_name(word, lex):
                continue
            if any(ch in lex.nongiven for ch in (word[2:] if word[:2] in lex.compound else word[1:])):
                continue
            _put(out, NameHit(st, pe, word, SCORE_LOW - 1, False, text[m.start():st], m.start(), True, person_evidence=personal_action))
            break


def _list_item_like_name(word: str, lex: Lexicon) -> bool:
    """名单里的一项是否值得登记：姓氏（含复姓）开头的 2～4 字汉字，不是年级、教师称谓。"""
    if not 2 <= len(word) <= 4 or not _CJK_RE.match(word) or word in _CHAIN_GRADES or word.endswith(_CHAIN_NOT_NAME_END):
        return False
    return has_surname_prefix(word, lex) and word not in lex.compound


def _scan_list(text: str, a: Anchor, lex: Lexicon, out: Dict[Tuple[int, int], NameHit],
               organizations: FrozenSet[str] = frozenset()) -> None:
    for m in a.regex.finditer(text):
        t0 = m.end()
        t1 = len(text)
        for i in range(t0, len(text)):
            if text[i] in _SENT_END:
                t1 = i
                break
        # 括注里的逗号不能当分隔符：先把括注整体换成占位字符
        tail = text[t0:t1]
        masked = _PAREN_RE.sub(lambda mm: "\x00" * len(mm.group(0)), tail)
        items: List[Tuple[int, int, str]] = []
        recognized = False
        for piece in re.finditer(r"[^、，,]+", masked):
            a0, a1 = piece.span()
            seg = piece.group(0).replace("\x00", " ")
            lstripped = seg.lstrip(" \t　")
            a0 += len(seg) - len(lstripped)
            core = lstripped.rstrip(" \t　")
            core = _ETC_TAIL_RE.sub("", core)
            core = _ITEM_TAIL_RE.sub("", core)
            if not core:
                continue
            title = _LIST_TITLE_RE.match(core)
            titled = bool(title and _shape(core[title.end():], lex, evidence=True, tail_ok=True))
            if title and titled:
                a0 += title.end()
                core = core[title.end():]
            word = core
            s = t0 + a0
            e = s + len(word)
            items.append((s, e, word))
            evidence = word in organizations or titled or _personal_context(text[:s], text[e:])
            sh = _shape(word, lex, evidence=evidence, common_ambig=(a.strength >= 3), tail_ok=True)
            if sh is None:
                continue
            score = a.strength + 2 + sh.form
            if sh.pseudo:
                _put(out, NameHit(s, e, word, score, True, m.group(0), m.start()))
            elif score >= SCORE_LOW:
                _put(out, NameHit(s, e, word, score, False, m.group(0), m.start(), person_evidence=titled))
                recognized = True
        if recognized:       # 名单里有一项识别出来了：其余姓氏开头的 2～4 字项（与常用词同形、复姓表外等）一律登记进姓名表
            for s, e, word in items:
                if (s, e) in out or not _list_item_like_name(word, lex):
                    continue
                _put(out, NameHit(s, e, word, SCORE_LOW - 1, False, m.group(0), m.start(), True))


_SCANNERS = {"prefix": _scan_prefix, "postfix": _scan_postfix, "frame": _scan_frame, "list": _scan_list}


def organization_names(lines: Iterable[str], lex: Lexicon) -> FrozenSet[str]:
    """只有全称紧邻的显式定义可证明简称属于单位。"""
    return frozenset(m[1] for line in lines for m in _ORG_ALIAS_RE.finditer(line) if has_surname_prefix(m[1], lex))


def _personal_context(head: str, tail: str) -> bool:
    tail = tail.lstrip()
    closer = _TABLE_NOTE_PAIRS.get(tail[:1])
    note = tail[1:tail.index(closer)] if closer and closer in tail else ""
    return bool(_PERSON_TITLE_END_RE.search(head.rstrip()) or re.match(r"同志|同学(?!们)|先生|女士", tail)
                or _TABLE_ID_NOTE_RE.search(note) or _EMPLOYMENT_RE.search(note) or _NOTE_TITLE_RE.search(note))


def grade_abbreviation(hit: NameHit, lex: Lexicon, organizations: FrozenSet[str]) -> None:
    if hit.pseudo or (hit.table_only and hit.anchor_start < 0) or len(hit.name) not in (2, 3):
        return
    defined = hit.name in organizations
    if defined or hit.name[-1] in lex.org_abbr_end:
        hit.table_only = False
        if not hit.person_evidence:
            hit.org_level = "P1"
            hit.score = SCORE_LOW
            hit.org_hint = DEFINED_ABBREVIATION_HINT if defined else ABBREVIATION_HINT


def find_names(text: str, anchors: Sequence[Anchor], lex: Lexicon,
               organizations: Optional[FrozenSet[str]] = None) -> List[NameHit]:
    """在单行文字里识别姓名。同一区间取最高分；区间重叠时长的优先。"""
    found: Dict[Tuple[int, int], NameHit] = {}
    for a in anchors:
        if organizations and a.kind in ("frame", "list"):
            _SCANNERS[a.kind](text, a, lex, found, organizations)
        else:
            _SCANNERS[a.kind](text, a, lex, found)
    if organizations is not None:
        for hit in found.values():
            hit.person_evidence = hit.person_evidence or _personal_context(text[:hit.start], text[hit.end:])
            grade_abbreviation(hit, lex, organizations)
    ordered = sorted(found.values(), key=lambda h: (-(h.end - h.start), -h.score, h.start))
    kept: List[NameHit] = []
    for h in ordered:
        if all(h.end <= k.start or h.start >= k.end for k in kept):
            kept.append(h)
    kept.sort(key=lambda h: h.start)
    return kept


def _md_cells(line: str, width: int = 0, header_line: str = "") -> List[Tuple[int, str]]:
    """按未转义的竖线切列，保留值在原行里的偏移，用于遮蔽摘录。"""
    pipes = [m.start() for m in _MD_PIPE_RE.finditer(line) if m["pipe"]]
    if not pipes:
        return []
    bounds = [-1, *pipes, len(line)]
    left_border = not line[:pipes[0]].strip()
    right_border = not line[pipes[-1] + 1:].strip()
    short = len(bounds) - 1 - left_border - right_border < width
    # 列数不足时，以表头的边界样式区分外侧竖线与空首列、空末列。
    if left_border and not (short and not header_line.lstrip().startswith("|")):
        bounds.pop(0)
    if right_border and not (short and not header_line.rstrip().endswith("|")):
        bounds.pop()
    cells = []
    for left, right in zip(bounds, bounds[1:]):
        raw = line[left + 1:right]
        value = raw.strip()
        start = left + 1 + len(raw) - len(raw.lstrip())
        cells.append((start, value))
    return cells


def _md_header_label(label: str) -> str:
    label = _MD_HEADER_MARKS_RE.sub("", label).strip("：:")
    label = label.strip("【】[]（）()《》").rstrip("：:")
    # 剥掉外括号时，保留内部括注的开括号，便于裁掉“姓名（实名）”中的备注。
    return re.split(r"[（(【\[《]", label, maxsplit=1)[0].rstrip("：:")


def _md_table_start(lines: Sequence[str], idx: int) -> List[Tuple[int, str]]:
    if idx + 1 >= len(lines):
        return []
    separator = _md_cells(lines[idx + 1])
    if not separator or not all(_MD_SEPARATOR_RE.fullmatch(value) for _, value in separator):
        return []
    header = _md_cells(lines[idx])
    return header if len(header) == len(separator) else []


def _table_nonname(value: str, lex: Lexicon) -> bool:
    if value in lex.table_nonnames or value in _CHAIN_GRADES or value.removesuffix("年级组") in _CHAIN_GRADES:
        return True
    if _TABLE_CLASS_RE.fullmatch(value):
        return True
    surname = value.removesuffix("某").removesuffix("某")
    if surname != value and (surname in lex.surnames_common or surname in lex.surnames_rare or surname in lex.compound):
        return True
    return _table_department(value, lex)


def _table_department(value: str, lex: Lexicon) -> bool:
    if len(value) < 2 or not value.endswith(_TABLE_DEPT_END):
        return False
    # “王秀英返班”从首字起名，“值守李科”的“科”同时是姓名尾字。检查所有起点。
    # 含姓氏的常见单位、年级组已在上面的精确分支处理。
    return not any(has_surname_prefix(value[pos:pos + 4], lex) for pos in range(len(value) - 1))


def _table_cell_names(value: str, start: int, label: str, score: int, lex: Lexicon,
                      natural_column: bool) -> Tuple[List[NameHit], bool]:
    # 删除标记但保留可见文字与源坐标；<br> 保留为分隔，姓名中间的内联标记不切碎姓名。
    sibling_starts = []
    close_end = -1

    def hide_tag(match: "re.Match[str]") -> str:
        nonlocal close_end
        if not match[1] and match.start() == close_end:
            sibling_starts.append(match.start())
        close_end = match.end() if match[1] else -1
        return (" " if match[2].lower() == "br" else "\0") * len(match[0])

    marked = _TABLE_LINK_RE.sub(lambda m: "\0" + m[1] + "\0" * (len(m[0]) - len(m[1]) - 1), value)
    marked = _TABLE_TAG_RE.sub(hide_tag, marked)
    while True:
        marked, stripped = _TABLE_INLINE_RE.subn(lambda m: "\0" * len(m[1]) + m[2] + "\0" * len(m[1]), marked)
        if not stripped:
            break
    offsets = [i for i, ch in enumerate(marked) if ch != "\0"]
    sibling_cuts = sorted({bisect_left(offsets, i) for i in sibling_starts})
    clean = "".join(marked[i] for i in offsets)
    cell = clean.strip()
    if not cell or cell in lex.table_nonnames or _TABLE_PLACEHOLDER_RE.fullmatch(cell) or cell.isdecimal():
        return [], False
    if _TABLE_CLASS_RE.fullmatch(cell):
        return [], False
    clean, placeholders = _TABLE_PLACEHOLDER_RE.subn(lambda m: " " * len(m[0]), clean)

    def name_hit(pos: int, end: int) -> Optional[NameHit]:
        word = clean[pos:end]
        evidence = natural_column or _personal_context(clean[:pos], clean[end:])
        shape = _shape(word, lex, evidence=evidence, tail_ok=True)
        recognized = shape and not shape.pseudo and (evidence or not (shape.ambiguous and len(word) == 2))
        connector_name = natural_column and len(word) == 3 and any(ch in "和与及" for ch in word[1:])
        if recognized or (connector_name and _list_item_like_name(word, lex)):
            return NameHit(start + pos, start + end, word, score, False, label, person_evidence=evidence)
        return None

    tokens = list(_TABLE_TOKEN_RE.finditer(clean))
    if not tokens:
        return [], not (placeholders and not clean.strip(" \t、，,；;/|"))
    hits = []
    masks = {}
    unknown = bool(re.search("[a-zA-Z]", clean))
    for index, token in enumerate(tokens):
        first, last = token.span()
        word = token[0]
        if word in ("和", "与", "及") and len(tokens) > 1:
            continue
        # 名单项被 Markdown 或括号隔开时，沿用跨格式连词识别。
        if (index and word[0] in "和与及" and _list_item_like_name(word[1:], lex)
                and clean[tokens[index - 1].end():first].strip(" \t）)]】〕》") == ""):
            first += 1
        if (index + 1 < len(tokens) and word[-1] in "和与及" and _list_item_like_name(word[:-1], lex)
                and not clean[last:tokens[index + 1].start()].strip(" \t（([【〔《")
                and _list_item_like_name(tokens[index + 1][0], lex)):
            last -= 1

        # 修饰语可帮助找出原来能报出的姓名；登记范围始终取未经裁剪的片段。
        name_start = first
        while name_start < last and not clean[name_start:last].endswith(_TABLE_DEPT_END):
            prefix = _TABLE_PREFIX_RE.match(clean[name_start:last]) or _TABLE_UNIT_PREFIX_RE.match(clean[name_start:last])
            if not prefix or last - name_start - prefix.end() < 2:
                break
            if not _table_nonname(prefix[0], lex):
                unknown = True
            name_start += prefix.end()
        pieces = _split_connect(clean, name_start, last, lex, "和与及")
        for idx, (pos, end) in enumerate(pieces):
            raw_start = token.start() if idx == 0 else pos
            raw_end = token.end() if idx == len(pieces) - 1 else end
            raw = clean[raw_start:raw_end]
            if _table_nonname(raw, lex):
                continue
            word = _TABLE_SUFFIX_RE.sub("", clean[pos:end])
            word_end = pos + len(word)
            hit = name_hit(pos, word_end)
            recognized = hit is not None
            if hit:
                hits.append(hit)
            else:
                # 先尝试完整文字，以保留跨标签的单个姓名。相邻元素各自成名才拆开。
                cuts = sibling_cuts[bisect_left(sibling_cuts, pos + 1):bisect_left(sibling_cuts, word_end)]
                if cuts:
                    bounds = [pos, *cuts, word_end]
                    split_hits = [None if _table_nonname(clean[lo:hi], lex) else name_hit(lo, hi)
                                  for lo, hi in zip(bounds, bounds[1:])]
                    if all(split_hits):
                        hits.extend(h for h in split_hits if h is not None)
                        recognized = True
            if not recognized:
                unknown = True
            # 剥过修饰语或未识别的原段整段登记。子串穷举只看二、三字及四字复姓名。
            if len(raw) >= 2 and (not recognized or raw != word):
                masks[raw_start, raw_end] = raw
            if len(raw) >= 3:
                for offset in range(raw_start, raw_end - 1):
                    for width in ((4, 3, 2) if clean[offset:offset + 2] in lex.compound else (3, 2)):
                        stop = offset + width
                        if stop <= raw_end and has_surname_prefix(clean[offset:stop], lex):
                            masks[offset, stop] = clean[offset:stop]
    for h in hits:
        masks.pop((h.start - start, h.end - start), None)
    hits.extend(NameHit(start + lo, start + hi, name, SCORE_LOW, False, label, table_only=True)
                for (lo, hi), name in masks.items())
    formatted = []
    for hit in hits:
        lo, hi = offsets[hit.start - start], offsets[hit.end - start - 1] + 1
        hit.start, hit.end = start + lo, start + hi
        if value[lo:hi] != hit.name:
            formatted.append(NameHit(hit.start, hit.end, value[lo:hi], SCORE_LOW, False, label, table_only=True))
    return hits + formatted, unknown


def find_table_names(lines: Sequence[str], lex: Lexicon, domain: str) -> Dict[int, TableNameRow]:
    """识别 Markdown 表格的姓名列。返回按零基行下标索引的命中，敏感列决定分级。"""
    found: Dict[int, TableNameRow] = {}
    sensitive = lex.table_sensitive[domain]
    idx = 0
    fence = ""
    while idx < len(lines):
        mark = _MD_FENCE_RE.match(lines[idx])
        if mark:
            delim, rest = mark.groups()
            if not fence:
                fence = delim
            elif delim.startswith(fence) and not rest.strip():
                fence = ""
            idx += 1
            continue
        header = _md_table_start(lines, idx) if not fence else []
        if not header:
            idx += 1
            continue
        header_line = lines[idx]
        labels = tuple(_md_header_label(label) for _, label in header)
        sensitive_labels = [label for label in labels if any(w in label for w in sensitive)
                            and not re.search(r"整改|任务|问题|台账", label)]
        score = SCORE_HIGH if sensitive_labels else SCORE_LOW
        public = not sensitive_labels and any(label in lex.table_public or _TABLE_PUBLIC_RE.search(label)
                                               for label in labels)
        personal_column = any(label not in lex.table_names and not label.endswith("姓名") for label in sensitive_labels)
        duty = not personal_column and any(_TABLE_DUTY_RE.search(label) for label in labels)
        columns = [i for i, label in enumerate(labels) if (label in lex.table_names or label.endswith("姓名"))
                   and not (duty and label.endswith(("责任人", "责任人姓名")))
                   and not (public and (label == "姓名" or _TABLE_PUBLIC_RE.search(label)))
                   and label[:-2] not in lex.table_public and label not in lex.table_public]
        idx += 2
        while idx < len(lines) and not _MD_FENCE_RE.match(lines[idx]) and not _md_table_start(lines, idx):
            cells = _md_cells(lines[idx], len(header), header_line)
            if not cells:
                break
            hits = []
            unrecognized = False
            for col in columns:
                if col >= len(cells):
                    continue
                start, value = cells[col]
                label = labels[col]
                natural = "姓名" in label or (personal_column and label in ("拟任人选", "人选", "处分对象", "当事人", "责任人"))
                items, unknown = _table_cell_names(value, start, label, score, lex, natural)
                hits.extend(items)
                unrecognized |= unknown
            if hits or unrecognized:
                found[idx] = TableNameRow(labels, hits, unrecognized)
            idx += 1
    return found


# ---------------------------------------------------------------------------
# 全文姓名表与遮蔽
# ---------------------------------------------------------------------------

_TAIL_ROUNDS = 6
_TAIL_RE_CACHE: Dict[int, "Pattern[str]"] = {}


def _tail_regex(lex: Lexicon) -> "Pattern[str]":
    """并列尾巴：已遮蔽的“〔姓名N〕（可带括注）、”之后，姓氏开头的 2～3 字，后面紧跟并列收尾（、等 两人 三人 同志 分别 括注 标点 行尾）。"""
    key = id(lex)
    rx = _TAIL_RE_CACHE.get(key)
    if rx is None:
        chars = re.escape("".join(sorted(lex.surnames)))
        rx = re.compile(r"(?P<head>〔姓名\d+〕(?:[（(][^）)]{0,16}[）)])?、)(?P<w>[" + chars + r"][一-鿿]{1,2})"
                        r"(?=、|等|两人|三人|同志|分别|[，。；）)（(,;]|$)")
        _TAIL_RE_CACHE[key] = rx
    return rx


class NameTable:
    """全文姓名表：按首次出现编号，占位符〔姓名1〕〔姓名2〕。代称（张某）不进表。"""

    def __init__(self) -> None:
        self._order: Dict[str, int] = {}
        self._pattern: Optional[Pattern[str]] = None

    def add(self, name: str) -> int:
        idx = self._order.get(name)
        if idx is None:
            idx = len(self._order) + 1
            self._order[name] = idx
            self._pattern = None
        return idx

    def add_hits(self, hits: Iterable[NameHit]) -> None:
        for h in hits:
            if not h.pseudo:
                self.add(h.name)

    def add_table_masks(self, rows: Iterable[TableNameRow]) -> None:
        """正式姓名编号完成后，再登记表格残段和重叠子串。"""
        self.add_hits(hit for row in rows for hit in row.hits if hit.table_only)

    def placeholder(self, name: str) -> str:
        return f"〔姓名{self.add(name)}〕"

    def names(self) -> List[str]:
        return list(self._order)

    def __contains__(self, name: object) -> bool:
        return name in self._order

    def __len__(self) -> int:
        return len(self._order)

    def mask(self, s: str) -> str:
        """把文字里所有已登记的姓名换成占位符，长名优先、单遍替换（占位符不会被再次匹配）。
        之后再处理并列尾巴：“〔姓名N〕、姓氏开头的 2～3 字”后面紧跟“、等 两人 三人 同志 分别 标点”，而后项没登记过的，
        把后项也登记并遮蔽（宁可多遮：摘录、context 里切到并列后项时，不让后项原名露出来）。"""
        s = self._mask_registered(s)
        if self._order and "〔姓名" in s and "、" in s:
            s = self._mask_tails(s)
        return s

    def _mask_registered(self, text: str) -> str:
        if not self._order or not text:
            return text
        if self._pattern is None:
            names = sorted(self._order, key=len, reverse=True)
            self._pattern = re.compile("|".join(re.escape(name) for name in names))
        return self._pattern.sub(lambda m: f"〔姓名{self._order[m[0]]}〕", text)

    def mask_output(self, value: Any) -> Any:
        """用最终登记表遮蔽报告。摘录或文件名可能刚刚登记了此前未知的并列后项。"""
        if not self._order:
            return value
        if isinstance(value, str):
            return self._mask_registered(value)
        if isinstance(value, dict):
            return {key: self.mask_output(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.mask_output(item) for item in value]
        return value

    def _mask_tails(self, s: str) -> str:
        try:
            lex = load_lexicon()
        except LexiconError:
            return s
        rx = _tail_regex(lex)

        def sub(m: "re.Match[str]") -> str:
            word = m.group("w")
            sh = _shape(word, lex, common_ambig=True, mask_only=True, chain=True)
            if sh is None or sh.pseudo:
                return m.group(0)
            return m.group("head") + self.placeholder(word)

        for _ in range(_TAIL_ROUNDS):    # 一串并列可能有好几项，逐轮往后吃
            new = rx.sub(sub, s)
            if new == s:
                break
            s = new
        return s

    def cut(self, text: str, start: int, end: int) -> str:
        """不切开姓名的截取：取 text[start:end]，边界落在某个已登记姓名中间时，把这个姓名整个并进来，再遮蔽。
        所以摘录的两端不会露出半个姓名。"""
        start, end = max(0, start), min(len(text), end)
        changed = bool(self._order)
        while changed:
            changed = False
            for name in self._order:
                at = text.find(name)
                while at >= 0:
                    stop = at + len(name)
                    if at < start < stop:
                        start, changed = at, True
                    if at < end < stop:
                        end, changed = stop, True
                    at = text.find(name, at + 1)
        if end < len(text):
            end = self._trim_hanging(text, start, end)
        return self.mask(text[start:end])

    def _trim_hanging(self, text: str, start: int, end: int) -> int:
        """悬挂片段回退：摘录以“、，：（”加 1～2 个汉字结尾、片段首字是姓氏、且片段不是已登记的完整姓名时，
        很可能把后面一个没识别出来的姓名截成了半个（“……、钱”），回退到分隔符，不露出半个姓名。"""
        m = _HANG_RE.search(text[start:end])
        if m is None or m.group(1) in self._order:
            return end
        try:
            lex = load_lexicon()
        except LexiconError:
            return end
        if m.group(1)[0] not in lex.surnames:
            return end
        return start + m.start(1)

    def mask_excerpt(self, value: str, text: Optional[str]) -> str:
        """遮蔽一段已经截好的摘录 value。能在原文 text 里定位时，按原文重新“不切开姓名”地截取再遮蔽
        （value 以“……”结尾时保留省略号）；定位不到时退化为 mask_fragment。"""
        if not value:
            return value
        clipped = value.endswith("……")
        core = value[:-2] if clipped else value
        if text and core:
            pos = text.find(core)
            if pos >= 0:
                return self.cut(text, pos, pos + len(core)) + ("……" if clipped else "")
        return self.mask_fragment(value)

    def mask_fragment(self, s: str) -> str:
        """遮蔽一段已经截好、两端可能切断姓名的摘录：先整串遮蔽；摘录开头、末尾残留的姓名片段（至少 2 字，
        如“……低保户王小”）也换成占位符。原文不在手边、只有摘录字符串时用这个。"""
        out = self.mask(s)
        for name in list(self._order):
            for k in range(len(name) - 1, 1, -1):
                if out.endswith(name[:k]):
                    out = out[:-k] + self.placeholder(name)
                    break
                if out.startswith(name[-k:]):
                    out = self.placeholder(name) + out[k:]
                    break
        return out


# ---------------------------------------------------------------------------
# 结果去重
# ---------------------------------------------------------------------------

def merge_issues(issues: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """(id, line, excerpt, message) 完全相同的合并成一条并加 count；保持首次出现顺序。
    同组里级别不同时保留最严重的（P0 > P1 > P2）。"""
    merged: Dict[Tuple[Any, Any, Any, Any], Dict[str, Any]] = {}
    for it in issues:
        key = (it.get("id"), it.get("line"), it.get("excerpt"), it.get("message"))
        cur = merged.get(key)
        if cur is None:
            row = dict(it)
            row["count"] = 1
            merged[key] = row
        else:
            cur["count"] += 1
            lv = it.get("level")
            if isinstance(lv, str) and isinstance(cur.get("level"), str) and lv < cur["level"]:
                cur["level"] = lv
    return list(merged.values())
