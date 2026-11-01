// Call screen: the handoff button, hands-free listening, Whisper upload and Dadaji's voice.
const $ = (id) => document.getElementById(id);
const log = $("log"), input = $("input"), send = $("send"), pill = $("pill");
const handoffBtn = $("handoff"), tapBtn = $("tap"), endBtn = $("end"), voiceSelect = $("voice");
const personaSelect = $("persona");
const levelBar = $("level").firstElementChild;

let sessionId = null;
let inCall = false;
let busy = false; // a scammer turn is being processed
let personas = {}; // key -> {key, name, description, finale, speaker, rate, pitch}
// Who is on the line for the picked persona: "Dadaji", or "Bunty" for Naughty Bunty.
const who = () => personas[personaSelect.value]?.speaker || "Dadaji";

// ---------- UI helpers ----------
const STATE_LABELS = { idle: "Ready", speaking: "Dadaji speaking…", listening: "Listening…",
                       transcribing: "Hearing you…", thinking: "Dadaji thinking…", typing: "Type to talk" };
function setState(state) {
  pill.textContent = STATE_LABELS[state].replace("Dadaji", who());
  pill.className = state;
  tapBtn.textContent = state === "speaking" ? "Interrupt " + who() : "Done speaking";
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

async function postJSON(url, body, timeoutMs = 0) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                                 body: JSON.stringify(body),
                                 signal: timeoutMs ? AbortSignal.timeout(timeoutMs) : undefined });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

// ---------- Personas ----------
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
let voicePicked = false; // the user chose a voice themselves: keep it
voiceSelect.addEventListener("change", () => { voicePicked = true; });
function loadVoices() {
  // Indian voices only, Hindi first. Voices load asynchronously, so this runs again on voiceschanged.
  voices = speechSynthesis.getVoices().filter((v) => /^(hi|en)[-_]IN/i.test(v.lang))
    .sort((a, b) => b.lang.startsWith("hi") - a.lang.startsWith("hi"));
  const current = voiceSelect.value;
  voiceSelect.replaceChildren(...voices.map((v) => new Option(`${v.name} (${v.lang})`, v.voiceURI)));
  if (!voices.length) voiceSelect.append(new Option("Default voice", ""));
  // Rishi (en-IN, Apple devices) is the default: most Hindi voices are female.
  const rishi = voices.find((v) => /rishi/i.test(v.name) && /^en[-_]IN/i.test(v.lang));
  if (voicePicked && voices.some((v) => v.voiceURI === current)) voiceSelect.value = current;
  else if (rishi) voiceSelect.value = rishi.voiceURI;
  else if (voices.some((v) => v.voiceURI === current)) voiceSelect.value = current;
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
    // Dadaji: a little slower and lower, to sound older. Bunty: quicker and higher.
    const persona = personas[personaSelect.value];
    utterance.rate = persona?.rate ?? 0.9;
    utterance.pitch = persona?.pitch ?? 0.8;
    // Safety nets, so the call can't get stuck: speech that never starts (blocked, no voices)
    // is skipped after SPEECH_START_MS, and speech that never ends is cut off.
    let started = false;
    const done = (why) => {
      clearTimeout(startTimer); clearTimeout(endTimer);
      if (why !== "end") console.warn("[speech]", why);
      resolve();
    };
    const startTimer = setTimeout(() => { if (!started) { speechSynthesis.cancel(); done("never started, skipping"); } },
                                  SPEECH_START_MS);
    const endTimer = setTimeout(() => { speechSynthesis.cancel(); done("timed out"); },
                                Math.min(words.length * 100 + 3000, SPEECH_MAX_MS));
    utterance.onstart = () => { started = true; };
    utterance.onend = () => done("end");
    utterance.onerror = (e) => done("error: " + e.error);
    speechSynthesis.cancel();
    speechSynthesis.speak(utterance);
  });
}
const SPEECH_START_MS = 2500, SPEECH_MAX_MS = 20000;

// Browsers only allow sound after a click. Call this inside every click that may lead to
// sound later (the handoff, each Send, End call): an empty utterance unlocks speech, and the
// muted scream unlocks the audio element (Safari).
function unlockAudio() {
  if (!speechSynthesis.speaking) speechSynthesis.speak(new SpeechSynthesisUtterance(""));
  unlockScream();
}

// ---------- The finale scream ----------
const scream = new Audio("/static/scream.wav");
scream.preload = "auto";

// Safari only lets audio play later if it was started during a click. So on every click that
// starts or ends a call (and each typed send), play it silently for a moment; the real play
// after Dadaji's last line is then allowed, even when the finale starts by itself.
function unlockScream() {
  if (!scream.paused) return;
  scream.muted = true;
  scream.play().then(() => { scream.pause(); scream.currentTime = 0; scream.muted = false; })
    .catch(() => { scream.muted = false; });
}

// The page flickers dark and shakes when the shriek hits. scream.wav opens with 0.7 s of
// silence (a jump scare), so the effect waits for that.
const SCREAM_SILENCE_MS = 700, HAUNT_MS = 1000;
function haunt() {
  document.body.classList.add("haunted");
  setTimeout(() => document.body.classList.remove("haunted"), HAUNT_MS);
}

function playScream() {
  return new Promise((resolve) => {
    // Safety nets, like speak(): skip it if it hasn't started in 1.5 s, stop it after 5 s.
    let started = false;
    const done = (why) => {
      clearTimeout(startTimer); clearTimeout(endTimer);
      scream.onplaying = scream.onended = scream.onerror = null;
      if (why !== "end") { console.warn("[scream]", why); scream.pause(); }
      resolve();
    };
    const startTimer = setTimeout(() => { if (!started) done("never started, skipping"); }, 1500);
    const endTimer = setTimeout(() => done("timed out"), 5000);
    scream.onplaying = () => { started = true; setTimeout(haunt, SCREAM_SILENCE_MS); };
    scream.onended = () => done("end");
    scream.onerror = () => done("error loading audio");
    scream.muted = false;
    scream.volume = 1; // full volume: it has to be louder than Dadaji
    scream.currentTime = 0;
    scream.play().catch((err) => done("blocked: " + err.name));
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
  let hungUp = false;
  send.disabled = true;
  discardTurn(); // if they typed while the mic was listening
  addMessage("Scammer", text, "me");
  setState("thinking");
  try {
    lockPersona(true);
    const data = await postJSON("/api/chat", { message: text, session_id: sessionId, persona: personaSelect.value });
    sessionId = data.session_id;
    dashboard.watch(sessionId); // no-op if already watching this call
    if (!inCall) {
      // A typed-only session is a call too: it can be ended (finale + complaint).
      // The handoff button hides until then, so the typed case isn't left open.
      endBtn.hidden = false;
      handoffBtn.hidden = true;
    }
    if (data.hangup) {
      // The scammer is giving up: Dadaji gets the last word before they can hang up.
      // (No `return` here: it would skip the endCall() below the try block.)
      hungUp = true;
      console.log("[finale] scammer is giving up, starting the finale");
      addMessage("", "Scammer is giving up…", "error");
    } else {
      addMessage(who(), data.reply, "dadaji");
    }
    if (inCall && !hungUp) {
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
  if (hungUp) return endCall();
  if (inCall) stream ? startListening() : setState("typing");
  else setState("idle");
}

// ---------- Call controls ----------
handoffBtn.addEventListener("click", async () => {
  unlockAudio(); // inside the click, before any await
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
    addMessage(who(), data.greeting, "dadaji");
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

// The finale. Runs on End call (the backup) or by itself when the scammer gives up.
// Every step has a timeout (speak, playScream, the server call), so it always reaches the end.
const END_TIMEOUT_MS = 30000; // the server writes the complaint with an LLM; usually 2-5 s
async function endCall() {
  const id = sessionId;
  if (!id) return; // already ending
  const persona = personas[personaSelect.value];
  console.log("[finale] 1/5 ending call", id);
  inCall = false;
  stopMic();
  speechSynthesis.cancel();
  sessionId = null;
  tapBtn.hidden = endBtn.hidden = true;
  // The server stops the timer, saves the case and writes the complaint (a couple of seconds),
  // while Dadaji delivers his last line. Errors are caught here and shown after the finale.
  const ending = postJSON("/api/call/end", { session_id: id }, END_TIMEOUT_MS)
    .then((data) => ({ data }), (err) => ({ err }));

  try {
    // Finale: "this call was recorded and reported", then the ghostly scream.
    if (persona) {
      console.log("[finale] 2/5 Dadaji's last line");
      addMessage(who(), persona.finale, "dadaji");
      setState("speaking");
      await speak(persona.finale);
    }
    console.log("[finale] 3/5 scream");
    pill.textContent = "👻 AAAAAAH!";
    await playScream();
  } catch (err) {
    console.error("[finale] sound failed, skipping ahead", err);
  }

  handoffBtn.hidden = false;
  setState("idle");
  lockPersona(false);
  addMessage("", "Call ended", "error");
  console.log("[finale] 4/5 waiting for the complaint");
  const { data, err } = await ending;
  if (data) {
    dashboard.finish(data.case, data.report); // the final case file stays, plus the complaint
    console.log("[finale] 5/5 complaint shown");
  } else {
    dashboard.stop();
    addError("Couldn't close the case file: " + err.message);
    console.error("[finale] 5/5 no complaint:", err);
  }
}

endBtn.addEventListener("click", () => {
  unlockAudio(); // must happen inside the click, before any await
  endCall();
});

$("form").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || busy) return;
  unlockAudio(); // typed calls can end by themselves too (the auto-finale has no click)
  input.value = "";
  scammerSays(text).then(() => input.focus());
});

setState("idle");
