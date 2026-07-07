# 开发计划

> 本文档记录开发进度和待办任务，每次新会话从这里开始，了解当前状态。
> 关键设计决策见各设计文档，本文档只跟踪实现进度。

---

## 项目概览

三层架构的数据分析平台：
- **后端**（Python + FastAPI）：解析录包 → proto 时间序列 → HTTP Query API
- **插件层**（Python 脚本）：查询后端数据，转换为前端可视化格式，或做数据分析
- **前端**（Vue 3 + TypeScript）：渲染 VizChunk（回放）和 PluginResult（分析结果）

设计文档索引：
- `ARCHITECTURE.md` — 三层架构总览，**先读这个**
- `BACKEND_DESIGN.md` — 后端详细设计（目录结构、接口定义、数据流）
- `PLUGIN_SYSTEM.md` — 插件系统设计（Manifest、注册表、api 工具箱）
- `DESIGN.md` — 平台整体设计理念
- `PLATFORM.md` — 三大平台（数据/项目/人员管理）功能规划

---

## 当前进度

### 已完成

- [x] 所有设计文档编写完成
- [x] `backend/` 目录结构创建完成（所有文件夹和空文件）
- [x] `backend/parsers/base.py` — 公共数据结构 + IPC 协议 + 抽象接口
  - `FieldDef` / `TopicSchema` / `TopicFrame` / `RecordingMeta`
  - `ParserCommand` / `ParserResponse`
  - `AbstractParser` 抽象基类
  - `run_subprocess_loop()` 子进程通用主循环
- [x] `backend/parsers/manager.py` — 子进程管理器
  - 按需启动子进程，长期复用
  - 崩溃自动重启并恢复加载状态
  - 线程安全（每格式一把锁）
  - `load()` / `get_frames()` / `get_schema()` / `shutdown()`

---

## 待开发任务

### 阶段一：后端解析层

解析器按格式独立，每种格式一个子进程，proto 不互相干扰。

- [ ] **`parsers/db3/parser.py`**
  - 继承 `AbstractParser`
  - 用 `sqlite3` 读取 db3 文件（SQLite 格式）
  - 扫描所有 topic 表，建立时间戳索引
  - `load()` 返回 `RecordingMeta`
  - `get_frames()` 按时间范围 yield `TopicFrame`
  - `get_schema()` 从 proto descriptor 生成 `TopicSchema`

- [ ] **`parsers/db3/converters/`**
  - `obstacle.py` — obstacle proto → dict
  - `laneline.py` — laneline proto → dict
  - `odometry.py` — odometry proto → dict
  - 每个 converter 函数签名：`convert(proto_msg) -> dict`

- [ ] **`parsers/db3/__main__.py`**
  - 三行代码：实例化 `Db3Parser`，调用 `run_subprocess_loop()`

- [ ] **`parsers/db4/`** — 结构同 db3，但 proto 不同
  - `parser.py` / `converters/` / `__main__.py`

- [ ] **`parsers/noah_txt/`** — 文本格式解析
  - `parser.py` / `converters/` / `__main__.py`

> **注意**：proto .pb.py 文件需要从现有后端 `visualization-backend` 复制或重新生成。
> 参考路径：`/media/edward/MAPLOC/code/git/github/autonomous-driving-visualization/visualization-backend/drivers/`

---

### 阶段二：后端存储层

- [ ] **`store/time_index.py`**
  - 内存中按 topic 分类、按时间戳排序存储 `TopicFrame`
  - 用 `sortedcontainers.SortedList` 做时间索引
  - `add(frame)` — 写入一帧
  - `query_range(topic, t_from, t_to)` — 时间范围查询（最常用）
  - `query_nearest(topic, t)` — 最近帧
  - `query_before(topic, t, n)` / `query_after(topic, t, n)` — 前后 n 帧
  - `get_topics()` / `get_time_range()` / `get_frame_count(topic)`

- [ ] **`store/recording.py`**
  - 管理多个录包，每个录包对应一个 `TimeIndex`
  - `load(path)` — 调 `ParserManager` 解析，写入 `TimeIndex`，返回 `recording_id`
  - `get_index(recording_id)` — 返回对应 `TimeIndex`
  - `list_recordings()` — 所有已加载录包的元信息
  - `unload(recording_id)` — 从内存中释放

- [ ] **`store/annotations.py`**
  - 存储 topic / 字段的语义注解（人类备注 + AI 推断）
  - `add(topic, field, annotation)` / `get(topic, field)` 
  - 持久化到 SQLite 文件（重启不丢失）

---

### 阶段三：后端 HTTP API

- [ ] **`app/config.py`**
  - 端口、数据目录、插件目录、超时配置等

- [ ] **`app/main.py`**
  - FastAPI 应用初始化
  - 注册路由
  - 启动时扫描插件目录，加载注册表
  - 关闭时调用 `ParserManager.shutdown()`

- [ ] **`app/api/recordings.py`**
  - `GET  /api/recordings` — 列出所有已加载录包
  - `POST /api/recordings/load` — 加载录包文件
  - `DELETE /api/recordings/{id}` — 卸载录包

- [ ] **`app/api/series.py`**
  - `GET /api/recordings/{id}/topics` — topic 列表及时间范围
  - `GET /api/recordings/{id}/series/{topic}?from=&to=` — 时间范围帧数据
  - `GET /api/recordings/{id}/frame/{topic}?t=` — 最近单帧
  - `GET /api/recordings/{id}/frame/{topic}/before?t=&n=` — 前 n 帧
  - `GET /api/recordings/{id}/frame/{topic}/after?t=&n=` — 后 n 帧

- [ ] **`app/api/schema.py`**
  - `GET /api/recordings/{id}/schema/{topic}` — 字段结构
  - `GET /api/annotations/{topic}` — 语义注解
  - `POST /api/annotations/{topic}` — 新增注解

- [ ] **`app/api/plugins.py`**
  - `GET  /api/plugins` — 注册表插件列表
  - `GET  /api/plugins/{name}` — 插件完整 manifest
  - `POST /api/plugins/run` — 执行插件，返回 task_id
  - `GET  /api/plugins/tasks/{task_id}` — 查询任务状态
  - `WS   /ws/plugins/tasks/{task_id}` — 实时进度推送

---

### 阶段四：插件运行时

- [ ] **`app/plugin_runtime/registry.py`**
  - 扫描 `plugins/builtin/` 和 `plugins/user/` 目录
  - 读取每个插件的 `manifest.json`
  - 提供插件查询和脚本加载接口

- [ ] **`app/plugin_runtime/api_context/data.py`**
  - `ApiContext` 类，持有 `RecordingStore` 引用
  - `get_timeseries(recording_id, topic, time_range)` → `list[dict]`
  - `get_frame(recording_id, topic, t)` → `dict`
  - `get_schema(topic)` → `dict`
  - `get_annotations(topic)` → `list[dict]`
  - `list_topics(recording_id)` → `list[str]`
  - `progress(ratio, message)` — 推送进度到前端

- [ ] **`app/plugin_runtime/api_context/index.py`** — 时间索引工具
  - `nearest` / `before` / `after` / `range` / `context` / `align`

- [ ] **`app/plugin_runtime/api_context/stats.py`** — 统计工具
  - `mean` / `std` / `percentile` / `zscore` / `rolling_mean` / `histogram`

- [ ] **`app/plugin_runtime/api_context/anomaly.py`** — 异常检测
  - `threshold` / `zscore` / `iqr` / `sudden_change` / `merge_segments`

- [ ] **`app/plugin_runtime/api_context/error.py`** — 误差分析
  - `rmse` / `mae` / `mape` / `per_frame` / `percentile_error`

- [ ] **`app/plugin_runtime/api_context/timeseries.py`** — 时序处理
  - `diff` / `smooth` / `resample` / `correlation`

- [ ] **`app/plugin_runtime/runtime.py`**
  - 用 `RestrictedPython` 在沙箱中执行插件脚本
  - 注入 `ApiContext` 对象
  - 超时控制（默认 120s）、内存限制
  - 任务状态管理（running / done / error）
  - 结果通过 WebSocket 推送到前端

---

### 阶段五：内置插件

每个插件包含 `plugin.py`（实现）和 `manifest.json`（说明书）。

- [ ] **`plugins/builtin/ego_viz/`**
  - 自车位姿和历史轨迹可视化
  - 最简单，用于跑通整个链路

- [ ] **`plugins/builtin/obstacle_viz/`**
  - 障碍物（car/truck/pedestrian/cyclist）可视化
  - 输出 CUBE 类型 VizObject

- [ ] **`plugins/builtin/lane_line_viz/`**
  - 视觉感知车道线可视化
  - 输出 POLYLINE 类型 VizObject，支持各种线型

---

### 阶段六：前端

> 前端参考现有代码：
> `/media/edward/MAPLOC/code/git/github/autonomous-driving-visualization/visualization-frontend`
> 现有代码已有完整的 2D/3D 渲染能力，可以直接复用。

- [ ] **`frontend/`** 目录结构搭建（Vue 3 + TypeScript + Vite）

- [ ] **VizChunk 渲染（回放视图）**
  - 接收插件返回的 `VizChunk[]`，缓存到本地
  - 时间轴 + 进度条（用户拖动 → 从缓存取对应帧）
  - 复用现有 `Canvas2DRenderer`（2D 鸟瞰）
  - 复用现有 `World` + 各 Renderer（3D 场景）

- [ ] **PluginResult 渲染（分析视图）**
  - 图表（ECharts）：line / bar / scatter / pie / heatmap
  - 表格
  - 告警卡片
  - 报表布局（12 列网格，stat / chart / table / divider）
  - 文字摘要

- [ ] **插件管理 UI**
  - 插件列表（从注册表获取）
  - 参数填写表单（根据 manifest.run_params 自动生成）
  - 任务进度展示
  - 结果展示页

---

## 推荐开发顺序

```
parsers/db3/  →  store/time_index  →  store/recording
      ↓
app/main + app/api/  →  端到端测试（能查到数据）
      ↓
plugin_runtime/api_context/  →  runtime.py
      ↓
plugins/builtin/ego_viz  →  跑通插件完整链路
      ↓
前端接入，渲染第一个插件结果
      ↓
补齐其他解析器 / 插件 / 前端功能
```

**关键里程碑**：能从一个 db3 文件，通过插件，在前端看到车道线和障碍物可视化。

---

## 技术栈速查

| 层 | 语言 | 主要库 |
|----|------|--------|
| 后端解析 | Python 3.11+ | `sqlite3`, `google-protobuf` |
| 后端服务 | Python 3.11+ | `fastapi`, `uvicorn`, `sortedcontainers` |
| 插件运行时 | Python 3.11+ | `RestrictedPython` |
| 前端 | TypeScript | `Vue 3`, `Three.js`, `ECharts`, `pinia` |

启动命令：
```bash
cd backend
uvicorn app.main:app --reload --port 8080
```

---

## 关键文件快速定位

| 想了解什么 | 看哪里 |
|-----------|--------|
| 整体三层架构 | `ARCHITECTURE.md` |
| 后端接口定义 | `BACKEND_DESIGN.md` § 五 |
| 插件如何写 | `PLUGIN_SYSTEM.md` § 四 |
| VizObject 格式 | `ARCHITECTURE.md` § 三 |
| 数据流从文件到前端 | `BACKEND_DESIGN.md` § 七 |
| 子进程 IPC 协议 | `parsers/base.py` |
| 子进程管理 | `parsers/manager.py` |
