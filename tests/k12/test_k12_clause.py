"""分句图结构契约，回归断言只涉及分句、语境、极性与角色。"""
from __future__ import annotations

from collections import defaultdict
import importlib.util
import json
import re
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


P0_RULES = {
    "JZ-006": "fee", "K12-G05": "fee",
    "JZ-008": "tutoring", "K12-G09": "tutoring",
    "JZ-003": "parents_rank", "K12-G01": "general_rank", "K12-G04": "identity",
}
FEE_ACTIONS = {"收取", "代收", "收缴", "缴纳", "交纳", "上交", "交齐", "缴齐",
               "购买", "订购", "征订", "订阅", "办理", "收费", "缴费", "交费", "付款", "缴", "买", "收", "订"}
TUTOR_ACTIONS = {"组织", "推荐", "安排", "动员", "要求", "介绍", "联系", "强迫", "强制", "让"}
TRANSFER_ACTIONS = {"提供", "提供给", "发给", "发送", "发送给", "透露", "泄露", "转交", "移交", "推荐", "输送"}
RANK_ACTIONS = {"公布", "张贴", "通报", "公示", "发布", "晒", "排名", "发到", "发成绩", "上传到", "分班", "排座"}
IDENTITY_ACTIONS = {"属于", "系", "是", "认定为", "登记为", "确诊为", "患有",
                    "享受助学金", "受处分", "被处分", "被记过", "受到处分"}


def _ancestors(graph, action):
    while action.parent is not None:
        action = graph.actions[action.parent]
        yield action


def p0_shapes(graph, family):
    """首版结构门禁对照。证据只来自当前动作及其控制链。"""
    by_root = defaultdict(list)
    for action in graph.actions:
        if action.admission and action.polarity == P.POSITIVE and not action.binding:
            chain = (action, *_ancestors(graph, action))
            by_root[chain[-1].id].append(action)
    for chain in by_root.values():
        school = any(a.school_agent for a in chain)
        for action in chain:
            verb = action.predicate
            if family == "fee":
                forced = any(a.mandatory or a.predicate == "要求" for a in (action, *_ancestors(graph, action)))
                uniform = any(a.uniform for a in (action, *_ancestors(graph, action)))
                if (verb in FEE_ACTIONS and (school or action.fixed_notice) and action.object
                        and action.project is not None and "报刊" not in graph.projects[action.project].label
                        and (forced or uniform and not action.voluntary)):
                    yield action
            elif family == "tutoring" and school:
                if (verb in TRANSFER_ACTIONS and re.fullmatch(r"校外(?:培训机构|辅导机构|补习班)", action.recipient)
                        and re.fullmatch(r"生源|(?:学生和家长|学生|家长)(?:的)?(?:电话(?:号码)?|微信号|学籍号|学号|名单|通讯录|联系方式|信息)", action.object)):
                    yield action
                elif verb in TUTOR_ACTIONS:
                    controlled = [a for a in chain if a is action or action in _ancestors(graph, a)]
                    roles = " ".join(a.agent + " " + a.object + " " + a.recipient for a in controlled)
                    if (re.search(r"学生|同学|新生", roles)
                            and any(re.search(r"校外.*(?:有偿|付费|收费).*(?:补课|补习|辅导|培训)", a.object)
                                    for a in controlled)):
                        yield action
            elif family in {"parents_rank", "general_rank"} and verb in RANK_ACTIONS:
                if verb in {"排名", "分班", "排座"}:
                    head = graph.text[action.extent.start:action.span.start]
                    if re.search(r"按(?:考试)?成绩", head) or family == "parents_rank" and action.negation:
                        yield action
                elif re.search(r"成绩|分数|排名|名次", action.object) and (
                    family == "parents_rank" or verb in {"公布", "张贴", "通报", "公示"}
                ):
                    yield action
            elif family == "identity" and verb in IDENTITY_ACTIONS and action.agent:
                # 沿用本步报告的现行姓名置信门槛。身份前缀与新锚点由 3b 接入。
                matches, _ = CHECK._g04_analyze(graph.clauses[action.clause].text)
                if any(m["score"] >= 6 for m in matches):
                    yield action


def _probe_samples():
    return json.loads((SAMPLES / "clause_review_r1.json").read_text(encoding="utf8"))


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
        self.assertEqual(last.text, "另学校统一购买校服")
        self.assertIsNone(last.admission)
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
        named = CLAUSE.analyze("关于课后服务收费的通知：学校必须收取课后服务费。")
        self.assertEqual(named.clauses[0].context, C.NOTICE)
        self.assertEqual(named.actions[0].admission, CLAUSE.Admission.NOTICE)
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
        self.assertEqual(earlier.actions[-1].local_polarity, P.POSITIVE)
        self.assertEqual(earlier.actions[-1].polarity, P.UNKNOWN)
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
        inline = CLAUSE.analyze("学校统一购买校服费用180元交给班主任。").actions[0]
        self.assertEqual((inline.object, inline.admission), ("校服", CLAUSE.Admission.MAIN))
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

    def test_all_regression_p0_upper_bounds(self):
        checked = widening = 0
        for case in regression_cases():
            graph = CLAUSE.analyze(case["text"])
            if case.get("candidate_for_widening"):
                widening += 1
                self.assertFalse(any(a.admission for a in graph.actions), case["id"])
            shapes = {family: tuple(p0_shapes(graph, family)) for family in set(P0_RULES.values())}
            for stage, data in case["by_stage"].items():
                for entry, expected in data.get("expected", {}).items():
                    new_layer = data.get("expected_new_layer", {}).get(entry, {})
                    for rule, levels in expected.items():
                        family = P0_RULES.get(rule)
                        if family is None or "P0" in new_layer.get(rule, {}).get("allowed", levels):
                            continue
                        checked += 1
                        if stage == "义务教育" or family in {"tutoring", "identity"}:
                            self.assertFalse(shapes[family], (case["id"], stage, entry, rule, case["text"]))
        self.assertGreater(checked, 2000)
        self.assertEqual(widening, 16)

    def test_every_admitted_regression_sentence_consumes_all_mutations(self):
        sample = _probe_samples()
        residuals = [text for key in ("B1", "B2", "B5", "原创") for text in sample["残余"][key]]
        self.assertGreaterEqual(len(sample["残余"]["原创"]), 30)
        admitted = set()
        for case in regression_cases():
            graph = CLAUSE.analyze(case["text"])
            sentences = defaultdict(list)
            for clause in graph.clauses:
                if clause.parent is None:
                    sentences[clause.sentence].append(clause)
            for clauses in sentences.values():
                if any(c.admission for c in clauses):
                    admitted.add(graph.text[clauses[0].span.start:clauses[-1].span.end])
        self.assertGreaterEqual(len(admitted), 30)
        for text in sorted(admitted):
            for residual in residuals:
                for changed in (text+residual, text+"，"+residual, residual+"，"+text, residual+text):
                    graph = CLAUSE.analyze(changed+"。")
                    self.assertFalse(any(a.admission for a in graph.actions), changed)
            for detail in sample["执行细化"]:
                graph = CLAUSE.analyze(text+"，"+detail+"。")
                self.assertTrue(any(a.admission for a in graph.actions), (text, detail))
                self.assertEqual(graph.clauses[-1].tail, CLAUSE.Tail.DETAIL)

    def test_review_blockers_end_to_end(self):
        probes = _probe_samples()["复现实测"]
        for blocker, text, options in probes:
            with self.subTest(blocker=blocker, text=text):
                graph = CLAUSE.analyze(text, **options)
                self.assertFalse(any(action.admission for action in graph.actions))
        self.assertEqual(len(probes), 26)  # 报告写 24，评审脚本实含 26。

    def test_review_list_hierarchy_and_word_colon_scope(self):
        for parent, children, next_item in [
            ("（一）", ("1）", "2）"), "（二）"),
            ("1. ", ("（1）", "（2）"), "2. "),
            ("（1）", ("①", "②"), "（2）"),
        ]:
            text = (parent+"严禁以下行为：\n"+children[0]+"学校统一购买校服。\n"
                    +children[1]+"班主任组织学生参加校外有偿补课。\n"+next_item+"学校统一购买校服。")
            split = CLAUSE.split_clauses(text)
            colon = next(f for f in split.frames if f.kind == "colon")
            self.assertEqual(colon.clauses, [1, 2])
            graph = CLAUSE.analyze(text)
            self.assertEqual([c.context for c in graph.clauses], [C.NEGATION] * 3 + [C.ASSERTION])
        text = "反面案例如下：\n学校统一购买校服。教师向校外培训机构透露学生电话。\n学校统一购买校服。"
        graph = CLAUSE.analyze(text, paragraph_starts=(1, 2, 3))
        self.assertEqual([c.context for c in graph.clauses], [C.UNKNOWN] * 3 + [C.ASSERTION])
        self.assertEqual([a.admission for a in graph.actions], [None, None, CLAUSE.Admission.MAIN])

    def test_review_scopes_lexical_boundaries_and_refusal(self):
        for source, obj in [
            ("拒不缴纳班费者", "班费"),
            ("所有未缴纳校服费的学生", "校服费"),
            ("未缴纳校服费和资料费的学生", "校服费和资料费"),
        ]:
            graph = CLAUSE.analyze(source+"不得报名。")
            prior, result = graph.actions
            self.assertEqual((prior.polarity, prior.object, prior.refusal), (P.NEGATIVE, obj, True))
            self.assertEqual((result.polarity, result.conditions), (P.NEGATIVE, (prior.id,)))
        graph = CLAUSE.analyze("各班没有不购买校服的。")
        self.assertEqual([(a.polarity, a.refusal) for a in graph.actions], [(P.POSITIVE, False)])
        for stub in ("不同意", "不及时", "绝不", "从未", "坚决反对", "严厉杜绝"):
            graph = CLAUSE.analyze("学校"+stub+"公布考试成绩。")
            self.assertEqual(graph.polarity(0, "公布"), P.NEGATIVE, stub)
        graph = CLAUSE.analyze("成绩不理想的学生一律交由班主任组织参加校外收费补习。")
        self.assertEqual([(a.predicate, a.agent, a.polarity) for a in graph.actions],
                         [("组织", "班主任", P.POSITIVE), ("参加", "班主任", P.POSITIVE)])
        graph = CLAUSE.analyze("学校不但组织学生参加校外有偿补课，还收取高额补课费。")
        self.assertEqual(graph.clauses[0].text, "学校不但组织学生参加校外有偿补课")
        self.assertEqual(graph.actions[0].agent, "学校")
        self.assertFalse(any(a.polarity == P.POSITIVE for a in CLAUSE.analyze(
            "学校神秘地要求班主任组织学生参加校外有偿补课。").actions))
        for text in ("学校（是否采纳尚待讨论）统一购买校服。", "学校把学生电话统一购买校服。"):
            graph = CLAUSE.analyze(text)
            self.assertEqual(graph.clauses[0].context, C.UNKNOWN, text)
            self.assertIsNone(graph.clauses[0].admission, text)
        for text, predicate in [("学校统一代收费的项目必须列出明细。", "代收"), ("家委会收到材料。", "收")]:
            self.assertNotIn(predicate, {a.predicate for a in CLAUSE.analyze(text).actions})
        self.assertEqual(CLAUSE.analyze("王小明同学系单亲家庭关爱志愿者。").actions[0].object, "单亲家庭关爱志愿者")

    def test_review_groups_unheaded_tables_and_rank_destinations(self):
        graph = CLAUSE.analyze('网传"班主任组织学生参加校外有偿补课。请尽快报名。"，经核实并不属实。')
        self.assertFalse(any(c.malformed for c in graph.clauses))
        self.assertEqual(graph.actions[0].binding, CLAUSE.Binding.REFUTED)
        graph = CLAUSE.analyze("| 校服 | 统一购买校服 | 课后服务 | 自愿参加，不参加不收费 |")
        self.assertEqual([item.label for item in graph.projects], ["校服", "课后服务"])
        self.assertEqual(graph.actions[0].project, graph.clauses[0].project)
        headed = CLAUSE.analyze("| 费用名称 | 要求 | 项目名 | 要求 |\n| --- | --- | --- | --- |\n"
                               "| 校服 | 统一购买校服 | 课后服务 | 自愿参加 |")
        self.assertEqual([item.label for item in headed.projects], ["校服", "课后服务"])
        graph = CLAUSE.analyze("学校严禁组织学生参加校外有偿补课、向校外培训机构提供学生电话。")
        self.assertEqual(graph.polarity(1, "提供"), P.NEGATIVE)
        for text, obj, recipient in [
            ("成绩单不会不发到家长群。", "成绩单", "家长群"),
            ("成绩单不能不上传到班级群。", "成绩单", "班级群"),
            ("教师把学生学籍号提供给校外培训机构。", "学生学籍号", "校外培训机构"),
        ]:
            action = CLAUSE.analyze(text).actions[0]
            self.assertEqual((action.object, action.recipient, action.admission), (obj, recipient, CLAUSE.Admission.MAIN))

    def test_review_voluntary_correction_and_questions(self):
        graph = CLAUSE.analyze("不是不统一购买校服，而是自愿购买，不参加不收费。")
        self.assertEqual(graph.actions[0].binding, CLAUSE.Binding.ALTERNATIVE)
        self.assertTrue(graph.actions[1].voluntary and graph.actions[1].exit)
        self.assertEqual(graph.actions[0].project, graph.actions[1].project)
        for text in ("不公布成绩怎么行呢？", "学校统一购买校服，？", "学校统一购买校服并学校代收资料费？"):
            self.assertFalse(any(a.admission for a in CLAUSE.analyze(text).actions), text)

    def test_regression_structure(self):
        cases = {case["id"]: case for case in regression_cases()}
        structural_details = _probe_samples()["结构断言"]
        checked = set()
        categories = set()
        for line in (SAMPLES / "clause_structure.tsv").read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            case_id, predicate, context, polarity, school = line.split("\t")
            expected = structural_details.get(case_id, {}).get(predicate, {})
            with self.subTest(id=case_id, predicate=predicate):
                case = cases[case_id]
                checked.add(case_id)
                categories.add(case["category"])
                graph = CLAUSE.analyze(case["text"])
                if predicate == "-":
                    self.assertFalse(graph.actions)
                    self.assertEqual([c.text for c in graph.clauses], expected["segments"])
                    self.assertTrue(all(clause.context == context for clause in graph.clauses))
                    self.assertTrue(all(clause.admission is None for clause in graph.clauses))
                else:
                    hits = [a for a in graph.actions if (a.predicate, a.context, a.polarity, a.school_agent) ==
                            (predicate, context, polarity, school == "1")]
                    self.assertTrue(hits, (case["text"], graph.actions))
                    if expected:
                        def fields(action):
                            return {key: ([graph.actions[i].object for i in action.conditions]
                                           if key == "condition_objects" else getattr(action, key))
                                    for key in expected}
                        self.assertIn(expected, [fields(a) for a in hits], case["text"])
        self.assertGreaterEqual(len(checked), 150)
        self.assertEqual(categories, {case["category"] for case in cases.values()})


if __name__ == "__main__":
    unittest.main()
