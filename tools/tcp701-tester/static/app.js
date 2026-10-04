// TCP-701 tester dashboard — live traffic, server-side access decisions, QR generator.
const $ = (id) => document.getElementById(id);
const entries = [];            // all entries received (kept for re-filtering)
let status = {};
let accDirty = false;          // access form edited but not applied
let keyDirty = false;          // QR key edited here but not loaded into the device
let lastQr = null;             // {preset, params, result}
let fsSize = 160;              // fullscreen QR size in CSS px (~2.5 cm on most phones)

// ------------------------------------------------------------------ helpers
function toast(msg, err = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "show" + (err ? " err" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.className = ""), 3500);
}

async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.detail || res.statusText);
  return json;
}

const run = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const hex2 = (n) => (+n & 0xff).toString(16).padStart(2, "0").toUpperCase();
const hex4 = (n) => (+n & 0xffff).toString(16).padStart(4, "0").toUpperCase();
const bcd = (n) => hex2(Math.floor(n / 10) * 16 + (n % 10));
const store = {
  get(k, d) { try { return localStorage.getItem("tcp701." + k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("tcp701." + k, v); } catch {} },
};
const pad = (n) => String(n).padStart(2, "0");
const toLocalInput = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
const fromLocalInput = (s) => Math.floor(new Date(s).getTime() / 1000);
const randomKey = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => hex2(b)).join("");

// ------------------------------------------------------------------ traffic table
function matches(e) {
  const f = $("filter").value.trim().toLowerCase();
  if ($("hideHb").checked && e.cmd === "0101") return false;
  if ($("onlyRx").checked && e.dir !== "rx" && e.kind !== "access") return false;
  if (!f) return true;
  return [e.cmd, e.cmd_name, e.desc, e.hex, e.text, e.note].some((v) => v && String(v).toLowerCase().includes(f));
}

function rowHtml(e) {
  if (e.kind === "info" || e.kind === "note" || e.kind === "access") {
    const icon = { info: "ℹ", note: "✎", access: "⚖" }[e.kind];
    return `<tr class="${e.kind}" data-id="${e.id}"><td>${e.id}</td><td>${e.time}</td><td>${icon}</td><td colspan="7">${esc(e.text)}</td></tr>`;
  }
  if (e.kind === "junk") {
    return `<tr class="junk ${e.dir}" data-id="${e.id}"><td>${e.id}</td><td>${e.time}</td><td class="dir">${e.dir === "tx" ? "→" : "←"}</td><td colspan="5">${esc(e.text)}</td><td class="desc">${esc(e.hex)}</td><td></td></tr>`;
  }
  const cls = [e.dir, e.ok ? "" : "bad", e.type === 3 ? "event" : ""].join(" ");
  return `<tr class="${cls}" data-id="${e.id}">
    <td>${e.id}</td><td>${e.time}</td><td class="dir">${e.dir === "tx" ? "→ out" : "← in"}</td>
    <td>${e.cmd}</td><td class="name">${esc(e.cmd_name)}</td><td>${e.type_name}</td>
    <td>${e.status}</td><td>${e.ok ? "✔" : "✖"}</td><td class="desc">${esc(e.desc)}</td><td>${esc(e.note)}</td></tr>`;
}

function addEntry(e, render = true) {
  entries.push(e);
  if (entries.length > 5000) entries.splice(0, 1000);
  if (e.kind === "access" || (e.dir === "tx" && /ALLOW|DENY/.test(e.note || ""))) renderAccessHistory();
  if (!render || $("pause").checked || !matches(e)) return;
  const wrap = $("tablewrap");
  const atBottom = wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight < 40;
  $("rows").insertAdjacentHTML("beforeend", rowHtml(e));
  if (atBottom) wrap.scrollTop = wrap.scrollHeight;
  updateCount();
}

function rerender() {
  $("rows").innerHTML = entries.filter(matches).map(rowHtml).join("");
  $("tablewrap").scrollTop = $("tablewrap").scrollHeight;
  updateCount();
  renderAccessHistory();
}

function updateCount() {
  const frames = entries.filter((e) => e.kind === "frame");
  const tx = frames.filter((e) => e.dir === "tx").length;
  $("count").textContent = `${frames.length} frames (${tx} out / ${frames.length - tx} in)`;
}

function showDetail(id) {
  const e = entries.find((x) => x.id === id);
  if (!e) return;
  document.querySelectorAll("#rows tr.sel").forEach((r) => r.classList.remove("sel"));
  document.querySelector(`#rows tr[data-id="${id}"]`)?.classList.add("sel");
  if (e.kind !== "frame") {
    const extra = e.request ? "\n" + JSON.stringify(e.request, null, 2) : e.hex ? "\n" + e.hex : "";
    $("detail").innerHTML = `<div class="out">${esc(e.text)}${esc(extra)}</div>`;
    return;
  }
  const fields = e.fields.map(([n, h]) => `<div class="fld f-${n}"><small>${n}</small>${h || "—"}</div>`).join("");
  $("detail").innerHTML = `
    <div><b>${e.dir === "tx" ? "→ sent" : "← received"}</b> ${e.time} · ${esc(e.cmd_name)} · ${e.type_name} · status ${e.status}
      · len ${e.length} · checksum ${e.ok ? "OK ✔" : "<span style='color:var(--bad)'>BAD ✖</span>"}
      <button onclick="navigator.clipboard.writeText('${e.hex}')">copy hex</button></div>
    <div class="fields">${fields}</div>
    <div class="muted">${esc(e.desc)}${e.note ? " · " + esc(e.note) : ""}</div>`;
}

// ------------------------------------------------------------------ status
function setStatus(s) {
  status = s;
  const live = s.connected;
  $("led").className = "led " + (live ? "on" : s.mode === "listen" ? "wait" : "off");
  $("statusText").textContent = live
    ? (s.mode === "listen" ? `device connected from ${s.peer}` : `connected to ${s.peer}`)
    : s.mode === "listen" ? `listening on :${s.listen_port} — waiting for device…` : "stopped";
  $("devSn").textContent = s.device_sn || "—";
  if (s.device_sn && (!$("qrSn").dataset.touched)) $("qrSn").value = s.device_sn;
  if (document.activeElement !== $("hdrSerial")) $("hdrSerial").value = s.header_serial;
  $("reqType").value = String(s.req_type);
  $("wireMode").value = s.wire_mode;
  $("prefixMode").value = s.prefix_mode;
  $("wireNow").textContent = `tx ${s.wire} / rx ${s.rx_wire}` + (s.prefix ? " · ID " + s.prefix : "");

  document.querySelectorAll("[data-auto]").forEach((cb) => (cb.checked = !!s.auto[cb.dataset.auto]));
  $("auto0108").value = s.auto["0108"];
  if (!accDirty) {
    $("accPolicy").value = s.access.policy;
    $("accGrant").value = s.access.grant;
    $("accDoor").value = s.access.door;
    $("accUnlockSec").value = s.access.unlock_seconds;
    $("accDenyBeeps").value = s.access.deny_beeps || 0;
    $("accAllow").value = (s.access.allow_list || []).join("\n");
  }
  // The key loaded into the device (0601) lives on the server, so every screen (PC, phone) uses it.
  if (s.access.qr_key && !keyDirty) {
    $("qrKey").value = s.access.qr_key;
    $("qrKeyFmt").value = s.access.qr_key_format;
  }
  updateKeyState();
  renderPending(s.pending_access || []);
}

function updateKeyState() {
  const loaded = status.access && status.access.qr_key;
  const same = loaded && $("qrKey").value.trim().toUpperCase() === loaded;
  $("keyState").textContent = same ? "✔ same key as loaded in device" : loaded ? "⚠ differs from the key in the device" : "⚠ no key loaded into device yet";
  $("keyState").className = same ? "ok-text" : "warn-text";
}

function renderPending(items) {
  $("pendingCount").textContent = items.length;
  if (!items.length) { $("pendingList").innerHTML = `<p class="muted">None. Scan a card / QR / PIN at the device.</p>`; return; }
  $("pendingList").innerHTML = items.slice().reverse().map((it) => `
    <div class="req ${it.rule_verdict}">
      <div class="head"><span>#${it.id} · ${esc(it.time)} · <b>${esc(it.kind)}</b></span><span class="muted">rules: ${it.rule_verdict}</span></div>
      <div class="cred">${esc(it.credential || "—")}</div>
      <div class="muted small">${esc(Object.entries(it.decoded).map(([k, v]) => `${k}=${v}`).join(", "))}</div>
      ${it.qr ? `<div class="muted small">QR: card ${esc(it.qr.card_id)} · SN ${esc(it.qr.device_sn)} · doors ${esc(it.qr.door_list)} · ${esc(it.qr.start_text)} → ${esc(it.qr.end_text)} · CRC ${it.qr.crc_ok ? "ok" : "BAD"}</div>` : ""}
      ${it.reasons.length ? `<div class="reasons">${esc(it.reasons.join("; "))}</div>` : ""}
      <div class="btns"><button class="ok" data-answer="${it.id}" data-allow="1">✔ Allow</button><button class="bad" data-answer="${it.id}" data-allow="0">✖ Deny</button></div>
    </div>`).join("");
}

function renderAccessHistory() {
  const rows = entries.filter((e) => e.kind === "access" || (e.dir === "tx" && /ALLOW|DENY/.test(e.note || ""))).slice(-12);
  $("accessHistory").innerHTML = rows.length
    ? rows.map((e) => `${e.time}  ${esc(e.kind === "access" ? e.text : "→ " + e.note)}`).join("<br>")
    : "—";
}

// ------------------------------------------------------------------ websocket
function connectWs() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.event === "history") { entries.length = 0; msg.entries.forEach((e) => addEntry(e, false)); rerender(); }
    else if (msg.event === "entry") addEntry(msg.entry);
    else if (msg.event === "status") setStatus(msg.status);
    else if (msg.event === "access_pending") toast(`Access request: ${msg.item.kind} ${msg.item.credential} — Allow/Deny in Access tab`);
  };
  ws.onclose = () => { $("statusText").textContent = "dashboard server offline — retrying"; setTimeout(connectWs, 1500); };
  setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000);
}

// ------------------------------------------------------------------ commands
async function sendCmd(cmd, data = "") {
  const r = await api("/api/cmd", { cmd, data });
  $("lastReply").textContent = r.reply ? JSON.stringify(r.reply, null, 2) : "no reply (timeout)";
  if (!r.reply) toast(`no reply to ${cmd}`, true);
  else toast(`${cmd}: ${r.reply.desc || "status " + r.reply.status}`, r.reply.status !== 0);
  return r.reply;
}

function bcdNow() {
  const d = new Date();
  const wd = d.getDay() === 0 ? 7 : d.getDay(); // 1=Mon..7=Sun (unconfirmed, see test 2.4)
  return [d.getSeconds(), d.getMinutes(), d.getHours(), wd, d.getDate(), d.getMonth() + 1, d.getFullYear() % 100].map(bcd).join("");
}

// ------------------------------------------------------------------ QR
function qrParamsFromForm() {
  return {
    key: $("qrKey").value.trim(),
    key_format: $("qrKeyFmt").value,
    content_format: $("qrContentFmt").value,
    card_id: $("qrCard").value.trim(),
    device_sn: $("qrSn").value.trim(),
    doors: $("qrDoors").value.split(/[ ,;]+/).filter(Boolean).map(Number),
    start: fromLocalInput($("qrStart").value),
    duration_min: +$("qrDur").value,
    validity: fromLocalInput($("qrValidity").value),
    limit: +$("qrLimit").value,
    card_type: parseInt($("qrCardType").value, 16),
  };
}

function fillQrForm({ start, duration, validity, doors = "1", limit = 0, sn }) {
  $("qrStart").value = toLocalInput(new Date(start * 1000));
  $("qrDur").value = duration;
  $("qrValidity").value = toLocalInput(new Date(validity * 1000));
  $("qrDoors").value = doors;
  $("qrLimit").value = limit;
  if (sn) $("qrSn").value = sn;
}

async function generateQr(preset) {
  const now = Math.floor(Date.now() / 1000);
  const sn = status.device_sn || $("qrSn").value.trim();
  const base = { start: now - 60, duration: 5, validity: now + 365 * 86400, doors: "1", limit: 0, sn };
  const extra = {};
  if (!$("qrKey").value.trim()) { $("qrKey").value = randomKey(); store.set("qrKey", $("qrKey").value); }
  switch (preset) {
    case "form": break;
    case "valid": fillQrForm(base); break;
    case "expired": fillQrForm({ ...base, start: now - 3600, duration: 5 }); break;
    case "future": fillQrForm({ ...base, start: now + 3600 }); break;
    case "wrongsn": fillQrForm({ ...base, sn: ((parseInt(sn, 16) + 1) >>> 0).toString(16).padStart(8, "0").toUpperCase() }); break;
    case "badcrc": fillQrForm(base); extra.bad_crc = true; break;
    case "wrongkey": fillQrForm(base); extra.encrypt_key = randomKey(); break;
    case "door2": fillQrForm({ ...base, doors: "2" }); break;
    case "limit1": fillQrForm({ ...base, limit: 1 }); break;
    case "acctexp": fillQrForm({ ...base, validity: now - 86400 }); break;
  }
  const params = { ...qrParamsFromForm(), ...extra };
  const r = await api("/api/qr/generate", params);
  lastQr = { preset, params, result: r };
  $("qrOut").hidden = false;
  $("qrSvg").innerHTML = r.svg;
  const label = `${preset.toUpperCase()} · card ${params.card_id} · doors ${r.summary.doors} · ${r.summary.start} → ${r.summary.end}`;
  $("qrLabel").textContent = label;
  $("qrFields").innerHTML = r.fields.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("") +
    `<tr><td>validity</td><td>${esc(r.summary.validity)}</td></tr><tr><td>QR version</td><td>${r.qr_version}</td></tr>`;
  $("qrContent").textContent = `content (${r.content_format}): ${r.content}\nplain: ${r.plain}`;
  if ($("fullscreen").hidden === false) showFullscreen();
}

function showFullscreen() {
  if (!lastQr) return;
  $("fsSvg").innerHTML = lastQr.result.svg;
  const svg = $("fsSvg").querySelector("svg");
  svg.style.width = svg.style.height = fsSize + "px";
  $("fsSize").textContent = `${fsSize}px`;
  $("fsLabel").textContent = $("qrLabel").textContent;
  $("fullscreen").hidden = false;
}

// ------------------------------------------------------------------ bindings
function bind() {
  // connection
  $("btnListen").onclick = run(() => api("/api/listen", { port: +$("listenPort").value }));
  $("btnConnect").onclick = run(async () => {
    await api("/api/connect", { host: $("host").value.trim(), port: +$("port").value });
    store.set("host", $("host").value.trim()); store.set("port", $("port").value);
  });
  $("btnDisconnect").onclick = run(() => api("/api/disconnect", {}));
  $("btnProbe").onclick = run(async (ev) => {
    const scan = ev.shiftKey;
    toast(scan ? "scanning /24 for the port…" : "probing…");
    const r = await api("/api/probe", { host: $("host").value.trim(), port: +$("port").value, scan_subnet: scan });
    toast(r.found.length ? `port open on: ${r.found.join(", ")}` : "nothing answered", !r.found.length);
  });
  $("hdrSerial").onchange = run(() => api("/api/settings", { header_serial: $("hdrSerial").value.trim() }));
  $("reqType").onchange = run(() => api("/api/settings", { req_type: +$("reqType").value }));
  $("wireMode").onchange = run(() => api("/api/settings", { wire_mode: $("wireMode").value }));
  $("prefixMode").onchange = run(() => api("/api/settings", { prefix_mode: $("prefixMode").value }));

  // traffic
  ["filter", "hideHb", "onlyRx"].forEach((id) => ($(id).oninput = rerender));
  $("pause").onchange = () => !$("pause").checked && rerender();
  $("btnClear").onclick = () => { $("rows").innerHTML = ""; entries.length = 0; updateCount(); renderAccessHistory(); };
  $("rows").onclick = (ev) => { const tr = ev.target.closest("tr"); if (tr) showDetail(+tr.dataset.id); };

  // tabs
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
    document.querySelectorAll(".tabs button, .tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $("tab-" + b.dataset.tab).classList.add("active");
    store.set("tab", b.dataset.tab);
  }));

  // generic command buttons
  $("btnRecords").onclick = run(async () => {
    $("recordsInfo").textContent = "downloading…";
    const r = await api("/api/records/download", {});
    $("recordsInfo").textContent = `${r.count} records saved to logs/${r.file}` + (r.complete ? "" : " — INCOMPLETE (device stopped answering)");
    toast(`${r.count} records downloaded`);
  });
  document.querySelectorAll("[data-cmd]").forEach((b) => (b.onclick = run(() => sendCmd(b.dataset.cmd, b.dataset.data || ""))));
  $("btnAny").onclick = run(() => sendCmd($("anyCmd").value, $("anyData").value));

  // access
  $("btnMode0106").onclick = run(() => sendCmd("0106", $("mode0106").value));
  $("btnMode0602").onclick = run(() => sendCmd("0602", $("mode0602").value));
  ["accPolicy", "accGrant", "accUnlockSec", "accDenyBeeps", "accDoor", "accAllow", "accQrList"].forEach((id) => ($(id).oninput = () => (accDirty = true)));
  $("btnAccSave").onclick = run(async () => {
    await api("/api/settings", { access: {
      policy: $("accPolicy").value, grant: $("accGrant").value, door: +$("accDoor").value || 1,
      unlock_seconds: Math.min(254, Math.max(0, +$("accUnlockSec").value || 0)),
      deny_beeps: +$("accDenyBeeps").value || 0,
      qr_require_list: $("accQrList").checked,
      allow_list: $("accAllow").value.split(/\n+/).map((s) => s.trim()).filter(Boolean),
    } });
    accDirty = false;
    toast("access settings applied");
  });
  $("pendingList").onclick = run(async (ev) => {
    const b = ev.target.closest("[data-answer]");
    if (!b) return;
    await api("/api/access/answer", { id: +b.dataset.answer, allow: b.dataset.allow === "1" });
  });

  // QR
  $("qrKey").value = store.get("qrKey", "") || randomKey();
  $("qrKey").oninput = () => { keyDirty = true; store.set("qrKey", $("qrKey").value.trim()); updateKeyState(); };
  $("btnKeyRandom").onclick = () => { keyDirty = true; $("qrKey").value = randomKey(); store.set("qrKey", $("qrKey").value); updateKeyState(); toast("new key — press Load to device before scanning"); };
  $("btnKeyLoad").onclick = run(async () => {
    if (!confirm("Load this key with 0601? Previously issued QR codes stop working.")) return;
    const r = await api("/api/qr/load_key", { key: $("qrKey").value.trim(), key_format: $("qrKeyFmt").value });
    keyDirty = false;
    toast(r.reply ? `0601 status ${r.reply.status}` : "no reply to 0601", !r.reply || r.reply.status !== 0);
  });
  $("qrKeyFmt").onchange = run(() => api("/api/settings", { access: { qr_key_format: $("qrKeyFmt").value } }));
  $("qrSn").oninput = () => ($("qrSn").dataset.touched = "1");
  document.querySelectorAll("[data-preset]").forEach((b) => (b.onclick = run(() => generateQr(b.dataset.preset))));
  $("btnQrFull").onclick = showFullscreen;
  $("qrCardBox").onclick = showFullscreen;
  $("fsClose").onclick = () => ($("fullscreen").hidden = true);
  $("fsSmaller").onclick = () => { fsSize = Math.max(80, fsSize - 20); store.set("fsSize", fsSize); showFullscreen(); };
  $("fsBigger").onclick = () => { fsSize = Math.min(900, fsSize + 20); store.set("fsSize", fsSize); showFullscreen(); };
  document.querySelectorAll("[data-result]").forEach((b) => (b.onclick = run(async () => {
    if (!lastQr) return toast("generate a QR first", true);
    const p = lastQr.params, s = lastQr.result.summary;
    const text = `QR SCAN RESULT: ${b.dataset.result.toUpperCase()} — preset ${lastQr.preset}, card ${p.card_id}, SN ${p.device_sn}, doors ${s.doors}, ` +
      `${s.start} → ${s.end}, limit ${s.limit}, key ${p.key_format}/${p.content_format}` +
      (p.bad_crc ? ", BAD CRC" : "") + (p.encrypt_key ? ", WRONG KEY" : "") +
      ($("qrResultNote").value.trim() ? ` — ${$("qrResultNote").value.trim()}` : "");
    await api("/api/note", { text });
    $("qrResultNote").value = "";
    toast("result saved to session log");
  })));
  $("btnQrDecode").onclick = run(async () => {
    const r = await api("/api/qr/decode", { content: $("qrDecodeIn").value, key: $("qrKey").value.trim(),
      key_format: $("qrKeyFmt").value, device_sn: status.device_sn || null, door: +$("accDoor").value || 1 });
    $("qrDecodeOut").hidden = false;
    $("qrDecodeOut").textContent = (r.problems.length ? "PROBLEMS: " + r.problems.join("; ") : "VALID ✔") + "\n" + JSON.stringify(r.info, null, 2);
  });

  // door
  $("btnUnlock").onclick = run(() => sendCmd("0201", hex2($("unlockSec").value)));
  $("btnSyncTime").onclick = run(() => sendCmd("0103", bcdNow()));
  $("btnRelay").onclick = run(() => sendCmd("0203", $("relaySec").value.trim().padStart(2, "0")));
  $("btnHb").onclick = run(() => sendCmd("0205", hex4($("hbSec").value)));
  $("btnOpenMode").onclick = run(() => sendCmd("0107", $("openMode").value));
  $("btnTimeLimit").onclick = run(() => sendCmd("0204", $("timeLimit").value));
  document.querySelectorAll("[data-auto]").forEach((cb) => (cb.onchange = run(() => api("/api/settings", { auto: { [cb.dataset.auto]: cb.checked } }))));
  $("auto0108").onchange = run(() => api("/api/settings", { auto: { "0108": $("auto0108").value } }));

  // raw
  $("btnRaw").onclick = run(async () => {
    const r = await api("/api/raw", { hex: $("rawHex").value, fix_checksum: $("rawFix").checked });
    toast("sent " + r.sent);
  });
  $("btnBuild").onclick = run(() => api("/api/build", {
    head: $("bHead").value, serial: $("bSerial").value.trim() || null, cmd: $("bCmd").value.trim(),
    type: +$("bType").value, status: parseInt($("bStatus").value || "0", 16), data: $("bData").value,
    bad_checksum: $("bBad").checked,
  }));
  $("btnDouble").onclick = run(async () => {
    const s = $("hdrSerial").value.trim().padStart(8, "0");
    const t = hex2($("reqType").value);
    const f = (cmd) => { const body = `0000${s}${cmd}${t}00`; const sum = body.match(/../g).reduce((a, h) => a + parseInt(h, 16), 0) & 0xffff; return "FA" + hex4(sum) + body; };
    await api("/api/raw", { hex: f("0002") + f("0202"), fix_checksum: false });
  });

  // notes
  $("btnNote").onclick = run(async () => {
    const text = $("noteText").value.trim();
    if (!text) return;
    await api("/api/note", { text });
    $("noteText").value = "";
    toast("note saved to session log");
  });
}

async function init() {
  $("host").value = store.get("host", $("host").value);
  $("port").value = store.get("port", $("port").value);
  fsSize = +store.get("fsSize", fsSize);
  const now = Math.floor(Date.now() / 1000);
  fillQrForm({ start: now - 60, duration: 5, validity: now + 365 * 86400 });
  const cmds = await api("/api/commands");
  $("anyCmd").innerHTML = Object.entries(cmds).map(([k, v]) => `<option value="${k}">${k} ${v}</option>`).join("");
  const net = await api("/api/netinfo");
  $("pcIps").textContent = net.ips.length ? net.ips.join(" / ") : "run ipconfig";
  if (net.listen_port) $("listenPort").value = net.listen_port;
  bind();
  const tab = store.get("tab", "access");
  document.querySelector(`.tabs button[data-tab="${tab}"]`)?.click();
  connectWs();
}
init();
