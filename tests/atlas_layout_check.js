// Checks of the map's layout engine (cortex/atlas/static/force.js). Run by tests/test_atlas.py;
// prints "ok <n checks>" and exits 0, or throws.
'use strict';
const assert = require('assert');
const path = require('path');
const Force = require(path.join(__dirname, '..', 'cortex', 'atlas', 'static', 'force.js'));

let checks = 0;
function check(name, fn) {
  try { fn(); checks += 1; } catch (e) { e.message = name + ': ' + e.message; throw e; }
}

function make(groups, per, seed) {
  const nodes = [], links = [];
  for (let g = 0; g < groups; g++) {
    const base = nodes.length;
    for (let i = 0; i < per; i++) nodes.push({ group: g, r: 5 });
    for (let i = 1; i < per; i++) links.push({ a: base + i, b: base + ((i * 7) % i), w: 1 });   // a tree inside the group
    for (let i = 0; i < per; i += 3) links.push({ a: base + i, b: base + ((i + 4) % per), w: 1 });
  }
  links.push({ a: 0, b: per, w: 0.4 });                   // one weak bridge between the first two groups
  return { nodes, links, sim: new Force.Simulation(nodes, links, { seed: seed || 1 }) };
}

const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const mean = (xs) => xs.reduce((s, x) => s + x, 0) / xs.length;

check('positions are finite and the simulation settles', () => {
  const m = make(3, 24);
  m.sim.run(900);
  m.nodes.forEach((n) => { assert.ok(Number.isFinite(n.x) && Number.isFinite(n.y), 'non-finite position'); });
  assert.ok(m.sim.settled, 'did not settle within 900 ticks (alpha=' + m.sim.alpha + ')');
});

check('nodes of one group end up closer together than nodes of different groups', () => {
  const m = make(3, 24);
  m.sim.run(900);
  const within = [], between = [];
  for (let i = 0; i < m.nodes.length; i++) for (let j = i + 1; j < m.nodes.length; j++) {
    (m.nodes[i].group === m.nodes[j].group ? within : between).push(dist(m.nodes[i], m.nodes[j]));
  }
  assert.ok(mean(within) < mean(between) * 0.8, 'within=' + mean(within).toFixed(1) + ' between=' + mean(between).toFixed(1));
});

check('nodes do not sit on top of each other', () => {
  const m = make(2, 30);
  m.sim.run(900);
  let closest = Infinity;
  for (let i = 0; i < m.nodes.length; i++) for (let j = i + 1; j < m.nodes.length; j++) closest = Math.min(closest, dist(m.nodes[i], m.nodes[j]));
  assert.ok(closest > 4, 'closest pair is only ' + closest.toFixed(2) + ' apart');
});

check('the same seed gives the same layout, a different seed a different one', () => {
  const a = make(2, 15, 5), b = make(2, 15, 5), c = make(2, 15, 6);
  a.sim.run(200); b.sim.run(200); c.sim.run(200);
  assert.deepStrictEqual(a.nodes.map((n) => [n.x, n.y]), b.nodes.map((n) => [n.x, n.y]));
  assert.notDeepStrictEqual(a.nodes.map((n) => [n.x, n.y]), c.nodes.map((n) => [n.x, n.y]));
});

check('nodes that already have a position keep it when the simulation is built', () => {
  const nodes = [{ group: 1, x: 100, y: 200 }, { group: 1 }];
  new Force.Simulation(nodes, [], { seed: 1 });
  assert.strictEqual(nodes[0].x, 100);
  assert.strictEqual(nodes[0].y, 200);
  assert.ok(Number.isFinite(nodes[1].x));
});

check('a fixed node does not move', () => {
  const m = make(2, 10);
  m.nodes[3].fixed = true; m.nodes[3].x = 40; m.nodes[3].y = -40;
  m.sim.run(300);
  assert.strictEqual(m.nodes[3].x, 40);
  assert.strictEqual(m.nodes[3].y, -40);
});

check('empty, single-node, isolated-node and dangling-link graphs do not crash', () => {
  new Force.Simulation([], [], {}).run(10);
  const one = [{ group: 0 }]; new Force.Simulation(one, [], {}).run(50);
  assert.ok(Number.isFinite(one[0].x));
  const lone = [{ group: 0 }, { group: 1 }, { group: 2 }];
  new Force.Simulation(lone, [{ a: 0, b: 99, w: 1 }], {}).run(100);
  lone.forEach((n) => assert.ok(Number.isFinite(n.x) && Number.isFinite(n.y)));
});

check('two nodes at exactly the same spot are pushed apart, not into NaN', () => {
  const nodes = [{ group: 0, x: 5, y: 5 }, { group: 0, x: 5, y: 5 }];
  new Force.Simulation(nodes, [], {}).run(200);
  assert.ok(Number.isFinite(nodes[0].x) && Number.isFinite(nodes[1].y));
  assert.ok(dist(nodes[0], nodes[1]) > 1);
});

check('reheat wakes a settled simulation', () => {
  const m = make(1, 8);
  m.sim.run(2000);
  assert.ok(m.sim.settled);
  m.sim.reheat(0.5);
  assert.ok(!m.sim.settled);
});

check('1500 nodes take well under a second per tick', () => {
  const m = make(15, 100);
  const t0 = Date.now();
  for (let i = 0; i < 20; i++) m.sim.tick();
  const perTick = (Date.now() - t0) / 20;
  assert.ok(perTick < 250, perTick.toFixed(1) + ' ms per tick');
});

console.log('ok ' + checks);
