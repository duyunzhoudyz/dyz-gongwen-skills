"""分句图结构契约，回归断言只涉及分句、语境、极性与角色。"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from xinchuang import local_toolbox


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "gongwen-k12" / "scripts"
SAMPLES = Path(__file__).parent / "samples"
REGRESSION = SAMPLES / "clause_regression"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CHECK = load("_test_k12_clause_check", SCRIPTS / "k12_check.py")
CLAUSE = CHECK.load_clause_module()
C, P = CLAUSE.Context, CLAUSE.Polarity


def regression_cases():
    for name in ("probes", "supplemental_text", "output_probes"):
        for line in (REGRESSION / f"{name}.jsonl").read_text(encoding="utf-8").splitlines():
            yield json.loads(line)


class ClauseTest(unittest.TestCase):
    def test_numbering_quotes_list_close_and_word_paragraphs(self):
        text = ('严禁以下行为：\r\n1）教师推荐学生参加校外有偿补课。\r\n'
                '一）班主任把学生电话发给校外培训机构。\r\n'
                '学校统一购买校服。\r\n'
                '记录"残缺引语，学校统一收取资料费。\r\n'
                '学校公布"第1组,第2组"，另学校统一购买校服。')
        graph = CLAUSE.analyze(text, paragraph_starts=(1, 2, 3, 4, 5, 6))
        a, b, c, prose, malformed, amount, quote, last = graph.clauses
        self.assertEqual((b.span.line, b.span.column, c.span.line, c.span.column), (2, 3, 3, 3))
        self.assertFalse(b.malformed or c.malformed)
        self.assertEqual(b.list_block, c.list_block)
        self.assertIsNone(prose.list_block)
        self.assertEqual(prose.context, C.ASSERTION)
        self.assertEqual((b.context, c.context), (C.NEGATION, C.NEGATION))
        outer = next(f for f in graph.frames if f.source == a.id and f.kind == "colon")
        self.assertEqual(outer.clauses, [b.id, c.id])
        self.assertEqual(outer.scope.end, c.span.end)
        self.assertTrue(malformed.malformed)
        self.assertEqual(amount.text, "学校统一收取资料费")
        self.assertEqual(len(quote.groups), 1)
        group = quote.groups[0]
        self.assertEqual(text[group.content.start:group.content.end], "第1组,第2组")
        self.assertEqual(last.connector, "另")
        for clause in graph.clauses:
            self.assertEqual(text[clause.span.start:clause.span.end], clause.text)

    def test_brackets_titles_numbers_and_offsets(self):
        text = "  学校在08:30收取资料费1,200元（以任何名义，按标准）；学校不得（以任何名义）统一收取班费。"
        graph = CLAUSE.analyze(text)
        left, right = graph.clauses
        self.assertEqual(left.span.column, 3)
        self.assertEqual(left.following, right.id)
        self.assertEqual(right.previous, left.id)
        self.assertEqual(left.sentence, right.sentence)
        self.assertEqual(left.separator, "；")
        self.assertEqual(graph.polarity(right.id, "收取"), P.NEGATIVE)
        self.assertEqual(left.groups[0].kind, "bracket")
        self.assertEqual(CLAUSE.analyze("《关于收费的通知》").actions, [])
        self.assertEqual(CLAUSE.analyze("学校收取资料费（班主任统一购买校服）。").clauses[1].parent, 0)

    def test_multiline_brackets_and_simple_coordinates(self):
        text = "学校不得（以任何名义，\r\n按标准）统一收取资料费。\r\n"
        graph = CLAUSE.analyze(text)
        clause, = graph.clauses
        self.assertEqual((clause.span.line, clause.span.end_line), (1, 2))
        self.assertEqual(text[clause.span.start:clause.span.end], clause.text)
        group, = clause.groups
        self.assertEqual(text[group.content.start:group.content.end], "以任何名义，\r\n按标准")
        self.assertEqual(graph.polarity(clause.id, "收取"), P.NEGATIVE)
        self.assertTrue(CLAUSE.analyze(text, paragraph_starts=(1, 2)).clauses[0].malformed)

        legacy = load("_test_k12_clause_shared_shape", ROOT / "shared" / "scripts" / "gw_clause.py")
        ordinary = "学校公布名单，家长确认。各班统一归档！"
        result = CLAUSE.analyze(ordinary)
        self.assertEqual([(c.span.start, c.span.end, c.separator) for c in result.clauses],
                         list(legacy.split_clauses(ordinary)))

    def test_known_notice_first_item_unknown_heading_and_condition(self):
        positive = CLAUSE.analyze("收费通知：学校统一收取资料费，学校统一购买校服。")
        top, first, second = positive.clauses
        self.assertEqual(top.context, C.NOTICE)
        self.assertEqual(first.admission, CLAUSE.Admission.NOTICE)
        self.assertIsNone(second.admission)
        unknown = CLAUSE.analyze("经验分享：学校统一收取资料费。")
        self.assertEqual(unknown.clauses[1].context, C.UNKNOWN)
        self.assertEqual(unknown.polarity(1, "收取"), P.UNKNOWN)
        hypothetical = CLAUSE.analyze("如果发生如下情形：教师向校外培训机构提供家长电话。")
        self.assertEqual(hypothetical.clauses[1].context, C.CONDITION)
        self.assertEqual(hypothetical.polarity(1, "提供"), P.UNKNOWN)
        self.assertEqual(hypothetical.actions[-1].local_polarity, P.POSITIVE)

    def test_attributive_refusal_and_controlled_roles(self):
        graph = CLAUSE.analyze("未缴纳校服费的学生不得报名。")
        refusal, result = graph.actions
        self.assertTrue(refusal.attributive and refusal.refusal)
        self.assertEqual((refusal.object, refusal.polarity), ("校服费", P.NEGATIVE))
        self.assertEqual(result.conditions, (refusal.id,))
        self.assertEqual(result.polarity, P.NEGATIVE)
        self.assertTrue(result.consequence)

        graph = CLAUSE.analyze("成绩不理想的学生一律由班主任组织参加校外收费补习。")
        organize, attend = graph.actions
        self.assertEqual((attend.agent, attend.object, attend.polarity), ("班主任", "校外收费补习", P.POSITIVE))
        self.assertEqual(organize.object, "学生")
        self.assertTrue(organize.school_agent)
        self.assertEqual(attend.parent, organize.id)

        graph = CLAUSE.analyze("学校不断要求班主任把学生电话发给校外辅导机构。")
        require, send = graph.actions
        self.assertEqual((require.agent, require.object), ("学校", "班主任"))
        self.assertEqual((send.agent, send.object, send.recipient), ("班主任", "学生电话", "校外辅导机构"))
        self.assertEqual(send.parent, require.id)

        graph = CLAUSE.analyze("不得要求未报名的学生必须缴纳课后服务费。")
        self.assertEqual(graph.polarity(0, "缴纳"), P.NEGATIVE)
        self.assertEqual(graph.actions[-1].agent, "学生")

    def test_negation_scope_parallel_and_unknown_insertion(self):
        direct = CLAUSE.analyze("学校严禁对已交费的家长再次统一收取材料费。")
        self.assertEqual(direct.polarity(0, "收取"), P.NEGATIVE)
        extended = CLAUSE.analyze("学校严禁教师组织学生参加校外有偿补课并向校外培训机构提供学生信息。")
        self.assertEqual(extended.polarity(0, "组织"), P.NEGATIVE)
        self.assertEqual(extended.polarity(1, "提供"), P.NEGATIVE)
        local = CLAUSE.analyze("学校不统一订购教辅资料并要求全体学生购买校服。")
        self.assertEqual(local.polarity(0, "订购"), P.NEGATIVE)
        self.assertEqual(local.polarity(1, "购买"), P.POSITIVE)
        self.assertEqual(local.clauses[1].admission, CLAUSE.Admission.PARALLEL)
        self.assertEqual(local.actions[-1].admission, CLAUSE.Admission.PARALLEL)
        self.assertEqual(CLAUSE.analyze("学校未神秘地统一购买校服。").polarity(0, "购买"), P.UNKNOWN)
        earlier = CLAUSE.analyze("学校取消减免后统一收取校服费。")
        self.assertEqual(earlier.actions[-1].polarity, P.POSITIVE)
        self.assertIsNone(earlier.actions[-1].admission)

    def test_double_negation_correction_and_questions(self):
        for text, status in [
            ("学校绝非不公布考试成绩。", P.POSITIVE),
            ("不公布成绩怎么行呢？", P.POSITIVE),
            ("不公布成绩是绝对不可能的啊！", P.POSITIVE),
            ("难道可以公布成绩吗？", P.UNKNOWN),
        ]:
            with self.subTest(text=text):
                self.assertEqual(CLAUSE.analyze(text).polarity(0, "公布"), status)
        correction = CLAUSE.analyze("学校不是不公布成绩，而是本周五公布。")
        self.assertEqual(correction.polarity(0, "公布"), P.UNKNOWN)
        self.assertEqual(correction.polarity(1, "公布"), P.POSITIVE)
        self.assertEqual(correction.actions[-1].object, "")
        self.assertIsNone(correction.clauses[1].admission)

    def test_tail_execution_detail_vs_back_reference(self):
        for tail in ("周五前缴费", "交给班主任", "由班主任统一收款", "合计180元"):
            graph = CLAUSE.analyze("学校统一购买校服，" + tail + "。")
            self.assertEqual(graph.clauses[1].tail, CLAUSE.Tail.DETAIL, tail)
            self.assertEqual(graph.polarity(0, "购买"), P.POSITIVE, tail)
            self.assertEqual(graph.clauses[0].admission, CLAUSE.Admission.MAIN, tail)
        for tail in ("此方案周五再讨论", "该做法由班主任研究", "传闻周五前缴费", "未说明性质的附加段"):
            graph = CLAUSE.analyze("学校统一购买校服，" + tail + "。")
            self.assertEqual(graph.clauses[1].tail, CLAUSE.Tail.EVALUATION, tail)
            self.assertEqual(graph.polarity(0, "购买"), P.UNKNOWN, tail)
            self.assertIsNone(graph.clauses[0].admission, tail)

    def test_three_back_bindings_and_competition(self):
        for tail, binding, status in [
            ("一律禁止", CLAUSE.Binding.PROHIBITED, P.NEGATIVE),
            ("经核实并不属实", CLAUSE.Binding.REFUTED, P.NEGATIVE),
            ("已启动问责", CLAUSE.Binding.ACCOUNTABILITY, P.POSITIVE),
            ("是否属于违规收费", CLAUSE.Binding.QUESTION, P.UNKNOWN),
            ("此方案已被否决", CLAUSE.Binding.REJECTED, P.NEGATIVE),
            ("这是往年被督导叫停的错误做法", CLAUSE.Binding.HISTORICAL, P.NEGATIVE),
            ("此做法已被叫停", CLAUSE.Binding.HALTED, P.UNKNOWN),
        ]:
            graph = CLAUSE.analyze("学校统一购买校服，" + tail + "。")
            self.assertEqual((graph.actions[0].binding, graph.actions[0].polarity), (binding, status), tail)
            self.assertIsNone(graph.clauses[0].admission, tail)
        graph = CLAUSE.analyze("学校统一购买校服，学校统一收取资料费，此方案已被否决。")
        self.assertEqual([a.binding for a in graph.actions[:2]], [CLAUSE.Binding.UNRESOLVED] * 2)
        quote = CLAUSE.analyze("针对“班主任把学生电话发给校外培训机构”的匿名举报，经核查查无实据。")
        self.assertEqual(quote.actions[0].binding, CLAUSE.Binding.REFUTED)
        listed = CLAUSE.analyze("1）学校统一购买校服。\n2）一律禁止。\n学校统一收取资料费。")
        self.assertEqual(listed.actions[0].binding, CLAUSE.Binding.PROHIBITED)
        self.assertIsNone(listed.actions[-1].binding)
        stopped = CLAUSE.analyze("学校已统一购买校服，这种做法已被叫停。")
        self.assertEqual(stopped.actions[0].binding, CLAUSE.Binding.ACCOUNTABILITY)

    def test_markdown_table_project_and_exit_boundaries(self):
        text = ("| 项目 | 要求 | 项目 | 要求 |\n| --- | --- | --- | --- |\n"
                "| 校服 | 统一购买 | 课后服务 | 自愿参加，不参加不收费 |\n"
                "| 资料费 | 学校统一收取 | 校服 | 家长签收\\|可查 |")
        graph = CLAUSE.analyze(text)
        first, second = graph.actions[:2]
        self.assertEqual([first.predicate, second.predicate], ["购买", "参加"])
        self.assertNotEqual(first.project, second.project)
        self.assertFalse(first.exit)
        self.assertTrue(second.exit)
        self.assertTrue(second.voluntary)
        a, b = (graph.clauses[i] for i in (first.clause, second.clause))
        self.assertEqual((a.row, b.row, a.column, b.column), (2, 2, 2, 4))
        self.assertEqual(a.frames, b.frames)
        self.assertEqual((a.column_header, b.column_header), ("要求", "要求"))
        self.assertEqual(graph.frames[a.frames[0]].kind, "table_header")
        self.assertEqual(graph.clauses[-1].text, "家长签收\\|可查")
        self.assertNotIn(graph.actions[-1].project, {first.project, second.project})

    def test_cli_path_loader_and_toolbox_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            source = temp / "sample.txt"
            source.write_text("学校统一购买校服。", encoding="utf-8")
            run = subprocess.run([sys.executable, "-I", str(SCRIPTS / "k12_clause.py"), str(source)],
                                 capture_output=True, check=True, text=True)
            self.assertEqual(json.loads(run.stdout)["actions"][0]["predicate"], "购买")

            sys_path = sys.path[:]
            self.assertIs(CHECK.load_clause_module(), CLAUSE)
            key = "test_k12_clause_path"
            try:
                toolbox = local_toolbox._load_industry_module(key, SCRIPTS / "k12_check.py")
                self.assertIs(toolbox.load_clause_module(), CLAUSE)
                self.assertIn(CLAUSE.__name__, sys.modules)
            finally:
                local_toolbox._INDUSTRY_MOD_CACHE.pop(key, None)
                sys.modules.pop("_gw_ind_test_k12_clause_path_k12_check", None)
            self.assertEqual(sys.path, sys_path)

            isolated = temp / "gongwen-k12" / "scripts"
            shutil.copytree(SCRIPTS, isolated, ignore=shutil.ignore_patterns("__pycache__"))
            second = load("_test_k12_clause_isolated", isolated / "k12_check.py")
            copy = second.load_clause_module()
            try:
                self.assertIsNot(copy, CLAUSE)
                self.assertEqual(copy.analyze(source.read_text(encoding="utf-8")).actions[0].polarity, P.POSITIVE)
            finally:
                sys.modules.pop(copy.__name__, None)
                sys.modules.pop(second.__name__, None)

    def test_regression_structure(self):
        cases = {case["id"]: case for case in regression_cases()}
        checked = set()
        categories = set()
        for line in (SAMPLES / "clause_structure.tsv").read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            case_id, predicate, context, polarity, school = line.split("\t")
            with self.subTest(id=case_id, predicate=predicate):
                case = cases[case_id]
                checked.add(case_id)
                categories.add(case["category"])
                graph = CLAUSE.analyze(case["text"])
                if predicate == "-":
                    self.assertFalse(graph.actions)
                    self.assertTrue(graph.clauses)
                    self.assertTrue(all(clause.context == context for clause in graph.clauses))
                else:
                    hit = [(a.context, a.polarity, a.school_agent) for a in graph.actions if a.predicate == predicate]
                    self.assertIn((context, polarity, school == "1"), hit, (case["text"], hit))
        self.assertGreaterEqual(len(checked), 150)
        self.assertEqual(categories, {case["category"] for case in cases.values()})


if __name__ == "__main__":
    unittest.main()
