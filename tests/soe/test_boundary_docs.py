"""gongwen-soe 边界说明、核验日期和评测覆盖的守护测试。"""
import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "skills" / "gongwen-soe"
REFS = SKILL / "references"


def _lines(path: Path):
    return path.read_text(encoding="utf-8").split("\n")


class VerifiedDateHeaderTest(unittest.TestCase):
    def test_header_line_format(self):
        """references 下 4 份文件开头 5 行内须有“> 核验日期：YYYY-MM-DD”，且首行是一级标题。"""
        for name in ("glossary.md", "redlines.md", "calendar.md", "profile-detail.md"):
            lines = _lines(REFS / name)
            self.assertTrue(lines[0].startswith("# "), name)
            self.assertTrue(
                any(re.fullmatch(r"> 核验日期：\d{4}-\d{2}-\d{2}", line.rstrip()) for line in lines[:5]),
                name,
            )


class BoundaryTextTest(unittest.TestCase):
    def test_skill_points_to_boundary_section(self):
        """只断言锚点，不锁整句：SKILL.md 说明按提交的会议判归属并指向第八部分，画像里有第八部分标题。"""
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        detail = (REFS / "profile-detail.md").read_text(encoding="utf-8")
        self.assertIn("提交给哪个会议", skill)
        self.assertIn("第八部分", skill)
        self.assertIn("## 八、", detail)

    def test_old_ambiguous_parenthesis_removed(self):
        """旧括注“这些单位所属的国有企业仍归本包”可被读成学校所属企业的议题归本包，不得再出现。"""
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("这些单位所属的国有企业仍归本包", skill)


class EvalCoverageTest(unittest.TestCase):
    def setUp(self):
        data = json.loads((SKILL / "evals" / "evals.json").read_text(encoding="utf-8"))
        self.items = data["evals"]

    def test_coverage_minimums(self):
        anti = sum(1 for e in self.items if "防编造" in e["tags"])
        review = sum(1 for e in self.items if e.get("role_mode") == "审稿模式")
        secrecy = sum(1 for e in self.items if "保密" in e["tags"])
        boundary = sum(1 for e in self.items if "边界" in e["tags"] and any("转交" in t for t in e["tags"]))
        self.assertGreaterEqual(anti, 5)
        self.assertGreaterEqual(review, 3)
        self.assertGreaterEqual(secrecy, 3)
        self.assertGreaterEqual(boundary, 3)

    def test_files_exist(self):
        for e in self.items:
            for rel in e.get("files", []):
                self.assertTrue((SKILL / rel).is_file(), rel)

    def test_handoff_targets_exist(self):
        """边界转交用例里点名的转交目标 skill，在 skills/ 下必须存在。"""
        pattern = re.compile(r"gongwen-[a-z0-9]+(?:-[a-z0-9]+)*")
        checked = 0
        for e in self.items:
            if "边界" not in e["tags"] or not any("转交" in t for t in e["tags"]):
                continue
            text = json.dumps(e, ensure_ascii=False)
            for name in set(pattern.findall(text)):
                checked += 1
                self.assertTrue((REPO / "skills" / name).is_dir(), f"用例 {e['id']} 点名的 {name} 不存在")
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
