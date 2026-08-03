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


import httpx

class HfClient:
    def __init__(self, base_url: str = "https://huggingface.co", timeout: float = 30.0):
        self.base_url = base_url
        self.timeout = timeout

    def fetch_repo(self, repo_id: str) -> tuple[str, list[dict]]:
        tree_url = f"{self.base_url}/api/models/{repo_id}/tree/main"
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            r = client.get(tree_url)
            r.raise_for_status()
            files = r.json()
            readme = ""
            for f in files:
                if f.get("type") == "file" and f["path"].lower() == "readme.md":
                    rr = client.get(f"{self.base_url}/{repo_id}/raw/main/{f['path']}")
                    if rr.status_code == 200:
                        readme = rr.text
                    break
            return readme, files

    def weights_size_bytes(self, files: list[dict]) -> int:
        return sum(
            f.get("size", 0)
            for f in files
            if f.get("type") == "file"
            and (f["path"].endswith(".safetensors")
                 or f["path"].endswith(".gguf")
                 or (f["path"].endswith(".bin") and not f["path"].endswith(".json")))
        )

    def gguf_files(self, files: list[dict]) -> list[dict]:
        return [f for f in files if f.get("type") == "file" and f["path"].endswith(".gguf")]

    def download_command(self, repo_id: str, include: str | None = None) -> list[str]:
        cmd = ["hf", "download", repo_id]
        if include:
            cmd += ["--include", include]
        return cmd
