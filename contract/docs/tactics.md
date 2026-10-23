# Camada tática (`tactics.json` e `tactics_playbook.json`)

Como os jogadores se movem e se posicionam, no nível de **regiões** (os callouts do CS2: `BombsiteA`, `Apartments`, `TopofMid`...).
Não usa a geometria 3D: só o nome da região em que cada jogador está, a 8 amostras por segundo, em 599 rounds de 7 mapas.

- Schemas: [`tactics.schema.json`](../schemas/tactics.schema.json) e [`tactics_playbook.schema.json`](../schemas/tactics_playbook.schema.json)
- Referência executável: [`reference/tactics.py`](../reference/tactics.py)
- **Vetores de teste:** [`test_vectors/tactics_vectors.json`](../test_vectors/tactics_vectors.json) (≈ 1.300 casos)

## O que a Unity precisa fazer primeiro

A Unity precisa saber **em qual região cada bot está**. Isso exige marcar o mapa 3D com volumes que tenham os nomes de
`maps.<mapa>.places` (ex.: um volume "Apartments" na Mirage). Sem a geometria do mapa isso não pode ser feito. A posição
`centroid_m` de cada região está nas coordenadas da Source, em metros, e serve de referência para conferir o alinhamento.

## O que tem em `tactics.json` (por mapa)

| Bloco | O que é | Para que serve |
|---|---|---|
| `places` | centro, tamanho, quem usa (CT/T) e **zona** (`A`, `B`, `Mid`, `Spawn`) de cada região | marcar o mapa; decidir para onde ir |
| `graph` | para onde o jogador vai ao sair de cada região, e quanto tempo costuma ficar | movimento entre regiões |
| `occupancy` | onde cada lado costuma estar a cada 5 s do round | posição inicial e distribuição geral |
| **`forecast`** | **onde o jogador estará daqui a 5 s e 10 s, dada a região atual** | **o "para onde vou agora" do bot** |
| `post_plant` | depois do plant: chance e tempo de o CT chegar ao bombsite, defuse por CTs vivos | pós-plant e retake |
| `rotation` | como um CT reage ao primeiro contato, conforme a zona dele e a do contato | rotação do CT |
| `engagements` | onde acontecem o primeiro contato e os kills (pares atacante/vítima) | onde os duelos acontecem |
| `utility` | onde e quando cada lado joga cada granada | uso de utilitários |
| `evaluation` | validação do `forecast` em partidas inéditas | confiança |

**Zona** de uma região: `A` ou `B` se, depois de passar por ela, o jogador visita aquele bombsite em ao menos 65% das vezes
(fluxo dos atacantes; do CT onde o T quase não passa); `Mid` no meio-termo. É o que dá sentido a "rotação para o A" sem a geometria.

## O playbook (`tactics_playbook.json`)

As rotas dos **cinco jogadores de cada lado em todos os 599 rounds reais**: uma lista de passos `[região, entrada, saída]`, mais o
tipo de compra, o resultado e o plant do round. A ideia é a simulação **sortear um round real e reproduzi-lo**.
Isso preserva de graça o que é difícil de modelar, que é o time agir em conjunto (os cinco vão ao mesmo lugar, nos mesmos tempos).

```
1. sorteie um round do mapa:   pesos = round_weights(playbook, mapa, tipo_de_compra_do_T)   // rounds com a mesma compra pesam igual
2. a cada instante t, o bot i do T deve estar em   place_at(round, "T", i, t)               // índice em maps.<mapa>.places
3. se o bot saiu da rota (contato, morreu, o jogador gravado já tinha morrido) use o forecast   // seção abaixo
```

`died_at` mostra quando o jogador gravado morreu. A simulação decide as mortes sozinha, então depois de `died_at` (ou quando
`place_at` devolver `None`) o bot deve passar a seguir o `forecast`, e não parar.

## `forecast`: o modelo mais forte

Dado onde o jogador está agora, a distribuição de onde ele estará daqui a 5 s (ou 10 s):

```csharp
Dictionary<string, double> dist = model.Maps[map].Forecast[side]["5s"][place].P;   // soma ~1
string next = SampleCategorical(dist, rng);
```
Para horizontes até 7,5 s usa-se a tabela de 5 s; acima disso, a de 10 s (ver `reference/tactics.py`).

**Validado em partidas que o modelo não viu** (perda logarítmica por amostra, menor é melhor):

| Mapa | Ocupação (lado e tempo) | Previsão pela região atual | Melhora |
|---|---|---|---|
| Mirage | 2,56 | 1,10 | **+57%** (5 s) / +41% (10 s) |
| Inferno | 2,24 | 1,03 | +54% / +38% |
| Nuke | 2,62 | 1,18 | +55% / +38% |
| Cache | 3,06 | 1,43 | +53% / +37% |
| Dust2 | 2,62 | 1,17 | +55% / +39% |
| Ancient | 2,35 | 1,06 | +55% / +38% |

Anubis tem uma partida só (21 rounds) e não foi avaliado; suas tabelas existem, mas são frouxas.

## O que foi testado e NÃO funcionou (por isso não está no contrato)

Tentamos agrupar os rounds em **planos de ataque** e **setups de CT** (k-means sobre onde o time está a cada 20 s). Parecia bom: os grupos
eram interpretáveis ("execute rápido no B por Apartments", "split pelo TRamp"). Mas, medido em partidas inéditas:

- **Os 40 s iniciais de um round não preveem o bombsite do plant.** Em 5 dos 6 mapas o acerto foi igual ou pior que apostar sempre na
  classe mais comum (por exemplo, Nuke 41% contra 52% e Dust2 31% contra 51%). Só na Cache ficou acima (57% contra 50%), com amostra pequena.
- **Conhecer o plano não melhorou a previsão de posição** (de −10% a +3%), nem definindo o plano pelo desfecho (bombsite e rapidez do plant).
- Com 60 a 145 rounds por mapa, condicionar a posição a qualquer rótulo estratégico dilui os dados.

Ou seja, os "planos" eram uma divisão arbitrária de um contínuo de comportamentos. Por isso a coordenação do time vem do **playbook**
(rounds reais inteiros), que não depende de classificar nada.

## Limites desta versão

- **Sem geometria:** não há distâncias reais, linhas de visão nem navegação, só o grafo entre regiões. As distâncias entre centros
  (`centroid_m`) são uma aproximação.
- **Dados:** 599 rounds, quase todos com a FURIA de um dos lados; mapas pequenos (Anubis, 21 rounds) têm playbook curto.
- **Amostragem:** as posições estão a 8 Hz; movimentos mais rápidos que 0,125 s não aparecem.
- **Rotação:** a tabela olha 15 s depois do primeiro contato e só distingue zonas. Os CTs rotacionam devagar nos dados (por exemplo, na
  Mirage, só 1% dos CTs da zona B vão para o A em 15 s quando o contato é no A).

## Calibração

Para medir se a simulação se move como no jogo real, grave o evento `positions` (onde cada jogador vivo está, a 2 Hz ou mais; ver
[`sim_log.md`](sim_log.md)). O comparador mede `tactic.zone_share.*` (onde cada lado está aos 20, 40 e 60 s),
`tactic.first_contact_s`, `tactic.place_changes_per_player` e `tactic.dwell_s` ([`calibration.md`](calibration.md)).
