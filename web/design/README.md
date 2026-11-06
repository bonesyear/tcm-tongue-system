# web/design — 设计资源与历史 mockup

本目录不是可运行产品。当前页面、交互和知识库入口以 `web/templates/` 与现行代码为准。

## 当前仍有用途的资源

- `assets/mock-data.js`：`tests/test_web_app.py` 用它核对拍照向导各部位的拍摄提示，删除前须同步调整该回归。
- `assets/tokens.css`、`assets/base.css`：早期视觉规范参考。实际生效样式以 `web/static/css/` 和模板为准，修改设计稿不会改变产品页面。
- `vendor/echarts.min.js`：本地图表库的历史副本；当前运行使用的资源以 `web/static/` 为准。

## 静态历史资料

`pages/` 和 `previews/` 是 2026-09-30 的静态页面与截图，只用于回看早期设计。record、settings、知识库分组、独立折叠和下载入口均已不同于这些快照，不要用它们判断当前功能。

`package.json` 与 `dev-server.js` 仅用于需要时预览这些静态页面，不参与产品构建或运行。
