.PHONY: dev run lint clean build-prod run-prod

dev:
	python -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -e . && python -m ez_panel.app
.PHONY: venv venv-install-cli venv-run venv-run-safe kill-ezpanel venv-run-exec

venv:
	bash scripts/dev-venv.sh

venv-install-cli:
	python -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -e .
	@echo "Activate: . .venv/bin/activate && EZ-Panel --help"

kill-ezpanel:
	@echo "[kill] Terminating existing EZ-Panel processes and freeing common ports..."
	-@for p in 5000 5050 5051 5052 5053; do \
		fuser -k $${p}/tcp 2>/dev/null || true; \
	done
	-@pkill -f EZ-Panel || true
	-@pkill -f ez_panel.app || true
	-@pkill -f gunicorn.*ez_panel || true
	@echo "[kill] Done."

venv-run: kill-ezpanel
	. .venv/bin/activate && EZ-Panel --host 0.0.0.0 --port 5000

venv-run-safe: kill-ezpanel
	. .venv/bin/activate && EZ_PANEL_SAFE_MODE=1 EZ_PANEL_SCAN_METHOD_DEFAULT=ping EZ_PANEL_DEEP_DEFAULT=0 EZ_PANEL_INCLUDE_OFFLINE_DEFAULT=0 EZ_PANEL_UI_AUTO_REFRESH_MS=8000 EZ-Panel --host 0.0.0.0 --port 5000

# Start with command execution enabled (docker exec), on a specified port (default 5051)
venv-run-exec: kill-ezpanel
	. .venv/bin/activate && \
		PORT=$${PORT:-5051} && \
		FLASK_ENV=production \
		ALLOW_DOCKER_EXEC=1 \
		EXEC_TIMEOUT=$${EXEC_TIMEOUT:-30} \
		EXEC_CONTAINER_NAME=$${EXEC_CONTAINER_NAME:-c2panel_c2panel_1} \
		EZ_PANEL_HOST=0.0.0.0 \
		EZ_PANEL_PORT=$${PORT} \
		EZ-Panel --host 0.0.0.0 --port $${PORT}


run:
	. .venv/bin/activate && python -m ez_panel.app

lint:
	. .venv/bin/activate && python -m pip install ruff && ruff check ez_panel || true

clean:
	rm -rf .venv __pycache__ **/__pycache__ *.pyc *.pyo *.pyd build dist *.egg-info .pytest_cache .ruff_cache

build-prod:
	docker build -f Dockerfile.prod -t ezpanel:prod .

run-prod:
	docker compose -f docker-compose.prod.yml up --build

.PHONY: install-cli link-cli

# Install console scripts (EZ-Panel / ez-panel / ez_panel / ezpanel)
install-cli:
	python -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -e .
	@echo "Now you can run: . .venv/bin/activate && EZ-Panel --help"

# Symlink lightweight launcher to /usr/local/bin for system-wide usage (requires sudo)
link-cli:
	install -m 0755 scripts/EZ-Panel /usr/local/bin/EZ-Panel
	install -m 0755 scripts/EZ_Panel /usr/local/bin/EZ_Panel
	@echo "Installed CLI launchers: EZ-Panel and EZ_Panel. Run: EZ-Panel --help"

.PHONY: systemd-install systemd-uninstall

systemd-install:
	install -m 0644 packaging/systemd/ez-panel.service /etc/systemd/system/ez-panel.service
	systemctl daemon-reload
	systemctl enable ez-panel.service
	systemctl start ez-panel.service
	@echo "Service installed and started. Visit http://<host>:$$EZ_PANEL_PORT (default 5000)."

systemd-uninstall:
	systemctl stop ez-panel.service || true
	systemctl disable ez-panel.service || true
	rm -f /etc/systemd/system/ez-panel.service
	systemctl daemon-reload
	@echo "Service removed."
