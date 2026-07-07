"""
app/api/parsers.py

解析器查询接口。

前端获取解析器列表，展示给用户选择，用户选定 parser_id 后
传给 POST /api/recordings/load 加载录包。
"""

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_registry
from parsers.registry import ParserRegistry

router = APIRouter(prefix="/api/parsers", tags=["parsers"])


@router.get("", summary="获取所有解析器列表")
def list_parsers(
    registry: ParserRegistry = Depends(get_registry),
) -> list[dict]:
    """
    返回当前注册的所有解析器及其详细信息。
    前端根据返回列表展示选项，用户选定后取 parser_id 使用。
    """
    return [p.to_summary() for p in registry.all()]


@router.get("/{parser_id}", summary="获取指定解析器详情")
def get_parser(
    parser_id: str,
    registry: ParserRegistry = Depends(get_registry),
) -> dict:
    """按 parser_id 获取单个解析器的详细信息。"""
    try:
        return registry.get(parser_id).to_summary()
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Parser '{parser_id}' not found.",
        )
