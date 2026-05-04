"""``jcodemunch-mcp upgrade`` — pip install -U + refresh hooks/config.

Single command for the post-release path that previously required two
steps (``pip install -U jcodemunch-mcp`` and ``jcodemunch-mcp init
--hooks``). Picked up from issue #273: users on Copilot/parallel-session
workflows kept missing the second step and ending up with stale hook
templates pointing at older binaries.
"""

from __future__ import annotations

import shutil
import subprocess
import sys


def run_upgrade(*, no_pip: bool = False, yes: bool = True) -> int:
    """Run ``pip install -U jcodemunch-mcp`` then refresh hooks/config.

    Returns exit code (0 on success, non-zero on pip failure).
    """
    if not no_pip:
        pip_args = [sys.executable, "-m", "pip", "install", "-U", "jcodemunch-mcp"]
        print(f"$ {' '.join(pip_args)}")
        try:
            r = subprocess.run(pip_args, check=False)
        except OSError as e:
            print(f"  pip invocation failed: {e}", file=sys.stderr)
            return 1
        if r.returncode != 0:
            print(
                "  pip exited non-zero; skipping hook refresh. "
                "Re-run with --no-pip after fixing the install.",
                file=sys.stderr,
            )
            return r.returncode

    # Run init in --yes mode to refresh hook templates non-interactively.
    # Use the freshly-installed binary if it's on PATH, otherwise fall back
    # to the in-process module entry so a venv shim doesn't get bypassed.
    exe = shutil.which("jcodemunch-mcp")
    if exe:
        init_cmd = [exe, "init", "--hooks"]
    else:
        init_cmd = [sys.executable, "-m", "jcodemunch_mcp", "init", "--hooks"]
    if yes:
        init_cmd.append("--yes")

    print(f"$ {' '.join(init_cmd)}")
    try:
        r = subprocess.run(init_cmd, check=False)
    except OSError as e:
        print(f"  init invocation failed: {e}", file=sys.stderr)
        return 1
    return r.returncode
