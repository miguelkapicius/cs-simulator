"""Implementação de referência da camada tática (tactics.json e tactics_playbook.json), só biblioteca padrão.

A versão em C# deve devolver os mesmos números para as mesmas entradas
(veja contract/test_vectors/tactics_vectors.json).

  zone(model, map, place)                       -> "A" | "B" | "Mid" | "Spawn"
  next_places(model, map, place)                -> para onde o jogador vai ao sair da região {região: p}
  occupancy(model, map, side, t)                -> onde o lado costuma estar em t segundos {região: p}
  forecast(model, map, side, place, horizon_s)  -> onde o jogador estará daqui a ~5 ou ~10 s {região: p}
  rotation(model, map, contact_zone, own_zone)  -> como um CT reage ao primeiro contato
  round_weights(playbook, map, t_buy)           -> peso de cada round do playbook para sortear [(id, peso)]
  place_at(round, side, player_index, t)        -> região (índice) do jogador do round gravado em t, ou None se já morreu
  plant_site_probability(model, map, t, t_a, t_b, ct_a, ct_b) -> {"A": p, "B": 1-p}: onde o T vai plantar
  site_switch_probability(model, map, t_here, ct_here, t_other, ct_other) -> chance do T abandonar o bombsite em que está comprometido
"""
import math


def _map(model, map_):
    return model["maps"][map_]


def zone(model, map_, place):
    info = _map(model, map_)["places"].get(place)
    return info["zone"] if info else "Mid"


def next_places(model, map_, place):
    g = _map(model, map_)["graph"].get(place)
    return {e["to"]: e["p"] for e in g["edges"]} if g else {}


def occupancy(model, map_, side, t):
    occ = _map(model, map_)["occupancy"][side]
    i = min(int(t // occ["bucket_s"]), len(occ["buckets"]) - 1)
    return dict(occ["buckets"][max(i, 0)]["p"])


def forecast(model, map_, side, place, horizon_s):
    """Usa a tabela de 5 s para horizontes até 7,5 s e a de 10 s acima disso."""
    key = "5s" if horizon_s <= 7.5 else "10s"
    entry = _map(model, map_)["forecast"][side][key].get(place)
    return dict(entry["p"]) if entry else {}


def rotation(model, map_, contact_zone, own_zone):
    return _map(model, map_)["rotation"].get("by_contact_zone", {}).get(contact_zone, {}).get(own_zone)


def round_weights(playbook, map_, t_buy):
    """Rounds com o mesmo tipo de compra do T pesam igual; se não houver nenhum, todos pesam igual."""
    rounds = playbook["maps"][map_]["rounds"]
    same = [r for r in rounds if r["t_buy"] == t_buy]
    pool = same or rounds
    return [(r["id"], 1.0 / len(pool)) for r in pool]


def place_at(round_, side, player_index, t):
    player = round_[side][player_index]
    if player["died_at"] is not None and t >= player["died_at"]:
        return None
    for place, t_in, t_out in player["steps"]:
        if t_in <= t < t_out:
            return place
    return None


def _sigmoid(x):
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def plant_site_probability(model, map_, t, t_a, t_b, ct_a, ct_b):
    """Probabilidade do plant em cada bombsite, antes de a bomba ser plantada.

    t_a, t_b: Ts vivos nas zonas A e B; ct_a, ct_b: CTs vivos nas zonas A e B, no instante t (s desde o fim do freeze time).
    Usa o modelo cujo instante está mais perto de t (empate: o anterior). Mapa desconhecido usa intercepto 0.
    """
    models = model["site_decision"]["site_probability"]["models"]
    m = min(models, key=lambda x: (abs(x["t"] - t), x["t"]))
    x = (m["intercept"] + m["map_intercepts"].get(map_, 0.0)
         + m["coefficients"]["t_diff"] * (t_a - t_b) + m["coefficients"]["ct_diff"] * (ct_a - ct_b))
    p = _sigmoid(x)
    return {"A": p, "B": 1.0 - p}


def site_switch_probability(model, map_, t_here, ct_here, t_other, ct_other):
    """Chance de o time abandonar o bombsite em que estava comprometido aos 30 s (here = a zona do compromisso, other = a outra)."""
    m = model["site_decision"]["site_switch"]
    c = m["coefficients"]
    x = (m["intercept"] + m["map_intercepts"].get(map_, 0.0) + c["t_here"] * t_here + c["ct_here"] * ct_here
         + c["t_other"] * t_other + c["ct_other"] * ct_other)
    return _sigmoid(x)
