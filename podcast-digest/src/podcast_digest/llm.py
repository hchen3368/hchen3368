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
        if self.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        response = self.client.responses.create(**kwargs)
        text = response.output_text.strip()
        if not text:
            raise RuntimeError(f"{self.name} returned an empty response (status={response.status})")
        return text
