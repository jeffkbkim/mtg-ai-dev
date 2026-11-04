"""A seat played by a trained policy: the ONNX file play/export_policy.py writes, run with onnxruntime.

Every decision goes through the same encoder the training data went through (engine/encode.py), so the model sees
exactly what it saw in training:

    msg (one JSON line from PySeat) -> encode_decision -> collate([x]) -> onnxruntime -> logits (1, A) -> option

- greedy (temperature 0, the default): the highest-scoring legal option. temperature > 0 samples from
  softmax(logits / temperature) instead.
- A decision the encoder can't map (Unmapped: a DAMAGE split, a card or keyword outside the vocabulary) is never
  silently replaced: the seat picks a uniformly random legal option and records why ("fallback" in the info), so
  the game report can say how many decisions the model did not make.

    from policy_player import PolicyPlayer
    p = PolicyPlayer("data/policies/200-l1/policy.onnx", seed=0)
    choice, info = p.choose(msg)     # info: {"policy": {"p": 0.93, "n": 4}} or {"policy": {"fallback": "..."}}
"""
import json
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.encode import Unmapped, Vocab, collate, encode_decision  # noqa: E402


class PolicyPlayer:
    def __init__(self, onnx_path, seed=0, temperature=0.0, name=None):
        import onnxruntime
        onnx_path = Path(onnx_path)
        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads = 1  # a 30k-parameter model: one thread is fastest and leaves cores for the JVM
        opts.inter_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(str(onnx_path), opts, providers=["CPUExecutionProvider"])
        self.inputs = [i.name for i in self.session.get_inputs()]  # only what the exported forward reads
        meta_path = onnx_path.with_suffix(".json")
        self.meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        self.vocab = Vocab.load()
        self.rng = random.Random(seed)
        self.temperature = temperature
        self.name = name or f"policy:{self.meta.get('name', onnx_path.stem)}"
        self.fallbacks = Counter()  # reason -> count, over the whole run
        self.decisions = 0

    def start_game(self, game, deck_path):
        pass

    def end_game(self, result):
        pass

    def logits(self, msg) -> np.ndarray:
        """(A,) scores of the legal options, in option order. Raises Unmapped like the dataset builder does."""
        x = encode_decision({**msg, "choice": 0}, self.vocab)
        batch = collate([x])
        feed = {k: batch[k].numpy() for k in self.inputs}
        return self.session.run(None, feed)[0][0]

    def choose(self, msg):
        self.decisions += 1
        n = len(msg["options"])
        try:
            z = self.logits(msg).astype(np.float64)
        except Unmapped as err:
            reason = str(err)[:120]
            self.fallbacks[reason] += 1
            return self.rng.randrange(n), {"policy": {"fallback": reason, "n": n}}
        if len(z) != n:
            raise RuntimeError(f"model returned {len(z)} scores for {n} options")
        p = np.exp(z - z.max())
        p /= p.sum()
        if self.temperature > 0:
            q = np.exp((z - z.max()) / self.temperature)
            q /= q.sum()
            choice = int(self.rng.choices(range(n), weights=q)[0])
        else:
            choice = int(np.argmax(z))
        return choice, {"policy": {"p": round(float(p[choice]), 4), "n": n}}
