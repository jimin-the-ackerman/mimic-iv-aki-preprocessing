# English

## Preprocessing of MIMIC-IV 3.1 for AKI prediction in the ICU

This report describes how the preprocessed dataset was made. The model reads the first 48 hours of ICU data of a stay. It predicts whether acute kidney injury (AKI) starts in the next 24 hours. Every number below comes from the pipeline outputs, and every feature is listed with its derivation.

| Item | Value |
| --- | --- |
| Source data | MIMIC-IV 3.1 (hosp, icu) |
| ICU stays in the source | 94,458 (65,366 patients) |
| ICU stays in the dataset | 11,000 (10,211 patients) |
| Stays with label 1 | 1,733 (15.8%) |
| Label 1 by creatinine criteria / urine criterion / both | 778 / 1,092 / 137 |
| Hourly table | 528,000 rows (11,000 stays x 48 hours), 89 columns |
| Wide table | 11,000 rows (one per stay), 350 columns |
| Median age / female | 66.0 years / 43.8% |
| Deaths in hospital | 1,160 stays |
| Software | Python 3.12.13, DuckDB 1.5.6, pandas 3.0.6, pyarrow 26.0.0 |

### 1. Time axis and unit

- The unit of the dataset is the ICU stay (`stay_id`).
- `intime` is the ICU admission time. **Time zero** is `intime` + 48 hours. It is the prediction time.
- The **prediction window** is the 24 hours after time zero.
- Every feature uses only data from before time zero (see section 4.1).

### 2. Cohort rules

| Rule | Condition | Stays left | Patients left |
| --- | --- | --- | --- |
| - | All ICU stays | 94,458 | 65,366 |
| R1 | First ICU stay of the hospital admission | 85,242 | 65,366 |
| R2 | Age at ICU admission is 18 years or more | 85,242 | 65,366 |
| R3 | ICU stay is 48 hours long or longer | 40,746 | 34,348 |
| R4 | A weight exists (see `weight_kg`) | 40,619 | 34,260 |
| R5 | At least 2 creatinine values between ICU admission and time zero | 39,697 | 33,567 |
| R6 | No AKI starts before time zero | 17,646 | 15,984 |
| R7 | The outcome is known: AKI starts in the prediction window, or the ICU stay lasts until the window ends (`outtime` >= time zero + window) | 11,136 | 10,332 |
| R8 | Not a non-ESRD patient who starts dialysis in the ICU before time zero | 11,086 | 10,286 |
| R9 | Not a label-0 stay whose prediction window has no creatinine value and less than 6 hours of urine data | 11,000 | 10,211 |

The pipeline applies the rules in this order. Stays of ESRD and chronic dialysis patients are kept and flagged (`esrd_chronic_dialysis`).

### 3. Label

`label_aki_next_24h` is 1 if the first AKI of the stay starts after time zero and up to 24 hours after time zero. AKI starts at the first time that one of three KDIGO criteria is true.

| Criterion | Definition | Computation |
| --- | --- | --- |
| 1 | Creatinine rises by at least 0.3 mg/dL within 48 hours | A creatinine value is compared with the lowest earlier value in the 48 hours before it (strictly earlier). The criterion is true if the difference is at least 0.3 mg/dL. |
| 2 | Creatinine is at least 1.5 times the baseline within 7 days | A creatinine value is compared with the lowest earlier value in the 7 days before it (strictly earlier). The criterion is true if value >= 1.5 x lowest earlier value. |
| 3 | Urine output below 0.5 mL/kg/h for 6 hours | See the urine rule below. |

**Creatinine series.** Only itemid 50912 counts (values from 0.1 to 30 mg/dL). The series of a stay starts 7 days before ICU admission and ends at ICU discharge. The pipeline joins the laboratory table with `subject_id`, because some earlier values have no `hadm_id`. Values with the same time are averaged. An AKI start needs a measurement time at or after `intime`. The first value of the series has no earlier value, so it cannot start AKI.

**Urine rule.** The urine items (see section 4.3) are summed for each charting time. Each record covers the time since the previous record of the stay. The first record of a stay covers no time. For each record, the window is the 6 hours up to and including its charting time. The window is valid if both conditions are true. (a) The intervals of the records in the window sum to at least 6 and less than 12 hours. (b) Every interval in the window is at most 2 hours. The rate is the volume sum of the window divided by the weight (`weight_kg`) and by the interval sum in hours. If the rate is below 0.5 mL/kg/h, the criterion is true at the charting time of the record. A missing record is never zero output. The dataset also saves the start time of the reference rule without condition (b) (`onset_uo_reference_hour`).

### 4. Features

#### 4.1 General rules

- **Time window.** A measurement is used if its charting time is in [`intime`, time zero) and its storage time (`storetime`) is at or before time zero. This holds for `labevents`, `chartevents` and `outputevents`. Infusions (`inputevents`) and dialysis sessions (`procedureevents`) use their start time; the part of an infusion after time zero is cut off. Prescriptions use the start time before time zero and a stop time not before `intime`. The dialysis history item (225126) uses its charting time before time zero.
- **Hourly bins.** Hour h (0 to 47) is [`intime` + h hours, `intime` + h + 1 hours). A measurement belongs to the hour of its charting time.
- **Plausibility.** A raw value outside the range in the tables below is removed (set to missing) before the hourly aggregation. The wide table counts the removed values in `n_outlier_<variable>`.
- **Missing values.** A missing value stays missing. There is no imputation, no forward fill and no zero fill.
- **Masks.** For each hourly variable v, `v_obs` is 1 if hour h has a value, and 0 otherwise. `v_hsl` is the number of hours since the last hour with `v_obs` = 1 (0 if the hour has a value, empty before the first value).
- **Laboratory itemids with several items** (for example `na`) pool the values of all listed items. The hourly value is the mean of all pooled values in the hour.

#### 4.2 Column names

| Pattern | Table | Meaning |
| --- | --- | --- |
| `<v>` | hourly | Hourly value of variable v |
| `<v>_obs` | hourly | 1 if the hour has a value of v, otherwise 0 |
| `<v>_hsl` | hourly | Hours since the last value of v |
| `<v>_min`, `_max`, `_mean` | wide | Minimum, maximum and mean of the hourly values of v over hours 0 to 47 (hours without a value are skipped) |
| `<v>_first`, `_last` | wide | Hourly value of v in the first and in the last hour that has a value |
| `<v>_total` | wide | Sum of the hourly values of v (only for the variables that are volumes) |
| `<v>_n_hours_obs` | wide | Number of hours with a value of v (sum of `<v>_obs`) |
| `n_outlier_<v>` | wide | Number of raw values of v outside the plausible range |

Variables that are volumes (they have `_total` and no `_min`, `_max`, `_mean`, `_first`, `_last`): `drain_ml`, `intake_ml`, `other_output_ml`, `stool_ml`, `ultrafiltrate_ml`, `urine_ml`.

#### 4.3 Measured variables (hourly table and wide table)

Hourly rule: `mean` = mean of all values of the hour; `sum` = sum of the values of the hour. For output variables, the pipeline first sums all items at the same charting time. This sum is one event. It applies the range to the event. Then it sums the events of the hour.

| Variable | Meaning | Unit | MIMIC table | Itemids | Hourly rule | Plausible range |
| --- | --- | --- | --- | --- | --- | --- |
| `hr` | Heart rate | bpm | chartevents | 220045 | mean | 20 to 300 |
| `sbp` | Systolic blood pressure, non-invasive and arterial pooled | mmHg | chartevents | 220179, 220050 | mean | 40 to 300 |
| `dbp` | Diastolic blood pressure, non-invasive and arterial pooled | mmHg | chartevents | 220180, 220051 | mean | 10 to 200 |
| `mbp` | Mean blood pressure, non-invasive and arterial pooled | mmHg | chartevents | 220181, 220052 | mean | 20 to 250 |
| `rr` | Respiratory rate | /min | chartevents | 220210 | mean | 2 to 80 |
| `temp_c` | Body temperature (Fahrenheit converted: (F - 32) x 5 / 9) | °C | chartevents | 223762 (Celsius), 223761 (Fahrenheit) | mean | 25 to 45 |
| `weight_daily` | Daily weight | kg | chartevents | 224639 | mean | 20 to 400 |
| `dial_blood_flow` | Dialysis blood flow | mL/min | chartevents | 224144 | mean | 0 to 600 |
| `dialysate_rate` | Dialysate flow rate | mL/h | chartevents | 224154 | mean | 0 to 10000 |
| `ultrafiltrate_ml` | Ultrafiltrate output | mL | chartevents | 226457 | sum | 0 to 5000 |
| `creatinine` | Serum creatinine | mg/dL | labevents | 50912 | mean | 0.1 to 30 |
| `creatinine_wb` | Whole-blood creatinine (blood gas) | mg/dL | labevents | 52024 | mean | 0.1 to 30 |
| `bun` | Blood urea nitrogen | mg/dL | labevents | 51006 | mean | 1 to 300 |
| `urine_creat` | Urine creatinine | mg/dL | labevents | 51082 | mean | 1 to 1500 |
| `na` | Sodium, chemistry and whole blood pooled | mEq/L | labevents | 50983, 50824 | mean | 100 to 180 |
| `k` | Potassium, chemistry and whole blood pooled | mEq/L | labevents | 50971, 50822 | mean | 1.5 to 9 |
| `cl` | Chloride, chemistry and whole blood pooled | mEq/L | labevents | 50902, 50806 | mean | 60 to 140 |
| `hco3` | Bicarbonate, chemistry and calculated pooled | mEq/L | labevents | 50882, 50803 | mean | 3 to 60 |
| `phosphate` | Phosphate | mg/dL | labevents | 50970 | mean | 0.3 to 20 |
| `mg` | Magnesium | mg/dL | labevents | 50960 | mean | 0.3 to 10 |
| `uric_acid` | Uric acid | mg/dL | labevents | 51007 | mean | 0.5 to 30 |
| `urine_ml` | Urine output | mL | outputevents | 226559, 226560, 226561, 226567, 226563, 226564, 226565, 226627, 226631 | sum | 0 to 5000 |
| `drain_ml` | Drain output | mL | outputevents | 38 items (list in the code configuration) | sum | 0 to 5000 |
| `stool_ml` | Stool and ostomy output | mL | outputevents | 226579, 226580, 226582, 226583 | sum | 0 to 5000 |
| `other_output_ml` | Other output: every output item that is not urine, drain, stool or excluded | mL | outputevents | all remaining items | sum | 0 to 5000 |

Urine items: 226559, 226560, 226561, 226567, 226563, 226564, 226565, 226627, 226631. The pipeline does not count 226626, 226629, 227510, 227511, 227488, 226633, 227489 as output (pre-admission output, irrigant fluid, blood loss and tube-feed residual).

#### 4.4 Derived hourly variables

| Variable | Derivation |
| --- | --- |
| `intake_ml` | Records of `inputevents` with the unit mL and an amount above 0 and up to 10000 mL. The pipeline spreads the amount of a record over the hours that it overlaps with [`intime`, time zero): the share of an hour is (overlap time of the hour) / (total duration of the record). A record without duration goes entirely to its start hour. The hourly value is the sum of the shares. |
| `urine_ml_kg_h` | Urine output rate in mL/kg/h. Only records with an interval from the previous record of 1 second to 6 hours count. The pipeline spreads the volume of a record over the hours of its interval, in proportion to the overlap time. The hourly rate is (spread volume) / `weight_kg` / (covered time in hours). An hour needs at least 30 minutes of covered time. Rates outside 0 to 20 are removed. |
| `vasopressor_active` | 1 if a vasopressor infusion in `inputevents` (itemids 221289, 221662, 221749, 221906, 222315, 229617, 229630, 229631, 229632, 229709, 229764) covers the hour. An infusion that ends exactly at the start of an hour also marks that hour. Otherwise 0. |
| `dialysis_active` | 1 if a dialysis session in `procedureevents` (itemids 225441, 225802, 225805) covers the hour (same rule as `vasopressor_active`). Otherwise 0. |
| `crrt_active` | The same as `dialysis_active`, for itemid 225802 (CRRT) only. |
| `egfr_mdrd` | `175 x creatinine^-1.154 x age^-0.203 x 0.742 (if female)`, in mL/min/1.73 m2. `creatinine` is the hourly value, `age` is `age_at_icu`. No race term. |
| `egfr_cg` | Cockcroft-Gault: `(140 - age) x weight_kg / (72 x creatinine) x 0.85 (if female)`, in mL/min. |
| `egfr_ckdepi` | CKD-EPI 2021: `142 x min(Scr/k, 1)^a x max(Scr/k, 1)^-1.200 x 0.9938^age x 1.012 (if female)`. Scr is the hourly creatinine. k = 0.7 (female) or 0.9 (male). a = -0.241 (female) or -0.302 (male). No race term. |

The three eGFR variables have a value only in hours with a creatinine value (`egfr_cg` also needs `weight_kg`). They have no `_obs` and no `_hsl`. The wide table has their `_min`, `_max`, `_mean`, `_first` and `_last`.

#### 4.5 Static features and derived columns (wide table)

| Column | Derivation |
| --- | --- |
| `stay_id`, `subject_id`, `hadm_id`, `intime`, `anchor_year_group`, `gender`, `first_careunit`, `admission_type`, `hospital_expire_flag` | MIMIC-IV columns, copied without change from `icustays`, `patients` and `admissions`. |
| `time_zero` | `intime` + 48 hours. |
| `age_at_icu` | `patients.anchor_age` + (year of `intime` - `patients.anchor_year`). |
| `weight_kg`, `weight_src` | Earliest charted value of the first available source in this order: itemid 226512 (kg), 226531 (pounds x 0.45359237), 224639 (daily, kg). Only values charted before time zero and from 20 to 400 kg count. `weight_src` is `admission_kg`, `admission_lbs` or `daily`. |
| `esrd_icd_current_adm` | 1 if `diagnoses_icd` of this admission has an ICD-10 code N186, Z992 or an ICD-9 code 5856, V451, V4511. The hospital assigns the codes at discharge. |
| `esrd_icd_prior_adm` | The same codes on an earlier admission of the same patient (earlier `admittime`). |
| `dialysis_hx_item` | 1 if `chartevents` of the stay has itemid 225126 with the value 1, charted before time zero. |
| `esrd_chronic_dialysis` | `esrd_icd_current_adm` OR `esrd_icd_prior_adm` OR `dialysis_hx_item`. It filters stays. It includes information coded at discharge, so it is not a model input. |
| `esrd_known_at_t0` | `esrd_icd_prior_adm` OR `dialysis_hx_item`. It is known at time zero. Use it as the model input. |
| `ckd_icd_current_adm`, `ckd_icd_prior_adm` | 1 if `diagnoses_icd` has an ICD-10 code that starts with N18 (not N186) or an ICD-9 code 5851, 5852, 5853, 5854, 5855 or 5859, on this admission (current) or on an earlier admission (prior). |
| `creat_baseline_7d`, `creat_last_pre_icu` | From `labevents` itemid 50912 (0.1 to 30 mg/dL, stored by time zero) with a charting time from 7 days before `intime` up to time zero: `creat_baseline_7d` is the lowest value, `creat_last_pre_icu` is the last value before `intime`. |
| `n_dialysis_sessions_before_t0`, `first_dialysis_hour` | Number of rows of `procedureevents` (itemids 225441, 225802, 225805) that start before time zero, and the smallest start time in hours from `intime` (empty if none). |
| `vasopressor_hours`, `dialysis_hours`, `crrt_hours` | Sum of `vasopressor_active`, `dialysis_active` and `crrt_active` over the 48 hours. |
| `rrt_before_t0` | 1 if the first dialysis session of the stay (same itemids) starts at or before time zero. |
| `urine_ml_kg_h_overall` | (sum of the volumes of the valid records, see `urine_ml_kg_h`) / `weight_kg` / (sum of their intervals in hours). Values above 20 are set to missing. |
| `fluid_balance_ml` | `intake_ml_total` - `urine_ml_total` - `drain_ml_total` - `stool_ml_total` - `other_output_ml_total` (a missing output total counts as 0). Empty if there is no intake value or no urine value. |
| `label_aki_next_24h`, `aki_by_creat`, `aki_by_uo` | Label (section 3). `aki_by_creat` is 1 if the first start by criterion 1 or 2 is in the prediction window. `aki_by_uo` is 1 if the first start by criterion 3 (with condition (b)) is in the prediction window. The label is 1 if one of them is 1. |
| `onset_aki_hour`, `onset_creat_hour`, `onset_uo_hour`, `onset_uo_reference_hour` | Hours from `intime` to the first AKI start of the whole stay: by any criterion, by criteria 1 and 2, by criterion 3, and by the reference urine rule. Empty if there is none. These columns hold information after time zero. They are not model inputs. |
| `n_kidney_relevant_classes` | Number of the kidney-relevant drug flags (section 4.6) that are 1. |

#### 4.6 Drug features (wide table)

1. **Orders.** An order of `prescriptions` counts if its start time is before time zero. Its stop time must not be before `intime`. If an order has no stop time, the start time replaces it. The pipeline matches orders to the stay with `hadm_id`.
2. **Drug classes.** Script 06 maps each order to ATC classes with the RxNav service of the US National Library of Medicine: NDC code -> RxNorm product -> ingredient -> ATC classes (levels 1 to 4). 3,010 of 4,856 NDC codes map. For the other orders, the pipeline looks up the drug name. Of 1,655 names, 882 match exactly and 493 match by approximate match. An approximate match needs rank 1 and the first word of the name inside the matched name. The NDC result has priority over the name result. 79.7% of the 580,873 orders of the stays in the dataset that start before time zero have an ATC class.
3. **Route filter.** The pipeline drops an ATC code that does not fit the route of the order. Skin, eye and ear routes keep only ATC groups D and S. Other routes drop D and S. Other routes keep the intestinal anti-infectives A07 only for oral routes.

**Kidney-relevant flags** (draft list, 1 if at least one matching order exists). Antibiotics and antivirals count only intravenous orders (`IV` route; for aminoglycosides also `IM`).

| Column | Match rule | Route rule |
| --- | --- | --- |
| `atc_J01G_aminoglycoside` | ATC code starts with J01G | intravenous or intramuscular |
| `atc_J01XA_vancomycin` | ATC code starts with J01XA | intravenous |
| `drug_pip_tazo` | ingredient name contains piperacillin | intravenous |
| `atc_J01XB_polymyxin` | ATC code starts with J01XB | intravenous |
| `atc_J02AA_amphotericin` | ATC code starts with J02AA | intravenous |
| `atc_J05AB_nucleoside_antiviral` | ATC code starts with J05AB | intravenous |
| `atc_M01A_nsaid` | ATC code starts with M01A | any |
| `atc_C03C_loop_diuretic` | ATC code starts with C03C | any |
| `atc_C09_ace_arb` | ATC code starts with C09 | any |
| `atc_L04AD_calcineurin` | ATC code starts with L04AD | any |

**ATC level-3 flags** `atc3_<code>`: 1 if an order has an ATC code that starts with the 4 characters of `<code>`. The pipeline makes a flag for every class with an order in at least 1% of the stays (124 flags): A01A, A02A, A02B, A03B, A03F, A04A, A06A, A07A, A07D, A07E, A08A, A10A, A10B, A11C, A11D, A11G, A11H, A12A, A12B, A12C, B01A, B02B, B03A, B03B, B05B, B05C, B05X, C01A, C01B, C01C, C01D, C01E, C02A, C02D, C03A, C03B, C03C, C03D, C05A, C05B, C07A, C07F, C08C, C08D, C09A, C09B, C09C, C09D, C09X, C10A, C10B, D01A, D04A, D06A, D07A, D07X, D10A, D11A, G01A, G02C, G04B, G04C, H01B, H01C, H02A, H03A, H04A, J01A, J01C, J01D, J01E, J01F, J01G, J01M, J01R, J01X, J02A, J05A, L04A, M01A, M02A, M03A, M03B, M04A, N01A, N01B, N02A, N02B, N02C, N03A, N04B, N05A, N05B, N05C, N06A, N06B, N06D, N07A, N07B, P01A, P01B, R01A, R01B, R02A, R03A, R03B, R03C, R03D, R05C, R05D, R06A, S01A, S01B, S01C, S01E, S01G, S01H, S02A, S02B, S02D, S03A, V03A, V04C, V06D.

#### 4.7 Splits (`splits` table)

Each split puts all stays of one patient (`subject_id`) in the same part.

| Column | Definition | Train | Validation | Test |
| --- | --- | --- | --- | --- |
| `split_random` | Random by patient, 70/15/15 %, stratified by whether the patient has a label-1 stay (default) | 7,689 (15.8%) | 1,653 (15.7%) | 1,658 (15.7%) |
| `split_temporal` | By `anchor_year_group`: train 2008-2010, 2011-2013, 2014-2016; validation 2017-2019; test 2020-2022 | 6,949 (18.2%) | 2,255 (11.2%) | 1,796 (12.0%) |
| `split_hybrid` | Test = latest year group; earlier years random by patient 85/15 % train/validation | 7,836 (16.5%) | 1,368 (16.6%) | 1,796 (12.0%) |

The numbers in brackets are the shares of label 1. The seed of the random split is 42.

### 5. Known limits

- **Selection.** The dataset keeps only stays of 48 hours or longer without AKI before time zero. A model applies only to such patients.
- **Urine criterion and charting frequency.** The urine criterion needs charting intervals of at most 2 hours. A stay with rare urine charting cannot reach it. The `_n_hours_obs` columns measure charting frequency, so they can predict the label for a reason that is not clinical.
- **Drug data.** `prescriptions` has orders, not given doses. It has no intravenous contrast. The drug list is a draft that the clinical team has not reviewed.
- **Plausible ranges** are a draft that the clinical team has not reviewed.
- **Discharge codes.** The columns `esrd_icd_current_adm`, `ckd_icd_current_adm` and `esrd_chronic_dialysis` hold ICD codes that the hospital assigns at discharge. Do not use them as model inputs. The columns `label_*`, `aki_by_*`, `onset_*` and `hospital_expire_flag` hold outcome information. They are not model inputs.
- **Single hospital.** MIMIC-IV comes from one hospital. The dataset has no external validation.
- **eGFR** has no race term.

### Appendix: all columns

**Hourly table (89 columns).**

```text
stay_id, hour, hr, sbp, dbp, mbp, rr, temp_c, weight_daily, dial_blood_flow, dialysate_rate, ultrafiltrate_ml, creatinine, creatinine_wb, bun, urine_creat, na, k, cl, hco3, phosphate, mg, uric_acid, urine_ml, drain_ml, stool_ml, other_output_ml, intake_ml, urine_ml_kg_h, vasopressor_active, dialysis_active, crrt_active, egfr_mdrd, egfr_cg, egfr_ckdepi, hr_obs, sbp_obs, dbp_obs, mbp_obs, rr_obs, temp_c_obs, weight_daily_obs, dial_blood_flow_obs, dialysate_rate_obs, ultrafiltrate_ml_obs, creatinine_obs, creatinine_wb_obs, bun_obs, urine_creat_obs, na_obs, k_obs, cl_obs, hco3_obs, phosphate_obs, mg_obs, uric_acid_obs, urine_ml_obs, drain_ml_obs, stool_ml_obs, other_output_ml_obs, intake_ml_obs, urine_ml_kg_h_obs, hr_hsl, sbp_hsl, dbp_hsl, mbp_hsl, rr_hsl, temp_c_hsl, weight_daily_hsl, dial_blood_flow_hsl, dialysate_rate_hsl, ultrafiltrate_ml_hsl, creatinine_hsl, creatinine_wb_hsl, bun_hsl, urine_creat_hsl, na_hsl, k_hsl, cl_hsl, hco3_hsl, phosphate_hsl, mg_hsl, uric_acid_hsl, urine_ml_hsl, drain_ml_hsl, stool_ml_hsl, other_output_ml_hsl, intake_ml_hsl, urine_ml_kg_h_hsl
```

**Wide table (350 columns).**

```text
stay_id, subject_id, hadm_id, intime, time_zero, anchor_year_group, age_at_icu, gender, first_careunit, admission_type, weight_kg, weight_src, esrd_chronic_dialysis, esrd_known_at_t0, esrd_icd_current_adm, esrd_icd_prior_adm, dialysis_hx_item, ckd_icd_prior_adm, ckd_icd_current_adm, creat_baseline_7d, creat_last_pre_icu, n_dialysis_sessions_before_t0, first_dialysis_hour, atc_J01G_aminoglycoside, atc_J01XA_vancomycin, drug_pip_tazo, atc_J01XB_polymyxin, atc_J02AA_amphotericin, atc_J05AB_nucleoside_antiviral, atc_M01A_nsaid, atc_C03C_loop_diuretic, atc_C09_ace_arb, atc_L04AD_calcineurin, atc3_A01A, atc3_A02A, atc3_A02B, atc3_A03B, atc3_A03F, atc3_A04A, atc3_A06A, atc3_A07A, atc3_A07D, atc3_A07E, atc3_A08A, atc3_A10A, atc3_A10B, atc3_A11C, atc3_A11D, atc3_A11G, atc3_A11H, atc3_A12A, atc3_A12B, atc3_A12C, atc3_B01A, atc3_B02B, atc3_B03A, atc3_B03B, atc3_B05B, atc3_B05C, atc3_B05X, atc3_C01A, atc3_C01B, atc3_C01C, atc3_C01D, atc3_C01E, atc3_C02A, atc3_C02D, atc3_C03A, atc3_C03B, atc3_C03C, atc3_C03D, atc3_C05A, atc3_C05B, atc3_C07A, atc3_C07F, atc3_C08C, atc3_C08D, atc3_C09A, atc3_C09B, atc3_C09C, atc3_C09D, atc3_C09X, atc3_C10A, atc3_C10B, atc3_D01A, atc3_D04A, atc3_D06A, atc3_D07A, atc3_D07X, atc3_D10A, atc3_D11A, atc3_G01A, atc3_G02C, atc3_G04B, atc3_G04C, atc3_H01B, atc3_H01C, atc3_H02A, atc3_H03A, atc3_H04A, atc3_J01A, atc3_J01C, atc3_J01D, atc3_J01E, atc3_J01F, atc3_J01G, atc3_J01M, atc3_J01R, atc3_J01X, atc3_J02A, atc3_J05A, atc3_L04A, atc3_M01A, atc3_M02A, atc3_M03A, atc3_M03B, atc3_M04A, atc3_N01A, atc3_N01B, atc3_N02A, atc3_N02B, atc3_N02C, atc3_N03A, atc3_N04B, atc3_N05A, atc3_N05B, atc3_N05C, atc3_N06A, atc3_N06B, atc3_N06D, atc3_N07A, atc3_N07B, atc3_P01A, atc3_P01B, atc3_R01A, atc3_R01B, atc3_R02A, atc3_R03A, atc3_R03B, atc3_R03C, atc3_R03D, atc3_R05C, atc3_R05D, atc3_R06A, atc3_S01A, atc3_S01B, atc3_S01C, atc3_S01E, atc3_S01G, atc3_S01H, atc3_S02A, atc3_S02B, atc3_S02D, atc3_S03A, atc3_V03A, atc3_V04C, atc3_V06D, n_kidney_relevant_classes, hr_min, hr_max, hr_mean, hr_first, hr_last, hr_n_hours_obs, sbp_min, sbp_max, sbp_mean, sbp_first, sbp_last, sbp_n_hours_obs, dbp_min, dbp_max, dbp_mean, dbp_first, dbp_last, dbp_n_hours_obs, mbp_min, mbp_max, mbp_mean, mbp_first, mbp_last, mbp_n_hours_obs, rr_min, rr_max, rr_mean, rr_first, rr_last, rr_n_hours_obs, temp_c_min, temp_c_max, temp_c_mean, temp_c_first, temp_c_last, temp_c_n_hours_obs, weight_daily_min, weight_daily_max, weight_daily_mean, weight_daily_first, weight_daily_last, weight_daily_n_hours_obs, dial_blood_flow_min, dial_blood_flow_max, dial_blood_flow_mean, dial_blood_flow_first, dial_blood_flow_last, dial_blood_flow_n_hours_obs, dialysate_rate_min, dialysate_rate_max, dialysate_rate_mean, dialysate_rate_first, dialysate_rate_last, dialysate_rate_n_hours_obs, ultrafiltrate_ml_total, ultrafiltrate_ml_n_hours_obs, creatinine_min, creatinine_max, creatinine_mean, creatinine_first, creatinine_last, creatinine_n_hours_obs, creatinine_wb_min, creatinine_wb_max, creatinine_wb_mean, creatinine_wb_first, creatinine_wb_last, creatinine_wb_n_hours_obs, bun_min, bun_max, bun_mean, bun_first, bun_last, bun_n_hours_obs, urine_creat_min, urine_creat_max, urine_creat_mean, urine_creat_first, urine_creat_last, urine_creat_n_hours_obs, na_min, na_max, na_mean, na_first, na_last, na_n_hours_obs, k_min, k_max, k_mean, k_first, k_last, k_n_hours_obs, cl_min, cl_max, cl_mean, cl_first, cl_last, cl_n_hours_obs, hco3_min, hco3_max, hco3_mean, hco3_first, hco3_last, hco3_n_hours_obs, phosphate_min, phosphate_max, phosphate_mean, phosphate_first, phosphate_last, phosphate_n_hours_obs, mg_min, mg_max, mg_mean, mg_first, mg_last, mg_n_hours_obs, uric_acid_min, uric_acid_max, uric_acid_mean, uric_acid_first, uric_acid_last, uric_acid_n_hours_obs, urine_ml_total, urine_ml_n_hours_obs, drain_ml_total, drain_ml_n_hours_obs, stool_ml_total, stool_ml_n_hours_obs, other_output_ml_total, other_output_ml_n_hours_obs, intake_ml_total, intake_ml_n_hours_obs, urine_ml_kg_h_min, urine_ml_kg_h_max, urine_ml_kg_h_mean, urine_ml_kg_h_first, urine_ml_kg_h_last, urine_ml_kg_h_n_hours_obs, egfr_mdrd_min, egfr_mdrd_max, egfr_mdrd_mean, egfr_mdrd_first, egfr_mdrd_last, egfr_cg_min, egfr_cg_max, egfr_cg_mean, egfr_cg_first, egfr_cg_last, egfr_ckdepi_min, egfr_ckdepi_max, egfr_ckdepi_mean, egfr_ckdepi_first, egfr_ckdepi_last, vasopressor_hours, dialysis_hours, crrt_hours, urine_ml_kg_h_overall, fluid_balance_ml, n_outlier_hr, n_outlier_sbp, n_outlier_dbp, n_outlier_mbp, n_outlier_rr, n_outlier_temp_c, n_outlier_weight_daily, n_outlier_creatinine, n_outlier_creatinine_wb, n_outlier_bun, n_outlier_urine_creat, n_outlier_na, n_outlier_k, n_outlier_cl, n_outlier_hco3, n_outlier_phosphate, n_outlier_mg, n_outlier_uric_acid, n_outlier_dial_blood_flow, n_outlier_dialysate_rate, n_outlier_ultrafiltrate_ml, n_outlier_urine_ml, n_outlier_drain_ml, n_outlier_stool_ml, n_outlier_other_output_ml, label_aki_next_24h, aki_by_creat, aki_by_uo, onset_aki_hour, onset_creat_hour, onset_uo_hour, onset_uo_reference_hour, rrt_before_t0, hospital_expire_flag
```

---

# 한국어

## ICU의 AKI 예측을 위한 MIMIC-IV 3.1 전처리

이 보고서는 전처리 데이터 세트를 만든 방법을 설명한다. 모델은 한 입실의 첫 48시간 ICU 데이터를 읽고, 이후 24시간 안에 급성 신손상(AKI)이 시작하는지 예측한다. 아래의 모든 숫자는 파이프라인 출력에서 나왔고, 모든 피처는 유도 방법과 함께 나열한다.

| 항목 | 값 |
| --- | --- |
| 원본 데이터 | MIMIC-IV 3.1 (hosp, icu) |
| 원본의 ICU 입실 | 94,458 (65,366명) |
| 데이터 세트의 ICU 입실 | 11,000 (10,211명) |
| 라벨 1인 입실 | 1,733 (15.8%) |
| 크레아티닌 기준 / 소변량 기준 / 둘 다로 라벨 1 | 778 / 1,092 / 137 |
| hourly 테이블 | 528,000행(입실 11,000건 x 48시간), 89칼럼 |
| wide 테이블 | 11,000행(입실당 1행), 350칼럼 |
| 나이 중앙값 / 여성 | 66.0세 / 43.8% |
| 원내 사망 | 1,160건 |
| 소프트웨어 | Python 3.12.13, DuckDB 1.5.6, pandas 3.0.6, pyarrow 26.0.0 |

### 1. 시간 축과 단위

- 데이터 세트의 단위는 ICU 입실(`stay_id`)이다.
- `intime`은 ICU 입실 시각이다. **time zero**는 `intime` + 48시간이며 예측 시점이다.
- **예측 구간**은 time zero 이후 24시간이다.
- 모든 피처는 time zero 이전의 데이터만 사용한다(4.1절 참고).

### 2. 코호트 규칙

| 규칙 | 조건 | 남은 입실 | 남은 환자 |
| --- | --- | --- | --- |
| - | 전체 ICU 입실 | 94,458 | 65,366 |
| R1 | 입원의 첫 번째 ICU 입실 | 85,242 | 65,366 |
| R2 | ICU 입실 시 나이가 18세 이상 | 85,242 | 65,366 |
| R3 | ICU 재원이 48시간 이상 | 40,746 | 34,348 |
| R4 | 체중이 있다(`weight_kg` 참고) | 40,619 | 34,260 |
| R5 | ICU 입실부터 time zero까지 크레아티닌 값이 2개 이상 | 39,697 | 33,567 |
| R6 | time zero 이전에 AKI가 시작하지 않았다 | 17,646 | 15,984 |
| R7 | 결과를 알 수 있다: 예측 구간 안에서 AKI가 시작하거나 ICU 재원이 구간 끝까지 이어진다(`outtime` >= time zero + 구간) | 11,136 | 10,332 |
| R8 | ESRD가 아닌 환자가 time zero 이전에 ICU에서 투석을 시작한 입실이 아니다 | 11,086 | 10,286 |
| R9 | 예측 구간에 크레아티닌 값이 없고 소변 데이터가 6시간 미만인 라벨 0 입실이 아니다 | 11,000 | 10,211 |

파이프라인은 이 순서로 규칙을 적용한다. ESRD 환자와 만성 투석 환자의 입실은 제거하지 않고 플래그(`esrd_chronic_dialysis`)로 표시한다.

### 3. 라벨

`label_aki_next_24h`는 입실의 첫 AKI가 time zero 이후 24시간 이내에 시작하면 1이다. 세 가지 KDIGO 기준 중 하나가 처음 참이 되는 시점에 AKI가 시작한다.

| 기준 | 정의 | 계산 |
| --- | --- | --- |
| 1 | 48시간 이내에 크레아티닌이 0.3 mg/dL 이상 상승 | 크레아티닌 값을 직전 48시간의 가장 낮은 이전 값(엄격히 이전)과 비교한다. 차이가 0.3 mg/dL 이상이면 참이다. |
| 2 | 7일 이내에 크레아티닌이 기준값의 1.5배 이상 | 크레아티닌 값을 직전 7일의 가장 낮은 이전 값(엄격히 이전)과 비교한다. 값 >= 1.5 x 가장 낮은 이전 값이면 참이다. |
| 3 | 소변량이 6시간 동안 0.5 mL/kg/h 미만 | 아래 소변량 규칙을 참고한다. |

**크레아티닌 시계열.** itemid 50912만 사용한다(값 0.1~30 mg/dL). 한 입실의 시계열은 ICU 입실 7일 전에 시작하고 ICU 퇴실에 끝난다. 일부 이전 값에는 `hadm_id`가 없으므로 파이프라인은 `subject_id`로 검사 테이블을 결합한다. 시각이 같은 값은 평균한다. AKI 시작은 `intime` 이후의 측정 시각이 필요하다. 시계열의 첫 값에는 이전 값이 없으므로 이 값으로는 AKI가 시작할 수 없다.

**소변량 규칙.** 소변 항목(4.3절 참고)을 기록 시각마다 합산한다. 기록 하나는 같은 입실의 직전 기록 이후의 시간을 덮는다. 입실의 첫 번째 기록은 시간을 덮지 않는다. 각 기록의 구간은 그 기록 시각까지(시각 포함)의 6시간이다. 다음 두 조건을 모두 만족하면 구간은 유효하다. (a) 구간 안 기록 간격의 합이 6시간 이상 12시간 미만이다. (b) 구간 안의 모든 간격이 2시간 이하이다. 속도는 구간의 소변량 합을 체중(`weight_kg`)과 간격의 합(시간)으로 나눈 값이다. 속도가 0.5 mL/kg/h 미만이면 그 기록의 시각에 기준이 참이다. 기록이 없는 시간을 소변량 0으로 보지 않는다. 데이터 세트는 조건 (b)가 없는 기준 규칙의 시작 시점(`onset_uo_reference_hour`)도 저장한다.

### 4. 피처

#### 4.1 일반 규칙

- **시간 구간.** 기록 시각이 [`intime`, time zero)에 있고 저장 시각(`storetime`)이 time zero 이전 또는 같으면 그 측정값을 사용한다. 이 규칙은 `labevents`, `chartevents`, `outputevents`에 적용한다. 주입(`inputevents`)과 투석 세션(`procedureevents`)은 시작 시각을 사용하며, 주입의 time zero 이후 부분은 자른다. 처방은 시작 시각이 time zero 이전이고 중단 시각이 `intime`보다 앞서지 않아야 한다. 투석 문진 항목(225126)은 time zero 이전의 기록 시각을 사용한다.
- **시간 단위 구간.** h시간(0~47)은 [`intime` + h시간, `intime` + h + 1시간)이다. 측정값은 기록 시각이 속한 시간에 들어간다.
- **허용 범위.** 아래 표의 범위를 벗어난 원시 값은 시간별 집계 전에 제거한다(결측으로 바꾼다). wide 테이블의 `n_outlier_<변수>`가 제거한 값의 개수를 센다.
- **결측값.** 결측값은 결측으로 유지한다. 대치, 전방 채움, 0 채움이 없다.
- **마스크.** 시간별 변수 v마다 `v_obs`는 그 시간에 값이 있으면 1이고 없으면 0이다. `v_hsl`은 `v_obs` = 1인 마지막 시간 이후 경과 시간 수이다(값이 있는 시간은 0, 첫 값 이전은 비어 있다).
- **항목이 여러 개인 검사 변수**(예: `na`)는 나열한 모든 항목의 값을 합산한다. 그 시간의 값은 합산한 모든 값의 평균이다.

#### 4.2 칼럼 이름

| 패턴 | 테이블 | 의미 |
| --- | --- | --- |
| `<v>` | hourly | 변수 v의 시간별 값 |
| `<v>_obs` | hourly | 그 시간에 v의 값이 있으면 1, 없으면 0 |
| `<v>_hsl` | hourly | v의 마지막 값 이후 경과 시간 |
| `<v>_min`, `_max`, `_mean` | wide | 시간별 값의 0~47시간 최솟값, 최댓값, 평균(값이 없는 시간은 건너뜀) |
| `<v>_first`, `_last` | wide | 값이 있는 첫 시간과 마지막 시간의 v 시간별 값 |
| `<v>_total` | wide | v의 시간별 값의 합(부피 변수에만 있음) |
| `<v>_n_hours_obs` | wide | v의 값이 있는 시간의 수(`<v>_obs`의 합) |
| `n_outlier_<v>` | wide | 허용 범위를 벗어난 v의 원시 값 개수 |

부피 변수(`_total`이 있고 `_min`, `_max`, `_mean`, `_first`, `_last`가 없음): `drain_ml`, `intake_ml`, `other_output_ml`, `stool_ml`, `ultrafiltrate_ml`, `urine_ml`.

#### 4.3 측정 변수(hourly 테이블과 wide 테이블)

시간별 규칙: `mean` = 그 시간 모든 값의 평균, `sum` = 그 시간 값의 합. 배출량 변수는 파이프라인이 먼저 같은 기록 시각의 모든 항목을 합산한다. 이 합이 사건 하나이다. 파이프라인은 그 사건에 범위를 적용한다. 그 다음에 그 시간의 사건을 합산한다.

| 변수 | 의미 | 단위 | MIMIC 테이블 | Itemid | 시간별 규칙 | 허용 범위 |
| --- | --- | --- | --- | --- | --- | --- |
| `hr` | 심박수 | bpm | chartevents | 220045 | mean | 20~300 |
| `sbp` | 수축기 혈압(비침습과 동맥을 합산) | mmHg | chartevents | 220179, 220050 | mean | 40~300 |
| `dbp` | 이완기 혈압(비침습과 동맥을 합산) | mmHg | chartevents | 220180, 220051 | mean | 10~200 |
| `mbp` | 평균 혈압(비침습과 동맥을 합산) | mmHg | chartevents | 220181, 220052 | mean | 20~250 |
| `rr` | 호흡수 | /min | chartevents | 220210 | mean | 2~80 |
| `temp_c` | 체온(화씨는 (F - 32) x 5 / 9로 변환) | °C | chartevents | 223762 (섭씨), 223761 (화씨) | mean | 25~45 |
| `weight_daily` | 일일 체중 | kg | chartevents | 224639 | mean | 20~400 |
| `dial_blood_flow` | 투석 혈류량 | mL/min | chartevents | 224144 | mean | 0~600 |
| `dialysate_rate` | 투석액 유량 | mL/h | chartevents | 224154 | mean | 0~10000 |
| `ultrafiltrate_ml` | 한외여과량 | mL | chartevents | 226457 | sum | 0~5000 |
| `creatinine` | 혈청 크레아티닌 | mg/dL | labevents | 50912 | mean | 0.1~30 |
| `creatinine_wb` | 전혈 크레아티닌(혈액가스) | mg/dL | labevents | 52024 | mean | 0.1~30 |
| `bun` | 혈액요소질소 | mg/dL | labevents | 51006 | mean | 1~300 |
| `urine_creat` | 소변 크레아티닌 | mg/dL | labevents | 51082 | mean | 1~1500 |
| `na` | 나트륨(화학검사와 전혈을 합산) | mEq/L | labevents | 50983, 50824 | mean | 100~180 |
| `k` | 칼륨(화학검사와 전혈을 합산) | mEq/L | labevents | 50971, 50822 | mean | 1.5~9 |
| `cl` | 염소(화학검사와 전혈을 합산) | mEq/L | labevents | 50902, 50806 | mean | 60~140 |
| `hco3` | 중탄산염(화학검사와 계산값을 합산) | mEq/L | labevents | 50882, 50803 | mean | 3~60 |
| `phosphate` | 인산염 | mg/dL | labevents | 50970 | mean | 0.3~20 |
| `mg` | 마그네슘 | mg/dL | labevents | 50960 | mean | 0.3~10 |
| `uric_acid` | 요산 | mg/dL | labevents | 51007 | mean | 0.5~30 |
| `urine_ml` | 소변량 | mL | outputevents | 226559, 226560, 226561, 226567, 226563, 226564, 226565, 226627, 226631 | sum | 0~5000 |
| `drain_ml` | 배액량 | mL | outputevents | 38 개 항목(코드 설정에 목록 있음) | sum | 0~5000 |
| `stool_ml` | 대변량(장루 포함) | mL | outputevents | 226579, 226580, 226582, 226583 | sum | 0~5000 |
| `other_output_ml` | 기타 배출량: 소변, 배액, 대변, 제외 항목이 아닌 모든 배출 항목 | mL | outputevents | 나머지 모든 항목 | sum | 0~5000 |

소변 항목: 226559, 226560, 226561, 226567, 226563, 226564, 226565, 226627, 226631. 파이프라인은 226626, 226629, 227510, 227511, 227488, 226633, 227489을 배출량으로 세지 않는다(입실 전 배출량, 세척액, 출혈량, 경관영양 잔여량).

#### 4.4 파생 시간별 변수

| 변수 | 유도 방법 |
| --- | --- |
| `intake_ml` | `inputevents`의 단위가 mL이고 양이 0 초과 10000 mL 이하인 기록. 파이프라인은 기록의 양을 [`intime`, time zero)와 겹치는 시간들에 나누어 배분한다. 한 시간의 몫은 (그 시간의 겹치는 시간) / (기록의 전체 지속 시간)이다. 지속 시간이 없는 기록은 시작 시간에 모두 들어간다. 시간별 값은 몫의 합이다. |
| `urine_ml_kg_h` | mL/kg/h 단위의 소변량 속도. 직전 기록과의 간격이 1초 이상 6시간 이하인 기록만 사용한다. 파이프라인은 기록의 소변량을 그 간격이 걸친 시간들에 겹치는 시간에 비례해 배분한다. 시간별 속도는 (배분한 소변량) / `weight_kg` / (덮은 시간, 시간 단위)이다. 한 시간에 최소 30분이 덮여야 한다. 0~20 밖의 속도는 제거한다. |
| `vasopressor_active` | `inputevents`의 승압제 주입(itemid 221289, 221662, 221749, 221906, 222315, 229617, 229630, 229631, 229632, 229709, 229764)이 그 시간을 덮으면 1. 정확히 시간 시작에 끝나는 주입도 그 시간을 표시한다. 아니면 0. |
| `dialysis_active` | `procedureevents`의 투석 세션(itemid 225441, 225802, 225805)이 그 시간을 덮으면 1(`vasopressor_active`와 같은 규칙). 아니면 0. |
| `crrt_active` | `dialysis_active`와 같고, itemid 225802(CRRT)만 사용한다. |
| `egfr_mdrd` | `175 x 크레아티닌^-1.154 x 나이^-0.203 x 0.742(여성이면)`, 단위 mL/min/1.73 m2. 크레아티닌은 시간별 값이고 나이는 `age_at_icu`이다. 인종 항은 없다. |
| `egfr_cg` | Cockcroft-Gault: `(140 - 나이) x weight_kg / (72 x 크레아티닌) x 0.85(여성이면)`, 단위 mL/min. |
| `egfr_ckdepi` | CKD-EPI 2021: `142 x min(Scr/k, 1)^a x max(Scr/k, 1)^-1.200 x 0.9938^나이 x 1.012(여성이면)`. Scr은 시간별 크레아티닌이다. k = 0.7(여성) 또는 0.9(남성). a = -0.241(여성) 또는 -0.302(남성). 인종 항은 없다. |

eGFR 변수 세 개는 크레아티닌 값이 있는 시간에만 값이 있다(`egfr_cg`는 `weight_kg`도 필요하다). 이 변수에는 `_obs`와 `_hsl`이 없다. wide 테이블에는 `_min`, `_max`, `_mean`, `_first`, `_last`가 있다.

#### 4.5 정적 피처와 파생 칼럼(wide 테이블)

| 칼럼 | 유도 방법 |
| --- | --- |
| `stay_id`, `subject_id`, `hadm_id`, `intime`, `anchor_year_group`, `gender`, `first_careunit`, `admission_type`, `hospital_expire_flag` | MIMIC-IV 칼럼. `icustays`, `patients`, `admissions`에서 그대로 복사한다. |
| `time_zero` | `intime` + 48시간. |
| `age_at_icu` | `patients.anchor_age` + (`intime`의 연도 - `patients.anchor_year`). |
| `weight_kg`, `weight_src` | 다음 순서로 처음 사용 가능한 출처의 가장 이른 기록 값: itemid 226512(kg), 226531(파운드 x 0.45359237), 224639(일일, kg). time zero 이전에 기록했고 20~400 kg인 값만 사용한다. `weight_src`는 `admission_kg`, `admission_lbs`, `daily` 중 하나이다. |
| `esrd_icd_current_adm` | 이번 입원의 `diagnoses_icd`에 ICD-10 코드 N186, Z992 또는 ICD-9 코드 5856, V451, V4511가 있으면 1. 병원이 이 코드를 퇴원 시 부여한다. |
| `esrd_icd_prior_adm` | 같은 환자의 이전 입원(더 이른 `admittime`)에 같은 코드가 있으면 1. |
| `dialysis_hx_item` | 입실의 `chartevents`에 itemid 225126의 값이 1이고 time zero 이전에 기록했으면 1. |
| `esrd_chronic_dialysis` | `esrd_icd_current_adm` 또는 `esrd_icd_prior_adm` 또는 `dialysis_hx_item`. 입실을 거르는 데 쓴다. 퇴원 시 부여한 정보를 포함하므로 모델 입력이 아니다. |
| `esrd_known_at_t0` | `esrd_icd_prior_adm` 또는 `dialysis_hx_item`. time zero에 알 수 있다. 모델 입력으로 사용한다. |
| `ckd_icd_current_adm`, `ckd_icd_prior_adm` | `diagnoses_icd`에 N18로 시작하는 ICD-10 코드(N186 제외) 또는 ICD-9 코드 5851, 5852, 5853, 5854, 5855, 5859가 이번 입원(current) 또는 이전 입원(prior)에 있으면 1. |
| `creat_baseline_7d`, `creat_last_pre_icu` | `labevents` itemid 50912(0.1~30 mg/dL, time zero까지 저장)에서 기록 시각이 `intime` 7일 전부터 time zero까지인 값. `creat_baseline_7d`는 최저값이고 `creat_last_pre_icu`는 `intime` 이전의 마지막 값이다. |
| `n_dialysis_sessions_before_t0`, `first_dialysis_hour` | time zero 이전에 시작한 `procedureevents` 행(itemid 225441, 225802, 225805)의 수와 `intime`부터 가장 이른 시작 시각까지의 시간(없으면 비어 있음). |
| `vasopressor_hours`, `dialysis_hours`, `crrt_hours` | 48시간 동안 `vasopressor_active`, `dialysis_active`, `crrt_active`의 합. |
| `rrt_before_t0` | 입실의 첫 투석 세션(같은 itemid)이 time zero 이전 또는 같은 시각에 시작하면 1. |
| `urine_ml_kg_h_overall` | (유효한 기록의 소변량 합, `urine_ml_kg_h` 참고) / `weight_kg` / (그 간격의 합, 시간 단위). 20을 넘는 값은 결측으로 바꾼다. |
| `fluid_balance_ml` | `intake_ml_total` - `urine_ml_total` - `drain_ml_total` - `stool_ml_total` - `other_output_ml_total`(없는 배출량 합은 0으로 센다). 섭취 값이나 소변 값이 없으면 비어 있다. |
| `label_aki_next_24h`, `aki_by_creat`, `aki_by_uo` | 라벨(3절). `aki_by_creat`는 기준 1 또는 2로 처음 시작한 시점이 예측 구간 안에 있으면 1. `aki_by_uo`는 기준 3(조건 (b) 포함)으로 처음 시작한 시점이 예측 구간 안에 있으면 1. 둘 중 하나가 1이면 라벨은 1이다. |
| `onset_aki_hour`, `onset_creat_hour`, `onset_uo_hour`, `onset_uo_reference_hour` | `intime`부터 입실 전체에서 첫 AKI 시작까지의 시간: 모든 기준, 기준 1과 2, 기준 3, 기준 소변량 규칙 각각의 값. 없으면 비어 있다. 이 칼럼은 time zero 이후의 정보를 담으므로 모델 입력이 아니다. |
| `n_kidney_relevant_classes` | 값이 1인 신장 관련 약물 플래그(4.6절)의 수. |

#### 4.6 약물 피처(wide 테이블)

1. **처방.** `prescriptions`의 처방은 시작 시각이 time zero 이전이면 사용한다. 중단 시각은 `intime`보다 앞서면 안 된다. 중단 시각이 없으면 시작 시각이 대신한다. 파이프라인은 `hadm_id`로 처방을 입실에 연결한다.
2. **약물 분류.** 스크립트 06은 미국 국립의학도서관의 RxNav 서비스로 각 처방을 ATC 분류에 매핑한다: NDC 코드 -> RxNorm 제품 -> 성분 -> ATC 분류(1~4단계). NDC 코드 4,856개 중 3,010개가 매핑된다. 나머지 처방은 약물 이름으로 찾는다. 이름 1,655개 중 882개가 정확히 일치하고 493개가 근사 일치한다. 근사 일치는 순위가 1이어야 하고 이름의 첫 단어가 일치한 이름에 있어야 한다. NDC 결과가 이름 결과보다 우선한다. 데이터 세트 입실에서 time zero 이전에 시작한 처방 580,873건의 79.7%에 ATC 분류가 있다.
3. **경로 필터.** 파이프라인은 처방의 경로에 맞지 않는 ATC 코드를 버린다. 피부, 안과, 귀 경로는 ATC 그룹 D와 S만 유지한다. 그 밖의 경로는 D와 S를 버린다. 그 밖의 경로는 장내 항감염제 A07을 경구 경로에서만 유지한다.

**신장 관련 플래그**(초안 목록, 일치하는 처방이 하나 이상 있으면 1). 항생제와 항바이러스제는 정맥 처방(경로 `IV`, 아미노글리코시드는 `IM`도)만 인정한다.

| 칼럼 | 일치 규칙 | 경로 규칙 |
| --- | --- | --- |
| `atc_J01G_aminoglycoside` | ATC 코드가 다음으로 시작: J01G | 정맥 또는 근육 |
| `atc_J01XA_vancomycin` | ATC 코드가 다음으로 시작: J01XA | 정맥 |
| `drug_pip_tazo` | 성분 이름이 다음을 포함: piperacillin | 정맥 |
| `atc_J01XB_polymyxin` | ATC 코드가 다음으로 시작: J01XB | 정맥 |
| `atc_J02AA_amphotericin` | ATC 코드가 다음으로 시작: J02AA | 정맥 |
| `atc_J05AB_nucleoside_antiviral` | ATC 코드가 다음으로 시작: J05AB | 정맥 |
| `atc_M01A_nsaid` | ATC 코드가 다음으로 시작: M01A | 제한 없음 |
| `atc_C03C_loop_diuretic` | ATC 코드가 다음으로 시작: C03C | 제한 없음 |
| `atc_C09_ace_arb` | ATC 코드가 다음으로 시작: C09 | 제한 없음 |
| `atc_L04AD_calcineurin` | ATC 코드가 다음으로 시작: L04AD | 제한 없음 |

**ATC 3단계 플래그** `atc3_<코드>`: 처방의 ATC 코드가 `<코드>`의 4글자로 시작하면 1. 전체 입실의 1% 이상에 처방이 있는 분류마다 플래그를 만든다(124개): A01A, A02A, A02B, A03B, A03F, A04A, A06A, A07A, A07D, A07E, A08A, A10A, A10B, A11C, A11D, A11G, A11H, A12A, A12B, A12C, B01A, B02B, B03A, B03B, B05B, B05C, B05X, C01A, C01B, C01C, C01D, C01E, C02A, C02D, C03A, C03B, C03C, C03D, C05A, C05B, C07A, C07F, C08C, C08D, C09A, C09B, C09C, C09D, C09X, C10A, C10B, D01A, D04A, D06A, D07A, D07X, D10A, D11A, G01A, G02C, G04B, G04C, H01B, H01C, H02A, H03A, H04A, J01A, J01C, J01D, J01E, J01F, J01G, J01M, J01R, J01X, J02A, J05A, L04A, M01A, M02A, M03A, M03B, M04A, N01A, N01B, N02A, N02B, N02C, N03A, N04B, N05A, N05B, N05C, N06A, N06B, N06D, N07A, N07B, P01A, P01B, R01A, R01B, R02A, R03A, R03B, R03C, R03D, R05C, R05D, R06A, S01A, S01B, S01C, S01E, S01G, S01H, S02A, S02B, S02D, S03A, V03A, V04C, V06D.

#### 4.7 분할(`splits` 테이블)

각 분할은 한 환자(`subject_id`)의 모든 입실을 같은 부분에 넣는다.

| 칼럼 | 정의 | 학습 | 검증 | 테스트 |
| --- | --- | --- | --- | --- |
| `split_random` | 환자 단위 무작위 70/15/15 %, 환자의 라벨 1 입실 유무로 층화(기본값) | 7,689 (15.8%) | 1,653 (15.7%) | 1,658 (15.7%) |
| `split_temporal` | `anchor_year_group` 기준: 학습 2008-2010, 2011-2013, 2014-2016; 검증 2017-2019; 테스트 2020-2022 | 6,949 (18.2%) | 2,255 (11.2%) | 1,796 (12.0%) |
| `split_hybrid` | 테스트 = 가장 최근 연도 그룹. 이전 연도는 환자 단위 무작위로 학습 85%, 검증 15% | 7,836 (16.5%) | 1,368 (16.6%) | 1,796 (12.0%) |

괄호의 숫자는 라벨 1의 비율이다. 무작위 분할의 시드는 42이다.

### 5. 알려진 한계

- **선택 효과.** 데이터 세트는 재원 48시간 이상이고 time zero 이전에 AKI가 없는 입실만 유지한다. 모델은 그런 환자에게만 적용된다.
- **소변량 기준과 기록 빈도.** 소변량 기준은 기록 간격이 2시간 이하여야 한다. 소변 기록이 드문 입실은 이 기준에 도달할 수 없다. `_n_hours_obs` 칼럼은 기록 빈도를 나타내므로 임상과 무관한 이유로 라벨을 예측할 수 있다.
- **약물 데이터.** `prescriptions`에는 처방이 있고 실제 투여 용량은 없다. 정맥 조영제도 없다. 약물 목록은 임상팀이 아직 검토하지 않은 초안이다.
- **허용 범위**는 임상팀이 아직 검토하지 않은 초안이다.
- **퇴원 코드.** 칼럼 `esrd_icd_current_adm`, `ckd_icd_current_adm`, `esrd_chronic_dialysis`는 병원이 퇴원 시 부여하는 ICD 코드를 담는다. 모델 입력으로 사용하지 마십시오. 칼럼 `label_*`, `aki_by_*`, `onset_*`, `hospital_expire_flag`는 결과 정보를 담으므로 모델 입력이 아니다.
- **단일 병원.** MIMIC-IV는 한 병원의 데이터이다. 이 데이터 세트에는 외부 검증이 없다.
- **eGFR**에는 인종 항이 없다.

### 부록: 전체 칼럼

**hourly 테이블(89칼럼).**

```text
stay_id, hour, hr, sbp, dbp, mbp, rr, temp_c, weight_daily, dial_blood_flow, dialysate_rate, ultrafiltrate_ml, creatinine, creatinine_wb, bun, urine_creat, na, k, cl, hco3, phosphate, mg, uric_acid, urine_ml, drain_ml, stool_ml, other_output_ml, intake_ml, urine_ml_kg_h, vasopressor_active, dialysis_active, crrt_active, egfr_mdrd, egfr_cg, egfr_ckdepi, hr_obs, sbp_obs, dbp_obs, mbp_obs, rr_obs, temp_c_obs, weight_daily_obs, dial_blood_flow_obs, dialysate_rate_obs, ultrafiltrate_ml_obs, creatinine_obs, creatinine_wb_obs, bun_obs, urine_creat_obs, na_obs, k_obs, cl_obs, hco3_obs, phosphate_obs, mg_obs, uric_acid_obs, urine_ml_obs, drain_ml_obs, stool_ml_obs, other_output_ml_obs, intake_ml_obs, urine_ml_kg_h_obs, hr_hsl, sbp_hsl, dbp_hsl, mbp_hsl, rr_hsl, temp_c_hsl, weight_daily_hsl, dial_blood_flow_hsl, dialysate_rate_hsl, ultrafiltrate_ml_hsl, creatinine_hsl, creatinine_wb_hsl, bun_hsl, urine_creat_hsl, na_hsl, k_hsl, cl_hsl, hco3_hsl, phosphate_hsl, mg_hsl, uric_acid_hsl, urine_ml_hsl, drain_ml_hsl, stool_ml_hsl, other_output_ml_hsl, intake_ml_hsl, urine_ml_kg_h_hsl
```

**wide 테이블(350칼럼).**

```text
stay_id, subject_id, hadm_id, intime, time_zero, anchor_year_group, age_at_icu, gender, first_careunit, admission_type, weight_kg, weight_src, esrd_chronic_dialysis, esrd_known_at_t0, esrd_icd_current_adm, esrd_icd_prior_adm, dialysis_hx_item, ckd_icd_prior_adm, ckd_icd_current_adm, creat_baseline_7d, creat_last_pre_icu, n_dialysis_sessions_before_t0, first_dialysis_hour, atc_J01G_aminoglycoside, atc_J01XA_vancomycin, drug_pip_tazo, atc_J01XB_polymyxin, atc_J02AA_amphotericin, atc_J05AB_nucleoside_antiviral, atc_M01A_nsaid, atc_C03C_loop_diuretic, atc_C09_ace_arb, atc_L04AD_calcineurin, atc3_A01A, atc3_A02A, atc3_A02B, atc3_A03B, atc3_A03F, atc3_A04A, atc3_A06A, atc3_A07A, atc3_A07D, atc3_A07E, atc3_A08A, atc3_A10A, atc3_A10B, atc3_A11C, atc3_A11D, atc3_A11G, atc3_A11H, atc3_A12A, atc3_A12B, atc3_A12C, atc3_B01A, atc3_B02B, atc3_B03A, atc3_B03B, atc3_B05B, atc3_B05C, atc3_B05X, atc3_C01A, atc3_C01B, atc3_C01C, atc3_C01D, atc3_C01E, atc3_C02A, atc3_C02D, atc3_C03A, atc3_C03B, atc3_C03C, atc3_C03D, atc3_C05A, atc3_C05B, atc3_C07A, atc3_C07F, atc3_C08C, atc3_C08D, atc3_C09A, atc3_C09B, atc3_C09C, atc3_C09D, atc3_C09X, atc3_C10A, atc3_C10B, atc3_D01A, atc3_D04A, atc3_D06A, atc3_D07A, atc3_D07X, atc3_D10A, atc3_D11A, atc3_G01A, atc3_G02C, atc3_G04B, atc3_G04C, atc3_H01B, atc3_H01C, atc3_H02A, atc3_H03A, atc3_H04A, atc3_J01A, atc3_J01C, atc3_J01D, atc3_J01E, atc3_J01F, atc3_J01G, atc3_J01M, atc3_J01R, atc3_J01X, atc3_J02A, atc3_J05A, atc3_L04A, atc3_M01A, atc3_M02A, atc3_M03A, atc3_M03B, atc3_M04A, atc3_N01A, atc3_N01B, atc3_N02A, atc3_N02B, atc3_N02C, atc3_N03A, atc3_N04B, atc3_N05A, atc3_N05B, atc3_N05C, atc3_N06A, atc3_N06B, atc3_N06D, atc3_N07A, atc3_N07B, atc3_P01A, atc3_P01B, atc3_R01A, atc3_R01B, atc3_R02A, atc3_R03A, atc3_R03B, atc3_R03C, atc3_R03D, atc3_R05C, atc3_R05D, atc3_R06A, atc3_S01A, atc3_S01B, atc3_S01C, atc3_S01E, atc3_S01G, atc3_S01H, atc3_S02A, atc3_S02B, atc3_S02D, atc3_S03A, atc3_V03A, atc3_V04C, atc3_V06D, n_kidney_relevant_classes, hr_min, hr_max, hr_mean, hr_first, hr_last, hr_n_hours_obs, sbp_min, sbp_max, sbp_mean, sbp_first, sbp_last, sbp_n_hours_obs, dbp_min, dbp_max, dbp_mean, dbp_first, dbp_last, dbp_n_hours_obs, mbp_min, mbp_max, mbp_mean, mbp_first, mbp_last, mbp_n_hours_obs, rr_min, rr_max, rr_mean, rr_first, rr_last, rr_n_hours_obs, temp_c_min, temp_c_max, temp_c_mean, temp_c_first, temp_c_last, temp_c_n_hours_obs, weight_daily_min, weight_daily_max, weight_daily_mean, weight_daily_first, weight_daily_last, weight_daily_n_hours_obs, dial_blood_flow_min, dial_blood_flow_max, dial_blood_flow_mean, dial_blood_flow_first, dial_blood_flow_last, dial_blood_flow_n_hours_obs, dialysate_rate_min, dialysate_rate_max, dialysate_rate_mean, dialysate_rate_first, dialysate_rate_last, dialysate_rate_n_hours_obs, ultrafiltrate_ml_total, ultrafiltrate_ml_n_hours_obs, creatinine_min, creatinine_max, creatinine_mean, creatinine_first, creatinine_last, creatinine_n_hours_obs, creatinine_wb_min, creatinine_wb_max, creatinine_wb_mean, creatinine_wb_first, creatinine_wb_last, creatinine_wb_n_hours_obs, bun_min, bun_max, bun_mean, bun_first, bun_last, bun_n_hours_obs, urine_creat_min, urine_creat_max, urine_creat_mean, urine_creat_first, urine_creat_last, urine_creat_n_hours_obs, na_min, na_max, na_mean, na_first, na_last, na_n_hours_obs, k_min, k_max, k_mean, k_first, k_last, k_n_hours_obs, cl_min, cl_max, cl_mean, cl_first, cl_last, cl_n_hours_obs, hco3_min, hco3_max, hco3_mean, hco3_first, hco3_last, hco3_n_hours_obs, phosphate_min, phosphate_max, phosphate_mean, phosphate_first, phosphate_last, phosphate_n_hours_obs, mg_min, mg_max, mg_mean, mg_first, mg_last, mg_n_hours_obs, uric_acid_min, uric_acid_max, uric_acid_mean, uric_acid_first, uric_acid_last, uric_acid_n_hours_obs, urine_ml_total, urine_ml_n_hours_obs, drain_ml_total, drain_ml_n_hours_obs, stool_ml_total, stool_ml_n_hours_obs, other_output_ml_total, other_output_ml_n_hours_obs, intake_ml_total, intake_ml_n_hours_obs, urine_ml_kg_h_min, urine_ml_kg_h_max, urine_ml_kg_h_mean, urine_ml_kg_h_first, urine_ml_kg_h_last, urine_ml_kg_h_n_hours_obs, egfr_mdrd_min, egfr_mdrd_max, egfr_mdrd_mean, egfr_mdrd_first, egfr_mdrd_last, egfr_cg_min, egfr_cg_max, egfr_cg_mean, egfr_cg_first, egfr_cg_last, egfr_ckdepi_min, egfr_ckdepi_max, egfr_ckdepi_mean, egfr_ckdepi_first, egfr_ckdepi_last, vasopressor_hours, dialysis_hours, crrt_hours, urine_ml_kg_h_overall, fluid_balance_ml, n_outlier_hr, n_outlier_sbp, n_outlier_dbp, n_outlier_mbp, n_outlier_rr, n_outlier_temp_c, n_outlier_weight_daily, n_outlier_creatinine, n_outlier_creatinine_wb, n_outlier_bun, n_outlier_urine_creat, n_outlier_na, n_outlier_k, n_outlier_cl, n_outlier_hco3, n_outlier_phosphate, n_outlier_mg, n_outlier_uric_acid, n_outlier_dial_blood_flow, n_outlier_dialysate_rate, n_outlier_ultrafiltrate_ml, n_outlier_urine_ml, n_outlier_drain_ml, n_outlier_stool_ml, n_outlier_other_output_ml, label_aki_next_24h, aki_by_creat, aki_by_uo, onset_aki_hour, onset_creat_hour, onset_uo_hour, onset_uo_reference_hour, rrt_before_t0, hospital_expire_flag
```
