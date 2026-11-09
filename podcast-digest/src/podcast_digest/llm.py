from __future__ import annotations

from typing import Protocol


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


class OpenAILLM:
    def __init__(self, model: str = "gpt-5.4-mini", reasoning_effort: str | None = "low", client=None):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self._client = client
        self.name = f"openai:{model}"

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI()
        return self._client

    def complete(self, system: str, user: str) -> str:
        kwargs = {"model": self.model, "instructions": system, "input": user}
        if self.reasoning_effort and is_reasoning_model(self.model):
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        response = self.client.responses.create(**kwargs)
        if response.status != "completed":
            raise RuntimeError(f"{self.name} response {response.status}: {response.incomplete_details}")
        text = response.output_text.strip()
        if not text:
            raise RuntimeError(f"{self.name} returned an empty response")
        return text


def is_reasoning_model(model: str) -> bool:
    return model.startswith(("gpt-5", "o1", "o3", "o4"))
