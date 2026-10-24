"""Valoração: salário, buyout e hype. As fórmulas são a referência do contrato; aqui só ligam os objetos do jogo a elas."""
from typing import Dict

from contract.reference import manager_economy as eco
from manager.models import Player
from manager.params import load_params

salary_for = eco.salary_for
decay_hype = eco.decay_hype


def buyout_for(player: Player, week: int, interested: int, prm: Dict) -> int:
    if player.contract is None:
        return 0
    return eco.buyout_for(player.contract.salary_month, player.hype, player.contract.end_week, week, interested, prm)


def apply_match_result(player: Player, rating: float, won: bool, major: bool = False) -> None:
    """Atualiza forma e hype depois de uma partida; Major pesa mais no hype."""
    player.hype, player.form = eco.match_update(player.hype, player.form, rating, won, major, load_params())
