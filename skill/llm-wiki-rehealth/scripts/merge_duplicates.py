# -*- coding: utf-8 -*-
"""llm-wiki-rehealth: 重复页面合并（LLM 辅助 + 人工审批）。

流程：
  1) 列出候选重复组（P0 高置信 / P1 中置信 / P2 低置信）
  2) --draft <组key>     导出该组上下文到 reports/merge-draft-<key>.md，
                         供 LLM 起草合并稿
  3) LLM 生成合并稿，人工确认后保存为 reports/merge-result-<key>.md
  4) --apply <组key> --result <result.md>   执行合并：
     写合并稿到保留路径 → 全 wiki 重写指向被删页的链接 → index 重定向
     → 删除被删页 → 全部先备份

用法:
  python merge_duplicates.py --root <wiki或项目根>                 # 列候选组
  python merge_duplicates.py --root <root> --group <key> --draft   # 导出合并上下文
  python merge_duplicates.py --root <root> --group <key> --apply --result <md>
"""
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (
    ensure_utf8_stdout, ensure_frontmatter_std, normalize_key, parse_frontmatter_file,
    extract_wikilinks, list_md_files, collect_pages, parse_args, write_json_report,
    backup_file, p,
)

BACKUP_DIR = os.path.join(".llm-wiki", "repair-backup")


def resolve_paths(root):
    if os.path.basename(os.path.abspath(root)) == "wiki":
        return os.path.dirname(root), root
    cand = os.path.join(root, "wiki")
    if os.path.isdir(cand):
        return root, cand
    return root, root


def pick_kept(infos):
    """选择保留页：字节更大优先，其次 sources 更多。"""
    def score(i):
        try:
            size = os.path.getsize(i["path"])
        except OSError:
            size = 0
        return (size, len(i["fm"].get("sources", [])) if isinstance(i["fm"].get("sources", []), list) else 0)
    return max(infos, key=score)


MERGE_DIRS = ("concepts", "entities")


def build_groups(pages):
    """仅在 concepts/entities 目录**内部**做查重分组（同目录相似页），**不跨目录**。

    其他目录（comparisons/sources/queries/findings/...）不参与。
    concepts/x 与 entities/x 即使归一化同名也不构成候选（各目录内唯一则无重复）。
    """
    groups = []
    for key, infos in pages.items():
        by_dir = defaultdict(list)
        for i in infos:
            if i["type_dir"] not in MERGE_DIRS:
                continue
            by_dir[i["type_dir"]].append(i)
        for d, infos2 in by_dir.items():
            distinct = {}
            for i in infos2:
                distinct[i["path"]] = i
            if len(distinct) > 1:
                groups.append((key, list(distinct.values())))
    groups.sort(key=lambda g: -len(g[1]))
    return groups


def collect_aliases(infos):
    """收集组内所有页面可能被引用的名字（stem + title + title去符号）。"""
    aliases = set()
    for i in infos:
        aliases.add(i["stem"])
        aliases.add(normalize_key(i["stem"]))
        if i["title"]:
            aliases.add(i["title"])
            aliases.add(normalize_key(i["title"]))
    return aliases


def collect_inbound(wiki_root, aliases, exclude_paths):
    """找出所有指向这些别名的页面（入链来源）。"""
    result = []
    for path in list_md_files(wiki_root):
        if path in exclude_paths:
            continue
        _, body, _ = parse_frontmatter_file(path)
        for target, _ in extract_wikilinks(body):
            if normalize_key(target) in {normalize_key(a) for a in aliases}:
                result.append({"path": path, "target": target})
    return result


def render_draft(group_key, infos, inbound):
    lines = []
    lines.append(f"# 合并草稿：{group_key}")
    lines.append(f"共 {len(infos)} 个页面重复。请阅读下面每个页面的 frontmatter 与正文，")
    lines.append("生成一份合并稿（保留更完整的覆盖、union 所有 sources/related、正文择优融合）。")
    lines.append("输出到 reports/merge-result-<key>.md，格式与原页面一致（含 frontmatter）。\n")
    for i, info in enumerate(infos):
        with open(info["path"], "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        lines.append(f"--- 页面 {i+1}: {info['path']} ---")
        lines.append(content[:4000])
        if len(content) > 4000:
            lines.append(f"（...截断，全文 {len(content)} 字符）")
        lines.append("")
    lines.append("--- 入链来源 ---")
    for b in inbound[:30]:
        lines.append(f"  {b['path']} 里 [[{b['target']}]]")
    return "\n".join(lines)


def main():
    ensure_utf8_stdout()
    opts, pos = parse_args(sys.argv[1:], "重复页面合并")
    project_root, wiki_root = resolve_paths(opts["root"])
    if not os.path.isdir(wiki_root):
        p(f"[错误] 找不到 wiki 目录: {wiki_root}")
        sys.exit(1)

    pages, _ = collect_pages(wiki_root)
    groups = build_groups(pages)
    include_sources = "--include-sources" in pos

    # 默认剔除 sources/ 摘要页（资料摘要 vs 知识页面，性质不同，不应合并）
    def strip_sources(key, infos):
        kept = [i for i in infos if os.path.basename(os.path.dirname(i["path"])) != "sources"]
        dropped = [i for i in infos if os.path.basename(os.path.dirname(i["path"])) == "sources"]
        if len(kept) >= 2:
            return key, kept, dropped
        return None, [], dropped

    # 模式1：列候选组
    if "--draft" not in pos and "--apply" not in pos:
        p(f"== 重复候选组（默认不含 sources/ 摘要页）: ==")
        shown = 0
        for key, infos in groups:
            if not include_sources:
                key, kept, dropped = strip_sources(key, infos)
                if key is None:
                    continue
                infos = kept
            sizes = [os.path.getsize(i["path"]) for i in infos]
            tag = " [含sources摘要页,已剔除]" if not include_sources and dropped else ""
            p(f"  [{key}] ({len(infos)}页, 合计{sum(sizes)}B){tag}")
            for info in infos:
                p(f"      {info['path']}")
            shown += 1
            if shown >= 30:
                break
        p(f"\n共 {shown}+ 组。用法：--group <key> --draft 导出合并上下文；--group <key> --apply --result <合并稿> 执行。")
        p("如需把 sources/ 摘要页纳入合并候选，加 --include-sources。")
        return

    # 解析 group key 和 result
    group_key = None
    result_path = None
    for i, a in enumerate(pos):
        if a == "--group":
            group_key = pos[i + 1]
        if a == "--result":
            result_path = pos[i + 1]

    if not group_key:
        p("[错误] 需要 --group <key>")
        return
    # 找到匹配组
    target = None
    for key, infos in groups:
        if normalize_key(key) == normalize_key(group_key):
            target = (key, infos)
            break
    if not target:
        p(f"[错误] 找不到组 {group_key}（可用列表里的原样 key）")
        return
    key, infos = target
    aliases = collect_aliases(infos)
    exclude = {i["path"] for i in infos}
    inbound = collect_inbound(wiki_root, aliases, exclude)

    # 模式2：draft
    if "--draft" in pos:
        report_dir = opts.get("out") or os.path.join(project_root, "reports")
        os.makedirs(report_dir, exist_ok=True)
        draft_path = os.path.join(report_dir, f"merge-draft-{normalize_key(key)}.md")
        with open(draft_path, "w", encoding="utf-8") as f:
            f.write(render_draft(key, infos, inbound))
        p(f"合并上下文已导出: {draft_path}")
        p(f"请让 LLM 阅读该文件并生成合并稿，人工确认后保存为:")
        p(f"  {os.path.join(report_dir, f'merge-result-{normalize_key(key)}.md')}")
        p(f"然后执行: python merge_duplicates.py --root <root> --group {key} --apply --result <合并稿路径>")
        return

    # 模式3：apply
    if "--apply" in pos:
        if not result_path:
            p("[错误] --apply 需要 --result <合并稿.md>")
            return
        if not os.path.exists(result_path):
            p(f"[错误] 合并稿不存在: {result_path}")
            return
        kept = pick_kept(infos)
        removed = [i for i in infos if i["path"] != kept["path"]]
        removed_aliases = set()
        for i in removed:
            removed_aliases.add(i["stem"])
            removed_aliases.add(normalize_key(i["stem"]))
            if i["title"]:
                removed_aliases.add(i["title"])
                removed_aliases.add(normalize_key(i["title"]))
        # 需要把 removed 的 stem/title 归一化形式都纳入重写目标
        rewrite_keys = {normalize_key(a) for a in removed_aliases}

        p(f"== 执行合并 ==")
        p(f"  保留: {kept['path']}")
        p(f"  删除: {[i['path'] for i in removed]}")
        p(f"  入链来源待重写: {len(inbound)} 处")

        if not opts["apply"]:
            p("[错误] 需要 --apply 真正执行（本工具以 --apply 表示确认执行）")
            return
        backup_root = os.path.join(project_root, BACKUP_DIR)

        # 1) 写合并稿到保留页
        backup_file(kept["path"], backup_root)
        with open(result_path, "r", encoding="utf-8") as f:
            merged = f.read()
        with open(kept["path"], "w", encoding="utf-8") as f:
            f.write(ensure_frontmatter_std(merged))

        # 2) 重写所有指向被删页的链接
        for b in inbound:
            src = b["path"]
            backup_file(src, backup_root)
            with open(src, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            new_content = re.sub(
                r"\[\[([^\]|]*)(?:\|([^\]]+))?\]\]",
                lambda m: _rewrite_target(m, rewrite_keys, kept["stem"]),
                content,
            )
            if new_content != content:
                with open(src, "w", encoding="utf-8") as f:
                    f.write(new_content)

        # 3) index 重定向 + 删除被删页
        index_path = os.path.join(wiki_root, "index.md")
        if os.path.exists(index_path):
            backup_file(index_path, backup_root)
            with open(index_path, "r", encoding="utf-8", errors="replace") as f:
                idx = f.read()
            new_idx = re.sub(
                r"\[\[([^\]|]*)(?:\|([^\]]+))?\]\]",
                lambda m: _rewrite_target(m, rewrite_keys, kept["stem"]),
                idx,
            )
            if new_idx != idx:
                with open(index_path, "w", encoding="utf-8") as f:
                    f.write(new_idx)

        for i in removed:
            backup_file(i["path"], backup_root)
            os.remove(i["path"])
        p(f"完成：合并稿已写入 {kept['path']}，删除 {len(removed)} 个页面，重写 {len(inbound)} 处链接，备份在 {backup_root}")


def _rewrite_target(m, rewrite_keys, kept_stem):
    """若 wikilink 目标（归一化后）是被删页别名，重写为保留页 stem。"""
    raw = m.group(1).strip()
    alias = m.group(2).strip() if m.group(2) else None
    if normalize_key(raw) in rewrite_keys:
        # 保留 alias（显示文本），目标改为保留页
        if alias and normalize_key(alias) not in rewrite_keys:
            return f"[[{kept_stem}|{alias}]]"
        return f"[[{kept_stem}]]"
    return m.group(0)


if __name__ == "__main__":
    main()
