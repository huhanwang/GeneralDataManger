# GeneralDataManger

通用数据管理与分析平台，面向自动驾驶算法团队。

## 架构

三层独立，契约连接：

- **后端**（Python + FastAPI）：解析录包 → proto 时间序列 → HTTP Query API
- **插件层**（Python 脚本）：查询数据，转换为可视化格式或做分析，生成报表
- **前端**（Vue 3 + TypeScript）：渲染可视化结果和分析报表

## 文档

见 `docs/` 目录：

| 文档 | 内容 |
|------|------|
| `ARCHITECTURE.md` | 三层架构总览，**先读这个** |
| `DEVPLAN.md` | 开发计划与进度 |
| `BACKEND_DESIGN.md` | 后端详细设计 |
| `PLUGIN_SYSTEM.md` | 插件系统设计 |
| `DESIGN.md` | 平台设计理念 |
| `PLATFORM.md` | 三大平台功能规划 |

## 快速开始

```bash
# 后端
cd backend
pip install -e .
uvicorn app.main:app --reload --port 8080
```
