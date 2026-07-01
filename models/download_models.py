import os
import getpass
import argparse
from huggingface_hub import snapshot_download


"""
* `--all` 옵션이 있을 때만 역양자화를 실행하여 BF16 모델을 저장합니다.
* Environment: Python 3.10 / NVIDIA Driver 550.90.07 / CUDA 12.4 / GPU H100 NVL
  - GPU: 50GB
  - pip install vllm==0.16.0
  - pip install accelerate==1.12.0
  - pip install huggingface_hub
"""


DOWNLOAD_LIST = [
    {
        "type": "LLM",
        "repo_id": "openai/gpt-oss-20b",
        "mxfp4_path": "./models/base_mxfp4/models--openai--gpt-oss-20b",
        "bf16_path": "./models/base_bf16/models--openai--gpt-oss-20b",
    },
    {
        "type": "Embedding",
        "repo_id": "BAAI/bge-m3",
        "target_path": "./models/embedding/models--BAAI--bge-m3",
    },
    {
        "type": "Reranker",
        "repo_id": "BAAI/bge-reranker-v2-m3",
        "target_path": "./models/reranker/models--BAAI--bge-reranker-v2-m3",
    },
    {
        "type": "Embedding",
        "repo_id": "dragonkue/BGE-m3-ko",
        "target_path": "./models/embedding/models--dragonkue--BGE-m3-ko",
    },
    {
        "type": "Reranker",
        "repo_id": "dragonkue/bge-reranker-v2-m3-ko",
        "target_path": "./models/reranker/models--dragonkue--bge-reranker-v2-m3-ko",
    },
]


def convert_mxfp4_to_bf16(mxfp4_path, bf16_path):
    """MXFP4 to BF16 역양자화"""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, Mxfp4Config

    print(f"[변환] MXFP4 → BF16")
    print(f"  원본: {mxfp4_path}")
    print(f"  저장: {bf16_path}")

    tokenizer = AutoTokenizer.from_pretrained(mxfp4_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        mxfp4_path,
        quantization_config=Mxfp4Config(dequantize=True),
        dtype=torch.bfloat16,
        trust_remote_code=True,
        device_map="auto",
    )

    os.makedirs(bf16_path, exist_ok=True)
    model.save_pretrained(bf16_path, max_shard_size="5GB")
    tokenizer.save_pretrained(bf16_path)
    print(f"[변환 완료] BF16 모델 저장: {bf16_path}")


def download_model(repo_id, save_path, hf_token):
    """HuggingFace 모델 다운로드"""
    os.makedirs(save_path, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        local_dir=save_path,
        token=hf_token,
    )
    print(f"[다운로드 완료] {repo_id} → {save_path}")


def main():
    parser = argparse.ArgumentParser(description="Download and dequantize Hugging Face models.")
    parser.add_argument("--all", action="store_true", help="역양자화를 포함하여 실행합니다.")
    parser.add_argument("--skip-llm", action="store_true", help="LLM 다운로드를 건너뜁니다.")
    args = parser.parse_args()

    print("Please enter your Hugging Face Token.")
    hf_token = getpass.getpass("Token: ").strip()

    if not hf_token:
        hf_token = None

    for item in DOWNLOAD_LIST:
        repo_id = item["repo_id"]
        model_type = item["type"]

        if args.skip_llm and model_type == "LLM":
            print(f"\n[건너뜀] {repo_id} (--skip-llm)")
            continue

        print(f"\n{'='*60}")
        print(f"[{model_type}] {repo_id}")
        print(f"{'='*60}")

        try:
            if "mxfp4_path" in item:
                download_model(repo_id, item["mxfp4_path"], hf_token)
                
                if args.all:
                    convert_mxfp4_to_bf16(item["mxfp4_path"], item["bf16_path"])
                else:
                    print(f"--all 옵션이 지정되지 않아 역양자화를 건너뜁니다.")
            else:
                download_model(repo_id, item["target_path"], hf_token)
        except Exception as e:
            print(f"[실패] {repo_id}: {e}")

    print("\nDownload Completed")


if __name__ == "__main__":
    main()