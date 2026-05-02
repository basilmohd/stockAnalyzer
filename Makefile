.PHONY: webhook scheduler test

webhook:
	python webhook_server.py

scheduler:
	python scheduler.py

test:
	python -m pytest tests/ -v
