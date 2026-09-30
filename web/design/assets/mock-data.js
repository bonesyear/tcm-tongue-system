/* ============================================================
   Mock 数据 · 设计稿专用
   - 结构对齐真实记录形状 B（见 tests/fixtures/2026-06-25_analysis.json）
   - 分数为演示用手标值，非评分管线输出
   - 周报结构对齐 scripts/generate_weekly_report.py 的
     generate_weekly_report_data() 返回 dict
   ============================================================ */

/* 六维元数据（与 src/dimensions.py 一致） */
const DIMENSIONS = [
  { key: "tongue",    name: "舌诊",   sub: ["舌质", "舌苔", "舌下络脉"] },
  { key: "head_face", name: "头面诊", sub: ["面域", "唇域", "鼻域"] },
  { key: "eye",       name: "目诊",   sub: ["目赤", "巩膜黄染", "眼睑浮肿", "目眶黯黑"] },
  { key: "ear",       name: "耳诊",   sub: ["耳色", "耳轮"] },
  { key: "hand",      name: "手诊",   sub: ["手掌颜色", "甲床颜色", "甲床形态", "手掌瘀斑"] },
  { key: "skin",      name: "皮肤诊", sub: ["肤色", "甲错", "黄汗", "水肿", "干燥"] },
];

/* 分数等级工具：0 正常 / 1–3 轻 / 4–6 中 / 7–10 重（锁定口径） */
function sevClass(score) {
  if (score === null || score === undefined) return "sev-none";
  if (score === 0) return "sev-0";
  if (score <= 3) return "sev-1";
  if (score <= 6) return "sev-4";
  return "sev-7";
}
function sevLabel(score) {
  if (score === null || score === undefined) return "未覆盖";
  if (score === 0) return "正常";
  if (score <= 3) return "轻";
  if (score <= 6) return "中";
  return "重";
}

/* 危险信号字典（键对齐 templates/multi_dim_record_template.json，
   中文名对齐 templates/adaptive_analysis_prompt.md §4.5 关键安全红线） */
const DANGER_FLAGS = {
  daiyang:         { name: "戴阳证",   sign: "面红如妆 + 手足厥逆",         note: "真阳欲脱，严禁解表发汗，立即就医" },
  skin_cold:       { name: "肤冷脉微", sign: "皮肤触之冰冷 + 脉微",         note: "真阳衰竭，立即就医" },
  flesh_wasted:    { name: "大肉已脱", sign: "大肉已脱 + 大骨陷下",         note: "精血枯竭，预后不良，建议就医" },
  tongue_rigid:    { name: "舌体强硬", sign: "舌体短缩强硬 + 言语不利",     note: "中风先兆，立即就医" },
  tongue_critical: { name: "舌象危重", sign: "舌质紫暗 + 苔焦黑干裂",       note: "危重症，立即就医" },
  mirror_tongue:   { name: "镜面舌",   sign: "镜面舌 + 极度消瘦",           note: "重症消耗，立即就医" },
  acute_jaundice:  { name: "急性黄疸", sign: "巩膜黄染 + 皮肤黄如橘皮",     note: "急性肝胆重症，紧急就医" },
  wind_stroke:     { name: "中风重症", sign: "口不能言 + 身体不收",         note: "中风重症（风痱），立即就医" },
  throat_erosion:  { name: "狐惑重症", sign: "咽干 + 吞咽困难 + 面目乍赤乍黑", note: "建议就医" },
};

/* ---- 单日详情 mock：2026-06-25（结构 = 形状 B fixture，分数手标） ---- */
const MOCK_RECORD = {
  date: "2026-06-25",
  weekday: "星期四",
  coverage: 6,
  coverageTotal: 6,
  corrected: false,
  confidence: "HIGH",
  dims: [
    {
      key: "tongue", name: "舌诊", score: 2.7,
      groups: [
        { name: "舌质", fields: [
          { k: "颜色", v: "淡红", s: 0 },
          { k: "光泽", v: "荣润", s: 0 },
          { k: "形态", v: "偏胖大", s: 2 },
          { k: "瘀斑瘀点", v: "无", s: 0 },
          { k: "齿痕", v: "轻度", s: 4 },
          { k: "裂纹", v: "无明显裂纹", s: 0 },
          { k: "点刺", v: "舌尖散在点刺", s: null, ref: "退出评分层，仅供辨证（需肉眼确认）" },
          { k: "动态", v: "伸舌自如，无歪斜颤动", s: 0 },
        ]},
        { name: "舌苔", fields: [
          { k: "苔色", v: "白", s: 0 },
          { k: "厚薄", v: "薄白", s: 0 },
          { k: "润燥", v: "润", s: 0 },
          { k: "腻腐", v: "不腻", s: 0 },
          { k: "剥落", v: "局部剥落", s: 2 },
          { k: "分布", v: "分布尚匀", s: 0 },
        ]},
        { name: "舌下络脉", fields: [
          { k: "颜色", v: "隐约浅淡蓝紫色，大致正常", s: 0 },
          { k: "粗细", v: "不粗", s: 0 },
          { k: "迂曲", v: "无迂曲", s: 0 },
          { k: "瘀点", v: "无瘀点", s: 0 },
        ]},
      ],
    },
    {
      key: "head_face", name: "头面诊", score: 9,
      groups: [
        { name: "面域", fields: [
          { k: "面色", v: "晦暗", s: 5 },
          { k: "浮肿", v: "无明显浮肿", s: 0 },
          { k: "光泽", v: "光泽尚可", s: 0 },
        ]},
        { name: "唇域", fields: [
          { k: "唇色", v: "淡红", s: 0 },
          { k: "润燥", v: "偏干", s: 2 },
          { k: "口周", v: "口周轻度暗沉", s: 2 },
        ]},
        { name: "鼻域", fields: [
          { k: "鼻色", v: "正常", s: 0 },
          { k: "煽动", v: "无", s: 0 },
          { k: "出血", v: "无", s: 0 },
        ]},
      ],
    },
    {
      key: "eye", name: "目诊", score: 2,
      groups: [
        { name: "目", fields: [
          { k: "目赤", v: "白睛少许红血丝", s: 2 },
          { k: "巩膜黄染", v: "无黄染", s: 0 },
          { k: "眼睑浮肿", v: "无明显浮肿", s: 0 },
          { k: "目眶黯黑", v: "无明显黯黑", s: 0 },
        ]},
      ],
    },
    {
      key: "ear", name: "耳诊", score: 3,
      groups: [
        { name: "耳", fields: [
          { k: "耳色", v: "红赤", s: 3 },
          { k: "耳轮", v: "润泽", s: 0 },
        ]},
      ],
    },
    {
      key: "hand", name: "手诊", score: 4,
      groups: [
        { name: "手", fields: [
          { k: "手掌颜色", v: "偏淡白", s: 2 },
          { k: "手掌温度", v: "温", s: null, ref: "照片不可判，已降级为参考项" },
          { k: "甲床颜色", v: "淡白", s: 2 },
          { k: "甲床形态", v: "光滑", s: 0 },
          { k: "手掌瘀斑", v: "无", s: 0 },
        ]},
      ],
    },
    {
      key: "skin", name: "皮肤诊", score: 4,
      groups: [
        { name: "皮肤", fields: [
          { k: "肤色", v: "偏淡", s: 2 },
          { k: "甲错", v: "无甲错", s: 0 },
          { k: "黄汗", v: "无", s: 0 },
          { k: "水肿", v: "无", s: 0 },
          { k: "干燥", v: "轻度粗糙", s: 2 },
        ]},
      ],
    },
  ],
  photos: [
    { part: "舌面", dim: "舌诊" },
    { part: "舌底", dim: "舌诊" },
    { part: "头面", dim: "头面诊" },
    { part: "目",   dim: "目诊" },
    { part: "耳",   dim: "耳诊" },
    { part: "手",   dim: "手诊" },
    { part: "皮肤", dim: "皮肤诊" },
  ],
  diagnosis: {
    templateVersion: "v1.5.0",
    threeViews: [
      { k: "表里观", v: "里证为主" },
      { k: "正邪观", v: "正虚为主" },
      { k: "津液观", v: "津液不足" },
    ],
    fourPatterns: [
      { k: "水证", v: "轻度" },
      { k: "火证", v: "轻度" },
      { k: "气证", v: "轻度" },
      { k: "血证", v: "轻度" },
    ],
    sixDiseases: "示例六经归属（合成数据）",
    pathomechanism: "示例病机描述（合成数据，无临床含义）",
    formula: {
      name: "示例方（合成数据，12 味）",
      ingredients: [
        ["甘草", "6g"], ["茯苓", "10g"], ["陈皮", "6g"], ["山药", "10g"],
        ["莲子", "10g"], ["薏苡仁", "10g"], ["桔梗", "6g"], ["生姜", "3g"],
        ["大枣", "10g"], ["白扁豆", "10g"], ["芡实", "10g"], ["砂仁", "3g"],
      ],
      rationale: "示例方义：健脾化湿、和中养胃（合成数据，无临床含义）",
      note: "剂量仅供参考，请在执业中医师指导下使用",
    },
  },
  dangerTriggered: [],
};

/* ---- 记录列表 mock：近 14 天 ---- */
const MOCK_DAYS = [
  { date: "2026-06-25", coverage: 6, total: 24.7, dims: { 舌诊: 2.7, 头面诊: 9, 目诊: 2, 耳诊: 3, 手诊: 4, 皮肤诊: 4 } },
  { date: "2026-06-24", coverage: 6, total: 21.0, dims: { 舌诊: 2.3, 头面诊: 7, 目诊: 2, 耳诊: 3, 手诊: 4, 皮肤诊: 2.7 } },
  { date: "2026-06-23", coverage: 4, total: 14.3, dims: { 舌诊: 2.3, 头面诊: 7, 目诊: 2, 耳诊: null, 手诊: 3, 皮肤诊: null } },
  { date: "2026-06-22", coverage: 6, total: 19.7, dims: { 舌诊: 2.0, 头面诊: 7, 目诊: 2, 耳诊: 2, 手诊: 4, 皮肤诊: 2.7 } },
  { date: "2026-06-21", coverage: 2, total: 6.7,  dims: { 舌诊: 2.0, 头面诊: null, 目诊: null, 耳诊: null, 手诊: 2, 皮肤诊: 2.7 } },
  { date: "2026-06-20", coverage: 6, total: 18.3, dims: { 舌诊: 2.0, 头面诊: 5, 目诊: 2, 耳诊: 3, 手诊: 4, 皮肤诊: 2.3 } },
  { date: "2026-06-19", coverage: 6, total: 16.7, dims: { 舌诊: 1.7, 头面诊: 5, 目诊: 2, 耳诊: 3, 手诊: 3, 皮肤诊: 2.0 } },
];

/* ---- 趋势页 mock：结构对齐 generate_weekly_report_data() ---- */
const MOCK_WEEK = {
  week_id: "2026-W26",
  start_date: "2026-06-19",
  end_date: "2026-06-25",
  dates: MOCK_DAYS.slice().reverse().map(d => d.date.slice(5)),
  /* 维度偏离度序列：compute_dimension_deviation() 逐日输出 */
  dimSeries: {
    "舌诊":   [1.7, 2.0, 2.0, 2.0, 2.3, 2.3, 2.7],
    "头面诊": [5,   5,   7,   7,   7,   7,   9],
    "目诊":   [2,   2,   2,   2,   2,   2,   2],
    "耳诊":   [3,   3,   2,   2,   3,   3,   3],
    "手诊":   [3,   4,   4,   4,   4,   4,   4],
    "皮肤诊": [2.0, 2.3, 2.7, 2.7, null, 2.7, 4],
  },
  /* 舌象雷达：extract_tongue_metrics() 首/末日输出（9 轴） */
  radarAxes: ["舌质颜色", "舌苔厚度", "舌苔润燥", "齿痕", "瘀斑", "舌下络脉", "裂纹", "舌体胖瘦", "舌苔剥落"],
  radarFirst: [0, 0, 0, 3, 0, 1, 0, 3, 1],
  radarLast:  [0, 0, 0, 4, 0, 0, 0, 2, 2],
  trend_analysis: {
    "舌质变化": "舌质颜色偏离度整体稳定（0.0 → 0.0）",
    "舌苔变化": "舌苔厚度整体稳定（0.0 → 0.0）；舌苔润燥整体稳定（0.0 → 0.0）；舌苔剥落整体稳定（2.0 → 2.0）",
    "舌形变化": "齿痕程度整体稳定（4.0 → 4.0）；舌体胖瘦偏离度整体稳定（2.0 → 2.0）；裂纹程度整体稳定（0.0 → 0.0）",
    "舌下络脉变化": "舌下络脉迂曲度整体稳定（0.0 → 0.0）",
    "head_face_trend": "头面诊偏离度明显上升（5.0 → 9.0，累计分）",
    "eye_trend": "目诊偏离度整体稳定（2.0 → 2.0，累计分）",
    "ear_trend": "耳诊偏离度整体稳定（3.0 → 3.0，累计分）",
    "hand_trend": "手诊偏离度略升（3.0 → 4.0，累计分）",
    "skin_trend": "皮肤诊偏离度略升（2.0 → 4.0，累计分）",
    "体质变化趋势": "本周整体偏离度略升，头面诊为最大偏离维度。",
  },
  weekly_comparison: {
    "与前一周对比": "总偏离度较上周略升。",
    "好转指标": [],
    "恶化指标": ["面色晦暗"],
    "稳定指标": ["舌质颜色", "舌苔厚度", "齿痕", "目赤"],
  },
  summary: "本周共 7 天记录，头面诊偏离度上升，其余维度整体稳定。",
  next_week_suggestion: "继续每日记录，注意观察面色变化。",
};

/* ---- 拍照向导 mock：七部位拍摄纪律 ---- */
const WIZARD_STEPS = [
  { part: "舌面", dim: "舌诊",   tips: ["自然光下拍摄，避开有色光源", "伸舌自然放松，勿用力前伸", "禁用闪光灯"] },
  { part: "舌底", dim: "舌诊",   tips: ["舌尖抵上腭，露出舌下络脉", "⚠️ 严禁闪光灯（会加剧过度判读）", "对焦舌下两侧络脉"] },
  { part: "头面", dim: "头面诊", tips: ["正面素颜，免冠", "面向自然光源，避免逆光", "包含完整面部与唇周"] },
  { part: "目",   dim: "目诊",   tips: ["睁眼平视镜头", "白睛清晰可见", "分别拍摄双眼"] },
  { part: "耳",   dim: "耳诊",   tips: ["侧对光源", "双耳各拍一张", "耳轮完整入镜"] },
  { part: "手",   dim: "手诊",   tips: ["掌心向上自然摊开", "五指微分，甲床清晰", "禁用闪光灯"] },
  { part: "皮肤", dim: "皮肤诊", tips: ["前臂或小腿伸侧", "自然光下拍摄", "如有黄汗/甲错部位请特写"] },
];
