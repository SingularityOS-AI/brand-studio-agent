"""PIEZA 18 - la asignacion inicial gratuita debe ser 500, no 250.

Nota: el .env local fija INITIAL_SESSION_CREDITS=250 a proposito para no
tocar saldos existentes en dev; por eso este test desactiva la lectura de
.env (_env_file=None) y limpia el entorno real, para probar el DEFAULT del
codigo (config.py:69), no el valor efectivo de esta maquina.
"""
import importlib

import dotenv


def test_initial_session_credits_default_is_500(monkeypatch):
    monkeypatch.delenv("INITIAL_SESSION_CREDITS", raising=False)
    # Sin esto, reload() vuelve a leer .env y repone el 250 local antes de
    # que se evalue el default de la clase.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)

    import app.config as config_module
    importlib.reload(config_module)
    try:
        settings = config_module.Settings(_env_file=None)
        assert settings.initial_session_credits == 500
    finally:
        importlib.reload(config_module)  # restaura el estado real (.env con 250)
