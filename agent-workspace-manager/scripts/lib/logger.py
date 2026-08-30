"""Structured logging for Agent Workspace Manager operations."""
import os
import json
from datetime import datetime, timezone


class Logger:
    """Structured JSON-lines logger for workspace operations."""

    EVENT_TYPES = {
        "create": "CREATE",
        "delete": "DELETE",
        "open": "OPEN",
        "rollback": "ROLLBACK",
        "git_error": "GIT_ERROR",
        "idea_error": "IDEA_ERROR",
        "registry_error": "REGISTRY_ERROR",
        "warning": "WARNING",
        "info": "INFO",
    }

    def __init__(self, log_dir, enabled=True):
        self.log_dir = os.path.abspath(log_dir)
        self.enabled = enabled
        if enabled:
            os.makedirs(self.log_dir, exist_ok=True)

    def _log_file(self):
        """Return today's log file path."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return os.path.join(self.log_dir, f"workspace-{today}.jsonl")

    def log(self, event_type, message, workspace_id=None, details=None):
        """Log an event."""
        if not self.enabled:
            return
        event_code = self.EVENT_TYPES.get(event_type, event_type.upper())
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_code,
            "message": message,
            "workspaceId": workspace_id,
            "details": details or {},
        }
        try:
            with open(self._log_file(), "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def info(self, message, workspace_id=None, details=None):
        self.log("info", message, workspace_id, details)

    def warning(self, message, workspace_id=None, details=None):
        self.log("warning", message, workspace_id, details)

    def error(self, event_type, message, workspace_id=None, details=None):
        """Log an error event (git_error, idea_error, registry_error)."""
        self.log(event_type, message, workspace_id, details)

    def rollback(self, message, workspace_id=None, details=None):
        self.log("rollback", message, workspace_id, details)
