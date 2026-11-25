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
from functools import lru_cache
from itertools import groupby
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
    ALTERNATIVE = "合规替代"


class Tail(_TextEnum):
    DETAIL = "执行细化"
    CHOICE = "自愿或退出"
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
    unconsumed: Span | None = None
    question: bool = False


@dataclass
class Action:
    id: int
    clause: int
    predicate: str
    span: Span
    context: Context
    polarity: Polarity
    local_polarity: Polarity
    extent: Span | None = None
    agent: str = ""
    agent_span: Span | None = None
    school_agent: bool = False
    agent_inherited: bool = False
    object: str = ""
    object_span: Span | None = None
    topic: str = ""
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
    line_offsets: list[int] = field(default_factory=lambda: [0], repr=False)
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
_LIST = re.compile(r"(?P<indent>[ \t　]*)(?:(?P<major>[一二三四五六七八九十百]+、)|"
                   r"(?P<chinese>[（(][一二三四五六七八九十百]+[）)]|[一二三四五六七八九十百]+[）)])|"
                   r"(?P<decimal>[0-9]+(?:[.．](?!\d)|、))|(?P<right>[0-9]+[）)])|"
                   r"(?P<paired>[（(][0-9]+[）)])|(?P<circled>[①-⑳])|"
                   r"(?P<bullet>[-+*][ \t]+|[•●▪·]))[ \t　]*")
_LIST_LEVEL = {name: i for i, name in enumerate(("major", "chinese", "decimal", "right", "paired", "circled", "bullet"))}
_HEADING = re.compile(r"\s*(?:#{1,6}\s|(?:第[一二三四五六七八九十\d]+[章节条])|【[^】]+】\s*$)")
_JOIN = ("而是", "但是", "但", "而", "另", "以及", "或者", "同时", "还", "并", "且", "和", "或", "、", "/", "／")
_PARALLEL = {"并", "且", "及", "以及", "和", "、", "或", "或者", "/", "／"}
_TURN = {"但", "但是", "而", "另", "而是"}
_ATOMIC_JOIN = ("并非", "并不", "并列", "同时期", "还款", "还原", "归还", "退款", "和谐",
                "但凡", "另外", "另有", "另行", "另请", "另作", "另定", "另设", "另由")
_ITEM_COLUMN = re.compile(r"(?:(?:收费|缴费|征订|购买|服务|费用)(?:的)?)?(?:项目|品名|名称|明细|科目)"
                          r"(?:名称|名|列)?(?:[一二三四\d]+)?")
_TABLE_DIVIDER = re.compile(r":?-{3,}:?")
_THOUSANDS = re.compile(r"\d{3}(?!\d)")

# 口径 §1 句首白名单、§2 语境与回绑、§3.1–3.4 槽位。
_SCHOOL = ("学校", "本校", "我校", "教师", "老师", "班主任", "副班主任", "各班", "年级组", "各年级组", "教务处")
_OTHER_AGENT = ("家长委员会", "家委会", "全体学生", "所有学生", "全体家长", "学生", "新生", "同学们", "同学", "家长",
                "各班家长", "校外培训机构", "校外辅导机构", "财务会议", "教代会", "校务会",
                "困难学生", "贫困学生", "留守学生", "残疾学生", "家庭", "财务室", "每生", "该生", "本人", "校方",
                "教职工", "中小学校", "任何班级", "班级", "全班")
_AGENT = re.compile(r"(?:本校|我校|任课|在职|各位|任何)?(?:" +
                    _alternatives(_SCHOOL + _OTHER_AGENT) + r")"
                    r"(?:(?:和|与)(?:任课|在职)?(?:班主任|老师|教师|年级组))?")
_PERSON = re.compile(r"(?:学生[\u4e00-\u9fff]{2,4}(?=属于|患有|被记过|系|是|享受|登记|认定)"
                     r"|[\u4e00-\u9fff]{2,4}同学|[A-Z]\d{2,4}|你)")
_NOTICE = {"收费通知", "关于课后服务收费的通知", "现通知如下", "经研究决定"}
_BRIDGE = {"要求", "强迫", "强制", "组织", "安排", "动员", "允许", "让"}
_DISCUSSION = {"提出建议", "审议", "商议"}
# 口径 §2 否定四步 1。长词先行，“不同意／不及时”有自己的词界。
_PROHIBITION = ("严禁", "禁止", "不得", "不准", "切勿", "不可", "不要", "请勿",
                "坚决反对", "明确反对", "重申反对", "严厉杜绝", "反对", "杜绝", "绝不", "决不", "不同意",
                "明确制止", "坚决制止", "劝阻")
_NEGATIVE = ("不会", "不能", "未曾", "尚未", "不再", "没有", "不予", "拒绝", "拒不", "拒", "从未", "从不", "并不", "不", "未")
_NOTICE_PROHIBITION = re.compile(r"(?:" + _AGENT.pattern + r")?(?:" + _alternatives(_PROHIBITION) + r")")
_DOUBLE = ("绝非不", "并非不", "不得不", "不可能不", "不会不", "不能不", "无不", "没有不")
_NOT_NEGATION = ("不断", "不同", "不理想", "不达标", "不少于", "不超过", "不低于", "不及", "不管", "不论",
                 "不便", "不足", "不仅", "不但", "不只", "不光", "不止", "不单", "不一", "不等", "不均", "不定期", "不定时")
_TOKEN_WORDS = sorted(set(_DOUBLE + _PROHIBITION + _NEGATIVE + _NOT_NEGATION + ("不是不", "并非")),
                      key=lambda word: (-len(word), word))
_TOKEN_BOUNDARIES = {"不同": r"不同(?!意)", "不及": r"不及(?!时)"}
_TOKENS = re.compile("|".join(_TOKEN_BOUNDARIES.get(word, re.escape(word)) for word in _TOKEN_WORDS))
_NONNEG_PREFIX = re.compile(r"不断|不定期|不定时|不仅|不但|不只|不光|不止|不单")
_MODAL = re.compile(r"即日起|必须|一律|统一|务必|按标准|按规定|须|应当|应|现|将(?!学生|家长|名单|成绩|资料)|请|均|仍|已(?:经)?|曾|也|都")
_MANDATORY = {"必须", "一律", "务必", "须", "应当", "应", "强迫", "强制"}
# 口径 §2 否定四步 3、§3.4 帮扶；方案 44、63。首版时点及紧邻介宾槽。
_MANNER = re.compile(r"私下|变相|再次|强行|随意|主动|自愿|可以|义务|经常|多次|定期|及时|宣传(?=动员)")
_DEPARTURE_PREFIX = re.compile(r"提前")
_TIME = (r"(?:(?:本|下)?(?:星期|周)[一二三四五六日天末]|本周|下周|每周|寒暑假|寒假|暑假|开学前|"
         r"\d{1,4}(?:年\d{1,2})?月\d{1,2}[日号]|\d{1,2}[点时](?:\d{1,2}分)?|"
         r"\d{1,2}[:：]\d{2})(?:之前|之后|前|后|起)?")
_TIME_RE = re.compile(_TIME)
_PREP = re.compile(
    r"(?P<marker>在|于|向|对|给|把|将|为)"
    r"(?P<value>" + _TIME
    + r"|(?:任何)?(?:校外|[\ufffc]+)?(?:培训机构|辅导机构|补习班)"
      r"|课后服务费收取(?:标准|流程|情况)"
      r"|(?:年级微信群里|(?:任何)?(?:家长群|班群|班级群|微信群|群)(?:里|内|中)?)"
      r"|(?:本校|校内|校外|公告栏|宣传栏|课堂|学校|指定门店|教室(?:门口)?|家长会上|会议上|教代会上)"
      r"|(?:留守儿童|残疾学生|贫困学生|困难学生|单亲家庭|供电公司|每生)"
      r"|(?:已)?(?:交费|缴费|报名)的(?:家长|学生)"
      r"|(?:全体|全部|全班|各班|本班|本学期|期末|本次|阶段测验|考试|学生|家长委员会|家委会|家长|新生|班主任|教师|"
      r"校外|成绩|分数|排名|准考证|学籍号|学号|名单|资料|通讯录|联系方式|电话|材料)+"
      r"(?:的?(?:联系人|名单|通讯录|电话|微信号|信息|联系方式|成绩单|成绩|排名|分数|学籍号|学号|生源|机构|培训机构|辅导机构))*"
      r")"
)
_RECEIVER = re.compile(r"(?:家长群|班级群|班群|微信群|学生|家长|班主任|教师|老师|财务室|教务处|家委会|家长委员会|"
                       r"学校|本校|各班|供电公司|收费窗口|[^，。；、\s]{0,22}(?:培训机构|辅导机构|补习班|书店|机构|平台))")
_CENTRE = re.compile(r"的(?:全体)?(?:困难|贫困|留守|残疾)?(?:学生|新生|同学|家长|家庭|班级|人员)(?!名单|姓名|电话|微信|信息|成绩)")
_COLLECTION = {"收取", "代收", "收缴", "收齐"}
_FEE_RECIPIENT = re.compile(r"向(?P<target>[^，；。]{0,32}?(?:学生|新生|同学们?|家长|家庭))"
                            r"(?:\s*(?:每[人生位月次年日周]|每学[期年]))?"
                            r"(?=\s*(?:收取|代收|收缴|收齐))")
_REFUSAL = re.compile(r"(?:(?:尚)?未|没有|拒绝|拒不|不|拒)(?:统一|按期|按时)?(?:缴纳|交纳|上交|交齐|缴齐|缴费|缴|交费|交款|"
                      r"购买|订购|征订|订阅|办理保险|买|订|交(?=[^\s，。；]{1,16}(?:费|款)))")
_NON_COLLECTING = ("免收", "退费", "减免", "返还")
_FEES = ("收取", "代收", "收缴", "缴纳", "交纳", "上交", "交齐", "缴齐", "购买", "订购", "征订", "订阅", "办理",
         "收费", "缴费", "交费", "付款", "缴", "买", "收", "订") + _NON_COLLECTING
_COLLECTING_VERBS = _COLLECTION | {"缴纳", "交纳", "上交", "交齐", "缴齐", "收费", "缴费", "交费", "付款", "缴", "收"}
_TEXTBOOK_CONSEQUENCES = ("发教材", "发放教材")
_CONSEQUENCES = (*_TEXTBOOK_CONSEQUENCES, "发学习用品", "报名", "登记", "入校", "入班", "进入", "参加评优",
                 "参加", "参与", "领取", "进教室", "离校", "取消评先资格", "取消评优资格")
_PUNITIVE_CONSEQUENCES = {"扣", "扣发", "扣分", "取消资格", "取消评先资格", "取消评优资格",
                          "歧视", "区别对待", "点名", "催缴", "公示名单"}
_WIDE_CONSEQUENCES = ({"注册", "入学登记", "安排座位", "发放课本", "发课本", "领取课本", "办理入学", "选课"}
                      | (_PUNITIVE_CONSEQUENCES - set(_CONSEQUENCES)))
_RESTRICTION = re.compile(r"(?:不予|不得|不准|不许|不能|不会|未|不)$")
_CONSEQUENCE_TOKENS = re.compile(r"不许|" + _TOKENS.pattern)
_PAYMENT_DELIVERY = {"交给", "交到", "交至", "转给", "收齐", "汇给", "转入", "交"}
_IDENTITY = ("属于", "系", "是", "认定为", "登记为", "确诊为", "患有", "享受助学金",
             "受处分", "被处分", "被记过", "受到处分")
_IDENTITY_OBJECT = re.compile(r"贫困|低保|资助|受助|留守|特困|单亲|残疾|残障|孤儿|患病|病|处分|家庭|随班就读")
_PREDICATES = re.compile(_alternatives(
    (*_BRIDGE, *_FEES, *_CONSEQUENCES, *_IDENTITY, "参加培训", "公布", "张贴", "通报", "公示",
     "排名", "排座", "分班", "发布", "晒", "公开", "宣布", "记录", "完成", "推荐", "介绍", "输送", "透露",
     "发成绩", "告知", "写明", "签订", "提出建议", "审议", "商议", "归入", "设立", "填报", "联系",
     "泄露", "提供", "提供给", "发给", "发送", "发送给", "转交", "移交", "交给", "发到", "上传到", "上传",
     "到岗", "取消减免", "取消评优资格", "外出", "报送", "开展", "辅导", "培训", "培训学生", "咨询",
     "送去", "捐赠", "帮助", "讲解", "服务", "陪伴", "募集", "补习功课", "义务辅导", "执行", "支付",
     "决定", "前往", "接收", "签收", "留存", "存档", "归档", "退还", "开具", "核算", "确认", "劝阻", "进行",
     "提议", "否决", "采纳", "叫停", "查处", "整治", "制止", "追责", "处分", "立案查处", "调查", "缴款",
     "摊派", "传到", "入学", "列为", "被警告处分", *_WIDE_CONSEQUENCES, *_PAYMENT_DELIVERY)
))
# 动词同形的名词复合词，见口径 §3。剔除词边界假命中。
_NOUN_ENDINGS = {
    "收": r"入|支|据|费|取|缴|款人|到|件|文", "缴": r"纳|费|齐", "收费": r"标准|依据|项目|方式|情况|行为|管理|通知|单位|窗口",
    "代收": r"费(?:的|标准|流程|项目|$)", "收取": r"标准|流程|情况", "辅导": r"机构|班|中心|老师|教师|材料|资料|答疑",
    "服务": r"费|时间|项目|收费|工作|人员|中心|活动|情况|实行|自愿|[的：:]",
    "培训": r"机构|班|费|中心|学校|项目|活动|的", "排名": r"情况|名单|表|结果|数据",
    "参加": r"人数|人员|率", "报名": r"费|表|时间|流程|标准|条件|情况|人数",
    "购买": r"标准|方式|时间|的记录", "订": r"单|金|购|阅", "登记": r"栏|簿|表|类别|册", "处分": r"情况|决定",
    "决定": r"书|的", "公开": r"信息栏", "组织": r"机构|委员|者", "介绍": r"信", "发给": r"的",
    "联系": r"方式|电话|人", "交": r"接|流|易|通|付|由|涉|代|叉|换",
}
_NOUN_PREFIX = {"服务": ("课后", "志愿"), "培训": ("校外", "教育", "有偿", "免费", "教学", "师资", "能力", "集中"),
                "排名": ("的", "考试", "学生", "班级", "成绩"),
                "收费": ("校外", "非", "校内", "代"), "购买": ("的",), "交费": ("提",), "缴": ("催",)}
_NOUN_SUFFIX_RE = {verb: re.compile(pattern) for verb, pattern in _NOUN_ENDINGS.items()}
_ACTION_CONTINUATION = re.compile(r"(?:的|者|之后|以后|后|随即|然后|再|便|则|由|交由|为|向|把|将|"
                                  r"学校|各班|班主任|不|未|没有|不得|不予|严禁|须|必须|一律|统一|已|过)")
_FIXED_PREFIX = re.compile(r"按自愿原则|以自愿原则|按期|完全自愿|依照规定|以任何名义|"
                           r"(?:进行|搞)(?=成绩排名|排名)|上交前|每学期|每学月|每月|"
                           r"凡(?=未|已|自愿|组织|参加|购买)|可自行|可自由|可(?=自愿|购买|退出)|"
                           r"全体义务教育阶段(?=学生)")
_TUTOR_TOPIC = re.compile(r"校外(?:收费|有偿|付费)(?:补习|补课|辅导)活动(?=由)")
_TOPIC = re.compile(_TUTOR_TOPIC.pattern + r"|考试成绩(?:排名)?|期末成绩|期末考试|考试排名|成绩排名|成绩单|排名(?=不会不|不能不|不得不)|"
                    r"课后服务(?:费)?|校服(?:费)?|教辅(?:资料)?|意外伤害保险(?:费)?|研学(?:费用|活动|费)?|"
                    r"报刊|本项目|本项|本次研学活动|资料费|班费|成绩|学生电话|学生名单|学生信息")
_RANK_PREFIX = re.compile(r"(?:按(?:考试)?|(?:进行|搞|组织)(?:考试)?)成绩")
_RANK_DENIAL_ADJUNCT = re.compile(r"始终|一直|坚持|历来|明确|严格|坚决|一贯|从来|确实|按照规定")
_RANK_INQUIRY = re.compile(r"(?:询问|问)(?:是否|能否|可否|要不要|会不会)")
_RANK_RHETORIC = re.compile(r"难道|岂能|岂可|怎么敢|怎么可能|哪里会|怎会|怎能|哪能|何尝")
_JOIN_SIGNAL = re.compile(r"(?:现|须|应|必须|一律|统一|将|仍|已)")
_EXIT = re.compile(r"不参加不收费|不参加不缴费|未报名不收费|不报名不收费|不购买不收费|"
                   r"可自行(?:购买|订购)|不作强制要求|不强制|可(?:自由)?退出|可自愿选择是否参加")
_EXIT_WITHOUT_PAYMENT = re.compile(r"不参加不(?:收费|缴费)|(?:不|未)报名不收费|不购买不收费")
_NON_COMPULSORY = re.compile(r"自愿|可以|可(?:自行|自由|购买|退出)")
_PROJECT = re.compile(r"课后服务(?:费|收费)?|研学(?:活动|旅行|费|费用)?|意外伤害保险(?:费)?|"
                      r"校服(?:费)?|教辅(?:资料|材料|费)?|资料费|材料费|班费|活动费|报名费|"
                      r"报刊|练习册|安全手册|补习费|保险费|教材")
_PROJECT_CELL = re.compile(r"(?:[^\d，；：|。]{1,18})(?:费|保险|手册|教材|资料|校服|教辅|报刊|服务|活动|研学|练习册)")
_AMOUNT = re.compile(r"(?<!\d)\d+(?:,\d{3})*(?:\.\d+)?\s*元")
_FREE = re.compile(r"免费|(?<![\d,，.．])[0０]+(?:[,，][0０]{3})*(?:[.．][0０]+)?\s*元")
_POST_NEG = re.compile(r"(?:是)?(?:绝对)?(?:不可能|不行|根本不行|做不到)(?:的)?$|怎么行$")
_QUESTION_PARTICLES = "吗么呢"
_PARTICLES = "吧啊呀" + _QUESTION_PARTICLES
_POST_FEASIBLE = re.compile(r"并非(?:不可行|不能|不可以|不可能)$|并不(?:可行|现实)$")
_UNKNOWN_STANCE = re.compile(r"^(?:拟|拟议|提议|建议研究|考虑|有人建议|可能|疑似|计划讨论|待定)")
_STANCE_SUFFIX = re.compile(r"(?:只是|仅为|尚属)(?:提议|建议|设想|传闻)$|(?:尚待|有待)(?:讨论|研究|决定)$")
_FRAME_SHAPE = re.compile(r"(?:须知|如下|下列|以下|这种做法|这种说法|一项提议|一项方案)$")
_PRECONDITION = re.compile(r"^(?:如果|若(?:发现)?|如有|如发现|一旦|凡(?:发现|利用)|发现|假如)")
_REFERRAL = re.compile(r"^(?:针对|对于|关于|就)(?=\S)")
_SOURCE = re.compile(r"^(?:网传(?:谣言)?(?:称)?|传闻(?:称)?|据(?:反映|举报|传言|说|报道)|听说|匿名举报(?:称)?|"
                     r"某外校曾发生|外校曾发生|他校曾发生|往年(?:曾)?|有人(?:称|说)|(?:某)?(?:文件|报道)(?:提到|称))")
_GOVERNANCE = re.compile(r"(?:严肃查处|严查|专项(?:整治|督查|清查|治理|检查)|通报批评|展开排查|"
                         r"严肃追责|依法依规严肃追责|坚决制止|开展调查|予以处分|取消评优资格)")
_CONDITIONAL_RESPONSE = re.compile(r"查实|查处|问责|追责|制止|举报|处分|通报批评|取消评优资格")
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
    (Binding.REFUTED, r"(?:经(?:核实|核查|调查)(?:并)?不属实|查无实据|(?:这是|纯属|实为)谣言)"),
    (Binding.PROHIBITED, r"(?:一律禁止|坚决反对|坚决零容忍|不允许|将制止)"),
    (Binding.ACCOUNTABILITY, r"(?:已(?:启动问责|遭处分|立案查处|被问责|被处分|开展调查|处分)|立案查处|查处了此事)"),
    (Binding.REJECTED, r"(?:已被否决|不予采纳|未予采纳|已否决|未获通过|未执行|不执行)"),
    (Binding.HALTED, r"(?:叫停|停止实施)"),
    (Binding.QUESTION, r"是否"),
)
_BACK_BIND_RE = tuple((binding, re.compile(pattern)) for binding, pattern in _BACK_BIND)
# 口径 §1 句尾检查。每支均用 fullmatch，时间、金额、收款方之后没有开放尾部。
_PAYEE = r"(?:班主任|教师|老师|财务室|教务处|家委会|家长委员会|本校|学校|各班|收费窗口)"
_PAY_TO = r"(?:交给|交至|交到|汇至|交)" + _PAYEE
_DETAIL = re.compile(
    r"(?:(?:请|须)?(?:于|在|限于)?" + _TIME
    + r"(?:(?:缴费|付款|交费|收取|上交|交齐|缴纳|支付)(?:" + _AMOUNT.pattern + r")?|" + _PAY_TO + r")?"
    r"|(?:请)?" + _PAY_TO
    + r"|由" + _PAYEE + r"(?:统一)?(?:代收|收取|收款|保管|办理|收齐)"
    r"|(?:费用|金额|每人|每生|每学期|标准|收费标准)?(?:为|共计|合计)?\s*" + _AMOUNT.pattern + r"(?:" + _PAY_TO + r")?"
    r"|(?:通过|使用)(?:指定|学校)?(?:缴费平台|支付平台|银行转账|现金|扫码)(?:缴费|支付)?)"
)
_FIXED_NOTICE = re.compile(r"(?:不同年级的学生一律须|全年级不少于八成的同学须|未分班的新生须)(?:在|于)?")
_REFUSAL_CENTRE = re.compile(r"(?:者|的(?=\s*$))")
_ATTRIBUTIVE_ENTRY = re.compile(r"^(?:凡|已|尚|未|没|不|拒|成绩|经济|家庭|贫困|首批|全年级|全班|上周|本周|"
                                r"参加|报名|购买|缴费|交费|缴纳|分班|在读|在校|符合|随班|住宿|住校|来校|"
                                r"所有|全体|任何|本年级|本班|有困难|不同)")
_ISLAND_DELIMITER = re.compile(r"[；，。？！：;,:!?]")
_ISLAND_LEFT = re.compile(r"(?:向|对|给|为|把|将)(?=(?:所有|任何|全体|本年级|本班|有困难|成绩|"
                          r"已|尚|未|没有|不|拒|经济|贫困|参加|报名))")
_ISLAND_CONTROL = re.compile(_alternatives(_BRIDGE | set(_PROHIBITION)))
_LINK_TRANSITION = re.compile(r"(?:的|者|过)?(?:之后|以后|后|随即|然后|再|便|则)?")
_EVENT_TRANSITION = re.compile(r"(?:之后|以后|后|便|则|由|交由|不予|不得|不准|未再|一律|必须|重新)[^\ufffc]{0,22}$|不$")
_RECIPIENT_MARKER = re.compile(r"给(?=" + _RECEIVER.pattern + r"$)")
_OBJECT_END = re.compile(r"(?:的行为|的提议|之后|以后|后|的)$")
_DESTINATION_VERBS = {"发到", "上传到", "提供给", "发给", "发送给", "交给"}
_BRIDGE_OBJECT_END = re.compile(r"[把将向]")
_POST_QUESTION = re.compile(r"^(?:是否|有无必要|合规吗|可行吗|能否)")
_DEFERRED = re.compile(r"暂缓|待定|另行通知")
_CHOICE = re.compile(r"(?:也)?(?:自愿报名|自愿参加|课后服务自愿参加)")
_AGENT_TARGET = re.compile(r"(?:全体|所有|各班|本班)?(?:学生|新生|同学们?|家长)|班主任|教师|老师|各班|年级组|教务处")

# 口径 §1 句首主句及 §3.1、§3.3、§3.4。对象槽按谓词组绑定，余字交给封闭细化槽。
_FEE_OBJECT = re.compile(
    r"(?:意外伤害保险(?:费)?|课后服务(?:费)?|研学(?:旅行|活动)?(?:费|费用)?|校服(?:费)?"
    r"|教辅(?:资料|材料|费)?|(?:学生)?交通费|演出服装费用|资料费|材料费|班费|报名费|活动费"
    r"|练习册|安全手册|教材费|教材|补习费|保险费)(?:" + _AMOUNT.pattern + r")?"
)
_FEE_WITH_DETAIL = re.compile(r"(?P<object>" + _FEE_OBJECT.pattern + r")(?P<detail>" + _DETAIL.pattern + r")?")
_RANK_OBJECT = re.compile(r"(?:(?:本班|全班|本次|学生|期末|考试|期末考试)?(?:考试成绩|成绩排名|成绩单|成绩|排名|名次|分数))")
_WIDE_RANK_OBJECT = re.compile(r"[把将](?P<object>" + _RANK_OBJECT.pattern + r")$")
_RANK_VERBS = {"排名", "分班", "排座", "公布", "张贴", "通报", "公示", "发布", "晒", "发成绩", "发到", "上传到", "上传"}
_INFORMATION = re.compile(r"(?:学生和家长|学生|家长)(?:的)?(?:联系方式|电话(?:号码)?|微信号|学籍号|学号|名单|通讯录|信息)|生源")
_INSTITUTION = re.compile(r"(?:校外|[“\"][^“”\"]+[”\"])?(?:培训机构|辅导机构|补习班)")
_TRANSFER = {"提供", "提供给", "发给", "发送", "发送给", "透露", "泄露", "转交", "移交", "推荐", "输送"}
_TUTOR_OBJECT = re.compile(
    r"(?:(?:全体|所有)?(?:学生|同学们?|新生)(?:周[一二三四五六日末])?参加)?"
    r"(?:周[一二三四五六日末])?校外(?:培训机构的|辅导机构的)?(?:有偿|收费|付费)"
    r"(?:一对一|学科)?(?:补课|补习|辅导|培训班|培训)"
)
_TUTOR_VERBS = {"推荐", "介绍", "参加", "参加培训", "联系", "辅导", "培训", "培训学生"}
_IDENTITY_SLOT = re.compile(
    r"贫困家庭(?:子女|成员|学生)|低保家庭(?:子女|成员|学生)|(?:资助|受助)对象|留守(?:儿童|学生)"
    r"|单亲家庭(?:子女|成员|学生)|随班就读学生|孤儿|残疾学生|慢性肾病|抑郁症|哮喘|肺炎|癫痫"
)
_IDENTITY_NO_OBJECT = {"享受助学金", "被记过", "受处分", "被处分", "受到处分"}
_IDENTITY_ROLE = re.compile(
    r"(?:留守儿童|单亲家庭|残疾儿童|残障儿童|受助学生|资助对象|低保家庭学生)"
    r"(?:关爱|帮扶|审核|评选|康复|志愿|中心|之家|小组|社团|委员会|服务队)*"
    r"(?:志愿者|负责人|组长|副队长|委员|成员|队员|帮扶对象)"
)
_FEE_VOLUNTARY = re.compile(r"(?:课后服务|研学(?:活动)?)自愿参加")
_FIXED_ISLAND = re.compile(r"(?:成绩不理想|成绩不达标|不同年级|全年级不少于八成|未分班)(?:的)?")
_RANK_LOCATION = re.compile(r"(?:在|到)?(?:班级群|家长群|班群|微信群|宣传栏|公告栏)")
_POST_NEGATIVE = re.compile(r"(?:是)?(?:绝对)?(?:不可能|不行|根本不行|做不到)(?:的)?$")
_RANK_VERBAL = re.compile(r"(?:按(?:考试)?|不(?:搞|进行|组织)(?:考试)?)成绩$")
_NONASSERTED_ADJUNCT = re.compile(
    r"以(?:家委会|班费|辅导答疑|调研)名义|以(?:辅导答疑|调研)为由|借研学名义|"
    r"以班主任身份|承诺|提醒|拍照|按学校规定|班会上|家长群|再|私自|"
    r"按家委会群里的报价|向各户|另(?=由)|(?:义务教育|高中|中职)阶段|违规|面向家长"
)
_NEGATIVE_PREFIX_ADJUNCT = re.compile(r"(?:义务教育|高中|中职)阶段|家长群(?=[不未])|面向家长的材料|起草时|"
                                      r"#{1,6}\s*(?:[一二三四五六七八九十]+、)?|[但而](?=仍?不)")
_NEGATIVE_WRAPPER = re.compile(r"写(?:出|成)?|规定")
_FREE_TAIL = re.compile(
    r"(?:(?:每[人生]|费用|金额|收费(?:标准)?|价格)(?:为|是)?\s*)?"
    r"(?:(?:全部|全程|完全|一律|均)?免费|[0０]+(?:[.．][0０]+)?\s*元)"
    r"|(?:不|免)(?:向(?:全体|所有)?(?:学生|家长|监护人|家庭))?(?:收取|收|收费)(?:任何)?(?:费用|款项)?"
    r"|(?:费用)?由(?:本校|我校|学校)(?:全额|全部)?承担"
    r"|(?:费用)?由财政全额(?:拨款|负担|承担)"
    r"|免费(?:发放|发给|提供给)(?:全体|所有)?(?:学生|同学|新生|家长)?"
)
_PROJECT_CHOICE = re.compile(r"(?:(?P<project>[^\s：:]{1,24}?)(?:实行|按)?)?自愿(?:参加|报名|选购|购买|订购)(?:原则)?")
_VOLUNTARY_DETAIL = re.compile(r"(?:坚持|按|实行)自愿原则|完全自愿")
_ENROLLED = re.compile(r"^(?:凡)?(?:已)?自愿(?:报名|参加)(?:的(?:学生|同学)|者)")
_OPTIONAL_TOPIC = re.compile(r"(?P<project>[^\s：:]{1,24}?)由(?=(?:本校|我校|学校|学生|家长|监护人))")
_TEACHERS = re.compile(r"(?:全体|各位|本校|在职|任课)?(?:教师|老师|教职工|班主任)")
_TRAINING = r"(?:校外)?(?:免费|有偿|收费|付费)?(?:师德|教研|业务|继续教育|班主任工作|教学技能|急救)?(?:培训(?:班)?|研修(?:班)?|进修)"
_TEACHER_TRAINING = re.compile(
    rf"(?:{_AGENT.pattern})?(?P<head>组织|安排|动员)(?:{_TEACHERS.pattern})(?:参加|报名)(?:{_TRAINING})"
    rf"|(?:{_AGENT.pattern})?(?:组织{_INSTITUTION.pattern})?为(?:{_TEACHERS.pattern})"
    rf"(?P<delivery>组织|开展|举办|安排)(?:{_TRAINING})"
    rf"|(?:{_AGENT.pattern})?(?P<direct>培训)(?:{_TEACHERS.pattern})"
)
_MONEY = re.compile(r"[^\W\d免退收缴交付浪公经消]费|费用|款(?:项|额)|(?:校服|教辅|教材|资料)款(?!式)|" + _AMOUNT.pattern)
_PAYMENT_DISPOSAL = re.compile(r"[把将](?P<object>[^\s把将；，。]{1,32})$")
_SCORE_PENALTY = re.compile(r"(?:除|减)?(?:[\d一二三四五六七八九十]+)?(?:操行|德育|考核|评比|综合)?分")
_PAID_TUTORING_ACTIVITY = r"(?:校外)?(?:有偿|收费|付费)(?:补课|补习|辅导|培训)(?:班|活动|行为)?"
_PAID_TUTORING = re.compile(_PAID_TUTORING_ACTIVITY)
_UNDERTAKING = re.compile(r"(?:本校|我校|学校|教师|老师|班主任)?(?:坚决)?"
                          r"(?:(?:自觉抵制|决定查处)|劝阻(?:教师|老师|班主任)(?:宣传|推介))" + _PAID_TUTORING_ACTIVITY +
                          r"|(?:本校|我校|学校|教师|老师|班主任)?(?:可以|应|须)举报(?:上述行为|该行为)?"
                          r"|(?:本校|我校|学校|教育局)对\S+(?:行为)?实行零容忍")
_REPORT_CONTACT = re.compile(r"举报(?:电话|邮箱)(?:为|是)?\s*(?:\d[\d-]*|[^\s@]+@[^\s@]+)")
_PUBLISH_CONTACT = re.compile(r"(?:本校|我校|学校|教师|班主任)(?:按(?:照)?(?:上级|有关)要求)?"
                              r"(?:公布|公示|公开|提供)[^\s，；。！？]{0,28}举报(?:电话|邮箱)(?:为?[\d-]+)?")
_COMMITTEES = {"家委会", "家长委员会"}
_COMMITTEE_ROLE = re.compile(r"(?:以)?(?:家委会|家长委员会)(?:名义|决定|决议|通过|商议|收取|收缴|代收|筹集|核定|配合|登记)")
_COMMITTEE_HANDOFF = re.compile(r"由(?:家委会|家长委员会)(?:负责)?(?:落实|办理|收取|筹集|代收)")
_COMMITTEE_DELEGATE = re.compile(r"委托(?P<agent>家委会|家长委员会)(?:负责)?$")
_COMMITTEE_HEARING = re.compile(r"(?:家委会|家长委员会)(?:就\S+)?听取\S+")
_COMMITTEE_ACTOR = re.compile(r"(?:家委会|家长委员会)(?=先|随后|已|将|须)")
_CHARGE_LABEL = re.compile(r"^(?:的|标准|流程|情况|依据|要求|统一管理|办法|费等|与|及)|使用情况|核算|归档|公示明细")
_REVERSED_REFUSAL = re.compile(
    r"的(?:都|均)?(?:是|为)(?P<condition>(?:" + _REFUSAL.pattern + r")[^的]+)的(?:学生|同学|新生|家长)$"
)
_PROHIBITIVE_WRAPPER = re.compile(r"^(?:起草时)?不写|^(?:(?:义务教育|高中|中职)阶段)?(?:学校|本校|我校)?"
                                  r"(?:严禁|禁止|切勿|不得)(?:规定|把|将|作出|实施)")
_SCORE_FRAGMENT = re.compile(r"[^，。；！？!?]{0,16}(?:平均分|均分|考了|总分)[^，。；！？!?\d]{0,4}\d")
_LINKED_DENIAL = re.compile(r"^(?:(?:学校|本校|我校))?不向\S{1,18}(?:介绍|提供)")
_RANK_WIDE_TIME = re.compile(r"本学期|本学年|本月|本年度|今年|今后|今起|今日|今天|明天|明年|下学期|下学年|从今以后")
_AUTONOMOUS_ENROLMENT = re.compile(
    r"(?:家长|监护人)自行(?:给孩子)?(?:报(?:名|读)?|选择|联系)(?:校外|周末|假期)\S+"
)
_NEUTRAL_ASIDE = re.compile(r"(?:以任何名义|按标准)(?:[，、]按标准)?")
_LEXICAL_OBJECTS = (_FEE_OBJECT, _RANK_OBJECT, _TUTOR_OBJECT, _INFORMATION, _IDENTITY_SLOT, _INSTITUTION)
_ASSISTANCE_OBJECT = re.compile(r"(?:课外)?(?:书籍|绘本|文具|作业|功课|雨具)")
_FINANCE_OBJECT = re.compile(r"(?:电费(?:" + _AMOUNT.pattern + r")?|余额|(?:费用)?收支(?:情况)?)")
# 口径 §3.2、§3.4。账务和帮扶动词留宽层证据。
_WIDE_ONLY_ACTIONS = {"支付", "捐赠", "送去", "帮助", "陪伴"} | _WIDE_CONSEQUENCES | _PAYMENT_DELIVERY
_INSURANCE_TITLES = {"《意外伤害保险》", "“意外伤害保险”"}
_RECORDED = re.compile(r"(?:已(?:经)?(?:统一|实际)?(?:实施|执行|组织|开展|购买|订购|收取|缴纳)|"
                       r"实施后|执行后|发生后|已实际)")
_HISTORICAL = re.compile(r"往年|去年|历史上|当年|未实行|未实施|当前未")

def _number_separator(text, index):
    return (0 < index < len(text) - 1 and text[index - 1].isdigit()
            and text[index + 1].isdigit()
            and (text[index] in ".．:：" or
                 (text[index] in ",，" and _THOUSANDS.match(text, index + 1))))


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
        if char in _LINE_ENDS:
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
    covered = iter(_ISLAND_CONTROL.finditer(text))
    control = next(covered, None)
    for match in _PREDICATES.finditer(text):
        verb = match[0]
        while control is not None and control.end() <= match.start():
            control = next(covered, None)
        if control and control[0] in _PROHIBITION and control.start() <= match.start() < control.end():
            continue
        suffix = _NOUN_SUFFIX_RE.get(verb)
        if suffix and suffix.match(text, match.end()):
            continue
        if text.endswith(_NOUN_PREFIX.get(verb, ()), 0, match.start()) and not (
            verb == "排名" and _RANK_VERBAL.search(text, max(0, match.start()-12), match.start())
        ):
            continue
        if verb in _IDENTITY and verb in {"系", "是", "属于"} and not _IDENTITY_OBJECT.search(text, match.end()):
            continue
        if verb == "进行" and not _PAID_TUTORING.match(text, match.end()):
            continue
        yield match


def _closed_left(text, start, end, verbs):
    if _choice_detail(text[start:end].strip()):
        return True
    last = bisect_left(verbs, end)-1
    if last < 0 or verbs[last] < start:
        return False
    verb = _PREDICATES.match(text, verbs[last], end)
    suffix = text[verb.end():end].strip()
    return any(pattern.fullmatch(suffix) for pattern in _LEXICAL_OBJECTS) or (
        not suffix and (verb[0] in _IDENTITY_NO_OBJECT or _TOPIC.match(text, start, verb.start()) is not None
                        or verb[0] in {"排名", "分班", "排座"} and
                        _RANK_VERBAL.search(text, start, verb.start()))
    )


def _connector(text, index, start, end, verbs, breaks, in_island, prior):
    if (text.startswith(_ATOMIC_JOIN, index) or text[index-1:index+1] == "不但"
            or in_island):
        return ""
    for join in _JOIN:
        if not text.startswith(join, index):
            continue
        right = index + len(join)
        if right >= end or text[right] in _BREAKS:
            return ""
        if join in _TURN:
            if not text[start:index].strip() and prior:
                return join if _closed_left(text, *prior, verbs) else ""
            if not _closed_left(text, start, index, verbs):
                return ""
        left_verb = bisect_left(verbs, start)
        right_verb = bisect_left(verbs, right)
        next_break = breaks[bisect_left(breaks, right)]
        if (join in {"且", "同时", "还", "并"} and left_verb < len(verbs) and verbs[left_verb] < index
                and _SCORE_FRAGMENT.match(text, right, next_break)):
            return join
        if (left_verb < len(verbs) and verbs[left_verb] < index
                and right_verb < len(verbs) and verbs[right_verb] < next_break):
            if join == "、":
                subject = _AGENT.match(text, right, verbs[right_verb])
                slot = subject.end() if subject else right
                if (verbs[right_verb] != slot and not text.startswith(_PROHIBITION + _NEGATIVE, slot)
                        and not (_MODAL.match(text, slot) or _PREP.match(text, slot))):
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
    surface = "".join(visible)
    verbs = [start+match.start() for match in _verb_matches(surface)]
    islands = [(start+a, start+b) for a, b, _ in _islands(surface)] if "的" in surface or "者" in surface else ()
    previous = ""
    prior = None
    island = iter(islands)
    active = next(island, None)
    for index in positions:
        if index < start or index in escaped:
            continue
        char = text[index]
        if char in _BREAKS and not _number_separator(text, index):
            stop = index + 1
            if char in _SENTENCE_END:
                while stop < end and text[stop] in _SENTENCE_END and stop not in escaped:
                    stop += 1
            yield start, index, text[index:stop], previous
            prior = (start, index) if char not in _SENTENCE_END else None
            start, previous = stop, ""
        elif char in "而但另以或同还并且和、/／":
            while active and index >= active[1]:
                active = next(island, None)
            join = _connector(text, index, start, end, verbs, breaks, active and active[0] <= index, prior)
            if join:
                yield start, index, join, previous
                prior = start, index
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
        self.offsets = self.graph.line_offsets
        for line in self.lines:
            self.offsets.append(self.offsets[-1] + len(line))
        self.paragraph = 0
        self.sentence = 0
        self.sentence_count = 0
        self.siblings = {}
        self.header = None
        self.header_columns = []
        self.table = self.row = self.list_count = 0
        self.tables = {}
        self.open_frame = None
        self.questions = set()

    def next_sentence(self):
        self.sentence_count += 1
        self.sentence = self.sentence_count

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
                # 内联冒号框覆盖本句。段落框通过 frames 跨句传入。
                active = frames
                if self.open_frame is not None:
                    source = self.graph.frames[self.open_frame].source
                    active += self.graph.clauses[source].frames + (self.open_frame,)
                active = tuple(dict.fromkeys(active))
                groups = self.groups(line, offset, left, right, pairs)
                clause = self.clause(left + offset, right + offset, separator, connector, frames=active,
                                     parent=parent, groups=groups,
                                     malformed=any(left <= index < right for index in bad), **position)
                if separator[:1] in ("", "。", ".", "．", "？", "?") and clause.text.endswith(tuple(_QUESTION_PARTICLES)):
                    self.questions.add(self.sentence)
                saved = self.open_frame
                containing_sentence = self.sentence
                self.open_frame = None
                for group in groups:
                    inner = self.graph.text[group.content.start:group.content.end]
                    if group.kind == "title" or not any(_verb_matches(inner)):
                        continue
                    kind = "quote" if group.kind == "quote" else "annotation"
                    context = Context.QUOTE if kind == "quote" else Context.UNKNOWN
                    child_frame = self.frame(kind, context, group.span, clause.id)
                    self.next_sentence()
                    self.line_parts(line, offset, group.content.start-offset, group.content.end-offset,
                                    pairs, bad, escaped, frames=active + (child_frame,),
                                    parent=clause.id, **position)
                    self.open_frame = None
                self.sentence = containing_sentence
                self.open_frame = saved
                if separator in ("：", ":"):
                    frame_context = _intro(clause.text)
                    clause.context = frame_context
                    self.open_frame = self.frame("colon", frame_context, clause.span, clause.id)
                    last_header = self.open_frame
                else:
                    last_header = None
            if separator and separator[0] in _SENTENCE_END:
                if "？" in separator or "?" in separator:
                    self.questions.add(self.sentence)
                self.next_sentence()
                self.open_frame = None
        return last_header if self.open_frame is not None else None

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
            if not header and (column in item_columns or (
                not item_columns and (_PROJECT.fullmatch(label) or
                                      _PROJECT_CELL.fullmatch(label) and not any(_verb_matches(label)))
            )):
                project = self.project(label, self.span(offset+left, offset+right)) if label else None
            self.open_frame = None
            if header and left < right:
                self.clause(offset+left, offset+right, "", "", table=table, row=self.row, column=column, table_header=True)
            else:
                column_header = self.header_columns[column-1] if column <= len(self.header_columns) else ""
                self.line_parts(line, offset, left, right, pairs, bad, escaped, frames=active,
                                table=table, row=self.row, column=column, project=project, column_header=column_header)
        self.open_frame = None
        self.next_sentence()

    def list_scope(self, blocks, level, previous_level, previous_intro, offset, start):
        # 同体系同级编号共享块。跨到父级时结束原引导的子列表。
        while blocks and level < blocks[-1][0]:
            blocks.pop()
        if not blocks or level > blocks[-1][0]:
            intro_frame = self.graph.frames[previous_intro] if (
                previous_intro is not None and (previous_level is None or level > previous_level)
            ) else None
            self.list_count += 1
            source = intro_frame.source if intro_frame else len(self.graph.clauses)
            evidence = intro_frame.evidence if intro_frame else self.span(offset, offset+start)
            list_frame = self.frame("list", Context.UNKNOWN, evidence, source)
            blocks.append((level, self.list_count, intro_frame.id if intro_frame else None, list_frame))
        _, list_id, _, _ = blocks[-1]
        active = tuple(frame for _, _, intro, list_frame in blocks for frame in (intro, list_frame)
                       if frame is not None)
        return list_id, active

    def split(self, paragraph_starts):
        scans = [_scan_line(raw.rstrip(_LINE_ENDS)) for raw in self.lines]

        blocks = []
        previous_intro = None
        previous_level = None
        word_frame = None
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
                word_frame = previous_intro = self.open_frame = None
                self.paragraph += 1
                self.next_sentence()
                in_table = False
            elif paragraph_start:
                self.paragraph += 1
                self.next_sentence()
                word_frame = None
                if not marker:
                    blocks.clear()
                    word_frame = previous_intro
                    previous_intro = self.open_frame = None
            if not line.strip():
                continue
            if cells:
                blocks.clear()
                word_frame = previous_intro = self.open_frame = None
                if not in_table:
                    self.table += 1
                    self.row = 0
                    self.header = None
                    self.header_columns = []
                    self.paragraph += 1
                    self.next_sentence()
                in_table = True
                if not divider:
                    is_header = index < len(scans) and scans[index][-1]
                    self.table_line(line, offset, cells, pairs, bad, escaped, is_header)
                continue
            if in_table:
                self.paragraph += 1
            in_table = False
            active = (word_frame,) if word_frame is not None else ()
            list_id = None
            level = None
            if marker:
                indent = len(marker["indent"].expandtabs(4))
                level = indent, _LIST_LEVEL[marker.lastgroup]
                list_id, active = self.list_scope(blocks, level, previous_level, previous_intro, offset, start)
                self.open_frame = None
                self.next_sentence()
            elif blocks or (not paragraph_starts and previous_intro is not None):
                blocks.clear()
                if not paragraph_starts and previous_intro is not None:
                    # 纯文本以紧邻正文行作为下一段，冒号管到该行末。
                    active = (previous_intro,)
                previous_intro = self.open_frame = None
                self.paragraph += 1
                self.next_sentence()
            previous_intro = self.line_parts(line, offset, start, len(line), pairs, bad, escaped,
                                             frames=active, list_block=list_id)
            previous_level = level
            if marker:
                self.next_sentence()
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
    wide_only: bool = False


def _islands(visible):
    """找到紧邻中心词的定语。定语左边界停在本层控制词、模态或介词之后。"""
    start = 0
    for centre in _CENTRE.finditer(visible):
        prefix = visible[start:centre.start()]
        edge = max((mark.end() for mark in _ISLAND_DELIMITER.finditer(prefix)), default=0)
        controls = [m.end() for m in _ISLAND_CONTROL.finditer(prefix, edge)]
        prep = [m.end() for m in _ISLAND_LEFT.finditer(prefix, edge)]
        left = start + max([edge, *controls, *prep])
        attribute = visible[left:centre.start()].strip()
        if attribute and (_ATTRIBUTIVE_ENTRY.match(attribute) or controls or prep):
            yield left, centre.start(), centre.end()
        start = centre.end()
    for refusal in _REFUSAL.finditer(visible, start):
        if visible.endswith(("没有", "无"), 0, refusal.start()) or refusal[0].startswith("没有") and "没有不" in visible:
            continue
        marker = _REFUSAL_CENTRE.search(visible, refusal.end())
        if marker and not _ISLAND_DELIMITER.search(visible, refusal.end(), marker.start()):
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


def _consume_prefix(text, start, end, *, linked=False, predicate=""):
    prefix = _Prefix()
    index = start
    if linked:
        index = _LINK_TRANSITION.match(text, index, end).end()
    tokens = _CONSEQUENCE_TOKENS if predicate in _CONSEQUENCES or predicate in _WIDE_CONSEQUENCES else _TOKENS
    scoped_negative = any(m[0] in _PROHIBITION + _NEGATIVE or m[0] == "不许"
                          for m in tokens.finditer(text, index, end))
    while index < end:
        if text[index].isspace():
            index += 1
            continue
        marker = ""
        if text.startswith("交由", index, end) or text.startswith("由", index, end):
            marker = "交由" if text.startswith("交由", index, end) else "由"
        match = _PREP.match(text, index, end)
        if not match and not marker and text[index] in "向对给为把将" and text[index+1:index+2].isspace():
            inherited = _AGENT.match(text, index+1+len(text[index+1:end])-len(text[index+1:end].lstrip()), end)
            if inherited:
                prefix.arguments[text[index]] = inherited.span()
                index = inherited.end()
                continue
        if (predicate in _COLLECTION and (recipient := _FEE_RECIPIENT.match(text, index))
                and (not match or match.end() != recipient.end())):
            match = recipient
            prefix.arguments["向"] = recipient.span("target")
            prefix.wide_only = True
        elif scoped_negative and (adjunct := _NEGATIVE_PREFIX_ADJUNCT.match(text, index, end)):
            prefix.wide_only = True
            match = adjunct
        elif prefix.negation and prefix.negation[0] in _PROHIBITION + _NEGATIVE and (
                wrapper := _NEGATIVE_WRAPPER.match(text, index, end)):
            prefix.wide_only = True
            match = wrapper
        elif match:
            key = match["marker"]
            # “将”加已识别受事时是处置槽，孤立的“将”交给模态。
            if key in prefix.arguments:
                prefix.complete = False
            prefix.arguments[key] = match.span("value")
            if key in ("在", "于") and _TIME_RE.fullmatch(match["value"]):
                prefix.timing = match["value"]
        elif not marker and "topic" not in prefix.arguments and (match := _TOPIC.match(text, index, end)):
            prefix.arguments["topic"] = match.span()
        elif (match := _bounded_match(_PERSON, text, index+len(marker), end) or
              _AGENT.match(text, index+len(marker), end)) and (marker or index == start or
                set(prefix.arguments) <= {"topic"} and
                (not prefix.agents or prefix.negation is not None or scoped_negative and prefix.wide_only)):
            prefix.agents.append((match[0], match.start(), match.end(), marker))
        elif marker:
            prefix.complete = False
            return prefix
        elif match := tokens.match(text, index, end):
            word = match[0]
            if word in _NOT_NEGATION:
                if not _NONNEG_PREFIX.fullmatch(word):
                    prefix.complete = False
            elif prefix.negation is None:
                prefix.negation = word, match.start(), match.end()
            else:
                prefix.complete = False
        elif match := (_MODAL.match(text, index, end) or _bounded_match(_MANNER, text, index, end)
                       or _bounded_match(_FIXED_PREFIX, text, index, end)):
            prefix.signals.add(match[0])
        elif predicate == "离校" and (match := _DEPARTURE_PREFIX.match(text, index, end)):
            prefix.signals.add(match[0])
        elif predicate in {"排名", "分班", "排座"} and (match := _RANK_PREFIX.match(text, index, end)):
            topic = match.span()
            prefix.arguments.setdefault("topic", topic)
        elif match := _TIME_RE.match(text, index, end):
            prefix.timing = match[0]
        elif predicate in _RANK_VERBS and (match := _RANK_WIDE_TIME.match(text, index, end)):
            prefix.wide_only = True
        elif scoped_negative and predicate in _RANK_VERBS and (match := _RANK_DENIAL_ADJUNCT.match(text, index, end)):
            prefix.wide_only = True
        elif scoped_negative and (match := _NONASSERTED_ADJUNCT.match(text, index, end)):
            prefix.wide_only = True
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
    recipient = _FEE_RECIPIENT.search(surface)
    for verb in _verb_matches(surface):
        if recipient and recipient.start("target") <= verb.start() < recipient.end("target"):
            continue
        if events:
            previous = events[-1]
            between = surface[previous.end():verb.start()].strip()
            complement = (previous[0] in {"提议", "提出建议"} and verb[0] in _RANK_VERBS
                          or previous[0] == "告知" and _NOTICE_PROHIBITION.fullmatch(between)
                          or previous[0] == "决定" and verb[0] in _COLLECTION and
                          _AGENT.match(surface) and _AGENT.match(surface)[0] in _COMMITTEES)
            if not complement and previous[0] not in _BRIDGE | {"查处", "立案查处", "制止", "劝阻"} and not _EVENT_TRANSITION.search(between):
                continue
        events.append(verb)
    return events


def _leading_context(text):
    if _PROHIBITIVE_WRAPPER.match(text):
        return Context.NEGATION
    if _PRECONDITION.match(text) or re.match(r"^凡(?=组织|安排|推荐|提供|动员)", text):
        return Context.CONDITION
    if _SOURCE.match(text):
        return Context.QUOTE
    if _REFERRAL.match(text) or _UNKNOWN_STANCE.match(text) or _STANCE_SUFFIX.search(text) or text.startswith("因"):
        return Context.UNKNOWN
    if _GOVERNANCE.search(text):
        return Context.GOVERNANCE
    if text.startswith(("是否", "难道")):
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
    if verb[0] in _DISCUSSION and "对" in prefix.arguments:
        explicit_object = prefix.arguments["对"]
    recipient = next((prefix.arguments[key] for key in ("向", "给", "为", "对") if key in prefix.arguments), None)
    tail = clause.text[verb.end():end].rstrip().rstrip(_PARTICLES)
    topic = prefix.arguments.get("topic")
    if (explicit_object or verb[0] in _DESTINATION_VERBS) and _RECEIVER.fullmatch(tail):
        recipient = (verb.end(), verb.end()+len(tail))
        tail = ""
    elif match := _RECIPIENT_MARKER.search(tail):
        recipient = (verb.end()+match.end(), verb.end()+len(tail))
        tail = tail[:match.start()]
    if verb[0] in _BRIDGE | {"推荐"}:
        tail = tail.split("参加", 1)[0] if "参加" in tail and not tail.startswith("参加") else tail
        tail = _BRIDGE_OBJECT_END.split(tail, maxsplit=1)[0]
        if not tail and len(prefix.agents) > 1 and prefix.agents[-1][3]:
            return prefix.agents[0][1:3], recipient
    tail = _OBJECT_END.sub("", _POST_NEG.sub("", tail)).rstrip()
    return explicit_object or ((verb.end(), verb.end()+len(tail)) if tail else topic), recipient


def _is_school(agent):
    return any(agent == name or agent.endswith(name) and
               agent.startswith(("本校", "我校", "任课", "在职", "各位", "任何")) or
               agent.startswith(name+"和") or agent.startswith(name+"与") for name in _SCHOOL)


def _record_action(builder, clause, verb, end, prefix, *, outer=None, parent=None, attributive=False,
                   forced_negative=False, post_reverse=False, ambiguous=False, start=0):
    graph = builder.graph
    verb_text = verb[0]
    text = clause.text
    local, reason = Polarity.UNKNOWN, ""
    negation = prefix.negation
    word = negation[0] if negation else ""
    if (word == "不是不" and verb_text not in _PUNITIVE_CONSEQUENCES
            or word == "没有不" and not text[:end].rstrip(_PARTICLES).endswith("的")
            or word in _DOUBLE and not text[verb.end():end].strip() and verb_text in {"是", "决定"}):
        reason = "反转后项待核"
    elif ambiguous:
        reason = "可行性或词元待核"
    elif not prefix.complete:
        reason = "未消费前置"
    elif forced_negative or verb_text == "免收":
        local = Polarity.NEGATIVE
    elif post_reverse or word in _DOUBLE or word == "不是不":
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
                    context, polarity, local, extent=_position(builder, clause, (start, end)),
                    agent=agent, agent_span=agent_span, school_agent=_is_school(agent),
                    agent_inherited=agent_inherited, object=obj, object_span=object_span,
                    topic=_argument(builder, clause, prefix.arguments.get("topic"))[0],
                    recipient=receiver, recipient_span=recipient_span, timing=prefix.timing,
                    mandatory=bool(prefix.signals & _MANDATORY) or verb_text in {"强迫", "强制"},
                    uniform="统一" in prefix.signals,
                    voluntary=verb_text == "允许" or any(_NON_COMPULSORY.search(signal) for signal in prefix.signals)
                    or bool(parent and parent.voluntary), exit=bool(_EXIT.search(text)),
                    refusal=(verb_text in _FEES or verb_text == "交")
                    and bool(_REFUSAL.match(text[negation[1]:] if negation else "")),
                    consequence=bool((verb_text in _CONSEQUENCES or verb_text in _WIDE_CONSEQUENCES) and
                    (local == Polarity.NEGATIVE or local == Polarity.UNKNOWN and negation
                     and _RESTRICTION.fullmatch(word) and negation[2] == verb.start()
                      or verb_text.startswith("取消")
                      or verb_text in _PUNITIVE_CONSEQUENCES and verb_text != "扣"
                      and (not negation or word in _DOUBLE or word == "不是不")
                      or verb_text == "扣" and _SCORE_PENALTY.fullmatch(obj))),
                    parent=parent.id if parent else None, attributive=attributive,
                    fixed_notice=bool(_FIXED_NOTICE.match(text) and verb_text in _FEES),
                    negation=_position(builder, clause, negation[1:] if negation else None), reason=reason)
    if parent and local == Polarity.POSITIVE and parent.polarity != Polarity.POSITIVE:
        if parent.polarity == Polarity.NEGATIVE and (parent.negation or outer == Context.NEGATION):
            action.negation = action.negation or parent.negation
            action.context, action.polarity = Context.NEGATION, Polarity.NEGATIVE
        else:
            action.context, action.polarity = parent.context, Polarity.UNKNOWN
    graph.actions.append(action)
    graph._by_clause.setdefault(clause.id, []).append(action)
    for frame_id in clause.frames:
        graph.frames[frame_id].actions.append(action.id)
    return action


def _project_islands(builder, clause, visible):
    if _REVERSED_REFUSAL.search(visible):
        # “受限者都是未缴者”先保留两个关系槽，最后取反向条件。
        return visible, [], {}, True
    projected = list(visible)
    antecedents = []
    island_arguments = {}
    unknown_island = False
    for start, attribute_end, centre_end in _islands(visible):
        attribute = visible[start:attribute_end]
        refusal = _REFUSAL.search(attribute)
        if refusal:
            candidates = list(_verb_matches(visible[start:attribute_end].rjust(attribute_end)))
            if candidates:
                verb = candidates[0]
                prefix = _consume_prefix(visible, start+refusal.start(), verb.start())
                if refusal[0].startswith("拒"):
                    prefix.negation = "拒", start+refusal.start(), start+refusal.start()+1
                    prefix.complete = True
                action = _record_action(builder, clause, verb, attribute_end, prefix, outer=Context.CONDITION,
                                        attributive=True, forced_negative=True, start=start)
                action.refusal = True
                antecedents.append(action.id)
        projected[start:attribute_end+1] = " " * (attribute_end+1-start)
        if start and visible[start-1] in "向对给为把将":
            marker = visible[start-1]
            projected[start-1:centre_end] = " " * (centre_end-start+1)
            island_arguments[marker] = (start, centre_end)
        unknown_island |= not bool(_FIXED_ISLAND.fullmatch(attribute))
        if visible[centre_end-1:centre_end] in ("的", "者"):
            projected[centre_end-1] = " "
    return "".join(projected), antecedents, island_arguments, unknown_island


def _clause_actions(builder, clause, outer, question):
    raw = clause.text
    visible = _surface(clause)
    surface, antecedents, island_arguments, unknown_island = _project_islands(builder, clause, visible)
    if clause.malformed and outer is None:
        outer = Context.UNKNOWN
    events = _events(surface)
    stance = _leading_context(raw)
    source = _PRECONDITION.match(raw) or _SOURCE.match(raw) or _REFERRAL.match(raw)
    start = source.end() if source else 1 if raw.startswith("因") else 0
    if clause.separator in ("：", ":") and _intro(raw) != Context.UNKNOWN:
        return [], None
    if not events:
        if antecedents:
            clause.context = Context.CONDITION
        return [], None
    tail = raw.rstrip().rstrip(_PARTICLES)
    post = bool(_POST_NEG.search(tail) and (len(events) == 1 or
                len(events) == 2 and events[0][0] in _BRIDGE and events[1][0] == "参加"))
    feasible = bool(_POST_FEASIBLE.search(tail))
    if (question or stance == Context.QUESTION) and outer is None:
        outer = Context.QUESTION
    outer = outer if outer is not None else stance

    actions = []
    prefixes = []
    for i, verb in enumerate(events):
        if verb.start() < start:
            continue
        previous = actions[-1] if actions else None
        bridge = previous if previous and (previous.predicate in _BRIDGE or outer == Context.GOVERNANCE) else None
        prefix = _consume_prefix(surface, start, verb.start(), linked=bool(previous and not bridge), predicate=verb[0])
        if not previous:
            prefix.arguments.update(island_arguments)
        word = prefix.negation[0] if prefix.negation else ""
        if i == 0 and post and not (word and word in _NEGATIVE):
            post = False
            if question and outer is None:
                outer = Context.QUESTION
        if question and outer is None:
            outer = Context.QUESTION
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
                                post_reverse=post and i == 0, ambiguous=feasible, start=start)
        if antecedents and (action.consequence or action.predicate == "离校"):
            action.consequence = True
            action.conditions = tuple(antecedents)
        if not action.agent and previous and previous.agent and prefix.complete and not prefix.arguments.get("topic"):
            action.agent, action.agent_span, action.school_agent = previous.agent, previous.agent_span, previous.school_agent
        if action.refusal:
            antecedents.append(action.id)
        actions.append(action)
        prefixes.append(prefix)
        start = verb.end() if bridge or verb[0] in _BRIDGE else end
    if actions and clause.context == Context.UNKNOWN:
        clause.context = outer if outer is not None else actions[0].context
    proof = _explain(builder, clause, actions, prefixes, post, unknown_island)
    if len(actions) == 1 and actions[0].consequence and (relation := _REVERSED_REFUSAL.search(raw)):
        left, right = relation.span("condition")
        verb = next((m for m in _verb_matches(visible[:right]) if m.start() >= left), None)
        if verb:
            prefix = _consume_prefix(visible, left, verb.start())
            condition = _record_action(builder, clause, verb, right, prefix, outer=Context.CONDITION,
                                       attributive=True, forced_negative=True, start=left)
            condition.refusal = True
            actions[0].conditions = (condition.id,)
    return actions, proof

def _local_prohibition(graph, action):
    return action.negation and graph.text[action.negation.start:action.negation.end] in _PROHIBITION


@dataclass(frozen=True)
class _Explanation:
    actions: tuple[Action, ...]
    actor: bool
    complete: bool
    suffix: str = ""


def _terminal_slot(clause, action, prefix, post):
    """返回对象／接收方和已消费的末位。槽位失配时不把余文塞进宾语。"""
    text = clause.text
    start = action.span.end-clause.span.start
    verb = action.predicate
    tail = text[start:]
    obj = receiver = None
    topic = prefix.arguments.get("topic")
    disposal = prefix.arguments.get("把") or prefix.arguments.get("将")
    if verb in _FEES:
        pattern = _FEE_OBJECT
        if verb == "办理" and tail in _INSURANCE_TITLES:
            return (start, len(text)), None, len(text)
        if not tail and topic and action.school_agent and _FEE_OBJECT.fullmatch(text[slice(*topic)]):
            return topic, None, start
        if detail := _FEE_WITH_DETAIL.fullmatch(tail):
            end = start+detail.end("object")
            return (start, end), None, end
    elif verb in _RANK_VERBS:
        if verb in _DESTINATION_VERBS:
            match = _RANK_LOCATION.match(tail)
            if match and _RANK_OBJECT.fullmatch(action.object):
                return disposal or topic, (start, start+match.end()), start+match.end()
            return None, None, start
        if (disposal or topic) and (not tail or tail == "的" or _RANK_LOCATION.fullmatch(tail)
                                   or post and _POST_NEG.match(tail.rstrip(_PARTICLES))):
            if _RANK_LOCATION.fullmatch(tail):
                return disposal or topic, (start, len(text)), len(text)
            return disposal or topic, None, start
        pattern = _FINANCE_OBJECT if _FINANCE_OBJECT.fullmatch(tail) else _RANK_OBJECT
    elif verb in _DESTINATION_VERBS and _INFORMATION.fullmatch(action.object):
        match = _INSTITUTION.match(tail)
        if match:
            return disposal, (start, start+match.end()), start+match.end()
        return None, None, start
    elif verb in _TRANSFER and _INSTITUTION.fullmatch(action.recipient):
        pattern = _INFORMATION
    elif verb in _TUTOR_VERBS:
        pattern = _TUTOR_OBJECT
    elif verb == "报名" and _TUTOR_TOPIC.match(text) and action.parent is not None and not tail:
        return None, None, start
    elif verb in _IDENTITY:
        if verb in _IDENTITY_NO_OBJECT and not tail:
            return None, None, start
        pattern = _IDENTITY_ROLE if _IDENTITY_ROLE.fullmatch(tail) else _IDENTITY_SLOT
    elif verb in {"捐赠", "送去", "讲解", "帮助", "陪伴", "补习功课"}:
        pattern = _ASSISTANCE_OBJECT
    elif verb == "支付":
        pattern = _FINANCE_OBJECT
    else:
        return None, None, start
    match = pattern.match(tail)
    if match:
        obj = start, start+match.end()
        start = obj[1]
    if not obj and verb in _TRANSFER and _INFORMATION.fullmatch(action.object):
        obj = disposal
    return obj, receiver, start


def _consumed_group(graph, group, action):
    def inside(span):
        return span is not None and span.start <= group.span.start and group.span.end <= span.end

    if group.kind == "bracket":
        return bool(_NEUTRAL_ASIDE.fullmatch(graph.text[group.content.start:group.content.end]))
    if group.kind == "quote" and inside(action.recipient_span) and _INSTITUTION.fullmatch(action.recipient):
        return True
    return (action.predicate == "办理" and action.object in _INSURANCE_TITLES
            and inside(action.object_span))


def _explain(builder, clause, actions, prefixes, post, unknown_island):
    if not actions:
        return None
    head, last = actions[0], actions[-1]
    raw = clause.text
    obj, recipient, end = _terminal_slot(clause, last, prefixes[-1], post)
    suffix = raw[end:].strip()
    if obj and (not suffix or _execution_detail(suffix) or post or _tail_binding(suffix, False)):
        last.object, last.object_span = _argument(builder, clause, obj)
    if recipient:
        last.recipient, last.recipient_span = _argument(builder, clause, recipient)
    elif obj and last.recipient_span and last.recipient_span.start >= clause.span.start+end:
        last.recipient, last.recipient_span = "", None
    if obj or recipient:
        last.extent = builder.span(last.extent.start, clause.span.start+end)

    chain = all(action.parent == parent.id for parent, action in zip(actions, actions[1:]))
    if chain:
        for parent, child in zip(actions, actions[1:]):
            if child.agent_span and parent.span.end <= child.agent_span.start < child.span.start:
                parent.object, parent.object_span = child.agent, child.agent_span
            elif (parent.predicate == "组织" and child.predicate == "参加" and not parent.object
                  and len(prefixes[0].agents) == 2 and prefixes[0].agents[1][3]):
                # “同学由年级组安排班主任组织参加”保留前置参加者。
                parent.object, parent.object_span = _argument(builder, clause, prefixes[0].agents[0][1:3])
    parsed_controls = all(not action.object or _AGENT_TARGET.fullmatch(action.object) for action in actions[:-1])
    terminal = bool(obj or recipient or last.predicate in _IDENTITY_NO_OBJECT or
                    _FEE_VOLUNTARY.fullmatch(raw))
    terminal |= bool(head.school_agent and head.predicate == "动员" and last.predicate == "报名"
                     and _TUTOR_TOPIC.match(raw) and end == len(raw))
    terminal |= last.predicate == "参加" and _CHOICE.fullmatch(raw) is not None
    known_prefix = (all(prefix.complete for prefix in prefixes) and not unknown_island
                    and all(len(prefix.agents) <= 1 or len(prefix.agents) == 2 and prefix.agents[-1][3]
                            for prefix in prefixes)
                    and all(action.local_polarity != Polarity.UNKNOWN for action in actions))
    disposal = prefixes[-1].arguments.get("把") or prefixes[-1].arguments.get("将")
    if disposal:
        eligible_object = (_RANK_OBJECT if last.predicate in _RANK_VERBS else _INFORMATION)
        known_prefix &= (obj == disposal and eligible_object.fullmatch(raw[slice(*disposal)]) is not None)
    topic = prefixes[-1].arguments.get("topic")
    if topic and last.predicate in _FEES and obj != topic:
        known_prefix &= _canonical_project(raw[slice(*topic)]) == _canonical_project(last.object)
    groups = all(_consumed_group(builder.graph, group, last) for group in clause.groups)
    if end < len(raw) and (post and _POST_NEG.fullmatch(suffix.rstrip(_PARTICLES)) or
                           suffix == "的" and "没有不" in raw[:end]):
        suffix = ""
    closed = (chain and parsed_controls and terminal and known_prefix and groups
                and (not suffix or _execution_detail(suffix)))
    complete = closed and not any(prefix.wide_only for prefix in prefixes)
    school = any(a.school_agent and not a.agent_inherited for a in actions)
    special = (head.fixed_notice or last.predicate in _IDENTITY and bool(head.agent)
               or last.predicate in _RANK_VERBS and bool(head.negation))
    if clause.malformed:
        complete = closed = False
    if not complete:
        clause.unconsumed = _position(builder, clause, (end, len(raw))) if suffix else clause.span
    if last.predicate in _IDENTITY and _IDENTITY_ROLE.fullmatch(last.object):
        special = False
    if last.predicate in _WIDE_ONLY_ACTIONS or _FINANCE_OBJECT.fullmatch(last.object):
        school = False
    return _Explanation(tuple(actions), school or special, complete, "" if post else suffix)


def _chain_head(graph, action):
    while action.parent is not None:
        action = graph.actions[action.parent]
    return action


def _roots(graph, actions):
    return list({_chain_head(graph, item).id: _chain_head(graph, item)
                 for item in actions if not item.attributive}.values())


def _binding_units(graph, actions, later):
    units = set()
    for root in _roots(graph, actions):
        clause = graph.clauses[root.clause]
        quote = next((i for i in reversed(clause.frames) if graph.frames[i].kind == "quote"), None)
        units.add(("quote", quote) if quote is not None and quote not in later.frames else ("action", root.id))
    return units


def _tail_binding(text, question):
    if _EXIT.fullmatch(text.removeprefix("也")):
        return None
    for binding, pattern in _BACK_BIND_RE:
        if pattern.search(text):
            return binding
    if question or _POST_QUESTION.match(text):
        return Binding.QUESTION
    return None


def _resolved_binding(graph, earlier, text, binding):
    raw = [graph.clauses[action.clause].text for action in earlier]
    recorded = any(_RECORDED.search(item) for item in raw)
    if binding == Binding.HALTED:
        if recorded or _RECORDED.search(text):
            return Binding.ACCOUNTABILITY
        if _HISTORICAL.search(text) or any(_HISTORICAL.search(item) for item in raw):
            return Binding.HISTORICAL
    if binding == Binding.REJECTED and recorded:
        return Binding.UNRESOLVED
    return binding or Binding.UNRESOLVED


def _bind(graph, earlier, later, binding):
    for action in earlier:
        action.binding, action.binding_clause = binding, later.id
        action.admission = action.admission_evidence = None
        if binding in {Binding.PROHIBITED, Binding.REJECTED, Binding.HISTORICAL, Binding.ALTERNATIVE}:
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
    return _DETAIL.fullmatch(text) is not None and _FREE.search(text) is None


def _choice_detail(text):
    return bool(_CHOICE.fullmatch(text) or _EXIT.fullmatch(text.removeprefix("也")))


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


def _parallel_subject(graph, before, clause, explanation, candidates):
    """口径 §1 的并列结构。只有免收／不统一订购一式可共享施事。"""
    if before is None or before.frames or clause.frames or clause.project is None:
        return None
    if clause.connector == "并":
        return next((a for a in graph.actions_for(before.id)
                     if a.school_agent and a.project not in (None, clause.project)
                     and (a.predicate == "免收" or a.predicate == "订购" and a.uniform)
                     and a.polarity == Polarity.NEGATIVE and not _local_prohibition(graph, a)), None)
    if not explanation.actor or not any(a.school_agent for a in explanation.actions):
        return None
    if clause.connector == "另" and before.id in candidates:
        return next((a for a in graph.actions_for(before.id)
                     if a.project not in (None, clause.project) and a.polarity == Polarity.POSITIVE), None)
    return None


def _grant_sentence(graph, clauses, explanations):
    """先验证全句，再一次性提交准入。失败时没有先前已放行的动作。"""
    if any(c.tail in {Tail.EVALUATION, Tail.CHOICE} or _EXIT.search(c.text)
           or _NON_COMPULSORY.search(c.text) or _FREE.search(c.text) or _FREE_TAIL.fullmatch(c.text) for c in clauses):
        return
    candidates = {}
    grants = []
    for clause in clauses:
        before = graph.clauses[clause.previous] if clause.previous is not None else None
        proof = explanations.get(clause.id)
        if clause.context == Context.NOTICE and clause.separator in ("：", ":"):
            continue
        if clause.tail == Tail.DETAIL:
            continue
        if not proof or not proof.complete:
            return
        actions = proof.actions
        if (len(actions) == 1 and actions[0].school_agent and
                actions[0].polarity == Polarity.NEGATIVE and clause.following is not None
                and graph.clauses[clause.following].connector == "并" and
                actions[0].project is not None and
                (actions[0].predicate == "免收" or actions[0].predicate == "订购" and actions[0].uniform)
                and not _local_prohibition(graph, actions[0])):
            continue
        if any(action.polarity != Polarity.POSITIVE or action.binding or action.voluntary
               or action.predicate in _NON_COLLECTING for action in actions):
            return
        source = None
        admission, evidence = Admission.MAIN, clause.span
        if not clause.frames and clause.connector:
            source = _parallel_subject(graph, before, clause, proof, candidates)
            if source is None:
                # 明确的“并/且/同时/还”仍要求前项已解析，且此处有自己的主语。
                if (clause.connector not in {"并", "且", "同时", "还"} or not proof.actor
                        or before is None or before.id not in candidates):
                    return
            admission, evidence = Admission.PARALLEL, before.span
        elif clause.frames:
            notices = [graph.frames[i] for i in clause.frames if graph.frames[i].kind == "colon"]
            if not notices or any(frame.context != Context.NOTICE for frame in notices) or not proof.actor:
                return
            frame = notices[-1]
            if frame.clauses[0] != clause.id:
                # 已完全解释的同句并列能支持首项；通知资格只赋给首项。
                continue
            admission, evidence = Admission.NOTICE, frame.evidence
        elif not proof.actor:
            return
        if before is not None and not clause.connector and not clause.frames:
            admission = Admission.PARALLEL
        candidates[clause.id] = actions[0]
        grants.append((clause, actions, admission, evidence, source))
    for clause, actions, admission, evidence, source in grants:
        if source and clause.connector == "并":
            for action in actions:
                if not action.agent:
                    action.agent, action.agent_span = source.agent, source.agent_span
                    action.school_agent = action.agent_inherited = True
        _set_admission(clause, actions, admission, evidence)


def _resolve_correction(graph, before, clause, actions, history):
    if _EXIT.fullmatch(clause.text.removeprefix("也")):
        prior = [a for a in history if a.binding == Binding.UNRESOLVED and "不是不" in graph.clauses[a.clause].text]
        voluntary = next((a for a in reversed(history) if a.voluntary and a.exit and not a.mandatory
                          and a.project is not None and any(old.project == a.project for old in prior)), None)
        if voluntary:
            clause.tail = Tail.CHOICE
            _bind(graph, prior, clause, Binding.ALTERNATIVE)
            return True
    if before is None or clause.connector != "而是" or "不是不" not in before.text:
        return False
    prior = [action for action in graph.actions_for(before.id) if not action.attributive]
    repeated = [action for action in actions if any(old.predicate == action.predicate for old in prior)]
    projects = {old.project for old in prior if old.project is not None}
    if len(projects) == 1:
        for action in repeated:
            if action.voluntary and not action.object and action.project is None:
                action.project = next(iter(projects))
    alternative = any(action.polarity == Polarity.NEGATIVE for action in repeated)
    confirmed = any(action.timing or action.uniform for action in repeated if action.polarity == Polarity.POSITIVE)
    if alternative:
        _bind(graph, prior, clause, Binding.REJECTED)
    elif not confirmed or _DEFERRED.search(clause.text):
        _bind(graph, prior, clause, Binding.UNRESOLVED)
        _bind(graph, [action for action in repeated if not action.voluntary], clause, Binding.UNRESOLVED)
    return True


def _split_scope(graph, before, clause, inherited):
    if before is None:
        return None
    if clause.connector not in _PARALLEL:
        return None
    subject = _AGENT.match(clause.text)
    if subject and _JOIN_SIGNAL.match(clause.text, subject.end()):
        return None
    if before.context == Context.NEGATION and _PROHIBITIVE_WRAPPER.match(before.text):
        return next(iter(graph.actions_for(before.id)), None)
    for action in graph.actions_for(before.id):
        if _local_prohibition(graph, action) or (
                clause.connector in {"、", "/", "／"} and local_direct_negation(graph, action)
                and (action.predicate in {"组织", "推荐", "安排", "动员", "介绍"}
                     or action.predicate in _RANK_VERBS and not action.object)):
            return action
    return inherited


def _resolve_tail(graph, clause, actions, history, same_sentence, question, proof):
    if not history or clause.connector == "而是":
        return False
    prior = [action for action in history if not action.attributive and action.binding is None]
    if not prior:
        return False
    raw = clause.text
    if (actions and clause.context == Context.QUOTE and _SOURCE.match(raw)
            and all(action.polarity == Polarity.NEGATIVE for action in prior)):
        # 新闻来源引入一个独立动作，不把前项的直接否定翻成后置待核。
        return False
    if (_rank_clause_question(clause)
            and any(action.predicate in _RANK_VERBS for action in actions)
            and all(action.predicate in _RANK_VERBS and action.local_polarity == Polarity.NEGATIVE
                    for action in prior)):
        return False
    ref = bool(_BACKREF.match(raw))
    binding = _tail_binding(raw, question and not any(action.polarity == Polarity.POSITIVE for action in actions))
    if binding == Binding.QUESTION and not raw.startswith("是否") and any(
            action.school_agent and action.agent_span and action.agent_span.start >= clause.span.start
            and action.local_polarity == Polarity.POSITIVE for action in actions):
        # 完整疑问句可独立询问另一个行为。
        binding = None
    if binding is None and not ref:
        if _choice_detail(raw):
            clause.tail = Tail.CHOICE
            return True
        if _execution_detail(raw):
            clause.tail = Tail.DETAIL
            return True
    if binding is None and not ref and proof and proof.complete and (
        all(action.polarity == Polarity.POSITIVE for action in actions) or
        all(action.polarity == Polarity.NEGATIVE for action in actions + prior)
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
    if binding == Binding.REFUTED:
        clause.context = Context.REFUTATION
    elif binding == Binding.ACCOUNTABILITY:
        clause.context = Context.GOVERNANCE
    if not binding and not ref and all(
        a.polarity == Polarity.NEGATIVE or a.context in {Context.GOVERNANCE, Context.CONDITION} for a in prior
    ):
        return True
    if len(_binding_units(graph, prior, clause)) != 1:
        if ref or binding:
            _bind(graph, prior, clause, Binding.UNRESOLVED)
        else:
            _bind(graph, [action for action in prior if action.clause == clause.previous], clause, Binding.UNRESOLVED)
        return True
    if any(action.context == Context.CONDITION for action in prior) and _GOVERNANCE.search(raw) and not ref:
        return True
    _bind(graph, prior, clause, _resolved_binding(graph, prior, raw, binding))
    return True


def _inherited_context(graph, clause, before):
    outer = _external_context(graph, clause)
    if clause.parent is not None and outer in {None, Context.UNKNOWN, Context.QUOTE}:
        parent = graph.clauses[clause.parent]
        if parent.context in {Context.CONDITION, Context.GOVERNANCE, Context.REFUTATION} or (
            parent.context == Context.NEGATION and any(_local_prohibition(graph, a) for a in graph.actions_for(parent.id))
        ):
            return parent.context
    if outer is not None or before is None or before.context == Context.NOTICE:
        return outer
    if before.context in {Context.CONDITION, Context.QUOTE, Context.GOVERNANCE, Context.REFUTATION}:
        if before.context == Context.CONDITION and any(a.refusal for a in graph.actions_for(before.id)):
            return None
        return before.context
    if before.context == Context.UNKNOWN and clause.connector != "而是" and not (
        before.tail in {Tail.DETAIL, Tail.CHOICE} or _FEE_VOLUNTARY.fullmatch(before.text)
    ):
        return Context.UNKNOWN
    return None


def _apply_explanation(graph, clause, proof):
    if proof is None or proof.complete or clause.context not in {Context.ASSERTION, Context.REQUIREMENT}:
        return
    # 未消费词段仅阻断表层肯定；显式否定、回绑和局部动作证据仍供宽层核对。
    suffix = proof.suffix
    binding = _tail_binding(suffix, False) if suffix else None
    if suffix and _POST_NEGATIVE.fullmatch(suffix.rstrip(_PARTICLES)):
        binding = Binding.PROHIBITED
    if binding:
        _bind(graph, proof.actions, clause, _resolved_binding(graph, proof.actions, suffix, binding))
    else:
        clause.context = Context.UNKNOWN
        for action in proof.actions:
            if action.polarity == Polarity.POSITIVE:
                action.context, action.polarity = Context.UNKNOWN, Polarity.UNKNOWN
                action.reason = action.reason or "槽位未完整消费"


def _link_project_evidence(graph, clause, actions, before, history):
    if before and (not clause.connector or clause.connector in {"并", "且"}):
        refusals = [item for item in graph.actions_for(before.id) if item.refusal]
        if len(refusals) == 1:
            for item in actions:
                if item.consequence and not item.conditions:
                    item.conditions = (refusals[0].id,)
                    if item.project is None:
                        item.project = refusals[0].project
                    if item.project is not None and clause.id not in graph.projects[item.project].clauses:
                        graph.projects[item.project].clauses.append(clause.id)
                    if (refusals[0].project is not None and item.predicate in _TEXTBOOK_CONSEQUENCES
                            and clause.id not in graph.projects[refusals[0].project].clauses):
                        graph.projects[refusals[0].project].clauses.append(clause.id)
    if clause.project is None:
        return
    if before and _EXIT.fullmatch(clause.text.removeprefix("也")):
        for item in history:
            if item.project == clause.project:
                item.exit = True
    for item in history:
        if item.project == clause.project and item.voluntary and item.exit:
            for action in actions:
                if not (action.uniform or action.mandatory):
                    action.voluntary, action.exit = True, True


def _annotate(builder):
    graph = builder.graph
    by_sentence, by_list = defaultdict(list), defaultdict(list)
    projects = defaultdict(dict)
    prohibition, explanations = {}, {}
    sentences = defaultdict(list)
    for clause in graph.clauses:
        clause.question = clause.sentence in builder.questions
        if clause.table_header:
            continue
        before = graph.clauses[clause.previous] if clause.previous is not None else None
        history = by_sentence[clause.sentence, clause.parent, clause.table, clause.column]
        list_history = by_list[clause.list_block]
        same_sentence = bool(history)
        inherited = _split_scope(graph, before, clause, prohibition.get(before.id) if before else None)
        outer = _inherited_context(graph, clause, before)
        if inherited and outer in {None, Context.UNKNOWN}:
            prohibition[clause.id] = inherited
            outer = Context.NEGATION
        question = clause.sentence in builder.questions and clause.following is None
        actions, proof = _clause_actions(builder, clause, outer, question)
        if proof:
            explanations[clause.id] = proof
        if not actions:
            if clause.context == Context.UNKNOWN:
                clause.context = outer or (Context.QUESTION if question else
                                           _leading_context(clause.text) or clause.context)
        if inherited:
            for action in actions:
                action.negation = action.negation or inherited.negation
        _project_actions(builder, clause, graph.actions_for(clause.id), projects[clause.sentence, clause.parent])
        _link_project_evidence(graph, clause, actions, before, history)
        if not history or _choice_detail(clause.text):
            _apply_explanation(graph, clause, proof)
        tail_history = history
        if not tail_history and clause.list_block is not None and (
                _BACKREF.match(clause.text) or _tail_binding(clause.text, question)):
            tail_history = list_history
        if not _resolve_correction(graph, before, clause, actions, history):
            _resolve_tail(graph, clause, actions, tail_history, same_sentence, question, proof)
            if history and clause.tail not in {Tail.DETAIL, Tail.CHOICE}:
                _apply_explanation(graph, clause, proof)
        if clause.parent is None and clause.table is None:
            sentences[clause.sentence].append(clause)
        if clause.tail not in {Tail.DETAIL, Tail.CHOICE}:
            history.extend(actions)
        if clause.parent is not None and actions:
            parent = graph.clauses[clause.parent]
            if not graph.actions_for(parent.id):
                by_sentence[parent.sentence, parent.parent, parent.table, parent.column].extend(actions)
        if clause.list_block is not None and clause.tail not in {Tail.DETAIL, Tail.CHOICE}:
            list_history.extend(actions)
    for sentence, clauses in sentences.items():
        if sentence not in builder.questions:
            _grant_sentence(graph, clauses, explanations)


def _rank_clause_question(clause):
    return ("？" in clause.separator or "?" in clause.separator
            or clause.separator[:1] in {"", "。", ".", "．", "，", ",", "；", ";"}
            and clause.text.endswith(tuple(_QUESTION_PARTICLES))
            or clause.text.startswith("是否") or _RANK_INQUIRY.search(clause.text) is not None)


def local_direct_negation(graph, action):
    """局部否定可定位后续动作。"""
    clause = graph.clauses[action.clause]
    return (not clause.malformed and not _rank_clause_question(clause) and action.binding is None
            and not action.attributive and action.local_polarity == Polarity.NEGATIVE
            and action.negation is not None and clause.span.start <= action.negation.start < action.span.start
            and not ranking_reversal(graph, action))


def ranking_reversal(graph, action):
    """留下反转、反问和后置否定供人工复核。"""
    clause = graph.clauses[action.clause]
    if not action.negation:
        return False
    word = graph.text[action.negation.start:action.negation.end]
    tail = clause.text.rstrip(_PARTICLES)
    prefix = clause.text[:action.negation.start - clause.span.start]
    return (word in _DOUBLE or word == "不是不" or
            _RANK_RHETORIC.search(prefix) is not None or
            _POST_NEG.search(tail) is not None or tail.endswith(("不可以", "不能")))


def ranking_target(graph, action):
    """未消费的前置仍可含紧邻谓词的处置对象，只供宽层取证。"""
    clause = graph.clauses[action.clause]
    prefix = _surface(clause)[:action.span.start - clause.span.start]
    disposal = _WIDE_RANK_OBJECT.search(prefix)
    return disposal["object"] if disposal else action.object + action.topic


def paid_tutoring_delivery(action):
    return action.predicate in {"开展", "进行"} and _PAID_TUTORING.match(action.object) is not None


def teacher_training(graph, action):
    """整句必须是封闭的教师受训构式，且返回与基线相交的首动作。"""
    clause = graph.clauses[action.clause]
    if (action.attributive or clause.malformed or clause.question or clause.parent is not None
            or clause.groups or not _TEACHER_TRAINING.fullmatch(clause.text)):
        return None
    for neighbor in (clause.previous, clause.following):
        if neighbor is not None and graph.clauses[neighbor].sentence == clause.sentence:
            return None
    return _chain_head(graph, action)


def visible_evidence(clause):
    """屏蔽文件全称，保留原始偏移。文件名内的词不是正文行为证据。"""
    text = list(clause.text)
    for group in clause.groups:
        if group.kind != "title":
            continue
        start, end = group.span.start - clause.span.start, group.span.end - clause.span.start
        if re.search(r"意见|办法|规定|规则|通知|承诺书|工作方案|管理细则", clause.text[start:end]):
            text[start:end] = " " * (end - start)
    return "".join(text)


def _governance_holds(graph, clause, action):
    if any(graph.frames[i].context == Context.GOVERNANCE for i in clause.frames):
        return True
    text = _surface(clause)
    signal = _GOVERNANCE.search(text)
    if not signal or _RECORDED.search(text):
        return False
    subject = _AGENT.match(text)
    after_subject = subject.end() if subject else 0
    if (text.startswith(("对", "开展"), after_subject)
            and text[signal.end():] in ("", "工作", "行动", "活动")):
        return True
    prefix = _consume_prefix(text, 0, signal.start())
    if not prefix.complete or prefix.negation:
        return False
    if action:
        for governor in graph.actions_for(clause.id):
            if governor.span.start < clause.span.start + signal.end() <= governor.span.end:
                end = (governor.object_span or governor.span).end - clause.span.start
                if action.span.start > governor.span.start and re.match(r"(?:之后|以后|后|随即|然后|再|便|则)",
                        text[end:action.span.start - clause.span.start]):
                    return False
                break
    return True


def wide_suppressed(graph, clause, action=None):
    """决议、禁令、条件式治理等只屏蔽自身所辖候选。"""
    context = action.context if action else clause.context
    if action:
        if action.binding == Binding.ACCOUNTABILITY:
            return False
        if action.polarity == Polarity.NEGATIVE:
            return True
    if context in {Context.NEGATION, Context.REFUTATION}:
        return True
    head = _leading_context(clause.text)
    if head == Context.NEGATION:
        return True
    if clause.parent is not None:
        parent = graph.clauses[clause.parent]
        if _leading_context(parent.text) == Context.NEGATION:
            return True
    if clause.previous is not None:
        before = graph.clauses[clause.previous]
        if (before.separator in _PARALLEL and
                not any(a.agent or a.mandatory for a in graph.actions_for(clause.id)) and
                _LINKED_DENIAL.match(before.text) and not _POST_NEG.search(before.text.rstrip(_PARTICLES))):
            return True
    if context == Context.GOVERNANCE and _governance_holds(graph, clause, action):
        return True
    following = graph.clauses[clause.following] if clause.following is not None else None
    if context == Context.CONDITION or _leading_context(clause.text) == Context.CONDITION:
        if _CONDITIONAL_RESPONSE.search(clause.text) or following and _CONDITIONAL_RESPONSE.search(following.text):
            return True
    if _UNDERTAKING.fullmatch(clause.text) or _PUBLISH_CONTACT.fullmatch(clause.text):
        return True
    if (_REFERRAL.match(clause.text) and following and
            (_REPORT_CONTACT.fullmatch(following.text) or _UNDERTAKING.fullmatch(following.text))):
        return True
    if _AUTONOMOUS_ENROLMENT.fullmatch(clause.text):
        return True
    if _REFERRAL.match(clause.text) and any(
            child.parent == clause.id and child.context == Context.REFUTATION for child in graph.clauses):
        return True
    return False


def free_project(graph, clause, action=None):
    """免费证据取收款槽、数量槽或当前项目直接相邻的独立细化。"""
    if _FREE_TAIL.fullmatch(clause.text):
        return True
    if action and action.object_span and not action.attributive:
        obj = action.object
        if (_FREE.fullmatch(obj) or re.fullmatch(r"[^零0０\s]{0,24}?" + _FREE.pattern, obj)
                and not _MONEY.search(_FREE.sub("", obj))):
            return True
        if _forced_collection(graph, action):
            return False
        if (re.fullmatch(r"(?:校内|校外)?免费[^的]{1,22}", obj)
                and not _MONEY.search(_FREE.sub("", obj))):
            return True
    following = graph.clauses[clause.following] if clause.following is not None else None
    project = action.project if action else clause.project
    local_projects = {item.project for item in graph.actions_for(clause.id) if item.project is not None}
    if local_projects and local_projects != {project}:
        return False
    if (action is None and any(_forced_collection(graph, item) for item in graph.actions_for(clause.id))):
        return False
    if (following and project is not None and following.sentence == clause.sentence
            and not following.connector and following.parent == clause.parent
            and (following.table, following.row, following.column) == (clause.table, clause.row, clause.column)
            and _FREE_TAIL.fullmatch(following.text)):
        return True
    return any(group.kind == "bracket" and _FREE_TAIL.fullmatch(
        graph.text[group.content.start:group.content.end]) for group in clause.groups)


def optional_charge(graph, clause, action, related):
    """退出细化只有唯一项目先行项时才可绑定。"""
    candidates = [action] if action else graph.actions_for(clause.id)
    related = [c for c in related if c.parent == clause.parent and c.sentence == clause.sentence]
    project = action.project if action else clause.project
    def key_for(part, project_id):
        if project_id is not None:
            return _canonical_project(graph.projects[project_id].label)
        if topic := _OPTIONAL_TOPIC.match(part.text):
            return _canonical_project(topic["project"])
        return None

    key = key_for(clause, project)
    choices, exits, waived = set(), set(), set()
    current = None
    leading_exit = False
    leading_waiver = False
    for part in related:
        current = key_for(part, part.project) or current
        choice = _PROJECT_CHOICE.fullmatch(part.text)
        if choice and choice["project"] and not _AGENT.fullmatch(choice["project"]):
            current = _canonical_project(choice["project"])
        voluntary = choice or _VOLUNTARY_DETAIL.fullmatch(part.text) or _ENROLLED.match(part.text)
        if not voluntary:
            voluntary = any(item.voluntary or any(
                _VOLUNTARY_DETAIL.fullmatch(item.object[match.end():]) for match in _PROJECT.finditer(item.object)
            ) for item in graph.actions_for(part.id))
        if voluntary:
            choices.add(current)
        details = [part.text.removeprefix("也"), *(graph.text[group.content.start:group.content.end]
                   for group in part.groups if group.kind == "bracket")]
        if any(_EXIT.fullmatch(detail) for detail in details):
            without_payment = any(_EXIT_WITHOUT_PAYMENT.fullmatch(detail) for detail in details)
            if current:
                exits.add(current)
                if without_payment:
                    waived.add(current)
            else:
                leading_exit = True
                leading_waiver |= without_payment
    names = {label for part in related if (label := key_for(part, part.project))}
    if leading_exit and choices == {None} and len(names) == 1:
        choices = exits = names
        if leading_waiver:
            waived.update(names)
    elif leading_exit and len(choices) == 1 and None not in choices:
        exits.update(choices)
        if leading_waiver:
            waived.update(choices)
    if key not in choices & exits:
        return False
    if key in waived and action and _enrolled_payer(clause, action):
        return True
    if any(_forced_collection(graph, item, voluntary_agency=key in waived) for item in candidates):
        return False
    if action and any(item.mandatory or item.predicate == "要求" for item in (action, _chain_head(graph, action))):
        return bool(action.voluntary and action.exit)
    return True


def refusal_enforced(graph, clause, action):
    """拒缴后果自身常带否定，检查外围语境和实际执行的回绑。"""
    outer = _external_context(graph, clause)
    if outer in {Context.NEGATION, Context.GOVERNANCE, Context.REFUTATION} or _PROHIBITIVE_WRAPPER.match(clause.text):
        return False
    if action.polarity == Polarity.NEGATIVE and action.predicate in _PUNITIVE_CONSEQUENCES:
        return False
    return bool(action.consequence and action.conditions and
                action.binding not in {Binding.PROHIBITED, Binding.REJECTED, Binding.REFUTED, Binding.HISTORICAL})


def monetary_object(clause, action=None):
    """缴收动作需要金额或费用对象，金额细化须在当前分句。"""
    if action and _MONEY.search(action.object):
        return True
    text = _surface(clause)
    if action and action.predicate in _PAYMENT_DELIVERY:
        disposal = _PAYMENT_DISPOSAL.search(text, 0, action.span.start - clause.span.start)
        if disposal and _MONEY.search(disposal["object"]):
            return True
    if action and action.object:
        return bool(_AMOUNT.search(text[action.span.end - clause.span.start:]))
    return bool(_MONEY.search(text))


def referenced_charge(graph, clause):
    """省略宾语的缴交指令取紧邻前项的费用槽。"""
    if clause.previous is None or clause.connector:
        return False
    before = graph.clauses[clause.previous]
    return (monetary_object(before) or before.project is not None
            and _MONEY.search(graph.projects[before.project].label) is not None)


def implements_charge(graph, clause):
    if clause.previous is None:
        return False
    before = graph.clauses[clause.previous]
    return (before.project is not None and any(
                item.predicate in _FEES and item.predicate != "办理" for item in graph.actions_for(before.id))
            and any(item.predicate == "执行" for item in graph.actions_for(clause.id))
            and not wide_suppressed(graph, before))


def requests_payment_delivery(graph, action):
    prefix = graph.text[graph.clauses[action.clause].span.start:action.span.start].lstrip()
    return action.predicate in _PAYMENT_DELIVERY and prefix.startswith("请")


def _enrolled_payer(clause, action):
    subject = _ENROLLED.match(clause.text)
    if not subject or not action.mandatory or action.predicate not in _COLLECTING_VERBS:
        return False
    prefix = clause.text[subject.end():action.span.start - clause.span.start].strip()
    return prefix in _MANDATORY and action.local_polarity == Polarity.POSITIVE


def _forced_collection(graph, action, *, voluntary_agency=False):
    if action.predicate not in _COLLECTING_VERBS:
        return False
    return any(item.mandatory or item.predicate == "要求" or
               item.uniform and not (voluntary_agency and action.predicate == "代收")
               for item in (action, _chain_head(graph, action)))


def addressed_collection(action):
    """带收款方、收款对象及费用证据的直接收费，宽层核实。"""
    return (action.predicate in _COLLECTION and action.school_agent
            and action.local_polarity != Polarity.NEGATIVE and action.recipient
            and action.recipient.endswith(("学生", "新生", "同学", "同学们", "家长", "家庭"))
            and _MONEY.search(action.object) is not None)


def incidental_charge_object(text):
    """费用谓词后接规程、明细等时，取到的是费用元数据。"""
    return bool(_CHARGE_LABEL.search(text))


def committee_charge(graph, related, action=None):
    """家委会作为收款方、代办方或议事主体。"""
    if action and (action.agent in _COMMITTEES or action.recipient in _COMMITTEES):
        return True
    if action and action.predicate in _COLLECTION:
        clause = graph.clauses[action.clause]
        prefix = clause.text[:action.span.start - clause.span.start]
        if _COMMITTEE_DELEGATE.search(prefix):
            return True
    actors = [item for part in related for item in graph.actions_for(part.id)]
    mandates = any(_COMMITTEE_ROLE.match(part.text) for part in related)
    committee = (mandates or any(_COMMITTEE_ACTOR.match(part.text) for part in related)
                 or any(item.agent in _COMMITTEES or item.recipient in _COMMITTEES for item in actors))
    if action is None:
        return committee
    return (action.predicate in _FEES and _COMMITTEE_HANDOFF.search(action.object) is not None
            or committee and (action.predicate in {"代收", "收缴", "募集", "缴款", "摊派"}
            or (mandates or any(item.agent in _COMMITTEES and item.predicate == "决定" for item in actors))
            and (action.predicate in {"收取", "收"} or "代收" in action.object)
            or action.predicate == "上交" and any(item.agent in _COMMITTEES and item.predicate == "办理"
                                                for item in actors)))


def committee_discussion(graph, clause):
    return (_COMMITTEE_HEARING.fullmatch(clause.text) is not None and monetary_object(clause) or
            any(item.agent in _COMMITTEES and item.predicate in _DISCUSSION
               and re.search(r"(?:收取|收费)(?:标准|流程|情况)", item.object)
               for item in graph.actions_for(clause.id)))



@dataclass(frozen=True)
class IdentityRelation:
    clause: int
    names: tuple[str, ...]
    admission: Admission | None
    prefix_identity: bool = False


# 人名槽只负责划界。候选能否作姓名、分数是否达阈值仍由共享姓名模块判定。
_IDENTITY_PERSON = r"(?:某同学|[A-Za-z]同学|[\u3400-\u9fff]{2,4}?)"
_NAMES = _IDENTITY_PERSON + r"(?:、" + _IDENTITY_PERSON + r")*"
_PERSON_SLOT = r"(?P<names>" + _NAMES + r")"
_ORDINAL = r"[一二三四五六七八九十0-9]+"
_GRADE = r"(?:" + _ORDINAL + r"年级|[初高]" + _ORDINAL + r")"
_CLASS = r"(?:（" + _ORDINAL + r"）|" + _ORDINAL + r")班"
_CLASSROOM = rf"(?:(?:{_GRADE}(?:{_CLASS})?|{_CLASS})的?)?"
_PUPIL = _CLASSROOM + r"(?:学生)?" + _PERSON_SLOT + r"(?:同学)?"
_HEALTH = r"(?:慢性肾病|抑郁症|哮喘|肺炎|癫痫|糖尿病|自闭症|焦虑症)"
_STATUS = (r"(?:贫困家庭(?:子女|学生)|低保家庭(?:子女|学生|成员)?|资助对象|受助对象|"
           r"留守(?:儿童|学生)|(?:残疾|残障|随班就读)(?:学生|儿童)|孤儿|单亲家庭(?:成员|子女))")
_STATEMENT = (r"(?:(?:属于|系|是|被?认定为|登记为)" + _STATUS + r"|(?:患有|确诊为)" + _HEALTH
              + r"|享受助学金|被记过|被警告处分|被处分)")
_PREFIX_STATUS = r"(?:残疾|残障|贫困家庭|患病|留守|受助|随班就读)(?:学生|儿童|子女)"
_IDENTITY_PRECISE = tuple(map(re.compile, (
    _CLASSROOM + r"学生" + _PERSON_SLOT + r"(?:同学)?" + _STATEMENT,
    _CLASSROOM + _PERSON_SLOT + r"同学" + _STATEMENT,
    r"(?:不予)?免收" + _PREFIX_STATUS + _PERSON_SLOT + r"的(?:课后服务费|活动费|校服费)",
    r"(?:没有父母陪伴的)?" + _PREFIX_STATUS + _PERSON_SLOT
    + r"(?:由(?:祖父母|外祖父母|外婆|祖母|祖父)照料|需要特别照顾)",
)))
_IDENTITY_WIDE = tuple(map(re.compile, (
    _PUPIL + r"(?:疑似|可能)?" + _STATEMENT + r"(?:吗|呢|吧)?$",
    _PUPIL + r"(?:评定为" + _STATUS + r"|登记为(?:可能)?患病|自身患病|因" + _HEALTH + r"住院)",
    _PUPIL + r"为" + _STATUS + r"(?:$|(?:积极)?(?:募集|筹集))",
    _PUPIL + r"(?:个人档案|去年填报的登记类别).*?(?:资助对象|随班就读)",
    _PREFIX_STATUS + _PERSON_SLOT + r"(?:需要特别照顾|已到校|由(?:外婆|祖父母)照料)",
)))
_IDENTITY_SIGNAL = re.compile(_PREFIX_STATUS + "|" + _STATUS + "|" + _HEALTH + r"|助学金|患病|处分|记过|随班就读")
_PERSON_REFERENCE = re.compile(_PUPIL + r"[，,][^。；]*?本人(?:患有|确诊为)" + _HEALTH)
_CONTRAST_STATUS = re.compile(_PUPIL + r"(?:未|不曾)(?:被处分|被记过)但" + _STATEMENT)


_DISCIPLINE = r"(?:警告|严重警告|记过|记大过|留校察看|开除学籍)"
_DISEASE = r"(?:[\u3400-\u9fff]{1,9}(?:症|病|障碍)|" + _HEALTH + r")"
_ROSTER_ACTION = r"(?:已)?(?:列入|纳入)(?:[\u3400-\u9fff]{0,15}(?:名册|名单))|(?:已)?获得助学金"


@lru_cache(maxsize=2)
def _wide_identity_patterns(baseline_status):
    status = "(?:" + baseline_status + r"|贫困家庭|受助|留守|残疾|残障)"
    membership = status + r"(?:家庭)?(?:人员|学生|儿童|子女|成员|户)?"
    predicate = (r"(?:属于|系|是|登记为|认定为)" + membership
                 + r"|(?:被给予|受到|被)" + _DISCIPLINE + r"(?:处分)?"
                 + r"|(?:患有|确诊为)" + _DISEASE + r"|为" + _DISEASE + r"(?:儿童|学生)")
    signal = re.compile(_IDENTITY_SIGNAL.pattern + "|" + baseline_status + r"|处分|记大过|留校察看|患有|确诊为|障碍|症")
    roster = re.compile("(?:" + status + r"(?:家庭)?(?:学生|儿童|子女)|" + _PREFIX_STATUS
                        + r")名单(?:如下|为)?[：:]" + _PERSON_SLOT + r"$")
    return signal, roster, (re.compile(_PUPIL + "(?:" + predicate + r")(?:吗|呢)?$"),
            re.compile(status + r"(?:家庭)?的?" + _CLASSROOM + r"(?:学生|儿童)" + _PERSON_SLOT
                       + "(?:" + _ROSTER_ACTION + ")$"))


def identity_relations(graph, *, baseline_status="(?!)"):
    """直接关系须消费完整语句。名单继承、跨分句本人回指及不明外层只给关系证据。"""
    signal, roster, wide_patterns = _wide_identity_patterns(baseline_status)
    if not signal.search(graph.text):
        return
    sentences = defaultdict(list)
    for clause in graph.clauses:
        if clause.parent is None and not clause.table_header:
            sentences[clause.sentence, clause.table, clause.column].append(clause)
    for clauses in sentences.values():
        first, last = clauses[0], clauses[-1]
        value = graph.text[first.span.start:last.span.end]
        if not signal.search(value):
            continue
        exact = next((m for pattern in _IDENTITY_PRECISE if (m := pattern.fullmatch(value))), None)
        if exact:
            # 任何未消费的句首（例如列表、引述）、问句或表格均不授予直接陈述资格。
            line_start = graph.line_offsets[first.span.line - 1]
            clean_start = not graph.text[line_start:first.span.start].strip()
            admit = (clean_start and all(not (c.frames or c.malformed or c.question or c.table is not None
                                              or c.list_block is not None) for c in clauses))
            yield IdentityRelation(first.id, tuple(exact["names"].split("、")), Admission.MAIN if admit else None,
                                   exact.re in _IDENTITY_PRECISE[-2:])
            continue
        for m in (roster.search(value), _PERSON_REFERENCE.fullmatch(value), _CONTRAST_STATUS.fullmatch(value)):
            if m:
                yield IdentityRelation(first.id, tuple(m["names"].split("、")), None)
        for clause in clauses:
            for pattern in (*_IDENTITY_WIDE, *wide_patterns):
                for m in pattern.finditer(visible_evidence(clause)):
                    yield IdentityRelation(clause.id, tuple(m["names"].split("、")), None)


# 金额的物理行决定报告位置，依据只在自然段或当前数据行内有效。
_BASIS_AMOUNT = re.compile(r"(?:\d[\d,，]*(?:[.．]\d+)?|[零〇一二两三四五六七八九十百千万]+)\s*(?:元|块钱)")
_BASIS_PROJECT = re.compile(r"课后服务|校服|研学|实践费|伙食|午餐|餐费|校车|资料|材料|活动费|训练费|保险|班费|报名费|教辅")
_BASIS_ALIAS = {"伙食": "餐费", "午餐": "餐费"}
_BASIS_ACTION = re.compile(r"收取|收费(?!依据|管理|通知|办法|规定)|缴纳|交纳|收缴|缴齐|交齐|代收|上交|收(?=班费|材料费|资料费|\d)|购买|缴费")
_BASIS_STANDARD = re.compile(r"收费标准|收费金额|收费价格|缴费标准|费用标准")
_BASIS_HISTORY = re.compile(r"(?:已(?:经)?|累计|实际)(?:收取|收缴|缴纳|收费)|统计(?:累计)?收取")
_BASIS_PENDING = re.compile(r"【待(?:补|核实)[：:][^】]*收费依据[^】]*】|收费依据[：:]【待(?:补|核实)")
_BASIS_TITLE = re.compile(r"《([^》]+)》")
_BASIS_NUMBER = re.compile(r"[\u3400-\u9fff]{1,16}[〔［\[]\d{4}[〕］\]]\s*\d+\s*号")
_BASIS_AUTHORITY = r"(?:教育局|教育厅|教育部|发改委|发展改革委|物价局|物价部门|人民政府)"
_BASIS_APPROVED = re.compile(_BASIS_AUTHORITY + r"(?:已)?(?:批准|核定|批复)(?:的)?收费标准")
_BASIS_CITATION = re.compile(_BASIS_AUTHORITY + r"(?:(?:联合)?(?:印发|发布|制定)的?)?$")
_BASIS_NEGATED = re.compile(r"(?:尚未|未曾|没有|未|缺少|尚缺|并非)(?:获(?:得)?|取得|提供|见|经|按|有)?[^，。；：:\n]{0,18}$")
_LOCAL_CITATION = re.compile(r"(?:校委会|学校|教务处|校长办公会议?|班主任会议|教研组|家委会|班级集体)(?:内部)?(?:通过|批准|审定|拟定|发出|制定|核定|印发|发布)(?:的)?$")
_BASIS_DOCUMENT = re.compile(r"(?:收费|代收费|校服管理|服务性收费).*(?:意见|办法|细则|标准|通知|规定|规范|批复|目录)$")


def _basis_projects(value):
    known = {_BASIS_ALIAS.get(m[0], m[0]) for m in _BASIS_PROJECT.finditer(value)}
    if known:
        return known
    item = re.search(r"(?:收取|代收|缴纳|交纳|收缴)([\u3400-\u9fff]{1,12}?费)", value)
    return {item[1]} if item else set()


def _applicable_sources(text):
    """一份专用文件的文号与标题属于同一个依据，不另作普适依据。"""
    applicable = []
    for piece in re.split(r"[。；;\n，,]", text):
        titles = list(_BASIS_TITLE.finditer(piece))
        for title in titles:
            before = piece[:title.start()].rstrip()
            if (_LOCAL_CITATION.search(before) or _BASIS_NEGATED.search(before)
                    or re.match(r"(?:尚未|未)(?:获批|生效|批准)", piece[title.end():])):
                continue
            if _BASIS_DOCUMENT.search(title[1]) or (_BASIS_CITATION.search(before) and
                    _basis_projects(title[1]) and re.search(r"通知|办法|标准|意见", title[1])):
                applicable.append(set() if re.search("代收费|服务性收费", title[1]) else _basis_projects(title[1]))
        if not titles:
            for source in (*_BASIS_NUMBER.finditer(piece), *_BASIS_APPROVED.finditer(piece)):
                if not _BASIS_NEGATED.search(piece[:source.start()]) and not _BASIS_NEGATED.search(source[0]):
                    applicable.append(set())
    return applicable


@dataclass(frozen=True)
class UnsupportedAmount:
    line: int
    text: str


def table_heading(cells):
    return any(_ITEM_COLUMN.fullmatch(label) or _BASIS_STANDARD.fullmatch(label)
               or "姓名" in "".join(label.split()) or label in {"收费项目", "费用名称", "事项", "内容", "费用", "金额", "单价"} for label in cells)


def unsupported_amounts(graph, *, word_lines=()):
    if not _BASIS_AMOUNT.search(graph.text):
        return
    paragraphs = []
    paragraph = 0
    for start, end in zip(graph.line_offsets, graph.line_offsets[1:]):
        if not graph.text[start:end].strip():
            paragraph += 1
        paragraphs.append(paragraph)
    def block_key(clause):
        return (word_lines or paragraphs)[clause.span.line - 1], clause.table, clause.row

    # 只合并连续的同段分句，表内的文件不能落入表前后正文的依据范围。
    for (_, table, _), group in groupby((c for c in graph.clauses if c.parent is None), block_key):
        clauses = [c for c in group if not c.table_header]
        if not clauses:
            continue
        text = graph.text[clauses[0].span.start:clauses[-1].span.end]
        if not _BASIS_AMOUNT.search(text):
            continue
        sources = _applicable_sources(text)
        pending_lines = {c.span.line for c in clauses if _BASIS_PENDING.search(c.text)}
        if any(not keys for keys in sources):
            continue
        # 表头或同行的实收动作可解释另一列的金额；普通段落只借同句相邻的收费标准。
        by_sentence = defaultdict(list)
        for c in clauses:
            by_sentence[c.sentence].append(c)
        positions = {c.id: i for i, c in enumerate(clauses)}
        for sentence in by_sentence.values():
            active = []
            for c in sentence:
                raw = visible_evidence(c)
                clean = re.sub(r"[（(][^（）()]*(?:减免|免收|免缴)[^（）()]*[）)]", "", raw)
                if (_BASIS_ACTION.search(clean) and not _BASIS_HISTORY.search(clean)
                        and not wide_suppressed(graph, c) and not re.search(r"免收|退还|退回|退费|不收费", clean)):
                    active.append(c)
            for c in sentence:
                raw = visible_evidence(c)
                amount = _BASIS_AMOUNT.search(raw)
                if not amount or c.span.line in pending_lines or c.span.line + 1 in pending_lines:
                    continue
                if (_BASIS_HISTORY.search(raw) or re.search(r"退还|退回|退费|财政预算|财政拨付", raw)
                        or c.connector == "还" and c.previous is not None
                        and graph.clauses[c.previous].text.endswith("退")):
                    continue
                header = table is not None and (
                    _BASIS_STANDARD.fullmatch(c.column_header) or c.column_header in {"金额", "费用", "单价", "标准"}
                ) and any(s.column != c.column and (_ITEM_COLUMN.fullmatch(s.column_header)
                          or s.column_header == "费用") and s.text.strip() for s in clauses)
                related = [a for a in active if a is c or table is not None and a.project == c.project
                           or a.previous == c.id and _basis_projects(raw)
                           or c.previous == a.id and _BASIS_STANDARD.search(_BASIS_TITLE.sub("", a.text))]
                # 本句明确以“项目费＋每生／每月……金额”陈列单价。
                standard = re.search(r"费(?:每生|每人)(?:每月|每学期|每年)?\s*$", raw[:amount.start()])
                if not (header or related or standard):
                    continue
                projects = _basis_projects(_BASIS_TITLE.sub("", raw)) or set().union(
                    *(_basis_projects(_BASIS_TITLE.sub("", a.text)) for a in related))
                if table is not None and c.project is not None and not projects:
                    projects = _basis_projects(graph.projects[c.project].label)
                if sources and not projects and table is None:
                    # 光杆金额紧邻“按《文件》”或“依据：《文件》”时，项目来自直接修饰它的依据。
                    if re.fullmatch(r"(?:收费标准[：:]\s*)?(?:每[生人]\s*)?(?:收取|收费|缴纳)?\s*" +
                                    _BASIS_AMOUNT.pattern, raw):
                        idx = positions[c.id]
                        before = clauses[idx-1].text if idx else ""
                        after = "".join(s.text for s in clauses[idx+1:idx+3])
                        title = _BASIS_TITLE.search(before)
                        if (title and before.startswith(("按", "根据", "依据"))
                                and not before[title.end():].strip()
                                and clauses[idx - 1].separator in ("，", ",")):
                            projects = _basis_projects(title[1])
                        elif after.startswith("依据《") and all(
                                part is c or _BASIS_STANDARD.fullmatch(part.text) for part in sentence):
                            title = _BASIS_TITLE.search(after)
                            if title:
                                projects = _basis_projects(title[1])
                if projects and any(projects <= keys for keys in sources):
                    continue
                yield UnsupportedAmount(c.span.line, c.text)


def split_clauses(text: str, *, paragraph_starts: tuple[int, ...] = ()) -> ClauseGraph:
    """返回分句、引导框与表格项目，供独立检查切分。"""
    return _Builder(text).split(set(paragraph_starts))


def analyze(text: str, *, paragraph_starts: tuple[int, ...] = (), paragraph_offsets=()) -> ClauseGraph:
    """构建文档级分句图。Word 导入方可传真实段落的字符偏移；也接受 1 基物理行号。"""
    builder = _Builder(text)
    starts = set(paragraph_starts)
    starts.update(bisect_left(builder.offsets, offset) + 1 for offset in paragraph_offsets)
    graph = builder.split(starts)
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
