// Call screen: the handoff button, hands-free listening, Whisper upload and Dadaji's voice.
const $ = (id) => document.getElementById(id);
const log = $("log"), input = $("input"), send = $("send"), pill = $("pill");
const handoffBtn = $("handoff"), tapBtn = $("tap"), endBtn = $("end"), voiceSelect = $("voice");
const personaSelect = $("persona");
const levelBar = $("level").firstElementChild;

let sessionId = null;
let inCall = false;
let busy = false; // a scammer turn is being processed

// ---------- UI helpers ----------
const STATE_LABELS = { idle: "Ready", speaking: "Dadaji speaking…", listening: "Listening…",
                       transcribing: "Hearing you…", thinking: "Dadaji thinking…", typing: "Type to talk" };
function setState(state) {
  pill.textContent = STATE_LABELS[state];
  pill.className = state;
  tapBtn.textContent = state === "speaking" ? "Interrupt Dadaji" : "Done speaking";
  tapBtn.disabled = !(state === "listening" || state === "speaking");
}

function addMessage(who, text, cls) {
  const div = document.createElement("div");
  div.className = "msg " + cls;
  if (who) {
    const label = document.createElement("small");
    label.textContent = who;
    div.append(label);
  }
  div.append(text);
  log.append(div);
  log.scrollTop = log.scrollHeight;
}
const addError = (text) => addMessage("", "⚠ " + text, "error");

async function postJSON(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                                 body: JSON.stringify(body) });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

// ---------- Personas ----------
let personas = {}; // key -> {key, name, description, finale}
async function loadPersonas() {
  try {
    const list = await (await fetch("/api/personas")).json();
    personas = Object.fromEntries(list.map((p) => [p.key, p]));
    personaSelect.replaceChildren(...list.map((p) => {
      const opt = new Option(p.name, p.key);
      opt.title = p.description;
      return opt;
    }));
    dashboard.setPersonas(list);
  } catch { /* keep the built-in Sweet Dadaji option */ }
}
loadPersonas();
// A call keeps the persona it started with, so the picker is locked until it ends.
const lockPersona = (locked) => { personaSelect.disabled = locked; };

// ---------- Text-to-speech ----------
let voices = [];
function loadVoices() {
  // Indian voices only, Hindi first. Voices load asynchronously, so this runs again on voiceschanged.
  voices = speechSynthesis.getVoices().filter((v) => /^(hi|en)[-_]IN/i.test(v.lang))
    .sort((a, b) => b.lang.startsWith("hi") - a.lang.startsWith("hi"));
  const current = voiceSelect.value;
  voiceSelect.replaceChildren(...voices.map((v) => new Option(`${v.name} (${v.lang})`, v.voiceURI)));
  if (!voices.length) voiceSelect.append(new Option("Default voice", ""));
  if (voices.some((v) => v.voiceURI === current)) voiceSelect.value = current;
}
speechSynthesis.onvoiceschanged = loadVoices;
loadVoices();

let utterance = null; // kept in a variable: Chrome may drop onend if the utterance is garbage-collected
function speak(text) {
  return new Promise((resolve) => {
    const words = text.trim(); // already cleaned by the backend guardrail
    if (!words) return resolve();
    utterance = new SpeechSynthesisUtterance(words);
    const voice = voices.find((v) => v.voiceURI === voiceSelect.value);
    utterance.voice = voice || null;
    utterance.lang = voice ? voice.lang : "hi-IN";
    utterance.rate = 0.9;  // a little slower...
    utterance.pitch = 0.8; // ...and lower, to sound older
    // Safety net in case onend never fires, so the call can't get stuck.
    const timer = setTimeout(resolve, words.length * 120 + 3000);
    utterance.onend = utterance.onerror = () => { clearTimeout(timer); resolve(); };
    speechSynthesis.cancel();
    speechSynthesis.speak(utterance);
  });
}

// ---------- The finale scream ----------
const scream = new Audio("/static/scream.wav");
scream.preload = "auto";

// Safari only lets audio play later if it was started during a click. So on the End click,
// play it silently for a moment; the real play after Dadaji's last line is then allowed.
function unlockScream() {
  scream.muted = true;
  scream.play().then(() => { scream.pause(); scream.currentTime = 0; scream.muted = false; })
    .catch(() => { scream.muted = false; });
}

function playScream() {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, 6000); // safety net, like speak()
    scream.onended = scream.onerror = () => { clearTimeout(timer); resolve(); };
    scream.muted = false;
    scream.currentTime = 0;
    scream.play().catch(() => { clearTimeout(timer); resolve(); });
  });
}

// ---------- Microphone + hands-free turn-taking ----------
// While listening, the recorder runs from the start (so the first word isn't clipped) and
// a volume meter decides when the scammer has started and then stopped talking.
const END_SILENCE_MS = 1200, MIN_SPEECH_MS = 500, MAX_TURN_MS = 20000, IDLE_RESTART_MS = 15000;
const MIN_THRESHOLD = 0.015;

let stream = null, audioCtx = null, analyser = null, recorder = null;
let mimeType = "", turn = null, rafId = 0, noiseFloor = 0.01;

async function initMic() {
  stream = await navigator.mediaDevices.getUserMedia(
    { audio: { echoCancellation: true, noiseSuppression: true } });
  audioCtx = new AudioContext();
  await audioCtx.resume(); // Safari starts it suspended
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 1024;
  audioCtx.createMediaStreamSource(stream).connect(analyser);
  mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"]
    .find((t) => MediaRecorder.isTypeSupported(t)) || "";
}

function volume() { // root-mean-square of the current audio frame, roughly 0..1
  const buf = new Float32Array(analyser.fftSize);
  analyser.getFloatTimeDomainData(buf);
  let sum = 0;
  for (const x of buf) sum += x * x;
  return Math.sqrt(sum / buf.length);
}

function startListening() {
  if (!inCall || !stream) return;
  setState("listening");
  // Each recorder keeps its own chunks, so a discarded recorder's late data can't leak into the next turn.
  const chunks = [];
  recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  recorder.chunks = chunks;
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.start();
  const now = performance.now();
  turn = { startedAt: now, lastTick: now, lastLoudAt: 0, speechMs: 0, heard: false, forced: false };
  rafId = requestAnimationFrame(tick);
}

function tick() {
  if (!turn) return;
  const now = performance.now(), dt = now - turn.lastTick;
  turn.lastTick = now;
  const v = volume();
  // Threshold adapts to the room: about 3x the background noise.
  const threshold = Math.max(MIN_THRESHOLD, noiseFloor * 3);
  if (v > threshold) {
    turn.speechMs += dt;
    turn.lastLoudAt = now;
    if (turn.speechMs > 150) turn.heard = true;
  } else {
    noiseFloor = noiseFloor * 0.95 + v * 0.05;
  }
  levelBar.style.width = Math.min(100, (v / (threshold * 2)) * 100) + "%";

  if (turn.heard && now - turn.lastLoudAt > END_SILENCE_MS) return finishTurn();
  if (turn.heard && now - turn.startedAt > MAX_TURN_MS) return finishTurn();
  if (!turn.heard && now - turn.startedAt > IDLE_RESTART_MS) { // nobody spoke: drop the silent audio
    discardTurn();
    return startListening();
  }
  rafId = requestAnimationFrame(tick);
}

function stopRecorder() {
  return new Promise((resolve) => {
    const r = recorder;
    if (!r || r.state === "inactive") return resolve(null);
    r.onstop = () => resolve(new Blob(r.chunks, { type: (r.mimeType || "audio/webm").split(";")[0] }));
    r.stop();
  });
}

function discardTurn() {
  turn = null;
  cancelAnimationFrame(rafId);
  levelBar.style.width = "0";
  stopRecorder();
}

async function finishTurn() {
  const t = turn;
  turn = null;
  cancelAnimationFrame(rafId);
  levelBar.style.width = "0";
  const blob = await stopRecorder();
  if (!inCall || !blob) return;
  if (t.speechMs < MIN_SPEECH_MS && !t.forced) return startListening(); // a cough, not a sentence
  await transcribeAndReply(blob);
}

async function transcribeAndReply(blob) {
  setState("transcribing");
  const form = new FormData();
  form.append("audio", blob, "turn." + (blob.type.includes("mp4") ? "mp4" : "webm"));
  try {
    const res = await fetch("/api/transcribe", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      const err = new Error(data.detail || res.statusText);
      err.status = res.status;
      throw err;
    }
    if (!data.text) return startListening(); // only noise
    await scammerSays(data.text);
  } catch (err) {
    addError(err.message);
    if (err.status === 503) { stopMic(); setState("typing"); input.focus(); } // no Groq key: typing only
    else startListening();
  }
}

function stopMic() {
  discardTurn();
  stream?.getTracks().forEach((t) => t.stop());
  audioCtx?.close();
  stream = audioCtx = analyser = null;
}

// ---------- One scammer turn (spoken or typed) ----------
async function scammerSays(text) {
  if (busy) return;
  busy = true;
  send.disabled = true;
  discardTurn(); // if they typed while the mic was listening
  addMessage("Scammer", text, "me");
  setState("thinking");
  try {
    lockPersona(true);
    const data = await postJSON("/api/chat", { message: text, session_id: sessionId, persona: personaSelect.value });
    sessionId = data.session_id;
    dashboard.watch(sessionId); // no-op if already watching this call
    addMessage("Dadaji", data.reply, "dadaji");
    if (inCall) {
      setState("speaking");
      await speak(data.reply);
    }
  } catch (err) {
    addError(err.message);
    if (!sessionId) lockPersona(false); // the first message failed: no call was started
  } finally {
    busy = false;
    send.disabled = false;
  }
  if (inCall) stream ? startListening() : setState("typing");
  else setState("idle");
}

// ---------- Call controls ----------
handoffBtn.addEventListener("click", async () => {
  // Browsers only allow audio after a click, so "unlock" speech right here, before any await.
  speechSynthesis.speak(new SpeechSynthesisUtterance(""));
  handoffBtn.disabled = true;
  try {
    await initMic();
  } catch {
    addError("Microphone blocked or unavailable. Dadaji will still talk, and you can type.");
  }
  try {
    lockPersona(true);
    const data = await postJSON("/api/call/start", { persona: personaSelect.value });
    sessionId = data.session_id;
    dashboard.watch(sessionId);
    inCall = true;
    log.replaceChildren();
    handoffBtn.hidden = true;
    tapBtn.hidden = endBtn.hidden = false;
    addMessage("Dadaji", data.greeting, "dadaji");
    setState("speaking");
    await speak(data.greeting);
    if (!inCall) return;
    stream ? startListening() : setState("typing");
  } catch (err) {
    addError(err.message);
    stopMic();
    lockPersona(false);
  } finally {
    handoffBtn.disabled = false;
  }
});

tapBtn.addEventListener("click", () => {
  if (pill.className === "speaking") speechSynthesis.cancel(); // onend → back to listening
  else if (turn) { turn.forced = true; finishTurn(); }         // noisy room: send what we have
});

endBtn.addEventListener("click", async () => {
  const id = sessionId;
  const persona = personas[personaSelect.value];
  unlockScream(); // must happen inside the click, before any await
  inCall = false;
  stopMic();
  speechSynthesis.cancel();
  sessionId = null;
  tapBtn.hidden = endBtn.hidden = true;
  // The server stops the timer, saves the case and writes the complaint (a couple of seconds),
  // while Dadaji delivers his last line. Errors are caught here and shown after the finale.
  const ending = postJSON("/api/call/end", { session_id: id }).then((data) => ({ data }), (err) => ({ err }));

  // Finale: "this call was recorded and reported", then the ghostly scream.
  if (persona) {
    addMessage("Dadaji", persona.finale, "dadaji");
    setState("speaking");
    await speak(persona.finale);
  }
  pill.textContent = "👻 AAAAAAH!";
  await playScream();

  handoffBtn.hidden = false;
  setState("idle");
  lockPersona(false);
  addMessage("", "Call ended", "error");
  const { data, err } = await ending;
  if (data) dashboard.finish(data.case, data.report); // the final case file stays, plus the complaint
  else {
    dashboard.stop();
    addError("Couldn't close the case file: " + err.message);
  }
});

$("form").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || busy) return;
  input.value = "";
  scammerSays(text).then(() => input.focus());
});

setState("idle");
