# Nicla ↔ 노트북 통신 규약 (v1)

TCP, 보드가 서버(포트 5005), 노트북이 클라이언트. 동시에 한 명만 접속.
구현: `nicla/nvproto.py` (보드·노트북 공용), `laptop/nvlink.py`.

현재 배포 모델은 `background/stool`이다. `urine`/`liquid_stool`, 굳기·높이·실면적 필드는
후속 확장용이며 현재 값이 생성된다는 뜻이 아니다. 표의 단계 번호는 기존 문서의 분류이고,
현재 개발 순서는 [로드맵](roadmap.md)을 따른다.

`drive`/`stop`/`mode`의 ack는 명령 수신 확인이다. 현재 차량 UART 및 자율 주행이
미구현이므로 물리적 동작 완료를 의미하지 않는다.

## 보드 → 노트북: 프레임 메시지

```
"NV01" | uint32 LE 헤더 길이 | uint32 LE JPEG 길이 | 헤더 JSON(UTF-8) | JPEG
```

헤더 필드

| 키 | 의미 |
|---|---|
| `v` | 프로토콜 버전 (1) |
| `seq` | 프레임 번호 |
| `ms` | 촬영 시각 (보드 ms) |
| `w`, `h` | 이미지 크기 |
| `tof_mm` | ToF 거리 (없으면 null) |
| `det` | 검출 목록 (아래) |
| `mode` | manual / assist / auto |
| `vehicle` | 차량 링크 상태 (현재 `not_connected`) |
| `drive` | 마지막으로 받은 주행 명령 [왼쪽, 오른쪽] % |
| `fps`, `q` | 보드 측 fps, JPEG 품질 |
| `cam` | 30프레임마다: 노출 고정 여부, 노출(us), 게인, 화이트밸런스 |
| `mem` | 30프레임마다: 남은 RAM |
| `led` | 이 프레임을 찍을 때 보조 LED가 켜져 있었나 (1/0) |
| `illum` | LED 모드 off / on / alt (LED가 없으면 `none`) |
| `detector` | 실제 활성 검출기 (`tinyml_roi`, `color_demo`, `simulated` 등) |
| `pipeline` | 실제 단계 (`fomo_roi`, `fomo_only`, `color_demo`, `off`) |
| `detector_view` | 요청한 비교 경로 (`fomo` / `color_demo`) |
| `roi_refine`, `roi_refine_active` | ROI 보정 설정 / 현재 실제 적용 여부 |
| `temporal`, `temporal_window`, `temporal_min_hits` | 시간축 필터 설정 |
| `ack` / `pong` / `err` | 명령 응답 (해당 프레임에만) |

검출 항목 (`det`의 원소) — 있는 키만 그린다

| 키 | 단계 | 의미 |
|---|---|---|
| `cls` | 1 | 종류 (`blob` = 데모 색상 검출, 이후 `stool` / `urine` / `liquid_stool`) |
| `bbox` | 1 | [x, y, w, h] 픽셀 |
| `cx`, `cy` | 1 | 중심 |
| `px` | 1 | 픽셀 면적 |
| `fomo_bbox` | 2 | FOMO 후처리가 돌려준 중심 셀 주변 박스 |
| `roi` | 2 | 클래스별 영역 정제를 시도한 ROI |
| `source` | 2 | 1차 검출 출처 (`fomo`, `lab_demo`) |
| `region_source` | 2 | 최종 bbox 출처 (`lab`, `fomo_roi`, 이후 `led_diff`/`segmentation`) |
| `refined` | 2 | ROI 안에서 실제 영역을 찾았는지 여부 |
| `conf` | 2 | 1차 검출 신뢰도 0~1 |
| `grade` | 4 | 굳기 0=단단 1=정상 2=무름 3=물변 |
| `area_mm2` | 4 | 바닥 기준 실제 면적 |
| `height_mm` | 4 | ToF 기반 높이 |
| `contour` | 4 | 외곽선 [[x,y], ...] |

## 노트북 → 보드: 명령

JSON 한 줄 + `\n`. 모든 명령에 `seq`.

| 명령 | 예 | 동작 |
|---|---|---|
| ping | `{"t":"ping","seq":1}` | `pong: {seq, bt(보드 ms)}` 응답 → 왕복시간·시계 보정 |
| drive | `{"t":"drive","l":50,"r":50,"seq":2}` | 좌우 바퀴 −100~100 %. 뷰어는 키를 누르는 동안 10 Hz로 반복 송신 |
| stop | `{"t":"stop","seq":3}` | 정지 |
| mode | `{"t":"mode","m":"assist","seq":4}` | 모드 변경 |
| set | `{"t":"set","key":"jpeg_q","val":40,"seq":5}` | `jpeg_q`, `tof_every`, `blobs`, `illum`(off/on/alt), `settle`(0~3), `roi_refine`, `temporal`, `detector_view`(fomo/color_demo) 변경 |

## 차량 연결 (미정 — 차량 팀 코드 확정 후)

보드의 `vehicle_send(left, right)` 한 곳에만 코드를 넣으면 된다. 제안 형식(UART, 텍스트 한 줄):
`M,<left>,<right>\n`, `S\n`. 차량 쪽은 0.5초간 명령이 없으면 스스로 정지(워치독).
노트북 연결이 끊기면 보드가 `vehicle_stop()`을 호출하지만 현재는 상태만 갱신한다.
실제 정지를 위해 차량 UART와 차량 측 워치독 구현이 필요하다.

⚠ Nicla 헤더 핀은 3.3 V. 5 V 아두이노(우노 등)와 연결하면 레벨 시프터 필요.
