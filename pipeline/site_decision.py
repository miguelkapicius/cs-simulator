"""Decisão de bombsite do T: probabilidade de plant por bombsite e troca de lado.

Dois modelos, ambos validados em partidas que não viram (validação cruzada agrupada por partida):

  site_probability  P(plant no A | quantos Ts e CTs há em cada zona, no instante t)
                    Um modelo por instante (15, 25, 35, 45, 55 s); a Unity usa o mais próximo.
  site_switch       P(o time abandona o bombsite em que estava comprometido aos 30 s | Ts e CTs em cada zona)
                    Testa a hipótese "o T encontra o desequilíbrio e ataca onde há menos defesa".

Usa o estado verdadeiro do jogo (quem está em qual zona). Na simulação, quem decide é o time, que não vê tudo:
passe só o que o time conhece (por exemplo, os CTs avistados ou mortos).
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from calibration.metrics import KEY

SITE_TIMES = (15, 25, 35, 45, 55)
SWITCH_TAU = 30
C = 1.0
N_FOLDS = 4
MIN_ROUNDS = 40


def zone_counts(P, side, t, prefix):
    """Jogadores vivos do lado em cada zona (A, B) no instante t, por round."""
    g = P[(P.side == side) & (P.k == int(round(t * 8)))].groupby(KEY + ["zone"]).size().unstack(fill_value=0)
    for z in ("A", "B"):
        if z not in g:
            g[z] = 0
    return g[["A", "B"]].add_prefix(prefix)


def decision_frame(P, R, tau):
    """Rounds com plant em A ou B depois de tau, com as contagens por zona em tau."""
    Rk = R.set_index(KEY)
    pl = Rk[Rk.planted & Rk.plant_site.isin(["A", "B"])].copy()
    pl["siteA"] = (pl.plant_site == "A").astype(int)
    d = pl.join(zone_counts(P, "T", tau, "t_")).join(zone_counts(P, "CT", tau, "ct_")).fillna(0)
    d = d[d.plant_time_s > tau].copy()
    d["t_diff"], d["ct_diff"] = d.t_A - d.t_B, d.ct_A - d.ct_B
    return d


def _design(d, cols, maps):
    return np.column_stack([d[cols].to_numpy(float)] + [(d["map"] == m).to_numpy(float) for m in maps])


def _cv(d, cols, maps, y):
    """AUC e log-loss fora da amostra do modelo completo e de um modelo só com o mapa (a taxa-base)."""
    g = d.reset_index().match.to_numpy()
    out = {}
    for name, use in (("model", cols), ("base", [])):
        X = _design(d, use, maps)
        oof = np.zeros(len(d))
        for tr, te in GroupKFold(min(N_FOLDS, len(set(g)))).split(X, y, g):
            oof[te] = LogisticRegression(C=C, max_iter=2000).fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
        oof = np.clip(oof, 1e-6, 1 - 1e-6)
        out[name] = (oof, float(-np.mean(y * np.log(oof) + (1 - y) * np.log(1 - oof))))
    auc = float(roc_auc_score(y, out["model"][0])) if len(set(y)) > 1 else None
    return {"auc": None if auc is None else round(auc, 3), "log_loss": round(out["model"][1], 3), "baseline_log_loss": round(out["base"][1], 3),
            "improvement_pct": round(100 * (out["base"][1] - out["model"][1]) / out["base"][1], 1)}


def _fit(d, cols, maps, y):
    X = _design(d, cols, maps)
    lr = LogisticRegression(C=C, max_iter=2000).fit(X, y)
    coef = lr.coef_[0]
    return {"intercept": round(float(lr.intercept_[0]), 6),
            "coefficients": {c: round(float(v), 6) for c, v in zip(cols, coef[:len(cols)])},
            "map_intercepts": {m: round(float(v), 6) for m, v in zip(maps, coef[len(cols):])}}


def _bootstrap_coef(d, cols, maps, y, n_boot=300, seed=0):
    """Coeficientes e IC95% reamostrando partidas inteiras."""
    rng = np.random.default_rng(seed)
    matches = d.reset_index().match.to_numpy()
    um = np.unique(matches)
    boots = []
    for _ in range(n_boot):
        idx = np.concatenate([np.where(matches == m)[0] for m in rng.choice(um, len(um))])
        boots.append(LogisticRegression(C=C, max_iter=2000).fit(_design(d.iloc[idx], cols, maps), y[idx]).coef_[0][:len(cols)])
    return np.array(boots)


def pre_contact_check(P, R, first_contact, taus=(15, 20, 25)):
    """O efeito dos CTs na escolha do bombsite persiste quando ainda não houve nenhuma luta?

    Depois da primeira luta, o T mata CTs onde ataca e a contagem de defensores cai ali (causalidade invertida). Antes dela,
    a disposição dos CTs é a original: se o efeito continua, o T realmente acaba no lado que tinha menos defensores.
    """
    maps = sorted(P["map"].unique())
    out = []
    for tau in taus:
        d = decision_frame(P, R, tau).join(first_contact, how="left")
        for label, sel in (("todos os rounds", d), ("só rounds sem nenhuma luta antes de t", d[(d.first_contact > tau) | d.first_contact.isna()])):
            y = sel.siteA.to_numpy()
            full = LogisticRegression(C=C, max_iter=2000).fit(_design(sel, ["t_diff", "ct_diff"], maps), y).coef_[0][:2]
            ci = np.percentile(_bootstrap_coef(sel, ["t_diff", "ct_diff"], maps, y), [2.5, 97.5], axis=0)
            out.append({"t": tau, "rounds": label, "n_rounds": int(len(sel)),
                        "ct_diff": {"coef": round(float(full[1]), 3), "ci95": [round(float(ci[0][1]), 3), round(float(ci[1][1]), 3)]},
                        "t_diff": {"coef": round(float(full[0]), 3), "ci95": [round(float(ci[0][0]), 3), round(float(ci[1][0]), 3)]}})
    return out


def fit_site_probability(P, R):
    maps = sorted(P["map"].unique())
    models = []
    for tau in SITE_TIMES:
        d = decision_frame(P, R, tau)
        if len(d) < MIN_ROUNDS:
            continue
        y = d.siteA.to_numpy()
        models.append({"t": tau, "n_rounds": int(len(d)), "plant_a_rate": round(float(y.mean()), 3),
                       **_fit(d, ["t_diff", "ct_diff"], maps, y), "evaluation": _cv(d, ["t_diff", "ct_diff"], maps, y)})
    return {
        "features": ["t_diff", "ct_diff"],
        "definition": "t_diff = Ts vivos na zona A − Ts vivos na zona B; ct_diff = CTs vivos na zona A − CTs vivos na zona B, no instante t",
        "formula": "P(plant no A) = sigmoid(intercept + map_intercepts[mapa] + coefficients.t_diff * t_diff + coefficients.ct_diff * ct_diff)",
        "usage": "usa o modelo cujo t está mais perto do instante atual (empate: o anterior); só vale enquanto a bomba não foi plantada",
        "models": models,
    }


def switch_frame(P, R, tau=SWITCH_TAU):
    d = decision_frame(P, R, 0).copy()                         # todos os plants
    d = d.drop(columns=["t_A", "t_B", "ct_A", "ct_B", "t_diff", "ct_diff"]).join(zone_counts(P, "T", tau, "t_")).join(zone_counts(P, "CT", tau, "ct_")).fillna(0)
    d = d[d.plant_time_s > tau].copy()
    d["commit"] = np.where(d.t_A > d.t_B, "A", np.where(d.t_B > d.t_A, "B", "?"))
    d = d[d.commit != "?"].copy()
    d["switch"] = (d.commit != d.plant_site).astype(int)
    a = d.commit == "A"
    d["t_here"], d["ct_here"] = np.where(a, d.t_A, d.t_B), np.where(a, d.ct_A, d.ct_B)
    d["t_other"], d["ct_other"] = np.where(a, d.t_B, d.t_A), np.where(a, d.ct_B, d.ct_A)
    return d


def fit_switch(P, R):
    d = switch_frame(P, R)
    maps = sorted(d["map"].unique())
    cols = ["t_here", "ct_here", "t_other", "ct_other"]
    y = d.switch.to_numpy()
    boots = _bootstrap_coef(d, cols, maps, y)                    # IC95% reamostrando partidas inteiras
    model = _fit(d, cols, maps, y)
    model["coefficient_ci95"] = {c: [round(float(np.percentile(boots[:, i], 2.5)), 3), round(float(np.percentile(boots[:, i], 97.5)), 3)] for i, c in enumerate(cols)}
    adv = d.t_here - d.ct_here
    table = [{"local_advantage": label, "n": int(len(g)), "switch_rate": round(float(g.switch.mean()), 3)}
             for label, g in d.groupby(pd.cut(adv, [-9, -2, -1, 0, 1, 2, 9], labels=["<= -2", "-1", "0", "+1", "+2", ">= +3"]), observed=True)]
    return {
        "t": SWITCH_TAU, "n_rounds": int(len(d)), "switch_rate": round(float(y.mean()), 3),
        "features": cols,
        "definition": "o time está 'comprometido' com a zona (A ou B) onde há mais Ts aos 30 s; t_here/ct_here = Ts e CTs vivos nessa zona, t_other/ct_other = na outra",
        "formula": "P(abandonar o bombsite) = sigmoid(intercept + map_intercepts[mapa] + soma(coefficients[f] * f))",
        **model, "by_local_advantage": table, "switch_rate_by_map": {m: round(float(g.switch.mean()), 3) for m, g in d.groupby("map") if len(g) >= 20},
        "evaluation": _cv(d, cols, maps, y),
    }


def team_effects(P, R, B=2000, seed=0):
    """A identidade da equipe muda a defesa do CT ou a preferência de bombsite do T, dentro do mesmo mapa? (teste de permutação)"""
    rng = np.random.default_rng(seed)
    Rk = R.set_index(KEY)
    ct = zone_counts(P, "CT", 20, "ct_").join(Rk[["map", "ct_team", "t_team", "planted", "plant_site"]], how="inner")
    ct["diff"] = ct.ct_A - ct.ct_B

    def between(df, col, val):
        tot, n = 0.0, 0
        for _, gm in df.groupby("map"):
            gm = gm.groupby(col).filter(lambda x: len(x) >= 8)
            if gm[col].nunique() < 2:
                continue
            means = gm.groupby(col)[val].agg(["mean", "size"])
            tot += ((means["mean"] - gm[val].mean()) ** 2 * means["size"]).sum()
            n += len(gm)
        return tot / max(n, 1)

    def perm(df, col, val):
        obs, cnt = between(df, col, val), 0
        for _ in range(B):
            sh = df.copy()
            sh[col] = sh.groupby("map")[col].transform(lambda s: rng.permutation(s.values))
            cnt += between(sh, col, val) >= obs
        return float(obs), float((cnt + 1) / (B + 1))

    pl = ct[ct.planted & ct.plant_site.isin(["A", "B"])].copy()
    pl["siteA"] = (pl.plant_site == "A").astype(float)
    o1, p1 = perm(ct, "ct_team", "diff")
    o2, p2 = perm(pl, "t_team", "siteA")
    return {"ct_defense_by_team": {"between_team_variance": round(o1, 3), "p_value": round(p1, 3)},
            "t_site_preference_by_team": {"between_team_variance": round(o2, 3), "p_value": round(p2, 3)},
            "pairs_ct_with_20_rounds": int((ct.groupby(["map", "ct_team"]).size() >= 20).sum()), "pairs_ct_total": int(ct.groupby(["map", "ct_team"]).ngroups)}
