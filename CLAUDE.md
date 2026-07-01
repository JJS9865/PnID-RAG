# CLAUDE.md

RAG 기반 화학공정 안전 자문 시스템 (HAZOP 어시스턴트). LangGraph + 파인튜닝 LLM + 하이브리드 벡터 검색 + 다단계 리랭킹.

## 서버 실행

```bash
# Terminal 1: vLLM 추론 서버
python scripts/run_vllm.py --bf16

# Terminal 2: FastAPI
uvicorn src.main:app --host 0.0.0.0 --port 8888 --reload
```

FastAPI: 8888 / vLLM: 10001 / GPU 워크스테이션: 210.91.154.131

## 테스트

```bash
python -m src.core.nodes.router --bf16 --live o       # 라우터 (의도 분류)
python -m src.core.nodes.rewriter --bf16 --live o     # 리라이터 (엔티티 추출)
python -m src.services.chat_service --question "질문"  # 전체 파이프라인
python -m src.services.search_engine                   # 검색 엔진
```

## 평가

```bash
python tests/test_model_answer.py   # 답변 생성 테스트
python tests/test_model_score.py    # BERT-score 평가
python ragas/1_fill_docs.py         # RAGAS 평가 (순서대로 실행)
python ragas/2_fill_answers.py --risk 30
python ragas/3_run_ragas.py --risk 30 --all
```

## 주요 파일

| 파일 | 역할 |
|------|------|
| `config.py` | 모델 경로, 포트, LLM 파라미터 |
| `src/core/graph.py` | LangGraph 워크플로우 정의 |
| `src/core/state.py` | AgentState TypedDict |
| `src/core/nodes/router.py` | 의도 분류 (risk/law/design/general/fallback) |
| `src/core/nodes/rewriter.py` | 엔티티 추출 (물질, 설비) |
| `src/core/nodes/generator.py` | 답변 생성 (3개 서브플로우) |
| `src/services/search_engine.py` | 하이브리드 검색 + 리랭킹 |
| `src/services/chat_service.py` | 그래프 오케스트레이션, API 응답 포맷 |
| `src/services/corpus_loader.py` | PDF → LanceDB 임베딩 |
| `src/prompts/` | 노드별 LLM 프롬프트 |

## 모델

- **Base LLM**: `models--openai--gpt-oss-20b` (BF16/MXFP4) via vLLM
- **LoRA 어댑터**: `models/finetuned/best_adapter/m2/`
- **임베딩/리랭킹**: `config.py`의 `_EMBED_MODEL_VARIANT`로 선택
  - `"baai"` → BAAI/bge-m3 + bge-reranker-v2-m3 (현재 기본값)
  - `"dragonkue"` → dragonkue/BGE-m3-ko + bge-reranker-v2-m3-ko (한국어 특화, 임베딩 +15% / 리랭킹 +5%)
  - **주의**: 모델 변경 시 반드시 `corpus_loader.py --embed-model <variant>`로 DB 전체 재빌드 필요

## 벡터DB (LanceDB: `./data/vector_db`)

- **accidents**: 화학사고 사례
- **chemicals**: 화학물질 안전 데이터 460종
- **laws**: 국내 산업안전 법규
- **designs**: 기술 설계 지침
- **basics**: 기초 개념 (신규 추가)

```bash
python data/check_db.py                              # DB 상태 확인
python src/services/corpus_loader.py --table all     # 전체 재임베딩
```

---

## 개발 진행 상황

### 완료
- laws 조항(제N조) 기준 청킹
- laws/designs FTS 인덱스 추가
- basics 테이블 신규 추가
- accidents 안전원 파일 추가
- 임베딩/리랭킹 모델 교체 옵션 추가 (`config.py`의 `_EMBED_MODEL_VARIANT`: baai ↔ dragonkue)
- chemicals 텍스트 정제 (`_clean_chemical_text`: 원본 대비 51%로 압축, 할루시네이션 유발 섹션 제거)

### 미완료
- [ ] dragonkue 모델로 DB 재빌드 (`corpus_loader.py --table all --embed-model dragonkue` 후 config 변경)
- [ ] laws 별표/고시 청킹 보완 (테스트 후 진행)
- [ ] designs 섹션 단위 청킹 전환 (테스트 후 진행)
- [ ] basics 검색 파이프라인 연결 확인

