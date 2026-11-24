# -*- coding: utf-8 -*-
"""Q10：--banned 本单位禁用词表。格式见 shared/profiles/profile-template.md 第三部分。"""
from __future__ import annotations

import json
import unittest

from tests.lint.helpers import LINTER, REPO_ROOT, gl
from tests.lint.test_cli import TempDirMixin, cli

TEMPLATE = """# 禁用词

| 词语或表述 | 级别 | 原因 | 替换建议 | 适用范围 |
|---|---|---|---|---|
| 赋能 | 慎用 | 领导多次删改 | 推动、支持、提升 | 全部 |
| 全国领先 | 禁用 | 没有权威认定依据 | 写具体排名并注明来源 | 全部 |
| 高度重视 | 慎用 | 段首套话 | 直接写采取的措施 | 讲话、汇报 |
| 治愈率 100% | 禁用 | 不得作疗效保证 | 写具体病例数和随访结果 | 新闻稿、公众号 |
| 抓手、着力点 | 慎用 | 院长改稿删除 3 次 | 措施、重点 | 全部 |

## 维护记录
- 2026-05-20：建表 5 条（gongwen-profile）
"""

LIST_STYLE = """# 禁用词

## 禁用
- 拉满
- 遥遥领先：没有依据

## 慎用
- 打造（领导不喜欢）
- “闭环”

## 说明
- 本表由办公室维护
"""

TEXT = ("某局2026年工作汇报材料\n\n今年我局高度重视营商环境，排名全国领先，以数字化赋能政务服务。"
        "下一步要找准抓手，形成闭环。\n\n【起草说明】\n全国领先的说法已删去。\n")


def ban_ids(result):
    return [(i["id"], i["excerpt"]) for i in result["issues"] if i["id"].startswith("BAN-")]


class LoadBannedTest(TempDirMixin, unittest.TestCase):
    def test_template_table(self):
        terms = gl.load_banned(self.write("禁用词.md", TEMPLATE))
        by_term = {t.term: t for t in terms}
        self.assertEqual(set(by_term), {"赋能", "全国领先", "高度重视", "治愈率 100%", "抓手", "着力点"})
        self.assertTrue(by_term["全国领先"].banned)
        self.assertFalse(by_term["赋能"].banned)
        self.assertEqual(by_term["高度重视"].scope, "讲话、汇报")
        self.assertEqual(by_term["全国领先"].suggestion, "写具体排名并注明来源")
        self.assertEqual(by_term["全国领先"].source, "禁用词.md")

    def test_list_style_with_sections(self):
        terms = {t.term: t.banned for t in gl.load_banned(self.write("禁用词.md", LIST_STYLE))}
        self.assertEqual(terms, {"拉满": True, "遥遥领先": True, "打造": False, "闭环": False})

    def test_profile_eval_sample(self):
        path = REPO_ROOT / "skills" / "gongwen-profile" / "evals" / "files" / "已有禁用词（某局）.md"
        terms = {t.term: t.banned for t in gl.load_banned(path)}
        self.assertEqual(terms, {"全国领先": False, "高度重视": False, "拉满": True})

    def test_gbk_file(self):
        terms = gl.load_banned(self.write("禁用词.md", LIST_STYLE, encoding="gbk"))
        self.assertIn("拉满", {t.term for t in terms})

    def test_missing_file(self):
        with self.assertRaises(gl.InputError):
            gl.load_banned(self.tmp / "不存在.md")

    def test_term_regex(self):
        self.assertTrue(gl._term_regex("治愈率 100%").search("治愈率100%"))
        self.assertTrue(gl._term_regex("在……领导下").search("在县委的坚强领导下"))

    def test_mixed_table_and_list_merged(self):
        """表格与列表混写：两种来源的词条都保留，重复词条只留一条。"""
        text = "# 禁用词\n\n| 词语 | 级别 |\n|---|---|\n| 赋能 | 慎用 |\n\n## 禁用\n- 拉满\n- 赋能\n"
        terms = gl.load_banned(self.write("混写.md", text))
        self.assertEqual(sorted(t.term for t in terms), ["拉满", "赋能"])

    def test_section_level_resets_on_new_heading(self):
        """“## 慎用”之后的无级别标题小节回到默认级别（禁用），不沿用慎用。"""
        text = "# 禁用词\n\n## 慎用\n- 打造\n\n## 其他用词\n- 拉满\n"
        terms = {t.term: t.banned for t in gl.load_banned(self.write("级别.md", text))}
        self.assertEqual(terms, {"打造": False, "拉满": True})

    def _levels(self, text):
        return {t.term: t.banned for t in gl.load_banned(self.write("层级.md", text))}

    def test_nested_heading_inherits_level(self):
        """二级套三级：下级标题看不出级别时继承上级；同级的新标题重置。"""
        text = "## 慎用词\n### 经济类\n- 爆发式增长\n- 弯道超车\n## 禁用词\n### 政治类\n- 打擦边球\n"
        self.assertEqual(self._levels(text), {"爆发式增长": False, "弯道超车": False, "打擦边球": True})

    def test_nested_three_to_four(self):
        text = "### 慎用\n#### 甲类\n- 甲词\n#### 乙类\n- 乙词\n### 其他\n- 丙词\n"
        self.assertEqual(self._levels(text), {"甲词": False, "乙词": False, "丙词": True})

    def test_sibling_switch_and_return_to_shallow(self):
        text = ("## 慎用\n### 子类\n- 甲\n## 禁用\n- 乙\n## 慎用\n- 丙\n"
                "# 总表\n- 丁\n")
        self.assertEqual(self._levels(text), {"甲": False, "乙": True, "丙": False, "丁": True})

    def test_heading_level_skip(self):
        text = "## 慎用\n#### 深层\n- 甲\n## 其他\n- 乙\n"
        self.assertEqual(self._levels(text), {"甲": False, "乙": True})

    def test_nested_own_level_overrides_parent(self):
        text = "## 慎用\n### 其中必改\n- 甲\n### 普通\n- 乙\n"
        self.assertEqual(self._levels(text), {"甲": True, "乙": False})

    def test_descriptive_subheading_does_not_escalate(self):
        """复审指出的复现：“## 慎用词”下的子标题含“不规范”“需结合语境”等说明文字，不能把慎用升级为禁用。"""
        text = "## 慎用词\n\n### 宣传类（不规范易引发歧义，需结合语境）\n- 赋能\n- 抓手\n\n### 其他\n- 闭环\n"
        self.assertEqual(self._levels(text), {"赋能": False, "抓手": False, "闭环": False})
        terms = gl.load_banned(self.write("复现.md", text))
        result = gl.lint_text("要找准抓手，用数字化赋能，形成闭环。", "汇报材料", "style", linter=LINTER, banned=terms)
        self.assertEqual({(i["id"], i["level"]) for i in result["issues"] if i["id"].startswith("BAN-")},
                         {("BAN-002", "P2")})

    def test_explanatory_words_in_subheading_never_escalate(self):
        for sub in ("不规范", "需结合语境", "规范表述见附录", "统一口径", "规范用词", "统一表述", "规范写法",
                    "宣传类（不规范，需结合语境）", "视情况使用", "酌情", "不用赘述", "统一规范"):
            text = "## 慎用词\n### %s\n- 甲词\n" % sub
            self.assertEqual(self._levels(text), {"甲词": False}, sub)

    def test_explicit_ban_word_in_subheading_still_overrides(self):
        for sub in ("其中必改", "严禁使用", "不得使用的", "禁用类", "停用词"):
            text = "## 慎用词\n### %s\n- 甲词\n### 普通\n- 乙词\n" % sub
            self.assertEqual(self._levels(text), {"甲词": True, "乙词": False}, sub)

    def test_caution_words_in_heading(self):
        for head in ("慎用", "少用", "酌情使用", "需结合语境", "视情况而定"):
            self.assertEqual(self._levels("## %s\n- 甲\n" % head), {"甲": False}, head)

    def test_top_level_heading_without_level_word_defaults_to_ban(self):
        """没有上级级别时，说明性标题回到默认级别（禁用）；“规范用词”“不规范表述”都不改变这一点。"""
        for head in ("规范用词", "不规范表述", "本单位规范词", "统一口径"):
            self.assertEqual(self._levels("## %s\n- 甲\n" % head), {"甲": True}, head)

    def test_level_cell_and_tail_weak_signals(self):
        """级别单元格、列表项说明里：整格“规范/统一/不用”和固定搭配仍算禁用；“不规范”不算信号。"""
        text = ("## 慎用\n\n| 词语 | 级别 |\n|---|---|\n| 甲 | 规范 |\n| 乙 | 不规范 |\n| 丙 | 统一表述 |\n"
                "| 丁 | 慎用 |\n")
        self.assertEqual(self._levels(text), {"甲": True, "乙": False, "丙": True, "丁": False})
        self.assertEqual(self._levels("## 慎用\n- 戊：统一表述为某某\n- 己：不规范\n"), {"戊": True, "己": False})

    def test_no_heading_list_default(self):
        self.assertEqual(self._levels("- 甲\n- 乙（慎用）\n"), {"甲": True, "乙": False})

    def test_wildcard_crosses_enumeration_comma(self):
        regex = gl._term_regex("打造……高地")
        self.assertTrue(regex.search("打造开放、创新、协同的人才高地"))
        self.assertIsNone(regex.search("打造，开放创新，人才高地"))
        self.assertIsNone(regex.search("打造开放；人才高地"))
        self.assertIsNone(regex.search("打造开放：人才高地"))
        self.assertTrue(gl._term_regex("在……领导下").search("在县委、县政府的领导下"))

    def test_wildcard_does_not_cross_clause(self):
        regex = gl._term_regex("落实……工作")
        self.assertIsNone(regex.search("落实，搞定问题，安全工作"))
        self.assertIsNone(regex.search("落实、搞定问题：安全工作"))
        self.assertTrue(regex.search("落实安全生产工作"))
        m = regex.search("落实，搞定问题，落实安全工作")
        self.assertEqual(m.group(0), "落实安全工作")


class BannedCheckTest(TempDirMixin, unittest.TestCase):
    def test_levels_and_scope(self):
        terms = gl.load_banned(self.write("禁用词.md", TEMPLATE))
        result = gl.lint_text(TEXT, "汇报材料", "style", linter=LINTER, banned=terms)
        found = {(i["id"], i["excerpt"]): i for i in result["issues"] if i["id"].startswith("BAN-")}
        self.assertEqual(set(found), {("BAN-002", "高度重视"), ("BAN-001", "全国领先"), ("BAN-002", "赋能"),
                                      ("BAN-002", "抓手")})
        self.assertEqual(found[("BAN-001", "全国领先")]["level"], "P1")
        self.assertEqual(found[("BAN-002", "赋能")]["level"], "P2")
        self.assertEqual(found[("BAN-001", "全国领先")]["check"], "style")
        self.assertEqual(found[("BAN-001", "全国领先")]["basis"], "本单位禁用词表（禁用词.md）")
        self.assertEqual(found[("BAN-002", "赋能")]["suggestion"], "推动、支持、提升")
        # 适用范围“讲话、汇报”：通知中不比对“高度重视”
        result = gl.lint_text(TEXT, "通知", "style", linter=LINTER, banned=terms)
        self.assertNotIn(("BAN-002", "高度重视"), ban_ids(result))
        self.assertTrue(any("适用范围" in n for n in result["notes"]))

    def test_not_run_without_style(self):
        terms = gl.load_banned(self.write("禁用词.md", TEMPLATE))
        result = gl.lint_text(TEXT, "汇报材料", "punct", linter=LINTER, banned=terms)
        self.assertEqual(ban_ids(result), [])
        self.assertTrue(any("禁用词表没有比对" in n for n in result["notes"]))

    def test_without_banned_option(self):
        self.assertEqual(ban_ids(gl.lint_text(TEXT, "汇报材料", "style", linter=LINTER)), [])

    def test_marker_and_drafting_note_ignored(self):
        terms = gl.load_banned(self.write("禁用词.md", LIST_STYLE))
        result = gl.lint_text("检查【待补：是否形成闭环】。\n\n【起草说明】\n拉满。\n", "其他", "style",
                              linter=LINTER, banned=terms)
        self.assertEqual(ban_ids(result), [])

    def test_cli(self):
        banned = self.write("禁用词.md", TEMPLATE)
        doc = self.write("正文.txt", TEXT)
        code, out, _err = cli(str(doc), "--doc-type", "汇报材料", "--banned", str(banned), "--json", "--strict")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("BAN-001", [i["id"] for i in data["issues"]])
        self.assertTrue(any("已比对本单位禁用词表" in n for n in data["notes"]))

    def test_cli_missing_banned_file_returns_2(self):
        doc = self.write("正文.txt", TEXT)
        code, _out, err = cli(str(doc), "--banned", str(self.tmp / "不存在.md"))
        self.assertEqual(code, 2)
        self.assertIn("禁用词文件不存在", err)


if __name__ == "__main__":
    unittest.main()
