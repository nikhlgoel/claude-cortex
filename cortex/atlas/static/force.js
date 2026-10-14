/*
 * A small force-directed layout, written for this map and kept free of the page so it can be tested
 * on its own (tests/test_atlas_layout.js is run by tests/test_atlas.py when node is installed).
 *
 *   const sim = new Force.Simulation(nodes, links, {seed: 1});
 *   sim.run(300);                 // or call sim.tick() from requestAnimationFrame until sim.settled
 *
 * nodes: [{group, r?, x?, y?, fixed?}]   links: [{a, b, w?}]  (a and b are indices into nodes)
 * The simulation writes x, y, vx, vy onto the node objects.
 *
 * Why not a library: the graph is a few hundred to a few thousand nodes, and what makes it readable
 * is the part a generic layout does not know - nodes of one group (a Graphify "area") cluster
 * together. Repulsion uses a grid so a tick costs O(n), not O(n^2).
 */
(function (root) {
  'use strict';

  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function Simulation(nodes, links, options) {
    const o = options || {};
    this.nodes = nodes;
    this.links = links;
    this.linkLength = o.linkLength || 70;
    this.repulsion = o.repulsion || 1700;
    this.cell = o.cell || 96;
    this.gravity = o.gravity === undefined ? 0.008 : o.gravity;
    this.cohesion = o.cohesion === undefined ? 0.035 : o.cohesion;
    this.damping = o.damping || 0.8;
    this.alpha = 1;
    this.alphaDecay = o.alphaDecay || 0.985;
    this.alphaMin = o.alphaMin || 0.02;
    this._rand = mulberry32(o.seed === undefined ? 1 : o.seed);
    this._seed(o.keep !== false);
  }

  // Put each group on its own spot of a spiral and scatter its members around it, so the first frame
  // already looks like clusters instead of a hairball. Nodes that already have a position keep it.
  Simulation.prototype._seed = function (keep) {
    const groups = new Map();
    this.nodes.forEach((n) => {
      const g = n.group === undefined || n.group === null ? '_' : n.group;
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(n);
    });
    const golden = Math.PI * (3 - Math.sqrt(5));
    const spread = Math.sqrt(this.nodes.length) * 22;
    let i = 0;
    const rand = this._rand;
    groups.forEach((members) => {
      const radius = spread * Math.sqrt((i + 0.5) / groups.size);
      const cx = Math.cos(i * golden) * radius;
      const cy = Math.sin(i * golden) * radius;
      const local = 14 + Math.sqrt(members.length) * 12;
      members.forEach((n) => {
        if (keep && Number.isFinite(n.x) && Number.isFinite(n.y)) {
          n.vx = n.vx || 0; n.vy = n.vy || 0;
          return;
        }
        const angle = rand() * Math.PI * 2;
        const dist = Math.sqrt(rand()) * local;
        n.x = cx + Math.cos(angle) * dist;
        n.y = cy + Math.sin(angle) * dist;
        n.vx = 0; n.vy = 0;
      });
      i += 1;
    });
  };

  Simulation.prototype.reheat = function (alpha) {
    this.alpha = Math.max(this.alpha, alpha === undefined ? 0.6 : alpha);
  };

  Object.defineProperty(Simulation.prototype, 'settled', {
    get: function () { return this.alpha < this.alphaMin; },
  });

  Simulation.prototype.tick = function () {
    const nodes = this.nodes, links = this.links, n = nodes.length;
    if (!n) { this.alpha = 0; return; }
    const alpha = this.alpha, cell = this.cell;

    // 1. Repulsion between nearby nodes (grid of cells; only the 3x3 neighbourhood interacts).
    const grid = new Map();
    for (let i = 0; i < n; i++) {
      const key = Math.floor(nodes[i].x / cell) + ',' + Math.floor(nodes[i].y / cell);
      const bucket = grid.get(key);
      if (bucket) bucket.push(i); else grid.set(key, [i]);
    }
    for (let i = 0; i < n; i++) {
      const a = nodes[i];
      const cx = Math.floor(a.x / cell), cy = Math.floor(a.y / cell);
      for (let gx = cx - 1; gx <= cx + 1; gx++) {
        for (let gy = cy - 1; gy <= cy + 1; gy++) {
          const bucket = grid.get(gx + ',' + gy);
          if (!bucket) continue;
          for (let k = 0; k < bucket.length; k++) {
            const j = bucket[k];
            if (j <= i) continue;
            const b = nodes[j];
            let dx = a.x - b.x, dy = a.y - b.y;
            let d2 = dx * dx + dy * dy;
            if (d2 < 0.01) { dx = (this._rand() - 0.5); dy = (this._rand() - 0.5); d2 = dx * dx + dy * dy + 0.01; }
            const reach = cell * 1.5;
            if (d2 > reach * reach) continue;
            const minDist = ((a.r || 5) + (b.r || 5)) * 1.6;
            const d = Math.sqrt(d2);
            let f = this.repulsion / d2;
            if (d < minDist) f += (minDist - d) * 0.9;          // hard-ish shell so circles do not overlap
            f = Math.min(f, 12) * alpha;
            const fx = (dx / d) * f, fy = (dy / d) * f;
            a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
          }
        }
      }
    }

    // 2. Springs along links; heavier links pull a little tighter.
    for (let i = 0; i < links.length; i++) {
      const l = links[i], a = nodes[l.a], b = nodes[l.b];
      if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const w = l.w === undefined ? 1 : l.w;
      const rest = this.linkLength / (0.7 + Math.min(w, 3) * 0.3);
      const strength = 0.08 * Math.min(1, 0.35 + w * 0.3);
      const f = (d - rest) * strength * Math.max(alpha, 0.15);
      const fx = (dx / d) * f, fy = (dy / d) * f;
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    }

    // 3. Cohesion toward the group's centre, and a faint pull to the origin.
    const sums = new Map();
    for (let i = 0; i < n; i++) {
      const g = nodes[i].group === undefined || nodes[i].group === null ? '_' : nodes[i].group;
      let s = sums.get(g);
      if (!s) { s = { x: 0, y: 0, n: 0 }; sums.set(g, s); }
      s.x += nodes[i].x; s.y += nodes[i].y; s.n += 1;
    }
    for (let i = 0; i < n; i++) {
      const p = nodes[i];
      const g = p.group === undefined || p.group === null ? '_' : p.group;
      const s = sums.get(g);
      if (s.n > 1) {
        p.vx += (s.x / s.n - p.x) * this.cohesion * alpha;
        p.vy += (s.y / s.n - p.y) * this.cohesion * alpha;
      }
      p.vx -= p.x * this.gravity * alpha;
      p.vy -= p.y * this.gravity * alpha;
    }

    // 4. Integrate.
    for (let i = 0; i < n; i++) {
      const p = nodes[i];
      if (p.fixed) { p.vx = 0; p.vy = 0; continue; }
      p.vx *= this.damping; p.vy *= this.damping;
      const speed = Math.sqrt(p.vx * p.vx + p.vy * p.vy);
      if (speed > 40) { p.vx = (p.vx / speed) * 40; p.vy = (p.vy / speed) * 40; }
      p.x += p.vx; p.y += p.vy;
    }
    this.alpha *= this.alphaDecay;
  };

  Simulation.prototype.run = function (ticks) {
    for (let i = 0; i < ticks && !this.settled; i++) this.tick();
    return this;
  };

  const api = { Simulation: Simulation, mulberry32: mulberry32 };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Force = api;
})(typeof self !== 'undefined' ? self : this);
