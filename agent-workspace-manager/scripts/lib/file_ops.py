"""Safe file and directory operations."""
import os
import shutil
import tempfile


def validate_directory(path):
    """Validate that path exists and is a directory."""
    norm = os.path.normpath(os.path.abspath(os.path.expanduser(path)))
    if not os.path.exists(norm):
        raise FileNotFoundError(f"Directory does not exist: {norm}")
    if not os.path.isdir(norm):
        raise NotADirectoryError(f"Path is not a directory: {norm}")
    return norm


def safe_copy_file(src, dst):
    """Copy a single file safely. Creates parent dirs."""
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    if not os.path.isfile(src):
        raise FileNotFoundError(f"Source file not found: {src}")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def safe_copy_dir(src, dst, ignore_patterns=None):
    """Copy directory tree from src to dst. Returns list of (src, dst) copied."""
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    if not os.path.isdir(src):
        raise FileNotFoundError(f"Source directory not found: {src}")
    os.makedirs(dst, exist_ok=True)
    copied_files = []

    for item in os.listdir(src):
        src_item = os.path.join(src, item)
        dst_item = os.path.join(dst, item)
        if ignore_patterns and item in ignore_patterns:
            continue
        if os.path.isdir(src_item):
            sub_copied = safe_copy_dir(src_item, dst_item, ignore_patterns)
            copied_files.extend(sub_copied)
        else:
            shutil.copy2(src_item, dst_item)
            copied_files.append((src_item, dst_item))
    return copied_files


def safe_delete(path):
    """Delete a file or directory safely. Returns True if something was deleted."""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return False
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)
    return True


def atomic_write_text(path, content):
    """Atomically write text to a file (temp + rename)."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_path = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def atomic_write_json(path, data, indent=2):
    """Atomically write JSON data to a file."""
    import json

    content = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
    atomic_write_text(path, content)


def read_json(path):
    """Read and parse a JSON file."""
    import json

    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
