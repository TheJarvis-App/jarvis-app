// Jarvis's keyboard shortcuts, decided in one place: which key was pressed, whether someone is typing, and whether a
// window that takes over the screen (Coding Mode) has the keys.
//
// A shortcut key is recognised by the letter it types on a Latin keyboard (so an AZERTY "M" is where the keycap says
// M), and by its position on any other layout: with the keyboard in Hebrew, F types "כ" and "/" types ".", and those
// still mean F and "/". Nothing fires while the focus is in a text box, a text area, an editable element or a menu,
// or while an input method is composing.
//
// Loaded before every other script of the window; usable from Node too (tests/test_shortcuts.py runs it there).
(function (root) {
  const LATIN = /^[a-z]$/i;
  const TEXT_INPUTS = new Set(['text', 'search', 'email', 'url', 'tel', 'password', 'number', 'date', 'time', 'datetime-local', 'month', 'week', '']);

  // Is the user typing somewhere (so letters are text, not commands)?
  function typing(e) {
    const t = e && e.target;
    if (!t || typeof t !== 'object') return false;
    if (t.isContentEditable) return true;
    const tag = String(t.tagName || '').toUpperCase();
    if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (tag === 'INPUT') return TEXT_INPUTS.has(String(t.type || '').toLowerCase());
    return Boolean(t.closest && t.closest('[role="menu"], [role="listbox"], [contenteditable="true"]'));
  }

  // Was this the key `name` ('f', 'g', '/')? The modifiers are checked by shortcut() below.
  function is(e, name) {
    const key = String((e && e.key) || '');
    if (name === '/') return key === '/' || (key.length === 1 && !LATIN.test(key) && key !== '?' && e.code === 'Slash');
    if (key.length === 1 && LATIN.test(key)) return key.toLowerCase() === name;
    return key.length === 1 && e.code === 'Key' + name.toUpperCase();   // a letter of another alphabet: the physical key
  }

  const plain = (e) => !e.metaKey && !e.ctrlKey && !e.altKey;

  // A window that takes over the whole screen (Coding Mode) keeps the app's letter shortcuts for itself; only F (full
  // screen) still works there. Set by that window: jarvisKeys.modal = () => …
  const api = {
    typing, is, plain,
    modal: () => false,
    // The plain shortcut `name`, pressed outside any text field: what every global shortcut asks.
    shortcut(e, name, { inModal = false, repeat = false } = {}) {
      if (!e || e.isComposing || e.keyCode === 229) return false;
      if (!repeat && e.repeat) return false;
      if (!is(e, name) || !plain(e) || typing(e)) return false;
      return inModal || !api.modal();
    },
  };
  root.jarvisKeys = api;   // always: Jarvis's window runs its scripts with Node's `module` defined too
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
