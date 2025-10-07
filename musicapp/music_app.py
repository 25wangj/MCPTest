from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QDialog,
    QFileDialog,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

try:
    from .mcp_bridge import MCPBridge, MCPBridgeError
    from .spectrogram import SpectrogramError, generate_spectrogram, resolve_audio_path
except ImportError:
    from mcp_bridge import MCPBridge, MCPBridgeError  # type: ignore
    from spectrogram import SpectrogramError, generate_spectrogram, resolve_audio_path  # type: ignore


@dataclass
class RecordingMetadata:
    name: str
    size_bytes: int
    duration_seconds: float

    def formatted_size(self) -> str:
        if self.size_bytes < 1024:
            return f"{self.size_bytes} B"
        if self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        return f"{self.size_bytes / (1024 * 1024):.2f} MB"

    def formatted_duration(self) -> str:
        return f"{self.duration_seconds:.2f} s"


class MusicApp(QWidget):
    def __init__(self, bridge: Optional[MCPBridge] = None) -> None:
        super().__init__()
        self.bridge = bridge or MCPBridge()
        self.is_recording = False
        self.is_playing = False
        self.recordings: list[RecordingMetadata] = []
        self.curr_metadata: Optional[RecordingMetadata] = None
        self.curr_path: Optional[str] = None
        self._last_spectrogram_image: Optional[QImage] = None
        self._last_spectrogram_source: Optional[Path] = None
        self._last_spectrogram_title: Optional[str] = None

        self.setWindowTitle("Music MCP Controller")
        self._build_ui()
        self._apply_dark_theme()
        self._refresh_metadata()

    def _build_ui(self) -> None:
        layout = QVBoxLayout()

        # Current take summary
        curr_layout = QVBoxLayout()
        self.curr_path_label = QLabel("Current take: Unavailable")
        self.curr_info_label = QLabel("Size: N/A    Duration: N/A")
        curr_layout.addWidget(self.curr_path_label)
        curr_layout.addWidget(self.curr_info_label)
        layout.addLayout(curr_layout)

        # Recording controls
        control_layout = QGridLayout()
        self.record_button = QPushButton("Start Recording")
        self.stop_record_button = QPushButton("Stop Recording")
        self.play_button = QPushButton("Start Playback")
        self.stop_play_button = QPushButton("Stop Playback")

        self.stop_record_button.setEnabled(False)
        self.stop_play_button.setEnabled(False)

        control_layout.addWidget(self.record_button, 0, 0)
        control_layout.addWidget(self.stop_record_button, 0, 1)
        control_layout.addWidget(self.play_button, 1, 0)
        control_layout.addWidget(self.stop_play_button, 1, 1)
        layout.addLayout(control_layout)

        # Refresh (secondary)
        refresh_layout = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh Metadata")
        self.refresh_button.setFlat(True)
        self.refresh_button.setStyleSheet(
            "padding: 4px; color: #58a6ff; background-color: transparent; border: none;"
        )
        self.spectrogram_button = QPushButton("Show Spectrogram")
        self.spectrogram_button.setFlat(True)
        self.spectrogram_button.setStyleSheet(
            "padding: 4px; color: #58a6ff; background-color: transparent; border: none;"
        )
        self.export_spectrogram_button = QPushButton("Export Spectrogram")
        self.export_spectrogram_button.setFlat(True)
        self.export_spectrogram_button.setStyleSheet(
            "padding: 4px; color: #58a6ff; background-color: transparent; border: none;"
        )
        refresh_layout.addStretch(1)
        refresh_layout.addWidget(self.refresh_button)
        refresh_layout.addWidget(self.spectrogram_button)
        refresh_layout.addWidget(self.export_spectrogram_button)
        layout.addLayout(refresh_layout)

        # Save controls
        save_layout = QHBoxLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("New take name (without extension)")
        self.save_button = QPushButton("Save Current Take")
        save_layout.addWidget(self.name_input)
        save_layout.addWidget(self.save_button)
        layout.addLayout(save_layout)

        # Table of recordings
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Size", "Duration"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        # Actions for saved takes
        actions_layout = QHBoxLayout()
        self.set_curr_button = QPushButton("Set as Current")
        self.delete_button = QPushButton("Delete Take")
        self.set_curr_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        actions_layout.addWidget(self.set_curr_button)
        actions_layout.addWidget(self.delete_button)
        layout.addLayout(actions_layout)

        # Status
        self.status_label = QLabel("Ready.")
        layout.addWidget(self.status_label)

        self.setLayout(layout)
        self._wire_events()

    def _apply_dark_theme(self) -> None:
        accent = "#58a6ff"
        self.setStyleSheet(
            """
            QWidget {
                background-color: #0d1117;
                color: #f0f6fc;
            }
            QPushButton {
                background-color: #161b22;
                color: #f0f6fc;
                border: 1px solid #30363d;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:disabled {
                background-color: #161b22;
                color: #4b5563;
                border-color: #22272e;
            }
            QLineEdit {
                background-color: #161b22;
                color: #f0f6fc;
                border: 1px solid #30363d;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QTableWidget {
                background-color: #161b22;
                alternate-background-color: #11161d;
                color: #f0f6fc;
                gridline-color: #30363d;
            }
            QTableWidget::item:selected {
                background-color: #1f6feb;
                color: #f0f6fc;
            }
            QTableCornerButton::section {
                background-color: #161b22;
                border: 1px solid #30363d;
            }
            QHeaderView::section {
                background-color: #161b22;
                color: #f0f6fc;
                padding: 6px;
                border: 0px;
            }
            QScrollArea {
                background-color: #0d1117;
                border: none;
            }
            QScrollBar:vertical, QScrollBar:horizontal {
                background: #0d1117;
                width: 12px;
                height: 12px;
            }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                background: #30363d;
                border-radius: 6px;
            }
            """
        )
        link_style = f"padding: 4px; color: {accent}; background-color: transparent; border: none;"
        self.refresh_button.setStyleSheet(link_style)
        self.spectrogram_button.setStyleSheet(link_style)
        self.export_spectrogram_button.setStyleSheet(link_style)

    def _wire_events(self) -> None:
        self.record_button.clicked.connect(self._handle_start_recording)
        self.stop_record_button.clicked.connect(self._handle_stop_recording)
        self.play_button.clicked.connect(self._handle_start_playback)
        self.stop_play_button.clicked.connect(self._handle_stop_playback)
        self.save_button.clicked.connect(self._handle_save_take)
        self.set_curr_button.clicked.connect(self._handle_set_current)
        self.delete_button.clicked.connect(self._handle_delete_take)
        self.refresh_button.clicked.connect(self._refresh_metadata)
        self.spectrogram_button.clicked.connect(self._handle_show_spectrogram)
        self.export_spectrogram_button.clicked.connect(self._handle_export_spectrogram)
        self.table.selectionModel().selectionChanged.connect(self._update_selection_state)

    def _update_selection_state(self) -> None:
        has_selection = bool(self.table.selectionModel().selectedRows())
        self.set_curr_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)
        self._set_status(f"Error: {message}")

    def _handle_start_recording(self) -> None:
        try:
            if not self.bridge.start_recording():
                self._show_error("Recording already running or failed to start.")
                return
            self.is_recording = True
            self._set_status("Recording...")
        except MCPBridgeError as exc:
            self._show_error(str(exc))
            return
        self._update_controls()

    def _handle_stop_recording(self) -> None:
        try:
            if not self.bridge.stop_recording():
                self._show_error("Recording was not running.")
                return
            self.is_recording = False
            self._set_status("Recording stopped.")
            self._refresh_metadata()
        except MCPBridgeError as exc:
            self._show_error(str(exc))
        self._update_controls()

    def _handle_start_playback(self) -> None:
        try:
            if not self.bridge.start_playback():
                self._show_error("Playback already running or no audio available.")
                return
            self.is_playing = True
            self._set_status("Playing current take...")
        except MCPBridgeError as exc:
            self._show_error(str(exc))
            return
        self._update_controls()

    def _handle_stop_playback(self) -> None:
        try:
            if not self.bridge.stop_playback():
                self._show_error("Playback was not running.")
                self._set_status("Ready.")
            else:
                self._set_status("Playback stopped.")
        except MCPBridgeError as exc:
            self._show_error(str(exc))
            self._set_status("Ready.")
        finally:
            self.is_playing = False
            self._update_controls()

    def _handle_show_spectrogram(self) -> None:
        fallback = self._fallback_audio_path()
        try:
            audio_path = resolve_audio_path(self.curr_path, self.bridge, fallback)
            assets = generate_spectrogram(audio_path)
        except SpectrogramError as exc:
            self._show_error(str(exc))
            return
        self._cache_spectrogram(assets.image, audio_path, assets.title)

        dialog = QDialog(self)
        dialog.setWindowTitle(assets.title)
        dialog_layout = QVBoxLayout(dialog)
        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        image_label = QLabel()
        image_label.setPixmap(assets.pixmap)
        scroll.setWidget(image_label)
        dialog_layout.addWidget(scroll)
        dialog.resize(min(assets.pixmap.width() + 40, 900), min(assets.pixmap.height() + 80, 700))
        dialog.exec_()
        self._set_status("Spectrogram generated.")

    def _handle_export_spectrogram(self) -> None:
        fallback = self._fallback_audio_path()
        try:
            audio_path = resolve_audio_path(self.curr_path, self.bridge, fallback)
        except SpectrogramError as exc:
            self._show_error(str(exc))
            return
        regenerate = (
            self._last_spectrogram_image is None
            or self._last_spectrogram_source is None
            or self._last_spectrogram_source != audio_path.resolve()
        )
        if regenerate:
            try:
                assets = generate_spectrogram(audio_path)
            except SpectrogramError as exc:
                self._show_error(str(exc))
                return
            self._cache_spectrogram(assets.image, audio_path, assets.title)

        default_name = f"{audio_path.stem}_spectrogram.png"
        initial_dir = (
            str((self._last_spectrogram_source or audio_path).parent)
        )
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Spectrogram",
            str(Path(initial_dir) / default_name),
            "PNG Image (*.png)",
        )
        if not save_path:
            return
        target = Path(save_path)
        if target.suffix.lower() != ".png":
            target = target.with_suffix(".png")
        if not self._last_spectrogram_image or not self._last_spectrogram_image.save(str(target), "PNG"):
            self._show_error("Failed to save spectrogram image.")
            return
        self._set_status(f"Spectrogram exported to {target}.")

    def _fallback_audio_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "musicmcp" / "curr.wav"

    def _cache_spectrogram(self, image: QImage, source: Path, title: str) -> None:
        self._last_spectrogram_image = image.copy()
        self._last_spectrogram_source = source.resolve()
        self._last_spectrogram_title = title

    def _handle_save_take(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            self._show_error("Enter a name for the take.")
            return
        if " " in name:
            self._show_error("Take names should not contain spaces.")
            return
        try:
            if not self.bridge.save_current(name):
                self._show_error("Could not save current take. Ensure a recording exists and the name is unique.")
                return
            self._set_status(f"Saved take '{name}'.")
            self.name_input.clear()
            self._refresh_metadata()
        except MCPBridgeError as exc:
            self._show_error(str(exc))

    def _handle_set_current(self) -> None:
        selected = self._selected_take_name()
        if not selected:
            return
        try:
            if not self.bridge.set_as_current(selected):
                self._show_error("Failed to set selected take as current.")
                return
            self._set_status(f"Set '{selected}' as current take.")
            self._refresh_metadata()
        except MCPBridgeError as exc:
            self._show_error(str(exc))

    def _handle_delete_take(self) -> None:
        selected = self._selected_take_name()
        if not selected:
            return
        confirm = QMessageBox.question(
            self,
            "Delete Take",
            f"Delete saved take '{selected}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            if not self.bridge.delete_take(selected):
                self._show_error("Failed to delete the selected take.")
                return
            self._set_status(f"Deleted '{selected}'.")
            self._refresh_metadata()
        except MCPBridgeError as exc:
            self._show_error(str(exc))

    def _selected_take_name(self) -> Optional[str]:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        row = indexes[0].row()
        item = self.table.item(row, 0)
        return item.text() if item else None

    def _refresh_metadata(self) -> None:
        try:
            recordings_map = self.bridge.fetch_recordings()
            curr = recordings_map.get("curr")
            self.curr_metadata = None
            self.curr_path = None
            if isinstance(curr, dict):
                self.curr_metadata = RecordingMetadata(
                    name="curr",
                    size_bytes=int(curr.get("size", 0)),
                    duration_seconds=float(curr.get("time", 0.0)),
                )
                raw_path = curr.get("path")
                if raw_path:
                    self.curr_path = str(raw_path)
            if not self.curr_path:
                try:
                    self.curr_path = self.bridge.fetch_current_path()
                except MCPBridgeError:
                    self.curr_path = None
            saved: list[RecordingMetadata] = []
            for name, meta in recordings_map.items():
                if name == "curr" or not isinstance(meta, dict):
                    continue
                saved.append(
                    RecordingMetadata(
                        name=name,
                        size_bytes=int(meta.get("size", 0)),
                        duration_seconds=float(meta.get("time", 0.0)),
                    )
                )
            self.recordings = sorted(saved, key=lambda m: m.name.lower())
            self._populate_table()
            self._update_current_labels()
            self._update_selection_state()
        except MCPBridgeError as exc:
            self._show_error(str(exc))

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self.recordings))
        for row, meta in enumerate(self.recordings):
            self.table.setItem(row, 0, QTableWidgetItem(meta.name))
            self.table.setItem(row, 1, QTableWidgetItem(meta.formatted_size()))
            self.table.setItem(row, 2, QTableWidgetItem(meta.formatted_duration()))
        self.table.resizeRowsToContents()

    def _update_current_labels(self) -> None:
        if self.curr_metadata:
            path_display = self.curr_path or "curr.wav"
        else:
            path_display = self.curr_path or "Unavailable"
        self.curr_path_label.setText(f"Current take: {path_display}")
        if self.curr_metadata:
            self.curr_info_label.setText(
                f"Size: {self.curr_metadata.formatted_size()}    "
                f"Duration: {self.curr_metadata.formatted_duration()}"
            )
        else:
            self.curr_info_label.setText("Size: N/A    Duration: N/A")

    def _update_controls(self) -> None:
        self.record_button.setEnabled(not self.is_recording and not self.is_playing)
        self.stop_record_button.setEnabled(self.is_recording)
        self.play_button.setEnabled(not self.is_playing)
        self.stop_play_button.setEnabled(self.is_playing)


def run() -> None:
    app = QApplication([])
    window = MusicApp()
    window.resize(640, 480)
    window.show()
    app.exec_()


if __name__ == "__main__":
    run()
