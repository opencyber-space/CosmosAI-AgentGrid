# agent_marketing_content_creator.py
import logging
from typing import List, Optional

import dspy
import re

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main

from utils.dspy_aios_llms import AIOS_DSPy_LMs

log = logging.getLogger(__name__)

# --- 1. The Signatures ---

class ContentCreatorSignature(dspy.Signature):
    """
    ### ROLE
    You are a specialized Marketing Localization Expert. Your task is to transform a core product 
    description into a high-performing campaign for a specific market.

    ### INSTRUCTIONS
    1. USE THE MARKET: Tailor all cultural references, idioms, and values to the specific nation/region provided.
    2. APPLY THE STRATEGY: This is your creative 'north star'. 
    3. RESPECT CONSTRAINTS: Adhere to all formatting rules and legal disclaimers.
    4. SYNTHESIZE: Blend the product's core features with the strategy and cultural lens.
    5. EMPHASIZE PRODUCT: Ensure the 'Visual Suggestions' explicitly include the main product described in 'product_description'. Do not just suggest abstract concepts or surroundings; the product itself MUST be a central element of the suggested imagery.

    ### OUTPUT EXPECTATION
    Output only the final campaign content. Do not include internal reasoning.
    All campaign copy (Title, Tagline, Overview, etc.) MUST be in the primary language of the target [MARKET].

    ### MANDATORY OUTPUT STRUCTURE
    You MUST follow this exact structure for your output, using these exact headings:
    
    ## Product Name: {Localized Product Name}
    ## Tagline: {Catchy localized tagline}
    ## Campaign Overview: {Detailed localized campaign description}
    ## Call to Action: {Direct localized instruction for the consumer}
    ## Visual Suggestions: {Localized description of recommended imagery}

    IMPORTANT: You MUST ensure the 'adapted_campaign' field is populated with the full content of your localized campaign following the structure above.
    """
    product_description = dspy.InputField(desc="Core product info")
    market = dspy.InputField(desc="The target nation/region")
    strategy = dspy.InputField(desc="The cultural lens or strategic angle to apply")
    constraints = dspy.InputField(desc="Legal or formatting rules for this region")
    
    adapted_campaign = dspy.OutputField(desc="The final localized marketing campaign content")


class ContentParser:
    def parse(self, text: str) -> str:
        if not text:
            return ""
        
        match = re.search(r"\[\[ ## adapted_campaign ## \]\](.*?)(\[\[ ##|$)", text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
            
        if "[[ ##" in text:
            cleaned = re.sub(r"\[\[ ##.*?## \]\]", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
            cleaned = re.sub(r"\[\[ ##.*", "", cleaned, flags=re.DOTALL | re.IGNORECASE).strip()
            return cleaned
        
        return text.strip()


class ContentCreatorWorker(dspy.Module):
    def __init__(self, custom_doc_WorkerSignature):
        super().__init__()
        DynamicSignature_WorkerSignature = ContentCreatorSignature.with_instructions(custom_doc_WorkerSignature)
        self.worker = dspy.ChainOfThought(DynamicSignature_WorkerSignature)
        self.parser = ContentParser()

    def _fallback_parse_from_history(self):
        try:
            if hasattr(dspy.settings, "lm") and dspy.settings.lm and hasattr(dspy.settings.lm, "history") and dspy.settings.lm.history:
                last_response = dspy.settings.lm.history[-1].get('response', [""])[0]
                if last_response:
                    parsed = self.parser.parse(last_response)
                    if parsed:
                        return parsed
        except Exception as e:
            log.warning(f"Manual parsing from history failed: {e}")
        return ""

    def forward(self, product_description, market, strategy, constraints):
        result = self.worker(
            product_description=product_description,
            market=market,
            strategy=strategy,
            constraints=constraints
        )
        
        content = getattr(result, "adapted_campaign", "")
        if not content or "[[ ##" in str(content):
            fallback = self._fallback_parse_from_history()
            if fallback:
                return fallback

        return self.parser.parse(str(content))


class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        brief = task.job_data.copy()
        if "previous_stage_output" in brief and "product_description" not in brief:
            brief["product_description"] = brief["previous_stage_output"]
        strategy = brief.get("text", "")
        return brief, strategy


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
        self.worker = ContentCreatorWorker(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        return [task]

    def _execute_worker(self, brief, strategy):
        return self.worker.forward(
            product_description=brief.get("product_description", "N/A"),
            market=brief.get("market", "Unknown"),
            strategy=strategy,
            constraints=brief.get("constraints", "None")
        )

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            brief, strategy = self.payload_processor.prepare_payload(task)

            with self.model_context.get_context(task):
                campaign_content = self._execute_worker(brief, strategy)

            return AgentResult(
                task_id=task.task_id,
                job_output={"text": campaign_content},
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
