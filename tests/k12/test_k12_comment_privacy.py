"""评语入口编号净化回归，包括六轮评审的复现输入。"""
import csv
import io
import json
import unittest
from collections import Counter
from contextlib import contextmanager
from hashlib import sha256
from unittest.mock import patch

from tests.k12.test_k12_check import HAS_DOCX, K12TestCase, REPO_ROOT, SAMPLES, k12_check


def assert_hidden(test, rendered, report, originals, *, static=()):
    """比对完整文本和序列化 JSON。碰撞用例保留并单独断言静态字面量。"""
    for value in static:
        test.assertTrue(value in rendered or value in json.dumps(report, ensure_ascii=False), value)
    for output, serialized in ((rendered, False), (json.dumps(report, ensure_ascii=False), True)):
        for value in static:
            output = output.replace(value, "")
        for value in originals:
            test.assertNotIn(json.dumps(value, ensure_ascii=False)[1:-1] if serialized else value, output)


def assert_py005(test, report, baseline):
    hits = [[i["line"], i["message"].removeprefix("评语中出现")]
            for i in report["issues"] if i["id"] == "PY-005"]
    test.assertEqual(hits, list(baseline))


def py016_numbers(report):
    return {issue["message"].split("“", 1)[1].split("”", 1)[0]
            for issue in report["issues"] if issue["id"] == "PY-016"}


def rule_hits(report):
    return Counter((i["id"], i["level"], i["line"], i["category"],
                    i["message"] if i["id"] in ("PY-005", "PY-016") else "")
                   for i in report["issues"])


def assert_prose_preserved(test, bodies, originals, keep=()):
    """逐次还原正文替换，要求每个新占位符只对应本用例点名的编号。"""
    test.assertTrue(bodies)
    replaced = set()
    for raw, clean, tokens in bodies:
        raw_index = clean_index = 0
        for match in k12_check.COMMENT_NUMBER_TOKEN_RE.finditer(clean):
            literal = clean[clean_index:match.start()]
            test.assertTrue(raw.startswith(literal, raw_index), raw)
            raw_index += len(literal)
            if raw.startswith(match[0], raw_index):
                value = match[0]
            else:
                forms = tokens.get(match[0], ())
                value = next((form for form in forms if raw.startswith(form, raw_index)), None)
                test.assertIn(value, originals, f"正文被误替换：{raw!r}")
                replaced.add(value)
            raw_index += len(value)
            clean_index = match.end()
        test.assertEqual(clean[clean_index:], raw[raw_index:])
    cleaned = "\n".join(body for _, body, _ in bodies)
    for value in keep:
        test.assertIn(value, cleaned)
    return replaced


@contextmanager
def capture_prose():
    bodies = []
    clean = k12_check.CommentNumbers.clean_prose

    def record(numbers, raw, *args):
        safe = clean(numbers, raw, *args)
        tokens = {}
        for value, token in (numbers.forms | numbers.alias_values).items():
            if token not in raw and value in raw:
                tokens.setdefault(token, []).append(value)
        for forms in tokens.values():
            forms.sort(key=len, reverse=True)
        bodies.append((raw, safe, tokens))
        return safe

    with patch.object(k12_check.CommentNumbers, "clean_prose", record):
        yield bodies


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
    def write_input(self, filename, source, *, bom_crlf=False):
        if filename.endswith(".xlsx"):
            try:
                import openpyxl
            except ImportError:
                self.skipTest("openpyxl unavailable")

            path = self.tmp / filename
            workbook = openpyxl.Workbook()
            for row in source:
                workbook.active.append(row)
            workbook.save(path)
            return path
        if filename.endswith(".docx"):
            import docx

            path = self.tmp / filename
            document = docx.Document()
            tables = source if source and isinstance(source[0][0], list) else [source]
            for rows in tables:
                table = document.add_table(rows=len(rows), cols=len(rows[0]))
                for row, values in zip(table.rows, rows):
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
        if bom_crlf:
            path = self.tmp / filename
            path.write_bytes(("\ufeff" + source.replace("\r\n", "\n").replace("\n", "\r\n")).encode("utf-8"))
            return path
        return self.write(filename, source)

    def check_output(self, comments, facts, originals, *, static=(), baseline=(), keep_prose=(), prose_ids=None,
                     stage="义务教育", person="second", bom_crlf=False, exact_prose=False):
        path = self.write_input(*comments, bom_crlf=bom_crlf) if isinstance(comments, (list, tuple)) else comments
        args = ("comments", str(path), "--stage", stage, "--person", person)
        if facts:
            fact_path = self.write_input(*facts, bom_crlf=bom_crlf) if isinstance(facts, (list, tuple)) else facts
            args += ("--facts", str(fact_path))
        with capture_prose() as bodies:
            rc, rendered, err = self.run_main(*args)
        self.assertEqual((rc, err), (0, ""))
        report = self.run_json(*args)
        assert_hidden(self, rendered, report, originals, static=static)
        assert_py005(self, report, baseline)
        expected_prose = originals if prose_ids is None else prose_ids
        replaced = assert_prose_preserved(self, bodies, expected_prose, keep_prose)
        if exact_prose:
            self.assertEqual(replaced, set(expected_prose))
        return rendered, report

    def assert_frozen_report(self, rendered, report, expected_digest):
        self.assertNotIn("〔编号", rendered)
        self.assertEqual(rendered, k12_check.render_check_text(report) + "\n")
        serialized = json.dumps([report, rendered.removesuffix("\n")], ensure_ascii=False,
                                separators=(",", ":"))
        self.assertEqual(sha256(serialized.encode("utf-8")).hexdigest(), expected_digest)

    def assert_frozen_hits(self, report, case):
        baseline = Counter(map(tuple, case["baseline_hits"]))
        removed = Counter(map(tuple, case["remove"]))
        added = Counter(map(tuple, case["add"]))
        self.assertFalse(removed - baseline, (removed, baseline))
        self.assertEqual(rule_hits(report), baseline - removed + added)

    def check_review_cases(self, *, word):
        rows = (SAMPLES / "comment_privacy_review.jsonl").read_text(encoding="utf-8").splitlines()
        for raw in rows:
            case = json.loads(raw)
            if case["comments"][0].endswith(".docx") != word:
                continue
            with self.subTest(case=case["id"]):
                rendered, report = self.check_output(case["comments"], case["facts"], case["hide"],
                                                     static=case.get("static", ()), baseline=case["baseline_py005"],
                                                     keep_prose=case.get("known", ()))
                self.assertEqual(report["mode"], "comments")
                self.assertTrue(rendered.startswith("学生评语检查："))
                for value in case.get("preserve", ()):
                    self.assertIn(value, rendered)
                    self.assertIn(value, json.dumps(report, ensure_ascii=False))
                if "quantities" in case:
                    self.assertEqual(py016_numbers(report), set(case["quantities"]))
                if "ordinary_digest" in case:
                    self.assert_frozen_report(rendered, report, case["ordinary_digest"])
                if case["id"] == "10_same_cell_combined_header":
                    first = next(i for i in report["issues"] if i["id"] == "PY-001")
                    self.assertTrue(first["excerpt"].startswith("〔姓名1〕 〔编号1〕"))
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

    def check_round2_cases(self, *, word):
        rows = (SAMPLES / "comment_privacy_review_r2.jsonl").read_text(encoding="utf-8").splitlines()
        for raw in rows:
            case = json.loads(raw)
            comments, facts = case.get("comments"), case.get("facts")
            has_word = any(source and source[0].endswith(".docx") for source in (comments, facts))
            if has_word != word:
                continue
            with self.subTest(case=case["id"]):
                if case.get("examples"):
                    folder = REPO_ROOT / "examples/D-中小学评语本地脱敏与还原"
                    comments = folder / "2-模型生成评语-编号版.txt"
                    facts = folder / "1-本机脱敏事实表.md"
                rendered, report = self.check_output(
                    comments, facts, case.get("must_hide", ()), baseline=case["baseline_py005"],
                    static=case.get("static", ()), keep_prose=case.get("keep_prose", ()))
                serialized = json.dumps(report, ensure_ascii=False)
                for value in case.get("must_keep_txt", ()):
                    self.assertIn(value, rendered)
                for value in case.get("must_keep_json", ()):
                    self.assertIn(value, serialized)
                ids = set(self.ids(report))
                quantities = py016_numbers(report)
                self.assertLessEqual(set(case.get("expect_ids", ())), ids)
                self.assertTrue(ids.isdisjoint(case.get("forbid_ids", ())))
                self.assertLessEqual(set(case.get("expect_py016", ())), quantities)
                cid = case["id"].split("_", 1)[0]
                if cid == "V11":
                    excerpt = next(i["excerpt"] for i in report["issues"] if i["id"] == "PY-001")
                    self.assertIn("无可救药", excerpt)
                    self.assertNotIn("〔编号", excerpt)
                if cid == "V22":
                    self.assertEqual(report["entries"][0]["label"], "〔编号1〕")
                    self.assertIn("〔编号1〕", report["file"])
                    self.assertNotIn("〔编号2〕", serialized)
                if cid == "V25":
                    for issue in report["issues"]:
                        if issue["id"] in {"PY-007", "PY-008"}:
                            self.assertNotIn("〔姓名", issue["message"])
                        if issue["id"] in {"PY-007", "PY-015"}:
                            self.assertIn(issue["label"], issue["message"])
                if cid == "V28":
                    self.assertEqual([e["label"] for e in report["entries"]], ["S01", "S02", "S03", "S04"])

    def test_round2_review_cases(self):
        self.check_round2_cases(word=False)

    @unittest.skipUnless(HAS_DOCX, "需要既有可选库 python-docx")
    def test_round2_review_word_cases(self):
        self.check_round2_cases(word=True)

    def test_round3_review_and_ordinary_prose_against_baseline(self):
        # 普通输入冻结集成基线的完整 JSON 和文本。
        path = SAMPLES / "comment_privacy_review_r3.jsonl"
        for raw in path.read_text(encoding="utf-8").splitlines():
            case = json.loads(raw)
            with self.subTest(case=case["id"]):
                inputs = [case["comments"]] + ([case["facts"]] if case["facts"] else [])
                if not HAS_DOCX and any(name.endswith(".docx") for name, _ in inputs):
                    self.skipTest("python-docx unavailable")
                if "expected_error" in case:
                    cp = self.write_input(*case["comments"])
                    fp = self.write_input(*case["facts"])
                    for extra in ((), ("--json",)):
                        rc, output, err = self.run_main("comments", str(cp), "--facts", str(fp), *extra)
                        self.assertEqual((rc, output, err), (2, "", "错误：" + case["expected_error"] + "\n"))
                    continue
                rendered, report = self.check_output(
                    case["comments"], case["facts"], case["hide"], static=case["static"],
                    baseline=case["baseline_py005"], keep_prose=case["keep"],
                    prose_ids=case["expected_prose_ids"],
                )
                self.assert_frozen_hits(report, case)
                self.assertFalse(set(case.get("forbid_ids", ())) & set(self.ids(report)))
                self.assertFalse(set(case.get("forbid_py016", ())) &
                                 py016_numbers(report))
                if case["id"].startswith("W10_"):
                    self.assertEqual(report["file"], "w10.txt")
                if case["id"].startswith("W31_"):
                    self.assertEqual([e["label"] for e in report["entries"][:2]], ["S01", "S002"])
                if "ordinary_digest" in case:
                    self.assert_frozen_report(rendered, report, case["ordinary_digest"])

    def test_round4_scope_and_ordinary_prose_against_baseline(self):
        path = SAMPLES / "comment_privacy_review_r4.jsonl"
        cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(Counter(case["id"][0] for case in cases), {"P": 48, "X": 36, "O": 44, "I": 25})
        for case in cases:
            with self.subTest(case=case["id"]):
                inputs = [case["comments"]] + ([case["facts"]] if case["facts"] else [])
                if not HAS_DOCX and any(name.endswith(".docx") for name, _ in inputs):
                    self.skipTest("python-docx unavailable")
                rendered, report = self.check_output(
                    case["comments"], case["facts"], case["hide"], baseline=case["baseline_py005"],
                    keep_prose=case["keep"], stage=case.get("stage", "义务教育"),
                    person=case.get("person", "second"), bom_crlf=case.get("bom_crlf", False))
                if "ordinary_digest" in case:
                    self.assert_frozen_report(rendered, report, case["ordinary_digest"])
                else:
                    self.assert_frozen_hits(report, case)
                self.assertLessEqual(set(case.get("expect_py016", ())), py016_numbers(report))
                self.assertTrue(set(case.get("forbid_py016", ())).isdisjoint(py016_numbers(report)))
                self.assertLessEqual(set(case.get("expect_ids", ())), set(self.ids(report)))
                self.assertTrue(set(case.get("forbid_ids", ())).isdisjoint(self.ids(report)))
                if "expected_file" in case:
                    self.assertEqual(report["file"], case["expected_file"])
                if "baseline_similarity" in case:
                    self.assertEqual(report["similar_pairs"], case["baseline_similarity"])
                for rule, level in case.get("levels", {}).items():
                    self.assertEqual({i["level"] for i in report["issues"] if i["id"] == rule}, {level})
                for output in (rendered, json.dumps(report, ensure_ascii=False)):
                    self.assertFalse(any(0xE000 <= ord(ch) <= 0xF8FF for ch in output))

    def test_round5_interval_and_ordinary_reports_against_baseline(self):
        path = SAMPLES / "comment_privacy_review_r5.jsonl"
        cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(Counter(case["id"][0] for case in cases),
                         {"U": 44, "Z": 56, "E": 22, "W": 4, "M": 6, "T": 6, "A": 40})
        for case in cases:
            with self.subTest(case=case["id"]):
                inputs = [case["comments"]] + ([case["facts"]] if case["facts"] else [])
                if not HAS_DOCX and any(name.endswith(".docx") for name, _ in inputs):
                    self.skipTest("python-docx unavailable")
                rendered, report = self.check_output(
                    case["comments"], case["facts"], case["hide"], static=case.get("static", ()),
                    baseline=case["baseline_py005"], keep_prose=case["keep"],
                    prose_ids=case["prose_ids"], exact_prose=True)
                if case["ordinary"]:
                    self.assert_frozen_report(rendered, report, case["ordinary_digest"])
                else:
                    self.assert_frozen_hits(report, case)
                quantities = py016_numbers(report)
                self.assertLessEqual(set(case.get("expect_py016", ())), quantities)
                self.assertTrue(set(case.get("forbid_py016", ())).isdisjoint(quantities))
                ids = set(self.ids(report))
                self.assertLessEqual(set(case.get("expect_ids", ())), ids)
                self.assertTrue(set(case.get("forbid_ids", ())).isdisjoint(ids))
                for output in (rendered, json.dumps(report, ensure_ascii=False)):
                    self.assertFalse(any(0xE000 <= ord(ch) <= 0xF8FF for ch in output))
                excerpts = [i["excerpt"] for i in report["issues"] if i["id"] == "PY-001"]
                if case.get("excerpts"):
                    self.assertEqual(excerpts, case["excerpts"])
                if case.get("alias_pair"):
                    token = k12_check.COMMENT_NUMBER_TOKEN_RE.search(report["file"])[0]
                    self.assertTrue(any(token in excerpt for excerpt in excerpts))
                if "expected_labels" in case:
                    self.assertEqual([e["label"] for e in report["entries"]], case["expected_labels"])
                if "expected_file" in case:
                    self.assertEqual(report["file"], case["expected_file"])
                if "expected_text_parts" in case:
                    for value in case["expected_text_parts"]:
                        self.assertIn(value, rendered)
                if "baseline_ratios" in case:
                    self.assertEqual([pair["ratio"] for pair in report["similar_pairs"]], case["baseline_ratios"])

    def test_round6_paired_boundaries_decimal_and_compact_aliases(self):
        path = SAMPLES / "comment_privacy_review_r6.jsonl"
        cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(Counter(case["id"][0] for case in cases),
                         {"Q": 36, "U": 36, "S": 34, "V": 12, "B": 9, "A": 53})
        for case in cases:
            with self.subTest(case=case["id"]):
                inputs = [case["comments"]] + ([case["facts"]] if case["facts"] else [])
                if not HAS_DOCX and any(name.endswith(".docx") for name, _ in inputs):
                    self.skipTest("python-docx unavailable")
                rendered, report = self.check_output(
                    case["comments"], case["facts"], case["hide"], baseline=case["baseline_py005"],
                    keep_prose=case["keep"], prose_ids=case["prose_ids"], exact_prose=True,
                    stage=case.get("stage", "义务教育"), person=case.get("person", "second"))
                if "ordinary_digest" in case:
                    self.assertEqual(case["prose_ids"], [])
                    self.assert_frozen_report(rendered, report, case["ordinary_digest"])
                    if "baseline_name_mask" in case:
                        original, token = case["baseline_name_mask"]
                        assert_hidden(self, rendered, report, [original])
                        self.assertTrue(any(i["id"] == "PY-015" and i["label"] == token
                                            for i in report["issues"]))
                else:
                    self.assert_frozen_hits(report, case)
                quantities = py016_numbers(report)
                self.assertLessEqual(set(case.get("expect_py016", ())), quantities)
                self.assertTrue(set(case.get("forbid_py016", ())).isdisjoint(quantities))
                ids = set(self.ids(report))
                self.assertLessEqual(set(case.get("expect_ids", ())), ids)
                self.assertTrue(set(case.get("forbid_ids", ())).isdisjoint(ids))

    def test_explicit_labels_mask_dotted_values_and_fractions(self):
        comments = ("notes.txt", "S01：你很笨，考号：A117C3 2026/03/15参加比赛，"
                    "工号：45376 3/5，编号：67139 19.5元。")
        facts = ("facts.txt", "S01：2026/03/14参赛，跑2/5，花12.5元。")
        _, report = self.check_output(comments, facts, ("A117C3", "45376", "67139", "19.5"),
                                      baseline=[[1, "学号等编号"]],
                                      keep_prose=("2026/03/14参赛", "跑2/5", "12.5元"),
                                      prose_ids=("A117C3 2026", "03", "15", "45376 3", "5", "67139 19.5"),
                                      exact_prose=True)
        self.assertEqual(py016_numbers(report), set())

    def test_short_explicit_value_with_label_at_paragraph_start(self):
        comments = ("notes.txt", "考号：825，你很笨，读书7本。")
        facts = ("facts.txt", "考号：825，本周读书2本。")
        _, report = self.check_output(comments, facts, ("825",))
        self.assertEqual(py016_numbers(report), {"7"})

    def test_identity_number_split_at_calendar_components(self):
        value = "110105-2013-05-03-764X"
        self.check_output((f"notes_{value}.txt", f"S01：你很笨，档案中有{value}本人签收。"),
                          None, (value,))

    def test_baseline_number_split_by_marker_preserves_marker(self):
        comments = ("notes.txt", "S01：你很笨，学号884【待补：核对记录】509，读书7本。")
        _, report = self.check_output(comments, None, ("884", "509"), baseline=[[1, "学号等编号"]],
                                      keep_prose=("【待补：核对记录】",))
        self.assertEqual(report["summary"]["markers"]["待补"], 1)

    def test_confirmed_tag_alias_masks_matching_quantity(self):
        comments = ("notes_43256.txt", "S01：你很笨，学号：43256，记录43256字。")
        facts = ("facts.txt", "S01：记录12000字。")
        _, report = self.check_output(comments, facts, ("43256",), baseline=[[1, "学号等编号"]])
        self.assertNotIn("PY-016", self.ids(report))
        self.assertEqual(report["file"], "notes_〔编号1〕.txt")

    def test_short_confirmed_tag_masks_only_the_confirmed_position(self):
        comments = ("notes_7824.txt", "S01：你很笨，考生号：7824，记录7824字。")
        facts = ("facts.txt", "S01：记录1200字。")
        _, report = self.check_output(comments, facts, (), prose_ids=("7824",),
                                      keep_prose=("记录7824字",))
        self.assertEqual(py016_numbers(report), {"7824"})
        self.assertEqual(report["file"], "notes_7824.txt")
        insult = next(i for i in report["issues"] if i["id"] == "PY-001")
        self.assertIn("考生号：〔编号1〕", insult["excerpt"])

    def test_round3_independent_cell_members_and_explicit_number_list(self):
        comments = ("notes.md", [
            ["学生学号", "评语"],
            ["主：45510 45512 / 备：XYA-561", "你很笨，记录45510、45512和XYA-561，读书7本。"],
        ])
        facts = ("facts.md", [
            ["学生学号", "具体表现"],
            ["主：45510 45512 / 备：XYA-561", "考号：2026-01、2026-02，读书3本。"],
        ])
        _, report = self.check_output(comments, facts, ("45510", "45512", "XYA-561", "2026-01", "2026-02"),
                                      keep_prose=("读书7本", "读书3本"))
        self.assertEqual(py016_numbers(report), {"7"})

    def test_large_quantities_after_comma_still_reconcile(self):
        for unit in ("字", "下", "步", "余元", "多本", "题", "道", "圈", "遍", "场", "天", "周", "万", "千", "位", "页",
                     "件", "段", "回", "套", "公斤", "公里"):
            with self.subTest(unit=unit):
                raw = f"680125{unit}"
                _, report = self.check_output(
                    ("qty.txt", f"S01：你很笨，学号：78331，记录{raw}。"),
                    ("facts.txt", f"S01：691345{unit}。"), ("78331",),
                    baseline=[[1, "学号等编号"]], keep_prose=(raw,))
                self.assertEqual(py016_numbers(report), {"680125"})

    def test_round2_state_cells_do_not_register_prose_aliases(self):
        for state in ("无", "在读", "暂无", "正常", "待核", "-", "K", "ABC"):
            with self.subTest(state=state):
                prose = f"你很笨，还是无可救药。备注是{state}，规范范围50-60下。"
                _, report = self.check_output(
                    ("status.csv", [["编号", "评语"], [state, prose]]), None, (), keep_prose=(prose,))
                self.assertEqual(report["entries"][0]["label"], "〔编号1〕")
                self.assertIn("PY-001", self.ids(report))

    def test_only_certain_bare_prefixed_numbers_are_sanitized(self):
        for identifier in ("G110106201201155676", "L11010620120115567x", "g11010620120115567X",
                           "l110106201201155678", "G110106-20120115-567X", "L110106 20120115 567X",
                           "Q847512", "AZ847512", "az847512", "J847512A", "ZX847512XX"):
            with self.subTest(identifier=identifier):
                certain = identifier[0] in "GLgl"
                _, report = self.check_output(
                    (f"报告_{identifier}.txt", f"S01：你很笨，档案{identifier}已转入，20261126参加活动1次。"),
                    ("facts.txt", "S01：20261126参加活动1次。"), (identifier,) if certain else (),
                    keep_prose=("20261126参加活动1次",) + (() if certain else (identifier,)))
                self.assertIn("〔编号1〕" if certain else identifier, report["file"])
                self.assertEqual(py016_numbers(report), set() if certain else {"847512"})

    def test_round2_mixed_headers_and_adjacency(self):
        variants = (
            ("姓名与学生卡号", "WX_581_43", "WX_581_43王小明"),
            ("考号及姓名", "E-88059", "王小明E-88059"),
            ("姓名/工号", "AB__4582", "王小明/AB__4582"),
            ("姓名编号（内部）", "2026-02-01", "王小明2026-02-01"),
            ("学生（工号）", "ZZ 9418", "ZZ 9418王小明"),
            ("学生姓名（证件号码）", "2026/02/03", "王小明2026/02/03"),
            ("准考证号（学生姓名）", "Z811W2", "Z811W2王小明"),
            ("同学（学生卡号）", "59018", "王小明（8班）59018"),
            ("班级学生姓名（编号）", "AW_004", "AW_004（王小明）"),
        )
        for header, identifier, cell in variants:
            with self.subTest(header=header, identifier=identifier):
                # 日期形编号只在有编号上下文的混合格中净化。
                prefix = "" if header in {"姓名编号（内部）", "学生姓名（证件号码）"} else identifier
                notes = f"{prefix}王小明，你很笨，读书9本。"
                comments = [[header, "评语"], [cell, notes]]
                facts = [[header, "具体表现"], [cell, "读书4本"]]
                _, report = self.check_output(("mixed.csv", comments), ("facts.md", facts),
                                              (identifier, "王小明"))
                self.assertRegex(report["entries"][0]["label"], r"〔姓名\d+〕")
                self.assertNotIn("PY-015", self.ids(report))
                self.assertEqual(py016_numbers(report), {"9"})

    def test_round2_list_separators_and_local_codes(self):
        for separator in ("、", "和", "与", "/", "及"):
            with self.subTest(separator=separator):
                value = f"NB__024{separator}KA_003{separator}S004"
                comments = [["编号", "评语"], ["S004", f"你很笨，学生卡号是{value}，读书9本。"]]
                facts = [["编号", "具体表现"], ["S004", "读书4本"]]
                _, report = self.check_output(("list.md", comments), ("facts.csv", facts),
                                              ("NB__024", "KA_003"), keep_prose=("S004",))
                self.assertEqual(report["entries"][0]["label"], "S004")
                self.assertNotIn("PY-015", self.ids(report))

    def check_table_variants(self, *, word):
        for header, value, fmt in TABLE_VARIANTS:
            if (fmt == "docx") != word:
                continue
            with self.subTest(header=header, value=value, fmt=fmt):
                # 两侧仅有编号可对账。事实表额外的普通数字必须保留。
                comments = [[header, "评语"], [value, "你读书13本，表现很笨。"]]
                facts = [[header, "具体表现"], [value, "你读书7本。"]]
                local_code = value == "S096"
                in_filename = "/" not in value and (local_code or (len(value) >= 5 and any(c.isdigit() for c in value)))
                filename = f"评语_{value}.{fmt}" if in_filename else f"评语.{fmt}"
                _text, report = self.check_output((filename, comments), ("facts." + fmt, facts),
                                                  () if local_code else (value,))
                label = value if local_code else "〔编号1〕"
                self.assertEqual(report["entries"][0]["label"], label)
                if in_filename:
                    self.assertIn(label, report["file"])
                self.assertEqual(py016_numbers(report), {"13"})
                self.assertNotIn("PY-015", self.ids(report))

    def test_markdown_and_csv_variants(self):
        self.check_table_variants(word=False)

    @unittest.skipUnless(HAS_DOCX, "需要既有可选库 python-docx")
    def test_word_variants(self):
        self.check_table_variants(word=True)

    def test_inline_variants(self):
        outside_scope = {
            "教师工号 H-7873和H-5730": {"7873", "5730"},
            "你的号码录入档案6789112。": {"6789112"},
            "考生号A0和99B·备注": {"0", "99"},
        }
        after_comma = {"联系方式为 XN54-879, XN55-351": {"55", "351"},
                       "编号是：QA-0430，QQ-9271": {"9271"}}
        for note, originals in INLINE_VARIANTS:
            with self.subTest(note=note):
                known = note in outside_scope
                has_alias = len(originals[0]) >= 5 and "\t" not in originals[0]
                filename = f"评语_{originals[0]}.txt" if has_alias else "评语.txt"
                comment = f"S01：你读书17本，你很笨。{note}，应继续努力。"
                baseline = [[1, "手机号"]] if originals == ("15981936719",) else ()
                hidden = () if known else originals[:1] if note in after_comma else originals
                keep = (note,) if known else originals[1:] if note in after_comma else ()
                _, report = self.check_output((filename, comment), ("facts.txt", "S01：读书8本。"),
                                              hidden, baseline=baseline, keep_prose=keep)
                if known:
                    self.assertEqual(report["file"], filename)
                elif has_alias:
                    self.assertIn("〔编号1〕", report["file"])
                self.assertEqual(py016_numbers(report),
                                 {"17"} | outside_scope.get(note, set()) | after_comma.get(note, set()))

    def test_quantities_dates_and_numbered_rows_keep_their_meaning(self):
        comments = ("| 序号 | 学号 | 评语 |\n|---|---|---|\n"
                    "| 53 | 338517 | 你读书338517本，体育考了96分，2026-11-21参加17次劳动，"
                    "为5班捐款150000.65元。 |")
        facts = ("| 序号 | 学号 | 具体表现 |\n|---|---|---|\n"
                 "| 53 | 338517 | 读书3本，体育考了93分，2026-11-25参加7次劳动，为4班捐款150000.55元。 |")
        # 学号列确认了别名，即使后接量词也净化。其他数字继续对账。
        _, report = self.check_output(
            ("draft_338517.md", comments), ("facts.md", facts), ("338517",),
            keep_prose=("本，体育", "2026-11-21", "150000.65元", "5班"))
        self.assertNotIn("338517", report["file"])
        self.assertEqual(report["entries"][0]["label"], "53")
        self.assertEqual(py016_numbers(report),
                         {"96", "21", "17", "5", "150000.65"})

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
                                      ("39684", "FA19-36", "CD70-26", "FA19-36 CD70-26"))
        first, second = report["file"].removeprefix("评语_").removesuffix(".md").split("_")
        self.assertTrue(all(k12_check.COMMENT_NUMBER_TOKEN_RE.fullmatch(t) for t in (first, second)))
        self.assertNotEqual(first, second)

    def test_distinct_table_numbers_keep_internal_spaces_for_matching(self):
        comments = [["学号", "评语"], ["QB 7672", "你读书17本。"], ["QB7672", "你读书13本。"]]
        facts = [["学号", "具体表现"], ["QB7672", "读书13本"], ["QB 7672", "读书17本"]]
        _, report = self.check_output(("notes.md", comments), ("facts.csv", facts), ("QB 7672", "QB7672"))
        self.assertEqual([e["label"] for e in report["entries"]], ["〔编号1〕", "〔编号2〕"])
        self.assertTrue({"PY-015", "PY-016"}.isdisjoint(self.ids(report)))
