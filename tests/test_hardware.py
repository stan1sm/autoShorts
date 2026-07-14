from shorts.gui.hardware import HardwareSpecs, recommend


def _specs(**kw) -> HardwareSpecs:
    base = dict(
        cpu_cores=8, ram_gb=16.0, gpu_name=None, gpu_vram_gb=None,
        ffmpeg_version="8.1.1", has_anthropic_key=False,
        has_openai_key=False, has_groq_key=False,
    )
    base.update(kw)
    return HardwareSpecs(**base)


def _override_for(recs: dict, setting_contains: str) -> dict:
    note = next(n for n in recs["notes"] if setting_contains.lower() in n["setting"].lower())
    return note["override"]


def test_big_gpu_gets_large_v3():
    recs = recommend(_specs(gpu_name="RTX 4090", gpu_vram_gb=24.0))
    assert _override_for(recs, "whisper")["transcription.model"] == "large-v3"


def test_small_gpu_gets_medium():
    recs = recommend(_specs(gpu_name="GTX 1660", gpu_vram_gb=6.0))
    assert _override_for(recs, "whisper")["transcription.model"] == "medium"


def test_cpu_with_groq_key_recommends_groq():
    recs = recommend(_specs(has_groq_key=True))
    assert _override_for(recs, "engine")["transcription.engine"] == "groq"


def test_weak_cpu_gets_base():
    recs = recommend(_specs(cpu_cores=4, ram_gb=8.0))
    assert _override_for(recs, "whisper")["transcription.model"] == "base"


def test_strong_cpu_gets_medium():
    recs = recommend(_specs(cpu_cores=12, ram_gb=32.0))
    assert _override_for(recs, "whisper")["transcription.model"] == "medium"


def test_no_llm_key_warns_and_falls_back_to_heuristic():
    recs = recommend(_specs())
    assert _override_for(recs, "strategy")["clip_selection.strategy"] == "heuristic"
    assert any("API key" in w for w in recs["warnings"])


def test_anthropic_key_recommends_anthropic():
    recs = recommend(_specs(has_anthropic_key=True))
    ov = _override_for(recs, "llm provider")
    assert ov["clip_selection.llm_provider"] == "anthropic"


def test_missing_ffmpeg_warns():
    recs = recommend(_specs(ffmpeg_version=None))
    assert any("ffmpeg" in w for w in recs["warnings"])
