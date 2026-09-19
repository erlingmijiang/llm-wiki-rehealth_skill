# llm-wiki-rehealth

> 为 LLM 自动生成的 Wiki 仓库做**确定性修复与维护**。
> *Deterministic repair & maintenance for LLM-generated wikis.*

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

一套即插即用的 **Agent Skill + 纯 Python 工具包**。它只作用于 wiki 的 **markdown 仓库**，不修改 llm_wiki 应用本身——把「LLM 写出来的知识库会持续劣化」当作**确定性问题**来治理，而不是靠每次摄入时模型的临场发挥。

## 它解决什么问题

LLM Wiki（Karpathy 理念 / llm_wiki 等实现）在数百次摄入后会**必然漂移**：命名、类型判定、链接语法都无法保持一致。典型退化：

| 退化 | 表现 | 实测规模\* |
|---|---|---|
| **重复页面** | 同一概念被建成多个页面（命名/类型漂移） | 582 组 |
| **孤立页面** | 页面无任何正文入链 | 4771 个 |
| **失效链接** | `[[X]]` 指向不存在的页面 | 1325 处 |
| **元数据缺陷** | 缺 `updated`、结束符写成 `--`、`---` 未独占一行 | 651 个 |
| **问题批注文档** | 软件自动扫描产生的占位页/批注页，非知识内容 | 1580 个 |
| **摄入丢页** | 模型输出截断，页面被静默丢弃 | 154 页 |

<sub>\* 真实仓库实测（11k+ 页规模）。这些数字不是个例，而是长期运行的常态。</sub>

**系统性根因**：确定性逻辑过弱，过度信任每次摄入时 LLM 的现场决定。

## 核心能力

### 1. 全量审计（A–H 八类）
```bash
python skill/llm-wiki-rehealth/scripts/audit.py --root <wiki或项目根>
```
孤立页 / 失效链接 / 重复页（P0–P2 三级置信）/ frontmatter（字段 + 格式）/ related 形式 / ingest-cache 交叉验证（游离页）/ 截断丢页 / **问题批注残留**。

### 2. 确定性修复
| 脚本 | 作用 |
|---|---|
| `fix_links.py` | 失效链接降级为纯文本 + 输出**知识缺口清单** |
| `fix_related.py` | `related` 裸字符串 → `[[wikilink]]`（仅唯一命中时改写） |
| `fix_frontmatter.py` | 补齐 `type`/`created`/`updated`（类型由目录推断） |
| `fix_frontmatter_format.py` | 修复 `--` 结尾、结束符紧贴前一行、正文紧贴 `---` |
| `restore_frontmatter.py` | 从备份重组，恢复被误写丢失的 frontmatter |

### 3. 人机协作去重（核心特色）
去重不是「保留一个、删掉其他」，而是**融合写入**：

```
audit.py                →  列出重复候选组（concepts/entities 同目录，不跨目录）
annotate_duplicates.py  →  本地 WebUI：悬停预览前 500 字、批量选择（全选/按级/反选）
                           勾选合并 + 按命名规范推荐合并后文件名 + 备注（优先级最高）
        ↓ 用户完成标注 → annotations-<date>.json
LLM 起草合并稿           →  union 全部 sources/tags/related，正文择优融合
merge_annotations.py    →  写入目标文件 → 全 wiki 重写引用（含 related 裸串）
                           → 删被删页 → 备份
```

保证「合并前引用的每一个来源都不丢」，且合并后文件名符合统一命名规范，避免二次返工。

### 4. 问题批注文档清理
识别并清理软件自动生成的**非知识页面**：`tags:[stub,lint]` 的 Wiki Lint 占位页，以及「问题描述」命名的 ingest 分析批注页。含三段决策树（重定向 / 删除 / 补建）与**网络检索前置检查**。

### 5. 数据洞察
从 `.llm-wiki/` 运行状态中提取权威元数据：`ingest-cache.json`（源→页面映射）、`page-history/`（页面旧版）、`ingest-progress/`（**摄入断点与逐块中间产物**）、`ingest-warnings.log`（可定位到**源文件**的截断丢页清单）。

## 快速开始

```bash
git clone https://github.com/erlingmijiang/llm-wiki-rehealth_skill.git
cd llm-wiki-rehealth_skill/skill/llm-wiki-rehealth

# 1. 审计（只读，先看健康度）
python scripts/audit.py --root /path/to/your/wiki

# 2. 确定性修复（默认 dry-run，加 --apply 才写盘，写前自动备份）
python scripts/fix_links.py --root /path/to/your/wiki              # 预览
python scripts/fix_links.py --root /path/to/your/wiki --apply      # 执行

# 3. 重复页合并（WebUI 标注 → 融合合并）
python scripts/annotate_duplicates.py --root /path/to/your/wiki

# 4. 复跑验证
python scripts/audit.py --root /path/to/your/wiki
```

**环境要求：Python 3.8+，零第三方依赖**（纯标准库），跨平台（Windows / macOS / Linux）。

## 完整工作流

```
① scan_problem_annotations.py   问题批注文档清理（最前：内含重复线索，先消化）
② fix_links.py                  失效链接降级
③ fix_related.py                related 规范化
④ fix_frontmatter.py            元数据补齐
④ fix_frontmatter_format.py     元数据格式规范化
⑤ merge_annotations.py          重复页融合合并（人工标注）
⑥ audit.py                      复跑验证（批注残留须为 0）
⑦ 输出修复统计报告               末尾附「摄入中断任务清单」
```

**顺序不可颠倒**：批注文档最前（可减少后续去重工作量、让统计更准），合并最后（它会重写链接）。

## 设计原则

- **确定性优先**：所有修复由脚本完成，规则可复现，不依赖模型临场判断。
- **安全默认**：一切写操作**默认 dry-run**，`--apply` 才落盘，写前自动备份到 `.llm-wiki/repair-backup/`，可一键回滚。
- **高风险操作必须人工审批**：合并走 WebUI 标注，LLM 只起草、不擅删。
- **只读应用状态**：仅读取 `.llm-wiki/` 的元数据做决策，绝不改动应用运行文件。
- **跨 Agent 平台**：纯标准库脚本，可在任何 Agent / CI / 命令行中运行。

## 目录结构

```
skill/llm-wiki-rehealth/
├── SKILL.md                工作流入口：触发条件 + 核心工作流 + 修复顺序 + Gotchas
├── scripts/                13 个确定性脚本（纯 Python 标准库）
│   ├── common.py                    共享库（归一化/frontmatter 解析/备份）
│   ├── audit.py                     A–H 八类全量审计
│   ├── fix_links.py                 失效链接降级
│   ├── fix_related.py               related 规范化
│   ├── fix_frontmatter.py           元数据补齐
│   ├── fix_frontmatter_format.py    元数据格式规范化
│   ├── scan_problem_annotations.py  问题批注文档分类扫描
│   ├── annotate_duplicates.py       WebUI 重复页标注工具
│   ├── generate_merge_review.py     生成人工审批清单
│   ├── merge_duplicates.py          合并（CLI 流程）
│   ├── merge_annotations.py         按标注执行融合合并
│   ├── restore_frontmatter.py       从备份恢复 frontmatter
│   └── check_ingest_progress.py     摄入中断检测与续传可行性
├── references/             按需加载的规范文档
│   ├── commands.md                 全部脚本用法
│   ├── scenarios.md                场景区分（体检 / 大扫除 / 合并 / 跨平台）
│   ├── naming.md                   类型判定树 + 统一重命名规则
│   ├── linking.md                  链接规范与降级策略
│   ├── problem-annotations.md      问题批注文档识别与修复决策树
│   └── llm-wiki-data.md            .llm-wiki/ 数据利用与中断接续分析
└── assets/                 模板
    ├── merge-draft-template.md          合并稿模板
    ├── llm_wiki合并结果清单-模板.md      合并结果清单
    └── 修复统计报告-模板.md              修复统计报告（含摄入中断清单）
```

## 作为 Agent Skill 使用

把 `skill/llm-wiki-rehealth/` 放入 Agent 的 skills 目录（如 Claude Code 的 `.claude/skills/`），即可在对话中直接触发：

> 「帮我修复这个 wiki 仓库」「wiki 里有太多重复页面」「清理 wiki 里的批注页/占位页」

`SKILL.md` 会自动加载工作流与注意事项；脚本也可脱离 Agent 独立运行。

## 已知边界

- **跨目录同名不算重复**：`concepts/x` 与 `entities/x` 是类型判定漂移，需人工判归属，不自动合并。
- **`sources/` 摘要页不参与合并**：它们是资料摘要，不是知识页面。
- **歧义相关只标记不改写**：混合格式的 `related` 数组、多义匹配、缺 `title` 的页面均交人工。
- **去重范围**：仅 `concepts/` 与 `entities/` 目录内部（同目录）。
- **摄入丢页不可续传**：截断丢弃的页面原文未保留，只能按知识缺口重建；摄入**断点**可续（`ingest-progress`），但需由 llm_wiki 应用重新触发。

## License

[MIT](LICENSE) © 2026 ELMJ
