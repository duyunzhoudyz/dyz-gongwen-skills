"""第 3b 步第三轮定点复核。原件预期以父提交及逐条裁决为准。"""
import json
import sys

from tests.k12.test_k12_check import HAS_DOCX, K12TestCase, SAMPLES, k12_check
from tests.k12.test_k12_stage3b_review import materialize
from tests.k12.test_k12_stage3b_review2 import measured


def table_cases():
    # 项目列、金额列、金额、是否应提示；同一输入分别走 Markdown 和 Word。
    return (
        ("收费项目名称", "金额（元）", "125", True),
        ("费用 项目", "单价（元/人）", "0.25", True),
        ("收费科目", "费用", "十二元", True),
        ("收费明细", "单价", "五十元", True),
        ("缴费明细", "标准", "20元", True),
        ("项 目", "收费 金额", "35元", True),
        ("类别", "缴费金额(元/生)", "66", True),
        ("名称", "代收标准", "120元", True),
        ("项目", "收费单价", "30元", True),
        ("名称", "代收金额", "28元", True),
        ("类别", "缴费价格", "53元", True),
        ("项目", "金额（元）", "100元", False),
        ("名称", "单价（元/人）", "38", False),
        ("类别", "标准", "80元", False),
        ("预算项目", "支出金额", "200元", False),
        ("退费项目", "金额", "75元", False),
        ("收费明细", "金额（历史合计）", "70元", False),
        ("缴费项目", "标准", "0元", False),
        ("收费项目名称", "单价", "负零点五元", False),
        ("类别", "代收金额（元）", "-50", False),
        ("名称", "缴费金额", "0.00", False),
        ("编号", "收费标准", "180元", False),
        ("项目", "费用标准", "16元", False),
    )


def citation_cases():
    for unit, price in (("每人每次", 12), ("每生每月", 18), ("每人每学期", 35),
                        ("每生每课时", 46), ("每生每套", 85)):
        fee = f"本学期按{unit}{price}元标准收取"
        source = "依据区教育局《校服收费标准》（区教发〔2025〕9号）"
        for text in (f"{fee}。{source}。", f"{fee}。\n收费依据：区教育局《校服收费标准》。",
                     f"{fee}，{source}。"):
            yield text, False
        for text in (f"{fee}。{source}，校服每生收取150元。", f"{fee}。请参阅说明，{source}。",
                     f"本学期举办合唱社团活动。{fee}。{source}。"):
            yield text, True


class Stage3bReview3Tests(K12TestCase):
    def test_review_inputs(self):
        with (SAMPLES / "stage3b_review3_inputs.jsonl").open(encoding="utf8") as stream:
            for row in map(json.loads, stream):
                if "word" in row and not HAS_DOCX:
                    continue
                path = materialize(self.tmp, row)
                for entry, expected in row["expected"].items():
                    with self.subTest(probe=row["id"], entry=entry):
                        self.assertEqual(measured(k12_check, entry, path), expected)

    def test_every_horizontal_gap_preserves_question_and_following_text(self):
        module = k12_check.load_clause_module()
        # 用 Python 自身的物理行语义枚举，两端加字才能区分尾行是否真的断开。
        horizontal = (c for c in map(chr, range(sys.maxunicode + 1))
                      if c.isspace() and len(("甲" + c + "乙").splitlines()) == 1)
        stem, following = "学生王小明属于资助对象", "班主任组织学生参加校外有偿补课"
        for gap in (*horizontal, "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"):
            with self.subTest(codepoint=f"U+{ord(gap):04X}"):
                question = stem + "！" + gap + "？"
                graph = module.analyze(question)
                self.assertEqual([(c.text, c.question, c.separator) for c in graph.clauses],
                                 [(stem, True, "！" + gap + "？")])
                self.assertEqual(measured(k12_check, "general", self.write("疑问.txt", question)),
                                 [["K12-G04", "P1", 1]])
                plain = stem + "！" + gap + following + "。"
                first, second = module.analyze(plain).clauses
                self.assertEqual((first.text, first.separator, first.question), (stem, "！", False))
                self.assertEqual(second.text.lstrip(gap), following)
                self.assertEqual(second.span.end, plain.index("。"))

    def test_fee_table_combinations(self):
        for item, heading, price, expected in table_cases():
            rows = [[item, heading], ["春季实践", price]]
            markdown = "\n".join(("| " + " | ".join(rows[0]) + " |", "|---|---|", "| " + " | ".join(rows[1]) + " |"))
            forms = [{"text": markdown}]
            if HAS_DOCX:
                forms.append({"word": [["t", rows]]})
            for form in forms:
                with self.subTest(item=item, heading=heading, price=price, kind=next(iter(form))):
                    result = measured(k12_check, "general", materialize(self.tmp, form))
                    self.assertEqual([lv for rule, lv, _ in result if rule == "K12-G06"], ["P1"] if expected else [])

    def test_citation_scope(self):
        for text, expected in citation_cases():
            with self.subTest(text=text):
                result = measured(k12_check, "general", self.write("范围.md", text))
                self.assertEqual([lv for rule, lv, _ in result if rule == "K12-G06"], ["P1"] if expected else [])

    def test_http_questions(self):
        from tests.tools.test_local_toolbox_industry import LocalToolboxK12CommentsHTTPTest as HTTP
        HTTP.setUpClass()
        self.addCleanup(HTTP.tearDownClass)
        for text in ("学生王小明属于资助对象！ ？", "学生王小明属于资助对象！\u2003？",
                     "学生王小明属于资助对象！\u2009？", "第一句！ ？ 学生王小明属于资助对象。"):
            with self.subTest(text=text):
                data = HTTP().post_raw(json.dumps({"industry": "k12_general", "stage": "义务教育", "b": text}), ("王小明",))
                self.assertTrue(data["ok"])
                self.assertIn("[P1] K12-G04 第 1 行", data["text"])
                self.assertNotIn("[P0]", data["text"])
