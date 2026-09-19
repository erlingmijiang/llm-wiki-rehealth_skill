# 合并稿模板（LLM 输出格式）

阅读 `reports/merge-draft-<key>.md` 后，按本模板生成合并稿，保存为 `reports/merge-result-<key>.md`。

## 合并的定义：concepts/entities 目录内部相似页的融合写入，而非删一留一

合并 = 把 **`concepts/` 与 `entities/` 目录内部**（同目录分组，**不跨目录**；`concepts/x` 与 `entities/x` 同名不算重复）确认重复的文档**重新融合写入**为一个页面
（其他目录如 comparisons/sources/queries/findings 不参与查重）：

- **元数据保留合并前的所有来源**：`sources`/`related`/`tags` 取全部原页面的并集（去重），一个都不丢；
- **正文择优融合**：每页独有的章节都保留；
- **修改其他页面的引用**：全 wiki 指向被删页的 `[[旧slug]]` 统一重写为 `[[保留slug]]`（脚本自动完成）；
- 绝不是"只保留其中某一个、删掉其他"——被删页的信息必须完整进入保留页。

## frontmatter 字段 union 规则

```markdown
---
type: <权威 type：同名歧义按 references/naming.md 判定；concept/entity 合并取内容更像者>
title: <取信息更完整者，或更规范的命名>
created: <各组中最早的 created 日期，保留页面出生时间>
updated: <今天>
tags: <所有页面 tags 的并集，去重>
related: <所有页面 related 的并集，去重，统一 [[slug]] 形式>
sources: <所有页面 sources 的并集，去重 —— 合并前的所有来源都必须保留>
---

# <合并标题>

<融合后的正文>
```

## 正文融合规则

1. 概述取更完整、更新的版本；
2. 每个来源特有的章节保留并合并（避免信息丢失）；
3. 若两页有矛盾信息，保留双方并标注来源，如 "（来源A）…" / "（来源B）…"，不替用户做判断。

## 硬性要求

1. **sources 必须并集**（最关键：合并前的所有来源都不能丢，它们可能来自不同源）。
2. **created 取最早**；`updated` 盖今天。
3. **正文择优融合，不砍信息**：更完整版本为主，另一页独有的章节追加。
4. **矛盾保留双方**，用来源标注，不替用户判断。
5. **不要改变 wiki 结构文件**：不写 index.md / log.md / overview.md；不创建新页面。
6. **合并稿 frontmatter 用标准格式**：
   - 第一行 `---`
   - 中间为字段
   - 最后一行 `---`
   - `---` 结束后换行，再写正文（正文不紧贴 `---`）。
   （脚本写入时还会用 `ensure_frontmatter_std` 兜底，但请直接输出标准格式。）

## 合并后由脚本完成的事（无需你做）

- 写合并稿到保留页（自动规范化 frontmatter 格式）
- 重写全 wiki 指向被删页的 `[[旧slug]]` → `[[保留slug]]`
- index 条目重定向
- 删除被删页
- 全部先备份到 `.llm-wiki/repair-backup/`
