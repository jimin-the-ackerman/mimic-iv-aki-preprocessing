"""Map prescription drugs to RxNorm ingredients and ATC classes using the free NLM RxNav API.

NDC -> RxNorm product -> ingredient(s) -> ATC classes (via RxClass). Drug names of orders with no NDC, or whose NDC did not map,
fall back to an exact RxNorm name search and then to RxNorm's approximate match (recorded in the `match` column). Responses are cached in data/external/rxnav_cache.json (restartable). Writes data/external/drug_map.parquet
and data/external/drug_map_info.json (API version and date, because the service changes over time).
Needs internet access. ~10 minutes the first time.
"""
import json, time, threading, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import duckdb, pandas as pd
import re


def check_inputs():
    """Stop with a clear message if an earlier pipeline step has not been run."""
    required = ['data/cohort/cohort_final.parquet', 'data/mimiciv/3.1_parquet/hosp/prescriptions.parquet']
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        raise SystemExit("Missing input files (run the earlier steps first, see docs/pipeline.md; run from the project root):\n  " + "\n  ".join(missing))


def main():
    check_inputs()
    BASE = "https://rxnav.nlm.nih.gov/REST"
    CACHE_PATH = Path("data/external/rxnav_cache.json")
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    lock, last, fetched = threading.Lock(), [0.0], [0]

    def get(path):
        if path in cache: return cache[path]
        for attempt in range(5):
            with lock:  # at most ~15 requests per second overall (RxNav allows 20)
                wait = 0.07 - (time.time() - last[0]); last[0] = time.time() + max(wait, 0)
            if wait > 0: time.sleep(wait)
            try:
                with urllib.request.urlopen(BASE + path, timeout=30) as r:
                    cache[path] = json.loads(r.read().decode())
                with lock:
                    fetched[0] += 1
                    if fetched[0] % 500 == 0:
                        print(f"  {fetched[0]} new requests", flush=True); CACHE_PATH.write_text(json.dumps(cache))
                return cache[path]
            except Exception:
                time.sleep(2 ** attempt)
        cache[path] = None; return None

    def run(fn, items):
        with ThreadPoolExecutor(6) as ex: return list(ex.map(fn, items))

    P = "data/mimiciv/3.1_parquet"
    rx = duckdb.sql(f"""
select lower(drug) drug, case when ndc is null or ndc in ('0','') then null else ndc end ndc, count(*) n
from '{P}/hosp/prescriptions.parquet' where hadm_id in (select hadm_id from 'data/cohort/cohort_final.parquet') group by 1, 2""").df()

    ndcs = sorted(rx.ndc.dropna().unique())
    print(len(ndcs), "NDCs", flush=True)

    def ids(d): return ((d or {}).get("idGroup") or {}).get("rxnormId") or []
    ndc_cui = dict(zip(ndcs, run(lambda n: ids(get(f"/rxcui.json?idtype=NDC&id={n}")), ndcs)))
    print("NDC lookups done:", sum(bool(v) for v in ndc_cui.values()), "mapped", flush=True)

    # names to look up: orders with no NDC, or whose NDC did not map
    unmapped = rx[rx.ndc.isna() | ~rx.ndc.map(lambda n: bool(ndc_cui.get(n)))]
    names = sorted(unmapped.drug.unique())
    print(len(names), "drug names to look up", flush=True)
    exact = dict(zip(names, run(lambda n: ids(get("/rxcui.json?" + urllib.parse.urlencode({"name": n, "search": 2}))), names)))
    print("exact name matches:", sum(bool(v) for v in exact.values()), flush=True)

    def approx(n):
        """RxNorm approximate match. Scores are not on a fixed scale, so accept only a rank-1 candidate whose name contains the
    first word (>= 4 letters) of the drug name; this avoids picking an unrelated drug."""
        d = get("/approximateTerm.json?" + urllib.parse.urlencode({"term": n, "maxEntries": 1, "option": 1}))
        cands = [c for c in (((d or {}).get("approximateGroup") or {}).get("candidate") or []) if c.get("rank") == "1"]
        words = [w for w in re.findall(r"[a-z]+", n) if len(w) >= 4]
        if not cands or not words: return []
        ok = [c["rxcui"] for c in cands if c.get("name") and words[0] in c["name"].lower()]
        return [ok[0]] if ok else []
    need = [n for n in names if not exact[n]]
    ap = dict(zip(need, run(approx, need)))
    name_cui = {n: exact[n] or ap.get(n, []) for n in names}
    name_match = {n: "exact" if exact[n] else ("approx" if ap.get(n) else "none") for n in names}
    print("approximate name matches:", sum(bool(v) for v in ap.values()), flush=True)

    def ingredients(cui):
        d = get(f"/rxcui/{cui}/related.json?tty=IN")
        out = []
        for g in ((d or {}).get("relatedGroup") or {}).get("conceptGroup") or []:
            for c in g.get("conceptProperties") or []: out.append((c["rxcui"], c["name"]))
        if not out:  # the code may already be an ingredient
            p = get(f"/rxcui/{cui}/properties.json"); pr = (p or {}).get("properties") or {}
            if pr.get("tty") == "IN": out = [(pr["rxcui"], pr["name"])]
        return out
    cuis = sorted({c for v in list(ndc_cui.values()) + list(name_cui.values()) for c in v})
    ing = dict(zip(cuis, run(ingredients, cuis)))
    print("ingredient lookups done", len(cuis), flush=True)

    def atc(cui):
        d = get(f"/rxclass/class/byRxcui.json?rxcui={cui}&relaSource=ATC")
        return sorted({(i["rxclassMinConceptItem"]["classId"], i["rxclassMinConceptItem"]["className"])
                       for i in (d or {}).get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", [])})
    ing_ids = sorted({i for v in ing.values() for i, _ in v})
    atc_of = dict(zip(ing_ids, run(atc, ing_ids)))
    print("ATC lookups done", len(ing_ids), flush=True)
    CACHE_PATH.write_text(json.dumps(cache))

    def row(key, kind, cuis_, match=""):
        ings = sorted({x for c in cuis_ for x in ing.get(c, [])})
        # one name per code; codes and names are written in the same order, so the i-th name belongs to the i-th code
        atcs = sorted(dict(a for i, _ in ings for a in atc_of.get(i, [])).items())
        return {"key": key, "kind": kind, "match": match, "rxcui": ";".join(cuis_), "ingredients": ";".join(n for _, n in ings),
                "ingredient_rxcui": ";".join(i for i, _ in ings), "atc_codes": ";".join(c for c, _ in atcs),
                "atc_names": ";".join(n for _, n in atcs)}
    rows = [row(n, "ndc", v, "ndc") for n, v in ndc_cui.items()] + [row(n, "name", v, name_match[n]) for n, v in name_cui.items()]
    out = pd.DataFrame(rows)
    out.to_parquet("data/external/drug_map.parquet", index=False)
    ver = (get("/version.json") or {})
    json.dump({"built": time.strftime("%Y-%m-%d"), "rxnav": ver, "ndc_mapped": int((out[out.kind == 'ndc'].rxcui != '').sum()),
               "ndc_total": len(ndcs), "names_exact": int((out.match == "exact").sum()), "names_approx": int((out.match == "approx").sum()), "names_total": len(names),
               "with_atc": int((out.atc_codes != '').sum())}, open("data/external/drug_map_info.json", "w"), indent=1)
    print(open("data/external/drug_map_info.json").read())


if __name__ == "__main__":
    main()
