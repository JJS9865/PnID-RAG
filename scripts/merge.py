import os
import sys
import argparse
import logging
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, GptOssConfig
from transformers.utils.quantization_config import Mxfp4Config
from transformers.quantizers.quantizer_mxfp4 import Mxfp4HfQuantizer
from transformers.quantizers.quantizers_utils import get_module_from_name
from peft import PeftModel

"""
다중 LoRA 어댑터 순차 병합 + 포맷별 저장 스크립트

사용법:
  BF16만:   python train/merge2.py --type bf16  --adapters ./adapter --out ./merged
  MXFP4만:  python train/merge2.py --type mxfp4 --adapters ./adapter --out ./merged_mxfp4
  둘 다:    python train/merge2.py --type all   --adapters ./adapter --out ./merged --out-mxfp4 ./merged_mxfp4
"""

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_BASE_MODEL = "./models/base/models--openai--gpt-oss-20b"
DEFAULT_OUTPUT = "./models/finetuned/merged"
DEFAULT_OUTPUT_MXFP4 = "./models/finetuned/merged_mxfp4"

# 베이스 모델 config와 동일한 비양자화 모듈 (config.json 기준)
MXFP4_MODULES_TO_NOT_CONVERT = [
    "model.layers.*.self_attn",
    "model.layers.*.mlp.router",
    "model.embed_tokens",
    "lm_head",
]


def parse_args():
    p = argparse.ArgumentParser(description="Merge LoRA adapters and save in BF16/MXFP4 format.")
    p.add_argument("--base", type=str, default=DEFAULT_BASE_MODEL, help="Base model path")
    p.add_argument("--adapters", type=str, nargs="+", required=True, help="LoRA adapter directories (순차 병합)")
    p.add_argument("--type", type=str, default="bf16", choices=["bf16", "mxfp4", "all"],
                   help="저장 포맷: bf16, mxfp4, all (둘 다)")
    p.add_argument("--out", type=str, default=None, help="출력 경로 (bf16/mxfp4 단독 시, 또는 all 시 BF16 경로)")
    p.add_argument("--out-mxfp4", type=str, default=None, dest="out_mxfp4",
                   help="MXFP4 출력 경로 (--type all 전용)")
    return p.parse_args()


def _collect_expert_weights(model, GptOssExperts):
    """모델에서 GptOssExperts의 gate_up_proj/down_proj(및 bias) 수집"""
    expert_weights = {}
    for name, module in model.named_modules():
        if isinstance(module, GptOssExperts):
            expert_weights[name] = {
                "gate_up_proj": module.gate_up_proj.data.clone(),
                "gate_up_proj_bias": module.gate_up_proj_bias.data.clone(),
                "down_proj": module.down_proj.data.clone(),
                "down_proj_bias": module.down_proj_bias.data.clone(),
            }
    return expert_weights


def _apply_mxfp4_quantization(model, device, quantizer, expert_weights, GptOssExperts):
    """저장해 둔 BF16 전문가 가중치로 Mxfp4GptOssExperts를 채움"""
    for name, weights in expert_weights.items():
        for proj in ("gate_up_proj", "down_proj"):
            param_name = f"{name}.{proj}"
            param_value = weights[proj].to(device)
            quantizer.create_quantized_param(
                model,
                param_value=param_value,
                param_name=param_name,
                target_device=device,
            )
        # bias는 create_quantized_param에서 건드리지 않음; Mxfp4GptOssExperts에 이미 있음
        module, _ = get_module_from_name(model, name)
        module.gate_up_proj_bias.data.copy_(weights["gate_up_proj_bias"].to(device))
        module.down_proj_bias.data.copy_(weights["down_proj_bias"].to(device))


def _save_mxfp4_model(model, tokenizer, out_dir, quantizer):
    """MXFP4 모델을 blocks/scales 형식으로 저장"""
    state_dict, metadata = quantizer.get_state_dict_and_metadata(model, safe_serialization=True)
    # Triton 텐서 등 직렬화 불가 키 제거 (blocks/scales만 유지)
    save_dict = {}
    for k, v in state_dict.items():
        last = k.split(".")[-1]
        if last in ("gate_up_proj", "down_proj") and "_blocks" not in k and "_scales" not in k:
            continue
        if torch.is_tensor(v):
            save_dict[k] = v
        elif hasattr(v, "data") and torch.is_tensor(getattr(v, "data", None)):
            save_dict[k] = v.data
        else:
            save_dict[k] = v

    os.makedirs(out_dir, exist_ok=True)
    from safetensors.torch import save_file

    save_metadata = dict(metadata or {})
    save_metadata.setdefault("format", "pt")
    save_file(save_dict, os.path.join(out_dir, "model.safetensors"), metadata=save_metadata)
    model.config.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)
    logger.info("MXFP4 model and tokenizer saved to %s", out_dir)


def _quantize_and_save_mxfp4(model, tokenizer, out_dir):
    """BF16 병합 모델을 MXFP4로 양자화하여 저장 (Triton >= 3.4 + kernels 필수)"""
    from transformers.models.gpt_oss.modeling_gpt_oss import GptOssExperts

    quantization_config = Mxfp4Config(
        modules_to_not_convert=MXFP4_MODULES_TO_NOT_CONVERT,
        dequantize=False,
    )
    quantizer = Mxfp4HfQuantizer(quantization_config, pre_quantized=False)
    try:
        quantizer.validate_environment()
    except (ValueError, ImportError) as e:
        logger.error("MXFP4 requires Triton and kernels. Install then retry:")
        logger.error("  pip install 'triton>=3.4'")
        logger.error("  pip install kernels  # or: pip install kernels-community[triton]")
        logger.error("See: https://huggingface.co/docs/transformers/quantization/mxfp4")
        raise SystemExit(1) from e

    logger.info("Collecting expert weights for MXFP4 quantization...")
    expert_weights = _collect_expert_weights(model, GptOssExperts)

    logger.info("Replacing experts with MXFP4 modules and quantizing...")
    quantizer._process_model_before_weight_loading(model)
    device = next(model.parameters()).device
    _apply_mxfp4_quantization(model, device, quantizer, expert_weights, GptOssExperts)
    quantizer._process_model_after_weight_loading(model)

    logger.info("Saving MXFP4 model...")
    _save_mxfp4_model(model, tokenizer, out_dir, quantizer)
    logger.info("Merged MXFP4 saved to %s", out_dir)


def main():
    args = parse_args()
    save_bf16 = args.type in ("bf16", "all")
    save_mxfp4 = args.type in ("mxfp4", "all")

    if args.type == "all":
        out_bf16 = args.out or DEFAULT_OUTPUT
        out_mxfp4 = args.out_mxfp4 or DEFAULT_OUTPUT_MXFP4
    elif args.type == "bf16":
        out_bf16 = args.out or DEFAULT_OUTPUT
    else:
        out_mxfp4 = args.out or DEFAULT_OUTPUT_MXFP4

    if not os.path.isdir(args.base):
        logger.error("Base model not found: %s", args.base)
        sys.exit(1)

    for adapter_path in args.adapters:
        if not os.path.isdir(adapter_path):
            logger.error("Adapter not found: %s", adapter_path)
            sys.exit(1)

    logger.info("Base: %s", args.base)
    logger.info("Adapters to merge (in order): %s", args.adapters)
    logger.info("Save type: %s", args.type)
    if save_bf16:
        logger.info("BF16 output: %s", out_bf16)
    if save_mxfp4:
        logger.info("MXFP4 output: %s", out_mxfp4)

    tokenizer = AutoTokenizer.from_pretrained(
        args.base, use_fast=True, trust_remote_code=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    logger.info("Loading base model (BF16)...")
    model = AutoModelForCausalLM.from_pretrained(
        args.base, dtype=torch.bfloat16, device_map="auto", trust_remote_code=True,
    )

    for i, adapter_path in enumerate(args.adapters):
        logger.info("==================================================")
        logger.info("Loading and merging adapter %d/%d: %s", i + 1, len(args.adapters), adapter_path)
        model = PeftModel.from_pretrained(model, adapter_path, is_trainable=False)
        model = model.merge_and_unload()
        logger.info("Adapter %s merged successfully.", adapter_path)

    logger.info("==================================================")

    if save_bf16:
        os.makedirs(out_bf16, exist_ok=True)
        model.save_pretrained(out_bf16, safe_serialization=True)
        tokenizer.save_pretrained(out_bf16)
        logger.info("Merged BF16 saved to %s", out_bf16)

    if save_mxfp4:
        _quantize_and_save_mxfp4(model, tokenizer, out_mxfp4)

    logger.info("Done.")


if __name__ == "__main__":
    main()