import json
import logging
import re
import google.generativeai as genai
from app.config import GEMINI_API_KEY

logger = logging.getLogger("safepass.ai")

# Initialize Gemini if API key is provided
GEMINI_AVAILABLE = False
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # Using gemini-1.5-flash as the fast, lightweight, and free tier model
        gemini_model = genai.GenerativeModel("gemini-1.5-flash")
        GEMINI_AVAILABLE = True
        logger.info("Google Gemini API successfully configured.")
    except Exception as e:
        logger.error(f"Failed to initialize Google Gemini API: {e}. Falling back to offline engine.")
else:
    logger.info("No GEMINI_API_KEY provided. Operating in offline local fallback mode.")


# High-quality offline local dictionary fallback for FIFA's key language groups
LOCAL_TRANSLATIONS = {
    "es": {  # Spanish
        "evacuate_prompt": "Atención: Por favor evacúe de inmediato desde {start} a través de {exit}. Avance con calma, no corra.",
        "blocked_prompt": "Aviso de congestión: El sector {gate} está bloqueado por incidente. Desviando flujo de personas.",
        "congestion_prompt": "Congestión detectada en {zone}. Reduzca la velocidad y siga las rutas de salida alternativas.",
        "all_safe": "Rutas de evacuación normales y estables. Proceda con precaución.",
        "low_bandwidth": "ALERTA: Siga las señales de color verde para evacuar."
    },
    "fr": {  # French
        "evacuate_prompt": "Attention: Veuillez évacuer immédiatement depuis {start} via {exit}. Avancez calmement, ne courez pas.",
        "blocked_prompt": "Avis d'incident: L'accès {gate} est actuellement bloqué. Redirection du flux de personnes.",
        "congestion_prompt": "Congestion détectée en zone {zone}. Ralentissez et suivez les itinéraires alternatifs.",
        "all_safe": "Voies d'évacuation normales et stables. Veuillez circuler prudemment.",
        "low_bandwidth": "ALERTE: Suivez les flèches vertes pour évacuer."
    },
    "pt": {  # Portuguese
        "evacuate_prompt": "Atenção: Por favor, evacue imediatamente do {start} pelo {exit}. Caminhe com calma, não corra.",
        "blocked_prompt": "Aviso de incidente: O portão {gate} está bloqueado. Redirecionando o fluxo de pessoas.",
        "congestion_prompt": "Congestionamento detectado na zona {zone}. Reduza a velocidade e siga as rotas alternativas.",
        "all_safe": "Rotas de evacuação normais e estáveis. Prossiga com cuidado.",
        "low_bandwidth": "ALERTA: Siga as setas verdes para evacuar."
    },
    "ar": {  # Arabic
        "evacuate_prompt": "تنبيه: يرجى الإخلاء فوراً من {start} عبر {exit}. تحرك بهدوء، لا تركض.",
        "blocked_prompt": "تنبيه حركة: البوابة {gate} مغلقة بسبب حادث. جاري إعادة توجيه المسارات.",
        "congestion_prompt": "تم رصد ازدحام في المنطقة {zone}. يرجى إبطاء السرعة واتباع طرق بديلة.",
        "all_safe": "مسارات الخروج طبيعية ومستقرة. تحرك بحذر.",
        "low_bandwidth": "تنبيه: اتبع الإشارات الخضراء للإخلاء."
    },
    "ja": {  # Japanese
        "evacuate_prompt": "警告：ただちに{start}から{exit}を通って避難してください。走らず、落ち着いて行動してください。",
        "blocked_prompt": "混雑・規制情報：{gate}は現在ブロックされています。避難ルートを再計算しています。",
        "congestion_prompt": "{zone}エリアで混雑を検知。速度を落とし、迂回ルートへ進んでください。",
        "all_safe": "避難ルートは現在正常です。足元に注意して進んでください。",
        "low_bandwidth": "警告：緑色の避難表示・矢印に従って移動してください。"
    },
    "en": {  # English (Default)
        "evacuate_prompt": "Attention: Please evacuate immediately from {start} via {exit}. Move calmly, do not run.",
        "blocked_prompt": "Congestion notice: Gate {gate} is currently blocked. Rerouting in progress.",
        "congestion_prompt": "High crowd density detected in {zone}. Please slow down and follow alternative routes.",
        "all_safe": "All evacuation routes are green. Proceed normally.",
        "low_bandwidth": "ALERT: Follow green directional arrows to evacuate."
    }
}


async def generate_accessible_instructions(
    event_type: str, 
    start_zone: str, 
    exit_gate: str, 
    lang: str = "en"
) -> str:
    """
    Generates dynamic translated guidance.
    Uses Gemini API if available, else falls back immediately to local dictionary.
    """
    lang = lang.lower()
    
    # Base English string construction
    if event_type == "evacuate":
        text_template = LOCAL_TRANSLATIONS["en"]["evacuate_prompt"].format(start=start_zone, exit=exit_gate)
    elif event_type == "blocked":
        text_template = LOCAL_TRANSLATIONS["en"]["blocked_prompt"].format(gate=exit_gate)
    elif event_type == "congestion":
        text_template = LOCAL_TRANSLATIONS["en"]["congestion_prompt"].format(zone=start_zone)
    else:
        text_template = LOCAL_TRANSLATIONS["en"]["all_safe"]

    # If language is English, return immediately without calling LLM
    if lang == "en":
        return text_template

    # Attempt to use Gemini for real-time translation and natural accessibility indexing
    if GEMINI_AVAILABLE:
        try:
            prompt = (
                f"You are a professional, high-clarity emergency stadium broadcaster for the FIFA World Cup 2026. "
                f"Translate the following emergency warning/instruction into natural, clear, and urgent {lang}. "
                f"Keep the instructions concise and easy to read. Output ONLY the translated text, with no extra commentary:\n"
                f"'{text_template}'"
            )
            response = await gemini_model.generate_content_async(prompt)
            translated_text = response.text.strip()
            if translated_text:
                return translated_text
        except Exception as e:
            logger.warning(f"Gemini API query failed: {e}. Reverting to local translations dictionary.")

    # Fallback to local high-speed translation lookup
    lang_dict = LOCAL_TRANSLATIONS.get(lang, LOCAL_TRANSLATIONS["en"])
    if event_type == "evacuate":
        return lang_dict["evacuate_prompt"].format(start=start_zone, exit=exit_gate)
    elif event_type == "blocked":
        return lang_dict["blocked_prompt"].format(gate=exit_gate)
    elif event_type == "congestion":
        return lang_dict["congestion_prompt"].format(zone=start_zone)
    else:
        return lang_dict["all_safe"]


# ---------------------------------------------------------------------------
# Feature #44 — AI Incident Triage Classifier
# ---------------------------------------------------------------------------

# Offline keyword-based triage fallback
TRIAGE_KEYWORDS = {
    "Medical":    ["collapse", "faint", "heart", "injury", "blood", "ambulance", "hurt", "medical", "unconscious", "breathing", "seizure"],
    "Security":   ["fight", "weapon", "threat", "aggress", "punch", "knife", "gun", "arrest", "suspicious", "bomb", "attack"],
    "Structural": ["collapse", "crack", "ceiling", "wall", "structural", "barrier", "railing", "broken", "floor"],
    "Crowd":      ["crush", "stampede", "overflow", "surge", "crowd", "packed", "congestion", "queue", "push", "fall"],
    "Equipment":  ["turnstile", "scanner", "screen", "power", "outage", "failure", "broken", "stuck", "gate", "display"],
}

SEVERITY_WORDS = {
    5: ["critical", "emergency", "fatal", "death", "dying", "extreme", "immediate", "urgent"],
    4: ["serious", "severe", "dangerous", "major", "bad", "collapse", "unconscious"],
    3: ["moderate", "significant", "problem", "issue", "concern", "blocked", "injured"],
    2: ["minor", "small", "slight", "slow", "complaint", "delay"],
    1: ["info", "question", "unclear", "uncertain"],
}

TRIAGE_ACTIONS = {
    "Medical":    "Dispatch first aid / medical response team immediately. Clear a path to the affected zone.",
    "Security":   "Alert security personnel and nearby police units. Do not approach subject alone.",
    "Structural": "Evacuate affected zone immediately. Notify structural engineering team and stadium management.",
    "Crowd":      "Activate crowd crush prevention protocol. Reroute nearby sections. Consider PA announcement.",
    "Equipment":  "Dispatch stadium operations team. Manually open or redirect affected gate. Notify IT.",
}


def _offline_triage(description: str) -> dict:
    """Keyword-matching fallback triage when Gemini is unavailable."""
    desc_lower = description.lower()
    
    # Determine category
    category_scores = {cat: 0 for cat in TRIAGE_KEYWORDS}
    for cat, keywords in TRIAGE_KEYWORDS.items():
        for kw in keywords:
            if kw in desc_lower:
                category_scores[cat] += 1
    category = max(category_scores, key=category_scores.get)
    if category_scores[category] == 0:
        category = "Crowd"  # default
    
    # Determine severity
    severity = 2  # default
    for sev, words in sorted(SEVERITY_WORDS.items(), reverse=True):
        for w in words:
            if w in desc_lower:
                severity = sev
                break
        else:
            continue
        break
    
    return {
        "category": category,
        "severity": severity,
        "recommended_action": TRIAGE_ACTIONS.get(category, "Notify stadium operations immediately."),
        "affected_zones": [],
        "confidence": "offline-fallback",
    }


async def classify_incident(description: str) -> dict:
    """
    AI Incident Triage Classifier (Feature #44).
    Accepts a free-text incident description from stadium staff and returns
    structured classification: category, severity (1–5), recommended action,
    and affected zones. Uses Gemini with structured JSON output; falls back to
    regex keyword matching for offline operation.
    """
    if GEMINI_AVAILABLE:
        try:
            prompt = (
                "You are a stadium incident triage AI for the FIFA World Cup 2026. "
                "Classify the following incident report and respond ONLY with valid JSON. "
                "JSON schema: {\"category\": \"Medical|Security|Structural|Crowd|Equipment\", "
                "\"severity\": 1-5 (1=low,5=critical), "
                "\"recommended_action\": \"brief ops instruction\", "
                "\"affected_zones\": [\"zone names if mentioned, else empty array\"], "
                "\"confidence\": \"high|medium|low\"}\n\n"
                f"Incident Report: \"{description}\""
            )
            response = await gemini_model.generate_content_async(prompt)
            raw = response.text.strip()
            # Extract JSON even if wrapped in markdown code fences
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except Exception as e:
            logger.warning(f"Gemini triage failed: {e}. Using offline keyword classifier.")
    
    return _offline_triage(description)


# ---------------------------------------------------------------------------
# Feature #23 — RAG-Powered Fan Chatbot (In-Prompt RAG Context)
# ---------------------------------------------------------------------------

STADIUM_KNOWLEDGE_BASE = """
=== SafePass 2026 Fan Knowledge Base ===
STADIUM: FIFA World Cup 2026 Host Stadium, 70,000 capacity.
GATES: Gate A1 & A2 (North entrance/exit), Gate B1 & B2 (East), Gate C1 & C2 (South), Gate D1 & D2 (West).
FIRST AID: First Aid stations located at Concourse North (near Section 101), Concourse South (near Section 106), and Concourse West (near Section 107). Emergency: dial 911.
RESTROOMS: Restrooms on every concourse level, marked by blue signs. Accessible restrooms at Wheelchair Zone East and West.
FOOD & BEVERAGE: Concession stands on all concourse rings. Halal-certified vendors at Gate A2 North and Gate C1 South. Vegan options at Gate D1 West concession.
ACCESSIBILITY: Wheelchair seating at Wheelchair Zone East and West. Elevator access at Gates B1 and D1. Audio guides available at the help desk.
SECURITY: No outside food or large bags. Prohibited: weapons, flares, drones, laser pointers. Metal detectors at all entrance gates.
LOST & FOUND: Located at Gate A1 North Operations Room. Open until 2 hours after the final whistle.
EVACUATION: Follow illuminated green exit signs. Listen for audio announcements. Do not use elevators during emergencies. Stay calm and move to your nearest gate.
TRANSPORT: Shuttle buses depart from Parking Lot C every 15 minutes post-match. Nearest metro station: Stadium Central, 5-minute walk from Gate D West.
WIFI: Free stadium WiFi: "FIFA2026-Guest". Password: "WorldCup2026". Note: may be slow at peak times. Use Low Bandwidth Mode in the SafePass app.
MATCH INFO: Gates open 3 hours before kick-off. VIP Suites check-in at Gate A2 North VIP entrance. Kickoff is typically announced 90 minutes after gate open.
PROHIBITED: Smoking, alcohol outside designated zones, drones, professional cameras without press credentials.
MEDICAL EMERGENCY: Press the red emergency button in the SafePass app or approach any steward in an orange vest. First response teams are stationed throughout.
"""

CHATBOT_OFFLINE_RESPONSES = {
    "exit": "Your nearest exit is the gate corresponding to your section. North sections → Gate A, East → Gate B, South → Gate C, West → Gate D.",
    "food": "Concession stands are located on all concourse rings. Halal options at Gate A2 and C1. Vegan at Gate D1.",
    "toilet": "Restrooms are on every concourse level, marked by blue signs. Accessible facilities at Wheelchair Zones East and West.",
    "first aid": "First Aid stations are at Concourse North (Section 101), Concourse South (Section 106), and Concourse West (Section 107).",
    "wifi": "Stadium WiFi: 'FIFA2026-Guest'. Password: 'WorldCup2026'. Consider Low Bandwidth Mode if slow.",
    "lost": "Lost & Found is at Gate A1 North Operations Room, open until 2 hours after the match ends.",
    "transport": "Shuttle buses depart from Parking Lot C every 15 minutes. Metro: Stadium Central station, 5 min from Gate D West.",
    "emergency": "Press the red emergency button in SafePass or find a steward in an orange vest immediately.",
    "default": "I'm unable to connect to the AI assistant right now. Please approach the nearest steward or operations desk for assistance.",
}


async def fan_chatbot_query(question: str, lang: str = "en", conversation_history: list = None) -> str:
    """
    RAG-Powered Fan Chatbot (Feature #23).
    Uses Gemini with an in-prompt knowledge base as retrieval context (equivalent to
    top-k RAG retrieval in production). Falls back to keyword matching offline.
    
    Args:
        question: Fan's natural language question.
        lang: ISO language code for response.
        conversation_history: List of {role, text} dicts for context.
    
    Returns:
        AI-generated answer grounded in the stadium knowledge base.
    """
    if GEMINI_AVAILABLE:
        try:
            history_str = ""
            if conversation_history:
                for entry in conversation_history[-4:]:  # Last 4 exchanges for context
                    history_str += f"{entry['role'].upper()}: {entry['text']}\n"
            
            lang_instruction = f" Respond in {lang} language." if lang != "en" else ""
            
            prompt = (
                f"You are SafePass 2026, a friendly and knowledgeable fan assistant for the FIFA World Cup 2026.\n"
                f"Use ONLY the information in the knowledge base below to answer the fan's question.\n"
                f"Be concise (max 3 sentences), helpful, and calm. If the answer is not in the knowledge base, "
                f"say you don't have that information and suggest they find a steward.{lang_instruction}\n\n"
                f"=== KNOWLEDGE BASE ===\n{STADIUM_KNOWLEDGE_BASE}\n=== END KNOWLEDGE BASE ===\n\n"
                f"{history_str}"
                f"FAN: {question}\n"
                f"SAFEPASS ASSISTANT:"
            )
            response = await gemini_model.generate_content_async(prompt)
            return response.text.strip()
        except Exception as e:
            logger.warning(f"Gemini chatbot failed: {e}. Using offline responses.")
    
    # Offline keyword fallback
    q_lower = question.lower()
    for kw, response in CHATBOT_OFFLINE_RESPONSES.items():
        if kw in q_lower:
            return response
    return CHATBOT_OFFLINE_RESPONSES["default"]
