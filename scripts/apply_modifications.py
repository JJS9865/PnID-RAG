# -*- coding: utf-8 -*-
"""Apply all modifications to modify_rag_ppt.py"""

TARGET = 'scripts/modify_rag_ppt.py'

with open(TARGET, 'r', encoding='utf-8-sig') as f:
    content = f.read()

print(f"File loaded: {len(content)} chars")

# ============================================================
# 수정 1: build_slide_pipeline 의 "LLM 분析" → "사용자 질문 分析"
# (텍스트박스 내용 + 단계별 요약 표)
# ============================================================

# 1-a: build_slide_pipeline 의 LLM 분析 박스 텍스트
old1a = ('    # LLM \ubd84\uc11d \ubc15\uc2a4 (\ud558\ub098\ub85c \ud1b5\ud569)\n'
         '    LX = QX + QW + 0.5\n'
         '    LW = 3.2\n'
         '    add_rect(slide, LX, Y, LW, TOTAL_H, fill_hex=LBLUE, line_hex=BLUE, line_pt=0.8)\n'
         '    add_textbox(slide, LX, Y + TOTAL_H/2 - 0.55, LW, 1.1, [\n'
         '        {"text": "LLM \ubd84\uc11d", "sz": 10, "bold": True, "color_hex": NAVY,\n'
         '         "align": PP_ALIGN.CENTER},\n'
         '        {"text": "(GPT-OSS-20B)", "sz": 8, "color_hex": TEAL,\n'
         '         "align": PP_ALIGN.CENTER},\n'
         '        {"text": "\uc758\ub3c4+\uc5d4\ud2f0\ud2f0", "sz": 7.5, "color_hex": TEAL,\n'
         '         "align": PP_ALIGN.CENTER},\n'
         '    ])')

new1a = ('    # \uc0ac\uc6a9\uc790 \uc9c8\ubb38 \u5206\u6790 \ubc15\uc2a4 (\ud558\ub098\ub85c \ud1b5\ud569)\n'
         '    LX = QX + QW + 0.5\n'
         '    LW = 3.2\n'
         '    add_rect(slide, LX, Y, LW, TOTAL_H, fill_hex=LBLUE, line_hex=BLUE, line_pt=0.8)\n'
         '    add_textbox(slide, LX, Y + TOTAL_H/2 - 0.55, LW, 1.1, [\n'
         '        {"text": "\uc0ac\uc6a9\uc790 \uc9c8\ubb38 \u5206\u6790", "sz": 10, "bold": True, "color_hex": NAVY,\n'
         '         "align": PP_ALIGN.CENTER},\n'
         '        {"text": "(GPT-OSS-20B)", "sz": 8, "color_hex": TEAL,\n'
         '         "align": PP_ALIGN.CENTER},\n'
         '        {"text": "\uc758\ub3c4+\uc5d4\ud2f0\ud2f0", "sz": 7.5, "color_hex": TEAL,\n'
         '         "align": PP_ALIGN.CENTER},\n'
         '    ])')

if old1a in content:
    content = content.replace(old1a, new1a, 1)
    print("수정 1-a 완료: build_slide_pipeline LLM 분析 박스")
else:
    print("수정 1-a 실패: 대상 문자열을 찾지 못함")

# 1-b: 단계별 요약 표의 "LLM 분析" 행
old1b = '        ["LLM \ubd84\uc11d",         "\uc758\ub3c4 \ud310\ub2e8 + \ubb3c\uc9c8\u00b7\uc124\ube44\uba85 \ucd94\ucd9c",              "intents / target_material / target_equipment"],'
new1b = '        ["\uc0ac\uc6a9\uc790 \uc9c8\ubb38 \u5206\u6790", "\uc758\ub3c4 \ud310\ub2e8 + \ubb3c\uc9c8\u00b7\uc124\ube44\uba85 \ucd94\ucd9c",              "intents / target_material / target_equipment"],'

if old1b in content:
    content = content.replace(old1b, new1b, 1)
    print("수정 1-b 완료: 단계별 요약 표 LLM 분析 행")
else:
    print("수정 1-b 실패: 대상 문자열을 찾지 못함")

# ============================================================
# 수정 2: build_slide16 완전 재작성
# ============================================================

old_slide16_start = ('# \u2550' * 1 +
                      '\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n'
                      '# Slide 5: \uc9c8\ubb38 \ubd84\uc11d \u2014 LLM \ucc98\ub9ac\n'
                      '# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550')

# Use regex to find and replace the entire build_slide16 function
import re

# Find the block from the comment before build_slide16 to the start of build_slide17's comment
pattern_slide16 = re.compile(
    r'# \u2550{74}\n# Slide 5: \uc9c8\ubb38 \ubd84\uc11d \u2014 LLM \ucc98\ub9ac\n# \u2550{74}\n\ndef build_slide16\(slide\):.*?(?=\n# \u2550{74}\n# Slide 1[67])',
    re.DOTALL
)

new_slide16 = '''# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# Slide 5: \uc0ac\uc6a9\uc790 \uc9c8\ubb38 \u5206\u6790
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def build_slide16(slide):
    clear_slide(slide)
    update_title(slide, "RAG \uad6c\ucd95 - \uc0ac\uc6a9\uc790 \uc9c8\ubb38 \u5206\u6790")
    update_titlebar(slide,
        "\uc0ac\uc6a9\uc790 \uc9c8\ubb38 \u5206\u6790",
        "LLM\uc774 \uc9c8\ubb38\uc5d0\uc11c \uac80\uc0c9\uc5d0 \ud544\uc694\ud55c \uc815\ubcf4\ub97c \ud55c \ubc88\uc5d0 \ucd94\ucd9c \u2014 \ub864\uae30\ubc18 \ub300\ube44 \uc7a5\uc810")

    Y = 6.3

    # === \uc65c LLM\uc73c\ub85c \uc9c8\ubb38\uc744 \ubd84\ub958\ud558\ub294\uac00? ===
    section_header(slide, 0.8, Y, 32, "\uc65c LLM\uc73c\ub85c \uc9c8\ubb38\uc744 \ubd84\ub958\ud558\ub294\uac00?")
    Y += 0.65

    add_textbox(slide, 0.8, Y, 32.0, 0.35, [
        {"text": "\ud574\uc57c \ud560 \uc791\uc5c5: \uc0ac\uc6a9\uc790 \uc9c8\ubb38\uc5d0\uc11c \uc758\ub3c4(\uc5b4\ub290 DB\ub97c \uac80\uc0c9\ud560\uc9c0)\uc640 \ud575\uc2ec \uc815\ubcf4(\ubb3c\uc9c8\uba85\u00b7\uc124\ube44\uba85)\ub97c \ub3d9\uc2dc\uc5d0 \ud30c\uc545",
         "sz": 9, "bold": True, "color_hex": NAVY}
    ])
    Y += 0.45

    add_textbox(slide, 0.8, Y, 32.0, 1.6, [
        {"text": "\ub864\uae30\ubc18 \ubc29\uc2dd(\ud0a4\uc6cc\ub4dc/\ud328\ud134 \ub9e4\uce6d)\uc73c\ub85c \ud558\uba74?",
         "sz": 9, "bold": True, "color_hex": TEAL},
        {"text": "  - \ubc29\ubc95: \"\ud3ed\ubc1c\"\u00b7\"\uc704\ud5d8\" \ub4f1 \ud0a4\uc6cc\ub4dc \uc874\uc7ac \uc2dc risk\ub85c \ud310\ub2e8, \uc0ac\uc804 \uc815\uc758\ub41c \ubb3c\uc9c8\uba85 \ubaa9\ub85d\uacfc \ud328\ud134 \ub9e4\uce6d\uc73c\ub85c \ucd94\ucd9c",
         "sz": 8.5, "color_hex": GRAY20},
        {"text": "  - \ud55c\uacc4 \u2460: \ud654\ud559\uacf5\uc815 \ubb3c\uc9c8\u00b7\uc124\ube44\uba85\uc740 \uc218\uccad \uc885 \uc774\uc0c1 \u2192 \uc0ac\uc804 \uc644\uc131 \ud604\uc2e4\uc801\uc73c\ub85c \ubd88\uac00, \uc2e0\uc870\uc5b4\u00b7\uc57d\uc5b4 \ub300\uc751 \ubd88\uac00",
         "sz": 8.5, "color_hex": GRAY20},
        {"text": "  - \ud55c\uacc4 \u2461: \uc608\uc678 \ucf00\uc774\uc2a4 \ubc1c\uc0dd\ub9c8\ub2e4 \uaddc\uce59 \ucd94\uac00 \u2192 \ucf54\ub4dc \ubcf5\uc7a1\ub3c4 \ubb34\ud55c \uc99d\uac00, \uc720\uc9c0\ubcf4\uc218 \ubd88\uac00",
         "sz": 8.5, "color_hex": GRAY20},
    ])
    Y += 1.7

    add_textbox(slide, 0.8, Y, 32.0, 0.8, [
        {"text": "LLM + Few-shot\uc73c\ub85c \ud574\uacb0:",
         "sz": 9, "bold": True, "color_hex": GREEN},
        {"text": "  \uc608\uc2dc Q&A \uba87 \uac1c\ub9cc \ud504\ub86c\ud504\ud2b8\uc5d0 \ud3ec\ud568 \u2192 \uc0c8\ub85c\uc6b4 \ud45c\ud604\u00b7\ubcf5\ud569 \uc9c8\ubb38\u00b7\ud654\ud559 \uc804\ubb38 \uc6a9\uc5b4\ub3c4 \ubb38\ub9e5 \ud30c\uc545\ud558\uc5ec \ucc98\ub9ac / \ubcc4\ub3c4 \ud559\uc2b5 \ubd88\ud544\uc694",
         "sz": 8.5, "color_hex": GRAY20},
    ])
    Y += 1.0

    # === LLM \ud638\ucd9c \uad6c\uc870 \ubc0f \uc608\uc2dc ===
    section_header(slide, 0.8, Y, 32, "LLM \ud638\ucd9c \uad6c\uc870 \ubc0f \uc608\uc2dc")
    Y += 0.65

    # \uc67c\ucabd: \ud504\ub86c\ud504\ud2b8 \uad6c\uc870 \ucf54\ub4dc\ubc15\uc2a4
    LW = 18.0
    RW = 32.0 - LW - 0.6
    RX = 0.8 + LW + 0.6

    add_code_box(slide, 0.8, Y, LW, 5.8, [
        "[\uc2dc\uc2a4\ud15c \ud504\ub86c\ud504\ud2b8]",
        "\uc5ed\ud560: \ub108\ub294 \ud654\ud559\uacf5\uc815 \uc548\uc804 \uc804\ubb38 AI\uc57c.",
        "      \uc0ac\uc6a9\uc790 \uc9c8\ubb38\uc5d0\uc11c \uc758\ub3c4\uc640 \ud575\uc2ec \uc815\ubcf4\ub97c \ucd94\ucd9c\ud574.",
        '\ucd9c\ub825 \ud615\uc2dd: {"intents": ..., "target_material": "...", "target_equipment": "..."} JSON\ub9cc \ubc18\ud658',
        "",
        "[Few-shot \uc608\uc2dc]",
        '  Q: "\uc548\uc804\ubc38\ube0c \ubbf8\uc124\uce58 \uc2dc \uacfc\ud0dc\ub8cc\uac00 \uc5bc\ub9c8\uc778\uc9c0 \uc54c\ub824\uc918."',
        '  A: {"intents": "law", "target_material": "None", "target_equipment": "\uc548\uc804\ubc38\ube0c"}',
        "",
        '  Q: "V-101 \ud0f1\ud06c \ub0b4\ubd80 \uc555\ub825 \uae09\uc0c1\uc2b9 \uc2dc \ud3ed\ubc1c \uac00\ub2a5\uc131?"',
        '  A: {"intents": "risk", "target_material": "None", "target_equipment": "V-101 \ud0f1\ud06c"}',
        "",
        '  Q: "\uc774 \uc124\ube44 \uc704\ud5d8\ud574?"',
        '  A: {"intents": "risk", "target_material": "None", "target_equipment": "None"}',
        "",
        "[\uc720\uc800 \ud504\ub86c\ud504\ud2b8]",
        "  \ud1f0\ub8e8\uc5d4\uc744 \ucde8\uae09\ud558\ub294 \ubc18\uc751\uae30\uc758 \ud3ed\ubc1c \uc704\ud5d8\uc131\uc744 \uc54c\ub824\uc918.",
    ], font_sz=8.5)

    # \uc624\ub978\ucabd: LLM \ucd9c\ub825 + \ud65c\uc6a9 \ud45c
    add_textbox(slide, RX, Y, RW, 0.4, [
        {"text": "LLM \ucd9c\ub825", "sz": 9, "bold": True, "color_hex": ORANGE}
    ])
    add_code_box(slide, RX, Y + 0.45, RW, 1.4, [
        '{',
        '  "intents": "risk",',
        '  "target_material": "\ud1f0\ub8e8\uc5d4",',
        '  "target_equipment": "\ubc18\uc751\uae30"',
        '}',
    ], font_sz=9)

    usage_data = [
        ["\ucd9c\ub825 \ud544\ub4dc",         "\ud65c\uc6a9"],
        ["intents",          "\uac80\uc0c9 \ub300\uc0c1 DB \uacb0\uc815\n\"risk\" \u2192 accidents + chemicals"],
        ["target_material",  "accidents DB material \ubca1\ud130 \uc815\ubc00 \ub9e4\uce6d"],
        ["target_equipment", "accidents DB equipment \ubca1\ud130 \uc815\ubc00 \ub9e4\uce6d"],
        ["\uac12\uc774 None\uc774\uba74",     "\ud574\ub2f9 \ud544\ub4dc \ub9e4\uce6d \uc0dd\ub7b5\n\u2192 \uc804\uccb4 text_vector\ub85c\ub9cc \uac80\uc0c9"],
    ]
    add_table(slide, usage_data,
              l=RX, t=Y + 2.05, w=RW, h=3.6,
              col_widths=[4, 7.5],
              font_sz=8.5, header_sz=9.5,
              h_data=PP_ALIGN.LEFT)'''

m16 = pattern_slide16.search(content)
if m16:
    content = content[:m16.start()] + new_slide16 + content[m16.end():]
    print("수정 2 완료: build_slide16 재작성")
else:
    print("수정 2 실패: build_slide16 블록을 찾지 못함")
    # Debug: show what patterns exist
    import re
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'Slide 5' in line or 'build_slide16' in line:
            print(f"  Line {i}: {repr(line)}")

# ============================================================
# 수정 3 & 4 & 5: build_slide_semantic, build_slide_bm25 추가 +
#                  build_slide17 재작성
# 이 세 함수를 한 블록으로 build_slide16 뒤, build_slide18 앞에 삽입
# ============================================================

new_slides_semantic_bm25_slide17 = '''

# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# Slide 6: \uac80\uc0c9 \u2014 Semantic Search
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def build_slide_semantic(slide):
    clear_slide(slide)
    update_title(slide, "RAG \uad6c\ucd95 - \uac80\uc0c9 (Semantic Search)")
    update_titlebar(slide,
        "\uac80\uc0c9 (1\ub2e8\uacc4)  \u2014  Semantic Search",
        "\ud14d\uc2a4\ud2b8\ub97c \ubca1\ud130\ub85c \ubcc0\ud658\ud574 \uc758\ubbf8 \uae30\ubc18\uc73c\ub85c \uc720\uc0ac \ubb38\uc11c\ub97c \ucc3e\ub294\ub2e4")

    Y = 6.3

    # === Semantic Search\ub780? ===
    section_header(slide, 0.8, Y, 32, "Semantic Search\ub780?")
    Y += 0.65

    add_textbox(slide, 0.8, Y, 32.0, 0.55, [
        {"text": "\ud14d\uc2a4\ud2b8\ub97c \uace0\ucc28\uc6d0 \uc22b\uc790 \ubc30\uc5f4(\ubca1\ud130)\ub85c \ubcc0\ud658\ud574 \uc758\ubbf8\uac00 \ube44\uc2b7\ud55c \ubb38\uc11c\ub97c \ucc3e\ub294 \uac80\uc0c9 \ubc29\uc2dd.",
         "sz": 9.5, "color_hex": GRAY20},
        {"text": "\ud575\uc2ec \uc544\uc774\ub514\uc5b4: \"\ube44\uc2b7\ud55c \uc758\ubbf8 = \ubca1\ud130 \uacf5\uac04\uc5d0\uc11c \uac00\uae4c\uc6b4 \uc704\uce58\"",
         "sz": 9.5, "bold": True, "color_hex": NAVY},
    ])
    Y += 0.75

    add_code_box(slide, 0.8, Y, 32.0, 2.1, [
        '\uc608\uc2dc:',
        '  "\ud1f0\ub8e8\uc5d4 \ubc18\uc751\uae30 \ud3ed\ubc1c \uc704\ud5d8"   \u2192  [0.12, -0.85,  0.43, ...]  (1,024\ucc28\uc6d0)',
        '  "\uc778\ud654\uc131 \ubb3c\uc9c8 \uc6a9\uae30 \ud654\uc7ac \uc0ac\uace0" \u2192  [0.10, -0.81,  0.39, ...]  \u2190 \uc758\ubbf8 \uc720\uc0ac \u2192 \ubca1\ud130 \uac00\uae4c\uc6c0',
        '  "\ud39c\ud504 \uc720\ub7c9 \uce21\uc815 \ubc29\ubc95"        \u2192  [0.91,  0.23, -0.67, ...]  \u2190 \uc758\ubbf8 \ubb34\uad00 \u2192 \ubca1\ud130 \ub9d4',
        '',
        '\u2192 \ud45c\ud604\uc774 \ub2ec\ub77c\ub3c4 \uc758\ubbf8\uac00 \uc720\uc0ac\ud558\uba74 \uac80\uc0c9 \uac00\ub2a5 (\ud0a4\uc6cc\ub4dc \uc644\uc804 \uc77c\uce58 \ubd88\ud544\uc694)',
    ], font_sz=8.5)
    Y += 2.3

    # === \uba54\ucee4\ub2c8\uc998 \ub2e8\uacc4 (\ubc15\uc2a4+\ud654\uc0b4\ud45c \ub3c4\uc2dd) ===
    section_header(slide, 0.8, Y, 32, "\uba54\ucee4\ub2c8\uc998 \ub2e8\uacc4")
    Y += 0.65

    steps_sem = [
        ("\uc9c8\ubb38 \ud14d\uc2a4\ud2b8", PGRAY, PGRAY2, GRAY20),
        ("BGE-M3\n\uc784\ubca0\ub529 \ubaa8\ub378", LBLUE, BLUE, NAVY),
        ("1,024\ucc28\uc6d0\n\ubca1\ud130 \ubcc0\ud658", LBLUE, BLUE, NAVY),
        ("\ucf54\uc0ac\uc778 \uc720\uc0ac\ub3c4\n\uacc4\uc0b0", LBLUE, BLUE, NAVY),
        ("\uc0c1\uc704 N\uac74\n\ud6c4\ubcf4 \ucd94\ucd9c", LGREEN, GREEN, GREEN),
    ]
    BW_S = (32.0 - 4 * 0.5) / 5  # \u2248 6.0
    AW_S = 0.5
    BH_S = 1.7
    SX = 0.8
    for i, (label, fill, border, tc) in enumerate(steps_sem):
        add_rect(slide, SX, Y, BW_S, BH_S, fill_hex=fill, line_hex=border, line_pt=1.0)
        add_textbox(slide, SX + 0.1, Y + 0.2, BW_S - 0.2, BH_S - 0.2, [
            {"text": label, "sz": 9, "bold": True, "color_hex": tc, "align": PP_ALIGN.CENTER}
        ])
        SX += BW_S
        if i < 4:
            add_textbox(slide, SX, Y + BH_S / 2 - 0.22, AW_S, 0.44, [
                {"text": "\u2192", "sz": 12, "bold": True, "color_hex": GRAY20, "align": PP_ALIGN.CENTER}
            ])
            SX += AW_S

    Y += BH_S + 0.2

    add_textbox(slide, 0.8, Y, 32.0, 0.5, [
        {"text": "\ucf54\uc0ac\uc778 \uc720\uc0ac\ub3c4 = cos(\u03b8) = (A\u00b7B) / (|A||B|)   \u2014 1\uc5d0 \uac00\uae4c\uc6b8\uc218\ub85d \uc758\ubbf8 \uc720\uc0ac, 0\uc774\uba74 \ubb34\uad00",
         "sz": 8.5, "color_hex": GRAY50},
    ])
    Y += 0.7

    # === BGE-M3 \uc120\ud0dd \uc774\uc720 + \uac15\uc810\u00b7\uc57d\uc810 ===
    section_header(slide, 0.8, Y, 32, "BGE-M3 \uc120\ud0dd \uc774\uc720 + \uac15\uc810\u00b7\uc57d\uc810")
    Y += 0.65

    HALF_W_S = 15.8
    GAP_S = 0.6
    X2_S = 0.8 + HALF_W_S + GAP_S

    # \uc67c\ucabd: \uc120\ud0dd \uc774\uc720
    add_textbox(slide, 0.8, Y, HALF_W_S, 1.5, [
        {"text": "BGE-M3 \uc120\ud0dd \uc774\uc720", "sz": 9, "bold": True, "color_hex": TEAL},
        {"text": "\u25b8  \ud55c\uad6d\uc5b4\u00b7\uc601\uc5b4 \ub3d9\uc2dc \uc9c0\uc6d0 \u2192 \ubc95\ub839\uba85(\ud55c\uad6d\uc5b4) + \ud654\ud559\ubb3c\uc9c8\uba85(\uc601\ubb38 \ud63c\uc7ac) \ubaa8\ub450 \ucc98\ub9ac",
         "sz": 8.5, "color_hex": GRAY20},
        {"text": "\u25b8  1,024\ucc28\uc6d0: \ud654\ud559\uacf5\uc815 \uc804\ubb38 \ubb38\uc11c\uc758 \ubcf5\uc7a1\ud55c \uc758\ubbf8 \ud45c\ud604\uc5d0 \ucda9\ubd84\ud55c \ud45c\ud604\ub825",
         "sz": 8.5, "color_hex": GRAY20},
    ])

    # \uc624\ub978\ucabd: \uac15\uc810\u00b7\uc57d\uc810
    sw_data = [
        ["",       "\ub0b4\uc6a9"],
        ["\uac15\uc810",   "\"\ud3ed\ubc1c \uc0ac\uace0\"\uc640 \"\ud654\uc7ac \uc0ac\uace0\"\ucccc\ub984 \ud45c\ud604\uc774 \ub2e4\ub978 \uc720\uc0ac \uc0ac\uace0 \uac80\uc0c9 \uac00\ub2a5"],
        ["\uc57d\uc810",   "\"\uc0b0\uc548\ubc95 \uc81836\uc870\", \"V-101\" \uac19\uc740 \uace0\uc720 \ubc88\ud638\u00b7\ucf54\ub4dc\ub294 \uc758\ubbf8 \ubca1\ud130\ub85c \uad6c\ubd84 \uc5b4\ub824\uc6c0"],
    ]
    add_table(slide, sw_data,
              l=X2_S, t=Y, w=HALF_W_S, h=1.8,
              col_widths=[1.8, 10],
              font_sz=8.5, header_sz=9,
              h_data=PP_ALIGN.LEFT)

    Y += 2.0
    add_textbox(slide, 0.8, Y, 32.0, 0.4, [
        {"text": "\u2192 \uc774 \uc57d\uc810\uc744 \ubcf4\uc644\ud558\uae30 \uc704\ud574 BM25\ub97c \ud568\uaed8 \uc0ac\uc6a9 (\ub2e4\uc74c \uc2ac\ub77c\uc774\ub4dc)",
         "sz": 9, "bold": True, "color_hex": NAVY}
    ])


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# Slide 7: \uac80\uc0c9 \u2014 BM25 + Hybrid Score
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def build_slide_bm25(slide):
    clear_slide(slide)
    update_title(slide, "RAG \uad6c\ucd95 - \uac80\uc0c9 (BM25 + Hybrid)")
    update_titlebar(slide,
        "\uac80\uc0c9 (2\ub2e8\uacc4)  \u2014  BM25 + Hybrid Score",
        "\ud0a4\uc6cc\ub4dc \ube48\ub3c4 \uae30\ubc18 BM25\uc640 Semantic\uc744 \ud569\uc0b0\ud574 \uc0c1\ud638 \uc57d\uc810 \ubcf4\uc644")

    Y = 6.3

    # === BM25\ub780? ===
    section_header(slide, 0.8, Y, 32, "BM25\ub780?")
    Y += 0.65

    add_textbox(slide, 0.8, Y, 32.0, 0.4, [
        {"text": "\ub2e8\uc5b4\uc758 \ucd9c\ud604 \ube48\ub3c4\ub97c \uae30\ubc18\uc73c\ub85c \ubb38\uc11c\uc758 \uad00\ub828\ub3c4\ub97c \uacc4\uc0b0\ud558\ub294 \uace0\uc804 \uc815\ubcf4 \uac80\uc0c9 \uc54c\uace0\ub9ac\uc998. \ub450 \uac00\uc9c0 \ud575\uc2ec \uac1c\ub150:",
         "sz": 9, "color_hex": GRAY20}
    ])
    Y += 0.55

    tf_idf_data = [
        ["\uac1c\ub150",  "\uc758\ubbf8",                                  "\uc608\uc2dc"],
        ["TF\n(Term Frequency)",
         "\uc774 \ubb38\uc11c\uc5d0 \ud574\ub2f9 \ub2e8\uc5b4\uac00 \uc5bc\ub9c8\ub098 \uc790\uc8fc \ub098\uc624\ub294\uac00",
         "\"\ud1f0\ub8e8\uc5d4\"\uc774 5\ubc88 \ub4f1\uc7a5 \u2192 TF \ub192\uc74c"],
        ["IDF\n(Inverse Document Frequency)",
         "\uc804\uccb4 \ubb38\uc11c \uc911 \uc774 \ub2e8\uc5b4\uac00 \uc5bc\ub9c8\ub098 \ud76c\uadc0\ud55c\uac00",
         "\"\uc744/\uc774\"\ub294 \ud754\ud568 \u2192 IDF \ub099\uc74c\n\"\ud1f0\ub8e8\uc5d4\"\uc740 \ud76c\uadc0 \u2192 IDF \ub192\uc74c"],
    ]
    add_table(slide, tf_idf_data,
              l=0.8, t=Y, w=32.0, h=2.5,
              col_widths=[3.5, 8, 8],
              font_sz=8.5, header_sz=9.5,
              h_data=PP_ALIGN.LEFT)
    Y += 2.65

    add_code_box(slide, 0.8, Y, 32.0, 0.85, [
        "BM25 \uc810\uc218 = TF(\ub2e8\uc5b4, \ubb38\uc11c) \u00d7 IDF(\ub2e8\uc5b4)  \u2192  0~1\ub85c \uc815\uaddc\ud654",
        "\u2192 \ud754\ud55c \uc870\uc0ac(\"\uc744\", \"\uc774\")\ub294 \uc810\uc218 \ub099\uc74c / \uc804\ubb38 \uc6a9\uc5b4(\"\uc0b0\uc548\ubc95 \uc81836\uc870\", \"V-101\")\ub294 \uc810\uc218 \ub192\uc74c",
    ], font_sz=9)
    Y += 1.05

    # === BM25 vs Semantic \ube44\uad50 + Hybrid \uc120\ud0dd \uc774\uc720 ===
    section_header(slide, 0.8, Y, 32, "BM25 vs Semantic \ube44\uad50 \u2192 \uc65c Hybrid?")
    Y += 0.65

    cmp_data = [
        ["",        "Semantic Search",                       "BM25"],
        ["\uac15\uc810",    "\ud45c\ud604\uc774 \ub2ec\ub77c\ub3c4 \uc758\ubbf8 \uc720\uc0ac \ubb38\uc11c \ud0d0\uc0c9",      "\uc804\ubb38 \uc6a9\uc5b4\u00b7\ubc95\uc870\ud56d \ubc88\ud638 \uc815\ud655 \ub9e4\uce6d"],
        ["\uc57d\uc810",   "\uace0\uc720 \ubc88\ud638\u00b7\ucf54\ub4dc\uba85 \uad6c\ubd84 \uc5b4\ub824\uc6c0",           "\ud45c\ud604\uc774 \ub2e4\ub978 \uc720\uc0ac \uc0ac\uace0 \ud0d0\uc0c9 \ubd88\uac00"],
        ["\uacb0\ub860",    "\u2192 \ub450 \ubc29\uc2dd\uc774 \uc11c\ub85c\uc758 \uc57d\uc810\uc744 \uc815\ud655\ud788 \ubcf4\uc644  \u2192  Hybrid\ub85c \uacb0\ud569", ""],
    ]
    add_table(slide, cmp_data,
              l=0.8, t=Y, w=32.0, h=2.5,
              col_widths=[2.5, 9, 9],
              font_sz=8.5, header_sz=9.5,
              h_data=PP_ALIGN.LEFT)
    Y += 2.7

    add_textbox(slide, 0.8, Y, 32.0, 0.4, [
        {"text": "\u25b8  BM25 \uc120\ud0dd \ucd94\uac00 \uc774\uc720: LanceDB\uc5d0 \uae30\ubcf8 \ub0b4\uc7a5 \u2192 \ubcc4\ub3c4 \uad6c\ud604 \ubd88\ud544\uc694",
         "sz": 8.5, "color_hex": GRAY50}
    ])
    Y += 0.6

    # === Hybrid Score \ud569\uc0b0 \ubc0f \ud6c4\ubcf4 \uc120\ubcc4 ===
    section_header(slide, 0.8, Y, 32, "Hybrid Score \ud569\uc0b0 \ubc0f \ud6c4\ubcf4 \uc120\ubcc4")
    Y += 0.65

    add_code_box(slide, 0.8, Y, 32.0, 0.7, [
        "Hybrid Score = 0.5 \u00d7 Semantic \uc810\uc218 + 0.5 \u00d7 BM25 \uc810\uc218  \u2192  \uc0c1\uc704 N\uac74 \ud6c4\ubcf4 \uc120\ubcc4",
    ], font_sz=9.5)
    Y += 0.9

    cand_data = [
        ["\ud14c\uc774\ube14",    "1\ucc28 \uc0c1\uc704 \ud6c4\ubcf4 \uc218", "\ube44\uace0"],
        ["accidents", "300\uac74",           "re-ranking\uc5d0\uc11c \uc815\ubc00 \uc120\ubcc4\ud560 \uac83\uc774\ubbc0\ub85c \ub113\ub125\ud558\uac8c"],
        ["chemicals", "3\uac74",             "\ubb3c\uc9c8 1\uc885 = 1\uccad\ud06c \uad6c\uc870 \u2192 \uc18c\uc218\ub85c \ucda9\ubd84"],
        ["laws",      "10\uac74",            ""],
        ["designs",   "10\uac74",            ""],
    ]
    add_table(slide, cand_data,
              l=0.8, t=Y, w=32.0, h=2.5,
              col_widths=[3, 4, 12],
              font_sz=8.5, header_sz=9.5,
              h_data=PP_ALIGN.LEFT)


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# Slide 8: \uac80\uc0c9 \u2014 2\ucc28 Cross-Encoder Re-ranking
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def build_slide17(slide):
    clear_slide(slide)
    update_title(slide, "RAG \uad6c\ucd95 - \uac80\uc0c9 (Re-ranking)")
    update_titlebar(slide,
        "\uac80\uc0c9 (3\ub2e8\uacc4)  \u2014  Cross-Encoder Re-ranking",
        "1\ucc28 \ub300\ub7c9 \ud6c4\ubcf4\ub97c (\uc9c8\ubb38, \ubb38\uc11c) \uc30d\uc73c\ub85c \uc815\ubc00 \uc7ac\uc815\ub82c \u2192 \ucd5c\uc885 \uc18c\uc218 \ubb38\uc11c \uc120\ubcc4")

    Y = 6.3

    # === \uc65c Re-ranking\uc774 \ud544\uc694\ud55c\uac00? ===
    section_header(slide, 0.8, Y, 32, "\uc65c Re-ranking\uc774 \ud544\uc694\ud55c\uac00?")
    Y += 0.65

    add_textbox(slide, 0.8, Y, 32.0, 2.2, [
        {"text": "1\ucc28 Hybrid Search\uc758 \uad6c\uc870\uc801 \ud55c\uacc4:",
         "sz": 9, "bold": True, "color_hex": TEAL},
        {"text": "  \u25b8  Semantic Search: \uc9c8\ubb38 \ubca1\ud130\uc640 \ubb38\uc11c \ubca1\ud130\ub97c \uac01\uac01 \ub530\ub85c \ub9cc\ub4e0 \ub4a4 \uc720\uc0ac\ub3c4 \ube44\uad50 \u2192 \uc9c8\ubb38 \ubb38\ub9e5\uc744 \ubb38\uc11c \uc778\ucf54\ub529\uc5d0 \ubc18\uc601 \ubd88\uac00",
         "sz": 8.5, "color_hex": GRAY20},
        {"text": "  \u25b8  BM25: \ub2e8\uc5b4 \ube48\ub3c4\ub9cc \ubcf4\uc73c\ubbc0\ub85c \"\ubc18\uc751\uae30\"\ub77c\ub294 \ub2e8\uc5b4\uac00 \ub9ce\uc740 \ubb34\uad00\ud55c \ubb38\uc11c\uac00 \uc0c1\uc704\uc5d0 \uc62c \uc218 \uc788\uc74c",
         "sz": 8.5, "color_hex": GRAY20},
        {"text": "  \u2192 \uacb0\uacfc\uc801\uc73c\ub85c 1\ucc28\uc5d0\uc11c\ub294 \uad00\ub828 \uc788\uc5b4 \ubcf4\uc774\uc9c0\ub9cc \uc2e4\uc81c\ub85c\ub294 \ubb34\uad00\ud55c \ubb38\uc11c\uac00 \uc12f\uc5ec \ub4e4\uc5b4\uc634",
         "sz": 8.5, "bold": True, "color_hex": ORANGE},
        {"text": "Cross-Encoder Re-ranking: (\uc9c8\ubb38, \ubb38\uc11c) \uc30d\uc744 \ud568\uaed8 \ubaa8\ub378\uc5d0 \uc785\ub825 \u2192 \uc9c8\ubb38 \ub9e5\ub77d\uc5d0\uc11c \uc774 \ubb38\uc11c\uac00 \uc2e4\uc81c\ub85c \uad00\ub828 \uc788\ub294\uc9c0 \uc9c1\uc811 \ud310\ub2e8",
         "sz": 8.5, "bold": True, "color_hex": GREEN},
    ])
    Y += 2.4

    # === Cross-Encoder \uba54\ucee4\ub2c8\uc998 ===
    section_header(slide, 0.8, Y, 32, "Cross-Encoder \uba54\ucee4\ub2c8\uc998")
    Y += 0.65

    add_code_box(slide, 0.8, Y, 32.0, 2.7, [
        "Hybrid Search \ud6c4\ubcf4 (\uc608: accidents 300\uac74)",
        "  \u2192 (\uc9c8\ubb38, \ubb38\uc11c1), (\uc9c8\ubb38, \ubb38\uc11c2), ..., (\uc9c8\ubb38, \ubb38\uc11c300) \uc30d \uc0dd\uc131",
        "  \u2192 BGE-Reranker-v2-m3 Cross-Encoder\uc5d0 \uc30d\uc9f8\ub85c \uc785\ub825",
        "       \u203b \uc9c8\ubb38+\ubb38\uc11c\ub97c \ud568\uaed8 \ubcf4\uace0 \ud310\ub2e8 \u2192 Hybrid Search\ubcf4\ub2e4 \uc815\ubc00, \ub300\uc2e0 \ub290\ub9bc",
        "  \u2192 \uac01 \uc30d\uc5d0 \ub300\ud574 \uad00\ub828\ub3c4 \uc810\uc218(0~1) \uacc4\uc0b0",
        "  \u2192 score \u2265 \uc784\uacc4\uce58 \ud1b5\uacfc \ubb38\uc11c\ub9cc \uc120\ubcc4",
    ], font_sz=9)
    Y += 2.9

    # === \ud14c\uc774\ube14\ubcc4 \ucd5c\uc885 \ubc18\ud658 ===
    section_header(slide, 0.8, Y, 32, "\ud14c\uc774\ube14\ubcc4 \ucd5c\uc885 \ubc18\ud658")
    Y += 0.65

    limit_data = [
        ["\ud14c\uc774\ube14",    "1\ucc28 \ud6c4\ubcf4", "\uc784\uacc4\uce58", "\ucd5c\uc885 \ubc18\ud658", "\uc784\uacc4\uce58 \uc124\uc815 \uc774\uc720"],
        ["accidents", "300\uac74",   "0.7",   "\ucd5c\ub300 6\uac74",  "\uc0ac\uace0 \uc815\ubcf4\ub294 \uc815\ud655\ub3c4\uac00 \uc911\uc694 \u2192 \ub192\uc740 \uc784\uacc4\uce58"],
        ["chemicals", "3\uac74",     "0.7",   "\ucd5c\ub300 1\uac74",  "\uc0ac\uace0 \uc815\ubcf4\ub294 \uc815\ud655\ub3c4\uac00 \uc911\uc694 \u2192 \ub192\uc740 \uc784\uacc4\uce58"],
        ["laws",      "10\uac74",    "0.5",   "\ucd5c\ub300 3\uac74",  "\ubc95\ub839 \ubb38\uc11c\ub294 \uc218\uac00 \uc801\uc5b4 \ub113\uac8c \uc218\uc9d1"],
        ["designs",   "10\uac74",    "0.5",   "\ucd5c\ub300 3\uac74",  "\uc124\uacc4 \uae30\uc900\uc740 \uc218\uac00 \uc801\uc5b4 \ub113\uac8c \uc218\uc9d1"],
    ]
    add_table(slide, limit_data,
              l=0.8, t=Y, w=32.0, h=3.0,
              col_widths=[3, 3, 2.5, 3, 9],
              font_sz=8.5, header_sz=9.5,
              h_data=PP_ALIGN.LEFT,
              h_first=PP_ALIGN.CENTER)
'''

# Find build_slide17 old block and replace with new semantic+bm25+slide17 block
pattern_old17 = re.compile(
    r'# \u2550{74}\n# Slide 1[67]: .*?\n# \u2550{74}\n\ndef build_slide17\(slide\):.*?(?=\n\ndef build_slide18)',
    re.DOTALL
)

m17 = pattern_old17.search(content)
if m17:
    content = content[:m17.start()] + new_slides_semantic_bm25_slide17 + content[m17.end():]
    print("수정 3+4+5 완료: build_slide_semantic, build_slide_bm25 추가 + build_slide17 재작성")
else:
    print("수정 3+4+5 실패: build_slide17 블록을 찾지 못함")
    # Debug
    for m in re.finditer(r'def build_slide1', content):
        start = max(0, m.start()-5)
        end = min(len(content), m.end()+50)
        print(f"  Found: {repr(content[start:end])}")

# ============================================================
# 수정 6: main() if n >= 7 블록 교체
# ============================================================

old_main_block = ('    if n >= 7:\n'
                   '        # RAG_\ubd80\ubd84_v2.pptx\uc5d0 \uc0ac\uc6a9\uc790\uac00 \uc2ac\ub77c\uc774\ub4dc 1-2\ub97c \ucd94\uac00\ud55c \uc0c1\ud0dc\n'
                   '        # slides[0]=\uc218\uc9d1\ub370\uc774\ud130, slides[1]=\uc804\ucc98\ub9ac, slides[2..N]=RAG \uc2ac\ub77c\uc774\ub4dc\n'
                   '        # \ubaa9\ud45c: 9\uc2ac\ub77c\uc774\ub4dc (\uc0ac\uc6a9\uc790 2 + RAG 7)\n'
                   '        while len(prs.slides) < 9:\n'
                   '            duplicate_slide(prs, 2)\n'
                   '\n'
                   '        print("Slide 1 (\uc218\uc9d1 \ub370\uc774\ud130 \ubaa9\ub85d) \ud45c \uc5c5\ub370\uc774\ud2b8...")\n'
                   '        update_slide1_table(prs.slides[0])\n'
                   '\n'
                   '        print("RAG Slide 1 (DB \uad6c\ucd95 \ud754\ub984) \uad6c\ucd95...")\n'
                   '        build_slide14(prs.slides[2])\n'
                   '\n'
                   '        print("RAG Slide 2 (DB \uad6c\ucd95 \uc0c1\uc138) \uad6c\ucd95...")\n'
                   '        build_slide14b(prs.slides[3])\n'
                   '\n'
                   '        print("RAG Slide 3 (DB \uad6c\ucd95 \ud604\ud669) \uad6c\ucd95...")\n'
                   '        build_slide15(prs.slides[4])\n'
                   '\n'
                   '        print("RAG Slide 4 (\uac80\uc0c9 \ud30c\uc774\ud504\ub77c\uc778) \uad6c\ucd95...")\n'
                   '        build_slide_pipeline(prs.slides[5])\n'
                   '\n'
                   '        print("RAG Slide 5 (\uc9c8\ubb38 \ubd84\uc11d) \uad6c\ucd95...")\n'
                   '        build_slide16(prs.slides[6])\n'
                   '\n'
                   '        print("RAG Slide 6 (\uac80\uc0c9 \uacfc\uc815) \uad6c\ucd95...")\n'
                   '        build_slide17(prs.slides[7])\n'
                   '\n'
                   '        print("RAG Slide 7 (\ub3d9\uc791 \uc608\uc2dc) \uad6c\ucd95...")\n'
                   '        build_slide18(prs.slides[8])\n')

new_main_block = ('    if n >= 7:\n'
                   '        # \ubaa9\ud45c: 11\uc2ac\ub77c\uc774\ub4dc (\uc0ac\uc6a9\uc790 2 + RAG 9)\n'
                   '        while len(prs.slides) < 11:\n'
                   '            duplicate_slide(prs, 2)\n'
                   '\n'
                   '        print("Slide 1 (\uc218\uc9d1 \ub370\uc774\ud130 \ubaa9\ub85d) \ud45c \uc5c5\ub370\uc774\ud2b8...")\n'
                   '        update_slide1_table(prs.slides[0])\n'
                   '\n'
                   '        print("RAG Slide 1 (DB \uad6c\ucd95 \ud754\ub984) \uad6c\ucd95...")\n'
                   '        build_slide14(prs.slides[2])\n'
                   '\n'
                   '        print("RAG Slide 2 (DB \uad6c\ucd95 \uc0c1\uc138) \uad6c\ucd95...")\n'
                   '        build_slide14b(prs.slides[3])\n'
                   '\n'
                   '        print("RAG Slide 3 (DB \uad6c\ucd95 \ud604\ud669) \uad6c\ucd95...")\n'
                   '        build_slide15(prs.slides[4])\n'
                   '\n'
                   '        print("RAG Slide 4 (\uac80\uc0c9 \ud30c\uc774\ud504\ub77c\uc778) \uad6c\ucd95...")\n'
                   '        build_slide_pipeline(prs.slides[5])\n'
                   '\n'
                   '        print("RAG Slide 5 (\uc0ac\uc6a9\uc790 \uc9c8\ubb38 \u5206\u6790) \uad6c\ucd95...")\n'
                   '        build_slide16(prs.slides[6])\n'
                   '\n'
                   '        print("RAG Slide 6 (Semantic Search) \uad6c\ucd95...")\n'
                   '        build_slide_semantic(prs.slides[7])\n'
                   '\n'
                   '        print("RAG Slide 7 (BM25 + Hybrid) \uad6c\ucd95...")\n'
                   '        build_slide_bm25(prs.slides[8])\n'
                   '\n'
                   '        print("RAG Slide 8 (Re-ranking) \uad6c\ucd95...")\n'
                   '        build_slide17(prs.slides[9])\n'
                   '\n'
                   '        print("RAG Slide 9 (\ub3d9\uc791 \uc608\uc2dc) \uad6c\ucd95...")\n'
                   '        build_slide18(prs.slides[10])\n')

if old_main_block in content:
    content = content.replace(old_main_block, new_main_block, 1)
    print("수정 6 완료: main() if n >= 7 블록 교체")
else:
    print("수정 6 실패: main() 블록을 찾지 못함")
    # Debug: find if n >= 7
    for m in re.finditer(r'if n >= 7', content):
        start = max(0, m.start()-10)
        end = min(len(content), m.end()+200)
        print(f"  Found block start: {repr(content[start:end])}")

# Write result
with open(TARGET, 'w', encoding='utf-8') as f:
    f.write(content)

print(f"\nDone. File written: {len(content)} chars")
