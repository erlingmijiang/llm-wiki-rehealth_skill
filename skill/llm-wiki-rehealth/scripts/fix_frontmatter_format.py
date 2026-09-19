# -*- coding: utf-8 -*-
"""全库 frontmatter 格式规范化（标准格式修复）。

修复：
  - 结束符 `--` → `---`（少一个字符的元数据结尾）
  - 结束符后正文紧贴（无换行）→ 补换行
  - 统一为：首行 `---` / 中间字段 / 末行 `---` / 换行后正文

对每个文件先备份到 `.llm-wiki/repair-backup/`。无 frontmatter 或未闭合文件不动。

用法:
  python fix_frontmatter_format.py --root <wiki或项目根>          # dry-run
  python fix_frontmatter_format.py --root <wiki或项目根> --apply   # 执行
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (
    ensure_utf8_stdout, ensure_frontmatter_std, parse_frontmatter_file,
    parse_args, write_json_report, backup_file, p,
)

BACKUP_DIR = os.path.join(".llm-wiki", "repair-backup")


def resolve_paths(root):
    if os.path.basename(os.path.abspath(root)) == "wiki":
        return os.path.dirname(root), root
    cand = os.path.join(root, "wiki")
    if os.path.isdir(cand):
        return root, cand
    return root, root


def all_md_files(wiki_root):
    """遍历全部 .md（含 index/log/overview，它们也可能携带 frontmatter）。"""
    out = []
    for root, dirs, files in os.walk(wiki_root):
        for f in files:
            if f.endswith(".md"):
                out.append(os.path.normpath(os.path.join(root, f)))
    return out


def main():
    ensure_utf8_stdout()
    opts, _ = parse_args(sys.argv[1:], "frontmatter 格式规范化")
    project_root, wiki_root = resolve_paths(opts["root"])
    if not os.path.isdir(wiki_root):
        p(f"[错误] 找不到 wiki 目录: {wiki_root}")
        sys.exit(1)

    changed = []
    for path in all_md_files(wiki_root):
        _, _, text = parse_frontmatter_file(path)
        new_text = ensure_frontmatter_std(text)
        if new_text != text:
            changed.append({"path": path, "old_head": text[:30], "new_head": new_text[:30]})

    p(f"== frontmatter 格式修复: {len(changed)} 个文件需要规范化 ==")
    for c in changed[:15]:
        p(f"  [{'将改' if opts['apply'] else 'dry'}] {c['path']}")
        p(f"      {c['old_head']!r}  ->  {c['new_head']!r}")
    if len(changed) > 15:
        p(f"  ... 其余 {len(changed) - 15} 个")

    report_dir = opts.get("out") or os.path.join(project_root, "reports")
    write_json_report(report_dir, "frontmatter-format", {"changed": changed})

    if not opts["apply"]:
        p("\n[dry-run] 未写入。确认后加 --apply 执行（会先备份）。")
        return

    backup_root = os.path.join(project_root, BACKUP_DIR)
    done = 0
    for c in changed:
        path = c["path"]
        backup_file(path, backup_root)
        _, _, text = parse_frontmatter_file(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(ensure_frontmatter_std(text))
        done += 1
    p(f"完成：{done} 个文件已规范化，备份在 {backup_root}")


if __name__ == "__main__":
    main()
