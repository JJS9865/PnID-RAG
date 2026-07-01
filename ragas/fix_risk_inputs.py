"""risk 항목 중 1-chunk인 14개의 user_input/facility_info를 수정하여
사고 DB에서 2건 이상 검색되도록 물질을 교체한다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

RAGAS_FILE = Path(__file__).resolve().parent / "ragas_test.json"

QUESTION_UPDATES: Dict[str, str] = {
    "risk-004": "암모니아를 취급하는 저장탱크에서 누출 시 작업자 질식 위험을 평가해줘.",
    "risk-005": "메탄올을 취급하는 배관에서 누출 시 화재 위험성을 알려줘.",
    "risk-007": "톨루엔을 분리하는 증류탑에서 과압이나 역류 시 화재 위험성을 알려줘.",
    "risk-008": "아세톤을 교반하는 교반기에서 정전기로 인한 화재 위험이 있는지 알려줘.",
    "risk-009": "톨루엔을 이송하는 펌프에서 누출 시 화재 폭발 위험을 알려줘.",
    "risk-010": "메탄올을 이송하는 펌프에서 씨울 파손 시 누출 화재 위험을 분석해줘.",
    "risk-011": "암모니아를 취급하는 배관에서 누출 시 작업자 건강 위험을 알려줘.",
    "risk-016": "톨루엔을 저장하는 저장탱크에서 누출 시 화재 위험을 분석해줘.",
    "risk-020": "크실렌을 저장하는 저장탱크에서 증기 폭발이나 인화 위험이 있는지 알려줘.",
    "risk-022": "톨루엔을 냉각하는 냉각기에서 누출 시 화재 위험을 분석해줘.",
    "risk-025": "톨루엔을 분리하는 분리기에서 정전기 착화 위험을 분석해줘.",
    "risk-026": "황산을 취급하는 반응기에서 부식 누출 시 작업자 화상 위험을 알려줘.",
    "risk-027": "과산화수소를 완충하는 서지탱크에서 분해 반응으로 인한 과압 위험이 있는지 알려줘.",
    "risk-029": "메탄올 증기를 응축하는 응축기에서 누출 시 화재 위험을 알려줘.",
}

FACILITY_UPDATES: Dict[str, Dict[str, Any]] = {
    "risk-004": {
        "equip_id": "T-2004", "equip_type": "저장탱크", "material": "암모니아",
        "specs": {"용량": "30 m3", "설계 압력": "17.5 barg", "재질": "CS"},
    },
    "risk-005": {
        "equip_id": "L-2005", "equip_type": "배관", "material": "메탄올",
        "specs": {"구경": "4 inch", "재질": "CS", "운전 압력": "3 barg"},
    },
    "risk-007": {"material": "톨루엔"},
    "risk-008": {"material": "아세톤", "specs": {"형식": "Top entry", "동력": "22 kW", "재질": "SS316L"}},
    "risk-009": {"material": "톨루엔", "specs": {"형식": "Centrifugal", "양정": "50 m", "재질": "SS316L"}},
    "risk-010": {"material": "메탄올"},
    "risk-011": {
        "equip_id": "L-2011", "equip_type": "배관", "material": "암모니아",
        "specs": {"구경": "6 inch", "재질": "CS", "운전 압력": "10 barg"},
    },
    "risk-016": {
        "equip_id": "T-2016", "equip_type": "저장탱크", "material": "톨루엔",
        "specs": {"용량": "20 m3", "설계 압력": "2 barg", "재질": "CS"},
    },
    "risk-020": {"material": "크실렌", "specs": {"용량": "50 m3", "설계 압력": "2 barg", "재질": "CS"}},
    "risk-022": {"material": "톨루엔"},
    "risk-025": {"material": "톨루엔"},
    "risk-026": {
        "equip_id": "R-2026", "equip_type": "반응기", "material": "황산",
        "specs": {"형식": "CSTR", "용량": "8 m3", "재질": "SS316L", "운전 온도": "80 degC"},
    },
    "risk-027": {"material": "과산화수소"},
    "risk-029": {"material": "메탄올"},
}


def main():
    with open(RAGAS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    q_count = 0
    f_count = 0
    for sample in data.get("samples", []):
        sid = sample.get("id", "")

        if sid in QUESTION_UPDATES:
            sample["user_input"] = QUESTION_UPDATES[sid]
            q_count += 1

        if sid in FACILITY_UPDATES:
            updates = FACILITY_UPDATES[sid]
            equip_list = sample.get("facility_info", {}).get("equipment_list", [])
            if equip_list:
                equip = equip_list[0]
                for key in ("equip_id", "equip_type", "material"):
                    if key in updates:
                        equip[key] = updates[key]
                if "specs" in updates:
                    equip["specs"] = updates["specs"]
                f_count += 1

    with open(RAGAS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Wrote {RAGAS_FILE}")
    print(f"Updated {q_count} user_inputs, {f_count} facility_infos")


if __name__ == "__main__":
    main()
