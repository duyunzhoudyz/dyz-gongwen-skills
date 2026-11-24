# -*- coding: utf-8 -*-
"""shared/scripts/gw_clause.py 的测试：切分、各豁免窗口、豁免词归类、程序倒置组合判定。

运行：python -m unittest discover -s tests/names -t .

覆盖：
  1. 切分与窗口：clause、prev、lead、prefix、sentence 各自的范围（after 窗口已取消）；
  2. 方案 5.2 的每个类别（禁止、否定事实、调查引述、处置定性、出处、目标、称号）在每个窗口的生效与不生效；
  3. 程序倒置：组合判定的命中一律为 P1（收缩后不再产生 P0）、是不是同一事项、事后正常事项、reason_code；
     如实声明降级只作用于正则 P0 命中，且只看同一句与紧邻前后句（Declaration.adjust）；
  4. 豁免的语境检查（让步、例外、定语、禁止否定目的成分、指他、出处未出具）。

收缩（负责人决定，不再加规则）留下的已知代价，在本文件里有明确断言（KnownCostTest）：
  处置类只在命中所在分句内生效，出处类只在命中所在分句与紧邻的前一分句内生效；
  否决、整改、出处写在命中之后的分句里时，豁免不再生效，该句会重新被报出。
"""
from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path
from typing import List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared" / "scripts"


def _load(mod_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


gc = _load("_t_gw_clause_src", SHARED / "gw_clause.py")


def span(text: str, hit: str, nth: int = 0) -> tuple:
    idx = -1
    for _ in range(nth + 1):
        idx = text.index(hit, idx + 1)
    return idx, idx + len(hit)


def exempt(text: str, hit: str, cats: Sequence[str], prefix_window: int = 8) -> Optional[str]:
    s, e = span(text, hit)
    return gc.find_exemption(text, s, e, cats, prefix_window)


class SplitAndWindowTest(unittest.TestCase):
    def test_split_sentences_and_clauses(self) -> None:
        text = "甲，乙：丙；丁。戊"
        self.assertEqual([text[a:b] for a, b in gc.split_sentences(text)], ["甲，乙：丙", "丁", "戊"])
        self.assertEqual([text[c.start:c.end] for c in gc.split_clauses(text)], ["甲", "乙", "丙", "丁", "戊"])
        self.assertEqual([c.delim for c in gc.split_clauses(text)], ["，", "：", "；", "。", ""])
        self.assertEqual(gc.split_clauses(""), [])
        self.assertEqual(gc.split_clauses("，，。"), [])

    def test_windows_basic(self) -> None:
        text = "前句。巡察指出问题，经研判，该做法属于违规：先行开工，已整改，未再发生。下一句"
        s, e = span(text, "先行开工")
        w = gc.compute_windows(text, s, e)
        self.assertEqual(w.clause, "先行开工")
        self.assertEqual(w.prev, "该做法属于违规")
        self.assertEqual(w.lead, "该做法属于违规")
        self.assertFalse(hasattr(w, "after"))    # 收缩：命中之后的分句不再是豁免窗口
        self.assertEqual(w.sentence, "巡察指出问题，经研判，该做法属于违规：先行开工，已整改，未再发生")
        self.assertEqual(w.prefix, "")

    def test_prev_only_crosses_soft_separators(self) -> None:
        text = "上一句。本句命中处"
        s, e = span(text, "命中处")
        self.assertEqual(gc.compute_windows(text, s, e).prev, "")
        text2 = "上一分句；本句命中处"
        s, e = span(text2, "命中处")
        self.assertEqual(gc.compute_windows(text2, s, e).prev, "上一分句")
        text3 = "引导：本句命中处"
        s, e = span(text3, "命中处")
        w = gc.compute_windows(text3, s, e)
        self.assertEqual((w.prev, w.lead), ("引导", "引导"))
        text4 = "引导，本句命中处"
        s, e = span(text4, "命中处")
        w = gc.compute_windows(text4, s, e)
        self.assertEqual((w.prev, w.lead), ("引导", ""))

    def test_after_window_is_gone(self) -> None:
        self.assertNotIn("after", gc.WINDOW_NAMES)
        self.assertNotIn("after", gc.Windows._fields if hasattr(gc.Windows, "_fields") else gc.Windows.__dataclass_fields__)
        for cat in ("dispose", "source"):
            self.assertNotIn("after", gc.CATEGORY_SPEC[cat])
        self.assertEqual(set(gc.CATEGORY_SPEC["dispose"]), {"clause"})
        self.assertEqual(set(gc.CATEGORY_SPEC["source"]), {"clause", "prev"})

    def test_hit_spanning_clauses_takes_all_spanned(self) -> None:
        text = "甲乙，丙丁，戊己"
        s = text.index("乙")
        e = text.index("丁") + 1
        w = gc.compute_windows(text, s, e)
        self.assertEqual(w.clause, "甲乙，丙丁")

    def test_prefix_window_size_and_clause_bound(self) -> None:
        text = "一二三四五六七八九十命中"
        s, e = span(text, "命中")
        self.assertEqual(gc.compute_windows(text, s, e).prefix, "三四五六七八九十")
        self.assertEqual(gc.compute_windows(text, s, e, 16).prefix, "一二三四五六七八九十")
        text2 = "严禁甲，二三命中"
        s, e = span(text2, "命中")
        self.assertEqual(gc.compute_windows(text2, s, e, 16).prefix, "二三")  # 不跨分句

    def test_hit_on_separator_does_not_crash(self) -> None:
        text = "甲，乙"
        w = gc.compute_windows(text, 1, 2)
        self.assertEqual(w.clause, "甲")
        self.assertEqual(gc.compute_windows("", 0, 0).clause, "")


class IsExemptTest(unittest.TestCase):
    def test_patterns_by_window(self) -> None:
        text = "严禁下列行为：先行开工后补办手续。"
        s, e = span(text, "先行开工")
        self.assertTrue(gc.is_exempt(text, s, e, {"lead": r"严禁"}))
        self.assertFalse(gc.is_exempt(text, s, e, {"clause": r"严禁"}))
        self.assertFalse(gc.is_exempt(text, s, e, {"prefix": r"严禁"}))
        self.assertTrue(gc.is_exempt(text, s, e, {"sentence": r"严禁"}))
        self.assertTrue(gc.is_exempt(text, s, e, {"clause": None, "lead": re.compile("严禁")}))
        self.assertFalse(gc.is_exempt(text, s, e, {}))

    def test_prefix_window_parameter(self) -> None:
        text = "严禁在没有经过集体研究的情况下先行开工"
        s, e = span(text, "先行开工")
        self.assertFalse(gc.is_exempt(text, s, e, {"prefix": "严禁"}, prefix_window=8))
        self.assertTrue(gc.is_exempt(text, s, e, {"prefix": "严禁"}, prefix_window=16))

    def test_unknown_window_and_category(self) -> None:
        with self.assertRaises(ValueError):
            gc.is_exempt("甲乙", 0, 1, {"nowhere": "甲"})
        with self.assertRaises(ValueError):
            gc.is_exempt("甲乙", 0, 1, {"after": "乙"})     # after 窗口已取消
        with self.assertRaises(ValueError):
            gc.find_exemption("甲乙", 0, 1, ["nope"])
        with self.assertRaises(ValueError):
            gc.category_patterns(["nope"])

    def test_category_patterns_merge(self) -> None:
        pats = gc.category_patterns(["prohibit", "dispose"])
        # 禁止类用 chain、lead、chain_prefix（顿号并列的分句串），处置类只用 clause
        self.assertEqual(set(pats), {"chain", "lead", "chain_prefix", "clause"})
        text = "先行开工已整改"
        s, e = span(text, "先行开工")
        self.assertTrue(gc.is_exempt(text, s, e, pats))

    def test_extra_patterns_labelled(self) -> None:
        text = "另见说明，先行开工"
        s, e = span(text, "先行开工")
        self.assertEqual(gc.find_exemption(text, s, e, [], extra={"prev": "另见"}), "extra")
        self.assertIsNone(gc.find_exemption(text, s, e, ["prohibit"]))


class CategoryWindowTest(unittest.TestCase):
    """方案 5.2：每个类别在每个窗口的生效与不生效。"""

    # 禁止：clause、lead、prefix 生效；prev、after 不生效
    def test_prohibit_clause(self) -> None:
        self.assertEqual(exempt("严禁先行开工后补办手续。", "先行开工", ["prohibit"]), "prohibit")

    def test_prohibit_lead(self) -> None:
        self.assertEqual(exempt("严禁下列行为：先行开工后补办手续。", "先行开工", ["prohibit"]), "prohibit")

    def test_prohibit_prefix(self) -> None:
        self.assertEqual(exempt("严格规定不得在未批准时先行开工", "先行开工", ["prohibit"]), "prohibit")

    def test_prohibit_not_in_prev_or_after(self) -> None:
        self.assertIsNone(exempt("严禁违规操作，先行开工后补办手续。", "先行开工", ["prohibit"]))
        self.assertIsNone(exempt("先行开工后补办手续，严禁。", "先行开工", ["prohibit"]))
        self.assertIsNone(exempt("先行开工。严禁。", "先行开工", ["prohibit"]))

    def test_prohibit_all_words(self) -> None:
        for w in ("严禁", "禁止", "不得", "杜绝", "防止", "严防", "避免", "不能", "不应"):
            self.assertEqual(exempt(f"{w}先行开工", "先行开工", ["prohibit"]), "prohibit", w)

    # 否定事实：prefix 生效；“不存在”“未发现”另在 clause 生效；其余词在 clause 不生效
    def test_negation_prefix(self) -> None:
        for w in ("尚未", "未", "没有"):
            self.assertEqual(exempt(f"本院{w}先行开工", "先行开工", ["negation"]), "negation", w)

    def test_negation_clause_words(self) -> None:
        text = "经自查，不存在大量违规的情况，其中先行开工并无一例"
        self.assertEqual(exempt("不存在设备采购前先行开工的情形", "先行开工", ["negation"], prefix_window=2), "negation")
        self.assertEqual(exempt("未发现设备采购前先行开工的情形", "先行开工", ["negation"], prefix_window=2), "negation")
        self.assertIsNone(exempt(text, "先行开工", ["negation"], prefix_window=2))

    def test_negation_plain_words_not_in_clause_far_before(self) -> None:
        self.assertIsNone(exempt("没有按期完成设备采购的情况下先行开工", "先行开工", ["negation"]))
        self.assertIsNone(exempt("先行开工，没有", "先行开工", ["negation"]))
        self.assertIsNone(exempt("没有问题，先行开工", "先行开工", ["negation"]))

    # 调查引述：只看 clause
    def test_investigate_clause_only(self) -> None:
        self.assertEqual(exempt("审计发现本院调整诊断编码提高CMI", "调整诊断编码提高CMI", ["investigate"]), "investigate")
        self.assertEqual(exempt("存在先行开工问题", "先行开工", ["investigate"]), "investigate")
        for w in ("自查", "检查发现", "反馈", "巡察", "专项检查", "筛查", "排查", "核查", "线索", "监测", "稽核", "举报"):
            self.assertEqual(exempt(f"{w}涉及先行开工", "先行开工", ["investigate"]), "investigate", w)

    def test_investigate_not_in_other_windows(self) -> None:
        text = "经审计发现，本院拟通过调整诊断编码提高CMI。"
        self.assertIsNone(exempt(text, "调整诊断编码提高CMI", ["investigate"]))
        self.assertIsNone(exempt("巡察指出问题：先行开工", "先行开工", ["investigate"]))
        self.assertIsNone(exempt("先行开工，经巡察反馈", "先行开工", ["investigate"]))
        self.assertIsNone(exempt("巡察反馈。先行开工", "先行开工", ["investigate"]))

    # 处置、定性：只在命中所在分句（clause）生效；prev、lead、后续分句都不生效
    def test_dispose_clause_only(self) -> None:
        self.assertEqual(exempt("先行开工已整改到位", "先行开工", ["dispose"]), "dispose")
        text = "医院对个别科室提出的调整主要诊断编码以提高CMI的建议予以否决。"
        self.assertEqual(exempt(text, "调整主要诊断编码以提高CMI", ["dispose"]), "dispose")
        self.assertEqual(exempt("有科室建议分解住院降低次均费用，该做法违规。", "分解住院降低次均费用", ["dispose"]), None)

    def test_dispose_not_in_prev_lead_or_next_clause(self) -> None:
        self.assertIsNone(exempt("该做法已整改到位，建议调整主要诊断编码以提高CMI。", "调整主要诊断编码以提高CMI", ["dispose"]))
        self.assertIsNone(exempt("予以否决：调整主要诊断编码以提高CMI。", "调整主要诊断编码以提高CMI", ["dispose"]))
        self.assertIsNone(exempt("建议调整主要诊断编码以提高CMI。医院已予以否决。", "调整主要诊断编码以提高CMI", ["dispose"]))
        # 收缩：后一分句里的处置不再豁免（见 KnownCostTest）
        self.assertIsNone(exempt("建议调整主要诊断编码以提高CMI，医院已予以否决。", "调整主要诊断编码以提高CMI", ["dispose"]))

    def test_dispose_negated_violation_does_not_count(self) -> None:
        text = "建议调整主要诊断编码以提高CMI，不违规。"
        self.assertIsNone(exempt(text, "调整主要诊断编码以提高CMI", ["dispose"]))
        self.assertIsNone(exempt("建议调整诊断编码以提高CMI，以改善结余。", "调整诊断编码以提高CMI", ["dispose"]))
        self.assertIsNone(exempt("建议调整诊断编码以提高CMI，无违规风险。", "调整诊断编码以提高CMI", ["dispose"]))
        self.assertIsNone(exempt("建议调整诊断编码以提高CMI，存在违规风险。", "调整诊断编码以提高CMI", ["dispose"]))
        self.assertIsNone(exempt("建议调整诊断编码以提高CMI，该做法违反规定。", "调整诊断编码以提高CMI", ["dispose"]))    # 后一分句：收缩后不豁免
        self.assertEqual(exempt("建议调整诊断编码以提高CMI违反规定", "调整诊断编码以提高CMI", ["dispose"]), "dispose")      # 同分句才豁免

    def test_dispose_words(self) -> None:
        for w in ("否决", "不予采纳", "未予采纳", "未采纳", "不予支持", "未予支持", "不予同意", "予以纠正", "已纠正",
                  "整改到位", "整改完毕", "已整改", "完成整改", "已全部整改", "立行立改", "已叫停", "予以叫停", "已查处",
                  "属于违规", "不符合规定"):
            self.assertEqual(exempt(f"先行开工{w}。", "先行开工", ["dispose"]), "dispose", w)

    # 出处：clause、prev 生效（命中所在分句与紧邻的前一分句）；后续分句、跨句都不生效
    def test_source_windows(self) -> None:
        self.assertEqual(exempt("经省科技厅鉴定该技术国内领先", "国内领先", ["source"]), "source")
        self.assertEqual(exempt("经省科技厅鉴定，该技术国内领先", "国内领先", ["source"]), "source")
        self.assertEqual(exempt("发布的榜单显示名列前茅，该技术国内领先。", "国内领先", ["source"]), "source")
        # 收缩：出处写在命中之后的分句，不再豁免（见 KnownCostTest）
        self.assertIsNone(exempt("该技术国内领先，经省科技厅鉴定。", "国内领先", ["source"]))
        self.assertIsNone(exempt("该技术国内领先，发布的榜单显示名列前茅。", "国内领先", ["source"]))

    def test_source_not_across_sentences(self) -> None:
        self.assertIsNone(exempt("经省科技厅鉴定。该技术国内领先。", "国内领先", ["source"]))
        self.assertIsNone(exempt("该技术国内领先。经省科技厅鉴定。", "国内领先", ["source"]))

    # 目标：clause、lead 生效；prev（逗号）、after 不生效
    def test_target_clause_and_lead(self) -> None:
        self.assertEqual(exempt("力争降低次均费用", "降低次均费用", ["target"]), "target")
        self.assertEqual(exempt("明年目标：降低次均费用", "降低次均费用", ["target"]), "target")
        for w in ("力争", "争取", "目标", "愿景", "致力于", "计划", "拟"):
            self.assertEqual(exempt(f"{w}降低次均费用", "降低次均费用", ["target"]), "target", w)

    def test_target_not_in_prev_or_after(self) -> None:
        self.assertIsNone(exempt("力争完成，降低次均费用", "降低次均费用", ["target"]))
        self.assertIsNone(exempt("降低次均费用，力争完成", "降低次均费用", ["target"]))

    # 称号：只看 clause
    def test_title_clause_only(self) -> None:
        self.assertEqual(exempt("王某同志同志荣誉称号", "荣誉", ["title"]), "title")
        for w in ("同志", "先进", "优秀", "党员", "烈士", "称号"):
            self.assertEqual(exempt(f"{w}代表", "代表", ["title"]), "title", w)
        self.assertIsNone(exempt("优秀员工，荣誉代表", "荣誉代表", ["title"]))
        self.assertIsNone(exempt("荣誉代表，优秀员工", "荣誉代表", ["title"]))

    def test_multiple_categories_return_first_effective(self) -> None:
        text = "严禁先行开工已整改"
        self.assertEqual(exempt(text, "先行开工", ["dispose", "prohibit"]), "dispose")
        self.assertEqual(exempt(text, "先行开工", ["prohibit", "dispose"]), "prohibit")


# ---------------------------------------------------------------------------
# 程序倒置
# ---------------------------------------------------------------------------
def inv(*lines: str, rule_id: str = "HOS-034", cfg: Optional[dict] = None) -> List[dict]:
    conf = {"rule_id": rule_id}
    conf.update(cfg or {})
    return gc.find_inversions(list(lines), conf)


def lv(*lines: str, **kw) -> List[str]:
    return [r["level"] for r in inv(*lines, **kw)]


class ChainWindowTest(unittest.TestCase):
    """禁止类、否定类豁免遇顿号并列：并列各项共享前面的“杜绝”“严禁”“尚未”；逗号分开的分句仍各自独立。"""

    def test_chain_window_spans_enumeration_commas(self) -> None:
        text = "要杜绝先行开工、先行签约等现象。"
        s, e = span(text, "先行签约")
        win = gc.compute_windows(text, s, e)
        self.assertEqual(win.chain, "要杜绝先行开工、先行签约等现象")
        self.assertEqual(win.clause, "先行签约等现象")
        self.assertIn("杜绝", win.chain_prefix)
        self.assertNotIn("杜绝", win.clause)

    def test_chain_stops_at_comma_and_colon(self) -> None:
        text = "要杜绝先行开工，先行签约、先行付款问题。"
        s, e = span(text, "先行付款")
        self.assertEqual(gc.compute_windows(text, s, e).chain, "先行签约、先行付款问题")
        # chain 只往前并入顿号连着的各项，不往后：第一项只有自己
        self.assertEqual(gc.compute_windows(text, *span(text, "先行签约")).chain, "先行签约")

    def test_prohibit_across_dun_hao(self) -> None:
        text = "要杜绝先行开工、先行签约等现象。"
        for target in ("先行开工", "先行签约"):
            self.assertEqual(exempt(text, target, ["prohibit"]), "prohibit", target)
        self.assertEqual(exempt("严禁先行开工、先行签约、先行付款。", "先行付款", ["prohibit"]), "prohibit")
        self.assertEqual(exempt("不得违规采购、先行开工和先行签约。", "先行开工", ["prohibit"]), "prohibit")

    def test_prohibit_lead_for_second_item(self) -> None:
        text = "严禁下列行为：先行开工、先行签约。"
        s, e = span(text, "先行签约")
        self.assertEqual(gc.compute_windows(text, s, e).lead, "严禁下列行为")
        self.assertEqual(exempt(text, "先行签约", ["prohibit"]), "prohibit")

    def test_comma_clauses_stay_independent(self) -> None:
        # “杜绝”只管本分句；逗号后面的分句不受它保护
        self.assertIsNone(exempt("要杜绝违规问题，先行开工的项目已经上线。", "先行开工", ["prohibit"]))
        self.assertIsNone(exempt("落实，搞定问题", "搞定", ["prohibit"]))
        self.assertIsNone(exempt("要杜绝违规，先行开工、先行签约等做法仍然存在。", "先行签约", ["prohibit"]))
        self.assertIsNone(exempt("严禁违规。先行开工、先行签约。", "先行签约", ["prohibit"]))

    def test_negation_across_dun_hao(self) -> None:
        text = "尚未开工、先行签约等事项均已纠正。"
        self.assertEqual(exempt(text, "先行签约", ["negation"]), "negation")
        self.assertIsNone(exempt("尚未开工，先行签约事项已经办理。", "先行签约", ["negation"]))

    def test_other_categories_unchanged_by_chain(self) -> None:
        # 调查引述类仍只看 clause：顿号前面的“自查发现”不外溢
        self.assertIsNone(exempt("自查发现问题、先行开工、先行签约。", "先行签约", ["investigate"]))
        self.assertEqual(exempt("自查发现先行开工。", "先行开工", ["investigate"]), "investigate")


class DeclarationTest(unittest.TestCase):
    """如实声明的统一口径（gw_clause.Declaration）：就近（同句、前后句）声明时处置类豁免不适用；
    就近有肯定式声明且没有追认补办，正则 P0 降 P1；不再有全文级降级。"""

    CFG = {"rule_id": "SOE-001"}

    def test_near_declared_covers_same_previous_and_next_sentence(self) -> None:
        lines = ["特此如实报告。", "项目已于9月先行开工。该做法违反了规定。", "其他内容。", "无关的一句。"]
        d = gc.Declaration(lines, self.CFG)
        self.assertTrue(d.near_declared(1, lines[1].index("先行开工")))   # 下一句“该做法违反了规定”是肯定式声明
        self.assertFalse(d.near_declared(3, 0))
        self.assertTrue(gc.Declaration(["项目已先行开工，属于程序倒置。"], self.CFG).near_declared(0, 3))
        # “特此如实报告”不再算声明：只有它时，前一句、后一句、本句都不算 near
        only = ["特此如实报告。", "项目已于9月先行开工。", "无关的一句。"]
        d2 = gc.Declaration(only, self.CFG)
        self.assertFalse(d2.near_declared(1, 3))
        self.assertFalse(d2.near_declared(0, 0))

    def test_adjust_p0_to_p1_when_declared_nearby(self) -> None:
        lines = ["项目已于9月先行开工，该做法违反了规定，属于程序倒置，现如实报告。"]
        d = gc.Declaration(lines, self.CFG)
        self.assertEqual(d.adjust("P0", 0, 6), "P1")
        self.assertEqual(d.adjust("P1", 0, 6), "P1")
        self.assertEqual(d.adjust("P2", 0, 6), "P2")

    def test_normalize_nearby_keeps_p0(self) -> None:
        lines = ["项目已于9月先行开工，属于程序倒置，现如实报告，并提请董事会追认。"]
        d = gc.Declaration(lines, self.CFG)
        self.assertEqual(d.adjust("P0", 0, 6), "P0")

    def test_no_document_level_downgrade(self) -> None:
        """收缩：不再有全文级降级。声明只在本句、前一句、后一句起作用；隔两句以上的声明不降级。"""
        lines = ["一、情况", "项目已于9月先行开工。", "二、进展", "项目先行开工后累计完成形象进度25%。",
                 "三、声明", "以上程序倒置情况，如实报告。", "四、其他", "该项目已先行开工的部分将按规定处理。"]
        d = gc.Declaration(lines, self.CFG)
        self.assertFalse(hasattr(d, "doc_declared"))
        for idx in (1, 3, 7):
            self.assertEqual(d.adjust("P0", idx, 1), "P0", idx)
        self.assertEqual(d.adjust("P0", 4, 0), "P1")    # “三、声明”紧邻声明句，就近口径照常降级

    def test_find_inversions_are_always_p1(self) -> None:
        lines = ["项目已于9月先行开工，现提请董事会审议。", "中间若干行。", "该项目已先行开工，现提请董事会审议。",
                 "以上情况属于程序倒置，如实报告。"]
        rows = gc.find_inversions(lines, self.CFG)
        self.assertEqual([(r["line"], r["level"]) for r in rows], [(1, "P1"), (3, "P1")])
        self.assertEqual([r["reason_code"] for r in rows], ["same_sentence", "declared"])
        self.assertFalse(rows[0]["declared"])   # 声明不在本句、前后句：处置类豁免仍然适用
        self.assertTrue(rows[1]["declared"])    # 第 3 行紧邻第 4 行的声明
        rows = gc.find_inversions(lines + ["现补办手续。"], self.CFG)
        self.assertEqual([r["level"] for r in rows], ["P1", "P1"])

    def test_unrelated_honest_wording_is_not_a_declaration(self) -> None:
        """别处的“如实说明”“如实报告”与程序倒置无关，不算声明；肯定式声明在前一句或后一句才算。"""
        lines = ["一、要求", "要求各部门如实说明整改情况，如实报告安全生产情况。", "二、项目", "该项目已于9月开工建设，现提请董事会审议。"]
        rows = gc.find_inversions(lines, self.CFG)
        self.assertEqual([(r["line"], r["level"], r["reason_code"]) for r in rows], [(4, "P1", "same_sentence")])
        self.assertFalse(rows[0]["declared"])
        rows = gc.find_inversions(["特此如实说明。", "该项目已于9月开工建设，现提请董事会审议。"], self.CFG)
        self.assertEqual([r["reason_code"] for r in rows], ["same_sentence"])
        rows = gc.find_inversions(["以上程序倒置情况，如实说明。", "该项目已于9月开工建设，现提请董事会审议。"], self.CFG)
        self.assertEqual([r["reason_code"] for r in rows], ["declared"])
        # 明确指称程序问题的肯定式用语算声明
        for decl in ("以上程序倒置情况，请予知悉。", "本项目未履行决策程序。", "本项目程序上存在瑕疵。", "该事项系先执行后决策。"):
            d2 = gc.Declaration(lines + [decl], self.CFG)
            self.assertTrue(d2.declared_in(decl), decl)
            self.assertEqual(d2.adjust("P0", 3, 1), "P1", decl)

    def test_declared_flag_in_results(self) -> None:
        rows = gc.find_inversions(["设备已先行采购，属于程序倒置，现提请董事会审议。"], self.CFG)
        self.assertEqual((rows[0]["level"], rows[0]["declared"]), ("P1", True))
        rows = gc.find_inversions(["设备已先行采购，现提请董事会审议。"], self.CFG)
        self.assertEqual((rows[0]["level"], rows[0]["declared"]), ("P1", False))    # 组合判定一律 P1

    def test_negation_covers_pronoun_to_phrase_and_eight_chars_before(self) -> None:
        """否定检查覆盖“指代词到‘程序倒置’之间及其前 8 字”（还有匹配之后到分句末）：这些都不是声明，P0 照旧。"""
        base = "项目已于9月先行开工，现提请董事会补办审批手续。"
        for tail in ("上述做法不属于程序倒置。", "经核查，上述事项不存在程序倒置。", "该项目未发生程序倒置。",
                     "此前已就程序倒置问题开展了自查。", "坚决杜绝程序倒置。", "上述情况并非程序倒置。", "以上情况不是程序倒置。",
                     "各单位要防止出现先执行后决策问题。", "严禁以上程序倒置。", "该做法不构成程序倒置。"):
            with self.subTest(tail=tail):
                d = gc.Declaration([base + tail], self.CFG)
                self.assertFalse(d.declared_in(tail))
                self.assertEqual(d.adjust("P0", 0, 6), "P0")

    def test_affirmative_declaration_adjacent_sentences(self) -> None:
        # 同一句或紧邻前后句有肯定式声明、且这三句没有追认补办 -> P1
        for lines in (["项目已于9月先行开工，属于程序倒置，现如实报告。"],
                      ["设备已先行采购。", "以上情况属于程序倒置，由会议决定后续处理。"],
                      ["以上情况属于程序倒置，由会议决定后续处理。", "设备已先行采购。"]):
            with self.subTest(lines=lines):
                d = gc.Declaration(lines, self.CFG)
                k = 0 if "先行" in lines[0] else 1
                self.assertEqual(d.adjust("P0", k, lines[k].index("先行")), "P1")
        # 三句范围内有追认、补办 -> 保持 P0（包括前一句）
        d = gc.Declaration(["现补报审批手续。", "项目已于9月先行开工，属于程序倒置，现如实报告。"], self.CFG)
        self.assertEqual(d.adjust("P0", 1, 6), "P0")
        d = gc.Declaration(["工程已先行开工，现提请审议工程投资方案。以上情况系程序倒置，现报请追认。"], self.CFG)
        self.assertEqual(d.adjust("P0", 0, 3), "P0")


class InversionTest(unittest.TestCase):
    def test_same_sentence_is_p1_only(self) -> None:
        """收缩：组合判定一律 P1，不再产生 P0（P0 只来自各包的正则）。"""
        for text in ("本项目设备已于9月采购到位并投入使用，现提请院长办公会审议。",
                     "该项目已于2026年9月开工建设，现提请董事会审议。",
                     "已签约，现提请董事会审议",
                     "项目已先行开工建设，现提请董事会审议。",
                     "设备已先行采购，现补办审批手续。",
                     "合同已签订，提请党委会研究决定。"):
            with self.subTest(text=text):
                self.assertEqual(lv(text), ["P1"])

    def test_not_reported(self) -> None:
        for text in ("巡察反馈的先采购后报批问题，已于9月整改到位。",
                     "已完成论证，拟提交党委会议研究。",
                     "本项目尚未开工，现提请董事会审议。",
                     "已于9月召开职代会审议通过，现提请董事会审议。",
                     "经董事会审议通过后已开工建设。现提请董事会审议。",
                     "经董事会审议通过后已开工，现提请董事会备案。",
                     "严禁下列行为：先行开工后补办手续。",
                     "项目未已开工，现提请董事会审议。",
                     "请严禁已开工项目再提请追加审批。",
                     "本项目已开工。"):
            with self.subTest(text=text):
                self.assertEqual(inv(text), [])

    def test_p1_next_sentence(self) -> None:
        r = inv("本项目已开工建设。现提请董事会审议。")
        self.assertEqual([x["level"] for x in r], ["P1"])
        self.assertIn("邻句", r[0]["reason"])

    def test_p1_next_line_adjacent_only(self) -> None:
        self.assertEqual(lv("本项目已开工建设", "现提请董事会审议"), ["P1"])
        self.assertEqual(lv("本项目已开工建设", "", "现提请董事会审议"), [])
        self.assertEqual(lv("本项目已开工建设", "其他内容", "现提请董事会审议"), [])

    def test_declaration_changes_reason_only(self) -> None:
        for text in ("设备已先行采购，属于程序倒置，现如实报告，现提请董事会审议。",
                     "已先行实施后决策，属先实施后决策，提请董事会审议。",
                     "设备已先行采购，该做法违反了采购管理规定，现提请董事会审议。",
                     "设备已先行采购，未履行决策程序，现提请董事会审议。"):
            with self.subTest(text=text):
                self.assertEqual([(r["level"], r["reason_code"]) for r in inv(text)], [("P1", "declared")])
        # 只写“如实说明”“如实报告”不算声明
        for text in ("设备已先行采购，现如实说明，提请董事会审议。", "设备已先行采购，如实报告，现提请董事会审议。"):
            self.assertEqual([(r["level"], r["reason_code"]) for r in inv(text)], [("P1", "same_sentence")])

    def test_declaration_in_previous_or_next_sentence(self) -> None:
        self.assertEqual([r["reason_code"] for r in inv("特此如实报告。设备已先行采购，现提请董事会审议。")], ["same_sentence"])
        self.assertEqual([r["reason_code"] for r in inv("以上程序倒置情况特此如实报告。设备已先行采购，现提请董事会审议。")], ["declared"])
        self.assertEqual([r["reason_code"] for r in inv("设备已先行采购，现提请董事会审议。以上程序倒置情况如实说明。")], ["declared"])

    def test_normalize_is_p1_with_normalize_code(self) -> None:
        """追认、补办的 P0 由各包的正则负责；组合判定对写了追认、补办的句子只给 P1（reason_code normalize）。"""
        for text in ("设备已先行采购，属于程序倒置，现如实报告，并提请董事会追认。",
                     "设备已先行采购，属于程序倒置，如实报告，现补办审批手续。",
                     "本项目已开工。如实报告：现补办立项手续。"):
            with self.subTest(text=text):
                self.assertEqual([(r["level"], r["reason_code"]) for r in inv(text)], [("P1", "normalize")])

    def test_other_object_downgrades_to_p1(self) -> None:
        self.assertEqual(lv("一期已开工，现提请审议二期方案。"), ["P1"])
        self.assertEqual(lv("项目已投入使用，现提请审议追加投资方案。"), ["P1"])
        self.assertEqual(lv("项目已投入使用，现提请审议调整方案。"), ["P1"])

    def test_exec_negation_and_prior_ok(self) -> None:
        self.assertEqual(inv("防止已签约项目再次提请审议。"), [])
        self.assertEqual(inv("董事会批准后已开工，现提请审议预算。"), [])

    def test_exec_verbs_and_lookahead(self) -> None:
        self.assertEqual(inv("已完成方案论证，现提请董事会审议。"), [])
        self.assertEqual(inv("已采购方案编制服务，现提请审议。"), [])
        self.assertEqual(lv("已采购设备三批，现提请审议。"), ["P1"])
        self.assertEqual(inv("已实施前期调研，现提请董事会审议。"), [])
        self.assertEqual(lv("已经付款，现提请党委会审议。"), ["P1"])
        # EXEC 允许“已”与动词之间有“全部、基本、陆续、分批”
        for text in ("物资已全部采购到位，特提请审议。", "设备已基本安装，现提请审议。", "项目已陆续开工，现提请审议。", "设备已分批采购，现提请审议。"):
            self.assertEqual(lv(text), ["P1"], text)

    def test_result_fields(self) -> None:
        text = "前文。该项目已于2026年9月开工建设，现提请董事会审议。后文。"
        r = inv("无关行", text, rule_id="SOE-001")
        self.assertEqual(len(r), 1)
        row = r[0]
        self.assertEqual((row["id"], row["line"], row["level"]), ("SOE-001", 2, "P1"))
        self.assertEqual(text[row["start"]:row["end"]], "已于2026年9月开工建设，现提请董事会审议")
        self.assertEqual(row["excerpt"], text[row["start"]:row["end"]])
        self.assertTrue(row["reason"])

    def test_default_rule_id_and_multiple_lines(self) -> None:
        r = gc.find_inversions(["已签约，现提请董事会审议。", "无关。", "设备已安装，现补办手续。"], {})
        self.assertEqual([(x["id"], x["line"]) for x in r], [("HOS-034", 1), ("HOS-034", 3)])
        self.assertEqual(gc.find_inversions([], {}), [])
        self.assertEqual(gc.find_inversions(["", "   "], None), [])

    def test_cfg_overrides(self) -> None:
        cfg = {"exec": r"已盖章", "req": r"申请入库"}
        self.assertEqual(lv("文件已盖章，现申请入库。", cfg=cfg), ["P1"])
        # 提请对象是备案这类事后正常事项（POST_OBJ），不报
        self.assertEqual(lv("文件已盖章，现申请备案。", cfg={"exec": r"已盖章", "req": r"申请备案"}), [])
        self.assertEqual(lv("已签约，现提请董事会审议。", cfg=cfg), [])

    def test_excerpt_clipped(self) -> None:
        rows = inv("项目已开工，" + "甲" * 100 + "，现提请董事会审议。")
        self.assertEqual(len(rows), 1)
        self.assertLessEqual(len(rows[0]["excerpt"]), 80)

    def test_one_result_per_exec_sentence(self) -> None:
        r = inv("已签约，已付款，现提请董事会审议，现提请党委会审议。")
        self.assertEqual(len(r), 1)


TRUE_INVERSION = "本项目设备已于9月采购到位并投入使用，现提请院长办公会审议。"


class InversionSameMatterTest(unittest.TestCase):
    """方案 5(a)：是不是同一事项。已执行成分作定语、提请的是另一件事、事后正常事项，都不报或只给 P1。"""

    def test_attributive_exec_is_skipped(self) -> None:
        for text in ("已建成的信息系统运行良好，现提请院长办公会审议年度预算。",
                     "已投入使用的信息系统需要升级改造，现提请院长办公会审议升级方案。",
                     "去年已采购的CT设备运行良好，现提请审议新购MRI设备事项。",
                     "已签订的框架协议执行良好，现提请董事会审议续签事项。",
                     "公司已签订了的合同共12份，现提请董事会审议年度预算。"):
            with self.subTest(text=text):
                self.assertEqual(inv(text), [])

    def test_different_matter_is_not_reported(self) -> None:
        for text in ("我院已建成胸痛中心，现提请院长办公会审议创建卒中中心的实施方案。",
                     "医院已采购CT设备，现提请审议新购MRI设备事项。",
                     "公司已建成一期厂房，现提请董事会审议筹建研发中心事项。"):
            with self.subTest(text=text):
                self.assertEqual(inv(text), [])

    def test_empty_or_contained_object_with_new_marker_is_p1(self) -> None:
        self.assertEqual(lv("一期已开工，现提请审议二期方案。"), ["P1"])
        self.assertEqual(inv("一期已开工，现提请审议二期方案。")[0]["reason_code"], "other_item")
        self.assertEqual(lv("已采购CT设备，现提请审议追加CT设备采购方案。"), ["P1"])    # 已执行对象包含在提请对象里
        self.assertEqual(lv("项目已投入使用，现提请审议调整方案。"), ["P1"])

    def test_post_events_are_not_reported_unless_ratification(self) -> None:
        self.assertEqual(inv("项目已建成，现提请审议竣工决算。"), [])
        self.assertEqual(inv("项目已投入运营，现提请董事会审议绩效评价报告。"), [])
        self.assertEqual(inv("项目已完工，现提请董事会审议验收事项。"), [])
        self.assertEqual(inv("经董事会审议通过后已开工，现提请董事会备案。"), [])
        self.assertEqual(lv("项目已建成，现提请追认竣工决算。"), ["P1"])     # 追认：仍给提示，但组合判定只给 P1

    def test_normal_post_topics_are_not_reported(self) -> None:
        """POST_OBJ 补充：收费标准、管理办法、制度、细则、报废、处置、编制、计划、预算、方案调整、运行情况、使用情况。"""
        for text in ("食堂已投入使用，现提请审议食堂收费标准。",
                     "设备已于去年按程序采购并投入使用，现提请审议设备报废处置事项。",
                     "设备已采购到位，现提请审议设备使用管理办法。",
                     "信息系统已于去年上线，现提请审议数据安全管理制度。",
                     "公司已签订年度供货框架协议，现提请审议2027年采购计划。",
                     "我院已与某高校签订合作办学协议，现提请审议附属医院人员编制方案。",
                     "项目已投入使用，现提请审议运行情况。",
                     "设备已采购到位，现提请审议使用情况。",
                     "项目已开工，现提请审议年度预算。",
                     "项目已开工，现提请审议实施细则。"):
            with self.subTest(text=text):
                self.assertEqual(inv(text), [])
        # 提请对象里有追认、补办时，事后正常事项的例外不适用
        self.assertEqual(lv("设备已先行采购，现提请追认设备使用管理办法。"), ["P1"])

    def test_unsure_cases_are_p1_not_p0(self) -> None:
        self.assertEqual(lv("本项目已开工建设。现提请董事会审议。"), ["P1"])          # 邻句
        self.assertEqual(lv("一期已开工，现提请审议后续方案。"), ["P1"])


class InversionExecTiersTest(unittest.TestCase):
    """方案 5(b)：EXEC 分两档（E1～E4 强档，E5 弱档“于X月……”）；收缩后两档都只报 P1，区别只在提示文案。"""

    def test_strong_tier_variants(self) -> None:
        for text in ("医院已与供应商签订采购合同，现提请院长办公会审议。",                              # E2
                     "信息科已完成设备采购和安装调试，现提请院长办公会审议。",                          # E3
                     "物资公司已与供应商签订钢材采购合同，金额3200万元，会议同意提请董事会审议该采购事项。",
                     "该项目于2026年9月开工建设，目前主体工程已完成30%，现提请审议。",                 # E3（百分比）
                     "该项目9月份已开始施工，现将有关情况报请审议。",                                   # E4 + REQ“现将……报请”
                     "项目施工单位已于9月进场作业，现提请审议。",                                       # E4
                     TRUE_INVERSION):                                                                  # E1
            with self.subTest(text=text):
                self.assertEqual(lv(text), ["P1"])
                self.assertNotEqual(inv(text)[0]["reason_code"], "weak_exec")

    def test_p1_tier_dated_without_yi(self) -> None:
        rows = inv("本项目设备于9月采购到位并投入使用，现提请院长办公会审议。")
        self.assertEqual([r["level"] for r in rows], ["P1"])
        self.assertEqual(rows[0]["reason_code"], "weak_exec")
        self.assertEqual(lv("该项目于2026年9月先行开工，现提请董事会审议。"), ["P1"])

    def test_future_and_requirement_words_cancel_dated_tier(self) -> None:
        for w in ("计划", "拟", "预计", "将", "争取", "力争", "准备", "要求", "应当", "应", "须", "确保", "力求", "预定", "定"):
            with self.subTest(word=w):
                self.assertEqual(inv(f"项目{w}于9月开工建设，现提请院长办公会审议。"), [])
        # 前 4 字内才算：“设备于9月”里的“备”不是否定词
        self.assertEqual(lv("设备于9月采购到位，现提请审议。"), ["P1"])

    def test_negative_lookahead_and_framework_words(self) -> None:
        for text in ("医院已与供应商签订战略合作协议，现提请院长办公会审议。",
                     "医院已与供应商签订框架协议，现提请院长办公会审议。",
                     "医院已与供应商签订意向书，现提请院长办公会审议。",
                     "医院已与供应商签订保密协议，现提请院长办公会审议。",
                     "已完成设备采购需求论证，现提请院长办公会审议。",
                     "已采购可研报告编制服务，现提请院长办公会审议。",
                     "已完成采购管理办法的修订，现提请院长办公会审议。",
                     "医院已完成《采购管理办法》修订稿，拟于11月提请院长办公会审议。",
                     "医院已实施管理制度，现提请审议。",
                     "项目已完成竣工决算，现提请审议。"):
            with self.subTest(text=text):
                self.assertEqual(inv(text), [])

    def test_req_now_will_report_variant(self) -> None:
        self.assertEqual(lv("该项目已进场施工，现将有关情况提请院长办公会审议。"), ["P1"])
        self.assertEqual(lv("该项目已进场施工，现将该事项报送党委会研究。"), ["P1"])

    def test_loosened_request_wording(self) -> None:
        """既然只报 P1，提请表述放宽：请予审议、请审议、提交……会议审议、特提请。"""
        for text in ("项目已开工建设，请予审议。", "项目已开工建设，请审议。", "项目已开工建设，提交本次会议审议。",
                     "项目已开工建设，提交董事会审议。", "物资已全部采购到位，特提请审议。", "已签约，现提请董事会审议。"):
            with self.subTest(text=text):
                self.assertEqual(lv(text), ["P1"])

    def test_book_title_marks_block_done_pattern(self) -> None:
        self.assertEqual(inv("已完成《设备采购管理办法》修订，现提请审议。"), [])


class InversionDeclarationTest(unittest.TestCase):
    """方案 5(c)（收缩后）：声明只认肯定式；被否定的、套话、另段的都不触发降级；组合判定本身恒为 P1，声明只换提示文案。"""

    def test_affirmative_forms_are_declared(self) -> None:
        for decl in ("属于程序倒置", "系先执行后决策", "存在先实施后决策问题", "以上程序倒置情况", "上述先执行后决策的做法",
                     "该事项未履行决策程序", "该项目程序上存在瑕疵", "该做法违反了投资管理规定", "此行为违反了有关制度"):
            with self.subTest(decl=decl):
                self.assertEqual([r["reason_code"] for r in inv(f"设备已先行采购，{decl}，现提请董事会审议。")], ["declared"])

    def test_negated_or_generic_declarations_are_not_declared(self) -> None:
        for decl in ("各单位要坚决杜绝程序倒置", "要防止出现先执行后决策问题", "严禁以上程序倒置", "本院不存在程序倒置",
                     "现将有关情况如实报告如下", "特此如实说明", "未发现程序倒置", "上述做法不属于程序倒置", "该项目未发生程序倒置"):
            with self.subTest(decl=decl):
                self.assertEqual([r["reason_code"] for r in inv(f"设备已先行采购，{decl}，现提请董事会审议。")], ["same_sentence"])

    def test_far_declaration_does_not_count(self) -> None:
        # 另段、隔两句以上的声明或套话：不影响（不再有全文级降级）
        self.assertEqual([r["reason_code"] for r in inv(TRUE_INVERSION, "二、要求", "各单位要坚决杜绝程序倒置。")], ["same_sentence"])
        self.assertEqual([r["reason_code"] for r in inv(TRUE_INVERSION, "三、说明", "以上程序倒置情况，如实报告。")], ["same_sentence"])
        d = gc.Declaration([TRUE_INVERSION, "二、其他", "本项目程序上存在瑕疵。"], {})
        self.assertEqual(d.adjust("P0", 0, 3), "P0")

    def test_normalize_and_regex_hit_adjust(self) -> None:
        self.assertEqual([r["reason_code"] for r in inv("设备已先行采购，属于程序倒置，现提请追认。")], ["normalize"])
        d = gc.Declaration(["项目已于9月先行开工，该做法违反了投资管理规定，属于程序倒置，现如实报告。"], {})
        self.assertEqual(d.adjust("P0", 0, 6), "P1")
        d2 = gc.Declaration(["项目已于9月先行开工，现如实报告。"], {})
        self.assertEqual(d2.adjust("P0", 0, 6), "P0")      # 只有“如实报告”不降级


class InversionReasonCodeTest(unittest.TestCase):
    """方案 5(e)：P1 带 reason_code，引擎据此换文案。"""

    def code(self, *lines: str) -> List[str]:
        return [r["reason_code"] for r in inv(*lines)]

    def test_codes(self) -> None:
        self.assertEqual(self.code(TRUE_INVERSION), ["same_sentence"])
        self.assertEqual(self.code("设备已先行采购，属于程序倒置，现提请董事会审议。"), ["declared"])
        self.assertEqual(self.code(TRUE_INVERSION, "三、说明", "本项目程序上存在瑕疵。"), ["same_sentence"])    # 隔两行：不算就近
        self.assertEqual(self.code("设备已先行采购，现提请追认。"), ["normalize"])
        self.assertEqual(self.code("一期已开工，现提请审议二期方案。"), ["other_item"])
        self.assertEqual(self.code("本项目已开工建设。现提请董事会审议。"), ["adjacent"])
        self.assertEqual(self.code("本项目设备于9月采购到位，现提请院长办公会审议。"), ["weak_exec"])

    def test_priority_when_several_reasons(self) -> None:
        rows = inv("一期已开工，属于程序倒置，现提请审议二期方案。")
        self.assertEqual(rows[0]["reason_code"], "declared")
        self.assertEqual(rows[0]["reason_codes"], ["declared", "other_item"])
        rows = inv("本项目设备于9月采购到位。现提请院长办公会审议。")
        self.assertEqual(rows[0]["reason_codes"], ["adjacent", "weak_exec"])
        self.assertEqual(rows[0]["reason_code"], "adjacent")

    def test_reason_text(self) -> None:
        self.assertIn("同句", inv(TRUE_INVERSION)[0]["reason"])
        self.assertIn("邻句", inv("本项目已开工建设。现提请董事会审议。")[0]["reason"])
        self.assertNotIn("全文", inv(TRUE_INVERSION, "三、说明", "本项目程序上存在瑕疵。")[0]["reason"])


class InversionContrastPairsTest(unittest.TestCase):
    """方案 8.3 成对对照组：每一对只差一个关键词，结果必须不同。"""

    def test_pairs(self) -> None:
        pairs = [
            # (说明, 不报或较轻的写法, 期望, 报的写法, 期望)
            ("已建成的 / 已建成", "已建成的信息系统运行良好，现提请院长办公会审议年度预算。", [],
             "信息系统已建成，现提请院长办公会审议年度投资方案。", ["P1"]),
            ("新购 / 无标记", "已采购CT设备，现提请审议新购MRI设备事项。", [],
             "已采购CT设备，现提请审议CT设备采购事项。", ["P1"]),
            ("计划于 / 于", "项目计划于9月开工建设，现提请院长办公会审议。", [],
             "项目于9月开工建设，现提请院长办公会审议。", ["P1"]),
            ("战略合作协议 / 采购合同", "医院已与供应商签订战略合作协议，现提请院长办公会审议。", [],
             "医院已与供应商签订采购合同，现提请院长办公会审议。", ["P1"]),
        ]
        for name, text_a, exp_a, text_b, exp_b in pairs:
            with self.subTest(pair=name):
                self.assertEqual(lv(text_a), exp_a)
                self.assertEqual(lv(text_b), exp_b)

    def test_declaration_pairs(self) -> None:
        def code(*lines: str) -> List[str]:
            return [r["reason_code"] for r in inv(*lines)]

        # 防止…先执行后决策 / 属于先执行后决策（下一行）
        self.assertEqual(code("设备已采购到位，现提请院长办公会审议。", "各单位要防止出现先执行后决策问题。"), ["same_sentence"])
        self.assertEqual(code("设备已采购到位，现提请院长办公会审议。", "该事项属于先执行后决策。"), ["declared"])
        # 特此如实报告 / 属于程序倒置
        self.assertEqual(code("设备已采购到位，现提请院长办公会审议。", "特此如实报告。"), ["same_sentence"])
        self.assertEqual(code("设备已采购到位，现提请院长办公会审议。", "特此报告，属于程序倒置。"), ["declared"])
        # 另一对：不属于程序倒置 / 属于程序倒置
        self.assertEqual(code("设备已采购到位，现提请院长办公会审议。", "上述做法不属于程序倒置。"), ["same_sentence"])
        self.assertEqual(code("设备已采购到位，现提请院长办公会审议。", "上述做法属于程序倒置。"), ["declared"])


class ExemptionContextTest(unittest.TestCase):
    """方案第 6 节：处置类、出处类的豁免命中要过语境检查；成对对照组见 8.3。"""

    DISPOSE_CATS = ("prohibit", "investigate", "dispose")

    def ex(self, text: str, hit: str, cats: Sequence[str] = ("prohibit", "investigate", "dispose")) -> Optional[str]:
        return exempt(text, hit, cats)

    def test_concession_exception_and_attributive_are_not_exempt(self) -> None:
        for text, hit in (("建议通过分解住院降低次均费用，该做法虽违规但效果明显，请各科室参照执行。", "分解住院降低次均费用"),
                          ("建议各科室通过调整编码提高CMI，去年巡察中已整改的科室除外。", "调整编码提高CMI"),
                          ("建议通过分解住院降低次均费用，不符合规定的病例不纳入。", "分解住院降低次均费用")):
            with self.subTest(text=text):
                self.assertIsNone(self.ex(text, hit))

    def test_dispose_pairs(self) -> None:
        # 同分句内的成对对照：虽违规但 / 违规
        self.assertIsNone(self.ex("分解住院降低次均费用的做法虽违规但效果明显", "分解住院降低次均费用"))
        self.assertEqual(self.ex("分解住院降低次均费用的做法违规", "分解住院降低次均费用"), "dispose")
        # 已整改的科室除外 / 已整改
        self.assertIsNone(self.ex("调整编码提高CMI已整改的科室除外", "调整编码提高CMI"))
        self.assertEqual(self.ex("调整编码提高CMI问题已整改", "调整编码提高CMI"), "dispose")
        # 不符合规定的病例 / 不符合规定
        self.assertIsNone(self.ex("分解住院不符合规定的病例不纳入", "分解住院"))
        self.assertEqual(self.ex("分解住院做法不符合规定", "分解住院"), "dispose")

    def test_dispose_exception_words(self) -> None:
        # 例外词必须在“匹配后到分句末”之内；同分句里才有意义（后续分句本来就不再豁免）
        for tail in ("该做法违规但个别科室仍在执行", "已整改科室参照执行", "违规情形感控科以外", "违规情形不包括急诊",
                     "违规情形不计入考核", "违规情形不含手术科室", "已整改经验照此推广", "违规情形感控科除外"):
            with self.subTest(tail=tail):
                self.assertIsNone(self.ex(f"建议调整编码提高CMI{tail}。", "调整编码提高CMI"))
        for lead in ("尽管", "即使", "即便", "虽然"):
            self.assertIsNone(self.ex(f"建议调整编码提高CMI{lead}该做法违规仍请执行。", "调整编码提高CMI"), lead)
        # 例外词在下一分句：不影响本分句里的处置
        self.assertEqual(self.ex("建议调整编码提高CMI的做法违规，但个别科室仍在讨论。", "调整编码提高CMI"), "dispose")

    def test_purpose_and_prohibit_before_dispose_word_is_not_disposal(self) -> None:
        """处置词前有禁止、否定、目的性成分（避免、防止、确保不、以免、杜绝）时不算处置。"""
        for lead in ("避免", "防止", "确保不出现", "以免", "杜绝", "防范"):
            with self.subTest(lead=lead):
                self.assertIsNone(self.ex(f"建议调整编码提高CMI{lead}违规", "调整编码提高CMI", ("dispose",)))
        self.assertIsNone(self.ex("建议调整编码提高CMI以免违规", "调整编码提高CMI", ("dispose",)))
        # 同一个词，没有目的成分才算处置
        self.assertEqual(self.ex("建议调整编码提高CMI的做法违规", "调整编码提高CMI", ("dispose",)), "dispose")

    def test_other_party_violation_is_not_disposal(self) -> None:
        """“其他、别的、有的 + 单位 + 也”指他：别人违规不是对本做法的处置。"""
        for text in ("建议通过分解住院降低次均费用其他医院也违规这样做", "建议通过分解住院降低次均费用别的科室也违规",
                     "建议通过分解住院降低次均费用有的医院也违规"):
            with self.subTest(text=text):
                self.assertIsNone(self.ex(text, "分解住院降低次均费用"))

    def test_existing_controls_keep_exempt(self) -> None:
        # 调查引述仍然豁免（命中分句里有“巡察指出部分科室存在”）
        self.assertEqual(self.ex("巡察指出部分科室存在调整编码提高四级手术占比的苗头，已整改。", "调整编码提高四级手术占比"), "investigate")
        # 同分句内的否决仍然豁免
        self.assertEqual(self.ex("医院对个别科室提出的调整主要诊断编码以提高CMI的建议予以否决。", "调整主要诊断编码以提高CMI"), "dispose")
        self.assertIsNone(self.ex("建议调整主要诊断编码以提高CMI，不违规。", "调整主要诊断编码以提高CMI"))
        self.assertIsNone(self.ex("建议调整诊断编码以提高CMI，以改善结余。", "调整诊断编码以提高CMI"))


    def test_source_not_exempt_when_not_issued(self) -> None:
        for text, hit in (("该技术国内领先，鉴定意见尚未出具。", "国内领先"),
                          ("鉴定意见尚未出具，该技术国内领先。", "国内领先"),
                          ("鉴定意见待省科技厅出具，该技术国内领先。", "国内领先"),
                          ("相关评价报告将于明年发布，该技术国内领先。", "国内领先"),
                          ("发布的数据尚待核实，该技术国内领先。", "国内领先"),
                          ("评价报告正在编制，填补国内空白。", "填补国内空白"),
                          ("评价报告拟于年底出具，该技术国内领先。", "国内领先"),
                          ("鉴定意见没有取得，该技术国内领先。", "国内领先")):
            with self.subTest(text=text):
                self.assertIsNone(exempt(text, hit, ["source"]))

    def test_source_pairs(self) -> None:
        # 鉴定意见尚未出具 / 鉴定意见见附件（前一分句）
        self.assertIsNone(exempt("鉴定意见尚未出具，该技术国内领先。", "国内领先", ["source"]))
        self.assertEqual(exempt("鉴定意见见附件，该技术国内领先。", "国内领先", ["source"]), "source")
        self.assertEqual(exempt("经省科技厅鉴定，该技术国内领先。", "国内领先", ["source"]), "source")
        self.assertEqual(exempt("公司入选2025年某榜单前十位，技术国内领先。", "国内领先", ["source"]), "source")

    def test_rule_level_patterns_also_checked(self) -> None:
        """规则自带的豁免正则（如 SOE-008 的 exempt_context）里的“鉴定意见”“榜单”“据……统计”同样走语境检查。"""
        pat = (r"(?<![数依根凭论证占])据[^。；，,]{0,12}(?:统计|排名|榜单|报告|公告|评选|认定|评定|发布)"
               r"|经[^。]{0,12}(?:认定|鉴定|评价|评审|认证|评定)|榜单|排名|名单|证书|认定书|鉴定意见|评价报告|发布的|授予|评为|获评|入选")
        text = "该技术国内领先，鉴定意见尚未出具。"
        s, e = span(text, "国内领先")
        self.assertFalse(gc.is_exempt(text, s, e, {"sentence": pat}))
        text2 = "该技术国内领先，鉴定意见见附件。"
        s, e = span(text2, "国内领先")
        self.assertTrue(gc.is_exempt(text2, s, e, {"sentence": pat}))
        text3 = "据统计，该产品国内领先；经省协会认定，该产品获评省级荣誉。"
        s, e = span(text3, "国内领先")
        self.assertTrue(gc.is_exempt(text3, s, e, {"sentence": pat}))

    def test_match_effective_is_per_match(self) -> None:
        """同一窗口里有多处匹配时，只要有一处有效就算豁免。"""
        text = "已整改的科室除外而该做法已被医院否决"
        self.assertEqual(self.ex(text, "该做法"), "dispose")      # “已整改”被例外词抵消，“否决”有效


class KnownCostTest(unittest.TestCase):
    """收缩的已知代价（负责人决定接受）：否定、处置、出处写在命中之后的分句里，豁免不再生效，该句会重新被报出。
    这些断言把代价写明白：将来若要放宽（比如恢复后续窗口），这里会先失败，提醒重新评估。
    （对应规则的 suggestion 带“若后文已写明否决、整改或出处，可忽略本条”的提示。）"""

    def test_later_clause_disposal_no_longer_exempts(self) -> None:
        for text, hit in (("对个别科室提出的调整主要诊断编码以提高CMI的建议，医院明确予以否决。", "调整主要诊断编码以提高CMI"),
                          ("有科室建议通过分解住院降低次均费用，经医保办研判，该做法违规，未予采纳。", "分解住院降低次均费用"),
                          ("建议调整主要诊断编码以提高CMI值，避免违规。", "调整主要诊断编码以提高CMI"),
                          ("建议调整主要诊断编码以提高CMI，确保不出现违规。", "调整主要诊断编码以提高CMI"),
                          ("建议通过调整编码提高CMI，此前已有科室完成整改。", "调整编码提高CMI"),
                          ("建议通过分解住院降低次均费用，其他医院也违规这样做。", "分解住院降低次均费用")):
            with self.subTest(text=text):
                self.assertIsNone(exempt(text, hit, ["prohibit", "investigate", "dispose"]))

    def test_later_clause_source_no_longer_exempts(self) -> None:
        for text in ("该技术国内领先，经省科技厅鉴定。", "该技术国内领先，鉴定意见见附件。",
                     "该技术达到国内领先水平，有关鉴定意见待省科技厅出具。", "该技术国内领先，相关评价报告将于明年发布。"):
            with self.subTest(text=text):
                self.assertIsNone(exempt(text, "国内领先" if "国内领先" in text else "国内领先水平", ["source"]))

    def test_previous_clause_source_still_exempts(self) -> None:
        for text in ("经中华医学会鉴定，该技术达到国内领先水平", "该技术入选省卫健委发布的适宜技术推广目录，处于国内领先水平"):
            with self.subTest(text=text):
                self.assertEqual(exempt(text, "国内领先水平", ["source"]), "source")

    def test_investigation_quote_in_hit_clause_still_exempts(self) -> None:
        # 调查引述（命中所在分句里的“巡察指出……存在”）本来就看命中分句，不受收缩影响
        self.assertEqual(exempt("巡察指出部分科室存在调整编码提高四级手术占比的苗头，已整改。", "调整编码提高四级手术占比",
                                ["investigate"]), "investigate")


if __name__ == "__main__":
    unittest.main()
