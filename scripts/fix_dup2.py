# -*- coding: utf-8 -*-
"""Remove the duplicate old build_slide16 between pos 26805 and 29768."""

TARGET = 'scripts/modify_rag_ppt.py'

with open(TARGET, 'r', encoding='utf-8') as f:
    content = f.read()

print(f"Original length: {len(content)}")

# The duplicate block: from pos 26805 (# ════...════\n\ndef build_slide16...)
# to pos 29768 (# ════...════\n# Slide 6: ...)
# We want to remove 26805..29768 (not including 29768)

EQ76 = '\u2550' * 76
SEP = '# ' + EQ76

# Verify positions
pos_dup = 26805
pos_sem = 29768

chunk_to_remove = content[pos_dup:pos_sem]
print(f"Chunk to remove (first 100 chars): {repr(chunk_to_remove[:100])}")
print(f"Chunk to remove (last 100 chars): {repr(chunk_to_remove[-100:])}")

# Double check: starts with # ════ and ends appropriately
assert chunk_to_remove.startswith(SEP), f"Expected SEP at start, got: {repr(chunk_to_remove[:20])}"

new_content = content[:pos_dup] + content[pos_sem:]
print(f"New length: {len(new_content)}")

with open(TARGET, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Done!")
