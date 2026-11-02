"use strict";

const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const { spawn } = require("child_process");

const ROOT = path.join(__dirname, "..");
const PORT = Number(process.env.SHORTS_GUI_PORT || 8501);
const HOST = "127.0.0.1";
const BACKEND_URL = `http://${HOST}:${PORT}/`;
const CONFIG_PATH = path.join(ROOT, "config.yaml");

let backendProcess = null;
let mainWindow = null;

function resolveBackendCommand() {
  const winShorts = path.join(ROOT, ".venv", "Scripts", "shorts.exe");
  const posixShorts = path.join(ROOT, ".venv", "bin", "shorts");
  if (process.platform === "win32" && fs.existsSync(winShorts)) {
    return { cmd: winShorts, args: [] };
  }
  if (process.platform !== "win32" && fs.existsSync(posixShorts)) {
    return { cmd: posixShorts, args: [] };
  }
  // Fall back to whatever `shorts`/python is on PATH — works if the package
  // was installed into the active interpreter instead of a repo-local .venv.
  const py = process.platform === "win32" ? "python" : "python3";
  return { cmd: py, args: ["-m", "shorts.cli"] };
}

function isUp(url) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: 1500 }, (res) => {
      res.resume();
      resolve(true);
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => { req.destroy(); resolve(false); });
  });
}

async function waitForBackend(url, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await isUp(url)) return true;
    await new Promise((r) => setTimeout(r, 350));
  }
  return false;
}

function killBackend() {
  if (!backendProcess || backendProcess.killed) return;
  const pid = backendProcess.pid;
  if (process.platform === "win32") {
    // child.kill() alone leaves uvicorn's worker threads behind on Windows.
    spawn("taskkill", ["/pid", String(pid), "/T", "/F"]);
  } else {
    backendProcess.kill("SIGTERM");
  }
  backendProcess = null;
}

async function ensureBackend() {
  if (await isUp(BACKEND_URL)) {
    // A `shorts gui` instance is already running (e.g. started from a
    // terminal for debugging) — reuse it instead of spawning a second copy.
    return true;
  }
  const { cmd, args } = resolveBackendCommand();
  backendProcess = spawn(
    cmd,
    [...args, "gui", "--no-browser", "--host", HOST, "--port", String(PORT), "--config", CONFIG_PATH],
    { cwd: ROOT, stdio: ["ignore", "pipe", "pipe"] }
  );
  backendProcess.stdout.on("data", (d) => process.stdout.write(`[backend] ${d}`));
  backendProcess.stderr.on("data", (d) => process.stderr.write(`[backend] ${d}`));
  backendProcess.on("exit", (code) => {
    if (code && code !== 0 && mainWindow) {
      mainWindow.webContents.send("backend-crashed", code);
    }
    backendProcess = null;
  });
  backendProcess.on("error", (err) => {
    console.error("Failed to start backend:", err);
  });
  return waitForBackend(BACKEND_URL, 45000);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1040,
    minHeight: 680,
    backgroundColor: "#0a0b0f",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("closed", () => { mainWindow = null; });

  // External links (Buffer dashboard, etc.) open in the OS browser, not inside the app.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.loadFile(path.join(__dirname, "loading.html"));
}

ipcMain.handle("open-path", (_event, targetPath) => {
  if (typeof targetPath === "string" && targetPath) shell.openPath(targetPath);
});

app.whenReady().then(async () => {
  createWindow();
  const ready = await ensureBackend();
  if (!mainWindow) return;
  if (ready) {
    mainWindow.loadURL(BACKEND_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, "loading.html"), { query: { error: "1" } });
  }
});

app.on("window-all-closed", () => {
  killBackend();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", killBackend);

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
