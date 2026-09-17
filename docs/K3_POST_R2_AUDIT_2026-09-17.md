kimi version 2.0.0
• This is a substantial read-only audit task. I should delegate deep investigation to subagents, but I need to understand the codebase enough first. The task asks for sections ①-④ with file:line evidence and test outputs. Given the complexity, I could do it myself or delegate. The repo is small enough — let me look at key files directly. Key files: src/record.py, src/scoring.py, src/dimensions.py, src/confidence.py, scripts/generate_weekly_report.py, scripts/vision_client.py, scripts/input_validator.py, tests.

  Plan: run git show ef2f40a to see the diff, read the relevant files, run targeted python experiments, check consumers of records/daily. This is a lot of work — maybe delegate parallel explorations. But subagents can't easily run experiments and report back with the same fidelity... actually coder/explore agents can run bash. Read-only constraint: I can use explore agents with explicit "read-only, python -c allowed" instructions.

  Let me structure: 
  1. First, I read the commit diff and repair plan myself (core context).
  2. Then launch parallel subagents for the detailed probes? Or just do it myself — the repo is small.

  I'll do it mostly myself since evidence quality matters. Start with git show stat and reading key files.commit ef2f40aa0cf76ed421bd5069dff4de82af12e5bf
Author: bonesyear <199043401+bonesyear@users.noreply.github.com>
Date:   Thu Sep 17 21:13:15 2026 +0800

    fix(round2): 辨证层修复6条 + 方案A落地10项 + #19平局取高分
    
    A. 辨证层修复:
    - #5 _NEGATION_RE 移除'非' — '非典型黄染'不再被误否定漏报(取舍: '非X'表述按fail-loud判阳性, 写作规范改用无/不/未/没)
    - #8 has_formula_content 兜底扫描 — 剂量模式(\\d+[g克]) + 27个经方名白名单
    - #9 get_pattern_differentiation 形状A缺键返回{} — 原 fallback 返回整个 diag 会污染辨证
    - #10 confidence 英文词边界严格化 — HIGH1/HIGH_2 → None (fail-closed, 交覆盖度推断)
    - #12 danger_flags 宽松真值 — 字符串 'true'/'yes'/1 均可触发(修 fail-open) + 补测试
    - #16 删除不存在的 /codebase-design 文档引用
    B. 方案A落地: body_luster A路径 舌质荣枯→舌质润燥(模板同步同commit) | 移出评分层 | 删死代码 TONGUE_BODY_LUSTER_MAP | 雷达图加注释
    C. #19 _match_score 平局取分值最高者(fail-loud) — '湿润偏滑' 0分→7分, 湿盛信号不再被'润'掩盖
    
    验证: 198 passed(191+7) | 8项实测逐条通过 | ruff F,E722 All passed | 8/28真实C档案舌诊分 5.5→6.0(coating_moisture=7生效)

 src/confidence.py                        | 20 ++++++---
 src/dimensions.py                        |  2 +-
 src/record.py                            | 51 +++++++++++++++++++---
 src/scoring.py                           | 31 ++++++-------
 templates/multi_dim_record_template.json |  2 +-
 tests/test_confidence.py                 | 11 +++++
 tests/test_record.py                     | 74 ++++++++++++++++++++++++++++++++
 tests/test_scoring.py                    | 40 +++++++++++++----
 8 files changed, 193 insertions(+), 38 deletions(-)
8e97be5 docs: 轮次2后深查发现入档(备份污染周报已修 + 周报glob缺陷 + 轮次1审查遗留3点)
ddf3427 docs: 轮次2完成入档(含实测明细/取舍记录/红润词表缺口发现)
ef2f40a fix(round2): 辨证层修复6条 + 方案A落地10项 + #19平局取高分
311fa3a docs: 决策'老档案不用在意'(评分口径扩展不追溯/不标注趋势断点)
bf3fd71 docs: K3评分层意见归档 + 轮次3(评分覆盖扩展)入档 + 更正coating_thickness已有规则
5b37335 docs: C档案端到端实测发现两问题(同长度关键词低估湿盛/剥落斑无评分规则)
3711410 feat(record): 形状C支持 — 顶层规范英文维度键档案可被解析(0/6→6/6)
728514c docs: ⑤历史迁移决策=不做(C只对新档案生效,旧档保留原样)
commit ef2f40aa0cf76ed421bd5069dff4de82af12e5bf
Author: bonesyear <199043401+bonesyear@users.noreply.github.com>
Date:   Thu Sep 17 21:13:15 2026 +0800

    fix(round2): 辨证层修复6条 + 方案A落地10项 + #19平局取高分
    
    A. 辨证层修复:
    - #5 _NEGATION_RE 移除'非' — '非典型黄染'不再被误否定漏报(取舍: '非X'表述按fail-loud判阳性, 写作规范改用无/不/未/没)
    - #8 has_formula_content 兜底扫描 — 剂量模式(\\d+[g克]) + 27个经方名白名单
    - #9 get_pattern_differentiation 形状A缺键返回{} — 原 fallback 返回整个 diag 会污染辨证
    - #10 confidence 英文词边界严格化 — HIGH1/HIGH_2 → None (fail-closed, 交覆盖度推断)
    - #12 danger_flags 宽松真值 — 字符串 'true'/'yes'/1 均可触发(修 fail-open) + 补测试
    - #16 删除不存在的 /codebase-design 文档引用
    B. 方案A落地: body_luster A路径 舌质荣枯→舌质润燥(模板同步同commit) | 移出评分层 | 删死代码 TONGUE_BODY_LUSTER_MAP | 雷达图加注释
    C. #19 _match_score 平局取分值最高者(fail-loud) — '湿润偏滑' 0分→7分, 湿盛信号不再被'润'掩盖
    
    验证: 198 passed(191+7) | 8项实测逐条通过 | ruff F,E722 All passed | 8/28真实C档案舌诊分 5.5→6.0(coating_moisture=7生效)

diff --git a/src/confidence.py b/src/confidence.py
index df7a889..171d97c 100644
--- a/src/confidence.py
+++ b/src/confidence.py
@@ -72,14 +72,24 @@ _CHINESE_LEVEL_INDEX = {
 _CHINESE_LEVEL_SUFFIXES = ("", "度", "度确信", "度置信", "置信", "置信度", "等")
 
 
+def _is_word_boundary(ch: str) -> bool:
+    """英文规范值之后的合法边界字符：空格、连字符或 CJK 字符。
+
+    数字/下划线/英文字母都不是边界（"HIGH1"/"HIGH_2"/"HIGHEST" 不算
+    HIGH——fail-closed，认不出的置信度交给覆盖度推断执行安全检查）。
+    CJK 字符是合法边界且不能用 isalpha() 判断（CJK 的 isalpha() 为 True）。
+    """
+    return ch in " -" or "一" <= ch <= "鿿"
+
+
 def parse_level(text: Optional[str]) -> Optional[ConfidenceLevel]:
     """把记录自报的置信度字符串解析为枚举。无法识别（含空白串）返回 None。
 
     兼容三类写法：
       - 英文规范值："HIGH" / "high"（大小写不敏感）
-      - 英文带后缀："HIGH CONFIDENCE"、"HIGH置信度" 等——仅当规范值后
-        紧跟非英文字母（"HIGHEST" 不算 HIGH；CJK 字符是合法边界，
-        不能用 isalpha() 判断——CJK 的 isalpha() 为 True）
+      - 英文带后缀："HIGH CONFIDENCE"、"HIGH置信度" 等——规范值之后
+        只认可空格/连字符/CJK 字符/字符串结尾作为词边界
+        （"HIGHEST"/"HIGH1"/"HIGH_2" 都不算 HIGH）
       - 中文："高" / "高度" / "高度确信" / "高置信度" / "中等"（中/低 同理）
     """
     if text is None:
@@ -93,10 +103,10 @@ def parse_level(text: Optional[str]) -> Optional[ConfidenceLevel]:
         value = lvl.value
         if upper == value:
             return lvl
-        # 词边界前缀：后随字符不是 ASCII 字母即可（空格/连字符/中文均可）
+        # 词边界前缀：后随字符必须是空格/连字符/CJK
         if (upper.startswith(value)
                 and len(upper) > len(value)
-                and not ("A" <= upper[len(value)] <= "Z")):
+                and _is_word_boundary(upper[len(value)])):
             return lvl
     first = name[0]
     if first in _CHINESE_LEVEL_INDEX and name[1:] in _CHINESE_LEVEL_SUFFIXES:
diff --git a/src/dimensions.py b/src/dimensions.py
index a2316ad..368b4d6 100644
--- a/src/dimensions.py
+++ b/src/dimensions.py
@@ -10,7 +10,7 @@
 消费方（validator / weekly_report / prompt 文档）一律引用本模块，
 不再各自硬编码中英文维度名，从而消除"head_face vs 头面诊"式的拼写漂移。
 
-设计语汇（/codebase-design）：本模块是一个深 module——interface 很小
+设计语汇：本模块是一个深 module——interface 很小
 （六个枚举 + 两个 adapter），implementation 持有全部维度元数据。
 两个 adapter（中/英）同时存在 → 这是个真 seam，不是假想。
 """
diff --git a/src/record.py b/src/record.py
index da500b3..91c60fa 100644
--- a/src/record.py
+++ b/src/record.py
@@ -21,11 +21,12 @@ Interface（小而稳）：
 校验器与周报生成器都退化为本 module 的 adapter，只认 Record interface，
 不再各自手抄字段路径 → 形状只在一处定义，改一次全改。
 
-设计语汇（/codebase-design）：这是首选深 module——删掉它，"记录形状"的
+设计语汇：这是首选深 module——删掉它，"记录形状"的
 复杂度会立刻重现到模板、校验器、周报三个调用方。
 """
 
 import json
+import re
 from typing import Any, Dict, List, Optional, Tuple, Union
 
 from .dimensions import VisionDimension, DIMENSIONS, from_english, from_chinese
@@ -46,7 +47,7 @@ from .dimensions import VisionDimension, DIMENSIONS, from_english, from_chinese
 _DIMENSION_INDICATORS: Dict[VisionDimension, Dict[str, Dict[str, List[str]]]] = {
     VisionDimension.TONGUE: {
         "body_color":              {"A": ["舌质颜色"],         "B": ["body", "color"],              "C": ["body_color"]},
-        "body_luster":             {"A": ["舌质荣枯"],         "B": ["body", "luster"],             "C": ["body_luster"]},
+        "body_luster":             {"A": ["舌质润燥"],         "B": ["body", "luster"],             "C": ["body_luster"]},
         "body_size":               {"A": ["舌体胖瘦"],         "B": ["body", "shape"],              "C": ["body_size"]},
         "petechiae":               {"A": ["瘀斑瘀点"],         "B": ["body", "ecchymosis"],         "C": ["petechiae"]},
         "tooth_marks":             {"A": ["齿痕"],             "B": ["body", "tooth_marks"],        "C": ["tooth_marks"]},
@@ -142,6 +143,17 @@ def _safe_int(value: Any) -> int:
         return 0
 
 
+# 方剂内容兜底扫描：剂量模式（如 "桂枝10g"、"10 g"、"10克"）
+_DOSAGE_RE = re.compile(r"\d+\s*[gG克]")
+# 常见经方名（白名单键未命中时，值中出现方名即算有方剂内容）
+_CLASSIC_FORMULA_RE = re.compile(
+    r"桂枝汤|麻黄汤|葛根汤|小青龙汤|大青龙汤|白虎汤|大承气汤|小承气汤|"
+    r"调胃承气汤|小柴胡汤|大柴胡汤|柴胡桂枝干姜汤|半夏泻心汤|生姜泻心汤|"
+    r"甘草泻心汤|五苓散|苓桂术甘汤|真武汤|四逆汤|当归四逆汤|芍药甘草汤|"
+    r"桂枝茯苓丸|桃核承气汤|抵当汤|茵陈蒿汤|栀子豉汤|小建中汤|炙甘草汤"
+)
+
+
 def has_formula_content(formula: Any) -> bool:
     """判断方剂对象是否携带任何实质内容(方名/成分/药组/剂量)。
 
@@ -149,6 +161,10 @@ def has_formula_content(formula: Any) -> bool:
     "无方名但携带 12 味药材+具体剂量" 的记录——处方的实质是药物与剂量,
     不是方名。非 dict 的非空值(如整段方剂文本)同样算有内容,
     结构异常不能成为安全检查的放行理由(fail-closed)。
+
+    键白名单之外还有兜底扫描：任意值中出现剂量模式（\\d+[g克]）或
+    常见经方名（如桂枝汤/小柴胡汤）即判为有方剂内容——白名单键名
+    漂移（如 {"description": "含桂枝10g"}）不能成为放行理由。
     """
     if not formula:
         return False
@@ -156,7 +172,10 @@ def has_formula_content(formula: Any) -> bool:
         return bool(str(formula).strip())
     content_keys = ("name", "主方", "合方", "ingredients", "核心药组",
                     "剂量建议", "加减", "dosage", "herbs")
-    return any(formula.get(k) for k in content_keys)
+    if any(formula.get(k) for k in content_keys):
+        return True
+    text = _flatten_to_text(formula)
+    return bool(_DOSAGE_RE.search(text) or _CLASSIC_FORMULA_RE.search(text))
 
 
 def _flatten_to_text(obj: Any) -> str:
@@ -180,6 +199,20 @@ def _flatten_to_text(obj: Any) -> str:
     return " ".join(parts)
 
 
+# danger_flags 的宽松真值判定：LLM 可能把布尔输出为字符串 "true"/"yes"
+# 或数值 1，严格 `is True` 会让真值意图的红线静默不触发（fail-open）。
+# 注意：validator 对形状 A 的非布尔 triggered 仍报 error（输入层把关），
+# 这里的宽松化面向 Record 的消费方（周报/报告），双保险不冲突。
+_TRUE_FLAG_STRINGS = ("true", "yes", "1")
+
+
+def _is_triggered(value: Any) -> bool:
+    """danger_flags.triggered 的宽松真值判断（True/'true'/'yes'/1 均算触发）。"""
+    if isinstance(value, str):
+        return value.strip().lower() in _TRUE_FLAG_STRINGS
+    return value is True or value == 1
+
+
 class DailyRecord:
     """一份望诊日报记录的规范化表示。
 
@@ -281,7 +314,9 @@ class DailyRecord:
 
         形状 B：pattern_differentiation；形状 C：pattern_update（别名）；
         形状 A：deepseek_diagnosis.许家栋经方辨证。
-        容器类型不对时返回空 dict（结构错误由 validator 报告）。
+        容器类型不对时返回空 dict（结构错误由 validator 报告）；
+        形状 A 找不到辨证键时返回 {}，不得回落为整个 diagnosis dict
+        （否则"综合辨证结论"等无关字段会污染辨证结果）。
         """
         for key in ("pattern_differentiation", "pattern_update"):
             if key in self.raw:
@@ -290,7 +325,7 @@ class DailyRecord:
         diag = self.raw.get("deepseek_diagnosis") or {}
         if not isinstance(diag, dict):
             return {}
-        return diag.get("许家栋经方辨证", diag) or {}
+        return diag.get("许家栋经方辨证") or {}
 
     def get_formula(self) -> Any:
         """取方剂建议。
@@ -315,7 +350,9 @@ class DailyRecord:
     def get_triggered_danger_flags(self) -> List[str]:
         """取已触发的红线列表。
 
-        形状 B：danger_flags.triggered（列表）；形状 A：遍历 flag 对象 triggered=True。
+        形状 B：danger_flags.triggered（列表）；形状 A：遍历 flag 对象，
+        triggered 按宽松真值判定（True/'true'/'yes'/1 均算触发）——
+        严格 `is True` 会让 LLM 输出的字符串 "true" 静默不触发（fail-open）。
         """
         df = self.get_danger_flags()
         if not isinstance(df, dict):
@@ -324,7 +361,7 @@ class DailyRecord:
             return list(df["triggered"])
         triggered = []
         for name, flag in df.items():
-            if isinstance(flag, dict) and flag.get("triggered") is True:
+            if isinstance(flag, dict) and _is_triggered(flag.get("triggered")):
                 triggered.append(name)
         return triggered
 
diff --git a/src/scoring.py b/src/scoring.py
index 243776f..46805dd 100644
--- a/src/scoring.py
+++ b/src/scoring.py
@@ -18,13 +18,14 @@ observation 可为 Record.get_observation() 返回的 {指标: 文本}（推荐
     2. 子串匹配降级 —— 取命中最长的关键词（"红如妆" 优先于 "红"，
        "淡红" 优先于 "红"），消除歧义
     3. 否定守卫（双向） —— 前置：关键词前 6 字内、同一小句（以标点/空白
-       为界）出现否定词（无/不/未/没/非，"非常" 是程度副词不算）；
+       为界）出现否定词（无/不/未/没；"非" 不作否定词——"非正常/非典型"
+       类表述中"非"修饰的是"正常/典型"，误判为否定会漏报异常）；
        后置：关键词后紧跟否定短语（不明显/不显著/未见/阴性 等）。
        覆盖 "无明显浮肿"、"未见浮肿"、"没有黄染"、"浮肿不明显" 等真实
        LLM 产出中的常见否定表达；且按关键词的**全部出现位置**判定——
        "舌质不红，但舌边红" 中第二个 "红" 是真阳性，正常计分。
 
-评分基线约定：**正常表现一律 0 分**（淡红舌、薄白苔、润苔、荣润、适中
+评分基线约定：**正常表现一律 0 分**（淡红舌、薄白苔、润苔、适中
 均为 0）。0 = 正常，10 = 极重度异常，全表统一，杜绝"正常人踩关注线"。
 
 与 Record module 组合：Record 按维度取观测 → Scoring 打分。
@@ -108,13 +109,6 @@ TONGUE_BODY_SIZE_MAP = {
     "肿胀": 9,
 }
 
-# 舌质荣枯（有神/无神）
-TONGUE_BODY_LUSTER_MAP = {
-    "荣润": 0,   # 有神
-    "少泽": 5,   # 少神
-    "枯槁": 8,   # 无神
-}
-
 # 面部光泽
 FACE_LUSTER_MAP = {
     "荣润": 0,   # 有神
@@ -146,7 +140,6 @@ DIMENSION_RULES: Dict[VisionDimension, Dict[str, Dict[str, int]]] = {
         "sublingual_varicosity": SUBLINGUAL_VARICOSITY_MAP,
         "fissure": FISSURE_MAP,
         "body_size": TONGUE_BODY_SIZE_MAP,
-        "body_luster": TONGUE_BODY_LUSTER_MAP,
     },
     VisionDimension.HEAD_FACE: {
         "face_color":    {"萎黄": 5, "晦暗": 5, "黧黑": 5, "青灰": 5, "红如妆": 9},
@@ -185,6 +178,9 @@ DIMENSION_RULES: Dict[VisionDimension, Dict[str, Dict[str, int]]] = {
 
 
 # 舌诊的雷达图指标名 → 规范指标 key（供周报 extract_tongue_metrics 复用）
+# body_luster（舌质润燥，原"舌质荣枯"）不进雷达图也不参与评分：光泽受
+# 照片光线干扰（顺光/闪光灯观感完全不同），且神气/荣枯需动态观察，
+# 静态照片不可判——不给不可靠数据建展示位（方案 A，评分层降级到辨证层）。
 TONGUE_RADAR_METRIC_KEYS = {
     "舌质颜色": "body_color",
     "舌苔厚度": "coating_thickness",
@@ -201,8 +197,9 @@ TONGUE_RADAR_METRIC_KEYS = {
 # 匹配策略
 # ============================================================
 
-# 否定词：无/不/未/没/非（"非常" 是程度副词，用负向前瞻排除）
-_NEGATION_RE = re.compile(r"无|不|未|没|非(?!常)")
+# 否定词：无/不/未/没。"非" 已移除——"非正常红润""非典型黄染" 中"非"
+# 修饰的是"正常/典型"，当作否定词会把真异常误杀为正常（漏报）。
+_NEGATION_RE = re.compile(r"无|不|未|没")
 # 后置否定短语（"浮肿不明显""黄染未见" 等"关键词+否定"句式），
 # 必须锚定在关键词之后的小句开头，避免"充血无改善"这类误杀
 _POST_NEGATION_RE = re.compile(r"不明显|不显著|不突出|不著|未见|阴性")
@@ -242,7 +239,8 @@ def _has_unnegated_occurrence(text: str, kw: str) -> bool:
 
 
 def _match_score(rules: Dict[str, int], text: str) -> int:
-    """单指标打分：精确匹配优先 → 最长子串匹配（带双向否定守卫）。
+    """单指标打分：精确匹配优先 → 最长子串匹配（带双向否定守卫，
+    同长度关键词取分值最高者）。
 
     返回命中的分值；无命中返回 0。
     已知局限：无标点连写（如"手足不温伴厥冷"）中，否定词可能误伤
@@ -256,14 +254,17 @@ def _match_score(rules: Dict[str, int], text: str) -> int:
     if text in rules:
         return rules[text]
 
-    # 2. 子串匹配降级：取存在未否定出现的最长关键词
+    # 2. 子串匹配降级：取存在未否定出现的最长关键词；
+    #    同长度时取分值最高者（fail-loud：宁可高估不漏估——"湿润偏滑"
+    #    应命中"滑"=7，不能因"润"=0 排在前面而漏掉湿盛信号）
     best_kw = None
     for kw in rules:
         if kw not in text:
             continue
         if not _has_unnegated_occurrence(text, kw):
             continue
-        if best_kw is None or len(kw) > len(best_kw):
+        if (best_kw is None or len(kw) > len(best_kw)
+                or (len(kw) == len(best_kw) and rules[kw] > rules[best_kw])):
             best_kw = kw
 
     return rules[best_kw] if best_kw is not None else 0
diff --git a/templates/multi_dim_record_template.json b/templates/multi_dim_record_template.json
index 943830f..a0639a1 100644
--- a/templates/multi_dim_record_template.json
+++ b/templates/multi_dim_record_template.json
@@ -14,7 +14,7 @@
   "doubao_vision_analysis": {
     "舌诊": {
       "舌质颜色": "",
-      "舌质荣枯": "",
+      "舌质润燥": "",
       "瘀斑瘀点": "",
       "舌苔颜色": "",
       "舌苔厚薄": "",
diff --git a/tests/test_confidence.py b/tests/test_confidence.py
index 7998d54..878d261 100644
--- a/tests/test_confidence.py
+++ b/tests/test_confidence.py
@@ -75,6 +75,17 @@ def test_parse_level_word_boundary():
     assert C.parse_level("HIGH-CONF") is ConfidenceLevel.HIGH
 
 
+def test_parse_level_strict_boundary():
+    """严格词边界：数字/下划线不是合法边界——"HIGH1"/"HIGH_2" 不得
+    被解析成 HIGH（fail-closed，认不出就交给覆盖度推断）。"""
+    assert C.parse_level("HIGH1") is None
+    assert C.parse_level("HIGH_2") is None
+    # 合法边界不受影响：空格/连字符/CJK
+    assert C.parse_level("HIGH CONFIDENCE") is ConfidenceLevel.HIGH
+    assert C.parse_level("HIGH-置信") is ConfidenceLevel.HIGH
+    assert C.parse_level("HIGH置信度") is ConfidenceLevel.HIGH
+
+
 def test_is_consistent_accepts_chinese():
     assert C.is_consistent("高度确信", 6) is True
     assert C.is_consistent("低度确信", 6) is False
diff --git a/tests/test_record.py b/tests/test_record.py
index e8d5695..5338a30 100644
--- a/tests/test_record.py
+++ b/tests/test_record.py
@@ -159,6 +159,80 @@ def test_has_formula_content():
     assert has_formula_content("   ") is False
 
 
+def test_has_formula_content_fallback_scan():
+    """白名单键未命中时的兜底扫描：值中出现剂量模式或经方名即算有内容
+    （键名漂移不能成为安全检查的放行理由）。"""
+    from src.record import has_formula_content
+    assert has_formula_content({"description": "含桂枝10g"}) is True
+    assert has_formula_content({"note": "桂枝汤加减"}) is True
+    assert has_formula_content({"note": "小柴胡汤"}) is True
+    # 无剂量、无方名的描述不算方剂内容
+    assert has_formula_content({"note": "无"}) is False
+    assert has_formula_content({"description": "暂不需要"}) is False
+
+
+def test_shape_a_body_luster_moisture_path():
+    """方案 A：body_luster 的形状 A 路径为"舌质润燥"（与 vision prompt
+    键名一致）；旧键"舌质荣枯"不再解析（历史记录实测全为形状 B，无影响）。"""
+    rec = DailyRecord({
+        "date": "2026-01-01",
+        "doubao_vision_analysis": {"舌诊": {"舌质润燥": "润泽"}},
+    })
+    tongue = rec.get_observation(VisionDimension.TONGUE)
+    assert tongue["body_luster"] == "润泽"
+    old_key = DailyRecord({
+        "date": "2026-01-01",
+        "doubao_vision_analysis": {"舌诊": {"舌质荣枯": "荣润"}},
+    })
+    assert old_key.get_observation(VisionDimension.TONGUE)["body_luster"] == ""
+
+
+def test_shape_a_pattern_differentiation_missing_key_returns_empty():
+    """形状 A 缺"许家栋经方辨证"键时必须返回 {}，不得回落为整个
+    deepseek_diagnosis dict（否则无关字段污染辨证结果）。"""
+    rec = DailyRecord({
+        "date": "2026-01-01",
+        "doubao_vision_analysis": {"舌诊": {"舌质颜色": "淡红"}},
+        "deepseek_diagnosis": {"综合辨证结论": "脾虚", "方剂建议": {}},
+    })
+    assert rec.get_pattern_differentiation() == {}
+    # 键存在时正常取值
+    rec2 = DailyRecord({
+        "date": "2026-01-01",
+        "doubao_vision_analysis": {"舌诊": {"舌质颜色": "淡红"}},
+        "deepseek_diagnosis": {"许家栋经方辨证": {"核心病机": "脾虚"}},
+    })
+    assert rec2.get_pattern_differentiation() == {"核心病机": "脾虚"}
+
+
+def test_shape_a_danger_flags_triggered():
+    """形状 A 的 danger_flags：triggered 按宽松真值判定——布尔 True 与
+    LLM 可能输出的字符串 "true"/"yes"、数值 1 均算触发（严格 is True
+    会让字符串 "true" 静默不触发，fail-open）。"""
+    rec = DailyRecord({
+        "date": "2026-01-01",
+        "doubao_vision_analysis": {"舌诊": {"舌质颜色": "淡红"}},
+        "danger_flags": {
+            "daiyang": {"triggered": True, "finding": "面红如妆"},
+            "skin_cold": {"triggered": False, "finding": ""},
+        },
+        },
+    })
+    assert rec.get_triggered_danger_flags() == ["daiyang"]
+    # 字符串/数值真值同样触发
+    rec2 = DailyRecord({
+        "date": "2026-01-01",
+        "doubao_vision_analysis": {"舌诊": {"舌质颜色": "淡红"}},
+        "danger_flags": {
+            "daiyang": {"triggered": "true", "finding": "面红如妆"},
+            "skin_cold": {"triggered": "yes", "finding": "肢冷"},
+            "flesh_wasted": {"triggered": 1, "finding": "肉脱"},
+            "mirror_tongue": {"triggered": "false", "finding": ""},
+        },
+    })
+    assert rec2.get_triggered_danger_flags() == ["daiyang", "skin_cold",
+                                                 "flesh_wasted"]
+
+
 def test_no_information_loss_against_raw(real_record):
     """新架构取出的观测文本应是原始记录的子集，不丢失关键信息。"""
     raw = real_record.raw
diff --git a/tests/test_scoring.py b/tests/test_scoring.py
index 57e2b42..5ed22d1 100644
--- a/tests/test_scoring.py
+++ b/tests/test_scoring.py
@@ -62,7 +62,7 @@ def test_negation_guard_on_eye_edema():
 
 
 def test_negation_guard_extended_words():
-    # 否定词集扩充：未/没/非（历史 Bug 5——真实 LLM 产出常用"未见/没有"）
+    # 否定词集扩充：未/没（历史 Bug 5——真实 LLM 产出常用"未见/没有"）
     assert score_indicators(VisionDimension.HEAD_FACE,
                             {"face_edema": "未见明显浮肿"})["face_edema"] == 0
     assert score_indicators(VisionDimension.EYE,
@@ -72,6 +72,15 @@ def test_negation_guard_extended_words():
                             {"edema": "无明显的浮肿"})["edema"] == 0
 
 
+def test_fei_is_not_negation_for_abnormal_prefix():
+    """"非" 不是否定词："非正常/非典型" 修饰的是"正常/典型"，
+    误判为否定会把真异常漏报成正常（历史 Bug——"非正常红润" 被误否定）。"""
+    assert score_indicators(VisionDimension.TONGUE,
+                            {"body_color": "非正常红润"})["body_color"] == 7
+    assert score_indicators(VisionDimension.EYE,
+                            {"jaundice": "非典型黄染"})["jaundice"] == 4
+
+
 def test_negation_guard_clause_boundary():
     # 否定词只在同一小句内生效："无瘀点，散在瘀斑" 的"无"不应跨逗号抹掉"散在"
     inds = score_indicators(VisionDimension.TONGUE, {"petechiae": "无瘀点，散在瘀斑"})
@@ -120,7 +129,6 @@ def test_normal_tongue_scores_zero():
         "sublingual_varicosity": "无",
         "fissure": "无",
         "body_size": "适中",
-        "body_luster": "荣润",
     }
     assert score(VisionDimension.TONGUE, normal) == 0.0
     inds = score_indicators(VisionDimension.TONGUE, normal)
@@ -132,14 +140,28 @@ def test_tongue_score_sparse_not_diluted():
     assert score(VisionDimension.TONGUE, "青紫") == 10
 
 
-def test_body_luster_scoring():
-    # 舌质荣枯：枯槁高分、荣润正常
+def test_body_luster_not_scored():
+    """方案 A：body_luster（舌质润燥，原"舌质荣枯"）已从 DIMENSION_RULES
+    移除——光泽受照片光线干扰、静态照片不可判神气/荣枯，降级到辨证层，
+    不再参与 score()。"""
     inds = score_indicators(VisionDimension.TONGUE, {"body_luster": "枯槁"})
-    assert inds["body_luster"] == 8
-    inds2 = score_indicators(VisionDimension.TONGUE, {"body_luster": "少泽"})
-    assert inds2["body_luster"] == 5
-    inds3 = score_indicators(VisionDimension.TONGUE, {"body_luster": "荣润"})
-    assert inds3["body_luster"] == 0
+    assert "body_luster" not in inds
+
+
+def test_tie_break_prefers_higher_score():
+    """同长度关键词命中时取分值最高者（fail-loud：宁可高估不漏估）。
+    端到端实测发现："湿润偏滑" 曾因 "润":0 排在 "滑":7 之前被判 0 分，
+    湿盛信号被系统性掩盖。"""
+    assert score_indicators(VisionDimension.TONGUE,
+                            {"coating_moisture": "湿润偏滑"})["coating_moisture"] == 7
+    assert score_indicators(
VisionDimension.TONGUE,
+                            {"coating_moisture": "湿润"})["coating_moisture"] == 0
+    # 两个异常词平局：取更高的 "燥"=8 而非 "滑"=7
+    assert score_indicators(VisionDimension.TONGUE,
+                            {"coating_moisture": "滑燥并见"})["coating_moisture"] == 8
+    # 否定后平局不触发："燥" 被 "不" 否定，只剩 "润"=0
+    assert score_indicators(VisionDimension.TONGUE,
+                            {"coating_moisture": "苔润不燥"})["coating_moisture"] == 0
 
 
 def test_face_luster_scoring():
Now I have the full diff. Next: read the key source files in their current state (record.py, scoring.py, confidence.py), the weekly report script, vision_client, input_validator, and check the repair plan's "轮次 2 后深查发现" section. Also check consumers of records/daily and the shape C tests.

  Given the volume, I'll read key files myself and run experiments. Let me read files in parallel.Now read confidence.py, generate_weekly_report.py (glob part), vision_client.py, input_validator.py, and the repair plan's "轮次2后深查发现" section. Also check shape C interactions, other consumers of records/daily.Now read vision_client.py, input_validator.py, the repair plan's post-round-2 section, and check shape C. Also grep for consumers of records/daily./root/tcm-tongue-system/scripts/input_validator.py:23:  python3 scripts/input_validator.py <daily_analysis_json_path>
/root/tcm-tongue-system/scripts/input_validator.py:26:  python3 scripts/input_validator.py records/daily/2026-06-25_analysis.json
/root/tcm-tongue-system/scripts/input_validator.py:54:    """验证单个 daily analysis JSON 文件。
/root/tcm-tongue-system/scripts/input_validator.py:290:        print("用法: python input_validator.py <daily_analysis_json_path>")
/root/tcm-tongue-system/scripts/input_validator.py:291:        print("示例: python input_validator.py records/daily/2026-06-25_analysis.json")
/root/tcm-tongue-system/src/paths.py:12:    RECORDS_DAILY_DIR / RECORDS_WEEKLY_DIR / CHARTS_DIR 均在 DATA_ROOT 下
/root/tcm-tongue-system/src/paths.py:25:RECORDS_DAILY_DIR = os.path.join(DATA_ROOT, "records", "daily")
/root/tcm-tongue-system/src/paths.py:35:    for d in (RECORDS_DAILY_DIR, RECORDS_WEEKLY_DIR, CHARTS_DIR):
#!/bin/bash
# ============================================================
# 中医望诊系统 — OSS 版本备份脚本
# 策略：仅在内容变化时备份，始终覆盖旧版，只保留最新
#
# 安全约定（见 docs/CODE_REVIEW_2026-07-12.md 风险 A/B/D）：
#   - 不上传任何个人健康数据：records/（日报+周报）与 charts/ 全部排除
#   - 不上传《经方探源》全书原文（版权物）：
#     knowledge_base/jingfang_tanyuan_full.md 排除
#   - 临时打包文件用 mktemp 创建并 trap 清理，避免 /tmp 固定路径竞态
#
# 路径与配置：
#   - 仓库根默认取脚本所在目录的上级，可用 TCM_SYSTEM_DIR 覆盖
#   - OSS bucket 可用 TCM_OSS_BUCKET 覆盖（默认 smin-oss）
#   - 哈希命令自动选择 md5sum（Linux）/ shasum（macOS）
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEM_DIR="${TCM_SYSTEM_DIR:-$(dirname "$SCRIPT_DIR")}"
MANIFEST_FILE="${SYSTEM_DIR}/.backup_manifest"
OSS_BUCKET="${TCM_OSS_BUCKET:-smin-oss}"
OSS_PATH="oss://${OSS_BUCKET}/hermes/tcm-tongue-system/tcm-tongue-system-latest.tar.gz"
VERSION_FILE="${SYSTEM_DIR}/VERSION"

# --- 0. 可移植哈希命令（macOS 无 md5sum） ---
if command -v md5sum >/dev/null 2>&1; then
    HASH_CMD="md5sum"
elif command -v shasum >/dev/null 2>&1; then
    HASH_CMD="shasum -a 256"
else
    echo "❌ 找不到 md5sum / shasum，无法计算内容哈希" >&2
    exit 1
fi

TMP_TAR="$(mktemp -t tcm-backup.XXXXXX)"
trap 'rm -f "$TMP_TAR"' EXIT

# --- 1. 读取或生成版本号 ---
if [ -f "$VERSION_FILE" ]; then
---
2026-06-25
2026-06-25_analysis.json
2026-06-29
2026-06-29_analysis.json
2026-06-29_img1.jpg
2026-06-29_img2.jpg
2026-06-29_img3.jpg
2026-06-29_img4.jpg
2026-06-29_img5.jpg
2026-06-29_img6.jpg
2026-06-29_img7.jpg
2026-06-29_img8.jpg
2026-06-29_img9.jpg
2026-07-03
2026-07-03_analysis.json
2026-07-06
2026-07-09
2026-07-09_analysis.json
2026-07-10
2026-07-10_analysis.json
2026-07-12
2026-07-15
2026-07-15_analysis.json
2026-07-15_b
2026-07-15_b_analysis.json
2026-07-16_shifang
2026-07-16_shimin
2026-08-02
2026-08-02_analysis.json
2026-08-02_img1.jpg
---
2026-08-28_analysis_v1_旧格式.json
Confirmed: backup moved to records/_backup/ and renamed 2026-08-28_analysis_v1_旧格式.json. Now check the repair plan's "轮次 2 后深查发现" section, and other daily consumers. Also check records/daily listing fully to see what files exist around 2026-08-28. Also check docs. Then run experiments.

  Let me now read the repair plan's relevant section, list daily files fully, and check tests.2026-06-25_analysis.json
2026-06-29_analysis.json
2026-07-03_analysis.json
2026-07-09_analysis.json
2026-07-10_analysis.json
2026-07-15_analysis.json
2026-07-15_b_analysis.json
2026-08-02_analysis.json
2026-08-02_vision_raw.json
2026-08-03_guest_vision_raw.json
2026-08-03_sm_vision_raw.json
2026-08-09_analysis.json
2026-08-09_full_vision_raw.json
2026-08-14_analysis.json
2026-08-14_fu_vision_raw.json
2026-08-28_analysis.json
---
278:## 轮次 2 后深查发现（2026-09-17，用户追问"有遗留问题吗"）
/root/tcm-tongue-system/src/paths.py:12:    RECORDS_DAILY_DIR / RECORDS_WEEKLY_DIR / CHARTS_DIR 均在 DATA_ROOT 下
/root/tcm-tongue-system/src/paths.py:25:RECORDS_DAILY_DIR = os.path.join(DATA_ROOT, "records", "daily")
/root/tcm-tongue-system/src/paths.py:35:    for d in (RECORDS_DAILY_DIR, RECORDS_WEEKLY_DIR, CHARTS_DIR):
/root/tcm-tongue-system/scripts/generate_weekly_report.py:41:    RECORDS_DAILY_DIR as RECORDS_DIR,
/root/tcm-tongue-system/scripts/generate_weekly_report.py:89:    加载指定日期之前 7 天的所有 daily analysis JSON 记录。
/root/tcm-tongue-system/scripts/generate_weekly_report.py:143:    从单条 daily record 中提取舌象定量指标分数。
/root/tcm-tongue-system/scripts/generate_weekly_report.py:295:        records: 本周的 daily 记录列表
/root/tcm-tongue-system/scripts/generate_weekly_report.py:376:            "daily_records_count": 0,
/root/tcm-tongue-system/scripts/generate_weekly_report.py:543:        "daily_records_count": len(records),
/root/tcm-tongue-system/scripts/input_validator.py:23:  python3 scripts/input_validator.py <daily_analysis_json_path>
/root/tcm-tongue-system/scripts/input_validator.py:26:  python3 scripts/input_validator.py records/daily/2026-06-25_analysis.json
/root/tcm-tongue-system/scripts/input_validator.py:54:    """验证单个 daily analysis JSON 文件。
/root/tcm-tongue-system/scripts/input_validator.py:290:        print("用法: python input_validator.py <daily_analysis_json_path>")
/root/tcm-tongue-system/scripts/input_validator.py:291:        print("示例: python input_validator.py records/daily/2026-06-25_analysis.json")
`TONGUE_RADAR_METRIC_KEYS`（`scoring.py:188-197`）增加 `"舌苔剥落": "coating_peeling"` → 8 轴变 9 轴，同步周报模板（`generate_weekly_report.py:141-162`）与图表说明。理由：否则剥落只在维度均分里体现，趋势图仍看不到这个核心观察点。

**工作量**：3.1 ≈ 0.5-1 小时（1 行 + 4-6 测试）；3.2+3.3 ≈ 1 个工作日（7 map + 雷达/周报 + 15-20 测试 + fixture 核对 + 全量回归）+ 临床签认时间。

**历史趋势断点**：口径扩展后旧分与新分不可直接比较（8/28 档案 5.5 → 预计 6.5+，因 `湿润偏滑`→7、剥落→6 生效）。**用户决策（2026-09-17）：老档案不用在意** → 不做口径变更标注、不追溯重算、周报按新口径自然输出。

---

## 轮次 2 后深查发现（2026-09-17，用户追问"有遗留问题吗"）

### 已修（本轮自查发现并修复）

**备份文件污染周报** —— 重写 C 档案时创建的备份 `records/daily/2026-08-28_analysis.v1.bak.json` 被 `generate_weekly_report.py:112,121` 的 `glob("{date}*analysis*.json")` + `sorted()[-1]`（"取字典序最新"）选中（`v1.bak` 字典序排在 `analysis.json` 之后）→ 周报读到**旧格式档案**：舌诊偏离度 **0.0**（应 6.0）、误报 `safety_violation: "LOW 置信度下不应输出方剂"`。
**已修**：备份移至 `records/_backup/2026-08-28_analysis_v1_旧格式.json`（非 `.json` 结尾 + 移出 daily）→ 重跑周报验证：偏离度 **6.0**、`claimed=HIGH/covered=6/consistent=true`、无 safety_violation ✅

**根因是系统缺陷（未修，建议新增条目）**：周报 glob 过宽 + "字典序最新"启发式脆弱——任何同日期前缀的 json（`.bak`/副本/中间文件）都会参与竞争且可能胜出。建议：① 优先精确匹配 `{date}_analysis.json`；② 排除 `*.bak*`/`*copy*`/`*tmp*`；③ 多份命中时**打印警告**而非静默选一。

### 轮次 1 审查遗留 3 点（K3 提过、尚未处置；非轮次 2 引入）

1. `vision_client.py:122` **observe 无效 part-key 静默回退**（`PROMPTS.get(part, PROMPTS["其他"])` 无警告）——K3 建议打印可用类别列表
2. `tests/test_vision_client.py` 缺 **JSONDecodeError / timeout 用例**；"舌质润燥"键名指令**零测试**
3. 其余 6 部位（舌底/头面/目部/耳部/手部/皮肤）**PROMPTS 未声明键名** → 与 `record.py` A 路径键名不保证对齐。**影响已降低**（形状 C 落地后档案由 assistant 按 C 规范手写，observe 输出仅供辨证参考）；若将来做"observe 输出自动转档案"必须先修

### 既有、按决策不动

- 旧档案 validator `rc=1` 共 8 个（覆盖 0/6、置信度声称与实际不符）——"老档案不用在意"，不迁移
- `body_color` 词表缺口 `"红润"` → 7 分（既有，非本轮引入）→ 轮次 3 一并定
- 档案计数口径：`records/daily/*_analysis.json` 顶层 **11** 个（另有子目录/图片，`records` 未纳入 git 无法用 git 复核）；曾记"60 个"疑为含图片与子目录的口径，**无删除痕迹**
Now let me run experiments. Key probes:

  ① Round-2 changes:
  1. `_match_score` tie-break edges: same-length different scores; multiple keywords coexisting where a *longer* keyword exists but is negated while shorter non-negated (fine); but a subtle issue: tie-break takes the highest score among same-length — but what about a longer keyword with *lower* score? Longest wins still. Fine. Edge: dict iteration order of rules — with tie-break by score, order no longer matters for same-length. But what if the same-length keywords with equal scores both match — returns either (same score, doesn't matter). Also: `rules[kw] > rules[best_kw]` comparison requires int; fine.

  Potential hidden issue with tie-break: e.g. text "舌质淡白" for body_color rules: keywords "淡红":0, "淡白":7. "淡白" contains... does "淡红" appear? No. OK.

  But consider: text "苔润而滑" — "润"=0, "滑"=7 both length 1 → 7. Good. Consider "滑利而润" etc.

  Edge: negation of one occurrence only — "滑苔不多见，但苔滑" whatever.

  Another edge: scoring for coating_moisture "苔不润偏燥"? "不润" → "润" negated; "燥" unnegated → 8. Fine.

  But the tie-break interaction with negation: "湿润偏滑" — 润 unnegated (no negation before), 滑 unnegated → max=7. What about "苔滑而润" — 滑=7. OK.

  Potential issue: tie-break takes higher score — but consider "palm_temp" rules {"厥冷":8, "不温":4, "凉":4, "温":0}. Text "手足不温" → exact? Not in rules. Substring: "不温" matches (contains). Also "温" appears within "不温" — "温" occurrence at idx of 不温's 温： before it is "不" → negated. So "不温"=4 wins (longer). Text "手足温暖" → "温" unnegated → 0. Good.

  Edge case where tie-break could *overestimate* incorrectly: coating_moisture text "苔偏干燥但仍润"? "润" occurs after 干燥； before "润" is "仍" — not negation. So both hit, max(0, 8) = 8. Intent? "仍润" means still moist... marginal. Not a bug per se, it's the chosen fail-loud policy.

  2. _NEGATION_RE removed 非. Chain effects: does any keyword contain 非？ grep keywords: no keyword contains 非. But: negation words used as keywords themselves? "不温" is a keyword in palm_temp. "无" is a keyword in TOOTH_MARK_MAP/PETECHIAE_MAP etc. With text like "无" exact match. What about "非" appearing in negation window before keyword in real texts: "非正常红润" now scores 7 (intended). What about legitimate negations that used 非： "并非黄染" — previously 非（?！常） would negate... wait "并非" — 非 followed by 并， old regex 非（?！常） matched → negated. Now "并非黄染" → 黄染 NOT negated → false positive. That's a real regression risk! Also "绝非" "并非" "非" used as negation in "舌面非黄染" (rare). Let me test "并非黄染": before-window contains 非 but 非 no longer negation → scores. This is a漏判 risk: "并非水肿" would score 浮肿... Actually is that a fail-open? Yes — "并非" is a true negation. So the removal trades "非典型" false-negatives for "并非" false-positives. Worth flagging: recommend adding 并非/绝非 as negation phrases or the guard. Let me verify by experiment.

  3. _is_word_boundary: checks only char after the value. IndexError? It checks len(upper) > len(value) before indexing — safe. CJK range "一"(U+4E00) to "鿿"(U+9FFF) — covers common CJK but not extension chars, and not fullwidth punctuation like "，"(U+FF0C). "HIGH，置信度"? The char after HIGH would be ，— not in " -" and not in CJK range → None. Fullwidth chars fail-closed → None, safe direction. What about "HIGH（置信度）"? "（" U+FF08 not boundary → None, fail-closed. OK, direction safe. What about punctuation "."? "HIGH." → None. Fail-closed, fine.

  Note also: uppercase conversion of "一"..."鿿" — CJK unaffected by .upper(). Fine.

  Edge: does _is_word_boundary get called with upper char only; Chinese suffix check happens after. "高置信度" path: English loop doesn't match; Chinese first char 高， suffix 置信度 ∈ suffixes → HIGH. Good.

  4. _is_triggered laxness: value == 1 is True for True, 1, 1.0 (1.0 == 1 in Python), also for... value is True or value == 1: for value = "1" string handled by first branch. For value = 1.5 → False. For value = True → True. Danger: value == 1 with value being numpy bool? Not applicable. What about value = "TRUE " → strip/lower → "true" → True. Good. Chinese truth "是" → False. "对" → False. Hmm — LLM might output "triggered": "是"? Unlikely. What about other types like list? value == 1 False → fine. One subtle: bool is subclass of int so value == 1 covers True already; the `value is True or` is redundant but harmless. Also note False == 0 → value is False... value==1 for False is False. Good. What about 0.0? == 1? No. Edge: string "1.0" → not in list → False. Fine.

  But note interplay with validator: validator errors on non-bool triggered (input layer), while Record's lax reading tolerates. The docstring acknowledges. OK.

  5. _DOSAGE_RE `\d+\s*[gG克]`: false positives: "第3天10g"? "10g" matches — intended? "服用3天" no match. "10mg"? \d+\s*[gG] — "10mg": after digits comes "m" then "g"... \d+ matches "10", then \s* then needs [gG克] — next char is 'm', no match at that position; could match "0m"? No. Actually regex could match "g" at end? Need digits immediately before: in "10mg", is there \d+\s*[gG]? The only g is preceded by m. No match. Wait — but "mg" is a valid dosage unit! 10mg is a dosage but regex won't catch it. But for a *safety* check (formula content detection), missing "10mg" is a miss （漏报）. However 'g' alone with 克 covers Chinese practice; mg rare for herbs (herbs in grams). But西药 like "维生素C 100mg" would be missed → but would a formula contain mg? Possibly 生石膏等 in g. Minor miss.

  False positives: "三钱" — Chinese unit 钱 not covered → miss （漏报）. "第3天10g" — matches 10g, fine. "约5克左右" matches. False positive: "桂枝9克，白芍9克" — yes match. False positive risk: text "每日3次" no. "共5g生姜"? match, it is dosage anyway. False positive: "甘草泻心汤" already in whitelist. What about numbers with units like "6g" in unrelated note e.g. {"note": "体重增加2g..."} — unlikely. A more real false positive: "年龄36岁"? No 'g'. "G" uppercase: "3G" as in... "第五代"? no. "10G" memory? irrelevant. Also `_DOSAGE_RE` matches things like "3克" in "三克"? No — 三 is not \d. "三克" missed （漏报， Chinese numerals). Also 两/钱/分 units missed. So _DOSAGE_RE has 漏报 for Chinese-numeral dosages and 钱/两/毫克 units; 误报 risk low. Also formula names whitelist 27 — decent.

  Also: `has_formula_content` non-dict non-empty string counts as content — e.g. formula="无" → str("无").strip() truthy → True! Wait: `if not isinstance(formula, dict): return bool(str(formula).strip())`. formula = "无" → non-empty string → True (has formula content). That's fail-closed intentionally ("结构异常不能成为放行理由"). But "无" is a legit "no formula" answer in Chinese! get_formula returns {} for missing... but if record has formula: "无" (string), has_formula_content("无") → True → safety_violation false positive at LOW confidence. Hmm — is that pre-existing? Yes, that logic predates round 2 (bool(str.strip()) existed before). Not round-2 introduced. But worth noting interplay: the new fallback scan only applies to dicts. Existing test asserts has_formula_content("   ") is False but no test for "无". Let me check test_has_formula_content... The diff showed test asserts non-dict whitespace false. String "无" → True. Is that in tests? Check test_record.py test_has_formula_content. Let me check.

  6. get_pattern_differentiation narrowed: for shape A, now returns diag.get("许家栋经方辨证") or {}. Do historical A archives use other keys? Real records are shape B per plan. Check: are there any shape A records in records/daily? The 2026-08-28_analysis.json is shape C. Check keys in deepseek_diagnosis across daily records. Also pattern: `for key in ("pattern_differentiation", "pattern_update"): if key in self.raw` — note: for shape A record that happens to have top-level pattern_differentiation? fine. But subtle: pattern_update is shape C alias — but this loop runs for ALL shapes. If a shape A record had pattern_update, ok.

  Potential miss: historical A keys like "辨证" or "pattern"? Check records.

  7. has_formula_content fallback scan recursion: _flatten_to_text recursion — unbounded depth recursion; malicious deeply nested JSON could hit RecursionError. JSON.parse default depth limit ~... json.loads has recursion limit too. Practically fine. Performance: negligible. But one thing: _flatten_to_text converts non-string leaves via str() — numbers str() fine. Note: `elif obj is None: return ""` — but booleans: str(True) = "True" → included. formula={"active": True}? "True" contains no dosage. fine.

  Another subtlety in has_formula_content: content_keys check `any(formula.get(k) for k in content_keys)` — truthy check; formula={"name": ""} falls through to scan — good.

  But whitelist key miss: e.g. {"方剂": "桂枝汤"} — key "方剂" not in content_keys, but fallback scan finds 桂枝汤 → True. Good, that's the fix purpose.

  Miss: {"方剂": "苓桂甘枣汤"} — formula not in 27-name whitelist, no dosage → False. Whitelist is necessarily incomplete — inherent. Also "桂枝加葛根汤" contains "葛根汤"? "桂枝加葛根汤" contains substring "葛根汤" → True! Nice. "柴胡桂枝汤"? contains "桂枝" only, not "桂枝汤". Miss. Compound formulas like "桂枝加厚朴杏子汤" — contains "桂枝" + 汤 but not "桂枝汤" substring ("桂枝加..." → "枝加" breaks it). Miss. So whitelist substring gives partial coverage. Also formulas with 散/丸/饮 beyond list: "四逆散", "五积散", "藿香正气散" miss. So 漏报 remains for non-whitelisted names without dosage. Acceptable as defense-in-depth? Flag as known limitation.

  ② Checklist verification:
  A. Backup moved out — confirmed by ls (records/_backup/2026-08-28_analysis_v1_旧格式.json exists; daily has 2026-08-28_analysis.json only). Note: _backup file ends with .json actually! "2026-08-28_analysis_v1_旧格式.json" — it DOES end with .json. The plan says "非 .json 结尾" but ls shows .json. It's moved out of daily though, which is what matters since glob is scoped to RECORDS_DAILY_DIR. So claim "非.json 结尾" is inaccurate in the doc but harmless. Verify by re-running weekly report? The user said rerun verified 6.0. I can rerun read-only... generating weekly report writes files (charts, weekly json). Task says read-only, don't modify files. I can run functions in-process without writing (call load_week_records + generate_weekly_report_data, not main). That's read-only. Do that with python -c. But matplotlib import for charts not needed if just computing data.

  Also check: does daily dir still have other traps? e.g. 2026-07-15_b_analysis.json — same-date prefix! glob "2026-07-15*analysis*.json" matches both 2026-07-15_analysis.json and 2026-07-15_b_analysis.json; sorted()[-1] → "2026-07-15_b_analysis.json" (b > _). So for 2026-07-15 the report uses the _b record silently. That may be intended (b = second record of day?) but demonstrates checklist B's point is real, not hypothetical. Check what the _b file is.

  B. Accurate — and the _b case proves it. Also note vision_raw files: "2026-08-02_vision_raw.json" — glob "{date}*analysis*.json" — "2026-08-02_vision_raw.json" contains "analysis"? No ("vision_raw"). OK safe. But "2026-08-09_full_vision_raw.json" no. Fine.

  C. Check vision_client.py:122 — confirmed PROMPTS.get(part, PROMPTS["其他"]) no warning. classify at :113 does warn; observe doesn't. Accurate. Tests: check tests/test_vision_client.py content.

  D. Validator rc=1 8 files — could verify by running validator over daily files (read-only). body_color 红润 → 7: test "舌质红润" — "红" keyword unnegated → 7. Yes pre-existing.

  Third-class problems to check:
  - Other consumers of records/daily: only weekly report script globs; validator takes explicit path. backup_to_oss.sh excludes records/. Good.
  - Shape C × round 2: shape C A-path body_luster "舌质润燥" — C path is identity ["body_luster"], unaffected. But: does anything else reference 舌质荣枯？ grep repo. The vision prompt 舌面 prompt declares 舌质润燥. Check templates/daily_record_shape_c_template.json, adaptive_analysis_prompt.md, user-guide for stale 荣枯 references.
  - _DIMENSION_INDICATORS vs DIMENSION_RULES coverage diff: indicators per dimension vs rules — tongue has 18 indicators, 8 rules (now). Others: HEAD_FACE 9 indicators, 6 rules; EYE 5 vs 5; EAR 2 vs 2; HAND 5 vs 5; SKIN 5 vs 5. Diff: tongue indicators without rules: body_luster (intentional), body_dynamics, coating_color, coating_greasy, coating_peeling, coating_distribution, sublingual_color, sublingual_thickness, sublingual_petechiae; head_face: lip_around, nose_color, nose_bleeding no rules. That's the 轮次3 scope （评分覆盖扩展）. Note coating_peeling flagged in plan §3.1 to add.

  Also check: TONGUE_RADAR_METRIC_KEYS still 8 keys; the plan item 3.1 suggests adding coating_peeling later — pending.

  ④ Test validity review: examine the 8 new test functions. E.g. test_shape_a_danger_flags_triggered — verifies. test_tie_break — "滑燥并见": 滑=7, 燥=8 same length → 8. OK. "苔润不燥": 燥 negated by 不 → only 润 → 0. Valid.

  Potential fake coverage: test_shape_a_body_luster... asserts old key returns "" — good. test_parse_level_strict_boundary — fine. One thing: the tie-break test only covers coating_moisture; but does any other rules map have same-length different-score keywords? body_color: "淡红"0/"淡白"7 (len2 both): text "淡白"? exact → 7. text "舌质淡白偏淡红"? weird. palm_temp: "厥冷"8/"不温"4/"凉"4/"温"0. EYE jaundice "黄染明显"8/"黄染轻度"4/"黄染"4. sclera etc. So tie-break is generic.

  Hidden issue hunt in tie-break: previously "取命中最长" with dict order as tiebreak; now score-based. Any case where a *normal(0)* longer keyword vs shorter abnormal? E.g. coating_thickness "薄白"0 vs... text "薄白苔"? exact no; substring "薄白" len2 score0 — only hit → 0. Fine. What about text containing both "黄厚"7 and "薄黄"3 (len2)? max → 7 fail-loud. OK.

  Edge in _match_score: exact match check `text in rules` happens before negation guards — so text "不温" exact → 4 even though contains 不. Documented.

  Another subtle one: _is_negated window: "无明显的浮肿" — kw 浮肿 at some idx; before = "无明显的" → contains 无 → negated. Good. But now: "非正常" — consider HEAD_FACE face_color "红如妆"... fine.

  What about the removal of 非 affecting exact-match keyword "不温"? No.

  Regression check: texts that legitimately use 非 as negation in the actual archives: grep records for 非. Let me grep records/daily json for 非.

  Also check: does any scoring keyword itself start with negation char such that guard self-negates? "不温": if text == "不温" exact match path. If text "手足不温" → substring idx; before window "手足" no negation; OK. If text "并非不温" → double negation edge, negligible.

  jaundice rules: "黄染明显":8, "黄染轻度":4, "黄染":4. Text "非典型黄染" → "黄染" → 4 (test asserts). fine.

  Now run experiments in python. Also run the full test suite + ruff to confirm. Also validate the 8 old archives rc=1 claim quickly (validator on each daily json).

  Also check grep for 舌质荣枯 leftovers anywhere (docs, templates, tests). And check shape C template keys.

  Also "红润" issue: TONGUE_BODY_COLOR_MAP lacks 红润. Confirm.

  Let me also check tests/test_vision_client.py and conftest fixtures.

• 核心文件已读完。现在做实测探针。== _match_score 平局/边界 ==
'湿润偏滑' → 7
'滑燥并见' → 8
'苔润不燥' → 0
'不滑反润' → 0
'苔干燥但仍润' → 8
'润燥相济' → 8
== 非 否定连锁 ==
'非正常红润' body_color→ 7 | jaundice→ 0 | edema→ 0
'并非黄染' body_color→ 0 | jaundice→ 4 | edema→ 0
'绝非浮肿' body_color→ 0 | jaundice→ 0 | edema→ 4
'并非淡红舌' body_color→ 0 | jaundice→ 0 | edema→ 0
'舌面非充血' body_color→ 0 | jaundice→ 0 | edema→ 0
== parse_level 边界 ==
'HIGH1'
 → None
'HIGH_2' → None
'HIGHEST' → None
'HIGH CONFIDENCE' → ConfidenceLevel.HIGH
'HIGH-置信' → ConfidenceLevel.HIGH
'HIGH置信度' → ConfidenceLevel.HIGH
'HIGH，置信' → None
'HIGH。' → None
'HIGH（高）' → None
'HIGH.' → None
'HIGH\x00' → None
'高' → ConfidenceLevel.HIGH
'中等'
 → ConfidenceLevel.MEDIUM
'低度' → ConfidenceLevel.LOW
'MEDIUM1' → None
'LOW2' → None
' high ' → ConfidenceLevel.HIGH
'HIGH\tCONF' → None
== _is_triggered ==
True → True
False → False
1 → True

0 → False
1.0 → True
0.5 → False
'true' → True
'TRUE ' → True
'Yes' → True
'1' → True
'是' → False
'对' → False
'真' → False
[1] → False
None → False
2 
→ False
-1 → False
== has_formula_content 兜底 ==
{'note': '含桂枝10g'} → True
{'note': '10mg 维生素'} → False
{'note': '三钱'} → False

{'note': '第3天10g'} → 
True
{'note': '四逆散加减'} → False
{'note': '柴胡桂枝汤'} → True
{'note': '桂枝加厚朴杏子汤'} → False
{'note': '桂枝加葛根汤'} → True
{'note': '五苓散'} → True
{'desc': '每日3次'}
 → False
{'d': '3克'} → True
formula='无' (非dict) → True


• Key findings so far:
  - 并非/绝非 negations are now NOT recognized → false positives (fail-open on scoring). "并非黄染" → 4. This is a real chain-effect regression from removing 非.
  - parse_level: tab not a boundary — "HIGH\tCONF" → None. Docstring says 空格； tab fail-closed, safe. Fine but note.
  - has_formula_content: 10mg missed, 三钱 missed, 四逆散/柴胡桂枝汤 — wait "柴胡桂枝汤" returned True? Because contains "柴胡桂"... hmm "柴胡桂枝汤" — does it contain any whitelist substring? "柴胡桂枝干姜汤" no. "桂枝汤"? "柴胡桂枝汤" contains "枝汤"? Let me think: 柴胡桂枝汤 = 柴，胡，桂，枝，汤. Substring "桂枝汤" = 桂，枝，汤 — positions: 桂（2）枝（3）汤（4) — yes! "柴胡桂枝汤" ends with "桂枝汤". True via substring. Good. "四逆散" → False (miss; 四逆汤 in list, 散 not). "桂枝加厚朴杏子汤" → False — miss （真实经方）. "10mg" miss. "三钱" miss.
  - formula="无" → True: pre-existing fail-closed overreach; actually could cause false safety_violation. Check real archives whether formula is ever a bare string "无".

  Now check historical archives for shape A pattern keys, 舌质荣枯 remnants, 并非/非 negation usage in real records, and verify weekly report reproduces 6.0 read-only. Also test suite run, validator rc check, tests/test_vision_client.py contents../src/scoring.py
./docs/REPAIR_PLAN_2026-08-25.md
./docs/K3_REVIEW_2026-09-17.md
./docs/K3_SHAPE_C_ADVICE_2026-09-17.md
./docs/CODE_REVIEW_2026-08-25_KIMI.md
./tests/test_record.py
./tests/test_scoring.py
---荣枯 in records---
records/daily/2026-06-29_analysis.json
records/daily/2026-07-03_analysis.json
---非 as negation in records---
2026-06-25_analysis.json shape=B diag_keys= None top= ['confidence', 'pattern_differentiation', 'formula', 'danger_flags']
2026-06-29_analysis.json shape=B diag_keys= None top= ['confidence', 'formula']
2026-07-03_analysis.json shape=B 
diag_keys= None top= ['confidence']
2026-07-09_analysis.json shape=B diag_keys= None top= ['confidence', 'pattern_differentiation', 'formula']

2026-07-10_analysis.json shape=B diag_keys= None top= ['confidence', 'pattern_differentiation', 'formula']
2026-07-15_analysis.json shape=B diag_keys= None top=
 ['confidence', 'pattern_differentiation', 'formula']
2026-07-15_b_analysis.json shape=B diag_keys= None top= 
['confidence', 'pattern_differentiation', 'formula']
2026-08-02_analysis.json shape=C diag_keys= 
None top= ['confidence', 'formula_with_dosage', 'pattern_differentiation']
2026-08-09_analysis.json shape=C diag_keys=
 None top= ['confidence', 'formula_adjust']
2026-08-14_analysis.json shape=C diag_keys= 
None top= ['confidence', 'pattern_update', 'formula_adjust']
2026-08-28_analysis.json shape=C diag_keys= 
None top= ['confidence', 'pattern_update', 'formula']
2026-08-28_analysis_v1_旧格式.json shape=C diag_keys= 
None top= ['confidence', 'pattern_update', 'formula']
Interesting: 2026-08-02 shape=C but has "pattern_differentiation" (not pattern_update) — handled. No shape A records at all — so get_pattern_differentiation narrowing is zero-risk for history. 荣枯 appears in 06-29 and 07-03 (shape B) — check where: B path is body.luster; "荣枯" might be in text values. Check.

  Wait — 2026-08-02 has both "formula_with_dosage" AND is shape C. get_formula checks formula, formula_adjust, formula_with_dosage — fine.

  Note 2026-08-28 (C) has both pattern_update AND formula top-level. OK.

  Also 06-29/07-03 mention 荣枯 — where? Check context. Since they're shape B, the A-path key rename doesn't affect them. But if their B observations use "荣枯" text in body.luster... scoring no longer includes body_luster at all → text ignored for scoring. Fine.

  Now: check 荣枯 context in those records, verify weekly report read-only (6.0 & consistent), run pytest + ruff, inspect test_vision_client.py, validator rc over all daily files, check shape C template & prompt for stale key names, and check _b file choice for 07-15.records/daily/2026-06-29_analysis.json:荣枯
records/daily/2026-07-03_analysis.json:荣枯
===
loaded dates: ['2026-08-28']
summary: 本周（2026-08-28 至 2026-08-28）共 1 条日分析记录。舌诊综合偏离度由 6.0 变化至 6.0；当前偏离度最高的维度为「舌诊」（6.0 分）。舌质颜色偏离度整体稳定（0.0 → 0.0） 头面诊偏离度整体稳定（0.0 
checks: [{"date": "2026-08-28", "claimed": "HIGH", "covered_dimensions": 6, "expected": "HIGH", "consistent": true}]
07-15 glob: ['records/daily/2026-07-15_analysis.json', 'records/daily/2026-07-15_b_analysis.json']
 → 选中: records/daily/2026-07-15_b_analysis.json
Checklist A verified: weekly report now reads 2026-08-28 → 6.0, consistent=true, no violation. And the _b selection demonstrates B is real.

  Check where 荣枯 appears in those B records (probably in a text value; harmless). Now run full test suite + ruff, look at tests/test_vision_client.py, validator over daily files, shape C template keys, and check test validity of the 8 new tests. Also check templates/adaptive_analysis_prompt.md for stale key names and 舌质润燥 references. Also check tests/test_record_shape_c.py./usr/local/lib/hermes-agent/venv/bin/python3: No module named pytest
Found 177 errors.
[*] 127 fixable with the `--fix` option (7 hidden fixes can be enabled with the `--unsafe-fixes` option).
---07-03---
No pytest in that python; maybe there's a venv. Also ruff default run shows 177 errors but that's full rule set; the project uses F,E722 only. Let me find how tests were run (README/requirements-dev). And 荣枯 find printed nothing for 06-29 (only the grep line header?) — actually the output shows nothing before ---07-03---, meaning find didn't hit; but grep found "荣枯" — maybe it's in a non-string context? grep -o earlier printed "records/...:荣枯" meaning match exists. My python find should have caught it... unless the JSON has it inside a key? find only searches string values, not keys. Could be a key name. Check.===
/usr/local/bin/pytest
# 开发依赖：跑测试用
-r requirements.txt
pytest>=7.0
: "img7_skin.jpg"}}, "observations": {"舌面": {"舌质颜色": "（示例）", "荣枯": "（示例）", "老嫩": "（示例）", "舌体": "（示例）", "苔色": "（示例）", "苔厚薄": 
8_handback.jpg"}}, "observations": {"舌面": {"舌质颜色": "（示例）", "荣枯": "（示例）", "老嫩": "（示例）", "舌体": "（示例）", "苔色": "（示例）", "苔厚薄":
===
......................................................                   [100%]
198 passed in 0.39s
198 passed confirmed. 荣枯 in old B records is inside observations."舌面" (Chinese dimension name — shape B with Chinese dim key!). Interesting: shape B records use observations with 中文 dimension key "舌面" not "tongue"! So _dimension_root for shape B uses dim.english_name "tongue" → container.get("tongue") → missing → {} → tongue not covered?! But these are old records where validator gives rc=1 （覆盖 0/6) — consistent with checklist D's "覆盖 0/6". OK, known.

  Now ruff with the project's rule set:All checks passed!
===
"""vision_client 单元测试 — 全部 mock，无真实网络请求。"""
import io
import json
import urllib.error

import pytest

import vision_client


def _fake_response(payload):
    """构造 urlopen 返回值：支持 with 上下文管理，read() 返回 JSON 字节。"""
    class Resp:
        def read(self):
            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False
    return Resp()


@pytest.fixture
def img(tmp_path):
    p = tmp_path / "t.jpg"
    p.write_bytes(b"\xff\xd8fake-jpeg-bytes")
    return str(p)


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("VISION_API_KEY", "test-key")


def _block_env_files(monkeypatch, tmp_path):
    """让 load_key 读到的 .env 路径都指向不存在的位置。"""
    monkeypatch.setattr(vision_client.os.path, "expanduser",
                        lambda p: str(tmp_path / "nonexistent" / p[2:])
                        if p.startswith("~/") else p)


# ① 正常调用
def test_call_success(monkeypatch, img, key):
    monkeypatch.setattr(vision_client.urllib.request, "urlopen",
                        lambda req, timeout=None: _fake_response(
                            {"choices": [{"message": {"content": "舌面"}}]}))
    dt, out = vision_client.call(img, "prompt")
    assert out == "舌面"
    assert isinstance(dt, int)


def test_call_uses_mime_of_extension(monkeypatch, tmp_path, key):
    png = tmp_path / "t.png"
    png.write_bytes(b"\x89PNG-fake")
    seen = {}

    def capture(req, timeout=None):
        seen["body"] = json.loads(req.data.decode())
        return _fake_response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(vision_client.urllib.request, "urlopen", capture)
    vision_client.call(str(png), "prompt")
    url = seen["body"]["messages"][0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")


# ② HTTP 4xx/5xx 与缺 choices 不抛 KeyError，而是带状态码的 RuntimeError
def test_call_http_500(monkeypatch, img, key):
    def boom(req, timeout=None):
        raise urllib.error.HTTPError("http://x", 500, "Server Error", {},
                                     io.BytesIO(b"internal boom"))
    monkeypatch.setattr(vision_client.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError) as e:
        vision_client.call(img, "p")
    assert "500" in str(e.value)


def test_call_http_401(monkeypatch, img, key):
__pycache__
conftest.py
fixtures
test_confidence.py
test_dimensions.py
test_record.py
test_record_shape_c.py
test_retrieval
test_scoring.py
test_vision_client.py
test_weekly_report.py
45:def test_call_success(monkeypatch, img, key):
54:def test_call_uses_mime_of_extension(monkeypatch, tmp_path, key):
70:def test_call_http_500(monkeypatch, img, key):
80:def test_call_http_401(monkeypatch, img, key):
90:def test_call_missing_choices(monkeypatch, img, key):
97:def test_call_url_error(monkeypatch, img, key):
106:def test_main_no_args(capsys):
113:def test_main_observe_missing_part(img, capsys):
120:def test_main_unknown_mode(img, capsys):
128:def test_call_without_key(monkeypatch, img, tmp_path):
138:def test_load_key_env_file_comments(monkeypatch, tmp_path):
166:def test_mime_type(name, expected):
171:def test_classify_unknown_fallback(monkeypatch, img, capsys):
180:def test_classify_known_output(monkeypatch, img, capsys):
===
templates/adaptive_analysis_prompt.md:39:| **头面诊**（面域+唇域+鼻域） | ⭐⭐⭐ | 表里观最强（表里寒热第一视觉指标） | 火证（面赤）、水证（面肿）、血证（萎黄/唇萎）、气证（鼻翼煽动） | 太阳/少阴/真厥阴（戴阳鉴生死）+少阳（口唇指向） | 太阳面赤 vs 少阴戴阳；唇色+润燥判津液 |
templates/adaptive_analysis_prompt.md:231:| 头面诊 | 「今日未拍摄头面部照片，无法观察面色寒热、有无戴阳、唇色润燥、鼻翼煽动等指标，建议明日补充」 |
Confirmed C②: test_vision_client.py has no JSONDecodeError test and no timeout test... wait test_call_url_error at :97 — that covers URLError/timeout? vision_client wraps (URLError, socket.timeout, TimeoutError) → RuntimeError. Let me check what test_call_url_error raises. And no JSONDecodeError test (API returns invalid JSON) — confirmed by grep of test names; need to verify line 97. Also no test asserting 舌质润燥 in PROMPTS["舌面"] — grep showed no 润燥/荣枯 in test file. Confirmed.

  Check test_call_url_error body quickly, and check templates/daily_record_shape_c_template.json keys & weekly template, and the shape C test file briefly. Also validate all daily files rc to confirm D. Also check that tests/test_weekly_report.py has coverage of glob behavior.def test_call_url_error(monkeypatch, img, key):
    def boom(req, timeout=None):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(vision_client.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError):
        vision_client.call(img, "p")


# ③ 参数不足 / 未知 mode 退出码 2
def test_main_no_args(capsys):
===
['_comment', 'date', 'confidence', 'tongue', 'head_face', 'eye', 'ear', 'hand', 'skin', 'inquiry', 'pattern_update', 'formula', 'danger_flags']
tongue keys: ['body_color', 'body_luster', 'body_size', 'petechiae', 'tooth_marks', 'fissure', 'prickles', 'body_dynamics', 'coating_color', 'coating_thickness', 'coating_moisture', 'coating_greasy', 'coating_peeling', 'coating_distribution', 'sublingual_color', 'sublingual_thickness', 'sublingual_varicosity', 'sublingual_petechiae']
===
24:def test_compute_dimension_deviation_non_zero(real_raw):
34:def test_extract_tongue_metrics_non_zero(real_raw):
44:def test_weekly_report_data_valid_output(real_raw):
62:def test_validator_passes_real_record(real_raw, capsys):
72:def test_low_confidence_formula_flagged():
108:def test_low_confidence_ingredients_only_formula_flagged():
122:def test_unreported_confidence_does_not_bypass_safety():
134:def test_unparseable_confidence_does_not_bypass_safety():
148:def test_malformed_record_reports_error_not_traceback():
161:def test_danger_flags_type_errors_are_errors():
177:def test_load_week_records_tolerates_numeric_date(monkeypatch, tmp_path):
191:def test_weekly_summary_flags_safety_violation():
205:def test_empty_records_report_structure():
records/daily/2026-06-25_analysis.json rc=0
records/daily/2026-06-29_analysis.json rc=1
records/daily/2026-07-03_analysis.json rc=0
records/daily/2026-07-09_analysis.json rc=1
records/daily/2026-07-10_analysis.json rc=1
records/daily/2026-07-15_analysis.json rc=1
records/daily/2026-07-15_b_analysis.json rc=1
records/daily/2026-08-02_analysis.json rc=1
records/daily/2026-08-09_analysis.json rc=1
records/daily/2026-08-14_analysis.json rc=1
records/daily/2026-08-28_analysis.json rc=0
Validator rc=1 count = 7 files (06-29, 07-09, 07-10, 07-15, 07-15_b, 08-02, 08-09, 08-14) — wait count: 06-29, 07-09, 07-10, 07-15, 07-15_b, 08-02, 08-09, 08-14 = 8. Yes 8. D confirmed.

  But interesting: 08-02, 08-09, 08-14 are shape C and rc=1! Why? Let me check the reason — maybe confidence claim mismatch or something round-2-relevant. The checklist D said "覆盖 0/6、置信度声称不符". Shape C records failing validator — is that expected? Check one.

  Also check tests/test_record_shape_c.py quickly for fake coverage. And check why 08-28 rc=0 but 08-02/09/14 rc=1.验证结果: 1 个严重错误, 7 个警告

--- 严重错误 ---
🚨 安全边界违反: confidence=HIGH (全维度7部位照片)（LOW）不应输出方剂，但记录包含方剂内容

--- 警告 / 提示 ---
⚠️ 维度未覆盖: 舌诊（tongue）
⚠️ 维度未覆盖: 头面诊（head_face）
⚠️ 维度未覆盖: 目诊（eye）
--
❌ 存在严重错误，请修正后重新提交。
"confidence=HIGH （全维度7部位照片）" — parse_level("HIGH （全维度7部位照片）"): after HIGH comes space → boundary → HIGH. But validator says LOW — because claimed parsed HIGH but covered=0/6 → inferred LOW → safety check triggers. Wait but the record is shape C with tongue keys... "维度未覆盖： 舌诊"?? Shape C record with tongue dict — why uncovered? Let me look at 08-09's tongue content. Perhaps values are empty strings. Actually "HIGH （全维度7部位照片）" parses to HIGH (space boundary) but coverage 0/6 → is_consistent false. Why coverage 0? Check raw.{"body": "（示例舌象描述，合成数据）", "coating": "（示例苔质描述，合成数据）", "sublingual": "正常"}
{}
covered: 0
Important third-class finding! 2026-08-09 is detected as shape C (top-level "tongue" key) but its tongue node uses **shape B-style nested English paths** ({"body": ..., "coating": ..., "sublingual": ...}) — a hybrid "B-path under C-top-level" record. Shape C path is identity ["body_color"] etc., so get_observation returns all empty → coverage 0/6 → inferred LOW → safety violation. It's a real旧档案 issue, covered by checklist D ("老档案不用在意")? Checklist D says rc=1 共8个 "覆盖 0/6、置信度声称不符" — yes this matches. But the interesting nuance: 08-02/08-09/08-14 are "C 顶层 + B 内层路径" hybrids, not pure C. The record module could in principle fall back: for shape C, if identity path missing, try B path? Currently paths.get(shape_key) only. Not asked to fix; but worth noting the 3 "C" archives are actually hybrids and score 0 in weekly reports → but wait, weekly report for week covering 08-14 would show 舌诊 0.0. Hmm — 8/14 is within 7 days of... current date 2026-09-17, so not in this week. Historical. But it does affect any weekly report covering that week. Since user decided 老档案不用在意， note as part of D but with sharper diagnosis: they're hybrid shape records misclassified as C (top-level C keys trigger shape C, but inner structure is B). Actually _dimension_root for shape C: container = raw, key = english_name "tongue" → exists → root = d["tongue"] which has B-style inner keys; get_observation uses C path → empty. So hybrid = silently zero. That IS the same class as checklist B: silent mis-selection/zero without warning. Worth flagging as 第三类问题 #1 (hybrid shape → silent zero coverage, no warning from validator beyond "未覆盖" warnings... actually validator did warn 未覆盖； but weekly report just scores 0 silently).

  Also this interacts with 轮次2? Not introduced, but the round-2 body_luster A-path change is similar in kind.

  Now ② third-class checks: consumers of records/daily beyond weekly report — only validator (explicit path), backup excludes records. Confirmed. tests/fixtures? conftest real_record fixture — check what file it points to.

  _DIMENSION_INDICATORS vs DIMENSION_RULES diff — compute programmatically.

  Also check shape C test file for fake coverage, and check that test_weekly_report has no test of the glob selection (test_load_week_records_tolerates_numeric_date only). So the glob selection heuristic has zero tests — supports B fix needing tests.

  Also verify tie-break test validity: e.g., test asserts "苔润不燥" → 0: 燥 negated... wait 不燥 — negation before 燥 → negated → 润=0 → yes.

  Fake coverage check on new tests: test_shape_a_danger_flags_triggered asserts list order ["daiyang","skin_cold","flesh_wasted"] — dict order preserved, fine.

  test_has_formula_content_fallback_scan: fine.

  One more probe for ①: get_pattern_differentiation — no shape A historical records exist, and diag keys are None everywhere → narrowing has zero real impact; the fix is defensive only. But check templates/multi_dim_record_template.json (shape A template) deepseek_diagnosis keys — does the template use "许家栋经方辨证"? If template uses a different key, shape A records would always return {}. Check.

  Also check adaptive_analysis_prompt.md for the 辨证 key name.

  Also probe _match_score further: "苔干燥但仍润" → 8. Semantically "干燥" true + "仍润" — 8 arguably right (dry present). Fine.

  Another edge: keyword "无" in TOOTH_MARK_MAP etc. Text "无" exact → 0. Text "齿痕无" → substring "无" unnegated? _is_negated: before window "齿痕" no negation word... but "无" itself IS the keyword meaning "none" scoring 0. OK. Text "无明显齿痕" for tooth_marks: keywords 轻度/中度/重度/无 — "无" appears unnegated occurrence? The keyword "无" at idx0: before empty, after = "明显齿痕" — _POST_NEGATION_RE.match("明显齿痕")? No. So "无" matches → score 0. Good — "无" as keyword returning 0 is normal-baseline. But text "并非无齿痕"... edge, skip.

  What about negation of the keyword "无" itself being a negation word: e.g. PETECHIAE_MAP "无":0, text "散在瘀点，无瘀斑" — "散在" unnegated? before "散在" is empty → unnegated → 5. "无" also matches → same length 1 vs 2: 散在 longer → 5. Good. Text "无瘀斑瘀点" → "无" exact? no, substring "无" at idx0: is 无 negated? before empty → no → "无" scores 0... but "散在"/"密集" not present → 0. Correct.

  But here's a subtle one: "未见明显瘀斑" for petechiae: keywords 无/散在/密集 — none present → 0. Fine.

  Tongue body_color: text "示例舌色" → "淡红"(0) and... "淡白"? no. → 0. "红润" → "红"=7 (known issue D).

  Now check templates and prompts for key-name alignment (C③): template multi_dim_record_template.json (shape A) — check deepseek_diagnosis key and whether A path keys align with vision PROMPTS. And adaptive prompt.['许家栋经方辨证', '传统辨证参照', '综合辨证结论', '体质类型', '方剂建议', '饮食调理', '作息建议', '调理预期', '因问诊缺失导致的不确定性']
['舌质颜色', '舌质润燥', '瘀斑瘀点', '舌苔颜色', '舌苔厚薄', '舌苔润燥', '舌苔腻腐', '舌苔剥落', '舌苔分布', '舌体胖瘦', '齿痕', '裂纹', '点刺', '舌体动态', '舌下络脉颜色', '舌下络脉粗细', '舌下络脉迂曲', '舌下络脉瘀点']
===
templates/multi_dim_record_template.json:140:    "许家栋经方辨证": {
templates/multi_dim_record_template.json:171:    "方剂建议": {
templates/multi_dim_record_template.json:195:  "danger_flags": {
templates/adaptive_analysis_prompt.md:21:2. **置信度封顶**：证据维度越多、置信度越高；证据越少、结论越宽泛。不得在仅有1-2个维度时就给出具体方剂建议。
templates/adaptive_analysis_prompt.md:157:步骤5：方剂建议
templates/adaptive_analysis_prompt.md:218:   → ❌ 不输出方剂建议
templates/adaptive_analysis_prompt.md:446:**方剂建议**：
templates/adaptive_analysis_prompt.md:578:**❌ 当前不输出方剂建议、不输出剂量、不输出具体治法。**
templates/adaptive_analysis_prompt.md:610:- 不给任何方剂建议
===
"""pytest 共享配置：把仓库根与 scripts/ 加入 import 路径。

仓库根入 sys.path → 测试与 README 一致地使用 `from src.record import ...`；
scripts/ 入 sys.path → 可直接 `import generate_weekly_report` 做集成测试。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_ROOT, "scripts")
for p in (_ROOT, _SCRIPTS):
    if p not in sys.path:
        sys.path.insert(0, p)
Template shape A uses "许家栋经方辨证" — get_pattern_differentiation A-path aligns with template. Good. But note: a shape A record missing that key but having 综合辨证结论 returns {} — by design (#9).

  Check conftest real_record fixture — tests/conftest.py doesn't define real_record; maybe in tests/test_weekly_report.py or fixtures dir. Check quickly. Also compute indicator/rules diff. Also inspect tests/test_record_shape_c.py briefly for fake coverage. And verify tie-break dict-order independence — actually with score-based tie-break, order-independent for unequal scores. Equal-score ties: order-dependent but value same. OK.

  One more: check the docstring in scoring.py line 246-247 mentions known limitation about negation hurting next keyword — with 非 removed, "非正常" case fixed but "并非" lost. Good.

  Also: weekly report week covering 08-09: the hybrid record scores 0.0 silently. Confirm quickly? compute_dimension_deviation on 08-09 → tongue 0. Already know coverage 0.

  Now indicators vs rules diff:tongue 无评分规则: ['body_dynamics', 'body_luster', 'coating_color', 'coating_distribution', 'coating_greasy', 'coating_peeling', 'prickles', 'sublingual_color', 'sublingual_petechiae', 'sublingual_thickness'] | 规则无指标: []
head_face 无评分规则: ['lip_around', 'nose_bleeding', 'nose_color'] | 规则无指标: []
eye 无评分规则: [] | 规则无指标: []
ear 无评分规则: [] | 规则无指标: []
hand 无评分规则: [] | 规则无指标: []
skin 无评分规则: [] | 规则无指标: []
===
tests/test_weekly_report.py:19:def real_raw():
tests/test_weekly_report.py:24:def test_compute_dimension_deviation_non_zero(real_raw):
tests/test_weekly_report.py:34:def test_extract_tongue_metrics_non_zero(real_raw):
tests/test_weekly_report.py:44:def test_weekly_report_data_valid_output(real_raw):
tests/test_weekly_report.py:62:def test_validator_passes_real_record(real_raw, capsys):
tests/test_record.py:24:def real_record():
tests/test_record.py:29:def test_parses_real_record_as_shape_b(real_record):
tests/test_record.py:34:def test_get_observation_tongue_has_content(real_record):
tests/test_record.py:44:def test_get_observation_text_non_empty(real_record):
tests/test_record.py:49:def test_get_formula_non_empty(real_record):
tests/test_record.py:57:def test_get_pattern_differentiation(real_record):
tests/test_record.py:64:def test_get_danger_flags(real_record):
tests/test_record.py:71:def test_dimension_coverage_six(real_record):
tests/test_record.py:77:def test_inquiry_coverage(real_record):
tests/test_record.py:82:def test_confidence_claimed(real_record):
tests/test_record.py:86:def test_all_dimensions_return_stable_structure(real_record):
tests/test_record.py:236:def test_no_information_loss_against_raw(real_record):
2026-06-25_analysis.json
shape_c_sample.json
Now inspect tests/test_record_shape_c.py for fake coverage and check the shape C fixture. Also check tests/test_record.py real_record fixture uses fixtures/2026-06-25_analysis.json — a shape B record. Let me look at test_record_shape_c.py quickly and the new 8 tests... Actually the "8 new test functions" per the user: test_parse_level_strict_boundary, test_has_formula_content_fallback_scan, test_shape_a_body_luster_moisture_path, test_shape_a_pattern_differentiation_missing_key_returns_empty, test_shape_a_danger_flags_triggered, test_fei_is_not_negation_for_abnormal_prefix, test_body_luster_not_scored, test_tie_break_prefers_higher_score = 8. Assess each for fake coverage:

  1. test_parse_level_strict_boundary — real.
  2. test_has_formula_content_fallback_scan — real but doesn't test漏报 boundaries (10mg/三钱）.
  3. test_shape_a_body_luster_moisture_path — real, asserts old key rejected.
  4. test_shape_a_pattern_differentiation... — real.
  5. test_shape_a_danger_flags_triggered — real.
  6. test_fei_is_not_negation... — real; but misses the 并非/绝非 regression case.
  7. test_body_luster_not_scored — asserts "body_luster" not in inds. Note: score_indicators returns keys = rules_map keys only; body_luster removed from rules so absent. Real verification.
  8. test_tie_break_prefers_higher_score — real, including negation interplay.

  Potential fake coverage note: test_fei... uses "非正常红润" body_color → 7. But wait — is that actually the desired semantics? "非正常红润" — 红润 not in map; "红" hit → 7. OK.

  Another check on tie-break: '润燥相济' → 8 （燥=8 vs 润=0). Semantically "润燥相济" is a balanced/normal-ish phrase — scored 8, false-positive-ish but fail-loud policy. Note as accepted consequence.

  One more probe from the task: has_formula_content recursion risk — deep nesting: python recursion limit 1000; json.loads itself fails first at deep nesting (RecursionError during parse). Actually json.loads raises RecursionError beyond ~1000 too. _flatten_to_text recursion depth equals JSON depth, already bounded by parse. Not a new risk.

  Also check: `get_pattern_differentiation` for shape B/C — loop checks keys in raw for ALL shapes. If a shape A record has both doubao_vision_analysis AND pattern_update? fine.

  One more thing to verify for ②: does anything else glob records/daily? Grep whole repo for "glob". And check scripts/draw_hand_diagram.py — reads archives? Check.src/retrieval/grep_search.py:22:  - 递归 glob **/*.md，默认排除 README.md（元文档）。
src/retrieval/grep_search.py:37:from glob import glob
src/retrieval/grep_search.py:63:    files = glob(os.path.join(root, "**", "*.md"), recursive=True)
src/retrieval/grep_search.py:145:    # 已天然按 file→line 升序（glob 排序 + 行号递增），无需再排
src/retrieval/rag_search.py:119:    from glob import glob
src/retrieval/rag_search.py:122:    files = sorted(glob(os.path.join(root, "**", "*.md"), recursive=True))
src/retrieval/rag_search.py:344:    global _default
===
"""形状 C（自由格式，顶层规范英文维度键）测试。

fixture tests/fixtures/shape_c_sample.json 为脱敏样例（字段与值风格参考
records/daily/2026-08-28_analysis.json，不含任何患者身份信息）。
"""
import json
import os

import pytest

from src.record import DailyRecord
from src.dimensions import VisionDimension
from src import scoring

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "shape_c_sample.json"
)


@pytest.fixture
def shape_c_record():
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return DailyRecord(json.load(f))


# ---- 形状检测优先级 ----

def test_pure_shape_c_detected(shape_c_record):
    assert shape_c_record.shape == "C"


def test_observations_takes_priority_over_c_keys():
    raw = {"observations": {}, "tongue": {"body_color": "淡红"}}
    assert DailyRecord(raw).shape == "B"


def test_empty_dict_defaults_to_b():
    assert DailyRecord({}).shape == "B"


# ---- 维度键别名 face/palm ----

def test_face_alias_maps_to_head_face():
    record = DailyRecord({"face": {"face_color": "萎黄"}})
    assert record.shape == "C"
    assert record.get_observation(VisionDimension.HEAD_FACE)["face_color"] == "萎黄"


def test_palm_alias_maps_to_hand():
    record = DailyRecord({"palm": {"palm_color": "淡白"}})
    assert record.shape == "C"
    assert record.get_observation(VisionDimension.HAND)["palm_color"] == "淡白"


def test_canonical_key_wins_over_alias():
    record = DailyRecord({
        "head_face": {"face_color": "晦暗"},
        "face": {"face_color": "萎黄"},
    })
    assert record.get_observation(VisionDimension.HEAD_FACE)["face_color"] == "晦暗"
Enough. retrieval globs knowledge_base, not records. draw_hand_diagram doesn't glob records. vision_client no records access.

  One more check: is there a hybrid-shape test? The hybrid (C top-level + B inner paths) — check if test_record_shape_c covers it... probably not. That's the third-class finding #1.

  Also quick check: 2026-08-02 (shape C, rc=1) — same hybrid? It has formula_with_dosage and pattern_differentiation. Check its tongue structure to characterize.records/daily/2026-08-02_analysis.json ['body_color', 'body_shape', 'teeth_marks', 'coating_color', 'coating_thickness', 'coating_moisture', 'coating_greasy', 'coating_peeling']
  confidence= 'HIGH (照片3/6 + 用户确认目/耳/皮肤正常视同6/6)'
records/daily/2026-08-14_analysis.json ['body', 'coating', 'peeling', 'sublingual']
  confidence= 'HIGH (舌面+舌底照片, 用户确认余维度正常)'
Confirmed: three pre-08-28 "C" archives are hybrids: 08-02 uses identity-ish keys but "body_shape"/"teeth_marks" instead of canonical body_size/tooth_marks → partial miss; 08-14 uses B inner paths; 08-09 B inner paths. All → coverage 0 → rc=1. These are covered by decision D （老档案不动）, but worth noting the record module's shape C path is strict identity and old hybrid archives silently score 0 in weekly reports. 08-28 is pure C (works).

  Also note 08-02's confidence "HIGH （照片3/6...)" — parse_level: after HIGH comes space → HIGH. OK.

  Now verify parse_level('HIGH （照片...') — space boundary, fine.

  I have enough for the report. Let me also double-check the doc claim "非 .json 结尾" vs reality (.json 结尾 but moved out of daily) — A claim mostly accurate; the mechanism of fix is the move, not the extension.

  Also check docs statement "偏离度 6.0" verified above (read-only run, no files written — generate_weekly_report_data pure). Good.

  One more possible ① item: _match_score iterates `for kw in rules` — tie-break only by score now; for equal length AND equal score, first-in-dict wins — deterministic. Fine.

  _NEGATION_RE removal chain effects beyond scoring: _NEGATION_RE used anywhere else? grep.

  Also check: does anything import TONGUE_BODY_LUSTER_MAP still? grep.src/scoring.py:181:# body_luster（舌质润燥，原"舌质荣枯"）不进雷达图也不参与评分：光泽受
src/scoring.py:205:_POST_NEGATION_RE = re.compile(r"不明显|不显著|不突出|不著|未见|阴性")
src/scoring.py:220:    if _NEGATION_RE.search(before):
src/scoring.py:224:    return bool(_POST_NEGATION_RE.match(after))
src/record.py:50:        "body_luster":             {"A": ["舌质润燥"],         "B": ["body", "luster"],             "C": ["body_luster"]},
scripts/vision_client.py:43:    "舌面": "这是一张舌面照片，请精确观察并只输出JSON：舌质颜色、舌苔(颜色/厚薄/润燥/腻腐/剥落)、舌体(胖瘦/齿痕/裂纹/点刺)、舌质润燥(键名固定为\"舌质润燥\"，值只填一个词：润泽/偏干/干燥/干裂)。注意区分舌面中央的浅沟是生理性正中沟还是深宽病理裂纹。不判舌神/荣枯（照片光线干扰、静态不可判）。",
tests/test_record.py:175:    """方案 A：body_luster 的形状 A 路径为"舌质润燥"（与 vision prompt
tests/test_record.py:179:        "doubao_vision_analysis": {"舌诊": {"舌质润燥": "润泽"}},
tests/test_scoring.py:144:    """方案 A：body_luster（舌质润燥，原"舌质荣枯"）已从 DIMENSION_RULES
templates/multi_dim_record_template.json:17:      "舌质润燥": "",
All consistent — TONGUE_BODY_LUSTER_MAP fully removed, no stale references except docs (review docs, fine) and tests referencing in comments.

  I have all evidence. Compose the final report in Chinese, sections ①-④ + conclusion.

• # 轮次 2 独立审查报告

  复核基线：commit `ef2f40a` 工作区现状，`pytest` 198 passed、`ruff --select F,E722` All passed（已亲测复现）。以下全部为只读实测。

  ## ① 轮次 2 改动本身的隐患与边角

  **`_match_score` 平局新逻辑（src/scoring.py:260-270）——逻辑正确，有两个语义边角（非 bug，属 fail-loud 既定代价）**

  实测：`湿润偏滑→7`、`滑燥并见→8`、`苔润不燥→0`、`不滑反润→0`（被否定的"滑"正确让位）。但：
  - `苔干燥但仍润 → 8`、`润燥相济 → 8`。"润燥相济"是平衡/近正常表述，被判 8 分。平局取高分的 fail-loud 策略会把"润/燥并提"类文学化表述推高。词典序依赖已消除（同分平局结果与 dict 顺序无关），无不确定性 bug。
  - 平局比较只在**同长度**内发生；更长低分词仍赢更短高分词（如"不温"4 赢"温"0），符合预期。

  **`_NEGATION_RE` 移除"非"（src/scoring.py:202）——发现一个真回归方向**

  实测：`并非黄染 → jaundice=4`、`绝非浮肿 → edema=4`。"并非/绝非"是**真否定**，旧正则 `非(?!常)` 能接住"并非"，新正则接不住 → **漏报转误报（fail-open 方向）**。历史档案实测：grep 全部 daily 档案无任何"并非/绝非/非典型"用例，当前无实际损害，但 LLM 产出"并非X"是常见句式，这是移除"非"换来的敞口。commit message 只声明了"非典型"侧的取舍，未声明"并非"侧的失能。建议：把 `并非|绝非` 加回 `_NEGATION_RE`（1 个 alternation，可保留"非典型"不误伤）。

  **`_is_word_boundary`（src/confidence.py:75-82）——安全，无 IndexError**

  `len(upper) > len(value)` 前置短路，索引不可能越界。实测：`HIGH1/HIGH_2/HIGHEST/HIGH。/HIGH（高）/HIGH\tCONF/HIGH\x00 → None`（全部 fail-closed，方向安全）；`HIGH CONFIDENCE/HIGH-置信/HIGH置信度 → HIGH`。CJK 范围 `一–鿿`（U+4E00–U+9FFF）覆盖常用汉字，全角标点/扩展区汉字不收——方向同样是 fail-closed，无风险。唯一可记：tab/全角标点不算边界，与 docstring "空格/连字符/CJK" 一致，属文档内行为。

  **`_is_triggered` 宽松化（src/record.py:209-213）——无副作用**

  实测全谱：`True/1/1.0/'true'/'TRUE '/'Yes'/'1' → True`；`False/0/0.5/2/-1/'是'/'对'/'真'/[1]/None → False`。`1.0==1` 命中是合理附带行为；中文真值不触发属保守方向。与 validator 的"非布尔 triggered 报 error"（input_validator.py:157）双保险不冲突，docstring 已声明。

  **`_DOSAGE_RE` + 经方白名单（src/record.py:147-154）——漏报可枚举，误报未发现**

  实测：`含桂枝10g→True`、`第3天10g→True`、`3克→True`、`每日3次→False`（无误报）。漏报：`10mg→False`（毫克单位）、`三钱→False`（中文数字+钱/两单位）、`四逆散→False`（白名单只有四逆汤）、`桂枝加厚朴杏子汤→False`（"加"字打断"桂枝汤"子串）。`柴胡桂枝汤→True`、`桂枝加葛根汤→True`（子串意外命中）。兜底扫描本质是 recall 有限的启发式，27 方名单对《经方探源》体系覆盖不足。递归风险：`_flatten_to_text` 深度受 json.loads 自身递归上限约束，性能可忽略。

  另注意（既有、非本轮）：`has_formula_content("无") → True`（非 dict 非空串即判有内容，record.py:171-172）——"无"是合法"无方剂"答复却会被判 safety_violation。属 fail-closed 过激，档案中未出现，可记不修。

  **`get_pattern_differentiation` 收窄（src/record.py:328）——零风险**

  普查全部 11 份 daily 档案 + 1 份备份：**无一份形状 A**，无一份有 `deepseek_diagnosis` 键。形状 A 唯一来源是模板，而模板 `templates/multi_dim_record_template.json:140` 用的正是"许家栋经方辨证"，键名对齐。收窄无历史键名遗漏。

  ## ② A–D 清单核验 + 第三类问题

  **A. 准确（两处小措辞偏差）**。实测重跑（纯函数调用，未写盘）：`load_week_records → 偏离度 6.0、claimed=HIGH/covered=6/consistent=true、无 safety_violation`。备份确在 `records/_backup/`。偏差：①计划文档写"非 .json 结尾"，实际文件名是 `2026-08-28_analysis_v1_旧格式.json`（**仍 .json 结尾**），真正起作用的是移出 daily 目录——glob 按目录隔离，不影响正确性；②`_backup` 目录本身不在 git 追踪内（records 未入 git），长期靠约定。

  **B. 准确，且不是假设——现行档案正在踩中**。实测：`records/daily/2026-07-15*analysis*.json` 命中两份，`sorted()[-1]` 静默选中 `2026-07-15_b_analysis.json`。同日双记录场景下"字典序最新"就是"碰巧选对"，周报无测试覆盖此选择逻辑（test_weekly_report.py 仅测 numeric date 容错）。

  **C. 三点全部属实**。① vision_client.py:122 `PROMPTS.get(part, PROMPTS["其他"])` 无警告（classify 在 :113 倒是有 warn——observe 反而没有，不对称）；② test_vision_client.py 15 个用例中有 URLError（:97）但**无 JSONDecodeError、无 socket.timeout 专项、无"舌质润燥"键名断言**（grep 全文件零命中）；③ 实测确认：6 个非舌面部位的 PROMPTS（vision_client.py:44-49）均无键名指令。

  **D. 准确**。validator 实测 rc=1 恰为 8 份；`红润→7` 复现（"红":7 子串命中，词表无"红润"）。

  **第三类问题（你没列到的）**：

  1. **混合形状档案静默零分（比 B 更隐蔽）**。`2026-08-02/08-09/08-14` 三份被探测为形状 C（顶层有 `tongue` 键），但内层是 B 路径或漂移键名：08-09/08-14 的 `tongue` 下是 `{"body":..., "coating":..., "sublingual":...}`（B 式嵌套），08-02 是 `body_shape`/`teeth_marks`（非规范键 `body_size`/`tooth_marks`）。形状 C 路径是恒等映射 → `get_observation` 全空 → **覆盖 0/6 → 周报舌诊 0.0 且无任何提示**。这与 A 的备份污染同属一类系统病：**档案选择/解析失败时静默降级而非报警**。它被"老档案不用在意"决策覆盖，但如果将来再出现混合形状新档案，周报会无声地错。形状 C 测试（test_record_shape_c.py）也无此混合形状用例。
  2. `_DIMENSION_INDICATORS` vs `DIMENSION_RULES` 差异现状（实测）：舌诊 18 指标中 **10 个无评分规则**（body_dynamics、body_luster[有意]、coating_color、coating_greasy、coating_peeling、coating_distribution、prickles、sublingual_color/thickness/petechiae），头面诊 3 个（lip_around、nose_color、nose_bleeding），目/耳/手/皮肤全覆盖。body_luster 的移除使缺口从 9 变 10——与轮次 3 计划一致，非回归。除周报外无其他 records/daily 消费方（validator 走显式路径，backup_to_oss.sh 排除 records/，retrieval 只 glob knowledge_base，draw_hand_diagram 不读档案）——**B 的爆炸半径确认仅限周报**。

  ## ③ B/C 优先级与处置建议

  建议合并为一个收尾轮次，按必修/可选/不动划分：

  **必修（约 0.5 天）**
  1. B：周报 glob 收口——优先 `{date}_analysis.json` 精确匹配 → 兜底排除 `*.bak*`/`*copy*`/`*tmp*`/`*_旧格式*` → 多份命中打 warning（generate_weekly_report.py:112-121）+ 2-3 个测试（含同日 `_b` 场景）。
  2. ①新发现：`_NEGATION_RE` 加回 `并非|绝非`（scoring.py:202，1 行 + 2 测试）。这是轮次 2 自己引入的 fail-open 敞口，不应留给轮次 3。
  3. C①：observe 无效 part-key 打 warning（对齐 classify 已有行为，3 行 + 1 测试）。

  **可选（可与轮次 3 合并）**
  4. C②：补 JSONDecodeError/timeout/“舌质润燥”键名断言 3 个测试（约 0.5 小时）。
  5. C③：6 部位 PROMPTS 键名声明——只在决定做"observe 输出自动转档案"时才必修，现状影响低。
  6. 混合形状检测：形状 C 维度节点取观测为空但节点非空 dict 时打 warning（record.py `_dimension_root` 附近，~10 行 + 1 测试）——防"静默零分"复发。
  7. `_DOSAGE_RE` 补 `毫克|mg|钱|两` 与中文数字，白名单按需扩充——recall 增强，非安全问题，可放轮次 3。

  **不动（维持原决策）**：D 两项；`has_formula_content("无")→True` 的 fail-closed 过激（安全方向、无实际档案触发）。

  ## ④ 测试有效性审查（本轮 8 个新测试）

  逐个核验，**无假覆盖**——8 个测试都真实断言了意图行为（逐一改动源码对应行可使其变红的路径都存在）：

  - `test_parse_level_strict_boundary`：正反例齐全（非法边界 + 合法边界回归）。
  - `test_has_formula_content_fallback_scan`：命中/不命中双侧。
  - `test_shape_a_body_luster_moisture_path`：新键解析 + 旧键拒绝，双向。
  - `test_shape_a_pattern_differentiation_missing_key_returns_empty`：缺键 {} + 有键取值，双向。
  - `test_shape_a_danger_flags_triggered`：布尔/字符串/数值/假值四类。
  - `test_body_luster_not_scored`：断言 `not in inds`（真验证移除，不是换个方式测旧行为）。
  - `test_tie_break_prefers_higher_score`：含否定交互用例（`苔润不燥→0`），质量最高。
  - `test_fei_is_not_negation_for_abnormal_prefix`：验证了取舍的**收益侧**，但**缺取舍的代价侧**——没有任何测试钉住"并非/绝非"现在的行为（当前会判阳性）。这正是 ① 中敞口没被测试或文档接住的原因。建议补 2 个用例随必修项 2 一起落地。

  另：`test_shape_a_danger_flags_triggered` 断言列表顺序 `["daiyang","skin_cold","flesh_wasted"]` 依赖 dict 插入序（Python ≥3.7 稳定），非脆弱点。

  ## 最终结论

  **轮次 2 可视为完成**——7 项改动本身实现正确、测试真实、文档与代码一致，198 测试与 ruff 复现通过。但有一个**本轮新引入的未声明取舍**：移除"非"使"并非/绝非"类真否定失效（fail-open 方向），应进收尾轮次必修。

  **遗留清单最终版**

  | # | 条目 | 定级 |
  |---|------|------|
  | 1 | `_NEGATION_RE` 补 `并非\|绝非`（轮次 2 自引入） | **必修** |
  | 2 | 周报 glob 收口 + 多份命中警告（B，`_b` 档案证明非假设） | **必修** |
  | 3 | observe 无效 part-key 警告（C①） | **必修**（极小） |
  | 4 | 混合形状档案静默零分的检测/警告（新发现） | 可选，建议做 |
  | 5 | test_vision_client 补 3 用例（C②） | 可选 |
  | 6 | 6 部位 PROMPTS 键名（C③） | 可不动，待"自动转档案"再修 |
  | 7 | `_DOSAGE_RE` 单位/白名单扩充 | 可选，并入轮次 3 |
  | 8 | D 两项（旧档 rc=1×8、`红润→7`） | 不动 |
  | 9 | `has_formula_content("无")→True` 过激 | 不动（fail-closed 方向） |

  建议：必修 1-3 + 可选 4-5 合并为"轮次 2.5 收尾"（约 0.5-1 天），其余归轮次 3。

To resume this session: kimi -r session_a96d08b6-61cb-4e0e-8f92-845290d8ecce
