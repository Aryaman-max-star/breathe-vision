// BREATHE Vision dashboard. Polls the Python app's REST API (no extra libraries).
const $ = (id) => document.getElementById(id);
const get = (p) => fetch(p, { cache: "no-store" }).then((r) => r.json());
let last = null;

function fmt(x, d = 2, unit = "") { return x === null || x === undefined ? "–" : (+x).toFixed(d) + unit; }
function ago(ts) { const s = Math.round(Date.now() / 1000 - ts); return s < 60 ? s + " s ago" : Math.round(s / 60) + " min ago"; }

function renderVerdict(r) {
  const v = $("verdict");
  v.className = "card verdict sev-" + (r ? r.severity : "INFO");
  if (!r) return;
  const CAUSE = { heat: "heat-related", permanent: "permanent", internal: "internal fault" };
  $("vname").textContent = r.verdict.replace("_", " ") + (r.cause && CAUSE[r.cause] ? " · " + CAUSE[r.cause] : "");
  $("vreason").textContent = r.reason;
  $("vaction").textContent = r.action;
  const ai = r.ai ? ` · AI score ${fmt(r.ai.scan, 3)} (${fmt(r.ai.ms, 1)} ms on-device)` : " · AI not trained";
  $("vmeta").textContent = `${new Date(r.ts * 1000).toLocaleTimeString()} · common mode ${fmt(r.c_mm, 3, " mm")}` +
    ` · scan ${fmt(r.scan_ms, 0, " ms")} (${r.frames || "–"} frames)` + ai + (r.condensation_risk ? " · CONDENSATION RISK" : "");
}

function renderCells(r, slotSel) {
  const box = $("cells"); box.innerHTML = "";
  const tA = r && r.t_alarm_mm ? r.t_alarm_mm : 0.25;
  $("thr").textContent = r ? `(alarm ≥ ${fmt(tA, 2)} mm, watch ≥ ${fmt(r.t_watch_mm, 2)} mm)` : "";
  for (let i = 0; i < 4; i++) {
    const c = r && r.cells ? r.cells[i] : null;
    const rel = c && c.rel_mm !== null && c.rel_mm !== undefined ? c.rel_mm : null;
    const pct = rel === null ? 0 : Math.max(2, Math.min(100, (rel / (2 * tA)) * 100));
    const d = document.createElement("div");
    d.className = "cell " + (c ? c.verdict : "") + (slotSel === i + 1 ? " sel" : "");
    d.innerHTML = `<div class="bar"><div style="height:${pct}%"></div></div>
      <div class="lab">Slot ${i + 1}</div>
      <div class="num">${rel === null ? "–" : (rel >= 0 ? "+" : "") + rel.toFixed(2)}</div>
      <div class="lab">mm vs others</div>
      <div class="lab">${c ? c.verdict : ""} · conf ${c ? fmt(c.edge_conf, 2) : "–"}</div>
      <div class="lab">abs ${c ? fmt(c.delta_mm, 3) : "–"} · ${c ? c.n_cols || 0 : 0} cols</div>`;
    d.title = c ? c.action : "";
    box.appendChild(d);
  }
}

function renderThermo(t, chart) {
  $("thermo").innerHTML = `
    <div>Air at the module<b>${fmt(t.t_air_c, 1, " °C")}</b><span class="small">Δ ${fmt(t.dT_c, 1)} °C · ${t.sensor_location || ""}</span></div>
    <div>Surface (est.)<b>${fmt(t.t_surf_est_c, 1, " °C")}</b><span class="small">τ = ${t.tau_module_s} s</span></div>
    <div>Dew point<b>${fmt(t.t_dew_c, 1, " °C")}</b><span class="small">RH ${fmt(t.rh_pct, 0, " %")} · ${fmt(t.dTdt_c_per_min, 2)} °C/min</span></div>`;
  const cv = $("chart"), g = cv.getContext("2d");
  const W = cv.width, H = cv.height; g.clearRect(0, 0, W, H);
  if (!chart || chart.length < 2) { g.fillStyle = "#888"; g.fillText("waiting for temperature readings…", 10, 20); return; }
  const vals = chart.flatMap((p) => [p[1], p[2], p[3]]).filter((x) => x !== null);
  let lo = Math.min(10, ...vals) - 1, hi = Math.max(40, ...vals) + 1;
  const t0 = chart[0][0], t1 = chart[chart.length - 1][0];
  const X = (t) => 30 + ((t - t0) / Math.max(1, t1 - t0)) * (W - 40), Y = (v) => H - 15 - ((v - lo) / (hi - lo)) * (H - 25);
  g.fillStyle = "rgba(127,127,127,.18)"; g.fillRect(30, Y(35), W - 40, Y(15) - Y(35));
  g.fillStyle = "#888"; g.font = "11px sans-serif";
  for (let v = Math.ceil(lo / 5) * 5; v <= hi; v += 5) { g.fillText(v, 4, Y(v) + 4); }
  [[1, "#d0461b"], [2, "#2f6fb3"], [3, "#1f8a4c"]].forEach(([k, col]) => {
    g.strokeStyle = col; g.lineWidth = 2; g.beginPath(); let started = false;
    chart.forEach((p) => { if (p[k] === null) return; const x = X(p[0]), y = Y(p[k]); started ? g.lineTo(x, y) : g.moveTo(x, y); started = true; });
    g.stroke();
  });
}

function renderState(s) {
  $("pack").textContent = s.pack_id;
  const st = s.station || {};
  const camBad = s.camera && s.camera.ok === false;
  $("mode").textContent = s.station_error ? "VISION OFFLINE" : camBad ? "camera reconnecting…" :
    (st.mode || "…") + (s.on_board ? " · UNO Q" : " · laptop");
  $("simcard").hidden = st.mode !== "synthetic";
  $("dbpill").textContent = s.db.enabled ? (s.db.pending ? `Aiven: ${s.db.pending} pending` : "Aiven: synced") : "Aiven: off";
  $("dbstat").textContent = s.db.enabled ? `pending ${s.db.pending}` + (s.db.last_error ? ` · last error: ${s.db.last_error}` : " · OK") +
    (s.db.last_sync ? ` · last sync ${ago(s.db.last_sync)}` : "") : `Database off: ${s.db.last_error}`;
  $("bn").textContent = st.baseline_n_pending || 0;
  if (st.controls) {
    const c = st.controls, yes = (k) => (c[k] ? "✓" : "✗");
    $("ctrls").textContent = `camera ${st.resolution ? st.resolution.join("×") : ""} · autofocus off ${yes("autofocus_off")} · ` +
      `manual focus ${yes("focus")} · manual exposure ${yes("manual_exposure")} · white balance ${yes("wb_manual")} · ` +
      `ring light: ${c.ring_light || "left as is"}` +
      (st.camera_reconnects ? ` · ⚠ camera dropped out and reconnected ${st.camera_reconnects}× (USB power?)` : "");
  }
  $("calstat").innerHTML = st.geometry_ok
    ? `Calibration <b>${st.calib_id}</b> · fit error ${fmt(st.fit_median_px, 2)} px · columns ${JSON.stringify(st.n_cols)} · ` +
      `baseline ${st.baseline_ok ? "done" : "NOT done"} · σ_rel ${fmt(st.sigma_rel_mm, 3)} mm · alarm ${fmt(st.t_alarm_mm, 2)} mm · ` +
      `scale ${JSON.stringify(st.k_scale)} · screen brightness ${fmt(st.sky_ref, 0)} (aim 200–240) · focus ${st.focus ?? "–"} · lens ${st.lens_vs_tops || "–"} the tops · camera-moved check ${st.fiducials ? "on" : "OFF"} · AI ${s.ai_trained ? "trained" : "not trained"}`
    : (s.station_error ? "Vision offline: " + s.station_error : "Not calibrated yet. Start with step 1.");
  $("msg").textContent = (s.busy ? "⏳ " + s.busy + "… " : "") + (s.calib_mode ? "[CALIBRATION MODE] " : "") + s.message;
  document.querySelectorAll("button[data-cal], #scanBtn").forEach((b) => (b.disabled = !!s.busy));
  renderWizard(s.wizard, !!s.busy);
  const ra = document.querySelector('button[data-cal="reanchor"]');
  if (ra) {
    const calibrated = !!(st && st.baseline_ok);
    ra.disabled = !!s.busy || !calibrated;
    ra.title = calibrated ? "All 4 NORMAL cells in place. About 2 minutes." : "Available after the calibration is finished";
    $("placeNote").textContent = s.busy === "reanchor" ? "⏳ Re-anchoring… about 2 minutes. Don't touch anything." :
      s.busy === "fov" ? "⏳ Measuring the camera's field of view… a few seconds. Don't touch anything." :
      (s.message && s.message.startsWith("Field of view")) ? s.message :
      (calibrated ? "" : "Re-anchor becomes available once the calibration is finished. Before that, the guide compares with the ideal position, which doesn't need to be exact.");
  }
  if (s.last !== last || (s.last && last && s.last.ts !== last.ts)) { last = s.last; renderVerdict(s.last); }
  renderCells(s.last, s.slot_sel);
  renderThermo(s.thermal, s.chart);
  $("hist").innerHTML = s.history.map((h) => `<li><b>${h.verdict}</b> · ${new Date(h.ts * 1000).toLocaleTimeString()} · ${h.reason}</li>`).join("");
}

async function poll() {
  try { renderState(await get("/api/state")); } catch (e) { $("msg").textContent = "Dashboard lost connection to the board… " + e; }
  setTimeout(poll, 1000);
}
async function pollImg() {
  try {
    const r = await get("/api/snapshot");
    if (r.jpg) $("live").src = "data:image/jpeg;base64," + r.jpg;
    $("liveerr").textContent = r.error || "";
  } catch (e) { /* ignore */ }
  setTimeout(pollImg, 1500);
}

$("scanBtn").onclick = () => get("/api/scan");
$("thReset").onclick = () => get("/api/thermal_reset");
document.querySelectorAll("button[data-cal]").forEach((b) => (b.onclick = () => get("/api/calib/" + b.dataset.cal)));
document.querySelectorAll("button[data-sim]").forEach((b) => (b.onclick = () => get("/api/sim/" + b.dataset.sim)));
$("aivenBtn").onclick = async () => {
  $("aiven").textContent = "asking Aiven…";
  const r = await get("/api/aiven");
  if (!r.ok) { $("aiven").textContent = "Error: " + r.error; return; }
  const tbl = (rows, head) => `<table><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr>` +
    rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("") + "</table>";
  $("aiven").innerHTML = `TLS: ${r.tls ? r.tls.ssl + " " + r.tls.version : "?"}<br><b>pack_health</b>` +
    tbl(r.health, ["pack", "last scan", "scans", "flags"]) + "<b>last 10 scans</b>" + tbl(r.scans, ["time", "verdict", "c mm", "air °C", "AI"]);
};
// ---- calibration wizard ----
const WIZ_STEPS = ["Sharpen", "Learn layout", "Normal cells", "0.6 mm", "Final test"];
function renderWizard(w, busy) {
  if (!w) return;
  $("wizSteps").innerHTML = w.active ? WIZ_STEPS.map((n, i) => {
    const k = i + 1, cls = w.step === "done" || (w.step_no && k < w.step_no) ? "done" : (k === w.step_no ? "now" : "");
    return `<span class="${cls}">${k}. ${n}</span>`;
  }).join("") : "";
  $("wizTitle").textContent = (w.step_no ? `Step ${w.step_no} of ${w.steps_total}: ` : "") + (w.title || "");
  $("wizDo").innerHTML = (w.do || []).map((t) => `<li>${t}</li>`).join("");
  const pr = $("wizProg");
  pr.hidden = !w.progress;
  if (w.progress) pr.firstElementChild.style.width = (100 * w.progress[0] / w.progress[1]) + "%";
  const sl = $("wizSlots");
  sl.hidden = !w.slot;
  if (w.slot) sl.innerHTML = [1, 2, 3, 4].map((k) => `<div class="${k === w.slot ? "hot" : ""}">Slot ${k}<br>` +
    `<span class="small">${k === w.slot ? "TALLER cell" : "normal"}</span></div>`).join("");
  $("wizWork").hidden = !w.working;
  $("wizWork").textContent = w.working ? "⏳ " + w.working : "";
  const res = $("wizRes");
  res.hidden = !w.result || !!w.working;
  if (w.result) { res.className = "wizres " + (w.result.ok ? "ok" : "bad"); res.textContent = (w.result.ok ? "" : "⚠ ") + w.result.text; }
  $("wizBtn").textContent = w.button || "Start calibration";
  $("wizBtn").disabled = busy;
  $("wizSkip").hidden = !w.can_skip; $("wizSkip").disabled = busy;
  $("wizSkip").textContent = w.step === "focus" ? "Skip focus" : w.step === "baseline" ? "Continue anyway" : "Skip this slot";
  $("wizCancel").hidden = !w.active || w.step === "done";
}
$("wizBtn").onclick = () => get("/api/wizard/act");
$("wizSkip").onclick = () => get("/api/wizard/skip");
$("wizCancel").onclick = () => { if (confirm("Stop the calibration? Steps already done are kept.")) get("/api/wizard/cancel"); };

// ---- camera placement (live) ----
let placing = false;
const ICON = { distance: "↕", turn: "↻", tilt: "⤒", roll: "⟲", aim: "↔" };
async function pollPlacement() {
  if (!placing) return;
  try {
    const r = await get("/api/placement");
    if (!r.busy) {
      const head = $("placeHead");
      head.className = "placehead " + (r.status || "");
      head.textContent = (r.status === "ok" ? "✅ " : r.status === "lost" ? "⛔ " : r.status === "settling" ? "⏳ " : "➡️ ") + (r.headline || "");
      $("placeSteps").className = "steps2" + (r.status === "settling" ? " dim" : "");
      $("placeSteps").innerHTML = (r.steps || []).map((s) =>
        `<li class="${s.ok ? "done" : "todo"}"><span class="ic">${s.ok ? "✓" : (ICON[s.axis] || "•")}</span>${s.text}</li>`).join("");
      const n = r.numbers || {};
      $("placeNum").textContent = r.numbers ? `mode: ${r.mode === "calibration" ? "back to the calibrated position" : "optimal position"} · ` +
        `lens→screen ${fmt(n.lens_to_screen_mm, 0)} mm · distance error ${fmt(n.distance_error_mm, 0)} mm · turn ${fmt(n.turn_deg, 1)}° · ` +
        `tilt ${fmt(n.tilt_deg, 1)}° · roll ${fmt(n.roll_deg, 1)}° · ${n.steady ? "picture steady" : "waiting for a steady picture"}` : "";
      $("placeHint").textContent = r.hint || "";
      $("fovBtn").hidden = !r.offer_fov;
      $("placePicWrap").hidden = !r.picture;
      if (r.picture) $("placePic").src = "data:image/jpeg;base64," + r.picture;
    }
  } catch (e) { /* keep trying */ }
  setTimeout(pollPlacement, 1200);
}
$("fovBtn").onclick = () => get("/api/calib/fov");
$("placeBtn").onclick = () => {
  placing = !placing;
  $("placeBtn").textContent = placing ? "Stop live check" : "Start live check";
  if (placing) pollPlacement();
};

poll(); pollImg();
