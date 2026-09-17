kimi version 2.0.0
• Read-only analysis task. Need to read src/scoring.py and docs/REPAIR_PLAN_2026-08-25.md. Let me read the key files.Now let me check dimensions.py _DIMENSION_INDICATORS to list the 17 tongue indicators, and glance at tests/test_scoring.py for regression risk. Also maybe knowledge_base for clinical scoring references. Let me read dimensions.py.Now find _DIMENSION_INDICATORS — it's in record.py probably. Let me grep.Now I have the full 18 tongue indicators (17 listed + body_luster; actually count: body_color, body_luster, body_size, petechiae, tooth_marks, fissure, prickles, body_dynamics, coating_color, coating_thickness, coating_moisture, coating_greasy, coating_peeling, coating_distribution, sublingual_color, sublingual_thickness, sublingual_varicosity, sublingual_petechiae = 18). User said 17 tongue indicators; maybe excluding body_luster. Fine.

  Also check test count and test_scoring to assess regression risk briefly. Also check weekly report usage of TONGUE_RADAR_METRIC_KEYS. Probably enough. Let me quickly check tests for _match_score edge cases to gauge regression risk for "take highest score on tie".I now have everything I need. Let me do a quick sanity audit of "tie → highest score" across all maps to answer ① rigorously.

  For each indicator's rules dict, check whether two same-length keywords can co-occur in one observation text where picking highest score would be wrong:

  - TONGUE_BODY_COLOR_MAP: 淡红0(2), 淡白7(2), 红7(1), 红绛8(2), 紫暗9(2), 暗红8(2), 青紫10(2). Same-length co-occurrence: "淡白" contains "白"? "白" not a key. 2-char keys: 淡红/淡白/红绛/紫暗/暗红/青紫. Could a text contain both "淡红" and "紫暗"? Rarely; if so highest wins = 紫暗9 vs 淡红0 — clinically the abnormal finding dominates; arguably correct under fail-loud principle. "暗红" contains "红"(1-char, but 1-char loses on length anyway). OK.
  - TONGUE_COATING_THICKNESS_MAP: 薄白0, 薄黄3, 无苔8, 白厚7, 黄厚7, 厚腻8, 焦黑10 — all 2-char. "薄白" + "黄厚" co-occur → highest 7. Also note: "白厚" contains "白"... not key. Fine. One subtlety: "薄黄" (3) vs "黄厚" (7): text "薄黄苔" — only 薄黄. OK.
  - TONGUE_MOISTURE_MAP: 润0, 滑7, 燥8, 干裂10. Ties at 1-char: 润/滑/燥. This is the bug case. Highest→'湿润偏滑'=滑7 ✓. But consider "苔润不燥"? 燥 negated; 润 unnegated → 润 0 ✓ (negation guard already filters). Consider "转润，前期干燥" — history in value violates Shape C convention anyway.
  - TOOTH_MARK_MAP: 无(1), 轻度(2), 中度(2), 重度(2). Tie among 轻度/中度/重度: co-occurrence unlikely; highest→重度10 if "由重度转轻度" — again history-in-value violation. Also "无"(1-char) with "轻度齿痕"→轻度 wins by length ✓.
  - PETECHIAE_MAP: 无(1), 散在(2), 密集(2). Co-occurrence "散在" + "密集" unlikely.
  - SUBLINGUAL_VARICOSITY_MAP: same shape as TOOTH_MARK.
  - FISSURE_MAP: 无, 浅裂(2), 深裂(2). "浅裂" vs "深裂" co-occurrence unlikely.
  - TONGUE_BODY_SIZE_MAP: 适中(2)0, 胖大(2)7, 瘦小(2)6, 肿胀(2)9 — all 2-char! Co-occurrence "胖大" + "肿胀"? possible ("舌体胖大肿胀") → highest 9. Plausible. "适中" + others unlikely.
  - TONGUE_BODY_LUSTER_MAP: 荣润(2)0, 少泽(2)5, 枯槁(2)8 — will be deleted in 方案A anyway.
  - FACE_LUSTER_MAP: 荣润0/晦暗5/枯槁8.
  - SCLERA_COLOR_MAP: 黄染7, 苍白5, 蓝巩膜8(3). "黄染"+"苍白" both 2-char co-occur? unlikely.
  - Inline dicts:
    - face_color: 萎黄5(2), 晦暗5(2), 黧黑5(2), 青灰5(2), 红如妆9(3). Ties all 5 except 红如妆 — safe.
    - face_edema: 明显浮肿4(4), 轻度浮肿2(4), 面目鲜泽4(4), 卧蚕4(2). "明显浮肿" vs "轻度浮肿" same length 4: text "轻度浮肿" — contains "浮肿"... but "明显浮肿" not substring. If text "浮肿明显"... neither 4-char. Hmm "轻度浮肿，已不明显" — "明显浮肿" not substring of that ("浮肿，已不明显" no). OK. But if both appear → highest 4 over 2 — fine direction.
    - nose_flare: 明显4(2), 轻度2(2). Text "鼻翼煽动明显" → 明显 ✓. "轻度煽动" → 轻度 ✓. If both "轻度转明显"... history violation again. But: consider "不明显" → negation guard kills 明显 ✓. What about "轻度不明显" — 轻度前 "不"? "轻度" preceded by... text "鼻翼煽动轻度不明显"? weird. OK.
    - eye jaundice: 黄染明显8(4), 黄染轻度4(4), 黄染4(2). "黄染轻度" contains "黄染" too but longest wins (4>2) ✓. Tie between 黄染明显/黄染轻度: both contain... a text "黄染轻度" only matches 黄染轻度+黄染. Highest tie only if both 4-char present. Fine.
    - eye edema: 卧蚕6(2), 浮肿明显4(4), 浮肿4(2), 微肿2(2). tie 浮肿/微肿 → if text "微肿" only contains 微肿. OK.
    - skin color: 黄如橘皮8(4), 橘皮8(2), 烟熏5(2), 萎黄3(2). OK.
    - hand palm_temp: 厥冷8(2), 不温4(2), 凉4(1), 温0(1). Tie 凉/温 at 1 char: text "手温" → 温0; "不温" exact match path if whole text; substring: "手足不温" → 不温(2) wins ✓. But text "手足凉而温"? weird. More realistic: "凉" vs "温" — "偏凉" fine. Highest-score on tie: if text contains both 凉 and 温 unnegated → 4 either way (both map to 4/0... wait 凉=4, 温=0; tie → highest = 4). E.g. "掌心温，指尖凉" → currently first-in-dict... order: 厥冷, 不温, 凉, 温 → 凉 first → 4. Same result. OK.
    - HEAD_FACE lip etc. fine.

  General principle: the maps are severity-graded vocabularies; ties between normal (0) and abnormal (>0) same-length words: picking highest implements fail-loud (over-report rather than under-report), which is the right clinical direction for a screening/trend system. And actual tie co-occurrence of two different severities nearly always indicates history-in-value (violating Shape C "current state only" convention) — so the real fix companion is data convention, not more code.

  Alternative designs:
  1. Tie → max score (my recommendation). One-line change: `if best_kw is None or len(kw) > len(best_kw) or (len(kw) == len(best_kw) and rules[kw] > rules[best_kw])`. Or cleaner: sort candidates. Risk: minimal, audited above. Direction: fail-loud.
  2. Explicit severity ordering per map (sort dict entries by score desc before matching): equivalent to #1 but changes data structure instead of algorithm — same result, more churn, and obscures that tie-break is an algorithmic policy. Worse.
  3. Keyword weights/priority: over-engineering; adds a parallel severity scale duplicating the score itself.
  4. More systematic fix: require value = single canonical enum (validator constrains coating_moisture to one of 润/滑/燥/干裂), turning substring matching into exact matching. This is the "real" fix but bigger: needs validator changes + prompt changes + rewrite discipline; and breaks free-text tolerance that Shape C relies on. Can be noted as long-term direction.

  Also note: alternative "tie → max" only changes behavior when two same-length keywords both have unnegated occurrences. Existing tests: check test_longest_match_avoids_ambiguity etc. — none test same-length tie, presumably. Regression risk low; 191 tests (user says 191; repair plan says 179 + shape C tests presumably 191 now). Fine.

  ② Which indicators to add. Photo-reliability principle: reliable from a static photo = color, thickness, coating coverage/peeling, greasy (somewhat — greasy vs moist can be light-sensitive), prickles （点刺 — visible red points, reliable-ish), sublingual color/thickness (requires lifting tongue photo; if photo exists, color reliable). body_dynamics （颤动/痿软/歪斜） — NOT judgeable from static photo → exclude (same principle as body_luster). coating_distribution （苔分布： 满布/偏布） — reliable from photo, but clinical scoring ambiguous; can include with low weight or exclude. The patient's core: coating_peeling （剥落） — definitely add.

  Draft maps:

  - coating_color: {"薄白"? no—that's thickness}. Coating color: 白0, 黄3, 灰6, 黑8? Typical: 白苔 normal 0, 黄苔 3 （热）, 灰黑 7-8. But wait — coating_thickness map already includes 薄白/薄黄/白厚/黄厚/焦黑 which mix color+thickness. Risk of double-counting color in both coating_color and coating_thickness. Should deduplicate: keep combined color+thickness in coating_thickness as-is (legacy), and coating_color map use pure color words: {"白": 0, "黄": 3, "灰": 6, "黑": 8} — but "白" single char appears in "薄白" → substring match in coating_color text... Actually scoring is per-indicator text: obs["coating_color"] is its own field value in structured input, so cross-field contamination only in pure-text input (known limitation). But within-field: value "黄" fine. Also "白厚" value in coating_color field would hit "白"=0 — acceptable. Draft: {"白": 0, "黄": 3, "灰黑": 8, "灰": 6, "黑": 7}. Careful: "灰黑"(2) beats "灰"/"黑" by length ✓.

  - coating_greasy （腻）: {"无": 0? hmm normal is 不腻}. Values likely "稍腻/腻/厚腻/腐苔". Draft: {"不腻": 0, "稍腻": 3, "腻": 5, "厚腻": 8, "腐": 7}. Note "厚腻" already in thickness map — if both fields populated from same observation, double count; but structured fields independent. Also "腻"(1) inside "厚腻"(2) → longest wins ✓. Tie "稍腻"(2) vs ... fine. Note: "不腻" contains "腻" — negation guard: "不" before 腻 in same clause → negated ✓ good, guard handles it.

  - coating_peeling （剥落/花剥苔/地图舌）: {"无": 0, "剥落": 6, "花剥": 6, "地图舌": 7, "镜面舌": 9, "无苔": 8?} — 无苔 already in thickness. Draft: {"无剥落": 0, "剥脱": 6, "剥落": 6, "花剥": 6, "地图": 7, "镜面": 9}. Normal baseline: value "无" or "完整" → 0 default anyway (no hit = 0), so map only needs abnormal words. Keep: {"剥落": 6, "剥脱": 6, "花剥": 6, "地图舌": 7, "镜面舌": 9}. Photo reliability: peeling is structurally visible → reliable ✓.

  - prickles （点刺）: {"无": 0, "点刺": 5, "芒刺": 6}. Reliable from photo (visible red raised points) though resolution-dependent — medium reliability; include with moderate score.

  - coating_thickness already exists. User's finding 2 lists coating_thickness as missing but it IS in DIMENSION_RULES (line 142). Actually user's list says "coating_color / coating_thickness / ... 均无评分规则" — wrong about coating_thickness; it has a rule. I should correct that (evidence: scoring.py:142). Good — "when you have evidence the user is wrong, say so".

  - sublingual_color: {"淡紫": 4? normal 淡紫...} clinically 舌下络脉颜色 normal = 淡紫； abnormal 紫暗/青紫 = 瘀. Draft: {"淡紫": 0, "紫暗": 6, "青紫": 8, "紫": 4}. Photo reliable if sublingual photo taken ✓.
  - sublingual_thickness （粗细）: {"细": 0? normal ≤2mm}, {"粗": 5, "怒张": 7}. Hmm overlaps varicosity. Draft: {"正常":0 implicit, "增粗": 5, "曲张": 7}? varicosity covers 迂曲. Keep simple: {"增粗": 5, "怒张": 7}.
  - sublingual_petechiae: reuse PETECHIAE_MAP {无0, 散在5, 密集9} ✓.
  - coating_distribution: {"满布": 0?} clinical: 苔偏布/少苔分布... I'd exclude or low: {"偏苔"?}. Simpler to exclude with reason (distribution's abnormality mostly captured by peeling/thickness; scoring semantics unclear). Or include {"满布":0, "偏布":3, "少苔":5}. I'd recommend exclude initially — low marginal value.
  - body_dynamics: exclude — static photo cannot judge 颤动/痿软/歪斜 (same principle as 方案A).
  - body_luster: already being removed by 方案A.

  Also impact on score() mean: adding indicators changes the tongue mean (more terms). Sparse mean only counts v>0, so adding maps only affects when abnormal present — normal records unaffected ✓. Radar chart: TONGUE_RADAR_METRIC_KEYS fixed 8 — adding indicators doesn't auto-add to radar; need decide whether to add 剥落 to radar (recommend yes: replace or extend; radar count change affects weekly report charts/templates).

  ③ Consistency with 方案A: same principle — "照片可靠性原则" decides inclusion per-indicator, not a global direction. 方案A removes body_luster (unreliable: 神/荣枯 needs dynamic observation); 发现2 adds statically-verifiable signs (peeling, greasy, color, prickles, sublingual). Both move scoring toward photo-verifiable indicators. body_dynamics excluded by same principle — that's the unifying demonstration.

  ④ Implementation points & tests:
  - scoring.py: _match_score tie-break line 266; add maps near line 66; DIMENSION_RULES entries 140-150; maybe TONGUE_RADAR_METRIC_KEYS + weekly report.
  - Tests: tie-break case "湿润偏滑"→7; "苔润"→0; "滑燥并见"→8; negated "不滑" etc.; new maps: 剥落/花剥/镜面； "稍腻"→3; "不腻"→0 (negation guard on 腻）; coating_color 灰黑 longest match; sublingual maps; score() mean with new indicators (sparse unaffected when normal); structured dict test; fixture update if normal-tongue fixture lacks new keys (score unchanged since no hit = 0; but test_normal_tongue fixture should add new keys with normal values to pin behavior).
  - Regression risk on 191 tests: tie-break changes behavior only for same-length dual-hits — audit shows no existing test constructs that; new maps only activate for previously-None indicators — but careful: pure-text scoring tests (test_tongue_score_positive_on_red_yellow etc. use text input) — adding new rules to TONGUE means text like "黄" hits coating_color... wait, new maps under TONGUE with text input: every indicator matched against whole text. E.g. test text "舌红苔黄厚" → coating_color map "黄":3 hits → adds 3 to sum, covered count +1 → mean changes! Existing tests using raw text with tongue dimension could break. Need to check which tests score TONGUE with text containing 黄/腻/剥 etc. That's a real regression vector — mention it. Mitigation: audit tests; or new maps... can't avoid; just run tests and update expectations (they'd be legitimately changed) — or restrict: note test_tongue_score_positive_on_red_yellow uses "舌红苔黄厚" style text. Let me not over-assert; flag it.

  Actually let me quickly check test contents to be precise.One notable: test_longest_match_avoids_ambiguity uses "淡红为底，局部偏红" — with a new coating_peeling map under TONGUE, this pure-text input would hit "花剥"(6) for coating_peeling → covered +1, but the test only asserts inds["body_color"]==0, so safe. test_tongue_score_positive_on_red_yellow: score(TONGUE, "舌红苔黄") > 0 — adding coating_color "黄":3 still >0 ✓. test_tongue_score_sparse_not_diluted: score(TONGUE, "青紫") == 10 — "青紫" only hits body_color (10); new maps: does "青紫" hit sublingual_color "青紫":8? If I add that map with "青紫", text input → covered=2, mean=(10+8)/2=9 ≠ 10 → THIS TEST BREAKS. Good catch — concrete regression example to cite. Mitigation: sublingual_color map avoid bare "青紫"? But clinically sublingual 青紫 is the key word. Options: accept and update test (structured input is recommended path anyway), or design map keywords with 络脉 prefix ("青紫"→"紫暗/瘀紫"?). Actually can note: either update test to dict input (test intent is sparse-undiluted, better expressed via dict), or choose sublingual keywords like "紫暗":6,"怒张":7 avoiding "青紫". I'll flag both.

  test_tongue_score_on_clean_keywords: "舌质红绛苔黄厚" — new coating_color "黄":3 → also hits; but assert is >0, and body_size assert on "舌体胖大" — "胖大" hits body_size only; new maps don't match. Fine.

  Also 191 tests — user said 191; plan says 179 after round 1 plus shape C tests presumably brought to 191. Just refer to "现有 191 个测试".

  Now compose the answer, sections ①~⑤, with file:line refs. Keep concise but complete.

  Workload estimate: 发现1 fix ~0.5h (1 line + tests); 发现2 map additions ~0.5 day incl. tests + radar decision; scheduling: insert into 轮次 2 (both are scoring-layer, same file, same test file; 发现1 is small; 发现2 needs decision on radar). Actually recommend: 发现1 → 轮次 2 new entry (#19); 发现2 → also 轮次 2 but as its own sub-item with user decision, or separate 轮次 2.5? Recommend both into 轮次 2 as scoring-layer items, since 轮次 2 is exactly "辨证层（confidence + scoring + record）". Adding to same round keeps single full-test run and single commit discipline. But round 2 is already large (#5/#8/#9/#10/#12 + 方案A 项2~11 + #16). Alternative: 发现1 into 轮次 2 (tiny, synergistic with 方案A scoring edits), 发现2 into a new 轮次 2b or 轮次 3 (scoring expansion) because it needs clinical map decisions and radar changes. Recommend that: 发现1 insert 轮次 2 as new 序； 发现2 separate round after 轮次 2.

  Wait — the repair plan says order should be 形状C → 轮次2. Shape C is already implemented per the plan's 端到端验证 section (2026-09-17, files rewritten, chain works). Actually the section says "档案重写为 C 后 → 评分链路通" — implies C implemented. So 轮次 2 is next anyway.

  Line refs:
  - TONGUE_MOISTURE_MAP: scoring.py:66-71
  - tie logic: scoring.py:260-267 (line 266)
  - DIMENSION_RULES[TONGUE]: scoring.py:140-150
  - TONGUE_RADAR_METRIC_KEYS: scoring.py:188-197
  - score() sparse mean: scoring.py:321-326
  - weekly radar: generate_weekly_report.py:141-162
  - _DIMENSION_INDICATORS tongue 18 indicators: record.py:47-66
  - tests: test_scoring.py:111-127 (normal fixture), :130-132 sparse
  - repair plan round 2: docs/REPAIR_PLAN_2026-08-25.md:39-51

  Note correction: coating_thickness HAS a rule (scoring.py:142) — user listed it as missing. Also "点刺" is prickles (record.py:54), missing from rules indeed.

  Count tongue indicators: 18 including body_luster; user said 17 (probably excluding body_luster being removed). Fine, note 18→方案A后17.

  Map drafts — refine:

  coating_color: {"白": 0, "黄": 3, "灰": 6, "灰黑": 8, "黑": 7}. Hmm "黑" alone 7 vs "焦黑" already 10 in thickness — duplication of 黑/焦黑. In structured input fields are independent so it's fine, but pure-text double count is known limitation. Keep draft simple: {"白": 0, "黄": 3, "灰": 6, "黑": 7, "灰黑": 8}.

  coating_greasy: {"不腻": 0? unnecessary—no-hit=0; but "不腻" contains "腻" → negation guard: "不" immediately before "腻" in same clause → negated ✓ so no need for explicit 不腻}. Draft: {"稍腻": 3, "腻": 5, "厚腻": 8, "腐苔": 7, "腐": 7}. "腐" 1-char might over-hit ("腐" in other contexts rare in this field). Keep {"腐苔": 7} only? Values in Shape C likely "稍腻"/"腻"/"厚腻". Draft: {"稍腻": 3, "腻": 5, "厚腻": 8, "腐苔": 7}. Tie risk: "稍腻"(2) vs nothing else 2-char except... "腐苔". fine. Note "厚腻" duplicates thickness map — acceptable (different indicator; structured input independent; but if Shape C writer puts "厚腻" in both fields → double count in mean; mention as data-convention note).

  coating_peeling: {"剥落": 6, "剥脱": 6, "花剥": 6, "地图舌": 7, "镜面": 9}. Note "无剥落" → negated ✓.

  prickles: {"点刺": 5, "芒刺": 6} ("无点刺" negated ✓).

  sublingual_color: {"淡紫": 0, "紫暗": 6, "瘀紫": 7} — avoid "青紫" to not break test_tongue_score_sparse_not_diluted (or update test). I'll propose {"淡紫": 0, "紫暗": 6, "青紫": 8} and note the test conflict explicitly with two resolutions.

  sublingual_thickness: {"增粗": 5, "怒张": 7}.
  sublingual_petechiae: reuse PETECHIAE_MAP.

  Exclude: body_dynamics (static photo can't judge 动态 — same principle as 方案A), coating_distribution (low marginal value / semantics overlap with peeling+thickness; can revisit), body_luster （方案A removes).

  Radar: TONGUE_RADAR_METRIC_KEYS currently 8 (scoring.py:188-197) — after 方案A removes 舌苔润燥？ Wait — 方案A removes body_luster (which is NOT in radar keys) and... wait, 方案A is about 舌质干燥/润泽 = body_luster field renamed to 舌质润燥. Radar keys include "舌苔润燥": coating_moisture — that stays. OK. Adding coating_peeling to radar → 9 axes, weekly report template/charts change. Recommend: add "舌苔剥落" to radar (patient's core observation); keep others out of radar to limit scope.

  ③ unifying principle: "评分层只收照片静态可判的客观形态指标；需动态观察/光线敏感的主观判断降级到辨证层". Both 方案A (remove luster/moisture-of-body) and 发现2 (add peeling/greasy/color/prickles/sublingual) follow it; body_dynamics exclusion proves same rule applied symmetrically.

  ④ Test points listed. Regression: text-input tests may change (sparse test with 青紫 + sublingual 青紫）, fixture test_normal_tongue fixture (add new keys normal values), score mean changes when new abnormal indicators hit in existing fixtures — fixture 2026-06-25 test (test_weekly_report expects 5.5?) — K3 noted test_weekly_report.py:49-50 expects 5.5; adding maps could change if fixture text contains 腻/剥/黄. Flag: run and check.

  ⑤ Scheduling: 发现1 → 轮次 2 新增条目（编号续 #19，或插为评分层第 1 条 since it's P0 clinical underestimate); actually order within round: 发现1 small & independent → put early. 发现2 → separate round （轮次 3 "评分覆盖扩展") after 轮次 2, because (a) needs user sign-off on maps/clinical weights, (b) touches radar/周报 beyond scoring.py, (c) 轮次 2 already 13+ items. Also note dependency: 发现2 after 方案A lands (same file region, avoid conflicts).

  Workload: 发现1: ~0.5–1h (code 1-2 lines + 4-6 tests). 发现2: ~1 day (7 maps draft→review, scoring.py edits, radar keys + weekly report check, 15-20 tests, fixture updates, full regression). Total ~1–1.5 day.

  Write the answer in Chinese, structured ①~⑤ + summary.

• # 评估与建议

  先纠正一处事实：发现 2 的清单里 `coating_thickness` **已有**评分规则（`src/scoring.py:142` 挂在 `TONGUE_COATING_THICKNESS_MAP`），其余 8 个确实无规则。另 `_DIMENSION_INDICATORS` 舌部实为 18 个指标（`src/record.py:47-66`），方案 A 移除 `body_luster` 后剩 17。

  ## ① 发现 1 的修法：推荐"同长度时取最高分"

  **推荐方案：`_match_score` 的平局规则改为"同长度取分值最高者"**（`src/scoring.py:260-267`，一行改动）：

  ```python
  if best_kw is None or len(kw) > len(best_kw) \
          or (len(kw) == len(best_kw) and rules[kw] > rules[best_kw]):
  ```

  **理由**：

  - 我对全部 13 个 map 做了平局共现审计。同长度关键词同时出现未被否定出现的场景只有两类：
    1. **正常词与异常词并存**（本案例："湿润偏滑" 中 润0/滑7）→ 取高分方向正确，是筛查系统该有的 **fail-loud**（宁可高估不漏估）。评分口径本来就是"偏离度"，漏报湿盛比误报 7 分代价大。
    2. **两个不同程度异常词并存**（如"由重度转轻度"）→ 这本身就是形状 C "值只写当前状态、历史对比放 `*_note`"约定禁止的写法（REPAIR_PLAN ③，docs/REPAIR_PLAN_2026-08-25.md:189、202）。取高分只是把一个数据违规的后果导向保守方向，不产生新的临床错误。
  - 其他 map 无新增误判：`TOOTH_MARK_MAP` 轻/中/重度虽同为 2 字，但互斥共现只会出现在历史夹注里（同上）；`nose_flare` 的 明显4/轻度2 同长度，"轻度"句中不含"明显"子串，互不干扰；`face_edema` 明显浮肿4/轻度浮肿2 同理。审计未发现"同长度、可自然共现、且取高分方向错误"的反例。

  **备选方案对比**：

  | 方案 | 评价 |
  |---|---|
  | 按 map 显式严重度排序 | 与"取最高分"结果完全等价（分值本身就是严重度），但把算法策略藏进数据排版，换个维护者重排 dict 就静默失效。劣于改算法 |
  | 关键词加权重/优先级 | 引入与分值平行的第二套严重度标尺，过度设计 |
  | **更系统的修法**（长期方向）：validator 约束 `coating_moisture` 等字段为枚举值（润/滑/燥/干裂），子串匹配退化为精确匹配 | 根治，但与形状 C 容忍自然语言短语的设计冲突，需改 validator+prompt+写作纪律，成本不成比例。可作为未来选项记录，不建议现在做 |

  ## ② 发现 2：应补，按"照片静态可判"分批

  **建议纳入**（分值口径 0=正常基线）：

  | 指标 | map 草稿 | 依据 |
  |---|---|---|
  | `coating_peeling` | `{"剥落": 6, "剥脱": 6, "花剥": 6, "地图舌": 7, "镜面": 9}`（"无剥落"由否定守卫归零） | **最高优先**——核心观察点；剥落是结构性形态，静态照片完全可判 |
  | `coating_greasy` | `{"稍腻": 3, "腻": 5, "厚腻": 8, "腐苔": 7}` | 腻苔是苔质附着形态，照片可判性较好；"不腻"中"腻"被前置否定守卫拦截（`scoring.py:215-227`），无需显式 0 词条 |
  | `coating_color` | `{"白": 0, "黄": 3, "灰": 6, "黑": 7, "灰黑": 8}` | 颜色是照片最可靠的维度（"灰黑"靠最长匹配压过"灰"）；与 thickness map 的 薄黄/黄厚/焦黑 有语义重叠，结构化输入下字段独立不双计，纯文本双计是既有已注释局限 |
  | `prickles` | `{"点刺": 5, "芒刺": 6}` | 点刺为凸起红点，清晰度够时照片可判；分辨率敏感，故分值保守 |
  | `sublingual_color` | `{"淡紫": 0, "紫暗": 6, "青紫": 8}` | 前提是拍了舌下照；颜色可判 |
  | `sublingual_thickness` | `{"增粗": 5, "怒张": 7}` | 同上，粗细形态可判 |
  | `sublingual_petechiae` | 直接复用 `PETECHIAE_MAP`（`scoring.py:82-86`） | 零新增成本 |

  **仍应排除**：

  - `body_dynamics`（舌体动态：颤动/痿软/歪斜）——**静态照片不可判**，与方案 A 移除 `body_luster` 是同一原则，必须排除
  - `coating_distribution`（苔分布）——异常语义大多已被 peeling/thickness 覆盖，边际价值低，暂不进；后续若有真实判例再议
  - `body_luster`——方案 A 已定移除

  **附带决定**：是否把 `coating_peeling` 加进雷达图（`TONGUE_RADAR_METRIC_KEYS`，`scoring.py:188-197`；消费方 `generate_weekly_report.py:141-162`）。建议**加**——否则剥落只在维度均分里体现，趋势图仍看不到这个核心观察点。雷达从 8 轴变 9 轴需同步周报模板。

  ## ③ 与方案 A 不冲突：同一条原则的两个方向

  统一原则一句话：**评分层只收"静态照片可客观判读"的指标；需要动态观察或对光线/拍摄条件敏感的主观判断，降级到辨证层（LLM prompt 参考）**。

  - 方案 A 是该原则的**减法**：舌神/荣枯需动态观察，舌质润燥受光线干扰 → 移出评分
  - 发现 2 是该原则的**加法**：剥落/腻/苔色/点刺/舌下形态都是静态可判的形态学体征 → 补进评分
  - `body_dynamics` 的排除决定正好是同一原则在本议题内的对称应用，可作为写入文档的判例

  ## ④ 实现要点与测试要点

  **实现**（全部在 `src/scoring.py`，外加雷达一处）：

  1. `_match_score` 平局规则（`scoring.py:266`）——1~2 行
  2. 新增 6 个 map（插在各 map 区 `scoring.py:43-130`）+ `DIMENSION_RULES[TONGUE]` 挂 7 条（`scoring.py:140-150`）
  3. `TONGUE_RADAR_METRIC_KEYS` 加 `"舌苔剥落": "coating_peeling"`（`scoring.py:188-197`），周报模板 8 轴→9 轴

  **新增测试用例**（`tests/test_scoring.py`）：

  - 平局取高分：`"湿润偏滑"`→7；`"湿润"`→0；`"滑燥并见"`→8；`"苔润不燥"`→0（否定后平局不触发）
  - 剥落组：`"花剥"`→6、`"剥落斑"`→6、`"镜面舌"`→9、`"无剥落"`→0
  - 腻组：`"稍腻"`→3、`"不腻"`→0（守卫）、`"厚腻"`→8（最长匹配压过"腻"）
  - `coating_color`：`"灰黑"`→8 不降级为"灰"
  - 舌下三指标各一正一负
  - `score()` 均值含新指标的用例 + 稀疏记录不被稀释的回归

  **回归风险（现有 191 个测试）**：

  - **确定的冲突点**：`test_tongue_score_sparse_not_diluted`（`test_scoring.py:130-132`）用纯文本 `"青紫"` 断言 score==10。若 `sublingual_color` map 收 `"青紫": 8`，纯文本输入下两个指标同命中 → 均值变 9.0，测试红。两个解法：①把该测试改为结构化 dict 入参（本来就推荐结构化路径，测试意图"稀疏不稀释"用 dict 表达更准确）；②sublingual map 不收"青紫"只收"紫暗/瘀紫"。倾向 ①。
  - `test_normal_tongue_scores_zero` 的 fixture（`test_scoring.py:114-124`）应补新指标的正常值，把"正常舌象全 0"钉死在新规则上
  - 周报 fixture 期望分（K3 复核提到 `test_weekly_report.py:49-50` 期望 5.5）：若 fixture 文本含"腻/剥/黄"等词，新 map 命中会改均值——跑全量后逐个核对，方向正确则更新期望并在 commit 说明"评分口径扩展导致的历史期望变化"（与方案 A 项 10 同类）
  - 平局规则改动本身：审计现有测试无"同长度双命中"构造，预计零回归

  ## ⑤ 排期：发现 1 进轮次 2，发现 2 单列一轮

  - **发现 1 → 插入轮次 2**，作为评分层新增条目（续编号 #19）。理由：改动 1 行 + 少量测试，与轮次 2 同文件域（scoring.py），且与方案 A 项 3/4/5 编辑同一区域，同轮改完只需一次全量回归、一次 diff review。建议在轮次 2 内**排在方案 A 落地之前**（先修算法再动表结构，diff 更干净）。它本身就是计划"端到端验证发现"节已预记的处置（docs/REPAIR_PLAN_2026-08-25.md:222）。
  - **发现 2 → 单列"轮次 3：评分覆盖扩展"，排在轮次 2 之后**。理由：①涉及 7 个 map 的临床赋分，需你对分值草稿过目签字，不宜塞进已 13+ 项的轮次 2；②越出 scoring.py，牵涉雷达图与周报模板，文件域不同；③依赖方案 A 先落地（同区域编辑，避免冲突）；④它不改变既有口径的正确性，只扩展覆盖面，晚上一轮无风险累积。对应计划 223-226 行已标注"需用户决定"，本评估的 map 草稿即供该决策。

  ---

  ## 推荐方案汇总

  1. **发现 1**：`_match_score` 平局取最高分（fail-loud），一行改动，插入轮次 2
  2. **发现 2**：补 7 个指标的评分规则（剥落/腻/苔色/点刺/舌下颜色/粗细/瘀点），剥落进雷达图；排除 `body_dynamics`、`coating_distribution`；单列轮次 3
  3. **统一原则**：评分层只收静态照片可判指标——方案 A 做减法、发现 2 做加法，互不冲突
  4. 唯一确定的既有测试冲突是 `test_scoring.py:130` 的"青紫"稀疏测试，建议改结构化入参

  ## 工作量估计

  - 发现 1（含 4-6 个新测试）：约 **0.5–1 小时**
  - 发现 2（7 个 map + 雷达/周报 + 15-20 个测试 + fixture 核对 + 全量回归）：约 **1 个工作日**
  - 合计约 **1–1.5 个工作日**；map 分值草稿的临床审阅时间另计（取决于你逐条过目的速度）

To resume this session: kimi -r session_76ba7e11-0151-4961-bdf3-de33d454e8c3
