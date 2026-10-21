# 파이프라인: 스크립트 실행 순서

`scripts/` 폴더에 파이프라인이 있다. 스크립트를 번호 순서로 실행하십시오. 프로젝트 루트에서 실행하십시오.

각 스크립트는 앞선 스크립트가 쓴 파일을 읽는다. 각 스크립트는 자신의 파일을 쓴다. 스크립트끼리 메모리의 데이터를 공유하지 않는다.

각 스크립트는 먼저 입력 파일이 있는지 확인한다. 파일이 없으면 스크립트가 멈춘다. 그리고 없는 파일의 이름을 출력한다. 그래서 너무 일찍 실행한 스크립트는 명확한 메시지와 함께 실패한다.

모든 파라미터는 `config.yaml`에 있다.

## 파이프라인 실행

MIMIC-IV 파일로 데이터 세트를 만들려면 다음 단계를 수행하십시오.

1. MIMIC-IV 3.1 CSV 파일을 `data/mimiciv/3.1`에 넣으십시오.
2. Python 3.12 환경에서 `requirements.txt`의 패키지를 설치하십시오. 노트북도 쓰려면 대신 `requirements-notebook.txt`를 설치하십시오.
3. `data/external/rxnav_cache.json`이 있으면 프로젝트에 넣으십시오.
4. `PY=.venv/bin/python bash scripts/run_all.sh`를 실행하십시오.

CSV 변환(스크립트 `01`)을 건너뛰려면 `SKIP_01=1`로 설정하십시오. 변환에는 약 20분이 걸린다.

## 의존 관계 그래프

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

## 입력과 출력

| 단계 | 스크립트 | 읽는 파일 | 쓰는 파일 | 실행 시간(대략) |
| --- | --- | --- | --- | --- |
| 01 | `01_csv_to_parquet.py` | `data/mimiciv/3.1`의 CSV 파일 | `data/mimiciv/3.1_parquet/` | 20분 |
| 02 | `02_build_base_cohort.py` | Parquet 테이블: icustays, patients, admissions | `base_cohort.parquet`, `flow_base.csv` | 수 초 |
| 03 | `03_add_esrd_flag.py` | `base_cohort`. Parquet 테이블: diagnoses_icd, admissions, chartevents | `cohort_stage2.parquet` | 수 초에서 1분 |
| 04 | `04_build_labels.py` | `cohort_stage2`. Parquet 테이블: labevents, chartevents, outputevents, procedureevents | `cohort_stage3.parquet` | 1~2분 |
| 05 | `05_build_final_cohort.py` | `cohort_stage3` | `cohort_final.parquet`, `flow_final.csv` | 수 초 |
| 06 | `06_build_drug_map.py` | `cohort_final`. Parquet 테이블: prescriptions. **인터넷**(NLM RxNav 서비스) | `data/external/drug_map.parquet`, `drug_map_info.json`, `rxnav_cache.json` | 처음에는 1시간, 캐시가 있으면 수 초 |
| 07 | `07_build_features.py` | `cohort_final`, `data/external/drug_map.parquet`(`06`의 결과). Parquet 테이블: labevents, chartevents, inputevents, outputevents, procedureevents, diagnoses_icd, admissions, prescriptions | `hourly.parquet`, `wide.parquet` | 1분 미만 |
| 08 | `08_build_splits.py` | `wide.parquet` | `splits.parquet` | 수 초 |
| 09 | `09_build_feature_dictionary.py` | `hourly`, `wide`, `splits` | `docs/feature_dictionary.md`, `docs/feature_dictionary_kr.md` | 수 초 |
| 10 | `10_build_default_features.py` | `hourly`, `wide` | `default_features.json` | 수 초 |
| 11 | `11_export_csv.py` | `cohort_final`, `drug_map`, `hourly`, `wide`, `splits` | `cohort_final.csv`, `wide.csv`, `splits.csv`, `drug_map.csv`, `hourly_example.csv` | 수 초 |
| 12 | `12_build_standalone_report.py` | `hourly`, `wide`, `splits`, 흐름 표, `drug_map_info.json`. Parquet 테이블: prescriptions | 프로젝트 루트의 `PREPROCESSING_REPORT.md` | 수 초 |

`data/cohort/`와 `data/features/` 아래의 경로는 프로젝트 루트 기준이다.

## 변경 후 다시 실행

변경 후에는 오른쪽 칸의 스크립트를 다시 실행하십시오. 순서대로 실행하십시오.

| 변경하는 것 | 실행할 스크립트 |
| --- | --- |
| CSV 파일, MIMIC 버전 또는 `mimic_tables` | `01`~`12` |
| 코호트 규칙(나이, 최소 재원 기간) 또는 `time_zero_hours` | `02`~`12` |
| ESRD 규칙(`config.yaml`의 `esrd_*`) | `03`~`12` |
| KDIGO 임계값, 소변량 규칙, 크레아티닌 또는 체중 범위, 라벨용 itemid | `04`~`12` |
| 예측 구간(`horizon_hours`), 제외 규칙, 크레아티닌 값의 최소 개수 | `04`~`12` |
| `plausible_ranges`, 피처의 itemid, `drugs.kidney_relevant`, 배출량 항목 목록 | `07`~`12` |
| `06`의 약물 조회 코드 또는 RxNorm 캐시 | `06`~`12` |
| 분할 시드, 분할 비율, 연도 그룹 | `08`, `09`, `11`, `12` |
| 기본 피처 목록이 제안하는 칼럼 | `10` |
| 피처 사전의 설명만 | `09` |
| CSV 사본을 만들 파일, 또는 예시의 크기 | `11` |
| 독립 보고서의 내용을 바꾸는 모든 변경 | `12` |

## 참고 사항

- 모든 스크립트에는 함수 `main()`이 있다. 스크립트는 직접 시작할 때만 실행한다. 스크립트를 import하면 아무것도 실행하지 않는다.
- 앞선 출력을 읽는 스크립트에는 함수 `check_inputs()`도 있다.
- 스크립트 `00_make_sample_csvs.py`는 선택 사항이다. 이 스크립트는 MIMIC-IV 파일의 작은 CSV 사본을 만든다. 사본은 훑어보기용이다. 다른 스크립트는 이 스크립트를 사용하지 않는다.
- 스크립트 `06`만 인터넷이 필요하다. 서비스는 시간이 지나며 바뀐다. 파일 `data/external/rxnav_cache.json`을 보관하고 파이프라인을 실행할 사람에게 전달하십시오. 캐시가 있으면 새로 실행해도 같은 매핑이 나온다. 캐시에는 MIMIC-IV 처방의 약물명과 NDC 코드가 들어 있으므로 공개 저장소에는 넣지 않는다.
- 소변량 간격 설정이 `config.yaml`에서 2시간이 아니면 스크립트 `05`가 멈춘다. 스크립트 `04`는 2시간 변형만 계산한다.
- 스크립트 `01`은 `config.yaml`의 `mimic_tables`에 있는 테이블만 변환한다. 스크립트 `09`도 같은 목록을 사용한다. 다른 테이블을 변환하려면 이름을 인수로 주십시오. 예: `python scripts/01_csv_to_parquet.py hosp/emar`. 인수는 기본 목록을 대체한다.
- 스크립트는 모든 코호트 테이블과 피처 테이블을 `stay_id` 순으로 정렬해서 쓴다. hourly 테이블은 `stay_id`와 `hour` 순이다. 행 순서는 실행할 때마다 같다.
- Parquet 파일의 부동소수점 수는 마지막 자릿수가 실행과 컴퓨터에 따라 다를 수 있다. CSV 사본은 숫자를 유효숫자 10자리로 반올림한다. 클린룸 테스트에서 CSV 사본은 같았다.
- 스크립트 `scripts/compare_runs.py`는 두 실행의 출력을 비교한다. `python scripts/compare_runs.py A B`로 사용하십시오. A와 B는 두 프로젝트 폴더이다. 이 스크립트는 Parquet 파일을 정렬하고, 부동소수점 수에 상대 허용 오차 1e-9를 사용한다.

## 재현성 테스트

테스트 날짜: 2026-10-12.

- 테스트는 프로젝트의 깨끗한 사본에서 스크립트 `02`~`12`을 다시 실행했다.
- 사본에는 코호트, 피처, 약물 맵 파일이 없었다. RxNav 캐시 파일만 있었다.
- 모든 출력이 기존 실행의 출력과 같았다.

테스트가 확인하지 않은 항목은 두 가지이다.

- 스크립트 `01`. 별도 검사가 행 수를 CSV 파일과 비교했다.
- 캐시 없이 스크립트 `06`을 온라인으로 새로 실행하는 경우.
