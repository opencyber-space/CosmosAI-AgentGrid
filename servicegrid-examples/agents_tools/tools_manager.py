import logging

from typing import Any, Dict
from .db_client import ToolsRegistrySDK
from .runtimes.python_executor import LocalToolExecutor
from .runtimes.binary_executor import BinaryToolExecutor

logging.basicConfig(level=logging.INFO)


class ToolsExecutionManager:
    def __init__(self, base_url: str):

        self.base_url = base_url
        self.tool_instances: Dict[str, ToolExecutor] = {}
        self.sdk = ToolsRegistrySDK(base_url)

    def validate_input(self, input_data, api_spec):

        def validate(data, spec, path="root"):
            if not isinstance(spec, dict):
                raise ValueError(
                    f"Invalid API spec at {path}. Must be a dict.")

            for key, constraints in spec.items():
                if key not in data:
                    raise ValueError(
                        f"Missing required field '{key}' at {path}.")

                value = data[key]
                field_type = constraints.get("type", "any")

                # Type validation
                if field_type == "number":
                    if not isinstance(value, (int, float)):
                        raise ValueError(
                            f"Field '{key}' at {path} must be a number.")
                    if "min" in constraints and value < constraints["min"]:
                        raise ValueError(
                            f"Field '{key}' at {path} must be >= {constraints['min']}.")
                    if "max" in constraints and value > constraints["max"]:
                        raise ValueError(
                            f"Field '{key}' at {path} must be <= {constraints['max']}.")
                elif field_type == "string":
                    if not isinstance(value, str):
                        raise ValueError(
                            f"Field '{key}' at {path} must be a string.")
                    if "choices" in constraints and value not in constraints["choices"]:
                        raise ValueError(
                            f"Field '{key}' at {path} must be one of {constraints['choices']}.")
                elif field_type == "array":
                    if not isinstance(value, list):
                        raise ValueError(
                            f"Field '{key}' at {path} must be an array.")
                elif field_type == "object":
                    if not isinstance(value, dict):
                        raise ValueError(
                            f"Field '{key}' at {path} must be an object.")
                    nested_spec = constraints.get("properties", {})
                    validate(value, nested_spec, path=f"{path}.{key}")
                elif field_type == "any":
                    pass  # No validation required for "any"
                else:
                    raise ValueError(
                        f"Unsupported type '{field_type}' for field '{key}' at {path}.")

        validate(input_data, api_spec)
        return True

    def register(self, instance_name, tool_id, parameters):

        try:
            logging.info(
                f"Registering tool: instance_name={instance_name}, tool_id={tool_id}")
            tool_data = self.sdk.get_tool_by_id(tool_id)

            if instance_name in self.tool_instances:
                raise ValueError(
                    f"Instance {instance_name} is already registered.")

            tool_data['tool_parameters'].update(parameters)

            # Initialize the appropriate executor
            if tool_data["tool_runtime_type"] == "python" or tool_data["tool_runtime_type"] == "":
                executor = LocalToolExecutor(
                    download_url=tool_data["tool_source_code_link"],
                    tool_id=tool_id,
                    tool_data=tool_data
                )

                executor.init()

            else:
                executor = BinaryToolExecutor(
                    download_url=tool_data["tool_source_code_link"],
                    tool_id=tool_id,
                    tool_data=tool_data
                )

            # Store the executor and tool data
            self.tool_instances[instance_name] = {
                "executor": executor,
                "tool_data": tool_data
            }
            logging.info(f"Successfully registered tool: {instance_name}")

        except Exception as e:
            logging.error(
                f"Error registering tool: instance_name={instance_name}, error={e}")
            raise

    def unregister(self, instance_name):

        try:
            logging.info(f"Unregistering tool: instance_name={instance_name}")
            if instance_name in self.tool_instances:
                del self.tool_instances[instance_name]
                logging.info(
                    f"Successfully unregistered tool: {instance_name}")
            else:
                raise KeyError(f"Instance {instance_name} not found.")
        except Exception as e:
            logging.error(
                f"Error unregistering tool: instance_name={instance_name}, error={e}")
            raise

    def execute(self, instance_name, input_data):

        try:
            logging.info(
                f"Executing tool: instance_name={instance_name}, input_data={input_data}")
            if instance_name not in self.tool_instances:
                raise KeyError(f"Instance {instance_name} not found.")

            instance = self.tool_instances[instance_name]
            tool_data = instance["tool_data"]
            api_spec = tool_data.get("tool_api_spec", {})

            # Validate input_data against the api_spec
            # self.validate_input(input_data, api_spec)

            # Execute the tool
            executor = instance["executor"]
            result = executor.evaluate(input_data)
            logging.info(f"Successfully executed tool: {instance_name}")
            return result

        except Exception as e:
            logging.error(
                f"Error executing tool: instance_name={instance_name}, error={e}")
            raise

    def execute_command(self, instance_name, command_name, command_data):
        return self.tool_instances[instance_name]["executor"].execute_command(
            command_name, command_data
        )

    def get_instance_data(self, instance_name):

        try:
            logging.info(f"Fetching data for instance: {instance_name}")
            if instance_name in self.tool_instances:
                return self.tool_instances[instance_name]["tool_data"]
            else:
                raise KeyError(f"Instance {instance_name} not found.")
        except Exception as e:
            logging.error(
                f"Error fetching instance data: instance_name={instance_name}, error={e}")
            raise


class ToolExecutor:
    def __init__(self, tool_id, tool_data):
        self.tool_id = tool_id
        self.tool_data = tool_data
        self.executor = self._initialize_executor()

    def _initialize_executor(self):
        if self.tool_data["tool_runtime_type"] == "python":
            return LocalToolExecutor(
                download_url=self.tool_data["tool_source_code_link"],
                tool_id=self.tool_id,
                tool_data=self.tool_data
            )
        else:
            return BinaryToolExecutor(
                download_url=self.tool_data["tool_source_code_link"],
                tool_id=self.tool_id,
                tool_data=self.tool_data
            )

    def validate_input(self, input_data):
        def validate(data, spec, path="root"):
            if not isinstance(spec, dict):
                raise ValueError(
                    f"Invalid API spec at {path}. Must be a dict.")

            for key, constraints in spec.items():
                if key not in data:
                    raise ValueError(
                        f"Missing required field '{key}' at {path}.")

                value = data[key]
                field_type = constraints.get("type", "any")

                if field_type == "number" and not isinstance(value, (int, float)):
                    raise ValueError(
                        f"Field '{key}' at {path} must be a number.")
                elif field_type == "string" and not isinstance(value, str):
                    raise ValueError(
                        f"Field '{key}' at {path} must be a string.")
                elif field_type == "array" and not isinstance(value, list):
                    raise ValueError(
                        f"Field '{key}' at {path} must be an array.")
                elif field_type == "object" and not isinstance(value, dict):
                    raise ValueError(
                        f"Field '{key}' at {path} must be an object.")
                elif field_type == "any":
                    pass
                else:
                    raise ValueError(
                        f"Unsupported type '{field_type}' for field '{key}' at {path}.")

        api_spec = self.tool_data.get("tool_api_spec", {})
        validate(input_data, api_spec)
        return True

    def execute(self, input_data):
        try:
            logging.info(
                f"Executing tool: tool_id={self.tool_id}, input_data={input_data}")
            # self.validate_input(input_data)
            result = self.executor.execute(input_data)
            logging.info(f"Successfully executed tool: tool_id={self.tool_id}")
            return result
        except Exception as e:
            logging.error(
                f"Error executing tool: tool_id={self.tool_id}, error={e}")
            raise

    def execute_command(self, command_name, command_data):
        return self.executor.execute_command(command_name, command_data)
