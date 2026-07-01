import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Tuple

from langchain_openai import ChatOpenAI

from config import (
    BASE_MODEL_BF16,
    BASE_MODEL_MXFP4,
    EMBED_MODEL,
    LLM_MODEL,
    LLM_MAX_TOKENS,
    LLM_REASONING_EFFORT,
    LLM_TEMPERATURE,
    M_ADAPTER_NAME,
    REWRITER_MODEL,
    RERANK_MODEL,
    ROUTER_MODEL,
    VLLM_API_URL,
    VLLM_BASE_MODEL,
)

# FlagEmbedding 내부 tokenizer 안내 로그 억제
logging.getLogger("transformers").setLevel(logging.ERROR)

REPO_ROOT = Path(__file__).resolve().parents[2]
EMBED_MODEL_PATH = (REPO_ROOT / EMBED_MODEL).resolve()
RERANK_MODEL_PATH = (REPO_ROOT / RERANK_MODEL).resolve()
SEARCH_MODEL_DEVICE = "cuda:0"


def _make_client(model: str) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=VLLM_API_URL,
        api_key="EMPTY",
        model=model,
    )


def _bind_runtime_options(
    client: ChatOpenAI,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str | None = None,
):
    kwargs = {
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort
    return client.bind(**kwargs)


def get_base_model_name() -> str:
    if VLLM_BASE_MODEL == "mxfp4":
        return BASE_MODEL_MXFP4
    return BASE_MODEL_BF16


def _resolve_served_model(target: str) -> str:
    if target == "model_o":
        return get_base_model_name()
    if target == "model_m":
        return M_ADAPTER_NAME
    return target


model_o_mxfp4 = _bind_runtime_options(
    _make_client(BASE_MODEL_MXFP4),
    temperature=LLM_TEMPERATURE,
    max_tokens=LLM_MAX_TOKENS,
    reasoning_effort=LLM_REASONING_EFFORT,
)
model_o_bf16 = _bind_runtime_options(
    _make_client(BASE_MODEL_BF16),
    temperature=LLM_TEMPERATURE,
    max_tokens=LLM_MAX_TOKENS,
    reasoning_effort=LLM_REASONING_EFFORT,
)
model_m = _bind_runtime_options(
    _make_client(M_ADAPTER_NAME),
    temperature=LLM_TEMPERATURE,
    max_tokens=LLM_MAX_TOKENS,
    reasoning_effort=LLM_REASONING_EFFORT,
)
model_router = _make_client(_resolve_served_model(ROUTER_MODEL))
model_rewriter = _make_client(_resolve_served_model(REWRITER_MODEL))
model_llm = _bind_runtime_options(
    _make_client(_resolve_served_model(LLM_MODEL)),
    temperature=LLM_TEMPERATURE,
    max_tokens=LLM_MAX_TOKENS,
    reasoning_effort=LLM_REASONING_EFFORT,
)


def _ensure_model_path(path: Path, label: str) -> None:
    if not path.is_dir():
        raise FileNotFoundError(f"{label} 모델 경로 없음: {path}")


@lru_cache(maxsize=1)
def get_embed_model() -> Any:
    _ensure_model_path(EMBED_MODEL_PATH, "임베딩")

    from FlagEmbedding import BGEM3FlagModel

    return BGEM3FlagModel(
        str(EMBED_MODEL_PATH),
        use_fp16=True,
        devices=SEARCH_MODEL_DEVICE,
    )


@lru_cache(maxsize=1)
def get_rerank_model() -> Any:
    _ensure_model_path(RERANK_MODEL_PATH, "리랭커")

    from FlagEmbedding import FlagReranker

    return FlagReranker(
        str(RERANK_MODEL_PATH),
        use_fp16=True,
        devices=SEARCH_MODEL_DEVICE,
    )


def load_search_models() -> Tuple[Any, Any]:
    return get_embed_model(), get_rerank_model()


def shutdown_search_models() -> None:
    """캐시된 검색 모델의 멀티프로세스 풀 종료 후 캐시를 비운다."""
    for getter in (get_embed_model, get_rerank_model):
        if getter.cache_info().currsize == 0:
            continue
        model = getter()
        stop_pool = getattr(model, "stop_self_pool", None)
        if callable(stop_pool):
            stop_pool()
        getter.cache_clear()


def warmup_search_models() -> None:
    embed_model, rerank_model = load_search_models()

    embed_model.encode(["warmup"], return_dense=True, return_sparse=False)
    rerank_model.compute_score([["warmup", "warmup"]], normalize=True)
