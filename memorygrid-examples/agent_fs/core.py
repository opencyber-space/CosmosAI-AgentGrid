from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .exceptions import (
    AgentFSError,
    BranchError,
    CommitError,
    FileNotFoundError,
    MergeConflictError,
    RefNotFoundError,
)


@dataclass
class CommitInfo:
    hash: str
    short_hash: str
    author: str
    email: str
    date: str
    message: str
    files_changed: list[str] = field(default_factory=list)


@dataclass
class StatusEntry:
    path: str
    staged: str    # X in "XY" of `git status --porcelain`
    unstaged: str  # Y in "XY"


class AgentFS:
    """Version-controlled file system backed by a git repository.

    Root of the file system is ``path / subject_id``.  All file paths passed
    to the public API are relative to that root.
    """

    def __init__(self, path: str | Path, subject_id: str, *, author_name: str = "AgentFS", author_email: str = "agentfs@local") -> None:
        self.root = Path(path) / subject_id
        self.author_name = author_name
        self.author_email = author_email
        self._init_repo()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_repo(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if not (self.root / ".git").exists():
            self._git("init")
            self._git("config", "user.name", self.author_name)
            self._git("config", "user.email", self.author_email)
            # Create an initial empty commit so HEAD is valid from the start
            self._git("commit", "--allow-empty", "-m", "init: initialise repository")

    def _git(self, *args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            env=env,
            capture_output=capture,
            text=True,
        )
        if check and result.returncode != 0:
            raise AgentFSError(result.stderr.strip() or result.stdout.strip())
        return result

    def _abs(self, file_path: str) -> Path:
        p = (self.root / file_path).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise AgentFSError(f"Path '{file_path}' escapes the repository root")
        return p

    def _rel(self, abs_path: Path) -> str:
        return str(abs_path.relative_to(self.root))

    def _auto_commit(self, file_paths: list[str], message: str) -> str:
        for fp in file_paths:
            self._git("add", "--", fp)
        result = self._git("commit", "-m", message, check=False)
        if result.returncode != 0:
            if "nothing to commit" in result.stdout + result.stderr:
                return self.head()
            raise CommitError(result.stderr.strip())
        return self.head()

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def read(self, file_path: str) -> str:
        """Return the text content of *file_path* (UTF-8)."""
        abs_path = self._abs(file_path)
        if not abs_path.exists():
            raise FileNotFoundError(f"'{file_path}' does not exist")
        return abs_path.read_text(encoding="utf-8")

    def read_bytes(self, file_path: str) -> bytes:
        """Return the raw bytes of *file_path*."""
        abs_path = self._abs(file_path)
        if not abs_path.exists():
            raise FileNotFoundError(f"'{file_path}' does not exist")
        return abs_path.read_bytes()

    def write(
        self,
        file_path: str,
        content: str | bytes,
        message: str | None = None,
        auto_commit: bool = True,
    ) -> str | None:
        """Write *content* to *file_path*, optionally committing.

        Returns the new commit hash when *auto_commit* is True, else None.
        """
        abs_path = self._abs(file_path)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            abs_path.write_bytes(content)
        else:
            abs_path.write_text(content, encoding="utf-8")
        if auto_commit:
            msg = message or f"write: {file_path}"
            return self._auto_commit([file_path], msg)
        return None

    def delete(
        self,
        file_path: str,
        message: str | None = None,
        auto_commit: bool = True,
    ) -> str | None:
        """Delete *file_path*, optionally committing.

        Returns the new commit hash when *auto_commit* is True, else None.
        """
        abs_path = self._abs(file_path)
        if not abs_path.exists():
            raise FileNotFoundError(f"'{file_path}' does not exist")
        abs_path.unlink()
        if auto_commit:
            self._git("add", "--", file_path)
            msg = message or f"delete: {file_path}"
            result = self._git("commit", "-m", msg, check=False)
            if result.returncode != 0:
                raise CommitError(result.stderr.strip())
            return self.head()
        return None

    def move(
        self,
        src: str,
        dst: str,
        message: str | None = None,
        auto_commit: bool = True,
    ) -> str | None:
        """Rename/move *src* to *dst*, optionally committing."""
        abs_src = self._abs(src)
        abs_dst = self._abs(dst)
        if not abs_src.exists():
            raise FileNotFoundError(f"'{src}' does not exist")
        abs_dst.parent.mkdir(parents=True, exist_ok=True)
        self._git("mv", "--", src, dst)
        if auto_commit:
            msg = message or f"move: {src} -> {dst}"
            result = self._git("commit", "-m", msg, check=False)
            if result.returncode != 0:
                raise CommitError(result.stderr.strip())
            return self.head()
        return None

    def copy(
        self,
        src: str,
        dst: str,
        message: str | None = None,
        auto_commit: bool = True,
    ) -> str | None:
        """Copy *src* to *dst*, optionally committing."""
        abs_src = self._abs(src)
        abs_dst = self._abs(dst)
        if not abs_src.exists():
            raise FileNotFoundError(f"'{src}' does not exist")
        abs_dst.parent.mkdir(parents=True, exist_ok=True)
        if abs_src.is_dir():
            shutil.copytree(str(abs_src), str(abs_dst))
        else:
            shutil.copy2(str(abs_src), str(abs_dst))
        if auto_commit:
            msg = message or f"copy: {src} -> {dst}"
            return self._auto_commit([dst], msg)
        return None

    def mkdir(self, dir_path: str) -> None:
        """Create a directory (and parents) under the repo root."""
        abs_path = self._abs(dir_path)
        abs_path.mkdir(parents=True, exist_ok=True)

    def exists(self, file_path: str) -> bool:
        """Return True if *file_path* exists."""
        try:
            return self._abs(file_path).exists()
        except AgentFSError:
            return False

    def is_dir(self, file_path: str) -> bool:
        """Return True if *file_path* is a directory."""
        try:
            return self._abs(file_path).is_dir()
        except AgentFSError:
            return False

    def list(self, dir_path: str = "", recursive: bool = False) -> list[str]:
        """List files (and directories) under *dir_path*.

        Paths are returned relative to the repo root.  ``.git`` entries are
        excluded.  When *recursive* is True the listing is depth-first.
        """
        abs_dir = self._abs(dir_path) if dir_path else self.root
        if not abs_dir.exists():
            raise FileNotFoundError(f"'{dir_path}' does not exist")
        if recursive:
            entries = [
                self._rel(p)
                for p in sorted(abs_dir.rglob("*"))
                if ".git" not in p.parts
            ]
        else:
            entries = [
                self._rel(p)
                for p in sorted(abs_dir.iterdir())
                if p.name != ".git"
            ]
        return entries

    # ------------------------------------------------------------------
    # Version-control primitives
    # ------------------------------------------------------------------

    def stage(self, *file_paths: str) -> None:
        """Stage one or more files (git add).  Stages all changes if no paths given."""
        if file_paths:
            self._git("add", "--", *file_paths)
        else:
            self._git("add", "-A")

    def unstage(self, *file_paths: str) -> None:
        """Unstage one or more files (git reset HEAD).  Unstages all if no paths given."""
        if file_paths:
            self._git("reset", "HEAD", "--", *file_paths)
        else:
            self._git("reset", "HEAD")

    def commit(self, message: str, allow_empty: bool = False) -> str:
        """Commit all staged changes and return the new commit hash."""
        args = ["commit", "-m", message]
        if allow_empty:
            args.append("--allow-empty")
        result = self._git(*args, check=False)
        if result.returncode != 0:
            if "nothing to commit" in result.stdout + result.stderr:
                return self.head()
            raise CommitError(result.stderr.strip())
        return self.head()

    def head(self) -> str:
        """Return the full hash of the current HEAD commit."""
        return self._git("rev-parse", "HEAD").stdout.strip()

    def status(self) -> list[StatusEntry]:
        """Return the working-tree status as a list of :class:`StatusEntry`."""
        result = self._git("status", "--porcelain=v1")
        entries: list[StatusEntry] = []
        for line in result.stdout.splitlines():
            if not line:
                continue
            staged = line[0]
            unstaged = line[1]
            path = line[3:].strip()
            # Handle renames: "old -> new"
            if " -> " in path:
                path = path.split(" -> ")[-1]
            entries.append(StatusEntry(path=path, staged=staged, unstaged=unstaged))
        return entries

    def log(
        self,
        file_path: str | None = None,
        limit: int | None = None,
        branch: str | None = None,
    ) -> list[CommitInfo]:
        """Return commit history as a list of :class:`CommitInfo`.

        Args:
            file_path: Restrict history to commits that touched this file.
            limit:     Maximum number of commits to return.
            branch:    Branch/ref to walk (defaults to current HEAD).
        """
        fmt = "%H%x00%h%x00%an%x00%ae%x00%ai%x00%s"
        args = ["log", f"--pretty=format:{fmt}"]
        if limit:
            args += [f"-{limit}"]
        if branch:
            args += [branch]
        if file_path:
            args += ["--", file_path]
        result = self._git(*args)
        commits: list[CommitInfo] = []
        for line in result.stdout.splitlines():
            if not line:
                continue
            parts = line.split("\x00")
            if len(parts) < 6:
                continue
            hash_, short, author, email, date, message = parts[:6]
            # Retrieve files changed for this commit
            files_result = self._git(
                "diff-tree", "--no-commit-id", "-r", "--name-only", hash_,
                check=False,
            )
            files = files_result.stdout.strip().splitlines()
            commits.append(CommitInfo(
                hash=hash_,
                short_hash=short,
                author=author,
                email=email,
                date=date,
                message=message,
                files_changed=files,
            ))
        return commits

    def diff(
        self,
        file_path: str | None = None,
        from_ref: str | None = None,
        to_ref: str | None = None,
        staged: bool = False,
    ) -> str:
        """Return a unified diff string.

        - No refs: working-tree vs index (unstaged changes).
        - *staged* only: index vs HEAD (staged changes).
        - *from_ref* only: HEAD vs *from_ref*.
        - Both refs: *from_ref*...*to_ref*.
        """
        args = ["diff"]
        if staged:
            args.append("--cached")
        if from_ref and to_ref:
            args.append(f"{from_ref}...{to_ref}")
        elif from_ref:
            args += [from_ref, "HEAD"]
        if file_path:
            args += ["--", file_path]
        return self._git(*args).stdout

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------

    def branches(self) -> list[str]:
        """List all local branch names."""
        result = self._git("branch", "--format=%(refname:short)")
        return [b.strip() for b in result.stdout.splitlines() if b.strip()]

    def current_branch(self) -> str:
        """Return the name of the currently checked-out branch."""
        result = self._git("rev-parse", "--abbrev-ref", "HEAD")
        return result.stdout.strip()

    def create_branch(self, name: str, from_ref: str | None = None) -> None:
        """Create a new branch, optionally from *from_ref*."""
        args = ["branch", name]
        if from_ref:
            args.append(from_ref)
        result = self._git(*args, check=False)
        if result.returncode != 0:
            raise BranchError(result.stderr.strip())

    def delete_branch(self, name: str, force: bool = False) -> None:
        """Delete a local branch.  Set *force* to delete unmerged branches."""
        flag = "-D" if force else "-d"
        result = self._git("branch", flag, name, check=False)
        if result.returncode != 0:
            raise BranchError(result.stderr.strip())

    def checkout(self, ref: str, file_path: str | None = None, create: bool = False) -> None:
        """Check out a branch/commit/tag, or restore a single *file_path* from *ref*.

        Set *create* to True to create-and-checkout a new branch (git checkout -b).
        """
        if file_path:
            result = self._git("checkout", ref, "--", file_path, check=False)
        else:
            flags = ["-b"] if create else []
            result = self._git("checkout", *flags, ref, check=False)
        if result.returncode != 0:
            raise RefNotFoundError(result.stderr.strip())

    def merge(self, branch: str, message: str | None = None, strategy: str | None = None) -> str:
        """Merge *branch* into the current branch and return the new HEAD hash.

        Raises :class:`MergeConflictError` on conflicts.
        """
        args = ["merge", branch]
        if message:
            args += ["-m", message]
        if strategy:
            args += ["-s", strategy]
        result = self._git(*args, check=False)
        if result.returncode != 0:
            if "CONFLICT" in result.stdout or "conflict" in result.stderr.lower():
                raise MergeConflictError(result.stdout.strip())
            raise AgentFSError(result.stderr.strip())
        return self.head()

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def tag(self, name: str, message: str | None = None, ref: str | None = None) -> None:
        """Create a lightweight or annotated tag.

        If *message* is given an annotated tag is created.
        """
        args = ["tag"]
        if message:
            args += ["-a", name, "-m", message]
        else:
            args.append(name)
        if ref:
            args.append(ref)
        result = self._git(*args, check=False)
        if result.returncode != 0:
            raise AgentFSError(result.stderr.strip())

    def tags(self) -> list[str]:
        """List all tags sorted by creation date (newest first)."""
        result = self._git("tag", "--sort=-creatordate")
        return [t.strip() for t in result.stdout.splitlines() if t.strip()]

    def delete_tag(self, name: str) -> None:
        """Delete a local tag."""
        result = self._git("tag", "-d", name, check=False)
        if result.returncode != 0:
            raise AgentFSError(result.stderr.strip())

    # ------------------------------------------------------------------
    # File-level version operations
    # ------------------------------------------------------------------

    def read_at(self, file_path: str, ref: str) -> str:
        """Return the text content of *file_path* at *ref* (commit/branch/tag)."""
        result = self._git("show", f"{ref}:{file_path}", check=False)
        if result.returncode != 0:
            raise RefNotFoundError(f"'{file_path}' not found at ref '{ref}'")
        return result.stdout

    def read_bytes_at(self, file_path: str, ref: str) -> bytes:
        """Return the raw bytes of *file_path* at *ref*."""
        proc = subprocess.run(
            ["git", "show", f"{ref}:{file_path}"],
            cwd=self.root,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RefNotFoundError(f"'{file_path}' not found at ref '{ref}'")
        return proc.stdout

    def restore(self, file_path: str, ref: str, auto_commit: bool = True) -> str | None:
        """Restore *file_path* to its state at *ref*, optionally committing."""
        content = self.read_at(file_path, ref)
        return self.write(file_path, content, message=f"restore: {file_path} from {ref}", auto_commit=auto_commit)

    def revert(self, commit_hash: str) -> str:
        """Create a revert commit that undoes *commit_hash*.

        Returns the new HEAD commit hash.
        """
        result = self._git("revert", "--no-edit", commit_hash, check=False)
        if result.returncode != 0:
            raise CommitError(result.stderr.strip())
        return self.head()

    def cherry_pick(self, commit_hash: str) -> str:
        """Apply the changes of *commit_hash* onto the current branch.

        Returns the new HEAD commit hash.
        """
        result = self._git("cherry-pick", commit_hash, check=False)
        if result.returncode != 0:
            raise CommitError(result.stderr.strip())
        return self.head()

    # ------------------------------------------------------------------
    # Stash
    # ------------------------------------------------------------------

    def stash(self, message: str | None = None) -> None:
        """Save the current working-tree state to the stash."""
        args = ["stash", "push"]
        if message:
            args += ["-m", message]
        self._git(*args)

    def stash_pop(self, index: int = 0) -> None:
        """Apply and remove the stash entry at *index*."""
        self._git("stash", "pop", f"stash@{{{index}}}")

    def stash_apply(self, index: int = 0) -> None:
        """Apply the stash entry at *index* without removing it."""
        self._git("stash", "apply", f"stash@{{{index}}}")

    def stash_drop(self, index: int = 0) -> None:
        """Remove the stash entry at *index* without applying."""
        self._git("stash", "drop", f"stash@{{{index}}}")

    def stash_list(self) -> list[dict]:
        """Return all stash entries as a list of dicts with 'index', 'ref', and 'message'."""
        result = self._git("stash", "list", "--format=%gd %gs")
        entries = []
        for i, line in enumerate(result.stdout.splitlines()):
            if not line:
                continue
            parts = line.split(" ", 1)
            ref = parts[0] if parts else ""
            message = parts[1] if len(parts) > 1 else ""
            entries.append({"index": i, "ref": ref, "message": message})
        return entries

    # ------------------------------------------------------------------
    # Repository info
    # ------------------------------------------------------------------

    def info(self) -> dict:
        """Return a summary dict describing the current repository state."""
        return {
            "root": str(self.root),
            "branch": self.current_branch(),
            "head": self.head(),
            "branches": self.branches(),
            "tags": self.tags(),
            "status": [
                {"path": e.path, "staged": e.staged, "unstaged": e.unstaged}
                for e in self.status()
            ],
        }
