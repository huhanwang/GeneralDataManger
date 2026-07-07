"""
parsers/manager.py

管理解析器子进程的生命周期与通信。

设计原则：
- 每个 parser_id 对应一个子进程，按需启动，长期复用
- 子进程崩溃时自动重启，并重新加载上一个录包
- 同一 parser_id 的并发请求通过锁串行化，避免 stdin/stdout 交错
- 调用方只需传 parser_id，无需关心子进程细节
"""

from __future__ import annotations

import sys
import subprocess
import threading
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from parsers.base import (
    ParserCommand,
    ParserResponse,
    RecordingMeta,
    TopicFrame,
    TopicSchema,
)
from parsers.registry import ParserInfo, ParserRegistry

logger = logging.getLogger(__name__)


class ParserError(Exception):
    """解析器子进程返回 error 状态时抛出。"""


# ---------------------------------------------------------------------------
# 子进程状态
# ---------------------------------------------------------------------------

@dataclass
class _ProcState:
    """单个解析器子进程的运行状态。"""
    proc:          subprocess.Popen
    parser_id:     str
    module:        str
    loaded_path:   Optional[str]       = None
    loaded_topics: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# ParserManager
# ---------------------------------------------------------------------------

class ParserManager:
    """
    统一管理所有解析器子进程。

    用法：
        registry = ParserRegistry()
        manager  = ParserManager(registry)

        # 加载录包（需指定 parser_id）
        meta = manager.load("/data/rec.db3", parser_id="demo_db3")

        # 查询数据（用 recording_id 即可）
        frames = manager.get_frames(meta.recording_id, "laneline_list", 0.0, 30.0)
        schema = manager.get_schema(meta.recording_id, "laneline_list")

        manager.shutdown()
    """

    def __init__(self,
                 registry: ParserRegistry,
                 project_root: Optional[Path] = None):
        """
        registry:     ParserRegistry 实例，用于查找 parser_id 对应的模块路径。
        project_root: backend 根目录，子进程以此为 cwd。
                      默认取本文件所在目录的上级（即 backend/）。
        """
        self._registry   = registry
        self._root       = project_root or Path(__file__).parent.parent
        self._states:    dict[str, _ProcState]       = {}   # parser_id → ProcState
        self._locks:     dict[str, threading.Lock]   = defaultdict(threading.Lock)
        self._rec_parser: dict[str, str]             = {}   # recording_id → parser_id

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def load(self, path: str, parser_id: str,
             topics: Optional[list[str]] = None) -> RecordingMeta:
        """
        用指定解析器加载录包文件。
        parser_id 由调用方通过 registry.find() 确定后传入。
        """
        # 验证 parser_id 存在
        self._registry.get(parser_id)

        resp = self._call(
            parser_id,
            ParserCommand(cmd="load", path=path, topics=topics)
        )
        meta = RecordingMeta.from_dict(resp.data)
        self._rec_parser[meta.recording_id] = parser_id
        return meta

    def get_frames(self, recording_id: str, topic: str,
                   t_from: float, t_to: float) -> list[TopicFrame]:
        """查询指定录包、topic、时间范围内的所有帧。"""
        parser_id = self._require_parser_id(recording_id)
        resp = self._call(parser_id, ParserCommand(
            cmd="get_frames", topic=topic, t_from=t_from, t_to=t_to
        ))
        return [TopicFrame.from_dict(d) for d in resp.data]

    def get_schema(self, recording_id: str, topic: str) -> TopicSchema:
        """查询指定 topic 的字段结构。"""
        parser_id = self._require_parser_id(recording_id)
        resp = self._call(parser_id, ParserCommand(cmd="get_schema", topic=topic))
        return TopicSchema.from_dict(resp.data)

    def ping(self, parser_id: str) -> bool:
        """检测指定解析器子进程是否存活。"""
        try:
            resp = self._call(parser_id, ParserCommand(cmd="ping"))
            return resp.status == "ok"
        except Exception:
            return False

    def shutdown(self) -> None:
        """向所有子进程发送 exit 并等待退出，应用关闭时调用。"""
        for parser_id, state in list(self._states.items()):
            with self._locks[parser_id]:
                try:
                    self._write(state.proc, ParserCommand(cmd="exit"))
                    state.proc.wait(timeout=5)
                except Exception:
                    state.proc.kill()
                finally:
                    self._states.pop(parser_id, None)
        logger.info("ParserManager shutdown complete")

    # ------------------------------------------------------------------
    # 内部：IPC 调用
    # ------------------------------------------------------------------

    def _call(self, parser_id: str, cmd: ParserCommand) -> ParserResponse:
        """
        向指定解析器子进程发送指令，等待响应。
        崩溃时自动重启并恢复录包加载状态。
        """
        with self._locks[parser_id]:
            state = self._ensure_alive(parser_id)
            try:
                return self._roundtrip(state, cmd)
            except Exception as e:
                logger.warning("Parser '%s' error: %s — restarting", parser_id, e)
                self._kill(parser_id)
                state = self._ensure_alive(parser_id)
                # 重启后恢复上次加载的录包
                if state.loaded_path and cmd.cmd != "load":
                    self._roundtrip(state, ParserCommand(
                        cmd="load",
                        path=state.loaded_path,
                        topics=state.loaded_topics,
                    ))
                return self._roundtrip(state, cmd)

    def _roundtrip(self, state: _ProcState, cmd: ParserCommand) -> ParserResponse:
        """发送一条指令，读取一行响应。"""
        self._write(state.proc, cmd)
        line = state.proc.stdout.readline()
        if not line:
            raise RuntimeError("Subprocess stdout closed unexpectedly")

        resp = ParserResponse.from_json(line.strip())
        if resp.status == "error":
            raise ParserError(resp.message)

        if cmd.cmd == "load" and resp.status == "ok":
            state.loaded_path   = cmd.path
            state.loaded_topics = cmd.topics

        return resp

    @staticmethod
    def _write(proc: subprocess.Popen, cmd: ParserCommand) -> None:
        proc.stdin.write(cmd.to_json() + "\n")
        proc.stdin.flush()

    # ------------------------------------------------------------------
    # 内部：子进程管理
    # ------------------------------------------------------------------

    def _ensure_alive(self, parser_id: str) -> _ProcState:
        """返回存活的子进程，不存在或已退出则重新启动。"""
        state = self._states.get(parser_id)
        if state is None or state.proc.poll() is not None:
            state = self._start(parser_id)
            self._states[parser_id] = state
        return state

    def _start(self, parser_id: str) -> _ProcState:
        """启动解析器子进程，ping 确认就绪。"""
        info = self._registry.get(parser_id)
        logger.info("Starting parser '%s' (module: %s)", parser_id, info.module)

        proc = subprocess.Popen(
            [sys.executable, "-m", info.module],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(self._root),
        )

        state = _ProcState(proc=proc, parser_id=parser_id, module=info.module)

        try:
            self._write(proc, ParserCommand(cmd="ping"))
            line = proc.stdout.readline()
            if not line:
                stderr = proc.stderr.read()
                raise RuntimeError(
                    f"Parser '{parser_id}' failed to start.\nstderr:\n{stderr}"
                )
            resp = ParserResponse.from_json(line.strip())
            if resp.status != "ok":
                raise RuntimeError(
                    f"Parser '{parser_id}' ping failed: {resp.message}"
                )
        except Exception:
            proc.kill()
            raise

        logger.info("Parser '%s' started (pid=%d)", parser_id, proc.pid)
        return state

    def _kill(self, parser_id: str) -> None:
        """强制终止子进程。"""
        state = self._states.pop(parser_id, None)
        if state:
            state.proc.kill()
            logger.warning("Parser '%s' killed", parser_id)

    def _require_parser_id(self, recording_id: str) -> str:
        """根据 recording_id 反查 parser_id，未找到时报错。"""
        pid = self._rec_parser.get(recording_id)
        if pid is None:
            raise ValueError(
                f"Unknown recording_id '{recording_id}'. "
                "Call manager.load() first."
            )
        return pid
