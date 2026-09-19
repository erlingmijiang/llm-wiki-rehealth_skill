# -*- coding: utf-8 -*-
"""llm-wiki-rehealth: 失效链接修复。

将指向不存在页面的 [[目标]] 降级为纯文本（保留 alias / 目标文字），
避免页面指向虚空；同时把每个被降级的目标写入集中报告
reports/degraded-links-<date>.jsonl，供后续决定是否补建 stub 或补内容。

用法:
  python fix_links.py --root <wiki或项目根>              # dry-run，仅预览变更
  python fix_links.py --root <wiki或项目根> --apply      # 执行（先备份到 .llm-wiki/repair-backup/）
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (
    ensure_utf8_stdout, ensure_frontmatter_std, normalize_key, parse_frontmatter_file,
    list_md_files, collect_pages, parse_args, write_json_report, backup_file, p,
    WIKILINK_RE,
)

BACKUP_DIR = os.path.join(".llm-wiki", "repair-backup")


def degrade_links_in_body(body, valid_keys):
    """把 body 中指向不存在页面的 wikilink 降级为纯文本。

    从后往前替换，避免 span 错位。返回 (new_body, [(target, alias, replacement), ...])。
    """
    matches = list(WIKILINK_RE.finditer(body))
    new_body = body
    replaced = []
    for m in reversed(matches):
        target = m.group(1).strip()
        alias = m.group(2).strip() if m.group(2) else None
        if normalize_key(target) in valid_keys:
            continue
        replacement = alias if alias else target
        start, end = m.span()
        new_body = new_body[:start] + replacement + new_body[end:]
        replaced.append((target, alias, replacement))
    return new_body, list(reversed(replaced))


def resolve_paths(root):
    if os.path.basename(os.path.abspath(root)) == "wiki":
        return os.path.dirname(root), root
    cand = os.path.join(root, "wiki")
    if os.path.isdir(cand):
        return root, cand
    return root, root


def main():
    ensure_utf8_stdout()
    opts, _ = parse_args(sys.argv[1:], "失效链接降级修复")
    project_root, wiki_root = resolve_paths(opts["root"])
    if not os.path.isdir(wiki_root):
        p(f"[错误] 找不到 wiki 目录: {wiki_root}")
        sys.exit(1)

    pages, _ = collect_pages(wiki_root)
    valid = set(pages.keys())
    changes = []
    degraded_report = []

    for path in list_md_files(wiki_root):
        _, body, text = parse_frontmatter_file(path)
        if not text or not body:
            continue
        new_body, replaced = degrade_links_in_body(body, valid)
        if replaced:
            changes.append({"path": path, "old_len": len(body), "new_len": len(new_body)})
            for target, alias, repl in replaced:
                degraded_report.append({"from": path, "target": target, "alias": alias,
                                        "replacement": repl})

    p(f"== 失效链接修复: 共 {len(degraded_report)} 处，涉及 {len(changes)} 个文件 ==")
    for c in changes[:20]:
        p(f"  [{'将改' if opts['apply'] else 'dry'}] {c['path']}")
    if len(changes) > 20:
        p(f"  ... 其余 {len(changes) - 20} 个文件")

    report_dir = opts.get("out") or os.path.join(project_root, "reports")
    rep = write_json_report(report_dir, "degraded-links", degraded_report)
    p(f"\n知识缺口清单（被降级的目标，共 {len(degraded_report)} 条）: {rep}")

    if not opts["apply"]:
        p("\n[dry-run] 未写入任何文件。确认后加 --apply 执行（会先备份到 .llm-wiki/repair-backup/）。")
        return

    backup_root = os.path.join(project_root, BACKUP_DIR)
    for c in changes:
        path = c["path"]
        backup_file(path, backup_root)
        _, body, text = parse_frontmatter_file(path)
        new_body, _ = degrade_links_in_body(body, valid)
        # 保留 frontmatter 原文，仅替换 body（修复：此前只写 body 会丢失 frontmatter）
        head = ""
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                head = parts[0] + "---" + parts[1] + "---"
        with open(path, "w", encoding="utf-8") as f:
            f.write(ensure_frontmatter_std(head + new_body))
    p(f"完成：{len(changes)} 个文件已修复，备份在 {backup_root}")


if __name__ == "__main__":
    main()
