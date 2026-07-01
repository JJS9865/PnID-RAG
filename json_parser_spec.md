# json_parser.py 명세서

`src/services/json_parser.py` + `src/services/pid_translations.py`

P&ID JSON 데이터를 파싱하여 LLM 프롬프트용 또는 검색(임베딩)용 한국어 텍스트로 변환한다.

---

## 파일 구성

| 파일 | 역할 |
|------|------|
| `json_parser.py` | 파싱 로직, 흐름 추적, 공개 API |
| `pid_translations.py` | 영→한 번역 테이블, 번역 함수 |

번역 테이블을 별도 파일로 분리하여,
신규 설비 타입 추가나 구성품 패턴 수정 시 `pid_translations.py`만 편집하면 된다.

---

## 실행 방법

### 코드에서 사용

```python
from src.services.json_parser import facility_json_to_text, facility_json_to_retrieval_text

# 입력 형식은 3가지 모두 가능
facility_json_to_text(pid_dict)               # dict
facility_json_to_text("path/to/pid.json")     # 파일 경로 (str / Path)
facility_json_to_text('{"equipment_list": ...}')  # JSON 문자열

# target_ids로 특정 설비만 추출 (None이면 전체, 두 함수 모두 지원)
facility_json_to_text(pid_dict, target_ids=["D-0410"])
facility_json_to_retrieval_text(pid_dict, target_ids=["D-0410", "P-0410A"])
```

### 커맨드라인 테스트

```bash
# 내장 샘플 실행 (IS-VZ-DM-04012.json)
python src/services/json_parser.py

# 파일 직접 지정
python src/services/json_parser.py data/JSON_example/IS-VZ-DM-04012/IS-VZ-DM-04012.json

# 설비 ID 필터
python src/services/json_parser.py data/JSON_example/IS-VZ-DM-04012/IS-VZ-DM-04012.json D-0410
```

---

## 함수 설명

### `facility_json_to_text(facility_info, target_ids=None)`

**용도**: LLM 프롬프트에 삽입하는 설비 설명 텍스트 생성

- 설비별 블록 구조로 출력 (`■ [설비ID] 설비명`)
- 설비 사양: spec 키를 한국어로 번역, `unknown`(도면 코드번호) 제외
- 유입/유출 흐름: 배관 체인 추적 + 구성품 한국어 번역
- 연결 끝점: JSON 내 다른 설비이면 `설비명(설비ID)` 형식, 외부 시스템이면 원문
- 설치 구성품: 연결 배관에서 안전 관련 구성품 자동 수집

### `facility_json_to_retrieval_text(facility_info, target_ids=None)`

**용도**: 벡터 검색(임베딩) 및 BM25 키워드 검색에 사용할 압축 텍스트 생성

- 설비당 1줄, `|` 구분자로 핵심 정보 압축
- 설비명·사양값·상류/하류 설비·설치 구성품 모두 포함

---

## pid_translations.py 관리 방법

### 설비 타입 (`EQUIP_TYPE_KO`)

영문 `equip_type` → 한국어 매핑. 매핑 없는 값은 원문 그대로 출력.

```python
EQUIP_TYPE_KO = {
    "TANK": "탱크",  "PUMP": "펌프",  "FILTER": "필터",  ...
}
```

### spec 키 (`SPEC_KEY_KO`)

영문 spec 키 → 한국어 라벨. `None`으로 설정하면 출력에서 완전 제외.

```python
SPEC_KEY_KO = {
    "unknown":  None,    # 도면 코드번호 — 제외
    "dp":       "설계압력",
    "dt":       "설계온도",
    "matl":     "재질",  ...
}
```

### 배관 구성품 (`translate_component` 함수)

규칙 기반 번역. 새 구성품 패턴은 함수 내 조건문에 추가한다.

```
FULL BORE BALL VALVE  →  볼밸브
CHECK, CLOSING ...    →  체크밸브
Y-STRAINER ST-01204   →  Y형 스트레이너
REDUCER 4X3           →  레듀서 4X3
```

레듀서·플랜지 등 단순 배관 피팅은 흐름 표현에는 나타나지만,
설치 구성품 집계에서는 제외된다 (`VALVE` 타입 + `STRAINER` 포함 항목만 집계).

---

## 미설치 구성품 판단 — LLM 위임

파서는 **현재 설치된 구성품**만 수집하며, "어떤 구성품이 있어야 하는가"는 판단하지 않는다.

미설치 구성품 판단은 LLM에게 위임한다.

- `facility_json_to_text()`가 설비별 설치 구성품을 명시한 텍스트를 LLM 프롬프트에 삽입
- LLM은 화공 도메인 지식을 바탕으로, **해당 설비 타입에 원래 있어야 할 구성품** 중 현재 없는 것을 스스로 추론

예시:
```
■ [P-0410A] 펌프
  설치 구성품 : 볼밸브, Y형 스트레이너, 체크밸브
```
→ LLM이 "펌프 출구에 체크밸브가 설치되어 있으므로 역류 방지는 충족됨" 또는
  "흡입 측 안전밸브 없음 — 과압 시나리오에서 위험" 등을 판단.

이 방식의 장점:
- 설비 타입별 기대 구성품 목록을 하드코딩할 필요 없음
- LLM의 화공 도메인 지식을 직접 활용하므로 더 유연한 판단 가능
- 동일 설비라도 공정 맥락(취급 물질, 압력 조건 등)에 따라 다른 판단 가능

---

## 출력 예시

입력 파일: `data/JSON_example/IS-VZ-DM-04012/IS-VZ-DM-04012.json`

```
설비: D-0410 (TANK), P-0410A (PUMP), F-0410 (FILTER)
배관: LO-00008 → D-0410 → P-0410A → F-0410 → LO-12036
```

---

### `facility_json_to_text` — 전체

```
■ [D-0410] 탱크
  설비 사양 : 형식: VERTICAL, 용량: 55.842 m3, 크기: 3,000 ID x 6,900 TL mm, 설계압력: 5 / FV barg, 설계온도: 270 °C, 재질: SS 304
  유입 흐름 : LO-00008 → [레듀서 4X3] → 설비 입구
  유출 흐름 : 설비 출구 → [볼밸브, 볼밸브, 볼밸브, Y형 스트레이너, 레듀서 3X1] → 펌프(P-0410A)
  설치 구성품 : 볼밸브, Y형 스트레이너

■ [P-0410A] 펌프
  설비 사양 : 형식: ROTARY GEAR, 용량: 2.2 m3/h, 차압: 3.25 bar, 재질(케이싱/임펠러): SS 304 / SS316, 동력: 1.5 kW
  유입 흐름 : 탱크(D-0410) → [볼밸브, 볼밸브, 볼밸브, Y형 스트레이너, 레듀서 3X1] → 설비 입구
  유출 흐름 : 설비 출구 → [레듀서 2X1, 체크밸브, 볼밸브, 볼밸브] → 필터(F-0410)
  설치 구성품 : 볼밸브, Y형 스트레이너, 체크밸브

■ [F-0410] 필터
  설비 사양 : 형식: CARTRIDGE (Mesh size 5㎛), 유량: 1,923 kg/h, 설계압력: 7 barg, 설계온도: 270 °C, 재질(케이싱/메쉬): SS 304 / SS 316L
  유입 흐름 : 펌프(P-0410A) → [레듀서 2X1, 체크밸브, 볼밸브, 볼밸브] → 설비 입구
  유출 흐름 : 설비 출구 → [볼밸브] → LO-12036
  설치 구성품 : 체크밸브, 볼밸브
```

---

### `facility_json_to_text` — `target_ids=["D-0410"]`

```
■ [D-0410] 탱크
  설비 사양 : 형식: VERTICAL, 용량: 55.842 m3, 크기: 3,000 ID x 6,900 TL mm, 설계압력: 5 / FV barg, 설계온도: 270 °C, 재질: SS 304
  유입 흐름 : LO-00008 → [레듀서 4X3] → 설비 입구
  유출 흐름 : 설비 출구 → [볼밸브, 볼밸브, 볼밸브, Y형 스트레이너, 레듀서 3X1] → 펌프(P-0410A)
  설치 구성품 : 볼밸브, Y형 스트레이너
```

> `target_ids`로 필터링해도 연결 끝점(`펌프(P-0410A)`)은 전체 설비 맵 기준으로 표시된다.

---

### `facility_json_to_retrieval_text` — 전체

```
D-0410 탱크 | 형식: VERTICAL | 용량: 55.842 m3 | 크기: 3,000 ID x 6,900 TL mm | 설계압력: 5 / FV barg | 설계온도: 270 °C | 재질: SS 304 | 상류설비: LO-00008 | 하류설비: 펌프(P-0410A) | 설치 구성품: 볼밸브, Y형 스트레이너
P-0410A 펌프 | 형식: ROTARY GEAR | 용량: 2.2 m3/h | 차압: 3.25 bar | 재질(케이싱/임펠러): SS 304 / SS316 | 동력: 1.5 kW | 상류설비: 탱크(D-0410) | 하류설비: 필터(F-0410) | 설치 구성품: 볼밸브, Y형 스트레이너, 체크밸브
F-0410 필터 | 형식: CARTRIDGE (Mesh size 5㎛) | 유량: 1,923 kg/h | 설계압력: 7 barg | 설계온도: 270 °C | 재질(케이싱/메쉬): SS 304 / SS 316L | 상류설비: 펌프(P-0410A) | 하류설비: LO-12036 | 설치 구성품: 체크밸브, 볼밸브
```

### `facility_json_to_retrieval_text` — `target_ids=["D-0410"]`

```
D-0410 탱크 | 형식: VERTICAL | 용량: 55.842 m3 | 크기: 3,000 ID x 6,900 TL mm | 설계압력: 5 / FV barg | 설계온도: 270 °C | 재질: SS 304 | 상류설비: LO-00008 | 하류설비: 펌프(P-0410A) | 설치 구성품: 볼밸브, Y형 스트레이너
```
