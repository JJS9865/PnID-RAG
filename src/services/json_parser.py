import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from src.services.pid_translations import (
    translate_equip_type,
    translate_spec_key,
    translate_component,
    is_safety_component,
)


# ──────────────────────────────────────────────
# 내부 헬퍼
# ──────────────────────────────────────────────

def _load_facility_json(source: Union[dict, str, Path]) -> dict:
    """dict, JSON 문자열, 파일 경로를 모두 dict로 변환합니다."""
    if isinstance(source, dict):
        return source
    if isinstance(source, Path):
        with open(source, "r", encoding="utf-8") as f:
            return json.load(f)
    if isinstance(source, str):
        p = Path(source)
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        return json.loads(source)
    return {}


def _get(d: dict, *keys, default=""):
    """딕셔너리에서 여러 키 후보 중 첫 번째 존재하는 값을 반환합니다."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def _build_pipe_map(pipes: list) -> Dict[str, dict]:
    pipe_by_id: Dict[str, dict] = {}
    for p in pipes:
        lid = _get(p, "id", "line_id")
        if lid:
            pipe_by_id[lid] = p
    return pipe_by_id


def _build_eq_label_map(equipments: list) -> Dict[str, str]:
    """설비 ID → '설비명(설비ID)' 문자열 매핑을 구성합니다.
    연결 끝점 표시에 사용합니다."""
    eq_map: Dict[str, str] = {}
    for eq in equipments:
        eq_id   = _get(eq, "id", "equip_id")
        eq_type = translate_equip_type(_get(eq, "type", "equip_type"))
        if eq_id:
            eq_map[eq_id] = f"{eq_type}({eq_id})"
    return eq_map


def _strip_nozzle_suffix(ref: str) -> str:
    """설비 노즐 레퍼런스에서 노즐 ID를 제거합니다.
    예: D-0410-N1 → D-0410,  P-0410A-N11 → P-0410A"""
    m = re.match(r"^(.+)-N\d+\w*$", ref)
    return m.group(1) if m else ref


def _format_endpoint(ref: str, eq_label_map: Dict[str, str]) -> str:
    """배관 끝점 레퍼런스를 표시용 문자열로 변환합니다.
    - 설비 ID이면 → '설비명(설비ID)' (예: 탱크(D-0410))
    - 외부 시스템이면 → 원문 그대로 (예: LO-00008)
    """
    base = _strip_nozzle_suffix(ref)
    return eq_label_map.get(base, base)


def _comp_text(pipe: dict) -> str:
    """배관 구성품을 한국어 번역 후 쉼표 구분 문자열로 반환합니다."""
    components = pipe.get("components") or []
    if not components:
        return ""
    names = []
    for c in components:
        raw = _get(c, "tag", "type") if isinstance(c, dict) else str(c)
        names.append(translate_component(raw))
    return ", ".join(names)


def _trace_upstream(pipe_id: str, pipe_by_id: dict, visited: Set[str]) -> List[dict]:
    """상류(입구 방향) 배관 체인을 추적합니다."""
    chain = []
    current_id = pipe_id
    while current_id in pipe_by_id and current_id not in visited:
        visited.add(current_id)
        pipe = pipe_by_id[current_id]
        chain.insert(0, pipe)
        from_ref = pipe.get("from", "")
        if from_ref in pipe_by_id:
            current_id = from_ref
        else:
            break
    return chain


def _trace_downstream(pipe_id: str, pipe_by_id: dict, visited: Set[str]) -> List[dict]:
    """하류(출구 방향) 배관 체인을 추적합니다."""
    chain = []
    current_id = pipe_id
    while current_id in pipe_by_id and current_id not in visited:
        visited.add(current_id)
        pipe = pipe_by_id[current_id]
        chain.append(pipe)
        to_ref = pipe.get("to", "")
        if to_ref in pipe_by_id:
            current_id = to_ref
        else:
            break
    return chain


def _collect_safety_components(chains: List[List[dict]]) -> List[str]:
    """배관 체인 목록에서 안전 관련 구성품을 중복 제거 후 정렬하여 반환합니다."""
    seen: Set[str] = set()
    result: List[str] = []
    for chain in chains:
        for pipe in chain:
            for comp in pipe.get("components") or []:
                if isinstance(comp, dict) and is_safety_component(comp):
                    raw = _get(comp, "tag", "type")
                    ko  = translate_component(raw)
                    if ko not in seen:
                        seen.add(ko)
                        result.append(ko)
    return result


def _parse_equipment(eq: dict, pipes: list, pipe_by_id: dict) -> dict:
    """설비 하나를 파싱하여 정보 dict를 반환합니다 (내부 공용)."""
    eq_id        = _get(eq, "id", "equip_id")
    eq_type_raw  = _get(eq, "type", "equip_type")
    eq_type      = translate_equip_type(eq_type_raw)
    material     = _get(eq, "material")
    raw_spec     = _get(eq, "spec", "specs", default=None) or {}

    # spec 키 한국어 번역 + 제외 항목 필터링
    spec: Dict[str, str] = {}
    for k, v in raw_spec.items():
        ko_key = translate_spec_key(k)
        if ko_key is not None:
            spec[ko_key] = str(v)

    # 연결 배관 탐색
    inflows:  List[List[dict]] = []
    outflows: List[List[dict]] = []
    for pipe in pipes:
        from_ref = pipe.get("from", "")
        to_ref   = pipe.get("to", "")
        lid      = _get(pipe, "id", "line_id")

        if to_ref == eq_id or to_ref.startswith(eq_id + "-"):
            inflows.append(_trace_upstream(lid, pipe_by_id, set()))

        if from_ref == eq_id or from_ref.startswith(eq_id + "-"):
            outflows.append(_trace_downstream(lid, pipe_by_id, set()))

    # 설치 구성품 (안전 관련만)
    installed = _collect_safety_components(inflows + outflows)

    return {
        "id":        eq_id,
        "type":      eq_type,
        "material":  material,
        "spec":      spec,
        "inflows":   inflows,
        "outflows":  outflows,
        "installed": installed,
    }


def _filter_equipments(equipments: list, target_ids: Optional[List[str]]) -> list:
    if not target_ids:
        return equipments
    target_set = set(target_ids)
    return [eq for eq in equipments if _get(eq, "id", "equip_id") in target_set]


# ──────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────

def facility_json_to_text(
    facility_info: Union[dict, str, Path],
    target_ids: Optional[List[str]] = None,
) -> str:
    """
    P&ID 정보를 LLM 프롬프트용 한국어 텍스트로 변환합니다.

    Args:
        facility_info : P&ID 데이터. dict / JSON 문자열 / 파일 경로 모두 가능.
        target_ids    : 반환할 설비 ID 목록. None이면 전체 반환.

    Returns:
        LLM이 이해하기 쉬운 한국어 설비 설명 텍스트.

    출력 예시:
        ■ [D-0410] 탱크
          설비 사양 : 형식: VERTICAL, 용량: 55.842 m3, 설계압력: 5 / FV barg, ...
          유입 흐름 : LO-00008 → [레듀서 4X3] → 설비 입구
          유출 흐름 : 설비 출구 → [볼밸브, Y형 스트레이너] → 펌프(P-0410A)
    """
    data = _load_facility_json(facility_info)
    if not data:
        return ""

    all_equipments = _get(data, "equipments", "equipment_list", default=None) or []
    pipes          = _get(data, "lines", "piping_list", default=None) or []

    # 전체 설비 기준으로 label map 구성 (필터 전)
    eq_label_map = _build_eq_label_map(all_equipments)
    pipe_by_id   = _build_pipe_map(pipes)

    equipments = _filter_equipments(all_equipments, target_ids)

    sections = []
    for eq in equipments:
        parsed = _parse_equipment(eq, pipes, pipe_by_id)
        lines  = [f"■ [{parsed['id']}] {parsed['type']}"]

        if parsed["material"]:
            lines.append(f"  취급 물질 : {parsed['material']}")

        if parsed["spec"]:
            spec_str = ", ".join(f"{k}: {v}" for k, v in parsed["spec"].items())
            lines.append(f"  설비 사양 : {spec_str}")

        for chain in parsed["inflows"]:
            if not chain:
                continue
            source = _format_endpoint(chain[0].get("from", "?"), eq_label_map)
            comps  = [_comp_text(p) for p in chain if _comp_text(p)]
            mid    = " → ".join(f"[{c}]" for c in comps) + " → " if comps else ""
            lines.append(f"  유입 흐름 : {source} → {mid}설비 입구")

        for chain in parsed["outflows"]:
            if not chain:
                continue
            dest  = _format_endpoint(chain[-1].get("to", "?"), eq_label_map)
            comps = [_comp_text(p) for p in chain if _comp_text(p)]
            mid   = " → ".join(f"[{c}]" for c in comps) + " → " if comps else ""
            lines.append(f"  유출 흐름 : 설비 출구 → {mid}{dest}")

        if parsed["installed"]:
            lines.append(f"  설치 구성품 : {', '.join(parsed['installed'])}")

        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def facility_json_to_retrieval_text(
    facility_info: Union[dict, str, Path],
    target_ids: Optional[List[str]] = None,
) -> str:
    """
    P&ID 정보를 검색(임베딩)용 한국어 텍스트로 변환합니다.
    핵심 정보를 설비당 1줄로 압축하여 벡터 검색과 키워드 검색 모두에 적합합니다.

    Args:
        facility_info : P&ID 데이터. dict / JSON 문자열 / 파일 경로 모두 가능.
        target_ids    : 반환할 설비 ID 목록. None이면 전체 반환.

    Returns:
        설비당 1줄, `|` 구분 압축 텍스트.

    출력 예시:
        D-0410 탱크 | 형식: VERTICAL | 용량: 55.842 m3 | 설계압력: 5 / FV barg |
        재질: SS 304 | 상류설비: LO-00008 | 하류설비: 펌프(P-0410A)
    """
    data = _load_facility_json(facility_info)
    if not data:
        return ""

    all_equipments = _get(data, "equipments", "equipment_list", default=None) or []
    pipes          = _get(data, "lines", "piping_list", default=None) or []

    eq_label_map = _build_eq_label_map(all_equipments)
    pipe_by_id   = _build_pipe_map(pipes)

    equipments = _filter_equipments(all_equipments, target_ids)

    result_lines = []
    for eq in equipments:
        parsed = _parse_equipment(eq, pipes, pipe_by_id)
        parts  = [f"{parsed['id']} {parsed['type']}"]

        if parsed["material"]:
            parts.append(f"취급물질: {parsed['material']}")

        for k, v in parsed["spec"].items():
            parts.append(f"{k}: {v}")

        upstream = [
            _format_endpoint(chain[0].get("from", ""), eq_label_map)
            for chain in parsed["inflows"] if chain
        ]
        upstream = [s for s in upstream if s]
        if upstream:
            parts.append(f"상류설비: {', '.join(upstream)}")

        downstream = [
            _format_endpoint(chain[-1].get("to", ""), eq_label_map)
            for chain in parsed["outflows"] if chain
        ]
        downstream = [d for d in downstream if d]
        if downstream:
            parts.append(f"하류설비: {', '.join(downstream)}")

        if parsed["installed"]:
            parts.append(f"설치 구성품: {', '.join(parsed['installed'])}")

        result_lines.append(" | ".join(parts))

    return "\n".join(result_lines)


if __name__ == "__main__":
    import sys

    source = sys.argv[1] if len(sys.argv) > 1 else "data/JSON_example/IS-VZ-DM-04012/IS-VZ-DM-04012.json"
    ids    = sys.argv[2:] if len(sys.argv) > 2 else None

    print("=" * 60)
    print("[LLM용 텍스트]")
    print("=" * 60)
    print(facility_json_to_text(source, target_ids=ids))
    print()
    print("=" * 60)
    print("[검색용 텍스트]")
    print("=" * 60)
    print(facility_json_to_retrieval_text(source, target_ids=ids))
