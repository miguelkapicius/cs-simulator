# Histórico do contrato

Versionamento semântico (ver `docs/conventions.md`): **MAJOR** quebra a Unity, **MINOR** só acrescenta, **PATCH** renova dados ou documentação.

## 1.2.0: camada tática (2026-10-23)

Só acrescenta; tudo o que as versões anteriores entregaram continua válido.

- `tactics.json` (novo): por mapa, regiões com zona (A/B/Mid/Spawn), grafo de movimento, ocupação por tempo, **previsão de posição**
  (onde o jogador estará em 5 s e 10 s; +53% a +58% sobre a ocupação em partidas inéditas), pós-plant, rotação do CT, primeiro contato
  e utilitários.
- `tactics_playbook.json` (novo): as rotas dos cinco jogadores de cada lado nos 599 rounds reais, para reproduzir rounds inteiros.
- Evento `positions` no log da simulação (opcional, recomendado): a região de cada jogador vivo a 2 Hz ou mais.
- Métricas de calibração `tactic.*` (zona por tempo, primeiro contato, movimento e permanência); as metas passaram de 207 para 306 métricas.
  Em partidas reais inéditas elas dão 0 FAIL e 0,7% de WARN.
- Referência `reference/tactics.py` e `test_vectors/tactics_vectors.json` (≈ 1.300 casos).
- **Resultado negativo registrado:** agrupar rounds em "planos" (k-means) não previu o bombsite do plant com os 40 s iniciais de partidas
  inéditas e não melhorou a previsão de posição, então não há planos no contrato (ver `docs/tactics.md`).
- `real_to_simlog` passou a incluir `positions` (2 Hz) nos logs das demos.

## 1.1.0: dinâmica das armas (2026-10-23)

Só acrescenta; nada que a 1.0.0 entregou mudou de formato ou de significado.

- `weapon_dynamics.json` (novo): padrão de recuo bala a bala de 8 armas automáticas, escala do recuo (2,05; IC 95% 1,99 a 2,12),
  regra de reinício da rajada, penalidade de precisão por bala e penetração inferida. Com schema, referência
  (`reference/weapon_dynamics.py`) e `test_vectors/weapon_dynamics_vectors.json`.
- Compatibilidade: um artefato de MINOR/PATCH mais antigo continua válido (mesmo MAJOR).

**Correções de dados em `game_rules.json`** (formato igual, valores da validação do dano mudaram)
- O hitgroup `generic` é só dano de fogo e de granada, nunca de arma. A explicação anterior ("tiro que atravessou parede") estava
  errada, e a causa era um erro nosso: o dano de molotov/HE era atribuído à arma que o jogador segurava. Corrigido.
- Fogo amigo (dano reduzido a 33%) deixou de entrar na validação da fórmula de dano.
- **Pescoço não é cabeça:** a fórmula de dano documentada tratava o pescoço como a cabeça (×4, protegido pelo capacete). Medido nas demos,
  o pescoço é ×1,0 e protegido pelo colete (92% de acerto exato em 52 acertos, contra 0% antes). Corrigidos `game_rules.json`,
  `docs/game_rules.md` e o trecho de C#. **Quem já implementou a fórmula precisa ajustar o pescoço.**

## 1.0.0: primeiro contrato formal (2026-10-23)

Reúne tudo o que existia solto e fecha o ciclo de calibração.

**Artefatos (algoritmo ➜ Unity)**
- `player_profiles.json`, `game_rules.json`: agora com `contract_version` (o `schema_version` continua `"1.0"`).
  `game_rules.json` ganhou `weapon_classes` (classe de cada arma, usada nos perfis e nas métricas).
- `team_model.json` (novo): chance de vencer o round, tipo de compra e plano de ataque do T, com vetores de teste.
- `calibration_targets.json` (novo): 207 métricas do jogo real e o ruído entre partidas de cada uma.

**Log (Unity ➜ algoritmo)**
- `sim_log.jsonl` (novo): 11 tipos de evento, com schema, validador e exemplo.
  Campo `freeze_end.players[].equip_before` obrigatório (equipamento carregado antes da compra).

**Ferramentas**
- `calibration.validate_log`, `calibration.compare`: validação do log e relatório simulação vs. real.

**Correções de dados** (valores dos artefatos mudaram em relação à entrega anterior)
- Plants feitos depois do fim do round (2,5% dos plants) deixaram de contar como `bomb_planted`.
- Perfis e regras recalculados com 28 partidas (599 rounds) em vez de 5.

**Mudança de caminhos:** os arquivos entregues antes em `profiles/` e `game_rules/` agora estão em `contract/artifacts/`
e `contract/docs/`.
