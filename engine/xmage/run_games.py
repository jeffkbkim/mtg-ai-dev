"""Spike: random-move bot. Listens on a port, starts the JVM, answers every decision with a random option."""
import json, random, socket, subprocess, sys, time, collections
from pathlib import Path

runtime, classes, py_deck, ai_deck = sys.argv[1:5]
games = sys.argv[5] if len(sys.argv) > 5 else "1"
seed = int(sys.argv[6]) if len(sys.argv) > 6 else 0
log_path = Path(sys.argv[7]) if len(sys.argv) > 7 else Path("decisions.jsonl")
rng = random.Random(seed)

srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
port = srv.getsockname()[1]
jars = sorted(str(p) for p in Path(runtime).rglob("*.jar"))
cp = ":".join([classes] + jars)
extra = ["-Dspike.leaktest=true"] if __import__("os").environ.get("LEAKTEST") else []
jvm = subprocess.Popen(["java", *extra, "-Xmx3g", "-Djava.awt.headless=true", "--add-opens=java.base/java.lang=ALL-UNNAMED",
                        "-cp", cp, "SeatSpike", str(port), py_deck, ai_deck, games],
                       cwd=runtime, stdout=open(log_path.with_suffix(".jvm.log"), "w"), stderr=subprocess.STDOUT)
conn, _ = srv.accept()
conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
f = conn.makefile("rw")
kinds = collections.Counter(); options_seen = collections.Counter(); leaks = collections.Counter()
python_seconds = 0.0
with log_path.open("w") as log:
    for line in f:
        t0 = time.perf_counter()
        msg = json.loads(line)
        if msg["type"] == "end":
            break
        n = len(msg["options"])
        # biased random: when there is something other than PASS/DONE (option 0), take it 80% of the time,
        # so a game exercises more decision types than pure random would
        if n > 1 and msg["options"][0]["label"] in ("PASS", "DONE") and rng.random() < 0.8:
            choice = rng.randrange(1, n)
        else:
            choice = rng.randrange(n)
        kinds[msg["kind"]] += 1
        for l in msg.get("leaks", []): leaks[l] += 1
        options_seen[n] += 1
        log.write(json.dumps({**msg, "choice": choice}) + "\n")
        f.write(json.dumps({"choice": choice}) + "\n"); f.flush()
        python_seconds += time.perf_counter() - t0
rc = jvm.wait(timeout=600)
print("jvm exit", rc)
print("decisions by kind", dict(kinds))
print("python time per decision ms", round(1000 * python_seconds / max(1, sum(kinds.values())), 3))
print("leaks seen by python", dict(leaks))
print("option count histogram", dict(sorted(options_seen.items())))
