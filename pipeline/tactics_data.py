"""Carrega as posições dos jogadores (8 Hz, com o nome da região) e as junta com o resultado de cada round.

Usado por build_tactics.py. Tudo no nível de regiões (callouts); não precisa da geometria 3D do mapa.
"""
import json

import numpy as np
import pandas as pd

from calibration.metrics import KEY, round_frame
from calibration.simlog import load_tables
from pipeline.common import DATA_DIR, UNIT_TO_M

SAMPLE_HZ = 8


def match_dirs():
    return sorted(p.parent for p in DATA_DIR.glob("*/match.json"))


def load_positions():
    """Uma linha por jogador vivo por amostra: match, map, round, t, steamid, side, place, x, y, z (metros)."""
    parts = []
    for d in match_dirs():
        meta = json.loads((d / "match.json").read_text())
        t = pd.read_parquet(d / "ticks.parquet", columns=["round", "round_time", "after_round_end", "steamid", "side", "is_alive",
                                                          "X", "Y", "Z", "last_place_name"])
        t = t[t["is_alive"] & ~t["after_round_end"] & (t["round_time"] >= 0)]
        t = t[t["last_place_name"].notna() & (t["last_place_name"] != "")]     # amostras sem nome de região (raras) ficam de fora
        t = t.rename(columns={"round_time": "t", "last_place_name": "place"})
        t["x"], t["y"], t["z"] = t["X"] * UNIT_TO_M, t["Y"] * UNIT_TO_M, t["Z"] * UNIT_TO_M
        t["match"], t["map"] = d.name, meta["map"]
        parts.append(t[["match", "map", "round", "t", "steamid", "side", "place", "x", "y", "z"]])
    P = pd.concat(parts, ignore_index=True)
    return P.sort_values(["match", "round", "steamid", "t"]).reset_index(drop=True)


def load_rounds():
    """Rounds com vencedor, plant, tipos de compra e duração (mesmo código das métricas de calibração)."""
    files = sorted(DATA_DIR.glob("*/simlog.jsonl"))
    tables = load_tables(files)
    return round_frame(tables), tables


def team_alive_counts(P):
    """Jogadores vivos por (match, round, side, t)."""
    return P.groupby(KEY + ["side", "t"]).size().rename("alive").reset_index()


def runs(P):
    """Permanências: cada trecho contínuo de um jogador numa região (entrada, saída, duração em segundos)."""
    P = P.copy()
    g = P.groupby(KEY + ["steamid"])
    P["prev"] = g["place"].shift()
    P["run"] = (P["place"] != P["prev"]).groupby([P["match"], P["round"], P["steamid"]]).cumsum()
    r = P.groupby(KEY + ["steamid", "side", "run", "place"]).agg(t_in=("t", "min"), t_out=("t", "max"), n=("t", "size"),
                                                                 x=("x", "mean"), y=("y", "mean")).reset_index()
    r["dwell_s"] = r["n"] / SAMPLE_HZ
    return r


def hellinger(counts):
    """Raiz da distribuição: reduz o peso das regiões muito frequentes ao medir distância entre rounds."""
    c = np.asarray(counts, float)
    s = c.sum(axis=-1, keepdims=True)
    return np.sqrt(np.divide(c, s, out=np.zeros_like(c), where=s > 0))
