# Economia do modo manager

Implementação de referência em Python da economia do modo manager: o jogador cria um clube de Tier 3, contrata jogadores, paga salários e sobe de tier disputando o mercado com clubes do computador.
Não faz parte do contrato com a Unity (`contract/` não muda). O design e as decisões estão em `docs/superpowers/specs/2026-10-24-manager-economy-design.md`.

## Módulos (`manager/`)

| Módulo | Responsabilidade |
|---|---|
| `models.py` | `Player`, `Club`, `Contract`, `Offer`, todos serializáveis em JSON |
| `params.json` / `params.py` | Todos os números ajustáveis (faixas de salário, pesos, buyout, calendário) |
| `identity.py`, `elite.py` | Codinomes e países ficcionais; os 40 jogadores de comportamento real com a identidade trocada |
| `generate.py` | Jogadores gerados por tier, com a cauda de talento jovem escondido |
| `valuation.py` | Salário, buyout, decaimento de hype e efeito das partidas |
| `finance.py` | Folha, patrocínio, stickers dos Majors e regra da reserva de caixa |
| `decision.py` | Como o jogador escolhe entre ofertas (dinheiro, time, prestígio, função, reputação) |
| `market.py` | Mercado semanal com clubes do computador, buyouts e janelas |
| `scouting.py` | Informação imperfeita: estimativa com ruído fixo e atributos escondidos por nível |
| `calendar.py`, `game.py`, `world.py` | Semanas, temporada de 48 semanas, promoção e rebaixamento, ofertas e salvamento |
| `sim.py` | Simulação de fumaça (`make manager-sim`) |

## Como ajustar

Todo valor monetário e todo peso fica em `manager/params.json`. As faixas de salário seguem estimativas públicas (Tier 1 estrela $50 mil a $100 mil por mês, regular $15 mil a $50 mil, Tier 2 e 3 $1 mil a $5 mil). Contratos reais são confidenciais, então trate esses números como ponto de partida.
O buyout é limitado a 1,25 temporada de salário; sem esse teto, uma estrela saía por mais de $5 milhões, contra um recorde real de cerca de $1,1 milhão.

## Identidade ficcional

- Nenhum `name` nem `steamid` real entra em `manager/`: `tests/test_manager_identity.py` e `tests/test_manager_world_integrity.py` conferem isso.
- O comportamento dos 40 jogadores de elite vem dos perfis reais. Idade, país e histórico são sorteados.
- Revisão jurídica final da combinação de atributos é responsabilidade do dono do projeto.

## Limites conhecidos

- As partidas semanais usam um modelo simples de força do time (`game._play_week`). Quando a Unity entregar resultados reais, esse é o único ponto a trocar.
- Clubes do computador não compram jogadores do clube do jogador.
- Clubes do computador nunca quebram (patrocinador de emergência); o clube do jogador pode ficar no vermelho.
