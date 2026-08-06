from app.tty_stream import TtyStream


def test_newline_lines():
    s = TtyStream()
    events = s.feed(b"Fetching files...\nDone\n")
    assert events == [("line", "Fetching files..."), ("line", "Done")]
    assert s.flush() == []


def test_carriage_return_is_progress_overwrite():
    s = TtyStream()
    events = s.feed(b"\r45%|####| 45/100\r100%|####| 100/100 [00:01<00:00, 5.0MB/s]\n")
    assert events == [
        ("progress", "45%|####| 45/100"),
        ("line", "100%|####| 100/100 [00:01<00:00, 5.0MB/s]"),
    ]
    assert s.flush() == []


def test_crlf_and_mid_line_overwrite():
    s = TtyStream()
    events = s.feed(b"one\r\ntwo\rthree\n")
    assert events == [("line", "one"), ("line", "three")]
    assert s.flush() == []


def test_ansi_escapes_stripped():
    s = TtyStream()
    events = s.feed(b"\x1b[32mgreen\x1b[0m\n")
    assert events == [("line", "green")]


def test_progress_trailing_spaces_trimmed():
    s = TtyStream()
    events = s.feed(b"10%\r100%   \n")
    assert events == [("progress", "10%"), ("line", "100%")]


def test_control_bytes_dropped():
    s = TtyStream()
    events = s.feed(b"a\x07b\x08c\n")
    assert events == [("line", "abc")]


def test_flush_emits_partial_line():
    s = TtyStream()
    s.feed(b"partial")
    assert s.flush() == [("line", "partial")]
    assert s.flush() == []


def test_partial_utf8_buffered_across_chunks():
    s = TtyStream()
    s.feed("\u2713".encode("utf-8")[:1])
    events = s.feed("\u2713".encode("utf-8")[1:] + b" ok\n")
    assert events == [("line", "\u2713 ok")]


def test_tqdm_multibar_crlf_redraws_are_progress():
    """A pty turns tqdm's cursor-move \\n into \\r\\n, so a multi-bar redraw
    arrives as '<bar>\\r\\n\\r<next-bar>'. The redrawn bars must be 'progress'
    (in-place update) events, not finalized 'line' events."""
    s = TtyStream()
    events = s.feed(
        b"\rFetching 5 files:  20%|####      | 1/5 [00:00<00:00, 5.0it/s]\r\n"
        b"\rDownloading bytes: 200B\r\n\r\n"
        b"\rReconstructing...:  20%|####      | 200B / 1.0kB\r"
        b"\rFetching 5 files:  40%|########  | 2/5 [00:00<00:00, 5.0it/s]\r\n"
        b"\rDownloading bytes: 400B"
    )
    assert events == [
        ("progress", "Fetching 5 files:  20%|####      | 1/5 [00:00<00:00, 5.0it/s]"),
        ("progress", "Downloading bytes: 200B"),
        ("progress", "Reconstructing...:  20%|####      | 200B / 1.0kB"),
        ("progress", "Fetching 5 files:  40%|########  | 2/5 [00:00<00:00, 5.0it/s]"),
    ]
    assert s.flush() == [("line", "Downloading bytes: 400B")]


def test_crlf_line_followed_by_text_stays_a_line():
    s = TtyStream()
    events = s.feed(b"one\r\ntwo three\n")
    assert events == [("line", "one"), ("line", "two three")]
    assert s.flush() == []
