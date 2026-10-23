PY := .venv/bin/python
VERSION := $(shell cat contract/VERSION)

.PHONY: setup extract simlogs profiles rules dynamics targets team validate test lint refresh package help

help:
	@echo "make setup     cria o ambiente Python (.venv)"
	@echo "make refresh   regera TUDO a partir das demos (extract, simlogs, profiles, rules, dynamics, targets, team, validate)"
	@echo "make validate  confere os artefatos contra os schemas e os vetores de teste"
	@echo "make test      testes automatizados      make lint   verificação estática"
	@echo "make package   gera dist/cs-simulator-contract-<versão>.zip para enviar à Unity"

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

targets:
	$(PY) -m calibration.build_targets

team:
	$(PY) -W ignore -m pipeline.build_team_model

validate:
	$(PY) -m pipeline.validate_contract

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m pyflakes pipeline calibration contract/reference tests

refresh: extract simlogs profiles rules dynamics targets team validate

package: validate
	@mkdir -p dist
	@rm -f dist/cs-simulator-contract-$(VERSION).zip
	zip -q -r dist/cs-simulator-contract-$(VERSION).zip contract calibration pipeline/__init__.py pipeline/common.py pipeline/combat.py \
		requirements-calibration.txt -x "*/__pycache__/*" "*.pyc" ".DS_Store"
	@ls -la dist/cs-simulator-contract-$(VERSION).zip
