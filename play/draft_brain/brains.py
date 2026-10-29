"""Draft brains: what a bot seat picks from a pack, given the cards it already has.

Every brain answers one question, `scores(set_code, pack, pool, pack_number, pick_number)`, with a score per card in
the pack (higher is better; None for a card the brain doesn't know). The bot picks the best-scored card. Names are
card names as XMage prints them (a Room is "Left // Right"); pack_number and pick_number count from 0.

Brains here:
  statdraft  statistical-drafting (github.com/danieljbrooks/statistical-drafting, MIT): an MLP per set trained on
             17lands Premier Draft picks; looks at the pool, not the pick number.
  draftfm    DraftFM (github.com/brianward92/mtga, Apache-2.0): one model for every set, scoring cards from their
             features; looks at the pool and the pack and pick number.
  gih        our 17lands train-split numbers (seventeenlands/card_ratings.py): the card's games-in-hand win rate,
             then from pick 6 on a bonus for the pool's two main colours.
  xmage      XMage's own bot (its card ratings); the server keeps its built-in pick, this brain only names it.

Your own model plugs in the same way: a class with `name` and `scores(...)`, registered in BRAINS (see README.md).
Weights and data live outside Git, under ~/mtg-data/draft-brains and ~/mtg-data/17lands/ratings.
"""
import csv, json, re
from pathlib import Path

import numpy as np

HOME = Path.home()
WEIGHTS = HOME / "mtg-data/draft-brains"
RATINGS = HOME / "mtg-data/17lands/ratings"
REPO = Path(__file__).resolve().parent.parent.parent
COLORS = "WUBRG"


def card_info(set_code):
    """name -> {colors, mana_value, types, rarity} from our card text (engine/vocab/<set>_card_text.json)."""
    out = {}
    for card in json.loads((REPO / f"engine/vocab/{set_code.lower()}_card_text.json").read_text()):
        colors = "".join(c for c in COLORS if "{" + c in card.get("cost", "") or f"/{c}" in card.get("cost", ""))
        out[card["name"]] = {"colors": colors, "cost": card.get("cost", ""), "mana_value": card.get("mana_value", 0), "types": card.get("types", ""),
                             "rarity": card.get("rarity", "")}
    return out


class Brain:
    name = "?"
    label = "?"
    sets = ("DSK", "FDN")

    def scores(self, set_code, pack, pool, pack_number, pick_number):
        raise NotImplementedError


class XMageBrain(Brain):
    name, label = "xmage", "XMage ratings"

    def scores(self, set_code, pack, pool, pack_number, pick_number):
        return None   # the server keeps XMage's own pick


class StatDraftBrain(Brain):
    name, label = "statdraft", "statistical-drafting"

    def __init__(self):
        import onnxruntime
        self.models = {}
        for set_code in self.sets:
            with open(WEIGHTS / f"statdraft/{set_code}.csv") as f:
                names = [row["name"] for row in csv.DictReader(f)]
            session = onnxruntime.InferenceSession(str(WEIGHTS / f"statdraft/{set_code}_Premier.onnx"), providers=["CPUExecutionProvider"])
            self.models[set_code] = (session, {n: i for i, n in enumerate(names)}, len(names))

    def scores(self, set_code, pack, pool, pack_number, pick_number):
        session, index, size = self.models[set_code]
        collection = np.zeros((1, size), np.float32)
        for name in pool:
            if name in index:
                collection[0, index[name]] += 1
        mask = np.zeros((1, size), np.float32)
        for name in pack:
            if name in index:
                mask[0, index[name]] = 1
        out = session.run(None, {"collection": collection, "pack": mask})[0][0]
        return [float(out[index[n]]) if n in index else None for n in pack]


class DraftFMBrain(Brain):
    name, label = "draftfm", "DraftFM"
    POOL_COUNT_CAP = 8

    def __init__(self):
        import onnxruntime
        root = WEIGHTS / "draftfm"
        meta = json.loads((root / "model/meta.json").read_text())
        providers = ["CPUExecutionProvider"]
        encoder = onnxruntime.InferenceSession(str(root / "model/card_encoder.onnx"), providers=providers)
        self.scorer = onnxruntime.InferenceSession(str(root / "model/scorer.onnx"), providers=providers)
        self.null_pool = np.load(root / "model/constants.npz")["pool_null_input"].astype(np.float32)
        self.wr_id, self.games_id = int(meta["serving"]["wr_id"]), int(meta["serving"]["games_id"])
        self.sets_ = {}
        for set_code in self.sets:
            with np.load(root / f"sets/{set_code}/assets.npz") as z:
                if str(z["manifest_hash"]) != meta.get("manifest_hash", str(z["manifest_hash"])):
                    raise ValueError(f"DraftFM assets for {set_code} don't match the model")
                features = z["features"].astype(np.float32)[:, : meta.get("feat_dim") or None]
                names = [str(n) for n in z["names"]]
                ppp = int(z["picks_per_pack"]) or 14
            table = encoder.run(["card_emb"], {"features": features})[0]
            scalars = np.array([[len(names) / 400.0, float(ppp == 13), float(ppp == 14), float(ppp == 15)]], np.float32)
            self.sets_[set_code] = (table, {n: i for i, n in enumerate(names)}, ppp, scalars)

    def scores(self, set_code, pack, pool, pack_number, pick_number):
        table, index, ppp, scalars = self.sets_[set_code]
        rows = [index.get(n) for n in pack]
        known = sorted({r for r in rows if r is not None})
        if not known:
            return [None] * len(pack)
        pool_rows = [index[n] for n in pool if n in index]
        if pool_rows:
            uniq, counts = np.unique(np.asarray(pool_rows), return_counts=True)
            pool_emb, pool_counts = table[uniq][None], np.minimum(counts, self.POOL_COUNT_CAP)[None].astype(np.int64)
            pool_mask = np.zeros((1, len(uniq)), bool)
        else:
            pool_emb, pool_counts, pool_mask = self.null_pool[None, None], np.zeros((1, 1), np.int64), np.zeros((1, 1), bool)
        size = pack_number * ppp + pick_number
        position = np.array([[float(pack_number == 0), float(pack_number == 1), float(pack_number == 2), pick_number / ppp,
                              max(ppp - 1 - pick_number, 0) / ppp, size / 45.0, min(size / (3 * ppp), 1.0)]], np.float32)
        feed = {"pool_emb": pool_emb, "pool_counts": pool_counts, "pool_mask": pool_mask, "pack_emb": table[known][None],
                "pack_mask": np.zeros((1, len(known)), bool), "wr_id": np.array([self.wr_id], np.int64),
                "games_id": np.array([self.games_id], np.int64), "format_id": np.array([0], np.int64),  # Premier Draft
                "position": position, "set_scalars": scalars}
        logits = self.scorer.run(["logits"], feed)[0][0]
        by_row = dict(zip(known, logits))
        return [None if r is None else float(by_row[r]) for r in rows]


class GihBrain(Brain):
    name, label = "gih", "17lands GIH WR"
    COMMIT_FROM = 5        # picks before this take the best card; later ones lean into the pool's colours
    COLOR_BONUS = 0.04     # win-rate points for a card in the pool's two main colours (or colourless)

    def __init__(self):
        self.ratings = {s: json.loads((RATINGS / f"{s.lower()}_card_gih.json").read_text()) for s in self.sets}
        self.info = {s: card_info(s) for s in self.sets}

    def gih(self, set_code, name):
        rating = self.ratings[set_code].get(name)
        return rating["gih_wr"] if rating and rating["gih_wr"] and rating["gih_games"] >= 200 else None

    def main_colors(self, set_code, pool):
        weight = dict.fromkeys(COLORS, 0.0)
        for name in pool:
            wr = self.gih(set_code, name) or 0.5
            for c in self.info[set_code].get(name, {}).get("colors", ""):
                weight[c] += max(wr - 0.5, 0) + 0.01
        return "".join(sorted(COLORS, key=lambda c: -weight[c])[:2])

    def scores(self, set_code, pack, pool, pack_number, pick_number):
        commit = len(pool) >= self.COMMIT_FROM
        main = self.main_colors(set_code, pool) if commit else ""
        out = []
        for name in pack:
            wr = self.gih(set_code, name)
            if wr is None:
                out.append(None)
                continue
            colors = self.info[set_code].get(name, {}).get("colors", "")
            if commit and all(c in main for c in colors):
                wr += self.COLOR_BONUS
            out.append(wr)
        return out


BRAINS = {b.name: b for b in (XMageBrain, StatDraftBrain, DraftFMBrain, GihBrain)}
DEFAULT = "statdraft"
