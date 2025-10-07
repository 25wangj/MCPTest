import base64
import os
from dataclasses import dataclass

from PyQt5.QtCore import QBuffer, QIODevice
from PyQt5.QtGui import QImage

try:
    from openai import OpenAI
except ImportError as exc:  # pragma: no cover - dependency runtime check
    OpenAI = None  # type: ignore
    _import_error = exc
else:
    _import_error = None

PROMPT = (
    "This spectrogram was created from a recording of a piece of music. If possible, please identify the sequence of notes played and the instrument used."
)


class SpectrogramAnalysisError(RuntimeError):
    """Raised when spectrogram analysis fails."""


@dataclass
class AnalysisResult:
    text: str


def analyze_spectrogram(image: QImage, api_key: str | None = None) -> AnalysisResult:
    if OpenAI is None:  # pragma: no cover
        raise SpectrogramAnalysisError(
            "openai package is not installed. Install it with 'pip install openai'."
        ) from _import_error

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise SpectrogramAnalysisError("OPENAI_API_KEY environment variable is not set.")

    buffer = QBuffer()
    if not buffer.open(QIODevice.WriteOnly):
        raise SpectrogramAnalysisError("Failed to initialise image buffer.")
    if not image.save(buffer, "PNG"):
        raise SpectrogramAnalysisError("Failed to encode spectrogram image.")
    image_bytes = bytes(buffer.data())
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:image/png;base64,{image_b64}"

    client = OpenAI(api_key=key)
    try:
        response = client.responses.create(
            model="gpt-5",
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": PROMPT},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        )
    except Exception as exc:  # pragma: no cover
        raise SpectrogramAnalysisError(f"OpenAI API request failed: {exc}") from exc

    text = _extract_text(response)
    if not text:
        raise SpectrogramAnalysisError("OpenAI response did not contain any text output.")
    return AnalysisResult(text=text.strip())


def _extract_text(response: object) -> str:
    if hasattr(response, "output_text"):
        return str(getattr(response, "output_text"))
    if hasattr(response, "output") and response.output:
        pieces: list[str] = []
        for item in response.output:
            content = getattr(item, "content", None)
            if not content:
                continue
            for part in content:
                if getattr(part, "type", None) in {"output_text", "text"}:
                    text_value = getattr(part, "text", None) or getattr(part, "content", None)
                    if text_value:
                        pieces.append(str(text_value))
        if pieces:
            return "\n".join(pieces)
    if hasattr(response, "choices"):
        pieces = []
        for choice in getattr(response, "choices"):
            message = getattr(choice, "message", None)
            if message and hasattr(message, "content"):
                pieces.append(str(message.content))
        if pieces:
            return "\n".join(pieces)
    return ""
