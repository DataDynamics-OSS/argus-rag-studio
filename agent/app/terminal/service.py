"""Remote terminal session management."""

import asyncio
import fcntl
import logging
import os
import pty
import signal
import struct
import termios
import time
from dataclasses import dataclass, field

from app.core.config import settings

logger = logging.getLogger(__name__)

# Seconds without any WebSocket activity before a session is considered stale.
SESSION_IDLE_TIMEOUT = 120


@dataclass
class TerminalSession:
    """Represents an active terminal session."""

    session_id: str
    pid: int
    fd: int
    active: bool = True
    last_activity: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = time.monotonic()

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_activity


class TerminalManager:
    """Manage multiple terminal sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._reaper_task: asyncio.Task | None = None

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def start_reaper(self) -> None:
        """Start background task that cleans up stale sessions."""
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(self._reap_stale_sessions())

    async def _reap_stale_sessions(self) -> None:
        """Periodically check for and close stale sessions."""
        while True:
            await asyncio.sleep(30)
            stale = [
                sid for sid, s in self._sessions.items() if s.idle_seconds > SESSION_IDLE_TIMEOUT
            ]
            for sid in stale:
                logger.warning(
                    "Closing stale terminal session: %s (idle %.0fs)",
                    sid,
                    self._sessions[sid].idle_seconds,
                )
                self.close_session(sid)
            # Also reap any zombie child processes that were left behind.
            self._reap_zombies()

    @staticmethod
    def _reap_zombies() -> None:
        """Non-blocking reap of any finished child processes."""
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
                logger.debug("Reaped zombie child pid=%d", pid)
            except ChildProcessError:
                break

    def create_session(self, session_id: str) -> TerminalSession:
        """Create a new PTY-based terminal session."""
        if len(self._sessions) >= settings.terminal_max_sessions:
            raise RuntimeError(
                f"Maximum terminal sessions ({settings.terminal_max_sessions}) reached"
            )

        pid, fd = pty.openpty()
        child_pid = os.fork()

        if child_pid == 0:
            # Child process
            os.close(pid)
            os.setsid()
            os.dup2(fd, 0)
            os.dup2(fd, 1)
            os.dup2(fd, 2)
            if fd > 2:
                os.close(fd)
            # Change to the configured home directory so the shell
            # doesn't start in the agent's working directory.
            try:
                os.chdir(settings.terminal_home_dir)
            except OSError:
                os.chdir("/")
            os.environ["HOME"] = settings.terminal_home_dir
            os.execvp(settings.terminal_shell, [settings.terminal_shell, "-l"])
        else:
            # Parent process
            os.close(fd)
            session = TerminalSession(
                session_id=session_id,
                pid=child_pid,
                fd=pid,
            )
            self._sessions[session_id] = session
            logger.info(
                "Terminal session created: %s (pid=%d, active=%d/%d)",
                session_id,
                child_pid,
                len(self._sessions),
                settings.terminal_max_sessions,
            )
            return session

    async def read_output(self, session_id: str, size: int = 4096) -> bytes:
        """Read output from a terminal session."""
        session = self._get_session(session_id)
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, os.read, session.fd, size)
            session.touch()
            return data
        except OSError:
            session.active = False
            return b""

    def write_input(self, session_id: str, data: bytes) -> None:
        """Write input to a terminal session."""
        session = self._get_session(session_id)
        os.write(session.fd, data)
        session.touch()

    def resize(self, session_id: str, rows: int, cols: int) -> None:
        """Resize a terminal session."""
        session = self._get_session(session_id)
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(session.fd, termios.TIOCSWINSZ, winsize)
        session.touch()

    def close_session(self, session_id: str) -> None:
        """Close and clean up a terminal session.

        Order of operations is important:
        1. Remove from dict first so new connections aren't blocked.
        2. Close the PTY fd so any blocked os.read() in the executor unblocks.
        3. Send SIGTERM / SIGKILL to the child.
        4. Non-blocking waitpid to avoid freezing the asyncio event loop.
        """
        session = self._sessions.pop(session_id, None)
        if session is None:
            return

        session.active = False

        # 1) Close the PTY master fd first – this unblocks any pending
        #    os.read() running in the thread-pool executor.
        try:
            os.close(session.fd)
        except OSError:
            pass

        # 2) Terminate the child process.
        try:
            os.kill(session.pid, signal.SIGTERM)
        except OSError:
            pass

        # 3) Non-blocking waitpid – do NOT use blocking waitpid(pid, 0)
        #    because it freezes the asyncio event loop.
        try:
            pid, _ = os.waitpid(session.pid, os.WNOHANG)
            if pid == 0:
                # Child hasn't exited yet after SIGTERM; send SIGKILL.
                try:
                    os.kill(session.pid, signal.SIGKILL)
                except OSError:
                    pass
                # Try once more (non-blocking). The reaper task will
                # catch any remaining zombies periodically.
                try:
                    os.waitpid(session.pid, os.WNOHANG)
                except (OSError, ChildProcessError):
                    pass
        except (OSError, ChildProcessError):
            pass

        logger.info(
            "Terminal session closed: %s (pid=%d, remaining=%d)",
            session_id,
            session.pid,
            len(self._sessions),
        )

    def close_all(self) -> None:
        """Close all terminal sessions."""
        if self._reaper_task and not self._reaper_task.done():
            self._reaper_task.cancel()
        for session_id in list(self._sessions.keys()):
            self.close_session(session_id)

    def _get_session(self, session_id: str) -> TerminalSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Terminal session not found: {session_id}")
        return session


terminal_manager = TerminalManager()
