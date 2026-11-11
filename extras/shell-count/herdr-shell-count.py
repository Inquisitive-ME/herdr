#!/usr/bin/env python3
"""Report how many shell commands each herdr agent is running.

Every few seconds this asks herdr which process each agent pane runs, counts the
commands that process is running (its child shells, and programs a shell turned into
with exec) that have been alive for a few seconds, and stores the count in the pane's
`shells` token. The patched herdr sidebar shows it as "· 2 shells". Linux and macOS.

The count is meant to match Claude Code's background shells. A Bash call Claude is
waiting on looks the same from outside, but it started during the current working
turn and is at most 10 minutes old (Claude Code's limit for waiting on a command). So
while an agent works, a command counts once it's older than the turn or than 10
minutes. That needs the patched server's `state_since_ms` agent token; without it
every command counts.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERDR = os.environ.get("HERDR_BIN", "herdr")
SOURCE = "shell-count"
SHELLS = {"bash", "sh", "zsh", "dash", "fish"}
REFRESH_SECONDS = 30  # re-report unchanged counts so the TTL below never expires
FOREGROUND_LIMIT = 600  # Claude Code waits at most 10 minutes on a Bash command
AT_LAUNCH = 30  # children started this soon after the agent are its own (MCP servers)
AGENT_HELPERS = {"caffeinate"}  # Claude Code keeps the Mac awake while it works
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


def processes():
    """[(pid, parent pid, age in seconds, name)] for every process."""
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,etime=,comm="],
                         capture_output=True, text=True, timeout=10, check=True)
    rows = []
    for line in out.stdout.splitlines():
        fields = line.split(None, 3)
        if len(fields) < 4:
            continue
        pid, ppid, etime, comm = fields
        name = os.path.basename(comm.strip()).lstrip("-")  # macOS gives paths, login shells "-zsh"
        try:
            rows.append((int(pid), int(ppid), parse_etime(etime), name))
        except ValueError:
            continue
    return rows


def child_commands(rows, min_age):
    """{parent pid: ages in seconds of the commands it runs, alive at least min_age}.

    Commands are child shells, and other children started well after the parent: a
    shell that execs a program keeps its process, so Claude Code still counts it.
    Children started with the parent (MCP servers) and its helpers (caffeinate, its
    own daemon, named like the parent) don't count.
    """
    parents = {pid: (age, name) for pid, _, age, name in rows}
    counts = {}
    for _, ppid, age, name in rows:
        parent_age, parent_name = parents.get(ppid, (None, None))
        if age < min_age or name in AGENT_HELPERS or name == parent_name:
            continue
        started_later = parent_age is not None and parent_age - age > AT_LAUNCH
        if name in SHELLS or started_later:
            counts.setdefault(ppid, []).append(age)
    return counts


def agent_pid(agent):
    info = herdr_json("pane", "process-info", "--pane", agent["pane_id"])["process_info"]
    procs = info.get("foreground_processes") or []
    label = (agent.get("agent") or "").lower()

    def names(proc):
        # On macOS Claude Code renames its process to its version ("2.1.318"); argv0
        # still says "claude".
        return ((proc.get("name") or "").lower(),
                os.path.basename(proc.get("argv0") or "").lower())

    match = next((p for p in procs if label and any(label in n for n in names(p))), None)
    return (match or (procs[0] if procs else {})).get("pid")


def background_count(agent, ages, now_ms):
    """Commands that aren't ones a working agent is waiting on."""
    since = (agent.get("tokens") or {}).get("state_since_ms")
    if agent.get("agent_status") != "working" or not since:
        return len(ages)
    try:
        turn_seconds = max(0, now_ms - int(since)) / 1000
    except ValueError:
        return len(ages)
    # One second of slack for ps rounding: a call made right as the turn began is foreground.
    return sum(1 for age in ages if age > min(turn_seconds, FOREGROUND_LIMIT) + 1)


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
    shells = child_commands(processes(), min_age)
    now = time.monotonic()
    for agent in agents:
        pane = agent["pane_id"]
        try:
            pid = agent_pid(agent)
        except Exception:  # pane closed between calls
            continue
        count = background_count(agent, shells.get(pid, []), time.time() * 1000) if pid else 0
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
    last_error = None
    while True:
        if shutil.which(HERDR) is None:
            # herdr was uninstalled: exit cleanly so the service doesn't restart us.
            print("herdr-shell-count: herdr is not installed; exiting", file=sys.stderr, flush=True)
            return
        try:
            cycle(state, args.min_age, args.dry_run)
            delay = args.interval
            last_error = None
        except Exception as error:  # herdr not running yet, restarting, etc.
            if str(error) != last_error:  # log once per problem, not every retry
                print(f"herdr-shell-count: {error}", file=sys.stderr, flush=True)
                last_error = str(error)
            state.clear()
            delay = 10
        if args.once:
            return
        time.sleep(delay)


if __name__ == "__main__":
    main()
