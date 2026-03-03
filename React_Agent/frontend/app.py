import streamlit as st
import requests
import re
import json
import time
import streamlit.components.v1 as _components

# ─────────────────────────────────────────────
#  PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Nexus Research",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def extract_urls(text):
    return list(set(re.findall(r"https?://[^\s\"'<>)]+", text)))

def tool_class(name):
    n = name.lower()
    if "arxiv"  in n: return "arxiv"
    if "wiki"   in n: return "wiki"
    if "tavily" in n: return "tavily"
    return "default"

def tool_icon(name):
    n = name.lower()
    if "arxiv"  in n: return "📄"
    if "wiki"   in n: return "📖"
    if "tavily" in n: return "🌐"
    return "🔧"

def now_stamp():
    t = time.localtime()
    return f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"

def scroll_to_bottom():
    _components.html(
        """<script>
        (function() {
            function doScroll() {
                try {
                    var panel = window.parent.document.getElementById('nx-chat');
                    if (panel) { panel.scrollTop = panel.scrollHeight; }
                } catch(e) {}
            }
            doScroll();
            setTimeout(doScroll, 150);
            setTimeout(doScroll, 400);
        })();
        </script>""",
        height=0, scrolling=False,
    )

def to_html(text):
    import html as _html
    import re as _re
    t = text
    t = _re.sub(r'```[\w]*\n(.*?)```', lambda m: '<pre><code>' + _html.escape(m.group(1)) + '</code></pre>', t, flags=_re.DOTALL)
    t = _re.sub(r'`([^`]+)`', lambda m: '<code>' + _html.escape(m.group(1)) + '</code>', t)
    t = _re.sub(r'^### (.+)$', r'<h3>\1</h3>', t, flags=_re.MULTILINE)
    t = _re.sub(r'^## (.+)$',  r'<h2>\1</h2>', t, flags=_re.MULTILINE)
    t = _re.sub(r'^# (.+)$',   r'<h1>\1</h1>', t, flags=_re.MULTILINE)
    t = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
    t = _re.sub(r'__(.+?)__',     r'<strong>\1</strong>', t)
    t = _re.sub(r'\*([^\*\n]+?)\*', r'<em>\1</em>', t)
    t = _re.sub(r'(?<![_])_([^_\n]+?)_(?![_])', r'<em>\1</em>', t)
    t = _re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', t)
    lines = t.split('\n')
    result = []
    in_ul = in_ol = False
    for line in lines:
        ul_match = _re.match(r'^[\s]*[-*•] (.+)$', line)
        ol_match = _re.match(r'^[\s]*(\d+)\. (.+)$', line)
        if ul_match:
            if in_ol: result.append('</ol>'); in_ol = False
            if not in_ul: result.append('<ul>'); in_ul = True
            result.append(f'<li>{ul_match.group(1)}</li>')
        elif ol_match:
            if in_ul: result.append('</ul>'); in_ul = False
            if not in_ol: result.append('<ol>'); in_ol = True
            result.append(f'<li>{ol_match.group(2)}</li>')
        else:
            if in_ul: result.append('</ul>'); in_ul = False
            if in_ol: result.append('</ol>'); in_ol = False
            stripped = line.strip()
            if stripped == '': result.append('<br>')
            elif stripped.startswith('<h') or stripped.startswith('<pre'): result.append(stripped)
            else: result.append(f'<p>{stripped}</p>')
    if in_ul: result.append('</ul>')
    if in_ol: result.append('</ol>')
    return '\n'.join(result)

# ─────────────────────────────────────────────
#  NEW: AGENT PIPELINE HTML BUILDERS
# ─────────────────────────────────────────────
def build_planner_html(tasks, report_format, reasoning):
    """Renders the planner's task breakdown visually."""
    tool_colors = {"arxiv": "#f59e0b", "wiki": "#60a5fa", "tavily": "#a78bfa"}
    tool_icons  = {"arxiv": "📄", "wiki": "📖", "tavily": "🌐"}

    task_rows = ""
    for i, t in enumerate(tasks, 1):
        tool   = t.get("tool", "?")
        goal   = t.get("goal", "")
        color  = tool_colors.get(tool, "#00ffb4")
        icon   = tool_icons.get(tool, "🔧")
        task_rows += f"""
        <div class="agent-task">
          <span class="task-num">TASK {i}</span>
          <span class="task-tool" style="color:{color};border-color:{color}40">{icon} {tool.upper()}</span>
          <span class="task-goal">{goal}</span>
        </div>"""

    fmt_badge = f'<span class="fmt-badge">{report_format.replace("_"," ").upper()}</span>' if report_format else ""

    return f"""
    <div class="agent-block planner-block">
      <div class="agent-header">
        <span class="agent-icon">🧠</span>
        <span class="agent-name">PLANNER</span>
        <span class="agent-done">✓ DONE</span>
        {fmt_badge}
      </div>
      <div class="agent-reasoning">{reasoning}</div>
      {task_rows}
    </div>"""


def build_retrieval_html(retrieval_steps):
    """Renders live retrieval steps as they come in."""
    tool_colors = {"arxiv": "#f59e0b", "wiki": "#60a5fa", "tavily": "#a78bfa"}
    tool_icons  = {"arxiv": "📄", "wiki": "📖", "tavily": "🌐"}

    rows = ""
    for step in retrieval_steps:
        source  = step.get("source", "?")
        goal    = step.get("goal", "")
        score   = step.get("score", 0)
        color   = tool_colors.get(source, "#00ffb4")
        icon    = tool_icons.get(source, "🔧")
        bar_w   = int(score * 100)
        rows += f"""
        <div class="retrieval-step" style="border-left-color:{color}">
          <div class="ret-top">
            <span style="color:{color}">{icon} {source.upper()}</span>
            <span class="ret-goal">{goal[:70]}</span>
            <span class="ret-score">{score:.2f}</span>
          </div>
          <div class="score-bar"><div class="score-fill" style="width:{bar_w}%;background:{color}"></div></div>
        </div>"""

    return f"""
    <div class="agent-block retrieval-block">
      <div class="agent-header">
        <span class="agent-icon">🔍</span>
        <span class="agent-name">RETRIEVAL AGENTS</span>
        <span class="agent-pulse"><span class="dot-pulse"></span></span>
      </div>
      {rows}
    </div>"""


def build_retrieval_done_html(retrieval_steps):
    """Same as above but with DONE badge instead of pulse."""
    tool_colors = {"arxiv": "#f59e0b", "wiki": "#60a5fa", "tavily": "#a78bfa"}
    tool_icons  = {"arxiv": "📄", "wiki": "📖", "tavily": "🌐"}

    rows = ""
    for step in retrieval_steps:
        source  = step.get("source", "?")
        goal    = step.get("goal", "")
        score   = step.get("score", 0)
        color   = tool_colors.get(source, "#00ffb4")
        icon    = tool_icons.get(source, "🔧")
        bar_w   = int(score * 100)
        rows += f"""
        <div class="retrieval-step" style="border-left-color:{color}">
          <div class="ret-top">
            <span style="color:{color}">{icon} {source.upper()}</span>
            <span class="ret-goal">{goal[:70]}</span>
            <span class="ret-score">{score:.2f}</span>
          </div>
          <div class="score-bar"><div class="score-fill" style="width:{bar_w}%;background:{color}"></div></div>
        </div>"""

    return f"""
    <div class="agent-block retrieval-block">
      <div class="agent-header">
        <span class="agent-icon">🔍</span>
        <span class="agent-name">RETRIEVAL AGENTS</span>
        <span class="agent-done">✓ DONE</span>
      </div>
      {rows}
    </div>"""


def build_synthesizer_html(done=False):
    status = '<span class="agent-done">✓ DONE</span>' if done else '<span class="agent-pulse"><span class="dot-pulse"></span></span>'
    return f"""
    <div class="agent-block synth-block">
      <div class="agent-header">
        <span class="agent-icon">⚗️</span>
        <span class="agent-name">SYNTHESIZER</span>
        {status}
      </div>
      {"<div class='agent-reasoning'>Merging and cross-referencing all source data…</div>" if not done else
       "<div class='agent-reasoning'>All sources merged — redundancy removed, insights extracted.</div>"}
    </div>"""


def build_critic_html(verdict="", feedback="", loops=0, done=False):
    if not done:
        return f"""
        <div class="agent-block critic-block">
          <div class="agent-header">
            <span class="agent-icon">🔬</span>
            <span class="agent-name">CRITIC</span>
            <span class="agent-pulse"><span class="dot-pulse"></span></span>
          </div>
          <div class="agent-reasoning">Validating synthesis for contradictions and gaps…</div>
        </div>"""

    verdict_color = "#00ffb4" if verdict == "PASS" else "#f59e0b"
    verdict_icon  = "✓" if verdict == "PASS" else "↺"
    loop_txt      = f' (loop {loops})' if loops > 1 else ""

    return f"""
    <div class="agent-block critic-block">
      <div class="agent-header">
        <span class="agent-icon">🔬</span>
        <span class="agent-name">CRITIC</span>
        <span class="agent-done" style="color:{verdict_color};border-color:{verdict_color}40">
          {verdict_icon} {verdict}{loop_txt}
        </span>
      </div>
      <div class="agent-reasoning">{feedback[:120]}{"…" if len(feedback) > 120 else ""}</div>
    </div>"""


def build_writing_html():
    return """
    <div class="agent-block writing-block">
      <div class="agent-header">
        <span class="agent-icon">📝</span>
        <span class="agent-name">REPORT GENERATOR</span>
        <span class="agent-pulse"><span class="dot-pulse"></span></span>
      </div>
      <div class="agent-reasoning">Generating final report…</div>
    </div>"""


def build_pipeline_html(planner_html, retrieval_html, synth_html, critic_html, writing_html):
    """Combines all agent blocks into a single pipeline display inside the thinking box."""
    blocks = "".join(b for b in [planner_html, retrieval_html, synth_html, critic_html, writing_html] if b)
    return f"""
    <div class="nx-thinking">
      <div class="th-label">⬡ NEXUS PIPELINE <span class="dot-pulse"></span></div>
      {blocks}
    </div>"""

# ─────────────────────────────────────────────
#  SESSION STATE
# ─────────────────────────────────────────────
for key, val in [
    ("chat", []), ("sources_all", []), ("activity", []),
    ("query_count", 0), ("tool_count", 0),
    ("api_key", ""), ("authenticated", False)
]:
    if key not in st.session_state:
        st.session_state[key] = val
if "last_session_id" not in st.session_state:
    st.session_state.last_session_id = None

# ─────────────────────────────────────────────
#  CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;700;800&display=swap');

*, *::before, *::after { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #050912 !important; }

#MainMenu, footer, header,
[data-testid="stDecoration"],
[data-testid="stToolbar"],
[data-testid="stStatusWidget"] { display: none !important; }

[data-testid="stAppViewContainer"] {
    background: #050912 !important;
    font-family: 'Space Mono', monospace;
    color: #dde8ff;
}
[data-testid="stAppViewContainer"]::before {
    content: ""; pointer-events: none;
    position: fixed; inset: 0; z-index: 9999;
    background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,255,180,0.016) 2px, rgba(0,255,180,0.016) 4px);
}
[data-testid="stAppViewContainer"]::after {
    content: ""; pointer-events: none;
    position: fixed; inset: 0; z-index: 9998;
    background: radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,0.7) 100%);
}
[data-testid="stMain"] {
    background:
        linear-gradient(rgba(0,255,180,0.025) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,255,180,0.025) 1px, transparent 1px) !important;
    background-size: 40px 40px !important;
}
.block-container { padding: 0 !important; max-width: 100% !important; }
[data-testid="stHorizontalBlock"] { gap: 0 !important; }

/* ── HEADER ── */
.nx-header {
    padding: 13px 28px; border-bottom: 1px solid rgba(0,255,180,0.12);
    display: flex; align-items: center; gap: 16px;
    background: #050912; position: relative;
}
.nx-header::after {
    content: ""; position: absolute; bottom: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, #00ffb4, transparent);
    animation: hpulse 3s ease-in-out infinite;
}
@keyframes hpulse { 0%,100%{opacity:.25} 50%{opacity:.9} }
.nx-logo {
    width: 36px; height: 36px; flex-shrink: 0;
    border: 2px solid #00ffb4; border-radius: 8px;
    display: flex; align-items: center; justify-content: center; font-size: 16px;
    animation: glow 2.5s ease-in-out infinite;
}
@keyframes glow { 0%,100%{ box-shadow: 0 0 10px rgba(0,255,180,.28); } 50%{ box-shadow: 0 0 22px rgba(0,255,180,.65); } }
.nx-title { font-family:'Syne',sans-serif; font-size:19px; font-weight:800; color:#fff; }
.nx-sub   { font-size:8px; color:#00ffb4; letter-spacing:3px; text-transform:uppercase; opacity:.55; margin-top:2px; }
.nx-badge {
    margin-left: auto; padding: 3px 10px;
    background: rgba(0,255,180,.07); border: 1px solid rgba(0,255,180,.22);
    border-radius: 4px; font-size: 9px; color: #00ffb4; letter-spacing: 2px; flex-shrink: 0;
}

/* ── PANELS ── */
.nx-panel {
    height: calc(100vh - 68px); overflow-y: auto; overflow-x: hidden;
    padding: 22px 26px 96px;
    scrollbar-width: thin; scrollbar-color: rgba(0,255,180,.18) transparent;
}
.nx-panel::-webkit-scrollbar { width: 4px; }
.nx-panel::-webkit-scrollbar-thumb { background: rgba(0,255,180,.18); border-radius: 4px; }
.nx-side {
    height: calc(100vh - 68px); overflow-y: auto; overflow-x: hidden;
    padding: 18px 15px 96px;
    border-left: 1px solid rgba(0,255,180,.07);
    background: rgba(0,255,180,.012);
    scrollbar-width: thin; scrollbar-color: rgba(0,255,180,.1) transparent;
}
.nx-side::-webkit-scrollbar { width: 3px; }
.nx-side::-webkit-scrollbar-thumb { background: rgba(0,255,180,.12); border-radius: 3px; }

/* ── MESSAGES ── */
.msg-user {
    background: rgba(0,100,255,.1); border: 1px solid rgba(0,100,255,.3);
    border-radius: 12px 12px 4px 12px; padding: 12px 15px; margin-bottom: 16px;
    position: relative; font-size: 14px; color: #ddeeff; animation: fadeup .25s ease;
}
.msg-user::before {
    content:"YOU"; position:absolute; top:-8px; right:11px;
    background:#050912; padding:0 5px;
    font-size:8px; color:rgba(80,140,255,.65); letter-spacing:2px;
}
.msg-agent {
    background: rgba(0,255,180,.05); border: 1px solid rgba(0,255,180,.18);
    border-radius: 12px 12px 12px 4px; padding: 12px 15px; margin-bottom: 16px;
    line-height: 1.75; font-size: 13.5px; color: #e2ecff;
    position: relative; white-space: normal !important; animation: fadeup .25s ease;
}
.msg-agent::before {
    content:"NEXUS"; position:absolute; top:-8px; left:11px;
    background:#050912; padding:0 5px;
    font-size:8px; color:#00ffb4; letter-spacing:2px;
}
@keyframes fadeup { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:none} }

.msg-agent p { margin: 0 0 10px; color: #dde8ff; line-height: 1.75; }
.msg-agent p:last-child { margin-bottom: 0; }
.msg-agent h1,.msg-agent h2,.msg-agent h3,.msg-agent h4 {
    font-family:'Syne',sans-serif; font-weight:700; color:#fff;
    margin:14px 0 6px; border-bottom:1px solid rgba(0,255,180,.1); padding-bottom:4px;
}
.msg-agent h1{font-size:17px} .msg-agent h2{font-size:15px} .msg-agent h3{font-size:14px;color:#b8fce8;border-bottom:none}
.msg-agent strong,.msg-agent b { color:#00ffb4; font-weight:700; }
.msg-agent em,.msg-agent i { color:#c4b5fd; font-style:italic; }
.msg-agent ul { list-style:none; padding-left:0; margin:6px 0 10px; }
.msg-agent ul li { padding:3px 0 3px 18px; color:#dde8ff; position:relative; border-bottom:1px solid rgba(255,255,255,.03); }
.msg-agent ul li::before { content:"⬡"; position:absolute; left:0; color:#00ffb4; font-size:8px; top:6px; opacity:.7; }
.msg-agent ol { padding-left:20px; margin:6px 0 10px; }
.msg-agent ol li { color:#dde8ff; padding:3px 0; }
.msg-agent ol li::marker { color:#00ffb4; font-weight:700; }
.msg-agent code {
    background:rgba(0,255,180,.08); border:1px solid rgba(0,255,180,.2);
    border-radius:4px; padding:1px 7px; font-size:12px; color:#00ffb4; font-family:'Space Mono',monospace;
}
.msg-agent pre {
    background:rgba(0,0,0,.4); border:1px solid rgba(0,255,180,.15);
    border-radius:8px; padding:12px 14px; overflow-x:auto; margin:8px 0;
}
.msg-agent pre code { background:none; border:none; padding:0; font-size:12px; }
.msg-agent a { color:#60a5fa; text-decoration:underline; }
.msg-agent table { border-collapse:collapse; width:100%; margin:8px 0; font-size:12px; }
.msg-agent th { background:rgba(0,255,180,.08); color:#00ffb4; padding:6px 10px; text-align:left; }
.msg-agent td { padding:5px 10px; border-bottom:1px solid rgba(255,255,255,.05); color:#dde8ff; }

/* ── THINKING BOX ── */
.nx-thinking {
    border:1px solid rgba(0,255,180,.18); border-radius:10px;
    padding:13px 16px; margin-bottom:16px;
    background:rgba(0,255,180,.025); position:relative; overflow:hidden;
}
.nx-thinking::before {
    content:""; position:absolute; top:0; left:-60%; width:55%; height:100%;
    background:linear-gradient(90deg,transparent,rgba(0,255,180,.07),transparent);
    animation:sweep 2s ease-in-out infinite;
}
@keyframes sweep { from{left:-60%} to{left:110%} }
.th-label {
    font-size:9px; letter-spacing:3px; color:#00ffb4; margin-bottom:10px;
    display:flex; align-items:center; gap:8px;
}
.dot-pulse::after {
    content:"●●●"; letter-spacing:4px;
    animation:dts 1.2s steps(3,end) infinite;
}
@keyframes dts { 0%{content:"●○○"} 33%{content:"●●○"} 66%{content:"●●●"} 100%{content:"○○○"} }

/* ── AGENT BLOCKS ── */
.agent-block {
    border-radius:8px; padding:10px 12px; margin-bottom:8px;
    background:rgba(255,255,255,.02); border:1px solid rgba(255,255,255,.06);
    animation:slidein .2s ease;
}
@keyframes slidein { from{opacity:0;transform:translateX(-6px)} to{opacity:1;transform:none} }
.planner-block  { border-left:3px solid #00ffb4; }
.retrieval-block{ border-left:3px solid #a78bfa; }
.synth-block    { border-left:3px solid #34d399; }
.critic-block   { border-left:3px solid #f59e0b; }
.writing-block  { border-left:3px solid #60a5fa; }

.agent-header {
    display:flex; align-items:center; gap:8px;
    font-size:10px; letter-spacing:2px; margin-bottom:6px;
}
.agent-icon  { font-size:13px; }
.agent-name  { color:#fff; font-weight:700; flex:1; }
.agent-done  {
    font-size:8px; letter-spacing:1px; color:#00ffb4;
    background:rgba(0,255,180,.08); border:1px solid rgba(0,255,180,.2);
    border-radius:4px; padding:2px 7px;
}
.agent-pulse { font-size:10px; color:#00ffb4; }
.agent-reasoning {
    font-size:11px; color:rgba(180,200,240,.55);
    font-style:italic; margin-bottom:6px; line-height:1.5;
}
.fmt-badge {
    font-size:8px; letter-spacing:1px; color:#a78bfa;
    background:rgba(167,139,250,.08); border:1px solid rgba(167,139,250,.2);
    border-radius:4px; padding:2px 7px;
}

/* Planner task rows */
.agent-task {
    display:flex; align-items:center; gap:8px;
    padding:5px 8px; margin-bottom:3px; border-radius:5px;
    background:rgba(255,255,255,.02); font-size:11px;
}
.task-num  { font-size:8px; color:rgba(0,255,180,.4); letter-spacing:1px; white-space:nowrap; }
.task-tool {
    font-size:9px; letter-spacing:1px; border:1px solid;
    border-radius:4px; padding:1px 6px; white-space:nowrap;
}
.task-goal { color:rgba(200,220,255,.7); flex:1; }

/* Retrieval steps */
.retrieval-step {
    border-left:3px solid; border-radius:0 6px 6px 0;
    padding:6px 10px; margin-bottom:5px;
    background:rgba(255,255,255,.015);
}
.ret-top { display:flex; align-items:center; gap:8px; font-size:11px; margin-bottom:4px; }
.ret-goal { flex:1; color:rgba(200,220,255,.6); font-size:10px; }
.ret-score { font-size:9px; color:rgba(0,255,180,.6); white-space:nowrap; }
.score-bar { height:2px; background:rgba(255,255,255,.06); border-radius:1px; }
.score-fill { height:100%; border-radius:1px; transition:width .4s ease; }

/* ── SIDEBAR ── */
.side-title {
    font-size:9px; letter-spacing:3px; color:#00ffb4; text-transform:uppercase;
    padding-bottom:7px; margin-bottom:9px; border-bottom:1px solid rgba(0,255,180,.1);
}
.stat-row { display:flex; gap:5px; margin-bottom:13px; }
.stat-box {
    flex:1; background:rgba(0,255,180,.04); border:1px solid rgba(0,255,180,.09);
    border-radius:8px; padding:8px; text-align:center;
}
.stat-num { font-family:'Syne',sans-serif; font-size:19px; font-weight:800; color:#00ffb4; line-height:1; text-shadow:0 0 12px rgba(0,255,180,.4); }
.stat-lbl { font-size:8px; color:#6b7280; letter-spacing:1.5px; text-transform:uppercase; margin-top:3px; }
.source-card {
    background:rgba(255,255,255,.02); border:1px solid rgba(255,255,255,.07);
    border-radius:8px; padding:8px 10px; margin-bottom:6px; font-size:11px;
}
.source-num  { font-size:8px; color:#00ffb4; letter-spacing:2px; margin-bottom:3px; }
.source-link { color:#93c5fd; text-decoration:none; word-break:break-all; line-height:1.4; }
.activity-item {
    font-size:10px; color:#4b5563; padding:5px 0;
    border-bottom:1px solid rgba(255,255,255,.03);
    display:flex; gap:8px;
}
.activity-time { color:#00ffb4; opacity:.4; white-space:nowrap; }

/* ── EMPTY STATE ── */
.empty-state {
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    height:65%; gap:12px; text-align:center; padding-top:40px;
}
.empty-hex  { font-size:50px; opacity:.16; animation:float 3s ease-in-out infinite; }
@keyframes float { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-8px)} }
.empty-text { font-family:'Syne',sans-serif; font-size:15px; font-weight:700; color:rgba(255,255,255,.12); }
.empty-sub  { font-size:9px; letter-spacing:2px; color:rgba(0,255,180,.18); }

/* ── LOGIN ── */
.login-gate { position:fixed; inset:0; z-index:9997; display:flex; align-items:center; justify-content:center; background:#050912; }
.login-err {
    background:rgba(239,68,68,.08); border:1px solid rgba(239,68,68,.25);
    border-radius:8px; padding:8px 14px; font-size:12px; color:#fca5a5;
    margin-top:10px; animation:fadeup .2s ease;
}
div[data-testid="stTextInput"] input {
    background:rgba(5,15,30,.95) !important; border:1px solid rgba(0,255,180,.35) !important;
    border-radius:10px !important; color:#e0f0ff !important; caret-color:#00ffb4 !important;
    font-family:'Space Mono',monospace !important; font-size:13px !important;
    padding:10px 14px !important; text-align:center !important;
    -webkit-text-fill-color:#e0f0ff !important;
}
div[data-testid="stTextInput"] input:focus { border-color:rgba(0,255,180,.65) !important; box-shadow:0 0 0 2px rgba(0,255,180,.15) !important; outline:none !important; }
div[data-testid="stTextInput"] input::placeholder { color:rgba(150,180,220,.4) !important; -webkit-text-fill-color:rgba(150,180,220,.4) !important; }
div[data-testid="stButton"] > button {
    background:rgba(0,255,180,.08) !important; border:1px solid rgba(0,255,180,.35) !important;
    color:#00ffb4 !important; font-family:'Space Mono',monospace !important;
    font-size:11px !important; letter-spacing:3px !important;
    border-radius:10px !important; padding:10px !important; text-transform:uppercase !important;
    transition:all .2s ease !important;
}
div[data-testid="stButton"] > button:hover { background:rgba(0,255,180,.18) !important; border-color:rgba(0,255,180,.7) !important; box-shadow:0 0 16px rgba(0,255,180,.2) !important; }
button[kind="secondary"],[data-testid="stBaseButton-secondary"] {
    background:rgba(239,68,68,.07) !important; border:1px solid rgba(239,68,68,.25) !important;
    color:rgba(239,68,68,.8) !important; font-family:'Space Mono',monospace !important;
    font-size:9px !important; letter-spacing:2px !important; border-radius:4px !important;
}

/* ── CHAT INPUT ── */
[data-testid="stChatInput"] {
    position:fixed !important; bottom:0 !important; left:0 !important; right:0 !important;
    z-index:1000 !important; background:rgba(8,14,30,.98) !important;
    border-top:1px solid rgba(0,255,180,.2) !important;
    padding:12px 28px 16px !important; backdrop-filter:blur(12px) !important;
}
[data-testid="stChatInputTextArea"] {
    background:rgba(10,20,45,.9) !important; border:1px solid rgba(0,255,180,.35) !important;
    border-radius:10px !important; color:#ffffff !important; caret-color:#00ffb4 !important;
    font-family:'Space Mono',monospace !important; font-size:13px !important; padding:10px 14px !important;
}
[data-testid="stChatInputTextArea"]::placeholder { color:rgba(200,214,240,0.45) !important; }
[data-testid="stChatInputTextArea"]:focus { border-color:rgba(0,255,180,.55) !important; box-shadow:0 0 0 2px rgba(0,255,180,.12) !important; outline:none !important; }
[data-testid="stChatInputSubmitButton"] { color:#00ffb4 !important; }
[data-testid="stChatInputSubmitButton"] svg { fill:#00ffb4 !important; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  AUTH GATE
# ─────────────────────────────────────────────
if not st.session_state.authenticated:
    _, c1, mid, c2, _ = st.columns([0.8, 0.1, 2, 0.1, 0.8])
    with mid:
        st.markdown("<div style='height:22vh'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div style="text-align:center;margin-bottom:24px;">
          <div style="display:inline-flex;align-items:center;justify-content:center;
            width:52px;height:52px;border:2px solid #00ffb4;border-radius:12px;
            font-size:22px;margin-bottom:16px;box-shadow:0 0 20px rgba(0,255,180,.4);
            animation:glow 2.5s ease-in-out infinite;">⬡</div>
          <div style="font-family:'Syne',sans-serif;font-size:24px;font-weight:800;color:#fff;">NEXUS RESEARCH</div>
          <div style="font-size:9px;letter-spacing:3px;color:rgba(0,255,180,.55);text-transform:uppercase;margin-top:6px;">Restricted Access — Enter API Key</div>
        </div>""", unsafe_allow_html=True)

        key_input = st.text_input("API Key", type="password", placeholder="Enter your Nexus API key…", label_visibility="collapsed", key="key_field")
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        if st.button("⬡  AUTHENTICATE", use_container_width=True, key="auth_btn"):
            if key_input.strip():
                try:
                    resp = requests.post("http://127.0.0.1:8000/verify-key", headers={"X-Api-Key": key_input.strip()}, timeout=5)
                    if resp.status_code == 200:
                        st.session_state.api_key = key_input.strip()
                        st.session_state.authenticated = True
                        st.rerun()
                    else:
                        st.markdown('<div class="login-err">⚠ Invalid API key. Access denied.</div>', unsafe_allow_html=True)
                except Exception as e:
                    st.markdown(f'<div class="login-err">⚠ Cannot connect to server: {e}</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="login-err">⚠ Please enter your API key.</div>', unsafe_allow_html=True)
    st.stop()

# ─────────────────────────────────────────────
#  CHAT INPUT
# ─────────────────────────────────────────────
query = st.chat_input("Ask Nexus anything — science, news, research…")

# ─────────────────────────────────────────────
#  HEADER
# ─────────────────────────────────────────────
st.markdown("""
<div class="nx-header">
  <div class="nx-logo">⬡</div>
  <div>
    <div class="nx-title">NEXUS RESEARCH</div>
    <div class="nx-sub">Multi-Agent Intelligence Layer</div>
  </div>
  <div class="nx-badge">SYSTEM ONLINE</div>
</div>""", unsafe_allow_html=True)

logout_col1, logout_col2 = st.columns([6, 1])
with logout_col2:
    if st.button("⬡ LOGOUT", key="logout_btn", use_container_width=True):
        for k in ["authenticated", "api_key", "chat", "sources_all", "activity", "query_count", "tool_count"]:
            st.session_state[k] = False if k == "authenticated" else ("" if k == "api_key" else ([] if k in ["chat","sources_all","activity"] else 0))
        st.rerun()

# ─────────────────────────────────────────────
#  COLUMNS
# ─────────────────────────────────────────────
main_col, side_col = st.columns([3, 1], gap="small")

# ── SIDE PANEL ──
with side_col:
    src_html = ""
    if st.session_state.sources_all:
        items = "".join(
            f'<div class="source-card"><div class="source-num">SRC {i:02d}</div>'
            f'<a href="{lnk}" target="_blank" class="source-link">'
            f'{re.sub(r"https?://(www.)?","",lnk).split("/")[0]}</a></div>'
            for i, lnk in enumerate(st.session_state.sources_all[:12], 1)
        )
        src_html = f'<div class="side-title" style="margin-top:12px;">⬡ SOURCES</div>{items}'

    act_html = ""
    if st.session_state.activity:
        rows = "".join(
            f'<div class="activity-item"><span class="activity-time">{ts}</span><span>{lbl}</span></div>'
            for ts, lbl in reversed(st.session_state.activity[-8:])
        )
        act_html = f'<div class="side-title" style="margin-top:14px;">⬡ ACTIVITY</div>{rows}'

    st.markdown(f"""
    <div class="nx-side">
      <div class="side-title">⬡ SESSION</div>
      <div class="stat-row">
        <div class="stat-box"><div class="stat-num">{st.session_state.query_count}</div><div class="stat-lbl">Queries</div></div>
        <div class="stat-box"><div class="stat-num">{st.session_state.tool_count}</div><div class="stat-lbl">Tools</div></div>
        <div class="stat-box"><div class="stat-num">{len(st.session_state.sources_all)}</div><div class="stat-lbl">Sources</div></div>
      </div>
      {src_html}
      {act_html}
    </div>""", unsafe_allow_html=True)

# ── PANEL BUILDER ──
def build_panel(history, new_query="", live_html=""):
    if not history and not new_query:
        body = """
        <div class="empty-state">
          <div class="empty-hex">⬡</div>
          <div class="empty-text">Nexus is standing by</div>
          <div class="empty-sub">Ask anything — science, news, research</div>
        </div>"""
    else:
        body = "".join(
            f'<div class="msg-user">{msg}</div>' if role == "user"
            else f'<div class="msg-agent">{to_html(msg)}</div>'
            for role, msg in history
        )
        if new_query:
            body += f'<div class="msg-user">{new_query}</div>'
        if live_html:
            body += live_html
    return f'<div class="nx-panel" id="nx-chat">{body}</div>'

# ── MAIN PANEL ──
with main_col:
    panel_slot = st.empty()
    panel_slot.markdown(build_panel(st.session_state.chat), unsafe_allow_html=True)

# ── PDF DOWNLOAD BUTTON ──
if st.session_state.last_session_id:
    download_url = f"http://127.0.0.1:8000/download_pdf/{st.session_state.last_session_id}"

    col1, col2, col3 = st.columns([2, 1, 2])

    with col2:
        st.markdown(f"""
        <a href="{download_url}" target="_blank"
           style="
               display:block;
               text-align:center;
               padding:10px;
               border:1px solid rgba(0,255,180,0.4);
               border-radius:8px;
               color:#00ffb4;
               text-decoration:none;
               font-family:Space Mono;
               font-size:12px;
               letter-spacing:2px;
               background:rgba(0,255,180,0.08);
           ">
           ⬇ DOWNLOAD PDF
        </a>
        """, unsafe_allow_html=True)
# ─────────────────────────────────────────────
#  PROCESS QUERY
# ─────────────────────────────────────────────
if query:
    if st.session_state.last_session_id:
        st.session_state.last_session_id = None
    st.session_state.query_count += 1
    st.session_state.activity.append((now_stamp(), f"Query: {query[:38]}…" if len(query) > 38 else f"Query: {query}"))

    # ── Pipeline state trackers ──
    planner_html    = ""
    retrieval_steps = []
    retrieval_html  = ""
    synth_html      = ""
    critic_html     = ""
    writing_html    = ""
    streamed_answer = ""
    session_sources = []

    def update_panel(live_html):
        panel_slot.markdown(
            build_panel(st.session_state.chat, new_query=query, live_html=live_html),
            unsafe_allow_html=True
        )
        scroll_to_bottom()

    def refresh():
        """Rebuilds the full pipeline display and pushes to panel."""
        update_panel(build_pipeline_html(
            planner_html, retrieval_html, synth_html, critic_html, writing_html
        ))

    # Initial spinner
    update_panel('<div class="nx-thinking"><div class="th-label">⬡ INITIALIZING NEXUS PIPELINE <span class="dot-pulse"></span></div></div>')

    try:
        r = requests.post(
            "http://127.0.0.1:8000/ask_stream",
            json={"query": query},
            headers={"X-Api-Key": st.session_state.api_key},
            stream=True,
            timeout=180       # longer timeout for multi-agent pipeline
        )

        for line in r.iter_lines():
            if not line:
                continue
            try:
                event = json.loads(line.decode())
            except Exception:
                continue
            if "type" not in event:
                continue

            etype = event["type"]
            data  = event.get("data", {})

            # ── PLANNER ──
            if etype == "planner":
                tasks     = data.get("tasks", [])
                fmt       = data.get("format", "summary")
                reasoning = data.get("reasoning", "")
                st.session_state.tool_count += len(tasks)
                st.session_state.activity.append((now_stamp(), f"Planner: {len(tasks)} tasks → {fmt}"))
                planner_html   = build_planner_html(tasks, fmt, reasoning)
                retrieval_html = build_retrieval_html([])   # show empty retrieval block
                refresh()

            # ── RETRIEVAL ──
            elif etype == "retrieval":
                source = data.get("source", "?")
                retrieval_steps.append(data)
                # Collect URLs for source panel
                for url in data.get("urls", []):
                    if url not in session_sources:
                        session_sources.append(url)
                st.session_state.activity.append((now_stamp(), f"Retrieved: {source.upper()} (score {data.get('score',0):.2f})"))
                retrieval_html = build_retrieval_html(retrieval_steps)
                refresh()

            # ── SYNTHESIZER ──
            elif etype == "synthesizer":
                done = data.get("status") == "done"
                retrieval_html = build_retrieval_done_html(retrieval_steps)  # mark retrieval done
                synth_html     = build_synthesizer_html(done=done)
                st.session_state.activity.append((now_stamp(), "Synthesizer: merging sources"))
                refresh()

            # ── CRITIC ──
            elif etype == "critic":
                verdict  = data.get("verdict", "")
                feedback = data.get("feedback", "")
                loops    = data.get("loops", 0)
                synth_html  = build_synthesizer_html(done=True)
                critic_html = build_critic_html(verdict=verdict, feedback=feedback, loops=loops, done=True)
                st.session_state.activity.append((now_stamp(), f"Critic: {verdict} (loop {loops})"))
                if verdict == "RETRY":
                    # Reset retrieval for next loop
                    retrieval_steps.clear()
                    retrieval_html = build_retrieval_html([])
                refresh()

            # ── FINAL ANSWER ──
            elif etype == "answer":
                streamed_answer = data if isinstance(data, str) else str(data)
                writing_html = build_writing_html()
                st.session_state.activity.append((now_stamp(), "Report generator: writing"))
                refresh()

            elif etype == "meta":
                session_id = data.get("session_id")

                if session_id:
                    st.session_state.last_session_id = session_id
                    st.session_state.activity.append((now_stamp(), "PDF ready"))

        # ── Done — show final report ──
        update_panel(f'<div class="msg-agent">{to_html(streamed_answer)}</div>')


    except Exception as e:
        update_panel(
            build_panel(
                st.session_state.chat, new_query=query,
                live_html=f'<div class="msg-agent" style="border-color:rgba(239,68,68,.4);color:#fca5a5;">⚠ Pipeline error: {e}<br><span style="font-size:11px;opacity:.55">Make sure backend is running.</span></div>'
            )
        )
        streamed_answer = f"[Error: {e}]"

    # ── Persist to session ──
    st.session_state.chat.append(("user", query))
    st.session_state.chat.append(("assistant", streamed_answer))
    for url in session_sources:
        if url not in st.session_state.sources_all:
            st.session_state.sources_all.append(url)
    st.session_state.activity.append((now_stamp(), "✓ Response delivered"))
    st.rerun()