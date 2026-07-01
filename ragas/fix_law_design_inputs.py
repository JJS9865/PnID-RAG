from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


RAGAS_DIR = Path(__file__).resolve().parent
TARGET_PATH = RAGAS_DIR / "ragas_test.json"


# law 항목의 user_input을 법률 DB 키워드 빈도에 기반해 재작성
# DB 키워드 빈도: 경보(103), 보호구(109), 부식(96), 밀폐(91),
#   유해물질(75), 안전밸브(59), 세척(51), 응급조치(49), 안전진단(46),
#   수시검사(43), 배기장치(42), 작업환경측정(40), 사고대비물질(35),
#   긴급차단(35), 국소배기(33), 정기검사(31), 관리대상(31), 화학설비(30),
#   방폭(30), 안전장치(26), 방류벽(25), 안전거리(12)
# DB 0건: 방호벽(0), 가스 저장(0), 누출 방지(1), 배관 재질(2)
QUESTION_UPDATES: Dict[str, str] = {
    # 산업안전보건기준에 관한 규칙 - 폭발위험장소/방폭
    "law-002": (
        "메탄올 등 인화성 액체를 수시로 취급하는 반응기 구역에서 "
        "산업안전보건기준에 관한 규칙상 폭발위험장소의 전기기계·기구 사용 제한 기준을 위반했는지 검토해줘."
    ),
    "law-017": (
        "디젤 등 인화성 액체를 가열하는 히터 부근이 "
        "산업안전보건기준에 관한 규칙상 폭발위험장소 구분 및 방폭구조 전기기계·기구 사용 기준을 위반했는지 검토해줘."
    ),
    # 고압가스 안전관리법 - law-003 패턴 유지 ("가스 시설의 안전장치 및 ...")
    "law-003": (
        "LPG를 처리하는 플레어 스택 공정이 "
        "고압가스 안전관리법상 가스 시설의 안전장치 및 가스 누출 검지 경보장치 설치 기준을 위반했는지 검토해줘."
    ),
    "law-006": (
        "수소 가스를 취급하는 압축기가 "
        "고압가스 안전관리법상 가스 시설의 안전장치 및 긴급차단장치 설치와 정기검사 기준을 위반했는지 검토해줘."
    ),
    "law-020": (
        "암모니아를 취급하는 냉각기 공정이 "
        "고압가스 안전관리법상 독성가스 시설의 가스 누출 검지 경보장치 설치 및 방독면 비치 기준을 위반했는지 검토해줘."
    ),
    "law-025": (
        "LPG를 저장하는 서지탱크가 "
        "고압가스 안전관리법상 가스 시설의 안전거리 확보 및 안전장치와 긴급차단장치 설치 기준을 위반했는지 검토해줘."
    ),
    # 화학물질관리법 - 사고대비물질/화학사고
    "law-004": (
        "암모니아를 취급하는 냉각기 공정이 "
        "화학물질관리법상 사고대비물질의 방류벽 설치 및 긴급차단장치와 경보장치 설치 기준을 위반했는지 검토해줘."
    ),
    "law-019": (
        "톨루엔이 흐르는 제어밸브 라인에서 "
        "화학물질관리법상 화학사고 발생 시 즉시 신고 의무와 응급조치 및 비상조치 기준을 위반했는지 검토해줘."
    ),
    # 유해화학물질 취급시설 - 검사/안전진단
    "law-007": (
        "황산을 취급하는 열교환기가 "
        "화학물질관리법상 유해화학물질 취급시설의 정기검사 및 수시검사와 안전진단 기준을 위반했는지 검토해줘."
    ),
    "law-010": (
        "과산화수소를 저장하는 저장탱크가 "
        "유해화학물질 취급시설의 설치검사 및 정기검사 주기 기준을 위반했는지 검토해줘."
    ),
    "law-014": (
        "염산 가스를 처리하는 세정탑이 "
        "유해화학물질 취급시설의 방류벽 설치 및 긴급차단장치와 경보장치 설치 기준을 위반했는지 검토해줘."
    ),
    # 산업안전보건기준에 관한 규칙 - 특수화학설비/화학설비
    "law-005": (
        "벤젠을 취급하는 증류탑이 "
        "산업안전보건기준에 관한 규칙상 특수화학설비의 안전조치 및 긴급차단장치 설치 기준을 위반했는지 검토해줘."
    ),
    "law-009": (
        "황화수소를 취급하는 흡수탑이 "
        "산업안전보건기준에 관한 규칙상 화학설비의 안전밸브 및 긴급차단장치 설치와 부식 방지 기준을 위반했는지 검토해줘."
    ),
    "law-021": (
        "염소 가스를 취급하는 ESDV 공정이 "
        "산업안전보건기준에 관한 규칙상 화학설비의 긴급차단장치 설치 및 비상조치 기준을 위반했는지 검토해줘."
    ),
    "law-026": (
        "수소 가스를 취급하는 PSV 공정이 "
        "산업안전보건기준에 관한 규칙상 화학설비의 안전밸브 설치 및 정기검사 기준을 위반했는지 검토해줘."
    ),
    # 산업안전보건기준에 관한 규칙 - 관리대상 유해물질/국소배기
    "law-008": (
        "가성소다를 이송하는 펌프 설비에서 "
        "산업안전보건기준에 관한 규칙상 관리대상 유해물질 취급 시 국소배기장치 설치 및 보호구 지급 기준을 위반했는지 검토해줘."
    ),
    "law-023": (
        "벤젠을 취급하는 분리기가 "
        "산업안전보건기준에 관한 규칙상 관리대상 유해물질 취급 시 국소배기장치 설치 및 작업환경측정 기준을 위반했는지 검토해줘."
    ),
    # 산업안전보건기준에 관한 규칙 - 부식성 물질/보호구 (law-024는 이미 3건 성공)
    "law-024": (
        "황산을 취급하는 교반기 공정에서 "
        "산업안전보건기준에 관한 규칙상 부식성 물질 취급 시 보호구 착용 및 긴급 세안·세척 설비 설치 기준을 위반했는지 검토해줘."
    ),
    # 산업안전보건기준에 관한 규칙 - 인화성 액체 증기
    "law-015": (
        "나프타를 가열하는 열교환기 공정이 "
        "산업안전보건기준에 관한 규칙상 인화성 액체의 증기 발산 방지 및 환기 설비 설치 기준을 위반했는지 검토해줘."
    ),
    # 위험물안전관리법
    "law-016": (
        "크실렌을 저장하는 저장탱크가 "
        "위험물안전관리법상 위험물 저장소의 설치허가 및 안전관리자 선임 기준을 위반했는지 검토해줘."
    ),
}


# 새 질문에 어울리는 설비 사양 보강
FACILITY_UPDATES: Dict[str, Dict[str, Any]] = {
    "law-002": {"specs": {"운전 온도": "65 degC"}},
    "law-003": {"specs": {"운전 압력": "5 barg"}},
    "law-004": {"specs": {"운전 온도": "-33 degC", "운전 압력": "10 barg"}},
    "law-005": {"specs": {"운전 온도": "80 degC", "운전 압력": "1.5 barg"}},
    "law-006": {"specs": {"형식": "Reciprocating", "토출 압력": "50 barg"}},
    "law-010": {"specs": {"저장량": "30 ton"}},
    "law-015": {"specs": {"운전 온도": "180 degC"}},
    "law-016": {"specs": {"용량": "100 m3"}},
    "law-017": {"specs": {"운전 온도": "350 degC"}},
    "law-020": {"specs": {"운전 압력": "15 barg"}},
    "law-025": {"specs": {"설계 압력": "17.5 barg"}},
}


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _first_equipment(sample: Dict[str, Any]) -> Dict[str, Any] | None:
    facility_info = sample.get("facility_info") or {}
    equipments = facility_info.get("equipment_list") or facility_info.get("equipments")
    if not equipments:
        return None
    return equipments[0]


def _update_equipment(sample: Dict[str, Any], update: Dict[str, Any]) -> bool:
    equipment = _first_equipment(sample)
    if equipment is None:
        return False

    if "material" in update:
        equipment["material"] = update["material"]

    if "equip_type" in update:
        equipment["equip_type"] = update["equip_type"]
        if "type" in equipment:
            equipment["type"] = update["equip_type"]

    if "specs" in update:
        specs = equipment.get("specs") or equipment.get("spec")
        if specs is None:
            specs = {}
            equipment["specs"] = specs
        specs.update(update["specs"])

    return True


def main(target_path: Path) -> None:
    data = _load_json(target_path)
    q_changed = 0
    f_changed = 0

    for sample in data.get("samples", []):
        sample_id = sample.get("id")
        if sample_id in QUESTION_UPDATES:
            sample["user_input"] = QUESTION_UPDATES[sample_id]
            q_changed += 1
        if sample_id in FACILITY_UPDATES:
            if _update_equipment(sample, FACILITY_UPDATES[sample_id]):
                f_changed += 1

    _write_json(target_path, data)
    print(f"Wrote {target_path}")
    print(f"Updated {q_changed} user_inputs, {f_changed} facility_infos")


if __name__ == "__main__":
    main(target_path=TARGET_PATH)
