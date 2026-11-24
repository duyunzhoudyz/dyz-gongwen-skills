# -*- coding: utf-8 -*-
"""K12-G04（学生隐私）复审问题的引擎层回归与新增测试。

背景：K12-G04 接入共享姓名模块后，“单亲家庭学生陈子豪近期情绪波动较大。”“特困学生王建国获得资助。”
在 HEAD（d07b657）能报 P0、接入后不报（HEAD 只认“张王李赵刘陈杨黄周吴”10 个姓，接入后锚点要求身份词后紧跟姓名且右边界是标点）。
本轮把锚点拆成 K12_ROLE（身份词 + 角色名词，4 分）和 K12_BARE（身份词后直接接姓名，3 分），并取消右边界一票否决。

这里的测试都走引擎（k12_check 的 general / parents / comments 子命令），不直接调共享模块：
1. 点名句子的实测结果；
2. HEAD 对照（写死基线）：同一名字集、同一句式，命中数与 P0 数不低于 HEAD；HEAD 能做到的 10 个姓必须全报 P0；
3. 按语境分组的召回下限（实测向下取整到 5%）；召回用句式与留出集（复审人的“近期情绪低落”“获得资助”）不同的自拟后续；
4. 不应报的汇总、政策、职责写法；
5. 并列名单的泄露检查（文本与 --json 输出都不含姓名）；
6. 文件名回显遮蔽；
7. looks_like_name 仍走旧口径（has_surname_prefix）；examples/D 三条命令输出逐字一致。
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest

from tests.names.masking import check_masked_outputs
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "gongwen-k12" / "scripts"
FIXTURES = REPO_ROOT / "tests" / "names" / "fixtures"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import k12_check  # noqa: E402


# ---------------------------------------------------------------------------
# 夹具与小工具
# ---------------------------------------------------------------------------
def read_list(path: Path) -> List[str]:
    out = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _parse_given_names() -> Tuple[str, List[str]]:
    section, surnames, givens = "", "", []  # type: str, str, List[str]
    for raw in (FIXTURES / "given_names.txt").read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or (line.startswith("#") and not line.startswith("##")):
            continue
        if line.startswith("##"):
            section = line.lstrip("#").strip()
            continue
        if section == "姓":
            surnames += line
        elif section == "单字名":
            givens += list(line)
        elif section == "两字名":
            givens += line.split()
    return surnames, givens


def generated_names() -> List[str]:
    """60 个常见姓 × 名字用字，按固定步长抽样（四分之一），可复现。"""
    surnames, givens = _parse_given_names()
    out: List[str] = []
    for i, s in enumerate(surnames):
        for j, g in enumerate(givens):
            if (i * 7 + j) % 4 == 0:
                out.append(s + g)
    return list(dict.fromkeys(out))


def name_sets() -> Dict[str, List[str]]:
    return {"夹具名": read_list(FIXTURES / "names.txt"),
            "程序化生成": generated_names(),
            "人工名": read_list(FIXTURES / "manual_names.txt")}


class EngineCase(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="k12_name_review_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name: str, text: str) -> Path:
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_main(self, *args: str):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = k12_check.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def general_json(self, text: str, name: str = "g.txt") -> dict:
        p = self.write(name, text if text.endswith("\n") else text + "\n")
        code, out, err = self.run_main("general", str(p), "--json")
        self.assertIn(code, (0, 1), err)
        return json.loads(out)

    def g04(self, text: str) -> List[dict]:
        return [i for i in self.general_json(text)["issues"] if i["id"] == "K12-G04"]

    def per_name(self, template: str, names: Sequence[str]) -> Dict[str, dict]:
        """每个姓名套一次句式、各占一行、整批跑一次 general；返回 {姓名: K12-G04 问题}。"""
        text = "\n".join(template.format(n=n) for n in names) + "\n"
        data = self.general_json(text, "batch.txt")
        by_line = {i["line"]: i for i in data["issues"] if i["id"] == "K12-G04"}
        return {names[ln - 1]: it for ln, it in by_line.items()}


# ---------------------------------------------------------------------------
# 1. 点名句子的实测结果
# ---------------------------------------------------------------------------
class NamedSentencesTest(EngineCase):

    REPORTED_P0 = (
        ("单亲家庭学生陈子豪近期情绪波动较大。", "单亲家庭学生〔姓名1〕近期情绪波动较大"),
        ("特困学生王建国获得资助。", "特困学生〔姓名1〕获得资助。"),
        ("对低保家庭学生周梓涵、吴雨桐等5人发放助学金。", "低保家庭学生〔姓名1〕、〔姓名2〕等5人发放助学金"),
        ("对低保家庭学生周梓涵（三年级）、吴雨桐（五年级）发放助学金。",
         "低保家庭学生〔姓名1〕（三年级）、〔姓名2〕（五年级）发放助"),
    )
    NOT_REPORTED = (
        "特困学生：高一、高二各2人。",
        "孤儿学生：雷锋班、焦裕禄班各1人。",
        "建档立卡户学生：高一（3）班、高二（5）班各2人。",
        "本学期，学校对留守儿童、单亲家庭学生和家庭经济困难学生建立了一人一档。",
        "家庭经济困难，母亲长期无业。",
        "低保家庭学生名单：七年级、八年级，详见附表",
        "本学期特困学生：一年级、三年级各2人",
        "特困学生名单已按规定渠道报送。",
        "违纪处分政策学习王主任作专题辅导。",
        "同学们积极参与低保政策宣传。",
        # 自拟的 10 句学校常见汇总、政策、职责类写法（含各种年级班级称谓）
        "特困学生：初一、初二各3人。",
        "留守儿童：九年级（2）班、九年级（4）班共12人。",
        "单亲家庭学生：实验班、火箭班各2人，已建档。",
        "孤儿学生：少先队大队部已安排结对帮扶。",
        "低保家庭学生分布在七年级、八年级和九年级，共计18人。",
        "学校严格落实建档立卡户学生资助政策，做到应助尽助。",
        "特困学生由班主任和心理教师共同负责，定期家访。",
        "困难家庭学生认定工作由学生资助中心牵头。",
        "留守儿童之家已建成，覆盖全体留守儿童。",
        "单亲家庭学生的心理健康问题引起了学校高度重视。",
        "孤儿学生：高三（1）班、高三（2）班各1人。",
        "低保家庭学生：高一年级12人、高二年级9人。",
        "特困学生：初三（1）班、重点班各2人。",
        "特困学生资助标准由县教育局会同财政局制定。",
    )

    def test_named_sentences_are_p0_and_masked(self):
        for sentence, excerpt in self.REPORTED_P0:
            with self.subTest(s=sentence):
                issues = self.g04(sentence)
                self.assertEqual([i["level"] for i in issues], ["P0"])
                self.assertEqual(issues[0]["excerpt"], excerpt)

    def test_summary_policy_and_duty_sentences_are_not_reported(self):
        for sentence in self.NOT_REPORTED:
            with self.subTest(s=sentence):
                self.assertEqual(self.g04(sentence), [])

    def test_grade_and_class_words_are_not_names_in_lists_with_identity_word(self):
        # 年级、班名里首字恰是姓氏（高一、高二、初一的“高”，“雷锋班”“焦裕禄班”）：不当姓名
        for words in ("高一、高二", "高三、初三", "雷锋班、焦裕禄班", "实验班、火箭班"):
            with self.subTest(w=words):
                self.assertEqual(self.g04(f"特困学生：{words}各2人。"), [])

    def test_conjunct_items_with_one_non_name_in_the_middle_do_not_leak(self):
        # 并列中夹一个非姓名项：共享模块的并列识别在非姓名项处停下，引擎沿“、”项继续看，后面的姓名同样遮蔽
        cases = (
            ("对低保家庭学生周梓涵、三年级、吴雨桐发放助学金。", ("周梓涵", "吴雨桐")),
            ("对低保家庭学生周梓涵、实验班、吴雨桐等5人发放助学金。", ("周梓涵", "吴雨桐")),
            ("低保家庭学生周梓涵、七年级（2）班、孙浩宇（三年级）发放助学金", ("周梓涵", "孙浩宇")),
            ("低保家庭学生周梓涵、高一（3）班、吴雨桐。", ("周梓涵", "吴雨桐")),
        )
        for sentence, names in cases:
            with self.subTest(s=sentence):
                data = self.general_json(sentence)
                issues = [i for i in data["issues"] if i["id"] == "K12-G04"]
                self.assertEqual([i["level"] for i in issues], ["P0"])
                blob = json.dumps(data, ensure_ascii=False)
                for n in names:
                    self.assertNotIn(n, blob)
                self.assertGreaterEqual(issues[0]["excerpt"].count("〔姓名"), 2)

    def test_known_limit_first_item_is_not_a_name(self):
        # 已知局限（如实断言现状）：身份词后第一项就是非姓名项（“高一、周梓涵、吴雨桐”）时没有起点，整句不报
        self.assertEqual(self.g04("对低保家庭学生高一、周梓涵、吴雨桐发放助学金。"), [])


# ---------------------------------------------------------------------------
# 2. HEAD 对照（引擎层）
# ---------------------------------------------------------------------------
class HeadBaselineTest(EngineCase):

    def test_engine_not_below_head_on_fixture_names(self):
        """tests/names/fixtures/head_baseline.json 里 K12-G04 各句式的 HEAD（d07b657）数字写死在夹具里；
        同一名字集（names.txt 408 个）、同一句式，引擎层 general 命中数与 P0 数不得低于 HEAD。"""
        base = json.loads((FIXTURES / "head_baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(base["commits"]["HEAD"][:7], "d07b657")
        names = read_list(FIXTURES / "names.txt")
        self.assertEqual(len(names), base["names_count"])
        rows = [r for r in base["rows"] if r["engine"] == "k12"]
        self.assertEqual(len(rows), 4)
        lines = ["", "引擎层 K12-G04 与 HEAD 基线对照（names.txt 408 名；命中数，括号内 P0）："]
        for row in rows:
            got = self.per_name(row["template"], names)
            found = len(got)
            p0 = sum(1 for i in got.values() if i["level"] == "P0")
            head = row["HEAD"]
            lines.append(f"  {row['template']}：HEAD {head['detected']}（P0 {head['p0']}）→ 现 {found}（P0 {p0}）")
            self.assertGreaterEqual(found, head["detected"], f"{row['template']}：命中 {found} 低于 HEAD {head['detected']}")
            self.assertGreaterEqual(p0, head["p0"], f"{row['template']}：P0 {p0} 低于 HEAD {head['p0']}")
        sys.stderr.write("\n".join(lines) + "\n")

    def test_head_only_knew_ten_surnames_and_all_of_them_are_p0_now(self):
        """HEAD 只认“张王李赵刘陈杨黄周吴”10 个姓；这 10 个姓 × 20 个常见名套三种句式，新实现必须全部报 P0。"""
        surnames = "张王李赵刘陈杨黄周吴"
        givens = ["子豪", "建国", "梓涵", "雨桐", "志强", "小明", "思远", "欣怡", "浩然", "晓东",
                  "佳怡", "文博", "秀英", "丽华", "伟", "芳", "磊", "静", "勇", "婷"]
        names = [s + g for s in surnames for g in givens]
        self.assertEqual(len(names), 200)
        for template in ("单亲家庭学生{n}近期情绪低落。", "特困学生{n}获得资助。", "低保家庭学生{n}本学期获得资助。"):
            with self.subTest(t=template):
                got = self.per_name(template, names)
                not_p0 = [n for n in names if n not in got or got[n]["level"] != "P0"]
                self.assertEqual(not_p0, [])
                for n in names:
                    self.assertNotIn(n, got[n]["excerpt"])


# ---------------------------------------------------------------------------
# 3. 按语境分组的召回（引擎层）
# ---------------------------------------------------------------------------
# 每组若干句式（句式里的整数是应出现的姓名占位符个数）。后续用语都是自拟的，不用留出集的“近期情绪低落”“获得资助”“发放”。
GROUPS: Dict[str, List[Tuple[str, int]]] = {
    "身份+学生+标点": [("低保家庭学生{n}。", 1), ("单亲家庭学生{n}，已多次家访。", 1)],
    "身份+学生+时间词": [("单亲家庭学生{n}昨日请假。", 1), ("特困学生{n}本学期转入我校。", 1)],
    "身份+学生+功能字": [("低保家庭学生{n}在校住宿。", 1), ("孤儿学生{n}已转学。", 1)],
    "身份+学生+词表外动词": [("留守儿童{n}拒绝参加活动。", 1), ("特困学生{n}私自离校。", 1),
                      ("低保家庭学生{n}接受心理辅导。", 1)],
    "并列名单与等N人": [("对低保家庭学生周梓涵、{n}等5人发放助学金。", 2), ("对特困学生{n}、吴雨桐等5人发放助学金。", 2),
                  ("低保家庭学生{n}、吴雨桐、郑浩然已纳入资助。", 3)],
    "括注并列": [("低保家庭学生周梓涵（三年级）、{n}（五年级）已纳入资助。", 2),
             ("对特困学生{n}（三年级）、吴雨桐（五年级）发放助学金。", 2)],
    "同学后缀": [("单亲家庭的{n}同学近期情绪低落。", 1), ("低保家庭{n}同学获得资助。", 1)],
}
FIXED_NAMES = ("周梓涵", "吴雨桐", "郑浩然")

# (召回率下限, P0 比例下限)：实测值向下取整到 5%（2026-11 实测见各行注释）
FLOORS: Dict[str, Dict[str, Tuple[float, float]]] = {
    "身份+学生+标点": {"夹具名": (0.95, 0.95), "程序化生成": (0.95, 0.95), "人工名": (1.00, 1.00)},
    "身份+学生+时间词": {"夹具名": (0.90, 0.90), "程序化生成": (0.95, 0.95), "人工名": (0.75, 0.75)},
    "身份+学生+功能字": {"夹具名": (0.90, 0.90), "程序化生成": (0.95, 0.95), "人工名": (0.75, 0.75)},
    "身份+学生+词表外动词": {"夹具名": (0.90, 0.80), "程序化生成": (0.95, 0.95), "人工名": (0.70, 0.45)},
    "并列名单与等N人": {"夹具名": (0.95, 0.95), "程序化生成": (0.95, 0.95), "人工名": (0.90, 0.90)},
    "括注并列": {"夹具名": (0.95, 0.95), "程序化生成": (0.95, 0.95), "人工名": (1.00, 1.00)},
    "同学后缀": {"夹具名": (0.95, 0.95), "程序化生成": (0.95, 0.95), "人工名": (1.00, 1.00)},
}


class ContextRecallTest(EngineCase):

    def measure(self, group: str, names: Sequence[str]) -> Tuple[int, int, int, List[str]]:
        """返回 (总次数, 识别次数, 其中 P0 次数, 漏掉的“姓名@句式”)。识别 = 摘录里没有原名，且遮蔽占位符个数符合句式。"""
        names = [n for n in names if n not in FIXED_NAMES]
        total = found = p0 = 0
        missed: List[str] = []
        for template, count in GROUPS[group]:
            got = self.per_name(template, names)
            for n in names:
                total += 1
                it = got.get(n)
                if it and n not in it["excerpt"] and it["excerpt"].count("〔姓名") == count:
                    found += 1
                    if it["level"] == "P0":
                        p0 += 1
                else:
                    missed.append(f"{n}@{template}")
        return total, found, p0, missed

    def test_recall_by_context_group(self):
        sets = name_sets()
        lines = ["", "引擎层 K12-G04 按语境分组召回（识别率 / P0 比例）："]
        for group in GROUPS:
            for set_name, names in sets.items():
                total, found, p0, missed = self.measure(group, names)
                recall, p0_rate = found / total, p0 / total
                floor_recall, floor_p0 = FLOORS[group][set_name]
                lines.append(f"  {group} / {set_name}：{recall:.3f} / {p0_rate:.3f}（下限 {floor_recall:.2f} / {floor_p0:.2f}，样本 {total}）")
                with self.subTest(group=group, names=set_name):
                    self.assertGreaterEqual(recall, floor_recall, f"识别率 {recall:.3f}；漏：{' '.join(missed[:12])}")
                    self.assertGreaterEqual(p0_rate, floor_p0, f"P0 比例 {p0_rate:.3f}")
        sys.stderr.write("\n".join(lines) + "\n")

    def test_no_name_is_ever_left_in_an_excerpt(self):
        # 不管识别率多少：只要报了 K12-G04，摘录里就不能原样带出这个语境里的姓名
        sets = name_sets()
        for group, templates in GROUPS.items():
            for template, _count in templates:
                for set_name, names in sets.items():
                    names = [n for n in names if n not in FIXED_NAMES]
                    got = self.per_name(template, names)
                    leaked = [n for n, it in got.items() if n in it["excerpt"]]
                    with self.subTest(group=group, t=template, names=set_name):
                        self.assertEqual(leaked, [])


# ---------------------------------------------------------------------------
# 4. K12_SENS 增加“受到……处分的”（学生、同学之前）
# ---------------------------------------------------------------------------
class PunishmentIdentityTest(EngineCase):

    def test_named_punished_student_is_reported_and_masked(self):
        for sentence in ("受到警告处分的学生孙浩宇", "受到处分的学生孙浩宇已写出检查。", "受到记过处分的李明同学",
                         "受到处分的学生：孙浩宇、李明轩。"):
            with self.subTest(s=sentence):
                data = self.general_json(sentence)
                issues = [i for i in data["issues"] if i["id"] == "K12-G04"]
                self.assertEqual([i["level"] for i in issues], ["P0"])
                blob = json.dumps(data, ensure_ascii=False)
                for n in ("孙浩宇", "李明轩", "李明"):
                    self.assertNotIn(n, blob)

    def test_summary_and_duty_sentences_with_punished_students_are_not_reported(self):
        for sentence in ("受到处分的学生名单已按规定报送。", "对受过处分的学生开展帮扶：班主任、心理教师负责。",
                         "受到处分的学生共3人，已谈话。", "受到处分的同学们要认真反思。",
                         "受到处分的张老师已调岗。", "受到处分的教师王某某。", "他曾受过处分，现已改正。"):
            with self.subTest(s=sentence):
                self.assertEqual(self.g04(sentence), [])

    def test_known_limit_student_before_the_punishment(self):
        # 已知局限：“该生因打架受到处分”这类身份词和姓名不相邻的写法不报
        self.assertEqual(self.g04("孙浩宇因打架受到处分，已写出检查。"), [])


# ---------------------------------------------------------------------------
# 5. 文件名回显遮蔽
# ---------------------------------------------------------------------------
class FilenameMaskTest(EngineCase):

    BODY = "低保家庭学生马小明已落实资助。\n学校拟公布马小明的考试成绩排名。\n"

    def check(self, mode: str, filename: str, text: str, *extra: str):
        p = self.write(filename, text)
        code_t, out_t, _ = self.run_main(mode, str(p), *extra)
        code_j, out_j, _ = self.run_main(mode, str(p), *extra, "--json")
        self.assertIn(code_t, (0, 1))
        self.assertIn(code_j, (0, 1))
        return out_t, json.loads(out_j), out_j

    def test_general_masks_recognized_name_in_filename(self):
        out_t, data, out_j = self.check("general", "马小明家访记录.txt", self.BODY)
        self.assertEqual(data["file"], "〔姓名1〕家访记录.txt")
        self.assertIn("校内综合文书检查：〔姓名1〕家访记录.txt", out_t)
        self.assertNotIn("马小明", out_t)
        self.assertNotIn("马小明", out_j)

    def test_parents_masks_recognized_name_in_filename(self):
        out_t, data, out_j = self.check("parents", "给马小明家长的信.txt", self.BODY)
        self.assertEqual(data["file"], "给〔姓名1〕家长的信.txt")
        self.assertNotIn("马小明", out_t)
        self.assertNotIn("马小明", out_j)

    def test_comments_masks_label_name_in_filename(self):
        text = "马小明：你太笨了，要多努力。\nS02：你很聪明，这学期进步明显。\n"
        out_t, data, out_j = self.check("comments", "评语_马小明.txt", text, "--min-chars", "0")
        self.assertEqual(data["file"], "评语_〔姓名1〕.txt")
        self.assertIn("评语_〔姓名1〕.txt", out_t)
        self.assertNotIn("评语_马小明", out_t)
        self.assertNotIn("评语_马小明", out_j)

    def test_known_limit_name_only_in_filename_is_not_masked(self):
        # 已知局限：文件名里有、正文没识别到的姓名遮不住（文档字符串与 README 已写明）
        out_t, data, _ = self.check("general", "赵小四家访记录.txt", "本学期完成家访32人次。\n")
        self.assertEqual(data["file"], "赵小四家访记录.txt")
        self.assertIn("赵小四家访记录.txt", out_t)

    def test_name_in_filename_is_masked_for_parents_without_other_issues(self):
        p = self.write("马小明.txt", "单亲家庭的马小明同学需要关注。\n")
        code, out, _ = self.run_main("parents", str(p))
        self.assertEqual(code, 0)
        self.assertNotIn("马小明", out)


# ---------------------------------------------------------------------------
# 6. mask / unmask 的识别口径不变
# ---------------------------------------------------------------------------
class LooksLikeNameUnchangedTest(unittest.TestCase):

    def test_looks_like_name_still_uses_has_surname_prefix(self):
        gw, lex = k12_check.shared_names()
        samples = ("刘海", "林海", "黎明", "高峰", "欧阳", "欧阳明", "王和平", "马会芳", "周行", "张山", "宁静", "安然",
                   "王小明", "李华", "张老", "上官婉儿", "雷锋班", "高一", "三年级", "实验班")
        for word in samples:
            if word in k12_check.NOT_NAMES or any(word.endswith(s) for s in k12_check.NOT_NAME_SUFFIXES) and word not in k12_check.COMPOUND_SURNAMES:
                continue
            with self.subTest(word=word):
                self.assertEqual(k12_check.looks_like_name(word), bool(gw.has_surname_prefix(word, lex)))

    def test_differs_from_shared_looks_like_name_on_purpose(self):
        # 共享模块的 looks_like_name 对整词排除词（刘海）、复姓本身（欧阳）返回 False；
        # mask/unmask 沿用旧口径（只看姓氏开头），识别结果不随共享数据调整而变
        gw, lex = k12_check.shared_names()
        for word in ("刘海", "林海", "欧阳"):
            with self.subTest(word=word):
                self.assertFalse(gw.looks_like_name(word, lex))
        self.assertTrue(k12_check.looks_like_name("刘海"))
        self.assertTrue(k12_check.looks_like_name("林海"))


class ExampleDRegressionTest(EngineCase):
    """examples/D 三条命令（mask、comments、unmask）的输出须与该目录现有文件逐字一致（忽略换行符差异）。"""

    @staticmethod
    def norm(path: Path) -> str:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_example_d_outputs_are_identical(self):
        src = next(p for p in (REPO_ROOT / "examples").iterdir() if p.name.startswith("D-"))
        for f in src.iterdir():
            if f.is_file():
                shutil.copyfile(f, self.tmp / f.name)
        facts_csv = self.tmp / "输入-五年级二班学生事实表.csv"
        code, _out, err = self.run_main("mask", str(facts_csv), "--drop-sensitive")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.norm(self.tmp / "输入-五年级二班学生事实表-脱敏.md"), self.norm(src / "1-本机脱敏事实表.md"))
        self.assertEqual(self.norm(self.tmp / "输入-五年级二班学生事实表-对照表.csv"), self.norm(src / "对照表-仅本机留存示意.csv"))
        code, out, err = self.run_main("comments", str(self.tmp / "2-模型生成评语-编号版.txt"),
                                       "--facts", str(self.tmp / "1-本机脱敏事实表.md"), "--strict")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.replace("\r\n", "\n"), self.norm(src / "3-评语机检报告.txt"))
        code, _out, err = self.run_main("unmask", str(self.tmp / "2-模型生成评语-编号版.txt"),
                                        str(self.tmp / "对照表-仅本机留存示意.csv"))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.norm(self.tmp / "2-模型生成评语-编号版-姓名版.txt"), self.norm(src / "4-本机还原姓名版.txt"))





class MarkdownNameTableTest(EngineCase):
    def test_parent_document_reports_table_privacy(self) -> None:
        path = self.write("王秀英回访单.md", "| 学生姓名 | 病史 |\n| --- | --- |\n| 王秀英 | 哮喘 |\n")
        def run():
            code, output, err = self.run_main("parents", str(path), "--json", "--strict")
            self.assertEqual(code, 1, err)
            text_code, screen, text_err = self.run_main("parents", str(path), "--strict")
            self.assertEqual(text_code, 1, text_err)
            return json.loads(output), screen

        report, _ = check_masked_outputs(k12_check.shared_names()[0], run)
        rows = [(i["id"], i["level"], i["excerpt"]) for i in report["issues"]]
        self.assertEqual(rows, [("K12-G04", "P0", "〔姓名1〕")])
        self.assertEqual(report["file"], "〔姓名1〕回访单.md")

    def run_table(self, name, body):
        return check_masked_outputs(k12_check.shared_names()[0], lambda: self._run_table(name, body))

    def _run_table(self, name, body):
        path = self.tmp / name
        path.write_text(body, encoding="utf-8")
        code, out, err = self.run_main("general", str(path), "--json")
        text_code, rendered, text_err = self.run_main("general", str(path))
        self.assertEqual(code, text_code)
        self.assertIn(code, (0, 1), err + text_err)
        return json.loads(out), rendered

    def test_sensitive_and_ordinary_rows_keep_document_numbering(self) -> None:
        body = ("| 学生姓名 | 困难类型 |\n| --- | --- |\n| 王秀英 | 低保 |\n\n"
                "| 姓名 | 序号 |\n| --- | --- |\n| 王秀英 | 1 |\n| 欧阳明月 | 2 |\n")
        report, screen = self.run_table("王秀英附表.md", body)
        rows = [(i["id"], i["level"], i["line"], i["excerpt"]) for i in report["issues"]
                if i["id"] == "K12-G04"]
        self.assertEqual(rows, [("K12-G04", "P0", 3, "〔姓名1〕"),
                                ("K12-G04", "P1", 7, "〔姓名1〕"),
                                ("K12-G04", "P1", 8, "〔姓名2〕")])
        self.assertEqual(report["file"], "〔姓名1〕附表.md")
        for word in ("王秀英", "欧阳明月"):
            self.assertNotIn(word, json.dumps(report, ensure_ascii=False))
            self.assertNotIn(word, screen)
        for _, _, _, excerpt in rows:
            self.assertIn(excerpt, screen)
        sys.stderr.write(f"\nk12 表格姓名正例：命中 {len(rows)}/3。\n")

    def test_absent_public_and_nonnames_are_not_registered(self) -> None:
        controls = [
            ("王秀英", "| 编号 | 心理 |\n| --- | --- |\n| 王秀英 | 记录 |\n"),
            ("王秀英", "| 联系人姓名 | 心理 |\n| --- | --- |\n| 王秀英 | 记录 |\n"),
        ]
        controls.extend((cell, f"| 姓名 | 心理 |\n| --- | --- |\n| {cell} | 记录 |\n")
                        for cell in ("合计", "小计", "无", "/", "—", "高一", "五年级", "宣传科", "123"))
        misfires = 0
        for name, body in controls:
            with self.subTest(name=name, body=body):
                file_name = ("斜线" if name == "/" else name) + "附表.md"
                report, screen = self.run_table(file_name, body)
                rows = [i for i in report["issues"] if i["id"] == "K12-G04"]
                misfires += len(rows)
                self.assertEqual(rows, [])
                self.assertEqual(report["file"], file_name)
                self.assertNotIn("〔姓名", screen)
        sys.stderr.write(f"\nk12 表格姓名反例：误报 {misfires}/{len(controls)}。\n")

if __name__ == "__main__":
    unittest.main()
