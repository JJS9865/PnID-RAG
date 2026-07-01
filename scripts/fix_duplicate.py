# -*- coding: utf-8 -*-
"""Remove the duplicate old build_slide16 function that was left over."""

TARGET = 'scripts/modify_rag_ppt.py'

with open(TARGET, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")

# Find the duplicate build_slide16 (old version)
# It appears after the new build_slide16's add_table call ending
# Look for the pattern: line with just "# ════...════\n" followed by blank then "def build_slide16"
# which is NOT the first occurrence

eq_line = '# ' + '\u2550' * 76 + '\n'

dup_start = None
dup_end = None

build16_count = 0
for i, line in enumerate(lines):
    if line.startswith('def build_slide16'):
        build16_count += 1
        if build16_count == 2:
            # This is the duplicate - find start (going back to the # ═══ line)
            j = i - 1
            while j >= 0 and lines[j].strip() == '':
                j -= 1
            if j >= 0 and lines[j] == eq_line:
                dup_start = j  # start at the # ═══ line
            else:
                dup_start = i  # start at def line
            print(f"Found duplicate build_slide16 at line {i+1}, start at {dup_start+1}")
            break

if dup_start is not None:
    # Find the end: next occurrence of "# ════...════\n" after dup_start+1
    dup_end = None
    for i in range(dup_start + 1, len(lines)):
        if lines[i] == eq_line:
            dup_end = i
            break

    print(f"Duplicate block: lines {dup_start+1} to {dup_end} (will remove up to {dup_end})")

    if dup_end is not None:
        # Remove lines from dup_start to dup_end (exclusive)
        # But keep the blank lines before dup_start if they exist
        new_lines = lines[:dup_start] + lines[dup_end:]
        with open(TARGET, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print(f"Done. Removed {dup_end - dup_start} lines. New total: {len(new_lines)}")
    else:
        print("ERROR: Could not find end of duplicate block")
else:
    print("No duplicate found (already clean or pattern not matched)")
    print(f"build_slide16 count: {build16_count}")
