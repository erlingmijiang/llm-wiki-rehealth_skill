# 命令速查

所有脚本均纯 Python 标准库，`--root` 接受 **wiki 目录**或**含 wiki/ 的项目根**。默认 dry-run，`--apply` 才写盘（先备份到 `.llm-wiki/repair-backup/`）。输出 JSON 报告到 `reports/`（可用 `--out <dir>` 指定）。

## audit.py — 全量审计

```
python scripts/audit.py --root <root>
```

输出五类分级报告 + 交叉验证：
- **A 孤立页面**（无任何页面正文 `[[...]]` 入链；index/log/overview 不算）
- **B 失效链接**（指向不存在的页面）+ 高频失效目标（概念缺口）
- **C 重复页面**（P0 字符串归一化相等 / P1 核心token子集 / P2 语义近似）
- **D frontmatter 缺失**（type/title/created/updated）
- **E related 链接形式**（裸字符串 vs `[[wikilink]]`）
- **F ingest-cache 交叉验证**（哪些页面不在任何摄入记录）
- **G 截断丢弃页面**（来自 ingest-warnings.log）

## fix_links.py — 失效链接降级

```
python scripts/fix_links.py --root <root> [--apply]
```

- 指向不存在页面的 `[[目标]]` → 纯文本（保留 alias）。
- 每个被降级目标写入 `reports/degraded-links-<date>.json`（知识缺口清单）。

## fix_related.py — related 规范化

```
python scripts/fix_related.py --root <root> [--apply] [--backlink]
```

- 裸字符串项 → `[[slug]]`，**仅当归一化后唯一命中**存在页面。
- 歧义（多同名）、混合格式（含 `[[`）→ 跳过交人工。
- `--backlink`（可选）：仅对孤立目标页补反向链接。默认不动作。

## fix_frontmatter.py — 元数据补齐

```
python scripts/fix_frontmatter.py --root <root> [--apply]
```

- `type` 由目录推断（concepts→concept 等）。
- `created`/`updated` 盖章当天。
- 缺 `title` **只标记不自动填**（避免把 slug 当标题）；未闭合 frontmatter 只标记。

## merge_duplicates.py — 重复页面合并

```
python scripts/merge_duplicates.py --root <root> [--include-sources]        # 列候选组
python scripts/merge_duplicates.py --root <root> --group <key> --draft      # 导出合并上下文
python scripts/merge_duplicates.py --root <root> --group <key> --apply --result <合并稿.md>
```

- 默认剔除 `sources/` 摘要页（`--include-sources` 可纳入，谨慎）。
- **保留页选取**：字节更大 / sources 更多 / 入链更多。
- `--apply` 执行：写合并稿 → 全 wiki 重写指向被删页的链接 → index 重定向 → 删旧页，全部先备份。

## 常用参数

| 参数 | 作用 |
|------|------|
| `--root <path>` | wiki 目录或项目根（自动探测） |
| `--apply` | 执行写入（默认 dry-run） |
| `--out <dir>` | 报告输出目录 |
| `--backlink` | fix_related：对孤立目标页补反向链接 |
| `--include-sources` | merge：纳入 sources/ 摘要页 |
| `--group <key>` / `--result <md>` | merge：指定组与合并稿 |

## 辅助工具

### restore_frontmatter.py — 恢复丢失的 frontmatter

```
python scripts/restore_frontmatter.py --root <root>            # 从今天备份恢复无 frontmatter 文件
python scripts/restore_frontmatter.py --root <root> --date 2026-08-16
```

- 修复脚本 bug 导致写盘丢 frontmatter 后的回归恢复：从 `.llm-wiki/repair-backup/<文件>.<日期>.bak` 提取原 frontmatter，拼上当前正文重组写回（并套用标准格式）。
- 无备份的文件跳过并报告（不误改）。

### generate_merge_review.py — 生成重复页人工审批清单

```
python scripts/generate_merge_review.py --root <root>
```

- 依据最新 `reports/audit-*.json` 生成 `reports/duplicates-review.md`：每组以 Obsidian 链接 `[[目录/标题]]` 列出 + 元数据（type/字节/sources/created/入链），⭐ 标注建议保留。
- 用户逐组标注 `**→ 合并为 [[保留页]]**` 后返回，Agent 只合并被标注的组。

### annotate_duplicates.py — WebUI 重复页标注工具（推荐交互）

```
python scripts/annotate_duplicates.py --root <root> [--port 8765]
```

- 启动本地 WebUI，浏览器弹出展示 concepts/entities **同目录**重复候选组（不跨目录）。
- 鼠标悬停文件路径 → 浮层预览正文前 500 字（移开收回）；批量选择（全选/按级/反选/条件反选/取消）；勾选「合并此组」→ 填「合并后文件名」（按命名规范推荐）+「备注」（优先级最高）。
- 点「完成并提交」→ 保存 `reports/annotations-<date>.json`（group/name/note），服务器自动关闭，供 merge 执行。

### check_ingest_progress.py — 摄入中断检测与续传可行性

```
python scripts/check_ingest_progress.py --root <root> [--out <报告目录>]
```

- 读 `.llm-wiki/ingest-progress/*.json`：`completedThrough < chunkTotal` 即**摄入中断**，报告断点位置、续传参数（源指纹/长度/budget/target/overlap）与已有中间产物（globalDigest、逐块 analyses）。
- 同时汇总 `ingest-warnings.log` 的截断丢弃块（**不可续**，属知识缺口，只能重建）；记录头含**源文件路径**，输出按源聚合的中断明细。
- 续传动作需由 llm_wiki 应用重新触发摄入（本技能只读 wiki，不驱动应用）。
- **任务收尾必备**：其结果填入 `assets/修复统计报告-模板.md` 的第五节「摄入中断任务清单」。

### scan_problem_annotations.py — 扫描问题批注文档（非知识页面）

```
python scripts/scan_problem_annotations.py --root <root> [--out <报告目录>]
```

- 识别 **A 类 Wiki Lint 占位页**（细分：① 有同义真实页 → 删占位+重定向 / ② 描述性批注型 → 删占位 / ③ 真实知识缺口 → 补建）与 **B 类 Ingest 分析批注页**（按 重复 / 命名冲突 / 内容张力 / 覆盖更新 / 消歧核查 分类）。
- 输出 `reports/problem-annotations-<date>.json`；修复决策树与网络检索前置检查见 `references/problem-annotations.md`。

### merge_annotations.py — 按标注执行重复页融合合并

```
python scripts/merge_annotations.py --root <root> [--annotations <json>] [--draft-dir <dir>]
```

- 读 annotations JSON + LLM 起草的合并稿 `reports/merge-result-<name>.md`。
- 写合并稿到 `<dir>/<name>.md`（遵循命名规范），全 wiki 重写指向被删页的链接（含 frontmatter related 裸字符串）→ 新 slug，index 重定向，删被删页，全部先备份到 `.llm-wiki/repair-backup/`。
