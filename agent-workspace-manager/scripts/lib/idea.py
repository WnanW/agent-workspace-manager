"""IntelliJ IDEA integration module."""
import os
import sys
import subprocess
import shutil
import xml.etree.ElementTree as ET

from .config import IDEA_IGNORE_PATTERNS, WORKSPACE_XML_KEEP_COMPONENTS


class IdeaError(Exception):
    """Raised when IDEA operations fail."""
    pass


class IdeaModule:
    """Handles IntelliJ IDEA detection, launch, and config copying."""

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger

    def _get_idea_executable(self):
        """Get the IDEA executable path from config or auto-detect."""
        exe = self.config.get("ideaExecutable")
        if exe:
            return os.path.expanduser(exe)
        if sys.platform == "win32":
            paths = [
                os.path.expanduser("~/.local/share/JetBrains/Toolbox/apps/IDEA-U/bin/idea64.exe"),
                "C:/Program Files/JetBrains/IntelliJ IDEA/bin/idea64.exe",
            ]
        elif sys.platform == "darwin":
            paths = [
                "/Applications/IntelliJ IDEA.app/Contents/MacOS/idea",
                os.path.expanduser("~/Applications/IntelliJ IDEA.app/Contents/MacOS/idea"),
            ]
        else:
            paths = [
                os.path.expanduser("~/.local/share/JetBrains/Toolbox/apps/IDEA-U/bin/idea.sh"),
                "/opt/idea/bin/idea.sh",
                "/usr/local/bin/idea",
                "/snap/bin/intellij-idea-community",
                "/snap/bin/intellij-idea-ultimate",
            ]
        for p in paths:
            if os.path.isfile(p):
                return p
        return None

    def is_idea_available(self):
        """Check if IDEA is available."""
        return self._get_idea_executable() is not None

    def launch(self, project_path):
        """Launch IDEA with the given project. Does NOT wait for exit."""
        exe = self._get_idea_executable()
        if not exe:
            raise IdeaError(
                "IDEA executable not found.\n"
                "Please set 'ideaExecutable' in config/config.json.\n"
                "Common locations:\n"
                "  Linux:   ~/.local/share/JetBrains/Toolbox/apps/IDEA-U/bin/idea.sh\n"
                "           /opt/idea/bin/idea.sh\n"
                "           /snap/bin/intellij-idea-ultimate\n"
                "  macOS:   /Applications/IntelliJ IDEA.app/Contents/MacOS/idea\n"
                "  Windows: C:/Program Files/JetBrains/IntelliJ IDEA/bin/idea64.exe"
            )
        try:
            subprocess.Popen(
                [exe, os.path.abspath(project_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            if self.logger:
                self.logger.info(f"Launched IDEA for {project_path}")
            return exe
        except Exception as e:
            raise IdeaError(f"Failed to launch IDEA: {e}")

    def _is_ignored(self, name):
        """Check if a file/dir name matches the ignore blacklist."""
        return name in IDEA_IGNORE_PATTERNS

    def _extract_workspace_components(self, src_ws_xml):
        """
        Parse workspace.xml and extract only useful configuration components.
        Returns the XML string of a new workspace.xml containing only the
        kept components (MavenProjectsManager, MavenImportPreferences,
        RunManager, etc.), or None if the source file doesn't exist or
        has no useful components.
        """
        if not os.path.isfile(src_ws_xml):
            return None
        try:
            tree = ET.parse(src_ws_xml)
            root = tree.getroot()
        except ET.ParseError:
            return None

        # Keep only components in the whitelist.
        # Handle namespace: if IDEA added xmlns to the root element,
        # findall('component') won't match. Use local-name matching.
        kept = []
        for component in root:
            tag = component.tag
            # Strip namespace if present: {http://...}component -> component
            if '}' in tag:
                tag = tag.split('}', 1)[1]
            if tag == 'component':
                name = component.get('name', '')
                if name in WORKSPACE_XML_KEEP_COMPONENTS:
                    kept.append(component)

        if not kept:
            return None

        # Build a new workspace.xml with only the kept components
        new_root = ET.Element('project', attrib={'version': '4'})
        for comp in kept:
            new_root.append(comp)

        # Pretty-print
        try:
            ET.indent(new_root, space='  ')
        except AttributeError:
            pass  # Python < 3.9 fallback - no indent
        result = ET.tostring(new_root, encoding='unicode', xml_declaration=True)
        return result

    def _merge_workspace_xml(self, dst_ws_xml, extracted_xml):
        """
        Merge extracted workspace.xml components into destination workspace.xml.
        If dst doesn't exist, write the extracted content directly.
        If dst exists (git checked it out), replace/add kept components in-place.
        """
        if not extracted_xml:
            return False

        if not os.path.isfile(dst_ws_xml):
            # No existing workspace.xml in dest, just write the extracted one
            with open(dst_ws_xml, 'w', encoding='utf-8') as f:
                f.write(extracted_xml)
            return True

        # Destination exists (git checked it out) - merge
        try:
            dst_tree = ET.parse(dst_ws_xml)
            dst_root = dst_tree.getroot()
        except ET.ParseError:
            # Destination is corrupt, just overwrite with extracted
            with open(dst_ws_xml, 'w', encoding='utf-8') as f:
                f.write(extracted_xml)
            return True

        # Parse the extracted XML to get components to add
        try:
            src_tree = ET.fromstring(extracted_xml)
        except ET.ParseError:
            return False

        # Remove existing components with same names, then add extracted ones
        existing_components = {}
        for comp in list(dst_root):
            tag = comp.tag
            if '}' in tag:
                tag = tag.split('}', 1)[1]
            if tag == 'component':
                name = comp.get('name')
                if name:
                    existing_components[name] = comp
        for src_comp in list(src_tree):
            tag = src_comp.tag
            if '}' in tag:
                tag = tag.split('}', 1)[1]
            if tag == 'component':
                name = src_comp.get('name', '')
                if name in existing_components:
                    dst_root.remove(existing_components[name])
                dst_root.append(src_comp)

        try:
            ET.indent(dst_root, space='  ')
        except AttributeError:
            pass
        result = ET.tostring(dst_root, encoding='unicode', xml_declaration=True)
        with open(dst_ws_xml, 'w', encoding='utf-8') as f:
            f.write(result)
        return True

    def copy_configuration(self, src_project, dst_project):
        """
        Copy IDEA configuration from source project to destination project.

        Strategy: blacklist-based. Copies everything in .idea/ EXCEPT runtime
        state files (workspace.xml is specially handled - useful components are
        extracted from it, rest is discarded).
        Also copies root-level .iml files (module definitions with SDK/dependencies).

        This ensures: modules.xml, compiler.xml, encodings.xml, vcs.xml, misc.xml,
        codeStyles/, runConfigurations/, inspectionProfiles/, libraries/, *.iml
        are all carried over, so IDEA opens the workspace fully configured.

        For workspace.xml: extracts MavenProjectsManager (Maven project settings,
        linked pom files, profiles) and RunManager (run/debug configurations that
        were not saved as separate project files). These are the configurations
        users care about; the rest of workspace.xml is UI state (window positions,
        recent files, breakpoints) that should not be copied.

        Before copying, removes blacklisted files that git may have checked out
        into the workspace's .idea/.

        Returns list of (src, dst) files copied (for rollback).
        """
        copied_files = []

        # === 1. Copy .idea/ directory (blacklist strategy) ===
        src_idea = os.path.join(os.path.abspath(src_project), ".idea")
        dst_idea = os.path.join(os.path.abspath(dst_project), ".idea")

        if os.path.isdir(src_idea):
            os.makedirs(dst_idea, exist_ok=True)

            # First: remove blacklisted user-state files that git checked out
            for pattern in IDEA_IGNORE_PATTERNS:
                target = os.path.join(dst_idea, pattern)
                if os.path.exists(target):
                    try:
                        if os.path.isdir(target):
                            shutil.rmtree(target)
                        else:
                            os.remove(target)
                        if self.logger:
                            self.logger.info(f"Removed user-state: {pattern}")
                    except Exception as e:
                        if self.logger:
                            self.logger.warning(f"Could not remove {pattern}: {e}")

            # Copy everything not in blacklist
            for item in os.listdir(src_idea):
                if self._is_ignored(item):
                    continue
                src_path = os.path.join(src_idea, item)
                dst_path = os.path.join(dst_idea, item)
                try:
                    if os.path.isdir(src_path):
                        # Copy directory recursively
                        if os.path.exists(dst_path):
                            shutil.rmtree(dst_path)
                        shutil.copytree(src_path, dst_path)
                        # Track files for rollback
                        for root, _, files in os.walk(dst_path):
                            for f in files:
                                copied_files.append((os.path.join(root, f), os.path.join(root, f)))
                    elif os.path.isfile(src_path):
                        shutil.copy2(src_path, dst_path)
                        copied_files.append((src_path, dst_path))
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Could not copy {item}: {e}")

        # === 1b. Extract useful components from workspace.xml ===
        # workspace.xml is blacklisted from bulk copy, but it contains
        # MavenProjectsManager (Maven settings) and RunManager (run configs)
        # that users need. Extract only those, discard UI state.
        if os.path.isdir(src_idea):
            src_ws_xml = os.path.join(src_idea, "workspace.xml")
            dst_ws_xml = os.path.join(dst_idea, "workspace.xml")
            try:
                extracted = self._extract_workspace_components(src_ws_xml)
                if extracted:
                    merged = self._merge_workspace_xml(dst_ws_xml, extracted)
                    if merged:
                        copied_files.append((src_ws_xml, dst_ws_xml))
                        if self.logger:
                            self.logger.info(
                                f"Extracted workspace.xml components: "
                                f"{', '.join(WORKSPACE_XML_KEEP_COMPONENTS)}"
                            )
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Could not extract workspace.xml: {e}")

        # === 2. Copy root-level .iml files (module definitions) ===
        src_proj = os.path.abspath(src_project)
        dst_proj = os.path.abspath(dst_project)
        for item in os.listdir(src_proj):
            if item.endswith(".iml"):
                src_iml = os.path.join(src_proj, item)
                dst_iml = os.path.join(dst_proj, item)
                try:
                    shutil.copy2(src_iml, dst_iml)
                    copied_files.append((src_iml, dst_iml))
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Could not copy {item}: {e}")

        if self.logger:
            self.logger.info(f"Copied {len(copied_files)} IDEA config items to {dst_idea}")

        return copied_files
