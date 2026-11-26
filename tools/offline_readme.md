# 离线使用说明

这份说明随离线包一起发布，写给在单位内网（不能上外网的电脑）里用 dyz-gongwen-skills 的同志。包里的东西不需要联网就能用，只有安装 Python 依赖这一步例外，下面会逐条说明。

## 一、先看保密提醒

1. **涉密信息严禁输入任何联网 AI 工具。** 带密级标识（绝密、机密、秘密）的材料，以及标注“内部资料”“工作秘密”的材料，都不要粘贴到公网上的 AI 服务里。
2. 内网模型也要先问清楚。涉密信息只能在经批准的涉密信息系统中处理，本项目不提供也不替代任何保密资质。用之前请向本单位保密部门确认：这个内网模型所在的网络，允许处理到哪一级的材料。
3. 个人信息先脱敏再输入：身份证号、手机号、病案号、学号、家庭住址，以及患者、学生的真实姓名等。
4. 本项目的脚本只在本机运行，不访问网络，不收集数据。
5. 带到内网的 U 盘、光盘要按本单位规定登记和查毒。

完整的使用须知见包里的“使用须知.md”。

## 二、包里有什么

| 位置 | 内容 |
|---|---|
| `dist/prompts/` | 提示词版：每个 skill 一份 .md 文件，复制全文就能给内网模型用。索引见 `dist/prompts/README.md` |
| `dist/prompts-lite/`、`dist/prompts-bundles/`、`dist/rag-kb/` | 信创精简提示词、一站式合集、知识库切片及导入模板，由 `tools/build_prompts.py` 生成 |
| `xinchuang/` | 本机工具箱及 Linux、Windows 启动器、轻量排版脚本、`templates/` 空白 DOCX 模板、`lite/` 提示词和部署验收文档，来自仓库同名目录 |
| `skills/` | 全部 skill 的完整目录，含参考资料和可运行的脚本 |
| `install.ps1`、`install.sh`、`tools/install.py`、`.claude-plugin/marketplace.json` | 一键安装脚本、安装器及清单，用于把 skill 装进本机的 Agent 工具（第五节） |
| `README.md` | 项目主页。里面的 `git clone`、`/plugin marketplace add`、`npx skills add` 等安装方式都要联网，离线时不用看，按本说明操作 |
| `使用须知.md`、`LICENSE`、`THIRD_PARTY_NOTICES.md`、`CHANGELOG.md` | 使用须知、许可证、第三方说明、更新记录 |
| `离线使用说明.md` | 本说明，由仓库中的 `tools/offline_readme.md` 改名入包 |
| `wheelhouse/`（若随包提供） | 构建时收集的离线 Python 依赖，来源为仓库根目录下已准备的 `wheelhouse/` |
| `安全自查报告.md`、`SHA256SUMS.txt` | 打包时由 `tools/security_audit.py` 生成的静态审计报告和文件哈希清单 |

## 三、在内网模型里使用提示词（最常用）

内网模型指单位自己部署的大模型对话页面，或者单位统一采购的 AI 写作平台。不需要装任何软件。

1. 打开 `dist/prompts/` 文件夹，第一次用先打开 `gongwen.md`（总入口）。用记事本、WPS 或任何文本编辑器打开都行，按 Ctrl+A 全选，按 Ctrl+C 复制。
2. 在内网模型里新建一个对话，把全文粘贴进去。有两种放法，任选一种：
   - **放进系统提示词**：如果平台有“系统提示词”“角色设定”“智能体指令”“预设”之类的输入框，粘贴到那里。这样整个对话都按它的要求办事，效果最稳。
   - **作为第一条消息**：平台没有上述输入框时，直接粘贴成对话的第一条消息，发送出去。模型回复“已了解”之类的话以后，再说你要写什么。
3. 然后用平常说话的方式提需求，把材料贴进对话，如“下周要交科室年终总结，素材我贴在下面”。
4. 一个对话只用一份提示词。要换到另一个 skill（比如写完初稿要排版），当前对话会给你一张“交接卡”。新开一个对话，先粘贴下一份提示词，再粘贴交接卡和材料，接着往下做。

几点说明：

- 完整提示词版每份硬上限为 29000 字符（见 `tools/build_prompts.py` 的 `MAX_PROMPT_CHARS`）。粘贴后如果模型提示内容过长，或者回答明显漏掉了前面的要求，说明这个模型的上下文长度不够，请换一个上下文更长的模型，或者请平台管理员调大上限。
- 提示词版没法运行脚本。里面的“自检清单”需要你对照着人工逐项检查，模型也会在回复里提醒。
- 该装行业包的单位，用对应的提示词文件，如医院用 `gongwen-hospital.md`。文件名和用途见 `dist/prompts/README.md`。
- 模型写出来的稿子，事实、数据、政策依据都要你自己核对。稿子里的【待补】【待核实】标记，定稿前要逐条补齐。

## 四、运行 skill 自带的脚本（有 Python 的电脑）

脚本可以帮你检查标点、数字写法、格式要素、AI 腔，也能把稿子排成符合国家标准的 Word。没有 Python 也能用，只是这些检查要改成人工对照清单。

**需要的软件**

- Python 3.9 及以上。在命令行里运行 `python --version`（有的电脑要用 `python3 --version`）可以查看版本。
- 排版（生成 Word）和 Excel 表格需要两个扩展包：`python-docx`、`openpyxl`。只做文字检查（`gongwen_lint.py`）不需要它们。

**怎么运行**

打开命令行，进入包解压出来的文件夹，用下面这样的命令。以检查一份通知稿为例：

```text
python skills/gongwen-review/scripts/gongwen_lint.py 通知正文.txt --doc-type 通知
```

各脚本的用法见对应 skill 的 `SKILL.md` 里“自检清单”一节，加 `--help` 可以看中文参数说明。脚本检查出的问题分三级：P0 必须改，P1 建议改，P2 请人工判断。

**安装扩展包要联网**

`pip install python-docx openpyxl` 这条命令会从网上下载，内网电脑直接运行会失败。办法如下：

1. 找一台能上外网、系统和 Python 版本与内网电脑相同的电脑，运行：

   ```text
   python -m pip download python-docx openpyxl -d wheels
   ```

   下载的文件会放进 `wheels` 文件夹。这台外网电脑上不要放任何单位材料。
2. 把 `wheels` 文件夹按本单位规定带进内网，在内网电脑上运行：

   ```text
   python -m pip install --no-index --find-links wheels python-docx openpyxl
   ```

这一步办不到也没关系：Word 排版会改为给出 WPS/Word 的手动设置清单，其他功能不受影响。

## 五、装进本机的 Agent 工具（可选）

如果内网电脑上装了 Claude Code、Qwen Code、Codex、Cursor 等 Agent 工具，可以用包里的安装脚本把 skill 装进去。不装也不影响第三节的用法。

- Windows：在解压出来的文件夹地址栏输入 `powershell` 回车，运行 `powershell -ExecutionPolicy Bypass -File .\install.ps1`
- macOS、Linux、国产系统：在该文件夹打开终端，运行 `bash install.sh`
- 想先看会装到哪里、不真正写入：Windows 在命令末尾加 `-WhatIf`，其他系统加 `--dry-run`
- 要加装行业包（医院、高校、中小学、国企、基层）：命令末尾加 `--pack hospital`，可选 `hospital`、`university`、`k12`、`soe`、`grassroots`，或 `all`
- 想卸载：命令末尾加 `--uninstall`，看过要删除的清单再加 `--yes`

脚本运行中会问是否安装排版依赖。内网电脑没有外网时直接回车跳过，按第四节的办法处理。

## 六、哪些步骤需要联网

| 步骤 | 是否联网 |
|---|---|
| 复制 `dist/prompts/` 里的提示词到内网模型 | 不需要 |
| 运行 `gongwen_lint.py` 等 skill 自带脚本 | 不需要 |
| 运行安装脚本，把 skill 复制进本机 Agent 工具 | 不需要 |
| 安装 `python-docx`、`openpyxl`（`pip install`） | 需要，办法见第四节 |
| `README.md` 里的 `git clone`、`/plugin marketplace add`、`npx skills add`、访问 GitHub | 需要，离线时不用 |
| 你所用的 AI 模型本身 | 内网模型不出单位网络；公网模型要联网，不得输入涉密和内部敏感信息 |

## 七、遇到问题

- 提示词粘贴后模型不按要求办事：检查是否完整复制了全文（文件很长，别漏了结尾），再确认模型上下文够长。
- 命令行提示找不到 `python`：试试 `python3`，或者请单位信息中心安装 Python 3.9 及以上版本。
- 脚本报“缺少 python-docx”：按第四节安装，或者先不排版，只用文字检查。
- 其他问题和改进建议：项目主页的 Issues 页面（需要联网，请不要在上面贴任何单位材料）。

## 八、国产信创电脑（银河麒麟、统信 UOS、WPS）

单位电脑是国产操作系统、不能用编程类智能体工具时，按下面用。全部由你手动点击或运行，没有后台自动执行的部分。

1. **本机工具箱（双击即用）**：Linux 双击 `xinchuang/启动工具箱.sh` 或 `xinchuang/启动工具箱.desktop`，Windows 双击 `xinchuang/启动工具箱.bat`，启动器会尝试自动打开默认浏览器。在终端直接运行 `python3 xinchuang/local_toolbox.py --auto-port` 时，请在浏览器中手动打开终端显示的地址（默认 `http://127.0.0.1:8765`）。在一个页面里完成：一键复制内网提示词、直接导入 `.docx`/`.txt`/`.md` 做涉密检测（含页眉页脚）与双向脱敏还原、八关机检、事实数字核对、字体自检、国标排版下载 `.docx`（没有 `python-docx`/`lxml` 时自动改用内置零依赖轻量排版）、OFD 结构体检。只监听本机回环地址，不联网、不调模型，不保存正文（个别功能仅在本机临时目录瞬时处理、用后即删），多标签页映射表相互隔离，关闭窗口即销毁。
2. **命令行脱敏与还原**：`python3 skills/gongwen-review/scripts/desensitize.py mask 原稿.txt -o 脱敏稿.txt --map 映射表.json`，模型改稿后用 `restore` 还原。映射表用完请删除，不要外传。命中密级标识或“内部资料”等字样时直接拦截；脱敏不能让涉密材料进入非涉密系统。
3. **零依赖排版与免宏模板**：工具箱、脱敏、机检、事实核对、OFD 体检、轻量国标排版（`xinchuang/lite_docx.py`）和 `.docx` 读取全部只用 Python 标准库，不需要 `pip`。完整七种版式（红头套打、联合行文、表格）才需要 `python-docx`、`openpyxl`；若离线包内附带 `wheelhouse/`，按对应架构目录的 `INSTALL.txt` 离线安装。如果既没装 Python、信息中心又禁用了 WPS 宏，直接打开 `xinchuang/templates/` 下的 5 套 GB/T 9704 空白 `.docx` 模板（白头、红头、纪要、签报、综合材料）粘贴正文即可；允许用宏时可用 `skills/gongwen-format/assets/wps_gongwen_macro.js`，或按 `skills/gongwen-format/references/xinchuang.md` 手动设置。
4. **OFD**：导出 OFD 后可在工具箱直接点「⑧ OFD 结构体检」上传，或命令行运行 `python3 skills/gongwen-format/scripts/ofd_check.py 成稿.ofd`。折行、红线、印章位置仍要用阅读器或打印核对。
5. **提示词档位**：系统提示词框字数受限的，用 `dist/prompts-lite/`（22 份全精修，每份不超过 4000 字）。想在一个对话里走完起草、去腔、核稿的，用 `dist/prompts-bundles/`（4 套一站式合集）。单位信息中心要搭 Dify、MaxKB、FastGPT、扣子开源版的，用 `dist/rag-kb/` 的知识库切片和 `dify-app-template.yml`。
6. **交给信息中心审查与真机验收**：包根目录的《安全自查报告.md》是对全部 Python 脚本和 JS 宏的静态审计结果；`SHA256SUMS.txt` 用于核对文件未被改动，运行 `sha256sum -c SHA256SUMS.txt`；给信息中心和办公室领导审阅的架构对比与部署方案见 `xinchuang/单位信息中心入网评估与部署指引.md`，15 分钟真机打卡表见 `xinchuang/信创真机验收清单.md`。
