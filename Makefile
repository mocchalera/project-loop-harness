.PHONY: install test lint demo clean-demo

install:
	python -m pip install -e '.[dev]'

test:
	pytest

lint:
	ruff check src tests

demo:
	rm -rf /tmp/pcl-demo
	mkdir -p /tmp/pcl-demo
	pcl init --target /tmp/pcl-demo
	pcl feature add --root /tmp/pcl-demo --name "Login flow" --surface "ui:/login" --description "User signs in"
	pcl goal create --root /tmp/pcl-demo --title "Basic feature coverage"
	pcl render --root /tmp/pcl-demo
	@echo "Dashboard: /tmp/pcl-demo/.project-loop/dashboard/dashboard.html"

clean-demo:
	rm -rf /tmp/pcl-demo
