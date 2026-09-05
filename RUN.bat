@echo off
REM Brand Studio Agent - local run. Venv aislado, nunca el Python global.
cd /d "%~dp0"

if not exist .venv (
    echo [RUN] creando venv aislado...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -q -r requirements.txt
)

if not exist .env (
    echo [RUN] no hay .env real con ASSEMBLYAI_API_KEY.
    echo [RUN] corriendo en TEST_MODE: UI y guard de creditos funcionan, la voz no.
    echo [RUN] para probar voz de verdad: copia .env.example a .env y pon tu key.
    set TEST_MODE=true
)

start "" http://127.0.0.1:8010
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
