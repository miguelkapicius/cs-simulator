"""Regras de combate compartilhadas entre as demos (pipeline/) e o log da simulação (calibration/).

Só depende de pandas/numpy, para rodar sem o demoparser2.
"""
import pandas as pd

from pipeline.common import TICKRATE

SPOT_MIN_GAP_S = 0.5        # o inimigo precisa ter ficado fora de vista por 0,5 s para contar como novo avistamento
REACTION_WINDOW_S = 2.0     # tiro em até 2 s após avistar conta como reação
AIMED_SHOT_DEG = 10.0       # tiro "no alvo" se a mira está a menos de 10° do inimigo mais próximo
DUEL_WINDOW_S = 3.0         # duelo resolvido se alguém morre em até 3 s após o avistamento


def is_combat_shot(shots):
    """Tiro em combate: mira a menos de AIMED_SHOT_DEG de um inimigo, ou que acertou alguém."""
    return (shots["aim_err_deg"] < AIMED_SHOT_DEG) | shots["hit"]


def resolve_sightings(sp, shots, kills):
    """Reação e resultado de cada avistamento. Comum às demos e à simulação.

    sp:    tick, observer, target, distance_m, aim_err_deg (+ colunas extras, que são preservadas)
    shots: tick, shooter, target, aim_err_deg, hit
    kills: tick, attacker_steamid, user_steamid, after_round_end
    """
    # Logs parciais podem ter colunas de ids vazias (float); força texto para os merges
    sp = sp.astype({"observer": object, "target": object})
    shots = shots.astype({"shooter": object, "target": object})
    kills = kills.astype({"attacker_steamid": object, "user_steamid": object})

    # Ignora avistamentos com o observador já atirando (luta em andamento)
    sh = shots[["tick", "shooter", "target", "aim_err_deg", "hit"]].sort_values("tick")
    recent = pd.merge_asof(sp.sort_values("tick"), sh[["tick", "shooter"]].rename(columns={"tick": "last_shot"}),
                           left_on="tick", right_on="last_shot", left_by="observer", right_by="shooter",
                           direction="backward")
    sp = recent[recent["last_shot"].isna() | (recent["tick"] - recent["last_shot"] > SPOT_MIN_GAP_S * TICKRATE)].drop(columns=["shooter", "last_shot"])

    # Reação: primeiro tiro do observador mirando nesse alvo em até 2 s
    aimed = sh[sh["aim_err_deg"] < AIMED_SHOT_DEG].rename(columns={"tick": "shot_tick", "target": "shot_target"})
    m = sp[["tick", "observer", "target"]].merge(aimed, left_on=["observer", "target"], right_on=["shooter", "shot_target"])
    m = m[(m["shot_tick"] >= m["tick"]) & (m["shot_tick"] <= m["tick"] + REACTION_WINDOW_S * TICKRATE)]
    first = m.sort_values("shot_tick").drop_duplicates(["tick", "observer", "target"])
    first["reaction_s"] = (first["shot_tick"] - first["tick"]) / TICKRATE
    sp = sp.merge(first[["tick", "observer", "target", "reaction_s"]], on=["tick", "observer", "target"], how="left")

    # Resultado do duelo: quem matou quem em até 3 s
    k = kills[~kills["after_round_end"] & kills["attacker_steamid"].notna()][["tick", "attacker_steamid", "user_steamid"]]
    win = sp[["tick", "observer", "target"]].merge(k, left_on=["observer", "target"], right_on=["attacker_steamid", "user_steamid"], suffixes=("", "_k"))
    lose = sp[["tick", "observer", "target"]].merge(k, left_on=["target", "observer"], right_on=["attacker_steamid", "user_steamid"], suffixes=("", "_k"))
    window = DUEL_WINDOW_S * TICKRATE
    win = win[(win["tick_k"] >= win["tick"]) & (win["tick_k"] <= win["tick"] + window)].assign(outcome="win")
    lose = lose[(lose["tick_k"] >= lose["tick"]) & (lose["tick_k"] <= lose["tick"] + window)].assign(outcome="loss")
    res = pd.concat([win, lose]).sort_values("tick_k").drop_duplicates(["tick", "observer", "target"])
    sp = sp.merge(res[["tick", "observer", "target", "outcome"]], on=["tick", "observer", "target"], how="left")
    sp["outcome"] = sp["outcome"].fillna("none")
    return sp
