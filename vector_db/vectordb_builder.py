from __future__ import annotations
import argparse
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock, Thread
import pandas as pd
import fitz
import lancedb
import pyarrow as pa
VECTOR_DB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VECTOR_DB_ROOT))
from config import EMBED_MODEL


def resolve_vector_db_path(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return VECTOR_DB_ROOT / path


TABLE_NAMES = ("accidents", "laws", "designs", "chemicals", "basics")

VECTOR_DB_CONFIG = {
    "VECTOR_DB_DIR": "./data/vector_db",
    "ACCIDENTS_DIR": "./data/corpus/accidents",
    "LAWS_DIR": "./data/corpus/laws",
    "DESIGNS_DIR": "./data/corpus/designs",
    "CHEMICALS_DIR": "./data/corpus/chemicals",
    "BASICS_DIR": "./data/corpus/basics",
    "EMBEDDING_MODEL": EMBED_MODEL,
    "EMBEDDING_DIM": 1024,
    "EMBED_BATCH_SIZE": 8,
    "PARSE_WORKERS": min(8, os.cpu_count() or 1),
    "EMBEDDING_CACHE_ENABLED": True,
    "CHUNK_MAX_TOKENS": 1000,
    "CHUNK_OVERLAP_TOKENS": 100,
}

CONFIG = dict(VECTOR_DB_CONFIG)
logging.getLogger("transformers.tokenization_utils_base").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)


class TerminalProgressBar:
    """터미널에 고정 폭 단일 줄 진행률 막대를 출력"""

    _last_rendered_line_length = 0
    _job_started_at: float | None = None

    def __init__(self, label: str, total: int, width: int = 28) -> None:
        """진행률 막대를 초기화"""
        if TerminalProgressBar._job_started_at is None:
            TerminalProgressBar._job_started_at = time.monotonic()
        self.label = label
        self.total = total
        self.width = width
        self.current = 0
        self._lock = Lock()
        self._stop_event = Event()
        self._thread = Thread(target=self._render_elapsed, daemon=True)
        self._thread.start()
        self.render()

    def advance(self, amount: int = 1) -> None:
        """진행 수치를 증가"""
        with self._lock:
            self.current += amount
            self._render_locked()

    def finish(self) -> None:
        """진행률 막대를 완료 상태로 종료"""
        self._stop_event.set()
        self._thread.join()
        with self._lock:
            self.current = self.total
            self._render_locked()

    def render(self) -> None:
        """현재 진행률을 한 줄에 출력"""
        with self._lock:
            self._render_locked()

    def _render_elapsed(self) -> None:
        """경과 시간을 매초 갱신"""
        while not self._stop_event.wait(1):
            self.render()

    def _elapsed_text(self) -> str:
        """MM:SS 형식의 경과 시간을 반환"""
        started_at = TerminalProgressBar._job_started_at or time.monotonic()
        elapsed_seconds = int(time.monotonic() - started_at)
        minutes = elapsed_seconds // 60
        seconds = elapsed_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def _render_locked(self) -> None:
        """잠금 안에서 현재 진행률을 출력"""
        percent = 100 if self.total == 0 else int(self.current / self.total * 100)
        filled = self.width if self.total == 0 else int(self.width * self.current / self.total)
        bar = "#" * filled + "-" * (self.width - filled)
        count_width = len(f"{self.total}/{self.total} (100%)")
        count_text = f"{self.current}/{self.total} ({percent}%)".ljust(count_width)
        line = (
            f"[{bar}]  {self._elapsed_text()}  |  {count_text} |  {self.label}"
        )
        padding = " " * max(0, TerminalProgressBar._last_rendered_line_length - len(line))
        print("\r" + line + padding, end="", flush=True)
        TerminalProgressBar._last_rendered_line_length = len(line)


CHEMICAL_ENTRY_PATTERN = re.compile(
    r"2\.\s*화학사고\s*현장\s*대응\s*물질\s*\(2025\)\s*-\s*물질\s*정보\s*460종\s*-[^\n]*"
)
CAS_NUMBER_RE = re.compile(r"\b\d{2,7}-\d{2}-\d\b")
# NFPA 위험등급 설명 줄 패턴 (화재N:/건강N:/반응N:/특수OX: 등)
NFPA_DESC_RE = re.compile(r"^(화재|건강|반응)\d+:|^특수[\w\-]*\s*:")
CHEMICAL_STOP_LABELS = (
    "국문유사명",
    "영문유사명",
    "ERG대응지침번호",
    "UN번호",
    "화학물질군",
    "유해화학물질관리번호",
    "구조CAS번호",
    "CAS번호",
    "유해위험문구",
    "물리화학적 특성",
    "노출정보",
    "방재정보",
    "건강영향",
)


class CorpusLoader:
    def __init__(self):
        self.project_root = VECTOR_DB_ROOT
        self.corpus_root = resolve_vector_db_path("./data/corpus")
        self.vector_db_dir = resolve_vector_db_path(CONFIG["VECTOR_DB_DIR"])
        self.accidents_dir = resolve_vector_db_path(CONFIG["ACCIDENTS_DIR"])
        self.laws_dir = resolve_vector_db_path(CONFIG["LAWS_DIR"])
        self.designs_dir = resolve_vector_db_path(CONFIG["DESIGNS_DIR"])
        self.chemicals_dir = resolve_vector_db_path(CONFIG["CHEMICALS_DIR"])
        self.basics_dir = resolve_vector_db_path(CONFIG["BASICS_DIR"])
        self.embedding_model_name = str(resolve_vector_db_path(CONFIG["EMBEDDING_MODEL"]))
        self.embedding_dim = CONFIG["EMBEDDING_DIM"]
        self.embed_batch_size = CONFIG["EMBED_BATCH_SIZE"]
        self.parse_workers = CONFIG["PARSE_WORKERS"]
        self.embedding_cache_enabled = CONFIG["EMBEDDING_CACHE_ENABLED"]
        self.chunk_max_tokens = CONFIG["CHUNK_MAX_TOKENS"]
        self.chunk_overlap_tokens = CONFIG["CHUNK_OVERLAP_TOKENS"]
        self._embedding_cache: dict[str, list[float]] = {}
        self._tokenizer_lock = Lock()
        self._model = None
        self._db = None

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            progress = TerminalProgressBar("Loading embedding model", 1)
            self._model = SentenceTransformer(self.embedding_model_name)
            progress.advance()
            progress.finish()
        return self._model

    def _connect_db(self) -> lancedb.DBConnection:
        if self._db is None:
            self.vector_db_dir.mkdir(parents=True, exist_ok=True)
            self._db = lancedb.connect(str(self.vector_db_dir))
        return self._db

    def _table_exists(self, db: lancedb.DBConnection, table_name: str) -> bool:
        if hasattr(db, "list_tables"):
            tables = db.list_tables()
            if hasattr(tables, "tables"):
                tables = tables.tables
            return table_name in tables
        return table_name in db.table_names()

    def _map_files(self, files: list[Path], worker, desc: str):
        if self.parse_workers <= 1 or len(files) <= 1:
            progress = TerminalProgressBar(desc, len(files))
            results = []
            for path in files:
                results.append(worker(path))
                progress.advance()
            progress.finish()
            return results

        worker_count = min(self.parse_workers, len(files))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            progress = TerminalProgressBar(desc, len(files))
            results = []
            for result in executor.map(worker, files):
                results.append(result)
                progress.advance()
            progress.finish()
            return results

    def _embed(self, texts: list[str], label: str) -> list[list[float]]:
        if not texts:
            return []

        if not self.embedding_cache_enabled:
            model = self._load_model()
            progress = TerminalProgressBar(label, len(texts))
            vectors: list[list[float]] = []
            for start in range(0, len(texts), self.embed_batch_size):
                batch_texts = texts[start : start + self.embed_batch_size]
                vecs = model.encode(
                    batch_texts,
                    batch_size=self.embed_batch_size,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                vectors.extend(vecs.tolist())
                progress.advance(len(batch_texts))
            progress.finish()
            return vectors

        missing: list[str] = []
        seen_missing: set[str] = set()
        for text in texts:
            if text not in self._embedding_cache and text not in seen_missing:
                missing.append(text)
                seen_missing.add(text)

        if missing:
            model = self._load_model()
            progress = TerminalProgressBar(label, len(missing))
            for start in range(0, len(missing), self.embed_batch_size):
                batch_texts = missing[start : start + self.embed_batch_size]
                vecs = model.encode(
                    batch_texts,
                    batch_size=self.embed_batch_size,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                for text, vec in zip(batch_texts, vecs.tolist()):
                    self._embedding_cache[text] = vec
                progress.advance(len(batch_texts))
            progress.finish()
        return [self._embedding_cache[text] for text in texts]

    def _chunk_by_tokens(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []
        tokenizer = self._load_model().tokenizer
        with self._tokenizer_lock:
            ids = tokenizer.encode(text, add_special_tokens=False)
        if len(ids) <= self.chunk_max_tokens:
            return [text]
        chunks = []
        start = 0
        step = self.chunk_max_tokens - self.chunk_overlap_tokens
        while start < len(ids):
            end = start + self.chunk_max_tokens
            with self._tokenizer_lock:
                chunk_text = tokenizer.decode(ids[start:end], skip_special_tokens=True)
            if chunk_text.strip():
                chunks.append(chunk_text)
            if end >= len(ids):
                break
            start += step
        return chunks

    def _source_path(self, path: Path) -> str:
        rel_path = path.resolve().relative_to(self.project_root)
        return "./" + rel_path.as_posix()

    def _parse_pdf_pages(self, path: Path) -> list[tuple[int, str]]:
        doc = fitz.open(str(path))
        try:
            return [
                (page_num, page.get_text("text"))
                for page_num, page in enumerate(doc, start=1)
            ]
        finally:
            doc.close()

    def _chunk_pdf_by_page(self, path: Path) -> list[tuple[int, str]]:
        chunks: list[tuple[int, str]] = []
        for page_num, page_text in self._parse_pdf_pages(path):
            for chunk in self._chunk_by_tokens(page_text):
                chunks.append((page_num, chunk))
        return chunks

    def _extract_law_title(self, text: str) -> str:
        """법령 전문 텍스트의 첫 부분에서 법령명을 추출합니다."""
        # 법제처 PDF 헤더/푸터 패턴: '법제처', '국가법령정보센터', 부처 연락처 줄 등
        _HEADER_SKIP = re.compile(
            r"법제처|국가법령정보센터"        # 페이지 헤더
            r"|\[시행\s"                    # '[시행 YYYY...]' 형태 (시행일 줄)
            r"|고용노동부|환경부|산업통상자원부|기후에너지환경부"  # 부처 연락처
            r"|\d{3}-\d{3,4}-\d{4}"        # 전화번호
        )
        for line in text[:2000].splitlines():
            line = line.strip()
            if not line or line.startswith("["):
                continue
            # 공백이 많은 헤더 줄 건너뜀 (법제처 .... 1 .... 국가법령정보센터)
            if line.count(" ") > len(line) * 0.3:
                continue
            if re.search(r"[가-힣]", line) and not re.match(r"^제\d+조", line):
                if _HEADER_SKIP.search(line):
                    continue
                # "( 약칭: ... )" 같은 괄호 주석 제거
                clean = re.sub(r"\s*\(.*?\)\s*$", "", line).strip()
                if clean:
                    return clean
        return ""

    def _extract_article_header(self, chunk_text: str) -> str:
        """청크 텍스트 첫 줄에서 조항 헤더를 추출합니다. 예: '제1조(목적)'"""
        match = re.match(
            r"^[ \t]*(제\d+조(?:의\d+)?(?:[ \t]*\([^)]*\))?)",
            chunk_text.strip(),
        )
        return match.group(1).strip() if match else ""

    def _extract_section_from_page(self, page_text: str) -> str:
        """페이지 텍스트에서 KOSHA Guide 스타일 섹션 번호를 추출합니다. 예: '5', '5.1', '5.1.2'"""
        match = re.search(
            r"(?m)^(\d+(?:\.\d+){0,3})(?:\s+\S)",
            page_text[:1500],
        )
        return match.group(1) if match else ""


    def _clean_design_page_text(self, text: str) -> str:
        """PDF page text에서 반복 헤더/페이지 번호만 가볍게 제거합니다."""
        cleaned_lines: list[str] = []
        for raw_line in (text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line in {"KOSHA GUIDE", "KGS Code"}:
                continue
            if re.match(r"^C\s*[–-]\s*C\s*[–-]\s*\d+\s*[–-]\s*\d{4}$", line):
                continue
            if re.match(r"^KGS\s+[A-Z]+\d+\s+\d{4}$", line):
                continue
            if re.match(r"^-\s*\d+\s*-$", line):
                continue
            if re.match(r"^\d+$", line):
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip()

    def _is_design_toc_page(self, text: str) -> bool:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if not lines:
            return True
        joined = "\n".join(lines[:12])
        if re.search(r"목\s*차", joined):
            return True
        dot_leader_count = sum(1 for line in lines if "··" in line or re.search(r"\.{4,}", line))
        return dot_leader_count >= 4

    def _is_design_front_matter_page(self, text: str) -> bool:
        if not (text or "").strip():
            return True
        if self._is_design_toc_page(text):
            return True
        front_patterns = (
            "기술지원규정의개요",
            "기술지원규정의 개요",
            "제․개정경과",
            "제ᆞ개 정  일 자",
            "KGS Code 제․개정 이력",
            "가 스 기 술 기 준 위 원 회",
            "가스기술기준위원회 심의",
            "산업통상자원부 승인",
            "한국산업안전보건공단",
        )
        return any(pattern in text for pattern in front_patterns)

    def _is_design_back_matter_start(self, text: str) -> bool:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        first = "\n".join(lines[:8])
        return bool(
            re.search(r"(?m)^<별표\s*\d*>", first)
            or re.search(r"(?m)^<별지\s*\d*>", first)
            or "기술지원규정개정이력" in first
            or "KGS Code 기호 및 일련번호 체계" in first
            or re.search(r"(?m)^부록\s+[A-Z]", first)
        )


    def _extract_design_toc_headings(self, pages: list[tuple[int, str]]) -> dict[str, str]:
        """목차 페이지에서 실제 design heading code -> heading text를 추출합니다."""
        headings: dict[str, str] = {}
        for _page_num, page_text in pages:
            if not self._is_design_toc_page(page_text):
                continue
            for raw_line in page_text.splitlines():
                line = self._clean_inline_text(raw_line)
                if not line or re.search(r"^목\s*차$", line):
                    continue
                line = re.sub(r"[·․.]{3,}.*$", "", line).strip()
                line = re.sub(r"\s+\d+\s*$", "", line).strip()
                match = re.match(r"^([A-Z]?\d+(?:\.\d+){0,5})\.?\s*(\S.{0,100})$", line)
                if not match:
                    continue
                code = match.group(1).strip()
                title = self._clean_inline_text(match.group(2))
                heading_text = f"{code} {title}".strip()
                if len(heading_text) <= 100:
                    headings.setdefault(code, heading_text)
        return headings

    def _parent_design_section(self, code: str, toc_headings: dict[str, str], fallback: str) -> str:
        if not code:
            return fallback
        if re.match(r"^[A-Z]", code):
            top_match = re.match(r"^([A-Z]\d+)", code)
            top_code = top_match.group(1) if top_match else code
        else:
            top_code = code.split(".", 1)[0]
        return toc_headings.get(top_code) or fallback



    def _is_plausible_design_subheading_title(self, title: str) -> bool:
        title = self._clean_inline_text(title)
        if not title or len(title) > 70:
            return False
        if not re.search(r"[가-힣A-Za-z]", title):
            return False
        if title.startswith((":", ",", ".", "-")):
            return False
        if re.search(r"^[\d\s,./()~%㎜℃]+$", title):
            return False
        if re.search(r"(이상|초과|미만|이하)\s*\d", title):
            return False
        return True

    def _design_top_code(self, code: str) -> str:
        if re.match(r"^[A-Z]", code):
            match = re.match(r"^([A-Z]\d+)", code)
            return match.group(1) if match else code
        return code.split(".", 1)[0]

    def _design_toc_title_matches(self, code: str, title: str, toc_headings: dict[str, str]) -> bool:
        expected = toc_headings.get(code)
        if not expected:
            return False
        expected_title = expected[len(code):].strip(" .")

        def normalize(value: str) -> str:
            value = re.sub(r"<[^>]*>", "", value)
            value = re.sub(r"[\s\-·․.,:;()\[\]{}'\"“”]+", "", value)
            return value.strip()

        current_norm = normalize(title)
        expected_norm = normalize(expected_title)
        if not current_norm or not expected_norm:
            return False
        return current_norm.startswith(expected_norm) or expected_norm.startswith(current_norm)

    def _design_heading_match(self, line: str):
        """design 본문 heading을 찾습니다. 예: 5. 일반사항, 5.1 자료, L3.3.2 검사방법"""
        stripped = line.strip()
        if not stripped:
            return None
        if stripped.startswith(("표 ", "그림 ", "[비고]", "비고")):
            return None
        if re.search(r"[·․]{3,}", stripped):
            return None
        match = re.match(
            r"^([A-Z]?\d+(?:\.\d+){0,5})\.?\s*(\S.{0,120})$",
            stripped,
        )
        if not match:
            return None
        code = match.group(1)
        code_body = re.sub(r"^[A-Z]", "", code)
        if any(part == "0" for part in code_body.split(".")):
            return None
        title = match.group(2).strip()
        if len(f"{code} {title}".strip()) > 80:
            return None
        if re.match(r"^[A-Z]\d+$", code) and title.startswith(":"):
            return None
        return match

    def _design_heading_level(self, code: str) -> int:
        code_body = re.sub(r"^[A-Z]", "", code)
        return code_body.count(".") + 1

    def _chunk_design_by_heading(self, path: Path) -> list[tuple[int, str, str, str]]:
        """design PDF를 본문 heading 단위로 분할합니다.

        반환값: (page_num, chunk_text, section, subsection)
        """
        pages = self._parse_pdf_pages(path)
        toc_headings = self._extract_design_toc_headings(pages)
        body_pages: list[tuple[int, str]] = []
        body_started = False

        for page_num, page_text in pages:
            if not body_started:
                if self._is_design_front_matter_page(page_text):
                    continue
                if not re.search(r"(?m)^[A-Z]?1(?:\.\d+)*\.?\s*\S", page_text):
                    continue
                body_started = True

            if body_started and self._is_design_back_matter_start(page_text):
                break

            cleaned = self._clean_design_page_text(page_text)
            if len(cleaned) < 80:
                continue
            body_pages.append((page_num, cleaned))

        if not body_pages:
            return []

        full_text = ""
        page_starts: list[tuple[int, int]] = []
        for page_num, page_text in body_pages:
            page_starts.append((len(full_text), page_num))
            full_text += page_text.strip() + "\n"

        def get_page(char_pos: int) -> int:
            result = page_starts[0][1]
            for start, pnum in page_starts:
                if start <= char_pos:
                    result = pnum
                else:
                    break
            return result

        headings: list[dict] = []
        current_section = ""
        last_numeric_top_level = 0
        for match in re.finditer(r"(?m)^(.+)$", full_text):
            line = match.group(1).strip()
            heading = self._design_heading_match(line)
            if not heading:
                continue
            code = heading.group(1).strip()
            title = self._clean_inline_text(heading.group(2))
            heading_text = toc_headings.get(code) or f"{code} {title}".strip()
            level = self._design_heading_level(code)

            if toc_headings:
                if code in toc_headings:
                    if not self._design_toc_title_matches(code, title, toc_headings):
                        continue
                elif (
                    len(toc_headings) < 40
                    and level > 1
                    and self._design_top_code(code) in toc_headings
                ):
                    if not self._is_plausible_design_subheading_title(title):
                        continue
                else:
                    continue

            if level == 1 and not re.match(r"^[A-Z]", code):
                top_level = int(code.split(".", 1)[0])
                if not toc_headings:
                    if (
                        len(title) > 25
                        or (" " in title and len(title) > 12)
                        or re.search(r"(등|및|또는|한다|여부)$", title)
                    ):
                        continue
                    if last_numeric_top_level and (top_level <= last_numeric_top_level or top_level > last_numeric_top_level + 2):
                        continue
                last_numeric_top_level = max(last_numeric_top_level, top_level)

            if level == 1:
                current_section = heading_text
                subsection = ""
            else:
                current_section = self._parent_design_section(code, toc_headings, current_section)
                subsection = heading_text
            headings.append({
                "start": match.start(),
                "section": current_section or heading_text,
                "subsection": subsection,
            })

        if not headings:
            return [
                (page_num, chunk, "", "")
                for page_num, page_text in body_pages
                for chunk in self._chunk_by_tokens(page_text)
            ]

        chunks: list[tuple[int, str, str, str]] = []
        for idx, heading in enumerate(headings):
            start = heading["start"]
            end = headings[idx + 1]["start"] if idx + 1 < len(headings) else len(full_text)
            block = full_text[start:end].strip()
            if len(block) < 40:
                continue
            sub_chunks = self._chunk_by_tokens(block)
            for sub_idx, sub_text in enumerate(sub_chunks):
                if sub_idx > 0:
                    label = heading["subsection"] or heading["section"]
                    sub_text = f"{label} [계속 {sub_idx + 1}/{len(sub_chunks)}]\n{sub_text}"
                chunks.append((
                    get_page(start),
                    sub_text,
                    heading["section"],
                    heading["subsection"],
                ))
        return chunks

    def _extract_chapter_from_page(self, page_text: str) -> str:
        """페이지 텍스트에서 챕터/장 헤더를 추출합니다."""
        patterns = [
            r"(?im)^(chapter\s+\d+[^\n]{0,80})",
            r"(?m)^(제\s*\d+\s*장[^\n]{0,60})",
        ]
        for pat in patterns:
            m = re.search(pat, page_text[:1000])
            if m:
                return m.group(1).strip()
        return ""

    def _extract_design_title(self, path: Path) -> str:
        """designs PDF에서 지침명을 추출합니다.
        - KOSHA Guide: 파일명 '+' 패턴 → '[P-82-2023] 제목' 형태
        - KGS Code: PDF 첫 페이지 텍스트 파싱 → '[KGS AC111 2025] 제목' 형태
        - 기타: 파일명(확장자 제외) 그대로 반환
        """
        stem = path.stem

        # KOSHA Guide: 파일명에 '+' 포함 (구형 파일명)
        if "+" in stem:
            m = re.match(r"^([A-Z](?:-[A-Z])?-\d+-\d{4})\+(.+)$", stem)
            if m:
                code = m.group(1)
                title_part = m.group(2).replace("+", " ")
                return f"[{code}] {title_part}"
            return stem.replace("+", " ")

        # KOSHA Guide: 공백 구분자 (신형 파일명, 예: "P-82-2023 연속공정의 위험과 운전분석...")
        m = re.match(r"^([A-Z](?:-[A-Z])?-\d+-\d{4})\s+(.+)$", stem)
        if m:
            return f"[{m.group(1)}] {m.group(2)}"

        # KGS Code: 파일명이 'KGS'로 시작
        if stem.upper().startswith("KGS"):
            try:
                pages = self._parse_pdf_pages(path)
                if pages:
                    first_page = pages[0][1]
                    code_m = re.search(r"KGS\s+[A-Z]+\d+\s+\d{4}", first_page)
                    if code_m:
                        code = re.sub(r"\s+", " ", code_m.group(0)).strip()
                        # 실제 제목은 KGS 코드 앞에 위치
                        before = first_page[:code_m.start()]
                        title_lines = []
                        for line in before.splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            if re.search(r"[가-힣]", line):
                                title_lines.append(line)
                        title_part = " ".join(title_lines)
                        if title_part:
                            return f"[{code}] {title_part}"
            except Exception:
                pass

        return stem

    def _chunk_law_by_article(self, path: Path) -> list[tuple[int, str, str, str]]:
        """법률 PDF를 조항(제N조) 단위로 분할.
        반환값: (page_num, chunk_text, law_title, article_header) 리스트."""
        pages = self._parse_pdf_pages(path)

        # 전체 텍스트 + 문자 위치 → 페이지 번호 매핑 구성
        full_text = ""
        page_starts: list[tuple[int, int]] = []  # (char_pos, page_num)
        for page_num, page_text in pages:
            page_starts.append((len(full_text), page_num))
            full_text += page_text

        law_title = self._extract_law_title(full_text)

        def get_page(char_pos: int) -> int:
            result = page_starts[0][1] if page_starts else 1
            for start, pnum in page_starts:
                if start <= char_pos:
                    result = pnum
                else:
                    break
            return result

        # 행 시작 기준 조항 헤더 매칭 (제1조, 제2조의3, 제4조(목적) 등)
        article_re = re.compile(
            r"(?m)^[ \t]*제\d+조(?:의\d+)?(?:[ \t]*\([^)]*\))?"
        )
        matches = list(article_re.finditer(full_text))

        if not matches:
            # 조항 구조 미발견 시 페이지 단위로 분할
            return [
                (pn, pt.strip(), law_title, "")
                for pn, pt in pages if pt.strip()
            ]

        chunks: list[tuple[int, str, str, str]] = []

        # 첫 번째 조항 이전 전문(前文)은 검색 유용성이 낮아 제거함
        # (법령명은 title 필드에 별도 저장)

        # 조항별 청크
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
            chunk_text = full_text[match.start():end].strip()
            if not chunk_text:
                continue
            article_header = self._extract_article_header(chunk_text)
            sub_chunks = self._chunk_by_tokens(chunk_text)
            if len(sub_chunks) <= 1:
                chunks.append((get_page(match.start()), chunk_text, law_title, article_header))
            else:
                # 1000토큰 초과 조항 → 헤더 반복 삽입 후 서브청킹
                total_subs = len(sub_chunks)
                for sub_idx, sub_text in enumerate(sub_chunks):
                    if sub_idx > 0:
                        sub_text = f"{article_header} [계속 {sub_idx + 1}/{total_subs}]\n{sub_text}"
                    chunks.append((get_page(match.start()), sub_text, law_title, article_header))

        return chunks

    def _clean_inline_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def _extract_labeled_value(
        self,
        text: str,
        label: str,
        stop_labels: tuple[str, ...],
    ) -> str:
        stop_pattern = "|".join(
            re.escape(item) for item in stop_labels if item != label
        )
        pattern = (
            rf"{re.escape(label)}\s*(.*?)(?={stop_pattern}|$)"
            if stop_pattern
            else rf"{re.escape(label)}\s*(.*)"
        )
        match = re.search(pattern, text, flags=re.DOTALL)
        if not match:
            return ""
        return self._clean_inline_text(match.group(1))

    def _split_korean_english_name(self, raw_name: str) -> tuple[str, str]:
        raw_name = self._clean_inline_text(raw_name)
        if not raw_name:
            return "", ""

        has_korean = bool(re.search(r"[가-힣]", raw_name))
        has_english = bool(re.search(r"[A-Za-z]", raw_name))
        if has_korean and has_english:
            boundary = re.search(r"(?<=[가-힣])\s*(?=[A-Za-z])", raw_name)
            if boundary:
                return (
                    raw_name[: boundary.start()].strip(),
                    raw_name[boundary.end() :].strip(),
                )

            mixed_match = re.match(r"^(.*?[가-힣].*?)([A-Za-z].*)$", raw_name)
            if mixed_match:
                return mixed_match.group(1).strip(), mixed_match.group(2).strip()

        if has_korean:
            return raw_name, ""
        if has_english:
            return "", raw_name
        return raw_name, ""

    def _extract_chemical_name_lines(self, entry_text: str) -> list[str]:
        """PDF entry 헤더에서 물질명 줄을 추출"""
        entry_match = CHEMICAL_ENTRY_PATTERN.search(entry_text)
        remainder = entry_text[entry_match.end() :] if entry_match else entry_text
        raw_name = re.split(
            r"(?:구조\s*)?CAS번호|국문유사명|영문유사명|ERG대응지침번호|UN번호",
            remainder,
            maxsplit=1,
        )[0]

        lines: list[str] = []
        for raw_line in raw_name.splitlines():
            line = self._clean_inline_text(raw_line)
            if line and line != "구조":
                lines.append(line)
        return lines

    def _split_chemical_name_lines(self, name_lines: list[str]) -> tuple[str, str]:
        """PDF 물질명 줄 구조를 기준으로 국문명과 영문명을 분리"""
        if not name_lines:
            return "", ""

        english_start = None
        for idx, line in enumerate(name_lines[1:], start=1):
            if re.search(r"[A-Za-z]", line) and not re.search(r"[가-힣]", line):
                english_start = idx
                break

        if english_start is not None:
            korean_name = self._clean_inline_text(" ".join(name_lines[:english_start]))
            english_name = self._clean_inline_text(" ".join(name_lines[english_start:]))
            return korean_name, english_name

        return self._split_korean_english_name(" ".join(name_lines))

    def _extract_cas_number(self, entry_text: str) -> str:
        """PDF entry에서 CAS 번호만 추출"""
        value = self._extract_labeled_value(entry_text, "CAS번호", CHEMICAL_STOP_LABELS)
        return CAS_NUMBER_RE.search(value).group(0)

    def _normalize_chemical_field_value(self, value: str) -> str:
        """PDF 화학물질 header의 결측 표기를 없음으로 통일"""
        value = self._clean_inline_text(value)
        if not value or re.fullmatch(r"[-–—]+", value):
            return "없음"
        return value

    def _chemical_line_value(self, lines: list[str], label: str) -> str:
        """PDF entry 라인에서 단일 label 값을 추출"""
        for raw_line in lines:
            line = raw_line.strip()
            if line.startswith(label):
                value = line.split(":", 1)[1] if ":" in line else ""
                return self._normalize_chemical_field_value(value)
        return "없음"

    def _chemical_state_value(self, lines: list[str]) -> str:
        """PDF 상태 값을 검색용 대표 상태로 축약"""
        value = self._chemical_line_value(lines, "상태:")
        if value == "없음":
            return value
        return re.split(r"[\s(/,]", value, maxsplit=1)[0]

    def _is_chemical_continuation_stop(self, line: str) -> bool:
        """PDF chemical 라인 연속 수집의 종료 지점 여부를 반환"""
        if not line:
            return False
        stop_prefixes = (
            "상태:",
            "인화점:",
            "폭발한계",
            "발화점:",
            "색상:",
            "용해도",
            "옥탄올/물",
            "냄새:",
            "밀도/비중:",
            "용도",
            "증기밀도:",
            "작업장",
            "일반 인구",
            "분자식",
            "pH:",
            "끓는점:",
            "탐지",
            "개인보호구",
            "NFPA 코드",
            "국내규제",
            "위험",
            "그림문자",
            "화재",
            "누출",
            "인체노출",
            "응급조치",
        )
        return (
            line.startswith("•")
            or line.startswith(stop_prefixes)
            or bool(re.match(r"^(화재|건강|반응)\d+\s*:", line))
            or bool(re.match(r"^특수[\w\\\-]*\s*:", line))
            or line in {"취", "급", "시", "진압", "요령"}
        )

    def _clean_chemical_sentence(self, value: str) -> str:
        """PDF에서 이어 붙인 화학물질 설명 문장을 정리"""
        value = self._clean_inline_text(value)
        value = re.sub(r"(?<!\s)\((※|인화점)", r" (\1", value)
        return value

    def _collect_chemical_continuation(
        self,
        lines: list[str],
        start_idx: int,
        first_value: str,
    ) -> tuple[str, int]:
        """PDF 라인의 다음 label 전까지 이어지는 설명을 수집"""
        parts = [first_value.strip()]
        idx = start_idx + 1
        while idx < len(lines):
            line = lines[idx].strip()
            if not line:
                idx += 1
                continue
            if self._is_chemical_continuation_stop(line):
                break
            parts.append(line)
            idx += 1
        return self._clean_chemical_sentence(" ".join(parts)), idx

    def _extract_chemical_fire_text(self, lines: list[str]) -> str:
        """PDF 화재 및 폭발 가능성 bullet을 추출"""
        for idx, raw_line in enumerate(lines):
            line = raw_line.strip()
            if line.startswith("• 화재 및 폭발 가능성"):
                value = line.split(":", 1)[1] if ":" in line else line.replace("• 화재 및 폭발 가능성", "")
                value, _ = self._collect_chemical_continuation(lines, idx, value)
                return "없음" if value == "-" else value
        return "없음"

    def _extract_chemical_nfpa_bullets(self, lines: list[str]) -> list[str]:
        """PDF NFPA 코드 설명을 markdown bullet로 추출"""
        bullets: list[str] = []
        idx = 0
        while idx < len(lines):
            line = lines[idx].strip()
            match = re.match(r"^(화재|건강|반응)\d+\s*:\s*(.*)$", line)
            if match:
                value, next_idx = self._collect_chemical_continuation(lines, idx, match.group(2))
                bullets.append(f"- {value}")
                idx = next_idx
                continue

            special_match = re.match(r"^특수[\w\\\-]*\s*:\s*(.*)$", line)
            if special_match and special_match.group(1).strip() not in {"", "-"}:
                value, next_idx = self._collect_chemical_continuation(lines, idx, special_match.group(1))
                if bullets:
                    bullets[-1] += value
                idx = next_idx
                continue

            idx += 1
        return bullets

    def _extract_chemical_regulation_class(self, lines: list[str]) -> str:
        """PDF 국내규제 영역에서 위험요소 분류만 추출"""
        start_idx = None
        end_idx = None
        for idx, line in enumerate(lines):
            if line.strip() == "국내규제":
                start_idx = idx + 1
            elif start_idx is not None and line.strip() == "위험":
                end_idx = idx
                break
        if start_idx is None or end_idx is None:
            return "없음"

        classes: list[str] = []
        for raw_line in lines[start_idx:end_idx]:
            line = self._clean_inline_text(raw_line)
            if not line or line == "-" or re.match(r"^제\d+류", line):
                continue
            if line in {"노출", "노출, 작업, 관리", "가연성", "(비수용성)", "(수용성)"}:
                continue
            if any(item in line for item in ("사고대비물질", "유독물질", "제한물질", "금지물질", "허가물질")):
                classes.append(line)
        return ", ".join(classes) if classes else "없음"

    def _normalize_chemical_hazard_bullet(self, value: str) -> str:
        """PDF 그림문자/위험 bullet의 줄 결합 노이즈를 정리"""
        value = self._clean_chemical_sentence(value)
        value = value.replace("-1회노출", "-1회 노출")
        value = value.replace("-1회 노 출", "-1회 노출")
        return value

    def _collect_chemical_bullet(self, lines: list[str], start_idx: int) -> tuple[str, int]:
        """PDF bullet과 이어진 줄을 하나의 markdown bullet 값으로 결합"""
        line = lines[start_idx].strip()
        parts = [re.sub(r"^[•*]\s*", "", line)]
        idx = start_idx + 1
        section_stops = {
            "그림문자",
            "화재",
            "누출",
            "인체노출 유해성 / 증상",
            "응급조치",
            "진압",
            "요령",
        }
        while idx < len(lines):
            next_line = lines[idx].strip()
            if not next_line:
                idx += 1
                continue
            if next_line.startswith("•") or next_line in section_stops:
                break
            parts.append(next_line)
            idx += 1
        return self._normalize_chemical_hazard_bullet(" ".join(parts)), idx

    def _extract_chemical_section_bullets(
        self,
        lines: list[str],
        section_label: str,
        stop_labels: set[str],
    ) -> list[str]:
        """PDF section의 bullet 목록을 markdown bullet로 추출"""
        start_idx = None
        for idx, line in enumerate(lines):
            if line.strip() == section_label:
                start_idx = idx + 1
                break
        if start_idx is None:
            return []

        bullets: list[str] = []
        idx = start_idx
        while idx < len(lines):
            line = lines[idx].strip()
            if line in stop_labels:
                break
            if line.startswith("•"):
                value, next_idx = self._collect_chemical_bullet(lines, idx)
                bullets.append(f"- {value}")
                idx = next_idx
                continue
            idx += 1
        return bullets

    def _build_chemical_curated_body(self, entry_text: str) -> str:
        """PDF entry에서 검색용 화학물질 정제 본문을 구성"""
        lines = entry_text.splitlines()
        body_lines = [
            "[물리화학적 특성]",
            f"- 상태: {self._chemical_state_value(lines)}",
            f"- 색상: {self._chemical_line_value(lines, '색상:')}",
            f"- 화재 및 폭발 가능성: {self._extract_chemical_fire_text(lines)}",
            *self._extract_chemical_nfpa_bullets(lines),
            "",
            "[위험요소]",
            f"- 분류: {self._extract_chemical_regulation_class(lines)}",
            *self._extract_chemical_section_bullets(
                lines,
                "위험",
                {"그림문자", "화재", "누출", "인체노출 유해성 / 증상", "응급조치"},
            ),
            *self._extract_chemical_section_bullets(
                lines,
                "그림문자",
                {"화재", "누출", "인체노출 유해성 / 증상", "응급조치"},
            ),
        ]
        return "\n".join(body_lines).strip()

    def _build_chemical_name(self, entry_text: str) -> str:
        name_lines = self._extract_chemical_name_lines(entry_text)
        raw_name = self._clean_inline_text(" ".join(name_lines))
        korean_name, english_name = self._split_chemical_name_lines(name_lines)

        if korean_name and english_name:
            base_name = f"{korean_name} | {english_name}"
        else:
            base_name = korean_name or english_name or raw_name or "이름 미상"

        korean_alias = self._extract_labeled_value(
            entry_text,
            "국문유사명",
            CHEMICAL_STOP_LABELS,
        )
        english_alias = self._extract_labeled_value(
            entry_text,
            "영문유사명",
            CHEMICAL_STOP_LABELS,
        )
        alias_text = ", ".join(
            part for part in [korean_alias, english_alias] if part and part not in {"-", "없음"}
        )
        return f"{base_name} | {alias_text}" if alias_text else base_name

    def _build_chemical_markdown_text(self, entry_text: str) -> str:
        """PDF 화학물질 entry를 검색용 markdown 텍스트로 변환"""
        name_lines = self._extract_chemical_name_lines(entry_text)
        korean_name, english_name = self._split_chemical_name_lines(name_lines)
        display_name = (
            f"{korean_name} | {english_name}"
            if korean_name and english_name
            else korean_name or english_name or self._clean_inline_text(" ".join(name_lines))
        )
        labels = (
            ("CAS번호", "CAS번호"),
            ("국문 유사명", "국문유사명"),
            ("영문 유사명", "영문유사명"),
            ("ERG대응지침번호", "ERG대응지침번호"),
            ("UN번호", "UN번호"),
            ("화학물질군", "화학물질군"),
            ("유해화학물질관리번호", "유해화학물질관리번호"),
        )
        lines = [
            "[물질 정보]",
            f"- 물질명: {display_name}",
        ]
        for display_label, source_label in labels:
            if source_label == "CAS번호":
                value = self._extract_cas_number(entry_text)
            else:
                value = self._normalize_chemical_field_value(
                    self._extract_labeled_value(entry_text, source_label, CHEMICAL_STOP_LABELS)
                )
            lines.append(f"- {display_label}: {value}")

        lines.extend(["", self._build_chemical_curated_body(entry_text)])
        return "\n".join(lines).strip()

    def _load_chemical_list(self, xlsx_path: Path) -> list[tuple[str, str]]:
        """화학물질 목록_재정렬.xlsx를 읽어 (ko_name, en_name) 리스트 반환 (460종, 순서대로)."""
        if not xlsx_path.exists():
            return []

        df = pd.read_excel(xlsx_path)
        chemicals: list[tuple[str, str]] = []
        for _, row in df.iterrows():
            ko = str(row.get("국문명", "") or "").strip()
            en = str(row.get("영문명", "") or "").strip()
            chemicals.append((ko, en))

        return chemicals

    def _clean_chemical_text(self, text: str) -> str:
        """화학물질 페이지 텍스트에서 공정위험성 관련 정보만 추출.

        유지: 물질명/CAS/유사명/화학물질군, 물리화학적특성, NFPA등급설명,
              국내규제분류, 위험섹션(혼합금지/연소생성물/그림문자 포함)
        제거: 탐지장비, PPE세부(사고대응/취급시), 화재진압요령,
              누출방재요령, 인체노출/증상, 응급조치, 책 페이지헤더
        """
        # 독립 줄로 나타나는 "물리화학적 특성"이 없으면 목차/색인 페이지 → 그대로 반환
        if not re.search(r"(?m)^물리화학적 특성\s*$", text):
            return text

        lines = text.splitlines()
        result: list[str] = []

        # states:
        # 'name_block'  : 물리화학적 특성 이전 (물질명/CAS/유사명 블록)
        # 'phys_chem'   : 물리화학적 특성 섹션
        # 'skip'        : 탐지장비·개인보호구 헤더·사고대응 PPE 제거 구간
        # 'nfpa_desc'   : NFPA 등급 설명 줄 (화재N:/건강N:/ 등) — 유지
        # 'regulation'  : 국내규제 + 위험 섹션 — 유지
        # 'done'        : 화재진압요령 이후 — 모두 제거
        state = "name_block"
        nfpa_header_added = False

        for i, line in enumerate(lines):
            s = line.strip()

            # ── 항상 제거: 책 페이지 헤더 / 엔트리 헤더 줄 ────────────
            if CHEMICAL_ENTRY_PATTERN.match(s):
                continue
            # PDF 폰트 특수 공백 포함 대응: \s+ 대신 숫자+임의문자+키워드 패턴 사용
            if re.match(r"^\d+", s) and "화학사고 현장 대응 물질 정보집" in s:
                continue
            if s == "구조":  # 구조식 레이블 — 정보 없음
                continue

            # ── state 전환 및 출력 ──────────────────────────────────────
            if state == "name_block":
                if s == "물리화학적 특성":
                    state = "phys_chem"
                result.append(line)

            elif state == "phys_chem":
                if re.match(r"^탐지[,•·\s]", s) or s == "탐지":
                    state = "skip"
                elif s == "개인보호구":
                    state = "skip"
                else:
                    result.append(line)

            elif state == "skip":
                if NFPA_DESC_RE.match(s):
                    state = "nfpa_desc"
                    if not nfpa_header_added:
                        result.append("")
                        result.append("[NFPA 위험등급]")
                        nfpa_header_added = True
                    result.append(line)
                elif s in ("국내규제", "위험"):
                    state = "regulation"
                    result.append("")
                    result.append(line)
                # 그 외는 skip (사고대응 PPE 지시, 취급시 PPE 등)

            elif state == "nfpa_desc":
                if NFPA_DESC_RE.match(s):
                    result.append(line)
                elif s in ("국내규제", "위험"):
                    state = "regulation"
                    result.append("")
                    result.append(line)
                elif (not s                                      # 빈 줄
                      or len(s) == 1                             # 단글자 (취/급/시 세로글씨)
                      or s.startswith("•")                       # PPE 불릿
                      or s.startswith("*")                       # 각주
                      or re.match(r"^\s+[•*]", line)             # 들여쓰기 불릿
                      or re.match(r"^\d+", s)                    # 페이지 번호 / PPE 규격 번호
                      or any(w in s for w in ("마스크", "장갑", "보호복", "호흡기", "SCBA", "EN "))
                      ):
                    pass  # skip (취급시 PPE 영역 및 잔여 노이즈)
                else:
                    result.append(line)  # NFPA 설명 연속 줄

            elif state == "regulation":
                # 화재진압요령 시작: '화재' 단독 줄 + 다음 줄 '진압'
                if s == "화재":
                    peek = lines[i + 1].strip() if i + 1 < len(lines) else ""
                    if peek == "진압":
                        state = "done"
                        continue
                if s == "누출":
                    peek = lines[i + 1].strip() if i + 1 < len(lines) else ""
                    if peek == "방재":
                        state = "done"
                        continue
                if s.startswith("인체노출 유해성") or s == "응급조치":
                    state = "done"
                    continue
                result.append(line)

            # state == 'done': 이후 모두 제거

        cleaned = "\n".join(result)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _extract_chemical_entries(self, path: Path) -> list[dict]:
        entries: list[dict] = []

        for page_num, page_text in self._parse_pdf_pages(path):
            if not page_text.strip():
                continue

            matches = list(CHEMICAL_ENTRY_PATTERN.finditer(page_text))
            for idx, match in enumerate(matches):
                start = match.start()
                end = matches[idx + 1].start() if idx + 1 < len(matches) else len(page_text)
                entry_text = page_text[start:end].strip()
                if entry_text:
                    entries.append({
                        "page": page_num,
                        "text": entry_text,
                    })

        return entries

    def _normalize_foreign_row(self, row: pd.Series) -> dict:
        cols = set(row.index)

        def _s(key: str) -> str:
            val = row.get(key, "")
            return "" if pd.isna(val) else str(val).strip()

        if "Accident" in cols:
            return {
                "accident": _s("Accident"),
                "equipment": _s("Equipment"),
                "material": _s("Material"),
                "accident_type": _s("Type"),
                "cause": _s("Cause"),
            }

        if "사용설비(반응기 유형)" in cols:
            return {
                "accident": f"{_s('사고명')} {_s('사고개요')}".strip(),
                "equipment": _s("사용설비(반응기 유형)"),
                "material": _s("반응물 또는 생성물의 주요 화학물질 이름"),
                "accident_type": _s("사고유형"),
                "cause": _s("사고 원인"),
            }

        if "반응기 유형" in cols and "주요 화학물질" in cols:
            return {
                "accident": f"{_s('사고명')} {_s('사고개요')}".strip(),
                "equipment": _s("반응기 유형"),
                "material": _s("주요 화학물질"),
                "accident_type": _s("사고유형"),
                "cause": _s("사고원인"),
            }

        if "반응기 유형" in cols:
            return {
                "accident": f"{_s('사고명')} {_s('사고개요')}".strip(),
                "equipment": _s("반응기 유형"),
                "material": _s("반응물 또는 생성물의 주요 화학물질 이름"),
                "accident_type": _s("사고유형"),
                "cause": _s("사고 원인"),
            }

        def _find(*candidates: str) -> str:
            for c in candidates:
                if c in cols:
                    return _s(c)
            return ""

        return {
            "accident": _find("사고개요", "사고명", "내용"),
            "equipment": _find("설비", "반응기"),
            "material": _find("화학물질", "물질", "반응물"),
            "accident_type": _find("사고유형", "사고 유형", "유형"),
            "cause": _find("사고 원인", "원인", "사고원인"),
        }


    def _load_safety_center_file(self, path: Path) -> list[dict]:
        """안전원_P&ID 국내 화학사고 모음 파일을 읽어 표준 사고 레코드 리스트를 반환합니다."""
        records: list[dict] = []
        progress = TerminalProgressBar(f"Reading {path.stem}", 1)
        xl = pd.ExcelFile(path)
        progress.advance()
        progress.finish()

        def _s(row: pd.Series, key: str) -> str:
            val = row.get(key, "")
            return "" if pd.isna(val) else str(val).strip()

        # 시트1: 분석자료(최종) — PSM 중대산업사고
        if "분석자료(최종)" in xl.sheet_names:
            progress = TerminalProgressBar("Reading 분석자료(최종)", 1)
            df = xl.parse("분석자료(최종)")
            progress.advance()
            progress.finish()
            # 실제 데이터 컬럼 확인 (개  요 컬럼명에 공백 포함)
            overview_col = next((c for c in df.columns if "개" in str(c) and "요" in str(c)), None)
            progress = TerminalProgressBar("분석자료(최종)", len(df))
            for i, row in df.iterrows():
                accident  = _s(row, overview_col) if overview_col else ""
                equipment = _s(row, "사고설비")
                material  = _s(row, "사고물질")
                acc_type  = _s(row, "발생형태")
                cause     = _s(row, "사고원인")
                if not accident and not material and not equipment:
                    progress.advance()
                    continue
                records.append({
                    "accident": accident,
                    "equipment": equipment,
                    "material": material,
                    "accident_type": acc_type,
                    "cause": cause,
                    "origin": "안전원_PSM",
                    "id_prefix": f"safety_psm_{i+1:04d}",
                })
                progress.advance()
            progress.finish()

        # 시트2: 환경부(사고데이터) — 환경부 사고 데이터
        if "환경부(사고데이터)" in xl.sheet_names:
            progress = TerminalProgressBar("Reading 환경부(사고데이터)", 1)
            df = xl.parse("환경부(사고데이터)")
            progress.advance()
            progress.finish()
            progress = TerminalProgressBar("환경부(사고데이터)", len(df))
            for i, row in df.iterrows():
                accident  = _s(row, "사고내용")
                equipment = _s(row, "사고 설비")
                material  = _s(row, "제1사고물질")
                acc_type  = _s(row, "사고유형")
                cause     = _s(row, "사고원인")
                if not accident and not material and not equipment:
                    progress.advance()
                    continue
                records.append({
                    "accident": accident,
                    "equipment": equipment,
                    "material": material,
                    "accident_type": acc_type,
                    "cause": cause,
                    "origin": "안전원_환경부",
                    "id_prefix": f"safety_env_{i+1:04d}",
                })
                progress.advance()
            progress.finish()

        return records

    def _collect_accidents_records(self) -> list[dict]:
        records: list[dict] = []

        xlsx_files = sorted(self.accidents_dir.glob("*.xlsx"))

        for xlsx_path in xlsx_files:
            progress = TerminalProgressBar(f"Reading {xlsx_path.stem}", 1)
            df = pd.read_excel(xlsx_path)
            progress.advance()
            progress.finish()
            file_tag = xlsx_path.stem.replace(" ", "_")
            progress = TerminalProgressBar(xlsx_path.stem, len(df))
            for i, row in df.iterrows():
                accident  = str(row.get("Accident", "") or "").strip()
                equipment = str(row.get("Equipment", "") or "").strip()
                material  = str(row.get("Material", "") or "").strip()
                acc_type  = str(row.get("Type", "") or "").strip()
                cause     = str(row.get("Cause", "") or "").strip()
                if not accident and not material and not equipment:
                    progress.advance()
                    continue
                text = (
                    f"[사고내용] {accident}\n"
                    f"[관련설비] {equipment}\n"
                    f"[관련물질] {material}\n"
                    f"[사고유형] {acc_type}\n"
                    f"[사고원인] {cause}"
                )
                records.append({
                    "id":            f"{file_tag}_{i + 1:04d}",
                    "text":          text,
                    "source":        xlsx_path.name,
                    "source_path":   self._source_path(xlsx_path),
                    "material":      material,
                    "equipment":     equipment,
                    "accident_type": acc_type,
                    "cause":         cause,
                    "origin":        file_tag,
                })
                progress.advance()
            progress.finish()

        return records

    def _embed_accidents_records(self, records: list[dict]) -> None:
        text_vectors = self._embed([r["text"] for r in records], "Embedding accidents text")
        material_vectors = self._embed([r["material"] for r in records], "Embedding accidents material")
        equipment_vectors = self._embed([r["equipment"] for r in records], "Embedding accidents equipment")
        for r, text_v, material_v, equipment_v in zip(
            records,
            text_vectors,
            material_vectors,
            equipment_vectors,
        ):
            r["text_vector"] = text_v
            r["material_vector"] = material_v
            r["equipment_vector"] = equipment_v

    def _write_accidents_records(self, records: list[dict]) -> None:
        db = self._connect_db()
        schema = pa.schema([
            pa.field("id",            pa.string()),
            pa.field("text",          pa.string()),
            pa.field("text_vector",   pa.list_(pa.float32(), self.embedding_dim)),
            pa.field("source",        pa.string()),
            pa.field("source_path",   pa.string()),
            pa.field("material",      pa.string()),
            pa.field("material_vector", pa.list_(pa.float32(), self.embedding_dim)),
            pa.field("equipment",     pa.string()),
            pa.field("equipment_vector", pa.list_(pa.float32(), self.embedding_dim)),
            pa.field("accident_type", pa.string()),
            pa.field("cause",         pa.string()),
            pa.field("origin",        pa.string()),
        ])
        progress = TerminalProgressBar("Writing accidents", 1)
        if self._table_exists(db, "accidents"):
            db.drop_table("accidents")
        db.create_table("accidents", data=records, schema=schema)
        progress.advance()
        progress.finish()

    def load_accidents(self):
        records = self._collect_accidents_records()
        if not records:
            return
        self._embed_accidents_records(records)
        self._write_accidents_records(records)

    def _law_records_for_pdf(self, pdf_path: Path) -> list[dict]:
        source_path = self._source_path(pdf_path)
        return [
            {
                "id":          f"{pdf_path.stem}_{chunk_id:04d}",
                "text":        chunk,
                "source":      pdf_path.name,
                "chunk_id":    chunk_id,
                "page":        page_num,
                "source_path": source_path,
                "title":       law_title,
                "article":     article,
            }
            for chunk_id, (page_num, chunk, law_title, article) in enumerate(
                self._chunk_law_by_article(pdf_path)
            )
        ]

    def _collect_laws_records(self) -> list[dict]:
        pdf_files = sorted(self.laws_dir.rglob("*.pdf"))

        records: list[dict] = []
        self._load_model()
        for pdf_records in self._map_files(pdf_files, self._law_records_for_pdf, "  Laws PDFs"):
            records.extend(pdf_records)

        return records

    def _embed_laws_records(self, records: list[dict]) -> None:
        text_vectors    = self._embed([r["text"]    for r in records], "Embedding laws text")
        title_vectors   = self._embed([r["title"]   for r in records], "Embedding laws title")
        article_vectors = self._embed([r["article"] for r in records], "Embedding laws article")
        for r, tv, lv, av in zip(records, text_vectors, title_vectors, article_vectors):
            r["text_vector"]    = tv
            r["title_vector"]   = lv
            r["article_vector"] = av if r["article"] else tv  # 빈 article이면 text_vector 복사

    def _write_laws_records(self, records: list[dict]) -> None:
        db = self._connect_db()
        schema = pa.schema([
            pa.field("id",               pa.string()),
            pa.field("text",             pa.string()),
            pa.field("text_vector",      pa.list_(pa.float32(), self.embedding_dim)),
            pa.field("source",           pa.string()),
            pa.field("chunk_id",         pa.int32()),
            pa.field("page",             pa.int32()),
            pa.field("source_path",      pa.string()),
            pa.field("title",            pa.string()),
            pa.field("title_vector",     pa.list_(pa.float32(), self.embedding_dim)),
            pa.field("article",          pa.string()),
            pa.field("article_vector",   pa.list_(pa.float32(), self.embedding_dim)),
        ])
        progress = TerminalProgressBar("Writing laws", 1)
        if self._table_exists(db, "laws"):
            db.drop_table("laws")
        table = db.create_table("laws", data=records, schema=schema)
        table.create_fts_index("text", replace=True)
        progress.advance()
        progress.finish()

    def load_laws(self):
        records = self._collect_laws_records()
        if not records:
            return
        self._embed_laws_records(records)
        self._write_laws_records(records)

    def _design_records_for_pdf(self, pdf_path: Path) -> list[dict]:
        source_path = self._source_path(pdf_path)
        parts = pdf_path.parent.relative_to(self.designs_dir).parts
        category = f"{parts[0]}: {parts[1]}" if len(parts) >= 2 else parts[0]
        title = self._extract_design_title(pdf_path)
        return [
            {
                "id":          f"{pdf_path.stem}_{chunk_id:04d}",
                "text":        chunk,
                "source":      pdf_path.name,
                "chunk_id":    chunk_id,
                "page":        page_num,
                "source_path": source_path,
                "category":    category,
                "title":       title,
                "section":     section,
                "subsection":  subsection,
            }
            for chunk_id, (page_num, chunk, section, subsection) in enumerate(
                self._chunk_design_by_heading(pdf_path)
            )
        ]

    def _collect_designs_records(self) -> list[dict]:
        records: list[dict] = []
        if not self.designs_dir.exists():
            return records

        pdf_files = sorted(self.designs_dir.rglob("*.pdf"))
        self._load_model()
        for pdf_records in self._map_files(pdf_files, self._design_records_for_pdf, "  Designs PDFs"):
            records.extend(pdf_records)

        return records

    def _embed_designs_records(self, records: list[dict]) -> None:
        text_vectors       = self._embed([r["text"]       for r in records], "Embedding designs text")
        title_vectors      = self._embed([r["title"]      for r in records], "Embedding designs title")
        section_vectors    = self._embed([r["section"]    for r in records], "Embedding designs section")
        subsection_vectors = self._embed([r["subsection"] for r in records], "Embedding designs subsection")
        for r, tv, gv, sv, ssv in zip(
            records,
            text_vectors,
            title_vectors,
            section_vectors,
            subsection_vectors,
        ):
            r["text_vector"]       = tv
            r["title_vector"]      = gv
            r["section_vector"]    = sv if r["section"] else tv
            r["subsection_vector"] = ssv if r["subsection"] else r["section_vector"]

    def _write_designs_records(self, records: list[dict]) -> None:
        db = self._connect_db()
        schema = pa.schema([
            pa.field("id",                pa.string()),
            pa.field("text",              pa.string()),
            pa.field("text_vector",       pa.list_(pa.float32(), self.embedding_dim)),
            pa.field("source",            pa.string()),
            pa.field("chunk_id",          pa.int32()),
            pa.field("page",              pa.int32()),
            pa.field("source_path",       pa.string()),
            pa.field("category",          pa.string()),
            pa.field("title",             pa.string()),
            pa.field("title_vector",      pa.list_(pa.float32(), self.embedding_dim)),
            pa.field("section",           pa.string()),
            pa.field("section_vector",    pa.list_(pa.float32(), self.embedding_dim)),
            pa.field("subsection",        pa.string()),
            pa.field("subsection_vector", pa.list_(pa.float32(), self.embedding_dim)),
        ])
        progress = TerminalProgressBar("Writing designs", 1)
        if self._table_exists(db, "designs"):
            db.drop_table("designs")
        table = db.create_table("designs", data=records, schema=schema)
        table.create_fts_index("text", replace=True)
        progress.advance()
        progress.finish()

    def load_designs(self):
        records = self._collect_designs_records()
        if not records:
            return
        self._embed_designs_records(records)
        self._write_designs_records(records)

    def _basic_records_for_pdf(self, pdf_path: Path, category: str) -> list[dict]:
        source_path = self._source_path(pdf_path)
        title = pdf_path.stem
        records: list[dict] = []
        for chunk_id, (page_num, chunk) in enumerate(self._chunk_pdf_by_page(pdf_path)):
            chapter = self._extract_chapter_from_page(chunk)
            records.append({
                "id":          f"{pdf_path.stem}_{chunk_id:04d}",
                "text":        chunk,
                "source":      pdf_path.name,
                "chunk_id":    chunk_id,
                "page":        page_num,
                "source_path": source_path,
                "category":    category,
                "title":       title,
                "chapter":     chapter,
            })
        return records

    def _collect_basics_records(self) -> list[dict]:
        if not self.basics_dir.exists():
            return []

        records: list[dict] = []
        for subdir in sorted(self.basics_dir.iterdir()):
            if not subdir.is_dir():
                continue
            category = subdir.name
            pdf_files = sorted(subdir.glob("*.pdf"))
            self._load_model()
            worker = lambda path, category=category: self._basic_records_for_pdf(path, category)
            for pdf_records in self._map_files(pdf_files, worker, f"  {category}"):
                records.extend(pdf_records)

        return records

    def _embed_basics_records(self, records: list[dict]) -> None:
        text_vectors    = self._embed([r["text"]    for r in records], "Embedding basics text")
        title_vectors   = self._embed([r["title"]   for r in records], "Embedding basics title")
        chapter_vectors = self._embed([r["chapter"] for r in records], "Embedding basics chapter")
        for r, tv, bv, cv in zip(records, text_vectors, title_vectors, chapter_vectors):
            r["text_vector"]    = tv
            r["title_vector"]   = bv
            r["chapter_vector"] = cv if r["chapter"] else tv  # 빈 chapter이면 text_vector 복사

    def _write_basics_records(self, records: list[dict]) -> None:
        db = self._connect_db()
        schema = pa.schema([
            pa.field("id",             pa.string()),
            pa.field("text",           pa.string()),
            pa.field("text_vector",    pa.list_(pa.float32(), self.embedding_dim)),
            pa.field("source",         pa.string()),
            pa.field("chunk_id",       pa.int32()),
            pa.field("page",           pa.int32()),
            pa.field("source_path",    pa.string()),
            pa.field("category",       pa.string()),
            pa.field("title",          pa.string()),
            pa.field("title_vector",   pa.list_(pa.float32(), self.embedding_dim)),
            pa.field("chapter",        pa.string()),
            pa.field("chapter_vector", pa.list_(pa.float32(), self.embedding_dim)),
        ])
        progress = TerminalProgressBar("Writing basics", 1)
        if self._table_exists(db, "basics"):
            db.drop_table("basics")
        table = db.create_table("basics", data=records, schema=schema)
        table.create_fts_index("text", replace=True)
        progress.advance()
        progress.finish()

    def load_basics(self):
        records = self._collect_basics_records()
        if not records:
            return
        self._embed_basics_records(records)
        self._write_basics_records(records)

    def _collect_chemicals_records(self) -> list[dict]:
        pdf_files = sorted(self.chemicals_dir.glob("*.pdf"))
        if len(pdf_files) != 1:
            raise ValueError("chemicals corpus must contain exactly one PDF.")

        records: list[dict] = []
        progress = TerminalProgressBar("Chemicals PDFs", len(pdf_files))
        for pdf_path in pdf_files:
            source_path = self._source_path(pdf_path)
            for chunk_id, entry in enumerate(self._extract_chemical_entries(pdf_path)):
                records.append({
                    "id":            f"{pdf_path.stem}_{chunk_id:04d}",
                    "text":          self._build_chemical_markdown_text(entry["text"]),
                    "source":        pdf_path.name,
                    "chunk_id":      chunk_id,
                    "page":          entry["page"],
                    "source_path":   source_path,
                    "chemical_name": self._build_chemical_name(entry["text"]),
                })
            progress.advance()
        progress.finish()

        return records

    def _embed_chemicals_records(self, records: list[dict]) -> None:
        text_vectors = self._embed([r["text"] for r in records], "Embedding chemicals text")
        chemical_name_vectors = self._embed([r["chemical_name"] for r in records], "Embedding chemicals name")
        for r, text_v, chemical_name_v in zip(
            records,
            text_vectors,
            chemical_name_vectors,
        ):
            r["text_vector"] = text_v
            r["chemical_name_vector"] = chemical_name_v

    def _write_chemicals_records(self, records: list[dict]) -> None:
        db = self._connect_db()
        schema = pa.schema([
            pa.field("id",       pa.string()),
            pa.field("text",     pa.string()),
            pa.field("text_vector", pa.list_(pa.float32(), self.embedding_dim)),
            pa.field("source",   pa.string()),
            pa.field("chunk_id", pa.int32()),
            pa.field("page",     pa.int32()),
            pa.field("source_path", pa.string()),
            pa.field("chemical_name", pa.string()),
            pa.field("chemical_name_vector", pa.list_(pa.float32(), self.embedding_dim)),
        ])
        progress = TerminalProgressBar("Writing chemicals", 1)
        if self._table_exists(db, "chemicals"):
            db.drop_table("chemicals")
        db.create_table("chemicals", data=records, schema=schema)
        progress.advance()
        progress.finish()

    def load_chemicals(self):
        records = self._collect_chemicals_records()
        if not records:
            return
        self._embed_chemicals_records(records)
        self._write_chemicals_records(records)

    def _run_load_step(self, name: str, loader) -> None:
        loader()

    def load_tables(self, table_names: list[str] | tuple[str, ...]):
        for table_name in table_names:
            self._run_load_step(table_name, getattr(self, f"load_{table_name}"))

    def load_all(self):
        self.load_tables(TABLE_NAMES)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load corpus documents into LanceDB.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--table",
        choices=TABLE_NAMES + ("all",),
        help="빌드할 단일 카테고리입니다. all을 지정하면 전체 카테고리를 빌드합니다.",
    )
    parser.add_argument(
        "--tables",
        nargs="+",
        choices=TABLE_NAMES,
        help="빌드할 카테고리 목록입니다. 생략하면 전체 카테고리를 직렬 빌드합니다.",
    )
    args = parser.parse_args()

    if args.table and args.tables:
        parser.error("--table and --tables cannot be used together")

    if args.table == "all":
        target_tables = list(TABLE_NAMES)
    elif args.table:
        target_tables = [args.table]
    elif args.tables:
        target_tables = args.tables
    else:
        target_tables = list(TABLE_NAMES)

    loader = CorpusLoader()
    dispatch = {
        "accidents": loader.load_accidents,
        "laws":      loader.load_laws,
        "designs":   loader.load_designs,
        "chemicals": loader.load_chemicals,
        "basics":    loader.load_basics,
    }
    try:
        if len(target_tables) == 1:
            dispatch[target_tables[0]]()
        else:
            loader.load_tables(target_tables)
    finally:
        print()
