"""Caminhos e constantes compartilhados entre pipeline/, calibration/ e contract/reference/."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Entradas e dados intermediários (ficam só na máquina, ver .gitignore)
DEMOS_DIR = ROOT / "demos"
DATA_DIR = ROOT / "data"
REFERENCE_DIR = ROOT / "reference"

# O contrato com a Unity (versionado no git)
CONTRACT_DIR = ROOT / "contract"
ARTIFACTS_DIR = CONTRACT_DIR / "artifacts"
SCHEMAS_DIR = CONTRACT_DIR / "schemas"
VECTORS_DIR = CONTRACT_DIR / "test_vectors"
EXAMPLES_DIR = CONTRACT_DIR / "examples"

# Versão semântica do contrato: MAJOR quebra a Unity, MINOR só acrescenta, PATCH renova dados/documentação
CONTRACT_VERSION = (CONTRACT_DIR / "VERSION").read_text().strip() if (CONTRACT_DIR / "VERSION").exists() else "0.0.0"

TICKRATE = 64
UNIT_TO_M = 0.0254  # 1 unidade Source em metros

SIDE = {"CT": "CT", "TERRORIST": "T", "T": "T"}

# Classe de cada arma de fogo (id do jogo sem o prefixo weapon_)
WEAPON_CLASS = {
    **dict.fromkeys(["ak47", "m4a1", "m4a1_silencer", "m4a4", "famas", "galilar", "aug", "sg556"], "rifle"),
    "awp": "awp",
    **dict.fromkeys(["ssg08", "scar20", "g3sg1"], "sniper_other"),
    **dict.fromkeys(["glock", "usp_silencer", "hkp2000", "p250", "fiveseven", "tec9", "cz75a",
                     "deagle", "revolver", "elite"], "pistol"),
    **dict.fromkeys(["mac10", "mp9", "mp7", "mp5sd", "ump45", "p90", "bizon"], "smg"),
    **dict.fromkeys(["nova", "xm1014", "mag7", "sawedoff", "m249", "negev"], "heavy"),
}


def weapon_class(name):
    """Classe da arma a partir do nome do evento (com ou sem prefixo weapon_); None se não for arma de fogo."""
    if not isinstance(name, str):
        return None
    return WEAPON_CLASS.get(name.removeprefix("weapon_"))


# ---------- definições compartilhadas com a Unity (fazem parte do contrato) ----------

# Tipo de compra de um time no fim do freeze time, pelo valor médio de equipamento por jogador.
# Primeiro round de cada metade é sempre "pistol".
PISTOL_ROUNDS = (1, 13)
BUY_ECO_MAX = 1500    # abaixo disto: eco
BUY_FORCE_MAX = 3500  # abaixo disto: force; a partir daqui: full
BUY_TYPES = ["pistol", "eco", "force", "full"]


def buy_type(round_number, avg_equip_per_player):
    if round_number in PISTOL_ROUNDS:
        return "pistol"
    if avg_equip_per_player < BUY_ECO_MAX:
        return "eco"
    if avg_equip_per_player < BUY_FORCE_MAX:
        return "force"
    return "full"


# Nome exibido no jogo -> id da arma (para ler o inventário das demos)
DISPLAY_TO_ID = {
    "AK-47": "ak47", "AWP": "awp", "M4A1-S": "m4a1_silencer", "M4A4": "m4a1", "Galil AR": "galilar",
    "FAMAS": "famas", "AUG": "aug", "SG 553": "sg556", "SSG 08": "ssg08", "SCAR-20": "scar20", "G3SG1": "g3sg1",
    "Glock-18": "glock", "USP-S": "usp_silencer", "P2000": "hkp2000", "P250": "p250", "Five-SeveN": "fiveseven",
    "Tec-9": "tec9", "CZ75-Auto": "cz75a", "Desert Eagle": "deagle", "R8 Revolver": "revolver",
    "Dual Berettas": "elite", "MAC-10": "mac10", "MP9": "mp9", "MP7": "mp7", "MP5-SD": "mp5sd", "UMP-45": "ump45",
    "P90": "p90", "PP-Bizon": "bizon", "Nova": "nova", "XM1014": "xm1014", "MAG-7": "mag7", "Sawed-Off": "sawedoff",
    "M249": "m249", "Negev": "negev",
}
GRENADE_DISPLAY = {
    "Smoke Grenade": "smoke", "Flashbang": "flash", "High Explosive Grenade": "he",
    "Molotov": "molotov", "Incendiary Grenade": "molotov",
}
