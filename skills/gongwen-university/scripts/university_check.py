#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高校专用文书的行业机检（gongwen-university）。

在通用机检 gongwen_lint.py 与申报书形式审查 proposal_check.py 之外，补查高校 6 类专用文书
（审核评估自评、学科评估、学院总结、辅导员材料、校内签报/两级发文、大会报告提纲）的高频行业红线：
  - 规范提法：“双一流”误写为“入选/获批”（UNI-001）、旧称“就业率”（UNI-007）；
  - 事实与学术规范：无依据领先/填补空白（UNI-002）、成果/经费状态升级（UNI-003）、自评照抄提示语（UNI-006）；
  - 法规与隐私：违规招生承诺（UNI-004）、学生敏感隐私外露（UNI-005）、辅导员越界诊断用药（UNI-008）、
    部门越权对外行文或白头规避（UNI-009）、公开材料点名师德不合格（UNI-010）；
  - 程序矛盾：签报同时出现“经研究同意”与“意见尚未征求/待会签”（UNI-101）。

用法：
    python scripts/university_check.py <文件> [--type 文书] [--external] [--json] [--strict]
    python scripts/university_check.py --list-rules

输入 .txt、.md、.docx（docx 需要 python-docx），遇到单独成行的【起草说明】即停止读取。
输出字段与 gongwen_lint.py 一致（file、doc_type、char_count、summary、issues）。
退出码：0 正常；--strict 且存在 P0 时为 1；输入错误为 2。
只依赖标准库；规则在同目录的 university_rules.json 中，不联网、不写文件。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Sequence, Tuple

VERSION = "1.0.0"
RULES_PATH = Path(__file__).resolve().parent / "university_rules.json"
LEVELS = ("P0", "P1", "P2")
EXTERNAL_TYPE = "对外材料"

DRAFT_NOTE_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:(?:\*\*|__)\s*)?【起草说明】")
SENTENCE_END = "。！？；!?;\n"
TODO_MARK_RE = re.compile(r"【待补：[^】\n]*】")
VERIFY_MARK_RE = re.compile(r"【待核实：[^】\n]*】")


class InputError(Exception):
    """输入错误，退出码 2。"""


@dataclass
class Rule:
    id: str
    category: str
    gate: str
    level: str
    message: str
    suggestion: str
    basis: str
    types: Tuple[str, ...] = ()
    regex: Optional[Pattern[str]] = None
    external_level: Optional[str] = None
    trigger: Optional[Pattern[str]] = None
    contradict: Optional[Pattern[str]] = None
    hit_examples: List[str] = field(default_factory=list)
    miss_examples: List[str] = field(default_factory=list)

    def applies(self, doc_type: Optional[str]) -> bool:
        if not self.types or not doc_type:
            return True
        return doc_type in self.types


@dataclass
class RuleSet:
    types: Tuple[str, ...]
    rules: List[Rule]
    procedural: List[Rule]


def _compile(pattern: Optional[str], rid: str, name: str) -> Optional[Pattern[str]]:
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise InputError(f"规则 {rid} 的正则 {name} 无效：{exc}") from exc


def load_rules(path: Path = RULES_PATH) -> RuleSet:
    if not path.is_file():
        raise InputError(f"规则文件不存在：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"无法读取规则文件 {path}：{exc}") from exc

    types = tuple(data.get("types", ()))
    rules: List[Rule] = []
    for item in data.get("rules", ()):
        rules.append(
            Rule(
                id=item["id"],
                category=item["category"],
                gate=item["gate"],
                level=item["level"],
                message=item["message"],
                suggestion=item["suggestion"],
                basis=item["basis"],
                types=tuple(item.get("types", ())),
                regex=_compile(item.get("pattern"), item["id"], "pattern"),
                external_level=item.get("external_level"),
                hit_examples=list(item.get("hit_examples", ())),
                miss_examples=list(item.get("miss_examples", ())),
            )
        )
    procedural: List[Rule] = []
    for item in data.get("procedural", ()):
        procedural.append(
            Rule(
                id=item["id"],
                category=item["category"],
                gate=item["gate"],
                level=item["level"],
                message=item["message"],
                suggestion=item["suggestion"],
                basis=item["basis"],
                types=tuple(item.get("types", ())),
                trigger=_compile(item.get("trigger"), item["id"], "trigger"),
                contradict=_compile(item.get("contradict"), item["id"], "contradict"),
            )
        )
    return RuleSet(types=types, rules=rules, procedural=procedural)


def _strip_draft_note(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: List[str] = []
    for ln in lines:
        if DRAFT_NOTE_RE.match(ln):
            break
        kept.append(ln)
    return "\n".join(kept)


def read_input(path: Path) -> str:
    if not path.is_file():
        raise InputError(f"输入文件不存在：{path}")
    suf = path.suffix.lower()
    if suf == ".docx":
        try:
            import docx  # type: ignore
        except ImportError as exc:
            raise InputError("读取 .docx 需要安装 python-docx（pip install python-docx）") from exc
        doc = docx.Document(str(path))
        parts = [p.text for p in doc.paragraphs]
        for tb in doc.tables:
            for row in tb.rows:
                parts.append(" ".join(cell.text.strip() for cell in row.cells))
        return _strip_draft_note("\n".join(parts))
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise InputError(f"读取文件失败：{exc}") from exc
    return _strip_draft_note(raw)


def _line_col(text: str, pos: int) -> Tuple[int, int]:
    line = text.count("\n", 0, pos) + 1
    last_nl = text.rfind("\n", 0, pos)
    col = pos - last_nl
    return line, col


def _sentence_around(text: str, start: int, end: int) -> str:
    left = start
    while left > 0 and text[left - 1] not in SENTENCE_END:
        left -= 1
    right = end
    while right < len(text) and text[right] not in SENTENCE_END:
        right += 1
    return text[left:right].strip()[:120]


def _is_near(text: str, a: int, b: int) -> bool:
    """两个位置是否在同一句或相邻句内（不跨段）。"""
    lo, hi = (a, b) if a <= b else (b, a)
    between = text[lo:hi]
    if "\n" in between:
        return False
    return sum(1 for ch in between if ch in SENTENCE_END) <= 1


def check_text(
    text: str,
    *,
    doc_type: Optional[str] = None,
    external: bool = False,
    filename: str = "<text>",
    ruleset: Optional[RuleSet] = None,
) -> Dict[str, Any]:
    rs = ruleset or load_rules()
    if doc_type and doc_type not in rs.types:
        raise InputError(f"不支持的文书类型：{doc_type}（可选：{'、'.join(rs.types)}）")

    body = _strip_draft_note(text)
    is_ext = external or (doc_type == EXTERNAL_TYPE)
    issues: List[Dict[str, Any]] = []

    for rule in rs.rules:
        if not rule.applies(doc_type) or rule.regex is None:
            continue
        lvl = rule.external_level if (is_ext and rule.external_level) else rule.level
        for m in rule.regex.finditer(body):
            line, col = _line_col(body, m.start())
            issues.append(
                {
                    "rule_id": rule.id,
                    "level": lvl,
                    "gate": rule.gate,
                    "category": rule.category,
                    "line": line,
                    "col": col,
                    "match": m.group(0),
                    "context": _sentence_around(body, m.start(), m.end()),
                    "message": rule.message,
                    "suggestion": rule.suggestion,
                    "basis": rule.basis,
                }
            )

    for rule in rs.procedural:
        if not rule.applies(doc_type) or rule.trigger is None or rule.contradict is None:
            continue
        # 只在同一句或相邻句（同一段内）同时出现才算前后矛盾，避免全文远距离误报
        m_trig = m_cont = None
        for mt in rule.trigger.finditer(body):
            for mc in rule.contradict.finditer(body):
                if _is_near(body, mt.start(), mc.start()):
                    m_trig, m_cont = mt, mc
                    break
            if m_trig:
                break
        if m_trig and m_cont:
            line, col = _line_col(body, m_cont.start())
            issues.append(
                {
                    "rule_id": rule.id,
                    "level": rule.level,
                    "gate": rule.gate,
                    "category": rule.category,
                    "line": line,
                    "col": col,
                    "match": f"{m_trig.group(0)} / {m_cont.group(0)}",
                    "context": _sentence_around(body, m_cont.start(), m_cont.end()),
                    "message": rule.message,
                    "suggestion": rule.suggestion,
                    "basis": rule.basis,
                }
            )

    order = {lv: i for i, lv in enumerate(LEVELS)}
    issues.sort(key=lambda it: (order.get(it["level"], 9), it["line"], it["col"], it["rule_id"]))

    counts = {lv: sum(1 for it in issues if it["level"] == lv) for lv in LEVELS}
    markers = {
        "todo": len(TODO_MARK_RE.findall(body)),
        "verify": len(VERIFY_MARK_RE.findall(body)),
    }
    return {
        "file": filename,
        "doc_type": doc_type or "未指定",
        "external": is_ext,
        "char_count": len(body.replace("\n", "").replace(" ", "")),
        "summary": {
            "P0": counts["P0"],
            "P1": counts["P1"],
            "P2": counts["P2"],
            "total": len(issues),
            "markers": markers,
        },
        "issues": issues,
    }


def render_text(result: Dict[str, Any]) -> str:
    s = result["summary"]
    lines = [
        f"高校专用文书机检：{result['file']}（类型：{result['doc_type']}｜字数：{result['char_count']}）",
        f"汇总：P0 {s['P0']}｜P1 {s['P1']}｜P2 {s['P2']}｜共 {s['total']} 项"
        f"（【待补】{s['markers']['todo']}｜【待核实】{s['markers']['verify']}）",
    ]
    if not result["issues"]:
        lines.append("未检出高校行业规则问题。")
        return "\n".join(lines)
    for idx, it in enumerate(result["issues"], 1):
        lines.append(
            f"{idx}. [{it['level']}][{it['rule_id']}] 第{it['line']}行：{it['message']}"
            f"（命中：{it['match']}）"
        )
        lines.append(f"   建议：{it['suggestion']}")
        lines.append(f"   依据：{it['basis']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="高校专用文书行业机检（gongwen-university）。")
    p.add_argument("file", nargs="?", type=Path, help="待检文件（.txt / .md / .docx）")
    p.add_argument("--type", dest="doc_type", default=None, help="文书类型：审核评估/学科评估/学院总结/辅导员/签报/大会提纲/对外材料")
    p.add_argument("--external", action="store_true", help="按对外材料从严定级")
    p.add_argument("--json", dest="as_json", action="store_true", help="输出 JSON")
    p.add_argument("--strict", action="store_true", help="存在 P0 问题时返回退出码 1")
    p.add_argument("--list-rules", action="store_true", help="列出全部规则并退出")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        # 被工具箱以 mod.main(argv) 方式调用时，不得向调用方抛 SystemExit
        return 0 if exc.code == 0 else 2
    try:
        rs = load_rules()
        if args.list_rules:
            for r in list(rs.rules) + list(rs.procedural):
                ts = "、".join(r.types) if r.types else "全部"
                print(f"{r.id}\t{r.level}\t{r.category}\t[{ts}]\t{r.message}")
            return 0
        if args.file is None:
            raise InputError("请提供待检文件路径，或使用 --list-rules")
        text = read_input(args.file)
        result = check_text(
            text,
            doc_type=args.doc_type,
            external=args.external,
            filename=str(args.file),
            ruleset=rs,
        )
    except InputError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_text(result))

    if args.strict and result["summary"]["P0"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
