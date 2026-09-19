# -*- coding: utf-8 -*-
"""llm-wiki-rehealth: related 链接规范化。

把 frontmatter 中 `related` 数组的裸字符串项改写为 [[wikilink]]（仅当该项能
匹配到已存在的页面 slug/title）。保守策略：
  - 默认不改目标页正文
  - --backlink 可选：仅当目标页是孤立页面（无入链）时，在其正文补一条反向链接
  - 裸字符串匹配到多个页面（同名不同目录）时跳过，交给人工

用法:
  python fix_related.py --root <wiki或项目根>            # dry-run
  python fix_related.py --root <wiki或项目根> --apply    # 执行
  python fix_related.py --root <wiki或项目根> --apply --backlink
"""
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (
    ensure_utf8_stdout, ensure_frontmatter_std, normalize_key, parse_frontmatter_file,
    list_md_files, collect_pages, parse_args, write_json_report, backup_file, p,
)

BACKUP_DIR = os.path.join(".llm-wiki", "repair-backup")


def resolve_paths(root):
    if os.path.basename(os.path.abspath(root)) == "wiki":
        return os.path.dirname(root), root
    cand = os.path.join(root, "wiki")
    if os.path.isdir(cand):
        return root, cand
    return root, root


def canonical_target(key, pages):
    """给定 norm key，返回可写回的 [[slug]]（取首个匹配，命中多个返回 None）。"""
    infos = pages.get(key, [])
    distinct = {i["stem"] for i in infos}
    if len(distinct) == 1:
        return next(iter(distinct))
    return None  # 歧义，交人工


def rewrite_inline(inner, pages):
    """重写 inline related 数组。返回 (新文本 or None, [(orig, new), ...])。"""
    inner = inner.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]  # 剥离外层方括号
    if "[[" in inner:
        # 已含 wikilink 的混合格式，保守跳过，交人工
        return None, []
    parts = re.split(r',\s*', inner)
    changes = []
    new_parts = []
    for part in parts:
        raw = part.strip().strip('"').strip("'").strip()
        if not raw:
            new_parts.append(part)
            continue
        key = normalize_key(raw)
        if key in pages:
            target = canonical_target(key, pages)
            if target:
                new_part = f' "[[{target}]]"'
                changes.append((raw, target))
                new_parts.append(new_part)
                continue
        new_parts.append(part)
    if not changes:
        return None, []
    new_inner = ",".join(new_parts)
    return f"related:[{new_inner}]", changes


def rewrite_block_lines(lines, idx, pages):
    """重写 block 形态 related（related: 后跟随 - item 行）。"""
    changes = []
    j = idx + 1
    while j < len(lines) and re.match(r"^\s*-\s+", lines[j]):
        m = re.match(r"^(\s*-\s+)(.*)$", lines[j])
        raw = m.group(2).strip().strip('"').strip("'")
        key = normalize_key(raw)
        if raw and key in pages and not raw.startswith("[["):
            target = canonical_target(key, pages)
            if target:
                changes.append((raw, target))
                lines[j] = f'{m.group(1)}"[[{target}]]"'
        j += 1
    return changes


def main():
    ensure_utf8_stdout()
    opts, _ = parse_args(sys.argv[1:], "related 链接规范化")
    project_root, wiki_root = resolve_paths(opts["root"])
    if not os.path.isdir(wiki_root):
        p(f"[错误] 找不到 wiki 目录: {wiki_root}")
        sys.exit(1)

    pages, inbound = collect_pages(wiki_root)
    all_changes = []       # {path, changes:[(orig,new)]}
    backlink_jobs = []     # 需要补反向链接的 (源页, 目标slug)

    for path in list_md_files(wiki_root):
        _, _, text = parse_frontmatter_file(path)
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        raw_fm = parts[1]
        lines = raw_fm.splitlines()
        changes = []
        i = 0
        while i < len(lines):
            line = lines[i]
            m = re.match(r"^related:\s*(\[.*\])?\s*$", line)
            if m and m.group(1):
                # inline: related: [ ... ]
                new_line, ch = rewrite_inline(m.group(1), pages)
                if ch:
                    lines[i] = new_line
                    changes.extend(ch)
                    if opts.get("backlink"):
                        for orig, tgt in ch:
                            backlink_jobs.append((path, orig, tgt))
            elif m and not m.group(1):
                # block: related: 后跟 - item
                ch = rewrite_block_lines(lines, i, pages)
                if ch:
                    changes.extend(ch)
                    if opts.get("backlink"):
                        for orig, tgt in ch:
                            backlink_jobs.append((path, orig, tgt))
            i += 1
        if changes:
            new_fm = "\n".join(lines)
            all_changes.append({"path": path, "changes": changes, "new_fm": new_fm})

    p(f"== related 规范化: 涉及 {len(all_changes)} 个文件 ==")
    for c in all_changes[:10]:
        p(f"  [{'将改' if opts['apply'] else 'dry'}] {c['path']}: {len(c['changes'])} 处")
        for orig, new in c["changes"][:3]:
            p(f"      {orig!r} -> [[{new}]]")

    if opts.get("backlink"):
        p(f"\n== --backlink 待补反向链接 {len(backlink_jobs)} 处（目标为孤立页才补） ==")

    # 落盘报告
    report_dir = opts.get("out") or os.path.join(project_root, "reports")
    write_json_report(report_dir, "related-normalize", {
        "file_count": len(all_changes),
        "changes": [{"path": c["path"], "changes": [{"from": o, "to": t} for o, t in c["changes"]]} for c in all_changes],
    })

    if not opts["apply"]:
        p("\n[dry-run] 未写入。加 --apply 执行（会先备份）。")
        return

    backup_root = os.path.join(project_root, BACKUP_DIR)
    for c in all_changes:
        path = c["path"]
        backup_file(path, backup_root)
        _, _, text = parse_frontmatter_file(path)
        parts = text.split("---", 2)
        new_text = parts[0] + "---" + c["new_fm"] + "---" + parts[2]
        with open(path, "w", encoding="utf-8") as f:
            f.write(ensure_frontmatter_std(new_text))
    p(f"完成：{len(all_changes)} 个文件已规范化，备份在 {backup_root}")

    # --backlink：仅在孤立目标页补反向链接
    if opts.get("backlink") and opts["apply"]:
        done = 0
        for src_path, orig, tgt in backlink_jobs:
            key = normalize_key(tgt)
            target_infos = pages.get(key, [])
            if not target_infos:
                continue
            tgt_path = target_infos[0]["path"]
            # 仅在目标页是孤立页时补
            if inbound.get(key, 0) > 0:
                continue
            backup_file(tgt_path, backup_root)
            with open(tgt_path, "r", encoding="utf-8") as f:
                tt = f.read()
            if f"[[{os.path.splitext(os.path.basename(src_path))[0]}]]" in tt:
                continue
            if "## Related" in tt:
                tt = tt.replace("## Related", f"## Related\n- [[{os.path.splitext(os.path.basename(src_path))[0]}]]", 1)
            else:
                tt = tt.rstrip() + f"\n\n## Related\n- [[{os.path.splitext(os.path.basename(src_path))[0]}]]\n"
            with open(tgt_path, "w", encoding="utf-8") as f:
                f.write(tt)
            done += 1
        p(f"--backlink 完成：{done} 个孤立目标页补了反向链接")


if __name__ == "__main__":
    main()
