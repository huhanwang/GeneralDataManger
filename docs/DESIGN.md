# 通用数据分析平台 设计文档

> 本文档记录平台的整体架构思路，供后续开发参考。

---

## 一、平台定位

一个**通用性数据管理与分析平台**，不绑定特定行业或数据格式。

核心能力：
- 各种格式的数据上传、管理、检索
- 通用可视化（点线面体图像文本等时间序列数据）
- 分析过程记录与团队协作
- 问题发现与流转（Issue 管理）

长期目标：让 AI 能接管人类的分析过程——平台先把人类的分析行为记录下来，再逐步用 AI 替代。

---

## 二、三大模块

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   数据管理       │  │   可视化分析     │  │   问题流转       │
│                 │  │                 │  │                 │
│ 上传 / 存储      │  │ 对象模型         │  │ Issue 创建       │
│ 标签 / 分类      │  │ Player + Viewer  │  │ 分配 / 跟踪      │
│ 检索 / 过滤      │  │ 分析会话记录     │  │ 状态流转         │
│ 版本管理         │  │ 配置驱动渲染     │  │ 关联数据锚点     │
└─────────────────┘  └─────────────────┘  └─────────────────┘
         │                    │                    │
         └────────────────────┴────────────────────┘
                        recording_id / object_id 串联
```

---

## 三、数据管理模块

### 3.1 存储结构

```
对象存储（MinIO / S3 / OSS）
  /recordings/
    {recording_id}/
      raw/            原始文件（db3、db4、noah_txt、csv、...）
      media/
        camera/       图像帧
        lidar/        点云帧

关系数据库（PostgreSQL）
  recording 表        元数据、标签、状态
  tag 表              标签体系
  object_type 表      对象类型注册表
```

### 3.2 Recording 元数据

```sql
recording {
  id          UUID
  name        STRING
  description TEXT
  format      ENUM(db3, db4, noah_txt, csv, viz_json, ...)
  size_bytes  BIGINT
  duration_s  FLOAT          -- 时长（秒）
  uploaded_by USER_ID
  uploaded_at TIMESTAMP
  status      ENUM(uploading, processing, ready, archived)
  tags        STRING[]        -- 标签数组
  meta        JSONB           -- 任意扩展字段
}
```

### 3.3 数据管理 UI 功能

- 上传（支持大文件分片上传）
- 列表视图（表格 + 卡片切换）
- 多维过滤（格式、标签、时间范围、上传者、状态）
- 全文搜索（name + description）
- 标签管理（创建、批量打标、标签树）
- 数据详情页（元数据 + 关联的可视化入口 + 关联 Issue）

### 3.4 两种部署模式

```
纯云模式（默认）
  用户上传原始文件 → 云端处理服务解析转换 → 前端可视化

本地客户端模式（可选，适合大数据量）
  本地客户端拉取原始文件（或直接读本地磁盘）
  本地处理转换 → 同一套 VizObject 格式
  前端连 localhost 使用
  分析记录同步到云端

关键：本地客户端和云端处理服务是同一套代码，不同部署位置
前端只认 API endpoint，不关心后端在哪里运行
```

---

## 四、核心数据模型：VizObject

### 4.1 设计原则

平台的核心抽象是**对象管理**，而非数据可视化。可视化只是对象属性的一种呈现方式。

把数据当成对象来管理，才能让 AI 自然介入——AI 和人类使用同一套对象接口。

### 4.2 对象结构

```typescript
type VizObject = {
  // 通用 Header（每种对象都有）
  header: {
    id:          string    // 格式: "{recording_id}:{type}:{local_id}"
    type:        string    // 对象类型，见类型注册表
    source: {
      recording_id: string
      parser:       string  // 哪个解析器产生的
      local_id:     string  // 原始数据中的本地 ID
    }
    valid_from:  number    // 对象存在的起始时间戳
    valid_to:    number    // 对象消失的时间戳
    confidence:  number    // 整体置信度
    tags:        string[]
  }

  // 静态属性（不随时间变化）
  static: Record<string, any>

  // 时间序列属性（随时间变化，每个属性独立索引）
  time_series: {
    [prop: string]: Array<{ t: number; v: any }>
  }
}
```

### 4.3 ID 设计

```
格式：{recording_id}:{type}:{local_id}

示例：
  rec_abc123:obstacle:42          录包中 track_id=42 的障碍物
  rec_abc123:lane_line:left_01    左侧车道线
  rec_abc123:ego:0                自车（始终唯一）
  session_xyz:annotation:001      用户创建的标注
  system:issue:2024001            系统 Issue
```

local_id 来自原始数据中的跟踪 ID（track_id），保证跨帧稳定。

### 4.4 几何属性类型

可视化的所有内容归结为以下基础类型：

```
point    (x, y, z?)              单点 / 位置
points   Array<[x, y, z?]>      点云 / 散点
line     Array<[x, y, z?]>      折线 / 轨迹
polygon  Array<[x, y, z?]>      多边形（自动闭合）
box      (x, y, w, h, heading)  有向包围盒（2D）
box3d    (x,y,z,w,h,d,roll,pitch,yaw)  3D 包围盒
circle   (x, y, r)              圆
arrow    (x, y, heading, len?)  方向箭头
text     (x, y, content)        文本标注
image    (url | binary)         图像帧
latlng   (lat, lng)             地理坐标
```

### 4.5 对象类型注册表

注册表是扩展的唯一入口，加一种新的对象类型只需加一条 JSON：

```json
{
  "type": "obstacle",
  "display_name": "障碍物",
  "properties": {
    "static": ["size"],
    "time_series": {
      "pose":     { "value_type": "box",     "description": "位姿" },
      "velocity": { "value_type": "vector2", "description": "速度", "unit": "m/s" },
      "label":    { "value_type": "enum",    "values": ["car","truck","pedestrian","cyclist"] },
      "confidence": { "value_type": "float", "range": [0, 1] }
    }
  },
  "default_view": {
    "canvas_2d": { "geometry": "pose", "color_by": "label" },
    "chart":     { "series": ["confidence"] }
  }
}
```

---

## 五、可视化分析模块

### 5.1 架构：两个模块 + 一种格式

```
VizSequence（通用时序格式）
        ↑
   数据处理层
        │
┌───────┴───────┐
Player          Viewer
（时间控制）     （渲染）
```

**Player**：只管时间轴（播放、暂停、seek、速度）。
**Viewer**：只管渲染（读 Config 决定怎么画）。
两者通过当前帧的对象快照交互，职责完全分离。

### 5.2 前端 Config 控制渲染

同一份数据，不同 Config，不同呈现。Config 是唯一需要修改的地方：

```json
{
  "object_types": {
    "obstacle": {
      "color": "#ff6b6b",
      "visible": true,
      "render": {
        "box":  { "show": true, "fill": "rgba(255,107,107,0.2)" },
        "line": { "show": true, "dashed": true },
        "text": { "show": true }
      }
    },
    "lane_line": {
      "color": "#58a6ff",
      "render": {
        "line": { "show": true, "width": 2 }
      }
    }
  }
}
```

用户改颜色、改显隐、改线宽，只动 Config，不碰数据，不碰代码。

### 5.3 数据加载策略

```
后端处理完成，返回 Manifest（各对象数据大小清单）
          ↓
前端对比 MAX_CACHE_SIZE（可配置，默认 500MB）
          ↓
     ┌────┴────┐
  总量 < 限制    总量 > 限制
     ↓               ↓
  全量加载       按对象大小分类
  一次请求         小对象：全量加载
  放入内存         大对象：滑动窗口加载
```

决策标准只有一个：**大小**，不按类型（图像/点云/车道线）区分。

### 5.4 DataSelection：用户先声明需求

```typescript
type DataSelection = {
  recording_id: string
  time_range:   [number, number]
  objects: {
    [type: string]: {
      enabled:    boolean
      properties: string[]    // 只加载需要的属性
    }
  }
}
```

用户先选择要用哪些数据，后端精确处理，不做多余工作。

### 5.5 分析会话记录

用户的每一个操作都是事件，用事件溯源模式记录：

```typescript
type AnalysisEvent =
  | { type: 'OPEN_DATA';    recording_id: string; t: number }
  | { type: 'SEEK_TO';      time: number }
  | { type: 'PAUSE_AT';     time: number; dwell_ms: number }
  | { type: 'ZOOM_IN';      area: BBox }
  | { type: 'ANNOTATE';     time: number; object_id: string; note: string }
  | { type: 'BOOKMARK';     time: number; label: string }
  | { type: 'CREATE_ISSUE'; time_range: [number, number]; description: string }
  | { type: 'COMPARE';      recording_a: string; recording_b: string }
```

一次分析会话 = 这些事件的时序列表。
后续 AI 可以学习"人类在什么情况下会发现问题"，逐步替代人工分析。

---

## 六、问题流转模块

### 6.1 使用 Plane（开源）

Issue 管理不自研，直接集成 [Plane](https://github.com/makeplane/plane)：

- 开源（AGPL），可自托管
- 现代 UI，类似 Linear
- 支持自定义字段（用于关联数据锚点）
- 完整 REST API，方便集成

### 6.2 Issue 的数据锚点

Issue 比普通任务多了数据侧的定位信息：

```json
{
  "title": "定位模块在弯道处漂移",
  "description": "...",

  // 自定义字段（Plane 支持）
  "recording_id":  "rec_abc123",
  "time_range":    [45.2, 52.8],
  "object_ids":    ["rec_abc123:ego:0"],
  "snapshot_url":  "https://...",        // 问题现场截图
  "algorithm_version": "v2.3.1"         // 出问题时的算法版本
}
```

### 6.3 完整流转闭环

```
分析师在可视化里发现问题
        ↓
一键创建 Issue（自动带入当前时刻 / 对象 / 算法版本）
        ↓
开发者点"查看现场" → 跳转到对应录包的对应时刻
        ↓
开发者修复代码，提交 PR
        ↓
（可选）触发回灌 Job，在原始数据段上验证修复效果
        ↓
对比 before/after，验证通过 → Issue 关闭
        ↓
分析脚本保存为附件，关联到 Issue，供后续回归参考
```

---

## 七、数据处理层

### 7.1 处理管道

```
原始文件（db3 / db4 / noah_txt / csv / ...）
        ↓
[解析器]  format-specific，只管读文件
        ↓
[转换器]  原始字段 → VizObject（由 mapping config 驱动）
        ↓
VizObject JSON（通用格式）
        ↓
[分发]  按 Manifest 提供 API
```

### 7.2 Mapping Config（转换器配置）

新增数据格式只需加 mapping，不需要改代码：

```json
{
  "format": "db3",
  "mapping": {
    "obstacle_list[].bounding_box": "obstacle.pose",
    "obstacle_list[].label":        "obstacle.label",
    "obstacle_list[].trajectory":   "obstacle.line",
    "ego_pose":                     "ego.pose"
  }
}
```

### 7.3 处理服务部署方式

```
云端处理服务（默认）
  小数据量直接在云端处理
  资源允许时全自动，用户无感知

本地客户端（可选）
  同一套处理代码，运行在用户机器
  适合大数据量（自动驾驶等行业）
  处理完通过 localhost API 给前端
  分析记录同步回云端

私有化部署
  整套服务部署在企业内网
  数据不出内网
```

---

## 八、技术选型建议

| 层次 | 技术 | 说明 |
|------|------|------|
| 文件存储 | MinIO（自托管）/ S3 / OSS | 原始文件和媒体文件 |
| 元数据库 | PostgreSQL | Recording 信息、对象类型注册表 |
| Issue 管理 | Plane（开源自托管） | 不重复造轮子 |
| 前端框架 | Vue 3 + TypeScript | 现有基础 |
| 2D 渲染 | Canvas 2D API | 现有 Canvas2DRenderer 复用 |
| 3D 渲染 | Three.js | 现有 SceneManager 复用 |
| 本地客户端 | Go 或 Rust（轻量服务） | 处理+本地 HTTP 服务 |
| 处理服务 | C++（现有）/ Python | 现有 drivers 代码复用 |

---

## 九、开发阶段规划

### 第一阶段：数据管理基础

- 文件上传（分片，支持大文件）
- Recording 列表、搜索、过滤
- 标签系统
- 详情页

### 第二阶段：可视化核心

- VizObject 格式定义与 SDK
- DataSelection UI
- Player + Viewer（2D 优先）
- Config 驱动渲染

### 第三阶段：协作与流转

- 集成 Plane（Issue 管理）
- 分析会话记录
- Issue 数据锚点（关联录包时刻）
- 团队评论

### 第四阶段：扩展能力

- 3D 可视化
- 本地客户端
- 对比查看（两个录包叠加）
- AI 分析接入

---

## 十、核心设计原则

1. **对象优先**：数据是对象，可视化是属性的呈现，不是数据本身的目的
2. **Config 驱动**：改配置，不改代码，扩展新数据类型 / 新可视化方式
3. **格式统一**：VizObject 是唯一的中间格式，所有数据处理最终产出它
4. **部署灵活**：同一套代码，云端 / 本地客户端 / 私有化，前端无感知切换
5. **记录一切**：用户的分析行为完整记录，为后续 AI 替代打基础
6. **不重复造轮子**：Issue 管理用 Plane，文件存储用 MinIO，只在真正差异化的地方自研
