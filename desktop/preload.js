const { contextBridge, ipcRenderer } = require("electron");

// The first-start page only needs to read what the setup prints.
contextBridge.exposeInMainWorld("setup", {
  onLog: (callback) => ipcRenderer.on("setup-log", (_event, text) => callback(text)),
});
