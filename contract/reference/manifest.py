"""Implementação de referência do carregamento por fatias (contract/sharded/manifest.json), só biblioteca padrão.

A versão em C# deve devolver a mesma lista de arquivos e o mesmo total de bytes
(veja contract/test_vectors/manifest_vectors.json).

  match_files(manifest, map, team_a, team_b) -> {"files": [caminhos ordenados], "bytes": total}
  all_files(manifest)                         -> todas as entradas de arquivo do manifesto
  players_of(manifest, team)                  -> steamids do elenco do time, na ordem do manifesto
"""

LAYOUT_DOC = {
    "global": "vale para qualquer confronto: regras, dinâmica das armas, modelo de time, baseline dos perfis e dados táticos gerais",
    "teams": "um arquivo por time: elenco e estatísticas descritivas por mapa",
    "players": "um arquivo por jogador (steamid): o perfil completo, que não depende de outro jogador",
    "maps": "dois arquivos por mapa: tática (regiões, grafo, previsão...) e playbook (rotas de rounds reais)",
    "match": "um confronto (mapa + 2 times) carrega: global + os 2 times + os jogadores deles + o mapa. Tudo mais fica de fora",
    "cache": "cada arquivo tem bytes e sha256; só baixe/releia o que mudou de hash",
    "paths": "relativos à pasta contract/",
}


def all_files(manifest):
    out = list(manifest["global"].values())
    out += list(manifest["teams"].values())
    out += list(manifest["players"].values())
    for m in manifest["maps"].values():
        out += [m["tactics"], m["playbook"]]
    return out


def players_of(manifest, team):
    return list(manifest["teams"][team]["players"])


def match_files(manifest, map_, team_a, team_b):
    """Arquivos de um confronto. KeyError (com o nome) se o mapa ou um dos times não existir no manifesto."""
    for kind, key in (("maps", map_), ("teams", team_a), ("teams", team_b)):
        if key not in manifest[kind]:
            raise KeyError(f"{kind[:-1]} desconhecido: {key}")
    entries = list(manifest["global"].values())
    for team in {team_a, team_b}:
        entries.append(manifest["teams"][team])
        entries += [manifest["players"][p] for p in players_of(manifest, team)]
    entries += [manifest["maps"][map_]["tactics"], manifest["maps"][map_]["playbook"]]
    unique = {e["path"]: e for e in entries}
    return {"files": sorted(unique), "bytes": sum(e["bytes"] for e in unique.values())}
