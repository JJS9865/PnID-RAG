"""
사고사례 DB의 text 컬럼을 개별 PDF 파일로 생성합니다.
python scripts/generate_accidents_pdf.py --force
"""
import re
import sys
import argparse
from pathlib import Path

import lancedb
from fpdf import FPDF

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = PROJECT_ROOT / "assets" / "fonts"
FONT_REGULAR = str(FONT_DIR / "NanumGothic-Regular.ttf")
FONT_BOLD = str(FONT_DIR / "NanumGothic-Bold.ttf")
DB_PATH = str(PROJECT_ROOT / "data" / "vector_db")
OUTPUT_DIR = PROJECT_ROOT / "data" / "accidents_pdf"

TAG_PATTERN = re.compile(r"\[([^\]]+)\]\s*")
SECTION_TAGS = {"사고내용", "관련설비", "관련물질", "사고유형", "사고원인"}


def _parse_sections(text: str) -> list[tuple[str, str]]:
    """텍스트를 [태그] 단위로 분리"""
    sections = []
    pos = 0
    for m in TAG_PATTERN.finditer(text):
        if m.start() > pos:
            leftover = text[pos:m.start()].strip()
            if leftover:
                sections.append(("", leftover))
        tag = m.group(1)
        tag_end = m.end()
        next_m = TAG_PATTERN.search(text, tag_end)
        content = text[tag_end:next_m.start()].strip() if next_m else text[tag_end:].strip()
        sections.append((tag, content))
        pos = next_m.start() if next_m else len(text)
    if pos == 0:
        sections.append(("", text.strip()))
    return sections


def _create_pdf(doc_id: str, text: str, origin: str, source: str) -> FPDF:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.add_font("NanumGothic", "", FONT_REGULAR)
    pdf.add_font("NanumGothic", "B", FONT_BOLD)

    pdf.set_font("NanumGothic", "B", 16)
    title = "국내 사고사례" if origin == "domestic" else "국외 사고사례"
    pdf.cell(w=0, h=12, text=title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("NanumGothic", "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(w=0, h=6, text=f"문서 ID: {doc_id}  |  출처: {source}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    pdf.set_draw_color(200, 200, 200)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)

    sections = _parse_sections(text)
    for tag, content in sections:
        if tag in SECTION_TAGS:
            pdf.set_font("NanumGothic", "B", 11)
            pdf.cell(w=0, h=8, text=f"[{tag}]", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("NanumGothic", "", 11)
            pdf.multi_cell(w=0, h=7, text=content)
            pdf.ln(3)
        elif tag:
            pdf.set_font("NanumGothic", "B", 11)
            pdf.cell(w=0, h=8, text=f"[{tag}]", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("NanumGothic", "", 11)
            pdf.multi_cell(w=0, h=7, text=content)
            pdf.ln(3)
        else:
            pdf.set_font("NanumGothic", "", 11)
            pdf.multi_cell(w=0, h=7, text=content)
            pdf.ln(3)

    return pdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="기존 PDF 덮어쓰기")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    db = lancedb.connect(DB_PATH)
    table = db.open_table("accidents")
    df = table.to_pandas()

    total = len(df)
    created = 0
    skipped = 0

    print(f"사고사례 {total}건 PDF 생성 시작 → {OUTPUT_DIR}")
    for _, row in df.iterrows():
        doc_id = str(row.get("id", ""))
        if not doc_id:
            continue
        out_path = OUTPUT_DIR / f"{doc_id}.pdf"
        if out_path.exists() and not args.force:
            skipped += 1
            continue

        text = str(row.get("text", "")).strip()
        origin = str(row.get("origin", "")).strip()
        source = str(row.get("source", "")).strip()
        if not text:
            continue

        pdf = _create_pdf(doc_id, text, origin, source)
        pdf.output(str(out_path))
        created += 1

    print(f"완료: 생성={created}, 스킵(기존)={skipped}, 전체={total}")


if __name__ == "__main__":
    main()
