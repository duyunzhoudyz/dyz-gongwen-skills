#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单文件 GB/T 9704 HTML 轻排版（build_html.py）及工具箱接口测试。"""
from __future__ import annotations

import base64
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "gongwen-format" / "scripts"))
sys.path.insert(0, str(ROOT / "xinchuang"))

import build_html  # noqa: E402
import local_toolbox  # noqa: E402


SAMPLE_NOTICE = """关于召开全区冬季供暖协调会的通知

各街道办事处、区直有关部门：

为做好今冬供暖保障工作，定于2026年11月25日下午2时30分在区政府三楼会议室召开协调会。现将有关事项通知如下：

一、参会人员
各街道分管负责人，区城管局、区财政局主要负责人。

二、会议内容
（一）通报管网检修进度。重点核查老旧小区换热站试压情况。
（二）部署寒潮应急值班。

| 单位 | 联系人 | 报送截止 |
| --- | --- | --- |
| 城管局 | 王某 | 11月24日 |

附件：1. 参会回执表
2. 换热站排查清单

某区人民政府办公室
2026年11月22日

【起草说明】
假设：按会议通知白头排。
"""


class TestBuildHtml(unittest.TestCase):
    def test_auto_white_layout_and_cutoff(self) -> None:
        html_doc, report = build_html.build_html(SAMPLE_NOTICE.splitlines())
        self.assertEqual(report["layout"], "白头")
        self.assertIn("关于召开全区冬季供暖协调会的通知", html_doc)
        self.assertIn("各街道办事处、区直有关部门：", html_doc)
        self.assertIn("@page", html_doc)
        self.assertIn("margin: 37mm 26mm 35mm 28mm", html_doc)
        self.assertIn("打印 / 存为 PDF", html_doc)
        self.assertIn("复制纯文本", html_doc)
        self.assertIn("复制富文本", html_doc)
        self.assertIn('<table class="gw-table">', html_doc)
        self.assertIn("gw-attachment-first", html_doc)
        self.assertNotIn("【起草说明】", html_doc)
        self.assertNotIn("按会议通知白头排", html_doc)

    def test_redhead_and_meta(self) -> None:
        meta = {
            "发文机关标志": "某区人民政府办公室文件",
            "发文字号": "某政办发〔2026〕18号",
            "抄送": ["区委办公室", "区人大常委会办公室"],
            "印发机关": "某区人民政府办公室",
            "印发日期": "2026年11月22日印发",
        }
        html_doc, report = build_html.build_html(SAMPLE_NOTICE.splitlines(), meta=meta)
        self.assertEqual(report["layout"], "红头")
        self.assertIn('data-layout="红头"', html_doc)
        self.assertIn("某区人民政府办公室文件", html_doc)
        self.assertIn("某政办发〔2026〕18号", html_doc)
        self.assertIn("抄送：区委办公室，区人大常委会办公室。", html_doc)

    def test_note_layout_and_xss_escape(self) -> None:
        lines = [
            "关于停水检修的通知",
            "各位居民：",
            "明早8时停水<script>alert(1)</script>，请提前储水。",
            "某社区居委会",
            "2026年11月22日",
        ]
        html_doc, report = build_html.build_html(lines, layout="便签")
        self.assertEqual(report["layout"], "便签")
        self.assertNotIn("<script>alert(1)</script>", html_doc)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_doc)

    def test_cli_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "notice.txt"
            out = Path(tmp) / "notice.html"
            src.write_text(SAMPLE_NOTICE, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = build_html.main([str(src), "-o", str(out), "--layout", "白头", "--json"])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(buf.getvalue())["layout"], "白头")
            self.assertTrue(out.is_file())
            content = out.read_text(encoding="utf-8")
            self.assertIn("<!doctype html>", content)
            self.assertIn("关于召开全区冬季供暖协调会的通知", content)

    def test_toolbox_format_html(self) -> None:
        res = local_toolbox.op_format_html({"b": SAMPLE_NOTICE})
        self.assertTrue(res["ok"])
        self.assertEqual(res["mode"], "html_lite")
        decoded = base64.b64decode(res["html_b64"]).decode("utf-8")
        self.assertIn("关于召开全区冬季供暖协调会的通知", decoded)
        self.assertNotIn("【起草说明】", decoded)

    def test_empty_input_error(self) -> None:
        res = local_toolbox.op_format_html({"b": "   \n【起草说明】\n无"})
        self.assertFalse(res["ok"])

    def test_sign_block_follows_gbt9704_7352(self) -> None:
        html_doc, _ = build_html.build_html(SAMPLE_NOTICE.splitlines())
        self.assertIn('<div class="gw-sign-block"><p class="gw-signature">某区人民政府办公室</p>'
                      '<p class="gw-date">2026年11月22日</p></div>', html_doc)
        # 块右缘右空二字，日期比署名右移二字
        self.assertIn("margin: 28pt 2em 0 auto", html_doc)
        self.assertRegex(html_doc, r"\.gw-date \{[^}]*padding-left: 2em")

    def test_page_number_and_line_breaking(self) -> None:
        html_doc, _ = build_html.build_html(SAMPLE_NOTICE.splitlines())
        self.assertIn("@bottom-right", html_doc)
        self.assertIn("@bottom-left", html_doc)
        self.assertIn('content: "— " counter(page) " —"', html_doc)
        self.assertNotRegex(html_doc, r"\.gw-p \{[^}]*word-break: break-all")
        self.assertIn(".gw-wb { word-break: break-all; }", html_doc)

    def test_material_alias_and_layout_options(self) -> None:
        self.assertEqual(build_html.VALID_LAYOUTS, ("白头", "红头", "便签"))
        _, report = build_html.build_html(SAMPLE_NOTICE.splitlines(), layout="材料")
        self.assertEqual(report["layout"], "白头")
        _, report = build_html.build_html(["关于加强窗口服务的汇报材料", "今年以来，窗口办件量稳步增长。"])
        self.assertEqual(report["layout"], "白头")

    def test_redhead_placeholder_not_printed(self) -> None:
        html_doc, _ = build_html.build_html(SAMPLE_NOTICE.splitlines(), layout="红头")
        self.assertIn('data-placeholder="', html_doc)
        self.assertIn('<div class="gw-issuer" contenteditable="true"', html_doc)
        self.assertIn(".gw-issuer:empty::before { content: none; }", html_doc)
        self.assertNotIn(">（发文机关标志", html_doc)

    def test_tail_kept_with_last_paragraph(self) -> None:
        lines = ["关于停水检修的通知", "各位居民：", "明早8时停水，请提前储水。", "附件：停水范围示意图",
                 "某社区居委会", "2026年11月22日"]
        html_doc, _ = build_html.build_html(lines)
        # 落款与附件说明、最后一段正文放进同一个不分页的容器，避免落款单独成页
        self.assertRegex(html_doc, r'<div class="gw-tail"><p class="gw-p">明早8时停水，请提前储水。</p>'
                                   r'<p class="gw-attachment gw-attachment-first">.*?<div class="gw-sign-block">')
        self.assertIn(".gw-tail { break-inside: avoid;", html_doc)
        # 表格之后直接是附件说明的，只把附件说明与落款放在一起
        html_doc, _ = build_html.build_html(SAMPLE_NOTICE.splitlines())
        self.assertIn('</table>\n<div class="gw-tail"><p class="gw-attachment gw-attachment-first">', html_doc)

    def test_attachment_grid_alignment(self) -> None:
        html_doc, _ = build_html.build_html(SAMPLE_NOTICE.splitlines())
        self.assertIn('<span class="gw-att-label">附件：</span><span class="gw-att-no">1. </span>'
                      '<span class="gw-att-name">参会回执表</span>', html_doc)
        self.assertIn('<span class="gw-att-label"></span><span class="gw-att-no">2. </span>', html_doc)
        self.assertIn("grid-template-columns: 3em auto 1fr", html_doc)

    def test_long_ascii_token_breakable(self) -> None:
        lines = ["关于公布查询网址的通知", "各单位：",
                 "请登录 https://www.example.gov.cn/notice/2026/heating-plan.html 查询，联系电话010-12345678。",
                 "某局", "2026年11月22日"]
        html_doc, _ = build_html.build_html(lines)
        self.assertIn('<span class="gw-wb">https://www.example.gov.cn/notice/2026/heating-plan.html</span>', html_doc)
        self.assertNotIn('<span class="gw-wb">010-12345678</span>', html_doc)

    def test_markdown_residue_cleaned(self) -> None:
        lines = ["# 关于做好防汛工作的通知", "", "各单位：", "",
                 "**一、总体要求**", "要落实 __责任__，参照`实施方案`执行。", "---", "```", "代码围栏", "```",
                 "| 单位 | 联系人 |", "|---|---|", "| 城管局 | 王某 |",
                 "某局", "2026年11月22日"]
        html_doc, _ = build_html.build_html(lines)
        body = html_doc.split('<div id="gwDocBody">')[1].split("</article>")[0]
        self.assertIn("关于做好防汛工作的通知", body)
        for bad in ("# 关于", "**", "__", "`", "---"):
            self.assertNotIn(bad, body)
        self.assertIn("一、总体要求", body)
        self.assertIn("要落实 责任，参照实施方案执行。", body)
        # 表格仍是 1 个表头行 + 1 个数据行，分隔行不渲染
        self.assertEqual(body.count("<th>"), 2)
        self.assertEqual(body.count("<td>"), 2)

    def test_double_underscore_inside_word_kept(self) -> None:
        """词内的 __ 不是强调标记：a__b__c、snake__case__name 保留原样；独立的 __重点__ 仍被去标记。"""
        cleaned = build_html.clean_markdown_lines(["a__b__c", "变量名 snake__case__name 不变", "__重点__", "要落实__责任__。", "**加粗**"])
        self.assertEqual(cleaned[0], "a__b__c")
        self.assertIn("snake__case__name", cleaned[1])
        self.assertEqual(cleaned[2], "重点")
        self.assertEqual(cleaned[3], "要落实责任。")
        self.assertEqual(cleaned[4], "加粗")

    def test_standalone_separator_dropped(self) -> None:
        lines = ["关于测试的通知", "各单位：", "|---|---|", "正文一段。", "某局", "2026年11月22日"]
        html_doc, _ = build_html.build_html(lines)
        self.assertNotIn("<th>", html_doc)
        self.assertNotIn("|---|", html_doc)

    def test_official_text_untouched(self) -> None:
        lines = ["关于做好工作的通知", "各单位：", "一、加强领导", "（一）落实《工作方案》。", "某局", "2026年11月22日"]
        html_doc, _ = build_html.build_html(lines)
        self.assertIn("一、加强领导", html_doc)
        self.assertIn("落实《工作方案》。", html_doc)
        self.assertIn("2026年11月22日", html_doc)

    def test_control_chars_removed(self) -> None:
        lines = ["关于测试\x01的通知", "各单位：", "正文\x0b内容\x00结束\x1f。", "某局", "2026年11月22日"]
        html_doc, _ = build_html.build_html(lines)
        for ch in ("\x00", "\x01", "\x0b", "\x1f"):
            self.assertNotIn(ch, html_doc)
        self.assertIn("关于测试的通知", html_doc)

    def test_cli_gbk_input_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "gbk.txt"
            src.write_bytes(SAMPLE_NOTICE.encode("gb18030"))
            out = Path(td) / "gbk.html"
            err = io.StringIO()
            from contextlib import redirect_stderr
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = build_html.main([str(src), "-o", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("GB18030", err.getvalue())
            self.assertIn("关于召开全区冬季供暖协调会的通知", out.read_text(encoding="utf-8"))

    def test_cli_undecodable_input_friendly_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "bad.txt"
            src.write_bytes(b"\x81\x30\xff\xfe\x80\x81 bad")
            err = io.StringIO()
            from contextlib import redirect_stderr
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = build_html.main([str(src), "-o", str(Path(td) / "x.html")])
            self.assertNotEqual(code, 0)
            self.assertIn("编码", err.getvalue())


if __name__ == "__main__":
    unittest.main()
