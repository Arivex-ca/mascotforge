/* mascot-avatar.js
 * MascotForge V2 widget: zero-dependency Web Component.
 * <mascot-avatar manifest="manifest.json"></mascot-avatar>
 * Plays one looping video clip per mascot state.
 *
 * States (exactly the 6 from the V2 scoping, each one is an AI cost):
 *   idle, talking, thinking, clicked, error, sleeping
 *
 * Attributes:
 *   manifest     URL of the manifest.json file
 *   sleep-after  seconds of inactivity before auto sleep (default 60, 0 disables)
 *   parallax     "true" / "false" (default true), disabled when prefers-reduced-motion
 *
 * DOM events dispatched:
 *   statechange  detail { from, to }
 *   sleep
 *   wake
 *
 * Public methods:
 *   play(state)  returns a Promise
 *   wake()
 *   getState()
 */

const STATES = ["idle", "talking", "thinking", "clicked", "error", "sleeping"];
const LOOP_STATES = new Set(["idle", "talking", "thinking", "sleeping"]);
const DEFAULT_SLEEP_AFTER = 60;

class MascotAvatar extends HTMLElement {
  static get observedAttributes() {
    return ["manifest", "sleep-after", "parallax"];
  }

  constructor() {
    super();
    this._state = "idle";
    this._clips = new Map(); // state -> HTMLVideoElement
    this._manifestUrl = null;
    this._manifestBase = null;
    this._sleepTimer = null;
    this._sleepPending = false;
    this._returnTo = "idle";
    this._ready = null;
    this._fallbackShown = false;
    this._sleepAfter = DEFAULT_SLEEP_AFTER;
    this._parallaxOn = true;
    this._reducesMotion = false;

    const shadow = this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = [
      ":host { display: inline-block; position: relative; }",
      ".stage { position: relative; width: 100%; height: 100%; overflow: hidden; }",
      ".stage video { position: absolute; inset: 0; width: 100%; height: 100%;",
      "  object-fit: contain; display: none; }",
      ".stage video.active { display: block; }",
      ".fallback { position: absolute; inset: 0; display: none;",
      "  align-items: center; justify-content: center;",
      "  font: 14px/1.4 system-ui, sans-serif; color: #888;",
      "  background: #111; border-radius: 8px; text-align: center; padding: 12px; }",
      ".fallback.visible { display: flex; }",
    ].join("\n");
    shadow.appendChild(style);

    this._stage = document.createElement("div");
    this._stage.className = "stage";
    shadow.appendChild(this._stage);

    this._fallback = document.createElement("div");
    this._fallback.className = "fallback";
    this._fallback.textContent = "Avatar clip not available";
    shadow.appendChild(this._fallback);

    this._onClick = () => this.play("clicked");
    this._onPointerMove = (ev) => this._applyParallax(ev);
    this._onActivity = () => this._handleActivity();
  }

  connectedCallback() {
    this._reducesMotion =
      typeof matchMedia === "function" &&
      matchMedia("(prefers-reduced-motion: reduce)").matches;
    this._readAttributes();
    this._ready = this._loadManifest();

    this.addEventListener("click", this._onClick);
    window.addEventListener("pointermove", this._onPointerMove, {
      passive: true,
    });
    window.addEventListener("pointerdown", this._onActivity, { passive: true });
    window.addEventListener("wheel", this._onActivity, { passive: true });
    window.addEventListener("keydown", this._onActivity);
  }

  disconnectedCallback() {
    this.removeEventListener("click", this._onClick);
    window.removeEventListener("pointermove", this._onPointerMove);
    window.removeEventListener("pointerdown", this._onActivity);
    window.removeEventListener("wheel", this._onActivity);
    window.removeEventListener("keydown", this._onActivity);
    this._clearSleepTimer();
  }

  attributeChangedCallback(name, oldValue, newValue) {
    if (oldValue === newValue) return;
    this._readAttributes();
    if (name === "manifest" && this.isConnected) {
      this._ready = this._loadManifest();
    } else if (name === "sleep-after" && this.isConnected) {
      this._resetSleepTimer();
    }
  }

  /* ---------------- public API ---------------- */

  getState() {
    return this._state;
  }

  ready() {
    return this._ready || Promise.resolve();
  }

  play(state) {
    if (!STATES.includes(state)) {
      console.warn("[mascot-avatar] unknown state ignored:", state);
      return Promise.resolve();
    }
    return this._ready.then(() => this._setState(state));
  }

  wake() {
    if (this._state !== "sleeping") return Promise.resolve();
    this._setState("idle");
    this.dispatchEvent(new CustomEvent("wake"));
    return Promise.resolve();
  }

  /* ---------------- internals ---------------- */

  _readAttributes() {
    const manifest = this.getAttribute("manifest");
    this._manifestAttr = manifest || null;
    const sleepAfter = this.getAttribute("sleep-after");
    if (sleepAfter !== null) {
      const n = Number(sleepAfter);
      this._sleepAfter = Number.isFinite(n) && n >= 0 ? n : DEFAULT_SLEEP_AFTER;
    } else {
      this._sleepAfter = DEFAULT_SLEEP_AFTER;
    }
    const parallax = this.getAttribute("parallax");
    this._parallaxOn = parallax === null || parallax !== "false";
  }

  _loadManifest() {
    if (!this._manifestAttr) {
      console.warn("[mascot-avatar] missing manifest attribute");
      this._showFallback();
      return Promise.resolve();
    }
    // attributeChangedCallback can fire during upgrade while the element is
    // already connected, so connectedCallback may request the same manifest
    // twice. Load each manifest URL at most once; concurrent requests for the
    // same URL share the in-flight promise.
    const url = new URL(this._manifestAttr, document.baseURI).href;
    if (url === this._loadedManifestUrl && this._ready) return this._ready;
    this._loadedManifestUrl = url;
    this._ready = this._fetchAndBuild(url);
    return this._ready;
  }

  async _fetchAndBuild(url) {
    try {
      this._manifestUrl = url;
      this._manifestBase = new URL(".", url).href;
      const res = await fetch(url);
      if (!res.ok) throw new Error("HTTP " + res.status);
      const manifest = await res.json();
      this._buildClips(manifest);
      const initial = manifest.default_state || "idle";
      this._setState(STATES.includes(initial) ? initial : "idle");
      this._resetSleepTimer();
    } catch (err) {
      this._loadedManifestUrl = null; // allow a retry on next trigger
      console.warn("[mascot-avatar] manifest load failed:", err.message || err);
      this._showFallback();
    }
  }

  _buildClips(manifest) {
    // Clear any previously built clips (defensive: never duplicate).
    for (const video of this._clips.values()) video.remove();
    this._clips.clear();
    const states = (manifest && manifest.states) || {};
    for (const state of STATES) {
      const rel = states[state];
      if (!rel) {
        if (state !== "idle") {
          console.warn("[mascot-avatar] missing clip for state:", state);
        }
        continue;
      }
      const url = new URL(rel, this._manifestBase).href;
      const video = document.createElement("video");
      video.muted = true;
      video.playsInline = true;
      video.preload = "auto";
      video.loop = LOOP_STATES.has(state);
      video.setAttribute("aria-hidden", "true");
      video.addEventListener("error", () => this._onClipError(state, video));
      video.addEventListener("ended", () => this._onClipEnded(state));
      video.src = url;
      video.load();
      this._clips.set(state, video);
      this._stage.appendChild(video);
    }
  }

  _onClipError(state, video) {
    console.warn("[mascot-avatar] clip failed to load:", state, video.src);
    this._clips.delete(state);
    video.remove();
    if (this._state === state) {
      // Never show an empty stage: fall back to idle.
      this._setState("idle");
    }
    if (this._clips.size === 0) {
      this._showFallback();
    }
  }

  _onClipEnded(state) {
    // One-shot states (clicked, error) return to the previous state.
    if (!LOOP_STATES.has(state) && this._state === state) {
      this._setState(this._returnTo || "idle");
      // A one-shot clip that just played counts as widget activity: restart
      // the inactivity window (also settles a sleep that was deferred while
      // the clip was playing, see _resetSleepTimer).
      this._resetSleepTimer();
    }
  }

  _setState(next) {
    const from = this._state;
    if (from === next && !LOOP_STATES.has(next)) return;

    // Pause and hide the current clip.
    const current = this._clips.get(from);
    if (current) {
      current.classList.remove("active");
      current.pause();
    }

    if (next === "clicked") {
      // clicked is a one-shot: remember where to go back.
      this._returnTo = LOOP_STATES.has(from) ? from : "idle";
    }

    this._state = next;
    const video = this._clips.get(next);
    if (!video) {
      console.warn("[mascot-avatar] no clip for state, staying on idle:", next);
      this._state = "idle";
      const idleVideo = this._clips.get("idle");
      if (idleVideo) {
        idleVideo.classList.add("active");
        this._playVideo(idleVideo);
      } else {
        this._showFallback();
      }
      return;
    }

    this._fallbackShown = false;
    this._fallback.classList.remove("visible");
    video.classList.add("active");
    this._playVideo(video);

    if (from !== next) {
      this.dispatchEvent(
        new CustomEvent("statechange", { detail: { from, to: next } })
      );
    }
  }

  _playVideo(video) {
    const p = video.play();
    if (p && typeof p.catch === "function") {
      p.catch((err) => {
        console.warn("[mascot-avatar] clip play failed:", err && err.message);
      });
    }
  }

  _showFallback() {
    this._fallbackShown = true;
    this._fallback.classList.add("visible");
  }

  /* -------- sleep / wake / parallax -------- */

  _clearSleepTimer() {
    if (this._sleepTimer !== null) {
      clearTimeout(this._sleepTimer);
      this._sleepTimer = null;
    }
  }

  _resetSleepTimer() {
    this._clearSleepTimer();
    this._sleepPending = false;
    if (this._sleepAfter > 0 && this._state !== "sleeping") {
      this._sleepTimer = setTimeout(
        () => {
          // Never fall asleep in the middle of a one-shot clip
          // (clicked, error): defer sleep until the clip ends, otherwise the
          // timer would swallow the clip's return to its previous state.
          if (!LOOP_STATES.has(this._state)) {
            this._sleepPending = true;
            this._sleepTimer = null;
            return;
          }
          this._setState("sleeping");
          this.dispatchEvent(new CustomEvent("sleep"));
        },
        this._sleepAfter * 1000
      );
    }
  }

  _handleActivity() {
    if (this._state === "sleeping") {
      this.wake();
    }
    this._resetSleepTimer();
  }

  _applyParallax(ev) {
    if (!this._parallaxOn || this._reducesMotion) {
      if (this._stage.style.transform) this._stage.style.transform = "";
      return;
    }
    const rect = this.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const dx = Math.max(-1, Math.min(1, (ev.clientX - cx) / window.innerWidth));
    const dy = Math.max(-1, Math.min(1, (ev.clientY - cy) / window.innerHeight));
    const range = 6; // +/- 6 px, subtle
    this._stage.style.transform =
      "translate(" + (dx * range).toFixed(1) + "px," + (dy * range).toFixed(1) + "px)";
  }
}

customElements.define("mascot-avatar", MascotAvatar);
