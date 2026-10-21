# AKI prediction cohort definition (MIMIC-IV 3.1)

This document defines the task, the stays, the label, the feature rules and the splits. The parameters are in `config.yaml`.

## Terms

- **AKI**: acute kidney injury. This document uses the KDIGO criteria for AKI.
- **ICU stay**: one stay in an intensive care unit. Each stay has a `stay_id`.
- **Time zero**: the prediction time. It is 48 hours after ICU admission.
- **Prediction window**: the time after time zero in which the model looks for AKI. It is 24 hours long.
- **Feature**: a column that a model can use as input.
- **Flag**: a column with the value 0 or 1 (false or true).
- **ESRD**: end-stage renal disease.
- **CKD**: chronic kidney disease.
- **CRRT**: continuous renal replacement therapy, a type of dialysis.
- **eGFR**: estimated glomerular filtration rate.
- **ICD**: International Classification of Diseases.
- **ATC**: Anatomical Therapeutic Chemical classification of drugs.
- **NDC**: National Drug Code.

## Task

The model uses the ICU data from the first 48 hours after ICU admission. It predicts whether AKI starts in the next 24 hours. Only the first AKI of a stay counts. This is a binary classification task.

The length of the prediction window is `horizon_hours` in `config.yaml`. The current value is 24.

## Stay rules

The unit of the dataset is the ICU stay. A stay is in the dataset when it meets all rules below. The pipeline applies the rules in this order.

1. **R1.** The stay is the first ICU stay of its hospital admission.
2. **R2.** The patient is 18 years old or older.
3. **R3.** The ICU stay is at least 48 hours long. The task needs time zero.
4. **R4.** The stay has a weight. Without a weight, the pipeline cannot calculate the urine criterion.
5. **R5.** The stay has at least 2 creatinine values between ICU admission and time zero. With fewer values, the pipeline cannot calculate the creatinine criteria.
6. **R6.** No AKI starts before time zero. The task predicts only the first AKI.
7. **R7.** The outcome is known. AKI starts in the prediction window, or the ICU stay lasts until the window ends. A patient who dies or leaves the ICU earlier without AKI has no known outcome.
8. **R8.** The stay does not belong to a non-ESRD patient who starts dialysis in the ICU before time zero. This patient is effectively in AKI already.
9. **R9.** The stay does not combine the label 0 with an empty prediction window. An empty window has no creatinine value and less than 6 hours of urine data. No measurement exists, so the label 0 has no support.

## ESRD and CKD flags

The dataset keeps the stays of ESRD and chronic dialysis patients. The flag `esrd_chronic_dialysis` marks them. A user can remove them later.

The flag is 1 when one of these conditions is true:

- An ESRD ICD code (N186, Z992, 5856, V451 or V4511) exists on this admission or on an earlier admission.
- The admission-history item 225126 ("Dialysis patient") has the value 1 before time zero.

The dataset also keeps patients with other CKD. The flags `ckd_icd_prior_adm` and `ckd_icd_current_adm` mark them.

## Label

A stay has the label 1 when the first AKI starts after time zero and before the prediction window ends. AKI starts when at least one of these KDIGO criteria is true:

1. Creatinine rises by at least 0.3 mg/dL within 48 hours.
2. Creatinine is at least 1.5 times the baseline value within 7 days.
3. Urine output is below 0.5 mL/kg/h for 6 consecutive hours.

### Creatinine criteria

The pipeline compares each creatinine value with earlier values of the same patient. Criterion 1 uses the lowest earlier value in the 48 hours before the measurement. Criterion 2 uses the lowest earlier value in the 7 days before the measurement. The earlier values include hospital laboratory values from before ICU admission. The first creatinine value in this 7-day window has no earlier value. This value cannot start AKI.

### Urine output criterion

The volume of a urine record is the urine that collects since the previous record. The pipeline calculates the urine output as follows:

- A 6-hour window is valid when the charting intervals in the window cover 6 to 12 hours.
- Every interval in the window must be 2 hours or shorter. One large volume after a long charting gap cannot start AKI.
- A missing record is never zero output.
- The weight is the admission weight. If no admission weight exists, the weight is the first weight from before time zero.

### Criterion columns

The dataset saves the result of each criterion separately. It also saves the AKI start time for the reference urine rule. The reference rule accepts gaps of up to 12 hours, and the `mimic-code` project uses it. Use this start time for sensitivity analysis. The feature dictionary lists the columns.

## Feature rules

The features contain vital signs, laboratory values, weight, urine output, other output, fluid intake, dialysis data, eGFR and drug classes. The feature dictionary lists the columns.

**Time window.** The features use only data from before time zero. Laboratory values, chart events and output events must also have a storage time before time zero. Infusions, prescriptions and dialysis sessions use their start time. The pipeline clips each infusion at time zero.

**Missing values.** A missing value stays missing. The dataset has no imputation.

**Implausible values.** A value outside the plausible range becomes missing. The ranges are in `plausible_ranges` in `config.yaml`.

**eGFR.** The pipeline calculates eGFR from creatinine with the MDRD, Cockcroft-Gault and CKD-EPI 2021 equations. The equations have no race term. The dataset has no eGFR values from the laboratory. It has no Schwartz eGFR (a pediatric equation) and no cystatin C eGFR (MIMIC-IV has no cystatin C).

**Drug classes.** The drug features use the orders in the `prescriptions` table that start before time zero and do not stop before ICU admission. Each order has ATC classes. The dataset has two groups of drug flags:

- One flag for each of 10 kidney-relevant drug classes. The list is in `drugs.kidney_relevant` in `config.yaml`. For antibiotics and antivirals, only intravenous orders count.
- One flag for each ATC level-3 class with an order in at least 1% of the stays.

The vasopressor features come from the `inputevents` table.

## Splits

The file `splits.parquet` has three splits. Each split puts all stays of one patient (`subject_id`) in the same part.

- `split_random`: a random split with 70% train, 15% validation and 15% test. The label rate is almost the same in each part. This split is the default.
- `split_temporal`: train on the years 2008 to 2016, validate on 2017 to 2019 and test on 2020 to 2022. The split uses `anchor_year_group`.
- `split_hybrid`: the test part is the years 2020 to 2022. The earlier years split at random into 85% train and 15% validation.
