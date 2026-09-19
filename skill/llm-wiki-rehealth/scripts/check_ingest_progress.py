# -*- coding: utf-8 -*-
"""检测 llm_wiki 未完成的摄入任务（断点续传可行性分析）。

读 `.llm-wiki/ingest-progress/*.json`：`completedThrough < chunkTotal` 的源即为**摄入中断**，
脚本报告断点位置与已有中间产物（globalDigest / analyses），并给出续传所需上下文。

同时汇总 `.llm-wiki/ingest-warnings.log` 的丢弃块——那类中断**不可续**（失败块原文已丢），
属知识缺口，只能重建。

用法:
  python check_ingest_progress.py --root <wiki或项目根> [--out <报告目录>]
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ensure_utf8_stdout, parse_args, write_json_report, p


def resolve_paths(root):
    if os.path.basename(os.path.abspath(root)) == "wiki":
        return os.path.dirname(root), root
    cand = os.path.join(root, "wiki")
    if os.path.isdir(cand):
        return root, cand
    return root, root


def main():
    ensure_utf8_stdout()
    opts, _ = parse_args(sys.argv[1:], "检测未完成的摄入任务")
    project_root, wiki_root = resolve_paths(opts["root"])
    llm_dir = os.path.join(project_root, ".llm-wiki")
    prog_dir = os.path.join(llm_dir, "ingest-progress")
    warn_log = os.path.join(llm_dir, "ingest-warnings.log")

    if not os.path.isdir(prog_dir):
        p(f"[提示] 无 ingest-progress 目录（{prog_dir}），无法检测摄入断点。")
    records, incomplete = [], []
    if os.path.isdir(prog_dir):
        for fn in sorted(os.listdir(prog_dir)):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(prog_dir, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except (OSError, ValueError):
                continue
            ct = d.get("chunkTotal") or 0
            done = d.get("completedThrough") or 0
            rec = {
                "file": fn,
                "source": d.get("sourceIdentity", ""),
                "source_hash": d.get("sourceHash"),
                "source_length": d.get("sourceLength"),
                "source_budget": d.get("sourceBudget"),
                "target_chars": d.get("targetChars"),
                "overlap_chars": d.get("overlapChars"),
                "chunk_total": ct,
                "completed": done,
                "global_digest_chars": len(d.get("globalDigest") or ""),
                "analyses_blocks": len(d.get("analyses") or []),
                "updated": time.strftime("%Y-%m-%d %H:%M",
                                         time.localtime((d.get("updatedAt") or 0) / 1000))
                if d.get("updatedAt") else "-",
            }
            records.append(rec)
            if done < ct:
                rec["resume_from_chunk"] = done + 1
                incomplete.append(rec)

    p("== llm_wiki 摄入任务状态 ==")
    p(f"  进度记录: {len(records)} 条")
    p(f"  已完成: {len(records) - len(incomplete)}  |  **中断未完成: {len(incomplete)}**")
    if incomplete:
        p("\n  --- 可接续的中断任务 ---")
        for r in incomplete:
            p(f"    {r['source']}")
            p(f"      断点: 第 {r['resume_from_chunk']}/{r['chunk_total']} 块（已完成 {r['completed']}）")
            p(f"      续传所需: 源指纹 {r['source_hash']} | 长度 {r['source_length']} | "
              f"budget {r['source_budget']} | target {r['target_chars']} | overlap {r['overlap_chars']}")
            p(f"      已有中间产物: 全局摘要 {r['global_digest_chars']} 字符 / 分块分析 {r['analyses_blocks']} 块")
            p(f"      最后更新: {r['updated']}")
        p("\n  → 续传动作需由 llm_wiki 应用重新触发摄入（本技能只读 wiki，不改应用代码）；")
        p("    上述指纹与分块参数可用于校验源未变更、并从第 completedThrough+1 块续跑。")
    else:
        p("\n  无可接续的中断任务（全部完成）。")

    # 截断丢弃（记录头 = `## 时间 | 源文件`，段内为被丢弃的目标页面）
    dropped = []
    if os.path.exists(warn_log):
        with open(warn_log, "r", encoding="utf-8", errors="replace") as f:
            t = f.read()
        for blk in re.split(r"^## ", t, flags=re.M)[1:]:
            lines = blk.split("\n")
            m = re.match(r"([\d\-T:.Z]+)\s*\|\s*(.*)$", lines[0])
            ts, src = (m.group(1), m.group(2).strip()) if m else ("?", lines[0].strip())
            pages = re.findall(r'FILE block "([^"]+)" was not closed', blk)
            if src or pages:
                dropped.append({"time": ts, "source": src, "pages": pages})
    by_src = {}
    for d in dropped:
        by_src.setdefault(d["source"], []).extend(d["pages"])
    n_pages = sum(len(d["pages"]) for d in dropped)

    p(f"\n== 截断丢弃（ingest-warnings.log）: {n_pages} 页 / {len(dropped)} 次摄入 / {len(by_src)} 个源文件 ==")
    p("  **可定位到源文件**：每条记录 = `时间戳 | 源文件路径` + 该次摄入中被丢弃的目标页面。")
    p("  原因均为模型输出截断（max_tokens / timeout / 连接中断）；失败块原文未保留 → **不可续传**，")
    p("  只能作为知识缺口按 references/problem-annotations.md 重建。")
    if by_src:
        p("  按源文件聚合（丢弃页数降序）:")
        for src, pages in sorted(by_src.items(), key=lambda x: -len(x[1]))[:10]:
            p(f"    {len(pages)} 页 ← {src}")
            for pg in pages[:3]:
                p(f"         └ {pg}")
        if len(by_src) > 10:
            p(f"    ... 其余 {len(by_src) - 10} 个源见报告 JSON")

    report_dir = opts.get("out") or os.path.join(project_root, "reports")
    out = write_json_report(report_dir, "ingest-progress-check", {
        "records": records,
        "incomplete": incomplete,
        "dropped": dropped,
        "dropped_by_source": {k: v for k, v in
                              sorted(by_src.items(), key=lambda x: -len(x[1]))},
    })
    p(f"\n完整报告: {out}")


if __name__ == "__main__":
    main()
