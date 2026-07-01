from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


RAGAS_DIR = Path(__file__).resolve().parent

INPUT_KEYS = ("id", "user_input", "facility_info")
DEFAULT_PRESERVED_FIELDS = {
    "reference_contexts": [],
    "reference_context_metadata": [],
    "reference": None,
    "retrieved_contexts": None,
    "response": None,
}


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_sample(
    source_sample: Dict[str, Any],
    existing_sample: Dict[str, Any] | None,
) -> Dict[str, Any]:
    preserved: Dict[str, Any] = {}
    if existing_sample:
        for key, value in existing_sample.items():
            if key not in INPUT_KEYS:
                preserved[key] = value

    merged = {**DEFAULT_PRESERVED_FIELDS, **preserved}

    sample = {
        "id": source_sample.get("id"),
        "user_input": source_sample.get("user_input"),
        "facility_info": source_sample.get("facility_info"),
    }

    for key in DEFAULT_PRESERVED_FIELDS:
        sample[key] = merged.pop(key)

    for key, value in merged.items():
        sample[key] = value

    return sample


def main(source_path: Path, target_path: Path) -> None:
    source_data = _load_json(source_path)
    target_data = _load_json(target_path) if target_path.exists() else {}

    target_samples = target_data.get("samples", [])
    target_by_id = {
        str(sample.get("id")): sample
        for sample in target_samples
        if sample.get("id") is not None
    }

    merged_samples = []
    source_ids = []
    preserved_count = 0

    for source_sample in source_data.get("samples", []):
        sample_id = str(source_sample.get("id"))
        source_ids.append(sample_id)
        existing_sample = target_by_id.get(sample_id)
        if existing_sample is not None:
            preserved_count += 1
        merged_samples.append(_build_sample(source_sample, existing_sample))

    dropped_ids = [
        sample_id
        for sample_id in target_by_id
        if sample_id not in set(source_ids)
    ]

    output = {
        "version": source_data.get("version", target_data.get("version", "0.1.0")),
        "description": source_data.get(
            "description",
            target_data.get("description", "RAGAS TEST"),
        ),
        "samples": merged_samples,
    }

    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Wrote {target_path} ({len(merged_samples)} samples)")
    print(f"Preserved annotation fields for {preserved_count} samples")
    if dropped_ids:
        print(f"Dropped {len(dropped_ids)} samples not found in source")


if __name__ == "__main__":
    source_path = RAGAS_DIR / "ragas_test_origin.json"
    target_path = RAGAS_DIR / "ragas_test.json"
    main(source_path=source_path, target_path=target_path)
