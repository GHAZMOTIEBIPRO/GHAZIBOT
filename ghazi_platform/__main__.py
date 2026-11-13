"""Command line for the platform alpha.

    python -m ghazi_platform serve [--port 8765]
    python -m ghazi_platform grant-owner --email owner@example.com
    python -m ghazi_platform revoke-owner --email owner@example.com

`grant-owner` is the ONLY way to give the admin role. It runs on the host,
against the database file, so whoever runs it already controls the server (the
trust root). It refuses an account whose e-mail ownership is not proven, and it
signs that account out everywhere so the role starts from a fresh login.

`serve` is a single-threaded wsgiref server for local preview and tests only.
A production deployment needs a WSGI server, HTTPS and an owner hosting decision.
"""
from __future__ import annotations

import argparse
import logging
import sys
from wsgiref.simple_server import WSGIRequestHandler, make_server

from .accounts import AccountError, grant_owner, revoke_owner
from .config import Config, ConfigError
from .db import Database
from .web import App


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args) -> None:
        # Method, path and status only: no query string, headers or cookies.
        sys.stderr.write(f"{self.command} {self.path.split('?')[0][:120]} {args[1] if len(args) > 1 else ''}\n")


def _serve(port: int) -> int:
    try:
        app = App(Config.from_env())
    except ConfigError as err:
        print(f"refusing to start: {err}", file=sys.stderr)
        return 2
    if not app.cfg.enabled:
        print("GHAZI_PLATFORM_ENABLED is not set: every route will answer 404.", file=sys.stderr)
    with make_server("127.0.0.1", port, app, handler_class=_QuietHandler) as server:
        print(f"GHAZI platform alpha ({app.cfg.environment}) on http://127.0.0.1:{port}", file=sys.stderr)
        server.serve_forever()
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="python -m ghazi_platform")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="run the local development server")
    serve.add_argument("--port", type=int, default=8765)
    for name in ("grant-owner", "revoke-owner"):
        p = sub.add_parser(name, help=f"{name.replace('-', ' ')} (server-side only)")
        p.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    if args.command in (None, "serve"):
        return _serve(getattr(args, "port", 8765))
    try:
        cfg = Config.from_env()
    except ConfigError as err:
        print(f"refusing: {err}", file=sys.stderr)
        return 2
    db = Database(cfg.db_path)
    try:
        fn = grant_owner if args.command == "grant-owner" else revoke_owner
        out = fn(db, email=args.email, via="cli")
    except AccountError as err:
        print(err.message_ar, file=sys.stderr)
        return 1
    print(f"{args.command}: user {out['user_id']} is now {out['role']}; all of its sessions were signed out.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
