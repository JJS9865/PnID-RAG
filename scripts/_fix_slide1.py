"""Fix update_slide1_table in modify_rag_ppt.py - replace multi-line strings with proper escape sequences"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

TARGET = 'C:/Users/wlwl4/Downloads/hazop-develop/scripts/modify_rag_ppt.py'

with open(TARGET, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find update_slide1_table
start = next(i for i, l in enumerate(lines) if 'def update_slide1_table' in l)
end   = next(i for i, l in enumerate(lines) if 'def main' in l)

new_func = [
    'def update_slide1_table(slide):\n',
    '    """Slide 1의 기존 표를 실제 corpus 5종 데이터로 교체"""\n',
    '    for shape in list(slide.shapes):\n',
    '        if shape.shape_type == 19:  # TABLE\n',
    '            shape._element.getparent().remove(shape._element)\n',
    '            break\n',
    '\n',
    '    new_data = [\n',
    '        ["No.", "데이터 유형", "핵심 지식 내용", "주요 활용 목적", "데이터 건수"],\n',
    '        ["1", "사고사례\\n(accidents)",\n',
    '         "국내외 화학공정 사고 이력\\n사고내용, 관련물질·설비, 사고유형, 원인",\n',
    '         "공정 위험성 질문에 대한\\n유사 사고 사례 검색·제시",\n',
    '         "1,348건\\n(xlsx 3종)"],\n',
    '        ["2", "화학물질정보\\n(chemicals)",\n',
    '         "460종 화학물질의 MSDS 정보\\n위험성, 물성, 취급주의사항",\n',
    '         "특정 물질의 위험성·취급 정보 제공",\n',
    '         "501종\\n(pdf 1종)"],\n',
    '        ["3", "법령\\n(laws)",\n',
    '         "산업안전보건법, 고압가스안전관리법 등\\n국내 법령·고시·기준",\n',
    '         "법규 위반 여부 판단 및\\n해당 조항 근거 제시",\n',
    '         "2,099페이지\\n(pdf 43종)"],\n',
    '        ["4", "설계지침\\n(designs)",\n',
    '         "KOSHA Guide, KGS 코드 등\\n설계·운전 기술지침",\n',
    '         "설계 오류 여부 판단 및\\n개선 기준 제시",\n',
    '         "1,983페이지\\n(pdf 61종)"],\n',
    '        ["5", "화공 기초지식\\n(basics)",\n',
    '         "화공 전공서, 논문, 보고서\\n화학공정 원리·이론",\n',
    '         "배경 지식 기반\\n공정 위험 설명 보완",\n',
    '         "8,165페이지\\n(pdf 15종)"],\n',
    '    ]\n',
    '    add_table(slide, new_data,\n',
    '              l=0.44, t=3.90, w=32.99, h=14.13,\n',
    '              col_widths=[1.2, 3.5, 9.0, 7.0, 3.5],\n',
    '              font_sz=9.5, header_sz=10.5,\n',
    '              h_data=PP_ALIGN.LEFT,\n',
    '              h_first=PP_ALIGN.CENTER,\n',
    '              h_header=PP_ALIGN.CENTER)\n',
    '    print("  Slide 1 표 교체 완료")\n',
    '\n',
    '\n',
]

lines[start:end] = new_func

with open(TARGET, 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('Done. Total lines:', len(lines))
