// QuickPUE web input editor: shell, navigation, files, checks and issues.
import {
  S, cleanProject, computeMerged, getAt, initSchema, notify, onChange, redo, resetHistory, snapshot, undo,
} from './model.js';
import { hooks, renderProps, renderTopList, toggle, UI } from './form.js';
import { diagramView, lossView, nav, registerView, scenariosView, weatherView, yamlText, yamlView } from './views.js';
import { hideTip } from './charts.js';
import { api, clone, debounce, download, fmt, h, isObj, stripAttr, toast, unwrap } from './util.js';

const SECTIONS = [
  { id: 'project', title: 'Project', keys: ['preset', 'project', 'water_system'], group: 'Inputs',
    intro: 'Project identity, topology preset and water system. A preset supplies loops, plants, terminal units, zones and electrical defaults; every value it supplies is listed in the input register as an assumption.' },
  { id: 'weather', title: 'Weather', keys: ['weather'], view: weatherView, group: 'Inputs',
    intro: 'EPW weather file (8,760 h) and the design condition used for auto-sizing. Relative paths are relative to the project file.' },
  { id: 'it', title: 'IT load and scenarios', keys: ['it', 'scenarios'], view: scenariosView, group: 'Inputs', owns: ['it', 'scenarios'],
    intro: 'Minimum input (preset, installed IT and liquid fraction) creates the data hall when no halls are listed. Scenarios set the IT load of each 8,760 h run.' },
  { id: 'halls', title: 'Data halls', list: 'halls', group: 'Inputs',
    intro: 'Hall types: design IT per hall, liquid fraction (share of IT heat captured by CDUs), lighting and occupancy gains, and electrical loss heat released in the hall.' },
  { id: 'loops', title: 'Water loops', list: 'loops', group: 'Inputs',
    intro: 'Loops with supply and return temperatures, fluid, supply reset, multi-temperature connection (DT-A to DT-D) and loop pumps.' },
  { id: 'plants', title: 'Cooling plants', list: 'plants', group: 'Inputs',
    intro: 'Plants that cool a loop: chillers (integrated free cooling and adiabatic pads as options), dry coolers, towers, water-side economiser and condenser water.' },
  { id: 'cdus', title: 'CDUs', list: 'cdus', group: 'Inputs', intro: 'Coolant distribution units serving the liquid share of hall IT.' },
  { id: 'fwus', title: 'FWUs', list: 'fwus', group: 'Inputs', intro: 'Fan wall units serving the air share of hall IT.' },
  { id: 'zones', title: 'Support zones', list: 'zones', group: 'Inputs',
    intro: 'Support spaces (electrical, battery, transformer, office...) with gains, envelope, outdoor air and the electrical loss heat they receive.' },
  { id: 'room_units', title: 'Room units', list: 'room_units', group: 'Inputs',
    intro: 'CRAH, CRAC, PAC, VRF, split, FCU, dehumidifier, humidifier and outdoor or exhaust air fans serving zones and halls.' },
  { id: 'electrical', title: 'Electrical', keys: ['electrical'], group: 'Inputs',
    intro: 'UPS (IT and mechanical paths), transformers, switchboard and cable losses, PDU, and loss heat released outdoors.' },
  { id: 'other', title: 'Other end uses', keys: ['other'], group: 'Inputs',
    intro: 'Generator testing, jacket heaters, lifts, fixed loads (DHW, ancillary, office) and PV.' },
  { id: 'boundary', title: 'Boundary and GHG', keys: ['contingency', 'boundary', 'ghg'], group: 'Inputs', owns: ['contingency', 'boundary', 'ghg'],
    intro: 'Design contingency, end uses excluded from PUE and optional greenhouse gas factors.' },
  { id: 'settings', title: 'Settings', keys: ['settings'], group: 'Inputs',
    intro: 'Iteration, sizing and warning settings. Leave a field empty for the documented default.' },
  { id: 'diagram', title: 'System diagram', view: diagramView, group: 'Visualise' },
  { id: 'losses', title: 'Loss heat allocation', view: lossView, group: 'Visualise' },
  { id: 'register', title: 'Input register', view: registerView, group: 'Check' },
  { id: 'yaml', title: 'YAML', view: () => yamlView(applyYaml), group: 'Check' },
];

const OWNER = {};
SECTIONS.forEach((sec) => {
  (sec.owns || (sec.list ? [sec.list] : sec.keys || [])).forEach((k) => { OWNER[k] = sec.id; });
});
OWNER.preset = 'project';
OWNER.water_system = 'project';
OWNER.schema_version = 'project';

let current = 'project';
const els = {};
const DRAFT_KEY = 'quickpue-ui:draft';

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
async function boot() {
  els.main = document.getElementById('main');
  els.nav = document.getElementById('nav');
  els.side = document.getElementById('side');
  els.status = document.getElementById('status');
  els.file = document.getElementById('file');
  try {
    S.meta = await api('/api/meta');
  } catch (e) {
    els.main.textContent = `Cannot reach the QuickPUE editor server: ${e.message}`;
    return;
  }
  initSchema(S.meta.schema);
  document.getElementById('version').textContent = `v${S.meta.version} · schema ${S.meta.schema_version}`;
  hooks.pickFile = pickFile;
  hooks.presetChanged = () => { loadPreset().then(() => notify({ structural: true })); };
  nav.go = goTo;
  onChange(handleChange);
  wireToolbar();
  applyTheme(localStorage.getItem('quickpue-ui:theme') || 'auto');
  const hash = location.hash.replace('#', '');
  if (SECTIONS.some((x) => x.id === hash)) current = hash;
  window.addEventListener('hashchange', () => {
    const id = location.hash.replace('#', '');
    if (SECTIONS.some((x) => x.id === id) && id !== current) { current = id; renderAll(); }
  });
  document.addEventListener('focusout', () => { if (pendingRender) { pendingRender = false; renderSoon(); } });
  window.addEventListener('beforeunload', (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ''; } });

  const draft = readDraft();
  if (S.meta.initial) {
    await openPath(S.meta.initial, true);
    if (draft && draft.path === S.meta.initial && JSON.stringify(draft.project) !== JSON.stringify(S.project)) offerDraft(draft);
  } else if (draft) {
    await setProject(draft.project, draft.path || null, false);
    S.dirty = !!draft.dirty;
    renderAll();
    toast('Restored the last session in this browser.');
  } else {
    await setProject({}, null, false);
    showNew(true);
  }
}

async function setProject(project, path, hasComments) {
  S.project = isObj(project) ? project : {};
  S.path = path;
  S.hasComments = !!hasComments;
  S.dirty = false;
  S.check = null;
  S.register = new Map();
  S.errors = new Map();
  S.weatherKey = null;
  UI.open.clear();
  UI.closed.clear();
  UI.attr.clear();
  resetHistory();
  await loadPreset();
  computeMerged();
  S.hints = refChecks(S.merged);
  renderAll();
  runCheck();
  loadWeather();
}

// ---------------------------------------------------------------------------
// Change pipeline
// ---------------------------------------------------------------------------
let pendingRender = false;
let renderTimer = null;

function handleChange(o) {
  S.dirty = true;
  snapshotSoon();
  computeMerged();
  S.hints = refChecks(S.merged);
  scheduleCheck();
  saveDraftSoon();
  sideYamlSoon();
  renderNav();
  renderTitle();
  loadWeatherSoon();
  if (o.structural) renderMain();
  else if (o.rerender) renderSoon();
}

const snapshotSoon = debounce(snapshot, 350);
const scheduleCheck = debounce(runCheck, 450);
const saveDraftSoon = debounce(() => {
  try { localStorage.setItem(DRAFT_KEY, JSON.stringify({ path: S.path, project: S.project, dirty: S.dirty, t: Date.now() })); } catch (e) { /* storage unavailable */ }
}, 800);

function isTyping() {
  const a = document.activeElement;
  return a && els.main.contains(a) && (a.tagName === 'TEXTAREA' || (a.tagName === 'INPUT' && a.type !== 'checkbox'));
}

function renderSoon() {
  clearTimeout(renderTimer);
  renderTimer = setTimeout(renderMain, 0);
}

function requestRender() {
  if (isTyping()) pendingRender = true;
  else renderSoon();
}

// ---------------------------------------------------------------------------
// Check (schema, links and sizing on the server)
// ---------------------------------------------------------------------------
let checkSeq = 0;

async function runCheck() {
  const seq = ++checkSeq;
  const merged = clone(S.merged);
  setStatus('busy', 'Checking...');
  try {
    const r = await api('/api/check', { project: cleanProject(clone(S.project)), project_path: S.path, full: true });
    if (seq !== checkSeq) return;
    S.check = r;
    S.errors = new Map();
    S.errorList = r.errors.map((e) => {
      const { key, prefixes } = locToKey(e.loc, merged);
      if (!S.errors.has(key)) S.errors.set(key, []);
      S.errors.get(key).push(e.msg);
      return { ...e, key, prefixes };
    });
    S.register = new Map(r.register.map((e) => [e.path, e]));
    updateStatus();
    renderSide();
    renderNav();
    requestRender();
  } catch (e) {
    if (seq !== checkSeq) return;
    setStatus('err', 'Check failed');
    S.check = { ok: false, stage: 'load', errors: [{ loc: [], msg: e.message }], warnings: [], register: [], assumptions: [] };
    S.errorList = [{ loc: [], msg: e.message, key: '', prefixes: [] }];
    renderSide();
  }
}

function locToKey(loc, merged) {
  let m = merged;
  let key = '';
  const prefixes = [];
  for (const seg of loc) {
    if (typeof seg === 'number') {
      const item = Array.isArray(m) ? m[seg] : undefined;
      key += `[${isObj(item) && item.name !== undefined ? item.name : seg}]`;
      m = item;
    } else {
      key += (key ? '.' : '') + seg;
      m = isObj(m) ? m[seg] : undefined;
    }
    prefixes.push(key);
  }
  return { key, prefixes };
}

function updateStatus() {
  const c = S.check;
  if (!c) return setStatus('busy', 'Checking...');
  const nErr = c.errors.length;
  const nHint = [...S.hints.values()].reduce((a, v) => a + v.length, 0);
  if (nErr) return setStatus('err', `${nErr} error${nErr > 1 ? 's' : ''}`);
  if (c.stage === 'complete') {
    const nW = c.warnings.length + nHint;
    return setStatus(nW ? 'warn' : 'ok', nW ? `Valid, ${nW} warning${nW > 1 ? 's' : ''}` : 'Valid');
  }
  return setStatus('warn', 'Schema valid');
}

function setStatus(kind, text) {
  els.status.className = `status s-${kind}`;
  els.status.innerHTML = '';
  els.status.append(h('span', { class: 'status-icon', 'aria-hidden': 'true' }, { ok: '✓', warn: '!', err: '×', busy: '…' }[kind] || ''), text);
  els.status.title = kind === 'ok' ? 'Schema, references and auto-sizing checks pass (as quickpue validate)' : text;
}

// Client-side reference checks (instant; the server check is authoritative)
function refChecks(m) {
  const out = new Map();
  const add = (k, msg) => { if (!out.has(k)) out.set(k, []); out.get(k).push(msg); };
  const nm = (list) => new Set((Array.isArray(list) ? list : []).filter(isObj).map((x) => x.name));
  const loops = nm(m.loops);
  const halls = nm(m.halls);
  const zones = nm(m.zones);
  const dup = (list, base) => {
    const seen = new Set();
    (Array.isArray(list) ? list : []).filter(isObj).forEach((x) => {
      if (seen.has(x.name)) add(`${base}[${x.name}]`, `duplicate name "${x.name}"`);
      seen.add(x.name);
    });
  };
  ['halls', 'loops', 'plants', 'cdus', 'fwus', 'zones', 'room_units'].forEach((k) => dup(m[k], k));
  const loopRef = (k, v) => { if (v && !loops.has(v)) add(k, `loop "${v}" is not defined`); };
  (m.cdus || []).filter(isObj).forEach((c) => {
    (c.serves || []).forEach((x) => { if (!halls.has(x)) add(`cdus[${c.name}].serves`, `hall "${x}" is not defined`); });
    loopRef(`cdus[${c.name}].loop`, c.loop);
  });
  (m.fwus || []).filter(isObj).forEach((c) => {
    (c.serves || []).forEach((x) => { if (!halls.has(x)) add(`fwus[${c.name}].serves`, `hall "${x}" is not defined`); });
    loopRef(`fwus[${c.name}].loop`, c.loop);
  });
  (m.room_units || []).filter(isObj).forEach((r) => {
    (r.serves || []).forEach((x) => {
      const z = isObj(x) ? x.zone : x;
      if (!zones.has(z) && !halls.has(z)) add(`room_units[${r.name}].serves`, `zone or hall "${z}" is not defined`);
    });
    loopRef(`room_units[${r.name}].loop`, r.loop);
  });
  (m.plants || []).filter(isObj).forEach((p) => loopRef(`plants[${p.name}].loop`, p.loop));
  (m.loops || []).filter(isObj).forEach((l) => loopRef(`loops[${l.name}].from_loop`, l.from_loop));
  ((m.other || {}).loads || []).filter(isObj).forEach((x) => {
    if (x.heat_to_zone && !zones.has(x.heat_to_zone)) add(`other.loads[${x.name}].heat_to_zone`, `zone "${x.heat_to_zone}" is not defined`);
  });
  return out;
}

// ---------------------------------------------------------------------------
// Preset and weather
// ---------------------------------------------------------------------------
async function loadPreset() {
  const id = unwrap(S.project.preset);
  if (!id) {
    S.template = null;
    S.presetInfo = null;
    return;
  }
  try {
    const p = await api(`/api/preset?id=${encodeURIComponent(id)}${S.path ? `&project_path=${encodeURIComponent(S.path)}` : ''}`);
    S.template = stripAttr(p.template || {});
    S.presetInfo = p;
  } catch (e) {
    S.template = null;
    S.presetInfo = null;
    toast(e.message, 'error');
  }
  computeMerged();
}

const loadWeatherSoon = debounce(() => loadWeather(), 500);

async function loadWeather() {
  const epw = (S.merged.weather || {}).epw;
  const key = `${S.path}|${epw}`;
  if (key === S.weatherKey) return;
  S.weatherKey = key;
  S.weather = null;
  S.weatherError = null;
  if (!epw) {
    if (current === 'weather') requestRender();
    return;
  }
  try {
    const w = await api(`/api/weather?epw=${encodeURIComponent(epw)}${S.path ? `&project_path=${encodeURIComponent(S.path)}` : ''}`);
    if (S.weatherKey !== key) return;
    S.weather = w;
  } catch (e) {
    if (S.weatherKey !== key) return;
    S.weatherError = e.message;
  }
  if (['weather', 'plants'].includes(current)) requestRender();
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------
function renderAll() {
  renderNav();
  renderTitle();
  renderMain();
  renderSide();
  updateStatus();
}

function sectionIssues(id) {
  let err = 0;
  let warn = 0;
  for (const e of S.errorList || []) if (OWNER[(e.key || '').split(/[.[]/)[0]] === id) err++;
  for (const [k, v] of S.hints) if (OWNER[k.split(/[.[]/)[0]] === id) warn += v.length;
  return { err, warn };
}

function renderNav() {
  const groups = {};
  SECTIONS.forEach((sec) => (groups[sec.group] = groups[sec.group] || []).push(sec));
  els.nav.innerHTML = '';
  const m = S.merged || {};
  for (const [g, secs] of Object.entries(groups)) {
    els.nav.append(h('div', { class: 'nav-group' }, g));
    for (const sec of secs) {
      const n = sec.list && Array.isArray(m[sec.list]) ? m[sec.list].length : null;
      const iss = sectionIssues(sec.id);
      els.nav.append(h('a', {
        href: `#${sec.id}`, class: `nav-item ${current === sec.id ? 'on' : ''}`, 'aria-current': current === sec.id ? 'page' : undefined,
        onclick: (e) => { e.preventDefault(); goTo(sec.id); },
      }, h('span', { class: 'nav-label' }, sec.title),
      iss.err ? h('span', { class: 'dot err', title: `${iss.err} error(s)` }, String(iss.err)) : (iss.warn ? h('span', { class: 'dot warn', title: `${iss.warn} warning(s)` }, String(iss.warn)) : null),
      n !== null ? h('span', { class: 'nav-count' }, String(n)) : null));
    }
  }
  const sel = document.getElementById('nav-select');
  if (sel) {
    sel.innerHTML = '';
    SECTIONS.forEach((sec) => sel.append(h('option', { value: sec.id, selected: sec.id === current }, `${sec.group}: ${sec.title}`)));
  }
}

function renderTitle() {
  els.file.innerHTML = '';
  const name = unwrap((S.project.project || {}).name);
  els.file.append(...[h('span', { class: 'file-name', title: S.path ? `${S.meta.root}/${S.path}` : 'not saved yet' }, S.path || 'Untitled (not saved)'),
    name ? h('span', { class: 'muted' }, ` · ${name}`) : null,
    S.dirty ? h('span', { class: 'dirty', title: 'unsaved changes' }, ' ●') : null].filter(Boolean));
  document.title = `${S.dirty ? '* ' : ''}${S.path ? S.path.split('/').pop() : 'Untitled'} · QuickPUE inputs`;
}

function activeFk() {
  const a = document.activeElement;
  if (!a || !els.main.contains(a) || !a.dataset || !a.dataset.fk) return null;
  return { fk: a.dataset.fk, start: a.selectionStart, end: a.selectionEnd };
}

function renderMain() {
  clearTimeout(renderTimer);
  hideTip();
  const sec = SECTIONS.find((x) => x.id === current) || SECTIONS[0];
  const scroll = els.main.scrollTop;
  const focus = activeFk();
  els.main.innerHTML = '';
  if (draftBanner) els.main.append(draftBanner);
  els.main.append(h('div', { class: 'sec-head' }, h('h2', null, sec.title), sec.intro ? h('p', { class: 'intro' }, sec.intro) : null));
  try {
    if (sec.list) {
      if (sec.list === 'halls' && !(S.merged.halls || []).some((x) => !x._fromIt) && isObj(S.merged.it)) {
        const hl = (S.merged.halls || [])[0];
        els.main.append(h('div', { class: 'note' }, `No halls are listed, so the minimum-input IT block creates "${hl ? hl.name : 'Data hall'}" (${hl ? `${hl.count} × ${fmt(hl.it_kw)} kW, liquid ${fmt(hl.liquid_fraction)}` : ''}). Add a hall to define halls explicitly; the IT block is then ignored.`));
      }
      const derived = sec.list === 'halls' && (S.merged.halls || []).some((x) => x._fromIt);
      els.main.append(renderTopList(sec.list, derived ? 'No halls listed.' : `No ${sec.title.toLowerCase()} in this project${S.template ? ' or its preset' : ''}.`));
    }
    if (sec.keys) els.main.append(...renderProps(S.root, [], sec.keys));
    if (sec.view) els.main.append(sec.view());
  } catch (e) {
    console.error(e);
    els.main.append(h('div', { class: 'msg err' }, `Cannot display this section: ${e.message}`));
  }
  els.main.scrollTop = scroll;
  if (focus) {
    const el = els.main.querySelector(`[data-fk="${CSS.escape(focus.fk)}"]`);
    if (el) {
      el.focus({ preventScroll: true });
      try { if (focus.start !== null && focus.start !== undefined) el.setSelectionRange(focus.start, focus.end); } catch (e) { /* not a text input */ }
    }
  }
}

function goTo(id, key) {
  if (!SECTIONS.some((x) => x.id === id)) id = OWNER[id] || 'project';
  current = id;
  if (location.hash !== `#${id}`) history.replaceState(null, '', `#${id}`);
  if (key) for (const p of keyPrefixes(key)) toggle(p, true);
  renderNav();
  renderMain();
  if (key) {
    let el = null;
    for (const p of [key, ...keyPrefixes(key).reverse()]) {
      el = els.main.querySelector(`[data-key="${CSS.escape(p)}"]`);
      if (el) break;
    }
    if (el) {
      el.scrollIntoView({ block: 'center' });
      el.classList.add('flash');
      setTimeout(() => el.classList.remove('flash'), 1600);
    }
  } else {
    els.main.scrollTop = 0;
  }
}

function keyPrefixes(key) {
  const out = [];
  let i = 0;
  let cur = '';
  while (i < key.length) {
    const c = key[i];
    if (c === '[') {
      if (cur) out.push(cur);
      const j = key.indexOf(']', i);
      cur += key.slice(i, j + 1);
      i = j + 1;
    } else if (c === '.') {
      out.push(cur);
      cur += c;
      i++;
    } else {
      cur += c;
      i++;
    }
  }
  return [...new Set(out.filter(Boolean))];
}

// Issues / YAML side panel
let sideTab = 'issues';

function renderSide() {
  els.side.innerHTML = '';
  const tabs = h('div', { class: 'tabs', role: 'tablist' },
    ['issues', 'yaml'].map((t) => h('button', {
      type: 'button', role: 'tab', class: `tab ${sideTab === t ? 'on' : ''}`, 'aria-selected': sideTab === t ? 'true' : 'false',
      onclick: () => { sideTab = t; renderSide(); },
    }, t === 'issues' ? 'Issues' : 'YAML preview')));
  els.side.append(tabs);
  if (sideTab === 'yaml') {
    const pre = h('pre', { class: 'yaml-prev' }, '...');
    els.side.append(pre);
    yamlText().then((t) => { pre.textContent = t; }).catch((e) => { pre.textContent = e.message; });
    return;
  }
  const c = S.check;
  const list = h('div', { class: 'issues' });
  const item = (cls, title, msg, key) => h('div', { class: `issue ${cls}` },
    h('div', { class: 'issue-head' }, h('span', { class: 'issue-icon', 'aria-hidden': 'true' }, cls === 'err' ? '×' : '!'),
      h('span', { class: 'issue-path' }, title || (c && c.stage === 'sizing' ? 'sizing and links' : 'project')),
      key ? h('button', { type: 'button', class: 'link small', onclick: () => goTo(OWNER[key.split(/[.[]/)[0]] || 'project', key) }, 'Go') : null),
    h('div', { class: 'issue-msg' }, msg));
  const errs = S.errorList || [];
  if (!c) list.append(h('div', { class: 'muted' }, 'Checking...'));
  if (c) {
    const stageNote = { schema: 'Schema check', load: 'Loading', sizing: 'Sizing (design pass)', complete: 'Complete' }[c.stage] || c.stage;
    list.append(h('div', { class: 'issue-sum' }, c.errors.length ? `${c.errors.length} error(s) at stage: ${stageNote}` : `Inputs pass the schema, reference and sizing checks${c.design_label ? ` (sizing at ${c.design_label})` : ''}.`));
  }
  errs.forEach((e) => list.append(item('err', e.key, e.msg, e.key)));
  for (const [k, v] of S.hints) v.forEach((m) => list.append(item('warn', k, m, k)));
  if (c) (c.warnings || []).forEach((w) => list.append(item('warn', 'engine', w)));
  if (c && c.assumptions && c.assumptions.length) {
    list.append(h('details', { class: 'assume' }, h('summary', null, `Assumptions applied (${c.assumptions.length})`), c.assumptions.map((a) => h('p', { class: 'small' }, a))));
  }
  els.side.append(list);
}

const sideYamlSoon = debounce(() => { if (sideTab === 'yaml') renderSide(); }, 400);

// ---------------------------------------------------------------------------
// Files
// ---------------------------------------------------------------------------
async function openPath(path, quiet) {
  try {
    const r = await api(`/api/file?path=${encodeURIComponent(path)}`);
    await setProject(r.project, r.path, r.has_comments);
    clearDraft();
    if (!quiet) toast(`Opened ${r.path}`);
    if (r.has_comments) toast(`${r.path} has comments; saving from the editor writes the YAML without them.`, 'warn');
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function save(as) {
  let path = S.path;
  let overwrite = !!S.path;
  if (as || !path) {
    const name = (unwrap((S.project.project || {}).name) || 'project').replace(/[^\w.-]+/g, '_');
    path = await promptText('Save as', 'Path of the YAML file, relative to the editor root', S.path || `${name}.yaml`, S.meta.root);
    if (!path) return;
    if (!/\.ya?ml$/i.test(path)) path += '.yaml';
    overwrite = false;
  }
  if (overwrite && S.hasComments) {
    const ok = await confirmBox('Overwrite file with comments?', `${path} contains comments. The editor writes plain YAML without them. Overwrite it, or use Save as to keep the original.`, 'Overwrite');
    if (!ok) return;
  }
  try {
    let r;
    try {
      r = await api('/api/save', { path, project: cleanProject(clone(S.project)), overwrite, previous_path: S.path });
    } catch (e) {
      if (e.status !== 409) throw e;
      const ok = await confirmBox('File exists', `${path} already exists. Replace it?`, 'Replace');
      if (!ok) return;
      r = await api('/api/save', { path, project: cleanProject(clone(S.project)), overwrite: true, previous_path: S.path });
    }
    const moved = r.path !== S.path;
    if (r.notes.length) {
      S.project = r.project;
      toast(`Saved ${r.path}. Paths rebased: ${r.notes.join('; ')}`, 'warn');
    } else {
      toast(`Saved ${r.path}`);
    }
    S.path = r.path;
    S.dirty = false;
    S.hasComments = false;
    clearDraft();
    if (moved) { S.weatherKey = null; await loadPreset(); computeMerged(); runCheck(); loadWeather(); }
    renderAll();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function downloadYaml() {
  const t = await yamlText();
  const name = S.path ? S.path.split('/').pop() : `${(unwrap((S.project.project || {}).name) || 'project').replace(/[^\w.-]+/g, '_')}.yaml`;
  download(name, t, 'text/yaml');
}

async function applyYaml(text) {
  try {
    const r = await api('/api/yaml/parse', { text });
    if (!isObj(r.value)) throw new Error('the YAML must be a mapping (key: value pairs)');
    S.project = r.value;
    await loadPreset();
    notify({ structural: true });
    toast('YAML applied to the form.');
    return true;
  } catch (e) {
    toast(e.message, 'error');
    return false;
  }
}

function readDraft() {
  try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); } catch (e) { return null; }
}

function clearDraft() {
  try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* ignore */ }
}

let draftBanner = null;
function offerDraft(d) {
  draftBanner = h('div', { class: 'note banner' }, `Unsaved edits to ${d.path} from ${new Date(d.t).toLocaleString()} were found in this browser.`,
    h('button', { type: 'button', class: 'btn small primary', onclick: async () => { draftBanner = null; S.project = d.project; notify({ structural: true }); } }, 'Restore them'),
    h('button', { type: 'button', class: 'btn small', onclick: () => { draftBanner = null; clearDraft(); renderMain(); } }, 'Discard'));
  renderMain();
}

// ---------------------------------------------------------------------------
// Dialogs
// ---------------------------------------------------------------------------
function modal(title, body, buttons, opts = {}) {
  return new Promise((resolve) => {
    const dlg = document.getElementById('dlg');
    dlg.innerHTML = '';
    let result;
    const close = (v) => { result = v; dlg.close(); };
    const form = h('form', { method: 'dialog', class: `dlg ${opts.wide ? 'wide' : ''}`, onsubmit: (e) => { e.preventDefault(); const def = buttons.find((b) => b.primary); if (def) close(def.value()); } },
      h('div', { class: 'dlg-head' }, h('h3', null, title), h('button', { type: 'button', class: 'x', 'aria-label': 'Close', onclick: () => close(undefined) }, '×')),
      h('div', { class: 'dlg-body' }, body),
      h('div', { class: 'dlg-foot' }, buttons.map((b) => h('button', { type: b.primary ? 'submit' : 'button', class: `btn ${b.primary ? 'primary' : ''} ${b.danger ? 'danger' : ''}`, onclick: b.primary ? undefined : () => close(b.value ? b.value() : undefined) }, b.label))));
    dlg.append(form);
    dlg.onclose = () => resolve(result);
    dlg.showModal();
    const first = form.querySelector('[autofocus]') || form.querySelector('input, select');
    if (first) first.focus();
  });
}

function confirmBox(title, text, ok) {
  return modal(title, h('p', null, text), [{ label: 'Cancel', value: () => false }, { label: ok, primary: true, value: () => true }]);
}

function promptText(title, label, value, root) {
  const input = h('input', { type: 'text', value, autofocus: true, class: 'wide-input', spellcheck: 'false' });
  return modal(title, [h('label', { class: 'stack' }, label, input), root ? h('div', { class: 'muted small' }, `Root: ${root}`) : null],
    [{ label: 'Cancel' }, { label: 'Save', primary: true, value: () => input.value.trim() }]);
}

async function fileList(kind, relative) {
  try {
    return await api(`/api/files?kind=${kind}${relative && S.path ? `&relative_to=${encodeURIComponent(S.path)}` : ''}`);
  } catch (e) {
    toast(e.message, 'error');
    return [];
  }
}

function filePicker(files, label, onPick) {
  const q = h('input', { type: 'search', placeholder: 'Filter', autofocus: true });
  const ul = h('ul', { class: 'files' });
  const fill = () => {
    ul.innerHTML = '';
    const t = q.value.toLowerCase();
    const shown = files.filter((f) => f.path.toLowerCase().includes(t));
    shown.forEach((f) => ul.append(h('li', null, h('button', { type: 'button', class: 'file-btn', onclick: () => onPick(f) }, h('span', null, f.path), h('span', { class: 'muted small' }, `${fmt(f.size / 1024, 0)} kB`)))));
    if (!shown.length) ul.append(h('li', { class: 'muted' }, `No ${label} found under the editor root.`));
  };
  q.addEventListener('input', fill);
  fill();
  return [q, ul];
}

async function pickFile(kind) {
  const files = await fileList(kind, true);
  let chosen;
  const p = modal(kind === 'epw' ? 'Choose a weather file' : 'Choose a CSV file', [
    h('div', { class: 'muted small' }, `Files under ${S.meta.root}. The path is stored relative to ${S.path ? 'the project file' : 'the editor root (save the project to fix its folder)'}.`),
    filePicker(files, kind === 'epw' ? 'EPW files' : 'CSV files', (f) => { chosen = f.rel; document.getElementById('dlg').close(); }),
  ], [{ label: 'Cancel' }], { wide: true });
  await p;
  return chosen;
}

async function showOpen() {
  if (S.dirty && !(await confirmBox('Discard unsaved changes?', 'The current project has unsaved changes.', 'Discard'))) return;
  const files = await fileList('project', false);
  const fileInput = h('input', { type: 'file', accept: '.yaml,.yml,.json', class: 'file-input' });
  let chosen;
  fileInput.addEventListener('change', async () => {
    const f = fileInput.files[0];
    if (!f) return;
    const text = await f.text();
    try {
      const r = f.name.endsWith('.json') ? { value: JSON.parse(text) } : await api('/api/yaml/parse', { text });
      if (!isObj(r.value)) throw new Error('not a project mapping');
      chosen = { project: r.value, name: f.name };
      document.getElementById('dlg').close();
    } catch (e) {
      toast(`${f.name}: ${e.message}`, 'error');
    }
  });
  await modal('Open a project', [
    h('div', { class: 'muted small' }, `Project files (YAML or JSON) under ${S.meta.root}. Python project scripts are not opened.`),
    filePicker(files, 'project files', (f) => { chosen = f.path; document.getElementById('dlg').close(); }),
    h('div', { class: 'or' }, 'or load a file from this computer (relative paths then resolve against the editor root)'), fileInput,
  ], [{ label: 'Cancel' }], { wide: true });
  if (typeof chosen === 'string') await openPath(chosen);
  else if (chosen) {
    await setProject(chosen.project, null, false);
    S.dirty = true;
    renderTitle();
    toast(`Loaded ${chosen.name}; use Save as to store it under the editor root.`);
  }
}

async function showNew(first) {
  if (!first && S.dirty && !(await confirmBox('Discard unsaved changes?', 'The current project has unsaved changes.', 'Discard'))) return;
  const epws = await fileList('epw', false);
  const name = h('input', { type: 'text', placeholder: 'Project name', autofocus: true });
  const preset = h('select', null, h('option', { value: '' }, 'None: full equipment schedule'),
    S.meta.presets.map((p) => h('option', { value: p.id, selected: p.id === 'LC-ACC-IFC-AD' }, `${p.id}: ${p.name}`)));
  const desc = h('div', { class: 'muted small preset-desc' });
  const showDesc = () => { const p = S.meta.presets.find((x) => x.id === preset.value); desc.textContent = p ? `${p.water_system}, ${p.plant_type}. ${p.description || ''}` : 'Enter halls, loops, plants and terminal units yourself.'; };
  preset.addEventListener('change', showDesc);
  showDesc();
  const it = h('input', { type: 'text', inputmode: 'decimal', placeholder: 'e.g. 10000' });
  const lf = h('input', { type: 'text', inputmode: 'decimal', placeholder: 'e.g. 0.8 (0 for air-cooled halls)' });
  const epw = h('select', null, h('option', { value: '' }, 'Choose later'), epws.map((f) => h('option', { value: f.path }, f.path)));
  const res = await modal('New project', h('div', { class: 'form-grid' },
    h('label', null, 'Name', name),
    h('label', null, 'Topology preset', preset), desc,
    h('label', null, 'Installed IT (kW)', it),
    h('label', null, 'Liquid fraction (0 to 1)', lf),
    h('label', null, 'Weather file', epw),
    h('p', { class: 'muted small' }, 'Only what you enter here is written to the project. Everything else comes from the preset, the documented defaults or auto-sizing, and is listed in the input register.')),
  [...(first ? [{ label: 'Open a file instead', value: () => 'open' }] : [{ label: 'Cancel' }]), { label: 'Create', primary: true, value: () => 'create' }], { wide: true });
  if (res === 'open') return showOpen();
  if (res !== 'create') return;
  const p = {};
  if (preset.value) p.preset = preset.value;
  if (name.value.trim()) p.project = { name: name.value.trim() };
  p.weather = epw.value ? { epw: epw.value } : {};
  const itv = Number(it.value);
  const lfv = Number(lf.value);
  if (it.value.trim() && Number.isFinite(itv)) {
    p.it = { installed_kw: itv };
    if (lf.value.trim() && Number.isFinite(lfv)) p.it.liquid_fraction = lfv;
  }
  await setProject(p, null, false);
  S.dirty = true;
  goTo(epw.value ? 'it' : 'weather');
}

// ---------------------------------------------------------------------------
// Toolbar, theme, shortcuts
// ---------------------------------------------------------------------------
function wireToolbar() {
  const on = (id, fn) => document.getElementById(id).addEventListener('click', fn);
  on('b-new', () => showNew(false));
  on('b-open', showOpen);
  on('b-save', () => save(false));
  on('b-saveas', () => save(true));
  on('b-download', downloadYaml);
  on('b-undo', doUndo);
  on('b-redo', doRedo);
  on('b-theme', () => {
    const order = ['auto', 'light', 'dark'];
    const cur = localStorage.getItem('quickpue-ui:theme') || 'auto';
    applyTheme(order[(order.indexOf(cur) + 1) % 3]);
  });
  on('b-side', () => document.body.classList.toggle('side-open'));
  document.getElementById('nav-select').addEventListener('change', (e) => goTo(e.target.value));
  document.addEventListener('keydown', (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); save(e.shiftKey); }
    const inText = ['INPUT', 'TEXTAREA'].includes(document.activeElement && document.activeElement.tagName);
    if (mod && !inText && e.key.toLowerCase() === 'z') { e.preventDefault(); if (e.shiftKey) doRedo(); else doUndo(); }
    if (mod && !inText && e.key.toLowerCase() === 'y') { e.preventDefault(); doRedo(); }
  });
}

async function doUndo() {
  snapshot();
  if (undo()) { await loadPreset(); notify({ structural: true }); } else toast('Nothing to undo');
}

async function doRedo() {
  if (redo()) { await loadPreset(); notify({ structural: true }); } else toast('Nothing to redo');
}

function applyTheme(t) {
  try { localStorage.setItem('quickpue-ui:theme', t); } catch (e) { /* ignore */ }
  if (t === 'auto') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  const b = document.getElementById('b-theme');
  b.textContent = { auto: 'Theme: auto', light: 'Theme: light', dark: 'Theme: dark' }[t];
  if (S.meta && ['weather'].includes(current)) renderMain();
}

window.quickpue = { S, getAt, goTo, openPath, setProject };
boot();
