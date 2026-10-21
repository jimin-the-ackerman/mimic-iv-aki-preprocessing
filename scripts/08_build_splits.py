"""Stage 6: splits table with three versions, all by subject_id (no patient in more than one part).

split_random   : patients 70/15/15, stratified by whether the patient has any positive stay
split_temporal : by anchor_year_group (config splits.temporal)
split_hybrid   : latest year group = test; the other groups split randomly train/val by patient
Writes data/features/splits.parquet (stay_id, subject_id, anchor_year_group, split_*).
"""
from pathlib import Path
import duckdb, yaml, numpy as np, pandas as pd


def check_inputs():
    """Stop with a clear message if an earlier pipeline step has not been run."""
    required = ['data/features/wide.parquet']
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        raise SystemExit("Missing input files (run the earlier steps first, see docs/pipeline.md; run from the project root):\n  " + "\n  ".join(missing))


def main():
    check_inputs()
    cfg = yaml.safe_load(open("config.yaml"))["splits"]
    seed, fr = cfg["seed"], cfg["random_fractions"]
    df = duckdb.sql("""select stay_id, subject_id, anchor_year_group, label_aki_next_24h as y
                   from 'data/features/wide.parquet'""").df()
    rng = np.random.default_rng(seed)

    def assign(patients, fractions):
        """patients: DataFrame(subject_id, pos). Stratified shuffle split -> dict subject_id -> part."""
        out = {}
        names, probs = list(fractions), np.array(list(fractions.values()), dtype=float)
        for _, grp in patients.groupby("pos"):
            ids = grp["subject_id"].to_numpy().copy(); rng.shuffle(ids)
            cuts = (np.cumsum(probs / probs.sum()) * len(ids)).round().astype(int)[:-1]
            for name, part in zip(names, np.split(ids, cuts)):
                out.update({s: name for s in part})
        return out

    pat = df.groupby("subject_id").agg(pos=("y", "max"), grp=("anchor_year_group", "first")).reset_index()
    df["split_random"] = df.subject_id.map(assign(pat[["subject_id", "pos"]], fr))

    tmap = {g: part for part, gs in cfg["temporal"].items() for g in gs}
    assert set(df.anchor_year_group) <= set(tmap), set(df.anchor_year_group) - set(tmap)
    df["split_temporal"] = df.anchor_year_group.map(tmap)

    test_groups = cfg["temporal"]["test"]
    earlier = pat[~pat.grp.isin(test_groups)]
    hv = cfg["hybrid_val_fraction"]
    hmap = assign(earlier[["subject_id", "pos"]], {"train": 1 - hv, "val": hv})
    df["split_hybrid"] = np.where(df.anchor_year_group.isin(test_groups), "test", df.subject_id.map(hmap))

    df = df.drop(columns="y")
    for c in ["split_random", "split_temporal", "split_hybrid"]:
        assert df[c].notna().all(), c
        assert (df.groupby("subject_id")[c].nunique() == 1).all(), f"patient in several parts: {c}"
    df.to_parquet("data/features/splits.parquet", index=False)

    lab = duckdb.sql("select stay_id, label_aki_next_24h y from 'data/features/wide.parquet'").df().set_index("stay_id").y
    chk = df.set_index("stay_id")
    for c in ["split_random", "split_temporal", "split_hybrid"]:
        t = pd.DataFrame({"stays": chk[c].value_counts(), "positives": lab.groupby(chk[c]).sum()})
        t["rate"] = (t.positives / t.stays).round(3)
        print(c); print(t.loc[[p for p in ["train", "val", "test"] if p in t.index]].to_string(), "\n")


if __name__ == "__main__":
    main()
