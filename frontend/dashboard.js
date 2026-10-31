// Live case-file dashboard: listens on /ws/<session_id> and re-renders on every update.
// Every message carries the whole case file, so render() simply redraws everything.
// Scammer-supplied text is only ever set with textContent, never innerHTML.
const dashboard = (() => {
  const $ = (id) => document.getElementById(id);
  let ws = null, watching = null, retryTimer = 0;

  const SCAM_LABELS = {
    bank_kyc: "Bank KYC", otp_fraud: "OTP fraud", upi_refund: "UPI refund",
    digital_arrest: "Digital arrest", courier_customs: "Courier / customs",
    electricity_bill: "Electricity bill", lottery_prize: "Lottery / prize", job_task: "Job / task",
    investment: "Investment", loan_app: "Loan app", tech_support: "Tech support",
    other: "Other", not_scam: "Not a scam", unknown: "Unknown",
  };
  const EVIDENCE_LABELS = { phones: "Phone numbers", upi_ids: "UPI IDs", links: "Links", banks: "Banks / apps" };
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
    watching = sessionId;
    connect();
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const socket = (ws = new WebSocket(`${proto}://${location.host}/ws/${watching}`));
    socket.onopen = () => setConn("live");
    socket.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "case") render(msg.case);
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
    const socket = ws;
    ws = null;
    socket?.close();
    setConn("offline");
  }

  function setConn(state) {
    $("conn").textContent = state;
    $("conn").className = "conn " + (state === "live" ? "live" : "");
  }

  // ---------- Rendering ----------
  function render(c) {
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

  return { watch, stop };
})();
