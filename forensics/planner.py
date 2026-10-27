"""Local language-model tool selection with a finite, inspectable action space.

The model scores a single numbered token per allowed action. The dispatcher,
budgets and report facts remain deterministic. No model-generated code runs.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time

MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"
MODEL_REVISION = "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"
MODEL_SHA256 = "dd924a11b4c220f385b51ffa522daea7c9f3d850e31b162bb5661df483c6d3ee"
MODEL_FILES_SHA256 = {
    "model.safetensors": MODEL_SHA256,
    "config.json": "98d2ff8cc47488d08a2b0b3acf4eb99ef210779b42bd48605f6b8e36acdbf670",
    "tokenizer.json": "c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539",
    "tokenizer_config.json": "5b5d4f65d0acd3b2d56a35b56d374a36cbc1c8fa5cf3b3febbbfabf22f359583",
}
ROOT = Path(__file__).resolve().parent.parent
POLICY = """You select the next tool for an image-forensics investigation.
Goal: assess whether B-Free AI-generation evidence survives compression or resizing, using few calls.
You only see measurements; you do not see the image. B-Free scores are not calibrated probabilities.
Scores above 0.5 are elevated. A changed threshold decision means processing-sensitive evidence.
For an elevated or borderline original, prioritize a mild compression or resize test. If a tested
transformation changes the threshold decision, consider a different transformation to characterize
the instability, or stop if the available evidence already explains it. For a low original, one
perturbation may still reveal instability; low scores never prove authenticity. Avoid redundant work.
TruFor addresses local manipulation, not AI origin. Select it only if a manipulation map would add
a distinct, useful observation; disagreement with B-Free is not a contradiction. Stop when further
available tests would add little, or budget is exhausted. Do not infer truth labels.
Choose exactly one numbered action from the currently offered actions. Reply with its digit only.
"""


class PlannerUnavailable(RuntimeError):
    pass


class LocalPlanner:
    name = "Qwen2.5-1.5B-Instruct"

    def __init__(self, model_dir=None, device=None):
        self.model_dir = Path(model_dir or os.environ.get("FORENSICS_PLANNER_MODEL", ROOT / "external" / "Qwen2.5-1.5B-Instruct")).resolve()
        self.device = device or os.environ.get("FORENSICS_PLANNER_DEVICE", "auto")
        self._model = self._tokenizer = None
        self._lock = threading.Lock()
        self._fingerprint = None

    def status(self):
        required = ["config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json"]
        present = all((self.model_dir / name).is_file() for name in required)
        return {"available": present, "name": self.name, "loaded": self._model is not None,
                "reason": "Local model installed; selected actions are constrained and budgeted." if present else "Install the pinned local planner with scripts/install-planner.py.",
                "model_revision": MODEL_REVISION, "selection_method": "constrained next-token action scoring"}

    def _load(self):
        if self._model is not None:
            return
        if not self.status()["available"]:
            raise PlannerUnavailable(self.status()["reason"])
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        device = self.device
        if device == "auto":
            device = "mps" if torch.backends.mps.is_available() else "cpu"
        if device not in {"mps", "cpu"}:
            raise PlannerUnavailable("Planner device must be auto, mps or cpu.")
        hashes = {}
        for filename in ["model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json"]:
            digest = hashlib.sha256()
            with (self.model_dir / filename).open("rb") as stream:
                for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                    digest.update(block)
            hashes[filename] = digest.hexdigest()
        if hashes != MODEL_FILES_SHA256:
            raise PlannerUnavailable("Planner checkpoint, tokenizer or configuration differs from the pinned official model.")
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_dir, local_files_only=True, trust_remote_code=False)
        model = AutoModelForCausalLM.from_pretrained(
            self.model_dir, local_files_only=True, trust_remote_code=False,
            # FP16 produced non-finite Qwen logits on the verified MPS runtime.
            # Keep FP32 on both devices; invalid logits always stop the agent.
            torch_dtype=torch.float32,
            attn_implementation="eager")
        self._model = model.to(device).eval()
        self.device = device
        self._fingerprint = hashes

    def choose(self, observations: list[dict], actions: list[dict], remaining: int) -> dict:
        if not 1 <= len(actions) <= 9:
            raise ValueError("Planner requires one to nine allowed actions.")
        started = time.perf_counter()
        with self._lock:
            self._load()
            import torch
            context = {"observations": observations, "remaining_model_tool_calls": remaining,
                       "actions": [{"number": i + 1, **a} for i, a in enumerate(actions)]}
            prompt = self._tokenizer.apply_chat_template([
                {"role": "system", "content": POLICY},
                {"role": "user", "content": json.dumps(context, separators=(",", ":"), allow_nan=False)},
            ], tokenize=False, add_generation_prompt=True)
            inputs = self._tokenizer(prompt, return_tensors="pt").to(self.device)
            ids = [self._tokenizer.encode(str(i + 1), add_special_tokens=False) for i in range(len(actions))]
            if any(len(tokens) != 1 for tokens in ids):
                raise PlannerUnavailable("This tokenizer does not encode action digits as single tokens.")
            with torch.inference_mode():
                logits = self._model(**inputs, use_cache=False).logits[0, -1, [x[0] for x in ids]].float().cpu()
            if not torch.isfinite(logits).all():
                raise PlannerUnavailable("Planner returned non-finite action logits.")
            probs = torch.softmax(logits, dim=0).tolist()
            selected = int(torch.argmax(logits))
            return {"action": actions[selected]["id"], "policy": "local_llm",
                    "model": MODEL_ID, "model_revision": MODEL_REVISION, "device": self.device,
                    "precision": "float32",
                    "selection_method": "highest next-token logit among allowed numbered actions",
                    "action_weights": [{"action": a["id"], "weight": p} for a, p in zip(actions, probs)],
                    "weight_meaning": "Relative model preference over offered actions, not confidence or authenticity probability.",
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "policy_sha256": hashlib.sha256(POLICY.encode()).hexdigest(),
                    "model_file_sha256": self._fingerprint,
                    "input_tokens": int(inputs["input_ids"].shape[-1]),
                    "runtime_seconds": time.perf_counter() - started}


class RulePlanner:
    """Explicit comparison policy; never substituted for the language model."""
    name = "Fixed rule comparison"

    def choose(self, observations, actions, remaining):
        allowed = {a["id"] for a in actions}
        scores = [o["score"] for o in observations if o.get("score") is not None and o.get("score_kind") == "ai_generation"]
        wanted = "finish"
        if len(scores) < 2:
            wanted = "jpeg_q85_r1"
        elif any((x > .5) != (scores[0] > .5) for x in scores[1:]) and "resize_s0.9_r1" in allowed:
            wanted = "resize_s0.9_r1"
        elif scores[0] > .5 and "combined_q95_s0.9_r3" in allowed:
            wanted = "combined_q95_s0.9_r3"
        return {"action": wanted if wanted in allowed else "finish", "policy": "rule_baseline", "runtime_seconds": 0.0}
