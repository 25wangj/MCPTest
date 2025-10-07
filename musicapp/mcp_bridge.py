import asyncio
import json
from typing import Any, Awaitable

import yaml
import fastmcp


class MCPBridgeError(RuntimeError):
    """Raised when an MCP operation fails."""


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
                payload = getattr(response, "data", None)
                try:
                    if callable(payload):
                        payload = payload()
                    if asyncio.iscoroutine(payload):
                        payload = await payload
                except TypeError:
                    payload = None
                return payload

        return self._run(_runner())

    def _read_resource(self, uri: str) -> object:
        async def _runner():
            async with fastmcp.Client(self.endpoint) as client:
                records = await client.read_resource(uri)
                if not records:
                    return None
                record = records[0]
                for attr in ("json", "data", "text", "content"):
                    if not hasattr(record, attr):
                        continue
                    value = getattr(record, attr)
                    try:
                        if callable(value):
                            value = value()
                        if asyncio.iscoroutine(value):
                            value = await value
                    except TypeError:
                        continue
                    if value is not None:
                        return value
                if hasattr(record, "model_dump"):
                    return record.model_dump()
                if hasattr(record, "__dict__"):
                    return dict(record.__dict__)
                return None

        return self._run(_runner())

    @staticmethod
    def _unwrap_payload(payload: object) -> object:
        """Peel away common wrapper structures (ResourceContent, JSON-in-string, etc.)."""
        for _ in range(8):
            if payload is None:
                break
            if isinstance(payload, dict):
                text_value = payload.get("text")
                data_value = payload.get("data")
                content_value = payload.get("content")
                if isinstance(text_value, str):
                    payload = text_value
                    continue
                if isinstance(data_value, (str, dict)):
                    payload = data_value
                    continue
                if isinstance(content_value, (str, dict)):
                    payload = content_value
                    continue
            if isinstance(payload, str):
                try:
                    decoded = yaml.safe_load(payload)
                except yaml.YAMLError:
                    break
                if decoded is None:
                    break
                payload = decoded
                continue
            break
        return payload

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
        raw = self._unwrap_payload(raw)
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list):
            collected: dict[str, dict] = {}
            for item in raw:
                if isinstance(item, dict):
                    key = item.get("id") or item.get("name")
                    data = item.get("value") or item.get("data") or item
                    if key:
                        if isinstance(data, dict):
                            collected[str(key)] = data
                        else:
                            try:
                                loaded = yaml.safe_load(str(data))
                                if isinstance(loaded, dict):
                                    collected[str(key)] = loaded
                            except yaml.YAMLError:
                                continue
            if collected:
                return collected
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
        if hasattr(raw, "model_dump"):
            dumped = raw.model_dump()
            if isinstance(dumped, dict):
                return dumped
        try:
            fallback = yaml.safe_load(str(raw))
            if isinstance(fallback, dict):
                return fallback
        except yaml.YAMLError:
            pass
        raise MCPBridgeError(f"Unexpected recordings payload type: {type(raw)!r}")

    def fetch_current_path(self) -> str | None:
        raw = self._read_resource("data://curr")
        raw = self._unwrap_payload(raw)
        if raw is None:
            return None
        if isinstance(raw, str):
            return raw
        if isinstance(raw, (list, tuple)) and raw:
            return str(raw[0])
        return str(raw)
