# Preprocessing notes: AKI prediction dataset from MIMIC-IV 3.1

Date of the notes: 2026-10-12.

These notes give the counts, the implementation details, the reasons for the decisions, the limits and the open items. The rules are in [cohort_definition.md](cohort_definition.md). These notes refer to the stay rules by their numbers (R1 to R9).

## 1. Result

| Item | Value |
| --- | --- |
| ICU stays in MIMIC-IV | 94,458 (65,366 patients) |
| ICU stays in the dataset | 11,000 (10,211 patients) |
| Stays with the label 1 | 1,733 (15.8%) |
| Label 1 by the creatinine criteria (criteria 1 and 2) | 778 stays |
| Label 1 by the urine output criterion (criterion 3) | 1,092 stays |
| Label 1 by both | 137 stays |
| Rows of the hourly table | 528,000 (11,000 stays, 48 hours) |
| Rows of the wide table | 11,000 |
| Median age | 66 years |
| Female patients | 43.8% |
| Deaths in hospital | 1,160 stays |

## 2. Software and data version

- Python 3.12.13, DuckDB 1.5.6, pandas 3.0.6, pyarrow 26.0.0. `requirements.txt` lists the package versions of the pipeline. `requirements-notebook.txt` adds the packages of the notebook.
- The RxNav web service of the US National Library of Medicine gave the drug classes. Its version was 05-Oct-2026 (API 3.1.356). The pipeline built the mapping on 2026-10-12.

## 3. Steps

The order of the scripts and their files are in [pipeline.md](pipeline.md).

### Step 01: convert the CSV files to Parquet

The script reads 13 MIMIC-IV tables and writes them as Parquet files with zstd compression. The 13 CSV files use about 68 GB. The Parquet files use about 4 GB. The row count of each Parquet table is the same as the row count of its CSV file.

The tables are: patients, admissions, labevents, d_labitems, diagnoses_icd, d_icd_diagnoses and prescriptions (module `hosp`). And: icustays, chartevents, d_items, inputevents, outputevents and procedureevents (module `icu`).

### Step 02: base cohort

The script starts from the table `icustays` and joins the tables `patients` and `admissions`.

| Rule | Stays left | Patients left |
| --- | --- | --- |
| None (all ICU stays) | 94,458 | 65,366 |
| R1 (first ICU stay of the admission) | 85,242 | 65,366 |
| R2 (age 18 or older) | 85,242 | 65,366 |
| R3 (ICU stay of 48 hours or more) | 40,746 | 34,348 |

R2 removes no stay, because MIMIC-IV has only adult patients. R3 removes 52% of the stays. This rule is the largest selection in the dataset.

The age at ICU admission is `anchor_age` plus the difference between the year of the ICU admission and `anchor_year`. MIMIC-IV shifts all dates. The shift keeps the time differences.

### Step 03: ESRD and chronic dialysis flag

The flag rule is in the cohort definition. At this step, the flag is 1 for 2,575 of the 40,746 stays. The script does not remove any stay.

### Step 04: labels, weights and counts

The script calculates the time of the first AKI for each stay. The rules are in the cohort definition. These are the implementation details:

- **Creatinine.** The script uses the itemid 50912 only. It keeps values from 0.1 to 30 mg/dL. Some earlier values have no `hadm_id`. Therefore, the script joins the laboratory data to the stay with `subject_id`.
- **Urine output.** The script sums the urine items for each charting time. The first record of a stay covers no time. The script also calculates the reference rule.
- **Weight.** The script converts pounds to kg. It keeps weights from 20 to 400 kg.
- **Start times.** Each criterion keeps its own start time. Therefore, the script can calculate the label again for another prediction window.
- **Counts.** The script counts the creatinine values and the urine hours in the prediction window. It finds the first dialysis session of each stay.

### Step 05: final cohort and label

The script applies the rules that need the label. It writes `flow_final.csv`.

| Rule | Stays left | Patients left |
| --- | --- | --- |
| R1 to R3 (step 02) | 40,746 | 34,348 |
| R4 (weight available) | 40,619 | 34,260 |
| R5 (at least 2 creatinine values before time zero) | 39,697 | 33,567 |
| R6 (no AKI before time zero) | 17,646 | 15,984 |
| R7 (outcome known) | 11,136 | 10,332 |
| R8 (no early dialysis without ESRD) | 11,086 | 10,286 |
| R9 (label 0 has data in the window) | 11,000 | 10,211 |

R6 removes 22,051 stays. This rule is the second largest selection. The urine criterion starts first in 12,790 of these stays (58%). The creatinine criteria start first in 9,243 stays (42%). Both start together in 18 stays.

### Step 06: drug map

The script maps each drug order of the cohort to ATC classes.

1. The script looks up the NDC code of the order in RxNorm. It finds 3,010 of 4,856 NDC codes.
2. If the NDC code gives no result, the script looks up the drug name. It finds 882 names exactly and 493 names by approximate match. An approximate match must have rank 1 and must contain the first word of the drug name.
3. The script finds the ingredient of each RxNorm code. It asks RxClass for the ATC classes of the ingredient.

The result is the file `data/external/drug_map.parquet`. For the orders that start before time zero, 79.7% have an ATC class. The other 20.3% are mostly not drugs of interest. Examples are "bag", "vial", flush solutions and sterile water.

Almost all orders of the kidney-relevant drugs have an ATC class. One exception is enalapril, with 73%.

### Step 07: features

The script writes the hourly table and the wide table. The feature rules are in the cohort definition. The columns are in [feature_dictionary.md](feature_dictionary.md). The script makes 124 flags for ATC level-3 classes.

### Steps 08 to 11: splits, dictionary, default features and CSV copies

The script of step 08 writes three splits. The definitions are in the cohort definition. These are the sizes. The percentages are the shares of label 1.

| Split | Train | Validation | Test |
| --- | --- | --- | --- |
| `split_random` | 7,689 stays (15.8%) | 1,653 stays (15.7%) | 1,658 stays (15.7%) |
| `split_temporal` | 6,949 stays (18.2%) | 2,255 stays (11.2%) | 1,796 stays (12.0%) |
| `split_hybrid` | 7,836 stays (16.5%) | 1,368 stays (16.6%) | 1,796 stays (12.0%) |

The script of step 10 writes `default_features.json`. It is a suggested list of model inputs: 254 wide columns and 73 hourly columns. It leaves out the labels, the identifiers and the Caution columns. It also leaves out five variables that exist in less than 5% of the stays. It leaves out drug classes with an order in more than 99% of the stays.

Steps 09 and 11 write the feature dictionary and the CSV copies. The hourly CSV file has only a 100-stay example, because the full table is too large.

## 4. Decisions

The last column names the section or file that defines the decision.

| Topic | Reason | Defined in |
| --- | --- | --- |
| Prediction time | The doctors want one time zero. The task is simple and the label is clear. | Task |
| Prediction window | The doctors expect 24 hours. The script can calculate another value. | Task |
| Model type | The doctors ask for "AKI in the next X hours". | Task |
| Stays that end in the window | The outcome is not known. The filter treats death and discharge in the same way. | R7 |
| Study population | The task cannot use stays shorter than 48 hours or stays with AKI before time zero. | Stay rules |
| Baseline creatinine | This follows the KDIGO definition. | Creatinine criteria |
| ESRD and chronic dialysis | The doctors can remove these stays later. | ESRD and CKD flags |
| Urine criterion with an interval limit | One value after a long gap is not reliable. | Urine output criterion |
| Early dialysis without ESRD | These patients are effectively in AKI. | R8 |
| Label 0 with no data in the window | Nothing was measured, so the label has no support. | R9 |
| Missing values | The model code chooses the imputation. This prevents leakage between train and test. | Feature rules |
| Implausible values | The ranges are a draft for review. They are mostly tighter than the limits in the `mimic-code` project. The upper limit of the respiratory rate is looser (80 against 70). | Feature rules |
| eGFR | The laboratory values are rare and use other equations. MIMIC-IV has no cystatin C. | Feature rules |
| Drug classes | A standard classification replaces name matching. | Feature rules |
| Intravenous orders only | Oral, eye and skin forms do not harm the kidney in the same way. | Feature rules |
| Piperacillin by ingredient name | ATC from RxNorm cannot separate piperacillin from ampicillin. | `drugs.kidney_relevant` in `config.yaml` |
| Splits | The team can test the effect of the split type. | Splits |
| Table layout | The hourly table is for sequence models. The wide table is for tabular models. | Feature dictionary |
| Output columns | The doctors list these items. | Notes on items in `itemids.md` |

## 5. Known limits

- **Selection.** The dataset has only a part of the ICU stays (see section 1). The model applies only to patients who stay 48 hours or more in the ICU and have no AKI at 48 hours.
- **Urine criterion.** A stay with rare urine charting cannot reach the urine criterion. The label can miss AKI in these stays.
- **Charting frequency.** A feature that counts the hours with a value measures how often staff charted, not the state of the patient. In a baseline model, these counts alone give a test AUROC of 0.67. The urine criterion needs frequent charting, so this effect can come from the label. The same model keeps an AUROC of 0.73 without these counts. The notebook `notebooks/baseline_models.ipynb` shows this check.
- **Early AKI.** R6 removes a large part of the stays (step 05 gives the numbers). The model cannot predict AKI for these patients.
- **Time drift.** The label rate falls with time (see the split table in steps 08 to 11). A model can lose accuracy over time.
- **Single hospital.** MIMIC-IV comes from one hospital. The dataset has no external validation.
- **Drug orders.** The `prescriptions` table has orders, not the doses that the patient received. It has no intravenous contrast. 20.3% of the orders have no ATC class.
- **Discharge codes.** ICD codes of the current admission contain information from the end of the stay. The feature dictionary marks the affected columns as Caution.
- **Race.** The dataset has the field `race`, but the pipeline does not use it.
- **Drug recommendation.** The dataset gives the drug flags. A model that recommends the exclusion of a drug needs causal methods. A normal model learns only associations.

## 6. Open items

- The clinical team must review the plausible ranges (`plausible_ranges`) and the kidney-relevant drug list (`drugs.kidney_relevant`) in `config.yaml`.
- The team must decide if reported results include the 258 stays with the ESRD flag.
- The doctors asked for a drug database ("약물DB"). The team must name the database. The dataset uses RxNorm and ATC today.
- The doctors asked for a model that recommends the exclusion of drugs. This task belongs to the modeling stage. Preprocessing does not include it.
