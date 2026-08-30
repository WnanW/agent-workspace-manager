# Agent Workspace Manager

Isolated development workspace manager using Git Worktree, with IntelliJ IDEA
configuration preservation and rollback support. Ships as a skill package
(compatible with Hermes, Claude Code, and OpenCode).

## Requirements

- Python 3.8+
- Git with worktree support (`git worktree`)
- Optional: IntelliJ IDEA (for `ws open`)

## Installation

### From a release tarball

```bash
# Hermes
tar xzf releases/agent-workspace-manager-skill.tar.gz -C ~/.hermes/skills/software-development/

# Claude Code
tar xzf releases/agent-workspace-manager-claude.tar.gz -C ~/.claude/skills/

# OpenCode
tar xzf releases/agent-workspace-manager-opencode.tar.gz -C ~/.config/opencode/skills/
```

### From source

The skill lives in `agent-workspace-manager/`. To make the `ws` commands
available globally (installs `ws`, `wscreate`, `wslist`, `wsopen`, `wsdelete`
to `~/.local/bin/`):

```bash
bash agent-workspace-manager/install.sh
```

## Usage

### Agent usage (natural language)

This is a **skill**: after installing it to your agent's skills directory
(OpenCode: `~/.config/opencode/skills/`, Claude Code: `~/.claude/skills/`,
Hermes: `~/.hermes/skills/`), the agent loads `SKILL.md` automatically. You
don't type any commands — just ask in natural language, for example:

> "Create an isolated workspace on a new branch to fix this bug, and open it
> in IDEA."
>
> "List my current workspaces."
>
> "Delete the workspace for the login feature, keep the branch."

The agent will invoke the `ws` commands (or the Python script) itself. Note:
the agent's commands rely on the `ws` wrappers, so `bash install.sh` must have
been run once on the machine first.

### Manual usage (CLI)

```bash
# In your project directory:
wscreate                    # create a workspace on master (auto-suffix if master is current)
wscreate feature-login      # create a workspace on feature-login branch
wslist                      # list all managed workspaces
wsopen --name feature-login # open the workspace in IDEA
wsdelete --name feature-login  # delete workspace (branch preserved)
```

Or invoke the script directly:

```bash
python3 agent-workspace-manager/scripts/workspace_manager.py create --name feature-login
```

Workspaces are created as sibling directories of the source project, keeping
the main working tree clean while allowing parallel work on different branches.

## Documentation

- `agent-workspace-manager/SKILL.md` — full documentation and changelog
- `agent-workspace-manager/references/git-worktree-idea-pitfalls.md` — 14
  documented pitfalls of git worktree + IDEA config interactions
- `agent-workspace-manager/references/cross-platform-skill-packaging.md` —
  how the release tarballs are packaged for each platform

## License

MIT
