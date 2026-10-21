# 설치: 데이터, 환경, 출력 폴더

이 저장소에는 코드만 있다. MIMIC-IV 데이터는 없다. PhysioNet에서 MIMIC-IV 3.1을 받고(자격 인증 접근) 데이터 사용 약정을 지키십시오.

## 첫 실행 전의 폴더 구조

첫 스크립트를 실행하기 전에 프로젝트는 다음과 같아야 한다. 각 파일의 설명은 영문본 [setup.md](setup.md)와 같다.

```text
mimic-iv-aki-preprocessing/
├── README.md, LICENSE, config.yaml, PREPROCESSING_REPORT.md
├── requirements.txt, requirements-notebook.txt, .gitignore
├── notebooks/baseline_models.ipynb   (선택)
├── docs/                             (영문본과 _kr 국문본)
├── scripts/                          (00~12, compare_runs.py, make_share_zip.py, run_all.sh)
└── data/                             (저장소에 없음, 직접 만든다)
    ├── external/
    │   └── rxnav_cache.json          (선택, 06단계에서 약 1시간 절약)
    └── mimiciv/
        └── 3.1/
            ├── hosp/   admissions, d_icd_diagnoses, d_labitems, diagnoses_icd, labevents, patients, prescriptions (.csv)
            └── icu/    chartevents, d_items, icustays, inputevents, outputevents, procedureevents (.csv)
```

- 위의 CSV 13개가 파이프라인이 읽는 MIMIC-IV 파일의 전부이다. 약 68 GB를 쓴다. 파이프라인은 자체 파일을 위해 약 5 GB가 더 필요하다.
- 파일은 압축을 푼 `.csv`여야 한다. PhysioNet은 `.csv.gz` 파일을 제공하므로 먼저 압축을 푸십시오(예: `gunzip labevents.csv.gz`).
- 다른 MIMIC-IV 파일(예: `emar.csv`, `microbiologyevents.csv`)은 폴더에 있어도 된다. 파이프라인은 그 파일을 무시한다.
- `data/` 폴더는 `.gitignore`에 있다. 그 안의 어떤 파일도 저장소에 들어가지 않는다.

## 환경과 실행

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
PY=.venv/bin/python bash scripts/run_all.sh
```

노트북도 쓰려면 `requirements.txt` 대신 `requirements-notebook.txt`를 설치하십시오. 단계, 파일, 재현 방법은 [pipeline_kr.md](pipeline_kr.md)에 있다.

## 기준 모델 노트북

파이프라인 실행 후 `notebooks/baseline_models.ipynb`는 wide 테이블을 읽고, 몇 가지 그림을 그리고, 기준 분류기 세 개를 학습한다. 데이터 세트가 예측 모델을 뒷받침할 수 있는지 확인하는 용도이다. 프로젝트 폴더에서 이 프로젝트의 Python 환경으로 실행하십시오.

## 파이프라인이 만드는 폴더

| 폴더 | 내용 |
| --- | --- |
| `data/mimiciv/3.1_parquet/` | Parquet 테이블(01단계) |
| `data/mimiciv/3.1_sample/` | 선택 사항인 샘플 CSV 파일(스크립트 00) |
| `PREPROCESSING_REPORT.md` | 영문과 국문의 독립 보고서(12단계) |
| `data/cohort/` | 코호트 파일과 흐름 표 |
| `data/features/` | hourly 테이블과 wide 테이블, 분할, 기본 피처 목록, CSV 사본 |
| `data/external/` | 약물 맵(RxNav 캐시를 넣었다면 이미 있다) |

## 공유

MIMIC-IV 데이터는 제한된 데이터이다. 코드만 공유하십시오. `python scripts/make_share_zip.py`는 코드, 문서, 노트북, 설정을 담고 데이터는 담지 않은 `mimic_iv_aki_preprocessing.zip`을 만든다. `--with-cache`를 붙이면 RxNav 캐시도 포함한다(MIMIC-IV 처방의 약물명과 NDC 코드가 들어 있다). 로컬 경로, 이메일 주소, 노트북 출력이 있으면 스크립트는 멈춘다.
