#!/usr/bin/env python3
"""
Demo script for Demand Validation Engine (Pieza 3).

Tests the engine with a real niche and displays the results.
Requires YOUTUBE_API_KEY to be set in .env file.
"""

import asyncio
import json
import sys
from app.catalog.demand import validate_niche_demand, clear_demand_cache


def format_report(report):
    """Format report for human-readable output."""
    print("\n" + "=" * 80)
    print(f"[VALIDACION DEMANDA] {report.niche.upper()}")
    print("=" * 80)

    # Demand signals
    print("\n[DEMANDA ORGANICA]")
    print("-" * 80)
    if report.demand:
        for signal in report.demand:
            print(f"  * {signal.label}: {signal.value}")
            if signal.evidence_url:
                print(f"    URL: {signal.evidence_url}")
    else:
        print("  * No se detectaron señales de demanda")

    # Trust barrier
    print("\n[BARRERA DE CONFIANZA]")
    print("-" * 80)
    if report.trust_barrier:
        for signal in report.trust_barrier:
            print(f"  * {signal.label}: {signal.value}")
    else:
        print("  * No se detectaron señales de barrera de confianza")

    # Packaging
    print("\n[PATRONES DE EMPAQUETADO]")
    print("-" * 80)
    if report.packaging:
        for signal in report.packaging:
            print(f"  * {signal.label}: {signal.value}")
    else:
        print("  * No se detectaron patrones de empaquetado")

    # Trend direction
    print("\n[TENDENCIA DE BUSQUEDA]")
    print("-" * 80)
    trend_emoji = {
        "sube": "[SUBE]",
        "estable": "[ESTABLE]",
        "baja": "[BAJA]"
    }
    print(f"  {trend_emoji.get(report.trend_direction, '?')} Dirección: {report.trend_direction.upper()}")

    # Abort recommendation
    print("\n" + "=" * 80)
    if report.abort_recommended:
        print("[!] ABORTAR RECOMENDADO")
        print("    Motivo: La tendencia de búsqueda está en BAJA.")
        print("    No se recomienda invertir en este nicho actualmente.")
    else:
        print("[OK] NICHO VIABLE")
        print("    La tendencia no está en baja. Se debe evaluar el resto")
        print("    de señales (demanda, barrera, empaquetado) antes de decidir.")
    print("=" * 80 + "\n")


async def demo():
    """Run demo with real niche."""
    sys.stdout.reconfigure(encoding='utf-8')

    print("\n" + "=" * 80)
    print("[DEMO] VALIDACION DE DEMANDA AUTOMATIZADA (PIEZA 3)")
    print("=" * 80)

    # Test niche
    niche = "ciberseguridad para despachos de abogados"

    print(f"\nAnalizando nicho: '{niche}'...")

    # Clear cache for fresh analysis
    clear_demand_cache()

    try:
        # Validate demand
        report = await validate_niche_demand(niche=niche, use_cache=True)

        # Format and display
        format_report(report)

        # Also display JSON for machine readability
        print("\n[REPORT JSON]")
        print("-" * 80)
        print(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(demo())
