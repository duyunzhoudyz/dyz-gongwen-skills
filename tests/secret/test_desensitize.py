# -*- coding: utf-8 -*-
'''shared/scripts/desensitize.py 与 xinchuang/local_toolbox.py 的单元测试。

运行：python -m unittest tests.secret.test_desensitize
'''
from __future__ import annotations

import base64
import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
for sub in ('shared/scripts', 'xinchuang', 'skills/gongwen-format/scripts'):
    path = str(REPO_ROOT / sub)
    if path not in sys.path:
        sys.path.insert(0, path)

import desensitize as ds  # noqa: E402
import lite_docx  # noqa: E402
import local_toolbox as tb  # noqa: E402

TEXT = '联系人张三，电话13812345678，身份证11010519900307123X，邮箱zhang@example.com。'


class DesensitizeTest(unittest.TestCase):

    def test_round_trip(self):
        res = ds.mask_text(TEXT, ['张三'])
        for original in ('张三', '13812345678', '11010519900307123X', 'zhang@example.com'):
            self.assertNotIn(original, res.masked_text)
        self.assertEqual(len(res.mapping), 4)
        back = ds.restore_text(res.masked_text, res.mapping)
        self.assertEqual(back.restored_text, TEXT)
        self.assertEqual(back.missing_tokens, [])

    def test_same_value_same_token(self):
        res = ds.mask_text('张三来了。张三走了。', ['张三'])
        self.assertEqual(len(res.mapping), 1)
        self.assertEqual(res.masked_text.count('【自定义词1】'), 2)

    def test_secret_marks_block(self):
        with self.assertRaises(ds.SecretBlockedError):
            ds.mask_text('本文件为机密★5年，请勿外传。')

    def test_restore_reports_missing_token(self):
        res = ds.mask_text(TEXT, ['张三'])
        back = ds.restore_text('只剩一句话。', res.mapping)
        self.assertEqual(back.restored_count, 0)
        self.assertEqual(len(back.missing_tokens), 4)

    def test_cli_round_trip_and_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, masked, mapf, back = (Path(tmp) / n for n in ('a.txt', 'm.txt', 'map.json', 'b.txt'))
            src.write_text(TEXT, encoding='utf-8')
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(ds.main(['mask', str(src), '-o', str(masked), '--map', str(mapf), '--terms', '张三']), 0)
                self.assertEqual(ds.main(['restore', str(masked), '--map', str(mapf), '-o', str(back)]), 0)
            self.assertEqual(back.read_text(encoding='utf-8'), TEXT)
            secret = Path(tmp) / 's.txt'
            secret.write_text('机密★5年', encoding='utf-8')
            blocked_map = Path(tmp) / 'x.json'
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = ds.main(['mask', str(secret), '--map', str(blocked_map)])
            self.assertEqual(code, 3)
            self.assertFalse(blocked_map.exists())


class ToolboxOpsTest(unittest.TestCase):

    def setUp(self):
        tb.STATE['map'] = {}
        tb.STATE['sessions'].clear()

    def test_mask_then_restore(self):
        masked = tb.op_mask({'a': TEXT, 'terms': '张三'})
        self.assertTrue(masked['ok'])
        restored = tb.op_restore({'b': masked['text']})
        self.assertEqual(restored['text'], TEXT)

    def test_session_isolation_between_tabs(self):
        m1 = tb.op_mask({'sid': 'tab-1', 'a': '联系人张三，电话13812345678。', 'terms': '张三'})
        m2 = tb.op_mask({'sid': 'tab-2', 'a': '联系人李四，电话13987654321。', 'terms': '李四'})
        self.assertTrue(m1['ok'] and m2['ok'])
        r1 = tb.op_restore({'sid': 'tab-1', 'b': m1['text']})
        r2 = tb.op_restore({'sid': 'tab-2', 'b': m2['text']})
        self.assertIn('张三', r1['text'])
        self.assertIn('李四', r2['text'])
        self.assertIn('张三', tb.op_show_map({'sid': 'tab-1'})['text'])
        tb.op_clear_map({'sid': 'tab-1'})
        self.assertFalse(tb.op_restore({'sid': 'tab-1', 'b': m1['text']})['ok'])
        self.assertTrue(tb.op_restore({'sid': 'tab-2', 'b': m2['text']})['ok'])

    def test_extract_docx_and_secret_header_block(self):
        raw, _ = lite_docx.build_lite_docx(['关于窗口管理的通知', '各科室：', '按要求落实。'], font_check=False)
        res = tb.op_extract_docx({'filename': '通知.docx', 'data_b64': base64.b64encode(raw).decode('ascii')})
        self.assertTrue(res['ok'])
        self.assertFalse(res['secret_warn'])
        self.assertIn('关于窗口管理的通知', res['text'])
        # 页眉带涉密标识时脱敏强拦截
        blocked = tb.op_mask({'a': '普通正文', 'hf_a': '机密★5年'})
        self.assertFalse(blocked['ok'])
        self.assertIn('强拦截', blocked['text'])

    def test_ofd_check_via_toolbox(self):
        ns = 'xmlns:ofd="http://www.ofdspec.org/2016"'
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('OFD.xml', f'<ofd:OFD {ns}><ofd:DocBody><ofd:DocRoot>Doc_0/Document.xml</ofd:DocRoot></ofd:DocBody></ofd:OFD>')
            zf.writestr('Doc_0/Document.xml', f'<ofd:Document {ns}><ofd:CommonData><ofd:PageArea><ofd:PhysicalBox>0 0 210 297</ofd:PhysicalBox></ofd:PageArea></ofd:CommonData><ofd:Pages><ofd:Page ID="1" BaseLoc="Pages/Page_1/Content.xml"/></ofd:Pages></ofd:Document>')
            zf.writestr('Doc_0/PublicRes.xml', f'<ofd:Res {ns}><ofd:Fonts><ofd:Font ID="1" FontName="仿宋_GB2312"><ofd:FontFile>f.ttf</ofd:FontFile></ofd:Font></ofd:Fonts></ofd:Res>')
            zf.writestr('Doc_0/Pages/Page_1/Content.xml', f'<ofd:Page {ns}/>')
        res = tb.op_ofd({'filename': '成稿.ofd', 'data_b64': base64.b64encode(buf.getvalue()).decode('ascii')})
        self.assertTrue(res['ok'], res['text'])
        self.assertIn('210×297 mm', res['text'])

    def test_format_falls_back_to_lite_when_python_docx_missing(self):
        sample = '关于加强管理的通知\n\n各科室：\n\n请按要求落实。\n\n某单位\n2026年11月20日\n'
        with mock.patch.dict(sys.modules, {'docx': None}):
            res = tb.op_format({'b': sample})
        self.assertTrue(res['ok'], res['text'])
        self.assertEqual(res['mode'], 'lite')
        got = lite_docx.read_docx_text(base64.b64decode(res['docx']))
        self.assertIn('请按要求落实', got['body'])

    def test_prompts_list_and_path_traversal_blocked(self):
        listing = tb.op_prompts({})
        self.assertTrue(listing['ok'])
        ids = {it['id'] for it in listing['items']}
        self.assertIn('bundles/01-法定公文一站式.md', ids)
        self.assertIn('lite/gongwen-draft.md', ids)
        got = tb.op_prompt_text({'id': 'lite/gongwen-draft.md'})
        self.assertTrue(got['ok'])
        self.assertIn('六条红线', got['text'])
        bad = tb.op_prompt_text({'id': '../README.md'})
        self.assertFalse(bad['ok'])

    def test_restore_without_map_refused(self):
        self.assertFalse(tb.op_restore({'b': '【手机号1】'})['ok'])

    def test_secret_detection(self):
        self.assertFalse(tb.op_secret({'a': '机密★5年'})['ok'])
        self.assertTrue(tb.op_secret({'a': '普通通知。'})['ok'])

    def test_mask_blocked_keeps_no_map(self):
        res = tb.op_mask({'a': '内部资料，不得外传。'})
        self.assertFalse(res['ok'])
        self.assertEqual(tb.STATE['map'], {})

    def test_lint_runs(self):
        res = tb.op_lint({'b': '各单位要认真落实。'})
        self.assertTrue(res['text'].startswith('机检结果'))

    def test_factdiff_flags_changed_number(self):
        res = tb.op_factdiff({'a': '全年完成投资12亿元。', 'b': '全年完成投资15亿元。'})
        self.assertFalse(res['ok'])


class ToolboxServerTest(unittest.TestCase):

    def setUp(self):
        tb.STATE['map'] = {}
        self.server = HTTPServer((tb.HOST, 0), tb.Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(tb.HOST, self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, resp.read().decode('utf-8')
        finally:
            conn.close()

    def test_page_served_on_loopback(self):
        status, body = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('公文写作本机工具箱', body)

    def test_foreign_host_and_origin_refused(self):
        self.assertEqual(self.request('GET', '/', headers={'Host': 'evil.example'})[0], 403)
        payload = json.dumps({'a': TEXT}).encode('utf-8')
        self.assertEqual(self.request('POST', '/api/mask', payload, {'Origin': 'http://evil.example'})[0], 403)

    def test_api_mask_over_http(self):
        payload = json.dumps({'a': TEXT, 'terms': '张三'}).encode('utf-8')
        status, body = self.request('POST', '/api/mask', payload, {'Content-Type': 'application/json'})
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(data['ok'])
        self.assertNotIn('13812345678', data['text'])

    def test_import_plain_text_encodings_over_http(self):
        for name, text in (
            ('通知.txt', '关于报送材料的通知\r\n\r\n各单位：'),
            ('材料.md', '# 关于报送材料的通知\n\n**各单位：**\n【起草说明】保留原文。\n'),
        ):
            for encoding in ('gbk', 'utf-8', 'utf-8-sig'):
                with self.subTest(name=name, encoding=encoding):
                    body = json.dumps({
                        'filename': name,
                        'data_b64': base64.b64encode(text.encode(encoding)).decode('ascii'),
                    }).encode('utf-8')
                    status, result = self.request(
                        'POST', '/api/extract_text', body, {'Content-Type': 'application/json'},
                    )
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(result), {'ok': True, 'text': text})

    def test_unknown_api_refused(self):
        self.assertEqual(self.request('POST', '/api/nope', b'{}')[0], 403)

    def test_get_prompts_over_http(self):
        status, body = self.request('GET', '/api/prompts')
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data['ok'])
        self.assertTrue(data['items'])


if __name__ == '__main__':
    unittest.main()
