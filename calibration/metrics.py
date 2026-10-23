"""Métricas de calibração: o que a simulação precisa reproduzir do jogo real.

`compute_metrics(tables)` recebe as tabelas de calibration.simlog e devolve {id: métrica}.
Os ids são hierárquicos (`round.win_rate.CT`, `combat.accuracy.rifle.10-20m`); métricas por mapa
têm o sufixo `@de_mirage`. Três tipos de métrica:

  prop       {"k","n","value"}              proporções (taxa de acerto, vitórias...)
  mean       {"mean","std","n"}             médias de contagens por round
  quantiles  {"q": {"p5".."p95"},"mean","n"} distribuições contínuas (tempos, distâncias, ângulos)
"""
import json

import numpy as np
import pandas as pd

from pipeline.combat import is_combat_shot
from pipeline.common import ARTIFACTS_DIR, BUY_TYPES, PISTOL_ROUNDS, buy_type

QUANTILES = [5, 10, 25, 50, 75, 90, 95]
REASONS = ["t_killed", "ct_killed", "bomb_exploded", "bomb_defused", "time_ran_out"]
ACC_CLASSES = ["rifle", "awp", "pistol", "smg"]
BAND_CLASSES = ["rifle", "pistol", "smg"]
AUTOMATIC = ["rifle", "smg", "heavy"]
BANDS = [(0, 10, "0-10m"), (10, 20, "10-20m"), (20, 30, "20-30m"), (30, 1e9, "30m+")]
STILL_SPEED = 40.0
MIN_MAP_ROUNDS = 30     # só gera métricas por mapa com pelo menos este número de rounds
KEY = ["match", "round"]
POSITION_HZ = 2              # igual a calibration.simlog.POSITION_HZ
TACTIC_TIMES = (20, 40, 60)  # instantes do round (s) em que se mede a ocupação por zona
ZONES = ("A", "B", "Mid", "Spawn")


# ---------- construtores de métrica ----------

def prop(k, n):
    k, n = int(k), int(n)
    return {"kind": "prop", "k": k, "n": n, "value": (k / n) if n else None}


def mean(x):
    x = pd.Series(x, dtype=float).dropna()
    if x.empty:
        return None
    return {"kind": "mean", "mean": float(x.mean()), "std": float(x.std(ddof=1)) if len(x) > 1 else 0.0, "n": int(len(x))}


def quant(x):
    arr = np.asarray(pd.Series(x, dtype=float).dropna())
    if arr.size == 0:
        return None
    return {"kind": "quantiles", "q": {f"p{q}": float(np.percentile(arr, q)) for q in QUANTILES},
            "mean": float(arr.mean()), "n": int(arr.size), "_samples": arr}


def _add(m, key, metric):
    if metric is not None:
        m[key] = metric


# ---------- rounds ----------

def round_frame(t):
    r = t["rounds"].copy()
    bombs, kills = t["bombs"], t["kills"]

    planted = (bombs[(bombs["event"] == "planted") & ~bombs["after_round_end"]]
               .sort_values("tick").drop_duplicates(KEY)[KEY + ["round_time", "site"]]
               .rename(columns={"round_time": "plant_time_s", "site": "plant_site"}))
    r = r.merge(planted, on=KEY, how="left")
    r["planted"] = r["plant_time_s"].notna()

    valid = kills[~kills["after_round_end"] & kills["attacker_steamid"].notna()
                  & (kills["attacker_side"] != kills["user_side"])]
    r = r.merge(valid.groupby(KEY).size().rename("kills").reset_index(), on=KEY, how="left")
    r["kills"] = r["kills"].fillna(0)
    first = (valid.sort_values("tick").drop_duplicates(KEY)[KEY + ["round_time", "attacker_side"]]
             .rename(columns={"round_time": "first_kill_time_s", "attacker_side": "first_kill_side"}))
    r = r.merge(first, on=KEY, how="left")

    buys = team_buys(t)
    for side in ("CT", "T"):
        b = buys[buys["side"] == side][KEY + ["buy"]].rename(columns={"buy": f"{side.lower()}_buy"})
        r = r.merge(b, on=KEY, how="left")
    return r


def team_buys(t):
    g = t["players"].groupby(KEY + ["side"]).agg(avg_equip=("equip_value", "mean")).reset_index()
    g["buy"] = [buy_type(rn, a) for rn, a in zip(g["round"], g["avg_equip"])]
    return g


def round_metrics(r, tag=""):
    m = {}
    n = len(r)
    if n == 0:
        return m
    s = f"@{tag}" if tag else ""
    m[f"round.win_rate.CT{s}"] = prop((r["winner_side"] == "CT").sum(), n)
    for reason in REASONS:
        m[f"round.end_reason.{reason}{s}"] = prop((r["reason"] == reason).sum(), n)
        _add(m, f"round.duration_s.{reason}{s}", quant(r.loc[r["reason"] == reason, "duration_s"]))
    _add(m, f"round.duration_s.all{s}", quant(r["duration_s"]))

    m[f"round.plant_rate{s}"] = prop(r["planted"].sum(), n)
    pl = r[r["planted"]]
    _add(m, f"round.plant_time_s{s}", quant(pl["plant_time_s"]))
    if tag:  # a divisão entre bombsites só faz sentido por mapa
        m[f"round.plant_site.A{s}"] = prop((pl["plant_site"] == "A").sum(), pl["plant_site"].isin(["A", "B"]).sum())
    m[f"round.defuse_given_plant{s}"] = prop((pl["reason"] == "bomb_defused").sum(), len(pl))

    _add(m, f"round.kills_per_round{s}", mean(r["kills"]))
    _add(m, f"round.first_kill_time_s{s}", quant(r["first_kill_time_s"]))
    fk = r[r["first_kill_side"].notna()]
    m[f"round.first_kill_wins_round{s}"] = prop((fk["first_kill_side"] == fk["winner_side"]).sum(), len(fk))
    m[f"round.first_kill_ct_share{s}"] = prop((fk["first_kill_side"] == "CT").sum(), len(fk))

    if not tag:  # vitória do CT por combinação de compras (a relação economia -> resultado)
        for cb in BUY_TYPES:
            for tb in BUY_TYPES:
                g = r[(r["ct_buy"] == cb) & (r["t_buy"] == tb)]
                if len(g):
                    m[f"econ.ct_win_rate.{cb}_vs_{tb}"] = prop((g["winner_side"] == "CT").sum(), len(g))
    return m


# ---------- combate ----------

def _band(series):
    out = pd.Series(None, index=series.index, dtype=object)
    for lo, hi, name in BANDS:
        out[(series >= lo) & (series < hi)] = name
    return out


def combat_metrics(t):
    m = {}
    shots = t["shots"][t["shots"]["wclass"].notna()]
    if shots["aim_err_deg"].notna().any():
        cs = shots[is_combat_shot(shots)]
        for wc in ACC_CLASSES:
            g = cs[cs["wclass"] == wc]
            m[f"combat.accuracy.{wc}"] = prop(g["hit"].sum(), len(g))
            if wc in BAND_CLASSES and g["distance_m"].notna().any():
                band = _band(g["distance_m"])
                for _, _, name in BANDS:
                    gb = g[band == name]
                    m[f"combat.accuracy.{wc}.{name}"] = prop(gb["hit"].sum(), len(gb))
        _add(m, "combat.aim_error_first_bullet_deg", quant(cs.loc[cs["spray_index"] <= 1, "aim_err_deg"]))
        if cs["speed"].notna().any():
            m["combat.still_shot_rate"] = prop((cs["speed"] < STILL_SPEED).sum(), cs["speed"].notna().sum())
        if cs["ducking"].notna().any():
            m["combat.crouch_shot_rate"] = prop(cs["ducking"].fillna(False).astype(bool).sum(), len(cs))

    auto = shots[shots["wclass"].isin(AUTOMATIC) & shots["spray_index"].notna()].sort_values(["match", "shooter", "tick"])
    if len(auto):
        new_burst = (auto["spray_index"] <= 1) | (auto.groupby(["match", "shooter"])["spray_index"].diff() <= 0)
        burst = auto.groupby([auto["match"], auto["shooter"], new_burst.cumsum()])["spray_index"].max()
        _add(m, "combat.burst_length", quant(burst))

    kills = t["kills"]
    kills = kills[~kills["after_round_end"] & kills["attacker_steamid"].notna() & kills["wclass"].notna()
                  & (kills["attacker_side"] != kills["user_side"])]
    for wc in ACC_CLASSES:
        g = kills[kills["wclass"] == wc]
        m[f"combat.headshot_kill_rate.{wc}"] = prop(g["headshot"].sum(), len(g))
        _add(m, f"combat.kill_distance_m.{wc}", quant(g["distance_m"]))

    dmg = t["damages"]
    enemy = dmg[~dmg["after_round_end"] & dmg["attacker_steamid"].notna() & (dmg["attacker_side"] != dmg["user_side"])]
    located = enemy[enemy["wclass"].notna() & (enemy["hitgroup"] != "generic")]
    for wc in ACC_CLASSES:
        g = located[located["wclass"] == wc]
        m[f"combat.head_hit_share.{wc}"] = prop((g["hitgroup"] == "head").sum(), len(g))

    # ADR: dano por round por jogador (cada vítima conta no máximo 100)
    per_victim = enemy.groupby(KEY + ["attacker_steamid", "user_steamid"])["dmg_health"].sum().clip(upper=100)
    per_att = per_victim.groupby(level=[0, 1, 2]).sum().rename("dmg").reset_index().rename(columns={"attacker_steamid": "player"})
    pr = t["players"][KEY + ["player"]].merge(per_att, on=KEY + ["player"], how="left").fillna({"dmg": 0})
    _add(m, "combat.adr", mean(pr["dmg"]))
    return m


def duel_metrics(t):
    m = {}
    sg = t["sightings"]
    if sg is None or sg.empty or "reaction_s" not in sg:
        return m
    resolved = sg[sg["outcome"] != "none"]
    m["duel.win_rate"] = prop((resolved["outcome"] == "win").sum(), len(resolved))
    if resolved["distance_m"].notna().any():
        band = _band(resolved["distance_m"])
        for _, _, name in BANDS:
            g = resolved[band == name]
            m[f"duel.win_rate.{name}"] = prop((g["outcome"] == "win").sum(), len(g))
    m["duel.shoots_after_sighting"] = prop(sg["reaction_s"].notna().sum(), len(sg))
    _add(m, "duel.reaction_time_s", quant(sg["reaction_s"]))
    _add(m, "duel.crosshair_placement_deg", quant(sg["aim_err_deg"]))
    return m


# ---------- compras ----------

def buy_metrics(t):
    m = {}
    p = t["players"]
    buys = team_buys(t)
    for side in ("CT", "T"):
        b = buys[buys["side"] == side]
        for bt in BUY_TYPES:
            m[f"buy.type.{side}.{bt}"] = prop((b["buy"] == bt).sum(), len(b))

    full = p[~p["round"].isin(PISTOL_ROUNDS)]
    for side in ("CT", "T"):
        g = full[full["side"] == side]
        m[f"buy.armor_rate.{side}"] = prop((g["armor"] > 0).sum(), len(g))
        m[f"buy.helmet_rate.{side}"] = prop(g["helmet"].astype(bool).sum(), len(g))
    ct = full[full["side"] == "CT"]
    m["buy.kit_rate.CT"] = prop(ct["defuser"].astype(bool).sum(), len(ct))
    if "primary" in full:
        awps = full.assign(awp=(full["primary"] == "awp").astype(int)).groupby(KEY + ["side"])["awp"].sum().reset_index()
        for side in ("CT", "T"):
            _add(m, f"buy.awp_per_team.{side}", mean(awps.loc[awps["side"] == side, "awp"]))
    for kind in ("smoke", "flash", "he", "molotov"):
        if f"g_{kind}" in full:
            _add(m, f"buy.grenades_per_player.{kind}", mean(full[f"g_{kind}"]))
    return m


# ---------- tática ----------

def load_zones():
    """{mapa: {região: zona}} do tactics.json; vazio se o arquivo não existir (as métricas de zona são então puladas)."""
    path = ARTIFACTS_DIR / "tactics.json"
    if not path.exists():
        return {}
    doc = json.loads(path.read_text())
    return {mp: {pl: info["zone"] for pl, info in m["places"].items()} for mp, m in doc["maps"].items()}


def zone_share_metrics(pos, zones_wanted, suffix=""):
    m = {}
    for side in ("CT", "T"):
        ps = pos[pos["side"] == side]
        for tp in TACTIC_TIMES:
            g = ps[ps["k"] == tp * POSITION_HZ]
            if g.empty:
                continue
            share = g.groupby(KEY)["zone"].value_counts(normalize=True).unstack(fill_value=0)
            for z in zones_wanted:
                _add(m, f"tactic.zone_share.{side}.{tp}s.{z}{suffix}", mean(share[z] if z in share else pd.Series(0.0, index=share.index)))
    return m


def tactic_metrics(t, zones, r=None):
    m = {}
    dmg = t["damages"]
    contact = dmg[~dmg["after_round_end"] & dmg["attacker_steamid"].notna() & (dmg["attacker_side"] != dmg["user_side"])]
    _add(m, "tactic.first_contact_s", quant(contact.groupby(KEY)["round_time"].min()))

    pos = t.get("positions")
    if pos is None or pos.empty or not zones:
        return m
    pos = pos.copy()
    pos["zone"] = [zones.get(mp, {}).get(pl, "Mid") for mp, pl in zip(pos["map"], pos["place"])]
    m.update(zone_share_metrics(pos, ZONES))
    rounds_by_map = pos.groupby("map")[KEY].apply(lambda d: len(d.drop_duplicates()))
    for mp in sorted(rounds_by_map.index):
        if rounds_by_map[mp] >= MIN_MAP_ROUNDS:
            m.update(zone_share_metrics(pos[pos["map"] == mp], ("A", "B"), f"@{mp}"))

    # Compromisso e troca de bombsite: o time está "comprometido" com a zona (A ou B) onde há mais Ts aos 30 s
    if r is not None:
        c30 = pos[(pos["side"] == "T") & (pos["k"] == 30 * POSITION_HZ)].groupby(KEY + ["zone"]).size().unstack(fill_value=0)
        for z in ("A", "B"):
            if z not in c30:
                c30[z] = 0
        c30["commit"] = np.where(c30.A > c30.B, "A", np.where(c30.B > c30.A, "B", ""))
        j = c30[c30.commit != ""].join(r.set_index(KEY)[["planted", "plant_site", "plant_time_s"]], how="inner")
        j = j[j.planted & j.plant_site.isin(["A", "B"]) & (j.plant_time_s > 30)]
        m["tactic.site_switch_rate"] = prop((j.commit != j.plant_site).sum(), len(j))
        m["tactic.commit_A_share"] = prop((j.commit == "A").sum(), len(j))

    # Movimento: trocas de região por jogador e tempo de permanência (amostras consecutivas a POSITION_HZ)
    pos = pos.sort_values(KEY + ["player", "k"])
    g = pos.groupby(KEY + ["player"])
    consecutive = g["k"].diff() == 1
    changed = (pos["place"] != g["place"].shift()) & consecutive
    _add(m, "tactic.place_changes_per_player", mean(changed.groupby([pos["match"], pos["round"], pos["player"]]).sum()))
    new_run = ~consecutive | (pos["place"] != g["place"].shift())
    run_id = new_run.groupby([pos["match"], pos["round"], pos["player"]]).cumsum()
    dwell = pos.groupby(KEY + ["player", run_id]).size() / POSITION_HZ
    _add(m, "tactic.dwell_s", quant(dwell))
    return m


# ---------- ponto de entrada ----------

def compute_metrics(t, zones=None):
    zones = load_zones() if zones is None else zones
    r = round_frame(t)
    m = round_metrics(r)
    for mp in sorted(r["map"].unique()):
        sub = r[r["map"] == mp]
        if len(sub) >= MIN_MAP_ROUNDS:
            m.update(round_metrics(sub, mp))
    m.update(combat_metrics(t))
    m.update(duel_metrics(t))
    m.update(buy_metrics(t))
    m.update(tactic_metrics(t, zones, r))
    return m


def serializable(metrics):
    """Remove as amostras brutas (só ficam em memória) para gravar em JSON."""
    return {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in metrics.items()}


DESCRIPTIONS = {
    "round.win_rate.CT": "Fração de rounds vencidos pelo CT.",
    "round.end_reason": "Fração de rounds que terminam por este motivo.",
    "round.duration_s": "Duração do round (do fim do freeze time até o fim), em segundos.",
    "round.plant_rate": "Fração de rounds em que a bomba é plantada.",
    "round.plant_time_s": "Tempo de round em que a bomba é plantada.",
    "round.plant_site.A": "Entre os plants, fração no bombsite A.",
    "round.defuse_given_plant": "Entre os rounds com plant, fração que termina em defuse.",
    "round.kills_per_round": "Kills em combate por round.",
    "round.first_kill_time_s": "Tempo do primeiro kill do round.",
    "round.first_kill_wins_round": "Fração de rounds vencidos por quem fez o primeiro kill.",
    "round.first_kill_ct_share": "Fração dos primeiros kills feitos pelo CT.",
    "econ.ct_win_rate": "Vitória do CT conforme o tipo de compra de cada lado.",
    "combat.accuracy": "Taxa de acerto em tiros de combate (mira a menos de 10° de um inimigo, ou que acertaram).",
    "combat.aim_error_first_bullet_deg": "Erro de mira da primeira bala, em graus.",
    "combat.still_shot_rate": "Fração dos tiros dados parado (velocidade < 40).",
    "combat.crouch_shot_rate": "Fração dos tiros dados agachado.",
    "combat.burst_length": "Balas por sequência com armas automáticas.",
    "combat.headshot_kill_rate": "Fração dos kills que são headshot.",
    "combat.kill_distance_m": "Distância dos kills, em metros.",
    "combat.head_hit_share": "Fração dos acertos (com parte do corpo definida) que pegam a cabeça.",
    "combat.adr": "Dano médio por round por jogador (cada vítima conta no máximo 100).",
    "duel.win_rate": "Quando um jogador vê um inimigo e alguém morre em até 3 s, fração de vezes em que ele vence.",
    "duel.shoots_after_sighting": "Fração dos avistamentos em que o jogador atira em até 2 s.",
    "duel.reaction_time_s": "Tempo entre ver o inimigo e o primeiro tiro mirado nele.",
    "duel.crosshair_placement_deg": "Erro de mira (graus) no instante em que o inimigo aparece.",
    "tactic.zone_share": "Fração dos jogadores vivos do lado que estão em cada zona do mapa (A, B, Mid, Spawn) naquele instante do round.",
    "tactic.site_switch_rate": "Entre os rounds com plant depois de 30 s, fração em que o time plantou no bombsite oposto à zona onde havia mais Ts aos 30 s.",
    "tactic.commit_A_share": "Entre os mesmos rounds, fração em que o time estava comprometido com a zona A aos 30 s.",
    "tactic.first_contact_s": "Tempo do primeiro dano entre lados opostos no round.",
    "tactic.place_changes_per_player": "Trocas de região por jogador por round (amostras a 2 Hz).",
    "tactic.dwell_s": "Tempo contínuo que um jogador fica numa mesma região (amostras a 2 Hz).",
    "buy.type": "Fração dos rounds de cada lado por tipo de compra.",
    "buy.armor_rate": "Fração dos jogadores com colete (rounds sem pistola).",
    "buy.helmet_rate": "Fração dos jogadores com capacete (rounds sem pistola).",
    "buy.kit_rate": "Fração dos CTs com kit de defuse (rounds sem pistola).",
    "buy.awp_per_team": "AWPs por time por round (rounds sem pistola).",
    "buy.grenades_per_player": "Granadas por jogador no fim do freeze time (rounds sem pistola).",
}


def describe(metric_id):
    base = metric_id.split("@")[0]
    parts = base.split(".")
    for i in range(len(parts), 0, -1):
        key = ".".join(parts[:i])
        if key in DESCRIPTIONS:
            return DESCRIPTIONS[key]
    return ""
