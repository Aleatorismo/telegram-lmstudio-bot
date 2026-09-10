from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


PARAMETERS = ("temperature", "max_tokens", "top_p", "top_k", "min_p", "presence_penalty")
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
        except (ValueError, TypeError, OverflowError) as exc:
            raise ModelConfigError(f"Invalid value for {name}: {raw!r}") from exc
        result[name] = value
    return result


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
                sampling_params(profile.get(mode, {}))
            effort = profile.get("thinking_effort", "medium")
            if effort not in ("minimal", "low", "medium", "high", "xhigh"):
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
                    "thinking": dict.fromkeys(PARAMETERS),
                    "non_thinking": dict.fromkeys(PARAMETERS),
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
        if profile["type"] != "non_thinking":
            effort = profile.get("thinking_effort", "medium") if selection["mode"] == "thinking" else "none"
        return {**selection, "type": profile["type"],
                "parameters": sampling_params(profile.get(selection["mode"], {})),
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
        validated = sampling_params(changes)
        data = self.profiles()
        params = data["models"][current["model"]].setdefault(mode, {})
        for name in changes:
            params[name] = validated.get(name)
        write_json(self.path, data)
