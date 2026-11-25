"""评语入口编号净化回归，包括第 1 轮评审的复现输入。"""
import csv
import io
import json
import unittest

from tests.k12.test_k12_check import HAS_DOCX, K12TestCase, SAMPLES, k12_check


def assert_hidden(test, rendered, report, originals, *, static=()):
    """比对完整文本和序列化 JSON。碰撞用例保留并单独断言静态字面量。"""
    for value in static:
        test.assertTrue(value in rendered or value in json.dumps(report, ensure_ascii=False), value)
    for output in (rendered, json.dumps(report, ensure_ascii=False)):
        for value in static:
            output = output.replace(value, "")
        for value in originals:
            test.assertNotIn(value, output)


TABLE_VARIANTS = (
    ("导出学生 学 号 （系统内部编号请勿对外使用）", "AB 9187", "md"),
    ("准考证号码(本学期)", "B85-740", "csv"),
    ("考 生 号", "Z-654 AB", "docx"),
    ("学籍异动记录（以前年度）", "G62 7292", "csv"),
    ("证件尾号(打码前)", "4543", "md"),
    ("身份证号码", "111102-20171111-369X", "docx"),
    ("家长手机（备用）", "158 2288 2634", "csv"),
    ("联系 电话", "0411-86930023", "md"),
    ("紧急联系方式", "ABX 724-503", "docx"),
    ("教师工号", "KL-889G", "csv"),
    ("本市内部编号", "BL 840 XY", "md"),
    ("编 号", "S096", "csv"),
    ("学生 学号", "甲区 2394", "csv"),
    ("学生考号", "ALPHAOMEGA", "md"),
    ("考 生 号（新）", "34", "docx"),
    ("档案编号", "袋 A/蓝 区", "csv"),
    ("准考证号", "J45  670K", "md"),
    ("本校考号", "2026-01-12", "csv"),
    ("家长手机号", "00986-55", "docx"),
    ("编号", "K", "md"),
    ("编号", "年份 报告句子", "csv"),
)

INLINE_VARIANTS = (
    ("学号为：TM44-91", ("TM44-91",)),
    ("考号是 : TM44 92", ("TM44 92",)),
    ("考生号（后四位）为 4507", ("4507",)),
    ("学籍号码(旧)是：F-9780", ("F-9780",)),
    ("证件号码：2002Z、2003Y", ("2002Z", "2003Y")),
    ("身份证 110105 20130202 432X", ("110105 20130202 432X",)),
    ("手机是165-9981-0097", ("165-9981-0097",)),
    ("电话：0351 647-0291", ("0351 647-0291",)),
    ("联系方式为 XN54-879, XN55-351", ("XN54-879", "XN55-351")),
    ("教师工号 H-7873和H-5730", ("H-7873", "H-5730")),
    ("编号是：QA-0430，QQ-9271", ("QA-0430", "QQ-9271")),
    ("准考证为M438—附注", ("M438",)),
    ("准考证号码是JR49\t90B", ("JR49\t90B",)),
    ("你的号码录入档案6789112。", ("6789112",)),
    ("档案中的110105-20130503-764X。", ("110105-20130503-764X",)),
    ("号码留在这里15981936719。", ("15981936719",)),
    ("号码留在这里110105 20130503 764X。", ("110105 20130503 764X",)),
    ("编号：BG09 – 43、Q56－85", ("BG09 – 43", "Q56－85")),
    ("考生号A0和99B·备注", ("A0", "99B")),
    ("工号：T435637。", ("T435637",)),
)


class CommentPrivacyTests(K12TestCase):
    def write_input(self, filename, source):
        if filename.endswith(".docx"):
            import docx

            path = self.tmp / filename
            document = docx.Document()
            table = document.add_table(rows=len(source), cols=len(source[0]))
            for row, values in zip(table.rows, source):
                for cell, value in zip(row.cells, values):
                    cell.text = value
            document.save(path)
            return path
        if isinstance(source, list):
            if filename.endswith(".md"):
                source = "\n".join(k12_check.render_md_table(source))
            else:
                buffer = io.StringIO()
                csv.writer(buffer).writerows(source)
                source = buffer.getvalue()
        return self.write(filename, source)

    def check_output(self, comments, facts, originals, *, static=()):
        path = self.write_input(*comments)
        args = ("comments", str(path))
        if facts:
            args += ("--facts", str(self.write_input(*facts)))
        rc, rendered, err = self.run_main(*args)
        self.assertEqual((rc, err), (0, ""))
        report = self.run_json(*args)
        assert_hidden(self, rendered, report, originals, static=static)
        return rendered, report

    def check_review_cases(self, *, word):
        rows = (SAMPLES / "comment_privacy_review.jsonl").read_text(encoding="utf-8").splitlines()
        for raw in rows:
            case = json.loads(raw)
            if case["comments"][0].endswith(".docx") != word:
                continue
            with self.subTest(case=case["id"]):
                rendered, report = self.check_output(case["comments"], case["facts"], case["hide"],
                                                     static=case.get("static", ()))
                self.assertEqual(report["mode"], "comments")
                self.assertTrue(rendered.startswith("学生评语检查："))
                for value in case.get("preserve", ()):
                    self.assertIn(value, rendered)
                    self.assertIn(value, json.dumps(report, ensure_ascii=False))
                if "quantities" in case:
                    self.assertEqual({i["excerpt"] for i in report["issues"] if i["id"] == "PY-016"},
                                     set(case["quantities"]))
                if case["id"] in {"11_text_real_label_with_table_facts", "facts_table_text_comments_py007_py015.txt"}:
                    pair = next(i for i in report["issues"] if i["id"] == "PY-007")
                    self.assertEqual(pair["label"], "李明")
                    self.assertIn("王小明 与 李明", pair["message"])
                    missing = [i for i in report["issues"] if i["id"] == "PY-015"]
                    self.assertEqual({i["label"] for i in missing}, {"张小红", "〔姓名3〕"})
                    for issue in missing:
                        self.assertIn(issue["label"], issue["message"])

    def test_review_cases(self):
        self.check_review_cases(word=False)

    @unittest.skipUnless(HAS_DOCX, "需要既有可选库 python-docx")
    def test_review_word_case(self):
        self.check_review_cases(word=True)

    def check_table_variants(self, *, word):
        for header, value, fmt in TABLE_VARIANTS:
            if (fmt == "docx") != word:
                continue
            with self.subTest(header=header, value=value, fmt=fmt):
                # 两侧仅有编号可对账。事实表额外的普通数字必须保留。
                comments = [[header, "评语"], [value, "你读书13本，表现很笨。"]]
                facts = [[header, "具体表现"], [value, "你读书7本。"]]
                filename = f"评语_{value}.{fmt}" if "/" not in value else f"评语.{fmt}"
                _text, report = self.check_output((filename, comments), ("facts." + fmt, facts), (value,))
                self.assertEqual(report["entries"][0]["label"], "〔编号1〕")
                self.assertIn("〔编号1〕", report["file"] if "/" not in value else report["entries"][0]["label"])
                self.assertEqual({i["excerpt"] for i in report["issues"] if i["id"] == "PY-016"}, {"13"})
                self.assertNotIn("PY-015", self.ids(report))

    def test_markdown_and_csv_variants(self):
        self.check_table_variants(word=False)

    @unittest.skipUnless(HAS_DOCX, "需要既有可选库 python-docx")
    def test_word_variants(self):
        self.check_table_variants(word=True)

    def test_inline_variants(self):
        for note, originals in INLINE_VARIANTS:
            with self.subTest(note=note):
                filename = f"评语_{originals[0]}.txt" if "\t" not in originals[0] else "评语.txt"
                comment = f"S01：你读书17本，你很笨。{note}，应继续努力。"
                _, report = self.check_output((filename, comment), ("facts.txt", "S01：读书8本。"), originals)
                self.assertIn("〔编号1〕", report["file"] if "\t" not in originals[0]
                              else next(i["excerpt"] for i in report["issues"] if i["id"] == "PY-001"))
                self.assertEqual({i["excerpt"] for i in report["issues"] if i["id"] == "PY-016"}, {"17"})
                if note.startswith(("档案中的", "号码留在", "你的号码")):
                    self.assertIn("PY-005", self.ids(report))

    def test_quantities_dates_and_numbered_rows_keep_their_meaning(self):
        comments = ("| 序号 | 学号 | 评语 |\n|---|---|---|\n"
                    "| 53 | 338517 | 你读书338517本，体育考了96分，2026-11-21参加17次劳动，"
                    "为5班捐款150000.65元。 |")
        facts = ("| 序号 | 学号 | 具体表现 |\n|---|---|---|\n"
                 "| 53 | 338517 | 读书3本，体育考了93分，2026-11-25参加7次劳动，为4班捐款150000.55元。 |")
        # 同一数值只在“学号”列是编号。数量出现是预期。
        _, report = self.check_output(
            ("draft_338517.md", comments), ("facts.md", facts), ("338517",),
            static=("338517本", "数字“338517”", "原文：“338517”", '"excerpt": "338517"'))
        self.assertNotIn("338517", report["file"])
        self.assertEqual(report["entries"][0]["label"], "53")
        self.assertEqual({i["excerpt"] for i in report["issues"] if i["id"] == "PY-016"},
                         {"338517", "96", "21", "17", "5", "150000.65"})

    def test_filename_reuses_bare_id_with_adjacent_ascii_and_inline_value(self):
        raw_id, marked_id = "110105-20130503-764X", "A369-J0"
        _, report = self.check_output(
            (f"draft{raw_id}and{marked_id}suffix.txt",
             f"S01：你很笨，资料里出现{raw_id}，工号是{marked_id}。"),
            None, (raw_id, marked_id, "110105", "20130503", "764X"))
        self.assertRegex(report["file"], r"^draft〔编号\d+〕and〔编号\d+〕suffix\.txt$")

    def test_filename_masks_numbered_part_from_a_table_cell_or_inline_value(self):
        text = ("| 学号 | 评语 |\n|---|---|\n"
                "| 甲区 39684 / 乙区 | 你很笨，电话是FA19-36 CD70-26。 |")
        _, report = self.check_output(("评语_39684_CD70-26.md", text), None,
                                      ("39684", "FA19-36", "CD70-26"))
        first, second = report["file"].removeprefix("评语_").removesuffix(".md").split("_")
        self.assertEqual(report["entries"][0]["label"], first)
        self.assertNotEqual(first, second)

    def test_distinct_table_numbers_keep_internal_spaces_for_matching(self):
        comments = [["学号", "评语"], ["QB 7672", "你读书17本。"], ["QB7672", "你读书13本。"]]
        facts = [["学号", "具体表现"], ["QB7672", "读书13本"], ["QB 7672", "读书17本"]]
        _, report = self.check_output(("notes.md", comments), ("facts.csv", facts), ("QB 7672", "QB7672"))
        self.assertEqual([e["label"] for e in report["entries"]], ["〔编号1〕", "〔编号2〕"])
        self.assertTrue({"PY-015", "PY-016"}.isdisjoint(self.ids(report)))
