# -*- coding: utf-8 -*-
"""扫描 wiki 中的「问题批注文档」（非知识页面），分类输出修复清单。

识别两类（详见 references/problem-annotations.md）：
  A 类 Wiki Lint 占位页：tags 含 stub/lint + 正文含 "Created by Wiki Lint..."
      ① with_target  有同义真实页 → 删占位 + 重定向链接
      ② descriptive  描述性批注型（"这里可以加入…"/"XX缺失YY"）→ 删占位（非知识）
      ③ gap          真实知识缺口 → 补建（可能需联网检索）
  B 类 Ingest 分析批注页：文件名=问题描述，正文指出重复/冲突/张力
      按 重复/命名冲突/内容张力/覆盖更新/消歧核查 分类

用法:
  python scan_problem_annotations.py --root <wiki或项目根> [--out <报告目录>]
输出:
  reports/problem-annotations-<date>.json + stdout 分类摘要
"""
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (
    ensure_utf8_stdout, normalize_key, parse_frontmatter_file, list_md_files,
    collect_pages, parse_args, write_json_report, p,
)

STUB_MARK = "Created by Wiki Lint"
STUB_TAG_RE = re.compile(r"tags:\s*\[[^\]]*\b(stub|lint)\b")
DESCRIPTIVE_RE = re.compile(
    r"(这里可以|可以加入|应加入|待补充|待办|需要补充|缺失|应补充|建议加入|TODO|todo|需补充)")
B_FILE_RE = re.compile(
    r"(可能重复|命名冲突|命名碰撞|命名张力|是否与既有页面重复|的张力|可能已存在|是否与既有|消歧|核查|内容重叠|冲突风险|术语混淆)")
B_TS_RE = re.compile(r"-\d{4}-\d{2}-\d{2}-\d{6}\.md$")
B_BODY_RE = re.compile(
    r"(可能重复|命名冲突|命名碰撞|命名张力|的张力|可能已存在|内容重叠|潜在冲突|应以本次|需人工|建议)")
B_MAX_SIZE = 4096  # B 类批注页通常 <4KB
B_KINDS = [
    ("重复/已存在", re.compile(r"(重复|已存在|内容重叠|既有页面)")),
    ("命名冲突/张力", re.compile(r"(命名冲突|命名碰撞|命名张力)")),
    ("内容矛盾/张力", re.compile(r"(的张力|潜在冲突|矛盾|冲突)")),
    ("覆盖/更新", re.compile(r"(覆盖|更新既有|应以本次)")),
    ("消歧/核查", re.compile(r"(消歧|核查|需核对|需确认|适用范围)")),
]


def _fm_minimal(fm):
    """B 类批注页特征：frontmatter 极简（tags 与 sources 均空）。"""
    tags = fm.get("tags")
    srcs = fm.get("sources")
    return (not tags or tags == []) and (not srcs or srcs == [])


def resolve_paths(root):
    if os.path.basename(os.path.abspath(root)) == "wiki":
        return os.path.dirname(root), root
    cand = os.path.join(root, "wiki")
    if os.path.isdir(cand):
        return root, cand
    return root, root


def main():
    ensure_utf8_stdout()
    opts, _ = parse_args(sys.argv[1:], "扫描问题批注文档（非知识页面）")
    project_root, wiki_root = resolve_paths(opts["root"])
    if not os.path.isdir(wiki_root):
        p(f"[错误] 找不到 wiki 目录: {wiki_root}")
        sys.exit(1)

    pages, _ = collect_pages(wiki_root)
    a_with, a_desc, a_gap, b_items = [], [], [], []

    for path in list_md_files(wiki_root):
        fm, body, text = parse_frontmatter_file(path)
        stem = os.path.basename(path)[:-3]
        type_dir = os.path.basename(os.path.dirname(path))
        size = os.path.getsize(path)

        if STUB_MARK in text or STUB_TAG_RE.search(text):
            infos = pages.get(normalize_key(stem), [])
            others = [i["path"] for i in infos
                      if os.path.normpath(i["path"]) != os.path.normpath(path)]
            rec = {"path": path, "stem": stem, "type_dir": type_dir, "size": size}
            if others:
                rec["target"] = others[0]
                a_with.append(rec)
            elif DESCRIPTIVE_RE.search(stem):
                a_desc.append(rec)
            else:
                a_gap.append(rec)
        elif size <= B_MAX_SIZE and _fm_minimal(fm) and (
                B_FILE_RE.search(stem) or B_BODY_RE.search(text[:600])
                or (B_TS_RE.search(stem) and B_BODY_RE.search(text[:600]))):
            kinds = [k for k, rx in B_KINDS if rx.search(stem + text)]
            b_items.append({"path": path, "stem": stem, "type_dir": type_dir,
                            "size": size, "kinds": kinds})

    p("== 问题批注文档扫描 ==")
    p(f"  A 类 Wiki Lint 占位页: {len(a_with) + len(a_desc) + len(a_gap)}")
    p(f"      ① 有同义真实页（删占位+重定向）: {len(a_with)}")
    p(f"      ② 描述性批注型（删占位, 非知识）: {len(a_desc)}")
    p(f"      ③ 真实知识缺口（需补建）: {len(a_gap)}")
    p(f"  B 类 Ingest 分析批注页: {len(b_items)}")
    kc = Counter(k for it in b_items for k in it["kinds"])
    for k, v in kc.most_common():
        p(f"      {k}: {v}")
    p("")
    p(f"  A 类目录分布: {dict(Counter(x['type_dir'] for x in a_with + a_desc + a_gap))}")
    p(f"  B 类目录分布: {dict(Counter(x['type_dir'] for x in b_items))}")
    p("")
    p("  A① 样本:")
    for x in a_with[:5]:
        p(f"    {x['stem']}  ->  {os.path.relpath(x['target'], wiki_root)}")
    p("  A② 样本:")
    for x in a_desc[:5]:
        p(f"    {x['stem']}")
    p("  A③ 样本:")
    for x in a_gap[:8]:
        p(f"    {x['stem']}")
    p("  B 样本:")
    for x in b_items[:6]:
        p(f"    {x['stem']}  [{','.join(x['kinds'])}]")

    report_dir = opts.get("out") or os.path.join(project_root, "reports")
    rep = {
        "a_class": {"with_target": a_with, "descriptive": a_desc, "gap": a_gap},
        "b_class": b_items,
        "summary": {
            "a_total": len(a_with) + len(a_desc) + len(a_gap),
            "a_with_target": len(a_with), "a_descriptive": len(a_desc), "a_gap": len(a_gap),
            "b_total": len(b_items), "b_kinds": dict(kc),
        },
    }
    out = write_json_report(report_dir, "problem-annotations", rep)
    p(f"\n完整清单已写入: {out}")
    p("修复方式见 references/problem-annotations.md（含网络检索前置检查要求）")


if __name__ == "__main__":
    main()
