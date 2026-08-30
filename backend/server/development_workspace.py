"""Isolated, review-before-apply workspaces for autonomous development runs.

This is deliberately a constrained workspace boundary, not a container sandbox.
All subprocesses use argv arrays with ``shell=False`` and all model-authored paths
are resolved below the server-owned workspace root.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import config

WORKSPACES_ROOT = config.DATA_DIR / "dev_workspaces"
PROJECTS_ROOT = config.DATA_DIR / "dev_projects"
IGNORED_NAMES = {
    ".git", ".venv", "venv", "node_modules", "dist", "build", ".cache",
    ".pytest_cache", "__pycache__", ".mypy_cache", ".next", "coverage",
}
SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", "credentials.json", "secrets.json",
    "id_rsa", "id_ed25519",
}
MAX_FILE_BYTES = 1024 * 1024
MAX_WRITTEN_FILES = 100


class WorkspaceError(ValueError):
    pass


def _slug(value: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value)
    return clean[:80] or "default"


def _run(argv: List[str], *, cwd: Optional[Path] = None, timeout: int = 120,
         check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv, cwd=str(cwd) if cwd else None, shell=False, text=True,
            encoding="utf-8", errors="replace", capture_output=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkspaceError(str(exc)) from exc
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout or "command failed").strip()
        raise WorkspaceError(message[:4000])
    return result


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(repo), *args], check=check)


def _canonical_source(local_path: str) -> Path:
    path = Path(local_path).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise WorkspaceError("项目路径必须是存在的目录")
    return path


def _is_git(path: Path) -> bool:
    return _git(path, "rev-parse", "--is-inside-work-tree", check=False).returncode == 0


def _git_root(path: Path) -> Path:
    value = _git(path, "rev-parse", "--show-toplevel").stdout.strip()
    return Path(value).resolve(strict=True)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _skip_relative(relative: Path, extra_ignored: Optional[Iterable[str]] = None) -> bool:
    if any(part in IGNORED_NAMES for part in relative.parts):
        return True
    name = relative.name.lower()
    if name in SENSITIVE_NAMES or (name.startswith(".env") and name != ".env.example") \
            or name.endswith((".pem", ".key", ".p12", ".pfx")):
        return True
    normalized = relative.as_posix()
    return any(normalized == item.rstrip("/") or normalized.startswith(item.rstrip("/") + "/")
               for item in (extra_ignored or []))


def _manifest(root: Path, extra_ignored: Optional[Iterable[str]] = None) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if _skip_relative(relative, extra_ignored):
            continue
        result[relative.as_posix()] = _hash_file(path)
    return result


def _copy_source(source: Path, target: Path, extra_ignored: Optional[Iterable[str]] = None) -> None:
    def ignore(directory: str, names: List[str]) -> set[str]:
        parent = Path(directory)
        ignored = set()
        for name in names:
            entry = parent / name
            if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
                ignored.add(name)
                continue
            try:
                rel = (parent / name).relative_to(source)
            except ValueError:
                continue
            if _skip_relative(rel, extra_ignored):
                ignored.add(name)
        return ignored
    shutil.copytree(source, target, ignore=ignore, symlinks=False)


def detect_commands(root: Path) -> Dict[str, Any]:
    commands: List[List[str]] = []
    runtime: List[str] = []
    package_manager: Optional[str] = None
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists() \
            or any(root.glob("test*.py")) or (root / "tests").exists():
        runtime.append("python")
        has_pytest = (root / "pytest.ini").exists() or (root / "conftest.py").exists()
        if (root / "pyproject.toml").exists():
            try:
                has_pytest = has_pytest or "pytest" in (root / "pyproject.toml").read_text(
                    encoding="utf-8", errors="ignore")
            except OSError:
                pass
        commands.append([sys.executable, "-m", "pytest"] if has_pytest
                        else ([sys.executable, "-m", "unittest", "discover", "-s", "tests"]
                              if (root / "tests").exists()
                              else [sys.executable, "-m", "unittest", "discover"]))
    package_file = root / "package.json"
    if package_file.exists():
        runtime.append("node")
        if (root / "pnpm-lock.yaml").exists():
            package_manager = "pnpm"
        elif (root / "yarn.lock").exists():
            package_manager = "yarn"
        else:
            package_manager = "npm"
        try:
            scripts = json.loads(package_file.read_text(encoding="utf-8")).get("scripts", {})
        except (OSError, json.JSONDecodeError):
            scripts = {}
        if "test" in scripts and "no test specified" not in str(scripts["test"]):
            commands.append([package_manager, "run", "test"])
        if "build" in scripts:
            commands.append([package_manager, "run", "build"])
        elif "typecheck" in scripts:
            commands.append([package_manager, "run", "typecheck"])
    return {"runtime": runtime, "packageManager": package_manager, "commands": commands}


def validate_project(project: Dict[str, Any]) -> Dict[str, Any]:
    local_path = (project.get("localPath") or "").strip()
    if not local_path:
        return {
            "kind": "managed", "path": None, "repoClean": True,
            "currentRevision": None, "runtime": [], "packageManager": None,
            "commands": [], "warnings": ["首次运行时将创建受管理的 Git 项目"],
        }
    source = _canonical_source(local_path)
    detected = detect_commands(source)
    if _is_git(source):
        root = _git_root(source)
        clean = not bool(_git(root, "status", "--porcelain").stdout.strip())
        revision = _git(root, "rev-parse", "HEAD").stdout.strip()
        return {"kind": "git", "path": str(root), "repoClean": clean,
                "currentRevision": revision, "warnings": ([] if clean else ["Git 工作区存在未提交改动"]),
                **detected}
    return {"kind": "directory", "path": str(source), "repoClean": True,
            "currentRevision": None, "warnings": [], **detected}


def prepare_workspace(project: Dict[str, Any], space_id: str, run_id: str) -> Dict[str, Any]:
    run_root = WORKSPACES_ROOT / _slug(space_id) / _slug(run_id)
    workspace = run_root / "repo"
    metadata_path = run_root / "workspace.json"
    if metadata_path.exists():
        try:
            recovered = json.loads(metadata_path.read_text(encoding="utf-8"))
            if Path(recovered["workspacePath"]).resolve() == workspace.resolve() and workspace.exists():
                return recovered
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            pass
    run_root.mkdir(parents=True, exist_ok=True)
    validation = validate_project(project)
    extra_ignored = (project.get("developmentConfig") or {}).get("ignorePaths") or []
    kind = validation["kind"]
    if kind == "managed":
        source = PROJECTS_ROOT / _slug(space_id) / _slug(project["id"]) / "repo"
        source.mkdir(parents=True, exist_ok=True)
        if not _is_git(source):
            _git(source, "init")
            _git(source, "config", "user.email", "agent@ai-research-os.local")
            _git(source, "config", "user.name", "AI Research OS")
            (source / "README.md").write_text(f"# {project['name']}\n", encoding="utf-8")
            _git(source, "add", "README.md")
            _git(source, "commit", "-m", "Initialize managed project")
        kind = "git"
    else:
        source = Path(validation["path"])
    if kind == "git":
        source = _git_root(source)
        if _git(source, "status", "--porcelain").stdout.strip():
            raise WorkspaceError("Git 项目存在未提交改动，请先提交或暂存后再运行")
        base = _git(source, "rev-parse", "HEAD").stdout.strip()
        branch = f"ai-research-os/{_slug(project['id'])}/{run_id[:8]}"
        if workspace.exists():
            _git(source, "worktree", "remove", "--force", str(workspace), check=False)
            if workspace.exists():
                shutil.rmtree(workspace)
            _git(source, "worktree", "prune", check=False)
            _git(source, "branch", "-D", branch, check=False)
        _git(source, "worktree", "add", "-b", branch, str(workspace), base)
        _git(workspace, "config", "user.email", "agent@ai-research-os.local")
        _git(workspace, "config", "user.name", "AI Research OS")
        snapshot = {"kind": "git", "sourcePath": str(source), "workspacePath": str(workspace),
                    "baseRevision": base, "branchName": branch, "baseManifest": None,
                    "ignorePaths": extra_ignored, **detect_commands(workspace)}
        metadata_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        return snapshot
    if workspace.exists():
        shutil.rmtree(workspace)
    base_manifest = _manifest(source, extra_ignored)
    _copy_source(source, workspace, extra_ignored)
    snapshot = {"kind": "directory", "sourcePath": str(source), "workspacePath": str(workspace),
                "baseRevision": hashlib.sha256(json.dumps(base_manifest, sort_keys=True).encode()).hexdigest(),
                "branchName": None, "baseManifest": base_manifest, "ignorePaths": extra_ignored,
                **detect_commands(workspace)}
    metadata_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    return snapshot


def safe_path(workspace: Path, relative_path: str, *, allow_missing: bool = True) -> Path:
    candidate_rel = Path(relative_path.replace("\\", "/"))
    if candidate_rel.is_absolute() or ".." in candidate_rel.parts or _skip_relative(candidate_rel):
        raise WorkspaceError(f"不允许访问路径: {relative_path}")
    candidate = (workspace / candidate_rel).resolve(strict=False)
    root = workspace.resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError(f"路径越出研发工作区: {relative_path}") from exc
    parent = candidate.parent
    while parent != root and parent.exists():
        if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
            raise WorkspaceError(f"符号链接路径不允许写入: {relative_path}")
        parent = parent.parent
    if not allow_missing and not candidate.exists():
        raise WorkspaceError(f"文件不存在: {relative_path}")
    return candidate


def write_files(snapshot: Dict[str, Any], files: Iterable[Dict[str, Any]]) -> List[str]:
    root = Path(snapshot["workspacePath"])
    values = list(files)
    if len(values) > MAX_WRITTEN_FILES:
        raise WorkspaceError("单轮写入文件过多")
    written: List[str] = []
    for item in values:
        relative = str(item.get("path") or "").strip()
        content = item.get("content")
        deleting = item.get("delete") is True
        if not relative or (not deleting and not isinstance(content, str)):
            raise WorkspaceError("文件修改必须包含 path，以及文本 content 或 delete=true")
        normalized = Path(relative.replace("\\", "/")).as_posix()
        if any(normalized == value.rstrip("/") or normalized.startswith(value.rstrip("/") + "/")
               for value in (snapshot.get("ignorePaths") or [])):
            raise WorkspaceError(f"路径已被项目配置排除: {relative}")
        target = safe_path(root, relative)
        if deleting:
            if target.exists() and target.is_file():
                target.unlink()
            written.append(Path(relative).as_posix())
            continue
        raw = content.encode("utf-8")
        if len(raw) > MAX_FILE_BYTES:
            raise WorkspaceError(f"文件超过 1 MB: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".agent-tmp")
        temporary.write_bytes(raw)
        os.replace(temporary, target)
        written.append(Path(relative).as_posix())
    return written


def commit_iteration(snapshot: Dict[str, Any], iteration: int) -> Optional[str]:
    if snapshot["kind"] != "git":
        return None
    root = Path(snapshot["workspacePath"])
    _git(root, "add", "--all")
    if not _git(root, "diff", "--cached", "--quiet", check=False).returncode:
        return _git(root, "rev-parse", "HEAD").stdout.strip()
    _git(root, "commit", "-m", f"Agent development iteration {iteration}")
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def workspace_diff(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    root = Path(snapshot["workspacePath"])
    if snapshot["kind"] == "git":
        text = _git(root, "diff", "--binary", snapshot["baseRevision"], "HEAD").stdout
        names = _git(root, "diff", "--name-only", snapshot["baseRevision"], "HEAD").stdout.splitlines()
    else:
        base = snapshot.get("baseManifest") or {}
        current = _manifest(root, snapshot.get("ignorePaths") or [])
        names = sorted(set(base) | set(current))
        names = [name for name in names if base.get(name) != current.get(name)]
        chunks: List[str] = []
        source = Path(snapshot["sourcePath"])
        for name in names:
            before_path, after_path = source / name, root / name
            before = before_path.read_text(encoding="utf-8", errors="replace").splitlines(True) if before_path.exists() else []
            after = after_path.read_text(encoding="utf-8", errors="replace").splitlines(True) if after_path.exists() else []
            chunks.extend(difflib.unified_diff(before, after, f"a/{name}", f"b/{name}"))
        text = "".join(chunks)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"files": names, "patch": text[:1024 * 1024], "diffDigest": digest,
            "baseRevision": snapshot["baseRevision"]}


def apply_workspace(snapshot: Dict[str, Any], expected_base: str, expected_digest: str) -> Dict[str, Any]:
    current_diff = workspace_diff(snapshot)
    if expected_base != snapshot["baseRevision"] or expected_digest != current_diff["diffDigest"]:
        raise WorkspaceError("差异已过期，请重新审阅后再应用")
    source, workspace = Path(snapshot["sourcePath"]), Path(snapshot["workspacePath"])
    if snapshot["kind"] == "git":
        if _git(source, "status", "--porcelain").stdout.strip():
            raise WorkspaceError("原项目出现未提交改动，已拒绝应用")
        if _git(source, "rev-parse", "HEAD").stdout.strip() != snapshot["baseRevision"]:
            raise WorkspaceError("原项目 revision 已变化，已拒绝应用")
        head = _git(workspace, "rev-parse", "HEAD").stdout.strip()
        if head == snapshot["baseRevision"]:
            return {"applied": True, "revision": head, "files": []}
        result = _git(source, "cherry-pick", f"{snapshot['baseRevision']}..{head}", check=False)
        if result.returncode != 0:
            _git(source, "cherry-pick", "--abort", check=False)
            raise WorkspaceError("应用发生 Git 冲突，原项目已回滚")
        return {"applied": True, "revision": _git(source, "rev-parse", "HEAD").stdout.strip(),
                "files": current_diff["files"]}
    base = snapshot.get("baseManifest") or {}
    for name in current_diff["files"]:
        source_file = source / name
        actual = _hash_file(source_file) if source_file.exists() else None
        if actual != base.get(name):
            raise WorkspaceError(f"原项目文件已变化，拒绝应用: {name}")
    backup = Path(snapshot["workspacePath"]).parent / "apply-backup"
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir(parents=True)
    applied: List[str] = []
    try:
        for name in current_diff["files"]:
            source_file, workspace_file = source / name, workspace / name
            if source_file.exists():
                backup_file = backup / name
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, backup_file)
            if workspace_file.exists():
                source_file.parent.mkdir(parents=True, exist_ok=True)
                staged = source_file.with_name(source_file.name + ".agent-apply")
                shutil.copy2(workspace_file, staged)
                os.replace(staged, source_file)
            elif source_file.exists():
                source_file.unlink()
            applied.append(name)
    except Exception:
        for name in reversed(applied):
            source_file, backup_file = source / name, backup / name
            if backup_file.exists():
                source_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, source_file)
            elif source_file.exists():
                source_file.unlink()
        raise
    return {"applied": True, "revision": current_diff["diffDigest"], "files": applied}


__all__ = [
    "WorkspaceError", "apply_workspace", "commit_iteration", "detect_commands",
    "prepare_workspace", "safe_path", "validate_project", "workspace_diff", "write_files",
]
