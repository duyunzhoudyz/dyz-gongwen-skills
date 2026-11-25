"""用真实 CLI 检查第五轮原始输入、补充对照及新样例的规则、级别和全文遮蔽。"""
import unittest

from tests.names.test_name_review_round4 import UNKNOWN, check_input, fixture


class NameReviewRoundFiveTest(unittest.TestCase):
    def check_case(self, case):
        report, rows, registered = check_input(case)
        actual = [(r["id"], "?" if r["level"] == "P1" and r["message"] == UNKNOWN else r["level"][1:]) for r in rows]
        self.assertCountEqual(actual, [(case["rule"], grade) for grade in case["expect"]])
        if not case["expected_names"] and "?" not in case["expect"]:
            self.assertFalse(registered)
            self.assertEqual(report["file"], case["filename"])
        if case.get("mode") == "comments":
            self.assertIn("〔姓名", report["entries"][0]["label"])


def probe_test(case):
    def test(self):
        self.check_case(case)
    return test


samples = fixture("review_r5_inputs.json")
assert len(samples["main"]) == 30 and len(samples["supplemental"]) == 38 and len(samples["new"]) >= 30
for group in samples.values():
    for sample in group:
        setattr(NameReviewRoundFiveTest, "test_" + sample["id"], probe_test(sample))
