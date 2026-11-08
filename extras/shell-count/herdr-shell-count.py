#!/usr/bin/env python3
"""Report how many shell commands each herdr agent is running.

Every few seconds this asks herdr which process each agent pane runs, counts that
process's direct child shells (Claude Code's Bash calls and background shells) that
have been alive for a few seconds, and stores the count in the pane's `shells`
token. The patched herdr sidebar shows it as "· 2 shells". Linux and macOS.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERDR = os.environ.get("HERDR_BIN", "herdr")
SOURCE = "shell-count"
SHELLS = {"bash", "sh", "zsh", "dash", "fish"}
REFRESH_SECONDS = 30  # re-report unchanged counts so the TTL below never expires
TTL_MS = 60_000  # counts vanish if this watcher stops


def herdr_json(*args):
    out = subprocess.run([HERDR, *args], capture_output=True, text=True, timeout=10)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"herdr {args[0]} failed")
    return json.loads(out.stdout)["result"]


def parse_etime(text):
    """ps etime `[[dd-]hh:]mm:ss` -> seconds."""
    days, _, clock = text.strip().rpartition("-")
    seconds = 0
    for part in clock.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds + int(days or 0) * 86400


def child_shells(min_age):
    """{parent pid: number of shell children alive at least min_age seconds}."""
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,etime=,comm="],
                         capture_output=True, text=True, timeout=10, check=True)
    counts = {}
    for line in out.stdout.splitlines():
        fields = line.split(None, 3)
        if len(fields) < 4:
            continue
        _, ppid, etime, comm = fields
        name = os.path.basename(comm.strip()).lstrip("-")  # macOS gives paths, login shells "-zsh"
        try:
            if name in SHELLS and parse_etime(etime) >= min_age:
                counts[int(ppid)] = counts.get(int(ppid), 0) + 1
        except ValueError:
            continue
    return counts


def agent_pid(agent):
    info = herdr_json("pane", "process-info", "--pane", agent["pane_id"])["process_info"]
    procs = info.get("foreground_processes") or []
    label = (agent.get("agent") or "").lower()
    match = next((p for p in procs if label and label in (p.get("name") or "").lower()), None)
    return (match or (procs[0] if procs else {})).get("pid")


def report(pane_id, count, dry_run):
    change = ["--token", f"shells={count}", "--ttl-ms", str(TTL_MS)] if count else ["--clear-token", "shells"]
    if dry_run:
        print(f"{pane_id}: {count or 'clear'}")
        return
    seq = str(time.time_ns() // 1_000_000)
    subprocess.run([HERDR, "pane", "report-metadata", pane_id, "--source", SOURCE, "--seq", seq, *change],
                   capture_output=True, timeout=10)


def cycle(state, min_age, dry_run):
    agents = herdr_json("api", "snapshot")["snapshot"]["agents"]
    shells = child_shells(min_age)
    now = time.monotonic()
    for agent in agents:
        pane = agent["pane_id"]
        try:
            pid = agent_pid(agent)
        except Exception:  # pane closed between calls
            continue
        count = shells.get(pid, 0) if pid else 0
        last = state.get(pane)
        stale = last is not None and count and now - last[1] >= REFRESH_SECONDS
        if last is None or last[0] != count or stale:
            report(pane, count, dry_run)
            state[pane] = (count, now)
    for pane in set(state) - {a["pane_id"] for a in agents}:
        del state[pane]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--min-age", type=int, default=3, help="ignore shells younger than this (hooks)")
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="print counts instead of reporting them")
    args = parser.parse_args()
    state = {}  # pane -> (last reported count, when); empty state clears old counts on start
    while True:
        try:
            cycle(state, args.min_age, args.dry_run)
            delay = args.interval
        except Exception as error:  # herdr not running yet, restarting, etc.
            print(f"herdr-shell-count: {error}", file=sys.stderr, flush=True)
            state.clear()
            delay = 10
        if args.once:
            return
        time.sleep(delay)


if __name__ == "__main__":
    main()
