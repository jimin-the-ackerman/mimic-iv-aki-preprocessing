"""Convert the MIMIC-IV CSV tables used for the kidney cohort to Parquet (zstd)."""
import sys, time
from pathlib import Path
import duckdb
import yaml


def check_inputs():
    """Stop with a clear message if an earlier pipeline step has not been run."""
    required = ['data/mimiciv/3.1/icu/icustays.csv', 'data/mimiciv/3.1/hosp/patients.csv']
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        raise SystemExit("Missing input files (run the earlier steps first, see docs/pipeline.md; run from the project root):\n  " + "\n  ".join(missing))


def main():
    check_inputs()
    SRC = Path("data/mimiciv/3.1")
    DST = Path("data/mimiciv/3.1_parquet")

    TABLES = yaml.safe_load(open("config.yaml"))["mimic_tables"]
    # optional: name the tables as arguments, for example: python 01_csv_to_parquet.py hosp/emar
    if len(sys.argv) > 1:
        TABLES = {}
        for arg in sys.argv[1:]:
            module, name = arg.split("/")
            TABLES.setdefault(module, []).append(name)

    con = duckdb.connect()
    con.execute("set preserve_insertion_order=false")  # lower memory for big writes

    for module, names in TABLES.items():
        (DST / module).mkdir(parents=True, exist_ok=True)
        for name in names:
            src, dst = SRC / module / f"{name}.csv", DST / module / f"{name}.parquet"
            if dst.exists():
                print(f"skip {module}/{name} (exists)", flush=True)
                continue
            t = time.time()
            tmp = dst.with_suffix(".parquet.tmp")
            con.execute(
                f"copy (select * from read_csv('{src}', sample_size=-1)) "
                f"to '{tmp}' (format parquet, compression zstd)"
            )
            tmp.rename(dst)
            n = con.execute(f"select count(*) from '{dst}'").fetchone()[0]
            print(f"{module}/{name}: {n} rows, {dst.stat().st_size/1e9:.2f} GB, {time.time()-t:.0f}s", flush=True)


if __name__ == "__main__":
    main()
