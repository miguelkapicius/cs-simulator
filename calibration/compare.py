"""Compara o log da simulação com as metas do jogo real e gera o relatório.

Uso:
  .venv/bin/python -m calibration.compare LOG_OU_PASTA [...] [--targets ARQ] [--out PASTA] [--fail-on FAIL|WARN]

Como decidir o status de cada métrica (detalhes em contract/docs/calibration.md):
  INSUFFICIENT  a simulação tem menos de MIN_N amostras para aquela métrica
  OK            diferença pequena na prática (dentro da tolerância) OU dentro do ruído estatístico (|z| < 3)
  WARN          fora do ruído (3 <= |z| < 5) e maior que a tolerância
  FAIL          fora do ruído (|z| >= 5) e maior que a tolerância
  MISSING       a meta existe, mas o log da simulação não tem dados para calculá-la
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from calibration.metrics import compute_metrics, describe
from calibration.simlog import load_tables
from pipeline.common import ARTIFACTS_DIR, CONTRACT_VERSION

TARGETS_PATH = ARTIFACTS_DIR / "calibration_targets.json"
DEFAULT_THRESHOLDS = {
    "min_n": 30,        # amostras mínimas na simulação
    "z_warn": 3.0,      # |z| a partir do qual a diferença deixa de ser ruído
    "z_fail": 5.0,
    "prop_tol": 0.03,   # diferença absoluta tolerada em proporções
    "rel_tol": 0.05,    # diferença relativa tolerada em médias
    "cov_tol": 0.05,    # em distribuições: desvio tolerado na fração de amostras abaixo de cada quantil da meta
}
COVERAGE_QUANTILES = [10, 25, 50, 75, 90]
MIN_EQUIV_MATCHES = 0.05   # evita dividir por zero em simulações minúsculas
SEVERITY = {"FAIL": 0, "WARN": 1, "MISSING": 2, "INSUFFICIENT": 3, "OK": 4}


def _status(z, practical_ok, th, robust=True):
    """FAIL só é possível quando o ruído vem da variação entre partidas reais (robust); sem ela, no máximo WARN."""
    if practical_ok or abs(z) < th["z_warn"]:
        return "OK"
    return "FAIL" if (abs(z) >= th["z_fail"] and robust) else "WARN"


def frac_below(samples, v):
    """Fração das amostras abaixo de v (posto médio: correto com valores repetidos)."""
    return float(((samples < v).mean() + (samples <= v).mean()) / 2)


def _z(diff, se):
    if se > 0:
        return diff / se
    return 0.0 if diff == 0 else math.inf


def _noise(target, sim_matches, sd_iid_se, key="sd"):
    """Erro-padrão da diferença. Com a variação entre partidas reais (target['between']), o ruído é
    sd * sqrt(1/partidas_sim + 1/partidas_reais); sem ela, cai no erro-padrão de amostras independentes."""
    b = target.get("between")
    if b and key in b:
        return b[key] * math.sqrt(1 / max(sim_matches, MIN_EQUIV_MATCHES) + 1 / b["matches"]), True
    return sd_iid_se, False


def compare_metric(sim, target, th, sim_matches=1):
    kind = target["kind"]
    row = {"kind": kind, "n_sim": sim["n"], "n_target": target["n"]}
    if sim["n"] < th["min_n"]:
        return {**row, "status": "INSUFFICIENT", "sim": _headline(sim), "target": _headline(target)}

    if kind == "prop":
        p1, p0 = sim["value"], target["value"]
        pooled = (sim["k"] + target["k"]) / (sim["n"] + target["n"])
        se, robust = _noise(target, sim_matches, math.sqrt(pooled * (1 - pooled) * (1 / sim["n"] + 1 / target["n"])))
        diff = p1 - p0
        z = _z(diff, se)
        status = _status(z, abs(diff) <= th["prop_tol"], th, robust)
        return {**row, "status": status, "sim": p1, "target": p0, "diff": diff, "z": z}

    if kind == "mean":
        m1, m0 = sim["mean"], target["mean"]
        se, robust = _noise(target, sim_matches, math.sqrt(sim["std"] ** 2 / sim["n"] + target["std"] ** 2 / target["n"]))
        diff = m1 - m0
        z = _z(diff, se)
        tol = th["rel_tol"] * abs(m0) if m0 else 0.01
        return {**row, "status": _status(z, abs(diff) <= tol, th, robust), "sim": m1, "target": m0, "diff": diff, "z": z}

    if kind == "quantiles":
        samples = sim.get("_samples")
        if samples is None:
            return {**row, "status": "MISSING", "sim": _headline(sim), "target": _headline(target)}
        zs, devs, robust = [], [], bool(target.get("between"))
        for p in COVERAGE_QUANTILES:
            v = target["q"][f"p{p}"]
            q = target.get("coverage", {}).get(f"p{p}", p / 100)   # cobertura da própria distribuição real
            dev = frac_below(samples, v) - q
            iid = math.sqrt(q * (1 - q) * (1 / sim["n"] + 1 / target["n"]))
            if robust:
                se = target["between"]["sd_cov"][f"p{p}"] * math.sqrt(1 / max(sim_matches, MIN_EQUIV_MATCHES) + 1 / target["between"]["matches"])
            else:
                se = iid
            zs.append(_z(dev, se))
            devs.append(dev)
        z = -max(zs, key=abs)   # cobertura menor = simulação com valores maiores; inverte para z>0 = simulação maior
        med1, med0 = sim["q"]["p50"], target["q"]["p50"]
        diff = (med1 - med0) / abs(med0) if med0 else med1 - med0
        status = _status(z, max(abs(d) for d in devs) <= th["cov_tol"], th, robust)
        return {**row, "status": status, "sim": med1, "target": med0, "diff": diff, "z": z, "diff_is_relative": True}
    raise ValueError(f"tipo de métrica desconhecido: {kind}")


def _headline(m):
    return m.get("value") if m["kind"] == "prop" else m.get("mean") if m["kind"] == "mean" else m["q"]["p50"]


def compare(sim_metrics, targets, thresholds=None, matches_by_map=None, total_matches=1.0):
    """Tamanho da simulação em partidas equivalentes: total_matches no geral e matches_by_map[mapa] nas métricas '@mapa'.
    Uma partida equivalente = rounds simulados / rounds por partida real (ver equivalent_matches). Um trecho de
    2 rounds vale ~0,1 partida e, por isso, tem muito mais ruído do que uma partida inteira."""
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    matches_by_map = matches_by_map or {}
    rows = []
    for mid, target in targets.items():
        sim = sim_metrics.get(mid)
        if sim is None:
            rows.append({"id": mid, "kind": target["kind"], "status": "MISSING", "n_sim": 0, "n_target": target["n"],
                         "target": _headline(target)})
        else:
            m = matches_by_map.get(mid.split("@")[1], 0.0) if "@" in mid else total_matches
            rows.append({"id": mid, **compare_metric(sim, target, th, m), "sim_matches": m})
    for r in rows:
        r["desc"] = describe(r["id"])
    rows.sort(key=lambda r: (SEVERITY[r["status"]], -(abs(r["z"]) if isinstance(r.get("z"), float) and math.isfinite(r["z"]) else 1e9 if r.get("z") else 0), r["id"]))
    return rows


# ---------- relatório ----------

def _fmt(v, kind, is_diff=False, relative=False):
    if v is None:
        return "—"
    if is_diff:
        return f"{v * 100:+.1f}%" if relative or kind == "prop" else f"{v:+.3g}"
    if kind == "prop":
        return f"{v * 100:.1f}%"
    return f"{v:.3g}"


def summary(rows):
    counts = {}
    for r in rows:
        group = r["id"].split(".")[0]
        counts.setdefault(group, {s: 0 for s in SEVERITY})[r["status"]] += 1
    return counts


def render_markdown(rows, meta):
    cnt = summary(rows)
    total = {s: sum(c[s] for c in cnt.values()) for s in SEVERITY}
    out = ["# Relatório de calibração: simulação vs. jogo real\n",
           f"- Contrato: {meta['contract_version']}",
           f"- Simulação: {meta['sim_matches']} partida(s), {meta['sim_rounds']} rounds (≈ {meta['sim_equivalent']:.1f} partidas reais de tamanho)",
           f"- Meta: {meta['target_source']}",
           f"- Resultado: **{total['FAIL']} FAIL**, {total['WARN']} WARN, {total['OK']} OK, "
           f"{total['INSUFFICIENT']} sem amostra suficiente, {total['MISSING']} sem dados\n",
           "## Resumo por grupo\n", "| Grupo | FAIL | WARN | OK | Poucas amostras | Sem dados |", "|---|---|---|---|---|---|"]
    for g, c in sorted(cnt.items()):
        out.append(f"| {g} | {c['FAIL']} | {c['WARN']} | {c['OK']} | {c['INSUFFICIENT']} | {c['MISSING']} |")

    def table(sub):
        lines = ["| Métrica | Status | Simulação | Real | Diferença | z | n sim | n real |", "|---|---|---|---|---|---|---|---|"]
        for r in sub:
            z = r.get("z")
            zs = "—" if z is None else ("∞" if not math.isfinite(z) else f"{z:+.1f}")
            lines.append(f"| `{r['id']}` | {r['status']} | {_fmt(r.get('sim'), r['kind'])} | {_fmt(r.get('target'), r['kind'])} | "
                         f"{_fmt(r.get('diff'), r['kind'], True, r.get('diff_is_relative', False))} | {zs} | {r['n_sim']} | {r['n_target']} |")
        return lines

    bad = [r for r in rows if r["status"] in ("FAIL", "WARN")]
    out += ["\n## O que ajustar (FAIL e WARN)\n"]
    if bad:
        for r in bad:
            out.append(f"- **{r['status']}** `{r['id']}`: {r['desc']}")
        out += [""] + table(bad)
    else:
        out.append("Nenhuma métrica fora da faixa do jogo real.")
    missing = [r["id"] for r in rows if r["status"] == "MISSING"]
    per_map = sorted({m.split("@")[1] for m in missing if "@" in m})
    general = [m for m in missing if "@" not in m]
    if general or per_map:
        out += ["\n## Sem dados na simulação\n"]
        if general:
            out.append("Faltam eventos no log para calcular: " + ", ".join(f"`{m}`" for m in general[:40])
                       + (f" e mais {len(general) - 40}" if len(general) > 40 else "") + ". Ver `contract/docs/sim_log.md`.")
        if per_map:
            out.append("Métricas por mapa não avaliadas (a simulação tem poucos rounds nesses mapas): " + ", ".join(per_map) + ".")
    out += ["\n## Todas as métricas\n"] + table([r for r in rows if r["status"] in ("OK", "INSUFFICIENT")])
    return "\n".join(out) + "\n"


def equivalent_matches(rounds_table, targets_doc):
    """Quantas 'partidas reais' a simulação vale, contando rounds. Devolve (total, {mapa: partidas})."""
    per_match = targets_doc["source"]["rounds"] / targets_doc["source"]["matches"]
    by_map = (rounds_table.groupby("map").size() / per_match).to_dict()
    return len(rounds_table) / per_match, by_map


def run(paths, targets_path=TARGETS_PATH, out_dir=None, thresholds=None):
    targets_doc = json.loads(Path(targets_path).read_text())
    tables = load_tables(paths)
    sim = compute_metrics(tables)
    th = {**DEFAULT_THRESHOLDS, **targets_doc.get("thresholds", {}), **(thresholds or {})}
    total_eq, by_map = equivalent_matches(tables["rounds"], targets_doc)
    rows = compare(sim, targets_doc["metrics"], th, by_map, total_eq)
    meta = {"contract_version": CONTRACT_VERSION, "sim_matches": tables["matches"], "sim_rounds": len(tables["rounds"]),
            "sim_equivalent": total_eq,
            "target_source": f"{targets_doc['source']['matches']} partidas reais, {targets_doc['source']['rounds']} rounds "
                             f"(gerado em {targets_doc['generated_at']})"}
    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.md").write_text(render_markdown(rows, meta))
        (out_dir / "report.json").write_text(json.dumps({"meta": meta, "thresholds": th, "results": rows}, ensure_ascii=False,
                                                         indent=1, default=lambda o: None if isinstance(o, float) and not math.isfinite(o) else float(o) if isinstance(o, (np.floating,)) else str(o)))
    return rows, meta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", nargs="+", help="arquivos .jsonl ou pastas com logs da simulação")
    ap.add_argument("--targets", default=str(TARGETS_PATH))
    ap.add_argument("--out", help="pasta onde gravar report.md e report.json")
    ap.add_argument("--fail-on", choices=["FAIL", "WARN"], default="FAIL", help="status que faz o comando sair com erro")
    args = ap.parse_args(argv)
    rows, meta = run(args.logs, args.targets, args.out)
    text = render_markdown(rows, meta)
    print(text if not args.out else text.split("## Todas as métricas")[0])
    if args.out:
        print(f"Relatório completo em {args.out}/report.md")
    bad = {"FAIL"} if args.fail_on == "FAIL" else {"FAIL", "WARN"}
    return 1 if any(r["status"] in bad for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
