import re

class InvalidModelInput(ValueError):
    pass

_REPO_RE = re.compile(r"^[\w.\-]+/[\w.\-]+$")
_HF_LINK_RE = re.compile(r"^https?://(?:www\.)?huggingface\.co/([^/?#]+/[^/?#]+)")


def normalize_input(raw: str) -> str:
    """Accept 'user/model' or an https huggingface.co link; return 'user/model'."""
    s = raw.strip().strip("/")
    if not s:
        raise InvalidModelInput("Model input is empty.")
    m = _HF_LINK_RE.match(s)
    if m:
        return m.group(1)
    if _REPO_RE.match(s):
        return s
    raise InvalidModelInput(f"'{raw}' is not a huggingface.co link or 'user/model'.")
