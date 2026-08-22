"""FoodRescue AI Multilingual Localization and Language Detection Engine.

Provides:
1. Script-based and keyword-based language detection for English (en), Sinhala (si), and Tamil (ta).
2. Curated, natural localized conversational message catalogs.
3. Language preference resolution and fallback handling.
"""

import re
from typing import Optional, Dict, Any

SUPPORTED_LANGUAGES = {"en", "si", "ta"}
DEFAULT_LANGUAGE = "en"

LANGUAGE_NAMES = {
    "en": "English",
    "si": "සිංහල (Sinhala)",
    "ta": "தமிழ் (Tamil)"
}

# Unicode Script Ranges for Natural Script Detection
SINHALA_REGEX = re.compile(r'[\u0D80-\u0DFF]')
TAMIL_REGEX = re.compile(r'[\u0B80-\u0BFF]')


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
    latin_count = len(re.findall(r'[a-zA-Z]', s))
    if latin_count / total_len > 0.5:
        return "en"
        
    return None


def is_language_selection_intent(text: str, in_language_menu: bool = False) -> Optional[str]:
    """Check if the user is explicitly selecting or requesting a language change.
    Handles:
    - Keywords & codes: 'sinhala', 'tamil', 'english', 'si', 'ta', 'en', 'L1'..'L3'
    - Numbers:
        1 -> English (or Sinhala if in legacy menu)
        2 -> Sinhala (or Tamil)
        3 -> Tamil (or English)
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

    if in_language_menu:
        if clean in ["1", "l1"]:
            return "en"
        elif clean in ["2", "l2"]:
            return "si"
        elif clean in ["3", "l3"]:
            return "ta"

    # Exact codes or explicit change phrases
    if clean in ["tamil", "ta", "l3"] or any(p in clean for p in ["change language to tamil", "speak in tamil", "tamil please", "change to tamil", "in tamil", "tamil language"]):
        return "ta"

    if clean in ["sinhala", "si", "l2"] or any(p in clean for p in ["change language to sinhala", "speak in sinhala", "sinhala please", "change to sinhala", "in sinhala", "sinhala language"]):
        return "si"

    if clean in ["english", "en", "l1"] or any(p in clean for p in ["speak in english", "english please", "change language to english", "change to english", "in english", "english language"]):
        return "en"

    # Safe regex for standalone language names or commands
    if re.search(r'\b(tamil)\b', clean) and (len(clean) <= 10 or any(w in clean for w in ["language", "speak", "switch", "change", "please", "in", "to"])):
        return "ta"
    if re.search(r'\b(sinhala)\b', clean) and (len(clean) <= 10 or any(w in clean for w in ["language", "speak", "switch", "change", "please", "in", "to"])):
        return "si"
    if re.search(r'\b(english)\b', clean) and (len(clean) <= 10 or any(w in clean for w in ["language", "speak", "switch", "change", "please", "in", "to"])):
        return "en"

    return None


def is_response_mode_intent(text: str) -> Optional[str]:
    """Detect if user is setting response mode preference ('voice' or 'text')."""
    if not text:
        return None
    clean = text.strip().lower()
    if any(p in clean for p in [
        "voice replies please", "voice only", "voice response", "voice message", "voice please",
        "send voice", "talk to me", "හඬ පණිවිඩ", "குரல் செய்தி"
    ]):
        return "voice"
    if any(p in clean for p in [
        "text only", "text replies please", "text response", "text please", "send text",
        "no voice", "type only", "පෙළ පමණි", "உரை மட்டும்"
    ]):
        return "text"
    return None


LOCALIZED_MESSAGES: Dict[str, Dict[str, str]] = {
    # 1. First-Time User Onboarding Welcome
    "onboarding_welcome": {
        "en": (
            "👋 Welcome to FoodRescue AI!\n"
            "We help connect surplus food from donors with organizations and communities that need it.\n\n"
            "You can use this WhatsApp number to:\n"
            "1️⃣ Donate surplus food\n"
            "2️⃣ Request available food\n"
            "3️⃣ Volunteer to collect and deliver food\n"
            "4️⃣ Check your donation or pickup status\n"
            "5️⃣ Get help\n\n"
            "🌐 Website:\n"
            "https://foodrescue-ai-ten.vercel.app/\n\n"
            "🌍 Choose your language:\n"
            "1️⃣ English\n"
            "2️⃣ Sinhala\n"
            "3️⃣ Tamil\n\n"
            "🎤 You can also send a voice message.\n\n"
            "You can simply tell me what you need, for example:\n"
            "• \"I have 20 packets of rice available.\"\n"
            "• \"We need food for 30 people.\"\n"
            "• \"I am free to volunteer today.\""
        ),
        "si": (
            "👋 FoodRescue AI වෙත සාදරයෙන් පිළිගනිමු!\n"
            "අතිරික්ත ආහාර පරිත්‍යාගශීලීන්ගෙන් ලබාගෙන අවශ්‍යතා ඇති සංවිධාන සහ ප්‍රජාවන් වෙත සම්බන්ධ කිරීමට අපි සහාය වෙමු.\n\n"
            "ඔබට මෙම WhatsApp අංකය භාවිතා කළ හැක්කේ:\n"
            "1️⃣ අතිරික්ත ආහාර පරිත්‍යාග කිරීමට\n"
            "2️⃣ ලබාගත හැකි ආහාර ඉල්ලුම් කිරීමට\n"
            "3️⃣ ආහාර එකතු කර බෙදාහැරීමට ස්වේච්ඡාවෙන් ඉදිරිපත් වීමට\n"
            "4️⃣ ඔබගේ පරිත්‍යාග හෝ බෙදාහැරීම් තත්ත්වය පරීක්ෂා කිරීමට\n"
            "5️⃣ උපකාර ලබාගැනීමට\n\n"
            "🌐 වෙබ් අඩවිය:\n"
            "https://foodrescue-ai-ten.vercel.app/\n\n"
            "🌍 ඔබගේ භාෂාව තෝරන්න:\n"
            "1️⃣ English\n"
            "2️⃣ Sinhala\n"
            "3️⃣ Tamil\n\n"
            "🎤 ඔබට හඬ පණිවිඩයක් ද එවිය හැක.\n\n"
            "ඔබට අවශ්‍ය දේ කෙලින්ම පැවසිය හැක, උදාහරණයක් ලෙස:\n"
            "• \"මා ළඟ බත් පැකට් 20ක් තියෙනවා.\"\n"
            "• \"අපිට 30 දෙනෙකුට ආහාර අවශ්‍යයි.\"\n"
            "• \"මට අද ස්වේච්ඡාවෙන් උදව් කරන්න පුළුවන්.\""
        ),
        "ta": (
            "👋 FoodRescue AI இற்கு அன்புடன் வரவேற்கிறோம்!\n"
            "நன்கொடையாளர்களிடமிருந்து மீதமுள்ள உணவை பெற்று தேவைப்படும் அமைப்புகள் மற்றும் சமூகங்களுடன் இணைக்க நாங்கள் உதவுகிறோம்.\n\n"
            "நீங்கள் இந்த WhatsApp எண்ணைப் பயன்படுத்தி:\n"
            "1️⃣ உபரி உணவை தானமாக வழங்கலாம்\n"
            "2️⃣ கிடைக்கும் உணவைக் கோரலாம்\n"
            "3️⃣ உணவைச் சேகரித்து வழங்க தன்னார்வலராக உதவலாம்\n"
            "4️⃣ உங்கள் நன்கொடை அல்லது டெலிவரி நிலையைச் சரிபார்க்கலாம்\n"
            "5️⃣ உதவி பெறலாம்\n\n"
            "🌐 இணையதளம்:\n"
            "https://foodrescue-ai-ten.vercel.app/\n\n"
            "🌍 உங்கள் மொழியைத் தேர்ந்தெடுக்கவும்:\n"
            "1️⃣ English\n"
            "2️⃣ Sinhala\n"
            "3️⃣ Tamil\n\n"
            "🎤 நீங்கள் குரல் செய்தியையும் (Voice Message) அனுப்பலாம்.\n\n"
            "உங்களுக்கு என்ன தேவை என்பதை நேரடியாகக் கூறலாம், உதாரணமாக:\n"
            "• \"என்னிடம் 20 அரிசி பொட்டலங்கள் உள்ளன.\"\n"
            "• \"எங்களுக்கு 30 பேருக்கு உணவு தேவை.\"\n"
            "• \"நான் இன்று தன்னார்வலராக உதவத் தயார்.\""
        )
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
        )
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
        )
    },

    # 3. Language Selection Confirmation
    "language_selected": {
        "en": "English language selected. I will respond to your messages in English from now on.",
        "si": "සිංහල භාෂාව තෝරා ගන්නා ලදී. මින් පසු මම ඔබට සිංහලෙන් පිළිතුරු දෙන්නෙමි.",
        "ta": "தமிழ் மொழி தேர்ந்தெடுக்கப்பட்டது. இனி உங்கள் செய்திகளுக்கு தமிழில் பதிலளிப்பேன்."
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
        )
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
        )
    },

    # 6. Volunteer Availability Confirmed
    "volunteer_available": {
        "en": (
            "🎉 *Great! You are now marked as AVAILABLE.*\n\n"
            "We will match you with nearby food rescue pickups shortly! 🚚"
        ),
        "si": (
            "🎉 *ඉතා හොඳයි! ඔබ දැන් සූදානම් (AVAILABLE) ලෙස සටහන් විය.*\n\n"
            "අවට ඇති ආහාර බෙදාහැරීම් අවස්ථා පිළිබඳව අපි ඔබට වහාම දන්වන්නෙමු! 🚚"
        ),
        "ta": (
            "🎉 *சிறப்பு! நீங்கள் இப்போது AVAILABLE ஆக பதிவு செய்யப்பட்டுள்ளீர்கள்.*\n\n"
            "அருகிலுள்ள உணவு சேகரிப்புப் பணிகள் பற்றி விரைவில் அறிவிப்போம்! 🚚"
        )
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
        )
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
        )
    },

    # 9. Donor Workflow Slot Prompts
    "donor_ask_name": {
        "en": "Great! 🙏 I've recorded {quantity} {unit} of {food_type}. 🍚 📍\n\nWhat is your name or business/hotel name?",
        "si": "ස්තූතියි! 🙏 මා {food_type} {quantity} {unit} සටහන් කරගත්තා. 🍚 📍\n\nඔබගේ නම හෝ ව්‍යාපාරික/හෝටල් නාමය කුමක්ද?",
        "ta": "நன்றி! 🙏 நான் {quantity} {unit} {food_type} பதிவு செய்துள்ளேன். 🍚 📍\n\nஉங்கள் பெயர் அல்லது வணிக/ஹோட்டல் பெயர் என்ன?"
    },

    "donor_ask_city": {
        "en": "Thanks, {name}! 📍 I've noted {quantity} {unit} of {food_type}. 🍚\n\nWhich city or area is the food currently located in?",
        "si": "ස්තූතියි, {name}! 📍 මා {food_type} {quantity} {unit} සටහන් කරගත්තා. 🍚\n\nආහාර දැනට පිහිටා ඇති නගරය හෝ ප්‍රදේශය කුමක්ද?",
        "ta": "நன்றி, {name}! 📍 நான் {quantity} {unit} {food_type} பதிவு செய்துள்ளேன். 🍚\n\nஉணவு தற்போது எந்த நகரம் அல்லது பகுதியில் உள்ளது?"
    },

    "donor_ask_deadline": {
        "en": "Got it. 📍 {city}\n\nWhat time will the food be available until for collection / pickup? (e.g. 'Before 8 PM', 'By 6:30 PM')",
        "si": "තේරුම් ගත්තා. 📍 {city}\n\nආහාර එකතු කරගත හැකි අවසන් වේලාව කවදාද? (උදා. 'රාත්‍රී 8 ට පෙර')",
        "ta": "புரிந்தது. 📍 {city}\n\nஉணவை எத்தனை மணிக்குள் சேகரிக்க முடியும்? (எ.கா. 'இரவு 8 மணிக்கு முன்')"
    },

    "donor_ask_location_native": {
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
        )
    },

    "donor_location_received": {
        "en": "📍 Pickup location received successfully.",
        "si": "📍 ලබාගැනීමේ ස්ථානය සාර්ථකව ලැබිණි.",
        "ta": "📍 உணவு சேகரிக்கும் இருப்பிடம் வெற்றிகரமாகப் பெறப்பட்டது."
    },

    "slot_ask_quantity": {
        "en": "Great! 👍 I noted {food_type}.\n\n📦 *How many packets or portions do you have available?*",
        "si": "ඉතා හොඳයි! 👍 මා {food_type} සටහන් කරගත්තා.\n\n📦 *ඔබ සතුව ආහාර පාර්සල් / ප්‍රමාණය කොපමණ තිබේද?*",
        "ta": "சிறப்பு! 👍 {food_type} விபரம் பதிவு செய்யப்பட்டது.\n\n📦 *உங்களிடம் எத்தனை பொதிகள் / உணவுகள் உள்ளன?*"
    },

    "slot_ask_location": {
        "en": (
            "Almost done! 📍\n\n"
            "Please send the pickup location using WhatsApp's Location option so the volunteer can navigate to the food.\n\n"
            "Tap ➕ → Location → Send your current location."
        ),
        "si": (
            "සියල්ල සූදානම් වෙමින් පවතී! 📍\n\n"
            "ස්වේච්ඡා කුරියර්වරයාට ආහාර වෙත පැමිණීමට කරුණාකර WhatsApp හි Location පහසුකම භාවිතයෙන් ස්ථානය එවන්න.\n\n"
            "Tap ➕ → Location → Send your current location."
        ),
        "ta": (
            "கிட்டத்தட்ட முடிந்துவிட்டது! 📍\n\n"
            "தன்னார்வலர் உணவை வந்து சேகரிக்க WhatsApp இன் Location வசதியைப் பயன்படுத்தி இருப்பிடத்தை அனுப்பவும்.\n\n"
            "Tap ➕ → Location → Send your current location."
        )
    },

    "slot_ask_deadline": {
        "en": "Until what time can the food be collected?",
        "si": "ආහාර එකතු කරගත හැකි අවසන් වේලාව කවදාද?",
        "ta": "உணவை எத்தனை மணிக்குள் சேகரிக்க முடியும்?"
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
        )
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
        )
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
        )
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
        )
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
        )
    },

    "donor_food_collected_update": {
        "en": "📦 Your food has been collected successfully.",
        "si": "📦 ඔබගේ ආහාර සාර්ථකව එකතු කරගන්නා ලදී.",
        "ta": "📦 உங்கள் உணவு வெற்றிகரமாக சேகரிக்கப்பட்டது."
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
        )
    },

    "volunteer_already_claimed": {
        "en": "Sorry, this pickup has already been accepted by another volunteer. Thank you for responding! 🙏",
        "si": "සමාවන්න, මෙම බෙදාහැරීම දැනටමත් වෙනත් ස්වේච්ඡා සාමාජිකයෙකු විසින් භාරගෙන ඇත. ප්‍රතිචාර දැක්වීමට ස්තූතියි! 🙏",
        "ta": "மன்னிக்கவும், இந்த பணி ஏற்கனவே மற்றொரு தன்னார்வலரால் ஏற்றுக்கொள்ளப்பட்டது. பதிலளித்ததற்கு நன்றி! 🙏"
    },

    "response_mode_updated": {
        "en": "🎙️ Response mode preference updated to *{mode}*.",
        "si": "🎙️ ප්‍රතිචාර මාදිලිය *{mode}* ලෙස යාවත්කාලීන විය.",
        "ta": "🎙️ பதில் பயன்முறை *{mode}* ஆக மாற்றப்பட்டது."
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
        )
    },

    # 10. Error Recovery
    "error_recovery": {
        "en": (
            "I'm sorry, I'm having trouble processing that right now.\n\n"
            "Please try again in a moment. 🙏"
        ),
        "si": (
            "සමාවන්න, එම ඉල්ලීම සැකසීමේදී සුළු ගැටලුවක් ඇති විය.\n\n"
            "කරුණාකර මොහොතකින් නැවත උත්සාහ කරන්න. 🙏"
        ),
        "ta": (
            "மன்னிக்கவும், அந்த கோரிக்கையை செயலாக்குவதில் சிக்கல் ஏற்பட்டது.\n\n"
            "தயவுசெய்து சிறிது நேரத்தில் மீண்டும் முயற்சிக்கவும். 🙏"
        )
    }
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
