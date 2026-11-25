# -*- coding: utf-8 -*-
"""本机工具箱（xinchuang/local_toolbox.py）行业专检接口单元测试。

运行：python -m unittest tests.tools.test_local_toolbox_industry -v
"""
from __future__ import annotations

import http.client
import json
import re
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
XINCHUANG_DIR = REPO_ROOT / "xinchuang"
if str(XINCHUANG_DIR) not in sys.path:
    sys.path.insert(0, str(XINCHUANG_DIR))

import local_toolbox as tb  # noqa: E402


class LocalToolboxIndustryCheckTests(unittest.TestCase):
    def test_empty_text_rejected(self):
        res = tb.op_industry_check({"b": "   ", "industry": "grassroots"})
        self.assertFalse(res["ok"])
        self.assertIn("没有待检正文", res["text"])

    def test_grassroots_coercion_and_burden(self):
        text = "森林防火通知\n各位村民：\n未签责任书的取消分红资格。\n某村民委员会\n2026年10月16日\n"
        res = tb.op_industry_check({"b": text, "industry": "grassroots"})
        self.assertFalse(res["ok"])
        self.assertIn("NTC-018", res["text"])

    def test_hospital_external_p0(self):
        res = tb.op_industry_check({
            "b": "我院中医特色疗法保证治愈，永不复发。",
            "industry": "hospital",
            "ind_external": True,
        })
        self.assertFalse(res["ok"])
        self.assertIn("HOS-001", res["text"])

    def test_hospital_patient_privacy_masked(self):
        res = tb.op_industry_check({
            "b": "患者张某（床号12）夜间跌倒。当班护士李娜未执行双人核对。",
            "industry": "hospital",
            "doc_type": "RCA",
        })
        self.assertFalse(res["ok"])
        self.assertIn("HOS-030", res["text"])
        self.assertNotIn("李娜", res["text"])

    def test_soe_procedure_check(self):
        res = tb.op_industry_check({
            "b": "本项目先行开工，后续再补办党委会前置研究和董事会审议程序。",
            "industry": "soe",
            "doc_type": "议题材料",
        })
        self.assertFalse(res["ok"])
        self.assertIn("SOE-001", res["text"])

    def test_k12_parents_and_general(self):
        res_p = tb.op_industry_check({
            "b": "请各位家长今晚检查并批改孩子的数学作业。",
            "industry": "k12_parents",
        })
        self.assertFalse(res_p["ok"])
        self.assertIn("JZ-001", res_p["text"])

        res_g = tb.op_industry_check({
            "b": "课后服务统一讲授新课，要求学生强制参加。",
            "industry": "k12_general",
        })
        self.assertFalse(res_g["ok"])
        self.assertIn("K12-G03", res_g["text"])

    def test_university_and_blind_proposal(self):
        res_u = tb.op_industry_check({
            "b": "签约后保证录取并提供内部指标。",
            "industry": "university",
        })
        self.assertFalse(res_u["ok"])
        self.assertIn("UNI-004", res_u["text"])

        res_b = tb.op_industry_check({
            "b": "本研究由张三主持，在我校开展前期调研。",
            "industry": "university_blind",
            "terms": "张三、某大学",
        })
        self.assertFalse(res_b["ok"])
        self.assertIn("[P0] 匿名", res_b["text"])
        self.assertIn("〔身份词〕", res_b["text"])

    def test_three_industry_engines_in_one_process_do_not_cross(self):
        """同一进程里依次运行医院、国企、中小学（general）三个行业专检：都能加载共享模块 gw_names，
        结果各报各的规则号，姓名占位互不串用（每个包自己的全文姓名表，各自从〔姓名1〕编起）。"""
        hos = tb.op_industry_check({
            "b": "患者王建国术后发热。\n当班护士孙丽未执行双人核对。\n患者王建国对处置表示理解。",
            "industry": "hospital", "doc_type": "RCA",
        })
        soe = tb.op_industry_check({
            "b": "会议研究决定：对马建国给予记过处分，周杰同志受到警告处分。",
            "industry": "soe", "doc_type": "纪要",
        })
        k12 = tb.op_industry_check({
            "b": "低保家庭学生郭晓东，需重点关怀。\n特困学生：陈美玲，杨海涛",
            "industry": "k12_general",
        })
        for res in (hos, soe, k12):
            self.assertFalse(res["ok"])
        # 各报各的规则号，不串用
        self.assertIn("HOS-031", hos["text"])
        self.assertIn("HOS-032", hos["text"])
        self.assertNotIn("SOE-022", hos["text"] + k12["text"])
        self.assertIn("SOE-022", soe["text"])
        self.assertNotIn("HOS-03", soe["text"] + k12["text"])
        self.assertIn("K12-G04", k12["text"])
        self.assertNotIn("K12-G04", hos["text"] + soe["text"])
        # 姓名全部遮蔽，占位互不影响：每份结果各自从〔姓名1〕编起
        for name in ("王建国", "孙丽", "马建国", "周杰", "郭晓东", "陈美玲", "杨海涛"):
            for res in (hos, soe, k12):
                self.assertNotIn(name, res["text"], name)
        for res in (hos, soe, k12):
            self.assertIn("〔姓名1〕", res["text"])
        self.assertIn("〔姓名2〕", hos["text"])   # 王建国、孙丽
        self.assertIn("〔姓名2〕", soe["text"])   # 马建国、周杰
        self.assertIn("〔姓名3〕", k12["text"])   # 郭晓东、陈美玲、杨海涛
        # 三个包各自加载自己目录里的共享模块，模块对象互不相同
        mods = [sys.modules.get(f"_gw_gongwen-{pkg}_gw_names") for pkg in ("hospital", "soe", "k12")]
        self.assertTrue(all(m is not None for m in mods))
        self.assertEqual(len({id(m) for m in mods}), 3)
        # 再各跑一遍（缓存已建立），结果不变
        self.assertEqual(hos["text"], tb.op_industry_check({
            "b": "患者王建国术后发热。\n当班护士孙丽未执行双人核对。\n患者王建国对处置表示理解。",
            "industry": "hospital", "doc_type": "RCA"})["text"])

    def test_page_contains_industry_ui(self):
        self.assertIn('id="indPack"', tb.PAGE)
        self.assertIn('data-op="industry_check"', tb.PAGE)

    def test_leading_dash_doc_type_rejected_not_exit(self):
        """doc_type 以 - 开头不能被当成选项，更不能让进程退出。"""
        for key in ("university", "hospital", "soe"):
            res = tb.op_industry_check({"b": "关于测试的通知\n各单位：\n请知悉。", "industry": key, "doc_type": "-x"})
            self.assertFalse(res["ok"])
            self.assertIn("不能以", res["text"])

    def test_systemexit_from_script_becomes_error_result(self):
        """行业脚本内部 argparse 抛 SystemExit 时，转成普通错误结果。"""
        import types
        fake = types.SimpleNamespace(main=lambda argv: (_ for _ in ()).throw(SystemExit(2)))
        orig = tb._load_industry_module
        tb._load_industry_module = lambda key, script: fake
        try:
            res = tb.op_industry_check({"b": "正文", "industry": "university"})
        finally:
            tb._load_industry_module = orig
        self.assertFalse(res["ok"])
        self.assertTrue(res["text"])

    def test_lint_uses_readable_name(self):
        res = tb.op_lint({"b": "关于测试的通知\n各单位：\n请知悉。"})
        self.assertIn("粘贴文本", res["text"])
        self.assertNotIn("<text>", res["text"])

    def test_page_wording_not_overclaim(self):
        self.assertNotIn("不落盘", tb.PAGE)
        self.assertIn("临时目录", tb.PAGE)

    def test_http_server_survives_bad_request(self):
        """真实 HTTP 请求：构造 -x 的请求后服务仍可继续响应。"""
        import http.client
        import json
        import threading
        server = tb.HTTPServer((tb.HOST, 0), tb.Handler)
        port = server.server_address[1]
        th = threading.Thread(target=server.serve_forever, daemon=True)
        th.start()
        try:
            def post(path, body):
                conn = http.client.HTTPConnection(tb.HOST, port, timeout=20)
                conn.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
                resp = conn.getresponse()
                data = json.loads(resp.read().decode("utf-8"))
                conn.close()
                return resp.status, data
            st, data = post("/api/industry_check", {"b": "关于测试的通知\n各单位：\n请知悉。", "industry": "university", "doc_type": "-x"})
            self.assertEqual(st, 200)
            self.assertFalse(data["ok"])
            self.assertTrue(th.is_alive())
            st, data = post("/api/lint", {"b": "关于测试的通知\n各单位：\n请知悉。"})
            self.assertEqual(st, 200)
            self.assertIn("机检结果", data["text"])
        finally:
            server.shutdown()
            server.server_close()


class LocalToolboxK12CommentsHTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = tb.HTTPServer((tb.HOST, 0), tb.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def post(self, body, names=("王小明", "张小明", "陈子豪")):
        return self.post_raw(json.dumps({"industry": "k12_comments", **body}, ensure_ascii=False), names)

    def post_raw(self, body, forbidden):
        conn = http.client.HTTPConnection(tb.HOST, self.port, timeout=20)
        try:
            conn.request("POST", "/api/industry_check", body.encode("utf-8"),
                         {"Content-Type": "application/json"})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
        finally:
            conn.close()
        for value in forbidden:
            self.assertNotIn(value, raw)
            self.assertNotIn(value, json.dumps(data, ensure_ascii=False))
        return data

    def test_rejects_invalid_or_real_name_labels_without_processing_any_row(self):
        for text in ("王小明：你很懒。", "S01：你参与了值日。\n张小明：你很笨。",
                     "王小明·陈子豪：你很懒。", "S1：王小明同学说你很笨。",
                     "S０１：王小明同学说你很笨。", "S01 王小明：你很懒。",
                     "| 姓名 | 评语 |\n| --- | --- |\n| 王小明 | 你很懒 |"):
            with self.subTest(text=text), patch.object(tb, "_load_industry_module") as load:
                self.assertEqual(self.post({"b": text}), {"ok": False, "text": tb.K12_COMMENT_LABEL_ERROR})
                load.assert_not_called()

    def test_numbered_body_does_not_echo_names_or_other_raw_fields(self):
        for body, rid in (("S01：王小明同学说你是笨蛋。", "PY-001"),
                          ("S01：你学王小明，笨得像猪一样。", "PY-001"),
                          ("S01：王小明同学说你是差生。", "PY-002"),
                          ("S0204：陈子豪同学说你很懒。", "PY-002")):
            with self.subTest(body=body):
                data = self.post({"b": body})
                self.assertEqual(set(data), {"ok", "text"})
                self.assertIn(f"{rid} 第 1 行 {tb.K12_COMMENT_ADVICE[rid]}。", data["text"])
                self.assertNotIn("原文", data["text"])
        repeated = "\n".join(f"S0{i}：王小明同学说你的朗读很有感情。" for i in range(1, 4))
        self.assertIn("[P2] PY-008 S01 ", self.post({"b": repeated})["text"])

    def test_unrelated_left_fields_are_ignored_and_no_fact_comparison_runs(self):
        right = "S01：你完成了课代表的值日工作。"
        clean = self.post({"b": right})
        dirty = self.post({"b": right, "a": "| 编号 | 具体表现 |\n| --- | --- |\n| 张小明 | 值日 |",
                           "hf_a": "陈子豪", "hf_b": "王小明", "facts": "王小明", "doc_type": "-张小明",
                           "terms": "陈子豪", "sid": "王小明"})
        self.assertEqual(dirty, clean)
        self.assertTrue(dirty["ok"])
        self.assertNotIn("PY-015", dirty["text"])

    def test_comment_labels_and_issues_use_engine_physical_rows(self):
        for separator in ("\u2028", "\u2029", "\x85", "\v", "\f", "\n", "\r\n", "\r"):
            with self.subTest(separator=repr(separator)):
                body = "S01：你很笨。" + separator + "S02：王小明说你很懒。"
                data = self.post({"b": body})
                self.assertIn("PY-001 第 1 行", data["text"])
                self.assertIn("PY-002 第 2 行", data["text"])
                body = "S01：你很笨。" + separator + "王小明：你很懒。"
                data = self.post({"b": body})
                self.assertEqual(data, {"ok": False, "text": tb.K12_COMMENT_LABEL_ERROR})

    def test_empty_right_and_invalid_stage_use_fixed_errors(self):
        data = self.post({"b": " \n ", "a": "张小明：你很懒。"})
        self.assertEqual(data, {"ok": False, "text": "右框没有待检正文。"})
        data = self.post({"b": "S01：王小明说你很懒。", "stage": "陈子豪"})
        self.assertEqual(data, {"ok": False, "text": "学段须为义务教育、高中或中职。"})

    def test_all_three_stages_are_routed_for_each_k12_entry(self):
        for stage, level in (("义务教育", "P0"), ("高中", "P1"), ("中职", "P1")):
            for industry, draft, rid in (
                ("k12_comments", "S01：王小明说你这次考试排名第一名。", "PY-003"),
                ("k12_parents", "全体学生必须购买意外伤害保险。", "JZ-006"),
                ("k12_general", "课后服务期间讲授新课。", "K12-G03"),
            ):
                with self.subTest(stage=stage, industry=industry):
                    data = self.post({"b": draft, "stage": stage, "industry": industry})
                    self.assertEqual(data["ok"], level != "P0")
                    self.assertIn(f"[{level}] {rid}", data["text"])

    def test_engine_error_cannot_echo_input(self):
        with patch.object(tb, "_load_industry_module", side_effect=ValueError("王小明无效")):
            data = self.post({"b": "S01：张小明请求重试。"})
        self.assertEqual(data, {"ok": False, "text": "评语检查失败，请核对编号格式和学段后重试。"})

    def test_r4_output_probes_over_http(self):
        fixture = REPO_ROOT / "tests/k12/samples/clause_regression/output_probes.jsonl"
        errors = {
            "empty": "右框没有待检正文。",
            "invalid_label": tb.K12_COMMENT_LABEL_ERROR,
            "invalid_stage": "学段须为义务教育、高中或中职。",
            "malformed_json": "请求正文不是有效 JSON。",
        }
        count = 0
        for probe in map(json.loads, fixture.read_text(encoding="utf-8").splitlines()):
            if "payload" not in probe and "raw_body" not in probe:
                continue
            for stage, record in probe["by_stage"].items():
                count += 1
                with self.subTest(probe=probe["id"], stage=stage):
                    expected = record["expected_output"]
                    payload = {"b": probe["text"], **probe.get("payload", {})}
                    body = probe.get("raw_body", json.dumps(payload, ensure_ascii=False))
                    data = self.post_raw(body, expected["forbidden_literals"])
                    kind = expected["response_kind"]
                    if kind in errors:
                        self.assertEqual(data, {"ok": False, "text": errors[kind]})
                        continue
                    self.assertEqual(kind, "report")
                    entry = probe["entries"][0]
                    hits = record["baseline_measured"][entry]["hits"]
                    if entry == "comments":
                        self.assertEqual(set(data), {"ok", "text"})
                        rendered = set()
                        if data["text"] != "未发现问题。":
                            for line in data["text"].splitlines():
                                match = re.fullmatch(r"\[(P[012])\] (PY-\d{3}) (第 [1-9]\d* 行|S[0-9]{2,4}) (.+)。", line)
                                self.assertIsNotNone(match, line)
                                level, rid, _where, advice = match.groups()
                                self.assertEqual(advice, tb.K12_COMMENT_ADVICE[rid])
                                rendered.add((rid, level))
                        self.assertEqual(rendered, {(rid, level) for rid, level, _ in hits})
                    else:
                        self.assertIn(f"学段：{stage}", data["text"])
                        allowed = expected["rule_allowed_levels"]
                        rendered = {(rid, level) for level, rid in
                                    re.findall(r"^\[(P[012])\] (\S+)", data["text"], re.M)}
                        retained = {(rid, level) for rid, level, _ in hits
                                    if not (rid in {"JZ-003", "K12-G01", "JZ-008"} and allowed.get(rid) == ["SKIP"])}
                        order = ("P0", "P1", "P2")
                        for rid, level in retained:
                            self.assertTrue(any(r == rid and order.index(lv) <= order.index(level)
                                                for r, lv in rendered), (rid, level, rendered))
                        for rid, level in rendered:
                            self.assertIn(level, allowed.get(rid, ()), rid)
                        for rid in record.get("expected_new_layer", {}).get(entry, {}):
                            if rid not in {"K12-G04", "K12-G06"} and "SKIP" not in allowed[rid]:
                                self.assertIn(rid, {rule for rule, _ in rendered})
                    self.assertEqual(data["ok"], all(level != "P0" for _, level, _ in hits))
                    ignored = expected["ignore_fields"]
                    if ignored:
                        clean = {key: value for key, value in payload.items() if key not in ignored}
                        self.assertEqual(data, self.post_raw(json.dumps(clean, ensure_ascii=False),
                                                             expected["forbidden_literals"]))
        self.assertEqual(count, 48)


if __name__ == "__main__":
    unittest.main()
