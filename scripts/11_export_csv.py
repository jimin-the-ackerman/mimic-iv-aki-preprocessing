"""Stage 11: CSV copies of the small outputs, for opening in Excel or VS Code. Parquet remains the main format.

Which files: config.yaml csv_export.files (chosen by size: all well under csv_export.max_csv_mb; Excel's row limit is 1,048,576).
The hourly table (about 125 MB as CSV) is too large, so data/features/hourly_example.csv holds its first N stays instead.
Format: UTF-8 with BOM (Excel reads non-ASCII text correctly), timestamps as 'YYYY-MM-DD HH:MM:SS', missing = empty cell,
numbers rounded to 10 significant digits (hides last-digit float noise; the Parquet files keep full precision).
"""
from pathlib import Path
import pandas as pd
import yaml


def check_inputs():
    """Stop with a clear message if an earlier pipeline step has not been run."""
    required = ['data/cohort/cohort_final.parquet', 'data/external/drug_map.parquet', 'data/features/wide.parquet', 'data/features/hourly.parquet', 'data/features/splits.parquet']
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        raise SystemExit("Missing input files (run the earlier steps first, see docs/pipeline.md; run from the project root):\n  " + "\n  ".join(missing))


def main():
    check_inputs()
    cfg = yaml.safe_load(open("config.yaml"))["csv_export"]

    def write(df, path):
        path = Path(path)
        df.to_csv(path, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d %H:%M:%S", float_format="%.10g")
        mb = path.stat().st_size / 1e6
        if mb > cfg["max_csv_mb"]:
            path.unlink()
            print(f"WARNING {path}: {mb:.0f} MB is over max_csv_mb ({cfg['max_csv_mb']}), not written")
        else:
            print(f"{path}: {len(df)} rows x {df.shape[1]} columns, {mb:.1f} MB")

    for f in cfg["files"]:
        write(pd.read_parquet(f"{f}.parquet"), f"{f}.csv")

    hourly = pd.read_parquet("data/features/hourly.parquet")
    first = sorted(hourly.stay_id.unique())[: cfg["hourly_example_stays"]]
    write(hourly[hourly.stay_id.isin(first)].sort_values(["stay_id", "hour"]), "data/features/hourly_example.csv")


if __name__ == "__main__":
    main()
