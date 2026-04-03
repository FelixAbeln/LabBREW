import argparse


def build_shared_parser(description: str = "Service"):
    parser = argparse.ArgumentParser(description=description)

    parser.add_argument('--backend-host', default='127.0.0.1')
    parser.add_argument('--backend-port', type=int, default=8765)
    parser.add_argument('--backend-url', default='')
    parser.add_argument('--data-backend-host', default='127.0.0.1')
    parser.add_argument('--data-backend-port', type=int, default=8769)
    parser.add_argument('--data-backend-url', default='')

    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8766)

    return parser


def parse_args(description: str = "Service"):
    parser = build_shared_parser(description)
    return parser.parse_args()