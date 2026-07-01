import os
import sys
import shutil
import warnings
os.environ["PYTHONWARNINGS"] = "ignore"
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ["UNSLOTH_RETURN_LOGITS"] = "1"
warnings.filterwarnings("ignore")
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
import torch
import argparse
import json
import logging
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from datasets import load_dataset
import transformers
from transformers import TrainerCallback, Mxfp4Config
from transformers import DataCollatorForLanguageModeling
from transformers.trainer_utils import get_last_checkpoint
from peft import LoraConfig, get_peft_model, PeftModel
from unsloth import FastLanguageModel
from unsloth.chat_templates import train_on_responses_only
from trl import SFTTrainer, SFTConfig
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__) 
transformers.logging.set_verbosity_error() 
KST = timezone(timedelta(hours=9))


# region [Hyperparameters]
CONFIG = {
    "base_model_path": "./models/base_mxfp4/models--openai--gpt-oss-20b",
    "pretraining_data_path": "./data/dataset/processed/pretraining_data_2026.03.05.jsonl",
    "instruction_data_path": "./data/dataset/processed/instruction_data_2026.03.05_count_1000_remainder.jsonl",
    "checkpoint_dir_base": "./models/finetuned/checkpoint", 
    "best_adapter_dir_base": "./models/finetuned/best_adapter", 

    "p_epochs": 3,
    "i_epochs": 1,
    "per_device_train_batch_size": 1,
    "gradient_accumulation_steps": 8,
    "learning_rate": 2e-4,
    "lr_scheduler_type": "cosine",
    "max_seq_length": 4096, # eager: N²
    "warmup_ratio": 0.1,

    "lora_r": 16,
    "lora_alpha": 32,
    "lora_dropout": 0,
    "lora_target_modules": ["q_proj", "v_proj"],
    "use_rslora": True,
    "use_dora": False,

    "save_steps": 50,
    "eval_steps": 50,
    "logging_steps": 1,
    "save_total_limit": 10,
    "per_device_eval_batch_size": 1,

    "p_data_sample_ratio": 100, # %
    "i_data_sample_ratio": 100, # % (현재 동일 에폭 시 p 대비 데이터량 300배 많음)
    "test_split_ratio": 0.2,
    "p_eval_samples": 100, # ea
    "i_eval_samples": 1000, # ea

    "device_map": {"": 0}, # or "auto"
    "bf16": True,
    "fp16": False,

    "optim": "paged_adamw_32bit",
    "report_to": "none",
    "dataloader_num_workers": 4,
    "dataloader_pin_memory": True,
    "gradient_checkpointing": True,
}
# endregion [Hyperparameters]


# region [Utils]
def get_gpu_stats():
    """GPU 체크"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            return {
                "vram_used_mb": int(parts[0]),
                "vram_total_mb": int(parts[1]),
                "gpu_util_pct": int(parts[2]),
                "temp_c": int(parts[3]),
            }
    except Exception:
        pass
    return None


def save_training_plot(history, save_dir):
    """학습 지표 저장"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle("Training Metrics", fontsize=14, fontweight="bold")

        # Train Loss & Eval Loss
        ax = axes[0][0]
        if history["train_loss"]:
            steps, vals = zip(*history["train_loss"])
            ax.plot(steps, vals, label="train_loss", color="#2196F3", linewidth=1, alpha=0.8)
        if history["eval_loss"]:
            steps, vals = zip(*history["eval_loss"])
            ax.plot(steps, vals, "o-", label="eval_loss", color="#F44336", markersize=5, linewidth=1.5)
        ax.set_xlabel("Step")
        ax.set_ylabel("Loss")
        ax.set_title("Loss")
        ax.legend()
        ax.grid(True, alpha=0.3)

        # Grad Norm
        ax = axes[0][1]
        if history["grad_norm"]:
            steps, vals = zip(*history["grad_norm"])
            ax.plot(steps, vals, color="#FF9800", linewidth=1, alpha=0.8)
        ax.set_xlabel("Step")
        ax.set_ylabel("Grad Norm")
        ax.set_title("Gradient Norm")
        ax.grid(True, alpha=0.3)

        # Learning Rate
        ax = axes[1][0]
        if history["lr"]:
            steps, vals = zip(*history["lr"])
            ax.plot(steps, vals, color="#4CAF50", linewidth=1.5)
        ax.set_xlabel("Step")
        ax.set_ylabel("Learning Rate")
        ax.set_title("Learning Rate Schedule")
        ax.grid(True, alpha=0.3)

        # Token Accuracy
        ax = axes[1][1]
        if history["token_acc"]:
            steps, vals = zip(*history["token_acc"])
            ax.plot(steps, vals, label="train", color="#9C27B0", linewidth=1, alpha=0.8)
        if history.get("eval_token_acc"):
            steps, vals = zip(*history["eval_token_acc"])
            ax.plot(steps, vals, "o-", label="eval", color="#E91E63", markersize=5, linewidth=1.5)
            ax.legend()
        ax.set_xlabel("Step")
        ax.set_ylabel("Token Accuracy")
        ax.set_title("Mean Token Accuracy")
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plot_path = os.path.join(save_dir, "training_metrics.png")
        fig.savefig(plot_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return plot_path
    except Exception as e:
        logger.warning("생성 실패: %s", e)
        return None


class TrainLogCallback(TrainerCallback):
    """
    시각화용 로그 데이터 수집 + ETA 표시 + 실시간 그래프 갱신
    """
    def __init__(self, log_path: str, plot_dir: str = None):
        self.log_path = log_path
        self.plot_dir = plot_dir
        self.history = {
            "train_loss": [],
            "eval_loss": [],
            "grad_norm": [],
            "lr": [],
            "token_acc": [],
            "eval_token_acc": [],
        }
        self.best_eval_loss = float("inf")
        self.best_step = 0
        self.train_start_time = None

    def _write(self, line: str):
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _format_eta(self, seconds):
        h, rem = divmod(int(seconds), 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h}h {m:02d}m {s:02d}s"
        return f"{m}m {s:02d}s"

    def on_train_begin(self, args, state, control, **kwargs):
        self.train_start_time = datetime.now(KST)
        total_steps = state.max_steps
        start_str = self.train_start_time.strftime("%Y-%m-%d %H:%M:%S")
        header = f"{'step':>6} | {'loss':>8} | {'grad_norm':>10} | {'lr':>12} | {'token_acc':>10}"
        self._write(header)
        self._write("-" * 60)
        logger.info("학습 시작 시각: %s | 총 스텝: %d", start_str, total_steps)
        logger.info("학습 로그 파일: %s", self.log_path)

    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs is None:
            return

        step = state.global_step
        loss = logs.get("loss", "")
        grad_norm = logs.get("grad_norm", "")
        lr = logs.get("learning_rate", "")
        token_acc = logs.get("mean_token_accuracy", "")

        if loss != "":
            loss_f = float(loss)
            gpu = get_gpu_stats()
            acc_s_log = f" | token_acc={float(token_acc):.4f}" if token_acc != "" else ""

            eta_str = ""
            if self.train_start_time and step > 0:
                elapsed = (datetime.now(KST) - self.train_start_time).total_seconds()
                remaining = elapsed / step * (state.max_steps - step)
                eta_str = f" | ETA: {self._format_eta(remaining)}"

            if gpu:
                print(
                    f"[Step {step}/{state.max_steps}] loss={loss_f:.4f}{acc_s_log}"
                    f" | GPU: {gpu['vram_used_mb']}/{gpu['vram_total_mb']} MiB"
                    f" ({gpu['gpu_util_pct']}%) {gpu['temp_c']}°C{eta_str}",
                    flush=True,
                )
            else:
                print(f"[Step {step}/{state.max_steps}] loss={loss_f:.4f}{acc_s_log}{eta_str}", flush=True)

            loss_s = f"{loss_f:.4f}"
            grad_s = f"{float(grad_norm):.4f}" if grad_norm != "" else ""
            lr_s = f"{float(lr):.8f}" if lr != "" else ""
            acc_s = f"{float(token_acc):.4f}" if token_acc != "" else ""
            self._write(f"{step:>6} | {loss_s:>8} | {grad_s:>10} | {lr_s:>12} | {acc_s:>10}")

            self.history["train_loss"].append((step, loss_f))
            if grad_norm != "":
                self.history["grad_norm"].append((step, float(grad_norm)))
            if lr != "":
                self.history["lr"].append((step, float(lr)))
            if token_acc != "":
                self.history["token_acc"].append((step, float(token_acc)))

            if self.plot_dir:
                save_training_plot(self.history, self.plot_dir)

    def on_evaluate(self, args, state, control, metrics=None, **kwargs):
        if metrics is None:
            return
        eval_loss = metrics.get("eval_loss")
        if eval_loss is not None:
            step = state.global_step
            eval_acc = metrics.get("eval_mean_token_accuracy")
            acc_str = f" | eval_token_acc={eval_acc:.6f}" if eval_acc is not None else ""
            self._write(f"  [eval] step={step} | eval_loss={eval_loss:.6f}{acc_str}")
            self.history["eval_loss"].append((step, eval_loss))
            if eval_acc is not None:
                self.history["eval_token_acc"].append((step, eval_acc))

            if eval_loss < self.best_eval_loss:
                self.best_eval_loss = eval_loss
                self.best_step = step


def check_gpu():
    """GPU 상태 확인"""
    logger.info("=" * 50)
    logger.info("PyTorch: %s | CUDA: %s", torch.__version__, torch.cuda.is_available())
    if torch.cuda.is_available():
        logger.info("GPU 수: %s | 디바이스 0: %s", torch.cuda.device_count(), torch.cuda.get_device_name(0))
        gpu = get_gpu_stats()
        if gpu:
            logger.info("VRAM: %d / %d MiB | GPU: %d%% | 온도: %d°C",
                        gpu["vram_used_mb"], gpu["vram_total_mb"],
                        gpu["gpu_util_pct"], gpu["temp_c"])
    else:
        logger.warning("CUDA를 사용할 수 없습니다.")
    logger.info("=" * 50)


def parse_args():
    """커맨드라인 인자 파싱"""
    parser = argparse.ArgumentParser(description="GPT-OSS LoRA 파인튜닝")
    parser.add_argument(
        "--mode", type=str, required=True, choices=["new", "resume", "update"],
        help="new: 처음부터 학습, resume: 체크포인트 재개, update: 어댑터 추가 학습",
    )
    parser.add_argument(
        "--stage", type=str, required=True, choices=["p", "pretraining", "i", "instruction", "a", "all"],
        help="p: pretraining, i: instruction, a: all (p→i 순차 독립 학습)",
    )
    parser.add_argument(
        "--id", type=str, default=None,
        help="resume/update 시 폴더명 (예: p-2026-0215-1430, i-2026-0215-2028)",
    )
    parser.add_argument(
        "--base", type=str, default=None,
        help="CONFIG의 베이스 모델 경로를 덮어씀"
    )
    args = parser.parse_args()
    if args.mode in ("resume", "update") and not args.id:
        parser.error(f"--mode {args.mode} 사용 시 --id 필요 (예: p-2026-0215-1430, i-2026-0215-2028)")
    if args.stage in ("a", "all") and args.mode != "new":
        parser.error("--stage a/all은 --mode new에서만 사용 가능합니다")
    return args


def get_stage_prefix(stage_arg):
    """전달받은 인자 반환"""
    return "p" if stage_arg in ["p", "pretraining"] else "i"


def get_checkpoint_dir(args):
    """
    체크포인트 저장 경로 반환
    """
    base = CONFIG["checkpoint_dir_base"]
    if args.mode in ("new", "update"):
        timestamp = datetime.now(KST).strftime("%Y-%m%d-%H%M")
        prefix = get_stage_prefix(args.stage)
        folder_name = f"{prefix}-{timestamp}"
        out = os.path.join(base, folder_name)
        os.makedirs(out, exist_ok=True)
        return out
    
    out = os.path.join(base, args.id)
    if not os.path.isdir(out):
        sys.exit(f"체크포인트 디렉터리를 찾을 수 없습니다: {out}")
    return out


def get_best_adapter_dir(checkpoint_dir):
    """
    최적 어댑터 저장 경로 반환
    """
    base = CONFIG["best_adapter_dir_base"]
    run_id = os.path.basename(os.path.normpath(checkpoint_dir))
    out = os.path.join(base, run_id)
    os.makedirs(out, exist_ok=True)
    return out


def get_update_adapter_path(args):
    """update 모드 어댑터 경로 반환"""
    path = os.path.join(CONFIG["best_adapter_dir_base"], args.id)
    if not os.path.isdir(path):
        sys.exit(f"어댑터 디렉터리를 찾을 수 없습니다: {path}")
    return path


def save_train_log(args, checkpoint_dir, best_adapter_dir, adapter_from=None):
    """학습 설정값과 메타데이터를 JSON 파일로 저장"""
    log_path = os.path.join(checkpoint_dir, "train_params.json")
    log_data = {
        **CONFIG,
        "mode": args.mode,
        "stage": args.stage,
        "run_id": args.id if args.mode == "resume" else os.path.basename(checkpoint_dir),
        "adapter_from": adapter_from,
        "checkpoint_dir": checkpoint_dir,
        "best_adapter_dir": best_adapter_dir,
        "timestamp": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2, ensure_ascii=False)
    logger.info("학습 파라미터 저장: %s", log_path)
# endregion [Utils]


# region [Training]
def train_all(args):
    """P→I 순차 독립 학습 (각각 별도 프로세스로 GPU 메모리 완전 해제)"""
    cmd_base = [sys.executable, os.path.abspath(__file__), "--mode", "new"]
    if args.base:
        cmd_base += ["--base", args.base]

    logger.info("=" * 60)
    logger.info("[ALL] P→I 순차 독립 학습 시작 (베이스: %s)", CONFIG["base_model_path"])
    logger.info("=" * 60)

    for idx, stage in enumerate(["p", "i"], 1):
        logger.info("[ALL] Step %d/2: %s adapter 학습", idx, stage.upper())
        result = subprocess.run(cmd_base + ["--stage", stage])
        if result.returncode != 0:
            sys.exit(f"[ALL] {stage.upper()} adapter 학습 실패 (exit code: {result.returncode})")
        logger.info("[ALL] Step %d/2: %s adapter 학습 완료", idx, stage.upper())

    logger.info("=" * 60)
    logger.info("[ALL] P→I 순차 독립 학습 완료")
    logger.info("  P adapter: %s/p-*", CONFIG["best_adapter_dir_base"])
    logger.info("  I adapter: %s/i-*", CONFIG["best_adapter_dir_base"])
    logger.info("=" * 60)


def train():
    """모델 학습"""
    check_gpu()
    args = parse_args()

    if args.base:
        CONFIG["base_model_path"] = args.base
        logger.info("베이스 모델 경로 덮어쓰기 적용: %s", args.base)

    if args.stage in ("a", "all"):
        train_all(args)
        return

    prefix = get_stage_prefix(args.stage)

    if prefix == "p":
        data_path = CONFIG["pretraining_data_path"]
        dataset_text_field = "text"
        packing = True
        logger.info("Pretraining Mode Applied")
    else:
        data_path = CONFIG["instruction_data_path"]
        dataset_text_field = None
        packing = False
        logger.info("Instruction Mode Applied")

    checkpoint_dir = get_checkpoint_dir(args)
    best_adapter_dir = get_best_adapter_dir(checkpoint_dir)
    logger.info("체크포인트 경로: %s", checkpoint_dir)
    logger.info("최적 어댑터 경로: %s", best_adapter_dir)

    adapter_from = None
    if args.mode == "update":
        adapter_from = get_update_adapter_path(args)
        logger.info("추가 학습 원본 어댑터: %s", adapter_from)

    save_train_log(args, checkpoint_dir, best_adapter_dir, adapter_from)
    log_txt_path = os.path.join(checkpoint_dir, "train_log.txt")

    model_path = CONFIG["base_model_path"]
    
    # Unsloth FastLanguageModel 사용하여 모델과 토크나이저 한 번에 로드
    logger.info("Unsloth 모델 및 토크나이저 로드 중: %s", model_path)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_path,
        max_seq_length=CONFIG["max_seq_length"],
        dtype=torch.bfloat16 if CONFIG["bf16"] else None,
        load_in_4bit=False,
        trust_remote_code=True,
        device_map=CONFIG["device_map"],
        quantization_config=Mxfp4Config(dequantize=True),
    )

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    model.config.use_cache = False

    if args.mode == "update":
        logger.info("기존 어댑터 로드 (추가 학습): %s", adapter_from)
        model = PeftModel.from_pretrained(model, adapter_from, is_trainable=True)
    else:
        logger.info("새 Unsloth LoRA 어댑터 생성: r=%d, alpha=%d", CONFIG["lora_r"], CONFIG["lora_alpha"])
        model = FastLanguageModel.get_peft_model(
            model,
            r=CONFIG["lora_r"],
            target_modules=CONFIG["lora_target_modules"],
            lora_alpha=CONFIG["lora_alpha"],
            lora_dropout=0, # Unsloth 최적화를 위해 0 적용
            bias="none",
            use_gradient_checkpointing="unsloth",
            random_state=42,
            use_rslora=CONFIG["use_rslora"],
            use_dora=CONFIG["use_dora"]
        )

    model.print_trainable_parameters()

    sample_pct = CONFIG["p_data_sample_ratio"] if prefix == "p" else CONFIG["i_data_sample_ratio"]
    sample_ratio = sample_pct / 100.0
    logger.info("데이터셋 로드: %s (샘플링 비율: %d%%)", data_path, sample_pct)

    full_ds = load_dataset("json", data_files=data_path, split="train")

    if sample_ratio < 1.0:
        sampled_ds = full_ds.train_test_split(train_size=sample_ratio, seed=42)["train"]
    else:
        sampled_ds = full_ds

    split_ds = sampled_ds.train_test_split(test_size=CONFIG["test_split_ratio"], seed=42)
    train_dataset = split_ds["train"]
    eval_dataset = split_ds["test"]

    eval_samples = CONFIG["p_eval_samples"] if prefix == "p" else CONFIG["i_eval_samples"]
    eval_full_size = len(eval_dataset)
    if len(eval_dataset) > eval_samples:
        eval_dataset = eval_dataset.shuffle(seed=42).select(range(eval_samples))

    logger.info("데이터 분할 — 전체: %d건, 샘플링: %d건, train: %d건, eval: %d건 (전체 eval %d건 중 서브샘플링)",
                len(full_ds), len(sampled_ds), len(train_dataset), len(eval_dataset), eval_full_size)

    sft_kwargs = dict(
        output_dir=checkpoint_dir, num_train_epochs=CONFIG["p_epochs"] if prefix == "p" else CONFIG["i_epochs"],
        per_device_train_batch_size=CONFIG["per_device_train_batch_size"],
        gradient_accumulation_steps=CONFIG["gradient_accumulation_steps"],
        learning_rate=CONFIG["learning_rate"], lr_scheduler_type=CONFIG["lr_scheduler_type"],
        warmup_ratio=CONFIG["warmup_ratio"], bf16=CONFIG["bf16"], fp16=CONFIG["fp16"],
        per_device_eval_batch_size=CONFIG["per_device_eval_batch_size"],
        save_strategy="steps", save_steps=CONFIG["save_steps"], eval_strategy="steps", eval_steps=CONFIG["eval_steps"],
        load_best_model_at_end=True, metric_for_best_model="eval_loss", greater_is_better=False,
        save_total_limit=CONFIG["save_total_limit"], logging_steps=CONFIG["logging_steps"], optim=CONFIG["optim"],
        report_to=CONFIG["report_to"], gradient_checkpointing=CONFIG["gradient_checkpointing"],
        dataloader_num_workers=CONFIG["dataloader_num_workers"], dataloader_pin_memory=CONFIG["dataloader_pin_memory"],
        max_length=CONFIG["max_seq_length"],
        packing=packing,
        eos_token=tokenizer.eos_token,
    )
    if dataset_text_field is not None:
        sft_kwargs["dataset_text_field"] = dataset_text_field
    sft_config = SFTConfig(**sft_kwargs)

    log_callback = TrainLogCallback(log_txt_path, plot_dir=checkpoint_dir)
    trainer_kwargs = dict(
        model=model, args=sft_config, train_dataset=train_dataset, eval_dataset=eval_dataset,
        processing_class=tokenizer, callbacks=[log_callback],
    )
    if prefix == "i":
        def formatting_func(example):
            msgs = example["messages"]
            if msgs and isinstance(msgs[0], dict):
                return [tokenizer.apply_chat_template(msgs, tokenize=False)]
            return [tokenizer.apply_chat_template(m, tokenize=False) for m in msgs]
        trainer_kwargs["formatting_func"] = formatting_func
    trainer = SFTTrainer(**trainer_kwargs)

    if prefix == "i":
        trainer = train_on_responses_only(
            trainer,
            instruction_part="<|start|>user<|message|>",
            response_part="<|start|>assistant",
        )
        logger.info("Unsloth train_on_responses_only 적용 완료")

    _orig_compute_loss = trainer.compute_loss
    def _compute_loss_with_acc(mdl, inputs, return_outputs=False, num_items_in_batch=None):
        (loss, outputs) = _orig_compute_loss(mdl, inputs, return_outputs=True, num_items_in_batch=num_items_in_batch)
        mode = "train" if trainer.model.training else "eval"
        try:
            logits = outputs.logits
            if logits is not None and hasattr(logits, "shape"):
                labels = inputs.get("labels")
                if labels is not None:
                    with torch.no_grad():
                        shift_logits = logits[..., :-1, :].contiguous()
                        shift_labels = labels[..., 1:].contiguous()
                        preds = shift_logits.argmax(dim=-1)
                        mask = shift_labels != -100
                        total = mask.sum()
                        if total > 0:
                            acc = ((preds == shift_labels) & mask).sum().float() / total.float()
                            trainer._metrics[mode]["mean_token_accuracy"].append(acc.item())
        except Exception:
            pass
        return (loss, outputs) if return_outputs else loss
    trainer.compute_loss = _compute_loss_with_acc

    if args.mode == "resume":
        last_ckpt = get_last_checkpoint(checkpoint_dir)
        if last_ckpt:
            logger.info("체크포인트 재개: %s", last_ckpt)
            trainer.train(resume_from_checkpoint=last_ckpt)
        else:
            sys.exit(f"체크포인트를 찾을 수 없습니다: {checkpoint_dir}")
    else:
        logger.info("학습 시작")
        trainer.train()

    logger.info("최적 어댑터 저장: %s", best_adapter_dir)
    trainer.model.save_pretrained(best_adapter_dir)
    tokenizer.save_pretrained(best_adapter_dir)

    # 시각화 그래프 생성
    plot_path = save_training_plot(log_callback.history, checkpoint_dir)
    if plot_path:
        shutil.copy2(plot_path, os.path.join(best_adapter_dir, "training_metrics.png"))
        logger.info("학습 시각화 저장: %s", plot_path)

    best_log_path = os.path.join(best_adapter_dir, "train_log.txt")
    shutil.copy2(log_txt_path, best_log_path)

    best_info = {
        "best_eval_loss": log_callback.best_eval_loss if log_callback.best_eval_loss < float("inf") else None,
        "best_step": log_callback.best_step,
        "total_steps": trainer.state.global_step,
        "checkpoint_dir": checkpoint_dir,
        "adapter_from": adapter_from,
        "timestamp": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(best_adapter_dir, "best_info.json"), "w", encoding="utf-8") as f:
        json.dump(best_info, f, indent=2, ensure_ascii=False)

    logger.info("=" * 50)
    logger.info("학습 완료")
    logger.info("체크포인트: %s", checkpoint_dir)
    logger.info("최적 어댑터: %s", best_adapter_dir)
    if log_callback.best_eval_loss < float("inf"):
        logger.info("  best eval_loss: %.6f (step %d)", log_callback.best_eval_loss, log_callback.best_step)
    logger.info("학습 로그: %s", log_txt_path)
    logger.info("=" * 50)
# endregion [Training]


if __name__ == "__main__":
    train()