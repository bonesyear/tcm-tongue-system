#!/usr/bin/env node
/* 零依赖静态服务器，仅用于设计稿本地预览。
   用法：npm run dev [-- --port 7100 --host 127.0.0.1] */
const http = require("http");
const fs = require("fs");
const path = require("path");

const args = process.argv.slice(2);
function arg(name, dft) {
  const i = args.indexOf("--" + name);
  return i >= 0 && args[i + 1] ? args[i + 1] : dft;
}
const port = Number(process.env.PORT || arg("port", 7100));
const host = process.env.HOST || arg("host", "127.0.0.1");
const root = __dirname;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
};

http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split("?")[0]);
  if (p === "/") p = "/index.html";
  const file = path.join(root, path.normalize(p));
  if (!file.startsWith(root)) { res.writeHead(403); return res.end(); }
  fs.readFile(file, (err, buf) => {
    if (err) { res.writeHead(404); return res.end("404"); }
    res.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
    res.end(buf);
  });
}).listen(port, host, () => {
  console.log(`design preview: http://${host}:${port}/`);
});
