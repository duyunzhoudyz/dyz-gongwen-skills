# -*- coding: utf-8 -*-
"""提交前复审回退项的修复测试（v1.3.0）：处置词要针对被命中的做法（A2）、如实声明只认对本事项的直接断言（A5）、
后续分句里有针对该做法的处置、出处词时 P0 降为 P1（A6）、自评与内部评审不算出处（B3）。

运行：python -m unittest discover -s tests/names -t .
"""
from __future__ import annotations

import unittest
from typing import Sequence

from tests.names.test_gw_clause import gc, inv, span

def exempt_dispose(text: str, hit: str) -> bool:
    s, e = span(text, hit)
    return gc.find_exemption(text, s, e, ("dispose",)) is not None


class DisposeTargetsHitTest(unittest.TestCase):
    """同一分句里的处置词必须针对被命中的做法；拿不准就不豁免（宁可报）。"""

    HIT = "调整主要诊断编码以提高CMI"

    def test_unrelated_dispose_in_same_clause_does_not_exempt(self) -> None:
        for text in ("建议各科室整改到位后调整主要诊断编码以提高CMI值。",
                     "建议调整主要诊断编码以提高CMI值并已纠正部分漏填编码。",
                     "已整改科室建议调整主要诊断编码以提高CMI值。",
                     "建议调整主要诊断编码以提高CMI值、已整改。"):
            with self.subTest(text=text):
                self.assertFalse(exempt_dispose(text, self.HIT))

    def test_dispose_that_targets_the_practice_exempts(self) -> None:
        for text in ("对个别科室提出的调整主要诊断编码以提高CMI的建议予以否决。",
                     "医院否决了个别科室提出的调整主要诊断编码以提高CMI值的建议。",
                     "医院否决了个别科室调整主要诊断编码以提高CMI的建议。",
                     "对调整主要诊断编码以提高CMI的问题已整改到位。"):
            with self.subTest(text=text):
                self.assertTrue(exempt_dispose(text, self.HIT))

    def test_past_and_purpose_and_other_do_not_exempt(self) -> None:
        for text in ("建议调整主要诊断编码以提高CMI，避免违规。", "建议调整主要诊断编码以提高CMI值，确保不违规。"):
            with self.subTest(text=text):
                self.assertFalse(exempt_dispose(text, self.HIT))
        # 同分句里“此前”“去年”：说的是别的科室、过去的事
        self.assertFalse(exempt_dispose("建议调整主要诊断编码以提高CMI，此前已有科室完成整改。", self.HIT))
        self.assertFalse(exempt_dispose("建议调整主要诊断编码以提高CMI值，去年已整改的科室除外。", self.HIT))

    def test_hit_position_unknown_keeps_old_behaviour(self) -> None:
        """不给命中位置时 match_effective 不看位置关系（旧调用方式不受影响）。"""
        text = "建议各科室整改到位后调整主要诊断编码以提高CMI值。"
        rx = gc._DISPOSE_FULL
        m = rx.search(text)
        self.assertTrue(gc.match_effective(text, m))
        self.assertFalse(gc.match_effective(text, m, span(text, "调整主要诊断编码以提高CMI")))


class LaterExemptionTest(unittest.TestCase):
    """后续分句里针对该做法的处置、出处词：后续词同样要过语境检查，并且只看规则实际配置的类别。"""

    def later(self, text: str, hit: str, kinds: Sequence[str] = ("dispose", "source")) -> bool:
        s, e = span(text, hit)
        return gc.later_exemption_words(text, s, e, kinds)

    def test_real_later_disposal(self) -> None:
        for text, hit in (("个别科室提出调整主要诊断编码以提高CMI值，医院予以否决。", "调整主要诊断编码以提高CMI"),
                          ("有科室建议通过分解住院降低次均费用，经医保办研判，该做法违规，未予采纳。", "建议通过分解住院"),
                          ("个别病区改变主要诊断编码来提升CMI，目前已完成整改。", "改变主要诊断编码来提升CMI")):
            with self.subTest(text=text):
                self.assertTrue(self.later(text, hit))

    def test_context_check_for_later_words(self) -> None:
        hit = "调整主要诊断编码以提高CMI"
        for text in ("建议调整主要诊断编码以提高CMI值，避免违规。",
                     "建议调整主要诊断编码以提高CMI值，此前已有科室完成整改。",
                     "建议调整主要诊断编码以提高CMI值，其他医院也违规这样做。",
                     "建议调整主要诊断编码以提高CMI值，确保不违规。"):
            with self.subTest(text=text):
                self.assertFalse(self.later(text, hit))
        self.assertTrue(self.later("个别科室提出调整主要诊断编码以提高CMI值，医院予以否决。", hit))

    def test_source_context_check(self) -> None:
        hit = "国内领先"
        for text in ("该技术国内领先，有关鉴定意见待省科技厅出具。", "该技术国内领先，相关评价报告将于明年发布。",
                     "我院技术国内领先，正在申请省科技厅鉴定。", "我院技术国内领先，拟申请鉴定。"):
            with self.subTest(text=text):
                self.assertFalse(self.later(text, hit, ("source",)))
        self.assertTrue(self.later("该技术国内领先，经省科技厅鉴定。", hit, ("source",)))

    def test_kinds_limit(self) -> None:
        """HOS-033 只配置了处置类：后续分句出现“排名”这样的出处词不触发。"""
        text = "建议调整主要诊断编码以提高CMI值，排名靠前。"
        s, e = span(text, "调整主要诊断编码以提高CMI")
        self.assertTrue(gc.later_exemption_words(text, s, e))
        self.assertFalse(gc.later_exemption_words(text, s, e, ("dispose",)))


class SourceSelfEvaluationTest(unittest.TestCase):
    """B3：自评、院内评审、本院认定、初步评价不是出处。"""

    def is_source(self, text: str) -> bool:
        return gc._SOURCE_FULL.search(text) is not None

    def test_not_sources(self) -> None:
        for text in ("经自我评价，我院神经外科技术国内领先。", "经院内评审，我院神经外科技术国内领先。",
                     "经内部评审，我院技术国内领先。", "经本院认定，我院技术国内领先。", "经本单位评价，我院技术国内领先。",
                     "经初步评价，我院技术国内领先。", "经自行鉴定，我院技术国内领先。", "经自评认定，我院技术国内领先。"):
            with self.subTest(text=text):
                self.assertFalse(self.is_source(text))

    def test_real_sources_unchanged(self) -> None:
        for text in ("经省科技厅鉴定，该技术国内领先。", "经国家卫生健康委评审，我院胸痛中心国内领先。",
                     "经中华医学会鉴定，该技术达到国内领先水平", "经自治区科技厅鉴定，该技术国内领先。",
                     "经国家自然科学基金委评审，该成果国际领先。"):
            with self.subTest(text=text):
                self.assertTrue(self.is_source(text))


class DeclarationAssertionTest(unittest.TestCase):
    """A5：如实声明只认“对本事项的直接断言”；疑问、条件、转述、他人、否认、难以认定等写法不算。"""

    def declared(self, *lines: str) -> bool:
        decl = gc.Declaration(list(lines))
        return decl.declared_in("".join(lines))

    def adjust(self, text: str) -> str:
        """text 的第一个“先行开工/先行采购”按 P0 命中走 adjust：返回调整后的级别。"""
        decl = gc.Declaration([text])
        for key in ("先行开工", "先行采购"):
            if key in text:
                return decl.adjust("P0", 0, text.index(key))
        raise AssertionError(text)

    def test_not_declarations_stay_p0(self) -> None:
        for text in ("该项目已先行开工，是否属于程序倒置请会议研究。",
                     "该项目已先行开工，属于程序倒置的说法不准确。",
                     "该项目已先行开工，有人认为属于程序倒置，我们认为不是。",
                     "该项目已先行开工，难以认定属于程序倒置。",
                     "该项目已先行开工，谈不上属于程序倒置。",
                     "其他单位因属于程序倒置被通报。该项目已先行开工，现提请审议。",
                     "该项目已先行开工，现提请审议。如属于程序倒置，按规定处理。",
                     "该项目已先行开工，不属于程序倒置，现提请审议。",
                     "该项目已先行开工，并非程序倒置。",
                     "该项目已先行开工，算不上属于程序倒置。",
                     "该项目已先行开工，并不属于程序倒置。",
                     "该项目已先行开工，未必属于程序倒置。",
                     "该项目已先行开工，有的单位认为属于程序倒置。",
                     "该项目已先行开工，不应认为属于程序倒置。",
                     "若属于程序倒置，应当说明。该项目已先行开工。",
                     "该项目已先行开工，所谓属于程序倒置是质疑。"):
            with self.subTest(text=text):
                self.assertEqual(self.adjust(text), "P0")

    def test_direct_assertions_downgrade(self) -> None:
        for text in ("项目已于9月先行开工，属于程序倒置，现如实报告。",
                     "设备已先行采购。以上情况属于程序倒置，由会议决定后续处理。",
                     "上述事项属于程序倒置。该项目已先行开工，现提请审议。",
                     "该项目未履行决策程序即先行开工，现提请审议。",
                     "该项目已先行开工，该做法违反了投资管理办法。"):
            with self.subTest(text=text):
                self.assertEqual(self.adjust(text), "P1")

    def test_normalize_within_scope_keeps_p0(self) -> None:
        """声明所在句及其后两句、倒置句及其前后一句里有追认、补办，不降级；隔一句的补报同样挡住。"""
        for text in ("该项目已先行开工，现提请审议。属于程序倒置。下一步补报审批。",
                     "该项目已先行开工。属于程序倒置。现如实报告。下一步补办手续。",
                     "该项目已先行开工，属于程序倒置，现提请追认。"):
            with self.subTest(text=text):
                self.assertEqual(self.adjust(text), "P0")

    def test_combination_reason_code_unchanged(self) -> None:
        """组合判定仍按 reason_code 给原因：声明所在句带“特此报告，”前缀也要识别（DECL 先从“此”起匹配，要回退到“属于”）。"""
        self.assertEqual([r["reason_code"] for r in inv("设备已采购到位，现提请院长办公会审议。", "特此报告，属于程序倒置。")], ["declared"])
        self.assertEqual([r["reason_code"] for r in inv("设备已采购到位，现提请院长办公会审议。", "是否属于程序倒置请会议研究。")], ["same_sentence"])


if __name__ == "__main__":
    unittest.main()
