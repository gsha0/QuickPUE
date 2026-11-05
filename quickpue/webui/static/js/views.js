// Input visualisations: weather, IT scenarios, system diagram, loss heat allocation, input register, YAML.
// These read the inputs only; nothing here estimates energy or PUE.
import { S, cleanProject } from './model.js';
import { barChart, heatmap, hideTip, lineChart, showTip } from './charts.js';
import { api, clone, download, fmt, h, isObj, KIND_LABEL, ORIGIN_LABEL, s, short } from './util.js';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export const nav = { go: null };

function stat(label, value, sub) {
  return h('div', { class: 'stat' }, h('div', { class: 'stat-label' }, label), h('div', { class: 'stat-value' }, value), sub ? h('div', { class: 'stat-sub' }, sub) : null);
}

// ---------------------------------------------------------------------------
// Weather
// ---------------------------------------------------------------------------
function thresholds(m, w) {
  const out = [];
  const spec = (m.weather || {}).design_condition || 'epw_0.4';
  if (isObj(spec) && Number.isFinite(Number(spec.db))) out.push({ t: Number(spec.db), label: 'Design DB (user)', var: 'db' });
  else if (w.design_points[spec]) out.push({ t: w.design_points[spec].db, label: `Design DB (${spec})`, var: 'db' });
  for (const pl of m.plants || []) {
    for (const c of pl.chillers || []) {
      if (isObj(c.adiabatic) && c.adiabatic.enabled !== false && Number.isFinite(Number(c.adiabatic.activation_c))) {
        out.push({ t: Number(c.adiabatic.activation_c), label: `Adiabatic ${c.name}`, var: 'db', incl: !!c.adiabatic.activation_inclusive });
      }
    }
    for (const d of pl.dry_coolers || []) {
      if (isObj(d.adiabatic) && d.adiabatic.enabled !== false && Number.isFinite(Number(d.adiabatic.activation_c))) {
        out.push({ t: Number(d.adiabatic.activation_c), label: `Adiabatic ${d.name}`, var: 'db', incl: !!d.adiabatic.activation_inclusive });
      }
    }
    for (const t of pl.towers || []) {
      if (Number.isFinite(Number(t.design_wb_c))) out.push({ t: Number(t.design_wb_c), label: `Tower ${t.name} design WB`, var: 'wb' });
    }
  }
  for (const r of m.room_units || []) {
    if (/^outdoor_(db|dewpoint)_(above|below)$/.test(r.activation || '') && Number.isFinite(Number(r.activation_value))) {
      out.push({ t: Number(r.activation_value), label: `${r.name} (${r.activation.replace('outdoor_', '').replace('_', ' ')})`, var: r.activation.includes('dewpoint') ? 'dp' : 'db', below: r.activation.endsWith('below') });
    }
  }
  return out;
}

export function weatherView() {
  const w = S.weather;
  if (!w) {
    return h('div', { class: 'panel' }, h('h3', null, 'Weather file'),
      h('div', { class: S.weatherError ? 'msg err' : 'muted' }, S.weatherError || 'Set the EPW file above to see the climate summary.'));
  }
  const m = S.merged;
  const spec = (m.weather || {}).design_condition || 'epw_0.4';
  const dp = isObj(spec) ? { db: spec.db, wb: spec.wb, label: 'user design condition' } : (w.design_points[spec] || w.design_points['epw_0.4']);
  const ann = w.monthly.find((r) => r.label === 'Annual') || {};
  const months = w.monthly.filter((r) => r.label !== 'Annual');
  const xs = months.map((_, i) => i + 1);
  const xl = Object.fromEntries(xs.map((x, i) => [x, MONTHS[i]]));
  const monthly = lineChart([
    { name: 'DB max', x: xs, y: months.map((r) => r['DBT max (C)']), color: 2, points: true },
    { name: 'DB mean', x: xs, y: months.map((r) => r['DBT mean (C)']), color: 1, points: true },
    { name: 'DB min', x: xs, y: months.map((r) => r['DBT min (C)']), color: 1, dash: true },
    { name: 'WB max', x: xs, y: months.map((r) => r['WBT max (C)']), color: 3, points: true },
  ], { height: 230, width: 460, xLabels: xl, xTicks: xs, xName: '', yLabel: '°C', unit: '°C', title: 'Monthly temperatures', xMin: 1, xMax: 12 });

  const starts = [];
  let doy = 0;
  for (let i = 0; i < w.day.length; i += 24) {
    if (w.day[i] === 1) starts.push({ day: doy, label: MONTHS[w.month[i] - 1] });
    doy++;
  }
  const dayLabel = (d) => `${w.day[d * 24]} ${MONTHS[w.month[d * 24] - 1]}`;
  const heat = heatmap(w.hourly.t_db, { unit: '°C', name: 'Dry bulb', mid: ann['DBT mean (C)'], monthStarts: starts, dayLabel, title: 'Hourly dry bulb (day of year by hour of day)' });

  // hours per year above each temperature
  const th = thresholds(m, w);
  const sorted = (arr) => [...arr].sort((a, b) => a - b);
  const db = sorted(w.hourly.t_db);
  const wb = sorted(w.hourly.t_wb);
  const above = (arr, t) => {
    let lo = 0;
    let hi = arr.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (arr[mid] > t) hi = mid; else lo = mid + 1;
    }
    return arr.length - lo;
  };
  const tmin = Math.floor(Math.min(db[0], wb[0]));
  const tmax = Math.ceil(db[db.length - 1]);
  const grid = [];
  for (let t = tmin; t <= tmax; t += 0.5) grid.push(t);
  const exceed = lineChart([
    { name: 'Dry bulb', x: grid, y: grid.map((t) => above(db, t)), color: 2 },
    { name: 'Wet bulb', x: grid, y: grid.map((t) => above(wb, t)), color: 3 },
  ], {
    height: 230, width: 460, xLabel: 'Outdoor temperature (°C)', xName: 'T', yLabel: 'hours per year above T', unit: 'h', yMin: 0,
    markers: th.filter((x) => x.var !== 'dp').map((x, i) => ({ x: x.t, label: short(x.label, 22), row: i % 4 })), title: 'Hours per year above a temperature',
  });
  const dp_all = sorted(w.hourly.t_dp);
  const count = (x) => {
    const arr = x.var === 'wb' ? wb : (x.var === 'dp' ? dp_all : db);
    if (x.below) return arr.filter((v) => v < x.t).length;
    return x.incl ? arr.filter((v) => v >= x.t).length : above(arr, x.t);
  };
  const thTable = th.length ? h('table', { class: 'data' }, h('thead', null, h('tr', null, h('th', null, 'Input threshold'), h('th', null, 'Variable'), h('th', { class: 'num' }, '°C'), h('th', { class: 'num' }, 'Hours per year'))),
    h('tbody', null, th.map((x) => h('tr', null, h('td', null, x.label), h('td', null, `${{ db: 'dry bulb', wb: 'wet bulb', dp: 'dew point' }[x.var]} ${x.below ? '<' : (x.incl ? '≥' : '>')}`),
      h('td', { class: 'num' }, fmt(x.t, 1)), h('td', { class: 'num' }, count(x).toLocaleString()))))) : null;

  return h('div', { class: 'panel' },
    h('h3', null, 'Weather file'),
    h('div', { class: 'station' }, h('b', null, w.station), ` · ${fmt(w.latitude, 3)}, ${fmt(w.longitude, 3)} · ${fmt(w.elevation_m, 0)} m · ${w.source || ''}`),
    w.warnings.length ? h('div', { class: 'msg warn' }, w.warnings.join(' ')) : null,
    h('div', { class: 'stats' },
      stat('Annual mean DB', `${fmt(ann['DBT mean (C)'], 1)} °C`),
      stat('Maximum DB', `${fmt(ann['DBT max (C)'], 1)} °C`),
      stat('Minimum DB', `${fmt(ann['DBT min (C)'], 1)} °C`),
      stat('Maximum WB', `${fmt(ann['WBT max (C)'], 1)} °C`),
      stat('Sizing design point', `${fmt(dp.db, 1)} / ${fmt(dp.wb, 1)} °C`, `${dp.label} (DB / WB)`)),
    h('div', { class: 'charts two' }, monthly, exceed),
    thTable,
    heat,
    h('details', { class: 'table-view' }, h('summary', null, 'Monthly table'),
      h('table', { class: 'data' }, h('thead', null, h('tr', null, h('th', null, ''), Object.keys(months[0]).filter((k) => k !== 'label').map((k) => h('th', { class: 'num' }, k)))),
        h('tbody', null, w.monthly.map((r) => h('tr', null, h('td', null, r.label), Object.entries(r).filter(([k]) => k !== 'label').map(([, v]) => h('td', { class: 'num' }, fmt(v, 1)))))))));
}

// ---------------------------------------------------------------------------
// IT scenarios
// ---------------------------------------------------------------------------
export function scenariosView() {
  const m = S.merged;
  const halls = (m.halls || []).filter(isObj);
  const it = halls.reduce((a, x) => a + (Number(x.count) || 1) * (Number(x.it_kw) || 0), 0);
  const liq = halls.reduce((a, x) => a + (Number(x.count) || 1) * (Number(x.it_kw) || 0) * (Number(x.liquid_fraction) || 0), 0);
  let sc = m.scenarios || 'nabers';
  if (sc === 'nabers') sc = [0.9, 0.75, 0.5, 0.25].map((p) => ({ name: `${Math.round(p * 100)}%`, it_fraction: p }));
  else if (sc === 'design') sc = [{ name: '100%', it_fraction: 1 }];
  if (!Array.isArray(sc)) sc = [];
  const flat = sc.filter((x) => isObj(x) && x.it_fraction !== undefined && x.it_fraction !== null);
  const prof = sc.filter((x) => isObj(x) && x.profile);
  const lf = it > 0 ? liq / it : 0;
  const body = [];
  body.push(h('div', { class: 'stats' },
    stat('Installed IT', `${fmt(it / 1000, 2)} MW`, `${halls.length} hall type(s)`),
    stat('Liquid captured', `${fmt(lf * 100, 0)} %`, `${fmt(liq / 1000, 2)} MW at installed IT`),
    stat('Scenarios', String(sc.length), prof.length ? `${prof.length} hourly profile(s)` : 'flat fractions')));
  if (flat.length && it > 0) {
    body.push(barChart(flat.map((x) => x.name), [
      { name: 'Liquid-cooled IT', values: flat.map((x) => (Number(x.it_fraction) * liq) / 1000), color: 1 },
      { name: 'Air-cooled IT', values: flat.map((x) => (Number(x.it_fraction) * (it - liq)) / 1000), color: 2 },
    ], { height: 200, yLabel: 'MW', unit: 'MW', yFmt: (v) => fmt(v, 2), title: 'IT load per flat scenario (installed IT × fraction)' }));
  }
  if (prof.length) body.push(h('div', { class: 'muted small' }, `Hourly profiles (read at run time, not previewed here): ${prof.map((x) => `${x.name}: ${x.profile}`).join('; ')}`));
  if (!it) body.push(h('div', { class: 'muted' }, 'Enter the installed IT (minimum input) or the data halls to see the scenario loads.'));
  return h('div', { class: 'panel' }, h('h3', null, 'Scenario IT loads'), body);
}

// ---------------------------------------------------------------------------
// System diagram (halls / zones -> terminal units -> loops -> plants)
// ---------------------------------------------------------------------------
const COLWS = [176, 184, 176, 224]; // spaces, terminal units, loops, plants
const GAPX = 56;
const LINE = 15;
const COLX = COLWS.map((_, i) => 20 + COLWS.slice(0, i).reduce((a, b) => a + b, 0) + i * GAPX);
const chars = (w, px) => Math.floor((w - 16) / (px * 0.58));

function node(id, col, title, lines, cls, go) {
  return { id, col, title, lines: lines.filter(Boolean), cls, go, h: 28 + LINE * lines.filter(Boolean).length };
}

function equipLine(label, x) {
  const q = x.quantity ?? (x.duty !== undefined ? `${x.duty}+${x.standby || 0}` : 'auto');
  const cap = x.capacity_kw ?? x.rated_capacity_kw;
  return `${label}: ${q} × ${cap ? fmt(Number(cap)) + ' kW' : 'auto kW'}`;
}

export function diagramView() {
  const m = S.merged;
  const nodes = [];
  const edges = [];
  const byId = new Map();
  const add = (n) => { if (!byId.has(n.id)) { byId.set(n.id, n); nodes.push(n); } return byId.get(n.id); };
  const halls = (m.halls || []).filter(isObj);
  const zones = (m.zones || []).filter(isObj);
  const loops = (m.loops || []).filter(isObj);
  const plants = (m.plants || []).filter(isObj);
  const space = (name) => (halls.some((x) => x.name === name) ? `hall:${name}` : zones.some((x) => x.name === name) ? `zone:${name}` : null);
  const missing = (col, kind, name) => add(node(`missing:${kind}:${name}`, col, name, [`${kind} not found`], 'missing'));

  halls.forEach((x) => add(node(`hall:${x.name}`, 0, x.name, [`${x.count || 1} × ${fmt(Number(x.it_kw) / 1000, 2)} MW IT`, `liquid ${fmt(Number(x.liquid_fraction || 0) * 100, 0)} %`, x._fromIt ? 'from minimum input' : null], 'hall', ['halls', x.name])));
  zones.forEach((x) => add(node(`zone:${x.name}`, 0, x.name, [`${x.count || 1} × ${x.category || 'electrical'}, ${fmt(x.setpoint_c ?? 27)} °C`], 'zone', ['zones', x.name])));
  loops.forEach((x) => add(node(`loop:${x.name}`, 2, x.name, [`${fmt(x.supply_c)} / ${fmt(x.return_c)} °C${x.reset && x.reset.type && x.reset.type !== 'fixed' ? ', reset' : ''}`, `${x.medium || 'water'}${x.glycol_pct ? ' ' + x.glycol_pct + ' %' : ''}${x.connection && x.connection !== 'direct' ? `, ${x.connection}` : ''}`], 'loop', ['loops', x.name])));
  const loopId = (name, col) => (loops.some((x) => x.name === name) ? `loop:${name}` : missing(col, 'loop', name).id);

  plants.forEach((p) => {
    const lines = [p.type || 'type?'];
    (p.chillers || []).forEach((c) => lines.push(equipLine(c.name, c) + (c.adiabatic ? ', adiabatic' : '') + (c.free_cooling ? ', free cooling' : '')));
    (p.dry_coolers || []).forEach((c) => lines.push(equipLine(c.name, c) + (c.adiabatic ? ', adiabatic' : '')));
    (p.towers || []).forEach((c) => lines.push(equipLine(c.name, c)));
    if (p.wse) lines.push(`WSE approach ${fmt(p.wse.approach_k ?? 2)} K`);
    if (p.condenser_water) lines.push('condenser water loop');
    const n = add(node(`plant:${p.name}`, 3, p.name, lines, 'plant', ['plants', p.name]));
    if (p.loop) edges.push({ a: loopId(p.loop, 2), b: n.id, cls: 'water' });
  });
  loops.forEach((x) => {
    if (x.from_loop) {
      const src = loops.some((l) => l.name === x.from_loop) ? `loop:${x.from_loop}` : missing(2, 'loop', x.from_loop).id;
      edges.push({ a: `loop:${x.name}`, b: src, cls: 'link', label: x.connection, same: true });
    }
  });
  const terminal = (list, kind, cls, section) => list.filter(isObj).forEach((x) => {
    const lines = [];
    if (kind === 'CDU') lines.push(`${x.quantity ?? 'auto'} units${x.active ? `, ${x.active} active` : ''}`);
    if (kind === 'FWU') lines.push(`${x.quantity ?? 'auto'} units${x.fan_power_kw ? ` × ${fmt(Number(x.fan_power_kw))} kW fan` : ''}`);
    if (kind === 'RU') lines.push(`${x.type || '?'}${x.quantity ? ' × ' + x.quantity : ''}${x.loop ? '' : (['CRAC', 'VRF', 'split', 'DX_dehumidifier'].includes(x.type) ? ', air-cooled DX' : '')}`);
    const n = add(node(`${kind}:${x.name}`, 1, x.name, lines, cls, [section, x.name]));
    (x.serves || []).forEach((sv) => {
      const nm = isObj(sv) ? sv.zone : sv;
      const sid = space(nm) || missing(0, kind === 'RU' ? 'zone' : 'hall', nm).id;
      edges.push({ a: sid, b: n.id, cls, label: isObj(sv) && sv.share ? `${fmt(sv.share * 100, 0)} %` : '' });
    });
    if (x.loop) edges.push({ a: n.id, b: loopId(x.loop, 2), cls: 'water' });
  });
  terminal(m.cdus || [], 'CDU', 'liquid', 'cdus');
  terminal(m.fwus || [], 'FWU', 'air', 'fwus');
  terminal(m.room_units || [], 'RU', 'room', 'room_units');

  if (!nodes.length) {
    return h('div', { class: 'panel' }, h('h3', null, 'System diagram'), h('div', { class: 'muted' }, 'Nothing to draw yet: add halls, loops and plants, or choose a preset.'));
  }

  // order columns: plants as listed; loops by the first plant they feed; terminals by loop; spaces by terminals
  const cols = [[], [], [], []];
  nodes.forEach((n) => cols[n.col].push(n));
  const idx = new Map();
  const setIdx = (c) => cols[c].forEach((n, i) => idx.set(n.id, i));
  setIdx(3);
  const mean = (arr) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 1e6);
  const neighbours = (id, col) => edges.filter((e) => (e.a === id && byId.get(e.b)?.col === col) || (e.b === id && byId.get(e.a)?.col === col)).map((e) => idx.get(e.a === id ? e.b : e.a)).filter((v) => v !== undefined);
  const sortCol = (c, ref) => {
    const pos = new Map(cols[c].map((n, i) => [n.id, i]));
    cols[c].sort((a, b) => (mean(neighbours(a.id, ref)) - mean(neighbours(b.id, ref))) || (pos.get(a.id) - pos.get(b.id)));
    setIdx(c);
  };
  sortCol(2, 3);
  sortCol(1, 2);
  sortCol(0, 1);
  sortCol(1, 0);

  const GAPY = 12;
  const heights = cols.map((c) => c.reduce((a, n) => a + n.h + GAPY, -GAPY));
  const H = Math.max(...heights, 60) + 40;
  const W = COLX[3] + COLWS[3] + 20;
  cols.forEach((c, ci) => {
    let y = 30 + (H - 40 - heights[ci]) / 2;
    c.forEach((n) => { n.x = COLX[ci]; n.w = COLWS[ci]; n.y = y; y += n.h + GAPY; });
  });
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'diagram', role: 'img', 'aria-label': 'System diagram of spaces, terminal units, loops and plants' });
  ['Spaces', 'Terminal units', 'Water loops', 'Plants'].forEach((t, i) => svg.append(s('text', { x: COLX[i], y: 16, class: 'col-title' }, t)));
  const eg = s('g', { class: 'edges' });
  svg.append(eg);
  // fan edges out over the height of each node
  const ports = new Map();
  const portY = (n, side, k) => {
    const key = `${n.id}:${side}`;
    const list = ports.get(key) || [];
    return n.y + n.h / 2 + (list.length > 1 ? ((list.indexOf(k) / (list.length - 1)) - 0.5) * Math.min(n.h - 12, list.length * 6) : 0);
  };
  edges.forEach((e, k) => {
    const a = byId.get(e.a);
    const b = byId.get(e.b);
    if (!a || !b) return;
    const sa = e.same ? 'r' : (a.col < b.col ? 'r' : 'l');
    const sb = e.same ? 'r' : (a.col < b.col ? 'l' : 'r');
    for (const [n, sd] of [[a, sa], [b, sb]]) {
      const key = `${n.id}:${sd}`;
      if (!ports.has(key)) ports.set(key, []);
      ports.get(key).push(k);
    }
  });
  edges.forEach((e, k) => {
    const a = byId.get(e.a);
    const b = byId.get(e.b);
    if (!a || !b) return;
    let d;
    if (e.same) {
      const x = a.x + a.w;
      const y1 = portY(a, 'r', k);
      const y2 = portY(b, 'r', k);
      d = `M${x},${y1} C${x + 50},${y1} ${x + 50},${y2} ${x},${y2}`;
    } else {
      const fwd = a.col < b.col;
      const x1 = fwd ? a.x + a.w : a.x;
      const x2 = fwd ? b.x : b.x + b.w;
      const y1 = portY(a, fwd ? 'r' : 'l', k);
      const y2 = portY(b, fwd ? 'l' : 'r', k);
      const dx = Math.abs(x2 - x1) / 2;
      d = `M${x1},${y1} C${x1 + (fwd ? dx : -dx)},${y1} ${x2 - (fwd ? dx : -dx)},${y2} ${x2},${y2}`;
    }
    const p = s('path', { d, class: `edge e-${e.cls} ${b.cls === 'missing' || a.cls === 'missing' ? 'e-missing' : ''}` });
    eg.append(p);
    if (e.label) {
      const lx = e.same ? a.x + a.w + 40 : (a.x + a.w + b.x) / 2;
      const ly = e.same ? (portY(a, 'r', k) + portY(b, 'r', k)) / 2 : (portY(a, 'r', k) + portY(b, 'l', k)) / 2;
      eg.append(s('text', { x: lx, y: ly - 3, class: 'edge-label', 'text-anchor': 'middle' }, e.label));
    }
  });
  nodes.forEach((n) => {
    const g = s('g', { class: `node n-${n.cls} ${n.go ? 'clickable' : ''}`, transform: `translate(${n.x},${n.y})`, tabindex: n.go ? 0 : undefined });
    g.append(s('rect', { width: n.w, height: n.h, rx: 6, class: 'node-box' }));
    g.append(s('rect', { width: 4, height: n.h, rx: 2, class: 'node-key' }));
    g.append(s('text', { x: 12, y: 18, class: 'node-title' }, short(n.title, chars(n.w, 13))));
    n.lines.forEach((l, i) => g.append(s('text', { x: 12, y: 18 + LINE * (i + 1), class: 'node-line' }, short(l, chars(n.w, 11.5)))));
    if (n.go) {
      const go = () => nav.go && nav.go(n.go[0], `${n.go[0]}[${n.go[1]}]`);
      g.addEventListener('click', go);
      g.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') go(); });
      g.addEventListener('mousemove', (ev) => showTip(ev, `<div class="tip-head">${esc(n.title)}</div>${n.lines.map((l) => `<div>${esc(l)}</div>`).join('')}<div class="muted">Click to edit</div>`));
      g.addEventListener('mouseleave', hideTip);
    }
    svg.append(g);
  });
  const key = (cls, label) => h('span', { class: 'legend-item' }, h('span', { class: `key-box n-${cls}` }), label);
  const ekey = (cls, label) => h('span', { class: 'legend-item' }, h('span', { class: `key-line e-${cls}` }), label);
  const nMissing = nodes.filter((n) => n.cls === 'missing').length;
  return h('div', { class: 'panel' },
    h('h3', null, 'System diagram'),
    h('div', { class: 'muted small' }, 'Heat flows left to right: spaces to the terminal units that serve them, to the water loops, to the plants. Built from the inputs (preset merged); click a box to edit it.'),
    nMissing ? h('div', { class: 'msg err' }, `${nMissing} reference(s) point to names that do not exist (red boxes).`) : null,
    h('div', { class: 'legend' }, key('hall', 'Data hall'), key('zone', 'Support zone'), key('liquid', 'CDU'), key('air', 'FWU'), key('room', 'Room unit'), key('loop', 'Water loop'), key('plant', 'Plant'),
      ekey('liquid', 'liquid (CDU)'), ekey('air', 'air (FWU)'), ekey('room', 'room unit'), ekey('water', 'water'), ekey('link', 'loop connection')),
    h('div', { class: 'diagram-wrap' }, svg));
}

// ---------------------------------------------------------------------------
// Electrical loss heat allocation (from the engine, via the full check)
// ---------------------------------------------------------------------------
export function lossView() {
  const c = S.check;
  const head = h('h3', null, 'Electrical loss heat allocation');
  const intro = h('p', { class: 'muted small' }, 'Where the heat of each loss element is released (halls, zones and outdoors), as the engine resolves the "losses" and "heat_outdoors" inputs. Unallocated heat is treated as released outdoors and reported as a warning.');
  if (!c || c.stage !== 'complete' || !c.loss_alloc) {
    return h('div', { class: 'panel' }, head, intro, h('div', { class: 'muted' }, c && c.errors.length ? 'Resolve the input errors first (see Issues).' : 'Waiting for the input check...'));
  }
  const la = c.loss_alloc;
  const rows = la.elements.map((el) => {
    const a = la.alloc[el.name] || {};
    const sum = Object.values(a).reduce((x, y) => x + y, 0);
    const pduDefault = el.name === 'PDU' && la.pdu_default_to_halls;
    const un = pduDefault ? 0 : Math.max(0, 1 - sum);
    const inside = Object.entries(a).filter(([r]) => r !== '__outdoors__');
    const outdoors = a.__outdoors__ || 0;
    const bar = h('div', { class: 'alloc-bar', title: pduDefault ? 'released in the data halls' : `${fmt(sum * 100, 1)} % allocated` },
      h('span', { class: 'seg a', style: { width: `${Math.min(1, pduDefault ? 1 : sum) * 100}%` } }),
      un > 1e-6 ? h('span', { class: 'seg u', style: { width: `${un * 100}%` } }) : null);
    return h('tr', null,
      h('td', null, h('b', null, el.name), h('div', { class: 'muted small' }, el.kind.replace('_', ' '))),
      h('td', null, pduDefault ? h('span', { class: 'muted' }, 'data halls (default when no allocation is given)')
        : h('div', { class: 'recv' }, inside.map(([r, f]) => h('span', { class: 'chip' }, `${r} ${fmt(f * 100, 1)} %`)))),
      h('td', { class: 'num' }, outdoors ? `${fmt(outdoors * 100, 1)} %` : ''),
      h('td', { class: `num ${un > 1e-6 ? 'warn-cell' : ''}` }, un > 1e-6 ? `${fmt(un * 100, 1)} %` : ''),
      h('td', null, bar));
  });
  return h('div', { class: 'panel' }, head, intro,
    h('div', { class: 'scroll-x' }, h('table', { class: 'data alloc' },
      h('thead', null, h('tr', null, h('th', null, 'Loss element'), h('th', null, 'Released in zones and halls'), h('th', { class: 'num' }, 'Outdoors'), h('th', { class: 'num' }, 'Unallocated'), h('th', null, 'Allocated'))),
      h('tbody', null, rows))),
    h('div', { class: 'legend' }, h('span', { class: 'legend-item' }, h('span', { class: 'key-box alloc-a' }), 'allocated'), h('span', { class: 'legend-item' }, h('span', { class: 'key-box alloc-u' }), 'unallocated (released outdoors, warned)')));
}

// ---------------------------------------------------------------------------
// Input register
// ---------------------------------------------------------------------------
const regFilter = { q: '', origin: '', kind: '' };

export function registerView() {
  const c = S.check;
  const head = h('h3', null, 'Input register');
  if (!c || !c.register.length) {
    return h('div', { class: 'panel' }, head, h('div', { class: 'muted' }, c && c.errors.length ? 'Resolve the input errors first (see Issues).' : 'Waiting for the input check...'));
  }
  const reg = c.register;
  const by = (k) => reg.reduce((a, e) => { a[e[k]] = (a[e[k]] || 0) + 1; return a; }, {});
  const origins = by('origin');
  const kinds = reg.filter((e) => e.origin === 'user').reduce((a, e) => { a[e.kind] = (a[e.kind] || 0) + 1; return a; }, {});
  const order = ['user', 'preset', 'default', 'auto'];
  const total = reg.length;
  const COL = { user: 1, preset: 2, default: 3, auto: 4 };
  const segBar = h('div', { class: 'seg-bar', role: 'img', 'aria-label': 'register entries by origin' }, order.filter((o) => origins[o]).map((o) => h('span', {
    class: `seg o-${o}`, style: { flex: String(origins[o]), '--k': `var(--series-${COL[o]})` }, title: `${ORIGIN_LABEL[o]}: ${origins[o]}`,
  })));
  const filtered = () => reg.filter((e) => (!regFilter.origin || e.origin === regFilter.origin) && (!regFilter.kind || e.kind === regFilter.kind)
    && (!regFilter.q || `${e.path} ${e.ref} ${e.note} ${e.value}`.toLowerCase().includes(regFilter.q.toLowerCase())));
  const tbody = h('tbody');
  const countEl = h('span', { class: 'muted small' });
  const fill = () => {
    const rows = filtered();
    tbody.innerHTML = '';
    rows.slice(0, 1500).forEach((e) => tbody.appendChild(h('tr', null,
      h('td', { class: 'mono' }, e.path.split(/(?<=[.\]])/).flatMap((p, i) => (i ? [h('wbr'), p] : [p]))), h('td', { class: 'num' }, fmt(e.value)), h('td', null, e.unit),
      h('td', null, h('span', { class: `pill o-${e.origin}` }, ORIGIN_LABEL[e.origin] || e.origin)),
      h('td', null, h('span', { class: `pill k-${e.kind}` }, KIND_LABEL[e.kind] || e.kind)),
      h('td', { class: 'small' }, [e.ref, e.note].filter(Boolean).join(' · ')))));
    countEl.textContent = `${rows.length} of ${total} entries${rows.length > 1500 ? ' (first 1,500 shown)' : ''}`;
  };
  const sel = (key, opts, label) => h('select', { 'aria-label': label, onchange: (e) => { regFilter[key] = e.target.value; fill(); } },
    h('option', { value: '' }, label), opts.map(([v, t]) => h('option', { value: v, selected: regFilter[key] === v }, t)));
  const csv = () => {
    const q = (t) => `"${String(t ?? '').replace(/"/g, '""')}"`;
    const lines = ['path,value,unit,source_kind,reference,note,origin', ...reg.map((e) => [e.path, e.value, e.unit, e.kind, e.ref, e.note, e.origin].map(q).join(','))];
    download('input_register.csv', lines.join('\n'), 'text/csv');
  };
  fill();
  return h('div', { class: 'panel' }, head,
    h('p', { class: 'muted small' }, 'Every value the run would use: entered by you, taken from the preset, a schema default with its basis, or auto-sized by the design pass (8.4.2). This is the register the CLI writes to input_register.csv.'),
    h('div', { class: 'stats' }, order.filter((o) => origins[o]).map((o) => stat(ORIGIN_LABEL[o], String(origins[o]), `${fmt((origins[o] / total) * 100, 0)} % of ${total}`))),
    segBar,
    h('div', { class: 'legend' }, order.filter((o) => origins[o]).map((o) => h('span', { class: 'legend-item' }, h('span', { class: 'key', style: { '--k': `var(--series-${COL[o]})` } }), ORIGIN_LABEL[o]))),
    Object.keys(kinds).length ? h('div', { class: 'muted small kinds' }, 'Entered values by source: ', Object.entries(kinds).map(([k, n]) => h('span', { class: `pill k-${k}` }, `${KIND_LABEL[k] || k} ${n}`))) : null,
    h('div', { class: 'filters' },
      h('input', { type: 'search', placeholder: 'Filter by path, reference or value', value: regFilter.q, oninput: (e) => { regFilter.q = e.target.value; fill(); } }),
      sel('origin', order.map((o) => [o, ORIGIN_LABEL[o]]), 'All origins'),
      sel('kind', Object.keys(KIND_LABEL).map((k) => [k, KIND_LABEL[k]]), 'All source kinds'),
      countEl, h('span', { class: 'spacer' }), h('button', { type: 'button', class: 'btn small', onclick: csv }, 'Download CSV')),
    h('div', { class: 'scroll-x' }, h('table', { class: 'data register' },
      h('colgroup', null, ['32%', '11%', '6%', '11%', '13%', '27%'].map((w) => h('col', { style: { width: w } }))),
      h('thead', null, h('tr', null, h('th', null, 'Path'), h('th', { class: 'num' }, 'Value'), h('th', null, 'Unit'), h('th', null, 'Origin'), h('th', null, 'Source'), h('th', null, 'Reference, rule or basis'))),
      tbody)));
}

// ---------------------------------------------------------------------------
// YAML
// ---------------------------------------------------------------------------
export async function yamlText() {
  const r = await api('/api/yaml/dump', { project: cleanProject(clone(S.project)) });
  return r.text;
}

export function yamlView(applyText) {
  const ta = h('textarea', { class: 'yaml-edit', spellcheck: 'false', rows: 30, 'aria-label': 'Project YAML' });
  const status = h('span', { class: 'muted small' }, 'Loading...');
  let dirty = false;
  ta.addEventListener('input', () => { dirty = true; status.textContent = 'Edited: apply to update the form.'; });
  yamlText().then((t) => { if (!dirty) { ta.value = t; status.textContent = 'Generated from the form.'; } });
  return h('div', { class: 'panel' }, h('h3', null, 'Project YAML'),
    h('p', { class: 'muted small' }, 'The file the CLI reads (quickpue run, quickpue validate). Edit here and apply, or edit in the form. Comments are not kept: YAML written by the editor has none.'),
    h('div', { class: 'filters' },
      h('button', { type: 'button', class: 'btn primary small', onclick: async () => { const ok = await applyText(ta.value); if (ok) { dirty = false; status.textContent = 'Applied.'; } } }, 'Apply edits'),
      h('button', { type: 'button', class: 'btn small', onclick: async () => { ta.value = await yamlText(); dirty = false; status.textContent = 'Regenerated from the form.'; } }, 'Discard edits'),
      h('button', { type: 'button', class: 'btn small', onclick: () => { navigator.clipboard && navigator.clipboard.writeText(ta.value); } }, 'Copy'),
      status),
    ta);
}
