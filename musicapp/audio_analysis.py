import base64
import os
from dataclasses import dataclass
from pathlib import Path

try:
    from openai import OpenAI
except ImportError as exc:  # pragma: no cover - dependency runtime check
    OpenAI = None  # type: ignore
    _import_error = exc
else:
    _import_error = None

PROMPT = (
    "Please identify the sequence of notes played, the instrument used, and the name of the piece."
)


class AudioAnalysisError(RuntimeError):
    """Raised when audio analysis fails."""


@dataclass
class AnalysisResult:
    text: str


def analyze_audio(audio_path: Path, api_key: str | None = None) -> AnalysisResult:
    if OpenAI is None:  # pragma: no cover - runtime guard
        raise AudioAnalysisError(
            "openai package is not installed. Install it with 'pip install openai'."
        ) from _import_error

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise AudioAnalysisError("OPENAI_API_KEY environment variable is not set.")

    path_obj = Path(audio_path)
    if not path_obj.is_file():
        raise AudioAnalysisError(f"Audio file not found: {audio_path}")

    try:
        audio_bytes = path_obj.read_bytes()
    except Exception as exc:  # pragma: no cover - filesystem error
        raise AudioAnalysisError(f"Failed to read audio file: {exc}") from exc

    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    client = OpenAI(api_key=key)

    try:
        completion = client.chat.completions.create(
            model="gpt-audio",
            modalities=["text"],
            audio={"voice": "alloy", "format": "wav"},
            messages=[
            {
                "role": "user",
                "content": [
                    { 
                    "type": "text",
                    "text": PROMPT
                    },
                    {
                    "type": "input_audio",
                    "input_audio": {
                        "data": audio_b64,
                        "format": "wav"
                    }
                }
            ]
        },
    ]
        )
    except Exception as exc:  # pragma: no cover - network runtime
        raise AudioAnalysisError(f"OpenAI API request failed: {exc}") from exc

    text = completion.choices[0].message.content
    print(text)
    if not text:
        raise AudioAnalysisError("OpenAI response did not contain any text output.")
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
