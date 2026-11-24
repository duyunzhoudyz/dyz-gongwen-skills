# 政务内网 RAG 知识库切片包（Dify / FastGPT / MaxKB / 扣子私有版）

本目录由 `tools/build_prompts.py --xinchuang` 自动生成，共 16 个切片文件、462 个标准知识片。
每个切片均以 `---` 分隔，顶部带 `[知识来源 | 分类 | 小节]` 语义锚点，无需二次清洗即可直接入库。

## 一、平台对照

| 平台 | 用哪个文件 | 分段怎么设 | 详细步骤 |
|---|---|---|---|
| Dify | `chunks/` 下全部 `.md`；应用模板 `dify-app-template.yml` | 自定义分段，标识符 `---`，最大分段长度 1600，重叠长度 0 | 本文第二节 |
| FastGPT | `fastgpt/qa-import.csv` | 模版导入，不分段，一行一条数据（`q`、`a` 两列） | `fastgpt/README.md` |
| MaxKB | `chunks/` 下全部 `.md`；或 QA 文件 `maxkb/qa-import.csv` | 高级分段，标识符 `---`，分段长度 1600；QA 文件不用分段 | `maxkb/README.md` |
| 扣子（Coze Studio 开源版） | `chunks/` 下全部 `.md` | 文本知识库自定义分段，标识符 `---`，最大长度 1600，重叠度 0，以实际界面为准 | `coze/README.md` |

## 二、导入方法

### Dify（私有化内网版）
1. 左侧「知识库」→「创建知识库」→ 批量上传 `chunks/` 下的全部 `.md` 文件。
2. 分段设置选「自定义」，分段标识符填 `---`，最大分段长度设 `1600`，重叠长度 `0`。
3. 左侧「工作室」→「导入 DSL 文件」，选择 `dify-app-template.yml`，在上下文中关联刚建好的知识库，切换为本单位内网模型即可发布给全单位使用。

### FastGPT / MaxKB / 扣子
1. 各平台的导入步骤、分段设置和注意事项见 `fastgpt/README.md`、`maxkb/README.md`、`coze/README.md`。
2. FastGPT 用 `fastgpt/qa-import.csv`；MaxKB 上传 `chunks/` 下的 `.md`（高级分段填 `---`），或导入 `maxkb/qa-import.csv`；扣子上传 `chunks/` 下的 `.md`。
3. 新建应用，将 `dist/prompts-lite/gongwen.md` 或 `dify-app-template.yml` 中的 `pre_prompt` 粘贴为系统提示词，关联知识库即可。

## 三、切片清单

| 文件 | 主题 | 切片数 |
|---|---|---:|
| `chunks/01-guardrails.md` | 红线与保密 | 9 |
| `chunks/02-tiaoli.md` | 公文处理条例 | 17 |
| `chunks/03-doc-types.md` | 文种决策与辨析 | 39 |
| `chunks/04-gbt9704.md` | 国标格式9704 | 13 |
| `chunks/05-gbt15834.md` | 标点规范15834 | 13 |
| `chunks/06-gbt15835.md` | 数字规范15835 | 10 |
| `chunks/07-jianfu.md` | 基层减负规定 | 8 |
| `chunks/08-data-expression.md` | 数据表述规范 | 15 |
| `chunks/09-normative-terms.md` | 规范用词与机构旧称 | 5 |
| `chunks/10-ai-tone.md` | 去AI腔规范 | 5 |
| `chunks/11-defensive.md` | 去防御腔规范 | 10 |
| `chunks/12-output-format.md` | 输出与交接规范 | 6 |
| `chunks/13-roles.md` | 角色模式 | 11 |
| `chunks/14-calendar.md` | 写作日历 | 11 |
| `chunks/15-unit-profiles.md` | 7类单位画像 | 83 |
| `chunks/16-skills-workflows.md` | 各公文技能工作流 | 207 |
