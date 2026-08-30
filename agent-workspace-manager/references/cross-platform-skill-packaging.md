# Cross-Platform Skill Packaging

Pattern for packaging one skill across Hermes, Claude Code, and OpenCode.
All three platforms support the Agent Skills open standard (SKILL.md + scripts/ +
references/), but differ in frontmatter fields and script path resolution.

## v3.0: Unified Single Package

**One tar.gz for all platforms.** The Python/scripts code is identical and
SKILL.md is shared. Key technique: merge ALL platform-specific frontmatter
fields into one file — each platform reads the fields it recognizes and ignores
the rest.

```yaml
# Merged frontmatter — works on all three platforms
name: agent-workspace-manager
description: |
  ...
category: software-development          # Hermes
allowed-tools:                           # Claude Code
  - Bash
  - Read
disable-model-invocation: false          # Claude Code
license: MIT                             # OpenCode
compatibility:                           # OpenCode
  - opencode
metadata:                                # OpenCode
  version: "3.0.0"
```

**No per-platform SKILL.md generation needed.** No path substitution. One
`tar.gz` per release instead of three.

## Platform Differences (reference)

| Aspect | Hermes | Claude Code | OpenCode |
|--------|--------|-------------|----------|
| Install path | `~/.hermes/skills/<category>/<name>/` | `~/.claude/skills/<name>/` | `~/.config/opencode/skills/<name>/` |
| Script path resolution | Relative from skill dir | Relative from skill dir | Absolute (agent cwd = project) |
| Frontmatter recognized | name, description, category | name, description, allowed-tools, disable-model-invocation | name, description, license, compatibility, metadata |
| Ignored fields | allowed-tools, license, compatibility | category, license, compatibility | category, allowed-tools, disable-model-invocation |

## The Script Path Problem

OpenCode agents run with the user's project as cwd, not the skill directory.
Relative paths like `scripts/workspace_manager.py` won't resolve from project cwd.

**v3.0 solution:** `install.sh` installs `ws`/`wscreate`/`wslist`/`wsopen`/`wsdelete`
wrapper scripts to `~/.local/bin/` with the Python script path hardcoded at install
time. SKILL.md references `wscreate` etc., not Python paths. This sidesteps the
relative-vs-absolute path problem entirely — all platforms call the same `ws`
commands regardless of skill install location.

**Pre-v3.0 approach (deprecated):** Generate three SKILL.md variants, substituting
relative paths with absolute `~/.config/opencode/skills/<name>/scripts/...` for
OpenCode. Required per-platform packaging and was fragile if install path changed.

## install.sh Wrapper Pattern

```bash
# install.sh generates wrapper scripts with hardcoded Python path
PYTHON_SCRIPT="$SCRIPT_DIR/scripts/workspace_manager.py"

# ws dispatcher (subcommand form: ws create, ws list, ...)
printf '#!/bin/bash\nPYTHON_SCRIPT="%s"\ncase ...' "$PYTHON_SCRIPT" > "$BIN_DIR/ws"

# Alias wrappers (direct form: wscreate, wslist, ...)
for cmd in create list open delete; do
    printf '#!/bin/bash\nexec python3 "%s" %s "$@"\n' "$PYTHON_SCRIPT" "$cmd" > "$BIN_DIR/ws${cmd}"
done
```

**Critical pitfall:** `install.sh` MUST `rm -f` old wrappers before writing new
ones. If a previous version used symlinks (`ln -sf ws wscreate`), later writing
through the symlink with `>` or `printf >` overwrites the shared `ws` target
file, corrupting all aliases. Always `rm -f "$BIN_DIR/ws"*` first.

**Heredoc vs printf — non-issue (corrected):** An earlier version of this doc
claimed heredoc `<< EOF` silently expanded `${cmd}` to the wrong value inside
`for` loops. Testing proved this false — heredoc expands loop variables
correctly in bash 5.x. The real problem was always leftover symlinks from a
prior `install.sh` version. Both heredoc and printf work fine once symlinks
are removed. Use whichever you prefer; `printf` is slightly more compact for
one-liner wrappers.

## Version Naming Convention

- Tag: `v<major>.<minor>.<patch>` (e.g., v3.0.0)
- Tarball: `agent-workspace-manager-v<major>.<minor>.tar.gz` (single unified package)
- Upload to Gitea/GitHub release as attachment
