#!/usr/bin/env python3
"""
Agent Workspace Manager - CLI entry point.

Provides isolated development workspaces using Git Worktree.
Workspaces are created as siblings of the source project directory.

Usage:
    python3 workspace_manager.py create [branch-name]
    python3 workspace_manager.py list [--project PROJECT]
    python3 workspace_manager.py open --name NAME [--project PROJECT]
    python3 workspace_manager.py delete --name NAME [--project PROJECT]
"""
import sys
import os
import argparse

# Add the scripts directory to path so we can import lib
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from lib.config import Config
from lib.logger import Logger
from lib.workspace import WorkspaceManager, WorkspaceError, WorkspaceExistsError
from lib.idea import IdeaError
from lib.git_ops import GitError
from lib.registry import RegistryError
from lib import utils


def get_config_path(args):
    """Get config file path."""
    if getattr(args, "config", None):
        return getattr(args, "config")
    skill_root = os.path.dirname(SCRIPT_DIR)
    return os.path.join(skill_root, "config", "config.json")


def get_config(config_path=None):
    """Load configuration. Priority: --config flag > skill dir config > defaults."""
    if not config_path:
        skill_root = os.path.dirname(SCRIPT_DIR)
        config_path = os.path.join(skill_root, "config", "config.json")
    return Config(config_path)


def get_manager(args):
    """Create a WorkspaceManager instance from CLI args."""
    config = get_config(getattr(args, "config", None))
    logger = Logger(config.get_log_dir(), config.get("enableLogging", True))
    return WorkspaceManager(config, logger)


def cmd_create(args):
    """Create a new workspace."""
    manager = get_manager(args)
    try:
        ws = manager.create(
            branch=args.branch,
            no_idea_config=args.no_idea_config,
            launch_idea=True,
        )
        print(f"OK: Workspace created")
        print(f"  Name:    {ws['workspaceName']}")
        print(f"  Path:    {ws['workspacePath']}")
        print(f"  Branch:  {ws['branch']}")
        print(f"  ID:      {ws['id']}")
        return 0
    except WorkspaceExistsError as e:
        existing = e.entry
        print(f"NOTE: Workspace already exists, skipping creation.")
        print(f"  Name:    {existing.get('workspaceName', '?')}")
        print(f"  Path:    {existing.get('workspacePath', '?')}")
        print(f"  Branch:  {existing.get('branch', '?')}")
        # Try to open it for the user
        try:
            ws = manager.open(
                name=existing.get("workspaceName"),
                project=existing.get("projectName"),
            )
            print(f"\nOpened existing workspace.")
            return 0
        except IdeaError as ie:
            config_path = get_config_path(args)
            print(f"\nCould not open IDEA.", file=sys.stderr)
            print(f"\n{ie}", file=sys.stderr)
            print(f"\nConfig file: {config_path}", file=sys.stderr)
            print(f"Run: wsopen --name {existing.get('workspaceName', '?')}", file=sys.stderr)
            return 0
        except Exception:
            print(f"\nTo open it later, run: wsopen --name {existing.get('workspaceName', '?')}")
            return 0
    except IdeaError as e:
        # Workspace was created successfully, but IDEA launch failed.
        # The workspace entry is already registered and usable.
        config_path = get_config_path(args)
        print(f"OK: Workspace created (but IDEA could not open)")
        print(f"\n{e}", file=sys.stderr)
        print(f"\nConfig file: {config_path}", file=sys.stderr)
        print(f"After fixing, run: wsopen --name <name>", file=sys.stderr)
        return 0
    except (WorkspaceError, GitError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_open(args):
    """Open an existing workspace in IDEA."""
    manager = get_manager(args)
    try:
        ws = manager.open(
            name=args.name,
            project=args.project,
        )
        print(f"OK: Workspace opened")
        print(f"  Name:    {ws['workspaceName']}")
        print(f"  Path:    {ws['workspacePath']}")
        print(f"  Branch:  {ws['branch']}")
        return 0
    except IdeaError as e:
        config_path = get_config_path(args)
        print(f"ERROR: Could not open IDEA.\n\n{e}", file=sys.stderr)
        print(f"\nConfig file: {config_path}", file=sys.stderr)
        print(f"After fixing, run: wsopen --name {args.name}", file=sys.stderr)
        return 1
    except WorkspaceError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_delete(args):
    """Delete a workspace (worktree directory + registry, branch preserved)."""
    manager = get_manager(args)
    try:
        manager.delete(
            name=args.name,
            project=args.project,
        )
        print(f"OK: Workspace deleted")
        return 0
    except WorkspaceError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_list(args):
    """List all managed workspaces."""
    manager = get_manager(args)
    grouped = manager.list(project=args.project)

    if not grouped:
        print("(no workspaces)")
        return 0

    for project_name, workspaces in sorted(grouped.items()):
        print(f"\n[{project_name}]")
        headers = ["Name", "Branch", "Status", "Created", "Last Opened"]
        rows = []
        for ws in workspaces:
            rows.append([
                ws.get("workspaceName", ""),
                ws.get("branch", ""),
                ws.get("status", ""),
                utils.truncate_str(ws.get("createdAt", ""), 19),
                utils.truncate_str(ws.get("lastOpenedAt", ""), 19),
            ])
        lines = utils.format_table(rows, headers)
        for line in lines:
            print(f"  {line}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="workspace_manager",
        description="Agent Workspace Manager - isolated development workspaces via Git Worktree",
    )
    parser.add_argument("--config", help="Path to config.json", default=None)
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # create
    p_create = subparsers.add_parser("create", help="Create a new workspace (default branch: master)")
    p_create.add_argument("branch", nargs="?", default=None,
                          help="Branch name (default: master). Existing branch is checked out; "
                               "non-existing branch is created from current HEAD.")
    p_create.add_argument("--no-idea-config", action="store_true", help="Skip IDEA config copying")
    p_create.set_defaults(func=cmd_create)

    # open
    p_open = subparsers.add_parser("open", help="Open a workspace in IDEA")
    p_open.add_argument("--name", required=True, help="Workspace name")
    p_open.add_argument("--project", default=None, help="Project name (default: current project)")
    p_open.set_defaults(func=cmd_open)

    # delete
    p_delete = subparsers.add_parser("delete", help="Delete a workspace (branch preserved)")
    p_delete.add_argument("--name", required=True, help="Workspace name")
    p_delete.add_argument("--project", default=None, help="Project name (default: current project)")
    p_delete.set_defaults(func=cmd_delete)

    # list
    p_list = subparsers.add_parser("list", help="List all managed workspaces")
    p_list.add_argument("--project", default=None, help="Filter by project name")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
