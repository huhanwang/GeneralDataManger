"""
parsers/manager.py

管理解析器子进程的生命周期与通信。

设计原则：
- 每种格式一个子进程（db3 / db4 / noah_txt），按需启动，长期复用
- 子进程崩溃时自动重启，并重新加载上一个录包
- 同一格式的并发请求通过锁串行化，避免 stdin/stdout 交错
- 主进程通过本类与子进程交互，调用方无需感知子进程存在
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
    AbstractParser,
    ParserCommand,
    ParserResponse,
    RecordingMeta,
    TopicFrame,
    TopicSchema,
)

logger = logging.getLogger(__name__)

# 文件后缀 → 格式名（与 parsers/ 下子目录名对应）
_SUFFIX_TO_FORMAT: dict[str, str] = {
    ".db3":  "db3",
    ".db4":  "db4",
    ".txt":  "noah_txt",
}


class ParserError(Exception):
    """解析器子进程返回 error 状态时抛出。"""


# ---------------------------------------------------------------------------
# 子进程状态
# ---------------------------------------------------------------------------

@dataclass
class _ProcState:
    """单个格式子进程的运行状态。"""
    proc:         subprocess.Popen
    loaded_path:  Optional[str] = None   # 子进程当前已加载的录包路径
    loaded_topics: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# ParserManager
# ---------------------------------------------------------------------------

class ParserManager:
    """
    统一管理所有格式的解析器子进程。

    用法：
        manager = ParserManager()

        # 加载录包（自动识别格式，启动对应子进程）
        meta = manager.load("/data/rec.db3")

        # 查询数据（用 recording_id 即可，无需关心格式）
        frames = manager.get_frames(meta.recording_id, "laneline_list", 0.0, 30.0)
        schema = manager.get_schema(meta.recording_id, "laneline_list")

        # 关闭（应用退出时调用）
        manager.shutdown()
    """

    def __init__(self, project_root: Optional[Path] = None):
        """
        project_root: backend 根目录，子进程以此为 cwd 启动。
                      默认取本文件所在目录的上级（即 backend/）。
        """
        self._root = project_root or Path(__file__).parent.parent
        self._states: dict[str, _ProcState] = {}          # format → ProcState
        self._locks:  dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._rec_fmt: dict[str, str] = {}                 # recording_id → format

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def load(self, path: str,
             topics: list[str] | None = None) -> RecordingMeta:
        """
        加载录包文件。
        自动识别格式，启动对应子进程（已启动则复用），返回录包元信息。
        """
        fmt = _detect_format(path)
        resp = self._call(fmt, ParserCommand(cmd="load", path=path, topics=topics))
        meta = RecordingMeta.from_dict(resp.data)
        self._rec_fmt[meta.recording_id] = fmt
        return meta

    def get_frames(self, recording_id: str, topic: str,
                   t_from: float, t_to: float) -> list[TopicFrame]:
        """查询指定录包、topic、时间范围内的所有帧。"""
        fmt   = self._require_format(recording_id)
        resp  = self._call(fmt, ParserCommand(
            cmd="get_frames", topic=topic, t_from=t_from, t_to=t_to
        ))
        return [TopicFrame.from_dict(d) for d in resp.data]

    def get_schema(self, recording_id: str, topic: str) -> TopicSchema:
        """查询指定 topic 的字段结构。"""
        fmt  = self._require_format(recording_id)
        resp = self._call(fmt, ParserCommand(cmd="get_schema", topic=topic))
        return TopicSchema.from_dict(resp.data)

    def ping(self, fmt: str) -> bool:
        """检测指定格式的子进程是否存活，可用于健康检查。"""
        try:
            resp = self._call(fmt, ParserCommand(cmd="ping"))
            return resp.status == "ok"
        except Exception:
            return False

    def shutdown(self) -> None:
        """向所有子进程发送 exit 指令并等待退出，应在应用关闭时调用。"""
        for fmt, state in list(self._states.items()):
            with self._locks[fmt]:
                try:
                    self._write(state.proc, ParserCommand(cmd="exit"))
                    state.proc.wait(timeout=5)
                except Exception:
                    state.proc.kill()
                finally:
                    self._states.pop(fmt, None)
        logger.info("ParserManager shutdown complete")

    # ------------------------------------------------------------------
    # 内部：IPC 调用
    # ------------------------------------------------------------------

    def _call(self, fmt: str, cmd: ParserCommand) -> ParserResponse:
        """
        向指定格式的子进程发送指令并等待响应。
        同一格式的调用串行执行（锁保护），避免 stdin/stdout 交错。
        子进程崩溃时自动重启并重新加载录包。
        """
        with self._locks[fmt]:
            state = self._ensure_alive(fmt)
            try:
                return self._roundtrip(state, cmd)
            except Exception as e:
                logger.warning("Parser %s error: %s — restarting", fmt, e)
                self._kill(fmt)
                # 重启后若有已加载的录包，先恢复加载
                state = self._ensure_alive(fmt)
                if state.loaded_path and cmd.cmd != "load":
                    self._roundtrip(state, ParserCommand(
                        cmd="load",
                        path=state.loaded_path,
                        topics=state.loaded_topics,
                    ))
                return self._roundtrip(state, cmd)

    def _roundtrip(self, state: _ProcState,
                   cmd: ParserCommand) -> ParserResponse:
        """写入指令，读取一行响应，处理 error 状态。"""
        self._write(state.proc, cmd)
        line = state.proc.stdout.readline()
        if not line:
            raise RuntimeError("Subprocess closed stdout unexpectedly")

        resp = ParserResponse.from_json(line.strip())

        if resp.status == "error":
            raise ParserError(resp.message)

        # 记录子进程已加载的录包，供崩溃重启后恢复
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

    def _ensure_alive(self, fmt: str) -> _ProcState:
        """返回存活的子进程状态，不存在或已退出则重新启动。"""
        state = self._states.get(fmt)
        if state is None or state.proc.poll() is not None:
            state = self._start(fmt)
            self._states[fmt] = state
        return state

    def _start(self, fmt: str) -> _ProcState:
        """启动指定格式的解析器子进程，并用 ping 确认就绪。"""
        logger.info("Starting %s parser subprocess", fmt)
        proc = subprocess.Popen(
            [sys.executable, "-m", f"parsers.{fmt}"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,          # 行缓冲，确保每行 JSON 及时到达
            cwd=str(self._root),
        )
        # 启动后 ping 一次，确认子进程正常运行
        try:
            self._write(proc, ParserCommand(cmd="ping"))
            line = proc.stdout.readline()
            if not line:
                stderr = proc.stderr.read()
                raise RuntimeError(
                    f"Parser '{fmt}' failed to start.\nstderr:\n{stderr}"
                )
            resp = ParserResponse.from_json(line.strip())
            if resp.status != "ok":
                raise RuntimeError(f"Parser '{fmt}' ping failed: {resp.message}")
        except Exception:
            proc.kill()
            raise

        logger.info("%s parser subprocess started (pid=%d)", fmt, proc.pid)
        return _ProcState(proc=proc)

    def _kill(self, fmt: str) -> None:
        """强制结束子进程，从状态表中移除。"""
        state = self._states.pop(fmt, None)
        if state:
            state.proc.kill()
            logger.warning("%s parser subprocess killed", fmt)

    def _require_format(self, recording_id: str) -> str:
        """根据 recording_id 查找格式，未找到时抛出有意义的错误。"""
        fmt = self._rec_fmt.get(recording_id)
        if fmt is None:
            raise ValueError(
                f"Unknown recording_id '{recording_id}'. "
                "Call manager.load() first."
            )
        return fmt


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _detect_format(path: str) -> str:
    """根据文件后缀推断格式名称。"""
    suffix = Path(path).suffix.lower()
    fmt = _SUFFIX_TO_FORMAT.get(suffix)
    if fmt is None:
        supported = ", ".join(_SUFFIX_TO_FORMAT.keys())
        raise ValueError(
            f"Unsupported file format '{suffix}'. "
            f"Supported: {supported}"
        )
    return fmt
