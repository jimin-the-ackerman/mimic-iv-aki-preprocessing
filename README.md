# MIMIC-IV AKI Prediction Preprocessing Pipeline

*[한국어 버전은 여기](README.ko.md)*

This project is a preprocessing pipeline that builds a model-ready dataset
from MIMIC-IV 3.1 for predicting acute kidney injury (AKI) in the ICU.

> This repository contains the preprocessing part of a team project at the
> Korea Clinical Datathon (October 16–18, 2026). The team topic was
> "AKI prediction model development: Can an AI agent improve prediction
> performance?", using MIMIC-IV. I was responsible for data preprocessing;
> the team's modeling and AI-agent experiments are not included. I wrote
> the pipeline by myself, using a local LLM run through Ollama as a coding
> assistant. Some definitions, such as the prediction time and the
> prediction window, follow requests from the clinicians on the team.

---

## 1. Overview

The model reads the data of the first 48 hours of an ICU stay and predicts
whether AKI (KDIGO definition) starts in the following 24 hours.

| Item | Definition |
| --- | --- |
| Unit | ICU stay (`stay_id`) |
| Time zero (prediction time) | ICU admission (`intime`) + 48 hours |
| Input window | [`intime`, time zero) |
| Prediction window | 24 hours after time zero |
| Label | `label_aki_next_24h`: the first AKI of the stay starts in the prediction window |

The pipeline produces two tables from the same cohort: an **hourly table**
for sequence models and a **wide table** (one row per stay) for tabular
models. All parameters (cohort rules, KDIGO thresholds, itemids, plausible
ranges, drug classes, splits) are kept in `config.yaml`.

---

## 2. Pipeline

```
MIMIC-IV 3.1 CSV (13 tables)
-> 01 CSV to Parquet
-> 02 Base cohort (R1-R3)
-> 03 ESRD / chronic dialysis flag
-> 04 KDIGO labels (creatinine + urine output), weight, counts
-> 05 Final cohort (R4-R9)
-> 06 Drug map (NDC -> RxNorm -> ATC, via NLM RxNav)
-> 07 Features (hourly table + wide table)
-> 08 Patient-level splits
-> 09-12 Feature dictionary, default feature list, CSV copies, report
```

Each script reads the files of earlier steps, checks that its inputs exist,
and writes its own outputs (`scripts/run_all.sh`; dependency graph in
`docs/pipeline.md`).

### 2.1 Cohort
The cohort starts from all 94,458 ICU stays and applies nine rules in order
(`docs/cohort_definition.md`): first ICU stay of the admission, age 18 or
older, ICU stay of 48 hours or more, weight available, at least two
creatinine values before time zero, no AKI before time zero, a known
outcome, no dialysis started in the ICU before time zero in non-ESRD
patients, and data in the prediction window for label-0 stays. Stays of
ESRD and chronic dialysis patients are kept and flagged
(`esrd_chronic_dialysis`).

### 2.2 KDIGO Labels
AKI starts at the first time that one of three KDIGO criteria is true
(`scripts/04_build_labels.py`):

- **Creatinine, 48 hours:** a rise of at least 0.3 mg/dL against the lowest
  strictly earlier value in the previous 48 hours.
- **Creatinine, 7 days:** a value of at least 1.5 times the lowest strictly
  earlier value in the previous 7 days. The series starts 7 days before ICU
  admission and is joined by `subject_id`, because some pre-ICU values have
  no `hadm_id`.
- **Urine output:** below 0.5 mL/kg/h over a 6-hour window. The window is
  valid only if the charted intervals cover at least 6 and less than 12
  hours and no interval is longer than 2 hours. A missing record is never
  treated as zero output.

Each criterion keeps its own onset time, so the label can be recomputed for
another prediction window.

### 2.3 Features
- **Leakage control.** A measurement is used only if both its charting time
  and its storage time (`storetime`) are before time zero. Infusions are cut
  at time zero.
- **Hourly aggregation.** Vital signs, laboratory values, outputs, intake,
  urine output rate, vasopressor and dialysis status, and three eGFR
  equations (MDRD, Cockcroft-Gault, CKD-EPI 2021 without race term).
- **Plausibility.** Values outside a configured range are set to missing and
  counted in `n_outlier_<variable>`.
- **Missing values.** No imputation, forward fill or zero fill. Each hourly
  variable has an observation mask (`_obs`) and hours since the last value
  (`_hsl`).
- **Non-input columns.** ICD codes assigned at discharge and all outcome
  columns are marked as non-inputs in the feature dictionary.
  `default_features.json` lists the suggested model inputs.

### 2.4 Drug Features
Prescriptions are mapped NDC → RxNorm product → ingredient → ATC classes
through the NLM RxNav service, with an exact and an approximate name search
as fallback (`scripts/06_build_drug_map.py`). ATC codes that do not fit the
route of the order are dropped. The wide table has ten kidney-relevant drug
flags (draft list) and 124 ATC level-3 flags.

### 2.5 Splits
Three splits, all by patient (`subject_id`): random 70/15/15 stratified by
whether the patient has a label-1 stay (default), temporal by `anchor_year_group`, and hybrid (latest year
group as test).

### 2.6 Validation
- **Reproducibility.** Steps 02–12 were re-run in a clean copy of the
  project, and every output was identical (`scripts/compare_runs.py`).
- **Dataset sanity check.** `notebooks/baseline_models.ipynb` fits three
  baseline classifiers to check that the dataset can support a model,
  including a shuffled-label control and a check on charting-frequency
  features, which can predict the label for a non-clinical reason.

---

## 3. Resulting Dataset

| Item | Value |
| --- | --- |
| ICU stays in MIMIC-IV 3.1 | 94,458 (65,366 patients) |
| ICU stays in the dataset | 11,000 (10,211 patients) |
| Label 1 | 1,733 stays (15.8%) |
| Label 1 by creatinine / urine output / both | 778 / 1,092 / 137 |
| Hourly table | 528,000 rows (11,000 stays × 48 hours), 89 columns |
| Wide table | 11,000 rows, 350 columns |
| Median age / female | 66.0 years / 43.8% |

| Rule | Condition | Stays left | Patients left |
| --- | --- | --- | --- |
| – | All ICU stays | 94,458 | 65,366 |
| R1 | First ICU stay of the admission | 85,242 | 65,366 |
| R2 | Age 18 or older | 85,242 | 65,366 |
| R3 | ICU stay of 48 hours or more | 40,746 | 34,348 |
| R4 | Weight available | 40,619 | 34,260 |
| R5 | At least 2 creatinine values before time zero | 39,697 | 33,567 |
| R6 | No AKI before time zero | 17,646 | 15,984 |
| R7 | Outcome known | 11,136 | 10,332 |
| R8 | No early dialysis without ESRD | 11,086 | 10,286 |
| R9 | Label-0 stays have data in the prediction window | 11,000 | 10,211 |

---

## 4. Repository Structure

```
mimic-iv-aki-preprocessing/
├── config.yaml                  all parameters of the pipeline
├── scripts/                     steps 00-12, run_all.sh, compare_runs.py, make_share_zip.py
├── docs/                        definitions, feature dictionary, itemids, pipeline, notes (English + _kr)
├── notebooks/
│   └── baseline_models.ipynb    dataset sanity check (no outputs stored)
├── PREPROCESSING_REPORT.md      standalone report generated by step 12 (English + Korean)
├── requirements.txt             pipeline packages
└── requirements-notebook.txt    pipeline + notebook packages
```

---

## 5. Reproduction

### 5.1 Data
MIMIC-IV 3.1 requires credentialed access through
[PhysioNet](https://physionet.org/content/mimiciv/3.1/). Place the 13
uncompressed CSV files as described in `docs/setup.md`.

### 5.2 Environment Setup

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

### 5.3 Full Pipeline Execution

```bash
PY=.venv/bin/python bash scripts/run_all.sh
# SKIP_01=1 skips the CSV-to-Parquet conversion when the Parquet files exist
```

Step 06 needs internet access for the RxNav service (about 1 hour the first
time, seconds with the cache). Which steps to re-run after a change is
listed in `docs/pipeline.md`.

---

## 6. Limitations

- The dataset covers only ICU stays of 48 hours or more without AKI before
  time zero.
- The urine criterion needs charting intervals of at most 2 hours, so a
  stay with rare urine charting cannot reach it.
- `prescriptions` holds orders, not administered doses, and has no
  intravenous contrast.
- The plausible ranges and the kidney-relevant drug list are drafts that
  the clinical team has not reviewed.
- MIMIC-IV comes from a single hospital; there is no external validation.

---

## 7. Related Documents

- [`docs/index.md`](docs/index.md): index of all documents and reading order
- [`docs/cohort_definition.md`](docs/cohort_definition.md): task, stay
  rules, label, feature rules and splits
- [`docs/preprocessing_notes.md`](docs/preprocessing_notes.md): counts per
  step, decisions and their reasons, limits and open items
- [`docs/feature_dictionary.md`](docs/feature_dictionary.md): every column
  of the hourly and wide tables
- [`docs/itemids.md`](docs/itemids.md): MIMIC-IV item numbers used
- [`docs/pipeline.md`](docs/pipeline.md): script order, inputs and outputs,
  what to re-run after a change
- [`docs/setup.md`](docs/setup.md): data placement, environment and output
  folders
- [`PREPROCESSING_REPORT.md`](PREPROCESSING_REPORT.md): standalone report
  with all definitions and numbers

Every document in `docs/` has a Korean version (`_kr`).

---

## 8. Data Use & License

This repository contains code and documentation only. It holds no MIMIC-IV
data and nothing derived from it at the patient level. Use of MIMIC-IV is
subject to the PhysioNet credentialed data use agreement. The code is
released under the [MIT License](LICENSE).

---

## 9. Author

Jimin (jimin-the-ackerman)
