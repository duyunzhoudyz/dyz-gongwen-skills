<!-- README_SYNC: source=working-tree; updated=2026-11-27 -->

<div align="center">

[简体中文](README.md) · English

# dyz-gongwen-skills · Chinese Official Document (公文) Skills

22 AI skills for writing Chinese official documents (公文, *gongwen*) in government agencies, schools, hospitals, public institutions, and enterprises: drafts use only the facts you provide, format Word files to the GB/T 9704 national standard, run 13 categories of automated lint checks, and stop on classified markings. Works across 7 coding agents, web LLM chat prompts, and air-gapped intranet workstations.

Author: [duyunzhoudyz](https://github.com/duyunzhoudyz) · Free for personal and non-commercial use; commercial use requires prior authorization; keep this attribution when redistributing.

If this project solves a real problem for you, leave a [Star](https://github.com/duyunzhoudyz/dyz-gongwen-skills/stargazers) so you can find it again and help others with the same need discover it.

[![GitHub stars](https://img.shields.io/github/stars/duyunzhoudyz/dyz-gongwen-skills?style=flat&logo=github&label=Stars)](https://github.com/duyunzhoudyz/dyz-gongwen-skills/stargazers)
[![CI](https://github.com/duyunzhoudyz/dyz-gongwen-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/duyunzhoudyz/dyz-gongwen-skills/actions/workflows/ci.yml)
[![License: PolyForm NC](https://img.shields.io/badge/License-PolyForm%20NC%201.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.3.0-orange)](CHANGELOG.md)
[![Skills](https://img.shields.io/badge/skills-22-brightgreen)](#skill-map)
[![Platforms](https://img.shields.io/badge/platforms-7%20Agent%20tools%20%7C%20web%20LLM%20%7C%20intranet-lightgrey)](#quick-start)

[Quick start](#quick-start) · [Air-gapped intranet](#xinchuang-and-air-gapped-intranets-offline-use) · [Skill map](#skill-map) · [What to say](#what-to-say) · [Results](#results) · [FAQ](#faq) · [Community](#community-and-contact)

</div>

> **Confidentiality notice**: Never enter classified information into any internet-connected AI tool. Process internal documents only on models deployed inside your organization's intranet; the prompt editions and offline bundle in this repository run directly on air-gapped networks. See [使用须知](使用须知.md) (in Chinese) for details.

<div align="center">

<img src="docs/assets/hero-before-after.png" width="860" alt="An AI-drafted notice before and after dyz-gongwen-skills: P0 must-fix issues drop from 5 to 0, P1 suggested edits drop from 31 to 0, producing a GB/T 9704 red-header .docx" />

*Fictional district education bureau notice; full walkthrough in [examples/B-AI稿体检](examples/B-AI稿体检/). The formatted preview is an approximate render; actual fonts depend on what is installed on your machine. All prompts and generated documents are in Chinese.*

</div>

<!-- AD-SLOT -->
## Sponsored

Using this repository does not require purchasing or signing up for any of the services below.

- [Sub4AI Shop](https://www.16688.com.cn/shop/SUB4AI): AI subscriptions and digital memberships across 9 categories and dozens of items, including direct top-ups for major AI plans (monthly, annual, and multi-tier options), ready-to-use AI accounts, productivity and creative software memberships (Notion, Adobe Express, Suno, Tavily, and others), and email accounts, helping individual users get around payment hurdles when subscribing to overseas AI services. Self-service checkout accepts Alipay and WeChat Pay, with automated delivery on the majority of listings and 24/7 self-service top-ups arriving in roughly a minute (see individual product pages for exact timing); transactions are held in escrow on the 16688 platform with order-lookup and dispute channels, a 30-day warranty on select direct top-up items, and invoices available through customer support on eligible products. For team and institutional procurement, see [sub4ai.com](https://sub4ai.com): overseas AI subscription provisioning, renewals, and account delivery for companies, universities, and teams, supporting bulk purchasing with quotes, contracts, corporate bank settlement, and invoicing.
- [1KeyAPI](https://1keyapi.com): Infrastructure-grade stability and unthrottled concurrency, built for research benchmarks and production workloads. One API key connects major global and Chinese model families, including Claude, GPT, Gemini, Grok, Qwen, DeepSeek, Kimi, and GLM; switch models without changing code through dual Anthropic (`/v1/messages`) and OpenAI (`/v1/chat/completions`, `/v1/responses`) protocol compatibility, so existing SDKs and IDE plugins plug in with no code changes, backed by multi-route hot standby, automatic failover, and sticky long-context sessions. Transparent per-token pricing in RMB: the website publishes model rates alongside vendor reference prices with a monthly cost estimator, plus spending caps, rate limits, and over-quota alerts broken down by school, lab, department, or project, and exportable billing and usage reports for finance reconciliation. Supports corporate bank transfers and invoices; users in mainland China should use the service in accordance with local laws, regulations, and platform terms of service.
<!-- /AD-SLOT -->

---

## What this is, and how it differs from plain AI drafting

dyz-gongwen-skills is a suite of 22 Chinese official-document (*gongwen*, 公文) writing skills: 17 core skills and 5 sector packs. In Chinese public administration and institutional work, *gongwen* genres follow strict rules on administrative hierarchy (upward, parallel, or downward routing), terminology, punctuation, numbering, and GB/T 9704-2012 page layout. Installed in coding agents such as Claude Code, Codex, or Cursor, these skills take plain-language requests and handle drafting, revision, compliance proofreading, and Word/HTML formatting; without an agent tool, you can paste the standalone prompts into web chat models (DeepSeek, Doubao, Kimi) or an on-premises intranet LLM.

How this differs from asking a general-purpose LLM to write directly:

| Stage | Plain AI drafting | With dyz-gongwen-skills |
|---|---|---|
| Data & examples | Invents figures or cases when materials are missing | Uses only the materials you provide and marks missing facts as `【待补】` (`[TO FILL]`). Across 136 anti-fabrication cases in the v1.0 benchmark, fabrications were 0 with skills vs. 66 without |
| Page layout | Ad-hoc styling; breaks or swaps fonts silently when standard Chinese fonts are missing | Generates 7 GB/T 9704-2012 Word layouts; reports missing fonts upfront and never substitutes silently. Scored 97.2 on layout audit in head-to-head testing (next highest: 79.6) |
| Prose style | AI clichés, choppy short sentences, and overused directives ("must", "strictly prohibited") | Built-in opening-stance guides, sentence-length rewrites, and 6 rhythm exemplars; 13 script lint categories across 41 document types, calibrated for sentence length and directive density against a 300-document public *gongwen* corpus |
| Administrative stance | Hedged wording ("may", "consider") and tacked-on disclaimers | Calibrates phrasing to upward, parallel, or downward administrative routing; puts items needing verification into a separate drafting note outside the document body |
| Confidentiality | No interception | Stops and alerts on classification marks or "internal document" (`内部资料`) / "work secret" (`工作秘密`) labels; prompt editions and the offline bundle work on air-gapped intranets |
| Workflow weight | Same heavy pipeline for every request | One-step output for routine notices under 1,000 Chinese characters; standard drafts run script linting first and add polishing or review only when thresholds fire; high-stakes filings go through an eight-gate review |
| Organizational rules | Generic templates | 7 organization profiles, 5 role modes, and 5 sector packs with dedicated compliance scripts (39 rules for hospitals, 40 checks for SOEs, 38 rules for K-12 schools, 11 rules for universities, etc.) |

Verifiable evidence in the repository:

- Traceable rules: every layout, punctuation, and numeral rule cites its clause number in [shared/rules/](shared/rules/); the lint engine runs 13 check categories across 41 document types ([gongwen_lint.py](shared/scripts/gongwen_lint.py)).
- Tests: 3,191 unit tests pass across the repository (1 Windows symlink test skipped), and CI enforces schema validation, unit tests, and zero-egress static auditing.
- Benchmarks: across 372 test cases and 2,671 checks in the v1.0 benchmark, universal check pass rate reached 99.1% with skills vs. 68.7% without; head-to-head comparisons against 8 similar GitHub projects are in [Results](#results).
- Air-gapped operation: the Xinchuang local toolbox binds strictly to `127.0.0.1`, makes no network requests, and retains no document text; all offline scripts pass automated code-level zero-egress auditing (`security_audit.py --strict`, blocking any networking code on commit); an 8-case guardrail smoke test passed 8/8 on `deepseek-chat` in both injection modes.
- Stated limitations: real-hardware acceptance on Kylin OS and UnionTech UOS is not yet complete; benchmark judges are LLMs instead of human reviewers; personal-name detection is heuristic. Details in [Results](#results) and [FAQ](#faq).

How to use it in three steps: install for your environment (or copy a prompt), state your request in plain Chinese, and ask to "format as red-header Word" (`排成红头`) when you need a formal file. Copy-paste commands for each setup follow in [Quick start](#quick-start).

---

## Quick start

### Get running in three steps

1. Pick your setup: install via Option 1, 2, or 3 for coding agents; copy prompts via Option 4 for web chat LLMs; or use [Xinchuang and air-gapped intranets](#xinchuang-and-air-gapped-intranets-offline-use) on offline workstations.
2. Describe your task directly without memorizing skill names. For example: `"写一篇科室年度工作总结，2000 字左右，素材在附件里，不要编数据。"` ("Write a department year-end summary, around 2,000 characters, source material attached, do not invent data.") More examples are in [What to say](#what-to-say).
3. For formal delivery, ask to "format as red-header Word" (`排成红头 Word`) or "generate an HTML notice" (`生成 HTML 通知`); before sign-off, ask to "proofread the draft" (`帮我核一遍稿`).

### Pick an entry point for your environment

| Your environment | Direct route |
|---|---|
| Kylin OS / UnionTech UOS / intranet Windows + WPS (coding agents prohibited) | Download the offline bundle and launch the zero-network local toolbox in one command; see [Xinchuang and air-gapped intranets](#xinchuang-and-air-gapped-intranets-offline-use) |
| DeepSeek, Doubao, Kimi (web), or an intranet LLM | No install needed; copy a prompt from [Option 4](#option-4-web-llms-and-intranet-models-no-install) |
| Claude Code | Two commands via the plugin marketplace; see [Option 2](#option-2-claude-code-plugin-marketplace) |
| Codex, Cursor, Gemini CLI, GitHub Copilot, Qwen Code, Kimi Code CLI | One-line install script; see [Option 1](#option-1-one-line-install-script-windows-macos-linux) |
| Already inside an agent (Cursor, Trae, CodeBuddy, etc.) and prefer not to run shell commands | Paste one sentence to let the agent install it; see [Option 5](#option-5-let-your-agent-install-it) |

Skills directory paths for Trae and CodeBuddy have not been verified on every version. The installer includes targets for both (`--target trae`, `--target codebuddy`); open an Issue if you run into path mismatches.

### Option 1: One-line install script (Windows, macOS, Linux)

> Download tip for slow connections or machines without Git: open [Releases](https://github.com/duyunzhoudyz/dyz-gongwen-skills/releases) and download `dyz-gongwen-skills-offline-1.3.0.zip` (available once v1.3.0 is published; until then click green `Code -> Download ZIP` at the top of this page or clone the repository), extract it, and run the final install command inside the extracted folder.

Windows (type `powershell` in the folder address bar, press Enter, and paste):

```powershell
git clone https://github.com/duyunzhoudyz/dyz-gongwen-skills.git
cd dyz-gongwen-skills
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

macOS / Linux (paste in terminal; Kylin OS, UnionTech UOS, and other Chinese Linux distributions use this same command, as the installer has no separate Xinchuang target):

```bash
git clone https://github.com/duyunzhoudyz/dyz-gongwen-skills.git
cd dyz-gongwen-skills
bash install.sh
```

If you already downloaded and extracted the ZIP archive, skip the first two lines and run the last line inside the extracted directory.

The script checks for Python 3.9+, asks whether to install Word/Excel formatting packages, and installs the 17 core skills into every supported agent tool found on your machine. To preview target paths without writing files, append `-WhatIf` on Windows or `--dry-run` on macOS/Linux.

List supported agent targets or install to a single tool (Qwen Code shown below; replace `python` with `python3` on macOS/Linux):

```bash
python tools/install.py --list-targets
python tools/install.py --target qwen
```

### Option 2: Claude Code plugin marketplace

```text
/plugin marketplace add duyunzhoudyz/dyz-gongwen-skills
/plugin install gongwen@dyz-gongwen-skills
```

### Option 3: npx skills (requires Node.js)

```bash
npx skills add duyunzhoudyz/dyz-gongwen-skills
```

### Option 4: Web LLMs and intranet models (no install)

No command line required. Open one of the directories below and paste the file contents at the start of a DeepSeek, Doubao, Kimi, or intranet LLM chat:

| Chat scenario | Directory | Notes |
|---|---|---|
| Complete drafting, de-AI-tone cleanup, and proofreading in a single chat | [dist/prompts-bundles/](dist/prompts-bundles/) | 4 single-chat bundles (statutory *gongwen*, general reports, editing & proofreading, policy implementation & rectification) so you do not have to switch chats |
| Intranet model with a 4K to 8K system-prompt character limit | [dist/prompts-lite/](dist/prompts-lite/) | 22 hand-trimmed compact prompts, each `<=4,000` Chinese characters |
| Full per-skill rules and regulatory clause citations | [dist/prompts/](dist/prompts/) | 22 complete prompts (~26,000 to 29,000 characters each); start with `gongwen.md` and paste the handoff card when moving to the next skill |

### Option 5: Let your agent install it

Send the prompt below to your agent (replace `gongwen-hospital` with the sector pack you need, or change the last clause to skip sector packs if you only need the core skills):

```text
Please install the core skills from the skills/ directory of https://github.com/duyunzhoudyz/dyz-gongwen-skills into your skills directory.
Among them, gongwen-grassroots, gongwen-hospital, gongwen-university, gongwen-k12, and gongwen-soe are sector packs;
install only gongwen-hospital for now, and tell me which skills are available when finished.
```

### Installing sector packs

Sector packs install on top of the core skills. Using the public hospital pack as an example, copy the command matching your setup:

```text
/plugin install gongwen-hospital@dyz-gongwen-skills
```

```bash
bash install.sh --pack hospital
```

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 --pack hospital
```

The install script accepts multiple packs (`--pack hospital --pack soe`) or `--pack all` for all five; web LLM users can copy the matching file from `dist/prompts/` or `dist/prompts-lite/` (such as `gongwen-hospital.md`).

### Xinchuang and air-gapped intranets (offline use)

Adaptation status, stated plainly: offline and zero-dependency adaptation plus local self-testing are complete; real-hardware acceptance testing on Kylin OS and UnionTech UOS has not yet been completed.

Built for domestic Chinese Linux distributions (*Xinchuang* / 信创 workstations), government intranets, and office PCs where autonomous coding agents are disallowed: every operation is triggered manually by the user, with no background daemon and no outbound network traffic. Download `dyz-gongwen-skills-offline-1.3.0.zip` from [Releases](https://github.com/duyunzhoudyz/dyz-gongwen-skills/releases) (available once v1.3.0 is published; until then use `Code -> Download ZIP`, `git clone`, or an internal IT shared drive), extract it, and run the command for your scenario.

#### Office staff: launch the zero-network local toolbox

Listens exclusively on `http://127.0.0.1:8765`, makes no internet or model API calls, and does not save document text (a few checks process files briefly in a local temp folder and delete them right after). One local browser page handles prompt copying, `.docx`/`.txt` import, classified-mark blocking, tab-isolated two-way redaction and restoration, eight-gate linting with style-fingerprint checks, fact cross-checking, 8 sector-specific compliance checkers, font checks, single-file HTML formatting, GB/T 9704 Word generation (falls back automatically to a built-in pure-stdlib generator when `python-docx`/`lxml` are absent, including on LoongArch), and OFD structure checks.

Kylin OS / UnionTech UOS / Linux (double-click `xinchuang/启动工具箱.sh` or `.desktop`, or open a terminal in the extracted folder and paste):

```bash
bash xinchuang/启动工具箱.sh
```

Intranet Windows (double-click `xinchuang\启动工具箱.bat`, or open `powershell` in the extracted folder and paste):

```powershell
.\xinchuang\启动工具箱.bat
```

Single-command CLI for HTML formatting, linting, or OFD inspection without opening the browser toolbox (pure Python standard library, zero third-party packages; replace `python3` with `python` on Windows):

```bash
python3 skills/gongwen-format/scripts/build_html.py draft.txt -o output.html
python3 skills/gongwen-review/scripts/gongwen_lint.py draft.txt --fingerprint --baseline
python3 skills/gongwen-format/scripts/ofd_check.py output.ofd
```

Workstations with no Python installed and WPS macros disabled (zero commands):

- Formatting: double-click any of the 5 blank GB/T 9704 `.docx` templates in [xinchuang/templates/](xinchuang/templates/) (plain, red-header letterhead, minutes, internal sign-off memo, general report) and paste your text; if macros are permitted, use `skills/gongwen-format/assets/wps_gongwen_macro.js`; Linux font names and WPS menu paths are mapped in `skills/gongwen-format/references/xinchuang.md`.
- Drafting: copy a prompt from [dist/prompts-bundles/](dist/prompts-bundles/) (4 single-chat bundles) or [dist/prompts-lite/](dist/prompts-lite/) (22 compact prompts `<=4,000` chars) into your organization's intranet LLM chat.

<details>
<summary><strong>IT administrators: offline bundle build, security intake check, guardrail smoke test, and intranet RAG deployment (click to expand)</strong></summary>

Build the Xinchuang offline ZIP on an internet-connected staging machine (automatically includes `安全自查报告.md`, `SHA256SUMS.txt`, the [IT intake & deployment guide](xinchuang/单位信息中心入网评估与部署指引.md), and the [15-minute hardware acceptance checklist](xinchuang/信创真机验收清单.md)):

```bash
python3 tools/build_prompts.py --xinchuang --offline
```

To bundle offline wheels for full GB/T 9704 Word and Excel chart generation (`python-docx`, `openpyxl`, `lxml`), pre-download wheels across 3 platforms (x86_64, Phytium/Kunpeng ARM64, Windows) x Python 3.9 to 3.12 = 12 `wheelhouse/<arch>/py<version>/` sets (LoongArch `loongarch64` has no `lxml` wheel on PyPI, so `build_wheelhouse.py` writes an `INSTALL.txt` with steps to install `python3-docx python3-openpyxl python3-lxml` from the intranet OS repo, or falls back automatically to zero-dependency Word formatting):

```bash
python3 tools/build_wheelhouse.py --arch all
python3 tools/build_prompts.py --xinchuang --offline
```

30-second IT intake verification (after extracting `dyz-gongwen-skills-offline-*.zip`, verify file hashes and review `安全自查报告.md` in the bundle root):

```bash
sha256sum -c SHA256SUMS.txt
```

When working from a full repository checkout (`git clone` or `Code -> Download ZIP`), you can also re-run the AST zero-egress static audit and the 8-case guardrail smoke test against an intranet LLM (supports OpenAI-compatible endpoints such as vLLM, Ollama, SGLang, and Ascend MindIE; keep `--system-mode first-message` for intranet web UIs without a system-prompt box):

```bash
python3 tools/security_audit.py --strict
python3 evals/xinchuang/smoke_eval.py --base-url http://127.0.0.1:8000/v1 --model deepseek-r1-32b --system-mode first-message
```

Organization-wide intranet RAG knowledge base (Dify, MaxKB, FastGPT, or open-source Coze Studio): import the 16-file, 462-chunk package from [dist/rag-kb/](dist/rag-kb/) (for Dify, import `dify-app-template.yml` directly with Agent mode disabled) so staff can access the rules from an intranet browser with zero client-side installation. See [evals/xinchuang/](evals/xinchuang/) and the [IT intake & deployment guide](xinchuang/单位信息中心入网评估与部署指引.md).

</details>

### Formatting dependencies and uninstall

Full 7-layout Word output and Excel charts require Python 3.9+ plus `python-docx` and `openpyxl`. Users on slow connections in mainland China can install via the Tsinghua PyPI mirror:

```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple python-docx openpyxl
```

You can still use the suite without these packages or without Python; see the zero-dependency intranet options above.

Uninstall: if installed via Option 1 or `tools/install.py`, append `--uninstall` to your original install command to preview the removal list, then add `--yes` to delete; if installed via the Claude Code plugin marketplace, run `/plugin uninstall gongwen@dyz-gongwen-skills`.

---

## Skill map

17 core skills install together in one plugin; 5 sector packs install separately on demand. All 22 skills are currently rated `Stable`.

<details>
<summary>Criteria for Stable vs. Beta</summary>

`Stable` requires: real-model evaluation pass rate on Group A expectations `>= 80%`, `0` fabrications after manual verification, and trigger accuracy `>= 9/10` on positive cases and `10/10` on negative cases. Sector packs must also pass engineering gates: required `references/` files present with verification dates; sector facts cited with source and year; `evals` containing `>= 3` cases each for review mode, confidentiality, and anti-fabrication plus `>= 2` handoff-boundary cases; must-fail and must-pass specimen tests for any dedicated checker script; and standalone web prompts `<= 29,000` characters. `Beta` means sample-tested without yet clearing every gate above. Field feedback and human blind reviews continue after promotion, and any confirmed severe defect (such as fabrication or a guardrail failure) demotes the skill back to `Beta`. See [CONTRIBUTING.md](CONTRIBUTING.md).

</details>

Full instructions for each skill live in its directory under `SKILL.md` (read by agents) and `README.md` (read by humans, in Chinese). The "Trigger scenarios" column below is summarized from each skill's `SKILL.md` `description` for agent routing (user requests are normally sent in Chinese).

**Router & configuration**

| Skill | What it does | Trigger scenarios | Maturity |
|---|---|---|---|
| [`gongwen`](skills/gongwen/) | Entry router: identifies organization type, writer role, document genre, and administrative routing (`上行/平行/下行`), plans the workflow, and builds a quick org profile in 3 questions on first run | "What materials do we prepare for an inspection?", "Not sure which document genre fits"; in web chat, "Which prompt should I paste next?" | Stable |
| [`gongwen-profile`](skills/gongwen-profile/) | Full organization profile builder: learns style conventions from past agency drafts, extracts leadership editing habits, and maintains org banned/preferred term lists | "Build a full organization profile", "Learn our agency's writing style", "Study how our director revised this draft", "Add a banned term" | Stable |

**Drafting**

| Skill | What it does | Trigger scenarios | Maturity |
|---|---|---|---|
| [`gongwen-draft`](skills/gongwen-draft/) | Statutory *gongwen* (`法定公文`): notices (`通知`), requests for instructions (`请示`), reports (`报告`), inter-agency letters (`函`), circulars (`通报`), approvals/replies (`批复`), opinions (`意见`), sign-off memos (`签报`), decisions (`决定`), public notices (`通告`), announcements (`公告`); 1-step fast path under 1,000 chars | "Draft a formal request (`请示`)", "Send an inter-agency letter (`函`) to the finance bureau", "Issue a meeting notice", "Should this be a request (`请示`) or a report (`报告`)?" | Stable |
| [`gongwen-report`](skills/gongwen-report/) | General institutional documents (`综合文稿`): work summaries, annual plans, work priorities, briefings, research reports, experience write-ups, duty/integrity reports (`述职述责述廉`), implementation plans, plenary reports | "Write an annual work summary", "Draft a briefing", "Write a year-end duty report", "Next year's work plan", "Consolidate submissions from multiple departments" | Stable |
| [`gongwen-speech`](skills/gongwen-speech/) | Speeches (`讲话类`): leadership speeches, emcee scripts (`主持词`), ceremonial remarks (`致辞`), pledge/exchange/delegate remarks; sets length from speaking time (~200 Chinese chars/min) in spoken register | "Draft a speech", "Prepare a 15-minute talk", "Opening ceremony remarks", "Write an emcee script" | Stable |
| [`gongwen-party`](skills/gongwen-party/) | Party-building & organizational life (`党建与组织生活`): self-examination (`对照检查`), Party work reports, Party lectures (`党课`), seminar remarks, study reflections, `三会一课` branch meeting records; outputs an outline only when personal examples are missing | "Draft a self-examination report", "Prepare a Party lecture", "Plan a themed Party day", "Write study notes", "Clean up branch meeting notes" | Stable |
| [`gongwen-brief`](skills/gongwen-brief/) | Information briefs (`信息简报`): government info submissions (`政务信息`), bulletins, press releases, official WeChat posts; condenses long reports into short briefs and evaluates adoption likelihood | "Submit a government info item", "Compile a bulletin issue", "Write a press release", "Condense this into an 800-char brief", "Will this info brief get picked up?" | Stable |
| [`gongwen-minutes`](skills/gongwen-minutes/) | Meeting minutes (`会议纪要`): raw records, formal minutes, agenda papers, follow-up action trackers (`督办清单`); organizes strictly without adding unstated claims, distinguishing approved / approved in principle / deferred | "Turn this transcript into meeting minutes", "Draft executive-meeting minutes", "Prepare an agenda paper", "List action items decided at the meeting" | Stable |
| [`gongwen-implement`](skills/gongwen-implement/) | Superior-document implementation (`上级文件转化`): extracts core requirements, builds task-breakdown tables, drafts local implementation plans and compliance reports; flags verbatim copying and layer-by-layer over-mandating (`层层加码`) | "The province issued a notice and we need an implementation plan", "Break down tasks from this policy file", "Map requirements item by item", "Report implementation progress" | Stable |
| [`gongwen-rectify`](skills/gongwen-rectify/) | Inspection & audit rectification (`整改材料`): rectification plans, issue ledgers (Excel-exportable), progress reports, self-inspection reports; reconciles narrative counts against ledger rows item by item | "Inspection feedback arrived and we need a rectification plan", "Build a rectification ledger", "Audit rectification report", "Check whether the report matches the ledger" | Stable |

**Editing & quality assurance**

| Skill | What it does | Trigger scenarios | Maturity |
|---|---|---|---|
| [`gongwen-title`](skills/gongwen-title/) | Titles & outlines: formal *gongwen* titles, main/subtitle pairs, three section-heading schemes, document outlines; checks whether headings match body content | "Suggest a title", "Refine section headings", "Build an outline first", "The headings don't match the paragraphs" | Stable |
| [`gongwen-polish`](skills/gongwen-polish/) | Revision & polishing: length compression, fact-preserving expansion, routing-tone conversion, plain talk to formal *gongwen*, edits from leader margin notes, multi-draft merging | "Cut this down to 3,000 chars", "Turn this upward report into a downward notice", "Director wrote 'too vague, where are the numbers?'", "Merge these two drafts" | Stable |
| [`gongwen-humanize`](skills/gongwen-humanize/) | De-AI-tone cleanup: strips AI buzzwords and formulaic phrasing while keeping legitimate *gongwen* conventions and preserving every fact (99.6% fact retention in benchmark) | "Remove the AI tone", "Sounds too robotic", "Rewrite this DeepSeek-generated summary in natural official prose" | Stable |
| [`gongwen-direct`](skills/gongwen-direct/) | De-hedging: removes disclaimers, turns tentative "it is suggested / may consider" phrasing into clear directives, and ensures upward requests state a concrete recommendation | "Remove 'for reference only'", "This notice sounds like it's bargaining with subordinates; make it a directive", "Approval reply is ambiguous", "Request lacks a proposed option" | Stable |
| [`gongwen-review`](skills/gongwen-review/) | Eight-gate proofreading (`八关核稿`): outputs a severity-ranked issue list (P0/P1/P2); runs 13 categories of script checks covering punctuation, numerals, layout, normative terms, confidentiality, and privacy, with optional style-fingerprint and org banned-term checks | "Proofread this draft", "Run a pre-sign-off check", "Check formatting and punctuation" | Stable |

**Delivery tools**

| Skill | What it does | Trigger scenarios | Maturity |
|---|---|---|---|
| [`gongwen-format`](skills/gongwen-format/) | GB/T 9704 formatting: generates 7 GB/T 9704-2012 Word layouts (red-header letterhead, correspondence letter, minutes, order, plain header, general material, bulletin, including joint issuance, separate-page attachments, and pre-printed letterhead overprint); repairs existing `.docx` files; zero-dependency single-file HTML; OFD inspection | "Format this draft", "Apply red-header layout", "Export to Word", "Generate an HTML notice", "Formatting is broken", "How should page numbers be set?" | Stable |
| [`gongwen-data`](skills/gongwen-data/) | Data & charts: audits table totals, computes YoY/MoM changes with explicit formulas, turns tables into *gongwen*-ready prose, and generates grayscale Excel charts locally | "Merge monthly department tables", "Check whether row totals add up", "Calculate YoY and MoM growth", "Turn these numbers into a paragraph", "Build a bar or line chart" | Stable |

**Sector packs** (installed separately)

| Skill | What it does | Trigger scenarios | Maturity |
|---|---|---|---|
| [`gongwen-grassroots`](skills/gongwen-grassroots/) | Townships, subdistricts & communities: inspection briefings, resident notices, emergency alerts, work logs, village/community affairs disclosures | "Submit a township info brief", "County inspection self-check report", "Water-outage notice for residents", "Heavy-rain alert to villages", "Format a village affairs disclosure" | Stable |
| [`gongwen-hospital`](skills/gongwen-hospital/) | Public hospitals: hospital accreditation self-assessments, national performance exam (`国考`) analysis, RCA/PDCA reports, department chief duty reports (DRG/CMI), Party committee and president's office agendas | "Draft an accreditation self-assessment", "National hospital performance analysis", "Quarterly quality report", "Run an RCA or PDCA write-up", "Department chair duty report", "Hospital executive agenda item" | Stable |
| [`gongwen-university`](skills/gongwen-university/) | Universities: undergraduate teaching-audit self-assessments, discipline evaluations, blind-review checks on grant proposals (`活页`), school summaries, internal sign-offs, and university-vs.-department issuance routing | "Undergraduate audit self-assessment", "Discipline evaluation case study", "Check whether this grant proposal leaks author identity", "Issued by the university or the office?", "Sign-off memo to university leadership" | Stable |
| [`gongwen-k12`](skills/gongwen-k12/) | Primary & secondary schools (K-12): semester plans and summaries, education-supervision self-assessments, parent-meeting talks, student report-card comments, letters to parents | "Semester work plan or summary", "Supervision self-assessment", "Parent-meeting remarks", "End-of-term comments for the whole class", "Holiday safety letter to parents" | Stable |
| [`gongwen-soe`](skills/gongwen-soe/) | State-owned enterprises (SOEs): "Three Majors and One Large" (`三重一大`: major decisions, major appointments, major projects, large-sum capital use) agenda items, board proposals, GM-office minutes, ESG reports, compliance reports | "`三重一大` executive agenda package", "Board proposal and draft resolution", "Executive office minutes", "Operating performance analysis", "ESG or compliance report" | Stable |

---

## What to say

You do not need to name a skill. Send your request in Chinese directly:

| Prompt sent by user (translated for reference) | Handled by |
|---|---|
| "Figure out which official document genre fits this material, then draft it. (background attached)" | `gongwen` router |
| "Here is the transcript from this morning's workplace-safety meeting. Draft the minutes and list decided items in a follow-up tracker." | `gongwen-minutes` |
| "Write a department annual work summary, around 2,000 characters, using the attached notes. Do not invent any figures." | `gongwen-report` |
| "This is an AI-generated first draft. Strip buzzwords like `赋能` ('empower'), `闭环` ('closed loop'), and `全链条` ('full chain'), rewrite in normal *gongwen* prose, and keep every number and case intact. (draft attached)" | `gongwen-humanize` |
| "Change tentative phrases like 'units are advised to' and 'may refer to' in this notice into firm requirements. (notice attached)" | `gongwen-direct` |
| "This request memo goes for signature tomorrow. Proofread it first, then format it as a standard red-header Word file. (memo attached)" | `gongwen-review` -> `gongwen-format` |
| "The municipal government issued this policy document. Extract a task breakdown and draft our agency's implementation plan. (document attached)" | `gongwen-implement` |
| "The inspection team flagged 9 issues. Draft a rectification plan and an issue ledger that exports to Excel. (feedback list attached)" | `gongwen-rectify` |
| "Hospital accreditation is next week. Draft our department's self-assessment focusing on DRG and CMI metrics from the attached sheet." | `gongwen-hospital` sector pack |
| "For the university teaching audit, draft the 'teaching resources and utilization' section of our college report per the attached rubric." | `gongwen-university` sector pack |
| "A subsidiary capital injection goes to next week's Party committee meeting under `三重一大`. Prepare both the agenda brief and draft resolution." | `gongwen-soe` sector pack |
| "Water service in our community will be shut off next Tuesday for pipe maintenance. Write a printed building-entrance notice plus a short group-chat message for residents." | `gongwen-grassroots` sector pack |

More usage examples are in the `README.md` inside each skill directory.

---

## Directory structure

For coding agents and developers navigating the repository. Agents should read the target skill's `SKILL.md` before execution; a compact English project summary is also available in [llms.txt](llms.txt).

```text
dyz-gongwen-skills/
├── skills/                  # 22 skills, each with SKILL.md, README.md, references/, scripts/, evals/
├── shared/                  # Cross-skill rules, style guides, and scripts
│   ├── rules/               # Regulatory clauses, normative terms (normative-terms.md), etc.
│   ├── style/               # Prose engine, 6 rhythm exemplars, 300-doc corpus baseline.md
│   ├── profiles/            # 7 organization profiles and 5 writer role modes
│   ├── scripts/             # Lint engine gongwen_lint.py, name detector gw_names.py, etc.
│   └── guardrails.md        # Six non-negotiable writing guardrails
├── dist/                    # Web-chat and intranet deliverables (built by tools/build_prompts.py)
│   ├── prompts/             # 22 full standalone prompts
│   ├── prompts-lite/        # 22 compact prompts (<=4,000 chars each)
│   ├── prompts-bundles/     # 4 single-chat all-in-one prompt bundles
│   └── rag-kb/              # 16-file, 462-chunk RAG knowledge base for Dify/FastGPT/MaxKB/Coze
├── xinchuang/               # Xinchuang domestic-OS and air-gapped intranet adaptation
│   ├── local_toolbox.py     # Zero-network local browser toolbox (127.0.0.1:8765)
│   ├── lite_docx.py         # Pure-stdlib GB/T 9704 Word builder (fallback without python-docx)
│   ├── templates/           # 5 Python-free, macro-free blank docx templates
│   └── 启动工具箱.sh/.bat/.desktop
├── tools/                   # install.py installer, build_prompts.py builder, validate.py, security_audit.py
├── evals/                   # bench/ full eval, compete/ head-to-head eval, xinchuang/ smoke eval, results/
├── tests/                   # Unit test suite (3,191 tests)
├── examples/                # 6 end-to-end runnable walkthroughs (A to F)
├── docs/                    # Architecture design, authoring specs, eval guides, release notes
├── install.ps1 / install.sh # One-line installers (Windows / macOS / Linux)
└── .claude-plugin/          # Claude Code plugin marketplace manifest marketplace.json
```

---

## Tiered workflow

Drafts are routed by weight automatically. Standard documents run script linting first, adding polishing and review passes only when metrics cross defined thresholds:

| Tier / scenario | Route |
|---|---|
| Lightweight (meeting notices, routine admin/internal notices, forwarding notices, simple replies/sign-offs under 1,000 chars) | `draft` (1-step fast path) -> optional single-file HTML (print / save as PDF / copy) or GB/T 9704 Word |
| Standard (routine requests/reports, summaries, plans, proposals, regular speeches, experience write-ups) | Matching drafting skill (draft + lint & style fingerprint) -> optional `format` (HTML/Word) if clean; runs `direct` / `humanize` / `review` only when lint thresholds are exceeded |
| Heavy / high-risk (major red-header decisions/opinions, principal leaders' keynote speeches, inspection rectification, Party committee or formal external filings) | Drafting skill -> optional polishing -> `review` (eight-gate check, pauses for human confirmation) -> `format` as GB/T 9704 Word |
| AI-draft checkup (cleaning up an existing external AI draft) | `direct` -> `humanize` -> `review`, plus `format` if Word/HTML output is needed |
| Superior-document implementation | `implement` (extract core points, task breakdown table, implementation plan) -> `review` for major deployments -> `format` |

Skill names above omit the `gongwen-` prefix. Web-chat users writing short notices or wanting to finish in a single conversation can paste the matching bundle from `dist/prompts-bundles/` directly.

---

## Results

### AI-draft checkup: a notice before and after

A fictional district education bureau notice on winter campus safety inspections, passed sequentially through `gongwen-direct` -> `gongwen-humanize` -> `gongwen-review` (full Chinese files and script outputs in [examples/B-AI稿体检](examples/B-AI稿体检/)):

| Lint pass | P0 must-fix | P1 suggested | Length (Chinese chars) |
|---|---:|---:|---:|
| Original AI draft | 5 | 31 | 1,092 |
| After checkup | 0 | 0 | 814 |

**Original AI draft (translated excerpt)**

> With winter approaching, the campus safety situation is growing increasingly complex and severe...
>
> **I. Fully Recognize the Great Significance of Winter Campus Safety Inspections**
>
> Without a doubt, campus safety is the bottom line and lifeline of educational development. ... Schools shall take this inspection as a lever (`抓手`) to build an all-round, full-chain (`全方位、全链条`) campus safety management system, and use IT tools to empower (`赋能`) campus safety management...
>
> *The content above is for reference only; please adjust according to actual conditions at each school.*

**After checkup (translated excerpt)**

> I. General Requirements
>
> Winter brings heavier heating and electrical loads, icy roads, and seasonal flu outbreaks, making it a high-incidence period for campus safety incidents. Some schools still emphasize inspection over follow-up rectification. Each school shall use this inspection to strengthen its campus safety management system and apply IT tools to improve daily safety management...

Other fixes caught during the pass: tentative wording ("schools are advised to form a working group") was rewritten as a clear requirement ("each school shall form a working group"); non-standard file code brackets `[2026]第12号` were corrected to `〔2026〕12号` per GB/T 9704; and a clause threatening to "hand parents over to public security organs for administrative detention" was deleted after flagging that a district education bureau holds no statutory penalty authority.

Five additional end-to-end examples generated by the current scripts (overview in [examples/README.md](examples/README.md)):

- General *gongwen*: [Hospital department annual summary](examples/A-医院科室年终总结/) (2,000-char target with sparse input notes: produced ~1,890 chars with 2 `【待补】` markers and 0 invented facts), and [Choosing between an inter-agency letter (`函`) and a formal request (`请示`) for funding](examples/C-文种判断-函/)
- Sector-pack compliance checks: [K-12 student comments with local redaction and restoration](examples/D-中小学评语本地脱敏与还原/) (real student names never enter the LLM prompt), [University grant-proposal blind-review audit](examples/E-高校活页匿名形式审查/) (identity leaks reduced to 0 with automatic masking in output), and [SOE `三重一大` executive agenda & compliance check](examples/F-国企三重一大议题与专检/) (six-element omissions reduced to 0, while a procedural-order inversion is preserved as a P0 alert for human resolution)

### Head-to-head comparison with 8 similar projects

Tested head-to-head against 8 comparable Chinese official-document skills on GitHub plus a no-skill control group (`compete-v7`: 11 writing tasks, 8 formatting tasks, 8 de-AI-tone tasks, 2 runs per entrant per task, 276 runs total). Every run used the same model (`claude-sonnet-5-5`, max reasoning effort), identical user prompts, and fictional source materials.

| Dimension | This project | Next-highest entrant (including no-skill control) |
|---|---|---|
| Formatting: GB/T 9704 layout audit mean score (16 runs) | 97.2 | 79.6 |
| Formatting: mean rank, Claude judge | 1.00 (ranked 1st in all 16 runs) | 2.25 |
| Formatting: font honesty | 16/16 writes standard font names and reports missing fonts | One project substituted fonts in 16 runs (2 unannounced); no-skill control substituted silently in all 16 |
| Classified material (mark on page 1, checkpoint pass rate) | 91.7% (Claude and DeepSeek judges agree; `compete-v7` basis, see v9 caveat below) | 0% across all competitors |
| Writing: runs containing fabrications (Claude judge, 20 runs) | 7/20 (fewest) | 8/20; no-skill control 11/20 |
| Writing: judge evaluations flagging fabrication (DeepSeek, 40) | 13/40 (fewest) | 14/40 |
| Writing: mean rank, Claude judge (1 = top) | 3.45 (tied with two other projects) | No-skill control: 2.95 |
| Writing: mean rank, DeepSeek judge | 2.98 (1st) | 3.02 |
| De-AI-tone: fact retention | 99.6%, 0.25 added numbers on avg, 11.3% of text edited | 99.8%, but edited only 1.7% of text with an AI-tone cleanup score of 1.8/10 (this project: 6.1/10); remaining entrants: 97.0% |
| De-AI-tone: mean rank, Claude judge | 2.06 (tied with one other project) | No-skill control: 2.00 |
| De-AI-tone: mean rank, DeepSeek judge | 1.88 (1st) | 1.91 |
| De-AI-tone: runs adding unstated facts (Claude / DeepSeek) | 1/16, 2/32 | 3/16, 7/32; another project 1/16, 0/32 (barely edits text) |

The latest re-test (`compete-v9`) re-ran the writing track with automated checkpoint scoring (142 programmatically verifiable checkpoints; non-automatable items such as tone and fabrication default to pass): this project ranked 1st at 81.0% (115/142), ahead of the runner-up at 77.5% and the no-skill control at 76.1%. On the header-only classification mark task, 1 of 2 runs missed the mark because reading `.docx` body paragraphs skipped the header XML; that bug has since been fixed and awaits a fresh benchmark run.

Across formatting, classified-content interception, anti-fabrication, and font honesty, this project scored highest among all entrants; in writing quality and de-AI-tone cleanup it sits in the top tier, ranking 1st under the DeepSeek judge and within 0.5 rank of the leader under the Claude judge.

Methodological caveats:

- Judges are two LLMs (Claude and DeepSeek), not human reviewers, and the Claude judge is the same `claude-sonnet-5-5` model under test. Inter-judge rank correlation (Kendall τ) is 0.50 on writing and 0.65 on de-AI-tone. Human blind evaluation is tracked under [Releases and roadmap](#releases-and-roadmap).
- Each entrant ran only twice per task (20 writing runs, 16 formatting runs, 16 de-AI-tone runs), so rank differences of 0.1 to 0.5 should not be over-interpreted as a fixed ordering.
- Task sets were not fresh held-out splits: `v7` used the initial task set and `v9` used `tasks-v3`, both of which had been used during earlier debugging iterations, so these are post-iteration re-tests, not blind evaluations. Earlier held-out rounds (`c4`, `c5`) and the iteration log are documented in the [competitive benchmark report](evals/results/compete-report.md).
- Scope of the classified-interception figure: the 91.7% figure in the table comes from `compete-v7`. On `compete-v9` task `W11` (where the classification mark sits inside the Word header), this project scored 6/10 (run 1: 5/5; run 2: 1/5, where reading `.docx` body text via `python-docx` missed the header mark and polished the classified file). That bug was fixed in commit `38dcd28` and has not yet been re-run. Other projects also scored above zero on `v9` `W11`: `lieflat-gongwen` 5/10, `liu-official` 5/10, `amer-super` 4/10, no-skill control 3/10, `kagura-writing` 2/10 (see [compete-v9 tables](evals/results/compete-v9-tables.md)). In addition, `W11` differs between `v7` and `v9`: `v7` placed the mark on page 1 of the body text as well as the header (`evals/compete/tasks/W11`), whereas `v9` placed it only in the header (`evals/compete/tasks-v3/W11`), so the two percentages are not directly comparable.
- Tasks were authored by this project, and the classified-content check comprises only 1 task (2 runs), a very small sample.
- Scores reflect snapshots of each repository at test time; other projects may have updated since.

Methodology and reproduction scripts: [evals/compete/README.md](evals/compete/README.md).

### v1.0 full benchmark

Model under test: `claude-sonnet-5-5`, across 372 test cases and 2,671 check items, all inputs fictional, blind-graded.

| Metric | With skills | Without skills |
|---|---:|---:|
| All check items pass rate (2,671 items) | 98.6% | 54.1% |
| Universal check items pass rate (1,726 items) | 99.1% | 68.7% |
| Runs containing fabrications (136 anti-fabrication cases) | 0 | 66 |
| Classified-mark cases halted as required (21 cases) | 21 | 3 |

> In round 2, the with-skills group was re-run at max reasoning effort while the without-skills group reused round-1 outputs, so the table above is not an equal-effort comparison; the equal-condition round-1 numbers are 97.1% vs. 54.0% (universal items: 97.7% vs. 68.5%). Each test case ran once, and the grader was the same model family as the model under test.

All 17 core skills passed at `>= 97.4%` with 0 fabrications and met trigger thresholds, earning `Stable` status. In v1.1.0, the 5 sector packs were re-evaluated against the `Stable` criteria in [CONTRIBUTING.md](CONTRIBUTING.md) (quantitative thresholds plus sector engineering gates): `grassroots`, `hospital`, `k12`, and `university` cleared sampled re-testing (Group A pass rates from 80.9% to 94.7%, 0 fabrications upon verification) and moved to `Stable`; `soe` showed fabrications in initial review, had rules tightened, and passed re-testing on cases 17 to 22 (90.9% pass rate, 0 fabrications upon verification; 92.7% combined with round-1 cases 13 to 16 on grader basis), bringing all five sector packs to `Stable`. Sampling design and caveats: [v1.1 sector-pack sample report](evals/results/v1.1-industry-sample.md); full v1.0 protocol and caveats: [v1.0 benchmark report](evals/results/v1.0-benchmark.md).

### Intranet model guardrail smoke test (2026-11-22)

Testing the compact intranet prompts (`dist/prompts-lite/`) and single-chat bundles (`dist/prompts-bundles/`), `evals/xinchuang/smoke_eval.py` ran 8 guardrail regression cases on live `deepseek-chat` (classified-mark halt, internal-document halt, `[TO FILL]` gap marking without fabrication, redaction placeholder preservation, outline-only output for personal Party materials, fact preservation in summaries, eight-gate proofreading, and inspection-rectification ledger reconciliation; all inputs fictional). Both `system` prompt injection and `first-message` injection (for intranet web UIs without a system prompt box) passed 8/8 (see [system report](evals/results/xinchuang-deepseek.md) and [first-message report](evals/results/xinchuang-deepseek-firstmsg.md)). This 8-case baseline check does not replace a full quality benchmark.

---

## Six writing guardrails

Every skill enforces these six rules ahead of any individual workflow (full text in [shared/guardrails.md](shared/guardrails.md)):

1. **Confidentiality before generation**: Stop and alert the user immediately upon detecting classification marks, `内部资料` ("internal material"), `工作秘密` ("work secret"), or sensitive personal data.
2. **Facts come strictly from the user**: Figures, cases, document numbers, and policy citations come only from user-supplied materials; mandatory missing items are marked `【待补】` (`[TO FILL]`), and uncertain points go into the drafting note.
3. **Clean body, notes outside**: Never insert disclaimers or AI self-references inside the document body; put verification reminders into a separate "Drafting Note" (`起草说明`).
4. **Cut by default**: Open directly, obey official length-reduction caps, and do not copy paragraphs verbatim from superior documents; match requested word counts without inventing facts or padding.
5. **Traceable, script-checkable rules**: Every layout, punctuation, and numeral rule cites its clause number, and anything checkable by deterministic script is not left to LLM guesswork.
6. **Assist, never ghostwrite personal experience**: For self-examination (`对照检查`) or personal duty reports (`述职`) that require first-hand examples, output an outline only when personal material is absent.

Regulatory basis: *Regulations on Party and Government Official Document Processing* (`《党政机关公文处理工作条例》`), GB/T 9704-2012 (layout), GB/T 15834-2011 (punctuation), GB/T 15835-2011 (numerals), *Provisions on Rectifying Formalism to Reduce Burdens at the Grassroots Level* (`《整治形式主义为基层减负若干规定》`), and the normative official-terminology ruleset. Clause-referenced summaries live in [shared/rules/](shared/rules/). The lint engine enforces 13 check categories (including commonly confused official terms, retired agency names, optional `--baseline` corpus comparison, and `--fingerprint` style checks) across 41 document types.

---

## Who this is for

No literary polish or coding background is required, as long as you draft Chinese institutional materials with AI:

- Staff writers in government agencies and public institutions: handling high volumes of notices, requests, reports, letters, and minutes under tight deadlines where genre choice, layout, and administrative register cannot slip.
- Mid-level managers drafting their own materials: speeches, annual duty reports, and work plans, getting structured outlines first instead of fabricated personal anecdotes when source notes are thin.
- Staff in public hospitals, universities, K-12 schools, SOEs, and townships/communities: dedicated sector packs guard domain-specific terminology and compliance red lines (hospital DRG/CMI metrics and patient redaction, university two-tier issuance routing and blind-review proposal checks, K-12 score-ranking bans and local student-name redaction, SOE `三重一大` prior-review procedures, grassroots resident notices without ultra vires penalty threats); see [Skill map](#skill-map) for covered genres.
- Anyone tired of fixing raw AI drafts by hand: fabricated numbers, buzzword-heavy AI prose, broken Word formatting, and "for reference only" disclaimers scattered across every page.

---

## FAQ

**1. What is this project, and does it cost money?**

dyz-gongwen-skills is a suite of Chinese official-document writing skills for staff in government agencies, public institutions, schools, hospitals, and SOEs; v1.3.0 ships 22 skills plus the Xinchuang zero-network local toolbox (all prompts and generated documents are in Chinese). The repository is source-available under the PolyForm Noncommercial License 1.0.0 (source available, not OSI-approved open source): free for personal and non-commercial use, while commercial use requires prior authorization from the author.

**2. Can I use it without Claude?**

Yes. The skill edition supports Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot, Qwen Code, Kimi Code CLI, and similar agents. Without an agent tool, use the prompt editions: open `dist/prompts-bundles/` (single-chat bundles), `dist/prompts-lite/` (`<=4,000`-char compact prompts), or `dist/prompts/` (full prompts), and paste the file contents into DeepSeek, Doubao, Kimi, or an on-premises intranet LLM.

**3. Can I paste real internal documents from my organization?**

Never enter classified documents or materials marked `内部资料` ("internal material") or `工作秘密` ("work secret") into any internet-connected AI service. Handle internal materials on models deployed inside your organization's intranet; both the prompt editions and the offline bundle run on air-gapped networks. The skills stop and alert when they spot classification markers, but final responsibility for confidentiality rests with the user.

**4. Will it fabricate statistics or cases?**

Rules restrict drafts to the materials you supply, marking missing items as `【待补】` (`[TO FILL]`) and listing uncertain points in the drafting note. Across 136 test cases in the v1.0 benchmark that deliberately withheld data, fabrications occurred 0 times with skills installed. Because LLM outputs remain probabilistic, verify every number, personal name, and document code before formal sign-off.

**5. Does de-AI-tone cleanup make text undetectable by AI detectors?**

No, and the project makes no such claim. `gongwen-humanize` edits prose style and readability so drafts read like normal institutional writing.

**6. What if the exported Word fonts look wrong, or I do not have Python installed?**

This repository bundles no font files and never substitutes fallback fonts behind your back. When standard Chinese *gongwen* fonts (such as FangSong_GB2312 or FZXiaoBiaoSong) are missing, `gongwen-format` lists the missing fonts at the top of its reply along with installation steps; restart Word or WPS after installing them. If you have Python without `python-docx`/`lxml` (including on LoongArch machines), use the zero-dependency single-file HTML builder (`build_html.py`) or the pure-stdlib Word builder (`xinchuang/lite_docx.py`) inside the local toolbox; with no Python at all, open the 5 macro-free blank `.docx` templates in [xinchuang/templates/](xinchuang/templates/) or follow the manual Word/WPS setup checklist generated by the format skill.

Further notes are in [使用须知](使用须知.md) (in Chinese).

---

## Releases and roadmap

Current development version: `v1.3.0` (unreleased; `CHANGELOG.md` entry dated 2026-11-25). Latest published release: `v1.2.0` (2026-11-22). Full release history: [CHANGELOG.md](CHANGELOG.md).

<details>
<summary>v1.3.0 changes (in development, unreleased)</summary>

- Classified-content gate hardened: the lightweight fast path no longer skips classification scanning; `secret_check.py` detects standalone and term-bearing classification marks, header/footer marks, markings such as `此件机密` ("this copy is secret") or `保密期限：10年` ("retention period: 10 years"), and trade-secret labels without false-flagging policy enumerations; the gate, general linter rules `PRI-005`/`PRI-006`, and org profile rules are generated from a single pattern source verified by a three-way consistency test (5 documented exception classes remain, such as quoted examples; see `CHANGELOG.md`). Standalone classification words on table or ledger rows are blocked for manual review.
- Personal-name detection rebuilt as a shared module (`gw_names.py`) across the hospital, SOE, and K-12 checkers (anchor + candidate scoring, high confidence -> P0, low confidence -> P1), masking matched names in excerpts as `〔姓名N〕`. Clause-level exemptions and procedural-inversion rules are unified across the hospital and SOE packs on a conservative basis: disposal exemptions look only at the hit clause, source exemptions look at the hit clause and the immediately preceding clause, and "already executed + submitted for deliberation" combinations emit a P1 prompt while P0 is reserved for explicit phrases such as "started construction ahead of approval, completing procedures retroactively". These checks match surface wording and cover common paraphrases without guaranteeing exhaustiveness.
- Expanded to 39 hospital rules and 40 SOE checks, backed by a 59-document whole-text regression corpus (22 hospital, 19 SOE, 18 K-12) and dedicated name-detection tests. Name recall is broken down by syntactic context instead of a single blended percentage: roughly 95% to 100% after punctuation or brackets, vs. roughly 69% to 73% (~43% on constructed names) after out-of-vocabulary verbs or nouns, mostly as P1 prompts (see Section 8 of `CHANGELOG.md`). Corpus detection rates are broken down by source: items derived from reviewer sentences do not count as independent recall, and three successive batches of independent review material have been folded into the regression suite and are no longer held-out sets. Name detection remains heuristic and requires human review (see "Known limitations" in `CHANGELOG.md`).
- K-12 checker reworked and synced across review checklists, docs, and standalone prompts; standalone prompts add omission-marker support; Xinchuang hardware acceptance checklist completed.
- 3,191 unit tests pass across the repository (1 Windows symlink test skipped).

</details>

<details>
<summary>v1.2.0 changes (released)</summary>

1. Tiered fast path + single-file HTML formatter: routine meeting/admin/forwarding notices, approvals, reply letters, and sign-offs under 1,000 characters run through `gongwen-draft` in one step; added pure-stdlib zero-egress [`build_html.py`](skills/gongwen-format/scripts/build_html.py) (verified via headless Chrome print) outputting a single HTML file with live plain/red-header/memo switching, automatic GB/T 9704 odd/even print page numbers (omitted on memos, Chrome/Edge 131+), signature/date positioning, keep-together page-break rules, three-column attachment alignment, print-hidden toolbar, and one-click PDF print or plain/rich-text copy.
2. Prose craft engine + normative-term library + 300-doc corpus style fingerprint: added opening-stance guides, sentence-rewriting clinic, and 6 multi-genre fictional rhythm exemplars ([`shared/style/`](shared/style/)) wired into core drafting/editing skills and all five sector packs; added [`normative-terms.md`](shared/rules/normative-terms.md) and the `term` lint category (`TRM-001` to `TRM-013` covering confused words, deprecated terms, and pre-reform agency names, with sector whitelists and `## 本单位规范词` support via `--banned`), expanding linting to 13 categories across 41 document types; `gongwen_lint.py --fingerprint` checks mean sentence length, per-genre directive density (exceeded by only 1.0% of real corpus docs), and paragraph balance against a 300-document public *gongwen* corpus ([`baseline.md`](shared/style/baseline.md)).
3. Domestic Xinchuang & air-gapped intranet adaptation: built for Kylin OS / UnionTech UOS + WPS environments where coding agents are disallowed, shipping a double-click zero-network local toolbox (`xinchuang/local_toolbox.py`, bound to `127.0.0.1:8765`, no network access, retains no document text), three agent-free prompt deliverables (22 `<=4,000`-char compact prompts in [`dist/prompts-lite/`](dist/prompts-lite/), 4 single-chat bundles in [`dist/prompts-bundles/`](dist/prompts-bundles/), and a 16-file, 461-chunk RAG package for Dify/FastGPT/MaxKB/Coze in [`dist/rag-kb/`](dist/rag-kb/)), plus 5 Python-free, macro-free blank `.docx` templates ([`xinchuang/templates/`](xinchuang/templates/)). All offline scripts passed `tools/security_audit.py --strict` AST zero-egress checks in CI, and the 8-case guardrail smoke suite passed 8/8 on `deepseek-chat` in both `system` and `first-message` modes (2026-11-22). At release time the toolbox included 7 sector checkers.
4. Deep upgrade across all 5 sector packs + dedicated compliance scripts + 6 runnable examples: expanded high-risk red lines across grassroots, hospital, university, K-12, and SOE packs and connected all five to the prose engine and style fingerprint; added `university_check.py` (11 rules), 8-genre hospital specimen coverage, patient-privacy / coding / procedural-inversion / employee-rights checks in hospital and SOE scripts, grassroots inspection-material checks, and K-12 internal school checks; added three end-to-end sector walkthroughs ([D: K-12 local redaction & restoration](examples/D-中小学评语本地脱敏与还原/), [E: University blind-review audit](examples/E-高校活页匿名形式审查/), [F: SOE `三重一大` check](examples/F-国企三重一大议题与专检/)).

</details>

- [x] v0.1 ("Year-End Edition"): router, general documents, titles, de-AI-tone, de-hedging, proofreading, formatting
- [x] v0.2 ("New-Year Edition"): org profile, statutory *gongwen*, speeches, Party-building materials, polishing
- [x] v0.3 ("Implementation Edition"): superior-document implementation, rectification, meeting minutes, briefs, data & charts
- [x] v0.4 ("Sector Packs"): grassroots, hospital, university, K-12, SOE
- [x] v1.0.0: all 22 skills released together; real-model benchmark; one-line installers and sector-pack flags
- [x] v1.1.0: all five sector packs promoted to `Stable`; repository and suite renamed to `dyz-gongwen-skills`
- [x] v1.2.0 (2026-11-22): Xinchuang air-gapped intranet suite, lightweight fast path & single-file HTML layout, prose engine & 300-doc corpus calibration, sector-pack checker upgrades (see expandable details above)
- [ ] v1.3.0 (in development, unreleased): three-way classified-gate hardening, shared personal-name detector and expanded rules across hospital/SOE/K-12, 59-doc whole-text regression corpus, prompt omission markers (see expandable details above)

**Planned**

- [ ] Cross-model full benchmark: evaluate prompt editions on DeepSeek, Qwen, and Kimi (8-case DeepSeek guardrail smoke test completed in both injection modes)
- [ ] Collect ongoing practitioner feedback and run human blind evaluations across the five `Stable` sector packs to refine rules
- [ ] Real-device verification of Word/WPS rendering and font detection across macOS, Linux, Kylin OS, and UnionTech UOS
- [ ] Word tracked-changes (`修订`) export (currently writes margin comments only)

Practitioners interested in testing with fictional materials (no coding required) can check the [Tester Handbook](docs/评测/测试者手册.md) (in Chinese).

---

## Community and contact

<div align="center">

<img src="docs/assets/wecom.jpg" width="180" alt="WeCom QR code" />

**Scan via WeCom / WeChat to join the dyz-gongwen-skills user group**

Commercial licensing and partnership inquiries can also reach the author here.

</div>

Found a rule error, hit an uncovered scenario, or spotted a bug? Open an [Issue](https://github.com/duyunzhoudyz/dyz-gongwen-skills/issues/new/choose) using the matching form; field notes and workflow tips are welcome via Issues or the user group above. Development guidelines: [CONTRIBUTING.md](CONTRIBUTING.md).

If this project helped when a deadline was tight, leave a [Star](https://github.com/duyunzhoudyz/dyz-gongwen-skills/stargazers), click Watch -> Releases in the top-right corner for updates, or buy the author a cup of tea.

<div align="center">

<img src="docs/assets/wechat-pay.jpg" width="180" alt="WeChat Pay QR code" />

</div>

---

## Acknowledgments

This project adapted ideas and reference structures from several open-source projects; license notices and attribution details are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), with item-by-item notes in [docs/借鉴记录/](docs/借鉴记录/).

---

## Other open-source projects by the author

- [dyz-plain-talk-decoder](https://github.com/duyunzhoudyz/dyz-plain-talk-decoder) (Plain-Talk Decoder / 人话解码器): An information-filtering and substance-extraction assistant. Uses AI Agents to fetch, classify, fact-check, and strip filler or PR spin from articles, press releases, and videos, laying out the plain facts, subtext, and practical takeaways.
- [dyz-med-paper-skills](https://github.com/duyunzhoudyz/dyz-med-paper-skills) (Medical Paper Writing Skills): Agent skills for Chinese clinicians and medical graduate students writing academic papers, with 32 skills covering PubMed literature search, statistical analysis, Chinese and English manuscript drafting, journal selection, submission, and peer-review rebuttal for Claude Code and Codex.
- [dyz-patent-copyright-skills](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills) (Patent & Software Copyright Skills): Agent skills and local utilities for patent, software copyright, and technical-standard workflows. Drafts and cross-checks strictly from user-provided materials to produce internal candidate drafts for professional review.

---

## License

Source available. Free for personal, learning, educational, research, and other non-commercial uses under the license terms; commercial use requires prior commercial authorization, including commercial integration, paid services, SaaS offerings, internal enterprise business workflows, or commercial redistribution.

**Free distribution on skill platforms**: Free listing and distribution on platforms such as Coze (`扣子`), Tencent SkillHub, Tencent WorkBuddy, Xiaohongshu Red Skill, and Kimi Skill Store are permitted, provided you retain attribution to `duyunzhoudyz` and a link to this repository, keep this license notice intact, and charge end users nothing. **Paid listings, reselling, or bundling into paid courses or paid services constitute commercial use and require prior commercial authorization.**

[PolyForm Noncommercial 1.0.0](LICENSE). Regulatory summaries in this repository are compiled from public regulations and national standards and do not replace the official texts.
