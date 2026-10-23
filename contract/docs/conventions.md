# Convenções do contrato

## Versão

A versão atual está em `contract/VERSION` e o histórico em `CHANGELOG.md`. Segue versionamento semântico `MAJOR.MINOR.PATCH`:

| Mudança | Versão | Exemplo |
|---|---|---|
| Campo removido, renomeado ou com significado diferente | **MAJOR** | trocar a unidade de `distance_m` |
| Campo ou evento novo (opcional), regra nova | **MINOR** | novo evento no log, nova função no modelo de time |
| Dados renovados, documentação, correção sem mudar o formato | **PATCH** | perfis recalculados com mais demos |

Todo artefato e todo `match_start` carregam `contract_version`. A Unity deve recusar um artefato de MAJOR diferente
do que ela implementa e pode avisar se o MINOR for mais novo.

## Unidades e ângulos

| Grandeza | Unidade |
|---|---|
| Distância nos dados e no log | metros (`distance_m`), exceto onde o nome diz "unidades" |
| Posições das demos (`data/`, `ticks.parquet`) | unidades Source: 1 unidade = 0,0254 m |
| Velocidade | unidades Source por segundo (faca = 250) |
| Tempo | segundos (o log usa ticks + `tickrate`) |
| Ângulos | graus |
| Dinheiro | US$ do jogo |

Altura dos olhos usada nas medições de mira: 64 unidades (1,63 m) em pé e 46 (1,17 m) agachado.

### Eixos da Source x Unity
A Source tem o eixo Z para cima e X/Y no plano. A Unity tem o eixo Y para cima. Uma conversão típica de posição é
`unity = (x, z, y) * 0.0254`, mas depende de como o mapa foi importado. Confira com pontos conhecidos
(por exemplo, as posições de plant de cada bombsite nos dados). Para o `pitch`, a Source usa positivo para baixo.

## Ids

- **Jogador:** texto. Para jogadores reais, o `steamid` de 17 dígitos (sempre como texto, nunca como número, pois estoura 53 bits).
- **Armas:** ids de `game_rules.json`. Atenção: `m4a1` é a **M4A4** e `m4a1_silencer` é a **M4A1-S**.
- **Mapas:** `de_mirage`, `de_dust2`, `de_inferno`, `de_nuke`, `de_cache`, `de_ancient`, `de_anubis`.
- **Callouts (nomes de região):** os da Source (`BombsiteA`, `Underpass`...), usados em `positions` dos perfis.
- **Times:** nomes curtos (`FURIA`, `BetBoom`, `Aurora`, `9z`, `Vitality`...).

## Aleatoriedade

Qualquer sorteio feito com os parâmetros do contrato deve usar uma **semente controlada**, registrada em `match_start.seed`.
Assim uma partida pode ser reproduzida exatamente para depurar.

## Taxas, distribuições e suavização

- **Taxas** (`{value, n, shrunk}`): use `shrunk`, que puxa a taxa em direção à média geral quando a amostra é pequena.
- **Distribuições** (`{p10, p25, p50, p75, p90, ...}`): sorteie por interpolação linear entre os percentis. Exemplo em C# em
  [`player_profiles.md`](player_profiles.md). `source: "baseline"` quer dizer que o jogador tinha poucas amostras
  e recebeu a distribuição média.

## Carregar JSON na Unity

Os arquivos usam dicionários (`weapons.ak47`, `by_distance."0-10m"`). O `JsonUtility` da Unity **não lê dicionários**.
Use o Newtonsoft JSON (pacote oficial `com.unity.nuget.newtonsoft-json`).
