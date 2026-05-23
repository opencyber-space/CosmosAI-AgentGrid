import logging
from typing import List, Optional
import dspy

from agents_sdk.core.agent_executor import AgentTask, AgentResult
from agents_sdk.core.main import main
from agents_sdk.core.agent_executor import Context

from utils.request_response_classes import AgentChainContext, AgentTurn
from utils.dspy_aios_llms import AIOS_DSPy_LMs

import json
import pydantic
import re
from google import genai
from google.genai import types
from PIL import Image
from io import BytesIO
import io
import base64
import uuid
from minio import Minio
from datetime import timedelta

# MinIO Config (Hardcoded for timebeing)


log = logging.getLogger(__name__)


class PromptExtractor:

    def extract_visual_suggestions(self, campaign_content):
        match_v = re.search(r"## Visual Suggestions: (.*)", campaign_content, re.DOTALL)
        return match_v.group(1).strip() if match_v else campaign_content

    def extract_campaign_overview(self, campaign_content):
        match_o = re.search(r"## Campaign Overview: (.*)", campaign_content, re.DOTALL)
        return match_o.group(1).strip() if match_o else campaign_content

    def build_final_prompt(self, market, product_description, visual_suggestions, campaign_overview, review_feedback):
        feedback_str = f"\n\nCRITICAL FEEDBACK FROM PREVIOUS ATTEMPT: {review_feedback}\nPlease address this feedback specifically to improve the cultural alignment." if review_feedback else ""
        return (
            f"Market: {market}\n"
            f"Product: {product_description}\n"
            f"Visual Concept: {visual_suggestions}\n"
            f"Context: {campaign_overview}{feedback_str}"
        )


class GoogleImageGenerator:

    def __init__(self, subject):
        self.client = None
        self.model_name = ""
        models = subject.integrations.models if hasattr(subject.integrations, 'models') else (subject.integrations.get('models', []) if subject.integrations else [])
        for oneBlock in models:
            self.model_name = oneBlock.llm_block_id if hasattr(oneBlock, 'llm_block_id') else oneBlock.get('llm_block_id')
            llm_params = oneBlock.llm_parameters if hasattr(oneBlock, 'llm_parameters') else oneBlock.get('llm_parameters', {})
            log.info(f"Adding model {self.model_name} to pool llm_params:{llm_params} oneBlock:{oneBlock}")
            if "google" in self.model_name:
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
                    # CRITICAL: This tells the model to output an image instead of just text
                    response_modalities=["IMAGE"], 
                    image_config=types.ImageConfig(
                        aspect_ratio="16:9"
                    )
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
        return img_url.split("?")[0]


class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data.copy()
        market = data.get("market", "Unknown")
        session_id = data.get("session_id", "")
        return data, market, session_id


class ModelContextManager:
    def __init__(self, aios_dspy_lm: AIOS_DSPy_LMs):
        self.aios_dspy_lm = aios_dspy_lm

    def get_context(self, task: AgentTask):
        session_id = task.job_data.get("session_id", "")
        model_name = task.job_data.get("model_name", self.aios_dspy_lm.get_any_model(session_id=session_id))
        return dspy.context(
            lm=self.aios_dspy_lm.get_choosen_model(
                model_name=model_name,
                session_id=session_id
            )
        )


class SampleAgent:

    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.prompt_extractor = PromptExtractor()
        self.image_generator = GoogleImageGenerator(subject)
        
        his_config = self.subject.persona.config.get("parameters", {})
        self.minio_config = his_config.get("MINIO_CONFIG", {})
        self.minio_uploader = MinioUploader(self.minio_config)
        
        self.payload_processor = AgentPayloadProcessor()
        #self.model_context = ModelContextManager(self.aios_dspy_lm)

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        return [task]

    def _prepare_prompt(self, data):
        pipeline_context = data.get("pipeline_context", {})
        market = data.get("market", "Unknown")
        product_description = data.get("product_description", "N/A")
        campaign_content = pipeline_context.get("content") or data.get("previous_stage_output", "")
        visual_suggestions = self.prompt_extractor.extract_visual_suggestions(campaign_content)
        campaign_overview = self.prompt_extractor.extract_campaign_overview(campaign_content)
        review_feedback = data.get("review_feedback")
        final_prompt = self.prompt_extractor.build_final_prompt(
            market, product_description, visual_suggestions, campaign_overview, review_feedback
        )
        return market, visual_suggestions, final_prompt

    def _prepare_inputs(self, task: AgentTask):
        return self.payload_processor.prepare_payload(task)

    def _execute_worker(self, final_prompt):
        return self.image_generator.generate_image_bytes(final_prompt)

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data, market, session_id = self._prepare_inputs(task)
            market, visual_suggestions, final_prompt = self._prepare_prompt(data)

            if self.image_generator.client is None:
                log.error("Google client is not initialized")
                return AgentResult(
                    task_id=task.task_id,
                    job_output={"error": "Google client is not initialized"},
                    is_error=True,
                )

            data_bytes = self._execute_worker(final_prompt)
            img_url = ""
            if data_bytes:
                img_url = self.minio_uploader.upload(data_bytes, session_id, task.task_id)

            return AgentResult(
                task_id=task.task_id,
                job_output={
                    "text": visual_suggestions, 
                    "image_url": img_url,
                    "visual_concept_details": visual_suggestions
                },
                is_error=False,
            )
        except Exception as e:
            log.exception("Error processing task %s: %s", task.task_id, e)
            return AgentResult(
                task_id=task.task_id,
                is_error=True,
                error_data={"stage": "on_data", "message": str(e)},
            )

if __name__ == "__main__":
    main(SampleAgent)
