# 1단계: 하드웨어 검증

목표: 학습을 시작하기 전에 **이 하드웨어로 무엇을 잴 수 있는지** 판정한다.
결과에 따라 2단계 데이터 수집 방식(ToF 사용 여부, 장착 위치, 카메라 설정)이 확정된다.

| 작업 | 질문 | 도구 | 판정 기준 |
|---|---|---|---|
| 1-1 환경 | 보드·노트북이 준비됐나 | OpenMV IDE, `pip install` | 모든 스크립트 실행됨 |
| 1-2 장착 기하 | 바닥이 얼마나 보이고 1px이 몇 mm인가 | `viewer.py` + `calibrate.py` | FOMO 칸 1개 ≤ 15 mm |
| 1-3 ToF | 5 mm 높이 차이를 구분하나 | `tof_logger.py` + `capture.py` + `analyze_tof.py` | d' ≥ 3 |
| 1-4 노출 | 조명 고정 시 밝기가 안정적인가 | `exposure_test.py` + `analyze_exposure.py` | 10분 변동 ≤ 5% |
| 1-5 Wi-Fi | 노트북으로 몇 fps, 지연 얼마로 오나 | `stream_server.py` + `viewer.py` | ≥ 8 fps, 지연 p95 ≤ 300 ms |

차량 제어(UART)는 차량 쪽 보드가 정해진 뒤 추가한다. 지금은 명령이 보드까지 도착하는지(ack)만 확인한다.

---

## 1-1. 환경 준비 (한 번만)

1. **OpenMV IDE** 설치 → Nicla 연결 → IDE가 펌웨어 업데이트를 제안하면 진행 (OpenMV 펌웨어가 아니면 여기서 설치됨)
2. 노트북에서:
   ```
   git clone https://github.com/SuyongHuh1/nicla-tool
   cd nicla-tool
   py -m pip install -r laptop\requirements.txt
   py -m pytest -q tests          # 14 passed 이면 정상
   ```
3. 보드 드라이브(USB로 연결하면 보이는 디스크)에 `nicla\camlib.py`, `nicla\nvproto.py` 복사
4. `nicla\wifi_config_example.py`를 `wifi_config.py`로 복사해 핫스팟 이름/비밀번호 입력 후 보드 드라이브에 복사
   - **노트북 모바일 핫스팟(2.4 GHz)** 추천. 학교 Wi-Fi(학번 로그인)는 안 됨
   - 안테나(U.FL)를 보드 J6에 꼭 연결

**스크립트 실행 방법 두 가지**
- 화면만 볼 때: OpenMV IDE에서 열고 ▶ 실행
- `capture.py`로 기록할 때: IDE에서 *Tools → Save open script to OpenMV Cam (as main.py)* → **IDE 종료** → 보드 리셋 버튼. (IDE가 켜져 있으면 COM 포트를 점유함)

## 1-2. 장착 기하 (calibration)

1. 체스보드 인쇄: `py laptop\calibrate.py board` → `results\calib\chessboard_9x7_20mm.pdf`를 **실제 크기(100%)**로 인쇄, 50 mm 막대를 자로 확인
2. 카메라를 실제 장착 위치에 고정. 아래 조합마다 반복 (라벨 예: `floor_h120_t45`)
   - 높이: 실제 장착 높이 1개 + 위아래 1개씩
   - 하향 각도: 2종 (예: 30°, 45°)
3. 체스보드를 카메라 앞 바닥에 평평하게 놓고 `stream_server.py` 실행 → `py laptop\viewer.py --host <IP> --label floor_h120_t45` → **C** 키로 저장
4. `py laptop\calibrate.py floor captures\floor_h120_t45_*.jpg`
   - 출력: 화면 아래/가운데/위의 mm/px, 보이는 바닥 폭·깊이, **FOMO 칸 1개의 실제 크기**
   - `results\calib\floor_*_check.png`에 10 mm 격자가 체스보드와 맞으면 성공
5. (선택) 렌즈 왜곡이 크면: 체스보드를 여러 각도로 15장 찍어 `calibrate.py intrinsics captures\cal_*.jpg` → floor에 `--intrinsics results\calib\intrinsics.json`

**판정**: 분변 크기(지름 20~40 mm)를 생각하면 FOMO 칸 1개가 15 mm 이하여야 검출이 안정적. 넘으면 카메라를 낮추거나 각도를 키움.

## 1-3. ToF 판별력 (핵심 실험)

**준비물**: 높이 5 / 10 / 20 / 30 mm 블록을 두 가지 면적(약 30×30 mm, 60×60 mm)으로. 지우개, 레고, 골판지 적층 등. 바닥과 비슷한 색이면 더 좋음.

**블록 위치**: 카메라 화면 정중앙(ToF는 카메라 옆에서 같은 방향을 봄). viewer에서 ToF 값이 변하는 위치를 먼저 확인.

보드에 `tof_logger.py`를 main.py로 저장한 뒤, 조건마다:
```
py laptop\capture.py --kind tof --label h00_b00_t45            # 바닥만 (기울기마다 1번)
py laptop\capture.py --kind tof --label h05_b30_t45
py laptop\capture.py --kind tof --label h10_b30_t45
py laptop\capture.py --kind tof --label h20_b30_t45
py laptop\capture.py --kind tof --label h30_b30_t45
py laptop\capture.py --kind tof --label h05_b60_t45
...  (b60도 동일)
```
라벨 규칙: `h<높이mm>_b<블록mm>_<태그>`. 태그는 장착 조건(기울기·높이). 같은 태그끼리 비교된다.

분석:
```
py laptop\analyze_tof.py --tilt-deg 45
```
→ `results\tof\verdict.md`, `summary.png`

**판정**
- **PASS**: 5 mm 간격의 모든 쌍에서 d' ≥ 3 → ToF 높이를 모델 B 특징으로 사용
- **조건부**: 60 mm 블록만 통과 → ToF 측정 영역이 작은 물체보다 큼. 근거리 장착 또는 ROI 축소(전체 ST 드라이버 필요) 검토
- **FAIL**: 라인 레이저 삼각측량으로 전환

참고: VL53L1X 시야각은 약 27°. 거리 100 mm에서 측정 영역 지름 약 48 mm, 기울이면 앞뒤로 더 길어짐. `verdict.md`에 조건별 측정 영역 크기가 계산되어 나온다.

## 1-4. 조명·노출 고정

보조 LED를 켠 상태로 `exposure_test.py`를 main.py로 저장:
```
py laptop\capture.py --kind exposure --label lock_led --seconds 600
```
비교용으로 파일 상단 `LOCK = False`로 바꿔 한 번 더 (`--label auto_led`). 주변 조명을 일부러 바꿔 보면(형광등 끄기 등) 차이가 잘 보인다.
```
py laptop\analyze_exposure.py
```
**판정**: LOCK 조건에서 변동 ≤ 5%, 노출값 고정 유지. 실패 시 LED 밝기를 올리고 노출 시간을 짧게 고정.

## 1-5. Wi-Fi 송출

`stream_server.py`를 main.py로 저장 (camlib.py, nvproto.py, wifi_config.py 함께). OpenMV IDE 시리얼 터미널에 `stream_server ready: <IP>:5005`가 표시됨 (핫스팟 연결 기기 목록에서도 확인 가능).

JPEG 품질별로 60초씩:
```
py laptop\viewer.py --host <IP> --label wifi_q30 --jpeg-q 30 --duration 60
py laptop\viewer.py --host <IP> --label wifi_q50 --jpeg-q 50 --duration 60
py laptop\viewer.py --host <IP> --label wifi_q70 --jpeg-q 70 --duration 60
```
→ `results\stream\wifi_q*.json` (fps, 지연 p50/p95, 왕복시간)

화면 확인: 갈색 물체를 놓으면 분홍 박스(데모 색상 검출)가 표시되어야 함. 안 잡히면 OpenMV IDE의 *Tools → Machine Vision → Threshold Editor*로 `BLOB_LAB` 값을 조정.
조종 키(WASD)를 누르면 HUD의 `drive` 값이 바뀌어야 함 (보드까지 명령 도착 확인).

**판정**: 8 fps 이상, 지연 p95 300 ms 이하인 품질 중 가장 높은 값 채택. 미달이면 QQVGA(160×120) 송출 검토.

---

## 결과 전달

`results\` 폴더를 git으로 올리면(`git add results && git commit -m "phase1 results" && git push`) 분석·판정을 이어서 진행한다. 녹화 영상(`recordings\`)은 용량이 커서 git에서 제외되어 있으니 필요하면 Google Drive로.
