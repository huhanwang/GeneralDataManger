"""
app/main.py

FastAPI 应用入口。

启动流程：
  1. 初始化 ParserRegistry（扫描 parsers/ 下所有 registry.yaml）
  2. 注册所有路由
  3. 启动服务

启动命令：
  cd backend
  uvicorn app.main:app --reload --port 8080
"""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import parsers as parsers_router
from parsers.registry import ParserRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 启动 ──────────────────────────────────────
    logger.info("Initializing ParserRegistry from %s", settings.parsers_root)
    app.state.registry = ParserRegistry(settings.parsers_root)
    logger.info("ParserRegistry ready: %d parsers", len(app.state.registry))

    yield

    # ── 关闭 ──────────────────────────────────────
    logger.info("Shutting down...")


# ---------------------------------------------------------------------------
# 应用
# ---------------------------------------------------------------------------

app = FastAPI(
    title="GeneralDataManger API",
    version="0.1.0",
    description="通用数据管理与分析平台后端",
    lifespan=lifespan,
)

# 开发阶段允许所有跨域（生产环境按需收紧）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# 路由注册
# ---------------------------------------------------------------------------

app.include_router(parsers_router.router)
