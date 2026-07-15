"use strict";

// ---------- helpers ----------
const $ = (sel) => document.querySelector(sel);
const api = async (url, opts) => {
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
};
const getPath = (obj, path) => path.split(".").reduce((o, k) => (o ?? {})[k], obj);
const setPath = (obj, path, value) => {
  const keys = path.split(".");
  let node = obj;
  for (const k of keys.slice(0, -1)) node = node[k] ?? (node[k] = {});
  node[keys.at(-1)] = value;
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".panel").forEach((p) =>
      p.classList.toggle("active", p.id === "tab-" + btn.dataset.tab));
    if (btn.dataset.tab === "run") loadRunOptions();
    if (btn.dataset.tab === "clips") { loadClips(); loadPostingOptions(); }
    if (btn.dataset.tab === "settings") { loadSettings(); loadHardware(); loadChannels(); }
  });
});

// ---------- run tab ----------
const runMsg = (text, cls) => { const el = $("#run-msg"); el.textContent = text; el.className = "msg " + (cls || ""); };

$("#submit-source").addEventListener("click", async () => {
  const source = $("#source-input").value.trim();
  if (!source) return runMsg("Enter a file path or URL first.", "err");
  try {
    await api("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, force: $("#force-check").checked,
                             publish: $("#publish-check").checked }) });
    $("#source-input").value = "";
    runMsg("Job queued.", "ok");
    pollJobs();
  } catch (e) { runMsg(e.message, "err"); }
});

$("#file-input").addEventListener("change", () => {
  const f = $("#file-input").files[0];
  $("#file-name").textContent = f ? f.name : "…or choose a file to upload into the inbox";
  $("#submit-file").disabled = !f;
});

// fetch() can't report upload progress — use XMLHttpRequest for the upload.
function uploadWithProgress(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded, e.total); };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        let detail = xhr.statusText;
        try { detail = JSON.parse(xhr.responseText).detail || detail; } catch {}
        reject(new Error(detail));
      }
    };
    xhr.onerror = () => reject(new Error("upload failed — is the server still running?"));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

const fmtMB = (bytes) => (bytes / (1024 * 1024)).toFixed(1);

function showUploadProgress(loaded, total) {
  const pct = total ? Math.round((loaded / total) * 100) : 0;
  $("#upload-progress").hidden = false;
  $("#upload-progress-fill").style.width = pct + "%";
  $("#upload-progress-label").textContent =
    pct >= 100 ? "processing…" : `${pct}% · ${fmtMB(loaded)} / ${fmtMB(total)} MB`;
}

$("#submit-file").addEventListener("click", async () => {
  const f = $("#file-input").files[0];
  if (!f) return;
  $("#submit-file").disabled = true;
  runMsg("Uploading " + f.name + "…");
  showUploadProgress(0, f.size);
  try {
    const { path } = await uploadWithProgress(f, showUploadProgress);
    await api("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: path, force: $("#force-check").checked,
                             publish: $("#publish-check").checked }) });
    runMsg("Uploaded and queued.", "ok");
    $("#file-input").value = "";
    $("#file-name").textContent = "…or choose a file to upload into the inbox";
    pollJobs();
  } catch (e) { runMsg(e.message, "err"); }
  $("#upload-progress").hidden = true;
  $("#submit-file").disabled = false;
});

// Map raw pipeline events to human-readable stage labels.
const STAGE_LABELS = [
  [/^ingest\.start/, () => "preparing source…"],
  [/^ingest\.downloading/, () => "downloading video"],
  [/^ingest\.validating/, () => "validating video (checking format & duration)"],
  [/^ingest\.hashing/, () => "fingerprinting file (dedup check)"],
  [/^skip\./, () => "already processed"],
  [/^transcribe\.loading_model/, () => "loading Whisper model (first run downloads it — be patient)"],
  [/^transcribe\.transcribing/, () => "transcribing audio"],
  [/^transcribe\.start/, () => "starting transcription"],
  [/^transcribe\.done/, () => "transcription finished"],
  [/^select\./, () => "picking the best clips (LLM)"],
  [/^metadata\.clip_(\d+)/, (m, j) => `writing title & hashtags — clip ${+m[1]}${j.clips_total ? " of " + j.clips_total : ""}`],
  [/^render\.clip_(\d+)/, (m, j) => `rendering clip ${+m[1]}${j.clips_total ? " of " + j.clips_total : ""}`],
  [/^pipeline\.done/, () => "finishing up"],
];

function stageCell(j) {
  if (j.status !== "running") return "";
  const s = j.stage || "";
  let label = s || "starting…";
  for (const [re, fmt] of STAGE_LABELS) {
    const m = s.match(re);
    if (m) { label = fmt(m, j); break; }
  }
  let html = `<div>${esc(label)}${j.progress != null ? ` — ${Math.round(j.progress)}%` : ""}</div>`;
  if (j.progress != null) {
    html += `<div class="progress-track mini"><div class="progress-fill" style="width:${Math.round(j.progress)}%"></div></div>`;
  }
  return html;
}

let jobsTimer = null;
async function pollJobs() {
  try {
    const jobs = await api("/api/jobs");
    $("#jobs-empty").style.display = jobs.length ? "none" : "block";
    $("#jobs-table tbody").innerHTML = jobs.map((j) => `
      <tr>
        <td>${j.id}</td>
        <td class="src" title="${esc(j.source)}">${esc(j.source)}</td>
        <td><span class="badge ${j.status}">${j.status}</span></td>
        <td class="stage">${stageCell(j)}</td>
        <td>${j.clips || ""}</td>
        <td class="src" title="${esc(j.error || "")}">${esc(j.error || "")}</td>
      </tr>`).join("");
    const active = jobs.some((j) => j.status === "queued" || j.status === "running");
    document.body.classList.toggle("working", active);
    clearTimeout(jobsTimer);
    if (active) jobsTimer = setTimeout(pollJobs, 2000);
  } catch { /* server restarting; retry on next action */ }
}

// ---------- clips tab ----------
const clipsMsg = (text, cls) => { const el = $("#clips-msg"); el.textContent = text; el.className = "msg " + (cls || ""); };

// posts index: "{source_id}/{clip_file}" -> {platform: record}
function indexPosts(posts) {
  const idx = {};
  for (const p of posts) (idx[p.clip_file] ??= {})[p.platform] = p;
  return idx;
}

const fmtWhen = (iso) => iso ? new Date(iso).toLocaleString([], {
  weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
}) : "";

function postBadges(sourceId, clipFile, postIdx, hostedSet) {
  const key = `${sourceId}/${clipFile}`;
  const badges = [];
  badges.push(hostedSet.has(key)
    ? `<span class="badge hosted" title="uploaded to object storage">hosted</span>`
    : `<span class="badge unhosted" title="not yet uploaded">not hosted</span>`);
  const dues = [];
  for (const [platform, rec] of Object.entries(postIdx[key] || {})) {
    const cls = { scheduled: "scheduled", sent: "done", failed: "failed", pending: "queued" }[rec.status] || "queued";
    const title = rec.last_error ? rec.last_error : (rec.buffer_post_id ? `Buffer post ${rec.buffer_post_id}` : rec.status);
    badges.push(`<span class="badge ${cls}" title="${esc(title)}">${esc(platform)}: ${esc(rec.status)}</span>`);
    if (rec.scheduled_for) dues.push(`${platform} posts ${fmtWhen(rec.scheduled_for)}`);
  }
  return `<div class="post-badges">${badges.join(" ")}</div>` +
    (dues.length ? `<div class="due-line">${esc(dues.join(" · "))}</div>` : "");
}

// True when this clip has no Buffer post yet on any platform — i.e. a time
// picker is still meaningful.
function clipUnposted(sourceId, clipFile, postIdx) {
  const records = Object.values(postIdx[`${sourceId}/${clipFile}`] || {});
  return !records.some((r) => r.buffer_post_id);
}

const localMinNow = () => {
  const d = new Date(Date.now() - new Date().getTimezoneOffset() * 60000 + 5 * 60000);
  return d.toISOString().slice(0, 16);
};

function collectSchedule(groupEl) {
  const schedule = {};
  groupEl.querySelectorAll(".clip-when").forEach((el) => {
    if (el.value) schedule[el.dataset.clip] = el.value;
  });
  return schedule;
}

const ALL_PLATFORMS = ["youtube", "instagram", "tiktok"];

// Checkboxes for the platforms this clip can still be posted to (already
// posted platforms are shown as badges instead). Defaults to the platforms
// configured in Settings.
function platformRow(sourceId, clipFile, postIdx, cfgPlatforms) {
  const recs = postIdx[`${sourceId}/${clipFile}`] || {};
  const open = ALL_PLATFORMS.filter((p) => !recs[p]?.buffer_post_id);
  if (!open.length) return "";
  const boxes = open.map((p) => `
    <label class="inline-check">
      <input type="checkbox" class="clip-platform" data-clip="${esc(clipFile)}"
             value="${p}" ${cfgPlatforms.includes(p) ? "checked" : ""}> ${p}
    </label>`).join("");
  return `<div class="platform-row"><label>Post to</label>${boxes}</div>`;
}

// {clip_file: [platform, ...]} for every clip that has checkboxes rendered —
// an all-unchecked clip is sent as [] so the backend skips it.
function collectPlatforms(groupEl) {
  const platforms = {};
  groupEl.querySelectorAll(".clip-platform").forEach((el) => {
    (platforms[el.dataset.clip] ??= []);
    if (el.checked) platforms[el.dataset.clip].push(el.value);
  });
  return platforms;
}

function publishJobLine(job) {
  if (!job) return "";
  const stats = job.post && !Array.isArray(job.post)
    ? ` — ${job.post.succeeded} created, ${job.post.skipped_duplicates} skipped` +
      (job.post.skipped_deselected ? `, ${job.post.skipped_deselected} deselected` : "") +
      `, ${job.post.failed.length} failed`
    : "";
  const stage = job.status === "running" ? ` (${job.stage === "host" ? "uploading clips…" : "creating posts…"})` : "";
  return `<span class="badge ${job.status}">publish: ${job.status}</span>${esc(stage + stats)}
          ${job.error ? `<span class="err-text">${esc(job.error)}</span>` : ""}`;
}

function publishFailures(job) {
  if (!job) return [];
  const post = job.post && !Array.isArray(job.post) ? job.post.failed : [];
  return [...(job.host?.failed || []), ...(post || [])];
}

let clipsData = { results: [], postIdx: {}, hostedSet: new Set(), publishJobs: [],
                  cfgPlatforms: [] };

async function loadClips() {
  const [results, postsData, publishJobs, config] = await Promise.all([
    api("/api/results"), api("/api/posts"), api("/api/publish"), api("/api/config"),
  ]);
  clipsData = {
    results,
    postIdx: indexPosts(postsData.posts),
    hostedSet: new Set(postsData.hosted.map((h) => h.clip_file)),
    publishJobs,
    cfgPlatforms: config.posting?.platforms || [],
  };
  renderClips();
  if (publishJobs.some((j) => j.status === "queued" || j.status === "running")) {
    clearTimeout(publishTimer);
    publishTimer = setTimeout(loadClips, 2500);
  }
}
let publishTimer = null;

function renderClips() {
  const { results, postIdx, hostedSet, publishJobs, cfgPlatforms } = clipsData;
  $("#clips-empty").style.display = results.length ? "none" : "block";
  $("#clips-container").innerHTML = results.map((m) => {
    const job = publishJobs.find((j) => j.source_id === m.source_id);  // newest first
    const busy = job && (job.status === "queued" || job.status === "running");
    return `
    <div class="source-group">
      <h3>${esc(m.source_file)} <span class="muted">(${esc(m.source_id)}, ${m.clips.length} clips)</span></h3>
      <div class="row publish-bar">
        <button class="primary publish-btn" data-source="${esc(m.source_id)}" ${busy ? "disabled" : ""}>Publish</button>
        <button class="dryrun-btn" data-source="${esc(m.source_id)}" ${busy ? "disabled" : ""}>Dry run</button>
        <span class="publish-status">${publishJobLine(job)}</span>
      </div>
      ${publishFailures(job).length ? `<pre class="dryrun-out fail-list">${
        esc(publishFailures(job).join("\n"))}</pre>` : ""}
      <pre class="dryrun-out" id="dryrun-${esc(m.source_id)}" hidden></pre>
      <div class="clip-grid">
        ${m.clips.map((c) => {
          const file = c.file.replace(/^clips\//, "");
          const tags = Object.entries(c.hashtags || {})
            .map(([p, t]) => `<div><b>${esc(p)}:</b> ${esc((t || []).join(" "))}</div>`).join("");
          const whenRow = clipUnposted(m.source_id, c.file, postIdx) ? `
              <div class="when-row">
                <label>Post at</label>
                <input type="datetime-local" class="clip-when"
                       data-clip="${esc(c.file)}" min="${localMinNow()}">
                <span class="muted">empty = auto</span>
              </div>` : "";
          return `
          <div class="clip-card">
            <video controls preload="metadata" src="/media/${encodeURIComponent(m.source_id)}/${encodeURIComponent(file)}"></video>
            <div class="meta">
              <div class="title">${esc(c.title)}</div>
              <div class="desc">${esc(c.description)}</div>
              <div class="muted">${c.duration}s · score ${c.score}</div>
              ${postBadges(m.source_id, c.file, postIdx, hostedSet)}
              ${platformRow(m.source_id, c.file, postIdx, cfgPlatforms)}
              ${whenRow}
              <div class="tags">${tags}</div>
            </div>
          </div>`;
        }).join("")}
      </div>
    </div>`;
  }).join("");

  document.querySelectorAll(".publish-btn").forEach((btn) => btn.addEventListener("click", async () => {
    btn.disabled = true;
    const group = btn.closest(".source-group");
    const schedule = collectSchedule(group);
    const platforms = collectPlatforms(group);
    try {
      await api("/api/publish", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_id: btn.dataset.source, schedule, platforms }) });
      const picked = Object.keys(schedule).length;
      const skipped = Object.values(platforms).filter((p) => !p.length).length;
      clipsMsg(`Publish queued for ${btn.dataset.source}` +
        (picked ? ` — ${picked} clip(s) at your chosen times` : "") +
        (skipped ? ` — ${skipped} clip(s) deselected` : "") + ".", "ok");
      loadClips();
    } catch (e) { clipsMsg(e.message, "err"); btn.disabled = false; }
  }));

  document.querySelectorAll(".dryrun-btn").forEach((btn) => btn.addEventListener("click", async () => {
    const out = $("#dryrun-" + CSS.escape(btn.dataset.source));
    if (!out.hidden) { out.hidden = true; return; }
    btn.disabled = true;
    try {
      const res = await api("/api/publish", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_id: btn.dataset.source, dry_run: true,
                               schedule: collectSchedule(btn.closest(".source-group")),
                               platforms: collectPlatforms(btn.closest(".source-group")) }) });
      const posts = res.post.dry_run_inputs.map((e) =>
        `--- ${e.clip} -> ${e.platform} ---\n${JSON.stringify(e.input, null, 2)}`).join("\n\n");
      out.textContent =
        `HOST: ${res.host.uploaded} would upload, ${res.host.skipped} unchanged, ${res.host.failed.length} failed\n` +
        `POST: ${res.post.attempted} post(s) would be created` +
        (res.post.skipped_duplicates ? ` (${res.post.skipped_duplicates} already posted)` : "") + "\n\n" + posts;
      out.hidden = false;
      clipsMsg("", "");
    } catch (e) { clipsMsg(e.message, "err"); }
    btn.disabled = false;
  }));
}

$("#refresh-clips").addEventListener("click", loadClips);
$("#retry-failed").addEventListener("click", async () => {
  try {
    const res = await api("/api/posts/retry-failed", { method: "POST" });
    clipsMsg(res.queued ? "Retry queued." : "Nothing to retry.", "ok");
    if (res.queued) loadClips();
  } catch (e) { clipsMsg(e.message, "err"); }
});

// ---------- config forms ----------
// Per-run choices live on the Run tab; per-publish choices on the Clips tab;
// Settings keeps only set-once machine/account configuration.

const RUN_SCHEMA = [
  { path: "campaign.rules", label:
      "Campaign rules — the brand's brief, verbatim, any language (required focus, " +
      "mandatory hashtags, per-platform @mentions, CTA). Guides clip selection and " +
      "titles/descriptions. Changing it? Tick Force to re-select clips.",
    type: "textarea" },
  { path: "clip_selection.clips_per_source", label: "Clips per video", type: "number", min: 1, max: 20 },
  { path: "clip_selection.min_clip_seconds", label: "Min clip length (s)", type: "number" },
  { path: "clip_selection.max_clip_seconds", label: "Max clip length (s)", type: "number" },
  { path: "video.effects.zoom.mode", label: "Zoom effect", type: "select", options: [
    { value: "none", label: "none" },
    { value: "continuous", label: "continuous (slow zoom)" },
    { value: "punch_in", label: "punch-in (cuts at sentences)" },
  ]},
  { path: "video.effects.zoom.intensity", label: "Zoom intensity (1.01–1.5)", type: "number",
    min: 1.01, max: 1.5, step: 0.01 },
  { path: "video.captions.animation", label: "Caption animation", type: "select",
    options: ["pop", "none"] },
];

const POSTING_SCHEMA = [
  { path: "posting.draft_only", label: "Draft only (approve in Buffer before going live)", type: "checkbox" },
  { path: "posting.schedule_mode", label: "Scheduling", type: "select",
    options: ["queue", "spread", "immediate"] },
  { path: "posting.spread.posts_per_day_per_platform", label: "Spread: posts per day", type: "number", min: 1 },
  { path: "posting.spread.window_days", label: "Spread: window (days)", type: "number", min: 1 },
];

// ---------- settings tab ----------
const SETTINGS_SCHEMA = [
  { section: "System (transcription, LLM, folders)", fields: [
    { path: "transcription.engine", label: "Transcription engine", type: "select",
      options: ["faster-whisper", "openai", "groq"] },
    { path: "transcription.model", label: "Whisper model (local engine)", type: "select",
      options: ["large-v3", "medium", "small", "base", "tiny"] },
    { path: "transcription.language", label: "Language (auto = detect)", type: "text" },
    { path: "clip_selection.strategy", label: "Clip selection strategy", type: "select",
      options: ["llm", "heuristic"] },
    { path: "clip_selection.llm_provider", label: "LLM provider", type: "select", options: ["anthropic", "openai"] },
    { path: "clip_selection.llm_model", label: "LLM model", type: "text" },
    { path: "input.inbox_dir", label: "Inbox folder", type: "text" },
    { path: "output.root_dir", label: "Output folder", type: "text" },
  ]},
  { section: "Video & captions", fields: [
    { path: "video.reframe_mode", label: "Reframe mode", type: "select",
      options: ["center_crop_blur", "subject_tracking"] },
    { path: "video.captions.enabled", label: "Burn in captions", type: "checkbox" },
    { path: "video.captions.font", label: "Caption font", type: "text" },
    { path: "video.captions.font_size", label: "Font size", type: "number" },
    { path: "video.captions.position", label: "Position", type: "select",
      options: ["bottom_third", "middle", "top_third"] },
    { path: "video.captions.words_per_caption", label: "Words per caption", type: "number", min: 1, max: 4 },
    { path: "video.captions.highlight_color", label: "Highlight color", type: "color" },
    { path: "video.captions.base_color", label: "Base color", type: "color" },
    { path: "video.encoding.fps", label: "FPS", type: "number" },
    { path: "video.encoding.bitrate", label: "Video bitrate", type: "text" },
  ]},
  { section: "Publishing defaults (Buffer)", fields: [
    { path: "posting.enabled", label: "Enable publishing", type: "checkbox" },
    { path: "posting.platforms", label: "Default platforms", type: "multicheck",
      options: ["youtube", "instagram", "tiktok"] },
    { path: "metadata.cta", label: "Fallback call to action (campaign rules override)", type: "text" },
    { path: "posting.spread.same_source_gap_hours", label: "Spread: hours between clips of one video", type: "number", min: 1 },
    { path: "posting.spread.quiet_hours.0", label: "Spread: quiet hours start (0-23)", type: "number", min: 0, max: 23 },
    { path: "posting.spread.quiet_hours.1", label: "Spread: quiet hours end (0-23)", type: "number", min: 0, max: 23 },
    { path: "posting.spread.timezone", label: "Spread: timezone", type: "text" },
    { path: "posting.instagram.post_type", label: "Instagram post type", type: "select",
      options: ["reel", "post", "story"] },
    { path: "posting.instagram.hashtags_in_first_comment", label: "IG hashtags in first comment", type: "checkbox" },
    { path: "posting.youtube.ensure_shorts_tag", label: "Ensure #shorts tag (YouTube)", type: "checkbox" },
    { path: "posting.youtube.category_id", label: "YouTube category", type: "select", options: [
      { value: "24", label: "Entertainment" }, { value: "22", label: "People & Blogs" },
      { value: "23", label: "Comedy" }, { value: "20", label: "Gaming" },
      { value: "27", label: "Education" }, { value: "28", label: "Science & Technology" },
      { value: "25", label: "News & Politics" }, { value: "17", label: "Sports" },
      { value: "10", label: "Music" }, { value: "26", label: "Howto & Style" },
    ]},
    { path: "posting.youtube.privacy", label: "YouTube privacy (once published)", type: "select",
      options: ["public", "unlisted", "private"] },
    { path: "posting.youtube.made_for_kids", label: "YouTube: made for kids", type: "checkbox" },
    { path: "posting.youtube.notify_subscribers", label: "YouTube: notify subscribers", type: "checkbox" },
    { path: "posting.tiktok.thumbnail_offset_seconds", label: "TikTok thumbnail offset (s, empty = default)", type: "number" },
  ]},
  { section: "Media hosting", fields: [
    { path: "hosting.backend", label: "Backend", type: "select", options: ["r2", "s3", "minio"] },
    { path: "hosting.bucket", label: "Bucket", type: "text" },
    { path: "hosting.public_mode", label: "Access mode", type: "select",
      options: ["signed_url", "public_bucket"] },
    { path: "hosting.signed_url_ttl_days", label: "Signed URL TTL (days, max 7)", type: "number", min: 1, max: 7 },
    { path: "hosting.retention_days", label: "Retention (days)", type: "number", min: 1 },
  ]},
];

let currentConfig = null;

function fieldInput(f, value) {
  if (f.type === "multicheck") {
    return `<div class="multicheck">` + f.options.map((o) => `
      <label class="inline-check">
        <input type="checkbox" data-multipath="${f.path}" value="${esc(o)}"
               ${(value || []).includes(o) ? "checked" : ""}> ${esc(o)}
      </label>`).join("") + `</div>`;
  }
  if (f.type === "select") {
    const opts = f.options.map((o) => {
      const v = typeof o === "object" ? o.value : o;
      const label = typeof o === "object" ? o.label : o;
      return `<option value="${esc(v)}" ${String(v) === String(value) ? "selected" : ""}>${esc(label)}</option>`;
    }).join("");
    return `<select data-path="${f.path}">${opts}</select>`;
  }
  if (f.type === "textarea")
    return `<textarea data-path="${f.path}" rows="8" spellcheck="false">${esc(value ?? "")}</textarea>`;
  if (f.type === "checkbox")
    return `<input type="checkbox" data-path="${f.path}" ${value ? "checked" : ""}>`;
  if (f.type === "color")
    return `<input type="color" data-path="${f.path}" value="${esc(value)}">`;
  if (f.type === "number")
    return `<input type="number" data-path="${f.path}" value="${esc(value)}"
            ${f.min != null ? `min="${f.min}"` : ""} ${f.max != null ? `max="${f.max}"` : ""}
            ${f.step != null ? `step="${f.step}"` : ""}>`;
  return `<input type="text" data-path="${f.path}" value="${esc(value)}">`;
}

const fieldRow = (f, cfg) => `
  <div class="field">
    <label>${esc(f.label)}</label>
    ${fieldInput(f, getPath(cfg, f.path))}
  </div>`;

async function loadSettings() {
  currentConfig = await api("/api/config");
  $("#settings-form").innerHTML = SETTINGS_SCHEMA.map((sec, i) => `
    <details class="settings-section" ${i === 0 ? "open" : ""}>
      <summary>${esc(sec.section)}</summary>
      ${sec.fields.map((f) => fieldRow(f, currentConfig)).join("")}
    </details>`).join("");
}

// ---------- auto-saved option panels (Run + Clips tabs) ----------
// Each change updates the shared config and PUTs it after a short debounce.

const optionsMsg = (sel, text, cls) => {
  const el = $(sel);
  el.textContent = text;
  el.className = "msg inline " + (cls || "");
};

function attachAutoSave(formSel, msgSel) {
  let timer = null;
  const handler = (e) => {
    const el = e.target;
    if (!el.dataset?.path || !currentConfig) return;
    let value = el.type === "checkbox" ? el.checked : el.value;
    if (el.type === "number") value = value === "" ? null : Number(value);
    setPath(currentConfig, el.dataset.path, value);
    optionsMsg(msgSel, "saving…");
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        await api("/api/config", { method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(currentConfig) });
        optionsMsg(msgSel, "saved ✓", "ok");
      } catch (err) { optionsMsg(msgSel, err.message, "err"); }
    }, 500);
  };
  $(formSel).addEventListener("input", handler);
  $(formSel).addEventListener("change", handler);
}

async function loadRunOptions() {
  currentConfig = await api("/api/config");
  $("#run-options").innerHTML = RUN_SCHEMA.map((f) => fieldRow(f, currentConfig)).join("");
}

// Rendered on tab activation only — loadClips polls while publish jobs run,
// and re-rendering the form mid-edit would wipe the operator's input.
async function loadPostingOptions() {
  currentConfig = await api("/api/config");
  $("#post-options").innerHTML = POSTING_SCHEMA.map((f) => fieldRow(f, currentConfig)).join("");
}

$("#save-settings").addEventListener("click", async () => {
  const msg = $("#settings-msg");
  document.querySelectorAll("#settings-form [data-path]").forEach((el) => {
    let value = el.type === "checkbox" ? el.checked : el.value;
    if (el.type === "number") value = value === "" ? null : Number(value);
    setPath(currentConfig, el.dataset.path, value);
  });
  const multipaths = new Set([...document.querySelectorAll("#settings-form [data-multipath]")]
    .map((el) => el.dataset.multipath));
  for (const path of multipaths) {
    const values = [...document.querySelectorAll(
      `#settings-form [data-multipath="${path}"]:checked`)].map((el) => el.value);
    setPath(currentConfig, path, values);
  }
  try {
    await api("/api/config", { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentConfig) });
    msg.textContent = "Saved. Applies to the next job.";
    msg.className = "msg ok";
  } catch (e) { msg.textContent = e.message; msg.className = "msg err"; }
});

// ---------- hardware panel ----------
function recIsActive(note, cfg) {
  return note.override && Object.entries(note.override)
    .every(([path, value]) => String(getPath(cfg, path)) === String(value));
}

async function loadHardware() {
  const [{ specs, recommendations }, cfg] = await Promise.all([
    api("/api/hardware"), api("/api/config"),
  ]);
  const yes = (v) => v ? "✔ set" : "✘ not set";
  $("#hw-specs").innerHTML = `
    <div class="spec"><b>CPU</b>${specs.cpu_cores} cores</div>
    <div class="spec"><b>RAM</b>${specs.ram_gb || "?"} GB</div>
    <div class="spec"><b>GPU</b>${esc(specs.gpu_name || "none detected")}${specs.gpu_vram_gb ? ` (${specs.gpu_vram_gb} GB)` : ""}</div>
    <div class="spec"><b>ffmpeg</b>${esc(specs.ffmpeg_version || "NOT FOUND")}</div>
    <div class="spec"><b>ANTHROPIC_API_KEY</b>${yes(specs.has_anthropic_key)}</div>
    <div class="spec"><b>OPENAI_API_KEY</b>${yes(specs.has_openai_key)}</div>
    <div class="spec"><b>GROQ_API_KEY</b>${yes(specs.has_groq_key)}</div>
    <div class="spec"><b>BUFFER_API_KEY</b>${yes(specs.has_buffer_key)}</div>
    <div class="spec"><b>R2 credentials</b>${yes(specs.has_r2_creds)}</div>`;

  $("#hw-recs").innerHTML = recommendations.notes.map((n, i) => `
    <div class="rec">
      <div class="what">${esc(n.setting)} → ${esc(n.value)}</div>
      <div class="why">${esc(n.reason)}</div>
      ${!n.override ? ""
        : recIsActive(n, cfg)
          ? `<span class="rec-active">● active</span>`
          : `<button class="small apply-rec" data-idx="${i}">Apply</button>`}
    </div>`).join("");
  $("#hw-warnings").innerHTML = recommendations.warnings
    .map((w) => `<div class="warning">⚠ ${esc(w)}</div>`).join("");

  document.querySelectorAll(".apply-rec").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const note = recommendations.notes[btn.dataset.idx];
      try {
        const cfg = await api("/api/config");
        for (const [path, value] of Object.entries(note.override)) setPath(cfg, path, value);
        await api("/api/config", { method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cfg) });
        $("#settings-msg").textContent = `Applied and saved: ${note.setting} → ${note.value}.`;
        $("#settings-msg").className = "msg ok";
        loadSettings();
        loadHardware();
      } catch (e) {
        $("#settings-msg").textContent = e.message;
        $("#settings-msg").className = "msg err";
        btn.disabled = false;
      }
    });
  });
}

// ---------- buffer channels ----------
const channelsMsg = (text, cls) => { const el = $("#channels-msg"); el.textContent = text; el.className = "msg " + (cls || ""); };

function renderChannels(rows) {
  $("#channels-list").innerHTML = rows.length
    ? `<table><thead><tr><th>Platform</th><th>Channel</th><th>ID</th><th>Refreshed</th></tr></thead><tbody>
       ${rows.map((c) => `<tr><td>${esc(c.platform)}</td><td>${esc(c.name || "")}</td>
         <td><code>${esc(c.channel_id)}</code></td>
         <td class="muted">${esc((c.refreshed_at || "").slice(0, 16).replace("T", " "))}</td></tr>`).join("")}
       </tbody></table>`
    : `<p class="muted">No channels cached — connect them in Buffer, then click "Refresh from Buffer".</p>`;
}

async function loadChannels() {
  try { renderChannels(await api("/api/buffer/channels")); } catch { /* server restarting */ }
}

$("#refresh-channels").addEventListener("click", async () => {
  channelsMsg("Contacting Buffer…");
  try {
    renderChannels(await api("/api/buffer/channels/refresh", { method: "POST" }));
    channelsMsg("Channel cache refreshed.", "ok");
  } catch (e) { channelsMsg(e.message, "err"); }
});

// ---------- init ----------
pollJobs();
loadRunOptions();
attachAutoSave("#run-options", "#run-options-msg");
attachAutoSave("#post-options", "#post-options-msg");
