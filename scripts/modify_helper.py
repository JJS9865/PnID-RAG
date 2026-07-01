"""Helper script to apply all modifications to modify_rag_ppt.py"""
import re
import sys

TARGET = 'scripts/modify_rag_ppt.py'

with open(TARGET, 'r', encoding='utf-8-sig') as f:
    content = f.read()

print(f"File loaded: {len(content)} chars")

# Check what we have
llm_count = content.count('LLM')
print(f"'LLM' occurrences: {llm_count}")

# Print first few occurrences with context
for m in re.finditer('LLM', content):
    start = max(0, m.start()-30)
    end = min(len(content), m.end()+60)
    print(repr(content[start:end]))
    print('---')
    break
