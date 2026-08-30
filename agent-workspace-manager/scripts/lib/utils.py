"""Common utilities for Agent Workspace Manager."""
import os
import uuid
import re
import platform
from datetime import datetime, timezone


def generate_id():
    """Generate a unique workspace ID."""
    return uuid.uuid4().hex[:12]


def timestamp():
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def is_windows():
    """Check if running on Windows."""
    return platform.system() == "Windows"


def normalize_path(path):
    """Normalize a path to absolute, expanded form."""
    return os.path.normpath(os.path.abspath(os.path.expanduser(path)))


def _sanitize_name(name):
    """Sanitize a name for use as directory/file name."""
    safe = re.sub(r'[\\/:*?"<>|]', "-", name)
    safe = safe.strip(".")
    return safe if safe else "workspace"


def truncate_str(s, max_len=80):
    """Truncate string with ellipsis."""
    if not s:
        return ""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def format_table(rows, headers=None):
    """Format rows as a simple aligned table string."""
    if not rows:
        return ["(no data)"]
    all_rows = list(rows)
    if headers:
        all_rows.insert(0, headers)
    num_cols = max(len(r) for r in all_rows)
    widths = [0] * num_cols
    for r in all_rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(str(cell)))
    lines = []
    for idx, r in enumerate(all_rows):
        line = "  ".join(
            str(r[i]).ljust(widths[i]) if i < len(r) else "".ljust(widths[i])
            for i in range(num_cols)
        )
        lines.append(line)
        if headers and idx == 0:
            lines.append("  ".join("-" * widths[i] for i in range(num_cols)))
    return lines
