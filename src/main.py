from config import FASTAPI_PORT
from src.api.app import app

DEFAULT_FASTAPI_PORT = FASTAPI_PORT

__all__ = ["app", "DEFAULT_FASTAPI_PORT"]
