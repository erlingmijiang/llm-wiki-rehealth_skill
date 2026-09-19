# -*- coding: utf-8 -*-
"""llm-wiki-rehealth 共享库：纯 Python 标准库，跨平台可运行。

提供 wiki 仓库扫描、归一化、frontmatter 解析、wikilink 提取、
ingest-cache 加载、备份与报告输出等基础能力。
"""
import io
import json
import os
import re
import shutil
import sys
import unicodedata
from datetime import date

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
EXCLUDE_STEMS = {"index", "log", "overview"}
DIR_PREFIXES = (
    "concepts", "entities", "sources", "findings", "queries", "comparisons",
    "methodology", "synthesis", "thesis", "articles", "thingkings", "controversy", "media", "fgt",
)
WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]")
FRONTMATTER_FIELDS = ("type", "title", "created", "updated")


def ensure_utf8_stdout():
    """确保 stdout 以 UTF-8 输出（Windows 控制台默认 GBK 会乱码）。"""
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------
def normalize_key(s):
    """把页面 slug / wikilink 目标 / title 归一化为可比较键。

    - NFKC 标准化（全角→半角、兼容字符）
    - 小写
    - 去掉目录前缀（concepts/xx → xx）
    - 去掉所有符号/空白（连字符、下划线、括号、点、空格、+ 等）
    """
    s = unicodedata.normalize("NFKC", s).lower().strip()
    for p in DIR_PREFIXES:
        if s.startswith(p + "/"):
            s = s[len(p) + 1:]
            break
    # 保留汉字与字母数字，去掉其余
    return re.sub(r"[^a-z0-9一-鿿]", "", s)


def filename_stem(path):
    """去掉 .md 后缀和目录，得到文件名 stem。"""
    return os.path.splitext(os.path.basename(path))[0]


def split_dir_prefix(path):
    """返回 (type_dir, stem)。path 形如 wiki/concepts/xxx.md → ('concepts','xxx')"""
    d = os.path.basename(os.path.dirname(path))
    return d, filename_stem(path)


# ---------------------------------------------------------------------------
# frontmatter
# ---------------------------------------------------------------------------
def parse_frontmatter(text):
    """解析 YAML frontmatter（宽松实现）。返回 (dict, body)。失败返回 ({}, text)。"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    raw = parts[1]
    body = parts[2]
    fm = {}
    in_block_list = None
    for line in raw.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            in_block_list = None
            if val == "" or val in ("|", ">"):
                in_block_list = key
                fm.setdefault(key, [])
            elif val.startswith("["):
                # inline 数组
                items = [x.strip().strip('"').strip("'") for x in val[1:-1].split(",") if x.strip()]
                fm[key] = items
            elif val in ("true", "True", "TRUE"):
                fm[key] = True
            elif val in ("false", "False", "FALSE"):
                fm[key] = False
            else:
                fm[key] = val.strip('"').strip("'")
        elif in_block_list and re.match(r"^\s*-\s+", line):
            item = re.sub(r"^\s*-\s+", "", line).strip().strip('"').strip("'")
            fm.setdefault(in_block_list, []).append(item)
    return fm, body


def parse_frontmatter_file(path):
    """读取文件并解析 frontmatter。返回 (fm_dict, body, text)。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return {}, "", ""
    fm, body = parse_frontmatter(text)
    return fm, body, text


# frontmatter 块：起始行 `---`，字段块，结束符（独立行或紧贴前一行末尾，2~4 个 `-`）
_FM_BLOCK_RE = re.compile(
    r"^---[ \t]*\r?\n(?P<fm>.*?)(?:\r?\n)?(?P<end>-{2,4})[ \t]*(?=\r?\n|$)",
    re.S,
)


def ensure_frontmatter_std(text):
    """规范化文件头 frontmatter 为标准格式（幂等，已标准则原样返回）。

    标准格式：
        ---
        <字段行>
        ---
        <正文>

    保证：首行 `---`；字段块居中；结束行 `---` **独占一行**；结束后换行再写正文。

    兼容修复（用正则精确定位 frontmatter 块，不误伤 frontmatter 内行内含 `---` 的值）：
      - 结束符 `--`（少一个字符）→ 规范为 `---`；
      - 结束符紧贴前一行（如 `sources: [...]---`）→ 提为独立行；
      - 结束符后正文紧贴（无换行）→ 插入换行。

    无 frontmatter 或无法可靠识别结束符（未闭合）的文件原样返回，交由其他逻辑标记。
    """
    if not text.startswith("---"):
        return text
    m = _FM_BLOCK_RE.match(text)
    if not m:
        return text  # 无法可靠识别 frontmatter 结束，保守不动
    raw_fm = m.group("fm").strip("\n")
    after = text[m.end():]
    if after and not after.startswith("\n") and not after.startswith("\r"):
        after = "\n" + after  # 结束符后正文紧贴则补换行
    return f"---\n{raw_fm}\n---{after}"


# ---------------------------------------------------------------------------
# wikilink
# ---------------------------------------------------------------------------
def extract_wikilinks(text):
    """提取所有 wikilink。返回 [(target_raw, alias_or_None)]。"""
    return [(m.group(1).strip(), m.group(2).strip() if m.group(2) else None)
            for m in WIKILINK_RE.finditer(text)]


def render_wikilink(target, alias=None):
    """生成规范化 wikilink 文本。"""
    return f"[[{target}]]" if not alias else f"[[{target}|{alias}]]"


# ---------------------------------------------------------------------------
# 页面收集
# ---------------------------------------------------------------------------
def list_md_files(wiki_root, exclude_stems=None):
    """遍历 wiki 根目录下所有 .md 文件，排除 index/log/overview。"""
    exclude = EXCLUDE_STEMS if exclude_stems is None else exclude_stems
    out = []
    for root, dirs, files in os.walk(wiki_root):
        for f in files:
            if not f.endswith(".md"):
                continue
            stem = os.path.splitext(f)[0]
            if stem in exclude:
                continue
            out.append(os.path.normpath(os.path.join(root, f)))
    return out


def collect_pages(wiki_root):
    """建立页面索引。

    返回 (pages, inbound):
      pages: dict norm_key -> list of dict{stem, path, title, type_dir, fm}
      inbound: Counter norm_key -> 入链数（排除 index/log/overview 作为来源）
    """
    from collections import Counter, defaultdict
    pages = defaultdict(list)
    for path in list_md_files(wiki_root):
        stem = filename_stem(path)
        type_dir, _ = split_dir_prefix(path)
        fm, body, _ = parse_frontmatter_file(path)
        title = str(fm.get("title", "")).strip()
        info = {"stem": stem, "path": path, "title": title,
                "type_dir": type_dir, "fm": fm, "body": body}
        key = normalize_key(stem)
        pages[key].append(info)
        if title:
            tkey = normalize_key(title)
            if tkey != key:
                pages[tkey].append(info)

    inbound = Counter()
    for path in list_md_files(wiki_root):
        _, body, _ = parse_frontmatter_file(path)
        for target, _ in extract_wikilinks(body):
            inbound[normalize_key(target)] += 1
    return pages, inbound


# ---------------------------------------------------------------------------
# ingest-cache（权威源→页面映射）
# ---------------------------------------------------------------------------
def load_ingest_cache(project_root):
    """读取 .llm-wiki/ingest-cache.json。

    返回 dict: 绝对路径 -> {"source": 源文件路径, "filesWritten": [相对项目根的路径]}
    以及 set 所有 written 页面绝对路径。文件缺失返回 ({}, set())。
    """
    cache_path = os.path.join(project_root, ".llm-wiki", "ingest-cache.json")
    written_abs = set()
    mapping = {}
    if not os.path.exists(cache_path):
        return mapping, written_abs
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return mapping, written_abs
    for src, info in data.get("entries", {}).items():
        for w in info.get("filesWritten", []):
            w = w.replace("\\", "/")
            p = os.path.normpath(os.path.join(project_root, w))
            mapping[p] = {"source": src, "rel": w}
            written_abs.add(p)
    return mapping, written_abs


# ---------------------------------------------------------------------------
# 备份 / 报告
# ---------------------------------------------------------------------------
def backup_file(path, backup_dir):
    """把文件复制到备份目录（保留相对结构），返回备份路径。"""
    if not os.path.exists(path):
        return None
    rel = os.path.basename(path)
    dest = os.path.join(backup_dir, f"{rel}.{date.today().isoformat()}.bak")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(path, dest)
    return dest


def write_json_report(reports_dir, name, data):
    """把结构化结果写入 reports/ 目录。"""
    os.makedirs(reports_dir, exist_ok=True)
    path = os.path.join(reports_dir, f"{name}-{date.today().isoformat()}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def p(*a):
    print(*a)


# ---------------------------------------------------------------------------
# 主入口辅助
# ---------------------------------------------------------------------------
def parse_args(argv, script_desc, extra=None):
    """极简参数解析：支持 --root 和 --dry-run/--apply 开关。

    返回 (opts dict, positional list)。
    """
    opts = {"root": os.getcwd(), "apply": False}
    pos = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--root":
            i += 1
            opts["root"] = argv[i]
        elif a in ("--apply", "--yes"):
            opts["apply"] = True
        elif a == "--backlink":
            opts["backlink"] = True
        elif a == "--out":
            i += 1
            opts["out"] = argv[i]
        elif a in ("-h", "--help"):
            p(f"{script_desc}\n用法: python {os.path.basename(sys.argv[0])} [--root <wiki或项目目录>] [--apply]")
            sys.exit(0)
        else:
            pos.append(a)
        i += 1
    return opts, pos


if __name__ == "__main__":
    ensure_utf8_stdout()
    p("common.py 共享库，非直接运行。")
