"""
parsers/registry.py

解析器注册表。

扫描 parsers/ 下所有 registry.yaml，自动发现全部解析器。
提供多维度查询接口供前端选择和后端匹配使用。

查询维度：
  必选：organization（组织）、format（数据格式）
  可选：project（项目）、date（录包采集日期）

目录约定：
  parsers/{org}/{parser_name}/registry.yaml
  对应模块：parsers.{org}.{parser_name}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class TopicInfo:
    """registry.yaml 中声明的 topic 描述。"""
    name:        str
    description: str = ""


@dataclass
class ParserInfo:
    """单个解析器的完整元信息，从 registry.yaml 加载。"""
    parser_id:    str
    name:         str
    organization: str
    format:       str           # 文件格式，如 "db3" "db4" "noah_txt"
    description:  str
    module:       str           # Python 模块路径，如 "parsers.demo.db3"
    directory:    Path          # registry.yaml 所在目录的绝对路径
    period_from:  Optional[date]         # 适用期间起始，None 表示无限制
    period_to:    Optional[date]         # 适用期间结束，None 表示无限制
    projects:     list[str]              # 适用项目列表，空列表表示通用
    topics:       list[TopicInfo]

    def covers_date(self, d: date) -> bool:
        """判断给定日期是否在此解析器的适用期间内。"""
        if self.period_from and d < self.period_from:
            return False
        if self.period_to and d > self.period_to:
            return False
        return True

    def matches_project(self, project: str) -> bool:
        """
        判断是否适用于给定项目。
        projects 为空列表时表示通用，匹配所有项目。
        """
        return not self.projects or project in self.projects

    def to_summary(self) -> dict:
        """返回前端列表展示所需的简要信息。"""
        return {
            "parser_id":    self.parser_id,
            "name":         self.name,
            "organization": self.organization,
            "format":       self.format,
            "description":  self.description,
            "period_from":  self.period_from.isoformat() if self.period_from else None,
            "period_to":    self.period_to.isoformat()   if self.period_to   else None,
            "projects":     self.projects,
            "topics":       [{"name": t.name, "description": t.description}
                             for t in self.topics],
        }


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

class ParserRegistry:
    """
    自动扫描 parsers/ 目录，发现所有 registry.yaml 并加载解析器信息。

    用法：
        registry = ParserRegistry()

        # 前端逐步缩小范围
        orgs    = registry.list_organizations()
        formats = registry.list_formats("CompanyA")
        projs   = registry.list_projects("CompanyA", "db3")

        # 匹配解析器
        matched = registry.find("CompanyA", "db3")               # 只用必选项
        matched = registry.find("CompanyA", "db3", project="NOA")
        matched = registry.find("CompanyA", "db3", date=date(2023,3,15))
        matched = registry.find("CompanyA", "db3", project="NOA", date=date(2023,3,15))

        # 直接按 ID 获取
        info = registry.get("companya_db3_2023h1")
    """

    def __init__(self, parsers_root: Optional[Path] = None):
        """
        parsers_root: parsers/ 目录路径。
                      默认取本文件所在目录（即 parsers/）。
        """
        self._root = parsers_root or Path(__file__).parent
        self._parsers: dict[str, ParserInfo] = {}
        self._load_all()

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        """递归扫描 _root/**/ 下所有 registry.yaml 并加载。"""
        yaml_files = list(self._root.rglob("registry.yaml"))
        if not yaml_files:
            logger.warning("No registry.yaml found under %s", self._root)
            return

        for yaml_path in sorted(yaml_files):
            try:
                info = self._load_one(yaml_path)
                if info.parser_id in self._parsers:
                    logger.warning(
                        "Duplicate parser_id '%s' in %s, skipping",
                        info.parser_id, yaml_path
                    )
                    continue
                self._parsers[info.parser_id] = info
                logger.debug("Loaded parser: %s (%s)", info.parser_id, info.name)
            except Exception as e:
                logger.error("Failed to load %s: %s", yaml_path, e)

        logger.info("ParserRegistry loaded %d parsers", len(self._parsers))

    def _load_one(self, yaml_path: Path) -> ParserInfo:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        _require_fields(data, yaml_path, ["parser_id", "name", "organization", "format"])

        directory = yaml_path.parent

        # 从目录路径推导模块路径：parsers/demo/db3 → parsers.demo.db3
        rel = directory.relative_to(self._root.parent)
        module = ".".join(rel.parts)

        period = data.get("period") or {}

        return ParserInfo(
            parser_id=data["parser_id"],
            name=data["name"],
            organization=data["organization"],
            format=data["format"],
            description=data.get("description", ""),
            module=module,
            directory=directory,
            period_from=_parse_date(period.get("from")),
            period_to=_parse_date(period.get("to")),
            projects=[str(p) for p in (data.get("projects") or [])],
            topics=[
                TopicInfo(
                    name=t["name"],
                    description=t.get("description", "")
                )
                for t in (data.get("topics") or [])
            ],
        )

    def reload(self) -> None:
        """重新扫描目录，热加载新增/修改的解析器。"""
        self._parsers.clear()
        self._load_all()

    # ------------------------------------------------------------------
    # 查询接口（供前端逐步筛选）
    # ------------------------------------------------------------------

    def list_organizations(self) -> list[str]:
        """返回所有组织名称，去重排序。"""
        return sorted({p.organization for p in self._parsers.values()})

    def list_formats(self, organization: str) -> list[str]:
        """返回指定组织下所有数据格式，去重排序。"""
        return sorted({
            p.format for p in self._parsers.values()
            if p.organization == organization
        })

    def list_projects(self, organization: str, format: str) -> list[str]:
        """
        返回指定组织+格式下所有项目名称。
        不包含空列表（通用解析器不属于特定项目）。
        """
        projects: set[str] = set()
        for p in self._parsers.values():
            if p.organization == organization and p.format == format:
                projects.update(p.projects)
        return sorted(projects)

    def find(
        self,
        organization: str,
        format: str,
        project: Optional[str] = None,
        date: Optional[date] = None,
    ) -> list[ParserInfo]:
        """
        查找匹配的解析器列表。

        必选：organization、format
        可选：project、date

        匹配规则：
          - project 不填：解析器 projects 为空（通用）或含指定项目都匹配
          - date 不填：不过滤期间
          - 多条结果按"特异性"排序：有期间约束 > 有项目约束 > 通用
        """
        results = []
        for p in self._parsers.values():
            if p.organization != organization:
                continue
            if p.format != format:
                continue
            if project is not None and not p.matches_project(project):
                continue
            if date is not None and not p.covers_date(date):
                continue
            results.append(p)

        # 特异性排序：约束越多越靠前（让最精确的匹配排第一）
        results.sort(key=_specificity, reverse=True)
        return results

    def get(self, parser_id: str) -> ParserInfo:
        """按 ID 获取解析器，不存在时抛出 KeyError。"""
        if parser_id not in self._parsers:
            raise KeyError(
                f"Parser '{parser_id}' not found. "
                f"Available: {list(self._parsers.keys())}"
            )
        return self._parsers[parser_id]

    def all(self) -> list[ParserInfo]:
        """返回所有已注册解析器列表。"""
        return list(self._parsers.values())

    def __len__(self) -> int:
        return len(self._parsers)

    def __repr__(self) -> str:
        return f"ParserRegistry({len(self._parsers)} parsers)"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _parse_date(value: object) -> Optional[date]:
    """将 yaml 中的日期值转为 date 对象，None / null 返回 None。"""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"Invalid date value: {value!r}")


def _specificity(p: ParserInfo) -> tuple:
    """
    计算解析器的特异性分数，用于排序。
    分数越高表示约束越精确，匹配优先级越高。
    """
    has_period  = int(p.period_from is not None or p.period_to is not None)
    has_project = int(bool(p.projects))
    return (has_period, has_project)


def _require_fields(data: dict, path: Path, fields: list[str]) -> None:
    missing = [f for f in fields if not data.get(f)]
    if missing:
        raise ValueError(
            f"{path}: missing required fields: {missing}"
        )
