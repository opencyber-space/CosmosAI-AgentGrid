import logging
import uuid
import json
import time
import dspy
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "agent-workflow-financial-team-lead": "my-company-financial-team-lead-agent",
    "agent-workflow-financial-accountant": "my-company-financial-accountant-agent",
    "agent-workflow-financial-controller": "my-company-financial-controller-agent",
    "agent-workflow-financial-strategist": "my-company-financial-strategist-agent",
    "agent-workflow-cos":"my-chief-of-staff-agent"
}

NODE_ACCOUNTANT = "my-company-financial-accountant-agent"
NODE_CONTROLLER = "my-company-financial-controller-agent"
NODE_STRATEGIST = "my-company-financial-strategist-agent"
NODE_COS = "my-chief-of-staff-agent"

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

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        if not isinstance(data, dict):
            data = {}
        if "initial_input" in data and isinstance(data["initial_input"], dict):
            data = data["initial_input"]
        communication_type = data.get("communication_type", "delegate")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return communication_type, model_name, session_id

class ModelContextManager:
    def __init__(self, aios_dspy_lm: AIOS_DSPy_LMs):
        self.aios_dspy_lm = aios_dspy_lm

    def get_context(self, model_name: str, session_id: str):
        return dspy.settings.context(
            lm=self.aios_dspy_lm.get_choosen_model(
                model_name=model_name,
                session_id=session_id
            )
        )

class FinancialTeamLeadAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        self.task_registry = {}

        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        data = task.job_data
        if not isinstance(data, dict):
            data = {}
        if not data:
            log.warning("Task %s has empty or invalid job_data, skipping.", task.task_id)
            return None
        return [task]

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Workflow Router", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            
            data = task.job_data
            if not isinstance(data, dict):
                data = {}
            
            initial_input = data.get("initial_input", data)
            if not isinstance(initial_input, dict):
                initial_input = {}
            if not initial_input and "task_type" in data:
                initial_input = data

            #log.info("Financial Lead Router called | last_node=%s | history=%s", last_node, history)

            task_type = initial_input.get("task_type", "approve_budget")

            history      = task.job_data.get("history", [])
            outputs      = task.job_data.get("outputs", {})
            initial_input = task.job_data.get("initial_input", {})
            last_executed = task.job_data.get("last_executed")
            last_executed_batch = task.job_data.get("last_executed_batch")
            final_blueprint = ""
            # if last_executed_batch:
            #     last_node = [node["nodeID"] for node in last_executed_batch]
            # elif last_executed:
            #     last_node = [last_executed["nodeID"]]
            # else:
            #     last_node = []
            last_node = None
            if last_executed and "output" in last_executed and "final_blueprint" in last_executed["output"]:
                final_blueprint = last_executed["output"]["final_blueprint"]
                last_node = last_executed["nodeID"]
                task_type = last_executed["output"]["task_type"]
            
            if task_id := initial_input.get("task_id", task.task_id):
                if task_id not in self.task_registry:
                    self.task_registry[task_id] = {
                        "approval_loops": 0
                    }

            if task_type == "execute_task":
                if not last_node:
                    # Execute audit and finish immediately
                    next_steps = self._handle_audit(task, task_id, initial_input, session_id, model_name)
                    next_nodes = [s["nodeID"] for s in next_steps] if next_steps else []
                    return AgentResult(task_id=task.task_id, job_output=next_steps, job_output_metadata={"next_nodes": next_nodes}, is_error=False)
                else:
                    return AgentResult(task_id=task.task_id, job_output=[], job_output_metadata={"next_nodes": []}, is_error=False)
                    
            elif task_type == "approve_budget":
                next_steps = self._route_budget_approval(task_id, last_node, history, outputs, initial_input, model_name, session_id,communication_type)
                next_nodes = [s["nodeID"] for s in next_steps] if next_steps else []
                
                # Log outgoing request
                for step in next_steps:
                    self._log_to_his(step["nodeID"], {"task_type": "approve_budget", "payload": step["input"]})
                
                return AgentResult(
                    task_id=task.task_id,
                    job_output=next_steps,
                    job_output_metadata={"next_nodes": next_nodes},
                    is_error=False,
                )
            elif task_type == "specialist_output":
                # text = data.get("text")
                # if text:
                #     payload = extract_json(text)
                #     if isinstance(payload, dict):
                #         # Merge payload keys to job_data for easier checks below
                #         for k, v in payload.items():
                #             data[k] = v

                role = data.get("role")
                #if role in ["Financial Accountant", "Financial Controller", "Financial Strategist"]:
                if last_executed["output"]["role"] == "Financial Accountant" and last_executed["output"]["is_balance_report"]:
                    # Step 2: Receive Balance from Accountant & Dispatch to Specialists
                    specialist_output = last_executed["output"]["specialist_output"]
                    self.task_registry[task_id]["available_budget"] = specialist_output.get("available_budget", 0)
                    
                    # Dispatch to both Controller and Strategist
                    #specialist_targets = ["company-financial-controller-agent", "company-financial-strategist-agent"]
                    nav_data = {
                        "task_type": "validate",
                        "aggregated_budget": self.task_registry[task_id]["aggregated_budget"],
                        "available_budget": self.task_registry[task_id]["available_budget"],
                        "problem_statement": self.task_registry[task_id]["problem_statement"],
                        "task_id": task_id,
                        "session_id": session_id,
                        "model_name": model_name,
                        "communication_type": communication_type,
                        "user_request": self.task_registry[task_id]["user_request"]
                    }
                    
                    # for target in specialist_targets:
                    #     if communication_type == "delegate":
                    #         self._log_to_his(target, nav_data)
                    #         self.context.delegator.submit_and_wait(subject_id=target, session_id=session_id, task_id=task.task_id, task_data=nav_data)
                    #     else:
                    #         self._log_to_his(target, nav_data)
                    #         self.context.p2p_manager.send_sync(task=task, subject_id=target, job_data=nav_data, session_id=session_id)
                    self._log_to_his(NODE_CONTROLLER, nav_data)
                    self._log_to_his(NODE_STRATEGIST, nav_data)
                    return AgentResult(
                        task_id=task.task_id,
                        job_output=[{
                            "nodeID": NODE_CONTROLLER,
                            "input": nav_data
                        },
                        {
                            "nodeID": NODE_STRATEGIST,
                            "input": nav_data
                        }],
                        job_output_metadata={"next_nodes": [NODE_CONTROLLER,NODE_STRATEGIST]},
                        is_error=False
                    )

                elif last_executed["output"]["role"] == "Financial Accountant" and last_executed["output"]["is_deduction_report"]:
                    specialist_output = last_executed["output"]["specialist_output"]
                    #update the budget after available budget deducted
                    self.task_registry[task_id]["available_budget"] = specialist_output.get("available_budget", 0)
                    decision_data = last_executed["output"]["decision_data"]
                    # Send success to CoS
                    job_data = {
                        "approval_decision": decision_data,
                        "task_id": task_id,
                        "user_request": self.task_registry[task_id].get("user_request"),
                        "communication_type": communication_type,
                        "final_budget": self.task_registry[task_id]["aggregated_budget"],
                        "model_name": model_name,
                        "session_id": session_id
                    }
                    self._log_to_his(NODE_COS, job_data)

                    # return AgentResult(task_id=task.task_id,
                    #     job_output=NODE_COS,
                    #     job_output_metadata={"next_nodes": [NODE_COS]}, 
                    #     is_error=False)
                    return AgentResult(task_id=task.task_id,
                        job_output=job_data,
                        job_output_metadata={}, 
                        is_error=False)
                elif last_executed["output"]["role"] in ["Financial Controller", "Financial Strategist"]:
                    # Step 3: Accumulate Specialist Output
                    if last_executed["output"]["role"] == "Financial Controller":
                        self.task_registry[task_id]["controller_feedback"] = last_executed["output"]["specialist_output"]
                    elif last_executed["output"]["role"] == "Financial Strategist":
                        self.task_registry[task_id]["strategist_feedback"] = last_executed["output"]["specialist_output"]
                    
                    # If both have replied, evaluate via LLM
                    if self.task_registry[task_id].get("controller_feedback") and self.task_registry[task_id].get("strategist_feedback"):
                        return self._evaluate_approval(task, task_id, session_id, model_name, communication_type)
                    
                    return AgentResult(task_id=task.task_id,
                        job_output=[],
                        job_output_metadata={"next_nodes": []}, 
                        is_error=False)

                return AgentResult(task_id=task.task_id,
                        job_output=[],
                        job_output_metadata={"next_nodes": []}, 
                        is_error=False)

        except Exception as e:
            log.exception(f"Error in Financial Team Lead on_data: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"stage": "on_data", "message": str(e)})

    def _route_budget_approval(self, task_id, last_node, history, outputs, initial_input, model_name, session_id,communication_type):
        # Step 1: Initial call -> Ask Accountant to check balance
        if not last_node:
            log.info("Step 1: dispatching to Accountant for balance check")
            # Determine aggregated_budget and problem_statement
            text = initial_input.get("text")
            agg_budget = initial_input.get("aggregated_budget")
            prob_stmt = initial_input.get("problem_statement")
            
            if text:
                extracted = extract_json(text)
                if isinstance(extracted, dict):
                    if "estimates" in extracted and not agg_budget:
                        agg_budget = extracted
                    elif not prob_stmt:
                        prob_stmt = extracted
                        
            if not prob_stmt:
                prob_stmt = self.task_registry[task_id].get("user_request", initial_input.get("user_request", ""))
            
            # Save into task registry to persist state across loops
            self.task_registry[task_id]["aggregated_budget"] = agg_budget
            self.task_registry[task_id]["problem_statement"] = prob_stmt
            self.task_registry[task_id]["controller_feedback"] = None
            self.task_registry[task_id]["strategist_feedback"] = None

            accountant_data = {
                    "task_type": "check_balance",
                    "task_id": task_id,
                    "session_id": session_id,
                    "model_name": model_name,
                    "communication_type": communication_type,
                    "user_request": self.task_registry[task_id]["user_request"]
                }
            
            # return [{
            #     "nodeID": NODE_ACCOUNTANT,
            #     "input": {**initial_input, "task_type": "check_balance", "aggregated_budget": agg_budget, "problem_statement": prob_stmt}
            # }]
            self._log_to_his(NODE_ACCOUNTANT, accountant_data)

            return [{
                "nodeID": NODE_ACCOUNTANT,
                "input": accountant_data
            }]
            
        # Step 2: After Accountant replies
        # if NODE_ACCOUNTANT in last_node:
        #     accountant_out = outputs.get(NODE_ACCOUNTANT, {})
        #     # Check if this is from check_balance
        #     if accountant_out.get("is_balance_report"):
        #         log.info("Step 2: balance checked, dispatching to Controller and Strategist")
        #         avail_budget = accountant_out.get("specialist_output", {}).get("available_budget", 0)
                
        #         current_agg_budget = self.task_registry[task_id].get("aggregated_budget")
        #         prob_stmt = self.task_registry[task_id].get("problem_statement")
                
        #         nav_data = {
        #             **initial_input,
        #             "task_type": "validate",
        #             "available_budget": avail_budget,
        #             "aggregated_budget": current_agg_budget,
        #             "problem_statement": prob_stmt
        #         }
        #         return [
        #             {"nodeID": NODE_CONTROLLER, "input": nav_data},
        #             {"nodeID": NODE_STRATEGIST, "input": nav_data}
        #         ]
            
        #     # Check if this is from deduct_budget
        #     elif accountant_out.get("is_deduction_report"):
        #         log.info("Step 5: deduction completed, workflow done")
        #         return []

        # # Step 3 & 4: Waiting for or processing Controller & Strategist
        # has_controller = NODE_CONTROLLER in last_node
        # has_strategist = NODE_STRATEGIST in last_node
        
        # if has_controller or has_strategist:
        #     if has_controller and has_strategist:
        #         log.info("Step 4: parallel execution finished, evaluating approval")
        #         return self._evaluate_approval(task_id, initial_input, model_name, session_id, communication_type)
        #     else:
        #         log.info("Step 3: waiting for parallel nodes (Controller & Strategist)")
        #         return []
                
        # return []

    def _evaluate_approval(self, task_id, initial_input, model_name, session_id,communication_type):
        controller_out = self.task_registry[task_id]["controller_feedback"]
        strategist_out = self.task_registry[task_id]["strategist_feedback"]
        # accountant_out = outputs.get(NODE_ACCOUNTANT, {}).get("specialist_output", {})
        
        current_agg_budget = self.task_registry[task_id].get("aggregated_budget")
        avail_budget = self.task_registry[task_id].get("aggregated_budget")
        prob_stmt = self.task_registry[task_id].get("problem_statement", initial_input.get("user_request", ""))

        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            module = dspy.ChainOfThought(FinancialApprovalSignature)
            result = module(
                aggregated_budget=json.dumps(current_agg_budget),
                available_budget=str(avail_budget),
                problem_statement=json.dumps(prob_stmt),
                controller_feedback=json.dumps(controller_out),
                strategist_feedback=json.dumps(strategist_out)
            )
            decision_data = extract_json(result.approval_decision)

        if decision_data.get("approved"):
            log.info("Approval SUCCESS. Dispatching to Accountant for deduction.")
            total_cost = current_agg_budget.get("total", 0) if isinstance(current_agg_budget, dict) else 0
            accountant_data = {
                "task_type": "deduct_budget",
                "amount": total_cost,
                "task_id": task_id,
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": communication_type,
                "user_request":self.task_registry[task_id]["user_request"],
                "decision_data":decision_data
            }
            self._log_to_his(NODE_ACCOUNTANT, accountant_data)
            return [{
                "nodeID": NODE_ACCOUNTANT,
                "input": accountant_data
            }]
        else:
            self.task_registry[task_id]["approval_loops"] += 1
            if self.task_registry[task_id]["approval_loops"] > 3:
                log.warning("Max approval loops reached. Forcing approval.")
                total_cost = current_agg_budget.get("total", 0) if isinstance(current_agg_budget, dict) else 0

                accountant_data = {
                    "task_type": "deduct_budget",
                    "amount": total_cost,
                    "task_id": task_id,
                    "session_id": session_id,
                    "model_name": model_name,
                    "communication_type": communication_type,
                    "user_request":self.task_registry[task_id]["user_request"],
                    "decision_data":decision_data
                }
                self._log_to_his(NODE_ACCOUNTANT, accountant_data)
                return [{
                    "nodeID": NODE_ACCOUNTANT,
                    "input": accountant_data
                }]
            
            log.info("Approval FAILED. Adjusting budget by 20% and looping.")
            if isinstance(current_agg_budget, dict) and "estimates" in current_agg_budget:
                estimates = current_agg_budget["estimates"]
                valid_estimates = [e for e in estimates if e.get("amount", 0) > 0]
                if valid_estimates:
                    target = min(valid_estimates, key=lambda x: x.get("amount", float("inf")))
                    target["amount"] -= (target["amount"] * 0.20)
                    new_total = sum(e.get("amount", 0) for e in estimates)
                    current_agg_budget["buffer"] = new_total * 0.1
                    current_agg_budget["total"] = new_total * 1.1

            self.task_registry[task_id]["aggregated_budget"] = current_agg_budget
            
            # Route back to Controller and Strategist with adjusted budget
            nav_data = {
                **initial_input,
                "task_type": "validate",
                "available_budget": avail_budget,
                "aggregated_budget": current_agg_budget,
                "problem_statement": prob_stmt
            }
            self._log_to_his(NODE_CONTROLLER, nav_data)
            self._log_to_his(NODE_STRATEGIST, nav_data)
            return [
                {"nodeID": NODE_CONTROLLER, "input": nav_data},
                {"nodeID": NODE_STRATEGIST, "input": nav_data}
            ]

    def _handle_audit(self, task, task_id, initial_input, session_id, model_name):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            module = dspy.ChainOfThought(FinancialAuditSignature)
            result = module(total_spent=0, team_outcomes="Project in execution")
            outcome_data = extract_json(result.team_outcome)
        
        log.info(f"Audit completed: {outcome_data}")
        return []

if __name__ == "__main__":
    main(FinancialTeamLeadAgent)
