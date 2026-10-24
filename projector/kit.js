// The projector's modelling kit, shared by every builder: materials that read as real things (car paint, fabric, fur,
// skin, chrome, glass, screens), smooth shapes (rounded boxes, lathed and extruded profiles, tapered limbs) and
// textures drawn on a canvas (patterns, screens, wood). Sizes are "projector units"; the projector rescales each model.
const THREE = require('../vendor/three/three.cjs');

const WHITE = new THREE.Color(1, 1, 1);
const std = (o) => new THREE.MeshStandardMaterial(o);
const phys = (o) => new THREE.MeshPhysicalMaterial(o);
const MAT = {
  matte: (c) => std({ color: c, roughness: 0.8, metalness: 0.05 }),
  plastic: (c) => phys({ color: c, roughness: 0.32, metalness: 0, clearcoat: 0.35, clearcoatRoughness: 0.3 }),
  metal: (c) => std({ color: c, roughness: 0.3, metalness: 0.9 }),
  chrome: (c) => std({ color: c, roughness: 0.1, metalness: 1 }),
  paint: (c) => phys({ color: c, roughness: 0.32, metalness: 0.45, clearcoat: 1, clearcoatRoughness: 0.06 }),   // cars, armour
  glass: (c) => phys({ color: c, roughness: 0.05, metalness: 0, transparent: true, opacity: 0.28, depthWrite: false }),
  tinted: (c) => phys({ color: c, roughness: 0.06, metalness: 0.3, clearcoat: 1, clearcoatRoughness: 0.03 }),   // car windows, visors
  glow: (c) => std({ color: c, emissive: c, emissiveIntensity: 1.6, roughness: 0.4 }),
  organic: (c) => std({ color: c, roughness: 0.65, metalness: 0, side: THREE.DoubleSide }),
  fabric: (c) => phys({ color: c, roughness: 0.82, metalness: 0, sheen: 0.7, sheenRoughness: 0.55, sheenColor: c.clone().lerp(WHITE, 0.35) }),
  skin: (c) => phys({ color: c, roughness: 0.55, metalness: 0, sheen: 0.35, sheenRoughness: 0.5, sheenColor: c.clone().lerp(WHITE, 0.4) }),
  fur: (c) => phys({ color: c, roughness: 0.9, metalness: 0, sheen: 0.45, sheenRoughness: 0.8, sheenColor: c.clone().lerp(WHITE, 0.25) }),
  rubber: (c) => std({ color: c, roughness: 0.92, metalness: 0 }),
  wood: (c) => std({ color: c, roughness: 0.62, metalness: 0 }),
  gloss: (c) => phys({ color: c, roughness: 0.08, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.02 }),   // eyes, lacquer
};
const mat = (kind, color) => (MAT[kind] || MAT.matte)(new THREE.Color(color));
// a material that shows a picture (a screen, a pattern), optionally glowing like a lit display
function texMat(texture, { kind = 'matte', glow = 0, color = '#ffffff', ...extra } = {}) {
  const m = mat(kind, color);
  m.map = texture;
  if (glow) { m.emissive = new THREE.Color('#ffffff'); m.emissiveMap = texture; m.emissiveIntensity = glow; }
  Object.assign(m, extra);
  return m;
}
const deg = (d) => (d * Math.PI) / 180;
const V = (x, y, z) => new THREE.Vector3(x, y, z);

function part(root, name) {
  let g = root.getObjectByProperty('_partKey', name);
  if (!g) { g = new THREE.Group(); g.userData.part = name; g.name = name; g._partKey = name; root.add(g); }
  return g;
}
function mesh(geo, material, parent, at = [0, 0, 0], rot = [0, 0, 0], scale = null) {
  const m = new THREE.Mesh(geo, material);
  m.position.set(...at); m.rotation.set(...rot);
  if (scale) m.scale.set(...scale);
  m.castShadow = true; m.receiveShadow = true;
  parent.add(m);
  return m;
}
const tube = (points, r, segs = 64, radial = 10, closed = false) =>
  new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points.map((p) => (p.isVector3 ? p : V(...p))), closed), segs, r, radial, closed);

// a tube along points that tapers from radius r1 to r2 (tails, trunks, antlers, horns, cables)
function taper(points, r1, r2, segs = 48, radial = 14) {
  const curve = new THREE.CatmullRomCurve3(points.map((p) => (p.isVector3 ? p : V(...p))));
  const geo = new THREE.TubeGeometry(curve, segs, 1, radial, false), p = geo.attributes.position, c = new THREE.Vector3(), v = new THREE.Vector3();
  for (let i = 0; i <= segs; i++) {
    curve.getPointAt(i / segs, c);
    const r = r1 + (r2 - r1) * (i / segs);
    for (let j = 0; j <= radial; j++) { const k = i * (radial + 1) + j; v.fromBufferAttribute(p, k).sub(c).multiplyScalar(r).add(c); p.setXYZ(k, v.x, v.y, v.z); }
  }
  geo.computeVertexNormals();
  return geo;
}
// a smooth skin through cross-sections: at(u, v) gives the point u of the way along (0..1) and v of the way round (0..1,
// where v 1 meets v 0). Torsos, car bodies, shoe uppers: one seamless surface instead of overlapping blobs.
function loft(nu, nv, at) {
  const cols = nv + 1, pos = new Float32Array((nu + 1) * cols * 3), uv = new Float32Array((nu + 1) * cols * 2), idx = [];
  const p = new THREE.Vector3();
  for (let i = 0; i <= nu; i++) for (let j = 0; j < cols; j++) {
    const k = i * cols + j; at(i / nu, (j % nv) / nv, p);
    pos.set([p.x, p.y, p.z], k * 3); uv.set([j / nv, i / nu], k * 2);
  }
  for (let i = 0; i < nu; i++) for (let j = 0; j < nv; j++) { const a = i * cols + j, b = a + 1, c = a + cols, d = c + 1; idx.push(a, b, c, b, d, c); }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3)); geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2)); geo.setIndex(idx);
  geo.computeVertexNormals();
  // face outward whatever way round the sections were described, and smooth across the seam
  const n = geo.attributes.normal, mid = Math.floor(nu / 2) * cols, c = new THREE.Vector3(), q = new THREE.Vector3(), nn = new THREE.Vector3();
  for (let j = 0; j < nv; j++) c.add(q.fromBufferAttribute(geo.attributes.position, mid + j)); c.divideScalar(nv);
  q.fromBufferAttribute(geo.attributes.position, mid + Math.floor(nv / 4)); nn.fromBufferAttribute(n, mid + Math.floor(nv / 4));
  if (nn.dot(q.sub(c)) < 0) { for (let t = 0; t < idx.length; t += 3) [idx[t + 1], idx[t + 2]] = [idx[t + 2], idx[t + 1]]; geo.setIndex(idx); geo.computeVertexNormals(); }
  for (let i = 0; i <= nu; i++) { const a = i * cols, b = a + nv; q.fromBufferAttribute(n, a).add(nn.fromBufferAttribute(n, b)).normalize(); n.setXYZ(a, q.x, q.y, q.z); n.setXYZ(b, q.x, q.y, q.z); }
  return geo;
}
// a rounded-square point on a cross-section: angle a, half-sizes w and h, squareness n (2 = ellipse, 4+ = boxier)
const squircle = (a, w, h, n = 3) => { const c = Math.cos(a), s = Math.sin(a); return [Math.sign(c) * Math.pow(Math.abs(c), 2 / n) * w, Math.sign(s) * Math.pow(Math.abs(s), 2 / n) * h]; };
// a box with rounded edges and corners (radius r), smooth-shaded: what most manufactured things are
function roundedBox(w, h, d, r = 0.04, s = 4) {
  const half = [w / 2, h / 2, d / 2];
  r = Math.max(0.0005, Math.min(r, ...half.map((x) => x - 1e-4)));
  const n = 2 * s + 1, geo = new THREE.BoxGeometry(1, 1, 1, n, n, n), p = geo.attributes.position, nr = geo.attributes.normal;
  const h0 = 0.5 / n, v = new THREE.Vector3(), inner = new THREE.Vector3();
  for (let i = 0; i < p.count; i++) {
    v.fromBufferAttribute(p, i);
    for (let a = 0; a < 3; a++) {   // the middle row of cells spans the flat face, the outer s rows the rounded band
      const c = v.getComponent(a), core = half[a] - r, ac = Math.abs(c);
      v.setComponent(a, ac <= h0 ? (c / h0) * core : Math.sign(c) * (core + ((ac - h0) / (0.5 - h0)) * r));
    }
    inner.set(...[0, 1, 2].map((a) => Math.max(-(half[a] - r), Math.min(half[a] - r, v.getComponent(a)))));
    const dir = v.clone().sub(inner), len = dir.length();
    if (len > 1e-6) { dir.divideScalar(len); v.copy(inner).addScaledVector(dir, r); nr.setXYZ(i, dir.x, dir.y, dir.z); }
    p.setXYZ(i, v.x, v.y, v.z);
  }
  return geo;
}
// a solid of revolution around y from a profile [[radius, y], ...] (bottles, fuselages, rockets, torsos)
const lathe = (profile, segs = 64) => new THREE.LatheGeometry(profile.map(([r, y]) => new THREE.Vector2(Math.max(0, r), y)), segs);
// a flat outline [[x, y], ...] (or a THREE.Shape) given depth along z, with softly rounded edges, centred on z
function extrude(outline, depth, bevel = 0.02, holes = []) {
  const shape = outline instanceof THREE.Shape ? outline : new THREE.Shape(outline.map(([x, y]) => new THREE.Vector2(x, y)));
  for (const h of holes) shape.holes.push(new THREE.Path(h.map(([x, y]) => new THREE.Vector2(x, y))));
  const geo = new THREE.ExtrudeGeometry(shape, { depth: Math.max(0.001, depth - 2 * bevel), bevelEnabled: bevel > 0, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 4, curveSegments: 32 });
  geo.translate(0, 0, -(depth - 2 * bevel) / 2);
  geo.computeVertexNormals();
  return geo;
}
// a smooth closed outline through the given points
function smoothOutline(points, n = 120) {
  const curve = new THREE.CatmullRomCurve3(points.map(([x, y]) => V(x, y, 0)), true, 'centripetal');
  return curve.getPoints(n).map((p) => [p.x, p.y]);
}
const ellipse = (rx, ry, n = 48, cx = 0, cy = 0) => Array.from({ length: n }, (_, i) => { const a = (i / n) * Math.PI * 2; return [cx + Math.cos(a) * rx, cy + Math.sin(a) * ry]; });
const rect = (w, h, cx = 0, cy = 0) => [[cx - w / 2, cy - h / 2], [cx + w / 2, cy - h / 2], [cx + w / 2, cy + h / 2], [cx - w / 2, cy + h / 2]];
const reverse = (pts) => pts.slice().reverse();   // holes wind the other way

// a limb from a to b, tapering from radius r1 to r2, with rounded ends (arms, legs, necks, trunks)
const UP = V(0, 1, 0);
function limb(parent, a, b, r1, r2, material, caps = true) {
  a = a.isVector3 ? a : V(...a); b = b.isVector3 ? b : V(...b);
  const dir = b.clone().sub(a), len = dir.length(), g = new THREE.Group();
  g.position.copy(a).add(b).multiplyScalar(0.5);
  g.quaternion.setFromUnitVectors(UP, dir.normalize());
  mesh(new THREE.CylinderGeometry(r2, r1, len, 28, 1, true), material, g);
  if (caps) { mesh(new THREE.SphereGeometry(r1, 28, 18), material, g, [0, -len / 2, 0]); mesh(new THREE.SphereGeometry(r2, 28, 18), material, g, [0, len / 2, 0]); }
  parent.add(g);
  return g;
}
// an ellipsoid (radii rx, ry, rz) at a point
const blob = (parent, at, rx, ry, rz, material, segs = 40) => mesh(new THREE.SphereGeometry(1, segs, Math.round(segs * 0.7)), material, parent, at, [0, 0, 0], [rx, ry, rz]);

// textures drawn on a canvas (in the window; tests that only check specs never get here)
function canvasTex(w, h, draw, { repeat = null, srgb = true } = {}) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  draw(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  if (repeat) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(...repeat); }
  return t;
}
// a seeded random, so the same model looks the same every time it's drawn
function rng(seed = 7) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }
function woodTex(base = '#b07a43', dark = '#7a4e26', seed = 3) {
  const r = rng(seed);
  return canvasTex(512, 512, (g, w, h) => {
    g.fillStyle = base; g.fillRect(0, 0, w, h);
    for (let i = 0; i < 90; i++) {
      g.strokeStyle = dark; g.globalAlpha = 0.08 + r() * 0.18; g.lineWidth = 1 + r() * 3;
      const y = r() * h; g.beginPath(); g.moveTo(0, y);
      for (let x = 0; x <= w; x += 32) g.lineTo(x, y + Math.sin(x / 70 + i) * 6 + (r() - 0.5) * 3);
      g.stroke();
    }
    g.globalAlpha = 1;
  });
}

module.exports = { THREE, MAT, mat, texMat, deg, V, part, mesh, tube, taper, loft, squircle, roundedBox, lathe, extrude, smoothOutline, ellipse, rect, reverse, limb, blob, canvasTex, rng, woodTex };
