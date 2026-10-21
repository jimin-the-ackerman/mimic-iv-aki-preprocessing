# Pipeline: the order of the scripts

The folder `scripts/` contains the pipeline. Run the scripts in the order of their numbers. Run them from the project root.

Each script reads files that earlier scripts wrote. Each script writes its own files. The scripts share no data in memory.

Each script first checks that its input files exist. If a file is missing, the script stops. It prints the names of the missing files. Therefore, a script that runs too early fails with a clear message.

All parameters are in `config.yaml`.

## Run the pipeline

To make the dataset from the MIMIC-IV files, do these steps:

1. Put the MIMIC-IV 3.1 CSV files in `data/mimiciv/3.1`.
2. Install the packages from `requirements.txt` in a Python 3.12 environment. For the notebook, install `requirements-notebook.txt` instead.
3. If you have it, put `data/external/rxnav_cache.json` in the project.
4. Run `PY=.venv/bin/python bash scripts/run_all.sh`.

To skip the CSV conversion (script `01`), set `SKIP_01=1`. The conversion takes about 20 minutes.

## Dependency graph

```text
 MIMIC-IV 3.1 CSVs
        |
   01 csv_to_parquet ----------------------------------------------+  (every later script reads these Parquet tables)
        |                                                          |
   02 build_base_cohort    -> data/cohort/base_cohort.parquet      |
        |                                                          |
   03 add_esrd_flag        -> data/cohort/cohort_stage2.parquet    |
        |                                                          |
   04 build_labels         -> data/cohort/cohort_stage3.parquet    |
        |                                                          |
   05 build_final_cohort   -> data/cohort/cohort_final.parquet     |
        |                                                          |
   06 build_drug_map       -> data/external/drug_map.*             |   (needs internet or the saved cache)
        |                                                          |
   07 build_features       -> data/features/hourly.parquet, wide.parquet
        |            \
   08 build_splits    10 build_default_features -> data/features/default_features.json
        |      -> data/features/splits.parquet
   09 build_feature_dictionary -> docs/feature_dictionary*.md   (reads hourly, wide, splits)
   11 export_csv -> CSV copies of the small outputs (reads the files above)
   12 build_standalone_report -> PREPROCESSING_REPORT.md   (reads the tables, the flow tables and the drug map)
```

## Inputs and outputs

| Step | Script | Reads | Writes | Run time (approximate) |
| --- | --- | --- | --- | --- |
| 01 | `01_csv_to_parquet.py` | CSV files in `data/mimiciv/3.1` | `data/mimiciv/3.1_parquet/` | 20 minutes |
| 02 | `02_build_base_cohort.py` | Parquet tables: icustays, patients, admissions | `base_cohort.parquet`, `flow_base.csv` | seconds |
| 03 | `03_add_esrd_flag.py` | `base_cohort`; Parquet tables: diagnoses_icd, admissions, chartevents | `cohort_stage2.parquet` | seconds to 1 minute |
| 04 | `04_build_labels.py` | `cohort_stage2`; Parquet tables: labevents, chartevents, outputevents, procedureevents | `cohort_stage3.parquet` | 1 to 2 minutes |
| 05 | `05_build_final_cohort.py` | `cohort_stage3` | `cohort_final.parquet`, `flow_final.csv` | seconds |
| 06 | `06_build_drug_map.py` | `cohort_final`; Parquet table: prescriptions; **internet** (NLM RxNav service) | `data/external/drug_map.parquet`, `drug_map_info.json`, `rxnav_cache.json` | 1 hour the first time, seconds with the cache |
| 07 | `07_build_features.py` | `cohort_final`, `data/external/drug_map.parquet` (from `06`); Parquet tables: labevents, chartevents, inputevents, outputevents, procedureevents, diagnoses_icd, admissions, prescriptions | `hourly.parquet`, `wide.parquet` | less than 1 minute |
| 08 | `08_build_splits.py` | `wide.parquet` | `splits.parquet` | seconds |
| 09 | `09_build_feature_dictionary.py` | `hourly`, `wide`, `splits` | `docs/feature_dictionary.md`, `docs/feature_dictionary_kr.md` | seconds |
| 10 | `10_build_default_features.py` | `hourly`, `wide` | `default_features.json` | seconds |
| 11 | `11_export_csv.py` | `cohort_final`, `drug_map`, `hourly`, `wide`, `splits` | `cohort_final.csv`, `wide.csv`, `splits.csv`, `drug_map.csv`, `hourly_example.csv` | seconds |
| 12 | `12_build_standalone_report.py` | `hourly`, `wide`, `splits`, the flow tables, `drug_map_info.json`, Parquet table: prescriptions | `PREPROCESSING_REPORT.md` in the project root | seconds |

The paths under `data/cohort/` and `data/features/` are relative to the project root.

## Change something and run again

After a change, run the scripts in the right column again. Run them in order.

| What you change | Scripts to run |
| --- | --- |
| The CSV files, the MIMIC version or `mimic_tables` | `01` to `12` |
| The cohort rules (age, minimum stay) or `time_zero_hours` | `02` to `12` |
| The ESRD rule (`esrd_*` in `config.yaml`) | `03` to `12` |
| The KDIGO thresholds, the urine rule, the creatinine or weight ranges, or the itemids for the label | `04` to `12` |
| The horizon (`horizon_hours`), the exclusions or the minimum number of creatinine values | `04` to `12` |
| `plausible_ranges`, the itemids of the features, `drugs.kidney_relevant` or the output item lists | `07` to `12` |
| The drug lookup code in `06` or the RxNorm cache | `06` to `12` |
| The split seed, the split fractions or the year groups | `08`, `09`, `11` and `12` |
| The columns that the default feature list suggests | `10` |
| Only the descriptions in the feature dictionary | `09` |
| The files that get a CSV copy, or the size of the example | `11` |
| Any change that alters the content of the standalone report | `12` |

## Notes

- Every script has a function `main()`. A script runs only when you start it directly. If you import a script, nothing runs.
- Scripts that read earlier outputs also have a function `check_inputs()`.
- Script `00_make_sample_csvs.py` is optional. It makes small CSV copies of the MIMIC-IV files for browsing. No other script uses it.
- Script `06` is the only script that needs the internet. The service changes with time. Keep the file `data/external/rxnav_cache.json` and pass it to the people who run the pipeline. The cache makes a new run give the same mapping. The cache is not in the public repository, because it holds drug names and NDC codes from MIMIC-IV prescriptions.
- Script `05` stops if the urine interval setting in `config.yaml` is not 2 hours. Script `04` calculates only the 2-hour variant.
- Script `01` converts only the tables in `mimic_tables` in `config.yaml`. Script `09` uses the same list. To convert other tables, give their names as arguments, for example `python scripts/01_csv_to_parquet.py hosp/emar`. The arguments replace the default list.
- The scripts write all cohort and feature tables sorted by `stay_id`. The scripts sort the hourly table by `stay_id` and `hour`. The row order is the same on every run.
- The last digit of a floating-point number in a Parquet file can differ between runs and machines. The CSV copies round numbers to 10 significant digits. They were identical in the clean-room test.
- The script `scripts/compare_runs.py` compares the outputs of two runs. Use it as `python scripts/compare_runs.py A B`, where A and B are two project folders. It sorts the Parquet files and uses a relative tolerance of 1e-9 for floating-point numbers.

## Reproducibility test

Date of the test: 2026-10-12.

- The test ran scripts `02` to `12` again in a clean copy of the project.
- The copy had no cohort, feature or drug-map files. It had only the RxNav cache file.
- Every output was the same as the output of the main run.

The test did not cover two items:

- Script `01`. A separate check compared the row counts with the CSV files.
- A new online run of script `06` without the cache.
