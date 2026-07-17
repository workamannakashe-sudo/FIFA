import pytest
from app.ai_helper import generate_accessible_instructions

@pytest.mark.asyncio
async def test_ai_translation_fallback():
    # Test that English is generated correctly and fast without API call
    eng_msg = await generate_accessible_instructions("evacuate", "Stand_North_Lower", "Gate_A_North", "en")
    assert "Stand_North_Lower" in eng_msg
    assert "Gate_A_North" in eng_msg
    assert "do not run" in eng_msg
    
    # Test Spanish fallback translation
    es_msg = await generate_accessible_instructions("evacuate", "Stand_North_Lower", "Gate_A_North", "es")
    assert "Stand_North_Lower" in es_msg
    assert "Gate_A_North" in es_msg
    assert "no corra" in es_msg
    
    # Test Japanese fallback translation
    ja_msg = await generate_accessible_instructions("evacuate", "Stand_North_Lower", "Gate_A_North", "ja")
    assert "Stand_North_Lower" in ja_msg
    assert "Gate_A_North" in ja_msg
    assert "避難" in ja_msg
    
    # Test blocked fallback translation
    blocked_msg = await generate_accessible_instructions("blocked", "", "Gate_B_East", "fr")
    assert "Gate_B_East" in blocked_msg
    assert "bloqué" in blocked_msg
