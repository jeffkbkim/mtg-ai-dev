"""Compile and run the DSK rules smoke test against an extracted XMage runtime.

This starts built-in bots, not a Python learned policy. All runtime state and
logs go to the supplied external runtime/output directories.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).resolve().parent
    jars = sorted(runtime.rglob("*.jar"))
    if not jars:
        raise SystemExit("No runtime jars found")
    classpath = os.pathsep.join(map(str, jars))
    decks = [here / "dsk_ug.dck", here / "dsk_uw.dck"]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="mtg-smoke-") as classes:
        subprocess.run(["javac", "-cp", classpath, "-d", classes,
                        str(here / "DskSmoke.java")], check=True, timeout=60)
        command = ["/usr/bin/time", "-l", "java", "-Xms256m", "-Xmx3g",
                   "-Djava.awt.headless=true", "--add-opens=java.base/java.lang=ALL-UNNAMED",
                   "-cp", classes + os.pathsep + classpath, "DskSmoke", *map(str, decks)]
        with (output / "run.log").open("w") as log:
            proc = subprocess.Popen(command, cwd=runtime, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            try:
                rc = proc.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                import signal
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=10)
                rc = 124
    lines = (output / "run.log").read_text().splitlines()
    results = [s for s in lines if s.startswith(("RESULT ", "BOOT_SECONDS ", "DECK_OK "))]
    report = {"returncode": rc, "elapsed_seconds": round(time.monotonic()-started, 3),
              "runtime": str(runtime), "results": results,
              "deck_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in decks},
              "resource_usage": [s.strip() for s in lines if "maximum resident set size" in s]}
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
