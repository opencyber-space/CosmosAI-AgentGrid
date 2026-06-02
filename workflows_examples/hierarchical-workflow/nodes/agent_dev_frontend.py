import logging
import uuid
import json
import io
import os
import time
import dspy
from minio import Minio
from datetime import timedelta
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "agent-workflow-developer-team-lead": "my-company-developer-team-lead-agent",
    "agent-workflow-dev-backend": "my-company-dev-backend-agent",
    "agent-workflow-dev-frontend": "my-company-dev-frontend-agent"
}
DEV_TEAM_LEAD = "my-company-developer-team-lead-agent"
DEV_BACKEND = "my-company-dev-backend-agent"
DEV_FRONTEND = "my-company-dev-frontend-agent"

# MinIO Config

class MinioCodeUploader:
    def __init__(self, minio_config):
        self.minio_config = minio_config
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

    def upload(self, code_string, filename, session_id, task_id):
        safe_filename = filename.replace("/", "_")
        object_name = f"{session_id}/{safe_filename}"
        
        data_bytes = code_string.encode('utf-8')
        self.minio_client.put_object(
            self.minio_bucket,
            object_name,
            io.BytesIO(data_bytes),
            length=len(data_bytes),
            content_type="text/plain"
        )
        file_url = self.minio_client.presigned_get_object(self.minio_bucket, object_name, expires=timedelta(hours=1))
        file_url = file_url.replace(self.minio_config["MINIO_URL"], self.minio_config.get("MINIO_EXTERNAL_URL"))
        file_url = file_url.replace(self.minio_internal_port, self.minio_external_port)
        return file_url.split("?")[0]

class CodePlanSignature(dspy.Signature):
    """
    ### ROLE
    You are the Frontend Developer.

    ### TASK
    Generate a complete project code plan consisting of a list of files necessary to build the frontend requirements. Include dependency files like `package.json` where applicable, but DO NOT include any bash or setup scripts (e.g., `setup.sh`).
    Keep the plan concise. Do NOT generate huge nested arrays.

    ### OUTPUT
    Output EXACTLY a valid JSON block mirroring this syntax:
    {"code_plan": [{"filename": "example.js", "description": "foo"}, {"filename": "setup.sh", "description": "bar"}]}
    All keys MUST be double-quoted. Do NOT wrap in generic text.
    """
    problem_statement = dspy.InputField(desc="The product idea")
    architecture = dspy.InputField(desc="The system architecture design")
    dev_pointers = dspy.InputField(desc="Specific frontend UI/UX implementation pointers from the Team Lead")
    output_data = dspy.OutputField(desc="""Valid JSON block: {"code_plan": [{"filename": "string", "description": "string"}]}""")

class CodeFileSynthesisSignature(dspy.Signature):
    """
    ### ROLE
    You are the Frontend Developer writing production-ready code.

    ### TASK
    Write the exact raw file content for the requested filename. Include everything required (imports, full logic). Do not abbreviate.
    CRITICAL: Avoid repeating patterns, deep directory trees, or recursive code generation. Be concise and functional.
    Do NOT output JSON. Just output the raw file content. Do not use markdown codeblocks.

    ### OUTPUT
    Output the exact string content of the file.
    """
    architecture = dspy.InputField(desc="The system architecture design")
    dev_pointers = dspy.InputField(desc="Specific frontend pointers from the Team Lead")
    filename = dspy.InputField(desc="The filename to generate")
    file_description = dspy.InputField(desc="What this file should contain")
    file_content = dspy.OutputField(desc="Exact raw file content string")

class FrontendCodePlanModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.worker = dspy.ChainOfThought(CodePlanSignature)

    def forward(self, problem_statement, architecture, dev_pointers):
        return self.worker(
            problem_statement=json.dumps(problem_statement), 
            architecture=json.dumps(architecture),
            dev_pointers=json.dumps(dev_pointers)
        )

class FrontendCodeSynthesisModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.worker = dspy.ChainOfThought(CodeFileSynthesisSignature)

    def forward(self, architecture, dev_pointers, filename, file_description):
        return self.worker(
            architecture=json.dumps(architecture),
            dev_pointers=json.dumps(dev_pointers),
            filename=filename,
            file_description=file_description
        )

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

class FrontendDevAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.plan_module = FrontendCodePlanModule(self.persona_default_system_message)
        self.synthesis_module = FrontendCodeSynthesisModule(self.persona_default_system_message)
        
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        self.task_registry = {}
        
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.minio_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("MINIO_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.minio_uploader = MinioCodeUploader(self.minio_config)

        # Initialize HIS Client
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        task_type = task.job_data.get("task_type")
        if task_type != "execute_task":
            log.warning("Task %s has task_type %s, which is not execute_task, skipping Frontend Developer.", task.task_id, task_type)
            return None
        return [task]

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Developer Team", "timestamp": time.time()}
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

            # problem_statement is inside 'text' or passed directly
            text = data.get("text")
            problem_statement = json.loads(text) if isinstance(text, str) and text.startswith("{") else (data.get("problem_statement") or raw_text)

            architecture = data.get("architecture", "Generic architecture pending")
            dev_pointers = data.get("frontend_pointers") or data.get("dev_pointers") or "Build standard dynamic frontend."
            llm_session_id = data.get("session_id", str(uuid.uuid4()))

            with self.model_context.get_context(model_name=model_name, session_id=llm_session_id):
                # Step 1: Generate File Plan
                log.info("Frontend Dev generating code plan...")
                plan_result = self.plan_module.forward(
                    problem_statement=problem_statement, 
                    architecture=architecture,
                    dev_pointers=dev_pointers
                )
                
                try:
                    plan_data = extract_json(plan_result.output_data)
                    code_plan = plan_data.get("code_plan", [])
                except Exception as e:
                    log.error(f"Frontend Dev failed to parse code_plan JSON: {e}")
                    code_plan = []
                
                # Step 2: Iteratively Synthesize Code Files
                log.info(f"Frontend Dev plan established: {len(code_plan)} files. Synthesizing...")
                synthesized_files = {}
                file_urls = {}
                local_dir = f"/tmp/dev_output/frontend/{task_id}/"
                os.makedirs(local_dir, exist_ok=True)

                for file_info in code_plan:
                    fname = file_info.get("filename", "unknown.txt")
                    fdesc = file_info.get("description", "")
                    log.info(f"Synthesizing file: {fname}")
                    
                    syn_result = self.synthesis_module.forward(
                        architecture=architecture,
                        dev_pointers=dev_pointers,
                        filename=fname,
                        file_description=fdesc
                    )
                    
                    try:
                        file_content = syn_result.file_content
                    except Exception as e:
                        log.error(f"Failed to get file_content for file {fname}. Skipping. Error: {e}")
                        continue
                    
                    # Ensure no backticks leak into content
                    file_content = file_content.strip()
                    if file_content.startswith("```"):
                        lines = file_content.split("\n")
                        file_content = "\n".join(lines[1:-1])

                    # Save Locally
                    local_path = os.path.join(local_dir, fname.replace("/", "_"))
                    with open(local_path, "w") as f:
                        f.write(file_content)
                    
                    # Upload to MinIO
                    uploaded_url = self.minio_uploader.upload(file_content, fname, llm_session_id, task_id)
                    file_urls[fname] = uploaded_url
                    synthesized_files[fname] = True

                    #Comment below break if you need all code files
                    #currently we will be writing only one code file for saving time
                    break
            
            output_data = {
                "ui_description": "Frontend implementation complete.",
                "implementation_summary": f"Successfully planned and generated {len(synthesized_files)} files.",
                "code_plan": code_plan,
                "file_urls": file_urls
            }

            parent_id = DEV_TEAM_LEAD
            job_data = {
                "task_type": "specialist_report",
                "specialist_report": output_data,
                "role": "Frontend Developer",
                "session_id": llm_session_id,
                "model_name": model_name,
                "communication_type": communication_type,
                "task_id": task_id,
                "user_request": self.task_registry[task_id].get("user_request")
            }

            self._log_to_his(parent_id, job_data)
            return AgentResult(task_id=task.task_id, job_output=job_data, job_output_metadata={}, is_error=False)

        except Exception as e:
            log.exception(f"Error in Frontend Dev: {e}")
            return AgentResult(task_id=task.task_id, job_output={}, job_output_metadata={}, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(FrontendDevAgent)
