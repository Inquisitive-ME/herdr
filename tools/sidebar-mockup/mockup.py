"""Draw herdr's sidebar to a PNG the way kitty with the Breeze Dark theme shows it.

Runs the given herdr binary in a throwaway session (its own config, state and sockets in a
temporary directory, removed afterwards; a herdr you have running is not touched), builds a
made-up layout of spaces, tabs and agents, and renders the sidebar's cells.

    python3 mockup.py <herdr-binary> <out.png> [--attention] [--hover TEXT] [--columns N]
                      [ENV=VALUE ...]

--attention  puts two agents in "needs input" and two in "finished".
--hover TEXT moves the mouse onto the first sidebar line containing TEXT.
--columns N  draws N columns instead of just the sidebar, e.g. to include a hover card.
             The panes then show too, with your shell prompt (user and host name).
ENV=VALUE    is passed to herdr, e.g. a switch a prototype reads.

Needs pyte and pillow (`pip install pyte pillow`) and the Hack or DejaVu Sans Mono font.
"""
import fcntl
import json
import os
import pty
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time

import pyte
from PIL import Image, ImageDraw, ImageFont

ROWS, COLS, SIDEBAR = 34, 110, 40
# kitty's Breeze Dark theme. herdr asks the terminal for these (OSC 10/11) and shades
# from the background, so the harness answers with them too.
BG, FG = (0x23, 0x26, 0x27), (0xFC, 0xFC, 0xFC)
NAMED = {
    "black": (35, 38, 39), "red": (237, 21, 21), "green": (17, 209, 22),
    "brown": (246, 116, 0), "yellow": (253, 188, 75), "blue": (29, 153, 243),
    "magenta": (155, 89, 182), "cyan": (26, 188, 156), "white": (252, 252, 252),
    "brightblack": (127, 140, 141),
}
FONTS = [
    ("/usr/share/fonts/truetype/hack/Hack-Regular.ttf", "/usr/share/fonts/truetype/hack/Hack-Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"),
]
CONFIG = """onboarding = false
[update]
version_check = false
manifest_check = false
[ui]
sidebar_width = %d
sidebar_max_width = 60
[keys]
next_agent = "prefix+a"
previous_agent = "prefix+shift+a"
focus_agent = "prefix+alt+1..9"
[ui.sidebar.agents]
rows = [
  ["state_icon", "workspace", "tab"],
  [{ token = "$asking", dim = true }],
]
""" % SIDEBAR
# (space, [(tab, agent state or None for a plain terminal)]). The first tab is the
# space's own; the rest are created.
LAYOUT = [
    ("webapp", [("prod", "idle"), ("staging", "idle"), ("deploy", "idle"), ("backend", None),
                ("frontend", None), ("data import", "idle")]),
    ("personal", [("photos", "idle"), ("budget", "idle"), ("cleanup", "idle")]),
    ("helpers", [("1", "working")]),
    ("notes", [("1", "idle")]),
]
ASKING = {"deploy": "Bash: make deploy", "data import": "Question: which bucket should I sync?"}


class Screen(pyte.Screen):
    def report_device_status(self, *args, **kwargs):
        pass


class Session:
    def __init__(self, binary, root, extra_env):
        self.binary = binary
        # Nothing that points at a herdr you're running: its sockets or its SSH agent link.
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("HERDR_") and k != "SSH_AUTH_SOCK"}
        self.env.update(
            XDG_CONFIG_HOME=os.path.join(root, "config"),
            XDG_STATE_HOME=os.path.join(root, "state"),
            TERM="xterm-256color",
            HERDR_DISABLE_SOUND="1",
            HERDR_SOCKET_PATH=os.path.join(root, "s.sock"),
            HERDR_CLIENT_SOCKET_PATH=os.path.join(root, "c.sock"),
            **extra_env,
        )
        # Debug builds read herdr-dev/, release builds herdr/.
        for name in ("herdr", "herdr-dev"):
            os.makedirs(os.path.join(self.env["XDG_CONFIG_HOME"], name))
            with open(os.path.join(self.env["XDG_CONFIG_HOME"], name, "config.toml"), "w") as f:
                f.write(CONFIG)
        self.screen = Screen(COLS, ROWS)
        self.stream = pyte.ByteStream(self.screen)
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execve(binary, [binary], self.env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        self.panes = {}

    def cli(self, *args):
        out = subprocess.run([self.binary, *args], env=self.env, capture_output=True,
                             text=True, timeout=20)
        if out.returncode != 0:
            raise RuntimeError(f"herdr {' '.join(args)} failed: {out.stderr or out.stdout}")
        return json.loads(out.stdout)["result"] if out.stdout.strip().startswith("{") else None

    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if not select.select([self.fd], [], [], 0.05)[0]:
                continue
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                return
            if b"]11;?" in data:
                os.write(self.fd, b"\x1b]11;rgb:%02x%02x/%02x%02x/%02x%02x\x1b\\" % (BG[0], BG[0], BG[1], BG[1], BG[2], BG[2]))
            if b"]10;?" in data:
                os.write(self.fd, b"\x1b]10;rgb:%02x%02x/%02x%02x/%02x%02x\x1b\\" % (FG[0], FG[0], FG[1], FG[1], FG[2], FG[2]))
            self.stream.feed(data)

    def agent(self, tab, pane, state):
        self.panes[tab] = pane
        self.cli("pane", "report-agent", pane, "--source", "mockup", "--agent", "claude",
                 "--state", state)

    def build(self):
        first = True
        for space, tabs in LAYOUT:
            if first:
                snapshot = self.cli("api", "snapshot")["snapshot"]
                workspace = snapshot["workspaces"][0]["workspace_id"]
                self.cli("workspace", "rename", workspace, space)
                root = snapshot["panes"][0]
                first = False
            else:
                created = self.cli("workspace", "create", "--label", space)
                workspace = created["workspace"]["workspace_id"]
                root = created["root_pane"]
            self.cli("tab", "rename", root["tab_id"], tabs[0][0])
            panes = [root["pane_id"]]
            for tab, _ in tabs[1:]:
                created = self.cli("tab", "create", "--workspace", workspace, "--label", tab)
                panes.append(created["root_pane"]["pane_id"])
            for (tab, state), pane in zip(tabs, panes):
                if state:
                    self.agent(tab, pane, state)

    def attention(self):
        for tab in ("deploy", "photos", "budget", "data import"):
            self.agent(tab, self.panes[tab], "working")
        self.pump(2)
        for tab, asking in ASKING.items():
            self.agent(tab, self.panes[tab], "blocked")
            self.cli("pane", "report-metadata", self.panes[tab], "--source", "mockup",
                     "--token", f"asking={asking}")
        for tab in ("photos", "budget"):
            self.agent(tab, self.panes[tab], "idle")

    def hover(self, text):
        for row, line in enumerate(self.screen.display):
            column = line[:SIDEBAR].find(text)
            if column >= 0:
                # SGR mouse motion with no button held.
                os.write(self.fd, b"\x1b[<35;%d;%dM" % (column + 1, row + 1))
                return
        raise SystemExit(f"--hover: no sidebar line contains {text!r}")

    def close(self):
        try:
            self.cli("server", "stop")
        except Exception as error:
            print("server stop:", error, file=sys.stderr)
        try:
            os.kill(self.pid, 9)
        except ProcessLookupError:
            pass


def render(screen, out, columns):
    regular, bold = next(pair for pair in FONTS if all(os.path.exists(p) for p in pair))
    font, bold = ImageFont.truetype(regular, 15), ImageFont.truetype(bold, 15)
    cw, ch = 9, 19
    img = Image.new("RGB", (cw * columns + 16, ch * ROWS + 16), BG)
    draw = ImageDraw.Draw(img)

    def color(name, default):
        if name == "default":
            return default
        if name in NAMED:
            return NAMED[name]
        try:
            return tuple(int(name[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return default

    for y in range(ROWS):
        for x in range(columns):
            c = screen.buffer[y][x]
            px, py = 8 + x * cw, 8 + y * ch
            fg, bg = (c.bg, c.fg) if c.reverse else (c.fg, c.bg)
            draw.rectangle([px, py, px + cw - 1, py + ch - 1], fill=color(bg, BG))
            if c.data.strip():
                draw.text((px, py + 1), c.data, fill=color(fg, FG), font=bold if c.bold else font)
            if c.underscore:
                draw.line([px, py + ch - 2, px + cw - 1, py + ch - 2], fill=color(fg, FG))
    img.save(out)


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        raise SystemExit(__doc__)
    binary, out = os.path.abspath(args[0]), args[1]
    attention = "--attention" in args
    hover = args[args.index("--hover") + 1] if "--hover" in args else None
    columns = min(int(args[args.index("--columns") + 1]), COLS) if "--columns" in args else SIDEBAR + 1
    extra_env = dict(a.split("=", 1) for a in args[2:] if "=" in a and not a.startswith("--"))
    # A short path: Unix socket paths are limited to about 100 bytes.
    root = tempfile.mkdtemp(prefix="hm-", dir="/tmp")
    session = Session(binary, root, extra_env)
    try:
        session.pump(4)
        session.build()
        session.pump(2)
        if attention:
            session.attention()
        session.pump(2)
        if hover:
            session.hover(hover)
        session.pump(1)
        render(session.screen, out, columns)
        for line in session.screen.display:
            print(line[:columns].rstrip())
    finally:
        session.close()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
