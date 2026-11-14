import logging

from mlx_vlm import generate, load
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config

from ...config import MAX_TOKENS
from .parse import parse_located, parse_lines
from .prompt import PROMPT, locate_prompt

logger = logging.getLogger(__name__)


class OcrEngine:
    """Wraps mlx-vlm model loading and prompts a vision-language model to transcribe an image."""

    def __init__(self, model_path: str):
        self._model, self._processor = load(model_path)
        self._config = load_config(model_path)

    def analyze(self, image_path: str, width: int, height: int, part: str = "") -> list[dict]:
        """`part` labels this model pass in the debug log, e.g. "part 2/4, focus x=0..574 y=291..1020"."""
        prefix = f"{part}, " if part else ""
        raw = self._generate(image_path, PROMPT)
        logger.debug("analyze: %s%dx%d image, raw model output: %s", prefix, width, height, raw)
        lines = parse_lines(raw, width, height)
        logger.debug("analyze: %s%d lines: %s", prefix, len(lines), lines)
        return lines

    def locate(self, image_path: str, width: int, height: int, phrases: list[str]) -> list[list[int] | None]:
        """Pixel bbox of each phrase in the image, or None where the model didn't find it."""
        raw = self._generate(image_path, locate_prompt(phrases))
        logger.debug("locate: raw model output: %s", raw)
        boxes = parse_located(raw, len(phrases), width, height)
        logger.debug("locate: boxes: %s", boxes)
        return boxes

    def _generate(self, image_path: str, text: str) -> str:
        prompt = apply_chat_template(
            self._processor, self._config, text, num_images=1, enable_thinking=False
        )
        result = generate(
            self._model,
            self._processor,
            prompt,
            image=[image_path],
            max_tokens=MAX_TOKENS,
            temperature=0.0,
            verbose=False,
        )
        # Newer mlx-vlm returns a GenerationResult with .text; older versions return a str.
        return result if isinstance(result, str) else result.text
