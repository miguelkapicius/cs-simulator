PY := .venv/bin/python
VERSION := $(shell cat contract/VERSION)

.PHONY: setup extract simlogs profiles rules dynamics tactics targets team shards elite manager-vectors validate test lint refresh package package-game help manager-sim

help:
	@echo "make setup     cria o ambiente Python (.venv)"
	@echo "make refresh   regera TUDO a partir das demos (extract, simlogs, profiles, rules, dynamics, tactics, targets, team, shards, elite, manager-vectors, validate)"
	@echo "make manager-vectors  regera os vetores de teste da economia do manager (depois de mudar manager_params.json)"
	@echo "make validate  confere os artefatos contra os schemas e os vetores de teste"
	@echo "make test      testes automatizados      make lint   verificação estática"
	@echo "make manager-sim  simula 3 temporadas da economia do manager e resume o resultado"
	@echo "make package   gera dist/cs-simulator-contract-<versão>.zip para enviar à Unity (desenvolvimento e calibração, com dados reais)"
	@echo "make package-game  gera dist/cs-simulator-game-<versão>.zip para embarcar no jogo (sem nenhuma identidade real)"

setup:
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

extract:
	$(PY) -W ignore -m pipeline.extract_demos

simlogs:
	$(PY) -W ignore -m pipeline.real_to_simlog

profiles:
	$(PY) -W ignore -m pipeline.build_player_profiles

rules:
	$(PY) -W ignore -m pipeline.build_game_rules

dynamics:
	$(PY) -W ignore -m pipeline.build_weapon_dynamics

tactics:
	$(PY) -W ignore -m pipeline.build_tactics

targets:
	$(PY) -m calibration.build_targets

team:
	$(PY) -W ignore -m pipeline.build_team_model

shards:
	$(PY) -W ignore -m pipeline.build_shards

manager-vectors:
	$(PY) -m pipeline.build_manager_vectors

elite:
	$(PY) -m pipeline.build_elite_players
	$(PY) -m pipeline.build_synthesis_vectors

validate:
	$(PY) -m pipeline.validate_contract

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m pyflakes pipeline calibration contract/reference manager tests

manager-sim:
	$(PY) -m manager.sim --seed 1 --seasons 3

refresh: extract simlogs profiles rules dynamics tactics targets team shards elite manager-vectors validate

package: validate
	@mkdir -p dist
	@rm -f dist/cs-simulator-contract-$(VERSION).zip
	zip -q -r dist/cs-simulator-contract-$(VERSION).zip contract calibration pipeline/__init__.py pipeline/common.py pipeline/combat.py \
		requirements-calibration.txt -x "*/__pycache__/*" "*.pyc" ".DS_Store"
	@ls -la dist/cs-simulator-contract-$(VERSION).zip

package-game: validate
	$(PY) -m pipeline.package_game
