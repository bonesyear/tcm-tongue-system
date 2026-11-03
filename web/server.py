"""Web 层生产 WSGI 入口；依赖单独声明在 web/requirements.txt。"""
from __future__ import annotations

from photo_store import MAX_PHOTO_BYTES


def serve_http(app, host, port):
    from waitress import serve
    return serve(
        app, host=host, port=port,
        threads=8,
        connection_limit=64,
        channel_timeout=300,
        max_request_body_size=MAX_PHOTO_BYTES + 1024 * 1024,
        backlog=32,
    )
