// The human heart for the projector: four chambers, the great vessels, the coronary arteries on its surface, valves
// and the wall between the two sides. It beats (atria, then ventricles), blood flows through the vessels (blue
// without oxygen, red with it), and the inside view opens it front to back to show the chambers.
const { THREE, mat, deg, V, part, mesh, taper, blob } = require('./kit.js');

const RED = '#b3262e', BLUE = '#3159a8', MUSCLE = '#a8423b';

// the heart's outer shape: a sphere pushed into a cone toward the apex (down and to its left, our right)
function heartShell(front) {
  const geo = new THREE.SphereGeometry(1, 64, 48, front ? 0 : Math.PI, Math.PI), p = geo.attributes.position, v = new THREE.Vector3();
  for (let i = 0; i < p.count; i++) {
    v.fromBufferAttribute(p, i);
    const down = Math.max(0, -v.y);
    v.x *= 1 - down * 0.45; v.z *= (1 - down * 0.4) * 0.82;
    v.y *= 1.18; v.y -= down * down * 0.35;
    v.x += down * down * 0.32;   // the apex points to the heart's left
    p.setXYZ(i, v.x, v.y, v.z);
  }
  geo.computeVertexNormals();
  return geo;
}

function heartModel() {
  const root = new THREE.Group(), holder = new THREE.Group(); holder.position.y = 1.25; holder.rotation.z = deg(-18); root.add(holder);
  const muscle = mat('skin', MUSCLE); muscle.side = THREE.DoubleSide; muscle.sheenColor = new THREE.Color('#ff9a8a');
  const inner = mat('skin', '#6e1f22'); inner.side = THREE.BackSide;
  const wall = part(root, 'Heart Wall'); holder.add(wall);
  const back = mesh(heartShell(false), muscle, wall), front = mesh(heartShell(true), muscle, wall);
  mesh(heartShell(false), inner, wall, [0, 0, 0], [0, 0, 0], [0.9, 0.92, 0.88]);
  // inside: the four chambers (seen with the front opened), the septum between the two sides, the valves
  const chamber = (name, at, r, color) => { const g = part(root, name); holder.add(g); blob(g, at, r[0], r[1], r[2], mat('gloss', color)).material.opacity = 0.92; return g; };
  const ra = chamber('Right Atrium', [-0.38, 0.38, 0.05], [0.3, 0.28, 0.32], '#4a3570');
  const la = chamber('Left Atrium', [0.34, 0.42, -0.1], [0.28, 0.24, 0.3], '#8a2a35');
  const rv = chamber('Right Ventricle', [-0.22, -0.28, 0.12], [0.34, 0.5, 0.32], '#3b3a7a');
  const lv = chamber('Left Ventricle', [0.25, -0.32, 0.0], [0.32, 0.56, 0.34], '#9a2630');
  const septum = part(root, 'Septum'); holder.add(septum);
  mesh(new THREE.PlaneGeometry(0.14, 1.3, 1, 1), mat('skin', '#7a2a2a'), septum, [0.02, -0.08, 0.04], [0, deg(-10), deg(4)]).material.side = THREE.DoubleSide;
  const valves = part(root, 'Valves'); holder.add(valves);
  for (const [x, y, z, c] of [[-0.3, 0.1, 0.12, '#f1e6c8'], [0.3, 0.1, -0.02, '#f1e6c8'], [-0.05, 0.5, 0.25, '#f1e6c8'], [0.1, 0.5, 0.0, '#f1e6c8']]) mesh(new THREE.TorusGeometry(0.11, 0.025, 12, 32), mat('gloss', c), valves, [x, y, z], [Math.PI / 2, 0, 0]);
  const insideParts = [ra, la, rv, lv, septum, valves];
  // the great vessels: the aorta arching over, the pulmonary trunk splitting, the venae cavae, the pulmonary veins
  const vessel = (name, pts, r1, r2, color) => { const g = part(root, name); holder.add(g); const m = mesh(taper(pts, r1, r2, 64, 20), mat('skin', color), g); return { g, curve: new THREE.CatmullRomCurve3(pts.map((p) => V(...p))), m }; };
  const aorta = vessel('Aorta', [[0.05, 0.55, 0.05], [0.08, 1.05, 0.05], [0.0, 1.35, -0.05], [-0.35, 1.32, -0.25], [-0.5, 1.0, -0.4], [-0.45, 0.2, -0.55]], 0.17, 0.13, RED);
  const ag = aorta.g;
  for (const [x, z] of [[-0.05, 0.0], [-0.2, -0.1], [-0.32, -0.2]]) mesh(taper([[x, 1.32, z], [x - 0.02, 1.62, z]], 0.05, 0.04), mat('skin', RED), ag);
  const pulm = vessel('Pulmonary Artery', [[-0.12, 0.45, 0.42], [-0.05, 0.85, 0.35], [0.1, 1.05, 0.15], [0.55, 1.05, 0.0]], 0.15, 0.1, BLUE);
  mesh(taper([[0.05, 1.02, 0.18], [-0.35, 1.05, 0.05], [-0.7, 0.98, 0.0]], 0.09, 0.07), mat('skin', BLUE), pulm.g);
  const svc = vessel('Vena Cava', [[-0.5, 0.55, 0.05], [-0.52, 1.0, 0.02], [-0.5, 1.5, 0.0]], 0.13, 0.12, BLUE);
  const ivc = { curve: new THREE.CatmullRomCurve3([V(-0.45, -1.2, 0), V(-0.45, -0.6, 0.0), V(-0.45, -0.1, 0.02)]) };
  mesh(taper(ivc.curve.points, 0.13, 0.13), mat('skin', BLUE), svc.g);
  const veins = part(root, 'Pulmonary Veins'); holder.add(veins);
  for (const [z, y] of [[0.12, 0.6], [-0.12, 0.45]]) for (const s of [-1, 1]) mesh(taper([[0.35, y, -0.25 + z * 0.4], [0.35 + s * 0.4, y + 0.05, -0.35 + z], [0.35 + s * 0.75, y + 0.1, -0.35 + z]], 0.06, 0.05), mat('skin', '#c4434a'), veins);
  // the coronary arteries, which feed the heart muscle itself, running over its surface
  const cor = part(root, 'Coronary Arteries'); holder.add(cor);
  const onSurface = (pts, push = 1.02) => pts.map(([x, y, z]) => { const d = V(x, y, z); return d.normalize().multiplyScalar(push).multiply(V(1, 1.18, 0.82)).toArray(); });
  for (const pts of [[[0.1, 0.5, 0.8], [0.35, 0.1, 0.9], [0.5, -0.4, 0.7], [0.55, -0.9, 0.4]], [[-0.1, 0.5, 0.8], [-0.45, 0.2, 0.85], [-0.7, -0.2, 0.6]], [[0.3, 0.3, 0.9], [0.65, 0.0, 0.7], [0.85, -0.3, 0.3]]]) mesh(taper(onSurface(pts), 0.03, 0.012, 40, 8), mat('skin', '#d9373f'), cor);
  // blood: little cells flowing along the vessels
  const blood = part(root, 'Blood Flow'); holder.add(blood);
  const flows = [[aorta.curve, '#ff4b52'], [pulm.curve, '#5d86ff'], [svc.curve, '#5d86ff'], [ivc.curve, '#5d86ff']].map(([curve, c]) => {
    const n = 14, inst = new THREE.InstancedMesh(new THREE.SphereGeometry(0.03, 10, 8), mat('glow', c), n); inst.castShadow = false; blood.add(inst); return { curve, inst, n };
  });
  const m4 = new THREE.Matrix4(), tmp = new THREE.Vector3();
  const cutaway = (on) => { front.visible = !on; insideParts.forEach((g) => { g.visible = on; }); };
  cutaway(false);
  return {
    group: root, cutaway,
    animate: (t) => {
      // lub-dub: the atria squeeze a moment before the ventricles, about 70 times a minute
      const beat = (t * 1.17) % 1, atria = Math.exp(-Math.pow((beat - 0.1) / 0.06, 2)), vent = Math.exp(-Math.pow((beat - 0.3) / 0.09, 2));
      wall.scale.set(1 - vent * 0.05, 1 - vent * 0.035, 1 - vent * 0.05);
      ra.scale.setScalar(1 - atria * 0.08); la.scale.setScalar(1 - atria * 0.08); rv.scale.setScalar(1 - vent * 0.1); lv.scale.setScalar(1 - vent * 0.1);
      flows.forEach((f, k) => { for (let i = 0; i < f.n; i++) { f.curve.getPointAt((t * 0.18 + i / f.n + k * 0.13) % 1, tmp); m4.makeTranslation(tmp.x, tmp.y, tmp.z); f.inst.setMatrixAt(i, m4); } f.inst.instanceMatrix.needsUpdate = true; });
    },
  };
}

module.exports = { heartModel };
