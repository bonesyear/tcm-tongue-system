# 知识检索架构设计（Grep + 别名词典 + 可选 RAG）

> 状态：已决策并实现（2026-07-03）。本文记录设计阶段对每个关键决策的自我质疑（grilling）与结论。
> 原则：**Grep 做主路径，RAG 做补充路径，不是反过来。**

> **2026-07-12 实现更新**（见 docs/CODE_REVIEW_2026-07-12.md Bug 6）：
> 1. **KB 规模前提已变**：设计时 5 个内容文件共 1752 行；现含
>    全文约 10800 行。实测纯 grep 单查询全库约 1-2ms（文件行缓存生效后更快），
>    决策 2（纯 Python re，不引 ripgrep）仍然成立。
> 2. **决策 8 的 TF-IDF 兜底已重写为纯 Python 倒排索引**：原 numpy 稠密矩阵
>    在现 KB 规模下为 4498 chunk × 33613 词表 ≈ 605 MB（峰值 RSS 1.28 GB），
>    倒排化后峰值 RSS ≈ 85 MB，且不再依赖 numpy（RAG 兜底恒可用）。
> 3. **dispatcher 新增 RagSearch 进程内缓存**（按 kb_root 键）：原实现每次
>    低命中查询新建实例重建索引（~0.4s/次），现首查建一次、后续 ~1ms。
>    注意：进程存活期间 KB 内容变更不触发索引重建。
> 4. **包结构变更**：src/ 已成为常规 Python 包，tests/conftest.py 注入的
>    是仓库根 + scripts/（不再是 src/），统一为 `from src.retrieval import ...`
>    风格——决策 12 中"conftest 把 src/ 加入 sys.path、`from retrieval
>    import retrieve` 可用"的描述已过时，仅作历史记录保留。
> 5. **TCM_KB_ROOT 对 grep 与 RAG 同时生效**（原仅 grep 读该变量，设置后
>    retrieve() 会混合两个知识库的结果）；kb_root/TCM_KB_ROOT 为部署配置，
>    不应来自用户输入。
>
> **2026-10-28 B17 更新**：grep、RAG 与别名词典共用 `kb_paths` 的仓库根相对
> 绝对路径；词典默认读取当前知识库根的 `synonym_map.yaml`。RAG 实例缓存与
> 索引构建加锁，模块级入口与 dispatcher 共享实例；外部手工修改知识库内容仍不
> 自动重建索引，ZIP 导入/回滚则显式调用 `invalidate_kb_caches()` 清理该根缓存。
> 非 UTF-8 文件和不可用词典告警并降级，词典按 UTF-8 BOM 兼容、
> 字符串标量解析。TF-IDF 仅作词法补充：多词查询至少命中一个多字符 token，
> 且余弦不低于 0.2；embedding 同样采用 0.2 下限。AND 的 RAG 补充按真实文件
> 再核验全部展开条件并过滤低分，不返回只含部分词的文件。分隔线不生成 chunk，
> 超长行按 500 字切分，摘录指向 token 重合度最高的真实正文行。TF-IDF 不再
> 对无词法重合的概念查询强行给出结果；需要真正语义召回时可配置本地 embedding。
>
> **2026-11-03 运行链修复**：`inspect_kb()` 统一未配置、空库、可用和错误状态，
> 并用路径、大小和 mtime_ns 生成轻量版本签名。Web 报告从同次配置快照显式传入
> `kb_root`，保存状态/根/版本；换库使报告过期，准备期间版本变化则拒绝混合生成。
> 报告中的条文只是候选参考，单条/总长度受限，不能宣称均为模型实际引用。
> 本地速览的项目内置映射不属于当前知识库检索，两者不得混称。
>
> **2026-11-03 分类扩展**：`inspect_kb_categories()` 分别解析体质、食疗和方剂根，
> 专用变量优先，旧综合库只作同类回退。各类独立导入、检索、保存状态和版本；
> 缺体质库隐藏体质/辨证，缺食疗库隐藏饮食，缺方剂库隐藏方药及完整方药报告。
> 缺体质或方剂时保守隐藏全案，不切割自由 Markdown 冒充可靠的类别过滤。
>
> **2026-11-03 硬化**：分类 ZIP 用 `kb.yaml` 声明类别；`TCM_KB_STRICT_CATEGORIES=1`
> 禁止综合回退。综合导入保留分类子目录，配置写回失败同时恢复配置和目录。
> 缺方剂的方名/剂量、缺食疗的结构化饮食、缺体质的结构化辨证在写入前拒绝。
> 词典最多 512 键、每键 64 项、单词条 128 字，避免无界正则展开。
>
> **2026-11-03 重置**：分类重置只处理程序管理副本，`TCM_KB_<类别>_DISABLED=1`
> 优先于综合库回退；新 ZIP 校验后替换旧副本并解除停用。配置事务按快照字节恢复，
> 避免新增空键或文件内容未真正还原。外部原库不作为重置目标。

## 0. 背景与约束

- 知识库现状：`knowledge_base/` 下 5 个内容 md 文件（共 1752 行），辨证时全量注入 LLM 上下文。需升级为可检索。
- 现有代码约定：`src/` 仅用标准库；模块带详尽中文 docstring；`tests/conftest.py` 把 `src/` 与 `scripts/` 加入 `sys.path`；pytest 9.1。
- 环境实测：PyYAML 6.0.3 已装（但未声明在 requirements.txt）、numpy 2.4.6 已装、sentence-transformers/faiss **未装**、ripgrep 已装。
- 硬约束：不改动 5 个知识库 md 内容；新代码全部放 `src/retrieval/`；Python 3；无新增外部依赖（RAG 层可选 sentence-transformers/faiss 除外）；每模块配测试；模块间接口清晰、不循环依赖。

## 1. 架构总览

```
                         ┌─────────────────────┐
   临床查询 "便软"  ───▶  │  dispatcher.retrieve │  统一入口
                         └──────────┬──────────┘
                    ① expand        │        ③ (命中<3 且 RAG 可用) 补充
              ┌─────────────────────┘        └──────────────┐
              ▼                                              ▼
   ┌─────────────────────┐                       ┌─────────────────────┐
   │  synonym_loader     │  ② pattern            │     rag_search      │
   │  expand(query)      │────────▶  ┌──────────┐│  (骨架，deps 未装    │
   │  → pattern/terms    │           │ grep_    ││   时 is_available    │
   └─────────────────────┘           │ search   ││   =False，返回 [])  │
        leaf，无内部依赖               │ .search  │└─────────────────────┘
                                      │ (pattern)│   leaf，无内部依赖
                                      └────┬─────┘
                                           ▼
                                   全文 .md 行号命中
                                   file/line/content/context
```

依赖图（无环）：
```
synonym_loader  (leaf)
grep_search     (leaf)
rag_search      (leaf)
dispatcher      → synonym_loader, grep_search, rag_search
__init__        导出四者公共 API
```

## 2. 关键决策（grilling 结论）

### 决策 1：YAML 解析——依赖 PyYAML 还是手写？

- **质疑**：PyYAML 不在 requirements.txt；硬依赖它违反"无新增外部依赖"。
- **结论**：`synonym_loader` 内 `try: import yaml`；可用则用，不可用则回退到手写解析器（只支持本文作者写死的受限子集：顶层 `key:` + 缩进 `- 项` 的 block 序列，无 flow/锚点/引号）。这样既享受已装 PyYAML 的稳健，又保证未装环境不崩。**不把 PyYAML 加进 requirements.txt**（保持声明依赖不变）。
- **代价**：手写解析器只认一种格式 → 在 yaml 文件顶部注释里写明格式约束。

### 决策 2：Grep 引擎——ripgrg 还是 Python re？

- **质疑**：rg 已装且快；但子进程+跨平台+额外依赖。
- **结论**：纯 Python `re`。知识库仅 1752 行，逐行 `re.search` 亚毫秒级。零外部进程、零新依赖、Windows 也能跑。rg 留作未来优化项，不引入。

### 决策 3：grep_search 接 `query` 还是 `pattern`？别名词典展开放哪？

- **质疑**：任务给的 grep API 是 `search(query)`，又说"输入查询词之前先经别名词典展开"。若 grep_search 内部自己展开，则与 dispatcher 的展开重复（接口污染）；若不展开，`search("便软")` 直调会 0 命中（不直观）。
- **结论**：**展开只在一个地方做**——`synonym_loader.expand()`。`grep_search.search(query)` 是**纯 grep 原语**，`query` 即 grep 正则模式（单术语如 `"太阴水饮"` 也是合法模式）。dispatcher 调 `expand()` 拿到 pattern，再调 `grep_search.search(pattern)`。这样：
  - grep_search 不依赖 synonym_loader（leaf，可独立测试）；
  - dispatcher 是唯一编排点，无重复展开；
  - 直查标准术语 `search("苓桂术甘汤")` 立即可用；
  - 查临床口语词走 `dispatcher.retrieve("便软")` 或手动 `search(expand("便软").pattern)`。
- **取舍**：牺牲"`search()` 自动展开"的便利，换接口纯净。值。

### 决策 4：同义词 OR 模式必须 re.escape

- **质疑**：术语里若含正则元字符（如括号、点）会破坏匹配或误分组。
- **结论**：`expand()` 对每个术语 `re.escape()` 后再 `|` 连接。原查询词也一并 escape 后加入模式（任务示例 `"下利|溏泄|便软"` 中的"便软"即原词）。**关键正确性点**。

### 决策 5：匹配语义——子串还是整行？

- **质疑**：裸 `"红"` 会命中面红/红赤/淡红等大量噪声。
- **结论**：grep 返回**所有含任一术语的行**（子串匹配，`re.search`）。消歧是下游 LLM 的职责——grep 只提供证据，不下判断。别名词典把临床词映射到**特异多字术语**（如"小便黄赤"而非"黄"）来抑制噪声。这是 grep 的正确语义，与 scoring 模块的"最长子串匹配"职责不同（scoring 打分要消歧，grep 检索要全召回）。

### 决策 6：context 边界与去重

- **结论**：每条 grep 结果 = 一条匹配行（按 file+line 去重，一行命中多术语仍算 1 条）。`context` = `lines[max(0,l-3):l+4]`（前 3 + 匹配行 + 后 3），文件首尾自然截断。`content` 单独给匹配行文本（与 context 中间元素重复，但符合任务示例格式）。dispatcher 合并 RAG chunk 时改用行范围判重：仅当 chunk 整段均被 grep 覆盖才去除，保留段内尚未覆盖的补充证据（2026-10-26）。

### 决策 7：dispatcher 路由阈值

- **结论**：`GREP_MIN_HITS = 3`（命名常量，可调）。命中数 = grep 结果条数。
  - `>= 3` → `method="grep"`，不调 RAG。
  - `< 3` 且 RAG 可用 → 合并 grep+rag，`method="both"`（grep==0 时 `"rag"`）。
  - `< 3` 且 RAG 不可用 → `method="grep"`，诚实返回少量命中。
  - `== 0` 且 RAG 不可用 → `method="grep"`，`results=[]`。

### 决策 8：RAG 骨架如何不破坏 import？

- **质疑**：sentence-transformers/faiss 未装；若模块级 `import`，则 `import rag_search` 崩，连带 dispatcher 崩。
- **结论**：**惰性导入**——`is_available()` 内部才 `import`，模块顶层零外部依赖。`search()` 未就绪时返回 `[]`。dispatcher 永远能 import rag_search，靠 `is_available()` 决定是否用。骨架结构完整（`build_index` 文档化 chunk=段落+章节标题元数据、存储=FAISS 优先/numpy 余弦兜底），但当前返回空。

### 决策 9：KB 文件发现与路径解析

- **结论**：`kb_paths` 统一解析知识库根与词典路径。可由函数参 `kb_root=` 或环境变量 `TCM_KB_ROOT` 覆盖；相对路径按仓库根归一，避免随当前工作目录混库。文件发现使用递归 `os.scandir`，默认排除 `README.md`（元文档），逐文件容错。测试用 `tmp_path` 注入临时 KB。

### 决策 10：AND/OR 组合查询

- **结论**：OR 由 `search(pattern)` 天然支持（正则 `|`，或别名词典展开）。AND 提供 `search_and(terms)`：只返回**同时含全部术语的文件**中各术语的命中行，支撑跨条文鉴别（如"苓桂"AND"五苓"）。
- **补充（2026-10-26）**：`retrieve()` 先 trim；串首/串尾或连续 AND 抛 `ValueError`，不再静默退化为普通词。`retrieve` 层 grep 与 RAG 统一 ASCII 大小写不敏感；底层原始正则 `search()/search_and()` 的默认大小写语义不变。

### 决策 11：原文行号溯源

- **结论**：grep 结果 `line` = md 文件内 1-based 行号（定位 KB 段落）；匹配行 `content` 中常含 `（Lnnn）` 原书行号引用（任务要求"原文行号溯源"由内容自带）。两者天然都有，无需额外处理。

### 决策 12：包内导入用相对导入

- **结论**：`src/retrieval/` 是子包，内部用相对导入 `from .synonym_loader import expand`。`tests/conftest.py` 已把 `src/` 加进 `sys.path`，故 `from retrieval import retrieve` / `from retrieval.grep_search import search` 均可用。与现有 `from dimensions import ...`（src 顶层平铺）风格不冲突。

## 3. 模块接口契约（写代码前确认）

### `synonym_loader.py`（leaf）
```python
@dataclass
class ExpandResult:
    query: str                 # 原查询
    pattern: str               # re.escape 后 OR 连接的正则，如 "便软|下利|便溏"
    terms: list[str]           # 全部检索词 = [原词] + 同义词
    synonyms_used: list[str]   # 实际生效的同义词（不含原词）；无则 []

def load_map(path: str | None = None) -> dict[str, list[str]]:
    """临床词 -> [标准术语]。YAML 解析（PyYAML 优先，回退手写）。"""

def expand(query: str, syn_map: dict | None = None) -> ExpandResult:
    """展开临床查询。query 非词典键时 pattern=re.escape(query)，synonyms_used=[]。"""
```

### `grep_search.py`（leaf，纯 grep）
```python
DEFAULT_KB_ROOT: str  # 由 __file__ 推导

def list_kb_files(kb_root: str | None = None, exclude: list[str] | None = None) -> list[str]:
def search(query: str, context_lines: int = 3, kb_root: str | None = None,
           case_sensitive: bool = True) -> list[dict]:
    """query 为 grep 正则模式。返回 [{"file","line","content","context"}]，按 file+line 去重。"""
def search_and(terms: list[str], context_lines: int = 3, kb_root: str | None = None) -> list[dict]:
    """AND：仅返回同时含全部 terms 的文件，附各 term 命中行。"""
```

### `rag_search.py`（leaf，骨架）
```python
class RagSearch:
    def __init__(self, kb_root: str | None = None): ...
    def is_available(self) -> bool: ...      # deps+索引就绪才 True
    def build_index(self) -> bool: ...        # 惰性 import；deps 缺失返回 False
    def search(self, query: str, k: int = 5) -> list[dict]: ...  # 未就绪返回 []

def is_available() -> bool: ...
def search(query: str, k: int = 5) -> list[dict]: ...  # 模块级便捷函数
```

### `dispatcher.py`（编排）
```python
GREP_MIN_HITS = 3
def retrieve(query: str, context_lines: int = 3, kb_root: str | None = None) -> dict:
    """返回 {"results","method","synonyms_used","grep_hits","rag_hits"}。"""
```

### `__init__.py`
导出：`retrieve`, `search`, `search_and`, `expand`, `load_map`, `ExpandResult`, `RagSearch`, `is_rag_available`。

## 4. 测试策略

- `test_synonym.py`：纯单元。`expand("便软")` 的 pattern 含 `下利`/`便溏`/`便软`；非词典键 `expand("太阴水饮")` 的 `synonyms_used==[]`、`terms==["太阴水饮"]`。
- `test_grep.py`：`tmp_path` 造临时 md，测基本命中、context 行数、文件首尾截断、OR 模式、AND、无命中 `[]`、正则元字符 escape、去重。加一条真实 KB 冒烟测试（`search("苓桂术甘汤")` 命中 formula-system.md）。
- `test_dispatcher.py`：临时 KB + monkeypatch `rag_search.is_available`，测三条路由（≥3、<3 无 RAG、<3 有 RAG）与 `synonyms_used` 透传。

## 5. 不做的事（YAGNI）

- 不引入 rg / 不加 PyYAML 到 requirements。
- 不实现 RAG 真实 embedding（骨架）。
- 不做查询结果排序打分（grep 按文件+行号自然序）。
- 不动 5 个知识库 md 内容。
