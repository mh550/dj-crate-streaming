// Crates web client — vanilla JS, talks only to the crate service (/api/*).
// Audio comes from Navidrome via the service's signed 302 redirects (/api/stream/<id>).
const $ = (s, r = document) => r.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const dur = s => `${Math.floor((s || 0) / 60)}:${String((s || 0) % 60).padStart(2, "0")}`;
const fmt = t => [t.suffix, t.bitRate ? `${t.bitRate}k` : null, t.bitDepth ? `${t.bitDepth}/${(t.sampleRate || 0) / 1000}` : null].filter(Boolean).join(" · ");

async function api(path, opts) {
  const r = await fetch(path, opts && { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(opts) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

const state = { playlists: [], current: null, playingId: null };

// ---- tabs
document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => {
  document.querySelectorAll(".tabs button, .tab").forEach(x => x.classList.remove("active"));
  b.classList.add("active"); $("#tab-" + b.dataset.tab).classList.add("active");
  ({ wanted: loadWanted, log: loadEvents })[b.dataset.tab]?.();
});

// ---- status
async function loadStatus() {
  try {
    const s = await api("/api/status");
    $("#server").textContent = `${s.serverType || "subsonic"} ${s.serverVersion || ""} · ${s.user} · ${s.crates} crate${s.crates === 1 ? "" : "s"}`;
    $("#wanted-count").textContent = s.wanted || "";
  } catch (e) { $("#server").textContent = e.message; $("#server").classList.add("err"); }
}

// ---- playlists
async function loadPlaylists() {
  state.playlists = await api("/api/playlists");
  const ul = $("#playlists"); ul.innerHTML = "";
  for (const p of state.playlists) {
    const li = el("li", "playlist");
    const grow = el("div", "grow");
    grow.append(el("div", "title", p.name));
    const sub = `${p.songCount} tracks · ${dur(p.duration)}` + (p.summary ? ` · ${p.summary.ok}/${p.summary.total} crate-ready` : "");
    grow.append(el("div", "sub", sub));
    li.append(grow);
    if (p.crate) li.append(el("span", "badge crate", "crate"));
    li.onclick = () => openPlaylist(p.id);
    ul.append(li);
  }
}

async function openPlaylist(id) {
  const p = await api("/api/playlists/" + id);
  state.current = p;
  $("#playlists").classList.add("hidden"); $("#detail").classList.remove("hidden");
  $("#detail-name").textContent = p.name;
  $("#detail-crate").checked = p.crate;
  $("#detail-summary").textContent = p.summary
    ? `crate · ${p.summary.ok} ready · ${p.summary.needs_source} need sourcing` + (p.summary.sourcing ? ` · ${p.summary.sourcing} downloading` : "") + (p.summary.failed ? ` · ${p.summary.failed} failed` : "")
    : `${p.songCount} tracks · ${dur(p.duration)} · not a crate`;
  const ol = $("#tracks"); ol.innerHTML = "";
  p.entries.forEach(t => {
    const li = el("li");
    const play = el("button", "play" + (state.playingId === t.id ? " playing" : ""), "▶");
    play.onclick = () => playTrack(t);
    const grow = el("div", "grow");
    grow.append(el("div", "title", t.title));
    grow.append(el("div", "sub", `${t.artist || "?"} · ${t.album || ""}`));
    li.append(play, grow, el("span", "fmt", fmt(t) + " · " + dur(t.duration)));
    if (t.crateStatus) { const b = el("span", "badge " + t.crateStatus, t.crateStatus.replace("_", " ")); b.title = t.crateReason || ""; li.append(b); }
    ol.append(li);
  });
}
$("#back").onclick = () => { $("#detail").classList.add("hidden"); $("#playlists").classList.remove("hidden"); loadPlaylists(); };
$("#detail-crate").onchange = async e => {
  const p = state.current; e.target.disabled = true;
  try { await api(`/api/playlists/${p.id}/crate`, { enabled: e.target.checked }); await openPlaylist(p.id); await loadStatus(); }
  catch (err) { alert(err.message); e.target.checked = !e.target.checked; }
  finally { e.target.disabled = false; }
};

// ---- wanted
// the last download check (spec §3a): verdict, then what was measured, then why
function verifyLine(v) {
  const m = v.measurements || {}, bits = [];
  if (m.cutoff_khz !== undefined) bits.push(m.cutoff_khz ? `cutoff ≈${m.cutoff_khz} kHz` : "cutoff < 11 kHz");
  if (m.bits_used) bits.push(`${m.bits_used}-bit used`);
  if (m.peak_db !== undefined && m.peak_db !== null) bits.push(`peak ${Number(m.peak_db).toFixed(1)} dB`);
  if (m.fingerprint_ber !== undefined) bits.push(`fingerprint ${m.fingerprint_ber}`);
  const why = [...(v.problems || []).map(p => "✗ " + p), ...(v.warnings || []).map(w => "! " + w)];
  return `last download ${v.ok ? "passed" : "rejected"} (${v.tier}): ${v.file} · ${bits.join(" · ")}${why.length ? " · " + why.join(" · ") : ""}`;
}

async function loadWanted() {
  const items = await api("/api/wanted"); const ul = $("#wanted"); ul.innerHTML = "";
  if (!items.length) ul.append(el("li", "muted", "nothing to source — every crate track meets policy"));
  for (const t of items) {
    const li = el("li"); const grow = el("div", "grow");
    grow.append(el("div", "title", `${t.artist} — ${t.title}`));
    grow.append(el("div", "sub", `${t.album || ""} ${t.year || ""} · ${dur(t.duration)} · ${t.crates.length ? "in " + t.crates.join(", ") : "external"} · tier ${t.tier}`));
    if (t.verify) grow.append(el("div", "sub", verifyLine(t.verify)));
    li.append(grow, el("span", "badge " + t.status, t.reason)); ul.append(li);
  }
}

// ---- search
$("#search-form").onsubmit = async e => {
  e.preventDefault(); const res = await api("/api/search?q=" + encodeURIComponent($("#q").value));
  const ul = $("#results"); ul.innerHTML = "";
  for (const t of res) {
    const li = el("li"); const play = el("button", "play", "▶"); play.onclick = () => playTrack(t);
    const grow = el("div", "grow"); grow.append(el("div", "title", t.title)); grow.append(el("div", "sub", `${t.artist || "?"} · ${t.album || ""}`));
    li.append(play, grow, el("span", "fmt", fmt(t) + " · " + dur(t.duration))); ul.append(li);
  }
};

// ---- log
async function loadEvents() {
  const ev = await api("/api/events"); const ul = $("#events"); ul.innerHTML = "";
  for (const e of ev) ul.append(el("li", null, `${new Date(e.ts * 1000).toLocaleTimeString()}  ${e.kind}  ${e.playlist_id || ""} ${e.song_id || ""}  ${e.detail || ""}`));
}

// ---- player: the stream tier (spec §1) is one server-side setting, so it survives a cache clear
function streamUrl(id) {
  const u = new URL("/api/stream/" + id, location.href);
  u.searchParams.set("tier", $("#quality").value);
  return u.toString();
}
async function loadStreamTier() {   // the menu comes from the server's table; the HTML options are the fallback
  try {
    const s = await api("/api/stream-tier"), sel = $("#quality"); sel.innerHTML = "";
    for (const [name, t] of Object.entries(s.tiers))
      sel.append(new Option(`${name} · ${t.format === "raw" ? "original" : `${t.format} ${t.maxBitRate}k`}`, name));
    sel.value = s.tier;
  } catch (e) { /* keep the static menu, crate selected (= the server's default) */ }
}
function playTrack(t) {
  state.playingId = t.id;
  $("#player").classList.remove("hidden");
  $("#np-title").textContent = t.title; $("#np-sub").textContent = `${t.artist || ""} · ${fmt(t)}`;
  const a = $("#audio"); a.src = streamUrl(t.id); a.play().catch(() => {});
  document.querySelectorAll(".play").forEach(b => b.classList.remove("playing"));
  if ("mediaSession" in navigator) navigator.mediaSession.metadata = new MediaMetadata({ title: t.title, artist: t.artist || "", album: t.album || "" });
  if (state.current) openPlaylist(state.current.id);
}
$("#quality").onchange = async () => {
  api("/api/stream-tier", { tier: $("#quality").value }).catch(e => alert(e.message));   // saved in parallel
  const a = $("#audio"); if (!state.playingId) return;
  const t = a.currentTime, wasPlaying = !a.paused;
  a.src = streamUrl(state.playingId); a.currentTime = t; if (wasPlaying) a.play().catch(() => {});
};

// ---- reconcile
$("#btn-reconcile").onclick = async () => {
  const b = $("#btn-reconcile"); b.disabled = true; b.textContent = "reconciling…";
  try { const r = await api("/api/reconcile", {}); b.textContent = `ok ${r.tracks_ok} · need ${r.tracks_needing_source}`; await loadPlaylists(); await loadStatus(); if (state.current) openPlaylist(state.current.id); }
  catch (e) { b.textContent = e.message; }
  finally { b.disabled = false; setTimeout(() => b.textContent = "reconcile", 2500); }
};

loadStatus(); loadPlaylists(); loadStreamTier();
