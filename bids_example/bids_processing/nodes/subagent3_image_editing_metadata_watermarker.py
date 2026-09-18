import logging
import time
from agents_sdk.core.his import HisClient
import uuid
import json
import io
import dspy
from dspy.utils.exceptions import AdapterParseError
from typing import Any, Dict, List, Optional
from PIL import ExifTags, Image, ImageDraw, ImageFont

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json
from utils.image_models import GPS_IFD, MinioStore, image_facts, minio_config

log = logging.getLogger(__name__)

MANAGER_ID = "manager3-image-editing"


# --- Signatures ---

class SubagentAssessSignature(dspy.Signature):
    """
    ### ROLE
    You are Sub-agent 3: Metadata Watermarker.

    ### TASK
    Assess the sub-task instruction for EXIF metadata handling, digital watermarking, and format conversion. Determine if you can perform this sub-task and estimate token usage, compute requirements, testing environment needs, and any constraints.

    ### OUTPUT
    Output EXACTLY a JSON block: {"can_do": bool, "approx_tokens": int, "compute_required": "low|moderate|high", "testing_env": "string", "constraints": ["string"], "status": "assessed"}

    ### CONSTRAINT
    "compute_required" MUST be exactly one of the lowercase strings "low", "moderate" or "high".
    Emit only that single word - no prose, no explanation, no qualifiers. Put any reasoning about
    compute needs into "constraints" instead.
    """
    subtask_instruction = dspy.InputField(desc="Sub-task instruction for metadata and watermarking")
    assessment_result = dspy.OutputField(desc="JSON block of assessment estimates and constraints")

class SubagentImplementSignature(dspy.Signature):
    """
    ### ROLE
    You are Sub-agent 3: Metadata Watermarker.

    ### TASK
    Plan the publication pass for a real image. `input_image_facts` describes the image to publish
    (the output of the earlier editing stages) and `original_image_facts` the original upload,
    including the EXIF tag names present. Your plan is executed in code: EXIF is carried over from
    the original, the tags in `exif_tags_to_remove` are deleted (any name starting with "GPS"
    removes the whole GPS block), the colour profile is kept when `keep_icc_profile` is true, and a
    text watermark is drawn at `watermark_position` with `watermark_opacity_pct` opacity (0-100).

    Take every value from the sub-task instruction. Use exact EXIF tag names such as "Artist" or
    "GPSInfo". `watermark_text` must be readable words, not a lone symbol: use the text the
    instruction gives, otherwise a short copyright line with an owner name such as "© AgentGrid".

    ### OUTPUT
    Put EXACTLY one JSON block, with no text around it, in the `implementation_result` output field (after `reasoning`): {"agent_role": "Metadata Watermarker", "watermark_text": "string", "watermark_opacity_pct": int, "watermark_position": "bottom-right|bottom-left|top-right|top-left", "exif_tags_to_remove": ["string"], "keep_icc_profile": bool, "status": "planned"}
    """
    subtask_instruction = dspy.InputField(desc="Sub-task instruction for metadata and watermarking")
    input_image_facts = dspy.InputField(desc="Facts measured from the image to publish")
    original_image_facts = dspy.InputField(desc="Facts measured from the original upload")
    implementation_result = dspy.OutputField(desc="JSON block with the watermark and metadata plan")

# --- Sub-Agent Node ---

class Subagent3ImageEditingMetadataWatermarkerAgent:
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
    def _strip_exif(exif, names):
        removed = []
        by_name = {name: tag for tag, name in ExifTags.TAGS.items()}
        for name in names:
            name = str(name).strip()
            if name.upper().startswith("GPS"):
                if GPS_IFD in exif:
                    del exif[GPS_IFD]
                    removed.append("GPSInfo")
                continue
            tag = by_name.get(name)
            if tag is not None and tag in exif:
                del exif[tag]
                removed.append(name)
        return sorted(set(removed))

    @staticmethod
    def _draw_watermark(img, text, opacity_pct, position):
        base = img.convert("RGBA")
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        font = ImageFont.load_default(size=max(16, base.width // 30))
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        text_w, text_h = right - left, bottom - top
        margin = max(8, base.width // 50)
        x = margin if "left" in position else base.width - text_w - margin
        y = margin if position.startswith("top") else base.height - text_h - margin
        alpha = round(255 * max(0, min(100, opacity_pct)) / 100)
        draw.text((x - left, y - top), text, font=font, fill=(255, 255, 255, alpha))
        return Image.alpha_composite(base, overlay), [x, y, x + text_w, y + text_h]

    def _implement(self, data, instruction, session_id, task_id):
        source = data.get("input_image") or {}
        original = data.get("original_image") or source
        if not source.get("object"):
            raise ValueError("implement task carries no input_image to publish")
        store = self._store()
        source_bytes = store.get_bytes(source)
        original_bytes = source_bytes if original == source else store.get_bytes(original)
        source_facts, original_facts = image_facts(source_bytes), image_facts(original_bytes)

        raw = self._predict(SubagentImplementSignature, "implementation_result",
                            subtask_instruction=instruction,
                            input_image_facts=json.dumps(source_facts),
                            original_image_facts=json.dumps(original_facts))
        plan = extract_json(raw) or {}
        text = str(plan.get("watermark_text") or "").strip()
        if sum(ch.isalnum() for ch in text) < 3:
            # A lone "©" at 12% opacity is invisible; a watermark needs readable words.
            text = "© AgentGrid"
        try:
            opacity = int(plan.get("watermark_opacity_pct"))
        except (TypeError, ValueError):
            opacity = 12
        position = plan.get("watermark_position") if plan.get("watermark_position") in ("bottom-right", "bottom-left", "top-right", "top-left") else "bottom-right"
        keep_icc = plan.get("keep_icc_profile", True) is not False

        img = Image.open(io.BytesIO(source_bytes))
        original_img = Image.open(io.BytesIO(original_bytes))
        operations = []
        exif_source = img if img.getexif() else original_img
        exif = exif_source.getexif()
        exif.get_ifd(GPS_IFD)
        removed = self._strip_exif(exif, plan.get("exif_tags_to_remove") or [])
        operations.append(f"EXIF carried over from the {'input' if exif_source is img else 'original'} image; removed {removed or 'nothing'}")
        icc = (img.info.get("icc_profile") or original_img.info.get("icc_profile")) if keep_icc else None
        operations.append("colour profile " + ("kept" if icc else "not embedded"))
        dpi = tuple(round(float(d)) for d in img.info["dpi"]) if img.info.get("dpi") else None

        had_alpha = "A" in img.getbands()
        marked, box = self._draw_watermark(img, text, opacity, position)
        operations.append(f"watermark '{text}' at {position}, {opacity}% opacity, box {box}")
        if not had_alpha:
            marked = marked.convert("RGB")

        buf = io.BytesIO()
        save_args = {"format": "PNG", "exif": exif}
        if icc:
            save_args["icc_profile"] = icc
        if dpi:
            save_args["dpi"] = dpi
        marked.save(buf, **save_args)
        return {
            "agent_role": "Metadata Watermarker",
            "output_image": store.put_bytes(buf.getvalue(), f"{session_id}/{task_id}/final.png"),
            "model_used": "none (deterministic PIL pass)",
            "watermark": {"text": text, "opacity_pct": opacity, "position": position, "box": box},
            "exif_tags_removed": removed,
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
        log.info(f"Preprocessing task {task.task_id} in Subagent3ImageEditingMetadataWatermarker")
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
                    assess_data = extract_json(raw) or {"can_do": True, "approx_tokens": 900, "status": "assessed"}
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
            log.exception(f"Error in Subagent 3 Metadata Watermarker: {e}")
            self._log_to_his(target_id=MANAGER_ID, job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "error", "message": str(e)}}); return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(Subagent3ImageEditingMetadataWatermarkerAgent)
