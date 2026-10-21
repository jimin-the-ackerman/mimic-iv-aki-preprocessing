# MIMIC-IV item numbers used by the pipeline

This document lists the MIMIC-IV item numbers (itemids) that the pipeline uses. It also maps each item group to the variable names in the feature tables. The version of MIMIC-IV is 3.1. Each itemid exists in the table `d_items` or the table `d_labitems`. The counts come from the Parquet tables. The machine-readable list is in `config.yaml` (key `itemids`).

## How to look up a column

1. Take the base name of the column. Remove the suffix (`_min`, `_max`, `_mean`, `_first`, `_last`, `_total`, `_obs`, `_hsl`, `_n_hours_obs`) and the prefix `n_outlier_`.
2. Find the base name in the column "Variable names" below.
3. Read the table and the itemids in the same row.

The feature dictionary describes each column. For a column that is not in this table, its description names the MIMIC-IV source.

| Group | Variable names | Table | Itemids |
| --- | --- | --- | --- |
| Creatinine | `creatinine`, `creatinine_wb` | labevents | 50912 (blood, 4.3 million rows), 52024 (whole blood) |
| Blood urea nitrogen (BUN) | `bun` | labevents | 51006 |
| Urine creatinine | `urine_creat` | labevents | 51082 (about 51,000 admissions) |
| Sodium, potassium, chloride | `na`, `k`, `cl` | labevents | 50983, 50971, 50902. Whole-blood versions: 50824, 50822, 50806 |
| Bicarbonate (HCO3) | `hco3` | labevents | 50882. The backup is 50803 (calculated) |
| Phosphate, magnesium, uric acid | `phosphate`, `mg`, `uric_acid` | labevents | 50970, 50960, 51007 |
| Heart rate | `hr` | chartevents | 220045 |
| Systolic, diastolic and mean blood pressure | `sbp`, `dbp`, `mbp` | chartevents | Non-invasive: 220179, 220180, 220181. Arterial: 220050, 220051, 220052 |
| Respiratory rate | `rr` | chartevents | 220210 |
| Temperature | `temp_c` | chartevents | 223762 (Celsius), 223761 (Fahrenheit, converted to Celsius) |
| Weight | `weight_kg` (admission weight), `weight_daily` | chartevents | 226512 (admission, kg), 226531 (admission, pounds, converted to kg), 224639 (daily, kg) |
| Urine output (catheters and voiding) | `urine_ml`, `urine_ml_kg_h` | outputevents | 226559 Foley, 226560 Void, 226561 Condom Cath, 226567 Straight Cath, 226563 Suprapubic |
| Urine output (other sources) | `urine_ml`, `urine_ml_kg_h` | outputevents | 226564 and 226565 Nephrostomy (right and left), 226627 OR Urine, 226631 PACU Urine |
| Drain output | `drain_ml` | outputevents | Chest tubes, Jackson-Pratt drains, wound vacuum, cerebrospinal fluid, pleural fluid and ascites tap |
| Stool output | `stool_ml` | outputevents | 226579, 226580, 226582, 226583 |
| Other output | `other_output_ml` | outputevents | All other items, for example gastric tubes, vomit, ileoconduit, ureteral stents and cath lab |
| Not counted as output | no variable | outputevents | 226633 Pre-Admission, 227489 and 227488 GU Irrigant, 226626 and 226629 blood loss, 227510 and 227511 tube-feed residual |
| Fluid and infusion intake | `intake_ml` | inputevents | All items with the unit mL |
| Vasopressor infusions | `vasopressor_active` | inputevents | 221289, 221662, 221749, 221906, 222315, 229617, 229630, 229631, 229632, 229709, 229764 |
| Dialysis sessions | `dialysis_active`, `crrt_active` | procedureevents | 225441 hemodialysis (2,746 stays), 225802 CRRT (2,274 stays), 225805 peritoneal dialysis (180 stays) |
| Dialysis settings | `dial_blood_flow`, `dialysate_rate`, `ultrafiltrate_ml` | chartevents | 224144 blood flow, 224154 dialysate rate, 226457 ultrafiltrate output |
| Dialysis history | `dialysis_hx_item` | chartevents | 225126 ("Dialysis patient") |

## Items that the pipeline does not use

- The eGFR values that the laboratory reports: 50920 (MDRD), 52026, 53161 and 53180. The laboratory stores the result of 50920 only as free text.
- The dialysate fluid items 225977 and 230085. They hold text values.

## Notes on items

- `d_labitems` has no item for cystatin C.
- The items CVVHD (225803), CVVHDF (225809) and SCUF (225955) have no rows in `procedureevents`.
- Some laboratory itemids have 0 admissions (for example 52546 and 52535). These items are outside the hospital stays.
- The exact itemid lists are in `config.yaml`.
