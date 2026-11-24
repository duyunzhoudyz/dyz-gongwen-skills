# -*- coding: utf-8 -*-
"""行业专检的入库独立语料回归：医院、国企、中小学三个行业专检按文件路径加载（与 xinchuang/local_toolbox.py 同款方式），
对 tests/industry_corpus/<行业>/ 下的文书逐篇运行，核对机检结果。

运行：python -m unittest discover -s tests/industry_corpus -t .

目录与格式见同目录 README.md。某个行业目录下没有 cases.json 时，该行业整体跳过（不算失败）。
cases.json 格式：
  {"engine": "hospital", "docs": [
    {"file": "A_h01_RCA跌倒.txt", "type": "RCA", "external": false, "kind": "clean", "max_p1": 0, "max_p2": 0},
    {"file": "V_h02_RCA_输液外渗.txt", "type": "RCA", "kind": "violation", "names": ["赵敏华", "孙丽"],
     "expect": [{"mark": "E5", "id": "HOS-030", "level": "P0", "line": 4}], "allow_extra_p0": [],
     "known_miss": [{"mark": "E3", "id": "HOS-005", "level": "P1", "reason": "……"}]}]}
可选字段：mode（中小学子命令，general 或 parents，默认 general）、args（附加命令行参数列表，如国企的 --as-of）、
known_miss（已知漏检，必须写原因，不参与断言但留在检出率分母里）、leak_known（已知会被规则摘录带出的姓名，见下）、
shrink_cost（仅规范文书：收缩已知代价。分句豁免取消“后续分句”窗口后，否决、整改、出处写在后一分句的句子会重新被报出（后续分句里有针对该做法的处置词时 P0 降为 P1）；
把这些命中登记成 [{"id","level","line","reason"}]，它们不计入 P0、P1、P2 基线，但每条登记都必须真的出现，否则登记过期、要求清理。
没有登记的命中照旧按基线判失败，所以登记不会掩盖其他回归）。

埋点清单在同目录的 marks.json（以它为准）：每个埋点有编号、文件、行号、违规点描述、应报规则与级别、来源 source。

断言：
  1. 规范文书（clean）：P0 必须为 0；P1 不超过 max_p1（缺省 0）；P2 不超过 max_p2（缺省不检查）。
  2. 违规文书（violation）：expect 里每一条的规则编号和级别（写了 line 时还有行号）都要出现；
     不在 expect 和 allow_extra_p0 里的规则编号出现 P0 视为失败。
  3. 所有文书：names 里的姓名不得出现在 JSON 输出和文本输出里；leak_known 里的姓名是已登记的真实泄露，
     出现时只打印警告（不静默通过），若已不再出现则判失败（要求清理登记）；同一姓名不得同时在两处。
  4. 埋点对账：expect 与 known_miss 的编号都是 marks.json 里该文书编号的子集；该文书所有运行的 expect 与
     known_miss 的并集覆盖 marks.json 里该文书的全部编号；同一次运行里一个编号不能同时在 expect 和 known_miss。
  5. 检出率按埋点编号去重（同一文书多次运行只算一次，任一运行检出即检出），已知漏检留在分母，
     按 source（author / review / heldout）分别打印，不合并成一个数字；另行打印运行次数。
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from collections import defaultdict
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
CORPUS = Path(__file__).resolve().parent

ENGINE_SCRIPTS: Dict[str, Path] = {
    "hospital": ROOT / "skills" / "gongwen-hospital" / "scripts" / "hospital_check.py",
    "soe": ROOT / "skills" / "gongwen-soe" / "scripts" / "soe_check.py",
    "k12": ROOT / "skills" / "gongwen-k12" / "scripts" / "k12_check.py",
}
_MODULES: Dict[str, Any] = {}

SOURCES = ("author", "review", "heldout")
SEVERITY = {"P0": 0, "P1": 1, "P2": 2}


def load_engine(key: str):
    """按文件路径加载行业专检脚本，模块名按引擎区分。"""
    mod = _MODULES.get(key)
    if mod is not None:
        return mod
    script = ENGINE_SCRIPTS[key]
    if not script.is_file():
        raise unittest.SkipTest(f"未找到脚本：{script.name}")
    mod_name = f"_gw_corpus_{key}_{script.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, str(script))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载脚本：{script.name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    _MODULES[key] = mod
    return mod


def build_argv(engine: str, path: Path, doc: Dict[str, Any], as_json: bool) -> List[str]:
    if engine == "k12":
        argv = [str(doc.get("mode") or "general"), str(path)]
    else:
        argv = [str(path)]
        if doc.get("type"):
            argv.append("--type=" + str(doc["type"]))
        if doc.get("external"):
            argv.append("--external")
    argv += [str(a) for a in doc.get("args") or []]
    if as_json:
        argv.append("--json")
    return argv


def run_engine(mod: Any, argv: Sequence[str]) -> Tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = int(mod.main(list(argv)))
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
    return code, out.getvalue(), err.getvalue()


def leak_report(doc: Dict[str, Any], json_text: str, plain_text: str) -> Tuple[List[str], List[str]]:
    """leak_known 登记的姓名：返回 (确实出现在输出里的, 已不再出现的)。出现的由运行器打印警告。"""
    leaked: List[str] = []
    stale: List[str] = []
    for name in doc.get("leak_known") or []:
        if name in json_text or name in plain_text:
            leaked.append(name)
        else:
            stale.append(name)
    return leaked, stale


def evaluate(doc: Dict[str, Any], issues: Sequence[Dict[str, Any]], json_text: str, plain_text: str
             ) -> Tuple[List[str], List[str]]:
    """纯函数：按 cases.json 的一条记录核对机检结果。返回 (失败说明列表, 检出率表的行)。"""
    fails: List[str] = []
    rows: List[str] = []
    file_name = doc.get("file", "?")
    kind = doc.get("kind")
    levels = {"P0": 0, "P1": 0, "P2": 0}
    for it in issues:
        lv = it.get("level")
        if lv in levels:
            levels[lv] += 1
    if kind == "clean":
        cost = list(doc.get("shrink_cost") or [])
        if cost:
            counted = {"P0": 0, "P1": 0, "P2": 0}
            seen_cost = [False] * len(cost)
            for it in issues:
                lv = it.get("level")
                hit_idx = [k for k, c in enumerate(cost)
                           if c.get("id") == it.get("id") and c.get("level") == lv and c.get("line") == it.get("line")]
                if hit_idx:
                    for k in hit_idx:
                        seen_cost[k] = True
                elif lv in counted:
                    counted[lv] += 1
            for k, c in enumerate(cost):
                if not str(c.get("reason") or "").strip():
                    fails.append(f"{file_name}：shrink_cost 的 {c.get('id')} 第{c.get('line')}行没写原因")
                if not seen_cost[k]:
                    fails.append(f"{file_name}：shrink_cost 登记的 {c.get('id')} {c.get('level')} 第{c.get('line')}行已不再出现，请清理登记")
            levels = counted
        if levels["P0"]:
            ids = sorted({str(i.get("id")) for i in issues if i.get("level") == "P0"})
            fails.append(f"{file_name}：规范文书不应有 P0，实得 {levels['P0']} 处（{'、'.join(ids)}）")
        max_p1 = int(doc.get("max_p1", 0))
        if levels["P1"] > max_p1:
            fails.append(f"{file_name}：P1 {levels['P1']} 处，超过基线 {max_p1}")
        if doc.get("max_p2") is not None and levels["P2"] > int(doc["max_p2"]):
            fails.append(f"{file_name}：P2 {levels['P2']} 处，超过基线 {doc['max_p2']}")
        rows.append(f"{file_name}\t规范\tP0={levels['P0']} P1={levels['P1']} P2={levels['P2']}"
                    + (f"（另有 {len(doc.get('shrink_cost') or [])} 条收缩已知代价）" if doc.get("shrink_cost") else ""))
    elif kind == "violation":
        expects = list(doc.get("expect") or [])
        for ex in expects:
            hit = [i for i in issues if i.get("id") == ex.get("id") and i.get("level") == ex.get("level")
                   and (ex.get("line") is None or i.get("line") == ex.get("line"))]
            mark = ex.get("mark", "")
            where = f"第{ex['line']}行" if ex.get("line") is not None else "任意行"
            rows.append(f"{file_name}\t{mark}\t{ex.get('id')} {ex.get('level')} {where}\t{'检出' if hit else '漏检'}")
            if not hit:
                fails.append(f"{file_name}：{mark} 应检出 {ex.get('id')} {ex.get('level')}（{where}）")
        allowed = {str(e.get("id")) for e in expects if e.get("level") == "P0"} | set(doc.get("allow_extra_p0") or [])
        extra = sorted({str(i.get("id")) for i in issues if i.get("level") == "P0" and str(i.get("id")) not in allowed})
        if extra:
            fails.append(f"{file_name}：出现 expect 之外的 P0：{'、'.join(extra)}")
        if not expects:
            fails.append(f"{file_name}：违规文书没有写 expect")
    else:
        fails.append(f"{file_name}：kind 只能是 clean 或 violation，实为 {kind!r}")
    for name in doc.get("names") or []:
        if name in json_text:
            fails.append(f"{file_name}：姓名“{name}”出现在 JSON 输出里")
        if name in plain_text:
            fails.append(f"{file_name}：姓名“{name}”出现在文本输出里")
    for name in doc.get("leak_known") or []:
        if name in (doc.get("names") or []):
            fails.append(f"{file_name}：“{name}”同时在 names 和 leak_known 里")
    _leaked, stale = leak_report(doc, json_text, plain_text)
    for name in stale:
        fails.append(f"{file_name}：leak_known 里的“{name}”已不再出现在输出里，请从 leak_known 移除")
    return fails, rows


# ---------------------------------------------------------------- 埋点对账与检出率

def load_marks(engine: str) -> List[Dict[str, Any]]:
    path = CORPUS / engine / "marks.json"
    if not path.is_file():
        raise AssertionError(f"[{engine}] 缺少 marks.json（埋点清单）")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("engine") != engine:
        raise AssertionError(f"{path} 的 engine 应为 {engine}")
    return list(data.get("marks") or [])


def check_marks(engine: str, docs: Sequence[Dict[str, Any]], marks: Sequence[Dict[str, Any]]) -> List[str]:
    """纯函数：埋点清单与 cases.json 对账，返回失败说明。"""
    fails: List[str] = []
    seen: set = set()
    by_file: Dict[str, set] = defaultdict(set)
    for mk in marks:
        code, file_name = str(mk.get("mark")), str(mk.get("file"))
        if code in seen:
            fails.append(f"[{engine}] marks.json 编号重复：{code}")
        seen.add(code)
        by_file[file_name].add(code)
        if mk.get("source") not in SOURCES:
            fails.append(f"[{engine}] 埋点 {code} 的 source 只能是 {'、'.join(SOURCES)}，实为 {mk.get('source')!r}")
        if not isinstance(mk.get("line"), int):
            fails.append(f"[{engine}] 埋点 {code} 缺行号")
        if not mk.get("desc") or not mk.get("rules"):
            fails.append(f"[{engine}] 埋点 {code} 缺 desc 或 rules")
        if not (CORPUS / engine / file_name).is_file():
            fails.append(f"[{engine}] 埋点 {code} 指向不存在的文件 {file_name}")
    covered: Dict[str, set] = defaultdict(set)
    viol_files = set()
    for doc in docs:
        if doc.get("kind") != "violation":
            continue
        file_name = doc["file"]
        viol_files.add(file_name)
        exp = {str(e.get("mark")) for e in doc.get("expect") or []}
        mis = {str(e.get("mark")) for e in doc.get("known_miss") or []}
        allowed = by_file.get(file_name, set())
        for code in sorted((exp | mis) - allowed):
            fails.append(f"{file_name}：编号 {code} 不在 marks.json 的该文书埋点里")
        for code in sorted(exp & mis):
            fails.append(f"{file_name}：编号 {code} 在同一次运行里既在 expect 又在 known_miss")
        for e in doc.get("known_miss") or []:
            if not str(e.get("reason") or "").strip():
                fails.append(f"{file_name}：known_miss {e.get('mark')} 没写原因")
        covered[file_name] |= exp | mis
    for file_name, codes in by_file.items():
        if file_name not in viol_files:
            fails.append(f"[{engine}] marks.json 里的文件 {file_name} 不是 cases.json 里的违规文书")
            continue
        for code in sorted(codes - covered[file_name]):
            fails.append(f"{file_name}：埋点 {code} 既没进 expect 也没进 known_miss")
    for file_name in sorted(viol_files):
        if file_name not in by_file:
            fails.append(f"{file_name}：违规文书在 marks.json 里没有任何埋点")
    return fails


def summarize_marks(docs: Sequence[Dict[str, Any]], marks: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """纯函数：按埋点编号去重统计。任一运行的 expect 里有它即检出；只在 known_miss 里的是已知漏检。
    派生埋点（derived_of）不计入分母。降级：检出的最高级别比标注的最高级别低。"""
    expect_levels: Dict[str, List[str]] = defaultdict(list)
    viol_docs: set = set()
    for doc in docs:
        if doc.get("kind") != "violation":
            continue
        viol_docs.add(doc["file"])
        for e in doc.get("expect") or []:
            expect_levels[str(e.get("mark"))].append(str(e.get("level")))
    stats: Dict[str, Dict[str, Any]] = {
        s: {"total": 0, "hit": 0, "miss": 0, "down": 0, "marks_miss": [], "marks_down": []} for s in SOURCES}
    derived: List[str] = []
    for mk in marks:
        code = str(mk["mark"])
        if mk.get("derived_of"):
            derived.append(code)
            continue
        st = stats[mk["source"]]
        st["total"] += 1
        if code in expect_levels:
            st["hit"] += 1
            marked = min(SEVERITY.get(str(r.get("level")), 9) for r in mk["rules"])
            got = min(SEVERITY.get(lv, 9) for lv in expect_levels[code])
            if got > marked:
                st["down"] += 1
                st["marks_down"].append(code)
        else:
            st["miss"] += 1
            st["marks_miss"].append(code)
    return {"by_source": stats, "derived": derived, "runs": len(docs),
            "clean_runs": sum(1 for d in docs if d.get("kind") == "clean"),
            "violation_runs": sum(1 for d in docs if d.get("kind") == "violation"),
            "violation_docs": len(viol_docs)}


def format_stats(engine: str, summary: Dict[str, Any]) -> str:
    lines = [f"[{engine}] 埋点检出率（按埋点编号去重；已知漏检留在分母；source 分开报告）"]
    for src in SOURCES:
        st = summary["by_source"][src]
        if not st["total"]:
            continue
        miss = "：" + "、".join(st["marks_miss"]) if st["marks_miss"] else ""
        down = f"；降级检出 {st['down']}（{'、'.join(st['marks_down'])}）" if st["down"] else ""
        lines.append(f"  {src:8s}检出 {st['hit']}/{st['total']}（其中已知漏检 {st['miss']}{miss}{down}）")
    if summary["derived"]:
        lines.append(f"  派生埋点（同句另一规则的实际覆盖，不计入分母）：{'、'.join(summary['derived'])}")
    lines.append(f"  运行次数 {summary['runs']}（规范文书 {summary['clean_runs']} 次，违规文书 {summary['violation_runs']} 次，"
                 f"涉及违规文书 {summary['violation_docs']} 篇）")
    return "\n".join(lines)


def run_corpus(engine: str) -> None:
    case_file = CORPUS / engine / "cases.json"
    if not case_file.is_file():
        raise unittest.SkipTest(f"{engine}：没有 cases.json，跳过")
    data = json.loads(case_file.read_text(encoding="utf-8-sig"))
    if data.get("engine") != engine:
        raise AssertionError(f"{case_file} 的 engine 应为 {engine}")
    mod = load_engine(engine)
    docs = data.get("docs") or []
    marks = load_marks(engine)
    all_fails: List[str] = list(check_marks(engine, docs, marks))
    table: List[str] = []
    warnings: List[str] = []
    for doc in docs:
        path = CORPUS / engine / doc["file"]
        if not path.is_file():
            all_fails.append(f"{doc['file']}：文件不存在")
            continue
        code_j, out_j, err_j = run_engine(mod, build_argv(engine, path, doc, True))
        code_t, out_t, err_t = run_engine(mod, build_argv(engine, path, doc, False))
        if code_j == 2 or code_t == 2:
            all_fails.append(f"{doc['file']}：引擎退出码 2：{(err_j or err_t or out_j).strip()[:200]}")
            continue
        try:
            issues = json.loads(out_j).get("issues") or []
        except ValueError:
            all_fails.append(f"{doc['file']}：JSON 输出无法解析")
            continue
        fails, rows = evaluate(doc, issues, out_j + err_j, out_t + err_t)
        all_fails.extend(fails)
        table.extend(rows)
        leaked, _stale = leak_report(doc, out_j + err_j, out_t + err_t)
        for name in leaked:
            warnings.append(f"[警告] [{engine}] {doc['file']}：已知泄露（leak_known）“{name}”出现在输出里")
    sys.stderr.write("\n" + format_stats(engine, summarize_marks(docs, marks)) + "\n")
    viol = [r for r in table if r.endswith("检出") or r.endswith("漏检")]
    if viol:
        sys.stderr.write("\n".join(viol) + "\n")
    if warnings:
        sys.stderr.write("\n".join(warnings) + "\n")
    if all_fails:
        raise AssertionError(f"[{engine}] 语料回归失败 {len(all_fails)} 项：\n" + "\n".join(all_fails))


class IndustryCorpusTest(unittest.TestCase):
    def test_hospital(self) -> None:
        run_corpus("hospital")

    def test_soe(self) -> None:
        run_corpus("soe")

    def test_k12(self) -> None:
        run_corpus("k12")


class EvaluateLogicTest(unittest.TestCase):
    """运行器自身的断言逻辑（不依赖语料和引擎）。"""

    @staticmethod
    def issue(rule_id: str, level: str, line: int = 1) -> Dict[str, Any]:
        return {"id": rule_id, "level": level, "line": line, "excerpt": "x"}

    def test_clean_pass_and_fail(self) -> None:
        doc = {"file": "a.txt", "kind": "clean", "max_p1": 1}
        self.assertEqual(evaluate(doc, [self.issue("X-1", "P1")], "", "")[0], [])
        self.assertTrue(evaluate(doc, [self.issue("X-1", "P1"), self.issue("X-2", "P1")], "", "")[0])
        self.assertTrue(evaluate(doc, [self.issue("X-1", "P0")], "", "")[0])
        doc2 = {"file": "a.txt", "kind": "clean", "max_p2": 0}
        self.assertTrue(evaluate(doc2, [self.issue("X-1", "P2")], "", "")[0])

    def test_violation_expect_and_extra_p0(self) -> None:
        doc = {"file": "v.txt", "kind": "violation", "expect": [
            {"mark": "E1", "id": "H-1", "level": "P0", "line": 4}, {"mark": "E2", "id": "H-2", "level": "P1"}]}
        ok = [self.issue("H-1", "P0", 4), self.issue("H-2", "P1", 9)]
        fails, rows = evaluate(doc, ok, "", "")
        self.assertEqual(fails, [])
        self.assertEqual(len(rows), 2)
        self.assertTrue(evaluate(doc, [self.issue("H-1", "P0", 5), self.issue("H-2", "P1")], "", "")[0])  # 行号不符
        self.assertTrue(evaluate(doc, [self.issue("H-1", "P0", 4)], "", "")[0])  # 缺 E2
        self.assertTrue(evaluate(doc, ok + [self.issue("H-3", "P0")], "", "")[0])  # 多出的 P0
        doc["allow_extra_p0"] = ["H-3"]
        self.assertEqual(evaluate(doc, ok + [self.issue("H-3", "P0")], "", "")[0], [])

    def test_names_must_not_leak(self) -> None:
        doc = {"file": "v.txt", "kind": "violation", "names": ["张丽丽"],
               "expect": [{"mark": "E1", "id": "H-1", "level": "P0"}]}
        issues = [self.issue("H-1", "P0")]
        self.assertEqual(evaluate(doc, issues, "{}", "无")[0], [])
        self.assertTrue(evaluate(doc, issues, "张丽丽", "")[0])
        self.assertTrue(evaluate(doc, issues, "", "患者张丽丽")[0])

    def test_leak_known_warns_and_stale_fails(self) -> None:
        doc = {"file": "v.txt", "kind": "violation", "leak_known": ["张丽丽"],
               "expect": [{"mark": "E1", "id": "H-1", "level": "P0"}]}
        issues = [self.issue("H-1", "P0")]
        self.assertEqual(evaluate(doc, issues, "患者张丽丽", "")[0], [])  # 已登记的泄露：不判失败，运行器打印警告
        self.assertEqual(leak_report(doc, "患者张丽丽", ""), (["张丽丽"], []))
        self.assertTrue(evaluate(doc, issues, "{}", "无")[0])  # 已不再泄露：要求清理登记
        doc2 = dict(doc, names=["张丽丽"])
        self.assertTrue(evaluate(doc2, issues, "患者张丽丽", "")[0])  # names 优先，不能靠 leak_known 放过

    def test_bad_kind_and_missing_expect(self) -> None:
        self.assertTrue(evaluate({"file": "a", "kind": "?"}, [], "", "")[0])
        self.assertTrue(evaluate({"file": "a", "kind": "violation"}, [], "", "")[0])

    def test_build_argv(self) -> None:
        p = Path("x.txt")
        self.assertEqual(build_argv("hospital", p, {"type": "RCA", "external": True}, True),
                         ["x.txt", "--type=RCA", "--external", "--json"])
        self.assertEqual(build_argv("k12", p, {"mode": "parents"}, True), ["parents", "x.txt", "--json"])
        self.assertEqual(build_argv("k12", p, {}, False), ["general", "x.txt"])
        self.assertEqual(build_argv("soe", p, {"args": ["--as-of", "2026-01-01"]}, False),
                         ["x.txt", "--as-of", "2026-01-01"])

    def test_run_engine_captures_output_and_exit(self) -> None:
        class Fake:
            @staticmethod
            def main(argv: Optional[Sequence[str]] = None) -> int:
                print("你好", list(argv or []))
                return 1

        code, out, _err = run_engine(Fake, ["a"])
        self.assertEqual(code, 1)
        self.assertIn("你好", out)


class MarksLogicTest(unittest.TestCase):
    """埋点对账与检出率统计的纯函数测试（用合成数据，不依赖引擎）。"""

    FILE = "V_h01_议题_购置设备.txt"  # 对账会检查文件是否存在，借用真实文件名

    @staticmethod
    def mark(code: str, source: str = "author", level: str = "P0", **kw: Any) -> Dict[str, Any]:
        d = {"mark": code, "file": MarksLogicTest.FILE, "line": 1, "desc": "x",
             "rules": [{"id": "H-1", "level": level}], "source": source}
        d.update(kw)
        return d

    def doc(self, expect: Sequence[str], miss: Sequence[str] = (), level: str = "P0") -> Dict[str, Any]:
        return {"file": self.FILE, "kind": "violation",
                "expect": [{"mark": m, "id": "H-1", "level": level} for m in expect],
                "known_miss": [{"mark": m, "id": "H-1", "level": "P0", "reason": "因为"} for m in miss]}

    def test_subset_and_cover(self) -> None:
        marks = [self.mark("A1"), self.mark("A2")]
        self.assertEqual(check_marks("hospital", [self.doc(["A1"], ["A2"])], marks), [])
        self.assertTrue(check_marks("hospital", [self.doc(["A1", "Z9"], ["A2"])], marks))  # 不在 marks 里
        self.assertTrue(check_marks("hospital", [self.doc(["A1"])], marks))  # A2 没覆盖
        self.assertTrue(check_marks("hospital", [self.doc(["A1", "A2"], ["A2"])], marks))  # 同一次运行两边都在
        bad = self.doc(["A1"], ["A2"])
        bad["known_miss"][0]["reason"] = " "
        self.assertTrue(check_marks("hospital", [bad], marks))  # known_miss 没写原因
        self.assertTrue(check_marks("hospital", [self.doc(["A1"], ["A2"])],
                                    [self.mark("A1", source="x"), self.mark("A2")]))  # source 非法

    def test_union_across_runs(self) -> None:
        marks = [self.mark("A1"), self.mark("A2")]
        docs = [self.doc(["A1"]), self.doc(["A2"])]  # 两次运行各覆盖一个：并集覆盖全部
        self.assertEqual(check_marks("hospital", docs, marks), [])

    def test_dedup_by_mark_and_keep_miss_in_denominator(self) -> None:
        marks = [self.mark("A1"), self.mark("A2"), self.mark("R1", source="review"), self.mark("D1", derived_of="A2")]
        docs = [self.doc(["A1"], ["A2"]), self.doc(["A1", "A2"])]  # A1 两次都检出只算一次；A2 一次漏检一次检出：算检出
        st = summarize_marks(docs, marks)
        self.assertEqual((st["by_source"]["author"]["hit"], st["by_source"]["author"]["total"]), (2, 2))
        self.assertEqual(st["runs"], 2)
        self.assertEqual(st["derived"], ["D1"])
        st2 = summarize_marks([self.doc(["A1"], ["A2"])], marks[:2])
        self.assertEqual((st2["by_source"]["author"]["hit"], st2["by_source"]["author"]["total"],
                          st2["by_source"]["author"]["miss"]), (1, 2, 1))
        self.assertIn("检出 1/2（其中已知漏检 1：A2", format_stats("hospital", st2))

    def test_downgrade_counted(self) -> None:
        marks = [self.mark("A1", level="P0")]
        self.assertEqual(summarize_marks([self.doc(["A1"], level="P1")], marks)["by_source"]["author"]["down"], 1)
        self.assertEqual(summarize_marks([self.doc(["A1"], level="P0")], marks)["by_source"]["author"]["down"], 0)

    def test_sources_reported_separately(self) -> None:
        marks = [self.mark("A1"), self.mark("R1", source="review"), self.mark("H1", source="heldout")]
        st = summarize_marks([self.doc(["A1", "R1"], ["H1"])], marks)
        self.assertEqual([st["by_source"][s]["hit"] for s in SOURCES], [1, 1, 0])
        self.assertEqual([st["by_source"][s]["total"] for s in SOURCES], [1, 1, 1])


if __name__ == "__main__":
    unittest.main()
