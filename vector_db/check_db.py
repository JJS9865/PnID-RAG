from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any

import lancedb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from vector_db.vectordb_builder import TABLE_NAMES, VECTOR_DB_CONFIG, resolve_vector_db_path
except ModuleNotFoundError:
    from vectordb_builder import TABLE_NAMES, VECTOR_DB_CONFIG, resolve_vector_db_path

DEFAULT_TABLES = list(TABLE_NAMES)
EXPECTED_ROW_COUNTS = {
    "chemicals": 460,
}

VECTOR_COLUMNS = {
    "text_vector",
    "material_vector",
    "equipment_vector",
    "title_vector",
    "article_vector",
    "section_vector",
    "subsection_vector",
    "chapter_vector",
    "chemical_name_vector",
}
TEXT_COLUMNS_BY_TABLE = {
    "accidents": ["text", "material", "equipment"],
    "laws": ["text", "title", "article"],
    "designs": ["text", "title", "section", "subsection"],
    "chemicals": ["text", "chemical_name"],
    "basics": ["text", "title", "chapter"],
}
REQUIRED_COLUMNS_BY_TABLE = {
    "accidents": ["id", "text", "source", "source_path", "material", "equipment", "text_vector", "material_vector", "equipment_vector"],
    "laws": ["id", "text", "source", "chunk_id", "page", "source_path", "title", "article", "text_vector", "title_vector", "article_vector"],
    "designs": ["id", "text", "source", "chunk_id", "page", "source_path", "category", "title", "section", "subsection", "text_vector", "title_vector", "section_vector", "subsection_vector"],
    "chemicals": ["id", "text", "source", "chunk_id", "page", "source_path", "chemical_name", "text_vector", "chemical_name_vector"],
    "basics": ["id", "text", "source", "chunk_id", "page", "source_path", "category", "title", "chapter", "text_vector", "title_vector", "chapter_vector"],
}


def _table_names(db: Any) -> list[str]:
    listed = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
    return sorted(listed.tables if hasattr(listed, "tables") else listed)


def _to_rows(table: Any) -> list[dict[str, Any]]:
    return table.to_arrow().to_pylist()


def _text_len(value: Any) -> int:
    return len(str(value or ""))


def _pct(num: int, den: int) -> str:
    if den == 0:
        return "0.00%"
    return f"{num / den * 100:.2f}%"


def _quantiles(values: list[int]) -> dict[str, int | float]:
    if not values:
        return {"min": 0, "p25": 0, "median": 0, "avg": 0, "p75": 0, "max": 0}
    sorted_values = sorted(values)
    n = len(sorted_values)

    def pick(q: float) -> int:
        return sorted_values[min(n - 1, int((n - 1) * q))]

    return {
        "min": sorted_values[0],
        "p25": pick(0.25),
        "median": int(median(sorted_values)),
        "avg": round(mean(sorted_values), 1),
        "p75": pick(0.75),
        "max": sorted_values[-1],
    }


def _format_preview(value: Any, limit: int) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _vector_dims(row: dict[str, Any]) -> dict[str, int]:
    dims = {}
    for key, value in row.items():
        if key in VECTOR_COLUMNS and isinstance(value, list):
            dims[key] = len(value)
    return dims


def _source_path_exists(source_path: Any) -> bool:
    if not source_path:
        return False
    text = str(source_path)
    if text.startswith("./"):
        text = text[2:]
    return resolve_vector_db_path(text).is_file()


def _looks_like_design_heading(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if len(text) > 100:
        return False
    match = re.match(r"^([A-Z]?\d+(?:\.\d+){0,5})\.?\s*(.*)$", text)
    if not match:
        return False
    code = match.group(1)
    code_body = re.sub(r"^[A-Z]", "", code)
    if any(part == "0" for part in code_body.split(".")):
        return False
    title = match.group(2).strip()
    if re.match(r"^[A-Z]\d+$", code) and title.startswith(":"):
        return False
    if re.search(r"^[,./~%\d\s]+$", title):
        return False
    if re.search(r"^에\s*대응", title):
        return False
    return True


def _print_table_summary(name: str, table: Any, rows: list[dict[str, Any]], expected_dim: int, sample_size: int, seed: int, show_text: int) -> bool:
    ok = True
    row_count = len(rows)
    schema_cols = [field.name for field in table.schema]
    print(f"\n=== {name} ===")
    print(f"rows: {row_count}")
    expected_rows = EXPECTED_ROW_COUNTS.get(name)
    if expected_rows is not None and row_count != expected_rows:
        ok = False
        print(f"[WARN] expected rows={expected_rows}, got={row_count}")
    print(f"columns: {', '.join(schema_cols)}")

    required = REQUIRED_COLUMNS_BY_TABLE.get(name, [])
    missing = [col for col in required if col not in schema_cols]
    if missing:
        ok = False
        print(f"[WARN] missing required columns: {missing}")

    try:
        indices = table.list_indices()
        print(f"indices: {indices}")
    except Exception as exc:
        print(f"indices: unavailable ({type(exc).__name__}: {exc})")

    if not rows:
        print("[WARN] empty table")
        return False

    ids = [row.get("id") for row in rows]
    duplicate_ids = [item for item, count in Counter(ids).items() if count > 1]
    if duplicate_ids:
        ok = False
        print(f"[WARN] duplicate ids: {len(duplicate_ids)}")
    else:
        print("duplicate ids: 0")

    first = rows[0]
    dims = _vector_dims(first)
    print(f"vector dims from first row: {dims}")
    bad_dim_cols = [col for col, dim in dims.items() if dim != expected_dim]
    if bad_dim_cols:
        ok = False
        print(f"[WARN] vector dims not {expected_dim}: {bad_dim_cols}")

    for col in TEXT_COLUMNS_BY_TABLE.get(name, ["text"]):
        if col not in schema_cols:
            continue
        lengths = [_text_len(row.get(col)) for row in rows]
        empty = sum(1 for length in lengths if length == 0)
        stats = _quantiles(lengths)
        print(
            f"{col}_len: min={stats['min']} p25={stats['p25']} median={stats['median']} "
            f"avg={stats['avg']} p75={stats['p75']} max={stats['max']} empty={empty} ({_pct(empty, row_count)})"
        )
        if col == "text" and empty:
            ok = False

    if "source_path" in schema_cols:
        missing_source_paths = sum(1 for row in rows if not _source_path_exists(row.get("source_path")))
        print(f"missing source_path files: {missing_source_paths} ({_pct(missing_source_paths, row_count)})")
        if missing_source_paths:
            ok = False

    if name == "designs":
        suspicious_sections = [row.get("section") for row in rows if not _looks_like_design_heading(row.get("section"))]
        suspicious_subsections = [row.get("subsection") for row in rows if not _looks_like_design_heading(row.get("subsection"))]
        print(f"suspicious section headings: {len(suspicious_sections)} ({_pct(len(suspicious_sections), row_count)})")
        print(f"suspicious subsection headings: {len(suspicious_subsections)} ({_pct(len(suspicious_subsections), row_count)})")
        for value in suspicious_sections[:3]:
            print(f"  section? {_format_preview(value, 160)}")
        for value in suspicious_subsections[:3]:
            print(f"  subsection? {_format_preview(value, 160)}")
        if suspicious_sections or suspicious_subsections:
            ok = False

    if "source" in schema_cols:
        source_counts = Counter(row.get("source") for row in rows)
        print("top sources:")
        for source, count in source_counts.most_common(5):
            print(f"  {source}: {count}")

    rng = random.Random(seed)
    sample_count = min(sample_size, row_count)
    sample_rows = rng.sample(rows, sample_count) if sample_count else []
    print(f"random samples: {sample_count}")
    for idx, row in enumerate(sample_rows, 1):
        print(f"  [{idx}] id={row.get('id')} page={row.get('page')} source={row.get('source')}")
        for key in ("title", "section", "subsection", "article", "chemical_name", "material", "equipment"):
            if key in row:
                print(f"      {key}: {_format_preview(row.get(key), 140)}")
        if show_text > 0:
            print(f"      text: {_format_preview(row.get('text'), show_text)}")

    print(f"status: {'OK' if ok else 'WARN'}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect LanceDB vector DB tables.")
    parser.add_argument("--db-dir", default=VECTOR_DB_CONFIG["VECTOR_DB_DIR"], help="LanceDB directory")
    parser.add_argument("--table", choices=DEFAULT_TABLES + ["all"], default="all", help="Table to inspect")
    parser.add_argument("--sample-size", type=int, default=3, help="Random sample rows per table")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--show-text", type=int, default=300, help="Preview chars for sampled text. Use 0 to hide.")
    parser.add_argument("--expected-dim", type=int, default=VECTOR_DB_CONFIG["EMBEDDING_DIM"], help="Expected vector dimension")
    args = parser.parse_args()

    db_dir = resolve_vector_db_path(args.db_dir)
    if not db_dir.exists():
        raise SystemExit(f"DB directory not found: {db_dir}")

    db = lancedb.connect(str(db_dir))
    available = _table_names(db)
    requested = available if args.table == "all" else [args.table]

    print(f"DB: {db_dir}")
    print(f"available tables: {available}")

    all_ok = True
    for name in requested:
        if name not in available:
            print(f"\n=== {name} ===")
            print("[WARN] table not found")
            all_ok = False
            continue
        table = db.open_table(name)
        rows = _to_rows(table)
        table_ok = _print_table_summary(
            name=name,
            table=table,
            rows=rows,
            expected_dim=args.expected_dim,
            sample_size=args.sample_size,
            seed=args.seed,
            show_text=args.show_text,
        )
        all_ok = all_ok and table_ok

    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
