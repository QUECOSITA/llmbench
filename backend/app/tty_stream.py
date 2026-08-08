import codecs
import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(text: str) -> str:
    text = _ANSI_RE.sub("", text)
    text = _CTRL_RE.sub("", text)
    return text


class TtyStream:
    """Normalize raw pty bytes into (kind, text) events.

    kind is "line" (a finalized newline-terminated line) or "progress" (a
    carriage-return overwrite of the current line, e.g. a tqdm bar update).
    Carriage-return overwrites are emitted as "progress" only when they look
    like a tqdm bar (they contain a percentage); a bare mid-line overwrite
    (e.g. "two\\rthree") is dropped in favor of the final content.
    """

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buf = ""
        # Content terminated by a '\r\n' whose verdict (line vs progress) is not
        # yet known. A pty turns tqdm's cursor-move '\n' into '\r\n', so a bar
        # redraw shows up as '<bar>\r\n\r<next-bar>'. The '\r' right after the
        # CRLF is what marks the terminated content as a redraw, and it may only
        # arrive in the next feed chunk.
        self._pending: str | None = None

    def feed(self, chunk: bytes) -> list[tuple[str, str]]:
        text = _clean(self._decoder.decode(chunk))
        events: list[tuple[str, str]] = []
        if self._pending is not None:
            if text.startswith("\r"):
                events.append(("progress", self._pending.rstrip()))
            else:
                events.append(("line", self._pending.rstrip()))
            self._pending = None
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == "\r":
                if i + 1 < n and text[i + 1] == "\n":
                    if self._buf:
                        self._pending = self._buf
                    self._buf = ""
                    i += 2
                    continue
                if self._pending is not None:
                    events.append(("progress", self._pending.rstrip()))
                    self._pending = None
                if self._buf and "%" in self._buf:
                    events.append(("progress", self._buf.rstrip()))
                self._buf = ""
            elif ch == "\n":
                if self._pending is not None:
                    events.append(("line", self._pending.rstrip()))
                    self._pending = None
                if self._buf:
                    events.append(("line", self._buf.rstrip()))
                self._buf = ""
            else:
                if self._pending is not None:
                    events.append(("line", self._pending.rstrip()))
                    self._pending = None
                self._buf += ch
            i += 1
        return events

    def flush(self) -> list[tuple[str, str]]:
        self._decoder.decode(b"", final=True)
        events: list[tuple[str, str]] = []
        if self._pending is not None:
            events.append(("line", self._pending.rstrip()))
            self._pending = None
        if self._buf:
            line = self._buf.rstrip()
            self._buf = ""
            events.append(("line", line)) if line else None
        return events
