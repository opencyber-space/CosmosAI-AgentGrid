import json
import logging
import uuid
import time
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "simple-workflow-router-agent": "my-simple-workflow-router-agent",
    "simple-static-workflow:1.0.0:stable": "my-simple-static-workflow",
}

NODE_STATIC_WORKFLOW = "my-simple-static-workflow"

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        communication_type = data.get("communication_type", "delegate")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return communication_type, model_name, session_id

class RouterAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.payload_processor = AgentPayloadProcessor()
        self.task_registry = {}
        
        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost:8080"),
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = self.subject.identity.subject_id
            target_id = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            log.info("Sending HIS log: source_id=%s, destination_id=%s", source_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id, "team": "Workflow Router", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        if not isinstance(task.job_data, dict):
            log.warning(
                "Task %s — job_data is not a dict (%s), skipping.",
                task.task_id, type(task.job_data).__name__,
            )
            return None
        return [task]

    def get_muxer(self):
        return None

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            
            self.task_registry[task.task_id] = {
                "model_name": model_name,
                "session_id": session_id
            }

            history      = task.job_data.get("history", [])
            outputs      = task.job_data.get("outputs", {})
            initial_input = task.job_data.get("initial_input", {})
            last_executed = task.job_data.get("last_executed")
            last_executed_batch = task.job_data.get("last_executed_batch")

            if last_executed_batch:
                last_node = [node["nodeID"] for node in last_executed_batch]
            elif last_executed:
                last_node = [last_executed["nodeID"]]
            else:
                last_node = []

            log.info(
                "Task %s — router called | last_node=%s | history=%s",
                task.task_id, last_node, history,
            )

            if not last_node:
                self._log_to_his(
                    target_id=self.subject.identity.subject_id, 
                    job_data={"task_type": "ROUTER_INCOMING", "last_node": last_node, "history": history, "initial_input":initial_input}
                )
            else:
                self._log_to_his(
                    target_id=self.subject.identity.subject_id, 
                    job_data={"task_type": "ROUTER_INCOMING", "last_node": last_node, "history": history, "last_executed_batch":last_executed_batch, "last_executed": last_executed}
                )

            next_steps = self._route(
                task_id=task.task_id,
                last_node=last_node,
                history=history,
                outputs=outputs,
                initial_input=initial_input,
                model_name=model_name
            )

            next_nodes = [s["nodeID"] for s in next_steps] if next_steps else []
            
            log.info(
                "Task %s — router decision: %s",
                task.task_id,
                next_nodes if next_nodes else "DONE",
            )

            for step in next_steps:
                self._log_to_his(
                    target_id=step["nodeID"],
                    job_data={"task_type": "ROUTER_OUTGOING", "payload": step["input"]}
                )

            return AgentResult(
                task_id=task.task_id,
                job_output=next_steps,
                job_output_metadata={"next_nodes": next_nodes},
                is_error=False,
            )

        except Exception as e:
            log.exception("Task %s — unexpected error in router on_data: %s", task.task_id, e)
            return AgentResult(
                task_id=task.task_id,
                is_error=True,
                error_data={"stage": "on_data", "message": str(e)},
            )

    def _route(
        self,
        task_id: str,
        last_node: List[str],
        history: List[str],
        outputs: dict,
        initial_input: dict,
        model_name: str
    ) -> list:
        # Step 1: First call - no history
        if not last_node:
            log.info("Task %s — Step 1: dispatching to simple-static-workflow", task_id)
            return [{
                "nodeID": NODE_STATIC_WORKFLOW,
                "input":  initial_input,
            }]

        # Step 2: After simple-static-workflow - done
        if NODE_STATIC_WORKFLOW in last_node:
            log.info("Task %s — Step 2: simple-static-workflow complete, returning to caller", task_id)
            return []

        log.warning(
            "Task %s — router reached unknown state | last_node=%s history=%s",
            task_id, last_node, history,
        )
        return []

if __name__ == "__main__":
    main(RouterAgent)
