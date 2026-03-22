from __future__ import annotations

import argparse


def build_common_service_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--backend-host", default="127.0.0.1")
    parser.add_argument("--backend-port", type=int, default=8765)
    parser.add_argument("--root-data", default="./data")
    return parser
