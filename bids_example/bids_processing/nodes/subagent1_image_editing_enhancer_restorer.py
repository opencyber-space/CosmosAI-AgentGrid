import logging
import time
from agents_sdk.core.his import HisClient
import uuid
import json
import io
import dspy
from dspy.utils.exceptions import AdapterParseError
from typing import Any, Dict, List, Optional
from PIL import Image, ImageOps

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json
from utils.image_models import MinioStore, OpenAIImageEditor, image_facts, minio_config

log = logging.getLogger(__name__)

MANAGER_ID = "manager3-image-editing"


# --- Signatures ---

class SubagentAssessSignature(dspy.Signature):
    """
    ### ROLE
    You are Sub-agent 1: Image Enhancer & Restorer.

    ### TASK
    Assess the sub-task instruction for resolution scaling, noise reduction, and color balancing. Determine if you can perform this sub-task and estimate token usage, compute requirements, testing environment needs, and any constraints.

    ### OUTPUT
    Output EXACTLY a JSON block: {"can_do": bool, "approx_tokens": int, "compute_required": "low|moderate|high", "testing_env": "string", "constraints": ["string"], "status": "assessed"}

    ### CONSTRAINT
    "compute_required" MUST be exactly one of the lowercase strings "low", "moderate" or "high".
    Emit only that single word - no prose, no explanation, no qualifiers. Put any reasoning about
    compute needs into "constraints" instead.
    """
    subtask_instruction = dspy.InputField(desc="Sub-task instruction for image enhancement and restoration")
    assessment_result = dspy.OutputField(desc="JSON block of assessment estimates and constraints")

class SubagentImplementSignature(dspy.Signature):
    """
    ### ROLE
    You are Sub-agent 1: Image Enhancer & Restorer.

    ### TASK
    Plan the enhancement of a real image. `input_image_facts` holds facts measured from that image
    (size, DPI, average luminance 0-1, percentage of clipped highlights). Your plan is executed in
    code: `edit_prompt` is sent together with the image to an image-editing model, then the result
    is resized to exactly `target_width` x `target_height` and saved at `target_dpi`.

    Write `edit_prompt` as a direct instruction to the image model: restore exposure and colour
    balance as the sub-task asks (for example lift shadows and partially shadowed faces, keep
    highlights unclipped, natural colours), and preserve the composition, people, objects and
    framing exactly - add or remove nothing and add no text.
    Take the target size and DPI from the sub-task instruction; if it gives none, keep the
    measured size and DPI.

    ### OUTPUT
    Put EXACTLY one JSON block, with no text around it, in the `implementation_result` output field (after `reasoning`): {"agent_role": "Image Enhancer & Restorer", "edit_prompt": "string", "target_width": int, "target_height": int, "target_dpi": int, "status": "planned"}
    """
    subtask_instruction = dspy.InputField(desc="Sub-task instruction for image enhancement and restoration")
    input_image_facts = dspy.InputField(desc="Facts measured from the input image")
    implementation_result = dspy.OutputField(desc="JSON block with the edit prompt and output targets")

# --- Sub-Agent Node ---

class Subagent1ImageEditingEnhancerRestorerAgent:
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
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.task_registry = {}
        self.default_model = "aios:qwen3-1-7b-vllm-block"
        try:
            if self.subject and hasattr(self.subject, 'integrations') and self.subject.integrations and self.subject.integrations.models:
                self.default_model = self.subject.integrations.models[0].llm_block_id
        except Exception:
            pass
        self.editor = OpenAIImageEditor(self.subject)
        self.store = None

    def _get_lm_context(self, model_name, session_id):
        return dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=session_id))

    def _predict(self, signature, output_field, **inputs):
        """Run `signature` with chain-of-thought and return the raw text of `output_field`.

        The model sometimes answers with the bare JSON block and skips DSPy's field markers,
        so both adapters raise AdapterParseError although the answer is usable. The raw LM
        response is recovered instead of failing the whole phase; extract_json parses it.
        """
        try:
            return getattr(dspy.ChainOfThought(signature)(**inputs), output_field)
        except AdapterParseError as e:
            log.warning(f"{signature.__name__}: adapter could not parse the LM response; recovering JSON from the raw text")
            raw = e.lm_response or ""
            wrapped = extract_json(raw)
            if isinstance(wrapped, dict) and output_field in wrapped:
                inner = wrapped[output_field]
                return inner if isinstance(inner, str) else json.dumps(inner)
            return raw

    def _store(self):
        # Connected lazily so an unreachable MinIO does not stop the agent from starting.
        if self.store is None:
            self.store = MinioStore(minio_config(self.subject))
        return self.store

    @staticmethod
    def _dimension(value, default):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        return value if 16 <= value <= 8192 else default

    def _implement(self, data, instruction, session_id, task_id):
        source = data.get("input_image") or {}
        if not source.get("object"):
            raise ValueError("implement task carries no input_image to edit")
        if self.editor.client is None:
            raise RuntimeError("no openai image model (openai:*image*) is configured in this agent's spec")
        store = self._store()
        source_bytes = store.get_bytes(source)
        source_facts = image_facts(source_bytes)

        raw = self._predict(SubagentImplementSignature, "implementation_result",
                            subtask_instruction=instruction,
                            input_image_facts=json.dumps(source_facts))
        plan = extract_json(raw) or {}
        prompt = plan.get("edit_prompt") or instruction
        width = self._dimension(plan.get("target_width"), source_facts["width"])
        height = self._dimension(plan.get("target_height"), source_facts["height"])
        dpi = self._dimension(plan.get("target_dpi"), (source_facts["dpi"] or [72])[0])

        edited = self.editor.edit_image_bytes(source_bytes, prompt)
        if not edited:
            raise RuntimeError(f"{self.editor.model_name} returned no image")
        img = Image.open(io.BytesIO(edited))
        operations = [f"{self.editor.model_name} edit, letterboxed and cropped back to the input framing ({img.width}x{img.height})"]
        if (img.width, img.height) != (width, height):
            if abs(img.width / img.height - width / height) < 0.01:
                img = img.resize((width, height), Image.LANCZOS)
                operations.append(f"resized to {width}x{height} (LANCZOS)")
            else:
                img = ImageOps.fit(img, (width, height), Image.LANCZOS)
                operations.append(f"fit to {width}x{height} (centre crop to the new aspect ratio, LANCZOS)")
        buf = io.BytesIO()
        img.save(buf, format="PNG", dpi=(dpi, dpi))
        operations.append(f"saved PNG at {dpi} DPI")
        output = store.put_bytes(buf.getvalue(), f"{session_id}/{task_id}/enhanced.png")
        return {
            "agent_role": "Image Enhancer & Restorer",
            "output_image": output,
            "model_used": self.editor.model_name,
            "edit_prompt": prompt,
            "operations": operations,
            "input_facts": source_facts,
            "output_facts": image_facts(buf.getvalue()),
            "status": "completed",
        }

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id, "team": getattr(self, "name", "Agent Team"), "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} in Subagent1ImageEditingEnhancerRestorer")
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:

        try:
            # Log incoming request
            self._log_to_his(
                target_id=getattr(self.subject.identity, 'subject_id', 'unknown'),
                job_data={"task_type": "INCOMING_TASK", "payload": task.job_data}
            )
            data = task.job_data
            event_type = data.get("event_type", "assess")
            task_id = data.get("task_id", task.task_id)
            instruction = data.get("text", "")
            model_name = data.get("model_name", self.default_model)
            session_id = data.get("session_id", str(uuid.uuid4()))

            if task_id not in self.task_registry:
                self.task_registry[task_id] = {}

            with self._get_lm_context(model_name, session_id):
                if event_type == "assess":
                    raw = self._predict(SubagentAssessSignature, "assessment_result", subtask_instruction=instruction)
                    assess_data = extract_json(raw) or {"can_do": True, "approx_tokens": 1600, "status": "assessed"}
                    self.task_registry[task_id]["assess"] = {"instruction": instruction, "response": assess_data, "status": "assessed"}
                    self._log_to_his(target_id=MANAGER_ID, job_data={"task_type": "OUTGOING_RESULT", "payload": assess_data}); return AgentResult(task_id=task_id, job_output=assess_data)

                elif event_type == "implement":
                    instruction = data.get("subtask_instruction") or instruction
                    implement_data = self._implement(data, instruction, session_id, task_id)
                    self.task_registry[task_id]["implement"] = {"instruction": instruction, "response": implement_data, "status": "completed"}
                    self._log_to_his(target_id=MANAGER_ID, job_data={"task_type": "OUTGOING_RESULT", "payload": implement_data}); return AgentResult(task_id=task_id, job_output=implement_data)

                else:
                    self._log_to_his(target_id=MANAGER_ID, job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "skipped", "reason": f"unhandled event_type: {event_type}"}}); return AgentResult(task_id=task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Subagent 1 Image Enhancer & Restorer: {e}")
            self._log_to_his(target_id=MANAGER_ID, job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "error", "message": str(e)}}); return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(Subagent1ImageEditingEnhancerRestorerAgent)
