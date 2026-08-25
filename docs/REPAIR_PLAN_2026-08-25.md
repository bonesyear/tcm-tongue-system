# 修改执行规划（tcm-tongue-system，2026-08-25 定案）

> 来源：Kimi 代码审查（docs/CODE_REVIEW_2026-08-25_KIMI.md，18 条问题）+ "干燥/润泽"专项审查（方案 A）。
> 状态：**已定案，待 kimi 额度重置后执行**。执行时按文件域分 3 轮，域内按严重度。
> 铁律：每轮改完跑全量测试（159）+ 相关实测；kimi 修复后须 review diff + 独立复验再提交。

## 总览

- 已消条目：#4（.env 注释）、#18（docstring）、增量 A/B（load_key 合并/assert 文案）
- 跳过：#17（prompt emoji，收益低）
- 待修：**14 条**，分 3 轮
- 执行顺序：轮次 1（vision_client.py）→ 轮次 2（辨证层）→ 轮次 3（文档层）

---

## 轮次 1 — scripts/vision_client.py（6 条）

| 序 | # | 问题 | 改动要点 | 验证 |
|---|---|---|---|---|
| 1 | #2 | API/网络错误无处理→KeyError 裸崩 | call() 捕获 HTTPError/URLError/socket.timeout；无 choices 检查；抛 RuntimeError 带状态码/摘要 | mock 4xx/5xx/缺 choices 断言非 KeyError |
| 2 | #3 | 命令行参数无边界检查 | 入口校验 len(sys.argv)；classify≥3/observe≥4；不足 exit(2)+用法 | subprocess 缺参断言退出码 2 |
| 3 | #1 | 文件句柄未关闭 | `with open(img_path,"rb") as f:` 包住 b64 读取 | 代码审查 |
| 4 | #6 | 图片 MIME 写死 jpeg | 扩展名→MIME（.png/.jpg/.jpeg/.webp），未知回退 jpeg | 各扩展名断言 payload url 前缀 |
| 5 | #7 | classify 不校验输出类别 | 输出 strip 取首行匹配 PROMPTS keys；不匹配回退"其他"+stderr 警告 | mock 未知类别断言回退 |
| 6 | #14 | 无测试覆盖 | 新建 tests/test_vision_qwen.py：正常/HTTP错误/参数/key未设/.env注释/MIME/类别 | 新增+全量通过 |

**中断风险**：完成 #2/#3 即可安全发布；#2 前中断 → API 失败仍裸崩（最坏）。

## 轮次 2 — 辨证层（confidence + scoring + record，7 条）

| 序 | # | 问题 | 改动要点 | 验证 |
|---|---|---|---|---|
| 1 | #5 | 否定词"非"误杀"非正常" | _NEGATION_RE 移除"非"（无/不/未/没 已够） | "非正常红润/非典型黄染"不否定断言 |
| 2 | #8 | has_formula_content key 白名单漏检 | 保留白名单+兜底扫描剂量模式 \d+[g克]/经方名 | {"description":"含桂枝10g"}判有方 |
| 3 | #9 | fallback 返回整个 diag | 形状 A 找不到键返回 {}（或显式历史 key 尝试） | shape A 缺键不污染 |
| 4 | #10 | 英文词边界不严（HIGH1→HIGH） | 只认空格/连字符/CJK/结尾为边界 | HIGH1/HIGH_2 → None |
| 5 | #11 | 舌诊均值缺测试 | body=7+coating=7 其余 0 → score==7.0 | 新增断言（#5 后做） |
| 6 | #12 | danger_flags 形状 A 无测试 | shape A fixture daiyang.triggered=true → ["daiyang"] | 新增测试 |
| 7 | #13 | 干燥/润泽方案 A 落地（见下） | 11 项落地清单 | 见专项 |

**中断风险**：#5 前中断 → 评分误杀"非正常"（影响辨证，最坏）；#5/#8/#9 完成 → 安全边界已修。

### #13 方案 A 落地清单（11 项）

1. `vision_client.py` PROMPTS["舌面"] 加"舌质润泽/干燥（粗判：润泽/偏干/干燥/干裂）"
2. `record.py` body_luster A 路径 ["舌质荣枯"] → ["舌质润燥"]（B 路径保留）
3. `scoring.py` DIMENSION_RULES[TONGUE] **移除 body_luster**（不再 score()）
4. `scoring.py` TONGUE_BODY_LUSTER_MAP 保留+注释"已降级仅历史兼容"
5. `scoring.py` 评分基线注释删"荣润"示例
6. `scoring.py` TONGUE_RADAR_METRIC_KEYS 加注释（照片光线干扰、静态不可判神气）
7. `tests/test_scoring.py` 删/改 test_body_luster_scoring（分数 0/不存在）
8. `tests/test_scoring.py` 正常舌象 fixture 删 body_luster 或期望 0
9. `tests/test_record.py` 补"舌质润燥"路径解析测试
10. `tests/fixtures/2026-06-25_analysis.json` score 期望更新（**历史评分口径变化**，正确方向）
11. `templates/multi_dim_record_template.json` "舌质荣枯"→"舌质润燥"

语义：干燥/润泽**评分层降级**（不计分、不进雷达图），**辨证层保留**（LLM prompt 参考，津亏/湿盛辅助信号）。双计：结构化输入不双计（独立字段），纯文本重复计分是既有已知局限。

## 轮次 3 — 文档层（2 条）

| # | 问题 | 改动 |
|---|---|---|
| 15 | confidence.py:9 引用不存在的 dimension-overlap-analysis.md | 改指 templates/adaptive_analysis_prompt.md §3.1 |
| 16 | record.py:23 / dimensions.py:13 引用 /codebase-design | 删除或改指实际文档 |

**中断无运行时风险**。

---

## 依赖关系

```
#14 测试 ← #2/#3/#6/#7 修完
#11 测试 ← #5 之后
#13 ← 独立已定案
```

## 验证总要求

- 每轮：pytest tests/ -q 全量通过；vision_client.py 改动后实测 `python3 scripts/vision_client.py classify <图>` 输出"舌面"
- 提交前：kimi 报告后自行 git diff review + 独立复验（测试/实测/ruff check --select F,E722）
- 每轮独立 commit（不混批次）
