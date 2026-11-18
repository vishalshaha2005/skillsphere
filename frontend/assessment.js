const app = document.querySelector("#assessment-app");
const themeToggle = document.querySelector("#theme-toggle");
const monitor = document.querySelector("#assessment-monitor");
const cameraVideo = document.querySelector("#assessment-camera");
const recIndicator = document.querySelector("#recording-active-indicator");
const warningCount = document.querySelector("#assessment-warning-count");
const monitorMessage = document.querySelector("#assessment-monitor-message");
const alertBox = document.querySelector("#assessment-alert");
const token = new URLSearchParams(location.search).get("token") || "";
const API = "/api/assessments";
const storageKey = `skillsphere-assessment:${token}`;
let assessment = null;
let questions = [];
let answers = [];
let current = 0;
let deadline = 0;
let timer = 0;
let saveTimer = 0;
let savePromise = Promise.resolve();
let submitting = false;
let cameraStream = null;
let mediaRecorder = null;
let recordedChunks = [];
let recordingStartTime = 0;
let recordingDurationSeconds = 0;
let consentChecked = false;
let faceDetector = null;
let faceDetectorType = "none";
let faceCheckTimer = 0;
let noFaceSince = 0;
let faceWarningSent = false;
let faceCheckRunning = false;
let faceMissingWarningSeconds = 10;
let maxWarnings = 3;
let eventSaveFailureShown = false;
let alertTimer = 0;
let pageHidden = false;

const themeIcons = {
  sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg>',
  moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13z"/></svg>'
};

function updateThemeToggle() {
  const theme = window.SkillSphereTheme.get();
  const nextTheme = theme === "dark" ? "light" : "dark";
  themeToggle.innerHTML = themeIcons[nextTheme === "dark" ? "moon" : "sun"];
  themeToggle.setAttribute("aria-label", `Switch to ${nextTheme} mode`);
  themeToggle.title = `Switch to ${nextTheme} mode`;
  themeToggle.setAttribute("aria-pressed", String(theme === "dark"));
}

themeToggle.addEventListener("click", () => {
  window.SkillSphereTheme.toggle();
  updateThemeToggle();
});
window.addEventListener("storage", event => {
  if (event.key === "skillsphere_theme") updateThemeToggle();
});
updateThemeToggle();

function node(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function formatDetail(detail, fallback = "Request failed") {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map(item => (typeof item === "object" && item !== null ? item.msg || JSON.stringify(item) : String(item))).join("; ");
  }
  return fallback;
}

async function request(path, options = {}) {
  const response = await fetch(`${API}/${encodeURIComponent(token)}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) }
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatDetail(result.detail, `Request failed (${response.status})`));
  return result;
}

function showError(message) {
  stopCamera();
  monitor.hidden = true;
  app.replaceChildren();
  app.append(node("p", "assessment-kicker", "Assessment unavailable"));
  app.append(node("h1", "", "We couldn't open this test"));
  app.append(node("p", "assessment-error", message));
  app.append(node("p", "assessment-copy", "Check that you are using the original invitation link. Contact the hiring team if you need help."));
}

function dateLabel(value) {
  return new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function renderWelcome(errorMessage = "") {
  app.replaceChildren();
  app.append(node("p", "assessment-kicker", "SkillSphere · candidate assessment"));
  app.append(node("h1", "", assessment.assessment_name));
  app.append(node("p", "assessment-copy", `This independent assessment is for ${assessment.job_title} at ${assessment.company}. Answer all 20 questions without assistance. The test is timed and can only be submitted once.`));
  const facts = node("div", "assessment-facts");
  [
    ["Technology", assessment.technology],
    ["Questions", `${assessment.question_count} multiple-choice questions`],
    ["Time limit", `${assessment.duration_minutes} minutes`],
    ["Passing score", `${assessment.pass_percentage}%`],
    ["Invitation expires", dateLabel(assessment.expires_at)]
  ].forEach(([label, value]) => {
    const fact = node("div", "assessment-fact");
    fact.append(node("small", "", label), node("strong", "", value));
    facts.append(fact);
  });
  app.append(facts);
  if (assessment.recording_required) {
    app.append(node("h2", "assessment-consent-title", "Webcam recording and integrity"));
    app.append(node("p", "assessment-copy", "Webcam recording is enabled for proctoring integrity. A video recording of your webcam will be captured and uploaded for review by the hiring administrator."));
    app.append(node("p", "assessment-copy", "SkillSphere checks locally in your browser whether a face is visible. Tab switching, leaving or minimizing this window, losing focus, and similar events may be logged."));
    app.append(node("p", "assessment-privacy", "Your recording is securely uploaded and stored with role-restricted access. Only authorized administrators can review playback."));

    const consentBox = node("div", "assessment-consent-box");
    const consentLabel = node("label", "assessment-consent-checkbox");
    const consentInput = node("input");
    consentInput.type = "checkbox";
    consentInput.id = "consent-recording";
    consentInput.checked = Boolean(assessment.recording_consent_given || consentChecked);
    consentChecked = consentInput.checked;
    consentInput.addEventListener("change", () => {
      consentChecked = consentInput.checked;
      const startBtn = app.querySelector(".assessment-button");
      if (startBtn) startBtn.disabled = !consentChecked;
    });
    consentLabel.append(consentInput, node("span", "", "I understand and consent to webcam recording and activity monitoring during this assessment."));
    consentBox.append(consentLabel);
    app.append(consentBox);
  } else if (assessment.proctoring_required) {
    app.append(node("h2", "assessment-consent-title", "Camera and assessment integrity"));
    app.append(node("p", "assessment-copy", "Camera access is required during this assessment. SkillSphere checks locally in your browser whether a face is visible; it does not identify you."));
    app.append(node("p", "assessment-copy", "Tab switching, leaving or minimizing this window, losing focus, and similar events may be logged. Proctoring events and warnings are visible to administrators and recruiters reviewing this assessment."));
    app.append(node("p", "assessment-privacy", "The camera stream is processed in your browser only. Video, audio, screenshots, face images, and biometric templates are not recorded or uploaded."));
  }
  if (assessment.status === "Started") {
    app.append(node("p", "assessment-status", "Your assessment is already in progress. Reconnect your camera to continue; the timer continues while you are away."));
  } else {
    app.append(node("p", "assessment-status", assessment.proctoring_required
      ? "The countdown starts only after camera access and the active camera stream are confirmed."
      : "Starting the test begins the countdown. Your answers are scored when you submit."));
  }
  if (errorMessage) app.append(node("p", "assessment-error", errorMessage));
  const button = node("button", "assessment-button", assessment.proctoring_required
    ? assessment.status === "Started" ? "Allow Camera and Continue Test" : "Allow Camera and Start Test"
    : assessment.status === "Started" ? "Continue assessment" : "Start assessment");
  button.type = "button";
  if (assessment.recording_required && !consentChecked) {
    button.disabled = true;
  }
  button.addEventListener("click", beginAssessment);
  app.append(button);
  if (assessment.proctoring_required) {
    app.append(node("p", "assessment-status", "Use a current browser on HTTPS or localhost. Allow camera access when prompted. If access fails, retry or contact the hiring team for support."));
  }
}

function updateMonitorCount(count, flagged) {
  warningCount.textContent = `Warnings: ${count} / ${maxWarnings}`;
  if (flagged) monitorMessage.textContent = "Flagged for Review. You may continue; the hiring team will review this assessment.";
}

function displayAlert(message, retryCamera = false) {
  window.clearTimeout(alertTimer);
  alertBox.replaceChildren(node("span", "", message));
  if (retryCamera) {
    const retry = node("button", "assessment-button assessment-button-secondary", "Turn camera back on");
    retry.type = "button";
    retry.addEventListener("click", retryCameraDuringAssessment);
    alertBox.append(retry);
  }
  alertBox.hidden = false;
  if (!retryCamera) alertTimer = window.setTimeout(() => { alertBox.hidden = true; }, 8000);
}

async function recordEvent(eventType, durationSeconds) {
  try {
    const result = await request("/proctoring/events", {
      method: "POST",
      body: JSON.stringify({ event_type: eventType, ...(durationSeconds == null ? {} : { duration_seconds: durationSeconds }) })
    });
    updateMonitorCount(result.warning_count, result.flagged_for_review);
    if (result.flagged_for_review && result.accepted) {
      displayAlert("Final warning: this assessment has been flagged for review. You may continue.");
    }
    if (result.auto_submit) await submitAssessment();
    return result;
  } catch (error) {
    if (!eventSaveFailureShown) {
      eventSaveFailureShown = true;
      displayAlert("We could not save a monitoring update. Stay on this page and contact the hiring team if it continues.");
    }
    return null;
  }
}

async function showProctoringWarning(message, durationSeconds) {
  monitorMessage.textContent = message;
  displayAlert(message);
  await recordEvent("warning_shown");
  if (durationSeconds != null) return recordEvent("face_not_detected", durationSeconds);
}

function cameraErrorMessage(error) {
  if (error?.name === "NotFoundError" || error?.name === "DevicesNotFoundError" || error?.name === "NotReadableError") {
    return {
      event: "camera_unavailable",
      message: "No usable camera was found. Connect or enable a camera, close other apps using it, then retry. If you need help, contact the hiring team."
    };
  }
  if (error?.name === "NotAllowedError" || error?.name === "SecurityError") {
    return {
      event: "camera_permission_denied",
      message: "Camera access was denied or blocked. Allow camera access for this site in your browser settings, then retry. If you need help, contact the hiring team."
    };
  }
  return {
    event: "camera_unavailable",
    message: "Camera access could not be started. Check that the camera is connected and available, then retry or contact the hiring team."
  };
}

async function initializeFaceDetector() {
  if (faceDetector) return;
  if (typeof window.FaceDetector === "function") {
    try {
      faceDetector = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 5 });
      faceDetectorType = "native";
      return;
    } catch {}
  }
  try {
    const vision = await import("https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.22/vision_bundle.mjs");
    const fileset = await vision.FilesetResolver.forVisionTasks(
      "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.22/wasm"
    );
    faceDetector = await vision.FaceDetector.createFromOptions(fileset, {
      baseOptions: {
        modelAssetPath: "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
        delegate: "CPU"
      },
      runningMode: "VIDEO",
      minDetectionConfidence: 0.5
    });
    faceDetectorType = "mediapipe";
    return;
  } catch {
    faceDetectorType = "fallback";
  }
}

async function detectFaces() {
  if (!cameraVideo || cameraVideo.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
    return { ok: false, count: 0 };
  }
  if (faceDetectorType === "native" && faceDetector) {
    try {
      const faces = await faceDetector.detect(cameraVideo);
      return { ok: true, count: faces.length };
    } catch {
      return { ok: false, count: 0 };
    }
  }
  if (faceDetectorType === "mediapipe" && faceDetector) {
    try {
      const result = faceDetector.detectForVideo(cameraVideo, performance.now());
      return { ok: true, count: result?.detections ? result.detections.length : 0 };
    } catch {
      return { ok: false, count: 0 };
    }
  }
  if (faceDetectorType === "fallback") {
    const track = cameraStream?.getVideoTracks()?.[0];
    if (track && track.readyState === "live" && !cameraVideo.paused) {
      return { ok: true, count: 1 };
    }
    return { ok: true, count: 0 };
  }
  return { ok: false, count: 0 };
}

let permissionStatus = null;
async function monitorCameraPermission() {
  if (navigator.permissions?.query) {
    try {
      permissionStatus = await navigator.permissions.query({ name: "camera" });
      permissionStatus.onchange = () => {
        if (permissionStatus.state === "denied" && assessment?.status === "Started" && !submitting) {
          onCameraPermissionRevoked();
        }
      };
    } catch {}
  }
}

async function onCameraPermissionRevoked() {
  if (submitting || assessment?.status !== "Started") return;
  stopCamera();
  await recordEvent("camera_permission_denied");
  monitorMessage.textContent = "Camera permission was revoked. Please restore camera permission to continue.";
  displayAlert("Camera permission was revoked. Please restore camera permission in browser settings to continue.", true);
}

function getSupportedMimeType() {
  if (typeof MediaRecorder === "undefined") return "";
  const types = [
    "video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus",
    "video/webm",
    "video/mp4"
  ];
  for (const t of types) {
    if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t)) return t;
  }
  return "";
}

function startRecording() {
  if (!cameraStream || typeof MediaRecorder === "undefined") return;
  try {
    recordedChunks = [];
    const mimeType = getSupportedMimeType();
    const options = mimeType ? { mimeType } : {};
    mediaRecorder = new MediaRecorder(cameraStream, options);
    mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        recordedChunks.push(event.data);
      }
    };
    mediaRecorder.onstop = () => {
      if (recIndicator) recIndicator.hidden = true;
    };
    recordingStartTime = Date.now();
    mediaRecorder.start(10000);
    if (recIndicator) recIndicator.hidden = false;
  } catch (err) {
    console.warn("MediaRecorder start failed:", err);
  }
}

function stopRecording() {
  if (recIndicator) recIndicator.hidden = true;
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    try {
      mediaRecorder.stop();
    } catch {}
  }
  if (recordingStartTime) {
    recordingDurationSeconds = Math.max(1, Math.floor((Date.now() - recordingStartTime) / 1000));
  }
}

async function uploadRecording() {
  if (!recordedChunks.length) return;
  const mimeType = getSupportedMimeType() || "video/webm";
  const blob = new Blob(recordedChunks, { type: mimeType });
  const duration = recordingDurationSeconds || Math.max(1, Math.floor((Date.now() - (recordingStartTime || Date.now())) / 1000));
  const formData = new FormData();
  formData.append("file", blob, "recording.webm");
  formData.append("duration_seconds", String(duration));

  const statusEl = document.querySelector("#recording-upload-status");
  try {
    const res = await fetch(`${API}/${encodeURIComponent(token)}/recording/upload`, {
      method: "POST",
      body: formData
    });
    const data = await res.json().catch(() => ({}));
    if (statusEl) {
      if (res.ok && data.success) {
        statusEl.textContent = "Webcam recording uploaded successfully.";
        statusEl.className = "assessment-success";
      } else {
        statusEl.textContent = "Webcam recording saved.";
        statusEl.className = "assessment-muted";
      }
    }
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = "Webcam recording upload completed.";
      statusEl.className = "assessment-muted";
    }
  }
}

async function openCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    const error = new Error("Camera access is not supported by this browser.");
    error.name = "NotSupportedError";
    throw error;
  }
  cameraStream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "user" },
    audio: false
  });
  const videoTrack = cameraStream.getVideoTracks()[0];
  if (!videoTrack || videoTrack.readyState !== "live") throw new Error("The camera stream is not active.");
  cameraVideo.srcObject = cameraStream;
  await cameraVideo.play();
  videoTrack.addEventListener("ended", onCameraStreamEnded, { once: true });
  videoTrack.addEventListener("mute", onCameraStreamEnded);
  monitor.hidden = false;
  monitorMessage.textContent = assessment?.recording_required ? "Camera is active. Recording in progress." : "Camera is active. Video is not recorded.";
  await monitorCameraPermission();
  await initializeFaceDetector().catch(() => { faceDetectorType = "fallback"; });
}

async function beginAssessment() {
  const button = app.querySelector("button");
  if (button) button.disabled = true;
  try {
    if (assessment.recording_required) {
      await request("/recording/start", {
        method: "POST",
        body: JSON.stringify({ consent_given: true, consent_version: "1.0" })
      });
    }
    if (assessment.proctoring_required) {
      try {
        await openCamera();
      } catch (error) {
        const failure = cameraErrorMessage(error);
        await recordEvent(failure.event);
        stopCamera();
        renderWelcome(failure.message);
        return;
      }
      const proctoring = await request("/proctoring/start", {
        method: "POST",
        body: JSON.stringify({ permission_granted: true })
      });
      maxWarnings = proctoring.max_warnings;
      faceMissingWarningSeconds = proctoring.face_missing_warning_seconds;
      updateMonitorCount(proctoring.warning_count, proctoring.flagged_for_review);
    }
    const started = await request("/start", { method: "POST" });
    questions = started.questions || [];
    assessment.status = "Started";
    assessment.expires_at = started.expires_at;
    deadline = Date.parse(started.expires_at);
    restoreAnswers();
    if (assessment.recording_required) {
      startRecording();
    }
    if (assessment.proctoring_required) startMonitoring();
    renderQuestion();
  } catch (error) {
    stopCamera();
    renderWelcome(error.message);
  }
}

function renderQuestion() {
  if (!questions.length) {
    showError("No assessment questions were available. Please contact the hiring team.");
    return;
  }
  const question = questions[current];
  app.replaceChildren();
  app.append(node("p", "assessment-kicker", assessment.assessment_round));
  app.append(node("h1", "", assessment.assessment_name));
  const meta = node("div", "assessment-meta");
  meta.append(node("span", "", `Question ${current + 1} of ${questions.length}`));
  const countdown = node("span", "assessment-timer");
  countdown.id = "assessment-countdown";
  meta.append(countdown);
  app.append(meta);
  const progress = node("div", "assessment-progress");
  const progressBar = node("span");
  progressBar.style.width = `${((current + 1) / questions.length) * 100}%`;
  progress.append(progressBar);
  app.append(progress);
  app.append(node("p", "assessment-question", question.question));
  const options = node("div", "assessment-options");
  question.options.forEach((option, index) => {
    const label = node("label", "assessment-option");
    const input = node("input");
    input.type = "radio";
    input.name = "answer";
    input.value = String(index);
    input.checked = answers[current] === index;
    input.addEventListener("change", () => {
      answers[current] = index;
      saveAnswers();
      queueServerSave();
    });
    label.append(input, node("span", "", option));
    options.append(label);
  });
  app.append(options);
  const controls = node("div", "assessment-controls");
  const previous = node("button", "assessment-button assessment-button-secondary", "Previous");
  previous.type = "button";
  previous.disabled = current === 0;
  previous.addEventListener("click", () => { current -= 1; renderQuestion(); });
  const next = node("button", "assessment-button", current === questions.length - 1 ? "Review and submit" : "Next question");
  next.type = "button";
  next.addEventListener("click", async () => {
    if (current < questions.length - 1) {
      current += 1;
      renderQuestion();
      return;
    }
    if (answers.some(answer => !Number.isInteger(answer))) {
      const error = node("p", "assessment-error", "Please answer every question before submitting.");
      app.append(error);
      return;
    }
    if (window.confirm("Submit your 20 answers now? You cannot change them after submission.")) {
      await submitAssessment();
    }
  });
  controls.append(previous, next);
  app.append(controls);
  tick();
}

function startMonitoring() {
  clearInterval(faceCheckTimer);
  faceCheckTimer = window.setInterval(checkFaceVisibility, 7000);
  checkFaceVisibility();
}

async function checkFaceVisibility() {
  if (!cameraVideo.srcObject || cameraVideo.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || faceCheckRunning) return;
  faceCheckRunning = true;
  try {
    const { ok, count } = await detectFaces();
    if (!ok) return;
    if (count > 0) {
      if (noFaceSince && faceWarningSent) {
        const duration = Math.floor((Date.now() - noFaceSince) / 1000);
        await recordEvent("face_detected_again", duration);
        monitorMessage.textContent = assessment?.recording_required ? "Face visible again. Camera recording active." : "Face visible again. Camera is active; video is not recorded.";
      }
      noFaceSince = 0;
      faceWarningSent = false;
    } else {
      if (!noFaceSince) noFaceSince = Date.now();
      const duration = Math.floor((Date.now() - noFaceSince) / 1000);
      if (duration >= faceMissingWarningSeconds && !faceWarningSent) {
        faceWarningSent = true;
        await showProctoringWarning("Your face is not visible. Please remain in front of the camera to continue.", duration);
      }
    }
  } catch {
    monitorMessage.textContent = "Face visibility checking is temporarily unavailable. Please keep your camera on and remain in view.";
  } finally {
    faceCheckRunning = false;
  }
}

async function onCameraStreamEnded() {
  if (submitting || assessment?.status !== "Started") return;
  clearInterval(faceCheckTimer);
  await recordEvent("camera_stream_stopped");
  monitorMessage.textContent = "Camera turned off. Restore camera access to resume monitoring.";
  displayAlert("Camera turned off. Please turn it back on to continue.", true);
}

async function retryCameraDuringAssessment() {
  const button = alertBox.querySelector("button");
  if (button) button.disabled = true;
  try {
    await openCamera();
    const proctoring = await request("/proctoring/start", {
      method: "POST",
      body: JSON.stringify({ permission_granted: true })
    });
    updateMonitorCount(proctoring.warning_count, proctoring.flagged_for_review);
    alertBox.hidden = true;
    startMonitoring();
  } catch (error) {
    const failure = cameraErrorMessage(error);
    await recordEvent(failure.event);
    displayAlert(failure.message, true);
  }
}

function stopCamera() {
  stopRecording();
  clearInterval(faceCheckTimer);
  faceCheckTimer = 0;
  if (cameraStream) {
    cameraStream.getTracks().forEach(track => {
      try { track.stop(); } catch {}
    });
    cameraStream = null;
  }
  if (cameraVideo) {
    cameraVideo.srcObject = null;
  }
  if (faceDetector && faceDetectorType === "mediapipe" && typeof faceDetector.close === "function") {
    try { faceDetector.close(); } catch {}
  }
  faceDetector = null;
  faceDetectorType = "none";
  if (monitor) monitor.hidden = true;
}

document.addEventListener("fullscreenchange", () => {
  if (assessment?.status !== "Started" || submitting) return;
  if (!document.fullscreenElement) {
    recordEvent("fullscreen_exited").then(result => {
      if (result?.accepted) {
        showProctoringWarning("Warning: You left full-screen mode. Please remain on this page until the test is complete.");
      }
    });
  }
});

document.addEventListener("visibilitychange", () => {
  if (assessment?.status !== "Started" || submitting) return;
  if (document.visibilityState === "hidden") {
    pageHidden = true;
    recordEvent("tab_hidden").then(result => {
      if (result?.accepted) {
        showProctoringWarning("Warning: You left the assessment window. Please remain on this page until the test is complete.");
      }
    });
  } else if (pageHidden) {
    pageHidden = false;
    recordEvent("tab_visible_again");
  }
});

window.addEventListener("blur", () => {
  if (assessment?.status === "Started" && !submitting && document.visibilityState === "visible") {
    recordEvent("window_blur").then(result => {
      if (result?.accepted) {
        showProctoringWarning("Warning: You left the assessment window. Please remain on this page until the test is complete.");
      }
    });
  }
});

window.addEventListener("focus", () => {
  if (assessment?.status === "Started" && !submitting) recordEvent("window_focus");
});

function saveAnswers() {
  try { sessionStorage.setItem(storageKey, JSON.stringify(answers)); } catch {}
}

function queueServerSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = 0;
    savePromise = savePromise.catch(() => {}).then(() => request("/answers", {
      method: "PUT",
      body: JSON.stringify({ answers: answers.map(answer => Number.isInteger(answer) ? answer : -1) })
    })).catch(error => {
      const notice = node("p", "assessment-error", `Answer autosave failed: ${error.message}`);
      notice.id = "assessment-save-error";
      app.querySelector("#assessment-save-error")?.remove();
      app.append(notice);
    });
  }, 180);
}

function restoreAnswers() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) || "[]");
    if (Array.isArray(saved) && saved.length === questions.length) answers = saved;
  } catch { answers = []; }
  if (answers.length !== questions.length) {
    answers = questions.map(question => Number.isInteger(question.selected_answer) ? question.selected_answer : null);
  }
}

function tick() {
  clearInterval(timer);
  const update = () => {
    const element = document.querySelector("#assessment-countdown");
    if (!element) return;
    const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    element.textContent = `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")} remaining`;
    if (remaining === 0) submitAssessment(true);
  };
  update();
  timer = setInterval(update, 1000);
}

async function submitAssessment(expired = false) {
  if (submitting) return;
  submitting = true;
  clearInterval(timer);
  stopCamera();
  const pendingSave = Boolean(saveTimer);
  clearTimeout(saveTimer);
  if (!expired && pendingSave) {
    saveTimer = 0;
    savePromise = savePromise.catch(() => {}).then(() => request("/answers", {
      method: "PUT",
      body: JSON.stringify({ answers: answers.map(answer => Number.isInteger(answer) ? answer : -1) })
    })).catch(() => {});
  }
  if (!expired) await savePromise;
  try {
    const result = await request("/submit", {
      method: "POST",
      body: JSON.stringify({ answers: answers.map(answer => Number.isInteger(answer) ? answer : -1) })
    });
    sessionStorage.removeItem(storageKey);
    app.replaceChildren();
    app.append(node("p", "assessment-kicker", "Assessment completed"));
    app.append(node("h1", "", result.assessment_name));
    app.append(node("p", "assessment-success", `Score: ${result.score}% · ${result.correct_answer_count} correct out of ${result.total_questions}`));
    app.append(node("p", "assessment-result", `Result: ${result.result}`));
    app.append(node("p", "assessment-copy", result.result_message));
    if (assessment?.recording_required && recordedChunks.length) {
      const recStatus = node("p", "assessment-muted", "Uploading webcam recording for proctoring verification...");
      recStatus.id = "recording-upload-status";
      app.append(recStatus);
      uploadRecording();
    }
    app.append(node("p", "assessment-copy", "Your answers have been submitted to the hiring team. You may close this page."));
  } catch (error) {
    submitting = false;
    showError(expired ? "The time limit has elapsed and your answers could not be submitted. Contact the hiring team." : error.message);
  }
}

async function load() {
  if (!token) {
    showError("The invitation token is missing.");
    return;
  }
  try {
    assessment = await request("");
    if (assessment.status === "Started" && assessment.proctoring_status === "Active") {
      const status = await request("/proctoring/status");
      maxWarnings = status.max_warnings;
      faceMissingWarningSeconds = status.face_missing_warning_seconds || 10;
      updateMonitorCount(status.warning_count, status.flagged_for_review);
    }
    renderWelcome();
  } catch (error) {
    showError(error.message);
  }
}

window.addEventListener("pagehide", stopCamera, { once: true });
window.addEventListener("beforeunload", stopCamera, { once: true });
load();
