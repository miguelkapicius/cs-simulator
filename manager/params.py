"""Carrega os parâmetros ajustáveis da economia (manager/params.json)."""
import json
from pathlib import Path
from typing import Dict

PARAMS_PATH = Path(__file__).with_name("params.json")


def load_params() -> Dict:
    with open(PARAMS_PATH, encoding="utf-8") as f:
        return json.load(f)
