# TinyML 중심 검출 + ROI 영역 추정

## 현재 브랜치의 실행 구조

```text
Nicla QVGA 프레임
        |
        v
FOMO: stool / urine 중심과 신뢰도
        |
        +-- stool -> 중심 ROI -> LAB blob -> 여유 폭을 더한 청소 bbox
        |
        +-- urine -> 중심 ROI -> 우선 ROI만 표시
                                 (LED 차분 실험 통과 후 영역 bbox로 교체)
```

`nicla/detection_config.py`가 모델 경로, 신뢰도, ROI 크기와 LAB 임계값을
관리한다. 기본 `DETECTOR_MODE="auto"`는 모델이 없으면 기존 색상 데모로
폴백한다. 모델을 설치하고 보드에서 확인한 뒤에는 `"tinyml_roi"`로 바꿔
모델 로드 실패를 숨기지 않게 한다.

최신 OpenMV 계열에서는 `ml.Model(..., postprocess=Fomo(...))`를 사용하고,
구형 펌웨어에서는 `tf.load(...).detect()`를 사용한다. `tinyml_roi.py`는 두
API를 모두 시도한다. 새 모델로 작업할 때는 최신 OpenMV 펌웨어를 우선
사용하고 실제 Nicla에서 메모리와 FPS를 다시 측정한다.

## 수집 전에 고정할 조건

데이터는 반드시 실제 로봇 전면 장착 위치에서 수집한다.

- 카메라 높이, 하향 각도, 좌우 방향, QVGA 해상도
- 롤러 폭과 카메라에서 롤러까지의 거리
- 노출·게인·화이트밸런스 고정 방식
- 바닥 종류와 LED 위치
- 각 녹화의 조명, 바닥, 모사체 종류, 거리 구간을 세션 이름에 기록

장착 위치가 바뀐 데이터는 같은 세션으로 섞지 않는다. 바닥 좌표 변환은
`calibrate.py floor`의 homography 결과를 사용하고, 높이가 있는 분변에는
보정 오차를 고려한 청소 여유 폭을 둔다.

## 첫 FOMO 데이터 수집안

아래 수량은 데모 가능성을 확인하기 위한 시작점이지 정확도를 보장하는
기준은 아니다.

| 종류 | 초기 목표 | 반드시 포함할 변화 |
|---|---:|---|
| 분변 모사체 양성 | 150~300장 | 형태, 크기, 방향, 근·중·원거리, 부분 가림 |
| 소변/보리차 양성 | 150~300장 | 양, 퍼짐, 바닥 2종 이상, LED 켬 프레임, 조명 변화 |
| 배경·강한 음성 | 200~300장 | 손, 갈색 생활용품, 그림자, 전선, 마른 반사체, 빈 바닥 |

- 한 프레임에 분변과 손 또는 갈색 물체가 같이 있어도 분변만 라벨링한다.
- FOMO 박스는 픽셀 단위 외곽선이 아니라 객체 전체를 일관되게 포함하는
  박스로 그린다. FOMO 출력은 최종적으로 중심 위치가 핵심이다.
- 소변은 LED 켬 상태에서만 시각적 단서가 안정적이라면 학습·추론 조건도
  LED 켬 프레임으로 통일한다. LED 끔 프레임은 차분용 짝으로 보존한다.
- 연속 프레임 대신 위치나 조건이 달라진 프레임을 우선 선택한다.
- train/validation/test는 프레임이 아니라 녹화 세션 단위로 70/15/15 분리한다.

녹화 예:

```powershell
py laptop\viewer.py --host <NICLA_IP> --record --label stool_wood_near_room `
  --target stool --floor wood_a --lighting room_on `
  --camera-height-mm 120 --camera-tilt-deg 45 --mount-id front_mount_v1
py laptop\viewer.py --host <NICLA_IP> --illum alt --record --label urine_wood_mid_room `
  --target urine --floor wood_a --lighting room_on `
  --camera-height-mm 120 --camera-tilt-deg 45 --mount-id front_mount_v1
```

이 옵션들은 녹화 폴더의 `session.json`에 저장되고 데이터셋 manifest까지
전달된다. 수동으로 기록할 때는 `datasets/session.example.json`을 복사해
같은 필드를 사용한다.

기존 색상 박스를 분변 라벨 초안으로 내보내는 예:

```powershell
py laptop\prepare_fomo_dataset.py recordings\<세션> --blob-class stool --every 5
```

생성된 `datasets/fomo/manifest.jsonl`의 박스에는 항상
`reviewed:false`가 붙는다. 손·그림자·갈색 물체 오탐을 삭제하고 누락된
분변·소변 박스를 추가한 뒤에만 학습에 사용한다.

## 색상/차분만으로 충분한지 판단하는 게이트

아래 값은 이 프로젝트의 초기 진행 기준이다. 학습 표준이나 보편적 보장
수치가 아니라, 별도 세그멘테이션 비용을 지불할지 결정하기 위한 기준이다.

### 분변 ROI-LAB

학습에 쓰지 않은 50장 이상의 세션 분리 테스트에서 다음을 모두 만족하면
세그멘테이션 없이 진행한다.

- FOMO 중심이 맞는 경우 ROI 안에서 LAB blob을 찾는 비율 90% 이상
- 여유 폭을 적용한 bbox가 사람이 표시한 실제 영역의 90% 이상을 포함
- 손·갈색 생활용품·그림자 테스트의 잘못된 영역 선택률 5% 이하
- 근·중·원거리와 각 바닥/조명 조건 중 하나라도 지속적으로 실패하지 않음

색이 여러 조각으로 끊기거나, 중심 근처의 다른 갈색 물체를 자주 선택하거나,
실제 청소 영역을 반복해서 작게 잡으면 분변 ROI 마스크를 수집한다.

### 소변 LED 차분

각 바닥·조명 조건에서 다음을 모두 만족하면 별도 세그멘테이션 모델 대신
LED 켬/끔 차분 blob을 사용한다.

- 젖은 영역과 마른 영역의 차분 분리도 `d' >= 3`
- 여유 폭 bbox가 사람이 표시한 액체 영역의 85% 이상을 포함
- 스텐판·PET·광택 장판 같은 마른 반사체 오탐률 5% 이하
- LED 켬/끔 프레임 정렬 실패 경고가 반복되지 않음

투명 액체가 보이지 않거나, 마른 광택과 구별되지 않거나, puddle이 여러
조각으로 분리돼 롤러 경로를 못 덮으면 소변 ROI 세그멘테이션으로 전환한다.

## 세그멘테이션이 필요해진 경우

처음부터 전체 QVGA 프레임을 픽셀 라벨링하지 않는다. 실패한 클래스의 FOMO
중심 주변 ROI만 저장해 마스크를 만든다.

- 먼저 실패 조건별 100~200 ROI 마스크로 작은 실험을 한다.
- 분변과 소변 마스크를 별도 클래스로 두고, 경계가 불분명한 반사·그림자는
  억지로 양성에 포함하지 않는다.
- 동일 장면의 연속 프레임은 같은 split에 둔다.
- 평가는 픽셀 IoU뿐 아니라 여유 폭 bbox가 실제 롤러 경로를 덮는지도 본다.

세그멘테이션은 FOMO를 대체하는 것이 아니라, FOMO가 고른 작은 ROI의 영역
추정기만 대체한다. 이 방식이 Nicla Vision의 메모리와 연산량을 제한한다.

## 보드 배포 체크

1. `main.py`, `camlib.py`, `nvproto.py`, `tinyml_roi.py`,
   `detection_config.py`, `labels.txt`, `wifi_config.py`를 보드에 둔다.
2. 모델을 `fomo_stool_urine.tflite`로 복사하거나 펌웨어에 내장한다.
3. `DETECTOR_MODE="tinyml_roi"`로 바꾼다.
4. 시리얼의 `# detector`와 뷰어 HUD가 `tinyml_roi`인지 확인한다.
5. 실제 보드의 FPS, `mem` 값, 중심 오차, ROI bbox 커버리지를 기록한다.

