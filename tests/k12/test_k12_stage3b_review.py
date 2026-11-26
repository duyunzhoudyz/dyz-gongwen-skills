"""第 3b 步复审探针。冻结预期分别来自 47b93e1、0705059。"""
import json
import re
from unittest.mock import patch
from itertools import product

from tests.k12.test_k12_check import HAS_DOCX, K12TestCase, SAMPLES, k12_check
from tests.k12.test_k12_stage1 import probe_hits
from tests.k12.test_k12_stage3b import comment_digest


# 首评样例原封存。复审裁决撤去只有“项目”或“费用”作项目列的表头证据。
_GENERIC_TABLE_CASES = {"G06_gap_04_col_header_biaozhun_plain"} | {
    f"新R3-{kind}-{index}" for kind in ("MD", "Word") for index in range(10, 19)
}


def samples():
    with (SAMPLES / "stage3b_review_r1.jsonl").open(encoding="utf8") as stream:
        yield from map(json.loads, stream)


BREAKS = ("\u2028", "\u2029", "\v", "\f", "\x85", "\r\n", "\r")
SEEDS = (
    "学校按成绩排名。每生收取校服费180元。",
    "全校公布学生成绩排名。每生收费120元。",
    "低保家庭学生王小明享受助学金。",
    "特困学生李文静享受补助。",
    "全体学生必须购买校服，每人缴纳校服费180元。",
    "学校统一征订教辅资料，每生收取资料费30元。",
    "各班收取研学费260元。学校按成绩排名。",
    "每人缴纳餐费100元。低保家庭学生王小明享受助学金。",
)


def break_cases():
    for seed_id, seed in enumerate(SEEDS, 1):
        for sep_id, sep in enumerate(BREAKS, 1):
            for pos in range(len(seed) + 1):
                value = seed[:pos] + sep + seed[pos:]
                key = f"{seed_id}-{sep_id}-{pos}"
                yield "txt-" + key, {"text": value}
                if pos in (1, len(seed) // 2, len(seed) - 1):
                    yield "docx-" + key, {"word": [["p", value]]}


def materialize(folder, row):
    path = folder / row.get("filename", "probe.docx" if "word" in row else "probe.md")
    if "word" not in row:
        path.write_bytes(row["text"].encode("utf8"))
        return path
    from docx import Document
    from docx.enum.text import WD_BREAK
    doc = Document()
    for kind, value in row["word"]:
        if kind == "p":
            paragraph = doc.add_paragraph()
            # XML 1.0 禁止 VT、FF 字面字符；Word 原生用 w:br 表达软换行与分页。
            for piece in re.split(r"([\v\f])", value):
                if piece in ("\v", "\f"):
                    paragraph.add_run().add_break(WD_BREAK.LINE if piece == "\v" else WD_BREAK.PAGE)
                elif piece:
                    paragraph.add_run(piece)
        else:
            table = doc.add_table(rows=len(value), cols=len(value[0]))
            for cells, values in zip(table.rows, value):
                for cell, text in zip(cells.cells, values):
                    cell.text = text
    doc.save(path)
    return path


class Stage3bReviewTests(K12TestCase):
    def assert_retained(self, baseline, now):
        for rule, level, line in baseline:
            self.assertTrue(any(r == rule and n == line and lv <= level for r, lv, n in now),
                            (rule, level, line, now))

    def test_insert_every_separator_at_every_text_position_and_in_word(self):
        frozen = json.loads((SAMPLES / "stage3b_review_breaks.json").read_text(encoding="utf8"))
        for key, row in break_cases():
            snapshot = frozen["results"][frozen["indexes"].pop(key)]
            if "word" in row and not HAS_DOCX:
                continue
            path = materialize(self.tmp, row)
            for entry, (old_rc, old_hits, stage3a_hits, prior_hits) in zip(("parents", "general"), snapshot):
                with self.subTest(key=key, entry=entry):
                    rc, output, error = self.run_main(entry, str(path), "--json")
                    self.assertEqual((rc, error), (old_rc, ""))
                    now = probe_hits(json.loads(output))
                    self.assert_retained(old_hits, now)
                    self.assert_retained(stage3a_hits, now)
                    self.assert_retained(prior_hits, now)
        self.assertFalse(frozen["indexes"])

    def test_review_inputs_and_new_variants(self):
        for row in samples():
            if "word" in row and not HAS_DOCX:
                continue
            path = materialize(self.tmp, row)
            for stage, entry in product(k12_check.STAGES, ("parents", "general")):
                with self.subTest(case=row["id"], stage=stage, entry=entry):
                    result = getattr(k12_check, "check_" + entry)(path, stage)
                    now = probe_hits(result)
                    base = row["base"][stage][entry]
                    self.assert_retained(base, now)
                    added_p0 = [h for h in now if h[1] == "P0" and h not in base]
                    self.assertEqual(added_p0, row.get("allowed_p0", {}).get(stage, {}).get(entry, []))
                    if row.get("rule") and entry == "general":
                        actual = [r for r, lv, n in now]
                        if row["id"] in _GENERIC_TABLE_CASES:
                            self.assertNotIn(row["rule"], actual)
                        else:
                            self.assertIn(row["rule"], actual)
                    if row.get("question"):
                        graph = k12_check.load_clause_module().analyze(row["text"])
                        self.assertTrue(graph.clauses)
                        self.assertTrue(all(c.question for c in graph.clauses if c.parent is None))
                    if row.get("forbidden"):
                        rendered = k12_check.render_check_text(result) + json.dumps(result, ensure_ascii=False)
                        for name in row["forbidden"]:
                            self.assertNotIn(name, rendered)
                    if row.get("fallback"):
                        self.assertIn(k12_check.shared_names()[0].TABLE_UNKNOWN_HINT,
                                      [i["message"] for i in result["issues"]])

    def test_word_paragraph_offsets_with_literal_breaks(self):
        for sep in BREAKS:
            with self.subTest(sep=repr(sep)):
                path = self.tmp / "分段.docx"
                doc = k12_check.Document(path=path, kind="docx", lines=[
                    "正文" + sep + "学校按成绩排名。", "低保家庭学生王小明享受助学金。", "每生收取校服费180元。"])
                with patch.object(k12_check, "load_document", return_value=doc):
                    rc, output, err = self.run_main("general", str(path), "--json")
                self.assertEqual((rc, err), (0, ""))
                now = probe_hits(json.loads(output))
                self.assertIn(["K12-G04", "P0", 2], now)
                self.assertIn(["K12-G06", "P1", 3], now)
                self.assertIn(["K12-G01", "P0", 1], now)

    def test_amount_header_requires_an_item_in_the_same_row(self):
        for value in ("| 序号 | 单价 |\\n|---|---|\\n| 1 | 180元 |",
                      "| 项目 | 金额 |\\n|---|---|\\n| | 180元 |\\n| 校服 | |"):
            now = probe_hits(k12_check.check_general(self.write("收费表.md", value)))
            self.assertNotIn("K12-G06", [rule for rule, level, line in now])

    def test_direct_citation_does_not_cover_a_separate_amount(self):
        for lead in ("依据区教育局《校服管理办法》执行；", "根据区教育局《研学收费标准》；"):
            row = self.write("通知.md", lead + "每生收取180元。")
            self.assertIn(["K12-G06", "P1", 1], probe_hits(k12_check.check_general(row)))

    def test_question_belongs_only_to_the_sentence_it_terminates(self):
        graph = k12_check.load_clause_module().analyze("学生王小明属于资助对象!?。学生李文静患有癫痫。")
        self.assertEqual([(c.separator, c.question) for c in graph.clauses], [("!?。", True), ("。", False)])

    def test_review_comments_and_name_scores(self):
        archive = json.loads((SAMPLES / "stage3b_review_aux.json").read_text(encoding="utf8"))
        for row in archive["comments"]:
            path = materialize(self.tmp, row)
            facts = self.write("facts.md", row["facts"]) if row.get("facts") else None
            self.assertEqual(comment_digest(k12_check, path, "义务教育", facts), row["digest"], row["filename"])
        for value, expected in archive["ellipsis"]:
            self.assertEqual([value[a:b] for a, b in k12_check._comment_tagged_values(value)], expected)
        gw, lex = k12_check.shared_names()
        anchor = gw.compile_anchors({"frame": [{"re": r"^(?P<n>[\u3400-\u9fff]{2,4})$", "strength": 1}]})
        for group in archive["name_scores"]:
            actual = [[word, h.score] for word in group["words"] for h in gw.find_names(word, anchor, lex)
                      if h.score >= group["threshold"]]
            self.assertEqual(actual, group["hits"])

    def test_review_http(self):
        from tests.tools.test_local_toolbox_industry import LocalToolboxK12CommentsHTTPTest as HTTP
        HTTP.setUpClass()
        self.addCleanup(HTTP.tearDownClass)
        client = HTTP()
        archive = json.loads((SAMPLES / "stage3b_review_aux.json").read_text(encoding="utf8"))
        for key, industry, text, forbidden in archive["http"]:
            with self.subTest(key=key):
                result = client.post_raw(json.dumps({"industry": industry, "b": text, "stage": "义务教育"}),
                                         forbidden)
                expected_rule = {"H03": "JZ-006", "H05": "K12-G06"}.get(key[:3], "K12-G04")
                self.assertIn(expected_rule, result["text"])
                self.assertEqual(result["ok"], key.startswith("H05"))
