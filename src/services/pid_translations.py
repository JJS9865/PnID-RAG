"""
P&ID JSON 파싱에 사용되는 영→한 번역 테이블 및 번역 함수 모음.
json_parser.py와 분리하여 관리한다.
"""

import re
from typing import Dict, List, Optional


# ──────────────────────────────────────────────
# 설비 타입 (equip_type)
# ──────────────────────────────────────────────

EQUIP_TYPE_KO: Dict[str, str] = {
    "TANK":           "탱크",
    "VESSEL":         "용기",
    "DRUM":           "드럼",
    "PUMP":           "펌프",
    "COMPRESSOR":     "압축기",
    "BLOWER":         "송풍기",
    "FAN":            "팬",
    "HEAT EXCHANGER": "열교환기",
    "EXCHANGER":      "열교환기",
    "COOLER":         "냉각기",
    "HEATER":         "가열기",
    "CONDENSER":      "응축기",
    "REBOILER":       "재비기",
    "FILTER":         "필터",
    "SEPARATOR":      "분리기",
    "COLUMN":         "컬럼",
    "REACTOR":        "반응기",
    "AGITATOR":       "교반기",
    "MIXER":          "혼합기",
}


# ──────────────────────────────────────────────
# spec 키
# None → 출력에서 제외
# ──────────────────────────────────────────────

SPEC_KEY_KO: Dict[str, Optional[str]] = {
    "unknown":          None,   # 도면 코드번호 — 불필요
    "type":             "형식",
    "capacity":         "용량",
    "capacity/storage": "용량/저장량",
    "size":             "크기",
    "dp":               "설계압력",
    "dt":               "설계온도",
    "matl":             "재질",
    "matl(cas./imp.)":  "재질(케이싱/임펠러)",
    "matl(cas./mesh)":  "재질(케이싱/메쉬)",
    "diff.p":           "차압",
    "power":            "동력",
    "flow_rate":        "유량",
    "spec_class":       None,   # 배관 사양 코드 — 불필요
}


# ──────────────────────────────────────────────
# 번역 함수
# ──────────────────────────────────────────────

def translate_equip_type(raw: str) -> str:
    """설비 타입 영문 → 한국어. 매핑 없으면 원문 반환."""
    return EQUIP_TYPE_KO.get(raw.strip().upper(), raw)


def translate_spec_key(key: str) -> Optional[str]:
    """spec 키 영문 → 한국어. None이면 해당 항목 제외."""
    return SPEC_KEY_KO.get(key.strip().lower(), key)


def translate_component(tag: str) -> str:
    """배관 구성품 태그 영문 → 한국어. 매핑 없으면 원문 반환."""
    upper = tag.upper()

    if "BALL VALVE" in upper:
        return "볼밸브"
    if upper.startswith("CHECK"):
        return "체크밸브"
    if upper.startswith("GATE VALVE"):
        return "게이트밸브"
    if upper.startswith("GLOBE"):
        return "글로브밸브"
    if upper.startswith("BUTTERFLY"):
        return "버터플라이밸브"
    if "FLOW CONTROL" in upper or upper.startswith("FCV"):
        return "유량조절밸브"
    if "PRESSURE CONTROL" in upper or upper.startswith("PCV"):
        return "압력조절밸브"
    if "RELIEF VALVE" in upper or upper.startswith("PRV") or upper.startswith("PSV"):
        return "안전밸브"
    if upper.startswith("REDUCER"):
        size = tag[len("REDUCER"):].strip()
        return f"레듀서 {size}" if size else "레듀서"
    if "STRAINER" in upper:
        m = re.match(r"^([A-Z])-STRAINER", upper)
        return f"{m.group(1)}형 스트레이너" if m else "스트레이너"
    if upper.startswith("FLOW ELEMENT") or upper.startswith("FLOW METER"):
        return "유량계"
    if upper.startswith("PRESSURE GAUGE"):
        return "압력계"
    if upper.startswith("TEMPERATURE"):
        return "온도계"

    return tag


def is_safety_component(comp: dict) -> bool:
    """배관 구성품이 안전 관련 항목인지 판단합니다.
    VALVE 타입은 항상 포함, GENERAL 타입은 스트레이너만 포함합니다.
    (레듀서·플랜지 등 단순 배관 피팅은 제외)
    """
    comp_type = comp.get("type", "").upper()
    if comp_type == "VALVE":
        return True
    if comp_type == "GENERAL":
        tag = comp.get("tag", "").upper()
        return "STRAINER" in tag
    return False
