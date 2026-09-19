# -*- coding: utf-8 -*-
"""按 WebUI 标注结果执行重复页融合合并（LLM 起草合并稿 + 人工标注）。

流程：
  1) 读 annotations JSON（annotate_duplicates.py 产出：group/name/note）
  2) 对每个标注组，读合并稿 reports/merge-result-<name>.md（LLM 起草）
  3) 写合并稿到目标文件 <dir>/<name>.md（遵循命名规范）
  4) 全 wiki 重写指向被删页旧别名（stem/title 归一化）的链接 → 新 slug（保留 alias 显示文本）
  5) index 重定向；删除被删页；全部先备份到 .llm-wiki/repair-backup/

注意：同名目标的多个标注组（如 A2A 的两变体）会合并为一组处理。

用法:
  python merge_annotations.py --root <wiki或项目根> [--annotations <json>] [--draft-dir <dir>]
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (
    ensure_utf8_stdout, ensure_frontmatter_std, normalize_key, parse_frontmatter_file,
    extract_wikilinks, list_md_files, parse_args, backup_file, p,
)

BACKUP_DIR = os.path.join(".llm-wiki", "repair-backup")
MERGE_DIRS = ("concepts", "entities")
WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]")


def resolve_paths(root):
    if os.path.basename(os.path.abspath(root)) == "wiki":
        return os.path.dirname(root), root
    cand = os.path.join(root, "wiki")
    if os.path.isdir(cand):
        return root, cand
    return root, root


def find_latest(repdir, prefix):
    if os.path.isdir(repdir):
        for fn in sorted(os.listdir(repdir), reverse=True):
            if fn.startswith(prefix) and fn.endswith(".json"):
                return os.path.join(repdir, fn)
    return None


def build_group_files(aud_path, norm_key, dirname):
    """从 audit dup_groups 找 normkey 组，过滤到指定目录的成员。"""
    with open(aud_path, "r", encoding="utf-8") as f:
        rep = json.load(f)
    BS = chr(92)
    for g in rep.get("dup_groups", []):
        if normalize_key(g["key"]) != normalize_key(norm_key):
            continue
        kept = []
        for x in g["files"]:
            if "/sources/" in x.replace(BS, "/"):
                continue
            if os.path.basename(os.path.dirname(x)) == dirname:
                kept.append(x)
        return kept
    return []


def collect_aliases(files):
    """收集被删页可能被引用的别名（stem/title 归一化）。"""
    aliases = set()
    for f in files:
        stem = os.path.basename(f)[:-3]
        aliases.add(normalize_key(stem))
        fm, _, _ = parse_frontmatter_file(f)
        title = str(fm.get("title", "")).strip()
        if title:
            aliases.add(normalize_key(title))
    return aliases


def rewrite_links(content, aliases, new_slug):
    """重写指向被删页别名的引用 → 新 slug：
    1) 正文/任意位置的 `[[旧别名]]` → `[[新slug]]`（保留 alias 显示文本）；
    2) frontmatter related 中的裸字符串旧别名 → `"[[新slug]]"`。
    """
    # 1) wikilink 重写
    def repl(m):
        raw = m.group(1).strip()
        alias = m.group(2).strip() if m.group(2) else None
        if normalize_key(raw) in aliases:
            if alias and normalize_key(alias) not in aliases:
                return f"[[{new_slug}|{alias}]]"
            return f"[[{new_slug}]]"
        return m.group(0)
    content = re.sub(r"\[\[([^\]|]*)(?:\|([^\]]+))?\]\]", repl, content)

    # 2) frontmatter related 裸字符串 → [[新slug]]
    lines = content.split("\n")
    changed = False
    for i, line in enumerate(lines):
        m = re.match(r'^related:\s*\[(.*)\]\s*$', line)
        if m:
            parts = re.split(r',\s*', m.group(1))
            new_parts = []
            any_ch = False
            for part in parts:
                stripped = part.strip().strip('"').strip("'").strip()
                if stripped and not stripped.startswith('[[') and normalize_key(stripped) in aliases:
                    new_parts.append(f'"[[{new_slug}]]"')
                    any_ch = True
                    continue
                new_parts.append(part)
            if any_ch:
                lines[i] = f'related:[{",".join(new_parts)}]'
                changed = True
        elif re.match(r'^related:\s*$', line):
            j = i + 1
            while j < len(lines) and re.match(r'^\s*-\s+', lines[j]):
                raw = re.sub(r'^\s*-\s+', '', lines[j]).strip().strip('"').strip("'").strip()
                if raw and not raw.startswith('[[') and normalize_key(raw) in aliases:
                    lines[j] = re.sub(r'^(\s*-\s+).*$', r'\1' + f'"[[{new_slug}]]"', lines[j])
                    changed = True
                j += 1
    if changed:
        content = "\n".join(lines)
    return content


def main():
    ensure_utf8_stdout()
    opts, pos = parse_args(sys.argv[1:], "按标注执行重复页融合合并")
    project_root, wiki_root = resolve_paths(opts["root"])
    if not os.path.isdir(wiki_root):
        p(f"[错误] 找不到 wiki 目录: {wiki_root}")
        sys.exit(1)
    repdir = opts.get("out") or os.path.join(project_root, "reports")

    ann_path = None
    draft_dir = repdir
    for i, a in enumerate(pos):
        if a == "--annotations" and i + 1 < len(pos):
            ann_path = pos[i + 1]
        if a == "--draft-dir" and i + 1 < len(pos):
            draft_dir = pos[i + 1]
    if not ann_path:
        ann_path = find_latest(repdir, "annotations-")
    if not ann_path or not os.path.exists(ann_path):
        p("[错误] 未找到 annotations JSON，先运行 annotate_duplicates.py 标注")
        sys.exit(1)
    aud_path = find_latest(repdir, "audit-")
    if not aud_path:
        p("[错误] 未找到 audit JSON")
        sys.exit(1)

    with open(ann_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    anns = payload.get("annotations", [])

    # 按目标文件名归并（同名目标=合并为一组）
    merged = {}
    for a in anns:
        if not a.get("merge"):
            continue
        # group 形如 "normkey [dir]"
        m = re.match(r"^(.*)\s*\[\s*([a-zA-Z0-9]+)\s*\]\s*$", a["group"])
        if not m:
            p(f"[警告] 无法解析组 key: {a['group']}，跳过")
            continue
        norm_key, dirname = m.group(1).strip(), m.group(2)
        agg = merged.setdefault((a["name"], dirname), {"norm_keys": [], "notes": []})
        agg["norm_keys"].append(norm_key)
        if a.get("note"):
            agg["notes"].append(a["note"])

    if not merged:
        p("没有标注为合并的组。")
        return

    backup_root = os.path.join(project_root, BACKUP_DIR)
    os.makedirs(backup_root, exist_ok=True)
    summary = []
    for (name, dirname), agg in merged.items():
        # 成员文件（多个 norm key 归并）
        member_set = {}
        for nk in agg["norm_keys"]:
            for f in build_group_files(aud_path, nk, dirname):
                member_set[f] = True
        members = list(member_set)
        if len(members) < 2:
            p(f"[跳过] {name} [{dirname}] 组内不足 2 页，无法合并")
            continue
        target_path = os.path.join(wiki_root, dirname, name + ".md")
        # 目标页 = 名为 name 的成员（若有）
        kept = [f for f in members if os.path.basename(f)[:-3] == name]
        removed = [f for f in members if f not in kept]
        aliases = collect_aliases(removed)
        # 合并稿
        draft = os.path.join(draft_dir, f"merge-result-{name}.md")
        if not os.path.exists(draft):
            p(f"[错误] 缺少合并稿: {draft}，跳过 {name}")
            continue
        with open(draft, "r", encoding="utf-8") as f:
            merged_text = f.read()

        p(f"\n== 合并: {name} [{dirname}] ==")
        p(f"  保留目标: {os.path.relpath(target_path, wiki_root)}")
        p(f"  删除: {[os.path.relpath(x, wiki_root) for x in removed]}")
        p(f"  备注: {agg['notes'] or '(无)'}")

        # 备份目标 + 成员
        for f in members:
            backup_file(f, backup_root)
        if target_path not in members:
            backup_file(target_path, backup_root)
        # 写合并稿到目标文件
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(ensure_frontmatter_std(merged_text))
        # 全 wiki 重写指向被删页的链接（含目标页自身正文）
        rewritten = 0
        for path in list_md_files(wiki_root) + [os.path.join(wiki_root, "index.md")]:
            if not os.path.exists(path):
                continue
            backup_file(path, backup_root)
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            new_content = rewrite_links(content, aliases, name)
            if new_content != content:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                rewritten += 1
        # 删除被删页
        for f in removed:
            if os.path.exists(f):
                os.remove(f)
        summary.append({"name": name, "dir": dirname, "removed": len(removed), "rewritten": rewritten})

    p("\n== 合并完成汇总 ==")
    for s in summary:
        p(f"  {s['dir']}/{s['name']}: 删 {s['removed']} 页, 重写 {s['rewritten']} 文件")
    p(f"备份目录: {backup_root}")


if __name__ == "__main__":
    main()
