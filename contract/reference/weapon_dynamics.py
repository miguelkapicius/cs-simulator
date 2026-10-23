"""Implementação de referência do recuo (weapon_dynamics.json), só biblioteca padrão.

A versão em C# deve devolver os mesmos números para as mesmas entradas
(veja contract/test_vectors/weapon_dynamics_vectors.json).

  next_bullet_index(model, weapon, prev_index, pause_s) -> índice da bala na rajada (1 = primeira)
  punch(model, weapon, bullet)                          -> (pitch, yaw) do punch, em graus
  bullet_direction(model, weapon, eye_pitch, eye_yaw, bullet) -> (pitch, yaw) da bala, sem a dispersão aleatória
  accuracy_penalty(model, weapon, bullet)               -> penalidade de precisão do jogo nessa bala

Convenções: pitch positivo = para baixo (Source), então um punch de pitch negativo faz a bala subir.
"""


def _pattern(model, weapon):
    return model["recoil"]["patterns"][weapon]


def next_bullet_index(model, weapon, prev_index, pause_s):
    """Continua a rajada se a pausa for curta; senão reinicia na bala 1."""
    cycle = _pattern(model, weapon)["cycle_time_s"]
    if prev_index is None or pause_s > model["recoil"]["reset_rule"]["pause_over_cycle_max"] * cycle:
        return 1
    return prev_index + 1


def _row(model, weapon, bullet):
    rows = _pattern(model, weapon)["bullets"]
    return rows[min(max(bullet, 1), len(rows)) - 1]   # depois da última bala medida, mantém a última


def punch(model, weapon, bullet):
    row = _row(model, weapon, bullet)
    return row["pitch"], row["yaw"]


def accuracy_penalty(model, weapon, bullet):
    return _row(model, weapon, bullet)["penalty"]


def bullet_direction(model, weapon, eye_pitch, eye_yaw, bullet):
    """Direção da bala = mira do jogador + scale * punch (a dispersão aleatória é somada depois)."""
    scale = model["recoil"]["scale"]["value"]
    p_pitch, p_yaw = punch(model, weapon, bullet)
    return eye_pitch + scale * p_pitch, eye_yaw + scale * p_yaw
