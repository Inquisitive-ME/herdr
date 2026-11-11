"""Tests for the shell-count watcher's agent lookup (extras/shell-count)."""
import importlib.util
import unittest
from pathlib import Path

WATCHER = Path(__file__).resolve().parent.parent / "extras/shell-count/herdr-shell-count.py"


def load_watcher():
    spec = importlib.util.spec_from_file_location("herdr_shell_count", WATCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentPidTests(unittest.TestCase):
    def agent_pid(self, procs):
        watcher = load_watcher()
        watcher.herdr_json = lambda *args: {"process_info": {"foreground_processes": procs}}
        return watcher.agent_pid({"pane_id": "w1:p1", "agent": "claude"})

    def test_finds_claude_on_macos_where_its_process_is_named_after_its_version(self):
        # Claude Code keeps caffeinate in its foreground group on macOS.
        procs = [
            {"name": "caffeinate", "argv0": "caffeinate", "pid": 9277},
            {"name": "2.1.318", "argv0": "claude", "pid": 63850},
        ]
        self.assertEqual(self.agent_pid(procs), 63850)

    def test_matches_argv0_given_as_a_path(self):
        procs = [
            {"name": "caffeinate", "argv0": "caffeinate", "pid": 1},
            {"name": "2.1.318", "argv0": "/Users/me/.local/bin/claude", "pid": 2},
        ]
        self.assertEqual(self.agent_pid(procs), 2)

    def test_finds_claude_on_linux_by_process_name(self):
        procs = [{"name": "claude", "argv0": None, "pid": 1066578}]
        self.assertEqual(self.agent_pid(procs), 1066578)


class ChildCommandTests(unittest.TestCase):
    CLAUDE = (100, 1, 86_400, "claude")  # (pid, parent pid, age in seconds, name)

    def counts(self, *children):
        return load_watcher().child_commands([self.CLAUDE, *children], min_age=3).get(100, [])

    def test_counts_shells_and_programs_a_shell_turned_into(self):
        # A background `exec python serve.py` keeps the shell's process, as python.
        self.assertEqual(self.counts((1, 100, 3_000, "bash"), (2, 100, 1_000, "python")),
                         [3_000, 1_000])

    def test_skips_children_started_with_the_agent_and_its_helpers(self):
        self.assertEqual(self.counts(
            (1, 100, 86_390, "node"),        # an MCP server from launch
            (2, 100, 600, "caffeinate"),     # macOS: keeps the Mac awake while working
            (3, 100, 70_000, "claude"),      # its own daemon
            (4, 100, 1, "bash"),             # a hook, too young
        ), [])


class BackgroundCountTests(unittest.TestCase):
    NOW_MS = 1_000_000_000

    def count(self, turn_seconds, ages, status="working"):
        agent = {"agent_status": status,
                 "tokens": {"state_since_ms": str(self.NOW_MS - turn_seconds * 1000)}}
        return load_watcher().background_count(agent, ages, self.NOW_MS)

    def test_a_long_turn_counts_commands_older_than_ten_minutes(self):
        # Two hours in: a 30-minute-old command can't be one Claude is waiting on.
        self.assertEqual(self.count(7_200, [10_800, 1_800, 300]), 2)

    def test_a_short_turn_counts_commands_older_than_the_turn(self):
        self.assertEqual(self.count(180, [300, 120]), 1)

    def test_an_idle_agent_counts_everything(self):
        self.assertEqual(self.count(7_200, [10_800, 1_800, 300], status="idle"), 3)


if __name__ == "__main__":
    unittest.main()
