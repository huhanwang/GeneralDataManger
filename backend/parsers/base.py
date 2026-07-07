"""
parsers/base.py

所有解析器共享的数据结构、IPC 通信协议和抽象接口。

每种格式（db3/db4/noah_txt）以独立子进程运行，通过 stdin/stdout
传输 JSON 消息与主进程通信。本文件在主进程和子进程中均会被导入。
"""

from __future__ import annotations

import json
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal


# ---------------------------------------------------------------------------
# 核心数据结构
# ---------------------------------------------------------------------------

@dataclass
class FieldDef:
    """描述 proto message 中的一个字段。"""
    name:        str
    type:        str        # float32 | float64 | int32 | int64 | string | bool | bytes | message | repeated
    description: str = ""
    unit:        str = ""   # 单位，如 "m"  "m/s"  "rad"  "%"
    children:    list[FieldDef] = field(default_factory=list)  # 嵌套 message 的子字段

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"name": self.name, "type": self.type}
        if self.description:
            d["description"] = self.description
        if self.unit:
            d["unit"] = self.unit
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> FieldDef:
        return cls(
            name=d["name"],
            type=d["type"],
            description=d.get("description", ""),
            unit=d.get("unit", ""),
            children=[cls.from_dict(c) for c in d.get("children", [])],
        )


@dataclass
class TopicSchema:
    """一个 topic 的字段结构，供 HTTP API 返回和 AI 理解数据含义。"""
    topic:       str
    proto_type:  str              # proto message 全名，如 "perception.ObstacleList"
    fields:      list[FieldDef]
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "topic":       self.topic,
            "proto_type":  self.proto_type,
            "description": self.description,
            "fields":      [f.to_dict() for f in self.fields],
        }

    @classmethod
    def from_dict(cls, d: dict) -> TopicSchema:
        return cls(
            topic=d["topic"],
            proto_type=d.get("proto_type", ""),
            description=d.get("description", ""),
            fields=[FieldDef.from_dict(f) for f in d.get("fields", [])],
        )


@dataclass
class TopicFrame:
    """某一 topic 在某一时刻的单帧数据。"""
    topic: str
    t:     float    # 时间戳（秒）
    data:  dict     # proto 反序列化后的纯 Python dict，不含任何 proto 类型

    def to_dict(self) -> dict:
        return {"topic": self.topic, "t": self.t, "data": self.data}

    @classmethod
    def from_dict(cls, d: dict) -> TopicFrame:
        return cls(topic=d["topic"], t=d["t"], data=d["data"])


@dataclass
class RecordingMeta:
    """录包文件的元信息，load 完成后返回给主进程。"""
    recording_id: str
    format:       str               # "db3" | "db4" | "noah_txt"
    path:         str
    t_start:      float             # 最早帧时间戳（秒）
    t_end:        float             # 最晚帧时间戳（秒）
    duration:     float             # t_end - t_start
    topics:       list[str]         # 所有可用 topic 名称
    frame_counts: dict[str, int]    # topic -> 总帧数

    def to_dict(self) -> dict:
        return {
            "recording_id": self.recording_id,
            "format":       self.format,
            "path":         self.path,
            "t_start":      self.t_start,
            "t_end":        self.t_end,
            "duration":     self.duration,
            "topics":       self.topics,
            "frame_counts": self.frame_counts,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RecordingMeta:
        return cls(**d)


# ---------------------------------------------------------------------------
# 子进程 IPC 协议
# ---------------------------------------------------------------------------

@dataclass
class ParserCommand:
    """主进程发给子进程的指令（写入子进程 stdin，每条一行 JSON）。"""
    cmd: Literal["load", "get_frames", "get_schema", "ping", "exit"]

    # load 参数
    path:   str | None       = None   # 录包文件路径
    topics: list[str] | None = None   # 指定加载的 topic，None 表示全部

    # get_frames 参数
    topic:  str | None   = None   # topic 名称（get_frames / get_schema 共用）
    t_from: float | None = None   # 起始时间（秒）
    t_to:   float | None = None   # 结束时间（秒）

    def to_json(self) -> str:
        d: dict[str, Any] = {"cmd": self.cmd}
        if self.path   is not None: d["path"]   = self.path
        if self.topics is not None: d["topics"] = self.topics
        if self.topic  is not None: d["topic"]  = self.topic
        if self.t_from is not None: d["t_from"] = self.t_from
        if self.t_to   is not None: d["t_to"]   = self.t_to
        return json.dumps(d)

    @classmethod
    def from_json(cls, s: str) -> ParserCommand:
        d = json.loads(s)
        valid = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass
class ParserResponse:
    """子进程返回给主进程的响应（写入子进程 stdout，每条一行 JSON）。"""
    status:  Literal["ok", "error", "progress"]
    data:    Any = None    # ok: 结果数据；progress: {"ratio": 0.6}
    message: str = ""      # error: 错误信息；progress: 提示文字

    def to_json(self) -> str:
        return json.dumps({
            "status":  self.status,
            "data":    self.data,
            "message": self.message,
        })

    @classmethod
    def from_json(cls, s: str) -> ParserResponse:
        d = json.loads(s)
        return cls(
            status=d["status"],
            data=d.get("data"),
            message=d.get("message", ""),
        )

    @classmethod
    def ok(cls, data: Any = None) -> ParserResponse:
        return cls(status="ok", data=data)

    @classmethod
    def error(cls, message: str) -> ParserResponse:
        return cls(status="error", message=message)

    @classmethod
    def progress(cls, ratio: float, message: str = "") -> ParserResponse:
        return cls(status="progress", data={"ratio": ratio}, message=message)


# ---------------------------------------------------------------------------
# 解析器抽象接口
# ---------------------------------------------------------------------------

class AbstractParser(ABC):
    """
    所有格式解析器的基类，在各子进程内部使用。

    每个子进程的 __main__.py 实例化具体 Parser 后调用 run_subprocess_loop()，
    通用循环负责读取 IPC 指令、调用以下方法、写回响应。
    子类只需实现业务逻辑，无需关心 IPC 通信细节。

    示例（parsers/db3/__main__.py）：
        from parsers.base import run_subprocess_loop
        from parsers.db3.parser import Db3Parser

        if __name__ == "__main__":
            run_subprocess_loop(Db3Parser())
    """

    @abstractmethod
    def load(self, path: str, topics: list[str] | None = None) -> RecordingMeta:
        """
        打开录包文件，扫描所有 topic 和时间戳范围，建立内部索引。
        不需要将所有帧数据读入内存。
        返回：录包元信息（时长、topic 列表、各 topic 帧数）。
        """

    @abstractmethod
    def get_frames(self, topic: str,
                   t_from: float, t_to: float) -> Iterator[TopicFrame]:
        """
        按时间范围逐帧 yield 指定 topic 的数据，按时间戳升序。
        实现时应避免将整段数据一次性加载到内存。
        """

    @abstractmethod
    def get_schema(self, topic: str) -> TopicSchema:
        """返回指定 topic 的字段结构定义。"""

    def get_frames_list(self, topic: str,
                        t_from: float, t_to: float) -> list[TopicFrame]:
        """便捷方法：将 get_frames() 收集为列表，小数据量时使用。"""
        return list(self.get_frames(topic, t_from, t_to))


# ---------------------------------------------------------------------------
# 子进程主循环
# ---------------------------------------------------------------------------

def run_subprocess_loop(parser: AbstractParser) -> None:
    """
    标准子进程主循环。
    从 stdin 逐行读取 JSON 指令 → 调用 parser → 将结果写入 stdout。

    每个解析器的 __main__.py 调用此函数即可，无需自行处理 IPC 细节。
    """
    while True:
        line = sys.stdin.readline()
        if not line:
            # stdin 已关闭，主进程退出
            break

        line = line.strip()
        if not line:
            continue

        try:
            cmd = ParserCommand.from_json(line)
        except Exception as e:
            _send(ParserResponse.error(f"Invalid command JSON: {e}"))
            continue

        try:
            _dispatch(parser, cmd)
        except Exception as e:
            _send(ParserResponse.error(f"Unhandled error in parser: {e}"))


def _dispatch(parser: AbstractParser, cmd: ParserCommand) -> None:
    """将指令路由到对应的 parser 方法。"""

    if cmd.cmd == "ping":
        _send(ParserResponse.ok("pong"))

    elif cmd.cmd == "exit":
        _send(ParserResponse.ok())
        sys.exit(0)

    elif cmd.cmd == "load":
        if not cmd.path:
            _send(ParserResponse.error("load requires 'path'"))
            return
        meta = parser.load(cmd.path, cmd.topics)
        _send(ParserResponse.ok(meta.to_dict()))

    elif cmd.cmd == "get_frames":
        if cmd.topic is None or cmd.t_from is None or cmd.t_to is None:
            _send(ParserResponse.error("get_frames requires 'topic', 't_from', 't_to'"))
            return
        frames = parser.get_frames_list(cmd.topic, cmd.t_from, cmd.t_to)
        _send(ParserResponse.ok([f.to_dict() for f in frames]))

    elif cmd.cmd == "get_schema":
        if not cmd.topic:
            _send(ParserResponse.error("get_schema requires 'topic'"))
            return
        schema = parser.get_schema(cmd.topic)
        _send(ParserResponse.ok(schema.to_dict()))

    else:
        _send(ParserResponse.error(f"Unknown command: {cmd.cmd}"))


def _send(response: ParserResponse) -> None:
    """将响应写入 stdout，每条一行，立即 flush 确保主进程能及时读到。"""
    sys.stdout.write(response.to_json() + "\n")
    sys.stdout.flush()
