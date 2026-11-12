"""Development server: `GHAZI_PLATFORM_ENABLED=1 python -m ghazi_platform [port]`.

Single-threaded wsgiref server for local preview and tests only. A production
deployment needs a WSGI server, HTTPS and a hosting decision by the owner.
"""
from __future__ import annotations

import sys
from wsgiref.simple_server import WSGIRequestHandler, make_server

from .web import create_app


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args) -> None:
        # Log method, path and status only (no query strings, which may carry ids).
        sys.stderr.write(f"{self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}\n")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    app = create_app()
    if not app.cfg.enabled:
        print("GHAZI_PLATFORM_ENABLED is not set: every route will answer 404.", file=sys.stderr)
    with make_server("127.0.0.1", port, app, handler_class=_QuietHandler) as server:
        print(f"GHAZI platform alpha on http://127.0.0.1:{port}", file=sys.stderr)
        server.serve_forever()


if __name__ == "__main__":
    main()
