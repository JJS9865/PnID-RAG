# PnID-RAG Vector DB Builder

## 폴더 구조

```text
.
├── data/
│   ├── corpus/
│   └── vector_db/
├── models/
│   ├── download_models.py
│   └── embedding/models--dragonkue--BGE-m3-ko/
├── vector_db/
│   ├── vector_db_config.py # Vector DB 경로, 기본 임베딩 모델, 청킹 설정
│   └── corpus_loader.py
└── requirements.txt
```

## 설치

```bash
pip install -r requirements.txt
```

## 임베딩 모델 다운로드

```bash
python models/download_models.py
```

## 전체 Vector DB 재구축

```bash
python vector_db/corpus_loader.py --table all
```

## 테이블별 구축

```bash
python vector_db/corpus_loader.py --table accidents
python vector_db/corpus_loader.py --table laws
python vector_db/corpus_loader.py --table designs
python vector_db/corpus_loader.py --table chemicals
python vector_db/corpus_loader.py --table basics
```

## 설정 변경

기본 경로, 기본 임베딩 모델, 배치 크기, 청킹 크기는 `vector_db/vector_db_config.py`에서 관리합니다.
기본값은 `DEFAULT_EMBED_MODEL = "dragonkue"`입니다.

일회성으로 다른 모델을 쓰고 싶을 때만 CLI 인자를 사용합니다.

```bash
python vector_db/corpus_loader.py --table all --embed-model dragonkue
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
python vector_db/check_db.py --table designs --sample-size 5 --show-text 500
```

`designs`는 section/subsection heading이 수식·표 항목처럼 보이는 경우 WARN으로 표시합니다.

출력 DB는 `data/vector_db`에 생성됩니다.
