import logging
import uuid
import json
import dspy
import io
import os
from minio import Minio
from datetime import timedelta
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

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

class FrontendDevAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.plan_module = FrontendCodePlanModule(self.persona_default_system_message)
        self.synthesis_module = FrontendCodeSynthesisModule(self.persona_default_system_message)
        his_config = self.subject.persona.config.get("parameters", {})
        self.minio_config = his_config.get("MINIO_CONFIG", {})
        self.minio_uploader = MinioCodeUploader(self.minio_config)
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
            # Check for problem_statement or architecture
            if "problem_statement" in task.job_data or "architecture" in task.job_data:
                return [task]
            log.warning("Task %s has no 'text' in job_data, skipping.", task.task_id)
            return None
        return [task]
    def _log_to_his(self, target_id, job_data):
        try:
            msg = {"text": str(job_data), "source_id": self.subject.identity.subject_id, "destination_id": target_id, "team": "Developer Team"}
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

            architecture = data.get("architecture", "Generic architecture pending")
            dev_pointers = data.get("dev_pointers", "Build standard dynamic frontend.")
            deliverables = data.get("deliverables", [])
            llm_session_id = str(uuid.uuid4())
            model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
            communication_type = data.get("communication_type", "delegate")

            with dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=llm_session_id)):
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
                        lines = file_content.split("\\n")
                        file_content = "\\n".join(lines[1:-1])

                    # Save Locally
                    local_path = os.path.join(local_dir, fname.replace("/", "_"))
                    with open(local_path, "w") as f:
                        f.write(file_content)
                    
                    # Upload to MinIO
                    uploaded_url = self.minio_uploader.upload(file_content, fname, llm_session_id, task_id)
                    file_urls[fname] = uploaded_url
                    synthesized_files[fname] = True
            
            output_data = {
                "ui_description": "Frontend implementation complete.",
                "implementation_summary": f"Successfully planned and generated {len(synthesized_files)} files.",
                "code_plan": code_plan,
                "file_urls": file_urls
            }

            parent_id = "company-developer-team-lead"
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

            if communication_type == "delegate":
                self._log_to_his(parent_id, job_data)
                self.context.delegator.submit_and_wait(subject_id=parent_id, session_id=llm_session_id, task_id=task.task_id, task_data=job_data)
            else:
                self._log_to_his(parent_id, job_data)
                self.context.p2p_manager.send_sync(task=task, subject_id=parent_id, job_data=job_data, session_id=llm_session_id)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Frontend Dev: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(FrontendDevAgent)
