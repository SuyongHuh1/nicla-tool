# nicla-tool

Arduino Nicla Vision으로 바닥의 분변을 찾아 굳기(점성)를 판별하고, 오줌 같은 액체도 찾아서 노트북 화면에 표시하며 원격 조종까지 하는 프로젝트.

![viewer](docs/viewer_preview.png)
*노트북 뷰어 화면 예시. **실제 카메라 영상이 아니라 시뮬레이터가 그린 합성 이미지**입니다. 분홍 박스는 1단계 데모 색상 검출(학습 모델 아님)을 그 합성 이미지에 돌린 결과이고, 주황 박스는 4단계 굳기 판정이 어떻게 표시될지 보여 주려고 값을 직접 넣은 예시입니다.*

## 구조

```
노트북 (viewer.py)  ◄── Wi-Fi: 영상 + 인식 결과 ──  Nicla Vision (stream_server.py)
                    ──  조종 명령 ──────────────►        │ (예정) UART
                                                        ▼
                                                    차량 아두이노
```

| 폴더 | 내용 |
|---|---|
| `nicla/` | 보드용 MicroPython (OpenMV 펌웨어). 신·구 카메라 API 모두 지원 |
| `laptop/` | 노트북용 Python: 측정 기록, 분석, 캘리브레이션, 뷰어, 보드 시뮬레이터 |
| `tests/` | 보드 모듈을 흉내 내 보드 스크립트까지 PC에서 검증하는 테스트 |
| `docs/` | [1단계 실험 절차](docs/phase1.md), [인식 구조](docs/architecture.md), [통신 규약](docs/protocol.md) |
| `results/` | 측정 결과 (git에 올림) |

## 빠른 시작 (보드 없이)

```
py -m pip install -r laptop\requirements.txt
py laptop\fake_nicla.py                      # 창 1: 가짜 보드
py laptop\viewer.py --host 127.0.0.1         # 창 2: 뷰어
```

## 진행 단계

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 하드웨어 확인 (간략판, 약 2시간): 송출, ToF 높이, 젖은 바닥 | **진행 중** → [docs/phase1.md](docs/phase1.md) |
| 2 | 모사체 데이터 수집 (뷰어 녹화 기능 사용) | |
| 3 | 학습: FOMO 검출(분변/액체) + MobileNetV2 굳기 분류(+ToF 특징), 액체는 LED 차분 → [구조](docs/architecture.md) | |
| 4 | 보드 배포, 인식 결과 오버레이, 자율 정지 | |
| 5 | 실환경 평가 (정확도, 종단 지연, 정지 거리) | |

차량 제어는 차량 쪽 코드가 정해지면 `nicla/stream_server.py`의 `vehicle_send()`에 연결한다.
