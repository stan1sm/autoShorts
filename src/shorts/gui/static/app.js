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
    if (btn.dataset.tab === "clips") loadClips();
    if (btn.dataset.tab === "settings") { loadSettings(); loadHardware(); }
  });
});

// ---------- run tab ----------
const runMsg = (text, cls) => { const el = $("#run-msg"); el.textContent = text; el.className = "msg " + (cls || ""); };

$("#submit-source").addEventListener("click", async () => {
  const source = $("#source-input").value.trim();
  if (!source) return runMsg("Enter a file path or URL first.", "err");
  try {
    await api("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, force: $("#force-check").checked }) });
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
      body: JSON.stringify({ source: path, force: $("#force-check").checked }) });
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
    clearTimeout(jobsTimer);
    if (active) jobsTimer = setTimeout(pollJobs, 2000);
  } catch { /* server restarting; retry on next action */ }
}

// ---------- clips tab ----------
async function loadClips() {
  const results = await api("/api/results");
  $("#clips-empty").style.display = results.length ? "none" : "block";
  $("#clips-container").innerHTML = results.map((m) => `
    <div class="source-group">
      <h3>${esc(m.source_file)} <span class="muted">(${esc(m.source_id)}, ${m.clips.length} clips)</span></h3>
      <div class="clip-grid">
        ${m.clips.map((c) => {
          const file = c.file.replace(/^clips\//, "");
          const tags = Object.entries(c.hashtags || {})
            .map(([p, t]) => `<div><b>${esc(p)}:</b> ${esc((t || []).join(" "))}</div>`).join("");
          return `
          <div class="clip-card">
            <video controls preload="metadata" src="/media/${encodeURIComponent(m.source_id)}/${encodeURIComponent(file)}"></video>
            <div class="meta">
              <div class="title">${esc(c.title)}</div>
              <div class="desc">${esc(c.description)}</div>
              <div class="muted">${c.duration}s · score ${c.score}</div>
              <div class="tags">${tags}</div>
            </div>
          </div>`;
        }).join("")}
      </div>
    </div>`).join("");
}
$("#refresh-clips").addEventListener("click", loadClips);

// ---------- settings tab ----------
const SETTINGS_SCHEMA = [
  { section: "Transcription", fields: [
    { path: "transcription.engine", label: "Engine", type: "select",
      options: ["faster-whisper", "openai", "groq"] },
    { path: "transcription.model", label: "Whisper model (local engine)", type: "select",
      options: ["large-v3", "medium", "small", "base", "tiny"] },
    { path: "transcription.language", label: "Language (auto = detect)", type: "text" },
  ]},
  { section: "Clip selection", fields: [
    { path: "clip_selection.strategy", label: "Strategy", type: "select", options: ["llm", "heuristic"] },
    { path: "clip_selection.llm_provider", label: "LLM provider", type: "select", options: ["anthropic", "openai"] },
    { path: "clip_selection.llm_model", label: "LLM model", type: "text" },
    { path: "clip_selection.clips_per_source", label: "Clips per video", type: "number", min: 1, max: 20 },
    { path: "clip_selection.min_clip_seconds", label: "Min clip length (s)", type: "number" },
    { path: "clip_selection.max_clip_seconds", label: "Max clip length (s)", type: "number" },
    { path: "clip_selection.min_gap_between_clips_seconds", label: "Min gap between clips (s)", type: "number" },
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
  { section: "Metadata", fields: [
    { path: "metadata.llm_provider", label: "LLM provider", type: "select", options: ["anthropic", "openai"] },
    { path: "metadata.llm_model", label: "LLM model", type: "text" },
    { path: "metadata.cta", label: "Call to action", type: "text" },
  ]},
  { section: "Input / output", fields: [
    { path: "input.inbox_dir", label: "Inbox folder", type: "text" },
    { path: "input.min_source_duration_seconds", label: "Min source duration (s)", type: "number" },
    { path: "output.root_dir", label: "Output folder", type: "text" },
  ]},
];

let currentConfig = null;

function fieldInput(f, value) {
  if (f.type === "select") {
    const opts = f.options.map((o) =>
      `<option value="${esc(o)}" ${o === value ? "selected" : ""}>${esc(o)}</option>`).join("");
    return `<select data-path="${f.path}">${opts}</select>`;
  }
  if (f.type === "checkbox")
    return `<input type="checkbox" data-path="${f.path}" ${value ? "checked" : ""}>`;
  if (f.type === "color")
    return `<input type="color" data-path="${f.path}" value="${esc(value)}">`;
  if (f.type === "number")
    return `<input type="number" data-path="${f.path}" value="${esc(value)}"
            ${f.min != null ? `min="${f.min}"` : ""} ${f.max != null ? `max="${f.max}"` : ""}>`;
  return `<input type="text" data-path="${f.path}" value="${esc(value)}">`;
}

async function loadSettings() {
  currentConfig = await api("/api/config");
  $("#settings-form").innerHTML = SETTINGS_SCHEMA.map((sec) => `
    <fieldset><legend>${esc(sec.section)}</legend>
      ${sec.fields.map((f) => `
        <div class="field">
          <label>${esc(f.label)}</label>
          ${fieldInput(f, getPath(currentConfig, f.path))}
        </div>`).join("")}
    </fieldset>`).join("");
}

$("#save-settings").addEventListener("click", async () => {
  const msg = $("#settings-msg");
  document.querySelectorAll("#settings-form [data-path]").forEach((el) => {
    let value = el.type === "checkbox" ? el.checked : el.value;
    if (el.type === "number" && value !== "") value = Number(value);
    setPath(currentConfig, el.dataset.path, value);
  });
  try {
    await api("/api/config", { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentConfig) });
    msg.textContent = "Saved. Applies to the next job.";
    msg.className = "msg ok";
  } catch (e) { msg.textContent = e.message; msg.className = "msg err"; }
});

// ---------- hardware panel ----------
async function loadHardware() {
  const { specs, recommendations } = await api("/api/hardware");
  const yes = (v) => v ? "✔ set" : "✘ not set";
  $("#hw-specs").innerHTML = `
    <div class="spec"><b>CPU</b>${specs.cpu_cores} cores</div>
    <div class="spec"><b>RAM</b>${specs.ram_gb || "?"} GB</div>
    <div class="spec"><b>GPU</b>${esc(specs.gpu_name || "none detected")}${specs.gpu_vram_gb ? ` (${specs.gpu_vram_gb} GB)` : ""}</div>
    <div class="spec"><b>ffmpeg</b>${esc(specs.ffmpeg_version || "NOT FOUND")}</div>
    <div class="spec"><b>ANTHROPIC_API_KEY</b>${yes(specs.has_anthropic_key)}</div>
    <div class="spec"><b>OPENAI_API_KEY</b>${yes(specs.has_openai_key)}</div>
    <div class="spec"><b>GROQ_API_KEY</b>${yes(specs.has_groq_key)}</div>`;

  $("#hw-recs").innerHTML = recommendations.notes.map((n, i) => `
    <div class="rec">
      <div class="what">${esc(n.setting)} → ${esc(n.value)}</div>
      <div class="why">${esc(n.reason)}</div>
      ${n.override ? `<button class="small apply-rec" data-idx="${i}">Apply</button>` : ""}
    </div>`).join("");
  $("#hw-warnings").innerHTML = recommendations.warnings
    .map((w) => `<div class="warning">⚠ ${esc(w)}</div>`).join("");

  document.querySelectorAll(".apply-rec").forEach((btn) => {
    btn.addEventListener("click", () => {
      const note = recommendations.notes[btn.dataset.idx];
      for (const [path, value] of Object.entries(note.override)) {
        const el = document.querySelector(`#settings-form [data-path="${path}"]`);
        if (!el) continue;
        if (el.type === "checkbox") el.checked = Boolean(value);
        else el.value = value;
      }
      btn.textContent = "Applied ✔";
      $("#settings-msg").textContent = 'Recommendation applied to the form — click "Save settings" to persist.';
      $("#settings-msg").className = "msg ok";
    });
  });
}

// ---------- init ----------
pollJobs();
