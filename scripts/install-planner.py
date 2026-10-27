"""Download the official, pinned local planner. No API token is needed."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forensics.planner import MODEL_ID, MODEL_REVISION, ROOT

if __name__ == "__main__":
    from huggingface_hub import snapshot_download
    print(snapshot_download(MODEL_ID, revision=MODEL_REVISION,
        local_dir=ROOT / "external" / "Qwen2.5-1.5B-Instruct",
        allow_patterns=["*.json", "*.safetensors", "merges.txt", "vocab.json", "LICENSE", "README.md"], max_workers=3))
