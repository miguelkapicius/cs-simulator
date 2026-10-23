# Camada de time (`team_model.json`)

As decisões do time que o algoritmo responde e a Unity usa: **quanto cada lado tem de chance de vencer o round agora**,
**que tipo de compra o time faz** e **como o T ataca**. É dado, não código: a Unity lê o JSON e aplica as fórmulas.

- Schema: [`schemas/team_model.schema.json`](../schemas/team_model.schema.json)
- Referência executável: [`reference/team_model.py`](../reference/team_model.py) (só Python padrão, 100 linhas)
- **Vetores de teste:** [`test_vectors/team_model_vectors.json`](../test_vectors/team_model_vectors.json)

## Como a implementação em C# prova que está certa

O arquivo de vetores tem entradas e a saída esperada (`expected`) calculada pela referência. A versão em C# deve devolver os
mesmos números (tolerância `1e-9`) para as mesmas entradas. Se bater em todos, a lógica está igual; se algum falhar, o
vetor aponta exatamente qual caso. É o teste de aceitação do contrato desta camada.

```
test_vectors/team_model_vectors.json
  win_probability  [{input:{...}, expected: 0.4631...}, ...]   (≈ 80 casos, inclui regras fixas e mapa desconhecido)
  buy_distribution [{input:{side,round,avg_resources_before}, expected:{eco,force,full}}, ...]
  round_plan       [{input:{map,t_buy}, expected:{plant_rate,site_a_share,plant_time_s}}, ...]
```

## 1. Chance de vencer o round (`win_probability`)

**Quando usar:** a qualquer momento do round, para o bot decidir se arrisca, salva a arma ou tenta retomar.

Entrada (`state`):

| Campo | Significado |
|---|---|
| `map` | id do mapa. Mapa desconhecido usa `unknown_map_intercept` |
| `round_time_s` | segundos desde o fim do freeze time |
| `alive_ct`, `alive_t` | jogadores vivos de cada lado |
| `bomb_planted` | a bomba foi plantada |
| `time_since_plant_s` | segundos desde o plant (só se plantada) |
| `ct_equip_avg`, `t_equip_avg` | valor médio de equipamento por jogador de cada lado, **medido no fim do freeze time** |

Saída: `p_ct`, a probabilidade do CT vencer (a do T é `1 - p_ct`).

```
Regras fixas:   alive_ct == 0                      -> 0.0
                alive_t == 0 e bomba não plantada  -> 1.0
Senão:          p_ct = sigmoid( intercept + map_intercepts[map] + Σ coefficients[f] · f )
```
As 8 features `f` (definidas em `features` no JSON e em `reference/team_model.py`):
`alive_diff`, `alive_ct`, `alive_t`, `planted`, `planted_x_alive_diff`, `clock_unplanted`, `clock_planted`, `equip_log_ratio`.
O relógio é a fração que resta do timer do round (115 s) antes do plant ou do timer da C4 (41 s) depois dele.

```csharp
static double Sigmoid(double x) => x >= 0 ? 1 / (1 + Math.Exp(-x)) : Math.Exp(x) / (1 + Math.Exp(x));

public double WinProbability(TeamModel m, State s) {
    var w = m.WinProbability;
    if (s.AliveCt <= 0) return 0.0;
    if (s.AliveT <= 0 && !s.BombPlanted) return 1.0;
    double planted = s.BombPlanted ? 1 : 0, diff = s.AliveCt - s.AliveT;
    double clock = s.BombPlanted ? (w.Clock.BombS - s.TimeSincePlantS) / w.Clock.BombS
                                 : (w.Clock.RoundS - s.RoundTimeS) / w.Clock.RoundS;
    clock = Math.Min(1, Math.Max(0, clock));
    double ratio = Math.Log((s.CtEquipAvg + w.EquipOffset) / (s.TEquipAvg + w.EquipOffset));
    double x = w.Intercept + (w.MapIntercepts.TryGetValue(s.Map, out var mi) ? mi : w.UnknownMapIntercept)
             + w.Coef["alive_diff"] * diff + w.Coef["alive_ct"] * s.AliveCt + w.Coef["alive_t"] * s.AliveT
             + w.Coef["planted"] * planted + w.Coef["planted_x_alive_diff"] * planted * diff
             + w.Coef["clock_unplanted"] * (1 - planted) * clock + w.Coef["clock_planted"] * planted * clock
             + w.Coef["equip_log_ratio"] * ratio;
    return Sigmoid(x);
}
```

**Qualidade:** validado por partida (o modelo nunca viu a partida que está avaliando) em 55 mil estados de 28 partidas:
perda logarítmica **0,483** (chute 50%: 0,693; tabela só com vivos e plant: 0,509) e AUC **0,84**.
As probabilidades previstas batem com o que acontece (curva de calibração em `evaluation.calibration`).

**O que o modelo NÃO vê:** posições, vida, utilitários, kit de defuse, habilidade dos jogadores. Quem for mais ou menos
habilidoso que a média deve ser tratado na mecânica, não aqui. Os estados são de 1 em 1 segundo de partidas profissionais,
então não extrapole para situações que nunca acontecem no profissional.

## 2. Compra (`buy_distribution`)

**Quando usar:** uma vez por time, no início da fase de compra, para sortear o tipo de compra.

Entrada: `side`, `round` (número do round) e `avg_resources_before`, a média por jogador de **dinheiro + valor do equipamento
que ele já carrega** antes de comprar (`freeze_end.money_before + equip_before`).
Saída: probabilidades de `eco`, `force` e `full`. Round 1 e 13 devolvem `{"pistol": 1.0}`.

Os tipos são definidos pelo equipamento médio por jogador no fim do freeze time:
`pistol` (rounds 1 e 13), `eco` < 1500, `force` < 3500, `full` a partir de 3500.

Depois de sortear o tipo, `buy.loadouts[lado][tipo]` diz **o que cada jogador leva**: chance de colete, capacete e kit,
quais armas principais e pistolas (`primary_share`, `secondary_share`), AWPs por time e granadas por jogador.
Sorteie o equipamento de cada bot respeitando o dinheiro dele.

Exemplo de leitura (T): com recursos de 3.000 por jogador, `eco` 26%, `force` 67%, `full` 7%; com 5.000, `full` 99%.

## 3. Plano de ataque do T (`round_plan`)

**Quando usar:** no início do round, para decidir se o T vai plantar, em qual bombsite e quando.

Entrada: `map` e `t_buy`. Saída: `plant_rate` (chance de plantar, dada a compra), `site_a_share` (chance do bombsite ser o A)
e `plant_time_s` (percentis do tempo de round em que o plant acontece). Mapas sem dados usam o `overall`.

## Limites desta versão

- **Dados:** 28 partidas, 599 rounds, quase todas com a FURIA. Mapas com poucos rounds (Anubis, 21) têm estimativas frouxas;
  `round_plan` é suavizado em direção à média geral, mas desconfie das diferenças entre mapas pequenos.
- **Ainda não há** decisões de salvar, rotacionar ou retomar: o modelo dá a chance de vitória, e a regra
  ("salva se `p_ct` < X") é escolha de design da Unity. Aprender essas regras a partir das posições nas demos é a camada tática.
