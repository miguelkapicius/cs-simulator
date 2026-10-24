# Pacote para embarcar no jogo (`make package-game`)

O contrato nasceu para calibrar a simulação com demos reais, então boa parte dele carrega **nomes, steamids e times reais**. Isso é normal no desenvolvimento e não pode ir para o jogo.
Há dois pacotes:

| | `make package` | `make package-game` |
|---|---|---|
| Arquivo | `cs-simulator-contract-<versão>.zip` | `cs-simulator-game-<versão>.zip` |
| Para quê | Desenvolvimento e calibração na Unity | **Dentro do build do jogo** |
| Dados reais (nomes, steamids, times) | Sim | **Não** |
| Conteúdo | Contrato inteiro: artefatos, schemas, docs, vetores, exemplos, fatias | Só artefatos de runtime e código de referência |

## O que entra no pacote do jogo

- `artifacts/`: `game_rules`, `weapon_dynamics`, `team_model`, `tactics`, `tactics_playbook` e [`elite_players`](elite_players.md) (os jogadores com identidade ficcional).
- `reference/`: o código de referência (Python) que a Unity porta, inclusive [`profile_synthesis`](profile_synthesis.md).
- `VERSION`, `MANIFEST.json` (tamanho e sha256 de cada arquivo) e `PACKAGE.md`.

## O que fica de fora, e por quê

| Fora | Motivo |
|---|---|
| `player_profiles.json` e `sharded/` | Indexados por `steamid`, com `name` e `team` reais |
| `examples/` e `test_vectors/` | Têm steamids e times reais |
| `calibration_targets.json` | Só serve à calibração |
| `docs/` e `CHANGELOG.md` | Os exemplos citam jogadores e times reais |

## O que a sanitização muda nos artefatos

- Ids de rounds do `tactics_playbook` vinham do nome da demo (`<time>-vs-<time>-m1-<mapa>-<hash>#1`). Viram `m<hash>#<n>`: o número do round e a unicidade ficam, o nome some.
- Nomes de torneios nas notas de compatibilidade de build de `game_rules` viram `evento`.

## O que o detector garante

Antes de gravar o zip, **todo arquivo** é varrido atrás de:

| Achado | Exemplo |
|---|---|
| `steamid` | número de 17 dígitos que começa com `7656` |
| Nome de arquivo de demo | `qualquer.dem` |
| Torneio | Thunderpick, ESL, StarLadder, BLAST, PGL, IEM |
| Time | qualquer time dos perfis, em qualquer posição do texto |
| Apelido de jogador | qualquer apelido dos perfis, **como valor**; como chave de JSON (`"max":`) é coincidência com uma palavra do jogo e é ignorado |

Se achar qualquer coisa, o build falha, mostra o arquivo e o achado, e **nenhum zip é criado**.

## O que o detector não garante

- Ele só conhece as identidades que estão em `player_profiles.json` na hora do build. Rode `make profiles` com todas as demos antes de gerar o pacote.
- Ele não vê identidade que não esteja em texto (por exemplo, alguém reconhecendo um time pela forma de jogar). A combinação de comportamento e atributos dos jogadores de elite continua precisando de revisão jurídica de quem publica.
- Torneios fora da lista acima passariam. Se aparecer um novo nas demos, acrescente-o em `EVENT_RE` (`pipeline/package_game.py`).

## Na Unity

Embarque no build só o conteúdo do `cs-simulator-game-<versão>.zip`. O pacote de desenvolvimento deve ficar fora de `StreamingAssets`, `Resources` e de qualquer pasta incluída no build.
