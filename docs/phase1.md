# 1단계: 하드웨어 확인 (간략판)

목표: 학습 데이터를 모으기 전에 **세 가지만 확인**한다. 전부 합쳐 2시간 안쪽, 추가 구매는 거의 없음.

| 실험 | 확인할 것 | 시간 | 필요한 것 |
|---|---|---|---|
| A. 송출 | 노트북에 영상이 오고 검출 박스가 뜨나, 몇 fps인가 | 30분 | 노트북 핫스팟 |
| B. ToF 높이 | 몇 mm 높이 차이까지 구분하나 | 40분 | 높이가 다른 집 물건 3개, 자 |
| C. 젖은 바닥 | 물 웅덩이가 카메라에 보이나 | 40분 | 장판, 물, 폰 플래시 |

화면 기하(1px이 몇 mm인지)는 B를 하면서 체스보드 사진 한 장으로 같이 잰다.
LED 자동 점멸 회로, 노출 장시간 안정성, 여러 장착 높이·각도 비교는 **필요해질 때(4단계)** 한다.

## 준비 (한 번만)

1. **OpenMV IDE** 설치 → Nicla를 Micro USB(데이터 케이블)로 연결 → 펌웨어 업데이트 제안이 뜨면 진행
2. 노트북에서:
   ```
   git clone https://github.com/SuyongHuh1/nicla-tool
   cd nicla-tool
   py -m pip install -r laptop\requirements.txt
   ```
3. 보드 드라이브(USB로 연결하면 보이는 디스크)에 `nicla\camlib.py`, `nicla\nvproto.py` 복사
4. `nicla\wifi_config_example.py`를 `wifi_config.py`로 복사해 노트북 핫스팟 이름·비밀번호(2.4 GHz)를 적고 보드 드라이브에 복사
5. 안테나를 보드 J6 커넥터에 연결

카메라 위치는 **실제로 달 위치 하나**만 정한다 (차체 위, 또는 비슷한 높이의 상자 위에 테이프로 고정). 각도는 폰 수평계 앱으로 한 번 재서 적어 둔다.

---

## A. 송출 확인 (30분)

1. OpenMV IDE에서 `nicla\stream_server.py`를 열고 *Tools → Save open script to OpenMV Cam (as main.py)* → 보드 리셋
2. IDE 시리얼 터미널에 `stream_server ready: <IP>:5005`가 뜸 (핫스팟의 연결된 기기 목록에서도 IP 확인 가능)
3. IDE를 닫고:
   ```
   py laptop\viewer.py --host <IP> --label wifi --duration 60
   ```
4. 화면 확인: 갈색 물건(초콜릿, 갈색 지우개 등)을 놓으면 분홍 박스가 떠야 함. WASD를 누르면 화면 위 `drive` 값이 바뀌어야 함 (차량 연결 전이라 명령 도착만 확인)

**결과**: 60초 뒤 `results\stream\wifi.json`에 fps와 지연이 저장됨. **8 fps 이상이면 통과.** 박스가 안 뜨면 `stream_server.py`의 `BLOB_LAB` 값을 OpenMV IDE *Tools → Machine Vision → Threshold Editor*로 조정.

## B. ToF 높이 + 화면 크기 (40분)

**화면 크기 먼저 (5분)**
1. `py laptop\calibrate.py board`로 만든 `results\calib\chessboard_9x7_20mm.pdf`를 **실제 크기(100%)**로 인쇄, 바닥에 테이프로 평평하게 붙임
2. 뷰어를 켜고 **C** 키 → `captures\` 폴더에 사진 저장
3. `py laptop\calibrate.py floor captures\<저장된 파일>.jpg`
   → 1px이 몇 mm인지, 바닥이 얼마나 보이는지 출력

**ToF 높이 (35분)**
1. 높이가 다른 납작한 물건 3개를 고른다. 대략 5 / 10 / 20 mm (지우개, 휴대폰 케이스, 책, 동전 더미 등). 가로세로 4 cm 이상인 것. **자로 높이를 재서** 라벨에 그 값을 쓴다
2. OpenMV IDE에서 `nicla\tof_logger.py`를 main.py로 저장 → IDE 닫고 리셋
3. 물건을 카메라 화면 정중앙에 하나씩 놓고:
   ```
   py laptop\capture.py --kind tof --label h00_b40        # 바닥만
   py laptop\capture.py --kind tof --label h06_b40        # 6 mm 물건
   py laptop\capture.py --kind tof --label h11_b40
   py laptop\capture.py --kind tof --label h21_b40
   py laptop\analyze_tof.py --tilt-deg <잰 각도, 수직 아래면 90>
   ```
   라벨 규칙: `h<높이mm>_b<물건 크기mm>`

**결과**: `results\tof\verdict.md`. 가장 작은 높이 차이가 구분되면(d' ≥ 3) **PASS → ToF 높이를 모델 입력으로 사용**. 안 되면 ToF는 빼고 카메라만으로 간다 (라인 레이저 같은 추가 장치는 쓰지 않음).

## C. 젖은 바닥 (40분)

LED 회로 대신 **폰 플래시**를 쓴다. 같은 자리에서 플래시를 켠 사진과 끈 사진을 비교하면, 주변 조명은 두 사진에 똑같이 들어가서 빠지고 플래시가 만든 반사만 남는다.

1. 구매한 장판을 30 cm 정도 잘라 카메라 앞에 깔고, 물 5 g(주방저울)을 붓는다. 노란색을 내고 싶으면 보리차를 쓴다
2. 뷰어를 `--label wood`로 켜 둔 채, 폰 플래시를 카메라 옆에서 바닥을 비스듬히 비추게 들고:
   - 플래시 **켜고 C**, 이어서 **끄고 C** → 터미널에 저장된 파일 이름 두 개가 찍힘 (먼저 것이 켬)
   - 그 사이 카메라·폰 위치가 움직이지 않게 주의
3. 분석 (처음에 마우스로 웅덩이와 마른 바닥을 한 번씩 드래그):
   ```
   py laptop\wet_analyze.py --pair captures\<켬 파일>.jpg captures\<끔 파일>.jpg --label wood_room --select
   ```
4. 같은 방법으로 두 번 더:
   - **실내등 끄고** 한 쌍 (조명이 바뀌어도 보이는지)
   - **물 없이 스텐판이나 PET 필름**을 놓고 한 쌍 (반짝이는 마른 표면을 물로 착각하는지)

**결과**: `results\wet\summary.md`. 플래시 차분(`켬−끔 차분`) d' ≥ 3이 실내등 켬/끔 모두에서 나오고, 스텐판·필름에서는 안 나오면 **2단계에서 액체 데이터도 모은다**. 안 보이면 1차 목표는 분변만으로 좁힌다.

---

## 결과 전달

`results\` 폴더를 git으로 올리거나(`git add results && git commit -m "phase1" && git push`), 이 대화에 연결된 폴더로 알려 주면 판정을 이어서 한다.

## 나중에 필요해지면 (지금은 안 함)

| 항목 | 언제 | 도구 |
|---|---|---|
| LED 자동 점멸 (D0 핀 + MOSFET) | 주행 중 액체 판별을 실제로 넣을 때 | `stream_server.py`의 `ILLUM_PIN`, `viewer.py --illum alt`, `wet_analyze.py <녹화 폴더>` |
| 노출 장시간 안정성 | 데이터 수집 중 밝기가 흔들릴 때 | `exposure_test.py`, `analyze_exposure.py` |
| 렌즈 왜곡 보정 | 면적 계산 오차가 클 때 | `calibrate.py intrinsics` |
| 편광 필름 | 반사 대비가 부족할 때 | — |
