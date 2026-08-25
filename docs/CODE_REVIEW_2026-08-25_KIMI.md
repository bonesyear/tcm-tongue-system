• # 完整代码审查与修改规划文档

  > 审查范围：`scripts/vision_qwen.py`、`src/confidence.py`、`src/record.py`、`src/scoring.py`、`tests/`。  
  > 审查纪律：编码规范/Fowler 坏味道 + 功能忠实度 + ponytail + karpathy-guidelines。  
  > 未修改任何文件，未执行 git 操作。

  ---

  # A) 代码审查报告

  ## 严重级

  ### 1. `scripts/vision_qwen.py:39` 文件句柄未关闭
  - **问题描述**：`b64 = base64.b64encode(open(img_path, "rb").read()).decode()` 未使用 `with` 关闭文件。
  - **理由**：小文件在 CPython 中通常会被快速回收，但这是基础资源泄漏模式；脚本若被以库方式导入或处理大量图片时会累积 open fd。Fowler：重复/不一致的资源管理坏味道。
  - **修复建议**：改为 `with open(img_path, "rb") as f: b64 = base64.b64encode(f.read()).decode()`。

  ### 2. `scripts/vision_qwen.py:51-54` 网络/API 失败无处理，直接 KeyError
  - **问题描述**：`urllib.request.urlopen` 不处理 `HTTPError`、`URLError`、`timeout`；返回后直接从 `data["choices"][0]["message"]` 取值。
  - **理由**：DashScope 返回 4xx/5xx 或限流时，`data` 中可能没有 `choices`，会抛 `KeyError` 裸异常，调用方看不到真实错误原因。这是信任边界（外部 API）缺错误处理的典型问题。
  - **修复建议**：捕获 `urllib.error.HTTPError` 读取响应体，`json.loads` 前检查 `data.get("choices")`，并返回/打印结构化错误信息。

  ### 3. `scripts/vision_qwen.py:57-58, 63` 命令行参数无边界检查
  - **问题描述**：直接访问 `sys.argv[1]`、`sys.argv[2]`、`sys.argv[3]`，参数不足时抛 `IndexError`。
  - **理由**：脚本入口应对用户输入做最小校验，裸 IndexError 是糟糕的 CLI 体验，也与 docstring 的用法约定不一致。
  - **修复建议**：在 `if __name__ == "__main__"` 开头检查 `len(sys.argv)`，参数不足时打印用法并 `sys.exit(2)`。

  ### 4. `scripts/vision_qwen.py:10-20` `.env` 解析不处理注释行
  - **问题描述**：`if line.startswith("DASHSCOPE_API_KEY=")` 会匹配被注释掉的行，如 `# DASHSCOPE_API_KEY=leaked`。
  - **理由**：key 读取安全要求注释内容不得被误读为真实配置；当前解析器过于朴素，存在配置污染风险。
  - **修复建议**：跳过空行和以 `#` 开头的行，再匹配 key；或直接用标准库 `configparser` 读取 `.env`（若文件格式兼容），最小改动是加 `if line.startswith("#"): continue`。

  ### 5. `src/scoring.py:205` 否定词“非”仅排除“非常”，会误杀“非正常”等
  - **问题描述**：`_NEGATION_RE = re.compile(r"无|不|未|没|非(?!常)")` 中 `(?!常)` 只排除“非常”，不排除“非正常”“非典型”等。
  - **理由**：医学描述中可能出现“非正常红润”“非典型黄染”，当前规则会把“非”识别为否定而误将真阳性抹零。这是否定守卫的边界假设未充分暴露。
  - **修复建议**：把“非”从通用否定词中移除，或增加常见例外白名单（如“非正常”“非典型”“非感染性”）；若保留“非”，需在注释/测试中明确其已知局限。

  ---

  ## 建议级

  ### 6. `scripts/vision_qwen.py:43` 图片格式未验证，统一写死 `image/jpeg`
  - **问题描述**：base64 后统一使用 `data:image/jpeg;base64,{b64}`，不区分实际格式。
  - **理由**：用户传入 PNG 时 MIME 与实际字节不一致，可能导致 API 侧解析异常或质量下降。最小校验成本很低。
  - **修复建议**：按文件扩展名（`.png`/`.jpg`/`.jpeg`/`.webp`）设置对应 MIME type；扩展名未知时仍回退 `image/jpeg` 并加注释。

  ### 7. `scripts/vision_qwen.py:60` `classify` 不验证模型输出是否在预定义类别中
  - **问题描述**：`print(out.strip())` 直接输出模型返回，未校验是否为“舌面/舌底/头面部/眼部/耳部/手掌/皮肤/其他”之一。
  - **理由**：LLM 可能输出多余解释、标点或幻觉类别，下游 `observe` 用该字符串查 `PROMPTS` 会回退到“其他”。
  - **修复建议**：对输出做简单后处理（strip、取首行、匹配字典 key），不匹配时输出错误提示或回退“其他”并打印警告。

  ### 8. `src/record.py:142-148` `has_formula_content` 的 key 列表是硬编码白名单，可能漏检
  - **问题描述**：`content_keys` 只列了 9 个 key，若 LLM 输出用其他字段（如 `prescription`、`formula_text`、`方药`）承载方剂，安全检查会放行。
  - **理由**：这是安全边界检查，fail-closed 要求宁可误判也要避免漏判；但无限扩展 key 列表又会变成维护负担。
  - **修复建议**：保留当前 key 列表并加一个兜底规则——若 dict 中任意 string 值包含剂量模式（如 `\d+\s*[g克]`）或常见经方名，也视为有方剂内容；同时用注释列出已知 key。

  ### 9. `src/record.py:251-263` / `src/record.py:265-277` fallback 会返回整个 `deepseek_diagnosis`
  - **问题描述**：`get_pattern_differentiation` 和 `get_formula` 在形状 A 下若找不到指定中文键，会返回整个 `deepseek_diagnosis` dict。
  - **理由**：这会把大量无关字段（如“病机分析”“建议”）当作辨证/方剂返回，可能导致下游误判。
  - **修复建议**：fallback 返回 `{}` 而不是整个 diag；若需兼容历史格式，应显式列出所有可能的历史 key 并逐一尝试。

  ### 10. `src/confidence.py:97-100` 英文词边界检查不充分
  - **问题描述**：`not ("A" <= upper[len(value)] <= "Z")` 只拒绝后续 ASCII 字母，数字/下划线/连字符都会被视为边界。
  - **理由**：`parse_level("HIGH1")`、`parse_level("HIGH_2")` 会被识别为 `HIGH`，可能不是预期；虽然当前没有证据表明 LLM 会这样写，但词边界语义不严谨。
  - **修复建议**：只接受空格、连字符、常见中文或字符串结束作为合法边界，或改用正则 `\bHIGH\b`（注意 `re.ASCII` 以避免 CJK 边界问题）。

  ### 11. `src/scoring.py:304-326` 舌诊均值逻辑在测试中缺少“多异常取平均”的显式断言
  - **问题描述**：`score` 对舌诊取 `total / covered`，现有测试只覆盖了单异常（`test_tongue_score_sparse_not_diluted`）和全正常（`test_normal_tongue_scores_zero`）。
  - **理由**：均值算法是核心规则，若未来被改成累加封顶，现有测试不会红。
  - **修复建议**：补一条断言：例如结构化 dict 中 body_color=7、coating_thickness=7、其余 0 时，舌诊 score 应等于 7.0。

  ### 12. `tests/test_record.py` 未覆盖形状 A 的 `danger_flags` 布尔触发分支
  - **问题描述**：`test_get_danger_flags` 只测了形状 B 空列表，未测试形状 A 中 `danger_flags.<name>.triggered=True` 的解析。
  - **理由**：`get_triggered_danger_flags` 的形状 A 分支是安全红线的关键路径，缺少回归测试。
  - **修复建议**：补一个 shape A fixture，包含 `{ "daiyang": {"triggered": true, "finding": "面红如妆"} }`，断言触发列表。

  ### 13. `src/scoring.py:188-197` `TONGUE_RADAR_METRIC_KEYS` 与 `DIMENSION_RULES[TONGUE]` 指标不一致
  - **问题描述**：雷达图只用 8 个指标，漏掉了 `body_luster`（舌质荣枯）。
  - **理由**：这是雷达图展示维度的设计选择，但没有注释说明为何排除“荣枯”；如果并非故意，则周报丢失了一个舌象指标。
  - **修复建议**：确认是否故意排除；若需完整，把“舌质荣枯”加入 `TONGUE_RADAR_METRIC_KEYS` 并调整雷达图布局。

  ---

  ## 信息级

  ### 14. `scripts/vision_qwen.py` 无任何测试覆盖
  - **问题描述**：`tests/` 下没有针对 `vision_qwen.py` 的单元/集成测试。
  - **理由**：新脚本的 API 调用结构、错误处理、key 读取、prompt 注入面均未被自动化验证；这是审查范围明确要求的测试点。
  - **修复建议**：至少补一个最小测试集（可用 `unittest.mock.patch` 替换 `urllib.request.urlopen`），覆盖：正常返回解析、HTTP 错误、参数不足、key 未设置、`.env` 注释不生效。

  ### 15. `src/confidence.py:9` 引用的 `dimension-overlap-analysis.md` 不存在
  - **问题描述**：模块 docstring 提到与 `dimension-overlap-analysis.md §5.2` 同源，但仓库中无此文件。
  - **理由**：文档漂移，未来维护者找不到规则来源。
  - **修复建议**：在 `docs/architecture/` 补充该文件，或把引用改成实际存在的文档（如 `templates/adaptive_analysis_prompt.md`）。

  ### 16. `src/record.py:23` / `src/dimensions.py:13` 引用 `/codebase-design`
  - **问题描述**：注释中写“设计语汇（/codebase-design）”，但仓库内无此文件。
  - **理由**：与 15 类似，属于文档/注释漂移；虽然不影响运行，但降低可维护性。
  - **修复建议**：删除该引用或改为指向实际的设计文档/skills。

  ### 17. `src/confidence.py:122-127` `prompt_paragraph()` 包含 emoji
  - **问题描述**：prompt 段落中使用了 🟡/🟠/🟢 emoji。
  - **理由**：对 LLM 提示词通常无害，但某些纯文本消费场景可能不需要；属于风格问题。
  - **修复建议**：保持即可，或提供一个无 emoji 的可选参数，但当前不值得增加复杂度。

  ### 18. `scripts/vision_qwen.py:25-34` `PROMPTS` 的 prompt 注入面可控但 docstring 有歧义
  - **问题描述**：用法说明写 `python3 vision_qwen.py observe <img> <prompt>`，但实际 `<prompt>` 是 key，用来查 `PROMPTS`；用户无法直接传入任意 prompt。
  - **理由**：docstring 与实际参数语义不符，可能造成误用；但“无法直接注入任意 prompt”这一点本身是安全优点。
  - **修复建议**：把 docstring 改成 `<part>` 或 `<part-key>`，并输出可用的 part 列表。

  ---

  ## 功能忠实度专项结论

  1. **`allows_formula` 严格执法 LOW 不给方**：✅ 正确。`confidence.py:46-53` 对 LOW 返回 False；`input_validator.py:208-216` 与 `generate_weekly_report.py:579-583` 均取“自报等级”与“覆盖度推断等级”的严格者执行，LLM 省略/乱填 confidence 也无法绕过。  
  2. **置信度升级规则**：✅ 忠实。`confidence.py:32-43` 只按拍照维度数映射，与 `adaptive_analysis_prompt.md §3.1` 完全一致；问诊只计数不升级等级。  
  3. **用户确认视同覆盖**：✅ 实现为 `record.py:308-325` 中 `inquiry` 项 `asked=True` 计数为“已采集”，但明确不进入置信度计算，符合 prompt 规则。

  ---

  ## 总体结论

  最值得修的 **2** 个问题：

  1. **`scripts/vision_qwen.py:51-54` 的 API/网络错误处理缺失** — 这是新脚本最突出的可靠性问题，外部 API 失败时会以 `KeyError` 裸崩溃，调用方无法诊断。
  2. **`scripts/vision_qwen.py:10-20` `.env` 解析不跳过注释行** — 涉及 key 读取安全，注释行中的假 key 可能被误读，且修复只需加一行过滤。

  其余问题多为边界/测试覆盖/文档漂移，可按优先级逐步补齐。当前辨证守门逻辑（LOW 禁方、置信度一致性、fail-closed 的覆盖度推断）实现正确且测试覆盖较好。

  ---

  # B) 修改规划

  ## P0：影响正确性 / 安全 / 可靠性

  ### #4 `scripts/vision_qwen.py:10-20` `.env` 解析不跳过注释行
  - **修改方案**：在 `load_key()` 中先 `line.strip()`，跳过 `not line or line.startswith("#")`，再匹配 `DASHSCOPE_API_KEY=`。
  - **测试**：在 `tests/test_vision_qwen.py` 中写临时 `.env` 文件，包含 `# DASHSCOPE_API_KEY=注释值` 和真实 key，断言只读取真实 key。
  - **工作量**：小
  - **依赖**：无

  ### #2 `scripts/vision_qwen.py:51-54` API/网络错误无处理
  - **修改方案**：在 `call()` 内捕获 `urllib.error.HTTPError` / `URLError` / `socket.timeout`；读取错误响应体；检查 `data.get("choices")` 再取值；失败时抛出带状态码+响应摘要的 `RuntimeError`。
  - **测试**：mock `urllib.request.urlopen` 返回 4xx/5xx/结构异常响应，断言抛异常且不抛 `KeyError`。
  - **工作量**：小
  - **依赖**：无

  ### #3 `scripts/vision_qwen.py:57-58, 63` 命令行参数无边界检查
  - **修改方案**：`if __name__ == "__main__"` 开头检查 `len(sys.argv)`，不足时打印用法并 `sys.exit(2)`；`observe` 模式检查 `len(sys.argv) >= 4`。
  - **测试**：通过 subprocess 调用无参/缺参脚本，断言退出码 2 且输出含“用法”。
  - **工作量**：小
  - **依赖**：无

  ### #5 `src/scoring.py:205` 否定词“非”误杀“非正常”等
  - **修改方案**：把 `_NEGATION_RE` 中的“非”移除，由“无/不/未/没”覆盖绝大多数医学否定场景。
  - **测试**：补 `tests/test_scoring.py` 断言“非正常红润”“非典型黄染”不被否定。
  - **工作量**：小
  - **依赖**：无

  ### #8 `src/record.py:142-148` `has_formula_content` 硬编码 key 可能漏检
  - **修改方案**：保留现有 key 白名单，增加兜底扫描：若 dict 中任意 string 值匹配剂量模式 `\d+\s*[g克]` 或常见经方名，视为有方剂内容；用注释说明兜底规则。
  - **测试**：补测试用例 `{"description": "含桂枝10g"}`、`{"prescription": "桂枝汤"}` 被判定为有内容。
  - **工作量**：小
  - **依赖**：无

  ### #9 `src/record.py:251-263` / `265-277` fallback 返回整个 `deepseek_diagnosis`
  - **修改方案**：两个 `get_*` 方法的 fallback 改为返回 `{}`；若历史记录依赖“返回整个 diag”，则显式列出历史 key 逐一尝试，最后返回 `{}`。
  - **测试**：补 shape A 测试，缺失指定中文键时返回 `{}`，不污染 `get_pattern_differentiation()` / `get_formula()`。
  - **工作量**：小
  - **依赖**：无

  ---

  ## P1：影响健壮性 / 可维护性

  ### #1 `scripts/vision_qwen.py:39` 文件句柄未关闭
  - **修改方案**：改为 `with open(img_path, "rb") as f: b64 = base64.b64encode(f.read()).decode()`。
  - **测试**：可加 mock 断言 `open()` 返回的 mock 调用了 `__exit__`；或靠代码审查，无需单独测试。
  - **工作量**：小
  - **依赖**：无

  ### #6 `scripts/vision_qwen.py:43` 图片格式统一写死 `image/jpeg`
  - **修改方案**：按扩展名设置 MIME：`.png`→`image/png`，`.jpg/.jpeg`→`image/jpeg`，`.webp`→`image/webp`；未知扩展名回退 `image/jpeg`。
  - **测试**：传不同扩展名 fixture，断言 payload 中 `url` 前缀正确。
  - **工作量**：小
  - **依赖**：无

  ### #7 `scripts/vision_qwen.py:60` `classify` 不验证输出类别
  - **修改方案**：对模型输出 strip、取首行，与 `PROMPTS` 的 key 集合或 `其他` 比较；不匹配时回退 `其他` 并打印 stderr 警告。
  - **测试**：mock 返回 `"舌面\n"`、`"未知类别"`，断言分别输出 `舌面` / `其他`。
  - **工作量**：小
  - **依赖**：无

  ### #10 `src/confidence.py:97-100` 英文词边界检查不充分
  - **修改方案**：把词边界判断改为只接受空格、连字符、CJK 字符或字符串结束作为合法边界；或改用 `re.fullmatch(r"HIGH([^\p{L}]|$)", ...)` 并指定 ASCII。
  - **测试**：补断言 `parse_level("HIGH1")` / `parse_level("HIGH_2")` 返回 `None`。
  - **工作量**：小
  - **依赖**：无

  ### #11 `src/scoring.py:304-326` 舌诊均值逻辑缺多异常断言
  - **修改方案**：在 `tests/test_scoring.py` 增加结构化 dict：两个指标 7 分、其余 0 分，断言 `score == 7.0`。
  - **测试**：即修改本身。
  - **工作量**：小
  - **依赖**：必须先确定 #5 的否定守卫改动不会导致该测试数据被误杀（当前测试用例不含“非”，可并行）。

  ### #12 `tests/test_record.py` 未覆盖 shape A 的 `danger_flags` 布尔触发分支
  - **修改方案**：在 `test_record.py` 增加 shape A fixture，断言 `get_triggered_danger_flags()` 返回 `[daiyang]`。
  - **测试**：即修改本身。
  - **工作量**：小
  - **依赖**：无

  ### #13 `src/scoring.py:188-197` 雷达图漏掉 `body_luster`
  - **修改方案**：与产品确认是否故意排除；若需完整，在 `TONGUE_RADAR_METRIC_KEYS` 加入 `{"舌质荣枯": "body_luster"}`，并调整 `generate_radar_chart` 的 `categories` / `category_labels`。
  - **测试**：补断言 `extract_tongue_metrics` 返回值含 `舌质荣枯` 且分数正确。
  - **工作量**：中（涉及图表布局）
  - **依赖**：无，但属于产品决策，建议先确认。

  ---

  ## P2：锦上添花

  ### #14 `scripts/vision_qwen.py` 无任何测试覆盖
  - **修改方案**：新建 `tests/test_vision_qwen.py`，覆盖正常调用、HTTP 错误、参数不足、key 未设置、`.env` 注释不生效。
  - **测试**：即修改本身。
  - **工作量**：中
  - **依赖**：依赖 #2、#3、#4 修复后才能完整覆盖错误路径；正常路径可独立写。

  ### #15 `src/confidence.py:9` 引用不存在的 `dimension-overlap-analysis.md`
  - **修改方案**：删除 docstring 中该引用，或改为 `templates/adaptive_analysis_prompt.md §3.1`。
  - **测试**：无。
  - **工作量**：小
  - **依赖**：无

  ### #16 `src/record.py:23` / `src/dimensions.py:13` 引用不存在的 `/codebase-design`
  - **修改方案**：删除注释中该引用，或指向实际设计文档。
  - **测试**：无。
  - **工作量**：小
  - **依赖**：无

  ### #17 `src/confidence.py:122-127` `prompt_paragraph()` 包含 emoji
  - **修改方案**：保持现状；若需要纯文本，可加可选参数 `use_emoji: bool = True`，默认不变。
  - **测试**：若加参数，补一条 `use_emoji=False` 断言。
  - **工作量**：小
  - **依赖**：无。建议不处理，收益低。

  ### #18 `scripts/vision_qwen.py:25-34` docstring 把 part-key 写成 `<prompt>`
  - **修改方案**：docstring 改成 `observe <img> <part-key>`；缺参/无效 part-key 时打印可用列表。
  - **测试**：subprocess 调用无效 part-key，断言输出可用列表或回退“其他”。
  - **工作量**：小
  - **依赖**：无

  ---

  ## 建议执行顺序

  ### 批次 1：P0 核心（先修安全/可靠性）
  顺序：#4 → #2 → #3 → #5 → #8 → #9  
  理由：#4 和 #2 是 `vision_qwen.py` 最紧迫的 key 安全和 API 错误；#3 同文件可顺手修；#5、#8、#9 是安全边界和形状解析的关键修复。

  ### 批次 2：P1 健壮性
  顺序：#1 → #6 → #7 → #10 → #11 → #12 → #13  
  理由：#1/#6/#7 与 `vision_qwen.py` 同文件，批次 1 顺手；#10/#11/#12 是 confidence/record/scoring 的小修；#13 需要产品确认，放最后。

  ### 批次 3：P2 补齐
  顺序：#14 → #15/#16/#18 → #17  
  理由：#14 依赖批次 1 的修复才能覆盖错误路径；#15/#16/#18 是文档/注释；#17 建议不做或最后做。

To resume this session: kimi -r session_1107b89d-3ddd-4113-9dde-5e13b0ea967e

---

## 增量确认补充（2026-08-25，kimi 复审 vision_qwen.py 配置化改造后）

**审查对象**：commit 22f9ab8（MODEL/URL → VISION_MODEL/VISION_BASE_URL 环境变量，load_key 重构 VISION_API_KEY > DASHSCOPE_API_KEY）

**确认结论（经本地实测校准）**：
1. ✅ 新问题 A：load_key 两个循环重复读 .env —— 建议抽成"读一次→按优先级取"
2. ✅ 新问题 B：assert 文案未随改造更新（仍写 DASHSCOPE_API_KEY not found）
3. ⚠️ kimi 称"#4 注释行被误读"——**实测不成立**（startswith 免疫行首 #）；真实风险为**行内注释污染**（`KEY=xxx # 备注` → 值含 `# 备注`），防御性处理即可
4. ✅ #18 docstring 歧义仍存在（observe <img> <prompt> 应为 <part-key>）
5. ✅ 配置化方向正确：优先级清晰、缺省回退兼容、未破坏调用契约

**处置**：按用户指令暂缓修复，等 kimi 额度重置后与 P0/P1/P2 一并执行。
