"""Git operations module - encapsulates all git interaction."""
import os
import subprocess


class GitError(Exception):
    """Raised when a git operation fails."""
    pass


class GitModule:
    """Encapsulates all Git operations. No business logic here."""

    def __init__(self, project_root, logger=None):
        self.project_root = os.path.abspath(project_root)
        self.logger = logger

    def _run_git(self, *args, cwd=None):
        """Run a git command, return stdout. Raises GitError on failure."""
        cwd = cwd or self.project_root
        try:
            result = subprocess.run(
                ["git"] + list(args),
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                err = result.stderr.strip() or result.stdout.strip()
                raise GitError(f"git {' '.join(args)} failed: {err}")
            return result.stdout.strip()
        except FileNotFoundError:
            raise GitError("git not found in PATH")
        except subprocess.TimeoutExpired:
            raise GitError(f"git {' '.join(args)} timed out")
        except GitError:
            raise
        except Exception as e:
            raise GitError(f"git {' '.join(args)} error: {e}")

    def is_git_repo(self):
        """Check if the project root is inside a git repository."""
        try:
            self._run_git("rev-parse", "--git-dir")
            return True
        except GitError:
            return False

    def get_repo_root(self):
        """Get the root directory of the git repository."""
        return self._run_git("rev-parse", "--show-toplevel")

    def get_current_branch(self):
        """Get the current branch name. Returns None if detached HEAD."""
        try:
            branch = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
            if branch == "HEAD":
                return None
            return branch
        except GitError:
            return None

    def get_default_branch(self):
        """Get the default branch (main or master)."""
        try:
            ref = self._run_git("symbolic-ref", "refs/remotes/origin/HEAD")
            return ref.replace("refs/remotes/origin/", "")
        except GitError:
            pass
        for branch in ["main", "master"]:
            try:
                self._run_git("rev-parse", "--verify", f"refs/heads/{branch}")
                return branch
            except GitError:
                continue
        return "master"

    def branch_exists(self, branch_name):
        """Check if a branch (local or remote) exists."""
        try:
            self._run_git("rev-parse", "--verify", f"refs/heads/{branch_name}")
            return True
        except GitError:
            pass
        try:
            self._run_git("rev-parse", "--verify", f"refs/remotes/origin/{branch_name}")
            return True
        except GitError:
            return False

    def create_worktree(self, worktree_path, branch_name, base_branch=None):
        """Create a git worktree at the given path with a new branch."""
        worktree_path = os.path.abspath(worktree_path)
        if base_branch is None:
            base_branch = self.get_current_branch() or self.get_default_branch()
        self._run_git("worktree", "add", "-b", branch_name, worktree_path, base_branch)
        return worktree_path

    def create_worktree_existing_branch(self, worktree_path, branch_name):
        """Create a worktree using an existing branch."""
        worktree_path = os.path.abspath(worktree_path)
        self._run_git("worktree", "add", worktree_path, branch_name)
        return worktree_path

    def delete_worktree(self, worktree_path, force=True):
        """Remove a git worktree. Default force=True (skill workspaces have untracked IDEA config)."""
        worktree_path = os.path.abspath(worktree_path)
        cmd = ["worktree", "remove", "--force", worktree_path]
        try:
            self._run_git(*cmd)
            return True
        except GitError:
            # Fallback: manual directory removal + prune
            try:
                self._run_git("worktree", "prune")
            except GitError:
                pass
            if not self.is_valid_worktree(worktree_path):
                return True
            raise

    def list_worktrees(self):
        """List all worktrees. Returns list of dicts with path, branch, head."""
        output = self._run_git("worktree", "list", "--porcelain")
        worktrees = []
        current = {}
        for line in output.split("\n"):
            if not line.strip():
                if current:
                    worktrees.append(current)
                    current = {}
                continue
            if line.startswith("worktree "):
                current["path"] = line[len("worktree "):]
            elif line.startswith("HEAD "):
                current["head"] = line[len("HEAD "):]
            elif line.startswith("branch "):
                current["branch"] = line[len("branch "):].replace("refs/heads/", "")
            elif line.startswith("detached"):
                current["detached"] = True
        if current:
            worktrees.append(current)
        return worktrees

    def is_valid_worktree(self, path):
        """Check if a path is a valid git worktree."""
        path = os.path.abspath(path)
        worktrees = self.list_worktrees()
        for wt in worktrees:
            if os.path.abspath(wt.get("path", "")) == path:
                return True
        return False

    def get_branches(self, remote=False):
        """List all branches."""
        cmd = ["branch", "--list"]
        if remote:
            cmd.append("-r")
        output = self._run_git(*cmd)
        branches = []
        for line in output.split("\n"):
            line = line.strip()
            if line:
                line = line.lstrip("* ").strip()
                if line and "HEAD ->" not in line:
                    branches.append(line)
        return branches
