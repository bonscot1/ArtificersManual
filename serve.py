#!/usr/bin/env python3
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve the ArtificersManual site for local and external users."
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind to.")
    parser.add_argument(
        "--port", default=8000, type=int, help="Port number to listen on."
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    site_dir = Path(__file__).parent / "site"
    handler = partial(SimpleHTTPRequestHandler, directory=str(site_dir))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving {site_dir} on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
