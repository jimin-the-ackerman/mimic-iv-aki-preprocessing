# 문서 목차

이 폴더는 MIMIC-IV 3.1에서 만든 전처리 데이터 세트를 설명한다. 이 데이터 세트는 중환자실의 급성 신손상(AKI) 예측을 지원한다.

모든 문서는 초안이다. 임상팀이 문서를 검토해야 한다. 남은 항목은 `preprocessing_notes_kr.md`에 있다.

## 문서 규칙

각 사실은 한 문서에만 있다. 다른 문서는 그 사실이 있는 문서로 연결한다. 같은 사실을 반복하지 않는다.

## 질문별 문서

| 질문 | 문서 |
| --- | --- |
| 데이터를 어떻게 준비하고, 환경을 설치하고, 파이프라인을 실행하는가? | [setup_kr.md](setup_kr.md) |
| 데이터 세트에 무엇이 있는가? 입실, 라벨, 피처, 분할의 규칙은 무엇인가? | [cohort_definition_kr.md](cohort_definition_kr.md) |
| 각 칼럼은 무엇을 뜻하는가? | [feature_dictionary_kr.md](feature_dictionary_kr.md) |
| 파이프라인은 MIMIC-IV의 어떤 항목 번호를 사용하는가? | [itemids_kr.md](itemids_kr.md) |
| 스크립트는 어떤 순서로 실행하는가? 어떻게 실행하는가? 변경 후에 무엇을 다시 실행하는가? | [pipeline_kr.md](pipeline_kr.md) |
| 파이프라인은 데이터 세트를 어떻게 만들었는가? 이유는 무엇인가? 입실이 몇 건 남았는가? 한계와 남은 항목은 무엇인가? | [preprocessing_notes_kr.md](preprocessing_notes_kr.md) |

## 읽는 순서

1. `cohort_definition_kr.md`
2. `preprocessing_notes_kr.md`
3. `feature_dictionary_kr.md`
4. `itemids_kr.md`
5. `pipeline_kr.md`
6. `setup_kr.md` (파이프라인 실행 전)

## 언어

각 문서에는 영문본과 국문본이 있다. 국문본 파일 이름은 `_kr`로 끝난다. 영문 목차는 [index.md](index.md)이다.

국문본은 영문본과 내용이 같다. 영문본이 기준 문서이다.
