"""复跑评审原件和新增样例。0/1 分别为实名 P0/P1，? 为该行的兜底 P1。"""
import json
import tempfile
import unittest
from pathlib import Path

from tests.industry_corpus.test_industry_corpus import build_argv, load_engine, run_engine
from tests.names.masking import check_masked_outputs
from tests.names.test_name_review_regressions import md

FIXTURES = Path(__file__).with_name("fixtures")
UNKNOWN = "姓名列内容未能识别，请人工核对"
RULES = {"hos": {"HOS-031"}, "soe": {"SOE-022", "SOE-023"}, "k12": {"K12-G04"}}


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def review_cases():
    source = fixture("review_r4_inputs.json")
    expected = {}
    for levels, keys in (
        ("0", "A01 A02 A03 A04 A05 A06 A08_orig A09_orig A10_orig A12 A14a A14b A14c A15_orig A16_orig B03 B04_orig R3_chenxinghe R3_wangjianyu R3_heming"),
        ("1", "A07 A13a A13b A13c A13d A13e A13_ganbu A13_zhuguan A14d"),
        ("01", "A11"), ("00", "B01 B02 B05 B07 B08 B10_orig R3_hejianguo"),
        ("?", "B06_orig"), ("0?", "B09 B11_orig"), ("", "B12_orig B13_orig B14 B15 D16 D17"),
    ):
        expected.update(dict.fromkeys(keys.split(), levels))
    for case in source["round3_originals"]:
        yield dict(case, expect=expected[case["id"]])
    for idx, cell in enumerate(source["round3_m1_clean_cells"], 1):
        yield {"id": f"M1_{idx:02d}", "engine": "hos", "filename": "clean.md", "expected_names": [], "expect": "",
               "body": md("| 患者姓名 | 诊断 |", f"| {cell} | 哮喘 |")}
    # B1 科/班尾姓名，B2 括号，B3 带前缀残段，B4 框架召回，B5 单位动作，
    # M1 同级对照及其后连词、格式、评语、公开名单的独立复现。
    levels = [
        "?", "?", "?", "0?", "?", "?", "00", "00", "0", "0", "0", "0", "0", "00",
        "?", "?", "?", "?", "?", "0", "0", "0", "0", "0", "", "", "", "", "",
        "1", "1", "1", "1", "00", "000", "00", "00", "00", "00", "0001", "?", "", "0?", "1", "",
    ]
    attacks = source["round4_new_attacks"]
    assert len(attacks) == len(levels) == 45
    for idx, (case, grade) in enumerate(zip(attacks, levels), 1):
        assert case["id"].startswith(f"R4_{idx:02d}_")
        yield dict(case, expect=grade)


def check_input(case):
    domain = {"hos": "hospital"}.get(case["engine"], case["engine"])
    mod = load_engine(domain)
    if domain == "hospital":
        gn = mod.shared_kit().names
    elif domain == "soe":
        gn = mod._shared()[0]
    else:
        gn = mod.shared_names()[0]
    doc = {"type": case.get("doc_type") or ("纪要" if domain == "soe" else None), "mode": case.get("mode")}
    registered = set()
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / case["filename"]
        path.write_text(case["body"], encoding="utf-8")

        def run():
            reports = []
            for as_json in (True, False):
                code, out, err = run_engine(mod, build_argv(domain, path, doc, as_json))
                if code:
                    raise AssertionError((code, err))
                reports.append(json.loads(out) if as_json else out)
            return tuple(reports)

        if case["id"] == "B13_orig":  # 非表格评语保留本机定位标签。
            report, screen = run()
            assert report["entries"][0]["label"] == "王秀英"
        else:
            report, screen = check_masked_outputs(gn, run, case["expected_names"], registered=registered)
    rows = [issue for issue in report["issues"] if issue["id"] in RULES[case["engine"]]]
    return report, rows, registered


class NameReviewRoundFourTest(unittest.TestCase):
    def check_input(self, case):
        report, rows, registered = check_input(case)
        grades = ["?" if i["level"] == "P1" and i["message"] == UNKNOWN else i["level"][1:] for i in rows]
        self.assertCountEqual(grades, list(case["expect"]), rows)
        if not case["expected_names"] and case["id"] != "B13_orig":
            self.assertFalse(registered)
            self.assertEqual(report["file"], case["filename"])
        if case["id"] in ("B14", "B15") or case["id"].startswith("R4_42"):
            self.assertIn("〔姓名", report["entries"][0]["label"])
        if case["id"] == "A11" or case["id"].startswith("R4_40"):
            expected = [(2, "P0"), (3, "P1")] if case["id"] == "A11" else [(2, "P0"), (3, "P0"), (4, "P0"), (6, "P1")]
            self.assertEqual([(i["line"], i["level"]) for i in rows], expected)
        if case["id"].startswith("A13") or case["id"].startswith("R4_44"):
            self.assertEqual(rows[0]["message"], "可能是单位简称，请人工确认" if case["id"] == "A13e" else "文内已定义为单位简称，如确指单位可忽略")

    def test_department_suffix_can_belong_to_name_or_action(self):
        for value, name in (("王秀英返班", "王秀英"), ("值守李科", "李科"), ("王建科复诊后返班", "王建科")):
            with self.subTest(value=value):
                self.check_input({"id": "部门尾字", "engine": "hos", "filename": name + ".md",
                                  "body": md("| 患者姓名 | 诊断 | 说明 |", f"| {value} | 哮喘 | {name}治愈率100% |"),
                                  "expected_names": [name], "expect": "?"})

    def test_mixed_placeholders_are_exact(self):
        for value in ("王某、N/A、共5人", "〔姓名1〕、〔姓名2〕", "—、N/A、合计3人", "（空）／见附件"):
            with self.subTest(value=value):
                self.check_input({"id": "混合占位", "engine": "hos", "filename": "汇总.md",
                                  "body": md("| 患者姓名 | 诊断 |", f"| {value} | 哮喘 |"),
                                  "expected_names": [], "expect": ""})

    def test_reference_hits(self):
        reference = fixture("name_reference_hits.json")
        cases = {c["id"]: c for c in REVIEW + ADVERSARIAL}
        self.assertCountEqual([r["id"] for r in reference["cases"]], list(cases))
        for sample in reference["cases"]:
            case = cases[sample["id"]]
            with self.subTest(case=sample["id"]):
                _, current, registered = check_input(case)
                previous = [sample[commit[:7]] for commit in reference["references"]]
                baseline = {(line, rule, level) for result in previous for line, rule, level in result["issues"]}
                expected_names = {name for result in previous for name in result["registered"]}
                self.assertTrue(expected_names <= registered)
                if expected_names:
                    for line, rule, level in baseline:
                        if line in sample.get("org_p1", []):
                            self.assertTrue(any(i["line"] == line and i["id"] == rule and i["level"] == "P1"
                                                and "单位简称" in i["message"] for i in current))
                        else:
                            self.assertTrue(any(i["line"] == line and i["id"] == rule and i["level"] <= level
                                                for i in current), (line, rule, level))
                additions = set()
                for issue in current:
                    line, rule, level = issue["line"], issue["id"], issue["level"]
                    if not (level == "P0" or issue["message"] == UNKNOWN):
                        continue
                    if any(line == l and rule == r and g <= level for l, r, g in baseline):
                        continue
                    category = sample.get("exceptions", {}).get(str(line))
                    self.assertIn(str(category), reference["exception_types"], issue)
                    if category == 3:
                        self.assertIn("|", case["body"])
                    else:
                        self.assertEqual(rule, "SOE-022")
                        self.assertTrue(registered.intersection(case["expected_names"]))
                    additions.add(str(line))
                self.assertEqual(additions, set(sample.get("exceptions", {})))


def probe_test(case):
    def test(self):
        self.check_input(case)
    return test


REVIEW = list(review_cases())
ADVERSARIAL = fixture("name_adversarial_r4.json")
assert len(REVIEW) == 122
for item in REVIEW + ADVERSARIAL:
    setattr(NameReviewRoundFourTest, "test_" + item["id"], probe_test(item))
