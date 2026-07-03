#!/usr/bin/env python3
"""Offline load generator — find this Pi's moderation throughput ceiling.

No Discord connection needed. It pushes synthetic messages through the *real*
deterministic analysis pipeline (the exact code the bot runs per message) as
fast as it can, and reports msgs/sec plus CPU temperature so you can watch the
board climb toward thermal throttle. This is the "watch it melt" tool.

Usage:
    python scripts/stress.py --seconds 30 --workers 4 --csv melt.csv

It deliberately does NOT call the LLM (that's offboard and network-bound); it
measures what the Pi itself must do for every single message before deciding
whether to escalate.
"""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import os
import random
import sys
import time
from pathlib import Path

# make the bot package importable when run from the repo root or scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.analysis import TextAnalyzer  # noqa: E402

CORPUS = [
    "hey everyone how's it going today, working on my raspberry pi project",
    "anyone know the best way to search discord for old messages?",
    "CHECK OUT THIS FREE NITRO http://discord-nitro.com @everyone claim now!!!",
    "f u c k this is so frustrating i cant get it to work",
    "🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉",
    "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod",
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA spam spam spam",
    "great question! you'll want to use from: and has:link in the search bar",
    "https://example.com/thing?a=1 and https://example.org check these out",
    "why is the sky blue and how do transformers actually work internally",
]


def read_temp() -> float | None:
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000.0
    except Exception:
        return None


def worker(enable_nltk: bool, wordlist: str, stop_at: float, out) -> None:
    analyzer = TextAnalyzer(enable_nltk=enable_nltk, wordlist_path=wordlist)
    rng = random.Random(os.getpid())
    n = 0
    while time.monotonic() < stop_at:
        for _ in range(500):
            analyzer.analyze(rng.choice(CORPUS))
            n += 1
    out.put(n)


def main() -> int:
    ap = argparse.ArgumentParser(description="Melt-the-Pi moderation load test")
    ap.add_argument("--seconds", type=int, default=15)
    ap.add_argument("--workers", type=int, default=mp.cpu_count())
    ap.add_argument("--nltk", action="store_true", help="include NLTK/VADER cost")
    ap.add_argument("--wordlist", default="", help="custom profanity wordlist path")
    ap.add_argument("--csv", default="", help="append per-second stats to this CSV")
    args = ap.parse_args()

    print(
        f"🔥 Stressing with {args.workers} worker(s) for {args.seconds}s "
        f"(nltk={args.nltk}). Cores detected: {mp.cpu_count()}."
    )
    start_temp = read_temp()
    if start_temp is not None:
        print(f"   Start CPU temp: {start_temp:.1f}°C")

    stop_at = time.monotonic() + args.seconds
    ctx = mp.get_context("spawn")
    q: mp.Queue = ctx.Queue()
    procs = [
        ctx.Process(target=worker, args=(args.nltk, args.wordlist, stop_at, q))
        for _ in range(args.workers)
    ]
    t0 = time.monotonic()
    for p in procs:
        p.start()

    # sample temperature/time once a second while the workers run
    samples = []
    while any(p.is_alive() for p in procs):
        time.sleep(1)
        samples.append((round(time.monotonic() - t0, 1), read_temp()))

    total = sum(q.get() for _ in procs)
    for p in procs:
        p.join()
    elapsed = time.monotonic() - t0
    end_temp = read_temp()

    rate = total / elapsed
    print("-" * 48)
    print(f"Processed : {total:,} messages")
    print(f"Elapsed   : {elapsed:.1f}s")
    print(f"Throughput: {rate:,.0f} msgs/sec  ({rate/max(1,args.workers):,.0f}/worker)")
    if start_temp is not None and end_temp is not None:
        print(f"CPU temp  : {start_temp:.1f}°C → {end_temp:.1f}°C (Δ {end_temp-start_temp:+.1f})")
        if end_temp >= 80:
            print("🌡️  Over 80°C — you are at/near thermal throttle. It's melting. 🫠")

    if args.csv:
        with open(args.csv, "a", newline="") as f:
            w = csv.writer(f)
            if f.tell() == 0:
                w.writerow(["t_s", "temp_c"])
            for t, temp in samples:
                w.writerow([t, temp if temp is not None else ""])
        print(f"Wrote temperature curve to {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
