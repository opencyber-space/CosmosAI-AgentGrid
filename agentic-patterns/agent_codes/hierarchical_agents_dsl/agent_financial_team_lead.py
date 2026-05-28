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
from utils.hierarchical_agents_models import BudgetEstimate, TeamOutcome
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

# --- 1. The Signatures ---

class FinancialApprovalSignature(dspy.Signature):
    """
    ### ROLE
    You are the Financial Team Lead.

    ### TASK
    Evaluate the proposed aggregated budget against the problem statement and available budget.
    Take into account the feedback provided by the Financial Controller and Financial Strategist.
    Make a final decision to approve or disapprove the budget based ON THEIR FEEDBACK. You cannot approve if they strongly warn against it or if the budget exceeds the available funds.
    
    ### OUTPUT
    Output EXACTLY a JSON block: {approved: bool, reasoning: str, suggestions: List[str]}
    """
    aggregated_budget = dspy.InputField(desc="The total budget estimate proposed")
    available_budget = dspy.InputField(desc="The actual funds available in the project ledger")
    problem_statement = dspy.InputField(desc="The product vision and priority")
    controller_feedback = dspy.InputField(desc="Cost realism and risk assessment from Controller")
    strategist_feedback = dspy.InputField(desc="Reallocation and strategic feedback from Strategist")
    approval_decision = dspy.OutputField(desc="JSON matching approval schema")

class FinancialAuditSignature(dspy.Signature):
    """
    ### ROLE
    You are the Financial Team Lead.

    ### TASK
    Audit the final spending and project status for financial compliance.
    
    ### OUTPUT
    Output EXACTLY a JSON block: {team_name, status, financial_summary: str}
    """
    total_spent = dspy.InputField(desc="Total budget spent")
    team_outcomes = dspy.InputField(desc="Outcomes from all teams")
    team_outcome = dspy.OutputField(desc="JSON matching TeamOutcome schema")

# --- 2. The Financial Team Lead Agent ---

class FinancialTeamLeadAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.task_registry = {}

        # Dynamic Discovery
        try:
            known_agents = KnownAgents(default_compact=False)
            known_agents.query_and_add(query={
                "metadata.subject_search_tags": "financial-subordinates"
            })
            self.subordinates = [agent.id for agent in known_agents.list_all()]
            log.info("Financial discovered subordinates: %s", self.subordinates)
        except Exception as e:
            log.error(f"Failed to discover financial subordinates: {e}")
            self.subordinates = []
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
            # Maybe it's a direct structured data call
            if any(key in task.job_data for key in ["aggregated_budget", "total_spent", "team_outcomes"]):
                return [task]
            log.warning("Task %s has no 'text' in job_data, skipping.", task.task_id)
            return None
        return [task]
    def _log_to_his(self, target_id, job_data):
        try:
            msg = {"text": str(job_data), "source_id": self.subject.identity.subject_id, "destination_id": target_id, "team": "Finance Team"}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass


    def get_muxer(self):
        return None

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            task_type = data.get("task_type", "approve_budget")
            llm_session_id = str(uuid.uuid4())
            model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
            communication_type = data.get("communication_type", "delegate")
            
            task_id = data.get("task_id", task.task_id)
            user_request = data.get("user_request")
            
            priority = data.get("priority", "Fast")
            if task_id not in self.task_registry:
                self.task_registry[task_id] = {"user_request": user_request, "priority": priority}
            else:
                if user_request:
                    self.task_registry[task_id]["user_request"] = user_request
                if "priority" in data:
                    self.task_registry[task_id]["priority"] = priority

            if task_type == "approve_budget":
                text = data.get("text")
                if text:
                    extracted = extract_json(text)
                    if isinstance(extracted, dict):
                        if "estimates" in extracted:
                            data["aggregated_budget"] = extracted
                        else:
                            data["problem_statement"] = extracted
                
                if not data.get("problem_statement"):
                    data["problem_statement"] = self.task_registry[task_id]["user_request"]

                # Step 1: Store initial budget request and ask Accountant for balance
                self.task_registry[task_id]["aggregated_budget"] = data.get("aggregated_budget")
                self.task_registry[task_id]["problem_statement"] = data.get("problem_statement")
                self.task_registry[task_id]["controller_feedback"] = None
                self.task_registry[task_id]["strategist_feedback"] = None
                self.task_registry[task_id]["approval_loops"] = 0

                accountant_data = {
                    "task_type": "check_balance",
                    "task_id": task_id,
                    "session_id": llm_session_id,
                    "model_name": model_name,
                    "communication_type": communication_type,
                    "user_request": self.task_registry[task_id]["user_request"]
                }
                
                target_id = "company-financial-accountant-agent"
                if communication_type == "delegate":
                    self._log_to_his(target_id, accountant_data)
                    self.context.delegator.submit_and_wait(subject_id=target_id, session_id=llm_session_id, task_id=task.task_id, task_data=accountant_data)
                else:
                    self._log_to_his(target_id, accountant_data)
                    self.context.p2p_manager.send_sync(task=task, subject_id=target_id, job_data=accountant_data, session_id=llm_session_id)
                
                return AgentResult(task_id=task.task_id, skip=True)
            
            elif task_type == "specialist_output":
                text = data.get("text")
                if text:
                    payload = extract_json(text)
                    if isinstance(payload, dict):
                        # Merge payload keys to job_data for easier checks below
                        for k, v in payload.items():
                            data[k] = v

                role = data.get("role")

                if role in ["Financial Accountant", "Financial Controller", "Financial Strategist"]:
                    if role == "Financial Accountant" and data.get("is_balance_report"):
                        # Step 2: Receive Balance from Accountant & Dispatch to Specialists
                        specialist_output = data.get("specialist_output", {})
                        self.task_registry[task_id]["available_budget"] = specialist_output.get("available_budget", 0)
                        
                        # Dispatch to both Controller and Strategist
                        specialist_targets = ["company-financial-controller-agent", "company-financial-strategist-agent"]
                        nav_data = {
                            "task_type": "validate",
                            "aggregated_budget": self.task_registry[task_id]["aggregated_budget"],
                            "available_budget": self.task_registry[task_id]["available_budget"],
                            "problem_statement": self.task_registry[task_id]["problem_statement"],
                            "task_id": task_id,
                            "session_id": llm_session_id,
                            "model_name": model_name,
                            "communication_type": communication_type,
                            "user_request": self.task_registry[task_id]["user_request"]
                        }
                        
                        for target in specialist_targets:
                            if communication_type == "delegate":
                                self._log_to_his(target, nav_data)
                                self.context.delegator.submit_and_wait(subject_id=target, session_id=llm_session_id, task_id=task.task_id, task_data=nav_data)
                            else:
                                self._log_to_his(target, nav_data)
                                self.context.p2p_manager.send_sync(task=task, subject_id=target, job_data=nav_data, session_id=llm_session_id)
                        
                        return AgentResult(task_id=task.task_id, skip=True)

                    elif role in ["Financial Controller", "Financial Strategist"] and not data.get("is_deduction_report"):
                        # Step 3: Accumulate Specialist Output
                        if role == "Financial Controller":
                            self.task_registry[task_id]["controller_feedback"] = data.get("specialist_output")
                        elif role == "Financial Strategist":
                            self.task_registry[task_id]["strategist_feedback"] = data.get("specialist_output")
                        
                        # If both have replied, evaluate via LLM
                        if self.task_registry[task_id].get("controller_feedback") and self.task_registry[task_id].get("strategist_feedback"):
                            return self._evaluate_approval(task, task_id, llm_session_id, model_name, communication_type)
                        
                        return AgentResult(task_id=task.task_id, skip=True)

                return AgentResult(task_id=task.task_id, skip=True)

            elif task_type == "execute_task":
                return self._handle_audit(task, task_id, llm_session_id, model_name, communication_type)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Financial Team Lead: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _evaluate_approval(self, task, task_id, session_id, model_name, comm_type):
        registry = self.task_registry[task_id]
        
        with self._get_lm_context(model_name, session_id):
            module = dspy.ChainOfThought(FinancialApprovalSignature)
            result = module(
                aggregated_budget=json.dumps(registry["aggregated_budget"]),
                available_budget=str(registry["available_budget"]),
                problem_statement=json.dumps(registry["problem_statement"]),
                controller_feedback=json.dumps(registry["controller_feedback"]),
                strategist_feedback=json.dumps(registry["strategist_feedback"])
            )
            
            decision_raw = result.approval_decision
            decision_data = extract_json(decision_raw)
            
        # Step 4: Decision Routing
        if decision_data.get("approved"):
            # Formalize deduction
            total_cost = registry["aggregated_budget"].get("total", 0)
            accountant_data = {
                "task_type": "deduct_budget",
                "amount": total_cost,
                "task_id": task_id,
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": comm_type,
                "user_request": registry["user_request"]
            }
            target_id = "company-financial-accountant-agent"
            if comm_type == "delegate":
                self._log_to_his(target_id, accountant_data)
                self.context.delegator.submit_and_wait(subject_id=target_id, session_id=session_id, task_id=task.task_id, task_data=accountant_data)
            else:
                self._log_to_his(target_id, accountant_data)
                self.context.p2p_manager.send_sync(task=task, subject_id=target_id, job_data=accountant_data, session_id=session_id)
            
            # Send success to CoS
            job_data = {
                "approval_decision": decision_data,
                "task_id": task_id,
                "user_request": registry.get("user_request"),
                "communication_type": comm_type,
                "final_budget": registry["aggregated_budget"],
                "model_name": model_name,
                "session_id": session_id
            }
            self._send_to_cos(task, job_data, session_id, comm_type)
        else:
            # 20% Budget Cut Logic
            registry["approval_loops"] += 1
            if registry["approval_loops"] > 3:
                # Force approve to prevent infinite loop
                decision_data["approved"] = True
                decision_data["reasoning"] += " (Forced approval after 3 failed adjustments)"
                job_data = {
                    "approval_decision": decision_data,
                    "task_id": task_id,
                    "user_request": registry.get("user_request"),
                    "communication_type": comm_type,
                    "final_budget": registry["aggregated_budget"],
                    "model_name": model_name,
                    "session_id": session_id
                }
                self._send_to_cos(task, job_data, session_id, comm_type)
                return AgentResult(task_id=task.task_id, skip=True)

            estimates = registry["aggregated_budget"].get("estimates", [])
            if estimates:
                # Find a candidate to cut (lowest amount or just pick one for demo)
                # "disapproved then it should go for 20% budget cuts for any low priority team"
                # Simplest proxy: pick the lowest requested amount that is > 0
                valid_estimates = [e for e in estimates if e.get("amount", 0) > 0]
                if valid_estimates:
                    target_estimate = min(valid_estimates, key=lambda x: x.get("amount", float("inf")))
                    cut_amount = target_estimate["amount"] * 0.20
                    target_estimate["amount"] -= cut_amount
                    
                    # Update totals
                    new_total = sum(e.get("amount", 0) for e in estimates)
                    registry["aggregated_budget"]["buffer"] = new_total * 0.1
                    registry["aggregated_budget"]["total"] = new_total * 1.1

            # Reset feedback and restart step 2
            registry["controller_feedback"] = None
            registry["strategist_feedback"] = None
            
            specialist_targets = ["company-financial-controller-agent", "company-financial-strategist-agent"]
            nav_data = {
                "task_type": "validate",
                "aggregated_budget": registry["aggregated_budget"],
                "available_budget": registry["available_budget"],
                "problem_statement": registry["problem_statement"],
                "task_id": task_id,
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": comm_type,
                "user_request": registry["user_request"]
            }
            
            for target in specialist_targets:
                if comm_type == "delegate":
                    self._log_to_his(target, nav_data)
                    self.context.delegator.submit_and_wait(subject_id=target, session_id=session_id, task_id=task.task_id, task_data=nav_data)
                else:
                    self._log_to_his(target, nav_data)
                    self.context.p2p_manager.send_sync(task=task, subject_id=target, job_data=nav_data, session_id=session_id)

        return AgentResult(task_id=task.task_id, skip=True)

    def _handle_audit(self, task, task_id, session_id, model_name, comm_type):
        with self._get_lm_context(model_name, session_id):
            module = dspy.ChainOfThought(FinancialAuditSignature)
            result = module(total_spent=0, team_outcomes="Project in execution")
            
            outcome_raw = result.team_outcome
            outcome_data = extract_json(outcome_raw)
            
        job_data = {
            "team_outcome": outcome_data,
            "task_id": task_id,
            "user_request": self.task_registry[task_id].get("user_request"),
            "communication_type": comm_type,
            "model_name": model_name,
            "session_id": session_id
        }
        self._send_to_cos(task, job_data, session_id, comm_type)
        return AgentResult(task_id=task.task_id, skip=True)

    def _send_to_cos(self, parent_task, job_data, session_id, comm_type):
        target_id = "company-chief-of-staff-agent"
        if comm_type == "delegate":
            self._log_to_his(target_id, job_data)
            self.context.delegator.submit_and_wait(subject_id=target_id, session_id=session_id, task_id=parent_task.task_id, task_data=job_data)
        else:
            self._log_to_his(target_id, job_data)
            self.context.p2p_manager.send_sync(task=parent_task, subject_id=target_id, job_data=job_data, session_id=session_id)

if __name__ == "__main__":
    main(FinancialTeamLeadAgent)
