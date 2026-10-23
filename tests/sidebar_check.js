// tests/sidebar_check.py's harness. Drives the real Jarvis window (index.html + renderer.js + panels.js) against an
// isolated engine: real mouse clicks and key presses on the sidebar, screenshots, and a log of what the engine sent
// back. No main.js, so no always-on-top overlay and no window minimizing on the user's desktop.
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs');
const path = require('path');

const REPO = process.env.REPO;
const OUT = process.env.OUT;
const WS_URL = process.env.WS_URL;
const results = { checks: [], seen: [], notes: [] };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let win;

function check(name, ok, detail) {
  results.checks.push({ name, ok: Boolean(ok), detail });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' — ' + JSON.stringify(detail) : ''}`);
}
const js = (code) => win.webContents.executeJavaScript(code);
async function shot(name) {
  const image = await win.webContents.capturePage();
  fs.writeFileSync(path.join(OUT, `${name}.png`), image.toPNG());
}
async function rect(id) {
  return js(`(() => { const r = document.getElementById(${JSON.stringify(id)}).getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height}; })()`);
}
async function click(id) {   // a real mouse click at the element's centre
  const r = await rect(id);
  const at = { x: Math.round(r.x), y: Math.round(r.y) };
  const under = await js(`(document.elementFromPoint(${at.x}, ${at.y}) || {}).closest?.('button')?.id || ''`);
  if (under !== id) results.notes.push({ clickBlocked: id, under });
  win.webContents.sendInputEvent({ type: 'mouseMove', ...at });
  win.webContents.sendInputEvent({ type: 'mouseDown', button: 'left', clickCount: 1, ...at });
  win.webContents.sendInputEvent({ type: 'mouseUp', button: 'left', clickCount: 1, ...at });
  await sleep(120);
}
async function key(keyCode) {
  win.webContents.sendInputEvent({ type: 'keyDown', keyCode });
  if (keyCode.length === 1) win.webContents.sendInputEvent({ type: 'char', keyCode });
  win.webContents.sendInputEvent({ type: 'keyUp', keyCode });
  await sleep(150);
}
const side = () => js(`({ mic: document.getElementById('scMicState').textContent,
  micPressed: document.getElementById('scMic').getAttribute('aria-pressed'),
  micDisabled: document.getElementById('scMic').disabled,
  dockPressed: document.getElementById('connectBtn').getAttribute('aria-pressed'),
  control: document.getElementById('scControlState').textContent,
  controlLabel: document.querySelector('#scControl .sc-label').textContent,
  controlDisabled: document.getElementById('scControl').disabled,
  taskShown: !document.getElementById('scTask').hidden,
  detail: document.getElementById('scDetail').textContent,
  pause: document.getElementById('scPause').hidden ? null : document.getElementById('scPause').textContent,
  cancel: !document.getElementById('scCancel').hidden,
  status: document.getElementById('scStatusText').textContent,
  tone: document.getElementById('scStatus').dataset.tone })`);
const deck = () => js(`({ shown: !document.getElementById('tcDeck').hidden,
  status: document.getElementById('tcStatusText').textContent, goal: document.getElementById('tcGoal').textContent,
  steps: document.querySelectorAll('#tcSteps .tc-step:not([data-status="live"])').length,
  result: document.getElementById('tcResult').hidden ? '' : document.getElementById('tcResultText').textContent,
  tone: document.getElementById('tcResult').dataset.tone || '',
  cancel: !document.getElementById('tcCancel').hidden, orb: getComputedStyle(document.getElementById('orbWrap')).display })`);
async function waitDeck(predicate, ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const d = await deck();
    if (predicate(d)) return d;
    await sleep(80);
  }
  return deck();
}
const engineLog = () => js('window.__log.splice(0)');
async function waitFor(predicate, ms, every = 60) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const s = await side();
    if (predicate(s)) return s;
    await sleep(every);
  }
  return side();
}
async function watch(ms, every = 50) {   // every distinct sidebar state shown for `ms`
  const end = Date.now() + ms;
  const states = [];
  while (Date.now() < end) {
    const s = await side();
    const label = `${s.control}|${s.taskShown ? 'task' : '-'}|${s.pause || '-'}|${s.cancel ? 'cancel' : '-'}`;
    if (states[states.length - 1] !== label) states.push(label);
    await sleep(every);
  }
  return states;
}
async function sendTyped(text) {
  await click('typeInput');
  await win.webContents.insertText(text);
  await sleep(150);
  const typed = await js("document.getElementById('typeInput').value");
  if (typed !== text) results.notes.push({ typedGot: typed });
  win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Enter' });
  win.webContents.sendInputEvent({ type: 'char', keyCode: '\r' });
  win.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Enter' });
  await sleep(300);
  const left = await js("document.getElementById('typeInput').value");
  if (left) {   // not sent by Enter: press the Send button, as a user would
    await click('typeSend');
    results.notes.push({ enterDidNotSend: left });
  }
}

async function scenario() {
  await js("window.__log = []; window.addEventListener('jarvis-message', (e) => window.__log.push(e.detail));");
  // 1. connects, starts from the engine's real state
  let s = await waitFor((x) => !x.micDisabled, 90000, 300);
  check('sidebar enables once the engine is connected', !s.micDisabled && !s.controlDisabled, s);
  await sleep(2500);   // the boot animation
  win.focus();
  win.webContents.focus();
  // A fresh data folder is a first run: its Welcome dialog covers the window. Dismiss it as a user would.
  const welcome = await js("!document.getElementById('welcomeLayer').hidden");
  if (welcome) {
    await click('welcomeSkip');
    await sleep(800);
    results.notes.push({ welcomeDismissedByClick: await js("document.getElementById('welcomeLayer').hidden") });
  }
  await shot('01-connected');
  check('audio-off engine shows the microphone as unavailable, not as listening', s.mic === 'Unavailable' || (await side()).mic === 'Unavailable', await side());

  // 2. layout: anchored at the bottom, list scrolls, no horizontal overflow
  const layout = await js(`(() => { const col = document.querySelector('.col-left').getBoundingClientRect();
    const sc = document.getElementById('sideControls').getBoundingClientRect();
    const ul = document.getElementById('tipList');
    const left = document.querySelector('.col-left');
    return { colBottom: col.bottom, scBottom: sc.bottom, scTop: sc.top, scHeight: sc.height,
      listScrolls: ul.scrollHeight > ul.clientHeight, listOverflow: getComputedStyle(ul).overflowY,
      hOverflow: left.scrollWidth > left.clientWidth + 1, colHeight: col.height }; })()`);
  check('controls sit at the bottom of the rail', Math.abs(layout.colBottom - layout.scBottom) < 24, layout);
  check('the list above scrolls instead of pushing the controls off', layout.listOverflow === 'auto', layout);
  check('no horizontal overflow in the rail', !layout.hOverflow, layout);
  check('the section is compact', layout.scHeight < 200, layout.scHeight);

  // 3. microphone: a real click mutes, the engine echoes what it applied, the dock follows
  await engineLog();
  await click('scMic');
  s = await waitFor((x) => x.mic === 'Off', 3000);
  await sleep(600);
  const echoes = (await engineLog()).filter((m) => m.type === 'mic_state');
  check('clicking the sidebar mic mutes', s.mic === 'Off' && s.micPressed === 'true', s);
  check('the dock mic button shows the same state', s.dockPressed === 'true', s.dockPressed);
  check('the engine confirms the listening loop is muted', echoes.some((m) => m.data.muted === true), echoes);
  await shot('02-muted');
  // keyboard: focus + Space toggles back
  await js("document.getElementById('scMic').focus()");
  await key('Space');
  s = await waitFor((x) => x.micPressed === 'false', 3000);
  await sleep(600);
  const echoes2 = (await engineLog()).filter((m) => m.type === 'mic_state');
  check('Space on the focused mic button unmutes (keyboard works)', s.micPressed === 'false', s);
  check('the engine confirms it is listening again', echoes2.some((m) => m.data.muted === false), echoes2);
  const focusRing = await js("getComputedStyle(document.getElementById('scMic'), ':focus-visible').outlineStyle || ''");
  results.notes.push({ focusRing });

  // 4. Take control: asks first (Settings say "ask"), then a session that waits
  await click('scControl');
  const asked = await js("(async () => { for (let i = 0; i < 60; i++) { if (!document.getElementById('controlLayer').hidden) return true; await new Promise(r => setTimeout(r, 100)); } return false; })()");
  check('Take control asks for permission first', asked);
  await shot('03-asks-permission');
  await click('controlAllow');
  s = await waitFor((x) => x.control === 'On · waiting', 8000);
  check('after Allow the session is on and waiting', s.control === 'On · waiting' && s.controlLabel === 'End control', s);
  let d = await deck();
  check('the Take Control panel takes the place of the orb, ready for a task', d.shown && d.status === 'Ready' && d.orb === 'none', d);
  await shot('04-session-waiting');

  // 5. a long build inside the session: progress, then the session stays
  await sendTyped('create a villa in blender');
  const states = await watch(30000);
  results.seen.push({ build: states });
  s = await side();
  check('the build showed working states with Pause and Cancel', states.some((x) => x.includes('|task|Pause|cancel')), states);
  check('after the build the session is still on (completing a task never ends control)', s.control === 'On · waiting', s);
  const chat = await js("[...document.querySelectorAll('#chatLog .msg.jarvis')].map(m => m.textContent).join('\\n')");
  check('the chat reports a checked, finished build', /all \d+ requirements hold/.test(chat), chat.slice(-400));
  d = await deck();
  check('the panel shows the finished build: its steps and its result', d.steps >= 5 && d.tone === 'ok' && /requirements hold/.test(d.result), d);
  await shot('05-after-build');

  // 6. cancel a task: the session stays
  await sendTyped('build me a three storey mansion with a garden, a pool and a garage in blender');
  s = await waitFor((x) => x.taskShown && x.cancel, 15000, 20);
  check('a running task offers Cancel task', s.taskShown && s.cancel, s);
  await shot('06-working');
  await click('scCancel');
  const after = await watch(8000);
  s = await side();
  results.seen.push({ cancel: after });
  check('Cancel stops the task', !s.taskShown, after);
  check('Cancel keeps the session (control not released)', s.control === 'On · waiting', s);
  await shot('07-cancelled-still-in-control');

  // 7. pause and resume, and muting during a task neither pauses nor cancels it
  await sendTyped('build a cozy cottage in blender');
  s = await waitFor((x) => x.taskShown && x.pause === 'Pause', 15000, 20);
  await click('scPause');
  s = await waitFor((x) => x.control === 'Paused', 5000, 30);
  check('Pause pauses the running task', s.control === 'Paused' && s.pause === 'Resume', s);
  await shot('08-paused');
  await click('scMic');   // mute while paused: must not cancel or resume anything
  await sleep(800);
  s = await side();
  check('muting while a task is paused leaves it paused (mute is not pause or cancel)', s.control === 'Paused' && s.mic === 'Off', s);
  await click('scPause');   // resume
  s = await waitFor((x) => x.control === 'On · waiting', 30000);
  check('Resume carries the task on to the end, session still on', s.control === 'On · waiting', s);
  await click('scMic');   // unmute again
  await sleep(500);

  // 8. a task typed into the panel, cancelled from the panel
  await click('tcInput');
  await win.webContents.insertText('build a small cabin in blender');
  await click('tcRun');
  d = await waitDeck((x) => x.cancel && /cabin/.test(x.goal), 15000);
  check('a task typed into the panel runs, with Cancel at hand', d.cancel && /cabin/.test(d.goal), d);
  await shot('08b-panel-task');
  await click('tcCancel');
  d = await waitDeck((x) => !x.cancel && x.status === 'Ready', 10000);
  s = await side();
  check('Cancel in the panel stops the task and keeps control', !d.cancel && d.status === 'Ready' && s.control === 'On · waiting', { d, s });

  // 9. End control
  await click('scControl');
  s = await waitFor((x) => x.control === 'Off', 5000);
  check('End control releases the session', s.control === 'Off' && s.controlLabel === 'Take control', s);
  d = await deck();
  check('the panel goes away and the orb comes back', !d.shown && d.orb !== 'none', d);
  await shot('09-released');

  // 9. classic look and a narrow window keep working
  await js("localStorage.setItem('jarvis-look', 'classic')");
  win.webContents.reload();
  await sleep(1500);
  await js("window.__log = []; window.addEventListener('jarvis-message', (e) => window.__log.push(e.detail));");
  s = await waitFor((x) => !x.micDisabled, 20000, 200);
  await sleep(2500);
  await shot('10-classic-look');
  const classic = await js(`(() => { const col = document.querySelector('.col-left').getBoundingClientRect();
    const sc = document.getElementById('sideControls').getBoundingClientRect(); return { colBottom: col.bottom, scBottom: sc.bottom,
    hOverflow: document.querySelector('.col-left').scrollWidth > document.querySelector('.col-left').clientWidth + 1 }; })()`);
  check('classic look: controls at the bottom, no overflow', Math.abs(classic.colBottom - classic.scBottom) < 24 && !classic.hOverflow, classic);
  await js("localStorage.removeItem('jarvis-look')");
  win.setSize(1000, 760);
  await sleep(800);
  const hidden = await js("getComputedStyle(document.querySelector('.col-left')).display");
  check('a narrow window hides the rail as before (the dock mic stays)', hidden === 'none', hidden);
  win.setSize(1280, 820);
  win.webContents.reload();
  await sleep(1500);
  s = await waitFor((x) => !x.micDisabled, 20000, 200);
  await sleep(2500);

  // 10. the engine goes away: the sidebar says so and disables its buttons
  fs.writeFileSync(path.join(OUT, 'kill-engine'), '');
  s = await waitFor((x) => x.micDisabled, 20000, 200);
  check('engine gone: status says disconnected, buttons disabled', s.micDisabled && s.controlDisabled && /Disconnected/.test(s.status), s);
  await shot('11-disconnected');
}

app.whenReady().then(async () => {
  ipcMain.on('control-event', () => {});
  win = new BrowserWindow({ width: 1280, height: 820, show: true, backgroundColor: '#02040a',
    webPreferences: { contextIsolation: false, nodeIntegration: true } });
  win.loadFile(path.join(REPO, 'index.html'), { query: { ws: WS_URL } });
  await new Promise((r) => win.webContents.once('did-finish-load', r));
  try {
    await scenario();
  } catch (error) {
    results.error = String(error && error.stack || error);
    console.log('ERROR', results.error);
    try { await shot('99-error'); } catch (e) { /* window gone */ }
  }
  fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 1));
  app.quit();
});
