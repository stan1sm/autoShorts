"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  isElectron: true,
  openPath: (targetPath) => ipcRenderer.invoke("open-path", targetPath),
  onBackendCrashed: (cb) => ipcRenderer.on("backend-crashed", (_e, code) => cb(code)),
});
