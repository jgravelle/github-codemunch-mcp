"""Hook event handler — receives Claude Code worktree events and writes to a JSONL manifest."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_MANIFEST_PATH = Path.home() / ".claude" / "jcodemunch-worktrees.jsonl"


def handle_hook_event(event_type: str, manifest_path: Path = DEFAULT_MANIFEST_PATH) -> None:
    """Read worktree JSON from stdin, append an event line to the JSONL manifest.

    Called by Claude Code's WorktreeCreate/WorktreeRemove hooks via:
        jcodemunch-mcp hook-event create
        jcodemunch-mcp hook-event remove
    """
    payload = json.load(sys.stdin)
    worktree_path = payload.get("worktreePath") or payload.get("worktree_path")
    if not worktree_path:
        print("ERROR: no worktreePath in stdin payload", file=sys.stderr)
        sys.exit(1)

    resolved = str(Path(worktree_path).resolve())
    entry = {
        "event": event_type,
        "path": resolved,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
        f.flush()

    print(f"jcodemunch-mcp: recorded {event_type} for {resolved}", file=sys.stderr)


def read_manifest(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> set[str]:
    """Read the JSONL manifest and return the set of currently active worktree paths.

    Replays all events in order: a 'create' adds a path, a 'remove' removes it.
    """
    active: dict[str, bool] = {}
    if not manifest_path.is_file():
        return set()

    with open(manifest_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            path = entry.get("path")
            event = entry.get("event")
            if not path or event not in ("create", "remove"):
                continue
            active[path] = event == "create"

    return {p for p, is_active in active.items() if is_active}
