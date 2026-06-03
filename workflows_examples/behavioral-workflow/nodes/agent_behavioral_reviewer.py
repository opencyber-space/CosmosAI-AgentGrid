import time
import logging
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from agents_sdk.core.agents_functions_graph import AgentsFunctionsGraph, AgentsFunctionsGraphError

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "agent-behavioral-code-creator": "my-behavioral-code-creator",
    "agent-behavioral-reviewer": "my-behavioral-reviewer",
}

NODE_CODE_CREATOR = "my-behavioral-code-creator"
NODE_REVIEWER = "my-behavioral-reviewer"
GRAPH_URI = "code_analysis_pipeline_3:1.0-stable"

class BehavioralReviewerAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.graph = AgentsFunctionsGraph()
        
        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Review Team", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        job = task.job_data
        if not job.get("code"):
            if "final_project_outcome" not in job:
                log.warning("Task %s missing 'code' in job_data — skipping.", task.task_id)
                return None
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            job = task.job_data
            if "final_project_outcome" in job:
                log.info(f"Received Final Project Outcome! Task {task.task_id} successfully completed.")
                return AgentResult(task_id=task.task_id, is_error=False, job_output=job, job_output_metadata={})

            # Log incoming request
            self._log_to_his(
                target_id=NODE_REVIEWER, # Self is target of incoming
                job_data={"task_type": "INCOMING_TASK", "payload": job}
            )

            input_data = {
                "code": job["code"],
                "function_name": job.get("function_name", ""),
                "description": job.get("description", ""),
            }

            log.info(f"Executing graph {GRAPH_URI} for code review")
            result = self.graph.execute_graph(
                graph_uri=GRAPH_URI,
                input_data=input_data,
            )

            job_output = result

            # Log outgoing result
            self._log_to_his(
                target_id="USER", # Terminal node
                job_data={"task_type": "OUTGOING_RESULT", "payload": job_output}
            )

            return AgentResult(
                task_id=task.task_id,
                job_output=job_output,
                job_output_metadata={"graph_uri": GRAPH_URI},
                is_error=False,
            )

        except AgentsFunctionsGraphError as e:
            log.exception("Graph call failed (task_id=%s): %s", task.task_id, e)
            return AgentResult(
                task_id=task.task_id,
                is_error=True,
                error_data={"stage": "on_data", "message": str(e)},
            )
        except Exception as e:
            log.exception("Task %s — unexpected error in on_data: %s", task.task_id, e)
            return AgentResult(
                task_id=task.task_id,
                is_error=True,
                error_data={"stage": "on_data", "message": str(e)},
            )

if __name__ == "__main__":
    main(BehavioralReviewerAgent)
