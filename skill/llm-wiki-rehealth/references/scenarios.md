# 应用场景区分

不同使用场景对应不同的命令组合与审批深度。**按场景路由，不要混用。**

## 场景 A：快速体检（低风险，可自动）

适合"最近摄入了一些源，想确认 wiki 没坏"。

```
audit.py --root <root>                    # 看健康度
fix_links.py --root <root>                # dry-run 失效链接
fix_frontmatter.py --root <root>          # dry-run 元数据
```
确认影响面小 → `--apply`。**不跑 merge**（合并是高风险操作）。

## 场景 B：深度大扫除（全流程，需审批）

适合仓库长期使用后问题堆积（孤岛/重复/失效多）。

```
audit.py --root <root>
scan_problem_annotations.py --root <root>     # ① 最前：问题批注文档（内含重复线索，先消化）
#   按 references/problem-annotations.md 决策树修复（涉知识缺口/矛盾张力时先探测网络检索工具）
audit.py --root <root>                        # 复跑：占位页清理后统计更准确
# 审阅报告 → 分阶段修复：
fix_links.py --root <root> --apply
fix_related.py --root <root> --apply          # 可选 --backlink
fix_frontmatter.py --root <root> --apply
merge_duplicates.py --root <root>             # 列候选 → 逐组 draft → LLM 起草 → 人工确认 → apply
audit.py --root <root>                        # 复验（H 类批注残留须为 0）
# 收尾：
check_ingest_progress.py --root <root>        # 摄入中断检测（可续断点 / 已丢弃页面）
# 按 assets/修复统计报告-模板.md 输出「修复统计报告」，保存到项目根
#   —— 报告末尾必须附「摄入中断任务清单」，逐条列出中断的源文件路径
```
**顺序不可颠倒**：**问题批注文档最前**（内含重复/冲突线索，先处理可减少后续去重工作量、且让统计更准），然后链接/元数据，最后合并（合并会重写链接）；**任务结束时输出修复统计报告**。

## 场景 C：合并专项（只做去重）

适合"只有重复页问题，其余健康"。

```
merge_duplicates.py --root <root>
# 逐组处理，人工审批每次合并
```
用 `--draft` 导出上下文 → LLM 起草合并稿（模板见 `assets/merge-draft-template.md`）→ 人工确认 → `--apply --result`。

## 场景 D：跨 Agent 平台（无 Claude 环境）

脚本是纯 Python 标准库，任何 Agent / 命令行直接可用：

```bash
python scripts/audit.py --root /path/to/wiki
python scripts/fix_links.py --root /path/to/wiki --apply
```
无需 Claude，无需安装依赖。SKILL.md 只是把这套流程封装为可复用的"维护纪律"。

## 场景 E：llm_wiki 应用内触发

在 llm_wiki 的 Chat Agent 中，用户可直接要求"运行 wiki 维护脚本"：
- 脚本路径指向 wiki 项目根；
- 用 `--out` 把报告写到应用可见位置；
- 合并后让应用重建 index（避免手工改 index 与程序冲突）。

## 场景互斥矩阵

| 场景 | 问题批注 | fix_links | fix_related | fix_frontmatter | merge | 审批要求 |
|------|---------|-----------|-------------|-----------------|-------|---------|
| A 快速体检 | ❌ | ✅ 自动 | ❌ | ✅ 自动 | ❌ | 低 |
| B 深度大扫除 | ✅ **最前** | ✅ | ✅ | ✅ | ✅ | 高（merge 必审批） |
| C 合并专项 | 按需 | ❌ | ❌ | ❌ | ✅ | 最高（每组合并审批） |
| D/E 复用 | 按需 | 按需 | 按需 | 按需 | 按需 | 视仓库规模 |

## 触发词映射（给 agent 的路由）

- 用户说"体检一下 wiki" / "看看 wiki 有没有问题" → 场景 A
- "大扫除" / "维护 wiki" / "修复 wiki" → 场景 B（**先做问题批注文档清理**）
- "太多重复页面" / "合并重复页" → 场景 C
- "清理批注页 / 占位页 / 问题文档 / stub 页" → 场景 B 的第一步（`scan_problem_annotations.py`）
- 用户明确要在其他平台/应用内跑 → 场景 D/E
