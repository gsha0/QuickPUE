// Minimal SVG / canvas charts for input previews: line charts with a crosshair tooltip, bar charts and
// an hourly heatmap. Colours come from CSS custom properties (--series-1.. --series-8, --grid, ...).
import { fmt, h, s } from './util.js';

const M = { l: 46, r: 14, t: 22, b: 34 };

export function niceTicks(min, max, count = 5) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const span = max - min;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((x) => x * mag).find((x) => span / x <= count) || 10 * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const out = [];
  for (let v = lo; v <= hi + step / 2; v += step) out.push(Math.round(v / step) * step);
  return out;
}

let tipEl = null;
function tip() {
  if (!tipEl) {
    tipEl = h('div', { class: 'chart-tip', role: 'tooltip' });
    document.body.appendChild(tipEl);
  }
  return tipEl;
}

export function showTip(evt, html) {
  const t = tip();
  t.innerHTML = html;
  t.style.display = 'block';
  const pad = 14;
  const w = t.offsetWidth;
  const hgt = t.offsetHeight;
  let x = evt.clientX + pad;
  let y = evt.clientY + pad;
  if (x + w > window.innerWidth - 8) x = evt.clientX - w - pad;
  if (y + hgt > window.innerHeight - 8) y = evt.clientY - hgt - pad;
  t.style.left = `${Math.max(4, x)}px`;
  t.style.top = `${Math.max(4, y)}px`;
}

export function hideTip() {
  if (tipEl) tipEl.style.display = 'none';
}

const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function legend(series) {
  if (series.length < 2) return null;
  return h('div', { class: 'legend' }, series.map((sr) => h('span', { class: 'legend-item' },
    h('span', { class: `key ${sr.dash ? 'dash' : ''}`, style: { '--k': `var(--series-${sr.color || 1})` } }),
    sr.name)));
}

// series: [{name, x: [], y: [], color: 1..8, dash, points, area, step}]
// opts: {xLabel, yLabel, xMin, xMax, yMin, yMax, markers: [{x, label}], hlines: [{y, label}], height,
//        xFmt, yFmt, unit}
export function lineChart(series, opts = {}) {
  const W = opts.width || 520;
  const H = opts.height || 200;
  const all = series.flatMap((sr) => sr.x.map((x, i) => [x, sr.y[i]])).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
  const xs = all.map((p) => p[0]);
  const ys = all.map((p) => p[1]);
  for (const m of opts.markers || []) if (Number.isFinite(m.x)) xs.push(m.x);
  for (const m of opts.hlines || []) if (Number.isFinite(m.y)) ys.push(m.y);
  const xMin = opts.xMin ?? Math.min(...xs);
  const xMax = opts.xMax ?? Math.max(...xs);
  const yt = niceTicks(opts.yMin ?? Math.min(...ys), opts.yMax ?? Math.max(...ys), opts.yTicks || 4);
  const yMin = opts.yMin ?? yt[0];
  const yMax = opts.yMax ?? yt[yt.length - 1];
  const xt = opts.xTicks || niceTicks(xMin, xMax, 6).filter((v) => v >= xMin - 1e-9 && v <= xMax + 1e-9);
  const px = (x) => M.l + ((x - xMin) / (xMax - xMin || 1)) * (W - M.l - M.r);
  const py = (y) => H - M.b - ((y - yMin) / (yMax - yMin || 1)) * (H - M.t - M.b);
  const xf = opts.xFmt || ((v) => fmt(v));
  const yf = opts.yFmt || ((v) => fmt(v));

  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'chart', role: 'img', 'aria-label': opts.label || 'chart' });
  const g = s('g', { class: 'axes' });
  for (const v of yt) {
    if (v < yMin - 1e-9 || v > yMax + 1e-9) continue;
    g.append(s('line', { x1: M.l, x2: W - M.r, y1: py(v), y2: py(v), class: v === yMin ? 'baseline' : 'gridline' }));
    g.append(s('text', { x: M.l - 6, y: py(v) + 4, class: 'tick', 'text-anchor': 'end' }, yf(v)));
  }
  const xLabels = opts.xLabels;
  for (const v of xt) {
    g.append(s('text', { x: px(v), y: H - M.b + 15, class: 'tick', 'text-anchor': 'middle' },
      xLabels ? (xLabels[v] ?? '') : xf(v)));
  }
  if (opts.xLabel) g.append(s('text', { x: (M.l + W - M.r) / 2, y: H - 3, class: 'axis-label', 'text-anchor': 'middle' }, opts.xLabel));
  if (opts.yLabel) g.append(s('text', { x: 4, y: 10, class: 'axis-label' }, opts.yLabel));
  svg.append(g);

  for (const m of opts.markers || []) {
    if (!Number.isFinite(m.x) || m.x < xMin || m.x > xMax) continue;
    svg.append(s('line', { x1: px(m.x), x2: px(m.x), y1: M.t, y2: H - M.b, class: 'marker' }));
    if (m.label) svg.append(s('text', { x: px(m.x) + 4, y: M.t + 10 + (m.row || 0) * 12, class: 'marker-label' }, m.label));
  }
  for (const m of opts.hlines || []) {
    if (!Number.isFinite(m.y)) continue;
    svg.append(s('line', { x1: M.l, x2: W - M.r, y1: py(m.y), y2: py(m.y), class: 'marker' }));
    if (m.label) svg.append(s('text', { x: W - M.r - 4, y: py(m.y) - 4, class: 'marker-label', 'text-anchor': 'end' }, m.label));
  }

  series.forEach((sr) => {
    const pts = sr.x.map((x, i) => [x, sr.y[i]]).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
    if (!pts.length) return;
    let d = '';
    pts.forEach(([x, y], i) => {
      if (sr.step && i > 0) d += `H${px(x).toFixed(1)}V${py(y).toFixed(1)}`;
      else d += `${i ? 'L' : 'M'}${px(x).toFixed(1)},${py(y).toFixed(1)}`;
    });
    const col = `var(--series-${sr.color || 1})`;
    if (sr.area) {
      const a = `${d}L${px(pts[pts.length - 1][0]).toFixed(1)},${py(yMin)}L${px(pts[0][0]).toFixed(1)},${py(yMin)}Z`;
      svg.append(s('path', { d: a, class: 'area', style: `fill:${col}` }));
    }
    svg.append(s('path', { d, class: `line ${sr.dash ? 'dash' : ''}`, style: `stroke:${col}` }));
    if (sr.points) {
      pts.forEach(([x, y]) => svg.append(s('circle', { cx: px(x), cy: py(y), r: 4, class: 'dot', style: `fill:${col}` })));
    }
  });

  // crosshair tooltip on the nearest x of the first series
  const base = series.find((sr) => sr.x.length);
  if (base && opts.hover !== false) {
    const cross = s('line', { y1: M.t, y2: H - M.b, class: 'crosshair', style: 'display:none' });
    svg.append(cross);
    const hit = s('rect', { x: M.l, y: M.t, width: W - M.l - M.r, height: H - M.t - M.b, class: 'hit' });
    hit.addEventListener('mousemove', (evt) => {
      const r = svg.getBoundingClientRect();
      const sx = ((evt.clientX - r.left) / r.width) * W;
      const xv = xMin + ((sx - M.l) / (W - M.l - M.r)) * (xMax - xMin);
      let best = 0;
      base.x.forEach((x, i) => { if (Math.abs(x - xv) < Math.abs(base.x[best] - xv)) best = i; });
      const xb = base.x[best];
      cross.setAttribute('x1', px(xb));
      cross.setAttribute('x2', px(xb));
      cross.style.display = '';
      const rows = series.map((sr) => {
        let j = sr.x.indexOf(xb);
        if (j < 0) j = sr.x.reduce((b, x, i) => (Math.abs(x - xb) < Math.abs(sr.x[b] - xb) ? i : b), 0);
        return `<div class="tip-row"><span class="key" style="--k:var(--series-${sr.color || 1})"></span>${esc(sr.name || '')}<b>${esc(yf(sr.y[j]))}${opts.unit ? ' ' + esc(opts.unit) : ''}</b></div>`;
      }).join('');
      const xl = xLabels ? (xLabels[xb] ?? xf(xb)) : xf(xb);
      showTip(evt, `<div class="tip-head">${esc(opts.xName || opts.xLabel || '')} ${esc(xl)}</div>${rows}`);
    });
    hit.addEventListener('mouseleave', () => { cross.style.display = 'none'; hideTip(); });
    svg.append(hit);
  }
  return h('figure', { class: 'chart-wrap' }, opts.title ? h('figcaption', null, opts.title) : null, svg, legend(series));
}

// categories: [labels]; series: [{name, values: [], color}] stacked
export function barChart(categories, series, opts = {}) {
  const W = opts.width || 520;
  const H = opts.height || 200;
  const totals = categories.map((_, i) => series.reduce((a, sr) => a + (Number(sr.values[i]) || 0), 0));
  const yt = niceTicks(0, Math.max(...totals, 1e-9), 4);
  const yMax = yt[yt.length - 1];
  const band = (W - M.l - M.r) / Math.max(categories.length, 1);
  const bw = Math.min(28, band * 0.6);
  const py = (y) => H - M.b - (y / (yMax || 1)) * (H - M.t - M.b);
  const yf = opts.yFmt || ((v) => fmt(v));
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'chart', role: 'img', 'aria-label': opts.label || 'bar chart' });
  for (const v of yt) {
    svg.append(s('line', { x1: M.l, x2: W - M.r, y1: py(v), y2: py(v), class: v === 0 ? 'baseline' : 'gridline' }));
    svg.append(s('text', { x: M.l - 6, y: py(v) + 4, class: 'tick', 'text-anchor': 'end' }, yf(v)));
  }
  if (opts.yLabel) svg.append(s('text', { x: 4, y: 10, class: 'axis-label' }, opts.yLabel));
  categories.forEach((c, i) => {
    const cx = M.l + band * (i + 0.5);
    let acc = 0;
    series.forEach((sr, k) => {
      const v = Number(sr.values[i]) || 0;
      if (v <= 0) return;
      const y0 = py(acc);
      const y1 = py(acc + v);
      const top = k === series.length - 1 || series.slice(k + 1).every((o) => !(Number(o.values[i]) > 0));
      const gap = acc > 0 ? 2 : 0;
      const hgt = Math.max(0.5, y0 - y1 - gap);
      const r = top ? Math.min(4, hgt / 2, bw / 2) : 0;
      const x = cx - bw / 2;
      const y = y1;
      const d = r ? `M${x},${y + hgt}V${y + r}Q${x},${y} ${x + r},${y}H${x + bw - r}Q${x + bw},${y} ${x + bw},${y + r}V${y + hgt}Z`
        : `M${x},${y + hgt}V${y}H${x + bw}V${y + hgt}Z`;
      const p = s('path', { d, class: `bar ${sr.hatch ? 'hatch' : ''}`, style: `fill:var(--series-${sr.color || 1})` });
      p.addEventListener('mousemove', (evt) => showTip(evt, `<div class="tip-head">${esc(c)}</div><div class="tip-row"><span class="key" style="--k:var(--series-${sr.color || 1})"></span>${esc(sr.name)}<b>${esc(yf(v))}${opts.unit ? ' ' + esc(opts.unit) : ''}</b></div>`));
      p.addEventListener('mouseleave', hideTip);
      svg.append(p);
      acc += v;
    });
    if (opts.valueLabels !== false && totals[i] > 0) {
      svg.append(s('text', { x: cx, y: py(totals[i]) - 5, class: 'value-label', 'text-anchor': 'middle' }, yf(totals[i])));
    }
    svg.append(s('text', { x: cx, y: H - M.b + 15, class: 'tick', 'text-anchor': 'middle' }, c));
  });
  return h('figure', { class: 'chart-wrap' }, opts.title ? h('figcaption', null, opts.title) : null, svg, legend(series));
}

// Diverging blue <-> grey <-> red ramp (reference palette), centred on `mid`.
const BLUE = ['#104281', '#256abf', '#5598e7', '#9ec5f4'];
const RED = ['#f7c2bd', '#ec8a83', '#e34948', '#a8261f'];

function hex(c) {
  return [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
}

function mix(a, b, t) {
  const x = hex(a);
  const y = hex(b);
  return x.map((v, i) => Math.round(v + (y[i] - v) * t));
}

export function divergingColor(v, min, mid, max, dark) {
  const neutral = dark ? '#383835' : '#f0efec';
  const stops = [...BLUE, neutral, ...RED];
  let t;
  if (v <= mid) t = 0.5 * Math.max(0, Math.min(1, (v - min) / ((mid - min) || 1)));
  else t = 0.5 + 0.5 * Math.max(0, Math.min(1, (v - mid) / ((max - mid) || 1)));
  const pos = t * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(pos));
  return mix(stops[i], stops[i + 1], pos - i);
}

// values: 8,760 hourly values (day-major). Rows = hour of day, columns = day of year.
export function heatmap(values, opts = {}) {
  const days = Math.floor(values.length / 24);
  const dark = document.documentElement.dataset.theme === 'dark'
    || (!document.documentElement.dataset.theme && window.matchMedia('(prefers-color-scheme: dark)').matches);
  const min = opts.min ?? Math.min(...values);
  const max = opts.max ?? Math.max(...values);
  const mid = opts.mid ?? (min + max) / 2;
  const cell = 2;
  const cv = h('canvas', { width: days * cell, height: 24 * 6, class: 'heatmap', role: 'img', 'aria-label': opts.label || 'hourly heatmap' });
  const ctx = cv.getContext('2d');
  const img = ctx.createImageData(days * cell, 24 * 6);
  for (let d = 0; d < days; d++) {
    for (let hr = 0; hr < 24; hr++) {
      const [r, g, b] = divergingColor(values[d * 24 + hr], min, mid, max, dark);
      for (let dx = 0; dx < cell; dx++) {
        for (let dy = 0; dy < 6; dy++) {
          const o = (((23 - hr) * 6 + dy) * days * cell + d * cell + dx) * 4;
          img.data[o] = r;
          img.data[o + 1] = g;
          img.data[o + 2] = b;
          img.data[o + 3] = 255;
        }
      }
    }
  }
  ctx.putImageData(img, 0, 0);
  cv.addEventListener('mousemove', (evt) => {
    const r = cv.getBoundingClientRect();
    const d = Math.min(days - 1, Math.max(0, Math.floor(((evt.clientX - r.left) / r.width) * days)));
    const hr = 23 - Math.min(23, Math.max(0, Math.floor(((evt.clientY - r.top) / r.height) * 24)));
    const label = opts.dayLabel ? opts.dayLabel(d) : `day ${d + 1}`;
    showTip(evt, `<div class="tip-head">${esc(label)}, ${String(hr).padStart(2, '0')}:00</div><div class="tip-row">${esc(opts.name || '')}<b>${esc(fmt(values[d * 24 + hr], 1))} ${esc(opts.unit || '')}</b></div>`);
  });
  cv.addEventListener('mouseleave', hideTip);
  const scale = h('div', { class: 'heat-scale' },
    h('span', null, `${fmt(min, 1)} ${opts.unit || ''}`),
    h('span', { class: 'heat-bar' }, Array.from({ length: 40 }, (_, i) => {
      const v = min + ((max - min) * i) / 39;
      const [r, g, b] = divergingColor(v, min, mid, max, dark);
      return h('span', { style: { background: `rgb(${r},${g},${b})` } });
    })),
    h('span', null, `${fmt(max, 1)} ${opts.unit || ''}`),
    h('span', { class: 'muted' }, ` (centre ${fmt(mid, 1)} ${opts.unit || ''})`));
  const months = opts.monthStarts || [];
  const axis = h('div', { class: 'heat-axis' }, months.map((m) => h('span', { style: { left: `${(m.day / days) * 100}%` } }, m.label)));
  return h('figure', { class: 'chart-wrap heat' }, opts.title ? h('figcaption', null, opts.title) : null,
    h('div', { class: 'heat-body' },
      h('div', { class: 'heat-hours' }, h('span', null, '24'), h('span', null, '12'), h('span', null, '0')),
      h('div', { class: 'heat-main' }, cv, axis)), scale);
}

// 24 h profile bars: weekday and weekend fractions
export function profileBars(weekday, weekend) {
  const W = 260;
  const H = 70;
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'chart mini', role: 'img', 'aria-label': 'daily profile' });
  const bw = (W - 30) / 24;
  const py = (v) => H - 14 - v * (H - 22);
  svg.append(s('line', { x1: 24, x2: W, y1: py(0), y2: py(0), class: 'baseline' }));
  svg.append(s('text', { x: 20, y: py(1) + 4, class: 'tick', 'text-anchor': 'end' }, '1'));
  svg.append(s('text', { x: 20, y: py(0) + 4, class: 'tick', 'text-anchor': 'end' }, '0'));
  const pair = weekend && JSON.stringify(weekend) !== JSON.stringify(weekday);
  for (let i = 0; i < 24; i++) {
    const draw = (v, k, off, w) => {
      const y = py(Math.max(0, Math.min(1.2, v)));
      const r = s('rect', { x: 26 + i * bw + off, y, width: Math.max(1, w), height: Math.max(0.5, py(0) - y), class: 'bar', style: `fill:var(--series-${k})` });
      r.addEventListener('mousemove', (evt) => showTip(evt, `<div class="tip-head">${String(i).padStart(2, '0')}:00</div><div class="tip-row">${k === 1 ? 'Weekday' : 'Weekend'}<b>${fmt(v, 2)}</b></div>`));
      r.addEventListener('mouseleave', hideTip);
      svg.append(r);
    };
    if (pair) {
      draw(weekday[i], 1, 0.5, bw / 2 - 1);
      draw(weekend[i], 2, bw / 2, bw / 2 - 1);
    } else {
      draw(weekday[i], 1, 0.5, bw - 1.5);
    }
  }
  [0, 6, 12, 18].forEach((hr) => svg.append(s('text', { x: 26 + hr * bw, y: H - 2, class: 'tick' }, `${hr}h`)));
  const lg = pair ? h('div', { class: 'legend small' },
    h('span', { class: 'legend-item' }, h('span', { class: 'key', style: { '--k': 'var(--series-1)' } }), 'Weekday'),
    h('span', { class: 'legend-item' }, h('span', { class: 'key', style: { '--k': 'var(--series-2)' } }), 'Weekend')) : null;
  return h('div', { class: 'mini-chart' }, svg, lg);
}
