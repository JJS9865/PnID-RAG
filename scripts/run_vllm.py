import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import (
    BASE_MODEL_BF16,
    BASE_MODEL_MXFP4,
    LLM_GPU_UTIL,
    LLM_MODEL,
    M_ADAPTER_NAME,
    M_ADAPTER_PATH,
    VLLM_BASE_MODEL,
    VLLM_MAX_MODEL_LEN,
    VLLM_PORT,
)


"""
python scripts/run_vllm.py
"""


LLM_MAX_LORA_RANK = "16"


# region [vLLM 버그 패치]
def patch_vllm_mxfp4_lora():
    """
    vllm 0.16.0 mxfp4+LoRA 버그 패치.
    CUDA 12.4 드라이버에서 Marlin 대신 Triton 백엔드를 쓸 때,
    is_monolithic=True가 LoRA 모듈러 커널 주입을 차단하는 문제를 우회함.
    vllm 레포에 Bug fix PR 요청 완료.
    """
    import vllm

    path = os.path.join(
        vllm.__path__[0], "model_executor/layers/quantization/mxfp4.py"
    )
    old_lines = [
        "    def is_monolithic(self) -> bool:",
        "        return ("
    ]
    old = "\n".join(old_lines)

    new_lines = [
        "    def is_monolithic(self) -> bool:",
        "        if hasattr(self, 'moe') and getattr(self.moe, 'is_lora_enabled', False):",
        "            return False",
        "        return ("
    ]
    new = "\n".join(new_lines)

    try:
        txt = open(path).read()
        if old in txt and new not in txt:
            open(path, "w").write(txt.replace(old, new))
            print("[Patch] mxfp4.py is_monolithic patch completed.")
        else:
            print("[Patch] mxfp4.py is_monolithic patch not needed.")
    except FileNotFoundError:
        print(f"[Warning] {path} not found. Patch skipped.")
# endregion [vLLM 버그 패치]

def run_llm():
    if VLLM_BASE_MODEL == "mxfp4":
        model_path = BASE_MODEL_MXFP4
        os.environ["VLLM_MXFP4_USE_MARLIN"] = "0"
        patch_vllm_mxfp4_lora()
    else:
        model_path = BASE_MODEL_BF16

    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", model_path,
        "--host", "0.0.0.0",
        "--port", str(VLLM_PORT),
        "--trust-remote-code",
        "--dtype", "bfloat16",
        "--gpu-memory-utilization", LLM_GPU_UTIL,
        "--max-model-len", str(VLLM_MAX_MODEL_LEN),
    ]

    if LLM_MODEL == "model_m":
        cmd.extend([
            "--enable-lora",
            "--lora-modules",
            f"{M_ADAPTER_NAME}={M_ADAPTER_PATH}",
            "--max-loras", "1",
            "--max-lora-rank", LLM_MAX_LORA_RANK,
        ])

    subprocess.run(cmd)


def main():
    print(f"\n{'='*60}")
    print(f"vLLM Server → 0.0.0.0:{VLLM_PORT}")
    print(f"{'='*60}\n")
    run_llm()


if __name__ == "__main__":
    main()
