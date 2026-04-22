set dotenv-load := true

run:
	uv run python main.py

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
