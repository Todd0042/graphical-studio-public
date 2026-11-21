"use strict";
/* Compose: drop an image -> its subject is cut out -> it lands as the top layer -> drag to move,
   drag a corner (or pinch / scroll) to scale -> pick a background preset -> Flatten & Save.
   Everything is drawn on one canvas at the real output size; the server only cuts subjects out
   and stores the flattened PNG. Uses $, el, api, setMsg, state, ACTIONS from app.js. */

const cmp = {
  canvas: null, ctx: null, W: 1920, H: 1080,
  layers: [],          // bottom -> top: {id, upload, name, img, x, y, scale, flip, alpha: canvas|null}
  selected: null,      // layer id
  images: new Map(),   // upload token -> HTMLImageElement
  bgImage: null,       // {upload, img} when the background is a photo
  undo: [],
  drag: null,          // {mode: "move"|"scale"|"pinch", ...}
  pointers: new Map(),
  guides: [],
};
const CMP_SIZES = [
  ["1920×1080 (HD wallpaper)", 1920, 1080], ["2560×1440 (QHD)", 2560, 1440], ["3840×2160 (4K)", 3840, 2160],
  ["1080×1920 (phone)", 1080, 1920], ["1080×1080 (square)", 1080, 1080], ["1280×720", 1280, 720],
];
const CMP_BGS = [
  ["solid", "Solid color"], ["linear", "Linear gradient"], ["radial", "Radial glow / vignette"],
  ["bands", "Repeating gradient bands"], ["split", "Two-tone split"], ["stripes", "Stripes"],
  ["dots", "Polka dots"], ["halftone", "Halftone fade"], ["checker", "Checkerboard"], ["image", "Photo (from gallery)"],
];
const CMP_SWATCHES = [
  ["Pure black", "#000000", "#1a1a1a"], ["Charcoal", "#141414", "#2b2b2b"], ["Mid grey", "#555555", "#888888"],
  ["White", "#ffffff", "#e6e6e6"], ["Navy", "#05070f", "#16213e"], ["Midnight purple", "#0b0614", "#2a1846"],
  ["Crimson", "#1a0004", "#7a0a1c"], ["Teal", "#021414", "#0d4d4d"], ["Sunset", "#ff7a3d", "#5b1d7a"], ["Pastel pink", "#ffd6e3", "#ff9fbf"],
];
const SNAP_PX = 14;  // screen pixels

/* ---------- setup ---------- */
function cmpInit() {
  cmp.canvas = $("#cmp-canvas");
  ColorPicker.bind($("#cmp-c1"), "Color 1");
  ColorPicker.bind($("#cmp-c2"), "Color 2");
  cmp.ctx = cmp.canvas.getContext("2d");
  fillSelect($("#cmp-size"), CMP_SIZES.map(([l]) => ({ key: l, label: l })));
  fillSelect($("#cmp-bg-type"), CMP_BGS.map(([k, l]) => ({ key: k, label: l })));
  $("#cmp-swatches").replaceChildren(...CMP_SWATCHES.map(([name, c1, c2]) => {
    const b = el("button", { type: "button", className: "swatch", title: name });
    b.style.background = `linear-gradient(135deg, ${c1}, ${c2})`;
    b.addEventListener("click", () => {
      $("#cmp-c1").value = c1; $("#cmp-c2").value = c2;
      ColorPicker.refresh();
      ColorPicker.remember(c2); ColorPicker.remember(c1);
      cmpCommit();
    });
    return b;
  }));
  for (const id of ["#cmp-bg-type", "#cmp-c1", "#cmp-c2", "#cmp-angle", "#cmp-density", "#cmp-vignette", "#cmp-start"]) {
    $(id).addEventListener("input", () => { cmpBgControls(); cmpDraw(); });
    $(id).addEventListener("change", () => cmpPushUndo());
  }
  $("#cmp-size").addEventListener("change", () => {
    const [, w, h] = CMP_SIZES.find(([l]) => l === $("#cmp-size").value);
    const sx = w / cmp.W, sy = h / cmp.H;
    for (const L of cmp.layers) { L.x *= sx; L.y *= sy; L.scale *= Math.min(sx, sy); }
    cmpResize(w, h);
    cmpCommit();
  });
  cmpResize(1920, 1080);
  cmpBgControls();

  const stage = $("#cmp-stage");
  stage.addEventListener("dragover", (e) => { e.preventDefault(); stage.classList.add("dropping"); });
  stage.addEventListener("dragleave", () => stage.classList.remove("dropping"));
  stage.addEventListener("drop", cmpOnDrop);
  $("#cmp-file").addEventListener("change", async (e) => {
    for (const f of e.target.files) await cmpAddFile(f);
    e.target.value = "";
  });
  cmp.canvas.addEventListener("pointerdown", cmpPointerDown);
  cmp.canvas.addEventListener("pointermove", cmpPointerMove);
  cmp.canvas.addEventListener("pointerup", cmpPointerUp);
  cmp.canvas.addEventListener("pointercancel", cmpPointerUp);
  cmp.canvas.addEventListener("wheel", cmpWheel, { passive: false });
  document.addEventListener("keydown", cmpKey);
  window.addEventListener("resize", cmpDraw);

  $("#cmp-undo").addEventListener("click", cmpUndo);
  $("#cmp-fade-on").addEventListener("change", () => { cmpFadeFromPanel(); cmpPushUndo(); });
  for (const id of ["#cmp-fade-angle", "#cmp-fade-start", "#cmp-fade-end"]) {
    $(id).addEventListener("input", cmpFadeFromPanel);
    $(id).addEventListener("change", cmpPushUndo);
  }
  $("#cmp-clear").addEventListener("click", () => {
    if (cmp.layers.length && !confirm("Remove every layer?")) return;
    cmp.layers = []; cmp.selected = null; cmpCommit();
  });
  $("#cmp-save").addEventListener("click", cmpSave);
  $("#cmp-download").addEventListener("click", cmpDownload);
  $$("[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  cmpPushUndo();
  cmpRenderLayerList();
}

function setMode(mode) {
  const composing = mode === "compose";
  $("main.layout").classList.toggle("composing", composing);
  $("#compose").hidden = !composing;
  $$("[data-mode]").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  if (state.selected) updateActionButtons($("#media-actions"), state.selected);
  if (composing) { cmpDraw(); if (state.galleryKind !== "photo") { setGalleryKind("photo"); loadGallery(); } }
}

function cmpResize(w, h) {
  cmp.W = w; cmp.H = h;
  cmp.canvas.width = w; cmp.canvas.height = h;
  $("#cmp-size").value = CMP_SIZES.find(([, a, b]) => a === w && b === h)[0];
  cmpDraw();
}

function cmpBgControls() {
  const t = $("#cmp-bg-type").value;
  $("#cmp-angle-wrap").hidden = !["linear", "bands", "split", "stripes", "halftone"].includes(t);
  $("#cmp-start-wrap").hidden = !["linear", "radial"].includes(t);
  $("#cmp-start-num").textContent = `${$("#cmp-start").value}%`;
  $("#cmp-density-wrap").hidden = !["bands", "stripes", "dots", "halftone", "checker"].includes(t);
  $("#cmp-colors").hidden = t === "image";
  $("#cmp-bg-photo-note").hidden = t !== "image";
}

/* ---------- drawing ---------- */
function cmpDraw(withUi = true) {
  const { ctx, W, H } = cmp;
  ctx.save();
  ctx.clearRect(0, 0, W, H);
  drawBackground(ctx, W, H);
  for (const L of cmp.layers) {
    const w = L.img.naturalWidth * L.scale, h = L.img.naturalHeight * L.scale;
    if (L.fade) {
      ctx.drawImage(fadedLayer(L, w, h), L.x - w / 2, L.y - h / 2, w, h);
      continue;
    }
    ctx.save();
    ctx.translate(L.x, L.y);
    if (L.flip) ctx.scale(-1, 1);
    ctx.drawImage(L.img, -w / 2, -h / 2, w, h);
    ctx.restore();
  }
  const vig = Number($("#cmp-vignette").value);
  if (vig > 0) {  // darkened edges over everything, like the dark wallpapers
    const g = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.25, W / 2, H / 2, Math.hypot(W, H) / 2);
    g.addColorStop(0, "rgba(0,0,0,0)");
    g.addColorStop(1, `rgba(0,0,0,${vig})`);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
  }
  if (withUi) drawSelection(ctx);
  ctx.restore();
}

function drawBackground(ctx, W, H) {
  const t = $("#cmp-bg-type").value, c1 = $("#cmp-c1").value, c2 = $("#cmp-c2").value;
  const angle = (Number($("#cmp-angle").value) * Math.PI) / 180, n = Number($("#cmp-density").value);
  const diag = Math.hypot(W, H);
  const start = Number($("#cmp-start").value) / 100;  // Color 1 holds solid until here, then fades to Color 2
  ctx.fillStyle = c1;
  ctx.fillRect(0, 0, W, H);
  const rotated = (fn) => { ctx.save(); ctx.translate(W / 2, H / 2); ctx.rotate(angle); fn(); ctx.restore(); };
  if (t === "linear") {
    const dx = Math.cos(angle) * diag / 2, dy = Math.sin(angle) * diag / 2;
    const g = ctx.createLinearGradient(W / 2 - dx, H / 2 - dy, W / 2 + dx, H / 2 + dy);
    g.addColorStop(0, c1); g.addColorStop(start, c1); g.addColorStop(1, c2);
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  } else if (t === "radial") {
    const g = ctx.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, diag / 2);
    g.addColorStop(0, c1); g.addColorStop(start, c1); g.addColorStop(1, c2);
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  } else if (t === "bands") {
    rotated(() => {
      const step = diag / n;
      for (let i = 0; i < n; i++) {
        const x0 = -diag / 2 + i * step;
        const g = ctx.createLinearGradient(x0, 0, x0 + step, 0);
        g.addColorStop(0, c1); g.addColorStop(1, c2);
        ctx.fillStyle = g; ctx.fillRect(x0, -diag / 2, step + 1, diag);
      }
    });
  } else if (t === "split") {
    rotated(() => { ctx.fillStyle = c2; ctx.fillRect(0, -diag / 2, diag / 2, diag); });
  } else if (t === "stripes") {
    rotated(() => {
      const step = diag / (n * 2);
      ctx.fillStyle = c2;
      for (let x = -diag / 2; x < diag / 2; x += step * 2) ctx.fillRect(x, -diag / 2, step, diag);
    });
  } else if (t === "dots" || t === "halftone") {
    const step = Math.max(W, H) / n;
    ctx.fillStyle = c2;
    for (let y = step / 2; y < H + step; y += step) {
      for (let x = step / 2; x < W + step; x += step) {
        let r = step * 0.3;
        if (t === "halftone") {  // dots shrink across the image along the angle
          const p = ((x - W / 2) * Math.cos(angle) + (y - H / 2) * Math.sin(angle)) / diag + 0.5;
          r = step * 0.48 * Math.max(0, Math.min(1, 1 - p));
        }
        if (r > 0.5) { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); }
      }
    }
  } else if (t === "checker") {
    const step = Math.max(W, H) / n;
    ctx.fillStyle = c2;
    for (let y = 0, row = 0; y < H; y += step, row++)
      for (let x = (row % 2) * step; x < W; x += step * 2) ctx.fillRect(x, y, step, step);
  } else if (t === "image" && cmp.bgImage) {  // cover the canvas, centered
    const img = cmp.bgImage.img, s = Math.max(W / img.naturalWidth, H / img.naturalHeight);
    const w = img.naturalWidth * s, h = img.naturalHeight * s;
    ctx.drawImage(img, (W - w) / 2, (H - h) / 2, w, h);
  }
}

/* Fade edge: the layer as shown (flip included), multiplied by an alpha ramp that is 100% at the
   "starts" line and 0% at the "gone" line, measured across the layer's box along the angle. */
function fadeLine(L, w, h) {
  const a = (L.fade.angle * Math.PI) / 180, dx = Math.cos(a), dy = Math.sin(a);
  const span = Math.abs(w * dx) + Math.abs(h * dy);  // the box's extent along the fade direction
  const p0 = -span / 2 + (L.fade.start / 100) * span, p1 = -span / 2 + (Math.max(L.fade.end, L.fade.start + 0.5) / 100) * span;
  return { dx, dy, p0, p1 };
}

function fadedLayer(L, w, h) {
  const c = cmp.fadeCanvas || (cmp.fadeCanvas = document.createElement("canvas"));
  c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h));
  const x = c.getContext("2d");
  x.save();
  x.translate(c.width / 2, c.height / 2);
  if (L.flip) x.scale(-1, 1);
  x.drawImage(L.img, -c.width / 2, -c.height / 2, c.width, c.height);
  x.restore();
  const { dx, dy, p0, p1 } = fadeLine(L, c.width, c.height);
  const g = x.createLinearGradient(c.width / 2 + dx * p0, c.height / 2 + dy * p0, c.width / 2 + dx * p1, c.height / 2 + dy * p1);
  g.addColorStop(0, "rgba(0,0,0,1)");
  g.addColorStop(1, "rgba(0,0,0,0)");
  x.globalCompositeOperation = "destination-in";
  x.fillStyle = g;
  x.fillRect(0, 0, c.width, c.height);
  x.globalCompositeOperation = "source-over";
  return c;
}

function layerBox(L) {
  const w = L.img.naturalWidth * L.scale, h = L.img.naturalHeight * L.scale;
  return { l: L.x - w / 2, t: L.y - h / 2, r: L.x + w / 2, b: L.y + h / 2, w, h };
}
function screenScale() { return cmp.canvas.getBoundingClientRect().width / cmp.W; }  // screen px per canvas px

function drawSelection(ctx) {
  const L = cmp.layers.find((x) => x.id === cmp.selected);
  const k = 1 / screenScale();
  ctx.lineWidth = 1.5 * k;
  for (const g of cmp.guides) {
    ctx.strokeStyle = "rgba(90,209,196,.9)";
    ctx.setLineDash([6 * k, 6 * k]);
    ctx.beginPath();
    if (g.x !== undefined) { ctx.moveTo(g.x, 0); ctx.lineTo(g.x, cmp.H); } else { ctx.moveTo(0, g.y); ctx.lineTo(cmp.W, g.y); }
    ctx.stroke();
  }
  ctx.setLineDash([]);
  if (!L) return;
  const b = layerBox(L), hs = 10 * k;
  ctx.strokeStyle = "#7c6cff";
  ctx.strokeRect(b.l, b.t, b.w, b.h);
  if (L.fade) {
    const { dx, dy, p0, p1 } = fadeLine(L, b.w, b.h), long = Math.hypot(b.w, b.h);
    ctx.save();
    ctx.beginPath(); ctx.rect(b.l, b.t, b.w, b.h); ctx.clip();
    ctx.setLineDash([8 * k, 6 * k]);
    for (const [p, color] of [[p0, "rgba(255,255,255,.9)"], [p1, "rgba(255,90,90,.9)"]]) {
      const cx = L.x + dx * p, cy = L.y + dy * p;
      ctx.strokeStyle = color;
      ctx.beginPath(); ctx.moveTo(cx - dy * long, cy + dx * long); ctx.lineTo(cx + dy * long, cy - dx * long); ctx.stroke();
    }
    ctx.restore();
  }
  ctx.fillStyle = "#fff";
  for (const [x, y] of [[b.l, b.t], [b.r, b.t], [b.l, b.b], [b.r, b.b]]) {
    ctx.fillRect(x - hs / 2, y - hs / 2, hs, hs);
    ctx.strokeRect(x - hs / 2, y - hs / 2, hs, hs);
  }
}

/* ---------- layers ---------- */
function loadImage(token) {
  if (cmp.images.has(token)) return Promise.resolve(cmp.images.get(token));
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => { cmp.images.set(token, img); resolve(img); };
    img.onerror = () => reject(new Error("That image has expired; add it again."));
    img.src = `/api/uploads/${token}`;
  });
}

// Alpha mask for picking: clicking a transparent pixel of a cutout selects what's under it.
function alphaCanvas(img) {
  const s = Math.min(1, 512 / Math.max(img.naturalWidth, img.naturalHeight));
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(img.naturalWidth * s)); c.height = Math.max(1, Math.round(img.naturalHeight * s));
  c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
  return { c, s, data: c.getContext("2d").getImageData(0, 0, c.width, c.height).data };
}

async function cmpAddLayer({ upload, name }, { fit = true } = {}) {
  const img = await loadImage(upload);
  const scale = fit ? Math.min((cmp.H * 0.85) / img.naturalHeight, (cmp.W * 0.85) / img.naturalWidth) : 1;
  const L = { id: crypto.randomUUID(), upload, name: name || "layer", img, x: cmp.W / 2, y: cmp.H / 2, scale, flip: false, alpha: alphaCanvas(img) };
  cmp.layers.push(L);
  cmp.selected = L.id;
  cmpCommit();
  return L;
}

async function cmpCutOut(upload) {
  const model = $("#cmp-model").value;
  setMsg($("#cmp-msg"), "Cutting out the subject… (a few seconds; the first cut after a restart takes longer)");
  return api("/api/compose/cutout", { method: "POST", body: { upload, model } });
}

async function cmpAddFile(file) {
  const msg = $("#cmp-msg");
  try {
    const fd = new FormData();
    fd.append("file", file);
    setMsg(msg, `Adding ${file.name}…`);
    let r = await api("/api/compose/upload", { method: "POST", form: fd });
    if ($("#cmp-auto-cut").checked) r = await cmpCutOut(r.upload);
    await cmpAddLayer({ upload: r.upload, name: file.name });
    setMsg(msg, `${file.name} added on top. Drag to move, drag a corner to resize.`);
  } catch (e) { setMsg(msg, e.message, true); }
}

async function cmpAddFromGallery(rel, { asBackground = false } = {}) {
  const msg = $("#cmp-msg");
  try {
    let r = await api("/api/compose/from-gallery", { method: "POST", body: { rel } });
    if (asBackground) {
      cmp.bgImage = { upload: r.upload, img: await loadImage(r.upload) };
      $("#cmp-bg-type").value = "image";
      cmpBgControls();
      cmpCommit();
      setMsg(msg, `${r.name} is the background.`);
      return;
    }
    const name = r.name;
    if ($("#cmp-auto-cut").checked) r = await cmpCutOut(r.upload);
    await cmpAddLayer({ upload: r.upload, name });
    setMsg(msg, `${name} added on top. Drag to move, drag a corner to resize.`);
  } catch (e) { setMsg(msg, e.message, true); }
}

async function cmpOnDrop(e) {
  e.preventDefault();
  $("#cmp-stage").classList.remove("dropping");
  const rel = e.dataTransfer.getData("application/x-gs-rel");
  if (rel) return cmpAddFromGallery(rel);
  for (const f of e.dataTransfer.files) if (f.type.startsWith("image/")) await cmpAddFile(f);
}

function cmpSyncFadePanel() {
  const L = cmp.layers.find((x) => x.id === cmp.selected);
  $("#cmp-fade").disabled = !L;
  const f = (L && L.fade) || { angle: 90, start: 70, end: 100 };
  $("#cmp-fade-on").checked = !!(L && L.fade);
  $("#cmp-fade-angle").value = f.angle; $("#cmp-fade-start").value = f.start; $("#cmp-fade-end").value = f.end;
  $("#cmp-fade-angle-num").textContent = `${f.angle}°`;
  $("#cmp-fade-start-num").textContent = `${f.start}%`;
  $("#cmp-fade-end-num").textContent = `${f.end}%`;
  for (const id of ["#cmp-fade-angle", "#cmp-fade-start", "#cmp-fade-end"]) $(id).disabled = !(L && L.fade);
}

function cmpFadeFromPanel() {
  const L = cmp.layers.find((x) => x.id === cmp.selected);
  if (!L) return;
  L.fade = $("#cmp-fade-on").checked
    ? { angle: Number($("#cmp-fade-angle").value), start: Number($("#cmp-fade-start").value), end: Number($("#cmp-fade-end").value) }
    : null;
  cmpSyncFadePanel();
  cmpDraw();
}

function cmpRenderLayerList() {
  cmpSyncFadePanel();
  const list = $("#cmp-layers");
  if (!cmp.layers.length) {
    list.replaceChildren(el("li", { className: "muted", textContent: "No layers yet: drop a picture on the canvas." }));
    return;
  }
  list.replaceChildren(...[...cmp.layers].reverse().map((L) => {
    const i = cmp.layers.indexOf(L);
    const btn = (label, title, fn) => {
      const b = el("button", { type: "button", className: "ghost", textContent: label, title });
      b.addEventListener("click", (ev) => { ev.stopPropagation(); fn(); });
      return b;
    };
    const li = el("li", { className: L.id === cmp.selected ? "selected" : "" },
      el("img", { src: `/api/uploads/${L.upload}`, alt: "" }),
      el("span", { className: "name", textContent: L.name }),
      btn("↑", "Bring forward", () => cmpMove(i, +1)),
      btn("↓", "Send backward", () => cmpMove(i, -1)),
      btn("⇋", "Flip horizontally", () => { L.flip = !L.flip; cmpCommit(); }),
      btn("✂", "Remove this layer's background", () => cmpRecut(L)),
      btn("✕", "Delete layer", () => cmpDelete(L.id)));
    li.addEventListener("click", () => { cmp.selected = L.id; cmpDraw(); cmpRenderLayerList(); });
    return li;
  }));
}

function cmpMove(i, dir) {
  const j = i + dir;
  if (j < 0 || j >= cmp.layers.length) return;
  [cmp.layers[i], cmp.layers[j]] = [cmp.layers[j], cmp.layers[i]];
  cmpCommit();
}
function cmpDelete(id) {
  cmp.layers = cmp.layers.filter((L) => L.id !== id);
  if (cmp.selected === id) cmp.selected = null;
  cmpCommit();
}
async function cmpRecut(L) {
  try {
    const r = await cmpCutOut(L.upload);
    const height = L.img.naturalHeight * L.scale;
    L.upload = r.upload;
    L.img = await loadImage(r.upload);
    L.alpha = alphaCanvas(L.img);
    L.scale = height / L.img.naturalHeight * 0.95;  // the cutout is cropped tighter; keep it about as tall
    cmpCommit();
    setMsg($("#cmp-msg"), "Background removed.");
  } catch (e) { setMsg($("#cmp-msg"), e.message, true); }
}

/* ---------- pointer: move, corner scale, pinch, wheel ---------- */
function toCanvas(e) {
  const r = cmp.canvas.getBoundingClientRect();
  return { x: ((e.clientX - r.left) / r.width) * cmp.W, y: ((e.clientY - r.top) / r.height) * cmp.H };
}

function hitLayer(p) {
  for (let i = cmp.layers.length - 1; i >= 0; i--) {
    const L = cmp.layers[i], b = layerBox(L);
    if (p.x < b.l || p.x > b.r || p.y < b.t || p.y > b.b) continue;
    let u = (p.x - b.l) / b.w, v = (p.y - b.t) / b.h;
    if (L.flip) u = 1 - u;
    const a = L.alpha;
    const px = Math.min(a.c.width - 1, Math.floor(u * a.c.width)), py = Math.min(a.c.height - 1, Math.floor(v * a.c.height));
    if (a.data[(py * a.c.width + px) * 4 + 3] > 20) return L;
  }
  return null;
}

function hitHandle(p) {
  const L = cmp.layers.find((x) => x.id === cmp.selected);
  if (!L) return null;
  const b = layerBox(L), r = 14 / screenScale();
  const corners = [[b.l, b.t, b.r, b.b], [b.r, b.t, b.l, b.b], [b.l, b.b, b.r, b.t], [b.r, b.b, b.l, b.t]];
  for (const [x, y, ax, ay] of corners) if (Math.abs(p.x - x) <= r && Math.abs(p.y - y) <= r) return { L, anchor: { x: ax, y: ay } };
  return null;
}

function cmpPointerDown(e) {
  cmp.canvas.setPointerCapture(e.pointerId);
  const p = toCanvas(e);
  cmp.pointers.set(e.pointerId, p);
  const L = cmp.layers.find((x) => x.id === cmp.selected);
  if (cmp.pointers.size === 2 && L) {  // second finger: pinch to scale
    const [a, b] = [...cmp.pointers.values()];
    cmp.drag = { mode: "pinch", L, dist: Math.hypot(a.x - b.x, a.y - b.y), scale: L.scale };
    return;
  }
  const h = hitHandle(p);
  if (h) {
    cmp.drag = { mode: "scale", L: h.L, anchor: h.anchor, start: p, scale: h.L.scale, cx: h.L.x, cy: h.L.y };
    return;
  }
  const hit = hitLayer(p);
  cmp.selected = hit ? hit.id : null;
  cmp.drag = hit ? { mode: "move", L: hit, start: p, x: hit.x, y: hit.y } : null;
  cmpDraw();
  cmpRenderLayerList();
}

function cmpPointerMove(e) {
  if (!cmp.pointers.has(e.pointerId)) {
    const p = toCanvas(e);
    cmp.canvas.style.cursor = hitHandle(p) ? "nwse-resize" : hitLayer(p) ? "move" : "default";
    return;
  }
  const p = toCanvas(e);
  cmp.pointers.set(e.pointerId, p);
  const d = cmp.drag;
  if (!d) return;
  if (d.mode === "move") {
    let x = d.x + p.x - d.start.x, y = d.y + p.y - d.start.y;
    cmp.guides = [];
    if (!e.altKey) {  // snap the layer's center to the middle and the thirds (hold Alt to place freely)
      const tol = SNAP_PX / screenScale();
      for (const gx of [cmp.W / 3, cmp.W / 2, (2 * cmp.W) / 3]) if (Math.abs(x - gx) < tol) { x = gx; cmp.guides.push({ x: gx }); }
      for (const gy of [cmp.H / 2]) if (Math.abs(y - gy) < tol) { y = gy; cmp.guides.push({ y: gy }); }
    }
    d.L.x = x; d.L.y = y;
  } else if (d.mode === "scale") {
    const ratio = Math.max(0.02, Math.hypot(p.x - d.anchor.x, p.y - d.anchor.y) / Math.hypot(d.start.x - d.anchor.x, d.start.y - d.anchor.y));
    d.L.scale = d.scale * ratio;  // the opposite corner stays put
    d.L.x = d.anchor.x + (d.cx - d.anchor.x) * ratio;
    d.L.y = d.anchor.y + (d.cy - d.anchor.y) * ratio;
  } else if (d.mode === "pinch" && cmp.pointers.size === 2) {
    const [a, b] = [...cmp.pointers.values()];
    d.L.scale = Math.max(0.02, d.scale * (Math.hypot(a.x - b.x, a.y - b.y) / d.dist));
  }
  cmpDraw();
}

function cmpPointerUp(e) {
  cmp.pointers.delete(e.pointerId);
  if (cmp.pointers.size) return;
  if (cmp.drag) cmpPushUndo();
  cmp.drag = null;
  cmp.guides = [];
  cmpDraw();
}

function cmpWheel(e) {
  const L = cmp.layers.find((x) => x.id === cmp.selected);
  if (!L) return;
  e.preventDefault();
  L.scale = Math.max(0.02, L.scale * Math.pow(1.0015, -e.deltaY));
  cmpDraw();
  clearTimeout(cmp.wheelTimer);
  cmp.wheelTimer = setTimeout(cmpPushUndo, 400);
}

function cmpKey(e) {
  if ($("#compose").hidden || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "")) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); cmpUndo(); return; }
  const L = cmp.layers.find((x) => x.id === cmp.selected);
  if (!L) return;
  const step = e.shiftKey ? 10 : 1;
  const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
  if (moves[e.key]) { e.preventDefault(); L.x += moves[e.key][0]; L.y += moves[e.key][1]; cmpCommit(); }
  else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); cmpDelete(L.id); }
}

/* ---------- undo ---------- */
function cmpSnapshot() {
  return JSON.stringify({
    size: [cmp.W, cmp.H], selected: cmp.selected, bgImage: cmp.bgImage && cmp.bgImage.upload,
    bg: Object.fromEntries(["cmp-bg-type", "cmp-c1", "cmp-c2", "cmp-angle", "cmp-density", "cmp-vignette", "cmp-start"].map((id) => [id, $(`#${id}`).value])),
    layers: cmp.layers.map(({ id, upload, name, x, y, scale, flip, fade }) => ({ id, upload, name, x, y, scale, flip, fade: fade || null })),
  });
}
function cmpPushUndo() {
  const snap = cmpSnapshot();
  if (cmp.undo[cmp.undo.length - 1] !== snap) cmp.undo.push(snap);
  if (cmp.undo.length > 100) cmp.undo.shift();
}
function cmpCommit() { cmpDraw(); cmpRenderLayerList(); cmpPushUndo(); }

async function cmpUndo() {
  if (cmp.undo.length < 2) return;
  cmp.undo.pop();
  const s = JSON.parse(cmp.undo[cmp.undo.length - 1]);
  for (const [id, v] of Object.entries(s.bg)) $(`#${id}`).value = v;
  cmpResize(s.size[0], s.size[1]);
  cmp.bgImage = s.bgImage ? { upload: s.bgImage, img: await loadImage(s.bgImage) } : null;
  cmp.layers = await Promise.all(s.layers.map(async (L) => {
    const img = await loadImage(L.upload);
    return { ...L, img, alpha: alphaCanvas(img) };
  }));
  cmp.selected = s.selected;
  ColorPicker.refresh();
  cmpBgControls();
  cmpDraw();
  cmpRenderLayerList();
}

/* ---------- flatten ---------- */
function cmpFlatten() {
  cmpDraw(false);
  return new Promise((resolve) => cmp.canvas.toBlob((blob) => { cmpDraw(); resolve(blob); }, "image/png"));
}

async function cmpSave() {
  const msg = $("#cmp-msg");
  if (!cmp.layers.length && $("#cmp-bg-type").value !== "image") return setMsg(msg, "Add a picture first.", true);
  const btn = $("#cmp-save");
  btn.disabled = true;
  try {
    setMsg(msg, "Flattening and saving…");
    const fd = new FormData();
    fd.append("image", await cmpFlatten(), "compose.png");
    fd.append("recipe", cmpSnapshot());
    const r = await api("/api/compose/save", { method: "POST", form: fd });
    setMsg(msg, `Saved ${r.name} to the gallery.`);
    if (state.galleryKind !== "photo") setGalleryKind("photo");
    state.selected = { rel: r.rel };
    loadGallery();
  } catch (e) { setMsg(msg, e.message, true); }
  finally { btn.disabled = false; }
}

async function cmpDownload() {
  const url = URL.createObjectURL(await cmpFlatten());
  const a = el("a", { href: url, download: `compose_${Date.now()}.png` });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

/* ---------- gallery hooks: add a gallery photo as a layer or as the background ---------- */
ACTIONS["compose-layer"] = (it) => { closeViewer(); return cmpAddFromGallery(it.rel); };
ACTIONS["compose-bg"] = (it) => { closeViewer(); return cmpAddFromGallery(it.rel, { asBackground: true }); };

cmpInit();
