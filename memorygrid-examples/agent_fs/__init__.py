"""agent_fs — version-controlled, git-backed file system for agents."""

from .core import AgentFS, CommitInfo, StatusEntry
from .exceptions import (
    AgentFSError,
    BranchError,
    CommitError,
    MergeConflictError,
    RefNotFoundError,
)
from .exceptions import FileNotFoundError as AgentFSFileNotFoundError

__all__ = [
    "AgentFS",
    "CommitInfo",
    "StatusEntry",
    "AgentFSError",
    "AgentFSFileNotFoundError",
    "BranchError",
    "CommitError",
    "MergeConflictError",
    "RefNotFoundError",
]
