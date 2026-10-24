# elite_players.json

Os jogadores de comportamento real, prontos para um produto: **sem nome, steamid nem time reais**.

## Para que serve

`player_profiles.json` descreve como cada jogador joga, mas é indexado por `steamid` e tem `name` e `team` reais. Isso serve para calibrar, não para mostrar.
`elite_players.json` é a versão para o jogo: o comportamento é o mesmo, a identidade é ficcional.

## Campos de cada jogador

| Campo | O que é |
|---|---|
| `pid` | Id estável (`e00`, `e01`...), na ordem de `player_profiles.json`. Use no lugar do `steamid` |
| `codename`, `country`, `age` | Identidade ficcional, sorteada com a semente do arquivo (`seed`) |
| `role` | `awper` ou `rifler` |
| `tier`, `skill`, `hidden`, `hype`, `form` | Atributos do modo manager (`skill` vem do percentil de ADR entre os perfis) |
| `profile` | O comportamento medido: `role_tags`, `mechanics`, `performance`, `weapons`, `positions`, com a mesma semântica de [`player_profiles.md`](player_profiles.md) |

O bloco `source` do arquivo original (times, demos, placares) **não** é copiado.

## Garantias

- O schema (`schemas/elite_players.schema.json`) proíbe `name`, `steamid` e `team` em cada jogador.
- `make validate` procura no arquivo inteiro qualquer nome, steamid ou time dos perfis reais, e qualquer número de 17 dígitos.
- A semente é fixa: gerar de novo com os mesmos perfis dá o mesmo arquivo (a data em `generated_at` muda).

## Limites

- A combinação de atributos (função, estatísticas, idade) pode lembrar um jogador real para quem conhece bem os dados. Os nomes mudam; a revisão jurídica dessa combinação é de quem publica o produto.
- Quando chegam demos novas, rode `make profiles` e depois `make elite`: o conjunto de jogadores e a ordem dos `pid` podem mudar.
