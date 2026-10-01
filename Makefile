.PHONY: run server test install

install:
	pip install -r requirements.txt

run:
	python main.py

server:
	python main.py --server

test:
	python tests/test_skills_tools.py
