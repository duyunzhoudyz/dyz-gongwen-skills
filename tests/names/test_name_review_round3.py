"""第三轮评审的复现、等价补测及独立对抗样例。"""
import tempfile
import unittest
from pathlib import Path

from tests.industry_corpus.test_industry_corpus import load_engine
from tests.names.masking import check_masked_outputs
from tests.names.test_name_review_regressions import Case, NAME_RULES, md, soe

ALIAS = "东岭钢铁有限责任公司（以下简称“唐钢”）。\n"
DEFINED = "文内已定义为单位简称，如确指单位可忽略"
POSSIBLE = "可能是单位简称，请人工确认"
UNKNOWN = "姓名列内容未能识别，请人工核对"


def discipline(key, sentence, level="P1", *, alias=ALIAS):
    return soe(key, alias + sentence, ("唐钢",), level)


def cell(key, domain, value, names, *levels, echo=None):
    label, kind, detail, trigger = {
        "hospital": ("患者姓名", "诊断", "哮喘", "治愈率100%，"),
        "soe": ("职工姓名", "处分", "警告", "先行开工"),
        "k12": ("学生姓名", "困难类型", "低保", "公布考试成绩排名，"),
    }[domain]
    body = md(f"| {label} | {kind} | 说明 |", f"| {value} | {detail} | {echo or trigger + '、'.join(names)} |")
    return Case(key, domain, body, names, levels, "纪要" if domain == "soe" else None)


def alias_row(key, header, row):
    return soe(key, ALIAS + "\n" + md(header, row), ("唐钢",), "P0")


REVIEW = (
    alias_row("A01", "| 拟任人选 | 拟任职务 | 说明 |", "| 唐钢 | 副总工程师 | 唐钢项目先行开工 |"),
    alias_row("A02", "| 处分对象 | 处分 |", "| 唐钢 | 记过 |"),
    alias_row("A03", "| 当事人 | 违纪事实 | 处分 |", "| 唐钢 | 违规报销 | 降级 |"),
    *(discipline(k, f"对唐钢{action}，唐钢项目先行开工。", "P0") for k, action in (
        ("A04", "给予记过处分"), ("A05", "给予记大过处分"), ("A06", "进行诫勉"))),
    *(soe(k, ALIAS + f"拟安置人员：唐钢（{note}）、王建国。", ("唐钢", "王建国"), "P1")
      for k, note in (("A07", "原财务部主任，已退休"), ("A08", "原财务科科长，党龄20年"),
                      ("A09", "身份证号370102198001011234"))),
    soe("A11", ALIAS + "撤销唐钢党内职务。\n对唐钢给予警告处分。", ("唐钢",), "P0", "P1"),
    alias_row("A12", "| 责任人 | 违纪事实 | 处分 |", "| 唐钢 | 违规报销 | 记过 |"),
    *(discipline(k, line + "\n对唐钢给予警告处分。", alias=alias) for k, line, alias in (
        ("A13a", "唐钢职工代表大会顺利召开。", ALIAS), ("A13b", "唐钢董事长出席会议。", ALIAS),
        ("A13c", "唐钢经理部来函。", ALIAS), ("A13d", "唐钢负责人来函说明情况。", ALIAS),
        ("A13e", "唐钢职工代表大会顺利召开。", ""), ("A13_ganbu", "唐钢干部大会传达了集团精神。", ALIAS),
        ("A13_zhuguan", "唐钢主管部门已审核同意。", ALIAS))),
    *(soe(k, f"{full}（以下简称“张伟”）。\n对张伟给予警告处分。", ("张伟",), level)
      for k, full, level in (("A14a", "关于华东有限公司的整改方案", "P0"), ("A14b", "某公司", "P0"),
                             ("A14c", "华东有限公司项目部", "P0"), ("A14d", "第一医院", "P1"))),
    cell("B01", "hospital", "王和平、王秀英", ("王和平", "王秀英"), "P0", "P0", echo="治愈率100%，王和平已出院，王秀英复查"),
    cell("B02", "soe", "李与同、王秀英", ("李与同", "王秀英"), "P0", "P0", echo="李与同先行开工"),
    cell("B03", "k12", "张及第、周梓涵", ("张及第", "周梓涵"), "P0", echo="公布考试成绩排名，张及第第一"),
    cell("B05", "soe", "分公司财务部王秀英、李明", ("王秀英", "李明"), "P0", "P0", echo="王秀英先行开工"),
    *(cell(k, "hospital", value, ("王秀英", "李明"), "P0", "P0", echo="治愈率100%，王秀英已出院")
      for k, value in (("B07", "[王秀英](https://a.cn)、李明"), ("B08", "【王秀英】、李明"))),
    cell("B09", "hospital", "王秀英、第三车间李明", ("王秀英", "第三车间李明", "李明"), "P0", "P1", echo="治愈率100%，李明已出院"),
    *(cell("复现" + name, "hospital", name, (name,), "P0", echo=f"治愈率100%，{name}已出院")
      for name in ("陈兴和", "王建与", "王和平", "周和平")),
    cell("复现和姓", "hospital", "王秀英、和建国", ("王秀英", "和建国"), "P0", "P0"),
    Case("B14", "comments", md("| 学生姓名 | 评语 |", "| 王和平 | 需要继续加油，上课听讲认真，按时完成各项作业，与同学友好相处，积极参加集体活动，愿新学期再接再厉取得更好成绩。 |"), ("王和平",), ()),
    soe("D16", md("| 序号 | 整改任务 | 整改责任人姓名 | 完成时限 |", "| 1 | 完善制度 | 王秀英 | 12月底 |"), ("王秀英",), visible=True),
    Case("D17", "k12", md("| 值班日期 | 值班人员姓名 | 值班领导 |", "| 周一 | 王秀英 | 李明 |"), ("王秀英",), (), visible=True),
)
MISSING_EQUIVALENTS = (
    discipline("等价出生年", "对唐钢（1980年生，拟退休）给予警告处分。", "P0"),
    cell("等价末字和", "soe", "吴正和、李明", ("吴正和", "李明"), "P0", "P0"),
    cell("等价三级单位", "hospital", "总公司分公司审计部陈敏", ("陈敏",), "P0"),
    cell("等价括号", "k12", "（吴雨桐）", ("吴雨桐",), "P0"),
    cell("等价残段", "soe", "执行窗口刘伟、陈敏", ("执行窗口刘伟", "刘伟", "陈敏"), "P0", "P1"),
    cell("等价链接", "hospital", "[周思和](relative)、李明", ("周思和", "李明"), "P0", "P0"),
    cell("等价首字和", "k12", "和安宁与陈敏", ("和安宁", "陈敏"), "P0"),
)
EMPTY_VALUES = ("王某", "张某某", "某同志", "——", "--", "N/A", "见附件", "另附", "略", "（无）", "待补充",
                "共5人", "合计3人", "五年级（2）班", "高一（3）班", "〔姓名1〕", "宣传部")
M1 = tuple(Case("占位" + val, "hospital", md("| 患者姓名 | 诊断 |", f"| {val} | 哮喘 |"), (), ()) for val in EMPTY_VALUES)

# 同一词在相邻两句进入两个框架，两次证据相反。逐次定级也覆盖尚未出现过的定义/称呼与括注组合。
PERSON_CASES = tuple(soe(f"同句{i:02}", f"海山检测中心（以下简称“{name}”）。\n"
                         + f"对{name}{note}给予警告处分。对{name}给予警告处分。", (name,), "P0", "P1")
                     for i, (name, note) in enumerate((
                         ("陈航", "先生"), ("李建", "女士"), ("吴铁", "（1985年生）"), ("张华", "（出生于1980年）"),
                         ("卢钢", "（党龄二十年）"), ("赵航", "（已离休，手续齐）"), ("宋华", "（工号 A-9，待归档）"),
                         ("孙铁", "（身份证号已复核）"), ("何钢", "（担任科长，借调中）"), ("王建", "（性别：女）"),
                         ("钱华", "（年龄四十二岁）"), ("陆建", "（已退休，仍受邀）"), ("马华", "（技改组工程师，返聘）"),
                         ("唐铁", "同志"), ("周建", "同学")), 1))

# 已知姓名与不同长度的未知字段同格，跨行、跨文件名与规则摘录追踪整段和重叠姓氏后缀。
RESIDUES = ("稽核窗口王李明", "驻点联络陈马宁", "北岸工区吴周平", "二号泵房林方敏", "机修工段韩金雨",
            "春检专席郑何君", "临时席位苏秦安", "见习岗程胡佳", "北门岗刘夏阳", "夜间席余江云",
            "西侧通道许安琪", "资料窗口侯杨柳", "青区临岗姚沈宁", "西库外勤梁高杰", "驻外专岗徐潘悦")
TABLE_CASES = tuple(cell(f"残段{i:02}", domain, f"{residue}、陈丽", ("陈丽", residue, residue[-3:], residue[-2:]),
                         "P0", "P1") for i, (residue, domain) in enumerate(zip(RESIDUES, ("hospital", "soe", "k12") * 5), 1))
GROUPS = (REVIEW, MISSING_EQUIVALENTS, M1, PERSON_CASES, TABLE_CASES)


def evaluate(case, directory, *, verify=True):
    domain = "k12" if case.industry == "comments" else case.industry
    engine = load_engine(domain)
    filename = ("王和平评语" if case.industry == "comments" else "及".join(case.names) or "附表") + ".md"
    if case in REVIEW and case.names and case.industry != "comments":
        name = "李明" if case.key == "B09" else "和建国" if case.key == "复现和姓" else case.names[0]
        filename = name + ".md"
    path = Path(directory) / filename
    path.write_text(case.body, encoding="utf-8")
    if domain == "k12":
        gn = engine.shared_names()[0]
        check = engine.check_comments if case.industry == "comments" else engine.check_general
        render = engine.render_check_text
    else:
        gn = engine.shared_kit().names if domain == "hospital" else engine._shared()[0]
        check = lambda p: engine.check_file(p, case.doc_type)
        render = engine.render_text

    def run():
        report = check(path)
        return report, render(report)

    report, screen = check_masked_outputs(gn, run, expected_names=() if case.visible else case.names) if verify else run()
    issues = [i for i in report["issues"] if i["id"] in NAME_RULES[domain]]
    return report, issues, screen


class RoundThreeTest(unittest.TestCase):
    def check_cases(self, cases):
        for case in cases:
            with self.subTest(case=case.key), tempfile.TemporaryDirectory() as tmp:
                report, issues, screen = evaluate(case, tmp)
                self.assertCountEqual([i["level"] for i in issues], case.levels)
                if case.visible:
                    self.assertIn(case.names[0], report["file"])
                if case in M1:
                    self.assertNotIn("〔姓名", report["file"])
                    self.assertFalse(issues)
                    gn, lex = load_engine("hospital").shared_kit().names, load_engine("hospital").shared_kit().lexicon
                    self.assertFalse(gn.find_table_names(case.body.splitlines(), lex, "hospital"))
                if case in TABLE_CASES or case.key in ("B09", "等价残段"):
                    self.assertEqual([i["message"] for i in issues if i["level"] == "P1"], [UNKNOWN])
                if case.key.startswith("A13") or case.key in ("A11", "A14d") or case in PERSON_CASES:
                    self.assertIn(POSSIBLE if case.key == "A13e" else DEFINED, [i["message"] for i in issues])
                if case.industry == "comments":
                    self.assertIn("〔姓名1〕", report["entries"][0]["label"])
                    self.assertIn("〔姓名1〕", report["file"])

    def test_closed_personal_actions(self):
        personal = ("开除党籍", "留党察看", "党内警告", "党内严重警告", "撤销党内职务", "开除公职", "开除", "记过",
                    "记大过", "降级", "撤职", "免职", "诫勉", "诫勉谈话", "停职检查", "移送司法机关")
        shared = ("警告", "通报批评", "罚款", "责令整改", "约谈", "问责", "处分", "追责", "开除出供应商名录")
        self.assertEqual(load_engine("soe")._shared()[2].personal_actions, frozenset(personal))
        for action in personal + shared:
            with self.subTest(action=action), tempfile.TemporaryDirectory() as tmp:
                case = discipline(action, f"对唐钢予以{action}。")
                if action in shared and action not in ("警告", "开除出供应商名录"):
                    _, issues, _ = evaluate(case._replace(names=()), tmp)
                    self.assertEqual(issues, [])
                    continue
                _, issues, _ = evaluate(case, tmp)
                self.assertEqual([i["level"] for i in issues], ["P0" if action in personal else "P1"])
                if action in shared:
                    self.assertEqual(issues[0]["message"], DEFINED)

    def test_format_boundaries_and_defined_common_words(self):
        self.check_cases((
            cell("跨标记连词", "hospital", "【王秀英】和李明", ("王秀英", "李明"), "P0", "P0"),
            cell("跨括注连词", "soe", "王秀英（女）和陈敏", ("王秀英", "陈敏"), "P0", "P0"),
            cell("多前缀后连词", "hospital", "财务部经理王秀英和李明", ("王秀英", "李明"), "P0", "P0"),
            cell("姓名与部门", "soe", "王秀英、宣传部", ("王秀英",), "P0"),
            soe("同形普通词", "河西研究所（以下简称“刘海”）。\\n拟安置人员：刘海。", ("刘海",), "P1"),
            discipline("机构括注", "对唐钢（经理部意见）给予警告处分。"),
        ))

    def test_review(self): self.check_cases(REVIEW)
    def test_equivalents(self): self.check_cases(MISSING_EQUIVALENTS)
    def test_placeholders(self): self.check_cases(M1)
    def test_local_evidence(self): self.check_cases(PERSON_CASES)
    def test_residuals(self): self.check_cases(TABLE_CASES)
