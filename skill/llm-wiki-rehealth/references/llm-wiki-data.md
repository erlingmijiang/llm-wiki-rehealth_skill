# `.llm-wiki/` 数据利用指南

`<项目根>/.llm-wiki/` 是 llm_wiki 应用的运行状态目录（实测 122M），内含**修复所需的权威元数据**。本文件说明每项数据的用途、信息详细程度，以及**中断任务的检测与接续分析**。

## 一、数据清单与用途

| 数据 | 规模 | 技能用途 | 详细程度 |
|---|---|---|---|
| `ingest-cache.json` | 448K | audit F 类交叉验证（哪些页面不在任何摄入记录）；合并前防误删 | `entries[源] = {hash, timestamp, filesWritten:[页面]}`——**完整源→页面映射** |
| `ingest-warnings.log` | 30K | audit G 类知识缺口清单 | 每条含时间戳、源、被丢弃的页面路径、原因文本；**不保留失败块原文** |
| `ingest-progress/*.json` | 2.1M / 47 条 | 摄入断点检测（见第二节） | **分块级进度 + 逐块中间产物**（详见下） |
| `page-history/` | 3.7M / 430 份 | 合并前内容比对、误删回溯 | 页面旧版（文件名 = 路径 + 时间戳），含完整 frontmatter + 正文 |
| `history/*.json` | 9.0M / 678 条 | 操作审计、内容级回滚 | `[{id, path, timestamp, author, tool, content全文}]`——**逐次写入的完整内容** |
| `file-snapshot.json` | 2.0M | 判断文件是否被外部改动 | `files[相对路径] = {hash, size, mtimeMs}` + `updatedAt` |
| `image-caption-cache.json` | 4.6M | 图片语义检索/页面补充 | `{sha256: {caption}}`——图片 AI 描述 |
| `repair-backup/` | 技能自产 | 所有 fix/merge 的备份与回滚源 | 技能写入，非应用数据 |
| `review.json` / `lint.json` | 空 `[]` | —— | **应用自带的审核/lint 机制从未执行**（这解释了问题长期堆积） |
| `chats/` `agent-sessions/` `conversations.json` `chat-preferences.json` `project.json` `*-queue.json` `lancedb/` | 小/空 | 与 wiki 维护无关 | 应用运行时状态 |

## 二、中断任务：能获得什么、能否接续

### 2.1 `ingest-progress/*.json` —— 可分块级续传

单条记录字段：

```
sourceIdentity   源文件路径
sourceHash       源指纹（校验源是否变更）
sourceLength     源字符数        sourceBudget     处理预算
targetChars      分块目标长度    overlapChars     块间重叠窗口
chunkTotal       总块数          completedThrough 已完成块数
globalDigest     全局摘要（中间产物，数千字）
analyses         逐块分析结果数组（中间产物，每块一段）
updatedAt        最后更新时间
```

**判定**：`completedThrough < chunkTotal` → 该源摄入**中断**。

**能得到的详细程度**（远超"仅知道中断了"）：
- 中断在**第几块**、还剩几块；
- **逐块中间产物**（`analyses`，如 `## Chunk 1/7 — Page 1 主要摘要：…`）与全局摘要 `globalDigest`；
- 续传所需的全部参数（源指纹、长度、budget、target、overlap）；
- 中断时间。

**能否接续**：信息层面**足以从第 `completedThrough+1` 块续跑**；但**执行续传需由 llm_wiki 应用重新触发摄入**——本技能只读写 wiki 的 markdown，不改应用代码，也不驱动应用队列。

### 2.2 `ingest-warnings.log` —— **可定位到源文件**，但不可续传

记录格式（每条一段）：

```
## <ISO 时间戳> | <源文件路径>
1. FILE block "wiki/<目录>/<页面>.md" was not closed before end of stream
   — likely truncation (model hit max_tokens, timeout, or connection dropped). Block dropped.
```

**能确认是摄入哪个原文件时中断的**：
- 每条记录头都带**源文件路径**，可精确定位到「**哪个源 → 什么时间 → 哪几个页面被丢弃**」；
- 可**按源文件聚合**（实测 87 页 / 87 次摄入 / **58 个源文件**，例如「`【已做废】AgentScope(v1.0) 技术文档.md`」丢 3 页、「`AgentScope 2.0.md`」丢 3 页、「`OpenAI Agents SDK.md`」丢 3 页）；
- 一次摄入生成多页时，能明确哪几页丢失。

**但**：
- 原因实测 100% 为 `truncation`（仅粗粒度，不含具体错误堆栈或会话上下文）；
- **失败块原文未保留**，也不指明丢在源文件的哪一段（无 chunk 位置）；
- 因此**不可续传**，这些条目按知识缺口处理：补建（必要时联网检索）或降级链接。

检测：`python scripts/check_ingest_progress.py --root <root>` 会输出按源文件聚合的中断明细。

### 2.3 检测命令

```
python scripts/check_ingest_progress.py --root <root>
```

输出：未完成摄入清单（源、断点位置、续传参数、已有中间产物、时间）+ 截断丢弃块清单 + 可续性判断。

## 三、技能对这些数据的使用边界

- **只读**：`ingest-cache.json`、`ingest-warnings.log`、`ingest-progress/`、`page-history/`、`history/`、`file-snapshot.json`、`image-caption-cache.json`；
- **只写**：`repair-backup/`（修复前备份）；
- **绝不触碰**：应用运行必需文件（`project.json`、`file-snapshot.json`、`conversations.json`、`chats/`、`agent-sessions/`、`*queue*.json`、`lancedb/`）——避免与程序状态冲突；
- `review.json` / `lint.json` 为空是**正常现象**，不是损坏，不要"修复"。

## 四、与修复流程的衔接

1. 修复前：`check_ingest_progress.py` 看有无可续的摄入断点；`audit.py` 读 F/G 类得游离页与知识缺口。
2. 合并前：查 `ingest-cache.json` 确认目标页的来源，查 `page-history/` 比对旧版，避免删错。
3. 修复后：`repair-backup/` 保留回滚能力；如需内容级回滚，可查 `history/` 中同一 path 的历史写入。
