# LLM Wiki 合并结果清单

> 合并日期：____-__-__
> 审计来源：`reports/audit-____.json` ｜ 标注来源：`reports/annotations-____.json`
> 合并组数：__ 组 ｜ 删除 __ 页 ｜ 重写 __ 个文件
> 备份位置：`.llm-wiki/repair-backup/`

## 合并明细

| # | 合并后文件 | 合并前页面 | 备注 |
|---|-----------|-----------|------|
| 1 | [[目录/合并后文件名]] | [[目录/旧页1]]、[[目录/旧页2]] | 补充说明 |
| 2 |  |  |  |

## 说明

- 合并原则：**concepts/entities 目录内、同目录**相似页融合写入（不跨目录），合并后文件名遵循命名规范（`references/naming.md`），frontmatter **union 全部 sources/tags/related**，正文择优融合。
- 流程：`annotate_duplicates.py`（WebUI 标注，勾选合并 + 合并后文件名 + 备注）→ LLM 按 `assets/merge-draft-template.md` 起草合并稿 `reports/merge-result-<name>.md` → `merge_annotations.py` 执行（写目标文件、全 wiki 重写链接、删被删页、备份）。
- 所有变更先备份至 `.llm-wiki/repair-backup/`，可用 `restore_frontmatter.py` 或备份目录回滚。
