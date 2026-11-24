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

from tests.names.masking import check_masked_outputs
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
            for example in rule.level_examples:
                with self.subTest(rule=rule.id, level_example=example["text"]):
                    levels = {i["level"] for i in self.check(example["text"], doc_type)["issues"] if i["id"] == rule.id}
                    self.assertEqual(levels, {example["level"]})

    def test_known_cost_examples_are_reported_again(self) -> None:
        """收缩的已知代价：否决、整改、出处写在命中之后的分句里，豁免不再生效，这些句子会重新被报出。
        （原先在 miss_examples 里，收缩后移到 known_cost_examples；将来若放宽窗口，这里会先失败，提醒重新评估。）"""
        raw = json.loads((SCRIPTS_DIR / "hospital_rules.json").read_text(encoding="utf-8"))
        count = 0
        for r in raw["rules"]:
            rule = next(x for x in self.ruleset.rules if x.id == r["id"])
            doc_type = rule.types[0] if rule.types else None
            for example in r.get("known_cost_examples") or []:
                count += 1
                with self.subTest(rule=r["id"], known_cost=example):
                    self.assertIn(r["id"], ids_of(self.check(example, doc_type)))
        self.assertGreaterEqual(count, 5)

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

    def test_procedure_inversion_declared_downgraded_to_p1(self) -> None:
        """如实声明程序倒置、没有追认补办的降为 P1（不再整句豁免）；写了追认、补办的仍是 P0。"""
        def level(text: str):
            levels = [i["level"] for i in self.check(text, "议题")["issues"] if i["id"] == "HOS-034"]
            return levels[0] if levels else None

        self.assertEqual(level("该设备已于9月先行采购，现提请会议审议。"), "P0")
        self.assertEqual(level("该设备已于9月先行采购，属于程序倒置，现如实报告。"), "P1")
        self.assertEqual(level("该设备已于9月先行采购，属于程序倒置，现提请追认。"), "P0")
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
            self.assertNotIn("context", issue)
        by_id = {i["id"]: i["excerpt"] for i in privacy}
        # 隐私规则的摘录是“锚点 + 占位符 + 右侧最多 8 字”；代称（张某）不进姓名表，原样保留
        self.assertEqual(by_id["HOS-031"], "患者姓名：〔姓名1〕。当班护士〔姓名2〕未")
        self.assertEqual(by_id["HOS-032"], "当班护士〔姓名2〕未执行双人核对。")
        self.assertIn("张某（床号12）", by_id["HOS-030"])
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
            self.assertIn("〔姓名1〕", out)
            self.assertIn("〔姓名2〕", out)

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
        self.assertIn("12床〔姓名1〕因跌倒骨折", other.get("context", "") + other["excerpt"])
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
        self.assertIn("〔姓名1〕", other.get("context", ""))

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



class NameDetectionTest(HospitalCheckBase):
    """锚点 + 候选 + 打分的实名识别：高置信 P0、低置信 P1，不靠姓氏表加排除词表的名单。"""

    PRIVACY = ("HOS-030", "HOS-031", "HOS-032")

    def privacy_levels(self, text: str, doc_type="RCA"):
        return [(i["id"], i["level"]) for i in self.check(text, doc_type)["issues"] if i["id"] in self.PRIVACY]

    def test_stopword_names_are_not_reported(self) -> None:
        """姓氏字开头的医学词、药名、地名、普通词，套入六种句式都不报隐私规则（恢复 HEAD 的同名回归测试，词表原样取自 HEAD）。

        词表里去掉“黎明”“韩国”两个词：它们与整词排除词同形（stopwords_exact），在“，男，56岁”这类强证据（R3 级右边界）下按设计
        放行为姓名（黎明、韩国确有人叫），带强证据的句式会识别，属于已知并接受的取舍（tests/names 的 test_exact_stopword_needs_strong_evidence_and_loses_one_point 逐词断言：无强证据不报，R3 级右边界下按 P1 报）。
        “强证据放行前缀排除词”只对名字用字都在常见名用字表里的三字候选生效，其余各词（含两字医学词）仍须全部不报。"""
        words = ("高血压 高热 高度 白细胞 白血病 白内障 黄疸 黄斑 马上 马蹄 周围 周期 周转 许可 许多 施行 施救 丁香 丁卡因 "
                 "任务 任职 任何 金额 金属 余额 程度 程序 方案 方法 石膏 于是 曾经 康复 夏季 陆续 华法林 文化 牛皮癣 洪水 严重 "
                 "严格 武汉 万一 段落 雷同 龙骨 陶瓷 江苏 柳氮磺吡啶 辛辣 葛根 范围 叶酸 顾及 唐突 郑重 董事 钟情 田间 "
                 "陈述 汤药 谢绝 钱币 毛细血管 孔隙 林巴 张口 张力 苏醒 杜冷丁 沈阳 白术 黄精 何首乌 夏枯草 金银花 石决明 "
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

    def test_strong_evidence_releases_prefix_stopwords_for_three_char_names(self) -> None:
        """强证据（R3 级右边界）下，前缀排除词（张大、孙子、夏天、杨梅……）不否决名字用字都是常见名用字的三字候选。"""
        for name in "张大伟 张大勇 王冠宇 王朝阳 叶子萌 苏子涵 孙子豪 金子涵 杨梅芳 白云飞 夏天宇 钱江涛 江河清 方可欣".split():
            with self.subTest(name=name):
                self.assertTrue(self.privacy_levels(f"患者{name}，男，56岁。"), name)
        for text in ("患者高血压，男性多见。", "患者周围神经病变，女性多见。", "患者白细胞偏高，男性多见。", "患者黄疸，男，56岁。"):
            with self.subTest(text=text):
                self.assertEqual(self.privacy_levels(text), [])

    def test_ambiguous_surname_three_char_names_with_strong_anchor(self) -> None:
        """歧义姓（常、关、祝、焦、单、管、安）的三字名在强锚点下按常见姓处理；两字名仍要求右边界是标点或身份括注。"""
        for name in "常秀芳 关晓峰 祝丽华 焦志刚 单丽娟 管玉兰 安秀英".split():
            with self.subTest(name=name):
                self.assertTrue(self.privacy_levels(f"当班护士{name}未执行双人核对。"), name)
        for text in ("患者和家属沟通。", "患者平均住院日缩短。", "病人关心的是费用。", "管理人员安排到位。"):
            with self.subTest(text=text):
                self.assertEqual(self.privacy_levels(text), [])

    def test_second_name_in_list_is_masked(self) -> None:
        """并列后项：形态合法就登记进姓名表并遮蔽（分数不足的不单独报）。"""
        issues = self.check("患者王磊、李娜两人均出现输液反应。", "RCA")["issues"]
        excerpts = " ".join(i["excerpt"] + i.get("context", "") for i in issues)
        self.assertTrue(issues)
        self.assertNotIn("王磊", excerpts)
        self.assertNotIn("李娜", excerpts)
        self.assertIn("〔姓名2〕", excerpts)

    def test_reported_as_p0(self) -> None:
        for text in ("患者王建国术后发热。", "患者：王建国，住院号123456。", "王建国（住院号20231234）于3月5日入院。",
                     "护士张丽丽未执行双人核对。", "由护士张丽丽负责该患者。", "当班护士为张丽丽，已交班。",
                     "12床张三因跌倒骨折。", "15床的孙某明日出院。", "患者李建国，男，56岁。"):
            with self.subTest(text=text):
                levels = self.privacy_levels(text)
                self.assertTrue(levels and all(lv == "P0" for _rid, lv in levels), levels)

    def test_not_reported(self) -> None:
        for text in ("值班医师曾多次未按时交班。", "患者黄疸，女性多见。", "患者沈阳籍，男，因肺炎入院。",
                     "患者平均住院日缩短。", "值班医师严格按流程处置。", "张主任查房至12床。",
                     "患者张某，男，56岁。", "患者高血压，需监测血压。", "患者关心的是费用问题。",
                     "医师初审后签字。", "当班护士任务繁重，病区新增床位12张。"):
            with self.subTest(text=text):
                self.assertEqual(self.privacy_levels(text), [])

    def test_low_confidence_is_p1(self) -> None:
        """低置信（总分恰为 5）报 P1，不是 P0。第 2 步起“与”“对”“的”“在”等功能字对三字名是强边界（得 2 分）：
        “患者赵敏华与家属沟通”是 P0；低置信 P1 改用右侧是词表外动词的自然写法（名用字在常见名用字表里、
        但右边界没有证据）。两字名在功能字后仍只得 1 分，仍是 P1。"""
        self.assertEqual(self.privacy_levels("患者赵敏华接受抗感染治疗。"), [("HOS-031", "P1")])
        self.assertEqual(self.privacy_levels("护士赵敏华私自离岗。"), [("HOS-032", "P1")])
        self.assertEqual(self.privacy_levels("12床赵敏接受治疗。"), [("HOS-030", "P1")])
        self.assertEqual(self.privacy_levels("12床赵敏与家属沟通。"), [("HOS-030", "P1")])
        # 三字名 + 功能字：P0
        self.assertEqual(self.privacy_levels("患者赵敏华与家属沟通。"), [("HOS-031", "P0")])
        self.assertEqual(self.privacy_levels("护士赵敏华与家属沟通。"), [("HOS-032", "P0")])

    def test_hos032_only_in_its_doc_types(self) -> None:
        self.assertEqual(self.privacy_levels("护士张丽丽未执行双人核对。", "述职"), [])
        self.assertEqual(self.privacy_levels("护士张丽丽未执行双人核对。", None), [])
        self.assertEqual(self.privacy_levels("护士张丽丽未执行双人核对。", "整改"), [("HOS-032", "P0")])

    def test_unanchored_name_masked_by_name_table(self) -> None:
        """没有锚点的“张丽丽当晚独自值守”识别不了，但同一姓名在别处被识别后，全文输出都遮蔽。"""
        text = "患者李建国术后发热。\n护士张丽丽未执行双人核对。\n张丽丽当晚独自值守，责任心不强。\n李建国责任心不强。"
        result = self.check(text, "RCA")
        dumped = json.dumps(result, ensure_ascii=False)
        for name in ("张丽丽", "李建国"):
            self.assertNotIn(name, dumped)
            self.assertNotIn(name, hc.render_text(result))
        # 第 3 行没有锚点，不作为 HOS-032 命中；但 HOS-018 的上下文里姓名以同一编号显示
        self.assertEqual([i["line"] for i in result["issues"] if i["id"] == "HOS-032"], [2])
        contexts = [i.get("context", "") for i in result["issues"] if i["id"] == "HOS-018"]
        self.assertTrue(any("〔姓名2〕当晚独自值守" in c for c in contexts), contexts)
        self.assertTrue(any("〔姓名1〕责任心不强" in c for c in contexts), contexts)

    def test_placeholder_numbers_follow_first_appearance(self) -> None:
        text = "患者王建国术后发热。\n当班护士为孙丽，已交班。\n患者王建国对处置表示理解。"
        result = self.check(text, "RCA")
        excerpts = {(i["id"], i["line"]): i["excerpt"] for i in result["issues"]}
        self.assertEqual(excerpts[("HOS-031", 1)], "患者〔姓名1〕术后发热。")
        self.assertEqual(excerpts[("HOS-032", 2)], "当班护士为〔姓名2〕，已交班。")
        self.assertEqual(excerpts[("HOS-031", 3)], "患者〔姓名1〕对处置表示理解。")

    def test_pseudonym_with_bed_number_is_not_in_name_table(self) -> None:
        """“张某”这类代称不进姓名表；与床号的组合仍是 HOS-030 的 P0。"""
        result = self.check("12床张某因跌倒骨折。\n另一名患者张某，男，56岁。", "RCA")
        self.assertEqual([(i["id"], i["level"]) for i in result["issues"]], [("HOS-030", "P0")])
        self.assertIn("张某", result["issues"][0]["excerpt"])
        self.assertNotIn("〔姓名", json.dumps(result, ensure_ascii=False))

    def test_identical_issues_merged_with_count(self) -> None:
        """(id, 行, excerpt, message) 完全相同的命中合并成一条，带 count。"""
        result = self.check("责任心不强，同样责任心不强。", "RCA")
        hits = [i for i in result["issues"] if i["id"] == "HOS-018"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["count"], 2)
        self.assertEqual(result["summary"]["P1"], 1)
        # 摘录不同的不合并
        self.assertEqual(len([i for i in self.check("责任心不强，同样粗心大意。", "RCA")["issues"]
                              if i["id"] == "HOS-018"]), 2)

    def test_long_digits_not_echoed(self) -> None:
        result = self.check("患者：王建国，住院号12345678。", "RCA")
        excerpt = next(i["excerpt"] for i in result["issues"] if i["id"] == "HOS-031")
        self.assertNotRegex(excerpt, r"\d{5,}")
        self.assertNotIn("1234", excerpt)

    def test_privacy_rules_have_no_embedded_name_lists(self) -> None:
        """隐私规则不再内嵌姓氏表和排除词表：规则文件里只剩锚点，数据在共享的 gw_names.json。"""
        raw = hc.RULES_PATH.read_text(encoding="utf-8")
        for word in ("周围神", "周转箱", "许可证", "高热量"):
            self.assertNotIn(word, raw)
        by_id = {r.id: r for r in self.ruleset.rules}
        for rid in ("HOS-030", "HOS-031", "HOS-032"):
            self.assertEqual(by_id[rid].detector, "names")
            self.assertTrue(by_id[rid].anchors)
            self.assertEqual(by_id[rid].low_level, "P1")
        self.assertIsNone(by_id["HOS-031"].regex)
        self.assertIsNone(by_id["HOS-032"].regex)


class SharedClauseExemptionTest(HospitalCheckBase):
    """分句豁免统一用 gw_clause：处置类只看命中所在分句，出处类看所在分句与紧邻的前一分句，调查引述只看命中分句；没有后续分句窗口。"""

    def test_disposed_or_sourced_not_reported(self) -> None:
        """同分句内的处置、前一分句内的出处、命中分句里的调查引述：不报。"""
        cases = (
            ("整改", "HOS-033", "医院否决了个别科室调整主要诊断编码以提高CMI的建议，并在质控会议上重申编码只依据病历记载。"),
            ("整改", "HOS-033", "经医保办研判，有科室建议通过分解住院降低次均费用的做法违规，未予采纳。"),
            ("整改", "HOS-033", "巡察指出部分科室存在调整编码提高四级手术占比的苗头，已整改。"),
            ("议题", "HOS-034", "巡察反馈的先采购后报批问题已于9月整改到位。"),
            ("对外宣传", "HOS-003", "经省科技厅鉴定，该技术国内领先。"),
            ("对外宣传", "HOS-003", "经中华医学会鉴定，该技术达到国内领先水平"),
            ("对外宣传", "HOS-003", "该技术入选省卫健委发布的适宜技术推广目录，处于国内领先水平"),
            ("议题", "HOS-035", "巡察反馈提请追认的问题已于9月整改到位。"),
            ("质量分析", "HOS-036", "巡察发现有科室推行开单提成，已整改到位。"),
            ("整改", "HOS-033", "严禁通过调整主要诊断编码提高CMI"),
            ("整改", "HOS-033", "检查发现个别病例存在分解住院问题"),
        )
        for doc_type, rid, text in cases:
            with self.subTest(text=text):
                self.assertNotIn(rid, ids_of(self.check(text, doc_type)))

    def test_known_cost_later_clause_reported_again(self) -> None:
        """收缩的已知代价（负责人决定接受）：否决、整改、出处写在后一分句里，豁免不再生效，重新被报出。
        报出的 suggestion 里带“若后文已写明否决、整改或出处，可忽略本条”的提示。"""
        cases = (
            ("整改", "HOS-033", "对个别科室提出的调整主要诊断编码以提高CMI的建议，医院明确予以否决。"),
            ("整改", "HOS-033", "有科室建议通过分解住院降低次均费用，经医保办研判，该做法违规，未予采纳。"),
            ("议题", "HOS-034", "巡察反馈的先采购后报批问题，已于9月整改到位。"),
            ("对外宣传", "HOS-003", "该技术国内领先，经省科技厅鉴定。"),
            ("议题", "HOS-035", "巡察反馈提请追认的问题，已于9月整改到位。"),
        )
        for doc_type, rid, text in cases:
            with self.subTest(text=text):
                hits = [i for i in self.check(text, doc_type)["issues"] if i["id"] == rid]
                self.assertTrue(hits)
                self.assertIn("可忽略本条", hits[0]["suggestion"])

    def test_new_acceptance_sentences_are_reported(self) -> None:
        """取消后续窗口、补语境检查后，下列句子必须报出（改动前的工作区不报，HEAD 报）。"""
        cases = (
            ("质量分析", "HOS-033", "建议调整主要诊断编码以提高CMI值，避免违规。"),
            ("质量分析", "HOS-033", "建议调整主要诊断编码以提高CMI，确保不出现违规。"),
            ("质量分析", "HOS-033", "建议通过调整编码提高CMI，此前已有科室完成整改。"),
            ("质量分析", "HOS-033", "建议通过分解住院降低次均费用，其他医院也违规这样做。"),
            ("质量分析", "HOS-033", "建议通过分解住院降低次均费用其他医院也违规这样做。"),        # 同分句：指他
            ("对外宣传", "HOS-003", "该技术达到国内领先水平，有关鉴定意见待省科技厅出具。"),
            ("对外宣传", "HOS-003", "该技术国内领先，相关评价报告将于明年发布。"),
            ("对外宣传", "HOS-003", "鉴定意见待省科技厅出具，该技术达到国内领先水平。"),
        )
        for doc_type, rid, text in cases:
            with self.subTest(text=text):
                self.assertIn(rid, ids_of(self.check(text, doc_type)))

    def test_still_reported(self) -> None:
        cases = (
            ("整改", "HOS-033", "经审计发现，本院拟通过调整诊断编码提高CMI。"),
            ("整改", "HOS-033", "虽开展了专项检查，仍建议调整主要诊断编码以提高CMI。"),
            ("整改", "HOS-033", "建议调整主要诊断编码以提高CMI，不违规。"),
            ("整改", "HOS-033", "建议通过分解住院降低次均费用，以改善结余。"),
            ("对外宣传", "HOS-003", "经省级认证，我院为全省第一。"),
        )
        for doc_type, rid, text in cases:
            with self.subTest(text=text):
                self.assertIn(rid, ids_of(self.check(text, doc_type)))

    def test_inversion_combination(self) -> None:
        def level(text: str):
            levels = [i["level"] for i in self.check(text, "议题")["issues"] if i["id"] == "HOS-034"]
            return levels[0] if levels else None

        # 收缩：组合判定一律 P1；P0 只来自 pattern 对“先行采购、补办手续”等明确写法的命中（单独的“追认”只报 HOS-035 P1）
        self.assertEqual(level("本项目设备已于9月采购到位并投入使用，现提请院长办公会审议。"), "P1")
        self.assertEqual(level("设备已先行采购，现提请院长办公会审议。"), "P0")
        self.assertEqual(level("设备已先行采购，属于程序倒置，现如实报告。"), "P1")
        self.assertEqual(level("一期设备已于9月投入使用，现提请审议二期方案。"), "P1")
        self.assertEqual(level("设备已于9月投入使用。\n现提请院长办公会审议。"), "P1")
        for text in ("已完成论证，拟提交党委会议研究。", "本项目尚未先行开工，已按程序提交审议。",
                     "已于9月召开职代会审议通过，现提请院长办公会审议。",
                     "本项目尚未开工，现提请院长办公会审议。"):
            with self.subTest(text=text):
                self.assertIsNone(level(text))
        # 只在议题中检查
        self.assertNotIn("HOS-034", ids_of(self.check("本项目设备已于9月采购到位并投入使用，现提请院长办公会审议。", "质量分析")))

    def test_inversion_merged_with_regex_hit_keeps_regex_excerpt(self) -> None:
        result = self.check("该设备已于9月先行采购，现提请会议审议。", "议题")
        hits = [i for i in result["issues"] if i["id"] == "HOS-034"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["excerpt"], "先行采购")


class BoundaryAndDedupeTest(HospitalCheckBase):
    """“的”“对”强边界、“床”左边界与同一姓名同一位置的多规则去重。"""

    def levels(self, text: str, doc_type="RCA"):
        return [(i["id"], i["level"]) for i in self.check(text, doc_type)["issues"]
                if i["id"] in ("HOS-030", "HOS-031", "HOS-032")]

    def test_strong_boundary_dui_de_reported(self) -> None:
        self.assertEqual(self.levels("患者王建国的家属对处置表示理解。"), [("HOS-031", "P0")])
        self.assertEqual(self.levels("患者赵敏华对处置过程表示不满。"), [("HOS-031", "P0")])
        self.assertEqual(self.levels("患者王丽的家属来访。"), [("HOS-031", "P1")])  # 两字名：低置信
        self.assertEqual(self.levels("护士赵敏华对患者进行了宣教。"), [("HOS-032", "P0")])

    def test_strong_boundary_dui_de_no_false_hits(self) -> None:
        for text in ("患者的家属对处置表示理解。", "医师的处置符合规范。", "护士对患者进行了宣教。",
                     "患者黄疸，女性多见。", "值班医师曾多次未按时交班。", "患者平均住院日缩短。"):
            with self.subTest(text=text):
                self.assertEqual(self.levels(text), [])

    def test_bed_number_name_reported_once(self) -> None:
        """“17床赵敏华（女，49岁）”：床号锚点与括注后锚点同时命中同一姓名，只留 HOS-030 一条。"""
        result = self.check("17床赵敏华（女，49岁）输液外渗。", "RCA")
        privacy = [i for i in result["issues"] if i["id"] in ("HOS-030", "HOS-031", "HOS-032")]
        self.assertEqual([(i["id"], i["level"]) for i in privacy], [("HOS-030", "P0")])
        self.assertNotIn("赵敏华", json.dumps(result, ensure_ascii=False))

    def test_dedupe_prefers_higher_level_then_semantic_rule(self) -> None:
        # 角色词（HOS-032）与括注（HOS-031 后锚点）同时命中：同级别，留 HOS-032
        self.assertEqual(self.levels("当班护士孙丽（工号N0387）未执行核对。"), [("HOS-032", "P0")])
        # 只有括注：HOS-031
        self.assertEqual(self.levels("赵敏华（住院号20231234）于3月5日入院。"), [("HOS-031", "P0")])
        # 不同位置的同一姓名各自报一条：床号处 HOS-030，“患者”处 HOS-031
        self.assertEqual(sorted(self.levels("17床赵敏华（女，49岁）输液外渗。\n患者赵敏华对处置表示不满。")),
                         [("HOS-030", "P0"), ("HOS-031", "P0")])

    def test_comma_list_second_name_is_masked(self) -> None:
        """患者名单里用逗号并列的第二个姓名也被识别并遮蔽。"""
        result = self.check("患者：王建国，李四\n李四术后发热。", "RCA")
        self.assertNotIn("李四", json.dumps(result, ensure_ascii=False))


class DeclarationExemptionTest(HospitalCheckBase):
    """程序倒置：就近有如实声明时处置类豁免不适用；正则 P0 命中在本句、前一句、后一句有对本事项的肯定式声明、且没有追认补办时降 P1（不再有全文级降级）。"""

    def levels(self, text: str):
        return [i["level"] for i in self.check(text, "议题")["issues"] if i["id"] == "HOS-034"]

    def test_declared_with_disposal_word_is_p1_not_silent(self) -> None:
        self.assertEqual(self.levels("设备已于9月先行采购，该做法违反了采购管理规定，属于程序倒置，现如实报告。"), ["P1"])
        self.assertEqual(self.levels("设备已于9月先行采购，该做法违反了采购管理规定，现如实报告。"), ["P1"])

    def test_disposal_without_declaration_still_exempt(self) -> None:
        """只有处置、没有声明：不报。原用例“设备已于9月先行采购，该做法违反了…规定，已整改。”拆成两条：
        无声明的巡察整改（处置与命中在同一分句）仍不报；含“该做法违反了…规定”的现在是肯定式声明，就近有声明时处置类豁免不适用，报 P1。
        收缩：整改写在后一分句时豁免不再生效（已知代价），见下一条。"""
        self.assertEqual(self.levels("巡察反馈的先采购后报批问题已于9月整改到位。"), [])

    def test_disposal_in_later_clause_no_longer_exempts(self) -> None:
        """整改写在后一分句：不再豁免，但后续分句里有针对该做法的处置词，P0 降为 P1（仍报出）。"""
        self.assertEqual(self.levels("巡察反馈的先采购后报批问题，已于9月整改到位。"), ["P1"])

    def test_affirmative_violation_statement_is_declaration_not_disposal(self) -> None:
        self.assertEqual(self.levels("设备已于9月先行采购，该做法违反了采购管理规定，已整改。"), ["P1"])

    def test_normalize_keeps_p0_even_when_declared(self) -> None:
        self.assertEqual(self.levels("设备已于9月先行采购，属于程序倒置，现如实报告，并提请院长办公会追认。"), ["P0"])

    def test_no_document_level_downgrade(self) -> None:
        """收缩：不再有全文级降级。声明只看同一句和紧邻的前、后一句；隔开的重复写法按原级别（正则 P0）。"""
        text = ("一、情况\n设备已于9月先行采购并投入使用，现提请院长办公会审议。\n二、进展\n"
                "该设备先行采购后已累计使用120台次，现提请院长办公会审议。\n三、说明\n以上程序倒置情况，如实报告。")
        self.assertEqual(self.levels(text), ["P0", "P0"])
        # 声明紧邻（下一行）：该处降 P1
        text2 = "设备已于9月先行采购并投入使用，现提请院长办公会审议。\n以上程序倒置情况，如实报告。"
        self.assertEqual(self.levels(text2), ["P1"])

    def test_chain_prohibition_with_dun_hao(self) -> None:
        self.assertEqual(self.levels("要杜绝先行开工、先行签约等现象。"), [])
        self.assertEqual(self.levels("严禁先行采购、先行付款，违者追责。"), [])
        self.assertEqual(self.levels("要杜绝违规操作，先行采购的设备已经上线。"), ["P0"])


class SharedModuleMissingTest(HospitalCheckBase):
    """缺共享模块或数据损坏：退出码 2，不静默降级。"""

    def load_copy(self, name: str, drop: str = "", corrupt_json: bool = False):
        import importlib.util
        pkg = self.tmp / name / "scripts"
        pkg.mkdir(parents=True)
        for fname in ("hospital_check.py", "hospital_rules.json", "gw_names.py", "gw_names.json", "gw_clause.py"):
            if fname != drop:
                shutil.copy(SCRIPTS_DIR / fname, pkg / fname)
        if corrupt_json:
            (pkg / "gw_names.json").write_text("{", encoding="utf-8")
        spec = importlib.util.spec_from_file_location(f"_test_hc_{name}", str(pkg / "hospital_check.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod

    def run_copy(self, mod, *args: str):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = mod.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_missing_modules_exit_2(self) -> None:
        sample = self.tmp / "稿.txt"
        sample.write_text("患者王建国术后发热。", encoding="utf-8")
        for index, (drop, hint) in enumerate((("gw_names.py", "gw_names"), ("gw_clause.py", "gw_clause"),
                                              ("gw_names.json", "姓名数据文件"))):
            with self.subTest(missing=drop):
                mod = self.load_copy(f"missing{index}", drop=drop)
                code, _out, err = self.run_copy(mod, str(sample), "--type", "RCA")
                self.assertEqual(code, 2)
                self.assertIn(hint, err)

    def test_corrupt_name_data_exit_2(self) -> None:
        sample = self.tmp / "稿.txt"
        sample.write_text("患者王建国术后发热。", encoding="utf-8")
        mod = self.load_copy("corrupt", corrupt_json=True)
        code, _out, err = self.run_copy(mod, str(sample), "--type", "RCA")
        self.assertEqual(code, 2)
        self.assertIn("gw_names.json", err)

    def test_complete_copy_works(self) -> None:
        sample = self.tmp / "稿.txt"
        sample.write_text("患者王建国术后发热。", encoding="utf-8")
        mod = self.load_copy("complete")
        code, out, _err = self.run_copy(mod, str(sample), "--type", "RCA", "--json")
        self.assertEqual(code, 0)
        self.assertNotIn("王建国", out)
        self.assertIn("HOS-031", out)


# ---------------------------------------------------------------------------
# 第 2 步新增：引擎层回归、自然行文召回、程序倒置与豁免成对对照、文件名遮蔽
# ---------------------------------------------------------------------------
NAMES_FIXTURES = REPO_ROOT / "tests" / "names" / "fixtures"


def _read_names(name: str):
    out = []
    for raw in (NAMES_FIXTURES / name).read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _privacy_hits(result, rule_id=None):
    return [i for i in result["issues"] if i["id"] in ("HOS-030", "HOS-031", "HOS-032")
            and (rule_id is None or i["id"] == rule_id)]


class EngineHeadBaselineTest(HospitalCheckBase):
    """引擎层与 HEAD（d07b657）对照：fixtures/head_baseline.json 里医院的句式，在仓库夹具名字集（408 个）上，
    现在的 check_text 命中的姓名数不得低于 HEAD 实跑数字（HOS-032 一行须带 --type RCA）。"""

    def test_no_regression_against_head(self) -> None:
        base = json.loads((NAMES_FIXTURES / "head_baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(base["commits"]["HEAD"][:7], "d07b657")
        names = _read_names("names.txt")
        self.assertEqual(len(names), base["names_count"])
        rows = [r for r in base["rows"] if r["engine"] == "hospital"]
        self.assertGreaterEqual(len(rows), 8)
        lines = ["", "引擎层与 HEAD 基线对照（命中名字数，括号内 P0）："]
        for row in rows:
            args = row["args"]
            doc_type = args[args.index("--type") + 1] if "--type" in args else None
            found = high = 0
            for n in names:
                result = self.check(row["template"].format(n=n), doc_type)
                hits = _privacy_hits(result, row["rule"])
                self.assertNotIn(n, json.dumps(result, ensure_ascii=False), f"{row['template']}：姓名泄露")
                if hits:
                    found += 1
                    if any(h["level"] == "P0" for h in hits):
                        high += 1
            head = row["HEAD"]["detected"]
            lines.append(f"  {row['rule']} {row['template']}：HEAD {head}（P0 {row['HEAD']['p0']}）→ 现 {found}（P0 {high}）")
            self.assertGreaterEqual(found, head, f"{row['template']}：命中 {found} 低于 HEAD 的 {head}")
        sys.stderr.write("\n".join(lines) + "\n")


class EngineNaturalRecallTest(HospitalCheckBase):
    """自然行文召回（引擎层）：按“名字之后接什么”分类，各测一组句式，打印召回率与 P0 比例并断言下限。
    下限取实测值向下取整到 5%，不得为了通过而调低。“词表外动词”这一类用的后续不在右边界词表里，
    也不是共享层测试里已用过的那几个（接受、自述、服药、私自离岗、拒绝、突发）与留出集（行、病情、跌倒、死亡、确诊）。"""

    # 类别 -> [(文书类型, 句式)]。同一句式只放一个姓名，识别与否看是否有 HOS-030、031、032 命中。
    CATEGORIES = {
        "标点与括注": (
            ("RCA", "患者{n}，男，56岁，因胸痛入院。"), ("RCA", "患者：{n}，住院号123456。"),
            ("RCA", "{n}（住院号20231234）于3月5日入院。"), ("RCA", "当班护士{n}（工号0123）未执行核对。"),
        ),
        "功能字": (
            ("RCA", "患者{n}在病房跌倒。"), ("RCA", "患者{n}对处置不满。"), ("RCA", "患者{n}被安排转科。"),
            ("RCA", "患者{n}与家属沟通。"), ("RCA", "患者{n}因发热入院。"),
        ),
        "时间词": (
            ("RCA", "患者{n}昨日出院。"), ("RCA", "值班护士{n}凌晨巡视时发现异常。"),
            ("RCA", "患者{n}近期反复发热。"), ("RCA", "患者{n}入院后完善检查。"),
        ),
        "亲属所属": (
            ("RCA", "患者{n}家属对处理结果不满。"), ("RCA", "患者{n}本人要求出院。"), ("RCA", "患者{n}母亲陪同就诊。"),
        ),
        "词表外动词": (
            ("RCA", "患者{n}主动配合检查。"), ("RCA", "患者{n}辗转多家医院求治。"),
            ("RCA", "值班护士{n}擅自调整滴速。"), ("RCA", "患者{n}签署知情同意书。"), ("RCA", "患者{n}需要长期随访。"),
        ),
    }
    # 类别 -> (召回下限, P0 比例下限)。取实测向下取整到 5%。
    FLOORS = {
        "标点与括注": (0.95, 0.90),
        "功能字": (0.85, 0.60),
        "时间词": (0.90, 0.65),
        "亲属所属": (0.90, 0.60),
        "词表外动词": (0.65, 0.15),  # P0 比例低是设计结果：词表外动词只给三字名 P1，强锚点（当班护士）才到 P0
    }

    def test_recall_by_context(self) -> None:
        names = _read_names("names.txt")
        report = ["", f"引擎层自然行文召回（夹具名 {len(names)} 个，识别次数 / 总次数；P0 次数 / 总次数）："]
        failures = []
        for cat, templates in self.CATEGORIES.items():
            total = found = high = 0
            for n in names:
                for doc_type, tpl in templates:
                    total += 1
                    result = self.check(tpl.format(n=n), doc_type)
                    self.assertNotIn(n, json.dumps(result, ensure_ascii=False), f"{tpl} 姓名泄露：{n}")
                    hits = _privacy_hits(result)
                    if hits:
                        found += 1
                        if any(h["level"] == "P0" for h in hits):
                            high += 1
            rec, p0 = found / total, high / total
            report.append(f"  {cat}：召回 {found}/{total} = {rec:.1%}，P0 {high}/{total} = {p0:.1%}")
            floor = self.FLOORS[cat]
            if rec < floor[0]:
                failures.append(f"{cat} 召回 {rec:.1%} 低于下限 {floor[0]:.0%}")
            if p0 < floor[1]:
                failures.append(f"{cat} P0 比例 {p0:.1%} 低于下限 {floor[1]:.0%}")
        sys.stderr.write("\n".join(report) + "\n")
        self.assertEqual(failures, [], "\n".join(failures))


class InversionPairTest(HospitalCheckBase):
    """程序倒置（HOS-034）成对对照：级别与 message 文案类别都断言。"""

    def verdict(self, text: str):
        """返回 None（不报）或 (级别, 文案类别)；文案类别：p0（pattern 命中的 P0）、same_sentence、declared、other_item、adjacent、weak_exec、normalize。
        收缩后组合判定只给 P1，P0 只来自 pattern 对“先行采购、补办手续”等明确写法的命中（单独的“追认”只报 HOS-035 P1）。"""
        hits = [i for i in self.check(text, "议题")["issues"] if i["id"] == "HOS-034"]
        if not hits:
            return None
        self.assertEqual(len(hits), 1, hits)
        hit = hits[0]
        base = next(r for r in self.ruleset.rules if r.id == "HOS-034").message
        if hit["level"] == "P0":
            self.assertEqual(hit["message"], base)
            return ("P0", "p0")
        self.assertNotIn("没有提示程序倒置", hit["message"])
        kind = {v: k for k, v in hc.INVERSION_P1_MESSAGES.items()}
        return (hit["level"], kind.get(hit["message"], "未知文案：" + hit["message"]))

    def test_other_item_pairs(self) -> None:
        self.assertIsNone(self.verdict("我院已建成胸痛中心，现提请院长办公会审议创建卒中中心的实施方案。"))
        self.assertEqual(self.verdict("我院已建成胸痛中心，现提请院长办公会审议。"), ("P1", "same_sentence"))
        self.assertIsNone(self.verdict("已投入使用的信息系统需要升级改造，现提请院长办公会审议升级方案。"))
        self.assertIsNone(self.verdict("去年已采购的CT设备运行良好，现提请审议新购MRI设备事项。"))
        self.assertEqual(self.verdict("一期设备已于9月投入使用，现提请审议二期方案。"), ("P1", "other_item"))

    def test_changed_wording(self) -> None:
        self.assertEqual(self.verdict("本项目设备于9月采购到位并投入使用，现提请院长办公会审议。"), ("P1", "weak_exec"))
        self.assertEqual(self.verdict("本项目设备已于9月采购到位并投入使用，现提请院长办公会审议。"), ("P1", "same_sentence"))
        self.assertEqual(self.verdict("医院已与供应商签订采购合同，现提请院长办公会审议。"), ("P1", "same_sentence"))
        self.assertEqual(self.verdict("信息科已完成设备采购和安装调试，现提请院长办公会审议。"), ("P1", "same_sentence"))
        self.assertEqual(self.verdict("项目已开工建设，请予审议。"), ("P1", "same_sentence"))
        self.assertEqual(self.verdict("物资已全部采购到位，特提请审议。"), ("P1", "same_sentence"))
        self.assertEqual(self.verdict("设备已于9月投入使用。\n现提请院长办公会审议。"), ("P1", "adjacent"))

    def test_declaration_cannot_be_abused(self) -> None:
        real = "医院已与供应商签订采购合同，现提请院长办公会审议。"     # 只有组合判定：P1，声明只换文案
        self.assertEqual(self.verdict(real + "\n坚决杜绝程序倒置。"), ("P1", "same_sentence"))
        self.assertEqual(self.verdict(real + "\n各单位要防止出现先执行后决策问题。"), ("P1", "same_sentence"))
        self.assertEqual(self.verdict("现将有关情况如实报告如下。\n" + real), ("P1", "same_sentence"))
        self.assertEqual(self.verdict(real + "\n以上情况属于程序倒置，如实报告。"), ("P1", "declared"))
        # pattern 命中的 P0（“先行采购”）：套话、否定写法、另段声明都不降级
        regex_hit = "设备已先行采购，现提请院长办公会审议。"
        for tail in ("坚决杜绝程序倒置。", "各单位要防止出现先执行后决策问题。", "上述做法不属于程序倒置。", "经核查，上述事项不存在程序倒置。",
                     "该项目未发生程序倒置。", "此前已就程序倒置问题开展了自查。"):
            self.assertEqual(self.verdict(regex_hit + "\n" + tail), ("P0", "p0"), tail)
        self.assertEqual(self.verdict("现将有关情况如实报告如下。\n" + regex_hit), ("P0", "p0"))
        self.assertEqual(self.verdict("设备已先行采购。\n以上情况属于程序倒置，由会议决定后续处理。"), ("P1", "declared"))
        self.assertEqual(self.verdict("设备已先行采购，属于程序倒置，现如实报告。"), ("P1", "declared"))
        self.assertEqual(self.verdict("设备已先行采购，属于程序倒置，现提请追认。"), ("P0", "p0"))
        self.assertEqual(self.verdict("工程已先行开工，现提请审议工程投资方案。以上情况系程序倒置，现报请追认。"), ("P0", "p0"))

    def test_not_reported_plans_and_policies(self) -> None:
        for text in ("已完成论证，拟提交党委会议研究。", "本项目尚未开工，现提请董事会审议。",
                     "已于9月召开职代会审议通过，现提请院长办公会审议。",
                     "医院已完成《采购管理办法》修订稿，拟于11月提请院长办公会审议。",
                     "项目计划于9月开工，现提请院长办公会审议。"):
            with self.subTest(text=text):
                self.assertIsNone(self.verdict(text))


class ExemptionWindowPairTest(HospitalCheckBase):
    """豁免窗口成对对照：让步、例外、定语使处置类豁免失效；出处类带“尚未”等也失效。"""

    def ids(self, text: str, doc_type):
        return [(i["id"], i["level"]) for i in self.check(text, doc_type)["issues"] if i["id"] in ("HOS-033", "HOS-003")]

    def test_disposal_exemption_does_not_apply(self) -> None:
        for text in ("建议通过分解住院降低次均费用，该做法虽违规但效果明显，请各科室参照执行。",
                     "建议各科室通过调整编码提高CMI，去年巡察中已整改的科室除外。",
                     "建议通过分解住院降低次均费用，不符合规定的病例不纳入。"):
            with self.subTest(text=text):
                self.assertIn(("HOS-033", "P0"), self.ids(text, "整改"))

    def test_disposal_exemption_still_applies(self) -> None:
        """处置类只在命中所在分句内生效。"""
        for text in ("经医保办研判，有科室建议通过分解住院降低次均费用的做法违规，未予采纳。",
                     "医院否决了个别科室调整主要诊断编码以提高CMI的建议。",
                     "巡察指出部分科室存在调整编码提高四级手术占比的苗头，已整改。"):
            with self.subTest(text=text):
                self.assertEqual(self.ids(text, "整改"), [])
        self.assertIn(("HOS-033", "P0"), self.ids("建议调整主要诊断编码以提高CMI，不违规。", "整改"))

    def test_disposal_in_later_clause_is_reported(self) -> None:
        """收缩的已知代价：处置写在后一分句，重新被报出；后续分句里有针对该做法的处置词，P0 降为 P1。"""
        for text in ("有科室建议通过分解住院降低次均费用，经医保办研判，该做法违规，未予采纳。",
                     "对个别科室提出的调整主要诊断编码以提高CMI的建议，医院明确予以否决。"):
            with self.subTest(text=text):
                self.assertEqual(self.ids(text, "整改"), [("HOS-033", "P1")])
        # 后续分句里的处置词同样要过语境检查：避免违规、此前已有他科整改、他院也违规，都不算针对本处做法的处置，仍是 P0
        for text in ("建议调整主要诊断编码以提高CMI值，避免违规。",
                     "建议调整主要诊断编码以提高CMI值，此前已有科室完成整改。",
                     "建议调整主要诊断编码以提高CMI值，其他医院也违规这样做。",
                     "建议调整主要诊断编码以提高CMI值，确保不违规。"):
            with self.subTest(text=text):
                self.assertEqual(self.ids(text, "整改"), [("HOS-033", "P0")])
        # 后续分句出现的是出处词（排名），而 HOS-033 没有配置出处类豁免：不提示、不降级
        self.assertEqual(self.ids("建议调整主要诊断编码以提高CMI值，排名靠前。", "整改"), [("HOS-033", "P0")])

    def test_unrelated_disposal_word_in_same_clause_does_not_exempt(self) -> None:
        """同分句里与命中无关的处置词不能放过真违规：处置词在命中之前要是“否决……的建议”的指称结构，在命中之后要紧接且不并列别的事。"""
        for text in ("建议各科室整改到位后调整主要诊断编码以提高CMI值。",
                     "建议调整主要诊断编码以提高CMI值并已纠正部分漏填编码。",
                     "已整改科室建议调整主要诊断编码以提高CMI值。"):
            with self.subTest(text=text):
                self.assertEqual(self.ids(text, "整改"), [("HOS-033", "P0")])
        for text in ("对个别科室提出的调整主要诊断编码以提高CMI的建议予以否决。",
                     "医院否决了个别科室提出的调整主要诊断编码以提高CMI值的建议。"):
            with self.subTest(text=text):
                self.assertEqual(self.ids(text, "整改"), [])

    def test_source_exemption(self) -> None:
        """出处类在命中所在分句与紧邻的前一分句内生效；出处写在后一分句不再豁免（已知代价）。"""
        self.assertIn(("HOS-003", "P0"), self.ids("该技术国内领先，鉴定意见尚未出具。", "对外宣传"))
        self.assertIn(("HOS-003", "P0"), self.ids("鉴定意见尚未出具，该技术国内领先。", "对外宣传"))
        self.assertEqual(self.ids("经省科技厅鉴定，该技术国内领先。", "对外宣传"), [])
        self.assertEqual(self.ids("鉴定意见见附件，该技术国内领先。", "对外宣传"), [])
        # 后续分句里有出处词：不再豁免，对外宣传的 P0 降为 P1（仍报出）
        self.assertEqual(self.ids("该技术国内领先，经省科技厅鉴定。", "对外宣传"), [("HOS-003", "P1")])
        self.assertEqual(self.ids("该技术国内领先，鉴定意见见附件。", "对外宣传"), [("HOS-003", "P1")])
        # 后续分句里的出处同样要过语境检查：待出具、将发布、正在申请都不算出处，仍是 P0
        for text in ("该技术国内领先，有关鉴定意见待省科技厅出具。", "该技术国内领先，相关评价报告将于明年发布。",
                     "我院神经外科技术国内领先，正在申请省科技厅鉴定。"):
            with self.subTest(text=text):
                self.assertEqual(self.ids(text, "对外宣传"), [("HOS-003", "P0")])
        # 自评、院内评审、初步评价不是出处（B3）：前置、后置都仍是 P0
        for text in ("经自我评价，我院神经外科技术国内领先。", "经院内评审，我院神经外科技术国内领先。",
                     "经本院认定，我院神经外科技术国内领先。", "我院神经外科技术国内领先，经初步评价。"):
            with self.subTest(text=text):
                self.assertEqual(self.ids(text, "对外宣传"), [("HOS-003", "P0")])


class FileNameMaskingTest(HospitalCheckBase):
    """文件名回显：正文已识别的姓名在报告头和 JSON 的 file 字段里一并遮蔽；
    文件名里有、正文没识别到的姓名遮不住（已知局限，这里固定住当前行为）。"""

    def test_name_in_file_name_masked_when_recognised_in_body(self) -> None:
        path = self.tmp / "李建国_输液外渗RCA.txt"
        path.write_text("患者李建国术后发热。", encoding="utf-8")
        result = hc.check_file(path, "RCA", ruleset=self.ruleset)
        self.assertEqual(result["file"], "〔姓名1〕_输液外渗RCA.txt")
        self.assertNotIn("李建国", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("李建国", hc.render_text(result))
        code, out, _err = self.run_main(str(path), "--type", "RCA")
        self.assertEqual(code, 0)
        self.assertNotIn("李建国", out)
        code, out, _err = self.run_main(str(path), "--type", "RCA", "--json")
        self.assertNotIn("李建国", out)
        self.assertEqual(json.loads(out)["file"], "〔姓名1〕_输液外渗RCA.txt")

    def test_name_only_in_file_name_cannot_be_masked(self) -> None:
        path = self.tmp / "张丽丽_总结.txt"
        path.write_text("本季度质量总结。", encoding="utf-8")
        result = hc.check_file(path, "质量分析", ruleset=self.ruleset)
        self.assertEqual(result["file"], "张丽丽_总结.txt")  # 已知局限：正文没有识别到的姓名遮不住


class SecondNameAfterParentheticalTest(HospitalCheckBase):
    def test_both_names_recognised_and_no_surname_left(self) -> None:
        result = self.check("涉事医生：赵立新（主治医师）、钱敏（住院医师）。", "RCA")
        dumped = json.dumps(result, ensure_ascii=False)
        for name in ("赵立新", "钱敏", "赵", "钱"):
            self.assertNotIn(name, dumped)
        excerpts = [i["excerpt"] for i in result["issues"] if i["id"] == "HOS-032"]
        self.assertTrue(any("〔姓名1〕" in e for e in excerpts), excerpts)
        self.assertTrue(any("〔姓名2〕" in e for e in excerpts), excerpts)
        self.assertTrue(all(i["level"] == "P0" for i in result["issues"] if i["id"] == "HOS-032"))


class RepairRoundTest(HospitalCheckBase):
    """提交前复审回退项的修复：名字含“向从以于”、并列链整条登记与遮蔽、同一锚点并列姓名合并成一条、姓名表不分文书类型、自评不算出处。"""

    def dump(self, result) -> str:
        return json.dumps(result, ensure_ascii=False)

    def test_names_with_soft_chars_reported_p0(self) -> None:
        for name in ("宋向东", "刘向阳", "陈向前", "赵从军", "郑以诚", "胡于江"):
            with self.subTest(name=name):
                for text in (f"患者{name}，男，61岁，因胸痛入院。", f"当班护士{name}未执行查对。"):
                    result = self.check(text, "RCA")
                    self.assertEqual([(i["id"], i["level"]) for i in result["issues"]][:1],
                                     [("HOS-031" if text.startswith("患者") else "HOS-032", "P0")])
                    self.assertNotIn(name, self.dump(result))

    def test_function_word_usage_not_reported(self) -> None:
        for text in ("患者向医生反映疼痛", "患者从家中带来药物", "患者以头痛为主诉", "患者于昨日出院", "护士向家属说明情况",
                     "当班护士于22时巡视", "值班医师从急诊赶来"):
            with self.subTest(text=text):
                self.assertEqual([i["id"] for i in self.check(text, "RCA")["issues"] if i["id"].startswith("HOS-03")], [])

    def test_chain_items_all_masked_and_merged(self) -> None:
        for tail in ("澹台静", "杨柳", "苏醒", "方圆", "田野", "叶子"):
            with self.subTest(tail=tail):
                result = self.check(f"当事护士徐莉、高语桐、{tail}均已接受约谈。", "RCA")
                self.assertNotIn(tail, self.dump(result))
                rows = [i for i in result["issues"] if i["id"] == "HOS-032"]
                self.assertEqual(len(rows), 1, rows)       # 同一锚点下的并列姓名合并成一条
                self.assertEqual(rows[0]["excerpt"].count("〔姓名"), 3)
        result = self.check("当事护士刘佳、李娜两人已约谈。", "RCA")
        rows = [i for i in result["issues"] if i["id"] == "HOS-032"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["excerpt"].count("〔姓名"), 2)

    def test_name_table_covers_all_types(self) -> None:
        """姓名表覆盖全部隐私规则，不分文书类型：议题文书里 HOS-032 不适用，姓名仍要遮蔽。"""
        text = "当班护士邹秀云已约谈，邹秀云所在病区已先行采购输液泵，现提请审议。"
        result = self.check(text, "议题")
        self.assertNotIn("邹秀云", self.dump(result))
        self.assertFalse([i for i in result["issues"] if i["id"] == "HOS-032"])      # 是否报出仍按类型
        self.assertTrue([i for i in result["issues"] if i["id"] == "HOS-034"])

    def test_unrelated_dispose_word_not_exempt(self) -> None:
        for text in ("建议各科室整改到位后调整主要诊断编码以提高CMI值。", "建议调整主要诊断编码以提高CMI值并已纠正部分漏填编码。",
                     "已整改科室建议调整主要诊断编码以提高CMI值。"):
            with self.subTest(text=text):
                self.assertEqual([(i["id"], i["level"]) for i in self.check(text, "整改")["issues"] if i["id"] == "HOS-033"],
                                 [("HOS-033", "P0")])

    def test_declaration_downgrade_only_for_direct_assertion(self) -> None:
        for text in ("该项目已先行开工，是否属于程序倒置请会议研究。", "该项目已先行开工，属于程序倒置的说法不准确。",
                     "该项目已先行开工，有人认为属于程序倒置，我们认为不是。", "该项目已先行开工，难以认定属于程序倒置。",
                     "该项目已先行开工，谈不上属于程序倒置。", "其他单位因属于程序倒置被通报。该项目已先行开工，现提请审议。",
                     "该项目已先行开工，现提请审议。如属于程序倒置，按规定处理。"):
            with self.subTest(text=text):
                self.assertEqual([i["level"] for i in self.check(text, "议题")["issues"] if i["id"] == "HOS-034"], ["P0"])
        for text in ("项目已于9月先行开工，属于程序倒置，现如实报告。", "设备已先行采购。以上情况属于程序倒置，由会议决定后续处理。"):
            with self.subTest(text=text):
                self.assertEqual([i["level"] for i in self.check(text, "议题")["issues"] if i["id"] == "HOS-034"], ["P1"])
        self.assertEqual([i["level"] for i in self.check("该项目已先行开工，现提请审议。属于程序倒置。下一步补报审批。", "议题")["issues"]
                          if i["id"] == "HOS-034"], ["P0"])





class MarkdownNameTableTest(HospitalCheckBase):
    def run_table(self, name, body):
        return check_masked_outputs(hc.shared_kit().names, lambda: self._run_table(name, body))

    def _run_table(self, name, body):
        path = self.tmp / name
        path.write_text(body, encoding="utf-8")
        code, out, err = self.run_main(str(path), "--json")
        text_code, rendered, text_err = self.run_main(str(path))
        self.assertEqual(code, text_code)
        self.assertIn(code, (0, 1), err + text_err)
        return json.loads(out), rendered

    def test_sensitive_and_ordinary_rows_keep_document_numbering(self) -> None:
        body = ("| 患者姓名 | 诊断 |\n| --- | --- |\n| 王秀英 | 复查观察 |\n\n"
                "| 姓名 | 序号 |\n| --- | --- |\n| 王秀英 | 1 |\n| 欧阳明月 | 2 |\n")
        report, screen = self.run_table("王秀英附表.md", body)
        rows = [(i["id"], i["level"], i["line"], i["excerpt"]) for i in report["issues"]
                if i["id"] == "HOS-031"]
        self.assertEqual(rows, [("HOS-031", "P0", 3, "〔姓名1〕"),
                                ("HOS-031", "P1", 7, "〔姓名1〕"),
                                ("HOS-031", "P1", 8, "〔姓名2〕")])
        self.assertEqual(report["file"], "〔姓名1〕附表.md")
        for word in ("王秀英", "欧阳明月"):
            self.assertNotIn(word, json.dumps(report, ensure_ascii=False))
            self.assertNotIn(word, screen)
        for _, _, _, excerpt in rows:
            self.assertIn(excerpt, screen)
        sys.stderr.write(f"\nhospital 表格姓名正例：命中 {len(rows)}/3。\n")

    def test_absent_public_and_nonnames_are_not_registered(self) -> None:
        controls = [
            ("王秀英", "| 编号 | 诊断 |\n| --- | --- |\n| 王秀英 | 记录 |\n"),
            ("王秀英", "| 联系人姓名 | 诊断 |\n| --- | --- |\n| 王秀英 | 记录 |\n"),
        ]
        controls.extend((cell, f"| 姓名 | 诊断 |\n| --- | --- |\n| {cell} | 记录 |\n")
                        for cell in ("合计", "小计", "无", "/", "—", "高一", "五年级", "宣传科", "123"))
        misfires = 0
        for name, body in controls:
            with self.subTest(name=name, body=body):
                file_name = ("斜线" if name == "/" else name) + "附表.md"
                report, screen = self.run_table(file_name, body)
                rows = [i for i in report["issues"] if i["id"] == "HOS-031"]
                misfires += len(rows)
                self.assertEqual(rows, [])
                self.assertEqual(report["file"], file_name)
                self.assertNotIn("〔姓名", screen)
        sys.stderr.write(f"\nhospital 表格姓名反例：误报 {misfires}/{len(controls)}。\n")

if __name__ == "__main__":
    unittest.main()
