from __future__ import annotations

import argparse


def build_shared_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--host', default='0.0.0.0', help='Service bind host')
    parser.add_argument('--port', type=int, default=8769, help='Service bind port')
    parser.add_argument('--backend-host', default='127.0.0.1', help='Backend host')
    parser.add_argument('--backend-port', type=int, default=8765, help='Backend port')
    parser.add_argument('--root-data', default='data', help='Shared persistent data folder')
    parser.add_argument('--service-name', default='', help='Optional override for display/service name')
    return parser
