from app.fit import fit_verdict


def test_fits_in_vram():
    verdict = fit_verdict(weights_bytes=10_000_000_000, vram_gb=24.0, ram_gb=64.0, ctx=8192, layers=32, heads=32, hidden=4096)
    assert verdict["stage"] == "gpu"


def test_offload_to_ram():
    verdict = fit_verdict(weights_bytes=40_000_000_000, vram_gb=24.0, ram_gb=64.0, ctx=8192, layers=32, heads=32, hidden=4096)
    assert verdict["stage"] == "ram_offload"


def test_warns_when_does_not_fit():
    verdict = fit_verdict(weights_bytes=100_000_000_000, vram_gb=24.0, ram_gb=64.0, ctx=8192, layers=32, heads=32, hidden=4096)
    assert verdict["stage"] == "no_fit"
    assert verdict["warning"] is True


def test_cpu_only_arch():
    verdict = fit_verdict(weights_bytes=10_000_000_000, vram_gb=0.0, ram_gb=64.0, ctx=8192, layers=32, heads=32, hidden=4096)
    assert verdict["stage"] == "ram"
