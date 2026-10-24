// The projector's model builders: each turns a checked spec (projector.py) into a Three.js group whose children are
// named parts (userData.part), so the projector can label them, select them and explain them.
//
// A builder returns { group, animate(t, dt) | null, explode | null, cutaway | null, hud(t) | null } where:
//   animate  moves the model (engine strokes, gears, orbiting electrons, the black hole's disk); null when it's still
//   explode  (k 0..1) spreads the parts apart for an exploded view; null when that means nothing for this model
//   cutaway  (on) opens the model to show inside (a flower's pistil and stamens); null when it doesn't apply
//   hud      a line for the stage (the engine's current stroke)
// Sizes are in "projector units": the projector scales every model to fit its platform afterwards.
const kit = require('./kit.js');
const { THREE, mat, deg, part, mesh, tube } = kit;
const living = require('./living.js'), made = require('./made.js'), body = require('./body.js');

// ---------- free composition from primitives (the AI's plan for subjects without a builder) ----------
function partsModel(spec) {
  const root = new THREE.Group();
  const explodes = [];
  for (const p of spec.parts) {
    const g = part(root, p.name);
    const s = p.size;
    let geo;
    switch (p.shape) {
      case 'sphere': geo = new THREE.SphereGeometry(s[0], 40, 28); break;
      case 'box': geo = new THREE.BoxGeometry(s[0], s[1], s[2]); break;
      case 'cylinder': geo = new THREE.CylinderGeometry(s[0], s[0], s[1], 40); break;
      case 'cone': geo = new THREE.ConeGeometry(s[0], s[1], 40); break;
      case 'torus': geo = new THREE.TorusGeometry(s[0], Math.min(s[1], s[0]), 20, 64); break;
      case 'ring': geo = new THREE.RingGeometry(Math.max(0.01, s[0] - s[1]), s[0], 64); break;
      case 'capsule': geo = new THREE.CapsuleGeometry(s[0], s[1], 8, 24); break;
      case 'ico': geo = new THREE.IcosahedronGeometry(s[0], 1); break;
      case 'plane': geo = new THREE.PlaneGeometry(s[0], s[1]); break;
      case 'tube': geo = tube(p.path, s[0]); break;
      case 'ellipsoid': geo = new THREE.SphereGeometry(1, 48, 32); geo.scale(s[0], s[1], s[2]); break;
      case 'roundbox': geo = kit.roundedBox(s[0], s[1], s[2], Math.min(s[0], s[1], s[2]) * 0.2); break;
      case 'lathe': geo = kit.lathe(p.profile, 64); break;
      case 'extrude': geo = kit.extrude(p.outline, Math.max(0.01, s[0]), Math.min(0.03, s[0] * 0.2)); break;
      default: continue;
    }
    const material = mat(p.material, p.color);
    if (['plane', 'ring', 'lathe'].includes(p.shape)) material.side = THREE.DoubleSide;
    const count = p.repeat ? p.repeat.count : 1;
    for (let i = 0; i < count; i++) {
      const holder = new THREE.Group();
      holder.position.set(...p.at);
      if (p.repeat) {
        const a = (i / count) * Math.PI * 2, r = p.repeat.radius;
        const off = p.repeat.axis === 'y' ? [Math.cos(a) * r, 0, Math.sin(a) * r] : p.repeat.axis === 'x' ? [0, Math.cos(a) * r, Math.sin(a) * r] : [Math.cos(a) * r, Math.sin(a) * r, 0];
        holder.position.add(new THREE.Vector3(...off));
        holder.rotation[p.repeat.axis] = -a;
      }
      mesh(geo, material, holder, [0, 0, 0], p.rot.map(deg));
      g.add(holder);
    }
    if (p.explode) explodes.push({ g, home: g.position.clone(), off: new THREE.Vector3(...p.explode) });
  }
  return { group: root, explode: explodes.length ? (k) => explodes.forEach((e) => e.g.position.copy(e.home).addScaledVector(e.off, k)) : null };
}

// ---------- a flower: petals in layers, sepals, stamens, a pistil, a stem and leaves ----------
function flowerModel(spec) {
  const P = spec.params, root = new THREE.Group();
  const petalLen = { round: 0.55, pointed: 0.6, long: 0.85 }[P.petal_shape], petalW = { round: 0.3, pointed: 0.2, long: 0.16 }[P.petal_shape];
  const many = !!P.composite;   // a composite head (sunflower, daisy): a broad disc of florets instead of a small centre
  const centerR = many ? 0.42 : 0.12;
  const petalMat = mat('organic', P.petal_color), green = mat('organic', '#4e8a3a'), dark = mat('organic', '#2f5e26');
  const head = new THREE.Group(); head.position.y = 0.95; head.rotation.x = deg(-28); root.add(head);
  // petals: a cupped ellipsoid each, in rings that open further toward the outside
  const petals = part(root, 'Petal'); head.add(petals);
  const petalGeo = new THREE.SphereGeometry(0.5, 24, 14);
  const front = [];
  for (let layer = 0; layer < P.layers; layer++) {
    const n = Math.max(3, Math.round(P.petals / P.layers)), tilt = deg(70 - layer * (40 / Math.max(1, P.layers - 1 || 1)));
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 + layer * 0.35;
      const holder = new THREE.Group(); holder.rotation.y = a; petals.add(holder);
      // a single flower cups its petals inward; a composite head (sunflower, daisy) spreads its rays out flat
      const hinge = new THREE.Group(); hinge.position.x = centerR * 0.9; hinge.rotation.z = many ? -deg(80 - layer * 12) : Math.PI / 2 - tilt; holder.add(hinge);
      const m = mesh(petalGeo, petalMat, hinge, [0, petalLen * (1 - layer * 0.12) / 2, 0], [0, 0, 0], [petalW * (1 - layer * 0.1), petalLen * (1 - layer * 0.12), 0.04]);
      m.rotation.x = deg(8);
      if (Math.cos(a) > 0.15) front.push(holder);   // the half toward you, hidden in the cutaway
    }
  }
  const sepals = part(root, 'Sepal'); head.add(sepals);
  for (let i = 0; i < 5; i++) {
    const holder = new THREE.Group(); holder.rotation.y = (i / 5) * Math.PI * 2 + 0.3; sepals.add(holder);
    const hinge = new THREE.Group(); hinge.position.set(centerR * 0.6, -0.04, 0); hinge.rotation.z = deg(-60); holder.add(hinge);
    mesh(petalGeo, green, hinge, [0, 0.16, 0], [0, 0, 0], [0.14, 0.34, 0.03]);
  }
  mesh(new THREE.SphereGeometry(centerR * 0.85, 24, 16), green, part(root, 'Receptacle'), [0, -0.05, 0], [0, 0, 0], [1, 0.55, 1]);
  head.add(part(root, 'Receptacle'));
  if (many) {   // the seed disc, florets in a sunflower's spiral (the golden angle)
    const disc = part(root, 'Stamen'); head.add(disc);
    const n = 260, dotGeo = new THREE.SphereGeometry(0.018, 8, 6), dm = mat('organic', P.center_color);
    const inst = new THREE.InstancedMesh(dotGeo, dm, n), m4 = new THREE.Matrix4();
    for (let i = 0; i < n; i++) { const r = centerR * Math.sqrt(i / n), a = i * 2.39996; m4.setPosition(Math.cos(a) * r, 0.04 + 0.03 * (1 - r / centerR), Math.sin(a) * r); inst.setMatrixAt(i, m4); }
    disc.add(inst);
    mesh(new THREE.CylinderGeometry(centerR, centerR * 0.95, 0.06, 40), mat('organic', P.center_color), disc, [0, 0.01, 0]);
  } else {
    // stamens: filaments topped by anthers, round the pistil
    const stamens = part(root, 'Stamen'); head.add(stamens);
    const filaments = part(root, 'Filament'), anthers = part(root, 'Anther'); stamens.add(filaments, anthers);
    for (let i = 0; i < 10; i++) {
      const a = (i / 10) * Math.PI * 2, x = Math.cos(a) * 0.08, z = Math.sin(a) * 0.08, top = [x * 2.4, 0.34, z * 2.4];
      mesh(tube([[x, 0, z], [x * 1.6, 0.18, z * 1.6], top], 0.007, 12), mat('organic', '#e8e0b8'), filaments);
      mesh(new THREE.CapsuleGeometry(0.018, 0.03, 4, 10), mat('organic', P.center_color === '#6b4423' ? '#e8b923' : P.center_color), anthers, top, [deg(70), a, 0]);
    }
    const pistil = part(root, 'Pistil'); head.add(pistil);
    mesh(new THREE.SphereGeometry(0.075, 20, 14), mat('organic', '#8fbf5a'), part(pistil, 'Ovary'), [0, 0.06, 0], [0, 0, 0], [1, 1.25, 1]);
    mesh(new THREE.CylinderGeometry(0.014, 0.02, 0.3, 12), mat('organic', '#b9d47a'), part(pistil, 'Style'), [0, 0.27, 0]);
    mesh(new THREE.SphereGeometry(0.035, 16, 10), mat('organic', '#d9e36a'), part(pistil, 'Stigma'), [0, 0.43, 0], [0, 0, 0], [1.3, 0.6, 1.3]);
  }
  // stem and leaves
  const stem = part(root, 'Stem');
  mesh(tube([[0, 0, 0], [0.05, 0.35, 0.02], [-0.02, 0.7, -0.04], [0, 0.92, 0.1]], 0.035, 40), green, stem);
  const leaves = part(root, 'Leaf');
  for (let i = 0; i < P.leaves; i++) {
    const holder = new THREE.Group(); holder.position.set(0, 0.2 + i * 0.2, 0); holder.rotation.y = i * 2.4; leaves.add(holder);
    const hinge = new THREE.Group(); hinge.rotation.z = deg(-55); holder.add(hinge);
    mesh(petalGeo, dark, hinge, [0, 0.26, 0], [0, 0, deg(6)], [0.2, 0.55, 0.025]);
  }
  return {
    group: root,
    cutaway: many ? null : (on) => { front.forEach((h) => { h.visible = !on; }); },
  };
}

// ---------- trees ----------
function treeModel(spec) {
  const { kind, leaf_color: lc } = spec.params, root = new THREE.Group();
  const barkColor = kind === 'birch' ? '#e8e4dc' : '#5b4330', bark = mat('organic', barkColor), leaf = mat('matte', lc);
  leaf.flatShading = true;
  const trunk = part(root, 'Trunk'), branches = part(root, 'Branches'), crown = part(root, 'Crown'), roots = part(root, 'Roots');
  if (kind === 'palm') {
    mesh(tube([[0, 0, 0], [0.12, 0.8, 0], [0.32, 1.6, 0.05], [0.55, 2.3, 0.1]], 0.07, 40), bark, trunk);
    for (let i = 0; i < 9; i++) {
      const a = (i / 9) * Math.PI * 2;
      mesh(tube([[0.55, 2.3, 0.1], [0.55 + Math.cos(a) * 0.5, 2.55, 0.1 + Math.sin(a) * 0.5], [0.55 + Math.cos(a) * 1.0, 2.15, 0.1 + Math.sin(a) * 1.0]], 0.04, 20), leaf, crown);
    }
  } else {
    const h = kind === 'pine' ? 2.6 : 1.5;
    mesh(new THREE.CylinderGeometry(0.07, 0.13, h, 14), bark, trunk, [0, h / 2, 0]);
    if (kind === 'birch') for (let i = 0; i < 9; i++) mesh(new THREE.BoxGeometry(0.06, 0.012, 0.005), mat('matte', '#2b2b2b'), trunk, [0, 0.2 + i * 0.15, 0.1], [0, i, 0]);
    if (kind === 'pine') {
      for (let i = 0; i < 5; i++) mesh(new THREE.ConeGeometry(0.9 - i * 0.15, 0.7, 12), leaf, crown, [0, 0.9 + i * 0.4, 0]);
    } else {
      for (let i = 0; i < 4; i++) {
        const a = i * 1.7;
        mesh(tube([[0, 1.0 + i * 0.12, 0], [Math.cos(a) * 0.35, 1.35 + i * 0.1, Math.sin(a) * 0.35], [Math.cos(a) * 0.6, 1.55 + i * 0.08, Math.sin(a) * 0.6]], 0.035, 16), bark, branches);
      }
      const r = (i) => { const v = Math.sin(i * 91.7) * 43758.5; return v - Math.floor(v); };
      for (let i = 0; i < 9; i++) mesh(new THREE.IcosahedronGeometry(0.45 + r(i) * 0.25, 1), leaf, crown, [(r(i + 3) - 0.5) * 1.1, 1.7 + r(i + 7) * 0.7, (r(i + 11) - 0.5) * 1.1]);
    }
  }
  for (let i = 0; i < 6; i++) {
    const a = (i / 6) * Math.PI * 2;
    mesh(tube([[0, 0.05, 0], [Math.cos(a) * 0.25, -0.12, Math.sin(a) * 0.25], [Math.cos(a) * 0.55, -0.3, Math.sin(a) * 0.55]], 0.025, 12), bark, roots);
  }
  return { group: root };
}

// ---------- DNA / RNA ----------
function helixModel(spec) {
  const { kind, turns } = spec.params, root = new THREE.Group();
  const perTurn = 10.5, steps = Math.round(turns * perTurn), height = turns * 1.1, R = 0.42;   // B-DNA: about 10.5 base pairs per turn
  const at = (i, strand) => { const a = (i / perTurn) * Math.PI * 2 + strand * deg(150); return [Math.cos(a) * R, (i / steps) * height - height / 2, Math.sin(a) * R]; };
  const backbone = part(root, 'Backbone');
  const strands = kind === 'rna' ? [0] : [0, 1];
  for (const s of strands) mesh(tube(Array.from({ length: steps * 4 + 1 }, (_, k) => at(k / 4, s)), 0.045, steps * 8), mat('plastic', s ? '#7aa2ff' : '#ff9f5a'), backbone);
  const BASES = { Adenine: '#e5484d', Thymine: '#f5c542', Uracil: '#f5c542', Guanine: '#46c26a', Cytosine: '#3b82f6' };
  const second = kind === 'rna' ? 'Uracil' : 'Thymine';
  const pairs = [['Adenine', second], [second, 'Adenine'], ['Guanine', 'Cytosine'], ['Cytosine', 'Guanine']];
  const rng = (i) => { const v = Math.sin(i * 12.9898) * 43758.5453; return v - Math.floor(v); };
  for (let i = 0; i < steps; i++) {
    const [b1, b2] = pairs[Math.floor(rng(i) * 4)];
    const p1 = new THREE.Vector3(...at(i, 0)), p2 = new THREE.Vector3(...at(i, 1));
    const mid = kind === 'rna' ? p1.clone().lerp(new THREE.Vector3(0, p1.y, 0), 0.6) : p1.clone().lerp(p2, 0.5);
    const rung = (from, to, name) => {
      const len = from.distanceTo(to), m = mesh(new THREE.CylinderGeometry(0.03, 0.03, len, 10), mat('plastic', BASES[name]), part(root, name));
      m.position.copy(from).lerp(to, 0.5); m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), to.clone().sub(from).normalize());
    };
    rung(p1, mid, b1);
    if (kind !== 'rna') rung(mid, p2, b2);
  }
  return { group: root, animate: (t, dt) => { root.rotation.y += dt * 0.35; } };
}

// ---------- molecules: atoms in CPK colours, bonds as sticks (double and triple bonds drawn side by side) ----------
const CPK = { H: '#f2f2f2', C: '#3a3a3a', N: '#3050f8', O: '#ff0d0d', F: '#90e050', Cl: '#1ff01f', Br: '#a62929', I: '#940094', S: '#ffff30', P: '#ff8000', Na: '#ab5cf2', K: '#8f40d4', Ca: '#3dff00', Fe: '#e06633', Mg: '#8aff00', Si: '#f0c8a0', B: '#ffb5b5' };
const RADIUS = { H: 0.31, C: 0.76, N: 0.71, O: 0.66, F: 0.57, S: 1.05, P: 1.07, Cl: 1.02 };
function moleculeModel(spec, names) {
  const { atoms, bonds } = spec.params, root = new THREE.Group();
  const pos = atoms.map((a) => new THREE.Vector3(a[1], a[2], a[3]));
  atoms.forEach((a, i) => mesh(new THREE.SphereGeometry((RADIUS[a[0]] || 0.8) * 0.42, 32, 22), mat('plastic', CPK[a[0]] || '#d0d0d0'), part(root, names[a[0]] || a[0]), pos[i].toArray()));
  const bondsPart = part(root, 'Bonds'), stick = mat('plastic', '#c8ced6');
  for (const [i, j, order] of bonds) {
    const a = pos[i], b = pos[j], dir = b.clone().sub(a), len = dir.length();
    const side = new THREE.Vector3(0, 1, 0).cross(dir).normalize();
    if (side.lengthSq() < 0.01) side.set(1, 0, 0);
    for (let k = 0; k < order; k++) {
      const off = side.clone().multiplyScalar((k - (order - 1) / 2) * 0.13);
      const m = mesh(new THREE.CylinderGeometry(0.06, 0.06, len, 12), stick, bondsPart);
      m.position.copy(a).lerp(b, 0.5).add(off); m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
    }
  }
  return { group: root, animate: (t, dt) => { root.rotation.y += dt * 0.25; } };
}

// ---------- an atom, as the Bohr model: a nucleus of protons and neutrons, electrons on shells ----------
function atomModel(spec) {
  const { z, neutrons, shells } = spec.params, root = new THREE.Group();
  const nucleons = Math.min(z + neutrons, 90), protonsN = Math.round((z / (z + neutrons)) * nucleons);
  const pr = part(root, 'Protons'), ne = part(root, 'Neutrons'), nucleus = part(root, 'Nucleus');
  nucleus.add(pr, ne);
  const ball = new THREE.SphereGeometry(0.075, 18, 12), rNuc = 0.075 * Math.cbrt(nucleons) * 1.15;
  const red = mat('plastic', '#ff5a5f'), grey = mat('plastic', '#9aa5b1');
  for (let i = 0; i < nucleons; i++) {   // packed in a ball; exactly protonsN protons, spread evenly among the neutrons
    const y = 1 - (2 * (i + 0.5)) / nucleons, r = Math.sqrt(1 - y * y), a = i * 2.39996, d = rNuc * Math.cbrt((i + 1) / nucleons);
    const proton = Math.floor(((i + 1) * protonsN) / nucleons) > Math.floor((i * protonsN) / nucleons);
    mesh(ball, proton ? red : grey, proton ? pr : ne, [Math.cos(a) * r * d, y * d, Math.sin(a) * r * d]);
  }
  const electrons = [];
  shells.forEach((count, s) => {
    const shell = part(root, `Shell ${s + 1}`), R = 0.55 + s * 0.38;
    shell.rotation.set(deg(70 - s * 25), deg(s * 40), deg(s * 15));
    mesh(new THREE.TorusGeometry(R, 0.006, 8, 120), mat('glow', '#4fd8ff'), shell).castShadow = false;
    for (let e = 0; e < count; e++) {
      const el = mesh(new THREE.SphereGeometry(0.04, 14, 10), mat('glow', '#9fe8ff'), shell);
      electrons.push({ el, R, a: (e / count) * Math.PI * 2, speed: 1.4 / (s + 1) });
    }
  });
  const place = () => electrons.forEach((e) => e.el.position.set(Math.cos(e.a) * e.R, Math.sin(e.a) * e.R, 0));
  place();
  return { group: root, animate: (t, dt) => { electrons.forEach((e) => { e.a += dt * e.speed; }); place(); } };
}

// ---------- gears: real involute-looking teeth, meshing, turning at their true ratios ----------
function gearShape(teeth, module) {
  const r = (module * teeth) / 2, ra = r + module, rf = r - 1.25 * module, shape = new THREE.Shape();
  for (let i = 0; i < teeth; i++) {
    const a = (i / teeth) * Math.PI * 2, w = Math.PI / teeth;
    const pts = [[rf, a - w * 0.55], [ra, a - w * 0.28], [ra, a + w * 0.28], [rf, a + w * 0.55], [rf, a + w * 1.45]];
    pts.forEach(([rad, ang], k) => { const x = Math.cos(ang) * rad, y = Math.sin(ang) * rad; if (i === 0 && k === 0) shape.moveTo(x, y); else shape.lineTo(x, y); });
  }
  const hole = new THREE.Path(); hole.absarc(0, 0, Math.max(module * 1.2, r * 0.18), 0, Math.PI * 2, true); shape.holes.push(hole);
  return shape;
}
function gearsModel(spec) {
  const { teeth } = spec.params, root = new THREE.Group(), module = 0.06;
  const colors = ['#c9a227', '#b8c2cc', '#8a95a3', '#d2915a'];
  let x = 0;
  const gears = teeth.map((n, i) => {
    const r = (module * n) / 2;
    if (i > 0) x += (module * teeth[i - 1]) / 2 + r;
    const g = part(root, `Gear ${i + 1}`);
    const geo = new THREE.ExtrudeGeometry(gearShape(n, module), { depth: 0.18, bevelEnabled: true, bevelSize: 0.01, bevelThickness: 0.01, bevelSegments: 2 });
    geo.center();
    const holder = new THREE.Group(); holder.position.set(x, 0, 0); g.add(holder);
    const m = mesh(geo, mat('metal', colors[i % colors.length]), holder);
    mesh(new THREE.CylinderGeometry(module * 1.1, module * 1.1, 0.5, 16), mat('metal', '#5b636e'), holder, [0, 0, 0], [Math.PI / 2, 0, 0]);
    // every other gear is turned half a tooth, so the teeth fall into each other's gaps
    return { m, n, phase: i % 2 ? Math.PI / n : 0, dir: i % 2 ? -1 : 1 };
  });
  root.children.forEach((c) => c.position.x -= x / 2);
  root.rotation.x = deg(-20);
  let a = 0;
  const pose = () => gears.forEach((g) => { g.m.rotation.z = g.phase + g.dir * a * (teeth[0] / g.n); });
  pose();
  return { group: root, animate: (t, dt) => { a += dt * 0.6; pose(); } };
}

// ---------- a four-stroke engine: crank, rod, piston, valves and spark, in the right order ----------
function engineModel() {
  const root = new THREE.Group(), steel = mat('metal', '#aab3bd'), darkSteel = mat('metal', '#6c7480');
  const cyl = part(root, 'Cylinder'), piston = part(root, 'Piston'), rod = part(root, 'Connecting Rod'), crank = part(root, 'Crankshaft');
  const inV = part(root, 'Intake Valve'), exV = part(root, 'Exhaust Valve'), plug = part(root, 'Spark Plug');
  const r = 0.32, L = 0.95, bore = 0.42, deckY = 1.95;   // crank radius, rod length, bore radius, top of the cylinder
  mesh(new THREE.CylinderGeometry(bore + 0.05, bore + 0.05, 1.25, 40, 1, true), mat('glass', '#9fd8ff'), cyl, [0, deckY - 0.62, 0]).castShadow = false;
  mesh(new THREE.BoxGeometry(1.15, 0.22, 1.0), darkSteel, cyl, [0, deckY + 0.11, 0]);   // the head
  const pistonMesh = mesh(new THREE.CylinderGeometry(bore, bore, 0.32, 40), steel, piston);
  for (let i = 0; i < 3; i++) mesh(new THREE.TorusGeometry(bore + 0.002, 0.008, 6, 40), darkSteel, pistonMesh, [0, 0.1 - i * 0.05, 0], [Math.PI / 2, 0, 0]);
  const rodMesh = mesh(new THREE.BoxGeometry(0.09, L, 0.07), steel, rod);
  const crankArm = new THREE.Group(); crank.add(crankArm);
  mesh(new THREE.CylinderGeometry(0.07, 0.07, 1.1, 20), darkSteel, crank, [0, 0, 0], [Math.PI / 2, 0, 0]);
  mesh(new THREE.BoxGeometry(0.16, r + 0.1, 0.08), darkSteel, crankArm, [0, r / 2, 0.12]);
  mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.08, 32, 1, false, Math.PI * 0.6, Math.PI * 0.8), darkSteel, crankArm, [0, 0, 0.12], [Math.PI / 2, 0, 0]);   // counterweight
  const valve = (group, x) => { const v = new THREE.Group(); group.add(v); v.position.set(x, deckY, 0); mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.5, 10), steel, v, [0, 0.25, 0]); mesh(new THREE.CylinderGeometry(0.1, 0.07, 0.03, 20), steel, v, [0, 0, 0]); return v; };
  const intake = valve(inV, -0.18), exhaust = valve(exV, 0.18);
  mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.35, 12), mat('matte', '#f2f2f2'), plug, [0, deckY + 0.3, 0]);
  const spark = mesh(new THREE.SphereGeometry(0.06, 12, 10), mat('glow', '#9fe8ff'), plug, [0, deckY + 0.02, 0]);
  spark.castShadow = false;
  const STROKES = ['Intake', 'Compression', 'Power', 'Exhaust'];
  let deg720 = 0, label = STROKES[0];
  const pose = () => {
    const th = (deg720 * Math.PI) / 180;
    const cx = r * Math.sin(th), cy = r * Math.cos(th);   // the crank pin
    const py = cy + Math.sqrt(L * L - cx * cx);            // the piston pin, straight above the crank
    crankArm.rotation.z = -th;
    pistonMesh.position.set(0, py + 0.16, 0);
    rodMesh.position.set(cx / 2, (cy + py) / 2, 0); rodMesh.rotation.z = Math.atan2(cx, py - cy);
    const stroke = Math.floor((deg720 % 720) / 180);
    label = STROKES[stroke];
    const lift = (on, x) => (on ? Math.sin(((deg720 % 180) / 180) * Math.PI) * 0.12 : 0);
    intake.position.y = deckY - lift(stroke === 0);
    exhaust.position.y = deckY - lift(stroke === 3);
    spark.visible = stroke === 2 && deg720 % 180 < 35;
  };
  pose();
  return { group: root, animate: (t, dt) => { deg720 = (deg720 + dt * 160) % 720; pose(); }, hud: () => `${label} stroke` };
}

// ---------- a desktop computer, opened up ----------
function computerModel() {
  const root = new THREE.Group(), pcb = mat('plastic', '#1f5e3a'), black = mat('plastic', '#1b1f26'), alu = mat('metal', '#aeb6c0'), gold = mat('metal', '#c9a227');
  const explodes = [];
  const add = (name, build, off) => { const g = part(root, name); build(g); explodes.push({ g, home: g.position.clone(), off: new THREE.Vector3(...off) }); return g; };
  add('Case', (g) => { mesh(new THREE.BoxGeometry(2.1, 2.2, 0.06), black, g, [0, 1.1, -0.55]); mesh(new THREE.BoxGeometry(2.1, 0.06, 1.2), black, g, [0, 0, 0]); mesh(new THREE.BoxGeometry(2.1, 2.2, 0.03), mat('glass', '#9fd8ff'), g, [0, 1.1, 0.6]).castShadow = false; }, [0, 0, -0.6]);
  add('Motherboard', (g) => { mesh(new THREE.BoxGeometry(1.7, 1.8, 0.04), pcb, g, [0, 1.15, -0.48]); for (let i = 0; i < 6; i++) mesh(new THREE.BoxGeometry(1.2, 0.01, 0.005), gold, g, [0.1, 0.5 + i * 0.22, -0.455]); }, [0, 0, -0.3]);
  add('CPU', (g) => { mesh(new THREE.BoxGeometry(0.26, 0.26, 0.04), alu, g, [-0.2, 1.55, -0.44]); }, [0, 0, 0.35]);
  add('CPU Cooler', (g) => {
    for (let i = 0; i < 14; i++) mesh(new THREE.BoxGeometry(0.42, 0.02, 0.32), alu, g, [-0.2, 1.4 + i * 0.022, -0.2]);
    mesh(new THREE.TorusGeometry(0.17, 0.02, 8, 32), black, g, [-0.2, 1.55, -0.02]);
  }, [0, 0.1, 0.9]);
  add('Memory (RAM)', (g) => { for (let i = 0; i < 2; i++) mesh(new THREE.BoxGeometry(0.035, 0.6, 0.16), mat('plastic', '#2b3a55'), g, [0.25 + i * 0.09, 1.55, -0.36]); }, [0.55, 0.15, 0.6]);
  add('Graphics Card (GPU)', (g) => { mesh(new THREE.BoxGeometry(1.35, 0.1, 0.5), black, g, [0.0, 0.85, -0.18]); for (const x of [-0.3, 0.3]) mesh(new THREE.TorusGeometry(0.16, 0.02, 8, 32), alu, g, [x, 0.79, -0.18], [Math.PI / 2, 0, 0]); }, [0, -0.15, 0.9]);
  add('Storage (SSD)', (g) => { mesh(new THREE.BoxGeometry(0.4, 0.012, 0.1), mat('plastic', '#3a3f4a'), g, [0.45, 1.12, -0.44], [Math.PI / 2, 0, 0]); }, [0.75, -0.1, 0.5]);
  add('Power Supply', (g) => { mesh(new THREE.BoxGeometry(0.75, 0.42, 0.85), mat('metal', '#3c424c'), g, [-0.55, 0.27, -0.1]); }, [-0.4, -0.2, 0.7]);
  return { group: root, explode: (k) => explodes.forEach((e) => e.g.position.copy(e.home).addScaledVector(e.off, k)), explodedFirst: true };
}

// ---------- a black hole (illustration): horizon, photon ring, a hot accretion disk, jets ----------
function blackholeModel(spec) {
  const root = new THREE.Group();
  mesh(new THREE.SphereGeometry(0.55, 48, 32), new THREE.MeshBasicMaterial({ color: 0x000000 }), part(root, 'Event Horizon'));
  mesh(new THREE.TorusGeometry(0.62, 0.012, 10, 140), new THREE.MeshBasicMaterial({ color: 0xfff1d6 }), part(root, 'Photon Sphere'), [0, 0, 0], [0, 0, 0]);
  const diskU = { uTime: { value: 0 } };
  const diskMat = new THREE.ShaderMaterial({
    uniforms: diskU, transparent: true, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: 'varying vec2 vP; void main(){ vP = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
    fragmentShader: `uniform float uTime; varying vec2 vP;
      void main(){ float r = length(vP); float a = atan(vP.y, vP.x);
        float t = clamp((r - 0.75) / 1.25, 0.0, 1.0);
        float swirl = 0.6 + 0.4 * sin(a * 6.0 - uTime * 2.2 + r * 9.0) * sin(a * 3.0 + uTime * 1.3 - r * 5.0);
        float beam = 0.6 + 0.4 * cos(a);   /* the side coming toward you looks brighter */
        vec3 hot = mix(vec3(1.0, 0.95, 0.85), vec3(1.0, 0.45, 0.12), t);
        float alpha = (1.0 - t) * smoothstep(0.0, 0.08, t + 0.02) * swirl * beam;
        gl_FragColor = vec4(hot * (1.4 - t), alpha); }`,
  });
  const disk = mesh(new THREE.RingGeometry(0.75, 2.0, 160, 4), diskMat, part(root, 'Accretion Disk'), [0, 0, 0], [deg(-78), 0, 0]);
  disk.castShadow = false;
  // the far side of the disk, bent over the top by gravity (lensing), shown as a faint arc
  const arc = mesh(new THREE.TorusGeometry(0.85, 0.05, 8, 80, Math.PI), new THREE.MeshBasicMaterial({ color: 0xffb46b, transparent: true, opacity: 0.35, blending: THREE.AdditiveBlending, depthWrite: false }), part(root, 'Accretion Disk'));
  arc.castShadow = false;
  if (spec.params.jets) {
    const jets = part(root, 'Jets');
    for (const s of [1, -1]) mesh(new THREE.ConeGeometry(0.12, 1.6, 24, 1, true), new THREE.MeshBasicMaterial({ color: 0x9fd8ff, transparent: true, opacity: 0.35, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }), jets, [0, s * 1.0, 0], [s > 0 ? Math.PI : 0, 0, 0]).castShadow = false;
  }
  root.position.y = 1.2;
  return { group: root, animate: (t) => { diskU.uTime.value = t; }, staysLit: true };
}

// ---------- a math surface: z = f(x, y [, t]), coloured by height ----------
function compile(expr) {
  // a tiny, safe expression evaluator (no eval): numbers, x y t, + - * / ^, unary minus, and the listed functions
  const FN = { sin: Math.sin, cos: Math.cos, tan: Math.tan, exp: Math.exp, log: Math.log, sqrt: Math.sqrt, abs: Math.abs };
  const tokens = expr.match(/\d*\.?\d+(?:e[+-]?\d+)?|[a-z]+|[-+*/^(),]/g) || [];
  let i = 0;
  const peek = () => tokens[i], next = () => tokens[i++];
  const primary = () => {
    const tk = next();
    if (tk === '(') { const v = sum(); next(); return v; }
    if (tk === '-') { const v = power(); return (s) => -v(s); }
    if (/^\d|^\./.test(tk)) { const n = parseFloat(tk); return () => n; }
    if (tk === 'pi') return () => Math.PI;
    if (tk === 'e') return () => Math.E;
    if (tk === 'x' || tk === 'y' || tk === 't') return (s) => s[tk];
    if (FN[tk]) {   // sin(x) or sin x
      if (peek() === '(') { next(); const a = sum(); next(); return (s) => FN[tk](a(s)); }
      const a = power(); return (s) => FN[tk](a(s));
    }
    throw new Error('Unexpected ' + tk);
  };
  const power = () => { const b = primary(); if (peek() === '^') { next(); const e = power(); return (s) => Math.pow(b(s), e(s)); } return b; };
  const product = () => {
    let a = power();
    while (peek() === '*' || peek() === '/' || (peek() && /^[a-z(]|^\d/.test(peek()))) {   // "2x", "x y": implied multiplication
      const op = /^[*\/]$/.test(peek()) ? next() : '*', b = power(), l = a;
      a = op === '*' ? (s) => l(s) * b(s) : (s) => l(s) / b(s);
    }
    return a;
  };
  const sum = () => { let a = product(); while (peek() === '+' || peek() === '-') { const op = next(), b = product(), l = a; a = op === '+' ? (s) => l(s) + b(s) : (s) => l(s) - b(s); } return a; };
  const f = sum();
  return f;
}
function surfaceModel(spec) {
  const { expr, range } = spec.params, root = new THREE.Group(), N = 90;
  const f = compile(expr), timed = /\bt\b/.test(expr);
  const geo = new THREE.PlaneGeometry(2.6, 2.6, N, N);
  geo.rotateX(-Math.PI / 2);
  const colors = new Float32Array(geo.attributes.position.count * 3);
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  const surf = mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.45, metalness: 0.1, side: THREE.DoubleSide }), part(root, 'Surface'));
  const wire = new THREE.LineSegments(new THREE.WireframeGeometry(geo), new THREE.LineBasicMaterial({ color: 0x9fe8ff, transparent: true, opacity: 0.12 }));
  surf.add(wire);
  const lo = new THREE.Color('#3b82f6'), mid = new THREE.Color('#4fd8ff'), hi = new THREE.Color('#ffd166'), c = new THREE.Color();
  const shape = (t) => {
    const p = geo.attributes.position, zs = [];
    for (let k = 0; k < p.count; k++) {
      const x = (p.getX(k) / 1.3) * range, y = (-p.getZ(k) / 1.3) * range;
      let z = f({ x, y, t });
      if (!Number.isFinite(z)) z = 0;
      zs.push(Math.max(-range * 2, Math.min(range * 2, z)));
    }
    const zmax = Math.max(1e-6, ...zs.map(Math.abs)), scale = 0.9 / zmax;   // the tallest point stands 0.9 above the middle
    zs.forEach((z, k) => {
      p.setY(k, z * scale);
      const h = (z / zmax + 1) / 2;
      c.copy(h < 0.5 ? lo : mid).lerp(h < 0.5 ? mid : hi, h < 0.5 ? h * 2 : (h - 0.5) * 2);
      colors.set([c.r, c.g, c.b], k * 3);
    });
    p.needsUpdate = true; geo.attributes.color.needsUpdate = true; geo.computeVertexNormals();
    wire.geometry.dispose(); wire.geometry = new THREE.WireframeGeometry(geo);
  };
  shape(0);
  root.position.y = 1.1;
  return { group: root, animate: timed ? (t) => shape(t) : null };
}

// two subjects side by side on the platform, each fitted to its half at the same height; their parts are named after
// them ("Rose: Petal") so picking and labels work as for one model
function compareModel(spec, elementNames) {
  const root = new THREE.Group(), built = spec.models.map((m) => module.exports.build(m, elementNames));
  built.forEach((b, i) => {
    b.group.traverse((o) => { if (o.userData.part) o.userData.part = `${spec.models[i].title}: ${o.userData.part}`; });
    const holder = new THREE.Group(); holder.add(b.group); root.add(holder);
    const size = new THREE.Box3().setFromObject(b.group, true).getSize(new THREE.Vector3());
    b.group.scale.multiplyScalar(Math.min(2.6 / Math.max(size.y, 0.01), 1.5 / Math.max(size.x, size.z, 0.01)));
    const box = new THREE.Box3().setFromObject(b.group, true), c = box.getCenter(new THREE.Vector3());
    b.group.position.x -= c.x; b.group.position.z -= c.z; b.group.position.y -= box.min.y;
    holder.position.x = i ? 1.1 : -1.1;
  });
  const each = (key) => (built.some((b) => b[key]) ? (...a) => built.forEach((b) => b[key]?.(...a)) : null);
  const hud = built.find((b) => b.hud);
  return { group: root, animate: each('animate'), explode: each('explode'), cutaway: each('cutaway'), hud: hud ? (t) => hud.hud(t) : null,
    explodedFirst: built.every((b) => b.explodedFirst) };
}

module.exports = {
  THREE,
  build(spec, elementNames = {}) {
    switch (spec.generator) {
      case 'parts': return partsModel(spec);
      case 'flower': return flowerModel(spec);
      case 'tree': return treeModel(spec);
      case 'helix': return helixModel(spec);
      case 'molecule': return moleculeModel(spec, elementNames);
      case 'atom': return atomModel(spec);
      case 'gears': return gearsModel(spec);
      case 'engine': return engineModel(spec);
      case 'computer': return computerModel(spec);
      case 'blackhole': return blackholeModel(spec);
      case 'surface': return surfaceModel(spec);
      case 'animal': return living.animalModel(spec);
      case 'humanoid': return living.humanoidModel(spec);
      case 'building': return made.buildingModel(spec);
      case 'vehicle': return made.vehicleModel(spec);
      case 'device': return made.deviceModel(spec);
      case 'guitar': return made.guitarModel(spec);
      case 'shoe': return made.shoeModel(spec);
      case 'heart': return body.heartModel(spec);
      case 'compare': return compareModel(spec, elementNames);
      default: throw new Error(`No builder for ${spec.generator}`);
    }
  },
  compileExpression: compile,
};
