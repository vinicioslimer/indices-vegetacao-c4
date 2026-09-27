.PHONY: install run test

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

run:
	.venv/bin/uvicorn vegetacao.main:app --reload

test:
	.venv/bin/python -m pytest -v
