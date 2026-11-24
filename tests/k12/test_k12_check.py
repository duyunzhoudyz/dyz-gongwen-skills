# -*- coding: utf-8 -*-
"""skills/gongwen-k12/scripts/k12_check.py 的单元测试。

运行：python -m unittest discover -s tests/k12 -t .

samples/ 下的标本：
    comments_must_fail.txt、parents_must_fail.txt  必错标本：每类问题都要报出；
    parents_must_fail_lines.txt                    必错标本：每行一句不写主语、语序变化的违规写法，逐行都要报出；
    parents_must_fail_speech.txt                   必错标本：送审的家长会讲话稿（同评测第12条材料）；
    comments_must_pass.txt、parents_must_pass.txt  必过标本：不得报出任何问题；
    comments_facts.md                              必过评语对应的脱敏事实表；
    students_lines.txt                             含姓名、手机号、学号的虚构事实表，用于脱敏测试。
"""
from __future__ import annotations

import csv
import io
import inspect
import json
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "gongwen-k12" / "scripts"
SAMPLES = Path(__file__).resolve().parent / "samples"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import k12_check  # noqa: E402

try:
    import openpyxl  # type: ignore  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    import docx  # type: ignore  # noqa: F401
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

NAMES = ("王小明", "李华", "欧阳晓晓", "小明", "晓晓")

# eea12327e4533be39979b66dbc0f0d3630131563 已有的规范文档成绩类 P0。
# 用原文片段标记，文档增删其他行不会使此基线失效。
REFERENCE_RANK_BASELINE = {
    "zhongxiaoxue.md": ("考试结果不排名、不公布", "额外检查：学生隐私和成绩排名"),
    "quick-cards.md": ("写考试排名（红线二）", "公布成绩排名（红线二）", "不含成绩）发到家长群", "不写分数排名"),
    "redlines.md": ("家庭住址；成绩和排名", "家长信不写学生和班级的考试排名"),
    "review-addon.md": ("高中、中职材料：考试排名",),
    "banzhuren-jihua-zongjie.md": ("习惯和方法的变化，不写分数和排名", "不写考试排名和分数", "用排名和分数说成效"),
    "jiazhanghui-jianghua.md": ("只发事项，不发成绩", "不写考试分数、均分、名次"),
    "xueqi-jihua-zongjie.md": ("不写学生、班级的考试排名", "写考试排名，或拿班级", "数学均分比邻校高出6分"),
    "xuesheng-pingyu.md": ("不写：考试分数和排名", "写分数和排名。", "这次单元测验语文得了96分"),
}


class K12TestCase(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="k12_check_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name: str, text: str) -> Path:
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return path

    def copy(self, name: str) -> Path:
        target = self.tmp / name
        shutil.copyfile(SAMPLES / name, target)
        return target

    def run_main(self, *args: str):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = k12_check.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def run_json(self, *args: str) -> dict:
        code, out, err = self.run_main(*args, "--json")
        self.assertIn(code, (0, 1), err)
        return json.loads(out)

    @staticmethod
    def ids(report: dict, level: str = "") -> list:
        return [i["id"] for i in report["issues"] if not level or i["level"] == level]


class CommentsTest(K12TestCase):

    def test_must_pass_sample_has_no_issue(self):
        report = self.run_json("comments", str(SAMPLES / "comments_must_pass.txt"),
                               "--facts", str(SAMPLES / "comments_facts.md"))
        self.assertEqual(report["entry_count"], 8, "【起草说明】之后的内容不应计入")
        self.assertEqual(report["issues"], [], report["issues"])

    def test_must_fail_sample_reports_each_problem(self):
        report = self.run_json("comments", str(SAMPLES / "comments_must_fail.txt"))
        found = set(self.ids(report))
        for rule in ("PY-001", "PY-002", "PY-003", "PY-004", "PY-005", "PY-006",
                     "PY-007", "PY-009", "PY-010", "PY-011", "PY-014"):
            self.assertIn(rule, found, rule)
        by_label = {}
        for item in report["issues"]:
            by_label.setdefault(item["label"], set()).add(item["id"])
        self.assertIn("PY-003", by_label["S03"])
        self.assertIn("PY-006", by_label["S05"])
        self.assertTrue(any(p["a"] == "S01" and p["b"] == "S02" for p in report["similar_pairs"]))

    def test_exam_rank_is_p0_and_competition_rank_is_not_reported(self):
        path = self.write("评语.txt",
                          "S01：你在校运会跳远比赛中获得第一名，赛前每天练习起跳，老师看在眼里。希望你把这股劲用到英语朗读上。\n"
                          "S02：你期中考试语文考了年级前三名，老师为你高兴。希望你下学期多读整本书，写作会更有底气。\n")
        report = self.run_json("comments", str(path), "--min-chars", "0")
        s01 = [i for i in report["issues"] if i["label"] == "S01"]
        s02 = [i for i in report["issues"] if i["label"] == "S02" and i["id"] == "PY-003"]
        self.assertEqual(s01, [])
        self.assertEqual(s02[0]["level"], "P0")

    def test_high_school_stage_lowers_rank_level(self):
        path = self.write("评语.txt", "S01：你期中考试数学考了全班第一名，课上常常帮同学讲题。希望你把错题本坚持下去，物理的计算会更稳。\n")
        report = self.run_json("comments", str(path), "--stage", "高中")
        rank = [i for i in report["issues"] if i["id"] == "PY-003"]
        self.assertEqual(rank[0]["level"], "P1")

    def test_strict_returns_1_on_p0(self):
        code, _out, _err = self.run_main("comments", str(SAMPLES / "comments_must_fail.txt"), "--strict")
        self.assertEqual(code, 1)
        code, _out, _err = self.run_main("comments", str(SAMPLES / "comments_must_pass.txt"), "--strict")
        self.assertEqual(code, 0)

    def test_marker_entry_is_p2_and_counted(self):
        path = self.write("评语.txt",
                          "S01：【待补：该生本学期的两三件具体表现】\n"
                          "S02：你每天早上第一个到教室开窗通风，还主动给班里的绿萝浇水。希望你上课多举手，把想法说出来。\n")
        report = self.run_json("comments", str(path))
        self.assertIn("PY-013", self.ids(report, "P2"))
        self.assertEqual(report["summary"]["markers"]["待补"], 1)
        self.assertEqual(report["summary"]["P0"], 0)

    def test_marker_text_does_not_trigger_person_check(self):
        path = self.write("评语.txt",
                          "S01：美术课上你画的《家乡的桥》贴在了走廊展板上，很多同学停下来细看。"
                          "【待补：该生本学期另一件具体表现】做数学计算时，试着每算完一题就换一种方法验一遍。\n")
        report = self.run_json("comments", str(path), "--min-chars", "0")
        self.assertNotIn("PY-010", self.ids(report))

    def test_facts_reconciliation(self):
        facts = self.write("事实表.md", "| 编号 | 具体表现 |\n|---|---|\n| S01 | 担任两次升旗手；竹编笔筒进展柜 |\n"
                                       "| S02 | 合唱领唱 |\n| S03 | 书写进步 |\n")
        comments = self.write("评语.txt",
                              "S01：这学期你3次担任升旗手，站姿挺拔，劳动课做的竹编笔筒被放进了学校展柜。希望你上课再专注一些。\n"
                              "S02：合唱比赛你担任领唱，声音清亮，还在《童心向党》演出中独唱。希望你按时交作业，做事更有计划。\n"
                              "S04：你这学期进步很大，老师为你高兴，希望你继续保持，在新学期里取得更好的成绩。\n")
        report = self.run_json("comments", str(comments), "--facts", str(facts))
        messages = " ".join(i["message"] for i in report["issues"])
        self.assertIn("“3”在该生的事实表中找不到", messages)        # 事实表写的是“两次”
        self.assertIn("童心向党", messages)
        self.assertIn("事实表中有 S03，评语中没有", messages)
        self.assertIn("事实表中没有 S04", messages)

    def test_chinese_numerals_in_facts_match_digits(self):
        facts = self.write("事实表.md", "| 编号 | 具体表现 |\n|---|---|\n| S01 | 读完十二本课外书 |\n")
        comments = self.write("评语.txt", "S01：这学期你读完了12本课外书，读书笔记写得认真，常给同学推荐好书。希望你把读到的好词好句用进作文。\n")
        report = self.run_json("comments", str(comments), "--facts", str(facts))
        self.assertNotIn("PY-016", self.ids(report))

    def test_table_input_with_comment_column(self):
        path = self.write("评语.md", "| 编号 | 评语 |\n|---|---|\n"
                                     "| S01 | 你是班上的后进生，要多努力，下学期要按时完成作业，把字写工整。 |\n"
                                     "| S02 | 你在科技节上做的水火箭飞得最远，讲解时条理清楚。希望你写实验记录时把数据记全。 |\n")
        report = self.run_json("comments", str(path))
        self.assertEqual(report["entry_count"], 2)
        self.assertIn("PY-002", self.ids(report))

    def test_label_on_its_own_line(self):
        path = self.write("评语.txt", "期末评语\n\nS01\n你每天坚持跳绳一千下，体育课上的进步大家都看到了。希望你把这份坚持用到背诵古诗上。\n\n"
                                      "S02\n你的手抄报《节约用水》被贴在了走廊展板上，配色很用心。希望你做题时把草稿写整齐。\n")
        report = self.run_json("comments", str(path), "--min-chars", "30")
        self.assertEqual([e["label"] for e in report["entries"]], ["S01", "S02"])
        self.assertEqual(report["issues"], [])

    def test_labour_words_and_negations_are_not_insults(self):
        path = self.write("评语.txt",
                          "S01：你在垃圾分类活动中当了宣传员，还把废物利用的点子讲给大家听。你常说“笨鸟先飞”，每天提前到校读书。\n"
                          "S02：你一点也不懒，大扫除时抢着搬笨重的桌子，从不偷懒。希望你上课多举手。\n"
                          "S03：你太懒了，是个笨孩子，每天都把垃圾丢在座位旁。\n")
        report = self.run_json("comments", str(path), "--min-chars", "0")
        by_label = {}
        for item in report["issues"]:
            by_label.setdefault(item["label"], set()).add(item["id"])
        self.assertFalse({"PY-001", "PY-002"} & by_label.get("S01", set()), by_label.get("S01"))
        self.assertFalse({"PY-001", "PY-002"} & by_label.get("S02", set()), by_label.get("S02"))
        self.assertIn("PY-001", by_label["S03"])            # “笨孩子”仍报贬损
        self.assertIn("PY-002", by_label["S03"])            # “太懒了”仍报标签化

    def test_shared_sentence_is_reported(self):
        tail = "希望你在新的学期里继续努力争取更大进步"
        body = ["你给班级图书角捐了五本书，还做了借阅登记表。",
                "你在拔河比赛中当第一棒，喊口号最响。",
                "你帮生病的同学整理了一周的笔记。",
                "你把教室后面的植物角照顾得很好。"]
        text = "\n".join(f"S0{i}：{b}{tail}。" for i, b in enumerate(body, start=1))
        report = self.run_json("comments", str(self.write("评语.txt", text)), "--min-chars", "0")
        self.assertIn("PY-008", self.ids(report))

    def test_no_entries_is_input_error(self):
        code, _out, err = self.run_main("comments", str(self.write("空.txt", "\n\n")))
        self.assertEqual(code, 2)
        self.assertIn("没有识别到评语", err)

    def test_excerpt_masks_id_number(self):
        report = self.run_json("comments", str(SAMPLES / "comments_must_fail.txt"))
        dumped = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("110101201301010011", dumped)


class ParentsTest(K12TestCase):

    def test_must_pass_sample_has_no_issue(self):
        report = self.run_json("parents", str(SAMPLES / "parents_must_pass.txt"))
        self.assertEqual(report["issues"], [], report["issues"])

    def test_must_fail_sample_reports_each_problem(self):
        report = self.run_json("parents", str(SAMPLES / "parents_must_fail.txt"))
        found = set(self.ids(report))
        for rule in ("JZ-001", "JZ-002", "JZ-003", "JZ-004", "JZ-005", "JZ-006", "JZ-007",
                     "JZ-008", "JZ-009", "JZ-010", "JZ-011", "JZ-012", "JZ-013"):
            self.assertIn(rule, found, rule)
        p0 = set(self.ids(report, "P0"))
        self.assertTrue({"JZ-001", "JZ-003", "JZ-006", "JZ-008", "JZ-010"} <= p0, p0)

    def test_each_line_of_unlabelled_violations_is_reported(self):
        report = self.run_json("parents", str(SAMPLES / "parents_must_fail_lines.txt"))
        by_line = {}
        for item in report["issues"]:
            by_line.setdefault(item["line"], set()).add(item["id"])
        expected = {1: "JZ-001", 2: "JZ-003", 3: "JZ-014", 4: "JZ-003", 5: "JZ-002"}
        for line, rule in expected.items():
            self.assertIn(rule, by_line.get(line, set()), (line, rule, by_line))
        self.assertIn("JZ-012", by_line[3])                 # 点名并写“拖了全班后腿”
        levels = {(i["line"], i["id"]): i["level"] for i in report["issues"]}
        self.assertEqual(levels[(1, "JZ-001")], "P0")
        self.assertEqual(levels[(2, "JZ-003")], "P0")
        self.assertEqual(levels[(3, "JZ-014")], "P0")

    def test_speech_for_review_reports_every_problem(self):
        report = self.run_json("parents", str(SAMPLES / "parents_must_fail_speech.txt"))
        found = set(self.ids(report))
        for rule in ("JZ-001", "JZ-002", "JZ-003", "JZ-005", "JZ-006", "JZ-007", "JZ-011", "JZ-012",
                     "JZ-013", "JZ-014"):
            self.assertIn(rule, found, rule)
        self.assertTrue({"JZ-001", "JZ-003", "JZ-006", "JZ-014"} <= set(self.ids(report, "P0")))

    def test_rank_words_in_dates_and_counts_are_not_reported(self):
        path = self.write("信.txt", "七年级第一学期的家长开放日另行通知。年级第一次家长会安排在开学第三周。"
                                    "全区第一批试点学校名单已公布。学期倒数第二周安排期末复习。")
        report = self.run_json("parents", str(path))
        self.assertNotIn("JZ-003", self.ids(report))

    def test_negated_statements_are_not_reported(self):
        path = self.write("信.txt", "学校不要求家长批改作业。考试结果不排名、不公布。课后服务不讲新课。"
                                    "学校不统一订购教辅资料。教师不得推荐学生参加校外培训班。"
                                    "期末成绩不会发到家长群，由班主任单独告知。不需要家长检查作业并签字。")
        self.assertEqual(self.run_json("parents", str(path))["issues"], [])

    def test_teacher_grading_is_not_reported(self):
        path = self.write("信.txt", "老师会当天批改作业，请家长督促孩子按时休息。请家长在回执上签字后交回。")
        self.assertEqual(self.run_json("parents", str(path))["issues"], [])

    def test_competition_rank_and_group_mentions_are_not_reported(self):
        path = self.write("讲话.txt", "本学期我班在校运动会上获得年级第二名。个别同学课间追跑，有过两次打架，会后我会单独沟通。"
                                      "请同学们不要打架。")
        report = self.run_json("parents", str(path))
        self.assertNotIn("JZ-003", self.ids(report))
        self.assertNotIn("JZ-012", self.ids(report))

    def test_high_school_stage(self):
        path = self.write("信.txt", "请家长每天检查孩子作业并签字。高一年级不布置书面作业的说法不适用。")
        report = self.run_json("parents", str(path), "--stage", "高中")
        levels = {i["id"]: i["level"] for i in report["issues"]}
        self.assertEqual(levels.get("JZ-001"), "P1")
        self.assertNotIn("JZ-004", levels)

    def test_fee_with_basis_in_paragraph(self):
        path = self.write("信.txt", "根据某区教育局《关于课后服务收费的通知》（某教〔2026〕5号），课后服务每生每月收费150元，家长自愿申请。")
        self.assertNotIn("JZ-007", self.ids(self.run_json("parents", str(path))))
        path2 = self.write("信2.txt", "请于周五前缴纳资料费每人40元，资料为《期末冲刺》。")
        self.assertIn("JZ-007", self.ids(self.run_json("parents", str(path2))))

    def test_text_after_draft_note_is_ignored(self):
        report = self.run_json("parents", str(SAMPLES / "parents_must_pass.txt"))
        self.assertNotIn("JZ-001", self.ids(report))

    @unittest.skipUnless(HAS_DOCX, "未安装 python-docx")
    def test_docx_input(self):
        import docx  # type: ignore
        d = docx.Document()
        d.add_paragraph("各位家长：")
        d.add_paragraph("期末考试结束后，学校将在家长群公布成绩排名。")
        path = self.tmp / "信.docx"
        d.save(str(path))
        self.assertIn("JZ-003", self.ids(self.run_json("parents", str(path))))


class MaskTest(K12TestCase):

    def assert_no_names(self, text: str) -> None:
        for name in NAMES:
            self.assertNotIn(name, text, name)

    def test_mask_lines_and_unmask_roundtrip(self):
        src = self.copy("students_lines.txt")
        code, out, err = self.run_main("mask", str(src))
        self.assertEqual(code, 0, err)
        self.assert_no_names(out)                                   # 屏幕输出不含姓名
        masked = (self.tmp / "students_lines-脱敏.txt").read_text(encoding="utf-8")
        self.assert_no_names(masked)
        self.assertIn("S01：", masked)
        self.assertIn("S01和S03是同桌", masked)                    # 名字（小明、晓晓）也替换
        self.assertNotIn("13812345678", masked)
        self.assertNotIn("20260102", masked)
        self.assertIn("1500米", masked)                            # 普通数字不动
        self.assertIn("S03", out)                                   # 敏感信息提示只给编号
        with (self.tmp / "students_lines-对照表.csv").open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0], ["编号", "姓名"])
        self.assertEqual(rows[1], ["S01", "王小明"])
        comments = self.write("评语.txt", "S01：你认真负责。\nS03：你书写进步很大。\n")
        code, out, err = self.run_main("unmask", str(comments), str(self.tmp / "students_lines-对照表.csv"))
        self.assertEqual(code, 0, err)
        self.assert_no_names(out)
        restored = (self.tmp / "评语-姓名版.txt").read_text(encoding="utf-8")
        self.assertIn("王小明：你认真负责。", restored)
        self.assertIn("欧阳晓晓：你书写进步很大。", restored)

    def test_teacher_header_lines_are_not_students(self):
        src = self.copy("students_lines.txt")                       # 开头两行是“班主任：李老师”等表头
        code, out, err = self.run_main("mask", str(src), "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["students"], 3)
        masked = (self.tmp / "students_lines-脱敏.txt").read_text(encoding="utf-8")
        self.assertIn("班主任：李老师", masked)
        self.assertIn("任课教师：数学王老师、英语张老师", masked)

    def test_drop_sensitive_replaces_family_and_health_sentences(self):
        src = self.write("情况.txt", "1. 陈雨桐：科学课记录豌豆苗高度。需改进：默写错得多。父母离异，跟奶奶生活，心理老师说有焦虑情绪。\n"
                                     "2. 刘子涵：合唱比赛领唱。受过警告处分。\n")
        code, out, err = self.run_main("mask", str(src), "--drop-sensitive")
        self.assertEqual(code, 0, err)
        masked = (self.tmp / "情况-脱敏.txt").read_text(encoding="utf-8")
        for secret in ("离异", "奶奶", "焦虑", "警告", "陈雨桐", "刘子涵"):
            self.assertNotIn(secret, masked)
        self.assertIn("【已略去：家庭、健康信息】", masked)
        self.assertIn("科学课记录豌豆苗高度", masked)                 # 其他句子保留
        self.assertIn("已略去：家庭信息 1 处、健康信息 1 处、处分信息 1 处", out)
        self.assertNotIn("陈雨桐", out)

    def test_without_drop_sensitive_hint_names_the_option(self):
        src = self.write("情况.txt", "1. 陈雨桐：科学课记录豌豆苗高度。父母离异。\n2. 刘子涵：合唱比赛领唱。\n")
        code, out, err = self.run_main("mask", str(src))
        self.assertEqual(code, 0, err)
        self.assertIn("--drop-sensitive", out)
        self.assertIn("离异", (self.tmp / "情况-脱敏.txt").read_text(encoding="utf-8"))  # 不加选项时保留，只提示

    def test_given_name_next_to_other_words_is_replaced_with_hint(self):
        src = self.write("情况.txt", "1. 张明月：明月当空的夜晚写了一首小诗。\n2. 刘子涵：合唱比赛领唱。\n")
        code, out, err = self.run_main("mask", str(src))
        self.assertEqual(code, 0, err)
        masked = (self.tmp / "情况-脱敏.txt").read_text(encoding="utf-8")
        self.assertNotIn("明月", masked)                             # 隐私优先，照常替换
        self.assertIn("明月当空", out)                               # 提示人工核对

    def test_mask_does_not_overwrite(self):
        src = self.copy("students_lines.txt")
        self.run_main("mask", str(src))
        self.run_main("mask", str(src))
        self.assertTrue((self.tmp / "students_lines-脱敏-v2.txt").exists())
        self.assertTrue((self.tmp / "students_lines-对照表-v2.csv").exists())

    def test_mask_csv_table_drops_sensitive_columns(self):
        src = self.write("名单.csv", "姓名,学号,具体表现,家长电话\n张小雨,20260301,运动会跳绳第一名；张小雨帮同学补课,13900001111\n"
                                     "刘洋,20260302,作文进步,13900002222\n")
        code, out, err = self.run_main("mask", str(src))
        self.assertEqual(code, 0, err)
        masked = (self.tmp / "名单-脱敏.md").read_text(encoding="utf-8")
        for secret in ("张小雨", "刘洋", "小雨", "20260301", "13900001111"):
            self.assertNotIn(secret, masked)
        self.assertIn("| 编号 |", masked)
        self.assertIn("S01帮同学补课", masked)

    def test_mask_markdown_table_keeps_other_text(self):
        src = self.write("事实.md", "# 四年级一班\n\n| 姓名 | 表现 |\n|---|---|\n| 赵子涵 | 担任班长 |\n| 钱多多 | 爱画画 |\n\n说明：子涵和多多都参加了科技节。\n")
        code, _out, err = self.run_main("mask", str(src))
        self.assertEqual(code, 0, err)
        masked = (self.tmp / "事实-脱敏.md").read_text(encoding="utf-8")
        self.assertIn("# 四年级一班", masked)
        self.assertIn("| S01 | 担任班长 |", masked)
        self.assertIn("S01和S02都参加了科技节", masked)

    @unittest.skipUnless(HAS_OPENPYXL, "未安装 openpyxl")
    def test_mask_xlsx(self):
        import openpyxl  # type: ignore
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["学生姓名", "具体表现"])
        ws.append(["孙悦", "主动打扫卫生"])
        ws.append(["周一鸣", "数学竞赛获奖"])
        path = self.tmp / "名单.xlsx"
        wb.save(str(path))
        code, _out, err = self.run_main("mask", str(path))
        self.assertEqual(code, 0, err)
        masked = (self.tmp / "名单-脱敏.md").read_text(encoding="utf-8")
        self.assertNotIn("孙悦", masked)
        self.assertNotIn("周一鸣", masked)

    def test_mask_without_names_is_input_error(self):
        src = self.write("无姓名.txt", "这学期班级开展了三次主题班会。\n")
        code, _out, err = self.run_main("mask", str(src))
        self.assertEqual(code, 2)
        self.assertIn("没有识别到学生姓名", err)
        self.assertFalse(any(self.tmp.glob("*-脱敏*")))

    def test_unmask_rejects_bad_mapping(self):
        comments = self.write("评语.txt", "S01：你好。\n")
        bad = self.write("表.csv", "a,b\n1,2\n")
        code, _out, err = self.run_main("unmask", str(comments), str(bad))
        self.assertEqual(code, 2)


class CliTest(K12TestCase):

    def test_missing_file_returns_2(self):
        code, _out, err = self.run_main("parents", str(self.tmp / "不存在.txt"))
        self.assertEqual(code, 2)
        self.assertIn("找不到文件", err)

    def test_unsupported_suffix_returns_2(self):
        code, _out, _err = self.run_main("parents", str(self.write("信.pdf", "x")))
        self.assertEqual(code, 2)

    def test_no_subcommand_returns_2(self):
        code, _out, _err = self.run_main()
        self.assertEqual(code, 2)

    def test_help_is_chinese(self):
        code, out, _err = self.run_main("--help")
        self.assertEqual(code, 0)
        self.assertIn("用法：", out)
        self.assertIn("子命令", out)

    def test_text_output(self):
        code, out, _err = self.run_main("parents", str(SAMPLES / "parents_must_fail.txt"))
        self.assertEqual(code, 0)
        self.assertIn("[P0] JZ-001", out)


class GeneralCheckTest(K12TestCase):

    def test_general_hits_all_four_redlines(self):
        text = (
            "本学期拟按考试成绩分班并公布考试成绩排名。\n"
            "迎检前突击补齐安全记录和家访记录。\n"
            "课后服务统一讲授新课，要求学生强制参加。\n"
            "对低保户张明同学给予了资助。\n"
        )
        p = self.write("general_fail.txt", text)
        code, out, _err = self.run_main("general", str(p), "--json", "--strict")
        self.assertEqual(code, 1)
        data = json.loads(out)
        ids = {i["id"] for i in data["issues"]}
        self.assertEqual(ids, {"K12-G01", "K12-G02", "K12-G03", "K12-G04"})

    def test_general_clean_and_negation_exempt(self):
        text = (
            "本学期严格落实双减要求，不得公布考试成绩排名，严禁课后服务讲授新课或强制参加。\n"
            "全校为32名困难学生落实资助，严禁补造台账。\n"
        )
        p = self.write("general_pass.txt", text)
        code, out, _err = self.run_main("general", str(p), "--json", "--strict")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["issues"], [])

    def _general_ids(self, text):
        p = self.write("general_tmp.txt", text)
        code, out, _err = self.run_main("general", str(p), "--json")
        return {i["id"] for i in json.loads(out)["issues"]}

    def test_g04_aggregate_count_not_reported(self):
        ids = self._general_ids("本学期学校统计全校建档立卡学生共43人，已全部享受资助政策。\n")
        self.assertNotIn("K12-G04", ids)

    def test_g04_individual_still_reported(self):
        for s in ("建档立卡学生王某家庭困难，已资助。", "对低保户张明同学给予了资助。", "单亲家庭的某同学需要关注。"):
            with self.subTest(s=s):
                self.assertIn("K12-G04", self._general_ids(s + "\n"))

    def test_g04_list_and_identity_variants_reported(self):
        for s in ("五年级二班低保户学生名单：郑磊、孙婷、何静。", "建档立卡学生名单：郑磊、孙婷、何静。",
                  "低保学生赵强已纳入帮扶。", "特困学生名单:郑磊,孙婷,何静。", "低保家庭学生：郑磊、孙婷。"):
            with self.subTest(s=s):
                self.assertIn("K12-G04", self._general_ids(s + "\n"))

    def test_g04_aggregate_variants_not_reported(self):
        for s in ("全校建档立卡学生共43人，已全部享受资助。", "全校低保学生3名，均已落实资助。",
                  "本学期特困学生名单已按规定渠道单独报送。", "困难家庭学生共12人，占比3%。"):
            with self.subTest(s=s):
                self.assertNotIn("K12-G04", self._general_ids(s + "\n"))

    def test_g04_third_round_cases(self):
        for s in ("五年级二班低保户学生3名：李华、王芳、赵强。", "建档立卡学生王某某。", "低保户张明同学。"):
            with self.subTest(s=s):
                self.assertIn("K12-G04", self._general_ids(s + "\n"))
        for s in ("关注离异家庭子女心理健康：班主任、心理教师、家长三方联动。",
                  "困难家庭学生资助项目包括：助学金、营养餐、校服减免。",
                  "低保学生3名，均已落实资助。", "特困学生名单已按规定渠道报送。",
                  "学校开展单亲家庭学生关爱活动，覆盖学生56人。",
                  "针对抑郁症等心理问题，学校开设讲座：识别、求助、陪伴。",
                  "对违纪处分情况进行统计：警告2人、记过1人。",
                  "违纪处分政策学习王主任作专题辅导。", "低保政策由李老师负责解读。"):
            with self.subTest(s=s):
                self.assertNotIn("K12-G04", self._general_ids(s + "\n"))

    def test_g03_basis_points_to_after_school_section(self):
        for rule in k12_check.GENERAL_RULES:
            if rule[0] == "K12-G03":
                self.assertIn("第六条", rule[-1])
                self.assertNotIn("第四条", rule[-1])
        text = (SCRIPTS_DIR.parent / "references" / "redlines.md").read_text(encoding="utf-8")
        self.assertIn("## 六、课后服务自愿参加", text)


class GeneralNameRecognitionTest(K12TestCase):
    """K12-G04 的“锚点 + 候选姓名 + 打分”：句子级期望（应报、不应报）与遮蔽。"""

    SHOULD_REPORT = (
        "对低保家庭学生马小明已落实资助。",
        "建档立卡户孙小红同学家庭困难。",
        "单亲家庭的郭晓东同学需要关注。",
        "低保户张明同学。",
        "建档立卡学生王某某。",
        "五年级二班低保户学生名单：郑磊、孙婷、何静。",
        "低保学生赵强已纳入帮扶。",
        "特困学生名单:郑磊,孙婷,何静",
    )
    SHOULD_NOT_REPORT = (
        "本学期特困学生：一年级、三年级各2人",
        "低保家庭学生名单：七年级、八年级，详见附表",
        "本学期学校统计全校建档立卡学生共43人，已全部享受资助政策。",
        "低保学生3名，均已落实资助。",
        "困难家庭学生共12人。",
        "特困学生名单已按规定渠道报送。",
        "关注离异家庭子女心理健康：班主任、心理教师、家长三方联动。",
        "困难家庭学生资助项目包括：助学金、营养餐、校服减免。",
        "违纪处分政策学习王主任作专题辅导。",
        "低保政策由李老师负责解读。",
        "同学们积极参与低保政策宣传。",
        "严禁公开低保学生张明的信息。",
        "不得公示低保学生赵强的姓名。",
    )
    NAMES = ("马小明", "孙小红", "郭晓东", "张明", "郑磊", "孙婷", "何静", "赵强")

    def _general(self, text: str, *extra: str) -> str:
        p = self.write("general_g04.txt", text)
        code, out, err = self.run_main("general", str(p), *extra)
        self.assertIn(code, (0, 1), err)
        return out

    def _issues(self, text: str) -> list:
        return json.loads(self._general(text + "\n", "--json"))["issues"]

    def test_should_report_as_p0(self):
        for s in self.SHOULD_REPORT:
            with self.subTest(s=s):
                issues = self._issues(s)
                self.assertEqual([(i["id"], i["level"]) for i in issues], [("K12-G04", "P0")])

    def test_should_not_report(self):
        for s in self.SHOULD_NOT_REPORT:
            with self.subTest(s=s):
                self.assertEqual([i["id"] for i in self._issues(s) if i["id"] == "K12-G04"], [])

    def test_pseudo_name_after_identity_stays_p0_and_is_not_masked(self):
        for s in ("单亲家庭的某同学需要关注。", "低保家庭A同学已资助。", "建档立卡学生王某家庭困难，已资助。"):
            with self.subTest(s=s):
                issues = self._issues(s)
                self.assertEqual([i["level"] for i in issues], ["P0"])
                self.assertNotIn("〔姓名", issues[0]["excerpt"])

    def test_same_clause_after_tongxue_anchor(self):
        # “同学”后锚点：姓名与敏感身份词同分句才报；跨分句不报
        issues = self._issues("李华同学是低保家庭的孩子。")
        self.assertEqual([(i["id"], i["level"]) for i in issues], [("K12-G04", "P1")])  # 分数 5：低置信
        self.assertEqual(self._issues("李华同学在校表现良好，低保家庭学生共12人。"), [])

    def test_excerpt_masks_names_in_text_and_json(self):
        text = "\n".join(self.SHOULD_REPORT) + "\n"
        out_json = self._general(text, "--json")
        out_text = self._general(text)
        for name in self.NAMES:
            self.assertNotIn(name, out_json)
            self.assertNotIn(name, out_text)
        issues = json.loads(out_json)["issues"]
        self.assertEqual(len(issues), len(self.SHOULD_REPORT))
        by_line = {i["line"]: i["excerpt"] for i in issues}
        self.assertIn("低保家庭学生〔姓名1〕", by_line[1])
        self.assertIn("低保户学生名单：〔姓名", by_line[6])
        self.assertIn("建档立卡学生王某某", by_line[5])  # 代称不遮蔽、不进姓名表

    def test_bare_name_on_later_line_is_masked_in_other_rules(self):
        text = "低保家庭学生马小明已落实资助。\n学校拟公布马小明的考试成绩排名。\n"
        data = json.loads(self._general(text, "--json"))
        g01 = [i for i in data["issues"] if i["id"] == "K12-G01"]
        self.assertEqual(len(g01), 1)
        self.assertNotIn("马小明", g01[0]["excerpt"])
        self.assertIn("〔姓名1〕", g01[0]["excerpt"])

    def test_stage_other_than_compulsory_keeps_p0(self):
        p = self.write("g.txt", "低保户张明同学。\n")
        code, out, _err = self.run_main("general", str(p), "--stage", "高中", "--json")
        self.assertEqual(json.loads(out)["issues"][0]["level"], "P0")


class K12PolicyRulesTest(K12TestCase):
    def test_jz003_scoped_negation_preserves_affirmative_disclosures(self):
        cases = (
            ("义务教育", "不晒成绩。", False),
            ("高中", "不在家长群发布成绩单，不按成绩给学生排名次张贴。", False),
            ("义务教育", "学校不按成绩排名次。", False),
            ("义务教育", "学校不公布、不张贴、不通报排名。", False),
            ("高中", "不公布排名，也不在班群发布成绩单。", False),
            ("义务教育", "学校不仅公布成绩，还张贴考试排名。", True),
            ("义务教育", "学校不得不公布成绩。", True),
            ("高中", "考试成绩，没有不公布的。", True),
            ("义务教育", "学校没有不公布成绩的。", True),
            ("义务教育", "不收班费并发布考试成绩。", True),
            ("高中", "不在教师群发布成绩，在家长群发布成绩。", True),
            ("高中", "不在课堂讨论，而是张贴考试排名。", True),
        )
        for stage, sentence, expected in cases:
            with self.subTest(stage=stage, sentence=sentence):
                path = self.write("成绩.txt", sentence)
                report = self.run_json("parents", str(path), "--stage", stage)
                self.assertEqual("JZ-003" in self.ids(report), expected)

    def test_score_and_general_rank_use_scoped_negation(self):
        cases = (
            ("parents", "JZ-014", "学校不在家长群公布平均分95分。", []),
            ("parents", "JZ-014", "学校不得不公布平均分95分。", ["P0"]),
            ("parents", "JZ-014", "学校不仅公布平均分95分，还张贴个人成绩。", ["P0"]),
            ("general", "K12-G01", "学校不在家长群张贴考试成绩。", []),
            ("general", "K12-G01", "学校不按成绩排名。", []),
            ("general", "K12-G01", "学校没有不公布考试成绩的。", ["P0"]),
            ("general", "K12-G01", "学校不收资料费并张贴考试成绩。", ["P0"]),
        )
        for command, rid, text, expected in cases:
            with self.subTest(command=command, text=text):
                path = self.write("成绩.txt", text)
                report = self.run_json(command, str(path))
                self.assertEqual([i["level"] for i in report["issues"] if i["id"] == rid], expected)

    def test_r1_matrix_both_entries(self):
        p0 = ("P0", "P1", "P1")
        skip = ("skip",) * 3
        cases = (
            ("force", "全体学生必须购买意外伤害保险。", p0, "第四十六条"),
            ("force", "家委会向每户收取班费80元。", p0, "不得以家长委员会名义违规收费"),
            ("force", "学校强制要求学生缴纳校服费。", p0, "第五条"),
            ("force", "课后服务不缴费则不予报名。", p0, "第9段、第20段"),
            ("force", "拒缴校服费，将不发放教材。", p0, "第五条"),
            ("force", "全体学生必须购买教辅材料。", p0, "中小学教辅材料管理办法"),
            ("uniform", "统一购买校服，开学第一周缴费。", p0, "第五条"),
            ("uniform", "学校统一订购教辅资料。", p0, "中小学教辅材料管理办法"),
            ("uniform", "学校统一办理意外伤害保险。", p0, "第四十六条"),
            ("uniform", "开学后统一缴纳班费。", p0, "第五条"),
            ("optout", "该保险由家长自愿报名，不参加不收费，学校仅代办。", skip, ""),
            ("optout", "保险由家长自愿统一办理，不参加不收费。", skip, ""),
            ("optout", "校服由家长自愿统一购买，也可自行购买。", skip, ""),
            ("optout", "教辅自愿统一订购，不强制。", skip, ""),
            ("optout", "家委会只代收保险费用，家长自愿报名，不参加不收费。", skip, ""),
            ("ambiguous", "教辅由家长自愿统一购买。", ("P1",) * 3, "中小学教辅材料管理办法"),
            ("ambiguous", "校内自愿购买意外伤害保险，学校统一办理。", ("P1",) * 3, "第四十六条"),
            ("conflict", "该保险自愿报名，但全体学生必须购买。", p0, "第四十六条"),
            ("conflict", "课后服务费写明自愿，但拒缴不予报名。", p0, "第20段"),
            ("conflict", "学校称家长可以自愿认购，可实际强制要求学生缴纳保险费。", p0, "第四十六条"),
            ("different", "课后服务自愿参加，但全体学生必须购买意外伤害保险。", p0, "第四十六条"),
            ("different", "本项免收费用，但要求全体学生缴费购买教辅。", p0, "中小学教辅材料管理办法"),
            ("unbound", "家长自愿参加，学校统一购买校服。", ("P1",) * 3, "第五条"),
            ("quoted", "严禁统一订购教辅。", skip, ""),
            ("quoted", "学校不统一订购教辅资料。", skip, ""),
            ("quoted", "家委会不得以班费名义向家长收取材料费。", skip, ""),
            ("periodical", "全体学生必须统一征订报刊。", skip, ""),
        )
        self.assertEqual({key for key, *_ in cases}, set(k12_check.FEE_MATRIX))
        for key, sentence, expected, basis in cases:
            self.assertEqual(k12_check.FEE_MATRIX[key][1], expected, key)
            path = self.write("收费.txt", sentence)
            for stage, level in zip(k12_check.STAGES, expected):
                with self.subTest(sentence=sentence, stage=stage):
                    for command, rid in (("general", "K12-G05"), ("parents", "JZ-006")):
                        report = self.run_json(command, str(path), "--stage", stage)
                        items = [i for i in report["issues"] if i["id"] == rid]
                        self.assertEqual([(i["line"], i["level"]) for i in items],
                                         [] if level == "skip" else [(1, level)], command)
                        if items:
                            self.assertIn(basis, items[0]["basis"])
                            if key == "ambiguous":
                                self.assertIn("请核对是否可以不参加", items[0]["message"])
                            if key == "unbound":
                                self.assertEqual(items[0]["message"], "自愿与统一或强制表述并存，请核对各项目是否可以不参加")

    def test_paid_tutoring_both_entries(self):
        cases = (
            ("学校推荐学生参加校外有偿补课。", True),
            ("班主任组织八年级学生到校外机构付费补习。", True),
            ("我校安排学生在校外补课，参加者每人收费200元。", True),
            ("教师向校外培训机构介绍生源。", True),
            ("学校向培训机构提供学生信息。", True),
            ("教师提供学生名单给校外培训机构。", True),
            ("学校组织校外培训机构为教师开展免费急救培训。", False),
            ("学校组织学生参加校内免费作业辅导。", False),
            ("禁止学校组织或推荐学生参加校外有偿补课。", False),
            ("学校明确不得向培训机构提供学生信息。", False),
            ("学校组织学生参加校外非学科公益活动。", False),
            ("学校推荐学生参加校外免费辅导。", False),
            ("我校安排学生在校外补课，报名者可获100元补贴。", False),
            ("学生家长向学校推荐学生参加校外有偿补课。", False),
            ("学校组织学生参加校外有偿补课治理宣传。", False),
            ("建议成绩不理想的学生报名参加周末辅导班，保证提分。", False),
        )
        for sentence, expected in cases:
            path = self.write("补课.txt", sentence)
            for stage in k12_check.STAGES:
                with self.subTest(sentence=sentence, stage=stage):
                    for command, rid in (("general", "K12-G09"), ("parents", "JZ-008")):
                        report = self.run_json(command, str(path), "--stage", stage)
                        self.assertEqual([(i["line"], i["level"]) for i in report["issues"] if i["id"] == rid],
                                         [(1, "P0")] if expected else [], command)

    def test_g06_paragraph_basis_and_legacy_jz007(self):
        authority = "依据：《课后服务收费办法》（某教〔2026〕12号）。"
        cases = (
            ("每生收费120元。\n" + authority, [], [1]),
            ("收费标准：每生 120 元。\n" + authority, [], [1]),
            ("根据报名人数统计，每生收费120元。", [1], []),
            ("每生收费120元。\n\n" + authority, [1], [1]),
            (authority + "\n\n每生收费120元。", [3], [3]),
        )
        for draft, expected_general, expected_parents in cases:
            path = self.write("依据.txt", draft)
            with self.subTest(draft=draft):
                for command, rid, expected in (("general", "K12-G06", expected_general),
                                                ("parents", "JZ-007", expected_parents)):
                    report = self.run_json(command, str(path))
                    self.assertEqual([(i["line"], i["level"]) for i in report["issues"] if i["id"] == rid],
                                     [(line, "P1") for line in expected])

    def test_g06_table_scope_and_exemptions(self):
        rows = (
            "项目 | 金额 | 依据\n--- | --- | ---\n"
            "收取课后服务费 | 120元 | 《课后服务收费办法》\n"
            "缴纳校服费 | 180元 | 根据报名人数统计\n"
            "收取资料费 | 35元 |\n"
            "教辅 | 免收20元 |\n"
        )
        prose = (
            "\n统计本学期实收120元。\n免收每生120元。\n财政预算拨付120元，用于课后服务。\n"
            "缴纳课后服务费【待补：每生120元】。\n缴纳费40元，收费依据：【待补】。\n"
            "\n收取保险费10元。\n依据：《课后服务收费办法》。\n"
            "\n收取教材费20元，按经区教育局批准的收费标准执行。\n"
            "\n收费标准：\n每生120元。\n\n每人一百二十元，须缴纳资料费。\n"
            "【起草说明】\n每生缴纳60元。"
        )
        path = self.write("收费表.md", rows + prose)
        issues = [i for i in self.run_json("general", str(path))["issues"] if i["id"] == "K12-G06"]
        self.assertEqual([i["line"] for i in issues], [4, 5, 14, 20, 22])
        self.assertTrue(all(i["level"] == "P1" for i in issues))

    @unittest.skipUnless(HAS_DOCX, "未安装 python-docx")
    def test_g06_word_tables_keep_rows_and_draft_boundary(self):
        d = docx.Document()
        d.add_paragraph("按下表所列标准收费。")
        table = d.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "收取课后服务费120元"
        table.cell(0, 1).text = "《课后服务收费办法》"
        table.cell(1, 0).text = "缴纳校服费180元"
        d.add_paragraph("【起草说明】")
        table = d.add_table(rows=1, cols=1)
        table.cell(0, 0).text = "每生收取50元"
        path = self.tmp / "收费表.docx"
        d.save(path)
        issues = [i for i in self.run_json("general", str(path))["issues"] if i["id"] == "K12-G06"]
        self.assertEqual([(i["line"], i["level"]) for i in issues], [(4, "P1")])

    def test_vocational_stage_routes_and_skips(self):
        path = self.write("中职.txt", "全体学生必须购买意外伤害保险。\n一年级布置书面作业。\n课后服务一律参加。")
        for command, rid in (("parents", "JZ-006"), ("general", "K12-G05")):
            report = self.run_json(command, str(path), "--stage", "中职", "--strict")
            self.assertEqual(report["stage"], "中职")
            self.assertIn(rid, self.ids(report, "P1"))
            self.assertNotIn("JZ-004", self.ids(report))

    def test_rule_catalog_text_json_and_live_rules(self):
        code, stdout, err = self.run_main("--list-rules")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("中小学专检规则（38 条）", stdout)
        code, out, err = self.run_main("--list-rules", "--json")
        self.assertEqual((code, err), (0, ""))
        data = json.loads(out)
        rules = {rule["id"]: rule for rule in data["rules"]}
        self.assertEqual((len(rules), len(data["rules"])), (38, 38))
        expected = {
            "comments": set(re.findall(r"PY-\d{3}", inspect.getsource(k12_check.check_comments))),
            "parents": {rule.id for rule in k12_check.PARENT_RULES} | {"K12-G04"},
            "general": {rule[0] for rule in k12_check.GENERAL_RULES} | {k12_check.FEE_BASIS_RULE[0]},
        }
        for rule in k12_check.CROSS_ENTRY_RULES:
            expected["parents"].add(rule.parents_id)
            expected["general"].add(rule.general_id)
        for command, ids in expected.items():
            self.assertEqual({rid for rid, rule in rules.items() if command in rule["commands"]}, ids)
        for rid, rule in rules.items():
            self.assertTrue(rule["condition"])
            self.assertIn(rid + " | ", stdout)
        for rid, levels in {"PY-003": ["P0", "P1", "P2"], "PY-017": ["P1", "P2"],
                            "JZ-002": ["P0", "P1", "P2"], "K12-G04": ["P0", "P1"],
                            "JZ-006": ["P0", "P1", "skip"], "K12-G05": ["P0", "P1", "skip"]}.items():
            self.assertEqual(rules[rid]["levels"], levels)
        for rid in ("JZ-004", "JZ-009", "JZ-010"):
            stages = rules[rid]["stage_levels"]["parents"]
            self.assertEqual((stages["高中"], stages["中职"]), (["skip"], ["skip"]))
        self.assertEqual(len(data["fee_matrix"]), len(k12_check.FEE_MATRIX))
        for row, (text, levels) in zip(data["fee_matrix"], k12_check.FEE_MATRIX.values()):
            self.assertEqual(row, {"condition": text, "stage_levels": dict(zip(k12_check.STAGES, levels))})
            self.assertIn(text + " | " + " | ".join(levels), stdout)

    def test_rule_catalog_usage_errors(self):
        path = str(self.write("样稿.txt", "测试"))
        for args in ((), ("--json",), ("--list-rules", "--stage", "中职"), ("--list-rules", "--wrong"),
                     ("parents", path, "--list-rules"), ("--list-rules", "general", path),
                     ("comments", path, "--stage", "未知")):
            with self.subTest(args=args):
                self.assertEqual(self.run_main(*args)[0], 2)

    def _assert_review_hits(self, cases):
        for command, rid, body, level in cases:
            with self.subTest(command=command, body=body):
                path = self.write("评审.txt", body)
                actual = [issue["level"] for issue in self.run_json(command, str(path))["issues"] if issue["id"] == rid]
                self.assertEqual(actual, [] if level == "SKIP" else [level])

    def _assert_review_pair(self, cases, general_id, parents_id):
        self._assert_review_hits((command, rid, body, level) for body, level in cases
                                 for command, rid in (("general", general_id), ("parents", parents_id)))

    def test_review_r1_b1_rank_negation_and_independent_score(self):
        cases = (
            ('parents', 'JZ-003', '考试成绩不排名是不可能的。', 'P0'),
            ('parents', 'JZ-003', '不公布成绩是不可能的。', 'P0'),
            ('parents', 'JZ-003', '不公布成绩排名是不行的。', 'P0'),
            ('parents', 'JZ-003', '考试成绩不可能不公布。', 'P0'),
            ('parents', 'JZ-003', '期末考试不可能不排名。', 'P0'),
            ('parents', 'JZ-003', '学校不是不公布成绩，而是本周五公布。', 'P0'),
            ('parents', 'JZ-003', '学校不会不公布成绩。', 'P0'),
            ('parents', 'JZ-003', '成绩单不会不发到家长群。', 'P0'),
            ('parents', 'JZ-003', '考试成绩没有不排名的。', 'P0'),
            ('parents', 'JZ-003', '考试成绩学校不得不公布。', 'P0'),
            ('general', 'K12-G01', '不公布考试成绩是不可能的。', 'P0'),
            ('general', 'K12-G01', '考试成绩不可能不公布。', 'P0'),
            ('parents', 'JZ-014', '学校不再公布排名且本次考试平均分为88.5分。', 'P0'),
            ('parents', 'JZ-014', '学校不按成绩排名并宣布本次数学平均分91分。', 'P0'),
            ('parents', 'JZ-014', '不排名且全班平均分89分。', 'P0'),
            ('parents', 'JZ-003', '请不要把成绩发到家长群。', 'SKIP'),
            ('parents', 'JZ-003', '不要在家长群发布成绩单。', 'SKIP'),
            ('parents', 'JZ-003', '学校不再在家长群发布成绩单。', 'SKIP'),
            ('parents', 'JZ-003', '学校不允许在家长群公布成绩。', 'SKIP'),
            ('parents', 'JZ-003', '学校不搞成绩排名。', 'SKIP'),
            ('parents', 'JZ-003', '学校不组织成绩排名。', 'SKIP'),
            ('parents', 'JZ-003', '学校不进行成绩排名。', 'SKIP'),
            ('parents', 'JZ-003', '学校拒绝公布成绩排名。', 'SKIP'),
            ('parents', 'JZ-003', '学校未在家长群公布成绩。', 'SKIP'),
            ('parents', 'JZ-003', '学校没有在家长群公布成绩。', 'SKIP'),
            ('parents', 'JZ-003', '请家长不要将成绩发到家长群。', 'SKIP'),
            ('parents', 'JZ-003', '成绩排名不得张贴在宣传栏。', 'SKIP'),
            ('general', 'K12-G01', '学校未在家长群公布考试成绩。', 'SKIP'),
            ('general', 'K12-G01', '不要在公告栏张贴考试成绩。', 'SKIP'),
            ('general', 'K12-G01', '学校拒绝公布考试成绩。', 'SKIP'),
            ('parents', 'JZ-014', '学校未在家长群公布平均分95分。', 'SKIP'),
            ('parents', 'JZ-014', '学校没有在群里公布平均分95分。', 'SKIP'),
            ('parents', 'JZ-003', '没有学生、班级的考试排名；面向家长的材料没有公布分数（义务教育）', 'SKIP'),
            ('parents', 'JZ-003', '不要在家长群晒成绩。', 'SKIP'),
            ('parents', 'JZ-003', '学校严禁在家长群发成绩单。', 'SKIP'),
        )
        self._assert_review_hits(cases)

    def test_r1_new_adversarial_rank(self):
        cases = (
            ('parents', 'JZ-003', '班会上不通报全班考试成绩。', 'SKIP'),
            ('parents', 'JZ-003', '不把阶段测验成绩传到群里。', 'SKIP'),
            ('general', 'K12-G01', '按学校规定不在教室门口公示考试成绩。', 'SKIP'),
            ('parents', 'JZ-014', '不在班群讨论名次且数学均分为87分。', 'P0'),
            ('general', 'K12-G01', '班主任不能不通报考试成绩。', 'P0'),
            ('parents', 'JZ-003', '成绩单不能不上传到班级群。', 'P0'),
            ('parents', 'JZ-003', '班主任不公示名次怎么行？', 'P0'),
            ('general', 'K12-G01', '不张贴考试成绩不可以。', 'P0'),
            ('parents', 'JZ-014', '不会不公开本班平均分83分。', 'P0'),
            ('parents', 'JZ-003', '排名不会不晒。', 'P0'),
        )
        self._assert_review_hits(cases)

    def test_review_r1_b2_m2_fee_project_and_refusal(self):
        cases = (
            ('课后服务自愿参加，不参加不收费，学校统一购买安全手册。', 'P0'),
            ('课后服务自愿参加，不参加不收费，全体学生必须购买运动鞋。', 'P0'),
            ('学校不组织统一征订报刊，但全体学生必须缴纳研学费。', 'P0'),
            ('报刊自愿订阅，全体学生必须购买安全手册。', 'P0'),
            ('| 校服 | 统一购买 | 课后服务 | 自愿参加，不参加不收费 |', 'P0'),
            ('校服统一购买、课后服务自愿参加且不参加不收费。', 'P0'),
            ('本项目免收报名费并要求全体学生必须购买意外伤害保险。', 'P0'),
            ('未购买过保险的学生必须统一购买意外伤害保险。', 'P0'),
            ('没有购买校服的新生必须统一购买校服。', 'P0'),
            ('学校取消减免后统一收取校服费180元。', 'P0'),
            ('学校不得不统一购买教辅资料。', 'P0'),
            ('未订购教辅者不得报名。', 'P0'),
            ('未缴纳校服费者不发教材。', 'P0'),
            ('不缴纳本学期意外伤害保险费的，不得参加研学活动。', 'P0'),
            ('家长委员会决定，向每生收取班费100元。', 'P0'),
            ('以家委会名义，向家长收取资料费。', 'P0'),
            ('学校统一办理《意外伤害保险》。', 'P0'),
            ('课后服务自愿参加，不参加不收费（全体学生必须购买意外伤害保险）。', 'P0'),
            ('校服费180元（全体学生必须缴纳）。', 'P0'),
            ('全体学生必须购买校服，课后服务自愿参加、不参加不收费。', 'P0'),
            ('| 意外伤害保险 | 全体学生必须购买 | 50元 |', 'P0'),
            ('本学期学校继续开展课后服务，家长可自愿为孩子报名参加，不参加不收费，同时开学第一周全体学生必须统一购买教辅资料。', 'P0'),
            ('校服（自愿统一购买）。', 'P1'),
            ('学校不统一订购教辅资料，全体学生必须购买校服。', 'P0'),
            ('学校不统一订购教辅资料但全体学生必须购买校服。', 'P0'),
            ('学校不统一订购教辅资料并要求全体学生购买校服。', 'P0'),
            ('所有学生自愿购买校服，不强制。', 'SKIP'),
            ('所有学生均可自愿购买校服，可自行购买。', 'SKIP'),
            ('面向全体学生收费的项目均实行自愿原则，不参加不收费。', 'SKIP'),
            ('向全体家长收取课后服务费坚持自愿原则，不参加不收费。', 'SKIP'),
            ('全体义务教育阶段学生自愿购买校服，可自行购买。', 'SKIP'),
            ('家长须知：自愿购买校服，可自行购买。', 'SKIP'),
            ('校服由家长自愿统一购买（可自行购买）。', 'SKIP'),
            ('不参加不收费，家长自愿统一办理意外伤害保险。', 'SKIP'),
            ('学校严禁强制或变相强制全体学生统一购买教辅资料。', 'SKIP'),
            ('不得要求全体学生必须购买意外伤害保险。', 'SKIP'),
            ('严禁以家委会名义收取班费。', 'SKIP'),
            ('课后服务不收费（不缴保险费不予报名）。', 'P0'),
            ('家长自愿报名，不参加不收费，学校统一代收意外伤害保险费。', 'SKIP'),
            ('不强制，自愿统一购买校服。', 'SKIP'),
        )
        self._assert_review_pair(cases, "K12-G05", "JZ-006")

    def test_r1_new_adversarial_fee(self):
        cases = (
            ('周五报名完全自愿，所有学生必须购买运动器材。', 'P1'),
            ('秋游自愿参加，不参加不收费；必须购买交通卡。', 'P0'),
            ('报纸须统一征订，家长可自行购买运动鞋。', 'SKIP'),
            ('学校禁止规定不缴校服费不得入学。', 'SKIP'),
            ('选读材料自愿参加，未缴纳练习册费不得选课。', 'P0'),
            ('统一代收费的项目必须列出明细。', 'SKIP'),
            ('不订购礼仪手册便不发学习用品。', 'P0'),
            ('家委会商议，向参加活动的学生收取活动费。', 'P0'),
            ('校服自愿购买（必须购买研学纪念册）。', 'P0'),
            ('面向所有监护人自愿征订校徽，也可自行购买。', 'SKIP'),
            ('校外参观可不参加、学校统一订购《急救实用手册》。', 'P0'),
            ('学校不会不统一收取学生交通费。', 'P0'),
            ('户外研学自愿，不参加不收费，学校统一购买校服。', 'P0'),
            ('| 意外伤害保险 | 家长自愿购买，不参加不收费 | 50元 |', 'SKIP'),
        )
        self._assert_review_pair(cases, "K12-G05", "JZ-006")

    def test_review_r1_b4_tutoring_and_governance(self):
        cases = (
            ('班主任组织同学们参加校外有偿补课。', 'P0'),
            ('现推荐成绩不理想的学生参加周末校外有偿补课。', 'P0'),
            ('向校外培训机构提供学生联系方式。', 'P0'),
            ('教师将学生名单提供给校外培训机构。', 'P0'),
            ('班主任把学生联系方式发给校外培训机构。', 'P0'),
            ('学校向校外培训机构提供家长联系方式。', 'P0'),
            ('学校向校外培训机构提供学生和家长信息。', 'P0'),
            ('教师向校外培训机构推荐生源。', 'P0'),
            ('学校为校外培训机构输送生源。', 'P0'),
            ('老师推荐学生参加校外有偿培训班。', 'SKIP'),
            ('学校推荐学生参加校外培训机构的有偿辅导。', 'SKIP'),
            ('年级组组织学生参加校外有偿补课。', 'P0'),
            ('学校不组织校内免费辅导而组织学生参加校外有偿补课。', 'P0'),
            ('班主任向“新星教育”培训机构介绍生源。', 'P0'),
            ('学校开展教师组织学生参加校外有偿补课专项整治工作。', 'SKIP'),
            ('学校严肃查处教师组织学生参加校外有偿补课行为。', 'SKIP'),
            ('学校组织学生参加校外研学实践活动，每生收取实践费80元。', 'SKIP'),
            ('部分家长自行给孩子报了校外有偿补课班，学校建议家长理性选择。', 'SKIP'),
            ('学校组织校外培训机构为教师开展免费急救培训。', 'SKIP'),
            ('学校组织学生在课后服务时间开展校内免费作业辅导。', 'SKIP'),
            ('严禁中小学校和在职教师组织、推荐学生参加校外有偿补课。', 'SKIP'),
            ('严禁教师为校外培训机构介绍生源、提供学生信息。', 'SKIP'),
        )
        self._assert_review_pair(cases, "K12-G09", "JZ-008")

    def test_r1_new_adversarial_tutoring(self):
        cases = (
            ('教务处已安排学生周六参加校外付费学科辅导。', 'P0'),
            ('请把本班监护人电话号码转交给青苗培训机构。', 'P0'),
            ('学校批量提供学生通讯录给辅导机构。', 'P0'),
            ('学校按上级要求公布有偿补课举报电话，请家长及时反馈。', 'SKIP'),
            ('学校对教师推荐学生参加校外有偿补课展开排查。', 'SKIP'),
            ('学校公布承诺书：本校教职工不参与有偿补课。', 'SKIP'),
            ('学校继续治理有偿补课，但本周安排学生到校外付费补习。', 'P0'),
            ('家长提醒学校不要安排学生参加校外有偿补课。', 'SKIP'),
            ('家长委托教师把学生电话提供给校外培训机构。', 'SKIP'),
            ('学校组织学生参加校外收费书法兴趣活动。', 'SKIP'),
            ('班主任将家长电话发给“青苗培训机构”。', 'P0'),
            ('学校发布承诺书，不组织校外有偿补课，向培训机构介绍生源。', 'SKIP'),
        )
        self._assert_review_pair(cases, "K12-G09", "JZ-008")

    def test_review_r1_m1_basis_and_table_headers(self):
        cases = (
            ('按照惯例，每生收取资料费40元。', 'P1'),
            ('经家委会同意，每生收取班费80元。', 'P1'),
            ('经家委会批准的收费标准，每生收费80元。', 'P1'),
            ('按学校核定的收费标准，每生收费120元。', 'P1'),
            ('依据《2026年春季学期工作方案》，每生收费120元。', 'P1'),
            ('根据报名人数统计，每生收费120元。', 'P1'),
            ('课后服务每生每月收费120元（对困难学生减免）。', 'P1'),
            ('课后服务每生每月收费120元（低保家庭学生免收）。', 'P1'),
            ('| 收费项目 | 收费标准 | 收费依据 |\n| --- | --- | --- |\n| 校服费 | 每生180元 | 根据报名人数统计 |', 'P1'),
            ('| 收费项目 | 收费标准 | 收费依据 |\n| --- | --- | --- |\n| 收取课后服务费 | 每生120元（困难生减免） | 无 |', 'P1'),
            ('依据：《课后服务收费办法》（某教〔2026〕12号）。\n\n校服每生收取180元。', 'P1'),
            ('依据《课后服务收费办法》，每生收取课后服务费120元。\n另收取研学费200元。', 'P1'),
            ('课后服务每生收费120元，【待补：收费依据】。', 'SKIP'),
            ('每生收取课后服务费120元（【待补：收费依据和标准】）。', 'SKIP'),
            ('每生收取课后服务费120元。\n【待补：收费依据】', 'SKIP'),
            ('学校向供电公司支付电费5000元。', 'SKIP'),
            ('学校向参与课后服务的教师支付补助每课时50元。', 'SKIP'),
            ('学校采购实验器材支付3200元。', 'SKIP'),
            ('依据《课后服务及代收费管理办法》（某教〔2026〕8号），每生收取课后服务费120元，代收校服费180元。', 'SKIP'),
            ('课后服务收费标准：每生每月120元。\n上述收费严格执行某发改〔2026〕18号文件规定。', 'SKIP'),
            ('| 项目 | 标准 | 依据 |\n| --- | --- | --- |\n| 收取课后服务费 | 120元 | 某教〔2026〕12号 |', 'SKIP'),
            ('财政预算安排课后服务经费50000元，免收学生费用。', 'SKIP'),
            ('本学期统计累计收取课后服务费36000元。', 'SKIP'),
            ('截至6月底，学校已收取课后服务费24000元。', 'SKIP'),
        )
        self._assert_review_hits(("general", "K12-G06", body, level) for body, level in cases)

    def test_r1_new_adversarial_fee_basis(self):
        cases = (
            ('收取校车费90元。\n【待核实：收费依据文件】', 'SKIP'),
            ('收取研学费260元。\n依据《义务教育学校服务性收费管理细则》。', 'SKIP'),
            ('报名费每生70元（低收入学生免缴），由学校负责收取。', 'P1'),
            ('学校向学生发放奖学金500元并支付手续费。', 'SKIP'),
            ('家委会核定收费标准，向每生缴费窗口代收训练费30元。', 'P1'),
            ('| 活动 | 参与条件 | 估算金额 |\n| --- | --- | --- |\n| 合唱 | 不参加不收费 | 60元 |', 'SKIP'),
            ('学校经区教育局核定收费标准，每生收取校车费90元。', 'SKIP'),
        )
        self._assert_review_hits(("general", "K12-G06", body, level) for body, level in cases)

    def test_catalog_g04_dynamic_and_py005_scope(self):
        rid, _, _, *details = k12_check.G04_RULE
        with patch.object(k12_check, "G04_RULE", (rid, "P2", "P2", *details)):
            rules = {rule["id"]: rule for rule in k12_check.rule_catalog()["rules"]}
        self.assertEqual(rules[rid]["levels"], ["P1", "P2"])
        for command in ("general", "parents"):
            self.assertEqual(rules[rid]["stage_levels"][command], {stage: ["P1", "P2"] for stage in k12_check.STAGES})
        self.assertNotIn("住址", rules["PY-005"]["condition"])
        path = self.write("评语.txt", "S01：你住在家庭住址：北京市海淀区中关村大街1号，学习认真。")
        self.assertNotIn("PY-005", self.ids(self.run_json("comments", str(path))))

    def test_new_p0_guardrail_on_reference_and_example_docs(self):
        references = REPO_ROOT / "skills" / "gongwen-k12" / "references"
        examples = next((REPO_ROOT / "examples").glob("D-*"))
        paths = sorted(references.rglob("*.md")) + sorted(examples.glob("*.md")) + sorted(examples.glob("*.txt"))
        self.assertGreater(len(paths), 36)
        ids = {"K12-G04", "K12-G05", "K12-G06", "K12-G09", "JZ-006", "JZ-008"}
        rank_ids = {"JZ-003", "JZ-014", "K12-G01"}
        # 当前规范文档已有历史命中。固定允许的旧行，保护新增 P0 和既有测试的可移植性。
        for command in ("general", "parents"):
            for path in paths:
                with self.subTest(command=command, path=path.name):
                    report = self.run_json(command, str(path))
                    self.assertEqual([i for i in report["issues"] if i["id"] in ids and i["level"] == "P0"
                                      and i["message"] != "表格姓名列出现真实姓名"], [])
                    baseline = REFERENCE_RANK_BASELINE.get(path.name, ())
                    source = k12_check.load_document(path).lines
                    for issue in report["issues"]:
                        if issue["level"] != "P0" or issue["id"] not in rank_ids:
                            continue
                        line = source[issue["line"] - 1]
                        if issue["id"] == "K12-G01":
                            self.assertEqual(path.name, "quick-cards.md")
                            self.assertIn("公布成绩排名（红线二）", line)
                        elif issue["id"] == "JZ-014":
                            self.assertEqual(path.name, "xuesheng-pingyu.md")
                            self.assertIn("这次单元测验语文得了96分", line)
                        else:
                            self.assertTrue(any(marker in line for marker in baseline), issue)


class ParentsAndCommentsMaskTest(K12TestCase):

    def test_parents_jz012_excerpt_masks_student_name(self):
        text = "本周数学测验后，张小明同学多次违纪，受到批评。\n欧阳晓晓同学屡教不改，请家长配合。\n个别同学作业拖拉，请家长关注。\n"
        p = self.write("parents_name.txt", text)
        code, out_text, _err = self.run_main("parents", str(p))
        code_j, out_json, _err = self.run_main("parents", str(p), "--json")
        self.assertEqual((code, code_j), (0, 0))
        for name in ("张小明", "欧阳晓晓", "晓晓"):
            self.assertNotIn(name, out_text)
            self.assertNotIn(name, out_json)
        issues = json.loads(out_json)["issues"]
        self.assertEqual([i["id"] for i in issues], ["JZ-012", "JZ-012"])
        self.assertIn("〔姓名1〕同学", issues[0]["excerpt"])
        self.assertIn("〔姓名2〕同学", issues[1]["excerpt"])

    def test_parents_identity_anchor_name_masked_in_other_rule_excerpt(self):
        text = "低保家庭学生周杰已资助。\n请家长检查周杰的作业并签字。\n"
        p = self.write("parents_anchor.txt", text)
        code, out, _err = self.run_main("parents", str(p), "--json")
        self.assertEqual(code, 0)
        self.assertNotIn("周杰", out)

    def test_comments_label_kept_but_excerpt_masked(self):
        text = "王小明：你太笨了，家里是低保户王小明的情况要照顾，你和李华同学一起进步。\nS02：你很聪明，这学期进步明显。\n"
        p = self.write("评语_姓名.txt", text)
        code, out, _err = self.run_main("comments", str(p), "--min-chars", "0", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["entries"][0]["label"], "王小明")
        issues = [i for i in data["issues"] if i["id"] in ("PY-001", "PY-006")]
        self.assertEqual({i["id"] for i in issues}, {"PY-001", "PY-006"})
        for i in issues:
            self.assertEqual(i["label"], "王小明")  # label 是教师本机的定位标识，保留
            self.assertNotIn("王小", i["excerpt"])  # 含被摘录截断的残片
            self.assertIn("〔姓名1〕", i["excerpt"])

    def test_code_labels_are_not_masked(self):
        p = self.write("评语_编号.txt", "S01：你太笨了，要加油。\n")
        out = json.loads(self.run_main("comments", str(p), "--min-chars", "0", "--json")[1])
        self.assertTrue(any(i["id"] == "PY-001" and "〔姓名" not in i["excerpt"] for i in out["issues"]))


class BoundaryRevisionTest(K12TestCase):
    """逗号并列名单、JZ-012 窗口放宽到 20 字、否定词“不给/不向”。"""

    def test_comma_list_both_names_found_and_masked(self):
        path = self.write("资助.txt", "特困学生：张三，李四\n")
        report = self.run_json("general", str(path))
        rows = [i for i in report["issues"] if i["id"] == "K12-G04"]
        self.assertEqual(len(rows), 1)
        text = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("张三", text)
        self.assertNotIn("李四", text)
        self.assertEqual(rows[0]["excerpt"], "特困学生：〔姓名1〕，〔姓名2〕")

    def test_later_line_mentioning_second_name_is_masked_too(self):
        path = self.write("资助2.txt", "特困学生：张三，李四\n2026年春季学期李四同学继续享受生活补助。\n")
        text = json.dumps(self.run_json("general", str(path)), ensure_ascii=False)
        self.assertNotIn("李四", text)

    def test_jz012_window_covers_20_chars_within_one_sentence(self):
        path = self.write("通知.txt", "陆思琪同学近期数学作业经常拖拉，多次被老师批评。\n")
        report = self.run_json("parents", str(path))
        self.assertIn("JZ-012", self.ids(report))
        self.assertNotIn("陆思琪", json.dumps(report, ensure_ascii=False))
        # 不跨句：被批评在下一句，不报
        path = self.write("通知2.txt", "陆思琪同学近期数学作业经常拖拉。多次被老师批评。\n")
        self.assertNotIn("JZ-012", self.ids(self.run_json("parents", str(path))))
        # 超过 20 字仍不报
        path = self.write("通知3.txt", "陆思琪同学近期数学作业和语文作业以及英语作业都经常出现拖拉现象，多次被老师批评。\n")
        self.assertNotIn("JZ-012", self.ids(self.run_json("parents", str(path))))

    def test_negated_give_homework_not_reported(self):
        for text in ("学校不给家长布置作业。", "学校不会给家长布置作业。", "学校不再给家长布置作业。", "老师不向家长布置作业。"):
            path = self.write("否定.txt", text + "\n")
            self.assertNotIn("JZ-002", self.ids(self.run_json("parents", str(path))), text)
        path = self.write("肯定.txt", "请给家长布置作业。\n")
        self.assertIn("JZ-002", self.ids(self.run_json("parents", str(path))))

    def test_hong_and_lai_surnames(self):
        path = self.write("洪赖.txt", "低保家庭学生洪建国，建档立卡户赖志强同学。\n")
        report = self.run_json("general", str(path))
        text = json.dumps(report, ensure_ascii=False)
        self.assertIn("K12-G04", self.ids(report))
        self.assertNotIn("洪建国", text)
        self.assertNotIn("赖志强", text)
        path = self.write("洪水.txt", "低保家庭学生资助政策宣传到位，洪水期间做好防汛。\n")
        self.assertNotIn("K12-G04", self.ids(self.run_json("general", str(path))))


class SharedModuleTest(K12TestCase):
    """共享模块 gw_names.py / gw_names.json：数据来源与缺失、损坏时的退出码。"""

    def test_surnames_come_from_shared_json(self):
        data = json.loads((SCRIPTS_DIR / "gw_names.json").read_text(encoding="utf-8"))
        self.assertEqual(k12_check.SURNAMES, set(data["surnames_common"]) | set(data["surnames_rare"]))
        self.assertEqual(k12_check.COMPOUND_SURNAMES, tuple(data["compound"]))
        self.assertEqual(len(k12_check.SURNAMES), 403)  # 旧表 401 字 + 洪、赖（见 gw_names.json 的 surnames_rare）
        self.assertTrue({"洪", "赖"} <= k12_check.SURNAMES)

    def test_looks_like_name_keeps_old_behaviour(self):
        for word in ("王小明", "欧阳晓晓", "张某", "李华"):
            self.assertTrue(k12_check.looks_like_name(word), word)
        for word in ("需改进", "班主任", "家长电话", "S01", "获奖情况"):
            self.assertFalse(k12_check.looks_like_name(word), word)

    def _run_copy(self, files, *args):
        import os
        import subprocess
        script_dir = self.tmp / "pkg" / "scripts"
        script_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            (script_dir / name).write_bytes((SCRIPTS_DIR / name).read_bytes())
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, str(script_dir / "k12_check.py"), *args], capture_output=True,
                              text=True, encoding="utf-8", env=env)

    def _all_commands(self):
        text = self.write("x.txt", "S01：你好。\n")
        table = self.write("t.csv", "编号,姓名\nS01,王小明\n")
        return [("mask", str(text)), ("unmask", str(text), str(table)), ("comments", str(text)),
                ("parents", str(text)), ("general", str(text))]

    def test_missing_gw_names_py_exits_2_for_every_command(self):
        for cmd in self._all_commands():
            with self.subTest(cmd=cmd[0]):
                r = self._run_copy(["k12_check.py", "gw_names.json"], *cmd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("gw_names.py", r.stderr)

    def test_missing_gw_names_json_exits_2_for_every_command(self):
        for cmd in self._all_commands():
            with self.subTest(cmd=cmd[0]):
                r = self._run_copy(["k12_check.py", "gw_names.py"], *cmd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("gw_names.json", r.stderr)

    def test_corrupt_gw_names_json_exits_2(self):
        script_dir = self.tmp / "pkg" / "scripts"
        script_dir.mkdir(parents=True, exist_ok=True)
        (script_dir / "gw_names.json").write_text("{坏的", encoding="utf-8")
        for cmd in self._all_commands():
            with self.subTest(cmd=cmd[0]):
                r = self._run_copy(["k12_check.py", "gw_names.py"], *cmd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("gw_names.json", r.stderr)

    def test_full_copy_runs(self):
        r = self._run_copy(["k12_check.py", "gw_names.py", "gw_names.json"], *self._all_commands()[4])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class ConnectorPairMaskTest(K12TestCase):
    """复审回退项：“和与及同跟”连接的两个学生姓名，两人都识别并遮蔽，连词不并入姓名，P0 不降。"""

    def test_pairs_masked_and_p0(self) -> None:
        pairs = (("程鹏", "邓景行"), ("宋向东", "李静"), ("林梓萌", "高峰"), ("彭语嫣", "苏醒"), ("邓景行", "田野"), ("卢俊豪", "黎明"))
        for first, second in pairs:
            with self.subTest(pair=(first, second)):
                p = self.write("g04_pair.txt", f"单亲家庭学生{first}和{second}参加了心理团辅。")
                code, out, err = self.run_main("general", str(p), "--json")
                report = json.loads(out)
                dump = json.dumps(report, ensure_ascii=False)
                self.assertNotIn(first, dump)
                self.assertNotIn(second, dump)
                self.assertEqual([i["level"] for i in report["issues"] if i["id"] == "K12-G04"], ["P0"])

    def test_common_nouns_after_connector_not_masked(self) -> None:
        p = self.write("g04_noun.txt", "单亲家庭学生和家庭经济困难学生参加了活动。")
        code, out, err = self.run_main("general", str(p), "--json")
        report = json.loads(out)
        self.assertEqual([i for i in report["issues"] if i["id"] == "K12-G04"], [])


if __name__ == "__main__":
    unittest.main()
