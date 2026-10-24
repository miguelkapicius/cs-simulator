# Histórico do contrato

Versionamento semântico (ver `docs/conventions.md`): **MAJOR** quebra a Unity, **MINOR** só acrescenta, **PATCH** renova dados ou documentação.

## 1.7.1: pacote para embarcar no jogo, sem identidade real (2026-10-24)

Nenhum artefato mudou de formato; só ferramenta e documentação.

- `make package-game` (novo) gera `dist/cs-simulator-game-<versão>.zip` com **só dados de runtime**: `game_rules`, `weapon_dynamics`, `team_model`, `tactics`, `tactics_playbook`,
  `elite_players`, o código de `reference/`, `VERSION`, `MANIFEST.json` (sha256) e `PACKAGE.md`. Fora ficam `player_profiles.json`, `sharded/`, `examples/`, `test_vectors/`,
  `calibration_targets.json`, a documentação e o CHANGELOG, que têm nomes, steamids e times reais ou exemplos com eles.
- A sanitização troca os ids de rounds do playbook (que vinham do nome da demo, como `<time>-vs-<time>-m1-<mapa>-<hash>#1`) por `m<hash>#<n>`, mantendo o número do round e a unicidade, e troca os nomes de torneios das notas de compatibilidade de build por `evento`.
- **O build reprova** (e nenhum zip é criado) se qualquer arquivo ainda tiver steamid, nome de demo, torneio, time ou apelido de jogador reais. O apelido só conta como valor; como chave de JSON (`"max":`) é coincidência com uma palavra do jogo.
- `make package` continua igual e continua levando dados reais: serve ao desenvolvimento e à calibração e **não deve ir dentro de um build do jogo**.
- `docs/game_package.md` explica o que entra, o que fica fora e o que o detector garante e não garante.

## 1.7.0: perfis sintetizados para jogadores sem demo (2026-10-24)

Só acrescenta; nenhum artefato existente mudou de formato.

- `reference/profile_synthesis.py` (novo): `synthesize_profile(template, knobs)` parte do perfil medido de um jogador real da mesma função e devolve um perfil
  **no mesmo formato de `player_profiles.json`**, para a Unity ter um só caminho de código. Com os knobs em zero, o perfil sai igual ao template.
  - `gap` (pontos de `skill` abaixo do template) piora precisão, erro de mira, reação, tiro instantâneo e parar antes de atirar, e reduz `kpr`, `adr` e `kast`.
  - `aggression`, `utility` e `spread` dão o estilo: primeiro contato e tentativas de duelo, granadas e trocas de morte, e regularidade.
  - `knobs_for(skill, hidden, role, template_skill)` converte `temperament`, `communication` e `consistency` (60 = neutro) nos knobs; `style_for(role)` escolhe a função do template.
- `test_vectors/profile_synthesis_vectors.json` (60 casos): knobs aplicados aos templates de `elite_players.json`, com 19 campos conferidos (`make validate`).
- `docs/profile_synthesis.md`: como usar, e o que é medido e o que é hipótese.
- **Aviso:** os dados só têm jogadores de nível profissional. As inclinações do `gap` são hipóteses a calibrar contra o `kpr` e o `adr` da simulação.

## 1.6.0: jogadores de elite sem identidade real (2026-10-24)

Só acrescenta; `player_profiles.json` e todo o resto continuam iguais.

- `elite_players.json` (novo): um jogador por perfil real, com **codinome, país e idade ficcionais** e o comportamento medido intacto
  (`profile.mechanics`, `performance`, `weapons`, `positions`, `role_tags`). Também traz os atributos que o modo manager usa
  (`skill`, `hidden`, `hype`, `form`, `tier`). Não tem `name`, `steamid`, `team` nem o bloco `source` (que cita times e demos).
- Gerado com semente fixa (`pipeline/build_elite_players.py`, `make elite`), então é reproduzível.
- `make validate` confere o schema e varre o arquivo atrás de qualquer nome, steamid ou time reais (inclusive em texto solto).
- **Aviso:** `player_profiles.json` e as fatias de `sharded/players/` ainda carregam `name` e `steamid` reais. Para mostrar jogadores num produto, use `elite_players.json`.

## 1.5.0: arquivos independentes por jogador, time e mapa (2026-10-24)

Só acrescenta; os arquivos únicos de `artifacts/` continuam iguais.

- `sharded/` (novo): perfis por jogador, estatísticas por time e tática/playbook por mapa, em arquivos independentes, mais `manifest.json` com caminho, bytes e sha256 de cada um.
  Um confronto (mapa + 2 times) carrega só os globais, os 2 times, os jogadores deles e o mapa: FURIA × Legacy na Mirage são 19 arquivos, 603 KB (27% do total).
- Referência `reference/manifest.py` (`match_files`, `players_of`, `all_files`) e `test_vectors/manifest_vectors.json` (196 confrontos).
- `make validate` confere hashes e que as fatias remontam exatamente os arquivos únicos originais.
- Previsto para a próxima MAJOR: aposentar os arquivos únicos de perfis e tática e entregar só as fatias.

## 1.4.0: reação x prefire nos perfis (2026-10-23)

Só acrescenta; `reaction_time_s` e todo o resto continuam como estavam.

- `player_profiles.json`: novo bloco `mechanics.engagement` (opcional no schema, presente em todos os jogadores e na média geral). Separa, quando um inimigo
  passa a ser visível, os desfechos **instantâneo** (tiro de 0,5 s antes a 0,1 s depois: o jogador já estava no ângulo), **atrasado** (reação de verdade) e
  **sem tiro**, por faixa do erro da mira nesse instante, mais `fired_before_visible`, `delayed_reaction_s` (mediana 0,22 s) e, na média geral, `flick_model`.
- **Aviso sobre o campo antigo:** `reaction_time_s` mistura tiros instantâneos com reações; seu p10 (~0,03 s) é impossível como reação. Use `engagement`.
- Métricas de calibração `duel.engage.*`, `duel.delayed_reaction_s.*` e `duel.fired_before_visible` (de 308 para 325 métricas).
- `pipeline/combat.py`: `engagement_timing`; `docs/player_profiles.md` ganhou a seção "engagement" com um trecho em C#.

## 1.3.0: decisão de bombsite (2026-10-23)

Só acrescenta; nada que as versões anteriores entregaram mudou de formato.

- `tactics.json` ganhou `site_decision`:
  - `site_probability`: probabilidade de plant em cada bombsite a partir de quantos Ts e CTs há em cada zona (AUC 0,79 a 0,86 em partidas inéditas);
  - `site_switch`: chance de o T abandonar o bombsite em que estava comprometido aos 30 s (58% em desvantagem de 2 ou mais, 4% com vantagem de 3 ou mais);
  - `pre_contact_check`: o T acaba no lado com menos defensores mesmo nos rounds sem nenhuma luta antes (coef. −0,47; IC 95% −0,88 a −0,15 aos 20 s);
  - `team_effects`: a equipe quase não muda a preferência de bombsite (p = 0,78) nem, de forma clara, a defesa do CT (p = 0,08).
- Referência `plant_site_probability` e `site_switch_probability` em `reference/tactics.py` e ~440 novos vetores de teste.
- Métricas de calibração `tactic.site_switch_rate` e `tactic.commit_A_share`.
- **Correção de texto da 1.2.0:** a nota dizia que os 40 s iniciais de um round "não preveem o bombsite do plant". O que não funcionou foi o
  agrupamento k-means; a contagem de Ts e CTs por zona prevê bem. `findings` e `docs/tactics.md` foram corrigidos.

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
