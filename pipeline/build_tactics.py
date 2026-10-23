"""Treina a camada tática no nível de regiões (callouts): contract/artifacts/tactics.json e tactics_playbook.json.

tactics.json, por mapa:
  places        as regiões (centro, tamanho, quem as usa, zona do mapa)
  graph         para onde os jogadores vão depois de cada região e quanto ficam nela
  occupancy     onde cada lado costuma estar a cada 5 s do round
  forecast      onde um jogador estará daqui a 5 s e 10 s, dada a região atual (o modelo mais forte: +35% a +58% sobre a ocupação)
  post_plant    o que o CT faz depois do plant
  rotation      como o CT reage ao primeiro contato
  engagements   onde acontecem o primeiro contato e os kills
  utility       onde cada lado joga cada granada
  evaluation    validação em partidas que o modelo não viu

tactics_playbook.json: as rotas de todos os rounds reais (uma região por passo), para a simulação sortear um round
real e reproduzi-lo. Tentamos agrupar os rounds em "planos" (k-means), mas eles não previram o bombsite do plant
com os 40 s iniciais de partidas inéditas e não melhoraram a previsão de posição, então não fazem parte do contrato.

Só usa o nome da região (last_place_name), então funciona sem a geometria 3D.

Uso: .venv/bin/python -m pipeline.build_tactics
"""
import hashlib
import json
from datetime import date

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from calibration.metrics import KEY
from contract.reference import tactics as ref
from pipeline.common import ARTIFACTS_DIR, BUY_TYPES, CONTRACT_VERSION, DATA_DIR, UNIT_TO_M, VECTORS_DIR
from pipeline import site_decision as sdec
from pipeline.tactics_data import SAMPLE_HZ, load_positions, load_rounds, runs

BUCKET_S = 5
MAX_T = 120
OCC_PRIOR = 20          # força do prior (marginal do lado) na ocupação por tempo
MIN_EDGE_N = 3
ZONE_HI = 0.65          # região é da zona A se em >= 65% das vezes o jogador visita o bombsite A em seguida (B se <= 35%)
ZONE_MIN_N = 30         # permanências mínimas para estimar o fluxo
ROTATION_DELTA_S = 15
UTIL_KINDS = ["smoke", "flash", "he", "molotov"]


def r(x, nd=4):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def quant(x, qs=(25, 50, 75)):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    return {f"p{q}": r(np.percentile(x, q), 2) for q in qs} if len(x) else None


# ---------- regiões e zonas ----------

def kind_of(name):
    return "spawn" if name.endswith("Spawn") else "site" if name.startswith("Bombsite") else "area"


def site_flow(runs_m, side):
    """Para cada região: fração das vezes em que o jogador, depois dela, visitou primeiro o bombsite A (e não o B)."""
    r_ = runs_m[runs_m.side == side].sort_values(KEY + ["steamid", "run"]).copy()
    r_["site"] = r_.place.where(r_.place.isin(["BombsiteA", "BombsiteB"]))
    r_["next_site"] = r_.groupby(KEY + ["steamid"])["site"].transform(lambda s: s.shift(-1).bfill())
    return r_.dropna(subset=["next_site"]).groupby("place").next_site.agg(n="size", pA=lambda s: (s == "BombsiteA").mean())


def assign_zones(info, runs_m):
    """Zona = para qual bombsite a região leva. Usa o fluxo dos atacantes (T); onde o T quase não passa, o do CT."""
    flows = {"T": site_flow(runs_m, "T"), "CT": site_flow(runs_m, "CT")}
    for place, i in info.items():
        if i["kind"] == "spawn":
            i["zone"], i["pa"] = "Spawn", None
        elif i["kind"] == "site":
            i["zone"], i["pa"] = place[-1], 1.0 if place.endswith("A") else 0.0
        else:
            i["zone"], i["pa"] = "Mid", None
            for side in ("T", "CT"):
                f = flows[side]
                if place in f.index and f.loc[place, "n"] >= ZONE_MIN_N:
                    pa = float(f.loc[place, "pA"])
                    i["pa"], i["zone"] = r(pa, 2), "A" if pa >= ZONE_HI else "B" if pa <= 1 - ZONE_HI else "Mid"
                    break
    return info


def build_places(Pm, runs_m):
    out = {}
    side_share = Pm.groupby(["place", "side"]).size().unstack(fill_value=0)
    for place, g in Pm.groupby("place"):
        out[place] = {
            "kind": kind_of(place), "n": int(len(g)),
            "centroid_m": [r(g.x.mean(), 2), r(g.y.mean(), 2), r(g.z.mean(), 2)],
            "spread_m": [r(g.x.std(), 2), r(g.y.std(), 2)],
            "bbox_m": [[r(g.x.quantile(.05), 2), r(g.y.quantile(.05), 2)], [r(g.x.quantile(.95), 2), r(g.y.quantile(.95), 2)]],
            "side_share": {s: r(side_share.loc[place].get(s, 0) / side_share.loc[place].sum(), 3) for s in ("CT", "T")},
        }
    return assign_zones(out, runs_m)


def build_graph(runs_m):
    runs_m = runs_m.sort_values(KEY + ["steamid", "run"])
    runs_m["next_place"] = runs_m.groupby(KEY + ["steamid"])["place"].shift(-1)
    graph = {}
    for place, g in runs_m.groupby("place"):
        nxt = g.dropna(subset=["next_place"])
        e = nxt.groupby("next_place").agg(n=("dwell_s", "size"), dwell=("dwell_s", "median")).reset_index()
        e = e[(e.n >= MIN_EDGE_N) & (e.next_place != place)]
        total = e.n.sum()
        graph[place] = {
            "dwell_s": quant(g.dwell_s),
            "edges": [{"to": row.next_place, "n": int(row.n), "p": r(row.n / total, 4), "dwell_s": r(row.dwell, 2)}
                      for row in e.sort_values("n", ascending=False).itertuples()] if total else [],
        }
    return graph


def build_occupancy(Pm, places):
    out = {}
    for side in ("CT", "T"):
        S = Pm[Pm.side == side].copy()
        S["b"] = (S.t // BUCKET_S).clip(upper=MAX_T // BUCKET_S).astype(int)
        marg = S.place.value_counts(normalize=True)
        buckets = []
        for b, g in S.groupby("b"):
            c = g.place.value_counts().reindex(marg.index).fillna(0)
            p = (c + OCC_PRIOR * marg) / (c.sum() + OCC_PRIOR)
            p = p[p >= 0.005]
            p = p / p.sum()
            buckets.append({"t": int(b * BUCKET_S), "p": {k: r(v, 4) for k, v in p.sort_values(ascending=False).items()}})
        out[side] = {"bucket_s": BUCKET_S, "buckets": buckets}
    return out


# ---------- pós-plant, rotação, contato ----------

def build_post_plant(Pm, Rm):
    out = {}
    CT = Pm[Pm.side == "CT"]
    for site in ("A", "B"):
        rows = Rm[Rm.planted & (Rm.plant_site == site)]
        recs = []
        for row in rows.itertuples():
            ct = CT[(CT.match == row.match) & (CT["round"] == row._asdict()["round"]) & (CT.t >= row.plant_time_s)]
            at_plant = CT[(CT.match == row.match) & (CT["round"] == row._asdict()["round"]) & (CT.t >= row.plant_time_s - 0.01) & (CT.t < row.plant_time_s + 0.2)]
            alive = int(at_plant.steamid.nunique())
            in_site = ct[ct.place == f"Bombsite{site}"]
            arrive = float(in_site.t.min() - row.plant_time_s) if len(in_site) else np.nan
            recs.append({"alive_ct": alive, "arrive_s": arrive, "defused": row.reason == "bomb_defused"})
        if not recs:
            continue
        d = pd.DataFrame(recs)
        by_alive = {str(k): {"n": int(len(g)), "ct_reach_rate": r(g.arrive_s.notna().mean(), 3), "defuse_rate": r(g.defused.mean(), 3)}
                    for k, g in d.groupby("alive_ct") if k >= 1}
        out[site] = {"n": int(len(d)), "defuse_rate": r(d.defused.mean(), 3), "ct_reach_rate": r(d.arrive_s.notna().mean(), 3),
                     "first_ct_arrival_s": quant(d.arrive_s), "by_alive_ct": by_alive}
    return out


def first_contacts(dm):
    """Primeiro dano entre lados opostos em cada round, com as regiões de quem atacou e de quem apanhou."""
    d = dm[(~dm.after_round_end) & dm.attacker_steamid.notna() & (dm.attacker_side != dm.user_side)]
    d = d.sort_values("tick").drop_duplicates(KEY)
    d["t_place"] = np.where(d.attacker_side == "T", d.attacker_last_place_name, d.user_last_place_name)
    d["ct_place"] = np.where(d.attacker_side == "CT", d.attacker_last_place_name, d.user_last_place_name)
    return d


def build_rotation(Pm, dm, places_info):
    zone = {p: i["zone"] for p, i in places_info.items()}
    fc = first_contacts(dm)
    CT = Pm[Pm.side == "CT"].copy()
    CT["k"] = (CT.t * SAMPLE_HZ).round().astype(int)
    idx = CT.set_index(KEY + ["steamid", "k"]).place
    rows = []
    for c in fc.itertuples():
        kc = int(round(c.round_time * SAMPLE_HZ))
        zc = zone.get(c.t_place)
        if zc is None or zc in ("Spawn",):
            continue
        alive = CT[(CT.match == c.match) & (CT["round"] == c._asdict()["round"]) & (CT.k == kc)]
        for sid in alive.steamid:
            if sid in (c.attacker_steamid, c.user_steamid):
                continue
            key = (c.match, c._asdict()["round"], sid)
            p0 = idx.get(key + (kc,))
            p1 = idx.get(key + (kc + ROTATION_DELTA_S * SAMPLE_HZ,))
            if p0 is None:
                continue
            first_in = CT[(CT.match == c.match) & (CT["round"] == c._asdict()["round"]) & (CT.steamid == sid) & (CT.k > kc)
                          & (CT.place.map(zone) == zc)]
            rows.append({"contact_zone": zc, "own_zone": zone.get(p0), "alive_after": p1 is not None,
                         "zone_after": zone.get(p1) if p1 is not None else None,
                         "arrive_s": (first_in.k.min() - kc) / SAMPLE_HZ if len(first_in) else np.nan})
    if not rows:
        return {}
    d = pd.DataFrame(rows)
    out = {}
    for zc, g in d.groupby("contact_zone"):
        out[zc] = {}
        for z0, gg in g.groupby("own_zone"):
            s = gg[gg.alive_after]
            if len(s) < 5:
                continue
            out[zc][z0] = {"n": int(len(s)), "to_contact_zone": r((s.zone_after == zc).mean(), 3), "stay": r((s.zone_after == z0).mean(), 3) if z0 != zc else None,
                           "arrive_s": quant(gg.arrive_s)}
    return {"delta_s": ROTATION_DELTA_S, "by_contact_zone": out,
            "note": "Para cada CT que não participou do primeiro dano: onde estava (own_zone) e onde estava 15 s depois, conforme a zona do contato."}


def build_engagements(dm, km_):
    fc = first_contacts(dm)
    out = {"first_contact": {
        "t_place": {k: r(v, 3) for k, v in fc.t_place.value_counts(normalize=True).head(12).items()},
        "ct_place": {k: r(v, 3) for k, v in fc.ct_place.value_counts(normalize=True).head(12).items()},
        "time_s": quant(fc.round_time), "n": int(len(fc))}}
    k = km_[(~km_.after_round_end) & km_.attacker_steamid.notna() & (km_.attacker_side != km_.user_side)]
    g = k.groupby(["attacker_side", "attacker_last_place_name", "user_last_place_name"]).agg(
        n=("tick", "size"), dist=("distance", "median")).reset_index()
    g = g[g.n >= 3].sort_values("n", ascending=False).head(60)
    out["pairs"] = [{"attacker_side": row.attacker_side, "attacker_place": row.attacker_last_place_name, "victim_place": row.user_last_place_name,
                     "n": int(row.n), "median_distance_m": r(row.dist, 1)} for row in g.itertuples()]
    return out


# ---------- utilitários ----------

def build_utility(Pm, gm, n_rounds_by_side):
    tree_pts = Pm[["x", "y", "z"]].to_numpy().copy()
    tree_pts[:, 2] *= 3.0                                  # a altura pesa mais (andares diferentes)
    tree, labels = cKDTree(tree_pts), Pm.place.to_numpy()
    g = gm[~gm.after_round_end].copy()
    pts = np.c_[g.x.to_numpy() * UNIT_TO_M, g.y.to_numpy() * UNIT_TO_M, g.z.to_numpy() * UNIT_TO_M * 3.0]
    _, nn = tree.query(pts, k=7)
    g["place"] = [pd.Series(labels[i]).mode().iloc[0] for i in nn]
    out = {}
    for side in ("CT", "T"):
        out[side] = {}
        for kind in UTIL_KINDS:
            s = g[(g.user_side == side) & (g.grenade == kind)]
            if s.empty:
                continue
            out[side][kind] = {"per_round": r(len(s) / n_rounds_by_side[side], 3), "time_s": quant(s.round_time),
                               "targets": {k: r(v, 3) for k, v in s.place.value_counts(normalize=True).head(10).items()}}
    return out


# ---------- previsão de posição ----------

HORIZONS_S = (5, 10)
FORECAST_PRIOR = 10
FORECAST_MIN_P = 0.01


def place_pairs(Pm, h):
    """Pares (região agora, região h segundos depois) do mesmo jogador, enquanto vivo nos dois instantes."""
    A = Pm[KEY + ["steamid", "side", "t", "place"]].copy()
    A["k"] = (A.t * SAMPLE_HZ).round().astype(int)
    B = A[KEY + ["steamid", "k", "place"]].rename(columns={"place": "place1"})
    B["k"] = B.k - h * SAMPLE_HZ
    return A.merge(B, on=KEY + ["steamid", "k"])


def build_forecast(Pm, places):
    pidx = {p: i for i, p in enumerate(sorted(places))}
    names = sorted(places)
    n = len(names)
    out = {}
    for side in ("CT", "T"):
        out[side] = {}
        for h in HORIZONS_S:
            M = place_pairs(Pm[Pm.side == side], h)
            i0, i1 = M.place.map(pidx).to_numpy(), M.place1.map(pidx).to_numpy()
            marg = np.bincount(i1, minlength=n) + 1e-9
            marg = marg / marg.sum()
            C = np.zeros((n, n))
            np.add.at(C, (i0, i1), 1)
            T = (C + FORECAST_PRIOR * marg) / (C.sum(1, keepdims=True) + FORECAST_PRIOR)
            entry = {}
            for i, name in enumerate(names):
                row = T[i]
                keep = row >= FORECAST_MIN_P
                row = np.where(keep, row, 0)
                row = row / row.sum()
                entry[name] = {"n": int(C[i].sum()), "p": {names[j]: r(row[j], 4) for j in np.argsort(-row) if row[j] > 0}}
            out[side][f"{h}s"] = entry
    return out


def evaluate_forecast(Pm, n_folds=4):
    """Log-verossimilhança de prever a região futura em partidas que o modelo não viu (menor = melhor)."""
    matches = sorted(Pm.match.unique())
    n_folds = min(n_folds, len(matches))
    if n_folds < 3:
        return None
    names = sorted(set(Pm.place))
    pidx = {p: i for i, p in enumerate(names)}
    n = len(names)
    res = {}
    for h in HORIZONS_S:
        M = place_pairs(Pm, h)
        M = M[(M.t * SAMPLE_HZ).round().astype(int) % SAMPLE_HZ == 0]            # 1 Hz, reduz a correlação
        M["i0"], M["i1"] = M.place.map(pidx), M.place1.map(pidx)
        occ_l, fc_l = [], []
        for f in range(n_folds):
            test = M.match.isin(set(matches[f::n_folds]))
            for side in ("CT", "T"):
                a, b = M[~test & (M.side == side)], M[test & (M.side == side)]
                marg = np.bincount(a.i1, minlength=n) + 1e-9
                marg = marg / marg.sum()
                occ = {}
                for bk, g in a.assign(b=((a.t + h) // BUCKET_S).clip(upper=MAX_T // BUCKET_S).astype(int)).groupby("b"):
                    c = np.bincount(g.i1, minlength=n)
                    occ[bk] = (c + OCC_PRIOR * marg) / (c.sum() + OCC_PRIOR)
                bb = ((b.t + h) // BUCKET_S).clip(upper=MAX_T // BUCKET_S).astype(int).to_numpy()
                occ_l += list(-np.log([occ.get(x, marg)[i] for x, i in zip(bb, b.i1.to_numpy())]))
                C = np.zeros((n, n))
                np.add.at(C, (a.i0.to_numpy(), a.i1.to_numpy()), 1)
                T = (C + FORECAST_PRIOR * marg) / (C.sum(1, keepdims=True) + FORECAST_PRIOR)
                fc_l += list(-np.log(T[b.i0.to_numpy(), b.i1.to_numpy()]))
        o, f_ = float(np.mean(occ_l)), float(np.mean(fc_l))
        res[f"{h}s"] = {"occupancy": r(o, 3), "forecast": r(f_, 3), "improvement_pct": r(100 * (o - f_) / o, 1), "samples": len(fc_l)}
    res["unit"] = "nats por amostra (menor = melhor); partidas inéditas, validação cruzada de 4 partes"
    return res


# ---------- playbook de rounds reais ----------

PLAYBOOK_MAX_T = 100


def build_playbook(Pm, Rm, runs_m, names):
    pidx = {p: i for i, p in enumerate(names)}
    rounds = []
    by_round = {k: g for k, g in runs_m[runs_m.t_in <= PLAYBOOK_MAX_T].groupby(KEY)}
    last_seen = Pm.groupby(KEY + ["steamid"]).t.max()
    for row in Rm.itertuples():
        key = (row.match, row._asdict()["round"])
        g = by_round.get(key)
        if g is None:
            continue
        teams = {}
        for side in ("CT", "T"):
            players = []
            for sid, gp in g[g.side == side].groupby("steamid"):
                died = float(last_seen.loc[key + (sid,)]) + 1 / SAMPLE_HZ
                players.append({"died_at": r(died, 2) if died < row.duration_s - 0.5 else None,
                                "steps": [[pidx[s.place], r(s.t_in, 2), r(s.t_out + 1 / SAMPLE_HZ, 2)] for s in gp.sort_values("t_in").itertuples()]})
            teams[side] = players
        rounds.append({"id": f"{row.match.split('__')[-1]}-{hashlib.md5(row.match.encode()).hexdigest()[:6]}#{key[1]}", "t_buy": row.t_buy, "ct_buy": row.ct_buy, "winner_side": row.winner_side,
                       "reason": row.reason, "duration_s": r(row.duration_s, 1),
                       "plant": {"site": row.plant_site, "t": r(row.plant_time_s, 1)} if row.planted else None,
                       "T": teams["T"], "CT": teams["CT"]})
    return {"places": names, "step_format": "[índice da região em 'places', entrada em s, saída em s]", "rounds": rounds}


# ---------- vetores de teste ----------

def make_vectors(model, playbook):
    """Entradas e saídas esperadas de contract/reference/tactics.py, para a versão em C#."""
    out = {"zone": [], "next_places": [], "occupancy": [], "forecast": [], "rotation": [], "round_weights": [], "place_at": [],
           "plant_site": [], "site_switch": []}
    sd_maps = sorted(model["site_decision"]["site_switch"]["map_intercepts"]) + ["de_desconhecido"]
    for mp in sd_maps:
        for t in (5.0, 15.0, 20.0, 30.0, 40.0, 55.0, 80.0):
            for ta, tb, ca, cb in ((0, 0, 2, 2), (3, 1, 2, 2), (1, 3, 2, 2), (2, 2, 3, 1), (2, 2, 1, 3), (5, 0, 0, 0), (4, 1, 2, 1)):
                out["plant_site"].append({"input": {"map": mp, "t": t, "t_a": ta, "t_b": tb, "ct_a": ca, "ct_b": cb},
                                          "expected": ref.plant_site_probability(model, mp, t, ta, tb, ca, cb)})
        for th, ch, to, co in ((4, 0, 1, 2), (4, 3, 1, 1), (2, 3, 2, 1), (1, 2, 4, 0), (5, 1, 0, 2), (3, 2, 2, 2)):
            out["site_switch"].append({"input": {"map": mp, "t_here": th, "ct_here": ch, "t_other": to, "ct_other": co},
                                       "expected": ref.site_switch_probability(model, mp, th, ch, to, co)})
    for mp, m in model["maps"].items():
        names = sorted(m["places"])
        for place in names[:: max(len(names) // 5, 1)][:6] + ["RegiaoQueNaoExiste"]:
            out["zone"].append({"input": {"map": mp, "place": place}, "expected": ref.zone(model, mp, place)})
        for place in names[:: max(len(names) // 4, 1)][:5]:
            out["next_places"].append({"input": {"map": mp, "place": place}, "expected": ref.next_places(model, mp, place)})
        for side in ("CT", "T"):
            for t in (0.0, 7.5, 40.0, 119.0, 400.0):
                out["occupancy"].append({"input": {"map": mp, "side": side, "t": t}, "expected": ref.occupancy(model, mp, side, t)})
            top = sorted(m["forecast"][side]["5s"], key=lambda k: -m["forecast"][side]["5s"][k]["n"])[:3]
            for place in top + ["RegiaoQueNaoExiste"]:
                for h in (3.0, 5.0, 7.5, 8.0, 10.0, 20.0):
                    out["forecast"].append({"input": {"map": mp, "side": side, "place": place, "horizon_s": h}, "expected": ref.forecast(model, mp, side, place, h)})
        for zc in ("A", "B", "Mid"):
            for z0 in ("A", "B", "Mid", "Spawn"):
                out["rotation"].append({"input": {"map": mp, "contact_zone": zc, "own_zone": z0}, "expected": ref.rotation(model, mp, zc, z0)})
        for b in BUY_TYPES:
            w = ref.round_weights(playbook, mp, b)
            out["round_weights"].append({"input": {"map": mp, "t_buy": b}, "expected": {"n": len(w), "weight": w[0][1], "first_ids": [x[0] for x in w[:3]]}})
        rounds = playbook["maps"][mp]["rounds"]
        for rnd in (rounds[0], rounds[len(rounds) // 2]):
            for side in ("CT", "T"):
                for i in range(len(rnd[side])):
                    for t in (0.0, 10.0, 30.0, 60.0, 95.0):
                        out["place_at"].append({"input": {"map": mp, "round_id": rnd["id"], "side": side, "player_index": i, "t": t},
                                                "expected": ref.place_at(rnd, side, i, t)})
    return {"contract_version": CONTRACT_VERSION, "generated_at": date.today().isoformat(), "tolerance": 1e-9,
            "description": "Entradas e saída esperada de contract/reference/tactics.py. A versão em C# deve reproduzir 'expected' dentro de 'tolerance'.", **out}


# ---------- principal ----------

def main():
    P = load_positions()
    R, tables = load_rounds()
    all_runs = runs(P)
    dmg, kls, gren = [], [], []
    for d in sorted(DATA_DIR.glob("*/match.json")):
        meta = json.loads(d.read_text())
        for name, bucket in (("damages", dmg), ("kills", kls), ("grenades", gren)):
            t = pd.read_parquet(d.parent / f"{name}.parquet")
            t["match"], t["map"] = d.parent.name, meta["map"]
            bucket.append(t)
    dmg, kls, gren = pd.concat(dmg, ignore_index=True), pd.concat(kls, ignore_index=True), pd.concat(gren, ignore_index=True)

    maps, playbook = {}, {}
    for mp in sorted(P["map"].unique()):
        Pm, Rm = P[P["map"] == mp].copy(), R[R["map"] == mp].copy()
        runs_m = all_runs[all_runs.match.isin(Pm.match.unique())]
        places = build_places(Pm, runs_m)
        n_by_side = {s: Pm[Pm.side == s].groupby(KEY).ngroups for s in ("CT", "T")}
        entry = {
            "n_rounds": int(len(Rm)), "places": places, "graph": build_graph(runs_m), "occupancy": build_occupancy(Pm, places),
            "forecast": build_forecast(Pm, places), "post_plant": build_post_plant(Pm, Rm),
            "rotation": build_rotation(Pm, dmg[dmg["map"] == mp], places),
            "engagements": build_engagements(dmg[dmg["map"] == mp], kls[kls["map"] == mp]),
            "utility": build_utility(Pm, gren[gren["map"] == mp], n_by_side),
            "evaluation": evaluate_forecast(Pm),
        }
        maps[mp] = entry
        playbook[mp] = build_playbook(Pm, Rm, runs_m, sorted(places))
        ev = entry["evaluation"]
        print(f"{mp}: {len(places)} regiões, {len(playbook[mp]['rounds'])} rounds no playbook | previsão 5s {ev['5s']['improvement_pct']:+.0f}%, 10s {ev['10s']['improvement_pct']:+.0f}% sobre a ocupação"
              if ev else f"{mp}: {len(places)} regiões (poucas partidas para avaliar)")

    # Decisão de bombsite do T (probabilidade de plant por bombsite e troca de lado)
    zone_of = {mp: {pl_: i["zone"] for pl_, i in m["places"].items()} for mp, m in maps.items()}
    P["zone"] = [zone_of[mp][pl_] for mp, pl_ in zip(P["map"], P.place)]
    P["k"] = (P.t * SAMPLE_HZ).round().astype(int)
    dm_all = dmg[(~dmg.after_round_end) & dmg.attacker_steamid.notna() & (dmg.attacker_side != dmg.user_side)]
    first_contact = dm_all.groupby(KEY).round_time.min().rename("first_contact")
    site_decision = {
        "site_probability": sdec.fit_site_probability(P, R),
        "site_switch": sdec.fit_switch(P, R),
        "pre_contact_check": sdec.pre_contact_check(P, R, first_contact),
        "team_effects": sdec.team_effects(P, R),
    }
    print("decisão de bombsite:", [(m["t"], m["evaluation"]["auc"]) for m in site_decision["site_probability"]["models"]],
          "| troca AUC", site_decision["site_switch"]["evaluation"]["auc"])

    base = {"schema_version": "1.0", "contract_version": CONTRACT_VERSION, "generated_at": date.today().isoformat()}
    source = {"matches": int(P.match.nunique()), "rounds": int(len(R)), "sample_hz": SAMPLE_HZ,
              "rounds_by_map": {mp: m["n_rounds"] for mp, m in maps.items()}}
    doc = {
        **base, "source": source,
        "conventions": [
            "Posições em metros, nas coordenadas da Source (1 unidade = 0,0254 m). Para a Unity, ver contract/docs/conventions.md.",
            "As regiões são os nomes de callout do próprio CS2 (last_place_name). Cada jogador está em exatamente uma região por vez.",
            "zone: A ou B se, depois de passar pela região, o jogador visita aquele bombsite em >= 65% das vezes (fluxo dos atacantes; do CT onde o T quase não passa); Mid no meio-termo; Spawn para os spawns. pa = fração que vai ao A.",
            "Tempos em segundos desde o fim do freeze time. Probabilidades somam 1 dentro de cada distribuição (exceto onde indicado).",
            "forecast[lado]['5s'][região].p é a distribuição da região do jogador 5 s depois, dado que está nessa região agora (e continua vivo).",
        ],
        "findings": [
            "Agrupar os rounds em 'planos' (k-means sobre janelas de 20 s) não previu o bombsite do plant em partidas inéditas (em 5 de 6 mapas o acerto foi igual ou pior que apostar na classe mais comum) e não melhorou a previsão de posição (de -10% a +3%); por isso não há planos no contrato.",
            "Uma medida simples funciona bem: quantos Ts e CTs há em cada zona (A/B) aos 15-55 s prevê o bombsite do plant com AUC de 0,79 a 0,86 em partidas inéditas (site_decision.site_probability).",
            "O T tende a acabar no lado com menos defensores: cada CT a mais no A em relação ao B reduz a chance de plant no A (coef. -0,47; IC95% -0,88 a -0,15 aos 20 s), e isso persiste nos rounds em que ainda não houve nenhuma luta, então não é só o T matando CTs onde ataca (site_decision.pre_contact_check).",
            "O T abandona o bombsite em que está comprometido com mais frequência quando está em desvantagem numérica ali: 58% se a desvantagem é de 2 ou mais, 4% se a vantagem é de 3 ou mais (site_decision.site_switch).",
            "A equipe quase não muda a preferência de bombsite do T (p = 0,78) nem muda de forma clara a defesa do CT (p = 0,08); só 9 de 30 pares (mapa, equipe de CT) têm 20 ou mais rounds, então perfis por equipe ainda não se sustentam.",
            "A região atual prevê a região futura bem melhor que a ocupação por tempo (+53% a +58% em 5 s, +35% a +41% em 10 s, em partidas inéditas).",
            "Para o comportamento coordenado do time, use o playbook (tactics_playbook.json): rounds reais com as rotas dos cinco jogadores.",
        ],
        "site_decision": site_decision,
        "maps": maps,
    }
    (ARTIFACTS_DIR / "tactics_playbook.json").write_text(json.dumps({**base, "source": source, "maps": playbook}, ensure_ascii=False, separators=(",", ":")))
    out = ARTIFACTS_DIR / "tactics.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    full_playbook = json.loads((ARTIFACTS_DIR / "tactics_playbook.json").read_text())
    VECTORS_DIR.mkdir(parents=True, exist_ok=True)
    vec = VECTORS_DIR / "tactics_vectors.json"
    vec.write_text(json.dumps(make_vectors(json.loads(out.read_text()), full_playbook), ensure_ascii=False, indent=1))
    print(f"\n{out} ({out.stat().st_size // 1024} KB), playbook ({(ARTIFACTS_DIR / 'tactics_playbook.json').stat().st_size // 1024} KB), {vec} ({vec.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
