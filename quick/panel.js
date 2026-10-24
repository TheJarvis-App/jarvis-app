// The Quick Access bar's page. It talks to the same Jarvis engine as the main window, over its own connection: what
// you type goes in as typed text, the microphone asks the engine to listen now, and the engine's answers, states and
// visuals arrive here as they do there. Nothing is answered here: every request goes through the real Jarvis.
(function () {
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const WIN = params.get('platform') === 'win32';
  document.body.dataset.platform = WIN ? 'win' : 'mac';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const MARGIN = 26;
  const CONTROL_ACTIVE = new Set(['starting', 'observing', 'thinking', 'acting', 'waiting', 'paused', 'listening']);
  const VISUALS = { projector: '3D model', graph: 'graph', globe: 'globe', planet: 'planet' };
  const STATES = {
    idle: 'Ready', sleeping: 'Ready', listening: 'Listening', thinking: 'Thinking', generating: 'Thinking',
    speaking: 'Speaking', muted: 'Microphone off', offline: 'Connecting to Jarvis…',
  };

  let socket = null, connected = false, state = 'idle', open = false, config = { input: 'text', stay: false, label: '' };
  let waitingFor = null;      // a request from the bar that hasn't been answered yet: { text, at }
  let listenAsked = 0;        // when the microphone was asked for (the engine says "listening" a moment later)
  let lastVisual = '';
  let shownAt = 0;
  const outbox = [];
  const ask = $('ask'), answer = $('answer');

  // ---------- the connection ----------
  function connect() {
    try {
      socket = new WebSocket(params.get('ws'));
    } catch (error) { setTimeout(connect, 1500); return; }
    socket.onopen = () => {
      connected = true;
      if (open) send({ type: 'quick_visibility', visible: true });
      if (open && document.body.classList.contains('menubar') && !outbox.some((m) => m.type === 'quick_menubar')) send({ type: 'quick_menubar' });
      while (outbox.length) socket.send(JSON.stringify(outbox.shift()));
      setState(state === 'offline' ? 'idle' : state);
    };
    socket.onclose = () => { connected = false; setState('offline'); setTimeout(connect, 1200); };
    socket.onerror = () => {};
    socket.onmessage = (event) => { try { onMessage(JSON.parse(event.data)); } catch (error) { console.error(error); } };
  }
  function send(payload, queue = false) {
    if (connected && socket.readyState === WebSocket.OPEN) { socket.send(JSON.stringify(payload)); return true; }
    if (queue) outbox.push(payload);
    return false;
  }

  function onMessage(data) {
    if (data.type === 'quick_toggle') { window.quick.toggle(data.source); return; }   // the engine saw the double press
    if (data.type === 'quick_menubar') { window.quick.menubar(data.data || {}); return; }
    if (data.status) setState(data.status);
    if (data.type === 'quick_notice') showNotice(data.text, data.kind === 'muted' ? ['Turn the microphone on', () => { send({ type: 'unmute' }); hideNotice(); startListening(); }] : null);
    if (data.type === 'mic' && data.data && !data.data.ok && data.data.message && open) showNotice(data.data.message);
    if (data.type === 'control' && data.data && CONTROL_ACTIVE.has(data.data.state) && open) window.quick.hide();   // out of the way of Jarvis's clicks
    if (VISUALS[data.type] && data.data && (waitingFor || open)) attachVisual(data.type);
    if (data.sender && (data.text || data.image) && (waitingFor || open)) addTurn(data.sender === 'user' ? 'you' : 'jarvis', data.text || '', data.image);
  }

  // ---------- state ----------
  function setState(next) {
    if (!connected && next !== 'offline') next = 'offline';
    if (next === 'sleeping') next = 'idle';
    state = next;
    document.body.dataset.state = next;
    $('statusText').textContent = next === 'idle' && listenAsked && Date.now() - listenAsked < 4000 ? 'Starting to listen…' : STATES[next] || 'Ready';
    const busy = ['listening', 'thinking', 'generating', 'speaking'].includes(next);
    $('stop').hidden = !busy;
    $('mic').setAttribute('aria-pressed', String(next === 'listening'));
    $('mic').disabled = next === 'offline';
    $('mic').title = next === 'listening' ? 'Stop listening' : `Talk to Jarvis (${WIN ? 'Ctrl' : '⌘'} L)`;
    if (next === 'listening') { listenAsked = 0; startMeter(); } else stopMeter();
    if (next === 'thinking' || next === 'generating') showTyping(); else hideTyping();
    if (inBar()) {
      if (next === 'listening') showLine('Listening…', 'listening');
      else if (next === 'thinking' || next === 'generating') showLine('Thinking…', 'thinking');
      else if (next === 'offline') showLine('Connecting to Jarvis…', 'notice');
      else if (lineKind === 'listening' || lineKind === 'thinking' || (lineKind === 'notice' && next !== 'offline')) hideLine();
    }
    if ((next === 'idle' || next === 'speaking') && waitingFor && answer.querySelector('.turn.jarvis:last-child')) waitingFor = null;
    measure();
  }
  const busy = () => ['listening', 'thinking', 'generating', 'speaking'].includes(state) || Boolean(waitingFor);

  // ---------- typing ----------
  function grow() { if (document.body.classList.contains('menubar')) return; ask.style.height = 'auto'; ask.style.height = `${Math.min(ask.scrollHeight, 112)}px`; measure(); }
  ask.addEventListener('input', grow);
  ask.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
    else if (e.key === 'Escape') { e.preventDefault(); escape(); }
  });
  function submit() {
    const text = ask.value.replace(/\s+/g, ' ').trim().slice(0, 500);
    if (!text) return;
    hideNotice();
    addTurn('you', text, null, true);
    waitingFor = { text, at: Date.now() };
    send({ type: 'text', text, quick: true }, true);
    if (!connected) $('statusText').textContent = 'Sending when Jarvis is ready…';
    ask.value = ''; grow();
    showTyping();
    showLine('Thinking…', 'thinking');
  }
  function escape() {
    if (ask.value) { ask.value = ''; grow(); return; }
    window.quick.hide();   // (closing also stops the listening; anything asked is still answered)
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && e.target !== ask) { e.preventDefault(); escape(); }
    // ⌘/Ctrl + Enter: open the full Jarvis app
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); window.quick.expand(lastVisual); }
    // ⌘/Ctrl + L: talk (or stop listening)
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && (e.key.toLowerCase() === 'l' || e.code === 'KeyL')) { e.preventDefault(); $('mic').click(); }
  });

  // ---------- talking ----------
  function startListening() {
    hideNotice();
    listenAsked = Date.now();
    if (send({ type: 'quick_listen' })) $('statusText').textContent = 'Starting to listen…';
  }
  $('mic').addEventListener('click', () => { if (state === 'listening') send({ type: 'quick_cancel' }); else startListening(); });
  $('stop').addEventListener('click', () => { send({ type: 'quick_cancel' }); waitingFor = null; hideTyping(); });
  $('close').addEventListener('click', () => window.quick.hide());
  $('expand').addEventListener('click', () => window.quick.expand(lastVisual));

  // the wave and the core follow your voice while Jarvis listens (loudness only, measured here, nothing recorded)
  const meter = { stream: null, ctx: null, raf: 0, starting: false };
  const bars = [];
  for (let i = 0; i < 22; i++) { const b = document.createElement('b'); $('wave').append(b); bars.push(b); }
  async function startMeter() {
    if (meter.stream || meter.starting || !navigator.mediaDevices?.getUserMedia) return;
    meter.starting = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      if (state !== 'listening') { stream.getTracks().forEach((t) => t.stop()); return; }
      meter.stream = stream;
      meter.ctx = new AudioContext();
      const analyser = meter.ctx.createAnalyser(); analyser.fftSize = 256; analyser.smoothingTimeConstant = 0.6;
      meter.ctx.createMediaStreamSource(stream).connect(analyser);
      const bins = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        meter.raf = requestAnimationFrame(tick);
        analyser.getByteFrequencyData(bins);
        let sum = 0;
        for (let i = 0; i < bars.length; i++) {
          const v = bins[2 + Math.floor(i * 1.6)] / 255;   // the speech range
          sum += v;
          bars[i].style.transform = `scaleY(${(0.12 + v * 0.88 * (1 - Math.abs(i - 10.5) / 16)).toFixed(3)})`;
        }
        $('core').style.setProperty('--level', Math.min(1, (sum / bars.length) * 2.2).toFixed(3));
      };
      tick();
    } catch (error) {
      console.warn('No microphone level for the bar:', error?.name || error);
    } finally { meter.starting = false; }
  }
  function stopMeter() {
    cancelAnimationFrame(meter.raf);
    meter.stream?.getTracks().forEach((t) => t.stop());
    meter.ctx?.close().catch(() => {});
    meter.stream = meter.ctx = null;
    $('core').style.setProperty('--level', '0');
    bars.forEach((b) => { b.style.transform = 'scaleY(.12)'; });
  }

  // ---------- the answer ----------
  function addTurn(who, text, image, local = false) {
    if (who === 'you' && !local && waitingFor && text === waitingFor.text && Date.now() - waitingFor.at < 15000) return;   // our own line, coming back
    if (who === 'you' && !local) waitingFor = waitingFor || { text, at: Date.now() };   // asked by voice
    hideTyping();
    const turn = document.createElement('div');
    turn.className = `turn ${who}`;
    const label = document.createElement('span'); label.className = 'who'; label.textContent = who === 'you' ? 'You' : 'Jarvis';
    turn.append(label);
    if (text) {
      if (who === 'you') { const p = document.createElement('p'); p.textContent = text; turn.append(p); }
      else { const body = document.createElement('div'); body.className = 'body'; body.append(render(text)); turn.append(body); }
    }
    if (image) { const img = new Image(); img.alt = ''; img.src = image; img.addEventListener('load', measure); turn.append(img); }
    answer.append(turn);
    if (inBar() && text) showLine(who === 'you' ? `“${text}”` : plain(text), who === 'you' ? 'heard' : 'answer');
    while (answer.children.length > 12) answer.firstElementChild.remove();
    answer.hidden = false;
    if (who === 'jarvis' && pendingVisual) { addChip(turn, pendingVisual); if (inBar()) $('expand').classList.add('has-visual'); pendingVisual = ''; }
    answer.scrollTop = answer.scrollHeight;
    measure();
  }
  let pendingVisual = '';
  function attachVisual(type) {
    lastVisual = type;
    // the engine sends a model before the words that go with it: it belongs to the answer still on its way
    const last = answer.querySelector('.turn.jarvis:not(.typing-turn):last-child');
    if (!waitingFor && last && !last.querySelector('.chip')) addChip(last, type); else pendingVisual = type;
  }
  function addChip(turn, type) {
    const chips = document.createElement('div'); chips.className = 'chips';
    const b = document.createElement('button'); b.type = 'button'; b.className = 'chip';
    b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.8 20 7.4v9.2l-8 4.6-8-4.6V7.4z"/><path d="M4 7.4 12 12l8-4.6M12 12v9.2"/></svg>';
    b.append(`Open the ${VISUALS[type]} in Jarvis`);
    b.addEventListener('click', () => window.quick.expand(type));
    chips.append(b); turn.append(chips);
    measure();
  }
  function showTyping() {
    if (answer.querySelector('.typing') || !(waitingFor || state === 'thinking' || state === 'generating')) return;
    const t = document.createElement('div'); t.className = 'turn jarvis typing-turn';
    t.innerHTML = '<span class="who">Jarvis</span><span class="typing"><b></b><b></b><b></b></span>';
    answer.append(t); answer.hidden = false; answer.scrollTop = answer.scrollHeight; measure();
  }
  function hideTyping() { answer.querySelector('.typing-turn')?.remove(); if (!answer.children.length) answer.hidden = true; measure(); }

  // a small, safe Markdown reader: paragraphs, lists, **bold**, `code` and code blocks (built as elements, never HTML)
  function inline(parent, text) {
    const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    for (const part of parts) {
      if (!part) continue;
      if (part.startsWith('**') && part.endsWith('**')) { const s = document.createElement('strong'); s.textContent = part.slice(2, -2); parent.append(s); }
      else if (part.startsWith('`') && part.endsWith('`')) { const c = document.createElement('code'); c.textContent = part.slice(1, -1); parent.append(c); }
      else parent.append(part);
    }
  }
  function render(text) {
    const frag = document.createDocumentFragment();
    const blocks = String(text).split(/```/);
    blocks.forEach((block, i) => {
      if (i % 2) { const pre = document.createElement('pre'), code = document.createElement('code'); code.textContent = block.replace(/^\w*\n/, ''); pre.append(code); frag.append(pre); return; }
      let list = null;
      for (const line of block.split('\n')) {
        const item = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
        if (item) { if (!list) { list = document.createElement(/^\s*\d/.test(line) ? 'ol' : 'ul'); frag.append(list); } const li = document.createElement('li'); inline(li, item[1]); list.append(li); continue; }
        list = null;
        if (!line.trim()) continue;
        const p = document.createElement('p'); inline(p, line.replace(/^#+\s*/, '')); frag.append(p);
      }
    });
    return frag;
  }

  // ---------- inside the menu bar: one line for everything (listening, thinking, what was heard, the answer) ----------
  const line = $('line'), lineText = $('lineText');
  let lineKind = '', ticker = null;
  const inBar = () => document.body.classList.contains('menubar');
  function showLine(text, kind) {
    if (!inBar()) return;
    lineKind = kind;
    line.dataset.kind = kind;
    lineText.textContent = text;
    line.hidden = false;
    ticker?.cancel(); ticker = null;
    requestAnimationFrame(() => {   // longer than the bar: it scrolls through, pausing at each end
      const over = lineText.scrollWidth - line.clientWidth + 16;
      if (over > 0 && !reduce && kind !== 'thinking' && kind !== 'listening') {
        const ms = Math.max(3500, over * 30);
        ticker = lineText.animate([{ transform: 'translateX(0)', offset: 0 }, { transform: 'translateX(0)', offset: 0.15 },
          { transform: `translateX(${-over}px)`, offset: 0.85 }, { transform: `translateX(${-over}px)`, offset: 1 }],
          { duration: ms + 2000, iterations: Infinity, direction: 'alternate', easing: 'ease-in-out' });
      }
    });
  }
  function hideLine() { if (line.hidden) return; ticker?.cancel(); ticker = null; line.hidden = true; lineKind = ''; }
  const plain = (text) => { const d = document.createElement('div'); d.append(render(text)); return d.textContent.replace(/\s+/g, ' ').trim(); };
  line.addEventListener('click', () => { hideLine(); ask.focus(); });
  ask.addEventListener('keydown', (e) => { if (inBar() && lineKind === 'answer' && e.key.length === 1) hideLine(); });
  ask.addEventListener('input', () => { if (inBar() && ask.value) hideLine(); });

  // ---------- notices ----------
  function showNotice(text, action = null) {
    if (inBar()) { showLine(text, 'notice'); if (action) line.onclick = () => { line.onclick = null; action[1](); }; return; }
    $('noticeText').textContent = text; $('notice').hidden = false;
    const b = $('noticeAction'); b.hidden = !action;
    if (action) { b.textContent = action[0]; b.onclick = action[1]; }
    measure();
  }
  function hideNotice() { $('notice').hidden = true; measure(); }

  // ---------- size: the window follows the bar ----------
  let measured = 0;
  function measure() {
    if (document.body.classList.contains('menubar')) return;   // inside the menu bar the height never changes
    requestAnimationFrame(() => {
      const h = Math.ceil($('bar').getBoundingClientRect().height + MARGIN);
      if (h !== measured) { measured = h; window.quick.size(h); }
    });
  }
  new ResizeObserver(measure).observe($('bar'));

  // the pointer: clicks go to the bar over the bar, and through the transparent margin round it to what's beneath
  $('bar').addEventListener('mouseenter', () => window.quick.hover(true));
  $('bar').addEventListener('mouseleave', () => window.quick.hover(false));

  // ---------- opening and closing ----------
  // ---------- the top edge: where the bar grows from (the notch on a Mac, the screen's top edge on Windows) ----------
  function applyGeometry(g) {
    const css = document.documentElement.style, neck = $('neck');
    const menubar = g?.mode === 'menubar';
    document.body.classList.toggle('menubar', menubar);
    if (menubar) {   // Jarvis Top inside the menu bar: one line, exactly the bar's height
      css.setProperty('--bar-h', `${g.height}px`);
      ask.setAttribute('wrap', 'off');
      document.body.classList.toggle('to-notch', Boolean(g.toNotch));
      document.body.classList.remove('has-neck', 'virtual-neck');
      neck.hidden = true;
      return;
    }
    const inset = g?.inset || 0;
    css.setProperty('--top', `${inset}px`);
    document.body.classList.toggle('has-neck', Boolean(g?.neck));
    document.body.classList.toggle('virtual-neck', Boolean(g?.neck && !g.neck.real));
    neck.hidden = !g?.neck;
    if (g?.neck) {
      const barW = (g.width || window.innerWidth) - 2 * MARGIN;
      css.setProperty('--neck-x', `${g.neck.x}px`);
      css.setProperty('--neck-w', `${g.neck.w}px`);
      css.setProperty('--neck-l', `${Math.max(0, g.neck.x - MARGIN)}px`);
      css.setProperty('--neck-r', `${Math.max(0, barW - (g.neck.x - MARGIN) - g.neck.w)}px`);
    }
  }
  // the spark: a point of light that drops out of the notch (or the top edge) and becomes the Jarvis core
  function aimSpark() {
    const core = $('core').getBoundingClientRect(), css = document.documentElement.style;
    const neckX = parseFloat(css.getPropertyValue('--neck-x')) || 0, neckW = parseFloat(css.getPropertyValue('--neck-w')) || 0;
    const top = parseFloat(css.getPropertyValue('--top')) || 0;
    const inBar = document.body.classList.contains('menubar');
    const fromX = inBar ? window.innerWidth - 6 : document.body.classList.contains('has-neck') ? neckX + neckW / 2 : window.innerWidth / 2;
    css.setProperty('--spark-x0', `${fromX}px`); css.setProperty('--spark-y0', `${inBar ? window.innerHeight / 2 : top + 2}px`);
    css.setProperty('--spark-x1', `${core.left + core.width / 2}px`); css.setProperty('--spark-y1', `${core.top + core.height / 2}px`);
  }

  window.quick.on('quick:config', (c) => { config = { ...config, ...c }; if (c?.geometry) applyGeometry(c.geometry); $('hint').textContent = config.label ? `${config.label} · esc` : 'esc to close'; });
  window.quick.on('quick:show', (c) => {
    if (c) config = { ...config, ...c };
    applyGeometry(config.geometry);
    $('hint').textContent = config.label ? `${config.label} · esc` : 'esc to close';
    open = true; shownAt = Date.now();
    document.body.classList.remove('closing', 'open'); void document.body.offsetWidth;
    aimSpark();
    document.body.classList.add('open');
    if (config.slow) { void getComputedStyle(document.body).opacity; document.getAnimations().forEach((a) => { a.playbackRate = 1 / config.slow; }); }
    send({ type: 'quick_visibility', visible: true });
    if (document.body.classList.contains('menubar')) send({ type: 'quick_menubar' }, true);   // (queued if Jarvis is still starting)
    // a fresh start after a while away, unless something is still on its way
    if (!busy() && answer.children.length && Date.now() - lastActivity() > 10 * 60 * 1000) { answer.replaceChildren(); answer.hidden = true; }
    setTimeout(() => ask.focus({ preventScroll: true }), 30);
    if (config.input === 'voice' && state !== 'listening') startListening();
    measure();
  });
  window.quick.on('quick:focus', () => ask.focus({ preventScroll: true }));
  window.quick.on('quick:will-hide', () => {
    open = false;
    send({ type: 'quick_visibility', visible: false });   // (anything asked keeps going and is answered)
    if (state === 'listening' && !waitingFor) send({ type: 'quick_cancel' });
    hideNotice();
    aimSpark();
    document.body.classList.remove('open'); document.body.classList.add('closing');
    if (config.slow) { void getComputedStyle(document.body).opacity; document.getAnimations().forEach((a) => { a.playbackRate = 1 / config.slow; }); }
    setTimeout(() => { document.body.classList.remove('closing'); window.quick.hidden(); }, (reduce ? 100 : 280) * (config.slow || 1));
  });
  window.quick.on('quick:blur', () => {
    // clicking elsewhere tucks it away, unless it's asked to stay, is busy, or is showing an answer to read
    // (and never in its first seconds: a just-launched Jarvis, or the system settling, can move the focus for a moment)
    if (config.stay || busy() || answer.children.length || ask.value || Date.now() - shownAt < 3000) return;
    window.quick.hide();
  });
  let lastAt = Date.now();
  const lastActivity = () => lastAt;
  new MutationObserver(() => { lastAt = Date.now(); }).observe(answer, { childList: true });

  setState('offline');
  connect();
  window.quick.ready();
  // for the tests: the bar's state, read from outside
  window.quickDebug = () => ({ geometry: config.geometry, open, state, connected, input: ask.value, turns: [...answer.querySelectorAll('.turn')].map((t) => ({ who: t.classList.contains('you') ? 'you' : 'jarvis', text: t.querySelector('p, .body')?.textContent || '', typing: t.classList.contains('typing-turn') })), notice: $('notice').hidden ? '' : $('noticeText').textContent, chip: answer.querySelector('.chip')?.textContent || '' });
})();
