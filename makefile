PYTHON_PATH ?= C:\Users\pedro\AppData\Local\Programs\Python\Python313\python.exe
VENV = .venv
UV_INSTALLER = uv-installer-latest.exe
UV_DOWNLOAD_URL = https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.exe

ifeq ($(OS),Windows_NT)
    RM = rmdir /s /q
    PYTHON_DEFAULT = python
    PIP = $(VENV)\Scripts\pip
    PYTHON_VENV = $(VENV)\Scripts\python
    UV = uv.exe
    NULL_OUTPUT = >nul 2>&1
    WHICH = where
else
    RM = rm -rf
    PYTHON_DEFAULT = python3
    PIP = $(VENV)/bin/pip
    PYTHON_VENV = $(VENV)/bin/python
    UV ?= $(HOME)/.local/bin/uv
    NULL_OUTPUT = >/dev/null 2>&1
    WHICH = which
endif

.PHONY: setup run clean check-uv install-uv check-python create-venv install-deps

check-uv:
	@echo "Checking UV installation..."
ifeq ($(OS),Windows_NT)
	@$(WHICH) $(UV) $(NULL_OUTPUT) || (echo UV not found. Installing... && $(MAKE) install-uv)
else
	@command -v uv $(NULL_OUTPUT) || command -v $(UV) $(NULL_OUTPUT) || \
		(echo "UV not found. Installing..." && $(MAKE) install-uv)
endif

install-uv:
	@echo "Installing UV..."
ifeq ($(OS),Windows_NT)
	@curl -Lo $(UV_INSTALLER) $(UV_DOWNLOAD_URL)
	@$(UV_INSTALLER) /quiet
	@del $(UV_INSTALLER)
else
	@curl -LsSf https://astral.sh/uv/install.sh | sh
	@echo 'export PATH="$$HOME/.local/bin:$$PATH"' >> ~/.bashrc || true
	@echo 'export PATH="$$HOME/.local/bin:$$PATH"' >> ~/.zshrc || true
endif
	@echo "UV successfully installed!"

check-python:
	@echo Checking Python...
ifeq ($(OS),Windows_NT)
	@if "$(PYTHON_PATH)" NEQ "" ( \
		if exist "$(PYTHON_PATH)" ( \
			echo Using provided Python path: $(PYTHON_PATH) && \
			"$(PYTHON_PATH)" --version \
		) else ( \
			echo ERROR: Provided PYTHON_PATH '$(PYTHON_PATH)' not found! && exit /b 1 \
		) \
	) else ( \
		$(WHICH) python $(NULL_OUTPUT) && (python --version) || (echo Python not found in PATH) \
	)
else
	@if [ -n "$(PYTHON_PATH)" ]; then \
		if [ -x "$(PYTHON_PATH)" ]; then \
			echo "Using provided Python path: $(PYTHON_PATH)"; \
			"$(PYTHON_PATH)" --version; \
		else \
			echo "ERROR: Provided PYTHON_PATH '$(PYTHON_PATH)' not found or not executable."; \
			exit 1; \
		fi \
	else \
		$(WHICH) $(PYTHON_DEFAULT) $(NULL_OUTPUT) && $(PYTHON_DEFAULT) --version || echo "Python not found in PATH"; \
	fi
endif

create-venv: check-uv
	@echo Checking if virtual environment exists...
ifeq ($(OS),Windows_NT)
	@if exist $(VENV) $(RM) $(VENV)
	@echo Creating virtual environment...
	@if "$(PYTHON_PATH)" NEQ "" ( \
		if exist "$(PYTHON_PATH)" ( \
			echo Using provided Python path: $(PYTHON_PATH) && \
			$(UV) venv $(VENV) --python "$(PYTHON_PATH)" --link-mode=copy \
		) else ( \
			echo ERROR: PYTHON_PATH '$(PYTHON_PATH)' not found! && exit /b 1 \
		) \
	) else ( \
		echo Creating virtual environment using project configuration... && \
		$(UV) venv $(VENV) --link-mode=copy \
	)
else
	@if [ -d $(VENV) ]; then $(RM) $(VENV); fi
	@echo "Creating virtual environment..."
	@if [ -n "$(PYTHON_PATH)" ]; then \
		$(UV) venv $(VENV) --python "$(PYTHON_PATH)" --link-mode=copy; \
	else \
		$(UV) venv $(VENV) --link-mode=copy; \
	fi
endif

install-deps: create-venv
	@echo Installing dependencies...
ifeq ($(OS),Windows_NT)
	@if exist requirements.txt ( \
		$(UV) pip install -r requirements.txt --link-mode=copy \
	) else if exist pyproject.toml ( \
		$(UV) sync --link-mode=copy \
	) else ( \
		echo No requirements.txt or pyproject.toml found. Skipping dependency installation. \
	)
else
	@if [ -f requirements.txt ]; then \
		$(UV) pip install -r requirements.txt --link-mode=copy; \
	elif [ -f pyproject.toml ]; then \
		$(UV) sync --link-mode=copy; \
	else \
		echo "No requirements.txt or pyproject.toml found. Skipping dependency installation."; \
	fi
endif
	@echo Dependencies installed successfully!

setup: install-deps
	@echo Setup completed!

run:
	@$(PYTHON_VENV) main.py

clean:
ifeq ($(OS),Windows_NT)
	@if exist $(VENV) rmdir /s /q $(VENV)
else
	@rm -rf $(VENV)
endif
	@echo Virtual environment removed!

setup-evolution-api:
	@if ! docker network ls | grep -q dokploy-network; then \
		docker network create dokploy-network; \
	fi
	docker compose -f ./evolution-api/docker-compose.yaml up
