---
name: llm-wiki-rehealth
description: 当需要对 LLM 生成的 Wiki 仓库进行修复/维护时加载——修复孤立页面、失效 wikilink、重复页面、缺失的 frontmatter 元数据，规范化 related 链接。不适用于创建新 wiki、回答 wiki 内容问题、或修改 llm_wiki 应用代码。
---

# llm-wiki-rehealth

对 LLM 生成的 wiki 仓库做确定性修复与维护。**只改 markdown 仓库，不改应用代码。**

## 何时用 / 何时不用

- **用**：wiki 出现重复页、孤岛页、失效 `[[链接]]`、frontmatter 缺字段、`related` 是裸字符串。
- **不用**：创建新 wiki、做内容查询、给 llm_wiki 打补丁。

## 核心工作流（5 步）

1. **审计** `python scripts/audit.py --root <wiki或项目根>` → 读分级报告（含 H 类批注残留统计）。
2. **审阅** → 向用户呈现修复计划与影响面（涉及文件数）。
3. **修复**（按下方「修复顺序」执行；逐个先 dry-run 再 `--apply`；脚本自动备份到 `.llm-wiki/repair-backup/`）。
4. **复跑 audit** 验证问题下降，且未引入新孤立/失效；**问题批注文档残留（H 类）必须为 0**。
5. **输出修复统计报告**（任务结束时，markdown 格式）：按 `assets/修复统计报告-模板.md` 填写，保存到项目根。
   **报告末尾必须附「摄入中断任务清单」**——由 `check_ingest_progress.py` 生成，逐条列出发生摄入中断的**源文件路径**（可续传的断点 / 不可续传的已丢弃页面）。

命令速查见 `references/commands.md`；场景区分见 `references/scenarios.md`。

## 修复顺序（依赖关系，勿颠倒）

**① 问题批注文档修复（最前，优先级最高）** → ② `fix_links` → ③ `fix_related` → ④ `fix_frontmatter` → ⑤ 重复页合并（最后，因为它会重写链接）。每次 `--apply` 前先 dry-run。

**为什么批注文档必须排最前**：

1. 批注文档（尤其 B 类）内部已写明「X 页与 Y 页可能重复 / 命名冲突 / 内容张力」等线索——先处理可直接**消化掉一批重复与命名问题，减少后续 merge 候选与人工标注量**；
2. 清除 A 类占位页后，audit 的孤立页/游离页统计不再被上千个占位页污染，**后续报告更准确**；
3. 占位页删除时会重写指向它的链接——若放到最后做，会把已合并的链接再改一遍，徒增重写量。

## 重复页标注与合并（推荐流程）

1. `audit.py` 产出候选 → `annotate_duplicates.py` 启动 WebUI，展示 **concepts/entities 同目录**候选（悬停预览前 500 字、批量选择、勾选合并 + 合并后文件名[按命名规范推荐] + 备注[优先级最高]）。
2. 用户点「完成并提交」→ `reports/annotations-<date>.json`（group/name/note）。
3. LLM 按 `assets/merge-draft-template.md` 起草每组合并稿 `reports/merge-result-<name>.md`（**union 全部 sources/tags/related**，正文择优融合）。
4. `merge_annotations.py` 执行：写合并稿到 `<dir>/<name>.md` → 全 wiki 重写链接（含 frontmatter related 裸字符串）→ index 重定向 → 删被删页 → 全部备份。
5. 复跑 `audit.py` 验证；按 `assets/llm_wiki合并结果清单-模板.md` 填生成合并结果清单。

## 问题批注文档修复（非知识页清理）

LLM 生成的 wiki 会沉淀两类**非知识页面**（识别特征、决策树详见 `references/problem-annotations.md`）：

- **A 类 Wiki Lint 占位页**：`tags` 含 `stub`/`lint` + 正文固定句 `Created by Wiki Lint as a placeholder...`，是失效链接目标的自动占位（实测 1534 个）。
- **B 类 Ingest 分析批注页**：文件名=问题描述（常带时间戳）、frontmatter 极简（tags/sources 空）、正文指出重复/命名冲突/内容张力并给建议。

流程：

1. `scan_problem_annotations.py` 分类扫描：A① 有同义真实页 / A② 描述性批注 / A③ 真实知识缺口；B 按问题类型归档。
2. 按决策树修复。**批注中的「需人工审核 / 人工确认 / 用户决定」字样不构成阻塞**——维护任务已授权，Agent 直接判断处理，不要反过来询问用户。
3. 可由页面间对比/合并/拆分解决的（A①、B 重复与命名类）→ 直接解决；涉及**知识缺口、文档缺失、内容矛盾与张力**（A③、B 冲突类）→ **必须联网检索**核实后再修。
4. 处理完**删除批注页**，把结论落到目标页面，并重写指向占位页的 `[[链接]]`。
5. **最终必须清零**：修复完成后 wiki 仓库内不得残留任何批注文件——验收标准 = 复跑 `audit.py` 的 **H 类「问题批注文档残留」为 0**（未清零 = 修复未完成）。
6. **环境前置检查**：启动修复前确认环境存在可用网络检索工具（按当前环境实际提供的检索能力探测，勿写死工具名）；**若不存在 → 立即停止任务并向用户发送警告**，不得凭记忆编造。

## Gotchas

1. **合并前必读权威元数据**：`ingest-cache.json`（源→页面映射）与 `page-history/`（旧版）。一个页面可能被多个源共享，删错无法恢复。
2. **`sources/` 摘要页绝不参与合并**：它们是资料摘要，不是知识页面；与概念/实体页同 key 时剔除，保留。
3. **related 数组可能混合格式**：裸字符串 + `[[...]]` 混排。含 `[[` 的数组跳过自动改写，交人工。
4. **同名歧义先判类型**：`entities/BM25` vs `concepts/BM25` 是类型判定漂移，合并前先用 `references/naming.md` 判定归属，别简单删一个。
5. **孤立页面判定口径**：`index.md`/`log.md`/`overview.md` 的目录项**不算**入链——它们只是导航。真正的知识连接是页面间 `[[...]]`。
6. **失效链接降级是单向操作**：`[[X]]` → 纯文本 `X` 后结构丢失。dry-run 务必检查降级清单，`degraded-links-*.json` 即知识缺口清单。
7. **别改 index.md 的确定性结构**：合并后建议跑 `rebuild_wiki_index` 或让用户在应用内重建，避免手工与程序冲突。
8. **跨平台注意**：脚本用正斜杠路径；Windows 下用 `PYTHONIOENCODING=utf-8` 防乱码。
9. **frontmatter 标准格式（必查）**：元数据第一行 `---`、中间字段、最后一行 `---`，结束 `---` 后**换行再写正文**（正文紧贴 `---` 会致解析紊乱）。所有脚本写盘前经 `ensure_frontmatter_std` 规范化；audit D 类统计"格式不规范 / 未闭合"。
10. **写盘脚本曾丢 frontmatter**：历史 fix_links 只写 body 丢元数据（已修，写盘保留 frontmatter 原文）。若遇无 frontmatter 回归，用 `scripts/restore_frontmatter.py` 从 `.llm-wiki/repair-backup/` 恢复。
11. **合并 = concepts/entities 目录内部相似页的融合写入，非删一留一**：查重**仅限 `concepts/` 与 `entities/` 两个目录的内部**（同目录分组），**不跨目录**——`concepts/x` 与 `entities/x` 即使同名也不算重复；同目录内多个归一化相似的页面才构成候选。其他目录（comparisons/sources/queries/findings/...）不参与。合并稿必须 union 全部原页面的 `sources`/`tags`/`related`（来源一个不丢），正文择优融合，然后才删被删页、重写引用。模板见 `assets/merge-draft-template.md`。标注用 `scripts/annotate_duplicates.py`（WebUI 批量选择）或 `scripts/generate_merge_review.py`（Obsidian 清单），用户标注后返回，只合并被标注的组。
12. **孤立判定口径**：audit 只统计 body 正文 `[[...]]` 入链；frontmatter 的 `related` 规范化后不计入——related 已建立关联但 audit 仍报孤立，属统计口径而非修复无效。
13. **问题批注文档不是知识页**：`tags:[stub,lint]` 的 Wiki Lint 占位页、以及"问题描述"命名的分析批注页，都要专门清理（`scan_problem_annotations.py` + `references/problem-annotations.md`）。批注里的"需人工确认"已被授权直接处理；涉知识缺口/矛盾张力必须联网检索；**环境中无可用网络检索工具时立即停止并警告用户**。删除占位页后务必重写指向它的链接，否则产生新的失效链接。

## 参考

- `references/commands.md` — 十一个脚本的完整用法与参数（含辅助工具）
- `references/scenarios.md` — 快速体检 / 深度大扫除 / 合并专项 / 跨 Agent 平台 / 应用内触发
- `references/naming.md` — 类型判定树 + slug 规范化 + 统一重命名规则
- `references/linking.md` — 链接规范与降级策略
- `references/problem-annotations.md` — 问题批注文档（非知识页）识别特征 + 修复决策树 + 网络检索前置检查
- `references/llm-wiki-data.md` — `.llm-wiki/` 数据利用指南（各项数据详细程度、摄入中断检测与续传可行性分析）
- `assets/merge-draft-template.md` — LLM 合并稿输出模板（融合写入 + union sources）
- `assets/llm_wiki合并结果清单-模板.md` — 合并结果清单模板
- `assets/修复统计报告-模板.md` — 修复统计报告模板（任务收尾输出，末尾含**摄入中断任务清单**）
