"""Gera contract/test_vectors/manager_economy_vectors.json: entradas e saídas esperadas de contract/reference/manager_economy.py.

Os casos valem para os números de manager_params.json (o `params_sha256` registra quais). Mudou um parâmetro? Rode de novo:
`make manager-vectors`. O port em C# aplica as mesmas entradas e confere as saídas com a tolerância do arquivo.

Uso: .venv/bin/python -m pipeline.build_manager_vectors
"""
import hashlib
import itertools
import json
from datetime import date

from contract.reference import manager_economy as eco
from pipeline.common import ARTIFACTS_DIR, CONTRACT_VERSION, VECTORS_DIR

TOLERANCE = 1e-9
ROSTER = [{"role": "awper", "skill": 80.0}, {"role": "rifler", "skill": 60.0},
          {"role": "igl", "skill": 55.0}, {"role": "coach", "skill": 90.0}]
FULL_ROSTER = [{"role": r, "skill": s} for r, s in (("awper", 88.0), ("igl", 76.0), ("entry", 74.0), ("support", 70.0),
                                                     ("lurker", 69.0), ("rifler", 66.0), ("coach", 80.0))]
HIDDEN = {"consistency": 71.5, "communication": 33.0, "ceiling": 90.0, "lan_form": 55.0, "temperament": 12.25}


def load_params():
    doc = json.loads((ARTIFACTS_DIR / "manager_params.json").read_text(encoding="utf-8"))
    return doc["params"]


def params_sha256(prm) -> str:
    return hashlib.sha256(json.dumps(prm, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def case(inp, expected):
    return {"input": inp, "expected": expected}


def build():
    prm = load_params()
    thr = prm["accept_threshold"]
    doc = {"contract_version": CONTRACT_VERSION, "generated_at": date.today().isoformat(), "tolerance": TOLERANCE,
           "params_sha256": params_sha256(prm),
           "note": "Cada grupo aplica a função de contract/reference/manager_economy.py de mesmo nome às entradas de `input` e espera `expected`."}

    doc["salary_for"] = [case({"tier": t, "skill": s, "hype": h}, eco.salary_for(t, s, h, prm))
                         for t, s, h in itertools.product((1, 2, 3), (0, 30, 50, 60, 70, 85, 95, 100), (0, 50, 100))]
    doc["buyout_for"] = [case({"salary_month": sal, "hype": h, "end_week": e, "week": w, "interested": i},
                              eco.buyout_for(sal, h, e, w, i, prm))
                         for sal, h, (e, w), i in itertools.product((1500, 40000, 90000), (0, 50, 100),
                                                                    ((96, 0), (96, 48), (96, 95), (96, 96), (300, 0)), (1, 3))]
    doc["decay_hype"] = [case({"hype": h, "weeks": w}, eco.decay_hype(h, w, prm))
                         for h, w in itertools.product((0, 25, 80, 100), (0, 1, 12, 48))]
    doc["match_update"] = [case({"hype": h, "form": f, "rating": r, "won": won, "major": maj},
                                dict(zip(("hype", "form"), eco.match_update(h, f, r, won, maj, prm))))
                           for h, f, r, won, maj in itertools.product((0.0, 50.0, 99.0), (0.0, 0.5), (0.4, 1.0, 1.6),
                                                                      (False, True), (False, True))]
    doc["weekly_wages"] = [case({"salaries_month": s}, eco.weekly_wages(s)) for s in ([], [1000], [12000, 4000, 3999])]
    doc["weekly_revenue"] = [case({"tier": t, "rank": r}, eco.weekly_revenue(t, r, prm))
                             for t, r in itertools.product((1, 2, 3), (0, 1, 2, 5, 10, 12, 16, 99))]
    doc["sticker_payout"] = [case({"tier": t, "hypes": hy}, eco.sticker_payout(t, hy, prm))
                             for t, hy in itertools.product((1, 2, 3), ([], [50.0], [20.0, 50.0, 90.0], [100.0] * 5))]
    doc["can_afford"] = [case({"budget": b, "weekly_wage_total": w, "offer_salary_month": s, "signing_bonus": bn},
                              eco.can_afford(b, w, s, bn, prm))
                         for b, w, s, bn in itertools.product((0, 30000, 50000, 1000000), (0, 3000), (0, 1500, 5000),
                                                              (0, 1000, 40000))]
    doc["team_strength"] = [case({"club_tier": t, "roster": r}, eco.team_strength(t, r, prm))
                            for t, r in itertools.product((1, 2, 3), ([], [{"role": "coach", "skill": 70.0}], ROSTER, FULL_ROSTER))]
    doc["role_term"] = [case({"role": ro, "skill": s, "roster": ROSTER}, eco.role_term(ro, s, ROSTER, prm))
                        for ro, s in itertools.product(("awper", "rifler", "igl", "coach", "lurker"), (50.0, 70.0, 90.0))]
    players = [{"tier": 2, "skill": 62.0, "hype": 30.0, "role": "awper"},
               {"tier": 1, "skill": 95.0, "hype": 80.0, "role": "rifler"},
               {"tier": 3, "skill": 45.0, "hype": 5.0, "role": "igl"}]
    clubs = [{"tier": 2, "prestige": 55.0, "reputation": 70.0}, {"tier": 1, "prestige": 90.0, "reputation": 10.0}]
    doc["score_offer"] = [case({"player": p, "offer_salary_month": s, "club": c, "roster": r},
                               eco.score_offer(p, s, c, r, prm))
                          for p, s, c, r in itertools.product(players, (500, 3000, 6000, 40000), clubs, ([], ROSTER))]
    doc["accepts"] = [case({"score": s}, eco.accepts(s, prm)) for s in (0.0, thr - 0.01, thr, thr + 0.01, 1.0)]
    doc["scout_noise"] = [case({"world_seed": sd, "pid": pid, "level": lv, "key": k, "width": prm["scouting"]["noise"][str(lv)]},
                               eco.scout_noise(sd, pid, lv, k, prm["scouting"]["noise"][str(lv)]))
                          for sd, pid, lv, k in itertools.product((1, 42), ("e00", "g_kozen"), (0, 1, 2, 3), ("skill", "consistency"))]
    doc["scout_numbers"] = [case({"skill": s, "hidden": HIDDEN, "pid": "g_kozen", "level": lv, "world_seed": 7},
                                 eco.scout_numbers(s, HIDDEN, "g_kozen", lv, 7, prm))
                            for s, lv in itertools.product((3.0, 60.0, 99.5), (0, 1, 2, 3))]
    return doc


def main():
    doc = build()
    (VECTORS_DIR / "manager_economy_vectors.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    groups = [k for k, v in doc.items() if isinstance(v, list)]
    print("manager_economy_vectors.json: %d casos em %d grupos" % (sum(len(doc[g]) for g in groups), len(groups)))


if __name__ == "__main__":
    main()
