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


if __name__ == "__main__":
    unittest.main()
