"""Extrai dados das demos de CS2 (demos/*.dem) para data/<demo>/.

Saída por demo:
  match.json        metadados, times, jogadores, placar final
  rounds.json       um registro por round (vencedor, motivo, economia, bomba, primeiro kill)
  kills.parquet     player_death com posições, lados e tempo no round
  damages.parquet   player_hurt
  grenades.parquet  detonações de granadas (smoke, flash, HE, molotov/incendiária)
  bomb.parquet      eventos da C4 (pickup, drop, plant, defuse, explode)
  economy.parquet   estado de cada jogador no fim do freeze time de cada round
  ticks.parquet     posição/vida/arma de cada jogador amostrados durante os rounds

Tabelas em Parquet (tipos preservados, steamids como texto); metadados pequenos em JSON.

Uso: .venv/bin/python -m pipeline.extract_demos [demo.dem ...]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from demoparser2 import DemoParser

from pipeline.common import DATA_DIR as OUT_DIR, DEMOS_DIR, SIDE

# Amostragem do ticks.parquet: a cada 8 ticks (8 amostras/s em 64 tick)
TICK_SAMPLE_EVERY = 8

# O mesmo time aparece com nomes diferentes conforme o torneio
TEAM_ALIASES = {
    "BetBoom Team": "BetBoom",
    "Aurora Gaming": "Aurora",
    "9z Globant": "9z",
    "Team Vitality": "Vitality",
}


def canonical_team(name):
    return TEAM_ALIASES.get(name, name)

PLAYER_EVENT_PROPS = ["X", "Y", "Z", "team_name", "last_place_name", "is_alive"]

ECONOMY_PROPS = [
    "team_name", "team_clan_name", "balance", "current_equip_value",
    "round_start_equip_value", "cash_spent_this_round", "armor_value",
    "has_helmet", "has_defuser", "inventory", "health",
]

TICK_PROPS = [
    "X", "Y", "Z", "pitch", "yaw", "health", "armor_value", "is_alive",
    "team_name", "active_weapon_name", "last_place_name", "balance",
    "current_equip_value", "is_scoped", "is_defusing", "has_defuser",
    "flash_duration",
]

GRENADE_EVENTS = {
    "smokegrenade_detonate": "smoke",
    "flashbang_detonate": "flash",
    "hegrenade_detonate": "he",
    "inferno_startburn": "molotov",
}

BOMB_EVENTS = ["bomb_pickup", "bomb_dropped", "bomb_planted", "bomb_defused", "bomb_exploded"]


def parse_event(parser, name, **kwargs):
    # round_end/round_officially_ended não aparecem em list_game_events(), mas são parseáveis
    try:
        df = parser.parse_event(name, **kwargs)
    except Exception:
        return pd.DataFrame()
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)


def detect_tickrate(parser, a, b):
    df = parser.parse_ticks(["game_time"], ticks=[a, b])
    times = df.groupby("tick")["game_time"].first()
    dt = times.loc[b] - times.loc[a]
    return int(round((b - a) / dt)) if dt > 0 else 64


def build_rounds(parser):
    """Rounds oficiais: após o último begin_new_match, numerados pelo placar."""
    bnm = parse_event(parser, "begin_new_match")
    # Demos da ESL começam já na partida (sem warmup/faca) e não têm begin_new_match
    match_start = int(bnm["tick"].max()) if "tick" in bnm and len(bnm) else 0
    round_end = parse_event(parser, "round_end")
    round_end = round_end[(round_end["tick"] > match_start) & round_end["winner"].notna()]
    official_end = sorted(parse_event(parser, "round_officially_ended")["tick"].tolist())
    freeze_end = sorted(parse_event(parser, "round_freeze_end")["tick"].tolist())

    end_ticks = round_end["tick"].tolist()
    state = parser.parse_ticks(["team_name", "team_clan_name", "team_rounds_total"], ticks=end_ticks)
    state["side"] = state["team_name"].map(SIDE)
    state["team_clan_name"] = state["team_clan_name"].map(canonical_team)
    by_tick = state.groupby(["tick", "side"]).agg(
        team=("team_clan_name", "first"), score=("team_rounds_total", "first")
    )

    rounds = []
    for _, r in round_end.iterrows():
        tick = int(r["tick"])
        ct, t = by_tick.loc[(tick, "CT")], by_tick.loc[(tick, "T")]
        winner_side = SIDE[r["winner"]]
        score_after = {"CT": int(ct["score"]), "T": int(t["score"])}
        rounds.append({
            "round": score_after["CT"] + score_after["T"],
            "end_tick": tick,
            "winner_side": winner_side,
            "winner_team": ct["team"] if winner_side == "CT" else t["team"],
            "reason": r["reason"],
            "ct_team": ct["team"],
            "t_team": t["team"],
            "score_after": {ct["team"]: score_after["CT"], t["team"]: score_after["T"]},
        })

    # Backup restaurado repete um round: fica a última ocorrência
    rounds = list({r["round"]: r for r in rounds}.values())
    rounds.sort(key=lambda r: r["end_tick"])

    prev_bound = match_start
    for r in rounds:
        r["start_tick"] = prev_bound
        fe = [f for f in freeze_end if prev_bound < f <= r["end_tick"]]
        r["freeze_end_tick"] = fe[-1] if fe else prev_bound
        oe = [o for o in official_end if o > r["end_tick"]]
        r["official_end_tick"] = oe[0] if oe else r["end_tick"]
        prev_bound = r["official_end_tick"]
        r["score_before"] = {
            team: score - (1 if team == r["winner_team"] else 0)
            for team, score in r["score_after"].items()
        }
    return match_start, rounds


def assign_round(df, rounds, tickrate):
    """Marca cada evento com round, tempo desde o fim do freeze e se veio após o fim do round."""
    if df.empty:
        return df
    # Eventos antes do fim do freeze são de tentativas abortadas (backup restaurado,
    # que mata todos com weapon=world) e são descartados
    freeze_ends = np.array([r["freeze_end_tick"] for r in rounds])
    ends = np.array([r["official_end_tick"] for r in rounds])
    idx = np.searchsorted(ends, df["tick"].to_numpy(), side="left")
    valid = (idx < len(rounds))
    valid[valid] &= df["tick"].to_numpy()[valid] >= freeze_ends[idx[valid]]
    df = df[valid].copy()
    idx = idx[valid]
    df.insert(0, "round", [rounds[i]["round"] for i in idx])
    freeze = np.array([rounds[i]["freeze_end_tick"] for i in idx])
    end = np.array([rounds[i]["end_tick"] for i in idx])
    df.insert(1, "round_time", np.round((df["tick"].to_numpy() - freeze) / tickrate, 3))
    df.insert(2, "after_round_end", df["tick"].to_numpy() > end)
    return df


def add_sides(df, rounds):
    """Converte colunas *_team_name (CT/TERRORIST) em lado (CT/T) e nome do time."""
    teams = {r["round"]: {"CT": r["ct_team"], "T": r["t_team"]} for r in rounds}
    df = df.drop(columns=[c for c in ("ct_team_name", "t_team_name") if c in df.columns])
    for col in [c for c in df.columns if c.endswith("team_name")]:
        prefix = col[: -len("team_name")]
        side = df[col].map(SIDE)
        df[prefix + "side"] = side
        df[prefix + "team"] = [teams[rn].get(s) for rn, s in zip(df["round"], side)]
        df.drop(columns=col, inplace=True)
    return df


def write_json(path, data):
    if isinstance(data, pd.DataFrame):
        data = json.loads(data.to_json(orient="records"))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))


def write_table(path, df):
    """Parquet com steamids como texto e colunas de tipo misto normalizadas para texto."""
    df = df.copy()
    for col in df.columns:
        if col == "steamid" or col.endswith("_steamid") or col.endswith("_xuid"):
            df[col] = df[col].map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else str(int(v)) if not isinstance(v, str) else v)
        elif df[col].dtype == object:
            types = {type(v) for v in df[col].dropna()}
            if len(types) > 1 and list not in types:
                df[col] = df[col].map(lambda v: None if v is None else str(v))
    df.to_parquet(path, index=False)


def extract(demo_path):
    demo_path = Path(demo_path)
    out = OUT_DIR / demo_path.stem
    out.mkdir(parents=True, exist_ok=True)
    parser = DemoParser(str(demo_path))
    header = parser.parse_header()

    match_start, rounds = build_rounds(parser)
    tickrate = detect_tickrate(parser, rounds[0]["freeze_end_tick"], rounds[0]["end_tick"])

    # Kills
    kills = parse_event(parser, "player_death", player=PLAYER_EVENT_PROPS)
    kills = add_sides(assign_round(kills, rounds, tickrate), rounds)

    # Dano
    damages = parse_event(parser, "player_hurt", player=["team_name", "last_place_name"])
    damages = add_sides(assign_round(damages, rounds, tickrate), rounds)

    # Granadas
    grenades = []
    for name, kind in GRENADE_EVENTS.items():
        g = parse_event(parser, name, player=["team_name"])
        if not g.empty:
            g.insert(0, "grenade", kind)
            grenades.append(g)
    grenades = pd.concat(grenades, ignore_index=True).sort_values("tick") if grenades else pd.DataFrame()
    grenades = add_sides(assign_round(grenades, rounds, tickrate), rounds)

    # Bomba
    bomb = []
    for name in BOMB_EVENTS:
        b = parse_event(parser, name, player=["X", "Y", "Z", "last_place_name"])
        if not b.empty:
            b.insert(0, "event", name.removeprefix("bomb_"))
            bomb.append(b)
    bomb = pd.concat(bomb, ignore_index=True).sort_values("tick") if bomb else pd.DataFrame()
    bomb = assign_round(bomb, rounds, tickrate)

    # Economia no fim do freeze time
    economy = parser.parse_ticks(ECONOMY_PROPS, ticks=[r["freeze_end_tick"] for r in rounds])
    tick_to_round = {r["freeze_end_tick"]: r["round"] for r in rounds}
    economy.insert(0, "round", economy["tick"].map(tick_to_round))
    economy["side"] = economy["team_name"].map(SIDE)
    economy["team_clan_name"] = economy["team_clan_name"].map(canonical_team)
    economy = economy.rename(columns={"team_clan_name": "team"}).drop(columns="team_name")

    # Ticks amostrados durante a parte jogável de cada round
    sample_ticks = []
    for r in rounds:
        sample_ticks.extend(range(r["freeze_end_tick"], r["end_tick"] + 1, TICK_SAMPLE_EVERY))
    ticks = parser.parse_ticks(TICK_PROPS, ticks=sample_ticks)
    ticks = add_sides(assign_round(ticks, rounds, tickrate), rounds)
    write_table(out / "ticks.parquet", ticks)

    # Jogadores
    players = (
        economy.groupby("steamid")
        .agg(name=("name", "last"), team=("team", "last"))
        .reset_index()
    )
    players["steamid"] = players["steamid"].astype(str)

    # Resumo por round
    real_kills = kills[~kills["after_round_end"]]
    for r in rounds:
        rn = r["round"]
        rk = real_kills[real_kills["round"] == rn].sort_values("tick")
        if not rk.empty:
            fk = rk.iloc[0]
            r["first_kill"] = {
                "attacker": fk["attacker_name"], "attacker_side": fk.get("attacker_side"),
                "victim": fk["user_name"], "victim_side": fk.get("user_side"),
                "weapon": fk["weapon"], "round_time": fk["round_time"],
            }
        else:
            r["first_kill"] = None
        r["kills"] = {"CT": int((rk["attacker_side"] == "CT").sum()), "T": int((rk["attacker_side"] == "T").sum())}
        rb = bomb[(bomb["round"] == rn)] if not bomb.empty else bomb
        # Plants depois do fim do round (Ts já venceram por eliminação) não contam
        planted = rb[(rb["event"] == "planted") & ~rb["after_round_end"]] if not rb.empty else rb
        r["bomb_planted"] = not planted.empty
        if not planted.empty:
            p = planted.iloc[0]
            r["plant"] = {"site": p.get("user_last_place_name"), "planter": p["user_name"], "round_time": p["round_time"]}
        re = economy[economy["round"] == rn]
        r["economy"] = {
            side: {
                "team": grp["team"].iloc[0],
                "equip_value": int(grp["current_equip_value"].sum()),
                "start_equip_value": int(grp["round_start_equip_value"].sum()),
                "spent": int(grp["cash_spent_this_round"].sum()),
                "money_left": int(grp["balance"].sum()),
            }
            for side, grp in re.groupby("side")
        }

    final = rounds[-1]["score_after"]
    match = {
        "demo": demo_path.name,
        "series": demo_path.stem.split("__")[0] if "__" in demo_path.stem else None,
        "map": header.get("map_name"),
        "server": header.get("server_name"),
        "patch_version": header.get("patch_version"),
        "tickrate": tickrate,
        "match_start_tick": match_start,
        "teams": sorted(final),
        "final_score": final,
        "winner": max(final, key=final.get),
        "rounds_played": len(rounds),
        "players": json.loads(players.to_json(orient="records")),
    }

    write_json(out / "match.json", match)
    write_json(out / "rounds.json", rounds)
    write_table(out / "kills.parquet", kills)
    write_table(out / "damages.parquet", damages)
    write_table(out / "grenades.parquet", grenades)
    write_table(out / "bomb.parquet", bomb)
    write_table(out / "economy.parquet", economy)

    print(f"{demo_path.name}: {match['map']} {final} | {len(rounds)} rounds, "
          f"{len(kills)} kills, {len(damages)} danos, {len(grenades)} granadas, {len(ticks)} linhas de ticks")
    return match


def main():
    demos = [Path(p) for p in sys.argv[1:]] or sorted(DEMOS_DIR.glob("*.dem"))
    OUT_DIR.mkdir(exist_ok=True)
    summary = [extract(d) for d in demos]
    write_json(OUT_DIR / "index.json", [
        {k: m[k] for k in ("demo", "series", "map", "final_score", "winner", "rounds_played")} for m in summary
    ])


if __name__ == "__main__":
    main()
