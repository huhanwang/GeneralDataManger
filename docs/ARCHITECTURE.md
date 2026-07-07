# 系统架构总览

> 三层独立，契约连接。后端只管数据，前端只管渲染，插件负责一切中间逻辑。

---

## 一、全局架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        后端 · 数据服务                           │
│                                                                 │
│   解析 db 文件 → proto 时间序列 → HTTP Query API                 │
│   不知道可视化，不知道分析逻辑，只管把数据查出来                   │
└───────────────────────────┬─────────────────────────────────────┘
                            │  HTTP  proto JSON / 时序数据
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│                        插件层 · 桥接与分析                        │
│                                                                 │
│   基础插件（库）：proto 对象 → VizObject                         │
│   组合插件（应用）：调用基础插件 + 分析逻辑 → PluginResult        │
│                                                                 │
│   插件注册表管理所有插件的能力说明，AI 读注册表写新插件            │
└──────────────┬──────────────────────────────┬───────────────────┘
               │  VizChunk（可视化数据）        │  PluginResult（分析结果）
               ↓                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                        前端 · 可视化平台                          │
│                                                                 │
│   回放视图：缓存 VizChunk，用户拖进度条查看场景演变               │
│   分析视图：渲染图表 / 表格 / 报表 / 时间轴标记                   │
│                                                                 │
│   不知道数据来自哪种传感器，只管渲染收到的对象和结果              │
└─────────────────────────────────────────────────────────────────┘
```

三层之间的契约：
- **后端 ↔ 插件**：HTTP Query API（proto JSON 格式）
- **插件 ↔ 前端**：VizChunk（场景数据）+ PluginResult（分析结果）

---

## 二、后端 · 数据服务

### 2.1 职责

- 解析 db3 / db4 / noah_txt 等格式，提取 proto 时间序列
- 按 topic key 存储，支持时间范围查询
- 对外暴露 HTTP Query API，返回 JSON 格式的 proto 数据
- 不包含任何可视化逻辑，不包含任何分析逻辑

### 2.2 HTTP Query API

```
# 录包管理
GET  /api/recordings
     → 所有录包列表（id, name, duration, topics）

GET  /api/recordings/{id}/info
     → 录包元信息 + 包含的 topic 列表

# Topic 数据查询
GET  /api/recordings/{id}/topics
     → 所有 topic key 列表 + 各自的 proto schema

GET  /api/recordings/{id}/series/{topic}?from=0&to=30
     → 时间范围内所有帧的数据（JSON 数组）
     → 每帧：{ t: number, data: proto字段展开的JSON }

GET  /api/recordings/{id}/frame/{topic}?t=45.2
     → 最近一帧的数据

GET  /api/recordings/{id}/schema/{topic}
     → proto 字段定义（字段名、类型、层级结构）
```

### 2.3 返回格式示例

```json
// GET /api/recordings/rec_001/series/laneline_list?from=40&to=42
[
  {
    "t": 40.0,
    "lanes": [
      { "id": 1, "type": "LINE_SOLID", "confidence": 0.92,
        "points": [[0,3.5],[5,3.6],[10,3.8]] },
      { "id": 2, "type": "LINE_DASHED", "confidence": 0.85,
        "points": [[0,-3.5],[5,-3.6],[10,-3.8]] }
    ]
  },
  { "t": 40.1, "lanes": [...] }
]
```

---

## 三、前端 · 可视化平台

### 3.1 职责

- 提供 2D 鸟瞰、3D 场景、图表、表格、时间轴等渲染能力
- 接收标准格式数据，按类型渲染，不含业务逻辑
- 不知道数据来自哪种传感器，不知道插件如何工作

### 3.2 接受的两类数据

**VizChunk（场景数据，用于回放视图）**

```typescript
interface VizChunk {
  from:    number       // 起始时间（秒）
  to:      number       // 结束时间（秒）
  objects: VizObject[]  // 该时段内所有对象
}

interface VizObject {
  id:         string      // 唯一标识，如 "lane:1" "obstacle:42"
  type:       ObjectType  // POLYLINE / CUBE / POLYGON / POINT_CLOUD / TEXT ...
  sub_type:   SubType     // LINE_SOLID / OBJ_CAR / ... （决定样式）
  valid_from: number      // 对象出现时间
  valid_to:   number      // 对象消失时间
  frames: {               // 每帧状态
    t:        number
    position: [number, number, number]
    rotation: [number, number, number]
    size:     [number, number, number]
    color:    [number, number, number, number]
    points?:  number[][]  // 折线 / 多边形的点列
  }[]
}
```

**PluginResult（分析结果，用于分析视图）**

```typescript
interface PluginResult {
  // 分析视图（总是存在）
  summary?:   string        // 文字结论
  charts?:    Chart[]       // 折线 / 柱状 / 散点 / 热力图 / 雷达图 ...
  tables?:    Table[]       // 数据表格
  alerts?:    Alert[]       // 告警卡片
  report?:    Report        // 报表布局（组合多个输出单元）

  // 回放视图（可选，有则展示）
  viz_chunks?: VizChunk[]   // 场景数据，有此字段才显示回放模块
  keyframes?:  Keyframe[]   // 时间轴标记点
}
```

### 3.3 前端模块结构

```
前端
│
├── 回放视图（可选模块，仅当 PluginResult 含 viz_chunks 时显示）
│   ├── 时间轴 + 进度条（用户拖动 → 从缓存取对应时刻场景）
│   ├── 2D 鸟瞰画布（Canvas 2D，渲染 VizObject）
│   ├── 3D 场景（Three.js，渲染 VizObject）
│   └── keyframe 标记（叠加在时间轴上）
│
└── 分析视图（始终存在）
    ├── 图表区（ECharts）
    ├── 表格区
    ├── 告警卡片
    ├── 文字摘要
    └── 报表布局（stat / chart / table / divider 网格组合）
```

### 3.4 ObjectType 与 SubType 枚举

前端渲染器按此枚举决定如何绘制，插件按此枚举描述对象：

```typescript
enum ObjectType {
  POLYLINE    = 3,   // 车道线、轨迹
  POLYGON     = 4,   // 区域、停车位
  CUBE        = 5,   // 障碍物、自车
  SPHERE      = 6,   // 点标记
  TEXT        = 7,   // 文字标注
  POINT_CLOUD = 1,   // 点云
  IMAGE       = 9    // 图像帧
}

enum SubType {
  // 车道线
  LINE_SOLID              = 1,
  LINE_DASHED             = 3,
  LINE_DOUBLE_SOLID       = 2,
  LINE_LEFT_SOLID_R_DASH  = 6,
  LINE_DOTTED             = 8,
  LINE_CURB               = 12,
  // 障碍物
  OBJ_CAR                 = 100,
  OBJ_PEDESTRIAN          = 101,
  OBJ_CYCLIST             = 102,
  OBJ_TRUCK               = 104,
}
```

---

## 四、插件层 · 桥接与分析

### 4.1 职责

- 从后端查询 proto 数据，转换为前端能渲染的 VizObject
- 对数据做分析计算，生成图表、报表、告警
- 插件之间可以互相调用，组合出复杂功能
- 插件注册表管理所有插件的能力说明，是 AI 的工具手册

### 4.2 插件的两种角色

```
基础插件（Library）                组合插件（Application）
────────────────────              ────────────────────────
专注一种数据对象的可视化            调用多个基础插件
对外暴露可复用函数                  加入自己的分析逻辑
也可以直接运行                      直接面向用户
                                    
lane_line_viz                      scene_overview
obstacle_viz          →  import →  map_comparison
ego_viz                            full_scene_replay
parking_slot_viz                   cpu_anomaly
```

### 4.3 插件文件结构

每个插件是一个 Python 文件，包含两部分：

```python
# ── lane_line_viz.py ──────────────────────────────────────

# Part 1：Manifest（机器可读的说明书）
PLUGIN_META = {
    "name":        "lane_line_viz",
    "version":     "1.0.0",
    "description": "将视觉感知车道线 proto 数据转换为可视化对象",
    "tags":        ["visualization", "perception", "lane"],

    "requires": {
        "proto_topics": ["laneline_list"],  # 需要后端提供的 topic
        "plugins":      []                  # 依赖的其他插件
    },

    # 对外暴露的函数（供其他插件 import）
    "exports": {
        "get_viz_objects": {
            "description": "返回指定时间范围内的车道线 VizObject 列表",
            "params": {
                "api":          "ApiContext",
                "recording_id": "string",
                "time_range":   "[number, number] | None"
            },
            "returns": "VizObject[]",
            "example": "lanes = lane_line_viz.get_viz_objects(api, 'rec_001', [0, 30])"
        }
    },

    # 用户直接运行时的参数表单（前端自动渲染）
    "run_params": [
        { "key": "recording_id", "type": "recording_picker", "label": "录包" },
        { "key": "time_range",   "type": "time_range",       "label": "时间范围", "optional": True },
        { "key": "color_by",     "type": "select",           "label": "颜色映射",
          "options": ["confidence", "line_type", "fixed"],   "default": "confidence" }
    ]
}

# Part 2：实现

def get_viz_objects(api, recording_id, time_range=None):
    """供其他插件调用"""
    frames = api.get_timeseries(recording_id, "laneline_list", time_range)
    objects = []
    for frame in frames:
        for lane in frame["lanes"]:
            objects.append({
                "id":         f"lane:{lane['id']}",
                "type":       "POLYLINE",
                "sub_type":   lane["type"],
                "valid_from": frame["t"],
                "valid_to":   frame["t"] + 0.1,
                "frames": [{
                    "t":      frame["t"],
                    "color":  confidence_to_color(lane["confidence"]),
                    "points": lane["points"]
                }]
            })
    return objects

def run(api, params):
    """用户直接运行的入口"""
    objects = get_viz_objects(api, params["recording_id"],
                              params.get("time_range"))
    return {
        "viz_chunks": [{"from": 0, "to": 999, "objects": objects}]
    }
```

### 4.4 组合插件示例

```python
# ── map_comparison.py ─────────────────────────────────────

PLUGIN_META = {
    "name":        "map_comparison",
    "description": "对比视觉车道线与地图车道线的横向偏差",
    "tags":        ["analysis", "lane", "map"],

    "requires": {
        "proto_topics": ["laneline_list", "hd_map_lanes"],
        "plugins":      ["lane_line_viz", "map_lane_viz"]   # 声明依赖
    },

    "exports": {},   # 组合插件通常不对外暴露函数

    "run_params": [
        { "key": "recording_id", "type": "recording_picker", "label": "录包" },
        { "key": "threshold",    "type": "number", "default": 0.3,
          "label": "偏差告警阈值(m)" }
    ]
}

# 直接 import，运行时注入同一个 api 实例
from registry import lane_line_viz, map_lane_viz

def run(api, params):
    rid       = params["recording_id"]
    trange    = params.get("time_range")
    threshold = params["threshold"]

    # 复用基础插件，不重写车道线可视化逻辑
    visual = lane_line_viz.get_viz_objects(api, rid, trange)
    mapped = map_lane_viz.get_viz_objects(api, rid, trange)

    # 对比计算
    diffs    = compute_lateral_offset(visual, mapped)
    exceeded = [d for d in diffs if d["offset"] > threshold]

    return {
        "viz_chunks": [{"from": 0, "to": 999,
                        "objects": visual + mapped + build_diff_overlays(diffs)}],
        "keyframes":  [{"t": d["t"], "severity": "warning",
                        "label": f"偏差 {d['offset']:.2f}m"} for d in exceeded],
        "charts":     [build_offset_chart(diffs, threshold)],
        "summary":    f"最大偏差 {max(d['offset'] for d in diffs):.2f}m，"
                      f"共 {len(exceeded)} 处超出阈值 {threshold}m"
    }
```

### 4.5 插件注册表

注册表是所有插件的目录，AI 读注册表了解有哪些能力可以调用：

```json
{
  "plugins": [
    {
      "name":        "lane_line_viz",
      "description": "视觉感知车道线可视化",
      "tags":        ["visualization", "lane"],
      "exports": [
        "get_viz_objects(api, recording_id, time_range?) → VizObject[]"
      ]
    },
    {
      "name":        "obstacle_viz",
      "description": "障碍物可视化，支持 car/truck/pedestrian/cyclist",
      "tags":        ["visualization", "obstacle"],
      "exports": [
        "get_viz_objects(api, recording_id, time_range?) → VizObject[]"
      ]
    },
    {
      "name":        "ego_viz",
      "description": "自车位姿与历史轨迹可视化",
      "tags":        ["visualization", "ego"],
      "exports": [
        "get_viz_objects(api, recording_id, time_range?) → VizObject[]",
        "get_trajectory(api, recording_id, time_range?) → Point[]"
      ]
    },
    {
      "name":        "map_comparison",
      "description": "视觉车道线与地图车道线横向偏差分析",
      "tags":        ["analysis", "lane"],
      "exports":     []
    }
  ]
}
```

### 4.6 api 对象：插件的工具箱

运行时向插件注入 `api` 对象，包含所有可用能力：

```python
api
│
├── # 后端数据查询（HTTP 调用，对插件透明）
│   api.get_timeseries(recording_id, topic, time_range) → frames[]
│   api.get_frame(recording_id, topic, t)               → frame
│   api.get_schema(topic)                               → schema
│   api.get_annotations(topic)                          → annotations
│   api.list_topics(recording_id)                       → topic[]
│
├── # 时间索引工具
│   api.index.nearest(frames, t)
│   api.index.before(frames, t, n)
│   api.index.after(frames, t, n)
│   api.index.range(frames, t1, t2)
│   api.index.align(frames_a, frames_b)    # 跨 topic 时间对齐
│
├── # 统计工具
│   api.stats.mean / std / percentile / zscore / rolling_mean ...
│
├── # 误差分析
│   api.error.rmse / mae / mape / per_frame ...
│
├── # 异常检测
│   api.anomaly.threshold / zscore / iqr / sudden_change / merge_segments ...
│
├── # 时序处理
│   api.timeseries.diff / smooth / resample / correlation ...
│
└── # 运行时工具
    api.progress(ratio, message)    # 推送进度到前端
    api.log(message)                # 调试日志
```

---

## 五、三层交互流程

### 5.1 用户运行一个插件

```
用户在前端选择插件 "map_comparison"，填写参数，点击运行
        ↓
前端 POST /plugin/run { name: "map_comparison", params: {...} }
        ↓
插件运行时启动 map_comparison 沙箱进程
注入 api 对象
        ↓
map_comparison 调用 lane_line_viz.get_viz_objects(api, ...)
        ↓
lane_line_viz 调用 api.get_timeseries("laneline_list", ...)
        ↓
api 内部 HTTP GET /api/recordings/rec_001/series/laneline_list
        ↓
后端返回 proto JSON 数据
        ↓
lane_line_viz 转换为 VizObject[]，返回给 map_comparison
        ↓
map_comparison 完成对比计算，return PluginResult
        ↓
运行时序列化结果，POST 回主服务
        ↓
主服务 WebSocket 推送到前端
        ↓
前端：有 viz_chunks → 显示回放视图（用户拖进度条查看场景）
      有 keyframes → 时间轴标记偏差点
      有 charts   → 显示偏差趋势图
      有 summary  → 显示文字结论
```

### 5.2 AI 写一个新插件

```
用户：帮我写一个展示完整感知场景的插件

AI 查询注册表，发现：
  lane_line_viz.get_viz_objects(api, recording_id, time_range) → VizObject[]
  obstacle_viz.get_viz_objects(api, recording_id, time_range) → VizObject[]
  ego_viz.get_viz_objects(api, recording_id, time_range)      → VizObject[]

AI 生成插件：
  from registry import lane_line_viz, obstacle_viz, ego_viz

  def run(api, params):
      rid    = params["recording_id"]
      trange = params.get("time_range")
      objects = (
          lane_line_viz.get_viz_objects(api, rid, trange) +
          obstacle_viz.get_viz_objects(api, rid, trange) +
          ego_viz.get_viz_objects(api, rid, trange)
      )
      return {"viz_chunks": [{"from": 0, "to": 9999, "objects": objects}]}

用户审核，保存到插件库
注册表自动更新，后续 AI 可继续组合此插件
```

### 5.3 插件之间的依赖关系

```
scene_overview
    ├── import lane_line_viz    → get_viz_objects()
    ├── import obstacle_viz     → get_viz_objects()
    └── import ego_viz          → get_viz_objects()

map_comparison
    ├── import lane_line_viz    → get_viz_objects()
    └── import map_lane_viz     → get_viz_objects()

full_perception_report
    ├── import scene_overview   → run()
    ├── import map_comparison   → run()
    └── 自己做汇总报表
```

同一次运行中，所有插件共享同一个 `api` 实例，数据查询走同一个连接，不重复建立。

---

## 六、职责边界总结

| 问题 | 谁负责 |
|------|--------|
| 这个 topic 的数据怎么查 | 后端 |
| proto 字段怎么解析 | 后端 |
| 这种对象怎么可视化 | 基础插件 |
| 这两种数据怎么对比分析 | 组合插件 |
| 分析结果怎么展示 | 前端 |
| 有哪些插件可以用 | 注册表 |
| 写一个新分析工具 | AI + 用户 |

**扩展新数据类型**：写一个基础插件，加入注册表，上层插件立即可以复用。

**扩展新分析能力**：写一个组合插件，import 已有基础插件，专注分析逻辑。

**前端和后端永远不需要改。**
