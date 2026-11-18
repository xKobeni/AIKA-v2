from typing import TypedDict

from src.config import Settings


class ChatMessage(TypedDict):
    role: str
    content: str


class OllamaError(Exception):
    """An Ollama failure safe to display to the user."""


class ModelUnavailable(OllamaError):
    """Ollama responded, but the selected model cannot be used locally."""


class OllamaClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.probe_timeout = min(3.0, settings.model_timeout)

    def check_model(self) -> dict:
        payload = self._request("GET", "/api/tags", self.probe_timeout)
        models = payload.get("models")
        if not isinstance(models, list):
            raise OllamaError("Ollama returned an invalid model list.")

        model = self.settings.model.casefold()
        if ":" not in model.rsplit("/", 1)[-1]:
            model += ":latest"
        for entry in models:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                raise OllamaError("Ollama returned an invalid model list.")
            if entry["name"].casefold() == model:
                if entry.get("remote_host") or entry.get("remote_model"):
                    raise ModelUnavailable(f"{self.settings.model} uses a remote model. Select an installed local model.")
                return entry
        raise self._missing_model()

    def generate(self, messages: list[ChatMessage]) -> str:
        """Return one assistant answer from the supplied messages."""
        think = self._thinking_value(self.check_model())
        body = {"model": self.settings.model, "messages": messages, "stream": False, "options": {"temperature": 0.2}}
        if think is not None:
            body["think"] = think
        payload = self._request("POST", "/api/chat", self.settings.model_timeout, body)
        message = payload.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant" or payload.get("done") is not True:
            raise OllamaError("Ollama returned an incomplete or invalid assistant response. Try again.")
        if payload.get("done_reason") == "length":
            raise OllamaError("Ollama reached its generation limit before completing the answer. Try a shorter request.")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise OllamaError("Ollama returned no usable assistant text. Try again or select another chat model.")
        return content.strip()

    def _thinking_value(self, model: dict) -> bool | str | None:
        mode = self.settings.ollama_think
        if mode == "default":
            return None

        capabilities = model.get("capabilities")
        if isinstance(capabilities, list) and "thinking" not in capabilities:
            if mode == "off":
                return None
            raise OllamaError("The selected model does not support thinking. Set AIKA_OLLAMA_THINK=off.")

        if capabilities is None and mode == "off":
            # Older model lists may omit capabilities. Preserve the original boolean request.
            return False

        details = self._request("POST", "/api/show", self.probe_timeout, {"model": self.settings.model})
        thinking = details.get("thinking")
        values = thinking.get("values") if isinstance(thinking, dict) else None
        if isinstance(values, list):
            supports_boolean = any(value is True for value in values)
            levels = [value for value in values if isinstance(value, str)]
            if mode == "off":
                # Ollama maps false to the lowest supported level for models that require thinking.
                return False if supports_boolean or levels else None
            if supports_boolean:
                return True
            if levels:
                default = thinking.get("default")
                return default if default in levels else levels[0]
        else:
            reported_capabilities = details.get("capabilities")
            if isinstance(reported_capabilities, list) and "thinking" in reported_capabilities:
                return mode == "on"

        if mode == "on":
            raise OllamaError("Ollama did not report supported thinking controls. Set AIKA_OLLAMA_THINK=default or off.")
        return None

    def _missing_model(self) -> ModelUnavailable:
        model = self.settings.model
        return ModelUnavailable(f"Model {model} is unavailable. Run `ollama pull {model}` or select an installed model.")

    def _request(self, method: str, path: str, timeout: float, body: dict | None = None) -> dict:
        try:
            import httpx
        except ImportError:
            raise OllamaError("HTTPX could not load. Install the project dependencies with `python -m pip install -e .`.") from None

        try:
            response = httpx.request(
                method,
                self.settings.runtime_url.rstrip("/") + path,
                json=body,
                timeout=httpx.Timeout(timeout, connect=self.probe_timeout),
                trust_env=False,
                follow_redirects=False,
            )
            response.raise_for_status()
        except httpx.ConnectError:
            raise OllamaError("Cannot connect to Ollama. Open Ollama or run `ollama serve`, then try again.") from None
        except httpx.TimeoutException:
            if path == "/api/chat":
                raise OllamaError("Ollama took too long to generate. Retry or increase AIKA_MODEL_TIMEOUT.") from None
            raise OllamaError("Ollama did not respond to the model check. Check the local service and try again.") from None
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if path in {"/api/chat", "/api/show"} and status == 404:
                raise self._missing_model() from None
            raise OllamaError(f"Ollama returned HTTP {status}. Check the local service and selected model, then retry.") from None
        except httpx.RequestError:
            raise OllamaError("Communication with Ollama failed. Check the local service and try again.") from None

        try:
            payload = response.json()
        except ValueError:
            raise OllamaError("Ollama returned an invalid JSON response. Check the local service.") from None
        if not isinstance(payload, dict) or "error" in payload:
            raise OllamaError("Ollama returned an unexpected API response. Check the local service.")
        return payload
