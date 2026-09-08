from __future__ import annotations

import io
import json
from dataclasses import replace
from typing import Any
from urllib.parse import urlencode

from prometheus_client import CollectorRegistry

from satgenpy.ai_datacenter.metrics_server import (
    MetricsController,
    MetricsSnapshot,
    make_wsgi_application,
)


class BackendTestCase:
    """Mixin providing a fresh controller, registry, and in-process WSGI client."""

    controller: MetricsController

    def setUp(self) -> None:
        self.controller = MetricsController(CollectorRegistry(), "NORMAL_BURST")
        self.controller.refresh()
        self.app = make_wsgi_application(self.controller)

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        query: dict[str, object] | None = None,
        body: bytes = b"",
    ) -> tuple[int, dict[str, str], bytes]:
        captured: dict[str, Any] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = dict(headers)

        environ: dict[str, object] = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": urlencode(query or {}),
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": "application/json",
            "wsgi.input": io.BytesIO(body),
        }
        body = b"".join(self.app(environ, start_response))
        return int(captured["status"].split()[0]), captured["headers"], body

    def json_request(self, path: str, **kwargs: object) -> tuple[int, dict[str, str], dict[str, Any]]:
        status, headers, body = self.request(path, **kwargs)
        return status, headers, json.loads(body.decode("utf-8"))


def snapshot_with(snapshot: MetricsSnapshot, **changes: object) -> MetricsSnapshot:
    return replace(snapshot, **changes)
