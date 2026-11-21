"use strict";
/* Color picker: a hue/saturation wheel, Hue / Saturation / Brightness sliders, a hex box, and the last
   25 chosen colors along the bottom (kept in this browser). Bind it to a hidden <input>: the picker
   writes the input's value and fires its "input" (while dragging) and "change" (when settled) events,
   so the code that uses the input doesn't know the picker exists. */

const ColorPicker = (() => {
  const RECENT_KEY = "gs-recent-colors";
  const MAX_RECENT = 25;
  const SIZE = 220;  // wheel diameter (CSS px)
  const bound = [];  // {input, button}
  let pop = null, target = null, hsv = { h: 0, s: 0, v: 0 }, startValue = "";

  /* ---------- color math ---------- */
  function hsvToRgb(h, s, v) {
    const f = (n) => { const k = (n + h / 60) % 6; return v - v * s * Math.max(0, Math.min(k, 4 - k, 1)); };
    return [f(5), f(3), f(1)].map((x) => Math.round(x * 255));
  }
  function rgbToHsv(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), d = max - Math.min(r, g, b);
    let h = 0;
    if (d) h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return { h: (h * 60 + 360) % 360, s: max ? d / max : 0, v: max };
  }
  const toHex = ([r, g, b]) => "#" + [r, g, b].map((x) => x.toString(16).padStart(2, "0")).join("");
  function parseHex(text) {
    let t = String(text || "").trim().replace(/^#/, "");
    if (/^[0-9a-f]{3}$/i.test(t)) t = t.split("").map((c) => c + c).join("");
    if (!/^[0-9a-f]{6}$/i.test(t)) return null;
    return [0, 2, 4].map((i) => parseInt(t.slice(i, i + 2), 16));
  }
  const currentHex = () => toHex(hsvToRgb(hsv.h, hsv.s, hsv.v));

  /* ---------- recent colors ---------- */
  function recent() {
    try { return JSON.parse(localStorage.getItem(RECENT_KEY)) || []; } catch { return []; }
  }
  function remember(hex) {
    const list = [hex, ...recent().filter((c) => c !== hex)].slice(0, MAX_RECENT);
    localStorage.setItem(RECENT_KEY, JSON.stringify(list));
    if (pop) renderRecent();
  }

  /* ---------- the popover ---------- */
  function build() {
    pop = el("div", { className: "cp-pop", hidden: true });
    const wheel = el("canvas", { className: "cp-wheel" });
    const dpr = window.devicePixelRatio || 1;
    wheel.width = wheel.height = Math.round(SIZE * dpr);
    wheel.style.width = wheel.style.height = `${SIZE}px`;
    const marker = el("div", { className: "cp-marker" });
    const wheelWrap = el("div", { className: "cp-wheel-wrap" }, wheel, marker);
    const slider = (name, max) => {
      const input = el("input", { type: "range", min: 0, max, step: 1, className: `cp-${name}` });
      const num = el("span", { className: "cp-num" });
      return { input, num, row: el("label", { className: "cp-row" }, el("span", { textContent: name }), input, num) };
    };
    const H = slider("Hue", 360), S = slider("Saturation", 100), V = slider("Brightness", 100);
    const hex = el("input", { type: "text", className: "cp-hex", maxLength: 7, spellcheck: false });
    const preview = el("div", { className: "cp-preview" });
    const done = el("button", { type: "button", className: "primary", textContent: "Done" });
    const recentRow = el("div", { className: "cp-recent" });
    pop.append(wheelWrap, H.row, S.row, V.row,
      el("div", { className: "cp-hexrow" }, preview, hex, done),
      el("div", { className: "cp-recent-label help", textContent: "Recent colors" }), recentRow);
    document.body.append(pop);
    Object.assign(pop, { wheel, marker, H, S, V, hex, preview, recentRow });

    // wheel: angle = hue, distance from the center = saturation
    const pick = (e) => {
      const r = wheel.getBoundingClientRect(), R = r.width / 2;
      const dx = e.clientX - r.left - R, dy = e.clientY - r.top - R;
      hsv.h = (Math.atan2(dy, dx) * 180 / Math.PI + 360) % 360;
      hsv.s = Math.min(1, Math.hypot(dx, dy) / R);
      if (hsv.v < 0.05) hsv.v = 1;  // picking a hue on a black wheel should show the hue
      update("input");
    };
    wheel.addEventListener("pointerdown", (e) => { wheel.setPointerCapture(e.pointerId); pick(e); });
    wheel.addEventListener("pointermove", (e) => { if (wheel.hasPointerCapture(e.pointerId)) pick(e); });
    wheel.addEventListener("pointerup", () => update("change"));
    H.input.addEventListener("input", () => { hsv.h = Number(H.input.value); update("input"); });
    S.input.addEventListener("input", () => { hsv.s = Number(S.input.value) / 100; update("input"); });
    V.input.addEventListener("input", () => { hsv.v = Number(V.input.value) / 100; update("input"); });
    for (const s of [H, S, V]) s.input.addEventListener("change", () => update("change"));
    hex.addEventListener("change", () => {
      const rgb = parseHex(hex.value);
      if (rgb) { hsv = rgbToHsv(...rgb); update("change"); } else hex.value = currentHex();
    });
    done.addEventListener("click", close);
    document.addEventListener("pointerdown", (e) => {
      if (!pop.hidden && !pop.contains(e.target) && !bound.some((b) => b.button === e.target)) close();
    });
    document.addEventListener("keydown", (e) => {
      if (pop.hidden) return;
      if (e.key === "Escape") { setValue(startValue, "change"); close(); }  // Escape puts the old color back
      if (e.key === "Enter" && document.activeElement !== hex) close();
    });
  }

  function drawWheel() {
    const c = pop.wheel, ctx = c.getContext("2d"), n = c.width, R = n / 2;
    const img = ctx.createImageData(n, n);
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        const dx = x - R + 0.5, dy = y - R + 0.5, d = Math.hypot(dx, dy) / R;
        if (d > 1) continue;
        const [r, g, b] = hsvToRgb((Math.atan2(dy, dx) * 180 / Math.PI + 360) % 360, d, hsv.v);
        const i = (y * n + x) * 4;
        img.data[i] = r; img.data[i + 1] = g; img.data[i + 2] = b;
        img.data[i + 3] = d > 0.985 ? Math.round((1 - d) / 0.015 * 255) : 255;  // soft edge
      }
    }
    ctx.putImageData(img, 0, 0);
    pop.drawnV = hsv.v;
  }

  function renderRecent() {
    const list = recent();
    pop.recentRow.replaceChildren(...(list.length ? list.map((c) => {
      const b = el("button", { type: "button", className: "cp-chip", title: c });
      b.style.background = c;
      b.addEventListener("click", () => { hsv = rgbToHsv(...parseHex(c)); update("change"); });
      return b;
    }) : [el("span", { className: "help", textContent: "Colors you choose show up here." })]));
  }

  // Sync every control to hsv, write the bound input and fire its event.
  function update(kind) {
    if (pop.drawnV !== hsv.v) drawWheel();
    const hex = currentHex(), R = SIZE / 2;
    const a = hsv.h * Math.PI / 180;
    pop.marker.style.left = `${R + Math.cos(a) * hsv.s * R}px`;
    pop.marker.style.top = `${R + Math.sin(a) * hsv.s * R}px`;
    pop.marker.style.background = hex;
    pop.H.input.value = Math.round(hsv.h); pop.H.num.textContent = `${Math.round(hsv.h)}°`;
    pop.S.input.value = Math.round(hsv.s * 100); pop.S.num.textContent = `${Math.round(hsv.s * 100)}%`;
    pop.V.input.value = Math.round(hsv.v * 100); pop.V.num.textContent = `${Math.round(hsv.v * 100)}%`;
    const grey = toHex(hsvToRgb(hsv.h, 0, hsv.v));
    pop.S.input.style.background = `linear-gradient(90deg, ${grey}, ${toHex(hsvToRgb(hsv.h, 1, hsv.v))})`;
    pop.V.input.style.background = `linear-gradient(90deg, #000, ${toHex(hsvToRgb(hsv.h, hsv.s, 1))})`;
    pop.H.input.style.background = "linear-gradient(90deg, #f00, #ff0, #0f0, #0ff, #00f, #f0f, #f00)";
    pop.preview.style.background = hex;
    if (document.activeElement !== pop.hex) pop.hex.value = hex;
    if (kind) setValue(hex, kind);
  }

  function setValue(hex, kind) {
    if (!target) return;
    target.input.value = hex;
    target.button.style.background = hex;
    target.input.dispatchEvent(new Event(kind === "change" ? "change" : "input", { bubbles: true }));
    if (kind === "change") target.input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function open(b) {
    if (!pop) build();
    target = b;
    startValue = b.input.value;
    hsv = rgbToHsv(...(parseHex(b.input.value) || [0, 0, 0]));
    pop.hidden = false;
    renderRecent();
    update(null);
    const r = b.button.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
    pop.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, r.left + window.scrollX))}px`;
    pop.style.top = `${r.bottom + window.scrollY + h + 8 > window.scrollY + window.innerHeight
      ? Math.max(window.scrollY + 8, r.top + window.scrollY - h - 6) : r.bottom + window.scrollY + 6}px`;
  }

  function close() {
    if (!pop || pop.hidden) return;
    pop.hidden = true;
    if (target && target.input.value !== startValue) remember(target.input.value);  // every chosen color is kept
    target = null;
  }

  return {
    /* Turn a hidden <input> into a color button that opens the picker. */
    bind(input, label) {
      const button = el("button", { type: "button", className: "cp-button", title: `${label}: click to pick a color` });
      button.style.background = input.value;
      input.after(button);
      const b = { input, button };
      bound.push(b);
      button.addEventListener("click", () => (pop && !pop.hidden && target === b ? close() : open(b)));
      return button;
    },
    /* Repaint the buttons after code changed an input's value directly (swatches, undo). */
    refresh() { for (const b of bound) b.button.style.background = b.input.value; },
    remember,
  };
})();
