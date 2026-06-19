from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    REFLECTIVE = "reflective"
    REWARD = "reward"


class Outcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


@dataclass
class BaseMemory:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = field(default=None, repr=False)
    created_at: datetime = field(default_factory=datetime.utcnow)
    score: Optional[float] = None  # similarity score when retrieved from vector search


@dataclass
class EpisodicMemory(BaseMemory):
    """A specific event or experience bound to time and context."""
    memory_type: MemoryType = field(default=MemoryType.EPISODIC, init=False)
    session_id: str = ""
    agent_id: str = ""
    context: Dict[str, Any] = field(default_factory=dict)  # who, when, where, why
    outcome: Outcome = Outcome.UNKNOWN
    importance: float = 0.5  # 0.0–1.0


@dataclass
class SemanticMemory(BaseMemory):
    """A factual statement stored as a subject–predicate–object triple."""
    memory_type: MemoryType = field(default=MemoryType.SEMANTIC, init=False)
    subject: str = ""
    predicate: str = ""
    object: str = ""
    confidence: float = 1.0
    source: str = ""
    updated_at: Optional[datetime] = None


@dataclass
class ProcedureStep:
    step_order: int = 0
    action: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    expected_outcome: str = ""


@dataclass
class ProceduralMemory(BaseMemory):
    """A named skill: a sequence of actions with trigger conditions."""
    memory_type: MemoryType = field(default=MemoryType.PROCEDURAL, init=False)
    name: str = ""
    trigger_conditions: List[str] = field(default_factory=list)
    steps: List[ProcedureStep] = field(default_factory=list)
    success_rate: float = 0.0
    use_count: int = 0
    updated_at: Optional[datetime] = None


@dataclass
class ReflectiveMemory(BaseMemory):
    """A self-generated insight or lesson extracted from past experience."""
    memory_type: MemoryType = field(default=MemoryType.REFLECTIVE, init=False)
    source_episode_id: Optional[str] = None
    lesson: str = ""
    improvement_suggestion: str = ""
    confidence: float = 1.0
    applied_count: int = 0


@dataclass
class RewardMemory(BaseMemory):
    """A (state, action, reward) tuple used for reinforcement-style learning."""
    memory_type: MemoryType = field(default=MemoryType.REWARD, init=False)
    state_description: str = ""
    action: str = ""
    reward: float = 0.0
    outcome: str = ""
    policy: str = "default"
    context: Dict[str, Any] = field(default_factory=dict)
