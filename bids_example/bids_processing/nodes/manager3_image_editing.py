import logging
import time
from agents_sdk.core.his import HisClient
import uuid
import json
import dspy
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main
from agents_sdk.core.known_agents import KnownAgents
import os
from openarcade_bidding_pysdk.client import OpenarcadeClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json
from utils.bid_utils import normalize_bid
from utils.image_models import MinioStore, image_facts, minio_config

log = logging.getLogger(__name__)

# Reserved key inside task_registry (sits alongside session_id keys).
BID_JOB_INDEX = "bid_job_index"

# --- 1. Signatures ---

class QualificationSignature(dspy.Signature):
    """
    ### ROLE
    You are Manager for Image Editing & Processing.

    ### TASK
    Assess whether the incoming job request falls within Image Enhancement, Resolution Scaling, Object Segmentation, Background Removal, or Metadata/Watermarking.
    If the job is too broad, explicitly identify the portion of the job that is out of scope.

    ### OUTPUT
    Output EXACTLY a JSON block: {"is_qualified": bool, "reasoning": "string", "out_of_scope": "string"}
    """
    job_description = dspy.InputField(desc="Incoming job request description")
    domain_fields_of_interest = dspy.InputField(desc="Domain fields of interest for Image Editing")
    qualification_result = dspy.OutputField(desc='JSON block: {"is_qualified": bool, "reasoning": "string", "out_of_scope": "string"}')

class TaskBreakdownSignature(dspy.Signature):
    """
    ### ROLE
    You are Manager 3 for Image Editing & Processing.

    ### TASK
    Decompose the qualified image editing job into sub-tasks for available subordinate agents (image enhancer, object segmenter, metadata watermarker).

    ### OUTPUT
    Output EXACTLY a JSON block mapping subordinate agent ID to sub-task instructions:
    {"subtask_assignments": [{"agent_id": "string", "instruction": "string"}]}
    """
    job_description = dspy.InputField(desc="Image editing job description")
    subordinates_info = dspy.InputField(desc="List of available subordinate agents and their capabilities")
    breakdown_result = dspy.OutputField(desc='JSON block with subtask_assignments')

class BidAggregationSignature(dspy.Signature):
    """
    ### ROLE
    You are Manager 3 for Image Editing & Processing.

    ### TASK
    Aggregate assessment estimates and constraints received from image editing sub-agents into a consolidated bid proposal.

    ### OUTPUT
    Output EXACTLY a JSON block: {"manager_id": "string", "total_estimated_tokens": int, "required_compute": "low|moderate|high", "testing_env": "string", "proposed_timeline": "fast|medium|slow", "aggregated_constraints": ["string"], "bid_status": "submitted"}

    ### CONSTRAINT
    "required_compute" MUST be exactly one of the lowercase strings "low", "moderate" or "high"
    (the highest tier reported by any sub-agent).
    "proposed_timeline" MUST be exactly one of the lowercase strings "fast", "medium" or "slow"
    (the slowest pace reported by any sub-agent).
    Emit only those single words - no prose, no durations such as "1-2 business days", no
    qualifiers. Put any reasoning into "aggregated_constraints" instead. "required_compute" is
    consumed by the bid evaluator as a numeric tier, so any other text makes the bid unscoreable.
    """
    job_description = dspy.InputField(desc="Image editing job description")
    subagent_assessments = dspy.InputField(desc="Sub-agent constraint and estimation responses")
    bid_result = dspy.OutputField(desc="JSON block containing aggregated bid metrics")

class ExecutionAggregationSignature(dspy.Signature):
    """
    ### ROLE
    You are Manager 3 for Image Editing & Processing.

    ### TASK
    Synthesize implementation results from all image editing sub-agents into a final Image Editing Delivery Report.
    `measured_facts` holds facts measured in code from the original and the delivered image, and
    `criteria_checks` compares them with the job's acceptance criteria. Take every size, DPI, EXIF,
    luminance and pass/fail statement from those two inputs only - never from the sub-agents' own
    claims. Report any failed check plainly in "media_summary".

    ### OUTPUT
    Output EXACTLY a JSON block: {"media_summary": "string", "images_processed": ["string"], "watermark_status": "string", "overall_status": "completed"}
    """
    job_description = dspy.InputField(desc="Image editing job description")
    subagent_results = dspy.InputField(desc="Execution results from image editing sub-agents")
    measured_facts = dspy.InputField(desc="Facts measured in code from the original and delivered images - ground truth")
    criteria_checks = dspy.InputField(desc="Measured facts compared with the acceptance criteria")
    final_report = dspy.OutputField(desc="JSON block of final image editing delivery")

# --- 2. Manager Agent Node ---

class Manager3ImageEditingAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.default_model = "aios:qwen3-1-7b-vllm-block"
        try:
            if self.subject and hasattr(self.subject, 'integrations') and self.subject.integrations and self.subject.integrations.models:
                self.default_model = self.subject.integrations.models[0].llm_block_id
        except Exception:
            pass
        self.task_registry = {}
        self.store = None

        # Discover image editing sub-agents
        try:
            known_agents = KnownAgents(default_compact=False)
            known_agents.query_and_add(query={
                "metadata.subject_search_tags": "image-editing-subordinates"
            })
            self.subordinates = [agent.id for agent in known_agents.list_all()]
            log.info("Manager 3 discovered image editing subordinates: %s", self.subordinates)
        except Exception as e:
            log.error(f"Failed to discover image editing subordinates: {e}")
            self.subordinates = []

    def _get_lm_context(self, model_name, session_id):
        return dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=session_id))

    def _init_task(self, session_id, task_id, user_request=None):
        """Ensure task_registry[session_id][task_id] exists and return it."""
        session = self.task_registry.setdefault(session_id, {})
        if task_id not in session:
            session[task_id] = {
                "user_request": user_request,
                "assess_responses": {},
                "implement_responses": {},
                "subtasks": []
            }
        return session[task_id]

    def _task_entry(self, session_id, task_id):
        """task_registry[session_id][task_id], created on demand."""
        return self.task_registry.setdefault(session_id, {}).setdefault(task_id, {})


    def _index_bid_job(self, bid_job_id, session_id, task_id):
        """Remember which session/task a bid_job belongs to.

        A bid_winner notification carries only bid_job_id - no session_id and no
        task_id - so without this index the winner hop would mint a fresh session
        and lose everything cached during the bid phase.
        """
        if not bid_job_id:
            return
        index = self.task_registry.setdefault(BID_JOB_INDEX, {})
        index[bid_job_id] = {"session_id": session_id, "task_id": task_id}

    def _lookup_bid_job(self, bid_job_id):
        """(session_id, task_id) recorded for this bid_job, or (None, None)."""
        if not bid_job_id:
            return None, None
        record = self.task_registry.get(BID_JOB_INDEX, {}).get(bid_job_id) or {}
        return record.get("session_id"), record.get("task_id")

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id, "team": getattr(self, "name", "Agent Team"), "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def _submit_to_openarcade(self, bid_job_id, bid_data):
        if bid_job_id:
            try:
                base_url = os.environ.get("OPENARCADE_BIDDING_URL", "http://localhost:5000")
                client = OpenarcadeClient(base_url=base_url)
                agent_name = getattr(self.subject.identity, "subject_id", None) or os.environ.get("SUBJECT_ID")
                if not agent_name:
                    raise ValueError("Unable to resolve subject_id for bid submission")
                client.submit_bid(
                    bid_job_id=bid_job_id,
                    bid_subject_id=agent_name,
                    bid_data=bid_data
                )
                log.info(f"Successfully submitted bid for {bid_job_id} using SDK.")
            except Exception as e:
                log.error(f"Failed to submit bid via SDK: {e}")
        else:
            log.warning("No bid_job_id found in task payload, skipping SDK submission.")

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} in Manager3ImageEditing")
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:

        try:
            # Log incoming request
            self._log_to_his(
                target_id=getattr(self.subject.identity, 'subject_id', 'unknown'),
                job_data={"task_type": "INCOMING_TASK", "payload": task.job_data}
            )
            data = task.job_data
            event_type = data.get("type", data.get("event_type", "bid_request"))
            task_id = data.get("task_id", task.task_id)
            bid_job_id = data.get("bid_job_id") or data.get("bid_job", {}).get("bid_job_id")
            user_request = data.get("bid_job", {}).get("bid_job_description", {}).get("text", data.get("text", ""))
            communication_type = data.get("communication_type", "p2p")
            model_name = data.get("model_name", self.default_model)
            session_id = data.get("session_id", str(uuid.uuid4()))

            # A bid_winner notification is deliberately lean: it carries neither the
            # bid_job nor the originating task_id (see delegate-system docs 5.3). Recover
            # the context cached during bid_request so sub-agents get the real job spec.
            if event_type == "bid_winner":
                prior_session_id, prior_task_id = self._lookup_bid_job(bid_job_id)
                if prior_task_id:
                    task_id = prior_task_id
                    # Reuse the bid-phase session so sub-agents can still read the
                    # assessments they stored under it.
                    session_id = prior_session_id or session_id
                    user_request = self._task_entry(session_id, task_id).get("user_request") or user_request
                else:
                    log.warning(f"No cached bid_request context for bid_job_id {bid_job_id}")

            self._init_task(session_id, task_id, user_request)
            if bid_job_id:
                self._task_entry(session_id, task_id)["bid_job_id"] = bid_job_id
                self._index_bid_job(bid_job_id, session_id, task_id)
            # Keep the structured job spec (input_image, acceptance criteria) from bid_request;
            # the bid_winner hop does not carry it, so the implementation phase reads it back.
            job_spec = data.get("bid_job", {}).get("bid_job_description")
            if isinstance(job_spec, dict) and job_spec:
                self._task_entry(session_id, task_id)["bid_job_description"] = job_spec

            if event_type == "bid_request":
                return self._handle_bid_request(task, task_id, user_request, session_id, model_name, communication_type)
            elif event_type in ("bid_winner", "bid_response"):
                return self._handle_bid_response(task, task_id, user_request, session_id, model_name, communication_type)
            else:
                log.warning(f"Unknown event_type {event_type} in Manager 3")
                self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "skipped", "reason": f"unhandled event_type: {event_type}"}}); return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Manager 3 Image Editing Agent: {e}")
            self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "error", "message": str(e)}}); return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _handle_bid_request(self, task, task_id, job_desc, session_id, model_name, comm_type):
        with self._get_lm_context(model_name, session_id):
            qual_module = dspy.ChainOfThought(QualificationSignature)
            domain_interest = "Image Enhancement, Resolution Upscaling, Color Correction, Object Segmentation, Background Removal, Masking, EXIF Metadata, Watermarking"
            qual_res = qual_module(job_description=job_desc, domain_fields_of_interest=domain_interest)
            qual_data = extract_json(qual_res.qualification_result) or {}

            if isinstance(qual_data, dict) and not qual_data.get("is_qualified", True):
                log.info(f"Manager 3 declined job {task_id}: {qual_data.get('reasoning')}")
                bid_data = {
                    "status": "declined",
                    "reason": qual_data.get("reasoning"),
                    "total_estimated_tokens": 9007199254740991,
                    "required_compute": 9007199254740991,
                    "bid_status": "declined"
                }
                bid_job_id = task.job_data.get("bid_job_id")
                self._submit_to_openarcade(bid_job_id, bid_data)
                self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": bid_data})
                return AgentResult(task_id=task_id, job_output=bid_data)

            breakdown_module = dspy.ChainOfThought(TaskBreakdownSignature)
            breakdown_res = breakdown_module(job_description=job_desc, subordinates_info=json.dumps(self.subordinates))
            breakdown_data = extract_json(breakdown_res.breakdown_result) or {}
            assignments = breakdown_data.get("subtask_assignments", []) if isinstance(breakdown_data, dict) else []

        assess_responses = {}
        subtask_instructions = {}
        for sub_id in self.subordinates:
            instruction = f"Assess image editing sub-task for {sub_id}"
            for assign in assignments:
                if assign.get("agent_id") == sub_id:
                    instruction = assign.get("instruction", instruction)
                    subtask_instructions[sub_id] = instruction

            sub_job_data = {
                "event_type": "assess",
                "text": instruction,
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": comm_type,
                "task_id": task_id
            }

            if comm_type == "p2p":
                res = self.context.p2p_manager.send_and_wait_sync(task_id=task_id, subject_id=sub_id, task_data=sub_job_data)
                assess_responses[sub_id] = res.get("data", {})
            elif comm_type == "delegate":
                res = self.context.delegator.submit_and_wait(subject_id=sub_id, session_id=session_id, task_id=task_id, task_data=sub_job_data)
                assess_responses[sub_id] = res
            else:
                self.context.direct.submit(to=sub_id, session_id=session_id, task=task, job_data=sub_job_data)
                assess_responses[sub_id] = {"status": "dispatched"}

        self._task_entry(session_id, task_id)["assess_responses"] = assess_responses
        self._task_entry(session_id, task_id)["subtask_instructions"] = subtask_instructions

        with self._get_lm_context(model_name, session_id):
            agg_module = dspy.ChainOfThought(BidAggregationSignature)
            agg_res = agg_module(job_description=job_desc, subagent_assessments=json.dumps(assess_responses))
            bid_data = extract_json(agg_res.bid_result) or {}
            # The evaluator scores these fields, so they are settled in code rather than
            # left to however the model happened to word (or omit) them.
            bid_data = normalize_bid(bid_data, assess_responses, getattr(self.subject.identity, "subject_id", None))

        self._task_entry(session_id, task_id)["bid_data"] = bid_data
        self._task_entry(session_id, task_id)["qual_data"] = qual_data
        self._task_entry(session_id, task_id)["breakdown_data"] = breakdown_data
        
        # OpenArcade SDK Submission
        bid_job_id = task.job_data.get("bid_job_id")
        self._submit_to_openarcade(bid_job_id, bid_data)

        self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": bid_data}); return AgentResult(task_id=task_id, job_output=bid_data)

    # Stage order of the editing chain: enhance first, segment the enhanced image, publish last.
    STAGE_KEYWORDS = (("enhancer",), ("segmenter",), ("watermark", "metadata"))

    def _pipeline_order(self, subordinates):
        def stage(sub_id):
            for index, words in enumerate(self.STAGE_KEYWORDS):
                if any(word in sub_id for word in words):
                    return index
            return len(self.STAGE_KEYWORDS)
        return sorted(subordinates, key=stage)

    def _store(self):
        # Connected lazily so an unreachable MinIO does not stop the agent from starting.
        if self.store is None:
            self.store = MinioStore(minio_config(self.subject))
        return self.store

    @staticmethod
    def _job_output(response):
        """The sub-agent's job_output from a p2p reply ({data: {job_output}}) or a bare result."""
        if not isinstance(response, dict):
            return {}
        if isinstance(response.get("job_output"), dict):
            return response["job_output"]
        return response

    def _measure_images(self, original, delivered, artifacts, criteria):
        """Facts measured in code from the stored images, and their comparison with the criteria."""
        store = self._store()
        facts = {"original": image_facts(store.get_bytes(original))}
        facts["delivered"] = image_facts(store.get_bytes(delivered)) if delivered != original else None
        for name, ref in artifacts.items():
            facts[name] = image_facts(store.get_bytes(ref))

        checks = {}
        out, before = facts["delivered"], facts["original"]
        if out is None:
            checks["image_edited"] = {"pass": False, "detail": "no stage produced a new image"}
            return facts, checks
        if "width" in criteria or "height" in criteria:
            want = [criteria.get("width"), criteria.get("height")]
            got = [out["width"], out["height"]]
            checks["dimensions"] = {"required": want, "actual": got, "pass": got == want}
        if "dpi" in criteria:
            checks["dpi"] = {"required": criteria["dpi"], "actual": out["dpi"],
                             "pass": bool(out["dpi"]) and all(d == criteria["dpi"] for d in out["dpi"])}
        if criteria.get("luminance_must_increase"):
            checks["exposure_corrected"] = {"original": before["avg_luminance"], "actual": out["avg_luminance"],
                                            "pass": out["avg_luminance"] > before["avg_luminance"]}
        if criteria.get("highlights_must_not_increase"):
            checks["highlights_not_clipped_further"] = {"original_pct": before["clipped_highlights_pct"],
                                                        "actual_pct": out["clipped_highlights_pct"],
                                                        "pass": out["clipped_highlights_pct"] <= before["clipped_highlights_pct"]}
        if "max_clipped_highlights_pct" in criteria:
            limit = criteria["max_clipped_highlights_pct"]
            checks["highlights_unclipped"] = {"limit_pct": limit, "actual_pct": out["clipped_highlights_pct"],
                                              "pass": out["clipped_highlights_pct"] <= limit}
        if criteria.get("remove_exif_tags"):
            left = [tag for tag in criteria["remove_exif_tags"] if tag in out["exif_tags"]]
            checks["exif_stripped"] = {"must_remove": criteria["remove_exif_tags"], "still_present": left, "pass": not left}
        if criteria.get("keep_exif_tags"):
            missing = [tag for tag in criteria["keep_exif_tags"] if tag not in out["exif_tags"]]
            checks["exif_kept"] = {"must_keep": criteria["keep_exif_tags"], "missing": missing, "pass": not missing}
        if criteria.get("keep_icc_profile"):
            checks["icc_profile_kept"] = {"pass": out["icc_profile"]}
        return facts, checks

    def _handle_bid_response(self, task, task_id, job_desc, session_id, model_name, comm_type):
        log.info(f"Manager 3 won bid for task {task_id}. Dispatching implementation to sub-agents...")
        entry = self._task_entry(session_id, task_id)
        job_spec = entry.get("bid_job_description") or {}
        criteria = job_spec.get("acceptance_criteria") or {}
        instructions = entry.get("subtask_instructions") or {}
        original = job_spec.get("input_image") or {}
        if not original.get("object"):
            message = "job has no input_image (MinIO bucket/object) to edit"
            log.error(f"Manager 3 cannot implement task {task_id}: {message}")
            self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "error", "message": message}})
            return AgentResult(task_id=task_id, is_error=True, error_data={"message": message})
        original = {k: original[k] for k in ("bucket", "object", "url") if k in original}

        # The sub-agents form a chain on one image: each stage that produces `output_image`
        # hands it to the next, while side artifacts (cutout, mask) are collected.
        current = original
        artifacts = {}
        implement_responses = {}
        for sub_id in self._pipeline_order(self.subordinates):
            sub_job_data = {
                "event_type": "implement",
                "text": f"Implement image editing sub-task for {job_desc}",
                "subtask_instruction": instructions.get(sub_id, ""),
                "input_image": current,
                "original_image": original,
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": comm_type,
                "task_id": task_id
            }

            if comm_type == "p2p":
                res = self.context.p2p_manager.send_and_wait_sync(task_id=task_id, subject_id=sub_id, task_data=sub_job_data)
                implement_responses[sub_id] = res.get("data", {})
            elif comm_type == "delegate":
                res = self.context.delegator.submit_and_wait(subject_id=sub_id, session_id=session_id, task_id=task_id, task_data=sub_job_data)
                implement_responses[sub_id] = res
            else:
                self.context.direct.submit(to=sub_id, session_id=session_id, task=task, job_data=sub_job_data)
                implement_responses[sub_id] = {"status": "dispatched"}

            output = self._job_output(implement_responses[sub_id])
            if isinstance(output.get("output_image"), dict) and output["output_image"].get("object"):
                current = output["output_image"]
                log.info(f"Stage {sub_id} produced {current.get('object')}")
            else:
                log.warning(f"Stage {sub_id} produced no output_image; the chain continues with {current.get('object')}")
            for key in ("cutout_image", "mask_image"):
                if isinstance(output.get(key), dict) and output[key].get("object"):
                    artifacts[key] = output[key]

        try:
            facts, checks = self._measure_images(original, current, artifacts, criteria)
        except Exception as e:
            log.exception(f"Measuring images failed for task {task_id}: {e}")
            facts, checks = {"error": str(e)}, {}

        with self._get_lm_context(model_name, session_id):
            final_module = dspy.ChainOfThought(ExecutionAggregationSignature)
            final_res = final_module(job_description=job_desc, subagent_results=json.dumps(implement_responses),
                                     measured_facts=json.dumps(facts), criteria_checks=json.dumps(checks))
            final_report = extract_json(final_res.final_report) or {}
        if not isinstance(final_report, dict):
            final_report = {}

        final_report.update({
            "input_image": original,
            "delivered_image": current,
            "artifacts": artifacts,
            "measured_facts": facts,
            "criteria_checks": checks,
            "criteria_passed": bool(checks) and all(check.get("pass") for check in checks.values()),
        })
        entry["implement_responses"] = implement_responses
        entry["final_report"] = final_report
        self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": final_report}); return AgentResult(task_id=task_id, job_output=final_report)

if __name__ == "__main__":
    main(Manager3ImageEditingAgent)
