#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把每个 skill 编译成可直接粘贴到网页大模型（DeepSeek、豆包、Kimi 等）的"提示词版"。

产物：
  dist/prompts/<skill>.md   信息块 + SKILL.md 正文（去掉 frontmatter）+ 按 prompt_bundle 顺序的附录
  dist/prompts/README.md    索引表
  dist/offline/dyz-gongwen-skills-offline-<版本>.zip（--offline 时生成）
    内含 skills/、dist/prompts/、一键安装脚本（install.ps1、install.sh、tools/install.py、
    .claude-plugin/marketplace.json）、根目录文档，以及由 tools/offline_readme.md 生成的"离线使用说明.md"

输出是确定性的：同样的输入，生成的文件逐字节相同（统一 LF 换行，不含时间戳）。
退出码：0 成功；1 存在错误，或 --check 发现不一致。
"""
from __future__ import annotations

import csv
import io
import os
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Set, Tuple

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from sync_shared import (  # noqa: E402
    REPO_ROOT,
    add_root_argument,
    exists_exact,
    list_skill_dirs,
    load_json_file,
    make_parser,
    normalize_rel_path,
    same_text_ignoring_eol,
    setup_console,
)
from validate import split_frontmatter  # noqa: E402

PROMPTS_REL = "dist/prompts"
PROMPTS_LITE_REL = "dist/prompts-lite"
PROMPTS_BUNDLES_REL = "dist/prompts-bundles"
RAG_KB_REL = "dist/rag-kb"
OFFLINE_REL = "dist/offline"
INDEX_NAME = "README.md"
LONG_PROMPT_CHARS = 30000
# 提示词版字数硬上限：超过时构建报错（--check 同样失败）。LONG_PROMPT_CHARS 只用于超长提示
MAX_PROMPT_CHARS = 29000
# 政务内网精简版硬上限：适配 4K/8K 系统提示词框和 32B/70B 私有化模型
MAX_LITE_CHARS = 4000
# 高频一站式合集版硬上限：单对话完成全流程，适配 16K/32K 内网模型
MAX_BUNDLE_CHARS = 12000
# RAG 知识库单切片目标上限（字符）
RAG_CHUNK_MAX_CHARS = 1400
# 手写精简骨架目录：有骨架的 skill，精简版直接读它，不再从 SKILL.md 截断
LITE_SKELETON_REL = 'xinchuang/lite'
REFERENCE_HEADING = "## 参考资料"
REFERENCE_PATH_RE = re.compile(r"`((?:references|assets|scripts)/[^`]+)`")
REFERENCE_TRIMMED_NOTE = "（其余参考文件未附上。）"
STATUS_LABELS = {
    "stable": "Stable（稳定版）",
    "beta": "Beta（测试版）",
    "draft": "Draft（草稿）",
}
CN_DIGITS = "零一二三四五六七八九"
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
PROMPT_OMIT_OPEN_RE = re.compile(r"<!-- prompt:omit(?:: (.+?))? -->")
PROMPT_OMIT_CLOSE = "<!-- /prompt:omit -->"
CODE_LANGS = {".json": "json", ".py": "python", ".yaml": "yaml", ".yml": "yaml", ".csv": "csv"}

# 离线包中跳过的缓存和系统文件；.gongwen（单位画像）和 公文（用户产出）可能含内部信息，也不得打包
JUNK_DIRS = {
    "__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".tox",
    ".venv", "venv", "node_modules", ".gongwen", "公文",
}
JUNK_FILES = {".DS_Store", "Thumbs.db"}
JUNK_SUFFIXES = {".pyc", ".pyo"}
ZIP_DATE = (1980, 1, 1, 0, 0, 0)

# 离线包根目录的文档（存在才打包）
OFFLINE_ROOT_DOCS = ("README.md", "LICENSE", "使用须知.md", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md")
# 离线包里的安装脚本：包内 README.md 的安装步骤指向它们，必须一起打包。路径相对仓库根，包内路径相同。
# .claude-plugin/marketplace.json 是安装器区分核心 skill 与行业包（--pack）的依据，没有它安装器会把全部 skill 都装上。
OFFLINE_INSTALL_FILES = (
    "install.ps1",
    "install.sh",
    "tools/install.py",
    ".claude-plugin/marketplace.json",
)
# 离线使用说明：源文件在 tools/ 下，打包时放在 zip 根目录并改名
OFFLINE_GUIDE_SRC = "tools/offline_readme.md"
OFFLINE_GUIDE_NAME = "离线使用说明.md"


# ---------------------------------------------------------------------------
# 文本处理
# ---------------------------------------------------------------------------

def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def strip_prompt_omissions(text: str) -> str:
    """仅在提示词版中省略标记块，保留代码围栏中的标记示例。"""
    if "prompt:omit" not in text:
        return text
    out: List[str] = []
    opened_at: Optional[int] = None
    fence = ""
    for number, line in enumerate(text.split("\n"), start=1):
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = ""
        elif not fence:
            opening = PROMPT_OMIT_OPEN_RE.fullmatch(line.strip())
            if opening:
                if opened_at is not None:
                    raise ValueError(f"第 {number} 行：prompt:omit 标记不能嵌套（块开始于第 {opened_at} 行）")
                opened_at = number
                if opening.group(1) is not None:
                    out.append(opening.group(1))
                continue
            if line.strip() == PROMPT_OMIT_CLOSE:
                if opened_at is None:
                    raise ValueError(f"第 {number} 行：prompt:omit 结束标记没有对应的开标记")
                opened_at = None
                continue
        if opened_at is None:
            out.append(line)
    if opened_at is not None:
        raise ValueError(f"第 {opened_at} 行：prompt:omit 标记未闭合")
    return "\n".join(out)


def cn_number(n: int) -> str:
    """1 -> 一，12 -> 十二，35 -> 三十五（附录编号用）。"""
    if n <= 0 or n >= 100:
        return str(n)
    if n < 10:
        return CN_DIGITS[n]
    tens, ones = divmod(n, 10)
    head = "十" if tens == 1 else CN_DIGITS[tens] + "十"
    return head + (CN_DIGITS[ones] if ones else "")


def find_first_h1(text: str) -> Tuple[Optional[str], Optional[int]]:
    """返回第一个一级标题（跳过代码块）及其行号（从 0 开始）。"""
    fence: Optional[Tuple[str, int]] = None
    for index, line in enumerate(text.split("\n")):
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1]:
                fence = None
            continue
        if fence is None and line.startswith("# "):
            title = re.sub(r"\s+#+\s*$", "", line[2:]).strip()
            if title:
                return title, index
    return None, None


def _is_cjk(ch: str) -> bool:
    """中日韩文字或全角标点。"""
    return bool(ch) and ("\u3000" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef")


def replace_bundle_paths(text: str, mapping: Dict[str, str]) -> str:
    """把已打包文件的路径替换为"（见附录X）"。

    路径可带反引号；与中文相邻时去掉多余空格，如"按 `references/x.md` 第一条"->"按（见附录一）第一条"。
    """
    if not mapping:
        return text
    alternatives = "|".join(re.escape(p) for p in sorted(mapping, key=len, reverse=True))
    pattern = re.compile(
        r"([ \t]?)(`?)(?<![A-Za-z0-9_./\\-])(" + alternatives + r")(?!\.?[A-Za-z0-9_/\\-])\2([ \t]?)"
    )

    def repl(match: "re.Match[str]") -> str:
        lead, trail = match.group(1), match.group(4)
        prev_ch = text[match.start() - 1] if match.start() > 0 else ""
        next_ch = text[match.end()] if match.end() < len(text) else ""
        if lead and _is_cjk(prev_ch):
            lead = ""
        if trail and _is_cjk(next_ch):
            trail = ""
        return lead + mapping[match.group(3)] + trail

    return pattern.sub(repl, text)


def trim_reference_table(body: str, mapping: Dict[str, str]) -> str:
    """参考资料表中，只指向提示词版未附上的文件（references/、assets/、scripts/ 下）的行无法读取，改为一句说明。

    已打包文件所在的行保留（路径随后替换为"见附录"）；表头和不含文件路径的行保留。只影响提示词版，SKILL.md 本身不变。
    """
    out: List[str] = []
    in_section = False
    dropped = 0
    for line in body.split("\n"):
        if line.startswith("#"):
            if in_section and dropped:
                out.append(REFERENCE_TRIMMED_NOTE)
                out.append("")
                dropped = 0
            in_section = line.strip() == REFERENCE_HEADING
        elif in_section and line.startswith("|"):
            cells = line.split("|")
            paths = REFERENCE_PATH_RE.findall(cells[1]) if len(cells) > 2 else []
            if paths and not any(p in mapping for p in paths):
                dropped += 1
                continue
        out.append(line)
    if in_section and dropped:
        while out and not out[-1].strip():
            out.pop()
        out += ["", REFERENCE_TRIMMED_NOTE]
    return "\n".join(out)


TOC_HEADING = "## 目录"


def strip_toc(text: str) -> str:
    """去掉附录文件里的"## 目录"小节：正文各小节标题都在，提示词版里目录只占字数。跳过代码块。"""
    out: List[str] = []
    in_toc = False
    fence: Optional[Tuple[str, int]] = None
    for line in text.split("\n"):
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1]:
                fence = None
        elif fence is None:
            if line.strip() == TOC_HEADING:
                in_toc = True
                continue
            if in_toc and line.startswith("#"):
                in_toc = False
        if not in_toc:
            out.append(line)
    return "\n".join(out)


def short_title(title: str, name: str) -> str:
    """"综合文稿（gongwen-report）" -> "综合文稿"。"""
    match = re.match(r"^(.*?)\s*[（(]\s*" + re.escape(name) + r"\s*[)）]\s*$", title)
    if match and match.group(1).strip():
        return match.group(1).strip()
    return title


def first_sentence(text: str) -> str:
    match = re.search(r"[。！？!?]", text)
    return text[:match.end()] if match else text


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


# ---------------------------------------------------------------------------
# 单个 skill 的渲染
# ---------------------------------------------------------------------------

@dataclass
class PromptDoc:
    name: str
    title: str
    short_title: str
    summary: str
    text: str
    char_count: int
    is_long: bool
    refined: bool = True  # False：由 SKILL.md 机械截断，没有手写精修


@dataclass
class RenderResult:
    doc: Optional[PromptDoc] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def render_appendix(index: int, rel: str, content: str, mapping: Dict[str, str]) -> str:
    pure = PurePosixPath(rel)
    suffix = pure.suffix.lower()
    label = f"附录{cn_number(index)}"
    if suffix in (".md", ".markdown"):
        if content.startswith("---\n"):
            _fields, body, _errors, has_fm = split_frontmatter(content)
            if has_fm:
                content = body
        title, line_index = find_first_h1(content)
        lines = content.split("\n")
        first_text = next((i for i, line in enumerate(lines) if line.strip()), None)
        if title is not None and line_index == first_text:
            del lines[line_index]  # 文件标题已用作附录小标题
        body = replace_bundle_paths(strip_toc("\n".join(lines)).strip("\n"), mapping)
        heading = title or pure.name
    elif suffix == ".txt":
        body = replace_bundle_paths(content.strip("\n"), mapping)
        heading = pure.name
    else:
        longest = max((len(m.group(0)) for m in re.finditer(r"`+", content)), default=0)
        fence = "`" * max(3, longest + 1)
        body = f"{fence}{CODE_LANGS.get(suffix, '')}\n{content.rstrip(chr(10))}\n{fence}"
        heading = pure.name
    return f"# {label}　{heading}\n\n{body}\n"


def render_header(name: str, title: str, version: str, status: str, char_count: int, is_long: bool) -> str:
    lines = [
        f"> **{title}**（提示词版）",
        ">",
        f"> 版本：{version}　成熟度：{status}　全文约 {char_count} 字符",
        ">",
        "> 使用方法：",
        "> 1. 复制全文，粘贴到对话开头；",
        "> 2. 再说出你的需求；",
        "> 3. 网页版无法运行脚本，自检清单需要人工逐项执行；",
        "> 4. 请勿输入涉密和内部敏感信息。",
    ]
    if is_long:
        lines += [
            ">",
            f"> 注意：全文超过 {LONG_PROMPT_CHARS} 字符，部分网页大模型可能截断或遗忘后文，建议选用支持长文本的模型。",
        ]
    lines += [">", f"> 本文件由 tools/build_prompts.py 根据 skills/{name} 自动生成，请勿手改。"]
    return "\n".join(lines) + "\n\n---\n\n"


HANDOFF_SOURCE = "references/_shared/style/output-format.md"
HANDOFF_HEADING = "## 四、交接卡与转交"


def extract_handoff(text: str) -> str:
    """从 output-format.md 中摘出第四部分"交接卡与转交"，改写为可作附录的独立小节；找不到时返回空串。"""
    lines = text.split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip().startswith(HANDOFF_HEADING)), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = lines[start + 1:end]
    # 三级标题提为二级，与其他附录的层级一致
    section = ["## " + line[4:] if line.startswith("### ") else line for line in section]
    body = "\n".join(section).strip("\n")
    return "# 交接卡与转交（摘自输出格式规范第四部分）\n\n" + body + "\n"


def render_skill(skill_dir: Path) -> RenderResult:
    result = RenderResult()
    name = skill_dir.name
    if not exists_exact(skill_dir, "SKILL.md", want_dir=False):
        result.errors.append("缺少 SKILL.md")
        return result
    try:
        skill_text = strip_prompt_omissions(normalize_newlines((skill_dir / "SKILL.md").read_text(encoding="utf-8")))
    except UnicodeDecodeError:
        result.errors.append("SKILL.md 不是合法的 UTF-8 编码")
        return result
    except ValueError as exc:
        result.errors.append(f"SKILL.md：{exc}")
        return result
    fields, body, _fm_errors, has_fm = split_frontmatter(skill_text)
    if not has_fm:
        result.warnings.append("SKILL.md 缺少 frontmatter，已按全文处理")
        body = skill_text

    manifest, err = load_json_file(skill_dir / "manifest.json")
    if err:
        result.errors.append(f"manifest.json：{err}")
        return result
    if not isinstance(manifest, dict):
        result.errors.append("manifest.json：顶层必须是 JSON 对象")
        return result
    version = manifest.get("version") if isinstance(manifest.get("version"), str) else "未标注"
    status = STATUS_LABELS.get(manifest.get("status"), "未标注")
    bundle = manifest.get("prompt_bundle", [])
    if not isinstance(bundle, list):
        result.errors.append("manifest.json 的 prompt_bundle 必须是数组")
        return result

    mapping: Dict[str, str] = {}
    files: List[Tuple[str, str]] = []
    for index, item in enumerate(bundle, start=1):
        rel, err = normalize_rel_path(item)
        if err:
            result.errors.append(f"prompt_bundle 第 {index} 项：{err}")
            continue
        if rel in mapping:
            result.warnings.append(f"prompt_bundle 重复列出 {rel}，已忽略重复项")
            continue
        if not exists_exact(skill_dir, rel, want_dir=False):
            result.errors.append(f"prompt_bundle 引用的文件不存在（注意大小写）：{rel}")
            continue
        try:
            # utf-8-sig：去掉记事本等工具写入的 BOM，避免混入提示词、影响标题识别
            content = normalize_newlines((skill_dir / rel).read_text(encoding="utf-8-sig"))
            if PurePosixPath(rel).suffix.lower() in (".md", ".markdown"):
                content = strip_prompt_omissions(content)
        except UnicodeDecodeError:
            result.errors.append(f"prompt_bundle 文件不是 UTF-8 文本：{rel}")
            continue
        except ValueError as exc:
            result.errors.append(f"prompt_bundle 文件 {rel}：{exc}")
            continue
        mapping[rel] = f"（见附录{cn_number(len(files) + 1)}）"
        files.append((rel, content))
    if result.errors:
        return result

    # 网页版跨 skill 转交需要交接卡和安装命令（开发规范 D14）。没有整份打包 output-format.md 的，
    # 自动附上它的第四部分"交接卡与转交"，避免各 skill 为此超出字数目标。
    if HANDOFF_SOURCE not in mapping and exists_exact(skill_dir, HANDOFF_SOURCE, want_dir=False):
        try:
            handoff_text = normalize_newlines((skill_dir / HANDOFF_SOURCE).read_text(encoding="utf-8-sig"))
            handoff = extract_handoff(strip_prompt_omissions(handoff_text))
        except ValueError as exc:
            result.errors.append(f"{HANDOFF_SOURCE}：{exc}")
            return result
        if handoff:
            files.append((HANDOFF_SOURCE[:-3] + "-第四部分.md", handoff))

    title = find_first_h1(body)[0] or name
    content = replace_bundle_paths(trim_reference_table(body.strip("\n"), mapping), mapping) + "\n"
    for index, (rel, text) in enumerate(files, start=1):
        content += "\n---\n\n" + render_appendix(index, rel, text, mapping)

    # 信息块中的字数包含信息块本身，迭代到位数稳定为止
    is_long = len(render_header(name, title, version, status, len(content), False)) + len(content) > LONG_PROMPT_CHARS
    count = len(content)
    full = ""
    for _ in range(10):
        full = render_header(name, title, version, status, count, is_long) + content
        if len(full) == count:
            break
        count = len(full)
    if is_long:
        result.warnings.append(f"提示词版共 {count} 字符，超过 {LONG_PROMPT_CHARS}，部分网页大模型可能截断")
    if count > MAX_PROMPT_CHARS:
        result.errors.append(f"提示词版共 {count} 字符，超过硬上限 {MAX_PROMPT_CHARS}，请精简 SKILL.md 或 prompt_bundle 中的重复内容")

    description = fields.get("description", "") if has_fm else ""
    result.doc = PromptDoc(
        name=name,
        title=title,
        short_title=short_title(title, name),
        summary=first_sentence(description.strip()),
        text=full,
        char_count=count,
        is_long=is_long,
    )
    return result


def render_index(docs: List[PromptDoc]) -> str:
    lines = [
        "# 提示词版索引",
        "",
        "本目录由 tools/build_prompts.py 自动生成，请勿手改。"
        "每个文件是一份可直接粘贴到网页大模型（DeepSeek、豆包、Kimi 等）的提示词。",
        "",
        "使用方法：打开对应文件，复制全文粘贴到对话开头，再说出你的需求。"
        "网页版无法运行脚本，自检清单需要人工逐项执行。请勿输入涉密和内部敏感信息。",
        "",
        "| 名称 | 中文名 | 说明 | 字数 | 文件 |",
        "|---|---|---|---:|---|",
    ]
    for doc in docs:
        lines.append(
            f"| {doc.name} | {_escape_cell(doc.short_title)} | {_escape_cell(doc.summary)} "
            f"| {doc.char_count} | [{doc.name}.md]({doc.name}.md) |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 整体构建、比较与写入
# ---------------------------------------------------------------------------

@dataclass
class BuildResult:
    outputs: Dict[str, str] = field(default_factory=dict)  # 文件名 -> 内容
    keep: Set[str] = field(default_factory=set)            # 出错未重建、需保留的旧文件
    docs: List[PromptDoc] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    skill_count: int = 0


def build_all(repo_root: Path) -> BuildResult:
    build = BuildResult()
    skill_dirs = list_skill_dirs(repo_root)
    build.skill_count = len(skill_dirs)
    for skill_dir in skill_dirs:
        name = skill_dir.name
        result = render_skill(skill_dir)
        build.warnings.extend(f"[{name}] {w}" for w in result.warnings)
        if result.doc is not None:  # 字数超限等不影响生成的错误：仍写出提示词版，但整体报错
            build.errors.extend(f"[{name}] {e}" for e in result.errors)
        if result.doc is None:
            build.errors.extend(f"[{name}] {e}" for e in result.errors)
            build.keep.add(f"{name}.md")
            continue
        build.docs.append(result.doc)
        build.outputs[f"{name}.md"] = result.doc.text
    if build.docs:
        build.outputs[INDEX_NAME] = render_index(build.docs)
    if build.errors:
        build.keep.add(INDEX_NAME)
    return build


def _existing_outputs(out_dir: Path) -> List[str]:
    if not out_dir.is_dir():
        return []
    return sorted(p.name for p in out_dir.iterdir() if p.is_file() and p.suffix == ".md")


def check_outputs(repo_root: Path, build: BuildResult) -> List[str]:
    """比较 dist/prompts 与当前源文件，返回差异描述（不写入）。"""
    out_dir = repo_root / PROMPTS_REL
    diffs: List[str] = []
    for fname in sorted(build.outputs):
        path = out_dir / fname
        if not exists_exact(out_dir, fname, want_dir=False):
            diffs.append(f"缺失  {PROMPTS_REL}/{fname}")
        elif not same_text_ignoring_eol(path.read_bytes(), build.outputs[fname]):
            diffs.append(f"不一致  {PROMPTS_REL}/{fname}")
    for fname in _existing_outputs(out_dir):
        if fname not in build.outputs and fname not in build.keep:
            diffs.append(f"多余  {PROMPTS_REL}/{fname}")
    return diffs


def write_outputs(repo_root: Path, build: BuildResult) -> List[str]:
    out_dir = repo_root / PROMPTS_REL
    actions: List[str] = []
    for fname in _existing_outputs(out_dir):  # 只删除 dist/prompts 下的旧 .md
        if fname not in build.outputs and fname not in build.keep:
            (out_dir / fname).unlink()
            actions.append(f"删除  {PROMPTS_REL}/{fname}")
    for fname in sorted(build.outputs):
        path = out_dir / fname
        text = build.outputs[fname]
        if path.is_file() and same_text_ignoring_eol(path.read_bytes(), text):
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        actions.append(f"写入  {PROMPTS_REL}/{fname}")
    return actions


# ---------------------------------------------------------------------------
# 国产信创与政务内网编译产物（精简提示词版 / 一站式合集版 / RAG 知识库切片包）
# ---------------------------------------------------------------------------

LITE_DROP_HEADINGS = ("## 参考资料", "## 角色适配", "## 单位差异")
LITE_GUARDRAILS = (
    "【六条红线】1.涉密先停（最高优先级）：凡材料出现密级标识（绝密/机密/秘密/★）或“内部资料”“工作秘密”“不得外传”等字样，"
    "立即停止全部写作任务——严禁起草、严禁改写、严禁复述或摘录原文任何内容，也不要输出正文和【起草说明】，只回复一句保密停止提醒即结束；个人隐私须先脱敏。"
    "2.事实只来自用户：严禁编造数据、案例、文号、引语，缺项标【待补】，存疑标【待核实】。"
    "3.正文干净：正文无免责声明和 AI 自述，提示放文末【起草说明】。"
    "4.默认做减法：开门见山，按指定字数写，不照抄上级、不注水。"
    "5.规则可溯源：按《条例》与 GB/T 9704/15834/15835 核对并注明依据。"
    "6.辅助不代笔：对照检查、述职等缺本人事例只出提纲。\n"
)

# 高频一站式单对话合集定义：(输出文件名, 中文名, 适用场景, 组合的 skill 列表)
BUNDLE_SPECS: Tuple[Tuple[str, str, str, Tuple[str, ...]], ...] = (
    (
        "01-法定公文一站式.md",
        "法定公文一站式（起草 + 去腔 + 核稿）",
        "通知、请示、报告、函、通报、批复、意见、签报：单对话完成定文种、起草、去防御/AI腔与八关核稿",
        ("gongwen-draft", "gongwen-direct", "gongwen-humanize", "gongwen-review"),
    ),
    (
        "02-综合材料一站式.md",
        "综合材料一站式（提纲 + 总结汇报 + 去腔 + 核稿）",
        "年终总结、工作计划、汇报、调研报告、述职、经验材料：单对话完成台账、标题、起草与审校",
        ("gongwen-report", "gongwen-title", "gongwen-direct", "gongwen-humanize", "gongwen-review"),
    ),
    (
        "03-核稿润色一站式.md",
        "成稿体检与润色一站式（去防御 + 去AI味 + 改稿 + 八关核稿）",
        "已有初稿或 AI 稿：单对话完成压缩/转译、去防御腔、去 AI 腔与 P0/P1/P2 八关体检",
        ("gongwen-direct", "gongwen-humanize", "gongwen-polish", "gongwen-review"),
    ),
    (
        "04-落实整改一站式.md",
        "上级文件落实与巡察整改一站式",
        "上级来文拆任务、写落实方案，或巡察/审计/督查整改方案、台账对账与进展报告",
        ("gongwen-implement", "gongwen-rectify", "gongwen-review"),
    ),
)

RAG_SHARED_SOURCES: Tuple[Tuple[str, str], ...] = (
    ("guardrails.md", "红线与保密"),
    ("rules/tiaoli.md", "公文处理条例"),
    ("rules/doc-types.md", "文种决策与辨析"),
    ("rules/gbt9704.md", "国标格式9704"),
    ("rules/gbt15834.md", "标点规范15834"),
    ("rules/gbt15835.md", "数字规范15835"),
    ("rules/jianfu.md", "基层减负规定"),
    ("rules/data-expression.md", "数据表述规范"),
    ("rules/normative-terms.md", "规范用词与机构旧称"),
    ("style/ai-tone.md", "去AI腔规范"),
    ("style/defensive.md", "去防御腔规范"),
    ("style/output-format.md", "输出与交接规范"),
    ("profiles/roles.md", "角色模式"),
    ("profiles/calendar.md", "写作日历"),
)


def _strip_sections(body: str, drop_prefixes: Sequence[str]) -> str:
    """按二级标题剔除不适合精简版/合集版的次要小节（跳过代码块）。"""
    out: List[str] = []
    skipping = False
    fence: Optional[Tuple[str, int]] = None
    for line in body.split("\n"):
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1]:
                fence = None
        elif fence is None and line.startswith("## "):
            heading = line.strip()
            skipping = any(heading.startswith(p) for p in drop_prefixes)
        if not skipping:
            out.append(line)
    return "\n".join(out)


def _strip_script_and_path_refs(text: str) -> str:
    """将面向 Agent 的相对路径和脚本命令改写为适合政务网页模型的纯文本表述。"""
    text = re.sub(r"`(?:references|assets)/[^`]+`", "对应规则", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _truncate_at_line(text: str, limit: int, suffix: str) -> str:
    if len(text) <= limit:
        return text
    budget = max(0, limit - len(suffix))
    cut = text[:budget]
    nl = cut.rfind("\n")
    if nl > budget // 2:
        cut = cut[:nl]
    return cut.rstrip() + suffix


def render_lite_skill(skill_dir: Path) -> Optional[PromptDoc]:
    """为单个 skill 编译 <= 4000 字的政务内网精简提示词版。"""
    name = skill_dir.name
    if not exists_exact(skill_dir, "SKILL.md", want_dir=False):
        return None
    raw = normalize_newlines((skill_dir / "SKILL.md").read_text(encoding="utf-8-sig"))
    fields, body, _errs, has_fm = split_frontmatter(raw)
    if not has_fm:
        body = raw
    title = find_first_h1(body)[0] or name
    skeleton = skill_dir.parent.parent / LITE_SKELETON_REL / (name + '.md')
    if skeleton.is_file():  # 手写骨架：直接读取，不截断；超过字数上限由 xinchuang_errors 报错
        label = short_title(title, name)
        head = '# %s（内网精简提示词版）\n\n%s\n' % (label, LITE_GUARDRAILS)
        text = head + normalize_newlines(skeleton.read_text(encoding='utf-8-sig')).strip() + '\n'
        desc = fields.get('description', '') if has_fm else ''
        return PromptDoc(name, title, label, first_sentence(desc.strip()), text, len(text), False)
    # 移除一级标题和署名引用块，保留核心规则
    lines = body.split("\n")
    cleaned: List[str] = []
    skipped_h1 = False
    for line in lines:
        if not skipped_h1 and line.startswith("# "):
            skipped_h1 = True
            continue
        if skipped_h1 and not cleaned and (not line.strip() or line.startswith("> 作者：")):
            continue
        cleaned.append(line)
    core = _strip_sections("\n".join(cleaned), LITE_DROP_HEADINGS)
    core = _strip_script_and_path_refs(core)
    header = (
        f"# {title}（内网精简提示词版）\n\n"
        f"> 面向政务内网大模型系统提示词框（<= {MAX_LITE_CHARS} 字符）。本份未精修：由 SKILL.md 机械截断而成，可能残留脚本命令和路径引用，仅作应急。\n\n"
        f"{LITE_GUARDRAILS}\n"
    )
    tail_note = "\n\n（注：精简版已省略次要示例；完整规则见知识库切片包或 dist/prompts/。）\n"
    full = _truncate_at_line(header + core + "\n", MAX_LITE_CHARS, tail_note)
    if not full.endswith("\n"):
        full += "\n"
    desc = fields.get("description", "") if has_fm else ""
    return PromptDoc(
        name=name,
        title=title,
        short_title=short_title(title, name),
        summary=first_sentence(desc.strip()),
        text=full,
        char_count=len(full),
        is_long=False,
        refined=False,
    )


def build_lite_prompts(repo_root: Path) -> Dict[str, str]:
    outputs: Dict[str, str] = {}
    docs: List[PromptDoc] = []
    for skill_dir in list_skill_dirs(repo_root):
        doc = render_lite_skill(skill_dir)
        if doc is None:
            continue
        docs.append(doc)
        outputs[f"{doc.name}.md"] = doc.text
    if docs:
        lines = [
            "# 政务内网精简提示词版索引（<= 4000 字符）",
            "",
            "适用于单位内网 DeepSeek / Qwen / 政务大模型等系统提示词框有字数限制（4K～8K）的场景。",
            "如需完整条款检索，建议配合 `dist/rag-kb/` 知识库切片包导入 Dify / FastGPT / MaxKB 使用。",
            "",
            "| 名称 | 中文名 | 说明 | 字数 | 文件 |",
            "|---|---|---|---:|---|",
        ]
        for d in docs:
            lines.append(
                f"| {d.name} | {_escape_cell(d.short_title)} | {_escape_cell(d.summary)} "
                f"| {d.char_count} | [{d.name}.md]({d.name}.md){'' if d.refined else '（未精修，机械截断，仅应急）'} |"
            )
        outputs[INDEX_NAME] = "\n".join(lines) + "\n"
    return outputs


def _demote_headings(text: str) -> str:
    """手写骨架的二级标题降为三级，放进合集的“环节”之下（骨架里没有代码块）。"""
    return re.sub(r'(?m)^## ', '### ', text)


def build_bundle_prompts(repo_root: Path) -> Dict[str, str]:
    """生成高频单对话一站式合集：只用手写骨架拼装，不含交接卡、脚本命令和路径引用。

    成员里有 skill 还没有手写骨架的，整份合集不生成，在索引里列为待精修，不拿机械截断版凑数。
    """
    outputs: Dict[str, str] = {}
    rows: List[Tuple[str, str, str, int]] = []
    pending: List[Tuple[str, str]] = []
    skeleton_dir = repo_root / LITE_SKELETON_REL
    for fname, title, scene, members in BUNDLE_SPECS:
        missing = [m for m in members if not (skeleton_dir / (m + '.md')).is_file()]
        if missing:
            pending.append((title, '、'.join(missing)))
            continue
        parts: List[str] = [
            '# %s\n' % title,
            '> 适用场景：%s' % scene,
            '> 使用方式：粘贴为政务内网大模型的系统提示词或首条消息，在一个对话内连续完成，不用切换对话。\n',
            LITE_GUARDRAILS,
            '## 执行顺序（同一对话内连续完成）\n',
            '1. 先判保密与缺项：遇密级、内部资料立即停止；缺数据、人名、文号标【待补】，严禁编造。',
            '2. 下面各环节依次在内部完成，最终只输出一份结果：有成稿就输出正文和【起草说明】；去腔、核稿中发现的、仍需用户处理的事项并入【起草说明】，不单独出清单。用户明确只要意见、不要改稿时，才按核稿环节的格式输出问题清单。',
            '3. 各环节里的“输出格式”“自检”是内部工作要求，不是要分别输出的内容。',
            '4. 没有脚本可用，逐项对照：发文字号六角括号〔〕、成文日期不编虚位、层次序号 一、（一）1.（1）、标点和数字规范。\n',
        ]
        for idx, member in enumerate(members, start=1):
            doc = render_lite_skill(repo_root / 'skills' / member)
            label = doc.short_title if doc else member
            body = normalize_newlines((skeleton_dir / (member + '.md')).read_text(encoding='utf-8-sig')).strip()
            parts.append('---\n\n## 第%s环节：%s\n\n%s\n' % (cn_number(idx), label, _demote_headings(body)))
        full = '\n'.join(parts)
        if not full.endswith('\n'):
            full += '\n'
        outputs[fname] = full
        rows.append((fname, title, scene, len(full)))
    if rows or pending:
        lines = [
            '# 高频一站式单对话合集版索引',
            '',
            '专为政务内网网页大模型设计：一份提示词覆盖完整写作链路，不用来回切换对话。合集只由手写骨架拼成，不含脚本命令和路径引用；成员还没有骨架的合集暂不生成。',
            '',
            '| 合集名称 | 适用场景 | 字数 | 文件 |',
            '|---|---|---:|---|',
        ]
        for fname, title, scene, count in rows:
            lines.append('| %s | %s | %d | [%s](%s) |' % (_escape_cell(title), _escape_cell(scene), count, fname, fname))
        for title, missing_names in pending:
            lines.append('| %s | 待精修：%s 还没有手写骨架，暂不生成 | - | - |' % (_escape_cell(title), missing_names))
        outputs[INDEX_NAME] = '\n'.join(lines) + '\n'
    return outputs


def xinchuang_errors(repo_root: Path, sets: Sequence[Tuple[str, Dict[str, str]]]) -> List[str]:
    """精简版、合集版超过字数上限，或骨架没有对应 skill 时报错；手写骨架不截断，超限必须改骨架。"""
    errors: List[str] = []
    limits = {PROMPTS_LITE_REL: MAX_LITE_CHARS, PROMPTS_BUNDLES_REL: MAX_BUNDLE_CHARS}
    for rel_dir, files in sets:
        limit = limits.get(rel_dir)
        if not limit:
            continue
        for name, text in sorted(files.items()):
            if name != INDEX_NAME and len(text) > limit:
                errors.append('%s/%s 共 %d 字符，超过上限 %d' % (rel_dir, name, len(text), limit))
    skeleton_dir = repo_root / LITE_SKELETON_REL
    if skeleton_dir.is_dir():
        names = {d.name for d in list_skill_dirs(repo_root)}
        for path in sorted(skeleton_dir.glob('*.md')):
            if path.stem not in names:
                errors.append('%s/%s 没有对应的 skill' % (LITE_SKELETON_REL, path.name))
    return errors


def _chunk_markdown(source_label: str, category: str, text: str, max_chars: int = RAG_CHUNK_MAX_CHARS) -> List[Tuple[str, str]]:
    """按二级/三级标题把 Markdown 拆成带语义锚点头的 RAG 知识切片。"""
    text = normalize_newlines(text).strip()
    if not text:
        return []
    sections: List[Tuple[str, List[str]]] = []
    cur_heading = "概述"
    cur_lines: List[str] = []
    fence: Optional[Tuple[str, int]] = None
    for line in text.split("\n"):
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1]:
                fence = None
        elif fence is None and (line.startswith("## ") or line.startswith("### ")):
            if any(x.strip() for x in cur_lines):
                sections.append((cur_heading, cur_lines))
            cur_heading = line.lstrip("#").strip()
            cur_lines = []
            continue
        cur_lines.append(line)
    if any(x.strip() for x in cur_lines):
        sections.append((cur_heading, cur_lines))

    chunks: List[Tuple[str, str]] = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        meta = f"[知识来源：{source_label} | 分类：{category} | 小节：{heading}]\n\n"
        if len(meta) + len(body) <= max_chars:
            chunks.append((heading, meta + body + "\n"))
            continue
        # 按段落切分超长小节，保持每片独立可读
        buf: List[str] = []
        buf_len = len(meta)
        part = 1
        for para in re.split(r"\n{2,}", body):
            p = para.strip()
            if not p:
                continue
            if buf and buf_len + len(p) + 2 > max_chars:
                chunks.append((f"{heading}（续{part}）", meta + "\n\n".join(buf) + "\n"))
                part += 1
                buf = [p]
                buf_len = len(meta) + len(p)
            else:
                buf.append(p)
                buf_len += len(p) + 2
        if buf:
            label = heading if part == 1 else f"{heading}（续{part}）"
            chunks.append((label, meta + "\n\n".join(buf) + "\n"))
    return chunks


def _dify_dsl_template() -> str:
    return """app:
  description: 面向党政机关、事业单位、国企内网部署的公文写作助手（配合 dist/rag-kb/chunks 知识库使用）
  icon: "📄"
  icon_background: "#E8EEF5"
  mode: chat
  name: 政务公文写作助手（dyz-gongwen-skills）
kind: app
model_config:
  agent_mode:
    enabled: false
  annotation_reply:
    enabled: false
  dataset_configs:
    datasets:
      datasets: []
    reranking_enable: true
    retrieval_model: multiple
    top_k: 6
  model:
    completion_params:
      temperature: 0.2
    mode: chat
    name: deepseek-r1-32b
    provider: openai_api_compatible
  pre_prompt: |
    你是单位内网公文写作助手，严格遵守六条写作红线与 GB/T 9704、GB/T 15834、GB/T 15835 规范：
    1. 保密先于生成：发现密级标识（绝密/机密/秘密/★）、“内部资料”“工作秘密”字样立即停止，不摘录、不改写。
    2. 事实只来自用户：严禁编造数据、案例、人名、文号、引语；缺失项标【待补：说明】，存疑项标【待核实：说明】。
    3. 正文干净、提示外置：正文禁止出现免责声明、AI 自述、Markdown 符号；核查意见放文末【起草说明】。
    4. 默认做减法：开门见山，按指定字数写，不照抄上位文件、不注水。
    5. 规则可溯源：检索已挂载的《政务公文知识库》条款，文种、标点、数字、格式问题须注明条款依据。
    6. 辅助不代笔：对照检查、述职等须本人亲历的材料，未提供真实事例时只出提纲与填写指引。
    使用说明：导入本 DSL 后，请在 Dify 中新建知识库并上传 dist/rag-kb/chunks/ 下的全部 Markdown 切片（按自定义分隔符 `---` 分段），再关联至本应用。
  suggested_questions:
    - "帮我判断这份材料该用请示还是函，并起草初稿"
    - "把这篇 AI 初稿去掉 AI 腔和防御腔，数字和事实一个不动"
    - "按八关核稿检查这份通知，输出 P0/P1/P2 清单"
version: 0.1.5
"""


# 各平台导入时填的分段长度，须大于切片目标上限 RAG_CHUNK_MAX_CHARS
RAG_SPLIT_LEN = 1600
FASTGPT_QA_HEADER = ('q', 'a')
# MaxKB QA 模板表头：转引自其公开 csv 模板（社区文章），导入前请与界面下载的模板核对
MAXKB_QA_HEADER = ('分段标题（选填）', '分段内容（必填，问题答案）', '问题（选填，单元格内一行一个）')
_NL = chr(10)


def _csv_text(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """标准库 csv 转义，行结束符 LF；开头放 U+FEFF（UTF-8 BOM），Excel 打开中文不乱码。"""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator=_NL)
    writer.writerow(header)
    writer.writerows(rows)
    return chr(0xFEFF) + buf.getvalue()


def _fastgpt_readme() -> str:
    return _NL.join([
        '# FastGPT 导入包',
        '',
        '`qa-import.csv` 由 `../chunks/` 下的切片生成：每个小节一行，`q` 是小节标题，`a` 是小节正文（顶部保留「知识来源 | 分类 | 小节」锚点）。',
        '',
        '## 文件格式',
        '',
        '依据 FastGPT 官方文档「结构化表格导入规范」：',
        '',
        '- 首行是表头，本文件只用 `q`、`a` 两列，二者不能同时为空。',
        '- 可选的 `index`（或 `indexes`）列可重复，用来给同一条数据补充其他问法；`metadata` 列至多一列，填 JSON。本文件没有用这两种列。',
        '- 单次只能导入 1 个文件，大小不超过 50 MB。',
        '- 本文件编码 UTF-8，开头带 BOM（U+FEFF），行结束符 LF；含逗号、双引号、换行的字段已按 RFC 4180 用双引号包裹。',
        '- 官方文档写的是“推荐 UTF-8 无 BOM”。如果导入提示「文件格式异常」，先用文本编辑器把本文件另存为「UTF-8 无 BOM」再试。',
        '',
        '## 导入步骤',
        '',
        '1. 新建知识库，选择索引模型和文件处理模型。',
        '2. 进入该知识库，点右上角「新建/导入」→「模版导入」。',
        '3. 选择 `qa-import.csv`，确认导入。系统在后台创建集合并生成向量与全文索引。',
        '4. 用知识库的「搜索测试」问几个条款类问题，确认能命中。',
        '5. 新建应用并关联该知识库，系统提示词取 `../dify-app-template.yml` 里的 `pre_prompt`。',
        '',
        '界面名称随版本可能不同，以实际界面为准。',
        '',
        '## 分段设置',
        '',
        '- 模版导入不分段：一行就是一条数据，没有分段长度和分隔符要填。',
        f'- 如果改走“上传文件”：上传 `../chunks/` 下的 `.md`，分段方式以实际界面为准；能自定义分隔符时填 `---`，长度填 {RAG_SPLIT_LEN}。这一路本包没有核实过。',
    ]) + _NL


def _maxkb_readme() -> str:
    return _NL.join([
        '# MaxKB 导入包',
        '',
        '两种方式二选一，不要在同一个文档里混用。界面名称随版本可能不同，以实际界面为准。',
        '',
        '## 方式一：上传 Markdown 切片（推荐）',
        '',
        '1. 打开「知识库」，点「创建知识库」，类型选「通用型」，填写名称并选择向量模型。',
        '2. 在该知识库里上传文档，选择 `../chunks/` 下全部 `.md` 文件。官方默认每次最多 50 个文件、单个不超过 100 MB。',
        f'3. 分段规则选「高级分段」：分段标识符手动输入 `---`，分段长度填 {RAG_SPLIT_LEN}（官方允许 50 至 4096）。自动清洗按需开启；要保留条款里的空行和缩进就关闭。',
        f'4. 在分段预览里核对：每个分段以「[知识来源 | 分类 | 小节]」锚点开头，切片目标上限为 {RAG_CHUNK_MAX_CHARS} 字符。确认后开始导入。',
        '5. 创建应用并关联该知识库，系统提示词取 `../dify-app-template.yml` 里的 `pre_prompt`。',
        '',
        '## 方式二：导入 QA 问答对',
        '',
        '1. 在通用型知识库里上传文档，类型选「QA 问答对」，选择本目录的 `qa-import.csv`。',
        '2. QA 文件的每条记录自动成为一个分段，不需要设置分段标识符和长度。',
        '3. 表头三列：分段标题（选填）、分段内容（必填）、问题（选填，单元格内一行一个）。本文件三列都填：标题和问题是小节标题，内容是带来源锚点的小节正文。',
        '4. 表头文字转引自 MaxKB 公开的 CSV 模板。如果导入提示格式不符，先在界面下载官方 QA 模板，与本文件核对表头后再导入。',
        '5. 文件编码 UTF-8，开头带 BOM，行结束符 LF。',
    ]) + _NL


def _coze_readme() -> str:
    return _NL.join([
        '# 扣子（Coze Studio 开源版）导入包',
        '',
        '扣子的文本知识库不需要专用文件，直接上传 `../chunks/` 下的 `.md`。界面名称随版本可能不同，以实际界面为准。',
        '',
        '## 前置条件',
        '',
        '- 知识库依赖 Embedding 服务和向量库（默认 Milvus），要先在部署配置里接好内网 Embedding。',
        '- 据社区文章，自建 Embedding 走 HTTP 方式时必须符合扣子自己的接口协议，暂不支持 Ollama、Xinference 协议。你所用版本是否已变化，以官方说明为准。',
        '',
        '## 导入步骤',
        '',
        '1. 进入「资源库」，新建资源，选「知识库」，格式选「文本格式」，导入类型选「本地文档」。',
        '2. 上传 `../chunks/` 下的 `.md` 文件（文本知识库支持 PDF、TXT、DOC、DOCX、MD）。',
        '3. 在创建设置页，文档解析策略选「快速解析」（内容是纯文本），分段策略选「自定义」。',
        f'4. 自定义分段：分段标识符填 `---`，分段最大长度填 {RAG_SPLIT_LEN}，分段重叠度填 0。若界面上限低于 {RAG_SPLIT_LEN}，填界面允许的最大值。',
        '5. 进入分段预览，核对每个分段以「[知识来源 | 分类 | 小节]」锚点开头。边界不对说明标识符没有生效，回到上一步调整。',
        '6. 确认后等待处理完成，在智能体或工作流中添加该知识库，系统提示词取 `../dify-app-template.yml` 里的 `pre_prompt`。',
        '',
        '## 预览不对时的备选',
        '',
        '改用「表格格式」知识库导入 `../fastgpt/qa-import.csv`：表格知识库按行分段，一行一个片段，不需要分段设置；在表结构配置里选 `q` 列作索引列，具体选项以实际界面为准。',
    ]) + _NL


def build_rag_kb(repo_root: Path) -> Dict[str, str]:
    """构建 Dify / FastGPT / MaxKB / 扣子 政务知识库切片包。"""
    outputs: Dict[str, str] = {}
    chunk_files: List[Tuple[str, str, int]] = []
    # shortcut: q 直接用小节标题，同名标题（如“概述”）会重复；需要区分时改成“分类：标题”
    qa_pairs: List[Tuple[str, str]] = []  # (小节标题, 带锚点的小节正文)
    shared_dir = repo_root / "shared"

    # 1. 共享规则、红线、文风与角色画像
    idx = 1
    for rel, category in RAG_SHARED_SOURCES:
        p = shared_dir / rel
        if not p.is_file():
            continue
        raw = p.read_text(encoding="utf-8-sig")
        chunks = _chunk_markdown(f"shared/{rel}", category, raw)
        if not chunks:
            continue
        fname = f"chunks/{idx:02d}-{Path(rel).stem}.md"
        joined = "\n---\n\n".join(body.strip() for _, body in chunks) + "\n"
        outputs[fname] = joined
        qa_pairs.extend((heading, body.strip()) for heading, body in chunks)
        chunk_files.append((fname, category, len(chunks)))
        idx += 1

    # 2. 7 类单位画像
    units_dir = shared_dir / "profiles" / "units"
    if units_dir.is_dir():
        unit_chunks: List[str] = []
        for up in sorted(units_dir.glob("*.md")):
            raw = up.read_text(encoding="utf-8-sig")
            for heading, body in _chunk_markdown(f"units/{up.name}", f"单位画像-{up.stem}", raw):
                unit_chunks.append(body.strip())
                qa_pairs.append((heading, body.strip()))
        if unit_chunks:
            fname = f"chunks/{idx:02d}-unit-profiles.md"
            outputs[fname] = "\n---\n\n".join(unit_chunks) + "\n"
            chunk_files.append((fname, "7类单位画像", len(unit_chunks)))
            idx += 1

    # 3. 各 skill 核心工作流切片（复用精简版，控制知识库总噪声）
    skill_chunks: List[str] = []
    for skill_dir in list_skill_dirs(repo_root):
        doc = render_lite_skill(skill_dir)
        if doc is None:
            continue
        for heading, body in _chunk_markdown(doc.name, f"技能规范-{doc.short_title}", doc.text):
            skill_chunks.append(body.strip())
            qa_pairs.append((heading, body.strip()))
    if skill_chunks:
        fname = f"chunks/{idx:02d}-skills-workflows.md"
        outputs[fname] = "\n---\n\n".join(skill_chunks) + "\n"
        chunk_files.append((fname, "各公文技能工作流", len(skill_chunks)))

    if not chunk_files:
        return {}

    outputs["dify-app-template.yml"] = _dify_dsl_template()
    outputs['fastgpt/qa-import.csv'] = _csv_text(FASTGPT_QA_HEADER, qa_pairs)
    outputs['fastgpt/README.md'] = _fastgpt_readme()
    outputs['maxkb/qa-import.csv'] = _csv_text(MAXKB_QA_HEADER, [(h, b, h) for h, b in qa_pairs])
    outputs['maxkb/README.md'] = _maxkb_readme()
    outputs['coze/README.md'] = _coze_readme()
    total_chunks = sum(c for _, _, c in chunk_files)
    readme = [
        "# 政务内网 RAG 知识库切片包（Dify / FastGPT / MaxKB / 扣子私有版）",
        "",
        f"本目录由 `tools/build_prompts.py --xinchuang` 自动生成，共 {len(chunk_files)} 个切片文件、{total_chunks} 个标准知识片。",
        "每个切片均以 `---` 分隔，顶部带 `[知识来源 | 分类 | 小节]` 语义锚点，无需二次清洗即可直接入库。",
        "",
        '## 一、平台对照',
        '',
        '| 平台 | 用哪个文件 | 分段怎么设 | 详细步骤 |',
        '|---|---|---|---|',
        f'| Dify | `chunks/` 下全部 `.md`；应用模板 `dify-app-template.yml` | 自定义分段，标识符 `---`，最大分段长度 {RAG_SPLIT_LEN}，重叠长度 0 | 本文第二节 |',
        '| FastGPT | `fastgpt/qa-import.csv` | 模版导入，不分段，一行一条数据（`q`、`a` 两列） | `fastgpt/README.md` |',
        f'| MaxKB | `chunks/` 下全部 `.md`；或 QA 文件 `maxkb/qa-import.csv` | 高级分段，标识符 `---`，分段长度 {RAG_SPLIT_LEN}；QA 文件不用分段 | `maxkb/README.md` |',
        f'| 扣子（Coze Studio 开源版） | `chunks/` 下全部 `.md` | 文本知识库自定义分段，标识符 `---`，最大长度 {RAG_SPLIT_LEN}，重叠度 0，以实际界面为准 | `coze/README.md` |',
        '',
        '## 二、导入方法',
        "",
        "### Dify（私有化内网版）",
        "1. 左侧「知识库」→「创建知识库」→ 批量上传 `chunks/` 下的全部 `.md` 文件。",
        "2. 分段设置选「自定义」，分段标识符填 `---`，最大分段长度设 `1600`，重叠长度 `0`。",
        "3. 左侧「工作室」→「导入 DSL 文件」，选择 `dify-app-template.yml`，在上下文中关联刚建好的知识库，切换为本单位内网模型即可发布给全单位使用。",
        "",
        '### FastGPT / MaxKB / 扣子',
        '1. 各平台的导入步骤、分段设置和注意事项见 `fastgpt/README.md`、`maxkb/README.md`、`coze/README.md`。',
        '2. FastGPT 用 `fastgpt/qa-import.csv`；MaxKB 上传 `chunks/` 下的 `.md`（高级分段填 `---`），或导入 `maxkb/qa-import.csv`；扣子上传 `chunks/` 下的 `.md`。',
        "3. 新建应用，将 `dist/prompts-lite/gongwen.md` 或 `dify-app-template.yml` 中的 `pre_prompt` 粘贴为系统提示词，关联知识库即可。",
        "",
        '## 三、切片清单',
        "",
        "| 文件 | 主题 | 切片数 |",
        "|---|---|---:|",
    ]
    for fname, cat, cnt in chunk_files:
        readme.append(f"| `{fname}` | {cat} | {cnt} |")
    outputs[INDEX_NAME] = "\n".join(readme) + "\n"
    return outputs


def _check_dir_outputs(repo_root: Path, rel_dir: str, expected: Dict[str, str]) -> List[str]:
    """比较 rel_dir 下磁盘文件与 expected，返回差异列表。"""
    base = repo_root / rel_dir
    diffs: List[str] = []
    for rel, text in sorted(expected.items()):
        path = base / rel
        if not path.is_file():
            diffs.append(f"缺失  {rel_dir}/{rel}")
        elif not same_text_ignoring_eol(path.read_bytes(), text):
            diffs.append(f"不一致  {rel_dir}/{rel}")
    if base.is_dir():
        for dirpath, _dirnames, filenames in os.walk(base):
            cur = Path(dirpath)
            for fname in sorted(filenames):
                p = cur / fname
                rel = p.relative_to(base).as_posix()
                if rel not in expected:
                    diffs.append(f"多余  {rel_dir}/{rel}")
    return diffs


def _write_dir_outputs(repo_root: Path, rel_dir: str, expected: Dict[str, str]) -> List[str]:
    base = repo_root / rel_dir
    actions: List[str] = []
    if base.is_dir():
        for dirpath, _dirnames, filenames in os.walk(base):
            cur = Path(dirpath)
            for fname in sorted(filenames):
                p = cur / fname
                rel = p.relative_to(base).as_posix()
                if rel not in expected:
                    p.unlink()
                    actions.append(f"删除  {rel_dir}/{rel}")
    for rel, text in sorted(expected.items()):
        path = base / rel
        if path.is_file() and same_text_ignoring_eol(path.read_bytes(), text):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        actions.append(f"写入  {rel_dir}/{rel}")
    return actions


# ---------------------------------------------------------------------------
# 离线包
# ---------------------------------------------------------------------------

def offline_version(repo_root: Path) -> Tuple[str, Optional[str]]:
    """从 marketplace.json 的 metadata.version 取版本号，返回 (版本, 警告)。"""
    path = repo_root / ".claude-plugin" / "marketplace.json"
    if not path.is_file():
        return "0.0.0", "未找到 .claude-plugin/marketplace.json，离线包版本号使用 0.0.0"
    data, err = load_json_file(path)
    if err:
        return "0.0.0", f"marketplace.json {err}，离线包版本号使用 0.0.0"
    metadata = data.get("metadata") if isinstance(data, dict) else None
    version = metadata.get("version") if isinstance(metadata, dict) else None
    if not isinstance(version, str) or not re.fullmatch(r"[0-9A-Za-z.+-]+", version):
        return "0.0.0", "marketplace.json 未设置有效的 metadata.version，离线包版本号使用 0.0.0"
    return version, None


def collect_offline_files(repo_root: Path, *, include_wheelhouse: bool = True) -> List[Tuple[str, Path]]:
    import build_wheelhouse

    files: List[Tuple[str, Path]] = []
    for top in ("skills", PROMPTS_REL, PROMPTS_LITE_REL, PROMPTS_BUNDLES_REL, RAG_KB_REL, "xinchuang"):
        base = repo_root / top
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in JUNK_DIRS)
            current = Path(dirpath)
            for name in sorted(filenames):
                if name in JUNK_FILES or Path(name).suffix in JUNK_SUFFIXES:
                    continue
                path = current / name
                files.append((f"{top}/{path.relative_to(base).as_posix()}", path))
    if include_wheelhouse:
        files.extend(build_wheelhouse.collect_wheelhouse(repo_root))
    for name in OFFLINE_ROOT_DOCS + OFFLINE_INSTALL_FILES:
        path = repo_root / name
        if path.is_file():
            files.append((name, path))
    guide = repo_root / OFFLINE_GUIDE_SRC
    if guide.is_file():
        files.append((OFFLINE_GUIDE_NAME, guide))
    return sorted(files, key=lambda item: item[0])


def offline_missing(repo_root: Path) -> List[str]:
    """离线包应带而仓库里找不到的文件（安装脚本和离线使用说明）。根目录文档缺失不提示，沿用旧行为。"""
    wanted = list(OFFLINE_INSTALL_FILES) + [OFFLINE_GUIDE_SRC]
    return [rel for rel in wanted if not (repo_root / rel).is_file()]


def _build_xinchuang_virtual(repo_root: Path, existing: Set[str]) -> List[Tuple[str, bytes]]:
    """当磁盘上尚未运行 --xinchuang 时，为离线包在内存中补齐精简版、合集版与 RAG 切片。"""
    extra: List[Tuple[str, bytes]] = []
    if not any(n.startswith(PROMPTS_LITE_REL + "/") for n in existing):
        for rel, text in sorted(build_lite_prompts(repo_root).items()):
            extra.append((f"{PROMPTS_LITE_REL}/{rel}", text.encode("utf-8")))
    if not any(n.startswith(PROMPTS_BUNDLES_REL + "/") for n in existing):
        for rel, text in sorted(build_bundle_prompts(repo_root).items()):
            extra.append((f"{PROMPTS_BUNDLES_REL}/{rel}", text.encode("utf-8")))
    if not any(n.startswith(RAG_KB_REL + "/") for n in existing):
        for rel, text in sorted(build_rag_kb(repo_root).items()):
            extra.append((f"{RAG_KB_REL}/{rel}", text.encode("utf-8")))
    return extra


def write_offline_zip(repo_root: Path, version: str, *, include_wheelhouse: bool = True) -> Tuple[Path, int]:
    """生成离线包（含安全自查报告与 SHA256SUMS.txt）；固定时间戳与权限，保证确定性输出。"""
    import security_audit

    out_dir = repo_root / OFFLINE_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"dyz-gongwen-skills-offline-{version}.zip"
    tmp = target.with_name(target.name + ".tmp")

    disk_files = collect_offline_files(repo_root, include_wheelhouse=include_wheelhouse)
    entries: List[Tuple[str, bytes]] = [(arc, p.read_bytes()) for arc, p in disk_files]
    existing = {arc for arc, _ in entries}
    entries.extend(_build_xinchuang_virtual(repo_root, existing))

    # 对随包 .py 执行零外联 AST 静态审计，附《安全自查报告.md》与《SHA256SUMS.txt》
    audit_summary = security_audit.audit_files(entries)
    audit_md = security_audit.render_audit_report(audit_summary, total_files=len(entries) + 1, version=version)
    entries.append(("安全自查报告.md", audit_md.encode("utf-8")))
    entries.sort(key=lambda item: item[0])
    sha_txt = security_audit.render_sha256sums(entries)
    entries.append(("SHA256SUMS.txt", sha_txt.encode("utf-8")))
    entries.sort(key=lambda item: item[0])

    with zipfile.ZipFile(tmp, "w") as zf:
        for arcname, raw in entries:
            info = zipfile.ZipInfo(arcname, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            mode = 0o755 if arcname.endswith((".sh", ".desktop")) else 0o644
            info.external_attr = mode << 16
            zf.writestr(info, raw, compresslevel=9)
    os.replace(tmp, target)
    return target, len(entries)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None, repo_root: Optional[Path] = None) -> int:
    setup_console()
    parser = make_parser(
        "build_prompts.py",
        "为每个 skill 生成给网页大模型使用的提示词版（dist/prompts/），可选生成国产信创多档产物与内网离线包。",
        "退出码：0 成功；1 存在错误，或 --check 发现不一致。",
    )
    parser.add_argument("--check", action="store_true", help="只比较不写入；dist/prompts 与源文件不一致时返回 1（供 CI 使用）")
    parser.add_argument(
        "--xinchuang",
        action="store_true",
        help="额外生成国产信创与政务内网产物：dist/prompts-lite/（<=4000字精简版）、"
             "dist/prompts-bundles/（高频单对话一站式合集）、dist/rag-kb/（Dify/FastGPT/MaxKB 知识库切片包）",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="额外生成 dist/offline/dyz-gongwen-skills-offline-<版本>.zip（含 skills/、多档提示词、RAG 切片、"
             "xinchuang/ 本地工具与模板、已预下载的 wheelhouse/、一键安装脚本、安全自查报告与 SHA256SUMS.txt）",
    )
    parser.add_argument(
        "--no-wheelhouse",
        action="store_true",
        help="构建离线包时跳过仓库根目录下的 wheelhouse/ 离线依赖目录",
    )
    add_root_argument(parser)
    args = parser.parse_args(argv)
    root = (args.root or repo_root or REPO_ROOT).resolve()

    build = build_all(root)
    if build.skill_count == 0:
        print("提示：skills/ 下还没有任何 skill，未生成提示词版。")
    for warning in build.warnings:
        print(f"警告：{warning}")
    for error in build.errors:
        print(f"错误：{error}")

    xinchuang_sets: List[Tuple[str, Dict[str, str]]] = []
    if args.xinchuang and build.skill_count > 0:
        xinchuang_sets = [
            (PROMPTS_LITE_REL, build_lite_prompts(root)),
            (PROMPTS_BUNDLES_REL, build_bundle_prompts(root)),
            (RAG_KB_REL, build_rag_kb(root)),
        ]
        for message in xinchuang_errors(root, xinchuang_sets):
            print('错误：' + message)
            build.errors.append(message)

    if args.check:
        diffs = check_outputs(root, build)
        for rel_dir, expected in xinchuang_sets:
            diffs.extend(_check_dir_outputs(root, rel_dir, expected))
        for diff in diffs:
            print(f"  {diff}")
        if args.offline:
            print("提示：--check 模式下不生成离线包。")
        if diffs:
            print(f"dist/prompts 与源文件不一致（{len(diffs)} 处）。请运行 python tools/build_prompts.py 后提交。")
            return 1
        if build.errors:
            return 1
        print(f"检查通过：{len(build.docs)} 份提示词版与源文件一致。")
        return 0

    try:
        actions = write_outputs(root, build)
        for rel_dir, expected in xinchuang_sets:
            if expected:
                actions.extend(_write_dir_outputs(root, rel_dir, expected))
    except OSError as exc:
        print(f"错误：写入 {PROMPTS_REL} 失败（{exc}）")
        return 1
    for action in actions:
        print(f"  {action}")
    for doc in build.docs:
        flag = "（超长）" if doc.is_long else ""
        print(f"[{doc.name}] {doc.char_count} 字符{flag}")
    if build.docs:
        print(f"已生成 {len(build.docs)} 份提示词版：{PROMPTS_REL}/")
    if xinchuang_sets:
        for rel_dir, expected in xinchuang_sets:
            if expected:
                print(f"已生成信创产物：{rel_dir}/（{len(expected)} 个文件）")

    if args.offline:
        if build.errors:
            print("存在错误，未生成离线包。")
        else:
            version, warning = offline_version(root)
            if warning:
                print(f"警告：{warning}")
            for rel in offline_missing(root):
                print(f"警告：找不到 {rel}，离线包里不会有它")
            try:
                target, count = write_offline_zip(root, version, include_wheelhouse=not args.no_wheelhouse)
            except OSError as exc:
                print(f"错误：生成离线包失败（{exc}）")
                return 1
            print(f"已生成离线包：{target.relative_to(root).as_posix()}（{count} 个文件）")
    return 1 if build.errors else 0


if __name__ == "__main__":
    sys.exit(main())
