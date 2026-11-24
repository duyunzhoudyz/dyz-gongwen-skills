# -*- coding: utf-8 -*-
"""gongwen-soe 引擎层的姓名识别、程序倒置、豁免窗口和文件名遮蔽测试（共享模块 1.1.0 口径）。

运行：python -m unittest discover -s tests/soe -t .

  1. 处分对象召回（SOE-022）：按句式分组，在三套名字集上各自断言下限（实测值向下取整到 5%），日志逐组打印召回率；
  2. 与 HEAD（d07b657）对照：tests/names/fixtures/head_baseline.json 里国企句式的 HEAD 命中数，引擎层不得更低；
  3. 误报对照：企业、机构、职务和普通动词不得被当成姓名；
  4. 程序倒置成对对照（议题材料）：真倒置报、同形的非倒置不报，换说法、声明、否定词的各种写法；
  5. 豁免窗口成对对照（对外材料，SOE-008）：出处“尚未出具”不算豁免；
  6. 文件名回显遮蔽。
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
SCRIPTS_DIR = REPO_ROOT / "skills" / "gongwen-soe" / "scripts"
FIXTURES = REPO_ROOT / "tests" / "names" / "fixtures"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import soe_check as sc  # noqa: E402


def read_list(path: Path) -> List[str]:
    out = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _parse_given_names() -> Tuple[str, List[str]]:
    section, surnames, givens = "", "", []
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
    """60 个常见姓 × 名字用字，按固定步长抽样（四分之一），与 tests/names 的取法一致，可复现。"""
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


class Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.ruleset = sc.load_rules()

    def check(self, text: str, doc_type=None, external: bool = False):
        return sc.check_text(text, doc_type, external, ruleset=self.ruleset)

    def rows(self, text: str, rid: str, doc_type=None, external: bool = False) -> List[dict]:
        return [i for i in self.check(text, doc_type, external)["issues"] if i["id"] == rid]

    def levels(self, text: str, rid: str, doc_type=None, external: bool = False) -> List[str]:
        return [i["level"] for i in self.rows(text, rid, doc_type, external)]


# ---------------------------------------------------------------------------
# 1. 处分对象召回（按句式分组）
# ---------------------------------------------------------------------------
# 前 6 个是方案点名的句式，后 3 个是另拟的带职务、单位的自然写法。
# 下限 = 实测值向下取整到 5%：夹具名（408）实测识别 98.3%、P0 95.1%；程序化生成（2580）99.1%/99.1%；人工名（42）100%/100%。
PUNISH_TEMPLATES = (
    "给予{n}同志党内警告处分。",
    "给予副部长{n}撤职处分。",
    "给予财务部原副部长{n}党内严重警告处分。",
    "对物资公司副总经理{n}给予记过处分。",
    "{n}被开除党籍。",
    "对{n}进行了诫勉谈话。",
    "对时任项目公司总经理{n}给予党内严重警告处分。",
    "给予采购部会计{n}同志记大过处分。",
    "对原董事长{n}作出开除党籍处分。",
)
FLOORS = {  # 名字集 -> (识别率下限, P0 比例下限)
    "夹具名": (0.95, 0.95),
    "程序化生成": (0.95, 0.95),
    "人工名": (1.00, 1.00),
}


class PunishRecallTest(Base):

    def measure(self, template: str, names: Sequence[str]) -> Tuple[int, int, List[str]]:
        found = high = 0
        leaked: List[str] = []
        for name in names:
            result = self.check(template.format(n=name), "纪要")
            rows = [i for i in result["issues"] if i["id"] == "SOE-022"]
            if rows:
                found += 1
                if any(i["level"] == "P0" for i in rows):
                    high += 1
                if name in json.dumps(result, ensure_ascii=False):
                    leaked.append(name)
        return found, high, leaked

    def test_recall_by_template(self) -> None:
        sets = name_sets()
        lines = ["", "处分对象召回（识别率；括号内 P0）："]
        for template in PUNISH_TEMPLATES:
            parts = []
            for set_name, names in sets.items():
                found, high, leaked = self.measure(template, names)
                total = len(names)
                lo_found, lo_high = FLOORS[set_name]
                parts.append(f"{set_name} {found}/{total}={found / total:.1%}（P0 {high / total:.1%}）")
                with self.subTest(template=template, names=set_name):
                    self.assertEqual(leaked, [], "姓名没有被遮蔽")
                    self.assertGreaterEqual(found / total, lo_found, f"识别率 {found}/{total}")
                    self.assertGreaterEqual(high / total, lo_high, f"P0 比例 {high}/{total}")
            lines.append(f"  {template}  " + " | ".join(parts))
        sys.stderr.write("\n".join(lines) + "\n")


class HeadBaselineTest(Base):

    def test_not_below_head(self) -> None:
        """tests/names/fixtures/head_baseline.json：HEAD（d07b657）引擎在 names.txt（408）上的国企句式实跑数字，引擎层不得更低。"""
        base = json.loads((FIXTURES / "head_baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(base["commits"]["HEAD"][:7], "d07b657")
        names = read_list(FIXTURES / "names.txt")
        self.assertEqual(len(names), base["names_count"])
        rows = [r for r in base["rows"] if r["engine"] == "soe"]
        self.assertGreaterEqual(len(rows), 5)
        lines = ["", "与 HEAD 基线对照（国企引擎层，命中名字数，括号内 P0）："]
        for row in rows:
            found = high = 0
            for name in names:
                issues = [i for i in self.check(row["template"].format(n=name), "纪要")["issues"] if i["id"] == row["rule"]]
                if issues:
                    found += 1
                    if any(i["level"] == "P0" for i in issues):
                        high += 1
            head = row["HEAD"]["detected"]
            lines.append(f"  {row['template']}：HEAD {head}（P0 {row['HEAD']['p0']}）→ 现 {found}（P0 {high}）")
            with self.subTest(template=row["template"]):
                self.assertGreaterEqual(found, head, f"命中 {found} 低于 HEAD 的 {head}")
                self.assertGreaterEqual(high, row["HEAD"]["p0"])
        sys.stderr.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# 3. 处分对象误报对照
# ---------------------------------------------------------------------------
class PunishMisfireTest(Base):

    NOT_REPORTED = (
        "对林业局给予警告。", "对孙公司给予警告。", "对项目经理给予警告处分。", "给予党内警告处分",
        "对贺州分公司给予警告", "邓小平理论学习不力的支部受到警告处分", "给予财务部全体人员通报批评",
        "对副总经理提出的方案给予肯定", "给予总经理办公会充分授权",
    )

    def test_not_reported_in_every_doc_type(self) -> None:
        for text in self.NOT_REPORTED:
            for doc_type in (None, "纪要", "合规报告"):
                with self.subTest(text=text, doc_type=doc_type):
                    self.assertEqual(self.rows(text, "SOE-022", doc_type), [])
                    self.assertNotIn("〔姓名", json.dumps(self.check(text, doc_type), ensure_ascii=False))

    def test_title_with_name_still_masked_but_title_kept(self) -> None:
        row = self.rows("给予副部长王建国撤职处分。", "SOE-022", "纪要")[0]
        self.assertEqual(row["level"], "P0")
        self.assertIn("副部长〔姓名1〕", row["excerpt"])
        self.assertNotIn("王建国", json.dumps(row, ensure_ascii=False))

    def test_known_limits_are_documented(self) -> None:
        """脚本说明和 README 都交代同形简称的处理口径及剩余边界。"""
        doc = sc.__doc__ or ""
        readme = (REPO_ROOT / "skills" / "gongwen-soe" / "README.md").read_text(encoding="utf-8")
        for text in (doc, readme):
            self.assertIn("唐钢", text)
            self.assertIn("隔着分句", text)
            self.assertIn("文件名", text)


# ---------------------------------------------------------------------------
# 4. 程序倒置成对对照
# ---------------------------------------------------------------------------
class InversionPairsTest(Base):
    T = "议题材料"

    def lv(self, text: str, doc_type=None) -> List[str]:
        return self.levels(text, "SOE-001", doc_type or self.T)

    def test_config_has_no_legacy_overrides(self) -> None:
        cfg = self.ruleset.inversion
        self.assertEqual(set(cfg) - {"说明"}, {"rule_id", "types"})
        self.assertEqual(cfg["types"], ["议题材料", "议案", "纪要", "决议"])

    def test_attributive_vs_predicate(self) -> None:
        """已执行成分作定语不算；同一件事作谓语的报 P0。"""
        self.assertEqual(self.lv("已签订的框架协议执行良好，现提请董事会审议续签事项。"), [])
        self.assertEqual(self.lv("已签订采购合同，现提请董事会审议。"), ["P1"])       # 收缩：组合判定只给 P1
        self.assertEqual(self.lv("已签订合同，现提请董事会审议。"), ["P1"])

    def test_framework_agreement_is_excluded_by_design(self) -> None:
        """共享模块把“框架、意向、备忘录、战略合作”协议排除在 P0 档之外：签框架协议后提请审议具体合作方案是正常顺序。
        这也包括不带“与某公司”的“已签订框架协议，现提请董事会审议。”（见汇报：与任务单里的预期不一致，未改共享模块）。"""
        for text in ("已与某公司签订战略合作框架协议，现提请董事会审议具体合作方案。",
                     "已签订框架协议，现提请董事会审议。", "计划于9月开工，现提请董事会审议。"):
            with self.subTest(text=text):
                self.assertEqual(self.lv(text), [])

    def test_rephrasings_are_p1(self) -> None:
        for text in ("该项目于2026年9月开工建设，目前主体工程已完成30%，现提请审议。",
                     "该项目9月份已开始施工，现将有关情况报请审议。",
                     "项目施工单位已于9月进场作业，现提请审议。",
                     "物资公司已与供应商签订钢材采购合同，会议同意提请董事会审议该采购事项。"):
            with self.subTest(text=text):
                self.assertEqual(self.lv(text), ["P1"])

    def test_loosened_request_wording_p1(self) -> None:
        for text in ("项目已开工建设，请予审议。", "项目已开工建设，提交本次会议审议。", "物资已全部采购到位，特提请审议。",
                     "本项目设备已于9月采购到位并投入使用，现提请院长办公会审议。", "该项目已于2026年9月开工建设，现提请董事会审议。",
                     "已签约，现提请董事会审议。"):
            with self.subTest(text=text):
                self.assertEqual(self.lv(text), ["P1"])

    def test_normal_topics_after_execution_not_reported(self) -> None:
        for text in ("食堂已投入使用，现提请审议食堂收费标准。", "设备已于去年按程序采购并投入使用，现提请审议设备报废处置事项。",
                     "设备已采购到位，现提请审议设备使用管理办法。", "信息系统已于去年上线，现提请审议数据安全管理制度。",
                     "公司已签订年度供货框架协议，现提请审议2027年采购计划。",
                     "我院已与某高校签订合作办学协议，现提请审议附属医院人员编制方案。",
                     "我院已建成胸痛中心，现提请院长办公会审议创建卒中中心的实施方案。",
                     "去年已采购的CT设备运行良好，现提请审议新购MRI设备事项。", "已签订的框架协议执行良好，现提请董事会审议续签事项。"):
            with self.subTest(text=text):
                self.assertEqual(self.lv(text), [])

    def test_not_reported(self) -> None:
        for text in ("计划于9月开工，现提请董事会审议。", "拟于9月开工，现提请董事会审议。",
                     "已完成采购需求论证，现提请董事会审议。", "已完成《采购管理办法》修订稿，拟于11月提请董事会审议。"):
            with self.subTest(text=text):
                self.assertEqual(self.lv(text), [])

    def test_slogans_and_template_phrases_do_not_downgrade(self) -> None:
        """杜绝、防止类套话、否定写法和“如实报告如下”不是声明：正则 P0 的真倒置句仍 P0，组合判定的 P1 也不换成“已声明”文案。"""
        true_line = "项目已于9月先行开工，现提请董事会补办审批手续。"          # pattern 命中（先行开工）：P0
        combo_line = "该项目已于2026年9月开工建设，现提请董事会审议。"          # 只有组合判定：P1
        tails = ("各单位要防止出现先执行后决策问题。", "坚决杜绝程序倒置。", "上述做法不属于程序倒置。", "经核查，上述事项不存在程序倒置。",
                 "该项目未发生程序倒置。", "此前已就程序倒置问题开展了自查。")
        for tail in tails:
            for sep in ("\n\n", ""):
                with self.subTest(tail=tail, sep=sep):
                    self.assertEqual(self.lv(true_line + sep + tail), ["P0"])
                    rows = self.rows(combo_line + sep + tail, "SOE-001", self.T)
                    self.assertEqual([r["level"] for r in rows], ["P1"])
                    self.assertNotIn("已如实写明", rows[0]["message"])
        for text in ("现将有关情况如实报告如下。" + true_line, "现将有关情况如实报告如下。\n" + true_line):
            with self.subTest(text=text):
                self.assertEqual(self.lv(text), ["P0"])
        # 追认字样：声明不起作用，仍 P0
        self.assertEqual(self.lv("工程已先行开工，现提请审议工程投资方案。以上情况系程序倒置，现报请追认。"), ["P0"])


    def test_affirmative_declaration_downgrades_to_p1(self) -> None:
        self.assertEqual(self.lv("项目已于9月先行开工，属于程序倒置，现如实报告。"), ["P1"])
        self.assertEqual(self.lv("项目已开工建设，现提请董事会审议。\n\n以上程序倒置情况，如实报告。"), ["P1"])      # 组合判定本就是 P1
        self.assertEqual(self.lv("项目已开工建设，现提请董事会审议，本项目属于程序倒置。"), ["P1"])
        self.assertEqual(self.lv("项目已于9月先行开工。\n以上情况属于程序倒置，由会议决定后续处理。"), ["P1"])      # 正则 P0 + 紧邻肯定式声明 -> P1
        # 写了追认或补办仍 P0
        self.assertEqual(self.lv("项目已于9月先行开工，属于程序倒置，现如实报告，并提请董事会追认。"), ["P0"])

    def test_honest_report_alone_is_not_a_declaration(self) -> None:
        self.assertEqual(self.lv("项目已于9月先行开工，现提请董事会补办审批手续，现如实报告。"), ["P0"])
        self.assertEqual(self.lv("项目已于9月先行开工，现提请董事会补办审批手续。\n特此如实说明。"), ["P0"])
        # 组合判定本身只给 P1
        self.assertEqual(self.lv("项目已开工建设，现提请董事会审议，现如实报告。"), ["P1"])

    def test_other_doc_types(self) -> None:
        """组合判定只在议题材料、议案、纪要、决议生效；其他类型不做组合判定，SOE-001 的正则命中不受限制。"""
        for doc_type in ("议案", "纪要", "决议"):
            with self.subTest(doc_type=doc_type):
                self.assertEqual(self.levels("项目施工单位已于9月进场作业，现提请审议。", "SOE-001", doc_type), ["P1"])
        for doc_type in ("经营分析", "合规报告", "对外材料", None):
            with self.subTest(doc_type=doc_type):
                self.assertEqual(self.levels("项目施工单位已于9月进场作业，现提请审议。", "SOE-001", doc_type), [])
                # 正则命中的“先行开工”按原规则报 P0，不分类型
                self.assertEqual(self.levels("项目已于9月先行开工，现提请董事会审议。", "SOE-001", doc_type), ["P0"])

    def test_messages_follow_reason(self) -> None:
        """P1 的说明文案按原因给，不显示与原因矛盾的文字。"""
        cases = (
            ("项目已开工建设，现提请董事会审议，本项目属于程序倒置。", "已如实写明程序倒置"),
            ("项目已开工建设，现提请董事会审议。\n\n以上程序倒置情况，如实报告。", "同一句里既写了"),
            ("项目已开工建设，现提请董事会审议。以上程序倒置情况，如实报告。", "已如实写明程序倒置"),
            ("项目已开工建设，现提请董事会审议，请予追认。", "追认"),
            ("一期已开工，现提请审议二期方案。", "提请事项可能与已执行事项不同"),
            ("设备已于9月采购到位。\n现提请院长办公会审议。", "相邻两句"),
            ("本项目设备于9月采购到位并投入使用，现提请院长办公会审议。", "于X月开工、投入使用"),
        )
        for text, keyword in cases:
            with self.subTest(text=text):
                rows = self.rows(text, "SOE-001", self.T)
                self.assertEqual([r["level"] for r in rows], ["P1"])
                self.assertIn(keyword, rows[0]["message"])
                self.assertNotIn("同句", rows[0]["message"])
                if "如实写明" not in keyword:
                    self.assertNotIn("如实写明", rows[0]["message"], "不是声明降级的 P1 不得写成已声明")
        # 邻句 P1 不得带“已如实声明”；声明类 P1 不得写成“相邻两句”
        declared = self.rows("项目已开工建设，现提请董事会审议，本项目属于程序倒置。", "SOE-001", self.T)[0]["message"]
        self.assertNotIn("相邻两句", declared)
        p0 = self.rows("项目已于9月先行开工，现提请董事会审议。", "SOE-001", self.T)[0]["message"]
        self.assertNotIn("组合判定", p0)             # pattern 命中的 P0 沿用规则自带 message


# ---------------------------------------------------------------------------
# 5. 豁免窗口成对对照（出处类）
# ---------------------------------------------------------------------------
class SourceExemptionPairsTest(Base):

    def test_source_not_yet_issued_is_not_exempt(self) -> None:
        for text in ("该技术国内领先，鉴定意见尚未出具。", "填补国内空白，评价报告正在编制。"):
            with self.subTest(text=text):
                self.assertEqual(self.levels(text, "SOE-008", "对外材料"), ["P0"])

    def test_source_given_is_exempt(self) -> None:
        for text in ("该技术国内领先，经省科技厅鉴定。", "该技术国内领先，鉴定意见见附件。"):
            with self.subTest(text=text):
                self.assertEqual(self.levels(text, "SOE-008", "对外材料"), [])


# ---------------------------------------------------------------------------
# 6. 文件名回显遮蔽
# ---------------------------------------------------------------------------
class FileNameMaskTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.ruleset = sc.load_rules()

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="soe_fname_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name: str, body: str) -> Path:
        path = self.tmp / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_name_in_file_name_is_masked_in_header_and_json(self) -> None:
        path = self.write("王建国处分材料.txt", "给予王建国同志党内警告处分。")
        result = sc.check_file(path, "纪要", ruleset=self.ruleset)
        self.assertEqual(result["file"], "〔姓名1〕处分材料.txt")
        text = sc.render_text(result)
        self.assertNotIn("王建国", text)
        self.assertIn("〔姓名1〕处分材料.txt", text.splitlines()[0])
        self.assertNotIn("王建国", json.dumps(result, ensure_ascii=False))

    def test_cli_json_output(self) -> None:
        import contextlib
        import io
        path = self.write("对李红梅给予记过处分的通报.txt", "会议决定对李红梅给予记过处分。")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sc.main([str(path), "--type", "纪要", "--json"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertNotIn("李红梅", out.getvalue())
        self.assertEqual(json.loads(out.getvalue())["file"], "对〔姓名1〕给予记过处分的通报.txt")

    def test_ordinary_file_name_untouched(self) -> None:
        path = self.write("党委会纪要.txt", "给予王建国同志党内警告处分。")
        self.assertEqual(sc.check_file(path, "纪要", ruleset=self.ruleset)["file"], "党委会纪要.txt")

    def test_name_only_in_file_name_cannot_be_masked(self) -> None:
        """已知局限：文件名里有、正文没被识别的姓名遮不住（README 与脚本说明已写）。"""
        path = self.write("张伟的材料.txt", "给予王建国同志党内警告处分。")
        self.assertEqual(sc.check_file(path, "纪要", ruleset=self.ruleset)["file"], "张伟的材料.txt")

    def run_table(self, name, body):
        return check_masked_outputs(sc._shared()[0], lambda: self._run_table(name, body))

    def _run_table(self, name, body):
        path = self.tmp / name
        path.write_text(body, encoding="utf-8")
        out, rendered, err = io.StringIO(), io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sc.main([str(path), "--type", "纪要", "--json"])
        text_err = io.StringIO()
        with redirect_stdout(rendered), redirect_stderr(text_err):
            text_code = sc.main([str(path), "--type", "纪要"])
        out, rendered, err, text_err = out.getvalue(), rendered.getvalue(), err.getvalue(), text_err.getvalue()
        self.assertEqual(code, text_code)
        self.assertIn(code, (0, 1), err + text_err)
        return json.loads(out), rendered

    def test_sensitive_and_ordinary_rows_keep_document_numbering(self) -> None:
        body = ("| 职工姓名 | 处分 |\n| --- | --- |\n| 王秀英 | 警告 |\n\n"
                "| 姓名 | 序号 |\n| --- | --- |\n| 王秀英 | 1 |\n| 欧阳明月 | 2 |\n")
        report, screen = self.run_table("王秀英附表.md", body)
        rows = [(i["id"], i["level"], i["line"], i["excerpt"]) for i in report["issues"]
                if i["id"] in ("SOE-022", "SOE-023")]
        self.assertEqual(rows, [("SOE-022", "P0", 3, "〔姓名1〕"),
                                ("SOE-023", "P1", 7, "〔姓名1〕"),
                                ("SOE-023", "P1", 8, "〔姓名2〕")])
        self.assertEqual(report["file"], "〔姓名1〕附表.md")
        for word in ("王秀英", "欧阳明月"):
            self.assertNotIn(word, json.dumps(report, ensure_ascii=False))
            self.assertNotIn(word, screen)
        for _, _, _, excerpt in rows:
            self.assertIn(excerpt, screen)
        sys.stderr.write(f"\nsoe 表格姓名正例：命中 {len(rows)}/3。\n")

    def test_absent_public_and_nonnames_are_not_registered(self) -> None:
        controls = [
            ("王秀英", "| 编号 | 违纪 |\n| --- | --- |\n| 王秀英 | 记录 |\n"),
            ("王秀英", "| 联系人姓名 | 违纪 |\n| --- | --- |\n| 王秀英 | 记录 |\n"),
        ]
        controls.extend((cell, f"| 姓名 | 违纪 |\n| --- | --- |\n| {cell} | 记录 |\n")
                        for cell in ("合计", "小计", "无", "/", "—", "高一", "五年级", "宣传科", "123"))
        misfires = 0
        for name, body in controls:
            with self.subTest(name=name, body=body):
                file_name = ("斜线" if name == "/" else name) + "附表.md"
                report, screen = self.run_table(file_name, body)
                rows = [i for i in report["issues"] if i["id"] in ("SOE-022", "SOE-023")]
                misfires += len(rows)
                self.assertEqual(rows, [])
                self.assertEqual(report["file"], file_name)
                self.assertNotIn("〔姓名", screen)
        sys.stderr.write(f"\nsoe 表格姓名反例：误报 {misfires}/{len(controls)}。\n")

    def test_abbreviations_follow_document_evidence(self) -> None:
        examples = [
            ("对唐钢给予警告处分。", "唐钢", "P1"),
            ("对唐钢给予警告处分。\n唐钢集团已回函。", "唐钢", "P1"),
            ("唐钢股份有限公司回函。\n拟安置人员：王建国、唐钢。", "唐钢", "P1"),
            ("唐钢公司回函。\n对唐钢给予警告处分。", "唐钢", "P1"),
            ("对马钢给予警告。", "马钢", "P1"),
            ("对曹宇航给予警告处分。", "曹宇航", "P1"),
            ("拟安置人员：唐钢、王建国。", "唐钢", "P1"),
            ("对唐钢同志给予警告处分。", "唐钢", "P0"),
            ("给予副部长唐钢警告处分。", "唐钢", "P0"),
            ("对唐钢（工号123）给予警告处分。", "唐钢", "P0"),
            ("唐钢（男）受到警告处分。", "唐钢", "P0"),
            ("唐钢被开除党籍。", "唐钢", "P0"),
            ("对唐钢进行了诫勉谈话。", "唐钢", "P0"),
        ]
        detected = 0
        for body, name, level in examples:
            with self.subTest(body=body):
                path = self.write(f"{name}核查.txt", body)
                report = sc.check_file(path, "纪要", ruleset=self.ruleset)
                rid = "SOE-023" if "拟安置" in body else "SOE-022"
                issues = [i for i in report["issues"] if i["id"] == rid and "〔姓名" in i["excerpt"]]
                self.assertIn(level, [i["level"] for i in issues])
                if level == "P1":
                    self.assertFalse(any(i["level"] == "P0" for i in issues))
                    self.assertTrue(any("可能是单位简称，请人工确认" in i["message"] for i in issues))
                self.assertNotIn(name, json.dumps(report, ensure_ascii=False))
                detected += 1
        controls = [
            "东岭冶炼有限责任公司（以下简称“唐钢”）。\n对唐钢给予警告处分。",
            "东岭物资有限公司（以下简称“唐华”）。\n对唐华给予警告处分。",
        ]
        misfires = 0
        for body in controls:
            name = "唐华" if "唐华" in body else "唐钢"
            with self.subTest(body=body):
                path = self.write(f"{name}核查.txt", body)
                report = sc.check_file(path, "纪要", ruleset=self.ruleset)
                self.assertEqual(report["file"], path.name)
                for row in report["issues"]:
                    self.assertNotIn("可能是单位简称", row["message"])
                    self.assertNotEqual(row["id"], "SOE-022")
                    self.assertNotIn("〔姓名2〕", row["excerpt"])
                misfires += int(report["file"] != path.name)
        sys.stderr.write(f"\n企业简称回归：预期命中 {detected}/{len(examples)}，有单位证据误报 {misfires}/{len(controls)}。\n")


if __name__ == "__main__":
    unittest.main()
