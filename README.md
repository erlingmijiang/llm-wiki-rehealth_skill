# llm-wiki-rehealth

对 LLM 生成的 Wiki 仓库做**确定性修复与维护**的技能包。不修改 llm_wiki 应用本身，只作用于实际产生的 markdown 仓库。

## 背景

Karpathy 的 LLM Wiki 理念 + nashsu 的 llm_wiki-main 工程实现，在**大规模长期使用**后暴露出五类问题：

| 问题 | 规模（以测试样例仓库实证） | 根因 |
|------|---------------------|------|
| 重复页面 | 450 组（P0=300 / P1=119 / P2=31） | 类型判定漂移 + 无模糊去重 |
| 孤立页面 | 3124 个（无正文入链） | related 全用裸字符串，不入链 |
| 失效链接 | 167 处 | 概念缺口 + 链接形式不统一 |
| 元数据缺失 | 480 个缺 updated | 整文件重写，updated 未被强制 |
| 截断丢页 | 83 个（ingest-warnings.log） | FILE block 截断未修复，静默丢弃 |

**系统性根因**：确定性逻辑过弱，过度信任每次摄入时 LLM 的现场决定；命名、类型、链接语法在数百次摄入后必然漂移。

## 设计

- **确定性脚本**（`scripts/`，纯 Python 标准库，跨 Agent 平台）：audit / fix_links / fix_related / fix_frontmatter / merge_duplicates。
- **维护纪律**（`rules/`）：命名判定树、slug 规范化、链接规范。
- **安全**：所有修改 dry-run 预览 → 备份到 `.llm-wiki/repair-backup/` → 落盘。
- **权威参考**：修复前读取 `.llm-wiki/ingest-cache.json`（源→页面映射）与 `page-history/`（页面旧版）。

## 使用

```bash
# 1. 审计
python scripts/audit.py --root <wiki或项目根>

# 2. 修复（逐个，先 dry-run 再 --apply）
python scripts/fix_links.py --root <root>            # dry-run 预览
python scripts/fix_links.py --root <root> --apply    # 执行（先备份）
python scripts/fix_related.py --root <root> --apply --backlink
python scripts/fix_frontmatter.py --root <root> --apply

# 3. 合并重复页（人工审批）
python scripts/merge_duplicates.py --root <root>                       # 列候选组
python scripts/merge_duplicates.py --root <root> --group <key> --draft # 导出合并上下文
#  → LLM 起草合并稿，人工确认
python scripts/merge_duplicates.py --root <root> --group <key> --apply --result <合并稿.md>

# 4. 复跑 audit 验证健康度
```

## 目录

```
SKILL.md                工作流入口（Hub）：触发条件 + 核心工作流 + Gotchas
scripts/                确定性脚本（纯 Python 标准库，跨 Agent 平台）
  common.py             共享库
  audit.py              全量审计（五类问题 + 交叉验证）
  fix_links.py          失效链接降级
  fix_related.py        related 规范化
  fix_frontmatter.py    元数据补齐
  merge_duplicates.py   重复合并
references/             Spokes：按需加载的重文档
  commands.md           命令完整用法
  scenarios.md          应用场景区分（快速体检/大扫除/合并专项/跨平台/应用内）
  naming.md             类型判定树 + slug 规范化
  linking.md            链接规范与降级策略
assets/                 模板
  merge-draft-template.md  LLM 合并稿输出模板
README.md               本文档
```

## 已知边界

- `sources/` 摘要页不参与合并删除。
- 含 `[[` 的混合 related 数组、歧义匹配、缺 title 的页面 → 只标记，交人工。
- 原项目的代码层缺陷已整理为独立 issue 文档（见工作区），供原开发者修复。
