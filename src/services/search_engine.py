import io
import sys
import math
import re
from collections import OrderedDict
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path

import lancedb
import pandas as pd
from typing import List, Dict, Any, Optional, Set, Tuple

from src.core.models import load_search_models

SEARCH_ENGINE_CONFIG = {
    # 설정
    "DB_PATH": "C:/PnID_RAG/vector_db",
    "DEVICE": "cuda",

    # 1차 검색(임베딩)
    "SEARCH_LIMIT_ACCIDENT": 300,
    "SEARCH_LIMIT_CHEMICAL": 3,
    "SEARCH_LIMIT_LAW": 10,
    "SEARCH_LIMIT_DESIGN": 10,
    "EMBED_CACHE_MAX_SIZE": 2048,
    "PRIMARY_SCORE_LEXICAL_WEIGHT": 0.5,
    "PRIMARY_SCORE_SEMANTIC_WEIGHT": 0.5,
    "PRIMARY_SCORE_BM25_FETCH_MULTIPLIER": 10,  # BM25 조회 배수
    "ACCIDENT_FIELD_MATCH_THRESHOLD": 0.7,  # Accident(material/equipment 필드) 한정 임계치

    # 2차 검색(리랭킹)
    "RERANK_TOP_ACCIDENT": 6,
    "RERANK_TOP_CHEMICAL": 1,
    "RERANK_TOP_LAW": 3,
    "RERANK_TOP_DESIGN": 3,
    "SIMILARITY_THRESHOLD_ACCIDENT": 0.7,
    "SIMILARITY_THRESHOLD_CHEMICAL": 0.7,
    "SIMILARITY_THRESHOLD_LAW": 0.5,
    "SIMILARITY_THRESHOLD_DESIGN": 0.5,
}

class SearchEngine:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SearchEngine, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.db = None
        self.embed_model = None
        self.rerank_model = None
        self._embed_cache: OrderedDict[str, List[float]] = OrderedDict()
        try:
            self.embed_model, self.rerank_model = load_search_models()
        except Exception as e:
            print(f"Error: 검색 모델 로드 실패: {e}")
        try:
            self.db = lancedb.connect(SEARCH_ENGINE_CONFIG["DB_PATH"])
        except Exception as e:
            print(f"Error: {e}")

    def _embed_query(
        self,
        query: str,
        ) -> List[float]:
        """로컬 임베딩 모델로 쿼리를 벡터로 변환"""
        query = (query or "").strip()
        if not query or self.embed_model is None:
            return []
        if query in self._embed_cache:
            self._embed_cache.move_to_end(query)
            return self._embed_cache[query]
        try:
            sink = io.StringIO()
            with redirect_stdout(sink), redirect_stderr(sink):
                encoded = self.embed_model.encode([query], return_dense=True, return_sparse=False)
            dense = encoded.get("dense_vecs")
            if dense is None or len(dense) == 0:
                return []
            vector = dense[0].tolist()
            self._embed_cache[query] = vector
            self._embed_cache.move_to_end(query)
            if len(self._embed_cache) > SEARCH_ENGINE_CONFIG["EMBED_CACHE_MAX_SIZE"]:
                self._embed_cache.popitem(last=False)
            return vector
        except Exception as e:
            print(f"Error (embed): {e}")
            return []

    def _ensure_fts(
        self,
        table: lancedb.Table,
        text_column: str = "text"
        ) -> None:
        """런타임 검색에서는 벡터 DB를 수정하지 않는다."""
        return None

    def _hybrid_search(
        self,
        table: lancedb.Table,
        query_vec: List[float],
        query: str,
        limit: int
        ) -> Optional[pd.DataFrame]:
        """하이브리드 검색 (실패 시 벡터 검색만 시도)"""
        self._ensure_fts(table)
        try:
            return (
                table.search(query_type="hybrid")
                .vector(query_vec)
                .text(query)
                .limit(limit)
                .to_pandas()
            )
        except Exception as e:
            print(f"Error: {e}")
            try:
                return (
                    table.search(query_vec)
                    .metric("cosine")
                    .limit(limit)
                    .to_pandas()
                )
            except Exception:
                return None

    def _table_columns(self, table: lancedb.Table) -> Set[str]:
        try:
            return set(table.schema.names)
        except Exception:
            return set()

    def _table_row_limit(self, table: lancedb.Table, fallback: int) -> int:
        try:
            row_count = int(table.count_rows())
            if row_count > 0:
                if fallback is None:
                    return row_count
                limit = int(fallback)
                if limit <= 0:
                    return row_count
                return min(row_count, limit)
        except Exception:
            pass
        return fallback

    def _field_hybrid_search(
        self,
        table: lancedb.Table,
        query: Optional[str],
        vector_column: Optional[str],
        text_column: Optional[str],
        limit: int,
    ) -> Tuple[Optional[pd.DataFrame], bool]:
        if not query or not text_column or not vector_column:
            return None, False

        query_vec = self._embed_query(query)
        if not query_vec:
            return None, False
        try:
            return (
                table.search(
                    query_type="hybrid",
                    vector_column_name=vector_column,
                    fts_columns=text_column,
                )
                .vector(query_vec)
                .text(query)
                .limit(limit)
                .to_pandas(),
                True,
            )
        except Exception as e:
            print(f"Error: {e}")
            return None, False

    def _pick_value(self, row: Dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in row and row[key] is not None:
                value = row[key]
                if isinstance(value, str):
                    value = value.strip()
                if value not in ("", None):
                    return value
        return None

    def _chemical_display_name(self, row: Dict[str, Any]) -> Optional[str]:
        chemical_name = self._pick_value(row, "chemical_name", "name")
        if not chemical_name:
            return None
        return str(chemical_name).split("|", 1)[0].strip() or None

    def _to_optional_int(self, value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None

    def _to_optional_float(self, value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _primary_score_weights(self) -> Tuple[float, float]:
        lexical_weight = self._to_optional_float(
            SEARCH_ENGINE_CONFIG.get("PRIMARY_SCORE_LEXICAL_WEIGHT")
        )
        semantic_weight = self._to_optional_float(
            SEARCH_ENGINE_CONFIG.get("PRIMARY_SCORE_SEMANTIC_WEIGHT")
        )

        lexical_weight = max(0.0, lexical_weight or 0.0)
        semantic_weight = max(0.0, semantic_weight or 0.0)

        total = lexical_weight + semantic_weight
        if total <= 0.0:
            return 0.3, 0.7

        return lexical_weight / total, semantic_weight / total

    def _distance_to_similarity(self, value: Any) -> Optional[float]:
        distance = self._to_optional_float(value)
        if distance is None:
            return None
        return max(0.0, 1.0 - distance)

    def _extract_primary_score(self, row: Dict[str, Any]) -> Optional[float]:
        score = self._to_optional_float(
            self._pick_value(
                row,
                "_target_relevance_score",
                "_chemical_name_score",
                "_relevance_score",
            )
        )
        if score is not None:
            return score
        return self._distance_to_similarity(self._pick_value(row, "_distance"))

    def _extract_primary_distance(self, row: Dict[str, Any]) -> Optional[float]:
        return self._to_optional_float(self._pick_value(row, "_distance"))

    def _rows_to_docs(self, search_res: pd.DataFrame, text_col: str) -> List[Dict[str, Any]]:
        docs = []
        for row in search_res.to_dict(orient="records"):
            text = self._pick_value(row, text_col, "text", "chunk_text", "content")
            if not text:
                continue

            primary_score = self._extract_primary_score(row)
            primary_distance = self._extract_primary_distance(row)

            display_title = self._pick_value(
                row,
                "source",
                "title",
                "filename",
                "file_name",
                "name",
            )

            docs.append({
                "doc_id": self._pick_value(row, "doc_id", "id", "_rowid"),
                "title": display_title,
                "source": self._pick_value(row, "source", "title", "name", "filename", "file_name"),
                "page": self._to_optional_int(self._pick_value(row, "page", "page_no", "page_num")),
                "pdf_url": self._pick_value(row, "pdf_url", "url", "file_url"),
                "source_path": self._pick_value(row, "source_path", "path", "file_path"),
                "material": self._pick_value(row, "material"),
                "equipment": self._pick_value(row, "equipment"),
                "chemical_name": self._pick_value(row, "chemical_name", "name"),
                "primary_score": primary_score,
                "primary_distance": primary_distance,
                "match_score": primary_score,
                "text": str(text),
            })
        return docs

    def _extract_accident_content(self, text: Any) -> str:
        value = str(text or "")
        if not value:
            return ""
        match = re.search(r"\[사고내용\]\s*(.*?)(?=\n\[[^\]]+\]|\Z)", value, re.DOTALL)
        if not match:
            return value
        return match.group(1).strip()

    def _filter_accident_docs_by_content_material(
        self,
        docs: List[Dict[str, Any]],
        target_material: Optional[str],
    ) -> List[Dict[str, Any]]:
        if not docs or not target_material:
            return docs

        filtered = []
        for doc in docs:
            content = self._extract_accident_content(doc.get("text") or doc.get("chunk_text"))
            if target_material in content:
                filtered.append(doc)

        return filtered or docs

    def _empty_like(self, search_res: Optional[pd.DataFrame]) -> pd.DataFrame:
        if search_res is None:
            return pd.DataFrame()
        return search_res.iloc[0:0].copy()

    def _filter_contains(
        self,
        search_res: Optional[pd.DataFrame],
        column: str,
        target: Optional[str],
    ) -> pd.DataFrame:
        if search_res is None or search_res.empty or not target or column not in search_res.columns:
            return self._empty_like(search_res)
        return search_res[
            search_res[column].astype(str).str.contains(str(target), case=False, na=False, regex=False)
        ].copy()

    def _filter_by_relevance(
        self,
        search_res: Optional[pd.DataFrame],
        score_column: str,
        target: Optional[str],
        threshold: float,
    ) -> pd.DataFrame:
        if search_res is None or search_res.empty or not target or score_column not in search_res.columns:
            return self._empty_like(search_res)
        return search_res[
            search_res[score_column].astype(float).fillna(0.0) >= threshold
        ].copy()

    def _normalize_lookup_text(self, value: Any) -> str:
        return re.sub(r"[^0-9A-Za-z가-힣]+", "", str(value or "")).lower()

    def _chemical_name_column(self, search_res: Optional[pd.DataFrame]) -> Optional[str]:
        if search_res is None:
            return None
        if "chemical_name" in search_res.columns:
            return "chemical_name"
        if "name" in search_res.columns:
            return "name"
        return None

    def _chemical_name_vector_column(self, search_res: Optional[pd.DataFrame]) -> Optional[str]:
        if search_res is None:
            return None
        if "chemical_name_vector" in search_res.columns:
            return "chemical_name_vector"
        return None

    def _cosine_similarity(self, left: Any, right: Any) -> float:
        if left is None or right is None:
            return 0.0
        try:
            left_values = [float(v) for v in left]
            right_values = [float(v) for v in right]
            if not left_values or not right_values:
                return 0.0
            dot = sum(a * b for a, b in zip(left_values, right_values))
            left_norm = math.sqrt(sum(a * a for a in left_values))
            right_norm = math.sqrt(sum(b * b for b in right_values))
            if left_norm == 0.0 or right_norm == 0.0:
                return 0.0
            return dot / (left_norm * right_norm)
        except Exception:
            return 0.0

    def _normalize_score_series(self, scores: pd.Series) -> pd.Series:
        numeric_scores = pd.to_numeric(scores, errors="coerce").fillna(0.0).astype(float)
        if numeric_scores.empty:
            return numeric_scores
        max_score = float(numeric_scores.max())
        if max_score <= 0.0:
            return numeric_scores * 0.0
        return (numeric_scores / max_score).clip(lower=0.0, upper=1.0)

    def _drop_vector_columns(self, search_res: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        """유사도 계산 후 메모리 절감을 위해 *_vector 컬럼을 제거한다."""
        if search_res is None or search_res.empty:
            return search_res
        vector_columns = [column for column in search_res.columns if str(column).endswith("_vector")]
        if not vector_columns:
            return search_res
        return search_res.drop(columns=vector_columns, errors="ignore")

    def _bm25_scores_by_id(
        self,
        table: lancedb.Table,
        query: str,
        limit: int,
        text_column: Optional[str] = None,
    ) -> Dict[str, float]:
        """BM25 점수를 id 기준으로 정규화해 반환한다."""
        if not query:
            return {}
        self._ensure_fts(table)
        try:
            search_builder = table.search(
                query,
                query_type="fts",
                fts_columns=text_column,
            )
            bm25_df = search_builder.limit(limit).to_pandas()
        except Exception as e:
            print(f"Error (bm25): {e}")
            return {}
        if bm25_df is None or bm25_df.empty:
            return {}
        if "id" not in bm25_df.columns or "_score" not in bm25_df.columns:
            return {}

        normalized_scores = self._normalize_score_series(bm25_df["_score"])
        score_map: Dict[str, float] = {}
        for doc_id, score in zip(bm25_df["id"].astype(str), normalized_scores):
            score_map[doc_id] = float(score)
        return score_map

    def _numeric_score_series(
        self,
        search_res: Optional[pd.DataFrame],
        column: str,
    ) -> pd.Series:
        index = search_res.index if search_res is not None else pd.RangeIndex(0)
        if search_res is None or search_res.empty or column not in search_res.columns:
            return pd.Series(0.0, index=index, dtype=float)
        return pd.to_numeric(search_res[column], errors="coerce").fillna(0.0)

    def _zero_score_series(self, search_res: Optional[pd.DataFrame]) -> pd.Series:
        index = search_res.index if search_res is not None else pd.RangeIndex(0)
        return pd.Series(0.0, index=index, dtype=float)

    def _field_similarity_scores(
        self,
        table: lancedb.Table,
        search_res: Optional[pd.DataFrame],
        target_value: Optional[str],
        text_column: str,
        vector_column: Optional[str] = None,
    ) -> Tuple[pd.Series, bool]:
        """필드 검색 결과의 BM25+cosine 하이브리드 점수를 계산한다."""
        if search_res is None or search_res.empty or not target_value or text_column not in search_res.columns:
            return self._zero_score_series(search_res), False

        lexical_scores = self._zero_score_series(search_res)
        if "id" in search_res.columns:
            bm25_multiplier = int(
                SEARCH_ENGINE_CONFIG.get("PRIMARY_SCORE_BM25_FETCH_MULTIPLIER", 10) or 10
            )
            bm25_multiplier = max(1, bm25_multiplier)
            bm25_limit = self._table_row_limit(
                table, max(len(search_res) * bm25_multiplier, len(search_res))
            )
            bm25_score_map = self._bm25_scores_by_id(
                table=table,
                query=target_value,
                limit=bm25_limit,
                text_column=text_column,
            )
            if bm25_score_map:
                lexical_scores = search_res["id"].astype(str).map(bm25_score_map).fillna(0.0).astype(float)

        if not vector_column or vector_column not in search_res.columns:
            return lexical_scores, False

        target_vec = self._embed_query(target_value)
        if not target_vec:
            return lexical_scores, False

        lexical_weight, semantic_weight = self._primary_score_weights()
        semantic_scores = search_res[vector_column].apply(
            lambda value: self._cosine_similarity(target_vec, value)
        ).astype(float)
        semantic_scores = semantic_scores.clip(lower=0.0, upper=1.0)
        hybrid_scores = (
            (semantic_scores * semantic_weight)
            + (lexical_scores * lexical_weight)
        ).astype(float)
        return hybrid_scores, True

    def _apply_doc_hybrid_relevance(
        self,
        table: lancedb.Table,
        search_res: Optional[pd.DataFrame],
        query: str,
        text_column: str,
        vector_column: Optional[str] = "text_vector",
    ) -> pd.DataFrame:
        """법규/설계 검색 결과에 BM25+semantic 하이브리드 1차 점수를 부여한다."""
        if search_res is None or search_res.empty:
            return self._empty_like(search_res)

        ranked = search_res.copy()
        lexical_scores = self._zero_score_series(ranked)
        if "id" in ranked.columns:
            bm25_multiplier = int(
                SEARCH_ENGINE_CONFIG.get("PRIMARY_SCORE_BM25_FETCH_MULTIPLIER", 10) or 10
            )
            bm25_multiplier = max(1, bm25_multiplier)
            bm25_limit = self._table_row_limit(
                table, max(len(ranked) * bm25_multiplier, len(ranked))
            )
            bm25_score_map = self._bm25_scores_by_id(
                table=table,
                query=query,
                limit=bm25_limit,
                text_column=text_column,
            )
            if bm25_score_map:
                lexical_scores = ranked["id"].astype(str).map(bm25_score_map).fillna(0.0).astype(float)

        semantic_scores = self._zero_score_series(ranked)
        if vector_column and vector_column in ranked.columns:
            query_vec = self._embed_query(query)
            if query_vec:
                semantic_scores = ranked[vector_column].apply(
                    lambda value: max(0.0, self._cosine_similarity(query_vec, value))
                ).astype(float)
                semantic_scores = semantic_scores.clip(lower=0.0, upper=1.0)

        lexical_weight, semantic_weight = self._primary_score_weights()
        hybrid_scores = (
            (semantic_scores * semantic_weight)
            + (lexical_scores * lexical_weight)
        ).astype(float)

        if "_relevance_score" in ranked.columns:
            ranked["_relevance_score_raw"] = pd.to_numeric(
                ranked["_relevance_score"], errors="coerce"
            ).fillna(0.0)
        ranked["_lexical_relevance_score"] = lexical_scores
        ranked["_semantic_relevance_score"] = semantic_scores
        ranked["_relevance_score"] = hybrid_scores
        ranked = self._drop_vector_columns(ranked)
        return ranked.sort_values("_relevance_score", ascending=False)

    def _combine_search_frames_by_id(
        self,
        frames: List[pd.DataFrame],
        score_columns: Tuple[str, ...],
    ) -> pd.DataFrame:
        valid_frames = [frame.copy() for frame in frames if frame is not None and not frame.empty]
        if not valid_frames:
            return pd.DataFrame()

        combined = pd.concat(valid_frames, ignore_index=True, sort=False)
        if "id" in combined.columns:
            aggregate: Dict[str, str] = {}
            for column in combined.columns:
                if column == "id":
                    continue
                aggregate[column] = "max" if column in score_columns else "first"
            combined = combined.groupby("id", as_index=False).agg(aggregate)
        else:
            dedup_cols = [col for col in ("text", "source", "page") if col in combined.columns]
            if dedup_cols:
                combined = combined.drop_duplicates(subset=dedup_cols, keep="first")
            else:
                combined = combined.drop_duplicates(keep="first")

        for score_column in score_columns:
            if score_column not in combined.columns:
                combined[score_column] = 0.0
            else:
                combined[score_column] = pd.to_numeric(combined[score_column], errors="coerce").fillna(0.0)
        return combined

    def _sort_accident_subset_by_target_relevance(
        self,
        search_res: Optional[pd.DataFrame],
        case_code: str,
    ) -> pd.DataFrame:
        if search_res is None or search_res.empty:
            return self._empty_like(search_res)

        ranked = search_res.copy()
        material_scores = self._numeric_score_series(ranked, "_material_relevance_score")
        equipment_scores = self._numeric_score_series(ranked, "_equipment_relevance_score")

        if case_code == "1-1":
            ranked["_target_relevance_score"] = (material_scores + equipment_scores) / 2
        elif case_code == "1-2":
            ranked["_target_relevance_score"] = material_scores
        elif case_code == "1-3":
            ranked["_target_relevance_score"] = equipment_scores
        else:
            ranked["_target_relevance_score"] = material_scores.where(
                material_scores >= equipment_scores, equipment_scores
            )

        ranked = ranked.sort_values("_target_relevance_score", ascending=False)
        return ranked

    def _build_risk_accident_search_res(
        self,
        table: lancedb.Table,
        target_material: Optional[str],
        target_equipment: Optional[str],
    ) -> pd.DataFrame:
        columns = self._table_columns(table)
        limit = self._table_row_limit(table, SEARCH_ENGINE_CONFIG["SEARCH_LIMIT_ACCIDENT"])

        material_res = None
        if target_material and "material" in columns and "material_vector" in columns:
            material_res, _ = self._field_hybrid_search(
                table=table,
                query=target_material,
                vector_column="material_vector",
                text_column="material",
                limit=limit,
            )
            if material_res is not None and not material_res.empty:
                material_scores, _ = self._field_similarity_scores(
                    table=table,
                    search_res=material_res,
                    target_value=target_material,
                    text_column="material",
                    vector_column="material_vector",
                )
                material_res = material_res.copy()
                material_res["_material_relevance_score"] = material_scores
                material_res = self._drop_vector_columns(material_res)

        equipment_res = None
        if target_equipment and "equipment" in columns and "equipment_vector" in columns:
            equipment_res, _ = self._field_hybrid_search(
                table=table,
                query=target_equipment,
                vector_column="equipment_vector",
                text_column="equipment",
                limit=limit,
            )
            if equipment_res is not None and not equipment_res.empty:
                equipment_scores, _ = self._field_similarity_scores(
                    table=table,
                    search_res=equipment_res,
                    target_value=target_equipment,
                    text_column="equipment",
                    vector_column="equipment_vector",
                )
                equipment_res = equipment_res.copy()
                equipment_res["_equipment_relevance_score"] = equipment_scores
                equipment_res = self._drop_vector_columns(equipment_res)

        return self._combine_search_frames_by_id(
            [
                material_res,
                equipment_res,
            ],
            ("_material_relevance_score", "_equipment_relevance_score"),
        )

    def _build_risk_chemical_search_res(
        self,
        table: lancedb.Table,
        target_material: Optional[str],
    ) -> Tuple[Optional[pd.DataFrame], Optional[str], bool]:
        columns = self._table_columns(table)
        if "chemical_name" in columns:
            name_col = "chemical_name"
        elif "name" in columns:
            name_col = "name"
        else:
            name_col = None

        if not target_material or not name_col:
            return None, name_col, False

        vector_col = "chemical_name_vector" if "chemical_name_vector" in columns else None
        search_res, vector_used = self._field_hybrid_search(
            table=table,
            query=target_material,
            vector_column=vector_col,
            text_column=name_col,
            limit=self._table_row_limit(table, SEARCH_ENGINE_CONFIG["SEARCH_LIMIT_CHEMICAL"]),
        )
        if search_res is None or search_res.empty:
            return search_res, name_col, vector_used

        chemical_scores, _ = self._field_similarity_scores(
            table=table,
            search_res=search_res,
            target_value=target_material,
            text_column=name_col,
            vector_column=vector_col,
        )
        ranked = search_res.copy()
        ranked["_chemical_name_score"] = chemical_scores
        ranked = self._drop_vector_columns(ranked)

        filtered_res, _ = self._filter_chemical_name_matches(ranked, target_material)
        if filtered_res is not None and not filtered_res.empty:
            ranked = filtered_res

        ranked = ranked.sort_values("_chemical_name_score", ascending=False)
        return ranked, name_col, vector_used

    def _filter_chemical_name_matches(
        self,
        search_res: Optional[pd.DataFrame],
        target_material: Optional[str],
    ) -> Tuple[pd.DataFrame, Optional[str]]:
        name_col = self._chemical_name_column(search_res)
        if search_res is None or search_res.empty or not target_material:
            return self._empty_like(search_res), name_col
        if not name_col:
            return search_res.copy(), None

        normalized_target = self._normalize_lookup_text(target_material)
        if not normalized_target:
            return search_res.copy(), name_col

        mask = search_res[name_col].astype(str).apply(
            lambda value: normalized_target in self._normalize_lookup_text(value)
        )
        return search_res[mask].copy(), name_col

    def _rerank_chemical_name_field(
        self,
        docs: List[Dict[str, Any]],
        target_material: Optional[str],
        top_k: int,
        threshold: float,
        show_progress: bool = False,
    ) -> List[Dict[str, Any]]:
        """화학물질명 컬럼 기준으로 2차 재정렬한다."""
        if not docs:
            return []
        if not target_material:
            return [{**doc, "score": 0.0, "rerank_score": 0.0} for doc in docs[:top_k]]
        if self.rerank_model is None:
            return [{**doc, "score": 0.0, "rerank_score": 0.0} for doc in docs[:top_k]]

        try:
            pairs = []
            for doc in docs:
                chemical_name = self._pick_value(doc, "chemical_name", "title", "source", "name")
                pairs.append([target_material, str(chemical_name or "")])

            scores = self._compute_rerank_scores(pairs, show_progress)
            if isinstance(scores, (int, float)):
                scores = [scores]

            results = []
            ranked_pairs = sorted(
                zip(docs, scores),
                key=lambda item: (
                    float(item[1]),
                    self._to_optional_float(item[0].get("primary_score")) or 0.0,
                ),
                reverse=True,
            )
            for doc, score in ranked_pairs:
                s = float(score)
                if s < threshold:
                    continue
                if len(results) >= top_k:
                    break
                results.append({
                    **doc,
                    "score": round(s, 4),
                    "rerank_score": round(s, 4),
                })
            return results
        except Exception as e:
            print(f"Error (chemical rerank): {e}")
            return [{**doc, "score": 0.0, "rerank_score": 0.0} for doc in docs[:top_k]]

    def _risk_case_label(self, case_code: str) -> str:
        mapping = {
            "1-1": "(1-1) 물질 매칭 YES + 설비 매칭 YES",
            "1-2": "(1-2) 물질 매칭 YES + 설비 매칭 NO",
            "1-3": "(1-3) 물질 매칭 NO + 설비 매칭 YES",
            "1-4": "(1-4) 물질 매칭 NO + 설비 매칭 NO + 물질 정보 YES",
            "1-5": "(1-5) 물질 매칭 NO + 설비 매칭 NO + 물질 정보 NO",
        }
        return mapping.get(case_code, mapping["1-4"])

    def _prepare_accident_subset_docs(
        self,
        search_res: Optional[pd.DataFrame],
        case_code: str,
        target_material: Optional[str],
    ) -> List[Dict[str, Any]]:
        if search_res is None or search_res.empty:
            return []

        ranked_res = self._sort_accident_subset_by_target_relevance(search_res, case_code)
        if ranked_res is None or ranked_res.empty:
            return []

        text_col = "text" if "text" in ranked_res.columns else ranked_res.columns[0]
        docs_list = self._rows_to_docs(ranked_res, text_col)
        if case_code in ("1-1", "1-2"):
            docs_list = self._filter_accident_docs_by_content_material(docs_list, target_material)
        return docs_list

    def _rerank_accident_subset_docs(
        self,
        docs: List[Dict[str, Any]],
        case_code: str,
        target_material: Optional[str],
        target_equipment: Optional[str],
        threshold: float,
        show_progress: bool = False,
    ) -> List[Dict[str, Any]]:
        """사고사례 필드값 기준으로 2차 재정렬한다."""
        if not docs:
            return []
        if self.rerank_model is None:
            return [{**doc, "score": 0.0, "rerank_score": 0.0} for doc in docs]

        try:
            scores: List[float] = []
            if case_code == "1-1":
                pairs_material = []
                pairs_equipment = []
                for doc in docs:
                    material_value = self._pick_value(doc, "material", "text", "chunk_text")
                    equipment_value = self._pick_value(doc, "equipment", "text", "chunk_text")
                    pairs_material.append([str(target_material or ""), str(material_value or "")])
                    pairs_equipment.append([str(target_equipment or ""), str(equipment_value or "")])

                material_scores = self._compute_rerank_scores(pairs_material, show_progress)
                equipment_scores = self._compute_rerank_scores(pairs_equipment, show_progress)
                if isinstance(material_scores, (int, float)):
                    material_scores = [material_scores]
                if isinstance(equipment_scores, (int, float)):
                    equipment_scores = [equipment_scores]
                scores = [
                    (float(ms) + float(es)) / 2.0
                    for ms, es in zip(material_scores, equipment_scores)
                ]
            elif case_code == "1-2":
                pairs = []
                for doc in docs:
                    material_value = self._pick_value(doc, "material", "text", "chunk_text")
                    pairs.append([str(target_material or ""), str(material_value or "")])
                scores = self._compute_rerank_scores(pairs, show_progress)
                if isinstance(scores, (int, float)):
                    scores = [scores]
                scores = [float(score) for score in scores]
            else:
                pairs = []
                for doc in docs:
                    equipment_value = self._pick_value(doc, "equipment", "text", "chunk_text")
                    pairs.append([str(target_equipment or ""), str(equipment_value or "")])
                scores = self._compute_rerank_scores(pairs, show_progress)
                if isinstance(scores, (int, float)):
                    scores = [scores]
                scores = [float(score) for score in scores]

            results = []
            ranked_pairs = sorted(
                zip(docs, scores),
                key=lambda item: (
                    float(item[1]),
                    self._to_optional_float(item[0].get("primary_score")) or 0.0,
                ),
                reverse=True,
            )
            for doc, score in ranked_pairs:
                s = float(score)
                if s < threshold:
                    continue
                results.append({
                    **doc,
                    "score": round(s, 4),
                    "rerank_score": round(s, 4),
                })
            return results
        except Exception as e:
            print(f"Error (accident rerank): {e}")
            return [{**doc, "score": 0.0, "rerank_score": 0.0} for doc in docs]

    def _select_accident_subset(
        self,
        search_res: Optional[pd.DataFrame],
        target_material: Optional[str],
        target_equipment: Optional[str],
        threshold: float,
        show_progress: bool = False,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        empty = self._empty_like(search_res)
        match_threshold = SEARCH_ENGINE_CONFIG.get("ACCIDENT_FIELD_MATCH_THRESHOLD", 0.7)

        material_res = self._filter_by_relevance(search_res, "_material_relevance_score", target_material, match_threshold)
        equipment_res = self._filter_by_relevance(search_res, "_equipment_relevance_score", target_equipment, match_threshold)

        if target_material and target_equipment:
            both_res = self._filter_by_relevance(material_res, "_equipment_relevance_score", target_equipment, match_threshold)
        else:
            both_res = empty

        both_docs = self._rerank_accident_subset_docs(
            self._prepare_accident_subset_docs(both_res, "1-1", target_material),
            "1-1",
            target_material,
            target_equipment,
            threshold,
            show_progress,
        )
        material_docs = self._rerank_accident_subset_docs(
            self._prepare_accident_subset_docs(material_res, "1-2", target_material),
            "1-2",
            target_material,
            target_equipment,
            threshold,
            show_progress,
        )
        equipment_docs = self._rerank_accident_subset_docs(
            self._prepare_accident_subset_docs(equipment_res, "1-3", target_material),
            "1-3",
            target_material,
            target_equipment,
            threshold,
            show_progress,
        )

        both_count = len(both_docs)
        material_count = len(material_docs)
        equipment_count = len(equipment_docs)

        selected_case_code = "1-4"
        selected_scope = "none"
        selected_docs: List[Dict[str, Any]] = []

        if both_count > 0:
            selected_case_code = "1-1"
            selected_scope = "both"
            selected_docs = both_docs
        elif material_count > 0:
            selected_case_code = "1-2"
            selected_scope = "material"
            selected_docs = material_docs
        elif equipment_count > 0:
            selected_case_code = "1-3"
            selected_scope = "equipment"
            selected_docs = equipment_docs

        selected_count = len(selected_docs)
        meta = {
            "risk_count": selected_count,
            "selected_accident_count": selected_count,
            "selected_risk_case_code": selected_case_code,
            "selected_risk_case": self._risk_case_label(selected_case_code),
            "selected_accident_scope": selected_scope,
            "both_count": both_count,
            "material_count": material_count,
            "equipment_count": equipment_count,
            "material_match": material_count > 0,
            "equipment_match": equipment_count > 0,
            "pair_match": both_count > 0,
        }
        return meta, selected_docs

    def _rerank_threshold(self, table_name: str) -> float:
        specific_key = f"SIMILARITY_THRESHOLD_{str(table_name or '').upper()}"
        if specific_key not in SEARCH_ENGINE_CONFIG:
            raise KeyError(f"{specific_key} 설정이 없습니다.")

        threshold = self._to_optional_float(SEARCH_ENGINE_CONFIG.get(specific_key))
        if threshold is None:
            raise ValueError(f"{specific_key} 값이 비어 있거나 숫자가 아닙니다.")

        return threshold

    def _compute_rerank_scores(
        self,
        pairs: List[List[str]],
        show_progress: bool = False,
    ):
        if show_progress:
            return self.rerank_model.compute_score(pairs, normalize=True)

        sink = io.StringIO()
        with redirect_stdout(sink), redirect_stderr(sink):
            return self.rerank_model.compute_score(pairs, normalize=True)

    def _rerank(
        self,
        query: str,
        docs: List[Dict[str, Any]],
        top_k: int,
        threshold: float,
        show_progress: bool = False
        ) -> List[Dict[str, Any]]:
        """로컬 리랭킹 모델로 문서를 재정렬"""
        if not docs:
            return []
        if not query:
            return [{**doc, "score": 0.0, "rerank_score": 0.0} for doc in docs[:top_k]]
        if self.rerank_model is None:
            return [{**doc, "score": 0.0, "rerank_score": 0.0} for doc in docs[:top_k]]

        try:
            pairs = [
                [query, str(doc.get("text") or doc.get("chunk_text") or "")]
                for doc in docs
            ]
            scores = self._compute_rerank_scores(pairs, show_progress)
            if isinstance(scores, (int, float)):
                scores = [scores]

            results = []
            for doc, score in sorted(zip(docs, scores), key=lambda x: x[1], reverse=True):
                s = float(score)
                if s < threshold:
                    continue
                if len(results) >= top_k:
                    break
                results.append({
                    **doc,
                    "score": round(s, 4),
                    "rerank_score": round(s, 4),
                })

            return results

        except Exception as e:
            print(f"Error (rerank): {e}")
            return [{**doc, "score": 0.0, "rerank_score": 0.0} for doc in docs[:top_k]]

    def _apply_match_scores(self, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        scored_docs: List[Dict[str, Any]] = []
        for doc in docs:
            if not isinstance(doc, dict):
                continue

            primary_score = self._to_optional_float(doc.get("primary_score"))
            if primary_score is None:
                primary_score = self._to_optional_float(doc.get("match_score"))

            rerank_score = self._to_optional_float(doc.get("rerank_score"))
            if rerank_score is None:
                rerank_score = self._to_optional_float(doc.get("score"))

            if primary_score is None:
                scored_docs.append(doc)
                continue

            rerank_score = rerank_score if rerank_score is not None else 0.0
            scored_docs.append({
                **doc,
                "primary_score": round(primary_score, 4),
                "match_score": round(primary_score, 4),
                "score": round(primary_score, 4),
                "rerank_score": round(rerank_score, 4),
            })

        scored_docs.sort(
            key=lambda item: (
                self._to_optional_float(item.get("rerank_score")) or 0.0,
                self._to_optional_float(item.get("primary_score")) or 0.0,
            ),
            reverse=True,
        )
        return scored_docs

    def search(
        self,
        query: str,
        intents: List[str],
        filters: Dict[str, str] = None,
        show_progress: bool = False,
    ) -> Dict[str, Any]:
        """
        의도에 따라 적절한 테이블을 검색하고 결과를 병합하여 반환
        """
        results = {
            "accident_docs": [],
            "chemical_docs": [],
            "law_docs": [],
            "design_docs": [],
            "search_metadata": {
                "risk_count": 0,
                "selected_accident_count": 0,
                "selected_risk_case_code": "1-5",
                "selected_risk_case": self._risk_case_label("1-5"),
                "selected_accident_scope": "none",
                "both_count": 0,
                "material_count": 0,
                "equipment_count": 0,
                "material_match": False,
                "equipment_match": False,
                "pair_match": False,
                "chemical_found": False,
                "chemical_name_column_used": None,
                "chemical_name_vector_used": False,
            }
        }

        filters = filters or {}

        if self.db is None:
            print("Error: DB 연결 안됨")
            return results

        query_vec: List[float] = []
        if any(intent in intents for intent in ("law", "design")):
            query_vec = self._embed_query(query)
            if not query_vec:
                print("Error: 쿼리 임베딩 실패")
                return results

        # 1. 공정위험성 근거 문서 검색
        if "risk" in intents:
            target_mat = filters.get("material")
            target_eq = filters.get("equipment")

            # 사고 사례 검색
            try:
                table = self.db.open_table("accidents")
                search_res = self._build_risk_accident_search_res(
                    table=table,
                    target_material=target_mat,
                    target_equipment=target_eq,
                )

                if search_res is not None and not search_res.empty:
                    accident_threshold = self._rerank_threshold("accident")
                    risk_meta, selected_docs = self._select_accident_subset(
                        search_res=search_res,
                        target_material=target_mat,
                        target_equipment=target_eq,
                        threshold=accident_threshold,
                        show_progress=show_progress,
                    )
                    results["search_metadata"].update(risk_meta)
                    results["accident_docs"] = self._apply_match_scores(
                        selected_docs[:SEARCH_ENGINE_CONFIG["RERANK_TOP_ACCIDENT"]]
                    )
            except Exception as e:
                print(f"Error: Accidents 검색 실패: {e}")

            # 화학물질 정보 검색
            try:
                table = self.db.open_table("chemicals")
                search_res = None
                name_col = None
                vector_used = False

                if target_mat:
                    search_res, name_col, vector_used = self._build_risk_chemical_search_res(table, target_mat)

                results["search_metadata"]["chemical_name_column_used"] = name_col
                results["search_metadata"]["chemical_name_vector_used"] = vector_used

                if search_res is not None and not search_res.empty:
                    text_col = "text" if "text" in search_res.columns else search_res.columns[0]
                    docs_list = self._rows_to_docs(search_res, text_col)
                    results["chemical_docs"] = self._apply_match_scores(
                        self._rerank_chemical_name_field(
                            docs_list,
                            target_mat,
                            SEARCH_ENGINE_CONFIG["RERANK_TOP_CHEMICAL"],
                            self._rerank_threshold("chemical"),
                            show_progress=show_progress,
                        )
                    )
                results["search_metadata"]["chemical_found"] = bool(results["chemical_docs"])
                if results["search_metadata"].get("selected_risk_case_code") in ("1-4", "1-5"):
                    results["search_metadata"]["selected_risk_case_code"] = (
                        "1-4" if results["search_metadata"]["chemical_found"] else "1-5"
                    )
                    results["search_metadata"]["selected_risk_case"] = self._risk_case_label(
                        results["search_metadata"]["selected_risk_case_code"]
                    )
            except Exception as e:
                print(f"Error: Chemicals 검색 실패: {e}")

        # 2. 법규위반 근거 문서 검색
        if "law" in intents:
            try:
                table = self.db.open_table("laws")
                search_res = self._hybrid_search(
                    table, query_vec, query, SEARCH_ENGINE_CONFIG["SEARCH_LIMIT_LAW"]
                )

                if search_res is not None and not search_res.empty:
                    text_col = "text" if "text" in search_res.columns else search_res.columns[0]
                    vector_col = "text_vector" if "text_vector" in search_res.columns else None
                    search_res = self._apply_doc_hybrid_relevance(
                        table=table,
                        search_res=search_res,
                        query=query,
                        text_column=text_col,
                        vector_column=vector_col,
                    )
                    docs_list = self._rows_to_docs(search_res, text_col)
                    results["law_docs"] = self._rerank(
                        query,
                        docs_list,
                        SEARCH_ENGINE_CONFIG["RERANK_TOP_LAW"],
                        self._rerank_threshold("law"),
                        show_progress,
                    )
            except Exception as e:
                print(f"Error: Laws 검색 실패: {e}")

        # 3. 설계오류 근거 문서 검색
        if "design" in intents:
            try:
                table = self.db.open_table("designs")
                search_res = self._hybrid_search(
                    table, query_vec, query, SEARCH_ENGINE_CONFIG["SEARCH_LIMIT_DESIGN"]
                )

                if search_res is not None and not search_res.empty:
                    text_col = "text" if "text" in search_res.columns else search_res.columns[0]
                    vector_col = "text_vector" if "text_vector" in search_res.columns else None
                    search_res = self._apply_doc_hybrid_relevance(
                        table=table,
                        search_res=search_res,
                        query=query,
                        text_column=text_col,
                        vector_column=vector_col,
                    )
                    docs_list = self._rows_to_docs(search_res, text_col)
                    results["design_docs"] = self._rerank(
                        query,
                        docs_list,
                        SEARCH_ENGINE_CONFIG["RERANK_TOP_DESIGN"],
                        self._rerank_threshold("design"),
                        show_progress,
                    )
            except Exception as e:
                print(f"Error: Designs 검색 실패: {e}")

        return results


# 검색 엔진 테스트
if __name__ == "__main__":
    output_dir = Path(__file__).resolve().parents[2] / "tests" / "test_search_engine"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = output_dir / f"search_engine_{timestamp}.txt"

    class _Tee:
        def __init__(self, *streams):
            self.streams = streams

        def write(self, data):
            for stream in self.streams:
                stream.write(data)
                stream.flush()
            return len(data)

        def flush(self):
            for stream in self.streams:
                stream.flush()

    def _score_text(doc: Dict[str, Any]) -> str:
        parts = []

        primary_score = doc.get("primary_score")
        if isinstance(primary_score, (int, float)):
            parts.append(f"1차={float(primary_score):.4f}")

        rerank_score = doc.get("rerank_score")
        if isinstance(rerank_score, (int, float)):
            parts.append(f"2차={float(rerank_score):.4f}")

        score = doc.get("score")
        if not parts and isinstance(score, (int, float)):
            parts.append(f"score={float(score):.4f}")

        return " | ".join(parts) if parts else "score=None"

    engine = SearchEngine()

    test_cases = [
        {
            "name": "TEST : 공정위험성 근거 문서 검색",
            "query": "황산이 흐르는 배관의 핀홀 부식으로 인해 작업자가 화학 화상을 입은 사고가 존재해?",
            "intents": ["risk"],
            "filters": {"material": "황산", "equipment": "배관"}
        },
        {
            "name": "TEST : 법규위반 근거 문서 검색",
            "query": "인화성 액체를 사용하는 장소에서 전기 설비를 방폭 구조로 설계하지 않았을 때 산업안전보건법 등에 따른 처벌을 찾아줘",
            "intents": ["law"],
            "filters": {}
        },
        {
            "name": "TEST : 설계오류 근거 문서 검색",
            "query": "반응기 내부 압력이 상승할 때 안전밸브와 파열판을 직렬로 설치해야 하는 물질 조건과 설치 시 주의사항은?",
            "intents": ["design"],
            "filters": {}
        }
    ]

    with open(log_path, "w", encoding="utf-8") as log_file:
        tee = _Tee(sys.stdout, log_file)
        with redirect_stdout(tee), redirect_stderr(tee):
            for i, tc in enumerate(test_cases, 1):
                print("\n" + "═"*60)
                print(f"{tc['name']}")
                print("═"*60)
                print(f"▶ Query: '{tc['query']}'")
                print(f"▶ Intents: {tc['intents']}")
                print(f"▶ Filters: {tc['filters']}")

                # 검색 실행
                results = engine.search(
                    query=tc['query'],
                    intents=tc['intents'],
                    filters=tc['filters'],
                    show_progress=False
                )

                target_keys = ["accident_docs", "chemical_docs", "law_docs", "design_docs"]
                for key in target_keys:
                    docs = results.get(key, [])
                    if not docs:
                        continue

                    print("\n" + "-"*40)
                    print(f"{key} 결과 (최종 {len(docs)}건 반환)")
                    print("-"*40)

                    for rank, doc in enumerate(docs[:3], 1):
                        text_preview = str(doc.get('text', ''))[:1000].replace('\n', ' ')
                        print(f"[ {rank}위 ({_score_text(doc)}) ]\n{text_preview}...(중략)\n")
