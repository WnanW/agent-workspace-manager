# Git Worktree + IDEA Config: Implementation Pitfalls

Bugs found during build+test of the agent-workspace-manager skill.
Non-obvious interactions between git worktree behavior and IDEA configuration.

---

## Pitfall 1: Git Worktree Checks Out Committed `.idea/` Files

**Symptom:** After creating a workspace, `workspace.xml` and `caches/` appear in the
workspace's `.idea/` directory even though the IDEA copy module never copies them.

**Root cause:** Git worktree does a full checkout of the branch. If the source project
committed `.idea/workspace.xml`, `.idea/caches/`, etc. to git, the worktree checkout
brings them along. The IDEA config copy step overlays on top — it doesn't remove
what's already there.

**Fix (v2.1):** `copy_configuration()` in `idea.py` runs a cleanup pass FIRST, deleting
blacklisted entries (workspace.xml, tasks.xml, shelf/, caches/, local_history/) from
the destination `.idea/` before copying. The copy itself uses a blacklist strategy —
it copies everything that isn't in the blacklist.

**Key insight:** The copy step is not just "add" — it must also "clean" user-state
files that git checked out. This applies regardless of whitelist vs blacklist
strategy; the cleanup pass is always needed.

---

## Pitfall 5: Whitelist Too Narrow — Missing modules.xml, .iml, libraries/

**Symptom:** User reports that IDEA opens the workspace requiring full reconfiguration:
JDK, Maven plugins, run configurations all missing. Must re-import project.

**Root cause:** v1/v2.0 used a whitelist of .idea/ files to copy: only misc.xml, vcs.xml,
encodings.xml, codeStyles/, inspectionProfiles/, runConfigurations/. This missed:
- `modules.xml` — without it, IDEA doesn't know what modules exist
- `*.iml` (root level) — module SDK, dependency, and output path definitions
- `compiler.xml` — compiler settings
- `libraries/` — library references (Maven dependency declarations)

**Fix (v2.1):** Switched from whitelist to blacklist strategy. Copy everything in
`.idea/` and root `*.iml` files EXCEPT runtime state (workspace.xml, tasks.xml,
usage.local.xml, shelf/, caches/, local_history/, workspace/).

**Key insight:** When the goal is "copy so it works without reconfiguration," a
whitelist is the wrong tool — you will always miss something. A blacklist copies
the full configuration and only excludes what would break (path-specific state,
caches that need regeneration). This is the goal-oriented approach: copy
everything that helps, exclude only what hurts.

---

---

## Pitfall 2: Branch Already Checked Out In Another Worktree (v2)

**Symptom:** `create` (default branch master) fails with:
`fatal: 'master' 已经检出到 '/path/to/my-project'`

**Root cause:** Git forbids the same branch being checked out in two worktrees
simultaneously. When the user runs `create` with no argument, the default is
`master` — but `master` is already the current branch of the main worktree.
`git worktree add -b master <path> master` tries to create a branch that exists,
and `git worktree add <path> master` tries to check out a branch that's already
checked out. Both fail.

**Fix (v2):** `workspace.py create()` uses a three-way branch strategy:

1. Branch does NOT exist → `git worktree add -b <branch> <path>` (create new from HEAD)
2. Branch exists but is NOT the current branch → `git worktree add <path> <branch>` (checkout existing)
3. Branch exists AND IS the current branch → auto-suffix the branch name
   (`master-2`, `master-3`, ...) and create as new branch from HEAD

The third case is the one that trips up testing. It happens whenever `create` is
called with the default argument from the main worktree.

**Key insight:** There are THREE branch states to handle, not two. The v1 code
only handled "exists" vs "doesn't exist" and missed the "exists AND is current"
case. Always check `git.get_current_branch()` against the requested branch.

**Test reproduction:**
```bash
# In a repo where master is the current branch:
python3 workspace_manager.py create
# Expected: workspace created with branch "master-2" (auto-suffixed)
```

---

## Pitfall 3: `delete` Without Force Always Fails on Skill-Created Workspaces

**Symptom:** `delete --name feature-login` fails with "contains modified or untracked
files, use --force to delete".

**Root cause:** The IDEA config copy step writes files (misc.xml, vcs.xml, codeStyles/,
runConfigurations/) into the workspace that are NOT tracked by git. Git worktree
remove refuses to delete a worktree with untracked files unless `--force` is used.

**Fix:** `delete()` in `workspace.py` always uses `force=True`. This is safe because
the untracked files are skill-generated IDEA config, not user code.

If git's force remove still fails, the code falls back to manual directory deletion
+ `git worktree prune`.

**Key insight:** Because the skill intentionally adds untracked files (IDEA config) to
every workspace, force delete is always needed. This is why there's no --force flag
on the CLI — it's the default and only behavior.

**v2 change:** The `--force` CLI flag was removed entirely. Force is always on.
This aligns with the design principle of minimal CLI surface.

---

## Pitfall 4: `git init -b main` Not Supported on Older Git

**Symptom:** `git init -b main` fails with `error: unknown switch 'b'` on older git
versions (e.g., git 2.25 on Ubuntu 20.04).

**Fix:** Use `git init` followed by `git symbolic-ref HEAD refs/heads/main`.

**Note:** This affects test setup, not the skill itself. The skill uses whatever
branch the repo already has.

---

## Rollback Implementation Detail

The `_rollback()` method in `workspace.py` uses a step list with variable-length tuples:
- `("worktree", ws_path, branch, project_root)` — 4 elements
- `("idea_config", ws_path, copied_files)` — 3 elements
- `("registry", ws_id)` — 2 elements (actually stored as 3 with None padding)

The method unpacks with `*step_args` to handle the variable arity. Each step type
has its own unpacking logic.

**v2 note:** The worktree rollback step now stores `actual_branch` (the possibly
auto-suffixed branch name) instead of the user-requested branch. This ensures
rollback removes the correct branch/worktree even when the name was auto-suffixed.

---

## Pitfall 6: Over-Engineered CLI — Too Many Commands and Flags

**Symptom:** User pushes back hard on the v1 design: "首先不需要这么复杂" (first of
all, this doesn't need to be so complex), "close直接删掉吧" (just delete close
entirely), "doctor完全不需要" (doctor is completely unnecessary).

**Root cause:** v1 had 8 subcommands (create, list, open, close, delete, status,
doctor, cleanup, config) with many flags (--name, --project, --branch, --new-branch,
--no-idea-config, --force, --dry-run, --fix). The design followed "complete API"
thinking rather than "minimal sufficient" thinking.

**Fix (v2):** Reduced to 4 commands. Decisions:
- `close` → deleted. It only flipped a status field, no resource release.
- `status` + `doctor` → deleted. Diagnostics without a fix action add no value.
- `cleanup` → deleted. Registry self-heals on access.
- `config` → deleted. Default config is sufficient for all known use cases.
- `create` → one positional arg (branch name, default master), no --project-root.
- `delete` → no --force flag, force is always on (untracked IDEA config expected).
- `--project` → kept on open/delete/list but defaults to cwd-derived project name.

**Key insight:** The user's design philosophy is minimal sufficient: "减少手动配置，
这就是目标" (reducing manual config, that's the goal). Every command and flag must
earn its place by serving the core goal. If a command doesn't directly contribute
to "create workspace that works → use it → clean it up," it's noise. When in doubt,
cut it. This is also documented in the Design Principles section of SKILL.md.

**Trigger pattern:** If you find yourself adding a `doctor`, `status`, `cleanup`, or
`config` subcommand "just in case," stop and ask whether the core commands already
handle that case implicitly.

---

## Pitfall 7: install.sh Symlink → File Overwrite Corruption

**Symptom:** After running a new `install.sh`, all alias wrappers (`wscreate`,
`wslist`, `wsopen`, `wsdelete`) contain `delete` — the last value of the loop
variable — regardless of what the script assigns.

**Root cause:** A previous version of `install.sh` created aliases as symlinks
(`ln -sf "$BIN_DIR/ws" "$BIN_DIR/wscreate"`). When the new `install.sh` (which
writes real files via `printf > "$BIN_DIR/ws${cmd}"`) runs, the OS follows the
existing symlink and writes to the `ws` target file. All four aliases point to
`ws`, so all four writes go to the same file. The last write wins — `delete`.

**Fix:** `install.sh` must `rm -f` all existing wrappers (including symlinks)
BEFORE writing new ones:
```bash
rm -f "$BIN_DIR/ws" "$BIN_DIR/wscreate" "$BIN_DIR/wslist" "$BIN_DIR/wsopen" "$BIN_DIR/wsdelete"
```

**Debugging trap:** `os.path.islink()` in Python returns `False` for the wrapper
path because the symlink target (`ws`) exists and resolves — it looks like a
regular file. `stat -c %F` reveals the truth (`符号链接` / `symbolic link`). Always
check with `ls -la` or `stat` before assuming a file is a regular file.

**Key insight:** When migrating from symlink-based to file-based wrapper generation,
the old symlinks must be explicitly removed. `>` redirection follows symlinks, so
writing through a symlink modifies the target, not the link itself.

**Heredoc note (corrected):** An earlier version of this pitfall claimed heredoc
`<< EOF` was the cause and `printf` was the fix. That was a misdiagnosis. Isolated
testing confirmed heredoc expands `${cmd}` correctly inside `for` loops in bash 5.x.
The real fix was `rm -f` — both heredoc and printf fail identically when symlinks
are present, and both work once symlinks are removed.

---

## Pitfall 11: XML Namespace Breaks ElementTree findall()

**Symptom:** `_extract_workspace_components()` returns `None` even though
workspace.xml contains `MavenProjectsManager` and `RunManager` components.

**Root cause:** Some IDEA versions add an `xmlns` attribute to the `<project>`
root element in workspace.xml:

```xml
<project version="4" xmlns="http://www.netbeans.org/ns/project/1">
```

Python's `xml.etree.ElementTree` treats all child elements as namespaced.
`root.findall('component')` returns an empty list because the actual tag
becomes `{http://www.netbeans.org/ns/project/1}component` instead of `component`.

**Fix:** Replace all `findall('component')` calls with explicit iteration that
strips namespace prefixes:

```python
for component in root:
    tag = component.tag
    if '}' in tag:
        tag = tag.split('}', 1)[1]
    if tag == 'component':
        name = component.get('name', '')
        ...
```

This applies to both `_extract_workspace_components()` and `_merge_workspace_xml()`.

**Key insight:** Never use `findall('component')` on IDEA XML files -- IDEA
may or may not include xmlns depending on version and project format. Always
strip namespace prefixes when matching tag names. The `name` attribute is
never namespaced, so it can be matched directly.

---

## Pitfall 12: create Does Not Attempt IDEA Launch -- User Never Discovers Missing Executable

**Symptom:** User runs `wscreate`, workspace is created successfully, but IDEA
does not open. No error message is shown. The user (or agent) doesn't know
that the IDEA executable wasn't found, because `launchIdeaAfterCreate` defaults
to `False` and `create` never calls `launch()`.

**Root cause:** The original design had `launchIdeaAfterCreate` defaulting to
`False` in config. The `create()` method only launches IDEA if this config
flag is `True`. Since it defaults to `False`, `create` silently completes
without ever trying to find or launch IDEA. The user only discovers the
missing executable when they manually run `wsopen`.

This is especially bad for agent-driven workflows: the agent calls `wscreate`,
gets success (exit 0), and moves on. It never sees the IDEA-not-found error
because the error was never triggered.

**Fix:** `cmd_create()` in `workspace_manager.py` now passes `launch_idea=True`
to `manager.create()`. This forces a launch attempt immediately after workspace
creation. If IDEA is not found, `IdeaError` is caught and the error message
(config file path, common locations, retry command) is printed to stderr --
but the workspace is still created successfully (exit 0).

**Key insight:** When a tool has a "launch/open" step that depends on external
configuration (executable path), that step should be attempted eagerly during
creation, not deferred to a separate command. This surfaces configuration
problems immediately rather than letting them lurk until the user tries to
open the workspace manually. For agent-driven workflows, this is critical --
the agent needs to see the error in the same command output, not in a
follow-up command it might never run.

---

## Pitfall 13: Wrong Component Name for Maven Settings -- MavenImportPreferences vs MavenProjectsManager

**Symptom:** After workspace copy, Maven project settings are lost. Maven home
path, settings.xml path, import options (auto-download sources/docs), and profile
selections all reset to defaults. The user must reconfigure Maven from scratch.

**Root cause:** `WORKSPACE_XML_KEEP_COMPONENTS` only had `MavenProjectsManager`.
But `MavenProjectsManager`'s `@State` annotation stores ONLY the project tree
(linked pom.xml files, resolved dependency list, ignored files). The actual Maven
configuration (Maven home, settings.xml, import options, profiles) is stored by
a DIFFERENT class: `MavenWorkspaceSettingsComponent`, which has:

```java
@State(name = "MavenImportPreferences",
       storages = @Storage(StoragePathMacros.WORKSPACE_FILE))
```

So the component name in workspace.xml is `MavenImportPreferences`, not
`MavenProjectsManager`. Both are in workspace.xml, but they store different
data:

- `MavenProjectsManager` -- project tree (what pom files are linked)
- `MavenImportPreferences` -- workspace settings (how Maven is configured)

**How found:** Traced through IntelliJ Community source code on GitHub:
- `MavenProjectsManager.java` has `@State(name = "MavenProjectsManager")` with
  NO `@Storage` -- default storage is workspace.xml
- `MavenWorkspaceSettingsComponent.java` has
  `@State(name = "MavenImportPreferences", storages = @Storage(StoragePathMacros.WORKSPACE_FILE))`
- `MavenProjectsManager.getWorkspaceSettings()` delegates to
  `MavenWorkspaceSettingsComponent.getInstance(project).getSettings()`

**Fix:** Added `MavenImportPreferences` to `WORKSPACE_XML_KEEP_COMPONENTS` in
`config.py`. Now the extraction picks up both components.

**Key insight:** IDEA component names do NOT always match class names.
`MavenProjectsManager` class -> component name `MavenProjectsManager` (matches).
`MavenWorkspaceSettingsComponent` class -> component name `MavenImportPreferences`
(does NOT match). Always check the `@State(name = ...)` annotation in the
IntelliJ source, not the class name. When investigating which IDEA component
stores a particular setting, search the IntelliJ Community repo on GitHub for
`@State` annotations in the relevant plugin directory.

**Search path:** `plugins/maven/src/main/java/org/jetbrains/idea/maven/` in
`JetBrains/intellij-community` repository.

---

## Pitfall 14: mavenHome Not Persisted -- IDEA Intentionally Discards It

**Symptom:** After workspace copy, `MavenImportPreferences` IS present in the
destination workspace.xml, and `userSettingsFile` (settings.xml path) came over
correctly. But the Maven home path (`mavenHome`) did not -- it shows "Bundled
Maven 3" or is empty in the destination project.

**Root cause:** IDEA's `MavenGeneralSettings.java` has a deprecated `getMavenHome()`
method that is gated by a `myForPersistence` flag:

```java
@Deprecated(forRemoval = true)
public @Nullable String getMavenHome() {
    if (myForPersistence) {
        return DEFAULT_MAVEN.getTitle(); // "Bundled Maven 3"
    }
    return mavenHomeType.getTitle();
}
```

When IDEA serializes `MavenGeneralSettings` to workspace.xml, it calls
`cloneForPersistence()` which sets `myForPersistence = true`. This causes
`getMavenHome()` to ALWAYS return "Bundled Maven 3" regardless of the actual
Maven home configuration. The deprecated field is intentionally not saved.

The ACTUAL Maven home type is persisted via two separate fields:
- `mavenHomeTypeForPersistence` (enum: `WRAPPER`, `BUNDLED3`, `BUNDLED4`, `CUSTOM`)
- `customMavenHome` (String, only set when type is `CUSTOM`)

Both are serialized to workspace.xml under the `MavenImportPreferences` component.
Our extraction copies the entire component, so both fields SHOULD come over.

**How to verify:** Open the SOURCE project's workspace.xml and search for
`customMavenHome`. If it's present with a path value, the extraction will carry
it over. If it's absent, the user is using Bundled Maven or Maven Wrapper, and
there is no custom path to carry -- IDEA uses the bundled Maven automatically.

**Key insight:** IDEA's serialization is not always a faithful snapshot of all
fields. Deprecated fields may be intentionally stubbed during persistence.
When a setting appears "missing" after copy, first check whether IDEA actually
writes it to the source workspace.xml at all -- the issue may be in IDEA's
serialization, not in the extraction logic.

**Source files (IntelliJ Community):**
- `MavenGeneralSettings.java` -- `getMavenHome()` with `myForPersistence` guard,
  `getMavenHomeTypeForPersistence()`, `getCustomMavenHome()`
- `MavenWorkspacePersistedSettings.java` -- `cloneForPersistence()` sets
  `myForPersistence = true`
- CDN mirror: `https://cdn.jsdelivr.net/gh/JetBrains/intellij-community@master/`
  (use when raw.githubusercontent.com is rate-limited)

---

## Pitfall 9: workspace.xml Blacklist Too Aggressive - Maven & Run Configs Lost

**Symptom:** After creating a workspace, Maven project settings (linked pom files,
profiles, ignored files) and run/debug configurations (not saved as project files)
are missing. User must re-import Maven projects and recreate run configs.

**Root cause:** `workspace.xml` was in the `IDEA_IGNORE_PATTERNS` blacklist,
which caused the ENTIRE file to be skipped during copy. But `workspace.xml` is a
mixed file - it contains both:

1. **Useful project configuration** (should be copied):
   - `MavenProjectsManager` - Maven project settings: linked pom files, profiles,
     ignored files patterns, import options
   - `RunManager` - run/debug configurations that were NOT saved as separate
     project files (i.e., user didn't check "Store as project file")

2. **Runtime UI state** (should NOT be copied):
   - `FileEditorManager` - currently open files, cursor positions
   - `ToolWindowManager` - window layout, docked/floating state
   - `DebuggerManager` - breakpoints
   - `RecentProjectsManager` - recent file list
   - `UsageViewManager` - usage search history

The old code treated it as pure runtime state and excluded it entirely.

**Fix:** Added `WORKSPACE_XML_KEEP_COMPONENTS` whitelist in `config.py`.
`copy_configuration()` now has a special step after the blacklist copy:
1. Parse source `workspace.xml` with ElementTree
2. Extract only components whose `name` attribute is in the keep list
3. Write/merge them into the destination `workspace.xml`

If the destination already has a `workspace.xml` (checked out by git), the
extracted components replace existing ones with the same name - other
components in the destination are left untouched (they'll be regenerated by
IDEA on first open anyway).

**Key insight:** `workspace.xml` is not purely "user state" - it's a mixed
file. The blacklist strategy works for files/dirs that are purely runtime
(caches, local_history, shelf). For mixed files, you need component-level
extraction. The `$PROJECT_DIR$` macro used inside these components resolves
automatically to the new workspace path, so no path fixing is needed.

**What about `RunManager` entries saved as project files?**
If the user checked "Store as project file", the run config is in
`.idea/runConfigurations/*.xml` - these are already copied by the blacklist
strategy (they're not in the blacklist). The `RunManager` component in
`workspace.xml` contains only the NON-shared run configs. Both paths are
now covered.

---

## Pitfall 10: Silent IDEA Launch Failure - No Guidance to User

**Symptom:** User creates a workspace or runs `wsopen`, but IDEA never opens.
No error message, no indication of what went wrong. The workspace appears to
work but nothing happens visually.

**Root cause:** The old `launch()` method in `idea.py` returned `None` silently
when the IDEA executable wasn't found. It only logged a warning to the log file.
The CLI layer didn't check the return value, so the user saw "OK: Workspace
opened" even though IDEA never launched.

On headless Linux servers or minimal installations, IDEA is often not in the
standard search paths (Toolbox, /opt, /snap). Auto-detection fails silently.

**Fix:** Two changes:
1. `launch()` now raises `IdeaError` (not returns None) when IDEA is not found.
   The error message includes common locations for all three platforms.
2. CLI `cmd_create` and `cmd_open` catch `IdeaError` separately:
   - `cmd_create`: prints "OK: Workspace created (but IDEA could not open)",
     shows the error with common locations, prints the config file path,
     and tells the user to run `wsopen` after fixing. Returns 0 (workspace
     IS created, only launch failed).
   - `cmd_open`: prints the error, config file path, and retry command.
     Returns 1.

The config file path is resolved via `get_config_path()` which respects
`--config` flag or defaults to `config/config.json` in the skill directory.

**Key insight:** A silent failure is worse than a loud one. When an optional
step (launch IDEA) fails, the user needs to know:
1. What failed (IDEA not found)
2. How to fix it (set ideaExecutable in config)
3. Where the config file is (absolute path)
4. What to do after fixing (retry command)

The workspace creation itself is NOT rolled back -- it succeeded, only the
IDEA launch failed. The user can fix the config and run `wsopen` to open
the already-created workspace.

---

## Pitfall 8: ws Command Dispatch - Why Direct Aliases Beat Subcommand Parsing

**Symptom:** LLM agents calling the skill sometimes struggle to correctly invoke
`python3 scripts/workspace_manager.py create feature-login` - the long Python
path is easy to get wrong, and relative paths fail on OpenCode (agent cwd is
project, not skill dir).

**Root cause:** The skill's command surface was Python-script-centric. Every
caller had to know the full script path and pass subcommands as arguments.

**Fix (v3.0):** `install.sh` installs short wrapper commands (`wscreate`,
`wslist`, `wsopen`, `wsdelete`) to `~/.local/bin/`. These sit between natural
language and registered commands — the LLM calls `wscreate feature-login` directly,
no path construction needed. Also supports subcommand form (`ws create`) for
discoverability.

**Key insight:** Short command names that hardcode the Python path at install
time solve both the path-resolution problem (OpenCode) and the LLM-dispatch
problem (no long paths to hallucinate). The user called this "介于自然语言和
命令注册之后的效果" — the sweet spot between NL and registered commands.
