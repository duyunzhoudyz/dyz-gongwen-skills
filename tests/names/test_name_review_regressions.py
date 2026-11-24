# -*- coding: utf-8 -*-
"""实名专项复审原例与独立对抗样例，从三个行业引擎验证报出和遮蔽。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import NamedTuple

from tests.industry_corpus.test_industry_corpus import load_engine


class Case(NamedTuple):
    key: str
    industry: str
    body: str
    names: tuple[str, ...]
    levels: tuple[str, ...]
    doc_type: str | None = None
    visible: bool = False
    other_rule: str = ""
    excerpts: tuple[str, ...] = ()


def md(headers: str, *rows: str) -> str:
    return "\n".join((headers, "| " + " | ".join("---" for _ in headers.strip().strip("|").split("|")) + " |", *rows))


def soe(key: str, body: str, names: tuple[str, ...], *levels: str, **kwargs) -> Case:
    return Case(key, "soe", body, names, levels, kwargs.pop("doc_type", "纪要"), **kwargs)


UNIT_PRIORITY = (
    soe("B1.1", "决定免去张建国公司副总经理职务，对张建国给予记过处分。", ("张建国",), "P0"),
    soe("B1.2", "决定免去张建国公司总会计师职务，张建国被开除党籍。", ("张建国",), "P0"),
    soe("B1.3", "聘任李明集团总经济师。对李明给予警告处分。", ("李明",), "P0"),
    soe("B1.4", "王建国公司报销违规。\n拟安置人员：王建国、李娜。", ("王建国", "李娜"), "P1",
        excerpts=("拟安置人员：〔姓名1〕、〔姓名2〕。",)),
    soe("B1.5", "上海华建集团有限公司回函。\n对华建给予警告处分。", ("华建",), "P1"),
    soe("B1.6", "本项目专项整顿工作（以下简称“张伟”）已启动。\n对张伟给予警告处分。", ("张伟",), "P0"),
)
CELL_ITEMS = (
    Case("B2.1", "hospital", md("| 患者姓名 | 诊断 | 说明 |", "| 王秀英、李明 | 哮喘 | 治愈率100%，王秀英、李明均已出院 |"),
         ("王秀英", "李明"), ("P0", "P0"), other_rule="HOS-002", excerpts=("〔姓名1〕", "〔姓名2〕")),
    soe("B2.2", md("| 职工姓名 | 处分 | 说明 |", "| 王秀英、李明 | 警告 | 王秀英、李明先行开工 |"),
        ("王秀英", "李明"), "P0", "P0", other_rule="SOE-001", excerpts=("〔姓名1〕", "〔姓名2〕")),
    Case("B2.3", "k12", md("| 学生姓名 | 困难类型 |", "| 周梓涵（三年级2班） | 低保 |"), ("周梓涵",), ("P0",)),
    soe("B2.4", md("| 职工姓名 | 处分 |", "| 王秀英（副部长） | 警告 |"), ("王秀英",), "P0"),
    Case("B2.5a", "hospital", md("| 患者姓名 | 诊断 |", "| 王秀英（56岁，女） | 哮喘 |"), ("王秀英",), ("P0",)),
    Case("B2.5b", "hospital", md("| 患者姓名 | 诊断 |", "| **王秀英**（女） | 哮喘 |"), ("王秀英",), ("P0",)),
)
PLACEHOLDERS = (
    soe("B3.1", md("| 当事人 | 责任人 | 处分 |", "| 王明亮 | 王明 | 警告 |"),
        ("王明亮", "王明"), "P0", "P0", excerpts=("〔姓名1〕", "〔姓名2〕")),
    soe("B3.2", md("| 备注 | 当事人 | 处分 |", "| 无 | 王明亮 | 警告 |", "| 王明亮协助 | 王明 | 警告 |"),
        ("王明亮", "王明"), "P0", "P0", excerpts=("〔姓名1〕", "〔姓名2〕")),
)
MARKDOWN = (
    *(Case(f"M1.1{letter}", "hospital", md(header, "| 王秀英 | 哮喘 |"), ("王秀英",), ("P0",))
      for letter, header in zip("abcde", ("| 患者姓名： | 诊断 |", " | 姓名（实名） | 诊断 |", "| 【患者姓名】 | 诊断 |",
                                         "| **患者**姓名 | 诊断 |", "| ***患者姓名*** | 诊断 |"))),
    Case("M1.2", "hospital", md("| 编号 | 备注 |", "| 1 | 无 |") + "\n" + md("| 患者姓名 | 诊断 |", "| 王秀英 | 哮喘 |"),
         ("王秀英",), ("P0",)),
    Case("M1.3", "hospital", "序号 | 患者姓名 | 诊断\n--- | --- | ---\n | 王秀英 | 哮喘", ("王秀英",), ("P0",)),
)
PUBLIC = (
    Case("M2.1", "hospital", md("| 序号 | 投诉问题 | 责任人 | 整改时限 |", "| 1 | 导诊指引不清 | 王秀英 | 12月底 |"),
         ("王秀英",), (), visible=True),
    soe("M2.2", md("| 序号 | 违纪整改任务 | 责任人 | 完成时限 |", "| 1 | 开展警示教育 | 王秀英 | 12月底 |"),
        ("王秀英",), visible=True),
    *(Case(f"M2.3{letter}.{domain}", domain, md(header, row), ("王秀英",), (), "纪要" if domain == "soe" else None, True)
      for letter, header, row in (("a", "| 姓名 | 奖项 |", "| 王秀英 | 优秀奖 |"),
                                  ("b", "| 值班日期 | 姓名 | 值班领导 |", "| 周一 | 王秀英 | 张主任 |"),
                                  ("c", "| 姓名 | 授课内容 | 时间 |", "| 王秀英 | 国学 | 周一 |"))
      for domain in ("hospital", "soe", "k12")),
    Case("M2.4", "hospital", md("| 姓名 | 诊断 |", "| 全员 | 观察 |"), ("全员",), (), visible=True),
)
PERSON_ACTION = (
    soe("M3.1a", "经董事会研究，对曹宇航给予开除处分。", ("曹宇航",), "P0"),
    soe("M3.1b", "对李钢给予党内警告处分。", ("李钢",), "P0"),
    soe("M3.1c", "对张建给予留党察看一年处分。", ("张建",), "P0"),
    soe("M3.1d", "对李钢分别给予开除党籍处分。", ("李钢",), "P0"),
    soe("M3.2a", "对李钢（厂长）给予警告处分。", ("李钢",), "P0"),
    soe("M3.2b", "对李钢（总会计师）给予警告处分。", ("李钢",), "P0"),
    soe("M3.3a", "拟提拔人选：副书记李钢、王建国。", ("李钢", "王建国"), "P1",
        excerpts=("拟提拔人选：副书记〔姓名1〕、〔姓名2〕。",)),
    soe("M3.3b", "拟提拔人选：总工程师李钢。", ("李钢",), "P1"),
    soe("M3.4", "东岭冶炼有限责任公司（以下简称“唐钢”）。\n\n" + md("| 处分对象 | 处分 |", "| 唐钢 | 警告 |"),
        ("唐钢",), visible=True),
)
SCOPE_AND_DEDUP = (
    Case("M4.1", "k12", md("| 学生姓名 | 困难类型 |", "| 王秀英同学 | 低保 |"), ("王秀英",), ("P0",),
         excerpts=("〔姓名1〕",)),
    soe("M4.2", "拟安置人员：唐钢、王建国。", ("唐钢", "王建国"), "P1",
        excerpts=("拟安置人员：〔姓名1〕、〔姓名2〕。",)),
    soe("M4.3", md("| 责任人 | 工作事项 |", "| 王秀英 | 完善制度 |"), ("王秀英",), doc_type="合规报告"),
    soe("M4.3a", md("| 责任人 | 工作事项 |", "| 王秀英 | 完善制度 |"), ("王秀英",), doc_type="改革台账"),
    soe("M4.3b", md("| 责任人 | 工作事项 |", "| 王秀英 | 完善制度 |"), ("王秀英",), doc_type="ESG报告"),
)

ADVERSARIAL_PEOPLE = (
    soe("人01", "东岭钢铁集团有限公司（以下简称“李钢”）。\n对李钢给予党内严重警告处分。", ("李钢",), "P0"),
    soe("人02", "李钢集团发布通告。\n李钢、王铁分别受到政务记大过处分。", ("李钢", "王铁"), "P0"),
    soe("人03", "由周铁公司内部核查。\n对周铁给予撤职处分。", ("周铁",), "P0"),
    soe("人04", "关于撤销赵航集团副董事长职务的决定。\n对赵航给予警告处分。", ("赵航",), "P1"),
    soe("人05", "华东王铁公司已回函。\n对王铁给予政务记过处分。", ("王铁",), "P0"),
    soe("人06", "何建集团已回函。\n何建（工号77）受到警告处分。", ("何建",), "P0"),
    soe("人07", "对周航进行了诫勉谈话。\n周航公司回函。", ("周航",), "P0"),
    soe("人08", "陈建股份有限公司已回函。\n拟提拔人选：副董事长陈建、魏文静。", ("陈建", "魏文静"), "P1"),
    soe("人09", "有关制度文件（以下简称‘张伟’）已经印发。\n张伟被免职。", ("张伟",), "P0"),
    soe("人10", "南方建设有限公司（以下简称“赵铁”）。\n" + md("| 处分对象 | 处分 |", "| 赵铁 | 政务记过 |"),
        ("赵铁",), "P0"),
    soe("人11", "西岭财务有限公司（以下简称“孙航”）。\n对王铁、孙航分别给予撤销党内职务处分。", ("王铁", "孙航"), "P0"),
    soe("人12", "方建集团发布通告。\n对方建同志给予警告处分。\n拟安置人员：方建、郑文俊。", ("方建", "郑文俊"), "P0", "P1"),
)
ADVERSARIAL_TABLES = (
    Case("表01", "hospital", md("| 患者姓名 | 诊断 | 说明 |",
                             "| **刘玉兰（病区A，女）**、陈志明（已出院） | 观察 | 治愈率100%，刘玉兰、陈志明均已离院 |"),
         ("刘玉兰", "陈志明"), ("P0", "P0"), other_rule="HOS-002"),
    Case("表02", "hospital", "编号 | 《患者姓名》 | 床号\n:--- | --- | ---:\n | 陈爱玲(预住院) | 3床\n陈爱玲治愈率100%。",
         ("陈爱玲",), ("P0",), other_rule="HOS-002"),
    Case("表03", "hospital", md("| 编号 | 说明 |", "| 1 | 无 |") + "\n"
         + md("| **病人**姓名（实名）： | 检查结果 |", "| 余小敏 | 复查 |") + "\n余小敏治愈率100%。",
         ("余小敏",), ("P0",), other_rule="HOS-002"),
    Case("表04", "k12", md("| 学生姓名 | 心理 | 备注 |", "| 蔡雨薇（申请中） | 观察 | 公布考试成绩排名，蔡雨薇第一 |"),
         ("蔡雨薇",), ("P0",), other_rule="K12-G01"),
    Case("表05", "k12", md("| 学生姓名 | 困难类型 |", "| **李秋瑶**及周伟 | 单亲 |") + "\n公布考试成绩排名，李秋瑶、周伟在列。",
         ("李秋瑶", "周伟"), ("P0",), other_rule="K12-G01"),
    soe("表06", md("| 职工姓名 | 处分 | 说明 |", "| 王明亮、王明 | 记过 | 王明亮、王明均已先行开工 |"),
        ("王明亮", "王明"), "P0", "P0", other_rule="SOE-001", excerpts=("〔姓名1〕", "〔姓名2〕")),
    soe("表07", md("| 职工姓名 | 工作事项 |", "| 徐明佳（已调离） | 协调采购 |") + "\n徐明佳所在项目先行开工。",
        ("徐明佳",), doc_type="合规报告", other_rule="SOE-001"),
    Case("表08", "k12", md("| 【学生姓名】 | 病史 |", "| 金一诺(已转班)、肖博扬同学 | 哮喘 |")
         + "\n金一诺、肖博扬被公布考试成绩排名。", ("金一诺", "肖博扬"), ("P0",), other_rule="K12-G01"),
    Case("表09", "hospital", md("| 姓名 | 住院号 |", "| _郑秀英_（复诊）和赵小雨 | 123 |")
         + "\n郑秀英和赵小雨治愈率100%。", ("郑秀英", "赵小雨"), ("P0", "P0"), other_rule="HOS-002"),
    soe("表10", "华北沈航股份有限公司已回函。\n" + md("| 处分对象 | 处分 | 备注 |",
        "| ***沈航***（已离岗） | 警告 | 沈航先行开工 |"), ("沈航",), "P0", other_rule="SOE-001"),
    Case("表11", "k12", md("| 学生姓名 | 说明 |", "| 钟可欣 | 低保家庭学生郑雨桐近期情绪低落 |")
         + "\n公布考试成绩排名，钟可欣、郑雨桐在列。", ("钟可欣", "郑雨桐"), ("P0",), other_rule="K12-G01"),
    Case("表12", "hospital", md("| 患儿姓名 | 诊断 | 说明 |", "| 欧阳明月（转科,21床）与**陈丽** | 观察 | 治愈率100%，欧阳明月与陈丽均观察 |"),
         ("欧阳明月", "陈丽"), ("P0", "P0"), other_rule="HOS-002"),
)

CASE_GROUPS = {
    "unit_priority": UNIT_PRIORITY, "cell_items_and_cross_rule_masking": CELL_ITEMS, "distinct_placeholders": PLACEHOLDERS,
    "markdown_boundaries": MARKDOWN, "public_and_duty_tables": PUBLIC, "natural_person_actions_and_titles": PERSON_ACTION,
    "rule_scope_and_deduplication": SCOPE_AND_DEDUP, "adversarial_people": ADVERSARIAL_PEOPLE,
    "adversarial_tables": ADVERSARIAL_TABLES,
}
NAME_RULES = {"hospital": {"HOS-031"}, "k12": {"K12-G04"}, "soe": {"SOE-022", "SOE-023"}}


def run_case(case: Case, path: Path):
    path.write_text(case.body, encoding="utf-8")
    engine = load_engine(case.industry)
    if case.industry == "k12":
        report = engine.check_general(path)
        screen = engine.render_check_text(report)
    else:
        report = engine.check_file(path, case.doc_type)
        screen = engine.render_text(report)
    return report, screen


class NameReviewRegressionTest(unittest.TestCase):
    def assert_cases(self, group: str) -> None:
        for case in CASE_GROUPS[group]:
            with self.subTest(case=case.key, text=case.body), tempfile.TemporaryDirectory() as work:
                path = Path(work) / ("及".join(case.names) + "附表.md")
                report, screen = run_case(case, path)
                issues = report["issues"]
                rows = [i for i in issues if i["id"] in NAME_RULES[case.industry]]
                self.assertEqual(tuple(i["level"] for i in rows), case.levels, rows)
                if case.excerpts:
                    self.assertEqual(tuple(i["excerpt"] for i in rows), case.excerpts)
                if case.other_rule:
                    refs = [i for i in issues if i["id"] == case.other_rule]
                    self.assertTrue(refs, issues)
                    self.assertTrue(any("〔姓名" in (i.get("context", "") + i["excerpt"]) for i in refs), refs)
                if case.visible:
                    self.assertEqual(report["file"], path.name)
                else:
                    for name in case.names:
                        self.assertNotIn(name, json.dumps(report, ensure_ascii=False))
                        self.assertNotIn(name, screen)
                    self.assertIn("〔姓名", report["file"])
                if case.key in ("B1.5", "M4.2"):
                    self.assertIn("可能是单位简称，请人工确认", rows[0]["message"])
                if (case.key.startswith("M3.") and case.levels) or case.key in ("人02", "人12"):
                    self.assertTrue(all("可能是单位简称" not in row["message"] for row in rows), rows)

    def test_unit_priority(self) -> None:
        self.assert_cases("unit_priority")

    def test_cell_items_and_cross_rule_masking(self) -> None:
        self.assert_cases("cell_items_and_cross_rule_masking")

    def test_distinct_placeholders(self) -> None:
        self.assert_cases("distinct_placeholders")

    def test_markdown_boundaries(self) -> None:
        self.assert_cases("markdown_boundaries")

    def test_public_and_duty_tables(self) -> None:
        self.assert_cases("public_and_duty_tables")

    def test_natural_person_actions_and_titles(self) -> None:
        self.assert_cases("natural_person_actions_and_titles")

    def test_rule_scope_and_deduplication(self) -> None:
        self.assert_cases("rule_scope_and_deduplication")

    def test_adversarial_people(self) -> None:
        self.assert_cases("adversarial_people")

    def test_adversarial_tables(self) -> None:
        self.assert_cases("adversarial_tables")
