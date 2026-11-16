"""Seed data: generate CSV files, then load them through the service APIs.

    python -m fleetops_seed generate [--out seed/seed-v1] [--vehicles 500] ...
    python -m fleetops_seed load [--data seed/seed-v1] [--gateway http://127.0.0.1:8080]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import httpx

from .catalog import SEED_VERSION, build_catalog
from .csvio import read_catalog, write_catalog
from .loader import Loader, gateway_urls

DEFAULT_DIR = Path("seed") / SEED_VERSION


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m fleetops_seed", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate", help="Write a deterministic catalog as CSV files")
    generate.add_argument("--out", type=Path, default=DEFAULT_DIR)
    generate.add_argument("--seed-version", default=SEED_VERSION)
    generate.add_argument("--providers", type=int, default=12)
    generate.add_argument("--fleets", type=int, default=20)
    generate.add_argument("--vehicles", type=int, default=500)
    generate.add_argument("--spare-units", type=int, default=20)
    generate.add_argument("--incidents", type=int, default=100)

    load = commands.add_parser("load", help="Load CSV files through the service APIs")
    load.add_argument("--data", type=Path, default=DEFAULT_DIR)
    load.add_argument("--gateway", default="http://127.0.0.1:8080",
                      help="Gateway base URL (default: %(default)s)")
    load.add_argument("--concurrency", type=int, default=16)
    return parser.parse_args()


def generate(args: argparse.Namespace) -> int:
    catalog = build_catalog(
        seed_version=args.seed_version, providers=args.providers, fleets=args.fleets,
        vehicles=args.vehicles, spare_units=args.spare_units, incidents=args.incidents,
    )
    for path in write_catalog(catalog, args.out):
        print(f"wrote {path}")
    print(", ".join(f"{n} {kind}" for kind, n in catalog.counts().items()))
    return 0


async def load(args: argparse.Namespace) -> int:
    catalog = read_catalog(args.data)
    print(f"{args.data} ({catalog.seed_version}): "
          + ", ".join(f"{n} {kind}" for kind, n in catalog.counts().items()))
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=30.0) as client:
        report = await Loader(client, gateway_urls(args.gateway), args.concurrency).load(
            catalog, progress=print
        )
    print(f"done in {time.perf_counter() - started:.1f}s")
    if report.failures:
        print(f"{len(report.failures)} failures:", file=sys.stderr)
        for failure in report.failures[:20]:
            print(f"  {failure}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    args = parse_args()
    sys.exit(generate(args) if args.command == "generate" else asyncio.run(load(args)))


if __name__ == "__main__":
    main()
