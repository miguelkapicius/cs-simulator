# Economia do modo manager: design

Data: 2026-10-24. Status: rascunho para aprovação.

Convenção: o que o dono do projeto decidiu aparece sem marcação. **[Decisão minha]** marca uma escolha feita por mim que ele ainda não viu aprovada. **[Referência]** marca um número vindo de pesquisa, usado só para calibrar.

## Intenção

O jogo tem um modo manager além da simulação de rounds. O jogador cria o próprio clube, contrata jogadores, paga salários e sobe de tier até chegar ao topo. A economia deve parecer a do CS profissional real, e não a de um jogo de futebol adaptado.

O dono pediu "uma experiência real". Em conversa, isso ficou em duas tensões que o desenho precisa sustentar:

1. **Estrela cara contra elenco equilibrado.** Cada contratação consome um orçamento que depende do desempenho do próprio time.
2. **Contratar agora contra esperar.** O valor de um jogador sobe com bons resultados e hype, e cai com má fase.

## Metas

- Valores (salário, buyout, receita) próximos da realidade do CS2 profissional, dentro do que as fontes permitem.
- Mercado vivo: times controlados pelo computador competem com o jogador pelos mesmos jogadores.
- Valor de mercado composto por **desempenho** e **hype**, nos dois casos com peso real.
- O jogador escolhe onde jogar por vários fatores, e não só dinheiro.
- Informação imperfeita: o manager vê uma estimativa do nível do jogador, e o scouting a melhora.
- Um clube pequeno tem caminho de crescimento viável, e não só os ricos.

## Não-metas

- Simular a economia fora do CS (skins, mercado de itens, apostas dos fãs).
- Reproduzir contratos reais de pessoas reais. Nenhum dado de um jogador ou clube real específico entra no produto.
- Gerenciamento de táticas em partida. Isso já é a camada de táticas do contrato.

## Anti-metas

Seria um fracasso mesmo que tecnicamente funcionasse:

- Um mercado em que sempre vence quem tem mais dinheiro (sem espaço para o clube pequeno).
- Um mercado em que o jogador acha o preço certo olhando a tabela (sem incerteza nem hype).
- Jogadores ficcionais que sejam reconhecíveis um a um como jogadores reais.

## Restrições

**Licença.** Nomes de jogadores e de times reais não podem aparecer. O dono decidiu: os jogadores terão codinomes e dados periféricos diferentes, mas o comportamento e as decisões no mapa continuam iguais. Notas:

- Comportamento e decisões são dados de jogo e ficam. O risco está em combinações que identificam alguém: mesma nacionalidade, idade, função, estatísticas e histórico de times juntos. **[Decisão minha]** Variar nacionalidade, idade e histórico por jogador, e manter função e comportamento. A revisão jurídica final é do dono.
- Nomes ficam numa camada de exibição. Dentro dos artefatos circulam só IDs neutros. O campo `name` e o `steamid` hoje em `contract/artifacts/player_profiles.json` são identidades reais e **não podem seguir para o produto**.

**Base de dados.** Existem hoje só 40 perfis de comportamento real (FURIA e adversários, 28 mapas). Isso não basta para povoar um mundo com várias ligas. Então:

- Os 40 viram a elite "de comportamento real", com identidade trocada.
- O resto do mundo, inclusive muitos jogadores de Tier 1, é **gerado**: segue as mesmas regras de comportamento no mapa (mira, posicionamento, utilitários coerentes), com atributos sorteados de distribuições calibradas nos 40.

**Contrato com a Unity.** O repositório é um contrato versionado (`contract/VERSION`, SemVer). Qualquer campo novo que a Unity consuma é MINOR. A economia em si não precisa ir para a Unity: ela alimenta o manager, e o manager entrega à simulação só o elenco escolhido.

## O que foi decidido

- Mercado com times do computador que disputam os mesmos jogadores que o jogador.
- Valor de mercado vem de desempenho e hype, nos dois casos.
- O jogador escolhe a oferta por vários fatores, e não só por dinheiro.
- Chegar o mais perto possível da realidade nos números.
- O jogador cria o próprio clube e cresce aos poucos até os tiers mais altos.
- Jogadores gerados, piores que os reais, povoam os tiers menores, e se comportam corretamente no mapa.

## Desenho proposto

Tudo abaixo é **[Decisão minha]** salvo onde indicado.

### Entidades

- **Clube:** orçamento, receita por fonte, tier, prestígio, histórico, reputação do manager.
- **Jogador:** atributos de comportamento (contrato existente), atributos escondidos, idade, função, contrato, `hype`, forma recente.
- **Contrato:** salário mensal, bônus de assinatura, data de fim, buyout.
- **Oferta e negociação.**

### Receita do clube

Fontes que existem no CS real: patrocínio, premiação, venda de stickers de Majors (repasse da Valve), merch e investimento direto. **[Referência]** O repasse de stickers já rivalizou com a premiação em alguns Majors, e times populares ganharam mais com stickers do que com o título. Este é o canal onde o hype vira dinheiro.

- Patrocínio: valor fixo por temporada, que sobe e desce com a posição no ranking.
- Premiação: variável, por torneio.
- Stickers: só em Majors, proporcional ao hype do elenco.
- Investimento: injeção inicial para quem cria o clube, depois é rara.

### Salários por tier **[Referência, estimativa]**

| Tier | Salário mensal por jogador |
|---|---|
| 1, estrela | $50 mil a $100 mil+ |
| 1, regular | $15 mil a $50 mil |
| 2 e 3 | $1 mil a $5 mil |

Um elenco completo de Tier 1 custa cerca de $210 mil a $230 mil por mês. Contratos reais são confidenciais; as faixas vêm de blogs e afiliados, com baixa confiabilidade. Os valores devem ser **parâmetros ajustáveis**, e não constantes no código.

### Valor de mercado

`valor = f(desempenho, hype, idade, tempo de contrato restante)`

- **Desempenho:** vem das partidas simuladas (o mesmo log que a calibração já mede).
- **Hype:** sobe com títulos, Majors e momentos de destaque. Decai com o tempo. Não depende do desempenho no curto prazo, e é isso que cria a tensão entre contratar agora ou esperar.
- **Buyout:** múltiplo do salário anual vezes o contrato restante, inflado pelo hype e pelo número de times interessados. **[Referência]** O recorde individual conhecido é cerca de $1,1 milhão (sh1ro, Cloud9 para Spirit). A compra de quatro jogadores do Heroic pelo Falcons é estimada em $6 a $10 milhões, e as fontes discordam. Não encontrei dados de buyout para tiers baixos; a escala deles é **[Decisão minha]** proporcional ao salário.
- Jogador livre custa só salário e bônus de assinatura, e quase nunca é estrela.

### Mercado com times do computador

- Cada time tem orçamento, necessidades de elenco e um perfil (agressivo ou conservador).
- Vários times fazem oferta pelo mesmo jogador; a buyout sobe com o número de interessados.
- Times do computador sentem o caixa: quem gasta demais num ano vende no seguinte.
- Sem janela rígida de transferências. O movimento se concentra depois dos Majors e no fim da temporada.

### Como o jogador escolhe uma oferta

Pesos iniciais ajustáveis:

- **Dinheiro:** pesa menos para quem já ganha muito, mais para jovens e para jogadores de tier baixo.
- **Força do time:** quem busca títulos prefere um time forte.
- **Prestígio do clube.**
- **Função:** um AWPer evita um time que já tem um AWPer estrela; IGL pesa o cargo de capitão.
- **Reputação do manager:** cumprir contratos, dar tempo de jogo e não trocar elenco o tempo todo atrai jogadores. É a principal arma do clube pequeno.

### Informação imperfeita

- **Visível:** rating recente, estatísticas por mapa e função, idade, time, faixa estimada de salário.
- **Escondido, revelado por scouting:** consistência sob pressão, comunicação, teto de crescimento, desempenho em LAN contra online, tendência a conflito no vestiário.
- **Variância de forma:** um jogador pode ter três meses de rating alto sem estar no nível real dele.

### Mundo e progressão

- O jogador começa com um clube novo, no tier mais baixo, com um orçamento inicial pequeno.
- Cada tier tem uma média e um teto de atributos menores que o seguinte, mas existe uma cauda de talento jovem escondido. Este é o caminho do clube pequeno.
- Subir de tier abre ligas, patrocínios e jogadores melhores. Descer é possível.

## Deixado ao construtor

- Fórmulas exatas de valor, buyout, hype e decaimento, a partir das referências acima.
- Quantos tiers e quantos clubes por tier; formato das ligas e do ranking.
- Gerador de jogadores: distribuições, correlações entre atributos, nomes e codinomes.
- Persistência do estado do manager e dos artefatos de economia.
- Onde o código mora (pipeline, camada nova ou módulo separado) e como o manager entrega o elenco à simulação.

## Ritmo e regras de jogo **[Decisão minha, delegada pelo dono]**

O dono pediu um jogo dinâmico, "nem demorado nem rápido demais". Daí:

- **Tempo:** corre em semanas, com um calendário de torneios. O jogo avança sozinho até o próximo evento que exige decisão (fim de contrato, oferta recebida, torneio, abertura de mercado), e o jogador pode avançar semana a semana quando quiser. Uma temporada tem cerca de 48 semanas, mas o jogador toma poucas dezenas de decisões por temporada.
- **Venda de jogadores:** permitida. O preço sai do mesmo modelo de buyout; com menos interessados, o preço cai.
- **Scouting:** custa dinheiro e semanas e revela atributos escondidos em níveis (de 1 a 3), e não tudo de uma vez.
- **Dificuldade:** três predefinições que mudam o orçamento inicial e o perfil dos clubes do computador (agressivo ou conservador).
