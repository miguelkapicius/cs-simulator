# Contrato entre o algoritmo e a simulação 3D

Esta pasta é **tudo que a Unity precisa saber** sobre o algoritmo, e nada além disso. O algoritmo roda em Python, só no
desenvolvimento, e entrega **arquivos de dados**. O jogo não depende de servidor, de Python nem de internet.

```
 demos reais ─► pipeline (Python) ─► artifacts/*.json ─► Unity lê e aplica
                                                              │
        report.md ◄─ calibration (compare) ◄─ sim_log.jsonl ◄─┘  Unity grava
        "o que ajustar na mecânica"
```

Dois sentidos, e só dois:

| Sentido | O quê | Onde está definido |
|---|---|---|
| Algoritmo ➜ Unity | `player_profiles.json`, `game_rules.json`, `weapon_dynamics.json`, `team_model.json`, `tactics.json`, `tactics_playbook.json`, `elite_players.json` | `artifacts/`, `schemas/`, `docs/` |
| Unity ➜ Algoritmo | `sim_log.jsonl` (o que aconteceu na simulação) | `schemas/sim_log.schema.json`, `docs/sim_log.md` |

A ideia central: **os dados reais são a especificação**. A mecânica 3D é ajustada até que o log dela dê as mesmas estatísticas das
partidas reais. O comparador diz o quanto falta.

## O que tem aqui

| Pasta/arquivo | Para quê |
|---|---|
| `VERSION`, `CHANGELOG.md` | versão do contrato e o que mudou |
| `artifacts/player_profiles.json` | **como cada jogador joga**: reação, mira, precisão, duelos, estilo, posições |
| `artifacts/game_rules.json` | **como o CS2 funciona**: armas, dano, colete, economia, tempos, bomba, granadas |
| `artifacts/elite_players.json` | **os jogadores para mostrar no produto**: o mesmo comportamento de `player_profiles.json`, com codinome, país e idade ficcionais e **sem nome, steamid nem time reais** ([`docs/elite_players.md`](docs/elite_players.md)) |
| `reference/profile_synthesis.py` | **perfil de quem não tem demo**: parte de um jogador real da mesma função e ajusta pela habilidade e pelos atributos ([`docs/profile_synthesis.md`](docs/profile_synthesis.md)) |
| `artifacts/weapon_dynamics.json` | **como a arma se comporta ao atirar**: padrão e escala do recuo, reinício da rajada, penalidade de precisão, penetração |
| `artifacts/tactics.json` e `tactics_playbook.json` | **movimento e posicionamento** no nível de regiões: para onde o jogador vai, onde cada lado costuma estar, rotações, **probabilidade de plant por bombsite**, e as rotas de 599 rounds reais |
| `artifacts/team_model.json` | **decisões do time**: chance de vencer o round, tipo de compra, plano de ataque |
| `artifacts/calibration_targets.json` | **o que a simulação precisa reproduzir** (325 métricas do jogo real) |
| `sharded/` | **os mesmos dados em arquivos independentes por jogador, time e mapa**, com um manifesto: um confronto carrega só ~27% do total ([`docs/sharding.md`](docs/sharding.md)) |
| `schemas/` | JSON Schema de cada artefato e do log; define o formato exato |
| `docs/` | explicação de cada artefato, do log e da calibração |
| `test_vectors/*.json` | entradas e saídas esperadas do modelo de time e do recuo, para testar o C# |
| `examples/sim_log_example.jsonl` | 2 rounds reais no formato do log |
| `reference/*.py` | implementações de referência (Python puro) do modelo de time e do recuo |

## Por onde começar (checklist de integração)

1. **Carregar os artefatos** na Unity (de preferência as fatias de `sharded/`, pelo manifesto, para ler só o do confronto) com o Newtonsoft JSON (`com.unity.nuget.newtonsoft-json`; o `JsonUtility` não lê dicionários).
   Confira `contract_version`: recuse MAJOR diferente. Ver [`docs/conventions.md`](docs/conventions.md).
2. **Usar `game_rules.json`** na mecânica: dano, colete, cadência, velocidades, tempos da bomba, economia
   ([`docs/game_rules.md`](docs/game_rules.md)). É o que torna o jogo "CS" e não precisa de ajuste fino.
3. **Aplicar o recuo** de `weapon_dynamics.json`: padrão por bala, escala 2,0 e reinício da rajada, provado com `test_vectors/`
   ([`docs/weapon_dynamics.md`](docs/weapon_dynamics.md)).
4. **Marcar o mapa 3D com as regiões** de `tactics.json` e usar o movimento ([`docs/tactics.md`](docs/tactics.md)): `forecast` para o bot decidir
   para onde ir, e o playbook para reproduzir rounds reais. Exige a geometria do mapa.
5. **Usar `player_profiles.json`** para os bots: tempo de reação, onde a mira está antes de ver o inimigo, erro do primeiro tiro,
   quanto o jogador atira parado ([`docs/player_profiles.md`](docs/player_profiles.md)).
6. **Implementar o modelo de time** em C# e provar com `test_vectors/` que dá os mesmos números da referência
   ([`docs/team_model.md`](docs/team_model.md)).
7. **Gravar o `sim_log.jsonl`** ([`docs/sim_log.md`](docs/sim_log.md)). Comece pelos eventos de round, economia e kills; depois tiros, danos e avistamentos.
8. **Validar e comparar** ([`docs/calibration.md`](docs/calibration.md)):
   ```bash
   python -m calibration.validate_log sim/*.jsonl
   python -m calibration.compare sim/ --out reports/rodada-01
   ```
9. **Ajustar a mecânica** pelo relatório e repetir. Pronto quando não restar `FAIL` com 20 ou mais partidas simuladas.

## Regras de convivência

- **Nada de campo mudar de significado em silêncio.** Qualquer alteração de formato ou semântica sobe a versão
  (MAJOR quebra, MINOR acrescenta, PATCH renova dados). Está tudo no [`CHANGELOG.md`](CHANGELOG.md).
- **Os dados são regerados** quando há demos novas (PATCH). A Unity não deve copiar valores dos JSON para o código: leia sempre do arquivo.
- **Dúvida sobre o que um campo significa?** O schema e o `docs/` são a fonte; se estiverem ambíguos, é bug do contrato e deve ser corrigido lá.
- **Os artefatos são gerados, não editados à mão.** Para mudar um valor, mude o pipeline (`pipeline/`) e regere (`make refresh`).

## Verificar que o contrato está íntegro

```bash
make validate    # cada artefato contra o schema, vetores de teste contra a referência, log de exemplo
make test        # testes automatizados
```
