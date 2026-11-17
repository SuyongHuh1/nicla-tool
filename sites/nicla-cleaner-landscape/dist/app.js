const targets = {
  "S-01": {
    type: "stool", name: "분변 #1", icon: "S1", tag: "우선 대상",
    confidenceLabel: "모델 신뢰도", confidence: 91,
    position: "왼쪽 42mm · 앞 183mm", size: "68 × 35mm", stability: "5/5 프레임",
    priority: "1순위 이동 계획", planTitle: "분변 #1 중심 정렬", turn: "↺ 8°", drive: "↑ 183mm", clean: "롤러 1회",
    nextAction: "좌회전 8°", strategy: "중심을 롤러 폭에 맞춘 뒤 직선 접근하여 수거합니다.", routeLegend: "1순위 접근 · 이후 #2"
  },
  "S-02": {
    type: "stool", name: "분변 #2", icon: "S2", tag: "대기 대상",
    confidenceLabel: "모델 신뢰도", confidence: 87,
    position: "오른쪽 65mm · 앞 224mm", size: "51 × 29mm", stability: "4/5 프레임",
    priority: "2순위 이동 계획", planTitle: "분변 #2 중심 정렬", turn: "↻ 12°", drive: "↑ 224mm", clean: "롤러 1회",
    nextAction: "우회전 12°", strategy: "1번 처리 후 재탐색하고, 가장 짧은 안전 경로로 접근합니다.", routeLegend: "2순위 접근 경로"
  },
  "U-01": {
    type: "urine", name: "소변 후보", icon: "U?", tag: "학습 데이터 필요",
    confidenceLabel: "영역 후보 점수", confidence: 64,
    position: "오른쪽 118mm · 앞 146mm", size: "92 × 46mm", stability: "3/5 프레임",
    priority: "3순위 · 학습 전 전략 예시", planTitle: "넓은 영역 지그재그 청소", turn: "↻ 영역 진입", drive: "3개 레인", clean: "2회 왕복",
    nextAction: "우측부터 3열", strategy: "영역 폭을 3개 레인으로 나눠 25% 겹치며 왕복합니다.", routeLegend: "소변 영역 · 3열 왕복"
  }
};

const phases = [
  { key: "align", title: "분변 2개 감지됨", badge: "대상 확인", action: "대상 정렬 시작", target: "S-01" },
  { key: "collect", title: "분변 #1 정렬 중", badge: "접근 중", action: "롤러 수거 시작", target: "S-01" },
  { key: "verify", title: "분변 #1 수거 중", badge: "롤러 작동", action: "수거 결과 확인", target: "S-01" },
  { key: "complete", title: "분변 #1 처리 완료", badge: "재확인 완료", action: "다음 대상 선택", target: "S-02" },
  { key: "align", title: "분변 1개 남음", badge: "다음 대상", action: "분변 #2 정렬 시작", target: "S-02" }
];

let phaseIndex = 0;
let selectedTarget = "S-01";
let completed = 0;
let toastTimer;

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 1400);
}

function selectTarget(id) {
  const target = targets[id];
  if (!target) return;
  selectedTarget = id;

  $$(".detection").forEach(el => el.classList.toggle("selected", el.dataset.target === id));
  $$(".priority-item").forEach(el => el.classList.toggle("active", el.dataset.target === id));
  $("#stageTarget").textContent = target.name;
  $("#stagePosition").textContent = target.position.replace(" · ", " · ");
  $("#stageStability").textContent = target.nextAction;
  $("#planPriority").textContent = target.priority;
  $("#planTitle").textContent = target.planTitle;
  $("#planConfidence").textContent = target.type === "urine" ? "후보" : `${target.confidence}%`;
  $("#planTurn").textContent = target.turn;
  $("#planDrive").textContent = target.drive;
  $("#planClean").textContent = target.clean;
  $("#planStrategy").textContent = target.strategy;
  $("#routeLegend").textContent = target.routeLegend;
  $("#motionCard").classList.toggle("urine-plan", target.type === "urine");
  $("#cameraStage").dataset.target = id;
}

function updatePhase() {
  const phase = phases[phaseIndex];
  $("#statusTitle").textContent = phase.title;
  $("#statusBadge").textContent = phase.badge;
  $("#actionLabel").textContent = phase.action;

  if (phase.key === "complete") {
    completed = 1;
    $("#doneCount").textContent = "1";
    $("#stoolCount").textContent = "1";
  }

  const firstTargetComplete = phaseIndex >= 3;
  const firstDetection = document.querySelector('.detection[data-target="S-01"]');
  const firstPriority = document.querySelector('.priority-item[data-target="S-01"]');
  firstDetection.classList.toggle("processed", firstTargetComplete);
  firstPriority.classList.toggle("completed", firstTargetComplete);
  firstPriority.querySelector("i").textContent = firstTargetComplete ? "✓" : "1";

  const order = ["search", "align", "collect", "verify"];
  let activeIndex = order.indexOf(phase.key);
  if (phase.key === "complete") activeIndex = order.length;
  $$(".progress-steps li").forEach((item, index) => {
    item.classList.toggle("done", index < activeIndex);
    item.classList.toggle("active", index === activeIndex);
    const circle = item.querySelector("i");
    circle.textContent = index < activeIndex ? "✓" : String(index + 1);
  });
  selectTarget(phase.target);
}

function openSheet(id) {
  $$(".side-sheet").forEach(sheet => {
    const open = sheet.id === id;
    sheet.classList.toggle("open", open);
    sheet.setAttribute("aria-hidden", String(!open));
  });
  $("#sheetBackdrop").classList.add("visible");
}

function closeSheets() {
  $$(".side-sheet").forEach(sheet => {
    sheet.classList.remove("open");
    sheet.setAttribute("aria-hidden", "true");
  });
  $("#sheetBackdrop").classList.remove("visible");
  $$(".nav-button").forEach(button => button.classList.toggle("active", button.dataset.view === "home"));
}

function setLayer(layer, enabled) {
  const stage = $("#cameraStage");
  if (layer === "raw") {
    stage.classList.toggle("raw-view", enabled);
    if (enabled) {
      $$(".layer-switch button:not([data-layer='raw'])").forEach(button => button.classList.remove("active"));
    }
  }
  if (layer === "fomo") stage.classList.toggle("hide-fomo", !enabled);
  if (layer === "roi") stage.classList.toggle("hide-roi", !enabled);
}

$$('.detection').forEach(button => button.addEventListener('click', () => selectTarget(button.dataset.target)));
$$('.priority-item').forEach(button => button.addEventListener('click', () => selectTarget(button.dataset.target)));

$$('.layer-switch button').forEach(button => {
  button.addEventListener('click', () => {
    const layer = button.dataset.layer;
    if (layer === 'raw') {
      const turnOn = !button.classList.contains('active');
      $$('.layer-switch button').forEach(item => item.classList.toggle('active', item === button && turnOn));
      setLayer('raw', turnOn);
      if (!turnOn) {
        document.querySelector('[data-layer="fomo"]').classList.add('active');
        document.querySelector('[data-layer="roi"]').classList.add('active');
        setLayer('fomo', true); setLayer('roi', true);
      }
      return;
    }
    $("#cameraStage").classList.remove("raw-view");
    document.querySelector('[data-layer="raw"]').classList.remove('active');
    button.classList.toggle('active');
    setLayer(layer, button.classList.contains('active'));
  });
});

$("#primaryAction").addEventListener("click", () => {
  phaseIndex = (phaseIndex + 1) % phases.length;
  if (phaseIndex === 0) {
    completed = 0;
    $("#doneCount").textContent = "0";
    $("#stoolCount").textContent = "2";
  }
  updatePhase();
});

$("#captureButton").addEventListener("click", () => showToast("현재 화면을 저장했습니다 · 데모"));
$("#remoteButton").addEventListener("click", () => openSheet("remoteSheet"));
$("#sheetBackdrop").addEventListener("click", closeSheets);
$$('[data-close-sheet]').forEach(button => button.addEventListener('click', closeSheets));

$$('.nav-button').forEach(button => {
  button.addEventListener('click', () => {
    $$('.nav-button').forEach(item => item.classList.toggle('active', item === button));
    if (button.dataset.view === 'home') closeSheets();
    if (button.dataset.view === 'history') openSheet('historySheet');
    if (button.dataset.view === 'diagnostics') openSheet('diagnosticsSheet');
  });
});

$("#emergencyButton").addEventListener("click", () => {
  $("#stopOverlay").classList.add("visible");
  $("#stopOverlay").setAttribute("aria-hidden", "false");
});
$("#resumeButton").addEventListener("click", () => {
  $("#stopOverlay").classList.remove("visible");
  $("#stopOverlay").setAttribute("aria-hidden", "true");
  showToast("안전 정지를 해제했습니다 · 데모");
});

$("#speedRange").addEventListener("input", event => $("#speedValue").textContent = `${event.target.value}%`);
$("#rollerButton").addEventListener("click", event => {
  event.currentTarget.classList.toggle("active");
  showToast(event.currentTarget.classList.contains("active") ? "롤러 시험 시작 · 데모" : "롤러 시험 정지");
});
$$('[data-drive]').forEach(button => {
  const message = {forward:'전진', back:'후진', left:'좌회전', right:'우회전', stop:'정지'}[button.dataset.drive];
  button.addEventListener('pointerdown', () => showToast(`${message} 명령 · 데모`));
  if (button.dataset.drive !== 'stop') button.addEventListener('pointerup', () => showToast('손을 떼어 정지했습니다'));
});

$("#roiToggle").addEventListener("change", event => {
  document.querySelector('[data-layer="roi"]').classList.toggle('active', event.target.checked);
  setLayer('roi', event.target.checked);
  $("#pipelineName").textContent = event.target.checked ? "FOMO → ROI" : "FOMO only";
});
$("#fomoToggle").addEventListener("change", event => {
  document.querySelector('[data-layer="fomo"]').classList.toggle('active', event.target.checked);
  setLayer('fomo', event.target.checked);
});
$("#temporalToggle").addEventListener("change", event => showToast(event.target.checked ? "3/5 프레임 필터 켜짐" : "시간축 필터 꺼짐"));

$$('.count-item[data-filter]').forEach(item => item.addEventListener('click', () => {
  $$('.count-item[data-filter]').forEach(other => other.classList.toggle('active', other === item));
  selectTarget(item.dataset.filter === 'stool' ? (completed ? 'S-02' : 'S-01') : 'U-01');
}));

updatePhase();

if ('serviceWorker' in navigator && location.protocol === 'https:') {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}
