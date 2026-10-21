"""Make a zip file with the material that can be shared: code, documentation and configuration only.

Excluded on purpose: everything in data/ (MIMIC-IV data and everything derived from it), the Python environment, caches,
the .claude folder and operating-system files. data/external/rxnav_cache.json is excluded unless you pass --with-cache,
because it holds drug names and NDC codes that come from MIMIC-IV prescriptions.

Before it writes the zip, the script checks the files to be included: no local absolute path, no e-mail address, no
notebook output. If a check fails, it writes nothing.

Usage: python scripts/make_share_zip.py [--with-cache]
"""
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT_NAME = "mimic-iv-aki-preprocessing"
OUT = Path("mimic_iv_aki_preprocessing.zip")
INCLUDE = ["README.md", "LICENSE", "config.yaml", "requirements.txt", "requirements-notebook.txt", ".gitignore", "PREPROCESSING_REPORT.md"]
INCLUDE_GLOBS = ["scripts/*.py", "scripts/*.sh", "docs/*.md", "notebooks/*.ipynb"]
CACHE = "data/external/rxnav_cache.json"
FORBIDDEN = {
    "local absolute path": re.compile(r"/Users/[^/\s]+/|/home/[^/\s]+/|[A-Za-z]:\\Users\\|/private/tmp/"),
    "e-mail address": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
}


def main():
    with_cache = "--with-cache" in sys.argv[1:]
    files = [Path(p) for p in INCLUDE]
    for pattern in INCLUDE_GLOBS:
        files += sorted(Path(".").glob(pattern))
    if with_cache:
        files.append(Path(CACHE))
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise SystemExit("Missing files (run the pipeline first):\n  " + "\n  ".join(missing))
    files = sorted(set(files), key=str)

    problems = []
    for f in files:
        if f.suffix == ".ipynb":
            nb = json.loads(f.read_text())
            if any(c.get("outputs") for c in nb["cells"] if c["cell_type"] == "code"):
                problems.append(f"{f}: the notebook has outputs (clear them first)")
        if str(f) == CACHE or f.name == Path(__file__).name:
            continue  # the cache is not a text document; this script holds the patterns of the check
        text = f.read_text(errors="ignore")
        for name, rx in FORBIDDEN.items():
            for m in rx.finditer(text):
                problems.append(f"{f}: {name}: {m.group(0)}")
    if problems:
        raise SystemExit("Not zipped. Fix these problems first:\n  " + "\n  ".join(problems))

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f"{ROOT_NAME}/{f.as_posix()}")
    print(f"{OUT}: {len(files)} files, {OUT.stat().st_size / 1e3:.0f} KB" + (" (with the RxNav cache)" if with_cache else " (without the RxNav cache)"))


if __name__ == "__main__":
    main()
