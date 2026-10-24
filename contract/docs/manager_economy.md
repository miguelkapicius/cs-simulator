# Economia do modo manager

O modo manager (contratar jogadores, pagar salários, subir de tier) tem três partes no contrato:

| Arquivo | O que é |
|---|---|
| `artifacts/manager_params.json` | Todos os números ajustáveis. Schema: `schemas/manager_params.schema.json` |
| `reference/manager_economy.py` | As fórmulas puras (só números e dicionários). A Unity porta isto |
| `test_vectors/manager_economy_vectors.json` | 485 casos em 14 grupos para conferir o port (tolerância 1e-9) |

O estado do mundo, o mercado com clubes do computador e o calendário não estão no contrato: são implementação de referência em `manager/` (ver `docs/manager-economy.md`, no repositório).

## Como portar e conferir

1. Carregue `manager_params.json` e use o bloco `params` como `prm`.
2. Implemente cada função de `manager_economy.py` com a mesma assinatura, sem arredondar (exceto onde o texto diz `int`).
3. Para cada grupo de `manager_economy_vectors.json`, aplique a função às entradas de `input` e compare com `expected` (inteiros e booleanos exatos; `double` com a tolerância do arquivo).
4. O arquivo traz `params_sha256`, o hash (JSON canônico com chaves ordenadas) dos parâmetros a que os casos se referem: se mudar, os vetores foram regerados para outros números.

Convenções: dinheiro é inteiro e `int(x)` trunca em direção a zero (em C#, `(long)x`). `0.5 ** x` é `Math.Pow(0.5, x)`. `tanh` é `Math.Tanh`.

## Funções

| Função | O que calcula |
|---|---|
| `salary_for(tier, skill, hype, prm)` | Salário mensal dentro da faixa do tier. Tier 1 usa a faixa `star` a partir da `skill` mínima de `salary_skill_range.star`. Posição na faixa = `blend.skill * skill_norm + blend.hype * hype/100` |
| `buyout_for(salary_month, hype, end_week, week, interested, prm)` | Salário anual x temporadas que restam (teto `max_seasons`) x `(1 + hype/hype_divisor)` x `(1 + interest_step * (interessados - 1))`. Zero quando o contrato acabou |
| `decay_hype(hype, weeks, prm)` | Meia-vida de `hype_half_life_weeks` semanas |
| `match_update(hype, form, rating, won, major, prm)` | Novo `(hype, form)` depois de uma partida; o Major multiplica a variação de hype |
| `weekly_wages(salaries_month)` | Soma dos salários mensais dividida por 4 |
| `weekly_revenue(tier, rank, prm)` | Patrocínio semanal do tier, ajustado linearmente pela posição no ranking (1 = melhor) |
| `sticker_payout(tier, hypes, prm)` | Repasse de stickers de um Major, proporcional ao hype médio; só o Tier 1 recebe |
| `can_afford(budget, weekly_wage_total, offer_salary_month, signing_bonus, prm)` | Depois do bônus, o caixa cobre `cash_reserve_weeks` semanas da folha já com o novo salário |
| `team_strength(club_tier, roster, prm)` | Média da `skill` dos 5 melhores, sem o coach, de 0 a 1; elenco vazio usa a média do tier |
| `role_term(role, skill, roster, prm)` | 1 se há vaga na função, 0,5 se ele entraria como titular de uma função cheia, 0 se seria reserva |
| `score_offer(player, offer_salary_month, club, roster, prm)` | Nota da oferta para o jogador: dinheiro, time, prestígio, função e reputação, com os pesos de `weights`. Estrelas ligam menos para dinheiro (`money_star_discount`) |
| `accepts(score, prm)` | O jogador aceita se a nota passar de `accept_threshold` |
| `scout_noise(world_seed, pid, level, key, width)` | Ruído uniforme fixo em `[-width, width]` (abaixo) |
| `scout_numbers(skill, hidden, pid, level, world_seed, prm)` | Estimativa de `skill` e atributos escondidos revelados pelo nível, limitados a 0..100 |

Entradas: `player = {tier, skill, hype, role}`, `club = {tier, prestige, reputation}`, `roster = [{role, skill}, ...]` (inclui o coach).

### Ruído do scouting

Ver o mesmo jogador de novo não pode sortear de novo, e o resultado tem de ser igual em qualquer linguagem. Por isso:

```
digest = sha256(utf8("<world_seed>:<pid>:<level>:<key>"))
u      = (inteiro big-endian dos 8 primeiros bytes de digest) / 2^64
ruído  = (2*u - 1) * width
```

Em C#, `ulong` para `double` arredonda para o mais próximo e a divisão por 2^64 é exata, então o resultado é idêntico ao do Python.

## Parâmetros

Todos em `manager_params.json`, bloco `params`. Os que as funções acima usam: `season_weeks`, `cash_reserve_weeks`, `salary_bands`, `salary_skill_range`, `salary_blend`, `weights`, `money_star_discount`,
`accept_threshold`, `role_cap`, `hype_half_life_weeks`, `hype_match`, `buyout`, `tier_sizes`, `sponsor_week`, `rank_factor`, `sticker_pool`, `generator.skill_mean` e `scouting`.
`generator`, `market` e `game` pertencem ao mundo do manager (geração de jogadores, mercado e calendário).

`make validate` confere o schema, que os pesos de `weights` somam 1, que as faixas de salário não se sobrepõem para cima e que os vetores batem com os parâmetros atuais.
Mudou um número? Rode `make manager-vectors`.

## Medido x palpite

- **Faixas de salário (US$ por mês):** Tier 1 estrela 50 mil a 100 mil, Tier 1 regular 15 mil a 50 mil, Tier 2 e 3 de 1 mil a 5 mil. Vêm de estimativas públicas (contratos reais são confidenciais).
- **Buyout:** limitado a 1,25 temporada de salário. Sem o teto, uma estrela saía por mais de US$ 5 milhões; o recorde individual conhecido é de cerca de US$ 1,1 milhão.
- **Palpite:** os pesos da decisão do jogador, as médias de `skill` por tier, os parâmetros de hype e o patrocínio por tier. Calibre-os jogando.
