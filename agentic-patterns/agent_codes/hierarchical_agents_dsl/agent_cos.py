import logging
import uuid
import json
import dspy
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from agents_sdk.core.known_agents import KnownAgents
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.hierarchical_agents_models import ProblemStatement, AggregatedBudget, BudgetEstimate, TeamOutcome, ProjectOutcome
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

# --- 1. The Signatures ---

class CoSExecutionTriggerSignature(dspy.Signature):
    """
    ### ROLE
    You are the Chief of Staff (Global Orchestrator).
    
    ### TASK
    Based on Financial Approval, decide which teams should start working immediately.
    Marketing and Architecture usually start parallel, while Development waits for Architecture.
    
    ### OUTPUT
    Output EXACTLY a JSON list of TeamLead IDs to trigger.
    """
    approval_decision = dspy.InputField(desc="The approval decision from the Financial Team")
    problem_statement = dspy.InputField(desc="The project context")
    teams_to_trigger = dspy.OutputField(desc="JSON list of strings: ['company-marketing-team-lead', 'company-arch-design-team-lead', ...]")

class CoSArtifactRouterSignature(dspy.Signature):
    """
    ### ROLE
    You are the Chief of Staff (Global Orchestrator).
    
    ### TASK
    Decide where to route a finished artifact based on current project dependencies.
    - If the artifact source is "Arch & Design Team", YOU MUST route it to "company-developer-team-lead" and "company-testing-team-lead" ONLY. DO NOT route it back to "company-arch-design-team-lead".
    - If the artifact source is "Developer Team", YOU MUST route it to "company-testing-team-lead" ONLY.
    - Never route an artifact back to the team that produced it.
    
    ### OUTPUT
    Output EXACTLY a JSON list of Target Subject IDs.
    """
    artifact_source = dspy.InputField(desc="Team that produced the artifact")
    artifact_description = dspy.InputField(desc="Summary of what was produced")
    valid_target_ids = dspy.InputField(desc="List of valid Team Lead agent IDs that you can route to")
    targets = dspy.OutputField(desc="JSON list of strings: ['company-developer-team-lead', ...]")

class CoSOutcomeSummarizerSignature(dspy.Signature):
    """
    ### ROLE
    You are the Chief of Staff (Global Orchestrator).
    
    ### TASK
    Summarize the final project outcome for the CEO. Include status from all teams and total budget spent.
    
    ### OUTPUT
    Output EXACTLY a JSON block representing the ProjectOutcome.
    """
    team_outcomes = dspy.InputField(desc="List of outcomes from all departments")
    total_spent = dspy.InputField(desc="Total budget spent")
    final_report = dspy.OutputField(desc="JSON block matching ProjectOutcome model")

# --- 2. The CoS Agent ---

class CoSAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        
        # Central Task Registry
        self.task_registry: Dict[str, Dict[str, Any]] = {}

        # Dynamic Discovery
        try:
            known_agents = KnownAgents(default_compact=False)
            known_agents.query_and_add(query={
                "metadata.subject_search_tags": "company-team-leads"
            })
            self.all_team_leads = [agent.id for agent in known_agents.list_all()]
            log.info("Discovered Team Leads via KnownAgents: %s", self.all_team_leads)
        except Exception as e:
            log.error(f"Failed to discover team leads: {e}")
            self.all_team_leads = []
        # Initialize HIS Client
        his_config = self.subject.persona.config.get("parameters", {}).get("HIS_CONFIG", {})
        self.his_client = HisClient(
            base_url=his_config["HIS_BASE_URL"],
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )


    def _get_lm_context(self, model_name, session_id):
        return dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=session_id))


    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        text = task.job_data.get("text")
        if not text:
            # Check if it's a callback with other data
            if any(key in task.job_data for key in ["budget_estimate", "approval_decision", "team_outcome"]):
                return [task]
            log.warning("Task %s has no 'text' in job_data, skipping.", task.task_id)
            return None
        return [task]
    def _log_to_his(self, target_id, job_data):
        try:
            msg = {"text": str(job_data), "source_id": self.subject.identity.subject_id, "destination_id": target_id, "team": "COS Team"}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass


    def get_muxer(self):
        return None

    def _init_task(self, task_id, user_request):
        if task_id not in self.task_registry:
            self.task_registry[task_id] = {
                "user_request": user_request,
                "priority": "Fast",
                "budgets": {},
                "team_outcomes": {},
                "expected_teams": [],
                "approval_status": False,
                "total_budget": 0.0
            }
        elif user_request and not self.task_registry[task_id].get("user_request"):
            self.task_registry[task_id]["user_request"] = user_request

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            task_type = data.get("task_type", "initiate")
            llm_session_id = str(uuid.uuid4())
            model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
            comm_type = data.get("communication_type", "delegate")
            
            task_id = data.get("task_id", task.task_id)
            user_request = data.get("user_request")
            
            # Extract priority directly from payload if available
            fallback_priority = "Fast"
            
            # Extract problem_statement from text
            text = data.get("text")
            extracted = extract_json(text) if text else None
            problem_statement = extracted if isinstance(extracted, dict) else (text or data.get("problem_statement"))
            
            if isinstance(problem_statement, dict) and "priority" in problem_statement:
                fallback_priority = problem_statement.get("priority", "Fast")
            
            priority = data.get("priority", fallback_priority)
            
            if task_id not in self.task_registry:
                self.task_registry[task_id] = {
                    "user_request": user_request, 
                    "priority": priority,
                    "expected_teams": [], # This will be populated in _stage_1_broadcast
                    "budgets": {},
                    "team_outcomes": {},
                    "approval_status": False,
                    "total_budget": 0.0
                }
            else:
                if user_request and not self.task_registry[task_id].get("user_request"):
                    self.task_registry[task_id]["user_request"] = user_request
                if priority and priority != "Fast" and self.task_registry[task_id]["priority"] == "Fast":
                    self.task_registry[task_id]["priority"] = priority
            
            # The 'text' in CoS is usually the stringified ProblemStatement (JSON)
            # problem_statement is already extracted above
            
            if "budget_estimate" in data:
                return self._stage_2_handle_budget(task, task_id, problem_statement, llm_session_id, model_name, comm_type)
            
            elif "approval_decision" in data:
                return self._stage_3_handle_approval(task, task_id, self.task_registry[task_id]["user_request"], llm_session_id, model_name, comm_type)
            
            elif "team_outcome" in data:
                return self._stage_4_handle_outcome(task, task_id, self.task_registry[task_id]["user_request"], llm_session_id, model_name, comm_type)

            elif task_type == "initiate":
                return self._stage_1_broadcast(task, task_id, problem_statement, llm_session_id, model_name, comm_type)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in CoS Agent: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _stage_1_broadcast(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        """Stage: Identify Teams and Request Budgets"""
        # Simplification: Broadcast to all discovered team leads except the financial team for budget estimation
        expected_teams = [team for team in self.all_team_leads if team != "company-financial-team-lead"]
        
        if not expected_teams:
            log.warning("No operating team leads discovered. Cannot broadcast for budget estimation.")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": "No operating team leads discovered."})

        self.task_registry[task_id]["expected_teams"] = expected_teams

        for team_id in expected_teams:
            job_data = {
                "task_type": "estimate_budget",
                "text": json.dumps(problem_statement),
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": comm_type,
                "task_id": task_id,
                "user_request": self.task_registry[task_id]["user_request"],
                "priority": self.task_registry[task_id]["priority"]
            }
            self._send(task, team_id, job_data, session_id, comm_type)
            
        return AgentResult(task_id=task.task_id, skip=True)

    def _stage_2_handle_budget(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        """Stage: Collect Budgets and Ask for Financial Approval"""
        estimate = BudgetEstimate(**task.job_data["budget_estimate"])
        registry = self.task_registry[task_id]
        registry["budgets"][estimate.team_name] = estimate
        
        if len(registry["budgets"]) >= len(registry["expected_teams"]):
            total = sum(e.amount for e in registry["budgets"].values())
            registry["total_budget"] = total * 1.1 # Add buffer
            aggregated = AggregatedBudget(
                estimates=list(registry["budgets"].values()),
                buffer=total * 0.1,
                total=registry["total_budget"]
            )
            
            job_data = {
                "task_type": "approve_budget",
                "text": json.dumps(aggregated.dict()),
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": comm_type,
                "task_id": task_id,
                "user_request": registry["user_request"],
                "priority": registry["priority"]
            }
            self._send(task, "company-financial-team-lead", job_data, session_id, comm_type)
            
        return AgentResult(task_id=task.task_id, skip=True)

    def _stage_3_handle_approval(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        """Stage: Trigger Execution Phase based on Approval"""
        decision = task.job_data["approval_decision"]
        registry = self.task_registry[task_id]
        if not decision.get("approved"):
            log.warning("Finance rejected budget. CoS should negotiate (demo: escalate to CEO)")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": "Financial approval rejected."})

        registry["approval_status"] = True

        # Bypass LLM prediction and route execution tasks to all functional team leads
        for team_id in self.all_team_leads:
            if team_id == "company-financial-team-lead":
                continue

            team_mapping = {
                "company-arch-design-team-lead": "Arch & Design Team",
                "company-developer-team-lead": "Frontend and Backend Development Team",
                "company-testing-team-lead": "Testing Team",
                "company-marketing-team-lead": "Marketing Team"
            }
            team_name = team_mapping.get(team_id)
            
            deliverables = []
            if team_name:
                estimate = registry.get("budgets", {}).get(team_name)
                if estimate:
                    deliverables = estimate.deliverables

            job_data = {
                "task_type": "execute_task",
                "text": json.dumps(problem_statement),
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": comm_type,
                "task_id": task_id,
                "user_request": registry["user_request"],
                "priority": registry["priority"],
                "deliverables": deliverables
            }
            self._send(task, team_id, job_data, session_id, comm_type)

        return AgentResult(task_id=task.task_id, skip=True)

    def _stage_4_handle_outcome(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        """Stage: Route Artifacts and Summarize Results"""
        outcome_data = task.job_data["team_outcome"]
        
        # Sanitize status to meet Pydantic Literal rules ('success', 'failure', 'in_progress')
        raw_status = outcome_data.get("status", "success").lower().replace(" ", "_")
        if raw_status not in ["success", "failure", "in_progress"]:
            raw_status = "success"
        outcome_data["status"] = raw_status
        
        outcome = TeamOutcome(**outcome_data)
        registry = self.task_registry[task_id]
        registry["team_outcomes"][outcome.team_name] = outcome_data
        
        # Artifact Routing Logic
        targets = []
        if "Arch" in outcome.team_name:
            targets = ["company-developer-team-lead", "company-testing-team-lead"]
            log.info(f"Deterministically routing Architecture artifact to {targets}")
        elif "Developer" in outcome.team_name or "Frontend" in outcome.team_name or "Backend" in outcome.team_name:
            targets = ["company-testing-team-lead"]
            log.info(f"Deterministically routing Developer artifact to {targets}")
        elif any(keyword in outcome.team_name for keyword in ["Testing", "Marketing", "Financial"]):
            targets = []
            log.info(f"No downstream target necessary for {outcome.team_name} artifact.")
        else:
            with self._get_lm_context(model_name, session_id):
                router = dspy.ChainOfThought(CoSArtifactRouterSignature)
                route_result = router(
                    artifact_source=outcome.team_name, 
                    artifact_description=outcome.deliverables if outcome.deliverables else "Outcome",
                    valid_target_ids=json.dumps(self.all_team_leads)
                )
                targets = extract_json(route_result.targets)
            log.info(f"LLM Routed Artifacts from {outcome.team_name} to: {targets}")
        for target_id in targets:
            job_data = {
                "task_type": "process_artifact",
                "text": json.dumps(outcome_data),
                "artifact_data": outcome_data,
                "problem_statement": problem_statement,
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": comm_type,
                "task_id": task_id,
                "user_request": registry["user_request"]
            }
            self._send(task, target_id, job_data, session_id, comm_type)

        # Completion Check
        if len(registry["team_outcomes"]) >= len(registry["expected_teams"]):
            return self._finalize_to_ceo(task, task_id, session_id, model_name, comm_type)
            
        return AgentResult(task_id=task.task_id, skip=True)

    def _finalize_to_ceo(self, task, task_id, session_id, model_name, comm_type):
        """Report final outcome back to CEO"""
        registry = self.task_registry[task_id]
        with self._get_lm_context(model_name, session_id):
            summarizer = dspy.ChainOfThought(CoSOutcomeSummarizerSignature)
            summary = summarizer(team_outcomes=json.dumps(list(registry["team_outcomes"].values())), total_spent=registry["total_budget"])
            
            final_report = extract_json(summary.final_report)

        job_data = {
            "communication_type": comm_type,
            "task_id": task_id,
            "final_project_outcome": final_report,
            "text": json.dumps(final_report),
            "model_name": model_name,
            "session_id": session_id
        }
        self._send(task, "company-ceo-agent", job_data, session_id, comm_type)
        return AgentResult(task_id=task.task_id, skip=True)

    def _send(self, parent_task, target_id, job_data, session_id, comm_type):
        if comm_type == "delegate":
            self._log_to_his(target_id, job_data)
            self.context.delegator.submit_and_wait(subject_id=target_id, session_id=session_id, task_id=parent_task.task_id, task_data=job_data)
        else:
            self._log_to_his(target_id, job_data)
            self.context.p2p_manager.send_sync(task=parent_task, subject_id=target_id, job_data=job_data, session_id=session_id)

if __name__ == "__main__":
    main(CoSAgent)
