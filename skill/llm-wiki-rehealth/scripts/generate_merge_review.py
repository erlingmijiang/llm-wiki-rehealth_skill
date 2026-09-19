# -*- coding: utf-8 -*-
"""生成重复页人工审批清单（Obsidian 链接格式），供用户逐组判断是否合并。

用法:
  python generate_merge_review.py --root <wiki或项目根>        # 依据最新 reports/audit-*.json
输出:
  reports/duplicates-review.md   — 每组以 [[目录/标题]] 列出，用户标注后返回执行 merge

已剔除 sources/ 摘要页；组内以 ⭐ 标注"建议保留"（字节更大/来源更多，仅供参考）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (
    ensure_utf8_stdout, parse_frontmatter_file, list_md_files, collect_pages,
    normalize_key, parse_args, p,
)

LEVEL_TITLE = {
    "p0": "## P0｜高置信（文件名归一化后字符串相等，多为类型判定漂移）",
    "p1": "## P1｜中置信（核心 token 子集/中英对照，需内容比对）",
    "p2": "## P2｜低置信（语义近似/跨目录，需人工细判）",
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
    opts, pos = parse_args(sys.argv[1:], "生成重复页人工审批清单")
    project_root, wiki_root = resolve_paths(opts["root"])
    if not os.path.isdir(wiki_root):
        p(f"[错误] 找不到 wiki 目录: {wiki_root}")
        sys.exit(1)

    repdir = opts.get("out") or os.path.join(project_root, "reports")
    aud = None
    if os.path.isdir(repdir):
        for fn in sorted(os.listdir(repdir), reverse=True):
            if fn.startswith("audit-") and fn.endswith(".json"):
                aud = os.path.join(repdir, fn)
                break
    if not aud:
        p("[错误] 未找到 reports/audit-*.json，请先运行 audit.py --root <root>")
        sys.exit(1)

    with open(aud, "r", encoding="utf-8") as f:
        rep = json.load(f)
    groups = rep["dup_groups"]
    BS = chr(92)

    def non_src(files):
        return [x for x in files if "/sources/" not in x.replace(BS, "/")]

    # 仅在 concepts/entities 目录内部查重（同目录分组，不跨目录）
    from collections import defaultdict
    MERGE_DIRS = ("concepts", "entities")
    filtered = []
    for g in groups:
        by_dir = defaultdict(list)
        for f in non_src(g["files"]):
            d = os.path.basename(os.path.dirname(f))
            if d in MERGE_DIRS:
                by_dir[d].append(f)
        for d, files in by_dir.items():
            if len(files) >= 2:
                filtered.append({"key": f"{g['key']} [{d}]", "level": g["level"], "files": files})
    groups = filtered
    groups.sort(key=lambda g: (g["level"], -len(g["files"])))

    _, inbound = collect_pages(wiki_root)
    stats = {"p0": 0, "p1": 0, "p2": 0}
    for g in groups:
        stats[g["level"]] += 1

    lines = []
    lines.append("# wiki 重复页面候选清单（人工判断用）")
    lines.append("")
    lines.append(f"> 生成自 `{os.path.basename(aud)}`，已剔除 `sources/` 摘要页")
    lines.append(f"> 可判断组数：**{len(groups)}** （P0 高置信 / P1 中置信 / P2 低置信）")
    lines.append("")
    lines.append("## 使用说明")
    lines.append("")
    lines.append("1. 逐组判断。若要合并，在该组末尾标注 `**→ 合并为 [[保留页路径]]**`；")
    lines.append("2. 若保留现状（误报/内容确有差异宜并存），标注 `保留` 或删掉该组；")
    lines.append("3. 完成后将本文档返回给 Agent，只合并被标注的组。")
    lines.append("")
    lines.append("---")
    lines.append("")

    current_lv = None
    for g in groups:
        lv = g["level"]
        if lv != current_lv:
            lines.append(LEVEL_TITLE[lv])
            lines.append("")
            lines.append(f"> 本组共 {stats[lv]} 组")
            lines.append("")
            current_lv = lv
        files = g["files"]
        lines.append(f"### {g['key']}")
        lines.append("")
        infos = []
        for f in files:
            fm, body, text = parse_frontmatter_file(f)
            size = os.path.getsize(f)
            srcs = fm.get("sources", [])
            nsrc = len(srcs) if isinstance(srcs, list) else (1 if srcs else 0)
            t = fm.get("type", "-")
            title = str(fm.get("title", "-"))
            created = fm.get("created", "-")
            stem = os.path.basename(f)[:-3]
            n_in = inbound.get(normalize_key(stem), 0)
            tkey = normalize_key(title)
            if tkey and tkey != normalize_key(stem):
                n_in += inbound.get(tkey, 0)
            infos.append((f, t, size, nsrc, created, n_in, stem))
        best = max(infos, key=lambda x: x[2])
        for (f, t, size, nsrc, created, n_in, stem) in infos:
            rel = os.path.relpath(f, wiki_root).replace(BS, "/")
            if rel.endswith(".md"):
                rel = rel[:-3]
            mark = " ⭐建议保留" if f == best[0] else ""
            lines.append(f"- [[{rel}]] — {t} | {size}B | sources={nsrc} | created={created} | 入链≈{n_in}{mark}")
        lines.append("")
        lines.append("　")
        lines.append("")

    out_path = os.path.join(repdir, "duplicates-review.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    p(f"清单已生成: {out_path} | {len(groups)} 组 {stats}")


if __name__ == "__main__":
    main()
