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

from tests.k12.test_k12_stage1 import REPO_ROOT, SAMPLES, k12_check, read_jsonl, stage4_corpus
from tests.tools import test_local_toolbox_industry as toolbox_tests


def input_file(directory, row):
    path = directory / row.get("filename", row["id"] + ".txt")
    if row.get("invalid"):
        path.write_bytes(b"\xff\xfe\x00\x80invalid" if path.suffix == ".txt" else b"not a zip file")
        return path, None
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
        for paragraph in row.get("paragraph", "").splitlines():
            document.add_paragraph(paragraph)
        table = document.add_table(rows=len(rows), cols=len(rows[0]))
        for target, cells in zip(table.rows, rows):
            for cell, value in zip(target.cells, cells):
                cell.text = value
        document.save(path)
    return path, (row["paragraph"] + "\n" if "paragraph" in row else "") + markdown


def cli(engine, args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = engine.main(list(map(str, args)))
    if code != 0:
        raise AssertionError((code, err.getvalue()))
    return out.getvalue()


def outputs(engine, http, path, body, mode, facts=()):
    data = http.post_raw(json.dumps({"industry": "k12_" + mode, "b": body, "stage": "义务教育"}), ())
    if mode != "comments" and "完成" not in data.get("note", ""):
        raise AssertionError(data)
    return (cli(engine, (mode, path, "--json", *facts)), cli(engine, (mode, path, *facts)),
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


# 封闭例外清单：每项须与 47b93e1 的字段、内容和次数完全一致，不得放成通配。
# 依据：口径文档第 82、89 行、tests/k12/test_k12_stage1.py:217（无编号评语逐字兼容硬规则）。
COMMENT_PATHS = {
    "entries[].label": "基线即如此，教师定位评语（含表头“学生”保留原名）；逐字兼容硬规则（47b93e1、口径第 82、89 行、test_k12_stage1.py:217）",
    "issues[].label": "基线即如此，教师定位告警或未配对事实记录；逐字兼容硬规则（47b93e1、口径第 82、89 行、test_k12_stage1.py:217）",
    "similar_pairs[].a": "基线即如此，相似评语的第一个定位标签；逐字兼容硬规则（47b93e1、口径第 82、89 行、test_k12_stage1.py:217）",
    "similar_pairs[].b": "基线即如此，相似评语的第二个定位标签；逐字兼容硬规则（47b93e1、口径第 82、89 行、test_k12_stage1.py:217）",
    "issues[PY-007].message": "基线即如此，相似度提示引用两个定位标签；逐字兼容硬规则（47b93e1、口径第 82、89 行、test_k12_stage1.py:217）",
    "issues[PY-008].message": "基线即如此，共用套句提示列举学生定位标签；逐字兼容硬规则（47b93e1、口径第 82、89 行、test_k12_stage1.py:217）",
    "issues[PY-015].message": "基线即如此，事实表对账提示引用未配对定位标签；逐字兼容硬规则（47b93e1、口径第 82、89 行、test_k12_stage1.py:217）",
    "issues[PY-017].message": "基线即如此，仅限纯文本无表格 --facts 对账提示引用原引号/书名号或奖项名；逐字兼容硬规则（47b93e1、口径第 82、89 行、test_k12_stage1.py:217）",
}


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
        review = read_jsonl(SAMPLES / "stage5_review_echo.jsonl")
        self.assertEqual(len(review), 96)
        rows += review
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
                        if row.get("invalid"):
                            errors = []
                            for extra in (["--json"], []):
                                err = io.StringIO()
                                with redirect_stderr(err):
                                    self.assertEqual(k12_check.main([mode, str(path), *extra]), 2)
                                errors.append(err.getvalue())
                            for name, before in zip(row["names"], row["baseline"][mode]):
                                self.assertEqual([s.count(name) for s in errors], before)
                            continue
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

    def test_review_p0(self):
        rows = read_jsonl(SAMPLES / "stage5_review_p0.jsonl")
        self.assertEqual(len(rows), 70)  # 67 条合规变体与 3 条违规对照
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "通知.txt"
            for row in rows:
                path.write_text(row["text"], encoding="utf8")
                for mode, stages in row["baseline"].items():
                    for stage, expected in stages.items():
                        report = getattr(k12_check, "check_" + mode)(path, stage)
                        actual = sorted({(i["id"], i["line"]) for i in report["issues"] if i["level"] == "P0"})
                        self.assertEqual(actual, list(map(tuple, expected)), (row["id"], mode, stage))

    def test_catalog_on_corpus_and_regression(self):
        catalog = json.loads(cli(k12_check, ("--list-rules", "--json")))["rules"]
        self.assertEqual(len(catalog), 38)
        declared = {(r["id"], mode, stage, level) for r in catalog for mode, stages in r["stage_levels"].items()
                    for stage, levels in stages.items() for level in levels}

        def check(path, mode, stage, facts=None):
            options = {"facts_path": facts} if facts else {}
            report = getattr(k12_check, "check_" + mode)(path, stage=stage, **options)
            for item in report["issues"]:
                self.assertIn((item["id"], mode, stage, item["level"]), declared, (path.name, item))

        corpus = REPO_ROOT / "tests/industry_corpus/k12"
        cases = json.loads((corpus / "cases.json").read_text(encoding="utf8"))["docs"]
        facts = {r["file"]: corpus / r["facts"] for r in cases if "facts" in r}
        for record in stage4_corpus():
            path = REPO_ROOT / record["file"]
            for mode, stages in record["runs"].items():
                for stage in stages:
                    if mode == "comments_facts":
                        check(path, "comments", stage, facts[path.name])
                    else:
                        check(path, mode, stage)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "回归.txt"
            for source in sorted((SAMPLES / "clause_regression").glob("*.jsonl")):
                for row in read_jsonl(source):
                    path.write_text(row["text"], encoding="utf8")
                    for mode in ("general", "parents"):
                        for stage in k12_check.STAGES:
                            check(path, mode, stage)

    def test_review_overmask(self):
        rows = read_jsonl(SAMPLES / "stage5_review_overmask.jsonl")
        self.assertEqual(len(rows), 42)
        with TemporaryDirectory() as tmp:
            for row in rows:
                case = row["id"].split("_")[0]
                paths = [input_file(Path(tmp), row)[0]]
                if "table" in row and find_spec("openpyxl"):
                    paths.append(input_file(Path(tmp), dict(row, filename="表.xlsx"))[0])
                for path in paths:
                    for mode in ("general", "parents"):
                        report = getattr(k12_check, "check_" + mode)(path)
                        for issue in report["issues"]:
                            # 误登已从识别层消除，整份报告统一遮蔽下静态建议文字也不再被污染。
                            for key in ("message", "basis", "suggestion"):
                                self.assertNotIn("〔姓名", issue[key], (row["id"], mode, key))
                            # 旧版 Markdown 人员表、实际带姓名的同形词对照仍可产生占位。
                            if case not in {"OM17", "OM18", "OM19", "OM20", "OM21", "OM26", "OM27",
                                            "OM28", "OM29", "OM30"}:
                                self.assertNotIn("〔姓名", issue["excerpt"], (row["id"], mode, issue))
                        if row["id"] == "OM_X1_xuesheng_he_jiazhang_jz003" and mode == "parents":
                            jz003 = next(i for i in report["issues"] if i["id"] == "JZ-003")
                            self.assertIn("学生和家长", jz003["excerpt"])
                            self.assertEqual(jz003["suggestion"], "删去；考试结果以适当方式单独告知学生和家长")

    def test_readable_excerpts(self):
        corpus = REPO_ROOT / "tests/industry_corpus/k12"
        for doc, rule, line, terms in [
                ("V_k06", "K12-G04", 7, ("留守学生", "〔姓名")),
                ("V_k06", "K12-G04", 8, ("〔姓名", "同学患有孤独症")),
                ("V_k05", "K12-G05", 16, ("必须购买校园意外险",)),
                ("V_k05", "K12-G06", 16, ("每生100元",)),
                ("V_k05", "K12-G06", 17, ("每套45元",))]:
            issues = k12_check.check_general(next(corpus.glob(doc + "_*.txt")))["issues"]
            shown = next(i["excerpt"] for i in issues if (i["id"], i["line"]) == (rule, line))
            for term in terms:
                self.assertIn(term, shown)

    def test_review_r1_structural_guards(self):
        """结构边界回归：不把年级/职务/歧义二字词和带非学生限定的表头误当学生姓名，且覆盖常见动词与右界。"""
        no_mask = [
            "学校要求高一同学统一购买校服180元。",
            "学校通知高二同学统一购买校服180元。",
            "学校要求班长同学统一购买校服180元。",
            "学校要求平安同学统一购买校服180元。",
            "学校要求向阳同学统一购买校服180元。",
            "明德同学参加活动，明德中学公布期末考试成绩排名。",
            "阳光同学参加活动，阳光小学公布期末考试成绩排名。",
            "学生和平由校方维护，学校公布期末考试成绩排名。",
        ]
        should_mask = [
            ("请家长批改王小明同学的数学作业并签字。", "王小明", "parents"),
            ("请家长批改李华同学的数学作业并签字。", "李华", "parents"),
            ("六（3）班陈嘉树同学连续三周缺交数学作业，请家长检查陈嘉树的作业并签字。", "陈嘉树", "parents"),
            ("学生王小明昨天交了校服费180元。学校在大会公布王小明的考试成绩。", "王小明", "general"),
            ('学校要求学生"唐子墨"参加校外有偿补课。年级大会公布唐子墨的考试成绩。', "唐子墨", "general"),
        ]
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "结构边界.txt"
            for text in no_mask:
                p.write_text(text, encoding="utf8")
                for mode in ("general", "parents"):
                    report = getattr(k12_check, "check_" + mode)(p)
                    for issue in report["issues"]:
                        for key in ("excerpt", "message", "basis", "suggestion"):
                            self.assertNotIn("〔姓名", issue[key], (text, mode, key, issue))
            for text, name, mode in should_mask:
                p.write_text(text, encoding="utf8")
                report = getattr(k12_check, "check_" + mode)(p)
                self.assertTrue(report["issues"], (text, mode))
                self.assertNotIn(name, json.dumps(report, ensure_ascii=False), (text, mode, report))
            # 带非学生括注的“姓名”表头不进学生姓名表
            csv_non_student = Path(tmp) / "教师表.csv"
            with csv_non_student.open("w", encoding="utf8", newline="") as stream:
                csv.writer(stream).writerows([
                    ["姓名（教师）", "姓名（家长）", "备注"],
                    ["王建国", "陈大勇", "学校公布王建国班级的期末考试成绩排名"],
                ])
            for mode in ("general", "parents"):
                report = getattr(k12_check, "check_" + mode)(csv_non_student)
                self.assertNotIn("〔姓名", json.dumps(report, ensure_ascii=False))
            # CSV 学生姓名正式编号连续，不被 table_only 子串打断
            csv_student = Path(tmp) / "学生表.csv"
            with csv_student.open("w", encoding="utf8", newline="") as stream:
                csv.writer(stream).writerows([
                    ["学生姓名", "备注"],
                    ["林晓峰", "学校公布林晓峰的期末考试成绩排名"],
                    ["周语桐", "学校公布周语桐的期末考试成绩排名"],
                ])
            report = k12_check.check_general(csv_student)
            excerpts = [i["excerpt"] for i in report["issues"] if i["id"] == "K12-G01"]
            self.assertTrue(any("〔姓名1〕" in e for e in excerpts), excerpts)
            self.assertTrue(any("〔姓名2〕" in e for e in excerpts), excerpts)

    def test_comments_closed_fields(self):
        toolbox_tests.LocalToolboxK12CommentsHTTPTest.setUpClass()
        self.addCleanup(toolbox_tests.LocalToolboxK12CommentsHTTPTest.tearDownClass)
        http = toolbox_tests.LocalToolboxK12CommentsHTTPTest()
        with TemporaryDirectory() as tmp:
            rows = read_jsonl(SAMPLES / "stage5_comments.jsonl") + read_jsonl(SAMPLES / "stage5_review_comments.jsonl")
            for row in rows:
                with self.subTest(case=row["id"]):
                    if Path(row.get("filename", "")).suffix in (".xlsx", ".docx") and not find_spec(
                            "openpyxl" if row["filename"].endswith(".xlsx") else "docx"):
                        continue
                    path, body = input_file(Path(tmp), row)
                    facts = ()
                    if "facts" in row:
                        ref = Path(tmp) / "事实.md"
                        ref.write_text(row["facts"], encoding="utf8")
                        facts = ("--facts", ref)
                    report = json.loads(cli(k12_check, ("comments", path, "--json", *facts)))
                    echoes = comment_echo_fields(report, row["names"])
                    self.assertEqual(echoes, row["baseline_fields"])
                    for key in comment_echo_fields(report, row.get("identified", row["names"])):
                        message = re.fullmatch(r"issues\[(\d+)\]\.message", key)
                        if message:
                            rule = report["issues"][int(message[1])]["id"]
                            self.assertIn(f"issues[{rule}].message", COMMENT_PATHS)
                            if rule == "PY-017":
                                self.assertTrue(facts and not k12_check._comment_tables(k12_check.load_document(path)))
                        else:
                            self.assertIn(re.sub(r"\[\d+\]", "[]", key), COMMENT_PATHS)
                    channels = outputs(k12_check, http, path, body, "comments", facts)
                    self.assertEqual(len(row["baseline"]), len(row["names"]))
                    for name, before in zip(row["names"], row["baseline"]):
                        self.assertEqual([channel.count(name) for channel in channels], before)
