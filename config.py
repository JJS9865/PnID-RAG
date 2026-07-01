# 서버 설정
RUNTIME_ENV = "server"  # local | server
GPU_SERVER_PUBLIC_IP = "210.91.154.131"  # 워크스테이션: {curl -s ifconfig.me} 값으로 변경
GPU_SERVER_PRIVATE_IP = "10.233.108.28"  # 워크스테이션: localhost or {hostname -I} 값으로 변경

# 포트 설정 (FastAPI = 외부 & vLLM = 내부 포트 사용)
FASTAPI_PORT = 8888
VLLM_PORT = 10001
FASTAPI_REMOTE_HOST = f"http://{GPU_SERVER_PUBLIC_IP}:20443"  # 워크스테이션: {GPU_SERVER_PUBLIC_IP}:{FASTAPI_PORT} 으로 변경
FASTAPI_REMOTE_PATH = "/deployment2/2fa684d738b1edad"  # 워크스테이션: 빈칸으로 변경
FASTAPI_LOCAL_HOST = f"http://localhost:{FASTAPI_PORT}"
FASTAPI_BASE_URL = FASTAPI_LOCAL_HOST if RUNTIME_ENV == "local" else f"{FASTAPI_REMOTE_HOST}{FASTAPI_REMOTE_PATH}"
VLLM_LOCAL_API_URL = f"http://localhost:{VLLM_PORT}/v1"
VLLM_REMOTE_API_URL = f"http://{GPU_SERVER_PRIVATE_IP}:{VLLM_PORT}/v1"
VLLM_API_URL = VLLM_LOCAL_API_URL if RUNTIME_ENV == "local" else VLLM_REMOTE_API_URL

# 경로 설정
BASE_MODEL_MXFP4 = "./models/base_mxfp4/models--openai--gpt-oss-20b"
BASE_MODEL_BF16 = "./models/base_bf16/models--openai--gpt-oss-20b"
M_ADAPTER_NAME = "m_adapter"
M_ADAPTER_PATH = "./models/finetuned/best_adapter/m2"
# 임베딩/리랭킹 모델 선택: "baai" 또는 "dragonkue"
# dragonkue 모델은 한국어 특화 파인튜닝 (임베딩 +15%, 리랭킹 +5%)
# ※ 모델을 바꾸면 반드시 corpus_loader.py --embed-model dragonkue 로 DB 전체 재빌드 필요
_EMBED_MODEL_VARIANT = "dragonkue"

_EMBED_MODEL_MAP = {
    "baai":      "./models/embedding/models--BAAI--bge-m3",
    "dragonkue": "./models/embedding/models--dragonkue--BGE-m3-ko",
}
_RERANK_MODEL_MAP = {
    "baai":      "./models/reranker/models--BAAI--bge-reranker-v2-m3",
    "dragonkue": "./models/reranker/models--dragonkue--bge-reranker-v2-m3-ko",
}
EMBED_MODEL  = _EMBED_MODEL_MAP[_EMBED_MODEL_VARIANT]
RERANK_MODEL = _RERANK_MODEL_MAP[_EMBED_MODEL_VARIANT]

# 모델 설정
VLLM_BASE_MODEL = "bf16"
ROUTER_MODEL = "model_o"
REWRITER_MODEL = "model_o"
LLM_MODEL = "model_m"

# LLM 설정
VLLM_MAX_MODEL_LEN = 100000
LLM_GPU_UTIL = "0.7"
LLM_TEMPERATURE = 0.1
LLM_REASONING_EFFORT = "low"
LLM_MAX_TOKENS = 20000
ROUTER_TEMPERATURE = 0.0
ROUTER_REASONING_EFFORT = "low"
ROUTER_MAX_TOKENS = 256
REWRITER_TEMPERATURE = 0.0
REWRITER_REASONING_EFFORT = "low"
REWRITER_MAX_TOKENS = 512





"""
# Server
python scripts/run_vllm.py --bf16
uvicorn src.main:app --host 0.0.0.0 --port 8888 --reload
uvicorn src.main:app --host 0.0.0.0 --port 8888 --reload --root-path /deployment2/2fa684d738b1edad
swagger 확인: http://210.91.154.131:20443/deployment2/2fa684d738b1edad/docs


# Tests
python -m src.services.search_engine
python -m src.core.nodes.router --models o --bf16
python -m src.core.nodes.rewriter --models o --bf16
python -m src.services.chat_service --question "오늘 날씨 어때?"


# Others
python data/check_db.py
python scripts/generate_accidents_pdf.py --force


# RAGAS
python ragas/1_fill_docs.py
python ragas/2_fill_answers.py --risk 30
python ragas/3_run_ragas.py --risk 30 --all | recall | ffn


"""