"""Simulate fleet movement and telematics events against the running services.

    python -m fleetops_sim                                  # replay the last 60 minutes
    python -m fleetops_sim --minutes 30 --live              # replay 30 minutes, then real time
    python -m fleetops_sim --inject battery_connectivity:veh_golden_001@20
                                                            # scripted fault 20 minutes in
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta

import httpx

from fleetops_seed.loader import gateway_urls

from .runner import Injection, RunConfig, Simulator
from .scenarios import SCENARIOS


def injection(raw: str) -> Injection:
    try:
        scenario, rest = raw.split(":", 1)
        vehicle_id, minute = rest.split("@", 1)
        return Injection(scenario, vehicle_id, float(minute))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected SCENARIO:VEHICLE@MINUTE, got {raw!r}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m fleetops_sim", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gateway", default="http://127.0.0.1:8080")
    parser.add_argument("--minutes", type=float, default=60,
                        help="Simulated window ending now, replayed as fast as possible")
    parser.add_argument("--live", action="store_true",
                        help="Keep running in real time after the replay (Ctrl+C to stop)")
    parser.add_argument("--live-minutes", type=float, default=None,
                        help="Stop after this many real-time minutes")
    parser.add_argument("--tick-seconds", type=float, default=60)
    parser.add_argument("--seed", default="sim-v1")
    parser.add_argument("--max-vehicles", type=int, default=None)
    parser.add_argument("--late-share", type=float, default=0.01,
                        help="Share of events delivered one tick late (default %(default)s)")
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--inject", type=injection, action="append", default=[],
                        metavar="SCENARIO:VEHICLE@MINUTE",
                        help=f"Scripted incident; scenarios: {', '.join(SCENARIOS)}")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    config = RunConfig(
        start=now - timedelta(minutes=args.minutes),
        minutes=args.minutes,
        tick=timedelta(seconds=args.tick_seconds),
        live=args.live,
        live_minutes=args.live_minutes,
        seed=args.seed,
        max_vehicles=args.max_vehicles,
        injections=args.inject,
        late_share=args.late_share,
        concurrency=args.concurrency,
    )
    for item in config.injections:
        if not args.live and item.minute + 12 > args.minutes:
            print(f"warning: {item.scenario} at minute {item.minute} needs 12 minutes; "
                  f"it ends after this {args.minutes:g}-minute replay unless --live",
                  file=sys.stderr)
    async with httpx.AsyncClient(timeout=30.0) as client:
        simulator = Simulator(client, gateway_urls(args.gateway), config)
        try:
            stats = await simulator.run(progress=print)
        except asyncio.CancelledError:
            stats = simulator.stats
    print("done:", stats.summary())
    print("by type:", ", ".join(f"{k} {v}" for k, v in stats.sent.most_common()))
    for failure in stats.failures:
        print(f"  {failure}", file=sys.stderr)
    return 1 if stats.outcome.get("failed") else 0


def main() -> None:
    try:
        sys.exit(asyncio.run(run(parse_args())))
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
