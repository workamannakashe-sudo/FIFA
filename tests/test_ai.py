"""
tests/test_ai.py
~~~~~~~~~~~~~~~~
Unit tests for Google Gemini translation templates, chatbot RAG prompts, and triage fallbacks.
"""

import pytest
from app.ai_helper import generate_accessible_instructions, classify_incident, fan_chatbot_query


@pytest.mark.asyncio
async def test_ai_translation_fallback():
    """Verify standard and fallback translated instructions are returned accurately."""
    # Test English
    eng_msg = await generate_accessible_instructions("evacuate", "Section_101_Lower", "Gate_A1_North", "en")
    assert "Section_101_Lower" in eng_msg
    assert "Gate_A1_North" in eng_msg
    assert "do not run" in eng_msg
    
    # Test Spanish fallback translation
    es_msg = await generate_accessible_instructions("evacuate", "Section_101_Lower", "Gate_A1_North", "es")
    assert "Section_101_Lower" in es_msg
    assert "Gate_A1_North" in es_msg
    assert "no corra" in es_msg
    
    # Test Japanese fallback translation
    ja_msg = await generate_accessible_instructions("evacuate", "Section_101_Lower", "Gate_A1_North", "ja")
    assert "Section_101_Lower" in ja_msg
    assert "Gate_A1_North" in ja_msg
    assert "避難" in ja_msg
    
    # Test blocked fallback translation
    blocked_msg = await generate_accessible_instructions("blocked", "Section_101_Lower", "Gate_B1_East", "fr")
    assert "Gate_B1_East" in blocked_msg
    assert "bloqué" in blocked_msg


@pytest.mark.asyncio
async def test_classify_incident_fallback():
    """Verify classify_incident triggers offline rule triage for security keywords."""
    res = await classify_incident("Fight breaking out between rival fans, significant injuries reported")
    assert res["category"] == "Security"
    assert res["severity"] >= 3
    assert len(res["recommended_action"]) > 0


@pytest.mark.asyncio
async def test_chatbot_query_fallback():
    """Verify chatbot query fallback matches typical fan questions."""
    res = await fan_chatbot_query("where is first aid?", "en", [])
    assert "first aid" in res.lower() or "medical" in res.lower()
