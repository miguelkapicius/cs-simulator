# Regras do jogo para a simulação (game_rules.json)

`game_rules.json` descreve **como o CS2 funciona**: armas, dano, colete, economia, tempos,
bomba, movimento e granadas. Ele complementa `player_profiles.json`, que descreve **como cada
jogador joga**. A mecânica da simulação deve reproduzir estas regras.

- **Versão do jogo:** build 2000930 (patch 1.41.9.0), a das demos do Thunderpick. Os arquivos oficiais vêm de
  [SteamDatabase/GameTracking-CS2 @ f68ba6aa24](https://github.com/SteamDatabase/GameTracking-CS2/tree/f68ba6aa24).
  Cópias locais em `reference/cs2_build_2000930/`.
  - As demos da ESL (1.41.8.8) e da StarLadder (1.41.8.1) foram comparadas arquivo a arquivo. As regras são as mesmas,
    exceto o tempo de bloqueio na recarga da AUG (3,77 s antes, 3,2 s agora) e a M14, que só existe a partir do 1.41.9.0.
    Detalhes em `game_build.demo_builds_compatibility`.
  - A configuração dos três torneios é igual em tudo que afeta o jogo. Só mudam warmup, pausa no intervalo e apresentação dos times.
- **Duas fontes, sempre identificadas:**
  - **oficial:** arquivos do jogo e configuração do torneio gravada nas demos;
  - **medido:** observado em 28 demos (599 rounds, 3 torneios). Valida o oficial e cobre regras que não estão nos arquivos.
- **Unidades:** distância em unidades Source (1 = 0,0254 m), velocidade em unidades/s, tempo em s, dinheiro em US$ do jogo.
- **Versão do formato:** `schema_version` = `"1.0"`.

**Carregar na Unity:** use o Newtonsoft JSON (`com.unity.nuget.newtonsoft-json`). O `JsonUtility` não lê
dicionários, e `weapons`, `match_config` e várias seções são dicionários.

## Resumo das regras principais

| Regra | Valor | Fonte | Validação nas demos |
|---|---|---|---|
| Rounds | MR12 (24), prorrogação MR3 com $12.500 | torneio | — |
| Tempo de round | 115 s (1,92 min) | torneio | 115,0 s nos 44 rounds que acabaram por tempo |
| Freeze time | 20 s | torneio (padrão 15) | 20 s; pausas táticas aumentam |
| Timer da C4 (do plant à explosão) | **41,0 s** | medido | 144 de 144 explosões |
| Tempo para plantar | **3,125 s** | medido | 322 de 322 plants |
| Defuse | **5 s com kit, 10 s sem** | medido | 67 de 67 (41 com kit, 26 sem) |
| Dinheiro inicial / máximo | $800 / $16.000 | oficial | — |
| Colete / colete + capacete / kit | $650 / $1.000 / $400 | oficial | — |
| Velocidade andando (shift) | 0,52 × máx. da arma | medido | 355 mil amostras |
| Velocidade agachado | ~0,34–0,36 × máx. | medido | mediana |
| Pavio da HE e da flash | 1,625 s | medido | 6.041 granadas |
| Duração da smoke | 22,06 s | medido | 3.823 smokes |
| Duração do molotov | 5,5 a 7,03 s | medido | 3.150 |
| Limite de granadas | 4 no total, 2 flashes | oficial | — |

## weapons.<arma>

Os 45 itens do jogo (armas, granadas, faca, C4, zeus), com os valores **oficiais** do `weapons.vdata`:

- **Combate:** `price`, `kill_award`, `damage`, `bullets_per_shot`, `armor_penetration`, `headshot_multiplier`,
  `range_modifier`, `penetration_power`, `cycle_time_s`, `rpm`, `full_auto`, `clip_size`, `reserve_clips`
  (no CS2 de 2026 a reserva é contada em pentes).
- **Movimento e precisão:** `max_speed` (`normal`; `alt` = com mira/zoom), `spread`, `inaccuracy`
  (`stand`, `crouch`, `move`, `jump`, `land`, `ladder`, `fire`), `recovery_time_s`.
- **Recuo e uso:** `recoil` (ângulo, variância, magnitude e `seed` do padrão), `deploy_time_s`, `reload_attack_lock_s`,
  `zoom`, `silencer` e `tagging` (quanto o jogador desacelera ao ser atingido).
- **`measured`:** cadência real (`fire_interval_s`) e velocidade máxima correndo (`run_speed_p99`).
  Os dois batem com o oficial em todas as armas com amostra suficiente.

**Atenção aos nomes:** `m4a1` é a **M4A4** e `m4a1_silencer` é a **M4A1-S**. `weapon_display_names` traduz
os nomes exibidos no jogo ("AK-47", "M4A1-S") para esses ids.

## damage_model: fórmula de dano (validada)

```csharp
// Retorna (dano na vida, dano no colete). Valores truncados para inteiro.
(int, int) Damage(Weapon w, float distUnits, Hitgroup hg, int armor, bool helmet) {
    float dmg = w.damage * Mathf.Pow(w.range_modifier, distUnits / 500f);
    dmg *= hg switch {
        Head or Neck => w.headshot_multiplier,   // 4.0 em quase todas as armas
        Stomach      => 1.25f,
        LeftLeg or RightLeg => 0.75f,
        _            => 1.0f };                   // peito e braços
    bool protegido = hg switch {
        LeftLeg or RightLeg => false,
        Head or Neck        => helmet,
        _                   => true };
    if (protegido && armor > 0) {
        float vida = dmg * w.armor_penetration;
        float colete = (dmg - vida) * 0.5f;
        if (colete > armor) { colete = armor; vida = dmg - armor * 2f; }
        return ((int)vida, (int)colete);
    }
    return ((int)dmg, 0);
}
// Fogo amigo: multiplicar por match_config.ff_damage_reduction_bullets (0,33) ou _grenade (0,85).
```

**Validação nas demos (8.302 danos):** sem colete, a fórmula reproduz exatamente 81% dos danos; com colete, 84%. **Nenhum**
dano real ficou acima do previsto. Os que ficam abaixo (14–17%) perderam quase metade ou mais do dano, o padrão de tiros que
atravessaram parede, objeto ou outro jogador. As demos não marcam esses tiros. Acertos registrados como `generic` (24%)
também são desse tipo.

## economy: algoritmo (validado)

```
início de cada metade:     dinheiro = start_money (800); contador_derrotas = starting_losses (1)
início de metade da prorrogação: dinheiro = overtime_start_money (12500); contador = 1
fim do round:
  vencedor: + win[motivo]  (eliminação 3250 | bomba explodiu 3500 | defuse 3500 | tempo 3250)
            contador_derrotas = max(contador - 2, 0)        ← medido: vitória desconta 2
  perdedor: contador = min(contador + 1, 5)
            + 1400 + 500 * (contador - 1)                   (máximo 3400)
            T que plantou e perdeu: +600 para o time
            Ts vivos quando o tempo acaba: recebem 0
  todos os CTs: +50 por T morto por CT no round              ← medido, não está no config
durante o round: kill = weapons.<arma>.kill_award; plant +300; defuse +300; teamkill -300
dinheiro nunca passa de max_money (16000)
```

**Validação (537 rounds, 3 torneios):** com essa regra, o dinheiro de 99,6% dos vencedores e de 93% dos perdedores bate exatamente.
As alternativas, com a vitória zerando o contador ou descontando 1, acertam só 82% e 74% dos perdedores.
O último round da partida não paga os $50 por T morto (não faz diferença para a simulação).

## movement, bomb, utility e round_timing

- **movement:** velocidade máxima por arma em `weapons.<arma>.max_speed`; faca = 250. Andar com shift = 0,52×; agachado ≈ 0,34–0,36×.
- **bomb:** os tempos de plant, timer e defuse da tabela acima. Todos foram medidos sem variação.
- **utility:**
  - `smoke_duration_s`, `molotov_burn_duration_s` e `time_to_detonate_s` (HE/flash com pavio de 1,625 s; a smoke detona quando para).
  - `flash_blind_duration_s`: distribuição real da cegueira (mediana 1,2 s, até 5,3 s).
  - `he_damage`: distribuição real do dano de HE (até 94).
  - `molotov_damage_per_event`: dano de cada tick de fogo (1 a 8).
- **round_timing:** quanto tempo os rounds duram em cada desfecho. Serve para validar o ritmo da simulação.
- **match_config:** todas as cvars de partida. `source` indica se o valor veio do torneio ou é o padrão competitivo.

## O que NÃO está aqui (lógica do motor do jogo)

Os parâmetros abaixo estão no arquivo, mas a fórmula que os combina é código do jogo e não vem nos arquivos:

- **Imprecisão:** como `spread` + `inaccuracy` + `recovery_time` se combinam a cada tiro. O comportamento é conhecido
  (a imprecisão sobe a cada tiro e se recupera com o tempo), mas a fórmula exata precisa ser reimplementada.
- **Padrão de recuo:** o CS2 gera o padrão a partir de `recoil.seed` e dos parâmetros de recoil. Para reproduzir o padrão
  exato será preciso extrair o padrão das demos (dá para fazer com os ângulos de mira durante o spray) ou usar uma tabela pública.
- **Penetração:** depende de `penetration_power` e do material da parede (os mapas trazem os materiais).
- **Raio e queda de dano da HE, e intensidade da flash conforme ângulo e distância:** aqui só há as distribuições medidas.

Esses quatro pontos podem ser medidos nas demos numa próxima etapa, se a mecânica precisar.
