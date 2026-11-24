# -*- coding: utf-8 -*-
"""提交前复审回退项的修复测试（v1.3.0）：名字含“向从以于”的三字名、并列链整条登记、连词“和与及同跟”并列、
复姓表补充、末字“行”不被截短。

运行：python -m unittest discover -s tests/names -t .

这些用例的思路是机制：软字（向从以于）、并列链回溯登记、连词并列，没有把任何一句话逐条塞进词表。
"""
from __future__ import annotations

import unittest

from tests.names.test_gw_names_shrink import LEX, gn, hits, names


class SoftGivenCharNamesTest(unittest.TestCase):
    """名字第二字是“向、从、以、于”的三字名，在强锚点下也能识别；功能字用法不误报。"""

    NAMES = "宋向东 刘向阳 陈向前 黄向红 周向群 朱向明 赵从军 郑以诚 胡于江".split()

    def test_soft_chars_moved_out_of_nongiven(self) -> None:
        for ch in "向从以于":
            self.assertIn(ch, LEX.soft_given)
            self.assertNotIn(ch, LEX.nongiven)

    def test_names_with_soft_char_recognised(self) -> None:
        for n in self.NAMES:
            with self.subTest(name=n):
                self.assertEqual(names(f"患者{n}，男，61岁，因胸痛入院。", "hospital"), [n])
                self.assertEqual(names(f"当班护士{n}未执行查对。", "hospital"), [n])

    def test_function_word_usage_not_reported(self) -> None:
        for text in ("患者向医生反映疼痛", "患者从家中带来药物", "患者以头痛为主诉", "患者于昨日出院",
                     "护士向家属说明情况", "当班护士于22时巡视", "值班医师从急诊赶来"):
            with self.subTest(text=text):
                self.assertEqual(names(text, "hospital"), [])

    def test_soft_char_not_allowed_in_two_char_name(self) -> None:
        # 软字只允许出现在三字名里：“王向”这样的两字名仍被拒绝
        self.assertIsNone(gn._shape("王向", LEX))


class CompoundSurnameTest(unittest.TestCase):
    def test_new_compound_surnames(self) -> None:
        for sur in "澹台 濮阳 公冶 宗政 太叔 申屠 闻人 赫连 呼延 万俟".split():
            with self.subTest(surname=sur):
                self.assertIn(sur, LEX.compound)
                self.assertEqual(names(f"当班护士{sur}静未按规定执行查对制度。", "hospital"), [f"{sur}静"])


class ChainRegistrationTest(unittest.TestCase):
    """锚点之后由“、”连接的并列链：任一项已识别，链上所有姓氏开头的 2～4 字项都登记（含与常用词同形的、复姓的），首项未识别时回溯。"""

    def test_same_form_items_in_chain_registered(self) -> None:
        for tail in ("杨柳", "苏醒", "方圆", "田野", "叶子", "澹台静"):
            with self.subTest(item=tail):
                got = [h.name for h in hits(f"当事护士徐莉、高语桐、{tail}均已接受约谈。", "hospital")]
                self.assertEqual(got, ["徐莉", "高语桐", tail])

    def test_three_char_name_ending_with_xing_not_truncated(self) -> None:
        hs = hits("当事护士程鹏、邓景行、叶子均已接受约谈。", "hospital")
        self.assertIn("邓景行", [h.name for h in hs])
        self.assertNotIn("邓景", [h.name for h in hs])
        self.assertEqual(names("当班护士邓景行未按规定执行查对制度。", "hospital"), ["邓景行"])

    def test_first_item_backfilled_when_later_item_recognised(self) -> None:
        got = names("经研究，拟推荐人选：高峰、熊建伟。", "soe", table_only=True)
        self.assertEqual(got, ["高峰"])
        self.assertEqual(names("经研究，拟推荐人选：高峰、熊建伟。", "soe"), ["熊建伟"])
        # 首项与常用词同形、后面接着识别出来的并列项
        self.assertEqual(sorted(h.name for h in hits("对相关责任人白云、陆国华分别给予警告处分。", "soe")), ["白云", "陆国华"])

    def test_frame_chain_registers_every_item(self) -> None:
        for first, second in (("林梓萌", "高峰"), ("曹博文", "杨柳"), ("邓景行", "田野"), ("程鹏", "邓景行")):
            with self.subTest(pair=(first, second)):
                got = sorted(h.name for h in hits(f"对相关责任人{first}、{second}分别给予警告处分。", "soe"))
                self.assertEqual(got, sorted([first, second]))

    def test_non_name_items_still_skipped(self) -> None:
        # 年级、班名不是姓名：并列链只登记姓名形态的项
        self.assertEqual(names("特困学生：张三丰、高一、高二。", "k12", table_only=True), [])

    def test_no_chain_without_recognised_item(self) -> None:
        # 锚点之后没有任何一项识别：不回溯（“患者高血压、糖尿病”）
        self.assertEqual(hits("患者高血压、黄疸、糖尿病。", "hospital"), [])


class ConnectorChainTest(unittest.TestCase):
    """连词“和与及同跟”并列：两人都登记，连词不并入前一个姓名。"""

    def test_hospital_and_k12_pairs(self) -> None:
        self.assertEqual(names("特困学生程鹏和邓景行参加了心理团辅。", "k12") + names("特困学生程鹏和邓景行参加了心理团辅。", "k12", True),
                         ["程鹏", "邓景行"])
        for conj in "和与及同跟":
            with self.subTest(conj=conj):
                text = f"特困学生王磊{conj}李静参加了心理团辅。"
                got = [h.name for h in hits(text, "k12")]
                self.assertEqual(got, ["王磊", "李静"])

    def test_same_form_second_item_after_connector(self) -> None:
        for second in ("高峰", "田野", "苏醒", "方圆", "黎明"):
            with self.subTest(second=second):
                got = [h.name for h in hits(f"特困学生卢俊豪和{second}参加了心理团辅。", "k12")]
                self.assertEqual(got, ["卢俊豪", second])

    def test_connector_followed_by_common_noun_not_a_name(self) -> None:
        for text in ("特困学生和家庭经济困难学生参加了活动。", "患者张三与家属沟通。", "特困学生：王磊和家长。"):
            with self.subTest(text=text):
                self.assertFalse([h for h in hits(text, "k12") + hits(text, "hospital") if h.name in ("家属", "家长", "家庭")])

    def test_frame_connector_split(self) -> None:
        got = sorted(h.name for h in hits("给予程鹏和邓景行同志党内警告处分。", "soe"))
        self.assertEqual(got, ["程鹏", "邓景行"])


if __name__ == "__main__":
    unittest.main()
