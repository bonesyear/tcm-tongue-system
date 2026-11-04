#!/usr/bin/env node
/* 真实 Chrome 回归：模型输出非 JSON 时，页面须同时说明解析失败与照片暂存状态。
 * 运行：node tests/browser/photo_staging_message.cjs
 * 保留截图和隔离日志：node tests/browser/photo_staging_message.cjs --keep-artifacts
 * 可用 CHROME_BIN 指定 Chrome；只使用隔离数据、合成图片和本地假模型。
 */
const assert = require("node:assert/strict");
const {spawn, spawnSync} = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const KEEP = process.argv.includes("--keep-artifacts");
const WORK = path.join(ROOT, ".browser-tmp", `photo-staging-${process.pid}`);
const PYTHON = process.env.PYTHON || (process.platform === "win32"
  ? path.join(ROOT, ".venv", "Scripts", "python.exe")
  : path.join(ROOT, ".venv", "bin", "python"));
const EXPECTED_STAGING = "图片已清洗并暂存，未替换已提交原图";
let browser;
let cdp;
let modelServer;
let webServer;

function delay(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

async function waitFor(action, label, timeout = 20000) {
  const deadline = Date.now() + timeout;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const value = await action();
      if (value) return value;
    } catch (error) { lastError = error; }
    await delay(100);
  }
  throw new Error(`等待超时：${label}${lastError ? `；${lastError.message}` : ""}`);
}

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function cleanEnvironment() {
  const env = {};
  for (const key of ["PATH", "Path", "SystemRoot", "SystemDrive", "WINDIR", "ComSpec",
    "PATHEXT", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS"]) {
    if (process.env[key]) env[key] = process.env[key];
  }
  const home = path.join(WORK, "home");
  for (const directory of ["AppData/Local", "AppData/Roaming", "Temp"]) {
    fs.mkdirSync(path.join(home, directory), {recursive: true});
  }
  Object.assign(env, {
    HOME: home,
    USERPROFILE: home,
    APPDATA: path.join(home, "AppData", "Roaming"),
    LOCALAPPDATA: path.join(home, "AppData", "Local"),
    TEMP: path.join(home, "Temp"),
    TMP: path.join(home, "Temp"),
    PYTHONUTF8: "1",
    PYTHONDONTWRITEBYTECODE: "1",
  });
  return env;
}

function chromeExecutable() {
  const candidates = [
    process.env.CHROME_BIN,
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ].filter(Boolean);
  const found = candidates.find(candidate => fs.existsSync(candidate));
  if (!found) throw new Error("未找到 Chrome，请通过 CHROME_BIN 指定可执行文件");
  return found;
}

function stopProcessTree(child) {
  if (!child || child.exitCode !== null || child.signalCode) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(child.pid), "/t", "/f"],
      {stdio: "ignore", windowsHide: true});
  } else {
    child.kill("SIGTERM");
  }
}

async function waitProcessExit(child, label) {
  if (!child || child.exitCode !== null || child.signalCode) return;
  await waitFor(() => child.exitCode !== null || child.signalCode, `${label}退出`, 8000);
}

class CDP {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 0;
    this.pending = new Map();
    this.listeners = new Map();
    socket.addEventListener("message", event => {
      const message = JSON.parse(String(event.data));
      if (message.id) {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        clearTimeout(pending.timer);
        if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
        else pending.resolve(message.result || {});
        return;
      }
      for (const listener of this.listeners.get(message.method) || []) listener(message);
    });
    socket.addEventListener("close", () => {
      for (const pending of this.pending.values()) {
        clearTimeout(pending.timer);
        pending.reject(new Error("Chrome 调试连接已关闭"));
      }
      this.pending.clear();
    });
  }

  static async connect(url) {
    const socket = new WebSocket(url);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Chrome 调试连接超时")), 10000);
      socket.addEventListener("open", () => { clearTimeout(timer); resolve(); }, {once: true});
      socket.addEventListener("error", () => { clearTimeout(timer); reject(new Error("Chrome 调试连接失败")); }, {once: true});
    });
    return new CDP(socket);
  }

  send(method, params = {}, sessionId) {
    const id = ++this.nextId;
    const message = {id, method, params};
    if (sessionId) message.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP 调用超时：${method}`));
      }, 15000);
      this.pending.set(id, {resolve, reject, timer});
      this.socket.send(JSON.stringify(message));
    });
  }

  on(method, listener) {
    if (!this.listeners.has(method)) this.listeners.set(method, []);
    this.listeners.get(method).push(listener);
  }
}

async function main() {
  fs.mkdirSync(WORK, {recursive: true});
  const data = path.join(WORK, "data");
  const newPhoto = path.join(WORK, "new-photo.jpg");
  const prepare = spawnSync(PYTHON, ["-c", `
import datetime
import json
import sys
from pathlib import Path
from PIL import Image
root = Path(sys.argv[1])
data = Path(sys.argv[2])
date = datetime.datetime.now().astimezone().date().isoformat()
photos = data / "records" / "photos" / date
photos.mkdir(parents=True, exist_ok=True)
(data / "records" / "daily").mkdir(parents=True, exist_ok=True)
old = photos / "舌面.jpg"
Image.new("RGB", (12, 12), (90, 90, 90)).save(old, format="JPEG")
Image.new("RGB", (12, 12), (150, 120, 100)).save(root / "new-photo.jpg", format="JPEG")
print(json.dumps({"date": date, "old_photo": str(old)}, ensure_ascii=False))
`, WORK, data], {cwd: ROOT, encoding: "utf8", env: cleanEnvironment()});
  assert.equal(preparedStatus(prepare), 0, `隔离图片准备失败：${prepare.stdout}\n${prepare.stderr}`);
  const prepared = JSON.parse(prepare.stdout.trim());
  const oldHash = sha256(prepared.old_photo);

  const modelCalls = [];
  modelServer = http.createServer((request, response) => {
    let raw = "";
    request.on("data", chunk => {
      raw += chunk;
      if (raw.length > 8 * 1024 * 1024) request.destroy();
    });
    request.on("end", () => {
      const body = JSON.parse(raw || "{}");
      modelCalls.push(body);
      assert.equal(request.url, "/v1/chat/completions");
      assert.equal(request.headers.authorization, "Bearer acceptance-local-key");
      response.writeHead(200, {"Content-Type": "application/json; charset=utf-8"});
      response.end(JSON.stringify({choices: [{message: {role: "assistant", content: "not-json"}, finish_reason: "stop"}]}));
    });
  });
  await new Promise((resolve, reject) => {
    modelServer.once("error", reject);
    modelServer.listen(0, "127.0.0.1", resolve);
  });
  const modelPort = modelServer.address().port;
  const envFile = path.join(WORK, "isolated.env");
  fs.writeFileSync(envFile, [
    "VISION_API_KEY=acceptance-local-key",
    `VISION_BASE_URL=http://127.0.0.1:${modelPort}/v1`,
    "VISION_MODEL=synthetic-vision",
    "LLM_DISABLED=1",
    "",
  ].join("\n"), "utf8");

  const portProbe = net.createServer();
  await new Promise(resolve => portProbe.listen(0, "127.0.0.1", resolve));
  const webPort = portProbe.address().port;
  await new Promise(resolve => portProbe.close(resolve));
  const serverLog = fs.createWriteStream(path.join(WORK, "web.log"));
  webServer = spawn(PYTHON, ["-c", `
import sys
sys.path.insert(0, sys.argv[4])
from app import create_app
from server import serve_http
app = create_app(env_file=sys.argv[1], data_root=sys.argv[2])
serve_http(app, "127.0.0.1", int(sys.argv[3]))
`, envFile, data, String(webPort), path.join(ROOT, "web")], {
    cwd: ROOT, env: cleanEnvironment(), shell: false, windowsHide: true,
  });
  webServer.stdout.pipe(serverLog);
  webServer.stderr.pipe(serverLog);
  const base = `http://127.0.0.1:${webPort}`;
  await waitFor(async () => (await fetch(`${base}/welcome`)).status === 200, "隔离 Web 服务");

  const browserLog = fs.createWriteStream(path.join(WORK, "chrome.log"));
  browser = spawn(chromeExecutable(), [
    "--headless=new", "--remote-debugging-port=0", `--user-data-dir=${path.join(WORK, "chrome-profile")}`,
    "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
    "--disable-component-update", "--disable-sync", "--disable-extensions",
    "--disable-default-apps", "--no-proxy-server", "--window-size=1280,900", "about:blank",
  ], {cwd: WORK, env: cleanEnvironment(), shell: false, windowsHide: true});
  browser.stdout.pipe(browserLog);
  let stderr = "";
  browser.stderr.on("data", chunk => { stderr += chunk; browserLog.write(chunk); });
  const wsUrl = await waitFor(() => {
    const match = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/);
    return match && match[1];
  }, "Chrome 调试端口");
  cdp = await CDP.connect(wsUrl);
  const {targetId} = await cdp.send("Target.createTarget", {url: "about:blank"});
  const {sessionId} = await cdp.send("Target.attachToTarget", {targetId, flatten: true});
  await cdp.send("Page.enable", {}, sessionId);
  await cdp.send("Runtime.enable", {}, sessionId);
  await cdp.send("Network.enable", {}, sessionId);
  await cdp.send("DOM.enable", {}, sessionId);
  const statuses = [];
  const exceptions = [];
  cdp.on("Network.responseReceived", message => {
    if (message.sessionId === sessionId && message.params.response.url.includes("/wizard/photo")) {
      statuses.push(message.params.response.status);
    }
  });
  cdp.on("Runtime.exceptionThrown", message => {
    if (message.sessionId === sessionId) exceptions.push(message.params.exceptionDetails);
  });
  const evaluate = async expression => {
    const result = await cdp.send("Runtime.evaluate", {
      expression, returnByValue: true, awaitPromise: true, userGesture: true,
    }, sessionId);
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result && result.result.value;
  };
  const navigate = async url => {
    await cdp.send("Page.navigate", {url}, sessionId);
    await waitFor(() => evaluate(`location.href === ${JSON.stringify(url)} && document.readyState === "complete"`), `页面 ${url}`);
  };

  await navigate(`${base}/welcome`);
  await evaluate(`(() => {
    document.querySelectorAll(".ack").forEach(box => box.click());
    document.getElementById("enter-btn").click();
    return true;
  })()`);
  await waitFor(() => evaluate(`location.pathname !== "/welcome" && document.readyState === "complete"`), "须知确认跳转");
  const wizardUrl = `${base}/wizard?new=1`;
  await navigate(wizardUrl);
  await waitFor(() => evaluate(`!!document.getElementById("file-input")`), "拍照向导");
  const {root} = await cdp.send("DOM.getDocument", {depth: 0}, sessionId);
  const {nodeId} = await cdp.send("DOM.querySelector", {nodeId: root.nodeId, selector: "#file-input"}, sessionId);
  assert.ok(nodeId, "照片文件输入存在");
  await cdp.send("DOM.setFileInputFiles", {nodeId, files: [newPhoto]}, sessionId);
  await waitFor(() => evaluate(`(() => {
    const alert = document.getElementById("wizard-alert");
    return alert && alert.textContent.includes("识图输出不是合法 JSON") &&
      getComputedStyle(alert).display !== "none" && !document.getElementById("file-input").disabled;
  })()`), "模型失败提示");

  const page = await evaluate(`(() => {
    const alert = document.getElementById("wizard-alert");
    const observation = document.getElementById("obs-box");
    const rect = alert.getBoundingClientRect();
    return {
      alert: alert.textContent,
      role: alert.getAttribute("role"),
      status: document.getElementById("step-status").textContent,
      observationVisible: getComputedStyle(observation).display !== "none",
      inputDisabled: document.getElementById("file-input").disabled,
      rect: {x: rect.left + scrollX, y: rect.top + scrollY, width: rect.width, height: rect.height},
    };
  })()`);
  const screenshot = await cdp.send("Page.captureScreenshot", {
    format: "jpeg", quality: 85,
    clip: {x: Math.max(0, page.rect.x - 16), y: Math.max(0, page.rect.y - 16),
      width: page.rect.width + 32, height: page.rect.height + 32, scale: 1},
  }, sessionId);
  fs.writeFileSync(path.join(WORK, "photo-staging-message.jpg"), Buffer.from(screenshot.data, "base64"));

  assert.deepEqual(statuses, [502], "异常识图返回 HTTP 502");
  assert.equal(page.role, "alert");
  assert.equal(page.inputDisabled, false, "失败后文件输入恢复可操作");
  assert.equal(page.observationVisible, false, "失败后不显示观察结果");
  assert.ok(!page.status.includes("已识图"), "失败后不显示已识图状态");
  assert.equal(modelCalls.length, 1, "本地假模型收到一次请求");
  assert.equal(sha256(prepared.old_photo), oldHash, "旧正式图字节保持不变");
  const staging = path.join(data, "records", "photos", prepared.date, ".staging");
  const staged = fs.existsSync(staging) ? fs.readdirSync(staging).filter(name => name.endsWith(".jpg")) : [];
  assert.equal(staged.length, 1, "清洗后的新图保留一份暂存副本");
  assert.ok(page.alert.includes(EXPECTED_STAGING),
    `失败提示应说明「${EXPECTED_STAGING}」，实际为：${page.alert}`);
  assert.equal(page.alert.split(EXPECTED_STAGING).length - 1, 1, "暂存提示不应重复");
  assert.deepEqual(exceptions, [], "浏览器无未捕获 JavaScript 异常");
  console.log(JSON.stringify({
    result: "BROWSER_REGRESSION_OK",
    http_status: 502,
    staging_message: EXPECTED_STAGING,
    old_photo_unchanged: true,
    staged_photo_count: 1,
    screenshot: path.join(WORK, "photo-staging-message.jpg"),
  }, null, 2));
}

function preparedStatus(result) {
  if (result.error) throw result.error;
  return result.status;
}

(async () => {
  let failure;
  try {
    await main();
  } catch (error) {
    failure = error;
  }
  try {
    if (cdp) {
      try { await cdp.send("Browser.close"); } catch (_) {}
      try { cdp.socket.close(); } catch (_) {}
    }
    stopProcessTree(browser);
    stopProcessTree(webServer);
    await Promise.all([
      waitProcessExit(browser, "Chrome"),
      waitProcessExit(webServer, "隔离 Web 服务"),
    ]);
    if (modelServer) {
      modelServer.closeAllConnections();
      await new Promise(resolve => modelServer.close(resolve));
    }
    if (!KEEP) fs.rmSync(WORK, {recursive: true, force: true, maxRetries: 10, retryDelay: 200});
    else console.log(`ARTIFACTS ${WORK}`);
  } catch (cleanupError) {
    if (failure) console.error(`清理隔离环境时另有错误：${cleanupError.message}`);
    else failure = cleanupError;
  }
  if (failure) throw failure;
})().catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
