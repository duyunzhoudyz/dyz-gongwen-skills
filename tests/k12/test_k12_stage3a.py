from collections import Counter
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.k12.stage3a_checks import (
    PAIRS, RULES, assert_noise, assert_preserved, assert_probe_additions,
    document_exemptions, hits, noise_mirrors, probe_exemptions,
)
from tests.k12.test_k12_stage1 import REGRESSION, REPO_ROOT, SAMPLES, k12_check, read_jsonl, run_entry


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
        path = REPO_ROOT / filename
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
        self.assertEqual(len(mirrors), 8)
        assert_noise(self, list(document_deltas(records)), mirrors)
        for record in records:
            for entry in RULES:
                for stage in k12_check.STAGES:
                    before = record["runs"][entry][stage]
                    exempt = document_exemptions(record, entry, before)
                    if exempt:
                        actual = run_entry(k12_check, entry, REPO_ROOT / record["file"], stage)
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
        self.assertEqual(set(pending), {"K12-G04", "K12-G06"})
        for rule, ids in pending.items():
            self.assertEqual(ids, [p["id"] for p in regression_probes() if any(
                rule in m for d in p["by_stage"].values() for m in d["expected"].values())])

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
            self.assertIn(("JZ-008", "P1", 1), result["parents"]["final"])
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
