from app.hf import normalize_input, InvalidModelInput


def test_normalize_repo_id():
    assert normalize_input("org/model") == "org/model"


def test_normalize_full_link():
    assert normalize_input("https://huggingface.co/org/model") == "org/model"


def test_normalize_link_with_suffix():
    assert normalize_input("http://huggingface.co/org/model/tree/main") == "org/model"
    assert normalize_input("https://www.huggingface.co/org/model/blob/main/README.md") == "org/model"


def test_normalize_trailing_slash():
    assert normalize_input("  org/model/  ") == "org/model"


def test_invalid_input():
    for bad in ["", "org", "https://google.com/foo", "org/model/extra/deep"]:
        try:
            normalize_input(bad)
            raise AssertionError(f"expected InvalidModelInput for {bad!r}")
        except InvalidModelInput:
            pass
