# agent_marketing_image_reviewer.py
import logging
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentTask, AgentResult
from agents_sdk.core.main import main
from agents_sdk.core.agent_executor import Context

from utils.request_response_classes import AgentChainContext, AgentTurn
from utils.dspy_aios_llms import AIOS_DSPy_LMs

import json
import dspy
import pydantic
import re
import requests
from PIL import Image
import io
import tempfile
import os
import uuid

log = logging.getLogger(__name__)

# --- 1. The Signatures ---

class ImageMatchVerifier(dspy.Signature):
    """
    ### ROLE
    You are a Brand Cultural Consultant. Your task is to review the proposed image concepts
    and campaign content to ensure they are culturally appropriate for the target market
    and align perfectly with the brand's localized strategy.

    ### INSTRUCTIONS
    1. IMAGE MANDATORY: You MUST have a valid image input to perform a review. If the 'image' input is missing, empty, or invalid, you cannot provide a score or feedback.
    2. REVIEW for cultural sensitivity and potential taboos in the target market.
    3. ALIGNMENT: Ensure the visual concept matches the campaign's message.
    4. FEEDBACK: Provide constructive feedback for the local market manager.

    ### OUTPUT EXPECTATION
    Output a structured review of the proposed creative. If no image is provided, explicitly state that the review was skipped.

    ### MANDATORY OUTPUT STRUCTURE
    You MUST follow this exact structure for your output:

    ## Cultural Alignment Score: {score}/10 (e.g., 9/10)
    ## Review Feedback: {Detailed feedback on image and content}
    ## Approval Status: {Approved/Needs Revision}
    """

    image = dspy.InputField(desc="The visual creative/image to be reviewed", type=dspy.Image)
    description = dspy.InputField(desc="The campaign description or localized strategy text")
    market = dspy.InputField(desc="The target geographical or cultural market (e.g., Japan, UAE)")

    cultural_alignment_score = dspy.OutputField(desc="A score from 1-10 in format 'X/10'", prefix="## Cultural Alignment Score:")
    review_feedback = dspy.OutputField(desc="Detailed feedback on image and content", prefix="## Review Feedback:")
    approval_status = dspy.OutputField(desc="Approved or Needs Revision", prefix="## Approval Status:")

class ImageReviewerWorker(dspy.Module):
    def __init__(self, custom_doc_WorkerSignature):
        super().__init__()
        DynamicSignature_WorkerSignature = ImageMatchVerifier.with_instructions(custom_doc_WorkerSignature)
        #self.worker = dspy.ChainOfThought(DynamicSignature_WorkerSignature)
        # Use ChainOfThought to improve the model's 'reasoning' before it gives the True/False result
        self.verifier = dspy.ChainOfThought(DynamicSignature_WorkerSignature)

    def forward(self, market, desc, image_data):
        response = self.verifier(
            image=image_data, description=desc, market=market
        )

        print(f"Score: {response.cultural_alignment_score}")
        print(f"Status: {response.approval_status}")
        print(f"Feedback: {response.review_feedback}")

        score = response.cultural_alignment_score
        if score and "/10" not in str(score):
            # Extract number and format as /10
            match = re.search(r"(\d+)", str(score))
            if match:
                score = f"{match.group(1)}/10"

        return {"cultural_alignment_score": score,
                "approval_status": response.approval_status,
                "review_feedback": response.review_feedback}


class ImageInputResolver:
    def resolve(self, img_input, task):
        image_to_review = None
        local_image_path = None

        if isinstance(img_input, str) and (img_input.startswith("http://") or img_input.startswith("https://")):
            log.info(f"Downloading image from URL: {img_input}")
            response = requests.get(img_input)
            response.raise_for_status()
            img_bytes = response.content
            log.info(f"Downloaded image size: {len(img_bytes)} bytes")

            pil_img = Image.open(io.BytesIO(img_bytes))
            log.info(f"Image resolution: {pil_img.size}")

            url_path = img_input.split("?")[0]
            filename = os.path.basename(url_path)
            if not filename or "." not in filename:
                filename = f"review_image_{task.task_id}_{uuid.uuid4().hex[:8]}.png"

            local_image_path = os.path.join(os.getcwd(), filename)
            with open(local_image_path, 'wb') as f:
                f.write(img_bytes)
            log.info(f"Saved image to local file: {local_image_path}")

            image_to_review = dspy.Image(url=pil_img)
            log.info(f"Created dspy.Image from PIL object using keyword argument")
        else:
            image_to_review = img_input
            
        return image_to_review, local_image_path


class PromptExtractor:

    def extract_visual_suggestions(self, campaign_content):
        match = re.search(r"## Visual Suggestions: (.*)", campaign_content)
        return match.group(1) if match else campaign_content

    def extract_campaign_overview(self, campaign_content):
        match = re.search(r"## Campaign Overview: (.*)", campaign_content)
        return match.group(1) if match else campaign_content

    def build_prompt(self, market, visual_suggestions, campaign_overview):
        return f"For Market: {market} generate image with details as below {visual_suggestions} Metadata for Image Generation={campaign_overview}"


class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data.copy()
        market = data.get("market", "Unknown")
        return data, market


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
        self.worker = ImageReviewerWorker(self.persona_default_system_message)
        self.prompt_extractor = PromptExtractor()
        self.image_resolver = ImageInputResolver()
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        return [task]

    def _prepare_inputs(self, data, task):
        pipeline_context = data.get("pipeline_context", {})
        market = data.get("market", "Unknown")
        campaign_content = pipeline_context.get("content") or data.get("previous_stage_output", "")
        visual_suggestions = self.prompt_extractor.extract_visual_suggestions(campaign_content)
        campaign_overview = self.prompt_extractor.extract_campaign_overview(campaign_content)
        final_content_for_image_generation = self.prompt_extractor.build_prompt(
            market, visual_suggestions, campaign_overview
        )

        img_input = pipeline_context.get("image") or data.get("image_url") or data.get("image_base64")

        return market, final_content_for_image_generation, img_input

    def _skip_review_result(self, task):
        return AgentResult(
            task_id=task.task_id,
            job_output={"text": "Review skipped due to missing image input."},
            is_error=False,
        )

    def _execute_worker(self, market, final_content_for_image_generation, image_to_review):
        result = self.worker(market=market, desc=final_content_for_image_generation, image_data=image_to_review)
        return result

    def on_data(self, task: AgentTask) -> AgentResult:
        local_image_path = None
        try:
            data, market = self.payload_processor.prepare_payload(task)
            market, final_content_for_image_generation, img_input = self._prepare_inputs(data, task)

            log.info(f"[{market}] Image Reviewer received img_input type: {type(img_input)}, value preview: {str(img_input)[:100]}")

            if not img_input or (isinstance(img_input, str) and img_input.strip() == ""):
                log.warning("No image input provided to Image Reviewer. Skipping review.")
                return self._skip_review_result(task)

            image_to_review, local_image_path = self.image_resolver.resolve(img_input, task)

            try:
                with self.model_context.get_context(task):
                    review_data = self._execute_worker(market, final_content_for_image_generation, image_to_review)
            finally:
                if local_image_path and os.path.exists(local_image_path):
                    try:
                        os.remove(local_image_path)
                        log.info(f"Cleaned up local image file: {local_image_path}")
                    except Exception as e:
                        log.warning(f"Failed to cleanup {local_image_path}: {e}")

            return AgentResult(
                task_id=task.task_id,
                job_output={"text": review_data},
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
