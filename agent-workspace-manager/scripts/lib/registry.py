"""Registry module - atomic read/write/backup for the workspace registry."""
import os
import json
import time
import tempfile
import shutil

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

from . import file_ops

REGISTRY_VERSION = 1

EMPTY_REGISTRY = {
    "version": REGISTRY_VERSION,
    "workspaces": [],
}


class RegistryError(Exception):
    """Raised when registry operations fail."""
    pass


class Registry:
    """Registry manager with atomic writes, locking, and backup."""

    def __init__(self, registry_path, logger=None):
        self.registry_path = os.path.abspath(registry_path)
        self.lock_path = self.registry_path + ".lock"
        self.backup_path = self.registry_path + ".bak"
        self.logger = logger
        self._ensure_registry()

    def _ensure_registry(self):
        """Create the registry file if it doesn't exist."""
        os.makedirs(os.path.dirname(self.registry_path), exist_ok=True)
        if not os.path.isfile(self.registry_path):
            file_ops.atomic_write_json(self.registry_path, EMPTY_REGISTRY)

    def _acquire_lock(self, timeout=10):
        """Acquire an exclusive lock on the registry."""
        if _HAS_FCNTL:
            lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_WRONLY, 0o644)
            start = time.time()
            while True:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return lock_fd
                except (IOError, OSError):
                    if time.time() - start > timeout:
                        os.close(lock_fd)
                        raise RegistryError("Registry lock timeout")
                    time.sleep(0.1)
        else:
            start = time.time()
            while True:
                try:
                    fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                    return fd
                except FileExistsError:
                    try:
                        mtime = os.path.getmtime(self.lock_path)
                        if time.time() - mtime > timeout:
                            os.remove(self.lock_path)
                            continue
                    except OSError:
                        pass
                    if time.time() - start > timeout:
                        raise RegistryError("Registry lock timeout")
                    time.sleep(0.1)

    def _release_lock(self, lock_fd):
        """Release the registry lock."""
        try:
            if _HAS_FCNTL:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
            if os.path.exists(self.lock_path):
                os.remove(self.lock_path)
        except OSError:
            pass

    def read(self):
        """Read the registry. Returns a copy of the registry dict."""
        try:
            return file_ops.read_json(self.registry_path)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            if self.logger:
                self.logger.error("registry_error", f"Failed to read registry: {e}")
            if os.path.isfile(self.backup_path):
                try:
                    return file_ops.read_json(self.backup_path)
                except Exception:
                    pass
            return dict(EMPTY_REGISTRY)

    def _read_locked(self):
        """Read registry (should be called while holding lock)."""
        try:
            return file_ops.read_json(self.registry_path)
        except (FileNotFoundError, json.JSONDecodeError):
            if os.path.isfile(self.backup_path):
                try:
                    return file_ops.read_json(self.backup_path)
                except Exception:
                    pass
            return dict(EMPTY_REGISTRY)

    def write(self, registry_data):
        """Atomically write the registry. Acquires lock, backs up, writes."""
        lock_fd = self._acquire_lock()
        try:
            if os.path.isfile(self.registry_path):
                shutil.copy2(self.registry_path, self.backup_path)
            file_ops.atomic_write_json(self.registry_path, registry_data)
        finally:
            self._release_lock(lock_fd)

    def add_workspace(self, workspace_entry):
        """Add a workspace entry to the registry. Atomic."""
        lock_fd = self._acquire_lock()
        try:
            data = self._read_locked()
            data["workspaces"].append(workspace_entry)
            file_ops.atomic_write_json(self.registry_path, data)
        finally:
            self._release_lock(lock_fd)

    def remove_workspace(self, workspace_id):
        """Remove a workspace by ID. Returns True if removed."""
        lock_fd = self._acquire_lock()
        try:
            data = self._read_locked()
            before = len(data["workspaces"])
            data["workspaces"] = [w for w in data["workspaces"] if w.get("id") != workspace_id]
            after = len(data["workspaces"])
            if before != after:
                file_ops.atomic_write_json(self.registry_path, data)
                return True
            return False
        finally:
            self._release_lock(lock_fd)

    def update_workspace(self, workspace_id, updates):
        """Update fields of a workspace by ID. Returns True if found."""
        lock_fd = self._acquire_lock()
        try:
            data = self._read_locked()
            found = False
            for w in data["workspaces"]:
                if w.get("id") == workspace_id:
                    w.update(updates)
                    found = True
                    break
            if found:
                file_ops.atomic_write_json(self.registry_path, data)
            return found
        finally:
            self._release_lock(lock_fd)

    def get_by_id(self, workspace_id):
        """Lookup workspace by ID."""
        data = self.read()
        for w in data["workspaces"]:
            if w.get("id") == workspace_id:
                return w
        return None

    def get_by_name(self, project_name, workspace_name):
        """Lookup workspace by project name and workspace name."""
        data = self.read()
        for w in data["workspaces"]:
            if w.get("projectName") == project_name and w.get("workspaceName") == workspace_name:
                return w
        return None

    def get_by_project(self, project_name):
        """Get all workspaces for a project."""
        data = self.read()
        return [w for w in data["workspaces"] if w.get("projectName") == project_name]

    def get_by_path(self, path):
        """Lookup workspace by workspace path."""
        path = os.path.abspath(path)
        data = self.read()
        for w in data["workspaces"]:
            if os.path.abspath(w.get("workspacePath", "")) == path:
                return w
        return None

    def get_all(self):
        """Get all workspaces."""
        data = self.read()
        return data["workspaces"]

    def get_existing_names(self, project_name):
        """Get set of existing workspace names for a project."""
        workspaces = self.get_by_project(project_name)
        return {w.get("workspaceName") for w in workspaces}
