# 后端设计文档

> 后端只做一件事：把各种格式的录包数据解析出来，以时间序列的形式存储，
> 通过 HTTP API 供插件和前端查询。不包含任何可视化逻辑，不包含任何分析逻辑。

---

## 一、整体架构

```
录包文件（db3 / db4 / noah_txt / ...）
        ↓
┌───────────────────────────────────────┐
│           解析层（子进程隔离）           │
│                                       │
│  db3 子进程   db4 子进程   noah 子进程  │
│  各自加载     各自加载     各自加载     │
│  专属 proto   专属 proto   专属格式    │
└──────────────────┬────────────────────┘
                   │ 结构化 TopicFrame 数据
                   ↓
┌───────────────────────────────────────┐
│           通用处理层                   │
│                                       │
│  Store：时间索引 + 录包管理            │
│  API：HTTP Query 接口                 │
│  PluginRuntime：插件执行与调度         │
└──────────────────┬────────────────────┘
                   │ HTTP JSON
          ┌────────┴────────┐
          ↓                 ↓
     插件脚本           前端页面
```

---

## 二、目录结构

```
backend/
├── app/                            # 通用处理层
│   ├── main.py                     # FastAPI 应用入口
│   ├── config.py                   # 配置（端口、路径、超时等）
│   │
│   ├── store/                      # 数据存储与查询
│   │   ├── recording.py            # 录包注册与管理
│   │   ├── time_index.py           # 时间索引，核心查询逻辑
│   │   └── annotations.py          # 对象语义注解（人类 + AI）
│   │
│   ├── api/                        # HTTP 路由
│   │   ├── recordings.py           # /api/recordings
│   │   ├── series.py               # /api/recordings/{id}/series/{topic}
│   │   ├── schema.py               # /api/recordings/{id}/schema/{topic}
│   │   └── plugins.py              # /api/plugins
│   │
│   └── plugin_runtime/             # 插件执行引擎
│       ├── runtime.py              # 沙箱执行、进度推送
│       ├── registry.py             # 插件注册表读写
│       └── api_context/            # 注入插件的 api 对象
│           ├── data.py             # api.get_timeseries / get_frame 等
│           ├── index.py            # api.index.*
│           ├── stats.py            # api.stats.*
│           ├── anomaly.py          # api.anomaly.*
│           ├── error.py            # api.error.*
│           └── timeseries.py       # api.timeseries.*
│
├── parsers/                        # 解析层（每种格式完全隔离）
│   ├── base.py                     # 解析器公共数据结构定义
│   ├── manager.py                  # 子进程管理（启停、IPC 通信）
│   │
│   ├── db3/                        # db3 格式解析子进程
│   │   ├── __main__.py             # 子进程入口，监听 stdin 指令
│   │   ├── parser.py               # SQLite 读取 + proto 提取
│   │   ├── proto/                  # db3 专属 proto 生成文件（.py）
│   │   └── converters/             # proto message → TopicFrame
│   │       ├── obstacle.py
│   │       ├── laneline.py
│   │       └── odometry.py
│   │
│   ├── db4/                        # db4 格式解析子进程
│   │   ├── __main__.py
│   │   ├── parser.py
│   │   ├── proto/
│   │   └── converters/
│   │
│   └── noah_txt/                   # noah_txt 格式解析子进程
│       ├── __main__.py
│       ├── parser.py
│       └── converters/
│
├── plugins/                        # 插件脚本库
│   ├── builtin/                    # 内置基础插件（随后端发布）
│   │   ├── lane_line_viz/
│   │   │   ├── plugin.py
│   │   │   └── manifest.json
│   │   ├── obstacle_viz/
│   │   │   ├── plugin.py
│   │   │   └── manifest.json
│   │   └── ego_viz/
│   │       ├── plugin.py
│   │       └── manifest.json
│   └── user/                       # 用户 / AI 创建的插件（运行时写入）
│
├── tests/
│   ├── test_parsers/
│   ├── test_store/
│   ├── test_api/
│   └── test_plugins/
│
└── pyproject.toml
```

---

## 三、解析层设计

### 3.1 为什么必须子进程隔离

protobuf 在 Python 进程内使用全局注册表。不同格式的数据文件（db3、db4）可能包含同名的 proto message（如 `Obstacle`、`LaneLine`），同进程加载会导致注册冲突，数据互相覆盖。

子进程隔离保证每种格式在独立的 Python 进程中加载自己的 proto，完全不干扰。

### 3.2 公共数据结构（base.py）

解析层向通用层输出统一格式，通用层不感知具体文件格式：

```python
# parsers/base.py

@dataclass
class TopicFrame:
    """单个 topic 在某一时刻的一帧数据"""
    topic:     str        # topic 标识，如 "laneline_list"
    t:         float      # 时间戳（秒）
    data:      dict       # proto 反序列化后的字段字典
    raw:       bytes      # 原始 proto binary（按需保留）

@dataclass
class TopicSchema:
    """topic 的字段结构描述"""
    topic:   str
    fields:  list[FieldDef]   # 字段名、类型、描述

@dataclass
class ParseResult:
    """一次解析任务的完整结果"""
    recording_id: str
    duration:     float
    topics:       list[str]
    frames:       list[TopicFrame]
    schemas:      dict[str, TopicSchema]
```

### 3.3 子进程通信协议（manager.py ↔ __main__.py）

主进程通过 stdin/stdout 与子进程通信，消息格式为换行分隔的 JSON：

```
主进程发送指令：
{ "cmd": "parse", "path": "/data/rec.db3", "topics": ["laneline_list"] }
{ "cmd": "get_schema", "topic": "laneline_list" }
{ "cmd": "exit" }

子进程返回结果：
{ "status": "ok", "data": [ ...TopicFrame列表... ] }
{ "status": "ok", "data": { ...TopicSchema... } }
{ "status": "error", "message": "..." }
```

### 3.4 子进程生命周期

```
首次请求某格式（如 db3）
    ↓
ParserManager 启动 db3 子进程
    python -m parsers.db3
    ↓
子进程初始化，加载全部 proto 文件
    ↓
主进程发送解析指令
    ↓
子进程解析，返回 TopicFrame 列表
    ↓
子进程保持运行（复用，避免重复启动开销）

进程崩溃 → 自动重启，不影响主进程
后端退出 → 发送 exit 指令，子进程正常退出
```

### 3.5 Converter 职责

每种格式的 converter 负责把 proto message 转成通用的 `TopicFrame.data` 字典：

```python
# parsers/db3/converters/obstacle.py

def convert(proto_msg) -> dict:
    """obstacle proto → 通用字段字典"""
    return {
        "obstacles": [
            {
                "id":         obs.id,
                "x":          obs.pose.x,
                "y":          obs.pose.y,
                "heading":    obs.pose.heading,
                "w":          obs.size.width,
                "l":          obs.size.length,
                "h":          obs.size.height,
                "label":      obs.label,          # car/truck/pedestrian
                "confidence": obs.confidence,
            }
            for obs in proto_msg.obstacles
        ]
    }
```

通用层拿到的永远是普通 Python dict，不接触任何 proto 类型。

---

## 四、通用处理层设计

### 4.1 Store：时间索引（time_index.py）

核心数据结构：按 topic 组织，每个 topic 内按时间戳排序：

```python
# app/store/time_index.py

class TimeIndex:
    """
    存储结构：
    {
      "laneline_list": SortedList[(t, TopicFrame), ...],
      "obstacle_list": SortedList[(t, TopicFrame), ...],
      ...
    }
    所有查询操作均基于此结构，二分查找 O(logN)
    """

    def add(self, frame: TopicFrame): ...

    def query_range(self, topic: str,
                    t_from: float, t_to: float) -> list[TopicFrame]:
        """查询时间范围内所有帧"""

    def query_nearest(self, topic: str, t: float) -> TopicFrame:
        """查询最近一帧"""

    def query_before(self, topic: str, t: float, n: int) -> list[TopicFrame]:
        """查询 t 之前的 n 帧"""

    def query_after(self, topic: str, t: float, n: int) -> list[TopicFrame]:
        """查询 t 之后的 n 帧"""

    def get_topics(self) -> list[str]: ...
    def get_time_range(self) -> tuple[float, float]: ...
```

### 4.2 Store：录包管理（recording.py）

```python
# app/store/recording.py

class RecordingStore:
    """
    管理所有已加载的录包
    key: recording_id → TimeIndex
    """

    def load(self, path: str) -> str:
        """
        加载录包：
        1. 根据文件扩展名选择解析器
        2. 通过 ParserManager 调用子进程解析
        3. 将结果写入 TimeIndex
        4. 返回 recording_id
        """

    def get_index(self, recording_id: str) -> TimeIndex: ...
    def list_recordings(self) -> list[RecordingMeta]: ...
    def unload(self, recording_id: str): ...
```

### 4.3 注解系统（annotations.py）

存储对象类型的语义描述，供 AI 写插件时理解数据含义：

```python
# app/store/annotations.py

@dataclass
class Annotation:
    source:     Literal["human", "ai"]
    author:     str           # 用户名 或 AI 模型标识
    content:    str           # 自然语言描述
    confidence: float         # human=1.0，AI 按实际
    created_at: datetime

class AnnotationStore:
    def add(self, topic: str, field: str | None, ann: Annotation): ...
    def get(self, topic: str, field: str | None) -> list[Annotation]: ...
```

---

## 五、HTTP API 设计

所有接口均为 JSON，无状态，供插件和前端调用。

### 5.1 录包接口

```
GET  /api/recordings
     → 所有已加载录包列表
     [{ id, name, path, duration, topics[], loaded_at }]

POST /api/recordings/load
     body: { path: "/data/rec.db3" }
     → { recording_id, duration, topics[] }

DELETE /api/recordings/{id}
     → 从内存中卸载录包
```

### 5.2 数据查询接口

```
GET  /api/recordings/{id}/topics
     → topic 列表及各 topic 的时间范围和帧数
     [{ topic, t_from, t_to, frame_count }]

GET  /api/recordings/{id}/series/{topic}?from=0&to=30
     → 时间范围内所有帧
     [{ t, data: {...} }, ...]

GET  /api/recordings/{id}/frame/{topic}?t=45.2
     → 最近一帧
     { t, data: {...} }

GET  /api/recordings/{id}/frame/{topic}/before?t=45.2&n=5
     → t 之前 n 帧
     [{ t, data: {...} }, ...]

GET  /api/recordings/{id}/frame/{topic}/after?t=45.2&n=5
     → t 之后 n 帧
     [{ t, data: {...} }, ...]
```

### 5.3 Schema 与注解接口

```
GET  /api/recordings/{id}/schema/{topic}
     → topic 的字段结构
     { topic, fields: [{ name, type, description }] }

GET  /api/annotations/{topic}?field=confidence
     → topic 或某字段的注解列表
     [{ source, author, content, confidence, created_at }]

POST /api/annotations/{topic}
     body: { field, content, source: "human" }
     → 新增注解
```

### 5.4 插件接口

```
GET  /api/plugins
     → 注册表中所有插件的摘要列表
     [{ name, description, tags, exports[] }]

GET  /api/plugins/{name}
     → 插件完整 manifest
     { name, version, description, exports, run_params, requires }

POST /api/plugins/run
     body: { name, params: { recording_id, ... } }
     → 启动执行，返回 task_id
     { task_id }

GET  /api/plugins/tasks/{task_id}
     → 查询任务状态与结果
     { status: "running"|"done"|"error", progress, result }

WS   /ws/plugins/tasks/{task_id}
     → WebSocket 实时接收进度和结果推送
```

---

## 六、插件运行时设计

### 6.1 执行流程

```
POST /api/plugins/run
        ↓
PluginRuntime.submit(name, params)
        ↓
从注册表加载插件脚本文件
        ↓
启动受限 Python 环境（RestrictedPython）
注入 ApiContext 对象
        ↓
执行 plugin.run(api, params)
        ↓
插件调用 api.get_timeseries()
  → ApiContext 内部调用 RecordingStore.query_range()
  → 直接内存访问，无 HTTP 开销
        ↓
插件 return PluginResult 字典
        ↓
结果写入 TaskStore
通过 WebSocket 推送给前端
```

### 6.2 ApiContext（注入插件的 api 对象）

```python
# app/plugin_runtime/api_context/data.py

class ApiContext:
    """
    插件拿到的 api 对象。
    持有 RecordingStore 引用，所有数据查询在内存中直接完成。
    """

    def __init__(self, store: RecordingStore, task_id: str):
        self._store    = store
        self._task_id  = task_id
        self.index     = IndexTools()
        self.stats     = StatsTools()
        self.anomaly   = AnomalyTools()
        self.error     = ErrorTools()
        self.timeseries = TimeseriesTools()

    def get_timeseries(self, recording_id: str, topic: str,
                       time_range: tuple | None = None) -> list[dict]:
        index = self._store.get_index(recording_id)
        if time_range:
            frames = index.query_range(topic, *time_range)
        else:
            frames = index.query_range(topic, *index.get_time_range())
        return [f.data for f in frames]

    def get_frame(self, recording_id: str, topic: str, t: float) -> dict:
        return self._store.get_index(recording_id).query_nearest(topic, t).data

    def get_schema(self, topic: str) -> dict: ...
    def get_annotations(self, topic: str) -> list[dict]: ...
    def list_topics(self, recording_id: str) -> list[str]: ...

    def progress(self, ratio: float, message: str = ""):
        """插件主动推送进度"""
        push_progress(self._task_id, ratio, message)
```

### 6.3 插件安全限制

```python
# RestrictedPython 限制
BLOCKED_IMPORTS = {
    "os", "sys", "subprocess", "socket",
    "shutil", "pathlib", "importlib",
    "ctypes", "multiprocessing"
}

ALLOWED_IMPORTS = {
    "math", "statistics", "collections",
    "itertools", "functools", "datetime",
    "json", "re", "copy"
}

# 运行限制
TIMEOUT_SECONDS  = 120    # 超时自动终止
MEMORY_LIMIT_MB  = 512    # 内存上限
```

---

## 七、数据流总图

```
文件路径
  │
  ▼
ParserManager.parse(path)
  │ 根据扩展名选子进程
  ▼
db3/__main__.py（子进程）
  读 SQLite → proto binary
  → converters 转换
  → TopicFrame 列表
  → stdout JSON 返回
  │
  ▼
RecordingStore.load()
  写入 TimeIndex（内存，按 topic 按时间排序）
  │
  ├──── HTTP API ──────────────────────────────────────────────
  │     插件 / 前端通过 /api/recordings/{id}/series/{topic}
  │     直接查询 TimeIndex，返回 JSON
  │
  └──── PluginRuntime ─────────────────────────────────────────
        plugin.run(api, params)
        api.get_timeseries() → 直接读 TimeIndex（内存，零 HTTP）
        return PluginResult
        → WebSocket 推送前端
```

---

## 八、依赖与启动

### 8.1 主要依赖

```toml
# pyproject.toml
[project]
dependencies = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "protobuf>=4.25",
    "sortedcontainers>=2.4",   # 时间索引
    "RestrictedPython>=7.0",   # 插件沙箱
    "websockets>=12.0",
    "pydantic>=2.0",
]
```

### 8.2 启动

```bash
# 开发
uvicorn app.main:app --reload --port 8080

# 生产
uvicorn app.main:app --workers 4 --port 8080
```

启动时自动：
1. 扫描 `plugins/builtin/` 加载内置插件注册表
2. 扫描 `plugins/user/` 加载用户插件注册表
3. 不预启动解析子进程（按需启动）

---

## 九、各模块职责边界

| 模块 | 知道什么 | 不知道什么 |
|------|---------|-----------|
| `parsers/db3/` | db3 文件结构、db3 proto 定义 | 其他格式、HTTP、插件 |
| `parsers/db4/` | db4 文件结构、db4 proto 定义 | 其他格式、HTTP、插件 |
| `store/time_index.py` | 时间索引、查询算法 | 文件格式、proto、HTTP |
| `store/recording.py` | 录包生命周期管理 | 文件格式内部细节 |
| `api/` | HTTP 路由、请求响应格式 | 业务逻辑、文件格式 |
| `plugin_runtime/` | 插件执行、沙箱、进度推送 | 具体分析逻辑 |
| `api_context/` | 封装数据查询和工具函数 | 插件业务逻辑 |
| `plugins/builtin/` | 特定数据对象的可视化 | 后端实现细节 |
