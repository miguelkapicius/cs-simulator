"""Lê o log da simulação (.jsonl, ver contract/docs/sim_log.md) e monta as tabelas das métricas.

O mesmo código lê o log da Unity e as demos reais convertidas (pipeline/real_to_simlog.py),
então as métricas das duas fontes são diretamente comparáveis.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.combat import resolve_sightings
from pipeline.common import weapon_class

TABLES = ["rounds", "players", "shots", "damages", "kills", "bombs", "grenades", "sightings"]


def read_events(path):
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"{path}:{n}: JSON inválido ({e})") from e


def _frame(events, columns):
    df = pd.DataFrame(events)
    for c in columns:
        if c not in df.columns:
            df[c] = np.nan
    return df


def load_match(path):
    """Tabelas de uma partida (um arquivo .jsonl)."""
    path = Path(path)
    by_type = {}
    for e in read_events(path):
        by_type.setdefault(e["type"], []).append(e)
    if "match_start" not in by_type:
        raise ValueError(f"{path}: sem evento match_start")
    ms = by_type["match_start"][0]
    tickrate = ms["tickrate"]
    match_id = path.parent.name if path.name in ("simlog.jsonl", "sim_log.jsonl") else path.stem

    # Rounds
    rs = _frame(by_type.get("round_start", []), ["round", "tick", "ct_team", "t_team"]).rename(columns={"tick": "start_tick"})
    fe = _frame(by_type.get("freeze_end", []), ["round", "tick"]).rename(columns={"tick": "freeze_end_tick"})
    re_ = _frame(by_type.get("round_end", []), ["round", "tick", "winner_side", "reason", "alive"]).rename(columns={"tick": "end_tick"})
    re_["alive_ct"] = re_["alive"].map(lambda a: a["CT"] if isinstance(a, dict) else np.nan)
    re_["alive_t"] = re_["alive"].map(lambda a: a["T"] if isinstance(a, dict) else np.nan)
    rounds = (rs[["round", "start_tick", "ct_team", "t_team"]]
              .merge(fe[["round", "freeze_end_tick"]], on="round")
              .merge(re_[["round", "end_tick", "winner_side", "reason", "alive_ct", "alive_t"]], on="round"))
    rounds["duration_s"] = (rounds["end_tick"] - rounds["freeze_end_tick"]) / tickrate

    # Jogadores por round (estado no fim do freeze time)
    prow = []
    for e in by_type.get("freeze_end", []):
        for p in e["players"]:
            g = p.get("grenades") or {}
            prow.append({"round": e["round"], **{k: v for k, v in p.items() if k != "grenades"},
                         **{f"g_{k}": g.get(k, 0) for k in ("smoke", "flash", "he", "molotov")}})
    players = pd.DataFrame(prow)
    sides = {(r, p): s for r, p, s in zip(players["round"], players["player"], players["side"])}

    # Janelas de cada round, para marcar tempo e eventos depois do fim
    win = rounds.set_index("round")[["freeze_end_tick", "end_tick"]]

    def stamp(df):
        if df.empty:
            return df.assign(round_time=np.nan, after_round_end=False)
        df = df[df["round"].isin(win.index)].copy()
        df["round_time"] = (df["tick"] - win.loc[df["round"], "freeze_end_tick"].to_numpy()) / tickrate
        df["after_round_end"] = df["tick"].to_numpy() > win.loc[df["round"], "end_tick"].to_numpy()
        return df[df["round_time"] >= 0]

    def side_of(df, col):
        return [sides.get((r, p)) for r, p in zip(df["round"], df[col])]

    shots = _frame(by_type.get("shot", []), ["round", "tick", "shooter", "weapon", "hit", "target", "distance_m",
                                             "aim_error_deg", "speed", "ducking", "airborne", "spray_index"])
    shots = stamp(shots)
    shots = shots[~shots["after_round_end"]].copy()
    shots["hit"] = shots["hit"].astype(bool)
    shots["aim_err_deg"] = shots["aim_error_deg"]
    shots["wclass"] = shots["weapon"].map(weapon_class)

    damages = stamp(_frame(by_type.get("damage", []), ["round", "tick", "attacker", "victim", "weapon", "hitgroup",
                                                       "dmg_health", "dmg_armor"]))
    damages = damages.rename(columns={"attacker": "attacker_steamid", "victim": "user_steamid"})
    damages["attacker_side"] = side_of(damages, "attacker_steamid")
    damages["user_side"] = side_of(damages, "user_steamid")
    damages["wclass"] = damages["weapon"].map(weapon_class)

    kills = stamp(_frame(by_type.get("kill", []), ["round", "tick", "attacker", "victim", "assister", "weapon", "headshot",
                                                   "distance_m"]))
    kills = kills.rename(columns={"attacker": "attacker_steamid", "victim": "user_steamid", "assister": "assister_steamid"})
    kills["attacker_side"] = side_of(kills, "attacker_steamid")
    kills["user_side"] = side_of(kills, "user_steamid")
    kills["headshot"] = kills["headshot"].fillna(False).astype(bool)
    kills["wclass"] = kills["weapon"].map(weapon_class)

    bombs = stamp(_frame(by_type.get("bomb", []), ["round", "tick", "event", "player", "site"]))
    grenades = stamp(_frame(by_type.get("grenade", []), ["round", "tick", "kind", "thrower"]))

    # Avistamentos: resolve reação e resultado do duelo (mesma regra dos perfis)
    sight = stamp(_frame(by_type.get("sighting", []), ["round", "tick", "observer", "target", "distance_m", "aim_error_deg"]))
    if len(sight):
        sight = sight[~sight["after_round_end"]].copy()
        sight["aim_err_deg"] = sight["aim_error_deg"]
        sight["side"] = side_of(sight, "observer")
        sight = resolve_sightings(sight, shots, kills)

    tables = {"rounds": rounds, "players": players, "shots": shots, "damages": damages, "kills": kills,
              "bombs": bombs, "grenades": grenades, "sightings": sight}
    map_name = ms["map"]
    for name, df in tables.items():
        df["match"] = match_id
        df["map"] = map_name
    return tables


def load_tables(paths):
    """Junta várias partidas. `paths` pode ter arquivos .jsonl ou pastas (procura simlog.jsonl/sim_log.jsonl/*.jsonl)."""
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            found = sorted(p.rglob("simlog.jsonl")) or sorted(p.rglob("sim_log.jsonl")) or sorted(p.rglob("*.jsonl"))
            files.extend(found)
        else:
            files.append(p)
    if not files:
        raise FileNotFoundError("nenhum arquivo .jsonl encontrado")
    parts = [load_match(f) for f in files]
    out = {name: pd.concat([p[name] for p in parts], ignore_index=True) for name in TABLES}
    out["matches"] = len(parts)
    return out
