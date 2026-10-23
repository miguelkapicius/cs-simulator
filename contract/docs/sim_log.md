# Log da simulação (`sim_log.jsonl`)

É o que a Unity **escreve**. Cada partida simulada vira um arquivo de texto com um evento JSON por linha
(JSON Lines). O mesmo formato é usado para as demos reais convertidas, então o comparador mede simulação e
jogo real com o mesmo código.

- Schema: [`schemas/sim_log.schema.json`](../schemas/sim_log.schema.json)
- Exemplo real (2 rounds): [`examples/sim_log_example.jsonl`](../examples/sim_log_example.jsonl)
- Validar: `python -m calibration.validate_log meu_log.jsonl`
- Comparar com o jogo real: ver [`calibration.md`](calibration.md)

## Regras gerais

1. **Um arquivo por partida**, um evento por linha, em UTF-8. Todo evento tem `type`.
2. **Ordem:** os eventos saem em ordem de `tick`. Dentro do mesmo tick, a ordem é
   `round_start`, `freeze_end`, `bomb`, `grenade`, `sighting`, `shot`, `damage`, `kill`, `round_end`.
3. **`tick`** é o tempo da simulação, em ticks, e `match_start.tickrate` diz quantos ticks valem 1 segundo
   (o CS2 usa 64). O tempo dentro do round é `(tick - freeze_end.tick) / tickrate`.
4. **Estrutura da partida:** `match_start`, depois, para cada round, `round_start`, `freeze_end`, os eventos do round e
   `round_end`, e por fim `match_end`. Os rounds são numerados 1, 2, 3... sem buracos.
5. **Ids:** `player` é um texto estável por jogador. Se o bot usa o perfil de um jogador real, use o `steamid` dele
   em `player_profiles.json`. Armas usam os ids de `game_rules.json` (`ak47`, `m4a1_silencer`, `awp`...).
   Facas viram `knife`. Dano de fogo é `inferno`, de HE é `hegrenade`, da bomba é `planted_c4`, de queda é `world`.
6. **Lados:** `CT` e `T`. Os times trocam de lado no intervalo, e `round_start` informa quem é CT e quem é T em cada round.
   Os lados dos jogadores vêm de `freeze_end.players[].side`, não precisam ser repetidos nos outros eventos.
7. **Distâncias** em metros, **ângulos** em graus, **velocidades** em unidades Source por segundo
   (ver [`conventions.md`](conventions.md)).
8. **Campos opcionais:** se você não tiver um valor, omita o campo ou use `null`. A métrica que depende dele aparece como
   "sem dados" no relatório, sem quebrar nada.

## Eventos

### `match_start`
```json
{"type":"match_start","contract_version":"1.0.0","source":"sim","map":"de_mirage","tickrate":64,"seed":12345,
 "sim_build":"unity-0.3.1","players":[{"player":"76561198200982290","name":"molodoy","team":"FURIA"}]}
```
`source` é `sim` na Unity. `seed` e `sim_build` são opcionais, mas ajudam a reproduzir uma partida.

### `round_start`
`{"type":"round_start","round":1,"tick":9823,"ct_team":"BetBoom","t_team":"FURIA","score":{"BetBoom":0,"FURIA":0}}`
Início do round (começo do freeze time). `score` é o placar antes do round.

### `freeze_end`
Estado de **todos os 10 jogadores** no fim do freeze time, depois da compra. Alimenta as métricas de economia e compra.

| Campo | Significado |
|---|---|
| `side` | `CT` ou `T` neste round |
| `money_before` | dinheiro no início da fase de compra |
| `equip_before` | valor do equipamento que o jogador já carregava (armas mantidas do round anterior) |
| `money` | dinheiro depois de comprar |
| `equip_value` | valor total do equipamento que carrega agora (some o preço de tudo) |
| `armor`, `helmet`, `defuser` | colete (0 a 100), capacete, kit de defuse |
| `primary`, `secondary` | arma principal e pistola (ids), ou `null` |
| `grenades` | quantidade de `smoke`, `flash`, `he`, `molotov` |

### `shot`
Um evento por tiro de arma de fogo.

| Campo | Significado |
|---|---|
| `shooter`, `weapon` | quem atirou e com qual arma |
| `hit` | o tiro acertou algum inimigo |
| `target` | inimigo acertado; se errou, o inimigo vivo mais próximo da mira. `null` se não há inimigo vivo |
| `distance_m` | distância até `target` |
| `aim_error_deg` | ângulo entre a mira e a **cabeça** de `target` |
| `speed` | velocidade horizontal do atirador no tiro |
| `ducking`, `airborne` | agachado, no ar |
| `spray_index` | posição da bala na rajada: 1 é a primeira depois de soltar o gatilho, 2 a segunda... |

`distance_m` e `aim_error_deg` são o que define um **"tiro de combate"** (mira a menos de 10° de um inimigo, ou
acertou). A precisão e a mira são medidas só sobre esses tiros, para não contar tiros dados sem inimigo na tela.

### `damage`
`attacker` (`null` se for dano do mundo), `victim`, `weapon`, `hitgroup`
(`head`, `neck`, `chest`, `stomach`, `left_arm`, `right_arm`, `left_leg`, `right_leg`, `generic`),
`dmg_health` (já limitado à vida restante) e `dmg_armor`. Opcionais: `health_after`, `armor_after`.

### `kill`
`attacker` (`null` para bomba/mundo), `victim`, `assister`, `weapon`, `headshot`, `penetrated` (superfícies atravessadas),
`thrusmoke`, `noscope`, `attackerblind`, `assistedflash`, `distance_m`.

### `bomb`
`event` é `pickup`, `dropped`, `planted`, `defused` ou `exploded`; `player` e, no `planted`, `site` (`A` ou `B`).
Um plant só vale se acontecer antes do `round_end`.

### `grenade`
Detonação: `kind` (`smoke`, `flash`, `he`, `molotov`) e `thrower`.

### `sighting` (recomendado)
`observer` passou a ver `target` (inimigo vivo) depois de **pelo menos 0,5 s sem vê-lo**. Traz `distance_m` e `aim_error_deg`
(ângulo entre a mira do observador e a cabeça do alvo nesse instante). Habilita as métricas de **tempo de reação**,
**duelo** e **posicionamento de mira**. Nas demos, "ver" é a linha de visão aproximada do próprio jogo; na Unity use
o seu teste de visibilidade (raycast) com o campo de visão do jogador.

### `round_end`
`winner_side`, `reason` (`t_killed`, `ct_killed`, `bomb_exploded`, `bomb_defused`, `time_ran_out`),
`score` (placar depois do round) e `alive` (`{"CT":n,"T":n}` vivos no instante do fim).

### `match_end`
`{"type":"match_end","winner":"FURIA","score":{"BetBoom":11,"FURIA":13}}`

## Como cada coisa é interpretada

- **Depois do `round_end`** ainda podem aparecer kills e danos (exit frags). Podem ser gravados normalmente:
  o carregador os marca como "depois do fim do round" e a maioria das métricas os ignora.
- **Antes do `freeze_end`** (durante o freeze time) eventos de tiro são ignorados.
- **Reação:** primeiro tiro mirado (`aim_error_deg < 10°`) no alvo em até 2 s depois do `sighting`.
- **Duelo:** resolvido se alguém mata o outro em até 3 s depois do `sighting`.
- **Sequência de tiros (rajada):** tiros consecutivos do mesmo jogador onde o `spray_index` sobe; cada vez que reinicia em 1
  começa outra rajada.

## O que gravar primeiro

Se quiser começar pequeno, estes eventos já dão a maior parte da calibração:
`match_start`, `round_start`, `freeze_end`, `kill`, `bomb`, `round_end`, `match_end` (rounds e economia),
e depois `shot` (precisão e mira), `damage` (onde os tiros acertam) e `sighting` (reação e duelo).
Cada família de métricas aparece como "sem dados" no relatório até o evento correspondente existir.
