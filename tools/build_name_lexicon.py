#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""姓名数据的开发期统计工具（不属于任何 skill 的运行时，不随包发布）。

姓名识别的数据在 shared/scripts/gw_names.json。其中两类数据来自对仓库规范性文档的统计：
  1. word_bigrams：常见二字词。规范性文档（skills/*/references、shared 下的 md、各 SKILL.md）里
     文档频次不低于 MIN_DF（20）篇的二字汉字串。根 README、各包 README、CHANGELOG 经常改动，不参与统计，
     免得改一次说明文字数据就跟着漂移。统计结果里明显的跨词噪声（“报或”“期或”这类不是词的串）列在 NOISE_BIGRAMS，人工剔除。识别时用来否决“姓名末字 + 后一字刚好是常见词”的截取
     （如“孙丽责任心”被截成“孙丽责”）。
  2. 排除词的挖掘候选：首字是姓氏、文档频次不低于 MIN_DF、第二字既不是常见名用字也不是非名用字的二字串。
     候选只打印，不自动入库；必须逐个人工过目，跨词串、明显不是词的删掉，再手工并入 stopwords。

用法：
  python tools/build_name_lexicon.py --update        # 重算 word_bigrams 与 counts，写回 gw_names.json
  python tools/build_name_lexicon.py --check         # 校验 JSON 里的 word_bigrams、counts 与统计结果一致
  python tools/build_name_lexicon.py --mine          # 打印排除词挖掘候选（人工复核用）
  python tools/build_name_lexicon.py --docs          # 打印参与统计的文档数

given_chars（常见名用字）不是统计出来的：它是独立整理的一份常见人名用字表，直接维护在 gw_names.json 里。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "shared" / "scripts" / "gw_names.json"
MIN_DF = 20
_RUN_RE = re.compile(r"[一-鿿]+")
# counts 字段统计的数据项（字符串按字数，列表按条数，word_bigrams 按二字串个数）
COUNT_KEYS = ("surnames_common", "surnames_rare", "compound", "ambiguous", "nongiven_chars", "soft_given_chars",
              "given_chars", "place_end", "place_end_2char", "stopwords", "stopwords_exact", "right_strong",
              "right_weak", "left_words", "word_bigrams", "table_names", "table_public", "table_nonnames",
              "table_sensitive_hospital", "table_sensitive_soe", "table_sensitive_k12", "org_abbr_end", "personal_actions",
              "frame_collectives", "office_modifiers")


# 人工剔除的跨词噪声（统计里达到文档频次、但不是词）。重新统计后须人工过目新增项，不是词的补到这里
NOISE_BIGRAMS: frozenset = frozenset((
    "不覆 尾提 律脱 纸摘 续让 "
    "一事 一的 业专 业包 业秘 个方 个问 中不 中写 中出 中列 中即 中提 中有 中标 中没 中的 中给 为具 为凑 为基 为目 为虚 么写 么时 书交 书的 了交 了什 了哪 了字 人信 人写 "
    "人同 人和 人职 代会 代写 代字 令性 令第 以学 以当 以本 以用 以考 件不 件中 件为 件位 件原 件和 件的 件系 件说 任主 任人 任单 任状 任部 份材 份证 众号 众的 会和 会或 "
    "会报 会研 会讲 估自 位制 位名 位和 位差 位或 位提 位画 位的 位类 位规 位领 体事 体做 体和 体情 体日 体要 作会 作和 作性 作总 作报 作提 作方 作日 作条 作流 作目 作秘 "
    "作要 例只 例的 例第 供了 供原 供参 供的 先写 先给 先读 先运 先问 发人 发日 发的 发通 可写 可执 和个 和主 和事 和依 和单 和原 和口 和国 和填 和处 和学 和安 和对 和已 "
    "和意 和成 和报 和措 和改 和数 和整 和文 和日 和时 和本 和条 和标 和正 和用 和社 和结 和自 和行 和表 和要 和起 大白 天推 学模 小标 年工 年的 年通 建与 建工 律不 律依 "
    "心谈 成一 成已 成情 成时 成的 才写 才在 才标 报或 改台 改措 改方 改法 改的 改说 政机 政部 文一 文不 文中 文为 文主 文写 文只 文和 文处 文或 文按 文日 文机 文标 文没 "
    "文用 文的 文管 文规 文里 新原 新后 新开 时不 时以 时使 时先 时写 时只 时完 时才 时按 时提 时用 时的 时读 时运 明一 明不 明中 明依 明写 明出 明原 明只 明和 明哪 明待 "
    "明提 明末 明来 明注 明的 明请 有一 有下 有事 有企 有依 有具 有写 有原 有提 有数 有文 有本 有标 有没 有画 有的 有要 期或 来的 民会 民的 理办 理工 理成 理的 理规 理部 "
    "生信 生健 生姓 生的 眉页 立医 策程 纯文 育局 育教 育部 致家 致的 良事 设机 词版 语化 谨模 轮交 进一 进正 进起 长会 长办 长的 "
    "不覆 尾提 律脱 纸摘 续让 "
).split())

# 低于文档频次阈值也保留，避免把已脱敏写法“李同学”中的“李同”误识别为姓名。
REQUIRED_BIGRAMS: frozenset = frozenset({"同学"})


def collect_docs() -> List[Tuple[Path, str]]:
    """参与统计的规范性文档：同内容只算一份（references/_shared 下是 shared 的副本）。"""
    files: List[Path] = []
    files += sorted((REPO / "skills").glob("*/references/**/*.md"))
    files += sorted((REPO / "shared").glob("**/*.md"))
    files += sorted((REPO / "skills").glob("*/SKILL.md"))
    seen: Dict[str, Path] = {}
    for p in files:
        text = p.read_text(encoding="utf-8-sig", errors="replace")
        seen.setdefault(text, p)
    return [(p, t) for t, p in seen.items()]


def bigram_docfreq(docs: List[Tuple[Path, str]]) -> Counter:
    """二字汉字串的文档频次：只在连续汉字内部取，不跨标点、空白、字母数字。"""
    df: Counter = Counter()
    for _p, text in docs:
        grams: Set[str] = set()
        for run in _RUN_RE.findall(text):
            for i in range(len(run) - 1):
                grams.add(run[i:i + 2])
        df.update(grams)
    return df


def build_bigrams(df: Counter) -> List[str]:
    common = {g for g, n in df.items() if n >= MIN_DF and g not in NOISE_BIGRAMS}
    return sorted(common | REQUIRED_BIGRAMS)


def load() -> Dict[str, object]:
    return json.loads(DATA.read_text(encoding="utf-8"))


def count_of(data: Dict[str, object], key: str) -> int:
    val = data[key]
    if key == "word_bigrams":
        return len(str(val).split())
    return len(val)  # type: ignore[arg-type]


def make_counts(data: Dict[str, object]) -> Dict[str, int]:
    return {k: count_of(data, k) for k in COUNT_KEYS}


def mine_stopwords(data: Dict[str, object], df: Counter) -> List[Tuple[str, int]]:
    surnames = set(str(data["surnames_common"])) | set(str(data["surnames_rare"]))
    given = set(str(data["given_chars"]))
    nongiven = set(str(data["nongiven_chars"]))
    soft = set(str(data["soft_given_chars"]))
    stop = list(data["stopwords"])  # type: ignore[arg-type]
    exact = set(data["stopwords_exact"])  # type: ignore[arg-type]
    out = []
    for g, n in df.items():
        if n < MIN_DF or g[0] not in surnames:
            continue
        if g[1] in given or g[1] in nongiven or g[1] in soft:
            continue
        if g in exact or any(g.startswith(w) for w in stop):
            continue
        out.append((g, n))
    out.sort(key=lambda kv: (-kv[1], kv[0]))
    return out


def check_data(data: Dict[str, object], bigrams: List[str]) -> Tuple[bool, bool, List[str], Dict[str, int]]:
    """校验 JSON 数据与统计来源：返回 (word_bigrams 一致, counts 一致, 文件里的 word_bigrams, 实算 counts)。
    --check 与 tests/names 的“数据与来源一致”测试共用这一个函数。"""
    have = str(data.get("word_bigrams", "")).split()
    counts = make_counts(data)
    return have == bigrams, data.get("counts") == counts, have, counts


def verify() -> Tuple[bool, str]:
    """直接校验仓库当前数据（等价于 --check）：返回 (是否一致, 说明)。"""
    docs = collect_docs()
    bigrams = build_bigrams(bigram_docfreq(docs))
    ok, counts_ok, have, _ = check_data(load(), bigrams)
    msg = f"word_bigrams {'一致' if ok else '不一致'}（文件 {len(have)} 个，统计 {len(bigrams)} 个）；counts {'一致' if counts_ok else '不一致'}"
    return ok and counts_ok, msg


def dump(data: Dict[str, object]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main(argv: List[str] = None) -> int:  # type: ignore[assignment]
    ap = argparse.ArgumentParser(description="姓名数据开发期统计工具")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--update", action="store_true", help="重算 word_bigrams 与 counts 并写回")
    g.add_argument("--check", action="store_true", help="校验 word_bigrams 与 counts")
    g.add_argument("--mine", action="store_true", help="打印排除词挖掘候选")
    g.add_argument("--docs", action="store_true", help="打印参与统计的文档")
    args = ap.parse_args(argv)
    docs = collect_docs()
    if args.docs:
        print(f"参与统计的文档 {len(docs)} 份（同内容去重）")
        for p, _t in docs:
            print(" ", p.relative_to(REPO).as_posix())
        return 0
    data = load()
    df = bigram_docfreq(docs)
    if args.mine:
        rows = mine_stopwords(data, df)
        print(f"挖掘候选 {len(rows)} 个（文档频次 >= {MIN_DF}，共 {len(docs)} 份文档）；须逐个人工复核后再并入 stopwords")
        print(" ".join(f"{g}:{n}" for g, n in rows))
        return 0
    bigrams = build_bigrams(df)
    if args.check:
        ok, counts_ok, have, _ = check_data(data, bigrams)
        print(f"word_bigrams：{'一致' if ok else '不一致'}（文件 {len(have)} 个，统计 {len(bigrams)} 个）；counts：{'一致' if counts_ok else '不一致'}")
        return 0 if ok and counts_ok else 1
    data["word_bigrams"] = " ".join(bigrams)
    data["counts"] = make_counts(data)
    DATA.write_text(dump(data), encoding="utf-8")
    print(f"已写回 {DATA.relative_to(REPO).as_posix()}：word_bigrams {len(bigrams)} 个，文档 {len(docs)} 份")
    return 0


if __name__ == "__main__":
    sys.exit(main())
