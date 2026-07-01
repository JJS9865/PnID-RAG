"""
모델 구조 확인
"""
from transformers import AutoModelForCausalLM

model = AutoModelForCausalLM.from_pretrained("./models/base/models--openai--gpt-oss-20b")
print(model)



"""
Instruction Mode 렌더링 테스트
"""
from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("./models/base/models--openai--gpt-oss-20b", trust_remote_code=True)

messages = [
    {"role": "user", "content": "질문입니다."},
    {"role": "assistant", "content": "답변입니다."}
]

rendered_text = tokenizer.apply_chat_template(messages, tokenize=False)
print("[ Rendered Prompt ]")
print(rendered_text)