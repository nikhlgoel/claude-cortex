/*
 * The map. Draws the files of a project as a force-directed graph (grouped by the areas Graphify found),
 * pins the palace's memories to the files they are about, and lets you click, search and expand.
 *
 * Everything shown from your project goes in through textContent, never as HTML: a note that contains
 * "<script>" is just text here.
 */
(function () {
  'use strict';

  const KEY = new URLSearchParams(location.search).get('k') || '';
  const $ = (id) => document.getElementById(id);
  const canvas = $('map');
  const ctx = canvas.getContext('2d');

  // ---- small helpers -------------------------------------------------------------------

  function h(tag, props) {
    const el = document.createElement(tag);
    const kids = Array.prototype.slice.call(arguments, 2);
    Object.keys(props || {}).forEach((k) => {
      if (k === 'class') el.className = props[k];
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), props[k]);
      else if (k === 'text') el.textContent = props[k];
      else el.setAttribute(k, props[k]);
    });
    kids.flat(2).forEach((c) => {
      if (c === null || c === undefined || c === false) return;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return el;
  }

  // Like appendChild for many children at once, but skips null/false (DOM append() would print "null").
  function put(parent) {
    Array.prototype.slice.call(arguments, 1).flat(2).forEach((c) => {
      if (c === null || c === undefined || c === false) return;
      parent.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return parent;
  }

  async function api(path, method) {
    const res = await fetch(path, { method: method || 'GET', headers: { 'X-Atlas-Key': KEY } });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || res.statusText);
    return res.json();
  }

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const plural = (n, one, many) => n + ' ' + (n === 1 ? one : (many || one + 's'));
  function ago(seconds) {
    if (seconds === null || seconds === undefined) return 'unknown';
    if (seconds < 90) return 'just now';
    if (seconds < 5400) return Math.round(seconds / 60) + ' min ago';
    if (seconds < 129600) return Math.round(seconds / 3600) + ' h ago';
    return Math.round(seconds / 86400) + ' days ago';
  }

  // ---- state ---------------------------------------------------------------------------

  const S = {
    data: null, nodes: [], links: [], adj: new Map(), sim: null,
    view: { x: 0, y: 0, k: 1 }, selected: null, hover: null, matches: null,
    show: { memories: true, weak: true }, colorBy: 'area', expanded: new Set(), symbols: new Map(),
    dirty: true, drag: null, pan: null, down: null, dpr: 1, w: 0, h: 0, labelCut: 0, areaRank: new Map(),
  };
  const theme = {};

  function readTheme() {
    const cs = getComputedStyle(document.documentElement);
    ['--bg', '--ink', '--muted', '--line', '--ok', '--warn', '--bad', '--node', '--accent', '--panel'].forEach((n) => {
      theme[n] = cs.getPropertyValue(n).trim();
    });
    S.dirty = true;
  }

  const HEALTH = { fresh: '--ok', verify: '--warn', orphaned: '--bad', unknown: '--muted' };
  const HEALTH_TEXT = {
    fresh: 'matches the code', verify: 'the code changed since this was written - check it',
    orphaned: 'the code it refers to is gone', unknown: 'not tied to code',
  };
  const hue = (n) => (n * 47 + 13) % 360;
  function hashHue(text) {
    let x = 7;
    for (let i = 0; i < text.length; i++) x = (x * 31 + text.charCodeAt(i)) >>> 0;
    return x % 360;
  }
  const dark = () => matchMedia('(prefers-color-scheme: dark)').matches;
  const hsl = (hh) => 'hsl(' + hh + ',' + (dark() ? '58%,62%' : '52%,44%') + ')';
  function areaColor(n) {
    const f = n.ref;
    if (S.colorBy === 'health') return f.health ? theme[HEALTH[f.health]] : theme['--node'];
    if (S.colorBy === 'folder') return hsl(hashHue(f.dir));
    const rank = S.areaRank.get(f.community);
    return rank === undefined ? theme['--node'] : hsl((rank * 36 + 12) % 360);
  }

  // ---- building the graph --------------------------------------------------------------

  function buildGraph(keepPositions) {
    const old = new Map();
    if (keepPositions) S.nodes.forEach((n) => old.set(n.key, n));
    const d = S.data;
    S.areaRank = new Map();
    (d.areas || []).filter((a) => a.files > 1).slice(0, 10).forEach((a, i) => S.areaRank.set(a.id, i));
    const nodes = [], links = [];
    const mk = (key, props) => {
      const o = old.get(key);
      return Object.assign({ key: key, x: o ? o.x : undefined, y: o ? o.y : undefined, vx: 0, vy: 0, fixed: false }, props);
    };
    d.files.forEach((f) => {
      // Files nothing links to would each become a lonely island far out; gather them in one place.
      const loose = f.degree === 0 && !f.memories;
      const group = loose ? '_loose' : (f.community === null ? 'd:' + f.dir : f.community);
      nodes.push(mk('f:' + f.id, { type: 'file', ref: f, label: f.name, group: group, r: (f.degree === 0 && !f.memories) ? 3.4 : clamp(5 + Math.sqrt(f.degree) * 1.5, 5, 18) }));
    });
    d.links.forEach((l) => links.push({ a: l[0], b: l[1], w: l[2], kind: 'file' }));
    if (S.show.memories) {
      d.memories.forEach((m) => {
        const home = m.files.length ? nodes[m.files[0]].group : '_notes';
        const idx = nodes.length;
        nodes.push(mk('m:' + m.id, { type: 'memory', ref: m, label: m.title, group: home, r: 6.5 }));
        m.files.forEach((fi) => links.push({ a: idx, b: fi, w: 0.9, kind: 'memory' }));
      });
    }
    const byKey = new Map(nodes.map((n, i) => [n.key, i]));
    S.expanded.forEach((file) => {
      const payload = S.symbols.get(file);
      const fi = byKey.get('f:' + file);
      if (!payload || fi === undefined) return;
      const group = nodes[fi].group;
      payload.symbols.forEach((s) => {
        const idx = nodes.length;
        byKey.set('s:' + s.id, idx);
        nodes.push(mk('s:' + s.id, { type: 'symbol', ref: s, label: s.label, group: group, r: s.kind === 'class' ? 4.5 : 3.2 }));
        links.push({ a: idx, b: fi, w: 1.4, kind: 'contains' });
      });
      payload.external.forEach((s) => {
        if (byKey.has('s:' + s.id)) return;
        const idx = nodes.length;
        byKey.set('s:' + s.id, idx);
        const home = byKey.get('f:' + s.file);
        nodes.push(mk('s:' + s.id, { type: 'symbol', ref: s, label: s.label, group: home === undefined ? group : nodes[home].group, r: 2.8, external: true }));
        if (home !== undefined) links.push({ a: idx, b: home, w: 0.6, kind: 'contains' });
      });
      payload.links.forEach((l) => {
        const a = byKey.get('s:' + l.s), b = byKey.get('s:' + l.t);
        if (a !== undefined && b !== undefined) links.push({ a: a, b: b, w: l.confidence === 'EXTRACTED' ? 0.9 : 0.4, kind: 'call', relation: l.relation, confidence: l.confidence });
      });
    });
    S.nodes = nodes;
    S.links = links;
    S.adj = new Map();
    const put = (a, b, w) => {
      if (!S.adj.has(a)) S.adj.set(a, new Map());
      S.adj.get(a).set(b, Math.max(w, S.adj.get(a).get(b) || 0));
    };
    links.forEach((l) => { put(l.a, l.b, l.w); put(l.b, l.a, l.w); });
    const degrees = d.files.map((f) => f.degree).sort((a, b) => b - a);
    S.labelCut = degrees.length ? degrees[Math.min(24, degrees.length - 1)] : 0;
    S.sim = new Force.Simulation(nodes, links, { seed: 3 });
    S.sim.alpha = keepPositions ? 0.45 : 1;
    if (!keepPositions) S.sim.run(300);          // most of the settling happens before the first frame
    S.dirty = true;
  }

  // ---- drawing -------------------------------------------------------------------------

  function resize() {
    const r = canvas.getBoundingClientRect();
    S.dpr = window.devicePixelRatio || 1;
    S.w = r.width; S.h = r.height;
    canvas.width = Math.round(r.width * S.dpr);
    canvas.height = Math.round(r.height * S.dpr);
    S.dirty = true;
  }

  function focusSet() {
    const f = S.hover !== null ? S.hover : S.selected;
    if (f === null || f === undefined) return null;
    const set = new Set([f]);
    (S.adj.get(f) || new Map()).forEach((_w, k) => set.add(k));
    return set;
  }

  function drawNode(n, alpha, isFocus) {
    ctx.globalAlpha = alpha;
    if (n.type === 'file') {
      if (n.ref.degree === 0 && !n.ref.memories) ctx.globalAlpha = alpha * 0.55;
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, 6.2832);
      ctx.fillStyle = areaColor(n); ctx.fill();
      if (n.ref.health && S.colorBy !== 'health') {
        ctx.lineWidth = 2.2 / S.view.k; ctx.strokeStyle = theme[HEALTH[n.ref.health]]; ctx.stroke();
      }
    } else if (n.type === 'memory') {
      const r = n.r + (isFocus ? 1.5 : 0);
      ctx.beginPath();
      ctx.moveTo(n.x, n.y - r * 1.3); ctx.lineTo(n.x + r, n.y); ctx.lineTo(n.x, n.y + r * 1.3); ctx.lineTo(n.x - r, n.y); ctx.closePath();
      ctx.fillStyle = theme[HEALTH[n.ref.fresh] || '--muted']; ctx.fill();
      ctx.lineWidth = 1.2 / S.view.k; ctx.strokeStyle = theme['--bg']; ctx.stroke();
    } else {
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, 6.2832);
      ctx.fillStyle = n.ref.kind === 'class' ? theme['--accent'] : theme['--ink'];
      ctx.globalAlpha = alpha * (n.external ? 0.5 : 0.85); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function draw() {
    ctx.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
    ctx.clearRect(0, 0, S.w, S.h);
    ctx.translate(S.view.x, S.view.y); ctx.scale(S.view.k, S.view.k);
    const focus = focusSet();
    const dim = (idx) => (S.matches ? (S.matches.has(idx) ? 1 : 0.12) : (focus ? (focus.has(idx) ? 1 : 0.14) : 1));

    ctx.lineCap = 'round';
    S.links.forEach((l) => {
      if (!S.show.weak && l.kind === 'file' && l.w < 0.9) return;
      const a = S.nodes[l.a], b = S.nodes[l.b];
      const alpha = Math.min(dim(l.a), dim(l.b));
      ctx.globalAlpha = alpha * (l.kind === 'file' ? clamp(0.18 + l.w * 0.16, 0.18, 0.6) : 0.5);
      ctx.strokeStyle = l.kind === 'memory' ? theme['--warn'] : (l.kind === 'call' ? theme['--muted'] : theme['--line']);
      ctx.lineWidth = (l.kind === 'file' ? clamp(0.6 + l.w * 0.5, 0.6, 2.4) : 0.9) / Math.sqrt(S.view.k);
      ctx.setLineDash(l.kind === 'memory' || l.confidence === 'INFERRED' ? [3 / S.view.k, 3 / S.view.k] : []);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    });
    ctx.setLineDash([]); ctx.globalAlpha = 1;

    S.nodes.forEach((n, i) => drawNode(n, dim(i), i === S.selected || i === S.hover));

    // Labels: the big hubs, anything focused or matched, and everything once you zoom in.
    ctx.font = (11 / Math.sqrt(S.view.k)) + 'px system-ui, sans-serif';
    ctx.textBaseline = 'middle';
    // Most important first; a label that would land on one already drawn is skipped.
    const wantedLabels = [];
    S.nodes.forEach((n, i) => {
      const hub = n.type === 'file' && S.labelCut > 0 && n.ref.degree >= S.labelCut;
      let priority = 0;
      if (i === S.selected || i === S.hover) priority = 1000;
      else if (S.matches && S.matches.has(i)) priority = 800;
      else if (focus && focus.has(i)) priority = 500 + (n.ref.degree || 0);
      else if (hub) priority = 100 + n.ref.degree;
      else if ((S.view.k > 1.6 && n.type !== 'symbol') || S.view.k > 2.6) priority = 10 + (n.ref.degree || 0);
      if (priority && dim(i) >= 0.3) wantedLabels.push([priority, i]);
    });
    wantedLabels.sort((a, b) => b[0] - a[0]);
    const size = 11 / Math.sqrt(S.view.k), taken = [];
    wantedLabels.slice(0, 160).forEach((entry) => {
      const n = S.nodes[entry[1]];
      const text = n.label.length > 34 ? n.label.slice(0, 33) + '…' : n.label;
      const box = { x: n.x + n.r + 3, y: n.y - size / 2, w: ctx.measureText(text).width, h: size };
      if (entry[0] < 1000 && taken.some((t) => box.x < t.x + t.w && box.x + box.w > t.x && box.y < t.y + t.h && box.y + box.h > t.y)) return;
      taken.push(box);
      ctx.fillStyle = theme['--ink']; ctx.globalAlpha = dim(entry[1]);
      ctx.fillText(text, box.x, n.y);
    });
    ctx.globalAlpha = 1;
    S.dirty = false;
  }

  function loop() {
    if (S.sim && !S.sim.settled) { S.sim.tick(); S.sim.tick(); S.dirty = true; }
    if (S.dirty) draw();
    requestAnimationFrame(loop);
  }

  // ---- view control --------------------------------------------------------------------

  function fit(nodeIdxs) {
    const list = (nodeIdxs && nodeIdxs.length ? nodeIdxs.map((i) => S.nodes[i]) : S.nodes);
    if (!list.length) return;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    list.forEach((n) => { x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y); x1 = Math.max(x1, n.x); y1 = Math.max(y1, n.y); });
    const pad = 70;
    const k = clamp(Math.min((S.w - pad * 2) / Math.max(x1 - x0, 60), (S.h - pad * 2) / Math.max(y1 - y0, 60)), 0.12, 3.2);
    S.view.k = k;
    S.view.x = S.w / 2 - ((x0 + x1) / 2) * k;
    S.view.y = S.h / 2 - ((y0 + y1) / 2) * k;
    S.dirty = true;
  }

  function toWorld(px, py) { return { x: (px - S.view.x) / S.view.k, y: (py - S.view.y) / S.view.k }; }

  function hit(px, py) {
    const p = toWorld(px, py);
    let best = null, bestScore = Infinity;
    for (let i = 0; i < S.nodes.length; i++) {
      const n = S.nodes[i];
      const dx = n.x - p.x, dy = n.y - p.y;
      const reach = n.r * (n.type === 'memory' ? 1.3 : 1) + 5 / S.view.k;   // drawn size + 5 screen px
      const d = Math.sqrt(dx * dx + dy * dy);
      if (d <= reach && d / reach < bestScore) { best = i; bestScore = d / reach; }
    }
    return best;
  }

  // ---- panel ---------------------------------------------------------------------------

  function chip(text, color) {
    const c = h('span', { class: 'chip', text: text });
    if (color) { c.style.borderColor = color; c.style.color = color; }
    return c;
  }
  function copyButton(text) {
    return h('button', { class: 'ghost', title: 'Copy', onclick: (e) => {
      const b = e.target;
      navigator.clipboard.writeText(text).then(() => { b.textContent = 'Copied'; setTimeout(() => { b.textContent = 'Copy'; }, 1200); });
    }, text: 'Copy' });
  }
  const healthChip = (state) => chip(HEALTH_TEXT[state] ? state : 'unknown', theme[HEALTH[state] || '--muted']);
  const closeButton = () => h('button', { class: 'ghost close', 'aria-label': 'Close', onclick: () => selectIndex(null), text: '×' });

  // The panel covers the right edge on a wide window; keep the selected node in the part you can see.
  function selectIndex(i, opts) {
    S.selected = i; S.dirty = true;
    renderPanel();
    if (i === null || i === undefined) return;
    const n = S.nodes[i];
    const free = S.w > 720 ? S.w - 404 : S.w;
    const sx = n.x * S.view.k + S.view.x, sy = n.y * S.view.k + S.view.y;
    if ((opts && opts.center) || sx < 40 || sx > free - 40 || sy < 40 || sy > S.h - 40) {
      S.view.x = free / 2 - n.x * S.view.k; S.view.y = S.h / 2 - n.y * S.view.k;
    }
  }
  const indexOfKey = (key) => S.nodes.findIndex((n) => n.key === key);

  function memoryCard(m) {
    return h('button', { class: 'card', onclick: () => {
      const i = indexOfKey('m:' + m.id);
      if (i >= 0) selectIndex(i, { center: true }); else showMemoryDetail(m.id);
    } },
      h('div', { class: 'row' }, chip(m.kind), healthChip(m.fresh)),
      h('strong', { text: m.title }),
      h('span', { class: 'muted', text: m.gist }));
  }

  function renderPanel() {
    const panel = $('panel');
    panel.textContent = '';
    if (S.selected === null || S.selected === undefined) { panel.classList.remove('open'); return; }
    panel.classList.add('open');
    const n = S.nodes[S.selected];
    if (n.type === 'file') return renderFile(panel, n);
    if (n.type === 'memory') return showMemoryDetail(n.ref.id);
    return renderSymbol(panel, n);
  }

  function renderFile(panel, n) {
    const f = n.ref, d = S.data;
    const idx = S.selected;
    const fileIndex = d.files.indexOf(f);
    const mems = d.memories.filter((m) => m.files.indexOf(fileIndex) >= 0);
    const open = S.expanded.has(f.id);
    put(panel, closeButton(), h('h2', { text: f.name }),
      h('div', { class: 'path' }, h('code', { text: f.id }), copyButton(f.id)),
      h('div', { class: 'row' }, f.area ? chip('area: ' + f.area) : null, f.health ? healthChip(f.health) : null,
        chip(plural(f.symbols, 'function/class', 'functions & classes')), chip(plural(f.degree, 'link'))),
      f.symbols ? h('button', { class: 'primary', onclick: () => toggleSymbols(f.id), text: open ? 'Hide functions' : 'Show functions on the map' }) : null,
      h('h3', { text: mems.length ? 'What we know about this file' : 'Nothing remembered about this file yet' }),
      mems.length ? mems.map(memoryCard) : h('p', { class: 'muted', text: 'Notes saved with a mention of this file appear here. Try: cc palace remember "title" "what you learned" --file ' + f.id }));
    const near = [];
    (S.adj.get(idx) || new Map()).forEach((w, j) => { if (S.nodes[j].type === 'file') near.push([j, w]); });
    near.sort((a, b) => b[1] - a[1]);
    if (near.length) {
      put(panel, h('h3', { text: 'Connected files' }), h('ul', { class: 'list' }, near.slice(0, 14).map((p) =>
        h('li', null, h('button', { class: 'link', onclick: () => selectIndex(p[0], { center: true }), text: S.nodes[p[0]].ref.id })))));
    }
  }

  function renderSymbol(panel, n) {
    const s = n.ref;
    const idx = S.selected;
    const calls = [], calledBy = [];
    S.links.forEach((l) => {
      if (l.kind !== 'call') return;
      if (l.a === idx) calls.push(l.b); else if (l.b === idx) calledBy.push(l.a);
    });
    const list = (title, ids) => (ids.length ? [h('h3', { text: title }), h('ul', { class: 'list' }, ids.slice(0, 20).map((j) =>
      h('li', null, h('button', { class: 'link', onclick: () => selectIndex(j, { center: true }), text: S.nodes[j].label }))))] : null);
    const where = s.file + (s.line ? ':' + s.line : '');
    put(panel, closeButton(), h('h2', { text: s.label }),
      h('div', { class: 'row' }, chip(s.kind), s.line ? chip('line ' + s.line) : null),
      h('div', { class: 'path' }, h('code', { text: where }), copyButton(where)),
      list('Uses', calls), list('Used by', calledBy));
    if (!calls.length && !calledBy.length) put(panel, h('p', { class: 'muted', text: 'No calls to or from this were recorded in the graph.' }));
  }

  async function showMemoryDetail(id) {
    const panel = $('panel');
    panel.classList.add('open');
    panel.textContent = '';
    put(panel, closeButton(), h('p', { class: 'muted', text: 'Loading…' }));
    try {
      const m = await api('/api/memory?id=' + encodeURIComponent(id));
      panel.textContent = '';
      put(panel, closeButton(),
        h('h2', { text: m.title }),
        h('div', { class: 'row' }, chip(m.kind), chip('layer ' + m.tier), healthChip(m.fresh), m.pinned ? chip('pinned') : null, chip('trust: ' + m.trust)),
        h('p', { class: 'muted small', text: HEALTH_TEXT[m.fresh] }),
        h('div', { class: 'body', text: m.body }),
        m.anchors.length ? [h('h3', { text: 'About these files' }), h('ul', { class: 'list' }, m.anchors.map((a) =>
          h('li', null, h('button', { class: 'link', onclick: () => { const i = indexOfKey('f:' + a.file); if (i >= 0) selectIndex(i, { center: true }); }, text: a.file + (a.label ? ' → ' + a.label : '') }), ' ', healthChip(a.state))))] : null,
        m.supersedes.length ? [h('h3', { text: 'Replaced earlier notes' }), h('ul', { class: 'list' }, m.supersedes.map((o) => h('li', { class: 'muted', text: o.title + ' (' + o.recorded_at.slice(0, 10) + ')' })))] : null,
        h('p', { class: 'muted small', text: 'Written ' + m.recorded_at.slice(0, 10) + ' · used ' + plural(m.uses, 'time') + ' · id ' + m.id }),
        h('div', { class: 'path' }, h('code', { text: 'cc palace expand ' + m.id }), copyButton('cc palace expand ' + m.id)));
    } catch (e) {
      put(panel, h('p', { class: 'muted', text: 'Could not load this note: ' + e.message }));
    }
  }

  async function toggleSymbols(file) {
    if (S.expanded.has(file)) S.expanded.delete(file);
    else {
      if (!S.symbols.has(file)) S.symbols.set(file, await api('/api/symbols?file=' + encodeURIComponent(file)));
      S.expanded.add(file);
    }
    const keep = S.nodes[S.selected] ? S.nodes[S.selected].key : null;
    buildGraph(true);
    S.selected = keep ? indexOfKey(keep) : null;
    if (S.selected < 0) S.selected = null;
    renderPanel();
  }

  // ---- search --------------------------------------------------------------------------

  let searchTimer = null, results = [], active = -1;
  function renderResults() {
    const box = $('results');
    box.textContent = '';
    box.classList.toggle('open', results.length > 0);
    results.forEach((r, i) => put(box, h('button', { class: 'result' + (i === active ? ' active' : ''), onclick: () => chooseResult(r) },
      h('span', { class: 'tag', text: r.type }), h('strong', { text: r.label }), h('span', { class: 'muted', text: r.sub || '' }))));
  }
  async function chooseResult(r) {
    results = []; renderResults();
    if (r.type === 'memory') {
      const i = indexOfKey('m:' + r.id);
      if (i >= 0) selectIndex(i, { center: true }); else showMemoryDetail(r.id);
    } else if (r.type === 'file') {
      const i = indexOfKey('f:' + r.id); if (i >= 0) selectIndex(i, { center: true });
    } else {
      if (!S.expanded.has(r.file)) await toggleSymbols(r.file);
      const i = indexOfKey('s:' + r.id); if (i >= 0) selectIndex(i, { center: true });
    }
  }
  $('search').addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    const q = e.target.value.trim();
    if (q.length < 2) { results = []; renderResults(); S.matches = null; S.dirty = true; return; }
    searchTimer = setTimeout(async () => {
      try {
        results = (await api('/api/search?q=' + encodeURIComponent(q))).results; active = results.length ? 0 : -1;
        const keys = new Set(results.map((r) => (r.type === 'memory' ? 'm:' : r.type === 'file' ? 'f:' : 's:') + r.id));
        S.matches = new Set(); S.nodes.forEach((n, i) => { if (keys.has(n.key)) S.matches.add(i); });
        if (!S.matches.size) S.matches = null;
        renderResults(); S.dirty = true;
      } catch (_e) { results = []; renderResults(); }
    }, 140);
  });
  $('search').addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { active = Math.min(active + 1, results.length - 1); renderResults(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { active = Math.max(active - 1, 0); renderResults(); e.preventDefault(); }
    else if (e.key === 'Enter' && results[active]) chooseResult(results[active]);
    else if (e.key === 'Escape') { e.target.value = ''; results = []; S.matches = null; renderResults(); S.dirty = true; }
  });

  // ---- pointer -------------------------------------------------------------------------

  canvas.addEventListener('pointerdown', (e) => {
    canvas.setPointerCapture(e.pointerId);
    const r = canvas.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    const i = hit(px, py);
    S.down = { x: px, y: py, moved: false, node: i };
    if (i !== null) { S.drag = i; S.nodes[i].fixed = true; } else S.pan = { x: S.view.x, y: S.view.y, px: px, py: py };
  });
  canvas.addEventListener('pointermove', (e) => {
    const r = canvas.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    if (S.down) {
      if (Math.abs(px - S.down.x) + Math.abs(py - S.down.y) > 4) S.down.moved = true;
      if (S.drag !== null && S.down.moved) {
        const p = toWorld(px, py); const n = S.nodes[S.drag];
        n.x = p.x; n.y = p.y; S.sim.reheat(0.25); S.dirty = true;
      } else if (S.pan) { S.view.x = S.pan.x + (px - S.pan.px); S.view.y = S.pan.y + (py - S.pan.py); S.dirty = true; }
      return;
    }
    const i = hit(px, py);
    if (i !== S.hover) { S.hover = i; S.dirty = true; canvas.style.cursor = i === null ? 'grab' : 'pointer'; }
    showTip(i, px, py);
  });
  canvas.addEventListener('pointerup', () => {
    const d = S.down;
    if (S.drag !== null && S.nodes[S.drag]) S.nodes[S.drag].fixed = false;
    if (d && !d.moved) selectIndex(d.node, null);
    S.down = null; S.drag = null; S.pan = null;
  });
  canvas.addEventListener('pointerleave', () => { if (!S.down) { S.hover = null; S.dirty = true; showTip(null); } });
  canvas.addEventListener('dblclick', (e) => {
    const r = canvas.getBoundingClientRect();
    const i = hit(e.clientX - r.left, e.clientY - r.top);
    if (i !== null && S.nodes[i].type === 'file' && S.nodes[i].ref.symbols) toggleSymbols(S.nodes[i].ref.id);
  });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const r = canvas.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    const before = toWorld(px, py);
    S.view.k = clamp(S.view.k * Math.exp(-e.deltaY * 0.0015), 0.1, 6);
    S.view.x = px - before.x * S.view.k; S.view.y = py - before.y * S.view.k;
    S.dirty = true;
  }, { passive: false });

  function showTip(i, px, py) {
    const tip = $('tip');
    if (i === null || i === undefined) { tip.hidden = true; return; }
    const n = S.nodes[i];
    tip.textContent = n.type === 'file' ? n.ref.id + (n.ref.area ? '  ·  ' + n.ref.area : '')
      : n.type === 'memory' ? n.ref.kind + ': ' + n.ref.title : n.ref.kind + ' ' + n.ref.label + '  ·  ' + n.ref.file;
    tip.hidden = false;
    tip.style.left = Math.max(4, Math.min(px + 14, S.w - tip.offsetWidth - 8)) + 'px';
    tip.style.top = (py + 16) + 'px';
  }

  // ---- toolbar, legend, status ---------------------------------------------------------

  function renderLegend() {
    const box = $('legend'); box.textContent = '';
    const dot = (color, shape) => { const s = h('i', { class: 'dot ' + (shape || '') }); s.style.background = color; return s; };
    put(box, h('span', null, dot(theme['--node']), 'file'), h('span', null, dot(theme['--ok'], 'diamond'), 'note: matches code'),
      h('span', null, dot(theme['--warn'], 'diamond'), 'code changed'), h('span', null, dot(theme['--bad'], 'diamond'), 'code gone'));
    if (S.colorBy === 'area') {
      (S.data.areas || []).filter((a) => S.areaRank.has(a.id)).slice(0, 8).forEach((a) => {
        put(box, h('span', null, dot(hsl((S.areaRank.get(a.id) * 36 + 12) % 360)), a.name || ('area ' + a.id)));
      });
      put(box, h('span', null, dot(theme['--node']), 'other'));
    }
  }

  function renderStatus() {
    const d = S.data, g = d.graph, p = d.palace;
    const parts = [];
    parts.push(g.present ? plural(g.files, 'file') + ' · ' + plural(g.symbols, 'function') : 'no code graph');
    if (p.present) parts.push(plural(p.memories, 'note'));
    if (g.present) parts.push('map built ' + ago(g.age_seconds));
    $('status').textContent = parts.join('  ·  ');
    const attn = $('attention');
    attn.hidden = !p.attention;
    attn.textContent = plural(p.attention, 'note') + ' to check';
    $('project').textContent = d.project.name;
    document.title = d.project.name + ' – project map';
    const banner = $('banner');
    const notes = [];
    if (!g.present) notes.push('No Graphify graph for this project yet, so only the files your notes mention are shown. Build one (offline, no model): graphify update .');
    if (g.error) notes.push(g.error);
    if (p.error) notes.push('Notes unavailable: ' + p.error);
    if (!p.present && !p.error) notes.push('No notes yet. Start with: cc palace init');
    if (d.truncated.files) notes.push('Showing the ' + d.files.length + ' most connected files (' + d.truncated.files + ' more not drawn).');
    banner.textContent = notes.join('  ');
    banner.hidden = !notes.length;
    $('empty').hidden = d.files.length > 0 || d.memories.length > 0;
  }

  async function load(refresh) {
    const data = await api(refresh ? '/api/refresh' : '/api/overview', refresh ? 'POST' : 'GET');
    const first = !S.data;
    S.data = data;
    S.expanded = new Set([...S.expanded].filter((f) => data.files.some((x) => x.id === f)));
    for (const f of S.expanded) S.symbols.set(f, await api('/api/symbols?file=' + encodeURIComponent(f)));
    buildGraph(!first);
    renderStatus(); renderLegend();
    if (first) fit();
    S.selected = null; renderPanel();
    $('changed').hidden = true;
  }

  function showError(e) {
    const banner = $('banner');
    banner.textContent = 'Could not load the map: ' + e.message; banner.hidden = false;
  }

  $('refresh').addEventListener('click', () => load(true).catch(showError));
  $('changed').addEventListener('click', () => load(true).catch(showError));
  $('fit').addEventListener('click', () => fit());
  $('toggle-notes').addEventListener('change', (e) => { S.show.memories = e.target.checked; buildGraph(true); S.selected = null; renderPanel(); });
  $('toggle-weak').addEventListener('change', (e) => { S.show.weak = e.target.checked; S.dirty = true; });
  $('color').addEventListener('change', (e) => { S.colorBy = e.target.value; renderLegend(); S.dirty = true; });
  $('attention').addEventListener('click', () => {
    const idx = [];
    S.nodes.forEach((n, i) => {
      if (n.type === 'memory' && (n.ref.fresh === 'verify' || n.ref.fresh === 'orphaned')) { idx.push(i); n.ref.files.forEach((f) => idx.push(f)); }
    });
    S.matches = new Set(idx); fit(idx); S.dirty = true;
  });
  window.addEventListener('keydown', (e) => {
    if (e.target && e.target.tagName === 'INPUT' && e.target.type !== 'checkbox') return;
    if (e.key === '/') { e.preventDefault(); $('search').focus(); }
    else if (e.key === 'Escape') { S.matches = null; selectIndex(null); }
    else if (e.key === 'f') fit();
    else if (e.key === 'm') { const c = $('toggle-notes'); c.checked = !c.checked; c.dispatchEvent(new Event('change')); }
  });
  window.addEventListener('resize', resize);
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { readTheme(); if (S.data) renderLegend(); });

  // Notice when the graph or the notes changed on disk while the window was open.
  setInterval(async () => {
    if (document.hidden || !S.data) return;
    try {
      const s = await api('/api/status');
      $('changed').hidden = !(s.files !== S.data.graph.files || s.memories !== S.data.palace.memories || s.attention !== S.data.palace.attention);
    } catch (_e) { /* the server went away: the button closes this window */ }
  }, 20000);

  readTheme(); resize(); canvas.style.cursor = 'grab';
  load(false).catch(showError);
  requestAnimationFrame(loop);
})();
