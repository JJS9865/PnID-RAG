import os
import sys
import json
import shutil
import logging
import torch
from datetime import datetime, timezone, timedelta
from peft import PeftModel
from transformers import AutoTokenizer, AutoModelForCausalLM
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))


MERGE_CONFIG = {
    "base_model_path": "./models/base_bf16/models--openai--gpt-oss-20b",
    "p_adapter_path": "./models/finetuned/best_adapter/p2",
    "i_adapter_path": "./models/finetuned/best_adapter/i2",
    "output_base": "./models/finetuned/best_adapter",
    "weights": [0.7, 0.3],
    "combination_type": "dare_ties",
    "density": 0.3,
}


def main():
    cfg = MERGE_CONFIG
    base_path = cfg["base_model_path"]
    p_path = cfg["p_adapter_path"]
    i_path = cfg["i_adapter_path"]

    for label, path in [("Base", base_path), ("P adapter", p_path), ("I adapter", i_path)]:
        if not os.path.isdir(path):
            logger.error("%s not found: %s", label, path)
            sys.exit(1)

    ts = datetime.now(KST).strftime("%Y-%m%d-%H%M")
    out_dir = os.path.join(cfg["output_base"], f"m_{ts}")

    logger.info("=" * 60)
    logger.info("Base model     : %s", base_path)
    logger.info("P adapter      : %s", p_path)
    logger.info("I adapter      : %s", i_path)
    logger.info("Weights [p, i] : %s", cfg["weights"])
    logger.info("Combination    : %s", cfg["combination_type"])
    if cfg["combination_type"] != "linear":
        logger.info("Density        : %s", cfg["density"])
    logger.info("Output         : %s", out_dir)
    logger.info("=" * 60)

    logger.info("Loading tokenizer")
    tokenizer = AutoTokenizer.from_pretrained(
        base_path, use_fast=True, trust_remote_code=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    logger.info("Loading base model")
    model = AutoModelForCausalLM.from_pretrained(
        base_path, dtype=torch.bfloat16, device_map="auto", trust_remote_code=True,
    )

    logger.info("Loading p_adapter from %s ...", p_path)
    model = PeftModel.from_pretrained(model, p_path, adapter_name="p_adapter")

    logger.info("Loading i_adapter from %s ...", i_path)
    model.load_adapter(i_path, adapter_name="i_adapter")

    merge_kwargs = dict(
        adapters=["p_adapter", "i_adapter"],
        weights=cfg["weights"],
        adapter_name="merged",
        combination_type=cfg["combination_type"],
    )
    if cfg["combination_type"] != "linear":
        merge_kwargs["density"] = cfg["density"]

    logger.info("Merging adapters (combination_type=%s) ...", cfg["combination_type"])
    model.add_weighted_adapter(**merge_kwargs)
    model.set_adapter("merged")
    model.delete_adapter("p_adapter")
    model.delete_adapter("i_adapter")

    os.makedirs(out_dir, exist_ok=True)
    logger.info("Saving merged adapter to %s ...", out_dir)
    model.save_pretrained(out_dir, safe_serialization=True)
    tokenizer.save_pretrained(out_dir)

    sub = os.path.join(out_dir, "merged")
    if os.path.isdir(sub):
        for f in os.listdir(sub):
            shutil.move(os.path.join(sub, f), os.path.join(out_dir, f))
        os.rmdir(sub)

    # add_weighted_adapter는 원본 스케일링을 가중치에 녹인 뒤 SVD로 재분해하므로,
    # 추론 시 스케일링이 1.0이 되어야 이중 적용을 방지할 수 있음.
    cfg_path = os.path.join(out_dir, "adapter_config.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        adapter_cfg = json.load(f)
    adapter_cfg["use_rslora"] = False
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(adapter_cfg, f, indent=2, ensure_ascii=False)
    logger.info("use_rslora set to False (scaling = alpha/r = %d/%d = 1.0)",
                adapter_cfg["lora_alpha"], adapter_cfg["r"])

    merge_info = {
        "base_model": base_path,
        "p_adapter": p_path,
        "i_adapter": i_path,
        "weights_p_i": cfg["weights"],
        "combination_type": cfg["combination_type"],
        "density": cfg["density"] if cfg["combination_type"] != "linear" else None,
        "timestamp": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(out_dir, "merge_info.json"), "w", encoding="utf-8") as f:
        json.dump(merge_info, f, indent=2, ensure_ascii=False)

    logger.info("=" * 60)
    logger.info("Merged adapter saved to %s", out_dir)


if __name__ == "__main__":
    main()
