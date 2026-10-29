"""The draft-brain service: XMage's bot seats ask it for each draft pick and for their deck, over local HTTP.

    uv run --group brain python -m play.draft_brain.server [--port 17190]

  GET  /brains   {"brains": [{"name", "label"}], "default": name}
  POST /pick     {"set", "brain", "pack": [names], "pool": [names], "pack_number", "pick_number"}
                 -> {"pick": name or null, "scores": [score or null per pack card], "brain"}
                 null pick: keep XMage's own pick (the xmage brain, or a brain that knows none of the cards)
  POST /build    {"set", "pool": [names]} -> {"main": [names], "lands": {basic: n}, "colors", "sideboard": [names]}

Listens on 127.0.0.1 only. Brains load once at start (a few MB each, well under a second per pick).
"""
import argparse, json, logging, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .brains import BRAINS, DEFAULT
from .deckbuild import build

log = logging.getLogger("draft_brain")
LOADED = {}


def load():
    for name, cls in BRAINS.items():
        try:
            LOADED[name] = cls()
        except Exception as e:   # a brain whose weights are missing is left out, the others still serve
            log.warning("brain %s not loaded: %s", name, e)


def pick(body):
    set_code = str(body.get("set", "")).upper()
    name = body.get("brain") or DEFAULT
    brain = LOADED.get(name) or LOADED.get(DEFAULT)
    pack, pool = list(body.get("pack") or []), list(body.get("pool") or [])
    if brain is None or set_code not in brain.sets or not pack:
        return {"pick": None, "scores": None, "brain": name}
    scores = brain.scores(set_code, pack, pool, int(body.get("pack_number", 0)), int(body.get("pick_number", 0)))
    if not scores or all(s is None for s in scores):
        return {"pick": None, "scores": scores, "brain": brain.name}
    best = max(range(len(pack)), key=lambda i: scores[i] if scores[i] is not None else float("-inf"))
    return {"pick": pack[best], "scores": scores, "brain": brain.name}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/brains":
            return self._send(200, {"brains": [{"name": b.name, "label": b.label} for b in LOADED.values()], "default": DEFAULT})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        started = time.perf_counter()
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if self.path == "/pick":
                result = pick(body)
            elif self.path == "/build":
                result = build(str(body.get("set", "")).upper(), list(body.get("pool") or []))
            else:
                return self._send(404, {"error": "not found"})
        except Exception as e:
            log.exception("%s failed", self.path)
            return self._send(500, {"error": str(e)})
        log.info("%s %s %.1f ms", self.path, result.get("brain", ""), (time.perf_counter() - started) * 1000)
        self._send(200, result)

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=17190)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
    load()
    log.info("draft brains %s on 127.0.0.1:%d", ", ".join(LOADED), args.port)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
