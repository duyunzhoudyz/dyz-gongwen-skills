"""第 1 步门禁：原判定、规范稿、规则目录和本机评语输出。"""
from collections import Counter
from hashlib import sha256
import json
import unittest

from tests.k12.test_k12_check import HAS_DOCX, K12TestCase, REPO_ROOT, SAMPLES, k12_check
from tests.k12.test_k12_comment_privacy import assert_hidden, assert_prose_preserved, assert_py005, capture_prose
from tests.k12.stage3a_checks import (
    RULES, assert_preserved, assert_probe_additions, document_additions, document_exemptions, hits,
    noise_mirrors, probe_exemptions,
)


REGRESSION = SAMPLES / "clause_regression"
ENTRIES = ("parents", "general", "comments")


def read_jsonl(path):
    return list(map(json.loads, path.read_text(encoding="utf-8").splitlines()))


def probe_hits(report):
    return [list(hit) for hit in sorted({(i["id"], i["level"], i["line"]) for i in report["issues"]},
                                        key=lambda hit: (hit[2], hit[0], hit[1]))]


def run_entry(engine, entry, path, stage, facts=None):
    try:
        checker = getattr(engine, f"check_{entry}")
        kwargs = {"facts_path": facts} if facts is not None else {}
        report = checker(path, stage=stage, **kwargs)
        return {"hits": probe_hits(report)}
    except engine.InputError as exc:
        return {"error": str(exc)}


def reference_documents():
    refs = REPO_ROOT / "skills/gongwen-k12/references"
    corpus = REPO_ROOT / "tests/industry_corpus/k12"
    clean = {row["file"] for row in json.loads((corpus / "cases.json").read_text(encoding="utf-8"))["docs"]
             if row["kind"] == "clean"}
    documents = {p: "reference" for p in refs.rglob("*.md")}
    for folder in (REPO_ROOT / "examples").glob("D-中小学*"):
        documents.update({p: "example" for p in folder.iterdir() if p.suffix in {".csv", ".md", ".txt"}})
    documents.update({p: "clean_corpus" if p.name in clean else "violation_corpus" for p in corpus.glob("*.txt")})
    documents.update({p: "clean_sample" if "must_pass" in p.name else "engine_sample"
                      for p in SAMPLES.iterdir() if p.suffix in {".md", ".txt"}})
    return {p.relative_to(REPO_ROOT).as_posix(): category for p, category in sorted(documents.items())}


class K12Stage1Tests(K12TestCase):
    def verify_number_privacy(self, args, originals, baseline=()):
        with capture_prose() as bodies:
            rc, rendered, err = self.run_main(*args)
        self.assertEqual((rc, err), (0, ""))
        report = self.run_json(*args)
        assert_hidden(self, rendered, report, originals)
        assert_py005(self, report, baseline)
        assert_prose_preserved(self, bodies, originals)

    def test_all_probes_preserve_baseline_except_the_frozen_private_number_findings(self):
        runs = errors = 0
        deltas = read_jsonl(SAMPLES / "comment_privacy_baseline_deltas.jsonl")
        private_differences = {(row["id"], row["stage"]): row for row in deltas}
        self.assertEqual(len(private_differences), len(deltas))
        applied = set()
        measured = set()
        levels = {rule["id"]: rule["stage_levels"] for rule in k12_check.rule_catalog()["rules"]}
        for filename in ("probes.jsonl", "supplemental_text.jsonl", "output_probes.jsonl"):
            for probe in read_jsonl(REGRESSION / filename):
                name = probe.get("filename", "probe.txt")
                path = self.tmp / name
                path.write_bytes(probe["text"].encode("utf-8"))
                facts = self.write("facts.md", probe["facts"]) if "facts" in probe else None
                for stage, stage_data in probe["by_stage"].items():
                    for entry, recorded in stage_data["baseline_measured"].items():
                        with self.subTest(probe=probe["id"], stage=stage, entry=entry):
                            runs += 1
                            actual = run_entry(k12_check, entry, path, stage, facts)
                            baseline = {key: recorded[key] for key in ("hits", "error") if key in recorded}
                            expected = baseline
                            if "hits" in baseline:
                                measured.update((probe["text"], stage, entry, *hit) for hit in baseline["hits"])
                            else:
                                errors += 1
                            key = (probe["id"], stage)
                            if entry == "comments" and key in private_differences:
                                changes = private_differences[key]
                                old_hits = {tuple(hit) for hit in baseline["hits"]}
                                removed = {tuple(hit) for hit in changes["removed"]}
                                added = {tuple(hit) for hit in changes["added"]}
                                self.assertTrue(removed or added)
                                self.assertTrue(removed <= old_hits)
                                self.assertFalse(added & old_hits)
                                expected = {"hits": (old_hits - removed) | added}
                                applied.add(key)
                            if "hits" in expected:
                                expected = {"hits": sorted(map(list, expected["hits"]),
                                                           key=lambda hit: (hit[2], hit[0], hit[1]))}
                            if entry == "comments":
                                self.assertEqual(actual, expected)
                            else:
                                final = stage_data["expected"][entry]
                                assert_preserved(self, expected, actual, probe_exemptions(expected, final))
                                assert_probe_additions(self, entry, expected, actual,
                                                       stage_data.get("expected_new_layer", {}).get(entry, {}))
                            for rid, level, _line in actual.get("hits", ()):
                                self.assertIn(level, levels[rid][entry][stage])
        self.assertEqual((runs, errors), (4215, 5))
        self.assertEqual(applied, set(private_differences))
        false_positives = read_jsonl(REGRESSION / "baseline_false_positives.jsonl")
        self.assertEqual(len(false_positives), 55)
        for row in false_positives:
            with self.subTest(probe=row["id"], rule=row["rule"], stage=row["stage"]):
                self.assertIn((row["text"], row["stage"], row["entry"], row["rule"],
                               row["baseline_measured"], row["line"]), measured)

    def test_cli_output_probes_hide_private_values_and_keep_number_comparisons(self):
        all_categories = ("身份证号", "手机号", "学号等编号")
        baseline_lines = {
            "R4-CLI_id18_mobile11_stu10": {line: all_categories for line in (2, 3, 4)},
            # 原基线漏掉纯数字首标签行，已登记该行新增的 PY-005。
            "R4-CLI_shared_sentence_and_missing_label": {line: all_categories for line in (1, 2, 3)},
            "R4-CLI_short_stu5_and_alnum": {1: ("学号等编号",)},
            "R5-CLI_R5_CMT_01_exact_header_short_alnum": {line: ("学号等编号",) for line in (2, 3, 4)},
            "R5-CLI_R5_CMT_03_text_shared_py008_py016_py017": {line: ("学号等编号",) for line in (1, 2, 3)},
            "R5-CLI_R5_CMT_06_code_s01_preserved_with_pii": {1: all_categories},
        }
        for probe in read_jsonl(REGRESSION / "output_probes.jsonl"):
            if not probe.get("private"):
                continue
            path = self.write(probe["filename"], probe["text"])
            facts = self.write("facts.md", probe["facts"])
            for stage, stage_data in probe["by_stage"].items():
                with self.subTest(probe=probe["id"], stage=stage):
                    expected = stage_data["expected_output"]
                    args = ("comments", str(path), "--facts", str(facts), "--stage", stage)
                    report = self.run_json(*args)
                    rc, rendered, err = self.run_main(*args)
                    self.assertEqual((rc, err), (0, ""))
                    assert_hidden(self, rendered, report, expected["forbidden_literals"])
                    for output in (rendered, json.dumps(report, ensure_ascii=False)):
                        for label in expected["preserve_cli_labels"]:
                            self.assertIn(label, output)
                    issues = [i for i in report["issues"] if i["id"] == "PY-016"]
                    self.assertEqual({i["line"] for i in issues}, set(expected["py016_allowed_quantity_lines"]))
                    self.assertTrue(all(i["excerpt"] not in expected["py016_forbidden_literals"] for i in issues))
                    baseline = [[line, category] for line, categories in baseline_lines.get(probe["id"], {}).items()
                                for category in categories]
                    self.verify_number_privacy(args, expected["forbidden_literals"], baseline)

    def test_comments_join_table_name_masks_and_all_private_id_columns(self):
        for comment_format, facts_format in (("md", "csv"), ("csv", "md")):
            with self.subTest(comments=comment_format, facts=facts_format):
                rows = [
                    ["学生姓名", "学生 学号", "准考证号码", "第二学号", "学生姓名及考号", "评语"],
                    ["王小明", "Z98K76", "45123", "A55B01", "王小明 8324",
                     "你在实验课表现突出，王小明的编号是45123、8324、A55B01，读书3本、画画60789、记录9999。"],
                    ["李明", "B77C88", "45124", "A55B02", "李明 8325",
                     "你在实验课表现突出，李明的编号是45124、8325、A55B02，读书3本、画画60789、记录9999。"],
                ]
                facts = [
                    ["学生姓名", "学生学号", "准考证号码", "具体表现"],
                    ["王小明", "Z98K76", "45123", "完成实验，读书3本"],
                    ["李明", "B77C88", "45124", "完成实验，读书3本"],
                    ["赵小红", "XM405", "60789", "认真听讲"],
                ]
                def render(data, fmt):
                    if fmt == "md":
                        return "\n".join(k12_check.render_md_table(data))
                    return "\n".join(",".join(row) for row in data)

                comments_path = self.write(f"王小明_Z98K76_45123_XM405_60789.{comment_format}",
                                           render(rows, comment_format))
                facts_path = self.write(f"facts.{facts_format}", render(facts, facts_format))
                args = ("comments", str(comments_path), "--facts", str(facts_path))
                report = self.run_json(*args)
                self.assertEqual([e["label"] for e in report["entries"]], ["〔姓名1〕", "〔姓名2〕"])
                self.assertEqual({(p["a"], p["b"]) for p in report["similar_pairs"]}, {("〔姓名1〕", "〔姓名2〕")})
                self.assertEqual({i["excerpt"] for i in report["issues"] if i["id"] == "PY-016"}, {"9999"})
                self.assertTrue(any(i["id"] == "PY-015" and i["label"] == "〔姓名3〕" for i in report["issues"]))
                assert_hidden(self, self.run_main(*args)[1], report,
                              ("王小明", "李明", "赵小红", "Z98K76", "45123", "A55B01", "8324",
                               "B77C88", "45124", "A55B02", "8325", "XM405", "60789"))
                self.verify_number_privacy(args, ("Z98K76", "45123", "A55B01", "8324", "B77C88",
                                                  "45124", "A55B02", "8325", "XM405", "60789"))

    def test_same_label_cell_preserves_name_and_number_placeholders(self):
        path = self.write("王小明_Z98K76.md",
                          "| 学生姓名 | 学生学号 | 评语 |\n|---|---|---|\n"
                          "| 王小明 Z98K76 | Z98K76 | 王小明 Z98K76 你很笨。 |")
        report = self.run_json("comments", str(path))
        self.assertEqual(report["entries"][0]["label"], "〔姓名1〕 〔编号1〕")
        self.assertEqual(report["file"], "〔姓名1〕_〔编号1〕.md")
        self.assertIn("〔姓名1〕 〔编号1〕", self.run_main("comments", str(path))[1])
        self.verify_number_privacy(("comments", str(path)), ("Z98K76",))

    def test_comments_keep_non_table_real_label_and_hide_file_error_details(self):
        path = self.write("notes.txt", "王小明：你很笨。")
        facts = self.write("facts.csv", "学生姓名,准考证号码,具体表现\n王小明,45123,参与劳动")
        report = self.run_json("comments", str(path), "--facts", str(facts))
        self.assertEqual(report["entries"][0]["label"], "王小明")
        self.verify_number_privacy(("comments", str(path), "--facts", str(facts)), ("45123",))
        for args in (("comments", str(self.tmp / "45123_Z98K76.md")),
                     ("comments", str(path), "--facts", str(self.tmp / "45123_Z98K76.csv"))):
            rc, out, err = self.run_main(*args)
            self.assertEqual((rc, out), (2, ""))
            self.assertNotIn("45123", err)
            self.assertNotIn("Z98K76", err)

    def test_comment_privacy_covers_adjacent_tokens_and_short_non_table_private_labels(self):
        path = self.write("draftZ98K76suffix.txt",
                          "S01：你学号Z98K76、考号45123，手机138-1234-5678，你认真完成劳动。\n"
                          "S02：你学号Z98K76、考号45123，手机138-1234-5678，你认真完成劳动。\n"
                          "S03：你学号Z98K76、考号45123，手机138-1234-5678，你认真完成劳动。\n"
                          "8324：你很笨。")
        facts = self.write("facts.md", "S01：完成劳动\nS02：完成劳动\nS03：完成劳动")
        report = self.run_json("comments", str(path), "--facts", str(facts))
        self.assertTrue(any(i["id"] == "PY-008" for i in report["issues"]))
        self.assertNotIn("PY-016", self.ids(report))
        assert_hidden(self, self.run_main("comments", str(path), "--facts", str(facts))[1], report,
                      ("Z98K76", "45123", "138-1234-5678", "8324"))
        self.verify_number_privacy(("comments", str(path), "--facts", str(facts)),
                                   ("Z98K76", "45123", "138-1234-5678", "8324"),
                                   [[line, "学号等编号"] for line in (1, 2, 3)])

    def test_markdown_table_without_leading_pipe_still_registers_ids_for_privacy(self):
        path = self.write("课后记录_Z98K76.md",
                          "学生学号 | 准考证号码 | 评语\n"
                          "--- | --- | ---\n"
                          "Z98K76 | 45123 | 你很笨。")
        args = ("comments", str(path))
        assert_hidden(self, self.run_main(*args)[1], self.run_json(*args), ("Z98K76", "45123"))
        self.verify_number_privacy(args, ("Z98K76", "45123"))

    def test_current_reference_documents_match_frozen_hits(self):
        data = read_jsonl(SAMPLES / "reference_baseline.jsonl")
        metadata, *docs = data
        self.assertEqual({record["file"]: record["category"] for record in docs}, reference_documents())
        by_file = {record["file"]: record for record in docs}
        mirrors = noise_mirrors(self, REPO_ROOT, SAMPLES, docs, k12_check.STAGES)
        levels = Counter()
        for record in docs:
            path = REPO_ROOT / record["file"]
            self.assertEqual(sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest(), record["sha256"])
            for entry in ENTRIES:
                for stage in k12_check.STAGES:
                    with self.subTest(file=record["file"], entry=entry, stage=stage):
                        actual = run_entry(k12_check, entry, path, stage)
                        frozen = record["runs"][entry][stage]
                        if entry == "comments":
                            self.assertEqual(actual, frozen)
                        else:
                            assert_preserved(self, frozen, actual, document_exemptions(record, entry, frozen))
                            added = hits(actual) - hits(frozen)
                            self.assertLessEqual({hit[0] for hit in added}, RULES[entry])
                            self.assertLessEqual(added, document_additions(record["file"], entry, stage, by_file, mirrors))
                        levels.update(hit[1] for hit in frozen.get("hits", ()))
        self.assertEqual(len(docs) * len(ENTRIES) * len(k12_check.STAGES), metadata["runs"])
        self.assertEqual(dict(levels), metadata["levels"])

    def test_rule_catalog_lists_current_rules_and_rejects_invalid_options(self):
        rc, out, err = self.run_main("--list-rules", "--json")
        self.assertEqual((rc, err), (0, ""))
        rules = {rule["id"]: rule for rule in json.loads(out)["rules"]}
        self.assertEqual(len(rules), 37)
        self.assertEqual(set(rules) - (
            {rule.id for rule in k12_check.PARENT_RULES}
            | {rule[0] for rule in k12_check.GENERAL_RULES}
            | {f"PY-{index:03d}" for index in range(1, 18)}
        ), {"K12-G05", "K12-G09"})
        self.assertEqual(set(rules),
                         {rule.id for rule in k12_check.PARENT_RULES}
                         | {rule[0] for rule in k12_check.GENERAL_RULES}
                         | {"K12-G05", "K12-G09"}
                         | {f"PY-{index:03d}" for index in range(1, 18)})
        for rid, rule in rules.items():
            self.assertTrue(rule["condition"], rid)
            self.assertEqual(set(rule["commands"]), set(rule["stage_levels"]))
            self.assertEqual(set(rule["levels"]),
                             {level for stages in rule["stage_levels"].values() for levels in stages.values()
                              for level in levels})
            for stages in rule["stage_levels"].values():
                self.assertEqual(tuple(stages), k12_check.STAGES)
        self.assertEqual(rules["JZ-009"]["stage_levels"]["parents"]["高中"], ["skip"])
        self.assertEqual(rules["JZ-011"]["condition"].count("；"), 1)
        self.assertEqual(rules["PY-003"]["stage_levels"]["comments"]["中职"], ["P1", "P2"])
        self.assertEqual(rules["K12-G04"]["stage_levels"]["parents"]["义务教育"], ["P0", "P1"])
        rc, text, err = self.run_main("--list-rules")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual({line.split(" | ")[0] for line in text.splitlines()[1:]}, set(rules))
        for args in ((), ("--json",), ("--list-rules", "--bad"), ("--list-rules", "parents", "probe.txt"),
                     ("comments",), ("parents", "probe.txt", "--stage", "小学")):
            self.assertEqual(self.run_main(*args)[0], 2)

    def test_baseline_union_requires_named_exact_line_and_keeps_stronger_issue(self):
        def issue(rule, level, line):
            return k12_check.Issue(rule, level, "", "", "", "", line=line)

        first = issue("JZ-003", "P0", 1)
        second = issue("JZ-003", "P0", 2)
        weak = issue("JZ-008", "P2", 2)
        upgraded = issue("JZ-008", "P1", 2)
        extra = issue("JZ-008", "P1", 3)
        independent = issue("JZ-003", "P0", 1)
        self.assertEqual(k12_check.merge_rule_issues([first, second, weak]), [first, second, weak])
        self.assertEqual(k12_check.merge_rule_issues(
            [first, independent, second, weak], [issue("JZ-003", "P1", 2), upgraded, extra], [first]),
            [independent, second, upgraded, extra])
        with self.assertRaises(ValueError):
            k12_check.merge_rule_issues([first], exemptions=[independent])
        unregistered = issue("JZ-006", "P0", 1)
        with self.assertRaises(ValueError):
            k12_check.merge_rule_issues([unregistered], exemptions=[unregistered])

    def test_baseline_union_keeps_table_name_fallback_when_same_line_is_upgraded(self):
        rule = "K12-G04"
        hint = k12_check.shared_names()[0].TABLE_UNKNOWN_HINT
        old = k12_check.Issue(rule, "P1", "", "表格姓名列出现真实姓名", "", "", line=2)
        fallback = k12_check.Issue(rule, "P1", "", hint, "", "", line=2)
        new = k12_check.Issue(rule, "P0", "", "新锚点", "", "", line=2)
        self.assertEqual(k12_check.merge_rule_issues([old, fallback], [new]), [fallback, new])

    @unittest.skipUnless(HAS_DOCX, "需要既有可选库 python-docx")
    def test_docx_keeps_table_positions_relative_to_paragraphs_and_boundary(self):
        import docx

        document = docx.Document()
        document.add_table(rows=1, cols=1).cell(0, 0).text = "首表"
        document.add_paragraph("正文")
        document.add_table(rows=1, cols=1).cell(0, 0).text = "正文表"
        document.add_paragraph("【起草说明】")
        document.add_table(rows=1, cols=1).cell(0, 0).text = "说明表"
        path = self.tmp / "顺序.docx"
        document.save(path)
        read = k12_check.load_document(path)
        self.assertEqual(read.table_after_paragraph, [0, 1, 2])
        self.assertEqual(k12_check.cut_at_boundary(read.lines), (["正文"], 2))
        self.assertEqual([table[0][0] for table in read.tables], ["首表", "正文表", "说明表"])
