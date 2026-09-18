from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any

class Step(BaseModel):
    who: Literal["user", "system", "agent"]
    action: str
    estimated_time_minutes: int
    priority: Literal["low", "medium", "high"]
    actor: Optional[str] = None

class ProblemStatement(BaseModel):
    product_idea: str = Field(description="The core product idea or problem to solve")
    priority: Literal["cheap", "fast", "premium"] = Field(description="The priority/quality level defined by the CEO")

class BudgetEstimate(BaseModel):
    team_name: str
    amount: float
    deliverables: List[str]

class AggregatedBudget(BaseModel):
    estimates: List[BudgetEstimate]
    buffer: float
    total: float
    status: Literal["pending", "approved", "rejected", "negotiating"] = "pending"

class TeamOutcome(BaseModel):
    team_name: str
    deliverables: List[str]
    status: Literal["success", "failure", "in_progress"]
    blueprint: Optional[str] = None
    repo_summary: Optional[str] = None
    detailed_dev_reports: Optional[Dict[str, Any]] = None
    specialist_detailed_reports: Optional[Dict[str, Any]] = None

class ProjectOutcome(BaseModel):
    aggregated_results: List[TeamOutcome]
    total_spent: float
    pass_testing: bool
    ceo_decision: Optional[Literal["accept", "retry", "stop"]] = None
