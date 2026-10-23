// The control overlay's only link to the rest of Jarvis: state in, button presses out.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('control', {
  onEvent: (callback) => ipcRenderer.on('control-event', (_event, message) => callback(message)),
  act: (action) => ipcRenderer.send('control-overlay-action', action),        // 'stop' | 'cancel' | 'pause' | 'resume'
  answer: (id, allow) => ipcRenderer.send('control-overlay-answer', { id, allow }),
  task: (goal) => ipcRenderer.send('control-overlay-task', String(goal)),      // a new task from the card's task box
  hovering: (on) => ipcRenderer.send('control-overlay-hover', Boolean(on)),   // let clicks reach the buttons
});
