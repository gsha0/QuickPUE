// Editor state, schema resolution and the preset merge used for display.
//
// S.project is exactly what is written to YAML: only values the user entered, with {value, unit, source}
// wrappers where a source is attributed. Preset, default and auto-sized values are shown as placeholders
// and never copied into it unless the user asks (for example "Customise" on a preset item).
import { clone, isAttr, isObj, stripAttr, unwrap } from './util.js';

export const S = {
  meta: null,
  root: null, // Project JSON schema
  defs: {},
  project: {},
  path: null, // root-relative path of the open file
  hasComments: false,
  dirty: false,
  template: null, // preset template (stripped of attribution wrappers)
  presetInfo: null,
  merged: {},
  check: null, // last server check result
  register: new Map(), // register key -> entry (from the last complete check)
  errors: new Map(), // register key -> [messages]
  hints: new Map(), // register key -> [client-side reference messages]
  weather: null,
  weatherKey: null,
  history: [],
  future: [],
  listeners: new Set(),
};

export function onChange(fn) {
  S.listeners.add(fn);
}

// opts: {structural: re-render now, rerender: re-render keeping focus, preset: preset id changed}
export function notify(opts = {}) {
  for (const fn of S.listeners) fn(opts);
}

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------
export function initSchema(schema) {
  S.root = schema;
  S.defs = schema.$defs || {};
}

const PICK = ['description', 'default', 'title'];

export function resolve(sch) {
  if (!sch) return {};
  let out = sch;
  if (sch.$ref) {
    const name = sch.$ref.split('/').pop();
    out = { ...S.defs[name], _model: name };
    for (const k of PICK) if (k in sch) out[k] = sch[k];
  }
  if (out.anyOf) {
    const nonNull = out.anyOf.filter((x) => x.type !== 'null');
    const nullable = nonNull.length < out.anyOf.length;
    if (nonNull.length === 1) {
      const inner = resolve(nonNull[0]);
      const r = { ...inner, nullable };
      for (const k of PICK) if (k in out) r[k] = out[k];
      return r;
    }
    return { ...out, anyOf: nonNull.map(resolve), nullable };
  }
  return out;
}

export function kindOf(sch) {
  if (sch.properties) return 'object';
  if (sch.anyOf) {
    const hasEnum = sch.anyOf.some((x) => x.enum);
    if (hasEnum && sch.anyOf.some((x) => x.type === 'array')) return 'enum-or-list';
    if (hasEnum && sch.anyOf.some((x) => x.type === 'object')) return 'enum-or-map';
    return 'any';
  }
  if (sch.enum) return 'enum';
  if (sch.const !== undefined) return 'enum';
  if (sch.type === 'boolean') return 'bool';
  if (sch.type === 'number') return 'number';
  if (sch.type === 'integer') return 'integer';
  if (sch.type === 'string') return 'string';
  if (sch.type === 'object') {
    const ap = sch.additionalProperties;
    return isObj(ap) && ap.type === 'number' ? 'map' : 'any';
  }
  if (sch.type === 'array') {
    if (sch.prefixItems) return 'tuple';
    const it = resolve(sch.items);
    if (it.properties) return 'list';
    if (it.prefixItems) return 'table';
    if (it.anyOf) return 'serves';
    if (it.type === 'string') return 'chips';
    if (it.type === 'number' || it.type === 'integer') return 'numlist';
    return 'any';
  }
  return 'any';
}

export function listItemSchema(sch) {
  if (sch.type === 'array') return resolve(sch.items);
  if (sch.anyOf) {
    const arr = sch.anyOf.find((x) => x.type === 'array');
    if (arr) return resolve(arr.items);
  }
  return {};
}

// Schema of the value at a path (list items through `items`).
export function schemaAt(path) {
  let sch = S.root;
  for (const seg of path) {
    sch = resolve(sch);
    if (typeof seg === 'string') {
      sch = sch.properties ? sch.properties[seg] : undefined;
    } else {
      sch = listItemSchema(sch);
    }
    if (!sch) return {};
  }
  return resolve(sch);
}

// ---------------------------------------------------------------------------
// Values
// ---------------------------------------------------------------------------
export function getAt(path, obj = S.project) {
  let cur = obj;
  for (const seg of path) {
    cur = unwrap(cur);
    if (cur === undefined || cur === null) return undefined;
    if (isObj(seg)) return undefined; // preset-only list item: nothing in the user data
    cur = cur[seg];
  }
  return cur;
}

function orderKeys(obj, sch) {
  const props = sch && sch.properties ? Object.keys(sch.properties) : null;
  if (!props) return;
  const entries = Object.entries(obj);
  entries.sort((a, b) => {
    const ia = props.indexOf(a[0]);
    const ib = props.indexOf(b[0]);
    return (ia < 0 ? 1e6 : ia) - (ib < 0 ? 1e6 : ib);
  });
  for (const k of Object.keys(obj)) delete obj[k];
  for (const [k, v] of entries) obj[k] = v;
}

// Set (or with value === undefined, delete) the raw value at path, creating parents as needed.
export function setAt(path, value) {
  if (!path.length) {
    S.project = value;
    return;
  }
  let cur = S.project;
  for (let i = 0; i < path.length - 1; i++) {
    const seg = path[i];
    let next = cur[seg];
    if (isAttr(next)) next = next.value;
    if (next === undefined || next === null) {
      if (value === undefined) return;
      next = typeof path[i + 1] === 'number' ? [] : {};
      cur[seg] = next;
      if (!Array.isArray(cur)) orderKeys(cur, schemaAt(path.slice(0, i)));
    }
    cur = next;
  }
  const last = path[path.length - 1];
  if (value === undefined) {
    if (Array.isArray(cur)) cur.splice(last, 1);
    else delete cur[last];
  } else {
    const isNew = !Array.isArray(cur) && !(last in cur);
    cur[last] = value;
    if (isNew) orderKeys(cur, schemaAt(path.slice(0, -1)));
  }
}

// Set a scalar while keeping an existing attribution wrapper.
export function setScalar(path, v) {
  const cur = getAt(path);
  if (isAttr(cur)) {
    if (v === undefined) setAt(path, undefined);
    else cur.value = v;
  } else {
    setAt(path, v);
  }
}

// Name of the user list item at a path ending in a number.
export function nameAt(path) {
  const v = unwrap(getAt(path));
  return isObj(v) ? unwrap(v.name) : undefined;
}

// Value from the preset template at the same logical place, matching named list items by name.
export function inheritedAt(path) {
  if (!S.template) return undefined;
  let u = S.project;
  let t = S.template;
  for (const seg of path) {
    if (t === undefined || t === null) return undefined;
    if (typeof seg === 'number') {
      const item = Array.isArray(unwrap(u)) ? unwrap(unwrap(u)[seg]) : undefined;
      const name = isObj(item) ? unwrap(item.name) : undefined;
      t = Array.isArray(t) ? t.find((x) => isObj(x) && x.name === name) : undefined;
      u = item;
    } else if (isObj(seg)) {
      t = Array.isArray(t) ? t.find((x) => isObj(x) && x.name === seg.n) : undefined;
      u = undefined;
    } else {
      const uu = unwrap(u);
      u = isObj(uu) ? uu[seg] : undefined;
      t = isObj(t) ? t[seg] : undefined;
    }
  }
  return t;
}

// ---------------------------------------------------------------------------
// Merge for display (mirrors inputs.deep_merge and inputs._expand_minimum; the server check is the
// authority, this copy only drives placeholders, reference suggestions and the diagrams).
// ---------------------------------------------------------------------------
const named = (x) => isObj(x) && 'name' in x;

export function deepMerge(base, over) {
  if (isObj(base) && isObj(over)) {
    const out = { ...base };
    for (const [k, v] of Object.entries(over)) out[k] = k in base ? deepMerge(base[k], v) : v;
    return out;
  }
  if (Array.isArray(base) && Array.isArray(over) && base.every(named) && over.every(named)) {
    const names = new Set(base.map((x) => x.name));
    const out = [];
    for (const b of base) {
      const o = over.find((x) => x.name === b.name);
      if (!o) out.push(b);
      else if (!o._remove) {
        const rest = { ...o };
        delete rest._remove;
        out.push(deepMerge(b, rest));
      }
    }
    for (const o of over) if (!names.has(o.name) && !o._remove) out.push(o);
    return out;
  }
  return clone(over);
}

export function expandMinimum(raw) {
  const it = raw.it;
  if (!isObj(it) || raw.halls && raw.halls.length) return raw;
  const n = parseInt(it.halls || 1, 10) || 1;
  const hall = {
    name: (S.presetInfo && S.presetInfo.hall_name) || 'Data hall', count: n,
    it_kw: Number(it.installed_kw) / n, liquid_fraction: Number(it.liquid_fraction || 0), _fromIt: true,
  };
  if (it.area_m2) hall.area_m2 = Number(it.area_m2) / n;
  if (it.height_m) hall.height_m = Number(it.height_m);
  return { ...raw, halls: [hall] };
}

export function computeMerged() {
  const user = stripAttr(cleanProject(clone(S.project)));
  let m;
  if (S.template) {
    m = deepMerge(clone(S.template), expandMinimum(user));
    if (S.presetInfo && S.presetInfo.water_system && !('water_system' in user)) {
      m.water_system = S.presetInfo.water_system;
    }
  } else {
    m = expandMinimum(user);
  }
  S.merged = m;
  return m;
}

// Drop empty objects that stand for "all defaults" (non-optional nested models), keep empty optional
// objects such as `free_cooling: {}` which mean "present with defaults".
export function cleanProject(p) {
  const walk = (val, sch) => {
    sch = resolve(sch);
    if (Array.isArray(val)) {
      const it = listItemSchema(sch);
      val.forEach((x) => walk(x, it));
      return;
    }
    if (!isObj(val) || isAttr(val) || !sch.properties) return;
    for (const [k, v] of Object.entries(val)) {
      const cs = resolve(sch.properties[k]);
      walk(v, cs);
      if (isObj(v) && !isAttr(v) && Object.keys(v).length === 0 && cs.properties && !cs.nullable) delete val[k];
      // an empty list of named items adds nothing (and removes nothing) when merged over a preset
      else if (Array.isArray(v) && v.length === 0 && kindOf(cs) === 'list') delete val[k];
    }
  };
  walk(p, S.root);
  return p;
}

// ---------------------------------------------------------------------------
// Names for references (from the merged project)
// ---------------------------------------------------------------------------
export function names(kind) {
  const m = S.merged || {};
  const list = (k) => (Array.isArray(m[k]) ? m[k].map((x) => x && x.name).filter(Boolean) : []);
  if (kind === 'loops') return list('loops');
  if (kind === 'halls') return list('halls');
  if (kind === 'zones') return list('zones');
  if (kind === 'spaces') return [...list('zones'), ...list('halls')];
  if (kind === 'loss_elements') {
    const e = m.electrical || {};
    const out = ['PDU'];
    (e.ups || []).forEach((u) => u && u.name && out.push(u.name));
    (e.transformers || []).forEach((t) => t && t.name && out.push(t.name));
    const dist = e.distribution === undefined ? { name: 'Distribution' } : e.distribution;
    if (dist) out.push(dist.name || 'Distribution');
    return [...out, ...S.meta.loss_aliases];
  }
  if (kind === 'chiller_library') return S.meta.chiller_library.map((c) => c.id);
  if (kind === 'end_uses') return Object.keys(S.meta.end_uses);
  if (kind === 'output_sets') return S.meta.output_sets;
  if (kind === 'fflp') return [...S.meta.fflp.map((c) => c.id), 'K-DP(0.3)', 'K-DP(0.5)'];
  if (kind === 'profiles') return Object.keys(S.meta.profiles);
  return [];
}

// ---------------------------------------------------------------------------
// History (undo / redo)
// ---------------------------------------------------------------------------
let lastSnap = null;

export function snapshot() {
  const snap = JSON.stringify(S.project);
  if (snap === lastSnap) return;
  if (lastSnap !== null) {
    S.history.push(lastSnap);
    if (S.history.length > 200) S.history.shift();
    S.future = [];
  }
  lastSnap = snap;
}

export function resetHistory() {
  S.history = [];
  S.future = [];
  lastSnap = JSON.stringify(S.project);
}

export function undo() {
  if (!S.history.length) return false;
  S.future.push(lastSnap);
  lastSnap = S.history.pop();
  S.project = JSON.parse(lastSnap);
  return true;
}

export function redo() {
  if (!S.future.length) return false;
  S.history.push(lastSnap);
  lastSnap = S.future.pop();
  S.project = JSON.parse(lastSnap);
  return true;
}
