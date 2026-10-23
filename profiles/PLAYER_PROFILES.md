# Perfis de jogadores para a simulação (player_profiles.json)

Este documento descreve `player_profiles.json`: o perfil mecânico, de desempenho e de estilo
de cada jogador, medido em demos reais de CS2. A ideia é que cada bot da simulação na Unity
use esses números para **reagir, mirar, atirar, se mover e se posicionar como o jogador real**.
Os resultados (quem vence o duelo, o round) devem surgir da simulação, e não ser sorteados.

- **Fonte:** 28 mapas de 11 séries da FURIA (Thunderpick World Championship 2026, ESL Pro League S24 e StarLadder Fall 2026),
  com 599 rounds e 40 jogadores de 8 times. Foram analisados cerca de 67.800 tiros e 3.476 avistamentos de inimigos.
- **Cobertura por time:**
  - FURIA: 599 rounds, com cerca de 220 duelos e 270 reações por jogador.
  - BetBoom: 212 rounds. Aurora: 109. MOUZ: 80. Legacy: 62. PARIVISION: 61. Vitality: 39. 9z: 36.
  - Times com poucos mapas ficam com várias distribuições em `source: "baseline"`.
- **Gerado por:** `build_player_profiles.py` (Python, demoparser2). Basta rodar de novo quando houver mais demos.
- **Versão do formato:** `schema_version` = `"1.0"`. Confira esse campo ao carregar o arquivo.

## Como carregar na Unity

O arquivo usa dicionários (`by_distance."0-10m"`, `positions.<mapa>`, `accuracy.<classe>`), e o `JsonUtility`
da Unity **não lê dicionários**. Use o Newtonsoft JSON, pacote oficial `com.unity.nuget.newtonsoft-json`:

```csharp
var profiles = JsonConvert.DeserializeObject<PlayerProfilesFile>(File.ReadAllText(path));
// ou, para explorar sem classes: JObject.Parse(...)["players"][0]["mechanics"]["reaction_time_s"]["p50"]
```

## Estrutura

```
{
  schema_version, generated_at,
  source:   { matches[], total_rounds, parser, tickrate },
  units:    { distance: metros, angles: graus, time: segundos, speed: unidades Source/s },
  method:   { parâmetros usados nas medições },
  baseline: { mechanics, performance },   // média de todos os jogadores = fallback
  players: [
    { steamid, name, team, role_tags[],
      mechanics:   { ... },   // como mira/atira/reage → parâmetros do bot
      performance: { ... },   // resultados reais → usar para VALIDAR a simulação
      weapons:     { ... },   // preferência de armas
      positions:   { <mapa>: { CT|T: { time_share, position_at_20s } } } }
  ]
}
```

## Três tipos de valor

1. **Taxas**: `{ "value": 0.26, "n": 270, "shrunk": 0.2606 }`
   - `value` é a taxa medida e `n` é o tamanho da amostra.
   - **Use `shrunk`.** É a taxa suavizada em direção à média geral (`(acertos + 20 × média) / (n + 20)`).
     Com amostra pequena ela fica perto da média; com amostra grande, perto do valor do jogador.
2. **Distribuições**: `{ "p10", "p25", "p50", "p75", "p90", "mean", "n", "source" }`
   - Percentis em que o bot sorteia um valor a cada evento (veja "Como sortear" abaixo).
   - `source: "baseline"` indica que o jogador tinha menos de 30 amostras e recebeu a distribuição geral.
3. **Contagens e médias**: `kpr`, `adr` etc. Servem para comparar, não para sortear.

## mechanics: como usar cada campo no bot

| Campo | O que mede | Uso sugerido no bot |
|---|---|---|
| `reaction_time_s` | Tempo entre o inimigo aparecer (entrar na visão do bot) e o primeiro tiro na direção dele | Atraso antes de começar a atirar quando um inimigo fica visível. Sorteie um valor a cada avistamento. |
| `crosshair_placement.total_deg` / `horizontal_deg` / `vertical_deg` | Distância angular entre a mira e a cabeça do inimigo **no instante em que ele aparece**. Vertical positivo = mira abaixo da cabeça | Onde a mira do bot está "pré-posicionada" ao segurar um ângulo. Antes de reagir, aplique esse desvio em relação à cabeça do alvo. |
| `aim_error_first_bullet_deg` | Erro angular entre a mira e a cabeça do alvo no primeiro tiro de cada sequência | Dispersão humana da mira no primeiro tiro, somada ao spread da própria arma. |
| `accuracy.<classe>.overall` / `by_distance` / `by_spray_bullet` | Fração de tiros em combate que causaram dano, por classe de arma, por faixa de distância e pela posição da bala no spray | **Use para validar e calibrar.** Ajuste `aim_error` e recuo até a simulação reproduzir essas taxas. |
| `hitgroups.<classe>` | Onde os acertos caem: `head`, `chest`, `stomach`, braços, pernas | Valide a distribuição de acertos. Se a mecânica sorteia o ponto atingido, use direto. |
| `burst_length` | Quantas balas por sequência com armas automáticas | Quantas balas o bot dispara antes de soltar o gatilho ou reajustar. |
| `movement.still_shot_rate` | Fração de tiros dados quase parado (< 40 unidades/s, ou seja, counter-strafe) | Chance do bot parar antes de atirar. O resto dos tiros sai em movimento, com a penalidade de precisão da arma. |
| `movement.speed_at_shot` | Distribuição da velocidade no momento do tiro | Velocidade a sortear quando o bot atira em movimento. |
| `movement.crouch_shot_rate` / `airborne_shot_rate` | Fração de tiros agachado / no ar | Chance de agachar no duelo / de pular atirando. |
| `shoots_after_sighting_rate` | Fração de avistamentos em que o jogador atirou em até 2 s | Agressividade: chance de engajar em vez de esconder ou recuar. |
| `duels.win_rate` / `by_distance` | Quando o jogador vê um inimigo primeiro e alguém morre em até 3 s, a fração de vezes em que ele vence | **Validação:** a taxa de duelos simulados deve ficar perto disso. |

Classes de arma: `rifle` (AK, M4, Galil, FAMAS, AUG, SG), `awp`, `sniper_other` (Scout, autos), `pistol`, `smg`, `heavy` (escopetas, metralhadoras).
Faixas de distância: `0-10m`, `10-20m`, `20-30m`, `30m+`. Posição da bala no spray: `1`, `2-3`, `4-6`, `7+`.

## performance: o que a simulação deve reproduzir

`kpr`/`dpr`/`apr` (kills, mortes e assistências por round), `adr`, `kd`, `kast`, `headshot_kill_rate`,
`survival_rate`, `opening` (chance de participar do primeiro duelo do round e de vencê-lo), trades,
`first_contact_s` (quanto tempo de round passa até o primeiro combate; mede agressividade),
`utility` (granadas por round, flash assists, dano de utilitário) e `by_side` (CT e T separados).

Esses números não entram como parâmetro. São o **alvo da calibração**: simule muitos rounds com os bots,
calcule as mesmas métricas e compare.

## weapons, positions e role_tags

- `weapons.kill_share_by_class`: de onde vêm os kills. Os AWPers têm de 30% a 60% dos kills com AWP
  (molodoy 48%, zorte 53%, woxic 52%, ZywOo 32%).
  Use na decisão de compra (quem compra AWP).
- `positions.<mapa>.<CT|T>.time_share`: callouts onde o jogador passa mais tempo vivo.
  `position_at_20s` é onde ele costuma estar 20 s após o fim do freeze (a posição de setup).
  Use para escolher o destino inicial do bot. Os nomes (`BombsiteB`, `Underpass`, `SideAlley`...)
  são os callouts do CS2 (`last_place_name`). Mapeie-os para regiões ou volumes no mapa da Unity.
- `role_tags`: `awper`, `entry`, `support`, `lurker` ou `rifler`. São tags inferidas por heurística, apenas indicativas.

## Como sortear de uma distribuição (C#)

```csharp
// Interpolação linear entre percentis; nas pontas, extrapola até p0≈p10 e p100≈p90 + (p90-p75)
public static float SampleFromPercentiles(Dist d, System.Random rng) {
    float u = (float)rng.NextDouble() * 100f;
    float[] ps = { 0, 10, 25, 50, 75, 90, 100 };
    float[] vs = { Mathf.Max(0, d.p10 - (d.p25 - d.p10)), d.p10, d.p25, d.p50, d.p75, d.p90, d.p90 + (d.p90 - d.p75) };
    for (int i = 1; i < ps.Length; i++)
        if (u <= ps[i]) return Mathf.Lerp(vs[i - 1], vs[i], (u - ps[i - 1]) / (ps[i] - ps[i - 1]));
    return vs[vs.Length - 1];
}
// Exceção: crosshair_placement.vertical_deg pode ser negativo (mira acima da cabeça); não aplique Max(0, ...) nele.
```

Use um `System.Random` com semente controlada para conseguir reproduzir a simulação.

## Calibração (o mais importante)

```
perfil → bots na Unity → simular N rounds → log no formato abaixo → mesmas métricas → comparar com performance/accuracy/duels
```

Peça para a simulação gravar um log JSON com eventos no **mesmo formato** dos dados reais:

- **Tiros:** `tick`, `shooter`, `weapon`, `hit`, `target`.
- **Dano:** `attacker_steamid`, `user_steamid`, `weapon`, `hitgroup`, `dmg_health`.
- **Mortes:** `attacker_steamid`, `user_steamid`, `weapon`, `headshot`, `round_time`.

Assim o mesmo código Python mede o quanto a simulação está parecida com o CS real e
indica quais parâmetros ajustar.

## Coordenadas (para quando os mapas do CS2 estiverem importados)

- As demos usam unidades Source (1 unidade = 0,0254 m), com o eixo Z para cima. A Unity usa metros e o eixo Y para cima.
- Altura dos olhos usada nas medições: 64 unidades em pé (1,63 m) e 46 agachado (1,17 m).
- Os dados de posição completos estão em `data/<demo>/ticks.parquet` (8 amostras/s) e podem ser convertidos depois.

## Limitações e como os números foram medidos

- **Amostra desigual:** a FURIA tem muitos dados, mas os adversários têm de 36 a 212 rounds. Use sempre `shrunk` nas taxas.
  Para os jogadores com `source: "baseline"`, a distribuição é a média geral, e não a do jogador.
- **Visão:** vem do `approximate_spotted_by` do jogo, uma linha de visão aproximada (a do radar).
- **Tempo de reação inclui prefire:** p10 ≈ 0,03–0,05 s, quando o jogador já atirava no ângulo antes de o inimigo aparecer.
  Se a sua mecânica tiver prefire separado, considere usar p25 como piso.
- **Mira:** os ângulos são os do tick (64/s). No CS2 o tiro ocorre entre ticks (sub-tick), então em flicks rápidos
  o erro medido é aproximado. O recuo não está incluído no ângulo da mira.
- **Precisão:** "tiros em combate" são os tiros com a mira a menos de 10° de um inimigo vivo, ou que acertaram alguém.
  Tiros através de parede e smoke entram na conta.
- **Alcance dos dados:** todas as partidas envolvem a FURIA, então os adversários foram medidos sempre contra o mesmo time.
  Para jogadores que não estão no arquivo, use o `baseline` como perfil genérico de jogador profissional.
