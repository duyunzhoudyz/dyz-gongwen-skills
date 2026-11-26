"""3b 定点复核。原件归档保留 Word、工作表、畸形输入和原始字节。"""
import csv
import hashlib
import json
from pathlib import Path
import sys
import tarfile

from tests.k12.test_k12_check import HAS_DOCX, HAS_OPENPYXL, K12TestCase, REPO_ROOT, SAMPLES, k12_check
from tests.k12.test_k12_stage1 import probe_hits


def own_questions():
    stems = ("学生李文静属于资助对象", "班主任组织学生参加校外有偿补课", "学校统一购买校服", "学校不公布考试成绩是不行的")
    gaps = ("！ \t？", ".\u00a0?", "。\u3000！\u200b?", "!\u200d？", "．\u2060？", "！\ufeff \u202f?")
    for stem in stems:
        for ending in gaps:
            yield stem, ending


def own_fees():
    for index, unit in enumerate(("每生每学期", "每生每套", "每人每月", "每人每次", "每生每课时", "每人每件"), 1):
        amount = f"本学期按{unit}{index*25}元标准收取"
        title = f"区教育局《春季校服收费标准》（区教发〔2025〕{index}号）"
        for text in (f"依据{title}，{amount}。", f"{amount}，依据{title}。", f"{amount}。\n收费依据：{title}。"):
            yield "依据匹配", text, False
        for text in (f"{amount}。", f"根据{title}，管乐社{unit}收取{index*25}元。",
                     f"街舞班{unit}收取{index*25}元。\n收费依据：{title}。",
                     f"街舞班，依据{title}，{amount}。"):
            yield "依据缺失或不匹配", text, True
    headers = ("收费项目", "收费名称", "缴费项目", "代收项目", "费用名称", "缴费名称")
    amounts = ("金额", "单价", "费用", "标准", "收费金额", "收费标准")
    def table(item, amount, value):
        return f"| {item} | {amount} |\n| --- | --- |\n| 春季实践 | {value} |"
    for i, (item, amount) in enumerate(zip(headers, amounts)):
        for value in ("0元", "0.00元（免费）", "负十五元", "负零点五元", "-0.25元"):
            yield "非正金额", table(item, amount, value), False
        yield "非正金额", table(item, amount, "零元"), False
        for value in ("0.25元", "十元", "十二点零元", f"{i+3}元"):
            yield "明确收费", table(item, amount, value), True
        generic = ("项目", "预算项目", "资助项目", "品名", "退费项目", "服务项目")[i]
        yield "非收费表头", table(generic, amount, f"{i+20}元"), False
    yield "同行明确正文", "| 项目 | 金额 |\n|---|---|\n| 校服 | 每生收取校服费180元 |", True


def measured(engine, entry, path, stage="义务教育"):
    try:
        report = getattr(engine, "check_" + entry)(path, stage=stage)
    except engine.InputError:
        return "InputError"
    if entry == "comments":
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n" + engine.render_check_text(report)
        return hashlib.sha256(rendered.encode("utf8")).hexdigest()
    return probe_hits(report)


class Stage3bReview2Tests(K12TestCase):
    def test_exact_review_inputs(self):
        snapshots = json.loads((SAMPLES / "stage3b_review2_expected.json").read_text(encoding="utf8"))
        with tarfile.open(SAMPLES / "stage3b_review2_inputs.tar.xz", "r:xz") as files:
            self.assertEqual(set(files.getnames()), set(snapshots["archive"]))
            for member in files:
                path = self.tmp / Path(member.name).name
                if (path.suffix == ".docx" and not HAS_DOCX) or (path.suffix == ".xlsx" and not HAS_OPENPYXL):
                    continue
                path.write_bytes(files.extractfile(member).read())
                for entry, index in snapshots["archive"][member.name].items():
                    with self.subTest(source=member.name, entry=entry):
                        if path.stem == "A38_csv_nul_byte" and entry != "comments" and sys.version_info < (3, 11):
                            with self.assertRaises(csv.Error):
                                measured(k12_check, entry, path)
                        else:
                            result = measured(k12_check, entry, path)
                            self.assertEqual(result, snapshots["values"][index])
                            # 七类空白 × 六条规则；JZ-006 在冻结基线已有 P0，仍由完整快照核对。
                            if (path.name[:3] in {"P22", "P23", "P24", "P25", "P26", "P27", "P28"}
                                    and "_JZ006" not in path.name and ("_JZ" in path.name) == (entry == "parents")):
                                self.assertFalse([hit for hit in result if hit[1] == "P0"])
                if path.stem in {"cmp_G04_space_full", "cmp_G04_space_half", "cmp_G04_dot_space_q",
                                 "cmp_G04_tab_q", "cmp_G04_ideosp_q", "cmp_G04_zwsp_q",
                                 "cmp_G04_prefix_space_q", "G04_docx_space_q"}:
                    for stage in k12_check.STAGES:
                        with self.subTest(source=member.name, stage=stage):
                            self.assertEqual(measured(k12_check, "general", path, stage), [["K12-G04", "P1", 1]])

    def test_review_repository_inputs(self):
        snapshots = json.loads((SAMPLES / "stage3b_review2_expected.json").read_text(encoding="utf8"))
        for rel, stages in snapshots["repository"].items():
            path = REPO_ROOT / rel
            if path.suffix == ".docx" and not HAS_DOCX:
                continue
            for stage, entries in stages.items():
                for entry, index in entries.items():
                    with self.subTest(file=rel, stage=stage, entry=entry):
                        self.assertEqual(measured(k12_check, entry, path, stage), snapshots["values"][index])

    def test_question_and_next_sentence_offsets(self):
        module = k12_check.load_clause_module()
        for stem, end in own_questions():
            next_sentence = "学生王小明属于资助对象"
            text = stem + end + " \t" + next_sentence + "。"
            with self.subTest(text=text):
                graph = module.analyze(text)
                self.assertEqual([(c.text, c.question, c.separator) for c in graph.clauses],
                                 [(stem, True, end), (next_sentence, False, "。")])
                self.assertEqual(graph.clauses[1].span.start, text.index(next_sentence))
                path = self.write("疑问.md", stem + end)
                for entry in ("general", "parents"):
                    actual = measured(k12_check, entry, path)
                    # “学校统一购买校服”在冻结 parents 入口已有 JZ-006 P0。
                    allowed = ["JZ-006"] if stem == "学校统一购买校服" and entry == "parents" else []
                    self.assertEqual([r for r, lv, n in actual if lv == "P0"], allowed)
        for gap in (" ", "\t", "\u3000", "\u00a0"):
            graph = module.analyze("学期结束！" + gap + "下学期见。")
            self.assertEqual([(c.text, c.separator, c.question) for c in graph.clauses],
                             [("学期结束", "！", False), ("下学期见", "。", False)])

    def test_bare_fee_and_explicit_fee_table(self):
        for label, text, expected in own_fees():
            with self.subTest(label=label, text=text):
                report = measured(k12_check, "general", self.write("通知.md", text))
                self.assertEqual([lv for r, lv, n in report if r == "K12-G06"], ["P1"] if expected else [])

    def test_http_review_inputs(self):
        from tests.tools.test_local_toolbox_industry import LocalToolboxK12CommentsHTTPTest as HTTP
        HTTP.setUpClass()
        self.addCleanup(HTTP.tearDownClass)
        snapshots = json.loads((SAMPLES / "stage3b_review2_expected.json").read_text(encoding="utf8"))
        for key, industry, value, repetitions, tail, expected in snapshots["http"]:
            with self.subTest(key=key):
                body = json.dumps({"industry": industry, "b": value * repetitions + tail, "stage": "义务教育"})
                actual = HTTP().post_raw(body, ())
                if repetitions > 1:
                    actual["text"] = hashlib.sha256(actual["text"].encode("utf8")).hexdigest()
                self.assertEqual(actual, expected)
