# -*- coding: utf-8 -*-
"""skills/gongwen-soe/scripts/soe_check.py 的单元测试。

运行：python -m unittest discover -s tests/soe -t .
必错标本和必过标本在 tests/soe/specimens/ 下。
"""
from __future__ import annotations

import datetime as dt
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "skills" / "gongwen-soe"
SCRIPTS_DIR = SKILL_DIR / "scripts"
SPECIMENS = Path(__file__).resolve().parent / "specimens"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import soe_check as sc  # noqa: E402

try:
    import docx  # type: ignore  # noqa: F401
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

AS_OF = dt.date(2026, 9, 30)


def ids_of(result) -> list:
    return [issue["id"] for issue in result["issues"]]


def serious(result) -> list:
    return [issue for issue in result["issues"] if issue["level"] in ("P0", "P1")]


class SoeCheckBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.ruleset = sc.load_rules()

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="soe_check_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, text: str, doc_type=None, external: bool = False):
        return sc.check_text(text, doc_type, external, ruleset=self.ruleset, as_of=AS_OF)

    def check_specimen(self, name: str, doc_type: str, external: bool = False):
        path = next(SPECIMENS.glob(name + ".*"))
        return sc.check_file(path, doc_type, external, ruleset=self.ruleset, as_of=AS_OF)

    def run_main(self, *args: str):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sc.main(list(args))
        return code, out.getvalue(), err.getvalue()


class RuleFileTest(SoeCheckBase):
    """规则文件本身的完整性，以及每条正则规则的命中、不命中例句。"""

    def test_rules_load(self) -> None:
        # 28 条旧规则 + SOE-029（拆分规避集体决策）
        self.assertEqual(len(self.ruleset.rules), 29)
        self.assertEqual(len(self.ruleset.procedural), 11)
        self.assertEqual(set(self.ruleset.procedural), set(sc.PROCEDURAL_IDS))
        self.assertIn("改革台账", self.ruleset.types)
        self.assertIn("ESG报告", self.ruleset.external_types)

    def test_every_rule_has_examples(self) -> None:
        for rule in self.ruleset.rules:
            with self.subTest(rule=rule.id):
                self.assertTrue(rule.hit_examples, "缺少必中例句")
                self.assertTrue(rule.miss_examples, "缺少必不中例句")
                self.assertTrue(rule.basis)

    def _type_for(self, rule) -> str:
        if rule.types:
            return rule.types[0]
        # SOE-001 的正则不限文书类型，但“已执行 + 提请”的组合判定只在 procedure_inversion.types 里生效：
        # 它的例句（含组合判定的 P0/P1 分级例句）要按组合判定适用的文书类型来跑
        inversion = self.ruleset.inversion or {}
        if rule.id == inversion.get("rule_id") and inversion.get("types"):
            return inversion["types"][0]
        return None

    def test_hit_examples(self) -> None:
        for rule in self.ruleset.rules:
            for example in rule.hit_examples:
                with self.subTest(rule=rule.id, example=example):
                    result = self.check(example, self._type_for(rule), external=rule.external_only)
                    self.assertIn(rule.id, ids_of(result))

    def test_miss_examples(self) -> None:
        for rule in self.ruleset.rules:
            for example in rule.miss_examples:
                with self.subTest(rule=rule.id, example=example):
                    result = self.check(example, self._type_for(rule), external=rule.external_only)
                    self.assertNotIn(rule.id, ids_of(result))

    def test_level_examples(self) -> None:
        """同一条规则按情形分级的例句（程序倒置的 P0/P1、低置信姓名的 P1）。"""
        count = 0
        for rule in self.ruleset.rules:
            for item in rule.level_examples:
                count += 1
                with self.subTest(rule=rule.id, example=item["text"]):
                    result = self.check(item["text"], self._type_for(rule), external=rule.external_only)
                    levels = [i["level"] for i in result["issues"] if i["id"] == rule.id]
                    self.assertTrue(levels, "没有命中")
                    self.assertEqual(min(levels), item["level"])
        self.assertGreaterEqual(count, 8)

    def test_name_rules_use_detector(self) -> None:
        rules = {r.id: r for r in self.ruleset.rules}
        for rid in ("SOE-022", "SOE-023"):
            with self.subTest(rule=rid):
                self.assertEqual(rules[rid].detector, "names")
                self.assertTrue(rules[rid].anchors)
                self.assertIsNone(rules[rid].regex, "旧的姓氏字符集正则已删除")
                self.assertIsNone(rules[rid].exempt_match, "SOE-022 内嵌的 exempt_match 大词表已删除")
        self.assertEqual(rules["SOE-022"].low_level, "P1")
        self.assertEqual(rules["SOE-022"].level, "P0")
        self.assertEqual(rules["SOE-023"].level, "P1")
        self.assertTrue(any(a.suffix for a in rules["SOE-022"].anchors), "SOE_FRAME_2 必须是 suffix 型")

    def test_bad_rule_file(self) -> None:
        bad = self.tmp / "rules.json"
        bad.write_text("{not json", encoding="utf-8")
        with self.assertRaises(sc.InputError):
            sc.load_rules(bad)
        bad.write_text(json.dumps({"types": ["议题材料"], "rules": [
            {"id": "X-1", "category": "c", "gate": "g", "level": "P9", "message": "m", "basis": "b", "pattern": "a"}
        ]}, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(sc.InputError):
            sc.load_rules(bad)


class SpecimenTest(SoeCheckBase):
    """必错标本必须报出预期问题；必过标本不得有 P0、P1。"""

    # 国企线接入共享模块后，按实跑核对：各必错标本的 id 集合没有变化，也没有新增 SOE-029（标本里没有“拆分后分别报批”的写法）
    CASES = (
        ("议题材料", "议题材料", False, {"SOE-001", "SOE-003", "SOE-004", "SOE-008", "SOE-024", "SOE-101", "SOE-102", "SOE-107"}),
        ("议题材料-职工权益", "议题材料", False, {"SOE-111"}),
        ("董事会决议", "决议", False, {"SOE-104"}),
        ("董事会决议-票数写法", "决议", False, {"SOE-104"}),
        ("总经理办公会纪要", "纪要", False, {"SOE-007", "SOE-023", "SOE-108", "SOE-109"}),
        ("ESG报告", "ESG报告", True, {"SOE-008", "SOE-009", "SOE-010", "SOE-011", "SOE-012", "SOE-013",
                                     "SOE-027", "SOE-106", "SOE-107"}),
        ("融合材料", "融合材料", False, {"SOE-016"}),
        ("经营分析", "经营分析", False, {"SOE-014", "SOE-015", "SOE-021", "SOE-107"}),
        ("合规报告", "合规报告", False, {"SOE-005", "SOE-010", "SOE-022", "SOE-026"}),
        ("改革台账", "改革台账", False, {"SOE-105"}),
    )

    def test_must_fail(self) -> None:
        for name, doc_type, external, expected in self.CASES:
            with self.subTest(specimen=name):
                result = self.check_specimen("必错-" + name, doc_type, external)
                self.assertTrue(expected.issubset(set(ids_of(result))),
                                f"缺少：{expected - set(ids_of(result))}")
                self.assertTrue(serious(result) or result["summary"]["P2"], "必错标本没有报出问题")

    def test_must_pass(self) -> None:
        for name, doc_type, external, _expected in self.CASES:
            with self.subTest(specimen=name):
                result = self.check_specimen("必过-" + name, doc_type, external)
                self.assertEqual(serious(result), [], json.dumps(result["issues"], ensure_ascii=False))

    def test_vote_format_details(self) -> None:
        result = self.check_specimen("必错-董事会决议-票数写法", "决议")
        messages = " ".join(i["message"] for i in result["issues"])
        self.assertIn("票数之和 8", messages)
        self.assertIn("未超过全体董事 9 人的半数", messages)
        self.assertNotIn("未写表决结果", messages)
        self.assertEqual(result["summary"]["P0"], 4)

    def test_resolution_details(self) -> None:
        result = self.check_specimen("必错-董事会决议", "决议")
        messages = " ".join(i["message"] for i in result["issues"])
        self.assertIn("未超过全体董事 9 人的半数", messages)
        self.assertIn("票数之和 4", messages)
        self.assertIn("全票", messages)
        self.assertEqual(result["summary"]["P0"], 4)

    def test_ledger_details(self) -> None:
        result = self.check_specimen("必错-改革台账", "改革台账")
        messages = [i["message"] for i in result["issues"]]
        self.assertTrue(any("有序推进" in m for m in messages))
        self.assertTrue(any("没有佐证材料" in m for m in messages))
        self.assertTrue(any("已过" in m and "按计划推进" in m for m in messages))
        self.assertTrue(any("牵头部门为空" in m for m in messages))
        self.assertTrue(any("滞后任务没有写原因" in m for m in messages))
        self.assertEqual(result["as_of"], "2026-09-30")

    def test_draft_note_cut(self) -> None:
        # 必过-合规报告 的【起草说明】中写了“零违规”，不应报出
        result = self.check_specimen("必过-合规报告", "合规报告")
        self.assertNotIn("SOE-010", ids_of(result))


class ResolutionTest(SoeCheckBase):

    HEAD = "会议应出席董事7人，实际出席董事7人。\n"

    def test_attendance_not_majority(self) -> None:
        result = self.check("会议应出席董事7人，实际出席董事3人。\n审议通过《关于A的议案》。\n表决结果：同意3票，反对0票，弃权0票。", "决议")
        self.assertTrue(any("会议不能举行" in i["message"] for i in result["issues"]))

    def test_actual_more_than_should(self) -> None:
        result = self.check("会议应出席董事5人，实际出席董事6人。\n表决结果：同意6票，反对0票，弃权0票。", "决议")
        self.assertTrue(any("多于应出席" in i["message"] for i in result["issues"]))

    def test_chinese_numerals_and_alt_format(self) -> None:
        text = "会议应出席董事七人，实际出席董事七人。\n审议通过《关于A的议案》。\n表决结果：7票同意，0票反对，0票弃权。"
        self.assertEqual(serious(self.check(text, "决议")), [])
        text_bad = "会议应出席董事七人，实际出席董事七人。\n审议通过《关于A的议案》。\n表决结果：6票同意，0票反对，0票弃权。"
        self.assertIn("SOE-104", ids_of(self.check(text_bad, "决议")))

    def test_recusal_counted(self) -> None:
        ok = self.HEAD + "审议通过《关于关联交易的议案》。关联董事张某、李某回避表决。\n表决结果：同意5票，反对0票，弃权0票。"
        self.assertEqual(serious(self.check(ok, "决议")), [])
        bad = self.HEAD + "审议通过《关于关联交易的议案》。关联董事张某回避表决。\n表决结果：同意5票，反对0票，弃权0票。"
        self.assertIn("SOE-104", ids_of(self.check(bad, "决议")))

    def test_recusal_without_count(self) -> None:
        text = self.HEAD + "审议通过《关于关联交易的议案》。有关联关系的董事回避表决。\n表决结果：同意5票，反对0票，弃权0票。"
        result = self.check(text, "决议")
        self.assertTrue(any(i["level"] == "P2" and "回避人数" in i["message"] for i in result["issues"]))

    def test_recusal_majority_of_unrelated_directors(self) -> None:
        # 9 名董事，5 名关联董事回避，4 名无关联董事中 3 票同意：依法通过（《公司法》第一百八十五条）
        text = ("会议应出席董事9人，实际出席董事9人。\n审议通过《关于关联交易的议案》。关联董事5人回避表决。\n"
                "表决结果：同意3票，反对1票，弃权0票。")
        self.assertEqual(serious(self.check(text, "决议")), [])
        bad = text.replace("同意3票，反对1票", "同意2票，反对2票")
        self.assertTrue(any("无关联关系董事 4 人的半数" in i["message"] for i in self.check(bad, "决议")["issues"]))

    def test_unrelated_directors_less_than_three(self) -> None:
        text = ("会议应出席董事7人，实际出席董事7人。\n审议通过《关于关联交易的议案》。关联董事5人回避表决。\n"
                "表决结果：同意2票，反对0票，弃权0票。")
        result = self.check(text, "决议")
        self.assertTrue(any(i["level"] == "P1" and "不足三人" in i["message"] for i in result["issues"]))

    def test_recusal_unknown_count_no_pass_judgement(self) -> None:
        text = ("会议应出席董事9人，实际出席董事9人。\n审议通过《关于关联交易的议案》。有关联关系的董事回避表决。\n"
                "表决结果：同意4票，反对0票，弃权0票。")
        result = self.check(text, "决议")
        self.assertFalse(any("半数" in i["message"] for i in result["issues"]))
        self.assertTrue(any(i["level"] == "P2" and "回避人数" in i["message"] for i in result["issues"]))

    def test_vote_formats(self) -> None:
        for votes in ("同意票8票，反对票1票，弃权票0票", "同意：8票；反对：1票；弃权：0票", "同意8票，反对1票",
                      "8票同意，1票反对，0票弃权"):
            with self.subTest(votes=votes):
                text = "会议应出席董事9人，实际出席董事9人。\n审议通过《关于A的议案》。\n表决结果：" + votes + "。"
                self.assertEqual(serious(self.check(text, "决议")), [])
                bad = text.replace("8", "4", 1)
                self.assertIn("SOE-104", [i["id"] for i in serious(self.check(bad, "决议"))])

    def test_failed_item_not_flagged(self) -> None:
        text = self.HEAD + "审议《关于B的议案》。\n表决结果：同意3票，反对4票，弃权0票。该议案未通过。"
        self.assertEqual(serious(self.check(text, "决议")), [])

    def test_missing_counts(self) -> None:
        result = self.check("某公司董事会决议\n审议通过《关于A的议案》。", "决议")
        messages = " ".join(i["message"] for i in result["issues"])
        self.assertIn("未写明应出席", messages)
        self.assertIn("未写表决结果", messages)

    def test_to_int(self) -> None:
        self.assertEqual(sc.to_int("7"), 7)
        self.assertEqual(sc.to_int("七"), 7)
        self.assertEqual(sc.to_int("十"), 10)
        self.assertEqual(sc.to_int("十二"), 12)
        self.assertEqual(sc.to_int("二十一"), 21)
        self.assertIsNone(sc.to_int("若干"))


class OtherProceduralTest(SoeCheckBase):

    def test_yian_elements(self) -> None:
        result = self.check("关于A的议案\n各位董事：\n公司拟向某子公司增资。", "议案")
        messages = " ".join(i["message"] for i in result["issues"])
        self.assertIn("提请审议事项", messages)
        self.assertIn("决策程序履行情况", messages)
        good = ("关于A的议案\n各位董事：\n一、决策程序履行情况\n2026年10月20日公司党委会前置研究讨论，同意提交董事会审议。\n"
                "二、提请审议事项\n同意公司向某子公司增资2.4亿元。\n以上议案，请审议。")
        self.assertNotIn("SOE-103", ids_of(self.check(good, "议案")))

    def test_fusion_two_skins(self) -> None:
        text = "某支部党建经验\n党支部开展主题党日活动，党员参与积极。\n公司全年发电量86亿千瓦时。"
        self.assertIn("SOE-110", ids_of(self.check(text, "融合材料")))
        no_data = "某支部党建经验\n党支部开展主题党日活动，党员参与积极。"
        result = self.check(no_data, "融合材料")
        self.assertTrue(any("没有结果数据" in i["message"] for i in result["issues"]))

    def test_minutes_intro_line_skipped(self) -> None:
        text = "总经理办公会纪要\n现将会议议定事项纪要如下：\n一、关于A\n会议同意方案，由综合部牵头，10月31日前完成。"
        self.assertNotIn("SOE-108", ids_of(self.check(text, "纪要")))

    def test_soe108_is_hint_without_placeholder_advice(self) -> None:
        text = "总经理办公会纪要\n一、关于A\n会议同意修订值班制度。"
        issues = [i for i in self.check(text, "纪要")["issues"] if i["id"] == "SOE-108"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["level"], "P2")
        self.assertNotIn("标【待补】", issues[0]["suggestion"])
        self.assertIn("起草说明", issues[0]["suggestion"])

    def test_ledger_without_table(self) -> None:
        result = self.check("改革任务进展：已完成5项。", "改革台账")
        self.assertTrue(any("没有找到" in i["message"] for i in result["issues"]))

    def test_ledger_rate_over_100(self) -> None:
        text = ("| 序号 | 任务 | 牵头部门 | 完成时限 | 完成率 | 状态 | 佐证材料 |\n|---|---|---|---|---|---|---|\n"
                "| 1 | A | 综合部 | 2026年12月 | 120% | 按计划推进 | 无 |")
        self.assertTrue(any("超过 100%" in i["message"] for i in self.check(text, "改革台账")["issues"]))

    def test_parse_deadline(self) -> None:
        self.assertEqual(sc.parse_deadline("2026年6月30日"), dt.date(2026, 6, 30))
        self.assertEqual(sc.parse_deadline("2026年2月"), dt.date(2026, 2, 28))
        self.assertEqual(sc.parse_deadline("2026-09-30"), dt.date(2026, 9, 30))
        self.assertEqual(sc.parse_deadline("2026年底"), dt.date(2026, 12, 31))
        self.assertIsNone(sc.parse_deadline("长期"))
        self.assertIsNone(sc.parse_deadline("2026年13月"))

    def test_parse_deadline_without_year(self) -> None:
        self.assertEqual(sc.parse_deadline("8月31日", 2026), dt.date(2026, 8, 31))
        self.assertEqual(sc.parse_deadline("9月底", 2026), dt.date(2026, 9, 30))
        self.assertEqual(sc.parse_deadline("2026年二季度"), dt.date(2026, 6, 30))
        self.assertEqual(sc.parse_deadline("三季度末", 2026), dt.date(2026, 9, 30))
        self.assertEqual(sc.parse_deadline("上半年", 2026), dt.date(2026, 6, 30))
        self.assertEqual(sc.parse_deadline("年底", 2026), dt.date(2026, 12, 31))
        self.assertIsNone(sc.parse_deadline("8月31日"))
        self.assertIsNone(sc.parse_deadline("13月5日", 2026))

    def test_ledger_deadline_edge_cases(self) -> None:
        text = ("| 序号 | 任务 | 牵头部门 | 完成时限 | 状态 | 佐证材料 | 备注 |\n|---|---|---|---|---|---|---|\n"
                "| 1 | A | 综合部 | 2026年9月30日 | 按计划推进 | 无 |  |\n"
                "| 2 | B | 综合部 | 8月31日 | 按计划推进 | 无 |  |\n"
                "| 3 | C | 综合部 | 2026年二季度 | 未启动 | 无 |  |\n"
                "| 4 | D | 综合部 | 2026年8月31日 | 有序推进 | 无 |  |\n"
                "| 5 | E | 综合部 | 2026年10月31日 | 按计划推进 | 无 |  |\n"
                "| 6 | F | 综合部 | 2026年6月30日 | 滞后 | 无 | 因审批未完成，新时限为11月 |")
        issues = self.check(text, "改革台账")["issues"]
        overdue = [i for i in issues if "状态仍为" in i["message"]]
        self.assertEqual(len(overdue), 4, json.dumps(overdue, ensure_ascii=False))
        self.assertTrue(any("已到" in i["message"] for i in overdue))
        self.assertTrue(any("有序推进" in i["message"] and "不在约定口径" in i["message"] for i in issues))

    def test_minutes_guarantee_and_items(self) -> None:
        text = ("总经理办公会纪要\n2026年11月18日，总经理主持召开总经理办公会，研究仓储中心扩建、担保等事项。\n"
                "一、关于港区仓储中心扩建\n会议原则同意项目建设方向，要求战略投资部比选选址，"
                "【待补：完成时限】前按程序提交公司党委会前置研究讨论后，提请董事会审议。\n"
                "二、关于为参股公司提供担保\n会议同意为某参股公司提供担保2000万元，由财务部办理相关手续，12月10日前完成。")
        result = self.check(text, "纪要")
        self.assertIn("SOE-007", ids_of(result))
        lines_109 = [i["line"] for i in result["issues"] if i["id"] == "SOE-109"]
        self.assertTrue(lines_109 and min(lines_109) >= 5, lines_109)
        marked = text.replace("12月10日前完成。",
                              "12月10日前完成【待核实：本事项是否在董事会授权范围内；是否须先提交党委会前置研究讨论】。")
        marked_ids = ids_of(self.check(marked, "纪要"))
        self.assertNotIn("SOE-007", marked_ids)
        self.assertNotIn("SOE-109", marked_ids)

    def test_money_units_standard_amount_excluded(self) -> None:
        # 制度标准金额（门槛）不计入金额单位统计（W1-SO-3）
        cases = (
            "5000万元以上的投资须提交党委会前置研究。本项目投资1.2亿元。",
            "单笔3000万元（含）以上的对外投资，应经党委会前置研究讨论。本项目投资2.6亿元。",
            "投资额超过3000万元的项目，按规定报集团公司审批。本项目投资2.6亿元。",
            "大额度资金标准为单笔2000万元及以上。本项目借款1.5亿元。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertNotIn("SOE-107", ids_of(self.check(text, "议题材料")))

    def test_money_units_still_reported(self) -> None:
        cases = (
            "收入12.3亿元、利润8600万元。",
            "应收账款余额超过8600万元，营业收入12.3亿元。",
            "项目投资2000万元以上，营业收入1.5亿元。",
            "5000万元以上的投资须提交党委会前置研究。本项目投资1.2亿元，其中设备购置4500万元。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIn("SOE-107", ids_of(self.check(text, "议题材料")))

    def test_money_units_specimens(self) -> None:
        passed = self.check_specimen("必过-议题材料-制度标准金额", "议题材料")
        self.assertNotIn("SOE-107", ids_of(passed))
        self.assertEqual(serious(passed), [], json.dumps(passed["issues"], ensure_ascii=False))
        failed = self.check_specimen("必错-议题材料-金额单位", "议题材料")
        self.assertIn("SOE-107", ids_of(failed))

    def test_soe005_board_decides_after_party(self) -> None:
        self.assertNotIn("SOE-005", ids_of(self.check("党委会研究后，董事会审议批准增资方案。")))
        self.assertIn("SOE-005", ids_of(self.check("党委会研究后决定增资1.5亿元。")))

    def test_ratio_with_base_is_p1(self) -> None:
        result = self.check("6月末资产负债率较年初下降1.4%。", "经营分析")
        self.assertEqual([i["level"] for i in result["issues"] if i["id"] == "SOE-014"], ["P1"])

    def test_external_only_rules_need_external(self) -> None:
        text = "公司全年实现营业收入128.6亿元，投标报价为每吨386元，毛利率为21.3%，上述数据未公开。"
        self.assertFalse({"SOE-011", "SOE-012", "SOE-013", "SOE-027"} & set(ids_of(self.check(text, "经营分析"))))
        result = self.check(text, "对外材料")
        self.assertTrue({"SOE-011", "SOE-012", "SOE-013", "SOE-027"} <= set(ids_of(result)))
        self.assertTrue(result["external"])

    def test_external_level_p0_for_esg(self) -> None:
        esg = self.check("公司已实现碳中和，全年零事故。投标报价为每吨386元，毛利率为21.3%。", "ESG报告")
        levels = {i["id"]: i["level"] for i in esg["issues"]}
        self.assertEqual(levels["SOE-009"], "P0")
        self.assertEqual(levels["SOE-010"], "P0")
        self.assertEqual(levels["SOE-012"], "P0")
        self.assertEqual(levels["SOE-027"], "P1")

    def test_soe011_no_longer_matches_trade_secret(self) -> None:
        self.assertNotIn("SOE-011", ids_of(self.check("本材料涉及公司商业秘密。", "对外材料")))
        self.assertIn("SOE-021", ids_of(self.check("本材料涉及公司商业秘密。", "对外材料")))

    def test_staff_interest_satisfied_by_not_yet(self) -> None:
        base = "关于调整薪酬分配方案的议题。"
        self.assertIn("SOE-111", ids_of(self.check(base, "议题材料")))
        self.assertNotIn("SOE-111", ids_of(self.check(base + "尚未征求工会意见，拟于10月征求。", "议题材料")))
        self.assertNotIn("SOE-111", ids_of(self.check("按现行工资水平测算，投资回收期6年。", "议题材料")))

    def test_staff_interest_specimens(self) -> None:
        passed = self.check_specimen("必过-议题材料-职工权益", "议题材料")
        self.assertNotIn("SOE-111", ids_of(passed))
        self.assertEqual(serious(passed), [], json.dumps(passed["issues"], ensure_ascii=False))
        for name in ("必错-议题材料", "必过-议题材料", "必过-议题材料-制度标准金额"):
            self.assertNotIn("SOE-111", ids_of(self.check_specimen(name, "议题材料")), name)

    def test_soe025_only_for_yian(self) -> None:
        text = "表决结果：同意9票，反对0票，弃权0票。"
        self.assertIn("SOE-025", ids_of(self.check(text, "议案")))
        self.assertNotIn("SOE-025", ids_of(self.check(text, "决议")))

    def test_privacy_rules_mask_excerpt(self) -> None:
        # 遮蔽格式变化：旧格式是整段“〔已遮蔽，共N字〕”，新格式只遮姓名、按全文首次出现编号为〔姓名N〕，
        # 并保留锚点和右侧上下文，使报告能看出是哪句话（见 MaskingTest 的编号和合并断言）
        text = "对李明给予记过处分。\n分流人员名单：赵敏、钱进。"
        result = self.check(text, "纪要")
        self.assertTrue({"SOE-022", "SOE-023"} <= set(ids_of(result)))
        by_id = {i["id"]: i for i in result["issues"] if i["id"] in ("SOE-022", "SOE-023")}
        self.assertEqual(by_id["SOE-022"]["excerpt"], "对〔姓名1〕给予记过处分。")
        self.assertEqual(by_id["SOE-023"]["excerpt"], "分流人员名单：〔姓名2〕、〔姓名3〕。")
        for issue in by_id.values():
            self.assertNotIn("context", issue)
        rendered = sc.render_text(result) + json.dumps(result, ensure_ascii=False)
        for name in ("李明", "赵敏", "钱进"):
            self.assertNotIn(name, rendered)

    def test_external_level_upgrade(self) -> None:
        text = "该技术填补了国内空白。"
        internal = self.check(text, "融合材料")
        external = self.check(text, "融合材料", external=True)
        self.assertEqual([i["level"] for i in internal["issues"] if i["id"] == "SOE-008"], ["P1"])
        self.assertEqual([i["level"] for i in external["issues"] if i["id"] == "SOE-008"], ["P0"])

    def test_no_type_runs_general_rules_only(self) -> None:
        result = self.check("项目已先行开工。\n会议决定投资5亿元。")
        self.assertIn("SOE-001", ids_of(result))
        self.assertNotIn("SOE-007", ids_of(result))
        self.assertTrue(any("未指定 --type" in n for n in result["notes"]))


class ClauseExemptionTest(SoeCheckBase):
    """豁免按分句生效：前半句有豁免词、后半句是真违规时不得整句放掉；语境词所在分句内的命中仍不报。"""

    # (句子, 规则, 是否应命中, 文书类型)
    CASES = (
        ("本次投标报价为1.2亿元，不得外传。", "SOE-012", True, "对外材料"),
        ("公司制定了投标管理制度，本次投标报价为1.2亿元。", "SOE-012", True, "对外材料"),
        ("本次未公开投标报价，以竞争性谈判方式选定供应商。", "SOE-012", False, "对外材料"),
        ("本次未公开投标报价，以竞争性谈判方式选定供应商。", "SOE-011", False, "对外材料"),
        ("本报告不包含任何未公开信息。", "SOE-011", False, "对外材料"),
        ("公司没有未披露的重大事项。", "SOE-011", False, "对外材料"),
        ("上述内容尚未公开，不得转载。", "SOE-011", True, "对外材料"),
        ("运营数据显示，公司产品市场占有率行业第一。", "SOE-008", True, "对外材料"),
        ("公司已成为行业第一的综合能源服务商。", "SOE-008", True, "对外材料"),
        ("该产品技术达国内领先水平，与国际一流相比仍有差距。", "SOE-008", True, "对外材料"),
        ("经努力，产品已达国内领先水平。", "SOE-008", True, "对外材料"),
        ("在全国范围内保持领先。", "SOE-008", True, "对外材料"),
        ("据中国某协会统计，公司产品市场占有率行业第一。", "SOE-008", False, "对外材料"),
        ("全省第一季度经营情况稳中有升。", "SOE-008", False, "对外材料"),
        ("全国第一届职工运动会在本公司举办。", "SOE-008", False, "对外材料"),
        ("我公司是行业内第一批开展该项目的企业。", "SOE-008", False, "对外材料"),
        ("推动产业规模最大化。", "SOE-008", False, "对外材料"),
        ("公司力求在国内领先。", "SOE-008", False, "对外材料"),
        ("公司谋求成为国内领先的综合能源服务商。", "SOE-008", False, "对外材料"),
        ("公司已实现碳中和，2030年目标为进一步降碳。", "SOE-009", True, "ESG报告"),
        ("我公司已实现碳中和。", "SOE-009", True, "ESG报告"),
        ("2025年实现零排放。", "SOE-009", True, "ESG报告"),
        ("园区已实现净零排放。", "SOE-009", True, "ESG报告"),
        ("公司碳中和路线图已经董事会审议通过。", "SOE-009", False, "ESG报告"),
        ("组织开展碳中和知识培训3场。", "SOE-009", False, "ESG报告"),
        ("力争2030年前实现碳达峰、2060年前实现碳中和。", "SOE-009", False, "ESG报告"),
        ("为实现碳中和，公司开展能耗对标。", "SOE-009", False, "ESG报告"),
        ("行业正加快推进碳中和进程。", "SOE-009", False, "ESG报告"),
        ("依据年度考核，公司全年零违规、零风险。", "SOE-010", True, "合规报告"),
        ("全年合规率达100%。", "SOE-010", True, "合规报告"),
        ("开展零风险意识教育专题培训。", "SOE-010", False, "合规报告"),
        ("创建零事故示范班组活动稳步推进。", "SOE-010", False, "合规报告"),
        ("2025年度未发生任何违规事项，见年报。", "SOE-010", False, "合规报告"),
        ("注：本报告含商业秘密，请注意保护。", "SOE-021", True, None),
        ("该报价数据属于商业秘密，不得泄露。", "SOE-021", True, None),
        ("本材料涉及公司商业秘密，请勿外传。", "SOE-021", True, None),
        ("密级：商业秘密", "SOE-021", True, None),
        ("密级：核心商密★5年", "SOE-021", True, None),
        ("文件保密等级：机密（商业秘密）", "SOE-021", True, None),
        ("以下内容为商密信息，请谨慎传阅。", "SOE-021", True, None),
        ("上述客户清单系本公司商业秘密范畴。", "SOE-021", True, None),
        ("【商密】本材料仅限内部阅览。", "SOE-021", True, None),
        ("公司加强商业秘密保护。", "SOE-021", False, None),
        ("签订商业秘密保护协议。", "SOE-021", False, None),
        ("依法保护商业秘密。", "SOE-021", False, None),
        ("本材料不涉及商业秘密。", "SOE-021", False, None),
        ("本制度涉及商业秘密范围界定。", "SOE-021", False, None),
        ("建议董事会注意，本议案已获全票通过。", "SOE-025", True, "议案"),
        ("本议案已获董事会一致同意。", "SOE-025", True, "议案"),
        ("若本议案未获通过，经理层不得实施该方案。", "SOE-025", False, "议案"),
        ("一致同意提交董事会审议。", "SOE-025", False, "议案"),
        ("本报告已经党委会前置研究，并经董事会审议通过。", "SOE-026", True, "合规报告"),
        ("本报告已经董事会审议通过，将报送国资委。", "SOE-026", True, "合规报告"),
        ("本报告经审计委员会审议后，提请董事会审议通过。", "SOE-026", False, "合规报告"),
        ("中标价格已于2025年披露。", "SOE-027", False, "对外材料"),
        ("成本价格管理办法已修订。", "SOE-027", False, "对外材料"),
        ("公司结算价为每吨420元，该数据请内部掌握。", "SOE-027", True, "对外材料"),
    )

    def test_clause_cases(self) -> None:
        for text, rid, expected, doc_type in self.CASES:
            with self.subTest(text=text, rule=rid):
                self.assertEqual(rid in ids_of(self.check(text, doc_type, external=True)), expected)

    def test_exempt_before_and_clause_fields_loaded(self) -> None:
        rules = {r.id: r for r in self.ruleset.rules}
        self.assertIsNotNone(rules["SOE-011"].exempt_before)
        for rid in ("SOE-008", "SOE-009", "SOE-010", "SOE-011", "SOE-012", "SOE-021", "SOE-025", "SOE-026", "SOE-027"):
            with self.subTest(rule=rid):
                self.assertIsNotNone(rules[rid].exempt_clause)
        # 这几条没有“出处在相邻分句”的需要，不留任何整句豁免
        for rid in ("SOE-011", "SOE-012", "SOE-021", "SOE-025", "SOE-026"):
            with self.subTest(rule=rid):
                self.assertIsNone(rules[rid].exempt, "语境类豁免应写在 exempt_clause，不应整句生效")


class PersonNameMisfireTest(SoeCheckBase):
    """SOE-022：姓氏开头的地名、单位名、普通词不当作处分对象的姓名。

    这是回归测试，不能证明识别精度：下面的清单是人工挑出来的反例，通过只说明这些词不再误报，
    不说明没列出的企业简称、地名不会误报（已知局限：“对唐钢给予警告处分”仍报 P0，见 KnownLimitTest）。
    识别精度由 tests/names 的召回、精度和对抗探针另行验证。
    """

    PLACES = (
        "林业局", "李渡镇", "贺州分公司", "钱塘项目部", "秦皇岛港务公司", "邓小平理论", "毛利率", "石油公司", "金融事业部",
        "江苏公司", "高新区管委会", "方正集团", "程序", "周边", "马鞍山基地", "何种情形", "黄山分公司", "孙公司", "张家港项目部",
        "王府井百货", "杨浦区", "田园综合体", "范围", "苏州工业园区", "吴江区", "郑州基地", "朱家角", "林芝市", "沈阳分公司",
        "唐山港", "韩城电厂", "梁山县", "宋庄镇", "胡同改造项目", "赵县水厂", "袁州区", "彭州市", "蔡甸区", "潘集矿", "杜集区",
        "戴河站", "钟祥市", "汪清县", "姜堰区", "熊猫基金", "孔雀城", "崔家营", "毛坯房项目", "邱县", "秦淮区", "顾问公司",
        "侯马市", "邵武市", "孟津县", "钱江新城", "贺兰山", "乔木园", "曹妃甸港", "吕梁市", "卢沟桥", "叶县电厂", "阎良区",
        "魏县", "薛城区", "傅家庄", "蒋家村", "郭家店", "董事会办公室", "萧山区", "罗湖区", "林场", "汤阴县", "黎川县", "张掖市",
        "徐庄", "李庄", "贺家湾", "蔡家坡", "吴淞口",
    )
    TEMPLATES = ("对{}给予警告处分。", "给予{}记过处分。", "{}受到警告处分。")

    def test_places_and_units_not_names(self) -> None:
        self.assertGreaterEqual(len(self.PLACES), 60)
        wrong = []
        for place in self.PLACES:
            for template in self.TEMPLATES:
                text = template.format(place)
                if "SOE-022" in ids_of(self.check(text)):
                    wrong.append(text)
        self.assertEqual(wrong, [])

    def test_real_names_still_hit(self) -> None:
        for text in ("给予王建国同志党内警告处分", "对李明给予记过处分", "张伟受到警告处分", "对刘洋给予警告处分",
                     "对陈晨给予记过处分", "给予吴刚撤职处分", "对郑浩给予降级处分", "对朱红给予开除处分"):
            with self.subTest(text=text):
                self.assertIn("SOE-022", ids_of(self.check(text)))


class MaskPropagationTest(SoeCheckBase):
    """姓名不得经其他规则的 excerpt、context 或函数检查的首行摘录泄露。"""

    def _assert_no_name(self, result, name: str) -> None:
        self.assertNotIn(name, json.dumps(result, ensure_ascii=False))
        self.assertNotIn(name, sc.render_text(result))

    def test_regex_rule_context_masked(self) -> None:
        # 遮蔽格式变化：旧引擎把整段命中片段（“王建国同志给予党内警告处分”）换成“〔已遮蔽〕”；
        # 新引擎只遮姓名并编号。context 窗口（命中前后各 12 字）要包含姓名才能看到占位，所以用姓名落在窗口内的写法
        text = "会议同意给予王建国同志警告，本议案全票通过。"
        result = self.check(text, "议案")
        self.assertIn("SOE-025", ids_of(result))
        issue = next(i for i in result["issues"] if i["id"] == "SOE-025")
        self.assertIn("〔姓名1〕", issue.get("context", ""))
        self._assert_no_name(result, "王建国")

    def test_context_window_never_leaves_half_a_name(self) -> None:
        """context 窗口边界恰好切在姓名中间时，不得露出半个姓名（旧的按片段遮蔽没有这个问题，新实现要保证）。"""
        # “全票通过”前 12 个字刚好切在“王建国”的“建”之前或之后
        for pad in range(0, 4):
            text = "给予王建国同志警告" + "，" * 0 + "某" * pad + "，本议案全票通过。"
            result = self.check(text, "议案")
            for part in ("王建", "建国", "王建国"):
                self.assertNotIn(part, json.dumps(result, ensure_ascii=False), (pad, part))

    def test_procedural_first_line_masked(self) -> None:
        for doc_type, text in (("议案", "对李明给予记过处分的议案\n各位董事：\n公司拟办理有关事项。"),
                               ("议题材料", "关于对赵强同志给予记大过处分的议题\n背景和依据：略。")):
            with self.subTest(doc_type=doc_type):
                result = self.check(text, doc_type)
                self.assertTrue(any(i["id"] in ("SOE-101", "SOE-103") for i in result["issues"]))
                self._assert_no_name(result, text[text.index("对") + 1:text.index("对") + 3] if doc_type == "议案" else "赵强")

    def test_masked_in_json_cli(self) -> None:
        path = self.tmp / "议案.txt"
        path.write_text("对李明给予记过处分的议案，本议案全票通过。\n", encoding="utf-8")
        code, out, _err = self.run_main(str(path), "--type", "议案", "--json")
        self.assertEqual(code, 0)
        self.assertNotIn("李明", out)
        code, out, _err = self.run_main(str(path), "--type", "议案")
        self.assertNotIn("李明", out)

    def test_name_masked_fulltext_across_lines(self) -> None:
        """姓名在第 2 行被隐私规则识别，在后面几行被非隐私规则带出，全文输出都不得含该姓名。"""
        text = ("关于有关事项的议案\n会议对王建国同志给予党内警告处分。\n\n表决情况\n"
                "王建国同志对此意见一致，本议案全票通过。\n分流人员名单：赵敏、钱进\n钱进同志本议案全票通过。")
        result = self.check(text, "议案")
        self.assertIn("SOE-025", ids_of(result))
        for name in ("王建国", "赵敏", "钱进"):
            self._assert_no_name(result, name)
        path = self.tmp / "议案.txt"
        path.write_text(text, encoding="utf-8")
        for extra in ((), ("--json",)):
            code, out, _err = self.run_main(str(path), "--type", "议案", *extra)
            self.assertEqual(code, 0)
            for name in ("王建国", "赵敏", "钱进"):
                self.assertNotIn(name, out)

    def test_pseudonym_not_in_name_table(self) -> None:
        result = self.check("对王某给予警告处分。\n王某对此意见一致，本议案全票通过。", "议案")
        issue = next(i for i in result["issues"] if i["id"] == "SOE-025")
        self.assertIn("王某", issue.get("context", ""))
        self.assertNotIn("〔姓名", json.dumps(result, ensure_ascii=False))

    def test_no_mask_without_names(self) -> None:
        result = self.check("本议案全票通过。", "议案")
        issue = next(i for i in result["issues"] if i["id"] == "SOE-025")
        self.assertEqual(issue["excerpt"], "全票通过")
        self.assertNotIn("〔姓名", json.dumps(result, ensure_ascii=False))


class NameDetectionTest(SoeCheckBase):
    """SOE-022 处分对象实名：锚点 + 候选 + 打分。高置信 P0、低置信 P1，不分内外。"""

    SHOULD_P0 = ("给予马建国同志党内警告处分", "给予周杰记过处分", "对欧阳明给予记过处分", "王强被开除党籍",
                 "会议同意给予赵强同志记大过处分", "给予张建国同志党内警告处分", "会议研究决定王强被开除党籍。",
                 "总经理王强同志受到党内严重警告处分。")
    SHOULD_NOT = ("对林业局给予警告。", "对孙公司给予警告。", "对项目经理给予警告处分。", "给予某同志党内警告处分",
                  "对王某给予警告处分", "对2名责任人给予警告处分", "给予党内警告处分", "对贺州分公司给予警告",
                  "邓小平理论受到警告处分。", "钱江新城受到警告处分。")

    def test_should_report_p0(self) -> None:
        for text in self.SHOULD_P0:
            for external in (False, True):
                with self.subTest(text=text, external=external):
                    levels = [i["level"] for i in self.check(text, None, external)["issues"] if i["id"] == "SOE-022"]
                    self.assertEqual(levels, ["P0"])

    def test_should_not_report(self) -> None:
        for text in self.SHOULD_NOT:
            with self.subTest(text=text):
                self.assertNotIn("SOE-022", ids_of(self.check(text)))

    def test_low_confidence_is_p1(self) -> None:
        # 歧义姓（宁）的两字名只有 5 分：低置信，P1，不分内外
        for external in (False, True):
            levels = [i["level"] for i in self.check("对宁静给予警告处分。", None, external)["issues"] if i["id"] == "SOE-022"]
            self.assertEqual(levels, ["P1"])

    def test_pseudonym_not_reported(self) -> None:
        for text in ("对王某给予警告处分。", "给予李某某同志记过处分。"):
            self.assertNotIn("SOE-022", ids_of(self.check(text)))

    def test_exempt_names_still_enter_table(self) -> None:
        """因豁免没报出的已识别姓名也进姓名表：其他规则的摘录里同样要遮蔽。
        SOE-022 本身没有配豁免，这里给它临时加一条 exempt_clause 来模拟。"""
        data = json.loads(sc.RULES_PATH.read_text(encoding="utf-8"))
        for item in data["rules"]:
            if item["id"] == "SOE-022":
                item["exempt_clause"] = "严禁"
        path = self.tmp / "rules.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        ruleset = sc.load_rules(path)
        text = "严禁给予王建国同志警告处分的做法。\n王建国对此意见一致，本议案全票通过。"
        result = sc.check_text(text, "议案", False, ruleset=ruleset, as_of=AS_OF)
        self.assertNotIn("SOE-022", ids_of(result), "已豁免，不报")
        self.assertIn("SOE-025", ids_of(result))
        self.assertNotIn("王建国", json.dumps(result, ensure_ascii=False))
        self.assertIn("〔姓名1〕", next(i for i in result["issues"] if i["id"] == "SOE-025")["context"])

    def test_list_rule_applies_to_types(self) -> None:
        text = "拟提拔人选名单：王建国、李红梅。"
        self.assertIn("SOE-023", ids_of(self.check(text, "议题材料")))
        self.assertNotIn("SOE-023", ids_of(self.check(text, "经营分析")))
        # 经营分析里不报，但姓名仍进表：别处的摘录里不得露出
        other = self.check("拟提拔人选名单：王建国、李红梅。\n王建国的毛利率为21.3%。", "对外材料")
        self.assertNotIn("王建国", json.dumps(other, ensure_ascii=False))


class KnownLimitTest(SoeCheckBase):
    """已知局限：记录目前识别不了或会误报的写法，防止文档与行为脱节。改进后应更新这里并同步文档。"""

    def test_enterprise_abbreviation_in_discipline_frame_misfires(self) -> None:
        for text in ("对唐钢给予警告处分", "对马钢给予警告"):
            with self.subTest(text=text):
                self.assertIn("SOE-022", ids_of(self.check(text)))

    def test_name_without_anchor_not_detected(self) -> None:
        result = self.check("马建国分管的项目中标价为3.2亿元。", "对外材料")
        self.assertNotIn("SOE-022", ids_of(result))
        self.assertNotIn("〔姓名", json.dumps(result, ensure_ascii=False))
        self.assertIn("马建国", json.dumps(result, ensure_ascii=False))  # 没有锚点，也没有别处识别，只能原样


class MaskingTest(SoeCheckBase):
    """全文姓名表编号、整串遮蔽、摘录合并。"""

    DOC = "会议同意给予马建国同志党内警告处分。\n马建国分管的项目中标价为3.2亿元。"

    def test_external_material_never_shows_name(self) -> None:
        result = self.check(self.DOC, "对外材料")
        ids = ids_of(result)
        self.assertIn("SOE-022", ids)
        self.assertIn("SOE-027", ids)
        rendered = sc.render_text(result) + json.dumps(result, ensure_ascii=False)
        self.assertNotIn("马建国", rendered)
        issue = next(i for i in result["issues"] if i["id"] == "SOE-027")
        self.assertIn("〔姓名1〕分管", issue["context"])
        path = self.tmp / "对外.txt"
        path.write_text(self.DOC, encoding="utf-8")
        for extra in ((), ("--json",)):
            code, out, err = self.run_main(str(path), "--type", "对外材料", *extra)
            self.assertEqual(code, 0)
            self.assertNotIn("马建国", out + err)

    def test_numbering_by_first_appearance(self) -> None:
        text = "对周杰给予记过处分。\n拟提拔人选名单：马建国、周杰。\n欧阳明被开除党籍。"
        result = self.check(text, "议题材料")
        excerpts = " ".join(i["excerpt"] for i in result["issues"])
        self.assertIn("对〔姓名1〕给予记过处分", excerpts)
        self.assertIn("〔姓名2〕、〔姓名1〕", excerpts)
        self.assertIn("〔姓名3〕被开除党籍", excerpts)

    def test_name_list_line_is_identifiable_and_merged(self) -> None:
        result = self.check("拟提拔人选名单：王建国、李红梅。", "议题材料")
        rows = [i for i in result["issues"] if i["id"] == "SOE-023"]
        self.assertEqual(len(rows), 1, "名单行不得再出现多条完全相同的摘录")
        self.assertEqual(rows[0]["line"], 1)
        self.assertEqual(rows[0]["excerpt"], "拟提拔人选名单：〔姓名1〕、〔姓名2〕。")
        self.assertEqual(rows[0]["count"], 2)
        text = sc.render_text(result)
        self.assertIn("SOE-023", text)
        self.assertIn("第1行", text)
        self.assertIn("〔姓名1〕、〔姓名2〕", text)
        self.assertNotIn("王建国", text)
        self.assertNotIn("李红梅", text)

    def test_identical_issues_are_merged_with_count(self) -> None:
        result = self.check("项目已先行开工，已先行开工。", None)
        rows = [i for i in result["issues"] if i["id"] == "SOE-001"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 2)
        self.assertEqual(result["summary"]["P0"], 1)

    def test_procedural_checks_are_masked(self) -> None:
        """函数检查（SOE-1xx）的摘录同样经全文姓名表。"""
        result = self.check("关于对赵强同志给予记大过处分的议题\n背景和依据：略。", "议题材料")
        self.assertTrue(any(i["id"] == "SOE-101" for i in result["issues"]))
        self.assertNotIn("赵强", json.dumps(result, ensure_ascii=False))
        self.assertIn("〔姓名1〕", next(i["excerpt"] for i in result["issues"] if i["id"] == "SOE-101"))

    def test_docx_style_duplicate_line_numbers_do_not_break(self) -> None:
        # docx 表格转 Markdown 行后，分隔行与表头行行号相同；遮蔽时按行号取原文，取第一个
        lines = [(1, "| 姓名 | 处分 |"), (1, "|---|---|"), (2, "对周杰给予记过处分。")]
        result = sc.build_result("x.docx", lines, None, False, self.ruleset, AS_OF)
        self.assertNotIn("周杰", json.dumps(result, ensure_ascii=False))


class ProcedureInversionTest(SoeCheckBase):
    """SOE-001 程序倒置：正则 + 组合判定（“已执行”与“提请或补办”）。"""

    # 收缩：P0 只来自 pattern 对“先行开工、补办手续、追认”等明确写法的命中；“已执行 + 提请”的组合判定一律 P1
    P0 = ("该项目已先行开工，现提请补办审批手续。",
          "项目已于9月先行开工，属于程序倒置，现如实报告，并提请董事会追认。",
          "项目已于9月先行开工，属于程序倒置，现如实报告并补办审批手续。")
    COMBO_P1 = ("该项目已于2026年9月开工建设，现提请董事会审议。", "已签约，现提请董事会审议。",
                "本项目设备已于9月采购到位并投入使用，现提请院长办公会审议。")
    P1 = ("项目已于9月先行开工，属于程序倒置，现如实报告。", "一期已开工，现提请审议二期方案。")
    NONE = ("巡察反馈的先行开工问题已于9月整改到位。", "严禁下列行为：先行开工后补办手续。", "本项目尚未开工，现提请董事会审议。",
            "已于9月召开职代会审议通过，现提请董事会审议。", "经董事会审议通过后已开工建设，现将进展报告如下。",
            "已完成论证，拟提交党委会议研究。")

    def levels(self, text: str, doc_type="议题材料") -> list:
        # 组合判定只在 procedure_inversion.types（议题材料、议案、纪要、决议）下生效，默认用议题材料
        return [i["level"] for i in self.check(text, doc_type)["issues"] if i["id"] == "SOE-001"]

    def test_p0(self) -> None:
        for text in self.P0:
            with self.subTest(text=text):
                self.assertEqual(min(self.levels(text) or ["-"]), "P0")

    def test_p1(self) -> None:
        for text in self.P1 + self.COMBO_P1:
            with self.subTest(text=text):
                self.assertEqual(self.levels(text), ["P1"])

    def test_combination_never_p0(self) -> None:
        for text in self.COMBO_P1:
            for doc_type in ("议题材料", "议案", "纪要", "决议"):
                with self.subTest(text=text, doc_type=doc_type):
                    self.assertEqual(self.levels(text, doc_type), ["P1"])

    def test_disposal_in_later_clause_no_longer_exempts(self) -> None:
        """收缩的已知代价：整改写在后一分句，豁免不再生效；后续分句里有针对该做法的处置词，P0 降为 P1，suggestion 带“可忽略本条”的提示。"""
        text = "巡察反馈的先行开工问题，已于9月整改到位。"
        self.assertEqual(self.levels(text), ["P1"])
        hit = next(i for i in self.check(text, "议题材料")["issues"] if i["id"] == "SOE-001")
        self.assertIn("可忽略本条", hit["suggestion"])

    def test_not_reported(self) -> None:
        for text in self.NONE:
            with self.subTest(text=text):
                self.assertEqual(self.levels(text), [])

    def test_all_doc_types(self) -> None:
        """组合判定只在议题材料、议案、纪要、决议中生效；其他文书类型不做组合判定（SOE-001 的正则规则本身仍不限类型）。"""
        combo = set(self.ruleset.inversion["types"])
        self.assertEqual(combo, {"议题材料", "议案", "纪要", "决议"})
        for doc_type in self.ruleset.types:
            with self.subTest(doc_type=doc_type):
                expected = ["P1"] if doc_type in combo else []
                self.assertEqual(self.levels("已签约，现提请董事会审议。", doc_type), expected)
        # 正则命中的“先行开工”不受类型限制：在“经营分析”下仍按原规则报 P0
        self.assertEqual(self.levels("项目已于9月先行开工，现提请董事会审议。", "经营分析"), ["P0"])
        self.assertEqual(self.levels("项目已先行开工。", None), ["P0"])

    def test_adjacent_sentence_is_p1_and_blank_line_breaks(self) -> None:
        self.assertEqual(self.levels("设备已于9月采购到位。\n现提请院长办公会审议。"), ["P1"])
        self.assertEqual(self.levels("设备已于9月采购到位。\n\n现提请院长办公会审议。"), [])

    def test_declared_caliber_change(self) -> None:
        """口径变化：写了肯定式声明（如“属于程序倒置”）且没写追认、补办的，由 P0 降为 P1（“如实报告”单独出现不算声明）；写了追认或补办的仍 P0。"""
        self.assertEqual(self.levels("项目已于9月先行开工，属于程序倒置，现如实报告。"), ["P1"])
        self.assertEqual(self.levels("项目已先行开工。"), ["P0"])
        result = self.check("项目已于9月先行开工，属于程序倒置，现如实报告。", "议题材料")
        issue = next(i for i in result["issues"] if i["id"] == "SOE-001")
        self.assertEqual(issue["excerpt"], "先行开工", "与正则命中合并时保留正则那条的摘录")

    def test_merge_with_regex_hit_keeps_regex_excerpt_and_higher_level(self) -> None:
        result = self.check("项目已于2026年9月先行开工，现提请补办审批手续。", "议题材料")
        rows = [i for i in result["issues"] if i["id"] == "SOE-001"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["level"], "P0")
        self.assertEqual(rows[0]["excerpt"], "先行开工")

    def test_inversion_only_issue_has_combination_excerpt(self) -> None:
        result = self.check("该项目已于2026年9月开工建设，现提请董事会审议。", "议题材料")
        row = next(i for i in result["issues"] if i["id"] == "SOE-001")
        self.assertIn("已于2026年9月开工建设", row["excerpt"])
        self.assertIn("提请董事会审议", row["excerpt"])

    def test_example_f_draft_still_p0(self) -> None:
        text = "项目已于2026年9月先行开工，现提请补办审批手续。"
        self.assertEqual(self.levels(text, "议题材料"), ["P0"])

    def test_bad_inversion_config(self) -> None:
        data = json.loads(sc.RULES_PATH.read_text(encoding="utf-8"))
        data["procedure_inversion"]["rule_id"] = "SOE-999"
        bad = self.tmp / "rules.json"
        bad.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(sc.InputError):
            sc.load_rules(bad)
        data["procedure_inversion"]["rule_id"] = "SOE-001"
        data["procedure_inversion"]["req"] = "("
        bad.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(sc.InputError):
            sc.load_rules(bad)


class SplitAvoidanceTest(SoeCheckBase):
    """SOE-029 拆分规避集体决策（P0）；SOE-006 保持 P1，只修正“三个子项目”写法。"""

    HITS = ("该项目拆分为三个子项目分别报批，每项均低于董事会审批标准", "该采购拆分为三个合同分别签订。",
            "将该项目拆分为一期、二期，分别立项，单项投资均低于5000万元的董事会审批标准。")
    MISSES = ("严禁化整为零规避集体决策。", "按合同约定分期支付工程款。", "推动子公司分拆上市。", "将主业拆分为三个业务板块。",
              "严禁将项目拆分为多个子项目分别报批。", "巡察指出该项目曾拆分为三个子项目分别报批问题已整改到位。")

    def test_hits(self) -> None:
        for text in self.HITS:
            with self.subTest(text=text):
                levels = [i["level"] for i in self.check(text)["issues"] if i["id"] == "SOE-029"]
                self.assertEqual(levels, ["P0"])

    def test_misses(self) -> None:
        for text in self.MISSES:
            with self.subTest(text=text):
                self.assertNotIn("SOE-029", ids_of(self.check(text)))

    def test_later_clause_disposal_is_reported_again(self) -> None:
        """收缩的已知代价：整改写在后一分句，重新被报出。"""
        ids = ids_of(self.check("巡察指出该项目曾拆分为三个子项目分别报批，已整改到位。"))
        self.assertIn("SOE-029", ids)

    def test_soe006_stays_p1_and_covers_sub_projects(self) -> None:
        result = self.check("该项目拆分为三个子项目，各自按小额采购办理。")
        self.assertEqual([i["level"] for i in result["issues"] if i["id"] == "SOE-006"], ["P1"])
        self.assertNotIn("SOE-029", ids_of(result))
        self.assertNotIn("SOE-006", ids_of(self.check("将主业拆分为三个业务板块。")))


class ExemptionMigrationTest(SoeCheckBase):
    """SOE-001、002、003、004、006、018、019 的豁免由整句迁到分句 + 引导句 + 前置否定；
    处置类只在命中所在分句内生效（收缩：取消后续分句 after 窗口，整改写在后一分句的重新被报出）。"""

    CASES = (
        # (规则, 句子, 是否命中)
        ("SOE-001", "严禁下列行为：先行开工后补办手续。", False),            # lead
        ("SOE-001", "不得先行开工，不得先签约后报批。", False),               # clause
        ("SOE-001", "项目尚未先行开工，待董事会审议后实施。", False),          # prefix 否定
        ("SOE-001", "项目未经批准先行开工。", True),                         # “未经批准”不是紧邻的否定
        ("SOE-001", "巡察反馈的先行开工问题已于9月整改到位。", False),         # 同分句处置类
        ("SOE-001", "巡察反馈的先行开工问题，已于9月整改到位。", True),        # 收缩的已知代价：处置写在后一分句，重新报出
        ("SOE-001", "对上述先行开工问题已责成相关单位整治。", False),          # 同分句（沿用旧整句词“整治”）
        ("SOE-001", "对上述先行开工问题，已责成相关单位整治。", True),          # 已知代价
        ("SOE-001", "项目已先行开工，已被叫停。", True),                      # “叫停”不在处置词里（“已叫停”才是），仍报
        ("SOE-001", "项目先行开工问题已叫停并整改到位。", False),
        ("SOE-001", "项目已先行开工，已叫停并整改到位。", True),               # 已知代价
        ("SOE-001", "严禁以下行为：\n先行开工后补办手续。", True),            # 引导句在上一行：整句窗口不跨行，仍报（已知局限）
        ("SOE-002", "现提请董事会对该合同予以追认。", True),
        ("SOE-002", "严禁以追认代替事前决策。", False),
        ("SOE-002", "现提请董事会追认，严禁此类情况再次发生。", True),         # 禁止词在后面的分句，不再整句放掉
        ("SOE-002", "现提请董事会追认该事项已纠正。", False),
        ("SOE-002", "现提请董事会予以追认，该事项已纠正。", True),             # 已知代价
        ("SOE-003", "严禁实施后再提交职代会审议。", False),
        ("SOE-003", "为防止方案实施后再提交职代会，现提前安排。", False),
        ("SOE-003", "方案实施后再提交职代会审议，请予关注。", True),
        ("SOE-004", "不得直接提交董事会审议。", False),
        ("SOE-004", "要求：不宜直接提交董事会。", False),
        ("SOE-004", "本事项已研究同意，拟直接提交董事会审议。", True),
        ("SOE-006", "严禁化整为零。", False),
        ("SOE-006", "该工程化整为零已整改。", False),                        # 同分句处置类
        ("SOE-006", "该工程化整为零，已整改。", True),                       # 已知代价
        # 口径变化：“已整改的”是定语（匹配后 6 字内有“的”），不算处置类豁免，所以现在报；成对的“已整改”（谓语）同分句仍豁免
        ("SOE-006", "该工程化整为零，已整改的只有一期。", True),
        ("SOE-006", "该工程化整为零问题已整改。", False),
        ("SOE-006", "该工程化整为零问题，已整改。", True),                   # 已知代价
        ("SOE-006", "项目化整为零，各自按小额采购办理。", True),
        ("SOE-018", "进一步理顺三会一层权责边界。", True),
        ("SOE-018", "不写“三会一层”，改为具体主体。", False),
        ("SOE-018", "完善三会一层运行机制，改为具体主体。", True),             # 豁免词在另一个分句：不再整句放掉
        ("SOE-019", "坚持授权即免责，放手让经理层决策。", True),
        ("SOE-019", "不得搞授权即免责。", False),
        ("SOE-019", "我们坚持授权即免责，但是不得滥用。", True),              # 禁止词在后面的分句：不再放掉
        ("SOE-019", "原则：授权即免责是错误的。", True),
    )

    def test_cases(self) -> None:
        for rid, text, expected in self.CASES:
            with self.subTest(rule=rid, text=text):
                self.assertEqual(rid in ids_of(self.check(text, "议题材料")), expected)

    def test_fields_migrated(self) -> None:
        rules = {r.id: r for r in self.ruleset.rules}
        for rid in ("SOE-001", "SOE-002", "SOE-003", "SOE-004", "SOE-006", "SOE-018", "SOE-019"):
            with self.subTest(rule=rid):
                self.assertIsNone(rules[rid].exempt, "已迁为 clause、lead、prefix 否定，不应再有整句 exempt_context")
                # 禁止类词迁到 exempt_chain（顿号并列的各项共享前面的“杜绝”“严禁”），其余词仍在 exempt_clause
                self.assertTrue(rules[rid].exempt_clause is not None or rules[rid].exempt_chain is not None)
                self.assertIsNotNone(rules[rid].exempt_lead)
        for rid in ("SOE-001", "SOE-002", "SOE-006", "SOE-029"):
            self.assertFalse(hasattr(rules[rid], "exempt_after"), rid)      # 收缩：后续分句窗口（after）已取消
            self.assertNotIn("after", rules[rid].exempt_windows, rid)
        # 处置类自带词只作用于命中所在分句
        self.assertIn("clause", rules["SOE-001"].exempt_windows)
        self.assertEqual(rules["SOE-011"].prefix_window, 16)


class SharedModuleTest(unittest.TestCase):
    """缺少共享模块或数据文件，或数据损坏：命令行退出 2，不静默降级。"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="soe_shared_test_"))
        self.scripts = self.tmp / "gongwen-soe" / "scripts"
        self.scripts.mkdir(parents=True)
        for name in ("soe_check.py", "soe_rules.json", "gw_names.py", "gw_names.json", "gw_clause.py"):
            shutil.copy2(SCRIPTS_DIR / name, self.scripts / name)
        self.doc = self.tmp / "文.txt"
        self.doc.write_text("给予王建国同志党内警告处分。", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args: str):
        env = dict(__import__("os").environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        proc = subprocess.run([sys.executable, "-B", str(self.scripts / "soe_check.py"), *args],
                              capture_output=True, env=env, cwd=str(self.tmp))
        return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")

    def test_intact_copy_works(self) -> None:
        code, out, _err = self.run_cli(str(self.doc), "--json")
        self.assertEqual(code, 0)
        self.assertIn("SOE-022", out)
        self.assertNotIn("王建国", out)

    def test_missing_files_exit_2(self) -> None:
        for name in ("gw_names.py", "gw_names.json", "gw_clause.py"):
            with self.subTest(missing=name):
                (self.scripts / name).rename(self.scripts / (name + ".bak"))
                try:
                    code, out, err = self.run_cli(str(self.doc), "--json")
                    self.assertEqual(code, 2, out + err)
                    self.assertIn("错误", err)
                    self.assertNotIn("SOE-", out)
                    self.assertEqual(self.run_cli("--list-rules")[0], 2)
                finally:
                    (self.scripts / (name + ".bak")).rename(self.scripts / name)

    def test_corrupt_data_exit_2(self) -> None:
        (self.scripts / "gw_names.json").write_text("{坏的", encoding="utf-8")
        code, out, err = self.run_cli(str(self.doc), "--json")
        self.assertEqual(code, 2)
        self.assertIn("姓名数据文件", err)

    def test_corrupt_module_exit_2(self) -> None:
        (self.scripts / "gw_clause.py").write_text("raise RuntimeError('坏的')\n", encoding="utf-8")
        code, _out, err = self.run_cli(str(self.doc), "--json")
        self.assertEqual(code, 2)
        self.assertIn("gw_clause", err)


class CliTest(SoeCheckBase):

    def test_json_output_and_strict(self) -> None:
        path = next(SPECIMENS.glob("必错-议题材料.*"))
        code, out, _err = self.run_main(str(path), "--type", "议题材料", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        for key in ("file", "doc_type", "char_count", "summary", "issues"):
            self.assertIn(key, data)
        code, _out, _err = self.run_main(str(path), "--type", "议题材料", "--strict")
        self.assertEqual(code, 1)

    def test_strict_pass(self) -> None:
        path = next(SPECIMENS.glob("必过-议题材料.*"))
        code, out, _err = self.run_main(str(path), "--type", "议题材料", "--strict")
        self.assertEqual(code, 0)
        self.assertIn("未发现行业规则问题", out)

    def test_as_of_option(self) -> None:
        path = next(SPECIMENS.glob("必错-改革台账.*"))
        code, out, _err = self.run_main(str(path), "--type", "改革台账", "--as-of", "2026-01-01", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["as_of"], "2026-01-01")
        self.assertFalse(any("已过" in i["message"] for i in data["issues"]))
        code, _out, _err = self.run_main(str(path), "--type", "改革台账", "--as-of", "2026/01/01")
        self.assertEqual(code, 2)

    def test_input_errors(self) -> None:
        code, _out, err = self.run_main(str(self.tmp / "不存在.txt"))
        self.assertEqual(code, 2)
        self.assertIn("文件不存在", err)
        bad = self.tmp / "a.pdf"
        bad.write_text("x", encoding="utf-8")
        self.assertEqual(self.run_main(str(bad))[0], 2)
        good = self.tmp / "a.txt"
        good.write_text("正文", encoding="utf-8")
        self.assertEqual(self.run_main(str(good), "--type", "不存在的类型")[0], 2)
        self.assertEqual(self.run_main()[0], 2)

    def test_list_rules_and_help(self) -> None:
        code, out, _err = self.run_main("--list-rules")
        self.assertEqual(code, 0)
        self.assertIn("SOE-104", out)
        self.assertIn("SOE-029", out)
        self.assertEqual(sum(1 for line in out.splitlines() if line.startswith("SOE-")), 40)  # 29 条正则 + 11 项函数检查
        code, out, _err = self.run_main("--help")
        self.assertEqual(code, 0)
        self.assertIn("用法", out)

    def test_gb18030_input(self) -> None:
        path = self.tmp / "gbk.txt"
        path.write_bytes("项目已先行开工。".encode("gb18030"))
        code, out, _err = self.run_main(str(path), "--json")
        self.assertEqual(code, 0)
        self.assertIn("SOE-001", out)

    def test_does_not_write_files(self) -> None:
        path = self.tmp / "a.txt"
        path.write_text("项目已先行开工。", encoding="utf-8")
        before = sorted(p.name for p in self.tmp.iterdir())
        self.run_main(str(path), "--json")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), before)


class EvalIsolationTest(unittest.TestCase):
    """评测材料中的关键数字和日期不得出现在 SKILL.md 和 references/ 中，避免模板示例替评测作答。"""

    TOKEN_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:亿元|万元)|(?<![\d.])\d+\.\d+(?![\d.])|\d+(?:\.\d+)?\s*[%％]"
                          r"|\d{1,2}月\d{1,2}日|同意\s*\d+\s*票|\d+\s*天|\d+\s*名")
    # 通用的期末日期、交易所披露截止日和工具阈值，不算重合
    ALLOWED = {"3月31日", "6月30日", "9月30日", "12月31日", "4月30日", "1月1日", "30%", "100%"}

    @staticmethod
    def _norm(text: str) -> str:
        return re.sub(r"\s", "", text).replace("％", "%")

    def _eval_tokens(self) -> dict:
        texts = [(f.name, f.read_text(encoding="utf-8")) for f in (SKILL_DIR / "evals" / "files").iterdir() if f.is_file()]
        data = json.loads((SKILL_DIR / "evals" / "evals.json").read_text(encoding="utf-8"))
        texts += [(f"evals.json 第{e['id']}条", e["prompt"]) for e in data["evals"]]
        tokens: dict = {}
        for name, text in texts:
            for m in self.TOKEN_RE.finditer(text):
                token = self._norm(m.group(0))
                if token not in self.ALLOWED:
                    tokens.setdefault(token, name)
        return tokens

    def test_eval_data_not_in_references(self) -> None:
        tokens = self._eval_tokens()
        self.assertTrue(tokens)
        files = [SKILL_DIR / "SKILL.md"] + [p for p in (SKILL_DIR / "references").rglob("*.md") if "_shared" not in p.parts]
        found = []
        for path in files:
            text = self._norm(path.read_text(encoding="utf-8"))
            for token, source in tokens.items():
                for m in re.finditer(re.escape(token), text):
                    s, e = m.start(), m.end()
                    if s and (text[s - 1].isdigit() or text[s - 1] == "."):
                        continue
                    if token[-1].isdigit() and e < len(text) and (text[e].isdigit() or text[e] == "."):
                        continue
                    found.append(f"{path.relative_to(SKILL_DIR)}：{token}（来自 {source}）")
                    break
        self.assertEqual(found, [])


class SharedFrameAndChainTest(SoeCheckBase):
    """suffix 型处分框架的左边界由共享模块内置；顿号并列的禁止类豁免；如实声明的统一口径。"""

    def only(self, text: str, rid: str, doc_type="议题材料"):
        return [(i["id"], i["level"]) for i in self.check(text, doc_type)["issues"] if i["id"] == rid]

    def test_frame_left_boundary_is_in_shared_module(self) -> None:
        rule = {r.id: r for r in self.ruleset.rules}["SOE-022"]
        self.assertFalse(hasattr(rule, "name_left_ok"), "左边界已由共享模块内置，引擎不再自带 name_left_ok")
        self.assertTrue(any(a.left_ok is not None for a in rule.anchors))
        for text in ("邓小平理论学习不力的支部受到警告处分", "王府井百货受到警告", "钱江新城项目部被诫勉",
                     "邓小平理论受到警告处分"):
            with self.subTest(text=text):
                self.assertEqual(self.only(text, "SOE-022", "纪要"), [])
        for text in ("会议研究决定王强被开除党籍", "总经理王强同志受到警告处分", "时任董事长周杰受到记过处分"):
            with self.subTest(text=text):
                self.assertEqual(self.only(text, "SOE-022", "纪要"), [("SOE-022", "P0")])

    def test_prohibit_across_dun_hao(self) -> None:
        self.assertEqual(self.only("要杜绝先行开工、先行签约等现象。", "SOE-001"), [])
        self.assertEqual(self.only("严禁先行开工、先行签约、先行付款。", "SOE-001"), [])
        # 逗号分句仍各自独立
        self.assertEqual(self.only("要杜绝违规问题，项目已于9月先行开工，现提请董事会审议。", "SOE-001"), [("SOE-001", "P0")])

    def test_declared_with_disposal_word_is_p1(self) -> None:
        text = "项目已于9月先行开工，该做法违反了投资管理规定，属于程序倒置，现如实报告。"
        self.assertEqual(self.only(text, "SOE-001"), [("SOE-001", "P1")])
        self.assertEqual(self.only("巡察反馈的先行开工问题已于9月整改到位。", "SOE-001"), [])
        self.assertEqual(self.only("项目已于9月先行开工，该做法违反了投资管理规定，现提请董事会追认，现如实报告。", "SOE-001"),
                         [("SOE-001", "P0")])

    def test_no_document_level_downgrade(self) -> None:
        """收缩：不再有全文级降级。声明只看同一句和紧邻的前、后一句；隔开的重复写法按原级别（正则 P0）。"""
        text = ("一、情况\n项目已于9月先行开工。\n二、进展\n该项目先行开工后累计完成形象进度25%，已于10月先行签约。\n"
                "三、说明\n以上程序倒置情况，如实报告。")
        levels = [lv for _i, lv in self.only(text, "SOE-001")]
        self.assertGreaterEqual(len(levels), 2)
        self.assertTrue(all(lv == "P0" for lv in levels), levels)
        # 声明紧邻（下一行）：该处降 P1
        levels = [lv for _i, lv in self.only("项目已于9月先行开工。\n以上程序倒置情况，如实报告。", "SOE-001")]
        self.assertEqual(levels, ["P1"])

    def test_soe024_staff_meeting_window(self) -> None:
        self.assertIn("SOE-024", ids_of(self.check("职工安置方案已听取职工意见，拟提交董事会审议。", "议题材料")))
        self.assertNotIn("SOE-024", ids_of(self.check("职工安置方案已听取职工意见，拟提交职代会审议。", "议题材料")))
        self.assertNotIn("SOE-024", ids_of(self.check("职工安置方案已听取职工意见，拟提交董事会和职工代表大会审议。", "议题材料")))
        self.assertNotIn("SOE-024", ids_of(self.check("职工安置方案已听取职工意见，待提交职工大会表决。", "议题材料")))
        # 窗口只有 12 字：提交之后很远才提职代会，不算
        self.assertIn("SOE-024", ids_of(self.check("职工安置方案已听取职工意见，拟提交董事会审议，各部门做好准备工作的同时另行通知职代会代表。", "议题材料")))

    def test_soe111_negated_trigger(self) -> None:
        for text in ("本项目不涉及职工安置。", "本方案不含薪酬调整。", "本次改革没有职工分流。", "本项目未涉及职工切身利益。",
                     "不涉及职工切身利益。"):
            with self.subTest(text=text):
                self.assertNotIn("SOE-111", ids_of(self.check(text, "议题材料")))
        for text in ("本项目涉及职工安置。", "拟调整薪酬方案。", "本项目涉及职工切身利益，不涉及其他。"):
            with self.subTest(text=text):
                self.assertIn("SOE-111", ids_of(self.check(text, "议题材料")))
        # 触发词前 8 字之外的“无”不算否定
        self.assertIn("SOE-111", ids_of(self.check("该公司无重大风险，为确保平稳过渡，拟定职工安置方案并组织实施。", "议题材料")))


@unittest.skipUnless(HAS_DOCX, "未安装 python-docx")
class DocxTest(SoeCheckBase):

    def test_docx_ledger_table(self) -> None:
        import docx as _docx  # type: ignore
        document = _docx.Document()
        document.add_paragraph("某集团改革任务台账")
        table = document.add_table(rows=3, cols=5)
        rows = [("序号", "改革任务", "完成时限", "状态", "佐证材料"),
                ("1", "完善授权制度", "2026年6月30日", "按计划推进", "无"),
                ("2", "专业化整合", "2026年12月", "已完成", "无")]
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                table.cell(r, c).text = value
        document.add_paragraph("【起草说明】")
        document.add_paragraph("项目已先行开工。")
        path = self.tmp / "台账.docx"
        document.save(str(path))
        result = sc.check_file(path, "改革台账", ruleset=self.ruleset, as_of=AS_OF)
        messages = " ".join(i["message"] for i in result["issues"])
        self.assertIn("已过", messages)
        self.assertIn("没有佐证材料", messages)
        self.assertNotIn("SOE-001", ids_of(result))


class LaterDisposalDowngradeTest(SoeCheckBase):
    """A6：命中之后的后续分句里有针对该做法的处置词，P0 降为 P1（不是豁免，仍报出要人看）；后续词要过语境检查。"""

    def levels(self, text: str, rid: str, doc_type="议题材料"):
        return [i["level"] for i in self.check(text, doc_type)["issues"] if i["id"] == rid]

    def test_split_with_later_disposal_is_p1(self) -> None:
        text = "有部门提出将项目拆分为两个子项目分别报批，经法务合规部审查认为该做法违反公司投资管理制度，未予采纳。"
        self.assertEqual(self.levels(text, "SOE-029"), ["P1"])
        hit = next(i for i in self.check(text, "议题材料")["issues"] if i["id"] == "SOE-029")
        self.assertIn("可忽略本条", hit["suggestion"])

    def test_later_words_failing_context_check_stay_p0(self) -> None:
        for tail in ("建议避免违规。", "此前已有单位完成整改。", "其他单位也违规这样做。", "确保不违规。"):
            with self.subTest(tail=tail):
                text = "有部门提出将项目拆分为两个子项目分别报批，" + tail
                self.assertEqual(self.levels(text, "SOE-029"), ["P0"])

    def test_inversion_with_ratification_stays_p0(self) -> None:
        text = "项目已于9月先行开工，该做法违反了投资管理规定，现提请董事会追认，现如实报告。"
        self.assertEqual(self.levels(text, "SOE-001"), ["P0"])

    def test_declaration_requires_direct_assertion(self) -> None:
        for text in ("该项目已先行开工，是否属于程序倒置请会议研究。", "该项目已先行开工，属于程序倒置的说法不准确。",
                     "该项目已先行开工，有人认为属于程序倒置，我们认为不是。", "该项目已先行开工，难以认定属于程序倒置。",
                     "其他单位因属于程序倒置被通报。该项目已先行开工，现提请审议。", "该项目已先行开工，现提请审议。如属于程序倒置，按规定处理。"):
            with self.subTest(text=text):
                self.assertEqual(self.levels(text, "SOE-001"), ["P0"])
        for text in ("项目已于9月先行开工，属于程序倒置，现如实报告。", "上述事项属于程序倒置。该项目已先行开工，现提请审议。"):
            with self.subTest(text=text):
                self.assertEqual(self.levels(text, "SOE-001"), ["P1"])
        # 声明之后隔一句才出现补报：仍是 P0
        self.assertEqual(self.levels("该项目已先行开工，现提请审议。属于程序倒置。下一步补报审批。", "SOE-001"), ["P0"])

    def test_names_chain_and_connector(self) -> None:
        for text in ("对相关责任人白云、陆国华分别给予诫勉谈话。", "对相关责任人程鹏、邓景行分别给予诫勉谈话。",
                     "给予程鹏和邓景行同志党内警告处分。", "经研究，拟推荐人选：高峰、熊建伟。"):
            with self.subTest(text=text):
                result = self.check(text, "纪要")
                dump = "".join((i.get("excerpt") or "") + (i.get("context") or "") for i in result["issues"])
                for name in ("白云", "陆国华", "邓景行", "程鹏", "高峰", "熊建伟"):
                    self.assertNotIn(name, dump)
                self.assertTrue([i for i in result["issues"] if i["id"] in ("SOE-022", "SOE-023")])


if __name__ == "__main__":
    unittest.main()
