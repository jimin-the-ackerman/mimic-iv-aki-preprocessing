#!/usr/bin/env bash
# Run the whole pipeline in order, from the project root:  PY=.venv/bin/python bash scripts/run_all.sh
# SKIP_01=1 skips the CSV -> Parquet conversion (about 20 minutes) when the Parquet files already exist.
set -euo pipefail
PY="${PY:-python}"
for s in 01_csv_to_parquet 02_build_base_cohort 03_add_esrd_flag 04_build_labels 05_build_final_cohort 06_build_drug_map \
         07_build_features 08_build_splits 09_build_feature_dictionary 10_build_default_features 11_export_csv 12_build_standalone_report; do
  if [ "$s" = "01_csv_to_parquet" ] && [ "${SKIP_01:-0}" = "1" ]; then echo "== skip $s"; continue; fi
  echo "== $s  $(date +%H:%M:%S)"
  "$PY" -I "scripts/$s.py"
done
echo "== done  $(date +%H:%M:%S)"
