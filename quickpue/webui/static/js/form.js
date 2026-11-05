// Schema-driven form. Every widget reads and writes S.project through model.js; empty inputs remove the
// key so preset values, tool defaults and auto-sizing still apply (and stay listed as such in the register).
import {
  S, getAt, inheritedAt, kindOf, listItemSchema, nameAt, names, notify, resolve, setAt, setScalar,
} from './model.js';
import { lineChart, profileBars } from './charts.js';
import {
  api, clone, fieldLabel, fmt, h, isAttr, isObj, KIND_LABEL, pathKey, short, stripAttr, titleCase,
  UNIT_LABEL, unitSuffix, unwrap,
} from './util.js';

export const UI = { open: new Set(), closed: new Set(), attr: new Set(), editInherited: new Set() };

export const keyOf = (path) => pathKey(path, nameAt);

let uid = 0;
const nextId = () => `f${++uid}`;

// ---------------------------------------------------------------------------
// Field hints (presentation only)
// ---------------------------------------------------------------------------
const PROFILE = { widget: 'profile' };
const END_USE = { ref: 'end_uses' };
const LOSS_KEYS = { keys: 'loss_elements' };
const HINTS = {
  loop: { ref: 'loops' },
  from_loop: { ref: 'loops' },
  'CDU.serves': { ref: 'halls' },
  'FWU.serves': { ref: 'halls' },
  'UPS.serves': { suggest: ['all'] },
  'ZoneShare.zone': { ref: 'spaces' },
  'FixedLoad.heat_to_zone': { ref: 'zones' },
  'PartLoad.curve': { widget: 'fflp' },
  'Hall.lighting_profile': PROFILE,
  'Hall.occupancy_profile': PROFILE,
  'Zone.lighting_profile': PROFILE,
  'Zone.occupancy_profile': PROFILE,
  'Zone.equipment_profile': PROFILE,
  'FixedLoad.profile': PROFILE,
  'ChillerCurveSpec.library': { ref: 'chiller_library' },
  'WeatherSpec.epw': { widget: 'file', kind: 'epw' },
  'Scenario.profile': { widget: 'file', kind: 'csv' },
  'PV.hourly_csv': { widget: 'file', kind: 'csv' },
  'Boundary.excluded': END_USE,
  'ProjectInfo.workflow': { ref: 'output_sets' },
  'ProjectInfo.notes': { widget: 'textarea' },
  'ProjectInfo.reference_documents': { lines: true },
  'Project.preset': { widget: 'preset' },
  'Project.schema_version': { hidden: true },
  'FixedLoad.end_use': END_USE,
  'RoomUnit.end_use': END_USE,
  'Hall.lighting_end_use': END_USE,
  'Zone.lighting_end_use': END_USE,
  'Zone.equipment_end_use': END_USE,
  'Hall.losses': LOSS_KEYS,
  'Zone.losses': LOSS_KEYS,
  'Electrical.heat_outdoors': LOSS_KEYS,
  'UPS.efficiency': { cols: ['Load fraction', 'Efficiency'], chart: { x: 'UPS load fraction', y: 'Efficiency' } },
  'PartLoad.table': { cols: ['IT load fraction', 'Flow fraction f'], chart: { x: 'IT load fraction', y: 'f' } },
};

function hint(model, key) {
  return HINTS[`${model}.${key}`] || HINTS[key] || {};
}

const GROUP_TITLES = {
  project: 'Project information', it: 'Minimum input: IT load', part_load: 'Part-load model',
  fan_part_load: 'Fan part-load model', integral_pump: 'Integral pump', primary_pump: 'Primary pump',
  secondary_pump: 'Secondary pump', free_cooling: 'Integrated free cooling', adiabatic: 'Adiabatic pads',
  condenser_water: 'Condenser water', wse: 'Water-side economiser', curves: 'Performance curves',
  pdu: 'PDU', distribution: 'Distribution (switchboard and cable) losses', generators: 'Generator testing',
  jacket_heaters: 'Generator jacket heaters', pv: 'Photovoltaics', reset: 'Supply temperature reset',
  ups: 'UPS systems', transformers: 'Transformers', lifts: 'Lifts', loads: 'Fixed loads', chillers: 'Chillers',
  dry_coolers: 'Dry coolers', towers: 'Cooling towers', heat_outdoors: 'Loss heat released outdoors',
  losses: 'Electrical loss heat released here', scenarios: 'IT load scenarios', ghg: 'Greenhouse gas factors',
  boundary: 'PUE boundary', contingency: 'Design contingency', settings: 'Engine settings', weather: 'Weather',
  electrical: 'Electrical', other: 'Other end uses', pump: 'Pump', efficiency: 'Efficiency table',
  table: 'Table', serves: 'Serves', excluded: 'End uses excluded from PUE', drive: 'Motor and VFD correction',
};

const ITEM_TITLES = {
  halls: 'hall', loops: 'loop', plants: 'plant', chillers: 'chiller', dry_coolers: 'dry cooler',
  towers: 'tower', cdus: 'CDU', fwus: 'FWU', zones: 'zone', room_units: 'room unit', ups: 'UPS',
  transformers: 'transformer', lifts: 'lift', loads: 'load', scenarios: 'scenario',
};

export const groupTitle = (key) => GROUP_TITLES[key] || titleCase(key);

// ---------------------------------------------------------------------------
// Value origin shown next to every field
// ---------------------------------------------------------------------------
function effective(f) {
  const v = unwrap(f.value);
  if (v !== undefined && v !== null) return { v, origin: 'user' };
  if (f.value === null) return { v: null, origin: 'user-null' };
  if (f.inh !== undefined && f.inh !== null) return { v: unwrap(f.inh), origin: 'preset' };
  const reg = S.register.get(keyOf(f.path));
  if (reg && (reg.origin === 'auto' || reg.origin === 'default')) return { v: reg.value, origin: reg.origin, rule: reg.ref };
  if (f.dflt !== undefined && f.dflt !== null && f.dflt !== '' && !(Array.isArray(f.dflt) && !f.dflt.length)) return { v: f.dflt, origin: 'default' };
  return { v: undefined, origin: null };
}

function placeholder(eff, f) {
  if (eff.origin === 'user' || eff.origin === 'user-null') {
    return '';
  }
  if (eff.v !== undefined) return fmt(eff.v);
  if (f.req) return 'required';
  const d = f.sch.description || '';
  return /auto|default/i.test(d) ? 'auto' : '';
}

function originNote(eff, f) {
  const inh = f.inh !== undefined && f.inh !== null ? unwrap(f.inh) : undefined;
  if (eff.origin === 'user') {
    if (inh !== undefined && JSON.stringify(inh) !== JSON.stringify(eff.v)) return h('span', { class: 'o o-preset' }, `overrides preset ${short(inh, 24)}`);
    return null;
  }
  if (eff.origin === 'preset') return h('span', { class: 'o o-preset' }, 'preset');
  if (eff.origin === 'auto') return h('span', { class: 'o o-auto', title: eff.rule || '' }, `auto-sized: ${short(eff.rule || '', 60)}`);
  if (eff.origin === 'default') return h('span', { class: 'o o-default', title: eff.rule || f.sch.description || '' }, 'tool default');
  if (f.req) return h('span', { class: 'o o-req' }, 'required');
  return null;
}

function messages(path) {
  const k = keyOf(path);
  const out = [];
  for (const m of S.errors.get(k) || []) out.push(h('div', { class: 'msg err' }, m));
  for (const m of S.hints.get(k) || []) out.push(h('div', { class: 'msg warn' }, m));
  return out;
}

function stateClass(path) {
  const k = keyOf(path);
  if (S.errors.has(k)) return 'has-error';
  if (S.hints.has(k)) return 'has-hint';
  return '';
}

// ---------------------------------------------------------------------------
// Entry points
// ---------------------------------------------------------------------------
export function renderProps(sch, path, keys, ctx = {}) {
  sch = resolve(sch);
  return keys.filter((k) => sch.properties && k in sch.properties).map((k) => renderProp(sch, path, k, ctx));
}

export function renderTopList(key, emptyText) {
  const sch = resolve(S.root.properties[key]);
  const path = [key];
  const f = { key, path, sch, model: 'Project', hn: {}, req: false, value: getAt(path), inh: inheritedAt(path), dflt: sch.default, ctx: {}, ro: false };
  return listBlock(f, { noHead: true, emptyText });
}

export function renderObjectFields(sch, path, ctx = {}) {
  sch = resolve(sch);
  const model = sch._model || sch.title;
  const grid = h('div', { class: 'grid' });
  const blocks = [];
  for (const key of Object.keys(sch.properties || {})) {
    if (hint(model, key).hidden) continue;
    const node = renderProp(sch, path, key, ctx);
    if (!node) continue;
    if (node.classList.contains('block')) blocks.push(node);
    else grid.appendChild(node);
  }
  const extra = EXTRAS[model] ? EXTRAS[model](path, ctx) : null;
  return [extra, grid.childNodes.length ? grid : null, ...blocks];
}

export function renderProp(parentSch, parentPath, key, ctx = {}) {
  const sch = resolve(parentSch.properties[key]);
  const path = [...parentPath, key];
  const model = parentSch._model || parentSch.title;
  const hn = hint(model, key);
  const req = (parentSch.required || []).includes(key);
  const value = getAt(path);
  const inh = inheritedAt(path);
  let dflt = sch.default;
  if (isObj(ctx.defaults) && key in ctx.defaults) dflt = ctx.defaults[key];
  const f = { key, path, sch, model, hn, req, value, inh, dflt, ctx, ro: !!ctx.readonly };
  const kind = hn.widget || kindOf(sch);
  switch (kind) {
    case 'object': return objectBlock(f);
    case 'list': return listBlock(f);
    case 'map': return mapBlock(f);
    case 'table': return tableBlock(f);
    case 'enum-or-list': return scenariosBlock(f);
    case 'enum-or-map': return designConditionField(f);
    case 'serves': return servesBlock(f);
    case 'chips': return chipsField(f);
    case 'numlist': return numlistField(f);
    case 'tuple': return tupleField(f);
    case 'fflp': return specField(f, 'fflp');
    case 'profile': return specField(f, 'profiles');
    case 'file': return fileField(f);
    case 'preset': return presetField(f);
    case 'textarea': return textareaField(f);
    case 'any': return anyField(f);
    default: return scalarField(f, kind);
  }
}

// ---------------------------------------------------------------------------
// Scalars
// ---------------------------------------------------------------------------
function labelEl(f, id, unitOverride) {
  const { label, unit } = fieldLabel(f.key);
  const attr = isAttr(f.value) ? f.value : null;
  const u = unitOverride !== undefined ? unitOverride : (attr && attr.unit ? attr.unit : unit);
  return h('div', { class: 'lbl' },
    h('label', { for: id, title: f.sch.description || '' }, label, f.req ? h('span', { class: 'req', title: 'required' }, '*') : null),
    u ? h('span', { class: `unit ${attr && attr.unit ? 'converted' : ''}`, title: attr && attr.unit ? `entered in ${attr.unit}; converted to ${unit}` : '' }, u) : null,
    f.sch.description ? h('span', { class: 'info', title: f.sch.description, 'aria-label': f.sch.description }, 'i') : null,
    tagButton(f));
}

function cell(f, id, input, extra) {
  const eff = effective(f);
  const k = keyOf(f.path);
  return h('div', { class: `field ${stateClass(f.path)} ${eff.origin === 'user' ? 'is-set' : ''}`, dataset: { key: k } },
    labelEl(f, id), input,
    h('div', { class: 'help' }, originNote(eff, f)),
    messages(f.path), extra || null,
    UI.attr.has(k) ? attrPanel(f) : null);
}

function scalarField(f, kind) {
  const id = nextId();
  const eff = effective(f);
  const cur = unwrap(f.value);
  const fk = `${keyOf(f.path)}:v`;
  let input;
  if (kind === 'enum' || kind === 'bool') {
    const opts = kind === 'bool' ? [true, false] : (f.sch.enum || [f.sch.const]);
    const showEff = eff.v !== undefined && eff.origin !== 'user' ? `${kind === 'bool' ? (eff.v ? 'Yes' : 'No') : eff.v} (${eff.origin === 'preset' ? 'preset' : eff.origin === 'auto' ? 'auto' : 'default'})` : (f.req ? 'Select...' : 'Not set');
    input = h('select', {
      id, disabled: f.ro, dataset: { fk },
      onchange: (e) => {
        const i = e.target.selectedIndex;
        setScalar(f.path, i === 0 ? undefined : opts[i - 1]);
        notify({ rerender: true });
      },
    }, h('option', { value: '' }, showEff),
    opts.map((o) => h('option', { value: String(o), selected: cur === o }, kind === 'bool' ? (o ? 'Yes' : 'No') : String(o))));
  } else {
    const isNum = kind === 'number' || kind === 'integer';
    const listId = datalistFor(f);
    input = h('input', {
      id, type: 'text', inputmode: isNum ? 'decimal' : undefined, value: cur === undefined || cur === null ? '' : String(cur),
      placeholder: placeholder(eff, f), disabled: f.ro, list: listId ? listId.id : undefined, dataset: { fk },
      autocomplete: 'off', spellcheck: isNum ? 'false' : undefined,
      oninput: (e) => {
        const t = e.target.value.trim();
        e.target.classList.remove('bad');
        if (t === '') {
          setScalar(f.path, undefined);
        } else if (isNum) {
          const n = Number(t.replace(/[,_\s]/g, ''));
          if (!Number.isFinite(n) || (kind === 'integer' && !Number.isInteger(n))) {
            e.target.classList.add('bad');
            e.target.title = kind === 'integer' ? 'whole number expected' : 'number expected';
            return;
          }
          setScalar(f.path, n);
        } else {
          setScalar(f.path, e.target.value);
        }
        notify({});
      },
      onchange: () => notify({ rerender: true }),
    });
    if (listId) input = [input, listId];
  }
  return cell(f, id, input);
}

function datalistFor(f) {
  const src = f.hn.ref ? names(f.hn.ref) : f.hn.suggest;
  if (!src || !src.length) return null;
  const id = nextId();
  return h('datalist', { id }, src.map((n) => h('option', { value: n }, f.hn.ref === 'end_uses' ? S.meta.end_uses[n] : null)));
}

// ---------------------------------------------------------------------------
// Source attribution ({value, unit, source, note})
// ---------------------------------------------------------------------------
function attrKind(v) {
  if (!isAttr(v)) return null;
  const src = v.source;
  if (typeof src === 'string') return src;
  return isObj(src) ? (src.kind || 'unspecified') : (v.unit || v.note ? 'unspecified' : null);
}

function tagButton(f) {
  const k = keyOf(f.path);
  const kind = attrKind(f.value);
  const src = isAttr(f.value) ? f.value.source : null;
  const ref = isObj(src) ? src.ref : '';
  const title = kind ? `${KIND_LABEL[kind] || kind}${ref ? ': ' + ref : ''}${f.value.note ? ' (' + f.value.note + ')' : ''}` : 'Add a unit or source attribution';
  return h('button', {
    type: 'button', class: `tag ${kind ? 'k-' + kind : ''} ${UI.attr.has(k) ? 'open' : ''}`, title, 'aria-label': title,
    disabled: f.ro,
    onclick: () => {
      if (UI.attr.has(k)) UI.attr.delete(k);
      else UI.attr.add(k);
      notify({ structural: true });
    },
  }, kind ? (KIND_SHORT[kind] || 'src') : 'src');
}

const KIND_SHORT = {
  document: 'doc', inference: 'inf', designer: 'dsg', assumption: 'asm', pending_manufacturer: 'pend',
  unspecified: 'unit',
};

const UNIT_CASE = {
  w: 'W', kw: 'kW', mw: 'MW', wh: 'Wh', kwh: 'kWh', mwh: 'MWh', gwh: 'GWh', 'l/s': 'L/s', 'm3/s': 'm3/s',
  'm3/h': 'm3/h', pa: 'Pa', kpa: 'kPa', m2: 'm2', m: 'm', mm: 'mm', c: 'C', k: 'K', l: 'L', kl: 'kL', ml: 'ML', '%': '%',
};

function attrPanel(f) {
  const cur = f.value;
  const a = isAttr(cur) ? cur : { value: cur };
  const src = isObj(a.source) ? a.source : (typeof a.source === 'string' ? { kind: a.source } : {});
  const suf = unitSuffix(f.key);
  const units = suf ? (S.meta.units[suf] || []).filter((u) => UNIT_CASE[u]).map((u) => UNIT_CASE[u]) : [];
  const hasValue = a.value !== undefined && a.value !== null;
  const write = (patch) => {
    // read the current value each time: several attribution edits happen without a re-render
    const now = getAt(f.path);
    const cur2 = isAttr(now) ? now : { value: now };
    const src2 = isObj(cur2.source) ? cur2.source : (typeof cur2.source === 'string' ? { kind: cur2.source } : {});
    const next = { value: cur2.value, unit: cur2.unit, kind: src2.kind, ref: src2.ref, note: cur2.note, ...patch };
    const w = { value: next.value };
    if (next.unit) w.unit = next.unit;
    if (next.kind || next.ref) {
      w.source = {};
      if (next.kind) w.source.kind = next.kind;
      if (next.ref) w.source.ref = next.ref;
    }
    if (next.note) w.note = next.note;
    setAt(f.path, Object.keys(w).length > 1 ? w : next.value);
    notify({});
  };
  const eff = effective(f);
  return h('div', { class: 'attr' },
    !hasValue ? h('div', { class: 'attr-note' }, 'Enter a value to attribute it.',
      eff.v !== undefined && eff.v !== null && !f.ro ? h('button', {
        type: 'button', class: 'link', onclick: () => { setAt(f.path, clone(eff.v)); notify({ structural: true }); },
      }, ` Use the shown value (${short(eff.v, 20)})`) : null) : null,
    units.length > 1 ? h('label', null, 'Unit', h('select', {
      disabled: !hasValue, onchange: (e) => write({ unit: e.target.value || undefined }),
    }, h('option', { value: '' }, `${UNIT_LABEL[suf]} (field unit)`),
    units.filter((u) => u.toLowerCase() !== suf && u !== UNIT_LABEL[suf]).map((u) => h('option', { value: u, selected: a.unit === u }, u)))) : null,
    h('label', null, 'Source', h('select', {
      disabled: !hasValue, onchange: (e) => write({ kind: e.target.value || undefined }),
    }, h('option', { value: '' }, 'Not stated'), S.meta.source_kinds.map((k) => h('option', { value: k, selected: src.kind === k }, KIND_LABEL[k] || k)))),
    h('label', { class: 'wide' }, 'Reference', h('input', {
      type: 'text', value: src.ref || '', disabled: !hasValue, placeholder: 'document, clause, drawing, email...',
      onchange: (e) => write({ ref: e.target.value.trim() || undefined }),
    })),
    h('label', { class: 'wide' }, 'Note', h('input', {
      type: 'text', value: a.note || '', disabled: !hasValue,
      onchange: (e) => write({ note: e.target.value.trim() || undefined }),
    })));
}

// ---------------------------------------------------------------------------
// Objects
// ---------------------------------------------------------------------------
export function isOpen(k, dflt) {
  if (UI.open.has(k)) return true;
  if (UI.closed.has(k)) return false;
  return dflt;
}

export function toggle(k, open) {
  if (open) {
    UI.open.add(k);
    UI.closed.delete(k);
  } else {
    UI.closed.add(k);
    UI.open.delete(k);
  }
}

function hasUserData(v) {
  return v !== undefined && v !== null && !(isObj(v) && Object.keys(v).length === 0);
}

function objectBlock(f) {
  const v = unwrap(f.value);
  const k = keyOf(f.path);
  const present = isObj(v);
  const nulled = f.value === null;
  const inherited = isObj(f.inh);
  const actions = [];
  let badge = null;
  let body = true;
  if (f.sch.nullable) {
    if (present) {
      if (!f.ro) actions.push(btn(inherited ? 'Revert to preset' : 'Remove', () => setAt(f.path, undefined), 'Delete these entries'));
      if (inherited) badge = h('span', { class: 'badge b-override' }, 'overrides preset');
    } else if (nulled) {
      badge = h('span', { class: 'badge b-removed' }, 'set to none');
      if (!f.ro) actions.push(btn('Restore', () => setAt(f.path, undefined)));
      body = false;
    } else if (inherited) {
      badge = h('span', { class: 'badge b-preset' }, 'from preset');
      if (!f.ro) actions.push(btn('Set to none', () => setAt(f.path, null), 'Remove the preset value for this project'));
    } else {
      body = false;
      const t = groupTitle(f.key);
      if (!f.ro) actions.push(btn(`Add ${t.charAt(0).toLowerCase()}${t.slice(1)}`, () => { setAt(f.path, {}); toggle(k, true); }, '', 'primary'));
      else badge = h('span', { class: 'badge' }, 'none');
    }
  }
  const depth = f.path.filter((x) => typeof x === 'string').length;
  const open = body && isOpen(k, depth <= 1 || hasUserData(v) || f.ctx.openAll);
  const head = h('div', { class: 'block-head' },
    body ? chevron(k, open) : h('span', { class: 'chev-space' }),
    h('span', { class: 'block-title', title: f.sch.description || '' }, groupTitle(f.key)),
    badge, h('span', { class: 'spacer' }), actions);
  const el = h('section', { class: `block obj ${stateClass(f.path)}`, dataset: { key: k } }, head, messages(f.path));
  if (body && open) {
    const dflt = isObj(f.dflt) ? f.dflt : undefined;
    el.appendChild(h('div', { class: 'block-body' }, renderObjectFields(f.sch, f.path, { ...f.ctx, defaults: dflt })));
  }
  return el;
}

function chevron(k, open) {
  return h('button', {
    type: 'button', class: `chev ${open ? 'open' : ''}`, 'aria-expanded': open ? 'true' : 'false', 'aria-label': open ? 'Collapse' : 'Expand',
    onclick: () => { toggle(k, !open); notify({ structural: true }); },
  }, '›');
}

function btn(label, fn, title, cls) {
  return h('button', {
    type: 'button', class: `btn small ${cls || ''}`, title: title || '',
    onclick: (e) => { e.stopPropagation(); fn(); notify({ structural: true }); },
  }, label);
}

// ---------------------------------------------------------------------------
// Lists of named items (merge with preset items by name)
// ---------------------------------------------------------------------------
const SUMMARY = {
  Hall: (x) => `${x.count || 1} × ${fmt(x.it_kw)} kW IT, liquid ${fmt(x.liquid_fraction ?? 0)}`,
  Loop: (x) => `${fmt(x.supply_c)} / ${fmt(x.return_c)} °C, ${x.medium || 'water'}${x.glycol_pct ? ' ' + x.glycol_pct + ' %' : ''}${x.connection && x.connection !== 'direct' ? ', ' + x.connection + ' from ' + x.from_loop : ''}`,
  Plant: (x) => `${x.type || '?'} on ${x.loop || '?'}`,
  Chiller: (x) => `${x.quantity ?? 'auto'} × ${x.capacity_kw ? fmt(x.capacity_kw) + ' kW' : 'auto kW'}, ${x.kind || 'air_cooled'}`,
  DryCooler: (x) => `${x.quantity ?? 'auto'} × ${x.rated_capacity_kw ? fmt(x.rated_capacity_kw) + ' kW' : 'auto kW'}`,
  Tower: (x) => `${x.quantity ?? 'auto'} × ${x.rated_capacity_kw ? fmt(x.rated_capacity_kw) + ' kW' : 'auto kW'}`,
  CDU: (x) => `${(x.serves || []).join(', ')} on ${x.loop || '?'}`,
  FWU: (x) => `${(x.serves || []).join(', ')} on ${x.loop || '?'}`,
  Zone: (x) => `${x.count || 1} × ${x.category || 'electrical'}, ${fmt(x.setpoint_c ?? 27)} °C`,
  RoomUnit: (x) => `${x.type || '?'} for ${(x.serves || []).map((z) => (isObj(z) ? z.zone : z)).join(', ')}`,
  UPS: (x) => `${x.path || 'it'} path${x.module_kw ? ', ' + fmt(x.module_kw) + ' kW modules' : ''}`,
  Transformer: (x) => `${x.level || 'MVLV'}, ${x.loss_model === 'no_load_load' ? 'no-load + load loss' : fmt(x.percent ?? 1) + ' % of ' + (x.basis || 'facility')}`,
  Scenario: (x) => (x.profile ? `profile ${x.profile}` : `${fmt((x.it_fraction ?? 0) * 100)} % of installed IT`),
  Lift: (x) => `${x.count || 1} lift(s)`,
  FixedLoad: (x) => `${x.end_use || ''}${x.kw ? ', ' + fmt(x.kw) + ' kW' : ''}${x.annual_kwh ? ', ' + fmt(x.annual_kwh) + ' kWh/yr' : ''}`,
};

function listEntries(f, itemSch) {
  const user = Array.isArray(unwrap(f.value)) ? unwrap(f.value) : [];
  const tmpl = Array.isArray(f.inh) ? f.inh.filter(isObj) : [];
  const named = !!(itemSch.properties && itemSch.properties.name);
  const out = [];
  const nm = (u) => (isObj(u) ? unwrap(u.name) : undefined);
  const userNamed = user.every((u) => isObj(u) && 'name' in u);
  const mergeable = named && userNamed && tmpl.every((t) => 'name' in t);
  if (mergeable && tmpl.length) {
    for (const t of tmpl) {
      const i = user.findIndex((u) => nm(u) === t.name);
      if (i < 0) out.push({ kind: 'preset', name: t.name, path: [...f.path, { n: t.name }], tmpl: t });
      else if (user[i]._remove) out.push({ kind: 'removed', name: t.name, ui: i, path: [...f.path, i], tmpl: t });
      else out.push({ kind: 'override', name: t.name, ui: i, path: [...f.path, i], tmpl: t });
    }
  }
  user.forEach((u, i) => {
    if (mergeable && tmpl.some((t) => t.name === nm(u))) return;
    if (isObj(u) && u._remove) out.push({ kind: 'orphan', name: nm(u), ui: i, path: [...f.path, i] });
    else out.push({ kind: 'user', name: nm(u), ui: i, path: [...f.path, i] });
  });
  if (!mergeable && tmpl.length && !user.length) {
    tmpl.forEach((t) => out.push({ kind: 'preset', name: t.name, path: [...f.path, { n: t.name }], tmpl: t }));
  }
  return { out, user, mergeable };
}

function uniqueName(base, user, tmpl) {
  const taken = new Set([...user.map((u) => unwrap(u && u.name)), ...tmpl.map((t) => t.name)]);
  let i = 1;
  while (taken.has(`${base} ${i}`)) i++;
  return `${base} ${i}`;
}

export function listBlock(f, opts = {}) {
  const itemSch = listItemSchema(f.sch);
  const k = keyOf(f.path);
  const { out, user } = listEntries(f, itemSch);
  const tmpl = Array.isArray(f.inh) ? f.inh.filter(isObj) : [];
  const itemTitle = ITEM_TITLES[f.key] || 'item';
  const add = () => {
    const name = uniqueName(titleCase(itemTitle), user, tmpl);
    const item = { name };
    const idx = user.length;
    setAt([...f.path, idx], item);
    toggle(keyOf([...f.path, idx]), true);
  };
  const head = opts.noHead ? null : h('div', { class: 'block-head' },
    h('span', { class: 'chev-space' }),
    h('span', { class: 'block-title', title: f.sch.description || '' }, groupTitle(f.key)),
    h('span', { class: 'count' }, String(out.filter((e) => e.kind !== 'removed' && e.kind !== 'orphan').length)),
    h('span', { class: 'spacer' }),
    !f.ro ? btn(`Add ${itemTitle}`, add, '', 'primary') : null);
  const el = h('section', { class: `block list ${stateClass(f.path)}`, dataset: { key: k } }, head, messages(f.path));
  if (!out.length) {
    el.appendChild(h('div', { class: 'empty' }, opts.emptyText || `No ${itemTitle}s.`, !f.ro && opts.noHead ? [' ', btn(`Add ${itemTitle}`, add, '', 'primary')] : null));
  }
  const many = out.length > 3;
  for (const e of out) el.appendChild(itemCard(e, itemSch, f, many));
  if (opts.noHead && out.length && !f.ro) el.appendChild(h('div', { class: 'list-foot' }, btn(`Add ${itemTitle}`, add, '', 'primary')));
  return el;
}

function itemCard(e, itemSch, f, many) {
  const key = keyOf(e.path);
  const model = itemSch._model || itemSch.title;
  const userItem = e.ui !== undefined ? stripAttr(unwrap(getAt([...f.path, e.ui]))) : undefined;
  const eff = { ...(e.tmpl || {}), ...(isObj(userItem) ? userItem : {}) };
  let summary = '';
  try { summary = SUMMARY[model] ? SUMMARY[model](eff) : ''; } catch (err) { summary = ''; }
  const ro = f.ro || e.kind === 'preset' || e.kind === 'removed' || e.kind === 'orphan';
  const open = e.kind !== 'removed' && e.kind !== 'orphan' && isOpen(key, !many);
  const badges = {
    preset: h('span', { class: 'badge b-preset', title: 'Defined by the preset; customise to change it' }, 'preset'),
    override: h('span', { class: 'badge b-override', title: 'Your entries are merged over the preset item of the same name' }, 'customised preset item'),
    removed: h('span', { class: 'badge b-removed' }, 'removed from preset'),
    orphan: h('span', { class: 'badge b-removed' }, 'removes a name the preset does not have'),
    user: null,
  };
  const actions = [];
  if (!f.ro) {
    if (e.kind === 'user') {
      actions.push(btn('Duplicate', () => {
        const copy = clone(getAt([...f.path, e.ui]));
        if (isObj(copy)) copy.name = `${unwrap(copy.name) || 'item'} copy`;
        const list = getAt(f.path);
        list.splice(e.ui + 1, 0, copy);
      }));
      actions.push(btn('Delete', () => setAt([...f.path, e.ui], undefined), 'Delete this item', 'danger'));
    } else if (e.kind === 'preset') {
      actions.push(btn('Customise', () => {
        const list = Array.isArray(unwrap(f.value)) ? unwrap(f.value) : [];
        setAt([...f.path, list.length], { name: e.name });
        toggle(keyOf([...f.path.slice(0), list.length]), true);
      }, 'Add an entry of the same name; your values are merged over the preset item', 'primary'));
      actions.push(btn('Remove', () => {
        const list = Array.isArray(unwrap(f.value)) ? unwrap(f.value) : [];
        setAt([...f.path, list.length], { name: e.name, _remove: true });
      }, 'Remove this preset item from the project'));
    } else if (e.kind === 'override') {
      actions.push(btn('Revert to preset', () => setAt([...f.path, e.ui], undefined), 'Delete your entries for this item'));
      actions.push(btn('Remove', () => setAt([...f.path, e.ui], { name: e.name, _remove: true }), 'Remove this preset item from the project'));
    } else {
      actions.push(btn('Restore', () => setAt([...f.path, e.ui], undefined)));
    }
  }
  const head = h('div', { class: 'card-head', onclick: (ev) => { if (ev.target.closest('button')) return; toggle(key, !open); notify({ structural: true }); } },
    e.kind !== 'removed' && e.kind !== 'orphan' ? chevron(key, open) : h('span', { class: 'chev-space' }),
    h('span', { class: 'card-name' }, e.name || h('em', null, '(unnamed)')),
    h('span', { class: 'card-sum' }, summary), badges[e.kind], h('span', { class: 'spacer' }), actions);
  const el = h('article', { class: `card k-${e.kind} ${stateClass(e.path)}`, dataset: { key } }, head, messages(e.path));
  if (open) el.appendChild(h('div', { class: 'card-body' }, renderObjectFields(itemSch, e.path, { ...f.ctx, readonly: ro, defaults: undefined })));
  return el;
}

// ---------------------------------------------------------------------------
// Maps (loss element -> fraction), tables (x, y) and chips
// ---------------------------------------------------------------------------
function inheritedView(f, render, copyValue) {
  // read-only display of a preset / default value with an "Edit" button that copies it
  const k = keyOf(f.path);
  const src = f.inh !== undefined && f.inh !== null ? 'preset' : 'default';
  return h('div', { class: 'inherited' }, render,
    !f.ro ? h('div', { class: 'inh-actions' },
      h('span', { class: `o o-${src}` }, src === 'preset' ? 'from preset' : 'tool default'),
      h('button', { type: 'button', class: 'btn small', onclick: () => { setAt(f.path, clone(copyValue)); UI.editInherited.add(k); notify({ structural: true }); } }, 'Edit a copy')) : null);
}

function mapBlock(f) {
  const v = unwrap(f.value);
  const k = keyOf(f.path);
  const listId = nextId();
  const dl = h('datalist', { id: listId }, names(f.hn.keys || '').map((n) => h('option', { value: n })));
  const head = h('div', { class: 'block-head' }, h('span', { class: 'chev-space' }),
    h('span', { class: 'block-title', title: f.sch.description || '' }, groupTitle(f.key)), h('span', { class: 'spacer' }),
    f.hn.keys === 'loss_elements' ? h('a', { href: '#losses', class: 'link small' }, 'See loss heat allocation') : null);
  const el = h('section', { class: `block map ${stateClass(f.path)}`, dataset: { key: k } }, head, messages(f.path), dl);
  const shown = isObj(v) ? v : null;
  const fallback = isObj(f.inh) ? f.inh : (isObj(f.dflt) ? f.dflt : null);
  if (!shown && fallback && Object.keys(fallback).length) {
    el.appendChild(inheritedView(f, kvTable(fallback), fallback));
  }
  if (shown || !fallback || !Object.keys(fallback).length) {
    const rows = Object.entries(shown || {});
    const tbl = h('table', { class: 'kv' }, h('thead', null, h('tr', null, h('th', null, 'Loss element or alias'), h('th', null, 'Fraction'), h('th', null, ''))),
      h('tbody', null, rows.map(([key, val]) => h('tr', null,
        h('td', null, h('input', {
          type: 'text', value: key, list: listId, disabled: f.ro, dataset: { fk: `${k}:k:${key}` },
          onchange: (e) => {
            const nk = e.target.value.trim();
            if (!nk || nk === key) return;
            const o = {};
            for (const [a, b] of Object.entries(shown)) o[a === key ? nk : a] = b;
            setAt(f.path, o);
            notify({ structural: true });
          },
        })),
        h('td', null, h('input', {
          type: 'text', inputmode: 'decimal', value: String(unwrap(val)), disabled: f.ro, dataset: { fk: `${k}:v:${key}` },
          oninput: (e) => { const n = Number(e.target.value); if (Number.isFinite(n) && e.target.value.trim() !== '') { shown[key] = n; notify({}); } },
          onchange: () => notify({ rerender: true }),
        })),
        h('td', null, !f.ro ? h('button', { type: 'button', class: 'x', title: 'Remove', onclick: () => { delete shown[key]; if (!Object.keys(shown).length) setAt(f.path, undefined); notify({ structural: true }); } }, '×') : null)))));
    el.appendChild(tbl);
    if (!f.ro) {
      const nk = h('input', { type: 'text', list: listId, placeholder: 'element (e.g. UPS-IT, ups, distribution)', dataset: { fk: `${k}:newk` } });
      const nv = h('input', { type: 'text', inputmode: 'decimal', placeholder: 'fraction 0 to 1', dataset: { fk: `${k}:newv` } });
      const addRow = () => {
        const key = nk.value.trim();
        const n = Number(nv.value);
        if (!key || !Number.isFinite(n) || nv.value.trim() === '') { nk.focus(); return; }
        const o = isObj(shown) ? shown : {};
        o[key] = n;
        setAt(f.path, o);
        notify({ structural: true });
      };
      nv.addEventListener('keydown', (e) => { if (e.key === 'Enter') addRow(); });
      el.appendChild(h('div', { class: 'add-row' }, nk, nv, h('button', { type: 'button', class: 'btn small', onclick: addRow }, 'Add')));
    }
  }
  return el;
}

function kvTable(obj) {
  return h('table', { class: 'kv ro' }, h('tbody', null, Object.entries(obj).map(([a, b]) => h('tr', null, h('td', null, a), h('td', null, fmt(unwrap(b)))))));
}

function tableBlock(f) {
  const v = unwrap(f.value);
  const k = keyOf(f.path);
  const cols = f.hn.cols || ['x', 'y'];
  const head = h('div', { class: 'block-head' }, h('span', { class: 'chev-space' }),
    h('span', { class: 'block-title', title: f.sch.description || '' }, groupTitle(f.key)), h('span', { class: 'spacer' }),
    Array.isArray(v) && !f.ro ? btn('Clear', () => setAt(f.path, undefined), 'Remove the table (preset or default applies)') : null);
  const el = h('section', { class: `block table ${stateClass(f.path)}`, dataset: { key: k } }, head, messages(f.path));
  const fallback = Array.isArray(f.inh) ? f.inh : (Array.isArray(f.dflt) ? f.dflt : null);
  const rowsShown = Array.isArray(v) ? v : fallback;
  const body = h('div', { class: 'table-body' });
  if (!Array.isArray(v) && fallback) {
    body.appendChild(inheritedView(f, xyTable(fallback, cols, true), fallback));
  } else {
    const rows = Array.isArray(v) ? v : [];
    const tbl = xyTable(rows, cols, f.ro, (i, j, n) => { rows[i][j] = n; notify({}); }, (i) => { rows.splice(i, 1); if (!rows.length) setAt(f.path, undefined); notify({ structural: true }); }, k);
    const wrap = h('div', null, tbl);
    if (!f.ro) {
      const a = h('input', { type: 'text', inputmode: 'decimal', placeholder: cols[0], dataset: { fk: `${k}:na` } });
      const b = h('input', { type: 'text', inputmode: 'decimal', placeholder: cols[1], dataset: { fk: `${k}:nb` } });
      const add = () => {
        const x = Number(a.value);
        const y = Number(b.value);
        if (a.value.trim() === '' || b.value.trim() === '' || !Number.isFinite(x) || !Number.isFinite(y)) { a.focus(); return; }
        const next = [...rows, [x, y]].sort((p, q) => p[0] - q[0]);
        setAt(f.path, next);
        notify({ structural: true });
      };
      b.addEventListener('keydown', (e) => { if (e.key === 'Enter') add(); });
      wrap.appendChild(h('div', { class: 'add-row' }, a, b, h('button', { type: 'button', class: 'btn small', onclick: add }, 'Add row')));
    }
    body.appendChild(wrap);
  }
  if (rowsShown && rowsShown.length >= 2 && f.hn.chart) {
    const pts = [...rowsShown].map((r) => r.map(Number)).sort((p, q) => p[0] - q[0]);
    body.appendChild(lineChart([{ name: groupTitle(f.key), x: pts.map((p) => p[0]), y: pts.map((p) => p[1]), points: true, color: 1 }],
      { height: 150, width: 360, xLabel: f.hn.chart.x, xName: f.hn.chart.x, yLabel: f.hn.chart.y }));
  }
  el.appendChild(body);
  return el;
}

function xyTable(rows, cols, ro, onEdit, onDel, k) {
  return h('table', { class: `kv xy ${ro ? 'ro' : ''}` },
    h('thead', null, h('tr', null, h('th', null, cols[0]), h('th', null, cols[1]), ro ? null : h('th', null, ''))),
    h('tbody', null, rows.map((r, i) => h('tr', null, [0, 1].map((j) => h('td', null, ro ? fmt(r[j], 4) : h('input', {
      type: 'text', inputmode: 'decimal', value: String(r[j]), dataset: { fk: `${k}:${i}:${j}` },
      oninput: (e) => { const n = Number(e.target.value); if (Number.isFinite(n) && e.target.value.trim() !== '') onEdit(i, j, n); },
      onchange: () => notify({ rerender: true }),
    }))), ro ? null : h('td', null, h('button', { type: 'button', class: 'x', title: 'Remove row', onclick: () => onDel(i) }, '×'))))));
}

function chipsField(f) {
  const id = nextId();
  const v = unwrap(f.value);
  const list = Array.isArray(v) ? v : null;
  const eff = effective(f);
  const k = keyOf(f.path);
  const src = f.hn.ref ? names(f.hn.ref) : (f.hn.suggest || []);
  const dl = src.length ? h('datalist', { id: `${id}l` }, src.map((n) => h('option', { value: n }, f.hn.ref === 'end_uses' ? S.meta.end_uses[n] : null))) : null;
  const shown = list || (Array.isArray(eff.v) ? eff.v : []);
  const known = new Set(src);
  const chips = h('div', { class: `chips ${list ? '' : 'inh'}` }, shown.map((c, i) => h('span', { class: `chip ${f.hn.ref && !known.has(c) ? 'unknown' : ''}`, title: f.hn.ref && !known.has(c) ? 'not found in this project' : '' },
    f.hn.ref === 'end_uses' && S.meta.end_uses[c] ? `${c}` : String(c),
    list && !f.ro ? h('button', { type: 'button', class: 'x', title: 'Remove', onclick: () => { list.splice(i, 1); if (!list.length) setAt(f.path, []); notify({ structural: true }); } }, '×') : null)),
  );
  const input = h('input', {
    id, type: 'text', list: dl ? `${id}l` : undefined, placeholder: f.ro ? '' : 'type and press Enter', disabled: f.ro, dataset: { fk: `${k}:add` },
    onkeydown: (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const t = e.target.value.trim();
      if (!t) return;
      const next = [...(list || (eff.origin === 'preset' ? [...shown] : [])), t];
      setAt(f.path, next);
      notify({ structural: true });
    },
    onchange: (e) => {
      const t = e.target.value.trim();
      if (!t || !known.has(t)) return;
      const next = [...(list || (eff.origin === 'preset' ? [...shown] : [])), t];
      setAt(f.path, next);
      notify({ structural: true });
    },
  });
  const wide = f.hn.lines || f.key === 'serves' || f.key === 'excluded';
  const el = cell(f, id, [chips, input, dl]);
  if (wide) el.classList.add('wide');
  return el;
}

function servesBlock(f) {
  // RoomUnit.serves: zone (or hall) names, optionally with a share {zone, share}
  const v = unwrap(f.value);
  const list = Array.isArray(v) ? v : [];
  const k = keyOf(f.path);
  const listId = nextId();
  const all = names('spaces');
  const dl = h('datalist', { id: listId }, all.map((n) => h('option', { value: n })));
  const shown = Array.isArray(v) ? v : (Array.isArray(f.inh) ? f.inh : []);
  const ro = f.ro || !Array.isArray(v) && Array.isArray(f.inh);
  const el = h('section', { class: `block serves ${stateClass(f.path)}`, dataset: { key: k } },
    h('div', { class: 'block-head' }, h('span', { class: 'chev-space' }), h('span', { class: 'block-title' }, 'Serves'), f.req ? h('span', { class: 'req' }, '*') : null,
      h('span', { class: 'muted small' }, 'zone or hall names; a share splits a zone load between unit types'),
      h('span', { class: 'spacer' }), !Array.isArray(v) && Array.isArray(f.inh) && !f.ro ? btn('Edit a copy', () => setAt(f.path, clone(f.inh))) : null),
    messages(f.path), dl);
  const tbl = h('table', { class: 'kv' }, h('thead', null, h('tr', null, h('th', null, 'Zone or hall'), h('th', null, 'Share (optional)'), h('th', null, ''))),
    h('tbody', null, shown.map((z, i) => {
      const zn = isObj(z) ? z.zone : z;
      const sh = isObj(z) ? z.share : undefined;
      const set = (name, share) => {
        list[i] = share === undefined || share === null || share === '' ? name : { zone: name, share: Number(share) };
        notify({});
      };
      return h('tr', { class: all.includes(zn) ? '' : 'unknown' },
        h('td', null, ro ? zn : h('input', { type: 'text', value: zn, list: listId, dataset: { fk: `${k}:${i}:z` }, oninput: (e) => set(e.target.value, sh), onchange: () => notify({ rerender: true }) })),
        h('td', null, ro ? fmt(sh) : h('input', { type: 'text', inputmode: 'decimal', value: sh ?? '', placeholder: '1.0', dataset: { fk: `${k}:${i}:s` }, oninput: (e) => set(zn, e.target.value.trim() === '' ? undefined : e.target.value), onchange: () => notify({ rerender: true }) })),
        h('td', null, ro ? null : h('button', { type: 'button', class: 'x', onclick: () => { list.splice(i, 1); notify({ structural: true }); } }, '×')));
    })));
  el.appendChild(tbl);
  if (!ro) {
    const nz = h('input', { type: 'text', list: listId, placeholder: 'zone or hall', dataset: { fk: `${k}:new` } });
    const add = () => {
      const t = nz.value.trim();
      if (!t) return;
      setAt(f.path, [...list, t]);
      notify({ structural: true });
    };
    nz.addEventListener('keydown', (e) => { if (e.key === 'Enter') add(); });
    nz.addEventListener('change', () => { if (all.includes(nz.value.trim())) add(); });
    el.appendChild(h('div', { class: 'add-row' }, nz, h('button', { type: 'button', class: 'btn small', onclick: add }, 'Add')));
  }
  return el;
}

function numlistField(f) {
  const id = nextId();
  const v = unwrap(f.value);
  const eff = effective(f);
  const input = h('input', {
    id, type: 'text', value: Array.isArray(v) ? v.join(', ') : '', placeholder: Array.isArray(eff.v) ? eff.v.join(', ') : 'comma separated numbers',
    disabled: f.ro, dataset: { fk: `${keyOf(f.path)}:v` },
    oninput: (e) => {
      const t = e.target.value.trim();
      e.target.classList.remove('bad');
      if (!t) { setAt(f.path, undefined); notify({}); return; }
      const nums = t.split(/[,;\s]+/).filter(Boolean).map(Number);
      if (nums.some((n) => !Number.isFinite(n))) { e.target.classList.add('bad'); return; }
      setAt(f.path, nums);
      notify({});
    },
    onchange: () => notify({ rerender: true }),
  });
  const el = cell(f, id, input);
  el.classList.add('wide');
  return el;
}

function tupleField(f) {
  const id = nextId();
  const v = unwrap(f.value);
  const eff = effective(f);
  const pair = Array.isArray(v) ? [...v] : [undefined, undefined];
  const ph = Array.isArray(eff.v) ? eff.v : ['min', 'max'];
  const mk = (i) => h('input', {
    id: i === 0 ? id : undefined, type: 'text', inputmode: 'decimal', value: pair[i] ?? '', placeholder: String(ph[i] ?? ''),
    disabled: f.ro, dataset: { fk: `${keyOf(f.path)}:${i}` },
    oninput: (e) => {
      const t = e.target.value.trim();
      pair[i] = t === '' ? undefined : Number(t);
      if (pair.every((x) => x === undefined)) setAt(f.path, undefined);
      else if (pair.every((x) => Number.isFinite(x))) setAt(f.path, [pair[0], pair[1]]);
      notify({});
    },
    onchange: () => notify({ rerender: true }),
  });
  return cell(f, id, h('div', { class: 'pair' }, mk(0), h('span', { class: 'muted' }, 'to'), mk(1)));
}

// ---------------------------------------------------------------------------
// Free-form values (Any): library ids as text, anything else as YAML / JSON
// ---------------------------------------------------------------------------
function yamlText(v) {
  if (v === undefined) return '';
  const t = JSON.stringify(v);
  return t.length > 70 ? JSON.stringify(v, null, 1).replace(/\n\s*/g, ' ') : t;
}

async function parseInto(f, text, ta) {
  const t = text.trim();
  if (!t) {
    setAt(f.path, undefined);
    notify({ rerender: true });
    return;
  }
  try {
    const r = await api('/api/yaml/parse', { text: t });
    ta.classList.remove('bad');
    setAt(f.path, r.value);
    notify({ rerender: true });
  } catch (e) {
    ta.classList.add('bad');
    ta.title = e.message;
  }
}

function anyField(f) {
  const id = nextId();
  const v = unwrap(f.value);
  const eff = effective(f);
  const ta = h('textarea', {
    id, rows: 2, value: yamlText(v), placeholder: eff.v !== undefined ? yamlText(eff.v) : 'YAML or JSON value', disabled: f.ro,
    spellcheck: 'false', dataset: { fk: `${keyOf(f.path)}:v` },
  });
  ta.addEventListener('change', () => parseInto(f, ta.value, ta));
  const el = cell(f, id, ta);
  el.classList.add('wide');
  return el;
}

function specField(f, lib) {
  // FFLP curve or schedule profile: a library id, or a custom YAML / JSON value
  const id = nextId();
  const v = unwrap(f.value);
  const eff = effective(f);
  const k = keyOf(f.path);
  const custom = (v !== undefined && typeof v !== 'string') || UI.editInherited.has(`${k}:custom`);
  let input;
  if (custom) {
    input = h('textarea', { id, rows: 2, value: yamlText(v), spellcheck: 'false', disabled: f.ro, dataset: { fk: `${k}:v` }, placeholder: lib === 'fflp' ? '{table: [[0, 0.1], [1, 1]]} or [c1, c2, c3, c4, c5]' : '24 hourly fractions, or {weekday: [...], weekend: [...]}' });
    input.addEventListener('change', () => parseInto(f, input.value, input));
  } else {
    const dl = h('datalist', { id: `${id}l` }, names(lib).map((n) => {
      const c = lib === 'fflp' ? S.meta.fflp.find((x) => x.id === n) : null;
      return h('option', { value: n }, c ? c.label : (S.meta.profiles[n] ? S.meta.profiles[n].source : null));
    }));
    input = [h('input', {
      id, type: 'text', list: `${id}l`, value: typeof v === 'string' ? v : '', placeholder: eff.v !== undefined ? short(eff.v, 30) : (lib === 'fflp' ? 'equipment default' : 'always'),
      disabled: f.ro, dataset: { fk: `${k}:v` }, autocomplete: 'off',
      oninput: (e) => { setScalar(f.path, e.target.value.trim() || undefined); notify({}); },
      onchange: () => notify({ rerender: true }),
    }), dl];
  }
  const toggleBtn = f.ro ? null : h('button', {
    type: 'button', class: 'link small', onclick: () => {
      if (custom) { UI.editInherited.delete(`${k}:custom`); if (v !== undefined && typeof v !== 'string') setAt(f.path, undefined); } else UI.editInherited.add(`${k}:custom`);
      notify({ structural: true });
    },
  }, custom ? 'Use a library id' : (lib === 'fflp' ? 'Custom curve' : 'Custom profile'));
  let preview = null;
  if (lib === 'profiles') {
    const p = profileArrays(eff.v === undefined ? (f.dflt ?? 'always') : eff.v);
    if (p) preview = profileBars(p.weekday, p.weekend);
  }
  const el = cell(f, id, h('div', { class: 'spec' }, input, toggleBtn), preview);
  el.classList.add(custom || preview ? 'wide' : 'x');
  return el;
}

export function profileArrays(spec) {
  if (typeof spec === 'string' && S.meta.profiles[spec]) return S.meta.profiles[spec];
  if (typeof spec === 'number') return { weekday: Array(24).fill(spec), weekend: Array(24).fill(spec) };
  if (Array.isArray(spec) && spec.length === 24) return { weekday: spec, weekend: spec };
  if (isObj(spec) && Array.isArray(spec.weekday)) return { weekday: spec.weekday, weekend: spec.weekend || spec.weekday };
  return null;
}

function textareaField(f) {
  const id = nextId();
  const v = unwrap(f.value);
  const ta = h('textarea', {
    id, rows: 3, value: v || '', disabled: f.ro, dataset: { fk: `${keyOf(f.path)}:v` },
    oninput: (e) => { setScalar(f.path, e.target.value || undefined); notify({}); },
  });
  const el = cell(f, id, ta);
  el.classList.add('wide');
  return el;
}

// file pickers are provided by the app (dialog with the server's file list)
export const hooks = { pickFile: null, presetChanged: null };

function fileField(f) {
  const id = nextId();
  const v = unwrap(f.value);
  const eff = effective(f);
  const input = h('input', {
    id, type: 'text', value: v || '', placeholder: eff.v ? String(eff.v) : (f.hn.kind === 'epw' ? 'path to .epw, relative to the project file' : 'path to .csv'),
    disabled: f.ro, dataset: { fk: `${keyOf(f.path)}:v` }, spellcheck: 'false',
    oninput: (e) => { setScalar(f.path, e.target.value.trim() || undefined); notify({}); },
    onchange: () => notify({ rerender: true }),
  });
  const browse = f.ro ? null : h('button', {
    type: 'button', class: 'btn small', onclick: async () => {
      const rel = await hooks.pickFile(f.hn.kind);
      if (rel) { setScalar(f.path, rel); notify({ structural: true }); }
    },
  }, 'Browse');
  const el = cell(f, id, h('div', { class: 'file' }, input, browse));
  el.classList.add('wide');
  return el;
}

function presetField(f) {
  const id = nextId();
  const v = unwrap(f.value);
  const groups = {};
  for (const p of S.meta.presets) {
    const g = p.id.startsWith('AIR') ? 'Air cooled halls (WS-6)' : 'Liquid and air halls';
    (groups[g] = groups[g] || []).push(p);
  }
  const sel = h('select', {
    id, disabled: f.ro, dataset: { fk: 'preset:v' },
    onchange: (e) => { setScalar(f.path, e.target.value || undefined); hooks.presetChanged && hooks.presetChanged(); },
  }, h('option', { value: '' }, 'None: full equipment schedule'),
  Object.entries(groups).map(([g, ps]) => h('optgroup', { label: g }, ps.map((p) => h('option', { value: p.id, selected: v === p.id }, `${p.id}: ${p.name}`)))));
  const p = S.meta.presets.find((x) => x.id === v);
  const info = p ? h('div', { class: 'preset-info' },
    h('div', null, h('b', null, p.name)), h('div', { class: 'muted' }, p.description || ''),
    h('div', { class: 'chips' }, h('span', { class: 'chip' }, p.water_system), h('span', { class: 'chip' }, p.plant_type), p.dcoptest ? h('span', { class: 'chip' }, `DCOPTEST ${p.dcoptest}`) : null),
    h('div', { class: 'muted small' }, 'Preset items appear in each section marked "preset". Customise an item to override its values; your entries merge over the preset by name.'))
    : (v ? h('div', { class: 'msg err' }, `Unknown preset ${v}`) : h('div', { class: 'muted small' }, 'Without a preset every loop, plant and terminal unit is entered in full.'));
  const el = cell(f, id, sel, info);
  el.classList.add('wide');
  return el;
}

function designConditionField(f) {
  const id = nextId();
  const v = unwrap(f.value);
  const eff = effective(f);
  const mode = isObj(v) ? 'custom' : (typeof v === 'string' ? v : '');
  const sel = h('select', {
    id, disabled: f.ro, dataset: { fk: `${keyOf(f.path)}:v` },
    onchange: (e) => {
      const m = e.target.value;
      setAt(f.path, m === '' ? undefined : (m === 'custom' ? { db: undefined, wb: undefined } : m));
      notify({ structural: true });
    },
  }, h('option', { value: '' }, `${eff.v && typeof eff.v === 'string' ? eff.v : 'epw_0.4'} (default)`),
  [['epw_0.4', 'EPW cooling 0.4 % DB / MCWB'], ['max', 'Maximum dry bulb hour'], ['custom', 'Custom design point']].map(([a, b]) => h('option', { value: a, selected: mode === a }, b)));
  let extra = null;
  if (mode === 'custom') {
    const set = (k2, t) => {
      const o = isObj(v) ? v : {};
      const n = Number(t);
      if (t.trim() === '') delete o[k2];
      else if (Number.isFinite(n)) o[k2] = n;
      setAt(f.path, o);
      notify({});
    };
    extra = h('div', { class: 'pair' },
      h('label', null, 'DB °C ', h('input', { type: 'text', inputmode: 'decimal', value: v.db ?? '', dataset: { fk: 'dc:db' }, disabled: f.ro, oninput: (e) => set('db', e.target.value) })),
      h('label', null, 'WB °C ', h('input', { type: 'text', inputmode: 'decimal', value: v.wb ?? '', dataset: { fk: 'dc:wb' }, disabled: f.ro, oninput: (e) => set('wb', e.target.value) })));
  }
  return cell(f, id, sel, extra);
}

function scenariosBlock(f) {
  const v = unwrap(f.value);
  const k = keyOf(f.path);
  const eff = effective(f);
  const mode = Array.isArray(v) ? 'list' : (typeof v === 'string' ? v : '');
  const effMode = Array.isArray(eff.v) ? 'list' : (eff.v || 'nabers');
  const set = (m) => {
    if (m === 'list') {
      const base = effMode === 'design' ? [[1.0]] : [[0.9], [0.75], [0.5], [0.25]];
      setAt(f.path, Array.isArray(eff.v) ? clone(eff.v) : base.map(([p]) => ({ name: `${Math.round(p * 100)}%`, it_fraction: p })));
    } else {
      setAt(f.path, m);
    }
    notify({ structural: true });
  };
  const opt = (m, label) => h('button', {
    type: 'button', class: `seg ${(mode || (effMode === m ? m : '')) === m ? 'on' : ''} ${!mode && effMode === m ? 'inh' : ''}`,
    disabled: f.ro, 'aria-pressed': mode === m ? 'true' : 'false', onclick: () => set(m),
  }, label);
  const el = h('section', { class: `block scen ${stateClass(f.path)}`, dataset: { key: k } },
    h('div', { class: 'block-head' }, h('span', { class: 'chev-space' }), h('span', { class: 'block-title' }, 'IT load scenarios'),
      h('span', { class: 'spacer' }), !mode ? h('span', { class: 'o o-default' }, eff.origin === 'preset' ? 'preset' : 'default') : null),
    messages(f.path),
    h('div', { class: 'segs' }, opt('nabers', 'NABERS set: 90, 75, 50, 25 %'), opt('design', 'Design: 100 %'), opt('list', 'Custom list')),
    h('div', { class: 'muted small' }, 'Each scenario is a flat fraction of installed IT for 8,760 h, or an hourly profile CSV (UC-6).'));
  if (mode === 'list') {
    el.appendChild(listBlock({ ...f, sch: resolve(f.sch.anyOf.find((x) => x.type === 'array')), inh: undefined }, { noHead: true, emptyText: 'No scenarios.' }));
  }
  return el;
}

// ---------------------------------------------------------------------------
// Visual extras shown inside specific groups
// ---------------------------------------------------------------------------
const curveCache = new Map();

function effAt(path, dflt) {
  const v = unwrap(getAt(path));
  if (v !== undefined) return stripAttr(v);
  const t = inheritedAt(path);
  if (t !== undefined) return t;
  return dflt;
}

const EXTRAS = {
  PartLoad(path) {
    const spec = effAt([...path, 'curve']);
    const fmin = Number(effAt([...path, 'f_min'], 0)) || 0;
    const box = h('div', { class: 'extra curve-prev' });
    if (spec === undefined || spec === null) {
      box.appendChild(h('div', { class: 'muted small' }, 'Curve not set: the equipment-type default applies (method and curve defaults per requirements 11.6, listed in docs/DESIGN_DECISIONS.md).'));
      return box;
    }
    const key = JSON.stringify(spec);
    const draw = (c) => {
      box.innerHTML = '';
      const y = c.x.map((x, i) => c.y[Math.max(i, c.x.findIndex((xx) => xx >= fmin))]);
      box.appendChild(lineChart([
        { name: 'FFLP(f)', x: c.x, y: c.y, color: 1 },
        ...(fmin > 0 ? [{ name: `with f_min ${fmin}`, x: c.x, y, color: 2, dash: true }] : []),
      ], { height: 150, width: 360, xLabel: 'Flow or speed fraction f', xName: 'f', yLabel: 'Fraction of design power', yMin: 0, markers: fmin > 0 ? [{ x: fmin, label: 'f_min' }] : [] }));
      box.appendChild(h('div', { class: 'muted small' }, c.describe));
    };
    if (curveCache.has(key)) {
      const c = curveCache.get(key);
      if (c.error) box.appendChild(h('div', { class: 'msg err' }, c.error));
      else draw(c);
    } else {
      box.appendChild(h('div', { class: 'muted small' }, 'Loading curve...'));
      api('/api/curve', { spec }).then((c) => { curveCache.set(key, c); draw(c); })
        .catch((e) => { curveCache.set(key, { error: e.message }); box.innerHTML = ''; box.appendChild(h('div', { class: 'msg err' }, e.message)); });
    }
    return box;
  },
  Reset(path, ctx) {
    const d = isObj(ctx.defaults) ? ctx.defaults : {};
    const g = (k, dv) => { const x = effAt([...path, k]); return x === undefined ? (d[k] ?? dv) : x; };
    const type = g('type', 'fixed');
    const loopPath = path.slice(0, -1);
    const supply = Number(effAt([...loopPath, 'supply_c']));
    const xs = Array.from({ length: 51 }, (_, i) => -5 + i);
    let ys;
    let xl = 'Outdoor dry bulb (°C)';
    if (type === 'fixed') {
      if (!Number.isFinite(supply)) return null;
      ys = xs.map(() => supply);
    } else if (type === 'ambient_linear') {
      const a1 = Number(g('t_amb_low_c'));
      const a2 = Number(g('t_amb_high_c'));
      const s1 = Number(g('supply_low_c'));
      const s2 = Number(g('supply_high_c'));
      if (![a1, a2, s1, s2].every(Number.isFinite)) return h('div', { class: 'extra muted small' }, 'Enter the four reset points to see the schedule.');
      ys = xs.map((x) => (x <= a1 ? s1 : x >= a2 ? s2 : s1 + ((x - a1) * (s2 - s1)) / (a2 - a1)));
    } else {
      const off = Number(g('offset_k', 3));
      const lo = Number(g('min_c', 12.78));
      const hi = Number(g('max_c', 23.89));
      if (type === 'wetbulb_offset') xl = 'Outdoor wet bulb (°C)';
      ys = xs.map((x) => Math.min(hi, Math.max(lo, x + off)));
    }
    return h('div', { class: 'extra' }, lineChart([{ name: 'Supply', x: xs, y: ys, color: 1 }],
      { height: 140, width: 360, xLabel: xl, xName: 'Ambient', yLabel: 'Supply (°C)', unit: '°C' }));
  },
  Adiabatic(path) {
    const w = S.weather;
    const act = Number(effAt([...path, 'activation_c']));
    const incl = !!effAt([...path, 'activation_inclusive'], false);
    if (!w || !Number.isFinite(act)) return null;
    const n = w.hourly.t_db.filter((t) => (incl ? t >= act : t > act)).length;
    return h('div', { class: 'extra stat-line' }, h('b', null, n.toLocaleString()), ` h/yr with outdoor DB ${incl ? '≥' : '>'} ${fmt(act)} °C in ${w.city || 'the weather file'} (pads can be active).`);
  },
  Hall(path) {
    const x = { ...(inheritedAt(path) || {}), ...stripAttr(unwrap(getAt(path)) || {}) };
    const n = Number(x.count || 1);
    const it = Number(x.it_kw);
    if (!Number.isFinite(it)) return null;
    const lf = Number(x.liquid_fraction || 0);
    return h('div', { class: 'extra stat-line' },
      `Total IT ${fmt((n * it) / 1000, 2)} MW: liquid ${fmt((n * it * lf) / 1000, 2)} MW, air ${fmt((n * it * (1 - lf)) / 1000, 2)} MW`,
      x.area_m2 ? `, density ${fmt(it / Number(x.area_m2), 2)} kW/m²` : '');
  },
};
