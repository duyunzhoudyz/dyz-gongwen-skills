# -*- coding: utf-8 -*-
"""shared/scripts/secret_check.py 的单元测试：密级只在页眉、页脚、文本框、表格等位置时也能检出。

运行：python -m unittest discover -s tests/secret -t .
"""
from __future__ import annotations

import io
import json
import re
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "shared" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import secret_check as sc  # noqa: E402

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


def para(text):
    return "<w:p><w:r><w:t>%s</w:t></w:r></w:p>" % text


def make_docx(path, body="", header=None, footer=None, htype="default"):
    sect = ""
    parts = {}
    rels = ""
    if header is not None:
        sect += '<w:headerReference w:type="%s" r:id="rId1"/>' % htype
        parts["word/header1.xml"] = '<w:hdr %s>%s</w:hdr>' % (NS, para(header))
        rels += '<Relationship Id="rId1" Target="header1.xml"/>'
    if footer is not None:
        sect += '<w:footerReference w:type="default" r:id="rId2"/>'
        parts["word/footer1.xml"] = '<w:ftr %s>%s</w:ftr>' % (NS, para(footer))
        rels += '<Relationship Id="rId2" Target="footer1.xml"/>'
    doc = '<w:document %s><w:body>%s<w:sectPr>%s</w:sectPr></w:body></w:document>' % (NS, body, sect)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", doc)
        zf.writestr("word/_rels/document.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % rels)
        for k, v in parts.items():
            zf.writestr(k, v)


def run(path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = sc.main([str(path)])
    return code, buf.getvalue()


class SecretCheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def docx(self, name, **kw):
        p = self.dir / name
        make_docx(p, **kw)
        return p

    def test_header_only(self):
        code, out = run(self.docx("a.docx", body=para("关于做好工作的通知"), header="秘密★5年"))
        self.assertEqual(code, 1)
        self.assertIn("页眉", out)

    def test_first_page_header(self):
        code, out = run(self.docx("a.docx", body=para("正文"), header="机密★10年", htype="first"))
        self.assertEqual(code, 1)
        self.assertIn("页眉(首页)", out)

    def test_footer_only(self):
        code, out = run(self.docx("b.docx", body=para("正文"), footer="内部资料 不得外传"))
        self.assertEqual(code, 1)
        self.assertIn("页脚", out)

    def test_textbox_only(self):
        box = "<w:p><w:r><w:pict><w:txbxContent>%s</w:txbxContent></w:pict></w:r></w:p>" % para("绝密★长期")
        code, out = run(self.docx("c.docx", body=para("正文") + box))
        self.assertEqual(code, 1)
        self.assertIn("文本框", out)

    def test_table_only(self):
        tbl = "<w:tbl><w:tr><w:tc>%s</w:tc></w:tr></w:tbl>" % para("工作秘密")
        code, out = run(self.docx("d.docx", body=para("正文") + tbl))
        self.assertEqual(code, 1)
        self.assertIn("表格", out)

    def test_body_marker(self):
        code, out = run(self.docx("e.docx", body=para("秘密★3年")))
        self.assertEqual(code, 1)
        self.assertIn("正文", out)

    def test_business_words_not_flagged(self):
        body = para("做好保密工作，加强涉密人员管理，规范涉密档案管理。") + para("秘密工作者不在此列")
        code, out = run(self.docx("f.docx", body=body, header="某单位文件", footer="第1页"))
        self.assertEqual(code, 0, out)

    def test_unstarred_level_flagged(self):
        """不带星号但明确指向文件密级的表述必须拦截。"""
        for text in ("本件为机密级文件，请勿外传。", "密级：机密", "密级:绝密", "本件属机密，不得复制。",
                     "本件秘密，阅后销毁。", "这是一份机密文件。", "该稿已标注机密。", "秘密级材料", "绝密级",
                     "本文件属机密文件", "该件为秘密文件", "此件系绝密文件", "本通知属秘密级文件。",
                     "本文件密级为秘密。", "该文件定为机密", "密级：秘密", "该材料属机密。", "该件为秘密。",
                     "此文件为机密。", "这份文件属机密。", "本文件属于机密文件。",
                     "该材料系秘密材料，请妥善保管。"):
            p = self.dir / "u.txt"
            p.write_text(text + "\n", encoding="utf-8")
            self.assertEqual(run(p)[0], 1, text)

    def test_common_secret_words_not_flagged(self):
        """常见正常用语不误伤。"""
        for text in ("要保守国家秘密，做好保密工作。", "严防商业秘密泄露。", "采用秘密投票方式表决。",
                     "揭开了一个秘密。", "加强对商业机密文件的管理。", "秘密工作者不在此列。", "保密教育月活动。",
                     "加强秘密文件管理。", "各单位要定期开展机密文件清退检查。", "做好机密文件的登记、传阅和清退。",
                     "严禁通过互联网传输秘密文件。", "涉密文件要专柜存放。", "涉及企业商业秘密。",
                     "凡属机密文件，一律专柜存放。", "本通知不涉密。", "请各单位做好定密工作。",
                     "该事项是秘密进行的。", "此次选举为秘密投票。", "这是商业秘密。",
                     "本规定属于机密文件管理范畴。", "上述事项属于秘密文件管理范围。"):
            p = self.dir / "n.txt"
            p.write_text(text + "\n", encoding="utf-8")
            self.assertEqual(run(p)[0], 0, text)

    def test_work_secret_still_flagged(self):
        p = self.dir / "w.txt"
        p.write_text("本材料属于工作秘密。\n", encoding="utf-8")
        self.assertEqual(run(p)[0], 1)

    def test_txt_and_bad_file(self):
        t = self.dir / "a.txt"
        t.write_text("第一行\n机密★5年\n", encoding="utf-8")
        self.assertEqual(run(t)[0], 1)
        bad = self.dir / "bad.docx"
        bad.write_bytes(b"not a zip")
        self.assertEqual(run(bad)[0], 2)

    def test_xlsx_header(self):
        p = self.dir / "a.xlsx"
        ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("xl/workbook.xml", '<workbook %s><sheets><sheet name="Sheet1"/></sheets></workbook>' % ns)
            zf.writestr("xl/sharedStrings.xml", '<sst %s><si><t>合计</t></si></sst>' % ns)
            zf.writestr("xl/worksheets/sheet1.xml",
                        '<worksheet %s><headerFooter><oddHeader>&amp;C秘密★5年</oddHeader></headerFooter></worksheet>' % ns)
        code, out = run(p)
        self.assertEqual(code, 1)
        self.assertIn("页眉", out)


# ---------------------------------------------------------------------------
# 以下为密级识别口径统一后的回归用例（版头独立标注、并列枚举不误拦、商业秘密标注）
# ---------------------------------------------------------------------------
SPECIMEN_DIR = Path(__file__).resolve().parent / "specimens"

STANDALONE_BLOCK = (
    "机密", "秘密", "绝密", "  机密  ", "机　密", "机 密", "【机密】", "（机密）", "[绝密]",
    "机密（10年）", "机密(10年)", "秘密(★5年)", "秘密（★5年）", "机密★10年", "机密★长期", "绝密（长期）",
    "此件机密，阅后收回", "该件秘密，阅后销毁", "机密级", "（机密级）", "机密　特急", "# 机密", "**机密**",
    "密级：机密", "保密等级：秘密",
    "本件为机密级文件，请勿外传。", "密级：秘密", "该文件定为机密", "本文件属机密文件", "该材料属机密。",
    "本件属机密级。", "该文件属机密级",
)
LEVEL_PASS = (
    "根据保守国家秘密法，国家秘密的密级分为绝密级、机密级、秘密级三级。各科室要严格执行秘密级以上文件管理规定。",
    "核心商业秘密级别划分为三级", "按商业秘密级别管理客户数据", "各单位应将涉密文件确定为秘密、机密、绝密三级",
    "密级分为绝密、机密、秘密三级", "绝密级、机密级、秘密级",
    "三、秘密载体管理", "（二）机密事项", "二、机密文件管理", "（一）秘密事项的确定", "第三章 绝密级事项",
    "秘密载体管理", "机密性要求较高的数据", "数据机密性要求较高", "本次会议不属于秘密会议",
    "加强秘密文件管理", "各单位要定期开展机密文件清退检查。", "严禁通过互联网传输秘密文件", "要保守国家秘密",
    "开展保密教育", "涉及企业商业秘密", "采取秘密投票方式", "凡属机密文件，一律专柜存放",
    "本规定属于机密文件管理范畴。", "这是商业秘密。",
)
BIZ_BLOCK = (
    "【核心商密】", "商业秘密", "（核心商密★5年）", "密级：商业秘密", "[普通商密]", "商密", "【商业秘密】附件：投标策略。",
    "核心商密★5年", "（商密）", "密级：核心商密★5年",
)
BIZ_PASS = (
    "加强商业秘密保护", "签订商业秘密保护协议", "本材料不涉及商业秘密", "涉及企业商业秘密", "这是商业秘密。",
    "依法保护商业秘密。", "公司制定了《商业秘密保护办法》。", "涉及客户信息（商业秘密）的材料要妥善保管",
    "**商业秘密保护**", "三、商业秘密保护",
)


def scan_text(text):
    return sc.scan([("第%d行" % i, line) for i, line in enumerate(text.splitlines(), 1) if line.strip()])


class UnifiedRuleTest(unittest.TestCase):
    def test_standalone_and_unstarred_blocked(self):
        for text in STANDALONE_BLOCK:
            self.assertTrue(scan_text(text), "应拦未拦：" + text)

    def test_level_enumeration_and_headings_pass(self):
        for text in LEVEL_PASS:
            self.assertFalse(scan_text(text), "不应拦却拦：%s -> %s" % (text, scan_text(text)))

    def test_commercial_secret_label(self):
        for text in BIZ_BLOCK:
            hits = scan_text(text)
            self.assertTrue(hits, "应拦未拦：" + text)
            self.assertTrue(all(h[1] == "商业秘密标注" for h in hits), (text, hits))
        for text in BIZ_PASS:
            self.assertFalse(scan_text(text), "不应拦却拦：%s -> %s" % (text, scan_text(text)))

    def test_retention_period_label_forms(self):
        """“保密期限为10年”等不带冒号的标注形态也拦（v1.2.0 就拦，上一步收窄时回退过）；法规引述仍放行。"""
        for text in ("保密期限为10年", "保密期限是十年", "保密期限 长期", "保密期限：永久", "保密期限为3个月。",
                     "保密期限为★5年", "（保密期限为10年）"):
            self.assertTrue(scan_text(text), "应拦未拦：" + text)
        for text in ("保密期限为10年的文件，须按期解密。", "保密期限一般为十年。", "保密期限最长为三十年。",
                     "国家秘密的保密期限，除另有规定外，绝密级不超过三十年。",
                     "各部门应当按规定确定密级和保密期限；保密期限届满的，按规定解密或者延长保密期限，并做好登记。"):
            self.assertFalse(scan_text(text), "不应拦却拦：%s -> %s" % (text, scan_text(text)))

    def test_retention_period_in_docx_header_and_footer(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            make_docx(d / "h.docx", body=para("关于做好工作的通知"), header="保密期限为10年")
            code, out = run(d / "h.docx")
            self.assertEqual(code, 1, out)
            self.assertIn("页眉", out)
            make_docx(d / "f.docx", body=para("关于做好工作的通知"), footer="保密期限：长期")
            code, out = run(d / "f.docx")
            self.assertEqual(code, 1, out)
            self.assertIn("页脚", out)
            make_docx(d / "ok.docx", body=para("国家秘密的保密期限，除另有规定外，绝密级不超过三十年。"),
                      header="某某局文件")
            self.assertEqual(run(d / "ok.docx")[0], 0)

    def test_more_standalone_forms(self):
        """v1.2.0 起漏的标注写法。"""
        for text in ("机密·5年", "绝密·长期", "★机密", "密 级：机 密", "机密件", "机密文件，注意保管", "机密，阅后收回",
                     "秘密文件，请勿外传", "绝密级材料"):
            self.assertTrue(scan_text(text), "应拦未拦：" + text)
        for text in ("做好机密文件的登记、传阅和清退", "各单位要定期开展机密文件清退检查。", "机密文件管理办法",
                     "机密文件要专柜存放，专人保管。", "★秘密载体管理"):
            self.assertFalse(scan_text(text), "不应拦却拦：%s -> %s" % (text, scan_text(text)))

    def test_normative_statements_pass(self):
        """保密制度、定密办法里规范性、条件性、否定性叙述中的密级词放行；断言本件密级的句子仍拦。"""
        for text in ("对拟定为机密级的事项，由定密责任人审核。", "经审查，该事项不应定为机密。",
                     "涉密人员接触机密级文件须经审批。", "本材料系秘密投票结果汇总。", "该文件应定为机密级的，须报审批。",
                     "本文件不属于机密级文件。", "定密责任人应当将该文件确定为机密。", "本文件密级为机密级的，须专人保管。",
                     "凡拟定为绝密级的事项，须报省级保密行政管理部门审批。"):
            self.assertFalse(scan_text(text), "不应拦却拦：%s -> %s" % (text, scan_text(text)))
        for text in ("本件为机密级文件", "该文件定为机密", "本文件属机密文件", "该材料属机密。", "此件机密，阅后收回",
                     "该文件定为机密级，请妥善保管。"):
            self.assertTrue(scan_text(text), "应拦未拦：" + text)

    def test_retention_period_only_when_labelled(self):
        """“保密期限”只在标注形态下拦：保密管理制度里的“确定保密期限”“保密期限届满”放行。"""
        for text in ("各部门应当按规定确定密级和保密期限。", "保密期限届满的，按规定解密或者延长。",
                     "国家秘密保密期限的确定应当符合法定要求。", "定密时应写明保密期限，并及时调整。"):
            self.assertFalse(scan_text(text), "不应拦却拦：%s -> %s" % (text, scan_text(text)))
        for text in ("保密期限：10年", "保密期限：★5年", "保密期限：长期", "保密期限:3个月", "机密 保密期限",
                     "★ 密级和保密期限", "密级：机密　保密期限：5年", "机密"):
            self.assertTrue(scan_text(text), "应拦未拦：" + text)

    def test_not_weaker_than_lint_rules(self):
        """PRI-005/PRI-006 的 hit_examples 以及这两条正则命中的样例，secret_check 必须同样命中。"""
        rules = json.loads((SCRIPTS_DIR / "lint_rules.json").read_text(encoding="utf-8"))
        rules = rules if isinstance(rules, list) else rules.get("rules", [])
        by_id = {r["id"]: r for r in rules if isinstance(r, dict)}
        samples = []
        for rid in ("PRI-005", "PRI-006"):
            samples.extend(by_id[rid]["hit_examples"])
        for text in samples:
            self.assertTrue(scan_text(text), "PRI 命中样例 secret_check 未命中：" + text)
        # 再用本文件的全部应拦样例反向核对：凡 PRI-005/006 正则能命中的，secret_check 必须命中
        regs = [re.compile(by_id[r]["pattern"]) for r in ("PRI-005", "PRI-006")]
        for text in STANDALONE_BLOCK + BIZ_BLOCK + tuple(samples):
            if any(rx.search(text) for rx in regs):
                self.assertTrue(scan_text(text), "PRI 命中而 secret_check 未命中：" + text)

    def test_specimens(self):
        for f in sorted(SPECIMEN_DIR.glob("pass_*.txt")):
            self.assertEqual(run(f)[0], 0, f.name + ": " + run(f)[1])
        for f in sorted(SPECIMEN_DIR.glob("block_*.txt")):
            self.assertEqual(run(f)[0], 1, f.name)
        self.assertEqual(len(list(SPECIMEN_DIR.glob("pass_*.txt"))), 5)
        self.assertEqual(len(list(SPECIMEN_DIR.glob("block_*.txt"))), 4)

    def test_ledger_specimen_blocked_by_design(self):
        """定密统计台账里每个单独成行（单元格）的密级词都拦：这是闸门宁严勿漏的已知局限（见 secret_check 文档字符串），不是漏放。"""
        hits = sc.scan(sc.extract(SPECIMEN_DIR / "block_4_定密统计台账.txt"))
        self.assertEqual([h[2] for h in hits], ["机密", "秘密", "秘密", "绝密"])
        self.assertEqual(run(SPECIMEN_DIR / "block_4_定密统计台账.txt")[0], 1)

    def test_long_specimens_are_long_enough(self):
        for name in ("pass_4_定密管理办法.txt", "pass_5_保密工作责任制度.txt"):
            text = (SPECIMEN_DIR / name).read_text(encoding="utf-8")
            self.assertGreaterEqual(len(text), 300, name)

    def test_docx_header_only_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            make_docx(d / "h.docx", body=para("关于做好工作的通知"), header="机密")
            code, out = run(d / "h.docx")
            self.assertEqual(code, 1, out)
            self.assertIn("页眉", out)
            make_docx(d / "h2.docx", body=para("关于做好工作的通知"), header="【核心商密】", footer="机密（10年）")
            code, out = run(d / "h2.docx")
            self.assertEqual(code, 1, out)
            self.assertIn("商业秘密标注", out)
            self.assertIn("页脚", out)
            make_docx(d / "ok.docx", body=para("三、秘密载体管理"), header="某某局文件", footer="第1页")
            self.assertEqual(run(d / "ok.docx")[0], 0)

    def test_desensitize_gate_uses_same_rules(self):
        import desensitize
        self.assertTrue(desensitize.check_secret_text("机密"))
        self.assertTrue(desensitize.check_secret_text("【核心商密】"))
        self.assertFalse(desensitize.check_secret_text("三、秘密载体管理"))


if __name__ == "__main__":
    unittest.main()
