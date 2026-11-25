"""第 3b 步门禁。快照由 47b93e1 与 9afe826 独立运行取得。"""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.k12.test_k12_check import HAS_DOCX, K12TestCase
from tests.k12.test_k12_stage1 import REPO_ROOT, SAMPLES, k12_check, read_jsonl, run_entry
from tests.k12.test_k12_stage3a import baseline_losses, regression_probes
from tests.k12.stage3a_checks import hits


def audit_inputs(folder):
    archive = json.loads((SAMPLES / "stage3a_adversarial.json").read_text(encoding="utf8"))["review_round_2"]
    extra = {(key, stage, entry): report for key, stage, entry, report in archive["unlabelled_baseline"]}
    for case in regression_probes():
        path = folder / case.get("filename", "probe.txt")
        path.write_bytes(case["text"].encode("utf8"))
        facts = None
        if "facts" in case:
            facts = folder / "facts.md"
            facts.write_bytes(case["facts"].encode("utf8"))
        base = {}
        for stage in k12_check.STAGES:
            measured = case["by_stage"].get(stage, {}).get("baseline_measured", {})
            base[stage] = {e: measured[e] if e in measured else extra.pop((case["id"], stage, e))
                           for e in ("parents", "general")}
        yield "regression", case["id"], path, facts, base, case
    assert not extra
    documents = {r["file"]: r["base"] for r in archive["external"]}
    for r in read_jsonl(SAMPLES / "reference_baseline.jsonl")[1:]:
        documents.setdefault(r["file"], {s: {e: r["runs"][e][s] for e in ("parents", "general")}
                                         for s in k12_check.STAGES})
    for file, base in documents.items():
        yield "documents", file, REPO_ROOT / file, None, base, {}
    for case in read_jsonl(SAMPLES / "stage3b_cases.jsonl"):
        path = folder / "probe.txt"
        path.write_bytes(case["text"].encode("utf8"))
        base = {stage: {e: {"hits": v} for e, v in row.items()} for stage, row in case["baseline"].items()}
        yield "own", case["id"], path, None, base, case


def comment_digest(engine, path, stage, facts):
    try:
        report = engine.check_comments(path, stage=stage, facts_path=facts)
        rendered = engine.render_check_text(report)
        value = json.dumps(report, ensure_ascii=False, indent=2) + "\n" + rendered
    except engine.InputError as exc:
        value = str(exc)
    return sha256(value.encode("utf8")).hexdigest()


class Stage3bTests(K12TestCase):
    def test_full_baseline_frozen_exceptions_and_admission(self):
        frozen = json.loads((SAMPLES / "stage3b_frozen.json").read_text(encoding="utf8"))
        losses = []
        totals = Counter()
        comments = {key: sha256() for key in frozen["comments"]}
        prior_rules = {key: sha256() for key in frozen["stage3a_rules"]}
        with TemporaryDirectory() as folder:
            for group, key, path, facts, base, case in audit_inputs(Path(folder)):
                ext = path.suffix.lower()
                if ext == ".docx" and not HAS_DOCX:
                    continue
                for stage, reports in base.items():
                    digest_group = "word" if ext == ".docx" else group
                    digest = comment_digest(k12_check, path, stage, facts)
                    comments[digest_group].update((key + stage + digest).encode("utf8"))
                    for entry in ("parents", "general"):
                        with self.subTest(key=key, stage=stage, entry=entry):
                            before = reports[entry]
                            actual = run_entry(k12_check, entry, path, stage)
                            self.assertEqual(actual.get("error"), before.get("error"))
                            losses.extend([group, key, stage, entry, *hit] for hit in baseline_losses(before, actual))
                            old_hits = sorted(h for h in hits(actual) if h[0] not in ("K12-G04", "K12-G06"))
                            row = json.dumps([key, stage, entry, old_hits], ensure_ascii=False)
                            prior_rules[digest_group].update(row.encode("utf8"))
                            added = hits(actual) - hits(before)
                            p0 = {r for r, level, line in added if level == "P0"}
                            if group == "regression":
                                data = case["by_stage"].get(stage, {})
                                expected = data.get("expected", {}).get(entry, {})
                                marked = {r for r in data.get("new_p0_evidence", {}) if r in expected}
                                self.assertEqual({(r, n) for r, lv, n in added if lv == "P0"},
                                                 {(r, data["new_p0_evidence"][r]["line"]) for r in marked})
                                totals["p0"] += len(p0)
                            elif group == "documents":
                                self.assertFalse(p0)
                            elif group == "own":
                                expected_p0 = set()
                                if entry == "general" and case["kind"] == "违规":
                                    rule = case["rule"]
                                    self.assertIn((rule, case["level"]), {(r, lv) for r, lv, _ in hits(actual)})
                                    if case["level"] == "P0" and not any(r == rule and lv == "P0" for r, lv, _ in hits(before)):
                                        expected_p0.add(rule)
                                self.assertEqual(p0, expected_p0)
                                totals[case["kind"]] += 1
        self.assertEqual(losses, frozen["losses"])
        self.assertEqual(totals, {"p0": 254, "合规": 66 * 6, "违规": 40 * 6})
        for key, digest in comments.items():
            if key != "word" or HAS_DOCX:
                self.assertEqual(digest.hexdigest(), frozen["comments"][key], key)
                self.assertEqual(prior_rules[key].hexdigest(), frozen["stage3a_rules"][key], key)

    def test_name_probe_and_catalog(self):
        probe = next(p for p in regression_probes() if p["id"] == "R3-HTTP_r3_general_name_mask")
        path = self.write("王小明.txt", probe["text"])
        forbidden = probe["by_stage"]["义务教育"]["expected_output"]["forbidden_literals"]
        for flags in ((), ("--json",)):
            rc, out, err = self.run_main("general", str(path), *flags)
            self.assertEqual((rc, err), (0, ""))
            self.assertIn("K12-G04", out)
            for name in forbidden:
                self.assertNotIn(name, out)
        rules = {r["id"]: r for r in k12_check.rule_catalog()["rules"]}
        self.assertEqual(rules["K12-G06"]["stage_levels"], {"general": dict.fromkeys(k12_check.STAGES, ["P1"])})

    @unittest.skipUnless(HAS_DOCX, "需要既有可选库 python-docx")
    def test_word_name_fallback_amount_and_drafting_boundary(self):
        from docx import Document
        doc = Document()
        doc.add_paragraph("正文")
        t = doc.add_table(rows=3, cols=4)
        rows = (("学生姓名", "收费项目", "收费标准", "处分"),
                ("王小明", "校服费", "180元", "无"), ("王小明、待识别字符Ω", "研学费", "260元", "无"))
        for row, values in zip(t.rows, rows):
            for cell, value in zip(row.cells, values):
                cell.text = value
        doc.add_paragraph("【起草说明】")
        doc.add_table(rows=1, cols=1).cell(0, 0).text = "收取说明费999元"
        path = self.tmp / "王小明.docx"
        doc.save(path)
        for entry in ("parents", "general"):
            report = getattr(k12_check, "check_" + entry)(path)
            self.assertNotIn("王小明", json.dumps(report, ensure_ascii=False))
            self.assertEqual({i["level"] for i in report["issues"] if i["id"] == "K12-G04"}, {"P1"})
            messages = {i["message"] for i in report["issues"] if i["id"] == "K12-G04" and i["line"] == 5}
            self.assertEqual(messages, {"表格姓名列出现真实姓名", k12_check.shared_names()[0].TABLE_UNKNOWN_HINT})
            fee = {i["line"] for i in report["issues"] if i["id"] == "K12-G06"}
            self.assertEqual(fee, {4, 5} if entry == "general" else set())
            self.assertNotIn("JZ-007", [i["id"] for i in report["issues"]])

    def test_prose_cannot_borrow_a_fee_source_from_an_intervening_table(self):
        text = "本月每人收取资料费180元。\n| 收费项目 | 收费依据 |\n| --- | --- |\n| 资料费 | 《服务性收费办法》 |\n家委会另行说明。"
        actual = run_entry(k12_check, "general", self.write("费用.md", text), "高中")
        self.assertIn(("K12-G06", "P1", 1), hits(actual))
        text = "依区教育局《校服收费规范》执行。\n每生收取校服费180元。"
        actual = run_entry(k12_check, "general", self.write("费用.md", text), "高中")
        self.assertFalse(any(rule == "K12-G06" for rule, _, _ in hits(actual)))

    def test_comment_number_long_tails(self):
        for text in ("S01：考号：138 1234 5678 139 5055 6677，你读书12本。",
                     "| 学号 | 评语 |\n|---|---|\n| 138 1234 5678 139 5055 6677 | 你读书12本。 |"):
            path = self.write("138 1234 5678_139 5055 6677.md", text)
            self.assertNotIn("5678", k12_check.check_comments(path)["file"])
            self.assertNotIn("6677", k12_check.check_comments(path)["file"])
        for header in ("考号", "姓名/考号"):
            path = self.write("A12.34.56.md", f"| {header} | 评语 |\n|---|---|\n"
                              "| A12.34.56、B23.45.67 | 你复核了A12.34.56和B23.45.67。 |")
            report = k12_check.check_comments(path)
            self.assertNotIn("A12.34.56", json.dumps(report, ensure_ascii=False))
            ids = k12_check.CommentNumbers()
            k12_check._comment_register_table(ids, [[[header], ["A12.34.56、B23.45.67"]]])
            ids.prepare()
            self.assertNotIn("B23.45.67", ids.clean_prose("记录B23.45.67。"))
        self.assertEqual(list(k12_check._comment_tagged_values("学号：…12345")), [])
