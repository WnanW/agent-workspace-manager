"""Configuration management for Agent Workspace Manager."""
import os
import json


DEFAULT_CONFIG = {
    "ideaExecutable": None,
    "copyIdeaConfiguration": True,
    "enableLogging": True,
    "enableRollback": True,
}

# Blacklist: .idea/ files and dirs that are runtime/user state.
# These are NEVER copied and are removed from the workspace after git checkout.
# Everything else in .idea/ is copied (modules.xml, compiler.xml, libraries/,
# codeStyles/, runConfigurations/, etc.)
#
# Note: workspace.xml is in the blacklist for BULK copy, but it is specially
# handled - useful components are extracted from it (see below).
IDEA_IGNORE_PATTERNS = [
    "workspace.xml",
    "tasks.xml",
    "usage.local.xml",
    "shelf",
    "caches",
    "local_history",
    "workspace",
]

# workspace.xml is a mixed file: it contains both useful project configuration
# AND runtime UI state (window positions, recent files, breakpoints, etc.).
# These are the component names we EXTRACT from workspace.xml and carry over
# to the new workspace. Everything else in workspace.xml is discarded.
#
# - MavenProjectsManager: Maven project tree (linked pom.xml files, resolved
#   dependency list). Without this, Maven projects must be re-linked.
# - MavenImportPreferences: Maven workspace settings (Maven home path,
#   settings.xml path, import options, profile selections). This is the
#   actual "Maven configuration" users care about. Without it, Maven settings
#   reset to defaults in the new workspace.
# - RunManager: Run/debug configurations that were NOT saved as separate
#   project files (i.e., user didn't check "Store as project file").
#   Without this, non-shared run configs are lost.
WORKSPACE_XML_KEEP_COMPONENTS = [
    "MavenProjectsManager",
    "MavenImportPreferences",
    "RunManager",
]

# Fixed global data directory for registry and logs
DATA_DIR = os.path.expanduser("~/.workspace-manager")


class Config:
    """Configuration manager with defaults and external config file support."""

    def __init__(self, config_path=None):
        self.config_path = config_path
        self._config = dict(DEFAULT_CONFIG)
        if config_path and os.path.isfile(config_path):
            self._load()

    def _load(self):
        """Load config from JSON file, merging with defaults."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            self._config.update(user_config)
        except (json.JSONDecodeError, IOError):
            pass

    def get(self, key, default=None):
        """Get a config value, expanding ~ for path values."""
        val = self._config.get(key, default)
        if isinstance(val, str) and val and (val.startswith("~/") or val.startswith("~\\")):
            return os.path.expanduser(val)
        return val

    def set(self, key, value):
        """Set a config value (in-memory only, not persisted)."""
        self._config[key] = value

    def save(self):
        """Persist current config to the config file."""
        if not self.config_path:
            return
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)

    def get_registry_path(self):
        """Get the registry file path."""
        return os.path.join(DATA_DIR, "registry.json")

    def get_log_dir(self):
        """Get the log directory path."""
        return os.path.join(DATA_DIR, "logs")

    def all(self):
        """Return all config as dict."""
        return dict(self._config)
