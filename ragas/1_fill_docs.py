from __future__ import annotations

import io
import json
import logging
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Dict, List

# FlagEmbedding(BGE) 내부 progress bar 및 안내 메시지 억제
os.environ["TQDM_DISABLE"] = "1"
logging.getLogger("transformers").setLevel(logging.ERROR)

REPO_ROOT = Path(__file__).resolve().parents[1]
RAGAS_DIR = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LOCAL_EMBED_PATH = REPO_ROOT / "models" / "embedding" / "models--BAAI--bge-m3"
LOCAL_RERANK_PATH = REPO_ROOT / "models" / "reranker" / "models--BAAI--bge-reranker-v2-m3"


def _make_local_embed_fn():
    """로컬 BGE-M3로 쿼리 임베딩. SearchEngine._embed_query와 동일 시그니처."""
    if not LOCAL_EMBED_PATH.is_dir():
        raise FileNotFoundError(f"임베딩 모델 경로 없음: {LOCAL_EMBED_PATH} (models/download_models.py로 다운로드)")

    from FlagEmbedding import BGEM3FlagModel

    model = BGEM3FlagModel(str(LOCAL_EMBED_PATH), use_fp16=True)

    def embed_query(query: str) -> List[float]:
        if not query:
            return []
        out = model.encode([query], return_dense=True, return_sparse=False)
        dense = out.get("dense_vecs")
        if dense is None or len(dense) == 0:
            return []
        return dense[0].tolist()

    return embed_query


def _make_local_rerank_fn():
    """로컬 BGE-reranker-v2-m3로 리랭크. SearchEngine._rerank와 동일 시그니처."""
    if not LOCAL_RERANK_PATH.is_dir():
        raise FileNotFoundError(f"리랭커 모델 경로 없음: {LOCAL_RERANK_PATH} (models/download_models.py로 다운로드)")

    from FlagEmbedding import FlagReranker

    reranker = FlagReranker(str(LOCAL_RERANK_PATH), use_fp16=True)

    def rerank_fn(
        query: str,
        docs: List[Dict[str, Any]],
        top_k: int,
        threshold: float,
        show_progress: bool = False,
    ) -> List[Dict[str, Any]]:
        if not docs:
            return []
        if not query:
            return [{**doc, "score": 0.0, "rerank_score": 0.0} for doc in docs[:top_k]]

        pairs = [[query, doc.get("text", "")] for doc in docs]
        scores = reranker.compute_score(pairs, normalize=True)
        if isinstance(scores, (int, float)):
            scores = [scores]

        results = []
        for doc, score in sorted(zip(docs, scores), key=lambda x: x[1], reverse=True):
            s = float(score)
            if s < threshold:
                continue
            if len(results) >= top_k:
                break
            results.append({**doc, "score": round(s, 4), "rerank_score": round(s, 4)})
        return results

    return rerank_fn


from src.services.search_engine import SearchEngine
from src.services.json_parser import facility_json_to_text
from src.core.nodes.rewriter import rewriter_node


def _get(d: dict, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def _run_rewriter(question: str, facility_info: dict | None) -> Dict[str, Any]:
    facility_text = facility_json_to_text(facility_info).strip() if facility_info else ""
    state = {
        "question": question,
        "facility_info": facility_text,
    }

    sink = io.StringIO()
    with redirect_stdout(sink), redirect_stderr(sink):
        rewritten = rewriter_node(state)

    return rewritten if isinstance(rewritten, dict) else {}


def _resolve_intent(sample: dict) -> str:
    intent = str(sample.get("intent") or "").strip().lower()
    if intent:
        return intent

    sample_id = str(sample.get("id") or "").strip().lower()
    if "-" in sample_id:
        return sample_id.split("-", 1)[0]
    return sample_id


def _preview_text(raw_text: str, limit: int = 20) -> str:
    text = " ".join((raw_text or "").strip().split())
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _score_or_zero(value: Any) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


def _chunk_metadata(
    category: str,
    source: str,
    primary_score: Any,
    rerank_score: Any,
    raw_text: str,
) -> Dict[str, Any]:
    return {
        "category": category,
        "source": str(source),
        "preview": _preview_text(raw_text),
        "primary_score": _score_or_zero(primary_score),
        "rerank_score": _score_or_zero(rerank_score),
    }


def _collect_reference_contexts(results: dict) -> tuple[List[str], List[Dict[str, Any]]]:
    """search() 결과를 카테고리 순서대로 2개 배열로 만든다."""
    texts: List[str] = []
    metadata: List[Dict[str, Any]] = []
    for key, category in [
        ("accident_docs", "accidents"),
        ("chemical_docs", "chemicals"),
        ("law_docs", "laws"),
        ("design_docs", "designs"),
    ]:
        docs = results.get(key) or []
        for doc in docs:
            source = doc.get("source") or doc.get("title") or ""
            raw_text = str(doc.get("text") or "").strip()
            if not raw_text:
                continue
            primary_score = doc.get("primary_score")
            if primary_score is None:
                primary_score = doc.get("match_score")
            if primary_score is None:
                primary_score = doc.get("score")
            rerank_score = doc.get("rerank_score")
            if rerank_score is None:
                rerank_score = doc.get("score")

            primary_score_value = _score_or_zero(primary_score)
            rerank_score_value = _score_or_zero(rerank_score)
            texts.append(raw_text)
            metadata.append(
                _chunk_metadata(
                    category=category,
                    source=source,
                    primary_score=primary_score_value,
                    rerank_score=rerank_score_value,
                    raw_text=raw_text,
                )
            )
    return texts, metadata


def main(data_path: Path) -> None:
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    engine = SearchEngine()
    if engine.db is None:
        print("Error: 벡터 DB 연결 실패. SEARCH_ENGINE_CONFIG['DB_PATH'] 확인.")
        sys.exit(1)

    print("로컬 임베딩/리랭크 + vLLM rewriter 사용 중...")
    try:
        engine._embed_query = _make_local_embed_fn()
        engine._rerank = _make_local_rerank_fn()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error (로컬 모델 로드): {e}")
        print("  pip install FlagEmbedding 후 다시 시도하세요.")
        sys.exit(1)

    samples = data["samples"]
    total = len(samples)
    for i, s in enumerate(samples, start=1):
        s.setdefault("reference", None)
        s.setdefault("retrieved_contexts", None)
        s.setdefault("response", None)

        user_input = (s.get("user_input") or "").strip()
        intent = _resolve_intent(s)

        if intent not in {"risk", "law", "design", "general"}:
            s["reference_contexts"] = []
            s["reference_context_metadata"] = []
            print(f"  [{i}/{total}] {s.get('id')} (unknown intent) → skipped")
            continue

        if intent == "general" or not user_input:
            s["reference_contexts"] = []
            s["reference_context_metadata"] = []
            print(f"  [{i}/{total}] {s.get('id')} (general or empty) → reference_contexts []")
            continue

        rewritten = _run_rewriter(
            question=user_input,
            facility_info=s.get("facility_info"),
        )
        search_query = str(rewritten.get("search_query") or user_input).strip()
        filters = None
        if intent == "risk":
            filters = {
                "material": rewritten.get("target_material"),
                "equipment": rewritten.get("target_equipment"),
            }

        results = engine.search(
            query=search_query,
            intents=[intent],
            filters=filters,
            show_progress=False,
        )
        ref_texts, ref_metadata = _collect_reference_contexts(results)
        s["reference_contexts"] = ref_texts
        s["reference_context_metadata"] = ref_metadata
        n = len(ref_texts)
        print(f"  [{i}/{total}] {s.get('id')} ({intent}) → {n} chunks | query={search_query}")

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Wrote {data_path}")


if __name__ == "__main__":
    data_path = RAGAS_DIR / "ragas_test.json"
    main(data_path=data_path)
