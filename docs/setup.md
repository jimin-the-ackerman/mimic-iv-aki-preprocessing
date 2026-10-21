# Setup: data, environment and output folders

This repository contains code only. It has no MIMIC-IV data. Get MIMIC-IV 3.1 from PhysioNet (credentialed access) and follow its data use agreement.

## Folder structure before the first run

Before you run the first script, the project must look like this:

```text
mimic-iv-aki-preprocessing/
├── README.md
├── LICENSE
├── config.yaml
├── requirements.txt
├── requirements-notebook.txt
├── .gitignore
├── PREPROCESSING_REPORT.md
├── notebooks/
│   └── baseline_models.ipynb         (optional)
├── docs/
│   ├── index.md                      index_kr.md
│   ├── setup.md                      setup_kr.md
│   ├── cohort_definition.md          cohort_definition_kr.md
│   ├── feature_dictionary.md         feature_dictionary_kr.md
│   ├── itemids.md                    itemids_kr.md
│   ├── pipeline.md                   pipeline_kr.md
│   └── preprocessing_notes.md        preprocessing_notes_kr.md
├── scripts/
│   ├── 00_make_sample_csvs.py        (optional)
│   ├── 01_csv_to_parquet.py
│   ├── 02_build_base_cohort.py
│   ├── 03_add_esrd_flag.py
│   ├── 04_build_labels.py
│   ├── 05_build_final_cohort.py
│   ├── 06_build_drug_map.py
│   ├── 07_build_features.py
│   ├── 08_build_splits.py
│   ├── 09_build_feature_dictionary.py
│   ├── 10_build_default_features.py
│   ├── 11_export_csv.py
│   ├── 12_build_standalone_report.py
│   ├── compare_runs.py               (optional)
│   ├── make_share_zip.py             (optional)
│   └── run_all.sh
└── data/                             (not in the repository; you create it)
    ├── external/
    │   └── rxnav_cache.json          (optional, saves about 1 hour in step 06)
    └── mimiciv/
        └── 3.1/
            ├── hosp/
            │   ├── admissions.csv           (0.09 GB)
            │   ├── d_icd_diagnoses.csv      (0.01 GB)
            │   ├── d_labitems.csv           (< 0.01 GB)
            │   ├── diagnoses_icd.csv        (0.18 GB)
            │   ├── labevents.csv            (18.4 GB)
            │   ├── patients.csv             (0.01 GB)
            │   └── prescriptions.csv        (3.49 GB)
            └── icu/
                ├── chartevents.csv          (41.94 GB)
                ├── d_items.csv              (< 0.01 GB)
                ├── icustays.csv             (0.01 GB)
                ├── inputevents.csv          (2.87 GB)
                ├── outputevents.csv         (0.46 GB)
                └── procedureevents.csv      (0.15 GB)
```

- The 13 CSV files above are the only MIMIC-IV files that the pipeline reads. They use about 68 GB. The pipeline needs about 5 GB more for its own files.
- The files must be uncompressed `.csv` files. PhysioNet offers `.csv.gz` files. Decompress them first (for example `gunzip labevents.csv.gz`).
- The other MIMIC-IV files (for example `emar.csv` or `microbiologyevents.csv`) can stay in the folders. The pipeline ignores them.
- The folder `data/` is in `.gitignore`. Nothing in it goes into the repository.

## Environment and run

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
PY=.venv/bin/python bash scripts/run_all.sh
```

For the notebook, install `requirements-notebook.txt` instead of `requirements.txt`. The steps, their files and the reproduction details are in [pipeline.md](pipeline.md).

## Baseline notebook

After the pipeline, `notebooks/baseline_models.ipynb` loads the wide table, shows a few plots and fits three baseline classifiers. It checks that the dataset can support a prediction model. Start it from the project folder with the Python environment of this project.

## Folders that the pipeline creates

| Folder | Content |
| --- | --- |
| `data/mimiciv/3.1_parquet/` | The Parquet tables (step 01) |
| `data/mimiciv/3.1_sample/` | The optional sample CSV files (script 00) |
| `PREPROCESSING_REPORT.md` | The standalone report in English and Korean (step 12) |
| `data/cohort/` | The cohort files and the flow tables |
| `data/features/` | The hourly and wide tables, the splits, the default feature list and the CSV copies |
| `data/external/` | The drug map (the RxNav cache is already there if you provided it) |

## Sharing

The data of MIMIC-IV are restricted. Share only the code. `python scripts/make_share_zip.py` makes `mimic_iv_aki_preprocessing.zip` with the code, the documentation, the notebook and the configuration, and without any data. Add `--with-cache` to include the RxNav cache (it holds drug names and NDC codes from MIMIC-IV prescriptions). The script stops if it finds a local path, an e-mail address or a notebook output.
