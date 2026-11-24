# -*- coding: utf-8 -*-
"""shared/scripts/secret_check.py 的单元测试：密级只在页眉、页脚、文本框、表格等位置时也能检出。

运行：python -m unittest discover -s tests/secret -t .
"""
from __future__ import annotations

import io
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


if __name__ == "__main__":
    unittest.main()
