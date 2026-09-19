# -*- coding: utf-8 -*-
"""恢复修复脚本误写丢失的 frontmatter。

场景：某 fix 脚本 bug 导致写盘时丢弃 frontmatter（如历史 fix_links 只写 body）。
从 `.llm-wiki/repair-backup/` 的备份中提取原 frontmatter，拼上当前文件正文，重组写回。

用法:
  python restore_frontmatter.py --root <wiki或项目根>            # 默认用今天日期的备份
  python restore_frontmatter.py --root <root> --date 2026-08-16  # 指定备份日期
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (
    ensure_utf8_stdout, ensure_frontmatter_std, parse_frontmatter_file,
    list_md_files, parse_args, p,
)


def resolve_paths(root):
    if os.path.basename(os.path.abspath(root)) == "wiki":
        return os.path.dirname(root), root
    cand = os.path.join(root, "wiki")
    if os.path.isdir(cand):
        return root, cand
    return root, root


def main():
    ensure_utf8_stdout()
    opts, pos = parse_args(sys.argv[1:], "恢复丢失的 frontmatter")
    project_root, wiki_root = resolve_paths(opts["root"])
    if not os.path.isdir(wiki_root):
        p(f"[错误] 找不到 wiki 目录: {wiki_root}")
        sys.exit(1)
    bdir = os.path.join(project_root, ".llm-wiki", "repair-backup")
    date_str = datetime.date.today().isoformat()
    for i, a in enumerate(pos):
        if a == "--date" and i + 1 < len(pos):
            date_str = pos[i + 1]
    if not os.path.isdir(bdir):
        p(f"[错误] 备份目录不存在: {bdir}")
        return

    bad = []
    for path in list_md_files(wiki_root):
        _, _, text = parse_frontmatter_file(path)
        if not text.startswith("---"):
            bad.append(path)
    if not bad:
        p("没有无 frontmatter 的文件，无需恢复。")
        return

    restored = 0
    errors = []
    for path in bad:
        bak = os.path.join(bdir, f"{os.path.basename(path)}.{date_str}.bak")
        if not os.path.exists(bak):
            errors.append(("no_bak", path))
            continue
        with open(bak, "r", encoding="utf-8", errors="replace") as f:
            orig = f.read()
        parts = orig.split("---", 2)
        if len(parts) < 3:
            errors.append(("bad_bak", path))
            continue
        head = parts[0] + "---" + parts[1] + "---"
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            cur_body = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(ensure_frontmatter_std(head + cur_body))
        restored += 1
    p(f"恢复完成: {restored} / {len(bad)}，备份日期 {date_str}")
    for e in errors[:10]:
        p(f"  错误[{e[0]}]: {e[1]}")


if __name__ == "__main__":
    main()
