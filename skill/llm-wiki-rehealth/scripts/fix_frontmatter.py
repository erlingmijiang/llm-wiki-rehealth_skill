# -*- coding: utf-8 -*-
"""llm-wiki-rehealth: frontmatter 补齐。

为缺失字段补入确定性值：
  - type   ← 从目录推断（concepts→concept 等）
  - created/updated ← 盖章当天日期（若缺失）
  - title  ← 仅标记，不自动填充（避免把 slug 当标题造成污染）

未闭合的 frontmatter 只标记不修改。用法:
  python fix_frontmatter.py --root <wiki或项目根> [--apply]
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (
    ensure_utf8_stdout, ensure_frontmatter_std, parse_frontmatter_file, list_md_files,
    split_dir_prefix, parse_args, write_json_report, backup_file, p,
)

BACKUP_DIR = os.path.join(".llm-wiki", "repair-backup")
TYPE_BY_DIR = {
    "concepts": "concept", "entities": "entity", "sources": "source",
    "findings": "finding", "queries": "query", "comparisons": "comparison",
    "methodology": "methodology", "synthesis": "synthesis", "thesis": "thesis",
    "articles": "article", "thingkings": "thingking", "controversy": "controversy",
    "media": "media", "fgt": "finding",
}


def resolve_paths(root):
    if os.path.basename(os.path.abspath(root)) == "wiki":
        return os.path.dirname(root), root
    cand = os.path.join(root, "wiki")
    if os.path.isdir(cand):
        return root, cand
    return root, root


def main():
    ensure_utf8_stdout()
    opts, _ = parse_args(sys.argv[1:], "frontmatter 补齐")
    project_root, wiki_root = resolve_paths(opts["root"])
    if not os.path.isdir(wiki_root):
        p(f"[错误] 找不到 wiki 目录: {wiki_root}")
        sys.exit(1)

    today = date.today().isoformat()
    plan = []   # {path, add: {field: value}}
    unclosed = []

    for path in list_md_files(wiki_root):
        fm, _, text = parse_frontmatter_file(path)
        if not text.startswith("---"):
            continue
        if text.count("---") < 2:
            unclosed.append(path)
            continue
        type_dir, stem = split_dir_prefix(path)
        add = {}
        if "type" not in fm:
            inferred = TYPE_BY_DIR.get(type_dir)
            if inferred:
                add["type"] = inferred
        for f in ("created", "updated"):
            if f not in fm:
                add[f] = today
        if "title" not in fm:
            # 仅标记，不自动填充
            add["__title_missing"] = True
        if add:
            plan.append({"path": path, "add": add})

    fills = [c for c in plan if not c["add"].get("__title_missing")]
    title_missing = [c["path"] for c in plan if c["add"].get("__title_missing")]
    p(f"== frontmatter 补齐 ==")
    p(f"  可确定性补齐（type/created/updated）: {len(fills)} 个文件")
    p(f"  缺 title（仅标记，不自动填）: {len(title_missing)} 个")
    p(f"  frontmatter 未闭合（只标记）: {len(unclosed)} 个")
    for c in fills[:10]:
        adds = {k: v for k, v in c["add"].items() if not k.startswith("__")}
        p(f"    [{'将改' if opts['apply'] else 'dry'}] {c['path']}: {adds}")

    report_dir = opts.get("out") or os.path.join(project_root, "reports")
    write_json_report(report_dir, "frontmatter-fix", {
        "fill_count": len(fills),
        "title_missing": title_missing,
        "unclosed": unclosed,
        "plan": [{**c, "add": {k: v for k, v in c["add"].items() if not k.startswith("__")}} for c in fills],
    })

    if not opts["apply"]:
        p("\n[dry-run] 未写入。加 --apply 执行（会先备份）。")
        return

    backup_root = os.path.join(project_root, BACKUP_DIR)
    done = 0
    for c in fills:
        path = c["path"]
        backup_file(path, backup_root)
        _, _, text = parse_frontmatter_file(path)
        parts = text.split("---", 2)
        raw_fm = parts[1]
        lines = raw_fm.rstrip().splitlines()
        for field in ("created", "updated"):
            if field in c["add"]:
                lines.append(f"{field}: {c['add'][field]}")
        if "type" in c["add"]:
            # type 放在 title 之前更符合惯例
            lines.insert(0, f"type: {c['add']['type']}")
        new_text = parts[0] + "---\n" + "\n".join(lines) + "\n---" + parts[2]
        with open(path, "w", encoding="utf-8") as f:
            f.write(ensure_frontmatter_std(new_text))
        done += 1
    p(f"完成：{done} 个文件已补齐，备份在 {backup_root}")
    if title_missing:
        p(f"提示：{len(title_missing)} 个缺 title 的页面见报告，请人工处理。")


if __name__ == "__main__":
    main()
