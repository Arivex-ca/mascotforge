(function () {
  "use strict";

  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));

  const PALETTE = {
    milk: "#F2ECE4",
    peach: "#FFB49C",
    butter: "#FFD873",
    matcha: "#B3D69A",
    mint: "#97E2CF",
    sky: "#9CCBFF",
    lilac: "#C6B4FF",
    bubblegum: "#FFA3C8",
    tangerine: "#FF9159",
    cocoa: "#9A6A52",
    ink: "#232228"
  };

  const SERIES = {
    blob: {
      label: "Shape",
      shapes: ["mochi", "bean", "pebble", "squircle", "pill", "drop", "kitty", "cloud"],
      materials: ["matte", "soft", "jelly", "glass", "clay", "velvet"]
    },
    animal: {
      label: "Animal",
      shapes: ["bunny", "cat", "dog", "frog", "hamster", "bear", "panda", "chick"],
      materials: ["fluffy", "knit", "felt"]
    }
  };

  const BUILTIN_STATES = ["idle", "listening", "thinking", "talking", "working", "happy", "done", "error"];
  const CUSTOM_STATES = ["sleeping", "waiting-for-approval"];
  const GALLERY_STATES = ["idle", "listening", "thinking", "working", "talking", "done", "error"];
  const STATE_CAPTIONS = {
    idle: "Idle breathing. Choose a state or run the agent loop.",
    listening: "Listening. Soft rings pull inward while the agent takes input.",
    thinking: "Thinking. The eyes look up and thought dots rise.",
    talking: "Talking. A syllable rhythm pulses without adding a mouth.",
    working: "Working. Scanning eyes and a busy orbit show active progress.",
    happy: "Happy. A quick hop and sparkles reward the interaction.",
    done: "Done. A green check confirms the task finished.",
    error: "Error. A shake and red badge make failure visible.",
    sleeping: "Sleeping. Closed eyes and slow breathing show a quiet agent.",
    "waiting-for-approval": "Waiting for approval. The agent pauses with a focused gaze."
  };

  const ACCESSORY_LABELS = {
    beret: "Beret",
    glasses: "Glasses",
    sunglasses: "Sunglasses",
    crown: "Crown",
    headphones: "Headphones",
    bow: "Bow",
    scarf: "Scarf",
    antenna: "Antenna"
  };

  const BUILTIN_ACCESSORIES = ["beret", "glasses", "sunglasses"];
  const CUSTOM_ACCESSORIES = ["crown", "headphones", "bow", "scarf", "antenna"];

  const ACCESSORY_DEFS = {
    crown: {
      anchor: "crown",
      parts: [
        { shape: "cylinder", size: [0.78, 0.15], at: [0, 0.04, 0], material: "metal", color: "#E8B23A" },
        { shape: "cone", size: [0.15, 0.32], at: [0.17, 0.21, 0], repeat: 5, material: "metal", color: "#FFD873" }
      ]
    },
    headphones: {
      anchor: "eyes",
      parts: [
        { shape: "torus", size: [1.9, 0.1], at: [0, 0.22, -0.08], arc: 180, material: "glossy-plastic", color: "#6E55C8" },
        { shape: "capsule", size: [0.3, 0.46], at: [1.75, 0, -0.02], repeat: 2, material: "glossy-plastic", color: "#6E55C8" }
      ]
    },
    bow: {
      anchor: "neck",
      parts: [
        { shape: "rounded-box", size: [0.34, 0.22, 0.12, 0.08], at: [-0.17, 0, 0.03], rotate: [0, 0, 24], material: "felt", color: "#E5534B" },
        { shape: "rounded-box", size: [0.34, 0.22, 0.12, 0.08], at: [0.17, 0, 0.03], rotate: [0, 0, -24], material: "felt", color: "#E5534B" },
        { shape: "sphere", size: [0.17], at: [0, 0, 0.08], material: "metal", color: "#F5A3B7" }
      ],
      svg: function (ctx) {
        ctx.el("path", { d: "M0 0C-18-17-38-13-39 2C-38 17-18 18 0 4C18 18 38 17 39 2C38-13 18-17 0 0Z", fill: "#E5534B" });
        ctx.el("circle", { r: "8", fill: "#F5A3B7", stroke: "#fff", "stroke-width": "2" });
      }
    },
    scarf: {
      anchor: "neck",
      parts: [
        { shape: "torus", size: [1.18, 0.16], at: [0, -0.14, -0.62], rotate: [90, 0, 0], material: "knit", color: "#AD94E6" },
        { shape: "capsule", size: [0.16, 0.4], at: [0.25, -0.13, 0.06], rotate: [0, 0, -12], material: "knit", color: "#AD94E6" }
      ]
    },
    antenna: {
      anchor: "crown",
      parts: [
        { shape: "capsule", size: [0.08, 0.46], at: [0, 0.25, 0], material: "metal", color: "#6FA8E8" },
        { shape: "sphere", size: [0.2], at: [0, 0.53, 0], material: "glass", color: "#9CCBFF" }
      ]
    }
  };

  const openedFromHash = location.hash.length > 1;
  const memory = {
    blob: { shape: "mochi", material: "jelly" },
    animal: { shape: "bunny", material: "knit" }
  };
  const state = {
    series: "blob",
    shape: "mochi",
    material: "jelly",
    color: "peach",
    eyes: "dot",
    cheeks: true,
    accessories: [],
    agentState: "idle",
    simulating: false
  };

  let customStateDefs = {};
  let showcaseTimer = null;
  let simulationTimer = null;
  let simulationIndex = 0;
  let announceTimer = null;
  let galleryOrbi = null;
  let galleryState = "thinking";

  function titleCase(value) {
    return value.split("-").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
  }

  function isHex(value) {
    return /^#[0-9a-f]{6}$/i.test(value || "");
  }

  function resolvedHex(value) {
    return PALETTE[value] || (isHex(value) ? value.toUpperCase() : PALETTE.peach);
  }

  function announce(message, kind) {
    const bar = $("#messageBar");
    bar.textContent = message;
    bar.dataset.kind = kind || "info";
    clearTimeout(announceTimer);
    announceTimer = setTimeout(() => {
      bar.dataset.kind = "info";
    }, 2500);
  }

  function readHash() {
    const params = new URLSearchParams(location.hash.slice(1));
    const requestedSeries = params.get("series");
    if (SERIES[requestedSeries]) state.series = requestedSeries;

    const definition = SERIES[state.series];
    const requestedShape = params.get("shape");
    const requestedMaterial = params.get("material");
    state.shape = definition.shapes.includes(requestedShape) ? requestedShape : memory[state.series].shape;
    state.material = definition.materials.includes(requestedMaterial) ? requestedMaterial : memory[state.series].material;
    memory[state.series] = { shape: state.shape, material: state.material };

    const requestedColor = params.get("color");
    if (PALETTE[requestedColor] || isHex(requestedColor)) state.color = requestedColor;
    if (["dot", "capsule"].includes(params.get("eyes"))) state.eyes = params.get("eyes");
    if (params.has("cheeks")) state.cheeks = params.get("cheeks") !== "0";

    const validAccessories = BUILTIN_ACCESSORIES.concat(CUSTOM_ACCESSORIES);
    state.accessories = (params.get("accessories") || "")
      .split(",")
      .filter((name, index, all) => validAccessories.includes(name) && all.indexOf(name) === index);

    const requestedState = params.get("state");
    if (BUILTIN_STATES.concat(CUSTOM_STATES).includes(requestedState)) state.agentState = requestedState;
    state.simulating = params.get("simulate") === "1";
  }

  function writeHash() {
    const params = new URLSearchParams();
    params.set("series", state.series);
    params.set("shape", state.shape);
    params.set("material", state.material);
    params.set("color", state.color);
    params.set("eyes", state.eyes);
    params.set("cheeks", state.cheeks ? "1" : "0");
    if (state.accessories.length) params.set("accessories", state.accessories.join(","));
    params.set("state", state.agentState);
    if (state.simulating) params.set("simulate", "1");
    history.replaceState(null, "", "#" + params.toString());
  }

  function registerDefinitions(patchManifest) {
    CUSTOM_ACCESSORIES.forEach((name) => {
      if (!AgentMascot.defineAccessory(name, ACCESSORY_DEFS[name])) {
        throw new Error("The browser engine refused the " + name + " accessory.");
      }
    });

    customStateDefs = patchManifest.engine_states || {};
    CUSTOM_STATES.forEach((name) => {
      if (!customStateDefs[name] || !AgentMascot.defineState(name, customStateDefs[name])) {
        throw new Error("The browser engine refused the " + name + " state.");
      }
    });

    const headlamp = patchManifest.engine_accessories && patchManifest.engine_accessories["night-headlamp"];
    if (!headlamp || !AgentMascot.defineAccessory("night-headlamp", headlamp)) {
      throw new Error("The browser engine refused Patch's headlamp.");
    }
  }

  function makeButton(label, dataName, value, pressed) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.dataset[dataName] = value;
    button.setAttribute("aria-pressed", pressed ? "true" : "false");
    return button;
  }

  function renderShapeControls() {
    const box = $("#shapeControls");
    box.replaceChildren();
    $("#shapeLegend").textContent = SERIES[state.series].label;
    SERIES[state.series].shapes.forEach((shape) => {
      const button = makeButton(titleCase(shape), "shape", shape, shape === state.shape);
      button.addEventListener("click", () => changeConfig("shape", shape, titleCase(shape) + " selected."));
      box.appendChild(button);
    });
  }

  function renderMaterialControls() {
    const box = $("#materialControls");
    box.replaceChildren();
    $("#materialLegend").textContent = state.series === "animal" ? "Fabric" : "Finish";
    SERIES[state.series].materials.forEach((material) => {
      const button = makeButton(titleCase(material), "material", material, material === state.material);
      button.addEventListener("click", () => changeConfig("material", material, titleCase(material) + " selected."));
      box.appendChild(button);
    });
  }

  function renderColorControls() {
    const box = $("#colorControls");
    box.replaceChildren();
    Object.entries(PALETTE).forEach(([name, hex]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.color = name;
      button.style.background = hex;
      button.setAttribute("aria-label", "Set mascot color to " + name);
      button.setAttribute("aria-pressed", state.color === name ? "true" : "false");
      button.addEventListener("click", () => changeConfig("color", name, titleCase(name) + " color selected."));
      box.appendChild(button);
    });
  }

  function renderAccessoryControls() {
    const box = $("#accessoryControls");
    box.replaceChildren();
    BUILTIN_ACCESSORIES.concat(CUSTOM_ACCESSORIES).forEach((name) => {
      const label = ACCESSORY_LABELS[name] + (CUSTOM_ACCESSORIES.includes(name) ? " +" : "");
      const button = makeButton(label, "accessory", name, state.accessories.includes(name));
      if (state.series === "blob" && BUILTIN_ACCESSORIES.includes(name)) {
        button.disabled = true;
        button.title = "Built-in accessories render on Animal 3D. Custom accessories work on both styles.";
      }
      button.addEventListener("click", () => toggleAccessory(name));
      box.appendChild(button);
    });
  }

  function renderStateControls() {
    const box = $("#stateControls");
    box.replaceChildren();
    BUILTIN_STATES.concat(CUSTOM_STATES).forEach((name) => {
      const label = titleCase(name) + (CUSTOM_STATES.includes(name) ? " +" : "");
      const button = makeButton(label, "state", name, state.agentState === name);
      button.addEventListener("click", () => {
        stopShowcase();
        stopSimulation(false);
        applyAgentState(name, true);
        announce(titleCase(name) + " state selected.");
      });
      box.appendChild(button);
    });
  }

  function renderAllControls() {
    renderShapeControls();
    renderMaterialControls();
    renderColorControls();
    renderAccessoryControls();
    renderStateControls();
    syncControls();
  }

  function applyGalleryState(name, shouldAnnounce) {
    if (!GALLERY_STATES.includes(name)) return;
    galleryState = name;

    ["#mochiDemoMascot", "#bunnyMascot", "#patchMascot"].forEach((selector) => {
      const mascot = $(selector);
      if (mascot) mascot.setState(name);
    });

    if (galleryOrbi) {
      const transition = galleryOrbi.play(name, { immediate: true });
      if (transition && typeof transition.catch === "function") {
        transition.catch((error) => {
          announce("Orbi could not switch state: " + (error.message || error), "error");
        });
      }
    }

    $("#galleryStateLabel").textContent = name.toUpperCase();
    $$('[data-live-state]').forEach((badge) => {
      badge.textContent = name.toUpperCase();
    });
    $$('[data-gallery-state]').forEach((button) => {
      button.setAttribute("aria-pressed", button.dataset.galleryState === name ? "true" : "false");
    });
    $$(".demo-console .gallery-card").forEach((card) => {
      card.classList.remove("is-reacting");
      requestAnimationFrame(() => card.classList.add("is-reacting"));
    });
    if (shouldAnnounce !== false) announce("Showing " + titleCase(name) + " across every live mascot.");
  }

  function syncControls() {
    $$("[data-series]", $("#seriesControls")).forEach((button) => {
      button.setAttribute("aria-pressed", button.dataset.series === state.series ? "true" : "false");
    });
    $$("[data-eyes]", $("#eyeControls")).forEach((button) => {
      button.setAttribute("aria-pressed", button.dataset.eyes === state.eyes ? "true" : "false");
    });
    $("#cheeksButton").setAttribute("aria-pressed", state.cheeks ? "true" : "false");
    const hex = resolvedHex(state.color);
    $("#customColor").value = hex.toLowerCase();
    $("#hexValue").textContent = hex.toUpperCase();
    $("#simulateButton").setAttribute("aria-pressed", state.simulating ? "true" : "false");
    $("#simulateButton .button-label").textContent = state.simulating ? "Stop simulation" : "Simulate agent";
    $("#simulateButton .button-icon").textContent = state.simulating ? "■" : "▶";
  }

  function activeAccessories() {
    if (state.series === "animal") return state.accessories;
    return state.accessories.filter((name) => CUSTOM_ACCESSORIES.includes(name));
  }

  function updateMascot(shouldWriteHash) {
    const mascot = $("#workshopMascot");
    mascot.setConfig({
      shape: state.shape,
      material: state.material,
      color: state.color,
      eyes: state.eyes,
      cheeks: state.cheeks,
      accessory: activeAccessories().join(" ") || "none",
      state: state.agentState
    });
    $("#stageState").textContent = state.agentState.toUpperCase();
    $("#stageCaption").textContent = STATE_CAPTIONS[state.agentState];
    updateCode();
    if (shouldWriteHash !== false) writeHash();
  }

  function changeConfig(key, value, message) {
    stopShowcase();
    state[key] = value;
    if (key === "shape" || key === "material") {
      memory[state.series] = { shape: state.shape, material: state.material };
    }
    renderAllControls();
    updateMascot();
    announce(message);
  }

  function setSeries(series) {
    if (series === state.series) return;
    stopShowcase();
    memory[state.series] = { shape: state.shape, material: state.material };
    state.series = series;
    state.shape = memory[series].shape;
    state.material = memory[series].material;
    renderAllControls();
    updateMascot();
    announce(series === "animal" ? "Animal 3D selected." : "Blob selected.");
  }

  function toggleAccessory(name) {
    stopShowcase();
    const index = state.accessories.indexOf(name);
    if (index >= 0) state.accessories.splice(index, 1);
    else state.accessories.push(name);
    renderAccessoryControls();
    updateMascot();
    announce(ACCESSORY_LABELS[name] + (index >= 0 ? " removed." : " added."));
  }

  function applyAgentState(name, shouldWriteHash) {
    state.agentState = name;
    $("#workshopMascot").setState(name);
    $("#stageState").textContent = name.toUpperCase();
    $("#stageCaption").textContent = STATE_CAPTIONS[name];
    $$("[data-state]", $("#stateControls")).forEach((button) => {
      button.setAttribute("aria-pressed", button.dataset.state === name ? "true" : "false");
    });
    updateCode();
    if (shouldWriteHash !== false) writeHash();
  }

  function startShowcase() {
    stopShowcase();
    const sequence = BUILTIN_STATES.concat(CUSTOM_STATES);
    let index = 0;
    showcaseTimer = setInterval(() => {
      index = (index + 1) % sequence.length;
      applyAgentState(sequence[index], false);
    }, 1900);
  }

  function stopShowcase() {
    clearInterval(showcaseTimer);
    showcaseTimer = null;
  }

  function startSimulation() {
    stopShowcase();
    stopSimulation(false);
    state.simulating = true;
    simulationIndex = 0;
    const sequence = ["listening", "thinking", "working", "talking", "done"];
    applyAgentState(sequence[simulationIndex], false);
    simulationTimer = setInterval(() => {
      simulationIndex = (simulationIndex + 1) % sequence.length;
      applyAgentState(sequence[simulationIndex], false);
    }, 1500);
    syncControls();
    writeHash();
    announce("Agent simulation running: listening, thinking, working, talking, done.");
  }

  function stopSimulation(announceStop) {
    clearInterval(simulationTimer);
    simulationTimer = null;
    if (state.simulating) {
      state.simulating = false;
      syncControls();
      writeHash();
      if (announceStop !== false) announce("Agent simulation stopped.");
    }
  }

  function definitionLine(kind, name, definition) {
    let source = JSON.stringify(definition, null, 2);
    if (kind === "Accessory" && name === "bow") {
      source = source.slice(0, -2) + ",\n  \"svg\": function (ctx) {\n" +
        "    ctx.el(\"path\", { d: \"M0 0C-18-17-38-13-39 2C-38 17-18 18 0 4C18 18 38 17 39 2C38-13 18-17 0 0Z\", fill: \"#E5534B\" });\n" +
        "    ctx.el(\"circle\", { r: \"8\", fill: \"#F5A3B7\", stroke: \"#fff\", \"stroke-width\": \"2\" });\n" +
        "  }\n}";
    }
    return "AgentMascot.define" + kind + "(\"" + name + "\", " + source + ");";
  }

  function embedSnippet() {
    const lines = [
      "<script src=\"https://arivex-ca.github.io/mascotforge/vendor/agent-mascot.js\"><\\/script>",
      "<script>",
      "AgentMascot.THREE_URL = \"https://arivex-ca.github.io/mascotforge/vendor/three.module.min.js\";"
    ];

    state.accessories.filter((name) => CUSTOM_ACCESSORIES.includes(name)).forEach((name) => {
      lines.push(definitionLine("Accessory", name, ACCESSORY_DEFS[name]));
    });
    CUSTOM_STATES.forEach((name) => {
      lines.push(definitionLine("State", name, customStateDefs[name]));
    });
    lines.push("<\\/script>");

    const attributes = [
      ["shape", state.shape],
      ["material", state.material],
      ["color", state.color],
      ["eyes", state.eyes],
      ["cheeks", String(state.cheeks)],
      ["state", state.agentState]
    ];
    const selectedAccessories = activeAccessories();
    if (selectedAccessories.length) attributes.splice(5, 0, ["accessory", selectedAccessories.join(" ")]);
    lines.push("<agent-mascot " + attributes.map(([name, value]) => name + "=\"" + value + "\"").join(" ") + "></agent-mascot>");
    return lines.join("\n").replace(/<\\\/script>/g, "</script>");
  }

  function updateCode() {
    $("#embedCode").textContent = embedSnippet();
  }

  function fallbackCopy(text) {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const copied = document.execCommand("copy");
    area.remove();
    if (!copied) throw new Error("Your browser blocked clipboard access.");
  }

  async function copyText(text, button, successMessage, storageKey) {
    const original = $(".button-label", button).textContent;
    button.disabled = true;
    button.classList.add("is-loading");
    $(".button-label", button).textContent = "Copying";
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
      else fallbackCopy(text);
      window[storageKey] = text;
      $(".button-label", button).textContent = "Copied";
      announce(successMessage, "success");
      await new Promise((resolve) => setTimeout(resolve, 650));
    } catch (error) {
      announce("Copy failed: " + (error.message || error), "error");
      $(".button-label", button).textContent = "Copy failed";
      await new Promise((resolve) => setTimeout(resolve, 900));
    } finally {
      button.disabled = false;
      button.classList.remove("is-loading");
      $(".button-label", button).textContent = original;
    }
  }

  function bindControls() {
    $$("[data-series]", $("#seriesControls")).forEach((button) => {
      button.addEventListener("click", () => setSeries(button.dataset.series));
    });
    $$("[data-eyes]", $("#eyeControls")).forEach((button) => {
      button.addEventListener("click", () => changeConfig("eyes", button.dataset.eyes, titleCase(button.dataset.eyes) + " eyes selected."));
    });
    $("#cheeksButton").addEventListener("click", () => changeConfig("cheeks", !state.cheeks, state.cheeks ? "Cheeks removed." : "Cheeks added."));
    $("#customColor").addEventListener("input", (event) => {
      stopShowcase();
      state.color = event.target.value.toUpperCase();
      renderColorControls();
      syncControls();
      updateMascot();
      announce("Custom color " + state.color + " selected.");
    });
    $("#simulateButton").addEventListener("click", () => {
      if (state.simulating) stopSimulation(true);
      else startSimulation();
    });
    $("#copyCodeButton").addEventListener("click", () => {
      copyText(embedSnippet(), $("#copyCodeButton"), "Code copied.", "__lastCopiedCode");
    });
    $("#copyLinkButton").addEventListener("click", () => {
      writeHash();
      copyText(location.href, $("#copyLinkButton"), "Shareable design link copied.", "__lastCopiedLink");
    });
    $$('[data-gallery-state]', $("#galleryStateControls")).forEach((button) => {
      button.addEventListener("click", () => applyGalleryState(button.dataset.galleryState, true));
    });
  }

  function showFallbackIfNeeded() {
    if (!AgentMascot.supports3D()) $("#fallbackNotice").hidden = false;
  }

  async function configureGallery(patchManifest) {
    const mochi = $("#mochiDemoMascot");
    mochi.setConfig({ state: galleryState });

    const bunny = $("#bunnyMascot");
    bunny.setConfig({ accessory: "headphones", state: galleryState });

    const patch = $("#patchMascot");
    const config = Object.assign({}, patchManifest.engine_config, {
      accessory: "night-headlamp",
      state: galleryState
    });
    patch.setConfig(config);

    const orbiMount = $("#orbiMount");
    if (!AgentMascot.supports3D()) {
      $("#orbiStatus").hidden = false;
      $("[data-gallery=orbi]").dataset.ready = "fallback";
      $("[data-gallery=mochi]").dataset.ready = "true";
      $("[data-gallery=bunny]").dataset.ready = "true";
      $("[data-gallery=patch]").dataset.ready = "true";
      applyGalleryState(galleryState, false);
      return;
    }
    const orbi = document.createElement("mascot-avatar");
    orbi.id = "orbiMascot";
    orbi.setAttribute("manifest", "./data/orbi-manifest.json");
    orbi.setAttribute("label", "Orbi typing on a keyboard");
    orbi.setAttribute("follow-cursor", "false");
    orbiMount.prepend(orbi);
    await customElements.whenDefined("mascot-avatar");
    await orbi.ready();
    galleryOrbi = orbi;
    await orbi.play(galleryState, { immediate: true });
    if (!orbi.shadowRoot || !orbi.shadowRoot.querySelector("wobnimo-mascot")) {
      throw new Error("Orbi's Wobnimo renderer did not start.");
    }
    $("[data-gallery=orbi]").dataset.ready = "true";
    $("[data-gallery=mochi]").dataset.ready = "true";
    $("[data-gallery=bunny]").dataset.ready = "true";
    $("[data-gallery=patch]").dataset.ready = "true";
    applyGalleryState(galleryState, false);
  }

  async function bootstrap() {
    const response = await fetch("./data/patch-manifest.json");
    if (!response.ok) throw new Error("Patch manifest returned HTTP " + response.status + ".");
    const patchManifest = await response.json();
    registerDefinitions(patchManifest);
    readHash();
    bindControls();
    renderAllControls();
    updateMascot();
    showFallbackIfNeeded();
    await configureGallery(patchManifest);

    if (state.simulating) startSimulation();
    else if (!openedFromHash) startShowcase();

    window.__mascotforge = {
      getState: () => JSON.parse(JSON.stringify(state)),
      stopShowcase,
      stopSimulation: () => stopSimulation(false),
      applyState: (name) => applyAgentState(name, true),
      getGalleryState: () => galleryState,
      applyGalleryState: (name) => applyGalleryState(name, false),
      ready: true
    };
    document.documentElement.dataset.ready = "true";
  }

  bootstrap().catch((error) => {
    console.error("MascotForge playground failed:", error);
    announce("Playground failed to start: " + (error.message || error), "error");
    $("#fallbackNotice").hidden = false;
    $("#fallbackNotice").textContent = "The live preview could not start. " + (error.message || error);
    document.documentElement.dataset.ready = "error";
  });
})();
