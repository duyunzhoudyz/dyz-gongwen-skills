#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分句切分、豁免窗口与程序倒置组合判定，医院、国企两个行业专检共用。

源文件位于仓库 shared/scripts/，各 skill 中的副本由 tools/sync_shared.py 生成，请勿在副本上手改。

三块内容：
  1. 切分：整句按 。！？；!?;\\n 切；分句在整句之外再按 ，,、：: 切。
  2. 豁免窗口：对一处命中（行内起止位置）算出 clause / chain / prev / lead / prefix / chain_prefix / sentence 七个窗口，
     再按“豁免词类别 -> 生效窗口”的归类判断是否豁免（禁止、否定事实、调查引述、处置定性、出处、目标、称号）。
     收缩（负责人决定，不再加规则）：处置类只在命中所在分句内生效，出处类只在命中所在分句与紧邻的前一分句内生效，
     命中之后的分句不再能豁免（原 after 窗口已取消）。已知代价：否决、处置、出处写在后一分句的句子会重新被报出；
     引擎在报出时若发现后续分句里有针对该做法的处置、出处词（later_exemption_words，只看规则实际配置的类别，后续词同样要过语境检查），
     P0 降为 P1（仍报出要人看），并在 suggestion 末尾补“若后文已写明否决、整改或出处，可忽略本条”。
     同分句里的处置词必须针对被命中的做法（见 match_effective 的位置关系检查）：无关的处置词不放过真违规，拿不准不豁免。
  3. 程序倒置：find_inversions 判断“已执行”与“提请或补办”是否出现在同一句或相邻两句，组合判定的命中一律为 P1（提示性质），
     P0 只来自各包规则里对“先行开工、先行采购（医院）、补办手续、先……后报批”等明确写法的正则（单独的“追认”写法由各包另一条规则报 P1）；Declaration 负责正则 P0 命中的如实声明降级：
     声明只认“对本事项的直接断言”（主语是该、本、此、上述、以上 + 项目、事项、做法、情况或承前省略，所在分句以断言收束；疑问、条件、转述、指他、否认、
     难以认定等不算），追认、补办的检查范围是声明所在句及其后两句、倒置句及其前后一句；拿不准不降级。处置类、出处类的豁免命中还要过语境检查（让步、例外、定语、禁止否定目的成分、指他、
     出处未出具的不算豁免，见 match_effective）。

只依赖标准库，不读文件、不联网。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional, Pattern, Sequence, Tuple, Union

# ---------------------------------------------------------------------------
# 1. 切分
# ---------------------------------------------------------------------------

HARD_SEPS = "。！？；;!?\n"          # 整句分隔
SOFT_SEPS = "，,、：:"               # 分句另加的分隔
CLAUSE_SEPS = HARD_SEPS + SOFT_SEPS
PREV_CROSS_SEPS = "，,、；;：:"      # prev 窗口允许跨过的分隔（软分隔，含分号）
COLON_SEPS = "：:"


class Clause(NamedTuple):
    start: int
    end: int      # 不含分隔符
    delim: str    # 紧跟其后的分隔符；行尾为 ""


def split_clauses(text: str) -> List[Clause]:
    """按整句和软分隔切成分句，丢弃空分句。"""
    out: List[Clause] = []
    pos = 0
    n = len(text)
    for i, ch in enumerate(text):
        if ch in CLAUSE_SEPS:
            if i > pos:
                out.append(Clause(pos, i, ch))
            pos = i + 1
    if pos < n:
        out.append(Clause(pos, n, ""))
    return out


def split_sentences(text: str) -> List[Tuple[int, int]]:
    """按整句分隔切句，返回不含分隔符的 (起, 止)，丢弃空句。"""
    out: List[Tuple[int, int]] = []
    pos = 0
    for i, ch in enumerate(text):
        if ch in HARD_SEPS:
            if i > pos:
                out.append((pos, i))
            pos = i + 1
    if pos < len(text):
        out.append((pos, len(text)))
    return out


# ---------------------------------------------------------------------------
# 2. 豁免窗口与豁免词归类
# ---------------------------------------------------------------------------

WINDOW_NAMES = ("clause", "chain", "prev", "lead", "prefix", "chain_prefix", "sentence")


@dataclass(frozen=True)
class Windows:
    clause: str    # 命中所在分句（跨分句取所跨各分句）
    chain: str     # 命中所在分句，向前并入由顿号“、”连着的并列分句（“杜绝先行开工、先行签约”里第二项也在“杜绝”的范围内）
    prev: str      # 紧邻的前一分句（只跨软分隔）
    lead: str      # 命中分句（chain 的起点）紧跟冒号时，冒号前的引导分句
    prefix: str    # 命中前、同一分句内的 N 个字
    chain_prefix: str  # 命中前、同一 chain 内的 N 个字（可跨顿号）
    sentence: str  # 命中所在整句（保留整句判断的规则用）
    clause_start: int = 0    # clause / chain / sentence 窗口在整行里的起点，用来算命中在窗口里的位置
    chain_start: int = 0
    sentence_start: int = 0

    def hit_span(self, name: str, start: int, end: int) -> Optional[Tuple[int, int]]:
        """命中 [start, end) 在名为 name 的窗口文字里的位置；窗口不含命中（prev、lead、prefix 等）返回 None。"""
        base = {"clause": self.clause_start, "chain": self.chain_start, "sentence": self.sentence_start}.get(name)
        if base is None:
            return None
        return max(0, start - base), max(0, end - base)


def compute_windows(text: str, start: int, end: int, prefix_window: int = 8) -> Windows:
    """按命中区间 [start, end) 计算各豁免窗口。"""
    clauses = split_clauses(text)
    hi = max(end, start + 1)
    idx = [i for i, c in enumerate(clauses) if c.start < hi and c.end > start]
    sent_start = 0
    for i in range(min(start, len(text)) - 1, -1, -1):
        if text[i] in HARD_SEPS:
            sent_start = i + 1
            break
    sent_end = len(text)
    for i in range(max(end, start), len(text)):
        if text[i] in HARD_SEPS:
            sent_end = i
            break
    sentence = text[sent_start:sent_end]
    if not idx:
        # 命中恰落在分隔符上：取起点之前最近的分句
        before = [i for i, c in enumerate(clauses) if c.end <= start]
        if not before:
            return Windows("", "", "", "", "", "", sentence, sentence_start=sent_start)
        idx = [before[-1]]
    i0, i1 = idx[0], idx[-1]
    c0, c1 = clauses[i0], clauses[i1]
    clause = text[c0.start:c1.end]
    # chain：向前并入由顿号连着的并列分句。禁止、否定类豁免用它：顿号并列的各项共享前面的“杜绝”“严禁”“尚未”
    j = i0
    while j > 0 and clauses[j - 1].delim == "、":
        j -= 1
    cj = clauses[j]
    chain = text[cj.start:c1.end]
    prev = lead = ""
    if i0 > 0:
        p = clauses[i0 - 1]
        if p.delim in PREV_CROSS_SEPS:
            prev = text[p.start:p.end]
    if j > 0:
        q = clauses[j - 1]
        if q.delim in COLON_SEPS:
            lead = text[q.start:q.end]
    prefix = text[max(c0.start, start - max(prefix_window, 0)):max(start, c0.start)]
    chain_prefix = text[max(cj.start, start - max(prefix_window, 0)):max(start, cj.start)]
    return Windows(clause, chain, prev, lead, prefix, chain_prefix, sentence,
                   clause_start=c0.start, chain_start=cj.start, sentence_start=sent_start)


# 处置、定性与出处两组词（方案 5.2）
DISPOSE = (r"否决|不予采纳|未予采纳|未采纳|不予支持|未予支持|不予同意|予以纠正|已纠正|整改到位|整改完毕|已整改|完成整改"
           r"|已[^，,。；]{0,8}整改|立行立改|已叫停|予以叫停|已查处"
           r"|(?<![不未无非])违规(?!风险|隐患)|(?<![不未无非])违反|不符合(?:规定|要求|规范|政策)|属于(?:违规|违法|禁止)")
# “经自我评价”“经院内评审”“经本院认定”这类自评、内部评审不是出处：经与鉴定、评价、评审、认定之间不得出现自我、自评、院内、内部、本院、本单位、本公司、初步、自行
SOURCE_SELF = r"自我|自评|自行|自查|院内|内部|本院|本单位|本公司|本企业|初步|自(?![然治贸主由动媒])"
SOURCE = (r"经(?:(?!" + SOURCE_SELF + r")[^。；，,]){0,12}?(?:鉴定|评价|评审|认定)|鉴定(?:意见|结论)|评价(?:结果|报告)|榜单|排行榜"
          r"|排名(?:结果|显示)|发布的")

PROHIBIT_WORDS = r"严禁|禁止|不得|杜绝|防止|严防|避免|不能|不应"
NEGATION_WORDS = r"尚未|未|没有|不存在|未发现"
NEGATION_CLAUSE_WORDS = r"不存在|未发现"
INVESTIGATE_WORDS = (r"自查|检查发现|反馈|审计|巡察|专项检查|筛查|排查|核查|线索|监测|稽核|举报"
                     r"|存在[^，,。；]{0,20}问题")
TARGET_WORDS = r"力争|争取|目标|愿景|致力于|计划|拟"
TITLE_WORDS = r"同志|先进|优秀|党员|烈士|称号"

# 类别 -> {窗口: 该窗口生效的词}
CATEGORY_SPEC: Dict[str, Dict[str, str]] = {
    # 禁止、否定类用 chain 窗口：顿号并列的各项共享前面的“杜绝”“尚未”（逗号分开的分句仍各自独立）
    "prohibit": {"chain": PROHIBIT_WORDS, "lead": PROHIBIT_WORDS, "chain_prefix": PROHIBIT_WORDS},
    "negation": {"chain_prefix": NEGATION_WORDS, "chain": NEGATION_CLAUSE_WORDS},
    "investigate": {"clause": INVESTIGATE_WORDS},
    "dispose": {"clause": DISPOSE},
    "source": {"clause": SOURCE, "prev": SOURCE},
    "target": {"clause": TARGET_WORDS, "lead": TARGET_WORDS},
    "title": {"clause": TITLE_WORDS},
}
CATEGORIES = tuple(CATEGORY_SPEC)

PatternLike = Union[str, Pattern[str], None]

# ---------------------------------------------------------------------------
# 豁免命中的语境检查（方案第 6 节）
# ---------------------------------------------------------------------------
# 处置类、出处类的豁免词命中后，还要看它所在分句的语境：虽然写了“违规”“已整改”，但若是让步（虽违规但……）、
# 例外（……除外）、定语（已整改的科室）或出处根本没有出具（鉴定意见尚未出具），就不算真正的处置或出处。
# 判断对象是“命中串整体属于 DISPOSE 或 SOURCE_CTX 的那一处匹配”，所以规则自带的豁免正则（如 SOE-008 的 exempt_context）里
# 的“鉴定意见”“榜单”“据……统计”等词同样适用。
SOURCE_CTX = (SOURCE + r"|证书|认定书|榜单|排名|名单|授予|评为|获评|入选|鉴定意见|评价报告|据[^，,。；]{0,10}(?:统计|发布)")
_DISPOSE_FULL = re.compile(DISPOSE)
_SOURCE_FULL = re.compile(SOURCE_CTX)
DISPOSE_CONCESSION = re.compile(r"虽|虽然|尽管|即使|即便")                    # 匹配前（同一分句）
DISPOSE_EXCEPT = re.compile(r"但|除外|以外|不纳入|不包括|不计入|不含|参照|照此|推广")  # 匹配后到分句末
# 匹配前（同一分句）的禁止、否定、目的性成分：“避免违规”“确保不出现违规”“以免违规”里的违规不是对前文做法的处置定性
DISPOSE_PURPOSE = re.compile(r"避免|防止|确保不|确保没有|以免|杜绝|防范|严防|不致")
# 匹配前（同一分句）指他：“其他医院也违规这样做”说的是别人违规，不是本单位对该做法的处置
DISPOSE_OTHER = re.compile(r"(?:其他|其它|别的|有的|别家|外院|兄弟)[^，,。；]{0,8}也")
DISPOSE_ATTR_REACH = 6                                                      # 匹配后 N 字内出现“的”：定语
SOURCE_BLOCK = re.compile(r"尚未|未(?:经|出具|取得|获得|发布)|尚待|有待|待|将于|将要|正在|拟|准备|申请|计划|暂未|暂无|没有")


def _clause_span(text: str, start: int, end: int) -> Tuple[int, int]:
    """text 里包含 [start, end) 的分句的起止（按 CLAUSE_SEPS 切）。"""
    lo = 0
    for i in range(min(start, len(text)) - 1, -1, -1):
        if text[i] in CLAUSE_SEPS:
            lo = i + 1
            break
    hi = len(text)
    for i in range(max(end, start), len(text)):
        if text[i] in CLAUSE_SEPS:
            hi = i
            break
    return lo, hi


# 处置词与命中的位置关系（命中位置已知时用）：处置词必须是针对被命中的做法，而不是同分句里无关的另一件事
# 处置词在命中之后：命中与处置词之间不得有并列词（“并已纠正部分漏填编码”里的纠正对象是别的东西），间隔不超过 DISPOSE_GAP 字，
# 处置词之后到分句末不得再带一个与做法无关的宾语（已纠正部分漏填编码）
DISPOSE_GAP = 14
DISPOSE_COORD = re.compile(r"并|且|同时|还|以及|及|与|和|另|此外|其中|其余|而")
DISPOSE_OBJ_OK = re.compile(r"^(?:了|的|等|到位|完毕|完成|情况|问题|事项|结果|处理|处分|通报|在案)*$|^(?:该|此|这|上述|以上|前述|其)")
DISPOSE_OBJ_MAX = 4
# 处置词在命中之前：只有“否决了个别科室提出的……的建议”这类先写处置、再指称被处置的提议才算：处置词与命中之间不得有并列词，
# 命中之后同一分句里须紧跟“的建议、的做法、的问题”等名词性成分，说明命中是被处置的那件事的内容
DISPOSE_NOUN_AFTER = re.compile(r"[^，,。；]{0,6}?的(?:建议|提议|议案|做法|问题|方案|行为|情况|现象|说法|苗头|事项|意见|想法|提法|主张|要求|请求)")
# 此前、以前、曾、去年：说的是过去另一回事，不是对本处做法的处置
DISPOSE_PAST = re.compile(r"此前|以前|之前|先前|早前|曾经|曾|过去|往年|去年|历史上|当年|前几年|前期")


def match_effective(win_text: str, m: "re.Match[str]", hit: Optional[Tuple[int, int]] = None) -> bool:
    """豁免窗口里的一处匹配是否真正有效。命中串不属于 DISPOSE、SOURCE_CTX 的匹配一律有效；
    属于处置类的：所在分句里匹配前有让步词、禁止否定目的成分（避免、防止、确保不、以免、杜绝）、指他（其他医院也……）、
    过去（此前、去年），匹配后到分句末有例外词、匹配后 6 字内有“的”，无效；
    给出被命中做法在窗口里的位置 hit=(起, 止) 时再看位置关系：处置词在命中之后，须紧接（间隔不超过 14 字、没有并列词）、
    且之后不再带无关宾语；处置词在命中之前，须是“否决了……（提出的）……的建议”这样的指称结构；与命中重叠的不算。不给 hit 时不做这一项；
    属于出处类的：所在分句里有“待、将于、拟、正在、尚未”等没有出处的表述，无效。"""
    word = m.group(0)
    if not word:
        return True
    is_dispose = bool(_DISPOSE_FULL.fullmatch(word))
    is_source = bool(_SOURCE_FULL.fullmatch(word))
    if not (is_dispose or is_source):
        return True
    lo, hi = _clause_span(win_text, m.start(), m.end())
    if is_dispose:
        before = win_text[lo:m.start()]
        after = win_text[m.end():hi]
        # 过去的判断只看处置词自己这一段：处置词在命中之后时，命中到处置词之间；命中本身（“曾拆分为三个子项目”）不算
        past_zone = win_text[hit[1]:m.start()] if (hit is not None and m.start() >= hit[1]) else before
        if (DISPOSE_CONCESSION.search(before) or DISPOSE_PURPOSE.search(before) or DISPOSE_OTHER.search(before)
                or DISPOSE_PAST.search(past_zone) or DISPOSE_EXCEPT.search(after) or "的" in after[:DISPOSE_ATTR_REACH]):
            return False
        if hit is not None and not _dispose_targets_hit(win_text, m, after, hit):
            return False
    if is_source and SOURCE_BLOCK.search(win_text[lo:hi]):
        return False
    return True


def _dispose_targets_hit(win_text: str, m: "re.Match[str]", after: str, hit: Tuple[int, int]) -> bool:
    """处置词是否针对被命中的做法（位置关系，见 match_effective）。拿不准返回 False（宁可报出）。"""
    hs, he = hit
    if m.start() < he and m.end() > hs:
        return False                       # 与命中重叠
    if m.start() >= he:                    # 处置词在命中之后
        gap = win_text[he:m.start()]
        if len(gap) > DISPOSE_GAP or DISPOSE_COORD.search(gap):
            return False
        rest = after.strip()
        return len(rest) <= DISPOSE_OBJ_MAX or bool(DISPOSE_OBJ_OK.search(rest))
    between = win_text[m.end():hs]         # 处置词在命中之前
    if len(between) > DISPOSE_GAP + 4 or DISPOSE_COORD.search(between):
        return False
    _lo, clause_hi = _clause_span(win_text, m.end(), m.end())
    return bool(DISPOSE_NOUN_AFTER.match(win_text[he:clause_hi]))


LATER_HINT = "若后文已写明否决、整改或出处，可忽略本条"


def later_exemption_words(text: str, start: int, end: int, kinds: Iterable[str] = ("dispose", "source")) -> bool:
    """命中所在分句之后、同一整句里的后续分句有没有“针对该做法”的处置类、出处类词（否决、已整改、鉴定、榜单……）。
    kinds 只取规则实际配置的豁免类别（dispose、source）：HOS-033 命中后，后面出现“排名”这样的出处词不算。
    后续分句里的词同样要过语境检查（让步、例外、定语、避免违规这类目的成分、指他、过去、出处未出具），不通过的不算。
    收缩后这些后续分句不再能豁免命中；引擎在报出时据此给提示（LATER_HINT），并把 P0 降为 P1。"""
    kinds = tuple(kinds)
    _lo, hi = _clause_span(text, start, end)
    if hi >= len(text) or text[hi] in HARD_SEPS:
        return False
    stop = len(text)
    for i in range(hi + 1, len(text)):
        if text[i] in HARD_SEPS:
            stop = i
            break
    rest = text[hi + 1:stop]
    for kind, rx in (("dispose", _DISPOSE_FULL), ("source", _SOURCE_FULL)):
        if kind in kinds and _any_effective(rx, rest):
            return True
    return False


def _any_effective(rx: Pattern[str], win_text: str, hit: Optional[Tuple[int, int]] = None) -> bool:
    for m in rx.finditer(win_text):
        if match_effective(win_text, m, hit):
            return True
    return False


def _as_pattern(p: PatternLike) -> Optional[Pattern[str]]:
    if p is None or p == "":
        return None
    if isinstance(p, str):
        return re.compile(p)
    return p


def window_text(win: Windows, name: str) -> str:
    if name not in WINDOW_NAMES:
        raise ValueError(f"未知窗口：{name}")
    return getattr(win, name)


def is_exempt(text: str, start: int, end: int, patterns: Mapping[str, PatternLike], prefix_window: int = 8) -> bool:
    """给定一行文字、命中区间和各窗口对应的豁免正则，任一窗口里有一处“有效”匹配即视为豁免。

    patterns 的键取 clause、chain、prev、lead、prefix、chain_prefix、sentence（没有 after，传入会抛 ValueError），值为正则（字符串或已编译）。
    匹配逐个（finditer）检查语境，见 match_effective：让步、例外、定语、出处未出具的匹配不算豁免。"""
    win = compute_windows(text, start, end, prefix_window)
    for name, pat in patterns.items():
        rx = _as_pattern(pat)
        if rx is not None and _any_effective(rx, window_text(win, name), win.hit_span(name, start, end)):
            return True
    return False


@lru_cache(maxsize=256)
def _category_patterns(category: str) -> Dict[str, Pattern[str]]:
    spec = CATEGORY_SPEC.get(category)
    if spec is None:
        raise ValueError(f"未知豁免类别：{category}；可选：{'、'.join(CATEGORIES)}")
    return {win: re.compile(words) for win, words in spec.items()}


def category_patterns(categories: Iterable[str]) -> Dict[str, Pattern[str]]:
    """把若干类别合并成 {窗口: 正则}，可直接传给 is_exempt。"""
    merged: Dict[str, List[str]] = {}
    for cat in categories:
        spec = CATEGORY_SPEC.get(cat)
        if spec is None:
            raise ValueError(f"未知豁免类别：{cat}；可选：{'、'.join(CATEGORIES)}")
        for win, words in spec.items():
            merged.setdefault(win, []).append(words)
    return {win: re.compile("|".join(f"(?:{w})" for w in ws)) for win, ws in merged.items()}


def find_exemption(text: str, start: int, end: int, categories: Iterable[str], prefix_window: int = 8,
                   extra: Optional[Mapping[str, PatternLike]] = None) -> Optional[str]:
    """按类别逐个判断，返回第一个生效的类别名；都不生效返回 None。extra 是规则自带的附加窗口正则，类别记为 "extra"。
    每处匹配都做语境检查（见 match_effective）。"""
    win = compute_windows(text, start, end, prefix_window)
    for cat in categories:
        for wname, rx in _category_patterns(cat).items():
            if _any_effective(rx, window_text(win, wname), win.hit_span(wname, start, end)):
                return cat
    for wname, pat in (extra or {}).items():
        rx = _as_pattern(pat)
        if rx is not None and _any_effective(rx, window_text(win, wname), win.hit_span(wname, start, end)):
            return "extra"
    return None


# ---------------------------------------------------------------------------
# 3. 程序倒置：组合判定（HOS-034、SOE-001）
# ---------------------------------------------------------------------------
# 收缩后：组合判定的命中一律为 P1（提示性质），不再产生 P0；P0 只来自各包规则里对“先行开工、补办手续、追认”等明确写法的正则。
# “已执行”分两档：强档（E1～E4，“已”加执行动词）和弱档（E5，只写“于X月开工、投入使用”，没有“已”字），两档都只报 P1，
# 区别只在提示文案（reason_code：同句 same_sentence、相邻两句 adjacent、弱档 weak_exec）。

# E1：已 + 执行动词。否定前瞻：方案、计划、需求、可研、立项、意向、框架、备忘录、管理、办法、制度等不是已执行
EXEC_NOT = r"(?!方案|计划|前|准备|论证|调研|需求|可研|立项|意向|框架|备忘录|管理|办法|制度)"
EXEC = (r"(?<![未没])已(?:经)?(?:全部|基本|陆续|分批)?(?:于[^，,。；]{1,12}?)?(?:先行|提前|预先)?"
        r"(?:开工建设|开工|动工|施工|签约|签订|签署|签了|付款|支付|采购到位|采购|购置|购买|到货|安装|投入使用|投用|启用|上线"
        r"|完工|建成|实施|执行|交付)" + EXEC_NOT)
# E2：已与某方签订。后 10 字内出现意向、框架、备忘录、保密协议、战略合作的不算
EXEC_SIGN = r"(?<![未没])已(?:经)?(?:与|同|和)[^，,。；《》]{1,15}?签(?:订|署|约)"
EXEC_SIGN_NOT = r"意向|框架|备忘录|保密协议|战略合作"
EXEC_SIGN_REACH = 10
# E3：已完成采购、安装、施工等；书名号内的不算（《采购管理办法》修订稿）
EXEC_DONE = (r"(?<![未没])已(?:经)?(?:全部|基本)?完成(?:了)?[^，,。；《》]{0,10}?"
             r"(?:采购|购置|安装|施工|建设|调试|签约|签订|招标|付款|支付|主体工程|工程量|\d+%)" + EXEC_NOT)
# E4：已进场、已开始施工
EXEC_START = (r"(?<![未没])已(?:经)?(?:于[^，,。；]{1,12}?)?"
              r"(?:进场(?:施工|作业)?|开始施工|启动施工|开始建设|开始采购)")
# E5（P1 档）：于X月开工、投入使用……没有“已”字。前 4 字内有拟、将、计划等将来、要求类词的不算
EXEC_DATED = (r"于(?:\d{4}年)?\d{1,2}月(?:份|底|初|中旬|上旬|下旬)?(?:\d{1,2}日)?(?:先行)?"
              r"(?:开工建设|开工|动工|采购到位|投入使用|签订|签约|建成|完工|上线|进场)")
EXEC_DATED_NOT = r"拟|将|计划|预计|争取|力争|准备|要求|应当|应|须|确保|力求|预定|定于"
EXEC_DATED_BACK = 4
EXEC_NEG = r"(?:尚未|未|没有|不得|严禁|禁止|防止|杜绝)[^，,。；]{0,4}$"
PRIOR_OK = r"(?:审议通过|研究通过|批准|批复|决策|同意|决定)(?:后|之后|以后)[^。；]{0,6}$"
REQ = (r"(?:现|特|今|拟)?提请[^。；\n]{0,12}?(?:审议|审批|研究|决定|决策|追认|批准|审定)"
       r"|请予审议|请审议|特提请|提交[^。；\n]{0,8}(?:会议|董事会|党委会|院长办公会)[^。；\n]{0,4}审议"
       r"|现(?:提交|报请|报送)[^。；\n]{0,12}?(?:审议|审批|研究|决定|批准)"
       r"|现将[^。；\n]{0,24}?(?:提请|报请|提交|报送)[^。；\n]{0,12}?(?:审议|审批|研究|决定|批准)"
       r"|补(?:办|报|走|履行|签)[^。；\n]{0,8}?(?:程序|手续|审批|决策|报批|上会)"
       r"|(?<!严禁)(?<!以)追认|事后(?:审批|报批|审议)")
# 新事项标记：提请对象里有这些词，说明提请的可能不是已执行的那件事（二期、续签、新购……）
NEW_OBJ = (r"二期|三期|后续|下一阶段|续建|续签|追加|调整|变更|增补|配套|新购|新建|新增|创建|筹建|升级|改造|扩建|改建|迁建"
           r"|新一轮|下一年度|明年")
OTHER_OBJ = NEW_OBJ    # 旧名，保留别名
# 事后的正常事项：验收、结算、备案等，提请对象里没有追认、补办时不报
POST_OBJ = (r"验收|结算|决算|审计报告|备案|总结|绩效评价|后评价|运营|运维|移交|进展报告|情况报告"
            r"|收费标准|管理办法|管理制度|制度|办法|细则|报废|处置|编制|计划|预算|方案调整|运行情况|使用情况")
OBJ_REACH = 8          # 已执行对象：已执行动词之后到分句末，取前 8 字
# 如实声明：只认肯定式。“如实报告”“如实说明”单独出现不再算声明
DECL = (r"(?:属于|系|属|存在|构成|形成)[^，,。；]{0,4}(?:程序倒置|先(?:执行|实施)后决策)"
        r"|(?:以上|上述|前述|该|此)[^。；]{0,10}(?:程序倒置|先(?:执行|实施)后决策)"
        r"|未(?:经|履行)[^，,。；]{0,8}(?:决策|审批|审议)程序|程序(?:上)?存在(?:瑕疵|问题)"
        r"|(?:该|此|这一)(?:做法|行为)?违反(?:了)?[^，,。；]{0,12}(?:规定|制度|程序|办法)")
DECL_NEG = (r"不属于|不属|不构成|未发生|并非|不是|没有|不存在|未发现|杜绝|防止|严禁|避免|不得|防范|自查"
            r"|禁止|严防|不能|不应|不再|不出现|未形成|不涉及"
            # 疑问、条件、转述、他人、难以认定等非断言写法（“是否属于程序倒置请会议研究”“如属于程序倒置，按规定处理”“其他单位因属于……被通报”）
            r"|是否|如(?!实)|若(?!干)|如果|倘|假如|一旦|说法|认为不|不认为|难以|谈不上|并不|算不上|未必|所谓|质疑|其他|别的"
            r"|有的|有些|有人|他人|外界|别人|他们|有观点|有意见|是不是|能否|可否|会不会|是否会|不好说|无法认定|不宜认定|不能认定")
DECL_NEG_BACK = 8      # 否定检查：匹配开头之前同一分句内的字数（匹配本身和匹配之后到分句末也要检查）
# 声明必须是对本事项的直接断言：主语是“该、本、此、上述、以上、前述 + 项目、事项、做法、情况”，或承前省略主语（前面没有别的主语）；
# 声明所在分句以断言收束（句末，或后面只是“情况、问题、的情形”），不是从句（……的说法）、引述或疑问。拿不准不降级
DECL_SUBJECT_OK = re.compile(r"^(?:|(?:现|经核查|经查|经审查|经自查|经研究|经核实|如实|如实说明|如实报告|特此|确|确实|确系|确属|也|均|又|还|同时|并|并且|且|即|就|则|是|系)"
                             r"|(?:该|本|此|这|这一|上述|以上|前述|上列)[^，。；]{0,8})[，,]?$")
DECL_TAIL_OK = re.compile(r"^(?:的)?(?:情形|情况|问题|现象|行为|事实|做法|事项)?(?:无疑|确实|属实|了)?"
                          r"(?:[，,]?(?:特此|现|在此|予以)?(?:如实)?(?:说明|报告|汇报|报告如下|说明如下))?$")
DECL_TAIL_THEN = re.compile(r"^(?:即|便|就|而|才)")   # “未履行决策程序即先行开工”：后面接的是倒置本身
DECL_WORD_FORMS = re.compile(r"程序倒置|先(?:执行|实施)后决策")
NORMALIZE = r"追认|补(?:办|报|走|履行)"

# 结果里的 reason_code：P0 为 "p0"；P1 按下面的优先级取第一个成立的原因，供引擎按原因换文案
REASON_CODES = ("normalize", "declared", "other_item", "adjacent", "weak_exec")
REASON_TEXT = {"declared": "如实声明", "other_item": "提请对象为其他事项",
               "adjacent": "邻句", "weak_exec": "仅有“于X月……”式表述", "same_sentence": "同句", "normalize": "追认或补办"}

_INV_DEFAULTS = {"exec": EXEC, "exec_neg": EXEC_NEG, "prior_ok": PRIOR_OK, "req": REQ, "other_obj": NEW_OBJ,
                 "decl": DECL, "normalize": NORMALIZE, "exec_sign": EXEC_SIGN,
                 "exec_done": EXEC_DONE, "exec_start": EXEC_START, "exec_dated": EXEC_DATED, "post_obj": POST_OBJ,
                 "decl_neg": DECL_NEG}
EXCERPT_LIMIT = 80


class _Sent(NamedTuple):
    line: int    # 行下标（0 起）
    start: int   # 行内起点
    end: int
    text: str


def _compile_inv(cfg: Mapping[str, Any]) -> Dict[str, Pattern[str]]:
    out: Dict[str, Pattern[str]] = {}
    for key, default in _INV_DEFAULTS.items():
        val = cfg.get(key)
        out[key] = re.compile(val if isinstance(val, str) and val else default)
    return out


def _sentences(lines: Sequence[str]) -> List[_Sent]:
    sents: List[_Sent] = []
    for li, line in enumerate(lines):
        for a, b in split_sentences(line):
            if line[a:b].strip():
                sents.append(_Sent(li, a, b, line[a:b]))
    return sents


_EXEC_NEG_NEAR = re.compile(EXEC_SIGN_NOT)
_EXEC_DATED_NOT_RE = re.compile(EXEC_DATED_NOT)


def _exec_candidates(sent: str, rx: Mapping[str, Pattern[str]], weak: bool) -> List["re.Match[str]"]:
    """句子里所有有效的“已执行”匹配（P0 档 weak=False，P1 档 weak=True），按位置排序。
    无效：前面同分句有否定（尚未、严禁……）、本句前面写了“审议通过后”、紧跟“的”或“了的”（已建成的……作定语）；
    E2 后 10 字内有意向、框架等；E5 前 4 字内有拟、将、计划等。"""
    keys = ("exec_dated",) if weak else ("exec", "exec_sign", "exec_done", "exec_start")
    found: List["re.Match[str]"] = []
    for key in keys:
        for m in rx[key].finditer(sent):
            before = sent[:m.start()]
            if rx["exec_neg"].search(before) or rx["prior_ok"].search(before):
                continue
            tail = sent[m.end():m.end() + 2]
            if tail.startswith("的") or tail.startswith("了的"):
                continue
            if key == "exec_sign" and _EXEC_NEG_NEAR.search(sent[m.end():m.end() + EXEC_SIGN_REACH]):
                continue
            if key == "exec_dated" and _EXEC_DATED_NOT_RE.search(sent[max(0, m.start() - EXEC_DATED_BACK):m.start() + 1]):
                continue    # 窗口带上匹配开头的“于”，才拼得出“定于”
            found.append(m)
    found.sort(key=lambda mm: (mm.start(), -mm.end()))
    return found


def _first_valid_exec(sent: str, rx: Mapping[str, Pattern[str]]) -> Optional[Tuple["re.Match[str]", bool]]:
    """(匹配, 是否 P1 档)。先找 P0 档，没有再找 P1 档。"""
    strong = _exec_candidates(sent, rx, False)
    if strong:
        return strong[0], False
    dated = _exec_candidates(sent, rx, True)
    if dated:
        return dated[0], True
    return None


def _exec_object(sent: str, em: "re.Match[str]") -> str:
    """已执行对象：已执行动词之后到分句末，取前 8 字（去掉开头的“了”）。"""
    tail = sent[em.end():]
    for i, ch in enumerate(tail):
        if ch in CLAUSE_SEPS:
            tail = tail[:i]
            break
    tail = tail.lstrip("了")
    return tail[:OBJ_REACH].strip()




def _clause_bounds(text: str, pos: int) -> Tuple[int, int]:
    """text 里 pos 所在分句的 (起, 止)，按 CLAUSE_SEPS 切；止不含分隔符。"""
    lo = 0
    for i in range(min(pos, len(text)) - 1, -1, -1):
        if text[i] in CLAUSE_SEPS:
            lo = i + 1
            break
    hi = len(text)
    for i in range(max(pos, 0), len(text)):
        if text[i] in CLAUSE_SEPS:
            hi = i
            break
    return lo, hi


class Declaration:
    """一份文书里程序倒置规则共用的“如实声明”判断（医院 HOS-034、国企 SOE-001 的正则命中和组合判定都调用它）。

    声明只认肯定式（DECL）：“属于程序倒置”“以上程序倒置情况”“未履行决策程序”“程序上存在瑕疵”“该做法违反了……规定”等。
    否定检查覆盖“匹配开头之前同一分句内 8 字 + 匹配本身 + 匹配之后到分句末”的整段：
    出现“不属于、不构成、未发生、并非、不是、没有、不存在、未发现、杜绝、防止、严禁、避免、不得、防范、自查”等即不算声明
    （“上述做法不属于程序倒置”“此前已就程序倒置问题开展了自查”都不是声明）。“如实报告”“如实说明”不参与判断。
    追认补办词（NORMALIZE）：“追认”“补办”等。
    收缩后只看同一句和紧邻的前一句、后一句，不再有全文级降级：
      - near_declared：命中所在句、前一句或后一句有声明。此时程序倒置类规则不适用“处置类”豁免
        （“该做法违反了……规定，属于程序倒置”里的“违反”不能把整句放过）。
      - adjust：regex 命中的 P0 降为 P1，当且仅当就近（本句、前一句、后一句）有声明，且这三句里没有追认、补办；
        其余情形（含另一段写了“坚决杜绝程序倒置”）原级别不动。
    cfg 同 find_inversions（procedure_inversion）；lines 是文书各行文字，行号 = 下标 + 1。"""

    def __init__(self, lines: Sequence[str], cfg: Optional[Mapping[str, Any]] = None) -> None:
        self.lines = lines
        self.rx = _compile_inv(cfg or {})
        self.sents = _sentences(lines)

    def _has_decl(self, text: str, decl_rx: Pattern[str]) -> bool:
        """text 里是否有未被否定、且是对本事项直接断言的肯定式声明。"""
        neg = self.rx["decl_neg"]
        for a, b in split_sentences(text):
            sent = text[a:b]
            pos = 0
            while pos <= len(sent):
                m = decl_rx.search(sent, pos)
                if m is None:
                    break
                lo, _hi0 = _clause_bounds(sent, m.start())
                _lo1, hi = _clause_bounds(sent, max(m.end() - 1, m.start()))
                region = sent[max(lo, m.start() - DECL_NEG_BACK):hi]
                if not neg.search(region) and self._direct_assertion(sent, m, lo, hi):
                    return True
                pos = m.start() + 1       # 从下一个位置重找：“特此报告，属于程序倒置”里 DECL 先从“此”起匹配，要退到“属于”再判
        return False

    @staticmethod
    def _direct_assertion(sent: str, m: "re.Match[str]", lo: int, hi: int) -> bool:
        """声明是否是对本事项的直接断言（见 DECL_SUBJECT_OK、DECL_TAIL_OK）。匹配带“程序倒置”字样的声明才检查句式；
        “未履行决策程序”“程序存在瑕疵”“该做法违反……规定”这类自带主语的写法只检查前面没有别的主语。"""
        before = sent[lo:m.start()].strip()
        if before and not DECL_SUBJECT_OK.match(before):
            return False
        tail = sent[m.end():hi].strip()
        if not tail:
            return True
        if DECL_TAIL_THEN.match(tail):
            return not DECL_WORD_FORMS.search(m.group(0))
        return bool(DECL_TAIL_OK.match(tail))

    def _locate(self, line: int, pos: int) -> int:
        """第 line 行（下标）pos 位置所在句子在 sents 里的下标；找不到返回 -1。"""
        best = -1
        for k, s in enumerate(self.sents):
            if s.line < line:
                continue
            if s.line > line:
                break
            if s.start <= pos:
                best = k
        return best

    def neighbours(self, line: int, pos: int) -> Tuple[str, str, str]:
        """(前一句, 本句, 后一句)；前后句只认同一行或紧挨着的上一行、下一行，没有的写空串。"""
        k = self._locate(line, pos)
        if k < 0:
            return "", "", ""
        cur = self.sents[k]
        prv = self.sents[k - 1] if k > 0 and cur.line - self.sents[k - 1].line <= 1 else None
        nxt = self.sents[k + 1] if k + 1 < len(self.sents) and self.sents[k + 1].line - cur.line <= 1 else None
        return (prv.text if prv else ""), cur.text, (nxt.text if nxt else "")

    def declared_in(self, text: str) -> bool:
        return bool(text) and self._has_decl(text, self.rx["decl"])

    def near_declared(self, line: int, pos: int) -> bool:
        return any(self.declared_in(t) for t in self.neighbours(line, pos) if t)

    def _step_ok(self, a: int, b: int) -> bool:
        """第 a、b 句（a < b）之间每一步都在同一行或紧挨着的下一行（中间不隔空行、不隔别的行）。"""
        return all(0 <= j - 1 and j < len(self.sents) and self.sents[j].line - self.sents[j - 1].line <= 1
                   for j in range(a + 1, b + 1))

    def scope(self, k: int) -> Tuple[List[str], List[int]]:
        """第 k 句（倒置句）的追认补办检查范围：倒置句及其前一句、后一句；以及其中带声明的句子及其后两句。
        返回 (范围内各句文字, 带声明的句子下标)。“追认、补办”写在声明之后隔一句的，也能被看到。"""
        idx = {k}
        if k - 1 >= 0 and self._step_ok(k - 1, k):
            idx.add(k - 1)
        if k + 1 < len(self.sents) and self._step_ok(k, k + 1):
            idx.add(k + 1)
        declared = [i for i in sorted(idx) if self.declared_in(self.sents[i].text)]
        for i in declared:
            for d in (1, 2):
                if i + d < len(self.sents) and self._step_ok(i, i + d):
                    idx.add(i + d)
        return [self.sents[i].text for i in sorted(idx)], declared

    def near_normalized(self, line: int, pos: int) -> bool:
        """倒置句及前后一句、声明所在句及其后两句里有追认、补办。"""
        k = self._locate(line, pos)
        if k < 0:
            return False
        texts, _decl = self.scope(k)
        return any(self.rx["normalize"].search(t) for t in texts)

    def adjust(self, level: str, line: int, pos: int) -> str:
        """regex 命中的级别调整：P0 在“就近有未被否定、且是对本事项直接断言的肯定式声明，并且追认、补办检查范围里没有追认补办”时降为 P1；
        其他级别不动。"""
        if level != "P0":
            return level
        if self.near_declared(line, pos) and not self.near_normalized(line, pos):
            return "P1"
        return level


def find_inversions(lines: Sequence[str], cfg: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """程序倒置组合判定（提示性质，命中一律为 P1）。

    lines：文书各行文字（一行一项，行号 = 下标 + 1）。
    cfg：规则 JSON 里的 procedure_inversion 对象；认 rule_id（默认 HOS-034），以及 exec、exec_sign、exec_done、exec_start、
    exec_dated、exec_neg、prior_ok、req、other_obj、post_obj、decl、decl_neg、normalize 等可选正则
    （缺省用本模块常量；注意 cfg 里写了 exec 只覆盖 E1，其余档位仍用默认）。types 由调用方判断，这里不看。

    判定：
      1. 同一句里有“已执行”（E1～E4）和“提请或补办”（REQ）-> P1（reason_code same_sentence）；
         已执行在本句、提请或补办在紧邻的下一句 -> P1（adjacent）；
      2. 只有“于X月开工、投入使用”这类没有“已”字的写法（E5）-> P1（weak_exec）；
      3. 已执行前面同分句有否定，或本句前面写了“审议通过后”等先批准再执行的表述，或已执行成分作定语（已建成的……）-> 不判；
      4. 是不是同一事项：提请对象里有二期、续签、新购等新事项标记时，已执行对象（动词后 8 字）不少于 2 字且不在提请对象里 -> 不判
         （“已建成胸痛中心……审议创建卒中中心的方案”），为空或在提请对象里 -> P1（other_item）；
         提请对象是验收、结算、备案、收费标准、管理办法、计划、预算等事后正常事项且没有追认、补办 -> 不判；
      5. 就近（本句、前句、后句）有肯定式声明、且没有追认补办 -> reason_code declared（仍是 P1，只换文案）；
         命中处就近写了“追认”“补办” -> reason_code normalize（仍是 P1：追认、补办的 P0 由各包的正则规则负责）。
    返回 [{"id","line","level","start","end","excerpt","reason","reason_code","reason_codes","declared"}]：
    level 恒为 "P1"；start/end 是该行内的摘录区间；declared 表示就近（本句、前后句）有声明，引擎据此对该命中不再适用“处置类”豁免；
    reason_code 供引擎按原因换文案（normalize、declared、other_item、adjacent、weak_exec、same_sentence，按此优先级取第一个成立的）。"""
    cfg = cfg or {}
    rule_id = str(cfg.get("rule_id") or "HOS-034")
    decl = Declaration(lines, cfg)
    rx = decl.rx
    sents = decl.sents
    results: List[Dict[str, Any]] = []
    for k, cur in enumerate(sents):
        got = _first_valid_exec(cur.text, rx)
        if got is None:
            continue
        em, weak = got
        nxt = sents[k + 1] if k + 1 < len(sents) and sents[k + 1].line - cur.line <= 1 else None
        prv = sents[k - 1] if k > 0 and cur.line - sents[k - 1].line <= 1 else None
        rm = rx["req"].search(cur.text)
        same = rm is not None
        req_sent = cur
        if rm is None and nxt is not None:
            rm = rx["req"].search(nxt.text)
            req_sent = nxt
        if rm is None:
            continue
        req_seg = req_sent.text[rm.start():]
        normalize = bool(rx["normalize"].search(cur.text) or rx["normalize"].search(req_sent.text))
        if rx["post_obj"].search(req_seg) and not rx["normalize"].search(req_seg) and not normalize:
            continue    # 验收、结算、备案、收费标准、管理办法、计划、预算等事后正常事项
        codes: List[str] = []
        if weak:
            codes.append("weak_exec")
        if not same:
            codes.append("adjacent")
        if rx["other_obj"].search(req_seg):
            obj = _exec_object(cur.text, em)
            if len(obj) >= 2 and obj not in req_seg and not normalize:
                continue    # 已执行的与提请的不是同一件事
            codes.append("other_item")
        near = [s.text for s in (prv, cur, nxt) if s is not None]
        if req_sent is not cur and req_sent is not nxt:
            near.append(req_sent.text)
        scope_texts, _declared_idx = decl.scope(k)
        near_norm = normalize or any(rx["normalize"].search(t) for t in near + scope_texts)
        declared = any(decl.declared_in(t) for t in near) or bool(_declared_idx)
        if declared and not near_norm:
            codes.append("declared")
        if near_norm:
            codes.append("normalize")
        if same:
            s0 = min(em.start(), rm.start())
            e0 = max(em.end(), rm.end())
        else:
            s0, e0 = em.start(), len(cur.text)
        s0 += cur.start
        e0 += cur.start
        excerpt = lines[cur.line][s0:min(e0, s0 + EXCERPT_LIMIT)]
        ordered = [c for c in REASON_CODES if c in codes]
        primary = ordered[0] if ordered else ("same_sentence" if same else "adjacent")
        texts = (["同句"] if same else []) + [REASON_TEXT[c] for c in ordered]
        results.append({"id": rule_id, "line": cur.line + 1, "level": "P1", "start": s0, "end": e0,
                        "excerpt": excerpt, "reason": "、".join(texts), "reason_code": primary,
                        "reason_codes": ordered, "declared": declared})
    return results
