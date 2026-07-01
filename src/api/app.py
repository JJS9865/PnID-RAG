from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.routers.chat import router as chat_router
from src.core.models import shutdown_search_models, warmup_search_models

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CORPUS_DIR = DATA_DIR / "corpus"
ACCIDENTS_PDF_DIR = DATA_DIR / "accidents_pdf"


@asynccontextmanager
async def lifespan(_: FastAPI):
    warmup_search_models()
    try:
        yield
    finally:
        shutdown_search_models()


app = FastAPI(title="POSTECH", lifespan=lifespan)


@app.get("/health")
async def health():
    """API Health Check"""
    return {"status": "ok"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(chat_router)
app.mount("/static/corpus", StaticFiles(directory=str(CORPUS_DIR)), name="corpus")
app.mount("/static/accidents_pdf", StaticFiles(directory=str(ACCIDENTS_PDF_DIR)), name="accidents_pdf")