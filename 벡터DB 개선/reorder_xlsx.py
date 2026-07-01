#!/usr/bin/env python3
"""PDF 페이지 순서에 맞게 화학물질 목록.xlsx를 재정렬하는 스크립트.

Usage:
    python reorder_xlsx.py
Output:
    화학물질 목록_재정렬.xlsx
"""

import re
from pathlib import Path
import pandas as pd
import fitz


CHEMICAL_ENTRY_PATTERN = re.compile(
    r"2\.\s*화학사고\s*현장\s*대응\s*물질\s*\(2025\)\s*-\s*물질\s*정보\s*460종\s*-[^\n]*"
)
STOP_LABELS = ("국문유사명", "영문유사명", "ERG대응지침번호", "UN번호", "구조CAS번호", "CAS번호")

# PDF에서 추출한 이름과 xlsx의 이름이 다른 경우 수동 매핑
# key: PDF 추출 한국어명(normalize 후), value: xlsx 국문명
MANUAL_MAPPING = {
    # 1,4-벤젠디카르복실산,비스(2-에틸헥실)에스테르 = 디옥틸 테레프탈산(DOTP)
    "1,4-벤젠디카르복실산,비스(2-에틸헥실)에스테르": "디옥틸 테레프탈산",
    "1,4-벤젠디카르복실산,비스(2-에틸헥실": "디옥틸 테레프탈산",
    # 에테인 vs 에탄 (맞춤법 차이)
    "1,1'-옥시비스(2-메톡시에테인)": "1,1'-옥시비스(2-메톡시에탄)",
}


def extract_names_from_entry(page_text: str) -> tuple[str, str]:
    """화학물질 페이지 텍스트에서 (한국어명, 영어명) 추출.

    긴 이름이 여러 줄로 쪼개지는 경우를 처리:
    - 한국어 문자가 있는 줄 → 한국어명 (여러 줄 연속 가능)
    - 한국어 문자가 없는 줄 → 영어명 (여러 줄 연속 가능)
    - '구조' 단독 줄에서 중단
    """
    m = CHEMICAL_ENTRY_PATTERN.search(page_text)
    if not m:
        return "", ""

    remainder = page_text[m.end():]

    # 알려진 stop label 전까지만 사용
    stop_m = re.search("|".join(re.escape(s) for s in STOP_LABELS), remainder)
    if stop_m:
        remainder = remainder[:stop_m.start()]

    # 줄 수집: '구조' 단독 줄에서 중단 (구조 이미지 섹션 헤더)
    lines: list[str] = []
    for raw in remainder.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s == "구조":
            break
        lines.append(s)

    # 한국어 유무로 분류 후 각각 합치기
    ko_parts = [l for l in lines if re.search(r"[가-힣]", l)]
    en_parts = [l for l in lines if not re.search(r"[가-힣]", l)]

    ko_name = re.sub(r"\s+", " ", " ".join(ko_parts)).strip()
    en_name = re.sub(r"\s+", " ", " ".join(en_parts)).strip()

    return ko_name, en_name


def normalize(name: str) -> str:
    """공백 제거, 소문자화."""
    return re.sub(r"\s+", "", name).lower()


def find_match(ko_name: str, en_name: str,
               ko_exact: dict, ko_norm: dict, en_norm: dict,
               used: set) -> int | None:
    """xlsx에서 ko_name/en_name에 대응하는 행 인덱스 반환."""

    candidates: list[int | None] = [
        # 1. 수동 매핑
        ko_exact.get(MANUAL_MAPPING.get(ko_name, "")),
        ko_exact.get(MANUAL_MAPPING.get(normalize(ko_name), "")),
        # 2. 한국어 정확 매칭
        ko_exact.get(ko_name),
        # 3. 한국어 정규화 매칭
        ko_norm.get(normalize(ko_name)) if ko_name else None,
        # 4. 영어 정규화 매칭
        en_norm.get(normalize(en_name)) if en_name else None,
    ]

    for idx in candidates:
        if idx is not None and idx not in used:
            return idx

    # 5. 한국어 부분 매칭 (최소 길이 조건으로 오매칭 방지)
    if ko_name:
        norm_pdf = normalize(ko_name)
        MIN_LEN = 8  # 너무 짧은 문자열은 오매칭 위험
        if len(norm_pdf) >= MIN_LEN:
            for xlsx_ko, idx in ko_exact.items():
                if idx in used:
                    continue
                norm_xlsx = normalize(xlsx_ko)
                if len(norm_xlsx) >= MIN_LEN and (norm_xlsx in norm_pdf or norm_pdf in norm_xlsx):
                    return idx

    return None


def main():
    base_dir = Path(__file__).parent
    xlsx_path = base_dir / "화학물질 목록.xlsx"
    chemicals_dir = base_dir / "data" / "corpus" / "chemicals"
    output_path = base_dir / "화학물질 목록_재정렬.xlsx"

    # xlsx 로드
    df = pd.read_excel(xlsx_path)
    print(f"xlsx 로드: {len(df)}종\n")

    # 매칭용 인덱스 구성
    ko_exact: dict[str, int] = {}
    ko_norm: dict[str, int] = {}
    en_norm: dict[str, int] = {}
    for i, row in df.iterrows():
        ko = str(row.get("국문명", "") or "").strip()
        en = str(row.get("영문명", "") or "").strip()
        if ko:
            ko_exact[ko] = i
            ko_norm[normalize(ko)] = i
        if en:
            en_norm[normalize(en)] = i

    # PDF에서 화학물질 순서 추출
    pdf_files = sorted(chemicals_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"오류: PDF 없음 ({chemicals_dir})")
        return

    pdf_entries: list[tuple[str, int, str, str]] = []  # (pdf명, 페이지, ko, en)
    for pdf_path in pdf_files:
        doc = fitz.open(str(pdf_path))
        try:
            for page_num, page in enumerate(doc, 1):
                text = page.get_text("text")
                if CHEMICAL_ENTRY_PATTERN.search(text):
                    ko, en = extract_names_from_entry(text)
                    pdf_entries.append((pdf_path.name, page_num, ko, en))
        finally:
            doc.close()

    print(f"PDF에서 화학물질 헤더 발견: {len(pdf_entries)}개\n")

    # 매칭 및 재정렬
    reordered: list[pd.Series] = []
    unmatched: list[tuple] = []
    used: set[int] = set()

    for pdf_file, page_num, ko, en in pdf_entries:
        idx = find_match(ko, en, ko_exact, ko_norm, en_norm, used)
        if idx is not None:
            used.add(idx)
            reordered.append(df.iloc[idx].copy())
        else:
            unmatched.append((pdf_file, page_num, ko, en))

    # 결과 출력
    print(f"매칭 성공: {len(reordered)}/{len(pdf_entries)}")
    if unmatched:
        print(f"미매칭 ({len(unmatched)}개):")
        for pdf_file, page_num, ko, en in unmatched:
            print(f"  p.{page_num}: 한국어={ko!r}, 영어={en!r}")
    print()

    # xlsx에는 있지만 PDF에서 발견 안 된 항목
    unused_indices = set(range(len(df))) - used
    if unused_indices:
        print(f"xlsx에만 있고 PDF에서 미발견 ({len(unused_indices)}개):")
        for i in sorted(unused_indices):
            row = df.iloc[i]
            print(f"  xlsx 행 {i+1}: {row.get('국문명')} / {row.get('영문명')}")
        print()

    # 재정렬된 xlsx 저장
    new_df = pd.DataFrame(reordered).reset_index(drop=True)
    new_df["번호"] = range(1, len(new_df) + 1)
    new_df = new_df[["번호", "영문명", "국문명", "CAS번호"]]
    new_df.to_excel(output_path, index=False)
    print(f"저장 완료: {output_path}")


if __name__ == "__main__":
    main()
