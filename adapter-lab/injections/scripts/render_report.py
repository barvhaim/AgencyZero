#!/usr/bin/env python3
"""
Turn every Langfuse session export in a folder into one readable HTML report.

    python render_report.py [EXPORT_DIR]        # default /out

Reads   EXPORT_DIR/session-*.json   (written by export_session.py)
Writes  EXPORT_DIR/report.html

The report has an index of all sessions (one row each, with flags such as
"read an MCP note" or "tried pip install") and, per session, a readable
timeline: what you asked, what Hermes said, every tool call with its
arguments, and what each tool returned.

Everything from the traces is HTML-escaped: traces contain attacker-controlled
text (that is the point of the lab), so nothing from them is ever rendered as
markup.
"""

import glob
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

EXPORT_DIR = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("OUT_DIR", "/out")
OUT_FILE = os.path.join(EXPORT_DIR, "report.html")

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Asia/Jerusalem")
    TZ_LABEL = "Israel time"
except Exception:  # slim images may lack tzdata
    LOCAL_TZ = timezone.utc
    TZ_LABEL = "UTC"

INSTALL_RE = re.compile(r"\b(pip3?|python3?\s+-m\s+pip|uv\s+pip|npm|pnpm|yarn)\s+(install|add|i)\b", re.I)
BACKGROUND_PREFIXES = ("Review the conversation above",)
SHORT = 600  # characters shown before "show all"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def when(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ts


def as_text(value) -> str:
    """Readable text for a tool input/output or message."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        # Common shapes: {"result": ...}, {"output": ...}, {"command": ...}
        for key in ("result", "output", "content"):
            if key in value and len(value) <= 6:
                inner = value[key]
                return inner if isinstance(inner, str) else json.dumps(inner, ensure_ascii=False, indent=2)
    return json.dumps(value, ensure_ascii=False, indent=2)


def block(text: str, cls: str = "") -> str:
    """Pre-formatted text, collapsed if long."""
    text = text or ""
    if len(text) <= SHORT:
        return f'<pre class="{cls}">{esc(text)}</pre>'
    return (f'<details class="long"><summary><pre class="{cls}">{esc(text[:SHORT])}…</pre>'
            f'<span class="more">הצג הכול ({len(text):,} תווים)</span></summary>'
            f'<pre class="{cls}">{esc(text)}</pre></details>')


def user_message(trace: dict) -> str:
    for obs in trace["observations"]:
        if obs.get("type") == "CHAIN":
            inp = obs.get("input")
            if isinstance(inp, dict) and inp.get("role") == "user":
                return as_text(inp.get("content"))
    inp = trace.get("input")
    if isinstance(inp, dict):
        return as_text(inp.get("content"))
    return ""


def final_answer(trace: dict) -> str:
    for obs in trace["observations"]:
        if obs.get("type") == "CHAIN":
            out = obs.get("output")
            if isinstance(out, dict):
                return as_text(out.get("content"))
    return ""


def tool_name(obs: dict) -> str:
    return (obs.get("name") or "").replace("Tool: ", "")


def command_of(obs: dict) -> str:
    inp = obs.get("input")
    return inp.get("command", "") if isinstance(inp, dict) else ""


# ---------------------------------------------------------------------------
# Analysis per session
# ---------------------------------------------------------------------------
def analyse(session: dict) -> dict:
    traces = sorted(session["traces"], key=lambda t: t.get("startTime") or "")
    tools, installs, mcp = [], [], set()
    background = 0
    for t in traces:
        if user_message(t).startswith(BACKGROUND_PREFIXES):
            background += 1
        for obs in t["observations"]:
            if obs.get("type") != "TOOL":
                continue
            name = tool_name(obs)
            tools.append(name)
            if name.startswith("mcp__"):
                mcp.add(name.replace("mcp__lab__", ""))
            if name == "terminal" and INSTALL_RE.search(command_of(obs)):
                installs.append(command_of(obs))
    first_user = next((user_message(t) for t in traces
                       if user_message(t) and not user_message(t).startswith(BACKGROUND_PREFIXES)), "")
    return {
        "traces": traces,
        "start": traces[0].get("startTime") if traces else None,
        "turns": len(traces),
        "tool_count": len(tools),
        "mcp": sorted(mcp),
        "installs": installs,
        "background": background,
        "first_user": first_user,
    }


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def render_step(obs: dict) -> str:
    kind = obs.get("type")
    t = when(obs.get("startTime"))[11:]
    if kind == "GENERATION":
        out = obs.get("output") if isinstance(obs.get("output"), dict) else {}
        text = as_text(out.get("content"))
        calls = [c.get("name") or (c.get("function") or {}).get("name") for c in out.get("tool_calls") or []]
        if not text and not calls:
            return ""
        parts = [f'<div class="step think"><span class="t">{esc(t)}</span><b>המודל</b>']
        if text:
            parts.append(block(text, "say"))
        if calls:
            parts.append('<div class="wants">מבקש להפעיל: ' + ", ".join(f"<code>{esc(c)}</code>" for c in calls) + "</div>")
        parts.append("</div>")
        return "".join(parts)
    if kind == "TOOL":
        name = tool_name(obs)
        cmd = command_of(obs)
        danger = name == "terminal" and INSTALL_RE.search(cmd)
        cls = "tool mcp" if name.startswith("mcp__") else "tool"
        if danger:
            cls += " danger"
        arg_text = cmd if cmd else as_text(obs.get("input"))
        flag = '<span class="flag">ניסיון התקנה</span>' if danger else ""
        return (f'<div class="step {cls}"><span class="t">{esc(t)}</span>'
                f'<b>כלי: <code>{esc(name)}</code></b>{flag}'
                f'<div class="lbl">קלט</div>{block(arg_text, "in")}'
                f'<div class="lbl">מה חזר</div>{block(as_text(obs.get("output")), "out")}</div>')
    return ""


def render_session(sid: str, a: dict, source: str) -> str:
    rows = []
    for i, t in enumerate(a["traces"], 1):
        msg = user_message(t)
        bg = msg.startswith(BACKGROUND_PREFIXES)
        steps = "".join(render_step(o) for o in sorted(t["observations"], key=lambda o: o.get("startTime") or "")
                        if o.get("type") in ("GENERATION", "TOOL"))
        who = "Hermes ברקע (לא את)" if bg else "את"
        rows.append(
            f'<div class="turn{" bg" if bg else ""}">'
            f'<div class="turnhead">הודעה {i} · {esc(when(t.get("startTime")))}</div>'
            f'<div class="user"><b>{who}:</b>{block(msg, "msg")}</div>'
            f'<details class="steps"><summary>מה קרה בפנים ({sum(1 for o in t["observations"] if o.get("type") == "TOOL")} כלים)</summary>{steps}</details>'
            f'<div class="answer"><b>Hermes ענה:</b>{block(final_answer(t), "msg")}</div>'
            f"</div>")
    return (f'<section id="{esc(sid)}"><h2>Session {esc(sid[:20])}…</h2>'
            f'<p class="meta">התחיל {esc(when(a["start"]))} · {a["turns"]} הודעות · {a["tool_count"]} קריאות לכלים · קובץ: {esc(source)}</p>'
            + "".join(rows) + '<p><a href="#top">חזרה לרשימה ↑</a></p></section>')


CSS = """
:root{--bg:#fff;--fg:#1d1d1b;--mut:#6b6a66;--line:#e3e1da;--card:#f7f6f2;--mcp:#eeedfe;--mcpb:#7f77dd;--dang:#fcebeb;--dangb:#e24b4a;--acc:#185fa5}
@media (prefers-color-scheme:dark){:root{--bg:#1c1c1a;--fg:#ecebe6;--mut:#a3a19a;--line:#3a3935;--card:#262624;--mcp:#2a2750;--mcpb:#9f98ee;--dang:#4a1b1b;--dangb:#f09595;--acc:#85b7eb}}
body{background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,Segoe UI,Arial,sans-serif;margin:0 auto;max-width:1000px;padding:16px}
h1{font-size:22px;font-weight:500}h2{font-size:18px;font-weight:500;margin-top:40px;border-top:1px solid var(--line);padding-top:24px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:right;vertical-align:top}
th{color:var(--mut);font-weight:500}a{color:var(--acc)}code{font-family:Consolas,monospace;font-size:13px}
pre{white-space:pre-wrap;word-break:break-word;direction:ltr;text-align:left;font:13px/1.5 Consolas,monospace;margin:4px 0;background:var(--card);padding:8px;border-radius:6px}
.meta,.t,.lbl,.turnhead{color:var(--mut);font-size:13px}.t{float:left}
.turn{border:1px solid var(--line);border-radius:10px;padding:12px;margin:14px 0}.turn.bg{opacity:.75;border-style:dashed}
.step{border-right:3px solid var(--line);padding:6px 10px;margin:8px 0}.step.mcp{border-color:var(--mcpb);background:var(--mcp)}
.step.danger{border-color:var(--dangb);background:var(--dang)}.flag{background:var(--dangb);color:#fff;border-radius:4px;padding:0 6px;margin-right:8px;font-size:12px}
.badge{display:inline-block;border-radius:4px;padding:0 6px;font-size:12px;margin:1px}.b-mcp{background:var(--mcp)}.b-dang{background:var(--dang)}
details.steps>summary{cursor:pointer;color:var(--acc);margin:6px 0}details.long>summary{list-style:none;cursor:pointer}.more{color:var(--acc);font-size:12px}
.wants{font-size:13px;color:var(--mut)}
"""


def main() -> None:
    files = sorted(glob.glob(os.path.join(EXPORT_DIR, "session-*.json")))
    if not files:
        sys.exit(f"No session-*.json files in {EXPORT_DIR}. Run export first.")

    sessions = {}  # one entry per session id: keep the newest export
    for path in files:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        sid = data.get("session_id") or os.path.basename(path)
        if sid not in sessions or path > sessions[sid][1]:
            sessions[sid] = (data, path)

    analysed = {sid: analyse(d) for sid, (d, _) in sessions.items()}
    order = sorted(analysed, key=lambda s: analysed[s]["start"] or "", reverse=True)

    index = []
    for sid in order:
        a = analysed[sid]
        badges = "".join(f'<span class="badge b-mcp">{esc(m)}</span>' for m in a["mcp"])
        if a["installs"]:
            badges += f'<span class="badge b-dang">ניסיון התקנה ×{len(a["installs"])}</span>'
        index.append(
            f'<tr><td>{esc(when(a["start"]))}</td><td><a href="#{esc(sid)}">{esc(sid[:14])}…</a></td>'
            f'<td>{esc(a["first_user"][:90])}</td><td>{a["turns"]}</td><td>{a["tool_count"]}</td><td>{badges}</td></tr>')

    body = "".join(render_session(sid, analysed[sid], os.path.basename(sessions[sid][1])) for sid in order)
    page = f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AgencyZero sessions</title><style>{CSS}</style></head>
<body><h1 id="top">AgencyZero · כל ה-sessions</h1>
<p class="meta">{len(order)} sessions · נוצר {esc(datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M"))} · שעות לפי {TZ_LABEL} ·
סגול = כלי MCP של המעבדה · אדום = ניסיון להתקין חבילה</p>
<table><thead><tr><th>מתי</th><th>Session</th><th>ההודעה הראשונה</th><th>הודעות</th><th>כלים</th><th>סימונים</th></tr></thead>
<tbody>{"".join(index)}</tbody></table>{body}</body></html>"""

    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"Report: {len(order)} session(s) -> {os.path.basename(OUT_FILE)}")


if __name__ == "__main__":
    main()
