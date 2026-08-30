"""Workspace module - core orchestrator for workspace lifecycle operations."""
import os
import subprocess

from . import utils
from . import file_ops
from .git_ops import GitModule, GitError
from .registry import Registry
from .idea import IdeaModule
from .config import Config


class WorkspaceError(Exception):
    """Raised when workspace operations fail."""
    pass


class WorkspaceExistsError(Exception):
    """Raised when a workspace already exists. Carries the existing entry."""
    def __init__(self, entry):
        self.entry = entry
        super().__init__(
            f"Workspace already exists: {entry.get('workspaceName', '?')} "
            f"(branch: {entry.get('branch', '?')}, path: {entry.get('workspacePath', '?')})"
        )


class WorkspaceManager:
    """
    Core workspace lifecycle manager.

    Workspaces are created as siblings of the source project directory.
    Path pattern: {project_parent}/{project_name}-{branch_name}/
    """

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self.registry = Registry(config.get_registry_path(), logger)
        self.idea = IdeaModule(config, logger)

    def _resolve_project(self, project_root=None):
        """Resolve and validate the project root. Default: cwd."""
        project_root = project_root or os.getcwd()
        project_root = utils.normalize_path(project_root)

        if not os.path.isdir(project_root):
            raise WorkspaceError(f"Project directory does not exist: {project_root}")

        git = GitModule(project_root, self.logger)
        if not git.is_git_repo():
            raise WorkspaceError(f"Not a git repository: {project_root}")

        repo_root = git.get_repo_root()
        project_name = os.path.basename(repo_root)
        project_parent = os.path.dirname(repo_root)

        return project_root, repo_root, project_name, project_parent, git

    def _workspace_path(self, project_parent, project_name, ws_name):
        """Build workspace path as sibling of project: {parent}/{project}-{ws_name}/"""
        return os.path.join(project_parent, f"{project_name}-{ws_name}")

    # --- Create ---

    def create(self, branch=None, project_root=None, no_idea_config=False,
               launch_idea=None):
        """
        Create a new workspace from the current project.

        Args:
            branch: branch name to use. If the branch exists, check it out;
                    if not, create a new branch from current HEAD.
                    Default: "master".
            project_root: project path (default: cwd).
            no_idea_config: skip IDEA config copying.
            launch_idea: override config to launch/not launch IDEA.

        Returns:
            dict: workspace entry

        Raises:
            WorkspaceError on failure (with rollback applied)
        """
        project_root, repo_root, project_name, project_parent, git = \
            self._resolve_project(project_root)

        branch = branch or "master"

        # Determine workspace name from branch
        ws_name = utils._sanitize_name(branch)

        # Check if a workspace for this project+branch already exists
        existing_names = self.registry.get_existing_names(project_name)
        if ws_name in existing_names:
            # Already in registry - find and return it, don't create
            existing = self.registry.get_by_name(project_name, ws_name)
            if existing:
                # Verify the workspace directory still exists
                ws_path_check = existing.get("workspacePath", "")
                if os.path.isdir(ws_path_check):
                    if self.logger:
                        self.logger.info(f"Workspace already exists: {existing['id']}", existing["id"])
                    raise WorkspaceExistsError(existing)
                # Directory gone but registry entry remains - fall through to recreate

        # Workspace path: sibling of project
        ws_path = self._workspace_path(project_parent, project_name, ws_name)

        # Check if workspace path already exists on disk
        if os.path.exists(ws_path):
            existing = self.registry.get_by_path(ws_path)
            if existing:
                if self.logger:
                    self.logger.info(f"Workspace already exists (by path): {existing['id']}", existing["id"])
                raise WorkspaceExistsError(existing)
            raise WorkspaceError(
                f"Workspace directory exists but not in registry: {ws_path}. "
                f"Manual cleanup required."
            )

        ws_id = utils.generate_id()
        now = utils.timestamp()

        # Determine branch strategy:
        # - Branch doesn't exist → create new from HEAD
        # - Branch exists but NOT current → check out existing
        # - Branch exists AND is current → create new branch with suffix (git can't
        #   have same branch in two worktrees)
        current_branch = git.get_current_branch()
        rollback_steps = []
        actual_branch = branch

        try:
            if not git.branch_exists(branch):
                # Create new branch from current HEAD
                git.create_worktree(ws_path, branch)
            elif branch == current_branch:
                # Same branch is already checked out in main worktree
                # Create a new branch from HEAD with suffix
                actual_branch = self._unique_name(branch, git.get_branches())
                git.create_worktree(ws_path, actual_branch)
            else:
                # Existing branch, not current → safe to check out in worktree
                git.create_worktree_existing_branch(ws_path, branch)
            rollback_steps.append(("worktree", ws_path, actual_branch, repo_root))
            if self.logger:
                self.logger.log("create", f"Created git worktree at {ws_path}", ws_id,
                                {"branch": actual_branch, "requestedBranch": branch, "projectRoot": project_root})

        except GitError as e:
            if self.logger:
                self.logger.error("git_error", str(e), ws_id)
            raise WorkspaceError(f"Failed to create git worktree: {e}")

        # Copy IDEA configuration
        if not no_idea_config and self.config.get("copyIdeaConfiguration", True):
            try:
                copied = self.idea.copy_configuration(project_root, ws_path)
                rollback_steps.append(("idea_config", ws_path, copied))
            except Exception as e:
                if self.logger:
                    self.logger.error("idea_error", f"Failed to copy IDEA config: {e}", ws_id)
                if self.config.get("enableRollback", True):
                    self._rollback(rollback_steps, ws_id)
                raise WorkspaceError(f"Failed to copy IDEA configuration: {e}")

        # Register workspace
        workspace_entry = {
            "id": ws_id,
            "projectName": project_name,
            "projectRoot": project_root,
            "workspaceName": ws_name,
            "workspacePath": ws_path,
            "branch": actual_branch,
            "type": "git-worktree",
            "createdAt": now,
            "lastOpenedAt": now,
            "status": "created",
        }
        try:
            self.registry.add_workspace(workspace_entry)
            rollback_steps.append(("registry", ws_id, None))
        except Exception as e:
            if self.logger:
                self.logger.error("registry_error", f"Failed to register workspace: {e}", ws_id)
            if self.config.get("enableRollback", True):
                self._rollback(rollback_steps, ws_id)
            raise WorkspaceError(f"Failed to register workspace: {e}")

        # Launch IDEA (optional)
        should_launch = launch_idea if launch_idea is not None else self.config.get("launchIdeaAfterCreate", False)
        if should_launch:
            self.idea.launch(ws_path)

        if self.logger:
            self.logger.log("create", f"Workspace created successfully: {ws_name}", ws_id,
                            {"path": ws_path, "branch": branch})

        return workspace_entry

    # --- Open ---

    def open(self, name, project=None):
        """Open an existing workspace (launch IDEA and update timestamp)."""
        project = project or self._detect_project_name()
        ws = self.registry.get_by_name(project, name)
        if not ws:
            raise WorkspaceError(f"Workspace not found: {name} (project: {project})")

        ws_path = ws["workspacePath"]
        if not os.path.isdir(ws_path):
            raise WorkspaceError(f"Workspace directory missing: {ws_path}")

        # Launch IDEA
        self.idea.launch(ws_path)

        # Update registry
        self.registry.update_workspace(ws["id"], {
            "lastOpenedAt": utils.timestamp(),
            "status": "opened",
        })

        if self.logger:
            self.logger.log("open", f"Opened workspace: {ws['workspaceName']}", ws["id"])

        return self.registry.get_by_id(ws["id"])

    # --- Delete ---

    def delete(self, name, project=None):
        """Delete a workspace: remove worktree directory + registry entry. Branch is preserved."""
        project = project or self._detect_project_name()
        ws = self.registry.get_by_name(project, name)
        if not ws:
            raise WorkspaceError(f"Workspace not found: {name} (project: {project})")

        ws_id = ws["id"]
        ws_path = ws["workspacePath"]
        project_root = ws.get("projectRoot")

        # Remove git worktree (force=True: skill workspaces have untracked IDEA config files)
        if project_root and os.path.isdir(project_root):
            git = GitModule(project_root, self.logger)
            try:
                if git.is_valid_worktree(ws_path):
                    git.delete_worktree(ws_path, force=True)
                else:
                    git.delete_worktree(ws_path, force=True)
            except GitError as e:
                if self.logger:
                    self.logger.warning(f"Git worktree removal failed, trying manual cleanup: {e}", ws_id)
                # Fallback: manual directory removal + prune
                if os.path.exists(ws_path):
                    file_ops.safe_delete(ws_path)
                try:
                    git._run_git("worktree", "prune")
                except GitError:
                    pass

        # Remove directory if still exists
        if os.path.exists(ws_path):
            file_ops.safe_delete(ws_path)

        # Remove from registry
        self.registry.remove_workspace(ws_id)

        if self.logger:
            self.logger.log("delete", f"Deleted workspace: {ws.get('workspaceName')}", ws_id,
                            {"path": ws_path})

        return True

    # --- List ---

    def list(self, project=None):
        """List all managed workspaces, optionally filtered by project."""
        if project:
            workspaces = self.registry.get_by_project(project)
        else:
            workspaces = self.registry.get_all()

        grouped = {}
        for ws in workspaces:
            pname = ws.get("projectName", "unknown")
            if pname not in grouped:
                grouped[pname] = []
            grouped[pname].append(ws)

        return grouped

    # --- Internal helpers ---

    def _detect_project_name(self):
        """Detect project name from cwd."""
        project_root, repo_root, project_name, _, _ = self._resolve_project()
        return project_name

    def _unique_name(self, base_name, existing_names):
        """Generate unique name by appending -2, -3, etc."""
        counter = 2
        while True:
            candidate = f"{base_name}-{counter}"
            if candidate not in existing_names:
                return candidate
            counter += 1

    def _rollback(self, steps, ws_id):
        """Rollback completed steps in reverse order."""
        if self.logger:
            self.logger.rollback(f"Rolling back {len(steps)} steps", ws_id)

        for step_type, *step_args in reversed(steps):
            try:
                if step_type == "worktree":
                    ws_path, branch, proj_root = step_args[0], step_args[1], step_args[2]
                    if proj_root and os.path.isdir(proj_root):
                        git = GitModule(proj_root, self.logger)
                        git.delete_worktree(ws_path, force=True)
                elif step_type == "idea_config":
                    ws_path, copied_files = step_args[0], step_args[1]
                    for src, dst in copied_files:
                        file_ops.safe_delete(dst)
                    idea_dir = os.path.join(ws_path, ".idea")
                    if os.path.isdir(idea_dir) and not os.listdir(idea_dir):
                        file_ops.safe_delete(idea_dir)
                elif step_type == "registry":
                    ws_id_to_remove = step_args[0]
                    self.registry.remove_workspace(ws_id_to_remove)
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Rollback step {step_type} failed: {e}", ws_id)
