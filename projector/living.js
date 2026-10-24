// Living things for the projector: four-legged animals and human figures (people, superheroes, robots, astronauts,
// knights). Each is one rig with real proportions, shaped and coloured by a kind or a preset, so a dog, a horse and an
// elephant, or Iron Man and Spider-Man, are recognisably themselves. Animals face +x, figures face +z.
const { THREE, mat, texMat, deg, V, part, mesh, taper, roundedBox, lathe, extrude, ellipse, limb, blob, canvasTex, rng, loft } = require('./kit.js');

// ---------- animals ----------
const ANIMALS = {
  dog: { len: 1.0, body: 0.27, leg: 0.5, neck: 0.3, neckUp: 52, head: 0.17, snout: 0.17, snoutR: 0.075, snoutDown: 8, ears: 'floppy', tail: 'up', feet: 'paw', color: '#b5783e', color2: '#f2e2c6', belly: true },
  cat: { len: 0.8, body: 0.2, leg: 0.38, neck: 0.15, neckUp: 50, head: 0.15, snout: 0.045, snoutR: 0.06, snoutDown: 5, ears: 'pointy', tail: 'long', feet: 'paw', color: '#686d75', color2: '#ececec', belly: true, whiskers: true },
  horse: { len: 1.3, body: 0.33, leg: 0.95, neck: 0.6, neckUp: 50, head: 0.17, snout: 0.36, snoutR: 0.11, snoutDown: 48, ears: 'small', tail: 'hair', feet: 'hoof', mane: 'crest', color: '#7a4a2a', color2: '#24160d' },
  zebra: { len: 1.25, body: 0.32, leg: 0.88, neck: 0.55, neckUp: 50, head: 0.16, snout: 0.34, snoutR: 0.1, snoutDown: 48, ears: 'small', tail: 'tuft', feet: 'hoof', mane: 'crest', pattern: 'stripes', color: '#f3f3f0', color2: '#151515' },
  cow: { len: 1.35, body: 0.4, leg: 0.6, neck: 0.28, neckUp: 25, head: 0.17, snout: 0.25, snoutR: 0.11, snoutDown: 40, ears: 'side', horns: 'short', tail: 'tuft', feet: 'hoof', pattern: 'spots', color: '#f4f1ea', color2: '#1d1d1d', udder: true },
  lion: { len: 1.15, body: 0.3, leg: 0.62, neck: 0.3, neckUp: 40, head: 0.2, snout: 0.15, snoutR: 0.1, snoutDown: 12, ears: 'round', tail: 'tuft', feet: 'paw', mane: 'lion', color: '#c9974a', color2: '#6e3f17' },
  tiger: { len: 1.2, body: 0.3, leg: 0.58, neck: 0.28, neckUp: 38, head: 0.19, snout: 0.14, snoutR: 0.1, snoutDown: 12, ears: 'round', tail: 'long', feet: 'paw', pattern: 'stripes', color: '#de7f26', color2: '#17110c', belly: true, bellyColor: '#f6eee2', whiskers: true },
  wolf: { len: 1.0, body: 0.26, leg: 0.6, neck: 0.3, neckUp: 45, head: 0.17, snout: 0.21, snoutR: 0.07, snoutDown: 10, ears: 'pointy', tail: 'bushy', feet: 'paw', color: '#74767a', color2: '#e8e4dc', belly: true },
  fox: { len: 0.82, body: 0.19, leg: 0.36, neck: 0.2, neckUp: 45, head: 0.14, snout: 0.17, snoutR: 0.05, snoutDown: 8, ears: 'big', tail: 'bushy', feet: 'paw', color: '#d4692a', color2: '#f7efe4', belly: true, tailTip: '#f7efe4', socks: '#2a1a12' },
  bear: { len: 1.2, body: 0.42, leg: 0.48, neck: 0.2, neckUp: 15, head: 0.22, snout: 0.14, snoutR: 0.1, snoutDown: 10, ears: 'round', tail: 'stub', feet: 'paw', color: '#5a3a22', color2: '#3a2414' },
  panda: { len: 1.1, body: 0.42, leg: 0.42, neck: 0.18, neckUp: 15, head: 0.23, snout: 0.1, snoutR: 0.1, snoutDown: 8, ears: 'round', tail: 'stub', feet: 'paw', pattern: 'panda', color: '#f2f1ec', color2: '#141414' },
  elephant: { len: 1.5, body: 0.55, leg: 0.82, neck: 0.12, neckUp: 12, head: 0.33, snout: 0, snoutR: 0.1, snoutDown: 0, ears: 'elephant', trunk: true, tusks: true, tail: 'tuft', feet: 'pad', color: '#8b8d90', color2: '#6f7174', skin: true },
  rabbit: { len: 0.55, body: 0.2, leg: 0.17, neck: 0.08, neckUp: 60, head: 0.13, snout: 0.05, snoutR: 0.055, snoutDown: 10, ears: 'long', tail: 'puff', feet: 'paw', color: '#cfc2b0', color2: '#f7f3ec', whiskers: true },
  deer: { len: 1.0, body: 0.26, leg: 0.8, neck: 0.42, neckUp: 60, head: 0.13, snout: 0.2, snoutR: 0.06, snoutDown: 40, ears: 'side', antlers: true, tail: 'stub', feet: 'hoof', color: '#9a6a3e', color2: '#efe4d2', belly: true },
  pig: { len: 0.95, body: 0.34, leg: 0.3, neck: 0.1, neckUp: 10, head: 0.2, snout: 0.12, snoutR: 0.09, snoutDown: 4, ears: 'floppy', tail: 'curl', feet: 'hoof', color: '#f0b2a8', color2: '#e48f86', skin: true, flatNose: true },
  sheep: { len: 0.95, body: 0.34, leg: 0.45, neck: 0.16, neckUp: 35, head: 0.15, snout: 0.14, snoutR: 0.07, snoutDown: 35, ears: 'side', tail: 'stub', feet: 'hoof', wool: true, color: '#f1ece0', color2: '#2b2622' },
  giraffe: { len: 1.1, body: 0.32, leg: 1.2, neck: 1.25, neckUp: 72, head: 0.14, snout: 0.22, snoutR: 0.07, snoutDown: 50, ears: 'side', horns: 'ossicones', tail: 'tuft', feet: 'hoof', mane: 'crest', pattern: 'patches', color: '#e8b860', color2: '#7a4a1e' },
  mouse: { len: 0.4, body: 0.13, leg: 0.1, neck: 0.05, neckUp: 20, head: 0.1, snout: 0.1, snoutR: 0.045, snoutDown: 10, ears: 'mouse', tail: 'thin', feet: 'paw', color: '#9a9590', color2: '#e9dfd6', belly: true, whiskers: true },
};

function furTexture(kind, c1, c2, seed, belly = null) {
  const r = rng(seed);
  return canvasTex(1024, 512, (g, w, h) => {
    g.fillStyle = c1; g.fillRect(0, 0, w, h);
    // a fine grain so the coat doesn't look like plastic
    for (let i = 0; i < 2600; i++) { g.fillStyle = r() < 0.5 ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.05)'; g.fillRect(r() * w, r() * h, 1 + r() * 2, 4 + r() * 8); }
    g.fillStyle = c2;
    if (kind === 'stripes') {
      for (let i = 0; i < 14; i++) {   // bands round the body, thickest on the back (a quarter of the way round), thinning to nothing on the belly
        const y = ((i + 0.5) / 14) * h + (r() - 0.5) * 14, wid = 3 + r() * 5;
        g.beginPath();
        for (let x = 0; x <= w; x += 8) { const back = Math.max(0, Math.cos(((x / w) - 0.25) * Math.PI * 2) * 0.5 + 0.5); g.lineTo(x, y + Math.sin(x / 50 + i) * 6 - wid * back); }
        for (let x = w; x >= 0; x -= 8) { const back = Math.max(0, Math.cos(((x / w) - 0.25) * Math.PI * 2) * 0.5 + 0.5); g.lineTo(x, y + Math.sin(x / 50 + i) * 6 + wid * back); }
        g.closePath(); g.fill();
      }
    } else if (kind === 'panda') {
      g.fillRect(0, h * 0.64, w, h * 0.36);   // the black band over the shoulders, at the chest end
    } else if (kind === 'spots') {
      for (let i = 0; i < 16; i++) { g.beginPath(); const x = r() * w, y = h * 0.15 + r() * h * 0.7; for (let a = 0; a < 6.3; a += 0.4) g.lineTo(x + Math.cos(a) * (40 + r() * 40), y + Math.sin(a) * (30 + r() * 30)); g.fill(); }
    } else if (kind === 'patches') {
      // a giraffe's net: dark patches separated by pale lines
      const cell = 64;
      for (let y = 0; y < h + cell; y += cell) for (let x = 0; x < w + cell; x += cell) {
        const cx = x + (r() - 0.5) * 20 + ((y / cell) % 2) * 32, cy = y + (r() - 0.5) * 20;
        g.beginPath(); for (let a = 0; a < 6.3; a += 0.9) g.lineTo(cx + Math.cos(a + r() * 0.4) * (24 + r() * 6), cy + Math.sin(a) * (24 + r() * 6)); g.fill();
      }
    }
    if (belly) {   // a paler belly, soft-edged, three quarters of the way round
      const grd = g.createLinearGradient(w * 0.55, 0, w * 0.95, 0);
      grd.addColorStop(0, 'rgba(0,0,0,0)'); grd.addColorStop(0.3, belly); grd.addColorStop(0.7, belly); grd.addColorStop(1, 'rgba(0,0,0,0)');
      g.fillStyle = grd; g.fillRect(w * 0.55, 0, w * 0.4, h);
    }
  });
}

function animalModel(spec) {
  const P = spec.params, K = { ...ANIMALS[P.kind] || ANIMALS.dog }, root = new THREE.Group();
  const c1 = P.color || K.color, c2 = P.color2 || K.color2;
  const coatKind = K.skin ? 'skin' : 'fur';
  const coat = K.pattern && K.pattern !== 'panda' && K.pattern !== 'stripes' || P.kind === 'zebra' ? texMat(furTexture(K.pattern, c1, c2, 11), { kind: coatKind }) : mat(coatKind, c1);
  const torsoMat = K.pattern || K.belly ? texMat(furTexture(K.pattern || 'plain', c1, c2, 11, K.belly ? K.bellyColor || c2 : null), { kind: coatKind }) : coat;
  const second = mat(coatKind, c2), dark = mat('gloss', '#0b0b0d'), hoofMat = mat('plastic', '#2a221c');
  const { len, body, leg, head } = K;
  const bodyY = leg + body * 0.78;
  // the body: hips, belly and chest, overlapping so the outline is an animal's, not an egg
  // the torso: one smooth skin from rump to chest, deeper at the chest and tucked in at the waist
  const bodyG = part(root, 'Body'), tuck = K.feet === 'pad' || K.wool ? 0.05 : 0.2;
  mesh(loft(64, 48, (u, v, out) => {
    const x = -len * 0.54 + u * len * 1.08, env = Math.pow(Math.sin(Math.PI * u), 0.4), a = v * Math.PI * 2, up = Math.sin(a) > 0;
    const ry = body * env * (0.9 + 0.18 * u) * (up ? 1 : 1 - tuck * Math.exp(-Math.pow((u - 0.38) / 0.17, 2)));
    out.set(x, bodyY + body * 0.06 * u + Math.sin(a) * ry, Math.cos(a) * body * 0.86 * env * (0.92 + 0.12 * u));
  }), torsoMat, bodyG);
  if (K.udder) blob(bodyG, [-len * 0.18, bodyY - body * 0.85, 0], body * 0.28, body * 0.2, body * 0.26, mat('skin', '#f0b9b0'));
  if (K.wool) {   // a fleece of little curls over the body
    const n = 420, wg = new THREE.SphereGeometry(body * 0.16, 10, 8), inst = new THREE.InstancedMesh(wg, mat('fur', c1), n), m4 = new THREE.Matrix4(), r = rng(5);
    for (let i = 0; i < n; i++) {
      const y = 1 - 2 * (i + 0.5) / n, rr = Math.sqrt(1 - y * y), a = i * 2.39996;
      if (y < -0.55) { m4.makeScale(0, 0, 0); inst.setMatrixAt(i, m4); continue; }
      m4.makeScale(1 + r() * 0.5, 1 + r() * 0.5, 1 + r() * 0.5).setPosition(Math.cos(a) * rr * len * 0.5, bodyY + y * body * 1.02, Math.sin(a) * rr * body * 0.95);
      inst.setMatrixAt(i, m4);
    }
    inst.castShadow = true; part(root, 'Wool').add(inst);
  }
  // the neck and head
  const up = deg(K.neckUp), n0 = V(len * 0.36, bodyY + body * 0.3, 0);
  const H = n0.clone().add(V(Math.cos(up) * K.neck, Math.sin(up) * K.neck, 0));
  const neckG = part(root, 'Neck');
  if (K.neck > 0.06) limb(neckG, n0, H, body * (K.neck > 0.4 ? 0.62 : 0.55), head * 0.7, K.pattern === 'panda' ? second : coat).scale.set(K.neck > 0.4 ? 1.35 : 1.1, 1, 0.8);
  const headG = new THREE.Group(); headG.position.copy(H); root.add(headG);
  const headPart = part(root, 'Head'); headG.add(headPart);
  blob(headPart, [head * 0.1, 0, 0], head * 1.12, head, head * 0.92, coat);
  const down = deg(-K.snoutDown), dir = V(Math.cos(down), Math.sin(down), 0);
  const muzzle = part(root, 'Muzzle'); headG.add(muzzle);
  const s0 = dir.clone().multiplyScalar(head * 0.55).add(V(head * 0.1, -head * 0.15, 0)), s1 = s0.clone().addScaledVector(dir, K.snout);
  if (K.snout > 0.02) limb(muzzle, s0, s1, K.snoutR * 1.3, K.snoutR, coat);
  const nose = part(root, 'Nose'); headG.add(nose);
  const tip = s1.clone().addScaledVector(dir, K.snoutR * 0.7);
  if (K.flatNose) mesh(new THREE.CylinderGeometry(K.snoutR * 0.95, K.snoutR, K.snoutR * 0.5, 32), mat('skin', c2), nose, tip.toArray(), [0, 0, Math.PI / 2 + down]);
  else if (!K.trunk) blob(nose, tip.toArray(), K.snoutR * 0.45, K.snoutR * 0.36, K.snoutR * 0.55, dark);
  // eyes: glossy, with a catch-light, so the face reads at a glance
  const eyes = part(root, 'Eyes'); headG.add(eyes);
  for (const z of [-1, 1]) {
    const at = V(head * 0.62, head * 0.32, z * head * 0.55);
    if (K.pattern === 'panda') blob(eyes, at.clone().add(V(-0.01, -0.01, z * 0.005)).toArray(), head * 0.2, head * 0.26, head * 0.12, second);
    blob(eyes, at.toArray(), head * 0.13, head * 0.14, head * 0.1, dark);
    blob(eyes, at.clone().add(V(head * 0.08, head * 0.05, z * head * 0.04)).toArray(), head * 0.035, head * 0.035, head * 0.03, mat('glow', '#ffffff'));
  }
  if (K.whiskers) for (const z of [-1, 1]) for (let i = 0; i < 3; i++) {
    const from = tip.clone().add(V(-K.snoutR * 0.6, -K.snoutR * 0.2, z * K.snoutR * 0.6));
    mesh(taper([from, from.clone().add(V(0.02, (i - 1) * 0.04, z * head * 0.9))], 0.004, 0.001, 8, 5), mat('plastic', '#f4f4f4'), muzzle);
  }
  // ears
  const ears = part(root, 'Ears'); headG.add(ears);
  const earMat = K.pattern === 'panda' ? second : coat;
  for (const z of [-1, 1]) {
    const top = V(-head * 0.15, head * 0.78, z * head * 0.5);
    switch (K.ears) {
      case 'pointy': case 'big': case 'small': {
        const s = K.ears === 'big' ? 1.45 : K.ears === 'small' ? 0.7 : 1;
        mesh(new THREE.ConeGeometry(head * 0.3 * s, head * 0.62 * s, 4, 1), earMat, ears, top.toArray(), [z * deg(-14), deg(45), 0], [1, 1, 0.45]);
        break;
      }
      case 'floppy': blob(ears, [-head * 0.08, head * 0.12, z * head * 1.0], head * 0.34, head * 0.66, head * 0.1, mat(coatKind, P.kind === 'dog' && !P.color ? '#8a5428' : c1)).rotation.set(z * deg(18), 0, deg(-10)); break;
      case 'round': blob(ears, [-head * 0.2, head * 0.82, z * head * 0.62], head * 0.12, head * 0.3, head * 0.3, earMat); break;
      case 'mouse': blob(ears, [-head * 0.2, head * 0.9, z * head * 0.6], head * 0.08, head * 0.55, head * 0.55, mat('skin', '#e7b4b0')); break;
      case 'side': blob(ears, [-head * 0.25, head * 0.45, z * head * 0.98], head * 0.16, head * 0.12, head * 0.4, earMat).rotation.set(z * deg(20), 0, 0); break;
      case 'long': blob(ears, [-head * 0.25, head * 1.45, z * head * 0.32], head * 0.24, head * 0.95, head * 0.09, earMat).rotation.set(z * deg(-10), 0, deg(-12)); break;
      case 'elephant': blob(ears, [-head * 0.45, head * 0.05, z * head * 0.85], head * 0.62, head * 0.95, head * 0.06, mat('skin', c2)).rotation.set(z * deg(25), deg(z * 18), 0); break;
      default: break;
    }
  }
  if (K.mane === 'lion') {   // a ruff of thick fur round the face
    const mane = part(root, 'Mane'); headG.add(mane);
    const mm = mat('fur', c2), r = rng(9);
    for (let i = 0; i < 60; i++) {
      const a = (i / 60) * Math.PI * 2, rr = head * (1.12 + r() * 0.3);
      blob(mane, [-head * 0.35 - r() * head * 0.4, Math.cos(a) * rr - head * 0.05, Math.sin(a) * rr], head * 0.3, head * 0.34, head * 0.34, mm, 16);
    }
  } else if (K.mane === 'crest') {
    const mane = part(root, 'Mane'), mm = mat('fur', c2);
    for (let i = 0; i <= 12; i++) { const p = n0.clone().lerp(H, i / 12).add(V(-0.04, body * 0.42 * (1 - i / 14) + head * 0.25 * (i / 12), 0)); blob(mane, p.toArray(), 0.05, 0.06, 0.025, mm, 12); }
  }
  if (K.horns === 'short') {
    const horns = part(root, 'Horns'); headG.add(horns);
    for (const z of [-1, 1]) mesh(taper([[-head * 0.2, head * 0.7, z * head * 0.4], [-head * 0.2, head * 0.95, z * head * 0.85], [-head * 0.05, head * 1.25, z * head * 1.05]], head * 0.11, head * 0.02), mat('plastic', '#e9dfc8'), horns);
  } else if (K.horns === 'ossicones') {
    const horns = part(root, 'Ossicones'); headG.add(horns);
    for (const z of [-1, 1]) { limb(horns, [-head * 0.25, head * 0.7, z * head * 0.3], [-head * 0.3, head * 1.35, z * head * 0.36], head * 0.09, head * 0.08, coat); blob(horns, [-head * 0.3, head * 1.4, z * head * 0.36], head * 0.12, head * 0.12, head * 0.12, second); }
  }
  if (K.antlers) {
    const ant = part(root, 'Antlers'); headG.add(ant);
    const am = mat('wood', '#cdb48c');
    for (const z of [-1, 1]) {
      const b = [V(-head * 0.2, head * 0.75, z * head * 0.35), V(-head * 0.5, head * 1.6, z * head * 0.9), V(-head * 0.4, head * 2.5, z * head * 1.2), V(-head * 0.1, head * 3.2, z * head * 1.1)];
      mesh(taper(b, head * 0.08, head * 0.03), am, ant);
      for (const [i, len2] of [[1, 0.8], [2, 0.7], [3, 0.5]]) mesh(taper([b[i], b[i].clone().add(V(head * 0.7 * len2, head * 0.55 * len2, z * head * 0.1))], head * 0.05, head * 0.015, 16, 8), am, ant);
    }
  }
  if (K.trunk) {
    const trunk = part(root, 'Trunk'); headG.add(trunk);
    mesh(taper([[head * 0.7, -head * 0.05, 0], [head * 1.0, -head * 0.6, 0], [head * 1.05, -head * 1.4, 0], [head * 0.95, -head * 2.1, 0], [head * 1.25, -head * 2.35, 0]], head * 0.3, head * 0.1), coat, trunk);
    const tusks = part(root, 'Tusks'); headG.add(tusks);
    for (const z of [-1, 1]) mesh(taper([[head * 0.6, -head * 0.45, z * head * 0.38], [head * 1.0, -head * 0.95, z * head * 0.45], [head * 1.5, -head * 0.95, z * head * 0.38]], head * 0.1, head * 0.02), mat('gloss', '#f2ead8'), tusks);
  }
  // legs: shoulder, elbow, wrist in front; hip, stifle (knee), hock (ankle) behind; thick where they meet the body
  const legs = part(root, 'Legs'), feet = part(root, K.feet === 'hoof' ? 'Hooves' : K.feet === 'pad' ? 'Feet' : 'Paws');
  const legMat = K.pattern === 'panda' ? second : coat, foot = K.feet === 'pad' ? body * 0.28 : body * 0.15, footY = foot * 0.75;
  for (const back of [false, true]) for (const z of [-1, 1]) {
    const fx = back ? -len * 0.31 : len * 0.3, zz = z * body * 0.5;
    const joints = K.feet === 'pad'
      ? [V(fx, bodyY - body * 0.1, zz), V(fx, leg * 0.5, zz), V(fx, footY, zz)]
      : back ? [V(fx, bodyY - body * 0.05, zz), V(fx + leg * 0.12, leg * 0.6, zz), V(fx - leg * 0.1, leg * 0.28, zz), V(fx - leg * 0.05, footY, zz)]
        : [V(fx, bodyY - body * 0.15, zz), V(fx - leg * 0.04, leg * 0.56, zz), V(fx + leg * 0.01, leg * 0.18, zz), V(fx + leg * 0.03, footY, zz)];
    const radii = K.feet === 'pad' ? [body * 0.34, body * 0.3, body * 0.3] : back ? [body * 0.5, body * 0.27, body * 0.16, body * 0.14] : [body * 0.38, body * 0.22, body * 0.15, body * 0.14];
    for (let k = 0; k < joints.length - 1; k++) limb(legs, joints[k], joints[k + 1], radii[k], radii[k + 1], k === joints.length - 2 && K.socks ? mat('fur', K.socks) : legMat);
    const f = joints[joints.length - 1], r0 = radii[radii.length - 1];
    if (K.feet === 'hoof') mesh(new THREE.CylinderGeometry(r0 * 0.95, r0 * 1.25, foot * 1.1, 24), hoofMat, feet, [f.x, f.y - foot * 0.2, zz]);
    else if (K.feet === 'pad') mesh(new THREE.CylinderGeometry(r0 * 1.05, r0 * 1.1, foot * 0.7, 32), mat('skin', c2), feet, [f.x, foot * 0.35, zz]);
    else blob(feet, [f.x + foot * 0.45, foot * 0.55, zz], foot * 1.3, foot * 0.6, foot * 0.95, K.socks ? mat('fur', K.socks) : legMat);
  }
  // the tail
  const tailG = new THREE.Group(); tailG.position.set(-len * 0.5, bodyY + body * 0.3, 0); root.add(tailG);
  const tail = part(root, 'Tail'); tailG.add(tail);
  const tm = K.pattern === 'panda' ? second : coat;
  switch (K.tail) {
    case 'up': mesh(taper([[0.04, -0.02, 0], [-0.06, 0.04, 0], [-0.15, 0.13, 0], [-0.2, 0.26, 0], [-0.17, 0.36, 0]], body * 0.17, body * 0.05), tm, tail); break;
    case 'long': mesh(taper([[0.03, 0, 0], [-0.1, -0.1, 0], [-0.18, -0.3, 0.02], [-0.24, -0.42, 0.04], [-0.36, -0.4, 0.05]].map(([x, y, z]) => [x * len * 1.4, y * leg * 1.6, z]), body * 0.14, body * 0.09), tm, tail); break;
    case 'bushy': {
      mesh(taper([[0, 0, 0], [-0.18, -0.12, 0], [-0.34, -0.2, 0], [-0.48, -0.15, 0]], body * 0.25, body * 0.32), tm, tail);
      if (K.tailTip) blob(tail, [-0.5, -0.14, 0], body * 0.36, body * 0.3, body * 0.3, mat('fur', K.tailTip));
      break;
    }
    case 'hair': for (let i = 0; i < 9; i++) mesh(taper([[0, 0, 0], [-0.08, -0.1, (i - 4) * 0.008], [-0.12, -0.45 - (i % 3) * 0.05, (i - 4) * 0.02]], 0.03, 0.012, 24, 8), mat('fur', c2), tail); break;
    case 'tuft': mesh(taper([[0, 0, 0], [-0.06, -0.15, 0], [-0.08, -0.45, 0]], body * 0.06, body * 0.04), tm, tail); blob(tail, [-0.08, -0.5, 0], body * 0.1, body * 0.18, body * 0.1, mat('fur', c2)); break;
    case 'thin': mesh(taper([[0, 0, 0], [-0.12, -0.04, 0], [-0.28, 0.02, 0.04], [-0.42, -0.04, 0]], body * 0.06, body * 0.02), mat('skin', '#d9a7a0'), tail); break;
    case 'curl': mesh(taper(Array.from({ length: 18 }, (_, i) => [-0.02 - i * 0.006, Math.sin(i * 0.9) * 0.05 + i * 0.004, Math.cos(i * 0.9) * 0.05]), body * 0.05, body * 0.03), tm, tail); break;
    case 'puff': blob(tail, [-0.02, 0.02, 0], body * 0.32, body * 0.32, body * 0.32, mat('fur', c2)); break;
    default: blob(tail, [-0.02, 0, 0], body * 0.14, body * 0.14, body * 0.14, tm); break;
  }
  // alive: it breathes, its tail moves, its head turns a little and its ears twitch now and then
  const ear0 = ears.rotation.clone();
  return {
    group: root,
    animate: (t) => {
      bodyG.scale.set(1, 1 + Math.sin(t * 2.2) * 0.012, 1 + Math.sin(t * 2.2) * 0.018);
      tailG.rotation.y = Math.sin(t * (K.tail === 'up' ? 7 : 2)) * (K.tail === 'up' ? 0.45 : 0.15);
      headG.rotation.y = Math.sin(t * 0.5) * 0.18; headG.rotation.z = Math.sin(t * 0.37) * 0.05;
      ears.rotation.x = ear0.x + (Math.sin(t * 1.3) > 0.97 ? Math.sin(t * 40) * 0.08 : 0);
    },
  };
}

// ---------- human figures ----------
// the skeleton (metres, roughly): feet on the floor at y 0, the top of the head at 1.92, facing +z
const SK = { ankle: 0.08, knee: 0.5, hip: 0.95, shoulderY: 1.55, shoulderX: 0.2, hipX: 0.095, head: 1.79 };
const PRESETS = {
  person: { skin: '#d9a37e', suit: '#3c6e9f', suit2: '#2b2f38', boots: '#f2f2f2', hair: '#3a2618', head: 'Head' },
  ironman: { skin: '#b3121b', suit: '#a8121a', suit2: '#d4a017', boots: '#a8121a', head: 'Helmet', armour: true },
  spiderman: { skin: '#c41e24', suit: '#c41e24', suit2: '#1f3e8f', boots: '#c41e24', head: 'Mask' },
  batman: { skin: '#16171a', suit: '#454852', suit2: '#16171a', boots: '#16171a', head: 'Cowl', cape: '#121316', belt: '#d8b437' },
  superman: { skin: '#e2b08c', suit: '#1f4fae', suit2: '#1f4fae', boots: '#c4161c', hair: '#101114', head: 'Head', cape: '#c4161c', belt: '#e8c12c' },
  captain_america: { skin: '#24427a', suit: '#24427a', suit2: '#24427a', boots: '#7a2a1e', head: 'Helmet', belt: '#6b4a2a' },
  hulk: { skin: '#5c8f3a', suit: '#5c8f3a', suit2: '#5b3b8c', boots: '#5c8f3a', hair: '#151515', head: 'Head', bulk: 1.45 },
  robot: { skin: '#9aa3ad', suit: '#9aa3ad', suit2: '#5c6670', boots: '#5c6670', head: 'Head', armour: true },
  astronaut: { skin: '#e9ecef', suit: '#e9ecef', suit2: '#e9ecef', boots: '#c9ced4', head: 'Helmet' },
  knight: { skin: '#c3c7cc', suit: '#c3c7cc', suit2: '#9aa0a8', boots: '#9aa0a8', head: 'Helmet', armour: true },
};

function webTexture(red, blue, sides) {
  return canvasTex(1024, 1024, (g, w, h) => {
    g.fillStyle = red; g.fillRect(0, 0, w, h);
    if (sides) {   // blue down the sides, red front and back (u runs round the body from the front)
      g.fillStyle = blue;
      for (const c of [0.25, 0.75]) g.fillRect((c - 0.09) * w, 0, 0.18 * w, h);
    }
    g.strokeStyle = 'rgba(10,10,14,0.85)'; g.lineWidth = 2.2;
    for (let i = 0; i <= 32; i++) { const x = (i / 32) * w; if (sides && [0.25, 0.75].some((c) => Math.abs(i / 32 - c) < 0.09)) continue; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }
    for (let j = 0; j <= 24; j++) {
      g.beginPath();
      for (let i = 0; i <= 32; i++) { const x = (i / 32) * w, y = (j / 24) * h + Math.sin((i / 32) * Math.PI * 16) * 7; if (i) g.lineTo(x, y); else g.moveTo(x, y); }
      g.stroke();
    }
    if (sides) { g.fillStyle = blue; for (const c of [0.25, 0.75]) g.fillRect((c - 0.08) * w, 0, 0.16 * w, h); }
  });
}
function decal(draw, w = 256, h = 256) { return canvasTex(w, h, draw); }

function humanoidModel(spec) {
  const P = spec.params, preset = PRESETS[P.preset] ? P.preset : 'person', S = { ...PRESETS[preset] }, root = new THREE.Group();
  if (P.color) S.suit = P.color;
  if (P.color2) S.suit2 = P.color2;
  const bulk = S.bulk || 1, armour = !!S.armour;
  const kindOf = (c) => (preset === 'ironman' ? 'paint' : preset === 'robot' || preset === 'knight' ? 'metal' : preset === 'hulk' ? 'skin' : 'fabric');
  const web = preset === 'spiderman';
  const torsoMat = web ? texMat(webTexture(S.suit, S.suit2, true), { kind: 'fabric' }) : mat(kindOf(), S.suit);
  const limbMat = web ? texMat(webTexture(S.suit2, S.suit2, false), { kind: 'fabric' }) : mat(kindOf(), S.suit2 === S.suit ? S.suit : S.suit2);
  const redWeb = web ? texMat(webTexture(S.suit, S.suit, false), { kind: 'fabric' }) : null;
  const skinMat = preset === 'person' || preset === 'superman' ? mat('skin', S.skin) : preset === 'hulk' ? mat('skin', S.skin) : null;
  const sx = SK.shoulderX * bulk, hx = SK.hipX * (1 + (bulk - 1) * 0.6);
  // torso: a lathed body shape, flattened front to back
  const torso = part(root, armour && preset !== 'robot' ? 'Chest Plate' : 'Torso');
  const prof = [[0.0, 0.9], [0.13, 0.915], [0.16, 0.97], [0.155, 1.06], [0.14, 1.13], [0.152, 1.22], [0.18, 1.33], [0.19, 1.43], [0.175, 1.52], [0.12, 1.585], [0.055, 1.615], [0, 1.62]];
  const tg = mesh(lathe(prof.map(([r, y]) => [r * bulk * (y > 1.25 ? 1 : 1 - (bulk - 1) * 0.25), y]), 64), torsoMat, torso);
  tg.scale.z = 0.66 * (1 + (bulk - 1) * 0.4);
  if (preset === 'hulk') { const shorts = part(root, 'Shorts'); mesh(lathe([[0.0, 0.84], [0.15 * bulk, 0.85], [0.17 * bulk * 0.92, 0.95], [0.16 * bulk * 0.88, 1.06], [0, 1.07]], 48), mat('fabric', S.suit2), shorts).scale.z = 0.74; }
  if (preset === 'person') { const pants = part(root, 'Trousers'); mesh(lathe([[0.0, 0.86], [0.14, 0.87], [0.162, 0.97], [0.158, 1.05], [0, 1.06]], 48), mat('fabric', S.suit2), pants).scale.z = 0.7; }
  // shoulders, arms, hands
  const arms = part(root, 'Arms'), hands = part(root, armour || web || preset === 'batman' || preset === 'captain_america' ? 'Gloves' : 'Hands');
  const upperMat = preset === 'ironman' ? mat('paint', S.suit2) : preset === 'person' ? mat('fabric', S.suit) : web ? limbMat : preset === 'superman' || preset === 'batman' || preset === 'captain_america' ? mat('fabric', S.suit) : limbMat;
  const foreMat = preset === 'ironman' ? mat('paint', S.suit) : preset === 'person' ? skinMat : web ? redWeb : preset === 'batman' ? mat('fabric', S.suit2) : preset === 'captain_america' ? mat('fabric', S.suit) : upperMat;
  const handMat = preset === 'person' || preset === 'superman' || preset === 'hulk' ? skinMat : preset === 'captain_america' ? mat('fabric', S.boots) : preset === 'ironman' ? mat('paint', S.suit) : web ? redWeb : mat(kindOf(), S.suit2);
  const wrists = [];
  for (const side of [-1, 1]) {
    const sh = V(side * sx, SK.shoulderY, 0), el = V(side * (sx + 0.085 * bulk), 1.27, -0.03), wr = V(side * (sx + 0.13 * bulk), 1.03, 0.02);
    blob(arms, sh.toArray(), 0.075 * bulk, 0.07 * bulk, 0.07 * bulk, armour ? mat(kindOf(), S.suit) : upperMat);
    limb(arms, sh, el, 0.058 * bulk, 0.048 * bulk, upperMat);
    limb(arms, el, wr, 0.047 * bulk, 0.038 * bulk, foreMat);
    blob(hands, [wr.x + side * 0.008, wr.y - 0.075, wr.z + 0.01], 0.038 * bulk, 0.07 * bulk, 0.03 * bulk, handMat);
    wrists.push(wr);
  }
  // legs and boots
  const legs = part(root, 'Legs'), boots = part(root, armour || web || preset === 'batman' || preset === 'superman' || preset === 'captain_america' ? 'Boots' : 'Feet');
  const thighMat = preset === 'ironman' ? mat('paint', S.suit2) : preset === 'person' || preset === 'hulk' ? mat(preset === 'hulk' ? 'skin' : 'fabric', preset === 'hulk' ? S.skin : S.suit2) : web ? limbMat : mat(kindOf(), S.suit);
  const shinMat = preset === 'ironman' ? mat('paint', S.suit) : preset === 'superman' || preset === 'captain_america' || preset === 'batman' ? mat('fabric', S.boots) : thighMat;
  const bootMat = preset === 'person' ? mat('rubber', S.boots) : preset === 'ironman' ? mat('paint', S.boots) : web ? redWeb : mat(kindOf(), S.boots);
  const feetAt = [];
  for (const side of [-1, 1]) {
    const hip = V(side * hx, SK.hip, 0), knee = V(side * (hx + 0.01), SK.knee, 0.015), ankle = V(side * (hx + 0.015), SK.ankle + 0.03, -0.01);
    limb(legs, hip, knee, 0.085 * bulk, 0.062 * bulk, thighMat);
    limb(legs, knee, preset === 'superman' || preset === 'captain_america' || preset === 'batman' ? knee.clone().lerp(ankle, 0.35) : ankle, 0.06 * bulk, 0.05 * bulk, thighMat);
    if (preset === 'superman' || preset === 'captain_america' || preset === 'batman') limb(boots, knee.clone().lerp(ankle, 0.35), ankle, 0.055 * bulk, 0.047 * bulk, shinMat);
    mesh(roundedBox(0.105 * bulk, 0.085, 0.27, 0.035), bootMat, boots, [ankle.x, 0.043, 0.055]);
    feetAt.push(V(ankle.x, 0, 0.05));
  }
  // neck and head
  const headName = S.head, headG = part(root, headName);
  limb(part(root, 'Neck'), [0, 1.58, 0], [0, 1.7, 0.005], 0.05 * bulk, 0.047 * bulk, preset === 'person' || preset === 'superman' || preset === 'hulk' ? skinMat : mat(kindOf(), preset === 'ironman' ? S.suit2 : S.skin));
  const headMat = web ? redWeb : preset === 'person' || preset === 'superman' || preset === 'hulk' ? skinMat : preset === 'ironman' ? mat('paint', S.suit) : mat(kindOf(), preset === 'batman' ? S.skin : S.skin);
  const skull = blob(headG, [0, SK.head, 0.01], 0.105, 0.125, 0.115, headMat);
  const eyes = part(root, 'Eyes');
  if (preset === 'person' || preset === 'superman' || preset === 'hulk') {
    const hair = part(root, 'Hair');
    const hg = new THREE.SphereGeometry(0.112, 40, 24, 0, Math.PI * 2, 0, Math.PI * 0.52);
    mesh(hg, mat('fabric', S.hair), hair, [0, SK.head + 0.012, -0.005], [deg(-14), 0, 0], [1.02, 1.05, 1.06]);
    for (const x of [-0.038, 0.038]) { blob(eyes, [x, SK.head + 0.012, 0.1], 0.016, 0.012, 0.01, mat('gloss', '#1c140e')); }
    blob(headG, [0, SK.head - 0.022, 0.118], 0.015, 0.022, 0.016, skinMat);   // the nose
  }
  if (preset === 'ironman') {
    // the gold faceplate and its glowing eye slits
    mesh(new THREE.SphereGeometry(0.117, 48, 32, Math.PI * 0.18, Math.PI * 0.64, Math.PI * 0.3, Math.PI * 0.55), mat('paint', S.suit2), headG, [0, SK.head, 0.012], [0, 0, 0], [0.92, 1.08, 1.0]);
    for (const x of [-1, 1]) mesh(roundedBox(0.04, 0.009, 0.01, 0.004), mat('glow', '#d9f6ff'), eyes, [x * 0.035, SK.head + 0.02, 0.117], [0, x * deg(14), x * deg(-8)]);
    const reactor = part(root, 'Arc Reactor');
    mesh(new THREE.TorusGeometry(0.034, 0.008, 12, 40), mat('chrome', '#cfd6dc'), reactor, [0, 1.41, 0.128]);
    mesh(new THREE.CircleGeometry(0.03, 40), mat('glow', '#9ff0ff'), reactor, [0, 1.41, 0.131]);
    const abs = part(root, 'Abdomen Plates');
    for (let i = 0; i < 3; i++) mesh(roundedBox(0.16 - i * 0.012, 0.045, 0.03, 0.012), mat('paint', S.suit2), abs, [0, 1.2 - i * 0.055, 0.092]);
    const rep = part(root, 'Repulsors');
    for (const w of wrists) mesh(new THREE.CircleGeometry(0.018, 24), mat('glow', '#9ff0ff'), rep, [w.x + Math.sign(w.x) * 0.006, w.y - 0.075, w.z + 0.034]);
    const jets = part(root, 'Boot Jets');
    for (const f of feetAt) { const j = mesh(new THREE.ConeGeometry(0.04, 0.16, 24, 1, true), mat('glow', '#bff4ff'), jets, [f.x, -0.075, f.z], [Math.PI, 0, 0]); j.material.transparent = true; j.material.opacity = 0.8; j.castShadow = false; }
    for (const side of [-1, 1]) mesh(roundedBox(0.13, 0.06, 0.15, 0.03), mat('paint', S.suit), part(root, 'Arms'), [side * (sx + 0.02), SK.shoulderY + 0.03, 0]);
  }
  if (web) {
    // big white lenses with black frames, and the spider on the chest
    for (const x of [-1, 1]) {
      const g = new THREE.Group(); g.position.set(x * 0.045, SK.head + 0.012, 0.098); g.rotation.set(0, x * deg(26), x * deg(28)); eyes.add(g);
      blob(g, [0, 0, 0], 0.036, 0.024, 0.012, mat('gloss', '#101014'));
      blob(g, [0, 0, 0.005], 0.029, 0.018, 0.01, mat('glow', '#f2f4f8')).material.emissiveIntensity = 0.35;
    }
    const emblem = part(root, 'Spider Emblem'), em = mat('gloss', '#0d0d10');
    blob(emblem, [0, 1.41, 0.123], 0.016, 0.03, 0.008, em); blob(emblem, [0, 1.455, 0.12], 0.011, 0.014, 0.007, em);
    for (const s of [-1, 1]) for (let i = 0; i < 4; i++) {
      const a = deg(-50 + i * 33), from = V(s * 0.01, 1.42 + (1.5 - i) * 0.008, 0.124);
      mesh(taper([from, from.clone().add(V(s * Math.cos(a) * 0.045, Math.sin(a) * 0.045 + 0.012, 0)), from.clone().add(V(s * Math.cos(a) * 0.065, Math.sin(a) * 0.065 - 0.012, -0.004))], 0.0035, 0.0018, 12, 6), em, emblem);
    }
    const shooters = part(root, 'Web Shooters');
    for (const w of wrists) mesh(new THREE.CylinderGeometry(0.041, 0.041, 0.03, 24), mat('chrome', '#b9c1c9'), shooters, [w.x, w.y + 0.01, w.z]);
  }
  if (preset === 'batman') {
    const cowl = headG;
    for (const x of [-1, 1]) mesh(new THREE.ConeGeometry(0.018, 0.075, 12), mat('fabric', S.skin), cowl, [x * 0.06, SK.head + 0.135, -0.005], [0, 0, x * deg(-8)]);
    mesh(new THREE.SphereGeometry(0.108, 40, 24, Math.PI * 0.2, Math.PI * 0.6, Math.PI * 0.56, Math.PI * 0.3), mat('skin', '#d8a585'), part(root, 'Jaw'), [0, SK.head + 0.004, 0.015], [0, 0, 0], [0.96, 1.08, 1.02]);
    for (const x of [-1, 1]) blob(eyes, [x * 0.036, SK.head + 0.025, 0.104], 0.017, 0.007, 0.008, mat('glow', '#f2f4f8')).material.emissiveIntensity = 0.4;
    const emblem = part(root, 'Bat Emblem');
    const bat = [[0, 0.02], [0.02, 0.035], [0.03, 0.02], [0.06, 0.03], [0.12, 0.005], [0.1, -0.005], [0.085, -0.03], [0.06, -0.018], [0.04, -0.03], [0.02, -0.018], [0, -0.04]];
    const pts = bat.concat(bat.slice(1, -1).reverse().map(([x, y]) => [-x, y]));
    mesh(extrude(pts, 0.008, 0.002), mat('gloss', '#0b0b0d'), emblem, [0, 1.42, 0.125], [0, 0, 0], [1.1, 1.1, 1]);
  }
  if (preset === 'superman') {
    const emblem = part(root, 'Emblem');
    const tex = decal((g, w, h) => {
      g.fillStyle = '#e8c12c'; g.beginPath(); g.moveTo(w * 0.1, h * 0.22); g.lineTo(w * 0.26, h * 0.06); g.lineTo(w * 0.74, h * 0.06); g.lineTo(w * 0.9, h * 0.22); g.lineTo(w * 0.5, h * 0.94); g.closePath(); g.fill();
      g.strokeStyle = '#c4161c'; g.lineWidth = 16; g.stroke();
      g.fillStyle = '#c4161c'; g.font = 'bold 150px Georgia, serif'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('S', w * 0.5, h * 0.42);
    });
    mesh(new THREE.PlaneGeometry(0.15, 0.13), texMat(tex, { kind: 'fabric', transparent: true }), emblem, [0, 1.42, 0.127]);
  }
  if (preset === 'captain_america') {
    const emblem = part(root, 'Star');
    const star = Array.from({ length: 10 }, (_, i) => { const a = Math.PI / 2 + (i * Math.PI) / 5, r = i % 2 ? 0.02 : 0.05; return [Math.cos(a) * r, Math.sin(a) * r]; });
    mesh(extrude(star, 0.01, 0.002), mat('plastic', '#f4f4f4'), emblem, [0, 1.42, 0.125]);
    const stripes = part(root, 'Stripes');
    for (let i = 0; i < 5; i++) mesh(new THREE.CylinderGeometry(0.15, 0.15, 0.022, 48, 1, true, -0.9, 1.8), mat('fabric', i % 2 ? '#f4f4f4' : '#b3202a'), stripes, [0, 1.06 + i * 0.026, 0], [0, 0, 0], [1, 1, 0.68]);
    const shield = part(root, 'Shield');
    const sg = new THREE.Group(); sg.position.set(wrists[1].x + 0.06, 1.1, 0.05); sg.rotation.set(0, Math.PI / 2, 0); shield.add(sg);
    [['#b3202a', 0.2], ['#f4f4f4', 0.16], ['#b3202a', 0.12], ['#1f3c8a', 0.08]].forEach(([c, r], i) => mesh(new THREE.CylinderGeometry(r, r, 0.02 + i * 0.004, 64), mat('paint', c), sg, [0, 0, 0], [Math.PI / 2, 0, 0]));
    mesh(extrude(star.map(([x, y]) => [x * 1.4, y * 1.4]), 0.01, 0.002), mat('paint', '#f4f4f4'), sg, [0, 0, 0.018]);
    const a = decal((g, w, h) => { g.fillStyle = '#f4f4f4'; g.font = 'bold 200px Arial'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('A', w / 2, h / 2 + 10); });
    mesh(new THREE.PlaneGeometry(0.05, 0.05), texMat(a, { transparent: true }), headG, [0, SK.head + 0.06, 0.112], [deg(-20), 0, 0]);
    mesh(new THREE.SphereGeometry(0.106, 40, 24, Math.PI * 0.2, Math.PI * 0.6, Math.PI * 0.56, Math.PI * 0.3), mat('skin', '#e2b08c'), part(root, 'Jaw'), [0, SK.head + 0.004, 0.017], [0, 0, 0], [0.96, 1.08, 1.02]);
    for (const x of [-0.036, 0.036]) blob(eyes, [x, SK.head + 0.015, 0.107], 0.014, 0.01, 0.008, mat('gloss', '#1c2a40'));
  }
  if (preset === 'robot') {
    mesh(roundedBox(0.2, 0.03, 0.02, 0.01), mat('glow', '#4fd8ff'), eyes, [0, SK.head + 0.015, 0.108]);
    const ant = part(root, 'Antenna');
    limb(ant, [0, SK.head + 0.12, 0], [0, SK.head + 0.22, 0], 0.006, 0.006, mat('chrome', '#cfd6dc'));
    blob(ant, [0, SK.head + 0.23, 0], 0.016, 0.016, 0.016, mat('glow', '#ff5a5f'));
    const panel = part(root, 'Chest Panel');
    mesh(roundedBox(0.16, 0.12, 0.02, 0.01), mat('metal', '#3a434d'), panel, [0, 1.38, 0.118]);
    for (let i = 0; i < 3; i++) mesh(new THREE.CircleGeometry(0.012, 20), mat('glow', ['#4fd8ff', '#ffd166', '#7ee787'][i]), panel, [-0.045 + i * 0.045, 1.38, 0.13]);
  }
  if (preset === 'astronaut') {
    skull.material = mat('fabric', '#e9ecef');
    const helmet = part(root, 'Visor');
    mesh(new THREE.SphereGeometry(0.17, 48, 32), mat('glass', '#dfe8ef'), headG, [0, SK.head, 0.01]);
    mesh(new THREE.SphereGeometry(0.162, 48, 32, Math.PI * 0.15, Math.PI * 0.7, Math.PI * 0.25, Math.PI * 0.45), mat('chrome', '#d4a54a'), helmet, [0, SK.head, 0.015]);
    mesh(new THREE.TorusGeometry(0.15, 0.025, 16, 48), mat('fabric', '#c9ced4'), headG, [0, 1.64, 0], [Math.PI / 2, 0, 0]);
    const pack = part(root, 'Life Support Pack');
    mesh(roundedBox(0.34, 0.46, 0.16, 0.04), mat('fabric', '#f2f3f5'), pack, [0, 1.35, -0.2]);
    const flag = decal((g, w, h) => { for (let i = 0; i < 13; i++) { g.fillStyle = i % 2 ? '#fff' : '#b3202a'; g.fillRect(0, (i * h) / 13, w, h / 13 + 1); } g.fillStyle = '#1f3c8a'; g.fillRect(0, 0, w * 0.42, h * 0.54); }, 128, 96);
    mesh(new THREE.PlaneGeometry(0.06, 0.042), texMat(flag), part(root, 'Mission Patch'), [-(sx + 0.03), 1.48, 0.04], [0, -Math.PI / 2 + 0.4, 0]);
  }
  if (preset === 'knight') {
    for (const x of [-1, 1]) mesh(roundedBox(0.045, 0.008, 0.01, 0.003), mat('matte', '#050506'), eyes, [x * 0.035, SK.head + 0.02, 0.117]);
    mesh(new THREE.CylinderGeometry(0.118, 0.12, 0.24, 40), mat('chrome', S.skin), headG, [0, SK.head - 0.005, 0.005]);
    const plume = part(root, 'Plume');
    mesh(taper([[0, SK.head + 0.12, 0], [0, SK.head + 0.24, -0.06], [0, SK.head + 0.18, -0.2], [0, SK.head + 0.02, -0.26]], 0.03, 0.012), mat('fabric', '#b3202a'), plume);
    const sword = part(root, 'Sword'), w0 = wrists[0];
    const sg = new THREE.Group(); sg.position.set(w0.x - 0.01, w0.y - 0.075, w0.z + 0.02); sword.add(sg);
    mesh(roundedBox(0.035, 0.8, 0.008, 0.003), mat('chrome', '#dfe3e8'), sg, [0, -0.43, 0]);
    mesh(roundedBox(0.16, 0.022, 0.03, 0.008), mat('metal', '#b08d3a'), sg, [0, -0.02, 0]);
    mesh(new THREE.CylinderGeometry(0.014, 0.014, 0.12, 16), mat('rubber', '#3a2618'), sg, [0, 0.05, 0]);
    const shield = part(root, 'Shield');
    const out = [[-0.15, 0.2], [0.15, 0.2], [0.15, 0.0], [0.08, -0.16], [0, -0.22], [-0.08, -0.16], [-0.15, 0.0]];
    const sh = mesh(extrude(out, 0.03, 0.01), mat('paint', '#1f3c8a'), shield, [wrists[1].x + 0.06, 1.12, 0.03], [0, Math.PI / 2, 0]);
    mesh(extrude([[-0.02, 0.15], [0.02, 0.15], [0.02, -0.15], [-0.02, -0.15]], 0.01, 0.003), mat('metal', '#d4a017'), sh, [0, 0, 0.018]);
  }
  if (S.cape) {   // a cape hanging from the shoulders, falling in folds
    const cape = part(root, 'Cape'), g = new THREE.PlaneGeometry(1, 1, 30, 40), p = g.attributes.position;
    for (let i = 0; i < p.count; i++) {
      const u = p.getX(i) + 0.5, v = 0.5 - p.getY(i), wid = 0.36 + v * 0.42, y = 1.6 - v * 1.45;
      const x = (u - 0.5) * wid * 2, z = -0.13 - v * 0.14 - Math.cos((u - 0.5) * Math.PI) * 0.05 * (1 - v) + Math.sin(u * Math.PI * 7) * 0.025 * v;
      p.setXYZ(i, x, y, z);
    }
    g.computeVertexNormals();
    const cm = mat('fabric', S.cape); cm.side = THREE.DoubleSide;
    mesh(g, cm, cape);
  }
  if (S.belt) {
    const belt = part(root, 'Utility Belt');
    mesh(new THREE.TorusGeometry(0.152, 0.018, 12, 64), mat(preset === 'batman' ? 'paint' : 'fabric', S.belt), belt, [0, 1.0, 0], [Math.PI / 2, 0, 0], [1, 0.68, 1]);
    if (preset === 'batman') for (let i = 0; i < 6; i++) { const a = deg(-70 + i * 28); mesh(roundedBox(0.035, 0.04, 0.025, 0.008), mat('paint', S.belt), belt, [Math.sin(a) * 0.155, 1.0, Math.cos(a) * 0.104], [0, a, 0]); }
  }
  const floatY = preset === 'ironman' ? 0.08 : 0;
  root.position.y = floatY;
  return {
    group: root,
    animate: (t) => {
      tg.scale.x = 1 + Math.sin(t * 1.8) * 0.01;   // breathing
      if (preset === 'ironman') {
        root.position.y = floatY + Math.sin(t * 1.6) * 0.02;
        part(root, 'Boot Jets').children.forEach((j, i) => { j.scale.y = 1 + Math.sin(t * 31 + i) * 0.15; j.material.opacity = 0.65 + Math.sin(t * 23 + i) * 0.15; });
        part(root, 'Arc Reactor').children[1].material.emissiveIntensity = 1.5 + Math.sin(t * 2.4) * 0.35;
      }
    },
  };
}

module.exports = { animalModel, humanoidModel, ANIMALS, PRESETS };
