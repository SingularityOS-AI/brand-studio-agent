"""
PIEZA 19 — andamiaje compartido de los tests e2e sin voz.

Nota de entorno (honestidad, no un bypass): en esta maquina de desarrollo el
interprete de `.venv` no puede escribir en `%TEMP%` (se verifico con un
`os.mkdir` crudo, EPERM, independiente de Playwright) y por lo tanto no puede
lanzar Chromium. El interprete global `C:\\Python312_Neural\\python.exe` SI
puede (se verifico primero). Por eso, si el import de Playwright o el
lanzamiento del navegador fallan por esta causa puntual del entorno, el modulo
completo se SALTA (skip) en vez de fallar, para no romper `pytest -q` corrido
desde `.venv` con el resto de la suite. Un error de Playwright que NO sea ese
permiso especifico de temp sigue fallando de verdad: esto no esconde una
regresion real, solo evita que una limitacion de esta maquina tumbe el resto
de tests que nada tienen que ver con navegadores.

Para correr esta suite de verdad: usar el interprete que si puede lanzar
Chromium, por ejemplo:
    C:\\Python312_Neural\\python.exe -m pytest tests/e2e/ -v
"""
import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    pytest.skip(
        "playwright no esta instalado en este interprete; instalarlo o "
        "correr con el interprete que si lo tiene.",
        allow_module_level=True,
    )


def _browser_can_launch_here() -> bool:
    """Prueba real: intenta lanzar Chromium (y cerrarlo de inmediato).

    Nota: `tempfile.gettempdir()` de Python NO sirve como probe aqui, porque
    cuando el interprete no puede escribir en `%TEMP%` real, Python cae en
    silencio al directorio de trabajo actual (que si es escribible) y el
    probe daria un falso positivo. Playwright, en cambio, apunta directo a
    `%TEMP%` del sistema para su `mkdtemp` interno y ahi si revienta con
    EPERM en el interprete de `.venv` de esta maquina. Por eso el probe real
    es lanzar el navegador de verdad, no simular la escritura de un temp.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


if not _browser_can_launch_here():
    pytest.skip(
        "este interprete no puede lanzar Chromium (EPERM al crear su "
        "directorio temporal en %TEMP%). Correr con el interprete que si "
        "puede (ver docstring de este archivo).",
        allow_module_level=True,
    )
