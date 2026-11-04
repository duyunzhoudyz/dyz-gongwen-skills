# -*- coding: utf-8 -*-
"""tools/corpus/llm_client.py 的离线单元测试：网络与密钥文件全部 mock，不联网、不读真实密钥。

运行：python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "tools" / "corpus" / "llm_client.py"

_spec = importlib.util.spec_from_file_location("llm_client_under_test", MODULE_PATH)
llm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(llm)

FAKE_KEY = "fake-key-for-test-0001"


class FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ok_body(content="好", model="m-returned"):
    return json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                       "usage": {"total_tokens": 5}, "model": model}, ensure_ascii=False).encode("utf-8")


def http_error(code, body=b'{"error": {"message": "bad thing"}}'):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body))


class KeyFileTestCase(unittest.TestCase):
    """把 REPO 指到临时目录，密钥文件都在临时目录里。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        patcher = mock.patch.object(llm, "REPO", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        llm._SECRETS.clear()
        self.addCleanup(llm._SECRETS.clear)

    def write_key(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8")


class ConfigTest(unittest.TestCase):
    def test_three_providers_configured(self):
        self.assertEqual(sorted(llm.PROVIDERS), ["deepseek", "doubao", "qwen"])
        for cfg in llm.PROVIDERS.values():
            self.assertTrue(cfg["base_url"].startswith("https://"))
            self.assertTrue(cfg["key_file"].endswith(".key.local"))
            self.assertTrue(cfg["model"])

    def test_urls_follow_plan(self):
        self.assertEqual(llm.PROVIDERS["deepseek"]["base_url"], "https://api.deepseek.com")
        self.assertEqual(llm.PROVIDERS["doubao"]["base_url"], "https://ark.cn-beijing.volces.com/api/v3")
        self.assertIn("compatible-mode/v1", llm.PROVIDERS["qwen"]["base_url"])

    def test_payload_has_no_system_prompt_and_no_temperature(self):
        for name in llm.PROVIDERS:
            p = llm.build_payload(name, "请回复：好", max_tokens=20)
            self.assertEqual([m["role"] for m in p["messages"]], ["user"])
            self.assertNotIn("temperature", p)
            self.assertEqual(p["max_tokens"], 20)

    def test_payload_omits_max_tokens_when_none(self):
        self.assertNotIn("max_tokens", llm.build_payload("deepseek", "x"))

    def test_model_override(self):
        self.assertEqual(llm.build_payload("deepseek", "x", model="other")["model"], "other")


class ReadKeyTest(KeyFileTestCase):
    def test_first_non_empty_line(self):
        self.write_key("deepseek.key.local", f"\n  \n{FAKE_KEY}\nsecond-line\n")
        self.assertEqual(llm.read_key("deepseek"), FAKE_KEY)

    def test_bom_and_crlf(self):
        (self.root / "qwen.key.local").write_bytes(("﻿" + FAKE_KEY + "\r\nx\r\n").encode("utf-8"))
        self.assertEqual(llm.read_key("qwen"), FAKE_KEY)

    def test_missing_file(self):
        with self.assertRaises(llm.KeyFileError) as cm:
            llm.read_key("doubao")
        self.assertIn("doubao.key.local", str(cm.exception))

    def test_empty_file(self):
        self.write_key("doubao.key.local", "\n  \n")
        with self.assertRaises(llm.KeyFileError):
            llm.read_key("doubao")


class ChatTest(KeyFileTestCase):
    def setUp(self):
        super().setUp()
        self.write_key("deepseek.key.local", FAKE_KEY + "\n")

    def test_success_and_request_shape(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResp(ok_body("好", "ds-x"))) as m:
            res = llm.chat("deepseek", "请回复：好", max_tokens=20)
        self.assertEqual(res["content"], "好")
        self.assertEqual(res["model"], "ds-x")
        req = m.call_args[0][0]
        self.assertEqual(req.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer " + FAKE_KEY)
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["model"], "deepseek-chat")
        self.assertNotIn("temperature", body)
        self.assertEqual(len(body["messages"]), 1)

    def test_http_401_is_fatal(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(401)):
            with self.assertRaises(llm.ApiError) as cm:
                llm.chat("deepseek", "x")
        self.assertTrue(cm.exception.fatal)
        self.assertFalse(cm.exception.retryable)
        self.assertEqual(cm.exception.status, 401)

    def test_http_429_is_retryable(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(429)):
            with self.assertRaises(llm.ApiError) as cm:
                llm.chat("deepseek", "x")
        self.assertTrue(cm.exception.retryable)
        self.assertFalse(cm.exception.fatal)

    def test_http_400_neither(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(400)):
            with self.assertRaises(llm.ApiError) as cm:
                llm.chat("deepseek", "x")
        self.assertFalse(cm.exception.retryable or cm.exception.fatal)
        self.assertIn("bad thing", str(cm.exception))

    def test_network_error_is_retryable(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
            with self.assertRaises(llm.ApiError) as cm:
                llm.chat("deepseek", "x")
        self.assertTrue(cm.exception.retryable)

    def test_timeout_is_retryable(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("t")):
            with self.assertRaises(llm.ApiError) as cm:
                llm.chat("deepseek", "x")
        self.assertTrue(cm.exception.retryable)

    def test_unparsable_and_empty(self):
        for body in (b"not json", ok_body("   "), b'{"choices": []}'):
            with self.subTest(body=body[:20]):
                with mock.patch("urllib.request.urlopen", return_value=FakeResp(body)):
                    with self.assertRaises(llm.ApiError):
                        llm.chat("deepseek", "x")

    def test_error_text_never_contains_key(self):
        leaked = http_error(400, json.dumps({"error": {"message": f"bad key {FAKE_KEY}"}}).encode("utf-8"))
        with mock.patch("urllib.request.urlopen", side_effect=leaked):
            with self.assertRaises(llm.ApiError) as cm:
                llm.chat("deepseek", "x")
        self.assertNotIn(FAKE_KEY, str(cm.exception))


class PingTest(KeyFileTestCase):
    def test_missing_key_skipped_without_network(self):
        with mock.patch("urllib.request.urlopen") as m:
            r = llm.ping("qwen")
        m.assert_not_called()
        self.assertEqual(r["status"], "missing_key")
        self.assertIn("缺密钥，待用户提供", llm.format_ping(r))

    def test_success_report_has_no_key_or_reply_text(self):
        self.write_key("deepseek.key.local", FAKE_KEY)
        with mock.patch("urllib.request.urlopen", return_value=FakeResp(ok_body("好的", "ds-x"))) as m:
            r = llm.ping("deepseek")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["chars"], 2)
        self.assertEqual(r["model"], "ds-x")
        body = json.loads(m.call_args[0][0].data.decode("utf-8"))
        self.assertLessEqual(body["max_tokens"], 20)
        text = llm.format_ping(r)
        self.assertIn("成功", text)
        self.assertIn("ds-x", text)
        self.assertNotIn(FAKE_KEY, text)
        self.assertNotIn("好的", text)

    def test_failure_report(self):
        self.write_key("deepseek.key.local", FAKE_KEY)
        with mock.patch("urllib.request.urlopen", side_effect=http_error(400)):
            r = llm.ping("deepseek", model="no-such-model")
        self.assertEqual(r["status"], "fail")
        text = llm.format_ping(r)
        self.assertIn("失败", text)
        self.assertIn("no-such-model", text)
        self.assertNotIn(FAKE_KEY, text)


class MainTest(KeyFileTestCase):
    def run_main(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = llm.main(argv)
        return code, buf.getvalue()

    def test_all_missing_keys_exit_zero(self):
        with mock.patch("urllib.request.urlopen") as m:
            code, out = self.run_main(["ping"])
        m.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual(out.count("缺密钥，待用户提供"), 3)

    def test_failure_exit_one(self):
        self.write_key("deepseek.key.local", FAKE_KEY)
        with mock.patch("urllib.request.urlopen", side_effect=http_error(401)):
            code, out = self.run_main(["ping", "--only", "deepseek"])
        self.assertEqual(code, 1)
        self.assertNotIn(FAKE_KEY, out)

    def test_model_requires_only(self):
        with self.assertRaises(SystemExit) as cm:
            with contextlib.redirect_stderr(io.StringIO()):
                llm.main(["ping", "--model", "x"])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
