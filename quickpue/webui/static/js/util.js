// Small DOM, formatting and path helpers shared by the editor modules.

export const ATTR_KEYS = ['value', 'unit', 'source', 'note'];

export function h(tag, attrs, ...children) {
  const el = document.createElementNS(
    attrs && attrs.svg ? 'http://www.w3.org/2000/svg' : 'http://www.w3.org/1999/xhtml', tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'svg' || v === undefined || v === null || v === false) continue;
      if (k === 'class') el.setAttribute('class', v);
      else if (k === 'style' && typeof v === 'object') {
        for (const [p, x] of Object.entries(v)) {
          if (p.startsWith('--')) el.style.setProperty(p, x);
          else el.style[p] = x;
        }
      }
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k === 'value' && !attrs.svg) continue;
      else if (k === 'checked' || k === 'disabled' || k === 'selected' || k === 'readOnly') el[k] = !!v;
      else el.setAttribute(k, v === true ? '' : v);
    }
  }
  append(el, children);
  if (attrs && !attrs.svg && attrs.value !== undefined && attrs.value !== null) el.value = attrs.value;
  return el;
}

export function s(tag, attrs, ...children) {
  return h(tag, { ...(attrs || {}), svg: true }, ...children);
}

function append(el, children) {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else if (c instanceof Node) el.appendChild(c);
    else el.appendChild(document.createTextNode(String(c)));
  }
}

export const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
export const isAttr = (v) => isObj(v) && 'value' in v && Object.keys(v).every((k) => ATTR_KEYS.includes(k));
export const unwrap = (v) => (isAttr(v) ? v.value : v);
export const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));

export function stripAttr(v) {
  if (isAttr(v)) return stripAttr(v.value);
  if (Array.isArray(v)) return v.map(stripAttr);
  if (isObj(v)) {
    const o = {};
    for (const [k, x] of Object.entries(v)) o[k] = stripAttr(x);
    return o;
  }
  return v;
}

export function debounce(fn, ms) {
  let t = null;
  const d = (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
  d.cancel = () => clearTimeout(t);
  return d;
}

export async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  };
  const r = await fetch(path, opt);
  let data;
  try {
    data = await r.json();
  } catch (e) {
    throw new Error(`${path}: ${r.status} ${r.statusText}`);
  }
  if (!r.ok) {
    const err = new Error(data.error || `${r.status}`);
    err.status = r.status;
    throw err;
  }
  return data;
}

// Register-style key for a path: plants[Plant].chillers[ACC].capacity_kw
export function pathKey(path, nameAt) {
  let out = '';
  path.forEach((seg, i) => {
    if (typeof seg === 'number' || (isObj(seg) && 'n' in seg)) {
      const name = isObj(seg) ? seg.n : nameAt(path.slice(0, i + 1));
      out += `[${name !== undefined && name !== null && name !== '' ? name : (isObj(seg) ? '?' : seg)}]`;
    } else {
      out += (out ? '.' : '') + seg;
    }
  });
  return out;
}

// ---------------------------------------------------------------------------
// Units and labels. The unit of a field follows its name suffix (inputs._unit_for).
// ---------------------------------------------------------------------------
export function unitSuffix(key) {
  const k = String(key).toLowerCase();
  for (const suf of ['kwh', 'l_s', 'kw', 'pa', 'm2', 'pct']) if (k.endsWith('_' + suf)) return suf;
  for (const suf of ['c', 'k', 'm', 'l']) if (k.endsWith('_' + suf)) return suf;
  return null;
}

export const UNIT_LABEL = {
  kw: 'kW', kwh: 'kWh', l_s: 'L/s', pa: 'Pa', m2: 'm²', m: 'm', c: '°C', k: 'K', l: 'L', pct: '%',
};

const ACR = {
  cop: 'COP', lwt: 'LWT', ect: 'ECT', tcs: 'TCS', ups: 'UPS', it: 'IT', pv: 'PV', ghg: 'GHG', dhw: 'DHW',
  oa: 'OA', rh: 'RH', ua: 'UA', epw: 'EPW', plr: 'PLR', eflh: 'EFLH', coc: 'Cycles of concentration',
  hx: 'HX', cw: 'CW', wse: 'WSE', cdu: 'CDU', cdus: 'CDUs', fwu: 'FWU', fwus: 'FWUs', ach: 'ACH', pdu: 'PDU',
  hv: 'HV', db: 'DB', wb: 'WB', kva: 'kVA', id: 'ID', tx: 'TX', dx: 'DX', vrf: 'VRF', pac: 'PAC',
  crah: 'CRAH', crac: 'CRAC', fcu: 'FCU', oaf: 'OAF', eaf: 'EAF', ws: 'WS', cp: 'CP', ups_it: 'UPS IT',
};

const SPECIAL = {
  kw: ['Power', 'kW'], kw_peak: ['Peak', 'kWp'], percent: ['Loss', '%'], it_kw: ['IT capacity per hall', 'kW'],
  installed_kw: ['Installed IT', 'kW'], lighting_w_m2: ['Lighting', 'W/m²'], equipment_w_m2: ['Equipment', 'W/m²'],
  u_wall: ['Wall U value', 'W/m²K'], u_roof: ['Roof U value', 'W/m²K'], eflh_hours: ['EFLH', 'h'],
  trip_time_s: ['Trip time', 's'], standby_hours: ['Standby hours', 'h/yr'], hours_per_test: ['Hours per test', 'h'],
  infiltration_ach: ['Infiltration', 'ACH'], rating_kva: ['Rating', 'kVA'],
  occupancy_m2_per_person: ['Occupancy', 'm²/person'], density_kw_per_m2: ['IT density', 'kW/m²'],
  electricity_kg_per_kwh: ['Electricity factor', 'kg/kWh'], diesel_kg_per_l: ['Diesel factor', 'kg/L'],
  diesel_mwh_per_l: ['Diesel energy content', 'MWh/L'], fuel_l_per_h: ['Fuel use', 'L/h'],
  server_airflow_l_s_per_kw: ['Server airflow', 'L/s per kW'], r_th_k_per_kw: ['Thermal resistance', 'K/kW'],
  cop_ambient_slope_per_k: ['COP change', 'per K'], kw_per_generator: ['Heater power', 'kW each'],
  specific_yield_kwh_per_kw: ['Specific yield', 'kWh/kWp'], annual_litres: ['Annual diesel', 'L'],
  t_amb_low_c: ['Ambient low', '°C'], t_amb_high_c: ['Ambient high', '°C'],
  supply_low_c: ['Supply at ambient low', '°C'], supply_high_c: ['Supply at ambient high', '°C'],
  min_c: ['Minimum', '°C'], max_c: ['Maximum', '°C'], t_on_c: ['Full on at or below', '°C'],
  t_off_c: ['Off at or above', '°C'], tests_per_year: ['Tests per year', ''], trips_per_year: ['Trips per year', ''],
  activation_c: ['Activation', '°C DB'], f_min: ['Minimum flow fraction', ''], liquid_fraction: ['Liquid fraction', ''],
  m2: ['Area', 'm²'], rated_ect_c: ['Rated entering condenser', '°C'], rated_lwt_c: ['Rated leaving water', '°C'],
  rated_water_in_c: ['Rated water in', '°C'], rated_water_out_c: ['Rated water out', '°C'],
  rated_air_c: ['Rated air', '°C'], design_wb_c: ['Design wet bulb', '°C'], tcs_supply_c: ['TCS supply', '°C'],
  t_junction_max_c: ['Max junction', '°C'], recirculation_k: ['Recirculation', 'K'],
  stage_up_plr: ['Stage-up PLR', ''], min_plr: ['Minimum PLR', ''], heat_to_stream: ['Heat to stream', 'fraction'],
  glycol_pct: ['Glycol', '%'], rh_max_pct: ['RH max', '%'], drift_fraction: ['Drift', 'fraction'],
  relaxation: ['Relaxation', ''], sizing_it_fraction: ['Sizing IT fraction', ''],
  diesel_mwh: ['Diesel', 'MWh'], hourly_csv: ['Hourly CSV', ''], epw: ['EPW weather file', ''],
};

export function fieldLabel(key) {
  if (SPECIAL[key]) return { label: SPECIAL[key][0], unit: SPECIAL[key][1] };
  const suf = unitSuffix(key);
  let base = key;
  if (suf && key.toLowerCase().endsWith('_' + suf)) base = key.slice(0, -(suf.length + 1));
  const words = base.split('_').filter(Boolean).map((w) => ACR[w.toLowerCase()] || w);
  let label = words.join(' ');
  label = label.charAt(0).toUpperCase() + label.slice(1);
  return { label, unit: suf ? UNIT_LABEL[suf] : '' };
}

export function titleCase(t) {
  return String(t || '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
}

export function fmt(v, digits) {
  if (v === null || v === undefined || v === '') return '';
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return String(v);
    const d = digits !== undefined ? digits : (Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : Math.abs(v) >= 1 ? 2 : 3);
    return v.toLocaleString('en-AU', { maximumFractionDigits: d, minimumFractionDigits: 0 });
  }
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (Array.isArray(v)) return v.length > 6 ? `[${v.length} items]` : JSON.stringify(v);
  if (isObj(v)) return JSON.stringify(v);
  return String(v);
}

export function short(v, n = 48) {
  const t = fmt(v);
  return t.length > n ? t.slice(0, n - 1) + '…' : t;
}

export function download(name, text, type = 'text/plain') {
  const a = h('a', { href: URL.createObjectURL(new Blob([text], { type })), download: name });
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    URL.revokeObjectURL(a.href);
    a.remove();
  }, 0);
}

let toastTimer = null;
export function toast(msg, kind = 'info') {
  let el = document.getElementById('toast');
  if (!el) {
    el = h('div', { id: 'toast', role: 'status', 'aria-live': 'polite' });
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.className = `show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = ''; }, kind === 'error' ? 6000 : 3000);
}

export const KIND_LABEL = {
  document: 'Document', inference: 'Inference', designer: 'Designer', assumption: 'Assumption',
  pending_manufacturer: 'Pending manufacturer', unspecified: 'Unspecified',
};

export const ORIGIN_LABEL = { user: 'Entered', preset: 'Preset', default: 'Tool default', auto: 'Auto-sized' };
