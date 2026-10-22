// Crates web client — vanilla JS, talks only to the crate service (/api/*).
// Audio comes from Navidrome via the service's signed 302 redirects (/api/stream/<id>).
const $ = (s, r = document) => r.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const dur = s => `${Math.floor((s || 0) / 60)}:${String((s || 0) % 60).padStart(2, "0")}`;
const fmt = t => [t.suffix, t.bitRate ? `${t.bitRate}k` : null, t.bitDepth ? `${t.bitDepth}/${(t.sampleRate || 0) / 1000}` : null].filter(Boolean).join(" · ");

async function api(path, opts) {
  const r = await fetch(path, opts && { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(opts) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(j.error || r.statusText); e.status = r.status; throw e; }
  return j;
}
// what a failed playlist change means, in words for a phone (the server's own text is the fallback)
function changeError(e) {
  if (e.status === 409) return "This playlist is a crate by its name: remove [crate]/🎛 from the name to change this.";
  if (e.status === 502) return "Navidrome didn't keep the change; nothing was changed here.";
  if (e.status === 503) return "Navidrome or the worker is busy, try again in a moment.";
  return e.message;
}

const state = { playlists: [], current: null, playingId: null };

// ---- tabs
document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => {
  document.querySelectorAll(".tabs button, .tab").forEach(x => x.classList.remove("active"));
  b.classList.add("active"); $("#tab-" + b.dataset.tab).classList.add("active");
  ({ wanted: loadWanted, log: loadEvents, identity: loadIdentity })[b.dataset.tab]?.()?.catch(e => alert(e.message));
});

// ---- status
// health:begin
// playlist health (M9 §7): one line per playlist whose entries point at files Navidrome no longer has, in the
// worker's words (sourcing.worker.health_detail). Healing stays manual.
function healthLines(rows) {
  return (rows || []).map(r => r.missing === 1
    ? `1 entry in ${r.name} points at a missing file`
    : `${r.missing} entries in ${r.name} point at missing files`);
}
// health:end
async function loadStatus() {
  try {
    const s = await api("/api/status");
    $("#server").textContent = `${s.serverType || "subsonic"} ${s.serverVersion || ""} · ${s.user} · ${s.crates} crate${s.crates === 1 ? "" : "s"}`;
    $("#wanted-count").textContent = s.wanted || "";
    const lines = healthLines(s.playlistHealth), banner = $("#health");
    banner.replaceChildren(...lines.map(t => el("div", null, t)));
    banner.classList.toggle("hidden", !lines.length);
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
    const sub = `${p.songCount} tracks · ${dur(p.duration)}` + (p.summary ? ` · ${p.summary.ok}/${p.summary.total} ${p.crate ? "crate-ready" : "ready"}` : "");
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
  const label = p.crate ? "crate" : null;
  $("#detail-summary").textContent = p.summary
    ? `${label || "tiered"} · ${p.summary.ok} ready · ${p.summary.needs_source} need sourcing` + (p.summary.sourcing ? ` · ${p.summary.sourcing} downloading` : "") + (p.summary.failed ? ` · ${p.summary.failed} failed` : "") + (p.summary.review ? ` · ${p.summary.review} to decide` : "")
    : `${p.songCount} tracks · ${dur(p.duration)} · ${label || "not a crate"}`;
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
    if (t.crateReason && ["review", "failed"].includes(t.crateStatus)) li.append(el("div", "reason", t.crateReason));   // a phone has no hover
    ol.append(li);
  });
  renderPlaylistWanted(p);
}
// A playlist's queued tracks the library does not have yet (GET /api/playlists/<id> `wanted`): each offers the same
// play-now ▶ as the Wanted tab (one POST per tap; playNow and its progress strip are shared), and says why when not.
function renderPlaylistWanted(p) {
  const box = $("#detail-wanted"), ul = $("#detail-wanted-list"), items = p.wanted || [];
  ul.innerHTML = ""; box.classList.toggle("hidden", !items.length);
  $("#detail-wanted-title").textContent = `Not in the library yet (${items.length})`;
  for (const w of items) {
    const t = { song_id: w.id, external: true, artist: w.artist, title: w.title, status: w.status, reason: w.reason,
                provisional: w.provisional, library_song_id: w.library_song_id, filed: w.filed };
    const li = el("li", "wrow"), grow = el("div", "grow"), mine = pn[w.id] && pn[w.id].active;
    const canPlayNow = !w.library_song_id && (mine || w.status === "needs_source" || (w.status === "failed" && !w.filed));
    if (canPlayNow) li.append(pnButton(t, mine));
    grow.append(el("div", "title", `${w.artist} — ${w.title}`));
    if (canPlayNow || pn[w.id]) { const b = el("div", "pn"); b.dataset.wid = w.id; b.setAttribute("role", "status"); b.setAttribute("aria-live", "polite"); pnFill(b, w.id); grow.append(b); }
    if (w.reason) grow.append(el("div", "reason", w.reason));
    li.append(grow, el("span", "badge " + w.status, w.status.replace("_", " ")));
    ul.append(li);
  }
}
$("#back").onclick = () => { $("#detail").classList.add("hidden"); $("#playlists").classList.remove("hidden"); loadPlaylists(); };
$("#detail-crate").onchange = async e => {
  const p = state.current; e.target.disabled = true;
  try { await api(`/api/playlists/${p.id}/crate`, { enabled: e.target.checked }); await openPlaylist(p.id); await loadStatus(); }
  catch (err) { alert(changeError(err)); e.target.checked = !e.target.checked; }
  finally { e.target.disabled = false; }
};

// ---- wanted
// A `review` row is a question. These reasons are the ones copy replacement leaves (crates.store.RETRYABLE_REVIEW,
// which this must match: tests/test_web_m8.py compares them): approving such a row downloads again, so they
// offer Preview/Approve like a needs_source row. Any other review reason (import's "ambiguous …") offers nothing.
const RETRYABLE_REVIEW = /^(?:kept beside |declined replacement #\d+|replacement #\d+ not made:|filed beside )/;
// the last download check (spec §3a): verdict, then what was measured, then why
function verifyLine(v) {
  const m = v.measurements || {}, bits = [];
  if (m.cutoff_khz !== undefined) bits.push(m.cutoff_khz ? `cutoff ≈${m.cutoff_khz} kHz` : "cutoff < 11 kHz");
  if (m.bits_used) bits.push(`${m.bits_used}-bit used`);
  if (m.peak_db != null) bits.push(`peak ${Number(m.peak_db).toFixed(1)} dB`);
  if (m.fingerprint_ber !== undefined) bits.push(`fingerprint ${m.fingerprint_ber}`);
  const why = [...(v.problems || []).map(p => "✗ " + p), ...(v.warnings || []).map(w => "! " + w)];
  return `last download ${v.ok ? "passed" : "rejected"} (${v.tier}): ${v.file} · ${bits.join(" · ")}${why.length ? " · " + why.join(" · ") : ""}`;
}

// proposals (D23): a new version never replaces anything by itself. Swap edits that one slot, Keep leaves it as it is.
const KIND = { version_swap: "new version", unproven_copy: "better copy, not proven the same recording" };
async function loadProposals() {
  const items = await api("/api/proposals"), ul = $("#proposals"); ul.innerHTML = "";
  $("#proposals-box").classList.toggle("hidden", !items.length);
  for (const p of items) {
    const li = el("li", "proposal"), grow = el("div", "grow");
    grow.append(el("div", "title", p.playlist_name), el("div", "sub wrap", KIND[p.kind] || p.kind), el("div", "wrap", p.summary));
    // the summary names both songs; if it ever does not, say which songs the question is about
    if (p.old_name && p.new_name && !(p.summary || "").includes(p.old_name)) grow.append(el("div", "sub wrap", `${p.old_name} → ${p.new_name}`));
    const swap = el("button", "primary", "Swap"), keep = el("button", null, "Keep");
    const answer = (action, btn) => async () => {
      swap.disabled = keep.disabled = true; const label = btn.textContent; btn.textContent = "…";
      try {
        const r = await api(`/api/proposals/${p.id}` + (action === "accept" ? "/accept" : "/decline"), {});
        // an accept can end `stale` (the slot changed, the edit was not confirmed): say why instead of claiming success
        if (action === "accept" && r.decision !== "accepted") alert(`Not swapped: ${r.result || r.decision}`);
        await loadAfterProposal();
      } catch (err) {
        alert(err.status === 409 ? `Already answered: ${err.message}` : err.message);
        if (err.status === 409) await loadAfterProposal(); else { swap.disabled = keep.disabled = false; btn.textContent = label; }
      }
    };
    swap.onclick = answer("accept", swap); keep.onclick = answer("decline", keep);
    const row = el("div", "actions"); row.append(swap, keep);
    li.append(grow, row); ul.append(li);
  }
}
async function loadAfterProposal() {
  await loadWanted(); await loadStatus();
  if (state.current) await openPlaylist(state.current.id);        // the slot may have changed under an open playlist
}

// ---- play-now (D20). Pressing ▶ on a queued track the library does not have is Michael's approval for ONE fast copy:
// the page says so, shows where the copy is (queued → downloading → checking → filed → playing), starts it when the
// file lands, and says why when it cannot. One request per tap; the polling backs off and sleeps with the page.
// pn:begin
const PN_STEPS = ["queued", "downloading", "checking", "filed", "playing"];
const PN_GIVE_UP_MS = 10 * 60 * 1000;                      // of visible waiting; a later tap on ▶ picks the watch up again
function pnDelay(n) { return Math.min(10000, Math.round(2000 * Math.pow(1.5, n))); }       // 2 s, 3, 4.5, 6.75, then 10
// Where a row (GET /api/wanted/<id>) is on the way to a playable file: one of PN_STEPS, or "ended" with the reason why.
function pnPhase(r) {
  const a = r.approval, why = r.reason || "";
  if (r.library_song_id) return { phase: "playing" };
  if (r.status === "verify") return { phase: r.filed ? "filed" : "checking" };   // today a verify row is always already filed
  if (r.status === "sourcing") return { phase: /^(?:checking|verifying)\b/i.test(r.reason || "") ? "checking" : "downloading" };
  if (r.status === "needs_source" || r.status === "failed") {
    if (r.status === "needs_source" && a && !a.used_at) return { phase: "queued" };
    if (r.status === "needs_source" && a && a.result === "started") return { phase: "downloading" };
    if (r.status === "needs_source" && a && /^ok\b/.test(a.result || "")) return { phase: "checking" };   // filed; Navidrome not listing it yet
  }
  const result = a && a.used_at && a.result && a.result !== "started" ? a.result : "";
  const parts = [why || result];                          // the row's own reason; the approval's result only when it has none
  if (r.status === "ok") return { phase: "ended", message: "It is in the library already: search for it." };
  return { phase: "ended", message: parts.join(" · ") || "Nothing is fetching this track." };
}
// pn:pure-end
const pn = {};          // wanted id -> {active, phase, note, message, tries, waited, errs, timer, paused, busy, t}
const PN_HINT = "▶ downloads a quick copy to play now";
const SILENCE = "data:audio/wav;base64,UklGRnQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YVAAAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgA==";

// A phone lets a page start audio only from a tap, and the file lands seconds later: the tap itself primes the player.
function unlockAudio() {
  const a = $("#audio");
  if (a.getAttribute("src")) return;                       // something already played here, so it is unlocked
  a.src = SILENCE; a.play().catch(() => {});
}
function pnSel(id) { return CSS.escape(id); }
function pnPaint(id) {
  document.querySelectorAll(`.pn[data-wid="${pnSel(id)}"]`).forEach(box => pnFill(box, id));
  document.querySelectorAll(`button.pn-btn[data-wid="${pnSel(id)}"]`).forEach(b => {
    const on = !!(pn[id] && pn[id].active); b.disabled = on; b.textContent = on ? "…" : "▶";
  });
}
function pnFill(box, id) {
  const s = pn[id]; box.replaceChildren();
  if (!s) { box.append(el("div", "pn-hint", PN_HINT)); return; }
  if (s.active || s.phase === "playing") {
    const at = PN_STEPS.indexOf(s.phase);
    box.append(el("div", "pn-line", s.active ? `fetching… ${s.phase}` : "playing"));
    const ol = el("ol", "pn-steps");
    PN_STEPS.forEach((n, i) => ol.append(el("li", i < at || (!s.active && i === at) ? "done" : i === at ? "now" : null, n)));
    box.append(ol);
    if (s.note) box.append(el("div", "pn-note", s.note));
  }
  if (s.message) box.append(el("div", "pn-msg", s.message));
}
function pnStop(id, message) {
  const s = pn[id]; if (!s) return;
  clearTimeout(s.timer); Object.assign(s, { active: false, timer: null, paused: false, busy: false, message });
  pnPaint(id);
}
function pnSchedule(t, delay) {
  const id = t.song_id, s = pn[id]; if (!s || !s.active) return;
  clearTimeout(s.timer); s.timer = null; s.t = t;
  if (document.hidden) { s.paused = true; return; }        // nothing is asked of the server while nobody looks
  if (s.waited >= PN_GIVE_UP_MS) return pnStop(id, "Still not here after 10 minutes. It may yet arrive: check Wanted later, or tap ▶ to keep watching.");
  s.paused = false; s.waited += delay; s.timer = setTimeout(() => pnTick(t), delay);
}
async function pnTick(t) {
  const id = t.song_id, s = pn[id];
  if (!s || !s.active || s.busy) return;
  if (document.hidden) { s.paused = true; return; }
  s.busy = true; let row;
  try { row = await api(`/api/wanted/${id}`); s.errs = 0; }
  catch (e) {
    s.busy = false;
    if (e.status === 404) return pnStop(id, "This track left the queue before a file arrived.");
    if (++s.errs >= 5) return pnStop(id, "Lost contact with the crate service. The download may still finish: check Wanted.");
    return pnSchedule(t, pnDelay(s.tries++));
  }
  s.busy = false;
  if (!s.active) return;
  const ph = pnPhase(row);
  if (ph.phase === "playing") return pnLanded(t, row);
  if (ph.phase === "ended") return pnStop(id, `Couldn't fetch it: ${ph.message}`);
  s.phase = ph.phase; pnPaint(id);
  pnSchedule(t, pnDelay(s.tries++));
}
// The file is in the library: play it (a provisional copy says so; the upgrade is queued for Michael's approval).
async function pnLanded(t, row) {
  const id = t.song_id;
  clearTimeout(pn[id].timer);
  pn[id] = { active: false, phase: "playing" };
  const ok = await playTrack({ id: row.library_song_id, title: row.title, artist: row.artist, album: row.album, provisional: row.provisional });
  if (!ok) pn[id].message = "It is here, but the browser blocked autoplay: tap ▶ to play.";
  pnPaint(id);
  if ($("#tab-wanted").classList.contains("active")) loadWanted().catch(() => {});
}
async function pnRefused(t, e) {
  const id = t.song_id, s = pn[id];
  if (e.status === 409) {                                 // already being fetched (a double tap elsewhere), or has a file, or must wait
    let row = null;
    try { row = await api(`/api/wanted/${id}`); } catch (_) { /* the refusal below stands */ }
    const ph = row && pnPhase(row);
    if (ph && ph.phase === "playing") return pnLanded(t, row);
    if (ph && ph.phase !== "ended") {                     // someone else's tap: watch it instead of starting another
      Object.assign(s, { phase: ph.phase, note: "Already being fetched (another tap or device)." });
      pnPaint(id); return pnSchedule(t, 0);
    }
    return pnStop(id, `Not started: ${e.message.split(id).join("this track")}`);
  }
  if (e.status === 404) return pnStop(id, "Not started: this track is no longer in the queue. Reload Wanted.");
  if (e.status) return pnStop(id, `Not started: ${e.message}`);
  pnStop(id, "Couldn't reach the crate service, so nothing was confirmed. Check Wanted before tapping again.");
}
async function playNow(t, btn) {
  const id = t.song_id;
  if (pn[id] && pn[id].active) return;                     // a second tap is dropped here, never sent
  btn.disabled = true;
  pn[id] = { active: true, phase: "queued", tries: 0, waited: 0, errs: 0, t };
  pnPaint(id); unlockAudio();
  try { await api(`/api/wanted/${id}/play-now`, {}); }
  catch (e) { return pnRefused(t, e); }
  pnSchedule(t, pnDelay(pn[id].tries++));
}
// The ▶ of a queued track the library does not have (the Wanted tab and a playlist's "Not in the library yet" list).
function pnButton(t, mine) {
  const pl = el("button", "play pn-btn", mine ? "…" : "▶");
  pl.setAttribute("aria-label", "Play now: downloads a quick copy of this track, then plays it");
  pl.dataset.wid = t.song_id; pl.disabled = !!mine;
  pl.onclick = () => playNow(t, pl);
  return pl;
}
// a page that was asleep (or reloaded) watches again at once
document.addEventListener("visibilitychange", () => {
  for (const s of Object.values(pn)) {
    if (!s.active || !s.t) continue;
    if (document.hidden) { clearTimeout(s.timer); s.timer = null; s.paused = true; }
    else if (s.paused) pnSchedule(s.t, 0);
  }
});
// pn:end

async function loadWanted() {
  await loadProposals().catch(e => { $("#proposals-box").classList.add("hidden"); alert(e.message); });
  const items = await api("/api/wanted"); const ul = $("#wanted"); ul.innerHTML = "";
  if (!items.length) ul.append(el("li", "muted", "nothing to source — every tiered track meets its tier"));
  for (const t of items) {
    const li = el("li", "wrow"); const grow = el("div", "grow");
    const review = t.status === "review";     // keep-both / declined / ambiguous: a decision is waiting
    const offer = !review || RETRYABLE_REVIEW.test(t.reason || "");   // only retryable reviews can be previewed or approved
    const id = t.song_id, lib = t.library_song_id, ph = pnPhase(t).phase;
    // a play-now another tab/device started, or this page before a reload: watch it instead of offering a second tap
    if (t.external && !lib && !pn[id] && t.approval && t.approval.purpose === "play-now" && PN_STEPS.slice(0, 4).includes(ph)) {
      pn[id] = { active: true, phase: ph, tries: 0, waited: 0, errs: 0, t }; pnSchedule(t, 0);
    }
    const mine = pn[id] && pn[id].active;
    const idle = !t.approval || t.approval.used_at;
    const canPlayNow = t.external && !lib && (mine || ((t.status === "needs_source" || (t.status === "failed" && !t.filed)) && idle));
    if (lib || !t.external) {                    // a file Navidrome has: play it, nothing is downloaded
      const pl = el("button", "play" + (state.playingId === (lib || id) ? " playing" : ""), "▶");
      pl.setAttribute("aria-label", "Play the library copy");
      pl.onclick = () => playTrack({ id: lib || id, title: t.title, artist: t.artist, album: t.album, provisional: t.provisional });
      li.append(pl);
    } else if (canPlayNow) {
      li.append(pnButton(t, mine));
    }
    grow.append(el("div", "title", `${t.artist} — ${t.title}`));
    grow.append(el("div", "sub wrap", `${t.album || ""} ${t.year || ""} · ${dur(t.duration)} · ${t.crates.length ? "in " + t.crates.join(", ") : "external"} · tier ${t.tier}`));
    if (lib && t.provisional) grow.append(el("div", "pn-prov", "provisional — a better copy is queued for your approval"));
    if (canPlayNow || (pn[id] && (!lib || pn[id].phase === "playing" || pn[id].message))) { const box = el("div", "pn"); box.dataset.wid = id; box.setAttribute("role", "status"); box.setAttribute("aria-live", "polite"); pnFill(box, id); grow.append(box); }
    if (t.reason) grow.append(el("div", "reason", t.reason));
    if (t.verify) grow.append(el("div", "sub wrap", verifyLine(t.verify)));
    const pending = t.approval && !t.approval.used_at, pk = t.preview && t.preview.pick;
    const busy = t.status === "sourcing" || t.status === "verify";   // in progress: shown, not offered again
    if (pending && !mine) grow.append(el("div", "sub wrap", "approved · waiting for worker"));
    else if (t.approval) grow.append(el("div", "sub wrap", `worker: ${t.approval.result}`));
    if (pk && !pending) {                      // basename only: the peer's name stays out of the UI
      grow.append(el("div", "sub wrap", `pick: ${pk.basename} · ${pk.extension} · ${pk.bit_rate ?? "?"}k · score ${pk.score.toFixed(2)}`));
      const d = el("details"); d.append(el("summary", null, "why"), el("pre", "sub wrap", t.preview.explain || "")); grow.append(d);
    } else if (t.preview && !pending) grow.append(el("div", "sub wrap", "no acceptable candidate"));
    li.append(grow);
    if (!offer) { /* an ambiguous import: nothing to search or approve, the reason above says what is waiting */ }
    else if (!pending && !busy && t.filed) {        // failed after filing ("never indexed"): nothing to preview or pick
      const rc = el("button", null, "Re-check");
      rc.onclick = async () => {
        rc.disabled = true;
        try { await api(`/api/wanted/${t.song_id}/approve`, {}); await loadWanted(); }
        catch (e) { alert(e.message); rc.disabled = false; }
      };
      li.append(rc);
    } else if (!pending && !busy) {
      const pv = el("button", null, "Preview");
      pv.onclick = async () => {
        pv.disabled = true; pv.textContent = "searching…";
        try { await api(`/api/wanted/${t.song_id}/preview`, {}); await loadWanted(); }
        catch (e) { alert(e.message); pv.disabled = false; pv.textContent = "Preview"; }
      };
      li.append(pv);
    }
    if (pk && !pending && !busy && offer) {
      const ap = el("button", null, "Approve");
      ap.onclick = async () => {
        ap.disabled = true;
        try { await api(`/api/wanted/${t.song_id}/approve`, { candidate: pk }); await loadWanted(); }
        catch (e) { alert(e.message); ap.disabled = false; }
      };
      li.append(ap);
    }
    li.append(el("span", "badge " + t.status, t.status.replace("_", " "))); ul.append(li);
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

// ---- identity (M9 §5a, R7): the identity proposal's open rows. A tap only records Michael's pick
// (POST /api/identity/choice → identity-choices.json); the worker writes tags later, never this page.
// identity:begin
const MB_RECORDING = "https://musicbrainz.org/recording/";
const len = s => s == null ? "?:??" : dur(Math.round(s));
const ID_DONE = { accept: () => "accepted", choose: c => `chosen: ${c.mbid}`, skip: () => "skipped" };
function idPaint(box, choice) {                // the choice the server holds for this row
  box.textContent = !choice ? "" : choice.stale ? "stale: pick again" : (ID_DONE[choice.action] || (() => choice.action))(choice);
}
function idLink(mbid) {
  const a = el("a", "mb", "MusicBrainz"); a.href = MB_RECORDING + encodeURIComponent(mbid); a.target = "_blank"; a.rel = "noopener";
  return a;
}
function idCandidate(c, name, checked, suggested) {
  const lab = el("label", "cand" + (suggested ? " suggested" : "")), radio = el("input"), text = el("div", "grow");
  radio.type = "radio"; radio.name = name; radio.value = c.id; radio.checked = checked;
  text.append(el("div", "wrap", `${c.title || "?"} — ${c.artist || "?"} · ${len(c.length_s)}`));
  const sub = [c.release, c.disambiguation, suggested ? "suggested: on this file's album" : ""].filter(Boolean).join(" · ");
  if (sub) text.append(el("div", "sub wrap", sub));
  text.append(idLink(c.id));
  lab.append(radio, text);
  return lab;
}
function idRow(r, i) {
  const li = el("li", "irow"), grow = el("div", "grow"), f = r.file || {};
  if (r.songId) {
    const pl = el("button", "play" + (state.playingId === r.songId ? " playing" : ""), "▶");
    pl.setAttribute("aria-label", "Play this file");
    pl.onclick = () => playTrack({ id: r.songId, title: f.title || r.path, artist: f.artist, album: f.album });
    li.append(pl);
  }
  grow.append(el("div", "title", `${f.artist || "?"} — ${f.title || "?"}`));
  grow.append(el("div", "sub wrap", [f.album, len(f.length_s)].filter(Boolean).join(" · ")));
  grow.append(el("div", "sub wrap", r.path));
  if (r.why) grow.append(el("div", "reason", r.why));
  li.append(grow, el("span", "badge", r.cls));

  const buttons = [], box = el("div", "istate");
  box.setAttribute("role", "status"); box.setAttribute("aria-live", "polite");
  let radios = [], choose = null;
  const picked = () => radios.find(x => x.checked);
  const send = (action, mbid) => async () => {
    buttons.forEach(b => b.disabled = true); box.textContent = "…";
    try { const res = await api("/api/identity/choice", { path: r.path, action, ...(mbid ? { mbid } : {}) }); r.choice = res.choice; idPaint(box, res.choice); }
    catch (e) {                                  // the server's own words, in this row, under the choice it still holds
      idPaint(box, r.choice); box.append(el("div", "err", e.message || `not saved (${e.status || "no answer"})`));
      if (e.status === 409) box.append(button("reload", () => loadIdentity()));   // "the proposal changed…; reload"
    }
    finally { buttons.forEach(b => b.disabled = false); if (choose) choose.disabled = !picked(); }
  };
  const button = (label, onclick, cls) => { const b = el("button", cls, label); b.onclick = onclick; buttons.push(b); return b; };
  if (r.cls === "search" && r.proposed) {        // one proposed recording: Accept writes exactly the one shown
    const p = el("div", "proposed");
    p.append(el("div", "wrap", `proposed: ${r.proposed.title || "?"} · ${len(r.proposed.length_s)}`), idLink(r.proposed.id));
    li.append(p);
    button("Accept", send("accept", r.proposed.id), "primary");
  } else if (["ambiguous", "none"].includes(r.cls)) {
    const low = s => (s || "").toLowerCase();       // the choices file holds canonical (lowercase) ids
    const fs = el("fieldset", "cands"), pre = low(r.choice && r.choice.action === "choose" && !r.choice.stale ? r.choice.mbid : r.suggested);
    for (const c of r.candidates || []) fs.append(idCandidate(c, "idpick-" + i, low(c.id) === pre, low(c.id) === low(r.suggested)));
    radios = [...fs.querySelectorAll("input")];
    li.append(fs);
    choose = button("Choose", () => send("choose", picked().value)(), "primary");
    choose.disabled = !picked();
    fs.onchange = () => { choose.disabled = !picked(); };
  } else {                                       // conflict / error: the evidence, and Skip only
    const ids = ["mb_trackid", "acoustid_id", "isrc"].filter(k => f[k]).map(k => `${k} ${f[k]}`);
    if (ids.length) li.append(el("div", "reason", "the file has " + ids.join(" · ")));
  }
  button("Skip", send("skip"));
  const row = el("div", "actions"); row.append(...buttons);
  li.append(row, box);
  idPaint(box, r.choice);
  return li;
}
let idSeq = 0;                                   // only the newest request paints the list (filter taps can overlap)
async function loadIdentity() {
  const sel = $("#identity-class"), ul = $("#identity"), cls = sel.value, seq = ++idSeq;
  let d;
  try { d = await api("/api/identity" + (cls ? "?class=" + encodeURIComponent(cls) : "")); }
  catch (e) { if (seq !== idSeq) return; $("#identity-count").textContent = ""; ul.replaceChildren(el("li", "muted wrap", e.message || "the identity list did not load")); return; }
  if (seq !== idSeq) return;
  const counts = d.counts || {};
  $("#identity-count").textContent = Object.values(counts).reduce((a, b) => a + b, 0) || "";
  for (const o of sel.options) o.textContent = o.value ? `${o.value} (${counts[o.value] || 0})` : "all";
  ul.replaceChildren(...d.rows.map(idRow));
  if (!d.rows.length) ul.append(el("li", "muted", "nothing to decide here"));
}
$("#identity-class").onchange = () => loadIdentity();
// identity:end

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
      sel.append(new Option(t.format == null ? `${name} · Navidrome decides` : t.format === "raw" ? `${name} · original` : `${name} · ${t.format} ${t.maxBitRate}k`, name));
    sel.value = s.tier;
  } catch (e) { /* keep the static menu, server selected (= the server's default) */ }
}
function playTrack(t) {
  state.playingId = t.id;
  $("#player").classList.remove("hidden");
  $("#np-title").textContent = t.title; $("#np-sub").textContent = [t.artist, fmt(t), t.provisional ? "provisional copy" : ""].filter(Boolean).join(" · ");
  const a = $("#audio"); a.src = streamUrl(t.id);
  const started = a.play().then(() => true, () => false);       // false: the browser refused (play-now says so)
  document.querySelectorAll(".play").forEach(b => b.classList.remove("playing"));
  if ("mediaSession" in navigator) navigator.mediaSession.metadata = new MediaMetadata({ title: t.title, artist: t.artist || "", album: t.album || "" });
  if (state.current) openPlaylist(state.current.id);
  return started;
}
$("#audio").addEventListener("error", () => {             // a stream that cannot play says so instead of staying silent
  if (state.playingId) $("#np-sub").textContent = "Couldn't play this one: Navidrome did not send the file.";
});
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
// a link to …/#<tab> opens that tab, …/#identity/<class> with that filter (R7-05's screenshots); the Identity pill is filled either way
const [hashTab, hashClass] = location.hash.slice(1).split("/");
const opened = [...document.querySelectorAll(".tabs button")].find(b => b.dataset.tab === hashTab);
if (opened && hashTab === "identity" && [...$("#identity-class").options].some(o => o.value === hashClass))
  $("#identity-class").value = hashClass;
if (!opened || opened.dataset.tab !== "identity") loadIdentity();
if (opened) opened.click();
// the worker recounts playlist health every export; a tab left open on the phone catches up when shown again
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") loadStatus(); });
