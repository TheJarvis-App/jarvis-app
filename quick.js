// How it meets the top of the screen. On a Mac with a notch, the bar grows out of the notch: the notch is black
// hardware that no menu or status item ever sits under (macOS keeps them clear of it), so a black "neck" exactly
// filling the notch's rectangle continues it, unseen, down into the bar: notch, neck and bar read as one surface. The
// system menu bar itself is never covered or restyled (an app can't take it over): the window over it is transparent
// and lets every click through except on the bar. Without a notch (older Macs, external screens), Jarvis draws a small
// notch of its own in the middle of the menu bar while it's open. On Windows the bar hangs from the top edge of the
// work area (under a taskbar at the top), flush, and unfolds from a line of light along that edge.
//
// Quick Access: a small Jarvis bar at the top of the screen, opened with a shortcut from any app, without bringing the
// main window forward. This file is the main-process side: the window, where it goes, the shortcut, and focus.
//
//   * The shortcut: a key combination (⌥ Space by default) is registered with the operating system's own hotkey service
//     (Electron's globalShortcut: RegisterHotKey on Windows, Carbon hotkeys on macOS), which needs no permission and
//     works whatever app is in front. A double press of a modifier can't be registered that way; the engine watches for
//     it (quick_keys.py) and sends "quick_toggle", which the bar passes on here.
//   * The window: created once, kept hidden, shown instantly. On macOS it's a non-activating panel, so the app you were
//     in stays the active app and the main Jarvis window stays where it was; on Windows it's a tool window (no taskbar
//     button) that takes the keyboard while it's open.
//   * Where: the display the mouse is on. On a Mac, centred right under the menu bar (below the notch, never over the
//     menu bar's items), joined to it; on Windows, a little below the top of the work area (clear of a taskbar on top).
//   * Settings: read from settings.json (the same file the engine uses) and re-read when it changes.
const { BrowserWindow, globalShortcut, ipcMain, screen, app } = require('electron');
const fs = require('fs');
const { execFile, execFileSync } = require('child_process');
const path = require('path');

const MAC = process.platform === 'darwin';
const WIDTHS = { compact: 560, regular: 680, wide: 820 };
const MARGIN = 26;          // transparent room round the bar for its glow and shadow (clicks pass through it)
const DEFAULTS = { JARVIS_QUICK: 'on', JARVIS_QUICK_SHORTCUT: MAC ? 'hold-command' : 'Alt+Space', JARVIS_QUICK_CUSTOM: 'Control+Shift+Space',
  JARVIS_QUICK_INPUT: 'text', JARVIS_QUICK_STAY: 'on', JARVIS_QUICK_SIZE: 'regular', JARVIS_QUICK_POSITION: 'center' };
const GESTURES = new Set(['hold-command', 'double-command', 'double-option', 'double-shift', 'double-control']);
const FALLBACK = 'Alt+Space';   // registered alongside a gesture: works with no permission, whatever happens to the gesture

function labelFor(shortcut) {
  if (shortcut === 'hold-command') return MAC ? 'Hold ⌘ 3 s' : 'Hold Ctrl 3 s';
  if (shortcut.startsWith('double-')) {
    const key = shortcut.slice(7);
    const names = MAC ? { command: '⌘ Command', option: '⌥ Option', shift: '⇧ Shift', control: '⌃ Control' }
      : { command: 'Ctrl', option: 'Alt', shift: 'Shift', control: 'Ctrl' };
    return `${names[key] || key} twice`;
  }
  const mac = { commandorcontrol: '⌘', cmdorctrl: '⌘', command: '⌘', cmd: '⌘', control: '⌃', ctrl: '⌃', alt: '⌥', option: '⌥', shift: '⇧', space: 'Space' };
  const win = { commandorcontrol: 'Ctrl', cmdorctrl: 'Ctrl', command: 'Win', cmd: 'Win', control: 'Ctrl', ctrl: 'Ctrl', alt: 'Alt', option: 'Alt', shift: 'Shift', space: 'Space' };
  const parts = shortcut.split('+').map((p) => (MAC ? mac : win)[p.toLowerCase()] || (p.length === 1 ? p.toUpperCase() : p));
  return MAC ? parts.join(parts.length > 2 ? '' : ' ').replace(/ (?=Space)/, ' ') : parts.join('+');
}

class QuickAccess {
  constructor({ dataDir, wsUrl, log, showMain, mainWindow }) {
    Object.assign(this, { dataDir, wsUrl, log, showMain, mainWindow });
    this.win = null;
    this.ready = false;
    this.config = { ...DEFAULTS };
    this.registered = null;     // the key combination registered with the OS
    this.status = { enabled: true, shortcut: '', label: '', ok: true, message: '' };
    this.height = 96;           // the bar's own height, reported by the page
    this.lastToggle = 0;
    this.testing = false;
    this.hovering = false;
  }

  // ---------- settings ----------
  settingsFile() { return path.join(this.dataDir, 'settings.json'); }
  readConfig() {
    let saved = {};
    try { saved = JSON.parse(fs.readFileSync(this.settingsFile(), 'utf8')).values || {}; } catch (_) { /* no settings yet: defaults */ }
    const next = { ...DEFAULTS };
    for (const key of Object.keys(DEFAULTS)) if (typeof saved[key] === 'string' && saved[key]) next[key] = saved[key];
    for (const key of Object.keys(DEFAULTS)) if (process.env[key]) next[key] = process.env[key];   // as for the engine: the environment wins
    return next;
  }
  start() {
    this.apply(this.readConfig());
    // Settings saved in the window (or edited by hand) take effect without a restart
    let debounce = null;
    try {
      fs.watch(path.dirname(this.settingsFile()), (_event, name) => {
        if (name && name !== 'settings.json') return;
        clearTimeout(debounce);
        debounce = setTimeout(() => this.apply(this.readConfig()), 250);
      });
    } catch (error) { this.log(`Quick Access: can't watch the settings file (${error.message}); changes apply after a restart.`); }
    ipcMain.on('quick:size', (_e, h) => this.resize(h));
    ipcMain.on('quick:hide', () => this.hide('the bar'));
    ipcMain.on('quick:hidden', () => this.finishHide());
    ipcMain.on('quick:hover', (_e, over) => this.hover(Boolean(over)));
    ipcMain.on('quick:menubar', (_e, layout) => {   // the engine measured where the app's menus are (Accessibility)
      if (!layout || typeof layout !== 'object') return;
      this.menus = { ok: Boolean(layout.ok), app: String(layout.app || ''), name_end: Number(layout.name_end) || 0, menus_end: Number(layout.menus_end) || 0,
        starts: Array.isArray(layout.starts) ? layout.starts.map(Number).filter(Number.isFinite) : [] };
      if (this.visible()) { this.win.setBounds(this.bounds()); this.send('quick:config', this.pageConfig()); }
    });
    ipcMain.on('quick:expand', (_e, what) => this.expand(what));
    ipcMain.on('quick:toggle', (_e, source) => this.toggle(String(source || 'engine')));
    ipcMain.on('quick:ready', () => {
      this.ready = true;
      this.send('quick:config', this.pageConfig());
      if (this.pendingShow) {   // shown before the page had loaded (Jarvis just started): now it can take the keyboard
        this.send('quick:show', this.pendingShow); this.pendingShow = null;
        if (this.win && this.win.isVisible()) this.win.focus();
      }
    });
    ipcMain.handle('quick-status', () => this.status);
    ipcMain.handle('quick-test', () => { this.testing = true; setTimeout(() => { this.testing = false; }, 20000); return this.status; });
    ipcMain.handle('quick-open', () => { this.show('the menu'); return true; });
  }
  pageConfig() {
    return { input: this.config.JARVIS_QUICK_INPUT, stay: this.config.JARVIS_QUICK_STAY === 'on', size: this.config.JARVIS_QUICK_SIZE,
      label: this.status.label, platform: process.platform, geometry: this.geometry || null,
      slow: !app.isPackaged ? Number(process.env.JARVIS_QUICK_SLOWMO) || 0 : 0 };   // (development: slowed-down motion, to inspect it)
  }
  apply(config) {
    const changed = JSON.stringify(config) !== JSON.stringify(this.config) || this.registered === null;
    this.config = config;
    if (!changed && this.win) return;
    const enabled = config.JARVIS_QUICK !== 'off';
    const choice = config.JARVIS_QUICK_SHORTCUT;
    // a gesture is watched for by the engine (quick_keys.py); ⌥ Space stays registered beside it as the fallback
    const accelerator = choice === 'custom' ? config.JARVIS_QUICK_CUSTOM : GESTURES.has(choice) ? FALLBACK : choice;
    // the key combination: registered with the OS (released first if it changed)
    if (this.registered && this.registered !== accelerator) { globalShortcut.unregister(this.registered); this.registered = null; }
    let ok = true, message = '';
    if (enabled && accelerator && this.registered !== accelerator) {
      try {
        ok = globalShortcut.register(accelerator, () => this.toggle('shortcut'));
      } catch (error) { ok = false; message = `“${accelerator}” isn't a key combination Jarvis understands.`; }
      if (ok) this.registered = accelerator;
      else if (!message) message = `${labelFor(accelerator)} is already used by another app or by the system, so it can't open Jarvis. Choose another shortcut in Settings → Quick Access.`;
      if (!ok && GESTURES.has(choice)) {   // only the fallback is taken: the gesture itself still works
        this.log(`Quick Access: ${labelFor(accelerator)} is used by another app, so only ${labelFor(choice)} opens the bar.`);
        ok = true; message = '';
      }
    }
    if (!enabled && this.registered) { globalShortcut.unregister(this.registered); this.registered = null; }
    const label = labelFor(choice === 'custom' ? config.JARVIS_QUICK_CUSTOM : choice);   // (the fallback is added below)
    this.status = { enabled, shortcut: choice, label: GESTURES.has(choice) && this.registered ? `${label} · ${labelFor(FALLBACK)}` : label, ok, message, gesture: GESTURES.has(choice) };
    this.log(enabled ? `Quick Access: ${label}${ok ? '' : ` (not available: ${message})`}.` : 'Quick Access: off.');
    if (enabled && !this.win) setTimeout(() => this.create(), 1500);   // ready before it's first needed
    if (!enabled && this.win) this.hide('turned off');
    this.send('quick:config', this.pageConfig());
    this.toMain('quick-status', this.status);
    this.place();
  }

  // ---------- the window ----------
  create() {
    if (this.win) return;
    const width = this.width() + MARGIN * 2;
    this.readScreens();
    this.win = new BrowserWindow({
      width, height: this.height + MARGIN, show: false, frame: false, transparent: true, backgroundColor: '#00000000',
      enableLargerThanScreen: true,   // macOS: may sit over the menu bar's strip (transparent there, clicks pass through)
      resizable: false, movable: false, minimizable: false, maximizable: false, fullscreenable: false, skipTaskbar: true,
      hasShadow: false, alwaysOnTop: true, title: 'Jarvis Quick Access',
      ...(MAC ? { type: 'panel' } : {}),   // macOS: a non-activating panel, above full-screen apps, on every Space
      webPreferences: { preload: path.join(__dirname, 'quick', 'preload.js'), contextIsolation: true, nodeIntegration: false,
        sandbox: true, spellcheck: true },
    });
    this.win.setAlwaysOnTop(true, MAC ? 'pop-up-menu' : 'screen-saver');
    if (MAC) this.win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true, skipTransformProcessType: true });
    this.win.setIgnoreMouseEvents(true, { forward: true });   // until the pointer is over the bar itself
    this.win.webContents.on('will-navigate', (e) => e.preventDefault());
    this.win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    this.win.on('blur', () => { if (process.env.JARVIS_QUICK_PROBE) setTimeout(() => { const f = BrowserWindow.getFocusedWindow(); this.log(`Quick Access: blur (focused now: ${f ? f.getTitle() : 'another app'})`); }, 60); this.send('quick:blur'); });
    this.win.on('focus', () => { if (process.env.JARVIS_QUICK_PROBE) this.log('Quick Access: focus'); });
    if (!app.isPackaged) this.win.webContents.on('console-message', (_e, level, message) => { if (level >= 2) this.log(`Quick Access page: ${message}`); });
    this.win.on('closed', () => { this.win = null; this.ready = false; });
    this.win.loadFile(path.join(__dirname, 'quick', 'quick.html'), { query: { ws: this.wsUrl(), platform: !app.isPackaged && process.env.JARVIS_QUICK_LOOK === 'win' ? 'win32' : process.platform } });
    if (process.env.JARVIS_QUICK_PROBE) this.probe(process.env.JARVIS_QUICK_PROBE);
    for (const event of ['display-added', 'display-removed', 'display-metrics-changed']) screen.on(event, () => { this.readScreens(); this.place(); });
  }
  width() { return WIDTHS[this.config.JARVIS_QUICK_SIZE] || WIDTHS.regular; }
  // the notch and menu bar of each screen, from AppKit (NSScreen's safe area and the menu bar either side of the notch)
  readScreens(now = false) {
    if (!MAC) return;
    const script = `ObjC.import("AppKit"); const out = []; const ss = $.NSScreen.screens;
      for (let i = 0; i < ss.count; i++) { const s = ss.objectAtIndex(i), f = s.frame, v = s.visibleFrame; let top = 0, l = null, r = null;
        try { top = s.safeAreaInsets.top; } catch (e) {}
        try { const a = s.auxiliaryTopLeftArea, b = s.auxiliaryTopRightArea; if (a.size.width > 0 && b.size.width > 0) { l = a.origin.x + a.size.width; r = b.origin.x; } } catch (e) {}
        out.push({ x: f.origin.x, w: f.size.width, h: f.size.height, menu: (f.origin.y + f.size.height) - (v.origin.y + v.size.height), safeTop: top, notch: l !== null ? [l - f.origin.x, r - l] : null }); }
      JSON.stringify(out);`;
    const done = (error, stdout) => {
      if (error) { this.log(`Quick Access: couldn't read the screen layout (${error.message}); using the menu bar's height only.`); return; }
      try { this.screens = JSON.parse(stdout); } catch (_) { this.screens = []; }
      this.place();   // (the notch may only be known now)
    };
    if (now) {   // the first placement waits for it (about 0.1 s): placed without the notch, it could cover the status icons
      try { done(null, execFileSync('osascript', ['-l', 'JavaScript', '-e', script], { timeout: 5000, encoding: 'utf8' })); }
      catch (error) { done(error); }
      return;
    }
    execFile('osascript', ['-l', 'JavaScript', '-e', script], { timeout: 5000 }, done);
  }
  edge(display) {
    // the top of the screen: the menu bar's height (or the notch's, with the menu bar hidden), and where the notch is
    const b = display.bounds, wa = display.workArea;
    const info = (this.screens || []).find((s) => Math.round(s.x) === b.x && Math.round(s.w) === b.width && Math.round(s.h) === b.height);
    const menu = wa.y - b.y || (info && info.notch ? Math.round(info.safeTop) : 0);
    return { menu, notch: info && info.notch ? { x: b.x + info.notch[0], w: info.notch[1] } : null };
  }
  // Where Jarvis Top goes in the menu bar of `display`. With a notch: ending at the notch (a few points under it, so
  // they meet with no gap), starting after the frontmost app's menus if they leave room, otherwise after the app's name:
  // its own menus (File, Edit…) are covered while Jarvis Top is open and come back when it closes. The Apple menu, the
  // app's name, the notch and the status icons on the right are never covered. Without a notch: after the app's menus,
  // up to a little past the middle (status icons fill in from the right).
  menubarSpan(display, edge) {
    const b = display.bounds, m = this.menus && this.menus.ok ? this.menus : null;
    const MAX = 560, MIN = 320, COVER = 420;
    const nameEnd = m ? m.name_end + 12 : b.x + 160;   // (no Accessibility: room for the Apple menu and a long app name)
    if (edge.notch) {
      const right = edge.notch.x + 4;
      let left = m ? m.menus_end + 12 : right - COVER;
      // the app's menus leave too little room: cover only as many of them as a usable bar needs (they're back on close)
      if (right - left < MIN) {
        left = right - COVER;
        // whole menu titles only: start where one begins (the nearest that leaves at least MIN), never mid-word
        const fits = (m?.starts || []).filter((x) => x >= nameEnd && right - x >= MIN);
        if (fits.length) left = fits.reduce((a, x) => (Math.abs(x - (right - COVER)) < Math.abs(a - (right - COVER)) ? x : a)) - 4;
      }
      left = Math.max(left, right - MAX, nameEnd);
      return { x: Math.round(left), width: Math.round(right - left), toNotch: true };
    }
    const center = b.x + b.width / 2;
    let left = m ? m.menus_end + 12 : center - 300, right = Math.min(left + MAX, center + 300);
    if (right - left < MIN) { right = center + 300; left = Math.max(nameEnd, right - MAX); }
    return { x: Math.round(left), width: Math.round(right - left), toNotch: false };
  }
  bounds() {
    const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
    const wa = display.workArea, b = display.bounds;
    const w = this.width() + MARGIN * 2;
    const right = this.config.JARVIS_QUICK_POSITION === 'right';
    const x = right ? wa.x + wa.width - w - 6 : Math.round(wa.x + (wa.width - w) / 2);
    let top, neck = null, inset = 0;
    if (MAC) {
      // Jarvis Top lives inside the menu bar: exactly its height, between the app's menus and the notch
      if (!this.screens) this.readScreens(true);
      const edge = this.edge(display), span = this.menubarSpan(display, edge);
      const height = edge.menu || 24;
      this.geometry = { mode: 'menubar', height, width: span.width, toNotch: span.toNotch, app: this.menus?.app || '' };
      return { x: span.x, y: b.y, width: span.width, height };
    } else {
      top = wa.y;   // flush with the top of the work area (under a taskbar at the top)
    }
    this.geometry = { inset, neck, width: w };
    return { x, y: top, width: w, height: Math.min(Math.round(inset + this.height), Math.round(wa.height * 0.85)) };
  }
  place() { if (this.win && this.win.isVisible() && !this.hiding) { this.win.setBounds(this.bounds()); this.send('quick:config', this.pageConfig()); } }
  resize(h) {
    if (MAC) return;   // inside the menu bar: always exactly its height
    const height = Math.max(60, Math.min(900, Number(h) || 96));   // the bar and the margin under it
    if (Math.abs(height - this.height) < 1) return;
    this.height = height;
    if (this.win && this.win.isVisible()) {
      const b = this.bounds(), now = this.win.getBounds();
      this.win.setBounds({ ...now, height: b.height });   // the top stays put; the bar grows downwards
    }
  }
  hover(over) {
    if (!this.win || over === this.hovering) return;
    this.hovering = over;
    if (over) this.win.setIgnoreMouseEvents(false); else this.win.setIgnoreMouseEvents(true, { forward: true });
  }

  // ---------- showing and hiding ----------
  visible() { return Boolean(this.win && this.win.isVisible() && !this.hiding); }
  toggle(source) {
    if (this.config.JARVIS_QUICK === 'off') return;
    const now = Date.now();
    if (now - this.lastToggle < 280) return;   // one press, one toggle (key repeat, two triggers at once)
    this.lastToggle = now;
    if (this.testing) { this.testing = false; this.toMain('quick-tested', { ok: true, source }); }
    if (!this.visible()) this.show(source);
    else if (!this.win.isFocused()) this.focus();
    else this.hide('the shortcut');
  }
  show(source) {
    if (!this.win) this.create();
    clearTimeout(this.hideTimer); this.hiding = false;
    this.win.setBounds(this.bounds());   // (works out this.geometry, which the page draws the top edge from)
    if (this.ready) this.send('quick:show', { source, ...this.pageConfig() }); else this.pendingShow = { source, ...this.pageConfig() };
    if (MAC) {
      this.win.setIgnoreMouseEvents(false);   // inside the menu bar, the whole window is the bar
      this.win.showInactive();   // in front, without making Jarvis the active app (the panel takes the keys itself)
      this.win.focus();
    } else {
      this.win.show();
      this.win.focus();
    }
    this.log(`Quick Access opened (${source}).`);
  }
  focus() {
    if (!this.win) return;
    this.win.focus();
    this.send('quick:focus');
  }
  hide(reason) {
    if (!this.visible()) return;
    this.hiding = true;
    this.send('quick:will-hide');            // the page plays its exit, then says quick:hidden
    this.hideTimer = setTimeout(() => this.finishHide(), 420 * (Number(!app.isPackaged && process.env.JARVIS_QUICK_SLOWMO) || 1));
    this.log(`Quick Access closed (${reason}).`);
  }
  finishHide() {
    clearTimeout(this.hideTimer);
    if (!this.win || !this.hiding) return;
    this.hiding = false;
    this.hover(false);
    this.win.hide();
    // Windows gives the keyboard back to the window under the bar; a Mac panel never took the app's place.
  }
  expand(what) {
    this.hide('opening Jarvis');
    this.showMain();
    if (what) this.toMain('quick-open-visual', String(what));
  }

  // ---------- messages ----------
  send(channel, data) { if (this.win && !this.win.isDestroyed() && this.ready) this.win.webContents.send(channel, data); }
  toMain(channel, data) { const w = this.mainWindow(); if (w && !w.isDestroyed()) w.webContents.send(channel, data); }
  // tests only (JARVIS_QUICK_PROBE=file): the bar's state, written every 250 ms for a test to read
  probe(file) {
    setInterval(async () => {
      if (!this.win) return;
      let page = null;
      try { page = await this.win.webContents.executeJavaScript('window.quickDebug && window.quickDebug()'); } catch (_) { /* loading */ }
      const main = this.mainWindow();
      try {
        fs.writeFileSync(file, JSON.stringify({ visible: this.win.isVisible(), focused: this.win.isFocused(), bounds: this.win.getBounds(),
          mainVisible: Boolean(main && main.isVisible()), mainFocused: Boolean(main && main.isFocused()), status: this.status,
          display: screen.getDisplayNearestPoint(screen.getCursorScreenPoint()).workArea, page, at: Date.now() }));
      } catch (_) { /* the test reads the next one */ }
    }, 250);
  }
  reload() { if (this.win) { this.ready = false; this.win.loadFile(path.join(__dirname, 'quick', 'quick.html'), { query: { ws: this.wsUrl(), platform: process.platform } }); } }
  stop() { if (this.registered) globalShortcut.unregister(this.registered); }
}

module.exports = { QuickAccess, labelFor };
