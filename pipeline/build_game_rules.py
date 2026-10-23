"""Gera contract/artifacts/game_rules.json: regras e constantes do CS2 para a simulação.

Duas fontes, sempre identificadas no JSON:
  - oficial:  arquivos do jogo na build das demos (reference/cs2_build_2000930/, de
              SteamDatabase/GameTracking-CS2) + cvars do servidor gravadas nas demos
  - medido:   valores observados nas demos, usados para validar o oficial e para
              cobrir o que não está nos arquivos (multiplicadores de dano, fórmula do
              colete, velocidades de andar/agachar, tempos de plant/defuse, economia)

Uso: .venv/bin/python -m pipeline.build_game_rules
"""
import json
import re
from datetime import date

import numpy as np
import pandas as pd
from demoparser2 import DemoParser

from pipeline.common import (ARTIFACTS_DIR as OUT, CONTRACT_VERSION, DATA_DIR, DEMOS_DIR, REFERENCE_DIR,
                             SIDE, TICKRATE, WEAPON_CLASS)
from pipeline.extract_demos import parse_event

REF_DIR = REFERENCE_DIR / "cs2_build_2000930"
SCHEMA_VERSION = "1.0"
GAME_BUILD = {
    "client_version": 2000930, "patch_version": "1.41.9.0",
    "files_commit": "https://github.com/SteamDatabase/GameTracking-CS2/tree/f68ba6aa24",
    # Builds das demos comparadas com a de referência (weapons.vdata, gamemode_competitive.cfg, preços)
    "demo_builds_compatibility": {
        "14190 (1.41.9.0, Thunderpick)": "build de referência",
        "14188 (1.41.8.8, ESL Pro League; commit 7193ca82cb)": "igual, exceto aug.reload_attack_lock_s 3.766667 (hoje 3.2)",
        "14181 (1.41.8.1, StarLadder; commit d8e2c7a4f9)": "igual, exceto aug.reload_attack_lock_s 3.766667 e sem a m14 (arma nova no 1.41.9.0)",
    },
}


# ---------- leitura do KV3 (weapons.vdata) ----------

KV3_TOKEN = re.compile(r'''
    (?P<comment>//[^\n]*|<!--.*?-->)
  | (?P<typed>[A-Za-z_][A-Za-z0-9_]*:"(?:[^"\\]|\\.)*")
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<punct>[{}\[\]=,])
  | (?P<word>[^\s{}\[\]=,"]+)
''', re.VERBOSE | re.DOTALL)


def parse_kv3(text):
    tokens = [(m.lastgroup, m.group()) for m in KV3_TOKEN.finditer(text) if m.lastgroup != "comment"]
    pos = 0

    def value():
        nonlocal pos
        kind, tok = tokens[pos]
        pos += 1
        if tok == "{":
            obj = {}
            while tokens[pos][1] != "}":
                key = tokens[pos][1].strip('"')
                pos += 2  # chave e "="
                obj[key] = value()
            pos += 1
            return obj
        if tok == "[":
            arr = []
            while tokens[pos][1] != "]":
                if tokens[pos][1] == ",":
                    pos += 1
                    continue
                arr.append(value())
            pos += 1
            return arr
        if kind == "string":
            return tok[1:-1]
        if kind == "typed":
            return tok.split(":", 1)[1].strip('"')
        if tok in ("true", "false"):
            return tok == "true"
        try:
            return int(tok)
        except ValueError:
            try:
                return float(tok)
            except ValueError:
                return tok

    return value()


def parse_cfg(text):
    out = {}
    for line in text.splitlines():
        line = line.split("//")[0].strip()
        if line:
            parts = line.split(None, 1)
            out[parts[0]] = parts[1].strip().strip('"') if len(parts) > 1 else ""
    return out


def num(v):
    if isinstance(v, (int, float)) or v is None:
        return v
    s = str(v).strip().lower()
    if s in ("true", "false"):
        return s == "true"
    try:
        f = float(s)
        return int(f) if f.is_integer() and "." not in s else f
    except ValueError:
        return v


# ---------- armas ----------

def pair(v):
    """Campos [normal, alternativo] do vdata (alternativo = mira/silenciador/modo alternativo)."""
    if isinstance(v, list):
        return {"normal": v[0], "alt": v[1] if len(v) > 1 else v[0]}
    return {"normal": v, "alt": v}


def weapon_entry(name, w):
    cycle = w.get("m_flCycleTime")
    cycle_n = cycle[0] if isinstance(cycle, list) else cycle
    entry = {
        "type": w.get("m_WeaponType"),
        "gear_slot": w.get("m_GearSlot"),
        "price": w.get("m_nPrice"),
        "kill_award": w.get("m_nKillAward"),
        "damage": w.get("m_nDamage"),
        "bullets_per_shot": w.get("m_nNumBullets"),
        "armor_penetration": round(w["m_flArmorRatio"] * 0.5, 4) if "m_flArmorRatio" in w else None,
        "armor_ratio_raw": w.get("m_flArmorRatio"),
        "headshot_multiplier": w.get("m_flHeadshotMultiplier"),
        "range_units": w.get("m_flRange"),
        "range_modifier": w.get("m_flRangeModifier"),
        "penetration_power": w.get("m_flPenetration"),
        "cycle_time_s": pair(cycle),
        "rpm": round(60 / cycle_n) if cycle_n else None,
        "full_auto": w.get("m_bIsFullAuto"),
        "burst_mode": w.get("m_bHasBurstMode"),
        "clip_size": w.get("m_iMaxClip1"),
        "reserve_clips": w.get("m_nPrimaryReserveAmmoMax") if w.get("m_bReserveAmmoAsClips") else None,
        "reserve_ammo": None if w.get("m_bReserveAmmoAsClips") else w.get("m_nPrimaryReserveAmmoMax"),
        "max_speed": pair(w.get("m_flMaxSpeed")),
        "attack_movespeed_factor": w.get("m_flAttackMovespeedFactor"),
        "spread": pair(w.get("m_flSpread")),
        "inaccuracy": {k: pair(w.get(f"m_flInaccuracy{v}")) for k, v in {
            "stand": "Stand", "crouch": "Crouch", "move": "Move", "jump": "Jump",
            "land": "Land", "ladder": "Ladder", "fire": "Fire"} .items() if f"m_flInaccuracy{v}" in w},
        "inaccuracy_jump_initial": w.get("m_flInaccuracyJumpInitial"),
        "recovery_time_s": {
            "stand": w.get("m_flRecoveryTimeStand"), "crouch": w.get("m_flRecoveryTimeCrouch"),
            "stand_final": w.get("m_flRecoveryTimeStandFinal"), "crouch_final": w.get("m_flRecoveryTimeCrouchFinal"),
            "transition_start_bullet": w.get("m_nRecoveryTransitionStartBullet"),
            "transition_end_bullet": w.get("m_nRecoveryTransitionEndBullet"),
        },
        "recoil": {
            "angle": pair(w.get("m_flRecoilAngle")), "angle_variance": pair(w.get("m_flRecoilAngleVariance")),
            "magnitude": pair(w.get("m_flRecoilMagnitude")), "magnitude_variance": pair(w.get("m_flRecoilMagnitudeVariance")),
            "seed": w.get("m_nRecoilSeed"),
        },
        "deploy_time_s": w.get("m_flDeployDuration"),
        "reload_attack_lock_s": w.get("m_flDisallowAttackAfterReloadStartDuration"),
        "zoom": {"levels": w.get("m_nZoomLevels"), "fov1": w.get("m_nZoomFOV1"), "fov2": w.get("m_nZoomFOV2"),
                 "unzoom_after_shot": w.get("m_bUnzoomsAfterShot")},
        "silencer": w.get("m_eSilencerType"),
        "tagging": {"flinch_velocity_modifier_large": w.get("m_flFlinchVelocityModifierLarge"),
                    "flinch_velocity_modifier_small": w.get("m_flFlinchVelocityModifierSmall")},
    }
    return {k: v for k, v in entry.items() if v is not None}


def load_weapons():
    vdata = parse_kv3((REF_DIR / "weapons.vdata").read_text())
    return {k.removeprefix("weapon_"): weapon_entry(k, v) for k, v in vdata.items()
            if k.startswith("weapon_") and not k.endswith("_prefab") and k != "weapon_base" and isinstance(v, dict)}


# ---------- regras de partida (cvars) ----------

MATCH_CVARS = ("mp_", "cash_", "ammo_", "ff_", "spec_freeze_time")


def load_match_config(demo_cvars):
    defaults = parse_cfg((REF_DIR / "gamemode_competitive.cfg").read_text())
    keys = sorted(k for k in set(defaults) | set(demo_cvars) if k.startswith(MATCH_CVARS))
    out = {}
    for k in keys:
        if k in demo_cvars:
            out[k] = {"value": num(demo_cvars[k]), "source": "torneio (cvar na demo)",
                      **({"competitive_default": num(defaults[k])} if k in defaults and defaults[k] != demo_cvars[k] else {})}
        else:
            out[k] = {"value": num(defaults[k]), "source": "padrão competitivo"}
    return out


def demo_cvars(parser, match_start):
    sc = parse_event(parser, "server_cvar")
    sc = sc[sc["tick"] <= match_start + 2000]
    return dict(zip(*sc.drop_duplicates("name", keep="last")[["name", "value"]].T.values))


# ---------- medições ----------

HITGROUPS = ["head", "neck", "chest", "stomach", "left_arm", "right_arm", "left_leg", "right_leg"]
# Medido nas demos: o pescoço NÃO é cabeça (×1,0, protegido pelo colete; 92% de acerto exato em 52 acertos)
DEFAULT_HG_MULT = {"chest": 1.0, "stomach": 1.25, "left_arm": 1.0, "right_arm": 1.0,
                   "left_leg": 0.75, "right_leg": 0.75, "neck": 1.0}


def predict_damage(base, range_mod, dist_units, hg_mult, armor_pen, armor_before, armored_hit):
    """Fórmula de dano do CS (motor Source): retorna (dano na vida, dano no colete)."""
    dmg = base * range_mod ** (dist_units / 500.0) * hg_mult
    if armored_hit and armor_before > 0:
        health = dmg * armor_pen
        armor = (dmg - health) * 0.5
        if armor > armor_before:
            armor = armor_before
            health = dmg - armor * 2
        return int(health), int(armor)
    return int(dmg), 0


def measure_damage(parser, rounds, weapons, display_names):
    ev = parse_event(parser, "player_hurt", player=["X", "Y", "Z", "has_helmet", "active_weapon_name", "team_name"])
    # Fogo amigo é multiplicado por ff_damage_reduction_bullets (0,33): não segue a fórmula e fica de fora
    ev = ev[ev["attacker_team_name"] != ev["user_team_name"]]
    # O evento chama variantes pelo mesmo nome (M4A1-S e M4A4 viram "m4a1"); a arma na mão do atirador desambigua
    # Só o 'm4a1' é ambíguo. Trocar a arma de TODO evento pela que está na mão atribuiria dano de molotov e HE
    # (hitgroup 'generic') à arma de fogo que o jogador segura depois de arremessar.
    held = ev["attacker_active_weapon_name"].map(display_names)
    ambiguous = (ev["weapon"] == "m4a1") & held.notna() & held.isin(weapons.keys())
    ev["weapon"] = held.where(ambiguous, ev["weapon"])
    ev = ev[ev["weapon"].isin(weapons.keys()) & ev["attacker_X"].notna()].copy()
    ev["dist_units"] = np.sqrt((ev["attacker_X"] - ev["user_X"]) ** 2 + (ev["attacker_Y"] - ev["user_Y"]) ** 2
                               + (ev["attacker_Z"] - ev["user_Z"]) ** 2)
    ev["armor_before"] = ev["armor"] + ev["dmg_armor"]
    ev["helmet"] = ev["user_has_helmet"].fillna(False).astype(bool)
    return ev


def damage_model(hurt, weapons):
    """Estima multiplicadores por parte do corpo e valida a fórmula do colete."""
    h = hurt[hurt["health"] > 0].copy()  # dano letal fica limitado à vida restante
    h["base"] = h["weapon"].map(lambda w: weapons[w]["damage"])
    h["rmod"] = h["weapon"].map(lambda w: weapons[w]["range_modifier"])
    h["pen"] = h["weapon"].map(lambda w: weapons[w]["armor_penetration"])
    h["hsmult"] = h["weapon"].map(lambda w: weapons[w]["headshot_multiplier"])
    h["raw"] = h["base"] * h["rmod"] ** (h["dist_units"] / 500.0)
    h = h[h["weapon"].map(lambda w: weapons[w].get("bullets_per_shot", 1)) == 1]  # sem escopetas

    # Multiplicador que reproduz exatamente o maior número de danos sem colete. Tiros que
    # atravessam parede só reduzem o dano, então a mediana seria puxada para baixo.
    mult = {}
    unarmored = h[h["armor_before"] == 0]
    candidates = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]
    for hg, g in unarmored.groupby("hitgroup"):
        scale = g["hsmult"] if hg == "head" else 1.0
        rates = {c: float(((g["raw"] * c * (scale / (4.0 if hg == "head" else 1.0))).astype(int)
                           == g["dmg_health"]).mean()) for c in candidates}
        best = max(rates, key=rates.get)
        mult[hg] = {"best_fit": best, "exact_match_rate": round(rates[best], 3), "n": int(len(g))}

    def hg_mult(row):
        if row["hitgroup"] == "head":
            return row["hsmult"]
        return DEFAULT_HG_MULT.get(row["hitgroup"], 1.0)

    def armored_hit(row):
        if row["hitgroup"] in ("left_leg", "right_leg"):
            return False
        if row["hitgroup"] == "head":
            return row["helmet"]
        return True

    pred = h.apply(lambda r: predict_damage(r["base"], r["rmod"], r["dist_units"], hg_mult(r), r["pen"],
                                            r["armor_before"], armored_hit(r)), axis=1)
    h["pred_health"] = [p[0] for p in pred]
    h["pred_armor"] = [p[1] for p in pred]
    # "generic" = acerto sem parte do corpo definida (típico de tiro que atravessou algo); fica fora da validação
    generic_share = round(float((h["hitgroup"] == "generic").mean()), 3)
    h = h[h["hitgroup"] != "generic"]
    diff = h["dmg_health"] - h["pred_health"]
    err = diff.abs()
    by_case = {}
    for name, mask in {"sem_colete": h["armor_before"] == 0, "com_colete": h["armor_before"] > 0}.items():
        e, d = err[mask], diff[mask]
        by_case[name] = {"n": int(mask.sum()), "exato": round(float((e == 0).mean()), 3),
                         "ate_1hp": round(float((e <= 1).mean()), 3),
                         # dano menor que o previsto é compatível com tiro atravessando parede/objeto
                         "menor_que_previsto": round(float((d < -1).mean()), 3),
                         "maior_que_previsto": round(float((d > 1).mean()), 3)}
    by_hg = {hg: {"n": int(len(g)), "ate_1hp": round(float((err[g.index] <= 1).mean()), 3),
                  "maior_que_previsto": round(float((diff[g.index] > 1).mean()), 3)}
             for hg, g in h.groupby("hitgroup")}
    by_weapon = {w: {"n": int(len(g)), "ate_1hp": round(float((err[g.index] <= 1).mean()), 3),
                     "maior_que_previsto": round(float((diff[g.index] > 1).mean()), 3)}
                 for w, g in h.groupby("weapon") if len(g) >= 15}
    armor_err = (h["dmg_armor"] - h["pred_armor"]).abs()
    return mult, {"vida": by_case, "por_parte_do_corpo": by_hg, "por_arma": by_weapon,
                  "generic_hitgroup_share": generic_share,
                  "dano_no_colete_ate_1": round(float((armor_err[h["armor_before"] > 0] <= 1).mean()), 3)}


def measure_fire_rate(parser, rounds, weapons):
    wf = parse_event(parser, "weapon_fire")
    wf["weapon"] = wf["weapon"].str.removeprefix("weapon_")
    wf = wf[wf["weapon"].isin(weapons.keys())].sort_values(["user_steamid", "tick"])
    wf["dt"] = wf.groupby("user_steamid")["tick"].diff()
    same = wf["weapon"] == wf.groupby("user_steamid")["weapon"].shift()
    out = {}
    for w, g in wf[same].groupby("weapon"):
        cyc = weapons[w]["cycle_time_s"]["normal"] * TICKRATE
        cont = g["dt"][(g["dt"] > 0) & (g["dt"] <= cyc * 1.5)]  # tiros em sequência contínua
        if len(cont) >= 10:
            # Média: o intervalo oficial cai entre ticks (0,1 s = 6,4 ticks) e alterna entre 6 e 7
            out[w] = {"measured_interval_s_mean": round(float(cont.mean() / TICKRATE), 4), "n": int(len(cont))}
    return out


def measure_movement(parser, rounds, weapon_names):
    base = [t for r in rounds for t in range(r["freeze_end_tick"], r["end_tick"], 16)]
    st = parser.parse_ticks(["X", "Y", "is_alive", "is_walking", "ducking", "is_scoped", "is_airborne",
                             "active_weapon_name"], ticks=sorted(set(base) | {t + 1 for t in base}))
    nxt = st[["tick", "steamid", "X", "Y"]].copy()
    nxt["tick"] -= 1
    m = st[st["tick"].isin(base)].merge(nxt, on=["tick", "steamid"], suffixes=("", "_n"))
    m["speed"] = np.hypot(m["X_n"] - m["X"], m["Y_n"] - m["Y"]) * TICKRATE
    m = m[m["is_alive"].astype(bool) & ~m["is_airborne"].fillna(False).astype(bool)]
    m["weapon"] = m["active_weapon_name"].map(weapon_names)
    return m[["weapon", "speed", "is_walking", "ducking", "is_scoped"]]


def weapon_display_names(parser):
    """Mapeia o nome de exibição (ex.: 'AK-47') para o id (ak47) cruzando tiros com a arma ativa."""
    wf = parse_event(parser, "weapon_fire")
    st = parser.parse_ticks(["active_weapon_name"], ticks=sorted(wf["tick"].unique()))
    m = wf.assign(user_steamid=wf["user_steamid"].astype(str)).merge(
        st.assign(steamid=st["steamid"].astype(str)), left_on=["tick", "user_steamid"], right_on=["tick", "steamid"])
    m["weapon"] = m["weapon"].str.removeprefix("weapon_")
    return m.groupby("active_weapon_name")["weapon"].agg(lambda s: s.value_counts().index[0]).to_dict()


def measure_bomb(parser, rounds):
    planted = parse_event(parser, "bomb_planted")
    exploded = parse_event(parser, "bomb_exploded")
    defused = parse_event(parser, "bomb_defused")
    out = {"timer_s": [], "plant_s": [], "defuse_s": {"with_kit": [], "without_kit": []}}
    valid = lambda t: any(r["freeze_end_tick"] <= t <= r["official_end_tick"] for r in rounds)
    for _, e in exploded.iterrows():
        p = planted[(planted["tick"] < e["tick"])]
        if valid(e["tick"]) and len(p):
            out["timer_s"].append((e["tick"] - p["tick"].max()) / TICKRATE)
    for _, p in planted.iterrows():
        if not valid(p["tick"]):
            continue
        win = list(range(int(p["tick"]) - 320, int(p["tick"]) + 1))
        st = parser.parse_ticks(["m_bStartedArming"], ticks=win)
        st = st[st["steamid"].astype(str) == str(p["user_steamid"])].set_index("tick")["m_bStartedArming"]
        arming = st.fillna(False).astype(bool)
        if arming.any():
            # início da última sequência contínua de "armando"
            ticks = arming[arming].index
            start = ticks[-1]
            for t in reversed(ticks):
                if start - t > 1:
                    break
                start = t
            out["plant_s"].append((p["tick"] - start) / TICKRATE)
    for _, d in defused.iterrows():
        if not valid(d["tick"]):
            continue
        win = list(range(int(d["tick"]) - 704, int(d["tick"]) + 1))
        st = parser.parse_ticks(["is_defusing", "has_defuser"], ticks=win)
        st = st[st["steamid"].astype(str) == str(d["user_steamid"])].set_index("tick")
        dfs = st["is_defusing"].fillna(False).astype(bool)
        if dfs.any():
            ticks = dfs[dfs].index
            start = ticks[-1]
            for t in reversed(ticks):
                if start - t > 1:
                    break
                start = t
            kit = bool(st["has_defuser"].fillna(False).iloc[-2])
            out["defuse_s"]["with_kit" if kit else "without_kit"].append((d["tick"] - start) / TICKRATE)
    return out


def measure_utility(parser, rounds):
    out = {}
    # entityid é reaproveitado: casa cada início com o primeiro fim seguinte da mesma entidade
    for start, end, name in [("smokegrenade_detonate", "smokegrenade_expired", "smoke_duration_s"),
                             ("inferno_startburn", "inferno_expire", "molotov_burn_duration_s")]:
        a = parse_event(parser, start)[["entityid", "tick"]].sort_values("tick")
        b = parse_event(parser, end)[["entityid", "tick"]].rename(columns={"tick": "tick_end"}).sort_values("tick_end")
        m = pd.merge_asof(a, b, left_on="tick", right_on="tick_end", by="entityid", direction="forward")
        m = m.dropna(subset=["tick_end"])
        dur = (m["tick_end"] - m["tick"]) / TICKRATE
        out[name] = dur[dur <= 60].tolist()  # fins sem par (fim do round, restart) geram durações absurdas
    # Tempo até detonar: do primeiro tick do projétil em voo até a detonação
    g = parser.parse_grenades()
    g = g[g["grenade_type"].str.endswith("Projectile") & g["x"].notna()].sort_values(["grenade_entity_id", "tick"])
    seg = (g.groupby("grenade_entity_id")["tick"].diff() != 1).cumsum().rename("segment")
    span = g.groupby([seg, "grenade_entity_id", "grenade_type"])["tick"].agg(["min", "max"]).reset_index()
    for gtype, ev, label in [("CHEGrenadeProjectile", "hegrenade_detonate", "he"),
                             ("CFlashbangProjectile", "flashbang_detonate", "flash"),
                             ("CSmokeGrenadeProjectile", "smokegrenade_detonate", "smoke")]:
        det = parse_event(parser, ev)[["entityid", "tick"]]
        s = span[span["grenade_type"] == gtype].merge(det, left_on="grenade_entity_id", right_on="entityid")
        s = s[(s["tick"] >= s["min"]) & (s["tick"] <= s["max"] + 2)]
        out.setdefault("time_to_detonate_s", {}).setdefault(label, []).extend(((s["tick"] - s["min"]) / TICKRATE).tolist())
    # Dano de HE e molotov
    hurt = parse_event(parser, "player_hurt")
    out["he_damage"] = hurt[hurt["weapon"] == "hegrenade"][["dmg_health", "dmg_armor"]].to_dict("records")
    out["molotov_damage_events"] = hurt[hurt["weapon"] == "inferno"]["dmg_health"].tolist()
    # Duração de cegueira (flash_duration quando muda)
    st = parser.parse_ticks(["flash_duration"], ticks=[t for r in rounds for t in range(r["freeze_end_tick"], r["end_tick"], 4)])
    st = st.sort_values(["steamid", "tick"])
    rise = st["flash_duration"] > st.groupby("steamid")["flash_duration"].shift().fillna(0) + 0.05
    out["flash_blind_s"] = st.loc[rise, "flash_duration"].tolist()
    return out


def measure_round_timing(parser, rounds):
    times = {"freeze_s": [], "round_time_used_s": {}, "restart_delay_s": []}
    for r in rounds:
        times["freeze_s"].append((r["freeze_end_tick"] - r["start_tick"]) / TICKRATE)
        times["round_time_used_s"].setdefault(r["reason"], []).append((r["end_tick"] - r["freeze_end_tick"]) / TICKRATE)
        times["restart_delay_s"].append((r["official_end_tick"] - r["end_tick"]) / TICKRATE)
    times["freeze_s"] = times["freeze_s"][1:]  # o primeiro round começa com o begin_new_match
    return times


def measure_economy(parser, rounds):
    """Dinheiro recebido por cada jogador na virada do round (antes de qualquer compra)."""
    ticks = [t for r in rounds for t in (r["end_tick"] - 1, r["official_end_tick"] + 1)]
    st = parser.parse_ticks(["balance", "team_name"], ticks=ticks)
    st["steamid"] = st["steamid"].astype(str)
    rows = []
    kills = parse_event(parser, "player_death")
    for r in rounds:
        a = st[st["tick"] == r["end_tick"] - 1].set_index("steamid")
        b = st[st["tick"] == r["official_end_tick"] + 1].set_index("steamid")
        # Kills depois do fim do round também dão dinheiro: só jogadores sem kill nesse intervalo
        late = kills[(kills["tick"] >= r["end_tick"] - 1) & (kills["tick"] <= r["official_end_tick"] + 1)]
        late_killers = set(late["attacker_steamid"].dropna().astype(str))
        for sid in a.index.intersection(b.index):
            if sid in late_killers:
                continue
            side = SIDE.get(a.loc[sid, "team_name"])
            rows.append({"round": r["round"], "side": side, "won": side == r["winner_side"], "reason": r["reason"],
                         "delta": int(b.loc[sid, "balance"] - a.loc[sid, "balance"]),
                         "capped": int(b.loc[sid, "balance"]) >= 16000})
    return pd.DataFrame(rows)


# ---------- agregação ----------

def stats(values, digits=3):
    s = pd.Series(values, dtype=float).dropna()
    if s.empty:
        return None
    return {"median": round(float(s.median()), digits), "p10": round(float(s.quantile(.1)), digits),
            "p90": round(float(s.quantile(.9)), digits), "min": round(float(s.min()), digits),
            "max": round(float(s.max()), digits), "n": int(len(s))}


CT_BONUS_PER_T_DEATH = 50   # medido: não está no gamemode_competitive.cfg


def half_start(n):
    return n in (1, 13) or (n > 24 and (n - 25) % 3 == 0)


def economy_rule_fit(econ, rounds_by_demo, kills_by_demo, cfg):
    """Testa regras do contador de derrotas contra o dinheiro recebido por round.

    Esperado do perdedor = 1400 + 500*(contador-1) [+600 se o T plantou] [+50 por T morto, se CT];
    do vencedor = prêmio pelo motivo [+50 por T morto, se CT]. Usa a moda dos jogadores do lado
    (Ts vivos quando o tempo acaba recebem 0 e ficam fora da moda). Rounds em que o dinheiro é
    redefinido (fim de metade/prorrogação) e o último round da partida são ignorados.
    """
    win_reward = {"t_killed": cfg["cash_team_elimination_bomb_map"]["value"],
                  "ct_killed": cfg["cash_team_elimination_bomb_map"]["value"],
                  "bomb_exploded": cfg["cash_team_terrorist_win_bomb"]["value"],
                  "bomb_defused": cfg["cash_team_win_by_defusing_bomb"]["value"],
                  "time_ran_out": cfg["cash_team_win_by_time_running_out_bomb"]["value"]}
    base = cfg["cash_team_loser_bonus"]["value"]
    step = cfg["cash_team_loser_bonus_consecutive_rounds"]["value"]
    start = cfg["mp_starting_losses"]["value"]
    planted_bonus = cfg["cash_team_planted_bomb_but_defused"]["value"]
    on_win = {"zera": lambda c: 0, "desconta_1": lambda c: max(c - 1, 0), "desconta_2": lambda c: max(c - 2, 0)}
    rows = []
    for demo, rounds in rounds_by_demo.items():
        e, k = econ[econ["demo"] == demo], kills_by_demo[demo]
        last = rounds[-1]["round"]
        for rule, fn in on_win.items():
            c = {}
            for r in rounds:
                n = r["round"]
                if half_start(n):
                    c = {"CT": start, "T": start}
                win = r["winner_side"]
                los = "T" if win == "CT" else "CT"
                c[los] = min(c[los] + 1, 5)
                t_deaths = int(((k["round"] == n) & (k["user_side"] == "T") & (k["attacker_side"] == "CT")).sum())
                expected = {
                    los: base + step * (c[los] - 1) + (planted_bonus if los == "T" and r.get("bomb_planted") else 0)
                         + (CT_BONUS_PER_T_DEATH * t_deaths if los == "CT" else 0),
                    win: win_reward[r["reason"]] + (CT_BONUS_PER_T_DEATH * t_deaths if win == "CT" else 0),
                }
                c[win] = fn(c[win])
                if n == last or half_start(n + 1):
                    continue
                for side, exp in expected.items():
                    obs = e[(e["round"] == n) & (e["side"] == side) & ~e["capped"]]["delta"]
                    if len(obs):
                        rows.append({"rule": rule, "role": "perdedor" if side == los else "vencedor",
                                     "ok": int(obs.mode().iloc[0] == exp)})
    df = pd.DataFrame(rows)
    return {rule: {role: {"acerto": round(float(g2["ok"].mean()), 3), "n": int(len(g2))}
                   for role, g2 in g.groupby("role")} for rule, g in df.groupby("rule")}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    weapons = load_weapons()
    guns = {k: v for k, v in weapons.items() if v.get("damage") and v.get("type") not in
            ("WEAPONTYPE_GRENADE", "WEAPONTYPE_KNIFE", "WEAPONTYPE_C4", "WEAPONTYPE_TASER", "WEAPONTYPE_EQUIPMENT")}

    hurt_all, fire, move, bomb, util, timing, econ, cvars_seen, names = [], {}, [], [], [], [], [], {}, {}
    rounds_by_demo, kills_by_demo = {}, {}
    for demo in sorted(DEMOS_DIR.glob("*.dem")):
        match = json.loads((DATA_DIR / demo.stem / "match.json").read_text())
        rounds = json.loads((DATA_DIR / demo.stem / "rounds.json").read_text())
        rounds_by_demo[demo.stem] = rounds
        kills_by_demo[demo.stem] = pd.read_parquet(DATA_DIR / demo.stem / "kills.parquet")
        parser = DemoParser(str(demo))
        cvars_seen.update(demo_cvars(parser, match["match_start_tick"]))
        names.update(weapon_display_names(parser))
        hurt_all.append(measure_damage(parser, rounds, guns, names))
        for w, v in measure_fire_rate(parser, rounds, guns).items():
            fire.setdefault(w, []).append(v)
        move.append(measure_movement(parser, rounds, names))
        bomb.append(measure_bomb(parser, rounds))
        util.append(measure_utility(parser, rounds))
        timing.append(measure_round_timing(parser, rounds))
        econ.append(measure_economy(parser, rounds).assign(demo=demo.stem))
        print(f"{demo.stem}: ok")

    cfg = load_match_config(cvars_seen)
    hurt = pd.concat(hurt_all, ignore_index=True)
    hg_mult, damage_fit = damage_model(hurt, guns)

    # Cadência: compara intervalo medido com o oficial
    for w, vals in fire.items():
        if not weapons[w].get("full_auto"):
            continue  # em armas semiautomáticas o intervalo depende do jogador, não da arma
        n = sum(v["n"] for v in vals)
        mean = float(np.average([v["measured_interval_s_mean"] for v in vals], weights=[v["n"] for v in vals]))
        weapons[w]["measured"] = {**weapons[w].get("measured", {}),
                                  "fire_interval_s": {"mean": round(mean, 4), "n": n,
                                                      "official": weapons[w]["cycle_time_s"]["normal"]}}

    # Velocidade: p99 correndo (sem shift, sem agachar, sem mira) vs oficial
    mv = pd.concat(move, ignore_index=True)
    mv = mv[mv["weapon"].notna()]
    run = mv[~mv["is_walking"].fillna(False).astype(bool) & ~mv["ducking"].fillna(False).astype(bool)
             & ~mv["is_scoped"].fillna(False).astype(bool)]
    for w, g in run.groupby("weapon"):
        if w in weapons and len(g) >= 50:
            weapons[w].setdefault("measured", {})["run_speed_p99"] = {
                "value": round(float(g["speed"].quantile(.99)), 1), "n": int(len(g)),
                "official": weapons[w]["max_speed"]["normal"]}
    ratios = {}
    for state, mask in {"walk": mv["is_walking"].fillna(False).astype(bool) & ~mv["ducking"].fillna(False).astype(bool),
                        "crouch": mv["ducking"].fillna(False).astype(bool)}.items():
        g = mv[mask].copy()
        g["max"] = g["weapon"].map(lambda w: weapons.get(w, {}).get("max_speed", {}).get("normal"))
        g = g[g["max"].notna()]
        r = g["speed"] / g["max"]
        moving = r[r > 0.05]
        ratios[state] = {**{f"speed_ratio_p{q}": round(float(moving.quantile(q / 100)), 3) for q in (50, 75, 90, 95, 99)},
                         "n_moving": int(len(moving))}

    bomb_all = {"timer_s": [], "plant_s": [], "with_kit": [], "without_kit": []}
    for b in bomb:
        bomb_all["timer_s"] += b["timer_s"]; bomb_all["plant_s"] += b["plant_s"]
        bomb_all["with_kit"] += b["defuse_s"]["with_kit"]; bomb_all["without_kit"] += b["defuse_s"]["without_kit"]

    u = {"smoke": [], "molotov": [], "flash": [], "he": [], "molotov_dmg": [], "fuse": {}}
    for x in util:
        u["smoke"] += x["smoke_duration_s"]; u["molotov"] += x["molotov_burn_duration_s"]
        u["flash"] += x["flash_blind_s"]; u["he"] += x["he_damage"]; u["molotov_dmg"] += x["molotov_damage_events"]
        for k, v in x["time_to_detonate_s"].items():
            u["fuse"].setdefault(k, []).extend(v)
    he = pd.DataFrame(u["he"])

    t_all = {"freeze_s": [], "restart_delay_s": [], "by_reason": {}}
    for t in timing:
        t_all["freeze_s"] += t["freeze_s"]; t_all["restart_delay_s"] += t["restart_delay_s"]
        for k, v in t["round_time_used_s"].items():
            t_all["by_reason"].setdefault(k, []).extend(v)

    ec = pd.concat(econ, ignore_index=True)
    win_rewards = {reason: stats(g[~g["capped"]]["delta"], 0) for reason, g in ec[ec["won"]].groupby(["side", "reason"])}
    win_rewards = {f"{s}_{r}": v for (s, r), v in win_rewards.items()}

    out = {
        "schema_version": SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "generated_at": date.today().isoformat(),
        "game_build": GAME_BUILD,
        "sources": {
            "oficial": "weapons.vdata, gamemode_competitive.cfg e items_game.txt da build 2000930 + cvars do servidor do torneio gravadas nas demos",
            "medido": f"{len(rounds_by_demo)} demos de partidas profissionais, {sum(len(r) for r in rounds_by_demo.values())} rounds",
        },
        "units": {"distance": "unidades Source (1 = 0,0254 m)", "speed": "unidades/s", "time": "segundos",
                  "money": "US$ do jogo", "angles": "graus"},
        "match_config": cfg,
        "equipment_prices": {k: v for k, v in json.loads((REF_DIR / "equipment_prices.json").read_text()).items() if k != "source"},
        "economy": {
            "rules": {
                "start_money": cfg["mp_startmoney"]["value"], "max_money": cfg["mp_maxmoney"]["value"],
                "overtime_start_money": cfg["mp_overtime_startmoney"]["value"],
                "win": {"elimination": cfg["cash_team_elimination_bomb_map"]["value"],
                        "bomb_exploded_T": cfg["cash_team_terrorist_win_bomb"]["value"],
                        "bomb_defused_CT": cfg["cash_team_win_by_defusing_bomb"]["value"],
                        "time_ran_out_CT": cfg["cash_team_win_by_time_running_out_bomb"]["value"]},
                "loss_bonus": {"base": cfg["cash_team_loser_bonus"]["value"],
                               "per_consecutive_loss": cfg["cash_team_loser_bonus_consecutive_rounds"]["value"],
                               "starting_losses": cfg["mp_starting_losses"]["value"],
                               "max": cfg["cash_team_loser_bonus"]["value"] + 4 * cfg["cash_team_loser_bonus_consecutive_rounds"]["value"],
                               "formula": "contador começa em starting_losses a cada metade; derrota: contador+1 (máx 5) e "
                                          "bônus = base + per_consecutive_loss*(contador-1); vitória: contador-2 (mín 0)",
                               "win_decrements_counter_by": {"value": 2, "source": "medido (ver measured.loss_counter_rule_fit)"}},
                "planted_but_lost_T_team": cfg["cash_team_planted_bomb_but_defused"]["value"],
                "ct_bonus_per_t_death": {"value": CT_BONUS_PER_T_DEATH, "source": "medido",
                                         "note": "cada CT recebe +50 por T morto por CT no round (inclui depois do fim do round), "
                                                 "vencendo ou perdendo; não ocorre no último round da partida"},
                "t_survivors_on_time_loss": {"value": 0, "note": "Ts vivos quando o tempo acaba não recebem bônus de derrota"},
                "money_reset": "início de cada metade: start_money; início de cada metade da prorrogação: overtime_start_money",
                "player": {"plant": cfg["cash_player_bomb_planted"]["value"], "defuse": cfg["cash_player_bomb_defused"]["value"],
                           "kill_default": cfg["cash_player_killed_enemy_default"]["value"],
                           "kill_by_weapon": "ver weapons.<arma>.kill_award",
                           "teamkill": cfg["cash_player_killed_teammate"]["value"]},
            },
            "measured": {"win_reward_per_player": win_rewards,
                         "loss_counter_rule_fit": economy_rule_fit(ec, rounds_by_demo, kills_by_demo, cfg)},
        },
        "damage_model": {
            "formula": [
                "dano = damage * range_modifier ^ (distancia_unidades / 500) * multiplicador_parte_do_corpo",
                "cabeça usa weapons.<arma>.headshot_multiplier (4.0 em quase todas); pescoço é ×1.0",
                "colete protege peito, estômago, braços e pescoço; cabeça só com capacete; pernas nunca",
                "se protegido e colete > 0: vida = dano * armor_penetration; colete -= (dano - vida) * 0.5",
                "se o colete não basta: colete zera e vida = dano - colete_antes * 2",
                "valores são truncados para inteiro; fogo amigo multiplica por ff_damage_reduction_*",
            ],
            "penetration_note": "Tiros que atravessam parede, objeto ou jogador perdem dano conforme weapons.<arma>.penetration_power "
                                "e o material; as demos não marcam esses tiros no evento de dano. Os danos abaixo do previsto em "
                                "'validation' são em sua maioria esses casos (medidos em weapon_dynamics.json). O hitgroup 'generic' "
                                "NÃO é tiro de arma: é só dano de fogo (molotov) e de granada (HE).",
            "hitgroup_multipliers": {hg: {"value": (4.0 if hg == "head" else DEFAULT_HG_MULT.get(hg)),
                                          **({"note": "multiplicador da arma (headshot_multiplier)"} if hg == "head" else {}),
                                          **({"note": "o pescoço NÃO é cabeça: ×1,0 e protegido pelo colete (não pelo capacete)"} if hg == "neck" else {}),
                                          "measured": hg_mult.get(hg)} for hg in HITGROUPS},
            "validation": damage_fit,
        },
        "movement": {
            "max_speed_by_weapon": "weapons.<arma>.max_speed (normal; alt = com mira)",
            "knife_speed": weapons.get("knife", {}).get("max_speed", {}).get("normal"),
            "measured": ratios,
            "note": "andar (shift) = 0,52 × velocidade máxima da arma (exato em todas as amostras). Agachado: usar ~0,34–0,36 "
                    "(mediana medida); percentis altos são a desaceleração logo após agachar correndo",
        },
        "bomb": {
            "timer_s": {"value": stats(bomb_all["timer_s"])["median"] if bomb_all["timer_s"] else None, "measured": stats(bomb_all["timer_s"])},
            "plant_duration_s": {"measured": stats(bomb_all["plant_s"])},
            "defuse_duration_s": {"with_kit": stats(bomb_all["with_kit"]), "without_kit": stats(bomb_all["without_kit"])},
        },
        "utility": {
            "limits": {"total": cfg["ammo_grenade_limit_total"]["value"], "flashbang": cfg["ammo_grenade_limit_flashbang"]["value"]},
            "smoke_duration_s": stats(u["smoke"]),
            "molotov_burn_duration_s": stats(u["molotov"]),
            "time_to_detonate_s": {**{k: stats(v) for k, v in u["fuse"].items()},
                                   "note": "HE e flash têm pavio fixo; smoke detona quando para de se mover; "
                                           "molotov/incendiária detonam ao tocar o chão"},
            "flash_blind_duration_s": stats(u["flash"]),
            "he_damage": {"health": stats(he["dmg_health"]) if len(he) else None, "armor": stats(he["dmg_armor"]) if len(he) else None},
            "molotov_damage_per_event": stats(u["molotov_dmg"]),
        },
        "round_timing": {
            "freeze_time_s": {"official": cfg["mp_freezetime"]["value"], "measured": stats(t_all["freeze_s"])},
            "round_time_s": {"official": round(cfg["mp_roundtime_defuse"]["value"] * 60, 1),
                             "measured_time_ran_out": stats(t_all["by_reason"].get("time_ran_out", []))},
            "restart_delay_s": {"official": cfg["mp_round_restart_delay"]["value"], "measured": stats(t_all["restart_delay_s"])},
            "duration_by_end_reason_s": {k: stats(v) for k, v in t_all["by_reason"].items()},
        },
        "weapons": dict(sorted(weapons.items())),
        "weapon_display_names": dict(sorted(names.items())),
        "weapon_classes": dict(sorted(WEAPON_CLASS.items())),
    }
    path = OUT / "game_rules.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print(f"\n{path} ({path.stat().st_size // 1024} KB): {len(weapons)} armas/itens")
    print("Validação do dano:", json.dumps(damage_fit["vida"]))
    print("Multiplicadores (melhor ajuste):", {k: (v["best_fit"], v["exact_match_rate"], v["n"]) for k, v in hg_mult.items()})
    print("Por arma:", json.dumps(damage_fit["por_arma"]))
    print("Regra do contador de derrotas:", out["economy"]["measured"]["loss_counter_rule_fit"])
    print("Bomba:", out["bomb"])


if __name__ == "__main__":
    main()
