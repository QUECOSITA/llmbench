import asyncio
import os
import sys

import pytest

pytest.importorskip("app.pty_stream")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pty is not available on Windows")
def test_open_download_pty_factory_returns_posix_stream():
    from app.pty_stream import open_download_pty
    stream = open_download_pty(["hf", "download", "org/model"])
    assert type(stream).__name__ == "PosixPtyStream"


@pytest.mark.skipif(sys.platform == "win32", reason="posix pty not on Windows")
def test_posix_pty_stream_reads_output(tmp_path):
    from app.pty_stream import open_download_pty
    script = tmp_path / "emit.py"
    script.write_text("import sys\nprint('hello')\n")
    stream = open_download_pty([sys.executable, "-u", str(script)])

    async def run():
        await stream.spawn()
        events = [ev async for ev in stream.read_events()]
        rc = await stream.wait()
        stream.close()
        return events, rc

    events, rc = asyncio.run(run())
    assert rc == 0
    assert any(kind == "line" and "hello" in text for kind, text in events)
