#!/usr/bin/env python3
"""Render the SysML v2 model to SVG with the OMG pilot (%viz) and write a preview page.

    ./render.py              # src/model -> diagrams/*.svg + diagrams/index.html
    ./render.py src/inny     # another model folder

Needs the pilot (docker compose --profile pilot up -d sysml-pilot) and `pip install websocket-client`.
PILOT_URL (default http://localhost:8890, from the devcontainer http://host.docker.internal:8890),
PILOT_TOKEN (default sysml).
"""
import glob
import html
import json
import os
import re
import sys
import urllib.request
import uuid

import websocket

HERE = os.path.dirname(os.path.abspath(__file__))
URL = os.environ.get("PILOT_URL", "http://localhost:8890").rstrip("/")
TOKEN = os.environ.get("PILOT_TOKEN", "sysml")

# (file name, title, %viz view, element, extra styles)
# POLYLINE: straight segments, labels stay in place (ORTHOLINE detaches labels and arrow ends). LR: ports spread out on IBDs.
DIAGRAMS = [
    ("01_proces", "Proces biznesowy", "action", "ProcesElicytacji::ProcesBiznesowy", ["POLYLINE"]),
    ("02_sekwencja", "Sekwencja sesji elicytacji", "sequence", "SekwencjaElicytacji::SesjaElicytacji", []),
    ("03_stany_przydzialu", "Stany przydziału", "state", "StanyElicytacji::AssignmentLifecycle", ["POLYLINE"]),
    ("04_stany_zadania", "Stany zadania workera", "state", "StanyElicytacji::JobLifecycle", ["POLYLINE"]),
    ("05_kontekst", "Kontekst kliniki (IBD)", "interconnection", "KontekstElicytacji::kontekstKliniki", ["LR"]),
    ("06_wnetrze_systemu", "Wnętrze systemu (IBD)", "interconnection", "StrukturaElicytacji::SystemElicytacji", ["LR"]),
    ("07_model_danych", "Model danych (BDD)", "tree", "StrukturaElicytacji::Data", ["LR"]),
    ("08a_struktura_systemu", "Struktura systemu (BDD)", "tree", "StrukturaElicytacji::SystemElicytacji", ["LR"]),
    ("08b_struktura_api", "Struktura API (BDD)", "tree", "StrukturaElicytacji::BackendApi", ["LR"]),
    ("08c_struktura_workera", "Struktura workera (BDD)", "tree", "StrukturaElicytacji::Worker", ["LR"]),
]


SATISFY = ("08_spelnianie", "Wymagania i ich spełnianie (satisfy)")


def satisfy_section(raw):
    """HTML table of `satisfy` (requirement -> element) read from the model text.

    The pilot's %viz draws no satisfy relations (and exceeds its 1000-element limit on the Spelnianie
    package), so this view is a table here; SysON draws it as the `spelnianieWymagan` view.
    """
    reqs = {}
    for m in re.finditer(r"requirement\s*<'([^']+)'>\s*(\w+)[^{]*\{\s*doc\s*/\*(.*?)\*/", raw, flags=re.S):
        reqs[m.group(2)] = (m.group(1), re.sub(r"\s*\n\s*\*?\s*", " ", m.group(3)).strip())
    by = {}
    for req, target in re.findall(r"^\s*satisfy\s+(\w+)\s+by\s+([\w.]+);", raw, flags=re.M):
        by.setdefault(re.sub(r"^kontekstKliniki\.(hosting\.)?(system\.)?", "", target), []).append(req)
    body = []
    for target, rs in sorted(by.items()):
        for i, r in enumerate(sorted(rs, key=lambda n: reqs.get(n, ("~", ""))[0])):
            rid, text = reqs.get(r, ("?", r))
            first = f"<td rowspan='{len(rs)}'><b>{html.escape(target)}</b></td>" if i == 0 else ""
            body.append(f"<tr>{first}<td>{html.escape(rid)}</td><td>{html.escape(r)}</td><td>{html.escape(text)}</td></tr>")
    done = {r for rs in by.values() for r in rs}
    missing = ", ".join(f"{html.escape(i)} {html.escape(n)}" for n, (i, _) in sorted(reqs.items(), key=lambda x: x[1][0]) if n not in done)
    return (f'<section id="{SATISFY[0]}"><h2>{html.escape(SATISFY[1])}<small> (tabela: pilot nie rysuje satisfy)</small></h2>'
            f'<table><tr><th>Element systemu (satisfy by)</th><th>Id</th><th>Wymaganie</th><th>Treść</th></tr>{"".join(body)}</table>'
            f'<p>Bez <code>satisfy</code> ({len(reqs) - len(done)} z {len(reqs)}): {missing}</p></section>')


def api(method, path):
    req = urllib.request.Request(URL + path, method=method, headers={"Authorization": "token " + TOKEN})
    if method == "POST":
        req.data = json.dumps({"name": "sysml"}).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
    return json.loads(body) if body else None


def execute(ws, code):
    """Run one cell; return (text, svg, errors)."""
    mid = uuid.uuid4().hex
    ws.send(json.dumps({
        "header": {"msg_id": mid, "msg_type": "execute_request", "username": "render",
                   "session": "render", "version": "5.3"},
        "parent_header": {}, "metadata": {}, "channel": "shell",
        "content": {"code": code, "silent": False, "store_history": False,
                    "user_expressions": {}, "allow_stdin": False},
    }))
    text, svg, errors = [], [], []
    while True:
        m = json.loads(ws.recv())
        if m.get("parent_header", {}).get("msg_id") != mid:
            continue
        t, c = m["msg_type"], m["content"]
        if t == "stream":
            text.append(c["text"])
        elif t in ("execute_result", "display_data"):
            text.append(c["data"].get("text/plain", ""))
            svg.append(c["data"].get("image/svg+xml", ""))
        elif t == "error":
            errors.append(c.get("evalue", ""))
        elif t == "status" and c["execution_state"] == "idle":
            return "".join(text), "".join(svg), errors


def main():
    src = os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else "src/model")
    out = os.path.join(HERE, "diagrams")
    os.makedirs(out, exist_ok=True)

    raw = "\n".join(open(f, encoding="utf-8").read() for f in sorted(glob.glob(os.path.join(src, "*.sysml"))))
    # Docs become notes on every diagram; strip them for rendering only (the model files stay as they are).
    model = re.sub(r"\bdoc\s*/\*.*?\*/", "", raw, flags=re.S)

    kernel = api("POST", "/api/kernels")
    ws_url = re.sub(r"^http", "ws", URL) + f"/api/kernels/{kernel['id']}/channels"
    ws = websocket.create_connection(ws_url, header=["Authorization: token " + TOKEN], timeout=600)
    try:
        text, _, errors = execute(ws, model)
        problems = [l for l in text.splitlines() if l.startswith(("ERROR", "WARNING"))]
        warnings = sum(l.startswith("WARNING") for l in problems)
        if errors or any(l.startswith("ERROR") for l in problems):
            print("Model has errors, nothing rendered:", *errors, *[l for l in problems if l.startswith("ERROR")], sep="\n  ")
            sys.exit(1)
        print(f"model ok ({warnings} warnings)")

        cards = []
        for name, title, view, element, styles in DIAGRAMS:
            _, svg, errors = execute(ws, f"%viz --view={view} " + " ".join(f"--style={x}" for x in ["HIDEMETADATA", *styles]) + f" {element}")
            if not svg:
                print(f"  {name}: no diagram", *errors)
                continue
            open(os.path.join(out, name + ".svg"), "w", encoding="utf-8").write(svg)
            note = " (pilot: limit 1000 elementów, może być niepełny)" if "EXCEEDS THE LIMIT" in svg else ""
            print(f"  {name}.svg{note}")
            cards.append(f'<section id="{name}"><h2>{html.escape(title)}<small>{note}</small></h2>'
                         f'<a href="{name}.svg"><img src="{name}.svg" alt="{html.escape(title)}"></a></section>')
        cards.append(satisfy_section(raw))
        print("  08_spelnianie (tabela)")
    finally:
        ws.close()
        api("DELETE", f"/api/kernels/{kernel['id']}")

    nav = " · ".join(f'<a href="#{n}">{html.escape(t)}</a>' for n, t, *_ in [*DIAGRAMS, SATISFY])
    page = f"""<!doctype html><html lang="pl"><head><meta charset="utf-8"><title>Diagramy SysML</title>
<style>body{{font-family:sans-serif;margin:16px;background:#fff;color:#222}}nav{{margin-bottom:16px}}
section{{margin-bottom:40px}}h2 small{{font-weight:normal;color:#a60;font-size:60%;margin-left:8px}}
img{{max-width:100%;border:1px solid #ddd}}
table{{border-collapse:collapse;font-size:14px}}td,th{{border:1px solid #ccc;padding:4px 8px;vertical-align:top;text-align:left}}</style></head><body>
<h1>Diagramy SysML (pilot OMG)</h1><nav>{nav}</nav>{''.join(cards)}</body></html>"""
    open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(page)
    print("preview:", os.path.join(out, "index.html"))


if __name__ == "__main__":
    main()
