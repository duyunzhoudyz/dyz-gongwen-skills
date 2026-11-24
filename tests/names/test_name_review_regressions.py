# -*- coding: utf-8 -*-
"""实名专项复审原例与独立对抗样例，从三个行业引擎验证报出和遮蔽。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import NamedTuple

from tests.industry_corpus.test_industry_corpus import load_engine
from tests.names.masking import check_masked_outputs


class Case(NamedTuple):
    key: str
    industry: str
    body: str
    names: tuple[str, ...]
    levels: tuple[str, ...]
    doc_type: str | None = None
    visible: bool = False
    other_rule: str = ""
    excerpts: tuple[str, ...] = ()


def md(headers: str, *rows: str) -> str:
    return "\n".join((headers, "| " + " | ".join("---" for _ in headers.strip().strip("|").split("|")) + " |", *rows))


def soe(key: str, body: str, names: tuple[str, ...], *levels: str, **kwargs) -> Case:
    return Case(key, "soe", body, names, levels, kwargs.pop("doc_type", "纪要"), **kwargs)


UNIT_PRIORITY = (
    soe("B1.1", "决定免去张建国公司副总经理职务，对张建国给予记过处分。", ("张建国",), "P0"),
    soe("B1.2", "决定免去张建国公司总会计师职务，张建国被开除党籍。", ("张建国",), "P0"),
    soe("B1.3", "聘任李明集团总经济师。对李明给予警告处分。", ("李明",), "P0"),
    soe("B1.4", "王建国公司报销违规。\n拟安置人员：王建国、李娜。", ("王建国", "李娜"), "P1",
        excerpts=("拟安置人员：〔姓名1〕、〔姓名2〕。",)),
    soe("B1.5", "上海华建集团有限公司回函。\n对华建给予警告处分。", ("华建",), "P1"),
    soe("B1.6", "本项目专项整顿工作（以下简称“张伟”）已启动。\n对张伟给予警告处分。", ("张伟",), "P0"),
)
CELL_ITEMS = (
    Case("B2.1", "hospital", md("| 患者姓名 | 诊断 | 说明 |", "| 王秀英、李明 | 哮喘 | 治愈率100%，王秀英、李明均已出院 |"),
         ("王秀英", "李明"), ("P0", "P0"), other_rule="HOS-002", excerpts=("〔姓名1〕", "〔姓名2〕")),
    soe("B2.2", md("| 职工姓名 | 处分 | 说明 |", "| 王秀英、李明 | 警告 | 王秀英、李明先行开工 |"),
        ("王秀英", "李明"), "P0", "P0", other_rule="SOE-001", excerpts=("〔姓名1〕", "〔姓名2〕")),
    Case("B2.3", "k12", md("| 学生姓名 | 困难类型 |", "| 周梓涵（三年级2班） | 低保 |"), ("周梓涵",), ("P0",)),
    soe("B2.4", md("| 职工姓名 | 处分 |", "| 王秀英（副部长） | 警告 |"), ("王秀英",), "P0"),
    Case("B2.5a", "hospital", md("| 患者姓名 | 诊断 |", "| 王秀英（56岁，女） | 哮喘 |"), ("王秀英",), ("P0",)),
    Case("B2.5b", "hospital", md("| 患者姓名 | 诊断 |", "| **王秀英**（女） | 哮喘 |"), ("王秀英",), ("P0",)),
)
PLACEHOLDERS = (
    soe("B3.1", md("| 当事人 | 责任人 | 处分 |", "| 王明亮 | 王明 | 警告 |"),
        ("王明亮", "王明"), "P0", "P0", excerpts=("〔姓名1〕", "〔姓名2〕")),
    soe("B3.2", md("| 备注 | 当事人 | 处分 |", "| 无 | 王明亮 | 警告 |", "| 王明亮协助 | 王明 | 警告 |"),
        ("王明亮", "王明"), "P0", "P0", excerpts=("〔姓名1〕", "〔姓名2〕")),
)
MARKDOWN = (
    *(Case(f"M1.1{letter}", "hospital", md(header, "| 王秀英 | 哮喘 |"), ("王秀英",), ("P0",))
      for letter, header in zip("abcde", ("| 患者姓名： | 诊断 |", " | 姓名（实名） | 诊断 |", "| 【患者姓名】 | 诊断 |",
                                         "| **患者**姓名 | 诊断 |", "| ***患者姓名*** | 诊断 |"))),
    Case("M1.2", "hospital", md("| 编号 | 备注 |", "| 1 | 无 |") + "\n" + md("| 患者姓名 | 诊断 |", "| 王秀英 | 哮喘 |"),
         ("王秀英",), ("P0",)),
    Case("M1.3", "hospital", "序号 | 患者姓名 | 诊断\n--- | --- | ---\n | 王秀英 | 哮喘", ("王秀英",), ("P0",)),
)
PUBLIC = (
    Case("M2.1", "hospital", md("| 序号 | 投诉问题 | 责任人 | 整改时限 |", "| 1 | 导诊指引不清 | 王秀英 | 12月底 |"),
         ("王秀英",), (), visible=True),
    soe("M2.2", md("| 序号 | 违纪整改任务 | 责任人 | 完成时限 |", "| 1 | 开展警示教育 | 王秀英 | 12月底 |"),
        ("王秀英",), visible=True),
    *(Case(f"M2.3{letter}.{domain}", domain, md(header, row), ("王秀英",), (), "纪要" if domain == "soe" else None, True)
      for letter, header, row in (("a", "| 姓名 | 奖项 |", "| 王秀英 | 优秀奖 |"),
                                  ("b", "| 值班日期 | 姓名 | 值班领导 |", "| 周一 | 王秀英 | 张主任 |"),
                                  ("c", "| 姓名 | 授课内容 | 时间 |", "| 王秀英 | 国学 | 周一 |"))
      for domain in ("hospital", "soe", "k12")),
    Case("M2.4", "hospital", md("| 姓名 | 诊断 |", "| 全员 | 观察 |"), ("全员",), (), visible=True),
)
PERSON_ACTION = (
    soe("M3.1a", "经董事会研究，对曹宇航给予开除处分。", ("曹宇航",), "P0"),
    soe("M3.1b", "对李钢给予党内警告处分。", ("李钢",), "P0"),
    soe("M3.1c", "对张建给予留党察看一年处分。", ("张建",), "P0"),
    soe("M3.1d", "对李钢分别给予开除党籍处分。", ("李钢",), "P0"),
    soe("M3.2a", "对李钢（厂长）给予警告处分。", ("李钢",), "P0"),
    soe("M3.2b", "对李钢（总会计师）给予警告处分。", ("李钢",), "P0"),
    soe("M3.3a", "拟提拔人选：副书记李钢、王建国。", ("李钢", "王建国"), "P0",
        excerpts=("拟提拔人选：副书记〔姓名1〕、〔姓名2〕。",)),
    soe("M3.3b", "拟提拔人选：总工程师李钢。", ("李钢",), "P0"),
    soe("M3.4", "东岭冶炼有限责任公司（以下简称“唐钢”）。\n\n" + md("| 处分对象 | 处分 |", "| 唐钢 | 警告 |"),
        ("唐钢",), "P0"),
)
SCOPE_AND_DEDUP = (
    Case("M4.1", "k12", md("| 学生姓名 | 困难类型 |", "| 王秀英同学 | 低保 |"), ("王秀英",), ("P0",),
         excerpts=("〔姓名1〕",)),
    soe("M4.2", "拟安置人员：唐钢、王建国。", ("唐钢", "王建国"), "P1",
        excerpts=("拟安置人员：〔姓名1〕、〔姓名2〕。",)),
    soe("M4.3", md("| 责任人 | 工作事项 |", "| 王秀英 | 完善制度 |"), ("王秀英",), doc_type="合规报告"),
    soe("M4.3a", md("| 责任人 | 工作事项 |", "| 王秀英 | 完善制度 |"), ("王秀英",), doc_type="改革台账"),
    soe("M4.3b", md("| 责任人 | 工作事项 |", "| 王秀英 | 完善制度 |"), ("王秀英",), doc_type="ESG报告"),
)

ADVERSARIAL_PEOPLE = (
    soe("人01", "东岭钢铁集团有限公司（以下简称“李钢”）。\n对李钢给予党内严重警告处分。", ("李钢",), "P0"),
    soe("人02", "李钢集团发布通告。\n李钢、王铁分别受到政务记大过处分。", ("李钢", "王铁"), "P0"),
    soe("人03", "由周铁公司内部核查。\n对周铁给予撤职处分。", ("周铁",), "P0"),
    soe("人04", "关于撤销赵航集团副董事长职务的决定。\n对赵航给予警告处分。", ("赵航",), "P1"),
    soe("人05", "华东王铁公司已回函。\n对王铁给予政务记过处分。", ("王铁",), "P0"),
    soe("人06", "何建集团已回函。\n何建（工号77）受到警告处分。", ("何建",), "P0"),
    soe("人07", "对周航进行了诫勉谈话。\n周航公司回函。", ("周航",), "P0"),
    soe("人08", "陈建股份有限公司已回函。\n拟提拔人选：副董事长陈建、魏文静。", ("陈建", "魏文静"), "P0"),
    soe("人09", "有关制度文件（以下简称‘张伟’）已经印发。\n张伟被免职。", ("张伟",), "P0"),
    soe("人10", "南方建设有限公司（以下简称“赵铁”）。\n" + md("| 处分对象 | 处分 |", "| 赵铁 | 政务记过 |"),
        ("赵铁",), "P0"),
    soe("人11", "西岭财务有限公司（以下简称“孙航”）。\n对王铁、孙航分别给予撤销党内职务处分。", ("王铁", "孙航"), "P0"),
    soe("人12", "方建集团发布通告。\n对方建同志给予警告处分。\n拟安置人员：方建、郑文俊。", ("方建", "郑文俊"), "P0", "P1"),
)
ADVERSARIAL_TABLES = (
    Case("表01", "hospital", md("| 患者姓名 | 诊断 | 说明 |",
                             "| **刘玉兰（病区A，女）**、陈志明（已出院） | 观察 | 治愈率100%，刘玉兰、陈志明均已离院 |"),
         ("刘玉兰", "陈志明"), ("P0", "P0"), other_rule="HOS-002"),
    Case("表02", "hospital", "编号 | 《患者姓名》 | 床号\n:--- | --- | ---:\n | 陈爱玲(预住院) | 3床\n陈爱玲治愈率100%。",
         ("陈爱玲",), ("P0",), other_rule="HOS-002"),
    Case("表03", "hospital", md("| 编号 | 说明 |", "| 1 | 无 |") + "\n"
         + md("| **病人**姓名（实名）： | 检查结果 |", "| 余小敏 | 复查 |") + "\n余小敏治愈率100%。",
         ("余小敏",), ("P0",), other_rule="HOS-002"),
    Case("表04", "k12", md("| 学生姓名 | 心理 | 备注 |", "| 蔡雨薇（申请中） | 观察 | 公布考试成绩排名，蔡雨薇第一 |"),
         ("蔡雨薇",), ("P0",), other_rule="K12-G01"),
    Case("表05", "k12", md("| 学生姓名 | 困难类型 |", "| **李秋瑶**及周伟 | 单亲 |") + "\n公布考试成绩排名，李秋瑶、周伟在列。",
         ("李秋瑶", "周伟"), ("P0",), other_rule="K12-G01"),
    soe("表06", md("| 职工姓名 | 处分 | 说明 |", "| 王明亮、王明 | 记过 | 王明亮、王明均已先行开工 |"),
        ("王明亮", "王明"), "P0", "P0", other_rule="SOE-001", excerpts=("〔姓名1〕", "〔姓名2〕")),
    soe("表07", md("| 职工姓名 | 工作事项 |", "| 徐明佳（已调离） | 协调采购 |") + "\n徐明佳所在项目先行开工。",
        ("徐明佳",), doc_type="合规报告", other_rule="SOE-001"),
    Case("表08", "k12", md("| 【学生姓名】 | 病史 |", "| 金一诺(已转班)、肖博扬同学 | 哮喘 |")
         + "\n金一诺、肖博扬被公布考试成绩排名。", ("金一诺", "肖博扬"), ("P0",), other_rule="K12-G01"),
    Case("表09", "hospital", md("| 姓名 | 住院号 |", "| _郑秀英_（复诊）和赵小雨 | 123 |")
         + "\n郑秀英和赵小雨治愈率100%。", ("郑秀英", "赵小雨"), ("P0", "P0"), other_rule="HOS-002"),
    soe("表10", "华北沈航股份有限公司已回函。\n" + md("| 处分对象 | 处分 | 备注 |",
        "| ***沈航***（已离岗） | 警告 | 沈航先行开工 |"), ("沈航",), "P0", other_rule="SOE-001"),
    Case("表11", "k12", md("| 学生姓名 | 说明 |", "| 钟可欣 | 低保家庭学生郑雨桐近期情绪低落 |")
         + "\n公布考试成绩排名，钟可欣、郑雨桐在列。", ("钟可欣", "郑雨桐"), ("P0",), other_rule="K12-G01"),
    Case("表12", "hospital", md("| 患儿姓名 | 诊断 | 说明 |", "| 欧阳明月（转科,21床）与**陈丽** | 观察 | 治愈率100%，欧阳明月与陈丽均观察 |"),
         ("欧阳明月", "陈丽"), ("P0", "P0"), other_rule="HOS-002"),
)

# 第二轮评审原始输入；文件名也故意含人名，供两个输出通道核验。
ROUND2_PEOPLE = (
    soe("NB1_01", "张伟公司电脑遗失，造成失密风险。\n对张伟给予警告处分。", ("张伟",), "P0"),
    soe("NB1_02", "王建国公司卡消费超标。\n对王建国给予警告处分。", ("王建国",), "P0"),
    soe("NB1_03", "经查，陈敏公司账目异常。\n拟安置人员：陈敏、周杰。", ("陈敏", "周杰"), "P1"),
    soe("NB1_04", "李明集团内违规违纪。\n对李明给予警告处分。", ("李明",), "P0"),
    soe("NB1_05", "张伟股份占比30%。\n对张伟给予警告处分。", ("张伟",), "P0"),
    soe("NB1_06", "免去：张建国公司副总工程师职务。\n对张建国给予记过处分。", ("张建国",), "P0"),
    soe("NB1_07", "刘洋公司纪委书记职务已免。\n对刘洋给予记过处分。", ("刘洋",), "P0"),
    soe("NB1_08", "经王伟公司垫付差旅费。\n对王伟给予警告处分。", ("王伟",), "P0"),
    soe("NB1_09", "在李强公司工作期间考勤造假。\n拟安置人员：李强、周敏。", ("李强", "周敏"), "P1"),
    soe("NB1_10", "对赵磊公司期间报销开展核查。\n对赵磊给予警告处分。", ("赵磊",), "P0"),
    soe("NB1_11", "唐钢公司回函。\n对唐钢（42岁，男）给予警告处分。", ("唐钢",), "P0"),
    soe("NB1_12", "唐钢公司回函。\n拟安置人员：唐钢（42岁，男）、王建国。", ("唐钢", "王建国"), "P0"),
    soe("NB1_13", "东岭冶炼有限责任公司（以下简称“唐钢”）。\n\n" +
        md("| 职工姓名 | 处分 |", "| 唐钢 | 警告 |"), ("唐钢",), "P0"),
    soe("NB1_14", "孙建公司副厂长任职期满。\n对孙建给予记过处分。", ("孙建",), "P0"),
)


def table_case(key, industry, cell, names, remarks):
    header, detail, sensitive, other = {
        "hospital": ("患者姓名", "诊断", "哮喘", "HOS-002"),
        "soe": ("职工姓名", "处分", "警告", "SOE-001"),
        "k12": ("学生姓名", "困难类型", "低保", "K12-G01"),
    }[industry]
    body = md(f"| {header} | {detail} | {'备注' if industry == 'k12' else '说明'} |",
              f"| {cell} | {sensitive} | {remarks} |")
    return Case(key, industry, body, names, ("P0",) * (1 if industry == "k12" else len(names)),
                "纪要" if industry == "soe" else None, other_rule=other)


ROUND2_CELLS = (
    table_case("NB2_01", "hospital", "**王秀英、李明**", ("王秀英", "李明"), "治愈率100%，王秀英、李明已出院"),
    table_case("NB2_02", "soe", "`王秀英、李明`", ("王秀英", "李明"), "王秀英、李明先行开工"),
    table_case("NB2_03", "k12", "**周梓涵（三班）、吴雨桐（五班）**", ("周梓涵", "吴雨桐"), "公布考试成绩排名，周梓涵、吴雨桐在列"),
    table_case("NB2_04", "hospital", "王秀英、李明等2人", ("王秀英", "李明"), "治愈率100%，李明出院"),
    table_case("NB2_05", "k12", "周梓涵等3人", ("周梓涵",), "公布考试成绩排名，周梓涵第一"),
    table_case("NB2_06", "hospital", "王秀英 李明", ("王秀英", "李明"), "治愈率100%，王秀英、李明复查"),
    table_case("NB2_07", "soe", "王秀英；李明", ("王秀英", "李明"), "王秀英、李明先行开工"),
    table_case("NB2_08", "k12", "周梓涵/吴雨桐", ("周梓涵", "吴雨桐"), "公布考试成绩排名，周梓涵、吴雨桐在列"),
    table_case("NB2_09", "hospital", "王秀英<br>李明", ("王秀英", "李明"), "治愈率100%，王秀英、李明出院"),
    table_case("NB2_10", "soe", "副部长**王秀英**", ("王秀英",), "王秀英先行开工"),
    table_case("NB2_11", "hospital", "~~王秀英~~", ("王秀英",), "治愈率100%，王秀英已转院"),
    table_case("NB2_12", "k12", "1.周梓涵", ("周梓涵",), "公布考试成绩排名，周梓涵第一"),
    table_case("NB2_13", "hospital", "王秀英、刘海", ("王秀英", "刘海"), "治愈率100%，王秀英、刘海复查"),
    table_case("NB2_14", "soe", "（原财务部）王秀英", ("王秀英",), "王秀英先行开工"),
)
ROUND2_DUTY = (
    soe("O1", md("| 责任人 | 处分 | 整改措施 |", "| 王秀英 | 党内警告 | 限期退赔 |"), ("王秀英",), "P0"),
    soe("O2", md("| 责任人 | 违纪事实 | 处分 | 完成时限 |", "| 王秀英 | 违规报销 | 记过 | 10月底 |"), ("王秀英",), "P0"),
    Case("O9", "hospital", md("| 责任人 | 诊断 | 整改措施 |", "| 王秀英 | 哮喘 | 整改完成 |"), ("王秀英",), ("P0",)),
)

# 弱处分锚点与独立身份说明分开；严格定义放在正文前、后两种位置。
NEW_PEOPLE = (
    *(soe(f"真人{i:02}", f"河西检测中心（以下简称“陆航”）。\n对陆航给予警告处分。\n{identity}", ("陆航",), "P1")
      for i, identity in enumerate((
          "人员身份已核验：纪委书记陆航签字。", "人员身份已核验：陆航副总审计师签字。",
          "签收记录：陆航（档案编号37，工号82）。", "出席凭据：陆航（本期核验，56岁）。",
          "签名记录：陆航（轮值，女）。", "参会人员：陆航同志签到。",
          "班务履历：陆航同学曾任班长。", "紧急联络人：工会主席陆航。",
          "交接记录：陆航（已返岗）。", "负责人：党组副书记陆航。",
      ), 1)),
    soe("真人11", "对姚钢给予警告处分。\n交接由姚钢副总法律顾问签字。\n河东冶炼厂，以下简称姚钢。", ("姚钢",), "P1"),
    soe("真人12", "北岸电力有限公司（以下简称“唐钢-A”）。\n对唐钢给予警告处分。", ("唐钢",), "P1"),
    soe("真人13", "东岭资产有限公司审计方案（以下简称“罗敏”）。\n对罗敏给予警告处分。", ("罗敏",), "P0"),
    soe("真人14", "西岭资产有限公司《资金管理规定》（以下简称“谢华”）。\n对谢华给予记过处分。", ("谢华",), "P0"),
    soe("真人15", "东岭检测中心（以下简称“许航”）。\n对许航给予警告处分。\n" +
        md("| 随访员姓名 | 序号 |", "| 许航 | 7 |"), ("许航",), "P1", "P0"),
    *(soe(f"真人{i}", f"{phrase}（以下简称“唐钢”）。\n对唐钢给予警告处分。", ("唐钢",), "P1")
      for i, phrase in enumerate(("公共场所", "园区布局", "患者入院", "依法治厂"), 16)),
    *(soe(f"真人{i}", f"河西检测中心（以下简称“{name}”）。\n{body}", (name,), lv)
      for i, name, body, lv in (
          (20, "刘海", "对刘海（42岁，男）给予警告处分。", "P0"),
          (21, "刘海", "拟安置人员：刘海（42岁，男）。", "P0"),
          (22, "唐钢", "对唐钢同学给予警告处分。", "P0"),
          (23, "唐钢", "唐钢同学受到警告处分。", "P0"),
          (24, "唐钢", "任命唐钢担任副总经理。\n对唐钢给予警告处分。", "P1"),
      )),
)


def cross_table(key, domain, cells, names, *, lead="", header="", levels=None):
    label, sensitive, other, trigger = {
        "hospital": ("患者姓名", "诊断", "HOS-002", "治愈率100%"),
        "soe": ("职工姓名", "处分", "SOE-001", "先行开工"),
        "k12": ("学生姓名", "病史", "K12-G01", "公布考试成绩排名"),
    }[domain]
    echo = "、".join(names) + trigger + "。"
    body = echo + "\n" + lead + md(f"| {header or label} | {sensitive} |", *(f"| {v} | 记录 |" for v in cells)) + "\n" + echo
    return Case(key, domain, body, names, levels or ("P0",) * (len(cells) if domain == "k12" else len(names)),
                "纪要" if domain == "soe" else None, other_rule=other)


NEW_TABLES = (
    cross_table("外露01", "hospital", ["王秀英🩺李明"], ("王秀英", "李明")),
    cross_table("外露02", "soe", ["陈敏\\|周杰"], ("陈敏", "周杰")),
    cross_table("外露03", "k12", ["周梓涵\u200b吴雨桐"], ("周梓涵", "吴雨桐")),
    cross_table("外露04", "hospital", ["陈丽①李明②王秀英"], ("陈丽", "李明", "王秀英")),
    cross_table("外露05", "soe", ["审计部副总审计师陈敏"], ("陈敏",)),
    cross_table("外露06", "k12", ["【随访（周五复查）】周梓涵"], ("周梓涵",)),
    cross_table("外露07", "hospital", ["〔一病区〕陈丽〔床位（待定）〕"], ("陈丽",)),
    cross_table("外露08", "soe", ["采购中心时任副厂长宋文静"], ("宋文静",)),
    cross_table("外露09", "k12", ["周梓涵→吴雨桐"], ("周梓涵", "吴雨桐"), header="随访学生姓名"),
    cross_table("外露10", "hospital", ["罗佳琪", "陈丽", "罗佳琪"], ("罗佳琪", "陈丽"), levels=("P0",) * 3),
    cross_table("外露11", "soe", ["(A-9)李明｜陈敏"], ("李明", "陈敏")),
    cross_table("外露12", "k12", ["一、吴雨桐★周梓涵等两人"], ("吴雨桐", "周梓涵")),
    cross_table("外露13", "hospital", ["刘海＋陈丽"], ("刘海", "陈丽")),
    cross_table("外露14", "soe", ["张伟\t陈敏"], ("张伟", "陈敏"), lead="| 标题 | 序号 |\n| --- | --- |\n| 至此 | 1 |\n"),
    cross_table("外露15", "k12", ["整改组〔说明〕吴雨桐◆周梓涵"], ("吴雨桐", "周梓涵")),
    *(Case(f"外露{i}", domain, f"李明{trigger}。\n王秀英、李明。{trigger}。\n" +
           md(header, "| 王秀英 | 记录 |"), ("王秀英", "李明"), ("P0",),
           "纪要" if domain == "soe" else None, other_rule=other)
      for i, domain, header, trigger, other in (
          (16, "hospital", "| 患者姓名 | 诊断 |", "治愈率100%", "HOS-002"),
          (17, "soe", "| 职工姓名 | 处分 |", "先行开工", "SOE-001"),
          (18, "k12", "| 学生姓名 | 病史 |", "公布考试成绩排名", "K12-G01"),
      )),
)

CASE_GROUPS = {
    "new_people": NEW_PEOPLE, "new_tables": NEW_TABLES,
    "round2_people": ROUND2_PEOPLE, "round2_cells": ROUND2_CELLS, "round2_duty": ROUND2_DUTY,
    "unit_priority": UNIT_PRIORITY, "cell_items_and_cross_rule_masking": CELL_ITEMS, "distinct_placeholders": PLACEHOLDERS,
    "markdown_boundaries": MARKDOWN, "public_and_duty_tables": PUBLIC, "natural_person_actions_and_titles": PERSON_ACTION,
    "rule_scope_and_deduplication": SCOPE_AND_DEDUP, "adversarial_people": ADVERSARIAL_PEOPLE,
    "adversarial_tables": ADVERSARIAL_TABLES,
}
NAME_RULES = {"hospital": {"HOS-031"}, "k12": {"K12-G04"}, "soe": {"SOE-022", "SOE-023"}}


def run_case(case: Case, path: Path):
    path.write_text(case.body, encoding="utf-8")
    engine = load_engine(case.industry)
    if case.industry == "k12":
        names, check, render = engine.shared_names()[0], lambda: engine.check_general(path), engine.render_check_text
    else:
        names = engine.shared_kit().names if case.industry == "hospital" else engine._shared()[0]
        check, render = lambda: engine.check_file(path, case.doc_type), engine.render_text

    def run():
        report = check()
        return report, render(report)

    return check_masked_outputs(names, run, expected_names=() if case.visible else case.names)


class NameReviewRegressionTest(unittest.TestCase):
    def assert_cases(self, group: str) -> None:
        for case in CASE_GROUPS[group]:
            with self.subTest(case=case.key, text=case.body), tempfile.TemporaryDirectory() as work:
                path = Path(work) / ("及".join(case.names) + "附表.md")
                report, screen = run_case(case, path)
                issues = report["issues"]
                rows = [i for i in issues if i["id"] in NAME_RULES[case.industry]]
                self.assertEqual(tuple(i["level"] for i in rows), case.levels, rows)
                if case.excerpts:
                    self.assertEqual(tuple(i["excerpt"] for i in rows), case.excerpts)
                if case.other_rule:
                    refs = [i for i in issues if i["id"] == case.other_rule]
                    self.assertTrue(refs, issues)
                    self.assertTrue(any("〔姓名" in (i.get("context", "") + i["excerpt"]) for i in refs), refs)
                if case.visible:
                    self.assertEqual(report["file"], path.name)
                else:
                    for name in case.names:
                        self.assertNotIn(name, json.dumps(report, ensure_ascii=False))
                        self.assertNotIn(name, screen)
                    self.assertIn("〔姓名", report["file"])
                if case.key in ("B1.5", "M4.2"):
                    self.assertIn("可能是单位简称，请人工确认", rows[0]["message"])
                if case.key.startswith("M3.") or case.key == "人02":
                    self.assertTrue(all("可能是单位简称" not in row["message"] for row in rows), rows)

                if case.key == "人12":
                    self.assertNotIn("可能是单位简称", rows[0]["message"])
                    self.assertIn("可能是单位简称", rows[1]["message"])

    def test_unknown_cells_warn_once_per_row_and_respect_scope(self):
        for domain, header, rule, types in (
            ("hospital", "诊断", "HOS-031", (None,)), ("k12", "病史", "K12-G04", (None,)),
            ("soe", "违纪", "SOE-022", ("合规报告", "纪要")),
            ("soe", "序号", "SOE-023", ("纪要", "合规报告")),
        ):
            for doc_type in types:
                with self.subTest(domain=domain, doc_type=doc_type, header=header), tempfile.TemporaryDirectory() as work:
                    body = md(f"| 姓名 | 当事人 | {header} |", "| ？？？ | X-17 | 记录 |",
                              "| 王秀英 | 𠮷野 | 记录 |", "| | — | 记录 |")
                    case = Case("兜底", domain, body, ("王秀英",), (), doc_type)
                    report, screen = run_case(case, Path(work) / "王秀英.md")
                    rows = [i for i in report["issues"] if i["id"] == rule]
                    warnings = [(i["line"], i["level"]) for i in rows if i["message"] == "姓名列内容未能识别，请人工核对"]
                    expected = [] if rule == "SOE-023" and doc_type == "合规报告" else [(3, "P1"), (4, "P1")]
                    self.assertEqual(sorted(warnings), expected)
                    self.assertEqual(report["file"], "〔姓名1〕.md")
                    if expected:
                        self.assertIn("姓名列内容未能识别，请人工核对", screen)

    def test_fallback_skips_public_and_duty_tables(self):
        for domain, col in (("hospital", "投诉问题"), ("soe", "违纪整改任务"), ("k12", "整改措施")):
            for label, subject in (("责任人姓名", col), ("姓名", "授课内容")):
                case = Case("公开", domain, md(f"| {label} | {subject} |", "| A-17 | 记录 |"), (), (), "纪要")
                with self.subTest(domain=domain, label=label), tempfile.TemporaryDirectory() as work:
                    report, _ = run_case(case._replace(doc_type="纪要" if domain == "soe" else None), Path(work) / "表.md")
                    self.assertFalse(any(i["id"] in NAME_RULES[domain] for i in report["issues"]))

    def test_strict_alias_definition_and_titles(self):
        engine = load_engine("soe")
        gn = engine._shared()[0]
        rule = next(r for r in engine.load_rules().rules if r.id == "SOE-022")
        self.assertTrue(all(a.left_ok.pattern == "(?:" + gn._PERSON_TITLE + "|原|时任|现任|该)$"
                            for a in rule.anchors if a.kind == "frame"))
        for unit in ("能源有限公司", "能源有限责任公司", "能源股份有限公司", "集团公司", "集团有限公司",
                     "总公司", "分公司", "电机厂", "矿务局", "设计院", "研究所", "检测中心", "管理委员会"):
            body = f"河西{unit}（以下简称“陆航”）。\n对陆航给予警告处分。"
            case = soe("简称", body, ("陆航",), "P1")
            with self.subTest(unit=unit), tempfile.TemporaryDirectory() as work:
                report, _ = run_case(case, Path(work) / "陆航.md")
                self.assertEqual(report["file"], "〔姓名1〕.md")
                self.assertEqual([(i["level"], i["message"]) for i in report["issues"] if i["id"] == "SOE-022"],
                                 [("P1", gn.DEFINED_ABBREVIATION_HINT)])
        for title in ("副总工程师", "副总会计师", "副总经济师", "副厂长", "纪委书记", "党委委员", "总法律顾问"):
            body = md("| 处分对象 | 处分 |", f"| {title}陆航 | 警告 |")
            case = soe("职务", body, ("陆航",), "P0")
            with self.subTest(title=title), tempfile.TemporaryDirectory() as work:
                report, _ = run_case(case, Path(work) / "陆航.md")
                self.assertEqual([(i["level"], i["excerpt"]) for i in report["issues"] if i["id"] == "SOE-022"],
                                 [("P0", "〔姓名1〕")])
                self.assertEqual(report["file"], "〔姓名1〕.md")

    def test_new_people(self):
        self.assert_cases("new_people")

    def test_new_tables(self):
        self.assert_cases("new_tables")

    def test_round2_people(self):
        self.assert_cases("round2_people")

    def test_round2_cells(self):
        self.assert_cases("round2_cells")

    def test_round2_duty(self):
        self.assert_cases("round2_duty")

    def test_unit_priority(self) -> None:
        self.assert_cases("unit_priority")

    def test_cell_items_and_cross_rule_masking(self) -> None:
        self.assert_cases("cell_items_and_cross_rule_masking")

    def test_distinct_placeholders(self) -> None:
        self.assert_cases("distinct_placeholders")

    def test_markdown_boundaries(self) -> None:
        self.assert_cases("markdown_boundaries")

    def test_public_and_duty_tables(self) -> None:
        self.assert_cases("public_and_duty_tables")

    def test_natural_person_actions_and_titles(self) -> None:
        self.assert_cases("natural_person_actions_and_titles")

    def test_rule_scope_and_deduplication(self) -> None:
        self.assert_cases("rule_scope_and_deduplication")

    def test_adversarial_people(self) -> None:
        self.assert_cases("adversarial_people")

    def test_adversarial_tables(self) -> None:
        self.assert_cases("adversarial_tables")
