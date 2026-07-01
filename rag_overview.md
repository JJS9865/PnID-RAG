# RAG 시스템 구조 정리

## 전체 파이프라인 흐름

```
사용자 질문
    ↓
[1] Intent Router       → 질문 의도 분류 (risk / law / design / general)
    ↓
[2] Entity Extractor    → 물질명 / 설비명 추출
    ↓
[3] 1차 검색 (Hybrid)   → Embedding + BM25 검색 (LanceDB)
    ↓
[4] 2차 검색 (Re-rank)  → BGE-Reranker-v2-m3
    ↓
[5] Case 분류           → 검색 결과 매칭 패턴 판별
    ↓
[6] 프롬프트 구성 + 답변 생성 (LLM)
    ↓
최종 응답 (답변 + 인용 출처)
```

---

## 1. Corpus (지식 베이스)

4가지 종류의 문서를 수집·가공하여 Vector DB에 저장한다.

| 테이블 | 내용 | 원본 형식 |
|--------|------|-----------|
| **accidents** | 국내외 화학 사고 사례 | Excel (domestic_accident.xlsx, 국외 사고사례.xlsx) |
| **chemicals** | 화학물질 안전 정보 460종 | PDF (물질별 페이지 단위) |
| **laws** | 산업안전보건법, 고압가스안전관리법 등 | PDF |
| **designs** | KOSHA Guide, 기술 지침 등 설계 기준서 | PDF (카테고리 하위 폴더별 분류) |

### 사고사례 문서의 구조화

사고사례는 일반 텍스트가 아닌 **5개 필드 태그** 형식으로 저장된다.

```
[사고내용] 톨루엔 취급 중 반응기에서 폭발 발생...
[관련설비] 반응기(Reactor)
[관련물질] 톨루엔(Toluene)
[사고유형] 폭발
[사고원인] 냉각수 공급 중단으로 인한 폭주 반응
```

이 구조 덕분에 물질명/설비명 필드에 대한 **별도 벡터 인덱스**를 생성하여 필드 단위 유사도 검색이 가능하다.

### 문서 청킹 전략

| 테이블 | 청킹 방식 |
|--------|-----------|
| accidents | 레코드 1건 = 청크 1개 (구조화된 Excel 행) |
| chemicals | PDF 페이지 단위 |
| laws | **조항(제N조) 단위**로 분할 (조항 경계 regex 탐지, 미발견 시 페이지 단위 fallback) |
| designs | PDF 페이지 단위, 800자 슬라이딩 윈도우 (overlap 100) |

---

## 2. Vector DB 구조

- **DB**: LanceDB (`./data/vector_db`)
- **테이블 수**: 4개 (accidents / chemicals / laws / designs)
- **임베딩 모델**: `BAAI/bge-m3` (1024차원, 코사인 유사도)
- **인덱스**: 각 테이블의 `text_vector` 컬럼 + Full-Text Search(BM25) 인덱스

### 테이블별 추가 벡터 컬럼

| 테이블 | 추가 벡터 컬럼 | 용도 |
|--------|---------------|------|
| accidents | `material_vector`, `equipment_vector` | 물질/설비 필드 단위 유사도 검색 |
| chemicals | `chemical_name_vector` | 물질명 벡터 유사도 검색 |
| laws | 없음 | text_vector만 사용 |
| designs | 없음 | text_vector만 사용 |

---

## 3. Query Preprocessing

검색 전 두 단계의 LLM 전처리를 수행한다.

### 3-1. Intent Router

- **역할**: 사용자 질문을 4가지 카테고리로 분류
- **모델**: GPT-OSS-20B (base model, temperature=0.0, max_tokens=256, reasoning_effort="low")
- **출력 형식**: JSON `{"intents": ["카테고리"]}`

| 카테고리 | 의미 | 예시 |
|----------|------|------|
| `risk` | 공정위험성 분석 | "톨루엔 반응기의 폭발 위험성은?" |
| `law` | 법규위반 검토 | "안전밸브 미설치 시 과태료는?" |
| `design` | 설계오류/기술지침 | "배관 두께가 KOSHA 기준에 맞나?" |
| `general` | 일상대화 / 해당없음 | "안녕하세요" |

라우팅 결과에 따라 **어떤 DB를 얼마나 검색할지**, **어떤 프롬프트를 쓸지**가 완전히 달라진다.
복수 의도가 감지될 경우 LLM 답변 생성 없이 재질문 안내 메시지를 반환한다.

### 3-2. Entity Extractor (Rewriter)

- **역할**: 질문에서 물질명과 설비명을 JSON으로 추출
- **모델**: GPT-OSS-20B (temperature=0.0, max_tokens=512, reasoning_effort="low")
- **출력 형식**: `{"target_material": "톨루엔", "target_equipment": "반응기"}`
- 추출된 값은 이후 **사고사례 필드 매칭 검색**에 직접 사용된다.

```
예시 입력: "톨루엔을 취급하는 반응기의 공정위험성을 알려줘."
예시 출력: {"target_material": "톨루엔", "target_equipment": "반응기"}
```

---

## 4. 1차 검색: Hybrid Search

### 알고리즘: Embedding + BM25 Hybrid

두 가지 검색 방식을 결합하여 의미 기반 매칭과 키워드 기반 매칭을 동시에 활용한다.

| 방식 | 알고리즘 | 특징 |
|------|----------|------|
| **Semantic Search** | BGE-M3 Dense Embedding + Cosine Similarity | 의미적으로 유사한 문서 탐색 |
| **Lexical Search** | BM25 (Best Match 25) | 키워드 정확 매칭, 전문 용어에 강함 |
| **Hybrid** | 두 점수를 가중합 | 의미 + 키워드 동시 반영 |

**최종 1차 점수**: `semantic_score × 0.5 + BM25_score × 0.5`

BM25 점수는 최대값으로 정규화(0~1) 후 합산된다.

### BGE-M3 임베딩 모델

- 다국어 지원, 한국어 문서에 최적화
- Dense vector 1024차원
- `normalize_embeddings=True` → L2 정규화된 벡터, 내적 = 코사인 유사도

### BM25 알고리즘

문서 내 단어 빈도(TF)와 역문서 빈도(IDF)를 결합해 관련도를 계산하는 확률적 검색 모델.

```
BM25(q, d) = Σ IDF(t) × (TF(t,d) × (k1+1)) / (TF(t,d) + k1 × (1 - b + b × |d|/avgdl))
```
- `k1`: 단어 빈도 포화 파라미터 (보통 1.2~2.0)
- `b`: 문서 길이 정규화 파라미터 (보통 0.75)
- 전문 용어, 고유명사(물질명, 법조항 번호 등)에서 특히 효과적

### 테이블별 1차 검색 한도

| 테이블 | 검색 한도 |
|--------|-----------|
| accidents | 최대 300건 |
| chemicals | 최대 3건 |
| laws | 최대 10건 |
| designs | 최대 10건 |

사고사례를 300건 대량 조회하는 이유: 이후 **필드 매칭 필터링**으로 물질/설비 일치 문서를 추려내기 때문이다.

---

## 5. 사고사례(Accidents) 검색 상세 흐름

사고사례는 일반 텍스트 전체를 쿼리하는 대신, **물질 필드와 설비 필드를 분리하여 검색 → 임계치 필터링 → Case 자동 결정**하는 전용 파이프라인을 사용한다.

```
[STEP 1] 필드별 Hybrid 검색 (최대 300건)
    material 필드  ← target_material로 hybrid 검색 → _material_relevance_score 부여
    equipment 필드 ← target_equipment로 hybrid 검색 → _equipment_relevance_score 부여
    두 결과를 ID 기준으로 병합 (점수는 max 취합)
         ↓
[STEP 2] 임계치 필터링 (threshold = 0.7)
    both_res     : material ≥ 0.7  AND  equipment ≥ 0.7
    material_res : material ≥ 0.7
    equipment_res: equipment ≥ 0.7
         ↓
[STEP 3] Case별 Re-ranking (BGE-Reranker-v2-m3)
    1-1 (both)    : [target_material, doc.material] + [target_equipment, doc.equipment] → 두 점수 평균
    1-2 (material): [target_material, doc.material]
    1-3 (equipment): [target_equipment, doc.equipment]
    → rerank score ≥ 0.7인 문서만 통과, 최대 6건 반환
         ↓
[STEP 4] Case Code 자동 결정 (우선순위: 1-1 > 1-2 > 1-3 > 1-4 > 1-5)
    both_docs > 0       → Case 1-1 선택
    material_docs > 0   → Case 1-2 선택
    equipment_docs > 0  → Case 1-3 선택
    모두 없음 + chemicals 있음 → Case 1-4
    모두 없음 + chemicals 없음 → Case 1-5 (답변 불가)
```

이 Case Code가 이후 **Generator의 프롬프트 선택, 고정 intro 문구, LLM 호출 횟수**를 모두 결정한다.

---

## 6. 2차 검색: Re-ranking

### 알고리즘: Cross-Encoder Reranker

1차 검색의 결과를 쿼리와 함께 재입력하여 더 정밀한 관련도를 계산한다.

- **모델**: `BAAI/bge-reranker-v2-m3`
- **방식**: Cross-Encoder (쿼리 + 문서를 함께 입력 → 관련도 점수 출력)
- Bi-Encoder(임베딩 모델)와 달리 쿼리와 문서의 **직접 상호작용**을 학습

| | Bi-Encoder (임베딩) | Cross-Encoder (Reranker) |
|---|---|---|
| 방식 | 쿼리/문서 각각 인코딩 후 벡터 비교 | 쿼리+문서 쌍을 함께 입력 |
| 속도 | 빠름 (벡터 캐시 가능) | 느림 (쌍마다 추론 필요) |
| 정확도 | 상대적으로 낮음 | 높음 |
| 역할 | 후보군 대량 추출 | 후보군 정밀 재정렬 |

### 테이블별 Re-rank 설정 (laws / designs)

accidents는 별도 흐름(섹션 5) 사용. laws / designs는 일반 Re-rank 적용.

| 테이블 | 최종 반환 수 | 유사도 임계치 |
|--------|-------------|---------------|
| laws | 최대 3건 | 0.5 이상 |
| designs | 최대 3건 | 0.5 이상 |
| chemicals | 최대 1건 | 0.7 이상 |

임계치 미만 문서는 모두 제거된다. 법령/설계는 임계치를 낮게 설정한 이유는, 법조문 특성상 질문과 표현이 달라도 내용적으로 관련 있는 경우가 많기 때문이다.

---

## 7. Case 분류

### Risk (공정위험성)

섹션 5의 Accidents 검색 흐름에서 자동 결정된다.

| Case Code | 조건 | 의미 |
|-----------|------|------|
| 1-1 | 물질 매칭 ✓ + 설비 매칭 ✓ | 동일 물질 + 유사 설비 사고 이력 존재 → 위험성 높음 |
| 1-2 | 물질 매칭 ✓ + 설비 매칭 ✗ | 동일 물질 사고 이력만 존재 |
| 1-3 | 물질 매칭 ✗ + 설비 매칭 ✓ | 유사 설비 사고 이력만 존재 |
| 1-4 | 둘 다 ✗ + 화학물질 정보 ✓ | 사고 이력 없음, 물질 정보로 대응 |
| 1-5 | 근거 문서 없음 | 답변 불가 |

### Law / Design

검색 결과를 LLM에 전달한 후, **Case Selector 호출(LLM 1회)**로 결정된다.

| Intent | Case Code | 의미 |
|--------|-----------|------|
| Law | 2-1 | 법규위반 YES |
| Law | 2-2 | 법규위반 NO (준수) |
| Law | 2-3 | 판단 불가 |
| Law | 2-4 | 근거 문서 없음 |
| Design | 3-1 | 설계오류 YES |
| Design | 3-2 | 설계오류 NO |
| Design | 3-3 | 판단 불가 |
| Design | 3-4 | 근거 문서 없음 |

---

## 8. P&ID (facility_info) 입력

### 개요

사용자는 질문 외에 **P&ID 설비 정보를 JSON 형식**으로 함께 전달할 수 있다. 이 정보는 검색 단계에서는 사용되지 않고, **Generator LLM 프롬프트에 직접 삽입**되어 답변의 정확도를 높인다.

```json
{
  "equipment_list": [
    {
      "equip_id": "E-2008",
      "equip_type": "COOLER",
      "specs": {
        "type": "DOUBLE PIPE",
        "duty": "0.009 MMkcal/h",
        "dp(i/o)": "15.0 / 10.0 barg",
        "dt(i/o)": "130 / 130 °C",
        "matl(i/o)": "SS 316L / SS 304"
      }
    }
  ],
  "piping_list": [
    {
      "line_id": "11027",
      "spec_class": "1-1/2-CHWS-11027-4CC2-IF",
      "from": "CHWS-11156",
      "to": "E-2008-S1",
      "components": [
        { "seq": 1, "type": "VALVE", "tag": "GATE, GENERAL VALVE" }
      ]
    }
  ]
}
```

### 포함 정보

| 필드 | 내용 |
|------|------|
| `equip_type` | 설비 종류 (COOLER, REACTOR, PUMP 등) |
| `specs.dp` | 설계 압력 (Design Pressure) |
| `specs.dt` | 설계 온도 (Design Temperature) |
| `specs.matl` | 재질 (SS 316L, CS 등) |
| `piping_list` | 연결 배관 라인, 노즐, 밸브/피팅 구성 |

### 프롬프트 내 활용 방식

```
[사용자 질문]: 이 설비에 설계오류가 있는지 분석해줘.

[설비 정보 (P&ID)]:
{ "equipment_list": [...], "piping_list": [...] }

[근거 문서]:
[CITE_1] ...
```

LLM은 P&ID 정보를 근거 문서와 함께 참조하여 **설계 압력/온도/재질이 기술 지침에 부합하는지** 또는 **법규 기준을 충족하는지** 판단한다. 입력이 없을 경우 빈 문자열로 처리되며, 답변 품질에 직접 영향을 준다.

---

## 9. 프롬프트 구성 및 답변 생성

### 문서 → Context 포맷팅

검색된 문서는 LLM에 전달하기 전에 아래 형식으로 직렬화된다.

```
[CITE_1]
문서 제목: domestic_accident.xlsx
문서 ID: domestic_0042
페이지: 없음
유사도: 0.8732
본문:
[사고내용] 톨루엔 취급 중 반응기에서 누출...
[관련설비] 반응기
[관련물질] 톨루엔
[사고유형] 화재
[사고원인] 플랜지 결함

[CITE_2]
문서 제목: 화학사고_대응물질정보.pdf
...
```

`[CITE_N]` 번호는 LLM이 답변 문장 내 인용 표시에 그대로 사용하고, 최종 API 응답에서 출처 목록으로 변환된다.

### Intent별 LLM 호출 구조

**Risk (공정위험성)**

Case 1-1 / 1-2 / 1-3:
```
[병렬 LLM 2회 호출]
  호출 A → 위험 특성 설명 + 대응 제안 (2문장)
  호출 B → 주요 사고 사례 목록
두 결과를 합쳐 최종 답변 구성
```

Case 1-4: LLM 1회 호출 (화학물질 정보 기반 설명)

**Law (법규위반) / Design (설계오류)**

```
[순차 LLM 2회 호출]
  호출 1 → Case Selector: 2-1(위반)/2-2(준수)/2-3(판단불가) 중 택 1
  호출 2 → Case에 맞는 프롬프트로 본문 생성
고정 Intro + LLM 본문 + 고정 Outro 조합
```

**고정 Intro/Outro 예시 (Law)**:
- 2-1 Intro: "검색된 문서를 기준으로 검토한 결과, 법적 요구사항을 충족하지 않는 것으로 확인되었습니다."
- 2-1 Outro: "해당 조항 위반 시 과태료 또는 행정 처분의 대상이 될 수 있습니다. 세부적인 법적 해석과 조치는 관할 기관 혹은 전문가를 통해 확인하시기 바랍니다."

### Context 길이 제한

| Intent | Context 최대 길이 |
|--------|------------------|
| risk | 제한 없음 (사고사례 최대 6건 + 화학물질 1건) |
| law | 10,000자로 truncate |
| design | 10,000자로 truncate |

### 답변 생성 모델

- **모델**: GPT-OSS-20B (LoRA adapter 적용, vLLM 서빙)
- **파라미터**: temperature=0.1, max_tokens=20,000
- **인용 후처리**: `[CITE_N]` 위치와 문장부호 정규화 적용

---

## 10. Citation 시스템

LLM이 생성한 답변 내 `[CITE_N]` 태그를 파싱하여 출처를 API 응답에 첨부한다.

**API 응답 구조**:
```json
{
  "answer": "톨루엔 반응기에서는 폭발 위험성이 높습니다. [CITE_1] ...",
  "sources": [
    {
      "title": "domestic_accident.xlsx",
      "page": null,
      "url": "/corpus/accidents/domestic_accident.xlsx"
    }
  ]
}
```

문서 제목, PDF 링크, 페이지 번호까지 포함하여 사용자가 원문 확인이 가능하다.
