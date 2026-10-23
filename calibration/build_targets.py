"""Gera as metas de calibração (contract/artifacts/calibration_targets.json) a partir das demos reais.

Usa os logs convertidos (data/<demo>/simlog.jsonl, de pipeline.real_to_simlog), os mesmos que a
simulação grava, e o mesmo código de métricas do comparador.

Uso: .venv/bin/python -m calibration.build_targets
"""
import json
from datetime import date

import numpy as np

from calibration.compare import COVERAGE_QUANTILES, DEFAULT_THRESHOLDS, frac_below
from calibration.metrics import compute_metrics, describe, serializable
from calibration.simlog import load_tables
from pipeline.common import ARTIFACTS_DIR, CONTRACT_VERSION, DATA_DIR


def _round(v, nd=5):
    if isinstance(v, float):
        return round(v, nd)
    if isinstance(v, dict):
        return {k: _round(x, nd) for k, x in v.items()}
    return v


MIN_N_MATCH = 5      # amostras mínimas de uma partida para entrar na estimativa do ruído entre partidas
MIN_MATCHES = 5      # partidas mínimas para estimar o ruído; abaixo disso a meta fica sem 'between'


def between_match_noise(files, targets):
    """Quanto cada métrica varia de uma partida real para outra (desvio-padrão entre partidas).

    O comparador usa isso como medida de ruído: as amostras de uma mesma partida (mesmos jogadores,
    mapa e adversário) não são independentes, então tratá-las como independentes geraria falsos alarmes.
    """
    per_match = [compute_metrics(load_tables([f])) for f in files]
    out = {}
    for mid, tgt in targets.items():
        got = [pm[mid] for pm in per_match if mid in pm and pm[mid]["n"] >= MIN_N_MATCH]
        if len(got) < MIN_MATCHES:
            continue
        if tgt["kind"] == "prop":
            vals = [g["k"] / g["n"] for g in got]
            out[mid] = {"matches": len(got), "sd": float(np.std(vals, ddof=1))}
        elif tgt["kind"] == "mean":
            out[mid] = {"matches": len(got), "sd": float(np.std([g["mean"] for g in got], ddof=1))}
        else:
            sd = {}
            for p in COVERAGE_QUANTILES:
                fr = [frac_below(g["_samples"], tgt["q"][f"p{p}"]) for g in got]
                sd[f"p{p}"] = float(np.std(fr, ddof=1))
            out[mid] = {"matches": len(got), "sd_cov": sd}
    return out


def make_targets(files):
    """Metas (com o ruído entre partidas) a partir de uma lista de logs. Devolve (tabelas, métricas)."""
    tables = load_tables(files)
    full = compute_metrics(tables)
    noise = between_match_noise(files, full)
    metrics = serializable(full)
    for mid, nz in noise.items():
        metrics[mid]["between"] = nz
    for mid, m in full.items():
        if m["kind"] == "quantiles":
            # Cobertura da própria distribuição real em cada quantil. Em valores inteiros com repetição
            # (rajadas, kills) ela difere de p/100, e é essa a referência certa para a simulação.
            metrics[mid]["coverage"] = {f"p{p}": frac_below(m["_samples"], m["q"][f"p{p}"]) for p in COVERAGE_QUANTILES}
    return tables, metrics


def main():
    files = sorted(DATA_DIR.glob("*/simlog.jsonl"))
    if not files:
        raise SystemExit("Sem logs reais. Rode: python -m pipeline.real_to_simlog")
    tables, metrics = make_targets(files)
    metrics = {k: {**_round(v), "desc": describe(k)} for k, v in sorted(metrics.items())}
    doc = {
        "schema_version": "1.0",
        "contract_version": CONTRACT_VERSION,
        "generated_at": date.today().isoformat(),
        "source": {"matches": tables["matches"], "rounds": len(tables["rounds"]), "maps": sorted(tables["rounds"]["map"].unique().tolist())},
        "thresholds": DEFAULT_THRESHOLDS,
        "metrics": metrics,
    }
    out = ARTIFACTS_DIR / "calibration_targets.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    kinds = {}
    for m in metrics.values():
        kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
    print(f"{out} ({out.stat().st_size // 1024} KB): {len(metrics)} métricas {kinds} de {tables['matches']} partidas / {len(tables['rounds'])} rounds")


if __name__ == "__main__":
    main()
