# cs-simulator

Algoritmo que aprende com demos de CS2 de partidas profissionais e alimenta uma simulação 3D (Unity).
Os dados reais são a especificação: a mecânica do jogo é ajustada até reproduzir as estatísticas do jogo real.

- **[`contract/`](contract/README.md)**: o contrato com a Unity (artefatos, schemas, documentação, vetores de teste). **Comece por aqui.**
- `pipeline/`: gera os artefatos a partir das demos (extração, perfis, regras, modelo de time).
- `calibration/`: valida o log da simulação e compara com o jogo real.
- `manager/`: economia do modo manager (contratos, mercado, scouting, calendário). Não faz parte do contrato com a Unity. Ver [`docs/manager-economy.md`](docs/manager-economy.md).
- `docs/`: documentação interna do pipeline. `tests/`: testes.

Fora do git (pesados, regeráveis): `demos/`, `archives/`, `data/`, `reference/`. Ver `.gitignore`.

```bash
make setup      # ambiente Python
make refresh    # regera tudo a partir das demos em demos/
make validate   # confere o contrato
make help       # todos os comandos
```
