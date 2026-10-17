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
  ({ wanted: loadWanted, log: loadEvents })[b.dataset.tab]?.()?.catch(e => alert(e.message));
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
    const sub = `${p.songCount} tracks · ${dur(p.duration)}` + (p.summary ? ` · ${p.summary.ok}/${p.summary.total} ${p.crate ? "crate-ready" : "ready"}` : "");
    grow.append(el("div", "sub", sub));
    li.append(grow);
    if (p.crate) li.append(el("span", "badge crate", "crate"));
    else if (p.tier) li.append(el("span", "badge tier", p.tier));
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
  renderTier(p);
  const label = p.crate ? "crate" : p.tier ? `tier ${p.tier}` : null;
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
}
$("#back").onclick = () => { $("#detail").classList.add("hidden"); $("#playlists").classList.remove("hidden"); loadPlaylists(); };
$("#detail-crate").onchange = async e => {
  const p = state.current; e.target.disabled = true;
  try { await api(`/api/playlists/${p.id}/crate`, { enabled: e.target.checked }); await openPlaylist(p.id); await loadStatus(); }
  catch (err) { alert(changeError(err)); e.target.checked = !e.target.checked; }
  finally { e.target.disabled = false; }
};

// The comment owns crate and tier (D21). A crate always wins: while crate is on, the stored tier (tierTag) is shown
// but the menu is off and says when it applies, so it never looks like it did nothing.
function renderTier(p) {
  const sel = $("#detail-tier"), note = $("#detail-tier-note");
  sel.value = (p.crate ? p.tierTag : p.tier) || "";
  sel.disabled = !!p.crate;
  let text = "";
  if (p.crate) {
    text = p.tierTag ? `crate (tier ${p.tierTag} applies when crate is off)` : "crate (no other tier set; pick one once crate is off)";
    if (p.crateByName) text += " · crate by name: remove [crate]/🎛 from the name to turn it off";
  }
  note.textContent = text; note.classList.toggle("hidden", !text);
}
$("#detail-tier").onchange = async e => {
  const p = state.current, sel = e.target; sel.disabled = true;
  try { await api(`/api/playlists/${p.id}/tier`, { tier: sel.value || null }); await openPlaylist(p.id); await loadStatus(); }
  catch (err) { alert(changeError(err)); renderTier(p); }          // back to what the playlist really has
  finally { sel.disabled = !!state.current.crate; }
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
      const pl = el("button", "play pn-btn", mine ? "…" : "▶");
      pl.setAttribute("aria-label", "Play now: downloads a quick copy of this track, then plays it");
      pl.dataset.wid = id; pl.disabled = !!mine;
      pl.onclick = () => playNow(t, pl);
      li.append(pl);
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
