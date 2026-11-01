// Live case-file dashboard: listens on /ws/<session_id> and re-renders on every update.
// Every message carries the whole case file, so render() simply redraws everything.
// Scammer-supplied text is only ever set with textContent, never innerHTML.
const dashboard = (() => {
  const $ = (id) => document.getElementById(id);
  let ws = null, watching = null, retryTimer = 0;
  // Time-wasted timer. offset = server clock minus this browser's clock, in seconds.
  const clock = { start: null, end: null, offset: 0, timer: 0 };

  const SCAM_LABELS = {
    bank_kyc: "Bank KYC", otp_fraud: "OTP fraud", upi_refund: "UPI refund",
    digital_arrest: "Digital arrest", courier_customs: "Courier / customs",
    electricity_bill: "Electricity bill", lottery_prize: "Lottery / prize", job_task: "Job / task",
    investment: "Investment", loan_app: "Loan app", tech_support: "Tech support",
    fake_fine_threat: "Fake fine / threat",
    other: "Other", not_scam: "Not a scam", unknown: "Unknown",
  };
  const EVIDENCE_LABELS = { phones: "Phone numbers", upi_ids: "UPI IDs", links: "Links", banks: "Banks / apps" };
  let personaNames = {}; // key -> display name, set by call.js once /api/personas loads
  const pretty = (key) => key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

  function el(tag, cls, text, title) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    if (title) node.title = title;
    return node;
  }

  // ---------- Connection ----------
  function watch(sessionId) {
    if (sessionId === watching) return;
    stop();
    $("reportcard").hidden = true; // a new call: the last complaint goes away
    watching = sessionId;
    connect();
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const socket = (ws = new WebSocket(`${proto}://${location.host}/ws/${watching}`));
    socket.onopen = () => setConn("live");
    socket.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "case") render(msg.case, msg.now);
    };
    socket.onclose = (e) => {
      if (socket !== ws || !watching) return; // we closed it on purpose
      if (e.code === 4404) return stop();     // server doesn't know this call (it restarted)
      setConn("reconnecting…");
      retryTimer = setTimeout(connect, 2000);
    };
  }

  function stop() {
    watching = null;
    clearTimeout(retryTimer);
    clearInterval(clock.timer); // freezes the timer where it is
    const socket = ws;
    ws = null;
    socket?.close();
    setConn("offline");
  }

  function setConn(state) {
    $("conn").textContent = state;
    $("conn").className = "conn " + (state === "live" ? "live" : "");
  }

  // The call is over: show the final case file (timer stopped), the complaint and the total.
  function finish(c, report) {
    stop();
    render(c);
    loadStats();
    if (report) showReport(report);
  }

  // ---------- Complaint ----------
  let reportText = "";

  async function copy(text, btn) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // No clipboard API (plain http on a LAN address): the old select-and-copy way.
      const area = el("textarea");
      area.value = text;
      document.body.append(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    const label = btn.textContent;
    btn.textContent = "Copied ✓";
    setTimeout(() => (btn.textContent = label), 1500);
  }

  function showReport(r) {
    const base = `/api/cases/${r.session_id}`;
    $("dl-txt").href = `${base}/report?format=txt`;
    $("dl-json").href = `${base}/report?format=json`;
    $("dl-transcript").href = `${base}/transcript`;
    // Fetched now, so "Copy all" can copy straight away (browsers want the copy right after the click).
    reportText = "";
    fetch(`${base}/report?format=txt&attach=false`).then((res) => res.text()).then((t) => (reportText = t));

    $("report").replaceChildren(...r.sections.flatMap((section) => {
      const rows = el("dl");
      for (const f of section.fields) {
        const dd = el("dd");
        if (f.value) {
          const btn = el("button", "copy", "Copy");
          btn.onclick = () => copy(f.value, btn);
          dd.append(f.value, btn);
        }
        if (f.hint) dd.append(el("small", "", f.hint));
        rows.append(el("dt", "", f.label), dd);
      }
      return [el("h4", "", section.title), rows];
    }));
    $("reportnotes").replaceChildren(...r.notes.map((n) => el("li", "", n)));
    $("reportcard").hidden = false;
    $("reportcard").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  $("copyall").onclick = (e) => reportText && copy(reportText, e.target);

  // ---------- Time wasted ----------
  function fmtClock(s) {
    const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, pad = (n) => String(n).padStart(2, "0");
    return (h ? h + ":" + pad(m) : pad(m)) + ":" + pad(s % 60);
  }
  function fmtLong(s) {
    const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
    return h ? `${h} h ${m} min` : m ? `${m} min ${s % 60} s` : `${s} s`;
  }

  function updateClock(c, now) {
    // The server's clock decides; the browser only ticks between updates. Using the server
    // time sent with each message keeps the timer right even if the phone's clock is off.
    if (now != null) clock.offset = now - Date.now() / 1000;
    clock.start = c.started_at;
    clock.end = c.ended_at;
    clearInterval(clock.timer);
    if (clock.end == null && watching) clock.timer = setInterval(drawClock, 1000);
    drawClock();
  }

  function drawClock() {
    const end = clock.end ?? Date.now() / 1000 + clock.offset;
    $("clock").textContent = fmtClock(Math.max(0, Math.floor(end - clock.start)));
    $("clock").classList.toggle("ended", clock.end != null);
  }

  async function loadStats() {
    try {
      const { calls, seconds } = await (await fetch("/api/stats")).json();
      $("totals").textContent = calls ? `Dadaji has kept scammers busy for ${fmtLong(seconds)} ` +
        `across ${calls} call${calls === 1 ? "" : "s"}.` : "";
    } catch { /* the total is a nice extra; never break the dashboard over it */ }
  }
  loadStats();

  // ---------- Rendering ----------
  function render(c, now) {
    updateClock(c, now);
    $("personaname").textContent = "· " + (personaNames[c.persona] || pretty(c.persona));
    const started = c.turns > 0;
    const color = `hsl(${120 - c.risk_score * 1.2} 70% 50%)`; // green → red
    $("risk").textContent = started ? c.risk_score : "–";
    $("risk").style.color = started ? color : "";
    $("riskbar").style.width = c.risk_score + "%";
    $("riskbar").style.background = color;
    sparkline(c.risk_history, color);
    $("turns").textContent = started ? `· turn ${c.turns}` : "";

    $("scamtype").textContent = started ? (SCAM_LABELS[c.scam_type] || pretty(c.scam_type)) : "Waiting for the scammer…";
    $("signals").replaceChildren(...c.signals.map((s) => el("li", "chip", s)));

    $("tactic").replaceChildren(...(c.stall_tactic
      ? [el("strong", "", pretty(c.stall_tactic)), el("div", "muted", c.stall_note || "")]
      : [el("span", "muted", "Dadaji is improvising")]));

    const passed = c.phone_passed;
    $("passcard").hidden = !passed;
    if (passed) {
      $("passtext").textContent = `${personaNames[passed.from] || pretty(passed.from)} passed the phone ` +
        `at turn ${passed.turn}: ` + (passed.source === "button" ? "the Pass to Bunty button."
          : `the scammer pushed for phone steps a second time ("${passed.detail}").`);
    }

    renderEvidence(c.evidence);
    renderGuardrail(c);

    const t = c.timings;
    $("timings").textContent = t.analysis == null ? "" :
      `Last turn: analyst + injection check ${t.analysis}s (in parallel) · Dadaji ${t.dadaji ?? "…"}s` +
      ` · evidence ${t.evidence ?? "…"}s (background)`;
  }

  function sparkline(history, color) {
    const line = $("spark").querySelector("polyline");
    const n = history.length;
    line.setAttribute("points", n < 2 ? "" :
      history.map((r, i) => `${(i / (n - 1)) * 100},${30 - r * 0.28}`).join(" "));
    line.style.stroke = color;
  }

  function renderEvidence(ev) {
    const rows = [];
    for (const [kind, label] of Object.entries(EVIDENCE_LABELS)) {
      if (!ev[kind].length) continue;
      const values = el("dd");
      for (const item of ev[kind]) {
        const tip = `turn ${item.turn} · found by ${item.source === "tool" ? "a tool call" : "the regex safety net"}`;
        values.append(el("span", "chip " + (item.source === "regex" ? "net" : ""), item.value, tip));
      }
      rows.push(el("dt", "", label), values);
    }
    $("evidence").replaceChildren(...rows);
    $("context").replaceChildren(...ev.context.map((ctx) => {
      const who = [ctx.claimed_identity, ctx.claimed_org].filter(Boolean).join(" · ");
      const money = [ctx.amount, ctx.payment_method].filter(Boolean).join(" via ");
      const li = el("li");
      li.append(el("span", "turn", `T${ctx.turn}`), " ", [who, money, ctx.note].filter(Boolean).join(" — "));
      return li;
    }));
    $("noevidence").hidden = rows.length > 0 || ev.context.length > 0;
  }

  function renderGuardrail(c) {
    const items = [
      ...c.injection_attempts.map((a) => ({ turn: a.turn, text:
        `Injection attempt caught by ${a.source === "prompt_guard"
          ? `Prompt Guard (${a.score.toFixed(3)})` : "the phrase list"} → Dadaji played dumb` })),
      ...c.guardrail_blocks.map((b) => ({ turn: b.turn, text:
        `Reply blocked (${b.problems.join(", ")}): “${b.draft}”` })),
    ].sort((a, b) => a.turn - b.turn);
    $("guard").replaceChildren(...(items.length
      ? items.map((i) => { const li = el("li"); li.append(el("span", "turn", `T${i.turn}`), " ", i.text); return li; })
      : [el("li", "muted", c.turns ? "All replies passed ✓" : "Nothing yet")]));
  }

  const setPersonas = (list) => { personaNames = Object.fromEntries(list.map((p) => [p.key, p.name])); };

  return { watch, stop, finish, setPersonas };
})();
