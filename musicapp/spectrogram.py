from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from scipy.io import wavfile
from scipy.signal import spectrogram as scipy_spectrogram

try:
    from .mcp_bridge import MCPBridge, MCPBridgeError
except ImportError:
    from mcp_bridge import MCPBridge, MCPBridgeError  # type: ignore


class SpectrogramError(RuntimeError):
    """Raised when generating or exporting a spectrogram fails."""


@dataclass
class SpectrogramAssets:
    pixmap: QPixmap
    image: QImage
    title: str


def resolve_audio_path(
    curr_path: str | None,
    bridge: MCPBridge,
    fallback: Path,
) -> Path:
    """Determine which file to use for the current take."""
    candidate = curr_path
    if not candidate:
        try:
            candidate = bridge.fetch_current_path()
        except MCPBridgeError as exc:
            raise SpectrogramError(str(exc)) from exc
    candidate_path = Path(candidate) if candidate else None
    if candidate_path and candidate_path.is_file():
        return candidate_path.resolve()
    if fallback.is_file():
        return fallback.resolve()
    if candidate_path:
        raise SpectrogramError(f"Current take file not found at {candidate_path}.")
    raise SpectrogramError("Current take path is unavailable. Refresh metadata and try again.")


def generate_spectrogram(audio_path: Path) -> SpectrogramAssets:
    """Compute and render a spectrogram image for the given audio file."""
    audio_path = audio_path.resolve()
    try:
        sample_rate, data = wavfile.read(str(audio_path))
    except Exception as exc:  # pylint: disable=broad-except
        raise SpectrogramError(f"Failed to read audio: {exc}") from exc
    if data.size == 0:
        raise SpectrogramError("Current take is empty.")
    if data.ndim > 1:
        data = data.mean(axis=1)
    data = data.astype(np.float32, copy=False)
    if len(data) < 32:
        raise SpectrogramError("Recording too short for spectrogram.")
    nperseg = int(min(1024, len(data)))
    noverlap = int(min(nperseg - 1, max(0, int(nperseg * 0.75))))
    try:
        freqs, times, power = scipy_spectrogram(
            data,
            fs=sample_rate,
            nperseg=nperseg,
            noverlap=noverlap,
            scaling="spectrum",
            mode="magnitude",
        )
    except Exception as exc:  # pylint: disable=broad-except
        raise SpectrogramError(f"Could not compute spectrogram: {exc}") from exc
    if power.size == 0 or times.size == 0 or freqs.size == 0:
        raise SpectrogramError("Spectrogram data is empty.")

    power = np.maximum(power, 1e-12)
    power_db = 10 * np.log10(power)
    finite_mask = np.isfinite(power_db)
    if not finite_mask.any():
        raise SpectrogramError("Spectrogram contains no finite values.")
    finite_values = power_db[finite_mask]
    min_val = float(finite_values.min())
    max_val = float(finite_values.max())
    if np.isclose(max_val, min_val):
        normalized = np.zeros_like(power_db)
    else:
        normalized = (power_db - min_val) / (max_val - min_val)
    normalized = np.clip(normalized, 0.0, 1.0)
    flipped = normalized[::-1]

    height, width = flipped.shape
    low_rgb = np.array([13, 17, 23], dtype=np.float32)
    mid_rgb = np.array([59, 130, 246], dtype=np.float32)
    high_rgb = np.array([254, 240, 138], dtype=np.float32)
    colorized = np.empty((height, width, 3), dtype=np.float32)
    lower_mask = flipped <= 0.5
    if lower_mask.any():
        lower_ratio = (flipped[lower_mask] * 2.0).reshape(-1, 1)
        colorized[lower_mask] = low_rgb + lower_ratio * (mid_rgb - low_rgb)
    if (~lower_mask).any():
        upper_ratio = ((flipped[~lower_mask] - 0.5) * 2.0).reshape(-1, 1)
        colorized[~lower_mask] = mid_rgb + upper_ratio * (high_rgb - mid_rgb)
    colorized = np.clip(colorized, 0, 255).astype(np.uint8)
    buffer = np.ascontiguousarray(colorized)
    bytes_per_line = buffer.shape[1] * 3
    base_image = QImage(buffer.tobytes(), width, height, bytes_per_line, QImage.Format_RGB888).copy()

    left_margin, right_margin = 70, 20
    top_margin, bottom_margin = 20, 60
    canvas_width = width + left_margin + right_margin
    canvas_height = height + top_margin + bottom_margin
    canvas = QImage(canvas_width, canvas_height, QImage.Format_RGB32)
    canvas.fill(QColor("#0d1117"))

    painter = QPainter(canvas)
    painter.drawImage(left_margin, top_margin, base_image)

    axis_pen = QPen(QColor("#8b949e"))
    axis_pen.setWidth(1)
    painter.setPen(axis_pen)
    bottom_y = top_margin + height
    right_x = left_margin + width
    painter.drawLine(left_margin, bottom_y, right_x, bottom_y)
    painter.drawLine(left_margin, top_margin, left_margin, bottom_y)

    tick_pen = QPen(QColor("#30363d"))
    text_pen = QPen(QColor("#c9d1d9"))
    tick_font = QFont()
    tick_font.setPointSize(9)
    painter.setFont(tick_font)

    if times.size:
        denom = max(1, times.size - 1)
        tick_count = min(6, times.size)
        indices = sorted({int(round(idx)) for idx in np.linspace(0, times.size - 1, tick_count)})
        for idx in indices:
            idx = min(times.size - 1, max(0, idx))
            ratio = idx / denom if denom else 0
            x_offset = int(round(ratio * width)) if width > 1 else 0
            x = left_margin + min(width, max(0, x_offset))
            painter.setPen(tick_pen)
            painter.drawLine(x, bottom_y, x, bottom_y + 6)
            label = f"{times[idx]:.2f}s" if times[idx] < 10 else f"{times[idx]:.1f}s"
            painter.setPen(text_pen)
            painter.drawText(x - 25, bottom_y + 24, 50, 16, Qt.AlignHCenter, label)

    if freqs.size:
        max_freq = float(freqs[-1]) if freqs[-1] else 1.0
        tick_count = min(6, freqs.size)
        indices = sorted({int(round(idx)) for idx in np.linspace(0, freqs.size - 1, tick_count)})
        for idx in indices:
            idx = min(freqs.size - 1, max(0, idx))
            freq_val = float(freqs[idx])
            ratio = freq_val / max_freq if max_freq else 0.0
            y_offset = int(round((1 - ratio) * height)) if height > 1 else 0
            y = top_margin + min(height, max(0, y_offset))
            painter.setPen(tick_pen)
            painter.drawLine(left_margin - 6, y, left_margin, y)
            label = _format_frequency(freq_val)
            painter.setPen(text_pen)
            painter.drawText(
                5,
                y - 8,
                left_margin - 12,
                16,
                Qt.AlignRight | Qt.AlignVCenter,
                label,
            )

    axis_font = QFont()
    axis_font.setPointSize(10)
    axis_font.setBold(True)
    painter.setFont(axis_font)
    painter.setPen(QPen(QColor("#58a6ff")))
    painter.drawText(
        left_margin,
        bottom_y + 44,
        width,
        20,
        Qt.AlignHCenter,
        "Time (s)",
    )
    painter.save()
    painter.translate(left_margin - 50, top_margin + height / 2)
    painter.rotate(-90)
    painter.setPen(QPen(QColor("#58a6ff")))
    painter.drawText(
        -height // 2,
        -20,
        height,
        20,
        Qt.AlignHCenter,
        "Frequency (Hz)",
    )
    painter.restore()
    painter.end()

    title = f"Spectrogram - {audio_path.name}"
    pixmap = QPixmap.fromImage(canvas)
    return SpectrogramAssets(pixmap=pixmap, image=canvas, title=title)


def _format_frequency(freq: float) -> str:
    if freq >= 1000:
        return f"{freq / 1000:.1f} kHz"
    if freq >= 100:
        return f"{freq:.0f} Hz"
    return f"{freq:.1f} Hz"
