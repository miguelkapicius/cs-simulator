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
"""


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
