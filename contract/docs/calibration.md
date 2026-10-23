# Calibração: a simulação reproduz o jogo real?

O critério de "a simulação está pronta" é objetivo: o log que ela grava tem que dar as **mesmas estatísticas** das demos reais.
O comparador faz essa conta e diz o que ajustar na mecânica.

```
Unity simula N partidas ──► sim_log.jsonl ──► validate_log ──► compare ──► report.md
                                                                  ▲
                                          contract/artifacts/calibration_targets.json
                                          (as mesmas métricas medidas em 28 partidas reais)
```

## Como usar

```bash
# 1. conferir que o log respeita o contrato
python -m calibration.validate_log sim/*.jsonl

# 2. comparar com o jogo real e gerar o relatório
python -m calibration.compare sim/ --out reports/rodada-01
#    -> reports/rodada-01/report.md (leitura)  e  report.json (para scripts)
```

O comando sai com código 1 se houver algum `FAIL` (`--fail-on WARN` também recusa avisos), então pode rodar em CI.
Quantas partidas simular: o ruído do relatório diminui com a raiz do número de partidas.
**Com 1 a 3 partidas** quase nada é conclusivo; **com 20 ou mais** a calibração é apertada.

## O que é medido (325 métricas)

| Grupo | Exemplos | Eventos necessários |
|---|---|---|
| `round.*` | vitória do CT, motivo do fim do round, duração, taxa e horário do plant, bombsite, defuse, kills por round, primeiro kill e quem vence depois dele | `round_*`, `freeze_end`, `kill`, `bomb` |
| `econ.*` | vitória do CT por combinação de compras (full x eco...) | `freeze_end` |
| `combat.*` | precisão por arma e distância, erro de mira da 1ª bala, tiros parado/agachado, tamanho da rajada, headshots, distância dos kills, ADR | `shot`, `damage`, `kill` |
| `duel.*` | tempo de reação, vitória no duelo, mira no instante em que o inimigo aparece, e quantas vezes o jogador atira instantaneamente, depois ou não atira ao ver um inimigo (por erro da mira) | `sighting` + `shot` + `kill` |
| `tactic.*` | onde cada lado está aos 20, 40 e 60 s (por zona do mapa), quando acontece o primeiro contato, trocas de região por jogador, tempo de permanência em cada região, e o quanto o time troca de bombsite depois de se comprometer | `positions`, `damage` |
| `buy.*` | tipo de compra, colete, capacete, kit, AWPs e granadas por jogador | `freeze_end` |

Métricas com sufixo `@de_mirage` são do mapa. Elas só aparecem se a simulação tiver rounds suficientes no mapa.
Cada métrica tem um `desc` em `calibration_targets.json` explicando o que mede.

## Como o status é decidido

Cada métrica é uma de três formas: **proporção** (taxa de acerto), **média** (kills por round) ou **distribuição**
(tempos, distâncias, ângulos; comparada nos quantis 10/25/50/75/90).

| Status | Significado |
|---|---|
| `OK` | diferença pequena na prática, ou dentro do ruído |
| `WARN` | fora do ruído (3 ≤ \|z\| < 5) e maior que a tolerância. Vale olhar |
| `FAIL` | fora do ruído (\|z\| ≥ 5) e maior que a tolerância. A mecânica precisa de ajuste |
| `INSUFFICIENT` | a simulação tem menos de 30 amostras dessa métrica; simule mais |
| `MISSING` | a meta existe, mas o log não tem os eventos para calculá-la |

**Tolerâncias** (`calibration_targets.json` → `thresholds`): proporções 3 pontos percentuais, médias 5% relativos,
distribuições 5 pontos percentuais de desvio em cada quantil. Uma diferença só vira alerta se for **estatisticamente real e também
grande o bastante para importar**.

### De onde vem o ruído
As amostras de uma mesma partida não são independentes: mesmos jogadores, mapa e adversário. Por isso o ruído **não** é
calculado como se cada tiro fosse independente (isso geraria falsos alarmes). Ele vem de **quanto a métrica varia de uma partida real
para outra** (`between` em cada meta) e encolhe com o número de partidas simuladas.
Metas sem partidas reais suficientes para estimar isso (`between` ausente) usam o erro-padrão de amostras independentes e nunca passam de `WARN`.

### Quão confiável é o comparador
Medido com partidas reais que ele não conhecia (8 divisões aleatórias, 19 partidas para calibrar e 9 para testar):
**0 FAIL e 1,4% de WARN**, o ruído esperado (nas métricas táticas, 0,7%). Já uma simulação adulterada de propósito (rifles errando 30% mais, rounds
terminando por tempo, jogadores parados no spawn) é apontada com `FAIL` nas métricas certas.

## Como usar o relatório para ajustar a mecânica

1. Comece pelo grupo `round.*` e `buy.*`: se o resultado do round está errado, os ajustes finos de mira não resolvem.
2. Nas métricas de `combat.accuracy.*`: se a precisão está baixa em todas as distâncias, o erro de mira (`aim_error_first_bullet_deg`)
   está alto demais; se só cai em distâncias longas, ajuste a dispersão da arma.
3. `duel.reaction_time_s` alto: o atraso do bot antes de atirar. `duel.crosshair_placement_deg` alto: a mira não está pré-posicionada.
4. `round.end_reason.time_ran_out` alto: os bots estão passivos demais.
5. `tactic.*`: `place_changes_per_player` e `dwell_s` baixos/altos demais indicam bots parados ou que trocam de região o tempo todo;
   `zone_share.*.Spawn` alto aos 40 s, bots que não saem do spawn; `first_contact_s` mostra se o ritmo do round (quando começa a luta) está certo.
6. Repita: simule, grave, compare. Guarde cada relatório (`--out reports/rodada-NN`) para ver a evolução.

## Recalibrar com novos dados

As metas são geradas das demos reais. Quando houver demos novas:

```bash
make refresh    # extrai, converte, regera perfis, regras, metas e modelo de time
```
O `generated_at` e o tamanho da amostra aparecem no topo de cada relatório.
