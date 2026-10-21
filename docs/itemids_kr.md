# 파이프라인이 사용하는 MIMIC-IV 항목 번호

이 문서는 파이프라인이 사용하는 MIMIC-IV 항목 번호(itemid)를 나열한다. 그리고 각 항목 그룹을 피처 테이블의 변수 이름에 연결한다. MIMIC-IV 버전은 3.1이다. 각 itemid는 `d_items` 테이블 또는 `d_labitems` 테이블에 있다. 개수는 Parquet 테이블에서 센 값이다. 기계가 읽는 목록은 `config.yaml`(키 `itemids`)에 있다.

## 칼럼 찾는 방법

1. 칼럼의 기본 이름을 구하십시오. 접미사(`_min`, `_max`, `_mean`, `_first`, `_last`, `_total`, `_obs`, `_hsl`, `_n_hours_obs`)와 접두사 `n_outlier_`를 떼십시오.
2. 아래 표의 "변수 이름" 칸에서 그 기본 이름을 찾으십시오.
3. 같은 행의 테이블과 itemid를 읽으십시오.

피처 사전은 각 칼럼을 설명한다. 이 표에 없는 칼럼은 설명에 MIMIC-IV 출처가 있다.

| 그룹 | 변수 이름 | 테이블 | Itemid |
| --- | --- | --- | --- |
| 크레아티닌 | `creatinine`, `creatinine_wb` | labevents | 50912(혈액, 430만 행), 52024(전혈) |
| 혈액요소질소(BUN) | `bun` | labevents | 51006 |
| 소변 크레아티닌 | `urine_creat` | labevents | 51082(입원 약 51,000건) |
| 나트륨, 칼륨, 염소 | `na`, `k`, `cl` | labevents | 50983, 50971, 50902. 전혈 버전: 50824, 50822, 50806 |
| 중탄산염(HCO3) | `hco3` | labevents | 50882. 대체 항목은 50803(계산값) |
| 인산염, 마그네슘, 요산 | `phosphate`, `mg`, `uric_acid` | labevents | 50970, 50960, 51007 |
| 심박수 | `hr` | chartevents | 220045 |
| 수축기, 이완기, 평균 혈압 | `sbp`, `dbp`, `mbp` | chartevents | 비침습: 220179, 220180, 220181. 동맥: 220050, 220051, 220052 |
| 호흡수 | `rr` | chartevents | 220210 |
| 체온 | `temp_c` | chartevents | 223762(섭씨), 223761(화씨, 섭씨로 변환) |
| 체중 | `weight_kg`(입실 시 체중), `weight_daily` | chartevents | 226512(입실 시, kg), 226531(입실 시, 파운드, kg으로 변환), 224639(일일, kg) |
| 소변량(도뇨관과 배뇨) | `urine_ml`, `urine_ml_kg_h` | outputevents | 226559 Foley, 226560 Void, 226561 Condom Cath, 226567 Straight Cath, 226563 Suprapubic |
| 소변량(기타 경로) | `urine_ml`, `urine_ml_kg_h` | outputevents | 226564와 226565 Nephrostomy(오른쪽과 왼쪽), 226627 OR Urine, 226631 PACU Urine |
| 배액량 | `drain_ml` | outputevents | 흉관, Jackson-Pratt 배액관, 상처 진공 장치, 뇌척수액, 흉막액, 복수 천자 |
| 대변량 | `stool_ml` | outputevents | 226579, 226580, 226582, 226583 |
| 기타 배출량 | `other_output_ml` | outputevents | 나머지 모든 항목. 예는 위관, 구토, 회장도관, 요관 스텐트, 심혈관 조영실이다 |
| 배출량으로 세지 않는 항목 | 해당 변수가 없다 | outputevents | 226633 Pre-Admission, 227489와 227488 GU Irrigant, 226626과 226629 출혈량, 227510과 227511 경관영양 잔여량 |
| 수액과 주입액 섭취량 | `intake_ml` | inputevents | 단위가 mL인 모든 항목 |
| 승압제 주입 | `vasopressor_active` | inputevents | 221289, 221662, 221749, 221906, 222315, 229617, 229630, 229631, 229632, 229709, 229764 |
| 투석 세션 | `dialysis_active`, `crrt_active` | procedureevents | 225441 혈액투석(입실 2,746건), 225802 CRRT(입실 2,274건), 225805 복막투석(입실 180건) |
| 투석 설정값 | `dial_blood_flow`, `dialysate_rate`, `ultrafiltrate_ml` | chartevents | 224144 혈류량, 224154 투석액 유량, 226457 한외여과량 |
| 투석 문진 | `dialysis_hx_item` | chartevents | 225126("Dialysis patient") |

## 파이프라인이 사용하지 않는 항목

- 검사실이 보고한 eGFR 값: 50920(MDRD), 52026, 53161, 53180. 검사실은 50920의 결과를 자유 텍스트로만 저장한다.
- 투석액 항목 225977과 230085. 이 항목은 텍스트 값을 담는다.

## 항목에 관한 설명

- `d_labitems`에는 시스타틴 C 항목이 없다.
- 항목 CVVHD(225803), CVVHDF(225809), SCUF(225955)는 `procedureevents`에 행이 없다.
- 일부 검사 itemid는 입원 수가 0이다(예: 52546, 52535). 이 항목은 병원 재원 밖의 데이터이다.
- 정확한 itemid 목록은 `config.yaml`에 있다.
