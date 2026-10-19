"""Readable transcript of one recorded game for review: both seats, each decision with what that seat saw
(state only when it changed since the seat's previous decision), the options, the pick and the reason.

  python3 play/transcript.py <run>/game<N>.jsonl > transcript.txt
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import clean, render

last = {}
for line in open(sys.argv[1]):
    try:
        r = json.loads(line)
    except json.JSONDecodeError:
        print("[unreadable record]"); continue
    text = render(r)
    state, _, decision = text.partition("\nDecision: ")
    g = r["obs"]["entries"][0]
    print(f"=== seat {r['seat']} #{r['idx']} | turn {g['turn']} {g['step']} | life me {g['my_life']} opp {g['opp_life']}")
    print(state if last.get(r["seat"]) != state else "(state unchanged)")
    last[r["seat"]] = state
    print("Decision: " + decision)
    print(f">>> picked {r['choice']}: {clean(r['options'][r['choice']]['label'])}  | reason: {r.get('reason', '')}\n")
