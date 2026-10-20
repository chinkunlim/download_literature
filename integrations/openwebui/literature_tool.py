"""
title: 文獻下載（Literature downloader）
author: limchinkun
version: 0.1.0
description: Add references, start processing, check progress and get the APA 7 list from the local
  literature downloader web app (uv run literature-web). Paste this file into Open WebUI → Workspace → Tools.
"""

# Open WebUI tool for the local literature downloader (ADR-008).
# It calls the app's JSON API; nothing else is needed inside Open WebUI (standard library only).
# Open WebUI in Docker: set the valve base_url to http://host.docker.internal:8765 and add
# HTTP_ALLOWED_HOSTS=host.docker.internal to the downloader's .env.

from __future__ import annotations

import json
import urllib.error
import urllib.request

from pydantic import BaseModel, Field


class Tools:
    """Tools the model can call."""

    class Valves(BaseModel):
        """Settings shown in Open WebUI."""

        base_url: str = Field(
            default="http://host.docker.internal:8765",
            description="Address of the literature web app (native Open WebUI: http://127.0.0.1:8765)",
        )

    def __init__(self) -> None:
        """Create the tools with default settings."""
        self.valves = self.Valves()

    def _call(self, method: str, path: str, body: dict | None = None) -> dict | list | str:
        """Call the web app's API.

        Args:
            method: HTTP method.
            path: API path such as /api/status.
            body: JSON body for POST requests.

        Returns:
            Decoded JSON, or an error message.
        """
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.valves.base_url.rstrip("/") + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return f"Error {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}"
        except OSError as exc:
            hint = "Is `uv run literature-web` running?"
            return f"Cannot reach the literature app at {self.valves.base_url} ({exc}). {hint}"

    def add_references(self, text: str) -> str:
        """
        Add references to the reading list. One reference per line or paragraph; each can be a full APA
        citation, author + title, just a title, or a DOI (English or Chinese). They are identified and
        downloaded when processing starts.
        :param text: The references to add.
        :return: How many were added.
        """
        result = self._call("POST", "/api/items", {"text": text})
        return result if isinstance(result, str) else f"Added {len(result.get('keys', []))} reference(s)."

    def start_processing(self, interactive: bool = False) -> str:
        """
        Start identifying and downloading the pending references in the background.
        :param interactive: True only when the user is at the computer to pass bot checks in Chrome.
        :return: Whether the job started.
        """
        result = self._call("POST", "/api/process", {"interactive": interactive})
        if isinstance(result, str):
            return "A job is already running." if result.startswith("Error 409") else result
        return "Processing started. Ask for the status to follow progress."

    def get_status(self) -> str:
        """
        Get progress: whether a job is running, how many references are in each state, and the last result.
        :return: A short status report.
        """
        s = self._call("GET", "/api/status")
        if isinstance(s, str):
            return s
        job = s.get("job") or {}
        parts = [f"running: {s['running']}", f"counts: {s['counts']}"]
        if job:
            parts.append(f"last download job: {job['done']}/{job['total']} ({job['state']})")
        parts += [f"now: {s['stages']}"] if s["stages"] else []
        parts += [s["last_summary"]] if s.get("last_summary") else []
        parts += [f"error: {s['last_error']}"] if s.get("last_error") else []
        return "\n".join(parts)

    def list_references(self, status: str = "") -> str:
        """
        List references with their status (downloaded, downloaded_copy, needs_review, borrow, unavailable,
        not_found, pending) and notes.
        :param status: Only list references with this status; empty lists all.
        :return: One line per reference.
        """
        items = self._call("GET", "/api/items")
        if isinstance(items, str):
            return items
        rows = [i for i in items if not status or i["status"] == status]
        lines = []
        for i in rows:
            note = f" — {i['notes']}" if i["notes"] else ""
            lines.append(f"- [{i['status_label']}] {i['apa'] or i['input']}{note}")
        return "\n".join(lines) or "No references."

    def get_apa_list(self) -> str:
        """
        Get the APA 7th reference list of all identified references, in reference-list order.
        :return: The reference list as plain text.
        """
        result = self._call("GET", "/api/apa")
        return result if isinstance(result, str) else result["text"]
