# sample_agent.py
import logging
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentTask, AgentResult
from agents_sdk.core.main import main
from agents_sdk.core.agent_executor import Context

from agents_llm import AIGridClient
from agents_llm.custom import OpenAIBlockInferenceSystem
from agents_sdk.core.known_agents import KnownAgents
from agents_search.search import AgentSearchSelector

from utils.request_response_classes import AgentChainContext, AgentTurn
from utils.dspy_aios_llms import AIOS_DSPy_LMs

import requests
import uuid
import random
import string
import json
import dspy
import pydantic
import re
import threading
import time

log = logging.getLogger(__name__)

# --- 1. The Signatures ---

class PipelineStagePlan(pydantic.BaseModel):
    stage_name: str = pydantic.Field(description="Name of the stage (e.g., 'content', 'image', 'social')")
    agent_id: str = pydantic.Field(description="The EXACT Agent ID from the available_agents list")
    task_instruction: str = pydantic.Field(description="Instructions for this agent (e.g., 'Create tagline for Japan')")

class MarketWorkflow(pydantic.BaseModel):
    market: str = pydantic.Field(description="The name of the target market")
    pipeline: List[PipelineStagePlan] = pydantic.Field(description="List of agent stages for this market")

class OrchestratorSignature(dspy.Signature):
    """
    ### ROLE
    You are a Strategic Marketing Orchestrator. 

    ### TASK
    Decompose the 'product_description' into localized campaigns for EACH target market.
    Identify the most effective sequence of agents from the 'available_agents' list to fulfill the campaign goals.

    ### WORKFLOW CONSTRUCTION RULES
    1. ANALYZE capabilities: Read the 'Capabilities', 'Inputs', and 'Outputs' for each agent in 'available_agents'.
    2. DESIGN logical flow: Create a pipeline where each agent's output provides the necessary context or input for subsequent agents.
    3. CONSOLIDATE TASKS: One stage = One Agent Call. If an agent (e.g., Content Creator) produces multiple required outputs (e.g., localized copy AND visual suggestions), you MUST combine these into a SINGLE stage. DO NOT create separate stages for different outputs from the same agent if they are generated simultaneously.
    4. EFFICIENCY: Never plan a redundant stage to generate information already produced by a previous agent.
    5. PRODUCT CONSISTENCY: Every stage's 'task_instruction' MUST explicitly tell the agent to use the EXACT product name from the 'product_description'. Prohibit agents from inventing, localizing, or hallucinating different product names.
    6. ADAPT to available tools: Use only the agents provided. If an agent with a specific capability (e.g., image review) is available, use it at the appropriate stage to ensure quality.
    7. NO SET SEQUENCE: Do not follow a fixed sequence. Instead, reason about the most logical path from core content to final distribution based on the specific agents provided.
    8. COMPLETE CAMPAIGN: Ensure the pipeline covers everything from localized creation to distribution strategy.

    ### OUTPUT FIELD: workflow_plans
    Populate 'workflow_plans' with the selected agent steps. Use the EXACT Agent ID.
    Example structure:
    [
      {
        "market": "<Market_Name>",
        "pipeline": [
          {"stage_name": "<stage_purpose_1>", "agent_id": "<agent_id_A>", "task_instruction": "..."},
          {"stage_name": "<stage_purpose_2>", "agent_id": "<agent_id_B>", "task_instruction": "..."},
          "... (Add more stages as needed to fulfill the campaign steps reasoned above)"
        ]
      }
    ]
    """
    product_description = dspy.InputField()
    available_agents = dspy.InputField(desc="List of available agents with their IDs and capabilities")
    
    workflow_plans: List[MarketWorkflow] = dspy.OutputField(desc="A list of workflows, one per market, each with its own pipeline of agent stages")


class WorkflowParser:

    def _extract_json_blocks(self, s):
        blocks = []
        stack = []
        start = -1
        in_string = False
        escape = False
        
        for i, char in enumerate(s):
            if escape:
                escape = False
                continue
            if char == '\\':
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            
            if in_string:
                continue

            if char in ('{', '['):
                if not stack:
                    start = i
                stack.append(char)
            elif char in ('}', ']'):
                if stack:
                    top = stack.pop()
                    if (top == '{' and char == '}') or (top == '[' and char == ']'):
                        if not stack:
                            blocks.append(s[start:i+1])
                    else:
                        stack = []
        return blocks

    def parse(self, text):
        if not text or not isinstance(text, str):
            log.warning("Parser received non-string input: %s", type(text))
            return []

        log.info("Parsing workflows from raw text. Length: %d", len(text))
        
        cleaned_text = re.sub(r'\[\[ ## .*? ## \]\]', '', text, flags=re.DOTALL)
        log.debug("Cleaned text (first 100 chars): %s", cleaned_text[:100])
        
        json_blocks = self._extract_json_blocks(cleaned_text)
        log.info("Extracted %d potential JSON blocks", len(json_blocks))
        workflows = []

        for block in json_blocks:
            try:
                # Try raw parsing first
                try:
                    data = json.loads(block)
                except json.JSONDecodeError:
                    # Fallback for LLMs that use single quotes 
                    try:
                        data = json.loads(block.replace("'", '"'))
                    except:
                        continue
                
                # Handle dspy wrapper or reasoning wrapper
                if isinstance(data, dict):
                    if "workflow_plans" in data:
                        data = data["workflow_plans"]
                    elif "workflows" in data:
                        data = data["workflows"]
                
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and 'market' in item:
                            market_name = item.get('market')
                            raw_pipeline = item.get('pipeline') or item.get('steps') or item.get('workflow') or item.get('agents')
                            
                            if market_name and raw_pipeline:
                                normalized_pipeline = []
                                for stage in raw_pipeline:
                                    if isinstance(stage, dict):
                                        normalized_pipeline.append({
                                            "stage_name": stage.get("stage_name") or stage.get("name") or stage.get("task_name") or "adaptation",
                                            "agent_id": stage.get("agent_id") or stage.get("id") or "marketing-content-creator-agent",
                                            "task_instruction": stage.get("task_instruction") or stage.get("cmd") or stage.get("instruction") or stage.get("task") or "Process."
                                        })
                                if normalized_pipeline:
                                    workflows.append({"market": market_name, "pipeline": normalized_pipeline})
                elif isinstance(data, dict) and 'market' in data:
                    # Single market case
                    raw_pipe = data.get('pipeline') or data.get('steps') or data.get('agents')
                    if raw_pipe:
                         workflows.append({"market": data['market'], "pipeline": raw_pipe})

            except Exception as e:
                log.debug("JSON block processing failed: %s", e)
                continue

        # Heuristic/Fallback for Tag-based format [TASK_START] MARKET: ... [STRATEGY]: ... [TASK_END]
        if not workflows:
            log.info("JSON parsing failed to find workflows. Trying tag-based recovery.")
            # Be very aggressive in finding blocks. Look for anything between TASK_START/MARKET and TASK_END/MARKET
            blocks = re.findall(r'(?:\[TASK_START\]|MARKET:)(.*?)(?=\[TASK_START\]|\[TASK_END\]|MARKET:|$)', text, re.DOTALL | re.IGNORECASE)
            for block in blocks:
                # Handle [MARKET]: Japan, MARKET: Japan, [MARKET] Japan, etc.
                m_match = re.search(r'(?:\[?MARKET\]?):\s*(.*?)(?=\[|[A-Z]+:|$)', block, re.IGNORECASE)
                s_match = re.search(r'(?:\[?STRATEGY\]?|\[?CONSTRAINTS\]?):\s*(.*?)(?=\[|[A-Z]+:|$)', block, re.IGNORECASE)
                
                market_val = m_match.group(1).strip() if m_match else None
                strategy_val = s_match.group(1).strip() if s_match else "Create localized marketing content."
                
                if market_val:
                    workflows.append({
                        "market": market_val,
                        "pipeline": [
                            {
                                "stage_name": "content",
                                "agent_id": "marketing-content-creator-agent",
                                "task_instruction": strategy_val
                            }
                        ]
                    })

        if workflows:
            log.info("Successfully parsed %d workflows", len(workflows))
            return workflows

        return []


class MarketingOrchestrator(dspy.Module):
    def __init__(self,custom_doc_OrchestratorSignature,custom_doc_WorkerSignature):
        super().__init__()
        DynamicSignature_OrchestratorSignature = OrchestratorSignature.with_instructions(custom_doc_OrchestratorSignature)
        self.planner = dspy.ChainOfThought(DynamicSignature_OrchestratorSignature)
        self.parser = WorkflowParser()

    def forward(self, product_description, available_agents):
        # STEP 1: The Orchestrator plans the workflows based on available agents
        plan = self.planner(
            product_description=product_description,
            available_agents=available_agents
        )
        
        # dspy might return an empty list if it fails to parse the structured output field
        raw_output = getattr(plan, "workflow_plans", [])
        log.info("Initial dspy-parsed workflow_plans: Type=%s, Value=%s", type(raw_output), raw_output)

        # Ensure we have a list to work with
        final_list = []
        if isinstance(raw_output, list):
            for item in raw_output:
                if isinstance(item, dict):
                    final_list.append(item)
                elif hasattr(item, "model_dump"):
                    final_list.append(item.model_dump())
                elif hasattr(item, "dict"):
                    final_list.append(item.dict())

        # If empty, try manual parsing from raw text
        if not final_list:
            log.info("Structured output was empty. Attempting manual parsing from LLM response history.")
            
            raw_text = ""
            # Priority 1: Get from plan's raw_text if dspy populated it
            if hasattr(plan, "raw_text"):
                raw_text = plan.raw_text
                log.info("Found raw_text on plan object (Length: %d)", len(raw_text))

            # Priority 2: Get from LM history which is most reliable for custom LMs
            if not raw_text:
                try:
                    # In dspy, settings.lm is usually managed correctly within context
                    lm = dspy.settings.lm
                    log.info("Current dspy.settings.lm type: %s", type(lm))
                    if lm and hasattr(lm, "history") and lm.history:
                        last_entry = lm.history[-1]
                        resp = last_entry.get('response', [""])
                        raw_text = "\n".join(resp) if isinstance(resp, list) else str(resp)
                        log.info("Retrieved raw_text from LM history (Length: %d)", len(raw_text))
                    else:
                        log.warning("dspy.settings.lm has no history or is None")
                except Exception as e:
                    log.debug("Failed to access history: %s", e)

            # Priority 3: Fallback to str(plan) which sometimes has the text
            if not raw_text:
                raw_text = str(plan)
                log.info("Falling back to str(plan) for raw_text (Length: %d)", len(raw_text))

            if raw_text:
                parsed_workflows = self.parser.parse(raw_text)
                if parsed_workflows:
                    final_list = parsed_workflows
        
        log.info("Final structured workflows: %s", final_list)
        return final_list


class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        text = task.job_data["text"]
        session_id = task.job_data.get("session_id", "")
        communication_type = task.job_data.get("communication_type", "delegate")
        model_name = task.job_data.get("model_name", "")
        return text, session_id, communication_type, model_name


class ModelContextManager:
    def __init__(self, aios_dspy_lm: AIOS_DSPy_LMs):
        self.aios_dspy_lm = aios_dspy_lm

    def get_context(self, model_name: str, session_id: str):
        return dspy.context(
            lm=self.aios_dspy_lm.get_choosen_model(
                model_name=model_name,
                session_id=session_id
            )
        )


class PipelineExecutor:

    def __init__(self, context: Context):
        self.context = context
        self.mapping = {
            "content": ["content", "copy", "text", "article", "marketing content"],
            "social": ["social", "campaign", "platform", "post", "strategy"],
            "email": ["email", "mail", "newsletter", "send"],
            "review": ["review", "alignment", "score", "audit", "reviewer"],
            "visual_suggestions": ["visual suggestions", "visual concept"]
        }

    def _get_storage_key(self, stage_name: str, agent_id: str):
        assigned_category = None
        for cat, keywords in self.mapping.items():
            if any(k in stage_name.lower() for k in keywords) or (cat == "review" and "image-reviewer" in agent_id):
                assigned_category = cat
                break
        return assigned_category if assigned_category else stage_name

    def _prepare_stage_payload(self, market_name, instruction, last_output, market_output, text, last_output_before_image, pending_feedback):
        payload = {
            "market": market_name,
            "text": instruction,
            "previous_stage_output": last_output,
            "pipeline_context": market_output,
            "product_description": text,
            "session_id": str(uuid.uuid4()),
            "communication_type": "p2p"
        }
        if pending_feedback:
            payload["previous_stage_output"] = last_output_before_image
            payload["review_feedback"] = pending_feedback
        return payload

    def _parse_review_score(self, review_data):
        score = 0
        feedback = ""
        
        if isinstance(review_data, str) and (review_data.strip().startswith("{") or review_data.strip().startswith("[")):
            try:
                review_data_parsed = json.loads(review_data)
                if isinstance(review_data_parsed, dict):
                    review_data = review_data_parsed
            except:
                pass

        if isinstance(review_data, dict):
            score_raw = review_data.get("cultural_alignment_score", 0)
            feedback = review_data.get("review_feedback", "")
            try:
                if isinstance(score_raw, str):
                    match_score = re.search(r"(\d+)", score_raw)
                    score = int(match_score.group(1)) if match_score else 0
                else:
                    score = int(float(score_raw))
            except:
                score = 0
        return score, feedback

    def execute(self, task, workflow, text, results_dict):
        market_name = workflow.get("market", "Unknown")
        pipeline = workflow.get("pipeline", [])
        log.info(f"Starting dynamic pipeline for market: {market_name}")
        
        market_output = {"market": market_name, "review_history": [], "retry_count": 0}
        last_output = text
        
        try:
            max_image_retries = 1
            last_image_stage_idx = -1
            last_output_before_image = None
            pending_feedback = None
            current_image_data = {}
            
            i = 0
            while i < len(pipeline):
                stage = pipeline[i]
                stage_name = stage.get("stage_name", f"stage_{i}")
                agent_id = stage.get("agent_id")
                instruction = stage.get("task_instruction", "")
                
                log.info(f"[{market_name}] Executing Stage: {stage_name} with Agent: {agent_id}")
                
                is_generator_stage = "image-generator" in agent_id or ("image" in stage_name.lower() and "reviewer" not in agent_id)
                storage_key = self._get_storage_key(stage_name, agent_id)
                is_review_stage = storage_key == "review"

                if is_generator_stage and not pending_feedback:
                    last_output_before_image = last_output

                payload = self._prepare_stage_payload(
                    market_name, instruction, last_output, market_output, text, 
                    last_output_before_image, pending_feedback
                )
                
                if is_generator_stage:
                    last_image_stage_idx = i

                res = self.context.p2p_manager.send_and_wait_sync(
                    task_id=task.task_id, subject_id=agent_id, task_data=payload
                )
                
                job_output = res.get("data", {}).get("job_output", {})
                worker_text = job_output.get("text", "")
                final_text_content = job_output.get("text") or worker_text
                
                market_output[storage_key] = final_text_content
                
                if is_generator_stage:
                    current_image_data.update({
                        "stage_name": stage_name,
                        "instruction": instruction,
                        "text": final_text_content
                    })
                    img_url = job_output.get("image_url")
                    if img_url:
                        current_image_data["image_url"] = img_url
                        market_output["image"] = img_url
                
                if is_review_stage:
                    current_image_data.update({
                        "review_stage_name": stage_name,
                        "review_data": final_text_content
                    })
                    score, feedback = self._parse_review_score(final_text_content)
                    log.info(f"[{market_name}] Review Score: {score}, Threshold: 8")
                     
                    if score < 8 and max_image_retries > 0 and last_image_stage_idx != -1 and market_output.get("image"):
                        log.info(f"[{market_name}] Score {score} below 8. Triggering agentic retry.")
                        market_output["review_history"].append(current_image_data.copy())
                        market_output["retry_count"] += 1
                        pending_feedback = feedback or str(final_text_content)
                        max_image_retries -= 1
                        i = last_image_stage_idx
                        current_image_data = {}
                        continue
                    else:
                        pending_feedback = None 
                
                last_output = worker_text
                i += 1
                
            results_dict[market_name] = market_output
            log.info(f"[{market_name}] Dynamic pipeline completed successfully.")

        except Exception as e:
            log.error(f"Error in dynamic pipeline for {market_name}: {e}")
            market_output["error"] = str(e)
            results_dict[market_name] = market_output


class SampleAgent:

    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.marketing_orchestrator = MarketingOrchestrator(self.persona_default_system_message,"")
        self.pipeline_executor = PipelineExecutor(self.context)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)

        self.known_agents = KnownAgents(default_compact=False)
        self.known_agents.query_and_add(query={
            "metadata.subject_search_tags": "marketing"
        })
        log.info(f"Available marketing agents: {[agent.id for agent in self.known_agents.list_all()]}")

    def _get_available_agents_context(self) -> str:
        agents = []
        for agent in self.known_agents.list_all():
            if agent.id == self.subject.identity.subject_id:
                continue
                
            metadata = agent.subject.metadata.subject_metadata if hasattr(agent.subject.metadata, 'subject_metadata') else {}
            capabilities = metadata.get("capabilities_metadata", {})
            
            info = [
                f"Agent ID: {agent.id}",
                f"Name: {agent.subject.identity.subject_name}",
                f"Goal: {agent.subject.persona.goal}",
                f"Description: {capabilities.get('description') or agent.subject.metadata.subject_description}",
                f"Inputs: {capabilities.get('inputs', 'Not Specified')}",
                f"Outputs: {capabilities.get('outputs', 'Not Specified')}"
            ]
            agents.append("\n".join(info))
        
        return "\n---\n".join(agents)

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id}")
        text = task.job_data.get("text")
        if not text:
            log.warning("Task %s has no 'text' in job_data, skipping.", task.task_id)
            return None
        return [task]

    def _prepare_inputs(self, task: AgentTask):
        return self.payload_processor.prepare_payload(task)

    def _execute_worker(self, text, agents_context, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.marketing_orchestrator.forward(
                product_description=text,
                available_agents=agents_context
            )

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            text, session_id, communication_type, model_name = self._prepare_inputs(task)
            agents_context = self._get_available_agents_context()
            log.info("Available Agents Context: %s", agents_context)

            workflows = self._execute_worker(text, agents_context, model_name, session_id)
            log.info("Planned workflows: %s", workflows)

            if not workflows:
                return AgentResult(
                    task_id=task.task_id,
                    is_error=True,
                    error_data={"message": "No valid marketing pipeline could be planned with available agents."}
                )

            threads = []
            results_dict = {}

            for workflow in workflows:
                t = threading.Thread(
                    target=self.pipeline_executor.execute,
                    args=(task, workflow, text, results_dict)
                )
                t.start()
                threads.append(t)

            for t in threads:
                t.join()

            final_results = list(results_dict.values())
            log.info("All market pipelines completed.")
            
            return AgentResult(
                task_id=task.task_id,
                job_output={"text": json.dumps(final_results, indent=2)},
                job_output_metadata={"market_count": len(final_results)},
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
