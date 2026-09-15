from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


SAMPLING_PARAMETERS = ("temperature", "max_tokens", "top_p", "top_k", "min_p", "presence_penalty",
                       "repetition_penalty")
PARAMETERS = (*SAMPLING_PARAMETERS, "repeat_penalty", "reasoning_effort", "chat_template_kwargs")
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")
TEMPLATE_PARAMETERS = ("enable_thinking", "preserve_thinking")
MODEL_TYPES = ("non_thinking", "thinking", "both", "unknown")


class ModelConfigError(ValueError):
    """Invalid model profiles or user selection."""


def sampling_params(values: dict) -> dict:
    if not isinstance(values, dict):
        raise ModelConfigError("Parameters must be a JSON object.")
    result = {}
    for name, raw in values.items():
        if name not in PARAMETERS:
            raise ModelConfigError(f"Unknown parameter: {name}. Allowed: {', '.join(PARAMETERS)}")
        if raw is None or (isinstance(raw, str) and raw.strip().lower() in ("", "default", "null")):
            continue
        if name == "reasoning_effort":
            if not isinstance(raw, str) or raw not in REASONING_EFFORTS:
                raise ModelConfigError(f"Invalid reasoning_effort. Use {', '.join(REASONING_EFFORTS)}.")
            result[name] = raw
            continue
        if name == "chat_template_kwargs":
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except ValueError as exc:
                    raise ModelConfigError("chat_template_kwargs must be a JSON object.") from exc
            if not isinstance(raw, dict):
                raise ModelConfigError("chat_template_kwargs must be a JSON object.")
            template = {}
            for key, value in raw.items():
                if key not in TEMPLATE_PARAMETERS:
                    raise ModelConfigError(f"Unknown chat_template_kwargs key: {key}.")
                if value is None or (isinstance(value, str) and value.strip().lower() in ("", "default", "null")):
                    continue
                if not isinstance(value, bool):
                    raise ModelConfigError(f"chat_template_kwargs.{key} must be true or false.")
                template[key] = value
            if template:
                result[name] = template
            continue
        try:
            if isinstance(raw, bool):
                raise ValueError
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError
            if name in ("max_tokens", "top_k"):
                if not value.is_integer():
                    raise ValueError
                value = int(value)
            if name == "temperature" and not 0 <= value <= 2:
                raise ValueError
            if name == "max_tokens" and value != -1 and value < 1:
                raise ValueError
            if name == "top_k" and value < 0:
                raise ValueError
            if name in ("top_p", "min_p") and not 0 <= value <= 1:
                raise ValueError
            if name == "presence_penalty" and not -2 <= value <= 2:
                raise ValueError
            if name in ("repetition_penalty", "repeat_penalty") and value <= 0:
                raise ValueError
        except (ValueError, TypeError, OverflowError) as exc:
            raise ModelConfigError(f"Invalid value for {name}: {raw!r}") from exc
        result[name] = value
    if ("repetition_penalty" in result and "repeat_penalty" in result
            and result["repetition_penalty"] != result["repeat_penalty"]):
        raise ModelConfigError("repetition_penalty and repeat_penalty must not have conflicting values.")
    return result


def mode_params(values: dict, mode: str) -> dict:
    params = sampling_params(values)
    enabled = params.get("chat_template_kwargs", {}).get("enable_thinking")
    if enabled is not None and enabled != (mode == "thinking"):
        raise ModelConfigError(f"chat_template_kwargs.enable_thinking conflicts with {mode} mode.")
    effort = params.get("reasoning_effort")
    if effort is not None and ((effort == "none") == (mode == "thinking")):
        raise ModelConfigError(f"reasoning_effort conflicts with {mode} mode. Use /think to switch modes.")
    return params


def request_params(values: dict, reasoning_effort: str | None = None) -> dict:
    """Convert profile names into LM Studio's OpenAI-compatible wire fields."""
    params = sampling_params(values)
    if "repetition_penalty" in params:
        params["repeat_penalty"] = params.pop("repetition_penalty")
    # A per-mode field (even explicit null/blank) overrides the legacy fallback.
    if "reasoning_effort" not in values and reasoning_effort is not None:
        params.update(sampling_params({"reasoning_effort": reasoning_effort}))
    return params


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        return data
    except (OSError, ValueError) as exc:
        raise ModelConfigError(f"Cannot read {path.name}: {exc}") from exc


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as f:
            temp = f.name
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
        os.replace(temp, path)
    except OSError as exc:
        raise ModelConfigError(f"Cannot save {path.name}: {exc}") from exc
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)


class ModelStore:
    """Reload editable profiles on every operation; persist per-user choices separately."""

    def __init__(self, path: str, selections_path: str, default_model: str = "") -> None:
        self.path = Path(path)
        self.selections_path = Path(selections_path)
        self.default_model = default_model

    def profiles(self) -> dict:
        data = read_json(self.path, {"models": {}})
        models = data.get("models")
        if not isinstance(models, dict):
            raise ModelConfigError("Model profiles must contain a 'models' object.")
        for model_id, profile in models.items():
            if not isinstance(model_id, str) or not model_id.strip() or not isinstance(profile, dict):
                raise ModelConfigError("Each model needs a non-empty ID and a profile object.")
            if profile.get("type", "unknown") not in MODEL_TYPES:
                raise ModelConfigError(f"Invalid model type for {model_id}. Use {', '.join(MODEL_TYPES)}.")
            for mode in ("thinking", "non_thinking"):
                mode_params(profile.get(mode, {}), mode)
            effort = profile.get("thinking_effort", "medium")
            validated_effort = sampling_params({"reasoning_effort": effort}).get("reasoning_effort")
            if validated_effort == "none":
                raise ModelConfigError(f"Invalid thinking_effort for {model_id}.")
        return data

    def merge_discovered(self, discovered: list[dict]) -> None:
        data = self.profiles()
        for model in discovered:
            model_id = model["id"]
            if model_id not in data["models"]:
                data["models"][model_id] = {
                    "type": model["type"],
                    "thinking_effort": model.get("thinking_effort", "medium"),
                    "thinking": dict.fromkeys(SAMPLING_PARAMETERS),
                    "non_thinking": dict.fromkeys(SAMPLING_PARAMETERS),
                }
            elif data["models"][model_id].get("type", "unknown") == "unknown":
                data["models"][model_id]["type"] = model["type"]
        if self.default_model and self.default_model not in data["models"]:
            data["models"][self.default_model] = {
                "type": "unknown", "thinking": {}, "non_thinking": {},
            }
        if data != read_json(self.path, {}):
            write_json(self.path, data)

    def _selection(self, user_id: int, models: dict) -> dict:
        selection = read_json(self.selections_path, {}).get(str(user_id))
        if selection is None:
            model = self.default_model or next(iter(models), "")
            selection = {"model": model, "mode": None}
        if not isinstance(selection, dict) or selection.get("model") not in models:
            raise ModelConfigError("Selected model is unavailable. Use /model to select a model.")
        model_type = models[selection["model"]].get("type", "unknown")
        if model_type == "unknown":
            raise ModelConfigError(
                f"Thinking capability for {selection['model']} is unknown. "
                f"Set its type in {self.path.name} to non_thinking, thinking, or both, then retry."
            )
        mode = selection.get("mode")
        if mode is None or model_type != "both":
            mode = "non_thinking" if model_type == "non_thinking" else "thinking"
        if mode not in ("thinking", "non_thinking"):
            raise ModelConfigError("Invalid saved mode. Use /model to select a model again.")
        return {"model": selection["model"], "mode": mode}

    def current(self, user_id: int) -> dict[str, Any]:
        models = self.profiles()["models"]
        selection = self._selection(user_id, models)
        profile = models[selection["model"]]
        effort = None
        values = profile.get(selection["mode"], {})
        parameters = mode_params(values, selection["mode"])
        if profile["type"] != "non_thinking":
            effort = (sampling_params({"reasoning_effort": profile.get("thinking_effort", "medium")}).get("reasoning_effort")
                      if selection["mode"] == "thinking" else "none")
        if "reasoning_effort" in values:
            effort = parameters.pop("reasoning_effort", None)
        return {**selection, "type": profile["type"],
                "parameters": parameters,
                "reasoning_effort": effort}

    def select(self, user_id: int, model_id: str) -> None:
        models = self.profiles()["models"]
        if model_id not in models:
            raise ModelConfigError("Unknown model ID. Use /model to list available models.")
        if models[model_id].get("type", "unknown") == "unknown":
            raise ModelConfigError(f"Set the model's type in {self.path.name} before selecting it.")
        self._save_selection(user_id, {"model": model_id, "mode": None})

    def _save_selection(self, user_id: int, selection: dict) -> None:
        data = read_json(self.selections_path, {})
        data[str(user_id)] = selection
        write_json(self.selections_path, data)

    def set_mode(self, user_id: int, mode: str | None) -> None:
        current = self.current(user_id)
        mode = mode or ("non_thinking" if current["mode"] == "thinking" else "thinking")
        if mode not in ("thinking", "non_thinking"):
            raise ModelConfigError("Usage: /think [on|off]")
        if current["type"] != "both" and mode != current["mode"]:
            raise ModelConfigError(f"This model only supports {current['mode'].replace('_', ' ')} mode.")
        self._save_selection(user_id, {"model": current["model"], "mode": mode})

    def update_params(self, user_id: int, changes: dict, mode: str | None = None) -> None:
        current = self.current(user_id)
        mode = mode or current["mode"]
        if mode not in ("thinking", "non_thinking"):
            raise ModelConfigError("Use on or off to choose a parameter profile.")
        if current["type"] != "both" and mode != current["mode"]:
            raise ModelConfigError("This model does not support the requested mode.")
        data = self.profiles()
        params = data["models"][current["model"]].setdefault(mode, {})
        changes = dict(changes)
        nested = {name: changes.pop(name) for name in list(changes) if name.startswith("chat_template_kwargs.")}
        if nested:
            if "chat_template_kwargs" in changes:
                raise ModelConfigError("Edit chat_template_kwargs as an object or individual keys, not both.")
            template = sampling_params(params).get("chat_template_kwargs", {})
            for name, raw in nested.items():
                key = name.split(".", 1)[1]
                if isinstance(raw, str) and raw.lower() in ("true", "false"):
                    raw = raw.lower() == "true"
                validated = sampling_params({"chat_template_kwargs": {key: raw}}).get("chat_template_kwargs", {})
                if key in validated:
                    template[key] = validated[key]
                else:
                    template.pop(key, None)
            changes["chat_template_kwargs"] = template
        validated = sampling_params(changes)
        for name in changes:
            params[name] = validated.get(name)
        # Both spellings address the same setting; editing one replaces the old alias.
        for name, alias in (("repetition_penalty", "repeat_penalty"), ("repeat_penalty", "repetition_penalty")):
            if name in changes and alias not in changes:
                params.pop(alias, None)
        mode_params(params, mode)
        write_json(self.path, data)
