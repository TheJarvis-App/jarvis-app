// The Quick Access bar's only bridge to the main process (quick.js): a few named messages, no Node.js in the page.
const { contextBridge, ipcRenderer } = require('electron');

const IN = new Set(['quick:show', 'quick:focus', 'quick:will-hide', 'quick:blur', 'quick:config']);
contextBridge.exposeInMainWorld('quick', {
  ready: () => ipcRenderer.send('quick:ready'),
  size: (height) => ipcRenderer.send('quick:size', Number(height) || 0),
  hide: () => ipcRenderer.send('quick:hide'),
  hidden: () => ipcRenderer.send('quick:hidden'),
  hover: (over) => ipcRenderer.send('quick:hover', Boolean(over)),
  expand: (what) => ipcRenderer.send('quick:expand', String(what || '')),
  toggle: (source) => ipcRenderer.send('quick:toggle', String(source || '')),
  menubar: (layout) => ipcRenderer.send('quick:menubar', layout),
  on: (channel, fn) => { if (IN.has(channel)) ipcRenderer.on(channel, (_event, data) => fn(data)); },
});
