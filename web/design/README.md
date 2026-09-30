# web/design — 六维望诊 Web 层设计稿

静态 mockup，不是可运行产品。视觉系统与页面规格的单一来源，
实现交接说明见 `docs/web-design-handoff.md`。

## 预览

```bash
npm run dev            # → http://127.0.0.1:7100/
# 或直接用浏览器打开 pages/index.html（无 fetch 依赖，file:// 可跑）
```

## 目录

- `assets/tokens.css` — 设计令牌（色板/字体/阴影/纸纹），实现只准消费变量
- `assets/base.css` — 共用组件（印章 logo、卡片、分数徽章+进度条、步骤条、弹层、表单）
- `assets/mock-data.js` — 演示数据，结构对齐记录形状 B 与周报 dict
- `pages/` — 记录列表 / 单日详情 / 趋势 / 拍照向导 / 设置
- `vendor/echarts.min.js` — ECharts 5.6.0 本地版（一切 JS/CSS vendor 到本地）
- `previews/` — 2026-09-30 实测渲染截图
