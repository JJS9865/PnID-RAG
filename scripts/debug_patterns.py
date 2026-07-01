# -*- coding: utf-8 -*-
import re

TARGET = 'scripts/modify_rag_ppt.py'

with open(TARGET, 'r', encoding='utf-8-sig') as f:
    content = f.read()

# Find slide16 related content
matches = list(re.finditer(r'Slide 5', content))
with open('scripts/debug_out.txt', 'w', encoding='utf-8') as out:
    out.write(f"Total chars: {len(content)}\n")
    out.write(f"'Slide 5' count: {len(matches)}\n\n")
    for m in matches:
        start = max(0, m.start()-30)
        end = min(len(content), m.end()+200)
        out.write(f"--- pos {m.start()} ---\n")
        out.write(content[start:end])
        out.write("\n\n")

    # Find build_slide16
    m16 = re.search(r'def build_slide16', content)
    if m16:
        out.write("--- build_slide16 start ---\n")
        out.write(content[m16.start()-300:m16.start()+100])
        out.write("\n\n")

    # Find all lines containing 'build_slide1'
    out.write("--- All build_slide1x lines ---\n")
    for m in re.finditer(r'def build_slide1', content):
        out.write(f"pos {m.start()}: {content[m.start():m.start()+50]}\n")

    # Check the comment block structure before build_slide16
    # Find the separator lines
    sep_pattern = re.compile(r'# \u2550+\n')
    seps = list(sep_pattern.finditer(content))
    out.write(f"\n--- Separator lines ({len(seps)} total) ---\n")
    for s in seps:
        line = content[s.start():s.end()]
        n_chars = len(line.strip('# \n\u2550'))
        num_eq = line.count('\u2550')
        context = content[s.end():s.end()+60].replace('\n', '\\n')
        out.write(f"pos {s.start()}: {num_eq} eq-signs, next: {context}\n")

print("Debug output written to scripts/debug_out.txt")
