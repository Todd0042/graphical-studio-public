"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  for (const k of kids) node.append(k);
  return node;
};

async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: { "X-GS-CSRF": "1" }, credentials: "same-origin" };
  if (form) opts.body = form;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 401) {
    location.href = "/login?next=/";
    throw new Error("Signed out");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

const state = {
  options: null, uploads: {}, galleryKind: "photo", galleryItems: [], selected: null, jobsSig: "",
  builder: { photo: null }, target: "photo", reconciled: null,
};
const STATE_LABEL = { queued: "Queued", waiting_gpu: "Waiting", running: "Generating", done: "Done", failed: "Failed", cancelled: "Cancelled" };
const ACTIVE = new Set(["queued", "waiting_gpu", "running"]);
const APP_LABEL = { graphical_studio: "Graphical Studio" };
const mediaRel = (p) => p.split("/outputs/").pop();
const setMsg = (node, text, isErr = false) => { node.textContent = text; node.classList.toggle("err", isErr); };

const hooks = {
  optionsLoaded: [], status: [], actionButtons: [], tileRender: [],
  applyRecipe: [], sendBuilder: [], showReconciled: [], viewerMedia: [], selectFromQueue: [],
};
const runHooks = (name, ...args) => hooks[name].forEach((fn) => fn(...args));

/* ---------- tabs ---------- */
function showTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".tabpane").forEach((p) => (p.hidden = p.dataset.pane !== name));
}
document.addEventListener("click", (ev) => {
  const tab = ev.target.closest(".tab[data-tab]");
  if (tab) showTab(tab.dataset.tab);
});

/* ---------- options ---------- */
function fillSelect(select, items, { keepFirst = false } = {}) {
  const first = keepFirst ? select.options[0] : null;
  select.replaceChildren(...(first ? [first] : []));
  for (const it of items) {
    const v = typeof it === "string" ? it : it.key;
    const l = typeof it === "string" ? it : it.label;
    select.append(el("option", { value: v, textContent: l, className: it.caution ? "caution" : "" }));
  }
  markCaution(select);
}

function markCaution(select) {
  select.classList.toggle("caution", !!select.selectedOptions[0]?.classList.contains("caution"));
}

function applyPhotoModelSettings(pf, key) {
  const m = state.options?.photo?.models?.find((x) => x.key === key);
  if (!m?.settings) return;
  for (const k of ["steps", "cfg", "sampler", "scheduler"]) {
    if (m.settings[k] !== undefined && pf[k]) pf[k].value = m.settings[k];
  }
}

function applyPhotoPreset(label) {
  const pf = $("#photo-form");
  const p = state.options.photo.presets.find((x) => x.label === label);
  if (p) { pf.preset.value = p.label; pf.width.value = p.width; pf.height.value = p.height; }
}

async function loadOptions() {
  const o = (state.options = await api("/api/options"));
  const pf = $("#photo-form");
  fillSelect(pf.model, o.photo.models);
  fillSelect(pf.sampler, o.photo.samplers);
  fillSelect(pf.scheduler, o.photo.schedulers);
  fillSelect(pf.ref_mode, o.photo.ref_modes);
  fillSelect(pf.lora, o.photo.loras, { keepFirst: true });
  fillSelect(pf.preset, [{ key: "", label: "Custom" }, ...o.photo.presets.map((p) => ({ key: p.label, label: p.label }))]);
  pf.negative.value = o.photo.default_negative;
  applyPhotoModelSettings(pf, pf.model.value);
  pf.model.addEventListener("change", () => applyPhotoModelSettings(pf, pf.model.value));
  pf.preset.addEventListener("change", () => applyPhotoPreset(pf.preset.value));
  $$("[data-photo-ref-only]").forEach((n) => (n.hidden = o.photo.supports_ref === false));
  $$("[data-photo-lora-only]").forEach((n) => (n.hidden = o.photo.supports_lora === false));

  renderBuilder(o.builder);
  if (o.app_labels) Object.assign(APP_LABEL, o.app_labels);
  applyUiStrings(o.ui);
  fillLlms(o[o.ui?.api_list_key || "llms"] || o.llms || [], o.ui?.storage_key || "gs-llm");
  renderPresets(o.presets, o.builder);
  runHooks("optionsLoaded", o);
}

function applyUiStrings(ui) {
  if (!ui) return;
  const setTxt = (id, val) => { const n = $(id); if (n && val) n.textContent = val; };
  setTxt("#llm-label-text", ui.picker_label);
  setTxt("#llm-help", ui.picker_help);
  setTxt("#vision-help", ui.vision_help);
  setTxt("#preview-help", ui.preview_help);
  setTxt("#reconcile-btn", ui.reconcile_web_btn);
  setTxt("#final-help", ui.final_help);
  setTxt("#photo-model-help", ui.photo_model_help);
  setTxt("#photo-neg-help", ui.photo_neg_help);
}

function renderPresets(presets, groups) {
  const labelOf = Object.fromEntries(groups.flatMap((g) => g.fields.map((f) => [f.key, f.label])));
  $("#preset-buttons").replaceChildren(...presets.map((p) => {
    const b = el("button", { type: "button", className: "ghost", textContent: p.name, title: p.about });
    b.addEventListener("click", () => {
      applyBuilderValues(p.values);
      schedulePreview();
      markStale();
      const changed = Object.keys(p.values).map((k) => labelOf[k] || k).join(", ");
      setMsg($("#builder-msg"), `Preset “${p.name}” set ${changed}. Everything else is unchanged.`);
    });
    return b;
  }));
}

function fillLlms(list, storageKey) {
  const sel = $("#llm-select");
  sel.replaceChildren(...list.map((d) => el("option", {
    value: d.name, textContent: d.label + (d.installed ? "" : " (not installed: run --llm-sync)"),
    disabled: !d.installed, className: d.caution ? "caution" : "", title: d.note,
  })));
  const saved = localStorage.getItem(storageKey);
  const pick = list.find((d) => d.name === saved && d.installed) || list.find((d) => d.default && d.installed) || list.find((d) => d.installed);
  if (pick) sel.value = pick.name;
  markCaution(sel);
  sel.addEventListener("change", () => { localStorage.setItem(storageKey, sel.value); markCaution(sel); });
}

/* ---------- Asset Studio: brief -> plan (local model) -> edit -> generate ---------- */
function initAssetStudio(o) {
  const f = $("#asset-form");
  const opts = o.assets || { kinds: [], models: [] };
  fillSelect(f.asset_kind, opts.kinds, { keepFirst: true });
  fillSelect(f.model, opts.models.map((m) => ({ key: m.key, label: m.label + (m.installed ? "" : " (not installed)") })));
  const llm = $("#llm-select");
  if (llm) {
    f.llm.replaceChildren(...[...llm.options].map((op) => op.cloneNode(true)));
    f.llm.value = llm.value;
  }
  const msg = $(".form-msg", f);
  const genMsg = $("#asset-gen-msg");
  let current = null;  // the last plan: {kind, title, concept, fields, plan}

  function showPlan(r, notes) {
    current = r;
    $("#asset-plan").hidden = false;
    $("#asset-fields").replaceChildren(...Object.entries(r.fields || {}).map(([k, v]) =>
      el("label", {}, k.replaceAll("_", " "), el("input", { name: `field:${k}`, value: String(v ?? ""), maxLength: 300 }))));
    f.concept.value = r.concept || "";
    const p = r.plan || {};
    for (const k of ["model", "width", "height", "steps", "seed", "remove_bg", "tile", "pixelate", "final_size", "export_sizes", "prompt", "negative"]) {
      if (f[k] && p[k] !== undefined && p[k] !== null) f[k].value = p[k];
    }
    const reasons = Object.entries(p.reasons || {}).map(([k, v]) => el("li", { textContent: `${k}: ${v}` }));
    const extra = (notes || []).map((n) => el("li", { textContent: n }));
    $("#asset-reasons").replaceChildren(...reasons, ...extra);
  }
  function editedFields() {
    const out = {};
    $$("input[name^='field:']", $("#asset-fields")).forEach((i) => { out[i.name.slice(6)] = i.value; });
    return out;
  }
  async function plan(body, btn) {
    btn.disabled = true;
    setMsg(msg, "Planning…");
    try {
      const job = await api("/api/jobs/asset_plan", { method: "POST", body });
      refreshJobs();
      const done = await waitForJob(job.id, (j) => setMsg(msg, j.message || j.status));
      if (done.status !== "done") throw new Error(done.error || done.message || "Planning failed");
      showPlan(done.result, done.notes);
      setMsg(msg, done.message, Boolean(done.result && done.result.refused));
    } catch (e) {
      setMsg(msg, e.message, true);
    } finally {
      btn.disabled = false;
    }
  }
  f.addEventListener("submit", (ev) => {
    ev.preventDefault();
    plan({ brief: f.brief.value, asset_kind: f.asset_kind.value, llm: f.llm.value }, $("button[type=submit]", f));
  });
  $("#asset-replan").addEventListener("click", (ev) => plan({
    brief: f.brief.value, asset_kind: (current && current.kind) || f.asset_kind.value, llm: f.llm.value,
    fields: editedFields(), concept: f.concept.value,
  }, ev.currentTarget));
  $("#asset-generate").addEventListener("click", async (ev) => {
    if (!current) return;
    const btn = ev.currentTarget;
    const p = { ...(current.plan || {}), kind: current.kind, title: current.title || "" };
    for (const k of ["model", "remove_bg", "tile", "final_size", "export_sizes", "prompt", "negative"]) p[k] = f[k].value;
    for (const k of ["width", "height", "steps", "seed", "pixelate"]) p[k] = Number(f[k].value);
    btn.disabled = true;
    try {
      const job = await api("/api/jobs/asset", { method: "POST", body: { plan: p } });
      setMsg(genMsg, `Queued (${job.id}). It shows up under Gallery → Assets when done.`);
      refreshJobs();
    } catch (e) {
      setMsg(genMsg, e.message, true);
    } finally {
      btn.disabled = false;
    }
  });
}

/* Gallery kind switch (Photos | Assets, plus any extension's kinds). */
document.addEventListener("click", (ev) => {
  const b = ev.target.closest(".gallery-head .seg-btn[data-kind]");
  if (!b) return;
  state.galleryKind = b.dataset.kind;
  $$(".gallery-head .seg-btn").forEach((x) => x.classList.toggle("active", x === b));
  $("#gallery-grid").classList.toggle("assets", state.galleryKind === "asset");
  state.selected = null;
  loadGallery();
});

/* ---------- attachments (reference image) ---------- */
function setAttachment(key, token, { thumb = "", label = "" } = {}) {
  const box = $(`.attach[data-attach="${key}"]`);
  if (!box) return;
  if (!token) {
    delete state.uploads[key];
    box.hidden = true;
    return;
  }
  state.uploads[key] = token;
  $("img", box).src = thumb;
  $("[data-attach-label]", box).textContent = label;
  box.hidden = false;
}

function bindAttachmentInputs(root = document) {
  $$("[data-clear]", root).forEach((b) => b.addEventListener("click", () => {
    setAttachment(b.dataset.clear, null);
    if (b.dataset.clear === "ref_upload") $("#photo-form").ref_mode.value = "none";
  }));

  $$("input[type=file][data-upload]", root).forEach((input) => {
    input.addEventListener("change", async () => {
      const key = input.dataset.upload;
      const msg = $(".form-msg", input.closest("form"));
      setAttachment(key, null);
      if (!input.files.length) return;
      const fd = new FormData();
      fd.append("file", input.files[0]);
      setMsg(msg, "Uploading image…");
      try {
        const res = await api("/api/uploads", { method: "POST", form: fd });
        setAttachment(key, res.upload, { thumb: URL.createObjectURL(input.files[0]), label: input.files[0].name });
        if (key === "ref_upload" && $("#photo-form").ref_mode.value === "none") $("#photo-form").ref_mode.value = "person";
        setMsg(msg, "Image attached.");
      } catch (e) {
        setMsg(msg, e.message, true);
      } finally {
        input.value = "";
      }
    });
  });
}
bindAttachmentInputs();

/* ---------- submit ---------- */
function formPayload(form, kind, uploadKey = "ref_upload") {
  const data = {};
  for (const f of form.elements) {
    if (!f.name || f.type === "file" || f.name === "preset") continue;
    data[f.name] = f.type === "checkbox" ? f.checked : f.value;
  }
  if (state.uploads[uploadKey]) data[uploadKey] = state.uploads[uploadKey];
  if (state.builder[kind]) data.builder = state.builder[kind];
  return data;
}

function bindJobForm(form, kind, uploadKey = "ref_upload") {
  form.prompt.addEventListener("input", () => { if (!form.prompt.value.trim()) state.builder[kind] = null; });
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const msg = $(".form-msg", form);
    const btn = $("button[type=submit]", form);
    btn.disabled = true;
    try {
      const job = await api(`/api/jobs/${kind}`, { method: "POST", body: formPayload(form, kind, uploadKey) });
      setMsg(msg, `Queued (${job.id}).${job.notes.length ? " " + job.notes.join(" · ") : ""}`);
      refreshJobs();
    } catch (e) {
      setMsg(msg, e.message, true);
    } finally {
      btn.disabled = false;
    }
  });
}
bindJobForm($("#photo-form"), "photo", "ref_upload");

async function waitForJob(id, onUpdate) {
  for (;;) {
    const job = await api(`/api/jobs/${id}`);
    onUpdate?.(job);
    if (!ACTIVE.has(job.status)) return job;
    await new Promise((r) => setTimeout(r, 1500));
  }
}

/* ---------- builder ---------- */
function renderBuilder(groups) {
  const root = $("#builder-fields");
  root.replaceChildren();
  for (const g of groups) {
    root.append(el("div", { className: "builder-group", textContent: g.group }));
    const grid = el("div", { className: "grid2" });
    for (const f of g.fields) {
      const sel = el("select", { name: f.key });
      for (const opt of f.options) sel.append(el("option", { value: opt, textContent: opt.split(":")[0] }));
      grid.append(el("label", {}, f.label, sel));
    }
    root.append(grid);
  }
}

function builderValues() {
  const vals = {};
  $$("#builder-fields select").forEach((s) => (vals[s.name] = s.value));
  return vals;
}

function applyBuilderValues(vals, { reset = false } = {}) {
  $$("#builder-fields select").forEach((s) => {
    if (vals[s.name] !== undefined && [...s.options].some((o) => o.value === vals[s.name])) s.value = vals[s.name];
    else if (reset) s.selectedIndex = 0;
  });
}

function mergeNegative(base, adds) {
  const neg = base.split(",").map((s) => s.trim()).filter(Boolean);
  for (const n of adds || []) if (!neg.includes(n)) neg.push(n);
  return neg.join(", ");
}

function setTarget(target) {
  state.target = target;
  $$("#builder-target .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.target === target));
  $("#send-btn").textContent = `Send to ${target === "photo" ? "Photo" : target[0].toUpperCase() + target.slice(1)}`;
  markStale();
  schedulePreview();
}

function builderSnapshot() {
  return JSON.stringify([state.target, builderValues(), $("#vision").value]);
}
function markStale() {
  $("#final-stale").hidden = !state.reconciled || state.reconciled.snapshot === builderSnapshot();
}

let previewTimer = null;
function schedulePreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    try {
      const r = await api("/api/builder/preview", { method: "POST", body: { target: state.target, values: builderValues(), vision: $("#vision").value } });
      $("#builder-preview").value = r.prompt;
      $("#preview-notes").textContent = r.notes.length ? `Conflict check: ${r.notes.join(" · ")}` : "";
    } catch (e) { /* preview is best-effort */ }
  }, 300);
}
$("#builder-fields").addEventListener("change", () => { schedulePreview(); markStale(); });
$("#vision").addEventListener("input", () => { schedulePreview(); markStale(); });

async function runBuilderJob(kind, body, buttons) {
  const msg = $("#builder-msg");
  buttons.forEach((b) => (b.disabled = true));
  try {
    const llmKey = state.options?.ui?.result_model_key || "llm";
    const queued = await api(`/api/jobs/${kind}`, { method: "POST", body: { ...body, llm: $("#llm-select").value, [llmKey]: $("#llm-select").value } });
    refreshJobs();
    const job = await waitForJob(queued.id, (j) => setMsg(msg, j.message));
    if (job.status !== "done") throw new Error(job.error || job.message);
    return job;
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}

$("#fill-btn").addEventListener("click", async () => {
  const vision = $("#vision").value.trim();
  if (!vision) return setMsg($("#builder-msg"), "Write your vision first.", true);
  try {
    const job = await runBuilderJob("fill", { vision, values: builderValues(), replace: $("#fill-replace").checked }, [$("#fill-btn")]);
    applyBuilderValues(job.result.values, { reset: true });
    schedulePreview();
    markStale();
    setMsg($("#builder-msg"), [...(job.notes || []), "Review the dropdowns, then Reconcile."].join(" · "));
  } catch (e) { setMsg($("#builder-msg"), e.message, true); }
});

$("#reconcile-btn").addEventListener("click", async () => {
  const snapshot = builderSnapshot();
  try {
    const job = await runBuilderJob("reconcile", { target: state.target, values: builderValues(), vision: $("#vision").value },
      [$("#reconcile-btn"), $("#send-btn")]);
    showReconciled(job.result, job.notes || [], snapshot);
    if (job.result?.refused) setMsg($("#builder-msg"), (job.notes || [])[0] || "Refused by instruct LLM.", true);
    else setMsg($("#builder-msg"), "Reconciled. Edit the Final prompt if you like, then Send.");
  } catch (e) { setMsg($("#builder-msg"), e.message, true); }
});

function showReconciled(r, notes, snapshot) {
  state.reconciled = { result: r, snapshot };
  $("#final-box").hidden = false;
  $("#final-prompt").value = r.prompt;
  $("#final-notes").textContent = notes.join(" · ");
  const llmKey = state.options?.ui?.result_model_key || "llm";
  const usedLlm = r[llmKey] || r.llm || "";
  const extraFmt = { text: "" };
  runHooks("showReconciled", r, extraFmt);
  const summary = extraFmt.text || `${r.model}, ${r.steps} steps, CFG ${r.cfg}, ${r.sampler}/${r.scheduler}`;
  $("#final-settings").textContent = `Will use ${summary}` + (usedLlm ? ` · reconciled by ${usedLlm}` : "");
  markStale();
}

$("#send-btn").addEventListener("click", () => {
  const rec = state.reconciled;
  const finalPrompt = $("#final-prompt").value.trim();
  if (!rec || !finalPrompt) return setMsg($("#builder-msg"), "Reconcile first.", true);
  const r = rec.result;
  const target = r.target;
  const [, values, vision] = JSON.parse(rec.snapshot);
  const form = $(`#${target}-form`);
  form.prompt.value = finalPrompt;
  const llmKey = state.options?.ui?.result_model_key || "llm";
  const usedLlm = r[llmKey] || r.llm || "";
  state.builder[target] = { values, vision, reconciled_prompt: r.prompt, final_prompt: finalPrompt, [llmKey]: usedLlm };
  form.steps.value = r.steps;
  form.cfg.value = r.cfg;
  form.sampler.value = r.sampler;
  form.scheduler.value = r.scheduler;
  if (target === "photo") {
    form.model.value = r.model;
    applyPhotoPreset(r.preset);
    form.vary_person.checked = !!r.vary_person;
    form.negative.value = mergeNegative(state.options.photo.default_negative, r.neg_additions);
  } else {
    runHooks("sendBuilder", target, form, r);
  }
  showTab(target);
  setMsg($(".form-msg", form), "Final prompt and settings are in. Queue it when ready.");
});

async function loadTemplates() {
  const res = await api("/api/templates");
  state.templates = res.templates;
  fillSelect($("#template-select"), res.templates.map((t) => ({ key: t.name, label: t.name })), { keepFirst: true });
}
$("#template-load").addEventListener("click", () => {
  const t = (state.templates || []).find((x) => x.name === $("#template-select").value);
  if (!t) return;
  applyBuilderValues(t.values, { reset: true });
  $("#vision").value = t.notes || "";
  schedulePreview();
  markStale();
  setMsg($("#builder-msg"), `Loaded template “${t.name}”.`);
});
$("#template-save").addEventListener("click", async () => {
  const name = prompt("Template name");
  if (!name) return;
  try {
    await api("/api/templates", { method: "POST", body: { name, values: builderValues(), notes: $("#vision").value } });
    await loadTemplates();
    $("#template-select").value = name;
    setMsg($("#builder-msg"), `Saved “${name}”.`);
  } catch (e) { setMsg($("#builder-msg"), e.message, true); }
});
$("#template-delete").addEventListener("click", async () => {
  const name = $("#template-select").value;
  if (!name || !confirm(`Delete template “${name}”?`)) return;
  await api(`/api/templates/${encodeURIComponent(name)}`, { method: "DELETE" });
  await loadTemplates();
});

/* ---------- queue ---------- */
function renderJobs(jobs) {
  const root = $("#jobs");
  if (!jobs.length) {
    root.replaceChildren(el("p", { className: "muted", textContent: "No jobs yet." }));
    return;
  }
  const shown = [...jobs.filter((j) => ACTIVE.has(j.status)), ...jobs.filter((j) => !ACTIVE.has(j.status)).slice(0, 10)];
  root.replaceChildren(...shown.map((j) => {
    const head = el("div", { className: "job-head" },
      el("span", { className: "kind", textContent: j.kind === "reconcile" ? "builder" : j.kind }),
      el("span", { className: "muted", textContent: new Date(j.created * 1000).toLocaleTimeString() }),
      el("span", { className: `state ${j.status}`, textContent: STATE_LABEL[j.status] || j.status }));
    const card = el("div", { className: "job" }, head, el("div", { className: "prompt", textContent: j.prompt, title: j.effective_prompt || "" }));
    card.append(el("div", { className: "msg", textContent: j.error ? `${j.message} ${j.error}` : j.message }));
    if (ACTIVE.has(j.status)) {
      const bar = el("div", { className: "bar" }, el("span"));
      bar.firstChild.style.width = `${j.progress || 0}%`;
      card.append(bar);
      const cancel = el("button", { className: "ghost danger", textContent: "Cancel", type: "button" });
      cancel.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        await api(`/api/jobs/${j.id}/cancel`, { method: "POST" });
        refreshJobs();
      });
      card.append(el("div", { className: "row" }, cancel));
    }
    if (j.status === "done" && j.outputs.length) {
      const thumbs = el("div", { className: "thumbs" });
      for (const out of j.outputs) {
        const rel = mediaRel(out);
        const img = el("img", { src: `/media/thumb/${encodeURI(rel)}`, alt: "", loading: "lazy" });
        img.addEventListener("click", (ev) => { ev.stopPropagation(); selectFromQueue(rel); });
        thumbs.append(img);
      }
      card.append(thumbs);
    }
    card.addEventListener("click", () => openLog(j.id));
    return card;
  }));
}

async function refreshJobs() {
  try {
    const [{ jobs }, status] = await Promise.all([api("/api/jobs"), api("/api/status")]);
    const sig = JSON.stringify(jobs.map((j) => [j.id, j.status, j.progress, j.message]));
    if (sig !== state.jobsSig) {
      const finished = state.jobsSig && jobs.some((j) => j.status === "done" && j.outputs.length && !state.jobsSig.includes(`"${j.id}","done"`));
      state.jobsSig = sig;
      renderJobs(jobs);
      if (finished) loadGallery();
    }
    runHooks("status", status);
  } catch (e) { /* transient network error: next poll retries */ }
}

async function openLog(id) {
  const job = await api(`/api/jobs/${id}`);
  $("#log-title").textContent = `${job.kind} · ${STATE_LABEL[job.status] || job.status}`;
  $("#log-prompt").textContent = job.effective_prompt || job.prompt;
  $("#log-body").textContent = [...job.notes, ...job.log].join("\n") || "(no output yet)";
  $("#log-dialog").showModal();
}
$("#log-close").addEventListener("click", () => $("#log-dialog").close());

/* ---------- gallery ---------- */
async function loadGallery() {
  const { items } = await api(`/api/media?kind=${state.galleryKind}`);
  state.galleryItems = items;
  const grid = $("#gallery-grid");
  if (!items.length) {
    grid.replaceChildren(el("p", { className: "muted", textContent: "Nothing here yet." }));
  } else {
    grid.replaceChildren(...items.map((it) => {
      const tile = el("button", { className: "tile", type: "button", title: `${it.name} · ${it.size} · ${it.mtime}` },
        el("img", { src: `/media/thumb/${encodeURI(it.rel)}`, alt: it.name, loading: "lazy" }),
        el("span", { className: "cap", textContent: it.name }));
      tile.dataset.rel = it.rel;
      if (it.kind === "photo") {
        tile.draggable = true;
        tile.addEventListener("dragstart", (ev) => ev.dataTransfer.setData("application/x-gs-rel", it.rel));
      }
      runHooks("tileRender", tile, it);
      tile.addEventListener("click", () => selectItem(it));
      return tile;
    }));
  }
  const sel = state.selected && items.find((i) => i.rel === state.selected.rel);
  selectItem(sel || null);
}

function updateActionButtons(root, it) {
  const isPhoto = it && it.kind === "photo";
  const refOn = state.options?.photo?.supports_ref !== false;
  $$("[data-photo-only]", root).forEach((b) => (b.hidden = !isPhoto));
  if (!refOn) $$("[data-photo-ref-only]", root).forEach((b) => (b.hidden = true));
  $$("[data-recipe-only]", root).forEach((b) => (b.hidden = !(it && it.has_recipe)));
  const composing = $("main.layout").classList.contains("composing");
  $$("[data-compose-only]", root).forEach((b) => (b.hidden = !(composing && isPhoto)));
  runHooks("actionButtons", root, it, isPhoto);
  const dl = $("[data-act=download]", root);
  if (it) dl.href = `/media/file/${encodeURI(it.rel)}?download=true`;
  const ex = $("[data-act=exports]", root);
  if (ex) {
    ex.hidden = !(it && it.kind === "asset");
    if (it) ex.href = `/api/media/exports?rel=${encodeURIComponent(it.rel)}`;
  }
}

function selectItem(it) {
  state.selected = it;
  $$(".tile").forEach((t) => t.classList.toggle("selected", !!it && t.dataset.rel === it.rel));
  const bar = $("#media-actions");
  bar.hidden = !it;
  if (!it) return;
  $(".sel-name", bar).textContent = it.name;
  updateActionButtons(bar, it);
}

async function selectFromQueue(rel) {
  const ctx = { kind: "photo" };
  runHooks("selectFromQueue", rel, ctx);
  if (state.galleryKind !== ctx.kind) state.galleryKind = ctx.kind;
  state.selected = { rel };
  await loadGallery();
  $("#media-actions").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function openViewer(it) {
  const src = `/media/file/${encodeURI(it.rel)}`;
  const res = { node: null };
  runHooks("viewerMedia", it, src, res);
  $(".viewer-body").replaceChildren(res.node || el("img", { src, alt: it.name }));
  updateActionButtons($("#viewer"), it);
  $("#viewer").showModal();
}
function closeViewer() {
  $(".viewer-body").replaceChildren();
  if ($("#viewer").open) $("#viewer").close();
}
$("#viewer-close").addEventListener("click", closeViewer);

function applyRecipe(r) {
  const form = $(`#${r.kind}-form`);
  const s = r.settings || {};
  const set = (name, v) => { if (v !== undefined && v !== null && form[name]) form[name].value = v; };
  form.prompt.value = r.variation ? `${r.prompt}, ${r.variation}` : (r.prompt || r.effective_prompt);
  set("negative", s.negative);
  for (const k of ["width", "height", "steps", "cfg", "sampler", "scheduler", "seed"]) set(k, s[k]);
  form.random_seed.checked = false;
  form.preset.value = "";
  if (r.kind === "photo") {
    set("model", s.model);
    set("lora", s.lora || "");
    set("lora_strength", s.lora_strength);
    set("ref_weight", s.ref_weight);
    form.vary_person.checked = false;
    if (r.reference_upload) {
      setAttachment("ref_upload", r.reference_upload, { thumb: `/api/uploads/${r.reference_upload}`, label: "from the original" });
      set("ref_mode", s.ref_mode);
    } else {
      setAttachment("ref_upload", null);
      form.ref_mode.value = "none";
    }
  } else {
    runHooks("applyRecipe", r, form, set);
  }
  state.builder[r.kind] = r.builder
    ? { values: r.builder.values, vision: r.builder.vision, reconciled_prompt: r.builder.reconciled_prompt } : null;
  if (r.builder) {
    applyBuilderValues(r.builder.values || {}, { reset: true });
    $("#vision").value = r.builder.vision || "";
    const sel = $("#llm-select");
    const llmKey = state.options?.ui?.result_model_key || "llm";
    const savedLlm = r.builder[llmKey] || r.builder.llm || "";
    if (savedLlm && [...sel.options].some((o) => o.value === savedLlm && !o.disabled)) { sel.value = savedLlm; markCaution(sel); }
    state.target = r.kind;
    setTarget(r.kind);
    const settings = r.kind === "photo"
      ? { model: s.model, steps: s.steps, cfg: s.cfg, sampler: s.sampler, scheduler: s.scheduler }
      : { version: s.version, steps: s.steps, cfg: s.cfg, sampler: s.sampler, scheduler: s.scheduler, duration: s.duration_sec, fps: s.fps };
    showReconciled({ ...settings, target: r.kind, prompt: r.builder.reconciled_prompt || r.prompt, [llmKey]: savedLlm, ...importedSendSettings(r) },
      ["Imported: this is the Final prompt it was made with."], builderSnapshot());
    $("#final-prompt").value = r.builder.final_prompt || r.prompt;
  }
}

function importedSendSettings(r) {
  const s = r.settings || {};
  const neg = (s.negative || "").split(",").map((x) => x.trim()).filter(Boolean);
  const srcDefaults = r.kind === "photo" ? state.options.photo : (state.options[r.kind] || state.options.photo);
  const base = (srcDefaults?.default_negative || "").split(",").map((x) => x.trim());
  return r.kind === "photo"
    ? { preset: "", vary_person: false, neg_additions: neg.filter((n) => !base.includes(n)), width: s.width, height: s.height }
    : { width: s.width, height: s.height, neg_additions: neg.filter((n) => !base.includes(n)) };
}

const ACTIONS = {
  view: (it) => openViewer(it),
  async import(it) {
    const r = await api(`/api/library/recipe?rel=${encodeURIComponent(it.rel)}`);
    applyRecipe(r);
    closeViewer();
    const kindLabel = r.kind[0].toUpperCase() + r.kind.slice(1);
    const lost = r.had_reference && !r.reference_upload ? " Its reference image has expired; attach one again if you need it." : "";
    if (r.builder) {
      showTab("builder");
      setMsg($("#builder-msg"), `Imported ${r.name}: dropdowns and vision restored, and the ${r.kind} form has its exact prompt and settings (same seed). Change things and Send to ${kindLabel}, or tweak the ${r.kind} form directly.${lost}`);
    } else {
      showTab(r.kind);
      setMsg($(".form-msg", $(`#${r.kind}-form`)), `Imported ${r.name}: exact prompt and settings (same seed). It wasn't made with the Prompt Builder, so there are no dropdowns to restore.${lost}`);
    }
  },
  async "photo-ref"(it) {
    const r = await api("/api/media/use-as-reference", { method: "POST", body: { rel: it.rel } });
    const pf = $("#photo-form");
    setAttachment("ref_upload", r.upload, { thumb: `/media/thumb/${encodeURI(it.rel)}`, label: `${r.name} · keeps the ${r.ref_mode === "person" ? "face" : "room"}` });
    pf.ref_mode.value = r.ref_mode;
    pf.ref_weight.value = 0.75;
    closeViewer();
    showTab("photo");
    setMsg($(".form-msg", pf), `Reference attached (${r.ref_mode}). Change the mode under Advanced if needed.`);
  },
  async delete(it) {
    if (!confirm(`Delete ${it.name}? This removes the file.`)) return;
    await api(`/api/media/${encodeURI(it.rel)}`, { method: "DELETE" });
    closeViewer();
    state.selected = null;
    loadGallery();
  },
};

for (const root of [$("#media-actions"), $("#viewer")]) {
  root.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-act]");
    if (!btn || btn.dataset.act === "download" || !state.selected) return;
    const handler = ACTIONS[btn.dataset.act];
    if (!handler) return;
    try {
      await handler(state.selected);
    } catch (e) {
      alert(e.message);
    }
  });
}

window.GS = {
  $, $$, el, api, state, APP_LABEL, setMsg, showTab, fillSelect, markCaution,
  setAttachment, bindAttachmentInputs, bindJobForm, mergeNegative, setTarget,
  refreshJobs, loadGallery, openViewer, closeViewer, ACTIONS,
  on: (name, fn) => hooks[name].push(fn),
};

/* ---------- boot ---------- */
(async () => {
  await loadOptions();
  initAssetStudio(state.options);
  setTarget("photo");
  await Promise.all([loadTemplates(), loadGallery(), refreshJobs()]);
  setInterval(refreshJobs, 2000);
})();
