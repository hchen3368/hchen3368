from __future__ import annotations

import json
from typing import Protocol


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...

    def complete_json(self, system: str, user: str, name: str, schema: dict) -> dict: ...


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
        return self._create(system, user)

    def complete_json(self, system: str, user: str, name: str, schema: dict) -> dict:
        text_format = {"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}}
        return json.loads(self._create(system, user, text=text_format))

    def _create(self, system: str, user: str, **extra) -> str:
        kwargs = {"model": self.model, "instructions": system, "input": user, **extra}
        if self.reasoning_effort and is_reasoning_model(self.model):
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        response = self._stream(kwargs)
        if response.status != "completed":
            raise RuntimeError(f"{self.name} response {response.status}: {response.incomplete_details}")
        text = response.output_text.strip()
        if not text:
            raise RuntimeError(f"{self.name} returned an empty response")
        return text

    def _stream(self, kwargs: dict):
        """Streams so long generations keep the connection busy instead of timing out at a gateway."""
        final = None
        for event in self.client.responses.create(**kwargs, stream=True):
            if event.type in ("response.completed", "response.incomplete", "response.failed"):
                final = event.response
        if final is None:
            raise RuntimeError(f"{self.name} stream ended without a final response")
        return final


def is_reasoning_model(model: str) -> bool:
    return model.startswith(("gpt-5", "o1", "o3", "o4"))
