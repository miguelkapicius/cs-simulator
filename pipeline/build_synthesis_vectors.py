"""Gera contract/test_vectors/profile_synthesis_vectors.json: entradas e saídas esperadas de profile_synthesis.synthesize_profile.

O port em C# aplica os mesmos knobs aos mesmos templates (de elite_players.json) e confere uma lista de campos.

Uso: .venv/bin/python -m pipeline.build_synthesis_vectors
"""
import json
from datetime import date

from contract.reference import profile_synthesis as ps
from pipeline.common import ARTIFACTS_DIR, CONTRACT_VERSION, VECTORS_DIR

CHECKED_PATHS = (
    "mechanics.accuracy.rifle.overall.shrunk", "mechanics.aim_error_first_bullet_deg.p50",
    "mechanics.aim_error_first_bullet_deg.p90", "mechanics.crosshair_placement.total_deg.p50",
    "mechanics.engagement.delayed_reaction_s.p50", "mechanics.engagement.by_aim_error.tight_lt2.instant.shrunk",
    "mechanics.engagement.by_aim_error.tight_lt2.delayed.shrunk", "mechanics.engagement.by_aim_error.tight_lt2.none.shrunk",
    "mechanics.movement.still_shot_rate.shrunk", "mechanics.shoots_after_sighting_rate.shrunk",
    "performance.kpr", "performance.dpr", "performance.kd", "performance.adr", "performance.kast",
    "performance.first_contact_s.p50", "performance.opening.attempt_rate.shrunk",
    "performance.utility.flash_per_round", "performance.trade_kills_per_round",
)
KNOBS = [
    {"gap": 0.0, "aggression": 0.0, "utility": 0.0, "spread": 0.0},
    {"gap": 10.0, "aggression": 0.0, "utility": 0.0, "spread": 0.0},
    {"gap": 30.0, "aggression": 0.0, "utility": 0.0, "spread": 0.0},
    {"gap": 60.0, "aggression": 0.0, "utility": 0.0, "spread": 0.0},
    {"gap": -15.0, "aggression": 0.0, "utility": 0.0, "spread": 0.0},
    {"gap": 0.0, "aggression": 1.0, "utility": 0.0, "spread": 0.0},
    {"gap": 0.0, "aggression": -1.0, "utility": 0.0, "spread": 0.0},
    {"gap": 0.0, "aggression": 0.0, "utility": 1.0, "spread": 0.0},
    {"gap": 0.0, "aggression": 0.0, "utility": -1.0, "spread": 0.0},
    {"gap": 0.0, "aggression": 0.0, "utility": 0.0, "spread": 1.0},
    {"gap": 0.0, "aggression": 0.0, "utility": 0.0, "spread": -1.0},
    {"gap": 25.0, "aggression": 0.5, "utility": -0.5, "spread": 0.5},
]
STYLES = ("awper", "entry", "lurker", "support", "rifler")


def get(o, path):
    for k in path.split("."):
        o = o[k]
    return o


def build():
    templates = json.loads((ARTIFACTS_DIR / "elite_players.json").read_text(encoding="utf-8"))["players"]
    cases = []
    for style in STYLES:
        template = next(t for t in templates if style in t["profile"]["role_tags"])
        for knobs in KNOBS:
            out = ps.synthesize_profile(template["profile"], knobs)
            cases.append({"input": {"template": template["pid"], "knobs": knobs},
                          "expected": {p: get(out, p) for p in CHECKED_PATHS}})
    return {"contract_version": CONTRACT_VERSION, "generated_at": date.today().isoformat(), "tolerance": 1e-5,
            "note": "Cada caso aplica `knobs` ao `profile` do jogador `template` de elite_players.json e confere os campos de `expected`.",
            "cases": cases}


def main():
    doc = build()
    (VECTORS_DIR / "profile_synthesis_vectors.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print("profile_synthesis_vectors.json: %d casos" % len(doc["cases"]))


if __name__ == "__main__":
    main()
