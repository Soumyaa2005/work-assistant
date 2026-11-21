"""Local demo page for the assistant. Standard library only.

    python3 ui.py --pack /path/to/BuildSprint-R3-candidate

Opens http://127.0.0.1:8765. Every button runs the same CLI the harness runs (my_solution.py), so what you see
is what gets scored. Reading a cited record applies the same visibility rule as the assistant.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CLI = os.path.join(HERE, "my_solution.py")


def env():
    return dict(os.environ)


def run_cli(*args):
    r = subprocess.run([sys.executable, CLI, *args], capture_output=True, text=True, env=env(), cwd=os.environ.get("ASSIST_CWD", HERE))
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"error": (r.stderr or r.stdout or "no output")[-400:]}


def days_available():
    root = os.environ["R3_PACK"]
    return sorted(int(re.search(r"day-(\d+)", f).group(1)) for f in glob.glob(os.path.join(root, "data", "days", "day-*.jsonl")))


def people():
    from assist import pack
    return [{"id": k, "name": v.get("name"), "role": v.get("role"), "org": v.get("org")} for k, v in sorted(pack.people().items())]


def record(person, rid):
    from assist import db, pack
    conn = db.connect()
    rec = db.get_record(conn, rid)
    if not rec or not pack.can_see(person, rec):
        return {"hidden": True}
    raw = rec["raw"]
    return {"id": rid, "type": rec["type"], "at": rec["at"], "author": pack.name_of(rec["author"]),
            "title": raw.get("title"), "body": raw.get("body"), "client": rec["client"]}


def status():
    from assist import db
    conn = db.connect()
    days = sorted(int(r["key"][3:]) for r in conn.execute("SELECT key FROM meta WHERE key LIKE 'day%'"))
    return {"days": days, "records": conn.execute("SELECT COUNT(*) AS c FROM records").fetchone()["c"]}


def feedback(person, words):
    from assist import db, memory as mem
    conn = db.connect()
    day = max([int(r["key"][3:]) for r in conn.execute("SELECT key FROM meta WHERE key LIKE 'day%'")] or [1])
    mem.apply_feedback(conn, [{"person": person, "day": day, "type": "preference", "words": words}])
    conn.commit()
    return {"ok": True}


def memory(person):
    from assist import db, memory as mem
    conn = db.connect()
    q = lambda sql: [dict(r) for r in conn.execute(sql, (person,))]
    p = mem.person_prefs(conn, person)
    return {"prefs": [r["words"] for r in q("SELECT words FROM prefs WHERE person=? ORDER BY id")],
            "parsed": {"max_changed": p["max_changed"], "blockers_first": p["blockers_first"], "skip": sorted(p["skip"])},
            "corrections": q("SELECT words, subject, value, client FROM corrections WHERE person=? ORDER BY id"),
            "verdicts": q("SELECT topic, verdict FROM verdicts WHERE person=? ORDER BY id"),
            "forgets": [r["words"] for r in q("SELECT words FROM forgets WHERE person=? ORDER BY id")]}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, code=200, ctype="application/json"):
        data = obj.encode() if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self.send(PAGE, ctype="text/html")
            if u.path == "/api/init":
                return self.send({"people": people(), "days": days_available(), "llm": bool(os.environ.get("GROQ_API_KEY") or os.environ.get("ASSIST_LLM_KEY"))})
            if u.path == "/api/record":
                return self.send(record(q["person"], q["id"]))
            if u.path == "/api/status":
                return self.send(status())
            if u.path == "/api/memory":
                return self.send(memory(q["person"]))
        except Exception as e:
            return self.send({"error": repr(e)}, 500)
        self.send({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        b = json.loads(self.rfile.read(n) or b"{}")
        try:
            if self.path == "/api/ingest":
                out = []
                for d in range(1, int(b["day"]) + 1):
                    out.append(run_cli("ingest", "--day", str(d)))
                return self.send({"results": out})
            if self.path == "/api/brief":
                return self.send(run_cli("brief", "--person", b["person"], "--date", b["date"]))
            if self.path == "/api/ask":
                return self.send(run_cli("ask", "--person", b["person"], "--at", b["at"], "--ask", b["text"]))
            if self.path == "/api/feedback":
                return self.send(feedback(b["person"], b["text"]))
            if self.path == "/api/forget":
                return self.send(run_cli("forget", "--person", b["person"], "--what", b["text"]))
        except Exception as e:
            return self.send({"error": repr(e)}, 500)
        self.send({"error": "not found"}, 404)


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Work assistant that remembers</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#17171a;--mut:#6e6e76;--line:#e8e8e4;--acc:#4f46e5;--accbg:#eef0ff;--ok:#127a4b;--okbg:#eaf7f0;--warn:#a15c07;--warnbg:#fff6e5;--bad:#b42318;--badbg:#fdeceb;--r:12px}
*{box-sizing:border-box}html,body{height:100%}body{margin:0;font:14.5px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--ink);background:var(--bg)}
.app{display:grid;grid-template-columns:280px 1fr;min-height:100%}
aside{background:var(--panel);border-right:1px solid var(--line);padding:22px 18px;display:flex;flex-direction:column;gap:20px;position:sticky;top:0;height:100vh;overflow:auto}
.brand{font-weight:650;font-size:16px;letter-spacing:-.01em;line-height:1.25}.brand small{display:block;font-weight:400;color:var(--mut);font-size:12px;margin-top:2px}
.sec>label,.lbl{display:block;font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin-bottom:6px}
select,input{width:100%;font:inherit;padding:9px 11px;border:1px solid var(--line);border-radius:9px;background:#fff;color:var(--ink);outline:none}
select:focus,input:focus{border-color:var(--acc);box-shadow:0 0 0 3px var(--accbg)}
button{font:inherit;font-weight:550;padding:9px 14px;border-radius:9px;border:1px solid var(--ink);background:var(--ink);color:#fff;cursor:pointer;white-space:nowrap}
button:hover{opacity:.92}button.sec{background:#fff;color:var(--ink);border-color:var(--line)}button.sec:hover{background:#fafaf8}button:disabled{opacity:.5;cursor:default}
.row{display:flex;gap:8px;align-items:center}.row>*{flex:1}.row>button{flex:0 0 auto}
.meter{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.meter div{background:var(--bg);border-radius:9px;padding:8px 10px}
.meter b{display:block;font-size:17px;letter-spacing:-.01em}.meter span{font-size:11px;color:var(--mut)}
.mem{font-size:13px}.mem h4{margin:10px 0 3px;font-size:12px;color:var(--mut);font-weight:600}.mem div.i{padding:3px 0;border-top:1px solid var(--line)}.mem div.i:first-of-type{border-top:0}
.flag{font-size:12px;color:var(--mut);display:flex;align-items:center;gap:6px}.dot{width:8px;height:8px;border-radius:50%;background:#c9c9c4}.dot.on{background:#22c55e}
main{padding:26px 34px;max-width:980px;width:100%}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin-bottom:22px}
.tab{background:none;border:0;border-bottom:2px solid transparent;border-radius:0;color:var(--mut);padding:10px 14px;font-weight:550}
.tab.on{color:var(--ink);border-bottom-color:var(--acc)}.tab:hover{color:var(--ink);opacity:1}
.panel{display:none}.panel.on{display:block}
.bar{display:flex;gap:10px;align-items:flex-end;margin-bottom:18px}.bar .g{flex:1}.bar .d{width:170px}.bar .t{width:210px}
h2{font-size:20px;margin:0 0 4px;letter-spacing:-.015em}.sub{color:var(--mut);margin:0 0 18px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;margin-bottom:14px}
.mh{display:flex;align-items:center;gap:10px;margin-bottom:10px}.mh b{font-size:15px}
.tag{font-size:11.5px;font-weight:600;padding:2px 9px;border-radius:999px}.tag.ok{background:var(--okbg);color:var(--ok)}.tag.hold{background:var(--warnbg);color:var(--warn)}.tag.ref{background:var(--badbg);color:var(--bad)}.tag.n{background:var(--bg);color:var(--mut)}
.sh{font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin:14px 0 6px}
.item{display:flex;gap:10px;padding:7px 0;border-top:1px solid var(--line);align-items:flex-start}.item:first-of-type{border-top:0}
.item .b{width:6px;height:6px;border-radius:50%;background:var(--acc);margin-top:8px;flex:0 0 6px}.item .x{flex:1}
.chip{display:inline-block;font:11.5px ui-monospace,Menlo,monospace;background:var(--accbg);color:var(--acc);border-radius:6px;padding:1px 7px;margin-left:6px;cursor:pointer;border:0}
.chip:hover{background:#e0e3ff}
.call{background:var(--accbg);border-radius:10px;padding:10px 12px;margin-top:12px}.call .sh{margin:0 0 3px;color:var(--acc)}
.promise{display:flex;justify-content:space-between;gap:10px;padding:5px 0;border-top:1px solid var(--line)}.promise:first-of-type{border-top:0}.promise span{color:var(--mut);font-size:13px}
.ans{font-size:16px}.meta{font-size:12px;color:var(--mut);margin-top:8px}
.ex{display:flex;flex-wrap:wrap;gap:6px;margin:-6px 0 16px}.ex button{background:#fff;color:var(--mut);border:1px solid var(--line);font-weight:450;font-size:12.5px;padding:4px 10px;border-radius:999px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}.two .card{margin:0}.who{font-weight:600}.who small{font-weight:400;color:var(--mut);display:block;font-size:12px}
.empty{color:var(--mut);padding:26px;text-align:center;border:1px dashed var(--line);border-radius:var(--r)}
#toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:var(--ink);color:#fff;padding:9px 16px;border-radius:999px;font-size:13px;opacity:0;transition:.2s;pointer-events:none}#toast.on{opacity:1}
#drawer{position:fixed;top:0;right:0;height:100%;width:420px;max-width:92vw;background:var(--panel);border-left:1px solid var(--line);box-shadow:-12px 0 32px rgba(0,0,0,.08);transform:translateX(105%);transition:.22s;padding:22px;overflow:auto;z-index:5}
#drawer.on{transform:none}#drawer h3{margin:0 0 4px;font-size:15px}.close{float:right;background:none;border:0;color:var(--mut);font-size:20px;padding:0 4px}
pre{white-space:pre-wrap;font:13px/1.55 ui-monospace,Menlo,monospace;background:var(--bg);border-radius:10px;padding:12px;margin:12px 0 0}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;padding:4px 10px;border-radius:999px;background:var(--bg);color:var(--mut)}
.pill.ok{background:var(--okbg);color:var(--ok)}.pill.warn{background:var(--warnbg);color:var(--warn)}
.role{font-size:12px;color:var(--mut);margin-top:5px}
.log{font:12px ui-monospace,Menlo,monospace;color:var(--mut);max-height:150px;overflow:auto}.log div{padding:2px 0;border-top:1px solid var(--line)}.log div:first-child{border-top:0}.log b{color:var(--ink);font-weight:600}
a.rv{color:var(--acc);cursor:pointer;font-size:12px;margin-left:6px}
@media(max-width:860px){.app{grid-template-columns:1fr}aside{position:static;height:auto}.two{grid-template-columns:1fr}main{padding:18px}}
</style></head><body>
<div class="app">
<aside>
<div class="brand">Work assistant that remembers<small>Briefs, answers and memory for your day</small></div>
<div class="sec"><label>Who is asking</label><select id="person"></select><div class="role" id="role"></div></div>
<div class="sec"><label>Load days</label><div class="row"><select id="day"></select><button id="ing">Ingest</button></div><div style="margin-top:8px"><span class="pill warn" id="status">Nothing loaded yet</span></div></div>
<div class="sec"><label>Tokens this session</label><div class="meter"><div><b id="tin">0</b><span>input</span></div><div><b id="tout">0</b><span>output</span></div><div><b id="tcost">$0</b><span>cost</span></div></div></div>
<div class="sec"><label>What it remembers</label><div class="mem" id="mem"></div></div>
<div class="sec" style="margin-top:auto"><label>Activity</label><div class="log" id="log"><span>No actions yet.</span></div></div>
<div class="flag"><span class="dot" id="dot"></span><span id="llmflag"></span></div>
</aside>
<main>
<div class="tabs"><button class="tab on" data-tab="brief">Brief</button><button class="tab" data-tab="ask">Ask</button><button class="tab" data-tab="forget">Forget</button><button class="tab" data-tab="priv">Privacy check</button></div>

<section class="panel on" id="p-brief"><h2>Meeting brief</h2><p class="sub">What changed since the last time this person met each client, with the record behind every line.</p>
<div class="bar"><div class="d"><label class="lbl">Meeting date</label><input id="date" type="date" value="2026-11-03"></div><button id="brief">Get brief</button><button class="sec" id="copy" style="display:none">Copy as text</button></div>
<div class="bar"><div class="g"><label class="lbl">Tell it how you want your briefs (it remembers)</label><input id="fb" placeholder="Max 3 changes, blockers first"></div><button class="sec" id="fbsave">Save preference</button></div><div id="briefout"></div></section>

<section class="panel" id="p-ask"><h2>Ask a question</h2><p class="sub">Short questions about tasks, people, billing or launch dates. Answers cite their records.</p>
<div class="bar"><div class="g"><label class="lbl">Question</label><input id="q" placeholder="Who handles billing for NB?"></div><div class="t"><label class="lbl">As of (UTC)</label><input id="at" value="2026-11-03T12:00:00Z"></div><button id="ask">Ask</button></div>
<div class="ex"><button class="sec">Who handles billing for NB?</button><button class="sec">When is the Northbeam launch?</button><button class="sec">NB ka billing kaun dekhta hai?</button></div><div id="askout"></div></section>

<section class="panel" id="p-forget"><h2>Forget something</h2><p class="sub">Tell it what to forget. It stops using and repeating that topic, for everyone.</p>
<div class="bar"><div class="g"><label class="lbl">What to forget</label><input id="fg" placeholder="Forget what I said about the Dubai trip"></div><button id="forget">Forget</button></div><div id="fgout"></div></section>

<section class="panel" id="p-priv"><h2>Privacy check</h2><p class="sub">The same question asked by two people. Only what each person may see should come back.</p>
<div class="bar"><div class="g"><label class="lbl">Question</label><input id="pq" value="Who owns billing for Northbeam?"></div></div>
<div class="bar"><div class="g"><label class="lbl">Person A</label><select id="pa"></select></div><div class="g"><label class="lbl">Person B</label><select id="pb"></select></div><button id="pv">Compare</button></div><div class="two" id="pout"></div></section>
</main></div>
<div id="drawer"><button class="close" id="dclose">×</button><div id="dbody"></div></div><div id="toast"></div>
<script>
const $=id=>document.getElementById(id);let tin=0,tout=0,tcost=0,loaded=0,lastBrief=null;const LOG=[];
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function api(p,b){const r=await fetch(p,b?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}:{});return r.json()}
function log(a,ms,note){LOG.unshift(`<div><b>${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}</b> ${esc(a)}${ms!=null?' · '+ms+' ms':''}${note?' · '+esc(note):''}</div>`);$('log').innerHTML=LOG.slice(0,8).join('')}
async function timed(a,fn,note){const t=performance.now();const r=await fn();log(a,Math.round(performance.now()-t),note&&note(r));return r}
function setStatus(s){loaded=(s.days||[]).length;const e=$('status');
if(!loaded){e.className='pill warn';e.textContent='Nothing loaded yet'}else{e.className='pill ok';e.textContent='Days 1–'+Math.max(...s.days)+' · '+s.records+' records'}
['brief','ask','forget','pv','fbsave'].forEach(i=>{$(i).disabled=!loaded;$(i).title=loaded?'':'Load a day first'})}
function setAsOf(n){const d=new Date(Date.UTC(2026,10,1+n,23,59,59));$('at').value=d.toISOString().slice(0,19)+'Z'}
function setRole(){const o=$('person').selectedOptions[0];$('role').textContent=o?(o.dataset.role+' · '+o.dataset.org):''}
function toast(t){const e=$('toast');e.textContent=t;e.classList.add('on');setTimeout(()=>e.classList.remove('on'),2200)}
function usage(u){if(!u)return;tin+=u.input_tokens||0;tout+=u.output_tokens||0;tcost+=u.cost_usd||0;$('tin').textContent=tin;$('tout').textContent=tout;$('tcost').textContent='$'+tcost.toFixed(4)}
function chips(ids){return (ids||[]).map(i=>`<button class="chip" data-id="${esc(i)}">${esc(i)}</button>`).join('')}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===t));document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('on',p.id==='p-'+t.dataset.tab))});
document.addEventListener('click',e=>{const id=e.target.dataset&&e.target.dataset.id;if(id)openRec(id)});
$('dclose').onclick=()=>$('drawer').classList.remove('on');
async function openRec(id){const r=await api(`/api/record?person=${$('person').value}&id=${id}`);$('drawer').classList.add('on');
$('dbody').innerHTML=r.hidden?`<h3>${esc(id)}</h3><p><span class="tag ref">Not visible to this person</span></p><p class="mut" style="color:var(--mut)">This record is private or belongs to another company, so it cannot be shown or cited.</p>`
:`<h3>${esc(r.title||r.type)}</h3><div class="meta">${esc(r.id)} · ${esc(r.type)} · ${esc(r.at)}<br>by ${esc(r.author)}</div><pre>${esc(r.body||'(no text)')}</pre>`}
async function loadMem(){const m=await api('/api/memory?person='+$('person').value);if(m.error){$('mem').innerHTML='<span style="color:var(--mut)">Load a day first.</span>';return}
const sec=(t,a)=>a.length?`<h4>${t}</h4>`+a.map(x=>`<div class="i">${esc(x)}</div>`).join(''):'';const p=m.parsed;const rd=[];
if(p.max_changed)rd.push('max '+p.max_changed+' changes');if(p.blockers_first)rd.push('blockers first');if(p.skip.length)rd.push('skipping '+p.skip.length+' topic'+(p.skip.length>1?'s':''));
$('mem').innerHTML=sec('Preferences',m.prefs)+sec('Applied as',rd)+sec('Corrections',m.corrections.map(c=>c.words))+sec('Verdicts',m.verdicts.map(v=>v.verdict+': '+v.topic))+(m.forgets.length?`<h4>Forgotten</h4><div class="i">${m.forgets.length} topic${m.forgets.length>1?'s':''} <a class="rv" id="rv">show</a><div id="rvt" style="display:none;margin-top:4px;color:var(--mut)">${m.forgets.map(esc).join('<br>')}</div></div>`:'')||'<span style="color:var(--mut)">Nothing stored yet.</span>'}
document.addEventListener('click',e=>{if(e.target.id==='rv'){const t=$('rvt');const on=t.style.display==='none';t.style.display=on?'block':'none';e.target.textContent=on?'hide':'show'}});
function ansHtml(r){let h='';
if(r.refused)h+=`<div class="mh"><span class="tag ref">Held back · refused</span></div><div>${esc(r.refused.reason==='private'?'That is private, so it cannot be shared.':r.refused.reason||'')}</div>`;
else if(r.clarify)h+=`<div class="mh"><span class="tag hold">Held back · needs clarifying</span></div><div class="ans">${esc(r.clarify.question)}</div><div class="meta">${(r.clarify.options||[]).map(o=>esc(o.text)+' · '+esc(o.id)).join('   ')}</div>`;
else if(r.answer){const none=!(r.answer.sources||[]).length;h+=`<div class="mh"><span class="tag ${none?'hold':'ok'}">${none?'Nothing found':'Answered'}</span></div><div class="ans">${esc(r.answer.text)}${chips(r.answer.sources)}</div>`;
if((r.matched||[]).length)h+=`<div class="meta">Matched ${r.matched.map(m=>'“'+esc(m.phrase)+'” → '+esc(m.id)).join(', ')}</div>`}
else h+=`<div style="color:var(--mut)">${esc(r.error||'No answer')}</div>`;
if(r.usage)h+=`<div class="meta">${r.usage.input_tokens} in · ${r.usage.output_tokens} out · $${r.usage.cost_usd} · ${r.usage.ms} ms</div>`;return h}
$('ing').onclick=async()=>{$('ing').disabled=true;$('status').className='pill warn';$('status').textContent='Loading…';const r=await timed('Ingest days 1–'+$('day').value,()=>api('/api/ingest',{day:+$('day').value}));r.results.forEach(x=>usage(x.usage));{const st=await api('/api/status');setStatus(st);if(st.days&&st.days.length)setAsOf(Math.max(...st.days))}
toast('Loaded days 1–'+$('day').value+' ('+r.results.map(x=>x.records??'done').join(' · ')+' records)');$('ing').disabled=false;loadMem()};
$('brief').onclick=async()=>{$('briefout').innerHTML='<div class="empty">Working…</div>';const r=await timed('Brief '+$('person').value+' '+$('date').value,()=>api('/api/brief',{person:$('person').value,date:$('date').value}),x=>Array.isArray(x)?x.length+' meeting(s)':'error');lastBrief=Array.isArray(r)?r:null;$('copy').style.display=lastBrief&&lastBrief.length?'inline-block':'none';
if(!Array.isArray(r)){$('briefout').innerHTML=`<div class="empty">${esc(r.error||'Error')}</div>`;return}
if(!r.length){$('briefout').innerHTML='<div class="empty">No client meeting for this person on that date.</div>';return}
$('briefout').innerHTML=r.map(b=>{usage(b.usage);let h=`<div class="card"><div class="mh"><b>${esc(b.meeting_id)}</b>`;
if(b.status!=='brief'){h+=`<span class="tag hold">Held back · ${esc(b.status.replace('_',' '))}</span></div>`+(b.clarify?`<div>${esc(b.clarify)}</div>`:'<div style="color:var(--mut)">Nothing new since the last meeting with this client.</div>')}
else{h+='<span class="tag ok">Brief</span></div><div class="sh" style="margin-top:0">What changed</div>'+(b.changed||[]).map(c=>`<div class="item"><span class="b"></span><div class="x">${esc(c.text)}${chips(c.sources)}</div></div>`).join('');
if((b.promises||[]).length)h+='<div class="sh">Open promises</div>'+b.promises.map(p=>`<div class="promise"><div>${esc(p.what)}${chips(p.sources)}</div><span>${esc(p.owner)} · due ${esc(p.due)}</span></div>`).join('');
if((b.open_these||[]).length)h+='<div class="sh">Read these first</div>'+b.open_these.map(o=>`<div class="item"><span class="b"></span><div class="x">${esc(o.why)}${chips([o.record])}</div></div>`).join('');
if(b.question_to_ask)h+=`<div class="call"><div class="sh">Question to ask</div>${esc(b.question_to_ask.text)}${chips(b.question_to_ask.sources)}</div>`}
return h+'</div>'}).join('')};
$('ask').onclick=async()=>{const r=await timed('Ask '+$('person').value,()=>api('/api/ask',{person:$('person').value,at:$('at').value,text:$('q').value}),x=>x.refused?'refused':x.clarify?'clarify':(x.answer&&x.answer.sources&&x.answer.sources.length?'answered':'nothing found'));usage(r.usage);$('askout').innerHTML=`<div class="card">${ansHtml(r)}</div>`};
$('q').addEventListener('keydown',e=>{if(e.key==='Enter')$('ask').click()});
document.querySelectorAll('.ex button').forEach(b=>b.onclick=()=>{$('q').value=b.textContent;$('ask').click()});
$('fbsave').onclick=async()=>{const w=$('fb').value.trim();if(!w)return;const r=await timed('Preference '+$('person').value,()=>api('/api/feedback',{person:$('person').value,text:w}));toast(r.ok?'Saved. Get the brief again to see it applied.':(r.error||'Failed'));loadMem()};
$('fb').addEventListener('keydown',e=>{if(e.key==='Enter')$('fbsave').click()});
$('forget').onclick=async()=>{const r=await timed('Forget '+$('person').value,()=>api('/api/forget',{person:$('person').value,text:$('fg').value}));
$('fgout').innerHTML=r.ok?'<div class="card"><span class="tag ok">Done</span> Forgotten. Ask about it on the Ask tab to check it is gone.</div>':`<div class="card">${esc(r.error||'Failed')}</div>`;loadMem()};
$('pv').onclick=async()=>{const out=$('pout');out.innerHTML='';for(const sel of ['pa','pb']){const p=$(sel).value;const r=await timed('Privacy ask '+p,()=>api('/api/ask',{person:p,at:$('at').value,text:$('pq').value}));usage(r.usage);
const d=document.createElement('div');d.className='card';d.innerHTML=`<div class="who">${esc($(sel).selectedOptions[0].dataset.name)}<small>${esc($(sel).selectedOptions[0].dataset.org)} · ${esc(p)}</small></div><div class="sh">Result</div>`+ansHtml(r);out.appendChild(d)}};
$('person').onchange=()=>{setRole();loadMem()};
$('date').addEventListener('keydown',e=>{if(e.key==='Enter')$('brief').click()});
$('fg').addEventListener('keydown',e=>{if(e.key==='Enter')$('forget').click()});
$('copy').onclick=async()=>{if(!lastBrief)return;const t=lastBrief.map(b=>b.meeting_id+' ['+b.status+']\n'+(b.changed||[]).map(c=>'- '+c.text+' ('+(c.sources||[]).join(', ')+')').join('\n')+((b.promises||[]).length?'\nOpen promises:\n'+b.promises.map(p=>'- '+p.what+' ('+p.owner+', due '+p.due+')').join('\n'):'')).join('\n\n');
try{await navigator.clipboard.writeText(t);toast('Copied')}catch(e){toast('Copy not allowed here')}};
(async()=>{const i=await api('/api/init');const opt=p=>`<option value="${p.id}" data-name="${esc(p.name)}" data-org="${p.org==='org_bw'?'Brightwave':'Kitepoint'}" data-role="${esc(p.role||'')}">${esc(p.name)} · ${p.id}${p.org==='org_bw'?' · Brightwave':''}</option>`;
$('person').innerHTML=$('pa').innerHTML=$('pb').innerHTML=i.people.map(opt).join('');
$('pa').value=i.people.find(p=>p.org!=='org_bw')?.id;$('pb').value=i.people.find(p=>p.org==='org_bw')?.id||i.people[0].id;
$('day').innerHTML=i.days.map(d=>`<option value="${d}">through day ${d}</option>`).join('');$('day').value=i.days[Math.min(2,i.days.length-1)];
$('llmflag').textContent=i.llm?'Model fallback on':'Rules only (no model)';$('dot').classList.toggle('on',i.llm);setRole();{const st=await api('/api/status');setStatus(st);if(st.days&&st.days.length)setAsOf(Math.max(...st.days))}loadMem()})();
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default=os.environ.get("R3_PACK") or os.getcwd())
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    os.environ["R3_PACK"] = os.path.abspath(a.pack)
    os.environ.setdefault("ASSIST_STORE", os.path.join(os.path.abspath(a.pack), ".assist_store.sqlite"))
    os.environ.setdefault("ASSIST_CWD", os.path.abspath(a.pack))
    if not os.path.isdir(os.path.join(os.environ["R3_PACK"], "data", "days")):
        sys.exit(f"No data/days folder under {os.environ['R3_PACK']}. Pass --pack /path/to/BuildSprint-R3-candidate")
    url = f"http://127.0.0.1:{a.port}"
    print(f"Serving {url}  (pack: {os.environ['R3_PACK']}, store: {os.environ['ASSIST_STORE']})  Ctrl+C to stop")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
