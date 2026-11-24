# -*- coding: utf-8 -*-
'''xinchuang/lite_docx.py 的单元测试：纯标准库国标轻量排版、docx 文本提取与 5 套空白公文模板。'''
from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for sub in ('xinchuang', 'skills/gongwen-format/scripts'):
    p = str(REPO_ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import lite_docx  # noqa: E402

try:
    import docx
    import check_docx
except ImportError:
    docx = None
    check_docx = None

SAMPLE_LINES = [
    '关于加强全区政务服务窗口管理的通知',
    '',
    '各科室：',
    '',
    '为进一步提升窗口服务质效，现就有关事项通知如下：',
    '一、严格值班值守',
    '（一）明确首问负责。工作人员要做好一次性告知，不得推诿扯皮。',
    '1.建立台账。每日下班前核对办件记录。',
    '',
    '某区政务服务中心',
    '2026年11月20日',
]


class LiteDocxBuildTest(unittest.TestCase):

    def test_build_contains_gbt9704_xml_and_is_deterministic(self):
        raw1, rep1 = lite_docx.build_lite_docx(SAMPLE_LINES, font_check=False)
        raw2, _rep2 = lite_docx.build_lite_docx(SAMPLE_LINES, font_check=False)
        self.assertEqual(raw1, raw2)
        self.assertTrue(rep1['has_title'])
        with zipfile.ZipFile(io.BytesIO(raw1)) as zf:
            names = set(zf.namelist())
            for needed in (
                '[Content_Types].xml', 'word/document.xml', 'word/styles.xml',
                'word/settings.xml', 'word/footer1.xml', 'word/footer2.xml',
            ):
                self.assertIn(needed, names)
            doc_xml = zf.read('word/document.xml').decode('utf-8')
            settings_xml = zf.read('word/settings.xml').decode('utf-8')
            self.assertIn('w:w="11906" w:h="16838"', doc_xml)
            self.assertIn('w:type="linesAndChars"', doc_xml)
            self.assertIn('方正小标宋简体', doc_xml)
            self.assertIn('仿宋_GB2312', doc_xml)
            self.assertIn('黑体', doc_xml)
            self.assertIn('楷体_GB2312', doc_xml)
            self.assertIn('<w:evenAndOddHeaders/>', settings_xml)

    def test_signature_places_follow_7_3_5_2_no_seal(self):
        """轻量版按 7.3.5.2 不加盖印章排落款：署名右空二字，日期首字比署名首字右移二字。"""
        sig, date = lite_docx._signature_places(['某区政务服务中心办公室'], '2026年11月20日')
        self.assertEqual(sig, ('left', 15.0, 0.0))   # 28 - 2 - 11
        self.assertEqual(date, ('left', 17.0, 0.0))  # 首字比署名首字右移二字
        # 日期加二字后比署名长：日期右对齐右空二字，署名左移
        sig, date = lite_docx._signature_places(['某局'], '2026年11月20日')
        self.assertEqual(date, ('right', 0.0, 2.0))
        self.assertEqual(sig[0], 'left')
        self.assertAlmostEqual(sig[1], 28 - 2 - 7 - 2)
        # 只有署名或只有日期：右对齐右空二字
        self.assertEqual(lite_docx._signature_places(['某局'], '')[0], ('right', 0.0, 2.0))
        self.assertEqual(lite_docx._signature_places([], '2026年11月20日')[1], ('right', 0.0, 2.0))

    def test_build_signature_xml_not_centered_four_chars(self):
        raw, _ = lite_docx.build_lite_docx(SAMPLE_LINES, font_check=False)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xml = zf.read('word/document.xml').decode('utf-8')
        # 样例署名 8 字、日期 7 字：日期加二字超过署名，日期右空二字，署名左缩进 28 - 2 - 7 - 2 = 17 字
        self.assertIn('w:leftChars="1700"', xml)
        self.assertIn('w:rightChars="200"', xml)
        self.assertNotIn('w:rightChars="400"', xml)  # 不再是“日期右空四字”

    def test_unit_fonts_preset_applies_fangzheng_gbk(self):
        raw, rep = lite_docx.build_lite_docx(SAMPLE_LINES, unit_fonts='preset:fangzheng-gbk', font_check=False)
        self.assertEqual(rep['fonts']['仿宋'], '方正仿宋_GBK')
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            doc_xml = zf.read('word/document.xml').decode('utf-8')
            self.assertIn('方正仿宋_GBK', doc_xml)
            self.assertIn('方正楷体_GBK', doc_xml)

    def test_empty_input_raises(self):
        with self.assertRaises(ValueError):
            lite_docx.build_lite_docx(['   ', ''], font_check=False)

    @unittest.skipUnless(docx and check_docx, '缺少 python-docx')
    def test_generated_docx_passes_check_docx(self):
        raw, _rep = lite_docx.build_lite_docx(SAMPLE_LINES, font_check=False)
        parsed = docx.Document(io.BytesIO(raw))
        full = '\n'.join(p.text for p in parsed.paragraphs)
        self.assertIn('严格值班值守', full)
        self.assertIn('某区政务服务中心', full)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'lite.docx'
            target.write_bytes(raw)
            report = check_docx.check_document(target)
        self.assertEqual(report['summary']['P0'], 0, report['issues'])
        self.assertEqual(report['summary']['P1'], 0, report['issues'])

    def test_read_docx_text_extracts_body_table_and_header(self):
        raw, _rep = lite_docx.build_lite_docx(SAMPLE_LINES, font_check=False)
        # 往内存 zip 里塞一个带页眉和表格的部件，验证零依赖提取
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as src, zipfile.ZipFile(buf, 'w') as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == 'word/document.xml':
                    tbl = (
                        '<w:tbl><w:tr>'
                        '<w:tc><w:p><w:r><w:t>项目</w:t></w:r></w:p></w:tc>'
                        '<w:tc><w:p><w:r><w:t>120万元</w:t></w:r></w:p></w:tc>'
                        '</w:tr></w:tbl>'
                    )
                    data = data.decode('utf-8').replace('<w:sectPr>', tbl + '<w:sectPr>').encode('utf-8')
                dst.writestr(item, data)
            dst.writestr(
                'word/header1.xml',
                '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:p><w:r><w:t>内部资料</w:t></w:r></w:p></w:hdr>',
            )
        got = lite_docx.read_docx_text(buf.getvalue())
        self.assertIn('严格值班值守', got['body'])
        self.assertIn('项目 | 120万元', got['body'])
        self.assertEqual(got['tables'], 1)
        self.assertIn('内部资料', got['headers_footers'])
        self.assertIn('内部资料', got['full'])

    def test_read_docx_rejects_invalid_bytes(self):
        with self.assertRaises(zipfile.BadZipFile):
            lite_docx.read_docx_text(b'not a docx')

    def test_repo_templates_exist_and_openable(self):
        tpl_dir = REPO_ROOT / 'xinchuang' / 'templates'
        expected = [
            '01-白头公文模板.docx',
            '02-红头公文模板.docx',
            '03-会议纪要模板.docx',
            '04-内部签报模板.docx',
            '05-综合材料模板.docx',
            'README.md',
        ]
        for name in expected:
            p = tpl_dir / name
            self.assertTrue(p.is_file(), name)
            if name.endswith('.docx'):
                got = lite_docx.read_docx_text(p.read_bytes())
                self.assertGreater(got['paragraphs'], 3, name)

    def test_cli_builds_docx_and_templates(self):
        tmp = Path(tempfile.mkdtemp(prefix='lite-docx-cli-'))
        self.addCleanup(shutil.rmtree, str(tmp), ignore_errors=True)
        src = tmp / '正文.txt'
        out = tmp / '成稿.docx'
        src.write_text('\n'.join(SAMPLE_LINES), encoding='utf-8')
        with redirect_stdout(io.StringIO()):
            code1 = lite_docx.main([str(src), '-o', str(out)])
            code2 = lite_docx.main(['--templates', str(tmp / 'tpls')])
        self.assertEqual(code1, 0)
        self.assertEqual(code2, 0)
        self.assertTrue(out.is_file())
        self.assertTrue((tmp / 'tpls' / '01-白头公文模板.docx').is_file())


if __name__ == '__main__':
    unittest.main()
