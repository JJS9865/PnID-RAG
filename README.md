# PnID-RAG Vector DB Builder

## 폴더 구조

```text
.
├── config.py                  # 임베딩 모델 경로 설정
├── data/
│   ├── corpus/                # 원본 corpus
│   └── vector_db/             # LanceDB 출력 DB
├── models/
│   └── embedding/models--dragonkue--BGE-m3-ko/
├── vector_db/
│   ├── vectordb_builder.py    # Vector DB 빌드 로직과 DB/청킹 설정
│   └── check_db.py            # Vector DB 점검 스크립트
└── requirements.txt
```

## 설치

```bash
pip install -r requirements.txt
```

## 임베딩 모델 설정

기본 임베딩 모델 경로는 루트의 `config.py`에서 관리합니다.

```python
EMBED_MODEL = "./models/embedding/models--dragonkue--BGE-m3-ko"
```

Vector DB 경로, corpus 경로, 배치 크기, 청킹 크기 등 빌드 설정은 `vector_db/vectordb_builder.py`의 `VECTOR_DB_CONFIG`에서 관리합니다.

## 전체 Vector DB 재구축

```bash
python vector_db/vectordb_builder.py --table all
```

인자를 생략해도 전체 테이블을 빌드합니다.

```bash
python vector_db/vectordb_builder.py
```

## 테이블별 구축

```bash
python vector_db/vectordb_builder.py --table accidents
python vector_db/vectordb_builder.py --table laws
python vector_db/vectordb_builder.py --table designs
python vector_db/vectordb_builder.py --table chemicals
python vector_db/vectordb_builder.py --table basics
```

여러 테이블을 한 번에 빌드할 때는 `--tables`를 사용합니다.

```bash
python vector_db/vectordb_builder.py --tables accidents laws designs
```

`chemicals` 테이블은 `data/corpus/chemicals/*.md`를 읽어 물질 1개당 1 row로 생성합니다.
`designs` 테이블은 표지/목차/후단 별표·별지성 페이지를 제외하고 section/subsection heading 단위로 생성합니다.

## Vector DB 점검

전체 테이블 요약, 스키마, 벡터 차원, 텍스트 길이 통계, 빈 필드, 중복 ID, source_path 존재 여부, 랜덤 샘플을 확인합니다.

```bash
python vector_db/check_db.py
```

특정 테이블만 확인할 수 있습니다.

```bash
python vector_db/check_db.py --table accidents --sample-size 5 --show-text 500
```

`designs`는 section/subsection heading이 수식·표 항목처럼 보이는 경우 WARN으로 표시합니다.

출력 DB는 기본적으로 `data/vector_db`에 생성됩니다.
