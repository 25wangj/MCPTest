import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable

import yaml
from PyQt5.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

import fastmcp


class MCPBridgeError(RuntimeError):
    """Raised when an MCP operation fails."""


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


class MCPBridge:
    """Synchronous facade around the asynchronous FastMCP client."""

    def __init__(self, endpoint: str = "http://127.0.0.1:8000/mcp") -> None:
        self.endpoint = endpoint

    def _run(self, coro: Awaitable[Any]) -> Any:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(coro)
            loop.run_until_complete(loop.shutdown_asyncgens())
            return result
        except Exception as exc:  # pylint: disable=broad-except
            raise MCPBridgeError(str(exc)) from exc
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    def _call_tool(self, name: str, args: dict | None = None) -> object:
        async def _runner():
            async with fastmcp.Client(self.endpoint) as client:
                response = await client.call_tool(name, args or {})
                return getattr(response, "data", None)

        return self._run(_runner())

    def _read_resource(self, uri: str) -> object:
        async def _runner():
            async with fastmcp.Client(self.endpoint) as client:
                records = await client.read_resource(uri)
                if not records:
                    return None
                record = records[0]
                for attr in ("json", "data", "text"):
                    if hasattr(record, attr):
                        value = getattr(record, attr)
                        if value is not None:
                            return value
                return None

        return self._run(_runner())

    def start_recording(self) -> bool:
        return bool(self._call_tool("startRecording"))

    def stop_recording(self) -> bool:
        return bool(self._call_tool("stopRecording"))

    def start_playback(self) -> bool:
        return bool(self._call_tool("startPlaying"))

    def stop_playback(self) -> bool:
        return bool(self._call_tool("stopPlaying"))

    def save_current(self, name: str) -> bool:
        return bool(self._call_tool("saveCurr", {"name": name}))

    def set_as_current(self, name: str) -> bool:
        return bool(self._call_tool("setAsCurr", {"name": name}))

    def delete_take(self, name: str) -> bool:
        return bool(self._call_tool("delete", {"name": name}))

    def fetch_recordings(self) -> dict[str, dict]:
        raw = self._read_resource("data://recordings")
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return yaml.safe_load(raw) or {}
            except yaml.YAMLError:
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise MCPBridgeError(
                        f"Could not parse recordings metadata: {exc}"
                    ) from exc
        raise MCPBridgeError(f"Unexpected recordings payload type: {type(raw)!r}")

    def fetch_current_path(self) -> str | None:
        raw = self._read_resource("data://curr")
        if raw is None:
            return None
        if isinstance(raw, str):
            return raw
        if isinstance(raw, (list, tuple)) and raw:
            return str(raw[0])
        return str(raw)


class MusicApp(QWidget):
    def __init__(self, bridge: MCPBridge | None = None) -> None:
        super().__init__()
        self.bridge = bridge or MCPBridge()
        self.is_recording = False
        self.is_playing = False
        self.recordings: list[RecordingMetadata] = []
        self.curr_metadata: RecordingMetadata | None = None
        self.curr_path: str | None = None

        self.setWindowTitle("Music MCP Controller")
        self._build_ui()
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
        self.refresh_button = QPushButton("Refresh Metadata")

        self.stop_record_button.setEnabled(False)
        self.stop_play_button.setEnabled(False)

        control_layout.addWidget(self.record_button, 0, 0)
        control_layout.addWidget(self.stop_record_button, 0, 1)
        control_layout.addWidget(self.play_button, 1, 0)
        control_layout.addWidget(self.stop_play_button, 1, 1)
        control_layout.addWidget(self.refresh_button, 2, 0, 1, 2)
        layout.addLayout(control_layout)

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

    def _wire_events(self) -> None:
        self.record_button.clicked.connect(self._handle_start_recording)
        self.stop_record_button.clicked.connect(self._handle_stop_recording)
        self.play_button.clicked.connect(self._handle_start_playback)
        self.stop_play_button.clicked.connect(self._handle_stop_playback)
        self.save_button.clicked.connect(self._handle_save_take)
        self.set_curr_button.clicked.connect(self._handle_set_current)
        self.delete_button.clicked.connect(self._handle_delete_take)
        self.refresh_button.clicked.connect(self._refresh_metadata)
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
            self._set_status("Recording…")
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
            self._set_status("Playing current take…")
        except MCPBridgeError as exc:
            self._show_error(str(exc))
            return
        self._update_controls()

    def _handle_stop_playback(self) -> None:
        try:
            if not self.bridge.stop_playback():
                self._show_error("Playback was not running.")
                return
            self.is_playing = False
            self._set_status("Playback stopped.")
        except MCPBridgeError as exc:
            self._show_error(str(exc))
        self._update_controls()

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

    def _selected_take_name(self) -> str | None:
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
            if isinstance(curr, dict):
                self.curr_metadata = RecordingMetadata(
                    name="curr",
                    size_bytes=int(curr.get("size", 0)),
                    duration_seconds=float(curr.get("time", 0.0)),
                )
            self.curr_path = self.bridge.fetch_current_path()
            saved = []
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
