// Take Control in the window: what Jarvis is doing on the computer, as the engine reports it — the state, the goal,
// the step he is on, every step so far and whether it worked, the plan, a small picture of the screen he sees, a
// question waiting for your OK, and the checked result. It replaces the orb while control is on.
//
// Nothing here decides anything: it draws the engine's 'control', 'control_preview' and 'control_confirm' messages
// and sends the same commands as the sidebar, the overlay and voice. The window steps aside while a task runs (see
// main.js), so this is mostly read between tasks and after one; the overlay is what shows on top meanwhile.
//
// Talks to the rest of Jarvis only through the 'jarvis-message' event and window.jarvisSend (renderer.js).
(function () {
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const send = (payload) => Boolean(window.jarvisSend?.(payload));
  const deck = $('tcDeck');
  if (!deck) return;
  let ipcRenderer = null;
  try { ({ ipcRenderer } = require('electron')); } catch (_) { /* a plain browser page (tests) */ }
  const appShell = $('appShell');

  const ON = new Set(['starting', 'planning', 'observing', 'thinking', 'acting', 'verifying', 'waiting', 'paused',
    'cancelling', 'recovering', 'listening']);
  // [what the status chip says, its tone]
  const STATUS = {
    starting: ['Starting', 'run'], planning: ['Planning', 'plan'], observing: ['Observing', 'plan'], thinking: ['Thinking', 'plan'],
    acting: ['Acting', 'run'], verifying: ['Verifying', 'plan'], waiting: ['Waiting for approval', 'ask'],
    paused: ['Paused', 'pause'], cancelling: ['Stopping', 'pause'], recovering: ['Recovering', 'warn'],
    listening: ['Ready', 'run'], completed: ['Completed', 'ok'], error: ['Failed', 'bad'], stopped: ['Stopped', 'idle'],
  };
  const ICON = {
    ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    failed: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M7 7l10 10M17 7L7 17"/></svg>',
    nochange: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12a8 8 0 0 1 13.7-5.6L20 8.5M20 4v4.5h-4.5"/></svg>',
    declined: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 12h12"/></svg>',
    checked: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8"/><path d="M12 8v4.5M12 16v.01"/></svg>',
    live: '<i class="tc-spin"></i>',
  };
  const EXAMPLES = ['Open Notepad and type a shopping list', 'Search YouTube for lo-fi music', 'Turn on dark mode in Settings'];
  const STEP_WORDS = { ok: 'worked', failed: 'failed', nochange: 'changed nothing', declined: 'you said no', checked: 'checked' };

  let control = null;          // the engine's last 'control' report
  let preview = null;          // the last screen picture
  let askId = null;            // a yes/no question waiting in the deck
  let dismissed = false;       // a finished result the user closed
  let taskStarted = 0;         // when the current task began (this window's clock), for the elapsed time
  let lastGoal = '';

  const working = (state) => ON.has(state) && state !== 'listening';

  function render() {
    const state = control?.state || 'stopped';
    const on = ON.has(state);
    const steps = Array.isArray(control?.steps) ? control.steps : [];
    const finished = !on && Boolean(control?.goal) && steps.length > 0;   // a one-off task's result
    const show = on || (finished && !dismissed);
    deck.hidden = !show;
    appShell?.classList.toggle('tc-on', show);
    document.body.classList.toggle('orb-hidden', show);   // orb.js stops drawing what can't be seen
    syncLive();
    if (!show) return;

    const busy = working(state);
    // Between tasks in a session, the last task's ending is still worth showing (the engine says "listening" with
    // how that task ended in `outcome`).
    const ended = state === 'listening' && control.outcome ? control.outcome : (!on ? state : '');
    const [label, tone] = STATUS[state] || STATUS.stopped;
    $('tcStatusText').textContent = label;
    $('tcStatus').dataset.tone = tone;
    deck.dataset.tone = busy ? tone : ended ? (STATUS[ended] || STATUS.stopped)[1] : 'idle';
    deck.dataset.state = state;

    const goal = control.goal || '';
    if (busy && goal !== lastGoal) taskStarted = Date.now();
    if (goal) lastGoal = goal;
    const shownGoal = goal || (ended ? lastGoal : '');
    $('tcGoal').textContent = shownGoal || 'Ready for a task';
    $('tcGoal').classList.toggle('is-placeholder', !shownGoal);

    // Steps used out of the most this task may take: a budget, honestly labelled, not a guess at "% done".
    const max = Number(control.maxSteps) || 0;
    const step = Number(control.step) || 0;
    $('tcProgress').hidden = !busy || !max;
    $('tcProgressBar').style.width = `${max ? Math.min(100, (step / max) * 100) : 0}%`;
    $('tcProgress').setAttribute('aria-valuenow', String(max ? step / max : 0));
    renderMeta();

    const now = $('tcNow');
    // While working, the step under way is the last line of the step list; paused or asking, it is said here.
    const live = busy && !['paused', 'waiting', 'cancelling'].includes(state);
    now.textContent = busy ? (live ? '' : control.detail || label) : state === 'listening' && !ended ? 'Tell Jarvis what to do: type below, or just say it.' : '';
    now.hidden = !now.textContent;

    // The result: the engine's own words, and whether the screen check confirmed it.
    const result = $('tcResult');
    result.hidden = busy || !ended || !control.detail;
    if (!result.hidden) {
      result.dataset.tone = (STATUS[ended] || STATUS.stopped)[1];
      result.querySelector('.tc-result-ic').innerHTML = ended === 'completed' ? ICON.ok : ended === 'error' ? ICON.failed : ICON.declined;
      $('tcResultText').textContent = control.detail;
      const check = $('tcCheck');
      // Only when the screen check ran (plain on-screen tasks); a build says in its own words what it checked.
      check.hidden = ended !== 'completed' || typeof control.verified !== 'boolean';
      check.textContent = control.verified ? 'Checked on screen' : 'Not confirmed on screen';
      check.dataset.ok = String(control.verified === true);
    }

    renderPlan(Array.isArray(control.plan) ? control.plan : []);
    renderSteps(steps, live);
    renderPreview();

    // Buttons: only what applies right now.
    $('tcPause').hidden = !busy || state === 'cancelling';
    $('tcPause').textContent = state === 'paused' ? 'Resume' : 'Pause';
    $('tcCancel').hidden = !busy || state === 'cancelling';
    $('tcEnd').hidden = !on;
    $('tcClose').hidden = on;
    $('tcForm').hidden = state === 'cancelling';
    $('tcRun').textContent = on ? (busy ? 'Replace task' : 'Run task') : 'Take control';
    $('tcInput').placeholder = busy ? 'A new task replaces this one…' : 'Give Jarvis a task…';
  }

  function renderMeta() {
    const state = control?.state || 'stopped';
    const parts = [];
    if (working(state) && Number(control.maxSteps) && control.step) parts.push(`Step ${control.step || 0} of up to ${control.maxSteps}`);
    if (working(state) && taskStarted) {
      const s = Math.max(0, Math.round((Date.now() - taskStarted) / 1000));
      parts.push(`${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`);
    }
    $('tcMeta').textContent = parts.join(' · ');
  }

  let planTouched = false;
  $('tcPlanWrap').querySelector('summary').addEventListener('click', () => { planTouched = true; });   // keys click it too
  function renderPlan(plan) {
    $('tcPlanWrap').hidden = !plan.length;
    if (!planTouched) $('tcPlanWrap').open = !(control?.steps || []).length;
    const list = $('tcPlan');
    if (list.dataset.key === JSON.stringify(plan)) return;
    list.dataset.key = JSON.stringify(plan);
    list.replaceChildren(...plan.map((text) => el('li', '', text)));
  }

  function stepItem(status, text, note, n) {
    const li = el('li', 'tc-step');
    li.dataset.status = status;
    const ic = el('span', 'tc-step-ic');
    ic.innerHTML = ICON[status] || ICON.checked;
    ic.setAttribute('aria-hidden', 'true');
    const body = el('div', 'tc-step-body');
    body.append(el('b', '', text));
    if (note) body.append(el('small', '', note));
    if (n) li.append(el('span', 'tc-step-n', String(n)));
    li.append(ic, body);
    li.setAttribute('aria-label', `${n ? `Step ${n}: ` : ''}${text}${STEP_WORDS[status] ? `, ${STEP_WORDS[status]}` : ''}`);
    return li;
  }

  function renderSteps(steps, live) {
    const list = $('tcSteps');
    const items = steps.map((s) => stepItem(s.status, s.text, s.note, s.n));
    // The step under way, as the engine describes it right now.
    if (live && control.detail) items.push(stepItem('live', control.detail, '', 0));
    const atEnd = list.scrollHeight - list.scrollTop - list.clientHeight < 24;
    list.replaceChildren(...items);
    if (atEnd) list.scrollTop = list.scrollHeight;
    $('tcEmpty').hidden = items.length > 0;
    $('tcExamples').hidden = working(control?.state);
    $('tcNotes').hidden = !steps.length;
  }

  // The live view (live.js) runs while the panel can be seen; the engine's still pictures are the fallback where the
  // screen can't be captured. While it shows, this window is kept out of screen captures (main.js), so the view shows
  // the desktop behind it instead of itself, over and over.
  let liveOn = false;
  let liveWanted = false;
  function syncLive() {
    const want = !deck.hidden && document.visibilityState === 'visible';
    if (want === liveWanted) return;
    liveWanted = want;
    try { ipcRenderer?.send('tc-capture-hidden', want); } catch (_) { /* not inside Electron */ }
    const video = $('tcLive');
    if (!want) {
      window.LiveScreen?.stop(video);
      liveOn = false;
      renderPreview();
      return;
    }
    window.LiveScreen?.start(video).then((ok) => {
      liveOn = ok && liveWanted;
      if (!liveWanted) window.LiveScreen.stop(video);
      renderPreview();
    });
  }
  document.addEventListener('visibilitychange', syncLive);

  function renderPreview() {
    const img = $('tcShot');
    const has = !liveOn && Boolean(preview?.image);
    $('tcLive').hidden = !liveOn;
    $('tcLiveTag').hidden = !liveOn;
    img.hidden = !has;
    $('tcShotEmpty').hidden = has || liveOn;
    if (has && img.getAttribute('src') !== preview.image) img.src = preview.image;
    const target = liveOn && control?.state === 'acting' ? control.target : null;
    if (target) window.LiveScreen.placeTarget($('tcTarget'), $('tcLive'), target);
    else $('tcTarget').hidden = true;
    const app = control?.app || preview?.app || '';
    const win = control?.window || preview?.window || '';
    $('tcApp').textContent = app ? `${app}${win && win !== app ? ` — ${win}` : ''}` : 'No app yet';
    $('tcApp').title = $('tcApp').textContent;
    img.alt = app ? `The screen Jarvis sees, with ${app} in front` : 'The screen Jarvis sees';
    renderAge();
  }

  function renderAge() {
    if (liveOn || !preview?.at) { $('tcAge').textContent = ''; return; }   // the live view is always "now"
    const s = Math.max(0, Math.round(Date.now() / 1000 - preview.at));
    $('tcAge').textContent = s < 3 ? 'just now' : s < 60 ? `${s} s ago` : `${Math.round(s / 60)} min ago`;
  }

  function showAsk(message) {
    askId = message.id;
    $('tcAskText').textContent = message.question;
    $('tcAsk').hidden = false;
  }
  function hideAsk(id) {
    if (id && id !== askId) return;
    askId = null;
    $('tcAsk').hidden = true;
  }
  function answer(allow) {
    if (askId) send({ type: 'control_answer', id: askId, allow });
    hideAsk();
  }

  window.addEventListener('jarvis-message', (event) => {
    const data = event.detail || {};
    if (data.type === 'control' && data.data) {
      const was = control?.state;
      control = data.data;
      if (ON.has(control.state) && !ON.has(was || 'stopped')) dismissed = false;
      if (control.goal && control.goal !== lastGoal) planTouched = false;
      if (control.state !== 'waiting') hideAsk();
      render();
    } else if (data.type === 'control_preview' && data.data) {
      preview = data.data;
      if (!deck.hidden) renderPreview();
    } else if (data.type === 'control_confirm') {
      // Asked mid-task (a risky step): answerable here as well as on the overlay and by voice.
      if (working(control?.state)) showAsk(data);
    } else if (data.type === 'control_confirm_done') {
      hideAsk(data.id);
    }
  });

  $('tcForm').addEventListener('submit', (event) => {
    event.preventDefault();
    const goal = $('tcInput').value.trim();
    if (!goal) { $('tcInput').focus(); return; }
    if (send({ type: 'control_command', action: 'task', goal })) {
      $('tcInput').value = '';
      dismissed = false;
    }
  });
  // Examples fill the task box (nothing runs until Run task): a start for someone who hasn't used this yet.
  $('tcExamples').replaceChildren(...EXAMPLES.map((text) => {
    const b = el('button', 'tc-example', text);
    b.type = 'button';
    b.addEventListener('click', () => { $('tcInput').value = text; $('tcInput').focus(); });
    return b;
  }));
  $('tcPause').addEventListener('click', () => send({ type: 'control_command', action: control?.state === 'paused' ? 'resume' : 'pause' }));
  $('tcCancel').addEventListener('click', () => send({ type: 'control_command', action: 'cancel' }));
  $('tcEnd').addEventListener('click', () => send({ type: 'control_command', action: 'release' }));
  $('tcClose').addEventListener('click', () => { dismissed = true; render(); });
  $('tcAllow').addEventListener('click', () => answer(true));
  $('tcDeny').addEventListener('click', () => answer(false));
  $('tcNotes').addEventListener('click', () => {
    const on = !$('tcSteps').classList.contains('show-notes');
    $('tcSteps').classList.toggle('show-notes', on);
    $('tcNotes').setAttribute('aria-pressed', String(on));
    $('tcNotes').textContent = on ? 'Hide details' : 'Show details';
  });
  setInterval(() => { if (!deck.hidden) { renderMeta(); renderAge(); } }, 1000);
})();
