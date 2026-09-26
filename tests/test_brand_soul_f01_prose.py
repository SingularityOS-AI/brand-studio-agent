import pytest
from unittest.mock import patch, MagicMock
from app.tools.brand_soul.generator import generate_brand_soul
from tests.test_soul import complete_confirmed_brain

@patch("app.tools.brand_soul.generator.get_brand_brain")
@patch("app.tools.brand_soul.generator._check_cache")
@patch("app.tools.brand_soul.generator._save_cache")
@patch("app.tools.brand_soul.generator._get_vertex_ai_client")
def test_f01_prose_no_json_like_format(
    mock_get_vertex_ai_client,
    mock_save_cache,
    mock_check_cache,
    mock_get_brain,
    complete_confirmed_brain
):
    """
    Given a brand brain and a mocked LLM (or test mode returning None),
    When the HTML is generated,
    Then it should NOT contain JSON-like characters or snake_case in its visible text.
    """
    mock_get_brain.return_value = complete_confirmed_brain
    mock_check_cache.return_value = None
    mock_save_cache.return_value = True

    # Mock Vertex AI client as None to trigger the fallback logic which avoids JSON formats
    mock_get_vertex_ai_client.return_value = None

    html, _ = generate_brand_soul("test_token")

    # Extract visible text by removing HTML tags and <style> block
    import re
    # Remove style block completely
    html_no_style = re.sub(r'<style.*?>.*?</style>', '', html, flags=re.DOTALL)
    text_content = re.sub(r'<[^>]+>', ' ', html_no_style)

    # We should not find dict/JSON-like strings in the visible text
    assert "{" not in text_content
    assert "}" not in text_content

    # "key: value" might be matched, but we can verify our fallback logic works
    # by ensuring snake_case keys are gone
    assert "sintoma_diagnostico" not in text_content
    assert "habilidad_a_desbloquear" not in text_content
    assert "resultado_deseado" not in text_content

@patch("app.tools.brand_soul.generator.get_brand_brain")
@patch("app.tools.brand_soul.generator._check_cache")
@patch("app.tools.brand_soul.generator._save_cache")
@patch("app.tools.brand_soul.generator._get_vertex_ai_client")
def test_f01_9_chapters_plus_summary(
    mock_get_vertex_ai_client,
    mock_save_cache,
    mock_check_cache,
    mock_get_brain,
    complete_confirmed_brain
):
    """
    Given a brand brain and a mocked LLM,
    When the HTML is generated,
    Then it must contain the 9 explicit English headings and the summary/closing.
    """
    mock_get_brain.return_value = complete_confirmed_brain
    mock_check_cache.return_value = None
    mock_save_cache.return_value = True

    mock_get_vertex_ai_client.return_value = None

    html, _ = generate_brand_soul("test_token")

    headings = [
        "<h2>Executive summary</h2>",
        "<h2>Diagnosis</h2>",
        "<h2>Brand Journey</h2>",
        "<h2>Your Pond</h2>",
        "<h2>Ideal Client</h2>",
        "<h2>Contrarian Take</h2>",
        "<h2>Associations</h2>",
        "<h2>Identity</h2>",
        "<h2>Offer</h2>",
        "<h2>Lead Magnet</h2>",
        "<h2>How Brandy will use this</h2>"
    ]

    for h in headings:
        assert h in html, f"Missing heading: {h}"
