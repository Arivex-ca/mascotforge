#!/usr/bin/env node
import { spawnSync, spawn } from 'child_process';
import { readFileSync, existsSync, mkdirSync, cpSync, statSync, watch, writeFileSync, mkdtempSync, rmSync, readdirSync } from 'fs';
import { createServer } from 'http';
import { resolve as resolve$1, dirname, join, relative, basename, extname, delimiter } from 'path';
import { fileURLToPath, pathToFileURL } from 'url';
import { tmpdir, homedir } from 'os';

// ../engine/src/behavior/states.ts
var STATES = ["idle", "thinking", "listening", "speaking", "sleeping", "working", "error", "surprised", "celebrating", "sad"];
var EXPRESSIONS = [...STATES, "happy"];
Object.fromEntries(EXPRESSIONS.map((e, i) => [e, i]));

// ../engine/src/compiler/resolve.ts
var SpecError = class extends Error {
  constructor(character, message) {
    super(`${character}: ${message}`);
    this.name = "SpecError";
  }
};
function resolve(spec) {
  const fail2 = (msg) => {
    throw new SpecError(spec.id, msg);
  };
  const bones = [{ name: "root", pivot: [0, 0, 0], index: 0, parentIndex: -1 }];
  const byName = /* @__PURE__ */ new Map([["root", 0]]);
  spec.bones.forEach((b, i) => {
    if (byName.has(b.name)) fail2(`bone "${b.name}" is declared twice`);
    const parent = b.parent ?? "root";
    const parentIndex = byName.get(parent);
    if (parentIndex === void 0) fail2(`bone "${b.name}" names parent "${parent}", which is not declared before it`);
    byName.set(b.name, i + 1);
    bones.push({ ...b, index: i + 1, parentIndex });
  });
  const materials = Object.entries(spec.materials).map(([name, m], i) => ({ name, id: i + 1, spec: m }));
  const matByName = new Map(materials.map((m) => [m.name, m.id]));
  const eyeIds = [materials.length + 1, materials.length + 2];
  const boneIndex = (name, where) => byName.get(name) ?? fail2(`${where} names bone "${name}", which does not exist`);
  const materialId = (name, where) => matByName.get(name) ?? fail2(`${where} names material "${name}", which does not exist`);
  materials.forEach((m) => {
    if (m.spec.shadeOf !== void 0) materialId(m.spec.shadeOf, `materials.${m.name}.shadeOf`);
  });
  spec.parts.forEach((p, i) => {
    boneIndex(p.bone, `parts[${i}]`);
    materialId(p.material, `parts[${i}]`);
  });
  spec.paints?.forEach((p, i) => {
    boneIndex(p.bone, `paints[${i}]`);
    p.on.forEach((m) => materialId(m, `paints[${i}]`));
  });
  const acting = bones.map(() => []);
  for (const [expression, perBone] of Object.entries(spec.acting ?? {})) {
    for (const [name, axes] of Object.entries(perBone)) {
      const i = boneIndex(name, `acting.${expression}`);
      for (const [axis, motion] of Object.entries(axes)) acting[i].push([expression, axis, motion]);
    }
  }
  const anchors = {};
  for (const [name, a] of Object.entries(spec.anchors ?? {})) anchors[name] = { bone: boneIndex(a.bone, `anchors.${name}`), at: a.at };
  for (const [trigger, emitters] of Object.entries(spec.fx ?? {})) {
    if (trigger === "replace") continue;
    emitters.forEach((e, i) => {
      if (!anchors[e.anchor]) fail2(`fx.${trigger}[${i}] names anchor "${e.anchor}", which does not exist`);
    });
  }
  return { spec, bones, boneIndex, materials, materialId, eyeIds, acting, anchors };
}

// ../engine/src/math/scalar.ts
var clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
function rng(seed) {
  let a = Math.floor(seed * 4294967295) >>> 0 || 1;
  return () => {
    a = a + 1831565813 >>> 0;
    let t = a;
    t = Math.imul(t ^ t >>> 15, t | 1);
    t ^= t + Math.imul(t ^ t >>> 7, t | 61);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

// ../engine/src/math/mat4.ts
var mat4 = () => identity(new Float32Array(16));
function identity(out) {
  out.fill(0);
  out[0] = out[5] = out[10] = out[15] = 1;
  return out;
}
function multiply(out, a, b) {
  const r = new Float32Array(16);
  for (let c = 0; c < 4; c++) {
    for (let row = 0; row < 4; row++) {
      r[c * 4 + row] = a[row] * b[c * 4] + a[4 + row] * b[c * 4 + 1] + a[8 + row] * b[c * 4 + 2] + a[12 + row] * b[c * 4 + 3];
    }
  }
  out.set(r);
  return out;
}
function fromTranslation(out, x, y, z) {
  identity(out);
  out[12] = x;
  out[13] = y;
  out[14] = z;
  return out;
}
function fromEuler(out, rx, ry, rz) {
  const cx = Math.cos(rx), sx = Math.sin(rx);
  const cy = Math.cos(ry), sy = Math.sin(ry);
  const cz = Math.cos(rz), sz = Math.sin(rz);
  identity(out);
  out[0] = cz * cy;
  out[1] = sz * cy;
  out[2] = -sy;
  out[4] = cz * sy * sx - sz * cx;
  out[5] = sz * sy * sx + cz * cx;
  out[6] = cy * sx;
  out[8] = cz * sy * cx + sz * sx;
  out[9] = sz * sy * cx - cz * sx;
  out[10] = cy * cx;
  return out;
}
function fromAxisAngle(out, axis, angle) {
  const [x, y, z] = axis;
  const c = Math.cos(angle), s = Math.sin(angle), t = 1 - c;
  identity(out);
  out[0] = t * x * x + c;
  out[1] = t * x * y + s * z;
  out[2] = t * x * z - s * y;
  out[4] = t * x * y - s * z;
  out[5] = t * y * y + c;
  out[6] = t * y * z + s * x;
  out[8] = t * x * z + s * y;
  out[9] = t * y * z - s * x;
  out[10] = t * z * z + c;
  return out;
}
function invert(out, m) {
  const [a00, a01, a02, a03, a10, a11, a12, a13, a20, a21, a22, a23, a30, a31, a32, a33] = m;
  const b00 = a00 * a11 - a01 * a10, b01 = a00 * a12 - a02 * a10, b02 = a00 * a13 - a03 * a10;
  const b03 = a01 * a12 - a02 * a11, b04 = a01 * a13 - a03 * a11, b05 = a02 * a13 - a03 * a12;
  const b06 = a20 * a31 - a21 * a30, b07 = a20 * a32 - a22 * a30, b08 = a20 * a33 - a23 * a30;
  const b09 = a21 * a32 - a22 * a31, b10 = a21 * a33 - a23 * a31, b11 = a22 * a33 - a23 * a32;
  const det = b00 * b11 - b01 * b10 + b02 * b09 + b03 * b08 - b04 * b07 + b05 * b06;
  if (!det) return identity(out);
  const d = 1 / det;
  out[0] = (a11 * b11 - a12 * b10 + a13 * b09) * d;
  out[1] = (a02 * b10 - a01 * b11 - a03 * b09) * d;
  out[2] = (a31 * b05 - a32 * b04 + a33 * b03) * d;
  out[3] = (a22 * b04 - a21 * b05 - a23 * b03) * d;
  out[4] = (a12 * b08 - a10 * b11 - a13 * b07) * d;
  out[5] = (a00 * b11 - a02 * b08 + a03 * b07) * d;
  out[6] = (a32 * b02 - a30 * b05 - a33 * b01) * d;
  out[7] = (a20 * b05 - a22 * b02 + a23 * b01) * d;
  out[8] = (a10 * b10 - a11 * b08 + a13 * b06) * d;
  out[9] = (a01 * b08 - a00 * b10 - a03 * b06) * d;
  out[10] = (a30 * b04 - a31 * b02 + a33 * b00) * d;
  out[11] = (a21 * b02 - a20 * b04 - a23 * b00) * d;
  out[12] = (a11 * b07 - a10 * b09 - a12 * b06) * d;
  out[13] = (a00 * b09 - a01 * b07 + a02 * b06) * d;
  out[14] = (a31 * b01 - a30 * b03 - a32 * b00) * d;
  out[15] = (a20 * b03 - a21 * b01 + a22 * b00) * d;
  return out;
}
function transformPoint(m, p) {
  const [x, y, z] = p;
  return [m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14]];
}
function transformDir(m, d) {
  const [x, y, z] = d;
  return [m[0] * x + m[4] * y + m[8] * z, m[1] * x + m[5] * y + m[9] * z, m[2] * x + m[6] * y + m[10] * z];
}

// ../engine/src/math/vec3.ts
var add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
var sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
var scale = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
var dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
var cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
var length = (a) => Math.hypot(a[0], a[1], a[2]);
function normalize(a) {
  const l = length(a) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
}

// ../engine/src/rig/rig.ts
var AXES = ["rx", "ry", "rz"];
function evaluate(m, time) {
  if (typeof m === "number") return m;
  const [base, amp = 0, hz = 0, phase = 0] = m;
  return base + amp * Math.sin(time * hz * Math.PI * 2 + phase);
}
var Rig = class {
  constructor(bones, acting = bones.map(() => [])) {
    this.bones = bones;
    this.acting = acting;
    this.world = bones.map(() => mat4());
    this.inverse = new Float32Array(bones.length * 16);
    this.tips = bones.map(() => null);
    this.spun = bones.map(() => ({ rx: 0, ry: 0, rz: 0 }));
  }
  bones;
  acting;
  world;
  /** World → bone, packed for upload: 16 floats per bone. */
  inverse;
  tips;
  /** Spin accumulated by acting, per bone and axis. */
  spun;
  scratch = { t: mat4(), r: mat4(), j: mat4(), inv: mat4() };
  /** A point in a bone's space, in world space, as of the last update. */
  point(bone, at) {
    return transformPoint(this.world[bone], at);
  }
  /**
   * Poses the skeleton. `root` places the whole character, `weights` blends
   * each expression's acting, `dt` steps the jiggle springs and spins.
   */
  update(root, ch, weights, time, dt) {
    const { t, r, j, inv } = this.scratch;
    this.world[0].set(root);
    for (let i = 1; i < this.bones.length; i++) {
      const bone = this.bones[i];
      const angle = { rx: bone.rest?.rx ?? 0, ry: bone.rest?.ry ?? 0, rz: bone.rest?.rz ?? 0 };
      for (const axis of AXES) {
        for (const [channel, weight] of bone.drive?.[axis] ?? []) angle[axis] += ch[channel] * weight;
        const w = bone.wave?.[axis];
        if (w) angle[axis] += w[0] * ch.energy * Math.sin(time * w[1] * Math.PI * 2 + w[2]);
      }
      for (const [expression, axis, motion] of this.acting[i]) {
        const weight = weights[expression];
        if (weight < 1e-3 && !(Array.isArray(motion) && motion[4])) continue;
        angle[axis] += weight * evaluate(motion, time);
        if (Array.isArray(motion) && motion[4]) this.spun[i][axis] += weight * motion[4] * dt;
      }
      for (const axis of AXES) angle[axis] += this.spun[i][axis];
      const out = this.world[i];
      multiply(out, this.world[bone.parentIndex], fromTranslation(t, ...bone.pivot));
      multiply(out, out, fromEuler(r, angle.rx, angle.ry, angle.rz));
      if (bone.jiggle) multiply(out, out, this.jiggle(i, out, dt, j, inv));
    }
    for (let i = 0; i < this.bones.length; i++) this.inverse.set(invert(inv, this.world[i]), i * 16);
  }
  /* The bone's tip is a point mass chasing where the tip would be at rest.
     Returns the extra rotation, in the bone's space, that points it there. */
  jiggle(i, posed, dt, out, inv) {
    const { axis, length: len, freq, damping, maxAngle = 0.9 } = this.bones[i].jiggle;
    const anchor = transformPoint(posed, [0, 0, 0]);
    const restTip = add(anchor, scale(normalize(transformDir(posed, axis)), len));
    let tip = this.tips[i];
    if (!tip || !(dt > 0)) {
      tip = this.tips[i] = tip ?? { x: restTip, v: [0, 0, 0] };
      if (!(dt > 0)) return fromAxisAngle(out, [0, 1, 0], 0);
    }
    const w = freq * Math.PI * 2;
    for (let k = 0; k < 3; k++) {
      tip.v[k] += (w * w * (restTip[k] - tip.x[k]) - 2 * damping * w * tip.v[k]) * dt;
      tip.x[k] += tip.v[k] * dt;
    }
    tip.x = add(anchor, scale(normalize(sub(tip.x, anchor)), len));
    invert(inv, posed);
    const want = normalize(transformDir(inv, sub(tip.x, anchor)));
    const rest = normalize(axis);
    const turn = cross(rest, want);
    const s = length(turn);
    if (s < 1e-6) return fromAxisAngle(out, [0, 1, 0], 0);
    const angle = clamp(Math.atan2(s, dot(rest, want)), 0, maxAngle);
    return fromAxisAngle(out, scale(turn, 1 / s), angle);
  }
};

// ../engine/src/check/sdf.ts
var len2 = (x, y) => Math.hypot(x, y);
var clamp2 = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
function sdEllipsoid(p, r) {
  const k0 = Math.hypot(p[0] / r[0], p[1] / r[1], p[2] / r[2]);
  const k1 = Math.hypot(p[0] / (r[0] * r[0]), p[1] / (r[1] * r[1]), p[2] / (r[2] * r[2]));
  return k0 * (k0 - 1) / Math.max(k1, 1e-6);
}
function sdRoundBox(p, b, r) {
  const qx = Math.abs(p[0]) - b[0] + r, qy = Math.abs(p[1]) - b[1] + r, qz = Math.abs(p[2]) - b[2] + r;
  return Math.hypot(Math.max(qx, 0), Math.max(qy, 0), Math.max(qz, 0)) + Math.min(Math.max(qx, qy, qz), 0) - r;
}
function sdCapsule(p, a, b, r) {
  const pa = [p[0] - a[0], p[1] - a[1], p[2] - a[2]];
  const ba = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const h = clamp2((pa[0] * ba[0] + pa[1] * ba[1] + pa[2] * ba[2]) / (ba[0] * ba[0] + ba[1] * ba[1] + ba[2] * ba[2] || 1e-9), 0, 1);
  return Math.hypot(pa[0] - ba[0] * h, pa[1] - ba[1] * h, pa[2] - ba[2] * h) - r;
}
function sdRoundCone(p, a, b, r1, r22) {
  const ba = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const l2 = ba[0] * ba[0] + ba[1] * ba[1] + ba[2] * ba[2] || 1e-9;
  const rr = r1 - r22;
  const a2 = l2 - rr * rr;
  const il2 = 1 / l2;
  const pa = [p[0] - a[0], p[1] - a[1], p[2] - a[2]];
  const y = pa[0] * ba[0] + pa[1] * ba[1] + pa[2] * ba[2];
  const z = y - l2;
  const xv = [pa[0] * l2 - ba[0] * y, pa[1] * l2 - ba[1] * y, pa[2] * l2 - ba[2] * y];
  const x2 = xv[0] * xv[0] + xv[1] * xv[1] + xv[2] * xv[2];
  const y2 = y * y * l2;
  const z2 = z * z * l2;
  const k = Math.sign(rr) * rr * rr * x2;
  if (Math.sign(z) * a2 * z2 > k) return Math.sqrt(x2 + z2) * il2 - r22;
  if (Math.sign(y) * a2 * y2 < k) return Math.sqrt(x2 + y2) * il2 - r1;
  return (Math.sqrt(x2 * a2 * il2) + y * rr) * il2 - r1;
}
function sdCylinder(p, r, h, rr) {
  const dx = len2(p[0], p[2]) - r + rr;
  const dy = Math.abs(p[1]) - h + rr;
  return Math.min(Math.max(dx, dy), 0) + len2(Math.max(dx, 0), Math.max(dy, 0)) - rr;
}
function sdRoundRect(x, y, b, r) {
  const qx = Math.abs(x) - b[0] + r, qy = Math.abs(y) - b[1] + r;
  return len2(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r;
}
function sdFrame(p, b, corner, w, depth) {
  const ring = Math.abs(sdRoundRect(p[0], p[1], b, corner)) - w;
  const ez = Math.abs(p[2]) - depth;
  return Math.min(Math.max(ring, ez), 0) + len2(Math.max(ring, 0), Math.max(ez, 0));
}
function sdPlate(p, b, corner, depth) {
  const e = sdRoundRect(p[0], p[1], b, corner);
  const ez = Math.abs(p[2]) - depth;
  return Math.min(Math.max(e, ez), 0) + len2(Math.max(e, 0), Math.max(ez, 0));
}
function smin(a, b, k) {
  const h = Math.max(k - Math.abs(a - b), 0) / k;
  return Math.min(a, b) - h * h * k * 0.25;
}
var smax = (a, b, k) => -smin(-a, -b, k);
function partDistance(part, l) {
  switch (part.shape) {
    case "sphere":
      return Math.hypot(l[0], l[1], l[2]) - part.radius;
    case "ellipsoid":
      return sdEllipsoid(l, part.radii);
    case "roundBox":
      return sdRoundBox(l, part.half, part.round);
    case "capsule":
      return sdCapsule(l, part.from, part.to, part.radius);
    case "roundCone":
      return sdRoundCone(l, part.from, part.to, part.r1, part.r2);
    case "cylinder":
      return sdCylinder(l, part.radius, part.half, part.round);
    case "frame":
      return sdFrame(l, part.half, part.corner, part.width, part.depth);
    case "plate":
      return sdPlate(l, part.half, part.corner, part.depth);
    case "hem":
      return Infinity;
  }
}
function partBox(part) {
  const sym = (x, y, z) => [[-x, -y, -z], [x, y, z]];
  const seg = (a, b, r) => [
    [Math.min(a[0], b[0]) - r, Math.min(a[1], b[1]) - r, Math.min(a[2], b[2]) - r],
    [Math.max(a[0], b[0]) + r, Math.max(a[1], b[1]) + r, Math.max(a[2], b[2]) + r]
  ];
  switch (part.shape) {
    case "sphere":
      return sym(part.radius, part.radius, part.radius);
    case "ellipsoid":
      return sym(...part.radii);
    case "roundBox":
      return sym(...part.half);
    case "capsule":
      return seg(part.from, part.to, part.radius);
    case "roundCone":
      return seg(part.from, part.to, Math.max(part.r1, part.r2));
    case "cylinder":
      return sym(part.radius, part.half, part.radius);
    case "frame":
      return sym(part.half[0] + part.width, part.half[1] + part.width, part.depth);
    case "plate":
      return sym(part.half[0], part.half[1], part.depth);
    case "hem":
      return null;
  }
}

// ../engine/src/check/field.ts
var TAN_HALF_FOV = 0.2;
var CAMERA_PITCH = 0.1;
function pose(r, expression = "idle", time = 0, drive = {}) {
  const hover = r.spec.motion?.float ?? 0;
  const rig = new Rig(r.bones, r.acting);
  const weights = Object.fromEntries(EXPRESSIONS.map((e) => [e, e === expression ? 1 : 0]));
  const channels = { yaw: 0, pitch: 0, roll: 0, flap: 0, talk: 0, energy: 0, ...drive };
  rig.update(fromTranslation(mat4(), 0, hover, 0), channels, weights, time, 0);
  return { world: rig.world.map((m) => m.slice()), inverse: rig.world.map((m) => invert(mat4(), m)) };
}
var rowMajor = (rot) => {
  const m = fromEuler(mat4(), rot[0], rot[1], rot[2]);
  return [m[0], m[4], m[8], m[1], m[5], m[9], m[2], m[6], m[10]];
};
var unit = (v) => {
  const n = Math.hypot(...v) || 1;
  return [v[0] / n, v[1] / n, v[2] / n];
};
var Field = class {
  constructor(spec) {
    this.spec = spec;
    this.r = resolve(spec);
    this.parts = spec.parts.map((p, i) => ({
      spec: p,
      bone: this.r.boneIndex(p.bone, `parts[${i}]`),
      at: p.at ?? [0, 0, 0],
      rot: p.rot ? rowMajor(p.rot) : null,
      clip: p.clip ? { normal: unit(p.clip.normal), offset: p.clip.offset ?? 0 } : null
    }));
    this.posed = pose(this.r);
  }
  spec;
  r;
  parts;
  posed;
  /** A point from a bone's space into the world, in the current pose. */
  toWorld(bone, at) {
    return transformPoint(this.posed.world[bone], at);
  }
  toBone(bone, p) {
    return transformPoint(this.posed.inverse[bone], p);
  }
  /** A world point into part `i`'s own space. */
  toPart(i, p) {
    const part = this.parts[i];
    const b = this.toBone(part.bone, p);
    const d = [b[0] - part.at[0], b[1] - part.at[1], b[2] - part.at[2]];
    const m = part.rot;
    return m ? [m[0] * d[0] + m[3] * d[1] + m[6] * d[2], m[1] * d[0] + m[4] * d[1] + m[7] * d[2], m[2] * d[0] + m[5] * d[1] + m[8] * d[2]] : d;
  }
  /** A point in part `i`'s own space back into the world. */
  fromPart(i, l) {
    const part = this.parts[i];
    const m = part.rot;
    const b = m ? [m[0] * l[0] + m[1] * l[1] + m[2] * l[2], m[3] * l[0] + m[4] * l[1] + m[5] * l[2], m[6] * l[0] + m[7] * l[1] + m[8] * l[2]] : l;
    return this.toWorld(part.bone, [b[0] + part.at[0], b[1] + part.at[1], b[2] + part.at[2]]);
  }
  /** Part `i` on its own, clip included, in its own space. */
  localDistance(i, l) {
    const part = this.parts[i];
    const d = partDistance(part.spec, l);
    const c = part.clip;
    return c ? Math.max(d, l[0] * c.normal[0] + l[1] * c.normal[1] + l[2] * c.normal[2] - c.offset) : d;
  }
  /** Part `i` on its own, at a world point. */
  partDistance(i, p) {
    return this.localDistance(i, this.toPart(i, p));
  }
  /**
   * The whole character at `p`, exactly as the shader's map() combines it.
   * `skip` leaves one part out; `eyes: false` leaves the eyes out.
   */
  map(p, skip = -1, eyes = true) {
    let d = 1e9;
    let id = 0;
    for (let i = 0; i < this.parts.length; i++) {
      if (i === skip) continue;
      const part = this.parts[i].spec;
      if (part.shape === "hem") {
        const l = this.toPart(i, p);
        d = smax(d, part.y + part.amplitude * Math.sin(Math.atan2(l[2], l[0]) * part.waves) - l[1], part.blend);
        continue;
      }
      const di = this.partDistance(i, p);
      const k = part.blend ?? 0;
      if (part.op === "sub") {
        d = k > 0 ? smax(d, -di, k) : Math.max(d, -di);
      } else {
        if (di < d) id = this.r.materialId(part.material, "");
        d = k > 0 ? smin(d, di, k) : Math.min(d, di);
      }
    }
    if (eyes && this.spec.eyes) {
      for (let e = 0; e < 2; e++) {
        const de = this.eyeDistance(e, p);
        if (de < d) {
          d = de;
          id = this.spec.eyes.kind === "ball" ? this.r.eyeIds[e] : this.r.materialId(this.spec.eyes.material, "eyes");
        }
      }
    }
    return { d, id };
  }
  /** One eye, open and looking ahead, the way it rests in idle. */
  eyeDistance(e, p) {
    const eyes = this.spec.eyes;
    const b = this.toBone(this.r.boneIndex(eyes.bone, "eyes"), p);
    const at = eyes.at[e];
    const l = [b[0] - at[0], b[1] - at[1], b[2] - at[2]];
    if (eyes.kind === "ball") return Math.hypot(...l) - eyes.radius;
    const [rx, ry, rz] = eyes.radii;
    const k0 = Math.hypot(l[0] / rx, l[1] / ry, l[2] / rz);
    const k1 = Math.hypot(l[0] / (rx * rx), l[1] / (ry * ry), l[2] / (rz * rz));
    return k0 * (k0 - 1) / Math.max(k1, 1e-6);
  }
  /** The surface normal at `p`, from the field's gradient. */
  normal(p, skip = -1, eyes = true) {
    const e = 6e-4;
    const g = [0, 0, 0];
    for (let k = 0; k < 3; k++) {
      const a = [p[0], p[1], p[2]];
      const b = [p[0], p[1], p[2]];
      a[k] += e;
      b[k] -= e;
      g[k] = this.map(a, skip, eyes).d - this.map(b, skip, eyes).d;
    }
    return unit(g);
  }
  /** Where the camera sits for this character's framing. */
  camera() {
    const distance = this.spec.frame.radius / TAN_HALF_FOV;
    return [0, this.spec.frame.target + distance * Math.sin(CAMERA_PITCH), distance * Math.cos(CAMERA_PITCH)];
  }
  /** Marches from `from` toward `to`; returns the distance travelled at the first hit, or null. */
  march(from, to, eyes = true, epsilon = 15e-4) {
    const dir = [to[0] - from[0], to[1] - from[1], to[2] - from[2]];
    const total = Math.hypot(...dir);
    const u = [dir[0] / total, dir[1] / total, dir[2] / total];
    const far = Math.min(total, this.spec.bound.radius * 2 + Math.hypot(from[0], from[1] - this.spec.bound.y, from[2]) + 0.5);
    let t = 0;
    for (let i = 0; i < 160 && t < far; i++) {
      const at = [from[0] + u[0] * t, from[1] + u[1] * t, from[2] + u[2] * t];
      const hit = this.map(at, -1, eyes);
      if (hit.d < epsilon) return { t, at, hit };
      t += Math.max(hit.d * 0.9, epsilon * 0.5);
    }
    return null;
  }
  /** Can the camera see the surface point `p`? */
  visible(p) {
    const cam = this.camera();
    const n = this.normal(p);
    const v = unit([cam[0] - p[0], cam[1] - p[1], cam[2] - p[2]]);
    if (n[0] * v[0] + n[1] * v[1] + n[2] * v[2] < 0.05) return false;
    const start = [p[0] + n[0] * 6e-3, p[1] + n[1] * 6e-3, p[2] + n[2] * 6e-3];
    return this.march(start, cam) === null;
  }
  /** The material name for an id from map(). */
  materialName(id) {
    const m = this.r.materials.find((x) => x.id === id);
    if (m) return m.name;
    return id === this.r.eyeIds[0] || id === this.r.eyeIds[1] ? "eye" : "nothing";
  }
};

// ../engine/src/check/validate.ts
var HEX = /^#[0-9a-f]{6}$/i;
var ID = /^[a-z][a-z0-9-]*$/;
var SHAPES = ["sphere", "ellipsoid", "roundBox", "capsule", "roundCone", "cylinder", "frame", "plate", "hem"];
var AXES2 = ["rx", "ry", "rz"];
var CHANNELS = ["yaw", "pitch", "roll", "flap", "talk"];
var TEMPERAMENT = ["float", "hop", "squash", "snap", "look", "snapLook", "talkSquash"];
var SURFACES = ["fur", "scales", "speckle", "ripple"];
var GLYPHS = ["z", "bubble", "sparkle", "heart", "note", "arc", "puff", "ring", "drop", "spark", "mote", "feather", "dot", "exclaim", "warning", "confetti", "cloud", "star", "gear"];
var TOP = ["id", "name", "tagline", "accent", "frame", "bound", "motion", "materials", "bones", "parts", "paints", "eyes", "face", "anchors", "acting", "fx", "glowPool"];
var MATERIAL_KEYS = ["color", "shadeOf", "f0", "spec", "shininess", "metal", "rim", "gloss", "sheen", "sss", "sssColor", "emit", "emitStrength", "glows", "surface"];
function validate(spec) {
  const issues = [];
  const err = (where, message, fix) => issues.push({ level: "error", where, message, fix });
  const warn = (where, message, fix) => issues.push({ level: "warning", where, message, fix });
  if (!spec || typeof spec !== "object") {
    err("spec", "The spec is not an object.");
    return issues;
  }
  const s = spec;
  const num = (v) => typeof v === "number" && Number.isFinite(v);
  const pos = (v) => num(v) && v > 0;
  const vec = (v, n) => Array.isArray(v) && v.length === n && v.every(num);
  const needNum = (where, v, positive = false) => {
    if (positive ? !pos(v) : !num(v)) err(where, `Expected ${positive ? "a number above 0" : "a number"}, got ${JSON.stringify(v)}.`);
  };
  const needVec = (where, v, n = 3) => {
    if (!vec(v, n)) err(where, `Expected ${n} numbers like [${n === 3 ? "x, y, z" : "x, y"}], got ${JSON.stringify(v)}.`);
  };
  const needHex = (where, v) => {
    if (typeof v !== "string" || !HEX.test(v)) err(where, `Expected a colour like "#ff8a3d", got ${JSON.stringify(v)}.`);
  };
  for (const key of Object.keys(s)) {
    if (!TOP.includes(key)) warn(key, `"${key}" is not a spec field, so it is ignored.`, `Known fields: ${TOP.join(", ")}.`);
  }
  if (typeof s.id !== "string" || !ID.test(s.id)) err("id", `id must be lowercase letters, digits and dashes, starting with a letter, like "sprout". Got ${JSON.stringify(s.id)}.`);
  if (typeof s.name !== "string" || !s.name) err("name", 'name is required: the display name, like "Sprout".');
  if (typeof s.tagline !== "string" || !s.tagline) warn("tagline", "tagline is missing: one line describing the character.");
  needHex("accent", s.accent);
  const frame = s.frame;
  if (!frame || typeof frame !== "object") err("frame", "frame is required: { target: <height the camera looks at>, radius: <half the visible height> }.", "Start with { target: 0.5, radius: 0.75 } for a mascot about 1 unit tall.");
  else {
    needNum("frame.target", frame.target);
    needNum("frame.radius", frame.radius, true);
  }
  const bound = s.bound;
  if (!bound || typeof bound !== "object") err("bound", "bound is required: { y: <centre height>, radius: <reach> }, a sphere that contains the whole body.", "Start with { y: 0.5, radius: 0.72 }.");
  else {
    needNum("bound.y", bound.y);
    needNum("bound.radius", bound.radius, true);
  }
  if (s.motion !== void 0) {
    if (typeof s.motion !== "object" || !s.motion) err("motion", "motion must be an object.");
    else for (const [k, v] of Object.entries(s.motion)) {
      if (!TEMPERAMENT.includes(k)) warn(`motion.${k}`, `"${k}" is not a motion setting.`, `Known: ${TEMPERAMENT.join(", ")}.`);
      else needNum(`motion.${k}`, v);
    }
  }
  const materials = s.materials ?? {};
  const materialNames = Object.keys(materials);
  if (typeof s.materials !== "object" || !materialNames.length) err("materials", 'materials is required: at least one named material, like { skin: { color: "#ffb38a" } }.');
  for (const [name, m] of Object.entries(materials)) {
    const at = `materials.${name}`;
    if (!m || typeof m !== "object") {
      err(at, "A material must be an object with at least a color.");
      continue;
    }
    needHex(`${at}.color`, m.color);
    for (const k of Object.keys(m)) if (!MATERIAL_KEYS.includes(k)) warn(`${at}.${k}`, `"${k}" is not a material setting, so it is ignored.`, `Known: ${MATERIAL_KEYS.join(", ")}.`);
    for (const k of ["f0", "spec", "shininess", "metal", "rim", "gloss", "sheen", "sss", "emitStrength"]) if (m[k] !== void 0) needNum(`${at}.${k}`, m[k]);
    for (const k of ["f0", "metal", "gloss"]) if (num(m[k]) && (m[k] < 0 || m[k] > 1)) warn(`${at}.${k}`, `${k} is meant to be between 0 and 1.`);
    for (const k of ["sssColor", "emit"]) if (m[k] !== void 0) needHex(`${at}.${k}`, m[k]);
    if (m.shadeOf !== void 0 && !materialNames.includes(m.shadeOf)) err(`${at}.shadeOf`, `shadeOf names "${m.shadeOf}", which is not a material.`);
    const surface = m.surface;
    if (surface !== void 0) {
      if (!SURFACES.includes(surface?.kind)) err(`${at}.surface.kind`, `surface.kind must be one of ${SURFACES.join(", ")}.`);
      needNum(`${at}.surface.scale`, surface?.scale, true);
    }
  }
  const boneNames = /* @__PURE__ */ new Set(["root"]);
  if (!Array.isArray(s.bones)) err("bones", 'bones is required: a list, usually starting with { name: "body", pivot: [0, 0, 0] }.');
  else s.bones.forEach((b, i) => {
    const at = `bones[${i}]`;
    if (typeof b?.name !== "string") return err(`${at}.name`, "Every bone needs a name.");
    if (boneNames.has(b.name)) err(`${at}.name`, `Bone "${b.name}" is declared twice${b.name === "root" ? ` ("root" is built in; don't declare it)` : ""}.`);
    const parent = b.parent ?? "root";
    if (!boneNames.has(parent)) err(`${at}.parent`, `Bone "${b.name}" names parent "${parent}", which is not declared before it. Declare parents first.`);
    boneNames.add(b.name);
    needVec(`${at}.pivot`, b.pivot);
    for (const field of ["rest", "drive", "wave"]) {
      const v = b[field];
      if (v === void 0) continue;
      for (const [axis, val] of Object.entries(v)) {
        if (!AXES2.includes(axis)) {
          err(`${at}.${field}.${axis}`, `"${axis}" is not an axis; use rx, ry or rz.`);
          continue;
        }
        if (field === "rest") needNum(`${at}.rest.${axis}`, val);
        if (field === "wave" && !vec(val, 3)) err(`${at}.wave.${axis}`, "A wave is [amplitude, hz, phase].");
        if (field === "drive") {
          if (!Array.isArray(val) || !val.every((d) => Array.isArray(d) && CHANNELS.includes(d[0]) && num(d[1]))) {
            err(`${at}.drive.${axis}`, `A drive is a list of [channel, weight] pairs, like [["yaw", 0.6]]. Channels: ${CHANNELS.join(", ")}.`);
          }
        }
      }
    }
    const j = b.jiggle;
    if (j !== void 0) {
      needVec(`${at}.jiggle.axis`, j?.axis);
      needNum(`${at}.jiggle.length`, j?.length, true);
      needNum(`${at}.jiggle.freq`, j?.freq, true);
      needNum(`${at}.jiggle.damping`, j?.damping, true);
    }
  });
  const needBone = (where, name) => {
    if (!boneNames.has(name)) err(where, `Names bone "${name}", which does not exist.`, `Bones: ${[...boneNames].join(", ")}.`);
  };
  const needMaterial = (where, name) => {
    if (!materialNames.includes(name)) err(where, `Names material "${name}", which does not exist.`, `Materials: ${materialNames.join(", ")}.`);
  };
  if (!Array.isArray(s.parts) || !s.parts.length) err("parts", "parts is required: at least one shape.");
  else s.parts.forEach((p, i) => {
    const at = `parts[${i}]`;
    needBone(`${at}.bone`, p?.bone);
    if (p?.shape !== "hem") needMaterial(`${at}.material`, p?.material);
    if (!SHAPES.includes(p?.shape)) return err(`${at}.shape`, `"${p?.shape}" is not a shape. Shapes: ${SHAPES.join(", ")}.`);
    if (p.at !== void 0) needVec(`${at}.at`, p.at);
    if (p.rot !== void 0) needVec(`${at}.rot`, p.rot);
    if (p.op !== void 0 && p.op !== "add" && p.op !== "sub") err(`${at}.op`, 'op is "add" (the default) or "sub".');
    if (p.op === "sub" && i === 0) err(`${at}.op`, "The first part cannot be a subtraction: there is nothing before it to cut.");
    if (p.blend !== void 0 && (!num(p.blend) || p.blend < 0)) err(`${at}.blend`, "blend is a distance, 0 or more (0.02\u20130.1 is typical).");
    if (p.clip !== void 0) {
      const c = p.clip;
      if (!vec(c?.normal, 3) || c.normal.every((x) => x === 0)) err(`${at}.clip.normal`, "clip.normal is a direction like [0, -1, 0] (keeps the top half).");
    }
    const size = {
      sphere: () => needNum(`${at}.radius`, p.radius, true),
      ellipsoid: () => vec(p.radii, 3) && p.radii.every((x) => x > 0) ? void 0 : err(`${at}.radii`, "radii are three sizes above 0: [x, y, z]."),
      roundBox: () => {
        if (!vec(p.half, 3) || !p.half.every((x) => x > 0)) err(`${at}.half`, "half is three half-sizes above 0: [x, y, z].");
        needNum(`${at}.round`, p.round);
      },
      capsule: () => {
        needVec(`${at}.from`, p.from);
        needVec(`${at}.to`, p.to);
        needNum(`${at}.radius`, p.radius, true);
      },
      roundCone: () => {
        needVec(`${at}.from`, p.from);
        needVec(`${at}.to`, p.to);
        needNum(`${at}.r1`, p.r1, true);
        needNum(`${at}.r2`, p.r2, true);
      },
      cylinder: () => {
        needNum(`${at}.radius`, p.radius, true);
        needNum(`${at}.half`, p.half, true);
        needNum(`${at}.round`, p.round);
      },
      frame: () => {
        needVec(`${at}.half`, p.half, 2);
        ["corner", "width", "depth"].forEach((k) => needNum(`${at}.${k}`, p[k], k !== "corner"));
      },
      plate: () => {
        needVec(`${at}.half`, p.half, 2);
        ["corner", "depth"].forEach((k) => needNum(`${at}.${k}`, p[k], k !== "corner"));
      },
      hem: () => ["y", "amplitude", "waves", "speed", "blend"].forEach((k) => needNum(`${at}.${k}`, p[k]))
    };
    size[p.shape]();
  });
  if (s.paints !== void 0 && !Array.isArray(s.paints)) err("paints", "paints must be a list.");
  else s.paints?.forEach((p, i) => {
    const at = `paints[${i}]`;
    needBone(`${at}.bone`, p?.bone);
    if (!Array.isArray(p?.on) || !p.on.length) err(`${at}.on`, 'on is the list of materials the paint may colour, like ["skin"].');
    else p.on.forEach((m, k) => needMaterial(`${at}.on[${k}]`, m));
    needHex(`${at}.color`, p?.color);
    needVec(`${at}.at`, p?.at);
    if (p?.kind === "sphere") needNum(`${at}.radius`, p.radius, true);
    else if (p?.kind === "ellipse") needVec(`${at}.radii`, p.radii, 2);
    else err(`${at}.kind`, 'kind is "sphere" (a ball of colour around at) or "ellipse" (projected along +z).');
  });
  const eyes = s.eyes;
  if (eyes !== void 0) {
    needBone("eyes.bone", eyes?.bone);
    if (!Array.isArray(eyes?.at) || eyes.at.length !== 2) err("eyes.at", "eyes.at is two points: [[-x, y, z], [x, y, z]].");
    else eyes.at.forEach((v, k) => needVec(`eyes.at[${k}]`, v));
    if (eyes?.kind === "ball") {
      needNum("eyes.radius", eyes.radius, true);
      needHex("eyes.iris", eyes.iris);
      needNum("eyes.irisSize", eyes.irisSize, true);
      needNum("eyes.pupilSize", eyes.pupilSize, true);
      needMaterial("eyes.lid", eyes.lid);
    } else if (eyes?.kind === "bead") {
      if (!vec(eyes.radii, 3) || !eyes.radii.every((x) => x > 0)) err("eyes.radii", "radii are three sizes above 0: [width, height, depth], like [0.03, 0.045, 0.02].");
      needMaterial("eyes.material", eyes.material);
    } else err("eyes.kind", 'eyes.kind is "ball" (white eyeballs with an iris and lids) or "bead" (glossy dark beads).');
  }
  const face = s.face;
  if (face !== void 0) {
    needBone("face.bone", face?.bone);
    if (face?.kind === "mouth") {
      if (!Array.isArray(face.on) || !face.on.length) err("face.on", 'face.on is the list of materials the mouth may be drawn on, like ["skin"].');
      else face.on.forEach((m, k) => needMaterial(`face.on[${k}]`, m));
      needVec("face.at", face.at);
      needNum("face.width", face.width, true);
      needHex("face.color", face.color);
      needHex("face.tongue", face.tongue);
    } else if (face?.kind === "screen") {
      needMaterial("face.material", face.material);
      needVec("face.center", face.center, 2);
      needVec("face.half", face.half, 2);
      needNum("face.cell", face.cell, true);
      needHex("face.color", face.color);
    } else err("face.kind", 'face.kind is "mouth" (a painted mouth) or "screen" (an LED face).');
  }
  const anchors = s.anchors ?? {};
  for (const [name, a] of Object.entries(anchors)) {
    needBone(`anchors.${name}.bone`, a?.bone);
    needVec(`anchors.${name}.at`, a?.at);
  }
  for (const [expression, perBone] of Object.entries(s.acting ?? {})) {
    if (!EXPRESSIONS.includes(expression)) {
      err(`acting.${expression}`, `"${expression}" is not a state.`, `States: ${EXPRESSIONS.join(", ")}.`);
      continue;
    }
    for (const [bone, axes] of Object.entries(perBone ?? {})) {
      needBone(`acting.${expression}.${bone}`, bone);
      for (const [axis, motion] of Object.entries(axes ?? {})) {
        const where = `acting.${expression}.${bone}.${axis}`;
        if (!AXES2.includes(axis)) err(where, `"${axis}" is not an axis; use rx, ry or rz.`);
        else if (!num(motion) && !(Array.isArray(motion) && motion.length >= 1 && motion.length <= 5 && motion.every(num))) {
          err(where, "A motion is a number (a held angle) or [base, amplitude, hz, phase, spin].");
        } else if (Math.abs(Array.isArray(motion) ? motion[0] : motion) + Math.abs(Array.isArray(motion) ? motion[1] ?? 0 : 0) > 3.3) {
          warn(where, "This turns more than 3.3 radians (about 190\xB0), which tends to look broken. Spins belong in the fifth number, spin.");
        }
      }
    }
  }
  const fx = s.fx ?? {};
  for (const [trigger, list] of Object.entries(fx)) {
    if (trigger === "replace") continue;
    const base = trigger.startsWith("enter:") ? trigger.slice(6) : trigger;
    if (!["ambient", "land", "syllable"].includes(trigger) && !EXPRESSIONS.includes(base)) {
      err(`fx.${trigger}`, `"${trigger}" is not a trigger.`, `Use a state name, "enter:<state>", "ambient", "land" or "syllable".`);
      continue;
    }
    if (!Array.isArray(list)) {
      err(`fx.${trigger}`, "Each trigger takes a list of emitters.");
      continue;
    }
    list.forEach((e, i) => {
      const at = `fx.${trigger}[${i}]`;
      if (!GLYPHS.includes(e?.glyph)) err(`${at}.glyph`, `"${e?.glyph}" is not a glyph.`, `Glyphs: ${GLYPHS.join(", ")}.`);
      if (!anchors[e?.anchor]) err(`${at}.anchor`, `Names anchor "${e?.anchor}", which does not exist.`, `Anchors: ${Object.keys(anchors).join(", ") || "none yet"}.`);
      needNum(`${at}.rate`, e?.rate, true);
      needVec(`${at}.velocity`, e?.velocity);
      needVec(`${at}.life`, e?.life, 2);
      needVec(`${at}.size`, e?.size, 2);
      needHex(`${at}.color`, e?.color);
    });
  }
  return issues;
}

// ../engine/src/check/check.ts
var SAMPLES = 260;
var SIGHT_SAMPLES = 48;
var EPS = 4e-3;
var r3 = (n) => Math.round(n * 1e3) / 1e3;
var r2 = (n) => Math.round(n * 100) / 100;
var fmt = (v) => `[${v.map(r3).join(", ")}]`;
var up2 = (n) => Math.ceil(n * 100) / 100;
function describePart(spec, i) {
  const p = spec.parts[i];
  return `parts[${i}] (${p.shape}, ${p.material} on ${p.bone})`;
}
function checkCharacter(spec) {
  const issues = validate(spec);
  const base = {
    id: String(spec?.id ?? "?"),
    name: String(spec?.name ?? "?"),
    parts: [],
    closeup: { target: Number(spec?.frame?.target) || 0.5, radius: (Number(spec?.frame?.radius) || 0.8) * 0.5 },
    extents: null,
    suggested: null,
    stats: {
      parts: Array.isArray(spec?.parts) ? spec.parts.length : 0,
      bones: Array.isArray(spec?.bones) ? spec.bones.length + 1 : 0,
      materials: spec?.materials ? Object.keys(spec.materials).length : 0,
      bytes: JSON.stringify(spec ?? {}).length
    }
  };
  const done = (more = {}) => {
    const all = [...issues, ...more.issues ?? []];
    const rank = { error: 0, warning: 1, note: 2 };
    all.sort((a, b) => rank[a.level] - rank[b.level]);
    return { ...base, ...more, issues: all, ok: !all.some((i) => i.level === "error") };
  };
  if (issues.some((i) => i.level === "error")) return done();
  let field;
  try {
    field = new Field(spec);
  } catch (e) {
    issues.push({ level: "error", where: "spec", message: e instanceof SpecError ? e.message.replace(/^[^:]+: /, "") : String(e) });
    return done();
  }
  const found = [];
  const add2 = (level, where, message, fix) => found.push({ level, where, message, fix });
  const random = rng(0.37);
  const exposed = [];
  const reports = [];
  const surfaces = /* @__PURE__ */ new Map();
  const backOnly = [];
  const rest = field.posed;
  const moving = [
    pose(field.r, "speaking", 0.2, { talk: 1 }),
    pose(field.r, "celebrating", 0.4, { flap: 1, talk: 1 }),
    pose(field.r, "surprised", 0.3, { talk: 0.6 }),
    pose(field.r, "sad", 0.3),
    pose(field.r, "sleeping", 0.3)
  ];
  spec.parts.forEach((part, i) => {
    const box = partBox(part);
    if (!box || part.op === "sub") return;
    const local = surfaceSamples(field, i, box, random);
    if (!local.length) {
      add2("warning", `parts[${i}]`, `${describePart(spec, i)} has no surface to measure; check its sizes are above zero and its clip does not cut it away entirely.`);
      return;
    }
    const samples = local.map((l) => field.fromPart(i, l));
    surfaces.set(i, samples);
    let shows = 0;
    let buried = 0;
    let pull = 0;
    const containers = /* @__PURE__ */ new Map();
    const mine = [];
    for (const p of samples) {
      const others = field.map(p, i).d;
      const final = field.map(p).d;
      pull = Math.max(pull, others - final);
      if (others < -EPS) {
        buried++;
        const j = container(field, i, p);
        if (j >= 0) containers.set(j, (containers.get(j) ?? 0) + 1);
      } else if (final <= EPS) {
        shows++;
        const bone = field.parts[i].bone;
        mine.push({ part: i, bone, local: field.toBone(bone, p), world: p });
      }
    }
    exposed.push(...mine);
    const sight = mine.filter((_, k) => k % Math.max(1, Math.floor(mine.length / SIGHT_SAMPLES)) === 0).slice(0, SIGHT_SAMPLES);
    const seenCount = sight.filter((s) => field.visible(s.world)).length;
    const report = { index: i, shows: shows / samples.length, seen: sight.length ? seenCount / sight.length * (shows / samples.length) : 0 };
    reports.push(report);
    const shaping = (part.blend ?? 0) > 0 && pull > 3e-3;
    const hidden = shows === 0 && buried > 0;
    const sliver = !hidden && report.shows < 0.04 && buried > 0 && !shaping;
    if ((hidden || sliver) && !shaping) {
      let best = report.shows;
      for (const posed of moving) {
        field.posed = posed;
        const out = local.filter((l) => {
          const p = field.fromPart(i, l);
          return field.map(p, i).d >= -EPS && field.map(p).d <= EPS;
        }).length;
        best = Math.max(best, out / local.length);
      }
      field.posed = rest;
      if (best >= 0.04) return;
    }
    const main2 = [...containers.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
    const inside = main2 !== void 0 ? ` inside ${describePart(spec, main2)}` : " inside the body";
    if (hidden) {
      if (shaping) {
        add2("note", `parts[${i}]`, `${describePart(spec, i)} is buried${inside}; it only rounds out the surface through its blend.`);
      } else {
        const out = escape(field, i, samples);
        add2(
          "error",
          `parts[${i}]`,
          `${describePart(spec, i)} is completely hidden${inside}, so it never shows.`,
          out ? `Move it outward: at ${fmt(out.at)} would bring it to the surface (that is ${r3(out.distance)} along ${out.axis}). Or make it larger.` : "Move it outward or make it larger."
        );
      }
    } else if (sliver) {
      add2("warning", `parts[${i}]`, `${describePart(spec, i)} is ${Math.round((1 - report.shows) * 100)}% buried${inside}; only a sliver shows.`, "If it should read clearly, move it outward or make it larger.");
    } else if (report.shows > 0 && seenCount === 0 && sight.length >= 4) {
      backOnly.push(i);
    }
  });
  if (backOnly.length) {
    add2("note", "parts", `Not visible from the front (on the back, or covered): ${backOnly.map((i) => `parts[${i}] (${spec.parts[i].material})`).join(", ")}. Fine for tails and backs; not for anything the viewer should notice.`);
  }
  floating(field, surfaces).forEach(({ parts, gap, from, to }) => {
    const names = parts.map((i) => `parts[${i}]`);
    const bone = field.parts[parts[0]].bone;
    const a = field.toBone(bone, from);
    const b = field.toBone(bone, to);
    const len = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]) || 1;
    const k = (gap + 0.012) / len;
    const shift = [(b[0] - a[0]) * k, (b[1] - a[1]) * k, (b[2] - a[2]) * k];
    const moved = parts.map((i) => {
      const at = field.parts[i].at;
      return `parts[${i}].at ${fmt([at[0] + shift[0], at[1] + shift[1], at[2] + shift[2]])}`;
    });
    add2(
      "warning",
      names.length === 1 ? names[0] : names.join(", "),
      `${parts.length === 1 ? describePart(spec, parts[0]) : `${describePart(spec, parts[0])} and ${parts.length - 1} more`} ${parts.length === 1 ? "floats" : "float"} free of the body: the nearest gap is ${r3(gap)}, so it looks detached from every angle.`,
      `Move it ${fmt(shift.map(r3))} in ${spec.parts[parts[0]].bone}'s space so it overlaps the body: ${moved.join(", ")}. If the whole bone is detached, move the bone's pivot by the same amount instead.`
    );
  });
  spec.parts.forEach((part, i) => {
    if (part.op !== "sub") return;
    const box = partBox(part);
    if (!box) return;
    const thin = Math.min(...[0, 1, 2].map((k) => (box[1][k] - box[0][k]) / 2));
    const samples = [0, Math.min(6e-3, thin * 0.3)].flatMap((inset) => surfaceSamples(field, i, box, random, inset).map((l) => field.fromPart(i, l)));
    const carves = samples.some((p) => field.map(p, i).d < 0 && field.map(p).d > field.map(p, i).d + 2e-4);
    if (carves) return;
    const later = spec.parts.findIndex((q, j) => j > i && q.op !== "sub" && q.shape !== "hem" && samples.some((p) => field.partDistance(j, p) < 0));
    add2(
      "warning",
      `parts[${i}]`,
      `${describePart(spec, i)} is a subtraction that cuts nothing.`,
      later >= 0 ? `A subtraction only cuts parts listed before it, and the part it overlaps, parts[${later}], comes after. Move the subtraction after parts[${later}].` : (() => {
        const bone = field.parts[i].bone;
        const near = project(field, field.toWorld(bone, part.at ?? [0, 0, 0]));
        return near ? `It does not reach any part. The nearest surface is at ${fmt(field.toBone(bone, near))} (in ${part.bone}'s space); centre it there, or a little inside, to carve.` : "It does not overlap any part. Move it into the part it should carve.";
      })()
    );
  });
  let extents = null;
  let suggested = null;
  if (exposed.length) {
    const min = [Infinity, Infinity, Infinity];
    const max = [-Infinity, -Infinity, -Infinity];
    for (const s of exposed) for (let k = 0; k < 3; k++) {
      min[k] = Math.min(min[k], s.world[k]);
      max[k] = Math.max(max[k], s.world[k]);
    }
    extents = { min, max };
    const hover = spec.motion?.float ?? 0;
    let lo = min[1], hi = max[1];
    const by = spec.bound.y + hover;
    let worst = { d: 0, state: "idle", part: -1 };
    const step = Math.max(1, Math.floor(exposed.length / 900));
    for (const state of STATES) {
      for (const t of [0, 0.35, 0.7, 1.05]) {
        const posed = pose(field.r, state, t);
        for (let k = 0; k < exposed.length; k += step) {
          const s = exposed[k];
          const w = transformPoint(posed.world[s.bone], s.local);
          lo = Math.min(lo, w[1]);
          hi = Math.max(hi, w[1]);
          const d = Math.hypot(w[0], w[1] - by, w[2]);
          if (d > worst.d) worst = { d, state, part: s.part };
        }
      }
    }
    const boundY = r2((lo + hi) / 2 - hover);
    let boundR = 0;
    for (const state of STATES) {
      const posed = pose(field.r, state, 0.5);
      for (let k = 0; k < exposed.length; k += step) {
        const s = exposed[k];
        const w = transformPoint(posed.world[s.bone], s.local);
        boundR = Math.max(boundR, Math.hypot(w[0], w[1] - hover - boundY, w[2]));
      }
    }
    boundR = up2(Math.max(boundR, worst.d - Math.abs(boundY + hover - by)) + 0.05);
    const halfW = Math.max(Math.abs(min[0]), Math.abs(max[0]));
    const low = Math.min(min[1], 0);
    const high = max[1] + (hover > 0 ? 0.05 : 0);
    const target = r2((low + high) / 2 + 0.02);
    const frameR = up2(Math.max(halfW, (high - low) / 2) * 1.3 + 0.04);
    suggested = { bound: { y: boundY, radius: boundR }, frame: { target, radius: frameR } };
    if (worst.d > spec.bound.radius + 0.012) {
      add2(
        worst.d > spec.bound.radius + 0.03 ? "error" : "warning",
        "bound",
        `${describePart(spec, worst.part)} reaches ${r3(worst.d)} from the bound's centre in "${worst.state}", past bound.radius ${spec.bound.radius}, so it gets sliced off there.`,
        `Set bound to { y: ${boundY}, radius: ${boundR} }.`
      );
    } else if (spec.bound.radius > boundR * 1.6 + 0.05) {
      add2("note", "bound", `bound.radius ${spec.bound.radius} is much larger than the body needs; a tighter bound renders faster.`, `bound: { y: ${boundY}, radius: ${boundR} }`);
    }
    const f = spec.frame;
    const top = max[1] - f.target, bottom = f.target - min[1];
    const over = Math.max(halfW, top, bottom) - f.radius;
    if (over > 5e-3) {
      const side = halfW - f.radius > 5e-3 ? "the sides" : top > bottom ? "the top" : "the bottom";
      add2("error", "frame", `The body is cut off at ${side} of the picture: it reaches ${r3(over)} past frame.radius ${f.radius}.`, `frame: { target: ${target}, radius: ${frameR} }`);
    } else if (Math.max(halfW, (max[1] - min[1]) / 2) < f.radius * 0.5) {
      add2("warning", "frame", `The body fills less than half the picture, so it will look small and far away.`, `frame: { target: ${target}, radius: ${frameR} }`);
    } else if (Math.abs((min[1] + max[1]) / 2 - f.target) > f.radius * 0.28) {
      add2("warning", "frame", `frame.target ${f.target} is far from the body's middle height (${r2((min[1] + max[1]) / 2)}), so it sits off-centre.`, `frame: { target: ${target}, radius: ${frameR} }`);
    }
    if (hover > 0 && min[1] < 0.02) {
      add2("warning", "parts", `Even hovering at motion.float ${hover}, the lowest point is at height ${r3(min[1])}, so it scrapes the floor.`, `Move the parts up by ${r3(0.05 - min[1])}, or raise motion.float.`);
    } else if (hover === 0 && min[1] > 0.035) {
      add2("warning", "parts", `The lowest point of the body is ${r3(min[1])} above the floor, so it hovers, but motion.float is 0.`, `Move the parts down by ${r3(min[1])} (or add feet), or set motion.float if it should hover.`);
    } else if (hover === 0 && min[1] < -0.03) {
      add2("warning", "parts", `The body dips ${r3(-min[1])} below the floor (y = 0), so its base disappears into the shadow.`, `Move the parts up by ${r3(-min[1])}, or flatten the base with a clip.`);
    }
  }
  const eyes = spec.eyes;
  if (eyes) {
    const bone = field.r.boneIndex(eyes.bone, "eyes");
    const depth = eyes.kind === "ball" ? eyes.radius : eyes.radii[2];
    const [a, b] = eyes.at;
    if (a[0] > b[0]) add2("warning", "eyes.at", "eyes.at[0] is to the right of eyes.at[1]. List the left eye (negative x) first; winks and glances depend on it.");
    if (Math.abs(a[0] + b[0]) > 0.015 || Math.abs(a[1] - b[1]) > 0.015 || Math.abs(a[2] - b[2]) > 0.015) {
      add2("warning", "eyes.at", `The eyes are not mirror images (${fmt(a)} and ${fmt(b)}), so the face looks lopsided.`, `Use [-x, y, z] and [x, y, z] with the same y and z.`);
    }
    eyes.at.forEach((at, e) => {
      const where = `eyes.at[${e}]`;
      if (at[2] <= 0) {
        add2("error", where, `This eye is at z ${at[2]}, on the back half of the head. Characters face +z, toward the camera.`, "Use a positive z, on the front of the face.");
        return;
      }
      const surface = skinAlongZ(field, bone, at);
      if (surface === null) {
        add2("error", where, "There is no head behind this eye: it floats in the air.", "Move it onto the face: give it the x and y of a point on the head.");
        return;
      }
      const front = at[2] + depth - surface;
      const want = eyes.kind === "ball" ? surface - depth * 0.7 : surface - depth * 0.3;
      const fixed = [at[0], at[1], r3(want)];
      if (front <= 2e-3) {
        add2("error", where, `This eye is buried ${r3(-front + 2e-3)} inside the head, so it cannot be seen.`, `Move it forward to at ${fmt(fixed)} (the face's surface is at z ${r3(surface)} there).`);
      } else if (at[2] - depth > surface + 4e-3) {
        add2("error", where, `This eye floats ${r3(at[2] - depth - surface)} in front of the face.`, `Move it back to at ${fmt(fixed)} (the face's surface is at z ${r3(surface)} there).`);
      } else if (front < depth * (eyes.kind === "ball" ? 0.08 : 0.25)) {
        add2("warning", where, `This eye barely pokes out of the face (${r3(front)}), so it reads as a dent.`, `Move it forward to at ${fmt(fixed)}.`);
      } else if (eyes.kind === "bead" && front > depth * 1.9) {
        add2("warning", where, `This bead eye stands almost entirely in front of the face, so it looks stuck on.`, `Move it back to at ${fmt(fixed)}.`);
      } else {
        const tip = field.toWorld(bone, [at[0], at[1], at[2] + depth * 0.9]);
        const sees = field.march(field.camera(), tip, true, 1e-3);
        if (sees && Math.hypot(sees.at[0] - tip[0], sees.at[1] - tip[1], sees.at[2] - tip[2]) > depth * 1.5) {
          add2("warning", where, `Something in front covers this eye from the camera: ${field.materialName(sees.hit.id)}.`, "Move the eye or the part in front of it.");
        }
      }
    });
  }
  spec.paints?.forEach((paint, i) => {
    const where = `paints[${i}]`;
    const bone = field.r.boneIndex(paint.bone, where);
    if (paint.kind === "sphere") {
      const radius = paint.radius ?? 0.1;
      const centre = field.toWorld(bone, paint.at);
      const d = field.map(centre).d;
      const reach = radius * (1 + (paint.soft ?? 0.15));
      const onSkin = project(field, centre);
      const hint = onSkin ? ` Its nearest surface point is at ${fmt(field.toBone(bone, onSkin))}.` : "";
      if (Math.abs(d) > reach) {
        add2(
          "error",
          where,
          `This paint never touches a surface: its centre is ${r3(Math.abs(d))} ${d < 0 ? "inside" : "outside"} the body, more than its radius ${radius}.`,
          onSkin ? `Move it to at ${fmt(field.toBone(bone, onSkin))}, on the surface.` : "Move its centre onto the surface."
        );
      } else if (Math.abs(d) > radius * 0.9) {
        add2("warning", where, `Only the very edge of this paint reaches the surface (its centre is ${r3(Math.abs(d))} ${d < 0 ? "inside" : "outside"} the body, radius ${radius}), so it shows as a faint speck.${hint}`);
      } else {
        const lands = paintLands(field, centre, radius);
        if (lands.size && ![...lands].some((m) => paint.on.includes(m))) {
          const name = [...lands][0];
          add2("warning", where, `This paint only meets "${[...lands].join('", "')}", not its on: [${paint.on.join(", ")}], so it does not show.`, `Add "${name}" to on, or move it.`);
        }
      }
    } else {
      const [rx, ry] = paint.radii ?? [0.1, 0.1];
      const ring = (s) => [0, 1, 2, 3, 4, 5, 6, 7].map((k) => [paint.at[0] + Math.cos(k * 0.785) * rx * s, paint.at[1] + Math.sin(k * 0.785) * ry * s, paint.at[2]]);
      const probes = [paint.at, ...ring(0.6), ...ring(0.9)];
      const hits = probes.map((q) => alongZ(field, bone, q)).filter((h) => !!h);
      const painted = hits.filter((h) => h.z > paint.at[2]);
      if (!hits.length) {
        add2("error", where, "There is no surface in front of or behind this ellipse paint.", "Move its x and y onto the body.");
      } else if (!painted.length) {
        const z = Math.min(...hits.map((h) => h.z));
        add2("error", where, `An ellipse paint colours only surface in front of its at.z (${paint.at[2]}), but the surface here is at z ${r3(z)}, behind it, so nothing is painted.`, `Set at.z below ${r3(z)}, e.g. ${r3(z - 0.08)}.`);
      } else if (!painted.some((h) => paint.on.includes(h.material))) {
        add2("warning", where, `This ellipse paint lands on "${painted[0].material}", which is not in its on: [${paint.on.join(", ")}].`, `Add "${painted[0].material}" to on, or move it.`);
      }
    }
  });
  const face = spec.face;
  if (face?.kind === "mouth") {
    const bone = field.r.boneIndex(face.bone, "face");
    const w = face.width;
    const probes = [-1, -0.5, 0, 0.5, 1].flatMap((u) => [-0.3, 0, 0.3].map((v) => [face.at[0] + u * w, face.at[1] + v * w, face.at[2]]));
    const hits = probes.map((q) => alongZ(field, bone, q)).filter((h) => !!h);
    const drawn = hits.filter((h) => h.z >= face.at[2] - 0.02 && face.on.includes(h.material));
    const centre = alongZ(field, bone, face.at);
    if (!hits.length || !centre) {
      add2("error", "face.at", "There is no surface behind the mouth: it floats in the air.", "Move face.at onto the front of the head.");
    } else if (!hits.some((h) => face.on.includes(h.material))) {
      add2("error", "face.on", `The mouth lands on "${centre.material}", which is not in face.on [${face.on.join(", ")}], so no mouth appears.`, `Add "${centre.material}" to face.on.`);
    } else if (!drawn.length) {
      add2("error", "face.at", `The mouth is drawn only on surface less than 0.02 behind face.at, but the face here is ${r3(face.at[2] - centre.z)} further back, so no mouth appears.`, `Set face.at to ${fmt([face.at[0], face.at[1], r3(centre.z)])}.`);
    } else if (drawn.length < hits.length * 0.4) {
      const deepest = Math.min(...hits.filter((h) => face.on.includes(h.material)).map((h) => h.z));
      add2("warning", "face.at", `Only part of the mouth lands on the face (${drawn.length} of ${hits.length} points), so it shows broken or shortened.`, `Set face.at to ${fmt([face.at[0], face.at[1], r3(deepest + 0.012)])}.`);
    } else if (!field.visible(field.toWorld(bone, [face.at[0], face.at[1], centre.z]))) {
      add2("warning", "face.at", "The camera cannot see where the mouth is drawn.", "Move it onto the front of the face.");
    }
    if (eyes) {
      const eyeY = Math.min(...eyes.at.map((at) => field.toWorld(field.r.boneIndex(eyes.bone, "eyes"), at)[1]));
      const mouthY = field.toWorld(bone, face.at)[1];
      if (mouthY > eyeY) add2("warning", "face.at", "The mouth is above the eyes.", "Put the mouth below the eyes, usually 0.06\u20130.12 lower.");
    }
  }
  const anchors = spec.anchors ?? {};
  const needs = [
    ["top", "thinking, working, celebrating, sad and sleeping effects", "warning"],
    ["mouth", "speaking effects", "warning"],
    ["ear", "listening effects", "note"],
    ["feet", "the landing puff after a hop", "note"]
  ];
  for (const [name, what, level] of needs) {
    if (!anchors[name] && !spec.fx?.replace?.length) add2(level, `anchors.${name}`, `There is no "${name}" anchor, so ${what} are skipped.`, `Add anchors.${name}: { bone, at }.`);
  }
  for (const [name, a] of Object.entries(anchors)) {
    if (name !== "top" && name !== "mouth") continue;
    const bone = field.r.boneIndex(a.bone, `anchors.${name}`);
    const d = field.map(field.toWorld(bone, a.at)).d;
    if (d < -0.06) add2("warning", `anchors.${name}`, `The "${name}" anchor is ${r3(-d)} deep inside the body, so effects from it start out hidden.`, name === "top" ? "Put it on or just above the top of the head." : "Move it onto the surface.");
  }
  const usedMaterials = /* @__PURE__ */ new Set([
    ...spec.parts.map((p) => p.material),
    ...spec.eyes?.kind === "ball" ? [spec.eyes.lid] : spec.eyes ? [spec.eyes.material] : [],
    ...spec.face?.kind === "screen" ? [spec.face.material] : [],
    ...Object.values(spec.materials).map((m) => m.shadeOf).filter((x) => !!x)
  ]);
  for (const name of Object.keys(spec.materials)) {
    if (!usedMaterials.has(name)) add2("note", `materials.${name}`, `Material "${name}" is not used by any part.`);
  }
  const usedBones = /* @__PURE__ */ new Set([
    ...spec.parts.map((p) => p.bone),
    ...(spec.paints ?? []).map((p) => p.bone),
    ...spec.eyes ? [spec.eyes.bone] : [],
    ...spec.face ? [spec.face.bone] : [],
    ...Object.values(anchors).map((a) => a.bone),
    ...spec.bones.map((b) => b.parent ?? "root")
  ]);
  for (const b of spec.bones) if (!usedBones.has(b.name)) add2("note", `bones`, `Bone "${b.name}" moves nothing: no part, paint, eye, face, anchor or child bone uses it.`);
  if (spec.parts.length > 48) add2("warning", "parts", `${spec.parts.length} parts is a lot; every part costs shader time on every pixel. Try to stay under 40.`);
  let closeup = base.closeup;
  if (eyes) {
    const bone = field.r.boneIndex(eyes.bone, "eyes");
    const [a, b] = eyes.at.map((at) => field.toWorld(bone, at));
    const spread = Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    closeup = { target: r3((a[1] + b[1]) / 2 - 0.04), radius: r3(Math.max(0.16, spread * 1.6)) };
  }
  return done({ issues: found, parts: reports, extents, suggested, closeup });
}
function surfaceSamples(field, i, box, random, inset = 0) {
  const out = [];
  const [lo, hi] = box;
  const pad = 0.1;
  for (let n = 0; n < SAMPLES; n++) {
    let l = [0, 1, 2].map((k) => {
      const span = hi[k] - lo[k];
      return lo[k] - span * pad + random() * span * (1 + 2 * pad);
    });
    let d = 0;
    for (let it = 0; it < 8; it++) {
      d = field.localDistance(i, l);
      const g = gradient((q) => field.localDistance(i, q), l);
      const g2 = g[0] * g[0] + g[1] * g[1] + g[2] * g[2];
      if (!(g2 > 1e-12)) break;
      const s = (d + inset) / g2;
      l = [l[0] - g[0] * s, l[1] - g[1] * s, l[2] - g[2] * s];
    }
    if (Math.abs(field.localDistance(i, l) + inset) < 1e-3) out.push(l);
  }
  return out;
}
function gradient(fn, p) {
  const e = 5e-4;
  return [0, 1, 2].map((k) => {
    const a = [p[0], p[1], p[2]];
    const b = [p[0], p[1], p[2]];
    a[k] += e;
    b[k] -= e;
    return (fn(a) - fn(b)) / (2 * e);
  });
}
function container(field, i, p) {
  let best = -1;
  let deepest = 0;
  field.spec.parts.forEach((q, j) => {
    if (j === i || q.op === "sub" || q.shape === "hem") return;
    const d = field.partDistance(j, p);
    if (d < deepest) {
      deepest = d;
      best = j;
    }
  });
  return best;
}
function paintLands(field, centre, radius) {
  const out = /* @__PURE__ */ new Set();
  const dirs = [[0, 0, 0], [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1], [0.7, 0.7, 0], [-0.7, 0.7, 0], [0.7, -0.7, 0], [-0.7, -0.7, 0]];
  for (const d of dirs) {
    const q = project(field, [centre[0] + d[0] * radius * 0.6, centre[1] + d[1] * radius * 0.6, centre[2] + d[2] * radius * 0.6]);
    if (q && Math.hypot(q[0] - centre[0], q[1] - centre[1], q[2] - centre[2]) <= radius) out.add(field.materialName(field.map(q).id));
  }
  return out;
}
function floating(field, surfaces) {
  const ids = [...surfaces.keys()];
  if (ids.length < 2) return [];
  const parent = new Map(ids.map((i) => [i, i]));
  const root = (i) => parent.get(i) === i ? i : root(parent.get(i));
  const reach = (i, j) => {
    let best = Infinity;
    for (const p of surfaces.get(i)) best = Math.min(best, field.partDistance(j, p));
    return best;
  };
  for (const i of ids) {
    for (const j of ids) {
      if (j <= i || root(i) === root(j)) continue;
      const touch = Math.max(0.015, field.parts[i].spec.blend ?? 0, field.parts[j].spec.blend ?? 0);
      if (reach(i, j) < touch || reach(j, i) < touch) parent.set(root(j), root(i));
    }
  }
  const body = root(ids[0]);
  const groups = /* @__PURE__ */ new Map();
  for (const i of ids) if (root(i) !== body) groups.set(root(i), [...groups.get(root(i)) ?? [], i]);
  return [...groups.values()].map((parts) => {
    let gap = Infinity;
    let from = [0, 0, 0];
    let to = [0, 0, 0];
    for (const i of parts) {
      for (const p of surfaces.get(i)) {
        let d = Infinity;
        let j = -1;
        for (const k of ids) {
          if (parts.includes(k)) continue;
          const dk = field.partDistance(k, p);
          if (dk < d) d = dk, j = k;
        }
        if (d < gap && j >= 0) {
          gap = d;
          from = p;
          const e = 6e-4;
          const g = [0, 1, 2].map((a) => {
            const q1 = [p[0], p[1], p[2]];
            const q2 = [p[0], p[1], p[2]];
            q1[a] += e;
            q2[a] -= e;
            return field.partDistance(j, q1) - field.partDistance(j, q2);
          });
          const n = Math.hypot(...g) || 1;
          to = [p[0] - g[0] / n * d, p[1] - g[1] / n * d, p[2] - g[2] / n * d];
        }
      }
    }
    return { parts: parts.sort((a, b) => a - b), gap, from, to };
  });
}
function project(field, p) {
  let q = [p[0], p[1], p[2]];
  for (let it = 0; it < 12; it++) {
    const d = field.map(q).d;
    if (Math.abs(d) < 3e-4) return q;
    const n = field.normal(q);
    q = [q[0] - n[0] * d, q[1] - n[1] * d, q[2] - n[2] * d];
  }
  return Math.abs(field.map(q).d) < 2e-3 ? q : null;
}
function escape(field, i, samples) {
  const part = field.parts[i];
  const at = part.at;
  const axes = [["+z", [0, 0, 1]], ["+y", [0, 1, 0]], ["-x", [-1, 0, 0]], ["+x", [1, 0, 0]], ["-y", [0, -1, 0]], ["-z", [0, 0, -1]]];
  let best = null;
  const local = samples.map((p) => field.toBone(part.bone, p));
  for (const [name, dir] of axes) {
    for (let t = 0.01; t <= 0.4; t += 0.01) {
      let clear = 0;
      for (const l of local) {
        const w = field.toWorld(part.bone, [l[0] + dir[0] * t, l[1] + dir[1] * t, l[2] + dir[2] * t]);
        if (field.map(w, i).d > 0) clear++;
      }
      if (clear >= local.length * 0.2) {
        if (!best || t < best.distance) best = { at: [at[0] + dir[0] * (t + 5e-3), at[1] + dir[1] * (t + 5e-3), at[2] + dir[2] * (t + 5e-3)], distance: t + 5e-3, axis: name };
        break;
      }
    }
  }
  return best;
}
function skinAlongZ(field, bone, at) {
  const from = field.toWorld(bone, [at[0], at[1], at[2] + 1.5]);
  const to = field.toWorld(bone, [at[0], at[1], at[2] - 1.5]);
  const hit = field.march(from, to, false, 4e-4);
  return hit ? field.toBone(bone, hit.at)[2] : null;
}
function alongZ(field, bone, at) {
  const from = field.toWorld(bone, [at[0], at[1], at[2] + 1.5]);
  const to = field.toWorld(bone, [at[0], at[1], at[2] - 1.5]);
  const hit = field.march(from, to, true, 4e-4);
  return hit ? { z: field.toBone(bone, hit.at)[2], material: field.materialName(hit.hit.id) } : null;
}
var MARK = { error: "\u2716 error  ", warning: "\u25B2 warning", note: "\xB7 note   " };
function formatCheck(report) {
  const lines = [`${report.name} (${report.id}): ${report.stats.parts} parts, ${report.stats.bones} bones, ${report.stats.materials} materials, ${(report.stats.bytes / 1024).toFixed(1)} KB of spec`];
  for (const issue of report.issues) {
    lines.push(`${MARK[issue.level]} ${issue.where}: ${issue.message}`);
    if (issue.fix) lines.push(`            fix: ${issue.fix}`);
  }
  const counts = ["error", "warning", "note"].map((l) => [l, report.issues.filter((i) => i.level === l).length]);
  if (!report.issues.length) lines.push("\u2713 No problems found.");
  else lines.push(counts.map(([l, n]) => `${n} ${l}${n === 1 ? "" : "s"}`).join(", ") + (report.ok ? ". No errors." : "."));
  return lines.join("\n");
}
var env = process.env;
function candidates() {
  const own = [env.WOBNIMO_BROWSER, env.CHROME_PATH, env.PUPPETEER_EXECUTABLE_PATH].filter((p) => !!p);
  const playwright = playwrightChromium();
  if (process.platform === "darwin") {
    const apps = ["Google Chrome", "Google Chrome Canary", "Chromium", "Microsoft Edge", "Brave Browser", "Arc", "Vivaldi"];
    const roots = ["/Applications", join(homedir(), "Applications")];
    const bins = { Arc: "Arc", "Brave Browser": "Brave Browser", Vivaldi: "Vivaldi" };
    return [...own, ...roots.flatMap((r) => apps.map((a) => join(r, `${a}.app`, "Contents", "MacOS", bins[a] ?? a))), ...playwright];
  }
  if (process.platform === "win32") {
    const roots = [env.PROGRAMFILES, env["PROGRAMFILES(X86)"], env.LOCALAPPDATA].filter((p) => !!p);
    const rel = ["Google\\Chrome\\Application\\chrome.exe", "Microsoft\\Edge\\Application\\msedge.exe", "BraveSoftware\\Brave-Browser\\Application\\brave.exe", "Chromium\\Application\\chrome.exe"];
    return [...own, ...roots.flatMap((r) => rel.map((p) => join(r, p))), ...playwright];
  }
  const names = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "microsoft-edge-stable", "brave-browser"];
  const dirs = (env.PATH ?? "").split(delimiter).filter(Boolean);
  return [...own, ...names.flatMap((n) => dirs.map((d) => join(d, n))), "/snap/bin/chromium", ...playwright];
}
function playwrightChromium() {
  const roots = [
    env.PLAYWRIGHT_BROWSERS_PATH,
    process.platform === "darwin" ? join(homedir(), "Library", "Caches", "ms-playwright") : "",
    process.platform === "win32" ? join(env.LOCALAPPDATA ?? "", "ms-playwright") : join(homedir(), ".cache", "ms-playwright")
  ].filter((r) => !!r && existsSync(r));
  const out = [];
  for (const root of roots) {
    const builds = readdirSync(root).filter((d) => /^chromium(-\d+)?$/.test(d)).sort().reverse();
    for (const b of builds) {
      out.push(
        join(root, b, "chrome-linux", "chrome"),
        join(root, b, "chrome-linux64", "chrome"),
        join(root, b, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"),
        join(root, b, "chrome-mac-arm64", "Chromium.app", "Contents", "MacOS", "Chromium"),
        join(root, b, "chrome-win", "chrome.exe"),
        join(root, b, "chrome-win64", "chrome.exe")
      );
    }
    out.push(join(root, "chromium"), join(root, "chromium", "chrome"));
  }
  return out;
}
function findBrowser(explicit) {
  const isFile = (p) => {
    try {
      return statSync(p).isFile();
    } catch {
      return false;
    }
  };
  if (explicit) return isFile(explicit) ? explicit : null;
  return candidates().find(isFile) ?? null;
}
function launchHeadless(executable, url, software = true) {
  const profile = mkdtempSync(join(tmpdir(), "wobnimo-"));
  const args = [
    "--headless=new",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--mute-audio",
    "--hide-scrollbars",
    `--user-data-dir=${profile}`,
    "--window-size=1400,1100",
    ...software ? ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] : ["--ignore-gpu-blocklist"],
    /* Chrome refuses to sandbox as root, which is how containers and CI run */
    ...process.platform === "linux" && process.getuid?.() === 0 ? ["--no-sandbox"] : [],
    url
  ];
  const child = spawn(executable, args, { stdio: "ignore", detached: process.platform !== "win32" });
  child.on("error", () => {
  });
  return {
    close() {
      try {
        if (process.platform === "win32") spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
        else if (child.pid) process.kill(-child.pid, "SIGKILL");
      } catch {
        child.kill("SIGKILL");
      }
      setTimeout(() => rmSync(profile, { recursive: true, force: true, maxRetries: 3 }), 300).unref();
    }
  };
}
function openInBrowser(url) {
  const [cmd, args] = process.platform === "darwin" ? ["open", [url]] : process.platform === "win32" ? ["cmd", ["/c", "start", '""', url]] : ["xdg-open", [url]];
  const child = spawn(cmd, args, { stdio: "ignore", detached: true });
  child.on("error", () => {
  });
  child.unref();
}
var LoadError = class extends Error {
};
var looksLikeSpec = (v) => !!v && typeof v === "object" && Array.isArray(v.parts) && typeof v.materials === "object";
async function loadSpec(file, name) {
  const path = resolve$1(file);
  const ext = extname(path).toLowerCase();
  let exports;
  try {
    if (ext === ".json") {
      const spec = JSON.parse(readFileSync(path, "utf8"));
      if (spec && typeof spec === "object" && !Array.isArray(spec)) return { spec, path };
      throw new LoadError(`${file} must hold one character spec as a JSON object.`);
    } else {
      exports = await import(`${pathToFileURL(path).href}?t=${Date.now()}`);
    }
  } catch (e) {
    const err = e;
    if (err.code === "ENOENT" || err.code === "ERR_MODULE_NOT_FOUND" && String(err.message).includes(path)) throw new LoadError(`No file at ${path}.`);
    if (err.code === "ERR_UNKNOWN_FILE_EXTENSION" && /\.[mc]?ts$/.test(ext)) throw new LoadError(TS_HELP);
    if (err instanceof SyntaxError && /\.[mc]?ts$/.test(ext) && !runsTypeScript()) throw new LoadError(`${err.message}
${TS_HELP}`);
    if (err instanceof LoadError) throw err;
    throw new LoadError(`Could not load ${file}: ${err.message}`);
  }
  if (name) {
    if (!looksLikeSpec(exports[name])) throw new LoadError(`${file} has no character export named "${name}". Character exports: ${specExports(exports).join(", ") || "none"}.`);
    return { spec: exports[name], path };
  }
  if (looksLikeSpec(exports.default)) return { spec: exports.default, path };
  const found = specExports(exports);
  if (found.length === 1) return { spec: exports[found[0]], path };
  if (found.length > 1) throw new LoadError(`${file} exports several characters (${found.join(", ")}). Pick one with --export <name>.`);
  throw new LoadError(`${file} does not export a character spec. End the file with \`export default <yourCharacter>;\`.`);
}
function specExports(exports) {
  return Object.keys(exports).filter((k) => k !== "default" && looksLikeSpec(exports[k]));
}
var TS_HELP = `This version of Node (${process.versions.node}) cannot run TypeScript files directly.
Use Node 22.18 or newer, or save the spec as .mjs (same code without type annotations) or .json.
Type-only imports must say so: \`import type { CharacterSpec } from 'wobnimo'\`.`;
var [major, minor] = process.versions.node.split(".").map(Number);
var stripsByDefault = major > 23 || major === 23 && minor >= 6 || major === 22 && minor >= 18;
var stripsWithFlag = major > 22 || major === 22 && minor >= 6;
var flagged = () => process.execArgv.some((a) => a.includes("strip-types")) || !!process.env.NODE_OPTIONS?.includes("strip-types");
function runsTypeScript() {
  return stripsByDefault || stripsWithFlag && flagged();
}
function needsTypeStripFlag(file) {
  return /\.[mc]?ts$/i.test(file) && !stripsByDefault && stripsWithFlag && !flagged();
}

// src/cli/pages.ts
var STYLE = `
  :root { color-scheme: light; --ink: #16181d; --mute: #6d6a62; --paper: #f4f1e9; --line: #e2ddd1; }
  body { margin: 0; font: 14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--ink); background: var(--paper); }
`;
var SHEET_CELLS = [
  { label: "front", state: "idle", turn: 0 },
  { label: "\xBE turn", state: "idle", turn: 0.75 },
  { label: "side", state: "idle", turn: Math.PI / 2 },
  { label: "back", state: "idle", turn: Math.PI },
  { label: "face close-up", state: "idle", turn: 0, closeup: true },
  { label: "thinking", state: "thinking" },
  { label: "listening", state: "listening" },
  { label: "speaking", state: "speaking" },
  { label: "working", state: "working" },
  { label: "error", state: "error" },
  { label: "surprised", state: "surprised" },
  /* between hops: 1.5 s in, the shared celebration is mid-somersault */
  { label: "celebrating", state: "celebrating", settle: 2.1 },
  { label: "sad", state: "sad" },
  { label: "sleeping", state: "sleeping" },
  { label: "as a 56px avatar", state: "idle", small: 56 }
];
function sheetPage(cell) {
  return `<!doctype html><meta charset="utf-8"><title>wobnimo preview</title><style>${STYLE}</style>
<body><canvas id="sheet"></canvas>
<script type="module">
const fail = (msg) => fetch('/error', { method: 'POST', body: String(msg) });
addEventListener('error', (e) => fail(e.message));
addEventListener('unhandledrejection', (e) => fail(e.reason?.message ?? e.reason));
try {
  const { snapshot, compile } = await import('/wobnimo.js');
  const spec = await (await fetch('/spec.json')).json();
  const summary = await (await fetch('/summary.json')).json();
  compile(spec);
  const cells = ${JSON.stringify(SHEET_CELLS)};
  const size = ${cell}, cols = 5, label = 26, pad = 10, head = 54;
  const canvas = document.getElementById('sheet');
  canvas.width = cols * (size + pad) + pad;
  canvas.height = head + Math.ceil(cells.length / cols) * (size + label + pad) + pad;
  const g = canvas.getContext('2d');
  g.fillStyle = '#f4f1e9';
  g.fillRect(0, 0, canvas.width, canvas.height);
  g.fillStyle = '#16181d';
  g.font = '600 20px system-ui, sans-serif';
  g.fillText(spec.name + ' (' + spec.id + ')', pad, 30);
  g.font = '13px system-ui, sans-serif';
  g.fillStyle = summary.errors ? '#c2410c' : summary.warnings ? '#a16207' : '#3f6212';
  g.fillText(summary.line, pad, 47);
  for (const [i, c] of cells.entries()) {
    const x = pad + (i % cols) * (size + pad);
    const y = head + Math.floor(i / cols) * (size + label + pad);
    g.fillStyle = '#ffffff';
    g.beginPath(); g.roundRect(x, y, size, size, 10); g.fill();
    /* the close-up re-aims the camera at the eyes */
    const subject = c.closeup ? { ...spec, frame: summary.closeup } : spec;
    const shot = await snapshot(subject, { state: c.state, size: c.small ?? size, pixelRatio: 1, seed: 0.3, turn: c.turn ?? 0, settle: c.settle ?? 1.5 });
    const s = c.small ?? size;
    g.drawImage(shot, x + (size - s) / 2, y + (size - s) / 2, s, s);
    g.fillStyle = '#6d6a62';
    g.font = '13px system-ui, sans-serif';
    g.fillText(c.label, x + 4, y + size + 18);
  }
  const blob = await new Promise((r) => canvas.toBlob(r, 'image/png'));
  await fetch('/result', { method: 'POST', body: blob });
} catch (e) {
  fail(e?.message ?? e);
}
</script>`;
}
function livePage() {
  return `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>wobnimo live preview</title>
<style>${STYLE}
  main { display: grid; grid-template-columns: minmax(280px, 520px) minmax(0, 1fr); gap: 24px; padding: 24px; max-width: 1200px; margin: 0 auto; }
  @media (max-width: 760px) { main { grid-template-columns: 1fr; } }
  #stage { aspect-ratio: 1; background: radial-gradient(circle at 50% 40%, #fff, #ebe6da); border-radius: 18px; }
  h1 { margin: 0 0 4px; font-size: 22px; } p { margin: 0 0 12px; color: var(--mute); }
  .states { display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0 18px; }
  button { font: inherit; border: 1px solid var(--line); background: #fff; border-radius: 999px; padding: 6px 12px; cursor: pointer; }
  button[aria-pressed="true"] { background: var(--ink); color: #fff; border-color: var(--ink); }
  pre { white-space: pre-wrap; background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 14px; font: 12.5px/1.5 ui-monospace, Menlo, Consolas, monospace; overflow-x: auto; }
  .err { color: #c2410c; }
</style>
<main>
  <div id="stage"></div>
  <section>
    <h1 id="name">Loading\u2026</h1><p id="tagline"></p>
    <div class="states" id="states"></div>
    <pre id="report"></pre>
  </section>
</main>
<script type="module">
import { mount, STATES } from '/wobnimo.js';
let mascot = null, state = 'idle', version = -1;
const states = document.getElementById('states');
for (const s of STATES) {
  const b = document.createElement('button');
  b.textContent = s;
  b.onclick = () => { state = s; mascot?.setState(s); paint(); };
  states.append(b);
}
const paint = () => states.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.textContent === state)));
async function load() {
  const r = await (await fetch('/state.json')).json();
  if (r.version === version) return;
  version = r.version;
  document.getElementById('report').textContent = r.report;
  if (!r.spec) { document.getElementById('report').className = 'err'; return; }
  document.getElementById('report').className = '';
  document.getElementById('name').textContent = r.spec.name;
  document.getElementById('tagline').textContent = r.spec.tagline;
  try {
    if (mascot) mascot.setSpec(r.spec);
    else mascot = mount(document.getElementById('stage'), r.spec, { state });
  } catch (e) {
    document.getElementById('report').textContent = String(e.message) + '\\n\\n' + r.report;
    document.getElementById('report').className = 'err';
  }
  paint();
}
await load();
setInterval(load, 600);
</script>`;
}

// src/cli/index.ts
var ROOT = resolve$1(dirname(fileURLToPath(import.meta.url)), "..");
var SKILL = join(ROOT, "skill");
var ENGINE = join(ROOT, "dist", "wobnimo.js");
var HELP = `wobnimo: design your own mascot

Usage
  npx wobnimo new <id>                  Start a mascot from the starter template (writes mascots/<id>.ts)
  npx wobnimo check <file>              Find what would look wrong once rendered, with exact fixes
  npx wobnimo preview <file>            Render every state and angle to one PNG, and check it
  npx wobnimo preview <file> --live     Open a live preview that reloads as you edit
  npx wobnimo skill                     Add the mascot-design skill for Claude Code, Codex, Cursor and others

Options
  --export <name>   Which export to use when a file has several characters
  --out <file>      Where preview writes its PNG (default .wobnimo/<id>.png)
  --size <px>       Size of each picture on the sheet (default 240)
  --json            check: print the report as JSON
  --browser <path>  preview: the Chrome, Edge or Chromium to use (or set WOBNIMO_BROWSER)
  --dir <path>      new: folder for the file (default mascots); skill: where to install

Docs: https://pouryaak.github.io/wobnimo/llms.txt`;
function parse(argv) {
  const flags = {};
  const rest = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const [k, v] = a.slice(2).split("=");
      const next = argv[i + 1];
      if (v !== void 0) flags[k] = v;
      else if (next !== void 0 && !next.startsWith("--") && !["live", "json", "force"].includes(k)) flags[k] = argv[++i];
      else flags[k] = true;
    } else if (a === "-h") flags.help = true;
    else rest.push(a);
  }
  return { command: rest[0] ?? "help", target: rest[1], flags };
}
var str = (v) => typeof v === "string" ? v : void 0;
function fail(message, code = 1) {
  process.stderr.write(`${message}
`);
  process.exit(code);
}
async function main() {
  const args = parse(process.argv.slice(2));
  if (args.flags.version || args.command === "version") return console.log(JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8")).version);
  if (args.flags.help || args.command === "help") return console.log(HELP);
  if (args.target && needsTypeStripFlag(args.target)) {
    const r = spawnSync(process.execPath, ["--experimental-strip-types", "--no-warnings", ...process.argv.slice(1)], { stdio: "inherit" });
    process.exit(r.status ?? 1);
  }
  switch (args.command) {
    case "new":
      return create(args);
    case "check":
      return check(args);
    case "preview":
      return args.flags.live ? live(args) : preview(args);
    case "skill":
      return skill(args);
    default:
      fail(`Unknown command "${args.command}".

${HELP}`);
  }
}
function create(args) {
  const id = args.target;
  if (!id || !/^[a-z][a-z0-9-]*$/.test(id)) fail("Give the mascot an id: lowercase letters, digits and dashes, like `npx wobnimo new sprout`.");
  const dir = resolve$1(str(args.flags.dir) ?? "mascots");
  const file = join(dir, `${id}.ts`);
  if (existsSync(file) && !args.flags.force) fail(`${relative(process.cwd(), file)} already exists. Use --force to overwrite it.`);
  const name = id.split("-").map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
  const template = readFileSync(join(SKILL, "templates", "starter.ts"), "utf8").replaceAll("__ID__", id).replaceAll("__NAME__", name).replaceAll("__CONST__", id.replace(/-([a-z0-9])/g, (_, c) => c.toUpperCase()));
  mkdirSync(dir, { recursive: true });
  writeFileSync(file, template);
  console.log(`Wrote ${relative(process.cwd(), file)}: a simple round character that passes every check.
Reshape it into yours, then run:
  npx wobnimo check ${relative(process.cwd(), file)}
  npx wobnimo preview ${relative(process.cwd(), file)}`);
}
async function check(args) {
  if (!args.target) fail("Which file? `npx wobnimo check mascots/sprout.ts`");
  const { spec } = await load(args);
  const report = checkCharacter(spec);
  if (args.flags.json) console.log(JSON.stringify(report, null, 2));
  else {
    console.log(formatCheck(report));
    console.log(nextStep(report, args.target));
  }
  process.exit(report.ok ? 0 : 1);
}
function nextStep(report, file) {
  if (!report.ok) return `
Fix the errors (each says what to change), then run the check again.`;
  return `
Next: npx wobnimo preview ${file}, then look at the picture.`;
}
async function load(args) {
  try {
    return await loadSpec(args.target, str(args.flags.export));
  } catch (e) {
    fail(e instanceof LoadError ? e.message : String(e));
  }
}
function summaryLine(report) {
  const n = (l) => report.issues.filter((i) => i.level === l).length;
  if (!report.issues.length) return "check: no problems found";
  return `check: ${n("error")} errors, ${n("warning")} warnings, ${n("note")} notes (run wobnimo check for details)`;
}
function serve(routes) {
  const server = createServer((req, res) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const path = new URL(req.url ?? "/", "http://x").pathname;
      const route = routes[path];
      if (!route) {
        res.writeHead(404);
        return res.end();
      }
      route(req, res, Buffer.concat(chunks));
    });
  });
  return new Promise(
    (done) => server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      done({ url: `http://127.0.0.1:${port}/`, close: () => server.close() });
    })
  );
}
var send = (type, body) => (_, res) => {
  res.writeHead(200, { "content-type": type, "cache-control": "no-store" });
  res.end(body);
};
function engineBundle() {
  if (!existsSync(ENGINE)) fail(`The engine bundle is missing (${ENGINE}). Reinstall wobnimo.`);
  return readFileSync(ENGINE);
}
async function preview(args) {
  if (!args.target) fail("Which file? `npx wobnimo preview mascots/sprout.ts`");
  const { spec } = await load(args);
  const report = checkCharacter(spec);
  const size = Math.max(96, Math.min(512, Number(str(args.flags.size) ?? 240) || 240));
  const out = resolve$1(str(args.flags.out) ?? join(".wobnimo", `${spec.id}.png`));
  if (report.issues.some((i) => i.where === "spec" || i.level === "error" && !report.extents)) {
    console.log(formatCheck(report));
    fail("\nThe spec has structural errors, so there is nothing to draw yet. Fix them first.");
  }
  let settle = () => {
  };
  const result = new Promise((r4) => settle = r4);
  const server = await serve({
    "/": send("text/html", sheetPage(size)),
    "/wobnimo.js": send("text/javascript", engineBundle()),
    "/spec.json": send("application/json", JSON.stringify(spec)),
    "/summary.json": send(
      "application/json",
      JSON.stringify({ line: summaryLine(report), errors: !report.ok, warnings: report.issues.some((i) => i.level === "warning"), closeup: report.closeup })
    ),
    "/result": (_, res, body) => {
      res.end();
      settle({ png: body });
    },
    "/error": (_, res, body) => {
      res.end();
      settle({ error: body.toString() });
    }
  });
  const browser = findBrowser(str(args.flags.browser) ?? void 0);
  let headless = null;
  if (browser) {
    headless = launchHeadless(browser, server.url);
  } else {
    console.log(`No Chrome, Edge or Chromium found to render with (set WOBNIMO_BROWSER to one).
Opening your browser instead; the picture is saved once it has drawn. Or open ${server.url} yourself.`);
    openInBrowser(server.url);
  }
  const timeout = new Promise((r4) => setTimeout(() => r4({ error: "Timed out after 120 seconds waiting for the browser to draw." }), 12e4).unref());
  const r = await Promise.race([result, timeout]);
  headless?.close();
  server.close();
  if (r.error || !r.png) fail(`Preview failed: ${r.error}`);
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, r.png);
  const rel = relative(process.cwd(), out);
  console.log(`Wrote ${rel}: front, \xBE, side, back, a face close-up, nine states and a 56px avatar.
Open it and look: is every part where you meant it, does each state read, does it look like "${spec.tagline}"?
`);
  console.log(formatCheck(report));
  ignoreOutput();
  process.exit(0);
}
function ignoreOutput() {
  const dir = resolve$1(".wobnimo");
  if (existsSync(dir) && !existsSync(join(dir, ".gitignore"))) writeFileSync(join(dir, ".gitignore"), "*\n");
}
async function live(args) {
  if (!args.target) fail("Which file? `npx wobnimo preview mascots/sprout.ts --live`");
  let version = 0;
  let state = { version, spec: null, report: "Loading\u2026" };
  const refresh = async () => {
    version++;
    try {
      const { spec } = await loadSpec(args.target, str(args.flags.export));
      const report = checkCharacter(spec);
      state = { version, spec: report.ok || report.extents ? spec : null, report: formatCheck(report) };
    } catch (e) {
      state = { version, spec: null, report: e instanceof Error ? e.message : String(e) };
    }
  };
  await refresh();
  const server = await serve({
    "/": send("text/html", livePage()),
    "/wobnimo.js": send("text/javascript", engineBundle()),
    "/state.json": (req, res) => send("application/json", JSON.stringify(state))(req, res)
  });
  const file = resolve$1(args.target);
  let timer;
  let last = statSync(file).mtimeMs;
  watch(dirname(file), (_, name) => {
    if (name && basename(file) !== String(name)) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      try {
        const now = statSync(file).mtimeMs;
        if (now === last) return;
        last = now;
      } catch {
        return;
      }
      void refresh();
    }, 120);
  });
  console.log(`Live preview of ${args.target}: ${server.url}
It reloads when the file changes. Ctrl+C to stop.`);
  openInBrowser(server.url);
}
function skill(args) {
  if (!existsSync(join(SKILL, "SKILL.md"))) fail(`The skill is missing from this install (${SKILL}).`);
  const explicit = str(args.flags.dir);
  const targets = explicit ? [resolve$1(explicit)] : [resolve$1(".claude", "skills", "wobnimo-mascot"), resolve$1(".agents", "skills", "wobnimo-mascot")];
  for (const t of targets) {
    mkdirSync(t, { recursive: true });
    cpSync(SKILL, t, { recursive: true, force: true });
    console.log(`Added the skill to ${relative(process.cwd(), t) || t}`);
  }
  console.log(`
Now ask your agent for a mascot in one sentence, for example:
  "Use the wobnimo-mascot skill to make a mascot for this app: a sleepy cloud wearing headphones."
Agents without skills can read ${relative(process.cwd(), join(targets[0], "SKILL.md"))} and follow it.`);
}
main().catch((e) => fail(e instanceof Error ? e.stack ?? e.message : String(e)));
