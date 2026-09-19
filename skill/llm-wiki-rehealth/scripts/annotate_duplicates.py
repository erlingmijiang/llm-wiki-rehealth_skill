# -*- coding: utf-8 -*-
"""WebUI 重复页标注工具（纯 Python 标准库，零依赖）。

启动本地 Web 服务，弹出浏览器，向用户展示 **concepts/entities 目录内部**（同目录、不跨目录）的
重复候选组：
  - 鼠标滑到文件路径上 → 浮层预览正文前 500 字（移开收回）
  - 勾选"合并此组" → 出现"合并后文件名"输入框（默认按**命名规范**推荐，可改）
    + "备注"输入框（用户与 Agent 的辅助交流，如别名/需保留的信息，**优先级最高**）
  - 批量选择：全选 / 全选P0/P1/P2 / 反选 / 条件反选P0/P1/P2 / 全部取消
  - 点"完成并提交" → 保存标注结果 JSON，服务器自动关闭

命名规范推荐（references/naming.md）：全英文 `-` 连接；中英互释用括号；组合词连写；模型版本号用 `.`。
合并时以推荐/自定的新文件名为准（避免合并后命名不规范再返工）。

用法:
  python annotate_duplicates.py --root <wiki或项目根> [--port 8765]
数据源: 最新 reports/audit-*.json 的 dup_groups；范围 = concepts/entities 目录内部。
输出: reports/annotations-<date>.json  →  供 merge 执行（每项含 group/name/note）。
"""
import json
import os
import re
import sys
import threading
import webbrowser
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ensure_utf8_stdout, parse_frontmatter_file, parse_args, p

MERGE_DIRS = ("concepts", "entities")
PREVIEW_LEN = 500


def naming_score(slug):
    """slug 命名规范程度打分（越高越符合 references/naming.md 规则）。"""
    has_cjk = bool(re.search(r"[一-鿿]", slug))
    has_par = bool(re.search(r"[（(]", slug))
    has_dash = bool(re.search(r"-", slug))
    has_dot = bool(re.search(r"\d\.\d", slug))
    score = 0.0
    if has_par:                              # 规则2 中英互释括号（信息最完整）
        score += 2.0
    if has_dot:                              # 规则5 模型版本号用 .（高于粘连/连字符版本）
        score += 2.0
    if re.match(r"^[a-z0-9]+(-[a-z0-9]+)+$", slug):  # 规则1/4 全英文多词用 - 连接
        score += 1.5
    elif not has_cjk and not has_par and not has_dot:
        score -= 1.0                         # 纯英文粘连（websearchtool）降权
    if has_cjk and not has_par:
        if has_dash:                         # 英文-中文组合（trial-攻击方法）
            score += 1.0
        else:                                # 规则3 中文组合词连写（A2A协议）
            score += 0.5
    if has_cjk and re.search(r"[a-z0-9]", slug):  # 中英信息更全，完整性加分
        score += 0.5
    return score


PAGE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>wiki 重复页标注筛选</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: "Segoe UI","Microsoft YaHei",sans-serif; margin:0; background:#f5f6f8; color:#222; }
  #toolbar { position: sticky; top:0; background:#fff; padding:10px 24px; border-bottom:1px solid #ddd;
             display:flex; align-items:center; gap:16px; z-index:10; box-shadow:0 2px 6px rgba(0,0,0,.06); flex-wrap:wrap;}
  #toolbar h1 { font-size:17px; margin:0; }
  #progress { color:#666; font-size:13px; }
  #selcount { color:#0b5394; font-weight:bold; font-size:13px; }
  #status { color:#1a7f37; font-size:13px; }
  #finish { margin-left:auto; background:#1a7f37; color:#fff; border:none; padding:9px 20px;
            border-radius:6px; font-size:15px; cursor:pointer; }
  #finish:hover { background:#14602a; }
  #batch { display:flex; gap:6px; flex-wrap:wrap; padding:8px 24px; background:#fff; border-bottom:1px solid #eee;}
  #batch button { padding:4px 10px; font-size:12px; border:1px solid #bbb; background:#fafafa;
                  border-radius:5px; cursor:pointer; }
  #batch button:hover { background:#eef; }
  #list { padding:16px 24px; max-width:1100px; margin:0 auto; }
  .group { background:#fff; border:1px solid #e0e2e6; border-radius:8px; margin:10px 0; padding:10px 14px; }
  .ghead { display:flex; align-items:center; gap:10px; margin-bottom:6px; }
  .lv { font-size:11px; font-weight:bold; padding:2px 8px; border-radius:10px; color:#fff; }
  .lvp0 { background:#d9534f; } .lvp1 { background:#f0ad4e; } .lvp2 { background:#777; }
  .gtitle { font-size:15px; font-weight:600; }
  .item { padding:4px 8px; margin:2px 0; border-radius:5px; cursor:default; }
  .item:hover { background:#eef3ff; }
  .path { font-family:Consolas,monospace; color:#0b5394; }
  .meta { color:#888; font-size:12px; margin-left:10px; }
  .opt { margin-top:8px; padding-top:8px; border-top:1px dashed #e0e2e6; font-size:13px; }
  .opt input[type=checkbox] { transform:scale(1.3); margin-right:6px; cursor:pointer; }
  .extra { margin-left:12px; }
  .extra label { color:#555; }
  .namein { width:280px; padding:3px 6px; font-size:13px; border:1px solid #bbb; border-radius:4px;
            font-family:Consolas,monospace; }
  .notein { width:320px; padding:3px 6px; font-size:13px; border:1px solid #d0b27a; border-radius:4px;
            background:#fffcf3; }
  #preview { display:none; position:fixed; z-index:1000; max-width:520px; max-height:320px; overflow:auto;
             background:#fffdf5; border:1px solid #ccc; border-radius:6px; padding:10px 12px;
             font-size:13px; line-height:1.6; box-shadow:0 4px 14px rgba(0,0,0,.18); white-space:pre-wrap;
             word-break:break-word; }
</style>
</head>
<body>
<div id="toolbar">
  <h1>重复页筛选标注</h1>
  <span id="progress">加载中…</span>
  <span id="selcount"></span>
  <span id="status"></span>
  <button id="finish">完成并提交</button>
</div>
<div id="batch">
  <button data-act="all">全选</button>
  <button data-act="p0">全选P0</button>
  <button data-act="p1">全选P1</button>
  <button data-act="p2">全选P2</button>
  <button data-act="invert">反选</button>
  <button data-act="inv0">反选P0</button>
  <button data-act="inv1">反选P1</button>
  <button data-act="inv2">反选P2</button>
  <button data-act="none">全部取消</button>
</div>
<div id="list"></div>
<div id="preview"></div>
<script>
let DATA = null;
const pv = document.getElementById('preview');
function showPreview(e){ const it=e.target.closest('.item'); if(!it) return;
  pv.textContent=it.dataset.preview; pv.style.display='block'; }
function movePreview(e){ pv.style.left=(e.clientX+14)+'px'; pv.style.top=(e.clientY+14)+'px'; }
function hidePreview(){ pv.style.display='none'; }

async function load(){ const r=await fetch('/api/data'); DATA=await r.json(); render(); }

function render(){
  const list=document.getElementById('list'); list.innerHTML='';
  DATA.forEach(g=>{
    const card=document.createElement('div'); card.className='group';
    const head=document.createElement('div'); head.className='ghead';
    const lv=document.createElement('span'); lv.className='lv lv'+g.level; lv.textContent=g.level.toUpperCase();
    const title=document.createElement('span'); title.className='gtitle'; title.textContent=g.key;
    head.appendChild(lv); head.appendChild(title); card.appendChild(head);
    g.items.forEach(it=>{
      const row=document.createElement('div'); row.className='item'; row.dataset.preview=it.preview;
      const link=document.createElement('span'); link.className='path'; link.textContent='[['+it.path+']]';
      const meta=document.createElement('span'); meta.className='meta';
      meta.textContent=it.type+' | '+it.size+'B | src='+it.sources+' | '+it.created;
      row.appendChild(link); row.appendChild(meta);
      row.addEventListener('mouseenter',showPreview); row.addEventListener('mousemove',movePreview);
      row.addEventListener('mouseleave',hidePreview); card.appendChild(row);
    });
    const opt=document.createElement('div'); opt.className='opt';
    const cb=document.createElement('input'); cb.type='checkbox'; cb.id='cb_'+g.key;
    const lab=document.createElement('label'); lab.htmlFor='cb_'+g.key; lab.textContent='合并此组';
    const extra=document.createElement('span'); extra.className='extra'; extra.style.display='none';
    const nm=document.createElement('label'); nm.textContent='合并后文件名('+g.dir+'/): ';
    const nameIn=document.createElement('input'); nameIn.type='text'; nameIn.className='namein';
    nameIn.value=g.suggest_name; nameIn.title='按命名规范推荐，可修改';
    const nt=document.createElement('label'); nt.textContent='  备注(优先级最高): ';
    const noteIn=document.createElement('input'); noteIn.type='text'; noteIn.className='notein';
    noteIn.placeholder='如：本页需保留的别名/关键信息…';
    extra.appendChild(nm); extra.appendChild(nameIn); extra.appendChild(nt); extra.appendChild(noteIn);
    cb.addEventListener('change',()=>{ extra.style.display=cb.checked?'inline':'none'; updateCount(); });
    opt.appendChild(cb); opt.appendChild(lab); opt.appendChild(extra);
    card.appendChild(opt); list.appendChild(card);
  });
  document.getElementById('progress').textContent='共 '+DATA.length+' 组候选（concepts/entities 同目录、不跨目录）';
  updateCount();
}
function updateCount(){
  const n=document.querySelectorAll('.group input[type=checkbox]:checked').length;
  document.getElementById('selcount').textContent='已勾选合并 '+n+' 组';
}
function applyBatch(act){
  document.querySelectorAll('.group').forEach(card=>{
    const lv=card.querySelector('.lv').textContent.toLowerCase();
    const cb=card.querySelector('input[type=checkbox]');
    const ex=card.querySelector('.extra');
    let on=null;
    if(act==='all') on=true;
    else if(act==='none') on=false;
    else if(act==='p0'||act==='p1'||act==='p2') on=(lv===act);
    else if(act==='invert') on=!cb.checked;
    else if(act==='inv0'||act==='inv1'||act==='inv2') on=(lv==='p'+act.slice(3))? !cb.checked : cb.checked;
    if(on!==null){ cb.checked=on; ex.style.display=on?'inline':'none'; }
  });
  updateCount();
}
document.querySelectorAll('#batch button').forEach(b=>b.addEventListener('click',()=>applyBatch(b.dataset.act)));

async function finish(){
  const ann=[];
  document.querySelectorAll('.group').forEach(card=>{
    const cb=card.querySelector('input[type=checkbox]');
    if(cb&&cb.checked){
      ann.push({ group: card.querySelector('.gtitle').textContent,
                 merge: true,
                 name: card.querySelector('.namein').value.trim(),
                 note: card.querySelector('.notein').value.trim() });
    }
  });
  const st=document.getElementById('status'); st.textContent='提交中…';
  const resp=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ annotations: ann, total: DATA.length })});
  const res=await resp.json();
  st.textContent='已保存 → '+res.path+'（勾选合并 '+ann.length+' 组，服务器即将关闭，可关闭此页）';
}
document.getElementById('finish').addEventListener('click',finish);
load();
</script>
</body>
</html>
"""


def resolve_paths(root):
    if os.path.basename(os.path.abspath(root)) == "wiki":
        return os.path.dirname(root), root
    cand = os.path.join(root, "wiki")
    if os.path.isdir(cand):
        return root, cand
    return root, root


def find_audit(repdir):
    if os.path.isdir(repdir):
        for fn in sorted(os.listdir(repdir), reverse=True):
            if fn.startswith("audit-") and fn.endswith(".json"):
                return os.path.join(repdir, fn)
    return None


def load_groups(wiki_root, aud):
    """读取 audit 的 dup_groups，仅在 concepts/entities 目录**内部**分组（同目录、不跨目录）。"""
    with open(aud, "r", encoding="utf-8") as f:
        rep = json.load(f)
    BS = chr(92)
    out = []
    for g in rep.get("dup_groups", []):
        by_dir = defaultdict(list)
        for x in g["files"]:
            if "/sources/" in x.replace(BS, "/"):
                continue
            d = os.path.basename(os.path.dirname(x))
            if d not in MERGE_DIRS:
                continue
            by_dir[d].append(x)
        for d, kept in by_dir.items():
            if len(kept) < 2:
                continue
            items = []
            for f in kept:
                fm, body, text = parse_frontmatter_file(f)
                size = os.path.getsize(f)
                srcs = fm.get("sources", [])
                nsrc = len(srcs) if isinstance(srcs, list) else (1 if srcs else 0)
                preview = (body or text).strip()
                preview = preview[:PREVIEW_LEN]
                rel = os.path.relpath(f, wiki_root).replace(BS, "/")
                if rel.endswith(".md"):
                    rel = rel[:-3]
                items.append({"path": rel, "type": fm.get("type", "-"),
                              "size": size, "sources": nsrc, "created": fm.get("created", "-"),
                              "title": str(fm.get("title", "-")), "preview": preview})
            if not items:
                continue
            # 命名规范推荐：命名最规范者的 slug 作为合并后文件名
            best_name = max(items, key=lambda it: (naming_score(it["path"].rsplit("/", 1)[-1]), it["size"]))
            out.append({"key": f"{g['key']} [{d}]", "level": g["level"], "dir": d,
                        "suggest_name": best_name["path"].rsplit("/", 1)[-1],
                        "items": items})
    out.sort(key=lambda g: {"p0": 0, "p1": 1, "p2": 2}[g["level"]])
    return out


def main():
    ensure_utf8_stdout()
    opts, pos = parse_args(sys.argv[1:], "WebUI 重复页标注工具")
    project_root, wiki_root = resolve_paths(opts["root"])
    if not os.path.isdir(wiki_root):
        p(f"[错误] 找不到 wiki 目录: {wiki_root}")
        sys.exit(1)
    repdir = opts.get("out") or os.path.join(project_root, "reports")
    aud = find_audit(repdir)
    if not aud:
        p("[错误] 未找到 reports/audit-*.json，先运行 audit.py")
        sys.exit(1)
    groups = load_groups(wiki_root, aud)
    if not groups:
        p("无候选组（concepts/entities 同目录内无重复）。")
        return

    port = 8765
    for i, a in enumerate(pos):
        if a == "--port" and i + 1 < len(pos):
            port = int(pos[i + 1])

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._send_bytes(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/data":
                self._send_bytes(json.dumps(groups, ensure_ascii=False).encode("utf-8"),
                                 "application/json; charset=utf-8")
            else:
                self.send_error(404)

        def do_POST(self):
            if urlparse(self.path).path != "/api/save":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except ValueError:
                self._send_bytes(b'{"ok":false,"error":"bad json"}', "application/json")
                return
            out_path = os.path.join(repdir, "annotations-" + os.path.basename(aud)[6:-5] + ".json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            p(f"\n标注结果已保存: {out_path}")
            p(f"勾选合并 {len(payload.get('annotations', []))} / {payload.get('total', '?')} 组")
            self._send_bytes(json.dumps({"ok": True, "path": out_path}).encode("utf-8"),
                             "application/json; charset=utf-8")
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def _send_bytes(self, data, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    p(f"候选组: {len(groups)}（concepts/entities 同目录、不跨目录）")
    p(f"Web UI 已启动: {url}  （浏览器未自动打开则手动访问）")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        p("\n已停止。")


if __name__ == "__main__":
    main()
