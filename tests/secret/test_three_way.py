# -*- coding: utf-8 -*-
"""三套密级识别口径的一致性测试：保密闸门 secret_check、通用机检 PRI-005/PRI-006、画像脚本 secret_marks。

同一批标注样例，三处结论必须相同；确因职责不同而有差别的，只能列在 GATE_ONLY 里并写明理由，不得静默不一致。
事实源是 shared/scripts/secret_check.py：lint_rules.json 中 PRI-005/PRI-006 的 pattern 由它的 lint_patterns() 生成，
secret_marks 的内置副本也取自它。

运行：python -m unittest discover -s tests/secret -t .
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from tests.lint.helpers import LINTER, gl  # noqa: F401  （加载共享机检引擎）
from tests.profile.helpers import SCRIPTS_DIR as PROFILE_SCRIPTS  # noqa: F401  （把画像脚本目录加入 sys.path）

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SCRIPTS = REPO_ROOT / "shared" / "scripts"
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

import secret_check as sc  # noqa: E402
import secret_marks  # noqa: E402

# 应识别（三处都报）：密级、保密期限、商业秘密标注、内部标注
MUST_MARK = (
    # 独立成行
    "机密", "秘密", "绝密", "  机密  ", "机　密", "机 密", "【机密】", "（机密）", "[绝密]", "机密级", "（机密级）",
    "机密　特急", "# 机密", "**机密**", "机密件", "机密文件，注意保管", "机密，阅后收回",
    # 带保密期限
    "机密（10年）", "秘密(★5年)", "机密★10年", "机密★长期", "绝密（长期）", "机密·5年", "绝密·长期", "秘密★5年",
    "绝密★启用前", "★机密",
    # 标签
    "密级：机密", "保密等级：秘密", "密级:绝密", "密 级：机 密", "本文件密级为秘密。",
    # 断言本件密级的句子
    "此件机密，阅后收回", "该件秘密，阅后销毁", "本件为机密级文件，请勿外传。", "本件属机密，不得复制。",
    "该文件定为机密", "本文件属机密文件", "该材料属机密。", "该件为秘密。", "这是一份机密文件。",
    "该稿已标注机密。", "本通知属秘密级文件。", "此文件为机密。",
    # 保密期限的标注形态
    "保密期限：10年", "保密期限为10年", "保密期限：★5年", "保密期限 长期", "保密期限:3个月", "机密 保密期限",
    # 商业秘密标注
    "【核心商密】", "密级：商业秘密", "（核心商密★5年）", "[普通商密]", "商密", "（商密）", "核心商密★5年",
    # 内部标注
    "内部资料", "内部资料，严禁外传", "（内部资料　注意保存）", "工作秘密　不得外传", "本材料属工作秘密，不得外传。",
    "仅供内部参考", "内部参阅", "注意保密",
    # v1.3.0 补入（此前文档登记为“三处都不认”）：空白代替冒号、保密期限写到期日、标题行开头的方括号密级、括注里的解密时间、考试式标注
    "密级　秘密", "密级 机密", "保密期限：至2030年12月31日", "保密期限：2030年12月31日",
    "【秘密】关于加强值班工作的通知", "[机密] 关于调整值班安排的通知", "机密（解密时间：2030年1月1日）",
    "绝密·启用前",
)

# 不应识别（三处都放行）：保密制度正文、规范性/条件性/否定性叙述、固定词、标题
MUST_PASS = (
    # v1.3.0 补入的反例：叙述里的“密级 ……”“保密期限 ……”、以“秘密”开头的复合词、方括号里不是单独的密级词
    "密级 的确定应当遵循最小化原则。", "保密期限 届满后自行解密。", "【秘密载体管理】各部门应当严格执行。",
    "密级 秘密级、机密级文件分别管理。", "保密期限：至解密之日止。",
    "各部门应当按规定确定密级和保密期限；保密期限届满的，按规定解密或者延长保密期限，并做好登记。",
    "国家秘密的保密期限，除另有规定外，绝密级不超过三十年，机密级不超过二十年，秘密级不超过十年。",
    "涉密人员应当按照密级和保密期限管理文件。",
    "对拟定为机密级的事项，由定密责任人审核。",
    "经审查，该事项不应定为机密。",
    "涉密人员接触机密级文件须经审批。",
    "本材料系秘密投票结果汇总。",
    "本文件不属于机密级文件。",
    "本文件不涉及机密事项。",
    "该文件应定为机密级的，须报审批。",
    "做好机密文件的登记、传阅和清退。",
    "各单位要定期开展机密文件清退检查。",
    "机密文件管理办法",
    "要保守国家秘密，做好保密工作。",
    "严防商业秘密泄露。",
    "采用秘密投票方式表决。",
    "揭开了一个秘密。",
    "加强对商业机密文件的管理。",
    "秘密工作者不在此列。",
    "保密教育月活动。",
    "加强秘密文件管理。",
    "严禁通过互联网传输秘密文件。",
    "涉密文件要专柜存放。",
    "涉及企业商业秘密。",
    "凡属机密文件，一律专柜存放。",
    "本通知不涉密。",
    "请各单位做好定密工作。",
    "该事项是秘密进行的。",
    "此次选举为秘密投票。",
    "这是商业秘密。",
    "本规定属于机密文件管理范畴。",
    "上述事项属于秘密文件管理范围。",
    "密级分为绝密、机密、秘密三级",
    "国家秘密的密级分为绝密级、机密级、秘密级。",
    "三、秘密载体管理",
    "（二）机密事项",
    "加强商业秘密保护",
    "签订商业秘密保护协议",
    "依法保护商业秘密。",
    "保密期限届满的，按规定解密。",
    "各单位须对拟定为秘密级以上的事项履行定密程序。",
)

# 闸门拦、通用机检与画像脚本放行的样例：(样例, 理由)。闸门“宁严勿漏”，另两处面向规范文书、不能因叙述性用词误报 P0
GATE_ONLY = (
    ("规范标注“秘密★1年”等密级标识。", "引号内的举例：通用机检与画像脚本按 skip_in_quotes 放行，闸门不分引号，宁严勿漏"),
    ("加强内部资料管理，规范标注“内部资料”字样。", "内部标注词出现在句子里：闸门停，PRI-006 只认整行标注和“本材料属……”形态，否则规范文书会误报"),
    ("编印《保密知识读本》（内部资料）2000册，发放到各科室。", "同上，出版物的“内部资料”字样是正常标注"),
    ("严守工作秘密，不在非涉密计算机上处理工作秘密。", "同上，保密教育文稿里的“工作秘密”是叙述"),
    ("本期简报仅供内部参考。", "同上：句中“仅供内部参考”闸门停，PRI-006 只认“本材料/本文件……”主语形态"),
)


def gate(text):
    return bool(sc.scan([("x", text)]))


def lint(text):
    r = gl.lint_text(text, None, "privacy", linter=LINTER)
    return any(i["id"] in ("PRI-005", "PRI-006") for i in r["issues"])


def marks(text):
    return any(label in ("密级标识", "内部标注") for label in secret_marks.find_marks([text]))


def verdicts(text):
    return gate(text), lint(text), marks(text)


class ThreeWayTest(unittest.TestCase):
    def test_sample_counts(self):
        self.assertGreaterEqual(len(MUST_MARK), 30)
        self.assertGreaterEqual(len(MUST_PASS), 30)
        self.assertEqual(len(set(MUST_MARK)), len(MUST_MARK), "应识别样例有重复")
        self.assertEqual(len(set(MUST_PASS)), len(MUST_PASS), "应放行样例有重复")

    def test_must_mark_all_three(self):
        for text in MUST_MARK:
            self.assertEqual(verdicts(text), (True, True, True), "应三处都识别（闸门，PRI，画像）：" + text)

    def test_must_pass_all_three(self):
        for text in MUST_PASS:
            self.assertEqual(verdicts(text), (False, False, False), "应三处都放行（闸门，PRI，画像）：" + text)

    def test_declared_exceptions(self):
        for text, reason in GATE_ONLY:
            self.assertTrue(reason)
            self.assertEqual(verdicts(text), (True, False, False), "例外样例结论变了：" + text)

    def test_single_line_wrapping_unchanged(self):
        """样例放在多行文本里的行首，三处同样识别（逐行规则不依赖整篇只有一行）。"""
        for text in ("机密", "【核心商密】", "保密期限为10年", "机密文件，注意保管"):
            doc = "关于做好保密工作的通知\n\n" + text + "\n\n各单位要认真落实。"
            r = gl.lint_text(doc, None, "privacy", linter=LINTER)
            self.assertTrue(any(i["id"] in ("PRI-005", "PRI-006") for i in r["issues"]), text)

    def test_specimens_agree(self):
        """整篇标本：闸门与通用机检（PRI-005/PRI-006）结论一致；放行标本三处都不报，拦截标本三处都报（含定密台账）。"""
        specimen_dir = Path(__file__).resolve().parent / "specimens"
        for f in sorted(specimen_dir.glob("pass_*.txt")):
            lines = f.read_text(encoding="utf-8").splitlines()
            self.assertFalse(sc.scan(sc.extract(f)), f.name)
            self.assertFalse(lint(chr(10).join(lines)), f.name)
            self.assertFalse(secret_marks.find_marks(lines), f.name)
        for f in sorted(specimen_dir.glob("block_*.txt")):
            lines = f.read_text(encoding="utf-8").splitlines()
            self.assertTrue(sc.scan(sc.extract(f)), f.name)
            self.assertTrue(lint(chr(10).join(lines)), f.name)
            self.assertTrue(secret_marks.find_marks(lines), f.name)

    def test_lint_rules_generated_from_secret_check(self):
        """lint_rules.json 的 PRI-005/PRI-006 pattern 必须与 secret_check.lint_patterns() 完全相同，改一处另一处要跟着改。"""
        data = json.loads((SHARED_SCRIPTS / "lint_rules.json").read_text(encoding="utf-8"))
        by_id = {r["id"]: r for r in data["rules"]}
        expected = sc.lint_patterns()
        for rid in ("PRI-005", "PRI-006"):
            self.assertEqual(by_id[rid]["pattern"], expected[rid], rid + " 与 secret_check 不同步，请重新生成")

    def test_skill_copies_in_sync(self):
        """画像脚本目录里的 lint_rules.json、secret_check.py 是 shared 的同步副本。"""
        for name in ("lint_rules.json", "secret_check.py"):
            self.assertEqual((SHARED_SCRIPTS / name).read_bytes(), (PROFILE_SCRIPTS / name).read_bytes(), name)


if __name__ == "__main__":
    unittest.main()
