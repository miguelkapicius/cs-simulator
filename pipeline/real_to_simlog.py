"""Converte as demos reais para o formato do log da simulação (data/<demo>/simlog.jsonl).

Assim as demos e a simulação passam pelo mesmo código de métricas (calibration/).
Rode depois de pipeline.extract_demos.

Uso: .venv/bin/python -m pipeline.real_to_simlog [demo.dem ...]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from demoparser2 import DemoParser

from pipeline.build_player_profiles import extract_shots, find_sighting_onsets
from pipeline.common import (CONTRACT_VERSION, DATA_DIR, DEMOS_DIR, DISPLAY_TO_ID, GRENADE_DISPLAY, TICKRATE,
                             WEAPON_CLASS)
from pipeline.extract_demos import assign_round

# Ordem dos tipos de evento dentro do mesmo tick
TYPE_ORDER = {"round_start": 0, "freeze_end": 1, "bomb": 2, "grenade": 3, "sighting": 4, "shot": 5, "damage": 6,
              "kill": 7, "round_end": 8}


def clean(v):
    """Converte tipos do numpy/pandas para JSON; NaN vira None."""
    if v is None or v is pd.NA:
        return None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else round(float(v), 4)
    return v


def rec(row, mapping):
    """Monta um dict a partir de uma linha: mapping = {campo_saida: coluna}."""
    return {k: clean(row[c]) if c in row.index else None for k, c in mapping.items()}


def loadout(inventory):
    primary = secondary = None
    grenades = {"smoke": 0, "flash": 0, "he": 0, "molotov": 0}
    for item in inventory:
        if item in GRENADE_DISPLAY:
            grenades[GRENADE_DISPLAY[item]] += 1
            continue
        wid = DISPLAY_TO_ID.get(item)
        cls = WEAPON_CLASS.get(wid)
        if cls == "pistol":
            secondary = wid
        elif cls:
            primary = wid
    return primary, secondary, grenades


def site_letter(place):
    if isinstance(place, str) and place.startswith("Bombsite") and place[-1] in "AB":
        return place[-1]
    return None


def convert(demo_path):
    demo_path = Path(demo_path)
    d = DATA_DIR / demo_path.stem
    match = json.loads((d / "match.json").read_text())
    rounds = json.loads((d / "rounds.json").read_text())
    kills = pd.read_parquet(d / "kills.parquet")
    damages = pd.read_parquet(d / "damages.parquet")
    bomb = pd.read_parquet(d / "bomb.parquet")
    grenades = pd.read_parquet(d / "grenades.parquet")
    economy = pd.read_parquet(d / "economy.parquet")

    parser = DemoParser(str(demo_path))
    shots = extract_shots(parser, rounds, damages)
    onsets = assign_round(find_sighting_onsets(parser, rounds), rounds, TICKRATE)
    onsets = onsets[~onsets["after_round_end"]]

    events = []  # (round, tick, tipo, dict)

    def add(round_number, tick, type_, body):
        events.append((round_number, int(tick), TYPE_ORDER[type_], {"type": type_, "round": int(round_number), "tick": int(tick), **body}))

    for r in rounds:
        n = r["round"]
        add(n, r["start_tick"], "round_start", {"ct_team": r["ct_team"], "t_team": r["t_team"], "score": r["score_before"]})

        eco = economy[economy["round"] == n]
        players = []
        for _, p in eco.iterrows():
            primary, secondary, gren = loadout(list(p["inventory"]))
            players.append({
                "player": str(p["steamid"]), "side": p["side"],
                "money_before": int(p["balance"] + p["cash_spent_this_round"]), "money": int(p["balance"]),
                "equip_before": int(p["round_start_equip_value"]),
                "equip_value": int(p["current_equip_value"]), "armor": int(p["armor_value"]),
                "helmet": bool(p["has_helmet"]), "defuser": bool(p["has_defuser"]),
                "primary": primary, "secondary": secondary, "grenades": gren,
            })
        add(n, r["freeze_end_tick"], "freeze_end", {"players": players})

        for _, k in kills[kills["round"] == n].iterrows():
            add(n, k["tick"], "kill", {
                **rec(k, {"attacker": "attacker_steamid", "victim": "user_steamid", "assister": "assister_steamid",
                          "weapon": "weapon", "headshot": "headshot", "penetrated": "penetrated", "thrusmoke": "thrusmoke",
                          "noscope": "noscope", "attackerblind": "attackerblind", "assistedflash": "assistedflash",
                          "distance_m": "distance"}),
                **({"weapon": "knife"} if str(k["weapon"]).startswith("knife") else {})})
        for _, x in damages[damages["round"] == n].iterrows():
            body = rec(x, {"attacker": "attacker_steamid", "victim": "user_steamid", "weapon": "weapon",
                           "hitgroup": "hitgroup", "dmg_health": "dmg_health", "dmg_armor": "dmg_armor",
                           "health_after": "health", "armor_after": "armor"})
            body["weapon"] = body["weapon"] or "world"  # dano sem arma (queda etc.)
            if body["weapon"].startswith("knife"):
                body["weapon"] = "knife"  # skins de faca (knife_karambit...) viram 'knife'
            add(n, x["tick"], "damage", body)
        for _, s in shots[shots["round"] == n].iterrows():
            add(n, s["tick"], "shot", {
                "shooter": str(s["shooter"]), "weapon": s["weapon"].removeprefix("weapon_"), "hit": bool(s["hit"]),
                "target": clean(s["target"]), "distance_m": clean(s["distance_m"]), "aim_error_deg": clean(s["aim_err_deg"]),
                "speed": clean(s["speed"]), "ducking": bool(s["ducking"]) if pd.notna(s["ducking"]) else False,
                "airborne": bool(s["airborne"]) if pd.notna(s["airborne"]) else False,
                "spray_index": max(1, int(s["spray_index"])) if pd.notna(s["spray_index"]) else 1})
        for _, b in bomb[bomb["round"] == n].iterrows():
            add(n, b["tick"], "bomb", {"event": b["event"], "player": clean(b["user_steamid"]),
                                       "site": site_letter(b["user_last_place_name"]) if b["event"] == "planted" else None})
        for _, g in grenades[grenades["round"] == n].iterrows():
            add(n, g["tick"], "grenade", {"kind": g["grenade"], "thrower": clean(g["user_steamid"])})
        for _, o in onsets[onsets["round"] == n].iterrows():
            add(n, o["tick"], "sighting", {"observer": str(o["observer"]), "target": str(o["target"]),
                                           "distance_m": clean(o["distance_m"]), "aim_error_deg": clean(o["aim_err_deg"])})

        rk = kills[(kills["round"] == n) & (kills["tick"] <= r["end_tick"])]
        alive = {s: 5 - int((rk["user_side"] == s).sum()) for s in ("CT", "T")}
        add(n, r["end_tick"], "round_end", {"winner_side": r["winner_side"], "reason": r["reason"],
                                            "score": r["score_after"], "alive": alive})

    events.sort(key=lambda e: (e[0], e[1], e[2]))
    final = rounds[-1]["score_after"]
    head = {"type": "match_start", "contract_version": CONTRACT_VERSION, "source": "real", "map": match["map"],
            "tickrate": match["tickrate"], "players": [{"player": p["steamid"], "name": p["name"], "team": p["team"]}
                                                       for p in match["players"]]}
    tail = {"type": "match_end", "winner": match["winner"], "score": final}
    out = d / "simlog.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for e in [head] + [e[3] for e in events] + [tail]:
            f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{demo_path.stem.split('__')[-1]}: {len(events) + 2} eventos ({out.stat().st_size // 1024} KB)")
    return out


def main():
    demos = [Path(p) for p in sys.argv[1:]] or sorted(DEMOS_DIR.glob("*.dem"))
    for demo in demos:
        convert(demo)


if __name__ == "__main__":
    main()
