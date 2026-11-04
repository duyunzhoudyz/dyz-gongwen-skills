# -*- coding: utf-8 -*-
"""行业包 gongwen-university 的内容完整性测试（不依赖第三方库）。

运行：python -m unittest discover -s tests/university -t .

检查：
    1. SKILL.md 的红线小节标题统一为“行业红线”；
    2. references/ 下五份资料首部有“> 核验日期：YYYY-MM-DD”；
    3. templates/ 下每份模板都有“正误对照”小节；
    4. evals 的覆盖数量（审稿模式、保密、防编造、边界转交）和 files 文件存在；
    5. 提示词版长度不超过 tools/build_prompts.py 的硬上限。
"""
from __future__ import annotations

import datetime
import json
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "skills" / "gongwen-university"
REFS = PKG / "references"
DATE_RE = re.compile(r"^> 核验日期：(\d{4})-(\d{2})-(\d{2})$")
DATED_FILES = ("glossary.md", "redlines.md", "calendar.md", "profile-detail.md", "data-caliber.md")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


class SkillMdTests(unittest.TestCase):
    def test_redline_heading_is_unified(self):
        text = read(PKG / "SKILL.md")
        self.assertRegex(text, r"(?m)^## 行业红线$")
        self.assertNotIn("红线执行点", text)


class VerifiedDateTests(unittest.TestCase):
    def test_each_reference_has_verified_date_on_first_line_after_title(self):
        for name in DATED_FILES:
            with self.subTest(file=name):
                lines = read(REFS / name).split("\n")
                self.assertTrue(lines[0].startswith("# "), "首行应为标题")
                rest = [ln for ln in lines[1:] if ln.strip()]
                m = DATE_RE.match(rest[0])
                self.assertIsNotNone(m, "标题下第一行应为“> 核验日期：YYYY-MM-DD”")
                datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


class TemplateTests(unittest.TestCase):
    def test_every_template_has_correct_vs_wrong_section(self):
        templates = sorted((REFS / "templates").glob("*.md"))
        self.assertGreaterEqual(len(templates), 7)
        for path in templates:
            with self.subTest(file=path.name):
                self.assertRegex(read(path), r"(?m)^## .*正误对照")


class EvalCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = json.loads(read(PKG / "evals" / "evals.json"))
        cls.items = data["evals"]

    def count(self, pred):
        return sum(1 for e in self.items if pred(e))

    def test_ids_unique_and_files_exist(self):
        ids = [e["id"] for e in self.items]
        self.assertEqual(len(ids), len(set(ids)))
        for e in self.items:
            for rel in e.get("files", []):
                self.assertTrue((PKG / rel).is_file(), f"用例 {e['id']} 的 files 不存在：{rel}")

    def test_review_mode_cases(self):
        self.assertGreaterEqual(self.count(lambda e: e.get("role_mode") == "审稿模式"), 3)

    def test_secrecy_cases(self):
        self.assertGreaterEqual(self.count(lambda e: "保密" in e.get("tags", [])), 3)

    def test_anti_fabrication_cases(self):
        self.assertGreaterEqual(self.count(lambda e: "防编造" in e.get("tags", [])), 5)

    def test_boundary_handoff_cases(self):
        self.assertGreaterEqual(self.count(lambda e: "边界" in e.get("tags", [])), 2)


class PromptLengthTests(unittest.TestCase):
    def test_prompt_within_hard_limit(self):
        tools = str(REPO_ROOT / "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        # 注意：此处依赖 build_prompts 的内部 API（render_skill、MAX_PROMPT_CHARS），该模块改名或改签名时需同步修改本测试
        import build_prompts as bp

        result = bp.render_skill(PKG)
        self.assertEqual(result.errors, [])
        self.assertIsNotNone(result.doc)
        self.assertLessEqual(result.doc.char_count, bp.MAX_PROMPT_CHARS)


if __name__ == "__main__":
    unittest.main()
