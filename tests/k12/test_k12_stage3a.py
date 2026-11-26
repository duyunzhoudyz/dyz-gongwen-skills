from collections import Counter
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tests.k12.stage3a_checks import (
    PAIRS, RANK, RANK_RULES, RULES, assert_noise, assert_preserved, assert_probe_additions,
    document_exemptions, hits, noise_mirrors, probe_exemptions,
)
from tests.k12.test_k12_stage1 import (
    REGRESSION, REPO_ROOT, SAMPLES, frozen_document_path, k12_check, read_jsonl, run_entry, stage4_corpus,
)


def regression_probes():
    for filename in ("probes.jsonl", "supplemental_text.jsonl", "output_probes.jsonl"):
        yield from read_jsonl(REGRESSION / filename)


def probe_runs():
    with TemporaryDirectory() as folder:
        directory = Path(folder)
        for probe in regression_probes():
            path = directory / probe.get("filename", "probe.txt")
            path.write_bytes(probe["text"].encode("utf8"))
            for stage in k12_check.STAGES:
                reports = {entry: run_entry(k12_check, entry, path, stage) for entry in RULES}
                yield probe, stage, reports


def document_deltas(records):
    for record in records:
        filename = record["file"]
        path = frozen_document_path(filename)
        lines = path.read_text(encoding="utf8").splitlines()
        for entry in RULES:
            for stage in k12_check.STAGES:
                before = record["runs"][entry][stage]
                actual = run_entry(k12_check, entry, path, stage)
                for rule, level, line in sorted(hits(actual) - hits(before)):
                    yield record["category"], filename, entry, stage, rule, level, line, lines[line - 1]


def fresh_cases():
    cases = json.loads((SAMPLES / "stage3a_adversarial.json").read_text(encoding="utf8"))
    for category, texts in cases.items():
        if category.startswith("review_round_"):
            continue
        for index, original in enumerate(texts, 1):
            yield category, index, original


def run_candidate(path, original, stage):
    path.write_text(original, encoding="utf8")
    doc = k12_check.load_document(path)
    lines, _ = k12_check.cut_at_boundary(doc.lines)
    evidence = k12_check._ClauseEvidence(doc, lines)
    result = {}
    for entry, rules in RULES.items():
        actual = run_entry(k12_check, entry, path, stage)
        final = sorted(h for h in hits(actual) if h[0] in rules)
        new = sorted({(i.id, i.level, i.line) for i in evidence.added(entry, stage)})
        result[entry] = {"final": final, "new": new}
    return result


def baseline_losses(before, after):
    current = {}
    for r, lv, n in hits(after):
        current[r, n] = min(current.get((r, n), len(RANK)), RANK[lv])
    return sorted((r, lv, n) for r, lv, n in hits(before) if current.get((r, n), len(RANK)) > RANK[lv])


def baseline_exemption_witness(evidence, rule, line):
    """定位被冻结的教师受训动作。"""
    if rule != "JZ-008" or not 1 <= line < len(evidence.offsets):
        return None
    text = evidence.graph.text[evidence.offsets[line - 1]:evidence.offsets[line] - 1]
    spec = next(rule_spec for rule_spec in k12_check.PARENT_RULES if rule_spec.id == rule)
    match = next(k12_check._parent_matches(spec, text), None)
    return evidence.exemption_witness(rule, line, match) if match else None


def clause_evidence(path):
    doc = k12_check.load_document(path)
    lines = ([" ".join(row) for table in doc.tables for row in table]
             if doc.kind == "table" else k12_check.cut_at_boundary(doc.lines)[0])
    return k12_check._ClauseEvidence(doc, lines)


class Stage3aTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = list(probe_runs())

    def test_regression_final_levels_and_positions(self):
        self.assertEqual(len(self.runs), 761 * 3)
        for probe, stage, reports in self.runs:
            data = probe["by_stage"].get(stage, {})
            for entry, expected in data.get("expected", {}).items():
                if entry not in reports:
                    continue
                with self.subTest(probe=probe["id"], entry=entry, stage=stage):
                    before = data["baseline_measured"][entry]
                    actual = reports[entry]
                    self.assertEqual(actual.get("error"), before.get("error"))
                    if "error" in before:
                        continue
                    additions = data.get("expected_new_layer", {}).get(entry, {})
                    for rule in RULES[entry]:
                        old = {(level, line) for r, level, line in hits(before) if r == rule}
                        seen = {(level, line) for r, level, line in hits(actual) if r == rule}
                        allowed = expected.get(rule, sorted({level for level, _ in old}) or ["SKIP"])
                        self.assertLessEqual({level for level, _ in seen} or {"SKIP"}, set(allowed),
                                             (rule, allowed, seen))
                        if rule in additions and (seen or "SKIP" not in allowed):
                            self.assertLessEqual(set(additions[rule]["lines"]), {line for _, line in seen},
                                                 (rule, additions[rule], seen))
                    assert_probe_additions(self, entry, before, actual, additions)

    def test_baseline_keeps_every_hit_except_named_exemptions(self):
        for probe, stage, reports in self.runs:
            data = probe["by_stage"].get(stage, {})
            for entry, before in data.get("baseline_measured", {}).items():
                if entry not in reports:
                    continue
                with self.subTest(probe=probe["id"], entry=entry, stage=stage):
                    exempt = probe_exemptions(before, data["expected"][entry])
                    assert_preserved(self, before, reports[entry], exempt)
                    for rule, _, line in exempt:
                        self.assertFalse(any(r == rule and n == line for r, _, n in hits(reports[entry])))

    def test_unmarked_new_p0_is_zero(self):
        for probe, stage, reports in self.runs:
            data = probe["by_stage"].get(stage, {})
            for entry, before in data.get("baseline_measured", {}).items():
                if entry not in reports:
                    continue
                with self.subTest(probe=probe["id"], entry=entry, stage=stage):
                    allowed = {rule: set(item["lines"])
                               for rule, item in data.get("expected_new_layer", {}).get(entry, {}).items()
                               if "P0" in item["allowed"]}
                    for rule, level, line in hits(reports[entry]) - hits(before):
                        if level == "P0":
                            self.assertIn(line, allowed.get(rule, ()), (rule, level, line))

    def test_ranking_baseline_objects_cannot_be_exempted(self):
        for rule in sorted(RANK_RULES):
            with self.subTest(rule=rule):
                baseline = k12_check.Issue(rule, "P0", "", "", "", "", line=1)
                with self.assertRaisesRegex(ValueError, "^基线豁免须指向已登记规则的一条原始命中$"):
                    k12_check.merge_rule_issues([baseline], exemptions=[baseline])

    def test_clear_violations_match_both_entries_and_pair_presence_agrees(self):
        clear = Counter()
        for probe, stage, reports in self.runs:
            expected = probe["by_stage"].get(stage, {}).get("expected", {})
            if not all(entry in expected and "error" not in reports[entry] for entry in RULES):
                continue
            for parent, general in PAIRS.items():
                required = any(rule in expected[entry] and "SKIP" not in expected[entry][rule]
                               for entry, rule in (("parents", parent), ("general", general)))
                with self.subTest(probe=probe["id"], stage=stage, family=general):
                    has_parent = any(r == parent for r, _, _ in hits(reports["parents"]))
                    has_general = any(r == general for r, _, _ in hits(reports["general"]))
                    self.assertEqual(has_parent, has_general)
                    if required:
                        clear[general] += 1
                        self.assertTrue(has_parent and has_general)
        self.assertEqual(set(clear), set(PAIRS.values()))

    def test_reference_and_clean_document_noise_gate(self):
        records = read_jsonl(SAMPLES / "reference_baseline.jsonl")[1:]
        mirrors = noise_mirrors(self, REPO_ROOT, SAMPLES, records, k12_check.STAGES)
        self.assertEqual(len(mirrors), 0)
        assert_noise(self, list(document_deltas(records)), mirrors)
        for record in records:
            for entry in RULES:
                for stage in k12_check.STAGES:
                    before = record["runs"][entry][stage]
                    exempt = document_exemptions(record, entry, before)
                    if exempt:
                        actual = run_entry(k12_check, entry, frozen_document_path(record["file"]), stage)
                        self.assertFalse(exempt & hits(actual))

    def test_catalog_describes_precision_wide_and_entry_difference(self):
        rules = {r["id"]: r for r in k12_check.rule_catalog()["rules"]}
        for parent, general in PAIRS.items():
            with self.subTest(general=general):
                matrix = rules[general]["writing_matrix"]
                self.assertGreaterEqual(len(matrix), 4)
                self.assertEqual(tuple(matrix[0]["stage_levels"]), k12_check.STAGES)
                self.assertEqual(matrix[0]["stage_levels"], dict(zip(
                    k12_check.STAGES, ("P0", "P1", "P1") if general == "K12-G05" else ("P0",) * 3)))
                self.assertEqual(rules[parent]["writing_matrix"], matrix)
                self.assertIn("parents", rules[general]["condition"])
                self.assertIn("general", rules[general]["condition"])

    def test_stage3b_pending_ids_match_the_two_deferred_rules(self):
        pending = json.loads((SAMPLES / "stage3b_pending.json").read_text(encoding="utf8"))
        self.assertEqual(pending, {})

    def test_stage2_review_warnings_at_rule_entry_points(self):
        suppressed = (
            "不写统一订购教辅。",
            "不组织、推荐学生参加校外有偿补课。",
            "不组织/推荐学生参加校外有偿补课。",
            "义务教育阶段严禁以任何名义收取费用。",
            "统一归档、收费依据、校外培训负担",
            "《关于进一步减轻义务教育阶段学生作业负担和校外培训负担的意见》",
            "收费须有依据。",
            "会议要求该子公司于2026年12月15日前提交费用压减方案，经理层审核后执行。",
            "学校退费260元，困难学生减免校服费。",
            "学校严禁规定未缴纳校服费的学生不得报名。",
            "学校统一购买校服，费用为0元。",
            "学校统一购买校服，全部免费。",
            "家长群不晒成绩。",
            "考试结果仅一对一告知。",
            "面向家长的材料没有公布分数。",
            "申请材料显示，校方没有向家长委员会收取展演费用。",
            "在专题会议上，学校重申反对安排全班参加校外有偿补课。",
            "学校禁止规定不缴校服费不得入学。",
        )
        with TemporaryDirectory() as folder:
            path = Path(folder) / "draft.txt"
            for original in suppressed:
                for stage in k12_check.STAGES:
                    with self.subTest(original=original, stage=stage):
                        result = run_candidate(path, original, stage)
                        for report in result.values():
                            self.assertEqual(report["new"], [])
                        if original == "家长群不晒成绩。":
                            self.assertEqual(result["parents"]["final"],
                                             [("JZ-003", "P0" if stage == "义务教育" else "P1", 1)])
                            self.assertEqual(result["general"]["final"], [])
                            continue
                        if original not in {
                            "不写统一订购教辅。", "学校统一购买校服，费用为0元。", "学校统一购买校服，全部免费。",
                        }:
                            for report in result.values():
                                self.assertEqual(report["final"], [])
            for original, family, level in (
                ("学校要求学生自愿统一购买校服。", "JZ-006", "P1"),
                ("学校允许学生统一购买校服。", "JZ-006", "P1"),
                ("不同年级的学生一律须在周五前交齐校服费。", "JZ-006", "P0"),
                ("各班统一购买校服。", "JZ-006", "P0"),
                ("班级统一购买校服。", "JZ-006", "P1"),
                ("全体学生须交齐校服费。", "JZ-006", "P1"),
                ("学校统一在开学第一周向家长收取资料费40元。", "JZ-006", "P1"),
                ("教师联系翻译后组织学生参加校外有偿补课。", "JZ-008", "P1"),
                ("校外收费补习活动由班主任在年级微信群里统一动员学生报名。", "JZ-008", "P0"),
            ):
                with self.subTest(original=original):
                    result = run_candidate(path, original, "义务教育")
                    for entry, rule in (("parents", family), ("general", PAIRS[family])):
                        self.assertEqual(result[entry]["new"], [(rule, level, 1)])
            for original in ("不公布成绩怎么行呢？", "班主任不公示名次怎么行？"):
                with self.subTest(original=original):
                    result = run_candidate(path, original, "义务教育")
                    self.assertIn(("JZ-003", "P1", 1), result["parents"]["new"])
                    self.assertTrue(all(lv == "P1" for r in result.values() for _, lv, _ in r["new"]))

    def test_exemptions_are_local_and_preserve_independent_targets(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "draft.txt"
            result = run_candidate(path, "学校不公布考试成绩；学校公布考试成绩。", "义务教育")
            self.assertIn(("JZ-003", "P0", 1), result["parents"]["final"])
            self.assertIn(("K12-G01", "P0", 1), result["general"]["final"])
            result = run_candidate(path, "学校不公布考试成绩且本班语文均分92分。", "义务教育")
            self.assertEqual(result["parents"]["final"], [("JZ-014", "P1", 1)])
            self.assertEqual(result["general"]["final"], [])
            result = run_candidate(path, "学校组织校外培训机构为教师开展免费急救培训。", "义务教育")
            self.assertFalse(any(r["final"] for r in result.values()))
            result = run_candidate(path, "学校组织教师参加校外有偿培训。", "义务教育")
            self.assertFalse(any(r["final"] for r in result.values()))
            result = run_candidate(path, "学校组织校外培训机构为教师开展免费急救培训；"
                                         "学校组织学生参加校外有偿补课。", "义务教育")
            self.assertIn(("JZ-008", "P0", 1), result["parents"]["final"])
            self.assertIn(("K12-G09", "P1", 1), result["general"]["final"])

    def test_sixty_new_adversarial_cases(self):
        cases = list(fresh_cases())
        self.assertEqual(Counter(c.split("_")[0] for c, _, _ in cases),
                         {"compliant": 20, "wrapped": 20, "precise": 20})
        text = {original for _, _, original in cases}
        self.assertEqual(len(text), len(cases))
        self.assertFalse(text & {r["text"] for r in regression_probes()})
        with TemporaryDirectory() as folder:
            path = Path(folder) / "draft.txt"
            for category, index, original in cases:
                for stage in k12_check.STAGES:
                    with self.subTest(category=category, index=index, stage=stage, original=original):
                        result = run_candidate(path, original, stage)
                        if category == "compliant":
                            self.assertTrue(all(lv != "P0" for row in result.values() for _, lv, _ in row["new"]))
                            continue
                        parent = "JZ-006" if category.endswith("fee") else "JZ-008"
                        for entry, rule in (("parents", parent), ("general", PAIRS[parent])):
                            if category.startswith("precise"):
                                level = "P1" if parent == "JZ-006" and stage != "义务教育" else "P0"
                                self.assertIn((rule, level, 1), result[entry]["new"])
                            else:
                                self.assertTrue(any(r == rule and lv in {"P0", "P1"} and n == 1
                                                    for r, lv, n in result[entry]["final"]), result)


class Stage3aReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = SAMPLES / "stage3a_adversarial.json"
        cls.cases = json.loads(fixture.read_text(encoding="utf8"))["review_round_1"]

    def test_review_text_and_reworded_cases(self):
        pair = {"fee": ("JZ-006", "K12-G05"), "tutor": ("JZ-008", "K12-G09"), "rank": ("JZ-003", "K12-G01")}
        self.assertEqual(len(self.cases["text"]), 444)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "review.txt"
            for case in self.cases["text"]:
                text, goal = case["text"], case["goal"]
                path.write_text(text, encoding="utf8")
                doc = k12_check.load_document(path)
                evidence = k12_check._ClauseEvidence(doc, doc.lines)
                if goal == "question":
                    with self.subTest(case=case["id"]):
                        self.assertTrue(any(c.question for c in evidence.graph.clauses))
                        self.assertFalse(any(a.admission for a in evidence.graph.actions))
                for stage, entries in case["base"].items():
                    for index, entry in enumerate(RULES):
                        with self.subTest(case=case["id"], stage=stage, entry=entry):
                            old = {tuple(hit) for hit in entries[entry]}
                            issues = getattr(k12_check, f"check_{entry}")(path, stage)["issues"]
                            actual = {(item["id"], item["level"], item["line"]) for item in issues}
                            rule = pair[case["family"]][index] if case["family"] else None
                            family = {item for item in actual if item[0] == rule}
                            added = actual - old
                            if goal not in {"hit", "no_exempt", "keep_second", "keep_student",
                                            "jz014_keep"}:
                                self.assertFalse(any(level == "P0" for _, level, _ in added), added)
                            if goal in {"hit", "wide"}:
                                self.assertTrue(family, actual)
                            elif goal == "none":
                                self.assertFalse(family & added)
                            elif goal == "p1":
                                self.assertEqual({level for _, level, _ in family}, {"P1"})
                                if case["id"].startswith("B6-new"):
                                    self.assertFalse(any(item[0] == rule for item in old))
                            elif goal == "baseline_or_p1":
                                self.assertEqual(family, {item for item in old if item[0] == rule}
                                                 or {(rule, "P1", 1)})
                            elif goal == "baseline_rank":
                                self.assertEqual({item for item in old if item[0] == rule}, family)
                            elif goal == "free":
                                self.assertFalse(any(item.id == rule for item in evidence.added(entry, stage)))
                            if goal == "keep_student":
                                tutor = "JZ-008" if entry == "parents" else "K12-G09"
                                self.assertTrue(any(item[0] == tutor for item in actual))
                            if goal in {"wide", "no_exempt", "jz014_keep", "keep_student"}:
                                self.assertLessEqual(old, actual)
                            for rid, level, line in old - actual:
                                self.assertIsNotNone(baseline_exemption_witness(evidence, rid, line),
                                                     (rid, level, line))

    def test_word_body_table_precedes_drafting_note(self):
        try:
            from docx import Document
        except ImportError:
            self.skipTest("python-docx 未安装")
        self.assertEqual(len(self.cases["docx"]), 16)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "review.docx"
            for case in self.cases["docx"]:
                doc = Document()
                doc.add_paragraph(case["paragraph"])
                first = doc.add_table(rows=2, cols=2)
                for row, values in zip(first.rows, (("项目", "说明"), (case["item"], case["body"]))):
                    for cell, value in zip(row.cells, values):
                        cell.text = value
                doc.add_paragraph("【起草说明】")
                second = doc.add_table(rows=2, cols=2)
                for row, values in zip(second.rows, (("合规反例", "示例"), ("收费", case["note"]))):
                    for cell, value in zip(row.cells, values):
                        cell.text = value
                for paragraph in case["after"]:
                    doc.add_paragraph(paragraph)
                doc.save(path)
                for stage in k12_check.STAGES:
                    for entry, rule in (("parents", "JZ-006"), ("general", "K12-G05")):
                        with self.subTest(case=case["id"], stage=stage, entry=entry):
                            report = getattr(k12_check, f"check_{entry}")(path, stage)
                            relevant = [item for item in report["issues"] if item["id"] == rule]
                            self.assertEqual([(item["level"], item["line"], item["excerpt"]) for item in relevant],
                                             [("P1", 3, case["body"])])


class Stage3aPositiveAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((SAMPLES / "stage3a_adversarial.json").read_text(encoding="utf8"))
        cls.round2 = cls.fixture["review_round_2"]
        cls.round3 = cls.fixture["review_round_3"]
        cls.round4 = cls.fixture["review_round_4"]

    def assert_preserved_with_witness(self, path, stage, base):
        evidence = None
        after = {entry: run_entry(k12_check, entry, path, stage) for entry in RULES}
        for entry, before in base.items():
            if entry not in RULES:
                continue
            self.assertEqual(before.get("error"), after[entry].get("error"))
            losses = baseline_losses(before, after[entry])
            # 排名在同一入口、学段和行号保留，且级别至少等于冻结基线。
            self.assertFalse([hit for hit in losses if hit[0] in RANK_RULES], (path, stage, entry, losses))
            for rule, level, line in losses:
                if evidence is None:
                    evidence = clause_evidence(path)
                witness = baseline_exemption_witness(evidence, rule, line)
                self.assertIsNotNone(witness, (entry, stage, rule, level, line, evidence.graph.text))
        return after

    def assert_external_preserved(self, path, stage, before):
        if path.suffix.lower() == ".docx":
            try:
                import docx
            except ImportError:
                self.skipTest("python-docx 未安装")
        self.assert_preserved_with_witness(path, stage, before)

    def test_baseline_preservation_across_regression_and_documents(self):
        extra = {(id_, stage, entry): report for id_, stage, entry, report in self.round2["unlabelled_baseline"]}
        self.assertEqual(len(extra), len(self.round2["unlabelled_baseline"]))
        total = 0
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            for probe in regression_probes():
                path = directory / probe.get("filename", "probe.txt")
                path.write_bytes(probe["text"].encode("utf8"))
                for stage in k12_check.STAGES:
                    with self.subTest(probe=probe["id"], stage=stage):
                        data = probe["by_stage"].get(stage, {})
                        base = {entry: report for entry, report in data.get("baseline_measured", {}).items()
                                if entry in RULES}
                        missing = RULES.keys() - base
                        base.update({entry: extra.pop((probe["id"], stage, entry)) for entry in missing})
                        after = self.assert_preserved_with_witness(path, stage, base)
                        for entry in missing:
                            self.assertFalse(any(level == "P0" for _, level, _ in hits(after[entry]) - hits(base[entry])))
                        total += len(base)
        self.assertFalse(extra)
        self.assertEqual(total, 761 * 3 * 2)
        external = {row["file"] for row in self.round2["external"]}
        sources = {*REPO_ROOT.glob("tests/industry_corpus/*/*.txt"), *REPO_ROOT.glob("examples/*/*"),
                   *SAMPLES.iterdir()}
        added = {r["file"] for r in stage4_corpus() if r["file"].endswith(".txt")}
        self.assertEqual(external | added, {path.relative_to(REPO_ROOT).as_posix() for path in sources
                                            if path.is_file() and path.suffix in k12_check.SUPPORTED_SUFFIXES})
        for record in self.round2["external"]:
            for stage, before in record["base"].items():
                with self.subTest(file=record["file"], stage=stage):
                    self.assert_external_preserved(REPO_ROOT / record["file"], stage, before)

        for record in read_jsonl(SAMPLES / "reference_baseline.jsonl")[1:]:
            for stage in k12_check.STAGES:
                with self.subTest(file=record["file"], stage=stage):
                    self.assert_external_preserved(
                        frozen_document_path(record["file"]), stage,
                        {entry: record["runs"][entry][stage] for entry in RULES},
                    )

    def test_round3_without_docx(self):
        self.assertGreaterEqual(len(set(self.round3["word_skip"])), 10)
        with patch.dict("sys.modules", {"docx": None}):
            for name in self.round3["word_skip"]:
                with self.subTest(file=name):
                    with self.assertRaisesRegex(unittest.SkipTest, "python-docx 未安装"):
                        self.assert_external_preserved(Path(name), "义务教育", {})

    def test_round3_text(self):
        for kind in ("punishment", "benefit", "question", "past", "current", "quote", "source", "unit"):
            self.assertGreaterEqual(sum(case["id"].startswith(f"{kind}-") for case in self.round3["variants"]), 10)
        pairs = {"fee": ("JZ-006", "K12-G05"), "tutor": ("JZ-008", "K12-G09"), "rank": ("JZ-003", "K12-G01")}
        with TemporaryDirectory() as folder:
            path = Path(folder) / "review.txt"
            for case in (*self.round3["text"], *self.round3["variants"]):
                path.write_text(case["text"], encoding="utf8")
                for stage, before in case["base"].items():
                    with self.subTest(id=case["id"], stage=stage):
                        after = self.assert_preserved_with_witness(path, stage, before)
                        for index, entry in enumerate(RULES):
                            actual, old = hits(after[entry]), hits(before[entry])
                            goal = case["goal"]
                            if goal == "keep":
                                assert_preserved(self, before[entry], after[entry], set())
                            self.assertFalse(any(level == "P0" for _, level, _ in actual - old), (entry, actual - old))
                            if not case["family"]:
                                continue
                            rule = pairs[case["family"]][index]
                            levels = {level for rid, level, _ in actual if rid == rule}
                            if goal in {"none", "exempt"}:
                                self.assertEqual(levels, set(), (entry, rule, actual))
                            elif goal == "baseline_rank":
                                self.assertEqual({hit for hit in actual if hit[0] == rule},
                                                 {hit for hit in old if hit[0] == rule})
                            elif goal in {"weak", "wide"}:
                                self.assertEqual(levels, {"P1"}, (entry, rule, actual))
                            elif goal == "baseline_or_p1":
                                self.assertEqual({hit for hit in actual if hit[0] == rule},
                                                 {hit for hit in old if hit[0] == rule} or {(rule, "P1", 1)})
                            elif goal == "hit":
                                self.assertTrue(levels, (entry, rule, actual))
                            elif goal == "no_new_p1":
                                self.assertFalse(any(rid == rule and level == "P1" for rid, level, _ in actual - old))

    def test_review_and_variant_text(self):
        self.assertEqual(len(self.round2["text"]), 338)
        variants = Counter(case["id"].rsplit("-", 1)[0] for case in self.round2["variants"])
        for key in ("rank", "teacher", "free", "voluntary"):
            for side in ("pass", "reject"):
                self.assertGreaterEqual(variants[f"{key}-{side}"], 15)
        self.assertGreaterEqual(variants["voluntary-same-collection"], 5)
        pair = {"fee": ("JZ-006", "K12-G05"), "tutor": ("JZ-008", "K12-G09"), "rank": ("JZ-003", "K12-G01")}
        with TemporaryDirectory() as folder:
            path = Path(folder) / "review.txt"
            for case in (*self.round2["text"], *self.round2["variants"], *self.round2["prior_text"]):
                path.write_text(case["text"], encoding="utf8")
                self.assert_variant_structure(path, case)
                for stage, before in case["base"].items():
                    with self.subTest(id=case["id"], stage=stage):
                        after = self.assert_preserved_with_witness(path, stage, before)
                        for index, entry in enumerate(RULES):
                            rule = pair.get(case["family"], (None, None))[index]
                            actual = hits(after[entry])
                            new = actual - hits(before[entry])
                            levels = {level for r, level, _ in actual if r == rule}
                            goal = case["goal"]
                            if goal in {"hit", "wide", "weak"}:
                                self.assertTrue(levels, (entry, rule, actual))
                            if goal in {"wide", "weak"}:
                                self.assertEqual(levels, {"P1"}, (entry, rule, actual))
                            if goal == "baseline_or_p1":
                                self.assertEqual({hit for hit in actual if hit[0] == rule},
                                                 {hit for hit in hits(before[entry]) if hit[0] == rule} or
                                                 {(rule, "P1", 1)})
                            if goal == "none":
                                self.assertFalse(levels, (entry, rule, actual))
                            if goal == "baseline_rank":
                                self.assertEqual({hit for hit in actual if hit[0] == rule},
                                                 {hit for hit in hits(before[entry]) if hit[0] == rule})
                            if goal in {"none", "no_new_p0", "free_wide", "weak", "wide"}:
                                self.assertFalse(any(level == "P0" for _, level, _ in new), (entry, new))
                            if goal == "keep":
                                assert_preserved(self, before[entry], after[entry], set())
                            if goal == "free_wide":
                                evidence = clause_evidence(path)
                                self.assertFalse(any(issue.id == rule for issue in evidence.added(entry, stage)))

    def assert_variant_structure(self, path, case):
        name = case["id"]
        if not name.startswith(("teacher-pass-", "free-pass-", "voluntary-pass-")):
            return
        evidence = clause_evidence(path)
        graph, module = evidence.graph, evidence.module
        if name.startswith("teacher-pass-"):
            qualified = any(module.teacher_training(graph, a) for a in graph.actions)
        elif name.startswith("free-pass-"):
            qualified = any(module.free_project(graph, graph.clauses[a.clause], a)
                            for a in graph.actions if a.predicate in {"购买", "订购"})
        else:
            qualified = any(module.optional_charge(graph, graph.clauses[a.clause], a, graph.clauses)
                            for a in graph.actions if a.predicate == "代收")
        self.assertTrue(qualified, case)

    def test_round4_reviews_keep_ranking_baseline(self):
        self.assertEqual(Counter(case["group"] for case in self.round4),
                         {"review_a": 97, "review_b": 40, "review_d": 18, "review_targeted": 25,
                          "grammar_accept": 24, "grammar_reject": 250, "line_independence": 8})
        rejected = Counter(case["id"].split("-", 1)[0] for case in self.round4
                           if case["group"] == "grammar_reject")
        self.assertEqual(rejected, {"time": 40, "adverb": 40, "group": 40, "tail": 40,
                                    "particle": 40, "contrast": 40, "hardmark": 10})
        rank_rules = {"parents": "JZ-003", "general": "K12-G01"}
        fee_rules = {"parents": "JZ-006", "general": "K12-G05"}
        with TemporaryDirectory() as folder:
            path = Path(folder) / "review.txt"
            for case in self.round4:
                text, group, goal = (case[key] for key in ("text", "group", "goal"))
                path.write_text(text, encoding="utf8")
                for stage, before in case["base"].items():
                    with self.subTest(id=case["id"], stage=stage):
                        after = self.assert_preserved_with_witness(path, stage, before)
                        had_rank = False
                        for entry, rule in rank_rules.items():
                            old, actual = hits(before[entry]), hits(after[entry])
                            had_rank |= any(r == rule for r, _, _ in old)
                            if group in {"review_a", "grammar_accept", "grammar_reject", "line_independence"} or (
                                    group == "review_targeted" and goal != "punitive_wide"):
                                assert_preserved(self, before[entry], after[entry], set())
                            if group == "review_b":
                                self.assertFalse(any(lv == "P0" for _, lv, _ in actual - old), actual - old)
                            if goal == "punitive_wide":
                                self.assertIn((fee_rules[entry], "P1", 1), actual)
                                self.assertFalse(any(lv == "P0" for _, lv, _ in actual - old), actual - old)
                            if case["id"] in {"first-denial", "second-denial"}:
                                self.assertIn((rule, "P0" if stage == "义务教育" else "P1", 1), actual)
                        if group in {"grammar_accept", "grammar_reject"}:
                            self.assertTrue(had_rank, before)

    def test_round5_review_inputs(self):
        cases = self.fixture["review_round_5"]
        self.assertEqual(Counter(case["script"] for case in cases),
                         {"closing": 140, "deep": 54, "extra": 39})
        with TemporaryDirectory() as folder:
            path = Path(folder) / "review.txt"
            for case in cases:
                path.write_text(case["text"], encoding="utf8")
                for stage, before in case["base"].items():
                    with self.subTest(id=case["id"], stage=stage):
                        after = self.assert_preserved_with_witness(path, stage, before)
                        for entry in RULES:
                            old, actual = hits(before[entry]), hits(after[entry])
                            if case["goal"] == "no_new_p0":
                                self.assertFalse(any(level == "P0" for _, level, _ in actual - old))
                            if case["goal"] == "keep":
                                assert_preserved(self, before[entry], after[entry], set())
                            if case["goal"] == "unchanged":
                                previous = hits(case["previous"][stage][entry])
                                self.assertEqual({h for h in actual if h[0] not in RANK_RULES},
                                                 {h for h in previous if h[0] not in RANK_RULES})
                                self.assertLessEqual(actual - previous,
                                                     {h for h in old if h[0] in RANK_RULES})

    def test_ranking_baseline_in_multiline_csv_cells(self):
        text = "学校不按成绩排名。"
        with TemporaryDirectory() as folder:
            path = Path(folder) / "review.csv"
            path.write_text(f'事项,内容\n排名,"{text}\n补充说明"\n'
                            f'排名,"材料如下：\n{text}"\n'
                            f'排名,"引文开始“\n前言\n{text}\n”"\n', encoding="utf8")
            for entry, rule in (("parents", "JZ-003"), ("general", "K12-G01")):
                report = run_entry(k12_check, entry, path, "义务教育")
                self.assertEqual({hit for hit in hits(report) if hit[0] == rule},
                                 {(rule, "P0", 2), (rule, "P0", 3), (rule, "P0", 4)})

    def test_ranking_baseline_in_multiline_xlsx_cells(self):
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl 未安装")
        text = "学校不按成绩排名。"
        with TemporaryDirectory() as folder:
            path = Path(folder) / "review.xlsx"
            book = Workbook()
            book.active.append(["事项", "内容"])
            book.active.append(["排名", text + "\n补充说明"])
            book.active.append(["排名", "材料如下：\n" + text])
            book.save(path)
            for entry, rule in (("parents", "JZ-003"), ("general", "K12-G01")):
                report = run_entry(k12_check, entry, path, "义务教育")
                self.assertEqual({hit for hit in hits(report) if hit[0] == rule}, {(rule, "P0", 2), (rule, "P0", 3)})

    def test_round6_reviews_keep_ranking_baseline_across_formats(self):
        cases = self.fixture["review_round_6"]
        self.assertEqual(Counter(case["group"] for case in cases),
                         {"visible": 70, "unicode": 32, "csv": 10, "xlsx": 7, "docx": 8,
                          "compliant": 40, "colon": 8, "markdown": 7, "sample": 1})
        with TemporaryDirectory() as folder:
            for case in cases:
                with self.subTest(id=case["id"]):
                    suffix, value = case["format"], case["input"]
                    path = Path(folder) / f"probe.{suffix}"
                    if suffix == "file":
                        path = REPO_ROOT / value
                    elif suffix == "xlsx":
                        try:
                            from openpyxl import Workbook
                        except ImportError:
                            self.skipTest("openpyxl 未安装")
                        book = Workbook()
                        for row in value:
                            book.active.append(row)
                        book.save(path)
                    elif suffix == "docx":
                        try:
                            from docx import Document
                        except ImportError:
                            self.skipTest("python-docx 未安装")
                        doc = Document()
                        for parts in value:
                            doc.add_paragraph("\n".join(parts))
                        doc.save(path)
                    else:
                        path.write_bytes(value.encode("utf8"))
                    for stage, before in case["base"].items():
                        with self.subTest(stage=stage):
                            after = self.assert_preserved_with_witness(path, stage, before)
                            for entry in RULES:
                                self.assertEqual({h for h in hits(after[entry]) if h[0] in RANK_RULES},
                                                 {h for h in hits(before[entry]) if h[0] in RANK_RULES})
                                if case["group"] == "compliant":
                                    allowed = case.get("known_p0", {}).get(stage, {}).get(entry, [])
                                    self.assertEqual({h for h in hits(after[entry]) - hits(before[entry]) if h[1] == "P0"},
                                                     {tuple(h) for h in allowed})

    def test_review_word_blocks(self):
        try:
            from docx import Document
        except ImportError:
            self.skipTest("python-docx 未安装")
        self.assertEqual(len(self.round2["docx"]), 22)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "review.docx"
            for case in (*self.round2["docx"], *self.round2["prior_docx"]):
                doc = Document()
                for kind, values in case["blocks"]:
                    if kind == "p":
                        doc.add_paragraph(values)
                    else:
                        table = doc.add_table(rows=len(values), cols=len(values[0]))
                        for row, cells in zip(table.rows, values):
                            for cell, text in zip(row.cells, cells):
                                cell.text = text
                doc.save(path)
                for stage, before in case["base"].items():
                    with self.subTest(id=case["id"], stage=stage):
                        self.assert_preserved_with_witness(path, stage, before)
                for entry, expected in case.get("table_body", {}).items():
                    issues = getattr(k12_check, f"check_{entry}")(path, "义务教育")["issues"]
                    actual = [[i[k] for k in ("id", "level", "line", "excerpt")] for i in issues]
                    rules_3b = {"K12-G04", "K12-G06"}
                    self.assertEqual([row for row in actual if row[0] not in rules_3b], expected, (case["id"], entry))
                    stage3b = json.loads((SAMPLES / "stage3b_word.json").read_text(encoding="utf8"))
                    self.assertEqual([row for row in actual if row[0] in rules_3b], stage3b[case["id"]][entry])
