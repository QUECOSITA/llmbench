import asyncio
import os
import struct
import sys
import threading

from app.spawn import spawn_env
from app.tty_stream import TtyStream


class DownloadPty:
    """Cross-platform pseudo-terminal for streaming hf CLI downloads."""

    async def spawn(self) -> None:
        raise NotImplementedError

    async def read_events(self):
        raise NotImplementedError

    def cancel(self) -> None:
        raise NotImplementedError

    async def wait(self) -> int:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class PosixPtyStream(DownloadPty):
    """os.openpty-based implementation for Linux/macOS.

    os.openpty() defaults to a 0x0 terminal; tqdm queries the size and
    suppresses progress bars when it reads 0 columns/rows, so set a sane
    default on the slave before the child is spawned.
    """

    def __init__(self, cmd: list[str], env: dict[str, str] | None = None):
        self.cmd = list(cmd)
        self.env = dict(env) if env is not None else spawn_env()
        self._proc = None
        self._master_fd = None
        self._slave_fd = None
        self._queue: asyncio.Queue[bytes | None] | None = None
        self._reader_thread: threading.Thread | None = None

    async def spawn(self) -> None:
        import fcntl
        import termios

        master_fd, slave_fd = os.openpty()
        try:
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        except OSError:
            pass
        self._master_fd = master_fd
        self._slave_fd = slave_fd

        self._proc = await asyncio.create_subprocess_exec(
            *self.cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            start_new_session=True, env=self.env,
        )
        try:
            os.close(slave_fd)
        except OSError:
            pass
        self._slave_fd = None

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._queue = queue

        def _read() -> None:
            try:
                while True:
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, data)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        self._reader_thread = threading.Thread(target=_read, daemon=True)
        self._reader_thread.start()

    async def read_events(self):
        assert self._queue is not None
        tty = TtyStream()
        while True:
            chunk = await self._queue.get()
            if chunk is None:
                break
            for event in tty.feed(chunk):
                yield event
        for event in tty.flush():
            yield event

    def cancel(self) -> None:
        import signal
        if self._proc is not None and self._proc.returncode is None:
            try:
                self._proc.send_signal(signal.SIGINT)
            except (ProcessLookupError, OSError):
                pass

    async def wait(self) -> int:
        assert self._proc is not None
        if self._proc.returncode is None:
            return await self._proc.wait()
        return self._proc.returncode

    def close(self) -> None:
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None


class ConPtyStream(DownloadPty):
    """pywinpty ConPTY implementation for Windows 10+.

    pywinpty's read() returns decoded UTF-8 str and blocks, so it runs on a
    background thread bridged into an asyncio queue; text is re-encoded to
    bytes before feeding the shared TtyStream parser.
    """

    def __init__(self, cmd: list[str], env: dict[str, str] | None = None):
        self.cmd = list(cmd)
        self.env = dict(env) if env is not None else spawn_env()
        self._proc = None
        self._queue: asyncio.Queue[bytes | None] | None = None
        self._reader_thread: threading.Thread | None = None

    async def spawn(self) -> None:
        from winpty import Backend, PtyProcess

        env_pairs = [f"{k}={v}" for k, v in self.env.items()]
        self._proc = PtyProcess.spawn(
            self.cmd, env=env_pairs, dimensions=(24, 80), backend=Backend.ConPTY,
        )

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._queue = queue
        proc = self._proc

        def _read() -> None:
            try:
                while proc.isalive():
                    try:
                        text = proc.read()
                    except EOFError:
                        break
                    if text:
                        loop.call_soon_threadsafe(
                            queue.put_nowait, text.encode("utf-8", errors="replace"))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        self._reader_thread = threading.Thread(target=_read, daemon=True)
        self._reader_thread.start()

    async def read_events(self):
        assert self._queue is not None
        tty = TtyStream()
        while True:
            chunk = await self._queue.get()
            if chunk is None:
                break
            for event in tty.feed(chunk):
                yield event
        for event in tty.flush():
            yield event

    def cancel(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate(force=False)
            except Exception:
                pass

    async def wait(self) -> int:
        assert self._proc is not None
        if self._proc.isalive():
            self._proc.terminate(force=True)
        return self._proc.exitstatus() if hasattr(self._proc, "exitstatus") else 0

    def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.close(force=True)
            except Exception:
                pass
            self._proc = None


def open_download_pty(cmd: list[str], env: dict[str, str] | None = None) -> DownloadPty:
    """Factory: ConPtyStream on Windows, PosixPtyStream everywhere else."""
    if sys.platform == "win32":
        return ConPtyStream(cmd, env)
    return PosixPtyStream(cmd, env)
