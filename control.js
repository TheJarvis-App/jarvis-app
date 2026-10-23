// The overlay shown while Jarvis uses the mouse and keyboard: what he is doing (observing, thinking, acting), a live
// view of the screen with what he is acting on, where his next click goes on the real screen, and how to stop him.
const ACTIVE = new Set(['starting', 'planning', 'observing', 'thinking', 'acting', 'verifying', 'waiting', 'paused',
  'cancelling', 'recovering', 'listening']);
const BADGE = {
  starting: 'Starting', planning: 'Planning', observing: 'Observing', thinking: 'Thinking', acting: 'Acting',
  verifying: 'Checking the result', cancelling: 'Stopping…', recovering: 'Recovering', paused: 'Paused — your turn',
  listening: 'Ready — listening',
};
const LAST_WORDS = { ok: '✓ Worked', failed: '✕ Failed', nochange: '↻ No change', declined: '– Skipped' };
const ENDED_BADGE = { completed: 'Done', stopped: 'Stopped', error: 'Stopped' };
const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
$('shortcut').textContent = params.get('shortcut') || 'Ctrl+Alt+Q';

let state = 'starting';
let questionId = null;
let since = 0;        // when the current state began (engine clock), so a long step shows it is still running
let lastStep = '';
let target = null;    // what is being acted on: {rect, screen} in screen pixels
let ringTimer = null;
let viewWanted = true;
try { viewWanted = localStorage.getItem('tc-overlay-view') !== 'off'; } catch (_) { /* keep the default */ }

function badgeText() {
  if (questionId) return 'Needs your OK';
  if (BADGE[state]) return BADGE[state];
  return ENDED_BADGE[state] || 'Stopped';
}

// The live view runs only while Jarvis is working and it is wanted: between commands, paused, or after the end
// there is nothing to watch that isn't on the screen itself.
function syncView() {
  const working = ACTIVE.has(state) && !['listening', 'paused'].includes(state);
  $('view').hidden = !viewWanted || !working;
  $('toggleView').textContent = viewWanted ? 'Hide view' : 'Show view';
  $('toggleView').setAttribute('aria-pressed', String(viewWanted));
  const video = $('video');
  if (viewWanted && working) {
    window.LiveScreen.start(video).then((ok) => {
      $('noView').hidden = ok;
      $('liveTag').hidden = !ok;
    });
  } else if (video.srcObject) {
    window.LiveScreen.stop(video);
    $('liveTag').hidden = true;
  }
}

function render(data) {
  state = data.state || state;
  document.body.dataset.state = state;
  const active = ACTIVE.has(state);
  document.body.toggleAttribute('data-ended', !active);
  $('badge').textContent = badgeText();
  if (!questionId) $('detail').textContent = data.detail || '';
  const where = data.app ? ` · in ${data.app}` : '';
  lastStep = active && data.step ? `Step ${data.step} of ${data.maxSteps}${where}` : (data.goal || '');
  $('meta').textContent = active && data.goal ? data.goal : '';
  $('meta').title = data.goal || '';
  // How the step before this one went, while working: a failure or a no-change is why Jarvis is recovering.
  const done = Array.isArray(data.steps) && data.steps.length ? data.steps[data.steps.length - 1] : null;
  const working = active && !['listening', 'paused'].includes(state);
  $('last').hidden = !working || !done || !LAST_WORDS[done.status];
  if (done && LAST_WORDS[done.status]) { $('last').textContent = LAST_WORDS[done.status]; $('last').dataset.status = done.status; $('last').title = done.text; }
  $('progress').hidden = !working || !data.maxSteps;
  $('progressBar').style.width = `${data.maxSteps ? Math.min(100, (100 * (data.step || 0)) / data.maxSteps) : 0}%`;
  since = Number(data.since) || Date.now() / 1000;
  tick();
  $('pause').textContent = state === 'paused' ? 'Resume' : 'Pause';
  $('pause').hidden = state === 'listening' || state === 'cancelling';   // nothing to pause between commands
  // Inside a "take control" session: Cancel ends this task only; Stop ends control altogether.
  $('cancel').hidden = !data.session || ['listening', 'cancelling'].includes(state);
  $('stopLabel').textContent = data.session ? 'End control' : 'Stop';
  $('controls').hidden = !active || Boolean(questionId);
  $('taskForm').hidden = !active || state === 'cancelling';
  $('taskInput').placeholder = state === 'listening' ? 'Tell Jarvis what to do…' : 'New task… (replaces this one)';
  showTarget(state === 'acting' ? data.target : null);
  syncView();
}

// The ring on the real screen and the box on the live view stay a moment after the action, so the eye can follow.
function showTarget(next) {
  if (next?.rect) {
    clearTimeout(ringTimer);
    target = next;
    const ring = $('ring');
    const dpr = window.devicePixelRatio || 1;
    const [x, y, w, h] = next.rect;
    ring.style.left = `${x / dpr - window.screenX - 4}px`;
    ring.style.top = `${y / dpr - window.screenY - 4}px`;
    ring.style.width = `${w / dpr + 8}px`;
    ring.style.height = `${h / dpr + 8}px`;
    ring.hidden = false;
    ring.classList.remove('fade');
    window.LiveScreen.placeTarget($('box'), $('video'), target);
  } else if (target && !ringTimer) {
    ringTimer = setTimeout(() => {
      ringTimer = null;
      target = null;
      $('ring').classList.add('fade');
      $('box').hidden = true;
    }, 1200);
  }
}

// Seconds on the current step, once it has taken a while: running, not frozen.
function tick() {
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - since));
  const working = ACTIVE.has(state) && !['listening', 'paused'].includes(state);
  $('step').textContent = lastStep + (working && seconds >= 5 ? `${lastStep ? ' · ' : ''}${seconds} s` : '');
}
setInterval(tick, 1000);

function ask(message) {
  questionId = message.id;
  $('badge').textContent = badgeText();
  $('detail').textContent = message.question;
  $('question').hidden = false;
  $('controls').hidden = true;
}

function unask(message) {
  if (message.id && message.id !== questionId) return;
  questionId = null;
  $('badge').textContent = badgeText();
  $('question').hidden = true;
  $('controls').hidden = !ACTIVE.has(state);
}

window.control.onEvent((message) => {
  if (message.type === 'control') render(message.data || {});
  else if (message.type === 'control_confirm') ask(message);
  else if (message.type === 'control_confirm_done') unask(message);
});

$('pause').addEventListener('click', () => window.control.act(state === 'paused' ? 'resume' : 'pause'));
$('stop').addEventListener('click', () => window.control.act('stop'));
$('cancel').addEventListener('click', () => window.control.act('cancel'));
$('allow').addEventListener('click', () => { if (questionId) window.control.answer(questionId, true); unask({}); });
$('deny').addEventListener('click', () => { if (questionId) window.control.answer(questionId, false); unask({}); });
$('toggleView').addEventListener('click', () => {
  viewWanted = !viewWanted;
  try { localStorage.setItem('tc-overlay-view', viewWanted ? 'on' : 'off'); } catch (_) { /* this time only */ }
  syncView();
});
$('video').addEventListener('loadedmetadata', () => { if (target) window.LiveScreen.placeTarget($('box'), $('video'), target); });
$('taskForm').addEventListener('submit', (event) => {
  event.preventDefault();
  const goal = $('taskInput').value.trim();
  if (!goal) return;
  window.control.task(goal);
  $('taskInput').value = '';
  $('taskInput').blur();
});

// The window lets clicks pass through to the apps underneath, except over the card itself (and while a task is being
// typed into it, so the keys reach the box).
let overCard = false;
let typing = false;
const syncHover = () => window.control.hovering(overCard || typing);
$('card').addEventListener('mouseenter', () => { overCard = true; syncHover(); });
$('card').addEventListener('mouseleave', () => { overCard = false; syncHover(); });
$('taskInput').addEventListener('focus', () => { typing = true; syncHover(); });
$('taskInput').addEventListener('blur', () => { typing = false; syncHover(); });
