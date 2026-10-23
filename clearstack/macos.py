"""Install the local dashboard service and a Spotlight-accessible ClearStack app."""

import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request


def main():
    if sys.platform != "darwin":
        raise SystemExit("This installer is for macOS.")
    root = Path(__file__).resolve().parent.parent
    label = "com.clearstack.dashboard"
    domain = f"gui/{os.getuid()}"
    url = "http://127.0.0.1:8766/tokens"
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "clearstack"
    state.mkdir(parents=True, exist_ok=True)
    agent = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    agent.parent.mkdir(parents=True, exist_ok=True)
    python = shutil.which("python3") or sys.executable
    config = {
        "Label": label,
        "ProgramArguments": [python, "-m", "clearstack.dashboard", "--port", "8766"],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": str(state / "dashboard.log"),
        "StandardErrorPath": str(state / "dashboard.log"),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1", "XDG_STATE_HOME": str(state.parent)},
    }
    if agent.exists():
        with agent.open("rb") as handle:
            if plistlib.load(handle).get("Label") != label:
                raise SystemExit(f"Refusing to replace an unrelated service: {agent}")
    agent.write_bytes(plistlib.dumps(config))
    app = Path.home() / "Applications" / "ClearStack.app"
    contents = app / "Contents"
    executable = contents / "MacOS" / "ClearStack"
    executable.parent.mkdir(parents=True, exist_ok=True)
    resources = contents / "Resources"
    resources.mkdir(exist_ok=True)
    executable.write_text(f'#!/bin/sh\nexec /usr/bin/open "{url}"\n')
    executable.chmod(0o755)
    info = {
        "CFBundleName": "ClearStack", "CFBundleDisplayName": "ClearStack",
        "CFBundleIdentifier": "com.clearstack.launcher", "CFBundleVersion": "1",
        "CFBundlePackageType": "APPL", "CFBundleExecutable": "ClearStack",
        "CFBundleIconFile": "ClearStack.icns", "LSUIElement": True,
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    with tempfile.TemporaryDirectory() as temporary:
        icons = Path(temporary) / "ClearStack.iconset"
        icons.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(["/usr/bin/sips", "-z", str(size * scale), str(size * scale),
                                str(root / "assets" / "logo.png"), "--out", str(icons / name)],
                               check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["/usr/bin/iconutil", "-c", "icns", str(icons), "-o", str(resources / "ClearStack.icns")], check=True)
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "bootstrap", domain, str(agent)], check=True)
    register = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    subprocess.run([register, "-f", str(app)], check=True)
    for _ in range(30):
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(0.5)
    else:
        raise SystemExit(f"Dashboard did not start. See {state / 'dashboard.log'}")
    print(f"Installed {app}\nDashboard: {url}\nStarts automatically at login.")
    subprocess.run(["open", str(app)], check=True)


if __name__ == "__main__":
    main()
