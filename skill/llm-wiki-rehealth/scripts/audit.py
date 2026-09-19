# -*- coding: utf-8 -*-
"""llm-wiki-rehealth: 全量审计脚本。

扫描 wiki 仓库，输出五类问题分级报告：
  A. 孤立页面（无任何页面正文 [[...]] 入链；index/log/overview 不算）
  B. 失效链接（指向不存在的页面）+ 概念缺口
  C. 重复页面（三级置信度分组）
  D. frontmatter 缺失（缺 type/title/created/updated）
  E. related 链接形式（裸字符串 vs [[...]]）
并交叉验证 ingest-cache（哪些页面不在任何摄入记录）与截断警告（被丢弃过的页面）。

用法:
  python audit.py --root <wiki目录或项目根>
输出: 分级报告到 stdout，结构化 JSON 到 reports/audit-<date>.json
"""
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (
    ensure_utf8_stdout, ensure_frontmatter_std, _FM_BLOCK_RE, normalize_key,
    parse_frontmatter_file, extract_wikilinks, list_md_files, collect_pages,
    load_ingest_cache, parse_args, write_json_report, p, EXCLUDE_STEMS,
)

REPORT_DIR_NAME = "reports"
WARN_LOG = os.path.join(".llm-wiki", "ingest-warnings.log")


def resolve_project_root(root):
    """允许传入 wiki 目录或项目根：若 root 含 wiki/ 则视为 wiki 根，否则找 root/wiki。"""
    if os.path.basename(os.path.normpath(root)) == "wiki" or os.path.basename(os.path.abspath(root)) == "wiki":
        return os.path.dirname(root), root
    cand = os.path.join(root, "wiki")
    if os.path.isdir(cand):
        return root, cand
    return root, root  # 直接当作 wiki 根


def jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def tokenize_key(s):
    """把归一化键拆成子 token（ASCII 词 + CJK 词组），用于相似度。"""
    import re
    ascii_parts = re.findall(r"[a-z0-9]+", s)
    cjk = re.findall(r"[一-鿿]{2,}", s)
    return ascii_parts + cjk


def classify_duplicates(dup_groups):
    """对重复组分级：P0 字符串相等 / P1 核心token子集 / P2 其余。"""
    import re
    result = {"p0": [], "p1": [], "p2": []}
    for key, infos in dup_groups:
        # 若所有文件 stem 归一化后完全相等 → P0
        stems = {normalize_key(i["stem"]) for i in infos}
        if len(stems) == 1 and all(re.fullmatch(r"[a-z0-9一-鿿]+", normalize_key(i["stem"])) or True for i in infos):
            result["p0"].append((key, infos))
            continue
        # 核心 token 重叠度
        toks = [set(tokenize_key(normalize_key(i["stem"]))) for i in infos]
        # 检查是否一个的 token 是另一个的子集（去掉单字符）
        sub_ok = False
        for i in range(len(toks)):
            for j in range(len(toks)):
                if i == j:
                    continue
                ti = {t for t in toks[i] if len(t) > 1}
                tj = {t for t in toks[j] if len(t) > 1}
                if ti and tj and (ti <= tj or tj <= ti):
                    sub_ok = True
        if sub_ok or any(len(t) > 0 for t in toks):
            sims = []
            for i in range(len(toks)):
                for j in range(i + 1, len(toks)):
                    sims.append(jaccard(toks[i], toks[j]))
            best = max(sims) if sims else 0
            if best > 0.4:
                result["p1"].append((key, infos))
                continue
        result["p2"].append((key, infos))
    return result


def main():
    ensure_utf8_stdout()
    opts, _ = parse_args(sys.argv[1:], "wiki 仓库全量审计")
    project_root, wiki_root = resolve_project_root(opts["root"])
    if not os.path.isdir(wiki_root):
        p(f"[错误] 找不到 wiki 目录: {wiki_root}")
        sys.exit(1)

    report = {}
    # ---- 页面收集与入链 ----
    pages, inbound = collect_pages(wiki_root)
    p(f"== 基础信息 ==")
    p(f"  wiki 根: {wiki_root}")
    p(f"  页面总数(含title别名): {len(pages)}")
    p(f"  文件总数: {len(list_md_files(wiki_root))}")

    # ---- A. 孤立页面 ----
    orphans = []
    seen = set()
    for key, infos in pages.items():
        if inbound.get(key, 0) == 0:
            for info in infos:
                if info["path"] not in seen:
                    orphans.append(info)
                    seen.add(info["path"])
    report["orphan_count"] = len(orphans)
    orphan_by_type = Counter(i["type_dir"] for i in orphans)
    p(f"\n== A. 孤立页面（无正文入链）: {len(orphans)} 个 ==")
    for td, c in orphan_by_type.most_common():
        p(f"    {td}: {c}")
    for info in orphans[:15]:
        p(f"    - {info['path']}")
    if len(orphans) > 15:
        p(f"    ... 其余 {len(orphans) - 15} 个见 JSON 报告")

    # ---- B. 失效链接 ----
    broken = []
    for path in list_md_files(wiki_root):
        stem = os.path.basename(path)[:-3]
        _, body, _ = parse_frontmatter_file(path)
        for target, alias in extract_wikilinks(body):
            if normalize_key(target) not in pages:
                broken.append({"from": stem, "target": target, "alias": alias, "path": path})
    report["broken_link_count"] = len(broken)
    p(f"\n== B. 失效链接（指向不存在的页面）: {len(broken)} 处 ==")
    raw_counter = Counter(b["target"] for b in broken)
    p("    高频失效目标（概念缺口）:")
    for t, c in raw_counter.most_common(15):
        p(f"      [{c}次] [[{t}]]")
    for b in broken[:15]:
        p(f"    [{b['from']}] -> [[{b['target']}]]")
    if len(broken) > 15:
        p(f"    ... 其余 {len(broken) - 15} 处见 JSON 报告")

    # ---- C. 重复页面 ----
    dup_groups = {k: v for k, v in pages.items() if len({i["path"] for i in v}) > 1}
    classified = classify_duplicates(list(dup_groups.items()))
    report["dup_p0"] = len(classified["p0"])
    report["dup_p1"] = len(classified["p1"])
    report["dup_p2"] = len(classified["p2"])
    p(f"\n== C. 重复页面组: P0(高置信)={len(classified['p0'])} P1(中置信)={len(classified['p1'])} P2(低置信)={len(classified['p2'])} ==")
    for label in ("p0", "p1", "p2"):
        groups = classified[label]
        if not groups:
            continue
        p(f"  [{label}] 示例:")
        for key, infos in groups[:5]:
            p(f"    {key}:")
            for info in infos:
                p(f"      {info['path']} (sources={len(info['fm'].get('sources', []))}, created={info['fm'].get('created','-')})")
        if len(groups) > 5:
            p(f"    ... 其余 {len(groups) - 5} 组见 JSON")

    # ---- D. frontmatter 缺失 ----
    missing = defaultdict(int)
    fm_total = 0
    for path in list_md_files(wiki_root):
        fm, body, text = parse_frontmatter_file(path)
        if not text.startswith("---"):
            missing["无frontmatter"] += 1
            continue
        if not _FM_BLOCK_RE.match(text):
            missing["frontmatter未闭合"] += 1
            continue
        fm_total += 1
        # 标准格式检查：结束符须独占一行、结束后换行再正文（ensure 可自动修复则视为不规范）
        if ensure_frontmatter_std(text) != text:
            missing["frontmatter格式不规范(结束符/换行)"] += 1
        for field in ("type", "title", "created", "updated"):
            if field not in fm:
                missing[f"缺{field}"] += 1
    report["frontmatter_missing"] = dict(missing)
    p(f"\n== D. frontmatter 完整性（扫描 {fm_total + missing['无frontmatter']} 文件） ==")
    for k, c in sorted(missing.items(), key=lambda x: -x[1]):
        p(f"    {k}: {c}")

    # ---- E. related 链接形式 ----
    related_plain = related_wiki = 0
    for path in list_md_files(wiki_root):
        fm, _, _ = parse_frontmatter_file(path)
        rel = fm.get("related", [])
        if isinstance(rel, str):
            rel = [rel]
        for item in rel:
            if "[[[" in item or item.strip().startswith("[[") and item.strip().endswith("]]"):
                related_wiki += 1
            elif item.strip():
                related_plain += 1
    report["related_plain"] = related_plain
    report["related_wikilink"] = related_wiki
    p(f"\n== E. related 字段形式 ==")
    p(f"    裸字符串: {related_plain}，[[wikilink]]: {related_wiki}")

    # ---- F. ingest-cache 交叉验证 ----
    mapping, written_abs = load_ingest_cache(project_root)
    all_files = list_md_files(wiki_root)
    not_in_cache = [os.path.normpath(f) for f in all_files if os.path.normpath(f) not in written_abs]
    report["not_in_ingest_cache"] = len(not_in_cache)
    report["ingest_entries"] = len(mapping)
    p(f"\n== F. ingest-cache 交叉验证 ==")
    p(f"    摄入记录: {len(mapping)} 条")
    p(f"    不在任何摄入记录的页面: {len(not_in_cache)} / {len(all_files)}")
    if mapping:
        p(f"    平均每源写入页面: 见 JSON")

    # ---- G. 截断警告核对 ----
    truncated = []
    warn_path = os.path.join(project_root, WARN_LOG)
    if os.path.exists(warn_path):
        with open(warn_path, "r", encoding="utf-8", errors="replace") as f:
            warn_text = f.read()
        import re
        for m in re.finditer(r'"wiki/[^"]+"\s+was not closed', warn_text):
            target = m.group(0).split('"')[1]
            truncated.append(target)
    report["truncated_dropped"] = len(truncated)
    p(f"\n== G. 截断丢弃页面（来自 ingest-warnings.log）: {len(truncated)} 个 ==")
    for t in truncated[:10]:
        p(f"    - {t}")
    if len(truncated) > 10:
        p(f"    ... 其余 {len(truncated) - 10} 个见 JSON")

    # ---- H. 问题批注文档残留（非知识页，最终应为 0）----
    stub_mark = "Created by Wiki Lint"
    stub_tag_re = re.compile(r"tags:\s*\[[^\]]*\b(stub|lint)\b")
    ann_file_re = re.compile(
        r"(可能重复|命名冲突|命名碰撞|命名张力|是否与既有页面重复|的张力|可能已存在|"
        r"是否与既有|消歧|核查|内容重叠|冲突风险|术语混淆)")
    n_stub = n_ann = 0
    for path in list_md_files(wiki_root):
        fm, body, text = parse_frontmatter_file(path)
        stem = os.path.basename(path)[:-3]
        if stub_mark in text or stub_tag_re.search(text):
            n_stub += 1
        elif os.path.getsize(path) <= 4096 and ann_file_re.search(stem):
            n_ann += 1
    report["stub_pages"] = n_stub
    report["annotation_pages"] = n_ann
    p(f"\n== H. 问题批注文档残留（修复完成后应为 0） ==")
    p(f"    Wiki Lint 占位页: {n_stub}")
    p(f"    Ingest 分析批注页: {n_ann}")
    p(f"    详见 references/problem-annotations.md；扫描用 scan_problem_annotations.py")

    # ---- 汇总与落盘 ----
    report["summary"] = {
        "orphan": len(orphans), "broken_link": len(broken),
        "dup_total": len(dup_groups), "frontmatter_missing": sum(missing.values()),
        "not_in_ingest_cache": len(not_in_cache), "truncated_dropped": len(truncated),
        "stub_pages": n_stub, "annotation_pages": n_ann,
    }
    report["orphans"] = [{"path": i["path"], "type": i["type_dir"]} for i in orphans]
    report["broken_links"] = broken
    report["dup_groups"] = [
        {"key": k, "level": lv, "files": [i["path"] for i in infos]}
        for lv in ("p0", "p1", "p2") for k, infos in classified[lv]
    ]
    report["truncated"] = truncated
    out = opts.get("out")
    if out:
        rdir = out
    else:
        rdir = os.path.join(project_root, REPORT_DIR_NAME)
    rep_path = write_json_report(rdir, "audit", report)
    p(f"\n== 完整报告已写入: {rep_path} ==")
    p(f"汇总: 孤立{len(orphans)} / 失效{len(broken)} / 重复{len(dup_groups)}组 / 元数据缺{sum(missing.values())} / 不在摄入记录{len(not_in_cache)} / 截断丢页{len(truncated)} / 批注残留{n_stub + n_ann}")


if __name__ == "__main__":
    main()
