import json
from pydantic import BaseModel, Field
from typing import List

# --- Pydantic Classes (copy/paste from above) ---

class AgentTurn(BaseModel):
    agent_name: str
    output: str

class AgentChainContext(BaseModel):
    original_user_request: str
    history: List[AgentTurn] = Field(default_factory=list)

    def add_turn(self, agent_name: str, output: str):
        new_turn = AgentTurn(agent_name=agent_name, output=output)
        self.history.append(new_turn)

    def get_prompt_for_next_agent(self, task_description: str, history_depth: int = -1) -> str:
        prompt = f"### Original User Request ###\n{self.original_user_request}\n\n"
        if self.history and history_depth != 0:
            prompt += "### Previous Work ###\n"
            if history_depth == -1:
                steps_to_show = self.history
            else:
                steps_to_show = self.history[-history_depth:]
            for step in steps_to_show:
                prompt += f"--- Output from {step.agent_name} ---\n{step.output}\n\n"
        if task_description:
            prompt += f"### Your Current Task ###\n{task_description}\n"
        else:
            pass
        return prompt

class AgentMuxContext(BaseModel):
    original_user_request: str = ""
    muxed_inputs: List[AgentTurn] = Field(default_factory=list)

    def add_original_user_request(self, request: str):
        self.original_user_request = request

    def add_muxed_input(self, agent_name: str, output: str):
        new_input = AgentTurn(agent_name=agent_name, output=output)
        self.muxed_inputs.append(new_input)

    def get_prompt_for_next_agent(self, task_description: str, history_depth: int = -1) -> str:
        prompt = f"### Original User Request ###\n{self.original_user_request}\n\n"
        if self.muxed_inputs:
            prompt += "### Muxed Inputs from Parallel Agents ###\n"
            for input_turn in self.muxed_inputs:
                prompt += f"--- Input from {input_turn.agent_name} ---\n{input_turn.output}\n\n"

        if task_description:
            prompt += f"### Your Current Task ###\n{task_description}\n"
        else:
            pass
        return prompt