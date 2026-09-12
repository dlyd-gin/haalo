import os

MODEL_PATH = os.environ.get("TTS_MODEL_PATH", "./models/Qwen3-TTS-12Hz-1.7B-Base-8bit")
HOST = os.environ.get("TTS_HOST", "127.0.0.1")
PORT = int(os.environ.get("TTS_PORT", "8000"))

# NOTE: the downloaded Qwen3-TTS-12Hz-1.7B-Base-8bit checkpoint's config has an
# empty talker_config.spk_id table, so these voice names currently select
# nothing at inference time (mlx_audio only applies a speaker embedding when
# the name matches a spk_id key) — every entry below produces the model's one
# default voice regardless of name. What *does* take effect is `language`,
# via config.talker_config.codec_language_id, which includes both "chinese"
# and "japanese". So output language is real; voice identity is a placeholder
# until a checkpoint with populated spk_id (or ref_audio-based cloning) is
# used. The "ja" mapping is PROVISIONAL and unvalidated for output language
# quality — see README's "Known risk" section. Confirm by ear before treating
# Japanese or Mandarin output as usable.
LANGUAGE_VOICE_MAP: dict[str, str] = {
    "en": "ryan",
    "ja": "ryan",  # PROVISIONAL — validate output language quality by ear
    "zh": "dylan",
    "ko": "ryan",  # PROVISIONAL — validate output language quality by ear
}
