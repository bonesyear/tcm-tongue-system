#!/usr/bin/env node
/* 真实 Chrome 回归：知识库默认折叠、五个独立开关、失败回滚与窄屏。
 * 运行：node tests/browser/kb_switches.cjs
 * 保留截图和隔离日志：node tests/browser/kb_switches.cjs --keep-artifacts
 * 可用 CHROME_BIN 指定 Chrome；只使用隔离配置和合成知识库。
 */
const assert = require("node:assert/strict");
const {spawn, spawnSync} = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const KEEP = process.argv.includes("--keep-artifacts");
const WORK = path.join(ROOT, ".browser-tmp", `kb-switches-${process.pid}`);
const PYTHON = process.env.PYTHON || (process.platform === "win32"
  ? path.join(ROOT, ".venv", "Scripts", "python.exe")
  : path.join(ROOT, ".venv", "bin", "python"));
let browser;
let cdp;
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
    HOME: home, USERPROFILE: home,
    APPDATA: path.join(home, "AppData", "Roaming"),
    LOCALAPPDATA: path.join(home, "AppData", "Local"),
    TEMP: path.join(home, "Temp"), TMP: path.join(home, "Temp"),
    PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1",
  });
  return env;
}

function chromeExecutable() {
  const candidates = [
    process.env.CHROME_BIN,
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
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
  } else child.kill("SIGTERM");
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

function readEnv(file) {
  const values = {};
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    if (!line || line.startsWith("#")) continue;
    const index = line.indexOf("=");
    if (index > 0) values[line.slice(0, index)] = line.slice(index + 1);
  }
  return values;
}

async function main() {
  fs.mkdirSync(WORK, {recursive: true});
  const data = path.join(WORK, "data");
  const kbRoot = path.join(WORK, "kb");
  const envFile = path.join(WORK, "isolated.env");
  const names = {constitution: "体质", diet: "食疗", formula: "方剂"};
  const lines = ["VISION_DISABLED=1", "LLM_DISABLED=1", "TCM_KB_ALLOW_EXTERNAL_KB=1"];
  for (const category of Object.keys(names)) {
    const root = path.join(kbRoot, category);
    fs.mkdirSync(root, {recursive: true});
    fs.writeFileSync(path.join(root, "synthetic.md"), `# 合成${names[category]}资料\n仅用于隔离界面验收。\n`, "utf8");
    lines.push(`TCM_KB_${category.toUpperCase()}_ROOT=${root}`);
  }
  const composite = path.join(kbRoot, "composite");
  fs.mkdirSync(composite, {recursive: true});
  fs.writeFileSync(path.join(composite, "synthetic.md"), "# 合成综合资料\n仅用于隔离界面验收。\n", "utf8");
  lines.push(`TCM_KB_ROOT=${composite}`, "TCM_KB_DIET_DISABLED=1", "");
  fs.writeFileSync(envFile, lines.join("\n"), "utf8");

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
  const gated = await fetch(`${base}/settings`, {redirect: "manual"});
  assert.equal(gated.status, 302, "未确认须知时设置页必须拦截");
  assert.equal(gated.headers.get("location"), "/welcome");

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
  const exceptions = [];
  const toggleStatuses = [];
  cdp.on("Runtime.exceptionThrown", message => {
    if (message.sessionId === sessionId) exceptions.push(message.params.exceptionDetails);
  });
  cdp.on("Network.responseReceived", message => {
    if (message.sessionId === sessionId && new URL(message.params.response.url).pathname === "/settings/toggle") {
      toggleStatuses.push(message.params.response.status);
    }
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
  const waitSave = async (target, desired) => {
    await waitFor(() => evaluate(`location.pathname === "/settings" && document.readyState === "complete" &&
      (() => {
        const input = document.querySelector('[data-kb-toggle="${target}"]');
        return input && !input.disabled && input.checked === ${desired} &&
          !document.getElementById("kb-categories-card").open;
      })()`), `${target} 开关保存后刷新`);
  };
  const expandGroup = async () => {
    await physicalClick(".kb-group-head");
    await waitFor(() => evaluate(`document.getElementById("kb-categories-card").open &&
      document.querySelector(".kb-group-body").getBoundingClientRect().height > 100`), "标题真实点击展开");
  };
  const physicalClick = async selector => {
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block: "center"})`);
    const point = await evaluate(`(() => {
      const rect = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();
      return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
    })()`);
    for (const type of ["mousePressed", "mouseReleased"]) {
      await cdp.send("Input.dispatchMouseEvent", {...point, type, button: "left", clickCount: 1}, sessionId);
    }
  };
  const clickAndSave = async target => {
    const before = await evaluate(`document.querySelector('[data-kb-toggle="${target}"]').checked`);
    await physicalClick(`[data-kb-toggle="${target}"]`);
    await waitSave(target, !before);
    const after = await evaluate(`document.querySelector('[data-kb-toggle="${target}"]').checked`);
    assert.notEqual(after, before, `${target} 开关持久化后状态应改变`);
  };
  const switchStates = () => evaluate(`Object.fromEntries([...document.querySelectorAll("[data-kb-toggle]")].map(input => [input.dataset.kbToggle, input.checked]))`);
  const noOverflow = () => evaluate(`document.documentElement.scrollWidth <= window.innerWidth &&
    document.body.scrollWidth <= window.innerWidth`);
  const screenshot = async (selector, filename) => {
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block: "start"})`);
    await delay(100);
    const image = await cdp.send("Page.captureScreenshot", {format: "jpeg", quality: 88}, sessionId);
    fs.writeFileSync(path.join(WORK, filename), Buffer.from(image.data, "base64"));
  };

  await navigate(`${base}/welcome`);
  await evaluate(`(() => {
    document.querySelectorAll(".ack").forEach(box => box.click());
    document.getElementById("enter-btn").click();
  })()`);
  await waitFor(() => evaluate(`location.pathname !== "/welcome" && document.readyState === "complete"`), "须知确认");
  await navigate(`${base}/settings`);
  assert.equal(await evaluate(`document.getElementById("kb-categories-card").open`), false, "子知识库默认折叠");
  assert.deepEqual(await switchStates(), {
    kb_categories: true, kb_constitution: true, kb_diet: false,
    kb_formula: true, kb_composite: true,
  });
  await screenshot("#kb-import-card", "desktop-collapsed.jpg");
  await evaluate(`document.querySelector(".kb-group-toggle").scrollIntoView({block: "center"})`);
  assert.equal(await evaluate(`(() => {
    const rect = document.querySelector(".kb-group-toggle").getBoundingClientRect();
    return document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
      ?.dataset.kbToggle;
  })()`), "kb_categories", "折叠状态下整组开关必须真实可见可点击");

  await evaluate(`(() => {
    window.originalFetch = window.fetch;
    window.fetch = async function (url, options) {
      return String(url).endsWith("/settings/toggle")
        ? new Response(JSON.stringify({ok: false, error: "合成保存失败"}),
          {status: 500, headers: {"Content-Type": "application/json"}})
        : window.originalFetch(url, options);
    };
  })()`);
  await physicalClick('[data-kb-toggle="kb_categories"]');
  await waitFor(() => evaluate(`document.getElementById("top-toast")?.textContent.includes("合成保存失败")`), "失败提示");
  assert.equal(await evaluate(`document.querySelector('[data-kb-toggle="kb_categories"]').checked`), true, "失败后恢复原开关");
  assert.equal(await evaluate(`document.querySelector('[data-kb-toggle="kb_categories"]').disabled`), false, "失败后恢复操作");
  assert.equal(await evaluate(`document.getElementById("kb-categories-card").open`), false, "整组开关不触发展开");
  assert.equal(readEnv(envFile).TCM_KB_CATEGORIES_DISABLED || "", "", "失败不写入配置");
  await evaluate(`window.fetch = window.originalFetch`);

  await clickAndSave("kb_categories");
  assert.equal(readEnv(envFile).TCM_KB_CATEGORIES_DISABLED, "1");
  await expandGroup();
  assert.deepEqual(await switchStates(), {
    kb_categories: false, kb_constitution: true, kb_diet: false,
    kb_formula: true, kb_composite: true,
  }, "整组关闭保留子库自身选择");
  assert.equal(await evaluate(`["constitution", "diet", "formula"].every(c =>
    document.getElementById("kb-status-label-" + c).textContent === "整组已停用")`), true);

  await clickAndSave("kb_composite");
  assert.equal(readEnv(envFile).TCM_KB_COMPOSITE_DISABLED, "1");
  await expandGroup();
  await clickAndSave("kb_diet");
  await expandGroup();
  assert.deepEqual(await switchStates(), {
    kb_categories: false, kb_constitution: true, kb_diet: true,
    kb_formula: true, kb_composite: false,
  }, "整组关闭时仍可保存子库偏好");
  assert.equal(readEnv(envFile).TCM_KB_CATEGORIES_DISABLED, "1");
  assert.equal(readEnv(envFile).TCM_KB_DIET_DISABLED || "", "");
  assert.equal(await evaluate(`document.getElementById("kb-status-label-diet").textContent`), "整组已停用");

  await clickAndSave("kb_constitution");
  await expandGroup();
  await clickAndSave("kb_formula");
  await clickAndSave("kb_categories");
  await expandGroup();
  assert.deepEqual(await switchStates(), {
    kb_categories: true, kb_constitution: false, kb_diet: true,
    kb_formula: false, kb_composite: false,
  }, "恢复整组后保留各子库最新选择");
  assert.equal(await evaluate(`document.getElementById("kb-status-label-diet").textContent`), "知识库可用");
  assert.equal(await evaluate(`document.getElementById("kb-status-label-constitution").textContent`), "已停用");
  await clickAndSave("kb_constitution");
  await expandGroup();
  await clickAndSave("kb_formula");
  await clickAndSave("kb_composite");
  await expandGroup();
  assert.deepEqual(await switchStates(), {
    kb_categories: true, kb_constitution: true, kb_diet: true,
    kb_formula: true, kb_composite: true,
  });
  assert.equal(await noOverflow(), true, "桌面无横向溢出");
  await screenshot("#kb-import-card", "desktop-expanded.jpg");

  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 390, height: 844, deviceScaleFactor: 1, mobile: true,
  }, sessionId);
  await navigate(`${base}/settings`);
  assert.equal(await noOverflow(), true, "390px 默认折叠无横向溢出");
  await expandGroup();
  assert.equal(await noOverflow(), true, "390px 展开后无横向溢出");
  await evaluate(`document.querySelector(".kb-group-toggle").scrollIntoView({block: "center"})`);
  assert.equal(await evaluate(`(() => {
    const card = document.getElementById("kb-categories-card").getBoundingClientRect();
    const toggle = document.querySelector(".kb-group-toggle").getBoundingClientRect();
    const summary = document.querySelector(".kb-group-head").getBoundingClientRect();
    return toggle.left >= card.left && toggle.right <= card.right &&
      toggle.top >= summary.top && toggle.bottom <= summary.bottom &&
      document.elementFromPoint(toggle.left + toggle.width / 2, toggle.top + toggle.height / 2)
        ?.dataset.kbToggle === "kb_categories";
  })()`), true, "折叠头开关不遮挡且在可点击区域");
  await screenshot("#kb-import-card", "mobile-expanded.jpg");
  assert.equal(toggleStatuses.length, 9, "五个开关共完成九次真实保存");
  assert.ok(toggleStatuses.every(status => status === 200), "真实开关请求全部成功");
  assert.deepEqual(exceptions, [], "浏览器无未捕获 JavaScript 异常");
  const saved = readEnv(envFile);
  for (const key of ["TCM_KB_CATEGORIES_DISABLED", "TCM_KB_COMPOSITE_DISABLED",
    "TCM_KB_CONSTITUTION_DISABLED", "TCM_KB_DIET_DISABLED", "TCM_KB_FORMULA_DISABLED"]) {
    assert.equal(saved[key] || "", "", `${key} 最终恢复启用`);
  }
  console.log(JSON.stringify({
    result: "BROWSER_REGRESSION_OK",
    welcome_gate: true, default_collapsed: true, independent_switches: 5,
    successful_toggle_requests: toggleStatuses.length,
    failure_rollback: true, sublibrary_preferences_preserved: true,
    desktop_overflow: false, mobile_390px_overflow: false,
    javascript_exceptions: exceptions.length,
    screenshots: ["desktop-collapsed.jpg", "desktop-expanded.jpg", "mobile-expanded.jpg"].map(file => path.join(WORK, file)),
  }, null, 2));
}

(async () => {
  let failure;
  try { await main(); } catch (error) { failure = error; }
  try {
    if (cdp) {
      try { await cdp.send("Browser.close"); } catch (_) {}
      try { cdp.socket.close(); } catch (_) {}
    }
    stopProcessTree(browser);
    stopProcessTree(webServer);
    await Promise.all([waitProcessExit(browser, "Chrome"), waitProcessExit(webServer, "隔离 Web 服务")]);
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
