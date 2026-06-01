"""Load the user's focus profile (drives the personalized do/skip take). Uses profile.yaml if it
exists (your real one, gitignored), else the committed profile.example.yaml."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_profile() -> dict:
    for name in ("profile.yaml", "profile.example.yaml"):
        path = ROOT / name
        if path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}
