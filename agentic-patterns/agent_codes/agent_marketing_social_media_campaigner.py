# agent_marketing_social_media_campaigner.py
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

log = logging.getLogger(__name__)

# --- 1. The Signatures ---

class SocialMediaSignature(dspy.Signature):
    """
    ### ROLE
    You are a Social Media Strategy Expert. Your task is to define the target audience
    and the distribution strategy for a localized marketing campaign.

    ### INSTRUCTIONS
    1. DEFINE demographics: age, gender, location, and interests for the specific [MARKET].
    2. STRATEGIZE: Select the best platforms and engagement tactics for this audience.
    3. ADAPT: Ensure the audience profiling reflects local social media trends.

    ### OUTPUT EXPECTATION
    Output a detailed target audience profile and a platform-specific distribution strategy.
    
    ### MANDATORY OUTPUT STRUCTURE
    You MUST follow this exact structure for your output:
    
    ## Target Audience: {Detailed demographics and interests}
    ## Platform Strategy: {Recommended social platforms and engagement tactics}
    ## Posting Schedule: {Optimal times and frequency}
    """
    market = dspy.InputField(desc="The target nation/region")
    campaign_content = dspy.InputField(desc="The localized campaign text")
    review_feedback = dspy.InputField(desc="Feedback from the image reviewer")
    
    social_strategy = dspy.OutputField(desc="The target audience and platform strategy")


class SocialMediaWorker(dspy.Module):
    def __init__(self, custom_doc_WorkerSignature):
        super().__init__()
        DynamicSignature_WorkerSignature = SocialMediaSignature.with_instructions(custom_doc_WorkerSignature)
        self.worker = dspy.ChainOfThought(DynamicSignature_WorkerSignature)

    def forward(self, market, campaign_content, review_feedback):
        result = self.worker(
            market=market,
            campaign_content=campaign_content,
            review_feedback=review_feedback
        )
        return result.social_strategy


class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data.copy()
        pipeline_context = data.get("pipeline_context", {})
        
        # 1. Get Campaign Content (Priority: pipeline_context['content'] -> product_description)
        data["campaign_content"] = pipeline_context.get("content") or data.get("product_description", "")
        
        # 2. Get Review Feedback (Priority: pipeline_context['review'] -> previous_stage_output)
        data["review_feedback"] = pipeline_context.get("review") or data.get("previous_stage_output", "")
        
        return data


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
        self.worker = SocialMediaWorker(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        return [task]

    def _prepare_inputs(self, data):
        market = data.get("market", "Unknown")
        campaign_content = data.get("campaign_content", "")
        review_feedback = data.get("review_feedback", "")
        return market, campaign_content, review_feedback

    def _execute_worker(self, market, campaign_content, review_feedback):
        return self.worker.forward(
            market=market,
            campaign_content=campaign_content,
            review_feedback=review_feedback
        )

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = self.payload_processor.prepare_payload(task)
            market, campaign_content, review_feedback = self._prepare_inputs(data)

            with self.model_context.get_context(task):
                social_strategy = self._execute_worker(market, campaign_content, review_feedback)

            return AgentResult(
                task_id=task.task_id,
                job_output={"text": social_strategy},
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
