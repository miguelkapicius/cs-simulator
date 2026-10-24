# Perfis sintetizados (profile_synthesis)

Os jogadores de `elite_players.json` têm perfil medido em demos. Os demais (ligas menores, jogadores gerados pelo modo manager) não têm demo.
Para eles, `reference/profile_synthesis.py` monta um perfil **no mesmo formato**, partindo de um jogador real da mesma função. O bot usa o perfil do mesmo jeito,
sem caminho de código especial.

## Entradas

- **template:** o `profile` de um jogador de `elite_players.json` cuja `role_tags` contém o estilo da função (`style_for`: `awper`, `entry`, `lurker`, `support`, `rifler`; o `igl` usa `support`; o `coach` não joga).
- **knobs:** quatro números.

| Knob | Faixa | Vem de | Efeito |
|---|---|---|---|
| `gap` | -15 a 60 | `skill` do template menos `skill` do jogador | Piora a mecânica (abaixo) |
| `aggression` | -1 a 1 | `temperament` | Primeiro contato mais cedo (até -25%), mais tentativas de duelo (até +50%), mais tiros após avistar (até +8 pontos) |
| `utility` | -1 a 1 | `communication` | Granadas por round, trocas de morte e `traded_death_rate` (até ±40%) |
| `spread` | -1 a 1 | `consistency` (invertido) | Alarga as distribuições em torno da mediana (até ±35%), sem mover a mediana |

`knobs_for` usa 60 como valor neutro dos atributos (20 e 100 saturam em -1 e 1). O `igl` ganha `aggression` -0,25 e `utility` +0,3.

## O que o `gap` muda, por ponto

| Medida | Efeito por ponto de `gap` | Limites |
|---|---|---|
| Taxas de acerto e `headshot_kill_rate` | -1,2% | 0,35 a 1,15 |
| Erro angular da mira e do primeiro tiro | +1,8% | |
| Tempo de reação (`delayed_reaction_s`) | +1,0% | |
| Chance de tiro instantâneo | -1,2%; 70% do que se perde vira reação atrasada, 30% vira "sem tiro" | 0,3 a 1,1 |
| `still_shot_rate` | -0,6% | 0,6 a 1,1 |
| `kpr` / `adr` / `kast` | -1,0% / -0,8% / -0,4% | |
| `dpr` | +0,6% | |

`positions`, `weapons` e `burst_length` não mudam: vêm do template e dão o estilo de ocupar o mapa e de escolher arma.

## Medido x hipótese

- **Medido:** as diferenças de estilo entre funções (por exemplo, o `entry` tem primeiro contato mediano de 29 s e o `lurker` de 50 s; o `support` joga 0,86 flash por round, contra 0,50 do rifler).
- **Hipótese:** tudo o que o `gap` faz. Os dados só têm profissionais, e entre eles a correlação da `skill` com a mecânica fica entre 0,0 e 0,4. As inclinações são monotônicas e limitadas, mas
  devem ser calibradas: simule os bots, calcule `kpr` e `adr` e compare com `performance` do perfil sintetizado.

## Verificação

`test_vectors/profile_synthesis_vectors.json` traz 60 casos (5 estilos x 12 combinações de knobs) com 19 campos esperados cada (tolerância 1e-5). `make validate` roda a referência contra eles.
O perfil sintetizado leva `"synthetic": true` na raiz.
