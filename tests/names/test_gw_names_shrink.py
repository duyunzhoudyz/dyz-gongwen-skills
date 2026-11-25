# -*- coding: utf-8 -*-
"""收缩方案后补的三件姓名识别事项与数据来源校验（shared/scripts/gw_names.py、tools/build_name_lexicon.py）。

运行：python -m unittest discover -s tests/names -t .

覆盖：
  1. 强证据下前缀排除词放行（三字候选）、歧义姓三字名在强锚点下按常见姓处理；
  2. 并列后项降低门槛并登记（NameHit.table_only）、夹在中间的非姓名项跳过、并列尾巴遮蔽；
  3. 处分框架姓名组支持“、”并列、括注；名单引导词；
  4. word_bigrams 与 counts 同统计来源一致（等价于 tools/build_name_lexicon.py --check），数据被改动而没重算时测试失败。
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared" / "scripts"
TOOLS = ROOT / "tools"


def _load(mod_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


gn = _load("_t_gw_names_shrink_src", SHARED / "gw_names.py")
LEX = gn.load_lexicon()

HOSPITAL = {
    "prefix": [{"re": r"患者[：:]", "strength": 3}, {"re": "患者", "strength": 2}, {"re": r"(?:当班|值班)?(?:护士|医师|医生)", "strength": 3}],
    "postfix": [{"re": r"(?=（\s*(?:住院号|\d{1,3}\s*床))", "strength": 3}],
}
K12 = {
    "prefix": [{"re": r"(?:特困|低保家庭|家庭经济困难)(?:的)?(?:学生|同学)[：:，,\s]{0,2}", "strength": 4},
               {"re": r"留守儿童[：:\s]{0,2}", "strength": 3}],
}
SOE_LEFT = r"(?:责任人|相关责任人|直接责任人|当事人|负责人|总经理|副总经理|副部长|原|时任)$"
SOE = {
    "frame": [{"re": r"(?:给予|对)(?P<n>[一-鿿、]{2,20}?)(?:同志)?(?:分别)?(?:给予|进行(?:了)?|予以|作出)?(?:党内|政务)?"
                      r"(?:严重警告|警告|记过|记大过|降级|撤职|开除党籍|开除|免职)",
               "strength": 3, "suffix": True, "left_ok": SOE_LEFT},
              {"re": r"(?P<n>[一-鿿、]{2,12}?)(?:同志)?(?:[（(][^）)]{1,16}[）)])?(?:受到|被给予|被)(?:党内|政务)?"
                      r"(?:严重警告|警告|记过|记大过|降级|撤职|开除党籍|开除|免职)",
               "strength": 3, "suffix": True, "left_ok": SOE_LEFT}],
    "list": [{"re": r"(?:拟安置人员|拟推荐人选|推荐人选|安置人员|人选)[：:]\s*", "strength": 3}],
    "prefix": [{"re": "拟推荐", "strength": 3}],
}
ANCHORS = {k: gn.compile_anchors(v) for k, v in (("hospital", HOSPITAL), ("k12", K12), ("soe", SOE))}


def hits(text: str, dom: str):
    return gn.find_names(text, ANCHORS[dom], LEX)


def names(text: str, dom: str, table_only: bool = False) -> List[str]:
    return [h.name for h in hits(text, dom) if h.table_only == table_only and not h.pseudo]


class StrongEvidenceReleasesPrefixStopwordsTest(unittest.TestCase):
    NAMES = "张大伟 张大勇 王冠宇 王朝阳 叶子萌 苏子涵 孙子豪 金子涵 杨梅芳 白云飞 夏天宇 钱江涛 江河清 方可欣".split()

    def test_r3_right_boundary_releases_three_char_names(self) -> None:
        for n in self.NAMES:
            with self.subTest(name=n):
                self.assertEqual(names(f"患者{n}，男，56岁。", "hospital"), [n])
                self.assertEqual(names(f"患者{n}（住院号123456）。", "hospital"), [n])

    def test_title_left_boundary_releases_three_char_names(self) -> None:
        for n in self.NAMES:
            with self.subTest(name=n):
                self.assertEqual(names(f"给予{n}同志党内警告处分。", "soe"), [n])
                self.assertEqual(names(f"对责任人{n}给予警告处分。", "soe"), [n])

    def test_without_strong_evidence_still_vetoed(self) -> None:
        for n in self.NAMES:
            with self.subTest(name=n):
                self.assertEqual(names(f"患者{n}术后发热。", "hospital"), [])

    def test_two_char_and_whole_word_stopwords_still_vetoed(self) -> None:
        for text in ("患者高血压，男性多见。", "患者周围神经病变，女性多见。", "患者白细胞偏高，男性多见。", "患者黄疸，男，56岁。",
                     "患者金银花，男，56岁。", "患者白内障，男，56岁。", "患者何首乌，男，56岁。"):
            with self.subTest(text=text):
                self.assertEqual(names(text, "hospital"), [])

    def test_ambiguous_surname_three_char_names_with_strong_anchor(self) -> None:
        for n in "常秀芳 关晓峰 祝丽华 焦志刚 单丽娟 管玉兰 安秀英".split():
            with self.subTest(name=n):
                self.assertEqual(names(f"当班护士{n}未执行双人核对。", "hospital"), [n])
        self.assertEqual(names("家庭经济困难学生关晓峰申请补助。", "k12"), ["关晓峰"])

    def test_ambiguous_function_char_surnames_stay_strict(self) -> None:
        for text in ("患者和家属沟通。", "患者平均住院日缩短。", "病人关心的是费用。", "管理人员安排到位。", "当班护士和家属沟通。"):
            with self.subTest(text=text):
                self.assertEqual(names(text, "hospital"), [])
        self.assertEqual(names("本学期，学校对单亲家庭学生和家庭经济困难学生建立了一人一档。", "k12"), [])


class ListTailTest(unittest.TestCase):
    def test_second_item_is_registered_and_masked(self) -> None:
        text = "患者王磊、李娜两人均出现输液反应。"
        hs = hits(text, "hospital")
        self.assertEqual([(h.name, h.table_only) for h in hs if h.name in ("王磊", "李娜")][0][0], "王磊")
        self.assertIn("李娜", [h.name for h in hs])
        t = gn.NameTable()
        t.add_hits(hs)
        self.assertEqual(t.cut(text, 0, len(text)), "患者〔姓名1〕、〔姓名2〕两人均出现输液反应。")

    def test_second_item_below_threshold_is_table_only(self) -> None:
        hs = hits("家庭经济困难学生王芳、杜鹃申请免除住宿费。", "k12")
        by = {h.name: h for h in hs}
        self.assertIn("杜鹃", by)
        self.assertTrue(by["杜鹃"].table_only)
        self.assertFalse(by["王芳"].table_only)
        t = gn.NameTable()
        t.add_hits(hs)
        out = t.cut("家庭经济困难学生王芳、杜鹃申请免除住宿费。", 0, 20)
        self.assertNotIn("王芳", out)
        self.assertNotIn("杜鹃", out)

    def test_non_name_item_in_the_middle_is_skipped(self) -> None:
        text = "对低保家庭学生周梓涵、三年级、吴雨桐等5人发放助学金。"
        self.assertEqual([h.name for h in hits(text, "k12")], ["周梓涵", "吴雨桐"])
        text = "对特困学生周梓涵（三年级）、吴雨桐（五年级）发放助学金。"
        self.assertEqual([h.name for h in hits(text, "k12")], ["周梓涵", "吴雨桐"])
        self.assertEqual([h.name for h in hits("特困学生：张三丰、高一、高二各2人。", "k12")], ["张三丰"])

    def test_org_and_grade_items_are_not_names(self) -> None:
        for text in ("孤儿学生：雷锋班、焦裕禄班各1人。", "特困学生：高一、高二各2人。", "建档立卡户学生：高一（3）班、高二（5）班各2人。"):
            self.assertEqual([h.name for h in hits(text, "k12")], [], text)

    def test_comma_chain_only_in_list_context(self) -> None:
        self.assertEqual(names("特困学生：张三丰，李四光。", "k12"), ["张三丰", "李四光"])
        self.assertEqual(hits("患者王建国，男，56岁。", "hospital")[0].name, "王建国")
        self.assertEqual(len(hits("患者王建国，男，56岁。", "hospital")), 1)

    def test_mask_tail_of_unregistered_followers(self) -> None:
        for text, want in (("给予刘凤英、陈素珍同志党内警告处分", "给予〔姓名1〕、〔姓名2〕同志党内警告处分"),
                           ("刘凤英、陈素珍等3人", "〔姓名1〕、〔姓名2〕等3人"),
                           ("刘凤英、李桂兰、张玉珍分别受到处分", "〔姓名1〕、〔姓名2〕、〔姓名3〕分别受到处分"),
                           ("刘凤英（原财务部副部长）、陈素珍（原办公室主任）受到处分", "〔姓名1〕（原财务部副部长）、〔姓名2〕（原办公室主任）受到处分")):
            t = gn.NameTable()
            t.add("刘凤英")
            self.assertEqual(t.mask(text), want, text)
        # 后项登记后，同一姓名在别处也一致遮蔽
        t = gn.NameTable()
        t.add("刘凤英")
        t.mask("刘凤英、陈素珍等3人")
        self.assertIn("陈素珍", t)
        self.assertEqual(t.mask("陈素珍已离职。"), "〔姓名2〕已离职。")
        # 不是姓名形态、或后面不是并列收尾的不遮
        t2 = gn.NameTable()
        t2.add("刘凤英")
        self.assertEqual(t2.mask("刘凤英、高血压患者"), "〔姓名1〕、高血压患者")
        self.assertEqual(t2.mask("刘凤英、财务部负责人"), "〔姓名1〕、财务部负责人")


class FrameAndListAnchorTest(unittest.TestCase):
    def test_discipline_frame_with_listed_names(self) -> None:
        self.assertEqual(names("会议决定给予刘凤英、陈素珍党内警告处分。", "soe"), ["刘凤英", "陈素珍"])
        self.assertEqual(names("对责任人李桂兰、张玉珍分别给予警告和记过处分。", "soe"), ["李桂兰", "张玉珍"])
        self.assertEqual(names("对相关责任人王淑芬给予警告处分。", "soe"), ["王淑芬"])
        self.assertEqual(names("周淑华（原财务部副部长）受到撤职处分。", "soe"), ["周淑华"])

    def test_discipline_frame_not_names(self) -> None:
        for text in ("对相关责任人给予警告处分。", "给予责任人所在部门通报批评。", "对项目经理给予警告处分。"):
            self.assertEqual(names(text, "soe"), [], text)

    def test_list_anchor_and_recommend_prefix(self) -> None:
        self.assertEqual(names("拟安置人员：郝玉珍、钟志强等12人。", "soe"), ["郝玉珍", "钟志强"])
        self.assertEqual(names("拟推荐沈欣妍、秦志明作为后备干部人选。", "soe"), ["沈欣妍", "秦志明"])
        for text in ("拟推荐技术骨干、青年人才参加培训。", "拟安置人员：一线操作岗、辅助岗共12人。"):
            self.assertEqual(names(text, "soe"), [], text)


class LexiconSourceTest(unittest.TestCase):
    """word_bigrams、counts 与统计来源一致（等价于 python tools/build_name_lexicon.py --check）。
    规范性文档（skills/*/references、shared 下的 md、各 SKILL.md）有改动、文档频次越过阈值时，
    这条测试会失败：运行 python tools/build_name_lexicon.py --update 重算，人工过目新增的二字串，不是词的补进 NOISE_BIGRAMS。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tool = _load("_t_build_name_lexicon", TOOLS / "build_name_lexicon.py")

    def test_data_matches_sources(self) -> None:
        ok, msg = self.tool.verify()
        self.assertTrue(ok, msg + "；运行 python tools/build_name_lexicon.py --update")

    def test_check_detects_drift(self) -> None:
        data = json.loads((SHARED / "gw_names.json").read_text(encoding="utf-8"))
        bigrams = self.tool.build_bigrams(self.tool.bigram_docfreq(self.tool.collect_docs()))
        ok, counts_ok, _have, _ = self.tool.check_data(data, bigrams)
        self.assertTrue(ok and counts_ok)
        broken = dict(data)
        broken["word_bigrams"] = broken["word_bigrams"] + " 虚构"
        self.assertFalse(self.tool.check_data(broken, bigrams)[0])
        broken = dict(data)
        broken["given_chars"] = data["given_chars"] + "鼎"       # 改了数据没更新 counts
        self.assertFalse(self.tool.check_data(broken, bigrams)[1])

    def test_unstable_docs_are_not_sources(self) -> None:
        rels = {p.relative_to(ROOT).as_posix() for p, _t in self.tool.collect_docs()}
        self.assertNotIn("README.md", rels)
        self.assertNotIn("CHANGELOG.md", rels)
        self.assertFalse([r for r in rels if r.count("/") == 2 and r.startswith("skills/") and r.endswith("/README.md")])
        self.assertTrue([r for r in rels if r.endswith("SKILL.md")])
        self.assertTrue([r for r in rels if "/references/" in r])

    def test_noise_bigrams_are_excluded(self) -> None:
        data = json.loads((SHARED / "gw_names.json").read_text(encoding="utf-8"))
        have = set(data["word_bigrams"].split())
        self.assertFalse(have & set(self.tool.NOISE_BIGRAMS))
        for g in ("报或", "期或"):
            self.assertNotIn(g, have)

    def test_classmate_bigram_is_kept_below_threshold(self) -> None:
        self.assertIn("同学", self.tool.build_bigrams(self.tool.bigram_docfreq([])))
        self.assertIn("同学", self.tool.load()["word_bigrams"].split())


if __name__ == "__main__":
    unittest.main()
