# 数据传输与可视化管道设计

> 本文档记录前后端数据传输、格式设计、缓存策略的完整方案。
> 核心原则：后端是纯数据服务，前端负责缓存与展示。

---

## 一、整体架构

```
原始数据文件 (db3 / db4 / noah_txt / ...)
        ↓
   后端处理服务
   ├── 解析原始文件 → VizObject 格式（懒处理，结果写临时缓存）
   ├── 提供 HTTP 接口（分段流式返回）
   └── 原始 proto 按需查询
        ↓
   前端（流式缓存 + 渲染）
   ├── 流式加载（类视频流，固定窗口缓存）
   ├── 可视化渲染（2D / 3D / 导航）
   ├── 属性面板（VizObject 属性查看）
   ├── 时间曲线（标量字段图表）
   └── 原始数据结构查看（按需请求 proto）
```

---

## 二、数据分类与处理策略

### 2.1 可视化几何数据（主路径）

所有几何对象统一转为 **VizObject 格式**：

- 障碍物（位置、姿态、大小、颜色）
- 车道线（点列、线型、置信度）
- 自车（位姿、轨迹）
- 停车位（角点、状态）
- 地图（几何线面）

**处理方式：** C++ 后端解析 proto → 转换 → 临时缓存 → 流式返回前端

### 2.2 媒体数据（独立路径）

- 激光雷达点云：每帧 ~1.2MB，单帧 URL 懒加载
- 相机图像：每帧 50~200KB，单帧 URL 懒加载

**处理方式：** 永久存储在对象存储，前端直接请求 URL，不走可视化管道

### 2.3 原始 Proto 数据（按需路径）

- 用户主动打开"数据结构面板"时才请求
- 一次只请求一个 topic 的分段数据
- 用于原始字段值查看和调试，不用于渲染

---

## 三、VizObject 格式设计

### 3.1 核心原则

```
Schema   → 固定在前后端代码中，不传输
数据     → 只传 id / type / sub / vf / vt / s[] / f[][]
字段名   → 完全不出现在传输内容里
压缩     → HTTP gzip，纯数字数组压缩率极高
```

### 3.2 类型枚举（与后端 scene_graph.h 对齐）

```typescript
// 复用后端现有枚举，前后端数值必须一致
enum ObjectType {
  POINT_CLOUD = 1,
  LINE_LIST   = 2,
  POLYLINE    = 3,   // 车道线、轨迹
  POLYGON     = 4,   // 区域、停车位
  CUBE        = 5,   // 障碍物、自车
  SPHERE      = 6,
  TEXT        = 7,
  MESH        = 8,
  IMAGE       = 9
}

enum SubType {
  // 车道线类
  LINE_SOLID              = 1,
  LINE_DOUBLE_SOLID       = 2,
  LINE_DASHED             = 3,
  LINE_SHORT_DASHED       = 4,
  LINE_DOUBLE_DASHED      = 5,
  LINE_LEFT_SOLID_R_DASH  = 6,
  LINE_RIGHT_SOLID_L_DASH = 7,
  LINE_DOTTED             = 8,
  LINE_VIRTUAL            = 10,
  LINE_SHADED_AREA        = 11,
  LINE_CURB               = 12,

  // 障碍物类
  OBJ_CAR        = 100,
  OBJ_PEDESTRIAN = 101,
  OBJ_CYCLIST    = 102,
  OBJ_CONE       = 103,
  OBJ_TRUCK      = 104,
  OBJ_BUS        = 105,
}
```

### 3.3 Schema 注册表（代码中定义，不传输）

```typescript
// (ObjectType, SubType) → 每帧字段的顺序和类型
// 前后端各自实现，数值对应

const FRAME_SCHEMAS: Record<string, string[]> = {

  // CUBE + OBJ_CAR（障碍物-轿车）
  '5:100': [
    't:f64',            // 时间戳
    'x:f32', 'y:f32', 'z:f32',          // 位置
    'rx:f32', 'ry:f32', 'rz:f32',       // 旋转（欧拉角，弧度）
    'r:u8', 'g:u8', 'b:u8', 'a:u8',     // 颜色
    'confidence:f32',   // 置信度
    'speed:f32',        // 速度（m/s）
    'label:u8'          // 分类标签
  ],

  // CUBE + OBJ_PEDESTRIAN（行人）
  '5:101': [
    't:f64',
    'x:f32', 'y:f32', 'z:f32',
    'rx:f32', 'ry:f32', 'rz:f32',
    'r:u8', 'g:u8', 'b:u8', 'a:u8',
    'confidence:f32', 'speed:f32'
  ],

  // POLYLINE + LINE_SOLID（实线车道线）
  '3:1': [
    't:f64',
    'r:u8', 'g:u8', 'b:u8', 'a:u8',    // 颜色
    'confidence:f32',                    // 置信度
    'n:u16',                             // 点数量
    'pts:f32*'                           // 点坐标（n×2 个 f32，x0,y0,x1,y1...）
  ],

  // POLYLINE + LINE_DASHED（虚线车道线）
  '3:3': [
    't:f64',
    'r:u8', 'g:u8', 'b:u8', 'a:u8',
    'confidence:f32',
    'n:u16', 'pts:f32*'
  ],

  // POLYGON（停车位、区域）
  '4:0': [
    't:f64',
    'r:u8', 'g:u8', 'b:u8', 'a:u8',
    'confidence:f32',
    'status:u8',                         // 0=empty 1=occupied 2=unknown
    'n:u16', 'pts:f32*'                  // 通常 4 个角点
  ],

  // CUBE + DEFAULT（自车）
  '5:0': [
    't:f64',
    'x:f32', 'y:f32', 'z:f32',
    'rx:f32', 'ry:f32', 'rz:f32',
    'lat:f64', 'lng:f64'                 // GPS 经纬度
  ]
}

const STATIC_SCHEMAS: Record<string, string[]> = {
  '5:100': ['track_id:u32', 'sw:f32', 'sh:f32', 'sd:f32'],  // 尺寸
  '5:101': ['track_id:u32', 'sw:f32', 'sh:f32', 'sd:f32'],
  '3:1':   ['position:u8'],    // 0=left 1=right 2=center 3=ego_left 4=ego_right
  '3:3':   ['position:u8'],
  '4:0':   ['slot_id:str'],
  '5:0':   ['sw:f32', 'sh:f32', 'sd:f32']   // 车身尺寸（固定）
}
```

### 3.4 传输格式（JSON，仅数字）

```json
[
  {
    "id":  "rec_001:obstacle:42",
    "t":   5,
    "sub": 100,
    "vf":  5.0,
    "vt":  48.3,
    "s":   [42, 4.2, 1.8, 1.5],
    "f":   [
      [5.0,  10.0, 2.0, 0.0,  0.0, 0.0, 0.50,  255, 107, 107, 255,  0.92, 5.2, 0],
      [5.1,  10.5, 2.0, 0.0,  0.0, 0.0, 0.48,  255, 107, 107, 255,  0.91, 5.1, 0]
    ]
  },
  {
    "id":  "rec_001:lane_line:left",
    "t":   3,
    "sub": 1,
    "vf":  0.0,
    "vt":  300.0,
    "s":   [0],
    "f":   [
      [0.0,  89, 210, 255, 255,  0.95,  3,  0, 3.5,  5, 3.6,  10, 3.8],
      [0.1,  89, 210, 255, 255,  0.93,  3,  0.1, 3.5,  5.1, 3.6,  10.1, 3.8]
    ]
  }
]
```

**字段说明：**

| Key | 含义 |
|-----|------|
| `id` | 对象唯一标识，格式 `{recording_id}:{type_name}:{local_id}` |
| `t`  | ObjectType 枚举值 |
| `sub`| SubType 枚举值 |
| `vf` | valid_from，对象开始存在的时间戳 |
| `vt` | valid_to，对象消失的时间戳 |
| `s`  | static 字段值数组（对应 STATIC_SCHEMAS） |
| `f`  | frames 二维数组（每行对应一帧，顺序对应 FRAME_SCHEMAS） |

### 3.5 Schema 版本管理

```json
// GET /info 返回
{
  "schema_version": 1,
  "duration": 300.0,
  "objects": [...]
}
```

前端检测到 `schema_version` 不匹配时提示刷新页面，防止前后端不同步。

---

## 四、后端临时缓存设计

### 4.1 两层存储

```
永久存储（对象存储，永不删除）：
  /raw/{recording_id}/data.db3          原始录包文件
  /media/{recording_id}/lidar/*.bin     点云文件
  /media/{recording_id}/camera/*.jpg    图像文件

临时缓存（对象存储，7天TTL）：
  /viz_cache/{recording_id}/
    metadata.json                       元信息（时长、对象列表、大小）
    chunks/
      0-30.viz.gz                       30秒一块的 VizObject 数据
      30-60.viz.gz
      60-90.viz.gz
      ...
    last_accessed                       最后访问时间（每次请求更新）
```

### 4.2 三级处理策略

```
第1级：chunk 已缓存
  命中 viz_cache → 直接读取返回
  延迟：~50ms

第2级：chunk 未缓存，实时处理
  读原始 db3 → C++ 解析 → 转 VizObject → 写入 viz_cache → 返回
  延迟：~500ms~2s（首次一次性代价）

第3级：后台预处理
  用户打开录包时，后台异步处理后续 chunk
  用户播放到该段时大概率已经缓存好了
```

### 4.3 TTL 管理

```
每次 chunk 被访问：更新 last_accessed 为当前时间

后台定时任务（每天执行）：
  遍历 viz_cache/
  如果 last_accessed < (今天 - 7天) → 删除整个录包的缓存

用户重新访问已删除缓存：
  触发第2级实时处理，重新生成
  原始 db3 永久保留，缓存可随时重建
```

### 4.4 存储成本估算

```
一个 300s 录包：
  原始 db3（含点云图像）：~10GB
  viz_cache（仅几何，无媒体）：~50~200MB  ← 约为原始的 2~5%

7天内活跃录包：保持缓存，访问极快
超过7天无人查看：自动清理，节省存储
```

---

## 五、流式播放设计

### 5.1 核心思想（类视频流）

```
不是：等所有数据加载完 → 再播放
而是：加载第一段 → 立即播放 → 边播边预取下一段
```

```
内存窗口（固定大小，不随录包长度增长）：

t=45s 播放时的内存：
  [25s ←── 已缓存 20s ──→ 45s ←── 预取 60s ──→ 105s]
  
  总内存占用 ≈ 80s × 0.5MB/s ≈ 40MB（固定上限）
```

### 5.2 前端流式播放器

```typescript
class StreamingPlayer {
  // 缓冲区参数
  private BUFFER_AHEAD  = 60   // 预取未来 60 秒
  private BUFFER_BEHIND = 20   // 保留过去 20 秒
  private CHUNK_SIZE    = 30   // 每次请求 30 秒

  private buffer   = new Map<string, VizChunk>()
  private inflight = new Set<string>()

  onTimeUpdate(t: number) {
    this.prefetch(t)    // 触发预取
    this.evict(t)       // 清理过期数据
  }

  private prefetch(t: number) {
    const need = t + this.BUFFER_AHEAD
    let start = this.getBufferedUntil(t)

    while (start < need) {
      const end = start + this.CHUNK_SIZE
      const key = `${start}-${end}`

      if (!this.buffer.has(key) && !this.inflight.has(key)) {
        this.fetchChunk(start, end)
      }
      start = end
    }
  }

  private evict(t: number) {
    const cutoff = t - this.BUFFER_BEHIND
    for (const [key, chunk] of this.buffer) {
      if (chunk.to < cutoff) this.buffer.delete(key)
    }
  }

  private async fetchChunk(from: number, to: number) {
    const key = `${from}-${to}`
    this.inflight.add(key)
    const res  = await fetch(`/viz?from=${from}&to=${to}`)
    const data = await res.json()
    this.buffer.set(key, new VizChunk(data))
    this.inflight.delete(key)
  }

  // Viewer 查询当前帧（同步，从 buffer 读）
  getSceneAt(t: number): SceneSnapshot | null {
    const chunk = this.findChunk(t)
    if (!chunk) return null
    return chunk.stateAt(t)
  }
}
```

### 5.3 Seek 处理

```
用户拖进度条到 t=200s
      ↓
清空当前 buffer
      ↓
立即请求 chunk [185s~215s]（当前位置附近）
      ↓
返回后（~200ms）渲染当前帧
      ↓
后台预取 [215s~275s]
```

### 5.4 VizChunk 的数据结构（前端）

```typescript
class VizChunk {
  from: number
  to:   number

  // 每个对象，按 schema 解析成 TypedArray
  objects: Map<string, ParsedObject>
  // key = object_id

  stateAt(t: number): SceneSnapshot {
    const result: SceneSnapshot = { t, objects: [] }

    for (const [id, obj] of this.objects) {
      if (t < obj.vf || t > obj.vt) continue

      const idx   = binarySearchLastBefore(obj.timestamps, t)
      const state = obj.getStateAtIndex(idx)

      result.objects.push({ id, type: obj.type, sub: obj.sub, state })
    }
    return result
  }
}

class ParsedObject {
  id:   string
  type: number        // ObjectType 枚举
  sub:  number        // SubType 枚举
  vf:   number
  vt:   number
  staticData: any

  // 每个字段一个 TypedArray（按 FRAME_SCHEMAS 解析）
  timestamps: Float64Array
  x:          Float32Array
  y:          Float32Array
  heading:    Float32Array
  confidence: Float32Array
  // ... 按 schema 动态创建

  // 变长点列
  pointsFlat:  Float32Array
  pointsCount: Uint16Array

  getStateAtIndex(idx: number): FrameState { ... }
}
```

---

## 六、后端 HTTP 接口

### 6.1 完整接口列表

```
// 元信息
GET /api/sessions/{id}/info
  → { schema_version, duration, objects: [{id, type, sub, vf, vt, size_bytes}] }

// 可视化数据（流式，分段）
GET /api/sessions/{id}/viz?from={T1}&to={T2}
  → VizObject[] JSON（gzip）
  → 30秒一段，后端从 viz_cache 或实时处理

// 媒体数据（按帧）
GET /api/sessions/{id}/media/lidar?t={T}
  → 二进制点云（bin）

GET /api/sessions/{id}/media/{camera_name}?t={T}
  → 图像（jpg/png）

// 原始 Proto 数据（数据结构查看，分段）
GET /api/sessions/{id}/proto?topic={topic_name}&from={T1}&to={T2}
  → { schema: [...], frames: [{t, d: {"1": val, "2": val}}] }（gzip）
  → schema 字段名用数字 ID 替代，节省传输量
```

### 6.2 接口返回大小参考

```
/viz?from=0&to=30（30秒，典型场景）：
  几何对象（无媒体）：~0.5~3MB gzip
  前端下载时间（10Mbps）：< 2.4s

/proto?topic=obstacle_list&from=0&to=30：
  ~300KB gzip

/media/lidar?t=45.2：
  ~200~400KB（原始点云）
```

---

## 七、前端三层缓存

```
┌─────────────────────────────────────────────────────────────┐
│  VizChunk 缓存（主缓存）                                      │
│  TypedArray 格式，滑动窗口，~40MB 固定上限                     │
│  来源：GET /viz 分段加载                                      │
│  用途：渲染、属性面板、时间曲线（映射字段）                     │
├─────────────────────────────────────────────────────────────┤
│  Proto 缓存（替换式，单 topic）                               │
│  一次只持有一个 topic 的分段数据                              │
│  来源：GET /proto 按需加载                                   │
│  用途：原始数据结构查看、字段值调试                            │
├─────────────────────────────────────────────────────────────┤
│  媒体缓存（LRU，有限窗口）                                    │
│  只缓存当前播放位置附近几帧                                   │
│  来源：GET /media 按帧懒加载                                  │
│  用途：点云渲染、相机图像显示                                  │
└─────────────────────────────────────────────────────────────┘
```

### 7.1 各缓存的触发时机

```
用户操作                    触发接口 / 读取层
──────────────────────────────────────────────────────────────
打开录包                  → GET /info（元信息）
开始播放                  → GET /viz?from=0&to=30（首段）
                            后台预取 from=30&to=60，from=60&to=90
播放推进                  → 读 VizChunk 缓存（同步，不发请求）
                            窗口边界触发预取下一 chunk
Seek 到新位置             → 清空 buffer → GET /viz?from=T-15&to=T+15
点击对象查看属性          → 读 VizChunk（不发请求）
打开时间曲线图            → 读 VizChunk 已加载范围的字段
打开数据结构面板          → GET /proto?topic=X&from=T&to=T+30
切换查看另一 topic        → GET /proto?topic=Y（替换 proto 缓存）
播放到激光雷达帧          → GET /media/lidar?t=T（LRU 缓存）
```

---

## 八、原始 Proto 数据格式（数据结构查看）

### 8.1 传输格式

复用 `DataStructurePublisher` 的设计思路：Schema 定义一次，数据用数字 ID。

```json
{
  "topic": "obstacle_list",
  "from": 0.0,
  "to": 30.0,

  "schema": [
    { "id": 1, "path": "header.raw_timestamp",              "type": "f64" },
    { "id": 2, "path": "obstacles[].id",                   "type": "i32" },
    { "id": 3, "path": "obstacles[].confidence",           "type": "f32" },
    { "id": 4, "path": "obstacles[].bounding_box.center.x","type": "f32" },
    { "id": 5, "path": "obstacles[].bounding_box.center.y","type": "f32" },
    { "id": 6, "path": "obstacles[].bounding_box.yaw",     "type": "f32" },
    { "id": 7, "path": "obstacles[].label",                "type": "i32" }
  ],

  "frames": [
    { "t": 5.0, "d": { "1": 1700000005.0, "2": [42,43], "3": [0.92,0.88], "4": [10.0,15.2], "5": [2.0,3.1], "6": [0.5,0.3], "7": [0,0] } },
    { "t": 5.1, "d": { "1": 1700000005.1, "2": [42,43], "3": [0.91,0.87], "4": [10.5,15.5], "5": [2.0,3.1], "6": [0.48,0.3], "7": [0,0] } }
  ]
}
```

### 8.2 前端展示

```
前端按 schema 还原字段名，展示成树形：

obstacle_list @ t=5.0s
├── header
│   └── raw_timestamp: 1700000005.0
└── obstacles
    ├── [0]
    │   ├── id: 42
    │   ├── confidence: 0.92
    │   ├── bounding_box
    │   │   ├── center.x: 10.0
    │   │   ├── center.y: 2.0
    │   │   └── yaw: 0.5
    │   └── label: 0 (car)
    └── [1]
        ├── id: 43
        └── ...
```

---

## 九、关键设计决策汇总

### 9.1 为什么不在前端存 proto 数据用于渲染

```
proto 数据问题：
  字段嵌套复杂，前端难以通用解析
  每种 topic 结构不同，需要为每个写特殊解析
  转换在 JS 中进行，比 C++ 慢很多
  
VizObject 优势：
  固定 schema，TypedArray 直接使用
  渲染时零转换，极快
  C++ 做转换更快更合适
```

### 9.2 为什么用流式而不是全量加载

```
全量加载的问题：
  300s 录包几何数据 ~5~50MB，需要等待
  1小时录包可能超过 200MB，不可行
  内存随录包长度线性增长

流式加载的优势：
  1秒内开始播放（加载首段约 0.5~1MB）
  内存固定约 40MB，不受录包长度影响
  任意长度录包均可处理
```

### 9.3 为什么用临时缓存而不是实时转换

```
每次实时转换的问题：
  30秒数据首次处理：500ms~2s
  用户 seek 到新位置会有明显延迟

临时缓存的优势：
  热数据：50ms 响应（读缓存）
  冷数据：首次处理后永久缓存（7天内）
  原始 db 永久保留，缓存随时可重建
  7天无访问自动清理，存储成本低
```

### 9.4 为什么 Schema 固定在代码中不传输

```
传 Schema 的问题：
  每个 chunk 都带字段名，大量重复
  JSON 中字符串字段名占比很高

固定 Schema 的优势：
  传输内容全部是数字（gzip 压缩率极高）
  前后端同步维护枚举，ObjectType+SubType 即为 Schema Key
  扩展新类型只需在注册表加一条，不改传输格式
```

---

## 十、后端代码复用

```
现有代码                              新架构中的角色
────────────────────────────────────────────────────────────
viz_core/publisher/                   →  改为 HTTP chunk 接口
  visualization_publisher.cpp            复用 SceneGraph 构建逻辑
                                         改为按时间段输出到文件

viz_core/publisher/                   →  复用 Schema 生成 + 数据提取
  data_structure_publisher.cpp           改为 HTTP 按需接口

viz_core/model/scene_graph.h          →  核心数据结构复用
  ObjectType / SubType 枚举              直接作为 Schema Key

viz_core/model/compressed_point_list  →  点云压缩复用（已有 zlib）

viz_core/server/websocket_server      →  退化为仅传输控制信令
                                         数据传输全部改为 HTTP

主要新增：
  HTTP 接口层（替代 WebSocket 数据推送）
  viz_cache 写入逻辑（处理结果保存为分段文件）
  TTL 管理（定时清理过期缓存）
```

---

## 十一、数据量参考

```
典型录包（300秒，10Hz，中等复杂度场景）：

可视化几何数据（viz_cache）：
  每 30s chunk：0.5~3MB gzip
  全部 10 个 chunk：5~30MB gzip
  前端内存（80s 窗口）：约 40MB

原始 proto（按需加载，单 topic 30s）：
  obstacle_list：~300KB gzip
  online_map：~2~5MB gzip（含点列）

媒体数据（每帧）：
  lidar 点云：200~400KB
  相机图像：50~200KB

存储成本（对象存储）：
  原始 db：~10GB（永久）
  viz_cache：~50~200MB（7天TTL）
  媒体文件：永久，按实际大小计费
```
