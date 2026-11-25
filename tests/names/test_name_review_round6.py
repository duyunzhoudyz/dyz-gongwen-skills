"""第六轮处分框架与表格已知局限，通过行业 CLI 同查登记、JSON 和屏幕遮蔽。"""
import unittest

from tests.industry_corpus.test_industry_corpus import load_engine
from tests.names.test_name_review_round4 import UNKNOWN, check_input, fixture


class NameReviewRoundSixTest(unittest.TestCase):
    def check_soe(self, case):
        report, rows, registered = check_input(case)
        names = case["expected_names"]
        self.assertEqual(registered, set(names))
        self.assertEqual([(r["line"], r["id"], r["level"]) for r in rows], [(1, "SOE-022", "P0")] * len(names))
        self.assertEqual(report["file"], "〔姓名1〕.md" if names else case["filename"])

    def check_html_fallback(self, case):
        report, rows, _ = check_input(case)
        rule = "SOE-022" if case["engine"] == "soe" else "HOS-031"
        self.assertEqual([(r["line"], r["id"], r["level"], r["message"]) for r in rows], [(3, rule, "P1", UNKNOWN)])
        self.assertRegex(report["file"], r"^〔姓名\d+〕\.md$")

    def check_html_split_name(self, case):
        # 实体/注释夹在二字名中时，未登记的姓名会出现在文件名和其他规则的上下文。
        report, rows, registered = check_input(case)
        self.assertEqual(registered, set(case["registered"]))
        self.assertEqual([(r["line"], r["id"], r["level"]) for r in rows], [(3, "HOS-031", "P1")])
        self.assertEqual(report["file"], case["filename"])
        contexts = [r["context"] for r in report["issues"] if r["id"] == "HOS-002"]
        self.assertTrue(any(case["exposed_name"] in s for s in contexts), contexts)

    def test_R6_40_collective_prefix_real(self):
        # 无职务时，两版基线均未识别张伟。允许后续提升召回，项目部不得当作姓名。
        body = "对项目部张伟给予警告处分，张伟项目先行开工。"
        _, rows, registered = check_input(dict(soe_case(body, ""), filename="张伟.md"))
        self.assertLessEqual(registered, {"张伟"})
        self.assertEqual([(r["id"], r["level"]) for r in rows], [("SOE-022", "P0")] if registered else [])

    def test_office_modifiers_with_and_without_name(self):
        lex = load_engine("soe")._shared()[2]
        for modifier in sorted(lex.office_modifiers) + ["原任全部", "所担任的全部"]:
            for name in ("王建国", ""):
                with self.subTest(modifier=modifier, name=name):
                    self.check_soe(soe_case(f"撤销{name}{modifier}党内职务。", name))

    def test_titles_notes_and_modifiers(self):
        for right in ("同志现任", "同志（原总经理）所担任的", "的原有", "原先担任的"):
            with self.subTest(right=right):
                self.check_soe(soe_case(f"撤销王建国{right}党内职务。", "王建国"))

    def test_modifier_can_be_part_of_full_name(self):
        for name in ("欧阳原任", "欧阳常任", "欧阳现任"):
            for title in ("", "副部长"):
                with self.subTest(name=name, title=title):
                    self.check_soe(soe_case(f"撤销{title}{name}党内职务。", name))

    def test_collectives_in_disposition_frames(self):
        for word in "党支部 党工委 党小组 常委会 党委会 总支委员会 支部委员会 职代会 股东会".split():
            for body in (f"对{word}予以停职检查。", f"{word}受到记过处分。", f"撤销{word}所任党内职务。"):
                with self.subTest(body=body):
                    self.check_soe(soe_case(body, ""))


def soe_case(body, name):
    return {"id": "处分框架", "engine": "soe", "filename": (name or "clean") + ".md", "body": body,
            "expected_names": [name] if name else []}


def probe_test(check, case):
    def test(self):
        check(self, case)
    return test


samples = fixture("review_r6_inputs.json")
for group, check in (("soe_person", NameReviewRoundSixTest.check_soe), ("soe_clean", NameReviewRoundSixTest.check_soe),
                     ("html_fallback", NameReviewRoundSixTest.check_html_fallback),
                     ("html_split_name", NameReviewRoundSixTest.check_html_split_name)):
    for sample in samples[group]:
        setattr(NameReviewRoundSixTest, "test_" + sample["id"], probe_test(check, sample))
