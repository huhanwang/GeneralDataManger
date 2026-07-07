"""
app/deps.py

FastAPI 依赖注入工厂函数。

各路由通过 Depends(get_xxx) 获取共享实例，
实例在应用启动时挂载到 app.state，这里只做转发。
"""

from fastapi import Request
from parsers.registry import ParserRegistry


def get_registry(request: Request) -> ParserRegistry:
    """返回应用级 ParserRegistry 单例。"""
    return request.app.state.registry
