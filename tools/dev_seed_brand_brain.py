"""
Script de bootstrap de un solo uso: siembra las 9 secciones del BrandBrain
directamente en la sesion real del CEO, para probar el Brand Soul HTML sin
gastar creditos de voz hablando los 9 nodos.

Como obtener el JWT: en el navegador donde el CEO ya inicio sesion en Brand
Studio -> F12 (DevTools) -> pestana Application -> Local Storage -> el
dominio de la app -> buscar la key que empieza con "sb-" y termina en
"-auth-token" -> copiar el valor -> es un JSON, el campo "access_token" es
el JWT. Pegarlo como argumento --jwt (entre comillas).

Correr con las mismas env vars que usa el .env local o el panel de Render
(SUPABASE_URL, SUPABASE_KEY, y si aplica SUPABASE_JWT_SECRET). Nunca
hardcodear el JWT en este archivo ni commitearlo.

Uso:
    python tools/dev_seed_brand_brain.py --jwt "eyJhbGciOi..."
"""

import argparse
import os
import sys
from pathlib import Path

# Permite correr el script como `python tools/dev_seed_brand_brain.py` desde
# la raiz del repo sin instalar el paquete.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Siembra un BrandBrain de prueba con las 9 secciones confirmadas."
    )
    parser.add_argument("--jwt", required=True, help="JWT de Supabase (access_token) del CEO.")
    args = parser.parse_args()

    missing = [
        var for var in ("SUPABASE_URL", "SUPABASE_KEY")
        if not os.getenv(var)
    ]
    if missing:
        print(f"[ERROR] Faltan variables de entorno: {', '.join(missing)}. "
              f"Corre este script con las mismas env vars que usa el .env local o Render.")
        return 1

    from app.auth.supabase_auth import supabase_auth
    from app.guard import guard
    from app.tools.brand_brain.models import Section, BrandBrain, CitationInvariantError
    from app.tools.brand_brain.questions import SECTIONS
    from app.tools.brand_brain.store import save_brand_brain

    try:
        user_id = supabase_auth.get_user_id(args.jwt)
    except Exception as e:
        print(f"[ERROR] JWT invalido o expirado: {e}")
        return 1

    try:
        session_token = guard.get_or_create_user_session(user_id)
    except Exception as e:
        print(f"[ERROR] No se pudo obtener/crear la sesion: {e}")
        return 1

    sections = []
    for section_def in SECTIONS:
        content = {
            field.key: f"[PRUEBA] valor de ejemplo para {field.key}"
            for field in section_def.fields
        }
        try:
            sections.append(Section(
                id=section_def.id,
                label=section_def.title,
                status="confirmado",
                content=content,
                citation_text=(
                    f"[DATO DE PRUEBA] Cita sembrada manualmente para la seccion "
                    f"'{section_def.id}', no proviene de una conversacion real."
                ),
                citation_source="usuario",
            ))
        except CitationInvariantError as e:
            print(f"[ERROR] Seccion '{section_def.id}' invalida: {e}")
            return 1

    brand_brain = BrandBrain(sections=sections)

    try:
        ok = save_brand_brain(session_token, brand_brain)
    except CitationInvariantError as e:
        print(f"[ERROR] BrandBrain invalido, no se guardo: {e}")
        return 1
    except Exception as e:
        print(f"[ERROR] Fallo al guardar en Supabase: {e}")
        return 1

    if not ok:
        print("[ERROR] save_brand_brain devolvio False (revisa TEST_MODE o la respuesta de Supabase).")
        return 1

    print(f"[OK] {len(sections)}/9 secciones sembradas para session_token={session_token[:12]}...")
    print("Refresca la pagina de Brand Studio para ver el panel con las 9 secciones confirmadas "
          "y prueba el boton 'Generar Brand Soul'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
