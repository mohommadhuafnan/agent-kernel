"""FoodRescue AI Multilingual Localization and Language Detection Engine.

Provides:
1. Script-based and keyword-based language detection for English (en), Sinhala (si), and Tamil (ta).
2. Curated, natural localized conversational message catalogs.
3. Language preference resolution and fallback handling.
"""

import os
import re
import json
import logging
import requests
from typing import Optional, Dict, Any, List

logger = logging.getLogger("foodrescue.translation")

SUPPORTED_LANGUAGES = {"en", "si", "ta"}
DEFAULT_LANGUAGE = "en"

VALSEA_TRANSLATION_ENDPOINT = os.environ.get("VALSEA_TRANSLATION_ENDPOINT", "https://api.valsea.ai/v1/translations")

LANGUAGE_NAMES = {"en": "English", "si": "සිංහල (Sinhala)", "ta": "தமிழ் (Tamil)"}

# Unicode Script Ranges for Natural Script Detection
SINHALA_REGEX = re.compile(r"[\u0D80-\u0DFF]")
TAMIL_REGEX = re.compile(r"[\u0B80-\u0BFF]")


def detect_language(text: str) -> Optional[str]:
    """Detect language of incoming text based on script analysis.
    Returns 'si', 'ta', or 'en' if confident, or None if ambiguous."""
    if not text or not isinstance(text, str):
        return None

    s = text.strip()
    if not s:
        return None

    # Count characters in respective script ranges
    si_count = len(SINHALA_REGEX.findall(s))
    ta_count = len(TAMIL_REGEX.findall(s))

    total_len = max(1, len(s.replace(" ", "")))

    if si_count >= 2 or (si_count / total_len) > 0.2:
        return "si"
    if ta_count >= 2 or (ta_count / total_len) > 0.2:
        return "ta"

    # Check if purely latin text
    latin_count = len(re.findall(r"[a-zA-Z]", s))
    if latin_count / total_len > 0.5:
        return "en"


def is_language_selection_intent(text: str, in_language_menu: bool = False) -> Optional[str]:
    """Check if the user is explicitly selecting or requesting a language change.
    Handles:
    - Keywords & codes: 'sinhala', 'tamil', 'english', 'si', 'ta', 'en', 'L1'..'L3'
    - Numbers:
        6 -> English
        7 -> Sinhala
        8 -> Tamil
    - Natural language phrases:
        'change language to tamil', 'tamil please', 'தமிழ்', 'தமிழில் பேசுங்கள்', 'speak in tamil'
        'change language to sinhala', 'sinhala please', 'සිංහල', 'සිංහලෙන් කතා කරන්න', 'speak in sinhala'
        'change language to english', 'english please', 'speak in english'
    """
    if not text:
        return None
    clean = text.strip().lower()

    # Exact native script checks first
    if any(p in clean for p in ["தமிழ்", "தமிழில்", "தமிழுக்கு"]):
        return "ta"
    if any(p in clean for p in ["සිංහල", "සිංහලෙන්", "සිංහලෙන් කතා කරන්න"]):
        return "si"

    # Number-based language selection (6: English, 7: Sinhala, 8: Tamil)
    if clean in ["6", "6️⃣", "l1", "option 6", "opt 6", "select 6"]:
        return "en"
    if clean in ["7", "7️⃣", "l2", "option 7", "opt 7", "select 7"]:
        return "si"
    if clean in ["8", "8️⃣", "l3", "option 8", "opt 8", "select 8"]:
        return "ta"

    if in_language_menu:
        if clean in ["1"]:
            return "en"
        elif clean in ["2"]:
            return "si"
        elif clean in ["3"]:
            return "ta"

    # Exact codes or explicit change phrases
    if clean in ["tamil", "ta"] or any(
        p in clean for p in ["change language to tamil", "speak in tamil", "tamil please", "change to tamil", "in tamil", "tamil language"]
    ):
        return "ta"

    if clean in ["sinhala", "si"] or any(
        p in clean
        for p in ["change language to sinhala", "speak in sinhala", "sinhala please", "change to sinhala", "in sinhala", "sinhala language"]
    ):
        return "si"

    if clean in ["english", "en"] or any(
        p in clean
        for p in ["speak in english", "english please", "change language to english", "change to english", "in english", "english language"]
    ):
        return "en"

    # Safe regex for standalone language names or commands
    if re.search(r"\b(tamil)\b", clean) and (
        len(clean) <= 10 or any(w in clean for w in ["language", "speak", "switch", "change", "please", "in", "to"])
    ):
        return "ta"
    if re.search(r"\b(sinhala)\b", clean) and (
        len(clean) <= 10 or any(w in clean for w in ["language", "speak", "switch", "change", "please", "in", "to"])
    ):
        return "si"
    if re.search(r"\b(english)\b", clean) and (
        len(clean) <= 10 or any(w in clean for w in ["language", "speak", "switch", "change", "please", "in", "to"])
    ):
        return "en"

    return None


def is_greeting_message(text: str) -> bool:
    """Check if incoming text is a greeting or main menu intent (e.g. 'hi', 'hii', 'hiii', 'hey', 'hello', 'menu', 'help', 'start', etc.)."""
    if not text or not isinstance(text, str):
        return False
    clean = text.strip().lower()
    clean = re.sub(r"[!.,?~#@*_\-\s]+$", "", clean).strip()
    if clean in [
        "hi",
        "hii",
        "hiii",
        "hiiii",
        "hey",
        "heyy",
        "heyyy",
        "hello",
        "helloo",
        "hellooo",
        "hlo",
        "hai",
        "haai",
        "hay",
        "hola",
        "ola",
        "start",
        "join",
        "help",
        "menu",
        "info",
        "welcome",
        "greetings",
        "options",
        "මෙනුව",
        "ආයුබෝවන්",
        "வணக்கம்",
    ]:
        return True
    pattern = r"^(h+i+|h+e+y+|h+e+l+o+|hlo|hai|hay|hola|ola|good\s+(?:morning|afternoon|evening|day)|greetings\b|welcome\b|menu\b|help\b|start\b|options\b|ආයුබෝවන්|வணக்கம்)"
    return bool(re.match(pattern, clean))


def is_response_mode_intent(text: str) -> Optional[str]:
    """Detect if user is setting response mode preference ('voice' or 'text')."""
    if not text:
        return None
    clean = text.strip().lower()
    if any(
        p in clean
        for p in [
            "voice replies please",
            "voice only",
            "voice response",
            "voice message",
            "voice please",
            "send voice",
            "talk to me",
            "හඬ පණිවිඩ",
            "குரல் செய்தி",
        ]
    ):
        return "voice"
    if any(
        p in clean
        for p in ["text only", "text replies please", "text response", "text please", "send text", "no voice", "type only", "පෙළ පමණි", "உரை மட்டும்"]
    ):
        return "text"
    return None


LOCALIZED_MESSAGES: Dict[str, Dict[str, str]] = {
    # 1. First-Time User Onboarding Welcome
    "onboarding_welcome": {
        "en": (
            "👋 Welcome to FoodRescue AI!\n\n"
            "FoodRescue AI is an intelligent platform connecting hotels, restaurants, and households with surplus food to charities, shelters, and communities in need across Sri Lanka with volunteer couriers.\n\n"
            "How can I help you today?\n"
            "1️⃣ Donate surplus food (Hotels, restaurants, households)\n"
            "2️⃣ Request available food (Charities, orphanages, communities)\n"
            "3️⃣ Volunteer to collect and deliver food (Couriers & volunteers)\n"
            "4️⃣ Check your donation or pickup status\n"
            "5️⃣ Help & Info\n\n"
            "🌍 Choose your language / භාෂාව තෝරන්න / மொழியைத் தேர்ந்தெடுக்கவும்:\n"
            "6️⃣ English\n"
            "7️⃣ Sinhala (සිංහල)\n"
            "8️⃣ Tamil (தமிழ்)\n\n"
            '🎤 You can also send a voice message or simply tell me what you need (e.g. "I have 20 meal packets in Kegalle").'
        ),
        "si": (
            "👋 FoodRescue AI වෙත සාදරයෙන් පිළිගනිමු!\n\n"
            "FoodRescue AI යනු ශ්‍රී ලංකාව පුරා හෝටල්, ආපනශාලා සහ පරිත්‍යාගශීලීන් සතු අතිරික්ත ආහාර, ස්වේච්ඡා කුරියර්වරුන්ගේ සහායෙන් ළමා නිවාස, සුබසාධන සංවිධාන සහ ප්‍රජාවන් වෙත කඩිනමින් සම්බන්ධ කරන බුද්ධිමත් වේදිකාවකි.\n\n"
            "අද ඔබට මා උදව් කරන්නේ කෙසේද?\n"
            "1️⃣ අතිරික්ත ආහාර පරිත්‍යාග කිරීමට\n"
            "2️⃣ ලබාගත හැකි ආහාර ඉල්ලුම් කිරීමට (සංවිධාන සහ ප්‍රජාවන්)\n"
            "3️⃣ ආහාර එකතු කර බෙදාහැරීමට ස්වේච්ඡාවෙන් ඉදිරිපත් වීමට\n"
            "4️⃣ ඔබගේ පරිත්‍යාග හෝ බෙදාහැරීම් තත්ත්වය පරීක්ෂා කිරීමට\n"
            "5️⃣ උපකාර සහ තොරතුරු\n\n"
            "🌍 ඔබගේ භාෂාව තෝරන්න:\n"
            "6️⃣ English\n"
            "7️⃣ Sinhala (සිංහල)\n"
            "8️⃣ Tamil (தமிழ்)\n\n"
            '🎤 ඔබට හඬ පණිවිඩයක් ද එවිය හැක හෝ අවශ්‍ය දේ කෙලින්ම පැවසිය හැක (උදා: "මා ළඟ කෑගල්ලේ බත් පැකට් 20ක් තියෙනවා").'
        ),
        "ta": (
            "👋 FoodRescue AI இற்கு அன்புடன் வரவேற்கிறோம்!\n\n"
            "FoodRescue AI என்பது இலங்கை முழுவதும் ஹோட்டல்கள், உணவகங்கள் மற்றும் நன்கொடையாளர்களிடமிருந்து மீதமுள்ள உணவை பெற்று, தன்னார்வலர்கள் மூலம் தேவைப்படும் அமைப்புகள் மற்றும் சமூகங்களுடன் இணைக்கும் சிறந்த தளமாகும்.\n\n"
            "இன்று உங்களுக்கு எவ்வாறு உதவலாம்?\n"
            "1️⃣ உபரி உணவை தானமாக வழங்க\n"
            "2️⃣ கிடைக்கும் உணவைக் கோர (அமைப்புகள் & தொண்டு இல்லங்கள்)\n"
            "3️⃣ உணவைச் சேகரித்து வழங்க தன்னார்வலராக உதவ\n"
            "4️⃣ உங்கள் நன்கொடை அல்லது டெலிவரி நிலையைச் சரிபார்க்க\n"
            "5️⃣ உதவி மற்றும் தகவல்\n\n"
            "🌍 உங்கள் மொழியைத் தேர்ந்தெடுக்கவும்:\n"
            "6️⃣ English\n"
            "7️⃣ Sinhala (සිංහල)\n"
            "8️⃣ Tamil (தமிழ்)\n\n"
            '🎤 நீங்கள் குரல் செய்தியையும் அனுப்பலாம் அல்லது தேவையானதைக் கூறலாம் (எ.கா: "என்னிடம் கேகாலையில் 20 பொதி சோறு உள்ளது").'
        ),
    },
    # 2. Returning User Menu
    "returning_welcome": {
        "en": (
            "👋 *Welcome back to FoodRescue AI!*\n\n"
            "How can I help you today?\n\n"
            "1️⃣ Donate surplus food\n"
            "2️⃣ Find available food\n"
            "3️⃣ Volunteer for pickups\n"
            "4️⃣ Track my active request\n"
            "5️⃣ Language & Help"
        ),
        "si": (
            "👋 *නැවතත් සාදරයෙන් පිළිගනිමු!*\n\n"
            "අද ඔබට මා උදව් කරන්නේ කෙසේද?\n\n"
            "1️⃣ ආහාර පරිත්‍යාග කරන්න\n"
            "2️⃣ ආහාර ඉල්ලුම් කරන්න\n"
            "3️⃣ ස්වේච්ඡා බෙදාහැරීම්\n"
            "4️⃣ මගේ ඉල්ලීම් පරීක්ෂා කරන්න\n"
            "5️⃣ භාෂාව සහ උපකාර"
        ),
        "ta": (
            "👋 *மீண்டும் நல்வரவு!*\n\n"
            "இன்று உங்களுக்கு எவ்வாறு உதவலாம்?\n\n"
            "1️⃣ உணவு தானம் செய்ய\n"
            "2️⃣ உணவு பெற\n"
            "3️⃣ தன்னார்வலர் சேவை\n"
            "4️⃣ நிலையை அறிய\n"
            "5️⃣ மொழி மற்றும் உதவி"
        ),
    },
    "returning_donor_welcome": {
        "en": (
            "👋 Welcome back, {name}! 🌱\n\n"
            "What would you like to donate today?\n"
            "You can simply tell me what food you have (e.g. *'I have 30 meal packets of rice and curry'*)."
        ),
        "si": (
            "👋 නැවතත් සාදරයෙන් පිළිගනිමු, {name}! 🌱\n\n"
            "අද ඔබ පරිත්‍යාග කිරීමට බලාපොරොත්තු වන්නේ කුමක්ද?\n"
            "ඔබ සතුව ඇති ආහාර පිළිබඳව කෙලින්ම පැවසිය හැක (උදා: *'මා ළඟ බත් පාර්සල් 30ක් ඇත'*)."
        ),
        "ta": (
            "👋 மீண்டும் நல்வரவு, {name}! 🌱\n\n"
            "இன்று நீங்கள் என்ன தானம் செய்ய விரும்புகிறீர்கள்?\n"
            "உங்களிடம் உள்ள உணவை நேரடியாகக் கூறலாம் (எ.கா. *'என்னிடம் 30 பொதி சோறு உள்ளது'*)."
        ),
    },
    # 3. Language Selection Confirmation
    "language_selected": {
        "en": "English language selected. I will respond to your messages in English from now on.",
        "si": "සිංහල භාෂාව තෝරා ගන්නා ලදී. මින් පසු මම ඔබට සිංහලෙන් පිළිතුරු දෙන්නෙමි.",
        "ta": "தமிழ் மொழி தேர்ந்தெடுக்கப்பட்டது. இனி உங்கள் செய்திகளுக்கு தமிழில் பதிலளிப்பேன்.",
    },
    # 4. Location Prompt
    "request_location": {
        "en": (
            "Almost done! 📍\n"
            "Please send the pickup location using WhatsApp's Location option so the volunteer can navigate to the food.\n"
            "Tap ➕ → Location → Send your current location."
        ),
        "si": (
            "සියල්ල සූදානම් වෙමින් පවතී! 📍\n"
            "ස්වේච්ඡා කුරියර්වරයාට ආහාර වෙත පැමිණීමට කරුණාකර WhatsApp හි Location පහසුකම භාවිතයෙන් ස්ථානය එවන්න.\n"
            "Tap ➕ → Location → Send your current location."
        ),
        "ta": (
            "கிட்டத்தட்ட முடிந்துவிட்டது! 📍\n"
            "தன்னார்வலர் உணவை வந்து சேகரிக்க WhatsApp இன் Location வசதியைப் பயன்படுத்தி இருப்பிடத்தை அனுப்பவும்.\n"
            "Tap ➕ → Location → Send your current location."
        ),
    },
    # 5. Missing Info Extraction Prompt
    "missing_location": {
        "en": (
            "Almost done! 📍\n"
            "Please send the pickup location using WhatsApp's Location option so the volunteer can navigate to the food.\n"
            "Tap ➕ → Location → Send your current location."
        ),
        "si": (
            "සියල්ල සූදානම් වෙමින් පවතී! 📍\n"
            "ස්වේච්ඡා කුරියර්වරයාට ආහාර වෙත පැමිණීමට කරුණාකර WhatsApp හි Location පහසුකම භාවිතයෙන් ස්ථානය එවන්න.\n"
            "Tap ➕ → Location → Send your current location."
        ),
        "ta": (
            "கிட்டத்தட்ட முடிந்துவிட்டது! 📍\n"
            "தன்னார்வலர் உணவை வந்து சேகரிக்க WhatsApp இன் Location வசதியைப் பயன்படுத்தி இருப்பிடத்தை அனுப்பவும்.\n"
            "Tap ➕ → Location → Send your current location."
        ),
    },
    # 6. Volunteer Availability Confirmed
    "volunteer_available": {
        "en": ("🎉 *Great! You are now marked as AVAILABLE.*\n\n" "We will match you with nearby food rescue pickups shortly! 🚚"),
        "si": ("🎉 *ඉතා හොඳයි! ඔබ දැන් සූදානම් (AVAILABLE) ලෙස සටහන් විය.*\n\n" "අවට ඇති ආහාර බෙදාහැරීම් අවස්ථා පිළිබඳව අපි ඔබට වහාම දන්වන්නෙමු! 🚚"),
        "ta": (
            "🎉 *சிறப்பு! நீங்கள் இப்போது AVAILABLE ஆக பதிவு செய்யப்பட்டுள்ளீர்கள்.*\n\n"
            "அருகிலுள்ள உணவு சேகரிப்புப் பணிகள் பற்றி விரைவில் அறிவிப்போம்! 🚚"
        ),
    },
    # 7. Collection Confirmed
    "pickup_collected": {
        "en": (
            "🍱 *Food Collection Confirmed!*\n\n"
            "The donor and recipient have been notified.\n\n"
            "**Next Step**: Please deliver the meals to:\n"
            "• 🏢 **Recipient**: {dest_org} ({dest_loc})\n"
            "• 📍 **Navigation**: {map_link}\n\n"
            "Once handed over, reply *'Delivered'*."
        ),
        "si": (
            "🍱 *ආහාර ලබාගැනීම තහවුරු විය!*\n\n"
            "පරිත්‍යාගශීලියා සහ භාරගන්නා සංවිධානය දැනුවත් කරන ලදී.\n\n"
            "**ඊළඟ පියවර**: කරුණාකර ආහාර මෙහි භාරදෙන්න:\n"
            "• 🏢 **ස්ථානය**: {dest_org} ({dest_loc})\n"
            "• 📍 **Navigation**: {map_link}\n\n"
            "භාරදුන් පසු *'Delivered'* හෝ *'භාරදුන්නා'* යැයි දන්වන්න."
        ),
        "ta": (
            "🍱 *உணவு சேகரிப்பு உறுதிசெய்யப்பட்டது!*\n\n"
            "நன்கொடையாளருக்கும் பெறுநருக்கும் அறிவிக்கப்பட்டுள்ளது.\n\n"
            "**அடுத்த படி**: உணவை இங்கு கொண்டு சேர்க்கவும்:\n"
            "• 🏢 **பெறுநர்**: {dest_org} ({dest_loc})\n"
            "• 📍 **Navigation**: {map_link}\n\n"
            "ஒப்படைத்த பிறகு *'Delivered'* என்று பதிலளிக்கவும்."
        ),
    },
    # 8. Delivery Completed Celebration
    "delivery_completed": {
        "en": (
            "❤️ *Donation delivered successfully!*\n\n"
            "Your {quantity} {unit} of {food_type} have reached the recipient organization.\n"
            "Thank you for helping reduce food waste and support your community! 🙏"
        ),
        "si": (
            "❤️ *පරිත්‍යාගය සාර්ථකව භාරදෙන ලදී!*\n\n"
            "ඔබගේ {food_type} {quantity} {unit} සංවිධානය වෙත ළඟා විය.\n"
            "ආහාර අපතේ යාම වළක්වා ප්‍රජාවට සහාය වීම පිළිබඳව ඔබට ස්තූතියි! 🙏"
        ),
        "ta": (
            "❤️ *நன்கொடை வெற்றிகரமாக வழங்கப்பட்டது!*\n\n"
            "உங்கள் {quantity} {unit} {food_type} பெறும் அமைப்பை அடைந்தது.\n"
            "உணவு வீணாவதைத் தடுத்து சமூகத்திற்கு உதவியதற்கு மிக்க நன்றி! 🙏"
        ),
    },
    # 9. Donor Workflow Slot Prompts
    "donor_ask_name": {
        "en": "Great! 🙏 I've recorded {quantity} {unit} of {food_type}. 🍚 📍\n\nWhat is your name or business/hotel name?",
        "si": "ස්තූතියි! 🙏 මා {food_type} {quantity} {unit} සටහන් කරගත්තා. 🍚 📍\n\nඔබගේ නම හෝ ව්‍යාපාරික/හෝටල් නාමය කුමක්ද?",
        "ta": "நன்றி! 🙏 நான் {quantity} {unit} {food_type} பதிவு செய்துள்ளேன். 🍚 📍\n\nஉங்கள் பெயர் அல்லது வணிக/ஹோட்டல் பெயர் என்ன?",
    },
    "donor_ask_city": {
        "en": "Thanks, {name}! 📍 I've noted {quantity} {unit} of {food_type}. 🍚\n\nWhich **district** or city in Sri Lanka is the food currently located in? (e.g. Kegalle, Kandy, Colombo, Gampaha, Kurunegala, Galle)",
        "si": "ස්තූතියි, {name}! 📍 මා {food_type} {quantity} {unit} සටහන් කරගත්තා. 🍚\n\nආහාර දැනට පිහිටා ඇති **දිස්ත්‍රික්කය** හෝ නගරය කුමක්ද? (උදා: කෑගල්ල, මහනුවර, කොළඹ, ගම්පහ, කුරුණෑගල, ගාල්ල)",
        "ta": "நன்றி, {name}! 📍 நான் {quantity} {unit} {food_type} பதிவு செய்துள்ளேன். 🍚\n\nஉணவு தற்போது இலங்கையின் எந்த **மாவட்டம்** அல்லது பகுதியில் உள்ளது? (எ.கா: கேகாலை, கண்டி, கொழும்பு, கம்பஹா, குருநாகல், காலி)",
    },
    "donor_ask_district": {
        "en": "Thanks, {name}! 📍 I've noted {quantity} {unit} of {food_type}. 🍚\n\nWhich **district** in Sri Lanka is the food currently located in? (e.g. Kegalle, Kandy, Colombo, Gampaha, Kurunegala, Galle)",
        "si": "ස්තූතියි, {name}! 📍 මා {food_type} {quantity} {unit} සටහන් කරගත්තා. 🍚\n\nආහාර දැනට පිහිටා ඇති **දිස්ත්‍රික්කය** කුමක්ද? (උදා: කෑගල්ල, මහනුවර, කොළඹ, ගම්පහ, කුරුණෑගල, ගාල්ල)",
        "ta": "நன்றி, {name}! 📍 நான் {quantity} {unit} {food_type} பதிவு செய்துள்ளேன். 🍚\n\nஉணவு தற்போது இலங்கையின் எந்த **மாவட்டத்தில்** உள்ளது? (எ.கா: கேகாலை, கண்டி, கொழும்பு, கம்பஹா, குருநாகல், காலி)",
    },
    "donor_ask_deadline": {
        "en": "Got it. 📍 Pickup location: {city}\n\nWhat time will the food donation be available until for collection / pickup? (e.g. 'Before 8 PM', 'By 6:30 PM')",
        "si": "තේරුම් ගත්තා. 📍 ලබාගැනීමේ ස්ථානය: {city}\n\nආහාර පරිත්‍යාගය එකතු කරගත හැකි අවසන් වේලාව කවදාද? (උදා. 'රාත්‍රී 8 ට පෙර')",
        "ta": "புரிந்தது. 📍 சேகரிக்கும் இடம்: {city}\n\nஉணவு தானத்தை எத்தனை மணிக்குள் சேகரிக்க முடியும்? (எ.கா. 'இரவு 8 மணிக்கு முன்')",
    },
    "donor_ask_location_native": {
        "en": (
            "Got it! 📍 Recorded {quantity} {unit} of {food_type} in {city}.\n\n"
            "📍 **Step 4: Please Share Your Pickup Live Location Pin**\n\n"
            "Tap ➕ (or 📎) → **Location** → **'Send your current location'** 📍 so our volunteer couriers can navigate directly to collect the food!"
        ),
        "si": (
            "ස්තූතියි! 📍 {city} හි {food_type} {quantity} {unit} සටහන් කරගත්තා.\n\n"
            "📍 **පියවර 4: කරුණාකර ඔබගේ ආහාර ලබාගැනීමේ ස්ථානය WhatsApp හරහා එවන්න**\n\n"
            "➕ (හෝ 📎) ඔබා → **ස්ථානය (Location)** → **'වත්මන් ස්ථානය එවන්න'** 📍 යවන්න. එවිට ස්වේච්ඡා කුරියර්වරුන්ට ආහාර ලබාගැනීමට පැමිණිය හැක!"
        ),
        "ta": (
            "நன்றி! 📍 {city} பகுதியில் {quantity} {unit} {food_type} பதிவு செய்யப்பட்டது.\n\n"
            "📍 **படி 4: உங்கள் உணவு சேகரிக்கும் நேரலை இருப்பிடத்தை (Location Pin) பகிரவும்**\n\n"
            "➕ (அல்லது 📎) அழுத்தி → **Location** → **'Send your current location'** 📍 என்பதை அனுப்பவும். இதன் மூலம் தன்னார்வலர்கள் உணவை வந்து சேகரிக்க முடியும்!"
        ),
    },
    "donor_location_received": {
        "en": "📍 Pickup location received successfully.",
        "si": "📍 ලබාගැනීමේ ස්ථානය සාර්ථකව ලැබිණි.",
        "ta": "📍 உணவு சேகரிக்கும் இருப்பிடம் வெற்றிகரமாகப் பெறப்பட்டது.",
    },
    "slot_ask_quantity": {
        "en": "Great! 👍 I noted {food_type}.\n\n📦 *How many packets or portions do you have available?*",
        "si": "ඉතා හොඳයි! 👍 මා {food_type} සටහන් කරගත්තා.\n\n📦 *ඔබ සතුව ආහාර පාර්සල් / ප්‍රමාණය කොපමණ තිබේද?*",
        "ta": "சிறப்பு! 👍 {food_type} விபரம் பதிவு செய்யப்பட்டது.\n\n📦 *உங்களிடம் எத்தனை பொதிகள் / உணவுகள் உள்ளன?*",
    },
    "slot_ask_location": {
        "en": (
            "📍 **Step 4: Please Share Your Pickup Live Location Pin**\n\n"
            "Tap ➕ (or 📎) → **Location** → **'Send your current location'** 📍 so our volunteer couriers can navigate directly to collect the food!"
        ),
        "si": (
            "📍 **පියවර 4: කරුණාකර ඔබගේ ආහාර ලබාගැනීමේ ස්ථානය WhatsApp හරහා එවන්න**\n\n"
            "➕ (හෝ 📎) ඔබා → **ස්ථානය (Location)** → **'වත්මන් ස්ථානය එවන්න'** 📍 යවන්න. එවිට ස්වේච්ඡා කුරියර්වරුන්ට ආහාර ලබාගැනීමට පැමිණිය හැක!"
        ),
        "ta": (
            "📍 **படி 4: உங்கள் உணவு சேகரிக்கும் நேரலை இருப்பிடத்தை (Location Pin) பகிரவும்**\n\n"
            "➕ (அல்லது 📎) அழுத்தி → **Location** → **'Send your current location'** 📍 என்பதை அனுப்பவும். இதன் மூலம் தன்னார்வலர்கள் உணவை வந்து சேகரிக்க முடியும்!"
        ),
    },
    "slot_ask_deadline": {
        "en": "Until what time can the food be collected?",
        "si": "ආහාර එකතු කරගත හැකි අවසන් වේලාව කවදාද?",
        "ta": "உணவை எத்தனை மணிக்குள் சேகரிக்க முடியும்?",
    },
    "donation_summary_confirm": {
        "en": (
            "📦 *Donation Summary*\n\n"
            "👤 Donor: {donor_name}\n"
            "🏢 Business: {business_name}\n"
            "🍚 Food: {food_type}\n"
            "📦 Quantity: {quantity} {unit}\n"
            "📍 Pickup area: {city}\n"
            "⏰ Pickup deadline: {deadline}\n"
            "📞 Contact: {contact_phone}\n"
            "📍 Pickup location: Received\n\n"
            "Please check the details above.\n"
            "Reply *Confirm* to publish this donation.\n"
            "Reply *Edit* if you want to change anything."
        ),
        "si": (
            "📦 *පරිත්‍යාග සාරාංශය*\n\n"
            "👤 පරිත්‍යාගශීලී: {donor_name}\n"
            "🏢 ව්‍යාපාරය: {business_name}\n"
            "🍚 ආහාර: {food_type}\n"
            "📦 ප්‍රමාණය: {quantity} {unit}\n"
            "📍 ප්‍රදේශය: {city}\n"
            "⏰ අවසන් වේලාව: {deadline}\n"
            "📞 දුරකථන: {contact_phone}\n"
            "📍 ස්ථානය: ලැබිණි\n\n"
            "කරුණාකර ඉහත විස්තර පරීක්ෂා කරන්න.\n"
            "මෙම පරිත්‍යාගය පළ කිරීමට *Confirm* (තහවුරුයි) ලෙස පිළිතුරු දෙන්න.\n"
            "වෙනස් කිරීමට *Edit* යැයි පිළිතුරු දෙන්න."
        ),
        "ta": (
            "📦 *நன்கொடை சுருக்கம்*\n\n"
            "👤 நன்கொடையாளர்: {donor_name}\n"
            "🏢 வணிகம்: {business_name}\n"
            "🍚 உணவு: {food_type}\n"
            "📦 அளவு: {quantity} {unit}\n"
            "📍 பகுதி: {city}\n"
            "⏰ இறுதி நேரம்: {deadline}\n"
            "📞 தொடர்பு: {contact_phone}\n"
            "📍 இருப்பிடம்: பெறப்பட்டது\n\n"
            "மேலே உள்ள விபரங்களைச் சரிபார்க்கவும்.\n"
            "இந்த நன்கொடையை வெளியிட *Confirm* என்று பதிலளிக்கவும்.\n"
            "மாற்ற விரும்பினால் *Edit* என்று பதிலளிக்கவும்."
        ),
    },
    "donation_created_card": {
        "en": (
            "✅ *Donation Created Successfully!*\n\n"
            "Thank you, {donor_name}! 🙏\n"
            "🍚 Food: {quantity} {unit} of {food_type}\n"
            "📍 Pickup: {city}\n"
            "⏰ Deadline: {deadline}\n"
            "🆔 Donation ID: {donation_id}\n"
            "📦 Status: PICKUP_ASSIGNED\n\n"
            "Your donation has been added to the FoodRescue network.\n"
            "🔎 We are coordinating with recipient organizations and volunteer couriers.\n\n"
            "Please wait while we coordinate the pickup. 🚚"
        ),
        "si": (
            "✅ *පරිත්‍යාගය සාර්ථකව නිර්මාණය විය!*\n\n"
            "ස්තූතියි, {donor_name}! 🙏\n"
            "🍚 ආහාර: {food_type} {quantity} {unit}\n"
            "📍 ස්ථානය: {city}\n"
            "⏰ අවසන් වේලාව: {deadline}\n"
            "🆔 Donation ID: {donation_id}\n"
            "📦 Status: PICKUP_ASSIGNED\n\n"
            "ඔබගේ පරිත්‍යාගය FoodRescue ජාලයට එක් කරන ලදී.\n"
            "🔎 අපි දැන් සුදුසු භාරගන්නා සංවිධානයක් සහ ස්වේච්ඡා කුරියර්වරයෙකු සම්බන්ධ කරමින් සිටිමු.\n\n"
            "කරුණාකර රැඳී සිටින්න. 🚚"
        ),
        "ta": (
            "✅ *நன்கொடை வெற்றிகரமாக உருவாக்கப்பட்டது!*\n\n"
            "நன்றி, {donor_name}! 🙏\n"
            "🍚 உணவு: {quantity} {unit} {food_type}\n"
            "📍 இடம்: {city}\n"
            "⏰ நேரம்: {deadline}\n"
            "🆔 Donation ID: {donation_id}\n"
            "📦 Status: PICKUP_ASSIGNED\n\n"
            "உங்கள் நன்கொடை FoodRescue நெட்வொர்க்கில் சேர்க்கப்பட்டுள்ளது.\n"
            "🔎 நாங்கள் இப்போது பெறும் அமைப்பு மற்றும் தன்னார்வ கூரியரை இணைக்கிறோம்.\n\n"
            "தயவுசெய்து காத்திருக்கவும். 🚚"
        ),
    },
    "donor_matched_update": {
        "en": (
            "🏢 Good news, {donor_name}!\n\n"
            "Your food donation has been matched with a suitable recipient organization.\n"
            "🚚 We are now looking for an available volunteer courier to collect and deliver the food.\n"
            "We will notify you when the pickup is accepted."
        ),
        "si": (
            "🏢 සුභ ආරංචියක්, {donor_name}!\n\n"
            "ඔබගේ ආහාර පරිත්‍යාගය සුදුසු සංවිධානයක් සමඟ සම්බන්ධ කරන ලදී.\n"
            "🚚 ආහාර රැගෙන ගොස් භාරදීමට ස්වේච්ඡා කුරියර්වරයෙකු සම්බන්ධ කරමින් සිටිමු.\n"
            "පරිත්‍යාගය භාරගත් පසු අපි ඔබට දන්වන්නෙමු."
        ),
        "ta": (
            "🏢 நற்செய்தி, {donor_name}!\n\n"
            "உங்கள் உணவு நன்கொடை பொருத்தமான பெறும் அமைப்போடு இணைக்கப்பட்டுள்ளது.\n"
            "🚚 உணவை சேகரித்து வழங்க தன்னார்வலரைத் தேடுகிறோம்.\n"
            "பணி ஏற்கப்பட்டதும் உங்களுக்கு அறிவிப்போம்."
        ),
    },
    "donor_volunteer_assigned_update": {
        "en": (
            "🚚 Great news, {donor_name}!\n\n"
            "A volunteer courier has accepted your donation pickup.\n"
            "The courier is preparing to collect the food and deliver it to the matched recipient organization.\n"
            "You will receive another update when the food is collected."
        ),
        "si": (
            "🚚 සුභ ආරංචියක්, {donor_name}!\n\n"
            "ස්වේච්ඡා කුරියර්වරයෙකු ඔබගේ ආහාර ලබාගැනීම භාරගෙන ඇත.\n"
            "ආහාර රැගෙන යාමට කුරියර්වරයා සූදානම් වෙමින් සිටී."
        ),
        "ta": (
            "🚚 நற்செய்தி, {donor_name}!\n\n"
            "ஒரு தன்னார்வ கூரியர் உங்கள் உணவு சேகரிப்பை ஏற்றுக்கொண்டார்.\n"
            "உணவை சேகரித்து வழங்க கூரியர் தயாராகி வருகிறார்."
        ),
    },
    "donor_volunteer_location_update": {
        "en": (
            "🚚 Your volunteer courier has accepted the pickup.\n\n"
            "Volunteer: {volunteer_name}\n"
            "📍 Current volunteer location:\n"
            "{map_link}\n\n"
            "The courier is preparing to collect your food."
        ),
        "si": (
            "🚚 ඔබගේ ස්වේච්ඡා කුරියර්වරයා ගමන් ආරම්භ කර ඇත.\n\n"
            "කුරියර්: {volunteer_name}\n"
            "📍 වත්මන් ස්ථානය:\n"
            "{map_link}\n\n"
            "ආහාර එකතු කරගැනීමට කුරියර්වරයා පැමිණෙමින් සිටී."
        ),
        "ta": (
            "🚚 உங்கள் தன்னார்வ கூரியர் பணியை ஏற்றுக்கொண்டார்.\n\n"
            "தன்னார்வலர்: {volunteer_name}\n"
            "📍 தற்போதைய இருப்பிடம்:\n"
            "{map_link}\n\n"
            "கூரியர் உணவை சேகரிக்க தயாராகி வருகிறார்."
        ),
    },
    "donor_food_collected_update": {
        "en": "📦 Your food has been collected successfully.",
        "si": "📦 ඔබගේ ආහාර සාර්ථකව එකතු කරගන්නා ලදී.",
        "ta": "📦 உங்கள் உணவு வெற்றிகரமாக சேகரிக்கப்பட்டது.",
    },
    "volunteer_pickup_offer": {
        "en": (
            "🚚 FoodRescue Pickup Available\n\n"
            "🍚 Food: {quantity} {unit} {food_type}\n"
            "📦 Quantity: {quantity} {unit}\n"
            "📍 Pickup: {pickup_city}\n"
            "🏢 Delivery: {recipient_name}\n"
            "⏰ Deadline: {deadline}\n"
            "📏 Estimated distance: {distance_km} km\n"
            "💰 Estimated transport support: LKR {transport_support}\n"
            "🗺️ Route:\n"
            "{route_url}\n\n"
            "Would you like to accept this pickup?\n"
            "Reply:\n"
            "1️⃣ Accept\n"
            "2️⃣ Reject"
        ),
        "si": (
            "🚚 ආහාර බෙදාහැරීමේ අවස්ථාවක් ඇත\n\n"
            "🍚 ආහාර: {food_type} {quantity} {unit}\n"
            "📦 ප්‍රමාණය: {quantity} {unit}\n"
            "📍 ලබාගැනීම: {pickup_city}\n"
            "🏢 භාරදීම: {recipient_name}\n"
            "⏰ අවසන් වේලාව: {deadline}\n"
            "📏 දුර: {distance_km} km\n"
            "💰 ඇස්තමේන්තුගත ප්‍රවාහන සහනාධාරය: රු. {transport_support}\n"
            "🗺️ මාර්ගය:\n"
            "{route_url}\n\n"
            "මෙම බෙදාහැරීම භාරගැනීමට කැමතිද?\n"
            "පිළිතුරු දෙන්න:\n"
            "1️⃣ Accept\n"
            "2️⃣ Reject"
        ),
        "ta": (
            "🚚 உணவு சேகரிப்புப் பணி கிடைத்துள்ளது\n\n"
            "🍚 உணவு: {quantity} {unit} {food_type}\n"
            "📦 அளவு: {quantity} {unit}\n"
            "📍 பெறுமிடம்: {pickup_city}\n"
            "🏢 சேருமிடம்: {recipient_name}\n"
            "⏰ நேரம்: {deadline}\n"
            "📏 தூரம்: {distance_km} km\n"
            "💰 பயண உதவித்தொகை: ரூ. {transport_support}\n"
            "🗺️ பாதை:\n"
            "{route_url}\n\n"
            "இந்த பணியை ஏற்க விரும்புகிறீர்களா?\n"
            "பதிலளிக்கவும்:\n"
            "1️⃣ Accept\n"
            "2️⃣ Reject"
        ),
    },
    "volunteer_already_claimed": {
        "en": "Sorry, this pickup has already been accepted by another volunteer. Thank you for responding! 🙏",
        "si": "සමාවන්න, මෙම බෙදාහැරීම දැනටමත් වෙනත් ස්වේච්ඡා සාමාජිකයෙකු විසින් භාරගෙන ඇත. ප්‍රතිචාර දැක්වීමට ස්තූතියි! 🙏",
        "ta": "மன்னிக்கவும், இந்த பணி ஏற்கனவே மற்றொரு தன்னார்வலரால் ஏற்றுக்கொள்ளப்பட்டது. பதிலளித்ததற்கு நன்றி! 🙏",
    },
    "response_mode_updated": {
        "en": "🎙️ Response mode preference updated to *{mode}*.",
        "si": "🎙️ ප්‍රතිචාර මාදිලිය *{mode}* ලෙස යාවත්කාලීන විය.",
        "ta": "🎙️ பதில் பயன்முறை *{mode}* ஆக மாற்றப்பட்டது.",
    },
    "returning_donor_welcome": {
        "en": (
            "👋 *Welcome back to FoodRescue AI, {name}!* (Registered Donor)\n\n"
            "You currently have active donations on file.\n\n"
            "What would you like to do today?\n"
            "1️⃣ Donate more food\n"
            "2️⃣ Check my donation status\n"
            "3️⃣ Update my details\n"
            "4️⃣ Help & Language"
        ),
        "si": (
            "👋 *නැවතත් සාදරයෙන් පිළිගනිමු {name}!* (ලියාපදිංචි පරිත්‍යාගශීලී)\n\n"
            "අද ඔබට කළ යුතු දේ කුමක්ද?\n"
            "1️⃣ තවත් ආහාර පරිත්‍යාග කරන්න\n"
            "2️⃣ මගේ පරිත්‍යාග තත්ත්වය පරීක්ෂා කරන්න\n"
            "3️⃣ තොරතුරු යාවත්කාලීන කරන්න\n"
            "4️⃣ උපකාර සහ භාෂාව"
        ),
        "ta": (
            "👋 *மீண்டும் நல்வரவு {name}!* (பதிவுசெய்த நன்கொடையாளர்)\n\n"
            "இன்று நீங்கள் என்ன செய்ய விரும்புகிறீர்கள்?\n"
            "1️⃣ மேலும் உணவு தானம் செய்ய\n"
            "2️⃣ நன்கொடை நிலையை அறிய\n"
            "3️⃣ விபரங்களை மாற்ற\n"
            "4️⃣ உதவி மற்றும் மொழி"
        ),
    },
    # 10. Error Recovery
    "error_recovery": {
        "en": ("I'm sorry, I'm having trouble processing that right now.\n\n" "Please try again in a moment. 🙏"),
        "si": ("සමාවන්න, එම ඉල්ලීම සැකසීමේදී සුළු ගැටලුවක් ඇති විය.\n\n" "කරුණාකර මොහොතකින් නැවත උත්සාහ කරන්න. 🙏"),
        "ta": ("மன்னிக்கவும், அந்த கோரிக்கையை செயலாக்குவதில் சிக்கல் ஏற்பட்டது.\n\n" "தயவுசெய்து சிறிது நேரத்தில் மீண்டும் முயற்சிக்கவும். 🙏"),
    },
    # 11. Status Queries & Workflow Coordination Cards
    "donation_status_card": {
        "en": (
            "📦 **Your Latest Donation**\n\n"
            "• **Donation ID**: `{donation_id}`\n"
            "• **Food**: {quantity} {unit} of {food_type}\n"
            "• **Location**: 📍 {location}\n"
            "• **Status**: `{status}`{task_info}\n\n"
            "Thank you for helping rescue food! ❤️"
        ),
        "si": (
            "📦 **ඔබගේ නවතම පරිත්‍යාගය**\n\n"
            "• **පරිත්‍යාග අංකය**: `{donation_id}`\n"
            "• **ආහාර**: {food_type} {quantity} {unit}\n"
            "• **ස්ථානය**: 📍 {location}\n"
            "• **තත්ත්වය**: `{status}`{task_info}\n\n"
            "ආහාර අපතේ යාම වැළැක්වීමට සහාය වීම ගැන ස්තූතියි! ❤️"
        ),
        "ta": (
            "📦 **உங்கள் சமீபத்திய நன்கொடை**\n\n"
            "• **நன்கொடை எண்**: `{donation_id}`\n"
            "• **உணவு**: {quantity} {unit} {food_type}\n"
            "• **இடம்**: 📍 {location}\n"
            "• **நிலை**: `{status}`{task_info}\n\n"
            "உணவை மீட்க உதவியதற்கு நன்றி! ❤️"
        ),
    },
    "donation_status_empty": {
        "en": (
            "📦 **No Active Donation Found**\n\n"
            "You don't have any active donations registered under your phone number right now.\n"
            "Reply **1** or say *'I have food to donate'* to create a new donation."
        ),
        "si": (
            "📦 **සක්‍රිය පරිත්‍යාගයක් හමු නොවීය**\n\n"
            "ඔබගේ දුරකථන අංකය යටතේ දැනට සක්‍රිය පරිත්‍යාගයක් ලියාපදිංචි වී නොමැත.\n"
            "නව පරිත්‍යාගයක් එක් කිරීමට **1** ලෙස පිළිතුරු දෙන්න හෝ *'මට ආහාර පරිත්‍යාග කිරීමට ඇත'* යැයි පවසන්න."
        ),
        "ta": (
            "📦 **செயலில் உள்ள நன்கொடை எதுவும் இல்லை**\n\n"
            "உங்கள் தொலைபேசி எண்ணின் கீழ் தற்போது செயலில் உள்ள நன்கொடைகள் எதுவும் பதிவு செய்யப்படவில்லை.\n"
            "புதிய நன்கொடையை உருவாக்க **1** என்று பதிலளிக்கவும் அல்லது *'உணவு தானம் செய்ய விரும்புகிறேன்'* என்று கூறவும்."
        ),
    },
    "pickup_status_card": {
        "en": (
            "🚚 **Pickup Status Update**\n\n"
            "• **Pickup ID**: `{task_id}`\n"
            "• **Status**: `{status}`\n"
            "• **From**: 📍 {pickup_location}\n"
            "• **To**: 🏢 {delivery_location}\n"
            "• **Scheduled Time**: ⏰ {scheduled_time}\n"
            "• **Volunteer**: {volunteer_name}\n\n"
            "I'll keep you posted as the pickup progresses!"
        ),
        "si": (
            "🚚 **බෙදාහැරීමේ තත්ත්ව යාවත්කාලීනය**\n\n"
            "• **කාර්ය අංකය**: `{task_id}`\n"
            "• **තත්ත්වය**: `{status}`\n"
            "• **ලබාගැනීම**: 📍 {pickup_location}\n"
            "• **භාරදීම**: 🏢 {delivery_location}\n"
            "• **නියමිත වේලාව**: ⏰ {scheduled_time}\n"
            "• **ස්වේච්ඡා සාමාජිකයා**: {volunteer_name}\n\n"
            "බෙදාහැරීමේ කටයුතු සිදුවන විට අපි ඔබට දන්වන්නෙමු!"
        ),
        "ta": (
            "🚚 **சேகரிப்பு நிலை புதுப்பிப்பு**\n\n"
            "• **பணி எண்**: `{task_id}`\n"
            "• **நிலை**: `{status}`\n"
            "• **பெறுமிடம்**: 📍 {pickup_location}\n"
            "• **சேருமிடம்**: 🏢 {delivery_location}\n"
            "• **நேரம்**: ⏰ {scheduled_time}\n"
            "• **தன்னார்வலர்**: {volunteer_name}\n\n"
            "பணி முன்னேறும் போது உங்களுக்கு அறிவிப்போம்!"
        ),
    },
    "pickup_status_empty": {
        "en": ("🚚 **No Active Pickup Found**\n\n" "There are currently no active pickup tasks assigned to or linked with your account."),
        "si": ("🚚 **සක්‍රිය බෙදාහැරීම් කාර්යයක් හමු නොවීය**\n\n" "ඔබගේ ගිණුමට සම්බන්ධ සක්‍රිය බෙදාහැරීම් කාර්යයක් දැනට නොමැත."),
        "ta": ("🚚 **செயலில் உள்ள சேகரிப்பு பணிகள் இல்லை**\n\n" "உங்கள் கணக்குடன் இணைக்கப்பட்ட செயலில் உள்ள பணிகள் எதுவும் தற்போது இல்லை."),
    },
    "donation_cancelled_success": {
        "en": (
            "🛑 **Donation Cancelled**\n\n"
            "Donation `{donation_id}` and its associated pickup coordination have been cancelled.\n"
            "Let me know if you need help with anything else!"
        ),
        "si": (
            "🛑 **පරිත්‍යාගය අවලංගු කරන ලදී**\n\n"
            "පරිත්‍යාග අංක `{donation_id}` සහ ඊට අදාළ බෙදාහැරීම් කටයුතු අවලංගු කර ඇත.\n"
            "ඔබට වෙනත් යමකට උපකාර අවශ්‍ය නම් දන්වන්න!"
        ),
        "ta": (
            "🛑 **நன்கொடை ரத்து செய்யப்பட்டது**\n\n"
            "நன்கொடை `{donation_id}` மற்றும் அதனுடன் தொடர்புடைய சேகரிப்பு ரத்து செய்யப்பட்டுள்ளது.\n"
            "வேறு உதவி தேவைப்பட்டால் தெரியப்படுத்தவும்!"
        ),
    },
    "donation_cancelled_draft_success": {
        "en": ("🛑 **Donation Cancelled**\n\n" "Your active donation draft has been cancelled. Let me know if you need anything else!"),
        "si": ("🛑 **පරිත්‍යාගය අවලංගු කරන ලදී**\n\n" "ඔබගේ සක්‍රිය පරිත්‍යාග සටහන අවලංගු කරන ලදී. ඔබට වෙනත් යමකට උපකාර අවශ්‍ය නම් දන්වන්න!"),
        "ta": (
            "🛑 **நன்கொடை ரத்து செய்யப்பட்டது**\n\n"
            "உங்கள் நன்கொடை வரைவு ரத்து செய்யப்பட்டுள்ளது. வேறு ஏதேனும் உதவி தேவைப்பட்டால் தெரியப்படுத்தவும்!"
        ),
    },
    "donation_ask_food_type": {
        "en": (
            "🍱 *What type of Food do you have for Donation?*\n\n"
            "1️⃣ Rice & Curry\n"
            "2️⃣ Bread & Bakery\n"
            "3️⃣ Vegetarian Meals\n"
            "4️⃣ Biryani\n"
            "5️⃣ Other\n\n"
            "Reply with a number or simply describe the food."
        ),
        "si": (
            "🍱 *ඔබ සතුව පරිත්‍යාගය සඳහා ඇති ආහාර වර්ගය කුමක්ද?*\n\n"
            "1️⃣ බත් සහ ව්‍යංජන\n"
            "2️⃣ පාන් සහ බේකරි නිෂ්පාදන\n"
            "3️⃣ නිර්මාංශ ආහාර\n"
            "4️⃣ බිරියානි\n"
            "5️⃣ වෙනත්\n\n"
            "අංකය හෝ ආහාර පිළිබඳ විස්තරය එවන්න."
        ),
        "ta": (
            "🍱 *தானம் செய்ய உங்களிடம் என்ன வகை உணவு உள்ளது?*\n\n"
            "1️⃣ சோறும் கறியும்\n"
            "2️⃣ ரொட்டி & பேக்கரி\n"
            "3️⃣ சைவ உணவுகள்\n"
            "4️⃣ பிரியாணி\n"
            "5️⃣ மற்றவை\n\n"
            "எண்ணை உள்ளிடவும் அல்லது உணவை விவரிக்கவும்."
        ),
    },
    "donation_ask_food_type_simple": {
        "en": "🍱 *What type of food do you have available?* (e.g. Rice, Bread, Vegetarian Meals)",
        "si": "🍱 *ඔබ සතුව ඇති ආහාර වර්ගය කුමක්ද?* (උදා: බත්, පාන්, නිර්මාංශ ආහාර)",
        "ta": "🍱 *உங்களிடம் என்ன வகை உணவு உள்ளது?* (எ.கா: சோறு, ரொட்டி, சைவ உணவு)",
    },
    # 12. Organization Support Progressive Slot-Filling
    "org_ask_name": {
        "en": (
            "🏢 **Recipient Organization Support**\n\n"
            "👋 Welcome to FoodRescue AI! We connect charities, shelters, and community organizations with fresh surplus food.\n\n"
            "1️⃣ What is your **organization's name**? (e.g. Hope Food Home, Sri Lanka Red Cross, Colombo Care)"
        ),
        "si": (
            "🏢 **සංවිධාන ආහාර ආධාර සේවාව**\n\n"
            "👋 FoodRescue AI වෙත සාදරයෙන් පිළිගනිමු! සුබසාධන සංවිධාන, ළමා නිවාස සහ ප්‍රජාවන් වෙත අතිරික්ත ආහාර සම්බන්ධ කිරීමට අපි සහාය වෙමු.\n\n"
            "1️⃣ ඔබගේ **සංවිධානයේ නම** කුමක්ද? (උදා: හෝප් ෆුඩ් හෝම්, ශ්‍රී ලංකා රතු කුරුස සමාජය)"
        ),
        "ta": (
            "🏢 **அமைப்புகளுக்கான உணவு உதவி**\n\n"
            "👋 FoodRescue AI இற்கு வரவேற்கிறோம்! தொண்டு இல்லங்கள் மற்றும் அமைப்புகளுக்கு உபரி உணவை இணைக்க உதவுகிறோம்.\n\n"
            "1️⃣ உங்கள் **அமைப்பின் பெயர்** என்ன? (எ.கா: ஹோப் ஃபுட் ஹோம், இலங்கை செஞ்சிலுவைச் சங்கம்)"
        ),
    },
    "org_ask_city": {
        "en": "Got it, **{org_name}**! 2️⃣ Which **district** in Sri Lanka is your organization located in? (e.g. Kegalle, Kandy, Colombo, Gampaha, Galle, Jaffna)",
        "si": "ස්තූතියි **{org_name}**! 2️⃣ ඔබගේ සංවිධානය පිහිටා ඇති **දිස්ත්‍රික්කය** කුමක්ද? (උදා: කෑගල්ල, මහනුවර, කොළඹ, ගම්පහ, ගාල්ල, යාපනය)",
        "ta": "புரிந்தது **{org_name}**! 2️⃣ உங்கள் அமைப்பு அமைந்துள்ள **மாவட்டம்** எது? (எ.கா: கேகாலை, கண்டி, கொழும்பு, கம்பஹா, காலி, யாழ்ப்பாணம்)",
    },
    "org_ask_district": {
        "en": "Got it, **{org_name}**! 2️⃣ Which **district** in Sri Lanka is your organization located in? (e.g. Kegalle, Kandy, Colombo, Gampaha, Galle, Jaffna)",
        "si": "ස්තූතියි **{org_name}**! 2️⃣ ඔබගේ සංවිධානය පිහිටා ඇති **දිස්ත්‍රික්කය** කුමක්ද? (උදා: කෑගල්ල, මහනුවර, කොළඹ, ගම්පහ, ගාල්ල, යාපනය)",
        "ta": "புரிந்தது **{org_name}**! 2️⃣ உங்கள் அமைப்பு அமைந்துள்ள **மாவட்டம்** எது? (எ.கா: கேகாலை, கண்டி, கொழும்பு, கம்பஹா, காலி, யாழ்ப்பாணம்)",
    },
    "org_ask_food_need": {
        "en": "What type of food (e.g. Rice & Curry, cooked meal packets, bakery) and how many portions does **{org_name}** need today?",
        "si": "**{org_name}** සඳහා අද අවශ්‍ය ආහාර වර්ගය (උදා: බත් සහ ව්‍යංජන, පිසූ ආහාර පාර්සල්, බේකරි) සහ ප්‍රමාණය කොපමණද?",
        "ta": "**{org_name}** இற்கு இன்று என்ன வகை உணவு மற்றும் எத்தனை பேருக்கு உணவு தேவை? (எ.கா: சோறும் கறியும், ரொட்டி, பொதிகள்)",
    },
    "org_ask_location_pin": {
        "en": (
            "📍 **Step 3: Please Share Your Delivery Location Pin**\n\n"
            "Tap ➕ (or paperclip) → **Location** → **'Send your current location'** 📍 so our volunteer couriers can calculate distance and deliver directly to your organization!"
        ),
        "si": (
            "📍 **අවශ්‍ය පියවර: කරුණාකර ඔබගේ බෙදාහැරීමේ ස්ථානය WhatsApp හරහා එවන්න**\n\n"
            "➕ (හෝ paperclip) ඔබා → **ස්ථානය (Location)** → **'වත්මන් ස්ථානය එවන්න'** 📍 යවන්න. එවිට ස්වේච්ඡා කුරියර්වරුන්ට දුර ගණනය කර ආහාර ගෙනවිත් දිය හැක!"
        ),
        "ta": (
            "📍 **அவசியமான படி: உங்கள் டெலிவரி இருப்பிடத்தை (Location Pin) பகிரவும்**\n\n"
            "➕ (அல்லது paperclip) அழுத்தி → **Location** → **'Send your current location'** 📍 என்பதை அனுப்பவும். இதன் மூலம் தன்னார்வலர்கள் தூரத்தைக் கணக்கிட்டு உணவை டெலிவரி செய்ய முடியும்!"
        ),
    },
    "org_ask_live_location": {
        "en": (
            "📍 **Step 3: Please Share Your Organization's Live Location Pin**\n\n"
            "Tap ➕ (or 📎) → **Location** → **'Send your current location'** 📍 so our volunteer couriers can navigate directly to your door!\n\n"
            "Also tell us what type of food and how many meal portions you need today."
        ),
        "si": (
            "📍 **පියවර 3: කරුණාකර ඔබගේ සංවිධානයේ ස්ථානය WhatsApp හරහා එවන්න**\n\n"
            "➕ (හෝ 📎) ඔබා → **ස්ථානය (Location)** → **'වත්මන් ස්ථානය එවන්න'** 📍 යවන්න. එවිට ස්වේච්ඡා කුරියර්වරුන්ට ආහාර ගෙනවිත් දිය හැක!\n\n"
            "එසේම ඔබට අවශ්‍ය ආහාර වර්ගය හෝ ප්‍රමාණය ද සඳහන් කරන්න."
        ),
        "ta": (
            "📍 **படி 3: உங்கள் அமைப்பின் நேரலை இருப்பிடத்தை (Location Pin) பகிரவும்**\n\n"
            "➕ (அல்லது 📎) அழுத்தி → **Location** → **'Send your current location'** 📍 என்பதை அனுப்பவும்.\n\n"
            "மேலும் உங்களுக்குத் தேவையான உணவு வகை அல்லது பொதிகளையும் குறிப்பிடவும்."
        ),
    },
    # Volunteer Workflow Templates
    "vol_ask_name": {
        "en": (
            "❤️ **Volunteer Courier Registration**\n\n"
            "Thank you for stepping up to rescue food in your community! 🚚\n\n"
            "1️⃣ What is your **full name**?"
        ),
        "si": (
            "❤️ **ස්වේච්ඡා කුරියර් සාමාජික ලියාපදිංචිය**\n\n"
            "ඔබගේ ප්‍රජාවේ ආහාර සුරැකීමට ඉදිරිපත් වීම පිළිබඳව ස්තූතියි! 🚚\n\n"
            "1️⃣ ඔබගේ **සම්පූර්ණ නම** කුමක්ද?"
        ),
        "ta": ("❤️ **தன்னார்வ கூரியர் பதிவு**\n\n" "உங்கள் சமூகத்தில் உணவை மீட்க முன்வந்ததற்கு நன்றி! 🚚\n\n" "1️⃣ உங்கள் **முழுப் பெயர்** என்ன?"),
    },
    "vol_ask_vehicle": {
        "en": (
            "Nice to meet you, **{vol_name}**! 🛵\n\n"
            "2️⃣ What **vehicle or transport mode** will you use for deliveries?\n"
            "(e.g. *Three-Wheeler*, *Motorbike*, *Car*, *Van*, *Bicycle*)"
        ),
        "si": (
            "හමුවීම සතුටක්, **{vol_name}**! 🛵\n\n"
            "2️⃣ බෙදාහැරීම් සඳහා ඔබ භාවිතා කරන **වාහනය හෝ ප්‍රවාහන මාදිලිය** කුමක්ද?\n"
            "(උදා: *Three-Wheeler* (ත්‍රීරෝද රථ), *Motorbike* (යතුරුපැදි), *Car*, *Van*, *Bicycle*)"
        ),
        "ta": (
            "மகிழ்ச்சி, **{vol_name}**! 🛵\n\n"
            "2️⃣ டெலிவரி செய்ய நீங்கள் பயன்படுத்தும் **வாகனம் அல்லது போக்குவரத்து முறை** என்ன?\n"
            "(எ.கா: *Three-Wheeler* (ஆட்டோ), *Motorbike* (பைக்), *Car*, *Van*, *Bicycle*)"
        ),
    },
    "vol_ask_district": {
        "en": (
            "Got it, **{vol_name}**! 📍\n\n"
            "3️⃣ Which **district** in Sri Lanka do you live in / can you cover? (e.g. Kegalle, Kandy, Colombo, Gampaha, Kurunegala, Galle, etc.)"
        ),
        "si": (
            "තේරුම් ගත්තා, **{vol_name}**! 📍\n\n"
            "3️⃣ ඔබ ජීවත් වන / ආවරණය කළ හැකි **දිස්ත්‍රික්කය** කුමක්ද? (උදා: කෑගල්ල, මහනුවර, කොළඹ, ගම්පහ, කුරුණෑගල, ගාල්ල)"
        ),
        "ta": (
            "புரிந்தது, **{vol_name}**! 📍\n\n"
            "3️⃣ நீங்கள் வசிக்கும் அல்லது சேவை செய்யக்கூடிய **மாவட்டம்** எது? (எ.கா: கேகாலை, கண்டி, கொழும்பு, கம்பஹா, குருநாகல், காலி)"
        ),
    },
    "vol_ask_live_location": {
        "en": (
            "Thank you, **{vol_name}**! 📍 Registered in **{district}** District ({vehicle}).\n\n"
            "4️⃣ **Please share your live location pin** now so we can coordinate nearby pickups in {district}.\n\n"
            "👉 Tap **➕ (or 📎) → Location → 'Send your current location' 📍**"
        ),
        "si": (
            "ස්තූතියි, **{vol_name}**! 📍 **{district}** දිස්ත්‍රික්කයේ ({vehicle}) ලියාපදිංචි විය.\n\n"
            "4️⃣ {district} දිස්ත්‍රික්කයේ ආහාර බෙදාහැරීම් සම්බන්ධ කිරීමට කරුණාකර ඔබගේ **වත්මන් ස්ථානය (Live Location)** එවන්න.\n\n"
            "👉 **➕ (හෝ 📎) ඔබා → ස්ථානය (Location) → 'වත්මන් ස්ථානය එවන්න' 📍 යවන්න**"
        ),
        "ta": (
            "நன்றி, **{vol_name}**! 📍 **{district}** மாவட்டத்தில் ({vehicle}) பதிவு செய்யப்பட்டது.\n\n"
            "4️⃣ {district} மாவட்டத்தில் அருகிலுள்ள பணிகளை இணைக்க உங்கள் **இருப்பிடத்தை (Live Location Pin)** பகிரவும்.\n\n"
            "👉 **➕ (அல்லது 📎) அழுத்தி → Location → 'Send your current location' 📍 என்பதை அனுப்பவும்**"
        ),
    },
    # Cross-Party Lifecycle Notifications
    "donation_connected_donor": {
        "en": (
            "🍱 *Food Donation Connected!*\n\n"
            "• 🏢 *Recipient*: {org_name} ({district})\n"
            "• 🍱 *Food*: {food_info}\n"
            "• 📍 *Status*: Your food donation has been connected to a verified recipient organization in {district}. We are assigning a local volunteer courier."
        ),
        "si": (
            "🍱 *ආහාර පරිත්‍යාගය සම්බන්ධ කරන ලදී!*\n\n"
            "• 🏢 *භාරගන්නා සංවිධානය*: {org_name} ({district})\n"
            "• 🍱 *ආහාර*: {food_info}\n"
            "• 📍 *තත්ත්වය*: ඔබගේ ආහාර පරිත්‍යාගය {district} හි සංවිධානයක් සමඟ සම්බන්ධ විය. ආහාර රැගෙන ඒමට ප්‍රාදේශීය ස්වේච්ඡා කුරියර්වරයෙකු සම්බන්ධ කරමින් සිටිමු."
        ),
        "ta": (
            "🍱 *உணவு நன்கொடை இணைக்கப்பட்டது!*\n\n"
            "• 🏢 *பெறுநர்*: {org_name} ({district})\n"
            "• 🍱 *உணவு*: {food_info}\n"
            "• 📍 *நிலை*: உங்கள் உணவு நன்கொடை {district} இல் உள்ள அமைப்புடன் இணைக்கப்பட்டுள்ளது. உணவை சேகரிக்க தன்னார்வலர் பணிக்கப்படுகிறார்."
        ),
    },
    "volunteer_dispatched_donor": {
        "en": (
            "🚚 *Volunteer Courier Assigned!*\n\n"
            "• 👤 *Courier*: {vol_name} ({vol_vehicle})\n"
            "• 📞 *Contact*: {vol_phone}\n"
            "• 🍱 *Food*: {food_info}\n"
            "• 📍 *Status*: Courier is en route to collect the food from your location.\n\n"
            "Please have the food packed and ready! 📦"
        ),
        "si": (
            "🚚 *ස්වේච්ඡා කුරියර්වරයෙකු සම්බන්ධ විය!*\n\n"
            "• 👤 *කුරියර්*: {vol_name} ({vol_vehicle})\n"
            "• 📞 *දුරකථන*: {vol_phone}\n"
            "• 🍱 *ආහාර*: {food_info}\n"
            "• 📍 *තත්ත්වය*: කුරියර්වරයා ආහාර ලබාගැනීමට ඔබගේ ස්ථානය වෙත පැමිණෙමින් සිටී.\n\n"
            "කරුණාකර ආහාර සූදානම් කර තබන්න! 📦"
        ),
        "ta": (
            "🚚 *தன்னார்வ கூரியர் நியமிக்கப்பட்டார்!*\n\n"
            "• 👤 *கூரியர்*: {vol_name} ({vol_vehicle})\n"
            "• 📞 *தொடர்பு*: {vol_phone}\n"
            "• 🍱 *உணவு*: {food_info}\n"
            "• 📍 *நிலை*: கூரியர் உங்கள் இடத்திற்கு உணவை சேகரிக்க வந்துகொண்டிருக்கிறார்.\n\n"
            "உணவை தயார் நிலையில் வைத்திருக்கவும்! 📦"
        ),
    },
    "volunteer_dispatched_org": {
        "en": (
            "🚚 *Courier Dispatched for Your Food Delivery!*\n\n"
            "• 👤 *Courier*: {vol_name} ({vol_vehicle})\n"
            "• 📞 *Contact*: {vol_phone}\n"
            "• 🍱 *Food*: {food_info}\n"
            "• 📍 *Status*: Courier is heading to collect the meals from {donor_name} in {district}."
        ),
        "si": (
            "🚚 *ඔබගේ ආහාර බෙදාහැරීම සඳහා කුරියර්වරයෙකු ගමන් ආරම්භ කර ඇත!*\n\n"
            "• 👤 *කුරියර්*: {vol_name} ({vol_vehicle})\n"
            "• 📞 *දුරකථන*: {vol_phone}\n"
            "• 🍱 *ආහාර*: {food_info}\n"
            "• 📍 *තත්ත්වය*: {district} හි {donor_name} වෙතින් ආහාර එකතු කරගැනීමට කුරියර්වරයා ගමන් කරයි."
        ),
        "ta": (
            "🚚 *உங்கள் உணவு டெலிவரிக்காக கூரியர் புறப்பட்டுள்ளார்!*\n\n"
            "• 👤 *கூரியர்*: {vol_name} ({vol_vehicle})\n"
            "• 📞 *தொடர்பு*: {vol_phone}\n"
            "• 🍱 *உணவு*: {food_info}\n"
            "• 📍 *நிலை*: {district} இல் உள்ள {donor_name} இடமிருந்து உணவை எடுக்க கூரியர் செல்கிறார்."
        ),
    },
    # 13. Distinct Delivery Completion Messages
    "delivery_completed_donor": {
        "en": (
            "🎉 *Delivery Completed!*\n\n"
            "Your food donation ({food_info}) has been safely delivered to *{org_name}* by courier *{vol_name}*!\n\n"
            "🌟 Together, we rescued food and fed lives. Thank you for your generosity! ❤️"
        ),
        "si": (
            "🎉 *ආහාර බෙදාහැරීම සාර්ථකව අවසන් විය!*\n\n"
            "ඔබගේ ආහාර පරිත්‍යාගය ({food_info}), *{vol_name}* විසින් *{org_name}* වෙත සාර්ථකව භාරදෙන ලදී!\n\n"
            "🌟 ආහාර අපතේ යාම වැළැක්වීමට සහ ජනතාවට සහන සැලසීමට දැක්වූ දායකත්වයට ස්තූතියි! ❤️"
        ),
        "ta": (
            "🎉 *டெலிவரி வெற்றிகரமாக முடிந்தது!*\n\n"
            "உங்கள் உணவு நன்கொடை ({food_info}), கூரியர் *{vol_name}* மூலம் *{org_name}* அமைப்பிற்குப் பாதுகாப்பாக வழங்கப்பட்டது!\n\n"
            "🌟 உணவை மீட்டு பசி போக்க உதவிய உங்கள் தாராள மனப்பான்மைக்கு நன்றி! ❤️"
        ),
    },
    "delivery_completed_org": {
        "en": (
            "🍱 *Food Delivery Arrived!*\n\n"
            "Courier *{vol_name}* has delivered the food donation ({food_info}) from *{donor_name}* to your organization.\n\n"
            "Enjoy the fresh meals! 🙏"
        ),
        "si": (
            "🍱 *ආහාර බෙදාහැරීම ලැබිණි!*\n\n"
            "*{donor_name}* වෙතින් පරිත්‍යාග කරන ලද ආහාර ({food_info}), *{vol_name}* විසින් ඔබගේ සංවිධානය වෙත භාරදෙන ලදී.\n\n"
            "නැවුම් ආහාර භුක්ති විඳින්න! 🙏"
        ),
        "ta": (
            "🍱 *உணவு டெலிவரி வந்து சேர்ந்தது!*\n\n"
            "*{donor_name}* வழங்கிய உணவு ({food_info}), கூரியர் *{vol_name}* மூலம் உங்கள் அமைப்பிற்கு டெலிவரி செய்யப்பட்டது.\n\n"
            "உணவை மகிழ்வுடன் ஏற்றுக்கொள்ளுங்கள்! 🙏"
        ),
    },
    "delivery_completed_volunteer": {
        "en": (
            "✅ *Delivery Confirmed & Completed!*\n\n"
            "Thank you, Courier *{vol_name}*! The food delivery ({food_info}) to *{org_name}* is complete.\n"
            "• 💰 *Transport Reimbursement*: LKR {transport_cost} recorded.\n\n"
            "You are now marked as AVAILABLE for new pickup tasks. 🚚"
        ),
        "si": (
            "✅ *බෙදාහැරීම සාර්ථකව තහවුරු විය!*\n\n"
            "ස්තූතියි කුරියර් *{vol_name}*! *{org_name}* වෙත ආහාර ({food_info}) බෙදාහැරීම අවසන් විය.\n"
            "• 💰 *ප්‍රවාහන සහනාධාරය*: රු. {transport_cost} සටහන් විය.\n\n"
            "ඔබ දැන් නව කාර්යයන් සඳහා සූදානම් (AVAILABLE) ලෙස සටහන් කර ඇත. 🚚"
        ),
        "ta": (
            "✅ *டெலிவரி வெற்றிகரமாக முடிந்தது!*\n\n"
            "நன்றி கூரியர் *{vol_name}*! *{org_name}* இற்கான உணவு டெலிவரி ({food_info}) முடிவடைந்தது.\n"
            "• 💰 *போக்குவரத்து கட்டணம்*: LKR {transport_cost} பதிவு செய்யப்பட்டது.\n\n"
            "நீங்கள் இப்போது புதிய பணிகளுக்குத் தயார் (AVAILABLE) என மாற்றப்பட்டுள்ளீர்கள். 🚚"
        ),
    },
    # 14. Mandatory WhatsApp Location Pin Templates
    "donor_ask_location_pin": {
        "en": (
            "Got it! 📍 Recorded {quantity} {unit} of {food_type} in {city}.\n\n"
            "📍 **Step 4: Please Share Your Pickup Live Location Pin**\n\n"
            "Tap ➕ (or 📎) → **Location** → **'Send your current location'** 📍 so our volunteer couriers can navigate directly to collect the food!"
        ),
        "si": (
            "ස්තූතියි! 📍 {city} හි {food_type} {quantity} {unit} සටහන් කරගත්තා.\n\n"
            "📍 **පියවර 4: කරුණාකර ඔබගේ ආහාර ලබාගැනීමේ ස්ථානය WhatsApp හරහා එවන්න**\n\n"
            "➕ (හෝ 📎) ඔබා → **ස්ථානය (Location)** → **'වත්මන් ස්ථානය එවන්න'** 📍 යවන්න. එවිට ස්වේච්ඡා කුරියර්වරුන්ට ආහාර ලබාගැනීමට පැමිණිය හැක!"
        ),
        "ta": (
            "நன்றி! 📍 {city} பகுதியில் {quantity} {unit} {food_type} பதிவு செய்யப்பட்டது.\n\n"
            "📍 **படி 4: உங்கள் உணவு சேகரிக்கும் நேரலை இருப்பிடத்தை (Location Pin) பகிரவும்**\n\n"
            "➕ (அல்லது 📎) அழுத்தி → **Location** → **'Send your current location'** 📍 என்பதை அனுப்பவும். இதன் மூலம் தன்னார்வலர்கள் உணவை வந்து சேகரிக்க முடியும்!"
        ),
    },
    "volunteer_ask_location_pin": {
        "en": (
            "📍 **Courier Location Pin Required**\n\n"
            "Please share your courier current/live location on WhatsApp:\n\n"
            "👉 **Tap ➕ (or 📎) → Location → 'Send your current location' 📍**\n\n"
            "This enables our AI to calculate exact road distances and match you with the nearest food pickups!"
        ),
        "si": (
            "📍 **කුරියර් ස්ථානය අවශ්‍ය වේ**\n\n"
            "කරුණාකර ඔබගේ වත්මන් ස්ථානය WhatsApp හරහා එවන්න:\n\n"
            "👉 **➕ (හෝ 📎) ඔබා → ස්ථානය (Location) → 'වත්මන් ස්ථානය එවන්න' 📍 යවන්න**"
        ),
        "ta": (
            "📍 **கூரியர் இருப்பிடம் தேவை**\n\n"
            "தயவுசெய்து உங்கள் தற்போதைய இருப்பிடத்தை வாட்ஸ்அப் மூலம் பகிரவும்:\n\n"
            "👉 **➕ (அல்லது 📎) அழுத்தி → Location → 'Send your current location' 📍 என்பதை அனுப்பவும்**"
        ),
    },
    "location_pin_required_reminder": {
        "en": (
            "📍 **WhatsApp Location Pin Required**\n\n"
            "We received your message, but to dispatch a volunteer courier and calculate road distances accurately, please share your exact location pin:\n\n"
            "1️⃣ Tap the **➕** (or **📎** paperclip) icon\n"
            "2️⃣ Select **Location**\n"
            "3️⃣ Tap **'Send your current location'** 📍\n\n"
            "Once received, we will proceed immediately! 🚚"
        ),
        "si": (
            "📍 **WhatsApp ස්ථාන පින් එක (Location Pin) අවශ්‍ය වේ**\n\n"
            "නිවැරදිව කුරියර්වරයෙකු සම්බන්ධ කිරීමට කරුණාකර ඔබගේ ස්ථානය එවන්න:\n\n"
            "1️⃣ **➕** (හෝ **📎**) ඔබන්න\n"
            "2️⃣ **ස්ථානය (Location)** තෝරන්න\n"
            "3️⃣ **'වත්මන් ස්ථානය එවන්න'** 📍 ඔබන්න"
        ),
        "ta": (
            "📍 **வாட்ஸ்அப் இருப்பிடப் பகிர்வு (Location Pin) தேவை**\n\n"
            "துல்லியமாக தூரத்தைக் கணக்கிட உங்கள் இருப்பிடத்தை அனுப்பவும்:\n\n"
            "1️⃣ **➕** (அல்லது **📎**) அழுத்தவும்\n"
            "2️⃣ **Location** ஐத் தேர்ந்தெடுக்கவும்\n"
            "3️⃣ **'Send your current location'** 📍 என்பதை அழுத்தவும்"
        ),
    },
}


def get_localized_message(key: str, lang: str = "en", **kwargs) -> str:
    """Retrieve and format a localized message string for the given language.
    Falls back to English if the translation key or language is missing."""
    norm_lang = lang.lower().strip() if lang else DEFAULT_LANGUAGE
    if norm_lang not in SUPPORTED_LANGUAGES:
        norm_lang = DEFAULT_LANGUAGE

    catalog = LOCALIZED_MESSAGES.get(key, {})
    template = catalog.get(norm_lang) or catalog.get("en") or ""

    if not template:
        return ""

    try:
        return template.format(**kwargs)
    except KeyError:
        return template


# =============================================================================
# VALSEA AI TRANSLATION & RESILIENT FALLBACK ENGINE
# =============================================================================

DOMAIN_PHRASE_MAPPINGS = {
    "si": [
        (r"What type of Food do you have for Donation\?", "ඔබ සතුව පරිත්‍යාගය සඳහා ඇති ආහාර වර්ගය කුමක්ද?"),
        (r"What type of food do you have available\?", "ඔබ සතුව ඇති ආහාර වර්ගය කුමක්ද?"),
        (r"Reply with a number or simply describe the food\.?", "අංකය හෝ ආහාර පිළිබඳ විස්තරය එවන්න."),
        (r"Thank you\. Your food rescue request was received\.?", "ස්තූතියි. ඔබගේ ආහාර මුදාගැනීමේ ඉල්ලීම ලැබිණි."),
        (r"Thank you\. Your request was received\.?", "ස්තූතියි. ඔබගේ ඉල්ලීම ලැබිණි."),
        (r"Your donation has been added to the FoodRescue network\.?", "ඔබගේ පරිත්‍යාගය FoodRescue ජාලයට එක් කරන ලදී."),
        (r"Donation Cancelled", "පරිත්‍යාගය අවලංගු කරන ලදී"),
        (r"Pickup Status Update", "බෙදාහැරීමේ තත්ත්ව යාවත්කාලීනය"),
        (r"Your Latest Donation", "ඔබගේ නවතම පරිත්‍යාගය"),
        (r"No Active Donation Found", "සක්‍රිය පරිත්‍යාගයක් හමු නොවීය"),
        (r"No Active Pickup Found", "සක්‍රිය බෙදාහැරීම් කාර්යයක් හමු නොවීය"),
        (r"Let me know if you need help with anything else!?", "ඔබට වෙනත් යමකට උපකාර අවශ්‍ය නම් දන්වන්න!"),
        (r"Let me know if you need anything else!?", "ඔබට වෙනත් යමකට උපකාර අවශ්‍ය නම් දන්වන්න!"),
        (r"Thank you for helping rescue food!?", "ආහාර සුරැකීමට සහාය වීම ගැන ස්තූතියි! ❤️"),
        (r"I'll keep you posted as the pickup progresses!?", "බෙදාහැරීමේ කටයුතු සිදුවන විට අපි ඔබට දන්වන්නෙමු!"),
    ],
    "ta": [
        (r"What type of Food do you have for Donation\?", "தானம் செய்ய உங்களிடம் என்ன வகை உணவு உள்ளது?"),
        (r"What type of food do you have available\?", "உங்களிடம் என்ன வகை உணவு உள்ளது?"),
        (r"Reply with a number or simply describe the food\.?", "எண்ணை உள்ளிடவும் அல்லது உணவை விவரிக்கவும்."),
        (r"Thank you\. Your food rescue request was received\.?", "நன்றி. உங்கள் உணவு மீட்புக் கோரிக்கை பெறப்பட்டது."),
        (r"Thank you\. Your request was received\.?", "நன்றி. உங்கள் கோரிக்கை பெறப்பட்டது."),
        (r"Your donation has been added to the FoodRescue network\.?", "உங்கள் நன்கொடை FoodRescue நெட்வொர்க்கில் சேர்க்கப்பட்டுள்ளது."),
        (r"Donation Cancelled", "நன்கொடை ரத்து செய்யப்பட்டது"),
        (r"Pickup Status Update", "சேகரிப்பு நிலை புதுப்பிப்பு"),
        (r"Your Latest Donation", "உங்கள் சமீபத்திய நன்கொடை"),
        (r"No Active Donation Found", "செயலில் உள்ள நன்கொடை எதுவும் இல்லை"),
        (r"No Active Pickup Found", "செயலில் உள்ள சேகரிப்பு பணிகள் இல்லை"),
        (r"Let me know if you need help with anything else!?", "வேறு உதவி தேவைப்பட்டால் தெரியப்படுத்தவும்!"),
        (r"Let me know if you need anything else!?", "வேறு ஏதேனும் உதவி தேவைப்பட்டால் தெரியப்படுத்தவும்!"),
        (r"Thank you for helping rescue food!?", "உணவை மீட்க உதவியதற்கு நன்றி! ❤️"),
        (r"I'll keep you posted as the pickup progresses!?", "பணி முன்னேறும் போது உங்களுக்கு அறிவிப்போம்!"),
    ],
}


def offline_fallback_translate(text: str, target_lang: str) -> str:
    """Resilient offline translator preserving markdown, formatting, numbers, and domain context."""
    if not text:
        return ""
    if target_lang not in ["si", "ta"]:
        return text

    translated = text

    # Apply phrase mappings first
    mappings = DOMAIN_PHRASE_MAPPINGS.get(target_lang, [])
    for pattern, replacement in mappings:
        translated = re.sub(pattern, replacement, translated, flags=re.IGNORECASE)

    return translated


def translate_text(text: str, target_lang: str, source_lang: Optional[str] = None) -> str:
    """Translate text into the target language using VALSEA AI Translation API with resilient fallback.

    Supported languages: 'si' (Sinhala), 'ta' (Tamil), 'en' (English).
    """
    if not text or not isinstance(text, str):
        return ""

    target_lang = (target_lang or "en").lower().strip()
    if target_lang not in SUPPORTED_LANGUAGES:
        target_lang = DEFAULT_LANGUAGE

    # If target language is English and text has no Sinhala or Tamil script, return directly
    if target_lang == "en":
        if not SINHALA_REGEX.search(text) and not TAMIL_REGEX.search(text):
            return text

    # If text is already in the target language script, return directly
    if target_lang == "si" and len(SINHALA_REGEX.findall(text)) >= 3:
        return text
    if target_lang == "ta" and len(TAMIL_REGEX.findall(text)) >= 3:
        return text

    valsea_key = os.environ.get("VALSEA_API_KEY", "")

    # 1. Primary: VALSEA AI Translation API
    if valsea_key and not valsea_key.startswith("your_"):
        try:
            logger.info(f"Submitting text ({len(text)} chars) to VALSEA AI Translation API [target={target_lang}]...")
            headers = {"Authorization": f"Bearer {valsea_key}", "Content-Type": "application/json"}
            payload = {"text": text, "target_language": target_lang, "source_language": source_lang or "auto", "model": "valsea-translate"}
            resp = requests.post(VALSEA_TRANSLATION_ENDPOINT, headers=headers, json=payload, timeout=15)
            if resp.status_code == 200:
                res_json = resp.json()
                translated = res_json.get("translated_text") or res_json.get("text") or res_json.get("translation")
                if translated:
                    logger.info(f"VALSEA Translation succeeded into '{target_lang}': {translated[:60]}")
                    return str(translated).strip()
            else:
                logger.warning(f"VALSEA Translation API responded with status {resp.status_code}: {resp.text}")
        except Exception as exc:
            logger.warning(f"VALSEA Translation encountered an error: {exc}. Activating resilient fallback.")

    # 2. Resilient Fallback Translation Engine
    return offline_fallback_translate(text, target_lang)


def translate_message_if_needed(text: str, target_lang: str) -> str:
    """Translate outgoing conversational message to user's preferred language if needed."""
    if not text:
        return ""
    target_lang = (target_lang or "en").lower().strip()
    if target_lang == "en":
        return text
    if target_lang == "si" and len(SINHALA_REGEX.findall(text)) >= 3:
        return text
    if target_lang == "ta" and len(TAMIL_REGEX.findall(text)) >= 3:
        return text
    return translate_text(text, target_lang=target_lang)
