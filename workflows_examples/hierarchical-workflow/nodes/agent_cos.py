import logging
import uuid
import json
import time
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

NODE_ID_MAPPING = {
    "agent-workflow-developer-team-lead": "my-company-developer-team-lead-agent",
    "agent-workflow-arch-design-team-lead": "my-company-arch-design-team-lead-agent",
    "agent-workflow-financial-team-lead": "my-company-financial-team-lead-agent",
    "agent-workflow-marketing-team-lead": "my-company-marketing-team-lead-agent",
    "agent-workflow-testing-team-lead": "my-company-testing-team-lead-agent",
    "agent-workflow-ceo": "my-ceo-agent",
    "agent-workflow-cos": "my-chief-of-staff-agent"
}

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

# --- Mappings ---

NODE_TO_AGENT_MAPPING = {
    "my-ceo-agent": "agent-workflow-ceo",
    "my-chief-of-staff-agent": "agent-workflow-cos",
    "my-financial-workflow": "agent-workflow-financial-team-lead",
    "my-marketing-workflow": "agent-workflow-marketing-team-lead",
    "my-testing-workflow": "agent-workflow-testing-team-lead",
    "my-developer-workflow": "agent-workflow-developer-team-lead",
    "my-architecture-workflow": "agent-workflow-arch-design-team-lead"
}

AGENT_TO_NODE_MAPPING = {
    "agent-workflow-ceo": "my-ceo-agent",
    "agent-workflow-cos": "my-chief-of-staff-agent",
    "agent-workflow-financial-team-lead": "my-financial-workflow",
    "agent-workflow-marketing-team-lead": "my-marketing-workflow",
    "agent-workflow-testing-team-lead": "my-testing-workflow",
    "agent-workflow-developer-team-lead": "my-developer-workflow",
    "agent-workflow-arch-design-team-lead": "my-architecture-workflow"
}

# --- 2. The CoS Agent ---

class CoSAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        
        # Central Task Registry (For local fallback/session tracking)
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
            self.all_team_leads = [
                "company-marketing-team-lead",
                "company-arch-design-team-lead",
                "company-developer-team-lead",
                "company-testing-team-lead",
                "company-financial-team-lead"
            ]
            
        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )

    def _get_lm_context(self, model_name, session_id):
        return dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=session_id))

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        # Router always processes — history can be empty on first call
        if not isinstance(task.job_data, dict):
            log.warning("Task %s — job_data is not a dict, skipping.", task.task_id)
            return None
        return [task]

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            mapped_target = NODE_TO_AGENT_MAPPING.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": mapped_target, "team": "COS Team", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def _get_context_data(self, outputs, initial_input):
        # 1. Look for CEO refined output
        ceo_out = outputs.get("my-ceo-agent", {}) if "my-ceo-agent" in outputs else initial_input
        problem_statement = ceo_out.get("problem_statement")
        
        if not problem_statement:
            # Fallback to extracting from text
            text = ceo_out.get("text") or initial_input.get("text") or ""
            extracted = extract_json(text) if text else None
            problem_statement = extracted if isinstance(extracted, dict) else (text or ceo_out.get("problem_statement"))
            
        user_request = ceo_out.get("user_request") or initial_input.get("user_request") or initial_input.get("text") or ""
        session_id = ceo_out.get("session_id") or initial_input.get("session_id") or str(uuid.uuid4())
        model_name = ceo_out.get("model_name") or initial_input.get("model_name") or "gpt-4o"
        task_id = ceo_out.get("task_id") or initial_input.get("task_id") or ""
        priority = ceo_out.get("priority") or (problem_statement.get("priority") if isinstance(problem_statement, dict) else None) or "Fast"
        
        return problem_statement, user_request, session_id, model_name, task_id, priority

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            if not isinstance(data, dict):
                data = {}
            history = data.get("history", [])
            outputs = data.get("outputs", {})
            initial_input = data.get("initial_input", {})
            if not isinstance(initial_input, dict):
                initial_input = {}
            if not initial_input and "task_type" in data:
                initial_input = data
                
            last_executed = data.get("last_executed")
            last_executed_batch = data.get("last_executed_batch")

            final_blueprint = ""
            last_node = None
            last_nodes = None
            if len(last_executed_batch)>1:
                # Note: use last_executed_batch when task is executed in parallel from this agent
                #task_type = last_executed["output"]["task_type"]
                last_node = [node["nodeID"] for node in last_executed_batch]
            elif last_executed and "output" in last_executed:
                if "final_blueprint" in last_executed["output"]:
                    final_blueprint = last_executed["output"]["final_blueprint"]
                #elif last_executed["output"]["task_type"] == "specialist_output":
                last_node = last_executed["nodeID"]
                #task_type = last_executed["output"]["task_type"]
                
            log.info("CoS Router called | last_node=%s | history=%s", last_node, history)

            # Get project context parameters from history/outputs/inputs
            problem_statement, user_request, session_id, model_name, task_id, priority = self._get_context_data(outputs, initial_input)

            # Log incoming request
            self._log_to_his(
                target_id=self.subject.identity.subject_id if hasattr(self.subject.identity, 'subject_id') else "agent-workflow-cos",
                job_data={"task_type": "ROUTER_INCOMING", "last_node": last_node, "history": history,"initial_input":initial_input,"last_executed_batch":last_executed_batch,"last_executed":last_executed,"outputs":outputs}
            )

            # Pure Routing Logic mapped directly to workflow stages:
            next_steps, final_job_output = self._route(
                task_id=task_id,
                last_node=last_node,
                outputs=outputs,
                problem_statement=problem_statement,
                user_request=user_request,
                session_id=session_id,
                model_name=model_name,
                priority=priority
            )

            next_nodes = [s["nodeID"] for s in next_steps] if next_steps else []
            log.info("CoS Router decision: %s", next_nodes if next_nodes else "DONE")

            # Log outgoing requests
            for step in next_steps:
                self._log_to_his(target_id=step["nodeID"], job_data={"task_type": step["input"]["task_type"], "payload": step["input"]})

            # send final outcome to HIS to CEO
            if final_job_output:
                self._log_to_his(target_id="my-ceo-agent", job_data={"task_type":"final_outcome","payload": final_job_output})

            return AgentResult(
                task_id=task.task_id,
                job_output=final_job_output if final_job_output is not None else next_steps,
                job_output_metadata={"next_nodes": next_nodes},
                is_error=False
            )

        except Exception as e:
            log.exception(f"Error in CoS Agent Router: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _route(self, task_id, last_node, outputs, problem_statement, user_request, session_id, model_name, priority):
        # ── State 1: Start/CEO Refined Problem Statement received ──
        # CEO is either the last executed node, or no workflow history exists yet.
        is_first_call = not last_node or "my-ceo-agent" in last_node
        
        # Check if we have gathered estimates yet
        estimation_nodes = ["my-marketing-workflow", "my-architecture-workflow", "my-developer-workflow", "my-testing-workflow"]
        has_estimates = all(node in outputs for node in estimation_nodes)
        
        if is_first_call:
            log.info("CoS Stage 1: Initiating budget estimation across 4 operating teams in parallel.")
            next_steps = []
            for node_id in estimation_nodes:
                next_steps.append({
                    "nodeID": node_id,
                    "input": {
                        "task_type": "estimate_budget",
                        "text": json.dumps(problem_statement),
                        "problem_statement": problem_statement,
                        "task_id": task_id,
                        "user_request": user_request,
                        "priority": priority,
                        "model_name": model_name,
                        "communication_type": "workflow",
                        "session_id": session_id
                    }
                })
            return next_steps, None

        # ── State 2: Estimates collected, request financial approval ──
        # Triggered when all 4 estimation nodes are complete, and finance has not been called yet.
        if has_estimates and "my-financial-workflow" not in outputs:
            log.info("CoS Stage 2: Collecting budgets and requesting financial approval.")
            estimates = []
            for node_id in estimation_nodes:
                out_val = outputs.get(node_id, {})
                est = out_val.get("budget_estimate")
                if est:
                    estimates.append(est)
            
            total = sum(e.get("amount", 0.0) for e in estimates)
            total_budget = total * 1.1 # Add buffer
            aggregated = {
                "estimates": estimates,
                "buffer": total * 0.1,
                "total": total_budget
            }
            
            return [{
                "nodeID": "my-financial-workflow",
                "input": {
                    "task_type": "approve_budget",
                    "text": json.dumps(aggregated),
                    "aggregated_budget": aggregated,
                    "task_id": task_id,
                    "user_request": user_request,
                    "priority": priority,
                    "model_name": model_name,
                    "communication_type": "workflow",
                    "session_id": session_id
                }
            }], None

        # ── State 3: Financial approval received, trigger execution phase ──
        # Triggered when my-financial-workflow finishes execution.
        if "my-financial-workflow" in last_node:
            finance_out = outputs.get("my-financial-workflow", {})
            decision = finance_out.get("approval_decision", {})
            
            if not decision.get("approved"):
                log.error("Financial approval rejected!")
                raise Exception("Financial approval rejected by Finance team.")
                
            log.info("CoS Stage 3: Financial approval granted! Triggering execute_task in parallel.")
            
            # Fetch budget estimates from outputs to extract specific deliverables
            estimates_dict = {}
            for node_id in estimation_nodes:
                out_val = outputs.get(node_id, {})
                est = out_val.get("budget_estimate") or {}
                team_name = est.get("team_name")
                if team_name:
                    estimates_dict[team_name] = est

            # Mapping for deliverables lookup
            team_mapping = {
                "my-architecture-workflow": "Arch & Design Team",
                "my-developer-workflow": "Frontend and Backend Development Team",
                "my-testing-workflow": "Testing Team",
                "my-marketing-workflow": "Marketing Team"
            }

            next_steps = []
            for node_id in estimation_nodes:
                team_name = team_mapping.get(node_id)
                deliverables = estimates_dict.get(team_name, {}).get("deliverables", []) if team_name else []
                
                next_steps.append({
                    "nodeID": node_id,
                    "input": {
                        "task_type": "execute_task",
                        "text": json.dumps(problem_statement),
                        "problem_statement": problem_statement,
                        "task_id": task_id,
                        "user_request": user_request,
                        "priority": priority,
                        "model_name": model_name,
                        "communication_type": "workflow",
                        "session_id": session_id,
                        "deliverables": deliverables
                    }
                })
            return next_steps, None

        # ── State 4: Architecture finished execution -> Route to Developer & Testing ──
        if "my-architecture-workflow" in last_node:
            arch_out = outputs.get("my-architecture-workflow", {})
            # Ensure it is the final execution outcome and not a budget estimate
            if "team_outcome" in arch_out or arch_out.get("task_type") == "team_outcome":
                arch_outcome = arch_out.get("team_outcome")
                log.info("CoS Stage 4: Architecture blueprint finished. Routing to Developer and Testing workflows.")
                return [
                    {
                        "nodeID": "my-developer-workflow",
                        "input": {
                            "task_type": "process_artifact",
                            "artifact_data": arch_outcome,
                            "problem_statement": problem_statement,
                            "task_id": task_id,
                            "session_id": session_id,
                            "model_name": model_name,
                            "communication_type": "workflow",
                            "user_request": user_request
                        }
                    },
                    {
                        "nodeID": "my-testing-workflow",
                        "input": {
                            "task_type": "process_artifact",
                            "artifact_data": arch_outcome,
                            "problem_statement": problem_statement,
                            "task_id": task_id,
                            "session_id": session_id,
                            "model_name": model_name,
                            "communication_type": "workflow",
                            "user_request": user_request
                        }
                    }
                ], None

        # ── State 5: Developer finished execution -> Route to Testing ──
        if "my-developer-workflow" in last_node:
            dev_out = outputs.get("my-developer-workflow", {})
            # Ensure it is the final execution outcome and not a budget estimate
            if "team_outcome" in dev_out or dev_out.get("task_type") == "team_outcome":
                dev_outcome = dev_out.get("team_outcome")
                log.info("CoS Stage 5: Developer code finished. Routing to Testing workflow.")
                return [
                    {
                        "nodeID": "my-testing-workflow",
                        "input": {
                            "task_type": "process_artifact",
                            "artifact_data": dev_outcome,
                            "problem_statement": problem_statement,
                            "task_id": task_id,
                            "session_id": session_id,
                            "model_name": model_name,
                            "communication_type": "workflow",
                            "user_request": user_request
                        }
                    }
                ], None

        # ── State 6: All done -> Summarize & finalize ──
        # Check if all 4 functional workflows have execution outcomes completed
        marketing_out = outputs.get("my-marketing-workflow", {})
        arch_out = outputs.get("my-architecture-workflow", {})
        dev_out = outputs.get("my-developer-workflow", {})
        test_out = outputs.get("my-testing-workflow", {})

        is_marketing_done = "team_outcome" in marketing_out or marketing_out.get("task_type") == "team_outcome"
        is_arch_done = "team_outcome" in arch_out or arch_out.get("task_type") == "team_outcome"
        is_dev_done = "team_outcome" in dev_out or dev_out.get("task_type") == "team_outcome"
        is_test_done = "team_outcome" in test_out or test_out.get("task_type") == "team_outcome"

        if is_marketing_done and is_arch_done and is_dev_done and is_test_done:
            log.info("CoS Stage 6: All operational outcomes collected. Compiling final report.")
            
            # Extract team outcome data dictionary from each workflow's output
            outcomes_list = []
            for out in [marketing_out, arch_out, dev_out, test_out]:
                outcome_data = out.get("team_outcome")
                if outcome_data:
                    outcomes_list.append(outcome_data)

            # Sum budget aggregate
            finance_out = outputs.get("my-financial-workflow", {})
            agg_budget = finance_out.get("aggregated_budget", {})
            total_spent = agg_budget.get("total", 0.0)

            # Use DSPy to summarize the outcomes
            with self._get_lm_context(model_name, session_id):
                summarizer = dspy.ChainOfThought(CoSOutcomeSummarizerSignature)
                summary = summarizer(
                    team_outcomes=json.dumps(outcomes_list, indent=2),
                    total_spent=str(total_spent)
                )
                final_report = extract_json(summary.final_report)

            # Inject detailed Outcomes for downstream HIS parsing or references
            final_report["team_outcomes"] = outcomes_list

            job_data = {
                "communication_type": "workflow",
                "task_id": task_id,
                "final_project_outcome": final_report,
                "text": json.dumps(final_report)
            }
            # Return empty list for next_steps to terminate the sub-workflow,
            # and final job_data to return to the parent workflow.
            return [], job_data

        log.info("CoS: Intermediate execution completed. Waiting for remaining active paths to finish.")
        return [], None

if __name__ == "__main__":
    main(CoSAgent)
