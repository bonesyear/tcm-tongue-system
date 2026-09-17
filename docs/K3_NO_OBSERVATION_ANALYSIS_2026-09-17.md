kimi version 2.0.0
• Let me analyze the code. I need to read src/scoring.py, src/record.py, scripts/generate_weekly_report.py, and check records/daily data. Let me do this efficiently — read key files in parallel.2026-06-25
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
2026-08-02_img2.jpg
2026-08-02_img3.jpg
2026-08-02_img4.jpg
2026-08-02_img5.jpg
2026-08-02_img6.jpg
2026-08-02_vision_raw.json
2026-08-03
2026-08-03_guest_img1.jpg
2026-08-03_guest_vision_raw.json
2026-08-03_sm_img1.jpg
2026-08-03_sm_img2.jpg
2026-08-03_sm_img3.jpg
2026-08-03_sm_img4.jpg
2026-08-03_sm_vision_raw.json
2026-08-09_analysis.json
2026-08-09_full_img1.jpg
2026-08-09_full_img2.jpg
2026-08-09_full_img3.jpg
2026-08-09_full_img4.jpg
2026-08-09_full_img5.jpg
2026-08-09_full_img6.jpg
2026-08-09_full_img7.jpg
2026-08-09_full_vision_raw.json
2026-08-14_analysis.json
2026-08-14_fu_img1.jpg
2026-08-14_fu_img2.jpg
2026-08-14_fu_vision_raw.json
2026-08-28_analysis.json
2026-08-28_img1.jpg
2026-08-28_img2.jpg
2026-W25_report.json
2026-W32_report.json
2026-W35_report.json
Now let me examine the actual data: records/daily/2026-08-09_analysis.json (the scene in question) and 08-14, 08-28, plus existing weekly reports to see actual distribution. Let me check the 08-09 file and look at what tongue observations exist, and check existing weekly reports for the int/float issue and the summary sentence.

  Also check tests that assert on detail types (test that asserts mean type). Let me check tests/test files referencing dimension_deviation_detail.=== 2026-08-09 shape keys: ['patient', 'gender_age', 'date', 'session', 'confidence', 'photo_coverage', 'vision_model', 'tongue']
tongue node: {"body": "（示例舌象描述，合成数据）", "coating": "薄白(中根稍厚), 润偏滑, 稍腻, 无剥落", "sublingual": "正常(闪光灯下Qwen仍判正常)"}

=== 2026-08-14 shape keys: ['patient', 'gender_age', 'date', 'session', 'confidence', 'tongue', 'inquiry', 'pattern_update']
tongue node: {"body": "（示例舌象，合成数据）", "coating": "白薄(中根稍厚), 湿润, 无明显腻(腻退, 湿继续改善), 点刺舌尖边散在", "peeling": "（示例剥落描述，合成数据）", "sublingual": "正常(Qwen闪光灯下仍判正常, 用户无变化报告; 湿退→络脉显影减轻)"}

=== 2026-08-28 shape keys: ['date', 'session', 'patient', 'gender_age', 'confidence', 'photos', 'tongue', 'head_face']
tongue node: {"body_color": "淡红", "body_size": "胖大", "tooth_marks": "边缘轻度齿痕", "fissure": "仅中央浅窄正中沟（生理性，非病理裂纹）", "prickles": "舌尖及舌边散在红色点刺，剥落区内亦见红点", "coating_color": "白", "coating_thickness": "中央及根部偏厚，边尖较薄", "coating_moisture": "湿润偏滑", "coating_greasy": "稍腻", "coating_peeling": "（示例剥落描述，合成数据）", "sublingual_color": "正常（浅蓝紫细条）", "sublingual_thickness": "正常（小于2mm）", "sublingual_varicosity": "正常（平直不迂曲）"}

=== 2026-08-02 shape keys: ['patient', 'gender_age', 'date', 'session', 'confidence', 'photo_coverage', 'formula_with_dosage', 'face']
tongue node: {"body_color": "（示例舌色，合成数据）", "body_shape": "偏胖", "teeth_marks": "（示例齿痕，合成数据）", "coating_color": "白带淡黄 (四模型一致)", "coating_thickness": "薄~中 (根部稍厚)", "coating_moisture": "润", "coating_greasy": "微腻", "coating_peeling": "无", "crack": "排除 — 生理性舌正中沟 (豆包2.0+K3+照片描述一致; 豆包2.1误判浅裂纹)", "sublingual_veins": "（示例舌下络脉，合成数据） (用户肉眼确认, 血瘀铁证; 自然光照豆包判正常但用户确认存在深紫; 闪光灯照豆包判深紫粗大蛇形与此吻合)"}

=== 2026-07-15 shape keys: 
['date', 'confidence', 'photo_coverage', 'dimensions_covered', 'dimensions_unchanged', 'photo_analysis', 'inquiry', 'trend_vs_0712']
tongue node: MISSING

=== 2026-07-10 shape keys: ['date', 'confidence', 'photo_coverage', 'dimensions_covered', 'dimensions_unchanged', 'inquiry_unchanged', 'photo_analysis', 'inquiry_new']
tongue node: MISSING

Interesting. 2026-08-09 is a shape C record with a free-text "tongue" node using keys body/coating/sublingual (B-style nested strings, but at top level so detected as shape C). The get_observation for shape C uses identity mapping: "body_color" path = ["body_color"], so digging root["body_color"] returns "" — hence all indicators empty. It prints the mixed-shape warning. Then score_indicators scores all 0. So extract_tongue_metrics returns all 0.0 — indistinguishable from "observed normal".

  Note: 08-09's tongue node has values as plain strings ("示例舌色欠红润, 胖大偏嫩...") under keys body/coating/sublingual. Shape C detection: top-level key "tongue" exists → shape C. Paths are identity, so nothing parses. Indeed the "混合形状" warning.

  Also 08-02: shape C with keys body_color (exists! "淡紫..."), body_shape (drift), teeth_marks (drift), coating_color, coating_thickness, coating_moisture, coating_greasy, coating_peeling, crack (drift), sublingual_veins (drift). So partial parse: body_color, coating_color, coating_thickness, coating_moisture, coating_greasy, coating_peeling parse; body_size, tooth_marks, fissure, prickles, sublingual_* missing.

  Key question ①: does score_indicators distinguish "no observation" from "observed normal 0"? Answer: NO. _match_score returns 0 for empty text and 0 for "淡红". score_indicators returns Dict[str, int] with all indicators always present, 0 for both cases. So cannot distinguish by score alone.

  But get_observation(dim) returns dict where missing indicators are "" (empty string placeholder) — record.py:299 "缺失指标以空串占位". So the "has observation" criterion: obs[indicator].strip() non-empty. That's reliable. Note the indicator key always exists in the dict (all indicators of the dimension are filled with "" placeholders), so "key existence" is NOT the criterion — non-empty text is.

  Minimal change path for item 1: In generate_weekly_report.py, the逐指标 trends at lines 560-584 call describe_trend with first_tm/last_tm scalars from extract_tongue_metrics. Options:

  Option A (no semantic change to extract_tongue_metrics): compute per-indicator "has observation" separately. Add a helper e.g. `_tongue_metric_has_obs(rec) -> Dict[str, bool]` using `rec.get_observation(TONGUE)` and TONGUE_RADAR_METRIC_KEYS mapping: has_obs = bool(obs[ind_key].strip()). Then in generate_weekly_report_data, pass per-metric n (0/1) into describe_trend via first_n/last_n? But describe_trend's n=0 path message says "无有效观测（未拍到或未解析到有分指标）" — works for per-indicator too if we call with first_n=0/1, last_n=0/1. But careful: describe_trend's improvement double-gate uses max too; if we pass first_n we must also pass first_max (has_detail requires all four). For scalar per-indicator, max = the value itself. So calling describe_trend(name, first_val, last_val, first_max=first_val, last_max=last_val, first_n=obs_flag_first, last_n=obs_flag_last) works: for n=0 cases outputs "无有效观测" message; otherwise behavior: the double gate for improvement with max=value, n=1 both — max_drop = delta, last_n <= first_n holds (1<=1), so same output as old path. Actually check: old path (no detail) returns "异常程度减轻" unconditionally for delta<0. New path with has_detail and both n=1: max_drop = first-last = abs(delta) ≥ 0.5 and last_n<=first_n → same message. Identical text. 

  But there's a subtlety: per-indicator "has observation" vs "has score". The dimension-level n counts indicators with score>0. At per-indicator level, an observation like "淡红" (normal, score 0) is a valid observation — n_obs=1 even though score 0. So the criterion for逐指标 should be "text non-empty" not "score>0". Good — that distinguishes正常0 from 无数据 exactly.

  However there's a subtle issue: a non-empty text that matches nothing (e.g. sublingual="正常(闪光灯下Qwen仍判正常)") also yields 0 and is a valid observation. Fine — it's observed normal.

  Risk of verbosity: for 08-09 scenario, all 9 radar metrics would print "本周无有效观测...不作趋势判定" in 舌质变化/舌苔变化/舌形变化/舌下络脉变化 — the trend_analysis would be a wall of "无有效观测". That's the "修了反而更差" risk. Mitigation: aggregate — if both ends have no observation for a metric, emit short "（无观测）" or collapse at the group level: if all metrics in a group lack observations, output one sentence for the group. Or use a short phrase like f"{name}本周无观测" instead of the long dimension-level sentence.

  Impact on extract_tongue_metrics semantics: Option A doesn't change it — radar chart (generate_radar_chart) and trend chart keep current behavior. But note radar chart also has a silent-zero issue: for 08-09, radar shows all axes at 0 looking normal. Radar chart consumes metrics.get(cat, 0) at line 372 — no NaN handling. That's a ③ item.

  Trend chart: already handles n=0 via NaN at dimension level (lines 440-453). But it uses dimension-level n; fine.

  weekly_comparison: lines 597-602 — it's a static placeholder "缺少上周周报数据", no silent-zero logic. OK.

  charts JSON metadata: chart_info only has path/type/title — no data values. Fine.

  summary max_dim (item 2): line 605 — max(last_dev.items()) — when all dims are 0.0 (e.g., week with only 08-09-like records), max picks first in dict order ("舌诊") and prints "当前偏离度最高的维度为「舌诊」（0.0 分）". Also next_week_suggestion branches on max_score<3.0 → the "维持现有套餐" suggestion, which is actually fine-ish, but the summary sentence is no-information. Fix: check last_detail — if all dims n==0 (or max_score==0 and all n==0), replace with "本周各维度均无有效观测" phrasing. Also if max_score==0.0 but some dims have observations (all normal), the sentence is still low-information but factually true; could suppress when max_score==0.

  Item 3: mean=0 int vs max=0.0 float. In compute_dimension_deviation_detail: "mean": score_dimension(dim, obs). score() returns 0.0 (float) in the tongue branch... wait: score() returns `0.0` when not indicators or covered==0 — that's float. For non-tongue dims: `round(min(sum(...),10),1)` — round(int, 1) returns int! round(0, 1) → 0 (int). round(7,1) → 7 int. Yes! Python: round(0, 1) == 0 and type is int. So for non-tongue dims with all-zero indicators, sum = 0 (int), min(0,10)=0 int, round(0,1)=0 int. Hence mean=0 int while max=0.0 float (explicitly written as 0.0 float literal). Confirmed at src/scoring.py:402.

  Also tongue branch: covered==0 → return 0.0 float. So the int issue only affects non-tongue dims when sum is int... actually sum of ints is always int; min(int,10) int; round(int,1) → int in Python 3 (round with ndigits on int returns int). So mean for non-tongue dims is ALWAYS int (e.g., 7 not 7.0)! And tongue mean is float (round(total/covered,1) float division). So the type inconsistency is systematic, not just zero case: 头面诊 mean could be int 4 vs 舌诊 float 4.0. JSON serialization: json.dump writes int as "4", float as "4.0". Consumers doing strict JSON schema validation (type: number fine; type: integer fails for 4.0...) or test assertions like assert detail["mean"] == 0 pass anyway in Python (0 == 0.0). But isinstance checks or JSON text diff/snapshot tests would break. Check tests to see if any assert on this.

  Let me check test_weekly_report.py for relevant assertions, and check existing weekly report JSONs for the actual output.

  Also confirm: does anything else consume extract_tongue_metrics? tests and main() radar. Let me grep.

• 现在核实测试断言与已有周报 JSON 的实际输出。{
 "舌诊": {
  "first": {
   "mean": 5.3,
   "max": 7.0,
   "n": 6
  },
  "last": {
   "mean": 5.3,
   "max": 7.0,
   "n": 6
  }
 },
 "头面诊": {
  "first": {
   "mean": 0,
   "max": 0.0,
   "n": 0
  },
  "last": {
   "mean": 0,
   "max": 0.0,
   "n": 0
  }
 },
 "目诊": {
  "first": {
   "mean": 0,
   "max": 0.0,
   "n": 0
  },
  "last": {
   "mean": 0,
   "max": 0.0,
   "n": 0
  }
 },
 "耳诊": {
  "first": {
   "mean": 0,
   "max": 0.0,
   "n": 0
  },
  "last": {
   "mean": 0,
   "max": 0.0,
   "n": 0
  }
 },
 "手诊": {
  "first": {
   "mean": 0,
   "max": 0.0,
   "n": 0
  },
  "last": {
   "mean": 0,
   "max": 0.0,
   "n": 0
  }
 },
 "皮肤诊": {
  "first": {
   "mean": 0,
   "max": 0.0,
   "n": 0
  },
  "last": {
   "mean": 0,
   "max": 0.0,
   "n": 0
  }
 }
}
SUMMARY: 本周（2026-08-28 至 2026-08-28）共 1 条日分析记录。舌诊综合偏离度均值由 5.3 变化至 5.3（最重单项 7 分，共 6 项异常）；当前偏离度最高的维度为「舌诊」（5.3 分）。舌质颜色偏离度整体稳定（0.0 → 0.0） 头面诊偏离度本周无有效观测（未拍到或未解析到有分指标），不作趋势判定。

舌质变化: 舌质颜色偏离度整体稳定（0.0 → 0.0）
舌苔变化: 舌苔厚度整体稳定（0.0 → 0.0）；舌苔润燥整体稳定（7.0 → 7.0）；舌苔剥落整体稳定（6.0 → 6.0）


• Interesting — the W35 report shows "舌质颜色偏离度整体稳定（0.0 → 0.0）" even for 2026-08-28 which HAS body_color "淡红" → score... body_color map: "淡红" 0. Text contains "偏红"? "红" kw=7 — is it negated? "剥落区偏红" — "红" occurrence preceded by "偏" within window "淡红". Let me check: first "红" in "淡红" — "淡红" is exact? Text is not exact match (long string), so substring path: "淡红" (len 2) found at idx 2 — unnegated → best_kw "淡红"? But "红绛" no. "暗红" no. Longest unnegated keyword: "淡红" len2 vs "红" len1 → "淡红" wins → 0. So 舌质颜色 = 0.0, genuinely "observed normal" here. But for 08-09 scenario it's unobserved. Both print "整体稳定（0.0 → 0.0）".

  Also note 舌苔厚度 in W35: "整体稳定（0.0 → 0.0）" but 08-28 coating_thickness="中央及根部偏厚，边尖较薄" — map: "白厚"7/"黄厚"7/"厚腻"8 — "偏厚" contains "厚"? Keywords: 薄白/薄黄/无苔/白厚/黄厚/厚腻/焦黑. "厚" alone is not a keyword. So 0. Hmm, that's a scoring coverage gap but not in scope.

  Wait, but the mean=5.3 with n=6 for 08-28 — from indicators: coating_moisture "湿润偏滑"→滑7, coating_greasy "稍腻"→3, coating_peeling→6 or 7 （地图舌7), prickles→5, body_size 胖大→7, tooth_marks 轻度→4. n=6 positives. OK.

  Now for 08-09: shape C mixed — all indicators "" → all scores 0, n=0 at dimension level (fixed in round 4), but per-metric tongue_metrics all 0.0 → trend says "舌质颜色偏离度整体稳定（0.0 → 0.0）". Confirmed.

  Let me quickly verify the actual behavior with a dry run simulating a week of 08-09 + 08-14 (both shape C mixed). Actually 08-14 also shape C with body/coating/peeling/sublingual nested strings → all empty too. And 08-02 partially parses.

  Let me run a quick check on what extract_tongue_metrics gives for each record and whether get_observation non-empty criterion works.=== 2026-08-09 shape C
  non-empty indicators: []
  radar metrics: {}
  tongue detail: {'mean': 0.0, 'max': 0.0, 'n': 0}
=== 2026-08-14 shape C
  non-empty indicators: []
  radar metrics: {}
  tongue detail: {'mean': 0.0, 'max': 0.0, 'n': 0}
=== 2026-08-02 shape 
C
  non-empty indicators: ['body_color', 'coating_color', 'coating_thickness', 'coating_moisture', 'coating_greasy', 'coating_peeling']
  radar metrics: {}
  tongue detail: {'mean': 4.0, 'max': 5.0, 'n': 2}
=== 2026-08-28 shape C

  non-empty indicators: ['body_color', 'body_size', 'tooth_marks', 'fissure', 'prickles', 'coating_color', 'coating_thickness', 'coating_moisture', 'coating_greasy', 'coating_peeling', 'sublingual_color', 'sublingual_thickness', 'sublingual_varicosity']
  radar metrics: {'舌苔润燥': 7.0, '齿痕': 4.0, '舌体胖瘦': 7.0, '舌苔剥落': 6.0}

  tongue detail: {'mean': 5.3, 'max': 7.0, 'n': 6}
=== 2026-06-25 shape B
  non-empty indicators: ['body_color', 'body_luster', 'body_size', 'petechiae', 'tooth_marks', 'fissure', 'prickles', 'coating_color', 'coating_thickness', 'coating_moisture', 'coating_greasy', 'coating_peeling', 'coating_distribution', 'sublingual_color', 'sublingual_thickness', 'sublingual_varicosity', 'sublingual_petechiae']
  radar metrics: 
{'舌体胖瘦': 7.0, '舌苔剥落': 7.0}
  tongue detail: {'mean': 6.3, 'max': 7.0, 'n': 3}
=== 2026-07-15 shape B

  non-empty indicators: []
  radar metrics: {}
  tongue detail: {'mean': 0.0, 'max': 0.0, 'n': 0}
Excellent — this confirms everything:

  1. 08-09/08-14 (shape C mixed): all obs empty → radar metrics all 0.0 → 逐指标趋势 prints "整体稳定（0.0 → 0.0）" — misleading. Note: 08-09's actual tongue text describes 胖大/齿痕/点刺/稍腻 — real abnormalities invisible in weekly per-metric trends. (Though dimension-level now says 无有效观测.)

  2. Interesting: 08-02 partial — radar metrics all 0.0! Even though body_color="淡紫..." （紫暗 9? "淡紫" not in map; "紫暗" not substring... text "淡紫 （用户确认...)" — kw "紫暗" not in text; "淡白"? no. So 0), coating_thickness "薄~中 （根部稍厚）" — no kw hit → 0. So 08-02 radar shows all-zero despite real observations （明显齿痕 etc. unparsed due to key drift teeth_marks). Also a misleading case but caused by key drift + keyword gaps.

  3. 07-15 shape B but no tongue observations at all (photo_analysis shape, "tongue node MISSING") → n=0, radar all 0.0.

  Data distribution in records/daily: weeks containing 07-10/07-15/08-09/08-14 have unobserved tongues. E.g., week of 08-09 target (08-03..08-09): only 08-09 record → 逐指标趋势 all "整体稳定（0.0 → 0.0）" while 08-09 actually has notable findings. Confirmed real-world impact.

  Also note 08-02 vs 08-09 week? They're in different weeks.

  Now item 3 confirmed: W35 JSON shows mean:0 (int) vs max:0.0 (float) for non-tongue dims. Root cause: src/scoring.py:402 round(min(sum(...),10),1) — sum of ints is int, round(int,1) is int. Tests assert `detail["舌诊"] == {"mean": 5.5, ...}` — dict equality, 0 == 0.0 in Python so tests pass either way. JSON consumers: json.dump writes 0 vs 0.0 — matters for strict schema (e.g., TS consumer typed number — fine; integer-vs-number distinction in some validators), or snapshot/diff of JSON text. Low severity, trivial fix: wrap float() in score() or in detail builder.

  Also check: does describe_trend's f"{first_val:.1f}" handle int fine — yes.

  Item 2 confirmed: when all dims n=0 (e.g. week with only 07-15-type or 08-09-type records), summary: max(last_dev.items()) → all 0.0 → max picks first key 舌诊 → "当前偏离度最高的维度为「舌诊」（0.0 分）" and next_week_suggestion goes to max_score<3.0 branch → "本周各维度偏离度总体较低，建议维持现有..." — that's actually misleading too ("偏离度总体较低" when really "无数据"). Worth mentioning: item 2 fix should also touch the suggestion branch.

  Wait — but summary also includes tongue_phrase which for n=0 both ends says "舌诊本周无有效观测...". So summary would read "...舌诊本周无有效观测...；当前偏离度最高的维度为「舌诊」（0.0 分）。" — contradictory! Good point for item 2 severity.

  Now item ③ other silent spots:

  a) Radar chart (generate_radar_chart, lines 371-380): `metrics.get(cat, 0)` — no n awareness; unobserved day draws all-zero polygon looking "perfectly normal". For 08-09 week, radar draws a dot at center. No "无观测" annotation (trend chart has one at line 450-453, radar doesn't). Silent position confirmed.

  b) Trend chart: dimension level handled (NaN). But per-metric tongue trends aren't in trend chart (it's dimension-level only). OK.

  c) summary's 舌质变化 sentence: for week first=08-09 (unobserved) last=08-28 (observed normal 0): "舌质颜色偏离度整体稳定（0.0 → 0.0）" — mixes unobserved→observed.

  d) next_week_suggestion max_score<3.0 branch as noted (line 637).

  e) charts JSON metadata: only path/type/title, no data — fine. But chart files themselves: radar for no-data week. Also `extract_tongue_metrics` used in main() Step 2 radar.

  f) weekly_comparison: static placeholder, no silent zero logic — but worth noting it's currently non-functional ("缺少上周周报数据") not a silent-zero issue.

  g) Also tongue_phrase uses first/last detail only — for a single-record week (first==last==08-28), fine.

  h) `describe_trend` stable branch: even with detail provided, "整体稳定（0.0 → 0.0）" when both n>0 but both vals 0 — that's genuinely "observed normal, stable" — fine at dimension level since n>0 means at least one positive score... wait, n counts positive-score indicators. At dimension level, if observations exist but all normal (score 0), n=0! Hmm — critical subtlety: dimension-level n = number of indicators with score>0. So a fully-observed all-normal tongue (e.g., 淡红/薄白/无齿痕） → n=0 → prints "无有效观测（未拍到或未解析到有分指标）". That's a false "no observation"! The n semantics conflate "无异常" with "无观测" at dimension level too! Wait — the round-4 message says "未拍到或未解析到有分指标" — they deliberately worded it as "无有效观测（未拍到或未解析到有分指标）". Hmm, but a真正常 fully observed tongue would also trigger it. Is that a real scenario? For this patient always some abnormality. But semantically n=0 ≠ 无观测； n=0 = 无阳性指标. The wording "无有效观测" is inaccurate for the all-normal case. This is a latent flaw of the round-4 fix itself, and directly relevant to item 1's solution: at per-indicator level we should use text-nonempty as the criterion (not score>0), which is strictly better. And we could note this for the dimension level too: a better n would be "number of indicators with non-empty observation text". But changing dimension-level n would alter round-4 behavior/tests — flag as consideration.

  Actually wait, check compute_dimension_deviation_detail docstring line 250: "n：有分（>0）指标数，即异常负荷；n=0 表示'无有效观测'（没拍到/解析不到与真正常在旧口径下同写 0.0，靠 n 区分）". They acknowledge n=0 includes真正常 case. The trend message "无有效观测" is thus semantically wrong for all-normal observations. Worth mentioning in ③ as a related silent/semantic issue.

  Now for the per-indicator solution:

  Minimal change (Option A, recommended): in generate_weekly_report.py:
  - Add helper `_tongue_observation_flags(rec: DailyRecord) -> Dict[str, bool]` mapping radar metric name → bool(obs[key].strip()), using TONGUE_RADAR_METRIC_KEYS. ~6 lines, near extract_tongue_metrics (line 197-219).
  - In generate_weekly_report_data (lines 543-584): compute first_flags/last_flags; wrap the describe_trend calls for tongue metrics via a local `_metric_trend(name, metric_key)` that passes first_n=flag as int, last_n, first_max=first_val, last_max=last_val. describe_trend unchanged! Its n=0 branch (line 296-300) produces "本周无有效观测...不作趋势判定" and "仅一端有有效观测" messages. And when both flags=1, double-gate path yields identical text to the old scalar path (verified logic: delta<-0.5, max_drop=delta≥0.5, last_n(1)<=first_n(1) → same "异常程度减轻" message).

  One caveat: describe_trend's n=0 message says "未拍到或未解析到有分指标" — at per-metric level should say "未观测到该指标" — maybe adjust wording via a small param or accept. Also verbosity risk: for a week like 08-03..08-09 with only 08-09 record (first==last, all flags False), trend_analysis 舌质/舌苔/舌形/舌下 would each contain long "无有效观测" sentences — 9 metrics → 7 describe_trend calls → repetitive. Mitigation: short-circuit at group level: if all metrics in 舌质/舌苔/舌形/舌下 groups lack observations at both ends, emit one compact sentence per group, e.g. "舌苔变化：本周无有效观测（厚度/润燥/剥落均未解析到）". Or simpler: in _metric_trend, when both ends n=0, return f"{name}本周无观测" (short). That's a smaller deviation from describe_trend. 

  Impact on extract_tongue_metrics semantics: Option A doesn't change it — radar chart and its tests unaffected. The radar chart's silent zero remains (③ item); optionally fix radar separately by passing flags and skipping/annotating no-observation days — but that changes chart rendering; recommend as optional P2.

  Alternative Option B (change extract_tongue_metrics to return Optional[float] / NaN for unobserved): would break test_extract_tongue_metrics_non_zero? Only if that fixture has unobserved metrics — check real_raw fixture. And radar chart metrics.get(cat, 0) with None → matplotlib error. More invasive; not recommended.

  Let me check the conftest real_raw fixture quickly to know if indicators are all observed there. Also check test at line 34-35. Also confirm test file for summary-related assertions to gauge what a fix to item 2 might break. Let me look at tests briefly.I have enough. Let me also quickly verify the claim about "score_indicators returns same result for no-obs vs normal-0" — yes, confirmed by reading _match_score (line 321-322: empty text → 0; "淡红" → 0). And get_observation fills "" placeholders (record.py:295-309), so keys always exist — criterion must be text non-empty, not key presence.

  One more check for ③: the dimension-level n semantics — n counts score>0 indicators, so a fully observed all-normal record also yields n=0 → "无有效观测" message is wrong for that case. Real data: is there such a record? 08-09 would be all-normal IF it parsed （淡红/薄白/无裂纹/齿痕轻微→轻度4 actually positive...). Well, semantically the issue exists regardless.

  Also verify the W32 report (week containing 08-02?) to see summary with max_dim issue. 2026-W32 report — check summary quickly. Also check what happens for a hypothetical all-n=0 week. W32: 08-02 week. Let me check its summary to see if item 2 manifested. Quick check.=== 2026-W25
SUMMARY: 本周（2026-06-25 至 2026-06-25）共 1 条日分析记录。舌诊综合偏离度由 2.1 变化至 2.1；当前偏离度最高的维度为「头面诊」（5.0 分）。舌质颜色偏离度整体稳定（5.0 → 5.0） 头面诊偏离度整体稳定（5.0 → 5.0）。
SUGGESTION: 头面诊偏离度最高，建议补充目部特写以排除早期巩膜黄染，同时关注面色寒热、唇润燥及鼻翼煽动变化。

=== 2026-W32
SUMMARY: 本周（2026-08-09 至 2026-08-09）共 1 条日分析记录。舌诊本周无有效观测（未拍到或未解析到有分指标），偏离度不予计值；当前偏离度最高的维度为「舌诊」（0.0 分）。舌质颜色偏离度整体稳定（0.0 → 0.0） 头面诊偏离度本周无有效观测（未拍到或未解析到有分指标），不作趋势判定。⚠️ 安全边界警示：1 条记录在 LOW 置信度下输出了方剂（2026-08-09），详见 confidence_checks。
SUGGESTION: 本周各维度偏离度总体较低，建议维持现有六维拍照套餐（舌+头面+目+耳+手+皮肤），保持规律记录即可。

W32 confirms item 2 exactly: "舌诊本周无有效观测…；当前偏离度最高的维度为「舌诊」（0.0 分）" — self-contradictory, and the suggestion says "本周各维度偏离度总体较低" when actually there's no data. Also W32's "舌质颜色偏离度整体稳定（0.0 → 0.0）" is exactly item 1 in the wild (08-09 record).

  I now have all evidence. Write the final answer, sections ①~④ + summary + effort. Keep it in Chinese, with file:line citations.

• 全部核实完毕（含实测数据验证）。以下为分析正文。

  ---

  ## ① 三项的真实影响与严重性

  **第 1 项：真实误导，已在历史周报中实际发生，严重性最高。**

  核实结论：`score_indicators`（src/scoring.py:365-374）对"无观测"与"有观测但正常"返回**完全相同**的结果——`_match_score` 对空文本在 src/scoring.py:321-322 直接 `return 0`，而"淡红"（`TONGUE_BODY_COLOR_MAP` src/scoring.py:46）、"薄白"（:59）也映射 0。逐指标层靠分值**无法**区分两者，技术疑点成立。

  真实场景（实测 `records/daily`）：

  - `2026-08-09_analysis.json` 是混合形状档案：顶层有 `tongue` 键被判为形状 C，但内部是 B 式嵌套（`body`/`coating`/`sublingual` 整段文本），按恒等映射（src/record.py:50-67 的 C 路径）解析后 **18 个规范指标全部为空串**。`extract_tongue_metrics`（scripts/generate_weekly_report.py:197-219）因此输出 9 轴全 0.0。而原文实际记录了"胖大偏嫩、齿痕轻微、舌尖点刺、稍腻"等真实异常——周报逐指标趋势却写"整体稳定（0.0 → 0.0）"。
  - 这不是假想场景：`records/weekly/2026-W32_report.json` 的 summary 里已经躺着这句话——`舌质颜色偏离度整体稳定（0.0 → 0.0）`（同一摘要里维度级已正确写"舌诊本周无有效观测"，逐指标级却写"稳定"，自相矛盾）。
  - 同类档案还有 `2026-08-14`（同混合形状，全空）、`2026-07-10`/`2026-07-15`（形状 B 但无 tongue 观测节点，全空）、`2026-08-02`（键名漂移 `teeth_marks`/`body_shape`/`crack`/`sublingual_veins`，18 项中只解析到 6 项，且 9 个雷达轴全 0.0——明明有"明显齿痕、中度血瘀"的确认记录）。records/daily 共 9 份 analysis，其中 5 份存在逐指标级全零或大幅欠解析，**该误导在真实数据分布中是常态而非边角**。

  **第 2 项：不止文字冗余，是自相矛盾 + 错误建议，中等严重性。**

  `records/weekly/2026-W32_report.json` 实测输出：`舌诊本周无有效观测…；当前偏离度最高的维度为「舌诊」（0.0 分）`——前后两句直接打架。根源在 scripts/generate_weekly_report.py:605 `max(last_dev.items())`：全 0.0 时 `max` 按字典序取第一个键（舌诊）。且 `max_score < 3.0` 分支（:637-641）进一步输出"本周各维度偏离度总体较低，建议维持现有…"——**把"无数据"叙述成"状况良好"**，这比 summary 那句冗余更有害。所以第 2 项修法应连带覆盖 next_week_suggestion 分支。

  **第 3 项：纯 JSON 序列化层面不一致，低严重性，但值得顺手修。**

  根因确认：非舌诊维度走 src/scoring.py:402 `round(min(sum(...), 10), 1)`——int 之和为 int，`round(int, 1)` 在 Python 3 中**返回 int**，所以非舌诊维度的 mean 恒为 int（不只是 0，有分时也是 `4` 而非 `4.0`），与 `max` 的 float 字面量（generate_weekly_report.py:267 `0.0`）和舌诊 mean（float 除法，scoring.py:399）不一致。`records/weekly/2026-W35_report.json` 实测：`"mean": 0, "max": 0.0` 同对象并列。

  影响面：Python 消费方不受影响（`0 == 0.0`，tests/test_weekly_report.py:277/338 的 dict 相等断言照常通过）；受影响的是严格 JSON Schema 校验（`type: number` 没事，要求一致类型的会报错）和 JSON 文本快照/diff。周报 JSON 目前无强类型消费方，故低危——但修复是一行的事（见④）。

  ## ② 第 1 项技术方案（重点）

  **判据可行：`get_observation(dim)` 的文本非空判定是可靠的"有无观测"信号。** 注意不是"键是否存在"——`get_observation`（src/record.py:295-309）对缺失指标**以空串占位**，返回 dict 的键集合恒定，所以判据必须是 `obs[ind_key].strip()` 非空。实测验证：08-09/08-14/07-15 全部指标为空串（无观测）；08-28 的 `body_color="淡红"` 非空但得 0 分（有观测、正常）——该判据把两类场景干净分开，而分值做不到。

  **推荐方案（最小改动，不改 `extract_tongue_metrics` 语义）：**

  1. 在 `extract_tongue_metrics`（generate_weekly_report.py:197-219）旁新增约 8 行的辅助函数：
     ```python
     def extract_tongue_observation_flags(record) -> Dict[str, bool]:
         """雷达轴名 → 该轴规范指标是否有观测文本（区分'正常 0'与'无数据'）。"""
         rec = record if isinstance(record, DailyRecord) else DailyRecord(record)
         obs = rec.get_observation(VisionDimension.TONGUE)
         return {name: bool(obs.get(key, "").strip())
                 for name, key in TONGUE_RADAR_METRIC_KEYS.items()}
     ```
  2. 在 `generate_weekly_report_data`（:543-584）算出 `first_flags`/`last_flags`，把 7 处逐指标 `describe_trend` 调用包一层 `_metric_trend(name, axis)`，以 `first_n=int(flag)`、`last_n=int(flag)`、`first_max=first_val`、`last_max=last_val` 传入 `describe_trend`。

  **关键：describe_trend 本身一行都不用改。** 它的 n=0 分支（:296-300）直接产出"无有效观测/仅一端有有效观测，不作趋势判定"；两端都有观测（n=1）时，双门槛路径退化为与旧标量路径**逐字相同**的输出（max_drop = |delta| ≥ 0.5 且 1 ≤ 1 恒成立，:313-317 与 :326-328 文案一致）。行为只在"无观测"场景改变，零回归风险。

  **对 `extract_tongue_metrics` 返回语义的影响：无。** 雷达图（:371-380 `metrics.get(cat, 0)`）、趋势图（走 `compute_dimension_deviation_detail`，:432）、tests/test_weekly_report.py:34-43 的断言全部不受影响。这是本方案相对"改 `extract_tongue_metrics` 返回 `Optional[float]`"（备选 B）的决定性优势——备选 B 会让雷达图 `metrics.get(cat, 0)` 拿到 `None` 直接炸 matplotlib，且改动面扩散到测试，不建议。

  **防冗长设计（避免"修了反而更差"）：** 若直接复用维度级长句，08-09 这种周全无观测的档案会在 舌质/舌苔/舌形/舌下 四组里刷出 7 句"本周无有效观测（未拍到或未解析到有分指标），不作趋势判定"。建议在 `_metric_trend` 里对"两端均无观测"用短句 `f"{name}本周无观测"`，或在分组级别短路：组内全部轴两端无观测时，整组输出一句（如"舌形变化：本周无有效观测（齿痕/胖瘦/裂纹均未解析到）"）。后者信息更完整，推荐。

  ## ③ 同类静默位置核查（实际查过代码）

  1. **雷达图全零多边形（最重要，未列入 3 项）**：`generate_radar_chart`（generate_weekly_report.py:371-380）`values = [metrics.get(cat, 0) ...]` 无任何 n 感知。08-09 周会画一个"完美居中"的全零多边形，视觉上是"一切正常"的最强误导。趋势图维度级已在 :440-453 用 NaN 断线 + "无有效观测"文字标注处理过，**雷达图没有对应处理**。
  2. **next_week_suggestion 的 max_score<3.0 分支**（:637-641）：全 n=0 时落入"偏离度总体较低"文案（W32 实测已发生），与第 2 项同源。
  3. **round-4 修复自身的语义残留**：`compute_dimension_deviation_detail` 的 n 定义为"score>0 的指标数"（:264, :250-251 docstring 已自知"没拍到/解析不到**与真正常**同写 0.0"）。一份"完整观测但全部正常"（淡红/薄白/无齿痕）的记录同样 n=0，会触发"本周无有效观测"文案——把"正常"误述为"没观测"。现有示例数据未触发（每期都有阳性指标），但语义上埋着。彻底解法是把 n 改为"观测文本非空的指标数"（与②的判据同源），但那会改变 round-4 已签认的行为与测试，建议仅记录为已知口径，本轮不动。
  4. **weekly_comparison**（:597-602）：是纯静态占位符（"缺少上周周报数据"），不参与任何数值判定，无静默零问题。
  5. **charts JSON 元数据**（:826-838）：只有 path/type/title，不带数值，无问题。
  6. **趋势图数据点**：已在轮次 4 处理（NaN 断线 + 图底标注），无遗留。

  ## ④ 修法建议、优先级与工作量

  | 项 | 建议 | 优先级 | 工作量 |
  |---|---|---|---|
  | 1a. 逐指标 n=0 标注（②方案：flags + `_metric_trend` + 分组短路） | **现在修** | P0 | ~40 行新增 + 3-4 个测试，约 0.5 天 |
  | 3. mean 类型统一：`src/scoring.py:402` 改 `round(float(min(sum(...), 10)), 1)`（或在 :266 包 `float()`） | **顺手修**（改 scoring 层更根治，舌诊分支本已 float） | P1 | 1 行 + 补一个 `isinstance(mean, float)` 断言，<0.5 小时 |
  | 2. 全 n=0 时 summary/suggestion 改写：当 `all(d["n"]==0 for d in last_detail.values())` 时，summary 写"本周各维度均无有效观测，不作偏离度排名"，suggestion 改为"本周未解析到有效观测，请按规范形状补拍/重传" | **现在修**（连带 :637 分支，不单修一句话） | P1 | ~10 行 + 1 个测试，约 1-2 小时 |
  | ③-1. 雷达图无观测日处理（跳过该日多边形或图注"该日无有效观测"） | 建议修但可与 1a 同批；需向 `generate_radar_chart` 传 flags（改签名，加默认参数保兼容） | P2 | ~15 行 + 图像人工目检，约 2 小时 |
  | ③-3. 维度级 n 口径改"文本非空" | **不建议现在修**：会推翻轮次 4 已签认的 n 语义与 tests/test_weekly_report.py:317-323/354-360 的断言，收益（覆盖"全观测全正常"假想场景）在当前数据分布下为零 | 不修（记录为已知口径） | — |

  **"修了反而更差"的风险评估：** 唯一真实风险是 1a 的冗长——逐指标层 7 个 `describe_trend` 调用全刷"无有效观测"会让 trend_analysis 可读性反而下降。用②的分组短路/短句方案可把 7 句压到 ≤4 句且信息更具体（列出缺哪些轴），风险可控。除此之外三项修复均为"无观测时才改变输出"，正常路径逐字不变，无回归面。

  **推荐汇总**

  - **修**：1a（P0，逐指标观测标注，走 `get_observation` 文本非空判据 + `describe_trend` 既有 n 分支，不动 `extract_tongue_metrics`）、2（P1，全 n=0 时 summary + next_week_suggestion 联动改写）、3（P1，`float()` 一行）。
  - **可同批修**：③-1 雷达图无观测标注（P2）。
  - **不修**：③-3 维度级 n 口径变更（推翻已签认语义、当前无真实触发场景）；weekly_comparison 维持占位（无缺陷，只是功能未实现，属另案）。

To resume this session: kimi -r session_c5a50c9d-7668-457c-87a0-f9d0853ef1d3
