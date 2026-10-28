"""17lands Premier Draft data of one set (DSK by default, MTG_SET=FDN for Foundations): convert to Parquet, audit it, and freeze a train/validation/test split by draft.

    uv run --group data python seventeenlands/prepare.py convert   # csv.gz -> parquet (once)
    uv run --group data python seventeenlands/prepare.py audit     # writes audit.json and prints a summary
    uv run --group data python seventeenlands/prepare.py split     # writes splits.parquet (draft_id -> split)

Data lives outside Git, in ~/mtg-data/17lands/<SET> (see scripts/download_17lands.sh). Card names are checked
against XMage's list for the set (engine/vocab/<set>_card_text.json); cards XMage lacks are listed, never replaced.
"""
import gzip, hashlib, json, os, re, shutil, sys, tempfile
from pathlib import Path

import polars as pl

SET = os.environ.get("MTG_SET", "DSK").upper()
DATA = Path.home() / f"mtg-data/17lands/{SET}"
REPO = Path(__file__).resolve().parent.parent
FILES = {k: f"{k}_public.{SET}.PremierDraft.csv.gz" for k in ("game_data", "draft_data", "replay_data")}
# card-count columns are small integers; replay turn columns hold "|"-joined 17lands card ids
COUNT_PREFIXES = ("deck_", "sideboard_", "opening_hand_", "drawn_", "tutored_", "pack_card_", "pool_")
GAME_KEY = ["draft_id", "build_index", "match_number", "game_number"]
SPLIT_SALT = f"mtg-ai-{SET.lower()}-split-v1"  # changing this reshuffles every draft: bump the version instead


def header(path):
    with gzip.open(path, "rt") as f:
        return f.readline().rstrip("\n").split(",")


def schema_for(kind, cols):
    s = {}
    for c in cols:
        if c.startswith(COUNT_PREFIXES) and kind != "replay_data" or c.startswith(("deck_", "sideboard_")):
            s[c] = pl.UInt8
        elif kind == "replay_data" and (c.startswith(("user_turn_", "oppo_turn_", "candidate_hand_")) or c == "opening_hand"):
            s[c] = pl.String
    return s


def convert():
    out = DATA / "parquet"; out.mkdir(exist_ok=True)
    for kind, name in FILES.items():
        dst = out / f"{kind}.parquet"
        if dst.exists():
            print("exists", dst); continue
        cols = header(DATA / name)
        with tempfile.TemporaryDirectory(dir=DATA) as tmp:
            csv = Path(tmp) / "data.csv"
            with gzip.open(DATA / name, "rb") as src, open(csv, "wb") as d:
                shutil.copyfileobj(src, d, 1 << 24)
            lf = pl.scan_csv(csv, schema_overrides=schema_for(kind, cols), infer_schema_length=20000)
            lf.sink_parquet(dst, compression="zstd")
        print("wrote", dst, round(dst.stat().st_size / 1e6), "MB")


def card_names(cols, prefix):
    return [c[len(prefix):] for c in cols if c.startswith(prefix)]


def audit():
    p = DATA / "parquet"
    xmage = {c["name"] for c in json.loads((REPO / f"engine/vocab/{SET.lower()}_card_text.json").read_text())}
    report = {}
    games = pl.scan_parquet(p / "game_data.parquet")
    replays = pl.scan_parquet(p / "replay_data.parquet")
    drafts = pl.scan_parquet(p / "draft_data.parquet")
    gcols = games.collect_schema().names()
    meta = [c for c in gcols if not c.startswith(COUNT_PREFIXES)]
    for kind, lf, key in (("game_data", games, GAME_KEY), ("replay_data", replays, GAME_KEY),
                          ("draft_data", drafts, ["draft_id", "pack_number", "pick_number"])):
        cols = lf.collect_schema().names()
        meta_cols = [c for c in cols if not c.startswith(COUNT_PREFIXES) and not re.match(r"(user|oppo)_turn_\d+_", c)]
        s = lf.select(
            pl.len().alias("rows"),
            pl.col("draft_id").n_unique().alias("drafts"),
            pl.col("draft_time").min().alias("first"), pl.col("draft_time").max().alias("last"),
            pl.struct(key).is_duplicated().sum().alias("duplicate_key_rows"),
            *[pl.col(c).null_count().alias(f"null:{c}") for c in meta_cols],
        ).collect().row(0, named=True)
        s["nulls"] = {k[5:]: v for k, v in s.items() if k.startswith("null:") and v}
        s = {k: v for k, v in s.items() if not k.startswith("null:")}
        report[kind] = s
    # card names
    names17 = card_names(gcols, "deck_")
    missing = sorted(set(names17) - xmage)
    report["cards"] = {"17lands_columns": len(names17), "xmage_cards": len(xmage),
                       "in_17lands_not_xmage": missing, "in_xmage_not_17lands": sorted(xmage - set(names17))}
    if missing:
        use = games.select([(pl.col(f"deck_{n}") > 0).sum().alias(n) for n in missing]).collect().row(0, named=True)
        report["cards"]["games_with_unsupported_card_in_deck"] = {k: v for k, v in use.items()}
        report["cards"]["games_with_any_unsupported_card"] = games.select(
            pl.any_horizontal([pl.col(f"deck_{n}") > 0 for n in missing]).sum()).collect().item()
    picks_unsupported = drafts.filter(~pl.col("pick").is_in(sorted(xmage))).group_by("pick").len().sort("len", descending=True).collect()
    report["cards"]["picks_of_cards_xmage_lacks"] = dict(zip(picks_unsupported["pick"], picks_unsupported["len"]))
    # deck sanity and game/replay agreement
    deck_size = games.select(pl.sum_horizontal([pl.col(f"deck_{n}") for n in names17]).alias("n")).select(
        pl.col("n").min().alias("min"), pl.col("n").median().alias("median"), pl.col("n").max().alias("max"),
        (pl.col("n") < 40).sum().alias("under_40")).collect().row(0, named=True)
    report["game_data"]["deck_size"] = deck_size
    gk = games.select(GAME_KEY).unique()
    rk = replays.select(GAME_KEY).unique()
    report["game_vs_replay"] = {"games_without_replay": gk.join(rk, on=GAME_KEY, how="anti").select(pl.len()).collect().item(),
                                "replays_without_game": rk.join(gk, on=GAME_KEY, how="anti").select(pl.len()).collect().item()}
    gd = games.select("draft_id").unique(); dd = drafts.select("draft_id").unique()
    report["drafts_vs_games"] = {"drafts_with_no_games": dd.join(gd, on="draft_id", how="anti").select(pl.len()).collect().item(),
                                 "games_with_no_draft_picks": gd.join(dd, on="draft_id", how="anti").select(pl.len()).collect().item()}
    report["meta"] = {"game_meta_columns": meta, "rank": games.group_by("rank").len().sort("len", descending=True).collect().to_dicts()}
    (DATA / "audit.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report, indent=1, default=str)[:6000])


def split_of(draft_id):
    h = int(hashlib.sha256(f"{SPLIT_SALT}:{draft_id}".encode()).hexdigest()[:8], 16) % 100
    return "train" if h < 80 else "validation" if h < 90 else "test"


def split():
    p = DATA / "parquet"
    ids = pl.concat([pl.scan_parquet(p / f"{k}.parquet").select("draft_id") for k in FILES]).unique().collect()
    s = ids.with_columns(pl.col("draft_id").map_elements(split_of, return_dtype=pl.String).alias("split"))
    s.write_parquet(DATA / "splits.parquet")
    counts = {}
    for k in FILES:
        counts[k] = pl.scan_parquet(p / f"{k}.parquet").select("draft_id").join(s.lazy(), on="draft_id").group_by("split").len().collect().sort("split").to_dicts()
    meta = {"salt": SPLIT_SALT, "rule": "sha256(salt:draft_id)[:8] % 100: <80 train, <90 validation, else test",
            "drafts": s.group_by("split").len().sort("split").to_dicts(), "rows": counts}
    (DATA / "splits.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    {"convert": convert, "audit": audit, "split": split}[sys.argv[1]]()
