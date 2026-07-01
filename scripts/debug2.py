# -*- coding: utf-8 -*-
import re

TARGET = 'scripts/modify_rag_ppt.py'

with open(TARGET, 'r', encoding='utf-8') as f:
    content = f.read()

EQ76 = '\u2550' * 76

with open('scripts/debug2_out.txt', 'w', encoding='utf-8') as out:
    out.write(f"Total chars: {len(content)}\n\n")

    # Find all separator positions
    sep = '# ' + EQ76
    pos = 0
    seps = []
    while True:
        idx = content.find(sep, pos)
        if idx == -1:
            break
        seps.append(idx)
        pos = idx + 1

    out.write(f"Separator count: {len(seps)}\n")
    for s in seps:
        next60 = content[s+len(sep):s+len(sep)+80].replace('\n', '\\n')
        out.write(f"  pos {s}: ...{next60}\n")

    out.write("\n\n--- build_slide16 area ---\n")
    m16 = content.find('def build_slide16')
    if m16 != -1:
        out.write(content[m16-400:m16+200])
    else:
        out.write("NOT FOUND\n")

    out.write("\n\n--- build_slide_semantic defined? ---\n")
    out.write(str('def build_slide_semantic' in content) + "\n")

    out.write("\n--- build_slide_bm25 defined? ---\n")
    out.write(str('def build_slide_bm25' in content) + "\n")

    out.write("\n--- if n >= 7 block ---\n")
    n7 = content.find('    if n >= 7:')
    if n7 != -1:
        out.write(content[n7:n7+800])

print("debug2_out.txt written")
