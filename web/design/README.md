# web/design — 六维望诊 Web 层设计稿

静态 mockup，不是可运行产品。**时效声明（2026-10-23 审查补记）**：
`assets/tokens.css` 令牌层（色板/字体/阴影/纸纹）仍是视觉规范的单一来源；
`pages/` 中 **record 页规格已实质脱钩**（2026-09-30 快照：缺两带布局/全案卡/
调理三表/kb-refs/dose-slip/煎服法嵌条，红线数与「声明正常」语义均为旧版），
以 `web/templates/record.html` 为唯一事实；index/trends/wizard/settings 页
大体仍相符。实现交接说明见 `docs/web-design-handoff.md`（其「声明正常计入
覆盖度」「九项红线」两条同样已被后续版本修订，读时以代码与 CHANGELOG 为准）。

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
