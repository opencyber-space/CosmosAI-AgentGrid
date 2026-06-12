import logging
import copy
import random
import string
import os
from dotenv import load_dotenv

load_dotenv("/app/.env")
load_dotenv()

from google import genai
from google.genai import types
import dspy

from agents_llm import AIGridClient
from agents_llm.custom import OpenAIBlockInferenceSystem

log = logging.getLogger(__name__)


def clean_json_string(s: str) -> str:
    """Strips trailing DSPy/AIOS markers and common markdown wrappers."""
    if not s:
        return s
    # Strip markers like [[ ## completed ## ]]
    # Some older prompts might use [[[ or [[
    s = s.split('[[')[0].strip()
    
    # Strip markdown code blocks if present
    if s.startswith("```json"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


class CustomAIOS(dspy.LM):
    def __init__(self, model_name, llm_params, persona_default_system_message, blockDetails=None):
        super().__init__(model=model_name)
        self.persona_default_system_message = persona_default_system_message
        self.session_id = None
        self.model_name = model_name
        self.llm_ai = AIGridClient()
        # self.kwargs = {
        #     "temperature": llm_params.get("temperature", 0.7),
        #     "max_tokens": llm_params.get("max_tokens", 1024),
        #     "top_p": llm_params.get("top_p", 0.95),
        #     "top_k": llm_params.get("top_k", 40),
        # }
        
        if "aios:" in self.model_name:
            print("AIGRID_MASTER: ", os.environ.get("AIGRID_MASTER"))
            print("AIGRID_INFERENCE_SERVER_URL: ", os.environ.get("AIGRID_INFERENCE_SERVER_URL"))
            self.llm_ai.add_block(
                name=self.model_name,
                network_host=os.environ.get("AIGRID_MASTER"),
                inference_server_id="",
                model=self.model_name.replace("aios:", ""),
                mode="rest",
                block_data={},
                default_headers={},
                urls={"rest": os.environ.get("AIGRID_INFERENCE_SERVER_URL")}
            )
        elif "openai:" in self.model_name:
            llm_params_ = copy.deepcopy(llm_params)
            api_key = llm_params_.pop("api_key", None) or (blockDetails.api_key if hasattr(blockDetails, 'api_key') else (blockDetails.get('api_key') if blockDetails else None))
            llm_params = copy.deepcopy(llm_params_)
            openai_block = OpenAIBlockInferenceSystem(
                model=self.model_name.replace("openai:", "") or "gpt-4o-mini",
                api_key=api_key,
                default_system_prompt=self.persona_default_system_message
            )
            self.llm_ai.add_custom_block(name=self.model_name, system=openai_block)
        elif "google:" in self.model_name or "gemini:" in self.model_name:
            log.info(f"Adding google model {self.model_name} to pool llm_params:{llm_params} oneBlock:{blockDetails}")
            llm_params_ = copy.deepcopy(llm_params)
            api_key = llm_params_.pop("api_key", None) or (blockDetails.api_key if hasattr(blockDetails, 'api_key') else (blockDetails.get('api_key') if blockDetails else None))
            llm_params = copy.deepcopy(llm_params_)
            model_id = self.model_name.replace("google:", "").replace("gemini:", "gemini/")
            # if "gemini" in model_id and "2.5" not in model_id:
            #     model_id = "gemini-2.5-flash"
            
            #self.model = Google(model=model_id, api_key=api_key, **llm_params)
            #genai.configure(api_key=api_key)
            # Set up the Nano Banana model in DSPy
            # Note: "gemini-2.5-flash-image" is the official model name for Nano Banana
            #self.model = dspy.Google(model=model_id, api_key=api_key)
            log.info(f"api_key: {api_key}")
            log.info(f"Adding google model {self.model_name} to pool llm_params:{llm_params} oneBlock:{blockDetails}")
            gemini_model = dspy.LM(
                model=model_id, 
                api_key=api_key,
                system_prompt=self.persona_default_system_message
            )
            self.llm_ai.add_custom_block(name=self.model_name, system=gemini_model)

        self.llm_params = llm_params
        self.history = []

    def __call__(self, prompt=None, messages=None, **kwargs):
        log.info("CustomAIOS.__call__ prompt type: %s", type(prompt))
        if prompt and isinstance(prompt, str):
             log.info("CustomAIOS.__call__ prompt prefix: %s", prompt[:200])
        
        log.debug("CustomAIOS.__call__ messages: %s", messages)
        log.info("CustomAIOS.__call__ kwargs keys: %s", list(kwargs.keys()))
        
        system_message = self.persona_default_system_message
        if messages is not None:
             user_contents = []
             for msg in messages:
                 role = msg.get('role')
                 content = msg.get('content')
                 if role == 'system':
                     system_message = content
                 elif role == 'user':
                     if isinstance(content, str):
                         user_contents.append(content)
                     elif isinstance(content, list):
                         # Extract text from multi-modal content list
                         text_parts = [item['text'] for item in content if isinstance(item, dict) and item.get('type') == 'text']
                         user_contents.extend(text_parts)
             
             # If prompt was not provided directly, use the gathered user contents
             if prompt is None:
                 prompt = "\n\n".join(user_contents)
             else:
                 # If prompt IS provided, but we also have user messages, we should ensure context is preserved
                 # Usually DSPy either provides prompt OR messages, but we handle both for safety.
                 pass
        
        log.info("--- AIOS LLM PAYLOAD START ---")
        log.info(f"System Message: {system_message}")
        log.info(f"Final Prompt: {prompt}")
        log.info("--- AIOS LLM PAYLOAD END ---")

        llm_params = copy.deepcopy(self.llm_params)
        llm_params.update({
            "temperature": kwargs.get("temperature", self.llm_params.get("temperature", 0.7)),
            "max_tokens": kwargs.get("max_tokens", self.llm_params.get("max_tokens", 1200)),
            "top_p": kwargs.get("top_p", self.llm_params.get("top_p", 1.0)),
            "top_k": kwargs.get("top_k", self.llm_params.get("top_k", 40))
        })
        
        # Prioritize session_id from kwargs (per-call isolation)
        session_id = kwargs.get("session_id", self.session_id)
        if not session_id:
            possible_characters = string.digits
            session_id = "session-"+''.join(random.choice(possible_characters) for _ in range(5))

        out = ""
        log.info(f"CustomAIOS: Preparing for inference. Model: {self.model_name}, Session: {session_id}")
        log.info(f"CustomAIOS: llm_params: {llm_params} session_id: {session_id}")
        if "aios:" in self.model_name:
            log.info(f"CustomAIOS: Calling async_infer for {self.model_name}...")
            try:
                waiter = self.llm_ai.async_infer(name=self.model_name, session_id=session_id,
                    data={
                        "mode": "chat",
                        "generation_config": llm_params,
                        "message": prompt,
                        "system_message": system_message
                    })
                log.info(f"CustomAIOS: async_infer called, waiting for response...")
                result = waiter.wait()
                log.info(f"CustomAIOS: waiter.wait() finished.")
                data = result.get("data",{})
                out = data.get("reply") or data.get("generated") or ""
            except Exception as e:
                log.error(f"CustomAIOS: Error in AIOS path: {e}", exc_info=True)
                raise e
            log.info(f"AIOS response received (length: {len(out)})")
            if out:
                log.debug(f"AIOS response preview: {out[:200]}...")
        elif "openai:" in self.model_name:
            log.info(f"CustomAIOS: Calling chat_completions for {self.model_name}...")
            try:
                if "max_tokens" in llm_params:
                    del llm_params["max_tokens"]
                log.info(f"CustomAIOS: llm_params: {llm_params} session_id: {session_id}")
                result = self.llm_ai.chat_completions(name=self.model_name, session_id=session_id, messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ], data=llm_params)
                #log.info(f"CustomAIOS: chat_completions called, waiting for response...")
                #result = waiter.wait()
                out = None
                if isinstance(result, dict) and "choices" in result:
                    out = result["choices"][0]["message"]["content"]
                    log.info(f"AIOS response received (length: {len(out)})")
                else:
                    log.warning("Could not extract message from result. Expected a dict with 'choices'.")
                if out:
                    log.debug(f"AIOS response preview: {out[:200]}...")
            except Exception as e:
                log.error(f"CustomAIOS: Error in OpenAI path: {e}", exc_info=True)
                raise e
        elif "google:" in self.model_name or "gemini:" in self.model_name:
            log.info(f"CustomAIOS: Calling Google LM instance for {self.model_name}...")
            try:
                # The user registered a dspy.LM instance via add_custom_block
                lm_instance = self.llm_ai.get(self.model_name)
                
                # log full messages for better debugging of multi-modal data
                if messages:
                    log.info("Passing %d messages to Google LM", len(messages))
                    for i, m in enumerate(messages):
                        content = m.get('content')
                        content_info = f"type: {type(content)}"
                        if isinstance(content, list):
                             content_info += f", parts: {len(content)}, types: {[type(p.get('image_url') or p.get('text')) for p in content if isinstance(p, dict)]}"
                        elif isinstance(content, str):
                             content_info += f", length: {len(content)}"
                        log.info("Message %d role: %s, content info: %s", i, m.get('role'), content_info)
                
                # Pass everything as received to the underlying dspy.LM
                out = lm_instance(prompt=prompt, messages=messages, **kwargs)
                log.info(f"Google model {self.model_name} generated response: {out}")
                # dspy.LM returns a list of strings
                return out
            except Exception as e:
                log.error(f"CustomAIOS: Error in Google path: {e}", exc_info=True)
                raise e

        self.history.append({
            "prompt": prompt,
            "response": [out],
            "kwargs": llm_params
        })
        return [out]

    # Add forward for dspy compatibility
    def forward(self, *args, **kwargs):
        return self.__call__(*args, **kwargs)

class AIOS_DSPy_LMs():
    def __init__(self, subject):
        self.subject = subject
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.model_pool = {}
        models = self.subject.integrations.models if hasattr(self.subject.integrations, 'models') else (self.subject.integrations.get('models', []) if self.subject.integrations else [])
        for oneBlock in models:
            model_name = oneBlock.llm_block_id if hasattr(oneBlock, 'llm_block_id') else oneBlock.get('llm_block_id')
            llm_params = oneBlock.llm_parameters if hasattr(oneBlock, 'llm_parameters') else oneBlock.get('llm_parameters', {})
            log.info(f"Adding model {model_name} to pool llm_params:{llm_params} oneBlock:{oneBlock}")
            self.model_pool[model_name] = CustomAIOS(model_name=model_name, llm_params=llm_params, persona_default_system_message=self.persona_default_system_message, blockDetails=oneBlock)

    def get_choosen_model(self, **kwargs):
        model_name = kwargs.get("model_name", "")
        if model_name and model_name not in list(self.model_pool.keys()):
            model_name = random.choice(list(self.model_pool.keys()))

        chosen_lm = self.model_pool.get(model_name)
        if not chosen_lm:
            raise ValueError("Selected model not available.")

        # Patch Google if missing
        # dspy = get_dspy()
        # if not hasattr(dspy, 'Google'):
        #     dspy.Google = Google
            
        # Ensure chosen_lm is seen as a dspy.LM for context manager
        # if not hasattr(chosen_lm, 'copy'): # dspy.LM has copy
        #      chosen_lm.__class__ = type("CustomAIOS", (chosen_lm.__class__, dspy.LM), {})
        #      # dspy.LM.__init__ might need more, but CustomAIOS already has history etc.

        chosen_lm.session_id = kwargs.get("session_id", "")
        return chosen_lm

    def get_any_model(self, **kwargs):
        return random.choice(list(self.model_pool.keys()))
    