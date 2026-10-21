# MIMIC-IV AKI Prediction Preprocessing Pipeline

*[English version here](README.md)*

본 프로젝트는 ICU 환자의 급성 신손상(AKI) 예측을 위해 MIMIC-IV 3.1로부터
모델 학습용 데이터 세트를 구축하는 전처리 파이프라인이다.

> ※ 본 저장소는 Korea Clinical Datathon(2026년 10월 16~18일) 팀 프로젝트 중
> 전처리 파트를 정리한 것입니다. 팀 주제는 "급성 신손상 예측 모델 개발: AI 에이전트가
> 예측 성능을 향상시킬 수 있을까?"였으며, MIMIC-IV 데이터를 사용하였습니다.
> 팀에서 데이터 전처리를 담당하였고, 팀의 모델링 및 AI 에이전트 실험은 포함하지 않았습니다.
> 파이프라인은 Ollama로 구동한 로컬 LLM을 코딩 보조로 활용하여 단독으로 구현하였으며,
> 예측 시점·예측 구간 등 일부 정의는 팀 내 임상 구성원의 요청을 반영하였습니다.

---

## 1. 개요

모델은 ICU 입실 후 첫 48시간의 데이터를 입력으로 받아, 이후 24시간 이내에
AKI(KDIGO 정의)가 시작하는지 예측한다.

| 항목 | 정의 |
| --- | --- |
| 단위 | ICU 입실(`stay_id`) |
| Time zero(예측 시점) | ICU 입실 시각(`intime`) + 48시간 |
| 입력 구간 | [`intime`, time zero) |
| 예측 구간 | time zero 이후 24시간 |
| 라벨 | `label_aki_next_24h`: 해당 입실의 첫 AKI가 예측 구간 안에서 시작 |

파이프라인은 동일한 코호트로부터 두 가지 테이블을 생성한다. 시퀀스 모델용
**hourly 테이블**과 표 형식 모델용 **wide 테이블**(입실당 1행)이다. 코호트
규칙, KDIGO 기준값, itemid, 허용 범위, 약물 분류, 분할 방식 등 모든
매개변수는 `config.yaml`에서 관리한다.

---

## 2. 전체 파이프라인

```
MIMIC-IV 3.1 CSV (13개 테이블)
    -> 01 CSV를 Parquet로 변환
    -> 02 기본 코호트 (R1-R3)
    -> 03 ESRD / 만성 투석 플래그
    -> 04 KDIGO 라벨 (크레아티닌 + 소변량), 체중, 측정 횟수
    -> 05 최종 코호트 (R4-R9)
    -> 06 약물 맵 (NDC -> RxNorm -> ATC, NLM RxNav 사용)
    -> 07 피처 생성 (hourly 테이블 + wide 테이블)
    -> 08 환자 단위 데이터 분할
    -> 09-12 Feature dictionary, 기본 피처 목록, CSV 사본, 보고서
```

각 스크립트는 이전 단계의 파일을 읽고, 입력 파일의 존재를 확인한 뒤, 자신의
출력 파일을 저장한다(`scripts/run_all.sh`; 의존 관계는 `docs/pipeline_kr.md` 참고).

### 2.1 Cohort
전체 ICU 입실 94,458건에서 시작하여 9개의 규칙을 순서대로 적용한다
(`docs/cohort_definition_kr.md`). 입원 중 첫 ICU 입실, 18세 이상, ICU 재원
48시간 이상, 체중 기록 존재, time zero 이전 크레아티닌 측정 2회 이상, time
zero 이전 AKI 없음, 결과 확인 가능, ESRD가 아닌 환자의 time zero 이전 ICU 내
투석 시작 없음, 라벨 0 입실의 예측 구간 내 데이터 존재가 그 규칙이다. ESRD 및
만성 투석 환자의 입실은 제외하지 않고 플래그(`esrd_chronic_dialysis`)로
표시한다.

### 2.2 KDIGO Labels
세 가지 KDIGO 기준 중 하나가 처음 참이 되는 시점을 AKI 시작으로 정의한다
(`scripts/04_build_labels.py`):

- **크레아티닌, 48시간:** 직전 48시간 내 가장 낮은 이전 값 대비 0.3 mg/dL
  이상 상승.
- **크레아티닌, 7일:** 직전 7일 내 가장 낮은 이전 값의 1.5배 이상. 크레아티닌
  시계열은 ICU 입실 7일 전부터 시작하며, ICU 입실 전 검사 중 일부는 `hadm_id`가
  없으므로 `subject_id`로 결합한다.
- **소변량:** 6시간 구간 동안 0.5 mL/kg/h 미만. 구간 내 기록 간격의 합이
  6시간 이상 12시간 미만이고 모든 기록 간격이 2시간 이하일 때만 유효한
  구간으로 본다. 기록이 없는 시간은 소변량 0으로 간주하지 않는다.

각 기준의 시작 시점을 따로 저장하므로, 다른 예측 구간에 대해서도 라벨을 다시
계산할 수 있다.

### 2.3 Features
- **정보 누수 방지.** 기록 시각과 저장 시각(`storetime`)이 모두 time zero
  이전인 측정값만 사용한다. 수액·약물 주입은 time zero에서 잘라낸다.
- **시간 단위 집계.** 활력징후, 검사값, 배출량, 섭취량, 소변량 속도, 승압제 및
  투석 여부, 세 가지 eGFR 공식(MDRD, Cockcroft-Gault, 인종 항이 없는
  CKD-EPI 2021)을 시간 단위로 집계한다.
- **허용 범위.** 설정된 범위를 벗어난 값은 결측으로 바꾸고,
  `n_outlier_<변수>`에 개수를 기록한다.
- **결측치.** 대치, 전방 채움, 0 채움을 하지 않는다. 각 시간별 변수에 관측
  마스크(`_obs`)와 마지막 측정 이후 경과 시간(`_hsl`)을 함께 제공한다.
- **모델 입력 제외 칼럼.** 퇴원 시 부여되는 ICD 코드와 결과 관련 칼럼은
  feature dictionary에 모델 입력 제외로 표시한다. 권장 입력 목록은
  `default_features.json`에 정리한다.

### 2.4 Drug Features
처방 데이터를 NLM RxNav 서비스를 통해 NDC → RxNorm 제품 → 성분 → ATC
분류로 매핑하며, NDC로 매핑되지 않는 경우 약물명의 정확 일치 및 근사 일치
검색을 사용한다(`scripts/06_build_drug_map.py`). 처방의 투여 경로와 맞지 않는
ATC 코드는 제외한다. wide 테이블에는 신장 관련 약물 플래그 10개(초안)와 ATC
3단계 플래그 124개가 있다.

### 2.5 Splits
모든 분할은 환자(`subject_id`) 단위로 수행한다. 라벨 1 입실 보유 여부로
층화한 70/15/15 무작위 분할(기본값), `anchor_year_group` 기준 연도별 분할,
가장 최근 연도 그룹을 테스트로 쓰는 혼합 분할의 세 가지를 제공한다.

### 2.6 Validation
- **재현성.** 깨끗한 프로젝트 복사본에서 02~12단계를 다시 실행하였고, 모든
  출력이 동일함을 확인하였다(`scripts/compare_runs.py`).
- **데이터 점검.** `notebooks/baseline_models.ipynb`는 세 가지 기준 분류기를
  학습하여 데이터 세트가 예측 모델을 뒷받침할 수 있는지 확인한다. 셔플 라벨
  대조 실험과, 임상적이지 않은 이유로 라벨을 예측할 수 있는 기록 빈도 피처에
  대한 점검을 포함한다.

---

## 3. 결과 데이터 세트

| 항목 | 값 |
| --- | --- |
| MIMIC-IV 3.1의 ICU 입실 | 94,458건 (65,366명) |
| 데이터 세트의 ICU 입실 | 11,000건 (10,211명) |
| 라벨 1 | 1,733건 (15.8%) |
| 크레아티닌 / 소변량 / 둘 다로 라벨 1 | 778 / 1,092 / 137 |
| hourly 테이블 | 528,000행 (11,000건 × 48시간), 89칼럼 |
| wide 테이블 | 11,000행, 350칼럼 |
| 나이 중앙값 / 여성 비율 | 66.0세 / 43.8% |

| 규칙 | 조건 | 남은 입실 | 남은 환자 |
| --- | --- | --- | --- |
| – | 전체 ICU 입실 | 94,458 | 65,366 |
| R1 | 입원 중 첫 ICU 입실 | 85,242 | 65,366 |
| R2 | 18세 이상 | 85,242 | 65,366 |
| R3 | ICU 재원 48시간 이상 | 40,746 | 34,348 |
| R4 | 체중 기록 존재 | 40,619 | 34,260 |
| R5 | time zero 이전 크레아티닌 2회 이상 | 39,697 | 33,567 |
| R6 | time zero 이전 AKI 없음 | 17,646 | 15,984 |
| R7 | 결과 확인 가능 | 11,136 | 10,332 |
| R8 | ESRD가 아닌 환자의 조기 투석 없음 | 11,086 | 10,286 |
| R9 | 라벨 0 입실의 예측 구간 내 데이터 존재 | 11,000 | 10,211 |

---

## 4. Repository Structure

```
mimic-iv-aki-preprocessing/
├── config.yaml                  파이프라인의 모든 매개변수
├── scripts/                     00-12단계, run_all.sh, compare_runs.py, make_share_zip.py
├── docs/                        정의, feature dictionary, itemid, 파이프라인, 노트 (영문 + _kr 국문)
├── notebooks/
│   └── baseline_models.ipynb    데이터 점검용 노트북 (출력 미포함)
├── PREPROCESSING_REPORT.md      12단계가 생성하는 독립 보고서 (영문 + 국문)
├── requirements.txt             파이프라인 패키지
└── requirements-notebook.txt    파이프라인 + 노트북 패키지
```

---

## 5. 재현 방법

### 5.1 데이터
MIMIC-IV 3.1은 [PhysioNet](https://physionet.org/content/mimiciv/3.1/)의 자격
인증을 거쳐 받을 수 있다. 압축을 푼 CSV 파일 13개를 `docs/setup_kr.md`에
설명한 위치에 둔다.

### 5.2 환경 설정

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

### 5.3 전체 파이프라인 실행

```bash
PY=.venv/bin/python bash scripts/run_all.sh
# Parquet 파일이 이미 있으면 SKIP_01=1로 CSV 변환 단계를 건너뛸 수 있다
```

06단계는 RxNav 서비스를 사용하므로 인터넷 연결이 필요하다(첫 실행 약 1시간,
캐시가 있으면 수 초). 설정 변경 후 다시 실행해야 하는 단계는
`docs/pipeline_kr.md`에 정리되어 있다.

---

## 6. 한계

- 데이터 세트는 ICU 재원 48시간 이상이고 time zero 이전에 AKI가 없는 입실만
  포함한다.
- 소변량 기준은 기록 간격이 2시간 이하여야 하므로, 소변량 기록이 드문 입실은
  이 기준을 충족할 수 없다.
- `prescriptions` 테이블은 실제 투여량이 아닌 처방 기록이며, 정맥 조영제
  정보를 포함하지 않는다.
- 허용 범위와 신장 관련 약물 목록은 임상팀의 검토를 거치지 않은 초안이다.
- MIMIC-IV는 단일 병원 데이터이며, 외부 검증은 수행하지 않았다.

---

## 7. 관련 문서

- [`docs/index_kr.md`](docs/index_kr.md): 전체 문서 목차와 읽는 순서
- [`docs/cohort_definition_kr.md`](docs/cohort_definition_kr.md): 과제, 입실
  규칙, 라벨, 피처 규칙, 분할
- [`docs/preprocessing_notes_kr.md`](docs/preprocessing_notes_kr.md): 단계별
  건수, 결정 사항과 근거, 한계, 남은 과제
- [`docs/feature_dictionary_kr.md`](docs/feature_dictionary_kr.md): hourly
  테이블과 wide 테이블의 모든 칼럼 설명
- [`docs/itemids_kr.md`](docs/itemids_kr.md): 사용한 MIMIC-IV itemid
- [`docs/pipeline_kr.md`](docs/pipeline_kr.md): 스크립트 실행 순서, 입출력,
  변경 후 재실행 단계
- [`docs/setup_kr.md`](docs/setup_kr.md): 데이터 배치, 환경 설정, 출력 폴더
- [`PREPROCESSING_REPORT.md`](PREPROCESSING_REPORT.md): 모든 정의와 수치를
  담은 독립 보고서 (후반부가 국문)

---

## 8. 데이터 사용 및 라이선스

본 저장소에는 코드와 문서만 포함되어 있으며, MIMIC-IV 데이터나 이로부터
파생된 환자 단위 데이터는 포함하지 않는다. MIMIC-IV의 사용은 PhysioNet의
자격 인증 데이터 사용 약정을 따른다. 코드는 [MIT License](LICENSE)로
공개한다.

---

## 9. Author

Jimin (jimin-the-ackerman)
