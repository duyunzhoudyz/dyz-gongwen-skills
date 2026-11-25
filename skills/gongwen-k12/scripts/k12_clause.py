"""中小学文书分句图。保留原文坐标，不涉及规则级别。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path


class _TextEnum(str, Enum):
    __str__ = str.__str__


class Context(_TextEnum):
    ASSERTION = "陈述"
    REQUIREMENT = "要求"
    NEGATION = "禁令或否定"
    CONDITION = "假设或条件"
    QUOTE = "转述或引用"
    REFUTATION = "辟谣"
    QUESTION = "疑问"
    GOVERNANCE = "治理或处置"
    NOTICE = "通知式固定引导"
    UNKNOWN = "未知"


class Polarity(_TextEnum):
    POSITIVE = "肯定"
    NEGATIVE = "否定"
    UNKNOWN = "判断不了"


class Admission(_TextEnum):
    MAIN = "句首主句"
    NOTICE = "紧邻通知首项"
    PARALLEL = "独立并列"


class Binding(_TextEnum):
    PROHIBITED = "后置禁令"
    REFUTED = "已辟谣"
    ACCOUNTABILITY = "事后处置"
    QUESTION = "提问"
    REJECTED = "提议未实行"
    HISTORICAL = "历史叫停，当前未实行"
    HALTED = "叫停，实施不明"
    UNRESOLVED = "后置评价待核"


class Tail(_TextEnum):
    DETAIL = "执行细化"
    EVALUATION = "回指评价"
    INDEPENDENT = "独立行为"


@dataclass(frozen=True)
class Span:
    """行、列从 1 开始。全文和行列区间均左闭右开，按 Unicode 字符计。"""
    start: int
    end: int
    line: int
    column: int
    end_line: int
    end_column: int


@dataclass(frozen=True)
class Group:
    kind: str
    span: Span
    content: Span


@dataclass
class Frame:
    id: int
    kind: str
    context: Context
    evidence: Span
    source: int
    clauses: list[int] = field(default_factory=list)
    actions: list[int] = field(default_factory=list)
    scope: Span | None = None


@dataclass
class Clause:
    id: int
    sentence: int
    span: Span
    text: str
    paragraph: int
    separator: str = ""
    connector: str = ""
    parent: int | None = None
    previous: int | None = None
    following: int | None = None
    list_block: int | None = None
    table: int | None = None
    row: int | None = None
    column: int | None = None
    project: int | None = None
    table_header: bool = False
    column_header: str = ""
    frames: tuple[int, ...] = ()
    groups: tuple[Group, ...] = ()
    context: Context = Context.UNKNOWN
    admission: Admission | None = None
    admission_evidence: Span | None = None
    tail: Tail | None = None
    malformed: bool = False


@dataclass
class Action:
    id: int
    clause: int
    predicate: str
    span: Span
    context: Context
    polarity: Polarity
    local_polarity: Polarity
    agent: str = ""
    agent_span: Span | None = None
    school_agent: bool = False
    agent_inherited: bool = False
    object: str = ""
    object_span: Span | None = None
    recipient: str = ""
    recipient_span: Span | None = None
    project: int | None = None
    timing: str = ""
    admission: Admission | None = None
    admission_evidence: Span | None = None
    mandatory: bool = False
    uniform: bool = False
    voluntary: bool = False
    exit: bool = False
    refusal: bool = False
    consequence: bool = False
    conditions: tuple[int, ...] = ()
    parent: int | None = None
    attributive: bool = False
    fixed_notice: bool = False
    negation: Span | None = None
    binding: Binding | None = None
    binding_clause: int | None = None
    reason: str = ""


@dataclass
class Project:
    id: int
    label: str
    evidence: Span
    clauses: list[int] = field(default_factory=list)


@dataclass
class ClauseGraph:
    text: str
    clauses: list[Clause] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    _by_clause: dict[int, list[Action]] = field(default_factory=dict, repr=False)

    def actions_for(self, clause: int) -> tuple[Action, ...]:
        return tuple(self._by_clause.get(clause, ()))

    def polarity(self, clause: int, predicate: str) -> Polarity:
        """同一分句的同名动作有歧义时，调用者可按 actions_for() 的位置区分。"""
        states = {action.polarity for action in self.actions_for(clause)
                  if action.predicate == predicate and not action.attributive}
        return states.pop() if len(states) == 1 else Polarity.UNKNOWN


def _alternatives(words):
    return "|".join(re.escape(word) for word in sorted(set(words), key=lambda word: (-len(word), word)))


# 口径 §2 切分，方案 §二、§三。
_PAIRS = dict(zip("（([［【〔《〈“‘「『", "）)]］】〕》〉”’」』"))
_TITLES = "《〈"
_QUOTES = "\"'“‘「『"
_SENTENCE_END = "。！？!?．."
_BREAKS = _SENTENCE_END + "，,；;：:"
_LINE_ENDS = "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"
_LIST = re.compile(r"(?P<indent>[ \t　]*)(?:(?:[-+*][ \t]+)|[•●▪·][ \t]*|"
                   r"(?:(?:[（(][0-9一二三四五六七八九十百]+[）)])|"
                   r"(?:[0-9一二三四五六七八九十百]+[、）)]|[0-9]+\.(?!\d))))[ \t　]*")
_HEADING = re.compile(r"\s*(?:#{1,6}\s|(?:第[一二三四五六七八九十\d]+[章节条])|【[^】]+】\s*$)")
_JOIN = ("而是", "但是", "但", "另", "以及", "或者", "同时", "还", "并", "且", "和", "或", "、")
_PARALLEL = {"并", "且", "及", "以及", "和", "、", "或", "或者"}
_TURN = {"但", "但是", "另", "而是"}
_ATOMIC_JOIN = ("并非", "并不", "并列", "同时期", "还款", "还原", "归还", "退款", "和谐", "另行")
_ITEM_COLUMN = re.compile(r"(?:(?:收费|缴费|征订|购买|服务)(?:的)?)?(?:项目|品名|名称)(?:名称|列)?(?:[一二三四\d]+)?")
_TABLE_DIVIDER = re.compile(r":?-{3,}:?")

# 口径 §1 句首白名单、§2 语境与回绑、§3.1–3.4 槽位。
_SCHOOL = ("学校", "本校", "我校", "教师", "老师", "班主任", "副班主任", "各班", "年级组", "各年级组", "教务处")
_OTHER_AGENT = ("家长委员会", "家委会", "全体学生", "所有学生", "全体家长", "学生", "新生", "同学们", "同学", "家长",
                "各班家长", "校外培训机构", "校外辅导机构", "财务会议", "教代会", "校务会",
                "家庭", "财务室", "每生", "该生", "本人")
_AGENT = re.compile(r"(?:本校|我校|任课|在职|各位|任何)?(?:" +
                    _alternatives(_SCHOOL + _OTHER_AGENT) + r")"
                    r"(?:(?:和|与)(?:班主任|老师|教师|年级组))?")
_PERSON = re.compile(r"(?:学生[\u4e00-\u9fff]{2,4}(?=属于|患有|被记过|系|是|享受|登记|认定)"
                     r"|[\u4e00-\u9fff]{2,4}同学|[A-Z]\d{2,4}|你)")
_NOTICE = {"收费通知", "关于课后服务收费的通知", "现通知如下", "经研究决定"}
_BRIDGE = {"要求", "强迫", "强制", "组织", "安排", "动员", "允许", "让"}
_DISCUSSION = {"商议", "审议", "提出建议"}
_PROHIBITION = ("严禁", "禁止", "不得", "不准", "切勿", "不可", "不要", "请勿")
_NEGATIVE = ("不会", "不能", "未曾", "尚未", "不再", "没有", "不予", "拒绝", "拒", "不", "未")
_DOUBLE = ("绝非不", "并非不", "不得不", "不可能不", "不会不", "不能不", "无不", "没有不")
_NOT_NEGATION = ("不断", "不同", "不理想", "不达标", "不少于", "不超过", "不低于", "不及", "不管", "不论",
                 "不便", "不足", "不仅", "不但", "不只", "不光", "不止", "不单", "不一", "不等", "不均", "不定期", "不定时")
_TOKENS = re.compile(_alternatives(_NOT_NEGATION + _DOUBLE + _PROHIBITION + _NEGATIVE + ("不是不", "并非")))
_NONNEG_PREFIX = re.compile(r"不断|不定期|不定时|不仅|不但|不只|不光|不止|不单")
_MODAL = re.compile(r"即日起|必须|一律|统一|务必|按标准|按规定|须|应当|应|现|将(?!学生|家长|名单|成绩|资料)|请|均|仍|已(?:经)?|曾")
_MANDATORY = {"必须", "一律", "务必", "须", "应当", "应", "强迫", "强制"}
_MANNER = re.compile(r"私下|变相|再次|强行|随意|现场|继续|直接|分别|集中|共同|主动|自愿|义务|经常|多次|定期")
_TIME = (r"(?:(?:本|下|每)?(?:星?期|周)[一二三四五六日天末]|本周|下周|每周|寒暑假|寒假|暑假|"
         r"(?:在|于)?开学(?:第[一二三四五六七八九十\d]+周)?|次日|今天|今日|明[天日]|即日|"
         r"\d{1,4}(?:年\d{1,2})?月\d{1,2}[日号]|\d{1,2}[点时](?:\d{1,2}分)?|"
         r"\d{1,2}[:：]\d{2})(?:上午|下午|放学)?(?:之前|之后|前|后)?")
_TIME_RE = re.compile(_TIME)
_PREP = re.compile(
    r"(?P<marker>在|于|向|对|给|把|将|为|按|面向)"
    r"(?P<value>" + _TIME
    + r"|(?:校外|[\ufffc]+|[\u4e00-\u9fff]{0,8}?)(?:培训机构|辅导机构|补习班)"
      r"|(?:本校|校内|校外|家长群|班群|班级群|微信群|公告栏|课堂|学校|指定门店|教室|会议上|教代会上)"
      r"|(?:留守儿童|残疾学生|贫困学生|困难学生|单亲家庭|供电公司|每生)"
      r"|(?:已)?(?:交费|缴费|报名)的(?:家长|学生)"
      r"|(?:全体|全部|全班|各班|本班|本学期|期末|本次|考试|学生|家长|新生|家委会|家长委员会|班主任|教师|"
      r"校外|成绩|分数|排名|准考证|学号|名单|资料|通讯录|联系方式|电话|材料|[\ufffc])+"
      r"(?:的?(?:联系人|名单|通讯录|电话|微信号|信息|联系方式|成绩单|成绩|排名|分数|学号|生源|机构|培训机构|辅导机构))*"
      r")"
)
_RECEIVER = re.compile(r"(?:家长群|学生|家长|班主任|教师|老师|财务室|教务处|家委会|家长委员会|"
                       r"学校|本校|各班|供电公司|收费窗口|[^，。；、\s]{0,22}(?:培训机构|辅导机构|补习班|书店|机构|平台))")
_CENTRE = re.compile(r"的(?:全体)?(?:学生|新生|同学|家长|家庭|班级|人员)(?!名单|姓名|电话|微信|信息|成绩)")
_REFUSAL = re.compile(r"(?:(?:尚)?未|没有|不|拒)(?:统一|按期)?(?:缴纳|交纳|上交|交齐|缴齐|缴费|缴|交费|交款|"
                      r"购买|订购|征订|订阅|办理保险|买|订)")
_FEES = ("收取", "代收", "收缴", "缴纳", "交纳", "上交", "交齐", "缴齐", "购买", "订购", "征订", "订阅", "办理",
         "收费", "缴费", "交费", "付款", "缴", "买", "收", "订", "免收", "退费", "减免")
_CONSEQUENCES = ("发教材", "发放教材", "发学习用品", "报名", "登记", "入校", "入班", "进入", "参加评优",
                 "参加", "参与", "领取", "进教室", "取消评先资格", "取消评优资格")
_IDENTITY = ("属于", "系", "是", "认定为", "登记为", "确诊为", "患有", "享受助学金",
             "受处分", "被处分", "被记过", "受到处分")
_IDENTITY_OBJECT = re.compile(r"贫困|低保|资助|受助|留守|特困|单亲|残疾|残障|孤儿|患病|病|处分|家庭|随班就读")
_PREDICATES = re.compile(_alternatives(
    (*_BRIDGE, *_FEES, *_CONSEQUENCES, *_IDENTITY, "参加培训", "公布", "张贴", "通报", "公示",
     "排名", "排座", "分班", "发布", "晒", "公开", "宣布", "记录", "完成", "推荐", "介绍", "输送", "透露",
     "发成绩", "告知", "写明", "签订", "提出建议", "审议", "商议", "归入", "设立", "填报", "联系",
     "泄露", "提供", "提供给", "发给", "发送", "发送给", "转交", "移交", "交给", "交由", "发到",
     "到岗", "取消减免", "取消评优资格", "离校", "外出", "报送", "开展", "辅导", "培训", "培训学生", "咨询",
     "送去", "捐赠", "帮助", "讲解", "服务", "陪伴", "募集", "补习功课", "义务辅导", "执行", "支付",
     "决定", "前往", "接收", "签收", "留存", "存档", "归档", "退还", "开具", "核算", "确认", "劝阻",
     "提议", "否决", "采纳", "叫停", "查处", "整治", "制止", "追责", "处分", "收费标准", "立案查处")
))
# 动词同形的名词复合词，见口径 §3。剔除词边界假命中。
_NOUN_ENDINGS = {
    "收": r"入|支|据|费|取|缴|款人", "缴": r"纳|费|齐", "收费": r"标准|依据|项目|方式|情况|行为|管理|通知|单位|窗口",
    "服务": r"费|时间|项目|收费|工作|人员|中心|活动|情况|实行|自愿|[的：:]",
    "培训": r"机构|班|费|中心|学校|项目|活动|的", "排名": r"情况|名单|表|结果|数据",
    "参加": r"人数|人员|率", "报名": r"费|表|时间|流程|标准|条件|情况|人数",
    "购买": r"标准|方式|时间|的记录", "订": r"单|金|购|阅", "登记": r"栏|簿|表|类别|册", "处分": r"情况|决定",
    "决定": r"书|的", "公开": r"信息栏", "组织": r"机构|委员|者", "介绍": r"信", "发给": r"的",
    "联系": r"方式|电话|人",
}
_NOUN_PREFIX = {"服务": ("课后", "志愿"), "培训": ("校外", "教育", "有偿", "免费", "教学", "师资", "能力", "集中"),
                "排名": ("的", "考试", "学生", "班级"),
                "收费": ("校外", "非", "校内", "代"), "购买": ("的",), "收费标准": ("的",)}
_NOUN_SUFFIX_RE = {verb: re.compile(pattern) for verb, pattern in _NOUN_ENDINGS.items()}
_ACTION_CONTINUATION = re.compile(r"(?:的|者|之后|以后|后|随即|然后|再|便|则|由|交由|为|向|把|将|"
                                  r"学校|各班|班主任|不|未|没有|不得|不予|严禁|须|必须|一律|统一|已|过)")
_FIXED_PREFIX = re.compile(r"按自愿原则|以自愿原则|按期|完全自愿|依照规定|以任何名义|"
                           r"(?:进行|搞)(?=成绩排名|排名)|上交前|每学期|每学月|每月|"
                           r"凡(?=未|已|自愿|组织|参加|购买)|可自行|可自由|可(?=自愿|购买|退出)|"
                           r"全体义务教育阶段(?=学生)|开学第一周(?=星期|周)")
_TOPIC = re.compile(r"考试成绩(?:排名)?|期末考试|考试排名|成绩单|排名(?=不会不|不能不|不得不)|"
                    r"课后服务(?:费)?|校服(?:费)?|教辅(?:资料)?|意外伤害保险(?:费)?|研学(?:费用|活动|费)?|"
                    r"报刊|本项目|本项|本次研学活动|资料费|班费|成绩")
_JOIN_SIGNAL = re.compile(r"(?:现|须|应|必须|一律|统一|将|仍|已)")
_EXIT = re.compile(r"不参加不收费|不参加不缴费|未报名不收费|不报名不收费|不购买不收费|"
                   r"可自行(?:购买|订购)|不作强制要求|不强制|可(?:自由)?退出|可自愿选择是否参加")
_PROJECT = re.compile(r"课后服务(?:费|收费)?|研学(?:活动|旅行|费|费用)?|意外伤害保险(?:费)?|"
                      r"校服(?:费)?|教辅(?:资料|材料|费)?|资料费|材料费|班费|活动费|报名费|"
                      r"报刊|练习册|安全手册|补习费|保险费|教材")
_PROJECT_CELL = re.compile(r"(?:[^\d，；：|。]{1,18})(?:费|保险|手册|教材|资料|校服|教辅|报刊|服务|活动|研学|练习册)")
_AMOUNT = re.compile(r"(?<!\d)\d+(?:,\d{3})*(?:\.\d+)?\s*元")
_POST_NEG = re.compile(r"(?:是)?(?:绝对)?(?:不可能|不行|根本不行|做不到)(?:的)?$|怎么行$")
_PARTICLES = "吧啊呀吗呢"
_POST_FEASIBLE = re.compile(r"并非(?:不可行|不能|不可以|不可能)$|并不(?:可行|现实)$")
_UNKNOWN_STANCE = re.compile(r"^(?:拟|拟议|提议|建议研究|考虑|有人建议|可能|疑似|据说|计划讨论|待定)")
_STANCE_SUFFIX = re.compile(r"(?:只是|仅为|尚属)(?:提议|建议|设想|传闻)$|(?:尚待|有待)(?:讨论|研究|决定)$")
_FRAME_SHAPE = re.compile(r"(?:须知|如下|下列|以下|这种做法|这种说法|一项提议|一项方案)$")
_PRECONDITION = re.compile(r"^(?:如果|若(?:发现)?|如有|如发现|一旦|凡(?:发现|利用)|发现|假如)")
_REFERRAL = re.compile(r"^(?:针对|对于|关于|就)(?=\S)")
_SOURCE = re.compile(r"^(?:网传(?:谣言)?(?:称)?|传闻(?:称)?|据(?:反映|举报|传言)|匿名举报(?:称)?|"
                     r"某外校曾发生|外校曾发生|他校曾发生|往年(?:曾)?|据报道|有人(?:称|说))")
_GOVERNANCE = re.compile(r"(?:严肃查处|严查|专项(?:整治|督查|清查|治理|检查)|通报批评|展开排查|"
                         r"严肃追责|依法依规严肃追责|坚决制止|开展调查|予以处分|取消评优资格)")
_INTRO = (
    (Context.NEGATION, r"(?:(?:本校|我校|学校))?(?:严禁|禁止|不得)(?:(?:作出|实施|有|出现))?"
                       r"(?:以下|下列|如下|此类|下述)?(?:行为|情形|情况|规定|做法|事项|问题)?"),
    (Context.NEGATION, r"(?:经排查|经核查)未发现(?:以下|下列|如下)(?:问题|行为|情形)"),
    (Context.CONDITION, r"(?:如果|若|如)发生(?:如下|以下|下列)(?:情形|情况|问题)"),
    (Context.GOVERNANCE, r"(?:校务会|财务会议|教代会)驳回了?(?:以下|如下|下列)(?:提议|方案)"),
    (Context.QUOTE, r"(?:网传谣言称|据举报|匿名举报称|传闻称|学校公布承诺书)"),
)
_INTRO_RE = tuple((context, re.compile(pattern)) for context, pattern in _INTRO)
_BACKREF = re.compile(r"^(?:为其|对其|此|该|这|上述|这种做法|前述|传闻|谣言|说法|所述|全体学生一律执行)")
_BACK_BIND = (
    (Binding.REFUTED, r"(?:经(?:核实|核查|调查)(?:并)?不属实|查无实据)"),
    (Binding.PROHIBITED, r"(?:一律禁止|坚决反对|坚决零容忍)"),
    (Binding.ACCOUNTABILITY, r"(?:已(?:启动问责|遭处分|立案查处|被问责|被处分)|立案查处)"),
    (Binding.REJECTED, r"(?:已被否决|未予采纳|已否决|未获通过)"),
    (Binding.HALTED, r"(?:叫停|停止实施)"),
    (Binding.QUESTION, r"是否"),
)
_BACK_BIND_RE = tuple((binding, re.compile(pattern)) for binding, pattern in _BACK_BIND)
_DETAIL = re.compile(r"(?:(?:请|须|于|在|限于)?(?:" + _TIME + r")(?:前|后)?"
                     r"(?:缴费|付款|交费|收取|上交|交齐|缴纳|支付|交)?[^，。！？]*"
                     r"|(?:请|统一|逾期前)?(?:交给|交至|交到|汇至|由)[^，。！？]{1,23}"
                     r"|(?:金额|每人|每生|每学期|标准|收费标准)?(?:为|共计|合计)?\s*"
                     r"\d+(?:,\d{3})*(?:\.\d+)?\s*元"
                     r"|(?:通过|使用)(?:指定|学校)?(?:缴费平台|支付平台|银行转账|现金|扫码)(?:缴费|支付)?)")
_FIXED_NOTICE = re.compile(r"(?:不同年级的学生一律须|全年级不少于八成的同学须|未分班的新生须)(?:在|于)?")
_REFUSAL_CENTRE = re.compile(r"(?:者|的(?=\s*$))")
_ATTRIBUTIVE_ENTRY = re.compile(r"^(?:凡|已|尚|未|没|不|拒|成绩|经济|家庭|贫困|首批|全年级|全班|上周|本周|"
                                r"参加|报名|购买|缴费|交费|缴纳|分班|在读|在校|符合|随班|住宿|住校|来校)")
_RECORDED = re.compile(r"(?:已(?:经)?(?:统一|实际)?(?:实施|执行|组织|开展|购买|订购|收取|缴纳)|"
                       r"实施后|执行后|发生后|已实际)")
_HISTORICAL = re.compile(r"往年|去年|历史上|当年|未实行|未实施|当前未")
_INTAKE_TAIL = re.compile(r"(?:一律执行|均须执行|均须参加|必须参加)$")

def _number_separator(text, index):
    return (0 < index < len(text) - 1 and text[index - 1].isdigit()
            and text[index + 1].isdigit()
            and (text[index] in ".．:：" or
                 (text[index] in ",，" and re.match(r"\d{3}(?!\d)", text[index + 1:index + 5]))))


def _pairs(text, start=0):
    """收集完整配对。未配对字符保留在可扫描层，由调用者标待核。"""
    stack, pairs, bad = [], {}, set()
    straight, straight_ends = {}, {}
    escaped = set()
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            escaped.add(index + 1)
            index += 2
            continue
        if char in _LINE_ENDS or char in _SENTENCE_END and not _number_separator(text, index):
            straight.clear()
        if char in "\"'" and not (char == "'" and 0 < index < len(text) - 1
                                    and text[index - 1].isascii() and text[index - 1].isalnum()
                                    and text[index + 1].isascii() and text[index + 1].isalnum()):
            if char in straight:
                left = straight.pop(char)
                straight_ends[left] = index
            else:
                straight[char] = index
            bad.add(index)
        index += 1

    straight_closers = set(straight_ends.values())
    for index in range(start, len(text)):
        if index in escaped:
            continue
        char = text[index]
        if index in straight_closers:
            if stack and straight_ends.get(stack[-1][1]) == index:
                _, left = stack.pop()
                pairs[left] = index
        elif char in _PAIRS or index in straight_ends:
            stack.append((char, index))
        elif char in _PAIRS.values():
            if stack and _PAIRS.get(stack[-1][0]) == char:
                _, left = stack.pop()
                pairs[left] = index
            else:
                bad.add(index)
    bad.update(index for _, index in stack)
    bad.difference_update(pairs)
    bad.difference_update(pairs.values())
    return pairs, bad, escaped


def _visible_positions(start, end, pairs):
    index = start
    while index < end:
        right = pairs.get(index)
        if right is not None and right < end:
            index = right + 1
        else:
            yield index
            index += 1


def _verb_matches(text):
    for match in _PREDICATES.finditer(text):
        verb = match[0]
        suffix = _NOUN_SUFFIX_RE.get(verb)
        if suffix and suffix.match(text, match.end()):
            continue
        if text.endswith(_NOUN_PREFIX.get(verb, ()), 0, match.start()):
            continue
        if verb in _IDENTITY and verb in {"系", "是", "属于"} and not _IDENTITY_OBJECT.search(text, match.end()):
            continue
        yield match


def _connector(text, index, start, end, verbs, breaks):
    if text.startswith(_ATOMIC_JOIN, index):
        return ""
    for join in _JOIN:
        if not text.startswith(join, index):
            continue
        right = index + len(join)
        if right >= end or text[right] in _BREAKS:
            return ""
        if join in _TURN:
            return join
        left_verb = bisect_left(verbs, start)
        right_verb = bisect_left(verbs, right)
        next_break = breaks[bisect_left(breaks, right)]
        if (left_verb < len(verbs) and verbs[left_verb] < index
                and right_verb < len(verbs) and verbs[right_verb] < next_break):
            if (join == "、" and verbs[right_verb] != right
                    and not text.startswith(_PROHIBITION + _NEGATIVE, right) and not _MODAL.match(text, right)):
                return ""
            return join
        return ""
    return ""


def _parts(text, start, end, pairs, escaped):
    """产出左闭右开区间、右界和左侧并列词。"""
    positions = list(_visible_positions(start, end, pairs))
    breaks = [i for i in positions if i not in escaped and text[i] in _BREAKS
              and not _number_separator(text, i)] + [end]
    # 字符扫描只做一次。谓词索引供多个并列词共用。
    visible = [" "] * (end-start)
    for index in positions:
        visible[index-start] = text[index]
    verbs = [start+match.start() for match in _verb_matches("".join(visible))]
    previous = ""
    for index in positions:
        if index < start or index in escaped:
            continue
        char = text[index]
        if char in _BREAKS and not _number_separator(text, index):
            yield start, index, char, previous
            start, previous = index + 1, ""
        elif char in "而但另以或同还并且和、":
            join = _connector(text, index, start, end, verbs, breaks)
            if join:
                yield start, index, join, previous
                start, previous = index + len(join), join
    yield start, end, "", previous


def _trim(text, start, end):
    while start < end and text[start].isspace():
        start += 1
    while start < end and text[end - 1].isspace():
        end -= 1
    return start, end


def _table_cells(text, start, pairs, escaped):
    bars = [index for index in _visible_positions(start, len(text), pairs)
            if text[index] == "|" and index not in escaped]
    if not bars:
        return []
    left = not text[start:bars[0]].strip()
    right = not text[bars[-1]+1:].strip()
    if len(bars) < 2 and (left or right):
        return []
    cuts = ([] if left else [start-1]) + bars + ([] if right else [len(text)])
    return [_trim(text, a+1, b) for a, b in zip(cuts, cuts[1:])]


def _intro(text):
    if text in _NOTICE:
        return Context.NOTICE
    return next((context for context, pattern in _INTRO_RE if pattern.fullmatch(text)), Context.UNKNOWN)


def _scan_line(line):
    marker = _LIST.match(line)
    if marker and not line[marker.end():].strip():
        marker = None
    start = marker.end() if marker else 0
    pairs, bad, escaped = _pairs(line, start)
    cells = _table_cells(line, start, pairs, escaped)
    divider = bool(cells and all(_TABLE_DIVIDER.fullmatch(line[a:b]) for a, b in cells))
    return line, marker, start, pairs, bad, escaped, cells, divider


class _Builder:
    def __init__(self, text):
        self.graph = ClauseGraph(text)
        self.lines = text.splitlines(keepends=True)
        self.offsets = [0]
        for line in self.lines:
            self.offsets.append(self.offsets[-1] + len(line))
        self.paragraph = 0
        self.sentence = 0
        self.siblings = {}
        self.header = None
        self.header_columns = []
        self.table = self.row = self.list_count = 0
        self.tables = {}
        self.open_frame = None

    def span(self, start, end):
        line = bisect_right(self.offsets[:-1], start) - 1
        last = bisect_right(self.offsets[:-1], max(start, end-1)) - 1
        return Span(start, end, line+1, start-self.offsets[line]+1, last+1, end-self.offsets[last]+1)

    def frame(self, kind, context, evidence, source):
        frame = Frame(len(self.graph.frames), kind, context, evidence, source)
        self.graph.frames.append(frame)
        return frame.id

    def project(self, label, span):
        project = Project(len(self.graph.projects), label, span)
        self.graph.projects.append(project)
        return project.id

    def clause(self, start, end, separator, connector, *, frames=(), parent=None,
               list_block=None, table=None, row=None, column=None, project=None, groups=(),
               malformed=False, table_header=False, column_header=""):
        graph = self.graph
        span = self.span(start, end)
        clause = Clause(len(graph.clauses), self.sentence, span, graph.text[start:end], self.paragraph,
                        separator=separator, connector=connector, parent=parent,
                        list_block=list_block, table=table, row=row, column=column,
                        project=project, frames=frames, groups=groups, malformed=malformed,
                        table_header=table_header, column_header=column_header)
        key = self.sentence, parent
        clause.previous = self.siblings.get(key)
        if clause.previous is not None:
            graph.clauses[clause.previous].following = clause.id
        self.siblings[key] = clause.id
        graph.clauses.append(clause)
        for frame_id in frames:
            frame = graph.frames[frame_id]
            frame.clauses.append(clause.id)
            frame.scope = self.span(min(frame.scope.start, start), max(frame.scope.end, end)) if frame.scope else span
        if project is not None:
            graph.projects[project].clauses.append(clause.id)
        return clause

    def line_parts(self, line, offset, start, end, pairs, bad, escaped, *, frames=(), parent=None, **position):
        last_header = None
        for left, right, separator, connector in _parts(line, start, end, pairs, escaped):
            left, right = _trim(line, left, right)
            if left < right:
                # 内联冒号框留在同句，下一句及下一段不会继承。
                if self.open_frame is not None:
                    open_frame = self.graph.frames[self.open_frame]
                    subject = _AGENT.match(line, left, right)
                    if (open_frame.context == Context.NEGATION and open_frame.clauses and subject
                            and _JOIN_SIGNAL.match(line, subject.end(), right)):
                        self.open_frame = None
                active = frames + ((self.open_frame,) if self.open_frame is not None else ())
                active = tuple(dict.fromkeys(active))
                groups = self.groups(line, offset, left, right, pairs)
                clause = self.clause(left + offset, right + offset, separator, connector, frames=active,
                                     parent=parent, groups=groups,
                                     malformed=any(left <= index < right for index in bad), **position)
                saved = self.open_frame
                self.open_frame = None
                for group in groups:
                    inner = self.graph.text[group.content.start:group.content.end]
                    if group.kind == "title" or not any(_verb_matches(inner)):
                        continue
                    kind = "quote" if group.kind == "quote" else "annotation"
                    context = Context.QUOTE if kind == "quote" else Context.UNKNOWN
                    child_frame = self.frame(kind, context, group.span, clause.id)
                    self.line_parts(line, offset, group.content.start-offset, group.content.end-offset,
                                    pairs, bad, escaped, frames=active + (child_frame,),
                                    parent=clause.id, **position)
                self.open_frame = saved
                if separator in ("：", ":"):
                    frame_context = _intro(clause.text)
                    clause.context = frame_context
                    self.open_frame = self.frame("colon", frame_context, clause.span, clause.id)
                    last_header = self.open_frame
                else:
                    last_header = None
            if separator and separator in _SENTENCE_END and parent is None:
                self.sentence += 1
                self.open_frame = None
        return last_header

    def groups(self, line, offset, start, end, pairs):
        groups = []
        index = start
        while index < end:
            right = pairs.get(index)
            if right is None or right >= end:
                index += 1
                continue
            kind = "title" if line[index] in _TITLES else "quote" if line[index] in _QUOTES else "bracket"
            groups.append(Group(kind, self.span(offset+index, offset+right+1),
                                self.span(offset+index+1, offset+right)))
            index = right + 1
        return tuple(groups)

    def table_line(self, line, offset, cells, pairs, bad, escaped, header):
        self.row += 1
        table = self.table
        columns = [line[left:right] for left, right in cells]
        if header:
            self.header = (self.span(offset+cells[0][0], offset+cells[-1][1]), len(self.graph.clauses))
            self.header_columns = columns
            self.tables[table] = {i for i, label in enumerate(columns, 1) if _ITEM_COLUMN.fullmatch(label)}
        item_columns = self.tables.get(table, set())
        row_frame = None
        if self.header and not header:
            row_frame = self.frame("table_header", Context.UNKNOWN, *self.header)
        active = (row_frame,) if row_frame is not None else ()
        project = None
        for column, (left, right) in enumerate(cells, 1):
            label = columns[column-1]
            if not header and (column in item_columns or
                               (not item_columns and (_PROJECT.fullmatch(label) or _PROJECT_CELL.fullmatch(label)))):
                project = self.project(label, self.span(offset+left, offset+right)) if label else None
            self.open_frame = None
            if header and left < right:
                self.clause(offset+left, offset+right, "", "", table=table, row=self.row, column=column, table_header=True)
            else:
                column_header = self.header_columns[column-1] if column <= len(self.header_columns) else ""
                self.line_parts(line, offset, left, right, pairs, bad, escaped, frames=active,
                                table=table, row=self.row, column=column, project=project, column_header=column_header)
        self.open_frame = None
        self.sentence += 1

    def split(self, paragraph_starts):
        scans = [_scan_line(raw.rstrip(_LINE_ENDS)) for raw in self.lines]

        blocks = []
        previous_intro = None
        in_table = False
        index = cross_limit = 0
        cross_pairs = {}
        while index < len(scans):
            line, marker, start, pairs, bad, escaped, cells, divider = scans[index]
            offset = self.offsets[index]
            last_line = index
            if not (marker or cells) and any(line[pos] in _PAIRS for pos in bad):
                # 同一段的物理换行可落在括注内。搜索只到本段结构边界。
                if index >= cross_limit:
                    cross_limit = index+1
                    while cross_limit < len(scans):
                        candidate, list_marker, _, _, _, _, row, _ = scans[cross_limit]
                        if (cross_limit+1 in paragraph_starts or not candidate.strip() or list_marker
                                or row or _HEADING.match(candidate)):
                            break
                        cross_limit += 1
                    segment = self.graph.text[offset:self.offsets[cross_limit]]
                    complete, _, _ = _pairs(segment)
                    cross_pairs = {left+offset: right+offset for left, right in complete.items()}
                cross_end = max((cross_pairs.get(pos+offset, -1) for pos in bad), default=-1)
                if cross_end >= offset+len(line):
                    last_line = bisect_right(self.offsets, cross_end)-1
                    segment = self.graph.text[offset:self.offsets[last_line+1]].rstrip(_LINE_ENDS)
                    line, marker, start, pairs, bad, escaped, cells, divider = _scan_line(segment)
            paragraph_start = index+1 in paragraph_starts
            index = last_line+1
            if not line.strip() or _HEADING.match(line):
                blocks.clear()
                previous_intro = self.open_frame = None
                self.paragraph += 1
                self.sentence += 1
                in_table = False
            elif paragraph_start:
                self.paragraph += 1
                self.sentence += 1
                if not marker:
                    blocks.clear()
                    previous_intro = self.open_frame = None
            if not line.strip():
                continue
            if cells:
                blocks.clear()
                previous_intro = self.open_frame = None
                if not in_table:
                    self.table += 1
                    self.row = 0
                    self.header = None
                    self.header_columns = []
                    self.paragraph += 1
                    self.sentence += 1
                in_table = True
                if not divider:
                    is_header = index < len(scans) and scans[index][-1]
                    self.table_line(line, offset, cells, pairs, bad, escaped, is_header)
                continue
            if in_table:
                self.paragraph += 1
            in_table = False
            active = ()
            list_id = None
            if marker:
                indent = len(marker["indent"].expandtabs(4))
                while blocks and indent < blocks[-1][0]:
                    blocks.pop()
                if not blocks or indent > blocks[-1][0]:
                    self.list_count += 1
                    source = self.graph.frames[previous_intro].source if previous_intro is not None else len(self.graph.clauses)
                    evidence = self.graph.frames[previous_intro].evidence if previous_intro is not None else self.span(offset, offset+start)
                    list_frame = self.frame("list", Context.UNKNOWN, evidence, source)
                    blocks.append((indent, self.list_count, previous_intro, list_frame))
                _, list_id, _, _ = blocks[-1]
                active = tuple(frame for _, _, intro, list_frame in blocks for frame in (intro, list_frame)
                               if frame is not None)
                self.open_frame = None
                self.sentence += 1
            elif blocks:
                blocks.clear()
                previous_intro = self.open_frame = None
                self.paragraph += 1
                self.sentence += 1
            previous_intro = self.line_parts(line, offset, start, len(line), pairs, bad, escaped,
                                             frames=active, list_block=list_id)
            if marker:
                self.sentence += 1
            if previous_intro is None:
                self.open_frame = None
        return self.graph


@dataclass
class _Prefix:
    complete: bool = True
    agents: list[tuple[str, int, int, str]] = field(default_factory=list)
    arguments: dict[str, tuple[int, int]] = field(default_factory=dict)
    signals: set[str] = field(default_factory=set)
    negation: tuple[str, int, int] | None = None
    timing: str = ""


def _islands(visible):
    """找到紧邻中心词的定语。定语左边界停在本层控制词、模态或介词之后。"""
    start = 0
    for centre in _CENTRE.finditer(visible):
        prefix = visible[start:centre.start()]
        controls = [m.end()+start for m in _verb_matches(prefix) if m[0] in _BRIDGE]
        prep = re.search(r"(?:向|对|给|为)(?=(?:已|未|没有|不|经济|贫困|参加|报名))", prefix)
        neg = _TOKENS.match(prefix)
        if neg and neg[0] in _PROHIBITION:
            controls.append(start+neg.end())
        left = max(controls + ([start+prep.end()] if prep else [start]))
        attribute = visible[left:centre.start()].strip()
        if attribute and (left > start or _ATTRIBUTIVE_ENTRY.match(attribute)) and not re.search(r"[、；，。]", attribute):
            yield left, centre.start(), centre.end()
        start = centre.end()
    for refusal in _REFUSAL.finditer(visible, start):
        marker = _REFUSAL_CENTRE.search(visible, refusal.end())
        if marker and not re.search(r"[、；，。]", visible[refusal.end():marker.start()]):
            yield refusal.start(), marker.start(), marker.end()
            break


def _canonical_project(label):
    for first, canonical in (("课后服务", "课后服务"), ("研学", "研学"), ("意外伤害保险", "意外伤害保险"),
                             ("校服", "校服"), ("教辅", "教辅")):
        if label.startswith(first):
            return canonical
    return label.strip("《》“”\"")


def _surface(clause):
    text = list(clause.text)
    for group in clause.groups:
        start = group.span.start-clause.span.start
        end = group.span.end-clause.span.start
        raw = clause.text[start+1:end-1]
        mark = "\ufffc" if group.kind in ("title", "quote") or any(_verb_matches(raw)) else " "
        text[start:end] = mark * (end-start)
    return "".join(text)


def _position(builder, clause, local):
    return builder.span(clause.span.start+local[0], clause.span.start+local[1]) if local else None


def _bounded_match(pattern, text, start, end):
    match = pattern.match(text, start)
    return match if match and match.end() <= end else None


def _consume_prefix(text, start, end, *, linked=False):
    prefix = _Prefix()
    index = start
    if linked:
        transition = re.match(r"(?:的|者|过)?(?:之后|以后|后|随即|然后|再|便|则)?", text[index:end])
        index += transition.end()
    while index < end:
        if text[index].isspace():
            index += 1
            continue
        marker = ""
        if text.startswith("交由", index, end) or text.startswith("由", index, end):
            marker = "交由" if text.startswith("交由", index, end) else "由"
        match = _PREP.match(text, index, end)
        if not match and text[index] in "向对给为" and text[index+1:index+2].isspace():
            inherited = _AGENT.match(text, index+1+len(text[index+1:end])-len(text[index+1:end].lstrip()), end)
            if inherited:
                prefix.arguments[text[index]] = inherited.span()
                index = inherited.end()
                continue
        if match:
            key = match["marker"]
            # “将”加已识别受事时是处置槽，孤立的“将”交给模态。
            prefix.arguments[key] = match.span("value")
            if key in ("在", "于") and _TIME_RE.fullmatch(match["value"]):
                prefix.timing = match["value"]
        elif (match := _bounded_match(_PERSON, text, index+len(marker), end) or
              _AGENT.match(text, index+len(marker), end)) and (marker or index == start or
                not prefix.arguments and (not prefix.agents or prefix.negation is not None)):
            prefix.agents.append((match[0], match.start(), match.end(), marker))
        elif marker:
            prefix.complete = False
            return prefix
        elif match := _TOKENS.match(text, index, end):
            word = match[0]
            if word in _NOT_NEGATION:
                if not _NONNEG_PREFIX.fullmatch(word):
                    prefix.complete = False
            elif prefix.negation is None:
                prefix.negation = word, match.start(), match.end()
            else:
                prefix.complete = False
        elif match := (_MODAL.match(text, index, end) or _MANNER.match(text, index, end)
                       or _bounded_match(_FIXED_PREFIX, text, index, end)):
            prefix.signals.add(match[0])
        elif match := _TOPIC.match(text, index, end):
            prefix.arguments.setdefault("topic", match.span())
        elif match := _TIME_RE.match(text, index, end):
            prefix.timing = match[0]
        else:
            prefix.complete = False
            # 未知插入不让否定越过。后续候选仍留证据，供宽层待核。
            index += 1
            continue
        index = match.end()
    return prefix


def _events(surface):
    """同一分句可含控制链、条件与后果、或局部动作结束后的新谓词。"""
    events = []
    for verb in _verb_matches(surface):
        if events:
            previous = events[-1]
            between = surface[previous.end():verb.start()].strip()
            if previous[0] not in _BRIDGE | {"查处", "立案查处", "制止", "劝阻"} and not re.search(
                r"(?:之后|以后|后|便|则|由|交由|不予|不得|不准|未再|一律|必须|重新)[^\ufffc]{0,22}$|不$", between
            ):
                continue
        events.append(verb)
    return events


def _leading_context(text):
    if _PRECONDITION.match(text):
        return Context.CONDITION
    if _SOURCE.match(text):
        return Context.QUOTE
    if _REFERRAL.match(text) or _UNKNOWN_STANCE.match(text) or _STANCE_SUFFIX.search(text) or text.startswith("因"):
        return Context.UNKNOWN
    if _GOVERNANCE.search(text):
        return Context.GOVERNANCE
    if text.startswith(("是否", "难道")) or text.endswith("吗"):
        return Context.QUESTION
    return None


def _external_context(graph, clause):
    contexts = [graph.frames[i].context for i in clause.frames
                if graph.frames[i].kind not in {"list", "table_header"}]
    return next((context for context in contexts if context != Context.NOTICE), None)


def _argument(builder, clause, bounds):
    if bounds is None:
        return "", None
    a, b = _trim(clause.text, *bounds)
    return clause.text[a:b], _position(builder, clause, (a, b)) if a < b else None


def _object_bounds(clause, verb, end, prefix):
    explicit_object = prefix.arguments.get("把", prefix.arguments.get("将"))
    recipient = prefix.arguments.get("向") or prefix.arguments.get("给") or prefix.arguments.get("为")
    tail = clause.text[verb.end():end].rstrip().rstrip(_PARTICLES)
    if explicit_object and _RECEIVER.fullmatch(tail):
        recipient = (verb.end(), verb.end()+len(tail))
    elif re.search(r"(?:提供|发送|转交|交付|发)给", tail):
        marker = re.search(r"(?:提供|发送|转交|交付|发)给", tail)
        recipient = (verb.end()+marker.end(), verb.end()+len(tail))
    elif match := re.search(r"给(?=" + _RECEIVER.pattern + r"$)", tail):
        recipient = (verb.end()+match.end(), verb.end()+len(tail))
        tail = tail[:match.start()]
    if verb[0] in _BRIDGE | {"推荐"}:
        tail = tail.split("参加", 1)[0] if "参加" in tail and not tail.startswith("参加") else tail
        tail = re.split(r"[把将向]", tail, maxsplit=1)[0]
        if not tail and len(prefix.agents) > 1 and prefix.agents[-1][3]:
            return prefix.agents[0][1:3], recipient
    tail = re.sub(r"(?:是)?(?:绝对)?(?:不可能|不行|根本不行|做不到)(?:的)?[吧啊呀吗呢]*$|"
                  r"怎么行[吧啊呀吗呢]*$|(?:的行为|的提议|之后|以后|后|的|者)$", "", tail).rstrip()
    return explicit_object or ((verb.end(), verb.end()+len(tail)) if tail else prefix.arguments.get("topic")), recipient


def _is_school(agent):
    return any(agent == name or agent.endswith(name) and
               agent.startswith(("本校", "我校", "任课", "在职", "各位", "任何")) or
               agent.startswith(name+"和") or agent.startswith(name+"与") for name in _SCHOOL)


def _record_action(builder, clause, verb, end, prefix, *, outer=None, parent=None, attributive=False,
                   forced_negative=False, post_reverse=False, ambiguous=False):
    graph = builder.graph
    verb_text = verb[0]
    text = clause.text
    local, reason = Polarity.UNKNOWN, ""
    negation = prefix.negation
    word = negation[0] if negation else ""
    if (word == "不是不" or word == "没有不" and not text[:end].rstrip(_PARTICLES).endswith("的")
            or word in _DOUBLE and not text[verb.end():end].strip() and verb_text in {"是", "决定"}):
        reason = "反转后项待核"
    elif word == "并非" or ambiguous:
        reason = "可行性或词元待核"
    elif not prefix.complete:
        reason = "未消费前置"
    elif forced_negative or verb_text == "免收":
        local = Polarity.NEGATIVE
    elif post_reverse or word in _DOUBLE:
        local = Polarity.POSITIVE
    elif negation:
        local = Polarity.NEGATIVE
    else:
        local = Polarity.POSITIVE

    agent = ""
    agent_span = None
    agent_inherited = False
    if prefix.agents:
        agent, start, stop, _ = prefix.agents[-1]
        agent_span = _position(builder, clause, (start, stop))
    elif parent and parent.agent:
        agent, agent_span = parent.agent, parent.agent_span
        agent_inherited = parent.clause != clause.id or parent.agent_inherited
    obj, receiver = _object_bounds(clause, verb, end, prefix)
    obj, object_span = _argument(builder, clause, obj)
    receiver, recipient_span = _argument(builder, clause, receiver)
    positive_context = Context.REQUIREMENT if (post_reverse or verb_text in _BRIDGE or
                        prefix.signals & (_MANDATORY | {"请", "将", "即日起", "现"})) else Context.ASSERTION
    if parent and parent.context == Context.REQUIREMENT and outer is None:
        positive_context = Context.REQUIREMENT
    context = outer if outer is not None else (Context.NEGATION if local == Polarity.NEGATIVE else
                                               positive_context if local == Polarity.POSITIVE else Context.UNKNOWN)
    polarity = local
    if context in {Context.QUESTION, Context.GOVERNANCE, Context.QUOTE, Context.CONDITION, Context.UNKNOWN}:
        polarity = Polarity.UNKNOWN if local != Polarity.NEGATIVE else local
    if context == Context.QUESTION:
        polarity = Polarity.UNKNOWN
    if context == Context.NEGATION:
        polarity = Polarity.NEGATIVE if local != Polarity.UNKNOWN else Polarity.UNKNOWN

    action = Action(len(graph.actions), clause.id, verb_text, _position(builder, clause, verb.span()),
                    context, polarity, local, agent=agent, agent_span=agent_span, school_agent=_is_school(agent),
                    agent_inherited=agent_inherited, object=obj, object_span=object_span,
                    recipient=receiver, recipient_span=recipient_span, timing=prefix.timing,
                    mandatory=bool(prefix.signals & _MANDATORY) or verb_text in {"强迫", "强制"},
                    uniform="统一" in prefix.signals, voluntary=any("自愿" in signal for signal in prefix.signals) or
                    bool(parent and parent.voluntary), exit=bool(_EXIT.search(text)),
                    refusal=verb_text in _FEES and bool(_REFUSAL.match(text[negation[1]:] if negation else "")),
                    consequence=verb_text in _CONSEQUENCES and
                    (local == Polarity.NEGATIVE or verb_text.startswith("取消")),
                    parent=parent.id if parent else None, attributive=attributive,
                    fixed_notice=bool(_FIXED_NOTICE.match(text) and verb_text in _FEES),
                    negation=_position(builder, clause, negation[1:] if negation else None), reason=reason)
    if parent and parent.negation and not action.negation and local == Polarity.POSITIVE:
        action.negation = action.negation or parent.negation
        if parent.polarity == Polarity.NEGATIVE:
            action.context, action.polarity = Context.NEGATION, Polarity.NEGATIVE
        elif parent.local_polarity == Polarity.UNKNOWN:
            action.context, action.polarity = Context.UNKNOWN, Polarity.UNKNOWN
    graph.actions.append(action)
    graph._by_clause.setdefault(clause.id, []).append(action)
    for frame_id in clause.frames:
        graph.frames[frame_id].actions.append(action.id)
    return action


def _clause_actions(builder, clause, outer, question):
    raw = clause.text
    visible = _surface(clause)
    projected = list(visible)
    if clause.malformed and outer is None:
        outer = Context.UNKNOWN

    antecedents = []
    for start, attribute_end, centre_end in _islands(visible):
        attribute = visible[start:attribute_end]
        refusal = _REFUSAL.search(attribute)
        if refusal:
            candidates = list(_verb_matches(visible[start:attribute_end].rjust(attribute_end)))
            if candidates:
                verb = candidates[0]
                prefix = _consume_prefix(visible, start, verb.start())
                if refusal[0].startswith("拒"):
                    prefix.negation = "拒", start+refusal.start(), start+refusal.start()+1
                    prefix.complete = True
                action = _record_action(builder, clause, verb, attribute_end, prefix, outer=Context.CONDITION,
                                        attributive=True, forced_negative=True)
                action.refusal = True
                antecedents.append(action.id)
        projected[start:attribute_end+1] = " " * (attribute_end+1-start)
        if visible[centre_end-1:centre_end] in ("的", "者"):
            projected[centre_end-1] = " "
    surface = "".join(projected)
    events = _events(surface)
    stance = _leading_context(raw)
    source = _PRECONDITION.match(raw) or _SOURCE.match(raw) or _REFERRAL.match(raw)
    start = source.end() if source else 1 if raw.startswith("因") else 0
    if clause.separator in ("：", ":") and _intro(raw) != Context.UNKNOWN:
        return []
    if not events:
        if antecedents:
            clause.context = Context.CONDITION
        return []
    tail = raw.rstrip().rstrip(_PARTICLES)
    post = bool(_POST_NEG.search(tail) and len(events) == 1)
    feasible = bool(_POST_FEASIBLE.search(tail))
    if (question or stance == Context.QUESTION) and not post and outer is None:
        outer = Context.QUESTION
    outer = outer if outer is not None else stance if not (post and stance == Context.QUESTION) else None

    actions = []
    for i, verb in enumerate(events):
        if verb.start() < start:
            continue
        previous = actions[-1] if actions else None
        bridge = previous if previous and (previous.predicate in _BRIDGE or outer == Context.GOVERNANCE) else None
        prefix = _consume_prefix(surface, start, verb.start(), linked=bool(previous))
        word = prefix.negation[0] if prefix.negation else ""
        if post and not (word and word in _NEGATIVE):
            post = False
            if question and outer is None:
                outer = Context.QUESTION
        if post and outer == Context.QUESTION and stance != Context.QUESTION:
            outer = None
        if previous and prefix.complete and prefix.agents and (
                raw.startswith("因") or previous.predicate == "咨询"):
            action_outer = Context.UNKNOWN
        else:
            action_outer = outer
        end = len(raw)
        if i+1 < len(events):
            next_verb = events[i+1]
            end = next_verb.start()
            if verb[0] not in _BRIDGE:
                segment = surface[verb.end():end]
                boundary = _ACTION_CONTINUATION.search(segment)
                if boundary:
                    end = verb.end()+boundary.start()
        action = _record_action(builder, clause, verb, end, prefix, outer=action_outer, parent=bridge,
                                post_reverse=post and i == 0, ambiguous=feasible)
        if antecedents and action.consequence:
            action.conditions = tuple(antecedents)
        if not action.agent and previous and previous.agent and prefix.complete and not prefix.arguments.get("topic"):
            action.agent, action.agent_span, action.school_agent = previous.agent, previous.agent_span, previous.school_agent
        if action.refusal:
            antecedents.append(action.id)
        actions.append(action)
        start = verb.end() if bridge or verb[0] in _BRIDGE else end
    if actions and clause.context == Context.UNKNOWN:
        clause.context = outer if outer is not None else actions[0].context
    return actions

def _local_prohibition(graph, action):
    return action.negation and graph.text[action.negation.start:action.negation.end] in _PROHIBITION


def _chain_head(graph, action):
    while action.parent is not None:
        action = graph.actions[action.parent]
    return action


def _roots(graph, actions):
    return list({_chain_head(graph, item).id: _chain_head(graph, item)
                 for item in actions if not item.attributive}.values())


def _tail_binding(text, question):
    if _EXIT.fullmatch(text.removeprefix("也")):
        return None
    for binding, pattern in _BACK_BIND_RE:
        if pattern.search(text):
            return binding
    if question or re.search(r"(?:有无必要|合规吗|可行吗|能否)", text):
        return Binding.QUESTION
    return None


def _bind(graph, earlier, later, binding):
    for action in earlier:
        action.binding, action.binding_clause = binding, later.id
        action.admission = action.admission_evidence = None
        if binding in {Binding.PROHIBITED, Binding.REJECTED, Binding.HISTORICAL}:
            action.context, action.polarity = Context.NEGATION, Polarity.NEGATIVE
        elif binding == Binding.REFUTED:
            action.context, action.polarity = Context.REFUTATION, Polarity.NEGATIVE
        elif binding == Binding.ACCOUNTABILITY:
            action.context = Context.GOVERNANCE
        elif binding == Binding.QUESTION:
            action.context, action.polarity = Context.QUESTION, Polarity.UNKNOWN
        else:
            action.context, action.polarity = Context.UNKNOWN, Polarity.UNKNOWN
        clause = graph.clauses[action.clause]
        if clause.context != Context.NEGATION:
            clause.context = action.context
        clause.admission = clause.admission_evidence = None


def _execution_detail(text):
    if _BACKREF.match(text) or _INTAKE_TAIL.search(text):
        return False
    if any(pattern.search(text) for _, pattern in _BACK_BIND_RE):
        return False
    if _AMOUNT.fullmatch(text):
        return True
    if text.startswith(("交给", "交至", "交到", "汇至", "由", "请交给")):
        parts = re.match(r"(?:请)?(?:交给|交至|交到|汇至|由)(.+)", text)
        if parts:
            recipient = re.sub(r"(?:统一)?(?:代收|收取|收款|保管|办理|收齐)$", "", parts[1])
            return _RECEIVER.fullmatch(recipient) is not None
    timing = re.match(r"(?:请|限于|于|在)?" + _TIME, text)
    if timing:
        suffix = text[timing.end():].strip()
        return (not suffix or re.fullmatch(r"(?:缴费|付款|交费|收取|上交|交齐|缴纳|支付|交)(?:\d+(?:\.\d+)?元)?", suffix)
                is not None)
    return _DETAIL.fullmatch(text) is not None and not re.search(r"评价|问题|是否|应否|可行|提议|做法", text)


def _project_actions(builder, clause, actions, known):
    graph = builder.graph
    if clause.project is not None or clause.table is not None:
        for action in actions:
            action.project = clause.project
        return
    local = {}
    for action in actions:
        project_text = _PROJECT.search(action.object)
        if project_text is None and action.predicate in _FEES and action.object:
            project_text = _PROJECT_CELL.match(action.object)
        if project_text:
            label = project_text[0]
            key = _canonical_project(label)
            if key not in known:
                evidence = action.object_span or action.span
                known[key] = builder.project(label, evidence)
            local[action.id] = known[key]
    if not local:
        project_names = {_canonical_project(match[0]): match for match in _PROJECT.finditer(clause.text)}
        if len(project_names) == 1:
            key, match = next(iter(project_names.items()))
            if key not in known:
                known[key] = builder.project(match[0], _position(builder, clause, match.span()))
            clause.project = known[key]
        elif len(known) == 1 and (_EXIT.search(clause.text) or
                                  any(action.consequence and action.conditions for action in actions)):
            clause.project = next(iter(known.values()))
    elif len(set(local.values())) == 1:
        clause.project = next(iter(local.values()))
    for action in actions:
        action.project = local.get(action.id, clause.project)
    projects = {action.project for action in actions if action.project is not None}
    if clause.project is not None:
        projects.add(clause.project)
    for project in sorted(projects):
        graph.projects[project].clauses.append(clause.id)


def _set_admission(clause, actions, admission, evidence):
    clause.admission, clause.admission_evidence = admission, evidence
    for action in actions:
        action.admission, action.admission_evidence = admission, evidence


def _admit(graph, clause, actions, before, history, inherited_prohibition):
    primary = _chain_head(graph, actions[0]) if actions else None
    positive = [action for action in actions if action.polarity == Polarity.POSITIVE
                and _chain_head(graph, action) is primary]
    if (not positive or clause.context not in {Context.ASSERTION, Context.REQUIREMENT}
            or clause.parent is not None or clause.malformed or inherited_prohibition):
        return
    if clause.previous is None and not clause.frames and not clause.connector:
        _set_admission(clause, positive, Admission.MAIN, clause.span)
        return
    for frame_id in reversed(clause.frames):
        frame = graph.frames[frame_id]
        if (frame.context == Context.NOTICE and frame.clauses[0] == clause.id
                and (clause.previous == frame.source or clause.list_block is not None)):
            _set_admission(clause, positive, Admission.NOTICE, frame.evidence)
            return
    if before is None or before.frames or clause.frames or clause.project is None:
        return
    if clause.connector == "并":
        earlier = graph.actions_for(before.id)
        exempt = next((action for action in earlier if action.school_agent
                       and action.project is not None and action.project != clause.project
                       and (action.predicate == "免收" or action.predicate == "订购"
                            and action.uniform and action.polarity == Polarity.NEGATIVE
                            and not _local_prohibition(graph, action))), None)
        if exempt and any(not action.agent or action.agent == exempt.agent for action in positive):
            for action in positive:
                if not action.agent:
                    action.agent, action.agent_span = exempt.agent, exempt.agent_span
                    action.school_agent = action.agent_inherited = True
            _set_admission(clause, positive, Admission.PARALLEL, before.span)
    elif clause.connector in {"但", "但是", "另"} and any(
        action.school_agent and not action.agent_inherited for action in positive
    ):
        distinct = {action.project for action in history if action.project is not None
                    and action.project != clause.project and action.voluntary and action.exit}
        new_project = all(old.project != clause.project for old in history if old.project is not None)
        if distinct or clause.connector == "另" and new_project:
            _set_admission(clause, positive, Admission.PARALLEL, before.span)


def _resolve_correction(graph, before, clause, actions):
    if before is None or clause.connector != "而是" or "不是不" not in before.text:
        return False
    prior = [action for action in graph.actions_for(before.id) if not action.attributive]
    repeated = [action for action in actions if any(old.predicate == action.predicate for old in prior)]
    alternative = any(action.polarity == Polarity.NEGATIVE for action in repeated)
    confirmed = any(action.timing or action.uniform for action in repeated if action.polarity == Polarity.POSITIVE)
    if alternative:
        _bind(graph, prior, clause, Binding.REJECTED)
    elif not confirmed or re.search(r"暂缓|待定|另行通知", clause.text):
        _bind(graph, prior + repeated, clause, Binding.UNRESOLVED)
    return True


def _split_scope(graph, before, clause, inherited):
    if before is None:
        return None
    if clause.connector not in _PARALLEL:
        return None
    subject = _AGENT.match(clause.text)
    if subject and _JOIN_SIGNAL.match(clause.text, subject.end()):
        return None
    for action in graph.actions_for(before.id):
        if _local_prohibition(graph, action):
            return action
    return inherited


def _resolve_tail(graph, clause, actions, history, same_sentence, question):
    if not history or clause.connector == "而是":
        return False
    prior = [action for action in history if not action.attributive and action.binding is None]
    if not prior:
        return False
    raw = clause.text
    ref = bool(_BACKREF.match(raw))
    binding = _tail_binding(raw, question and not any(action.polarity == Polarity.POSITIVE for action in actions))
    if binding == Binding.QUESTION and not raw.startswith("是否") and any(
            action.school_agent and action.agent_span and action.agent_span.start >= clause.span.start
            and action.local_polarity == Polarity.POSITIVE for action in actions):
        # 完整疑问句可独立询问另一个行为。
        binding = None
    if binding is None and _execution_detail(raw) and (not ref or _AMOUNT.fullmatch(raw)):
        clause.tail = Tail.DETAIL
        return True
    if binding is None and not ref and (_EXIT.fullmatch(raw.removeprefix("也")) or
                                       raw.startswith(("自愿报名", "自愿参加"))):
        clause.tail = Tail.DETAIL
        return True
    if binding is None and not ref and any(
        action.local_polarity != Polarity.UNKNOWN and (
            action.school_agent and action.agent_span and action.agent_span.start >= clause.span.start
            or clause.connector in _PARALLEL | _TURN | {"还", "同时"}
            or action.project is not None and all(old.project != action.project for old in prior)
        ) for action in actions
    ):
        clause.tail = Tail.INDEPENDENT
        return True
    # 无回指词只绑定紧邻。出现明确回指仍须唯一，且不能跨普通句号。
    if not ref and not same_sentence:
        nearest = graph.clauses[prior[-1].clause]
        if (clause.list_block is None or nearest.list_block != clause.list_block
                or clause.span.line-nearest.span.end_line != 1):
            return False
    if not same_sentence and not (ref or binding):
        return False
    clause.tail = Tail.EVALUATION
    if len(_roots(graph, prior)) != 1:
        if ref or binding:
            _bind(graph, prior, clause, Binding.UNRESOLVED)
        else:
            _bind(graph, [action for action in prior if action.clause == clause.previous], clause, Binding.UNRESOLVED)
        return True
    if binding == Binding.HALTED:
        earlier = graph.clauses[prior[0].clause].text
        if _RECORDED.search(earlier) or _RECORDED.search(raw):
            binding = Binding.ACCOUNTABILITY
        elif _HISTORICAL.search(raw) or _HISTORICAL.search(earlier):
            binding = Binding.HISTORICAL
    if binding == Binding.REJECTED and any(_RECORDED.search(graph.clauses[action.clause].text) for action in prior):
        binding = Binding.UNRESOLVED
    if any(action.context == Context.CONDITION for action in prior) and _GOVERNANCE.search(raw) and not ref:
        return True
    _bind(graph, prior, clause, binding or Binding.UNRESOLVED)
    return True


def _annotate(builder):
    graph = builder.graph
    questions = {clause.sentence for clause in graph.clauses
                 if clause.parent is None and clause.separator in "？?" and clause.separator}
    by_sentence = defaultdict(list)
    by_list = defaultdict(list)
    projects = defaultdict(dict)
    prohibition = {}
    for clause in graph.clauses:
        if clause.table_header:
            continue
        before = graph.clauses[clause.previous] if clause.previous is not None else None
        history = by_sentence[clause.sentence, clause.parent, clause.table, clause.column]
        list_history = by_list[clause.list_block]
        same_sentence = bool(history)
        outer = _external_context(graph, clause)
        if clause.parent is not None and outer in {None, Context.UNKNOWN, Context.QUOTE}:
            parent_context = graph.clauses[clause.parent].context
            if parent_context in {Context.CONDITION, Context.GOVERNANCE, Context.REFUTATION} or (
                parent_context == Context.NEGATION
                and any(_local_prohibition(graph, a) for a in graph.actions_for(clause.parent))
            ):
                outer = parent_context
        inherited = _split_scope(graph, before, clause, prohibition.get(before.id) if before else None)
        if inherited and outer is None:
            prohibition[clause.id] = inherited
            outer = Context.NEGATION
        discussed = (outer is None and before and before.separator in ("，", ",") and not clause.connector
                     and any(a.predicate in _DISCUSSION for a in graph.actions_for(before.id)))
        if discussed:
            outer = Context.UNKNOWN
        if outer is None and before and not clause.connector and not graph.actions_for(before.id):
            if _SOURCE.match(before.text):
                outer = Context.QUOTE
            elif _PRECONDITION.fullmatch(before.text):
                outer = Context.CONDITION
            elif before.separator in ("，", ",") and (_REFERRAL.match(before.text)
                    or _FRAME_SHAPE.search(before.text) or before.malformed):
                outer = Context.UNKNOWN
        question = clause.sentence in questions and clause.following is None
        actions = _clause_actions(builder, clause, outer, question)
        if not actions:
            if outer is not None:
                clause.context = outer
            elif question or clause.text.startswith("是否"):
                clause.context = Context.QUESTION
            elif clause.context == Context.UNKNOWN and (context := _leading_context(clause.text)) is not None:
                clause.context = context
        binding = _tail_binding(clause.text, False)
        if binding is not None and not any(action.polarity == Polarity.POSITIVE for action in actions):
            clause.context = {Binding.REFUTED: Context.REFUTATION, Binding.PROHIBITED: Context.NEGATION,
                              Binding.QUESTION: Context.QUESTION}.get(binding, Context.GOVERNANCE)
        if inherited:
            for action in actions:
                action.negation = action.negation or inherited.negation
                if action.local_polarity == Polarity.POSITIVE:
                    action.polarity = Polarity.NEGATIVE
        current = graph.actions_for(clause.id)
        _project_actions(builder, clause, current, projects[clause.sentence, clause.parent])
        if before and not clause.connector:
            refusals = [item for item in graph.actions_for(before.id) if item.refusal]
            if len(refusals) == 1:
                for item in actions:
                    if item.consequence and not item.conditions and item.project in (None, refusals[0].project):
                        item.conditions = (refusals[0].id,)
                        item.project = refusals[0].project
        if before and _EXIT.search(clause.text) and clause.project is not None:
            for item in history:
                if item.project == clause.project:
                    item.exit = True
        if actions and clause.project is not None:
            for item in history:
                if item.project == clause.project and item.voluntary and item.exit:
                    for action in actions:
                        if not (action.uniform or action.mandatory):
                            action.voluntary, action.exit = True, True
        tail_history = history
        if not tail_history and clause.list_block is not None and (
                _BACKREF.match(clause.text) or _tail_binding(clause.text, question)):
            tail_history = list_history
        if not discussed and not _resolve_correction(graph, before, clause, actions):
            _resolve_tail(graph, clause, actions, tail_history, same_sentence, question)
        _admit(graph, clause, actions, before, history, inherited)
        if clause.tail != Tail.DETAIL:
            history.extend(actions)
        if clause.parent is not None and actions:
            parent = graph.clauses[clause.parent]
            if not graph.actions_for(parent.id):
                by_sentence[parent.sentence, parent.parent, parent.table, parent.column].extend(actions)
        if clause.list_block is not None and clause.tail != Tail.DETAIL:
            list_history.extend(actions)


def analyze(text: str, *, paragraph_starts: tuple[int, ...] = ()) -> ClauseGraph:
    """构建文档级分句图。Word 导入方可传真实段落起始行号（1 基）。"""
    builder = _Builder(text)
    graph = builder.split(set(paragraph_starts))
    _annotate(builder)
    return graph


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, help="UTF-8 文本文件。省略时从标准输入读取。")
    args = parser.parse_args(argv)
    try:
        if args.path:
            with args.path.open(encoding="utf-8-sig", newline="") as stream:
                text = stream.read()
        else:
            text = sys.stdin.read()
    except (OSError, UnicodeError) as error:
        parser.error(str(error))
    graph = analyze(text)
    print(json.dumps({name: [asdict(value) for value in getattr(graph, name)]
                      for name in ("clauses", "frames", "actions", "projects")}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
