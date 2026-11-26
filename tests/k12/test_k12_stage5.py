"""第 5 步。姓名回显次数由 47b93e1 的 CLI 与工具箱 HTTP 实测冻结。"""
import csv
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
import re
import unittest

from tests.k12.test_k12_stage1 import SAMPLES, k12_check, read_jsonl
from tests.tools import test_local_toolbox_industry as toolbox_tests


def input_file(directory, row):
    path = directory / row.get("filename", row["id"] + ".txt")
    if "table" not in row:
        path.write_text(row["text"], encoding="utf8")
        return path, row["text"]
    rows = row["table"]
    markdown = "\n".join(k12_check.render_md_table(rows))
    if path.suffix == ".md":
        path.write_text(markdown, encoding="utf8")
    elif path.suffix == ".csv":
        with path.open("w", encoding="utf8", newline="") as stream:
            csv.writer(stream).writerows(rows)
    elif path.suffix == ".xlsx":
        from openpyxl import Workbook
        workbook = Workbook()
        for cells in rows:
            workbook.active.append(cells)
        workbook.save(path)
        workbook.close()
    elif path.suffix == ".docx":
        from docx import Document
        document = Document()
        if "paragraph" in row:
            document.add_paragraph(row["paragraph"])
        table = document.add_table(rows=len(rows), cols=len(rows[0]))
        for target, cells in zip(table.rows, rows):
            for cell, value in zip(target.cells, cells):
                cell.text = value
        document.save(path)
    return path, row.get("paragraph", "") + "\n" + markdown


def cli(engine, args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = engine.main(list(map(str, args)))
    if code != 0:
        raise AssertionError((code, err.getvalue()))
    return out.getvalue()


def outputs(engine, http, path, body, mode):
    data = http.post_raw(json.dumps({"industry": "k12_" + mode, "b": body, "stage": "义务教育"}), ())
    if mode != "comments" and "完成" not in data.get("note", ""):
        raise AssertionError(data)
    return (cli(engine, (mode, path, "--json")), cli(engine, (mode, path)),
            json.dumps(data, ensure_ascii=False))


def compliance():
    stems = ("课后服务全体在籍学生必须参加", "总分前十名的学生名单一并张贴在校门口宣传栏")
    for stem in stems:
        for form in (
            "不得要求“{}”。", "没有规定“{}”。", "假设有人写“{}”，请指出问题。",
            "{}？", "{}吗！", "{}呢？", "家长询问是否有“{}”的要求。",
            "校务会已否决“{}”的提议。", "以往的“{}”做法已经叫停。",
            "反面案例：{}。", "讨论稿写过“{}”，本校决定不采纳。", "切勿转述“{}”作为现行要求。",
            "自愿参加，可自由退出；{}是草案里已经删除的一句话。", "{}，此提议已撤回。",
        ):
            yield form.format(stem)
        for lead in ("此为引用，学校从未实行。", "本表为判断题，判断下列说法是否正确。"):
            yield lead + "\n" + stem + "。"
    yield from (
        "校园意外险自愿购买，不参加不收费。", "不可强制学生购买校园意外险。", "家长询问校园意外险是否有补贴？",
        "家委会未代收任何费用。", "每套45元为预算，由学校自行承担。", "校方已取消每册20元的代收安排。",
        "经费已列入财政预算，无需学生缴纳。", "残疾学生人数仅按年级汇总。", "受助学生名单只记录人数。",
        "留守学生关爱活动自愿参加。", "班主任不得在公告栏点名通报批评学生。", "保健室只统计焦虑症咨询次数。",
        "处分记录禁止外传。", "家庭关爱项目不公开学生身份。", "社团安排学生自愿参加，可自由退出。",
        "图书每份15元由财政拨付，学校免费发放。",
    )


# 口径第 82、89 行，tests/k12/test_k12_stage1.py:217。仅文本评语的原实名标签及其定位引用。
# 各路径只在对应样例的冻结值确实含有该姓名时允许；任何新字段或多一次重复均失败。
COMMENT_PATHS = {"entries[].label", "issues[].label", "similar_pairs[].a", "similar_pairs[].b",
                 "issues[].message"}


def comment_echo_fields(report, names):
    echoes = {}
    for key, value in report.items():
        if isinstance(value, list):
            for i, item in enumerate(value):
                for field, text in item.items():
                    if isinstance(text, str) and any(name in text for name in names):
                        echoes[f"{key}[{i}].{field}"] = text
        elif any(name in json.dumps(value, ensure_ascii=False) for name in names):
            echoes[key] = value
    return echoes


class Stage5Tests(unittest.TestCase):
    def test_name_echo_matrix(self):
        rows = read_jsonl(SAMPLES / "stage5_name_echo.jsonl")
        self.assertEqual(len(rows), 92)
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        toolbox_tests.LocalToolboxK12CommentsHTTPTest.setUpClass()
        self.addCleanup(toolbox_tests.LocalToolboxK12CommentsHTTPTest.tearDownClass)
        http = toolbox_tests.LocalToolboxK12CommentsHTTPTest()
        with TemporaryDirectory() as tmp:
            for row in rows:
                ext = Path(row.get("filename", "")).suffix
                if ext in (".docx", ".xlsx") and not find_spec("docx" if ext == ".docx" else "openpyxl"):
                    continue
                path, body = input_file(Path(tmp), row)
                for mode in ("general", "parents"):
                    with self.subTest(case=row["id"], entry=mode):
                        channels = outputs(k12_check, http, path, body, mode)
                        self.assertEqual(len(row["baseline"][mode]), len(row["names"]))
                        for name, before in zip(row["names"], row["baseline"][mode]):
                            self.assertEqual(len(before), 3)
                            counts = [output.count(name) for output in channels]
                            self.assertTrue(all(a <= b for a, b in zip(counts, before)), (name, counts, before))
                            if row.get("hidden") or name in row.get("identified", ()):
                                self.assertEqual(counts, [0, 0, 0], name)

    def test_compliant_variants(self):
        rows = list(compliance())
        self.assertGreaterEqual(len(set(rows)), 40)
        baseline = read_jsonl(SAMPLES / "stage5_compliant.jsonl")
        self.assertEqual([r["text"] for r in baseline], rows)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "规范.txt"
            for row in baseline:
                path.write_text(row["text"], encoding="utf8")
                for mode in ("general", "parents"):
                    with self.subTest(text=row["text"], entry=mode):
                        now = getattr(k12_check, "check_" + mode)(path)
                        p0 = sorted((i["id"], i["line"]) for i in now["issues"] if i["level"] == "P0")
                        self.assertEqual(p0, list(map(tuple, row[mode])))

    def test_comments_closed_fields(self):
        toolbox_tests.LocalToolboxK12CommentsHTTPTest.setUpClass()
        self.addCleanup(toolbox_tests.LocalToolboxK12CommentsHTTPTest.tearDownClass)
        with TemporaryDirectory() as tmp:
            for row in read_jsonl(SAMPLES / "stage5_comments.jsonl"):
                with self.subTest(case=row["id"]):
                    path, body = input_file(Path(tmp), row)
                    report = json.loads(cli(k12_check, ("comments", path, "--json")))
                    echoes = comment_echo_fields(report, row["names"])
                    self.assertEqual(echoes, row["baseline_fields"])
                    for key in echoes:
                        self.assertIn(re.sub(r"\[\d+\]", "[]", key), COMMENT_PATHS)
                    channels = outputs(k12_check, toolbox_tests.LocalToolboxK12CommentsHTTPTest(), path, body, "comments")
                    self.assertEqual(len(row["baseline"]), len(row["names"]))
                    for name, before in zip(row["names"], row["baseline"]):
                        self.assertEqual([channel.count(name) for channel in channels], before)
