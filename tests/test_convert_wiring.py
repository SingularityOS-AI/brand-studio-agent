"""
Wiring de la extraccion: llama al CAMINO REAL, no a constructores a mano.

Por que existe: `test_nueve_nodos.py` construye Section(...) directamente y por eso
paso en verde mientras `convert_to_sections` reventaba con TypeError en produccion
(le faltaba `label`). 107 tests verdes y el camino real roto. Este archivo cierra
ese hueco: si convert_to_sections deja de construir secciones, esto falla.
"""
import os
os.environ["TEST_MODE"] = "true"

from app.tools.brand_brain.extractor import convert_to_sections
from app.tools.brand_brain.models import BrandBrain
from app.tools.brand_brain.questions import get_section_order


# Contenido minimo que cumple los campos obligatorios de cada nodo (spec §3).
CONTENIDO = {
    "diagnostico": {"etapa": 2, "habilidad_a_desbloquear": "perspectiva",
                    "prohibicion": "optimizar horarios", "postura": "estudiante"},
    "brand_journey": {"resultado_deseado": "vender consultoria", "de_que_ser_conocido": "automatizacion",
                      "que_hacer": "publicar casos", "que_aprender": "guion"},
    "charco": {"problema": "no-show en clinicas", "nivel": "charco",
               "logro_que_lo_respalda": "baje el no-show 30% en mi clinica"},
    "icp": {"quien_decide": "dueno-dentista", "disparador_de_urgencia": "perdio plata con recepcionista",
            "poder_adquisitivo": "400k-2M facturacion"},
    "contrarian": {"creencia_comun": "hay que publicar diario", "postura_opuesta": "publicar menos y mejor",
                   "prueba": "mis clientes cierran con 1 post semanal"},
    "asociaciones": {"deseadas": ["rigor"], "prohibidas": ["gurus de humo"]},
    "identidad": {"voz": "directo tecnico sin humo", "colores": ["azul", "negro"], "tipografias": ["Inter"]},
    "oferta": {"resultado_sonado": "agenda llena", "probabilidad_percibida": "casos validados",
               "retraso": "14 dias", "esfuerzo": "hecho por ti", "componentes": ["setup", "3 posts/semana"]},
    "lead_magnet": {"tipo": "revelador", "problema_A": "auditoria de no-show",
                    "problema_B_que_revela": "no tiene sistema de recordatorios"},
}

CITA = {sid: f"esto lo dijo el fundador sobre {sid} y quedo grabado" for sid in CONTENIDO}


def _transcript():
    return "\n".join(f"Usuario: {c}" for c in CITA.values())


def _tool_result(ids, confirmed=True):
    return {"sections": [
        {"id": sid, "citation_text": CITA[sid], "confirmed": confirmed, "content": CONTENIDO[sid]}
        for sid in ids
    ]}


def test_los_nueve_nodos_se_construyen_por_el_camino_real():
    """Con contenido y cita validos, convert_to_sections devuelve los 9. Este es el test
    que habria cazado el TypeError de `label`."""
    ids = get_section_order()
    assert len(ids) == 9, f"la spec exige 9 nodos, hay {len(ids)}"

    secciones = convert_to_sections(_transcript(), _tool_result(ids))

    construidos = {s.id for s in secciones}
    faltan = set(ids) - construidos
    assert not faltan, f"nodos que NO se construyeron: {sorted(faltan)}"
    assert all(s.label for s in secciones), "alguna seccion salio sin label"
    assert all(s.status == "confirmado" for s in secciones)


def test_confirmed_false_deja_el_nodo_propuesto():
    secciones = convert_to_sections(_transcript(), _tool_result(["charco"], confirmed=False))
    assert len(secciones) == 1
    assert secciones[0].status == "propuesto"


def test_cita_ausente_del_transcript_descarta_el_nodo():
    """El invariante anti-alucinacion: si el fundador no lo dijo, no entra."""
    tr = {"sections": [{"id": "charco", "citation_text": "esto jamas se dijo en la conversacion",
                        "confirmed": True, "content": CONTENIDO["charco"]}]}
    assert convert_to_sections(_transcript(), tr) == []


def test_sin_cita_descarta_el_nodo():
    tr = {"sections": [{"id": "charco", "citation_text": "", "confirmed": True,
                        "content": CONTENIDO["charco"]}]}
    assert convert_to_sections(_transcript(), tr) == []


def test_brandbrain_acepta_las_secciones_del_camino_real():
    """El paso siguiente en produccion: las secciones entran a un BrandBrain sin reventar."""
    secciones = convert_to_sections(_transcript(), _tool_result(get_section_order()))
    brain = BrandBrain(sections=secciones)
    assert len(brain.sections) == 9
    assert all(brain.validate_all_sections().values())


def test_roundtrip_to_dict_from_dict():
    """Camino de lectura de produccion (store.get_brand_brain usa from_dict).
    Su test se perdio en la pieza 15A; se restituye aqui."""
    brain = BrandBrain(sections=convert_to_sections(_transcript(), _tool_result(get_section_order())))
    vuelta = BrandBrain.from_dict(brain.to_dict())
    assert len(vuelta.sections) == 9
    assert {s.id for s in vuelta.sections} == set(get_section_order())
    for original in brain.sections:
        copia = vuelta.get_section(original.id)
        assert copia.citation_text == original.citation_text
        assert copia.status == original.status
        assert copia.label == original.label
