// Coding Mode: Jarvis's coding workspace. One chat per project in the middle (what to build, change, fix, ask), the
// projects on the left, and on the right the project itself: its real files (with Jarvis's new and changed ones
// marked), how to run it, and what the checks and tests really said.
//
// This window never writes, runs or decides anything itself. Every message goes to Jarvis's engine (app.py, coder.py),
// which answers with what really happened: the chat, the job as it moves, the files on disk. Progress is drawn only
// from the engine's own reports; running a project and deleting a file both ask first.
//
// Talks to the rest of Jarvis only through the 'jarvis-message' event and window.jarvisSend (renderer.js).
(function () {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined && text !== null) n.textContent = text; return n; };
  const send = (payload) => Boolean(window.jarvisSend?.(payload));
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const svg = (paths, w = 1.8) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
  const ICON = {
    code: svg('<path d="M8.5 7 3.5 12l5 5M15.5 7l5 5-5 5M13.5 5l-3 14"/>'),
    plus: svg('<path d="M12 5v14M5 12h14"/>'),
    search: svg('<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>'),
    close: svg('<path d="M6 6l12 12M18 6 6 18"/>'),
    play: svg('<path d="M8 5.5v13l10.5-6.5z" fill="currentColor" stroke="none"/>'),
    stop: svg('<rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none"/>'),
    send: svg('<path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/>', 2),
    more: svg('<circle cx="5.5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="18.5" cy="12" r="1.3" fill="currentColor"/>'),
    panel: svg('<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M14.5 4.5v15"/>'),
    side: svg('<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M9.5 4.5v15"/>'),
    folder: svg('<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>'),
    folderOpen: svg('<path d="M3.5 17.5v-10a2 2 0 0 1 2-2h4l2 2.2h7a2 2 0 0 1 2 2v1.3"/><path d="M3.5 17.5 6 11.3a1.6 1.6 0 0 1 1.5-1h13a1 1 0 0 1 .9 1.4l-2.2 5.5a2 2 0 0 1-1.9 1.3H5.5a2 2 0 0 1-2-1"/>'),
    file: svg('<path d="M6.5 3.5h7l4 4v11a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2z"/><path d="M13.5 3.5v4h4"/>'),
    chevron: svg('<path d="m9.5 6.5 5.5 5.5-5.5 5.5"/>'),
    back: svg('<path d="M14.5 6l-6 6 6 6"/>'),
    copy: svg('<rect x="8.5" y="8.5" width="11" height="11" rx="2.2"/><path d="M15.5 8.5v-2a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2"/>'),
    check: svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 2),
    x: svg('<path d="M7 7l10 10M17 7 7 17"/>', 2),
    dash: svg('<path d="M7 12h10"/>', 2),
    edit: svg('<path d="M14.5 5.5l4 4L9 19H5v-4z"/><path d="M12.5 7.5l4 4"/>'),
    trash: svg('<path d="M5 7h14M10 4h4M7 7l.8 11.2a2 2 0 0 0 2 1.8h4.4a2 2 0 0 0 2-1.8L17 7"/>'),
    rename: svg('<path d="M4 17.5h16M7 14l7.5-7.5a1.8 1.8 0 0 1 2.5 2.5L9.5 16.5 6 17.5z"/>'),
    newFile: svg('<path d="M6.5 3.5h7l4 4v11a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2z"/><path d="M12 11v6M9 14h6"/>'),
    newFolder: svg('<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/><path d="M12 11v5M9.5 13.5h5"/>'),
    refresh: svg('<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4"/>'),
    external: svg('<path d="M13.5 5.5h5v5M18.5 5.5 11 13M16 13.5V18a1.5 1.5 0 0 1-1.5 1.5h-8A1.5 1.5 0 0 1 5 18v-8a1.5 1.5 0 0 1 1.5-1.5H11"/>'),
    terminal: svg('<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="m7.5 9.5 3 2.5-3 2.5M12.5 15h4"/>'),
    at: svg('<circle cx="12" cy="12" r="3.5"/><path d="M15.5 12v1.2a2.6 2.6 0 0 0 5 1V12a8.5 8.5 0 1 0-3.6 7"/>'),
    sort: svg('<path d="M7 5v14M4 16l3 3 3-3M17 19V5M14 8l3-3 3 3"/>'),
    eye: svg('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>'),
    eyeOff: svg('<path d="M4 4l16 16M9.9 6A9.7 9.7 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-3 3.7M6.4 7.5A17 17 0 0 0 2.5 12S6 18.5 12 18.5a9 9 0 0 0 3.6-.8M10 10a2.8 2.8 0 0 0 4 4"/>'),
    spark: svg('<path d="M12 3.5l1.8 5.2 5.2 1.8-5.2 1.8L12 17.5l-1.8-5.2L5 10.5l5.2-1.8z"/>'),
  };
  const EXAMPLES = [
    ['A racing website', 'A professional website about Formula 1 racing: a hero section, the teams, the race calendar and a contact form. Dark and modern.'],
    ['A browser game', 'A snake game I can play in the browser, with a score, levels that get faster, and a high score that is remembered.'],
    ['A photo tidy-up script', 'A Python script that renames the photos in a folder by the date they were taken, and tells me what it changed.'],
    ['A to-do API with tests', 'A small REST API in Node.js for a to-do list (add, list, finish, delete), saved to a file, with tests.'],
    ['A unit converter in C++', 'A command-line unit converter in C++ for length, weight and temperature.'],
  ];
  const STEPS = [['planning', 'Plan'], ['writing', 'Write'], ['checking', 'Check'], ['saving', 'Save']];
  const MAC = /Mac/i.test(navigator.platform || navigator.userAgent);

  // ---------- the skeleton ----------
  const layer = el('div', 'cd-layer');
  layer.id = 'codingLayer';
  layer.hidden = true;
  layer.setAttribute('role', 'dialog');
  layer.setAttribute('aria-modal', 'true');
  layer.setAttribute('aria-label', 'Coding Mode');
  if (MAC) layer.classList.add('cd-mac');
  layer.innerHTML = `
    <div class="cd-app" data-panel="open">
      <aside class="cd-side" aria-label="Projects">
        <div class="cd-brand"><span class="cd-mark">${ICON.code}</span><b>Coding</b><span class="cd-brand-sub">Jarvis</span></div>
        <button type="button" class="cd-new">${ICON.plus}<span>New project</span><kbd>${MAC ? '⌘' : 'Ctrl'} N</kbd></button>
        <label class="cd-search">${ICON.search}<input type="search" placeholder="Search name or folder" aria-label="Search projects by name or folder" spellcheck="false"></label>
        <div class="cd-side-tools">
          <span class="cd-side-label">Projects</span>
          <div class="cd-menu-wrap"><button type="button" class="cd-icon small cd-sort" aria-haspopup="menu" aria-expanded="false" aria-label="Sort projects" title="Sort">${ICON.sort}</button>
            <div class="cd-menu cd-sort-menu" role="menu" hidden></div></div>
          <button type="button" class="cd-icon small cd-earlier" aria-pressed="true" aria-label="Show earlier projects" title="Show earlier projects">${ICON.eye}</button>
        </div>
        <nav class="cd-threads" aria-label="Your projects"><ol class="cd-thread-list"><li class="cd-skel"></li><li class="cd-skel"></li><li class="cd-skel"></li></ol>
          <p class="cd-threads-empty" hidden></p>
          <div class="cd-hidden-group" hidden><button type="button" class="cd-hidden-toggle" aria-expanded="false"></button><ol class="cd-hidden-list" hidden></ol></div>
        </nav>
        <div class="cd-menu cd-row-menu" role="menu" hidden></div>
        <footer class="cd-side-foot">
          <button type="button" class="cd-folder-link" title="Open the folder where projects are saved">${ICON.folder}<span>Projects folder</span></button>
          <p class="cd-model"></p>
        </footer>
      </aside>
      <main class="cd-main">
        <header class="cd-top">
          <button type="button" class="cd-icon cd-side-toggle" aria-label="Show projects" title="Projects">${ICON.side}</button>
          <div class="cd-proj"><h2 class="cd-title">New project</h2><p class="cd-meta"><span class="cd-stack"></span><span class="cd-state"></span></p></div>
          <div class="cd-top-actions">
            <button type="button" class="cd-btn cd-primary cd-run" hidden>${ICON.play}<span>Run</span></button>
            <button type="button" class="cd-btn cd-vscode" hidden>${ICON.code}<span>Open in VS Code</span></button>
            <div class="cd-menu-wrap">
              <button type="button" class="cd-icon cd-more" aria-haspopup="menu" aria-expanded="false" aria-label="More actions" title="More" hidden>${ICON.more}</button>
              <div class="cd-menu" role="menu" hidden></div>
            </div>
            <span class="cd-sep" aria-hidden="true"></span>
            <button type="button" class="cd-icon cd-panel-toggle" aria-pressed="true" aria-label="Show the project panel" title="Project panel">${ICON.panel}</button>
            <button type="button" class="cd-icon cd-close" aria-label="Close Coding Mode" title="Close (Esc)">${ICON.close}</button>
          </div>
        </header>
        <section class="cd-feed" tabindex="-1"><div class="cd-feed-inner" aria-live="polite"></div></section>
        <div class="cd-toast" role="status" hidden></div>
        <form class="cd-composer" autocomplete="off">
          <div class="cd-compose">
            <textarea rows="1" maxlength="6000" spellcheck="true" aria-label="Message Jarvis"></textarea>
            <div class="cd-refs" role="listbox" aria-label="Project files" hidden></div>
            <div class="cd-compose-bar">
              <button type="button" class="cd-icon cd-ref" aria-label="Mention a file" title="Mention a file of the project">${ICON.at}</button>
              <p class="cd-status" role="status"></p>
              <span class="cd-compose-model"></span>
              <span class="cd-hint">Enter to send · Shift + Enter for a new line</span>
              <button type="button" class="cd-stop" hidden>${ICON.stop}<span>Stop</span></button>
              <button type="submit" class="cd-send" aria-label="Send" title="Send (Enter)">${ICON.send}</button>
            </div>
          </div>
        </form>
      </main>
      <aside class="cd-inspect" aria-label="Project">
        <div class="cd-tabs" role="tablist">
          <button type="button" role="tab" data-tab="files" aria-selected="true">Files<span class="cd-tab-count"></span></button>
          <button type="button" role="tab" data-tab="run" aria-selected="false">How to run</button>
          <button type="button" role="tab" data-tab="checks" aria-selected="false">Checks<span class="cd-tab-dot" hidden></span></button>
        </div>
        <section class="cd-pane" data-pane="files" role="tabpanel">
          <div class="cd-explorer">
            <div class="cd-pane-bar"><b class="cd-root-name"></b>
              <span class="cd-pane-tools">
                <button type="button" class="cd-icon small" data-fs="newfile" aria-label="New file" title="New file">${ICON.newFile}</button>
                <button type="button" class="cd-icon small" data-fs="mkdir" aria-label="New folder" title="New folder">${ICON.newFolder}</button>
                <button type="button" class="cd-icon small cd-refresh" aria-label="Refresh from disk" title="Refresh from disk">${ICON.refresh}</button>
                <button type="button" class="cd-icon small cd-reveal" aria-label="Show the folder" title="Show the folder">${ICON.external}</button>
              </span>
            </div>
            <div class="cd-tree" role="tree"></div>
          </div>
          <div class="cd-viewer" hidden>
            <div class="cd-viewer-bar">
              <button type="button" class="cd-icon small cd-viewer-back" aria-label="Back to the files" title="Back (Esc)">${ICON.back}</button>
              <b class="cd-viewer-path"></b>
              <span class="cd-seg" hidden><button type="button" data-mode="diff">Changes</button><button type="button" data-mode="file">File</button></span>
              <span class="cd-viewer-tools">
                <button type="button" class="cd-icon small cd-viewer-copy" aria-label="Copy the file" title="Copy">${ICON.copy}</button>
                <button type="button" class="cd-icon small cd-viewer-edit" aria-label="Edit the file" title="Edit">${ICON.edit}</button>
                <button type="button" class="cd-icon small cd-viewer-open" aria-label="Open in an editor" title="Open in VS Code or the default app">${ICON.external}</button>
              </span>
            </div>
            <div class="cd-viewer-body"></div>
          </div>
        </section>
        <section class="cd-pane" data-pane="run" role="tabpanel" hidden></section>
        <section class="cd-pane" data-pane="checks" role="tabpanel" hidden></section>
      </aside>
    </div>
    <div class="cd-dialog-scrim" hidden>
      <div class="cd-dialog" role="alertdialog" aria-modal="true" aria-labelledby="cdDialogTitle" aria-describedby="cdDialogText">
        <h3 id="cdDialogTitle"></h3>
        <p id="cdDialogText"></p>
        <label class="cd-dialog-check"><input type="checkbox"><span>Also move the project folder to the Trash</span></label>
        <p class="cd-dialog-path"></p>
        <div class="cd-dialog-actions"><button type="button" class="cd-btn cd-dialog-cancel">Cancel</button><button type="button" class="cd-btn cd-dialog-ok"></button></div>
      </div>
    </div>`;
  document.body.append(layer);

  const app = $('.cd-app', layer), feed = $('.cd-feed', layer), feedInner = $('.cd-feed-inner', layer);
  const composer = $('.cd-composer', layer), input = $('textarea', composer);

  // ---------- state ----------
  let info = { destinations: [], model: '', projectsDir: '', sandbox: false };
  let threads = [], thread = null, project = null, busy = false, status = '', job = null;
  let tab = 'files', search = '', viewing = null, expanded = new Set(), editing = null;
  let renaming = '', deleting = '', creating = '', menuOpen = false, loadedOnce = false, toastTimer = 0, closeTimer = 0, drawer = '';
  let confirmTests = false, tabChosen = false;
  let sidePrefs = { hidden: [], sort: 'recent', showEarlier: true }, threadsLoaded = false, hiddenOpen = false, renamingKey = '', rowMenuKey = '', dialog = null;

  const finished = () => Boolean(project && project.path);
  const FINAL = ['done', 'failed', 'stopped', 'interrupted'];
  const live = () => job && !FINAL.includes(job.phase);
  const canUse = (key) => (info.destinations.find((d) => d.key === key) || {}).available;

  // ---------- small renderers ----------
  function ago(seconds) {
    if (!seconds) return '';
    const mins = Math.max(0, Math.round((Date.now() / 1000 - seconds) / 60));
    return mins < 1 ? 'just now' : mins < 60 ? `${mins} min ago` : mins < 1440 ? `${Math.round(mins / 60)} h ago` : mins < 10080 ? `${Math.round(mins / 1440)} d ago`
      : new Date(seconds * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
  function clock(seconds) { return seconds ? new Date(seconds * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : ''; }
  function toast(message) {
    const t = $('.cd-toast', layer);
    if (!message) { t.hidden = true; return; }
    t.textContent = message; t.hidden = false; t.classList.remove('out');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.classList.add('out'); toastTimer = setTimeout(() => { t.hidden = true; }, 220); }, 4200);
  }
  async function copy(text, button) {
    try { await navigator.clipboard.writeText(text); }
    catch { const area = el('textarea'); area.value = text; document.body.append(area); area.select(); document.execCommand('copy'); area.remove(); }
    if (button) { button.classList.add('done'); button.setAttribute('aria-label', 'Copied'); setTimeout(() => { button.classList.remove('done'); button.setAttribute('aria-label', 'Copy'); }, 1400); }
  }
  function copyButton(getText, label = 'Copy') {
    const b = el('button', 'cd-copy'); b.type = 'button'; b.innerHTML = ICON.copy + ICON.check; b.setAttribute('aria-label', label); b.title = label;
    b.addEventListener('click', (e) => { e.stopPropagation(); copy(getText(), b); });
    return b;
  }

  // ---------- syntax colours: a small, honest highlighter (strings, comments, numbers, keywords, tags) ----------
  const KW = {
    js: 'await async break case catch class const continue default delete do else export extends finally for from function if import in instanceof let new of return static super switch this throw try typeof var void while yield true false null undefined',
    py: 'and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield self',
    c: 'auto bool break case catch char class const constexpr continue default delete do double else enum explicit extern false float for friend if inline int long namespace new nullptr operator private protected public return short signed sizeof static struct switch template this throw true try typedef typename union unsigned using virtual void volatile while include define std string vector',
    java: 'abstract boolean break byte case catch char class const continue default do double else enum extends final finally float for if implements import instanceof int interface long new null package private protected public return short static super switch this throw throws true false try void while var record',
    cs: 'abstract async await bool break case catch class const continue decimal default do double else enum false finally float for foreach if in int interface internal is namespace new null object out override private protected public readonly return static string struct switch this throw true try using var virtual void while',
    go: 'break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var true false nil',
    rs: 'as async await break const continue crate else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while',
    swift: 'as break case catch class continue default defer do else enum extension false for func guard if import in init let nil private protocol public return self static struct switch throw throws true try var while',
    sh: 'if then else elif fi for while do done case esac function in return export local echo exit set',
    sql: 'select from where insert into values update set delete create table primary key foreign references not null unique index drop alter add join left right inner outer on group by order having limit as and or default integer text real varchar int date',
  };
  const LANG_OF = { js: 'js', mjs: 'js', cjs: 'js', jsx: 'js', ts: 'js', tsx: 'js', json: 'json', py: 'py', c: 'c', h: 'c', cpp: 'c', cc: 'c', hpp: 'c', java: 'java', kt: 'java', cs: 'cs', go: 'go', rs: 'rs', swift: 'swift',
    sh: 'sh', bash: 'sh', zsh: 'sh', ps1: 'sh', sql: 'sql', html: 'html', htm: 'html', xml: 'html', svg: 'html', vue: 'html', css: 'css', scss: 'css', md: 'md', yml: 'sh', yaml: 'sh', toml: 'sh', rb: 'py', php: 'js', dockerfile: 'sh', makefile: 'sh' };
  const regexCache = {};
  function langFor(name) {
    const base = String(name || '').toLowerCase().split('/').pop();
    if (base === 'dockerfile' || base === 'makefile') return 'sh';
    const ext = base.includes('.') ? base.split('.').pop() : base;
    return LANG_OF[ext] || (KW[ext] ? ext : '');
  }
  function highlight(code, lang) {
    if (!lang || code.length > 300000) return esc(code);
    if (!regexCache[lang]) {
      const hash = ['py', 'sh'].includes(lang);
      const parts = [];
      if (lang === 'html') parts.push(['c', '<!--[\\s\\S]*?-->'], ['s', '"[^"]*"|\'[^\']*\''], ['t', '</?[A-Za-z][\\w:-]*|/?>'], ['a', '\\b[\\w:-]+(?==)']);
      else if (lang === 'css') parts.push(['c', '/\\*[\\s\\S]*?\\*/'], ['s', '"[^"\\n]*"|\'[^\'\\n]*\''], ['a', '[\\w-]+(?=\\s*:[^;{]*[;}])'], ['n', '#[0-9a-fA-F]{3,8}\\b|-?\\d*\\.?\\d+(?:px|rem|em|%|vh|vw|s|ms|deg|fr)?\\b'], ['k', '@[\\w-]+|!important']);
      else if (lang === 'json') parts.push(['a', '"(?:\\\\.|[^"\\\\])*"(?=\\s*:)'], ['s', '"(?:\\\\.|[^"\\\\])*"'], ['n', '-?\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?'], ['k', '\\b(?:true|false|null)\\b']);
      else if (lang === 'md') parts.push(['k', '^#{1,6} .*$'], ['s', '`[^`\\n]+`'], ['a', '\\*\\*[^*\\n]+\\*\\*']);
      else {
        parts.push(['c', hash ? '#[^\\n]*' : lang === 'sql' ? '--[^\\n]*|/\\*[\\s\\S]*?\\*/' : '//[^\\n]*|/\\*[\\s\\S]*?\\*/']);
        parts.push(['s', (lang === 'py' ? '"""[\\s\\S]*?"""|\'\'\'[\\s\\S]*?\'\'\'|' : '') + '"(?:\\\\.|[^"\\\\\\n])*"|\'(?:\\\\.|[^\'\\\\\\n])*\'' + (lang === 'js' || lang === 'sh' || lang === 'go' ? '|`(?:\\\\.|[^`\\\\])*`' : '')]);
        parts.push(['n', '\\b\\d+(?:\\.\\d+)?\\b']);
        if (KW[lang]) parts.push(['k', `\\b(?:${KW[lang].split(' ').join('|')})\\b`]);
        parts.push(['f', '\\b[A-Za-z_][\\w]*(?=\\s*\\()']);
      }
      regexCache[lang] = { re: new RegExp(parts.map(([, p]) => `(${p})`).join('|'), lang === 'sql' ? 'gmi' : 'gm'), kinds: parts.map(([k]) => k) };
    }
    const { re, kinds } = regexCache[lang];
    let out = '', last = 0, m;
    re.lastIndex = 0;
    while ((m = re.exec(code))) {
      if (m[0] === '') { re.lastIndex++; continue; }
      const kind = kinds[m.slice(1).findIndex((g) => g !== undefined)];
      out += esc(code.slice(last, m.index)) + `<span class="t-${kind}">${esc(m[0])}</span>`;
      last = m.index + m[0].length;
    }
    return out + esc(code.slice(last));
  }

  // ---------- Markdown, the little the chat needs: paragraphs, lists, headings, **bold**, `code`, fenced code ----------
  function inline(text) {
    return esc(text).replace(/`([^`\n]+)`/g, '<code>$1</code>').replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>').replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,!?:]|$)/g, '$1<em>$2</em>');
  }
  function codeBlock(code, lang, label) {
    const box = el('div', 'cd-codeblock');
    const head = el('div', 'cd-codeblock-head');
    head.append(el('span', '', label || lang || 'code'), copyButton(() => code, 'Copy code'));
    const pre = el('pre');
    pre.innerHTML = highlight(code, LANG_OF[(lang || '').toLowerCase()] || (lang || '').toLowerCase());
    box.append(head, pre);
    return box;
  }
  function markdown(text) {
    // Line by line: fenced code (also when indented inside a list item), lists whose items run over several lines,
    // headings, and paragraphs. Anything else is shown as text, never as HTML.
    const frag = document.createDocumentFragment();
    const lines = String(text || '').replace(/\r\n/g, '\n').split('\n');
    let para = [], list = null, item = null;
    const flushPara = () => { if (para.length) { const p = el('p'); p.innerHTML = para.map(inline).join('<br>'); (item || frag).append(p); para = []; } };
    const closeList = () => { flushPara(); item = null; if (list) { frag.append(list); list = null; } };
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const fence = line.match(/^(\s*)(```|~~~)\s*([\w.+-]*)/);
      if (fence) {
        const body = [];
        let j = i + 1;
        while (j < lines.length && !new RegExp(`^\\s*${fence[2]}\\s*$`).test(lines[j])) body.push(lines[j++].replace(new RegExp(`^ {0,${fence[1].length}}`), ''));
        flushPara();
        (item || frag).append(codeBlock(body.join('\n'), fence[3]));
        i = j;
        continue;
      }
      const bullet = line.match(/^(\s*)([-*•]|\d+[.)])\s+(.*)$/);
      if (bullet && !(item && bullet[1].length >= 4 && list)) {
        flushPara();
        const ordered = /\d/.test(bullet[2]);
        if (!list || (list.tagName === 'OL') !== ordered) {
          closeList();
          list = el(ordered ? 'ol' : 'ul');
          if (ordered && parseInt(bullet[2], 10) > 1) list.start = parseInt(bullet[2], 10);
        }
        item = el('li'); list.append(item);
        para.push(bullet[3]);
        continue;
      }
      if (!line.trim()) { flushPara(); if (list && !(lines[i + 1] || '').match(/^\s+\S|^\s*([-*•]|\d+[.)])\s/)) closeList(); continue; }
      const heading = line.match(/^#{1,4}\s+(.*)$/);
      if (heading) { closeList(); const h = el('h4'); h.innerHTML = inline(heading[1]); frag.append(h); continue; }
      if (list && !/^\s/.test(line) && !para.length) closeList();
      para.push(line.trim());
    }
    closeList();
    return frag;
  }

  // ---------- the sidebar ----------
  const SORTS = [['recent', 'Recent activity'], ['created', 'Date created'], ['name', 'Name']];
  const keyOf = (t) => t.key || t.id || ('path:' + t.path);
  const isActive = (t) => Boolean(thread && ((t.id && t.id === thread.id) || (!t.id && t.path && t.path === thread.path)));
  function threadRow(t) {
    const li = el('li', 'cd-thread-item');
    if (renamingKey === keyOf(t)) {
      const form = el('form', 'cd-thread-rename'), field = el('input');
      field.value = t.title || t.name || ''; field.setAttribute('aria-label', 'New name for the project'); field.maxLength = 80;
      form.append(field);
      const done = (save) => { const v = field.value.trim(); renamingKey = ''; if (save && v && v !== t.title) send({ type: 'code_rename', key: keyOf(t), title: v }); drawThreads(); };
      form.addEventListener('submit', (e) => { e.preventDefault(); done(true); });
      field.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(false); } });
      field.addEventListener('blur', () => setTimeout(() => { if (form.isConnected) done(true); }, 100));
      li.append(form);
      requestAnimationFrame(() => { field.focus(); field.select(); });
      return li;
    }
    const b = el('button', 'cd-thread'); b.type = 'button';
    const active = isActive(t);
    b.setAttribute('aria-current', active ? 'true' : 'false');
    const working = busy && job && t.id && job.thread === t.id;
    b.append(el('span', 'cd-thread-dot' + (working ? ' busy' : t.exists ? '' : ' gone')), el('b', '', t.title || t.name || 'Untitled'),
      el('small', '', [t.language, working ? 'working…' : t.exists || !t.path ? ago(sidePrefs.sort === 'created' ? t.created || t.updated : t.updated) : 'folder missing'].filter(Boolean).join(' · ')));
    b.title = t.path || 'Not built yet';
    b.addEventListener('click', () => { closeDrawer(); send(t.id ? { type: 'code_open_thread', id: t.id } : { type: 'code_open_thread', project: t.project }); });
    b.addEventListener('contextmenu', (e) => { e.preventDefault(); openRowMenu(t, more); });
    b.addEventListener('keydown', (e) => { if (e.key === 'ContextMenu' || (e.key === 'F10' && e.shiftKey)) { e.preventDefault(); openRowMenu(t, more); } });
    const more = el('button', 'cd-icon tiny cd-thread-more'); more.type = 'button';
    more.innerHTML = ICON.more; more.setAttribute('aria-label', `Actions for ${t.title || t.name || 'this project'}`); more.setAttribute('aria-haspopup', 'menu');
    more.addEventListener('click', (e) => { e.stopPropagation(); rowMenuKey === keyOf(t) ? closeRowMenu() : openRowMenu(t, more); });
    li.append(b, more);
    if (t.hidden) li.classList.add('is-hidden');
    return li;
  }
  function drawThreads() {
    const list = $('.cd-thread-list', layer);
    const q = search.trim().toLowerCase();
    const matches = (t) => !q || [t.title, t.name, t.language, t.path].join(' ').toLowerCase().includes(q);
    const by = { recent: (a, b) => (b.updated || 0) - (a.updated || 0), created: (a, b) => (b.created || b.updated || 0) - (a.created || a.updated || 0),
      name: (a, b) => String(a.title || a.name).localeCompare(String(b.title || b.name), undefined, { sensitivity: 'base', numeric: true }) }[sidePrefs.sort] || ((a, b) => 0);
    const visible = threads.filter((t) => !t.hidden && matches(t)).sort(by);
    const hidden = threads.filter((t) => t.hidden && matches(t)).sort(by);
    const earlier = sidePrefs.showEarlier || q ? visible : visible.filter(isActive);   // the setting keeps only the open one (a search still finds all)
    const tucked = visible.length - earlier.length;
    $('.cd-earlier', layer).setAttribute('aria-pressed', String(sidePrefs.showEarlier));
    $('.cd-earlier', layer).innerHTML = sidePrefs.showEarlier ? ICON.eye : ICON.eyeOff;
    $('.cd-earlier', layer).title = sidePrefs.showEarlier ? 'Hide earlier projects' : 'Show earlier projects';
    $('.cd-earlier', layer).setAttribute('aria-label', $('.cd-earlier', layer).title);
    if (!threadsLoaded) return;
    list.replaceChildren(...earlier.map(threadRow));
    const empty = $('.cd-threads-empty', layer);
    empty.hidden = Boolean(earlier.length);
    empty.replaceChildren();
    if (q && !visible.length && !hidden.length) empty.textContent = 'No project matches that name or folder.';
    else if (tucked) {
      empty.append(document.createTextNode(`${tucked} earlier project${tucked === 1 ? ' is' : 's are'} tucked away. `));
      const show = el('button', 'cd-linklike', 'Show them'); show.type = 'button';
      show.addEventListener('click', () => setPrefs({ showEarlier: true }));
      empty.append(show);
    } else if (!q) empty.textContent = threads.length ? 'Every project is hidden; they are below.' : 'Your projects will be listed here. Describe one in the chat to start.';
    if (tucked && earlier.length) { empty.hidden = false; }
    const group = $('.cd-hidden-group', layer);
    group.hidden = !hidden.length;
    const toggle = $('.cd-hidden-toggle', layer);
    toggle.textContent = `${hiddenOpen ? 'Hide' : 'Show'} hidden projects (${hidden.length})`;
    toggle.setAttribute('aria-expanded', String(hiddenOpen));
    $('.cd-hidden-list', layer).hidden = !hiddenOpen;
    $('.cd-hidden-list', layer).replaceChildren(...(hiddenOpen ? hidden.map(threadRow) : []));
    $('.cd-model', layer).textContent = info.free ? 'Free AI plan (Groq): big jobs pause for its limits, and the wait is shown.' : '';
    $('.cd-compose-model', layer).textContent = info.model ? `${info.model.replace(/^openai\//, '')}${info.free ? ' · Groq free' : ''}` : '';
    $('.cd-compose-model', layer).title = 'The AI that writes the code. A CODE_MODEL line in .env chooses another.';
  }

  function setPrefs(changes) { sidePrefs = { ...sidePrefs, ...changes }; drawThreads(); send({ type: 'code_prefs', ...changes }); }
  function closeRowMenu() { rowMenuKey = ''; $('.cd-row-menu', layer).hidden = true; }
  function openRowMenu(t, anchor) {
    const menu = $('.cd-row-menu', layer);
    rowMenuKey = keyOf(t);
    const item = (label, icon, action, cls = '') => {
      const b = el('button', 'cd-menu-item ' + cls); b.type = 'button'; b.setAttribute('role', 'menuitem'); b.innerHTML = icon + `<span>${esc(label)}</span>`;
      b.addEventListener('click', () => { closeRowMenu(); action(); });
      return b;
    };
    menu.replaceChildren(
      item('Rename', ICON.rename, () => { renamingKey = keyOf(t); if (t.hidden) hiddenOpen = true; drawThreads(); }),
      item(t.hidden ? 'Show in the list' : 'Hide from the list', t.hidden ? ICON.eye : ICON.eyeOff, () => send({ type: 'code_hide', key: keyOf(t), hidden: !t.hidden })),
      ...(t.path && t.exists ? [item('Show the folder', ICON.folder, () => send({ type: 'code_open_folder', path: t.path }))] : []),
      el('hr'),
      item('Remove…', ICON.trash, () => askRemove(t), 'danger'));
    const r = anchor.getBoundingClientRect(), side = $('.cd-side', layer).getBoundingClientRect();
    menu.style.top = Math.min(r.bottom + 4, window.innerHeight - 220) + 'px';
    menu.style.left = Math.max(8, Math.min(r.right - 220, side.right - 228)) + 'px';
    menu.hidden = false;
    menu.querySelector('button')?.focus();
  }
  function askRemove(t) {
    const name = t.title || t.name || 'this project';
    const working = busy && job && ((t.id && job.thread === t.id) || (t.path && job.path === t.path));
    dialog = { key: keyOf(t), t };
    const scrim = $('.cd-dialog-scrim', layer);
    $('#cdDialogTitle', layer).textContent = `Remove “${name}”?`;
    $('#cdDialogText', layer).textContent = working ? 'Jarvis is working on this project right now. Stop the work first, then remove it.'
      : t.path ? 'It leaves Coding Mode: its chat and its place in the list. Its files stay on your computer, exactly where they are.'
        : 'It leaves Coding Mode. Nothing was built for it yet, so there are no files.';
    const check = $('.cd-dialog-check input', layer);
    check.checked = false;
    $('.cd-dialog-check', layer).hidden = !(t.path && t.exists) || working;
    $('.cd-dialog-path', layer).textContent = t.path && t.exists ? t.path : '';
    $('.cd-dialog-path', layer).hidden = true;
    const ok = $('.cd-dialog-ok', layer);
    ok.disabled = Boolean(working);
    const sync = () => {
      ok.textContent = check.checked ? 'Remove and move folder to Trash' : 'Remove from list';
      ok.classList.toggle('danger', check.checked);
      $('.cd-dialog-path', layer).hidden = !check.checked;
    };
    check.onchange = sync; sync();
    scrim.hidden = false;
    requestAnimationFrame(() => $('.cd-dialog-cancel', layer).focus());
  }
  function closeDialog() { dialog = null; $('.cd-dialog-scrim', layer).hidden = true; }

  // ---------- the header ----------
  function drawHeader() {
    const title = project ? (project.name || thread?.title) : thread?.title || 'New project';
    $('.cd-title', layer).textContent = title || 'New project';
    const stack = project?.guide?.stack || project?.language || (live() && job.language) || '';
    $('.cd-stack', layer).textContent = stack;
    $('.cd-stack', layer).hidden = !stack;
    const state = $('.cd-state', layer);
    let label = '', tone = '';
    if (busy) { label = live() ? (job.action === 'change' ? 'Changing' : 'Building') : 'Working'; tone = 'busy'; }
    else if (project) {
      const failedChecks = (project.checks || []).some((c) => c.status === 'failed');
      if (project.phase === 'stopped') { label = 'Stopped · incomplete'; tone = 'warn'; }
      else if (project.tests?.status === 'failed' || failedChecks) { label = 'Needs attention'; tone = 'bad'; }
      else { label = 'Ready'; tone = 'ok'; }
    }
    state.textContent = label; state.dataset.tone = tone; state.hidden = !label;
    $('.cd-run', layer).hidden = !finished();
    $('.cd-run', layer).disabled = busy || !project?.guide?.launch;
    $('.cd-run', layer).title = project?.guide?.launch ? 'Start it (asks first)' : 'I can\'t tell how this project starts';
    $('.cd-vscode', layer).hidden = !(finished() && canUse('vscode'));
    $('.cd-more', layer).hidden = !finished();
  }
  function drawMenu() {
    const menu = $('.cd-menu', layer);
    const item = (label, icon, action, disabled = false) => {
      const b = el('button', 'cd-menu-item'); b.type = 'button'; b.setAttribute('role', 'menuitem'); b.innerHTML = icon + `<span>${esc(label)}</span>`; b.disabled = disabled;
      b.addEventListener('click', () => { toggleMenu(false); action(); });
      return b;
    };
    const items = [
      ...(canUse('vscode') ? [item('Open in VS Code', ICON.code, () => send({ type: 'code_deliver', destination: 'vscode', thread: thread?.id }))] : []),
      item('Show the folder', ICON.folder, () => send({ type: 'code_deliver', destination: 'local', thread: thread?.id })),
      item('Run the tests…', ICON.terminal, () => { setTab('checks'); confirmTests = true; drawChecks(); }, busy),
      item('Check the code again', ICON.refresh, () => send({ type: 'code_check', thread: thread?.id }), busy),
      el('hr'),
    ];
    for (const [key, label] of [['word', 'Make a Word document'], ['notes', 'Copy to Notes'], ['gdrive', 'Send to Google Drive'], ['zip', 'Make a zip']]) {
      const d = info.destinations.find((x) => x.key === key);
      if (d) items.push(item(label, ICON.external, () => send({ type: 'code_deliver', destination: key, thread: thread?.id }), !d.available));
      if (d && !d.available) items[items.length - 1].title = d.why || '';
    }
    if (!canUse('gdrive') && info.drive === 'ready') items.push(item('Connect Google Drive', ICON.external, () => { if (send({ type: 'code_connect_drive' })) toast('A browser tab is opening for the Google sign-in…'); }));
    menu.replaceChildren(...items);
  }
  function toggleMenu(open = !menuOpen) {
    menuOpen = open;
    if (open) drawMenu();
    $('.cd-menu', layer).hidden = !open;
    $('.cd-more', layer).setAttribute('aria-expanded', String(open));
    if (open) $('.cd-menu button:not(:disabled)', layer)?.focus();
  }

  // ---------- the chat ----------
  function emptyState() {
    const box = el('div', 'cd-hello');
    box.append(el('span', 'cd-hello-mark'));
    $('.cd-hello-mark', box).innerHTML = ICON.spark;
    box.append(el('h3', '', 'What should we build?'),
      el('p', 'cd-hello-lead', 'Describe it in your own words. Jarvis picks the language and every file it needs, writes them into a new project folder, checks them, and shows you exactly how to run it. Then keep talking to change it.'));
    const list = el('ul', 'cd-ideas');
    for (const [title, text] of EXAMPLES) {
      const li = el('li'), b = el('button', 'cd-idea'); b.type = 'button';
      b.append(el('b', '', title), el('span', '', text));
      b.addEventListener('click', () => { input.value = text; grow(); input.focus(); });
      li.append(b); list.append(li);
    }
    box.append(list);
    return box;
  }
  function workCard(m) {
    const j = m.job || {};
    const card = el('article', 'cd-work');
    card.dataset.phase = j.phase || 'planning';
    const verb = j.action === 'change' ? 'Changing' : 'Building';
    const running = !FINAL.includes(j.phase);
    const head = el('header', 'cd-work-head');
    head.append(el('span', 'cd-work-glyph'), el('b', '', running ? `${verb} ${j.name || 'the project'}` : j.phase === 'done' ? (j.action === 'change' ? `Changed ${j.name}` : `Built ${j.name}`)
      : j.phase === 'stopped' ? `Stopped ${j.name || ''}`.trim() : j.phase === 'interrupted' ? `Interrupted: ${j.name || 'the build'}` : `Couldn't finish ${j.name || 'it'}`));
    $('.cd-work-glyph', head).innerHTML = running ? '' : j.phase === 'done' ? ICON.check : ['stopped', 'interrupted'].includes(j.phase) ? ICON.dash : ICON.x;
    if (j.language) head.append(el('span', 'cd-work-lang', j.language));
    const reached = STEPS.findIndex(([k]) => k === (j.phase === 'fixing' ? 'checking' : j.phase));
    const steps = el('ol', 'cd-work-steps');
    STEPS.forEach(([key, label], i) => {
      const li = el('li', '', label);
      li.dataset.state = j.phase === 'done' ? 'done' : reached > i ? 'done' : reached === i && running ? 'now' : (j.phase === 'failed' || j.phase === 'stopped') && reached === i ? 'failed' : 'wait';
      steps.append(li);
    });
    card.append(head, steps);
    if (running && j.step) card.append(el('p', 'cd-work-step', j.step + '…'));
    const files = (j.files || []).filter((f) => f.status !== 'unchanged');
    if (files.length) {
      const list = el('ul', 'cd-work-files');
      for (const f of files.slice(0, 40)) {
        const li = el('li'); li.dataset.status = f.status;
        const b = el('button', 'cd-work-file'); b.type = 'button'; b.disabled = f.status === 'planned' || f.status === 'failed';
        b.append(el('i', 'cd-fdot'), el('span', '', f.path), el('small', '', f.status === 'failed' ? 'not written' : f.status === 'planned' ? '' : `${f.status === 'changed' ? 'changed' : 'new'} · ${f.lines || 0} lines`));
        b.title = f.error || '';
        b.addEventListener('click', () => { setTab('files'); openFile(f.path); });
        li.append(b); list.append(li);
      }
      if (files.length > 40) list.append(el('li', 'cd-work-more', `and ${files.length - 40} more`));
      card.append(list);
    }
    if (!running && j.checks && (j.checks.ok || j.checks.failed || j.checks.skipped)) {
      const c = j.checks;
      const line = el('button', 'cd-work-checks'); line.type = 'button';
      line.dataset.tone = c.failed ? 'bad' : 'ok';
      line.textContent = [c.ok ? `${c.ok} check${c.ok === 1 ? '' : 's'} passed` : '', c.failed ? `${c.failed} failed` : '', c.skipped ? `${c.skipped} not checked` : ''].filter(Boolean).join(' · ');
      line.addEventListener('click', () => setTab('checks'));
      card.append(line);
    }
    if (j.summary && !running) card.append(el('p', 'cd-work-summary', j.summary));
    return card;
  }
  function messageNode(m) {
    const wrap = el('div', `cd-msg cd-${m.role}`);
    wrap.dataset.id = m.id;
    wrap.dataset.kind = m.kind;
    if (m.role === 'user') {
      const bubble = el('div', 'cd-bubble');
      bubble.append(markdown(m.text));
      wrap.append(bubble, el('time', '', (m.via === 'voice' ? 'Said · ' : '') + clock(m.at)));
      return wrap;
    }
    if (m.kind === 'work') { wrap.append(workCard(m)); return wrap; }
    const body = el('div', 'cd-say');
    if (m.kind === 'error') body.classList.add('cd-say-error');
    body.append(markdown(m.text));
    if (m.kind === 'result' && m.phase === 'done' && finished()) {
      const row = el('div', 'cd-say-actions');
      const btn = (label, icon, action, cls = '') => { const b = el('button', 'cd-chip ' + cls); b.type = 'button'; b.innerHTML = icon + `<span>${esc(label)}</span>`; b.addEventListener('click', action); return b; };
      row.append(btn('How to run', ICON.terminal, () => setTab('run')));
      if (project?.guide?.launch) row.append(btn('Run it', ICON.play, () => askRun(), 'accent'));
      if (canUse('vscode')) row.append(btn('Open in VS Code', ICON.code, () => send({ type: 'code_deliver', destination: 'vscode', thread: thread?.id })));
      body.append(row);
    }
    if (m.kind === 'confirm') {
      const row = el('div', 'cd-say-actions');
      if (m.answer) row.append(el('span', 'cd-answered', m.answer === 'yes' ? 'You said yes.' : 'You said not now.'));
      else {
        const yes = el('button', 'cd-btn cd-primary small'); yes.type = 'button'; yes.innerHTML = ICON.play + '<span>Start it</span>';
        const no = el('button', 'cd-btn small'); no.type = 'button'; no.textContent = 'Not now';
        yes.addEventListener('click', () => { if (send({ type: 'code_confirm', thread: thread.id, id: m.id, yes: true })) { yes.disabled = no.disabled = true; } });
        no.addEventListener('click', () => { if (send({ type: 'code_confirm', thread: thread.id, id: m.id, yes: false })) { yes.disabled = no.disabled = true; } });
        row.append(yes, no);
      }
      body.append(row);
    }
    wrap.append(body);
    return wrap;
  }
  function drawFeed(scroll = true) {
    const messages = thread?.messages || [];
    if (!messages.length) feedInner.replaceChildren(emptyState());
    else feedInner.replaceChildren(...messages.map(messageNode));
    if (busy && !live() && status) feedInner.append(thinkingNode());
    if (scroll) requestAnimationFrame(() => { feed.scrollTop = feed.scrollHeight; });
  }
  function thinkingNode() {
    const n = el('div', 'cd-msg cd-jarvis cd-thinking');
    n.append(el('span', 'cd-dots'), el('span', '', status || 'Thinking'));
    $('.cd-dots', n).innerHTML = '<i></i><i></i><i></i>';
    return n;
  }
  function upsertMessage(m) {
    if (!thread) return;
    const at = thread.messages.findIndex((x) => x.id === m.id);
    const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 160;
    if (at >= 0) thread.messages[at] = { ...thread.messages[at], ...m };
    else thread.messages.push(m);
    const existing = $(`.cd-msg[data-id="${CSS.escape(m.id)}"]`, feedInner);
    if (existing) existing.replaceWith(messageNode(thread.messages[at >= 0 ? at : thread.messages.length - 1]));
    else drawFeed(false);
    $('.cd-thinking', feedInner)?.remove();
    if (busy && !live() && status) feedInner.append(thinkingNode());
    if (nearBottom || m.role === 'user') requestAnimationFrame(() => { feed.scrollTo({ top: feed.scrollHeight, behavior: 'smooth' }); });
  }

  // ---------- the composer ----------
  function grow() { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, Math.round(window.innerHeight * 0.36)) + 'px'; }
  function drawComposer() {
    input.placeholder = project ? `Ask for a change, a fix or a feature in ${project.name} — or ask anything about it` : 'Describe what to build: an app, a website, a game, a script, an API…';
    $('.cd-stop', layer).hidden = !busy;
    $('.cd-send', layer).hidden = busy;
    $('.cd-send', layer).disabled = !input.value.trim();
    $('.cd-hint', layer).hidden = busy || Boolean(status);
    $('.cd-status', layer).textContent = busy ? (live() ? (job.step || 'Working') + '…' : (status || 'Working') + '…') : '';
    $('.cd-ref', layer).hidden = !project;
    composer.classList.toggle('busy', busy);
  }
  function submit() {
    const text = input.value.trim();
    if (!text) return;
    if (busy) { toast('Jarvis is still working on the last request. Wait for it, or press Stop.'); return; }
    if (!send({ type: 'code_send', thread: thread?.id || '', text })) { toast('Jarvis’s engine isn’t connected, so nothing was sent.'); return; }
    busy = true; status = 'Sending';
    input.value = ''; grow(); closeRefs();
    drawComposer(); drawHeader();
  }
  function closeRefs() { $('.cd-refs', layer).hidden = true; }
  function openRefs() {
    const box = $('.cd-refs', layer);
    const files = (project?.tree || []).filter((f) => !f.folder).slice(0, 200);
    if (!files.length) return;
    box.replaceChildren(...files.map((f) => {
      const b = el('button', 'cd-ref-item'); b.type = 'button'; b.setAttribute('role', 'option');
      b.innerHTML = ICON.file + `<span>${esc(f.path)}</span>`;
      b.addEventListener('click', () => {
        const at = input.selectionStart ?? input.value.length;
        const before = input.value.slice(0, at).replace(/@$/, ''), after = input.value.slice(at);
        input.value = `${before}\`${f.path}\` ${after}`; closeRefs(); grow(); input.focus(); drawComposer();
      });
      return b;
    }));
    box.hidden = false;
    box.querySelector('button')?.focus();
  }

  // ---------- the inspector ----------
  function setTab(name, byUser = false) {
    if (byUser && live()) tabChosen = true;
    tab = name;
    for (const b of $$('.cd-tabs [role=tab]', layer)) b.setAttribute('aria-selected', String(b.dataset.tab === name));
    for (const p of $$('.cd-pane', layer)) p.hidden = p.dataset.pane !== name;
    if (app.dataset.panel !== 'open') setPanel(true);
    if (name === 'run') drawRun();
    if (name === 'checks') drawChecks();
  }
  function treeEntries() {
    if (project?.tree?.length) return project.tree;
    if (live() && job.files) return job.files.filter((f) => f.status !== 'planned' && f.status !== 'failed').map((f) => ({ path: f.path, size: 0, mark: f.status === 'changed' ? 'changed' : 'new' }));
    return [];
  }
  function buildTree(entries) {
    const root = { name: '', path: '', dirs: new Map(), files: [] };
    for (const e of entries) {
      const parts = e.path.replace(/\/$/, '').split('/');
      let node = root;
      parts.slice(0, e.folder ? parts.length : -1).forEach((part, i) => {
        if (!node.dirs.has(part)) node.dirs.set(part, { name: part, path: parts.slice(0, i + 1).join('/'), dirs: new Map(), files: [], mark: '' });
        node = node.dirs.get(part);
      });
      if (!e.folder) node.files.push({ ...e, name: parts[parts.length - 1] });
    }
    const markUp = (n) => { let m = ''; for (const d of n.dirs.values()) { const dm = markUp(d); if (dm && !m) m = dm; } for (const f of n.files) if (f.mark && !m) m = f.mark; n.mark = m; return m; };
    markUp(root);
    return root;
  }
  function drawTree() {
    const box = $('.cd-tree', layer);
    const entries = treeEntries();
    $('.cd-root-name', layer).textContent = project?.name || (live() && job.name) || 'Files';
    $('.cd-tab-count', layer).textContent = entries.length ? String(entries.filter((e) => !e.folder).length) : '';
    for (const b of $$('.cd-pane-tools button', layer)) b.disabled = !project || busy;
    if (!entries.length) {
      const empty = el('div', 'cd-pane-empty');
      empty.append(el('b', '', live() ? 'The files appear here as they are written.' : 'No files yet.'),
        el('span', '', live() ? 'Each one is saved to the project folder the moment it is done.' : 'Describe a project in the chat and its real files show up here, the new and changed ones marked.'));
      box.replaceChildren(empty);
      return;
    }
    const tree = buildTree(entries);
    const rows = [];
    if (creating) rows.push(inputRow(creating === 'mkdir' ? 'New folder name (or path/name)' : 'New file name (or path/name)', '', (value) => {
      send({ type: 'code_fs', op: creating, thread: thread.id, path: value }); creating = ''; drawTree();
    }, () => { creating = ''; drawTree(); }, 0));
    const walk = (node, depth) => {
      const dirs = [...node.dirs.values()].sort((a, b) => a.name.localeCompare(b.name));
      for (const d of dirs) {
        const open = expanded.has(d.path) || (!expanded.has('!' + d.path) && depth < 1);
        rows.push(treeRow({ path: d.path, name: d.name, folder: true, open, mark: d.mark }, depth));
        if (deleting === d.path) rows.push(confirmRow(d.path, depth));
        if (open) walk(d, depth + 1);
      }
      for (const f of node.files.sort((a, b) => a.name.localeCompare(b.name))) {
        rows.push(treeRow(f, depth));
        if (deleting === f.path) rows.push(confirmRow(f.path, depth));
      }
    };
    walk(tree, 0);
    box.replaceChildren(...rows);
  }
  function treeRow(item, depth) {
    if (renaming === item.path) return inputRow('New name', item.path, (value) => {
      send({ type: 'code_fs', op: 'rename', thread: thread.id, path: item.path, to: value }); renaming = ''; drawTree();
    }, () => { renaming = ''; drawTree(); }, depth);
    const row = el('div', 'cd-row'); row.setAttribute('role', 'treeitem');
    row.style.setProperty('--depth', depth);
    if (item.folder) row.setAttribute('aria-expanded', String(item.open));
    if (viewing && viewing.path === item.path) row.setAttribute('aria-selected', 'true');
    const main = el('button', 'cd-row-main'); main.type = 'button';
    main.innerHTML = (item.folder ? `<i class="cd-chev${item.open ? ' open' : ''}">${ICON.chevron}</i>${item.open ? ICON.folderOpen : ICON.folder}` : `<i class="cd-chev-space"></i>${ICON.file}`)
      + `<span class="cd-row-name">${esc(item.name)}</span>` + (item.mark ? `<i class="cd-mark-dot" data-mark="${item.mark}" title="${item.mark === 'new' ? 'Written by Jarvis' : 'Changed by Jarvis'}"></i><span class="cd-sr">, ${item.mark === 'new' ? 'new' : 'changed'}</span>` : '');
    main.addEventListener('click', () => {
      if (item.folder) {
        if (item.open) { expanded.delete(item.path); expanded.add('!' + item.path); } else { expanded.add(item.path); expanded.delete('!' + item.path); }
        drawTree();
      } else openFile(item.path);
    });
    row.append(main);
    if (project && !busy) {
      const tools = el('span', 'cd-row-tools');
      const tool = (icon, label, action) => { const b = el('button', 'cd-icon tiny'); b.type = 'button'; b.innerHTML = icon; b.setAttribute('aria-label', `${label} ${item.name}`); b.title = label; b.addEventListener('click', (e) => { e.stopPropagation(); action(); }); return b; };
      tools.append(tool(ICON.rename, 'Rename', () => { renaming = item.path; drawTree(); }), tool(ICON.trash, 'Delete', () => { deleting = item.path; drawTree(); }));
      row.append(tools);
    }
    return row;
  }
  function inputRow(placeholder, value, done, cancel, depth) {
    const row = el('form', 'cd-row cd-row-input'); row.style.setProperty('--depth', depth);
    const field = el('input'); field.value = value; field.placeholder = placeholder; field.setAttribute('aria-label', placeholder); field.spellcheck = false;
    row.append(field);
    row.addEventListener('submit', (e) => { e.preventDefault(); const v = field.value.trim(); if (v && v !== value) done(v); else cancel(); });
    field.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); e.preventDefault(); cancel(); } });
    field.addEventListener('blur', () => setTimeout(() => { if (row.isConnected) cancel(); }, 120));
    requestAnimationFrame(() => { field.focus(); const dot = field.value.lastIndexOf('.'); field.setSelectionRange(field.value.lastIndexOf('/') + 1, dot > 0 ? dot : field.value.length); });
    return row;
  }
  function confirmRow(path, depth) {
    const row = el('div', 'cd-row cd-row-confirm'); row.style.setProperty('--depth', depth);
    row.append(el('span', '', `Delete ${path.split('/').pop()}? A copy is kept in Jarvis’s backups.`));
    const yes = el('button', 'cd-btn danger tiny', 'Delete'); yes.type = 'button';
    const no = el('button', 'cd-btn tiny', 'Cancel'); no.type = 'button';
    yes.addEventListener('click', () => { send({ type: 'code_fs', op: 'delete', thread: thread.id, path }); deleting = ''; if (viewing?.path === path) closeViewer(); drawTree(); });
    no.addEventListener('click', () => { deleting = ''; drawTree(); });
    row.append(yes, no);
    requestAnimationFrame(() => no.focus());
    return row;
  }

  // ---------- one file ----------
  function openFile(path) {
    viewing = { path, content: null, diff: '', error: '', mode: (project?.changed || job?.changed || []).includes(path) ? 'diff' : 'file' };
    editing = null;
    $('.cd-explorer', layer).hidden = true;
    $('.cd-viewer', layer).hidden = false;
    drawViewer();
    if (!send({ type: 'code_file', path, thread: thread?.id || '' })) { viewing.error = 'Jarvis’s engine isn’t connected.'; drawViewer(); }
  }
  function closeViewer() {
    viewing = null; editing = null;
    $('.cd-viewer', layer).hidden = true;
    $('.cd-explorer', layer).hidden = false;
    drawTree();
  }
  function drawViewer() {
    if (!viewing) return;
    $('.cd-viewer-path', layer).textContent = viewing.path;
    $('.cd-viewer-path', layer).title = viewing.path;
    const seg = $('.cd-seg', layer);
    seg.hidden = !viewing.diff || Boolean(editing);
    for (const b of $$('button', seg)) b.setAttribute('aria-pressed', String(b.dataset.mode === viewing.mode));
    $('.cd-viewer-edit', layer).hidden = Boolean(editing) || viewing.content === null || Boolean(viewing.error);
    $('.cd-viewer-edit', layer).disabled = busy;
    $('.cd-viewer-copy', layer).hidden = viewing.content === null || Boolean(viewing.error);
    $('.cd-viewer-open', layer).hidden = !project;
    const body = $('.cd-viewer-body', layer);
    if (editing) {
      const area = el('textarea', 'cd-editor'); area.value = editing.draft; area.spellcheck = false; area.setAttribute('aria-label', `Editing ${viewing.path}`);
      area.addEventListener('input', () => { editing.draft = area.value; });
      area.addEventListener('keydown', (e) => {
        if (e.key === 'Tab') { e.preventDefault(); const s = area.selectionStart; area.setRangeText('  ', s, area.selectionEnd, 'end'); editing.draft = area.value; }
        if (e.key === 's' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); save(); }
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); editing = null; drawViewer(); }
      });
      const bar = el('div', 'cd-editor-bar');
      bar.append(el('span', '', `Editing · ${MAC ? '⌘' : 'Ctrl'} S saves · Esc cancels`));
      const cancel = el('button', 'cd-btn small', 'Cancel'); cancel.type = 'button'; cancel.addEventListener('click', () => { editing = null; drawViewer(); });
      const ok = el('button', 'cd-btn cd-primary small', 'Save'); ok.type = 'button'; ok.addEventListener('click', save);
      bar.append(cancel, ok);
      body.replaceChildren(area, bar);
      requestAnimationFrame(() => area.focus());
      return;
    }
    if (viewing.error) { body.replaceChildren(el('p', 'cd-pane-note', viewing.error)); return; }
    if (viewing.content === null) { body.replaceChildren(el('div', 'cd-skeleton')); return; }
    const pre = el('pre', 'cd-code'); pre.tabIndex = 0;
    if (viewing.mode === 'diff' && viewing.diff) {
      pre.classList.add('cd-diff');
      pre.replaceChildren(...viewing.diff.split('\n').map((line) => {
        const kind = line.startsWith('+++') || line.startsWith('---') ? 'meta' : line.startsWith('@@') ? 'hunk' : line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : '';
        return el('span', 'cd-dl' + (kind ? ` cd-d-${kind}` : ''), line || ' ');
      }));
    } else {
      const lines = highlight(viewing.content, langFor(viewing.path)).split('\n');
      if (lines.length > 1 && lines[lines.length - 1] === '') lines.pop();
      pre.innerHTML = lines.map((l) => `<span class="cd-ln">${l}</span>`).join('');   // an empty line keeps its height from CSS
      pre.style.setProperty('--gutter', String(String(lines.length).length));
    }
    body.replaceChildren(pre);
  }
  function save() {
    if (!editing || !viewing) return;
    if (send({ type: 'code_fs', op: 'save', thread: thread.id, path: viewing.path, content: editing.draft })) { viewing.content = editing.draft; viewing.diff = ''; viewing.mode = 'file'; editing = null; drawViewer(); }
  }

  // ---------- how to run ----------
  function drawRun() {
    const pane = $('[data-pane=run]', layer);
    const g = project?.guide;
    if (!g || g.kind === 'missing') {
      const empty = el('div', 'cd-pane-empty');
      empty.append(el('b', '', project ? 'The project folder isn’t there any more.' : 'Nothing to run yet.'),
        el('span', '', project ? project.path : 'When Jarvis has built a project, this panel says exactly how to start it on this computer: what to install, which commands to type and where, and what you should see.'));
      pane.replaceChildren(empty);
      return;
    }
    const out = [];
    const head = el('div', 'cd-run-head');
    head.append(el('span', 'cd-run-stack', g.stack));
    const runButton = el('button', 'cd-btn cd-ring'); runButton.type = 'button'; runButton.innerHTML = ICON.play + `<span>${g.launch?.type === 'browser' ? 'Open it' : 'Run it'}</span>`;
    runButton.disabled = busy || !g.launch; runButton.addEventListener('click', askRun);
    head.append(runButton);
    out.push(head);
    if (g.launch) out.push(el('p', 'cd-run-note', g.launch.type === 'browser' ? 'Opens it in your browser, after you confirm in the chat.' : `Opens ${MAC ? 'Terminal' : 'a terminal'} and runs it there, after you confirm in the chat.`));
    if (g.requirements?.length) {
      const sec = section('What you need');
      const ul = el('ul', 'cd-needs');
      for (const r of g.requirements) {
        const li = el('li');
        li.dataset.state = r.installed === true ? 'ok' : r.installed === false ? 'missing' : 'na';
        const mark = el('i', 'cd-need-mark'); mark.innerHTML = r.installed === true ? ICON.check : r.installed === false ? ICON.x : ICON.dash;
        const text = el('div');
        text.append(el('b', '', r.name));
        const sub = r.installed === true ? `Installed on this computer${r.version ? ` (${r.version})` : ''}.` : r.installed === false ? 'Not found on this computer.' : '';
        text.append(el('span', '', [sub, r.why].filter(Boolean).join(' ')));
        li.append(mark, text);
        if (r.installed === false && /^https:/.test(r.get || '')) {
          const get = el('button', 'cd-btn tiny'); get.type = 'button'; get.innerHTML = `<span>Get it</span>${ICON.external}`;
          get.addEventListener('click', () => send({ type: 'code_open_url', url: r.get }));
          li.append(get);
        } else if (r.installed === false && r.get) text.append(el('span', 'cd-need-get', r.get));
        ul.append(li);
      }
      sec.append(ul); out.push(sec);
    }
    const steps = section('Steps');
    const ol = el('ol', 'cd-steps');
    for (const s of g.steps || []) {
      const li = el('li');
      const p = el('p'); p.innerHTML = inline(s.text); li.append(p);
      if (s.command) {
        const cmd = el('div', 'cd-cmd');
        const code = el('code'); code.textContent = s.command;
        const prompt = el('span', 'cd-cmd-prompt', /^https?:/.test(s.command) ? '' : '$');
        if (/^https?:/.test(s.command)) prompt.innerHTML = ICON.external;
        cmd.append(prompt, code, copyButton(() => s.command, 'Copy command'));
        li.append(cmd);
      }
      if (s.where) li.append(el('small', '', s.where));
      ol.append(li);
    }
    steps.append(ol); out.push(steps);
    const facts = el('dl', 'cd-facts');
    if (g.expect) facts.append(el('dt', '', 'What you should see'), el('dd', '', g.expect));
    if (g.stop) facts.append(el('dt', '', 'To stop it'), el('dd', '', g.stop));
    if (facts.children.length) out.push(facts);
    if (g.problems?.length) {
      const sec = section('If something goes wrong');
      const list = el('dl', 'cd-problems');
      for (const pr of g.problems) { list.append(el('dt', '', pr.problem)); const dd = el('dd'); dd.innerHTML = inline(pr.fix); list.append(dd); }
      sec.append(list); out.push(sec);
    }
    out.push(verified(g));
    pane.replaceChildren(...out);
  }
  function section(title) { const s = el('section', 'cd-sec'); s.append(el('h4', '', title)); return s; }
  function verified(g) {
    const checks = project.checks || [];
    const ok = checks.filter((c) => c.status === 'ok').length, bad = checks.filter((c) => c.status === 'failed').length, skipped = checks.filter((c) => c.status === 'skipped').length;
    const did = [], not = [];
    if (g.known) did.push('These steps were worked out from the project’s own files on disk.');
    else not.push('Jarvis doesn’t recognise this kind of project, so these steps are not worked out from its files.');
    for (const r of g.requirements || []) if (r.installed === true) did.push(`${r.name.replace(/ \d.*$/, '')} ${r.version} answered on this computer.`);
    if (ok) did.push(`${ok} syntax and link check${ok === 1 ? '' : 's'} passed.`);
    if (bad) not.push(`${bad} check${bad === 1 ? '' : 's'} failed — see Checks.`);
    if (skipped) not.push(`${skipped} file${skipped === 1 ? '' : 's'} couldn’t be checked here.`);
    if (project.tests?.status === 'passed') did.push(`Its tests passed${project.tests.sandboxed ? ' (in a sandbox)' : ''}.`);
    else if (project.tests?.status === 'failed') not.push('Its tests failed — see Checks.');
    not.push('Jarvis hasn’t run the program itself; press Run to start it and see.');
    const box = el('section', 'cd-verified');
    const a = el('div'); a.append(el('h4', '', 'Checked'), listOf(did));
    const b = el('div'); b.append(el('h4', '', 'Not checked'), listOf(not));
    box.append(a, b);
    return box;
  }
  function listOf(items) { const ul = el('ul'); for (const t of items) ul.append(el('li', '', t)); return ul; }
  function askRun() {
    if (!thread || busy) return;
    if (send({ type: 'code_run', thread: thread.id })) { if (window.matchMedia('(max-width: 1080px)').matches) setPanel(false); }
  }

  // ---------- checks and tests ----------
  function drawChecks() {
    const pane = $('[data-pane=checks]', layer);
    const checks = project?.checks || (live() ? job.checks : []) || [];
    const tests = project?.tests || {};
    const failed = checks.filter((c) => c.status === 'failed').length;
    $('.cd-tab-dot', layer).hidden = !(failed || tests.status === 'failed');
    if (!project && !checks.length) {
      const empty = el('div', 'cd-pane-empty');
      empty.append(el('b', '', 'No checks yet.'), el('span', '', 'After writing, Jarvis checks every file with the tools on this computer (syntax, links, missing packages) and fixes what fails. The real output of each check appears here.'));
      pane.replaceChildren(empty);
      return;
    }
    const out = [];
    const testsBox = el('section', 'cd-sec cd-tests');
    const head = el('div', 'cd-sec-head');
    head.append(el('h4', '', 'Tests'));
    if (tests.status) { const pill = el('span', 'cd-pill', { passed: 'Passed', failed: 'Failed', not_run: 'Not run', running: 'Running…' }[tests.status] || tests.status); pill.dataset.tone = tests.status === 'passed' ? 'ok' : tests.status === 'failed' ? 'bad' : ''; head.append(pill); }
    testsBox.append(head);
    if (confirmTests) {
      const ask = el('div', 'cd-inline-confirm');
      ask.append(el('p', '', info.sandbox ? 'This runs the project’s own test code, in a sandbox with no network that can only write inside the project. Run them?'
        : 'This runs the project’s own test code on this computer, with a time limit and none of your keys, but without a sandbox. Run them?'));
      const yes = el('button', 'cd-btn cd-primary small', 'Run the tests'); yes.type = 'button';
      const no = el('button', 'cd-btn small', 'Not now'); no.type = 'button';
      yes.addEventListener('click', () => { confirmTests = false; send({ type: 'code_tests', thread: thread?.id }); drawChecks(); });
      no.addEventListener('click', () => { confirmTests = false; drawChecks(); });
      const row = el('div', 'cd-say-actions'); row.append(yes, no); ask.append(row);
      testsBox.append(ask);
    } else if (project) {
      const run = el('button', 'cd-btn small'); run.type = 'button'; run.innerHTML = ICON.terminal + '<span>Run the tests…</span>'; run.disabled = busy || tests.status === 'running';
      run.addEventListener('click', () => { confirmTests = true; drawChecks(); });
      testsBox.append(run);
    }
    if (tests.status && tests.status !== 'running') {
      const pre = el('pre', 'cd-output');
      pre.textContent = [tests.command ? `$ ${tests.command}${tests.sandboxed ? '   (sandboxed)' : ''}` : '', tests.output || ''].filter(Boolean).join('\n\n');
      testsBox.append(pre);
    } else if (!tests.status) testsBox.append(el('p', 'cd-pane-note', 'Not run. Tests only run when you ask.'));
    out.push(testsBox);
    const checkBox = el('section', 'cd-sec');
    const ch = el('div', 'cd-sec-head');
    ch.append(el('h4', '', 'Checks'));
    if (checks.length) ch.append(el('span', 'cd-sec-sum', [`${checks.filter((c) => c.status === 'ok').length} passed`, failed ? `${failed} failed` : '', checks.some((c) => c.status === 'skipped') ? `${checks.filter((c) => c.status === 'skipped').length} not checked` : ''].filter(Boolean).join(' · ')));
    if (project) { const again = el('button', 'cd-icon small'); again.type = 'button'; again.innerHTML = ICON.refresh; again.title = 'Check again'; again.setAttribute('aria-label', 'Check again'); again.disabled = busy; again.addEventListener('click', () => send({ type: 'code_check', thread: thread?.id })); ch.append(again); }
    checkBox.append(ch);
    const ul = el('ul', 'cd-checks');
    for (const c of [...checks].sort((a, b) => ({ failed: 0, skipped: 1, ok: 2 }[a.status] - { failed: 0, skipped: 1, ok: 2 }[b.status]))) {
      const li = el('li'); li.dataset.status = c.status;
      const mark = el('i', 'cd-need-mark'); mark.innerHTML = c.status === 'ok' ? ICON.check : c.status === 'failed' ? ICON.x : ICON.dash;
      const name = el('button', 'cd-check-file', c.file); name.type = 'button'; name.addEventListener('click', () => { setTab('files'); openFile(c.file); });
      li.append(mark, name, el('span', 'cd-check-tool', c.tool));
      if (c.output && c.status !== 'ok') li.append(el('pre', 'cd-output', c.output));
      ul.append(li);
    }
    if (!checks.length) ul.append(el('li', 'cd-pane-note', 'Nothing in this project could be checked automatically.'));
    checkBox.append(ul);
    out.push(checkBox);
    pane.replaceChildren(...out);
  }

  // ---------- panels on small windows ----------
  function setPanel(open) {
    app.dataset.panel = open ? 'open' : 'closed';
    $('.cd-panel-toggle', layer).setAttribute('aria-pressed', String(open));
    if (open && window.matchMedia('(max-width: 1080px)').matches) drawer = 'panel';
    else if (drawer === 'panel') drawer = '';
    app.dataset.drawer = drawer;
  }
  function closeDrawer() {
    if (drawer === 'side') { drawer = ''; app.dataset.drawer = ''; }
  }

  function drawAll(scroll = true) { drawThreads(); drawHeader(); drawFeed(scroll); drawComposer(); drawTree(); if (viewing) drawViewer(); if (tab === 'run') drawRun(); if (tab === 'checks') drawChecks(); else $('.cd-tab-dot', layer).hidden = !(((project?.checks) || []).some((c) => c.status === 'failed') || project?.tests?.status === 'failed'); }

  // ---------- open, close ----------
  function open(data) {
    clearTimeout(closeTimer);
    layer.classList.remove('closing');
    if (data) info = { ...info, ...data };
    if (layer.hidden) {
      window.hideGraph?.(); window.hideGlobe?.(); window.hidePlanet?.(); window.hideClock?.(); window.weatherPanel?.close?.();
      layer.hidden = false;
      setPanel(!window.matchMedia('(max-width: 1080px)').matches);
      send({ type: 'code_window', open: true });
      if (!loadedOnce) send({ type: 'code_info' });
      drawAll();
      requestAnimationFrame(() => input.focus({ preventScroll: true }));
    }
  }
  function close() {
    if (layer.hidden || layer.classList.contains('closing')) return;
    layer.classList.add('closing');
    closeTimer = setTimeout(() => { layer.hidden = true; layer.classList.remove('closing'); send({ type: 'code_window', open: false }); }, 180);
  }

  // ---------- from the backend ----------
  window.addEventListener('jarvis-message', (event) => {
    const msg = event.detail || {};
    switch (msg.type) {
      case 'coding_open': open(msg.data || {}); break;
      case 'close_coding': close(); break;
      case 'coding_info':
        info = { ...info, ...(msg.data || {}) };
        if (!loadedOnce) { loadedOnce = true; if (info.thread) send({ type: 'code_open_thread', id: info.thread }); }
        if (info.busy !== undefined && !info.busy && busy && !live()) busy = false;
        drawThreads(); drawHeader(); break;
      case 'coding_threads': threads = msg.data || []; threadsLoaded = true; if (msg.prefs) sidePrefs = { ...sidePrefs, ...msg.prefs }; drawThreads(); break;
      case 'coding_removed': toast(msg.data?.message || ''); break;
      case 'coding_thread': {
        const d = msg.data || {};
        const justBuilt = job && job.action === 'create' && job.phase === 'done' && d.project && !project;   // the first build of this chat just finished
        const changed = (d.thread?.id || '') !== (thread?.id || '') || (d.project?.path || '') !== (project?.path || '');
        thread = d.thread || null; project = d.project || null; busy = Boolean(d.busy); status = d.status || '';
        if (d.job) job = d.job; else if (!busy) job = null;
        if (changed) { if (viewing) closeViewer(); expanded = new Set(); renaming = deleting = creating = ''; confirmTests = false; }
        else if (viewing && !(project?.tree || []).some((f) => f.path === viewing.path)) closeViewer();
        else if (viewing && !editing) send({ type: 'code_file', path: viewing.path, thread: thread?.id || '' });
        drawAll(changed);
        if (justBuilt && !tabChosen && project?.guide) setTab('run');   // what to do next: how to run it
        if (!busy) tabChosen = false;
        if (changed) input.focus({ preventScroll: true });
        break;
      }
      case 'coding_message': {
        if (!thread || thread.id !== msg.thread) {
          if (!thread || (!thread.messages?.length && msg.data?.role === 'user')) thread = { id: msg.thread, title: '', path: '', messages: [] };
          else break;
        }
        upsertMessage(msg.data);
        drawThreads();
        if (msg.data.kind === 'confirm' && !msg.data.answer && window.matchMedia('(max-width: 1080px)').matches) setPanel(false);
        break;
      }
      case 'coding': {
        if (msg.thread && thread && msg.thread !== thread.id) { job = msg.data; busy = !FINAL.includes(job.phase); drawThreads(); drawComposer(); break; }
        job = msg.data;
        busy = !FINAL.includes(job.phase) || job.tests?.status === 'running';
        if (thread) {
          const card = thread.messages.find((m) => m.id === 'w-' + job.id);
          if (card) {
            card.job = { ...card.job, ...job, checks: summarize(job.checks) };
            const node = $(`.cd-msg[data-id="${CSS.escape(card.id)}"]`, feedInner);
            if (node) node.replaceWith(messageNode(card));
          }
        }
        if (project && job.path === project.path && job.tests) { project.tests = job.tests; if (tab === 'checks') drawChecks(); }
        if (!project) drawTree();
        drawHeader(); drawComposer(); drawThreads();
        break;
      }
      case 'coding_status': {
        const d = msg.data || {};
        if (d.thread && thread && d.thread !== thread.id) break;
        busy = Boolean(d.busy); status = d.step || '';
        $('.cd-thinking', feedInner)?.remove();
        if (busy && !live() && status) { feedInner.append(thinkingNode()); feed.scrollTo({ top: feed.scrollHeight, behavior: 'smooth' }); }
        drawComposer(); drawHeader(); break;
      }
      case 'coding_note': toast(msg.message); if (busy && !live() && status === 'Sending') { busy = false; status = ''; drawComposer(); } break;
      case 'coding_fs': toast(msg.data?.message || ''); break;
      case 'coding_file':
        if (viewing && msg.path === viewing.path && !editing) { viewing.content = msg.content ?? ''; viewing.diff = msg.diff || ''; viewing.error = msg.error || ''; if (!viewing.diff) viewing.mode = 'file'; drawViewer(); }
        break;
      default: break;
    }
  });
  function summarize(checks) {
    if (!Array.isArray(checks)) return checks || {};
    return { ok: checks.filter((c) => c.status === 'ok').length, failed: checks.filter((c) => c.status === 'failed').length, skipped: checks.filter((c) => c.status === 'skipped').length };
  }

  // ---------- controls ----------
  composer.addEventListener('submit', (e) => { e.preventDefault(); submit(); });
  input.addEventListener('input', () => { grow(); drawComposer(); if (input.value.endsWith('@') && project) openRefs(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
  });
  $('.cd-stop', layer).addEventListener('click', () => { if (send({ type: 'code_stop' })) { status = 'Stopping after the current step'; drawComposer(); } });
  $('.cd-ref', layer).addEventListener('click', () => ($('.cd-refs', layer).hidden ? openRefs() : closeRefs()));
  $('.cd-new', layer).addEventListener('click', () => { closeDrawer(); send({ type: 'code_new_thread' }); });
  $('.cd-earlier', layer).addEventListener('click', () => setPrefs({ showEarlier: !sidePrefs.showEarlier }));
  $('.cd-hidden-toggle', layer).addEventListener('click', () => { hiddenOpen = !hiddenOpen; drawThreads(); });
  $('.cd-sort', layer).addEventListener('click', (e) => {
    e.stopPropagation();
    const menu = $('.cd-sort-menu', layer), open = menu.hidden;
    menu.replaceChildren(...SORTS.map(([key, label]) => {
      const b = el('button', 'cd-menu-item'); b.type = 'button'; b.setAttribute('role', 'menuitemradio'); b.setAttribute('aria-checked', String(sidePrefs.sort === key));
      b.innerHTML = (sidePrefs.sort === key ? ICON.check : '<i class="cd-menu-gap"></i>') + `<span>${label}</span>`;
      b.addEventListener('click', () => { menu.hidden = true; $('.cd-sort', layer).setAttribute('aria-expanded', 'false'); setPrefs({ sort: key }); });
      return b;
    }));
    menu.hidden = !open;
    $('.cd-sort', layer).setAttribute('aria-expanded', String(open));
    if (open) menu.querySelector('[aria-checked="true"]')?.focus();
  });
  $('.cd-dialog-cancel', layer).addEventListener('click', closeDialog);
  $('.cd-dialog-ok', layer).addEventListener('click', () => {
    if (!dialog) return;
    const files = $('.cd-dialog-check input', layer).checked;
    if (send({ type: 'code_remove', key: dialog.key, files })) closeDialog();
  });
  $('.cd-dialog-scrim', layer).addEventListener('mousedown', (e) => { if (e.target.classList.contains('cd-dialog-scrim')) closeDialog(); });
  $('.cd-dialog', layer).addEventListener('keydown', (e) => {   // Tab stays inside the question while it's open
    if (e.key !== 'Tab') return;
    const items = [...$('.cd-dialog', layer).querySelectorAll('button:not(:disabled), input:not([disabled])')].filter((n) => n.offsetParent);
    const at = items.indexOf(document.activeElement);
    if (e.shiftKey && at <= 0) { e.preventDefault(); items[items.length - 1].focus(); }
    else if (!e.shiftKey && at === items.length - 1) { e.preventDefault(); items[0].focus(); }
  });
  layer.addEventListener('keydown', (e) => {   // arrow keys move through any open menu
    const menu = e.target.closest?.('.cd-menu');
    if (!menu || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
    const items = [...menu.querySelectorAll('button:not(:disabled)')];
    const i = items.indexOf(document.activeElement);
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : (i + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
    e.preventDefault(); items[next]?.focus();
  });
  $('.cd-search input', layer).addEventListener('input', (e) => { search = e.target.value; drawThreads(); });
  $('.cd-folder-link', layer).addEventListener('click', () => send({ type: 'code_deliver', destination: 'local' }));
  $('.cd-run', layer).addEventListener('click', askRun);
  $('.cd-vscode', layer).addEventListener('click', () => send({ type: 'code_deliver', destination: 'vscode', thread: thread?.id }));
  $('.cd-more', layer).addEventListener('click', (e) => { e.stopPropagation(); toggleMenu(); });
  $('.cd-close', layer).addEventListener('click', close);
  $('.cd-panel-toggle', layer).addEventListener('click', () => setPanel(app.dataset.panel !== 'open'));
  $('.cd-side-toggle', layer).addEventListener('click', () => { drawer = drawer === 'side' ? '' : 'side'; app.dataset.drawer = drawer; if (drawer === 'side') $('.cd-new', layer).focus(); });
  $('.cd-tabs', layer).addEventListener('click', (e) => { const b = e.target.closest('[role=tab]'); if (b) setTab(b.dataset.tab, true); });
  $('.cd-tabs', layer).addEventListener('keydown', (e) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
    const tabs = $$('.cd-tabs [role=tab]', layer); const i = tabs.findIndex((t) => t.dataset.tab === tab);
    const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length]; setTab(next.dataset.tab); next.focus();
  });
  for (const b of $$('[data-fs]', layer)) b.addEventListener('click', () => { creating = b.dataset.fs; drawTree(); });
  $('.cd-refresh', layer).addEventListener('click', () => { if (thread) send({ type: 'code_open_thread', id: thread.id }); });
  $('.cd-reveal', layer).addEventListener('click', () => send({ type: 'code_deliver', destination: 'local', thread: thread?.id }));
  $('.cd-viewer-back', layer).addEventListener('click', closeViewer);
  $('.cd-seg', layer).addEventListener('click', (e) => { const b = e.target.closest('button'); if (b && viewing) { viewing.mode = b.dataset.mode; drawViewer(); } });
  $('.cd-viewer-copy', layer).addEventListener('click', (e) => { if (viewing?.content != null) copy(viewing.content, e.currentTarget); });
  $('.cd-viewer-edit', layer).addEventListener('click', () => { if (viewing?.content != null && !busy) { editing = { draft: viewing.content }; drawViewer(); } });
  $('.cd-viewer-open', layer).addEventListener('click', () => { if (viewing) send({ type: 'code_open_file', path: viewing.path, thread: thread?.id }); });
  layer.addEventListener('click', (e) => {
    if (menuOpen && !e.target.closest('.cd-menu-wrap')) toggleMenu(false);
    if (rowMenuKey && !e.target.closest('.cd-row-menu, .cd-thread-more')) closeRowMenu();
    if (!$('.cd-sort-menu', layer).hidden && !e.target.closest('.cd-sort-menu, .cd-sort')) { $('.cd-sort-menu', layer).hidden = true; $('.cd-sort', layer).setAttribute('aria-expanded', 'false'); }
    if (!$('.cd-refs', layer).hidden && !e.target.closest('.cd-refs, .cd-ref')) closeRefs();
    if (drawer && e.target.classList.contains('cd-app')) { drawer = ''; app.dataset.drawer = ''; if (app.dataset.panel === 'open' && window.matchMedia('(max-width: 1080px)').matches) setPanel(false); }
  });
  window.addEventListener('keydown', (e) => {   // capture: before the window's own Escape (which leaves full screen)
    if (layer.hidden) return;
    if (e.key === 'Escape') {
      e.preventDefault(); e.stopImmediatePropagation();
      if (dialog) closeDialog();
      else if (rowMenuKey) closeRowMenu();
      else if (!$('.cd-sort-menu', layer).hidden) { $('.cd-sort-menu', layer).hidden = true; $('.cd-sort', layer).focus(); }
      else if (menuOpen) { toggleMenu(false); $('.cd-more', layer).focus(); }
      else if (!$('.cd-refs', layer).hidden) { closeRefs(); input.focus(); }
      else if (drawer === 'side') { drawer = ''; app.dataset.drawer = ''; }
      else if (editing) { editing = null; drawViewer(); }
      else if (viewing) closeViewer();
      else if (drawer === 'panel') setPanel(false);
      else close();
    } else if ((e.metaKey || e.ctrlKey) && window.jarvisKeys.is(e, 'n') && !e.shiftKey && !e.altKey) {
      e.preventDefault(); e.stopImmediatePropagation(); send({ type: 'code_new_thread' });
    }
  }, true);
  let wasNarrow = window.matchMedia('(max-width: 1080px)').matches;
  window.addEventListener('resize', () => {
    const narrow = window.matchMedia('(max-width: 1080px)').matches;
    if (narrow !== wasNarrow) { wasNarrow = narrow; setPanel(!narrow); if (!window.matchMedia('(max-width: 820px)').matches && drawer === 'side') { drawer = ''; app.dataset.drawer = ''; } }
    if (!layer.hidden) grow();
  });

  // The way in from the top bar.
  const settings = document.getElementById('settingsBtn');
  if (settings) {
    const button = el('button', 'icon-btn');
    button.type = 'button'; button.id = 'codeBtn'; button.title = 'Coding Mode'; button.setAttribute('aria-label', 'Coding Mode'); button.innerHTML = ICON.code;
    button.addEventListener('click', () => { open(); send({ type: 'code_info' }); });
    settings.before(button);
  }

  if (window.jarvisKeys) window.jarvisKeys.modal = () => !layer.hidden && !layer.classList.contains('closing');   // the app's letter shortcuts wait while it's open
  window.hideCoding = () => { if (!layer.hidden) close(); };
  window.codingOpen = () => !layer.hidden && !layer.classList.contains('closing');
  drawAll();
})();
