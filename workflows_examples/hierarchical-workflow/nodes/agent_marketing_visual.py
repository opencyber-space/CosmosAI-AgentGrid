import logging
import uuid
import json
import time
import dspy
import io
from io import BytesIO
from PIL import Image
from minio import Minio
from datetime import timedelta
from google import genai
from google.genai import types

from typing import Any, Dict, List, Optional
from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "agent-workflow-marketing-team-lead": "my-company-marketing-team-lead-agent",
    "agent-workflow-marketing-content": "my-company-marketing-content-agent",
    "agent-workflow-marketing-planning": "my-company-marketing-planning-agent",
    "agent-workflow-marketing-strategy": "my-company-marketing-strategy-agent",
    "agent-workflow-marketing-visual": "my-company-marketing-visual-agent",
}

class GoogleImageGenerator:
    def __init__(self, subject):
        self.client = None
        self.model_name = ""
        models = subject.integrations.models if hasattr(subject.integrations, 'models') else (subject.integrations.get('models', []) if subject.integrations else [])
        for oneBlock in models:
            self.model_name = oneBlock.llm_block_id if hasattr(oneBlock, 'llm_block_id') else oneBlock.get('llm_block_id')
            if "google" in self.model_name:
                llm_params = oneBlock.llm_parameters if hasattr(oneBlock, 'llm_parameters') else oneBlock.get('llm_parameters', {})
                api_key = llm_params.get("api_key", "")
                self.client = genai.Client(api_key=api_key)

    def generate_image_bytes(self, prompt):
        if self.client is None:
            return None

        if "google:" in self.model_name:
            model_id = self.model_name.replace("google:", "")
            response = self.client.models.generate_content(
                model=model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"], 
                    image_config=types.ImageConfig(aspect_ratio="16:9")
                )
            )
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    img = Image.open(BytesIO(part.inline_data.data))
                    buffered = BytesIO()
                    img.save(buffered, format="PNG")
                    return buffered.getvalue()
        return None

class MinioUploader:
    def __init__(self, minio_config):
        self.minio_config = minio_config
        if minio_config:
            self.minio_client = Minio(
                self.minio_config["MINIO_URL"],
                access_key=self.minio_config["MINIO_ACCESS_KEY"],
                secret_key=self.minio_config["MINIO_SECRET_KEY"],
                secure=False
            )
            self.minio_bucket = self.minio_config["MINIO_BUCKET"]
            self.minio_external_port = self.minio_config["MINIO_EXTERNAL_PORT"]
            self.minio_internal_port = self.minio_config["MINIO_INTERNAL_PORT"]
            
            if not self.minio_client.bucket_exists(self.minio_bucket):
                self.minio_client.make_bucket(self.minio_bucket)

    def upload(self, data_bytes, session_id, task_id):
        if not self.minio_config:
            return ""
        object_name = f"{session_id}_{task_id}_{uuid.uuid4().hex[:8]}.png"
        self.minio_client.put_object(
            self.minio_bucket,
            object_name,
            io.BytesIO(data_bytes),
            length=len(data_bytes),
            content_type="image/png"
        )
        img_url = self.minio_client.presigned_get_object(self.minio_bucket, object_name, expires=timedelta(hours=1))
        img_url = img_url.replace(self.minio_config["MINIO_URL"], self.minio_config.get("MINIO_EXTERNAL_URL", self.minio_config["MINIO_URL"]))
        img_url = img_url.replace(self.minio_internal_port, self.minio_external_port)
        return img_url.split("?")[0]

class VisualSignature(dspy.Signature):
    """
    ### ROLE
    You are the Marketing Visual Content Agent.
    ### TASK
    Describe the visual campaign assets required based on the problem statement.
    ### OUTPUT
    Output EXACTLY a valid JSON block. All keys MUST be double-quoted.
    """
    problem_statement = dspy.InputField(desc="The problem statement")
    output_data = dspy.OutputField(desc="""Valid JSON block: {"asset_descriptions": ["string"], "deliverables": ["string"]}""")

class VisualModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.worker = dspy.ChainOfThought(VisualSignature)
    def forward(self, problem_statement):
        return self.worker(problem_statement=json.dumps(problem_statement))

class ImagePromptSignature(dspy.Signature):
    """
    ### ROLE
    You are an expert Prompt Engineer for Image Generation Models.
    ### TASK
    Create a highly detailed, descriptive, and visually rich image generation prompt for a specific asset description.
    Include lighting, style, camera angles, color palette, and mood.
    ### OUTPUT
    Output EXACTLY a valid JSON block. All keys MUST be double-quoted.
    """
    problem_statement = dspy.InputField(desc="The overall product or campaign problem statement")
    asset_description = dspy.InputField(desc="The specific visual asset to be generated")
    output_data = dspy.OutputField(desc="""Valid JSON block: {"image_prompt": "string"}""")

class ImagePromptModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.worker = dspy.ChainOfThought(ImagePromptSignature)
    def forward(self, problem_statement, asset_description):
        return self.worker(problem_statement=json.dumps(problem_statement), asset_description=json.dumps(asset_description))

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        raw_text = data.get("text") or data.get("user_request") or ""
        communication_type = data.get("communication_type", "delegate")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return raw_text, communication_type, model_name, session_id

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

class MarketingVisualAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        
        self.module = VisualModule(self.persona_default_system_message)
        self.prompt_module = ImagePromptModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        self.image_generator = GoogleImageGenerator(subject)
        
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.minio_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("MINIO_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.minio_uploader = MinioUploader(self.minio_config)
        self.task_registry = {}
        
        # Initialize HIS Client
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        text = task.job_data.get("text")
        if not text and "problem_statement" not in task.job_data:
            log.warning("Task %s has no 'text' or 'problem_statement' in job_data, skipping.", task.task_id)
            return None
        return [task]

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Marketing Team", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            task_id = data.get("task_id", task.task_id)
            user_request = data.get("user_request")
            priority = data.get("priority", "Fast")
            
            raw_text, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            
            if task_id not in self.task_registry:
                self.task_registry[task_id] = {"user_request": user_request, "priority": priority}
            else:
                if user_request:
                    self.task_registry[task_id]["user_request"] = user_request
                if "priority" in data:
                    self.task_registry[task_id]["priority"] = priority

            text = data.get("text")
            problem_statement = json.loads(text) if isinstance(text, str) and text.startswith("{") else (data.get("problem_statement") or raw_text)
            llm_session_id = data.get("session_id", str(uuid.uuid4()))

            with self.model_context.get_context(model_name=model_name, session_id=llm_session_id):
                result = self.module.forward(problem_statement=problem_statement)
            
            output_raw = result.output_data
            output_data = extract_json(output_raw)
            
            task_type = data.get("task_type", "estimate_budget")
            
            if task_type == "execute_task":
                # Generate Images
                image_urls = []
                asset_descriptions = output_data.get("asset_descriptions", [])
                log.info(f"Visual Content starting generation for {len(asset_descriptions)} assets...")
                
                image_prompts = []
                for desc in asset_descriptions:
                    with self.model_context.get_context(model_name=model_name, session_id=llm_session_id):
                        prompt_res = self.prompt_module.forward(problem_statement=problem_statement, asset_description=desc)
                        prompt_data = extract_json(prompt_res.output_data)
                        optimized_prompt = prompt_data.get("image_prompt", f"Product Concept: {problem_statement}\nAsset Description: {desc}")
                        image_prompts.append(optimized_prompt)
                    
                    try:
                        log.info(f"Generating image using optimized prompt: {optimized_prompt}")
                        data_bytes = self.image_generator.generate_image_bytes(optimized_prompt)
                        if data_bytes and self.minio_config:
                            url = self.minio_uploader.upload(data_bytes, llm_session_id, task_id)
                            image_urls.append(url)
                            log.info(f"Generated image: {url}")
                    except Exception as gen_err:
                        log.error(f"Failed to generate image for desc '{desc}': {gen_err}")

                specialist_details = output_data.copy()
                specialist_details["image_urls"] = image_urls
                specialist_details["image_prompts"] = image_prompts
                
                job_data = {
                    "task_type": "specialist_report",
                    "specialist_report": {
                        "team_name": "Visual Content",
                        "details": specialist_details
                    },
                    "session_id": llm_session_id,
                    "model_name": model_name,
                    "communication_type": communication_type,
                    "task_id": task_id,
                    "user_request": self.task_registry[task_id].get("user_request")
                }
            else:
                job_data = {
                    "communication_type": communication_type,
                    "budget_estimate": {
                        "team_name": "Visual Content",
                        "deliverables": output_data.get("deliverables", ["Report"])
                    },
                    "details": output_data,
                    "session_id": llm_session_id,
                    "model_name": model_name,
                    "task_id": task_id,
                    "user_request": self.task_registry[task_id].get("user_request")
                }
            
            self._log_to_his("my-marketing-team-lead-agent", job_data)
            return AgentResult(task_id=task.task_id, job_output=job_data, is_error=False)

        except Exception as e:
            log.exception(f"Error in Visual Agent: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(MarketingVisualAgent)
