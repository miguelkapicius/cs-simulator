# Dinâmica das armas (`weapon_dynamics.json`)

`game_rules.json` diz **quais são** os parâmetros de cada arma (dano, cadência, dispersão base). Este arquivo diz **como a arma
se comporta ao atirar**, medido nas demos: para onde a mira sobe durante uma rajada, quando a rajada reinicia, quanto a precisão
piora e quanto dano se perde ao atravessar uma parede.

- Schema: [`schemas/weapon_dynamics.schema.json`](../schemas/weapon_dynamics.schema.json)
- Referência executável: [`reference/weapon_dynamics.py`](../reference/weapon_dynamics.py)
- **Vetores de teste:** [`test_vectors/weapon_dynamics_vectors.json`](../test_vectors/weapon_dynamics_vectors.json) (≈ 180 casos)
- Dados: 28 partidas, cerca de 68 mil tiros.

## 1. Recuo (`recoil`)

### O que foi medido
Em cada tiro, o valor que o próprio jogo guarda para o recuo (o *aim punch*). A tabela `patterns` traz, **bala a bala**, o punch
médio da arma numa rajada contínua. É determinístico: o desvio entre rajadas é de ~0,15°, só ruído de medição.

```
ak47          bala:   1     2     3     4     5     6     7     8     9    10    11    12
              pitch: 0.00 -0.10 -0.62 -1.44 -2.30 -3.10 -3.82 -4.34 -4.74 -4.60 -4.73 -5.00
              yaw:   0.00 -0.05  0.00 -0.07 -0.10  0.24  0.45  0.80  0.36 -0.81 -1.36 -0.98
m4a1_silencer pitch: 0.00 -0.08 -0.15 -0.51 -0.99 -1.50 -1.99 -2.31 -2.60 -2.63 -2.81 -2.94
```
Armas com padrão: `ak47`, `m4a1` (M4A4), `m4a1_silencer` (M4A1-S), `galilar`, `famas`, `mp9`, `mac10`, `mp7`.
Cada arma tem `max_measured_bullet`: depois dela, mantenha o último valor.

### Como usar
```csharp
// estado da rajada de cada bot/arma
int NextBullet(int prev, float pauseS, float cycleS)
    => (prev == 0 || pauseS > resetRule.PauseOverCycleMax * cycleS) ? 1 : prev + 1;

var row = pattern.Bullets[Math.Min(bullet, pattern.Bullets.Count) - 1];
float bulletPitch = eyePitch + recoil.Scale.Value * row.Pitch;   // pitch positivo = para baixo
float bulletYaw   = eyeYaw   + recoil.Scale.Value * row.Yaw;     // CUIDADO com o sentido do yaw (abaixo)
// depois some a dispersão aleatória do tiro (seção 2)
```

- **`scale.value` = 2.0.** A bala sai deslocada em **2 × punch**, não 1 ×. Ajustado nos dados: **2,05** (intervalo de confiança 95%: 1,99 a 2,12)
  em 4.811 tiros que acertaram, usando o quanto o jogador aponta abaixo da cabeça para compensar o recuo.
- **O jogador compensa.** O punch é o recuo da arma; o jogador real puxa o mouse para baixo para anulá-lo. Na Unity, aplique o punch
  e deixe o bot compensar com um erro. Não gere a bala já corrigida. O quanto cada jogador compensa o recuo **ainda não está medido
  por jogador** (os perfis só trazem o erro de mira na primeira bala); até lá, use a precisão por bala de `player_profiles.json`
  (`accuracy.<classe>.by_spray_bullet`) como alvo de calibração.
- **Sinais e eixos (Source).** Pitch **negativo** = a mira sobe. Yaw **positivo** = esquerda (anti-horário visto de cima).
  Na Unity, o yaw positivo é para a **direita**, então inverta o sinal do yaw ao converter. Confira com a rajada do AK: ela sobe e
  desvia primeiro para um lado (bala 6 a 8) e depois para o outro (bala 10 em diante).

### Reinício da rajada (`reset_rule`, `reset`)
Se a pausa desde o último tiro passar de **1,3 × o tempo de ciclo** da arma, o próximo tiro é a **bala 1**. Medido: nos rifles,
99,5% a 100% das pausas maiores que isso reiniciam; abaixo disso, 0,2%. `reset[classe].recoil_index_decay` traz, para quem quiser modelar o
resíduo, quanto do índice de recuo resta depois de uma pausa (34% depois de 0,3 a 0,4 s, 7% depois de 0,6 a 0,8 s, nada depois de 1 s). O punch residual
nessas pausas é menor que 0,15° e pode ser ignorado.

## 2. Dispersão e `penalty`

Cada bala do `patterns` tem `penalty`: o valor da **penalidade de precisão do jogo** naquele tiro. No AK sobe de 0,0135 (bala 1)
para ~0,024 (bala 8) e estabiliza. É a parte do cone de dispersão que cresce com a rajada.

**O que NÃO está medido:** como o jogo combina `penalty` com `spread` e `inaccuracy_stand/crouch/move/jump` (todos em
`game_rules.json`) para formar o cone final é código do motor, e as demos não mostram a bala individual. Ponto de partida
razoável, **ainda não validado**: `cone = spread + inaccuracy(estado do jogador) + penalty`. Quem valida é a calibração:
`combat.accuracy.*` (por arma e distância), `combat.still_shot_rate` e `combat.aim_error_first_bullet_deg` mostram se o cone está
grande ou pequeno demais ([`calibration.md`](calibration.md)).

## 3. Penetração (`penetration`)

O evento de dano das demos não marca se o tiro atravessou algo, então foi **inferido**: um acerto é "atenuado" quando o dano na vida
ficou mais de 1 ponto abaixo do que a fórmula de `game_rules.damage_model` prevê (essa fórmula acerta exatamente 82% a 86% dos danos
e nunca prevê menos do que o real).

| Classe | Acertos atenuados | Dano que resta quando atenua (mediana; p10 a p90) |
|---|---|---|
| rifle | 15% | 44% (13% a 77%) |
| pistola | 7% | 37% (6% a 69%) |
| smg | 4% | poucos casos para medir (menos de 30) |
| awp | 85% | 70% (34% a 77%) |

A parcela atenuada é calculada **só entre acertos que não mataram**, porque o dano letal é limitado à vida restante. Por isso é alta
na AWP (um acerto limpo quase sempre mata). Os kills com `penetrated > 0` são 5% dos kills de rifle, 4% dos de AWP e 2% dos de pistola.
O dano de fogo e de granada (`hitgroup: "generic"`) **não** é tiro de arma e não entra nestes números.

Uso: quando o tiro da Unity atravessar uma superfície, aplique ao dano a fração sorteada de `damage_fraction_when_attenuated[classe]`
(ou calcule pela `penetration_power` da arma e pelo material, se a Unity tiver os materiais do mapa) e confira o resultado pela
calibração.

## Limites desta versão

- Só 8 armas têm padrão de recuo: as automáticas com amostra suficiente. Pistolas, AWP e escopetas são de tiro semi-automático
  (o intervalo depende do jogador) e ficam sem padrão. Use o `recoil` de `game_rules.json` como aproximação.
- Depois da última bala medida (20 a 27, conforme a arma) o padrão é extrapolado mantendo o último valor.
- O padrão é o da versão 1.41.8.1 a 1.41.9.0 do jogo; um patch que mude o recuo exige recalcular.
