from pathlib import Path


VECTOR_DB_ROOT = Path(__file__).resolve().parents[1]


def resolve_vector_db_path(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return VECTOR_DB_ROOT / path


EMBED_MODEL_VARIANTS = {
    "baai": "./models/embedding/models--BAAI--bge-m3",
    "dragonkue": "./models/embedding/models--dragonkue--BGE-m3-ko",
}

DEFAULT_EMBED_MODEL = "dragonkue"

VECTOR_DB_CONFIG = {
    "VECTOR_DB_DIR": "./data/vector_db",
    "ACCIDENTS_DIR": "./data/corpus/accidents",
    "LAWS_DIR": "./data/corpus/laws",
    "DESIGNS_DIR": "./data/corpus/designs",
    "CHEMICALS_DIR": "./data/corpus/chemicals",
    "BASICS_DIR": "./data/corpus/basics",
    "EMBEDDING_MODEL": EMBED_MODEL_VARIANTS[DEFAULT_EMBED_MODEL],
    "EMBEDDING_DIM": 1024,
    "EMBED_BATCH_SIZE": 32,
    "CHUNK_MAX_TOKENS": 1000,
    "CHUNK_OVERLAP_TOKENS": 100,
}
