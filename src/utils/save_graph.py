from pathlib import Path
from datetime import datetime, timedelta, timezone
from src.core.graph import app_graph


def save_graph_png():
    """
    현재 컴파일된 LangGraph를 PNG 이미지로 저장
    사용법: python -m src.utils.save_graph
    """
    filename = f"graph_{datetime.now(timezone(timedelta(hours=9))):%Y-%m%d-%H%M-%S}.png"
    path = Path("src/utils") / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(app_graph.get_graph().draw_mermaid_png())
    print(f"Graph saved: {path}")


if __name__ == "__main__":
    save_graph_png()