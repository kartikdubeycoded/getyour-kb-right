"""Load the user's focus profile (drives the personalized take + the lanes/projects). Order:
the PROFILE_YAML env var (the whole YAML as a string — how a deployed host injects the private
profile as a secret, so it never has to be baked into the image), else profile.yaml (your real
local one, gitignored), else the committed profile.example.yaml."""

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_profile() -> dict:
    raw = os.getenv("PROFILE_YAML")
    if raw and raw.strip():  # deployed: profile arrives as a host secret, not baked into the image
        return yaml.safe_load(raw) or {}
    for name in ("profile.yaml", "profile.example.yaml"):
        path = ROOT / name
        if path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}
