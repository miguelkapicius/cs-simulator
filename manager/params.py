"""Carrega os parâmetros ajustáveis da economia: o artefato do contrato contract/artifacts/manager_params.json."""
import json
from typing import Dict

from pipeline.common import ARTIFACTS_DIR

PARAMS_PATH = ARTIFACTS_DIR / "manager_params.json"


def load_params() -> Dict:
    with open(PARAMS_PATH, encoding="utf-8") as f:
        return json.load(f)["params"]
