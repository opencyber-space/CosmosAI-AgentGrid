class AgentFSError(Exception):
    pass

class FileNotFoundError(AgentFSError):
    pass

class CommitError(AgentFSError):
    pass

class BranchError(AgentFSError):
    pass

class MergeConflictError(AgentFSError):
    pass

class RefNotFoundError(AgentFSError):
    pass
