import os
import uuid
import tempfile
import requests
import subprocess
import tarfile
import zipfile
import json
import hashlib
import logging
from pathlib import Path
import shutil

logging.basicConfig(level=logging.INFO)


class BinaryToolExecutor:
    def __init__(self, download_url: str, tool_id: str, tool_data: dict):
        self.download_url = download_url
        self.session_uuid = str(uuid.uuid4())
        self.temp_dir = Path(f"/tmp/{self.session_uuid}")
        self.code_dir = self.temp_dir / "code"
        self.output_file = self.temp_dir / "output.json"
        self.binary_file = None
        self.cache = {}
        self.tool_data = tool_data
        self.tool_id = tool_id

    def download(self):
        # Check if the path is a local file or directory
        target_path = Path(self.download_url)

        if target_path.exists():
            if target_path.is_file() and (target_path.suffix in [".gz", ".zip"] or target_path.suffixes[-2:] == [".tar", ".gz"]):
                logging.info(f"Using local archive: {target_path}")
                return target_path
            elif target_path.is_dir():
                logging.info(f"Using local directory: {target_path}")
                self.code_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(target_path, self.code_dir, dirs_exist_ok=True)
                logging.info(f"Copied local directory to {self.code_dir}")
                return None  # No need to unpack or download
            else:
                raise ValueError(
                    "Unsupported local path format or non-existing path")

        # Handle remote downloads
        url_hash = hashlib.md5(self.download_url.encode()).hexdigest()
        if url_hash in self.cache:
            logging.info("Loading from cache")
            cached_path = Path(self.cache.get(url_hash))
            if cached_path.exists():
                return cached_path

        try:
            response = requests.get(self.download_url, stream=True)
            response.raise_for_status()
            archive_path = self.temp_dir / "archive"
            with open(archive_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            self.cache[url_hash] = str(archive_path)
            logging.info(f"Downloaded and cached file to {archive_path}")
            return archive_path
        except requests.exceptions.RequestException as e:
            logging.error(f"Error downloading file: {e}")
            raise

    def unpack(self, archive_path):
        if not archive_path:
            # If archive_path is None, it means the code was copied directly from a directory
            logging.info(
                "No extraction needed (code directory already populated)")
            return

        try:
            if tarfile.is_tarfile(archive_path):
                with tarfile.open(archive_path) as tar:
                    tar.extractall(self.temp_dir)
                    logging.info(f"Extracted tar file to {self.temp_dir}")
            elif zipfile.is_zipfile(archive_path):
                with zipfile.ZipFile(archive_path, "r") as zip_ref:
                    zip_ref.extractall(self.temp_dir)
                    logging.info(f"Extracted zip file to {self.temp_dir}")
            else:
                logging.error("Unsupported file format")
                raise ValueError("Unsupported file format")
            self.binary_file = next(
                self.code_dir.glob("*"), None
            )  # Find the binary file
            if not self.binary_file or not self.binary_file.is_file():
                raise FileNotFoundError("Binary file not found in archive")
        except Exception as e:
            logging.error(f"Error extracting archive: {e}")
            raise

    def execute_binary(self, input_data):
        try:
            # Ensure the binary file exists
            if not self.binary_file or not self.binary_file.exists():
                raise RuntimeError("Binary file not found or not initialized")

            # Serialize input data to JSON
            input_json = json.dumps({
                "tool_id": self.tool_id,
                "tool_data": self.tool_data,
                "mode": "input",
                "input": input_data
            })

            # Prepare the subprocess command
            command = [
                str(self.binary_file),
                input_json,
                str(self.output_file)
            ]

            # Execute the binary
            subprocess.run(command, check=True)
            logging.info(f"Executed binary: {self.binary_file}")

            # Read the output from the file
            with open(self.output_file, "r") as f:
                output_data = json.load(f)

            return output_data
        except subprocess.CalledProcessError as e:
            logging.error(f"Binary execution failed: {e}")
            raise
        except FileNotFoundError:
            logging.error("Output file not found")
            raise
        except json.JSONDecodeError as e:
            logging.error(f"Error parsing output JSON: {e}")
            raise

    def execute_command(self, command_name: str, data: dict):
        return {"success": False, "message": "management commands not available for binaries"}

    def execute(self, input_data):
        try:
            archive_path = self.download()
            self.unpack(archive_path)
            return self.execute_binary(input_data)
        except Exception as e:
            logging.error(f"Execution failed: {e}")
            raise
