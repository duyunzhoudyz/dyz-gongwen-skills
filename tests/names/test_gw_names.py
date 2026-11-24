# -*- coding: utf-8 -*-
"""shared/scripts/gw_names.py 与 gw_names.json 的测试：结构、召回、精度、对抗探针。

运行：python -m unittest discover -s tests/names -t .

测试思路（不再用名单验证名单）：
  1. 结构：数据文件的集合关系、排除词的形态约束、规模下限与 counts 一致性，与 gongwen_lint.SURNAMES 一致。
  2. 召回：按“语境类别”分组（标点与括注、功能字、时间词、亲属与所属、词表外动词或名词、并列名单、职务框架、K12 身份加学生），
     每类单独统计、单独断言下限，在日志里分别打印召回率与 P0 比例，不合并成一个数字。名字集有三份：
       - fixtures/names.txt（408 个人工编写的虚构姓名，含易混名）；
       - fixtures/given_names.txt（60 个常见姓 × 单字名、两字名用字，按固定步长程序化抽样）；
       - fixtures/manual_names.txt（约 40 个人工名：复姓、少见姓、歧义姓、软字名）。
     另有 fixtures/confusable_names.txt（与排除词、地名同形的真实姓名，断言精确得分）。
     下限写死，取实测值向下取整到 5%；调低必须写明原因。
  3. 与 HEAD 对照：fixtures/head_baseline.json 是 HEAD（d07b657）引擎在同一名字集、同一句式上的实跑数字；
     共享层能断言的行（锚点在本文件里有等价写法）断言“新实现命中数不低于 HEAD”，其余留给各引擎自己的测试。
  4. 精度：对 skills/*/references 与 shared 下的 Markdown 跑各套锚点，识别结果只能是 fixtures/allowed_names.txt 登记的示例姓名。
  5. 对抗探针：按真实行文手写的“应不报”“应报”短语。已知做不到的句子登记在 KNOWN_LIMITS，测试日志里列出。
各套锚点在这里作为常量写入（含第 2 步各包将采用的新锚点：K12 角色锚点、国企职务称谓框架），三包接入时各自在规则 JSON 或脚本里声明，写法保持一致。
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(mod_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


gn = _load("_t_gw_names_src", SHARED / "gw_names.py")
gongwen_lint = _load("_t_gongwen_lint_src", SHARED / "gongwen_lint.py")
LEX = gn.load_lexicon(SHARED / "gw_names.json")

# 迁移前 k12_check.SURNAMES 的全集（401 字，按字符排序）。k12_check 接入共享数据后不再自带这张表，所以在此冻结一份。
LEGACY_K12_SURNAMES = (
    "丁万丛严丰乌乐乔于云亓井亢仇付仝仲任伊伍伏但位何佘余佟侯俞信修倪傅储元党全公兰关冀冉农冯况冶冷冼凌刁刘初利劳勾包匡区华卓单南卜卞卢卫印危卿厉原古史叶司吉向吕吴周呼和哈唐商喻国夏奉奚姚姜姬娄孔孙孟季宁安宋宗官宣宫容宾宿寇富封尉尚尤尧尹居屈展屠岑岳崔嵇左巩巫巴帅师席常干平幸庄应庞康廉廖张强彭徐惠慕戈戎成战戚戴房扈揭支敖敬文斯方於施时明易昝晁晋晏普景智曲曹曾朱朴权李杜束来杨杭林柏查柯柳柴栗栾桂桑梁梅植楚楼樊檀欧武段殷母毕毛江池汤汪沈沙浦海涂温游湛滕满漆潘焦熊燕牛牟狄玉王班甄甘田由申白皮盖盘盛相瞿石祁祖祝禹秦程穆窦章童符简管米粟索纪练缪罗羊翁翟耿聂肖胡胥臧舒艾芦芮花苏苑苗苟范茅茹荆荣莫萧葛董蒋蒙蒲蓝蔡蔺薄薛虞衡衣袁裘裴褚覃解詹计许诸谈谌谢谭谷豆费贺贾赫赵路车辛辜边连迟逯邓邝邢那邬邰邱邵邸邹郁郎郑郜郝郭都鄢金钟钮钱银门闫闭闵闻阎阙阚阮阳阴阿陆陈陶隆隋雍雷霍靳鞠韦韩项顾颜饶马骆高魏鲁鲍鲜鹿麦麻黄黎齐龙龚"
)

# 在旧 k12 姓氏表（401 字）之外新增的姓氏，逐个登记理由。surnames_common 不能动（必须与 gongwen_lint.SURNAMES 相同），
# 所以新增姓氏只放 surnames_rare（单独出现只给低置信的 P1 以内，由锚点和边界打分兜底）。
ADDED_SURNAMES = {
    "洪": "常见姓（百家姓、当代人口前 100 位），旧 k12 表漏了；“患者洪建国”“特困学生洪涛”此前识别不了（少见姓，两字名只给低分）。"
          "与之同形的普通词（洪水、洪流、洪峰、洪灾、洪脉、洪亮）已加回排除词",
    "赖": "常见姓（当代人口前 100 位），旧 k12 表漏了；与之同形的普通词（赖账、赖皮、赖家、赖氏）已加回排除词",
}

# ---------------------------------------------------------------------------
# 三套锚点（与方案 2.2 一致）
# ---------------------------------------------------------------------------
SEP = r"[：:，,\s]{0,2}(?:为|是)?[：:\s]{0,2}"
_ROLES = r"(?:护士长|护士|护师|医师|医生|药师|技师|技士|麻醉师|助产士)"
HOS_STRONG = (r"(?:患者|患儿|病人|病员)?姓名(?:(?:为|是)[：:]?|[：:])\s*|(?:患者|患儿|病人)[：:]\s*"
              r"|(?:床位号|床号)[：:为\s]*\d{1,3}[，,\s]*(?:患者|患儿|病人)?[：:，,\s]{0,2}"
              r"|(?<![\d])\d{1,3}\s*(?:床|号床)(?![位单旁边头尾日次垫上下数护])\s*(?:患者|患儿|病人|的)?[：:，,\s（(]{0,2}"
              r"|(?:当事|当班|值班|涉事|责任)" + _ROLES + SEP + r"|投诉人" + SEP)
HOS_PLAIN = (r"(?:患者|患儿|病人|病员)[，,\s]{0,2}"
             r"|(?:主管|管床|带教|实习|规培|进修|夜班|白班)?" + _ROLES + SEP)
HOS_POST = (r"(?=[（(]\s*(?:住院号|病案号|病历号|ID号|门诊号|床号|\d{1,3}\s*床|男|女|工号))"
            r"|(?=[，,]\s*(?:男|女)(?:性)?\s*(?:[，,、。（(]|\d))")
PUN = r"(?:严重警告|警告|记过|记大过|降级|撤职|撤销党内职务|留党察看|开除党籍|开除公职|开除|诫勉|免职)"
SOE_FRAME_1 = r"(?:给予|对)(?P<n>[一-鿿]{2,4}?)(?:同志)?(?:给予)?(?:党内|政务)?" + PUN
SOE_FRAME_2 = r"(?P<n>[一-鿿]{2,4}?)(?:同志)?(?:受到|被给予|被处以|被)(?:党内|政务)?" + PUN
# suffix 型 frame 的称谓放行（与 soe_rules.json 的 SOE-022 一致）：候选前面是这些职务称谓时左边界成立
SOE_LEFT_OK = (r"(?:总经理|副总经理|董事长|副董事长|党委书记|副书记|书记|副主任|主任|经理|副经理|部长|副部长|处长|科长|局长|总监"
               r"|总工程师|总会计师|厂长|院长|所长|队长|站长|原|时任|现任|该)$")
SOE_LIST = (r"(?:酝酿|考察对象|初步人选|候选人|拟提拔|拟推荐|拟任|裁减|分流|安置|内退|待岗|解除劳动合同|处分|问责)"
            r"(?:人员|职工|对象|人选)?(?:名单|人选)(?:初步)?(?:为|如下)?[：:]?\s*")
K12_SENS = (r"(?:低保户|低保家庭|低保(?!金|政策|标准|对象|资金|工作)|建档立卡户?|特困(?:供养)?|困难家庭|家庭经济困难"
            r"|单亲家庭|离异家庭|留守儿童|孤儿|抑郁症|多动症|自闭症|违纪处分|受过处分)")
K12_PRE = K12_SENS + r"(?:的)?(?:学生|同学|子女|儿童|家庭学生)?(?:[：:，,\s]{0,2})"
K12_LIST = K12_SENS + r"[^。；;：:\n]{0,12}?(?:名单(?:如下|为)?|\d+\s*[名人位])\s*[：:]\s*"
K12_POST = r"(?=同学(?!们))"
# 第 2 步中小学线将采用的新锚点：身份词加角色名词 4 分；只有身份词（去掉逗号分隔）3 分
K12_ROLE = K12_SENS + r"(?:的)?(?:学生|同学|子女|儿童|家庭学生)[：:，,\s]{0,2}"
K12_BARE = K12_SENS + r"(?:的)?[：:\s]{0,2}"
# 第 2 步国企线将采用的新处分框架：suffix 型，组长度上限 16 字，左边界用职务称谓表
SOE_FRAME_1_NEW = (r"(?:给予|对)(?P<n>[一-鿿]{2,16}?)(?:同志)?(?:给予|进行(?:了)?|予以|作出)?(?:党内|政务)?" + PUN)
SOE_TITLES = (r"(?:总经理助理|副总经理|总经理|董事长|副董事长|党委书记|党委副书记|副书记|书记|副主任|主任|副经理|经理|副部长|部长|副处长"
              r"|处长|副科长|科长|局长|总监|总工程师|总会计师|总经济师|厂长|院长|所长|队长|站长|组长|班长|主管|专员|员工|职工|干部"
              r"|会计|出纳|工程师|技术员|业务员|采购员|原|时任|现任|该)$")

ANCHORS = {
    "hospital": gn.compile_anchors({
        "prefix": [{"re": HOS_STRONG, "strength": 3}, {"re": HOS_PLAIN, "strength": 2}],
        "postfix": [{"re": HOS_POST, "strength": 3}],
    }),
    "soe": gn.compile_anchors({
        "frame": [{"re": SOE_FRAME_1, "strength": 3},
                  {"re": SOE_FRAME_2, "strength": 3, "suffix": True, "left_ok": SOE_LEFT_OK}],
        "list": [{"re": SOE_LIST, "strength": 3}],
    }),
    "soe_new": gn.compile_anchors({
        "frame": [{"re": SOE_FRAME_1_NEW, "strength": 3, "suffix": True, "left_ok": SOE_TITLES},
                  {"re": SOE_FRAME_2, "strength": 3, "suffix": True, "left_ok": SOE_TITLES}],
        "list": [{"re": SOE_LIST, "strength": 3}],
    }),
    "k12": gn.compile_anchors({
        "prefix": [{"re": K12_PRE, "strength": 3}],
        "list": [{"re": K12_LIST, "strength": 3}],
        "postfix": [{"re": K12_POST, "strength": 2}],
    }),
    "k12_new": gn.compile_anchors({
        "prefix": [{"re": K12_ROLE, "strength": 4}, {"re": K12_BARE, "strength": 3}],
        "list": [{"re": K12_LIST, "strength": 3}],
        "postfix": [{"re": K12_POST, "strength": 2}],
    }),
}
ALL_ANCHORS = ANCHORS["hospital"] + ANCHORS["soe"] + ANCHORS["soe_new"] + ANCHORS["k12"] + ANCHORS["k12_new"]


def detect(text: str, domain: str, min_score: int = gn.SCORE_LOW) -> List["gn.NameHit"]:
    anchors = ALL_ANCHORS if domain == "all" else ANCHORS[domain]
    return [h for h in gn.find_names(text, anchors, LEX) if not h.pseudo and h.score >= min_score]


def read_list(path: Path) -> List[str]:
    out = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


class TableNameTest(unittest.TestCase):
    def test_markdown_boundaries_and_original_offsets(self) -> None:
        lines = [
            "学生姓名 | **困难类型** | 备注",
            ":--- | ---: | :---:",
            "`欧阳明月` | 低保 | 左\\|右",
            "| 高一 | 低保 | 无 |",
            "| 宣传科 | 低保 | 无 |",
            "| 合计 | 1 | |",
            "",
            "| 联系人姓名 | 困难类型 |",
            "| --- | --- |",
            "| 王秀英 | 低保 |",
            "",
            "```md",
            "| 姓名 | 困难类型 |",
            "| --- | --- |",
            "| 王秀英 | 低保 |",
            "```",
            "| 姓名 | 困难类型 |",
            "| 王秀英 | 低保 |",
            "",
            "| 姓名 | 困难类型 |",
            "| **---** | --- |",
            "| 王秀英 | 低保 |",
        ]
        rows = gn.find_table_names(lines, LEX, "k12")
        self.assertEqual(list(rows), [2])
        hit, = rows[2].hits
        self.assertEqual((hit.name, hit.score, lines[2][hit.start:hit.end]), ("欧阳明月", gn.SCORE_HIGH, "欧阳明月"))

    def test_sensitive_headers_are_industry_specific(self) -> None:
        lines = ["| 姓名 | 诊断 |", "| --- | --- |", "| 张丽丽 | 观察 |"]
        for domain, score in (("hospital", gn.SCORE_HIGH), ("soe", gn.SCORE_LOW), ("k12", gn.SCORE_HIGH)):
            with self.subTest(domain=domain):
                self.assertEqual(gn.find_table_names(lines, LEX, domain)[2].hits[0].score, score)


# ---------------------------------------------------------------------------
# 1. 结构
# ---------------------------------------------------------------------------
class LexiconStructureTest(unittest.TestCase):
    def test_stopwords_sorted_unique(self) -> None:
        words = list(LEX.stopwords)
        self.assertEqual(words, sorted(set(words)), "排除词必须排序且去重")

    def test_stopwords_start_with_surname(self) -> None:
        for w in LEX.stopwords:
            self.assertTrue(w[0] in LEX.surnames or w[:2] in LEX.compound, f"排除词“{w}”不以姓氏字或复姓开头")

    def test_common_equals_gongwen_lint(self) -> None:
        self.assertEqual(set(LEX.surnames_common), set(gongwen_lint.SURNAMES))

    def test_union_is_superset_of_legacy_k12_with_registered_additions(self) -> None:
        """常见姓与少见姓的并集 ⊇ 旧 k12 姓氏表（401 字），新增项必须逐个登记在 ADDED_SURNAMES 里说明理由。"""
        self.assertEqual(len(LEGACY_K12_SURNAMES), 401)
        union = set(LEX.surnames_common) | set(LEX.surnames_rare)
        self.assertTrue(set(LEGACY_K12_SURNAMES) <= union, "旧表里有姓氏被删了：" + "".join(sorted(set(LEGACY_K12_SURNAMES) - union)))
        added = union - set(LEGACY_K12_SURNAMES)
        self.assertEqual(added, set(ADDED_SURNAMES), "新增姓氏必须逐个登记（字符集合与 ADDED_SURNAMES 完全一致）")
        for ch, why in ADDED_SURNAMES.items():
            self.assertTrue(why.strip(), ch)
            self.assertIn(ch, LEX.surnames_rare, f"新增姓氏“{ch}”应放在 surnames_rare（surnames_common 必须与 gongwen_lint.SURNAMES 相同）")

    def test_sets_disjoint_and_ambiguous_subset(self) -> None:
        self.assertFalse(LEX.surnames_common & LEX.surnames_rare)
        self.assertTrue(LEX.ambiguous <= LEX.surnames)
        self.assertTrue(LEX.compound and all(len(c) == 2 for c in LEX.compound))

    def test_char_sets_are_single_chars(self) -> None:
        for group in (LEX.nongiven, LEX.place_end, LEX.place_end_2char, LEX.given, LEX.soft_given):
            self.assertTrue(all(len(c) == 1 for c in group))

    def test_new_stopwords_present(self) -> None:
        for w in ("班主任", "程序", "严格", "安全", "全体", "于凌", "于次", "于后", "华润", "满意", "农业",
                  "赖账", "赖皮", "洪水", "洪流", "洪峰", "洪灾", "洪亮"):
            self.assertIn(w, LEX.stopwords)

    # ---- 1.1.0 新增字段 ----
    def test_version_and_new_fields(self) -> None:
        self.assertEqual(LEX.version, "1.2.0")
        self.assertGreaterEqual(len(LEX.given), 400)
        self.assertGreaterEqual(len(LEX.word_bigrams), 2000)
        self.assertTrue(LEX.soft_given and LEX.stopwords_exact)
        self.assertTrue(all(len(w) == 2 for w in LEX.word_bigrams))

    def test_given_soft_nongiven_disjoint(self) -> None:
        self.assertFalse(LEX.given & LEX.nongiven)
        self.assertFalse(LEX.soft_given & LEX.nongiven)
        self.assertFalse(LEX.given & LEX.soft_given)
        self.assertEqual(set(LEX.soft_given), set("和会年日时芷之向从以于无"))

    def test_exact_stopwords_rules(self) -> None:
        words = list(LEX.stopwords_exact)
        data = json.loads((SHARED / "gw_names.json").read_text(encoding="utf-8"))
        self.assertEqual(data["stopwords_exact"], sorted(set(words)), "整词排除词必须排序且去重")
        for w in words:
            self.assertTrue(w[0] in LEX.surnames or w[:2] in LEX.compound, f"整词排除词“{w}”不以姓氏字或复姓开头")
            self.assertNotIn(w, LEX.stopwords, f"“{w}”同时在前缀类和整词类，应只放整词类")
        for w in ("刘海", "林海", "黎明", "高峰", "王国", "高一", "初三", "张家", "李家村", "张家界", "金山", "文山", "戴维"):
            self.assertIn(w, LEX.stopwords_exact)

    def test_counts_match_actual_lengths(self) -> None:
        data = json.loads((SHARED / "gw_names.json").read_text(encoding="utf-8"))
        counts = data["counts"]
        for key, value in counts.items():
            raw = data[key]
            actual = len(raw.split()) if key == "word_bigrams" else len(raw)
            self.assertEqual(value, actual, key)
        self.assertEqual(set(counts), set(gn.MIN_SIZES))

    def test_lexicon_minimum_sizes(self) -> None:
        sizes = {"surnames_common": len(LEX.surnames_common), "surnames_rare": len(LEX.surnames_rare),
                 "compound": len(LEX.compound), "ambiguous": len(LEX.ambiguous), "nongiven_chars": len(LEX.nongiven),
                 "soft_given_chars": len(LEX.soft_given), "given_chars": len(LEX.given), "place_end": len(LEX.place_end),
                 "place_end_2char": len(LEX.place_end_2char), "stopwords": len(LEX.stopwords),
                 "stopwords_exact": len(LEX.stopwords_exact), "right_strong": len(LEX.right_strong),
                 "right_weak": len(LEX.right_weak), "left_words": len(LEX.left_words), "word_bigrams": len(LEX.word_bigrams),
                 "table_names": len(LEX.table_names), "table_public": len(LEX.table_public),
                 "table_nonnames": len(LEX.table_nonnames), "org_abbr_end": len(LEX.org_abbr_end),
                 **{"table_sensitive_" + d: len(words) for d, words in LEX.table_sensitive.items()}}
        for key, floor in gn.MIN_SIZES.items():
            self.assertGreaterEqual(sizes[key], floor, key)
        # 方案 7 给的下限不得被悄悄调低
        for key, floor in (("surnames_common", 200), ("surnames_rare", 100), ("compound", 15), ("stopwords", 800),
                           ("nongiven_chars", 100), ("place_end", 30), ("right_strong", 20), ("right_weak", 10),
                           ("left_words", 20), ("given_chars", 400), ("word_bigrams", 2000)):
            self.assertGreaterEqual(gn.MIN_SIZES[key], floor, key)

    def test_place_end_and_right_strong_revisions(self) -> None:
        self.assertIn("班", LEX.place_end)
        self.assertIn("校", LEX.place_end)
        self.assertIn("等", LEX.right_strong)
        for ch in "海江山":
            self.assertNotIn(ch, LEX.place_end_2char)
            self.assertIn(ch, LEX.given)
        for ch in "和会年日时芷之":
            self.assertNotIn(ch, LEX.nongiven)

    def test_given_chars_cover_everyday_name_characters(self) -> None:
        """常见名用字表是独立整理的，这里只抽查最常见的一批，防止整表被误删。"""
        for ch in "伟芳娜敏静丽强磊军洋勇艳杰涛明霞平刚华红燕玲辉鹏飞波斌宇浩凯健俊":
            self.assertIn(ch, LEX.given, ch)

    def _mutated(self, tmp: str, name: str, **changes) -> Path:
        data = json.loads((SHARED / "gw_names.json").read_text(encoding="utf-8"))
        data.update(changes)
        p = Path(tmp) / name
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return p

    def test_bad_lexicon_rejected(self) -> None:
        data = json.loads((SHARED / "gw_names.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            # 常见姓与少见姓重叠
            p = self._mutated(tmp, "a.json", surnames_rare=data["surnames_rare"] + data["surnames_common"][:1])
            with self.assertRaises(gn.LexiconError):
                gn.load_lexicon(p)
            # 排除词不以姓氏开头（同时 counts 也对不上，下面单独验证 counts）
            words = list(data["stopwords"]) + ["数学"]
            counts = dict(data["counts"], stopwords=len(words))
            p2 = self._mutated(tmp, "b.json", stopwords=words, counts=counts)
            with self.assertRaisesRegex(gn.LexiconError, "不以姓氏"):
                gn.load_lexicon(p2)
            with self.assertRaises(gn.LexiconError):
                gn.load_lexicon(Path(tmp) / "不存在.json")
            p3 = Path(tmp) / "c.json"
            p3.write_text("{坏", encoding="utf-8")
            with self.assertRaises(gn.LexiconError):
                gn.load_lexicon(p3)

    def test_counts_mismatch_rejected(self) -> None:
        data = json.loads((SHARED / "gw_names.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            # 多一个排除词但 counts 没更新
            p = self._mutated(tmp, "a.json", stopwords=list(data["stopwords"]) + ["王某人"])
            with self.assertRaisesRegex(gn.LexiconError, "counts"):
                gn.load_lexicon(p)
            # 没有 counts 字段
            bad = dict(data)
            del bad["counts"]
            p2 = Path(tmp) / "b.json"
            p2.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(gn.LexiconError, "counts"):
                gn.load_lexicon(p2)

    def test_truncated_data_rejected_by_minimum_sizes(self) -> None:
        data = json.loads((SHARED / "gw_names.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            cut = data["given_chars"][:100]
            p = self._mutated(tmp, "a.json", given_chars=cut, counts=dict(data["counts"], given_chars=len(cut)))
            with self.assertRaisesRegex(gn.LexiconError, "最小规模"):
                gn.load_lexicon(p)
            few = " ".join(data["word_bigrams"].split()[:500])
            p2 = self._mutated(tmp, "b.json", word_bigrams=few, counts=dict(data["counts"], word_bigrams=500))
            with self.assertRaisesRegex(gn.LexiconError, "最小规模"):
                gn.load_lexicon(p2)

    def test_sentinels_required(self) -> None:
        data = json.loads((SHARED / "gw_names.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            common = data["surnames_common"].replace("王", "")
            rare = data["surnames_rare"] + "王"
            p = self._mutated(tmp, "a.json", surnames_common=common, surnames_rare=rare,
                              counts=dict(data["counts"], surnames_common=len(common), surnames_rare=len(rare)))
            with self.assertRaisesRegex(gn.LexiconError, "哨兵"):
                gn.load_lexicon(p)
            comp = [c for c in data["compound"] if c != "欧阳"]
            p2 = self._mutated(tmp, "b.json", compound=comp, counts=dict(data["counts"], compound=len(comp)))
            with self.assertRaisesRegex(gn.LexiconError, "哨兵"):
                gn.load_lexicon(p2)

    def test_overlapping_char_sets_rejected(self) -> None:
        data = json.loads((SHARED / "gw_names.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            given = data["given_chars"] + data["nongiven_chars"][:1]
            p = self._mutated(tmp, "a.json", given_chars=given, counts=dict(data["counts"], given_chars=len(given)))
            with self.assertRaisesRegex(gn.LexiconError, "互不重叠"):
                gn.load_lexicon(p)


class ShapeAndHelpersTest(unittest.TestCase):
    def test_looks_like_name(self) -> None:
        for w in ("王建国", "李娜", "欧阳明", "上官雪儿", "王某", "张某某"):
            self.assertTrue(gn.looks_like_name(w, LEX), w)
        for w in ("高血压", "李渡镇", "沈阳籍", "严格", "项目经理", "一年级", "数学", "王", "王建国国国"):
            self.assertFalse(gn.looks_like_name(w, LEX), w)

    def test_has_surname_prefix(self) -> None:
        self.assertTrue(gn.has_surname_prefix("王老师", LEX))
        self.assertTrue(gn.has_surname_prefix("欧阳明", LEX))
        self.assertFalse(gn.has_surname_prefix("学生", LEX))
        self.assertFalse(gn.has_surname_prefix("", LEX))

    def test_pseudo_names_are_flagged_and_not_tabled(self) -> None:
        hits = gn.find_names("患者：张某，男，因发热入院。", ANCHORS["hospital"], LEX)
        self.assertEqual([(h.name, h.pseudo) for h in hits], [("张某", True)])
        table = gn.NameTable()
        table.add_hits(hits)
        self.assertEqual(len(table), 0)

    def test_scores_and_levels(self) -> None:
        h = gn.find_names("患者：王建国，住院号123456。", ANCHORS["hospital"], LEX)[0]
        self.assertGreaterEqual(h.score, gn.SCORE_HIGH)
        self.assertEqual(h.name, "王建国")
        h2 = gn.find_names("患者关晓彤（住院号123456）。", ANCHORS["hospital"], LEX)[0]  # 弱锚点（“患者”2 分）下歧义姓只给低置信
        self.assertEqual(h2.score, gn.SCORE_LOW)
        # 歧义姓三字名在强锚点（锚点分 >= 3）下按常见姓处理：高置信
        h3 = gn.find_names("当班护士关晓彤未执行双人核对。", ANCHORS["hospital"], LEX)[0]
        self.assertGreaterEqual(h3.score, gn.SCORE_HIGH)

    def test_no_hit_below_low_score(self) -> None:
        self.assertEqual(gn.find_names("患者平均住院日缩短。", ANCHORS["hospital"], LEX), [])

    def test_left_digit_veto(self) -> None:
        self.assertEqual(detect("1500米后帮同学们整理书包。", "k12"), [])
        self.assertEqual(detect("今天迎来5706位新同学。", "k12"), [])

    def test_compile_anchors_errors(self) -> None:
        with self.assertRaises(gn.AnchorError):
            gn.compile_anchors({"nope": []})
        with self.assertRaises(gn.AnchorError):
            gn.compile_anchors({"prefix": [{"re": "(", "strength": 3}]})
        with self.assertRaises(gn.AnchorError):
            gn.compile_anchors({"frame": [{"re": "对(.+)处分", "strength": 3}]})
        self.assertEqual(gn.compile_anchors(None), [])

    def test_list_items_split_and_parenthesis(self) -> None:
        text = "拟提拔人选名单：马建国（男，45岁）、周杰同志、欧阳明等3人。"
        hits = detect(text, "soe")
        self.assertEqual([h.name for h in hits], ["马建国", "周杰", "欧阳明"])

    def test_frame_suffix_picks_name_at_end(self) -> None:
        hits = detect("会议研究决定王强被开除党籍。", "soe")
        self.assertEqual([h.name for h in hits], ["王强"])
        hits = detect("总经理王强同志受到党内严重警告处分。", "soe")
        self.assertEqual([h.name for h in hits], ["王强"])


class BoundaryRevisionTest(unittest.TestCase):
    """边界词调整：“的”“对”升为右边界强词，“床”进左边界词，suffix 型 frame 有左边界，名单语境支持“，”并列。"""

    def test_de_and_dui_are_strong_right_boundaries(self) -> None:
        self.assertIn("的", LEX.right_strong)
        self.assertIn("对", LEX.right_strong)
        self.assertNotIn("的", LEX.right_weak)
        self.assertNotIn("对", LEX.right_weak)
        h = detect("患者王建国的家属对处置表示理解。", "hospital")
        self.assertEqual([(x.name, x.score >= gn.SCORE_HIGH) for x in h], [("王建国", True)])
        h = detect("患者赵敏华对处置过程表示不满。", "hospital")
        self.assertEqual([(x.name, x.score >= gn.SCORE_HIGH) for x in h], [("赵敏华", True)])
        h = detect("患者王丽的家属来访。", "hospital")  # 两字名：分数 5，低置信
        self.assertEqual([(x.name, x.score) for x in h], [("王丽", gn.SCORE_LOW)])

    def test_de_dui_do_not_create_false_hits(self) -> None:
        for text in ("患者的家属对处置表示理解。", "医师的处置符合规范。", "护士对患者进行了宣教。",
                     "患者家属对护理服务表示满意。", "值班医师对该病例高度重视。", "患者对治疗方案表示理解。",
                     "患者黄色的分泌物增多。", "医生对家属进行了告知。", "护士长对科室工作负责。"):
            self.assertEqual(detect(text, "hospital"), [], text)

    def test_bed_char_is_left_boundary(self) -> None:
        self.assertIn("床", LEX.left_words)
        self.assertEqual(gn.left_score("17床赵敏华（女，49岁）", 3, LEX), 1)
        # 后锚点（括注）经“床”左边界后得分 6，与 12床前锚点的同一姓名由引擎去重
        h = gn.find_names("17床赵敏华（女，49岁）输液外渗。", gn.compile_anchors({"postfix": [{"re": HOS_POST, "strength": 3}]}), LEX)
        self.assertEqual([(x.name, x.score) for x in h], [("赵敏华", 6)])

    def test_suffix_frame_has_left_boundary(self) -> None:
        for text in ("邓小平理论受到警告处分", "邓小平理论学习不力的支部受到警告处分", "王府井百货受到警告",
                     "钱江新城项目部被诫勉", "相关责任人受到党内警告处分"):
            self.assertEqual(detect(text, "soe"), [], text)
        for text, name in (("会议研究决定王强被开除党籍", "王强"), ("总经理王强同志受到警告处分", "王强"),
                           ("王强受到警告处分", "王强"), ("经研究，马建国被免职。", "马建国"),
                           ("时任董事长周杰受到记过处分", "周杰")):
            self.assertEqual([h.name for h in detect(text, "soe")], [name], text)

    def test_suffix_frame_left_ok_regex_is_caller_supplied(self) -> None:
        plain = gn.compile_anchors({"frame": [{"re": SOE_FRAME_2, "strength": 3, "suffix": True}]})
        self.assertEqual(gn.find_names("总经理王强同志受到警告处分", plain, LEX), [])  # 没有称谓正则：称谓前的“理”不是边界
        with_ok = gn.compile_anchors({"frame": [{"re": SOE_FRAME_2, "strength": 3, "suffix": True, "left_ok": SOE_LEFT_OK}]})
        self.assertEqual([h.name for h in gn.find_names("总经理王强同志受到警告处分", with_ok, LEX)], ["王强"])
        with self.assertRaises(gn.AnchorError):
            gn.compile_anchors({"prefix": [{"re": "患者", "strength": 3, "left_ok": "x$"}]})
        with self.assertRaises(gn.AnchorError):
            gn.compile_anchors({"frame": [{"re": SOE_FRAME_1, "strength": 3, "left_ok": "x$"}]})

    def test_comma_chain_in_list_context(self) -> None:
        h = detect("特困学生：张三，李四", "k12")
        self.assertEqual([x.name for x in h], ["张三", "李四"])
        h = detect("低保家庭学生：陈美玲，杨海涛，赵文静。", "k12")
        self.assertEqual([x.name for x in h], ["陈美玲", "杨海涛", "赵文静"])
        h = detect("特困学生：张三、李四，王五", "k12")
        self.assertEqual([x.name for x in h], ["张三", "李四", "王五"])

    def test_comma_does_not_chain_outside_list_or_on_non_names(self) -> None:
        for text, only in (("患者王建国，男，56岁，因发热入院。", ["王建国"]),
                           ("患者王建国，女性，56岁。", ["王建国"]),
                           ("患者：王建国，男，56岁。", ["王建国"]),
                           ("特困学生：张三，男，13岁。", ["张三"]),
                           ("患者王建国，李医生查房。", ["王建国"])):
            self.assertEqual([x.name for x in detect(text, "all")], only, text)


def scores(text: str, domain: str) -> List[Tuple[str, int]]:
    return [(h.name, h.score) for h in detect(text, domain)]


class RightScoreTest(unittest.TestCase):
    """方案 2.1：右边界分表，UNK（后接普通汉字）不再一票否决。"""

    def rs(self, text: str, name: str, name_len: int = 3) -> int:
        return gn.right_score(text, text.index(name) + len(name), LEX, name_len)

    def test_score_table(self) -> None:
        self.assertEqual(self.rs("王建国（男，56岁）", "王建国"), 3)
        self.assertEqual(self.rs("王建国同志受到处分", "王建国"), 3)
        self.assertEqual(self.rs("王建国同学成绩优秀", "王建国"), 3)
        self.assertEqual(self.rs("王建国，男，56岁", "王建国"), 3)
        self.assertEqual(self.rs("王建国。", "王建国"), 2)
        self.assertEqual(self.rs("患者王建国", "王建国"), 2)           # 行尾
        self.assertEqual(self.rs("王建国等5人", "王建国"), 2)          # right_strong 新增“等”
        self.assertEqual(self.rs("王建国昨日出院", "王建国"), 2)       # TIME
        self.assertEqual(self.rs("王建国近期情绪低落", "王建国"), 2)
        self.assertEqual(self.rs("王建国凌晨巡视", "王建国"), 2)
        self.assertEqual(self.rs("王建国家属来访", "王建国"), 2)       # KIN
        self.assertEqual(self.rs("王建国本人同意", "王建国"), 2)
        self.assertEqual(self.rs("王建国在病房", "王建国", 3), 2)      # FUNC1：三字名 2 分
        self.assertEqual(self.rs("王丽在病房", "王丽", 2), 1)          # FUNC1：两字名 1 分
        self.assertEqual(self.rs("王建国执行医嘱", "王建国"), 1)       # right_weak
        self.assertEqual(self.rs("王建国班上同学", "王建国"), gn.VETO)  # ORG_END（班）
        self.assertEqual(self.rs("李渡镇政府", "李渡"), gn.VETO)
        self.assertEqual(self.rs("王建国2床", "王建国"), gn.VETO)       # 数字
        self.assertEqual(self.rs("王建国ABC", "王建国"), gn.VETO)       # 字母
        self.assertEqual(self.rs("王建国行冠脉造影", "王建国"), gn.UNK)  # 其他汉字
        self.assertEqual(self.rs("王建国同学们好", "王建国"), gn.UNK)    # “同学们”不是身份括注，也不是时间词

    def test_unknown_three_char_needs_given_chars_and_not_common_word(self) -> None:
        # 末字 + 后一字是常见二字词：“孙丽责任心”不能取“孙丽责”
        self.assertEqual(scores("责任护士孙丽责任心不强。", "hospital"), [("孙丽", 5)])
        # 名字用字不在常见名用字表：三字候选否决（路途遥、房颤发、左侧肢……）
        for text in ("患者路途遥远。", "患者房颤发作。", "患者左侧肢体无力。", "患者冷汗淋漓。", "患者戴眼镜后视力改善。", "患者伍德灯检查。",
                     "患者米饭摄入量不足。", "患者沙丁胺醇吸入后缓解。", "患者付款后离院。", "患者柯氏评分偏高。", "患者季节性发作。"):
            self.assertEqual(detect(text, "hospital"), [], text)
        # 其他历史上暴露过的误报：母亲长、孙丽责、原记录、明确夜、谈话记、费用分、费用问
        for text in ("患者母亲长期陪护。", "患者原记录缺失。", "患者明确夜间症状。", "患者谈话记录见附页。", "患者费用分摊见附表。",
                     "患者费用问题已沟通。"):
            self.assertEqual(detect(text, "hospital"), [], text)

    def test_unknown_bonus_by_surname_tier_and_given_chars(self) -> None:
        # 三字名 UNK：常见姓加 1 分（弱锚点 2 + 1 + 形态 2 = 5，P1）；少见姓加 0 分（2 + 0 + 1 = 3，不报）
        self.assertEqual(scores("患者王建国行冠脉造影术。", "hospital"), [("王建国", 5)])
        self.assertEqual(scores("患者洪建国行冠脉造影术。", "hospital"), [])
        # 强锚点：同样的写法升到 P0
        self.assertEqual(scores("值班护士王建国私自离岗。", "hospital"), [("王建国", 6)])
        # 两字名 UNK：弱锚点不报；强锚点且名字用字在常见名用字表里才 5 分
        self.assertEqual(scores("患者王伟行冠脉造影术。", "hospital"), [])
        self.assertEqual(scores("值班护士王伟私自离岗。", "hospital"), [("王伟", 5)])

    def test_ambiguous_surname_requires_punctuation_or_identity_bracket(self) -> None:
        # 弱锚点（患者，2 分）下歧义姓仍须右边界是标点或身份括注；强锚点下的三字名见 test_ambiguous_three_char_names_with_strong_anchor
        self.assertEqual(scores("患者关晓彤（住院号123456）。", "hospital"), [("关晓彤", 5)])
        self.assertEqual(scores("患者：关晓彤，住院号123456。", "hospital"), [("关晓彤", 7)])   # “患者：”是强锚点（3 分）
        self.assertEqual(detect("患者关晓彤对处置不满。", "hospital"), [])
        self.assertEqual(detect("患者关晓彤昨日出院。", "hospital"), [])
        # 强锚点下两字名仍须右边界是标点或身份括注
        self.assertEqual(detect("当班护士关彤未执行双人核对。", "hospital"), [])
        # “和家庭”不是姓名
        self.assertEqual(detect("本学期，学校对单亲家庭学生和家庭经济困难学生建立了一人一档。", "k12_new"), [])

    def test_ambiguous_three_char_names_with_strong_anchor(self) -> None:
        """歧义姓（常、关、祝、焦、单、管、安、康、宁）的三字名在强锚点（>= 3）下按常见姓打分；和、向、来等功能字歧义姓不放宽。"""
        for name in ("常秀芳", "关晓峰", "祝丽华", "焦志刚", "单丽娟", "管玉兰", "安秀英"):
            self.assertEqual(scores(f"当班护士{name}未执行双人核对。", "hospital"), [(name, 7)], name)
        self.assertEqual(scores("家庭经济困难学生关晓峰申请补助。", "k12_new"), [("关晓峰", 7)])
        for text in ("患者和家属沟通。", "患者平均住院日缩短。", "病人关心的是费用。", "管理人员安排到位。",
                     "本学期，学校对单亲家庭学生和家庭经济困难学生建立了一人一档。"):
            self.assertEqual(detect(text, "hospital" if "学校" not in text else "k12_new"), [], text)

    def test_org_end_character_vetoes(self) -> None:
        for text in ("孤儿学生：雷锋班、焦裕禄班各1人。", "特困学生：高一、高二各2人。",
                     "建档立卡户学生：高一（3）班、高二（5）班各2人。", "特困学生名单：高一班、高二班。"):
            self.assertEqual(detect(text, "k12_new"), [], text)
        self.assertEqual(detect("患者李渡镇居民，因胸痛入院。", "hospital"), [])

    def test_func1_time_kin_three_char_p0_two_char_p1_or_none(self) -> None:
        self.assertEqual(scores("患者王建国在病房跌倒。", "hospital"), [("王建国", 6)])
        self.assertEqual(detect("患者王丽在病房跌倒。", "hospital"), [])
        self.assertEqual(scores("患者王建国昨日出院。", "hospital"), [("王建国", 6)])
        self.assertEqual(scores("患者王丽昨日出院。", "hospital"), [("王丽", 5)])
        self.assertEqual(scores("患者王建国家属对处理结果不满。", "hospital"), [("王建国", 6)])
        self.assertEqual(scores("值班护士周晓梅凌晨巡视时发现异常。", "hospital"), [("周晓梅", 7)])
        # 末字与后面时间词的首字重合：取两字
        self.assertEqual(scores("患者孙丽明日出院。", "hospital"), [("孙丽", 5)])

    def test_exact_stopword_needs_strong_evidence_and_loses_one_point(self) -> None:
        for name in ("刘海", "林海", "黎明", "高峰"):
            self.assertEqual(detect(f"患者{name}术后发热。", "hospital"), [], name)
            self.assertEqual(scores(f"患者{name}，男，56岁。", "hospital"), [(name, 5)], name)
        # 职务称谓左边界也是强证据（国企处分框架）
        self.assertEqual(scores("给予财务部原副部长刘海党内严重警告处分。", "soe_new"), [("刘海", 6)])
        self.assertEqual(detect("对刘海给予记过处分。", "soe_new"), [])
        # 整词只屏蔽整词，不屏蔽三字扩展
        self.assertEqual(scores("患者刘海涛，男，56岁。", "hospital"), [("刘海涛", 7)])

    def test_soft_given_only_in_three_char_names(self) -> None:
        self.assertEqual(scores("患者王和平，男，56岁。", "hospital"), [("王和平", 6)])
        self.assertEqual(scores("患者马会芳，男，56岁。", "hospital"), [("马会芳", 6)])
        self.assertEqual(detect("患者王和，男，56岁。", "hospital"), [])   # 两字名里出现软字直接拒绝
        self.assertEqual(detect("患者李年，男，56岁。", "hospital"), [])
        # 软字名在 UNK 下不享受加分：弱锚点 + 普通动词不报
        self.assertEqual(detect("患者王和平建议出院。", "hospital"), [])

    def test_compound_four_char_names_try_full_length_first(self) -> None:
        self.assertEqual(scores("患者欧阳明月术后发热。", "hospital"), [("欧阳明月", 6)])
        self.assertEqual(scores("患者：司马晓月，住院号123456。", "hospital"), [("司马晓月", 7)])
        self.assertEqual(detect("患者欧阳明显好转。", "hospital"), [])
        self.assertEqual(detect("患者欧阳，男，56岁。", "hospital"), [])   # 复姓本身不是姓名

    def test_bigram_veto_also_applies_to_two_char_candidates(self) -> None:
        self.assertEqual(detect("值班护士李明显缺乏经验。", "hospital"), [])

    def test_confusable_names_exact_scores(self) -> None:
        for raw in read_list(FIXTURES / "confusable_names.txt"):
            name, expect = raw.split("|")
            self.assertEqual(scores(f"患者{name}，男，56岁。", "hospital"), [(name, int(expect))], name)


class ChainAndNewAnchorTest(unittest.TestCase):
    """并列项（括注可跳过）、K12 角色锚点、国企职务称谓框架。"""

    def test_chain_skips_parenthetical(self) -> None:
        text = "低保家庭学生周梓涵（三年级）、吴雨桐（五年级）获得资助。"
        self.assertEqual([h.name for h in detect(text, "k12_new")], ["周梓涵", "吴雨桐"])
        text2 = "涉事医生：赵立新（主治医师）、钱敏（住院医师）。"
        self.assertEqual(scores(text2, "hospital"), [("赵立新", 7), ("钱敏", 6)])

    def test_etc_is_strong_right_boundary_and_names_are_masked(self) -> None:
        text = "对低保家庭学生周梓涵、吴雨桐等5人发放助学金。"
        hits = [h for h in gn.find_names(text, ANCHORS["k12_new"], LEX) if not h.pseudo]
        self.assertEqual([(h.name, h.score >= gn.SCORE_HIGH) for h in hits], [("周梓涵", True), ("吴雨桐", True)])
        table = gn.NameTable()
        table.add_hits(hits)
        self.assertEqual(table.mask(text), "对低保家庭学生〔姓名1〕、〔姓名2〕等5人发放助学金。")

    def test_k12_role_and_bare_anchors(self) -> None:
        self.assertEqual(scores("单亲家庭学生陈子豪近期情绪低落。", "k12_new"), [("陈子豪", 8)])
        self.assertEqual(scores("特困学生张伟获得资助。", "k12_new"), [("张伟", 6)])
        self.assertEqual(detect("家庭经济困难，母亲长期无业。", "k12_new"), [])      # 裸身份词不再认逗号
        self.assertEqual(detect("三年级（2）班有留守儿童三人。", "k12_new"), [])
        # 受处分类写法默认不报（已知局限 6）
        self.assertEqual(detect("因打架受到警告处分的学生孙浩宇已写出检查。", "k12_new"), [])

    def test_soe_title_frame(self) -> None:
        self.assertEqual(scores("给予副部长张伟撤职处分。", "soe_new"), [("张伟", 7)])
        self.assertEqual(scores("对物资公司副总经理王和平给予记过处分。", "soe_new"), [("王和平", 7)])
        self.assertEqual(scores("给予财务部原副部长陈建国党内严重警告处分。", "soe_new"), [("陈建国", 8)])
        for text in ("对时任总经理给予警告。", "对项目经理给予警告处分。", "对贺州分公司给予通报批评。", "对相关责任人给予警告。"):
            self.assertEqual(detect(text, "soe_new"), [], text)


class NameTableCutTest(unittest.TestCase):
    """不切开姓名的截取、已截断姓名残片的遮蔽（医院、国企、中小学三个引擎共用）。"""

    def make(self) -> "gn.NameTable":
        t = gn.NameTable()
        t.add("张丽丽")
        t.add("王建国")
        return t

    def test_cut_extends_boundaries_to_whole_names(self) -> None:
        t = self.make()
        text = "当班护士张丽丽未执行双人核对，患者王建国术后发热。"
        s = text.index("张丽丽") + 1          # 起点落在姓名中间
        e = text.index("王建国") + 1          # 终点落在另一个姓名中间
        out = t.cut(text, s, e)
        self.assertEqual(out, "〔姓名1〕未执行双人核对，患者〔姓名2〕")
        self.assertNotIn("丽丽", out)
        self.assertNotIn("建国", out)
        self.assertEqual(t.cut(text, 0, 4), "当班护士")
        self.assertEqual(t.cut(text, -5, 3), "当班护")

    def test_cut_trims_hanging_surname_fragment(self) -> None:
        """方案 7：摘录以“、，：（”加 1～2 个汉字结尾且首字是姓氏、片段不是已登记姓名时，回退到分隔符，不露出半个姓名。"""
        text = "涉事医生：赵立新（主治医师）、钱敏（住院医师）。"
        i = text.index("钱")
        t = gn.NameTable()
        t.add("赵立新")
        self.assertEqual(t.cut(text, 0, i + 1), "涉事医生：〔姓名1〕（主治医师）、")      # 截在“钱”上
        self.assertEqual(t.cut(text, 0, i + 2), "涉事医生：〔姓名1〕（主治医师）、")      # 截在“钱敏”之后但尚未登记：两个字都不露
        # 摘录到原文末尾：不回退；后项“钱敏”虽没登记，但紧跟在已登记姓名的并列尾巴上（“、钱敏（”），也一并遮蔽（宁可多遮）
        self.assertTrue(t.cut(text, 0, len(text)).endswith("、〔姓名2〕（住院医师）。"))
        t.add("钱敏")
        self.assertEqual(t.cut(text, 0, i + 1), "涉事医生：〔姓名1〕（主治医师）、〔姓名2〕")   # 已登记：整个并进来再遮蔽
        # 非姓氏开头的片段不回退
        self.assertEqual(gn.NameTable().cut("会议研究，决定如下。", 0, 8), "会议研究，决定如")
        self.assertEqual(gn.NameTable().cut("会议研究，决定", 0, 7), "会议研究，决定")

    def test_second_name_after_parenthetical_is_recognised_and_masked(self) -> None:
        text = "涉事医生：赵立新（主治医师）、钱敏（住院医师）。"
        hits = gn.find_names(text, ANCHORS["hospital"], LEX)
        self.assertEqual([h.name for h in hits], ["赵立新", "钱敏"])
        t = gn.NameTable()
        t.add_hits(hits)
        self.assertEqual(t.mask(text), "涉事医生：〔姓名1〕（主治医师）、〔姓名2〕（住院医师）。")

    def test_cut_with_empty_table_is_plain_slice(self) -> None:
        self.assertEqual(gn.NameTable().cut("张丽丽未执行", 1, 4), "丽丽未")

    def test_mask_excerpt_relocates_in_source_text(self) -> None:
        t = self.make()
        text = "拟对张丽丽给予通报批评并扣减当月绩效。"
        piece = text[text.index("丽丽给予"):]          # 已经切开了姓名的摘录
        self.assertEqual(t.mask_excerpt(piece, text), "〔姓名1〕给予通报批评并扣减当月绩效。")
        self.assertEqual(t.mask_excerpt(piece[:6] + "……", text), "〔姓名1〕给予通报……")
        self.assertEqual(t.mask_excerpt("", text), "")

    def test_mask_fragment_masks_truncated_name_at_both_ends(self) -> None:
        t = self.make()
        self.assertEqual(t.mask_fragment("……低保户王小"), "……低保户王小")  # 非登记姓名
        t.add("王小明")
        self.assertEqual(t.mask_fragment("……低保户王小"), "……低保户〔姓名3〕")
        self.assertEqual(t.mask_fragment("小明同学成绩优秀"), "〔姓名3〕同学成绩优秀")
        self.assertEqual(t.mask_fragment("王小明同学"), "〔姓名3〕同学")
        self.assertEqual(t.mask_fragment("没有姓名"), "没有姓名")
        self.assertEqual(len(t), 3)  # 遮蔽不新增姓名

    def test_mask_excerpt_falls_back_to_fragment_masking(self) -> None:
        t = self.make()
        self.assertEqual(t.mask_excerpt("丽丽未执行", "与这段摘录无关的原文"), "〔姓名1〕未执行")  # 退化为残片遮蔽
        self.assertEqual(t.mask_excerpt("患者王建国", None), "患者〔姓名2〕")


class NameTableTest(unittest.TestCase):
    def test_numbering_by_first_appearance(self) -> None:
        t = gn.NameTable()
        self.assertEqual(t.placeholder("张丽丽"), "〔姓名1〕")
        self.assertEqual(t.placeholder("王建国"), "〔姓名2〕")
        self.assertEqual(t.placeholder("张丽丽"), "〔姓名1〕")
        self.assertEqual(t.names(), ["张丽丽", "王建国"])
        self.assertIn("王建国", t)

    def test_mask_longest_first_and_single_pass(self) -> None:
        t = gn.NameTable()
        t.add("张丽")
        t.add("张丽丽")
        self.assertEqual(t.mask("张丽丽与张丽同行"), "〔姓名2〕与〔姓名1〕同行")
        self.assertEqual(t.mask(t.mask("张丽丽")), "〔姓名2〕")
        self.assertEqual(gn.NameTable().mask("没有姓名"), "没有姓名")

    def test_mask_after_add_hits(self) -> None:
        t = gn.NameTable()
        t.add_hits(gn.find_names("护士张丽丽未执行双人核对。", ANCHORS["hospital"], LEX))
        self.assertEqual(t.mask("张丽丽当晚独自值守"), "〔姓名1〕当晚独自值守")


class MergeIssuesTest(unittest.TestCase):
    def test_merge_same_key_and_count(self) -> None:
        a = {"id": "HOS-031", "line": 3, "excerpt": "患者〔姓名1〕术后发热", "message": "m", "level": "P0"}
        b = dict(a)
        c = dict(a, line=4)
        d = dict(a, level="P1")
        merged = gn.merge_issues([a, b, c, d])
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["count"], 3)
        self.assertEqual(merged[0]["level"], "P0")
        self.assertEqual(merged[1]["count"], 1)
        self.assertNotIn("count", a)  # 不改动入参


# ---------------------------------------------------------------------------
# 2. 召回（按语境类别分组）
# ---------------------------------------------------------------------------
# 每个类别是一组“名字之后接什么”的句式（domain 指用哪套锚点）。不同类别的右边界证据不同，召回差别很大，
# 合并成一个数字会把弱类别藏起来，所以按类别单独统计、单独断言下限。
# “词表外动词或名词”一类用的都是不在右边界词表里的后续（接受、自述、服药、私自离岗……）；
# 其中“拒绝”“突发”是方案点名的例子，本身在右边界词表里，作对照保留。
CATEGORIES: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "标点与括注": (
        ("hospital", "患者{n}，男，56岁，因胸痛入院。"), ("hospital", "患者：{n}，住院号123456。"),
        ("hospital", "{n}（住院号20231234）于3月5日入院。"), ("soe", "拟提拔人选名单：{n}。"),
        ("k12_new", "特困学生名单：{n}。"),
    ),
    "功能字": (
        ("hospital", "患者{n}在病房跌倒。"), ("hospital", "患者{n}对处置不满。"), ("hospital", "患者{n}被安排转科。"),
        ("hospital", "患者{n}与家属沟通。"), ("hospital", "患者{n}因发热入院。"),
    ),
    "时间词": (
        ("hospital", "患者{n}昨日出院。"), ("hospital", "值班护士{n}凌晨巡视时发现异常。"),
        ("hospital", "患者{n}近期反复发热。"), ("hospital", "患者{n}入院后完善检查。"), ("hospital", "当班护士{n}今晚值班。"),
    ),
    "亲属与所属": (
        ("hospital", "患者{n}家属对处理结果不满。"), ("hospital", "患者{n}本人要求出院。"),
        ("k12_new", "低保家庭学生{n}母亲长期患病。"), ("k12_new", "单亲家庭学生{n}家长近期来校。"),
    ),
    "词表外动词或名词": (
        ("hospital", "患者{n}接受抗感染治疗。"), ("hospital", "患者{n}自述胸闷三天。"), ("hospital", "患者{n}服药后出现皮疹。"),
        ("hospital", "值班护士{n}私自离岗。"), ("hospital", "患者{n}拒绝签字。"), ("hospital", "患者{n}突发胸痛。"),
    ),
    "并列名单": (
        ("k12_new", "特困学生周梓涵、{n}等5人获得资助。"), ("k12_new", "低保家庭学生{n}（三年级）、吴雨桐（五年级）。"),
        ("k12_new", "低保家庭学生吴雨桐（五年级）、{n}（六年级）。"), ("soe", "拟提拔人选名单：马建国、{n}、周杰。"),
        ("hospital", "涉事医生：赵立新（主治医师）、{n}（住院医师）。"),
    ),
    "职务框架": (
        ("soe_new", "给予副部长{n}撤职处分。"), ("soe_new", "给予财务部原副部长{n}党内严重警告处分。"),
        ("soe_new", "对物资公司副总经理{n}给予记过处分。"), ("soe", "给予{n}同志党内警告处分。"), ("soe", "对{n}给予记过处分。"),
    ),
    "K12身份加学生": (
        ("k12_new", "单亲家庭学生{n}近期情绪低落。"), ("k12_new", "特困学生{n}获得资助。"),
        ("k12_new", "低保家庭学生{n}本学期获得资助。"), ("k12_new", "留守儿童{n}由祖父母照看。"),
    ),
}
# 各类别各名字集的下限：(整体召回下限, 高置信 P0 比例下限)。取实测值向下取整到 5%，不得为了通过而调低；
# 要调低必须写明原因（例如某类写法按设计就只给 P1）。
#   - “功能字”“词表外动词或名词”两类里，两字名在弱锚点（患者、护士）后按设计不报，所以召回和 P0 比例都明显低；
#   - “词表外动词或名词”的 P0 比例很低是设计结果：这类写法只靠“名字用字 + 常见姓”撑起来，三字名 P1，强锚点才到 P0；
#   - “人工名”样本小（42 个），含歧义姓、软字名、少见姓，下限更低。
FLOORS: Dict[str, Dict[str, Tuple[float, float]]] = {
    "标点与括注": {"夹具名": (0.95, 0.90), "程序化生成": (0.95, 0.95), "人工名": (1.00, 0.75)},
    "功能字": {"夹具名": (0.85, 0.60), "程序化生成": (0.80, 0.55), "人工名": (0.75, 0.30)},
    "时间词": {"夹具名": (0.90, 0.70), "程序化生成": (0.95, 0.75), "人工名": (0.75, 0.50)},
    "亲属与所属": {"夹具名": (0.90, 0.75), "程序化生成": (0.95, 0.75), "人工名": (0.75, 0.50)},
    "词表外动词或名词": {"夹具名": (0.65, 0.20), "程序化生成": (0.70, 0.15), "人工名": (0.40, 0.10)},
    "并列名单": {"夹具名": (0.95, 0.90), "程序化生成": (0.95, 0.95), "人工名": (0.95, 0.85)},
    "职务框架": {"夹具名": (0.95, 0.95), "程序化生成": (0.95, 0.95), "人工名": (1.00, 1.00)},
    "K12身份加学生": {"夹具名": (0.90, 0.80), "程序化生成": (0.95, 0.85), "人工名": (0.75, 0.65)},
}


def _parse_given_names() -> Tuple[str, List[str]]:
    section = ""
    surnames = ""
    givens: List[str] = []
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
    """60 个常见姓 × 名字用字（单字名与两字名），按固定步长抽样（四分之一），可复现。"""
    surnames, givens = _parse_given_names()
    out: List[str] = []
    for i, s in enumerate(surnames):
        for j, g in enumerate(givens):
            if (i * 7 + j) % 4 == 0:
                out.append(s + g)
    return list(dict.fromkeys(out))


def name_sets() -> Dict[str, List[str]]:
    return {"夹具名": read_list(FIXTURES / "names.txt"), "程序化生成": generated_names(),
            "人工名": read_list(FIXTURES / "manual_names.txt")}


def measure_category(cat: str, names: Sequence[str]) -> Tuple[int, int, int, Dict[str, int]]:
    """返回 (总次数, 识别次数, 高置信次数, 每个名字被漏掉的次数)。"""
    total = found = high = 0
    missed: Dict[str, int] = {}
    for name in names:
        for domain, tpl in CATEGORIES[cat]:
            total += 1
            hits = [h for h in detect(tpl.format(n=name), domain) if h.name == name]
            if hits:
                found += 1
                if max(h.score for h in hits) >= gn.SCORE_HIGH:
                    high += 1
            else:
                missed[name] = missed.get(name, 0) + 1
    return total, found, high, missed


def diagnose(name: str) -> str:
    """给未识别的姓名归类原因，仅用于日志。"""
    if not gn.has_surname_prefix(name, LEX):
        return "非姓氏开头"
    if name in LEX.stopwords_exact:
        return "与整词排除词同形（无强证据）"
    if any(name.startswith(w) for w in LEX.stop_index.get(name[0], ())):
        return "以前缀排除词起首"
    compound = name[:2] in LEX.compound and len(name) >= 3
    given = name[2:] if compound else name[1:]
    if any(c in LEX.nongiven for c in given):
        return "名字含非名用字"
    if any(c in LEX.soft_given for c in given) and not compound and len(name) == 2:
        return "两字名含软字"
    if name[-1] in LEX.place_end:
        return "尾字是地名机构字"
    if len(name) == 2 and name[-1] in LEX.place_end_2char:
        return "两字名尾字是地名字"
    if not compound and name[0] in LEX.ambiguous:
        return "歧义姓（分数不够）"
    if not all(c in LEX.given or c in LEX.soft_given for c in given):
        return "名字用字不在常见名用字表"
    if not compound and name[0] in LEX.surnames_rare:
        return "少见姓（分数不够）"
    return "其他（右边界或形态）"


class RecallTest(unittest.TestCase):
    def test_name_files_sane(self) -> None:
        sets = name_sets()
        fixture = sets["夹具名"]
        self.assertGreaterEqual(len(fixture), 400)
        self.assertEqual(len(fixture), len(set(fixture)), "夹具姓名有重复")
        self.assertGreaterEqual(len(sets["人工名"]), 40)
        self.assertEqual(len(sets["人工名"]), len(set(sets["人工名"])))
        surnames, givens = _parse_given_names()
        self.assertEqual(len(surnames), 60)
        self.assertEqual(len(set(surnames)), 60)
        self.assertGreaterEqual(len(givens), 150)
        gen = sets["程序化生成"]
        self.assertGreaterEqual(len(gen), 1500)
        self.assertTrue(all(n[0] in surnames for n in gen))

    def test_fixture_names_not_in_stopwords(self) -> None:
        for label, names in name_sets().items():
            if label == "程序化生成":
                continue    # 姓 × 名的机械组合里难免有与普通词同形的（黄河、马力），不在这里断言
            clash = [n for n in names if n in LEX.stopwords]
            self.assertEqual(clash, [], f"{label}：前缀排除词表里出现了夹具姓名：{clash}")
            starts = [n for n in names if any(n.startswith(w) for w in LEX.stop_index.get(n[0], ()))]
            # 已知局限 3：“胡子”（胡子拉碴）是前缀排除词，所以姓名“胡子轩”漏报，登记在这里，不要再往前缀表里添这类词
            self.assertEqual([n for n in starts if n != "胡子轩"], [], f"{label}：夹具姓名以前缀排除词起首：{starts}")

    def test_recall_by_category(self) -> None:
        sets = name_sets()
        report = ["", "类别 × 名字集的召回率（识别次数 / 总次数）与 P0 比例（高置信次数 / 总次数）："]
        failures: List[str] = []
        for cat in CATEGORIES:
            for label, names in sets.items():
                total, found, high, missed = measure_category(cat, names)
                rec, p0 = found / total, high / total
                report.append(f"  {cat}｜{label}：召回 {found}/{total} = {rec:.1%}，P0 {high}/{total} = {p0:.1%}")
                floor = FLOORS.get(cat, {}).get(label)
                if floor is None:
                    failures.append(f"{cat}｜{label} 没有登记下限（实测召回 {rec:.1%}，P0 {p0:.1%}）")
                    continue
                if rec < floor[0]:
                    failures.append(f"{cat}｜{label} 召回 {rec:.1%} 低于下限 {floor[0]:.0%}")
                if p0 < floor[1]:
                    failures.append(f"{cat}｜{label} P0 比例 {p0:.1%} 低于下限 {floor[1]:.0%}")
        sys.stderr.write("\n".join(report) + "\n")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_missed_names_are_explained(self) -> None:
        """全部类别合计里，按原因归类打印漏报的姓名（日志用）；并断言“所有句式都识别不出”的夹具姓名都有可解释的原因。"""
        names = name_sets()["夹具名"]
        per_name = sum(len(v) for v in CATEGORIES.values())
        never: Dict[str, int] = {}
        for cat in CATEGORIES:
            _t, _f, _h, missed = measure_category(cat, names)
            for n, c in missed.items():
                never[n] = never.get(n, 0) + c
        always = [n for n, c in never.items() if c >= per_name]
        by_reason: Dict[str, List[str]] = {}
        for n in always:
            by_reason.setdefault(diagnose(n), []).append(n)
        lines = [f"夹具名里所有句式都识别不出的 {len(always)} 个（共 {len(names)} 个）："]
        for reason, ns in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"  [{reason}] {len(ns)} 个：{'、'.join(ns[:40])}{'…' if len(ns) > 40 else ''}")
        sys.stderr.write("\n" + "\n".join(lines) + "\n")
        self.assertNotIn("其他（右边界或形态）", by_reason, "有无法归因的漏报：" + str(by_reason.get("其他（右边界或形态）")))
        self.assertLessEqual(len(always), len(names) * 0.05)

    def test_manual_names_found_in_strongest_context(self) -> None:
        """人工名在最强语境（身份括注右边界）里必须都识别出来，并给出得分日志。"""
        miss = []
        for n in read_list(FIXTURES / "manual_names.txt"):
            hits = [h for h in detect(f"患者{n}，男，56岁。", "hospital") if h.name == n]
            if not hits:
                miss.append(n)
        self.assertEqual(miss, [])

    def test_confusable_names_each_found_somewhere(self) -> None:
        for name in ("高明", "白雪", "江涛", "金晶", "于洋", "关晓彤", "欧阳明"):
            ok = any(h.name == name for tpls in CATEGORIES.values() for dom, t in tpls
                     for h in detect(t.format(n=name), dom))
            self.assertTrue(ok, f"{name} 在任何句式下都没有识别出来")

    def test_no_regression_against_head_baseline(self) -> None:
        """与 HEAD（d07b657）引擎实跑数字对照：同一名字集（names.txt）、同一句式，共享层命中数不得低于 HEAD。
        锚点在本文件里有等价写法的行才断言（医院三条、国企、K12）；引擎层才能断言的细节留给各引擎自己的测试。"""
        base = json.loads((FIXTURES / "head_baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(base["commits"]["HEAD"][:7], "d07b657")
        self.assertIn("v1.2.0", base["commits"])
        names = read_list(FIXTURES / base["names_file"].split("/")[-1])
        self.assertEqual(len(names), base["names_count"])
        domain_of = {"hospital": "hospital", "soe": "soe", "k12": "k12_new"}
        lines = ["", "与 HEAD 基线对照（命中名字数，括号内 P0）："]
        for row in base["rows"]:
            tpl = row["template"]
            dom = domain_of[row["engine"]]
            if dom == "soe" and ("副部长" in tpl or "副总经理" in tpl):
                dom = "soe_new"
            found = high = 0
            for n in names:
                hs = [h for h in detect(tpl.format(n=n), dom) if h.name == n]
                if hs:
                    found += 1
                    if max(h.score for h in hs) >= gn.SCORE_HIGH:
                        high += 1
            head = row["HEAD"]["detected"]
            lines.append(f"  {row['rule']} {tpl}：HEAD {head}（P0 {row['HEAD']['p0']}）→ 现 {found}（P0 {high}）")
            self.assertGreaterEqual(found, head, f"{tpl}：命中数 {found} 低于 HEAD 的 {head}")
        sys.stderr.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# 3. 精度
# ---------------------------------------------------------------------------
def _doc_files() -> List[Path]:
    seen: Dict[str, Path] = {}
    for base, pat in ((ROOT / "skills", "*/references/**/*.md"), (ROOT / "shared", "**/*.md")):
        for p in sorted(base.glob(pat)):
            text = p.read_text(encoding="utf-8-sig", errors="replace")
            seen.setdefault(text, p)  # references/_shared 下是 shared 的副本，同内容只扫一份
    return sorted(seen.values())


class PrecisionTest(unittest.TestCase):
    def test_docs_only_report_registered_example_names(self) -> None:
        allowed = set(read_list(FIXTURES / "allowed_names.txt"))
        files = _doc_files()
        self.assertGreater(len(files), 20)
        found: Dict[str, List[str]] = {}
        for p in files:
            for no, line in enumerate(p.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
                for h in detect(line, "all"):
                    found.setdefault(h.name, []).append(f"{p.relative_to(ROOT).as_posix()}:{no}")
        unexpected = {n: locs[:3] for n, locs in found.items() if n not in allowed}
        self.assertEqual(unexpected, {}, "文档里识别出未登记的姓名（先判断是误识别还是示例姓名）")
        stale = sorted(allowed - set(found))
        if stale:
            sys.stderr.write(f"\n提示：allowed_names.txt 里这些姓名在文档中已不再出现：{'、'.join(stale)}\n")


# ---------------------------------------------------------------------------
# 4. 对抗探针
# ---------------------------------------------------------------------------
HOSPITAL_CLEAN = [
    "值班医师曾多次未按时交班。", "患者黄疸，女性多见。", "患者高热，男性居多。", "患者沈阳籍，男，因肺炎入院。",
    "患者平均住院日缩短。", "值班医师严格按流程处置。", "当班护士任务繁重，需增配人手。",
    "患者何时入院需登记。", "患者于入院当日完成评估。", "患者于术后第3天出现发热。", "患者于次日清晨好转。",
    "患者家属对护理服务表示满意。", "患者高度紧张，予心理疏导。", "患者安全管理制度已修订。",
    "患者信息录入不完整。", "患者康复训练每日两次。", "患者周边环境需保持整洁。", "患者范围覆盖全院。",
    "患者满意度调查结果见附表。", "患者程序性镇静需签署同意书。", "患者曾经发生过跌倒。", "患者全名核对后方可给药。",
    "患者何种情况需转诊，详见流程。", "护士长严格执行查对制度。", "值班医生高度重视该病例。",
    "责任护士安全意识不强。", "管床医生信息录入不及时。", "夜班护士范围内巡视不到位。", "主管医师周边环境巡查不足。",
    "当班护士程序执行不到位。", "患者平稳度过围手术期。", "患者常规检查未见异常。", "患者安静入睡。",
    "患者关节疼痛加重。", "患者单侧肢体无力。", "患者解除约束后情绪平稳。", "患者焦虑情绪明显。",
    "患者全程配合治疗。", "患者信任医护团队。", "患者时常出现头晕。", "患者那天晚间出现胸闷。",
    "患者都能按时服药。", "患者成年后首次发病。", "患者黄色分泌物增多。", "患者项目检查费用见表。",
    "患者全部转入ICU。", "患者展示出明显的康复意愿。", "患者位置固定后拍片。", "患者那里疼痛明显。",
    "医师初审意见未签字。", "护士单独值班时发生用药遗漏。", "护士常常加班，需调整排班。", "护士管理制度不完善。",
    "护师解释不到位，家属不满。", "医生应对不及时。", "医生成功完成抢救。", "医师由上级医师指导完成操作。",
    "12床患者高热不退。", "3床患者于夜间发生跌倒。", "5床患者安静休息。", "投诉人关于收费问题反映多次。",
    "投诉人高度关注处理进度。", "涉事护士长期休假，未参加培训。", "责任护士曾任科室质控员。",
    "责任医师于术前未履行告知。", "值班医师于夜间接到电话后到场。", "值班医师于凌晨到场。", "值班医师于18时到场。",
    "值班医师于三月值班。", "患者和家属共同签署知情同意。", "患者向值班医师反映疼痛。", "患者支付医疗费用时发现多收。",
    "患者初次就诊时间不详。", "患者年龄较大，需加强看护。", "患者高龄，合并多种基础病。", "患者姓名核对无误。",
    "姓名：见附表。", "患者高血压病史十年。", "患者平卧位休息。", "患者白细胞偏高。", "患者黄疸指数升高。",
    "患者石膏固定后复查。", "患者范围性皮疹，予对症处理。", "患者孙子在床旁陪护。", "患者安心接受治疗。",
    "患者的家属对处置表示理解。", "医师的处置符合规范。", "护士对患者进行了宣教。", "患者家属的意见已记录。",
    "患者对服务表示满意。", "患者洪水般涌入急诊。", "患者赖账不付费用。",
    # 取消右边界一票否决后的误报面（名字用字门槛、常见二字词否决、整词排除词、机构尾字）
    "患者路途遥远，需家属陪同。", "患者房颤发作后转入ICU。", "患者左侧肢体无力三天。", "患者冷汗淋漓，血压下降。",
    "患者戴眼镜后视力改善。", "患者伍德灯检查阳性。", "患者米饭摄入量不足。", "患者沙丁胺醇吸入后缓解。",
    "患者付款后离院。", "患者柯氏评分偏高。", "患者季节性发作。", "患者母亲长期陪护。", "患者原记录缺失。",
    "患者明确夜间症状。", "患者谈话记录见附页。", "患者费用分摊见附表。", "患者费用问题已沟通。",
    "患者刘海术后发热。", "患者黎明时分出现发热。", "患者高峰期血压波动。", "患者张家界旅游后发病。",
    "患者单位同事陪同就诊。", "患者时间观念较差。", "患者公开表示不满。", "患者常见症状为乏力。",
]
HOSPITAL_FLAG = [
    ("患者王建国术后发热。", "王建国"), ("患者：王建国，住院号123456。", "王建国"),
    ("王建国（住院号20231234）于3月5日入院。", "王建国"), ("护士张丽丽未执行双人核对。", "张丽丽"),
    ("由护士张丽丽负责该患者。", "张丽丽"), ("当班护士为张丽丽，已交班。", "张丽丽"),
    ("患者李秀英，女，68岁，因胸痛入院。", "李秀英"), ("12床患者陈美玲诉腹痛。", "陈美玲"),
    ("床号：8，患者刘志强，已办理出院。", "刘志强"), ("投诉人：赵文静，反映候诊时间过长。", "赵文静"),
    ("值班医师吴思远于夜间未到场。", "吴思远"), ("责任护士徐嘉怡擅自离岗。", "徐嘉怡"),
    ("涉事药师孙浩然拒绝签字。", "孙浩然"), ("患儿朱雨桐，女，3岁，发热三天。", "朱雨桐"),
    ("患者胡军因肺炎入院。", "胡军"), ("病人郭靖主诉头晕。", "郭靖"), ("主管医生高俊杰到场处置。", "高俊杰"),
    ("当事护士林诗涵已被约谈。", "林诗涵"), ("患者姓名：罗佳琪", "罗佳琪"),
    ("张丽丽（住院号99887）出院时未取药。", "张丽丽"), ("患者欧阳明，男，因车祸入院。", "欧阳明"),
    ("患者黄晓明出现过敏反应。", "黄晓明"), ("当班护士：于洋，已完成交接。", "于洋"),
    ("患者王建国的家属对处置表示理解。", "王建国"), ("患者赵敏华对处置过程表示不满。", "赵敏华"),
    ("患者王丽的家属来访。", "王丽"), ("17床赵敏华（女，49岁）输液外渗。", "赵敏华"),
    ("患者洪建国术后发热。", "洪建国"), ("患者赖志强，男，56岁。", "赖志强"),
    ("涉事医生：赵立新（主治医师）、钱敏（住院医师）。", "钱敏"), ("涉事医生：赵立新（主治医师）、钱敏（住院医师）。", "赵立新"),
    ("患者王和平，男，56岁。", "王和平"), ("患者刘海，男，56岁。", "刘海"), ("患者王建国行冠脉造影术。", "王建国"),
    ("患者陈美玲家属对处理结果不满。", "陈美玲"), ("值班护士徐嘉怡凌晨巡视时发现异常。", "徐嘉怡"),
    ("患者李秀英在病房跌倒。", "李秀英"), ("患者黄晓明病情加重。", "黄晓明"), ("患者孙浩然跌倒致骨折。", "孙浩然"),
]
SOE_CLEAN = [
    "对林业局给予警告。", "对孙公司给予警告。", "对项目经理给予警告处分。", "唐钢集团（以下简称唐钢）。对唐钢给予警告处分。", "对时任总经理给予警告。",
    "对贺州分公司给予通报批评。", "对董事会办公室给予警告。", "对集团公司给予警告处分。",
    "对李渡镇项目部给予警告。", "对王府井店给予警告处分。", "对工程部给予警告。", "对黄岛项目给予警告处分。",
    "对郑州分公司给予记过。", "对林业公司给予警告。", "对和平路店给予警告处分。", "严禁对违规人员不予处分。",
    "对周边单位给予警告。", "对集团董事会给予嘉奖。", "对有关责任人员给予党内警告处分。", "对相关责任人给予警告。",
    "对赵家庄项目部给予警告。", "对钱塘公司给予警告处分。", "对万科项目部给予警告。", "对时任董事长给予警告处分。",
    "对黄埔分公司给予警告。", "对白云分公司给予通报批评。", "对高铁项目部给予警告处分。",
    "拟提拔人选名单：详见附件。", "裁减人员名单：公司本部各部门。", "考察对象名单：见附表。",
    "名单如下：一分公司、二分公司、三分公司。", "问责名单：项目部、财务部、采购部。",
    "对孙公司的负责人给予警告处分。", "对董事会成员给予警告处分。", "对高管团队给予警告处分。",
    "邓小平理论学习不力的支部受到警告处分", "王府井百货受到警告", "钱江新城项目部被诫勉", "邓小平理论受到警告处分",
    "相关责任人受到党内警告处分。", "洪水防御不力的项目部受到警告。",
    "给予副部长撤职处分。", "对物资公司副总经理给予记过处分。", "对董事长给予警告处分。", "对项目部负责人给予诫勉。",
]
SOE_FLAG = [
    ("给予马建国同志党内警告处分", "马建国"), ("给予周杰记过处分", "周杰"), ("对欧阳明给予记过处分", "欧阳明"),
    ("王强被开除党籍", "王强"), ("对刘志强给予降级处分。", "刘志强"),
    ("经研究，决定给予陈美玲留党察看一年处分。", "陈美玲"), ("赵文静受到严重警告处分。", "赵文静"),
    ("对黄晓明同志给予撤职处分。", "黄晓明"), ("吴思远同志被免职。", "吴思远"), ("会议决定给予徐嘉怡诫勉。", "徐嘉怡"),
    ("拟提拔人选名单：孙浩然、朱雨桐。", "孙浩然"), ("拟提拔人选名单：孙浩然、朱雨桐。", "朱雨桐"),
    ("初步人选名单：郝国梁。", "郝国梁"), ("拟任人选名单为：郭晓东、何欣怡，公示五日。", "何欣怡"),
    ("裁减人员名单：高俊杰、林诗涵、罗佳琪。", "罗佳琪"),
    ("考察对象名单如下：郑博文（男，42岁）、梁志远（男，39岁）。", "梁志远"),
    ("内退人员名单：谢雅琴，宋晓雯。", "宋晓雯"), ("总经理王强同志受到警告处分", "王强"),
    ("会议研究决定王强被开除党籍", "王强"), ("解除劳动合同人员名单：唐梦瑶。", "唐梦瑶"),
    ("分流人员名单：许文博、韩雪梅。", "韩雪梅"), ("经董事会研究，对曹宇航给予开除处分。", "曹宇航"),
    ("彭丽萍被开除公职。", "彭丽萍"), ("会议研究决定，对肖雨轩同志给予诫勉。", "肖雨轩"),
    ("给予副部长张伟撤职处分。", "张伟"), ("对物资公司副总经理王和平给予记过处分。", "王和平"),
    ("给予财务部原副部长刘海党内严重警告处分。", "刘海"), ("给予财务部原副部长陈建国党内严重警告处分。", "陈建国"),
]
K12_CLEAN = [
    "本学期特困学生：一年级、三年级各2人", "低保家庭学生名单：七年级、八年级，详见附表", "同学们积极参与",
    "建档立卡户共计12户，已全部核查。", "单亲家庭学生比例为8%。", "留守儿童名单已按规定渠道报送。",
    "特困学生共计5人，其中七年级2人。", "家庭经济困难学生：已完成认定。", "抑郁症学生已转介至专业机构。",
    "低保家庭学生资助政策宣传到位。", "孤儿学生由学校统一安排。", "违纪处分学生名单由德育处保管。",
    "困难家庭学生每月补助200元。", "受过处分的同学须参加心理辅导。", "班里新来的同学很快融入集体。",
    "请同学们认真阅读。", "高年级同学帮助低年级同学。", "初三同学参加中考冲刺。", "全体同学积极参与。",
    "家庭经济困难学生认定工作按学期开展。", "孤儿、事实无人抚养儿童纳入保障。", "留守儿童：城区3人、乡镇5人。",
    "特困学生：高一、高二各2人。", "孤儿学生：雷锋班、焦裕禄班各1人。", "建档立卡户学生：高一（3）班、高二（5）班各2人。",
    "本学期，学校对留守儿童、单亲家庭学生和家庭经济困难学生建立了一人一档。", "家庭经济困难，母亲长期无业。",
]
K12_FLAG = [
    ("低保家庭学生马小明", "马小明"), ("建档立卡户孙小红同学", "孙小红"), ("单亲家庭的郭晓东同学", "郭晓东"),
    ("特困学生：王建国", "王建国"), ("单亲家庭学生刘志强，需重点关怀。", "刘志强"),
    ("留守儿童名单：陈美玲、杨海涛、赵文静。", "赵文静"), ("低保家庭名单如下：黄晓明、周婷婷。", "周婷婷"),
    ("抑郁症学生吴思远已休学。", "吴思远"), ("多动症学生徐嘉怡，需要个别辅导。", "徐嘉怡"),
    ("自闭症儿童孙浩然由家长陪读。", "孙浩然"), ("受过处分的朱雨桐同学已改正。", "朱雨桐"),
    ("孤儿毛小雨同学得到资助。", "毛小雨"), ("困难家庭学生郭晓东，已纳入帮扶。", "郭晓东"),
    ("家庭经济困难学生：何欣怡、高俊杰。", "高俊杰"), ("离异家庭学生李秀英，情绪低落。", "李秀英"),
    ("建档立卡户林诗涵同学学费已减免。", "林诗涵"), ("低保户的罗佳琪同学已完成资助申请。", "罗佳琪"),
    ("特困供养学生郑博文，由村委会代为监护。", "郑博文"), ("违纪处分：梁志远，已撤销。", "梁志远"),
    ("特困学生名单：谢雅琴、宋晓雯。", "宋晓雯"),
    ("特困学生：张三，李四", "张三"), ("特困学生：张三，李四", "李四"), ("低保家庭学生：赖志强，洪建国", "洪建国"),
    ("对低保家庭学生周梓涵、吴雨桐等5人发放助学金。", "吴雨桐"), ("对低保家庭学生周梓涵、吴雨桐等5人发放助学金。", "周梓涵"),
    ("低保家庭学生周梓涵（三年级）、吴雨桐（五年级）获得资助。", "吴雨桐"),
    ("三年级（2）班单亲家庭学生陈子豪近期情绪波动较大。", "陈子豪"), ("班主任对患有抑郁症的学生刘一诺进行了心理疏导。", "刘一诺"),
]
class AdversarialProbeTest(unittest.TestCase):
    maxDiff = None

    @staticmethod
    def _run_clean(domain: str, sentences: Sequence[str]) -> List[str]:
        if domain.startswith("soe"):
            return [s for s in sentences
                    if any(not h.pseudo and h.score >= gn.SCORE_LOW for h in
                           gn.find_names(s, ANCHORS[domain], LEX, gn.organization_names([s], LEX)))]
        return [s for s in sentences if detect(s, domain)]

    @staticmethod
    def _run_flag(domain: str, cases: Sequence[Tuple[str, str]]) -> List[str]:
        return [f"{s}（应识别{n}）" for s, n in cases if not any(h.name == n for h in detect(s, domain))]

    def test_probe_counts(self) -> None:
        self.assertGreaterEqual(len(HOSPITAL_CLEAN), 60)
        self.assertGreaterEqual(len(SOE_CLEAN), 30)
        self.assertGreaterEqual(len(K12_CLEAN), 20)
        self.assertGreaterEqual(len(HOSPITAL_FLAG), 20)
        self.assertGreaterEqual(len(SOE_FLAG), 20)
        self.assertGreaterEqual(len(K12_FLAG), 20)

    def test_hospital_clean(self) -> None:
        self.assertEqual(self._run_clean("hospital", HOSPITAL_CLEAN), [], "医院：应不报的句子被识别为姓名")

    def test_hospital_flag(self) -> None:
        self.assertEqual(self._run_flag("hospital", HOSPITAL_FLAG), [])

    def test_soe_clean(self) -> None:
        for dom in ("soe", "soe_new"):
            self.assertEqual(self._run_clean(dom, SOE_CLEAN), [], f"国企（{dom}）：应不报的句子被识别为姓名")

    def test_soe_flag(self) -> None:
        self.assertEqual(self._run_flag("soe_new", SOE_FLAG), [])
        # 现有锚点（尚无职务称谓框架）：只要求不含“副部长/副总经理”新写法的那些
        old_only = [c for c in SOE_FLAG if "副部长" not in c[0] and "副总经理" not in c[0]]
        self.assertEqual(self._run_flag("soe", old_only), [])

    def test_k12_clean(self) -> None:
        for dom in ("k12", "k12_new"):
            self.assertEqual(self._run_clean(dom, K12_CLEAN), [], f"中小学（{dom}）：应不报的句子被识别为姓名")

    def test_k12_flag(self) -> None:
        self.assertEqual(self._run_flag("k12_new", K12_FLAG), [])
        # 现有锚点：新增的几条并列、括注写法在现有锚点下本来就能识别的部分
        old_ok = [c for c in K12_FLAG if "吴雨桐" not in c[0] and "陈子豪" not in c[0] and "刘一诺" not in c[0]]
        self.assertEqual(self._run_flag("k12", old_ok), [])

    def test_undefined_abbreviation_reports_p1(self) -> None:
        text = "对唐钢给予警告处分。"
        hits = gn.find_names(text, ANCHORS["soe_new"], LEX, frozenset())
        self.assertEqual([(h.name, h.score, h.maybe_org) for h in hits], [("唐钢", gn.SCORE_LOW, True)])

    def test_task_sentences_exact(self) -> None:
        """方案给定的整组句子：应识别、不应识别各一遍。"""
        flag = [("患者王建国术后发热。", "王建国", "hospital"), ("患者：王建国，住院号123456。", "王建国", "hospital"),
                ("王建国（住院号20231234）于3月5日入院。", "王建国", "hospital"),
                ("护士张丽丽未执行双人核对。", "张丽丽", "hospital"), ("由护士张丽丽负责该患者。", "张丽丽", "hospital"),
                ("当班护士为张丽丽，已交班。", "张丽丽", "hospital"),
                ("给予马建国同志党内警告处分", "马建国", "soe"), ("给予周杰记过处分", "周杰", "soe"),
                ("对欧阳明给予记过处分", "欧阳明", "soe"), ("王强被开除党籍", "王强", "soe"),
                ("低保家庭学生马小明", "马小明", "k12"), ("建档立卡户孙小红同学", "孙小红", "k12"),
                ("单亲家庭的郭晓东同学", "郭晓东", "k12")]
        for text, name, dom in flag:
            with self.subTest(text=text):
                self.assertIn(name, [h.name for h in detect(text, dom)])
        clean = [("值班医师曾多次未按时交班。", "hospital"), ("患者黄疸，女性多见。", "hospital"),
                 ("患者高热，男性居多。", "hospital"), ("患者沈阳籍，男，因肺炎入院。", "hospital"),
                 ("患者平均住院日缩短。", "hospital"), ("值班医师严格按流程处置。", "hospital"),
                 ("对林业局给予警告。", "soe"), ("对孙公司给予警告。", "soe"), ("对项目经理给予警告处分。", "soe"),
                 ("本学期特困学生：一年级、三年级各2人", "k12"), ("低保家庭学生名单：七年级、八年级，详见附表", "k12"),
                 ("同学们积极参与", "k12")]
        for text, dom in clean:
            with self.subTest(text=text):
                self.assertEqual(detect(text, dom), [])


if __name__ == "__main__":
    unittest.main()
