/* mascot-avatar.js
 * MascotForge widget: zero-dependency Web Component.
 * <mascot-avatar manifest="manifest.json"></mascot-avatar>
 * Plays one video clip per mascot state. The states come from the manifest:
 * any names, any number.
 *
 * Manifest v2: { "default_state": "idle", "alpha": "stacked" | "none",
 *   "states": { "idle": { "src": "videos/idle.mp4", "loop": true }, ... } }
 * Manifest v1 (still read): "states": { "idle": "videos/idle.mp4", ... }
 *
 * alpha "stacked": each clip holds the color on top and the alpha mask below.
 * The widget recombines them in WebGL, so the mascot has a transparent
 * background in every browser, Safari and iOS included.
 *
 * Switching: by default a new state starts when the current clip ends. All
 * clips start and end on the same pose, so the switch shows no jump.
 * play(state, { immediate: true }) or switch="immediate" switches at once.
 *
 * Attributes:
 *   manifest     URL of the manifest.json file
 *   label        accessible name (default: manifest name)
 *   click-state  state played on click (default "clicked" if the manifest has it)
 *   sleep-state  state played after inactivity (default "sleeping" if present)
 *   sleep-after  seconds of inactivity before sleep (default 60, 0 disables)
 *   switch       "loop-end" (default) or "immediate"
 *   parallax     "true" / "false" (default true), off with prefers-reduced-motion
 *
 * DOM events: statechange { from, to }, sleep, wake
 * Public methods: play(state, { immediate }) -> Promise, wake(), getState(),
 *   ready() -> Promise, states (array of state names)
 */

const LEGACY_LOOP_STATES = new Set(["idle", "talking", "thinking", "sleeping"]);
const DEFAULT_SLEEP_AFTER = 60;
const ACTIVITY_THROTTLE_MS = 500;

const VERTEX_SHADER = `
attribute vec2 p;
varying vec2 uv;
void main() {
  uv = vec2((p.x + 1.0) * 0.5, (1.0 - p.y) * 0.5);
  gl_Position = vec4(p, 0.0, 1.0);
}`;

// Top half: premultiplied color. Bottom half: alpha mask as gray.
const FRAGMENT_SHADER = `
precision mediump float;
varying vec2 uv;
uniform sampler2D frame;
void main() {
  vec3 color = texture2D(frame, vec2(uv.x, uv.y * 0.5)).rgb;
  float alpha = texture2D(frame, vec2(uv.x, 0.5 + uv.y * 0.5)).r;
  alpha *= step(0.02, alpha); // compression noise on the background
  gl_FragColor = vec4(min(color, vec3(alpha)), alpha);
}`;

class StackedAlphaRenderer {
  constructor(canvas) {
    const gl = canvas.getContext("webgl", { premultipliedAlpha: true, alpha: true });
    if (!gl) throw new Error("WebGL unavailable");
    const program = gl.createProgram();
    for (const [type, source] of [
      [gl.VERTEX_SHADER, VERTEX_SHADER],
      [gl.FRAGMENT_SHADER, FRAGMENT_SHADER],
    ]) {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        throw new Error(gl.getShaderInfoLog(shader) || "shader error");
      }
      gl.attachShader(program, shader);
    }
    gl.linkProgram(program);
    gl.useProgram(program);

    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, "p");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

    gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.clearColor(0, 0, 0, 0);

    this.gl = gl;
    this.canvas = canvas;
  }

  draw(video) {
    if (video.readyState < 2 || !video.videoWidth) return;
    const gl = this.gl;
    const width = video.videoWidth;
    const height = Math.floor(video.videoHeight / 2);
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
      gl.viewport(0, 0, width, height);
    }
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, video);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }
}

class MascotAvatar extends HTMLElement {
  static get observedAttributes() {
    return ["manifest", "sleep-after", "label"];
  }

  constructor() {
    super();
    this._state = null;
    this._clips = new Map(); // state -> { video, loop }
    this._defaultState = null;
    this._returnTo = null;
    this._pending = null; // { state, resolvers }
    this._sleepTimer = null;
    this._lastActivity = 0;
    this._renderer = null;
    this._raf = null;
    this._manifest = null;
    this._loadedManifestUrl = null;
    this._ready = null;

    const shadow = this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = [
      ":host { display: inline-block; position: relative; -webkit-tap-highlight-color: transparent; }",
      ":host([role=button]) { cursor: pointer; }",
      ":host(:focus-visible) { outline: 2px solid #8b5cf6; outline-offset: 4px; border-radius: 12px; }",
      ".stage { position: relative; width: 100%; height: 100%; overflow: hidden;",
      "  transition: transform 120ms ease-out; }",
      ":host([role=button]:active) .stage, .stage.pressed { transform: scale(0.97); }",
      ".stage video, .stage canvas { position: absolute; inset: 0; width: 100%; height: 100%;",
      "  object-fit: contain; display: none; }",
      ".stage canvas.on, .stage video.active { display: block; }",
      ".stage video.feed { display: block; width: 1px; height: 1px; opacity: 0; pointer-events: none; }",
      ".stage.crop video.active { height: 200%; object-fit: fill; }",
      ".fallback { position: absolute; inset: 0; display: none; align-items: center;",
      "  justify-content: center; font: 13px/1.4 system-ui, sans-serif; color: #888;",
      "  text-align: center; padding: 12px; }",
      ".fallback.visible { display: flex; }",
    ].join("\n");
    shadow.appendChild(style);

    this._stage = document.createElement("div");
    this._stage.className = "stage";
    shadow.appendChild(this._stage);

    this._canvas = document.createElement("canvas");
    this._stage.appendChild(this._canvas);

    this._fallback = document.createElement("div");
    this._fallback.className = "fallback";
    this._fallback.textContent = "Mascot unavailable";
    shadow.appendChild(this._fallback);

    this._onClick = () => this._handleClick();
    this._onKeyDown = (ev) => {
      if (this.getAttribute("role") === "button" && (ev.key === "Enter" || ev.key === " ")) {
        ev.preventDefault();
        this._stage.classList.add("pressed");
        setTimeout(() => this._stage.classList.remove("pressed"), 120);
        this._handleClick();
      }
    };
    this._onPointerMove = (ev) => {
      this._applyParallax(ev);
      this._handleActivity(true);
    };
    this._onActivity = () => this._handleActivity(false);
    this._tick = () => this._renderFrame();
  }

  connectedCallback() {
    this._reducesMotion =
      typeof matchMedia === "function" &&
      matchMedia("(prefers-reduced-motion: reduce)").matches;
    this._ready = this._loadManifest();

    this.addEventListener("click", this._onClick);
    this.addEventListener("keydown", this._onKeyDown);
    window.addEventListener("pointermove", this._onPointerMove, { passive: true });
    window.addEventListener("pointerdown", this._onActivity, { passive: true });
    window.addEventListener("wheel", this._onActivity, { passive: true });
    window.addEventListener("touchstart", this._onActivity, { passive: true });
    window.addEventListener("keydown", this._onActivity);
  }

  disconnectedCallback() {
    this.removeEventListener("click", this._onClick);
    this.removeEventListener("keydown", this._onKeyDown);
    window.removeEventListener("pointermove", this._onPointerMove);
    window.removeEventListener("pointerdown", this._onActivity);
    window.removeEventListener("wheel", this._onActivity);
    window.removeEventListener("touchstart", this._onActivity);
    window.removeEventListener("keydown", this._onActivity);
    this._clearSleepTimer();
    if (this._raf !== null) cancelAnimationFrame(this._raf);
    this._raf = null;
  }

  attributeChangedCallback(name, oldValue, newValue) {
    if (!this.isConnected || oldValue === newValue) return;
    if (name === "manifest") this._ready = this._loadManifest();
    else if (name === "sleep-after") this._resetSleepTimer();
    else if (name === "label") this._applyRole();
  }

  /* ---------------- public API ---------------- */

  get states() {
    return Array.from(this._clips.keys());
  }

  getState() {
    return this._state;
  }

  ready() {
    return this._ready || Promise.resolve();
  }

  play(state, options) {
    return this.ready().then(() => {
      if (!this._clips.has(state)) {
        console.warn("[mascot-avatar] unknown state ignored:", state);
        return;
      }
      const immediate =
        (options && options.immediate) || this.getAttribute("switch") === "immediate";
      return this._request(state, immediate);
    });
  }

  wake() {
    if (this._state !== this._sleepState()) return Promise.resolve();
    const done = this._request(this._defaultState, true);
    this.dispatchEvent(new CustomEvent("wake"));
    this._resetSleepTimer();
    return done;
  }

  /* ---------------- manifest ---------------- */

  _loadManifest() {
    const attr = this.getAttribute("manifest");
    if (!attr) {
      console.warn("[mascot-avatar] missing manifest attribute");
      this._fallback.classList.add("visible");
      return Promise.resolve();
    }
    const url = new URL(attr, document.baseURI).href;
    if (url === this._loadedManifestUrl && this._ready) return this._ready;
    this._loadedManifestUrl = url;
    return this._fetchAndBuild(url);
  }

  async _fetchAndBuild(url) {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error("HTTP " + res.status);
      const manifest = await res.json();
      this._manifest = manifest;
      this._build(manifest, new URL(".", url).href);
      this._applyRole();
      const first = this._clips.has(manifest.default_state)
        ? manifest.default_state
        : this._firstLoopState();
      this._defaultState = first;
      if (first) this._show(first);
      this._resetSleepTimer();
    } catch (err) {
      this._loadedManifestUrl = null; // allow a retry on next trigger
      console.warn("[mascot-avatar] manifest load failed:", err.message || err);
      this._fallback.classList.add("visible");
    }
  }

  _build(manifest, base) {
    for (const { video } of this._clips.values()) video.remove();
    this._clips.clear();
    this._state = null;
    this._pending = null;

    this._renderer = null;
    if (manifest.alpha === "stacked") {
      try {
        this._renderer = new StackedAlphaRenderer(this._canvas);
      } catch (err) {
        console.warn("[mascot-avatar] WebGL off, transparency disabled:", err.message);
      }
    }
    this._canvas.classList.toggle("on", !!this._renderer);
    this._stage.classList.toggle("crop", manifest.alpha === "stacked" && !this._renderer);

    const states = (manifest && manifest.states) || {};
    for (const [state, entry] of Object.entries(states)) {
      const src = typeof entry === "string" ? entry : entry && entry.src;
      if (!src) continue;
      const loop =
        typeof entry === "object" && "loop" in entry ? !!entry.loop : LEGACY_LOOP_STATES.has(state);
      const video = document.createElement("video");
      video.muted = true;
      video.playsInline = true;
      video.setAttribute("playsinline", "");
      video.preload = "auto";
      video.loop = false; // looping is handled on "ended" to switch on clip boundaries
      video.setAttribute("aria-hidden", "true");
      if (this._renderer) {
        video.crossOrigin = "anonymous"; // WebGL needs CORS for clips on another origin
        video.className = "feed";
      }
      video.addEventListener("ended", () => this._onClipEnded(state));
      video.addEventListener("error", () => this._onClipError(state));
      video.src = new URL(src, base).href;
      this._clips.set(state, { video, loop });
      this._stage.appendChild(video);
    }
    if (this._clips.size === 0) this._fallback.classList.add("visible");
  }

  _firstLoopState() {
    for (const [state, clip] of this._clips) if (clip.loop) return state;
    return this._clips.keys().next().value || null;
  }

  _clickState() {
    const attr = this.getAttribute("click-state");
    if (attr !== null) return this._clips.has(attr) ? attr : null;
    return this._clips.has("clicked") ? "clicked" : null;
  }

  _sleepState() {
    const attr = this.getAttribute("sleep-state");
    if (attr !== null) return this._clips.has(attr) ? attr : null;
    return this._clips.has("sleeping") ? "sleeping" : null;
  }

  _applyRole() {
    const name =
      this.getAttribute("label") || (this._manifest && this._manifest.name) || "Mascot";
    if (this._clickState()) {
      this.setAttribute("role", "button");
      if (!this.hasAttribute("tabindex")) this.setAttribute("tabindex", "0");
    } else {
      this.setAttribute("role", "img");
    }
    this.setAttribute("aria-label", name);
  }

  /* ---------------- state machine ---------------- */

  _request(state, immediate) {
    if (state === this._state && !this._pending) return Promise.resolve();
    const current = this._clips.get(this._state);
    const playing = current && !current.video.paused && !current.video.ended;
    if (immediate || !playing) {
      this._show(state);
      return Promise.resolve();
    }
    // Wait for the current clip to reach its end (the shared pose).
    const resolvers = this._pending ? this._pending.resolvers : [];
    return new Promise((resolve) => {
      resolvers.push(resolve);
      this._pending = { state, resolvers };
    });
  }

  _show(next) {
    const from = this._state;
    const target = this._clips.get(next);
    if (!target) return;
    const leaving = this._clips.get(from);
    if (!target.loop) {
      // A one-shot returns to the loop state it interrupted.
      this._returnTo = leaving && leaving.loop ? from : this._returnTo || this._defaultState;
    }
    if (leaving && leaving !== target) {
      leaving.video.classList.remove("active");
      leaving.video.pause();
    }
    this._state = next;
    target.video.currentTime = 0;
    target.video.classList.add("active");
    this._fallback.classList.remove("visible");
    this._playVideo(target.video);
    this._startRendering();
    if (from !== next) {
      this.dispatchEvent(new CustomEvent("statechange", { detail: { from, to: next } }));
    }
  }

  _settlePending() {
    const pending = this._pending;
    this._pending = null;
    this._show(pending.state);
    for (const resolve of pending.resolvers) resolve();
  }

  _onClipEnded(state) {
    if (state !== this._state) return;
    const clip = this._clips.get(state);
    if (this._pending) {
      this._settlePending();
    } else if (clip.loop) {
      clip.video.currentTime = 0;
      this._playVideo(clip.video);
    } else {
      this._show(this._returnTo && this._clips.has(this._returnTo) ? this._returnTo : this._defaultState);
      this._resetSleepTimer();
    }
  }

  _onClipError(state) {
    const clip = this._clips.get(state);
    console.warn("[mascot-avatar] clip failed to load:", state, clip && clip.video.src);
    if (clip) clip.video.remove();
    this._clips.delete(state);
    if (this._state === state) {
      this._state = null;
      const fallbackState = this._clips.has(this._defaultState) ? this._defaultState : this._firstLoopState();
      if (fallbackState) this._show(fallbackState);
    }
    if (this._clips.size === 0) this._fallback.classList.add("visible");
  }

  _playVideo(video) {
    const p = video.play();
    if (p && typeof p.catch === "function") {
      p.catch((err) => console.warn("[mascot-avatar] clip play failed:", err && err.message));
    }
  }

  _startRendering() {
    if (!this._renderer || this._raf !== null) return;
    this._raf = requestAnimationFrame(this._tick);
  }

  _renderFrame() {
    this._raf = null;
    if (!this._renderer || !this.isConnected) return;
    const clip = this._clips.get(this._state);
    if (clip) this._renderer.draw(clip.video);
    this._raf = requestAnimationFrame(this._tick);
  }

  /* -------- click / sleep / wake / parallax -------- */

  _handleClick() {
    const state = this._clickState();
    if (state) this.play(state);
  }

  _clearSleepTimer() {
    if (this._sleepTimer !== null) {
      clearTimeout(this._sleepTimer);
      this._sleepTimer = null;
    }
  }

  _sleepAfter() {
    const raw = this.getAttribute("sleep-after");
    if (raw === null) return DEFAULT_SLEEP_AFTER;
    const n = Number(raw);
    return Number.isFinite(n) && n >= 0 ? n : DEFAULT_SLEEP_AFTER;
  }

  _resetSleepTimer() {
    this._clearSleepTimer();
    const sleepState = this._sleepState();
    const delay = this._sleepAfter();
    if (!sleepState || delay <= 0 || this._state === sleepState) return;
    this._sleepTimer = setTimeout(() => {
      this._sleepTimer = null;
      this.play(sleepState).then(() => {
        if (this._state === sleepState) this.dispatchEvent(new CustomEvent("sleep"));
      });
    }, delay * 1000);
  }

  _handleActivity(throttled) {
    const now = Date.now();
    if (throttled && now - this._lastActivity < ACTIVITY_THROTTLE_MS) return;
    this._lastActivity = now;
    if (this._state && this._state === this._sleepState()) this.wake();
    else this._resetSleepTimer();
  }

  _applyParallax(ev) {
    if (this.getAttribute("parallax") === "false" || this._reducesMotion) {
      if (this._stage.style.translate) this._stage.style.translate = "";
      return;
    }
    const rect = this.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const dx = Math.max(-1, Math.min(1, (ev.clientX - rect.left - rect.width / 2) / window.innerWidth));
    const dy = Math.max(-1, Math.min(1, (ev.clientY - rect.top - rect.height / 2) / window.innerHeight));
    const range = 6; // +/- 6 px, subtle
    this._stage.style.translate = (dx * range).toFixed(1) + "px " + (dy * range).toFixed(1) + "px";
  }
}

if (!customElements.get("mascot-avatar")) {
  customElements.define("mascot-avatar", MascotAvatar);
}
