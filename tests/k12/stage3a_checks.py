from collections import Counter
from hashlib import sha256
import json


RULES = {
    "parents": frozenset(("JZ-003", "JZ-006", "JZ-008", "JZ-014")),
    "general": frozenset(("K12-G01", "K12-G04", "K12-G05", "K12-G06", "K12-G09")),
}
EXEMPT_RULES = frozenset(("JZ-008",))
RANK_RULES = frozenset(("JZ-003", "K12-G01"))
PAIRS = {"JZ-006": "K12-G05", "JZ-008": "K12-G09"}
FAMILIES = {parent: general for parent, general in PAIRS.items()}
FAMILIES.update({"JZ-003": "K12-G01", "JZ-014": "K12-G01"})
RANK = {"P0": 0, "P1": 1, "P2": 2}
DOCUMENT_ADDITIONS = {
    "skills/gongwen-k12/references/review-addon.md": {
        "parents": {("JZ-008", "P1", 35), ("JZ-008", "P1", 46)},
        "general": {("K12-G09", "P1", 35), ("K12-G09", "P1", 46)},
    },
    "tests/k12/samples/parents_must_fail.txt": {
        "parents": {("JZ-006", "P1", 13)},
        "general": {("K12-G05", "P1", 13), ("K12-G06", "P1", 13), ("K12-G05", "P1", 15), ("K12-G09", "P1", 17)},
    },
    "tests/k12/samples/parents_must_fail_speech.txt": {
        "general": {("K12-G05", "P1", 11)},
    },
}


def hits(report):
    return {tuple(hit) for hit in report.get("hits", ())}


def assert_preserved(test, before, after, exempt):
    test.assertEqual(after.get("error"), before.get("error"))
    for rule, level, line in hits(before) - exempt:
        test.assertTrue(
            any(rule == r and line == n and RANK[lv] <= RANK[level] for r, lv, n in hits(after)),
            (rule, level, line, after),
        )


def probe_exemptions(before, expected):
    return {hit for hit in hits(before) if hit[0] in EXEMPT_RULES and expected.get(hit[0]) == ["SKIP"]}


def assert_probe_additions(test, entry, before, after, new_layer):
    for rule, level, line in hits(after) - hits(before):
        test.assertIn(rule, RULES[entry])
        test.assertIn(level, new_layer.get(rule, {}).get("allowed", ()), (rule, level, line))
        test.assertIn(line, new_layer[rule]["lines"])


def document_exemptions(record, entry, before):
    return set()


def document_additions(filename, entry, stage, records, mirrors):
    allowed = DOCUMENT_ADDITIONS.get(filename, {}).get(entry, set()).copy()
    if entry == "general":
        frozen = records[filename]["runs"]["parents"][stage]
        allowed.update((PAIRS[rule], "P1", line) for rule, _, line in hits(frozen)
                       if (filename, line, rule) in mirrors)
    return allowed


def noise_mirrors(test, root, samples, records, stages):
    by_file = {record["file"]: record for record in records}
    ledger = json.loads((samples / "stage3a_reference_mirrors.json").read_text(encoding="utf8"))
    keys = set()
    for item in ledger:
        filename, line, rule = (item[k] for k in ("file", "line", "baseline_rule"))
        test.assertNotIn((filename, line, rule), keys)
        test.assertTrue(filename.startswith("skills/gongwen-k12/references/"))
        test.assertEqual(by_file[filename]["category"], "reference")
        path = root / filename
        test.assertTrue(path.resolve().is_relative_to(root / "skills/gongwen-k12/references"))
        text = path.read_text(encoding="utf8").splitlines()[line - 1]
        test.assertEqual(sha256(text.encode("utf8")).hexdigest(), item["sha256"], (filename, line, text))
        test.assertIn(rule, PAIRS)
        for stage in stages:
            frozen = by_file[filename]["runs"]["parents"][stage]
            test.assertTrue(any(r == rule and n == line for r, _, n in hits(frozen)), (item, stage))
        keys.add((filename, line, rule))
    return keys


def assert_noise(test, deltas, mirrors):
    # 所有正文 P1 都记录，只有已标明基线违规的正文样本排除在合规文书门槛外。
    norm = [item for item in deltas if item[0] not in {"violation_corpus", "engine_sample"}]
    counts = Counter()
    deducted = set()
    for category, filename, entry, stage, rule, level, line, original in norm:
        test.assertNotEqual(level, "P0", (filename, entry, stage, rule, line, original))
        if level != "P1":
            continue
        test.assertNotRegex(original.strip(), r"^《[^》]+》[。；，]?$|收费(?:须|应|必须)(?:有|写明)(?:明确的?)?依据")
        mirror = next(((filename, line, r) for r, g in PAIRS.items() if g == rule), None)
        if category == "reference" and entry == "general" and mirror in mirrors:
            deducted.add(mirror)
            continue
        counts[(filename, line, FAMILIES.get(rule, rule))] = 1
    test.assertEqual(deducted, mirrors)
    for filename, count in Counter(f for f, _, _ in counts).items():
        test.assertLessEqual(count, 2, (filename, sorted(counts)))
    for family, count in Counter(rule for _, _, rule in counts).items():
        test.assertLessEqual(count, 3, (family, sorted(counts)))
