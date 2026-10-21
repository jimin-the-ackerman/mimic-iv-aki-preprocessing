"""Optional: make small copies of the MIMIC-IV CSVs that open in an editor (data/mimiciv/3.1_sample).

Files larger than 5 MB are cut to the header plus the first 1,000 rows; smaller files are copied whole. The first rows come
from the top of each file (a few patients), so samples are for looking at columns and formats, not for judging the data.
"""
import shutil
from pathlib import Path


def main():
    SRC, DST = Path("data/mimiciv/3.1"), Path("data/mimiciv/3.1_sample")
    if not SRC.exists():
        raise SystemExit(f"Missing {SRC} (put the MIMIC-IV CSVs there first)")
    for f in sorted(SRC.glob("*/*.csv")):
        out = DST / f.parent.name / f.name
        out.parent.mkdir(parents=True, exist_ok=True)
        if f.stat().st_size <= 5_000_000:
            shutil.copy(f, out)
            continue
        with open(f) as src, open(out, "w") as dst:
            for i, line in enumerate(src):
                if i > 1000: break
                dst.write(line)


if __name__ == "__main__":
    main()
