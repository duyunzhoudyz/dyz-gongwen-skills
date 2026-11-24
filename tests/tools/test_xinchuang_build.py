# -*- coding: utf-8 -*-
'''tools/build_prompts.py 的信创产物（精简版、合集版、知识库切片、离线包 wheelhouse）与 tools/security_audit.py 的单元测试。'''
from __future__ import annotations

import re
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.tools.fixtures import REPO_ROOT

import build_prompts
import security_audit

NL = chr(10)
# 精修版和合集版里不该出现的内容：交接卡、转交、脚本命令、路径引用、skill 名
FORBIDDEN = re.compile(r'交接卡|转交|gongwen-|python |scripts/|references/|dist/prompts|\.gongwen|新开对话')
LOOPBACK_SRC = NL.join(['from http.server import HTTPServer', 'HOST = ' + repr('127.0.0.1')])


def without_index(outputs):
    return {k: v for k, v in outputs.items() if k != build_prompts.INDEX_NAME}


class XinchuangOutputTest(unittest.TestCase):

    def test_all_skills_have_skeletons(self):
        skills = {d.name for d in build_prompts.list_skill_dirs(REPO_ROOT)}
        found = {p.stem for p in (REPO_ROOT / build_prompts.LITE_SKELETON_REL).glob('*.md')}
        self.assertTrue(skills)
        self.assertEqual(found, skills)

    def test_lite_prompts_within_limit(self):
        files = without_index(build_prompts.build_lite_prompts(REPO_ROOT))
        self.assertTrue(files)
        for name, text in files.items():
            self.assertLessEqual(len(text), build_prompts.MAX_LITE_CHARS, name)
            self.assertIn('六条红线', text, name)

    def test_refined_lite_prompts_are_clean(self):
        files = build_prompts.build_lite_prompts(REPO_ROOT)
        for name, text in without_index(files).items():
            self.assertIsNone(FORBIDDEN.search(text), name)
            self.assertNotIn('省略次要示例', text, name)
            self.assertNotIn('未精修', text, name)
        self.assertNotIn('未精修', files[build_prompts.INDEX_NAME])

    def test_missing_skeleton_falls_back_with_unrefined_mark(self):
        tmp = Path(tempfile.mkdtemp(prefix='xc-unrefined-'))
        self.addCleanup(shutil.rmtree, str(tmp), ignore_errors=True)
        skill_dir = tmp / 'skills' / 'gongwen-demo'
        skill_dir.mkdir(parents=True)
        (skill_dir / 'SKILL.md').write_text(
            '# 演示\n\n## 做什么\n正文内容。\n'
            '<!-- prompt:omit: 内网说明。 -->\nAgent 专用说明。\n<!-- /prompt:omit -->\n',
            encoding='utf-8',
        )
        files = build_prompts.build_lite_prompts(tmp)
        self.assertIn('未精修', files['gongwen-demo.md'])
        self.assertIn('未精修', files[build_prompts.INDEX_NAME])
        self.assertIn('内网说明。', files['gongwen-demo.md'])
        self.assertNotIn('Agent 专用说明。', files['gongwen-demo.md'])
        self.assertNotIn('prompt:omit', files['gongwen-demo.md'])

    def test_bundles_use_skeletons_only(self):
        files = build_prompts.build_bundle_prompts(REPO_ROOT)
        bundles = without_index(files)
        self.assertEqual(set(bundles), {spec[0] for spec in build_prompts.BUNDLE_SPECS})
        for name, text in bundles.items():
            self.assertLessEqual(len(text), build_prompts.MAX_BUNDLE_CHARS, name)
            self.assertIsNone(FORBIDDEN.search(text), name)
            self.assertNotIn('省略次要示例', text, name)

    def test_oversize_prompts_are_errors(self):
        too_long = {'a.md': 'x' * (build_prompts.MAX_LITE_CHARS + 1)}
        errors = build_prompts.xinchuang_errors(REPO_ROOT, [(build_prompts.PROMPTS_LITE_REL, too_long)])
        self.assertEqual(len(errors), 1)
        real = [(build_prompts.PROMPTS_LITE_REL, build_prompts.build_lite_prompts(REPO_ROOT)),
                (build_prompts.PROMPTS_BUNDLES_REL, build_prompts.build_bundle_prompts(REPO_ROOT))]
        self.assertEqual(build_prompts.xinchuang_errors(REPO_ROOT, real), [])

    def test_rag_kb_has_dify_template_and_anchored_chunks(self):
        out = build_prompts.build_rag_kb(REPO_ROOT)
        self.assertIn('dify-app-template.yml', out)
        chunks = [k for k in out if k.startswith('chunks/')]
        self.assertTrue(chunks)
        for name in chunks:
            self.assertIn('[知识来源：', out[name], name)
        for name in ('chunks/12-output-format.md', 'fastgpt/qa-import.csv', 'maxkb/qa-import.csv'):
            self.assertIn('网页对话环境', out[name], name)
            self.assertNotIn('一份素材出多个版本时', out[name], name)

    def test_dist_prompt_artifacts_have_no_omission_markers(self):
        for directory in (build_prompts.PROMPTS_REL, build_prompts.PROMPTS_LITE_REL,
                          build_prompts.PROMPTS_BUNDLES_REL, build_prompts.RAG_KB_REL):
            files = [p for p in (REPO_ROOT / directory).rglob('*') if p.is_file()]
            self.assertTrue(files, directory)
            for path in files:
                self.assertNotIn(b'prompt:omit', path.read_bytes(), str(path))

    def test_offline_collect_includes_wheelhouse_and_sets_exec_bits(self):
        tmp = Path(tempfile.mkdtemp(prefix='xc-offline-wh-'))
        self.addCleanup(shutil.rmtree, str(tmp), ignore_errors=True)
        (tmp / 'xinchuang').mkdir(parents=True)
        (tmp / 'xinchuang' / '启动工具箱.sh').write_bytes(b'#!/usr/bin/env bash\necho ok\n')
        (tmp / 'xinchuang' / '启动工具箱.desktop').write_bytes(b'[Desktop Entry]\nName=Test\n')
        wh = tmp / 'wheelhouse' / 'aarch64' / 'py3.11'
        wh.mkdir(parents=True)
        (wh / 'demo.whl').write_bytes(b'whl')
        (wh / 'INSTALL.txt').write_bytes(b'ok')

        with_wh = {arc for arc, _p in build_prompts.collect_offline_files(tmp, include_wheelhouse=True)}
        without_wh = {arc for arc, _p in build_prompts.collect_offline_files(tmp, include_wheelhouse=False)}
        self.assertIn('wheelhouse/aarch64/py3.11/demo.whl', with_wh)
        self.assertNotIn('wheelhouse/aarch64/py3.11/demo.whl', without_wh)

        zip_path, _count = build_prompts.write_offline_zip(tmp, '1.0.0', include_wheelhouse=True)
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            self.assertIn('wheelhouse/aarch64/py3.11/demo.whl', names)
            self.assertIn('安全自查报告.md', names)
            self.assertIn('SHA256SUMS.txt', names)
            sh_mode = zf.getinfo('xinchuang/启动工具箱.sh').external_attr >> 16
            desk_mode = zf.getinfo('xinchuang/启动工具箱.desktop').external_attr >> 16
            self.assertEqual(sh_mode, 0o755)
            self.assertEqual(desk_mode, 0o755)


class SecurityAuditTest(unittest.TestCase):

    def test_flags_network_import_and_eval(self):
        found = security_audit.audit_python_source('skills/x/scripts/a.py', NL.join(['import socket', 'eval(1)']))
        kinds = {f.kind for f in found if f.severity == 'FAIL'}
        self.assertEqual(kinds, {'联网模块导入', '动态执行调用'})

    def test_http_server_only_in_loopback_allowlist(self):
        ok = security_audit.audit_python_source('xinchuang/local_toolbox.py', LOOPBACK_SRC)
        self.assertFalse([f for f in ok if f.severity == 'FAIL'])
        bad = security_audit.audit_python_source('skills/x/scripts/a.py', LOOPBACK_SRC)
        self.assertTrue([f for f in bad if f.severity == 'FAIL'])

    def test_allowlisted_file_must_bind_loopback(self):
        found = security_audit.audit_python_source('xinchuang/local_toolbox.py', 'from http.server import HTTPServer')
        self.assertIn('回环地址校验失败', {f.kind for f in found})

    def test_sha256sums_sorted_and_standard(self):
        lines = security_audit.render_sha256sums([('b.py', b'x'), ('a.py', b'')]).splitlines()
        self.assertEqual(lines[0], 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  a.py')
        self.assertTrue(lines[1].endswith('  b.py'))

    def test_subprocess_only_in_allowlist(self):
        src = 'import subprocess'
        bad = security_audit.audit_python_source('skills/x/scripts/a.py', src)
        self.assertEqual({f.kind for f in bad if f.severity == 'FAIL'}, {'未登记的本机命令调用'})
        ok = security_audit.audit_python_source('skills/gongwen-format/scripts/gw_fonts.py', src)
        self.assertFalse([f for f in ok if f.severity == 'FAIL'])
        self.assertEqual([f.kind for f in ok if f.severity == 'NOTE'], ['本机命令调用'])

    def test_flags_os_system_and_shell_true(self):
        src = NL.join(['import os', 'os.system(1)', 'import subprocess', 'subprocess.run(1, shell=True)'])
        found = security_audit.audit_python_source('tools/install.py', src)
        self.assertEqual({f.kind for f in found if f.severity == 'FAIL'}, {'系统命令调用', 'shell=True 调用'})

    def test_js_macro_audit(self):
        bad = security_audit.audit_files([('skills/x/a.js', b'var r = fetch(1);')])
        self.assertEqual([f.kind for f in bad.failures], ['宏脚本禁用写法'])
        good = security_audit.audit_files([('skills/x/a.js', 'var a = 1;'.encode('utf-8'))])
        self.assertFalse(good.failures)
        self.assertEqual(good.scanned_js, ['skills/x/a.js'])

    def test_report_covers_macro_and_subprocess_notes(self):
        summary = security_audit.audit_files(security_audit.collect_repo_py(REPO_ROOT))
        report = security_audit.render_audit_report(summary, total_files=1)
        self.assertIn('本机命令调用', report)
        self.assertIn('wps_gongwen_macro.js', ' '.join(summary.scanned_js))

    def test_repo_scripts_pass_audit(self):
        summary = security_audit.audit_files(security_audit.collect_repo_py(REPO_ROOT))
        self.assertEqual([], ['%s:%d %s' % (f.path, f.line, f.kind) for f in summary.failures])


if __name__ == '__main__':
    unittest.main()
