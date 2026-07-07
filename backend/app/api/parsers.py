"""
app/api/parsers.py

解析器注册表查询接口，供前端逐步筛选可用的解析器。

前端选择流程：
  1. GET /api/parsers/organizations          → 获取所有组织
  2. GET /api/parsers/formats?org=X          → 获取该组织的数据格式
  3. GET /api/parsers/projects?org=X&fmt=Y   → 获取可选项目（可跳过）
  4. GET /api/parsers/match?org=X&fmt=Y&...  → 匹配解析器列表
  5. 用户确认 parser_id → 调用 POST /api/recordings/load 加载录包
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_registry
from parsers.registry import ParserRegistry

router = APIRouter(prefix="/api/parsers", tags=["parsers"])


# ---------------------------------------------------------------------------
# 逐步筛选接口
# ---------------------------------------------------------------------------

@router.get(
    "/organizations",
    summary="获取所有组织列表",
    response_description="组织名称数组",
)
def list_organizations(
    registry: ParserRegistry = Depends(get_registry),
) -> list[str]:
    """返回当前注册表中所有组织名称，用于前端第一步选择。"""
    return registry.list_organizations()


@router.get(
    "/formats",
    summary="获取指定组织的数据格式列表",
)
def list_formats(
    org: str = Query(..., description="组织名称"),
    registry: ParserRegistry = Depends(get_registry),
) -> list[str]:
    """返回指定组织下所有可用的数据格式，用于前端第二步选择。"""
    formats = registry.list_formats(org)
    if not formats:
        raise HTTPException(
            status_code=404,
            detail=f"Organization '{org}' not found or has no parsers.",
        )
    return formats


@router.get(
    "/projects",
    summary="获取指定组织+格式下的可选项目列表",
)
def list_projects(
    org: str    = Query(..., description="组织名称"),
    fmt: str    = Query(..., description="数据格式，如 db3"),
    registry: ParserRegistry = Depends(get_registry),
) -> list[str]:
    """
    返回该组织+格式下所有有项目约束的解析器所覆盖的项目列表。
    结果为空时表示该格式的解析器均为通用型（不区分项目），前端可跳过项目选择。
    """
    return registry.list_projects(org, fmt)


@router.get(
    "/match",
    summary="匹配解析器",
)
def match_parsers(
    org:     str           = Query(...,  description="组织名称（必填）"),
    fmt:     str           = Query(...,  description="数据格式（必填）"),
    project: Optional[str] = Query(None, description="项目名称（可选）"),
    date:    Optional[date]= Query(None, description="录包采集日期 YYYY-MM-DD（可选）"),
    registry: ParserRegistry = Depends(get_registry),
) -> list[dict]:
    """
    根据组织、格式（必填）以及项目、日期（可选）匹配解析器。

    - 返回多条结果时，按特异性排序（有期间约束 > 有项目约束 > 通用）
    - 返回空列表表示没有匹配的解析器
    - 通常情况下应返回唯一一条，前端直接使用其 parser_id
    """
    results = registry.find(org, fmt, project=project, date=date)
    return [r.to_summary() for r in results]


# ---------------------------------------------------------------------------
# 直接查询接口
# ---------------------------------------------------------------------------

@router.get(
    "",
    summary="获取所有解析器列表",
)
def list_all(
    registry: ParserRegistry = Depends(get_registry),
) -> list[dict]:
    """返回注册表中全部解析器的摘要信息，可用于管理页面展示。"""
    return [p.to_summary() for p in registry.all()]


@router.get(
    "/{parser_id}",
    summary="获取指定解析器详情",
)
def get_parser(
    parser_id: str,
    registry: ParserRegistry = Depends(get_registry),
) -> dict:
    """按 parser_id 获取解析器完整信息。"""
    try:
        return registry.get(parser_id).to_summary()
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Parser '{parser_id}' not found.",
        )
