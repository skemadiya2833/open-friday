.PHONY: run server test install doctor

install:
	pip install -r requirements/core.lock.txt
	pip install -e .

run:
	python -m friday

server:
	python -m friday serve --server

doctor:
	python -m friday doctor

test:
	pytest -q -k "not real_hotkey and not hotkey_conflict"
