import argparse
import re
from pathlib import Path
import pandas as pd
import fitz
import lancedb
import pyarrow as pa
from sentence_transformers import SentenceTransformer
from tqdm import tqdm


EMBED_MODEL_VARIANTS = {
    "baai":      "./models/embedding/models--BAAI--bge-m3",
    "dragonkue": "./models/embedding/models--dragonkue--BGE-m3-ko",
}

CONFIG = {
    "VECTOR_DB_DIR": "C:/PnID_RAG/vector_db",
    "ACCIDENTS_DIR": "./data/corpus/accidents",
    "LAWS_DIR": "./data/corpus/laws",
    "DESIGNS_DIR": "./data/corpus/designs",
    "CHEMICALS_DIR": "./data/corpus/chemicals",
    "BASICS_DIR": "./data/corpus/basics",
    "EMBEDDING_MODEL": EMBED_MODEL_VARIANTS["baai"],  # --embed-model 인자로 변경 가능
    "EMBEDDING_DIM": 1024,
    "EMBED_BATCH_SIZE": 32,
    "CHUNK_MAX_TOKENS": 1000,
    "CHUNK_OVERLAP_TOKENS": 100,
}

CHEMICAL_ENTRY_PATTERN = re.compile(
    r"2\.\s*화학사고\s*현장\s*대응\s*물질\s*\(2025\)\s*-\s*물질\s*정보\s*460종\s*-[^\n]*"
)
# NFPA 위험등급 설명 줄 패턴 (화재N:/건강N:/반응N:/특수OX: 등)
NFPA_DESC_RE = re.compile(r"^(화재|건강|반응)\d+:|^특수[\w\-]*\s*:")
CHEMICAL_STOP_LABELS = (
    "국문유사명",
    "영문유사명",
    "ERG대응지침번호",
    "UN번호",
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
        self.corpus_root = Path("./data/corpus")
        self.vector_db_dir = Path(CONFIG["VECTOR_DB_DIR"])
        self.accidents_dir = Path(CONFIG["ACCIDENTS_DIR"])
        self.laws_dir = Path(CONFIG["LAWS_DIR"])
        self.designs_dir = Path(CONFIG["DESIGNS_DIR"])
        self.chemicals_dir = Path(CONFIG["CHEMICALS_DIR"])
        self.basics_dir = Path(CONFIG["BASICS_DIR"])
        self.embedding_model_name = CONFIG["EMBEDDING_MODEL"]
        self.embedding_dim = CONFIG["EMBEDDING_DIM"]
        self.embed_batch_size = CONFIG["EMBED_BATCH_SIZE"]
        self.chunk_max_tokens = CONFIG["CHUNK_MAX_TOKENS"]
        self.chunk_overlap_tokens = CONFIG["CHUNK_OVERLAP_TOKENS"]
        self._model = None
        self._db = None

    def _load_model(self) -> SentenceTransformer:
        if self._model is None:
            print(f"Loading embedding model: {self.embedding_model_name}")
            self._model = SentenceTransformer(self.embedding_model_name)
        return self._model

    def _connect_db(self) -> lancedb.DBConnection:
        if self._db is None:
            self.vector_db_dir.mkdir(parents=True, exist_ok=True)
            self._db = lancedb.connect(str(self.vector_db_dir))
        return self._db

    def _embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load_model()
        embeddings: list[list[float]] = []
        for i in tqdm(
            range(0, len(texts), self.embed_batch_size),
            desc="  Embedding",
            leave=False,
        ):
            batch = texts[i : i + self.embed_batch_size]
            vecs = model.encode(batch, normalize_embeddings=True)
            embeddings.extend(vecs.tolist())
        return embeddings

    def _chunk_by_tokens(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []
        tokenizer = self._load_model().tokenizer
        ids = tokenizer.encode(text, add_special_tokens=False)
        if len(ids) <= self.chunk_max_tokens:
            return [text]
        chunks = []
        start = 0
        step = self.chunk_max_tokens - self.chunk_overlap_tokens
        while start < len(ids):
            end = start + self.chunk_max_tokens
            chunk_text = tokenizer.decode(ids[start:end], skip_special_tokens=True)
            if chunk_text.strip():
                chunks.append(chunk_text)
            if end >= len(ids):
                break
            start += step
        return chunks

    def _source_path(self, path: Path) -> str:
        project_root = self.corpus_root.parent.parent.resolve()
        rel_path = path.resolve().relative_to(project_root)
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
            rf"{re.escape(label)}\s*(.+?)(?={stop_pattern}|$)"
            if stop_pattern
            else rf"{re.escape(label)}\s*(.+)"
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

    def _build_chemical_name(self, entry_text: str) -> str:
        entry_match = CHEMICAL_ENTRY_PATTERN.search(entry_text)
        remainder = entry_text[entry_match.end() :] if entry_match else entry_text

        lines = []
        for line in remainder.splitlines():
            cleaned = self._clean_inline_text(line)
            if cleaned:
                lines.append(cleaned)

        raw_name = lines[0] if lines else ""
        raw_name = re.split(
            r"구조CAS번호|CAS번호|국문유사명|영문유사명|ERG대응지침번호|UN번호",
            raw_name,
            maxsplit=1,
        )[0]
        raw_name = self._clean_inline_text(raw_name)
        korean_name, english_name = self._split_korean_english_name(raw_name)

        if korean_name and english_name:
            base_name = f"{korean_name}({english_name})"
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
            part for part in [korean_alias, english_alias] if part
        )
        return f"{base_name} | {alias_text}" if alias_text else base_name

    def _load_chemical_list(self, xlsx_path: Path) -> list[tuple[str, str]]:
        """화학물질 목록_재정렬.xlsx를 읽어 (ko_name, en_name) 리스트 반환 (460종, 순서대로)."""
        if not xlsx_path.exists():
            print(f"Warning: {xlsx_path} not found. chemical_name will use PDF-extracted names.")
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
        xl = pd.ExcelFile(path)

        def _s(row: pd.Series, key: str) -> str:
            val = row.get(key, "")
            return "" if pd.isna(val) else str(val).strip()

        # 시트1: 분석자료(최종) — PSM 중대산업사고
        if "분석자료(최종)" in xl.sheet_names:
            df = xl.parse("분석자료(최종)")
            # 실제 데이터 컬럼 확인 (개  요 컬럼명에 공백 포함)
            overview_col = next((c for c in df.columns if "개" in str(c) and "요" in str(c)), None)
            for i, row in tqdm(df.iterrows(), total=len(df), desc="  분석자료(최종)"):
                accident  = _s(row, overview_col) if overview_col else ""
                equipment = _s(row, "사고설비")
                material  = _s(row, "사고물질")
                acc_type  = _s(row, "발생형태")
                cause     = _s(row, "사고원인")
                if not accident and not material and not equipment:
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

        # 시트2: 환경부(사고데이터) — 환경부 사고 데이터
        if "환경부(사고데이터)" in xl.sheet_names:
            df = xl.parse("환경부(사고데이터)")
            for i, row in tqdm(df.iterrows(), total=len(df), desc="  환경부(사고데이터)"):
                accident  = _s(row, "사고내용")
                equipment = _s(row, "사고 설비")
                material  = _s(row, "제1사고물질")
                acc_type  = _s(row, "사고유형")
                cause     = _s(row, "사고원인")
                if not accident and not material and not equipment:
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

        return records

    def load_accidents(self):
        print("\n=== Loading accidents ===")
        db = self._connect_db()
        records: list[dict] = []

        xlsx_files = sorted(self.accidents_dir.glob("*.xlsx"))
        print(f"Found {len(xlsx_files)} accident XLSXs")

        for xlsx_path in xlsx_files:
            print(f"Reading {xlsx_path.name} ...")
            df = pd.read_excel(xlsx_path)
            file_tag = xlsx_path.stem.replace(" ", "_")
            for i, row in tqdm(df.iterrows(), total=len(df), desc=f"  {xlsx_path.stem}"):
                accident  = str(row.get("Accident", "") or "").strip()
                equipment = str(row.get("Equipment", "") or "").strip()
                material  = str(row.get("Material", "") or "").strip()
                acc_type  = str(row.get("Type", "") or "").strip()
                cause     = str(row.get("Cause", "") or "").strip()
                if not accident and not material and not equipment:
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

        if not records: return
        print(f"Total accident records: {len(records)}")

        text_vectors = self._embed([r["text"] for r in records])
        material_vectors = self._embed([r["material"] for r in records])
        equipment_vectors = self._embed([r["equipment"] for r in records])
        for r, text_v, material_v, equipment_v in zip(
            records,
            text_vectors,
            material_vectors,
            equipment_vectors,
        ):
            r["text_vector"] = text_v
            r["material_vector"] = material_v
            r["equipment_vector"] = equipment_v

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
        if "accidents" in db.table_names():
            db.drop_table("accidents")
        table = db.create_table("accidents", data=records, schema=schema)
        print(f"accidents table: {table.count_rows()} rows written.")

    def load_laws(self):
        print("\n=== Loading laws ===")
        db = self._connect_db()

        pdf_files = sorted(self.laws_dir.rglob("*.pdf"))
        print(f"Found {len(pdf_files)} law PDFs")

        records: list[dict] = []
        for pdf_path in tqdm(pdf_files, desc="  Laws PDFs"):
            source_path = self._source_path(pdf_path)
            for chunk_id, (page_num, chunk, law_title, article) in enumerate(
                self._chunk_law_by_article(pdf_path)
            ):
                records.append({
                    "id":          f"{pdf_path.stem}_{chunk_id:04d}",
                    "text":        chunk,
                    "source":      pdf_path.name,
                    "chunk_id":    chunk_id,
                    "page":        page_num,
                    "source_path": source_path,
                    "title":       law_title,
                    "article":     article,
                })

        if not records: return
        print(f"Total law chunks: {len(records)}")
        text_vectors    = self._embed([r["text"]    for r in records])
        title_vectors   = self._embed([r["title"]   for r in records])
        article_vectors = self._embed([r["article"] for r in records])
        for r, tv, lv, av in zip(records, text_vectors, title_vectors, article_vectors):
            r["text_vector"]    = tv
            r["title_vector"]   = lv
            r["article_vector"] = av if r["article"] else tv  # 빈 article이면 text_vector 복사

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
        if "laws" in db.table_names():
            db.drop_table("laws")
        table = db.create_table("laws", data=records, schema=schema)
        table.create_fts_index("text", replace=True)
        print(f"laws table: {table.count_rows()} rows written.")

    def load_designs(self):
        print("\n=== Loading designs ===")
        db = self._connect_db()

        records: list[dict] = []
        if not self.designs_dir.exists():
            print(f"Error: {self.designs_dir} does not exist.")
            return

        pdf_files = sorted(self.designs_dir.rglob("*.pdf"))
        print(f"Found {len(pdf_files)} design PDFs")
        for pdf_path in tqdm(pdf_files, desc="  Designs PDFs"):
            source_path = self._source_path(pdf_path)
            parts = pdf_path.parent.relative_to(self.designs_dir).parts
            category = f"{parts[0]}: {parts[1]}" if len(parts) >= 2 else parts[0]
            title = self._extract_design_title(pdf_path)
            for chunk_id, (page_num, chunk) in enumerate(self._chunk_pdf_by_page(pdf_path)):
                section = self._extract_section_from_page(chunk)
                records.append({
                    "id":          f"{pdf_path.stem}_{chunk_id:04d}",
                    "text":        chunk,
                    "source":      pdf_path.name,
                    "chunk_id":    chunk_id,
                    "page":        page_num,
                    "source_path": source_path,
                    "category":    category,
                    "title":       title,
                    "section":     section,
                })

        if not records: return
        print(f"Total design chunks: {len(records)}")
        text_vectors    = self._embed([r["text"]    for r in records])
        title_vectors   = self._embed([r["title"]   for r in records])
        section_vectors = self._embed([r["section"] for r in records])
        for r, tv, gv, sv in zip(records, text_vectors, title_vectors, section_vectors):
            r["text_vector"]    = tv
            r["title_vector"]   = gv
            r["section_vector"] = sv if r["section"] else tv  # 빈 section이면 text_vector 복사

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
            pa.field("section",        pa.string()),
            pa.field("section_vector", pa.list_(pa.float32(), self.embedding_dim)),
        ])
        if "designs" in db.table_names():
            db.drop_table("designs")
        table = db.create_table("designs", data=records, schema=schema)
        table.create_fts_index("text", replace=True)
        print(f"designs table: {table.count_rows()} rows written.")

    def load_basics(self):
        print("\n=== Loading basics ===")
        db = self._connect_db()

        if not self.basics_dir.exists():
            print(f"Error: {self.basics_dir} does not exist.")
            return

        records: list[dict] = []
        for subdir in sorted(self.basics_dir.iterdir()):
            if not subdir.is_dir():
                continue
            category = subdir.name
            pdf_files = sorted(subdir.glob("*.pdf"))
            print(f"  Category [{category}]: {len(pdf_files)} PDFs")
            for pdf_path in tqdm(pdf_files, desc=f"  {category}"):
                source_path = self._source_path(pdf_path)
                title = pdf_path.stem
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

        if not records: return
        print(f"Total basics chunks: {len(records)}")
        text_vectors    = self._embed([r["text"]    for r in records])
        title_vectors   = self._embed([r["title"]   for r in records])
        chapter_vectors = self._embed([r["chapter"] for r in records])
        for r, tv, bv, cv in zip(records, text_vectors, title_vectors, chapter_vectors):
            r["text_vector"]    = tv
            r["title_vector"]   = bv
            r["chapter_vector"] = cv if r["chapter"] else tv  # 빈 chapter이면 text_vector 복사

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
        if "basics" in db.table_names():
            db.drop_table("basics")
        table = db.create_table("basics", data=records, schema=schema)
        table.create_fts_index("text", replace=True)
        print(f"basics table: {table.count_rows()} rows written.")

    def load_chemicals(self):
        print("\n=== Loading chemicals ===")
        db = self._connect_db()

        pdf_files = sorted(self.chemicals_dir.glob("*.pdf"))
        print(f"Found {len(pdf_files)} chemicals PDFs")

        # 화학물질 목록_재정렬.xlsx 로드 (프로젝트 루트 기준)
        xlsx_path = self.corpus_root.parent.parent / "화학물질 목록_재정렬.xlsx"
        chemical_list = self._load_chemical_list(xlsx_path)
        if chemical_list:
            print(f"화학물질 목록_재정렬.xlsx 로드 완료: {len(chemical_list)}종")

        records: list[dict] = []
        for pdf_path in tqdm(pdf_files, desc="  Chemicals PDFs"):
            source_path = self._source_path(pdf_path)
            chunk_id = 0
            chemical_idx = -1          # 물질목록순서.md 인덱스 (0-based)
            current_chemical_name = "" # 현재 물질명 (다음 헤더 나올 때까지 유지)

            for page_num, page_text in self._parse_pdf_pages(pdf_path):
                text = page_text.strip()
                if not text:
                    continue

                # 물질 헤더 감지 → 새 물질 시작
                if CHEMICAL_ENTRY_PATTERN.search(text):
                    chemical_idx += 1

                    # 목록에서 이름 조회
                    if chemical_idx < len(chemical_list):
                        ko, en = chemical_list[chemical_idx]
                        base = f"{ko}({en})" if ko and en else (ko or en or "이름 미상")
                    else:
                        # 목록 범위 초과 시 PDF 텍스트에서 추출
                        base = self._build_chemical_name(text)

                    # 유사명(aliases)은 PDF 텍스트에서 추출
                    alias_ko = self._extract_labeled_value(text, "국문유사명", CHEMICAL_STOP_LABELS)
                    alias_en = self._extract_labeled_value(text, "영문유사명", CHEMICAL_STOP_LABELS)
                    aliases = ", ".join(p for p in [alias_ko, alias_en] if p)
                    current_chemical_name = f"{base} | {aliases}" if aliases else base

                records.append({
                    "id":            f"{pdf_path.stem}_{chunk_id:04d}",
                    "text":          self._clean_chemical_text(text),
                    "source":        pdf_path.name,
                    "chunk_id":      chunk_id,
                    "page":          page_num,
                    "source_path":   source_path,
                    "chemical_name": current_chemical_name,
                })
                chunk_id += 1

        if not records: return
        print(f"Total chemical entries: {len(records)}")
        text_vectors = self._embed([r["text"] for r in records])
        chemical_name_vectors = self._embed([r["chemical_name"] for r in records])
        for r, text_v, chemical_name_v in zip(
            records,
            text_vectors,
            chemical_name_vectors,
        ):
            r["text_vector"] = text_v
            r["chemical_name_vector"] = chemical_name_v

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
        if "chemicals" in db.table_names():
            db.drop_table("chemicals")
        table = db.create_table("chemicals", data=records, schema=schema)
        print(f"chemicals table: {table.count_rows()} rows written.")

    def load_all(self):
        self.load_accidents()
        self.load_laws()
        self.load_designs()
        self.load_chemicals()
        self.load_basics()
        print("\n=== All tables loaded successfully ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load corpus documents into LanceDB.")
    parser.add_argument(
        "--table",
        choices=["accidents", "laws", "designs", "chemicals", "basics", "all"],
        default="all",
        help="Which table to build (default: all)",
    )
    parser.add_argument(
        "--embed-model",
        choices=list(EMBED_MODEL_VARIANTS.keys()),
        default="baai",
        help="임베딩 모델 선택 (default: baai). 모델을 바꾸면 DB 전체 재빌드 필요.",
    )
    args = parser.parse_args()

    CONFIG["EMBEDDING_MODEL"] = EMBED_MODEL_VARIANTS[args.embed_model]
    print(f"임베딩 모델: {CONFIG['EMBEDDING_MODEL']}")

    loader = CorpusLoader()
    dispatch = {
        "accidents": loader.load_accidents,
        "laws":      loader.load_laws,
        "designs":   loader.load_designs,
        "chemicals": loader.load_chemicals,
        "basics":    loader.load_basics,
        "all":       loader.load_all,
    }
    dispatch[args.table]()