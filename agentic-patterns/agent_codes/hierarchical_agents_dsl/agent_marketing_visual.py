import logging
import uuid
import json
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

# MinIO Config


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
            try:
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
            except Exception as e:
                log.error(f"Image generation API failed: {e}")
                return None
        return None

class MinioUploader:
    def __init__(self, minio_config):
        self.minio_config = minio_config
        self.minio_client = Minio(
            self.minio_config["MINIO_URL"],
            access_key=self.minio_config["MINIO_ACCESS_KEY"],
            secret_key=self.minio_config["MINIO_SECRET_KEY"],
            secure=False
        )
        self.minio_bucket = self.minio_config["MINIO_BUCKET"]
        
        if not self.minio_client.bucket_exists(self.minio_bucket):
            self.minio_client.make_bucket(self.minio_bucket)
    def upload(self, data_bytes, session_id, task_id):
        
        object_name = f"{session_id}_{task_id}_{uuid.uuid4().hex[:8]}.png"
        self.minio_client.put_object(
            self.minio_bucket,
            object_name,
            io.BytesIO(data_bytes),
            length=len(data_bytes),
            content_type="image/png"
        )
        img_url = self.minio_client.presigned_get_object(self.minio_bucket, object_name, expires=timedelta(hours=1))
        img_url = img_url.replace(self.minio_config["MINIO_URL"], self.minio_config.get("MINIO_EXTERNAL_URL"))
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
class MarketingVisualAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = VisualModule(self.persona_default_system_message)
        self.prompt_module = ImagePromptModule(self.persona_default_system_message)
        self.image_generator = GoogleImageGenerator(subject)
        his_config = self.subject.persona.config.get("parameters", {})
        self.minio_config = his_config.get("MINIO_CONFIG", {})
        self.minio_uploader = MinioUploader(self.minio_config)
        self.task_registry = {}
        # Initialize HIS Client
        his_config = self.subject.persona.config.get("parameters", {}).get("HIS_CONFIG", {})
        self.his_client = HisClient(
            base_url=his_config["HIS_BASE_URL"],
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )
    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        text = task.job_data.get("text")
        if not text:
            # Check for problem_statement
            if "problem_statement" in task.job_data:
                return [task]
            log.warning("Task %s has no 'text' in job_data, skipping.", task.task_id)
            return None
        return [task]
    def _log_to_his(self, target_id, job_data):
        try:
            msg = {"text": str(job_data), "source_id": self.subject.identity.subject_id, "destination_id": target_id, "team": "Marketing Team"}
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
            if task_id not in self.task_registry:
                self.task_registry[task_id] = {"user_request": user_request, "priority": priority}
            else:
                if user_request:
                    self.task_registry[task_id]["user_request"] = user_request
                if "priority" in data:
                    self.task_registry[task_id]["priority"] = priority
            # problem_statement is inside 'text' or passed directly
            text = data.get("text")
            problem_statement = json.loads(text) if isinstance(text, str) and text.startswith("{") else data.get("problem_statement")
            llm_session_id = str(uuid.uuid4())
            model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
            communication_type = data.get("communication_type", "delegate")
            with dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=llm_session_id)):
                result = self.module.forward(problem_statement=problem_statement)
            output_raw = result.output_data
            output_data = extract_json(output_raw)
            parent_id = "company-marketing-team-lead"
            task_type = data.get("task_type", "estimate_budget")
            if task_type == "execute_task":
                # Generate Images
                image_urls = []
                asset_descriptions = output_data.get("asset_descriptions", [])
                log.info(f"Visual Content starting generation for {len(asset_descriptions)} assets...")
                
                image_prompts = []
                for desc in asset_descriptions:
                    # Generate optimized prompt via DSPy Sub-Signature
                    try:
                        with dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=llm_session_id)):
                            prompt_res = self.prompt_module.forward(problem_statement=problem_statement, asset_description=desc)
                            prompt_data = extract_json(prompt_res.output_data)
                            optimized_prompt = prompt_data.get("image_prompt", f"Product Concept: {problem_statement}\nAsset Description: {desc}")
                    except Exception as prompt_err:
                        log.error(f"Failed to generate optimized prompt for desc '{desc}': {prompt_err}")
                        optimized_prompt = f"Product Concept: {problem_statement}\nAsset Description: {desc}"
                    
                    image_prompts.append(optimized_prompt)
                    
                    try:
                        log.info(f"Generating image using optimized prompt: {optimized_prompt}")
                        data_bytes = self.image_generator.generate_image_bytes(optimized_prompt)
                        if data_bytes:
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
                # estimate_budget
                job_data = {
                    "communication_type": communication_type,
                    "budget_estimate": {
                        "team_name": "Visual Content",
                        "deliverables": output_data.get("deliverables", ["Report"])
                    },
                    "details": output_data,
                    "session_id": llm_session_id,
                    "model_name": model_name,
                    "communication_type": communication_type,
                    "task_id": task_id,
                    "user_request": self.task_registry[task_id].get("user_request")
                }
            if communication_type == "delegate":
                self._log_to_his(parent_id, job_data)
                self.context.delegator.submit_and_wait(subject_id=parent_id, session_id=llm_session_id, task_id=task.task_id, task_data=job_data)
            else:
                self._log_to_his(parent_id, job_data)
                self.context.p2p_manager.send_sync(task=task, subject_id=parent_id, job_data=job_data, session_id=llm_session_id)
            return AgentResult(task_id=task.task_id, skip=True)
        except Exception as e:
            log.exception(f"Error in Visual Agent: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})
if __name__ == "__main__":
    main(MarketingVisualAgent)
