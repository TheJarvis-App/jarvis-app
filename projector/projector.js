// The 3D projector: a popup with the answer above and a holographic projector below it, where the model Jarvis chose
// (projector.py) materialises, turns, can be explored part by part, and explains itself as you pick its parts.
//
// The projector is a real-time Three.js scene: a dark chamber, a lit platform with glowing rings, a beam of light and
// a few drifting motes; the model rises into it behind a scan line. Drag to turn it, scroll or pinch to zoom, drag with
// two fingers / the right button / Shift to pan. Every control on screen does something for this model; the ones that
// don't apply (exploded view, cutaway, animation) aren't shown. Nothing draws while the popup is closed, and each model
// is disposed of when another replaces it.
(function () {
  const builders = require('./projector/builders.js');
  const THREE = builders.THREE;
  const $ = (id) => document.getElementById(id);
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const history = [];      // models shown this session, to step back and forth through (like the planets)
  let current = -1;

  // ---------- the scene: chamber, platform, beam, motes ----------
  let renderer, scene, camera, stage, canvas, model = null, selected = null, raf = 0, last = 0, t0 = 0;
  const view = { theta: 0.6, phi: 1.2, radius: 6.2, target: new THREE.Vector3(0, 1.15, 0) };
  const goal = { theta: 0.6, phi: 1.2, radius: 6.2, target: new THREE.Vector3(0, 1.15, 0) };
  const state = { autoRotate: !reduce, labels: true, exploded: 0, explodedGoal: 0, cutaway: false, playing: !reduce, scan: 1 };
  const beamU = { uTime: { value: 0 }, uColor: { value: new THREE.Color('#4fd8ff') } };
  let motes, scanLine, clip;

  function setup() {
    stage = $('projStage'); canvas = $('projCanvas');
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.12;
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.localClippingEnabled = true;
    scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x040812, 9, 22);
    scene.environment = studio();
    scene.environmentIntensity = 1.0;
    camera = new THREE.PerspectiveCamera(36, 1, 0.05, 80);
    // light: a soft sky, a warm key that casts the shadow, a cyan rim from behind, and the projector's own glow below
    scene.add(new THREE.HemisphereLight(0xdfeeff, 0x141a28, 1.15));
    const key = new THREE.DirectionalLight(0xfff1e0, 2.8); key.position.set(3, 6, 4); key.castShadow = true;
    key.shadow.mapSize.setScalar(1024); Object.assign(key.shadow.camera, { left: -3, right: 3, top: 3, bottom: -3, near: 0.5, far: 20 });
    key.shadow.bias = -0.0005;
    const rim = new THREE.DirectionalLight(0x4fd8ff, 1.6); rim.position.set(-4, 3, -5);
    const up = new THREE.PointLight(0x4fd8ff, 2.2, 6, 2); up.position.set(0, 0.7, 0);
    const fill = new THREE.DirectionalLight(0xffffff, 0.75); fill.position.set(0, 0.4, 1); camera.add(fill); scene.add(camera);   // a soft light from the viewer
    scene.add(key, rim, up);
    // the platform: a dark metal disc with two glowing rings and a fine radial grid
    const plat = new THREE.Group(); scene.add(plat);
    const disc = new THREE.Mesh(new THREE.CylinderGeometry(2.1, 2.25, 0.16, 96), new THREE.MeshStandardMaterial({ color: 0x0b1220, metalness: 0.7, roughness: 0.6 }));
    disc.position.y = -0.08; disc.receiveShadow = true; plat.add(disc);
    const glow = (r, w, o) => { const m = new THREE.Mesh(new THREE.TorusGeometry(r, w, 8, 160), new THREE.MeshBasicMaterial({ color: 0x4fd8ff, transparent: true, opacity: o })); m.rotation.x = Math.PI / 2; m.position.y = 0.005; plat.add(m); return m; };
    glow(2.02, 0.012, 0.9); glow(1.45, 0.006, 0.45); glow(0.7, 0.004, 0.3);
    const grid = new THREE.PolarGridHelper(2.0, 24, 6, 96, 0x1d4a66, 0x12324a); grid.position.y = 0.004; plat.add(grid);
    // the beam: a soft cone of light rising from the platform
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(1.95, 2.05, 3.4, 64, 1, true), new THREE.ShaderMaterial({
      uniforms: beamU, transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
      vertexShader: 'varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: `uniform float uTime; uniform vec3 uColor; varying vec3 vP;
        void main(){ float h = (vP.y + 1.7) / 3.4; float shimmer = 0.9 + 0.1 * sin(uTime * 1.3 + vP.x * 3.0);
          gl_FragColor = vec4(uColor, pow(1.0 - h, 3.0) * 0.05 * shimmer); }`,
    }));
    beam.position.y = 1.7; scene.add(beam);
    // motes drifting up through the beam
    const n = 160, pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { const a = Math.random() * Math.PI * 2, r = Math.sqrt(Math.random()) * 1.9; pos.set([Math.cos(a) * r, Math.random() * 3.2, Math.sin(a) * r], i * 3); }
    const mg = new THREE.BufferGeometry(); mg.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    motes = new THREE.Points(mg, new THREE.PointsMaterial({ color: 0x9fe8ff, size: 0.025, transparent: true, opacity: 0.55, depthWrite: false, blending: THREE.AdditiveBlending }));
    scene.add(motes);
    // the scan line that draws the model in, and the clipping plane that hides what it hasn't reached yet
    scanLine = new THREE.Mesh(new THREE.RingGeometry(0.0, 2.0, 96), new THREE.MeshBasicMaterial({ color: 0x9fe8ff, transparent: true, opacity: 0.0, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }));
    scanLine.rotation.x = -Math.PI / 2; scene.add(scanLine);
    clip = new THREE.Plane(new THREE.Vector3(0, -1, 0), 10);
    new ResizeObserver(resize).observe(stage);
    controls();
    resize();
  }
  // a dark room with a cool key panel, a violet fill and a warm strip below: what metal and glass reflect
  function studio() {
    const pm = new THREE.PMREMGenerator(renderer), room = new THREE.Scene();
    room.add(new THREE.Mesh(new THREE.BoxGeometry(12, 12, 12), new THREE.MeshBasicMaterial({ color: 0x0a1020, side: THREE.BackSide })));
    const panel = (rgb, pos, w, h) => { const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(...rgb) })); m.position.set(...pos); m.lookAt(0, 0, 0); room.add(m); };
    panel([3.2, 3.6, 4.0], [-4.5, 3.5, 3.5], 3.5, 2.5); panel([1.4, 1.2, 2.6], [5, 0.5, -2], 2.5, 5); panel([2.6, 2.2, 1.8], [0, -5, -3], 6, 1.2); panel([0.8, 0.9, 1.1], [0, 6, 0], 8, 8);
    const env = pm.fromScene(room, 0.03).texture;
    pm.dispose(); room.traverse((o) => { o.geometry?.dispose(); o.material?.dispose(); });
    return env;
  }
  function resize() {
    if (!renderer) return;
    const w = Math.max(1, stage.clientWidth), h = Math.max(1, stage.clientHeight);
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
    fitRadius();
  }

  // ---------- models ----------
  function dispose(obj) {
    obj.traverse((o) => {
      o.geometry?.dispose();
      for (const m of [].concat(o.material || [])) { for (const v of Object.values(m)) if (v?.isTexture) v.dispose(); m.dispose(); }
    });
  }
  // a soft cyan rim on every surface: it outlines the model against the dark chamber, the look of a hologram; the
  // picked part's rim brightens, so it glows without losing its own colours
  const RIM = new THREE.Color('#4fd8ff'), RIM_BASE = 0.3, RIM_PICKED = 1.7;
  function addRim(m) {
    if (!m.isMeshStandardMaterial) return;
    m.userData.rim = { value: RIM.clone().multiplyScalar(RIM_BASE) };
    m.onBeforeCompile = (sh) => {
      sh.uniforms.uRim = m.userData.rim;
      sh.fragmentShader = 'uniform vec3 uRim;\n' + sh.fragmentShader.replace('#include <opaque_fragment>',
        'outgoingLight += uRim * pow(1.0 - saturate(abs(dot(normalize(normal), normalize(vViewPosition)))), 2.4);\n#include <opaque_fragment>');
    };
    m.customProgramCacheKey = () => 'jarvis-rim';
  }
  let modelHeight = 2, modelWidth = 2;
  function place(built) {
    // fit every model to the platform: about 2.8 tall and 3.6 wide at most, standing just above the disc
    const g = built.group, holder = new THREE.Group();
    holder.add(g);
    const box = new THREE.Box3().setFromObject(g, true), size = box.getSize(new THREE.Vector3());   // precise: rotated rings don't inflate it
    const s = Math.min(2.8 / Math.max(size.y, 0.01), 3.6 / Math.max(size.x, size.z, 0.01));
    g.scale.multiplyScalar(s);
    const box2 = new THREE.Box3().setFromObject(g, true), c = box2.getCenter(new THREE.Vector3());
    g.position.x -= c.x; g.position.z -= c.z; g.position.y += 0.12 - box2.min.y;
    modelHeight = box2.max.y - box2.min.y + 0.12;
    modelWidth = Math.max(box2.max.x - box2.min.x, box2.max.z - box2.min.z);
    holder.userData.built = built;
    g.traverse((o) => {
      if (!o.isMesh && !o.isLineSegments && !o.isPoints) return;
      o.material = [].concat(o.material).map((m) => { m = m.clone(); m.clippingPlanes = [clip]; addRim(m); return m; })[0];
      if (o.material.emissive) { o.userData.emissive = o.material.emissive.clone(); o.userData.ei = o.material.emissiveIntensity; }
      o.userData.opacity = o.material.opacity; o.userData.transparent = o.material.transparent; o.userData.depthWrite = o.material.depthWrite;
    });
    return holder;
  }
  function parts() {
    const out = new Map();
    // only parts with something to show: an empty group would be a label and a button that do nothing
    model?.traverse((o) => { if (o.userData.part && !out.has(o.userData.part) && o.getObjectsByProperty('isMesh', true).length + o.getObjectsByProperty('isInstancedMesh', true).length) out.set(o.userData.part, o); });
    return out;
  }

  let swapping = null, thumbWanted = 0, thumbNow = false;
  function present(index, keep = false) {
    if (!renderer) setup();
    const spec = history[index];
    current = index;
    $('projLayer').hidden = false;
    document.body.classList.add('scene-paused');   // the window's own animations can rest while this is open
    $('projNav').hidden = history.length < 2;
    $('projCount').textContent = `${index + 1} / ${history.length}`;
    $('projPrev').disabled = index === 0; $('projNext').disabled = index === history.length - 1;
    words(spec);
    $('projGallery').hidden = true; $('projGalleryBtn').setAttribute('aria-pressed', 'false');
    if (keep && model && model.userData.spec?.generator === spec.generator) {   // a follow-up about the same model: keep it
      model.userData.spec = { ...model.userData.spec, ...spec, params: model.userData.spec.params, parts: model.userData.spec.parts };
      setupControls(spec, model.userData.built);
      focus(spec.focus);
      start();
      return;
    }
    $('projLoading').hidden = false;
    // the old model leaves (scan line sweeps down), then the new one is drawn in from the platform up
    const old = model;
    swapping = { old, t: old && !reduce ? 0 : 1 };
    setTimeout(() => {
      let built;
      try { built = builders.build(spec, ELEMENT_NAMES); }
      catch (error) { console.error('Projector: could not build', error); $('projLoading').hidden = true; failure(spec); return; }
      if (history[current] !== spec) return;   // another model was asked for meanwhile
      const holder = place(built);
      holder.userData.spec = spec;
      if (swapping?.old) { scene.remove(swapping.old); dispose(swapping.old); }
      model = holder; scene.add(model);
      selected = null;
      state.exploded = state.explodedGoal = built.explodedFirst ? 1 : 0;
      state.cutaway = !!spec.params?.cutaway;
      built.cutaway?.(state.cutaway);
      built.explode?.(state.exploded);
      state.playing = !reduce; state.scan = reduce ? 1 : 0;
      setupControls(spec, built);
      labelsFor(spec);
      chips(spec);
      resetView(true);
      if (spec.followUp) focus(spec.focus);
      $('projLoading').hidden = true;
      thumbWanted = performance.now() + 1700;
      swapping = null;
    }, old && !reduce ? 380 : 30);
    start();
  }
  function failure(spec) {
    $('projPartName').textContent = 'This model could not be drawn';
    $('projPartText').textContent = `${spec.explanation || ''} Something went wrong while building it, so it is shown in words only.`;
  }

  // ---------- words: the answer above, and a part's role when one is picked ----------
  const ELEMENT_NAMES = { H: 'Hydrogen', C: 'Carbon', N: 'Nitrogen', O: 'Oxygen', F: 'Fluorine', Cl: 'Chlorine', S: 'Sulfur', P: 'Phosphorus', Br: 'Bromine', I: 'Iodine', Na: 'Sodium', K: 'Potassium', Ca: 'Calcium', Fe: 'Iron', Mg: 'Magnesium', Si: 'Silicon', B: 'Boron' };
  function words(spec) {
    $('projKicker').textContent = spec.kicker || '3D model';
    $('projTitle').textContent = spec.title;
    $('projSummary').textContent = spec.summary || '';
    showExplanation(spec);
    const facts = $('projFacts'); facts.replaceChildren();
    for (const f of spec.facts || []) { const li = document.createElement('li'); li.textContent = f; facts.append(li); }
    facts.hidden = !(spec.facts || []).length;
    $('projHonesty').textContent = spec.honesty || '';
    $('projHonesty').hidden = !spec.honesty;
  }
  // one button per part the model really has (in the spec's order), so none of them is a button that does nothing
  function chips(spec) {
    const have = parts(), list = $('projParts'); list.replaceChildren();
    const names = (spec.part_names || []).filter((n) => have.has(n)).concat([...have.keys()].filter((n) => !(spec.part_names || []).includes(n)));
    for (const name of names) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'proj-chip'; b.textContent = name; b.dataset.part = name;
      b.setAttribute('aria-pressed', 'false');
      b.addEventListener('click', () => select(selected?.userData.part === name ? null : name));
      list.append(b);
    }
  }
  function showExplanation(spec) {
    $('projPartName').textContent = spec.question ? `“${spec.question}”` : 'About it';
    $('projPartText').textContent = spec.explanation || spec.summary || '';
  }

  // ---------- picking a part: it lights up, the rest steps back, and the words follow it ----------
  function select(name) {
    const spec = model?.userData.spec;
    if (!spec) return;
    const map = parts();
    selected = name ? map.get(name) || null : null;
    model.traverse((o) => {
      if (!o.isMesh) return;
      const mine = !!selected && isInside(o, selected);
      const m = o.material;
      if (m.userData.rim) m.userData.rim.value.copy(RIM).multiplyScalar(mine ? RIM_PICKED : selected ? 0.12 : RIM_BASE);
      if (m.emissive && o.userData.emissive) { m.emissive.copy(o.userData.emissive).lerp(RIM, mine ? 0.18 : 0); m.emissiveIntensity = mine ? Math.max(0.25, o.userData.ei) : o.userData.ei; }
      m.transparent = selected && !mine ? true : o.userData.transparent;
      m.opacity = selected && !mine ? Math.min(0.3, o.userData.opacity) : o.userData.opacity;
      m.depthWrite = selected && !mine ? false : o.userData.depthWrite ?? true;
    });
    document.querySelectorAll('#projParts .proj-chip').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.part === name)));
    if (selected) {
      $('projPartName').textContent = name;
      $('projPartText').textContent = spec.info?.[name] || 'Part of the model.';
    } else showExplanation(spec);
    labels.forEach((l) => { l.el.classList.toggle('is-picked', l.name === name); l.line.classList.toggle('is-picked', l.name === name); });
  }
  function isInside(o, ancestor) { for (let n = o; n; n = n.parent) if (n === ancestor) return true; return false; }
  function focus(names) { if (names?.length) select(names[0]); }

  // ---------- labels that float beside their parts ----------
  let labels = [];
  function labelsFor(spec) {
    const box = $('projLabels'); box.replaceChildren(); labels = [];
    const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'proj-leaders'); svg.setAttribute('aria-hidden', 'true'); box.append(svg);
    const map = parts();
    for (const [name, obj] of map) {
      const line = document.createElementNS(NS, 'path'), dot = document.createElementNS(NS, 'circle');
      dot.setAttribute('r', '2.6'); svg.append(line, dot);
      const el = document.createElement('button');
      el.type = 'button'; el.className = 'proj-label'; el.textContent = name; el.tabIndex = -1;   // the part list is the keyboard way in
      el.addEventListener('click', () => select(selected?.userData.part === name ? null : name));
      box.append(el);
      labels.push({ name, obj, el, line, dot });
    }
    box.hidden = !state.labels;
  }
  const tmp = new THREE.Vector3(), tmpBox = new THREE.Box3();
  function placeLabels() {
    if (!state.labels || !labels.length) return;
    const w = stage.clientWidth, h = stage.clientHeight;
    // where each part is on screen, and how wide the whole model is there
    tmpBox.setFromObject(model);
    let minX = Infinity, maxX = -Infinity;
    for (const x of [tmpBox.min.x, tmpBox.max.x]) for (const y of [tmpBox.min.y, tmpBox.max.y]) for (const z of [tmpBox.min.z, tmpBox.max.z]) {
      tmp.set(x, y, z).project(camera); const sx = ((tmp.x + 1) / 2) * w; minX = Math.min(minX, sx); maxX = Math.max(maxX, sx);
    }
    const mid = (minX + maxX) / 2;
    for (const l of labels) {
      tmpBox.setFromObject(l.obj);
      if (tmpBox.isEmpty()) { l.el.hidden = true; l.line.setAttribute('d', ''); continue; }
      tmpBox.getCenter(tmp).project(camera);
      l.el.hidden = tmp.z > 1;
      l.ax = ((tmp.x + 1) / 2) * w; l.ay = ((1 - tmp.y) / 2) * h; l.w = l.el.offsetWidth || l.name.length * 7 + 20;
    }
    // callouts: names in a column on each side of the model, spaced so none overlap, a thin line to each part
    const shown = labels.filter((l) => !l.el.hidden);
    for (const side of [-1, 1]) {
      const col = shown.filter((l) => (side < 0 ? l.ax < mid : l.ax >= mid)).sort((a, b) => a.ay - b.ay);
      let y = -Infinity;
      for (const l of col) { l.y = Math.max(l.ay, y + 28); y = l.y; }
      const over = y - (h - 70); if (over > 0) col.forEach((l) => { l.y -= over; });
      for (const l of col) {
        const edge = side < 0 ? Math.max(12 + l.w, minX - 28) : Math.min(w - 12 - l.w, maxX + 28);
        l.x = side < 0 ? edge - l.w : edge;
        l.el.style.transform = `translate(${l.x}px, ${l.y}px) translate(0, -50%)`;
        const lx = side < 0 ? edge : edge;
        l.line.setAttribute('d', `M${lx} ${l.y} L${l.ax} ${l.ay}`);
        l.dot.setAttribute('cx', l.ax); l.dot.setAttribute('cy', l.ay);
      }
    }
    labels.forEach((l) => { l.line.style.display = l.dot.style.display = l.el.hidden ? 'none' : ''; });
  }

  // ---------- controls ----------
  function setupControls(spec, built) {
    const bar = $('projControls');
    bar.querySelector('[data-act="explode"]').hidden = !built.explode;
    bar.querySelector('[data-act="explode"]').setAttribute('aria-pressed', String(state.explodedGoal > 0.5));
    bar.querySelector('[data-act="cutaway"]').hidden = !built.cutaway;
    bar.querySelector('[data-act="cutaway"]').setAttribute('aria-pressed', String(state.cutaway));
    const animated = !!built.animate;
    for (const act of ['play', 'replay']) bar.querySelector(`[data-act="${act}"]`).hidden = !animated;
    bar.querySelector('[data-act="play"]').setAttribute('aria-pressed', String(state.playing));
    bar.querySelector('[data-act="play"]').textContent = state.playing ? 'Pause' : 'Play';
    bar.querySelector('[data-act="rotate"]').setAttribute('aria-pressed', String(state.autoRotate));
    bar.querySelector('[data-act="labels"]').setAttribute('aria-pressed', String(state.labels));
    $('projHud').textContent = '';
  }
  const PRESETS = { front: { theta: 0, phi: 1.32 }, side: { theta: Math.PI / 2, phi: 1.32 }, top: { theta: 0.001, phi: 0.12 } };
  function fitRadius() {
    // close enough that the model fills most of the stage (the platform may run off its edges), whatever its shape
    const fov = (camera.fov * Math.PI) / 180, half = Math.max(modelHeight * 0.57, (modelWidth * 0.6) / Math.max(0.4, camera.aspect));
    return Math.max(2.6, Math.min(14, half / Math.tan(fov / 2) + modelWidth * 0.3));
  }
  function resetView(instant) {
    // two models side by side are seen almost face on, so neither stands behind the other
    Object.assign(goal, { theta: model?.userData.spec?.generator === 'compare' ? 0.12 : 0.6, phi: 1.2, radius: fitRadius() });
    goal.target.set(0, modelHeight * 0.5, 0);
    if (instant) { Object.assign(view, { theta: goal.theta, phi: goal.phi, radius: goal.radius }); view.target.copy(goal.target); }
  }
  function act(what, button) {
    const built = model?.userData.built;
    switch (what) {
      case 'reset': resetView(false); state.explodedGoal = built?.explodedFirst ? 1 : 0; select(null); break;
      case 'rotate': state.autoRotate = !state.autoRotate; button.setAttribute('aria-pressed', String(state.autoRotate)); break;
      case 'labels': state.labels = !state.labels; $('projLabels').hidden = !state.labels; button.setAttribute('aria-pressed', String(state.labels)); break;
      case 'explode': state.explodedGoal = state.explodedGoal > 0.5 ? 0 : 1; button.setAttribute('aria-pressed', String(state.explodedGoal > 0.5)); break;
      case 'cutaway': state.cutaway = !state.cutaway; built?.cutaway?.(state.cutaway); button.setAttribute('aria-pressed', String(state.cutaway)); break;
      case 'play': state.playing = !state.playing; button.textContent = state.playing ? 'Pause' : 'Play'; button.setAttribute('aria-pressed', String(state.playing)); break;
      case 'replay': state.scan = 0; state.playing = true; $('projControls').querySelector('[data-act="play"]').textContent = 'Pause'; break;
      case 'zoomin': goal.radius = Math.max(2.2, goal.radius * 0.8); break;
      case 'zoomout': goal.radius = Math.min(16, goal.radius * 1.25); break;
      case 'front': case 'side': case 'top': Object.assign(goal, PRESETS[what]); break;
      case 'full': {
        const on = $('projCard').classList.toggle('is-full');
        button.setAttribute('aria-pressed', String(on)); button.textContent = on ? 'Exit full screen' : 'Full screen';
        break;
      }
    }
  }
  function controls() {
    $('projControls').addEventListener('click', (e) => { const b = e.target.closest('button[data-act]'); if (b) act(b.dataset.act, b); });
    $('projClose').addEventListener('click', () => window.hideProjector());
    $('projPrev').addEventListener('click', () => window.reopenProjector('prev'));
    $('projNext').addEventListener('click', () => window.reopenProjector('next'));
    // pointer: one finger or the left button turns it, two fingers / right button / Shift pans, the wheel or a pinch zooms
    const pointers = new Map();
    let down = null, moved = 0, pinch = 0;
    canvas.addEventListener('pointerdown', (e) => {
      canvas.setPointerCapture(e.pointerId); pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      down = { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey }; moved = 0; state.userAt = performance.now();
      if (pointers.size === 2) { const [a, b] = [...pointers.values()]; pinch = Math.hypot(a.x - b.x, a.y - b.y); }
    });
    canvas.addEventListener('pointermove', (e) => {
      if (!pointers.has(e.pointerId)) return;
      const p = pointers.get(e.pointerId), dx = e.clientX - p.x, dy = e.clientY - p.y;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY }); moved += Math.abs(dx) + Math.abs(dy); state.userAt = performance.now();
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
        if (pinch) goal.radius = Math.max(2.2, Math.min(16, goal.radius * (pinch / d)));
        pinch = d; pan(dx / 2, dy / 2);
      } else if (down?.pan) pan(dx, dy);
      else { goal.theta -= dx * 0.008; goal.phi = Math.max(0.08, Math.min(1.62, goal.phi - dy * 0.006)); }
    });
    const up = (e) => {
      pointers.delete(e.pointerId); pinch = 0;
      if (down && moved < 6 && e.type === 'pointerup') pick(e);   // a tap, not a drag: pick what's under it
      if (!pointers.size) down = null;
    };
    canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', up);
    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    canvas.addEventListener('wheel', (e) => { e.preventDefault(); goal.radius = Math.max(2.2, Math.min(16, goal.radius * Math.exp(e.deltaY * 0.0012))); state.userAt = performance.now(); }, { passive: false });
    // keys, while the popup is open: arrows turn, + and - zoom, R resets, L labels, Space plays, Esc steps out
    window.addEventListener('keydown', (e) => {
      if ($('projLayer').hidden || /INPUT|TEXTAREA/.test(document.activeElement?.tagName)) return;
      const k = e.key;
      if (k === 'Escape') { e.preventDefault(); e.stopPropagation(); if (!$('projGallery').hidden && model) toggleGallery(false); else if ($('projCard').classList.contains('is-full')) act('full', $('projControls').querySelector('[data-act="full"]')); else if (selected) select(null); else window.hideProjector(); return; }
      const keyMap = { ArrowLeft: () => (goal.theta += 0.25), ArrowRight: () => (goal.theta -= 0.25), ArrowUp: () => (goal.phi = Math.max(0.08, goal.phi - 0.15)), ArrowDown: () => (goal.phi = Math.min(1.62, goal.phi + 0.15)),
        '+': () => act('zoomin'), '=': () => act('zoomin'), '-': () => act('zoomout'), r: () => act('reset'), R: () => act('reset'),
        l: () => act('labels', $('projControls').querySelector('[data-act="labels"]')), ' ': () => model?.userData.built?.animate && act('play', $('projControls').querySelector('[data-act="play"]')) };
      if (keyMap[k] && !(k === ' ' && document.activeElement?.tagName === 'BUTTON')) { e.preventDefault(); e.stopPropagation(); keyMap[k](); state.userAt = performance.now(); }
      else if (/^[a-z]$/i.test(k) && !e.metaKey && !e.ctrlKey) e.stopPropagation();   // the window's own letter shortcuts wait while the projector is open
    }, true);
  }
  function pan(dx, dy) {
    const right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0), upv = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
    const k = goal.radius * 0.0016;
    goal.target.addScaledVector(right, -dx * k).addScaledVector(upv, dy * k);
    goal.target.clampLength(0, 4);
  }
  const ray = new THREE.Raycaster();
  function pick(e) {
    if (!model) return;
    const r = canvas.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
    const hit = ray.intersectObject(model, true).find((h) => h.object.visible && h.object.material?.opacity > 0.3);
    let name = null;
    for (let o = hit?.object; o; o = o.parent) if (o.userData.part) { name = o.userData.part; break; }
    select(name && name !== selected?.userData.part ? name : null);
  }

  // ---------- the loop: only while the popup is open and the window is visible ----------
  function start() { if (!raf) { last = performance.now(); t0 = t0 || last; raf = requestAnimationFrame(frame); } }
  let animT = 0;
  function frame(now) {
    raf = 0;
    if ($('projLayer').hidden || document.hidden) return;
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const t = (now - t0) / 1000;
    const built = model?.userData.built;
    // the camera glides to where it's asked to be; when left alone for a while it turns slowly on its own
    if (state.autoRotate && performance.now() - (state.userAt || 0) > 2500) goal.theta += dt * 0.22;
    const f = 1 - Math.exp(-dt * 7);
    view.theta += (goal.theta - view.theta) * f; view.phi += (goal.phi - view.phi) * f; view.radius += (goal.radius - view.radius) * f;
    view.target.lerp(goal.target, f);
    camera.position.set(view.target.x + view.radius * Math.sin(view.phi) * Math.sin(view.theta), view.target.y + view.radius * Math.cos(view.phi), view.target.z + view.radius * Math.sin(view.phi) * Math.cos(view.theta));
    camera.lookAt(view.target);
    // the model: drawn in by the scan line from the platform up, exploded and animated as asked
    if (model) {
      state.scan = Math.min(1, state.scan + dt / 1.3);
      const k = 1 - Math.pow(1 - state.scan, 3), y = -0.05 + k * (modelHeight + 0.4);
      clip.constant = state.scan >= 1 ? 100 : y;
      scanLine.position.y = y; scanLine.material.opacity = state.scan < 1 ? 0.55 * (1 - k * 0.6) : 0;
      if (built?.explode && Math.abs(state.exploded - state.explodedGoal) > 0.001) { state.exploded += (state.explodedGoal - state.exploded) * (1 - Math.exp(-dt * 5)); built.explode(state.exploded); }
      if (built?.animate && state.playing) { animT += dt; built.animate(animT, dt); }
      if (built?.hud) $('projHud').textContent = built.hud(animT);
    }
    if (swapping?.old) { swapping.t = Math.min(1, swapping.t + dt / 0.38); clip.constant = (1 - swapping.t) * (modelHeight + 0.4); }
    beamU.uTime.value = t;
    motes.rotation.y += dt * 0.05;
    const p = motes.geometry.attributes.position;
    for (let i = 0; i < p.count; i++) { let yy = p.getY(i) + dt * 0.12; if (yy > 3.2) yy = 0; p.setY(i, yy); }
    p.needsUpdate = true;
    renderer.render(scene, camera);
    if (thumbNow && model) { thumbNow = false; saveThumb(model.userData.spec); window.__thumb = thumbs[keyOf(model.userData.spec)]; }
    if (thumbWanted && now > thumbWanted && model && state.scan >= 1) { thumbWanted = 0; if (!thumbs[keyOf(model.userData.spec)]) saveThumb(model.userData.spec); }
    placeLabels();
    raf = requestAnimationFrame(frame);
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !$('projLayer').hidden) start(); });

  // ---------- the window's interface (renderer.js calls these) ----------
  // ---------- every model shown is kept (across restarts), with a picture of it, for the gallery ----------
  const STORE = 'jarvis.projector.history', THUMBS = 'jarvis.projector.thumbs', KEEP = 40;
  const clean = (spec) => { const { update_only, followUp, ...rest } = spec; return rest; };
  const keyOf = (spec) => `${spec.title}|${spec.generator}|${JSON.stringify(spec.params || {})}`;
  let thumbs = {};
  try { thumbs = JSON.parse(localStorage.getItem(THUMBS) || '{}') || {}; } catch { thumbs = {}; }
  try { for (const s of JSON.parse(localStorage.getItem(STORE) || '[]')) if (s && s.title && s.generator) history.push(s); } catch { /* nothing saved yet */ }
  function save() {
    try { localStorage.setItem(STORE, JSON.stringify(history.slice(-KEEP).map(clean))); } catch { /* full or blocked: the gallery still works this session */ }
  }
  function saveThumb(spec) {
    // a small picture of the model as it stands now (the labels are drawn over the canvas, so they aren't in it)
    try {
      const c = document.createElement('canvas'), w = 320, h = 220; c.width = w; c.height = h;
      const src = renderer.domElement, sw = src.width, sh = src.height, crop = Math.min(sw / w, sh / h) * 0.86;
      c.getContext('2d').drawImage(src, (sw - w * crop) / 2, (sh - h * crop) / 2 - sh * 0.04, w * crop, h * crop, 0, 0, w, h);
      thumbs[keyOf(spec)] = c.toDataURL('image/webp', 0.78);
      const keys = Object.keys(thumbs); if (keys.length > 120) delete thumbs[keys[0]];
      localStorage.setItem(THUMBS, JSON.stringify(thumbs));
    } catch { /* the gallery falls back to the shipped pictures or a plain tile */ }
  }

  // ---------- the gallery: your models, and a library to open any time ----------
  let library = [];
  try { library = require('./projector/library.json'); } catch (error) { console.error('Projector: no library', error); }
  const GROUPS = [['all', 'All'], ['characters', 'Characters'], ['animals', 'Animals'], ['places', 'Places'], ['vehicles', 'Vehicles'], ['things', 'Things'], ['science', 'Science & nature']];
  const groupOf = (s) => ({ humanoid: 'characters', animal: 'animals', building: 'places', vehicle: 'vehicles', device: 'things', guitar: 'things', shoe: 'things', computer: 'things', engine: 'things' }[s.generator] || 'science');
  const shippedThumb = (s) => `projector/thumbs/${s.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}.webp`;
  let filter = 'all';
  function tile(spec, onOpen, removable) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'proj-tile';
    const pic = document.createElement('span'); pic.className = 'proj-thumb';
    const img = new Image(); img.alt = ''; img.decoding = 'async'; img.loading = 'lazy';
    img.src = thumbs[keyOf(spec)] || shippedThumb(spec);
    img.addEventListener('error', () => { img.remove(); pic.classList.add('is-empty'); pic.textContent = spec.title.slice(0, 1); }, { once: true });
    pic.append(img);
    const text = document.createElement('span'); text.className = 'proj-tile-text';
    const t = document.createElement('b'); t.textContent = spec.title;
    const sub = document.createElement('small'); sub.textContent = spec.summary || spec.kicker || '';
    text.append(t, sub); b.append(pic, text);
    b.title = `Open ${spec.title}`;
    b.addEventListener('click', onOpen);
    return b;
  }
  function renderGallery() {
    const recent = $('projRecent'); recent.replaceChildren();
    const seen = new Set(), mine = [];
    for (let i = history.length - 1; i >= 0; i--) { const k = keyOf(history[i]); if (!seen.has(k)) { seen.add(k); mine.push(i); } }
    for (const i of mine) recent.append(tile(history[i], () => present(i)));
    $('projRecentEmpty').hidden = mine.length > 0;
    const chips = $('projFilters'); chips.replaceChildren();
    for (const [id, label] of GROUPS) {
      const c = document.createElement('button'); c.type = 'button'; c.className = 'proj-chip'; c.textContent = label;
      c.setAttribute('aria-pressed', String(filter === id));
      c.addEventListener('click', () => { filter = id; renderGallery(); });
      chips.append(c);
    }
    const lib = $('projLibrary'); lib.replaceChildren();
    for (const spec of library.filter((s) => filter === 'all' || groupOf(s) === filter)) lib.append(tile(spec, () => window.showProjector({ ...spec, question: '' })));
  }
  function toggleGallery(on = $('projGallery').hidden) {
    if (on) renderGallery();
    $('projGallery').hidden = !on;
    $('projGalleryBtn').setAttribute('aria-pressed', String(on));
    if (on) $('projGallery').querySelector('button')?.focus({ preventScroll: true });
  }

  // ---------- the window's interface (renderer.js and the 3D button call these) ----------
  window.showProjector = function showProjector(spec) {
    if (spec.update_only && history.length) { history[history.length - 1] = clean({ ...history[history.length - 1], ...spec }); save(); present(history.length - 1, true); return; }
    history.push(spec);
    while (history.length > KEEP) history.shift();
    save();
    present(history.length - 1);
  };
  window.reopenProjector = function reopenProjector(which) {
    if (!history.length) return false;
    let i = current < 0 ? history.length - 1 : current;
    if (which === 'prev') i = Math.max(0, i - 1); else if (which === 'next') i = Math.min(history.length - 1, i + 1); else if (which === 'last') i = history.length - 1;
    if (i === current && !$('projLayer').hidden) return true;
    present(i);
    return true;
  };
  // the 3D button: the projector with the gallery open (the last model behind it, or the empty platform)
  window.openProjectorGallery = function openProjectorGallery() {
    if (history.length && current < 0) present(history.length - 1);
    else if (history.length) present(current);
    else {
      if (!renderer) setup();
      $('projLayer').hidden = false; document.body.classList.add('scene-paused');
      $('projKicker').textContent = '3D projector'; $('projTitle').textContent = 'Explore in 3D';
      $('projSummary').textContent = 'Open any model below, or ask Jarvis to show you something.';
      $('projNav').hidden = true;
      start();
    }
    toggleGallery(true);
  };
  window.hideProjector = function hideProjector() {
    $('projLayer').hidden = true;
    $('projGallery').hidden = true;
    $('projCard').classList.remove('is-full');
    document.body.classList.remove('scene-paused');
    cancelAnimationFrame(raf); raf = 0;
  };
  window.projectorOpen = () => !$('projLayer').hidden;
  window.projectorDebug = () => ({ radius: view.radius, goal: goal.radius, modelHeight, modelWidth, aspect: camera?.aspect, target: view.target.toArray(), phi: view.phi });
  // (a WebGL canvas can only be copied right after it's drawn, so the picture is taken in the next frame)
  window.projectorThumbNext = () => { thumbNow = true; window.__thumb = null; };
  document.addEventListener('DOMContentLoaded', () => {
    $('projGalleryBtn')?.addEventListener('click', () => toggleGallery());
    $('projOpenBtn')?.addEventListener('click', () => window.openProjectorGallery());
  });
  if (document.readyState !== 'loading') { $('projGalleryBtn')?.addEventListener('click', () => toggleGallery()); $('projOpenBtn')?.addEventListener('click', () => window.openProjectorGallery()); }
})();
