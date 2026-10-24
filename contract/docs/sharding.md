# Arquivos independentes por jogador, time e mapa (`sharded/`)

Os artefatos em `artifacts/` são arquivos únicos com tudo dentro (todos os jogadores, todos os mapas). Para um jogo isso carrega dados que
ninguém vai usar. A pasta `sharded/` entrega **os mesmos dados em arquivos pequenos e independentes**, e um manifesto diz quais carregar.

- Manifesto: [`sharded/manifest.json`](../sharded/manifest.json) · Schema: [`schemas/manifest.schema.json`](../schemas/manifest.schema.json)
- Referência: [`reference/manifest.py`](../reference/manifest.py) · **Vetores de teste:** [`test_vectors/manifest_vectors.json`](../test_vectors/manifest_vectors.json) (196 confrontos)

## Organização

```
sharded/
  manifest.json                    índice: caminho, bytes e sha256 de cada arquivo
  global/
    profiles_baseline.json         a média geral dos perfis (usada onde um jogador tem poucas amostras)
    tactics_global.json            dados táticos que valem para qualquer mapa (site_decision, convenções)
  teams/<time>.json                elenco e estatísticas descritivas do time, por mapa
  players/<steamid>.json           o perfil completo de um jogador
  maps/<mapa>/tactics.json         regiões, grafo, previsão de posição, pós-plant, rotação, utilitários do mapa
  maps/<mapa>/playbook.json        rotas dos rounds reais do mapa
```
Os dados globais já existentes (`artifacts/game_rules.json`, `weapon_dynamics.json` e `team_model.json`) são **referenciados no lugar**: o
manifesto aponta para eles, não há cópia. Os caminhos do manifesto são relativos a `contract/`.

## O que um confronto carrega

Um confronto é **mapa + dois times**. A regra (implementada em `match_files` na referência):

```
global (5 arquivos)  +  os 2 times  +  os jogadores desses times  +  tática e playbook do mapa
```

Exemplo real: **FURIA × Legacy na Mirage** = 19 arquivos, **603 KB, 27% do total** (2,2 MB):
os 5 globais (183 KB), as fatias de FURIA e Legacy, os 10 jogadores (9 a 12 KB cada) e a Mirage (tática 78 KB + playbook 230 KB).
Ficam de fora os outros 6 times, os outros 30 jogadores e os outros 6 mapas. Qualquer confronto carrega entre 381 e 670 KB.

```csharp
var manifest = Json.Load<Manifest>("sharded/manifest.json");
foreach (var path in Manifest.MatchFiles(manifest, "de_mirage", "FURIA", "Legacy"))   // lista ordenada
    cache.GetOrLoad(path, manifest.Sha256Of(path));                                   // só relê o que mudou de hash
```

## Independência

- **Entre jogadores:** cada arquivo de jogador tem o perfil inteiro; nenhum depende de outro jogador.
- **Entre times:** o arquivo do time só lista o elenco (steamids) e as estatísticas dele.
- **Entre mapas:** a tática e o playbook de um mapa não referenciam outro mapa.
- **Acrescentar dados não muda um confronto não relacionado:** novos times, jogadores e mapas entram no manifesto como arquivos novos;
  `match_files` de um confronto existente devolve a mesma lista (há um teste para isso).
- **Cache:** cada arquivo tem `sha256`. A geração é reprodutível (rodar duas vezes dá os mesmos hashes), então a Unity só precisa reler os arquivos cujo hash mudou.

**O que ainda é compartilhado** (e por isso pode mudar quando entram demos novas):
- Os 5 arquivos globais, que valem para qualquer confronto.
- Os valores `shrunk` dos perfis, que são suavizados em direção à média geral (`profiles_baseline`). Quando a média muda, os valores suavizados de todos os jogadores
  mudam um pouco, mesmo os que não jogaram nas demos novas. Isso não afeta o que um confronto carrega, só quais arquivos mudam de hash a cada atualização.

## Um time ou jogador que não está no manifesto

`match_files` falha com `KeyError` e o nome do que faltou. Na Unity, um jogador sem arquivo deve usar a média geral (`global/profiles_baseline.json`); um mapa
sem arquivo não tem tática nem playbook (use a mecânica sem a camada tática).

## Integridade (`make validate`)

Para cada arquivo do manifesto: existe, tem o tamanho e o sha256 declarados. E a verificação mais forte: **remontando as fatias, obtém-se exatamente os
arquivos únicos originais** (perfis, tática e playbook). Também confere que cada jogador pertence a exatamente um time e roda os vetores de teste.

## Arquivos únicos e fatias

Os dois formatos existem lado a lado e têm o mesmo conteúdo; os arquivos únicos (`artifacts/player_profiles.json`, `tactics.json`, `tactics_playbook.json`)
continuam sendo a fonte, e as fatias são geradas a partir deles (`make shards`). Quem já usa os arquivos únicos não precisa mudar nada.
A previsão é aposentar os arquivos únicos de perfis e tática na próxima versão MAJOR, deixando as fatias como o formato de entrega.

## Estatísticas do time (`teams/<time>.json`)

Elenco (steamid, nome, papéis, rounds) e, por mapa: rounds de CT e de T, taxa de vitória em cada lado, tipos de compra, taxa de plant e fração no bombsite A.
São descritivas. Com 28 partidas a equipe quase não muda a preferência de bombsite do T (p = 0,78) nem, de forma clara, a defesa do CT (p = 0,08;
ver `tactics.json` → `site_decision.team_effects`), então não trate diferenças pequenas entre times, ou com poucos rounds, como estilo de jogo.

## Quando entrarem mais demos

`make refresh` regera tudo, inclusive as fatias (`make shards`), e `make validate` confere o resultado. Times e mapas novos aparecem no manifesto sozinhos.
