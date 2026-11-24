# -*- coding: utf-8 -*-
"""skills/gongwen-hospital/scripts/hospital_check.py 的单元测试。

运行：python -m unittest discover -s tests/hospital -t .
必错标本和必过标本在 tests/hospital/specimens/ 下。
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "gongwen-hospital" / "scripts"
SPECIMENS = Path(__file__).resolve().parent / "specimens"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import hospital_check as hc  # noqa: E402

try:
    import docx  # type: ignore  # noqa: F401
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False


def ids_of(result) -> list:
    return [issue["id"] for issue in result["issues"]]


class HospitalCheckBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.ruleset = hc.load_rules()

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hospital_check_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, text: str, doc_type=None, external: bool = False):
        return hc.check_text(text, doc_type, external, ruleset=self.ruleset)

    def run_main(self, *args: str):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = hc.main(list(args))
        return code, out.getvalue(), err.getvalue()


class RuleFileTest(HospitalCheckBase):
    """规则文件本身的完整性。"""

    def test_every_rule_has_examples_and_basis(self) -> None:
        for rule in self.ruleset.rules:
            with self.subTest(rule=rule.id):
                self.assertTrue(rule.hit_examples, "每条正则规则至少要有一个命中示例")
                self.assertTrue(rule.miss_examples, "每条正则规则至少要有一个不命中示例")
                self.assertTrue(rule.basis)
        for rule in self.ruleset.procedural:
            self.assertTrue(rule.basis)

    def test_rule_examples(self) -> None:
        for rule in self.ruleset.rules:
            doc_type = rule.types[0] if rule.types else None
            for example in rule.hit_examples:
                with self.subTest(rule=rule.id, hit=example):
                    self.assertIn(rule.id, ids_of(self.check(example, doc_type)))
            for example in rule.miss_examples:
                with self.subTest(rule=rule.id, miss=example):
                    self.assertNotIn(rule.id, ids_of(self.check(example, doc_type)))

    def test_bad_rule_files_raise(self) -> None:
        cases = {
            "not_json.json": "{",
            "bad_level.json": json.dumps({"types": [], "rules": [
                {"id": "X-1", "category": "c", "gate": "g", "level": "P9", "message": "m",
                 "basis": "b", "pattern": "a"}]}),
            "bad_regex.json": json.dumps({"types": [], "rules": [
                {"id": "X-1", "category": "c", "gate": "g", "level": "P1", "message": "m",
                 "basis": "b", "pattern": "("}]}),
            "dup_id.json": json.dumps({"types": [], "rules": [
                {"id": "X-1", "category": "c", "gate": "g", "level": "P1", "message": "m",
                 "basis": "b", "pattern": "a"},
                {"id": "X-1", "category": "c", "gate": "g", "level": "P1", "message": "m",
                 "basis": "b", "pattern": "b"}]}),
            "unknown_type.json": json.dumps({"types": ["RCA"], "rules": [
                {"id": "X-1", "category": "c", "gate": "g", "level": "P1", "message": "m",
                 "basis": "b", "pattern": "a", "types": ["讲话稿"]}]}),
        }
        for name, content in cases.items():
            path = self.tmp / name
            path.write_text(content, encoding="utf-8")
            with self.subTest(case=name):
                with self.assertRaises(hc.InputError):
                    hc.load_rules(path)
        with self.assertRaises(hc.InputError):
            hc.load_rules(self.tmp / "missing.json")


class SpecimenTest(HospitalCheckBase):
    """必错标本必须报出预期问题，必过标本必须零问题。"""

    def test_must_fail_specimen(self) -> None:
        result = hc.check_file(SPECIMENS / "必错-根因分析.txt", "RCA", ruleset=self.ruleset)
        found = ids_of(result)
        for rid in ("HOS-002", "HOS-003", "HOS-004", "HOS-006", "HOS-018", "HOS-019", "HOS-020"):
            with self.subTest(rule=rid):
                self.assertIn(rid, found)
        # 【起草说明】之后的“责任心不强”不参与检查
        self.assertEqual(found.count("HOS-018"), 1)

    def test_must_fail_quality_specimen(self) -> None:
        """质量分析必错标本：指标名称、百分点、CMI 百分号、俗称“国考”、疗效保证、党政联席会议都要查出。"""
        result = hc.check_file(SPECIMENS / "必错-质量分析.txt", "质量分析", ruleset=self.ruleset)
        found = ids_of(result)
        expected = ("HOS-001", "HOS-003", "HOS-004", "HOS-006", "HOS-007", "HOS-008", "HOS-009",
                    "HOS-010", "HOS-011", "HOS-012", "HOS-013", "HOS-014", "HOS-015")
        for rid in expected:
            with self.subTest(rule=rid):
                self.assertIn(rid, found)
        # RCA 专用规则不适用于质量分析
        for rid in ("HOS-018", "HOS-019", "HOS-020"):
            self.assertNotIn(rid, found)
        self.assertEqual(result["summary"]["P1"], 5)
        self.assertEqual(result["summary"]["P0"], 0)
        # 【起草说明】之后的“大手术比例”“抗生素使用强度”不参与检查
        self.assertEqual(found.count("HOS-008"), 1)
        self.assertEqual(found.count("HOS-010"), 1)

    def test_must_fail_quality_specimen_external_escalates(self) -> None:
        """同一份标本按对外宣传检查，保证治愈升为 P0。"""
        result = hc.check_file(SPECIMENS / "必错-质量分析.txt", "对外宣传", ruleset=self.ruleset)
        self.assertGreaterEqual(result["summary"]["P0"], 1)
        self.assertIn("HOS-001", ids_of(result))

    def test_must_fail_quality_specimen_without_type(self) -> None:
        """不指定文书类型时，“国考”俗称不查（HOS-015 只查正式文书），其余照查。"""
        result = hc.check_file(SPECIMENS / "必错-质量分析.txt", None, ruleset=self.ruleset)
        found = ids_of(result)
        self.assertNotIn("HOS-015", found)
        for rid in ("HOS-006", "HOS-007", "HOS-008", "HOS-004"):
            self.assertIn(rid, found)

    def test_must_fail_specimen_without_type_skips_rca_rules(self) -> None:
        result = hc.check_file(SPECIMENS / "必错-根因分析.txt", None, ruleset=self.ruleset)
        found = ids_of(result)
        for rid in ("HOS-018", "HOS-019", "HOS-020"):
            self.assertNotIn(rid, found)
        self.assertIn("HOS-004", found)
        self.assertTrue(any("未指定 --type" in note for note in result["notes"]))

    def test_extended_six_doc_type_specimens(self) -> None:
        """补齐其余 6 类医院专用文书的必过/必错标本测试，实现 8 类文书全覆盖。"""
        cases = [
            ("等级评审", "必过-等级评审.txt", "必错-等级评审.txt", ("HOS-003", "HOS-008", "HOS-009", "HOS-010", "HOS-016", "HOS-037", "HOS-039")),
            ("绩效分析", "必过-绩效分析.txt", "必错-绩效分析.txt", ("HOS-006", "HOS-015", "HOS-021", "HOS-023", "HOS-033")),
            ("述职", "必过-述职.txt", "必错-述职.txt", ("HOS-002", "HOS-003", "HOS-007", "HOS-009", "HOS-036")),
            ("议题", "必过-议题.txt", "必错-议题.txt", ("HOS-004", "HOS-005", "HOS-034", "HOS-035")),
            ("行风", "必过-行风.txt", "必错-行风.txt", ("HOS-003", "HOS-017")),
            ("整改", "必过-整改.txt", "必错-整改.txt", ("HOS-010", "HOS-028")),
        ]
        for doc_type, pass_name, fail_name, expected_ids in cases:
            with self.subTest(doc_type=doc_type, kind="pass"):
                res_pass = hc.check_file(SPECIMENS / pass_name, doc_type, ruleset=self.ruleset)
                self.assertEqual(res_pass["issues"], [], f"{pass_name} 不应报错：{res_pass['issues']}")
            with self.subTest(doc_type=doc_type, kind="fail"):
                res_fail = hc.check_file(SPECIMENS / fail_name, doc_type, ruleset=self.ruleset)
                found = ids_of(res_fail)
                for rid in expected_ids:
                    self.assertIn(rid, found, f"{fail_name} 应命中 {rid}，实际：{found}")

    def test_privacy_specimens(self) -> None:
        """隐私标本：必错按 RCA 报 HOS-030/031/032，--strict 退出 1；必过零问题。"""
        res_fail = hc.check_file(SPECIMENS / "必错-隐私.txt", "RCA", ruleset=self.ruleset)
        found = ids_of(res_fail)
        for rid in ("HOS-030", "HOS-031", "HOS-032"):
            self.assertIn(rid, found)
        self.assertGreaterEqual(res_fail["summary"]["P0"], 3)
        code, _out, _err = self.run_main(str(SPECIMENS / "必错-隐私.txt"), "--type", "RCA", "--strict")
        self.assertEqual(code, 1)
        res_pass = hc.check_file(SPECIMENS / "必过-隐私.txt", "RCA", ruleset=self.ruleset)
        self.assertEqual(res_pass["issues"], [], res_pass["issues"])

    def test_external_specimens(self) -> None:
        res_fail = hc.check_file(SPECIMENS / "必错-对外宣传.txt", "对外宣传", ruleset=self.ruleset)
        levels = {i["id"]: i["level"] for i in res_fail["issues"]}
        self.assertEqual(levels.get("HOS-002"), "P0")
        self.assertEqual(levels.get("HOS-003"), "P0")
        self.assertIn("HOS-038", levels)
        res_pass = hc.check_file(SPECIMENS / "必过-对外宣传.txt", "对外宣传", ruleset=self.ruleset)
        self.assertEqual(res_pass["issues"], [], res_pass["issues"])

    def test_all_must_pass_specimens_clean_any_mode(self) -> None:
        """所有必过标本按本类型、对外宣传、不指定类型三种方式检查都应零问题。"""
        own = {"质量分析": "质量分析", "根因分析": "RCA", "等级评审": "等级评审", "绩效分析": "绩效分析",
               "述职": "述职", "议题": "议题", "行风": "行风", "整改": "整改",
               "隐私": "RCA", "对外宣传": "对外宣传"}
        for name, doc_type in own.items():
            for mode in (doc_type, "对外宣传", None):
                with self.subTest(specimen=name, mode=mode):
                    result = hc.check_file(SPECIMENS / f"必过-{name}.txt", mode, ruleset=self.ruleset)
                    self.assertEqual(result["issues"], [], result["issues"])

    def test_must_pass_specimen(self) -> None:
        for doc_type in ("质量分析", "绩效分析", None):
            with self.subTest(doc_type=doc_type):
                result = hc.check_file(SPECIMENS / "必过-质量分析.txt", doc_type, ruleset=self.ruleset)
                self.assertEqual(result["issues"], [], result["issues"])
                self.assertEqual({lv: result["summary"][lv] for lv in hc.LEVELS},
                                 {"P0": 0, "P1": 0, "P2": 0})
                self.assertEqual(result["summary"]["markers"], {"待补": 3, "待核实": 0})

    def test_must_pass_rca_specimen(self) -> None:
        """规范的根因分析：顿号连接的指标、“未给予处分”、起草说明中的处理意见都不报。"""
        result = hc.check_file(SPECIMENS / "必过-根因分析.txt", "RCA", ruleset=self.ruleset)
        self.assertEqual(result["issues"], [], result["issues"])

    def test_must_pass_specimen_as_external(self) -> None:
        result = hc.check_file(SPECIMENS / "必过-质量分析.txt", "对外宣传", ruleset=self.ruleset)
        self.assertEqual(result["issues"], [])
        self.assertTrue(result["external"])


class BehaviourTest(HospitalCheckBase):

    def test_external_escalates_levels(self) -> None:
        text = "该技术可保证治愈。手术成功率达100%。达到国内领先水平。"
        internal = {i["id"]: i["level"] for i in self.check(text)["issues"]}
        external = {i["id"]: i["level"] for i in self.check(text, external=True)["issues"]}
        by_type = {i["id"]: i["level"] for i in self.check(text, "对外宣传")["issues"]}
        self.assertEqual(internal, {"HOS-001": "P1", "HOS-002": "P2", "HOS-003": "P2"})
        self.assertEqual(external, {"HOS-001": "P0", "HOS-002": "P0", "HOS-003": "P0"})
        self.assertEqual(by_type, external)

    def test_superlative_exempt_with_source(self) -> None:
        """HOS-003：有鉴定、评价等出处时豁免；没有出处的对外宣传报 P0。"""
        bare = {i["id"]: i["level"] for i in self.check("该技术达到国内领先水平。", "对外宣传")["issues"]}
        self.assertEqual(bare.get("HOS-003"), "P0")
        self.assertNotIn("HOS-003", ids_of(self.check("经中华医学会鉴定，该技术达到国内领先水平。", "对外宣传")))
        self.assertNotIn("HOS-003", ids_of(self.check("据2026年复旦版榜单，我院排名全国第一。", "对外宣传")))

    def test_procedure_inversion_exempt_when_declared(self) -> None:
        self.assertIn("HOS-034", ids_of(self.check("该设备已于9月先行采购，现提请会议审议。", "议题")))
        self.assertNotIn("HOS-034", ids_of(self.check("该设备已于9月先行采购，属于程序倒置，现如实报告。", "议题")))
        # 只在议题中检查
        self.assertNotIn("HOS-034", ids_of(self.check("该设备已于9月先行采购。", "质量分析")))

    def test_prerequisite_confirmation_procedural(self) -> None:
        """HOS-039：写了“未发生前置要求所列情形”而全文无逐条确认时报；否定的确认不算。"""
        for text in ("评审周期内未发生前置要求所列情形。",
                     "前置要求自查结果：均未发生。",
                     "评审周期内未发生前置要求所列情形，尚未经院领导确认。"):
            with self.subTest(hit=text):
                self.assertIn("HOS-039", ids_of(self.check(text, "等级评审")))
        for text in ("经医院逐条确认，评审周期内未发生前置要求所列情形。",
                     "评审周期内未发生前置要求所列情形。【待补：前置要求确认结论】"):
            with self.subTest(miss=text):
                self.assertNotIn("HOS-039", ids_of(self.check(text, "等级评审")))
        self.assertNotIn("HOS-039", ids_of(self.check("评审周期内未发生前置要求所列情形。", "质量分析")))

    def test_privacy_excerpt_masked(self) -> None:
        """隐私类规则命中时 excerpt 遮蔽、不输出 context；JSON 与文本输出都不含真实姓名。"""
        text = "患者姓名：李建国。当班护士李娜未执行双人核对。患者张某（床号12）跌倒。"
        result = self.check(text, "RCA")
        privacy = [i for i in result["issues"] if i["id"] in ("HOS-030", "HOS-031", "HOS-032")]
        self.assertEqual({i["id"] for i in privacy}, {"HOS-030", "HOS-031", "HOS-032"})
        for issue in privacy:
            self.assertTrue(issue["excerpt"].startswith("〔已遮蔽，共"), issue["excerpt"])
            self.assertNotIn("context", issue)
        dumped = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("李建国", dumped)
        self.assertNotIn("李娜", dumped)
        path = self.tmp / "隐私.txt"
        path.write_text(text, encoding="utf-8")
        for extra in ((), ("--json",)):
            code, out, _err = self.run_main(str(path), "--type", "RCA", *extra)
            self.assertEqual(code, 0)
            self.assertNotIn("李建国", out)
            self.assertNotIn("李娜", out)
            self.assertIn("已遮蔽", out)

    def test_privacy_name_not_leaked_via_other_rules(self) -> None:
        """同一行既命中隐私规则又命中其他规则时，其他规则的 excerpt、context 也遮蔽姓名。"""
        text = "12床张三因跌倒骨折，责任心不强。"
        result = self.check(text, "RCA")
        found = ids_of(result)
        self.assertIn("HOS-030", found)
        self.assertIn("HOS-018", found)
        dumped = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("张三", dumped)
        other = [i for i in result["issues"] if i["id"] == "HOS-018"][0]
        self.assertIn("〔已遮蔽〕", other.get("context", "") + other["excerpt"])
        path = self.tmp / "泄露.txt"
        path.write_text(text, encoding="utf-8")
        for extra in ((), ("--json",)):
            code, out, _err = self.run_main(str(path), "--type", "RCA", *extra)
            self.assertEqual(code, 0)
            self.assertNotIn("张三", out)

    def test_privacy_age_no_longer_ceded(self) -> None:
        """实名加性别、年龄的写法由隐私规则报 P0；“张某”式代称不报。"""
        self.assertIn("HOS-031", ids_of(self.check("患者李建国，男，56岁。")))
        self.assertIn("HOS-030", ids_of(self.check("15床患者刘建国，男，56岁，因跌倒入院。")))
        self.assertNotIn("HOS-031", ids_of(self.check("患者张某，男，56岁。")))

    def test_prerequisite_confirmed_by_verification(self) -> None:
        base = "评审周期内未发生前置要求所列情形"
        self.assertNotIn("HOS-039", ids_of(self.check(base + "，经院领导逐条核实。", "等级评审")))
        self.assertIn("HOS-039", ids_of(self.check(base + "，未经院领导核实。", "等级评审")))
        self.assertIn("HOS-039", ids_of(self.check("评审周期内全部符合前置要求。", "等级评审")))

    def test_surgery_names_with_genzhi_pass(self) -> None:
        text = "完成胃癌根治术86例，乳腺癌改良根治手术40例，开展根治性放疗12例。"
        self.assertNotIn("HOS-002", ids_of(self.check(text, external=True)))

    def test_joint_meeting_exempt_in_prohibition(self) -> None:
        self.assertNotIn("HOS-004", ids_of(self.check("医院严格执行议事规则，不得以党政联席会议代替党委会议研究决定重大问题。")))
        self.assertIn("HOS-004", ids_of(self.check("经党政联席会议研究，同意调整绩效方案。")))

    def test_procedural_sanzhongyida(self) -> None:
        missing = "议题名称：购置数字减影血管造影机\n本项目属于“三重一大”事项，预算1200万元。经院长办公会议讨论通过。"
        complete = missing + "\n拟提交党委会议研究决定。"
        self.assertIn("HOS-005", ids_of(self.check(missing, "议题")))
        self.assertNotIn("HOS-005", ids_of(self.check(complete, "议题")))
        # 非议题文书不做这项检查
        self.assertNotIn("HOS-005", ids_of(self.check(missing, "质量分析")))
        issue = next(i for i in self.check(missing, "议题")["issues"] if i["id"] == "HOS-005")
        self.assertEqual(issue["line"], 2)
        self.assertEqual(issue["level"], "P1")

    def test_procedural_negated_party_meeting(self) -> None:
        """“尚未提交党委会议”“未经党委会议”不算已有党委会议程序。"""
        base = "本项目属于“三重一大”事项，预算1200万元。"
        for text in ("目前尚未提交党委会议研究。",
                     "未经党委会议研究，已签订意向书。",
                     "该事项尚未提交医院党委会议。",
                     "此前没有上党委会研究。"):
            with self.subTest(negated=text):
                self.assertIn("HOS-005", ids_of(self.check(base + text, "议题")))
        for text in ("经院长办公会议讨论通过后，提交党委会议研究决定。",
                     "尚未提交党委会议研究，拟于11月提交党委会议研究决定。",
                     "未通过的事项不再上会，本事项拟提交党委会议研究决定。"):
            with self.subTest(satisfied=text):
                self.assertNotIn("HOS-005", ids_of(self.check(base + text, "议题")))

    def test_index_vs_percentage_points(self) -> None:
        self.assertIn("HOS-006", ids_of(self.check("时间消耗指数下降0.05个百分点。")))
        self.assertNotIn("HOS-006", ids_of(self.check("时间消耗指数由1.05下降到1.00，出院患者手术占比提高2.1个百分点。")))
        self.assertIn("HOS-007", ids_of(self.check("科室CMI：1.25%")))

    def test_index_rule_does_not_cross_enumeration(self) -> None:
        """顿号并列的另一个比率指标用百分点是对的，不能误报。"""
        for text in ("平均住院日缩短0.4天、四级手术比例提高1.2个百分点",
                     "平均住院日缩短0.4天、出院患者手术占比提高2.1个百分点",
                     "RW值高的病组占比提高3.2个百分点",
                     "CMI为0.94，微创手术占比提高1.9个百分点"):
            with self.subTest(text=text):
                self.assertNotIn("HOS-006", ids_of(self.check(text)))
        self.assertIn("HOS-006", ids_of(self.check("平均住院日较上年缩短0.4个百分点、手术占比提高1.2个百分点")))

    def test_index_rule_crosses_comma(self) -> None:
        """最常见的错法带逗号：“CMI为0.94，较上年提高0.05个百分点”。"""
        for text in ("CMI为0.94，较上年提高0.05个百分点",
                     "病例组合指数（CMI）为1.08，同比提高0.06个百分点",
                     "平均住院日为7.6天，较上年同期缩短0.4个百分点",
                     "CMI由1.02提高到1.08，提高了6个百分点",
                     "（一）医疗质量。CMI为1.05，较上年提高0.06个百分点。"):
            with self.subTest(hit=text):
                self.assertIn("HOS-006", ids_of(self.check(text)))
        for text in ("CMI为0.94，较上年提高0.03；手术患者并发症发生率下降0.1个百分点",
                     "CMI为1.08，门诊次均费用增幅提高2.1个百分点",
                     "平均住院日为7.6天，病床使用率下降1.2个百分点",
                     "CMI增幅较上年提高0.5个百分点"):
            with self.subTest(miss=text):
                self.assertNotIn("HOS-006", ids_of(self.check(text)))

    def test_eval7_draft_reports_index_points(self) -> None:
        """评测 7 的初稿中“CMI为1.05，较上年提高0.06个百分点”必须查出。"""
        draft = REPO_ROOT / "skills" / "gongwen-hospital" / "evals" / "files" / "某医院2025年度绩效监测分析初稿.txt"
        result = hc.check_file(draft, "绩效分析", ruleset=self.ruleset)
        self.assertIn("HOS-006", ids_of(result))
        self.assertIn("HOS-015", ids_of(result))

    def test_guokao_not_in_other_words(self) -> None:
        for text in ("按全国考核要求按时上报数据。", "赴中国考察学习。", "出国考察3人次。"):
            with self.subTest(text=text):
                self.assertNotIn("HOS-015", ids_of(self.check(text, "绩效分析")))
        self.assertIn("HOS-015", ids_of(self.check("国考评价结果为A。", "绩效分析")))

    def test_efficacy_hundred_percent_in_words(self) -> None:
        self.assertIn("HOS-002", ids_of(self.check("手术成功率达到百分之百。")))

    def test_rca_punishment_variants(self) -> None:
        """扣绩效、通报批评、受到处分都算写入处理；否定说法不报。"""
        for text in ("扣当事护士当月绩效500元，全科通报批评。",
                     "科室意见：扣当月绩效500元。",
                     "当事护士已受到处分。",
                     "对当事人予以经济处罚。"):
            with self.subTest(hit=text):
                self.assertIn("HOS-020", ids_of(self.check(text, "RCA")))
        for text in ("均已妥善处理，未给予处分",
                     "主动上报的不予处分，不扣绩效，不通报批评",
                     "处理意见另按本院程序办理，未写入本报告",
                     "扣除节假日后，平均每日上报2.1例次"):
            with self.subTest(miss=text):
                self.assertNotIn("HOS-020", ids_of(self.check(text, "RCA")))
        # 只在 RCA 中检查
        self.assertNotIn("HOS-020", ids_of(self.check("扣当月绩效500元。", "质量分析")))

    def test_rca_more_punishment_and_character_words(self) -> None:
        for text in ("对当事护士批评教育。", "在全院通报。", "对护士长诫勉谈话。",
                     "取消当事人当年评先评优资格。", "当事护士待岗培训。"):
            with self.subTest(hit=text):
                self.assertIn("HOS-020", ids_of(self.check(text, "RCA")))
        for text in ("将考核扣分与科室绩效挂钩。", "在全院通报表扬主动上报的科室。"):
            with self.subTest(miss=text):
                self.assertNotIn("HOS-020", ids_of(self.check(text, "RCA")))
        self.assertIn("HOS-018", ids_of(self.check("当班护士工作不够细致。", "RCA")))

    def test_markers_counted_in_summary(self) -> None:
        text = "出院患者【待补：人次】人次，病历甲级率【待核实：病案科确认】。\n【起草说明】\n【待补：不计入】"
        summary = self.check(text)["summary"]
        self.assertEqual(summary["markers"], {"待补": 1, "待核实": 1})
        self.assertEqual(summary["P2"], 0)

    def test_outdated_basis_exempt_in_history(self) -> None:
        self.assertIn("HOS-016", ids_of(self.check("按照《三级医院评审标准(2020年版)》要求整改。")))
        self.assertNotIn("HOS-016", ids_of(self.check("上一周期按《三级医院评审标准（2022年版）》评审。")))

    def test_guokao_only_in_formal_types(self) -> None:
        text = "2025年度国考成绩为A。"
        self.assertIn("HOS-015", ids_of(self.check(text, "绩效分析")))
        self.assertNotIn("HOS-015", ids_of(self.check(text, "述职")))
        self.assertNotIn("HOS-015", ids_of(self.check(text)))

    def test_draft_note_cutoff_variants(self) -> None:
        for note_line in ("【起草说明】", "## 【起草说明】", "**【起草说明】**"):
            with self.subTest(note=note_line):
                text = f"正文没有问题。\n{note_line}\n大手术比例为18%。"
                self.assertEqual(self.check(text)["issues"], [])

    def test_issue_fields_match_lint_interface(self) -> None:
        issue = self.check("大手术比例为18.6%")["issues"][0]
        for key in ("id", "level", "category", "line", "excerpt", "message", "suggestion", "basis", "gate"):
            self.assertIn(key, issue)
        self.assertEqual(issue["check"], "hospital")

    def test_invalid_type_raises(self) -> None:
        with self.assertRaises(hc.InputError):
            self.check("正文", "讲话稿")


class CliTest(HospitalCheckBase):

    def test_json_output_and_strict(self) -> None:
        path = self.tmp / "对外稿.txt"
        path.write_text("本院专家团队保证治愈，药到病除。", encoding="utf-8")
        code, out, _err = self.run_main(str(path), "--type", "对外宣传", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["summary"]["P0"], 2)
        code, _out, _err = self.run_main(str(path), "--type", "对外宣传", "--strict")
        self.assertEqual(code, 1)
        code, _out, _err = self.run_main(str(path), "--strict")
        self.assertEqual(code, 0)  # 内部材料只报 P1

    def test_text_output(self) -> None:
        path = self.tmp / "稿.md"
        path.write_text("# 标题\n\n全年CMI为108%。\n", encoding="utf-8")
        code, out, _err = self.run_main(str(path))
        self.assertEqual(code, 0)
        self.assertIn("HOS-007", out)
        self.assertIn("第3行", out)

    def test_input_errors_return_2(self) -> None:
        code, _out, err = self.run_main(str(self.tmp / "不存在.txt"))
        self.assertEqual(code, 2)
        self.assertIn("文件不存在", err)
        bad = self.tmp / "稿.pdf"
        bad.write_bytes(b"%PDF")
        code, _out, err = self.run_main(str(bad))
        self.assertEqual(code, 2)
        good = self.tmp / "稿.txt"
        good.write_text("正文", encoding="utf-8")
        code, _out, err = self.run_main(str(good), "--type", "讲话稿")
        self.assertEqual(code, 2)
        self.assertIn("--type", err)
        code, _out, _err = self.run_main()
        self.assertEqual(code, 2)

    def test_list_rules(self) -> None:
        code, out, _err = self.run_main("--list-rules")
        self.assertEqual(code, 0)
        self.assertIn("HOS-001", out)
        self.assertIn("HOS-005", out)
        self.assertIn("HOS-039", out)
        self.assertEqual(sum(1 for line in out.splitlines() if line.startswith("HOS-")), 39)

    def test_gb18030_input(self) -> None:
        path = self.tmp / "旧编码.txt"
        path.write_bytes("抗生素使用强度为38.5。".encode("gb18030"))
        code, out, _err = self.run_main(str(path), "--json")
        self.assertEqual(code, 0)
        self.assertIn("HOS-010", out)

    @unittest.skipUnless(HAS_DOCX, "未安装 python-docx")
    def test_docx_input_with_table_and_note(self) -> None:
        import docx  # type: ignore
        document = docx.Document()
        document.add_paragraph("关于住院患者跌倒事件的根本原因分析报告")
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "原因"
        table.cell(0, 1).text = "当班护士粗心大意"
        document.add_paragraph("【起草说明】")
        document.add_paragraph("当班护士责任心不强")
        path = self.tmp / "根因分析.docx"
        document.save(str(path))
        code, out, _err = self.run_main(str(path), "--type", "RCA", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(ids_of(data), ["HOS-018"])
        self.assertEqual(data["issues"][0]["excerpt"], "粗心大意")


class ClauseExemptionTest(HospitalCheckBase):
    """分句豁免（exempt_clause 等）、隐私变体与程序性规则相邻句判断。"""

    CASES = [
    ("HOS-020","RCA",True,"已对当事护士扣罚当月奖金，不予追究其他人员。"),
    ("HOS-020","RCA",True,"责任认定另按程序办理，对科室负责人给予诫勉。"),
    ("HOS-020","RCA",False,"不予处分，不扣绩效。"),
    ("HOS-020","RCA",False,"对当事护士未给予处分，也未扣绩效。"),
    ("HOS-003",None,True,"经院内评估，我院技术国内领先。"),
    ("HOS-003",None,True,"学会发布年度报告，本中心为全省第一家。"),
    ("HOS-003",None,False,"据2025年榜单，我院位列省内第一。"),
    ("HOS-003",None,False,"经省级评审，该技术达到国内领先水平。"),
    ("HOS-033",None,True,"本院拟优化编码提升四级手术比例。"),
    ("HOS-033",None,True,"反馈意见已收到，建议修改手术操作编码以提高权重。"),
    ("HOS-033",None,False,"严禁调整诊断编码提高CMI。"),
    ("HOS-033",None,False,"自查发现，部分科室存在高编高套问题。"),
    ("HOS-034","议题",True,"合同已于上月先行签订，现提请会议审议。"),
    ("HOS-034","议题",True,"项目已先行付款，经论证，现提请审议。"),
    ("HOS-034","议题",False,"该项目尚未先行签约。"),
    ("HOS-034","议题",False,"严禁先行付款，现提请会议审议。"),
    ("HOS-035","议题",True,"合同已执行，现提请党委会议予以追认。"),
    ("HOS-035","议题",True,"设备已安装，请会议追认。"),
    ("HOS-035","议题",False,"严禁事后追认，现提请会议研究决定。"),
    ("HOS-035","议题",False,"提请会议追认该同志为先进个人。"),
    ("HOS-036",None,True,"自查发现问题，本人全年开单量位居第一。"),
    ("HOS-036",None,True,"科室开单奖励方案已执行。"),
    ("HOS-036",None,False,"严禁开单提成，取消开单奖励。"),
    ("HOS-036",None,False,"医师薪酬不与开单量挂钩。"),
    ("HOS-037","等级评审",True,"经自评，我院已达到三级甲等医院标准。"),
    ("HOS-037","等级评审",True,"拟于年内迎检，各项监测指标均达标。"),
    ("HOS-037","等级评审",False,"力争年内达到三级甲等医院标准。"),
    ("HOS-037","等级评审",False,"计划年内整改，目标：达到三级甲等医院标准。"),
    ("HOS-038","对外宣传",True,"全年发生2起医疗纠纷，均已化解。"),
    ("HOS-038","对外宣传",True,"建立投诉机制，院感暴发仍有发生。"),
    ("HOS-038","对外宣传",False,"全年无医疗纠纷。"),
    ("HOS-038","对外宣传",False,"开展医疗纠纷防范培训。"),
    ("HOS-039","等级评审",True,"评审周期内未发生前置要求所列情形。"),
    ("HOS-039","等级评审",True,"本次设备采购经院领导确认。\n未发生前置要求所列情形。"),
    ("HOS-039","等级评审",False,"经院领导逐条确认，评审周期内未发生前置要求所列情形。"),
    ("HOS-039","等级评审",False,"经院领导确认前置要求均已满足。\n评审周期内未发生前置要求所列情形。"),
    ("HOS-030",None,True,"7床周某某明日出院。"),
    ("HOS-030",None,True,"3床患者施蕾，女，术后第2天。"),
    ("HOS-030",None,False,"3床周围环境整洁。"),
    ("HOS-030",None,False,"本周新增12床，高度重视。"),
    ("HOS-031",None,True,"患者曾丽娜，女，因胃痛入院。"),
    ("HOS-031",None,True,"病人：高建军，男，56岁。"),
    ("HOS-031",None,False,"患者曾经跌倒，男性居多。"),
    ("HOS-031",None,False,"患者韩国籍，男，因肺炎入院。"),
    ("HOS-032","RCA",True,"责任护士任建华未按规定核对。"),
    ("HOS-032","RCA",True,"当班医师许红于凌晨到场。"),
    ("HOS-032","RCA",False,"当班护士任务繁重。"),
    ("HOS-032","RCA",False,"值班医师严格按流程处置。"),
        ("HOS-033", None, True, "经审计发现，本院拟通过调整诊断编码提高CMI。"),
    ("HOS-033", None, True, "虽开展了专项检查，仍建议调整主要诊断编码以提高CMI。"),
    ("HOS-034", "议题", True, "经专家论证，设备已先行采购，现提请会议审议。"),
    ("HOS-038", "对外宣传", True, "开展防范培训，今年仍发生医疗事故2起。"),
    ("HOS-038", "对外宣传", True, "我院建立了投诉机制，今年仍发生医疗事故2起。"),
    ("HOS-036", None, True, "取消开单提成，本人全年开单量位居第一。"),
    ("HOS-037", "等级评审", True, "对照标准自评，我院已达到三级甲等医院标准。"),
    ("HOS-003", None, True, "经省级认证，我院为全省第一。"),
    ("HOS-020", "RCA", True, "已对当事护士扣发当月绩效，未给予处分。"),
    ("HOS-032", "RCA", True, "当班护士王秀芳未执行双人核对，全院通报称此事已整改。"),
    ("HOS-003", None, False, "经中华医学会鉴定，该技术达到国内领先水平"),
    ("HOS-003", None, False, "全省第一季度门诊人次同比增长8.2%。"),
    ("HOS-003", None, False, "全市第一时间启动应急预案。"),
    ("HOS-003", None, False, "全国第一线医务人员坚守岗位。"),
    ("HOS-003", None, True, "全省第一家开展该术式的医院。"),
    ("HOS-034", "议题", False, "本项目尚未先行开工，已按程序提交审议。"),
    ("HOS-038", "对外宣传", False, "全年未发生医疗纠纷。"),
    ("HOS-038", "对外宣传", False, "全年未出现医疗事故。"),
    ("HOS-039", "等级评审", True, "本次设备采购经院领导确认。\n未发生前置要求所列情形。"),
    ("HOS-039", "等级评审", True, "须经院领导确认，评审周期内未发生前置要求所列情形。"),
    ("HOS-039", "等级评审", True, "评审周期内未发生前置要求所列情形，待确认。"),
    ("HOS-030", None, True, "（2床）刘某术后第一天复查血常规。"),
    ("HOS-030", None, True, "15床的孙某明日出院。"),
    ("HOS-030", None, True, "住院12床的王某，在家属陪同下出院。"),
    ("HOS-030", None, True, "床号 23 的刘某某输液时寒战。"),
    ("HOS-030", None, True, "12床（张三）因跌倒骨折。"),
    ("HOS-030", None, True, "床位号：12，患者王某某。"),
    ("HOS-030", None, True, "3床周子涵，女，2岁，因肺炎住院。"),
    ("HOS-031", None, True, "患者 刘洋，男，56岁，因跌倒入院。"),
    ("HOS-031", None, True, "患者：李建国，男，56岁，因跌倒入院。"),
    ("HOS-031", None, True, "患儿，刘子涵，男，5岁，因肺炎入院。"),
    ("HOS-031", None, True, "患者姓名为陈思远，女。"),
    ("HOS-031", None, True, "患者何丽，女，因胃痛入院。"),
    ("HOS-031", None, False, "患者沈阳籍，男，因肺炎入院。"),
    ("HOS-031", None, False, "患者徐州籍，男，因肺炎入院。"),
    ("HOS-031", None, False, "患者韩国籍，女，45岁"),
    ("HOS-032", "RCA", True, "当班护士施蕾未执行双人核对"),
    ("HOS-032", "RCA", True, "值班医师马建军于22时到场"),
    ("HOS-032", "RCA", True, "当班护士何丽未执行查对"),
    ]

    def test_clause_level_exemption_cases(self) -> None:
        for rule_id, doc_type, expected, text in self.CASES:
            with self.subTest(rule=rule_id, text=text):
                found = rule_id in ids_of(self.check(text, doc_type))
                self.assertEqual(found, expected)

    def test_stopword_names_are_not_reported(self) -> None:
        """姓氏字开头的医学词、药名、地名、普通词，套入三种句式都不报隐私规则。"""
        words = ("高血压 高热 高度 白细胞 白血病 白内障 黄疸 黄斑 马上 马蹄 周围 周期 周转 许可 许多 施行 施救 丁香 丁卡因 "
                 "任务 任职 任何 金额 金属 余额 程度 程序 方案 方法 石膏 于是 曾经 康复 夏季 陆续 华法林 文化 牛皮癣 洪水 严重 "
                 "严格 武汉 万一 段落 雷同 龙骨 陶瓷 江苏 柳氮磺吡啶 辛辣 葛根 黎明 范围 叶酸 顾及 唐突 郑重 董事 钟情 田间 "
                 "陈述 汤药 谢绝 钱币 毛细血管 孔隙 林巴 张口 张力 苏醒 杜冷丁 沈阳 韩国 白术 黄精 何首乌 夏枯草 金银花 石决明 "
                 "白天 白班 高层 高管 华北 余震 周报 林场").split()
        templates = (("HOS-031", "患者{X}，男，56岁，因发热入院。"), ("HOS-030", "12床{X}，女，因发热入院。"),
                     ("HOS-030", "12床患者{X}，男，因发热入院。"), ("HOS-030", "{X}（12床）发热。"),
                     ("HOS-032", "当班护士{X}未执行双人核对。"), ("HOS-032", "值班医师{X}于22时到场。"))
        self.assertGreaterEqual(len(words), 80)
        for word in words:
            for rule_id, template in templates:
                text = template.replace("{X}", word)
                with self.subTest(word=word, text=text):
                    self.assertNotIn(rule_id, ids_of(self.check(text, "RCA")))

    def test_real_names_are_reported(self) -> None:
        for name in ("刘洋", "李建国", "王秀英", "周子涵", "何丽", "施蕾", "马建军", "高明", "丁磊", "任杰", "金晶", "余军",
                     "程红", "石磊", "曾军", "白雪", "夏雨", "陆军", "许建国", "欧阳娜娜", "江涛", "于洋"):
            for rule_id, template in (("HOS-031", "患者{X}，男，56岁。"), ("HOS-030", "12床{X}，女，因发热入院。"),
                                      ("HOS-032", "当班护士{X}未执行双人核对。")):
                with self.subTest(name=name, rule=rule_id):
                    self.assertIn(rule_id, ids_of(self.check(template.replace("{X}", name), "RCA")))

    def test_exempted_name_still_masked_in_other_rules(self) -> None:
        """隐私规则因“通报原文”豁免未报出，姓名仍须在其他规则的 excerpt、context 中遮蔽。"""
        result = self.check("当班护士王秀芳（通报原文）扣发当月绩效。", "RCA")
        self.assertNotIn("HOS-032", ids_of(result))
        self.assertIn("HOS-020", ids_of(result))
        self.assertNotIn("王秀芳", json.dumps(result, ensure_ascii=False))
        other = [i for i in result["issues"] if i["id"] == "HOS-020"][0]
        self.assertIn("〔已遮蔽〕", other.get("context", ""))

    def test_name_masked_fulltext_across_lines(self) -> None:
        """姓名在第 2 行被隐私规则识别，在后面几行被非隐私规则的 excerpt、context 带出，全文输出都不得含该姓名。"""
        text = ("事件经过\n当班护士孙丽于14时完成静脉穿刺。\n\n原因分析\n"
                "孙丽责任心不强，对操作规范掌握不到位。\n拟对孙丽给予通报批评并扣减当月绩效。\n"
                "17床赵敏华（女，49岁）出现外渗。\n患者赵敏华对处置表示理解，家属赵敏华之女责任心不强。")
        result = self.check(text, "RCA")
        for rule_id in ("HOS-030", "HOS-032", "HOS-018", "HOS-020"):
            self.assertIn(rule_id, ids_of(result))
        for name in ("孙丽", "赵敏华"):
            self.assertNotIn(name, json.dumps(result, ensure_ascii=False))
            self.assertNotIn(name, hc.render_text(result))
        path = self.tmp / "RCA.txt"
        path.write_text(text, encoding="utf-8")
        for extra in ((), ("--json",)):
            code, out, _err = self.run_main(str(path), "--type", "RCA", *extra)
            self.assertEqual(code, 0)
            for name in ("孙丽", "赵敏华"):
                self.assertNotIn(name, out)

    def test_name_table_includes_exempted_and_extends_short_match(self) -> None:
        """豁免未报出的姓名同样入表；“患者姓名：李建国”被截成两字时补全。"""
        text = "当班护士王秀芳（通报原文）已处理。\n王秀芳后续扣发绩效，患者姓名：李建国。\n李建国责任心不强。"
        result = self.check(text, "RCA")
        for name in ("王秀芳", "李建国"):
            self.assertNotIn(name, json.dumps(result, ensure_ascii=False))

    def test_pseudonym_not_in_name_table(self) -> None:
        """“张某”这类代称不进姓名表，其他行的正常摘录不受影响。"""
        result = self.check("12床张某因跌倒骨折。\n责任心不强的当事人另行处理。", "RCA")
        issue = next(i for i in result["issues"] if i["id"] == "HOS-018")
        self.assertEqual(issue["excerpt"], "责任心不强")

    def test_masking_survives_clause_exemption(self) -> None:
        text = "12床张三因跌倒骨折，全院通报称此事已整改，对当事护士给予通报批评。"
        result = self.check(text, "RCA")
        self.assertIn("HOS-030", ids_of(result))
        self.assertNotIn("张三", json.dumps(result, ensure_ascii=False))

    def test_prerequisite_adjacent_scope(self) -> None:
        """HOS-039 的 satisfied 只在触发句或相邻句里算，且“须经”“待确认”不算已确认。"""
        far = "经院领导逐条确认前置要求。\n\n第二部分\n\n第三部分\n\n评审周期内未发生前置要求所列情形。"
        self.assertIn("HOS-039", ids_of(self.check(far, "等级评审")))
        near = "经院领导逐条确认。\n评审周期内未发生前置要求所列情形。"
        self.assertNotIn("HOS-039", ids_of(self.check(near, "等级评审")))


if __name__ == "__main__":
    unittest.main()
