.PHONY: install test lint generate-data train serve

install:
	pip install -r requirements.txt

test:
	pytest

lint:
	ruff check .

generate-data:
	python3 cli.py generate-data

train:
	python3 cli.py train

serve:
	python3 cli.py serve --reload
