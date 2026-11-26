"""第 4 步门禁。重跑语料并与双基线快照核对，合并正式文档计算噪声。"""
from collections import defaultdict
from hashlib import sha256
import json
import unittest

from tests.k12.stage3a_checks import RULES, assert_noise, hits, noise_mirrors
from tests.k12.test_k12_stage1 import (
    REPO_ROOT, REVIEW_ADDON, SAMPLES, k12_check, read_jsonl, run_entry, stage4_corpus,
)
from tests.k12.test_k12_stage3a import baseline_losses, document_deltas
from tests.k12.test_k12_stage3b import comment_digest
from tests.k12.stage5_checks import stage5_expected


CORPUS = "tests/industry_corpus/k12"
# 一处在原登记入口，另外两处只出现在补跑入口或学段。两份冻结基线已经同位置报出。
EXISTING_P0 = {
    ("A_k02_致家长的一封信.txt", "general", "义务教育"): {("K12-G01", "P0", 11)},
    ("A_k07_家长会讲话稿.txt", "parents", "义务教育"): {("JZ-003", "P0", 17)},
    ("A_k08_高中致家长信.txt", "parents", "义务教育"): {("JZ-003", "P0", 7)},
}


class Stage4CorpusTests(unittest.TestCase):
    def assert_name_echoes(self, path, entry, stage, echoes, *, names=(), facts_path=None):
        kwargs = {"facts_path": facts_path} if facts_path is not None else {}
        report = getattr(k12_check, f"check_{entry}")(path, stage=stage, **kwargs)
        structured = json.dumps(report, ensure_ascii=False)
        rendered = k12_check.render_check_text(report)
        by_name = {echo["name"]: echo for echo in echoes}
        for name in sorted(set(names) | by_name.keys()):
            echo = by_name.get(name)
            rule = echo["matrix_rules"].get(entry) if echo else None
            counts = {"json": structured.count(name), "text": rendered.count(name)}
            if rule is None:
                self.assertEqual(counts, {"json": 0, "text": 0}, f"新增姓名回显：{name}")
                continue
            self.assertTrue(any(counts.values()), f"{name} 已不再回显，请从已知回显移到正常姓名遮蔽期望")
            self.assertEqual(counts, echo["actual_counts"])
            excerpts = [(issue["id"], issue["line"], issue["excerpt"]) for issue in report["issues"]
                        if name in issue["excerpt"]]
            self.assertEqual(excerpts, [(rule, echo["line"], echo["actual_excerpt"])])

    def test_dual_baselines_exact_hits_comments_and_combined_noise(self):
        corpus = REPO_ROOT / CORPUS
        cases = json.loads((corpus / "cases.json").read_text(encoding="utf8"))["docs"]
        facts = {f"{CORPUS}/{case['file']}": corpus / case["facts"] for case in cases if "facts" in case}
        names_by_file = defaultdict(set)
        echoes_by_file = defaultdict(list)
        for case in cases:
            filename = case["file"]
            names_by_file[filename].update(case.get("names", ()))
            echoes_by_file[filename].extend(case.get("known_name_echo", ()))
        records = stage4_corpus()
        covered = {rec["file"] for rec in records}
        inputs = {path.relative_to(REPO_ROOT).as_posix()
                  for path in (*corpus.glob("*.txt"), *corpus.glob("*.md"))}
        self.assertEqual(covered, inputs | {REVIEW_ADDON})
        self.assertEqual(len(records), len(covered))
        self.assertEqual({f"{CORPUS}/{case['file']}" for case in cases}
                         | {p.relative_to(REPO_ROOT).as_posix() for p in facts.values()}, inputs)

        old_records = read_jsonl(SAMPLES / "reference_baseline.jsonl")[1:]
        # 语料 README 是列有违规例句的测试手册。历史对照仍使用它的冻结副本。
        noise_records = [record for record in old_records if record["file"] not in covered]
        deltas = list(document_deltas(noise_records))
        p0_checked = set()
        for rec in records:
            filename = rec["file"]
            path = REPO_ROOT / filename
            self.assertEqual(sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest(), rec["sha256"], filename)
            lines = path.read_text(encoding="utf8").splitlines()
            entries = set(RULES)
            if filename in facts or filename == REVIEW_ADDON:
                entries.add("comments")
            if filename in facts:
                entries.add("comments_facts")
            self.assertEqual(set(rec["runs"]), entries, filename)
            baseline_runs = {}
            for mode, runs in rec["runs"].items():
                self.assertEqual(tuple(runs), k12_check.STAGES, (filename, mode))
                entry = "comments" if mode == "comments_facts" else mode
                facts_path = facts[filename] if mode == "comments_facts" else None
                baseline_runs[mode] = {}
                for stage, values in runs.items():
                    with self.subTest(file=filename, entry=mode, stage=stage):
                        base, second, expected, *comments = values
                        second = base if second is None else second
                        expected = second if expected is None else expected
                        baseline_runs[mode][stage] = base
                        actual = run_entry(k12_check, entry, path, stage, facts_path)
                        self.assertEqual(actual, stage5_expected(path.name, mode, stage, expected))
                        for before in (base, second):
                            self.assertEqual(actual.get("error"), before.get("error"))
                            self.assertEqual(baseline_losses(before, actual), [])
                        if entry == "comments":
                            self.assertEqual([comment_digest(k12_check, path, stage, facts_path)], comments)
                        if rec["category"] == "clean_corpus":
                            key = (path.name, mode, stage)
                            allowed = EXISTING_P0.get(key, set())
                            for report in (base, second, actual):
                                self.assertEqual({hit for hit in hits(report) if hit[1] == "P0"}, allowed)
                            if allowed:
                                p0_checked.add(key)
                        names = names_by_file[path.name]
                        echoes = echoes_by_file[path.name]
                        if names or echoes:
                            self.assert_name_echoes(
                                path, entry, stage, echoes, names=names, facts_path=facts_path,
                            )
                        if entry in RULES:
                            for rule, level, line in sorted(hits(actual) - hits(base)):
                                deltas.append((rec["category"], filename, entry, stage,
                                               rule, level, line, lines[line - 1]))
            noise_records.append({**rec, "runs": baseline_runs})
        self.assertEqual(p0_checked, set(EXISTING_P0))
        mirrors = noise_mirrors(self, REPO_ROOT, SAMPLES, noise_records, k12_check.STAGES)
        self.assertEqual(len(mirrors), 0)
        assert_noise(self, deltas, mirrors)
