# bonesyear/tcm-tongue-system v1.8.34 代码审查报告

> **审查日期**：2026-10-26　**审查对象**：<https://github.com/bonesyear/tcm-tongue-system> `main` @ `a4b4b64`（v1.8.34，基线 474 项测试全绿）
> **性质**：只读审查。克隆在隔离临时目录中，**未改动任何代码**；按既定流程，本报告经你审阅确认后才进入修复。
> **逐条详情**（描述 / 证据 / 修复建议 / 登记情况 / 三视角验证）：[REVIEW_bonesyear_v1.8.34_2026-10-26_appendix.md](REVIEW_bonesyear_v1.8.34_2026-10-26_appendix.md)

---

## 0. 结论速览

**共确认 123 条问题，每条都有可运行的复现**：P0 共 10 项（含 11 个编号），P1 44 项，P2 68 项。现有 474 个测试都没有覆盖到这些场景。

| 级别 | 含义 | 数量 | 其中安全类 |
|---|---|---|---|
| **P0** | 主流程功能失效，或可导致密钥 / 健康数据外泄，应优先修复 | 10 项（11 个编号） | 7 项（8 个编号） |
| **P1** | 错误结果、数据丢失或安全加固缺口，需要特定条件才会触发 | 44 | 10 |
| **P2** | 边界情况、健壮性、可维护性、测试缺口、文档 | 68 | 10 |

**最值得优先处理的 5 件事：**

1. **网页向导 7 个部位中有 4 个的识图结果从未被评分**（G1）。查表时用错了键，头面、目、耳、手四维的识图结果全部进了 `_raw`。修复只需要改一行。
2. **安全铁律「LOW 置信度不出方剂」在 Web 主路径上没有被执行**（F21 + F2）。validator 的安全错误以 🚨 开头，而 Web 层只拦截 ❌ 开头的错误；另外 `get_formula` 也读不到 Web 报告里方剂实际存放的位置。
3. **「仅本机信任」可以被浏览器侧绕过**：CSRF（F41）、DNS rebinding（F42）、设置页 DOM XSS（F49）。三条都可能导致端点被改写，进而带走 API key 和健康记录。
4. **三条隐私外泄通道**：
   - CLI 读配置时，key 取自 `.env`，端点却没有从 `.env` 读，于是 key 和照片会发往默认的 DashScope（F22）。
   - OSS 备份脚本会把 `.env`、`.privacy-words` 和电子书一起上传（F34）。
   - pre-push 隐私守卫只扫描本次推送的最后一个提交，中间提交里的内容可以绕过（F31）。
5. **两处用户直接可见的问题**：局域网模式下，手机拍照流程的所有写操作都返回 403（F43）；周报把「全部正常」当成「没有数据」，还会建议用户重传照片（F23）。

---

## 1. 审查范围、方法与可信度

| 项目 | 说明 |
|---|---|
| 范围 | `src/`、`scripts/`（含 hooks、备份、推送脚本）、`web/`（服务端、数据层、模板、前端 JS/CSS）、`tests/`、文档与公开仓库历史 |
| 不重复报告 | `docs/AUDIT_2026-10-25_textbook-design.md` 中的领域口径问题（红线探测词零召回、评分词表缺重证词、问诊契约等，正等待主人裁决）；`docs/KNOWN_ISSUES.md` #1–#20 中已接受的设计 |
| 方法 | 14 个专项审查员（核心库、检索、脚本、shell 钩子、Web 鉴权、设置与 SSRF、文件、存储完整性、渲染 XSS、前端 JS、性能、测试质量、文档漂移、公开仓库隐私）→ 第一轮去重（134 → 93 条）→ 每条从 3 个视角独立验证（独立复现 / 设计与登记上下文 / 影响定级）→ 完备性评审指出 5 个遗漏方向 → 第二轮补漏 30 条 → 同样做 3 视角验证 |
| 结果 | 123 条全部判定成立（112 条 3/3、11 条 2/3），每条至少有一个视角独立复现 |

**关于可信度，有几点需要说明：**

- **否决数为 0，原因是发现阶段就要求附带复现。** 验证阶段的主要作用因此变成了校准级别：44 条被下调，5 条被上调。本报告的级别以「影响定级」视角为准。
- 我做了两处人工调整：
  - **F2 / F21 上调为 P0**：项目把「LOW 禁方剂」定为铁律，复现视角和上下文视角都判为高。影响视角判为中，理由是需要 LLM 违约或编辑降级才会触发，且 CLI 周报仍能事后标出。
  - **G20 下调为 P2**：影响视角之所以把它上调为高，是因为在复现过程中发现了 G1。G20 本身（点刺依据、耳道分泌物两个字段没有映射）只算低。
- 我亲自对照源码抽查了 G1、F22、F49、F21，结论与报告一致。
- 行号以 `a4b4b64` 为准。复现脚本在本会话的临时目录里（见 §9），会话结束后可能被清理。
- **F41 的一个限定**：完整的利用链是用 Flask test client 带跨站 Origin 跑通的，但 cookie 会不会随跨站 POST 发出取决于浏览器的 SameSite 策略，这一步只按浏览器规则推理，没有在真实浏览器中验证（详见 P0-3）。

---

## 2. P0：优先修复（10 项）

### P0-1　向导识图映射查错了表：头面 / 目 / 耳 / 手 4 个部位从不计分　`G1`（附带 `G20`）

- **位置**：`web/wizard_store.py:193`（`map_observation`）；调用方是 `web/app.py:509`
- **问题**：`OBSERVE_MAP.get(part, {})` 用部位名（头面 / 目 / 耳 / 手）去查表，但 `OBSERVE_MAP` 的键是 prompt_key（头面部 / 眼部 / 耳部 / 手掌）。这 4 个部位拿到的映射表是空的，识图返回的每个字段都被当成「未识别键」塞进 `_raw`。同文件第 216 行的 `observe_photo` 用的是 `PART_BY_NAME[part]["prompt_key"]`，两处写法不一致。
- **影响**：在网页向导这条主路径上，这 4 维没有观察值，不计覆盖度，评分为 None，置信度也被压低。每拍一个部位，前端都会弹出「部分识图字段未识别：面色、唇色……」。这个问题从引入向导的 35011e1 起就存在。现有测试只上传过舌面，所以没有发现。
- **建议**：改为 `OBSERVE_MAP.get(PART_BY_NAME[part]["prompt_key"], {})`，或者把表键统一成部位名。再补一条契约测试：7 个部位各用一组规范词跑一遍，断言 `unmapped` 为空。同时处理 G20：prompt 要求输出「点刺依据」「耳道分泌物」，表里却没有映射，建议把它们归入独立的 `_notes`。
- **需要决定**：已有向导记录里，这 4 维的数据还躺在 `_raw` 中，是否写一次性迁移脚本把它们搬回正确路径。

### P0-2　「LOW 置信度不出方剂」在 Web 路径上失效　`F21` + `F2`

- **位置**：`scripts/input_validator.py:249`；Web 的三个保存入口是 `web/app.py:573`、`web/records_store.py:696`、`web/trends_store.py:322`；另有 `src/record.py:413`
- **问题**：
  - **F21**：validator 的安全边界错误以「🚨 安全边界违反」开头，而 Web 三个入口都用 `e.startswith("❌")` 筛选阻断项。🚨 错误因此被整条丢掉，既不拦截，也不出现在返回给前端的 errors 或 warnings 里。在详情页把一条 MEDIUM 记录的某一维清空，使它降为 LOW，就能保存出违规记录。
  - **F2**：`get_formula` 只认 `formula`、`formula_adjust`、`formula_with_dosage` 和 `diagnosis.方剂建议` 这几个位置，但 Web 辨证报告把方剂写在 `diagnosis.report.markdown` 里。所以即使 🚨 不被过滤，也检测不到 Web 报告中的方剂。
  - **附带发现**：`update_observation` 修正后不会重算 `confidence`，覆盖度已经降到 1 维时，交给辨证 LLM 的仍然是「置信度：MEDIUM」。
- **影响**：这条铁律在 CLI 下以退出码 1 强制执行，在 Web 主路径上只剩 prompt 约束。
- **建议**：
  1. validator 改为返回结构化的严重级别，不再依赖 emoji 前缀表达语义。
  2. Web 三个入口只拦截「本次写入新引入的 🚨」，已存在的 🚨 放进 warnings 回传给前端。如果一律拦截，已经违规的存量记录在 Web 上就什么字段都改不了。
  3. 报告写回前，对 LOW 记录的「方剂建议」小节做剂量模式检测（g、克、两、钱、枚，以及中文数字）。注意合规的 LOW 报告本来就允许写「方剂类别方向」，不能只靠全文匹配方名。
  4. 修正后按向导的同一套口径重算 confidence。
  5. 补 field、submit（merge）、report 三条路径的回归测试。

### P0-3　所有表单式 POST 都没有 CSRF 防护　`F41`

- **位置**：`web/app.py`。`admin_allowed()` 在 :75-91，boot_ack 门禁在 :120-147，`/settings` 在 :632
- **问题**：
  - 请求只要来自本机，就被直接当成管理员。
  - 整个应用没有 CSRF token，也不校验 Origin 或 Referer。
  - `boot_ack` cookie 没有设置 SameSite 和 HttpOnly，而签发它的 `POST /welcome` 本身不做任何校验。
  - `/settings`、`/demo`、`/record/<date>/restore`、`/record/<date>/report`、`/wizard/photo` 都接受普通表单 POST。这类「简单请求」不会触发 CORS 预检。
- **影响**：用户本机开着服务时，只要访问一个恶意网页，对方就可以：
  - 改写 `.env` 中的 `LLM_BASE_URL` 或 `VISION_BASE_URL`，之后识图和报告请求会带着 Bearer key 和整份记录发往对方。实测利用链共 3 步：签发 cookie → 改写端点 → 触发报告，攻击者收到了 key 和 87KB 的当日记录。
  - 改写 `WEB_HOST` 或 `WEB_ADMIN_TOKEN`。
  - 浏览器差异：Firefox 和 Safari 没有默认 Lax，可以利用；Chrome 和 Edge 有「Lax+POST 两分钟豁免」，通常需要用户在恶意页上点一次。
- **建议**：
  1. 加一个统一的 `before_request`：所有改变状态的 POST（包括 `/welcome`）都要求 Origin 存在（缺失时看 Referer），且其 host 在白名单内。也可以改用每进程随机的 CSRF token，表单用隐藏字段，fetch 用自定义请求头。
  2. `boot_ack` 设置 `samesite="Strict", httponly=True`。
  3. 补测试：带外站 Origin 的上述 POST 都应返回 403。

### P0-4　不校验 Host 头，可被 DNS rebinding 绕过　`F42`

- **位置**：`web/app.py:75`；`/settings/models` 在 :681-701
- **问题**：`is_local()` 只看 `remote_addr`，应用没有 Host 白名单。一个解析到 127.0.0.1 的外部域名因此会被当作同源：它可以自己签发 boot_ack，读取 `/record/*` 和 `/photos/*`，还能以 JSON 方式调用 `/settings/models`。这个接口允许 body 覆盖 `base_url`，同时继续使用已保存的 key，等于把已存 key 发往调用方指定的地址。
- **建议**：
  - Host 白名单默认只放行 `127.0.0.1:<port>`、`localhost:<port>`、`[::1]:<port>`；`--lan` 时再加入局域网 IP 和 `.env` 中显式配置的主机名，不匹配返回 400。
  - `/settings/models` 在 `base_url` 被覆盖时，不再回落使用已保存的 key。
  - 这一项可以和 P0-3 放在同一个 `before_request` 里一起实现。

### P0-5　设置页「测试连通性」存在 DOM XSS　`F49`

- **位置**：`web/templates/settings.html:415/417`；错误消息来自 `web/llm_client.py:89-95` 和 `scripts/vision_client.py:163-173`
- **问题**：上游端点的 HTTP 错误响应体，前 200 字符会被拼进异常消息，返回为 `data.detail`，前端再用 `innerHTML` 原样插入页面。上游可能是第三方中转站，也可能是被中间人篡改的明文局域网端点。只要它返回含 HTML 的错误体，用户点一下「测试连通性」，脚本就会在 `127.0.0.1:8600` 源内执行。再加上本机请求免鉴权，脚本可以改写端点，也可以读取全部记录。已在真实浏览器中复现。
- **建议**：
  - 改为 `span.textContent = data.detail`，全站禁止把响应数据拼进 innerHTML。同类问题还有 P2 的 F70（向导红线弹窗）和 F74（相关测试缺口）。
  - 纵深防御：上游错误体只保留 JSON 里的 `error.message`；全站加 CSP 和 `X-Content-Type-Options: nosniff`（F44）。

### P0-6　CLI 的模型和端点只读环境变量、不读 .env，key 与照片会发往默认的 DashScope　`F22`

- **位置**：`scripts/vision_client.py:109-111`（模块级的 `MODEL` / `URL`），以及 :136、:151、:154
- **问题**：`load_key()` 会读 cwd 下的 `.env`，`MODEL`、`URL`、`TIMEOUT`、`MAX_TOKENS`、`TEMPERATURE` 却只读 `os.environ`。按 README「换模型 checklist」用 `.env` 配置后直接运行 CLI，实测请求发往 `dashscope.aliyuncs.com`，带着用户为别家厂商配置的 Bearer key 和 base64 照片。实验中用本地代理拦截了真实的 CONNECT 请求。
- **建议**：五项配置在 `call()` 运行时按「环境变量 > .env」统一解析，与 `load_key` 共用一个函数，再补测试。这个最小修复**不需要推翻** CHANGELOG v1.4.11「默认端点保留」的定策。是否彻底去掉内置的第三方默认端点，请主人裁决。
- **同根因的问题**：F24（Web 下 TIMEOUT、TEMPERATURE 不生效）、G12（LLM_MAX_TOKENS 不读 .env）、G9（用 `os.environ` 加 `importlib.reload` 传配置，并发时会错配）、G10（清掉 key 后会悄悄从其他来源取 key）。

### P0-7　OSS 备份会把 .env、真实姓名表和电子书整包上传　`F34`

- **位置**：`scripts/backup_to_oss.sh`。find 在 :50-60，tar 在 :78-93，默认桶在 :22
- **问题**：排除集只有 `records/`、`charts/`、`jingfang_tanyuan_full.md` 和几个缓存目录。以下内容都会被打进包：`.env`（内含 VISION_API_KEY、LLM_API_KEY、WEB_ADMIN_TOKEN）、`.privacy-words`（真实姓名）、`_books/`、`*.epub`、`*.pdf`、`docs/*_TASK_*.md`、`.claude/`。脚本结尾却打印「已排除……版权物」。此外 `OSS_BUCKET` 的默认值是作者自己的桶 `smin-oss`。
- **建议**：
  - 首选白名单打包：`git -C "$SYSTEM_DIR" ls-files -z | tar --null -T - -czf …`，少量需要的未跟踪文件再显式追加。
  - 去掉默认桶，未设置 `TCM_OSS_BUCKET` 时直接报错退出。
  - **如果主人已经运行过这个脚本**，建议检查 OSS 上已有的包，并轮换其中的 API key 和口令。

### P0-8　pre-push 只扫推送的最后一个提交，中间提交可以绕过　`F31`

- **位置**：`scripts/hooks/pre-push:168-170`（调用 ①②③ 层检查）、:26-31（`scan_fixed` / `scan_regex`）、:187（处置提示）
- **问题**：内容检查只对 `local_sha` 这一棵树执行 `git grep`。一次推送如果包含多个提交，只要最后一个提交删掉了敏感内容，中间的提交照样会推上远端。守卫自己的提示是「amend 或新提交」，而选「新提交」正好走进这个漏洞。实测：第一次推送被拦截，用户新提交一次删除文件后再推，守卫显示通过，真实姓名留在了远端历史中。
- **建议**：
  - 用 `git rev-list "$local_sha" --not --remotes="$1"` 得到真正新增的提交，逐个扫描它们新增的行。
  - 改用 `git grep -F -f .privacy-words` 一次匹配全部词：60 个词逐个扫要 0.95s，一次性扫只要 0.014s。
  - 提示改为「必须 amend 或 rebase 掉含敏感内容的提交」，并同步修正 `scripts/hooks/README.md:14` 和 `docs/user-guide.md:225` 的说法。
- **同区域的其他问题**：F33（扫描盲区）、F35（提交信息检查范围算错）、F37（在 worktree 中找不到词表时直接放行）、F36（日志里打印完整密钥）。

### P0-9　局域网模式下，向导和详情页的写操作全部返回 403　`F43`

- **位置**：`web/templates/wizard.html:702-705`（postJSON）、:727（照片上传）；`web/templates/record.html` 的 :572、:657、:689；`web/app.py:81-91`
- **问题**：服务端要求局域网请求携带口令，JSON 请求只认 body 里的 `admin_token`。但页面上所有 fetch 都不带口令，模板也拿不到 `token_arg`。即使设好了 `WEB_ADMIN_TOKEN`、访问地址也带了 `?token=`，`docs/web-quickstart.md` 第七章描述的「手机拍照（局域网）」流程依然整体 403。问诊选项、跳过、清除全部这几处还没有 else 分支，点了没有任何反馈。
- **建议**：口令校验通过后，下发一个 HttpOnly + SameSite=Strict 的会话 cookie，`admin_allowed()` 认这个 cookie。这样前端不用改，也能顺带解决 F45（口令出现在 URL 和日志里）。再补一组测试：局域网来源加正确口令，走完向导和修正流程。

### P0-10　周报把「全部正常」当成「无有效观测」　`F23`

- **位置**：`scripts/generate_weekly_report.py:286-290`。依赖它的地方有 :323、:492-504、:676、:682-693
- **问题**：变量 `n` 是「分值大于 0 的指标数」，下游有 5 处把 `n == 0` 当作「没拍到、没解析到」。但已经拍摄、全部正常的维度，`n` 同样是 0。项目自带的官方样例 `shape_c_sample.json` 中就有 5 个维度属于这种情况。
- **影响**：
  - 从异常恢复到正常时，永远不会报告「好转」。
  - 全正常的一周，摘要写「各维度均无有效观测」，下周建议写「请核对档案或重传照片」。
  - 趋势图上正常日的点被删掉。
  - Web 趋势页直接展示这些内容。CHANGELOG 声称已经区分「正常 0」和「无数据」，这只在逐指标层成立，维度层并没有做到。
- **建议**：detail 增加一个 `observed` 字段（维度已覆盖，且不是声明正常的占位）。所有「无观测」判断改用 `observed`，`n` 只表示异常负荷。补一条测试：全正常、全覆盖的周末必须报「减轻」或「稳定」。

---

## 3. P1：分主题（44 项）

> 每条的完整描述、证据和修复建议见附录，下面只列要点。

### A. 安全规则执行：红线、置信度、方剂（11 项）

| ID | 问题 | 位置 | 建议要点 |
|---|---|---|---|
| F4 | `has_formula_content` 的兜底扫描不认经方剂量单位（两、钱、枚）、中文键（方名、组成、药物）以及名单外的方名，与函数文档里「键名漂移不能成为放行理由」的承诺不符 | `src/record.py:195` | 按 fail-closed 改造：白名单补「方名、组成、药物、处方」等键；剂量正则覆盖两、钱、枚、升、中文数字和全角字符；方名改用「汤、散、丸、饮」这类通用形态匹配 |
| F5 | `allows_dosage` 没有任何生产调用，「MEDIUM 只给方剂大类、不给剂量」只靠 prompt 保证 | `src/confidence.py:55` | 在 validator 和报告写回处接入 |
| F3 | `danger_flags` 同时含 B 式 `triggered` 列表和 A 式旗对象时，A 式的 `triggered=true` 被静默丢弃，失败方向是放行 | `src/record.py:435` | 两种形状取并集；validator 对混合结构报错 |
| F63 | 修正流重估红线只对形状 B 生效，形状 A、C 的记录改成「强硬」「镜面」等红线词后不会亮横幅 | `web/records_store.py:674` | 改用 `DailyRecord` 的统一观察访问层再做探测 |
| G21 | 「误判，去修正」只清空红线旗，不改观察值，也不留任何痕迹；记录前后矛盾，下一次任意修正又会让红线静默复活 | `web/app.py:563` | 记录裁决审计字段，并引导用户去修改对应的观察值 |
| G22 | merge 模式下选「误判」，会连同此前已「保留警示」的旧红线一起清掉；而「保留」的决定从不落盘，导致每次都对已确认的红线重新拦截 | `web/app.py:563` | 区分新旧红线、支持逐条裁决，并持久化「保留」决定 |
| G23 | 红线一旦写入 `triggered` 就只增不减，修正观察值也撤销不了；历史日期没有任何撤销入口 | `web/records_store.py:677` | 被修正字段对应的探测键按新值重新判定，不再命中就移出 `triggered`，并写一条审计记录；人工写入的键保留不动 |
| G14 | 形状 C 的扁平问诊答案被辨证 LLM 输入和禁忌反向核对静默丢弃：问诊里报了「厥冷」，核对行仍写戴阳「未观测」 | `web/trends_store.py:161` | 在 `DailyRecord` 提供统一的 `get_inquiry_answers()` |
| F1 | 舌面选「声明正常」、舌底实拍时，整个舌诊维度被判为未覆盖，真实的舌下络脉异常被隐藏 | `src/record.py`、`web/wizard_store.py:451` | 占位判定改为「该维度的非空值全部是占位」，与文档描述一致；同一维度的另一部位写入真实值时，删除先前写入的占位 |
| G19 | 「声明正常」占位按逐字比较，半角括号、零宽字符等变体会被当作「已覆盖、0 分」 | `web/records_store.py:498` | 规范化时对常量和输入同时做；注意 NFKC 会改变全角的「？」和括号 |
| F6 | 评分的否定守卫把「不规则」「不均匀」中的「不」当成否定词，validator 又因为值里含「不」而豁免告警，异常被静默记为 0 分 | `src/scoring.py:389` | 加入构词语素白名单 |

> G21、G22、G23 涉及「误判 / 保留警示」两个出口的产品语义，需要主人裁决（见 §7）。F6 与 AUDIT_2026-10-25 中「danger 与 scoring 否定守卫双轨」一条相关，但不是同一个问题，建议与 AUDIT 的裁决一起排期。

### B. Web 安全加固（5 项）

| ID | 问题 | 位置 | 建议要点 |
|---|---|---|---|
| F46 | 读取 `.env` 时把值中 `#` 及其后的内容都当注释截掉，含 `#` 的管理口令实际只剩前缀，用户自己也察觉不到 | `web/envfile.py:38` | 只有 `#` 前是空白、且值没有被引号包住时，才当作行内注释；写入时给特殊字符加引号并转义，读写往返后回读校验；口令比较改用 `compare_digest` |
| F51 | `write_env` 对值既不校验也不转义，一个普通字段里塞换行就能注入任意额外的键 | `web/envfile.py:66` | 拒绝所有 `str.splitlines` 认作换行的字符（返回 400）；键名按正则校验；URL 和数值字段做格式校验 |
| F50 | 出站请求没有加固：可以读本机 `file://`、可以探测内网、已存 key 可以发往任意地址；跟随重定向时会跨主机转发 Authorization；响应体没有大小上限 | `web/llm_client.py:45` | 抽出公共的 `safe_fetch`：只允许 http(s)；跨主机重定向时去掉 Authorization；限制响应体大小和总时长；已存 key 只发往同源端点。私网段不宜一刀切，Ollama 这类本地端点是合法用法 |
| F91 | 局域网模式下，没有口令的设备也能浏览全部档案和原始照片；口令通过 URL 查询串传递，并写入访问日志 | `web/app.py:120` | 局域网下读取也要求鉴权（P0-9 的会话 cookie） |
| G7 | `WEB_HOST` 不做任何校验：`'::'`、`'0'` 或网卡 IP 都会对外开放，但既不告警，设置页还显示「仅本机」 | `web/app.py:760` | 用 `ipaddress` 解析并按白名单校验；用 `is_loopback` 判断是否对外暴露，非回环地址一律走口令检查和告警；设置页显示实际绑定的值 |

### C. 数据完整性、并发与坏档容错（12 项）

| ID | 问题 | 位置 |
|---|---|---|
| F55 | 「恢复」总是选全部历史中最早的备份，会删掉已生成的报告、跨代回滚，界面上也无法撤销 | `web/records_store.py:462` |
| F56 | 照片先覆盖、再识图，而且从不备份；识图失败或取消提交后，原图永久丢失 | `web/app.py:499` |
| F57 | 报告生成期间做的修正，会被报告落盘静默覆盖回滚（读-改-写丢失更新） | `web/trends_store.py:239` |
| F60 | 向导草稿非原子写，读到半截文件就整份重置，并发请求会清空草稿 | `web/wizard_store.py:146` |
| F61 | `/demo` 会无条件覆盖 2026-06-25 的真实记录，而且不备份 | `web/records_store.py:598` |
| F65 | 临时文件名固定且没有锁：并发时校验会串档，非法记录被放行；修正接口返回成功，数据却没有落盘 | `web/records_store.py:426` |
| F66 | LLM 结构化输出没做类型校验就落盘，`three_views` 为数组时该日详情页永久 500 | `web/trends_store.py`、`web/records_store.py:300` |
| F67 | 一份非 UTF-8 档案就会让首页和趋势页 500 | `web/records_store.py:491` |
| F68 | 详情页用记录 JSON 里的 date，而不是 URL 中的日期；两者不一致时，修正会写进另一天的记录 | `web/records_store.py:786` |
| F69 | 一条 date 不合法、或 `triggered` 含非字符串元素的记录，就能让首页、详情页、趋势页整页 500 | `web/records_store.py:521` |
| F72 | `?week=` 和 `?m=` 只做正则校验，`2026-02-30`、`2026-13-45` 这类值直接 500 | `web/app.py:259` |
| F27 | validator 只检查 date 是否存在，不校验格式，也不检查是否与文件名一致 | `scripts/input_validator.py:92` |

> **统一修法**：
> 1. 写一个原子写工具函数（`mkstemp` 生成唯一临时名，再 `os.replace`），所有落盘都走它。
> 2. 加按日期划分的进程内锁，读-改-写在锁内完成。
> 3. 加载层统一容错：坏档跳过，并给出告警。
> 4. 备份按用途打标签（correction、report、wizard、restore）；「恢复」只在最近一次向导提交之后的修正备份中挑选，保留已生成的报告，并提供撤销入口。
>
> 这四件事可以覆盖本组大部分问题，以及 P2 的 F53、F64、G4、G27–G30。

### D. 配置与外部模型调用（4 项）

| ID | 问题 | 位置 |
|---|---|---|
| F24 | 设置页的 `VISION_TIMEOUT` / `VISION_TEMPERATURE` 写进 `.env` 后从不生效，`VISION_MAX_TOKENS` 在 Web 下也无法配置 | `scripts/vision_client.py`、`web/app.py:136` |
| G12 | `LLM_MAX_TOKENS` 只从 `os.environ` 读；填了非数字直接 500；注释写默认 8000，代码实际是 16000；报告超时固定为 150 秒 | `web/trends_store.py:253` |
| F25 | `vision_client.call` 没有把所有异常都转成 RuntimeError：畸形或断流的响应让向导 500；429 被误报为「检查凭证」 | `scripts/vision_client.py:160` |
| F26 | LLM 输出后处理脆弱，且同样的代码复制了三份：带 `<think>` 块或前置说明句时解析失败；「舌面。」会被归为「其他」 | `scripts/vision_client.py:207` |

### E. 前端交互（5 项）

| ID | 问题 | 位置 |
|---|---|---|
| F75 | 设置页的模型开关：服务重启后会误报「✓ 已保存」，切换时还会把表单里未保存的编辑一起提交 | `web/templates/settings.html:302` |
| F76 | 识图结果写到了「当前步」，而不是发起上传的那一步；识图期间切换步骤，结果会挂到错误的部位 | `web/templates/wizard.html:731` |
| F77 | `postJSON` 不检查 HTTP 状态，多数调用既没有 catch 也没有 else，失败时点了毫无反应；提交按钮没有在途锁 | `web/templates/wizard.html:702` |
| F78 | 校验器的 ⚠️ 告警被前端丢弃，用户看不到「词表外措辞会被按 0 分计」这类提示 | `web/templates/record.html:667` |
| F79 | 移动端横向溢出：首页近七日行在 375px 宽度下撑到 538px；趋势图不随窗口大小调整 | `web/static/css/base.css:486` |

### F. 隐私守卫与公开仓库（4 项）

| ID | 问题 | 位置 |
|---|---|---|
| F33 | 隐私扫描有大面积盲区：二进制或 UTF-16 文件、`.gitattributes` 标为 binary 的文件、JSON 的 `\u` 转义、大小写变体、文件名本身；`scripts/hooks/` 整个目录在所有层都被排除 | `scripts/hooks/pre-push:27` |
| F35 | 提交信息检查的范围算错，三种情况会静默漏检：根提交、force push 时远端 SHA 本地不存在、附注标签的消息 | `scripts/hooks/pre-push:127` |
| F37 | 在 git worktree 中找不到 `.privacy-words` 时直接放行；词表行尾有空白时词条失效 | `scripts/hooks/pre-push:21` |
| F90 | 2026-09-17 的脱敏只做了前向提交，真实随访病案仍在公开 `main` 的可达历史中，任何 clone 都能读到。这与 KNOWN_ISSUES #11 说的 dangling 对象不是一回事。另外，曾误提交的 `records/_web-err.log` 暴露了内网地址 | `tests/fixtures/2026-06-25_analysis.json` |

> F90 是否重写公开历史，需要主人裁决（见 §7）。本报告和附录已对其中的真实临床值和内网 IP 做了脱敏。

### G. 知识库检索与性能（3 项）

| ID | 问题 | 位置 |
|---|---|---|
| F11 | 趋势报告的知识库引用名额被 5 个锚词占满，体征词和红线词的检索结果永远进不了报告（v1.8.27 声称的修复不成立） | `web/trends_store.py:216` |
| F16 | 装了 sentence-transformers 但模型加载失败时，不会回退到 TF-IDF；之后每次低命中检索都抛异常并重新尝试下载模型 | `src/retrieval/rag_search.py:304` |
| F82 | 记录文件名不规范时，首页复杂度退化为 O(N²)：1460 条记录时单次请求超过 1.1 秒 | `web/records_store.py:403` |

---

## 4. P2：边界情况、健壮性、可维护性、测试、文档（68 项）

> 按区域排列。每条的完整内容见附录。

| ID | 区域 | 类型 | 问题 | 位置 |
|---|---|---|---|---|
| F70 | Web 前端 | 安全 | 向导红线拦截弹窗用 innerHTML 拼接 f.name/f.sign/f.note；merge 模式会把既有记录 triggered 里的未知键原样当作 name 回传 | `web/templates/wizard.html:753` |
| F71 | Web 前端 | 缺陷 | 设置页把 token_arg 用 HTML 转义写进 &lt;script&gt; 字符串字面量：含 & &lt; &gt; " ' 的口令在 JS 请求中失效，?token=\ 会让整段脚本语法错误 | `web/templates/settings.html:347` |
| F80 | Web 前端 | 可维护性 | 可访问性硬伤：修正按钮和开关获焦不可见，拍照上传无法用键盘操作，危险弹层缺对话框语义且没有取消出口 | `web/templates/wizard.html:160` |
| F81 | Web 前端 | 缺陷 | 问诊答案点选后无法单独撤销（只能清除全部），误触「绝汗」等红线选项会直接进入记录和红线探测 | `web/templates/wizard.html:557` |
| F89 | Web 前端 | 文档 | 文档和界面文案与代码事实不符：「声明正常计入覆盖度」、「两组模型都要配」、REPAIR_PLAN 死链、CHANGELOG 里滞留的 Unreleased 段 | `web/templates/wizard.html:197` |
| G11 | Web 前端 | 缺陷 | 设置页「访问与安全」的状态和实际运行参数对不上：--lan 启动时显示「仅本机」，局域网地址的端口写死为 8600，只绑本机时也让手机用局域网地址访问 | `web/templates/settings.html:235` |
| F62 | Web 数据层 | 缺陷 | 照片目录与记录脱钩:换扩展名重拍、跳过的部位、上一轮会话留下的照片都会被当作'原图对照'展示 | `web/records_store.py:726` |
| F64 | Web 数据层 | 健壮性 | 报告落盘与向导提交是非原子写：中途崩溃/磁盘满留下半截 JSON，详情页 404 且「恢复」入口不可达 | `web/trends_store.py:326` |
| F88 | Web 数据层 | 可维护性 | 同一逻辑存在多份拷贝且已经出现分歧：选档和加载、覆盖度计算、向导两条录入通道的校验链 | `web/records_store.py:398` |
| G3 | Web 数据层 | 缺陷 | 首页「连续记录」从最近一条记录往回数，不从今天数；「近七日」实际是最近 7 条记录；未来日期的记录会截断真实连续天数，三处都没有测试 | `web/records_store.py:585` |
| G4 | Web 数据层 | 健壮性 | 备份时间戳用本地墙钟，restore 按文件名字典序取 min：夏令时回拨、系统改时区或时钟回调后，「恢复原始」会恢复到中间版本却报成功 | `web/records_store.py:462` |
| G15 | Web 数据层 | 健壮性 | 详情页修正接口 /record/&lt;date&gt;/field 完全不做服务端校验：词表外文本、空值、null、列表、声明正常占位、超长值都会 200 落盘 | `web/records_store.py:667` |
| G18 | Web 数据层 | 健壮性 | 识图结果的类型和键名不规范化：顶层数组会让整部位观察都进 _raw['']，列表/布尔被 str() 拍平，键名多一个空格就静默不评分，危重舌象写成 {名称: true} 时红线漏报 | `web/wizard_store.py:184` |
| G20 | Web 数据层 | 可维护性 | OBSERVE_MAP 和识图 prompt 契约漂移：prompt 要求输出的「点刺依据」「耳道分泌物」没有映射，合规输出每次都触发「未识别字段」告警，自由文本还被写入档案并参与红线扫描 | `web/wizard_store.py:111` |
| G27 | Web 数据层 | 缺陷 | 记录层所有 glob 拼接点都没有 glob.escape：文件名或数据目录含 [..] 时，恢复失败、首页显示空库，恢复还会把另一份档案的备份写进当前记录 | `web/records_store.py:458` |
| G28 | Web 数据层 | 健壮性 | 数据生命周期没有回收和删除路径：备份无限增长、.corrupt 被覆盖、孤儿草稿和照片永存；手工删档后，「恢复」还会把已删内容复活 | `web/records_store.py:437` |
| G29 | Web 数据层 | 缺陷 | list_dates 与 _select_daily_file 的匹配规则不一致：趋势页「去看看」链接会死循环；macOS 上首页显示空库，详情页和周报 CLI 却能读到记录 | `web/records_store.py:470` |
| G30 | Web 数据层 | 缺陷 | _SUSPECT_ARCHIVE_RE 漏掉中文「副本」「(1)」「_backup」等常见副本名，而备份按文件名挂钩：系统外的副本一出现，修正就写进副本，恢复报「未被修正过」 | `web/records_store.py:24` |
| F44 | Web 服务端 | 安全 | 缺少 X-Frame-Options/CSP 等安全响应头，设置页可被嵌入 iframe 点击劫持 | `web/app.py:119` |
| F45 | Web 服务端 | 安全 | 管理口令放在 URL 查询串里，并被 302 回写到 Location，会进入访问日志和浏览历史 | `web/app.py:678` |
| F47 | Web 服务端 | 健壮性 | JSON body 不是对象时，admin_allowed 和各端点都会 500 | `web/app.py:89` |
| F48 | Web 服务端 | 安全 | 口令比较不是常量时间；is_local 不识别 IPv4 映射地址 | `web/app.py:92` |
| F52 | Web 服务端 | 健壮性 | .env 不是 UTF-8 时全站 500：write_env 抛的是裸 UnicodeDecodeError，设置页的 env_error 提示路径是死代码；带 UTF-8 BOM 时首行的键静默失效 | `web/envfile.py:55` |
| F53 | Web 服务端 | 健壮性 | .env 写入不是原子操作（先截断再写），读路径也不加锁：并发时会读到空配置，合法口令被误拒；写到一半崩溃或磁盘满时 .env 整体丢失 | `web/envfile.py:69` |
| F54 | Web 服务端 | 缺陷 | 环境变量锁定的判定口径不一致：LLM_DISABLED/VISION_DISABLED 设为空串时，UI 显示可切换，服务端静默不写却仍返回「已保存」 | `web/app.py:661` |
| F59 | Web 服务端 | 健壮性 | 上传没有大小上限、也不校验文件头:超大文件会整份读进内存并 base64,非图片内容也会被保存并外发 | `web/app.py:492` |
| F73 | Web 服务端 | 缺陷 | mdmini 渲染正确性：松散有序列表每项都从 1 重新编号、列表起始序号被忽略、全由 -/: 组成的表格数据行被静默删除 | `web/mdmini.py:79` |
| F83 | Web 服务端 | 性能 | 首页每次请求都全量读取并评分所有记录（O(N)），日历再把当月记录重复加载一遍，实际只用到 7 条加当月 | `web/app.py:184` |
| G2 | Web 服务端 | 缺陷 | 向导跨午夜：每个请求各自取 date.today() 定位草稿，前端不带日期，午夜前后的操作分进两份草稿，提交必失败，旧草稿既没有恢复入口也不会被清理 | `web/app.py:540` |
| G5 | Web 服务端 | 健壮性 | 日期算术溢出：/?m=9999-12、/?m=0001-01、/trends?week=9999-12-25~31 和 0001-01-01~07 通过校验后在 ±timedelta 处抛异常，返回 500；页面自己的「下月/下一周」按钮会把人带进这些地址 | `web/app.py:263` |
| G6 | Web 服务端 | 健壮性 | 「今天」完全由服务端进程的本地时区决定，没有时区配置，记录时间戳也不带时区偏移：部署机或容器在 UTC 时，用户早晨的记录会落到前一天 | `web/app.py:180` |
| G8 | Web 服务端 | 安全 | 「局域网开启需口令」在代码里没有任何强制：启动、保存都不拦，可以在局域网模式下清掉口令，弱口令也照收且不限速；告警文案还低估了暴露范围 | `web/app.py:762` |
| G9 | Web 服务端 | 缺陷 | 视觉配置借进程级 os.environ 和 importlib.reload 传递，并发时端点、key、模型会错配，一家的 key 可能发到另一家 | `web/app.py:303` |
| G10 | Web 服务端 | 安全 | 设置页清掉视觉 key 后，「测试连通性」会悄悄从 DASHSCOPE_API_KEY 或 ~/.hermes/.env 等其他来源取 key，发往页面上配置的任意端点，并显示「连通正常」 | `web/app.py:309` |
| G13 | Web 服务端 | 健壮性 | 生产入口直接跑 Werkzeug 开发服务器：每个连接一个线程且不设上限，也没有请求超时，局域网里任何设备不需要口令就能挂住无限多的线程 | `web/app.py:766` |
| G16 | Web 服务端 | 安全 | /wizard/inquiry 只白名单问题键，不校验答案：任意长度、带换行的自由文本原样进入辨证 LLM 输入；非字符串直接 500；前端的出汗门禁在服务端不执行 | `web/app.py:468` |
| G25 | Web 服务端 | 健壮性 | acknowledge 不做白名单，也不绑定弹层展示过的红线集合：任意非空值都算「已确认」，首次提交即可带 fix 跳过弹层，弹层之后新增的红线会被一并处理 | `web/app.py:579` |
| F32 | 仓库守卫/运维脚本 | 缺陷 | push.sh 的 push 后验证形同虚设：fetch 没有绕过镜像，本地 tracking ref 会让验证自证通过；仓库级 insteadOf 把 push 改到镜像时仍报「✅ 验证通过」 | `scripts/push.sh:53` |
| F36 | 仓库守卫/运维脚本 | 安全 | 守卫日志本身成了泄露面：命中凭证时打印含完整密钥的整行，第 ① 层还直接打印敏感词本身 | `scripts/hooks/pre-push:90` |
| F38 | 仓库守卫/运维脚本 | 健壮性 | backup_to_oss.sh 的增量判定会静默失效：安装路径上层含 /records/、/charts/ 等目录名时哈希恒为空串，备份永久跳过；manifest 损坏时脚本静默 exit 1 | `scripts/backup_to_oss.sh:50` |
| F39 | 仓库守卫/运维脚本 | 安全 | push.sh 用整份临时 global 配置替换用户的全局配置，用户的凭据助手（gh/GCM/libsecret）被屏蔽，强制改用明文 store，交互输入的 token 会写入 ~/.git-credentials | `scripts/push.sh:44` |
| F40 | 仓库守卫/运维脚本 | 缺陷 | 第 ④ 层版本不一致的修复提示写错：提示「把 VERSION 改成 v$cl」，照做后依然失败，并提示改成「vv…」 | `scripts/hooks/pre-push:111` |
| F92 | 文档/仓库 | 文档 | 手册例图是逼真的 AI 生成人像，但 AI 水印被刻意抹除、C2PA 元数据被剥离，页面也没有 AI 生成声明 | `docs/images/face.jpg:1` |
| F93 | 文档/仓库 | 文档 | 许可声明自相矛盾且覆盖不全：web/ 等目录没有明确许可，知识库「禁止公开再分发」却放在公开仓库，LICENSE 缺少 GPL 全文 | `README.md:231` |
| F28 | 校验器/周报 | 健壮性 | danger_flags.triggered 的元素类型不校验，红线探测异常被 except: pass 静默吞掉，「可探测到红线体征但未标记」告警随之消失 | `scripts/input_validator.py:205` |
| F29 | 校验器/周报 | 缺陷 | week_id 取最后一条记录所在的 ISO 周，但统计窗口是滚动 7 天：周报标签与内容不符，同一 ISO 周内多次生成会静默覆盖 | `scripts/generate_weekly_report.py:584` |
| F30 | 校验器/周报 | 缺陷 | 双门槛「最重单项须同步下降」用在累加分维度上前提不成立，真实好转被判为「暂不判为好转」 | `scripts/generate_weekly_report.py:340` |
| G24 | 校验器/周报 | 缺陷 | 问诊来源的红线（绝汗→脱阳前兆）被「误判」清除后不可恢复：详情页不能修改问诊，validator 与修正重探都不扫问诊，LLM 被告知均未触发 | `scripts/input_validator.py:195` |
| F7 | 核心库 src | 健壮性 | 形状探测和维度取值只看键是否存在、类型是否对：空容器或非 dict 节点会遮蔽真实观测（含红线词），validator 不报错 | `src/record.py:261` |
| F8 | 核心库 src | 健壮性 | 列举式否定「未见A、B、C」只否定第一项：danger 误触发后续项；AUDIT 建议的「复用 scoring 守卫」也修不了（scoring 在「、」处截断小句） | `src/scoring.py:378` |
| F9 | 核心库 src | 缺陷 | get_inquiry_coverage 用 len(inquiry) 作分母，Web 记录只存已答题，问诊覆盖恒显示为满（如 2/2） | `src/record.py:481` |
| F10 | 核心库 src | 测试缺口 | 形状 A 模板与 _DIMENSION_INDICATORS/评分词表漂移：目诊缺巩膜颜色/下睑颜色字段，模板枚举「明显/轻度/重度」评分为 0，且无契约测试 | `src/record.py:85` |
| G17 | 核心库 src | 缺陷 | 红线探测和评分全链路没有文本规范化：零宽字符、全角空格、康熙部首、繁体字会让红线漏报，还能把正常的「淡红」误判为 7 分 | `src/danger.py:117` |
| F74 | 测试 | 测试缺口 | 测试缺口：没有任何测试覆盖客户端 innerHTML sink，也没有用 HTML 载荷渲染页面的回归测试 | `tests/test_web_trends.py:198` |
| F84 | 测试 | 测试缺口 | 安全和数据保护的关键分支几乎没有测试：10 个门禁删掉或改坏，474 个用例照样全过 | `tests/test_web_app.py:147` |
| F85 | 测试 | 测试缺口 | test_web_app.py 的 client 夹具没有传 data_root，会读取甚至改写真实的 records/ 目录，测试结果还取决于主人的真实数据 | `tests/test_web_app.py:30` |
| F86 | 测试 | 测试缺口 | mock 太粗导致关键行为测不到：发给辨证 LLM 的输入、识图结果的解析都没有真正被测，另有条件断言和恒真断言 | `tests/test_web_wizard.py:268` |
| F87 | 测试 | 测试缺口 | 测试的环境隔离不完整：_configure_vision 写进 os.environ 的值跨测试残留；开发机上有 LLM_DISABLED 或 VISION_DISABLED 时会挂 10 到 17 条 | `tests/test_web_app.py:287` |
| G26 | 测试 | 测试缺口 | 测试把「fix 后 triggered=[]」当作期望行为固化，确认语义的关键分支没有任何测试 | `tests/test_web_review_fixes.py:60` |
| F12 | 知识库检索 | 缺陷 | RAG 兜底没有相关性下限，『查无』被当成命中返回；AND 查询还会混入不满足 AND 的结果 | `src/retrieval/rag_search.py:219` |
| F13 | 知识库检索 | 健壮性 | 知识库里任意一个异常 .md 文件（非 UTF-8、失效软链、目录名以 .md 结尾）会让整个检索抛异常 | `src/retrieval/grep_search.py:81` |
| F14 | 知识库检索 | 缺陷 | 约 14% 的 RAG chunk 只有一条『---』分隔线，标题类查询时恒排第一；结果摘录取 chunk 首行而不是命中行 | `src/retrieval/rag_search.py:100` |
| F15 | 知识库检索 | 缺陷 | grep 与 RAG 结果按 (file,line) 去重基本失效：行号语义不同，且 Windows 下 RAG 路径不归一 | `src/retrieval/dispatcher.py:187` |
| F17 | 知识库检索 | 缺陷 | retrieve() 不规整查询：首尾空白会让别名展开和 grep 同时失效，悬挂的 AND 会被当作字面量检索 | `src/retrieval/dispatcher.py:89` |
| F18 | 知识库检索 | 健壮性 | 别名词典的两条解析路径行为不一致，且词典出错时整个检索崩溃而不是降级 | `src/retrieval/synonym_loader.py:56` |
| F19 | 知识库检索 | 缺陷 | expand_many 返回的 synonyms_used 永远为空列表 | `src/retrieval/synonym_loader.py:186` |
| F20 | 知识库检索 | 可维护性 | TCM_KB_ROOT 与 RAG 缓存的一致性问题：相对路径时 grep 和 RAG 会读不同的知识库；别名词典不跟随 TCM_KB_ROOT；并发首查会重复建索引 | `src/retrieval/dispatcher.py:44` |
| F58 | 识图客户端 | 安全 | 照片原样保存、原样发给视觉厂商:EXIF 里的 GPS 位置和设备信息一起外发 | `scripts/vision_client.py:143` |

---

## 5. CHANGELOG / KNOWN_ISSUES 中与实测不符的「已修复」声明

以下问题在文档里被记为已修或已一致，但复现表明修复不完整。修复时建议同步更正文档里的说法。

| 声明出处 | 声明内容 | 实测 | 对应 |
|---|---|---|---|
| CHANGELOG「周报『无观测』语义」 | 已区分「正常 0」与「无数据」 | 只在逐指标层成立，维度层仍把 n=0 当无数据 | F23 |
| CHANGELOG v1.8.27 | `max_hits` 8→10，防止体征词的命中被挤掉 | 5 个锚词仍占满全部 10 个名额 | F11 |
| CHANGELOG v1.8.0 | 修正流写回后重跑危险探测 | 只对形状 B 生效 | F63 |
| CHANGELOG v1.7.22 | 戴阳「厥冷」不再永远显示「未观测」 | 对形状 C 的扁平问诊不成立 | G14 |
| CHANGELOG Bug 7 | LOW + 方剂升级为严重错误 | 只在 CLI 下成立，Web 三个入口都丢弃 🚨 | F21 |
| CHANGELOG v1.3.3 | 修复「date 为数值时整周周报崩溃」 | `main()` 第 869 行仍然崩溃 | F27 |
| CHANGELOG v1.8.17 | 网格改为 `minmax(0,1fr)`，全站受益 | ≤760px 的媒体查询又把它覆盖回 `1fr` | F79 |
| CHANGELOG（RAG 缓存） | 不会再混合两个知识库 | `TCM_KB_ROOT` 为相对路径时仍可复现 | F20 |
| KNOWN_ISSUES #10 | 声明正常占位的判定全链路一致 | 只对逐字相同的占位串成立 | G19 |
| 92bd86b / 3f19caf 提交说明 | 脱敏后复扫零命中 | 只适用于 HEAD，历史提交中仍有真实病案 | F90 |

---

## 6. 修复分批建议

各批之间基本独立。批 1 改动小、收益高，建议先做；批 4 依赖主人裁决。

| 批次 | 主题 | 包含 | 说明 |
|---|---|---|---|
| **批 1** | 小改动、高收益 | G1 + G20、F49 + F70 + F74（innerHTML 汇点与对应测试）、F21（🚨 回传，并拦截新引入的 🚨）、F22、F34、F46、F72 + G5、F19、F40 | 多数是一到几行的修改，加上回归测试 |
| **批 2** | Web 安全框架 | F41、F42（统一的 `before_request`：Origin + Host 白名单）、F43 + F45 + F91（会话 cookie）、F44（安全响应头 / CSP）、F47、F48、F51、F52、F54、F71、F50（`safe_fetch`）、G7、G8、G10、G11、G13 | 一次设计，覆盖整个 Web 层 |
| **批 3** | 数据完整性 | 原子写 + 按日期加锁（F53、F57、F60、F64、F65）、F55、F56、F61、F62、坏档容错（F66–F69、F27）、G2、G4、G6、G27–G30 | 先抽出公共的原子写工具 |
| **批 4** | 安全规则口径（需裁决） | F2、F4、F5、F3、F7、F63、F1、G19、F6、F8、G17、G18、G14、G15、G16、G21–G26、F9、F10 | 部分与 AUDIT_2026-10-25 的领域裁决联动 |
| **批 5** | 隐私守卫与仓库卫生 | F31、F33、F35、F36、F37、F32、F38、F39、F90、F92、F93 | F90 涉及不可逆的历史重写 |
| **批 6** | 配置、识图、检索、周报、前端、性能、测试 | F24、G12、G9、F25、F26、F11、F12–F18、F20、F16、F23、F28–F30、F58、F59、F73、F75–F81、F82、F83、F84–F88、F89、G3 | F84：门禁类分支几乎没有测试；F85：测试会读写真实的 `records/` 目录，建议优先修 |

> **测试方面需要特别注意 F85**：`tests/test_web_app.py` 的 client 夹具没有传 `data_root`，会读取甚至改写主人真实的 `records/` 目录，测试结果也会因此取决于真实数据。修复期间跑测试前，建议先修这一条，或者在隔离环境中运行。

---

## 7. 需要主人裁决的事项

1. **F22 默认端点**：是否保留内置的 DashScope 默认端点（CHANGELOG v1.4.11 的定策）。最小修复（运行时读取 `.env`）不需要改变这个决策。
2. **「误判 / 保留警示」的语义**（G21–G25）：
   - 「保留」是否落盘？
   - 「误判」是否必须同时修改观察值，并留下审计记录？
   - 修正观察值后，红线能否撤销？
   - 能否逐条裁决？
3. **F90 公开历史**：是否用 `git filter-repo` 重写历史、force push，并请 GitHub Support 清理缓存。这一步不可逆，会影响所有已有的 clone。如果不重写，应在 KNOWN_ISSUES 中如实登记「真实病案在可达历史中」。
4. **F55「恢复原始」的含义**：恢复到首次修正前、上一版，还是让用户选？是否提供撤销？
5. **F2 报告的 LOW 检测范围**：只检测「方剂建议」小节还是全文？需要避免误报合规的「方剂类别方向」。
6. **G1 修复后的历史数据**：已有向导记录 `_raw` 中头面、目、耳、手 4 维的数据，是否迁移。
7. **F92 / F93**：手册例图是否加 AI 生成声明；许可证声明（`web/` 等目录没有明确许可，知识库「禁止再分发」却放在公开仓库里）。
8. **如果曾运行过 `backup_to_oss.sh`**（F34）：检查 OSS 上的备份包，并轮换其中的 API key 和管理口令。

---

## 8. 已检查但排除的方向

完备性评审在工作副本中实测后，确认以下方向没有问题，不必再查：

- `web/design/dev-server.js` 的路径穿越：`path.normalize` 会把路径限制在根目录内，而且 Flask 不托管这个目录，部署后访问不到。
- 外部 CDN 资源：模板中没有外链，echarts 5.6.0 已经 vendor 到本地。
- 正则 ReDoS：mdmini、scoring、validator 中的正则都没有回溯爆炸。
- Windows 编码：GBK 或 cp1252 下，stderr 输出 emoji 告警不会让请求 500。
- 形状 A / C 记录的整站冒烟测试：首页、详情、趋势全部返回 200。
- 静默吞错：只有少量 `except: pass`，都有正当理由。F28（红线探测异常被吞）是例外，已单独列出。

---

## 9. 产物与复现材料

| 产物 | 位置 |
|---|---|
| 本报告 | `docs/REVIEW_bonesyear_v1.8.34_2026-10-26.md`（未提交到 git） |
| 逐条详情附录 | `docs/REVIEW_bonesyear_v1.8.34_2026-10-26_appendix.md` |
| 结构化原始结果（JSON，含三视角完整理由） | `/private/tmp/claude-501/-Users-yuanmingchen-Desktop-cs-tcm-tongue-system/d17e0b36-8eed-4cff-9d1c-06a28a901b59/scratchpad/wf_result.json` |
| 复现脚本与工作副本 | `/private/tmp/claude-501/-Users-yuanmingchen-Desktop-cs-tcm-tongue-system/d17e0b36-8eed-4cff-9d1c-06a28a901b59/scratchpad/work/`（临时目录，可能被清理） |
| 被审查的克隆（未改动，474 测试全绿） | `/private/tmp/claude-501/-Users-yuanmingchen-Desktop-cs-tcm-tongue-system/d17e0b36-8eed-4cff-9d1c-06a28a901b59/scratchpad/src/bonesyear` |

> 注意：本地仓库 `yuanmingchen922/tcm-zhongyi`（v1.3.3）与 bonesyear 仓库的历史互不相关。本报告针对的是 bonesyear 的 v1.8.34，修复也应在 bonesyear 仓库（或它的分支 / fork）上进行。
