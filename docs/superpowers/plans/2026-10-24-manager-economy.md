# Economia do modo manager: plano de implementação

> **Para quem executa:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para executar tarefa por tarefa. Os passos usam caixas `- [ ]`.

**Goal:** Implementar a economia do modo manager (jogadores, contratos, valor de mercado, receita, mercado com clubes do computador, scouting e calendário em semanas) como uma implementação de referência em Python, testada e determinística.

**Architecture:** Novo pacote `manager/`, separado de `contract/`, com módulos pequenos e puros (modelos, valoração, finanças, decisão do jogador, mercado, scouting, jogo). O estado do mundo é um `World` serializável em JSON e todo sorteio usa `random.Random(seed)`. O pacote consome `contract/artifacts/player_profiles.json` só para derivar os 40 jogadores de elite com identidade trocada, e não altera o contrato com a Unity.

**Tech Stack:** Python 3.9 (`.venv`), pytest, dataclasses da stdlib. Sem dependências novas.

**Spec:** `docs/superpowers/specs/2026-10-24-manager-economy-design.md`

## Global Constraints

- Python 3.9: sem `X | Y` em tipos, sem `match`. Use `typing.Optional`, `Dict`, `List`.
- Determinismo: nenhum `random` global nem relógio. Todo sorteio recebe `random.Random`.
- Nenhum `name` nem `steamid` real em nenhuma saída de `manager/` (o jogador vê só `codename` e `pid`).
- Todo número de salário, buyout, hype e peso fica em `manager/params.json`, e não no código.
- Tiers: 3 (1 é o topo). Salário mensal por jogador: Tier 1 estrela $50 mil a $100 mil, Tier 1 regular $15 mil a $50 mil, Tier 2 e 3 $1 mil a $5 mil.
- Elenco: 5 titulares, 1 reserva e 1 coach (7 pessoas). Temporada de 48 semanas.
- Reserva de caixa: uma contratação só é permitida se, depois do bônus de assinatura, o caixa cobre 8 semanas da folha.
- `contract/VERSION` e `contract/` não mudam.
- Mensagens de commit em português, como os commits recentes do repositório.

## Review Focus

Entradas e condições que a spec implica e nenhuma tarefa exercitaria sozinha, da mais provável para a menos:

1. Um clube do computador com menos de 7 pessoas depois de uma saída: precisa ser completado com agentes livres, sem travar. (Tarefa 6)
2. Oferta que o clube não consegue pagar: rejeitada, nunca deixa o caixa negativo. (Tarefa 4)
3. Ver o mesmo jogador duas vezes em scouting: o ruído é estável, sem sortear de novo. (Tarefa 7)
4. Salvar e carregar um jogo no meio da temporada e continuar: o resultado é idêntico ao de quem não salvou. (Tarefa 8)
5. Vazamento de identidade real (nome ou steamid) em qualquer arquivo do mundo. (Tarefa 2)

---

### Tarefa 1: Modelos e parâmetros

**Files:**
- Create: `manager/__init__.py`, `manager/models.py`, `manager/params.py`, `manager/params.json`
- Test: `tests/test_manager_models.py`

**Interfaces:**
- Produces:
  - `Contract(salary_month: int, signing_bonus: int, end_week: int, buyout: int)`
  - `Player(pid: str, codename: str, country: str, role: str, age: int, tier: int, skill: float, hidden: Dict[str, float], hype: float, form: float, club_id: Optional[str], contract: Optional[Contract], profile_ref: Optional[str])`
  - `Club(cid: str, name: str, tier: int, budget: int, prestige: float, reputation: float, roster: List[str], style: str, is_human: bool)`
  - `Offer(club_id: str, salary_month: int, signing_bonus: int, weeks: int, role: str)`
  - cada um com `to_dict()` e `from_dict(d)`
  - `HIDDEN_KEYS = ("consistency", "communication", "ceiling", "lan_form", "temperament")`
  - `load_params() -> Dict`, lido de `manager/params.json`
- Consumes: nada.

- [ ] **Step 1: Escrever os testes**

```python
def test_player_roundtrip():
    p = Player("p1", "kilo", "BR", "awper", 22, 2, 71.0, {k: 50.0 for k in HIDDEN_KEYS},
               30.0, 0.0, None, None, None)
    assert Player.from_dict(p.to_dict()) == p

def test_contract_roundtrip_inside_player():
    c = Contract(4000, 2000, 60, 30000)
    p = Player("p2", "z", "PL", "igl", 30, 3, 55.0, {k: 40.0 for k in HIDDEN_KEYS}, 5.0, 0.0, "c1", c, None)
    assert Player.from_dict(p.to_dict()).contract == c

def test_params_have_the_spec_bands():
    prm = load_params()
    assert prm["salary_bands"]["1"]["star"] == [50000, 100000]
    assert prm["salary_bands"]["1"]["regular"] == [15000, 50000]
    assert prm["salary_bands"]["2"]["all"] == [1000, 5000]
    assert prm["salary_bands"]["3"]["all"] == [1000, 5000]
    assert prm["season_weeks"] == 48 and prm["cash_reserve_weeks"] == 8
```

- [ ] **Step 2: Rodar e ver falhar:** `.venv/bin/python -m pytest tests/test_manager_models.py -v`. Esperado: FAIL (módulo não existe).
- [ ] **Step 3: Implementar** as dataclasses e `params.json`, com `salary_bands`, `season_weeks`, `cash_reserve_weeks`, `weights` (money 0.35, team 0.25, prestige 0.15, role 0.15, reputation 0.10), `hype_half_life_weeks` e `buyout` (`interest_step` 0.15). Use `dataclasses.asdict` para o `to_dict`.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit:** `git add manager tests/test_manager_models.py && git commit -m "Manager: modelos e parâmetros da economia"`

### Tarefa 2: Identidade ficcional e jogadores de elite

**Files:**
- Create: `manager/identity.py`, `manager/elite.py`
- Test: `tests/test_manager_identity.py`

**Interfaces:**
- Produces:
  - `make_codename(rng: random.Random, taken: Set[str]) -> str`
  - `make_country(rng) -> str`
  - `skill_from_profile(profile: dict, all_profiles: List[dict]) -> float`: percentil da precisão `shrunk` geral entre os 40 perfis, mapeado para 70 a 98.
  - `elite_players(seed: int) -> List[Player]`: 40 jogadores de Tier 1, `profile_ref` = índice do perfil, sem `name` nem `steamid`. Idade, país e histórico variam por sorteio; função vem de `role_tags`.
- Consumes: `Player` da tarefa 1, `pipeline.common.ARTIFACTS_DIR`.

- [ ] **Step 1: Escrever os testes**

```python
def real_identifiers():
    d = json.load(open(ARTIFACTS_DIR / "player_profiles.json"))
    return {p["name"] for p in d["players"]} | {p["steamid"] for p in d["players"]}

def test_elite_has_40_players_and_no_real_identifier():
    players = elite_players(seed=1)
    assert len(players) == 40
    dump = json.dumps([p.to_dict() for p in players])
    for ident in real_identifiers():
        assert '"%s"' % ident not in dump

def test_codenames_never_equal_a_real_name():
    rng, taken = random.Random(3), set()
    names = {make_codename(rng, taken) for _ in range(500)}
    assert not (names & real_identifiers())

def test_elite_is_deterministic_for_the_seed():
    assert [p.to_dict() for p in elite_players(7)] == [p.to_dict() for p in elite_players(7)]

def test_elite_skill_is_between_70_and_98():
    assert all(70 <= p.skill <= 98 for p in elite_players(1))
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.** `make_codename` junta sílabas de uma lista curta e rejeita nomes em `taken` ou iguais a um nome real (carregue o conjunto uma vez). Elite: `age` 18 a 34 sorteado, `country` sorteado, `hidden` sorteado perto de 60 a 85, `hype` inicial proporcional à `skill`.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit:** `git commit -am "Manager: identidade ficcional e jogadores de elite"` (depois de `git add`).

### Tarefa 3: Gerador de jogadores por tier

**Files:**
- Create: `manager/generate.py`
- Test: `tests/test_manager_generate.py`

**Interfaces:**
- Produces: `generate_player(rng, tier: int, taken: Set[str], role: Optional[str] = None) -> Player`
- Consumes: `make_codename`, `make_country`, `Player`.

Médias de `skill` por tier: 1 → 78, 2 → 62, 3 → 48 (desvio 8). Existe uma cauda: 5% dos jogadores de Tier 3 e 3% dos de Tier 2 têm `hidden["ceiling"]` ≥ 85 e idade ≤ 20.

- [ ] **Step 1: Escrever os testes**

```python
def sample(tier, n=600):
    rng, taken = random.Random(5), set()
    return [generate_player(rng, tier, taken) for _ in range(n)]

def test_mean_skill_falls_with_tier():
    m = [sum(p.skill for p in sample(t)) / 600 for t in (1, 2, 3)]
    assert m[0] > m[1] > m[2]

def test_low_tier_has_a_hidden_talent_tail():
    young = [p for p in sample(3) if p.hidden["ceiling"] >= 85 and p.age <= 20]
    assert 0.02 * 600 <= len(young) <= 0.09 * 600

def test_roles_cover_the_roster_needs():
    assert {p.role for p in sample(2)} >= {"awper", "igl", "rifler", "coach"}

def test_codenames_unique_in_a_sample():
    assert len({p.codename for p in sample(1)}) == 600
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** `generate_player` com `rng.gauss`, limites 0 a 100, atributos escondidos sorteados pela média do tier. `coach` tem `skill` próprio e não joga partidas.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit:** `Manager: gerador de jogadores por tier`.

### Tarefa 4: Valoração, finanças e viabilidade de contratação

**Files:**
- Create: `manager/valuation.py`, `manager/finance.py`
- Test: `tests/test_manager_economy.py`

**Interfaces:**
- Produces:
  - `salary_for(tier: int, skill: float, hype: float, prm: Dict) -> int`
  - `buyout_for(player: Player, week: int, interested: int, prm: Dict) -> int`: 0 sem contrato; senão `salário anual × (semanas restantes / 48) × (1 + hype/100) × (1 + interest_step × max(0, interested-1))`.
  - `decay_hype(hype: float, weeks: int, prm: Dict) -> float`: meia-vida `hype_half_life_weeks`.
  - `apply_match_result(player: Player, rating: float, won: bool) -> None`: ajusta `form` e `hype`; hype ganha mais com vitória em torneio grande.
  - `weekly_wages(club: Club, players: Dict[str, Player]) -> int`
  - `weekly_revenue(club: Club, rank: int, prm: Dict) -> int`: patrocínio fixo por tier, ajustado pelo ranking.
  - `sticker_payout(club: Club, players: Dict[str, Player], prm: Dict) -> int`: proporcional ao hype médio do elenco, só em Majors.
  - `can_afford(club: Club, players: Dict[str, Player], offer: Offer, prm: Dict) -> bool`: regra da reserva de caixa.
- Consumes: modelos da tarefa 1.

- [ ] **Step 1: Escrever os testes**

```python
def test_salary_lands_inside_the_spec_bands():
    prm = load_params()
    assert 50000 <= salary_for(1, 95, 90, prm) <= 100000
    assert 15000 <= salary_for(1, 70, 30, prm) < 50000
    for t in (2, 3):
        assert 1000 <= salary_for(t, 60, 40, prm) <= 5000

def test_salary_grows_with_skill_and_hype():
    prm = load_params()
    assert salary_for(1, 90, 50, prm) > salary_for(1, 75, 50, prm)
    assert salary_for(1, 80, 90, prm) > salary_for(1, 80, 10, prm)

def test_buyout_is_zero_without_contract_and_grows_with_interest():
    prm = load_params()
    p = Player("p", "k", "BR", "rifler", 24, 1, 85.0, {}, 60.0, 0.0, "c", Contract(40000, 0, 96, 0), None)
    free = Player(**{**p.__dict__, "contract": None})
    assert buyout_for(free, 10, 3, prm) == 0
    assert buyout_for(p, 10, 4, prm) > buyout_for(p, 10, 2, prm) > buyout_for(p, 10, 1, prm)

def test_hype_halves_after_the_half_life():
    prm = load_params()
    w = prm["hype_half_life_weeks"]
    assert abs(decay_hype(80.0, w, prm) - 40.0) < 0.5

def test_can_afford_rejects_offers_that_break_the_reserve():
    prm = load_params()
    club, players = tiny_club(budget=50000, weekly=3000)
    assert not can_afford(club, players, Offer(club.cid, 5000, 40000, 48, "rifler"), prm)
    assert can_afford(club, players, Offer(club.cid, 1500, 1000, 48, "rifler"), prm)
```

(`tiny_club` é um helper de teste que monta um clube com a folha semanal pedida.)

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.** `salary_for` posiciona o jogador dentro da faixa do tier com `0.7 × skill_norm + 0.3 × hype_norm`. Tier 1 é "estrela" quando `skill ≥ 85`. Todo valor monetário é `int`.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit:** `Manager: valoração e finanças do clube`.

### Tarefa 5: Decisão do jogador

**Files:**
- Create: `manager/decision.py`
- Test: `tests/test_manager_decision.py`

**Interfaces:**
- Produces:
  - `score_offer(player: Player, offer: Offer, club: Club, roster: List[Player], prm: Dict) -> float`: soma ponderada de dinheiro, força do time, prestígio, função e reputação (pesos em `params.json`).
  - `choose_offer(player: Player, offers: List[Offer], clubs: Dict[str, Club], players: Dict[str, Player], prm: Dict) -> Optional[Offer]`: a de maior pontuação, ou `None` se nenhuma passa de `prm["accept_threshold"]`.
- Consumes: `salary_for`, modelos.

O termo de dinheiro compara o salário ofertado ao salário de mercado do jogador, com retorno decrescente (`tanh`), e pesa menos para quem tem `skill` alto.

- [ ] **Step 1: Escrever os testes**

```python
def test_awper_prefers_the_club_without_a_star_awper():
    prm = load_params()
    a, b = club_with_star_awper(), club_without_awper()
    p = awper_player()
    assert score_offer(p, same_offer(b), b, roster_of(b), prm) > score_offer(p, same_offer(a), a, roster_of(a), prm)

def test_reputation_can_beat_a_slightly_lower_salary():
    prm = load_params()
    rich, honest = club(reputation=10), club(reputation=90)
    p = young_player()
    low = Offer(honest.cid, 2000, 0, 48, "rifler")
    high = Offer(rich.cid, 2200, 0, 48, "rifler")
    assert score_offer(p, low, honest, [], prm) > score_offer(p, high, rich, [], prm)

def test_money_matters_less_to_stars():
    prm = load_params()
    star, rookie = player(skill=95), player(skill=55)
    delta = lambda pl: score_offer(pl, offer(1.5), c, [], prm) - score_offer(pl, offer(1.0), c, [], prm)
    assert delta(rookie) > delta(star)

def test_choose_offer_returns_none_below_threshold():
    assert choose_offer(player(), [awful_offer()], clubs, players, load_params()) is None
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** os cinco termos normalizados para 0 a 1. O termo de função é 0 se o clube já tem um jogador da mesma função com `skill` maior que o do candidato, 1 se a função está vaga.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit:** `Manager: decisão do jogador entre ofertas`.

### Tarefa 6: Mercado com clubes do computador

**Files:**
- Create: `manager/market.py`, `manager/world.py`
- Test: `tests/test_manager_market.py`

**Interfaces:**
- Produces:
  - `World(seed: int, week: int, difficulty: str, players: Dict[str, Player], clubs: Dict[str, Club], human_cid: str, rng_state: tuple)` com `to_dict()` / `from_dict()`
  - `ai_needs(club: Club, players: Dict[str, Player]) -> List[str]`: funções que faltam para chegar a 5 titulares, 1 reserva e 1 coach.
  - `run_market_week(world: World, rng: random.Random) -> List[Event]`: cada clube do computador com necessidade faz ofertas; jogadores livres e com contrato curto escolhem com `choose_offer`; compras com contrato pagam a buyout (`buyout_for` com o número de interessados). Clubes do computador que gastaram demais vendem no próximo ciclo.
  - `fill_roster_with_free_agents(world, club, rng) -> None`
  - `Event(kind: str, week: int, data: Dict)`
- Consumes: tarefas 1 a 5.

Estilo do clube do computador: `aggressive` gasta até 90% do caixa disponível, `conservative` até 50%.

- [ ] **Step 1: Escrever os testes**

```python
def test_ai_needs_lists_missing_roles():
    w = small_world(seed=1)
    club = remove_player(w, "c2", role="awper")
    assert "awper" in ai_needs(club, w.players)

def test_roster_is_refilled_after_a_departure():            # Review Focus 1
    w = small_world(seed=1)
    drop_two_players(w, "c2")
    run_market_week(w, random.Random(2))
    assert len(w.clubs["c2"].roster) == 7

def test_more_interested_clubs_raise_the_price():
    w = small_world(seed=1)
    low = price_paid(w, interested=1)
    high = price_paid(w, interested=4)
    assert high > low

def test_market_never_leaves_an_ai_club_with_negative_budget():
    w = small_world(seed=4)
    for week in range(60):
        run_market_week(w, random.Random(week))
    assert all(c.budget >= 0 for c in w.clubs.values())

def test_market_is_deterministic():
    a, b = small_world(seed=9), small_world(seed=9)
    run_market_week(a, random.Random(1)); run_market_week(b, random.Random(1))
    assert a.to_dict() == b.to_dict()
```

(`small_world`, `price_paid` e `drop_two_players` são helpers de teste. O mundo pequeno tem 3 clubes de Tier 3 e 12 agentes livres.)

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.** Em `run_market_week`, ordene os clubes por seed estável. Coletar as ofertas por jogador antes de resolver. Se não houver agente livre suficiente, `fill_roster_with_free_agents` gera jogadores com `generate_player` do tier do clube.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit:** `Manager: mercado com clubes do computador`.

### Tarefa 7: Scouting e informação imperfeita

**Files:**
- Create: `manager/scouting.py`
- Test: `tests/test_manager_scouting.py`

**Interfaces:**
- Produces:
  - `scout_view(player: Player, level: int, world_seed: int) -> Dict`: nível 0 mostra `skill_estimate` com ruído de ±12 e sem atributos escondidos; nível 1 ±8 e revela `consistency`; nível 2 ±4 e `communication`, `ceiling`; nível 3 ±1.5 e todos os escondidos. O ruído é uma função determinística de `(world_seed, pid, level)`.
  - `scout_cost(level: int, prm: Dict) -> Dict`: `{"money": int, "weeks": int}`, crescente com o nível.
- Consumes: `Player`, `HIDDEN_KEYS`.

- [ ] **Step 1: Escrever os testes**

```python
def test_same_view_twice_returns_the_same_numbers():         # Review Focus 3
    p = sample_player()
    assert scout_view(p, 1, 42) == scout_view(p, 1, 42)

def test_higher_level_is_closer_to_the_truth_on_average():
    ps = [sample_player(i) for i in range(300)]
    err = lambda lv: sum(abs(scout_view(p, lv, 7)["skill_estimate"] - p.skill) for p in ps) / 300
    assert err(3) < err(2) < err(1) < err(0)

def test_hidden_attributes_are_revealed_by_level():
    p = sample_player()
    assert "consistency" not in scout_view(p, 0, 1)
    assert "consistency" in scout_view(p, 1, 1) and "ceiling" not in scout_view(p, 1, 1)
    assert set(HIDDEN_KEYS) <= set(scout_view(p, 3, 1))

def test_cost_rises_with_level():
    prm = load_params()
    assert scout_cost(1, prm)["money"] < scout_cost(2, prm)["money"] < scout_cost(3, prm)["money"]
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** o ruído com `random.Random(hash_estável(world_seed, pid, level))` (use `hashlib`, nunca `hash()`, que muda entre execuções).
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit:** `Manager: scouting com informação imperfeita`.

### Tarefa 8: Calendário, jogo e salvamento

**Files:**
- Create: `manager/game.py`, `manager/calendar.py`
- Test: `tests/test_manager_game.py`

**Interfaces:**
- Produces:
  - `new_game(seed: int, difficulty: str, club_name: str) -> World`: 3 tiers (10, 12 e 16 clubes), os 40 de elite em Tier 1, o resto gerado, ~60 agentes livres; o clube humano começa em Tier 3. Dificuldades `easy`, `normal`, `hard` mudam o orçamento inicial e o estilo dos clubes do computador (valores em `params.json`).
  - `advance_week(world: World) -> List[Event]`: receita, folha, hype, mercado, calendário.
  - `advance_to_next_decision(world: World) -> List[Event]`: avança semanas até um evento que exige decisão (`contract_expiring`, `offer_received`, `tournament`, `market_open`).
  - `make_offer(world: World, pid: str, offer: Offer) -> Event`: valida com `can_afford`, rejeita se não paga.
  - `save_game(world: World, path) -> None` / `load_game(path) -> World` (JSON, inclui o estado do RNG).
  - `calendar.tournaments_for(season_week: int, tier: int) -> List[str]`: Majors nas semanas 20 e 44.
- Consumes: tudo anterior.

- [ ] **Step 1: Escrever os testes**

```python
def test_new_game_world_shape():
    w = new_game(1, "normal", "Aurora")
    assert [sum(1 for c in w.clubs.values() if c.tier == t) for t in (1, 2, 3)] == [10, 12, 16]
    assert w.clubs[w.human_cid].tier == 3

def test_advance_to_next_decision_stops_before_the_season_ends():
    w = new_game(1, "normal", "Aurora")
    ev = advance_to_next_decision(w)
    assert ev and w.week < 48

def test_offer_the_club_cannot_pay_is_rejected_and_budget_stays_non_negative():   # Review Focus 2
    w = new_game(1, "hard", "Aurora")
    star = best_free_agent(w)
    ev = make_offer(w, star.pid, Offer(w.human_cid, 100000, 500000, 48, star.role))
    assert ev.kind == "offer_rejected" and w.clubs[w.human_cid].budget >= 0

def test_save_load_continues_identically():                   # Review Focus 4
    a = new_game(3, "normal", "Aurora")
    for _ in range(10): advance_week(a)
    save_game(a, tmp / "s.json"); b = load_game(tmp / "s.json")
    for _ in range(20): advance_week(a); advance_week(b)
    assert a.to_dict() == b.to_dict()

def test_promotion_and_relegation_keep_the_tier_sizes():
    w = new_game(2, "normal", "Aurora")
    for _ in range(48): advance_week(w)
    assert [sum(1 for c in w.clubs.values() if c.tier == t) for t in (1, 2, 3)] == [10, 12, 16]

def test_full_season_keeps_every_club_at_7_people():
    w = new_game(2, "normal", "Aurora")
    for _ in range(48): advance_week(w)
    assert all(len(c.roster) == 7 for c in w.clubs.values() if not c.is_human)
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.** O `World` guarda o estado de `random.Random.getstate()` em `rng_state` (listas JSON) e restaura em `load_game`. `advance_week` processa na ordem: receita, folha, decaimento de hype, mercado, calendário.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit:** `Manager: calendário, jogo e salvamento`.

### Tarefa 9: Vazamento de identidade, simulação de fumaça e documentação

**Files:**
- Create: `manager/sim.py`, `docs/manager-economy.md`
- Modify: `Makefile` (alvo `manager-sim`), `README.md` (uma linha para `manager/`)
- Test: `tests/test_manager_world_integrity.py`

**Interfaces:**
- Produces: `python -m manager.sim --seed 1 --seasons 3`, imprime por temporada: caixa do clube humano, tier, maiores transferências e quantidade de clubes com caixa negativo.
- Consumes: `new_game`, `advance_week`.

- [ ] **Step 1: Escrever os testes**

```python
def test_a_saved_world_contains_no_real_identifier():          # Review Focus 5
    w = new_game(1, "normal", "Aurora")
    for _ in range(30): advance_week(w)
    dump = json.dumps(w.to_dict())
    for ident in real_identifiers():
        assert '"%s"' % ident not in dump

def test_three_seasons_run_without_negative_ai_budget_or_stuck_clubs():
    w = new_game(5, "normal", "Aurora")
    for _ in range(3 * 48): advance_week(w)
    assert all(c.budget >= 0 for c in w.clubs.values() if not c.is_human)
    assert all(len(c.roster) == 7 for c in w.clubs.values() if not c.is_human)
```

- [ ] **Step 2: Rodar e ver falhar:** `.venv/bin/python -m pytest tests/test_manager_world_integrity.py -v`.
- [ ] **Step 3: Implementar** `manager/sim.py`, o alvo `manager-sim` no `Makefile` (`$(PY) -m manager.sim --seed 1 --seasons 3`), a linha no `README.md` e `docs/manager-economy.md` (visão geral dos módulos, onde ajustar `params.json`, nota sobre identidade ficcional e a pendência da revisão jurídica).
- [ ] **Step 4: Verificar tudo:** `make test` e `make lint` passam, `make manager-sim` roda 3 temporadas em menos de 60 segundos e imprime a tabela. Confira `git status`: `contract/` sem alterações.
- [ ] **Step 5: Commit:** `Manager: simulação de fumaça, integridade de identidade e documentação`.

---

## Auto-revisão

- **Cobertura da spec:** receita (T4, T8), salários por tier (T1, T4), valor por desempenho e hype (T4), buyout com interessados (T4, T6), decisão com vários fatores (T5), clubes do computador (T6), scouting em níveis (T7), semanas e salvamento (T8), identidade ficcional e elite de 40 (T2), jogadores gerados por tier com cauda de talento (T3), progressão do clube humano de Tier 3 ao 1 (T8, T9), dificuldade (T8).
- **Promoção e rebaixamento:** ficam no fim da temporada da Tarefa 8. **Decisão minha:** os 2 melhores de cada tier sobem e os 2 piores descem, e o teste confere que o tamanho de cada tier se mantém.
- **Fora deste plano:** o desempenho real vem da simulação na Unity; aqui `apply_match_result` recebe o rating como entrada. A ligação entre os dois é um passo seguinte e não muda o contrato.
