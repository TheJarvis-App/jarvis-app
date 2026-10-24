// Made things for the projector: buildings (a house you can open, a skyscraper, the Eiffel Tower, a pyramid with its
// chambers), vehicles (a car, an airliner, a rocket), devices (a TV, a laptop, a phone, each opening into its layers),
// a guitar and a sneaker. Modelled from real proportions with smooth shapes, so each one reads at a glance.
const { THREE, mat, texMat, deg, V, part, mesh, taper, roundedBox, lathe, extrude, smoothOutline, ellipse, rect, reverse, limb, blob, canvasTex, rng, woodTex, loft, squircle } = require('./kit.js');
// y along x through control points [[x, y], ...], eased between them
const curveOf = (pts) => (x) => { if (x <= pts[0][0]) return pts[0][1]; for (let i = 1; i < pts.length; i++) if (x <= pts[i][0]) { const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], t = (x - x0) / (x1 - x0); return y0 + (y1 - y0) * (1 - Math.cos(t * Math.PI)) / 2; } return pts[pts.length - 1][1]; };

const explodeWith = (moves) => (k) => moves.forEach(([g, home, off]) => g.position.copy(home).addScaledVector(off, k));
const mover = (g, off) => [g, g.position.clone(), V(...off)];

// ---------- buildings ----------
function sidingTex(color) {
  return canvasTex(256, 256, (g, w, h) => {
    g.fillStyle = color; g.fillRect(0, 0, w, h);
    for (let y = 0; y < h; y += 21) { g.fillStyle = 'rgba(0,0,0,0.10)'; g.fillRect(0, y, w, 2); g.fillStyle = 'rgba(255,255,255,0.08)'; g.fillRect(0, y + 2, w, 2); }
  }, { repeat: [3, 3] });
}
function shingleTex(color) {
  const r = rng(4);
  return canvasTex(256, 256, (g, w, h) => {
    g.fillStyle = color; g.fillRect(0, 0, w, h);
    for (let row = 0; row < 8; row++) for (let i = 0; i < 9; i++) {
      const x = i * 32 - (row % 2) * 16, y = row * 32; g.fillStyle = `rgba(0,0,0,${0.08 + r() * 0.14})`; g.fillRect(x + 1, y + 1, 30, 30);
      g.fillStyle = 'rgba(0,0,0,0.35)'; g.fillRect(x, y + 29, 32, 3);
    }
  }, { repeat: [6, 3] });
}
function brickTex(color = '#9c4a33') {
  return canvasTex(256, 256, (g, w, h) => {
    g.fillStyle = '#d8d2c8'; g.fillRect(0, 0, w, h);
    const r = rng(8);
    for (let row = 0; row < 16; row++) for (let i = -1; i < 5; i++) { g.fillStyle = color; g.globalAlpha = 0.85 + r() * 0.15; g.fillRect(i * 64 + (row % 2) * 32 + 2, row * 16 + 2, 60, 12); }
    g.globalAlpha = 1;
  }, { repeat: [1, 1] });
}

function houseModel(P) {
  const root = new THREE.Group(), F = P.floors || 2, FH = 0.9, W = 2.0, D = 1.5, T = 0.08, H = F * FH, RA = deg(34), RH = (D / 2) * Math.tan(RA), y0 = 0.12;
  const wallM = texMat(sidingTex(P.wall_color || '#ece6da'), { kind: 'matte' }), trim = mat('plastic', '#f7f5f0');
  const glass = mat('tinted', '#2a3b4c'); glass.emissive = new THREE.Color('#ffcf8a'); glass.emissiveIntensity = 0.28;
  const moves = [];
  // the plot: lawn, a path to the door, two bushes
  const garden = part(root, 'Garden');
  mesh(roundedBox(W + 1.0, 0.06, D + 1.1, 0.03), mat('fabric', '#4f7d3a'), garden, [0, 0.03, 0.08]);
  mesh(roundedBox(0.36, 0.065, 0.55, 0.02), mat('matte', '#b9b2a6'), garden, [0.45, 0.035, D / 2 + 0.33]);
  for (const x of [-0.7, 1.05]) blob(garden, [x, 0.17, D / 2 + 0.2], 0.18, 0.15, 0.16, mat('fabric', '#3e6b2e'));
  mesh(roundedBox(W + 0.16, 0.12, D + 0.16, 0.02), mat('matte', '#8f949b'), part(root, 'Foundation'), [0, 0.06 + 0.03, 0]);
  // walls with real openings for the door and windows
  const walls = part(root, 'Walls'), windows = part(root, 'Windows'), door = part(root, 'Door');
  const hole = (x, y, w, h) => reverse(rect(w, h, x, y));
  const winsFront = [], winsBack = [], winsSide = [];
  for (let f = 0; f < F; f++) {
    const wy = f * FH + 0.5;
    for (const x of f === 0 ? [-0.55] : [-0.55, 0.45]) winsFront.push([x, wy]);
    if (f === 0) winsFront.push([-0.05, wy]);
    for (const x of [-0.5, 0.5]) winsBack.push([x, wy]);
    winsSide.push([0, wy]);
  }
  const wallMesh = (len, holes, extraTop) => {
    const out = extraTop ? [[-len / 2, 0], [len / 2, 0], [len / 2, H], [0, H + extraTop], [-len / 2, H]] : rect(len, H, 0, H / 2);
    return extrude(out, T, 0.004, holes);
  };
  const front = new THREE.Group(); front.position.set(0, y0, D / 2 - T / 2); walls.add(front);
  mesh(wallMesh(W, [...winsFront.map(([x, y]) => hole(x, y, 0.34, 0.4)), hole(0.45, 0.34, 0.32, 0.64)]), wallM, front);
  const back = new THREE.Group(); back.position.set(0, y0, -D / 2 + T / 2); walls.add(back);
  mesh(wallMesh(W, winsBack.map(([x, y]) => hole(x, y, 0.34, 0.4))), wallM, back);
  const sides = [];
  for (const s of [-1, 1]) {
    const g = new THREE.Group(); g.position.set(s * (W / 2 - T / 2), y0, 0); g.rotation.y = Math.PI / 2; walls.add(g); sides.push(g);
    mesh(wallMesh(D - 2 * T, winsSide.map(([x, y]) => hole(x, y, 0.34, 0.4)), RH), wallM, g);
  }
  moves.push(mover(front, [0, 0, 0.7]), mover(back, [0, 0, -0.7]), ...sides.map((g, i) => mover(g, [(i ? 1 : -1) * 0.7, 0, 0])));
  // windows: a white frame, a cross, and glass with a warm light inside
  const addWindow = (parent, x, y, z, ry) => {
    const g = new THREE.Group(); g.position.set(x, y, z); g.rotation.y = ry; parent.add(g);
    mesh(new THREE.PlaneGeometry(0.34, 0.4), glass, g);
    for (const [w, h, px, py] of [[0.38, 0.035, 0, 0.2], [0.38, 0.035, 0, -0.2], [0.035, 0.4, 0.17, 0], [0.035, 0.4, -0.17, 0], [0.34, 0.02, 0, 0], [0.02, 0.4, 0, 0]]) mesh(roundedBox(w, h, 0.03, 0.008), trim, g, [px, py, 0.01]);
    mesh(roundedBox(0.42, 0.03, 0.06, 0.01), trim, g, [0, -0.215, 0.025]);   // the sill
    return g;
  };
  winsFront.forEach(([x, y]) => { const w = addWindow(windows, x, y0 + y, D / 2 - T / 2, 0); moves.push(mover(w, [0, 0, 0.7])); });
  winsBack.forEach(([x, y]) => { const w = addWindow(windows, x, y0 + y, -D / 2 + T / 2, Math.PI); moves.push(mover(w, [0, 0, -0.7])); });
  for (const s of [-1, 1]) winsSide.forEach(([x, y]) => { const w = addWindow(windows, s * (W / 2 - T / 2), y0 + y, x, s * Math.PI / 2); moves.push(mover(w, [s * 0.7, 0, 0])); });
  // the front door, its step and a little canopy
  const dg = new THREE.Group(); dg.position.set(0.45, y0 + 0.34, D / 2 - T / 2); door.add(dg);
  mesh(roundedBox(0.3, 0.62, 0.04, 0.01), texMat(woodTex('#7a4322', '#4f2a14', 5), { kind: 'wood' }), dg);
  for (const py of [0.15, -0.12]) mesh(roundedBox(0.2, 0.2, 0.012, 0.005), mat('wood', '#6a3a1d'), dg, [0, py, 0.025]);
  blob(dg, [0.1, 0, 0.035], 0.018, 0.018, 0.018, mat('chrome', '#d4b46a'));
  mesh(roundedBox(0.5, 0.05, 0.25, 0.01), mat('matte', '#9aa0a6'), door, [0.45, y0 + 0.025, D / 2 + 0.11]);
  mesh(roundedBox(0.5, 0.035, 0.24, 0.01), trim, door, [0.45, y0 + 0.72, D / 2 + 0.1], [deg(12), 0, 0]);
  moves.push(mover(dg, [0, 0, 0.7]));
  // the roof: two sloping planes of shingles meeting at the ridge, with overhangs, and a brick chimney
  const roof = part(root, 'Roof'), rm = texMat(shingleTex(P.roof_color || '#5b3a32'), { kind: 'matte' });
  const eave = D / 2 + 0.2, slab = eave / Math.cos(RA), top = y0 + H + RH + 0.04;
  const roofHalves = [];
  for (const s of [1, -1]) {
    const g = new THREE.Group(); g.position.set(0, top - (eave * Math.tan(RA)) / 2, s * eave / 2); g.rotation.x = s * RA; roof.add(g); roofHalves.push(g);
    mesh(roundedBox(W + 0.34, 0.06, slab, 0.015), rm, g);
    mesh(roundedBox(W + 0.36, 0.05, 0.05, 0.01), trim, g, [0, -0.02, s * slab / 2]);
    moves.push(mover(g, [0, 0.9, s * 0.25]));
  }
  mesh(new THREE.CylinderGeometry(0.035, 0.035, W + 0.36, 16), mat('matte', '#3e2722'), roof, [0, top + 0.02, 0], [0, 0, Math.PI / 2]);
  const chim = part(root, 'Chimney');
  mesh(roundedBox(0.22, 0.75, 0.22, 0.01), texMat(brickTex(), { kind: 'matte' }), chim, [W * 0.26, top - 0.1, -D * 0.16]);
  mesh(roundedBox(0.27, 0.05, 0.27, 0.01), mat('matte', '#6d6f73'), chim, [W * 0.26, top + 0.28, -D * 0.16]);
  moves.push(mover(chim, [0, 1.0, 0]));
  // inside: floors, a wall between rooms, stairs, and enough furniture to tell a living room from a bedroom
  const floors = part(root, 'Floors'), rooms = part(root, 'Rooms'), wood = texMat(woodTex('#c79a6a', '#a17448', 2), { kind: 'wood' });
  for (let f = 0; f < F; f++) {
    const fl = new THREE.Group(); floors.add(fl);
    mesh(roundedBox(W - 2 * T, 0.05, D - 2 * T, 0.005), wood, fl, [0, y0 + f * FH + 0.025, 0]);
    if (f) moves.push(mover(fl, [0, f * 0.35, 0]));
  }
  mesh(roundedBox(0.06, H - 0.05, D - 2 * T, 0.005), mat('matte', '#f2efe9'), rooms, [-0.15, y0 + H / 2, 0]);
  const sofa = mat('fabric', '#3f6e8c');
  mesh(roundedBox(0.6, 0.18, 0.24, 0.05), sofa, rooms, [-0.55, y0 + 0.14, -0.45]); mesh(roundedBox(0.6, 0.22, 0.07, 0.03), sofa, rooms, [-0.55, y0 + 0.25, -0.55]);
  mesh(roundedBox(0.34, 0.03, 0.22, 0.01), wood, rooms, [-0.55, y0 + 0.18, -0.1]);
  mesh(roundedBox(0.5, 0.3, 0.22, 0.01), mat('plastic', '#e8e4dc'), rooms, [0.6, y0 + 0.2, -0.55]);
  if (F > 1) {
    const bed = new THREE.Group(); rooms.add(bed);
    mesh(roundedBox(0.42, 0.14, 0.62, 0.04), mat('fabric', '#f4f1ea'), bed, [-0.6, y0 + FH + 0.13, -0.25]);
    mesh(roundedBox(0.42, 0.06, 0.4, 0.03), mat('fabric', '#b5534a'), bed, [-0.6, y0 + FH + 0.22, -0.14]);
    mesh(roundedBox(0.46, 0.3, 0.05, 0.02), wood, bed, [-0.6, y0 + FH + 0.2, -0.57]);
    moves.push(mover(bed, [0, 0.35, 0]));
    const stairs = part(root, 'Stairs');
    for (let i = 0; i < 9; i++) mesh(roundedBox(0.28, 0.05, 0.12, 0.01), wood, stairs, [0.2, y0 + 0.07 + i * (FH / 9), -0.5 + i * 0.1]);
  }
  return {
    group: root, explode: explodeWith(moves),
    cutaway: (on) => { front.visible = !on; roofHalves[0].visible = !on; windows.children.forEach((w) => { if (w.position.z > D / 2 - 0.1) w.visible = !on; }); dg.visible = !on; },
  };
}

function towerTex(seed) {
  const r = rng(seed);
  return canvasTex(256, 1024, (g, w, h) => {
    const grd = g.createLinearGradient(0, 0, 0, h); grd.addColorStop(0, '#6f8fae'); grd.addColorStop(1, '#22374d'); g.fillStyle = grd; g.fillRect(0, 0, w, h);
    for (let y = 0; y < h; y += 16) for (let x = 0; x < w; x += 16) { const lit = r() < 0.32; g.fillStyle = lit ? `rgba(255,${200 + r() * 40},${130 + r() * 60},${0.55 + r() * 0.4})` : 'rgba(10,20,30,0.35)'; g.fillRect(x + 2, y + 3, 12, 10); }
    g.fillStyle = 'rgba(200,220,235,0.35)'; for (let y = 0; y < h; y += 16) g.fillRect(0, y, w, 2);
  });
}
function skyscraperModel(P) {
  const root = new THREE.Group(), tiers = [[1.0, 1.6], [0.78, 1.0], [0.56, 0.7]], moves = [];
  mesh(roundedBox(1.5, 0.08, 1.5, 0.02), mat('matte', '#8f949b'), part(root, 'Plaza'), [0, 0.04, 0]);
  const lobby = part(root, 'Lobby');
  mesh(roundedBox(1.15, 0.28, 1.15, 0.02), mat('tinted', '#203040'), lobby, [0, 0.22, 0]).material.emissive = new THREE.Color('#ffd9a0');
  lobby.children[0].material.emissiveIntensity = 0.25;
  let y = 0.36;
  const tower = part(root, 'Tower');
  tiers.forEach(([w, h], i) => {
    const g = new THREE.Group(); tower.add(g);
    const tm = texMat(towerTex(i + 2), { kind: 'tinted', glow: 0.35 }); tm.map.repeat.set(1, h / 1.6 * 2);
    mesh(roundedBox(w, h, w, 0.03), tm, g, [0, y + h / 2, 0]);
    for (let k = 0; k <= 0; k++) mesh(roundedBox(w + 0.04, 0.04, w + 0.04, 0.01), mat('metal', '#c9ced4'), g, [0, y + h, 0]);
    moves.push(mover(g, [0, i * 0.35 + 0.2, 0]));
    y += h + 0.04;
  });
  const crown = part(root, 'Crown');
  mesh(roundedBox(0.4, 0.22, 0.4, 0.04), mat('metal', '#c9ced4'), crown, [0, y + 0.11, 0]);
  const spire = part(root, 'Spire');
  mesh(new THREE.CylinderGeometry(0.01, 0.04, 0.9, 16), mat('chrome', '#dfe3e8'), spire, [0, y + 0.22 + 0.45, 0]);
  blob(spire, [0, y + 1.13, 0], 0.025, 0.025, 0.025, mat('glow', '#ff4d4d'));
  moves.push(mover(crown, [0, 1.2, 0]), mover(spire, [0, 1.4, 0]));
  const core = part(root, 'Core');
  mesh(roundedBox(0.3, y - 0.4, 0.3, 0.01), mat('matte', '#b8bcc2'), core, [0, 0.36 + (y - 0.4) / 2, 0]);
  return { group: root, explode: explodeWith(moves) };
}

function eiffelModel() {
  const root = new THREE.Group(), Ht = 3.0, iron = mat('metal', '#7c6a55');
  iron.roughness = 0.55; iron.metalness = 0.75;
  const w = (y) => 0.78 * Math.pow(1 - Math.min(y, 2.9) / 3.05, 1.85) + 0.035;   // the tower's famous curve, half-width at height y
  const corners = (y, f = 1) => [[1, 1], [1, -1], [-1, -1], [-1, 1]].map(([a, b]) => V(a * w(y) * f, y, b * w(y) * f));
  const legs = part(root, 'Legs'), lattice = part(root, 'Lattice');
  // four great corner girders, thick at the feet
  for (let c = 0; c < 4; c++) {
    const pts = []; for (let i = 0; i <= 24; i++) { const y = (i / 24) * 2.75; pts.push(corners(y)[c]); }
    mesh(taper(pts, 0.07, 0.012, 80, 8), iron, c < 4 ? legs : lattice);
    // each leg is a lattice column of its own below the second floor
    const inner = []; for (let i = 0; i <= 12; i++) { const y = (i / 12) * 1.15; inner.push(corners(y, 0.62)[c]); }
    mesh(taper(inner, 0.04, 0.02, 40, 6), iron, legs);
  }
  // the braces: thin bars criss-crossing every face (one instanced mesh, thousands of rivets' worth of detail)
  const bars = [];
  const levels = Array.from({ length: 40 }, (_, i) => Math.pow(i / 39, 1.1) * 2.75);
  for (let i = 0; i < levels.length - 1; i++) {
    const a = corners(levels[i]), b = corners(levels[i + 1]);
    for (let s = 0; s < 4; s++) { const n = (s + 1) % 4; bars.push([a[s], b[n]], [a[n], b[s]]); if (i % 3 === 0) bars.push([a[s], a[n]]); }
    if (levels[i] < 1.15) { const ai = corners(levels[i], 0.62), bi = corners(levels[i + 1], 0.62); for (let s = 0; s < 4; s++) { bars.push([a[s], bi[s]], [ai[s], b[s]]); } }
  }
  const barGeo = new THREE.CylinderGeometry(1, 1, 1, 6), inst = new THREE.InstancedMesh(barGeo, iron, bars.length), m4 = new THREE.Matrix4(), q = new THREE.Quaternion();
  bars.forEach(([a, b], i) => { const d = b.clone().sub(a), len = d.length(); q.setFromUnitVectors(V(0, 1, 0), d.normalize()); m4.compose(a.clone().lerp(b, 0.5), q, V(0.006, len, 0.006)); inst.setMatrixAt(i, m4); });
  inst.castShadow = true; lattice.add(inst);
  // the arches between the legs
  const arches = part(root, 'Arches');
  for (let s = 0; s < 4; s++) {
    const a0 = corners(0.02)[s], a1 = corners(0.02)[(s + 1) % 4], pts = [];
    for (let i = 0; i <= 20; i++) { const t = i / 20, p = a0.clone().lerp(a1, t), y = Math.sin(t * Math.PI) * 0.42 + 0.02 * (1 - Math.sin(t * Math.PI)); p.y = y; const wy = w(y) / w(0.02); p.x *= wy; p.z *= wy; pts.push(p); }
    mesh(taper(pts, 0.022, 0.022, 60, 8), iron, arches);
  }
  // the three floors and the antenna
  const floor = (name, y, pad, h) => { const g = part(root, name); mesh(roundedBox(w(y) * 2 + pad, h, w(y) * 2 + pad, 0.01), mat('metal', '#6a5a48'), g, [0, y, 0]); mesh(roundedBox(w(y) * 2 + pad + 0.02, 0.02, w(y) * 2 + pad + 0.02, 0.005), mat('glow', '#ffd28a'), g, [0, y + h / 2 + 0.01, 0]).material.emissiveIntensity = 0.6; return g; };
  floor('First Floor', 0.57, 0.12, 0.09); floor('Second Floor', 1.15, 0.08, 0.07); floor('Top Floor', 2.76, 0.06, 0.08);
  const ant = part(root, 'Antenna');
  mesh(new THREE.CylinderGeometry(0.008, 0.02, 0.4, 12), mat('metal', '#bcc3cb'), ant, [0, 3.0, 0]);
  blob(ant, [0, 3.2, 0], 0.018, 0.018, 0.018, mat('glow', '#ffffff'));
  return { group: root };
}

function pyramidModel() {
  const root = new THREE.Group(), B = 2.3, Hh = 1.46;   // Khufu: 230 m square, 146 m tall
  const stone = canvasTex(256, 256, (g, w, h) => { g.fillStyle = '#d6b98a'; g.fillRect(0, 0, w, h); const r = rng(6); for (let y = 0; y < h; y += 16) { for (let x = -((y / 16) % 2) * 20; x < w; x += 40) { g.fillStyle = `rgba(80,55,25,${0.05 + r() * 0.12})`; g.fillRect(x + 1, y + 1, 38, 14); } g.fillStyle = 'rgba(70,45,20,0.35)'; g.fillRect(0, y + 14, w, 2); } }, { repeat: [6, 6] });
  const sm = texMat(stone, { kind: 'matte' }); sm.side = THREE.DoubleSide;
  const shell = part(root, 'Casing'), halves = [];
  for (const [start, name] of [[Math.PI / 4, 'back'], [Math.PI / 4 + Math.PI, 'front']]) {
    const g = new THREE.Group(); shell.add(g); halves.push(g);
    mesh(new THREE.ConeGeometry(B / Math.SQRT2, Hh, 4, 1, true, start, Math.PI), sm, g, [0, Hh / 2, 0]);
  }
  // the cut face, seen when it's opened
  const cut = mesh(new THREE.BufferGeometry().setFromPoints([V(-B / 2, 0, 0), V(B / 2, 0, 0), V(0, Hh, 0)]), mat('matte', '#c9a979'), shell);
  cut.geometry.computeVertexNormals(); cut.material.side = THREE.DoubleSide; cut.visible = false;
  mesh(new THREE.ConeGeometry(0.06, 0.08, 4), mat('metal', '#e2b84a'), part(root, 'Capstone'), [0, Hh + 0.03, 0], [0, Math.PI / 4, 0]);
  // inside: the chambers and passages, in their true places (scaled)
  const dark = mat('matte', '#3a2a18'), lit = mat('glow', '#ffc46b'); lit.emissiveIntensity = 0.5;
  const ch = (name, w, h, d, at) => { const g = part(root, name); mesh(roundedBox(w, h, d, 0.005), lit, g, at); return g; };
  ch("King's Chamber", 0.1, 0.06, 0.05, [0.0, 0.43 + 0.03, -0.01]);
  ch("Queen's Chamber", 0.06, 0.05, 0.05, [0, 0.21, 0]);
  ch('Subterranean Chamber', 0.14, 0.04, 0.08, [0.05, -0.0, 0.0]);
  const gal = part(root, 'Grand Gallery');
  mesh(roundedBox(0.03, 0.06, 0.48, 0.005), lit, gal, [0, 0.31, 0.16], [deg(26), 0, 0]);
  const pass = part(root, 'Passages');
  mesh(roundedBox(0.02, 0.02, 1.2, 0.003), dark, pass, [0, 0.12, 0.62], [deg(-26), 0, 0]);
  mesh(roundedBox(0.02, 0.02, 0.4, 0.003), dark, pass, [0, 0.2, 0.2]);
  const inside = ["King's Chamber", "Queen's Chamber", 'Subterranean Chamber', 'Grand Gallery', 'Passages'].map((n) => part(root, n));
  inside.forEach((g) => { g.visible = false; });
  mesh(roundedBox(B + 0.5, 0.04, B + 0.5, 0.02), mat('matte', '#c9a46a'), part(root, 'Plateau'), [0, -0.02, 0]);
  return { group: root, cutaway: (on) => { halves[1].visible = !on; cut.visible = on; inside.forEach((g) => { g.visible = on; }); } };
}

function buildingModel(spec) {
  const P = spec.params;
  if (P.kind === 'skyscraper') return skyscraperModel(P);
  if (P.kind === 'eiffel') return eiffelModel(P);
  if (P.kind === 'pyramid') return pyramidModel(P);
  return houseModel(P);
}

// ---------- vehicles ----------
function wheel(parent, at, radius, width, rimMat) {
  const g = new THREE.Group(); g.position.set(...at); parent.add(g);
  const tyre = mat('rubber', '#141518');
  mesh(lathe([[radius * 0.68, -width / 2], [radius * 0.92, -width / 2], [radius, -width * 0.32], [radius, width * 0.32], [radius * 0.92, width / 2], [radius * 0.68, width / 2]], 48), tyre, g, [0, 0, 0], [Math.PI / 2, 0, 0]);
  const rim = new THREE.Group(); g.add(rim);
  const side = Math.sign(at[2]) || 1;
  mesh(new THREE.CylinderGeometry(radius * 0.7, radius * 0.7, width * 0.7, 40), mat('metal', '#3a3d42'), rim, [0, 0, 0], [Math.PI / 2, 0, 0]);
  for (let i = 0; i < 5; i++) { const s = new THREE.Group(); s.rotation.z = (i / 5) * Math.PI * 2; rim.add(s); mesh(roundedBox(radius * 0.16, radius * 0.6, 0.02, 0.008), rimMat, s, [0, radius * 0.33, side * width * 0.36]); }
  mesh(new THREE.CylinderGeometry(radius * 0.18, radius * 0.18, 0.03, 24), rimMat, rim, [0, 0, side * width * 0.37], [Math.PI / 2, 0, 0]);
  mesh(new THREE.TorusGeometry(radius * 0.68, 0.012, 8, 48), rimMat, rim, [0, 0, side * width * 0.36]);
  mesh(new THREE.CylinderGeometry(radius * 0.52, radius * 0.52, 0.015, 40), mat('metal', '#8d9299'), g, [0, 0, -side * width * 0.1], [Math.PI / 2, 0, 0]);
  return { g, rim };
}
function carModel(P) {
  const root = new THREE.Group(), kind = P.kind || 'sedan', moves = [];
  const K = {
    sedan: { hl: 1.08, W: 0.47, belt: 0.6, deck: 0.6, hood: 0.56, nose: 0.42, roof: 0.95, cab0: 0.4, roofF: 0.02, roofR: -0.42, cab1: -0.72, R: 0.17, low: 0.15, color: '#2b5d9c' },
    sports: { hl: 1.1, W: 0.5, belt: 0.48, deck: 0.5, hood: 0.43, nose: 0.31, roof: 0.76, cab0: 0.3, roofF: -0.14, roofR: -0.36, cab1: -0.86, R: 0.17, low: 0.12, color: '#c8102e' },
    suv: { hl: 1.08, W: 0.5, belt: 0.78, deck: 0.8, hood: 0.74, nose: 0.6, roof: 1.2, cab0: 0.46, roofF: 0.24, roofR: -0.92, cab1: -1.0, R: 0.21, low: 0.24, color: '#3d4a3a' },
  }[kind] || {};
  const paint = mat('paint', P.color || K.color), hl = K.hl, R = K.R, Ra = R + 0.045, wx = hl * 0.64;
  // the body's side view: the top line (bonnet, waist, boot) and the bottom line with the wheel arches cut into it
  const top = curveOf([[-hl, K.deck - 0.16], [-hl + 0.07, K.deck - 0.02], [-hl + 0.3, K.deck], [K.cab1, K.belt + 0.01], [K.cab0, K.belt], [hl - 0.36, K.hood], [hl - 0.06, K.nose], [hl, K.nose - 0.12]]);
  const bottom = (x) => { let y = K.low; for (const c of [wx, -wx]) { const d = Math.abs(x - c); if (d < Ra) y = Math.max(y, R + Math.sqrt(Ra * Ra - d * d) * 0.98); } return y; };
  const plan = (x) => Math.pow(Math.max(0, 1 - Math.pow(Math.abs(x) / hl, 5)), 0.3);   // rounded corners seen from above
  const body = part(root, 'Body'), bodyG = new THREE.Group(); body.add(bodyG);
  mesh(loft(140, 48, (u, v, out) => {
    const x = -hl + u * 2 * hl, yt = top(x), yb = bottom(x), ym = (yt + yb) / 2, hh = (yt - yb) / 2, [z, y] = squircle(v * Math.PI * 2, K.W * plan(x), hh, 4.5);
    const yy = ym + y, tumble = yy > ym ? 1 - 0.1 * Math.pow((yy - ym) / Math.max(hh, 1e-3), 2) : 1;
    out.set(x, yy, z * tumble);
  }), paint, bodyG);
  // dark wheel wells inside the arches
  for (const c of [wx, -wx]) mesh(new THREE.CylinderGeometry(Ra * 0.98, Ra * 0.98, K.W * 1.9, 32, 1, true, Math.PI / 2, Math.PI), mat('matte', '#0b0c0e'), bodyG, [c, R, 0], [Math.PI / 2, 0, 0]).material.side = THREE.DoubleSide;
  // the cabin: a dome of glass on the waist line, narrower at the top, with a roof in the body colour
  const cabin = part(root, 'Cabin'), cabG = new THREE.Group(); cabin.add(cabG);
  const roofLine = curveOf([[K.cab1, K.belt], [K.roofR, K.roof], [K.roofF, K.roof + 0.01], [K.cab0, K.belt]]);
  const cabMid = (K.cab0 + K.cab1) / 2;
  mesh(loft(90, 40, (u, v, out) => {
    const x = K.cab1 + u * (K.cab0 - K.cab1), yb = top(x) - 0.04, h = Math.max(0.002, roofLine(x) - yb + 0.04), a = v * Math.PI * 2;
    const s = Math.sin(a), c = Math.cos(a), y = s > 0 ? Math.pow(s, 0.7) * h : s * 0.02, k = y > 0 ? 1 - 0.22 * (y / h) : 1;
    out.set(x, yb + y, Math.sign(c) * Math.pow(Math.abs(c), 0.7) * K.W * plan(x) * 0.9 * k);
  }), mat('tinted', '#121820'), cabG);
  mesh(loft(60, 32, (u, v, out) => {
    const x = K.roofR + 0.06 + u * (K.roofF - K.roofR - 0.12), a = v * Math.PI * 2, s = Math.sin(a), c = Math.cos(a), env = Math.pow(Math.sin(Math.PI * u), 0.15);
    out.set(x, roofLine(x) - 0.012 + s * 0.022 * env, Math.sign(c) * Math.pow(Math.abs(c), 0.5) * K.W * 0.72 * env);
  }), paint, cabG);
  moves.push(mover(bodyG, [0, 0.42, 0]), mover(cabG, [0, 0.9, 0]));
  // lights, grille, mirrors, door handles, number plates
  const lights = part(root, 'Headlights'), tail = part(root, 'Taillights');
  for (const z of [-1, 1]) {
    mesh(roundedBox(0.05, 0.032, 0.17, 0.014), mat('glow', '#dff1ff'), lights, [hl - 0.07, K.nose - 0.05, z * K.W * 0.64], [0, z * deg(-18), deg(-12)]);
    mesh(roundedBox(0.06, 0.05, 0.16, 0.02), mat('paint', '#14161a'), bodyG, [K.cab0 - 0.04, K.belt + 0.04, z * (K.W * 0.95 + 0.04)]);
    for (const x of [0.12, cabMid - 0.18]) mesh(roundedBox(0.1, 0.018, 0.02, 0.008), mat('chrome', '#cfd5db'), bodyG, [x, K.belt - 0.06, z * K.W * 0.96]);
  }
  mesh(roundedBox(0.04, 0.05, K.W * 1.5, 0.02), mat('glow', '#ff2a2a'), tail, [-hl + 0.02, K.deck - 0.06, 0]);
  mesh(roundedBox(0.04, 0.09, K.W * 0.9, 0.03), mat('gloss', '#0d0e10'), bodyG, [hl - 0.02, K.nose - 0.17, 0]);
  for (const x of [hl - 0.005, -hl + 0.005]) mesh(roundedBox(0.012, 0.06, 0.22, 0.008), mat('plastic', '#f2f2f2'), bodyG, [x, K.low + 0.12, 0]);
  // wheels
  const wheels = part(root, 'Wheels');
  for (const x of [wx, -wx]) for (const z of [-1, 1]) {
    const w = wheel(wheels, [x, R, z * (K.W - 0.07)], R, 0.15, mat('chrome', '#d7dce2'));
    moves.push(mover(w.g, [x * 0.25, 0, z * 0.45]));
  }
  // inside: seats, the steering wheel and the dashboard; under the bonnet, the engine
  const interior = part(root, 'Interior'), seat = mat('fabric', '#2d2f35'), sy = K.belt - 0.2;
  for (const x of [cabMid + 0.12, cabMid - 0.3]) for (const z of [-0.18, 0.18]) { mesh(roundedBox(0.22, 0.07, 0.22, 0.03), seat, interior, [x, sy, z]); mesh(roundedBox(0.07, 0.3, 0.22, 0.03), seat, interior, [x - 0.12, sy + 0.16, z], [0, 0, deg(-10)]); }
  mesh(new THREE.TorusGeometry(0.075, 0.011, 10, 32), mat('rubber', '#1a1a1a'), interior, [K.cab0 - 0.14, K.belt + 0.04, 0.18], [0, Math.PI / 2, deg(-20)]);
  mesh(roundedBox(0.16, 0.08, K.W * 1.6, 0.03), mat('plastic', '#25272c'), interior, [K.cab0 - 0.06, K.belt - 0.02, 0]);
  const engine = part(root, 'Engine'), eg = new THREE.Group(); engine.add(eg);
  const ey = top(hl * 0.62) - 0.2;   // under the bonnet, not through it
  mesh(roundedBox(0.34, 0.18, 0.44, 0.03), mat('metal', '#6b7178'), eg, [hl * 0.62, ey, 0]);
  mesh(roundedBox(0.3, 0.04, 0.32, 0.02), mat('metal', '#b33a3a'), eg, [hl * 0.62, ey + 0.1, 0]);
  moves.push(mover(eg, [0.35, 0.3, 0]));
  return { group: root, explode: explodeWith(moves) };
}

function liveryTex(stripe) {
  return canvasTex(2048, 512, (g, w, h) => {
    // u runs round the fuselage (0: the right side, a little above the middle), v along it from the nose
    g.fillStyle = '#f5f7f9'; g.fillRect(0, 0, w, h);
    g.fillStyle = '#c9ced4'; g.fillRect(w * 0.62, 0, w * 0.26, h);   // the belly
    for (const u of [0.03, 0.47]) {
      g.fillStyle = stripe; g.fillRect((u - 0.03) * w, h * 0.12, w * 0.012, h * 0.82);
      g.fillStyle = '#1a2230';
      for (let v = 0.16; v < 0.8; v += 0.018) g.fillRect(u * w - 6, v * h, 12, h * 0.009);
      g.fillRect(u * w - 30, h * 0.07, 60, h * 0.022);   // cockpit windows
    }
  });
}
function planeModel(P) {
  const root = new THREE.Group(), L = 3.2, livery = P.color || '#1f4fae';
  const prof = Array.from({ length: 64 }, (_, i) => { const y = (i / 63) * L, t = y / L; const r = t < 0.12 ? 0.19 * Math.sqrt(t / 0.12) * (1 - Math.pow(1 - t / 0.12, 3) * 0.1) : t < 0.7 ? 0.19 : 0.19 * (1 - Math.pow((t - 0.7) / 0.3, 1.4) * 0.82); return [r, y]; });
  const fgeo = lathe(prof, 64), p = fgeo.attributes.position;
  for (let i = 0; i < p.count; i++) { const y = p.getY(i); if (y > L * 0.72) p.setX(i, p.getX(i) + Math.pow((y - L * 0.72) / (L * 0.28), 2) * 0.13); }
  fgeo.computeVertexNormals();
  const fus = part(root, 'Fuselage'), body = new THREE.Group(); body.rotation.z = Math.PI / 2; body.position.set(L / 2, 0.55, 0); fus.add(body);
  mesh(fgeo, texMat(liveryTex(livery), { kind: 'plastic' }), body);
  mesh(new THREE.SphereGeometry(0.06, 24, 16, 0, Math.PI * 2, 0, Math.PI / 2), mat('tinted', '#141c24'), part(root, 'Cockpit'), [L / 2 - 0.2, 0.67, 0], [0, 0, deg(-60)], [1.6, 0.6, 1.9]);
  // swept wings with a little dihedral, winglets at the tips
  const wings = part(root, 'Wings'), wm = mat('paint', '#e3e7eb');
  const plan = [[0.45, 0], [-0.35, 1.45], [-0.55, 1.45], [-0.35, 0]];
  for (const s of [1, -1]) {
    const g = new THREE.Group(); g.position.set(0.25, 0.48, 0); g.rotation.x = s * deg(5); wings.add(g);
    const wgeo = extrude(plan, 0.04, 0.012); const wmesh = mesh(wgeo, wm, g, [0, 0, 0], [-s * Math.PI / 2, 0, 0]);
    if (s < 0) wmesh.scale.z = -1;
    mesh(extrude([[0, 0], [0.12, 0], [0.04, 0.22], [-0.04, 0.22]], 0.02, 0.006), mat('paint', livery), g, [-0.52, 0, -s * 1.45], [0, 0, 0]);
  }
  // engines under the wings: a nacelle, a chrome lip, a fan that turns
  const engines = part(root, 'Engines'), fans = [];
  for (const s of [1, -1]) {
    const g = new THREE.Group(); g.position.set(0.32, 0.36, s * 0.62); engines.add(g);
    const ng = lathe([[0.1, 0], [0.12, 0.05], [0.115, 0.35], [0.07, 0.48], [0.04, 0.5]], 40);
    mesh(ng, mat('paint', '#d9dde2'), g, [0, 0, 0], [0, 0, Math.PI / 2]).material.side = THREE.DoubleSide;
    mesh(new THREE.TorusGeometry(0.105, 0.012, 12, 40), mat('chrome', '#cfd5db'), g, [0, 0, 0], [0, Math.PI / 2, 0]);
    const fan = new THREE.Group(); fan.position.x = -0.04; g.add(fan); fans.push(fan);
    for (let i = 0; i < 18; i++) { const b = new THREE.Group(); b.rotation.x = (i / 18) * Math.PI * 2; fan.add(b); mesh(roundedBox(0.008, 0.09, 0.025, 0.003), mat('metal', '#4a5058'), b, [0, 0.05, 0], [deg(30), 0, 0]); }
    mesh(new THREE.ConeGeometry(0.03, 0.05, 20), mat('chrome', '#e5e9ee'), fan, [0.02, 0, 0], [0, 0, -Math.PI / 2]);
    mesh(roundedBox(0.3, 0.12, 0.03, 0.01), mat('paint', '#d9dde2'), g, [-0.12, 0.1, 0]);
  }
  // the tail: a fin in the airline's colour and two stabilisers
  const fin = part(root, 'Tail Fin');
  mesh(extrude([[0, 0], [0.42, 0], [0.16, 0.62], [-0.04, 0.62]], 0.03, 0.01), mat('paint', livery), fin, [-L / 2 + 0.05, 0.66, 0]);
  const stab = part(root, 'Stabilizers');
  for (const s of [1, -1]) { const m = mesh(extrude([[0, 0], [0.3, 0], [0.08, 0.5], [-0.04, 0.5]], 0.025, 0.008), wm, stab, [-L / 2 + 0.08, 0.7, 0], [-s * Math.PI / 2, 0, 0]); if (s < 0) m.scale.z = -1; }
  // landing gear
  const gear = part(root, 'Landing Gear'), tyre = mat('rubber', '#141518');
  for (const [x, z] of [[L / 2 - 0.45, 0], [0.0, 0.2], [0.0, -0.2]]) {
    limb(gear, [x, 0.4, z], [x, 0.08, z], 0.012, 0.012, mat('chrome', '#cfd5db'), false);
    for (const dz of [-0.035, 0.035]) mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.04, 24), tyre, gear, [x, 0.06, z + dz], [Math.PI / 2, 0, 0]);
  }
  return { group: root, animate: (t, dt) => fans.forEach((f) => { f.rotation.x += dt * 9; }) };
}

function rocketModel() {
  const root = new THREE.Group(), moves = [], white = mat('paint', '#f2f4f6'), black = mat('paint', '#16181c');
  const stage = (name, y0, h, r, m) => { const g = part(root, name); mesh(new THREE.CylinderGeometry(r, r, h, 48), m, g, [0, y0 + h / 2, 0]); return g; };
  const s1 = stage('First Stage', 0.25, 1.7, 0.22, white);
  mesh(new THREE.CylinderGeometry(0.222, 0.222, 0.14, 48), black, s1, [0, 0.5, 0]);
  const inter = stage('Interstage', 1.95, 0.18, 0.222, black);
  const s2 = stage('Second Stage', 2.13, 0.75, 0.22, white);
  const fair = part(root, 'Payload Fairing');
  mesh(lathe([[0.235, 0], [0.235, 0.32], [0.2, 0.52], [0.13, 0.68], [0.04, 0.8], [0, 0.82]], 48), white, fair, [0, 2.88, 0]);
  const payload = part(root, 'Payload'); mesh(roundedBox(0.18, 0.28, 0.18, 0.02), mat('metal', '#d4a54a'), payload, [0, 3.06, 0]);
  for (const s of [-1, 1]) mesh(roundedBox(0.36, 0.005, 0.12, 0.002), mat('tinted', '#203a6a'), payload, [s * 0.28, 3.08, 0]);
  payload.visible = false;
  const fins = part(root, 'Fins');
  for (let i = 0; i < 4; i++) { const g = new THREE.Group(); g.rotation.y = (i / 4) * Math.PI * 2 + Math.PI / 4; fins.add(g); mesh(extrude([[0, 0], [0.24, -0.08], [0.24, 0.12], [0, 0.4]], 0.025, 0.008), black, g, [0.2, 0.3, 0]); }
  const eng = part(root, 'Engines');
  for (const [x, z] of [[0, 0], [0.11, 0.11], [-0.11, 0.11], [0.11, -0.11], [-0.11, -0.11]]) mesh(lathe([[0.03, 0.25], [0.035, 0.2], [0.06, 0.08], [0.075, 0]], 32), mat('metal', '#5a5f66'), eng, [x, 0.0, z]).material.side = THREE.DoubleSide;
  const flame = part(root, 'Exhaust');
  const fm = mat('glow', '#ffb347'); fm.transparent = true; fm.opacity = 0.85; fm.depthWrite = false;
  const plume = mesh(new THREE.ConeGeometry(0.2, 0.9, 32, 1, true), fm, flame, [0, -0.45, 0], [Math.PI, 0, 0]); plume.castShadow = false;
  const core = mesh(new THREE.ConeGeometry(0.1, 0.5, 24, 1, true), mat('glow', '#fff4d6'), flame, [0, -0.25, 0], [Math.PI, 0, 0]); core.castShadow = false;
  moves.push(mover(fair, [0, 1.2, 0]), mover(s2, [0, 0.8, 0]), mover(inter, [0, 0.4, 0]));
  root.position.y = 0.6;
  return {
    group: root, explode: (k) => { explodeWith(moves)(k); payload.visible = k > 0.05; payload.position.y = k * 0.9; },
    animate: (t) => { plume.scale.set(1 + Math.sin(t * 37) * 0.06, 1 + Math.sin(t * 23) * 0.12, 1 + Math.sin(t * 41) * 0.06); core.scale.y = 1 + Math.sin(t * 53) * 0.15; },
  };
}

function vehicleModel(spec) {
  const P = spec.params;
  if (P.kind === 'plane') return planeModel(P);
  if (P.kind === 'rocket') return rocketModel(P);
  return carModel(P);
}

// ---------- devices ----------
function sceneTex() {
  return canvasTex(1024, 576, (g, w, h) => {
    const sky = g.createLinearGradient(0, 0, 0, h * 0.7); sky.addColorStop(0, '#1b2a6b'); sky.addColorStop(0.55, '#c0587e'); sky.addColorStop(1, '#ffb36b'); g.fillStyle = sky; g.fillRect(0, 0, w, h);
    g.fillStyle = 'rgba(255,240,200,0.95)'; g.beginPath(); g.arc(w * 0.62, h * 0.55, 46, 0, 7); g.fill();
    const hills = (col, base, amp, f, ph) => { g.fillStyle = col; g.beginPath(); g.moveTo(0, h); for (let x = 0; x <= w; x += 8) g.lineTo(x, base - Math.abs(Math.sin(x / f + ph)) * amp - Math.sin(x / (f * 0.37)) * amp * 0.3); g.lineTo(w, h); g.fill(); };
    hills('#5a3c6e', h * 0.62, 90, 160, 1); hills('#36294f', h * 0.7, 60, 110, 2.3); hills('#1c1830', h * 0.8, 40, 70, 0.4);
    const lake = g.createLinearGradient(0, h * 0.8, 0, h); lake.addColorStop(0, '#ff9e6b'); lake.addColorStop(1, '#1b2a6b'); g.fillStyle = lake; g.fillRect(0, h * 0.8, w, h * 0.2);
  });
}
function phoneScreenTex() {
  return canvasTex(512, 1024, (g, w, h) => {
    const bg = g.createLinearGradient(0, 0, w, h); bg.addColorStop(0, '#3a1c71'); bg.addColorStop(0.5, '#d76d77'); bg.addColorStop(1, '#ffaf7b'); g.fillStyle = bg; g.fillRect(0, 0, w, h);
    g.fillStyle = 'rgba(255,255,255,0.92)'; g.font = '600 120px -apple-system, Helvetica, Arial'; g.textAlign = 'center'; g.fillText('9:41', w / 2, 230);
    const cols = ['#4fd8ff', '#7ee787', '#ffd166', '#ff7b72', '#a58bff', '#f2f2f2', '#56d364', '#79c0ff'];
    for (let i = 0; i < 16; i++) { const x = 60 + (i % 4) * 110, y = 360 + Math.floor(i / 4) * 130; g.fillStyle = cols[i % cols.length]; g.beginPath(); g.roundRect?.(x, y, 84, 84, 20); g.fill(); }
    g.fillStyle = 'rgba(255,255,255,0.25)'; g.beginPath(); g.roundRect?.(30, h - 170, w - 60, 120, 40); g.fill();
  });
}
function boardTex() {
  const r = rng(12);
  return canvasTex(512, 512, (g, w, h) => {
    g.fillStyle = '#145a32'; g.fillRect(0, 0, w, h);
    g.strokeStyle = 'rgba(212,175,55,0.55)'; g.lineWidth = 2;
    for (let i = 0; i < 70; i++) { g.beginPath(); let x = r() * w, y = r() * h; g.moveTo(x, y); for (let k = 0; k < 4; k++) { if (r() < 0.5) x += (r() - 0.5) * 160; else y += (r() - 0.5) * 160; g.lineTo(x, y); } g.stroke(); }
  });
}
function chip(parent, w, d, at, label) { const c = mesh(roundedBox(w, 0.012, d, 0.003), mat('matte', '#1b1d22'), parent, at); return c; }

function tvModel(P) {
  const root = new THREE.Group(), moves = [], Wd = 1.6, Hd = 0.9, y0 = 0.62;
  const layer = (name, geo, m, z) => { const g = part(root, name); mesh(geo, m, g, [0, y0, z]); moves.push(mover(g, [0, 0, z * 9])); return g; };
  layer('Front Glass', new THREE.PlaneGeometry(Wd - 0.03, Hd - 0.03), mat('glass', '#cfe8ff'), 0.016);
  layer('Screen', new THREE.PlaneGeometry(Wd - 0.03, Hd - 0.03), texMat(sceneTex(), { kind: 'matte', glow: 1.0 }), 0.01);
  const bl = layer('Backlight', new THREE.PlaneGeometry(Wd - 0.06, Hd - 0.06), mat('glow', '#f2f6ff'), -0.004); bl.children[0].material.emissiveIntensity = 0.7;
  const frame = part(root, 'Frame'); mesh(extrude(rect(Wd + 0.03, Hd + 0.03), 0.03, 0.006, [reverse(rect(Wd - 0.03, Hd - 0.03))]), mat('gloss', '#0d0e10'), frame, [0, y0, 0.004]);
  mesh(roundedBox(Wd, Hd, 0.012, 0.004), mat('gloss', '#0d0e10'), frame, [0, y0, -0.012]);
  const board = part(root, 'Mainboard'); const bg = new THREE.Group(); bg.position.set(0.25, y0 - 0.05, -0.04); board.add(bg);
  mesh(roundedBox(0.45, 0.3, 0.012, 0.004), texMat(boardTex()), bg); chip(bg, 0.08, 0.08, [0, 0, 0.012]); mesh(roundedBox(0.06, 0.04, 0.02, 0.005), mat('metal', '#9aa3ad'), bg, [-0.15, 0.08, 0.012]);
  const psu = part(root, 'Power Supply'); const pg = new THREE.Group(); pg.position.set(-0.3, y0 - 0.05, -0.04); psu.add(pg);
  mesh(roundedBox(0.4, 0.26, 0.012, 0.004), texMat(boardTex()), pg); for (let i = 0; i < 3; i++) mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.06, 20), mat('plastic', '#20232a'), pg, [-0.1 + i * 0.07, 0.04, 0.035], [Math.PI / 2, 0, 0]);
  const sp = part(root, 'Speakers'); for (const x of [-0.6, 0.6]) mesh(roundedBox(0.22, 0.06, 0.05, 0.02), mat('fabric', '#2a2c31'), sp, [x, y0 - Hd / 2 + 0.06, -0.05]);
  const back = part(root, 'Back Cover'); mesh(roundedBox(1.1, 0.62, 0.07, 0.03), mat('plastic', '#1d1f23'), back, [0, y0 - 0.04, -0.06]);
  moves.push(mover(bg, [0, 0, -0.45]), mover(pg, [0, 0, -0.45]), mover(sp.children[0], [0, -0.1, -0.6]), mover(sp.children[1], [0, -0.1, -0.6]), mover(back.children[0], [0, 0, -0.85]));
  const stand = part(root, 'Stand');
  for (const x of [-0.6, 0.6]) { mesh(roundedBox(0.05, 0.2, 0.05, 0.015), mat('metal', '#2b2e33'), stand, [x, 0.1, 0], [deg(-12), 0, 0]); mesh(roundedBox(0.08, 0.02, 0.32, 0.01), mat('metal', '#2b2e33'), stand, [x, 0.01, 0.02]); }
  return { group: root, explode: explodeWith(moves) };
}
function laptopModel() {
  const root = new THREE.Group(), moves = [], alu = mat('metal', '#c3c7cd'); alu.roughness = 0.38;
  const base = part(root, 'Case'); mesh(roundedBox(1.4, 0.035, 0.95, 0.03), alu, base, [0, 0.0175, 0]);
  const kb = part(root, 'Keyboard'), kg = new THREE.Group(); kb.add(kg);
  const keyGeo = roundedBox(0.075, 0.012, 0.075, 0.012), inst = new THREE.InstancedMesh(keyGeo, mat('plastic', '#1d1f23'), 6 * 14), m4 = new THREE.Matrix4();
  let n = 0; for (let r = 0; r < 6; r++) for (let c = 0; c < 14; c++) { m4.makeTranslation(-0.56 + c * 0.086, 0.042, -0.32 + r * 0.086 * (r === 0 ? 0.6 : 1)); inst.setMatrixAt(n++, m4); }
  inst.castShadow = true; kg.add(inst);
  const tp = part(root, 'Trackpad'); mesh(roundedBox(0.46, 0.004, 0.28, 0.02), mat('metal', '#b3b8bf'), tp, [0, 0.036, 0.3]);
  const batt = part(root, 'Battery'), bg = new THREE.Group(); batt.add(bg); for (const x of [-0.35, 0, 0.35]) mesh(roundedBox(0.3, 0.012, 0.42, 0.01), mat('plastic', '#2b2f36'), bg, [x, 0.012, 0.18]);
  const mb = part(root, 'Motherboard'), mg = new THREE.Group(); mb.add(mg); mesh(roundedBox(1.1, 0.006, 0.3, 0.004), texMat(boardTex()), mg, [0, 0.012, -0.25]); chip(mg, 0.1, 0.1, [0, 0.02, -0.25]); for (const x of [-0.3, 0.3]) chip(mg, 0.06, 0.1, [x, 0.02, -0.25]);
  const fan = part(root, 'Fan'), fg = new THREE.Group(); fg.position.set(0.48, 0.016, -0.25); fan.add(fg); for (let i = 0; i < 9; i++) { const b = new THREE.Group(); b.rotation.y = (i / 9) * Math.PI * 2; fg.add(b); mesh(roundedBox(0.06, 0.006, 0.015, 0.003), mat('plastic', '#3a3f47'), b, [0.035, 0, 0], [0, 0, deg(20)]); }
  // the lid, open past upright, with the screen on
  const lid = part(root, 'Screen'), hinge = new THREE.Group(); hinge.position.set(0, 0.035, -0.46); hinge.rotation.x = deg(-16); lid.add(hinge);
  mesh(roundedBox(1.4, 0.92, 0.022, 0.03), alu, hinge, [0, 0.46, 0]);
  mesh(roundedBox(1.38, 0.9, 0.004, 0.025), mat('gloss', '#0b0c0e'), hinge, [0, 0.46, 0.012]);
  mesh(new THREE.PlaneGeometry(1.3, 0.8), texMat(sceneTex(), { glow: 1.0 }), hinge, [0, 0.47, 0.0145]);
  moves.push(mover(hinge, [0, 0.5, -0.2]), mover(kg, [0, 0.5, 0]), mover(tp, [0, 0.5, 0.15]), mover(bg, [0, 0.25, 0.2]), mover(mg, [0, 0.3, -0.1]), mover(fg, [0.2, 0.3, 0]));
  return { group: root, explode: explodeWith(moves), animate: (t, dt) => { fg.rotation.y += dt * 12; } };
}
function phoneModel() {
  const root = new THREE.Group(), moves = [], W = 0.75, H = 1.55, y0 = 0.85;
  const holder = new THREE.Group(); holder.position.y = y0; holder.rotation.x = deg(-8); root.add(holder);
  const layer = (name, build, z) => { const g = part(root, name), lg = new THREE.Group(); lg.position.z = z; g.add(lg); holder.add(g); build(lg); moves.push(mover(lg, [0, 0, z > 0 ? 0.45 + z * 4 : -0.45 + z * 4])); return lg; };
  layer('Screen', (g) => { mesh(roundedBox(W - 0.01, H - 0.01, 0.012, 0.1), mat('gloss', '#08090b'), g); mesh(new THREE.PlaneGeometry(W - 0.07, H - 0.07), texMat(phoneScreenTex(), { glow: 1.1 }), g, [0, 0, 0.007]); }, 0.035);
  const frame = part(root, 'Frame'); holder.add(frame); mesh(roundedBox(W, H, 0.06, 0.1), mat('chrome', '#9aa1a9'), frame);
  layer('Battery', (g) => mesh(roundedBox(W * 0.62, H * 0.5, 0.02, 0.03), mat('plastic', '#2b2f36'), g, [0, -0.15, 0]), -0.01);
  layer('Logic Board', (g) => { mesh(roundedBox(W * 0.28, H * 0.55, 0.008, 0.02), texMat(boardTex()), g, [0.18, 0.28, 0]); chip(g, 0.1, 0.1, [0.18, 0.35, 0.008]); }, 0.0);
  layer('Cameras', (g) => { mesh(roundedBox(0.28, 0.28, 0.025, 0.07), mat('gloss', '#2a2d33'), g, [0.17, 0.52, 0]); for (const [x, y] of [[0.11, 0.58], [0.23, 0.46], [0.11, 0.46]]) { mesh(new THREE.CylinderGeometry(0.048, 0.05, 0.03, 32), mat('chrome', '#80868e'), g, [x, y, -0.012], [Math.PI / 2, 0, 0]); mesh(new THREE.CircleGeometry(0.035, 32), mat('gloss', '#0a0c12'), g, [x, y, -0.028], [Math.PI, 0, 0]); } }, -0.04);
  layer('Back Glass', (g) => mesh(roundedBox(W - 0.01, H - 0.01, 0.01, 0.1), mat('gloss', P_color()), g), -0.033);
  return { group: root, explode: explodeWith(moves) };
}
let P_color = () => '#3d4a5c';
function deviceModel(spec) {
  const P = spec.params;
  P_color = () => P.color || '#3d4a5c';
  if (P.kind === 'laptop') return laptopModel(P);
  if (P.kind === 'phone') return phoneModel(P);
  return tvModel(P);
}

// ---------- a guitar ----------
function guitarModel(spec) {
  const P = spec.params, electric = P.kind === 'electric', root = new THREE.Group(), y0 = 0.08;
  const holder = new THREE.Group(); holder.rotation.x = deg(-12); holder.position.set(0, 0.62, 0); root.add(holder);   // leaning, as on a stand
  // the body: two bouts and a waist, traced as one smooth outline
  const half = (y) => electric ? 0.36 * Math.sqrt(Math.max(0, 1 - Math.pow((y - 0.0) / 0.48, 2))) * (1 - 0.18 * Math.exp(-Math.pow((y - 0.12) / 0.08, 2)))
    : Math.max(0.4 * Math.sqrt(Math.max(0, 1 - Math.pow((y + 0.05) / 0.42, 2))), 0.3 * Math.sqrt(Math.max(0, 1 - Math.pow((y - 0.42) / 0.3, 2))), y > -0.1 && y < 0.5 ? 0.26 : 0);
  const ys = Array.from({ length: 80 }, (_, i) => (electric ? -0.48 : -0.47) + (i / 79) * (electric ? 0.96 : 1.19));
  const outline = smoothOutline([...ys.map((y) => [half(y) + 0.002, y]), ...ys.slice().reverse().map((y) => [-half(y) - 0.002, y])].filter((_, i) => i % 2 === 0), 160);
  const top = electric ? mat('paint', P.color || '#b3121b') : texMat(woodTex('#e3b778', '#b98c4e', 7), { kind: 'gloss' });
  const bodyP = part(root, 'Body'); holder.add(bodyP);
  mesh(extrude(outline, electric ? 0.07 : 0.16, 0.012), electric ? top : texMat(woodTex('#6b3a1e', '#3e1f0e', 4), { kind: 'gloss' }), bodyP, [0, 0, 0]);
  if (!electric) {
    mesh(extrude(outline, 0.004, 0), top, bodyP, [0, 0, 0.081]);
    const hole = part(root, 'Sound Hole'); holder.add(hole);
    mesh(new THREE.CircleGeometry(0.11, 48), mat('matte', '#0a0806'), hole, [0, 0.3, 0.0845]);
    mesh(new THREE.RingGeometry(0.115, 0.14, 64), mat('gloss', '#3a2412'), hole, [0, 0.3, 0.085]);
  } else {
    const pick = part(root, 'Pickups'); holder.add(pick);
    for (const y of [-0.05, 0.14]) mesh(roundedBox(0.2, 0.06, 0.02, 0.01), mat('gloss', '#111214'), pick, [0, y, 0.045]);
    const knobs = part(root, 'Knobs'); holder.add(knobs);
    for (const [x, y] of [[0.2, -0.25], [0.26, -0.15], [0.14, -0.35]]) mesh(new THREE.CylinderGeometry(0.025, 0.028, 0.03, 24), mat('chrome', '#cfd5db'), knobs, [x, y, 0.05], [Math.PI / 2, 0, 0]);
  }
  const zTop = electric ? 0.036 : 0.084;
  const bridge = part(root, 'Bridge'); holder.add(bridge);
  mesh(roundedBox(0.24, 0.05, 0.02, 0.008), mat('gloss', electric ? '#9aa1a9' : '#2a1608'), bridge, [0, -0.2, zTop + 0.01]);
  // the neck, the fretboard with its frets and dots, the headstock and its tuners
  const neckTop = 1.75, neckBase = electric ? 0.3 : 0.58;
  const neck = part(root, 'Neck'); holder.add(neck);
  mesh(roundedBox(0.1, neckTop - neckBase, 0.05, 0.02), mat('wood', '#c58b4f'), neck, [0, (neckTop + neckBase) / 2, zTop - 0.02]);
  const fb = part(root, 'Fretboard'); holder.add(fb);
  mesh(roundedBox(0.095, neckTop - neckBase + 0.15, 0.012, 0.004), mat('wood', '#2a1608'), fb, [0, (neckTop + neckBase) / 2 - 0.075, zTop + 0.01]);
  const frets = part(root, 'Frets'); holder.add(frets);
  for (let i = 1; i <= 19; i++) { const y = neckTop - (neckTop - neckBase + 0.15) * (1 - Math.pow(2, -i / 12)) * 1.33; if (y < neckBase - 0.15) break; mesh(new THREE.CylinderGeometry(0.003, 0.003, 0.095, 6), mat('chrome', '#d7dce2'), frets, [0, y, zTop + 0.017], [0, 0, Math.PI / 2]); if ([3, 5, 7, 9, 12].includes(i)) blob(frets, [0, y + 0.03, zTop + 0.017], 0.008, 0.008, 0.002, mat('gloss', '#f4efe6')); }
  const head = part(root, 'Headstock'); holder.add(head);
  mesh(extrude([[-0.06, 0], [0.06, 0], [0.08, 0.26], [-0.08, 0.26]], 0.025, 0.006), mat('gloss', '#2a1608'), head, [0, neckTop, zTop - 0.02], [deg(-12), 0, 0]);
  const tuners = part(root, 'Tuning Pegs'); holder.add(tuners);
  for (let i = 0; i < 6; i++) { const s = i < 3 ? -1 : 1, y = neckTop + 0.06 + (i % 3) * 0.075; mesh(new THREE.CylinderGeometry(0.01, 0.01, 0.06, 12), mat('chrome', '#d7dce2'), tuners, [s * 0.085, y, zTop - 0.01], [0, 0, Math.PI / 2]); mesh(roundedBox(0.03, 0.035, 0.008, 0.004), mat('chrome', '#d7dce2'), tuners, [s * 0.12, y, zTop - 0.01]); }
  // six strings from the bridge to the nut
  const strings = part(root, 'Strings'); holder.add(strings);
  const sm = mat('chrome', '#e8e2d2'), strs = [];
  for (let i = 0; i < 6; i++) { const x = -0.035 + i * 0.014, r = 0.0018 + (5 - i) * 0.0004; strs.push(limb(strings, [x, -0.2, zTop + 0.024], [x * 0.85, neckTop, zTop + 0.02], r, r, sm, false)); }
  mesh(roundedBox(0.1, 0.012, 0.012, 0.003), mat('plastic', '#f2eadb'), strings, [0, neckTop, zTop + 0.016]);
  return { group: root, animate: (t) => strs.forEach((s, i) => { s.scale.x = s.scale.z = 1 + Math.abs(Math.sin(t * (30 + i * 7))) * 0.6 * Math.max(0, Math.sin(t * 0.7 - i * 0.12)); }) };
}

// ---------- a sneaker ----------
function shoeModel(spec) {
  const P = spec.params, root = new THREE.Group(), main = P.color || '#f4f4f2', accent = P.color2 || '#d62f3a';
  const L = 1.4, hl = L / 2;
  // the footprint's half-width along the shoe (heel at -x, toe at +x): narrow heel, wide ball, rounded toe
  const width = (x) => { const t = (x + hl) / L; return 0.25 * (0.66 + 0.34 * Math.sin(Math.min(1, t * 1.3) * Math.PI * 0.6)) * Math.pow(Math.max(0, 1 - Math.pow(Math.abs(2 * t - 1), 6)), 0.32); };
  // the upper's height over the sole: low at the toe, rising over the instep to the collar at the heel
  const height = curveOf([[-hl, 0.3], [-hl + 0.12, 0.36], [-0.25, 0.36], [0.0, 0.3], [0.3, 0.2], [hl - 0.08, 0.13], [hl, 0.08]]);
  const soleTop = (x) => 0.1 + 0.06 * Math.max(0, -(x / hl));   // thicker under the heel
  const flat = (geo) => { geo.rotateX(-Math.PI / 2); return geo; };
  const xs = Array.from({ length: 60 }, (_, i) => -hl + (i / 59) * L);
  const print = (k) => smoothOutline([...xs.map((x) => [x, width(x) * k]), ...xs.slice().reverse().map((x) => [x, -width(x) * k])].filter((_, i) => i % 3 === 0), 140);
  const outsole = part(root, 'Outsole'); mesh(flat(extrude(print(1.04), 0.04, 0.012)), mat('rubber', '#2b2d31'), outsole, [0, 0.02, 0]);
  const mid = part(root, 'Midsole');
  mesh(loft(90, 40, (u, v, out) => {
    const x = -hl + u * L, a = v * Math.PI * 2, [z, y] = squircle(a, width(x) * 1.06, 1, 6);
    out.set(x, y > 0 ? soleTop(x) : 0.045, z);
  }), mat('plastic', '#fbfbf8'), mid);
  // the upper: one padded shell over the foot
  const up = part(root, 'Upper');
  const upperAt = (x, a) => { const w = width(x), h = height(x), s = Math.sin(a), c = Math.cos(a), sy = s > 0 ? Math.pow(s, 0.85) : 0; return V(x, soleTop(x) - 0.01 + sy * h, Math.sign(c) * Math.pow(Math.abs(c), 0.8) * w * (1 - 0.18 * sy * sy)); };
  mesh(loft(100, 48, (u, v, out) => out.copy(upperAt(-hl + 0.01 + u * (L - 0.02), v * Math.PI * 2))), mat('fabric', main), up);
  // the opening at the top, with its padded collar and dark lining
  const collar = part(root, 'Collar'), cx = -hl + 0.3, cy = soleTop(cx) + height(cx) - 0.01;
  mesh(new THREE.TorusGeometry(0.16, 0.04, 16, 48), mat('fabric', '#2b2d31'), collar, [cx, cy, 0], [Math.PI / 2 + deg(10), 0, 0], [1.45, 0.95, 1]);
  mesh(new THREE.CircleGeometry(0.16, 40), mat('fabric', '#141518'), collar, [cx, cy + 0.003, 0], [-Math.PI / 2 + deg(10), 0, 0], [1.45, 0.95, 1]);
  const tongue = part(root, 'Tongue');
  mesh(roundedBox(0.32, 0.04, 0.2, 0.02), mat('fabric', main), tongue, [cx + 0.25, cy + 0.03, 0], [0, 0, deg(24)]);
  const toe = part(root, 'Toe Cap');
  mesh(loft(30, 40, (u, v, out) => { const x = hl - 0.25 + u * 0.24, p = upperAt(x, v * Math.PI * 2); p.y = Math.max(p.y, soleTop(x)) + 0.006; p.z *= 1.03; out.copy(p); }), mat('fabric', '#e3e3df'), toe);
  const heel = part(root, 'Heel Counter');
  mesh(loft(24, 40, (u, v, out) => { const x = -hl + 0.005 + u * 0.3, a = v * Math.PI * 2, p = upperAt(x, a); p.y = Math.min(p.y, soleTop(x) + height(x) * 0.6); p.z *= 1.04; p.x -= 0.005; out.copy(p); }), mat('fabric', accent), heel);
  // a stripe sweeping along each side, following the upper's surface
  const stripe = part(root, 'Side Stripe');
  for (const side of [1, -1]) {
    const pts = []; for (let i = 0; i <= 24; i++) { const t = i / 24, x = -hl + 0.15 + t * 0.85, a = side > 0 ? 0.35 + 0.35 * Math.sin(t * Math.PI) : Math.PI - 0.35 - 0.35 * Math.sin(t * Math.PI); const p = upperAt(x, a); p.z *= 1.03; pts.push(p); }
    mesh(taper(pts, 0.012, 0.03, 60, 10), mat('plastic', accent), stripe);
  }
  // laces criss-crossing the instep, through metal eyelets
  const laces = part(root, 'Laces'), lm = mat('fabric', '#fafafa');
  for (let i = 0; i < 6; i++) {
    const x = cx + 0.2 + i * 0.065, y = soleTop(x) + height(x) + 0.008, w = width(x) * 0.42;
    for (const s of [1, -1]) mesh(taper([[x, y, -s * w], [x + 0.032, y + 0.02, 0], [x + 0.065, soleTop(x + 0.065) + height(x + 0.065) + 0.008, s * w]], 0.008, 0.008, 16, 6), lm, laces);
    for (const z of [-w, w]) mesh(new THREE.TorusGeometry(0.01, 0.0035, 8, 16), mat('chrome', '#cfd5db'), laces, [x, y - 0.004, z], [Math.PI / 2, 0, 0]);
  }
  return { group: root };
}

module.exports = { buildingModel, vehicleModel, deviceModel, guitarModel, shoeModel };
