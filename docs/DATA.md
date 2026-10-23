# Dados extraídos das demos (data/)

Gerado por `extract_demos.py` (demoparser2) a partir de `demos/*.dem`. Os `.rar` originais ficam em `archives/`.
`data/index.json` lista todas as demos com série, mapa, placar e número de rounds.

## Organização

- Nome de cada demo: `<evento>-<série>-<id>__<mapa>.dem`. A pasta de dados tem o mesmo nome: `data/<demo>/`.
  O prefixo evita colisão entre séries com o mesmo confronto (por exemplo, duas séries FURIA x MOUZ).
- Por demo:
  - `match.json` e `rounds.json`: metadados pequenos e aninhados, em JSON;
  - `kills`, `damages`, `grenades`, `bomb`, `economy` e `ticks`: tabelas em **Parquet**.
- Ler as tabelas: `pd.read_parquet("data/<demo>/kills.parquet")`. Os steamids são texto e os valores nulos são nulos de verdade.
- Nomes de times unificados (`TEAM_ALIASES` em `extract_demos.py`): "BetBoom Team" → "BetBoom", "Aurora Gaming" → "Aurora",
  "9z Globant" → "9z", "Team Vitality" → "Vitality".

## Convenções

- Só entram rounds oficiais:
  - demos com warmup e faca: os rounds a partir do último `begin_new_match`;
  - demos da ESL, que já começam na partida: a demo inteira.
- `round` é o número do round pelo placar (1..N). Quando um backup foi restaurado, vale a última tentativa,
  e eventos antes do fim do freeze time são descartados.
- `round_time` é contado em segundos desde o fim do freeze time (64 ticks/s).
- `after_round_end` marca eventos depois do `round_end` (exit frags etc.).
- Lado é `CT` ou `T`. As colunas `<prefixo>_side` e `<prefixo>_team` usam os prefixos `attacker`, `user` (vítima) e `assister`.
- Coordenadas `X`, `Y`, `Z` em unidades do mapa. `*_last_place_name` é o callout (ex.: `BombsiteB`).

## Arquivos

- **match.json**: série, mapa, tickrate, times, placar final, vencedor e jogadores (steamid, nome, time).
- **rounds.json**: um objeto por round com:
  - ticks de início, fim do freeze, fim e fim oficial;
  - vencedor, `reason` (`t_killed`, `ct_killed`, `bomb_exploded`, `bomb_defused`, `time_ran_out`) e times de cada lado;
  - placar antes e depois, primeiro kill, kills por lado e plant;
  - economia por lado (`equip_value`, `start_equip_value`, `spent`, `money_left`).
- **kills.parquet**: `player_death` com posição de atacante, vítima e assistente, arma, headshot, wallbang (`penetrated`),
  `thrusmoke`, `attackerblind`, `assistedflash` e `distance`. Inclui team kills e mortes pela C4.
- **damages.parquet**: `player_hurt` com `dmg_health`, `dmg_armor`, `health` restante, `hitgroup` e arma.
  Atenção: o evento chama a M4A1-S e a M4A4 de `m4a1`. Para distinguir, use a arma ativa do atacante.
- **grenades.parquet**: detonações (`smoke`, `flash`, `he`, `molotov`) com posição e quem lançou.
- **bomb.parquet**: `pickup`, `dropped`, `planted`, `defused` e `exploded`, com jogador e posição.
- **economy.parquet**: estado de cada jogador no fim do freeze time de cada round (dinheiro, equipamento, gasto, colete, capacete, kit e inventário).
- **ticks.parquet**: amostra a cada 8 ticks (8/s) da parte jogável de cada round, com posição, mira, vida, colete, arma ativa,
  callout, scope, defuse e flash.

Para reextrair: `.venv/bin/python extract_demos.py` (todas as demos, cerca de 6 s por demo).
