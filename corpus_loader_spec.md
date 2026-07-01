# corpus_loader.py 명세서

---

## 실행 방법

```bash
# 전체 테이블 빌드 (기본값)
python src/services/corpus_loader.py --table all

# 특정 테이블만 빌드
python src/services/corpus_loader.py --table accidents
python src/services/corpus_loader.py --table laws
python src/services/corpus_loader.py --table designs
python src/services/corpus_loader.py --table chemicals
python src/services/corpus_loader.py --table basics
```

- 실행 위치: 프로젝트 루트 (`hazop-develop/`)
- 기존 테이블은 `DROP` 후 재생성 (덮어쓰기)
- GPU 사용 시 임베딩 속도 향상 (`EMBED_BATCH_SIZE=32`)

---

## DB 개요

**저장소**: LanceDB (`./data/vector_db/`)

LanceDB는 로컬 파일 기반 벡터 DB로, 별도 서버 없이 Python에서 직접 접근한다.
각 테이블은 텍스트 청크 + 임베딩 벡터 + 메타데이터 필드로 구성된다.

**임베딩 모델**: `BAAI/bge-m3` (1024차원, 한/영 다국어)

### 테이블 목록

| 테이블 | 원본 형식 | 청킹 방식 | FTS | 레코드 수 (예상) |
|--------|-----------|-----------|-----|-----------------|
| accidents | Excel | 행 1개 = 1청크 | ✗ | ~1,000건+ |
| laws | PDF | 조항(제N조) 단위 | ✓ | ~수천 청크 |
| designs | PDF | 페이지 단위 | ✓ | ~수천 청크 |
| chemicals | PDF | 페이지 단위 | ✗ | ~460종 × 수 페이지 |
| basics | PDF | 페이지 단위 | ✓ | ~수만 청크 (대용량) |

**FTS**: LanceDB `create_fts_index("text")` — BM25 기반 풀텍스트 검색 인덱스

### 검색 방식 (search_engine.py)

- **Hybrid Search**: 벡터(ANN) + BM25(FTS) 0.5:0.5 혼합
- **Reranking**: `BAAI/bge-reranker-v2-m3` Cross-Encoder로 2차 정렬
- basics는 아직 search_engine.py에 미연동 (별도 설계 필요)

---

## 테이블별 스키마

### accidents

원본: `data/corpus/accidents/` (Excel 3종)

| 파일 | origin 태그 | 건수 |
|------|-------------|------|
| `domestic_accident.xlsx` | `domestic` | — |
| `국외 사고사례_250827.xlsx` | 시트명 기반 | — |
| `안전원_P&ID 국내 화학사고 모음_2025.06.09.xlsx` | `안전원_PSM` / `안전원_환경부` | 156 + 356건 |

| 필드 | 타입 | 설명 |
|------|------|------|
| id | string | `domestic_0001`, `safety_psm_0001` 등 |
| text | string | `[사고내용] ... [관련설비] ... [관련물질] ... [사고유형] ... [사고원인] ...` |
| text_vector | float32[1024] | text 임베딩 |
| source | string | 원본 파일명 |
| source_path | string | 상대 경로 |
| material | string | 관련 물질명 |
| material_vector | float32[1024] | 물질명 임베딩 |
| equipment | string | 관련 설비명 |
| equipment_vector | float32[1024] | 설비명 임베딩 |
| accident_type | string | 사고 유형 |
| cause | string | 사고 원인 |
| origin | string | 출처 구분 |

---

### laws

원본: `data/corpus/laws/` (PDF, 하위 폴더 포함)

청킹: `_chunk_law_by_article()` — `^제\d+조` 패턴으로 조항 경계 탐지
- 조항 구조 없으면 페이지 단위 fallback (`article = ""`)
- 전문(前文, 제1조 이전) 제거
- 2000자 초과 조항은 서브청킹: `제15조(안전조치) [계속 2/3]` 헤더 반복 삽입

| 필드 | 타입 | 설명 |
|------|------|------|
| id | string | `{파일명}_{chunk_id:04d}` |
| text | string | 조항 텍스트 |
| text_vector | float32[1024] | text 임베딩 |
| source | string | PDF 파일명 |
| chunk_id | int32 | 청크 순번 |
| page | int32 | 시작 페이지 |
| source_path | string | 상대 경로 |
| title | string | 법령명 (ex. "고압가스 안전관리법") |
| title_vector | float32[1024] | 법령명 임베딩 |
| article | string | 조항 헤더 (ex. "제1조(목적)"), 없으면 `""` |
| article_vector | float32[1024] | 조항 헤더 임베딩; `article=""`이면 text_vector 복사 |

---

### designs

원본: `data/corpus/designs/{카테고리}/` (PDF)

청킹: 페이지 단위 (`_chunk_pdf_by_page`)

title 추출 (`_extract_design_title()`):
- 파일명에 `+` 포함 → **KOSHA Guide**: `P-82-2023+제목+...` → `[P-82-2023] 제목 ...`
- 파일명이 `KGS`로 시작 → **KGS Code**: PDF 첫 페이지 텍스트에서 코드+한국어 제목 파싱
- 기타: 파일명(확장자 제외) 그대로

| 필드 | 타입 | 설명 |
|------|------|------|
| id | string | `{파일명}_{chunk_id:04d}` |
| text | string | 페이지 텍스트 |
| text_vector | float32[1024] | text 임베딩 |
| source | string | PDF 파일명 |
| chunk_id | int32 | 청크 순번 |
| page | int32 | 페이지 번호 |
| source_path | string | 상대 경로 |
| category | string | 하위 폴더명 |
| title | string | 정제된 지침명 |
| title_vector | float32[1024] | 지침명 임베딩 |
| section | string | 섹션 번호 (ex. `"5"`, `"5.1"`), 없으면 `""` |
| section_vector | float32[1024] | 섹션 임베딩; `section=""`이면 text_vector 복사 |

---

### chemicals

원본: `data/corpus/chemicals/` (PDF 1개)

물질명 결정: `화학물질 목록_재정렬.xlsx` 순서 인덱싱 → 범위 초과 시 PDF 텍스트 파싱

| 필드 | 타입 | 설명 |
|------|------|------|
| id | string | `{파일명}_{chunk_id:04d}` |
| text | string | 페이지 텍스트 |
| text_vector | float32[1024] | text 임베딩 |
| source | string | PDF 파일명 |
| chunk_id | int32 | 청크 순번 |
| page | int32 | 페이지 번호 (+29 오프셋 적용) |
| source_path | string | 상대 경로 |
| chemical_name | string | `"국문명(영문명) \| 유사명"` 형태 |
| chemical_name_vector | float32[1024] | 물질명 임베딩 |

---

### basics (신규)

원본: `data/corpus/basics/{카테고리}/` (PDF)

| 카테고리 | 내용 |
|----------|------|
| `기타` | 안전밸브 처리기준 등 보고서 |
| `논문_한글` | 한국어 화공 논문 |
| `전공서_영문` | 영문 화공 전공서 (최대 70MB) |

| 필드 | 타입 | 설명 |
|------|------|------|
| id | string | `{파일명}_{chunk_id:04d}` |
| text | string | 페이지 텍스트 |
| text_vector | float32[1024] | text 임베딩 |
| source | string | PDF 파일명 |
| chunk_id | int32 | 청크 순번 |
| page | int32 | 페이지 번호 |
| source_path | string | 상대 경로 |
| category | string | 하위 폴더명 |
| title | string | 파일명(확장자 제외) |
| title_vector | float32[1024] | 제목 임베딩 |
| chapter | string | `"Chapter N ..."` 또는 `"제N장 ..."`, 없으면 `""` |
| chapter_vector | float32[1024] | 챕터 임베딩; `chapter=""`이면 text_vector 복사 |

---

## 기존 DB("벡터DB 개선") 대비 변경사항

### 테이블 구성 변경

| 구분 | 기존 | 현재 |
|------|------|------|
| 테이블 수 | 4개 | 5개 |
| 신규 테이블 | — | `basics` |

### accidents

| 구분 | 기존 | 현재 |
|------|------|------|
| 원본 파일 | domestic + 국외 2종 | domestic + 국외 + **안전원_P&ID 1종 추가** |
| 신규 데이터 | — | 안전원_PSM 156건 + 안전원_환경부 356건 |
| 시트 처리 | — | `_load_safety_center_file()` (컬럼명 불규칙 처리 포함) |

### laws

| 구분 | 기존 | 현재 |
|------|------|------|
| 청킹 반환값 | `(page, chunk)` | `(page, chunk, title, article)` |
| 메타데이터 필드 | 없음 | `title`, `title_vector`, `article`, `article_vector` 추가 |
| 전문(前文) | 포함 (article="" 청크로 저장) | **제거** |
| 긴 조항 처리 | 제한 없음 (수만 자도 그대로) | **2000자 서브청킹** (`[계속 N/M]` 헤더 반복) |
| 빈 article 벡터 | 빈 문자열 그대로 임베딩 | **text_vector 복사**로 대체 |

### designs

| 구분 | 기존 | 현재 |
|------|------|------|
| 메타데이터 필드 | 없음 (`category`만) | `title`, `title_vector`, `section`, `section_vector` 추가 |
| title 값 | — | `_extract_design_title()`: KOSHA `[P-82-2023] 제목` / KGS `[KGS AC111 2025] 제목` / 기타 파일명 |
| 빈 section 벡터 | — | **text_vector 복사**로 대체 |

### chemicals

| 구분 | 기존 | 현재 |
|------|------|------|
| xlsx 참조 | `화학물질 목록_재정렬.xlsx` (동일) | 동일 |
| 스키마 | 동일 | 동일 |

> chemicals는 기존 `벡터DB 개선` 코드에서 이미 완성된 상태였으므로 변경 없음.

### basics (신규)

기존에 없던 테이블. 화공 일반정보(교재·논문·보고서)를 추가하여 general intent 질문 대응.
