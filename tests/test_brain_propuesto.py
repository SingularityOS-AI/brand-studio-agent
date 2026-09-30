"""
Brand Brain: secciones "propuesto" durante la entrevista.

Brandy guarda datos utiles con confirmed=false apenas los oye (para que
aparezcan en pantalla) y vuelve con confirmed=true tras un si explicito.
Un guardado intermedio "propuesto" nunca puede degradar un "confirmado".
"""
import os
os.environ["TEST_MODE"] = "true"

from unittest.mock import patch

from app.tools.brand_brain.models import BrandBrain, Section
from app.tools.brand_brain.extractor import extract_and_persist

LEAD = "agent: Hello! I'm Brandy, your Brand Studio Agent. Tell me what you do and who you do it for, in your own words.\n"

CONTENT = {
    "etapa": "creador atascado",
    "habilidad_a_desbloquear": "perspectiva",
    "prohibicion": "optimizar horarios",
    "postura": "estudiante",
}


def _tool_result(confirmed, citation):
    return {"sections": [{
        "id": "diagnostico",
        "citation_text": citation,
        "citation_source": "usuario",
        "confirmed": confirmed,
        "content": CONTENT,
    }]}


@patch("app.tools.brand_brain.extractor.save_brand_brain")
@patch("app.tools.brand_brain.extractor.get_brand_brain", return_value=None)
def test_seccion_abierta_se_guarda_como_propuesto(_get, mock_save):
    brain = extract_and_persist(
        session_token="t_propuesto",
        transcript=LEAD + "user: my rate is 75 dollars per hour",
        tool_result=_tool_result(False, "my rate is 75 dollars per hour"),
    )
    assert [s.status for s in brain.sections] == ["propuesto"]
    mock_save.assert_called_once()


@patch("app.tools.brand_brain.extractor.save_brand_brain")
@patch("app.tools.brand_brain.extractor.get_brand_brain")
def test_propuesto_no_degrada_una_seccion_ya_confirmada(mock_get, _save):
    mock_get.return_value = BrandBrain(sections=[Section(
        id="diagnostico", label="Diagnostico", status="confirmado",
        content=CONTENT, citation_text="yes exactly", citation_source="usuario",
    )])
    brain = extract_and_persist(
        session_token="t_no_degrada",
        transcript=LEAD + "user: yes exactly\nuser: and my rate is 75 dollars per hour",
        tool_result=_tool_result(False, "my rate is 75 dollars per hour"),
    )
    assert len(brain.sections) == 1
    assert brain.sections[0].status == "confirmado"
    assert brain.sections[0].citation_text == "yes exactly"


@patch("app.tools.brand_brain.extractor.save_brand_brain")
@patch("app.tools.brand_brain.extractor.get_brand_brain")
def test_si_explicito_promueve_propuesto_a_confirmado(mock_get, _save):
    mock_get.return_value = BrandBrain(sections=[Section(
        id="diagnostico", label="Diagnostico", status="propuesto",
        content=CONTENT, citation_text="my rate is 75 dollars per hour",
        citation_source="usuario",
    )])
    brain = extract_and_persist(
        session_token="t_promueve",
        transcript=LEAD + "user: my rate is 75 dollars per hour\nuser: yes that is right",
        tool_result=_tool_result(True, "yes that is right"),
    )
    assert [s.status for s in brain.sections] == ["confirmado"]
