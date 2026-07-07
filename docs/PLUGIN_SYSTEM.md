# 插件系统设计文档

> 平台提供数据查询与可视化能力，用户（借助 AI）编写分析脚本，脚本作为独立插件运行，结果回传前端展示。

---

## 一、设计理念

### 核心思路

```
前端  =  固定的可视化终端（提供渲染接口，用户不可修改）
后端  =  固定的数据查询服务（提供数据接口，用户不可修改）
插件  =  用户扩展的分析逻辑（Python 脚本，独立运行，可任意增减）
```

插件是唯一的扩展点。用户描述分析需求 → AI 生成插件脚本 → 插件调用平台接口完成分析 → 结果推送到前端展示。

### 与主服务的关系

```
┌─────────────────────────────────────────────────────────┐
│                      前端（固定）                         │
│   可视化原语：点线面框 / 图表 / 表格 / 时间轴标记          │
│   接收后端推送的结构化结果，按类型渲染，不含业务逻辑        │
├──────────────────────────┬──────────────────────────────┤
│      主服务后端（固定）    │       插件沙箱（可扩展）        │
│                          │                              │
│  数据查询 API             │  Plugin A  Plugin B  ...    │
│  VizObject 管理           │  独立进程  独立进程           │
│  对象注册表               │  互不影响  互不影响           │
│  注解存储                 │  崩溃不影响主服务             │
│  插件调度                 │                              │
└──────────────────────────┴──────────────────────────────┘
```

---

## 二、三层接口规范

### 2.1 后端数据查询接口（插件可调用）

插件通过 `api` 对象访问平台数据，主服务保证这些接口的稳定性：

```python
# 对象数据查询
api.get_objects(recording_id, object_type)
# → 返回该类型所有对象的列表（含 header、static 字段）

api.get_timeseries(recording_id, object_type, fields, time_range)
# → 返回指定字段的时序数据

api.get_frame(recording_id, object_type, t)
# → 返回某一时刻的对象快照

# 元信息查询
api.get_schema(object_type)
# → 返回对象的字段定义（类型、单位、范围）

api.get_annotations(object_type)
# → 返回该对象的人类备注 + AI 备注

api.list_object_types(recording_id)
# → 返回录包中包含的所有对象类型

# 录包信息
api.get_recording_info(recording_id)
# → 时长、格式、采集时间、包含对象类型列表
```

### 2.2 前端可视化接口（插件结果类型）

插件返回结构化 JSON，前端按类型渲染。前端支持的输出类型是固定的：

```python
return {

    # 时间轴标记（问题关键帧）
    "keyframes": [
        {
            "t":        45.2,           # 时刻（秒）
            "label":    "CPU 超载",
            "severity": "error",        # info / warning / error / critical
            "detail":   "total_cpu 达到 97.3%"
        }
    ],

    # 画布叠加几何（叠加在 2D/3D 视图上）
    "overlays": [
        { "type": "box",    "x": 10, "y": 3, "w": 4, "h": 2,
          "color": "#ff4444", "label": "异常区域", "t": 45.2 },
        { "type": "line",   "points": [[0,0],[10,5]], "color": "#58a6ff" },
        { "type": "point",  "x": 5, "y": 3, "color": "#ffd700", "size": 6 },
        { "type": "arrow",  "x": 5, "y": 3, "heading": 1.2, "color": "#fff" },
        { "type": "text",   "x": 5, "y": 3, "content": "漂移点", "color": "#fff" },
        { "type": "circle", "x": 5, "y": 3, "r": 2, "color": "#ff4444" },
        { "type": "polygon","points": [[0,0],[5,0],[5,5]], "color": "#4caf50" }
    ],

    # 图表（折线 / 柱状 / 散点）
    "charts": [
        {
            "title": "CPU 负载趋势",
            "type":  "line",            # line / bar / scatter
            "x_axis": { "label": "时间(s)" },
            "y_axis": { "label": "CPU %", "range": [0, 100] },
            "series": [
                { "name": "total_cpu", "data": [[0, 45], [1, 67], ...], "color": "#ff6b6b" }
            ],
            "threshold_lines": [
                { "y": 95, "label": "告警阈值", "color": "#ff4444" }
            ]
        }
    ],

    # 表格
    "tables": [
        {
            "title":   "异常进程列表",
            "columns": ["进程名", "峰值CPU%", "均值CPU%", "异常程度"],
            "rows": [
                ["perception_node", 45.2, 12.3, "高"],
                ["planning_node",   38.1, 10.1, "中"]
            ],
            "highlight_rows": [0]       # 高亮第 0 行
        }
    ],

    # 告警卡片（顶部或侧边栏显示）
    "alerts": [
        {
            "level":   "error",
            "title":   "检测到 CPU 超载",
            "message": "共 3 段时间 CPU 超过 95%，累计时长 8.2s",
            "t_range": [45.2, 53.4]     # 可选，点击跳转到对应时段
        }
    ],

    # 文字摘要（自然语言结论）
    "summary": "在 45.2s~53.4s 区间内，CPU 总占用率超过 95%，主要由 perception_node 进程引起（峰值 45.2%，超出基线 2.8σ）。建议排查感知模块在该场景下的计算效率。",

    # 报表视图（将多个输出组合成结构化报表页面）
    "report": {
        "title":    "CPU 负载分析报告",
        "subtitle": "录包 rec_001  采集时间 2024-01-15",
        "layout": [
            { "type": "summary",  "span": 12 },
            { "type": "alerts",   "span": 12, "ref": "overload_alerts" },
            { "type": "chart",    "span": 8,  "ref": "cpu_trend" },
            { "type": "chart",    "span": 4,  "ref": "process_pie" },
            { "type": "table",    "span": 12, "ref": "process_anomalies" }
        ]
    }
}
```

### 2.3 插件入口规范

每个插件必须实现 `run` 函数：

```python
def run(api, params):
    """
    api    : 平台数据查询接口对象
    params : 用户在前端填写的参数（recording_id、time_range、自定义参数等）
    return : 符合前端输出类型规范的字典
    """
    recording_id = params["recording_id"]
    time_range   = params.get("time_range", None)
    threshold    = params.get("threshold", 95)

    # ... 分析逻辑 ...

    return {
        "keyframes": [...],
        "charts":    [...],
        "summary":   "..."
    }
```

---

## 三、插件运行时（Plugin Runtime）

插件不直接调用 HTTP 接口，也不自己推送数据到前端。平台提供一个**插件运行时**，统一处理所有插件的通信，插件只需要调用注入的 `api` 对象。

### 3.1 整体架构

```
前端
  ↑ WebSocket 推送结果
主服务
  ↑ 返回结构化结果
Plugin Runtime（每次执行启动一个）
  ├── 注入 api 对象（数据查询 + 通用工具）
  ├── 执行插件 run(api, params)
  ├── api.query_*() 内部通过 IPC 向主服务请求数据
  └── run() 返回值序列化后交回主服务
插件沙箱（受限 Python 环境）
  └── 插件脚本在此运行，无法直接访问网络/文件系统
```

插件的视角极简：只有输入（`api` + `params`）和输出（`return` 字典），其余全部由运行时托管。

### 3.2 运行时完整流程

```
用户在前端触发插件
        ↓
主服务创建 Plugin Runtime 实例（独立进程）
        ↓
Runtime 通过 IPC 接收任务（recording_id、params）
        ↓
Runtime 构造 api 对象，注入插件
        ↓
插件调用 api.get_timeseries(...)
        ↓
Runtime 拦截调用 → IPC 向主服务请求数据 → 返回给插件
        ↓
插件完成计算，return 结果字典
        ↓
Runtime 序列化结果 → IPC 返回主服务
        ↓
主服务通过 WebSocket 推送到前端
        ↓
前端按输出类型渲染
        ↓
Runtime 进程退出（资源自动释放）
```

### 3.3 api 对象完整结构

```python
api
├── # 数据查询（通过 IPC 向主服务请求）
│   api.get_objects(recording_id, object_type)
│   api.get_timeseries(recording_id, object_type, fields, time_range)
│   api.get_frame(recording_id, object_type, t)
│   api.get_schema(object_type)
│   api.get_annotations(object_type)
│   api.list_object_types(recording_id)
│   api.get_recording_info(recording_id)
│
├── # 数据索引（本地计算，无网络请求，见第四章）
│   api.index.by_time(series, t)
│   api.index.range(series, t1, t2)
│   api.index.nearest(series, t)
│   api.index.before(series, t, n)
│   api.index.after(series, t, n)
│
└── # 通用分析工具（本地计算，见第四章）
    api.stats.mean / std / percentile / zscore ...
    api.anomaly.threshold / zscore / iqr ...
    api.timeseries.diff / smooth / resample ...
    api.error.rmse / mae / mape ...
```

### 3.4 进度推送（长时间运行）

插件运行时间较长时，可以主动推送进度到前端，用户看到实时进度条：

```python
def run(api, params):
    data = api.get_timeseries(...)

    results = []
    total = len(data.frames)

    for i, frame in enumerate(data.frames):
        # 每处理 10% 推送一次进度
        if i % (total // 10) == 0:
            api.progress(i / total, f"正在分析第 {i}/{total} 帧...")

        results.append(analyze_frame(frame))

    return { "tables": [build_table(results)] }
```

---

## 四、平台通用分析工具（Platform SDK）

这是注入到 `api` 对象中的标准工具库，AI 写插件时可直接调用，无需自己实现基础算法。工具库在本地运行，不发网络请求。

### 4.1 数据索引（api.index）

插件最常见的操作是"根据时间找数据"，`api.index` 封装了所有时间索引操作：

```python
series = api.get_timeseries(recording_id, "cpu_metrics", ["total"], [0, 300])
# series.frames = [{"t": 0.0, "total": 45.2}, {"t": 0.1, "total": 47.1}, ...]

# 找某一时刻最近的帧
frame = api.index.nearest(series, t=45.23)
# → {"t": 45.2, "total": 67.3}

# 找某时刻之前的 N 帧
prev_frames = api.index.before(series, t=45.2, n=10)
# → 最近 10 帧，按时间升序

# 找某时刻之后的 N 帧
next_frames = api.index.after(series, t=45.2, n=10)

# 取某段时间范围内的所有帧
window = api.index.range(series, t1=40.0, t2=50.0)

# 取某时刻前后各 N 帧（上下文窗口）
context = api.index.context(series, t=45.2, before=5, after=5)
# → 共 11 帧，t=45.2 在中间位置

# 跨对象按时间对齐（将两个时序对齐到同一时间轴）
aligned = api.index.align(series_a, series_b)
# → 两个 series 插值对齐，可逐帧对比
```

### 4.2 统计工具（api.stats）

```python
values = series.field("total")   # 提取某字段为数值列表

# 基础统计
api.stats.mean(values)           # 均值
api.stats.std(values)            # 标准差
api.stats.variance(values)       # 方差
api.stats.median(values)         # 中位数
api.stats.percentile(values, 95) # 百分位数
api.stats.min(values)
api.stats.max(values)

# 分布统计
api.stats.histogram(values, bins=20)
# → {"bins": [...], "counts": [...]}

api.stats.zscore(values)
# → 每个值对应的 z-score 列表

api.stats.zscore_at(values, v)
# → 值 v 在该分布中的 z-score（异常程度）

# 滑动统计（滑动窗口内的统计值）
api.stats.rolling_mean(values, window=10)
api.stats.rolling_std(values, window=10)
```

### 4.3 误差分析（api.error）

用于算法精度评估，对比预测值与真值：

```python
predicted = series_a.field("heading")
ground_truth = series_b.field("heading")

api.error.rmse(predicted, ground_truth)    # 均方根误差
api.error.mae(predicted, ground_truth)     # 平均绝对误差
api.error.mape(predicted, ground_truth)    # 平均绝对百分比误差
api.error.max_error(predicted, ground_truth)   # 最大误差
api.error.percentile_error(predicted, ground_truth, 95)  # 95分位误差

# 逐帧误差（返回每帧的误差值，用于图表展示）
api.error.per_frame(predicted, ground_truth)
# → [{"t": 0.0, "error": 0.02}, {"t": 0.1, "error": 0.05}, ...]
```

### 4.4 异常检测（api.anomaly）

```python
values = series.field("total_cpu")

# 阈值检测：超过固定值的帧
api.anomaly.threshold(series, field="total_cpu", threshold=95)
# → [{"t": 45.2, "value": 97.3}, ...]

# Z-score 检测：偏离均值超过 N 个标准差的帧
api.anomaly.zscore(series, field="total_cpu", sigma=2.0)
# → [{"t": 45.2, "value": 97.3, "zscore": 3.1}, ...]

# IQR 检测：四分位距法（对非正态分布更稳健）
api.anomaly.iqr(series, field="total_cpu", multiplier=1.5)

# 突变检测：相邻帧之间变化超过阈值
api.anomaly.sudden_change(series, field="confidence", delta=0.3)
# → 检测置信度骤降/骤升

# 连续异常段合并（将相邻的异常帧合并为时间段）
anomaly_frames = api.anomaly.zscore(series, field="total_cpu", sigma=2.0)
api.anomaly.merge_segments(anomaly_frames, gap=1.0)
# → [{"t_start": 45.2, "t_end": 53.4, "peak_value": 97.3}, ...]
```

### 4.5 时序处理（api.timeseries）

```python
# 求导（速度 → 加速度）
api.timeseries.diff(series, field="velocity")

# 平滑（去除高频噪声）
api.timeseries.smooth(series, field="heading", method="moving_avg", window=5)
api.timeseries.smooth(series, field="heading", method="savgol")

# 重采样（统一采样率）
api.timeseries.resample(series, hz=10)

# 两序列相关性
api.timeseries.correlation(series_a, field_a="cpu", series_b, field_b="latency")
# → correlation: 0.87, lag: 0.2s（B 比 A 滞后 0.2s）
```

### 4.6 使用示例：完整的 CPU 分析插件

展示上述工具如何组合使用：

```python
PLUGIN_META = {
    "name": "CPU 负载异常分析",
    "params": [
        { "key": "object_type", "type": "object_type_picker", "default": "cpu_metrics" },
        { "key": "threshold",   "type": "number", "default": 95 },
        { "key": "sigma",       "type": "number", "default": 2.0 }
    ]
}

def run(api, params):
    rid       = params["recording_id"]
    obj_type  = params["object_type"]
    threshold = params["threshold"]
    sigma     = params["sigma"]

    # 1. 获取数据
    api.progress(0.1, "加载数据...")
    series = api.get_timeseries(rid, obj_type,
                                fields=["total", "procs"],
                                time_range=params.get("time_range"))

    # 2. 超阈值检测 + 合并连续段
    api.progress(0.3, "检测超载时段...")
    over_frames  = api.anomaly.threshold(series, field="total", threshold=threshold)
    over_segs    = api.anomaly.merge_segments(over_frames, gap=2.0)

    # 3. 进程级异常检测（对每个进程单独做 z-score）
    api.progress(0.6, "分析异常进程...")
    proc_anomalies = []
    for proc_name in series.unique_values("procs.name"):
        proc_series = series.filter("procs.name", proc_name)
        baseline    = api.stats.mean(proc_series.field("procs.cpu"))
        anomalies   = api.anomaly.zscore(proc_series, field="procs.cpu", sigma=sigma)
        if anomalies:
            proc_anomalies.append({
                "name":     proc_name,
                "baseline": baseline,
                "peak":     api.stats.max(proc_series.field("procs.cpu")),
                "anomaly_count": len(anomalies)
            })

    # 4. 时序图数据
    cpu_trend = series.to_chart_series("total", color="#ff6b6b")

    api.progress(1.0, "完成")
    return {
        "keyframes": [
            { "t": seg["t_start"], "severity": "error",
              "label": f"CPU {seg['peak_value']:.1f}%" }
            for seg in over_segs
        ],
        "charts": [{
            "id": "cpu_trend", "title": "CPU 负载趋势",
            "type": "line", "series": [cpu_trend],
            "threshold_lines": [{ "y": threshold, "color": "#ff4444" }]
        }],
        "tables": [{
            "id": "proc_anomalies", "title": "异常进程",
            "columns": ["进程名", "基线CPU%", "峰值CPU%", "异常次数"],
            "rows": [[p["name"], p["baseline"], p["peak"], p["anomaly_count"]]
                     for p in proc_anomalies],
        }],
        "summary": f"共检测到 {len(over_segs)} 段 CPU 超载，"
                   f"累计 {sum(s['t_end']-s['t_start'] for s in over_segs):.1f}s。"
                   f"主要异常进程：{proc_anomalies[0]['name'] if proc_anomalies else '无'}。",
        "report": {
            "title": "CPU 负载分析报告",
            "layout": [
                { "type": "stat",   "span": 3, "value": len(over_segs),         "label": "超载时段数" },
                { "type": "stat",   "span": 3, "value": len(proc_anomalies),     "label": "异常进程数" },
                { "type": "summary","span": 6 },
                { "type": "chart",  "span": 8, "ref": "cpu_trend" },
                { "type": "table",  "span": 4, "ref": "proc_anomalies" }
            ]
        }
    }
```

---

## 五、插件生命周期

### 3.1 创建流程

```
用户描述分析需求（自然语言）
        ↓
AI 读取对象注册表 + 对象备注（了解数据结构和语义）
        ↓
AI 生成 Python 插件脚本
        ↓
平台对脚本进行安全检查（禁止网络访问、文件系统访问等）
        ↓
用户在测试录包上试运行，查看结果
        ↓
确认无误 → 插件保存到插件库
        ↓
后续分析时可随时调用
```

### 3.2 运行流程

```
用户在分析工作台选择插件
        ↓
填写插件参数（录包ID、时间范围、自定义参数）
        ↓
主服务在沙箱进程中执行插件 run()
        ↓
插件通过 api 接口查询数据（主服务处理请求，返回数据）
        ↓
插件完成计算，返回结构化结果
        ↓
主服务将结果推送到前端
        ↓
前端按输出类型渲染（keyframes / overlays / charts / tables / alerts / summary）
```

### 3.3 隔离与安全

```
每个插件运行在独立沙箱进程中
  ✓ 插件崩溃不影响主服务
  ✓ 插件之间互不影响
  ✓ 禁止访问网络
  ✓ 禁止读写文件系统（除通过 api 接口外）
  ✓ 禁止 import 危险模块（os.system / subprocess / socket 等）
  ✓ 超时自动终止（默认 60s）
  ✓ 内存上限（默认 512MB）
```

---

## 六、对象语义注解系统

AI 写插件时，需要知道每个对象字段的"语义"（这个字段是什么意思）。注解系统提供这个能力。

### 4.1 注解结构

```python
# 对象类型注解（描述整个对象）
{
    "object_type": "cpu_metrics",
    "annotations": [
        {
            "source":     "human",                  # human / ai
            "author":     "张三",                   # 人类作者 或 AI模型版本
            "confidence": 1.0,                      # 人类固定 1.0，AI 按实际
            "content":    "记录各进程的CPU占用率，采样频率 10Hz",
            "created_at": "2024-01-15T10:30:00Z"
        },
        {
            "source":     "ai",
            "author":     "claude-3.5",
            "confidence": 0.85,
            "content":    "字段 total 与 ego_status.cpu_load 高度相关，疑为同源数据",
            "created_at": "2024-01-16T09:00:00Z"
        }
    ]
}

# 字段级注解（描述某个具体字段）
{
    "object_type": "cpu_metrics",
    "field":       "procs[].cpu",
    "annotations": [
        {
            "source":     "human",
            "content":    "单个进程的 CPU 占用率，单位 %，范围 0~100",
            "confidence": 1.0
        }
    ]
}
```

### 4.2 AI 如何使用注解

```
AI 生成插件前，先调用：
  api.get_schema("cpu_metrics")      → 字段定义（类型/单位/范围）
  api.get_annotations("cpu_metrics") → 语义描述（人类备注 + AI推断）

两者合并，AI 就能理解：
  "这个对象有哪些字段"  +  "这些字段在业务上意味着什么"

然后生成有意义的分析脚本，而不是盲目处理数字
```

### 4.3 AI 自动生成注解

插件运行结束后，AI 可以基于分析结果补充注解：

```
插件发现：cpu_metrics.procs[].cpu 在场景 X 下规律性升高
AI 自动写入注解：
  "该字段在弯道场景下通常高于直道 15~20%，可能与感知模块的计算量有关"
  (source: ai, confidence: 0.72)
```

---

## 七、插件参数配置

用户在调用插件时，前端展示参数填写表单，参数由插件声明：

```python
# 插件在文件头声明参数（AI 生成时自动填写）
PLUGIN_META = {
    "name":        "CPU 负载异常分析",
    "description": "检测录包中 CPU 负载超阈值的时段，分析异常进程",
    "author":      "AI (claude)",
    "version":     "1.0",

    "params": [
        {
            "key":     "object_type",
            "label":   "CPU 数据对象",
            "type":    "object_type_picker",   # 前端渲染对象选择器
            "default": "cpu_metrics"
        },
        {
            "key":     "threshold",
            "label":   "告警阈值 (%)",
            "type":    "number",
            "default": 95,
            "range":   [50, 100]
        },
        {
            "key":     "anomaly_sigma",
            "label":   "进程异常判定（σ）",
            "type":    "number",
            "default": 2.0
        }
    ]
}
```

---

## 八、插件库管理

```
插件库
│
├── 系统内置插件（平台提供，只读）
│   ├── 基础统计：均值/方差/最大值/最小值
│   ├── 阈值检测：超阈值帧检测
│   ├── 置信度分析：置信度分布与低值预警
│   └── 对象轨迹分析：轨迹平滑度、异常跳变
│
├── 用户插件（用户或 AI 创建）
│   ├── CPU 负载异常分析      作者：张三  v1.2
│   ├── 车道线丢失检测        作者：AI    v2.0
│   ├── 定位漂移识别          作者：李四  v1.0
│   └── ...
│
└── 共享插件（团队共享）
    └── 审核通过后可被所有人调用
```

---

## 九、未来演进：AI 闭环

当插件库足够丰富后，AI 可以自动完成分析闭环：

```
新录包上传
    ↓
AI 自动识别录包中的对象类型（对比注解库）
    ↓
AI 自动选择匹配的插件批量运行
    ↓
AI 汇总各插件结果 → 自动创建 Issue（附数据锚点）
    ↓
开发者修复代码，提交 PR
    ↓
AI 触发回灌（用新版本算法重跑该录包）
    ↓
AI 自动运行同一套插件对比 before/after
    ↓
结论：问题消失 → 自动关闭 Issue，更新里程碑进度
      问题依然存在 → 重新打开 Issue，附对比报告
```

**每一次人工分析 + 插件创建，都在喂这个闭环，使其越来越自动化。**

---

## 十、报表视图设计

报表视图是前端的一种基础可视化能力，与图表、表格平级。它不引入新的数据类型，只是把已有输出单元按网格布局组合成一页完整报表。

### 8.1 定位

```
图表 / 表格 / 告警 / 摘要  ←  基础输出单元（可单独展示）
          ↓
       报表视图            ←  把多个基础单元组合成一页（布局容器）
          ↓
    导出 / 分享链接        ←  截图或生成静态页面
```

报表视图**不是独立数据**，是对同一次插件结果的另一种呈现方式。切换报表视图和切换到图表视图，看的是同一份数据。

### 8.2 布局规范

采用 12 列网格，`span` 控制每个单元占几列：

```
span=12  占满整行
span=8   占三分之二
span=6   占一半
span=4   占三分之一
span=3   占四分之一
```

```python
"report": {
    "title":    "报表标题",
    "subtitle": "副标题（录包信息、时间范围等）",
    "layout": [
        # 每行从左到右排列，span 超过 12 自动换行
        { "type": "summary",  "span": 12 },
        { "type": "alerts",   "span": 12, "ref": "overload_alerts" },
        { "type": "chart",    "span": 8,  "ref": "cpu_trend" },
        { "type": "chart",    "span": 4,  "ref": "process_pie" },
        { "type": "table",    "span": 12, "ref": "process_anomalies" }
    ]
}
```

`ref` 指向同一结果中 charts / tables / alerts 列表里对应元素的 `id` 字段。

### 8.3 支持的布局单元类型

| type | 对应数据 | 说明 |
|------|---------|------|
| `summary` | `summary` 字段 | 文字摘要卡片 |
| `chart` | `charts[].id` | 图表（line/bar/scatter/heatmap/radar/...） |
| `table` | `tables[].id` | 数据表格 |
| `alerts` | `alerts[].id` | 告警卡片列表 |
| `stat` | 内联数值 | 单个关键指标大字展示 |
| `divider` | 无 | 分隔线 + 小标题 |

`stat` 单元示例（常用于报表顶部的关键数字）：

```python
{ "type": "stat", "span": 3, "value": 3,      "label": "超载时段数", "color": "#ff4444" },
{ "type": "stat", "span": 3, "value": "8.2s", "label": "累计超载时长" },
{ "type": "stat", "span": 3, "value": "97.3%","label": "峰值 CPU",   "color": "#ff4444" },
{ "type": "stat", "span": 3, "value": "perception_node", "label": "主要异常进程" },
```

渲染效果：

```
┌─────────────┬─────────────┬─────────────┬──────────────────┐
│      3      │    8.2s     │    97.3%    │ perception_node  │
│  超载时段数  │  累计超载   │   峰值CPU   │   主要异常进程    │
└─────────────┴─────────────┴─────────────┴──────────────────┘
```

### 8.4 图表类型扩展

报表中的图表支持比单独展示时更多的类型，涵盖统计报表常用场景：

```python
{ "type": "line"      }   # 折线图（时序趋势）
{ "type": "bar"       }   # 柱状图（分类对比）
{ "type": "scatter"   }   # 散点图（分布）
{ "type": "pie"       }   # 饼图（占比）
{ "type": "heatmap"   }   # 热力图（时间×类别密度）
{ "type": "radar"     }   # 雷达图（多维对比）
{ "type": "histogram" }   # 直方图（数值分布）
{ "type": "boxplot"   }   # 箱线图（统计分布）
```

前端统一使用 ECharts 实现，AI 写插件时直接声明 type，不需要关心渲染细节。

### 8.5 交互保留

报表视图不是静态截图，前端仍然保留交互能力：

```
点击图表时间轴上的点   →  主播放器跳转到对应时刻
点击表格某行           →  高亮对应对象，跳转到对应时刻
点击 alerts 卡片       →  跳转到告警时段
```

### 8.6 导出与分享

```
[导出 PDF]   →  前端直接打印当前报表布局（浏览器 print API）
[导出图片]   →  截图当前报表区域
[分享链接]   →  生成带参数的链接，接收方打开后重新运行插件得到同样结果
[存档报告]   →  将本次结果快照保存到平台，可随时回看（不需重新运行）
```

---

## 十一、技术选型

| 层次 | 技术 | 说明 |
|------|------|------|
| 插件运行环境 | Python 3.10+ | 数据分析生态最丰富 |
| 沙箱隔离 | RestrictedPython / 子进程 + seccomp | 安全执行用户代码 |
| 插件调度 | 主服务内置任务队列 | 管理插件并发与超时 |
| 结果推送 | WebSocket / SSE | 实时推送到前端 |
| 插件存储 | 数据库（脚本文本 + 元数据） | 版本管理、权限控制 |
| 前端渲染 | Canvas 2D / ECharts / 自定义表格 | 对应各输出类型 |
