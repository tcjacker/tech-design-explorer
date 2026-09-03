#!/usr/bin/env python3
"""Serve an explorer locally and let Claude Code or Codex answer questions in it.

The published-artifact path uses the `sample` capability. On your own machine
there is no such runtime, but there *is* an agent CLI already installed — so this
serves the page over localhost and forwards each question, with the design
document as context, to `claude -p` or `codex exec`.

    python3 ask_server.py design-explorer.html                 # auto-detect an agent
    python3 ask_server.py design-explorer.html --agent codex
    python3 ask_server.py design-explorer.html --cmd "ollama run llama3"

The page finds the bridge on its own (`GET __tde/health`) and switches the Ask
panel from "offline" to the agent's name. Binds to 127.0.0.1 only; the answer is
whatever the agent writes to stdout.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Optional

AGENTS = {
    # every one of these reads the prompt on stdin and prints the answer on stdout
    "claude": ["claude", "-p"],
    "codex": ["codex", "exec", "-"],
}

MAX_PROMPT = 400_000


def detect_agent(preferred: str = "") -> Optional[str]:
    order = [preferred] if preferred else list(AGENTS)
    for name in order:
        if name in AGENTS and shutil.which(AGENTS[name][0]):
            return name
    return None


class Bridge:
    def __init__(self, argv: List[str], label: str, timeout: int) -> None:
        self.argv = argv
        self.label = label
        self.timeout = timeout
        self.lock = threading.Lock()

    def ask(self, prompt: str) -> str:
        prompt = prompt[:MAX_PROMPT]
        with self.lock:                      # one question at a time; agents are stateful
            try:
                proc = subprocess.run(self.argv, input=prompt, capture_output=True,
                                      text=True, timeout=self.timeout)
            except FileNotFoundError:
                return f"`{self.argv[0]}` is not installed on this machine."
            except subprocess.TimeoutExpired:
                return f"{self.label} did not answer within {self.timeout}s."
        out = (proc.stdout or "").strip()
        if out:
            return out
        err = (proc.stderr or "").strip()
        return f"{self.label} returned nothing (exit {proc.returncode}).\n{err[:600]}"


def make_handler(root: Path, page: str, bridge: Optional[Bridge]):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, fmt, *args):        # one line per question, not per asset
            if "__tde/ask" in (args[0] if args else ""):
                sys.stderr.write("  question received\n")

        def _json(self, code: int, payload) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):                          # noqa: N802
            if self.path.rstrip("/").endswith("__tde/health"):
                return self._json(200, {"agent": bridge.label if bridge else None,
                                        "page": page})
            if self.path in ("/", ""):
                self.path = "/" + page
            return super().do_GET()

        def do_POST(self):                         # noqa: N802
            if not self.path.rstrip("/").endswith("__tde/ask"):
                return self._json(404, {"error": "not found"})
            if not bridge:
                return self._json(503, {"error": "no agent is configured on this server"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, TypeError):
                return self._json(400, {"error": "bad request"})
            prompt = data.get("prompt") or data.get("question") or ""
            if not prompt.strip():
                return self._json(400, {"error": "empty question"})
            return self._json(200, {"answer": bridge.ask(prompt), "agent": bridge.label})

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("page", help="the rendered design-explorer.html")
    ap.add_argument("--agent", choices=sorted(AGENTS), default="",
                    help="which CLI answers questions (default: whichever is installed)")
    ap.add_argument("--cmd", default="", help="an arbitrary command that reads a prompt on stdin")
    ap.add_argument("--port", type=int, default=7654)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--open", action="store_true", help="open a browser window")
    args = ap.parse_args()

    page = Path(args.page).resolve()
    if not page.is_file():
        print(f"no such page: {page}", file=sys.stderr)
        return 2

    if args.cmd:
        bridge = Bridge(shlex.split(args.cmd), Path(shlex.split(args.cmd)[0]).name, args.timeout)
    else:
        name = detect_agent(args.agent)
        bridge = Bridge(AGENTS[name], name, args.timeout) if name else None

    handler = make_handler(page.parent, page.name, bridge)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"serving {page.name} at {url}")
    if bridge:
        print(f"  Ask panel answers via: {' '.join(bridge.argv)}")
    else:
        print("  no agent CLI found (claude / codex) — the Ask panel stays in copy-prompt mode")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
