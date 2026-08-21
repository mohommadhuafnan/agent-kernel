"""FoodRescue AI Multilingual Localization and Language Detection Engine.

Provides:
1. Script-based and keyword-based language detection for English (en), Sinhala (si), Tamil (ta), and Malayalam (ml).
2. Curated, natural localized conversational message catalogs.
3. Language preference resolution and fallback handling.
"""

import re
from typing import Optional, Dict, Any

SUPPORTED_LANGUAGES = {"en", "si", "ta", "ml"}
DEFAULT_LANGUAGE = "en"

LANGUAGE_NAMES = {
    "en": "English",
    "si": "සිංහල (Sinhala)",
    "ta": "தமிழ் (Tamil)",
    "ml": "മലയാളം (Malayalam)"
}

# Unicode Script Ranges for Natural Script Detection
SINHALA_REGEX = re.compile(r'[\u0D80-\u0DFF]')
TAMIL_REGEX = re.compile(r'[\u0B80-\u0BFF]')
MALAYALAM_REGEX = re.compile(r'[\u0D00-\u0D7F]')


def detect_language(text: str) -> Optional[str]:
    """Detect language of incoming text based on script analysis.
    Returns 'si', 'ta', 'ml', or 'en' if confident, or None if ambiguous."""
    if not text or not isinstance(text, str):
        return None
        
    s = text.strip()
    if not s:
        return None
        
    # Count characters in respective script ranges
    si_count = len(SINHALA_REGEX.findall(s))
    ta_count = len(TAMIL_REGEX.findall(s))
    ml_count = len(MALAYALAM_REGEX.findall(s))
    
    total_len = max(1, len(s.replace(" ", "")))
    
    if si_count >= 2 or (si_count / total_len) > 0.2:
        return "si"
    if ta_count >= 2 or (ta_count / total_len) > 0.2:
        return "ta"
    if ml_count >= 2 or (ml_count / total_len) > 0.2:
        return "ml"
        
    # Check if purely latin text
    latin_count = len(re.findall(r'[a-zA-Z]', s))
    if latin_count / total_len > 0.5:
        return "en"
        
    return None


def is_language_selection_intent(text: str, in_language_menu: bool = False) -> Optional[str]:
    """Check if the user is explicitly selecting a language (e.g. 'sinhala', 'tamil', 'english', 'malayalam', 'si', 'ta', 'en', 'ml', 'L1'..'L4').
    Plain digits 1-4 are only treated as language selection if in_language_menu is True."""
    if not text:
        return None
    clean = text.strip().lower()
    
    if in_language_menu and clean in ["1", "l1"]:
        return "si"
    elif in_language_menu and clean in ["2", "l2"]:
        return "ta"
    elif in_language_menu and clean in ["3", "l3"]:
        return "en"
    elif in_language_menu and clean in ["4", "l4"]:
        return "ml"

    if clean in ["sinhala", "si", "සිංහල", "l1"]:
        return "si"
    elif clean in ["tamil", "ta", "தமிழ்", "l2"]:
        return "ta"
    elif clean in ["english", "en", "l3"]:
        return "en"
    elif clean in ["malayalam", "ml", "മലയാളം", "l4"]:
        return "ml"
        
    return None


LOCALIZED_MESSAGES: Dict[str, Dict[str, str]] = {
    # 1. First-Time User Onboarding Welcome
    "onboarding_welcome": {
        "en": (
            "👋 *Welcome to FoodRescue AI!*\n\n"
            "We help rescue surplus food and connect it with people and organizations that need it.\n\n"
            "🍱 *What can you do here?*\n\n"
            "1️⃣ Donate surplus food\n"
            "2️⃣ Find available food (Recipient Org)\n"
            "3️⃣ Become a volunteer courier\n"
            "4️⃣ Track my donation\n"
            "5️⃣ Track my pickup\n"
            "6️⃣ Help & Language settings\n\n"
            "You can simply type what you need. For example:\n"
            "• _\"I have 20 meals available\"_\n"
            "• _\"I need food for our community kitchen\"_\n"
            "• _\"I am free to volunteer today\"_\n\n"
            "🌐 *Learn more*: https://foodrescue-ai-ten.vercel.app/\n\n"
            "🌍 *To change language, type*:\n"
            "• *Sinhala* (or *si* / සිංහල)\n"
            "• *Tamil* (or *ta* / தமிழ்)\n"
            "• *English* (or *en*)\n"
            "• *Malayalam* (or *ml* / മലയാളം)\n"
            "• or type *Language*\n\n"
            "Or simply send a voice message. 🎤"
        ),
        "si": (
            "👋 *FoodRescue AI වෙත සාදරයෙන් පිළිගනිමු!*\n\n"
            "අතිරික්ත ආහාර අපතේ යාම වළක්වා අවශ්‍යතා ඇති අයට බෙදාදීමට අපි සහාය වෙමු.\n\n"
            "🍱 *ඔබට කළ හැකි දේ:*\n"
            "1️⃣ අතිරික්ත ආහාර පරිත්‍යාග කරන්න\n"
            "2️⃣ ආහාර ලබාගන්න (සංවිධාන සඳහා)\n"
            "3️⃣ ස්වේච්ඡා බෙදාහරින්නෙකු වන්න\n"
            "4️⃣ පරිත්‍යාග තත්ත්වය පරීක්ෂා කරන්න\n"
            "5️⃣ බෙදාහැරීම පරීක්ෂා කරන්න\n"
            "6️⃣ උපකාර / මෙනුව\n\n"
            "ඔබට අවශ්‍ය දේ කෙලින්ම ලියන්න හෝ හඬ පණිවිඩයක් එවන්න. 🎤\n\n"
            "🌐 වැඩි විස්තර: https://foodrescue-ai-ten.vercel.app/"
        ),
        "ta": (
            "👋 *FoodRescue AI இற்கு அன்புடன் வரவேற்கிறோம்!*\n\n"
            "மீதமுள்ள உணவை வீணாக்காமல் தேவையானவர்களுக்கு பகிர்ந்தளிக்க நாங்கள் உதவுகிறோம்.\n\n"
            "🍱 *நீங்கள் செய்யக்கூடியவை:*\n"
            "1️⃣ உணவை தானமாக வழங்க\n"
            "2️⃣ உணவைப் பெற (அமைப்புகள்)\n"
            "3️⃣ தன்னார்வலராக இணைய\n"
            "4️⃣ எனது நன்கொடையை கண்காணிக்க\n"
            "5️⃣ டெலிவரியை கண்காணிக்க\n"
            "6️⃣ உதவி / மெனு\n\n"
            "உங்கள் தேவையை நேரடியாக எழுதலாம் அல்லது குரல் செய்தியை (Voice Message) அனுப்பலாம். 🎤\n\n"
            "🌐 மேலும் அறிய: https://foodrescue-ai-ten.vercel.app/"
        ),
        "ml": (
            "👋 *FoodRescue AI-ലേക്ക് സ്വാഗതം!*\n\n"
            "ഭക്ഷണം പാഴാക്കാതെ ആവശ്യക്കാരിലേക്ക് എത്തിക്കാൻ ഞങ്ങൾ സഹായിക്കുന്നു.\n\n"
            "🍱 *നിങ്ങൾക്ക് ചെയ്യാവുന്ന കാര്യങ്ങൾ:*\n"
            "1️⃣ ഭക്ഷണം ദാനം ചെയ്യുക\n"
            "2️⃣ ഭക്ഷണം ആവശ്യപ്പെടുക\n"
            "3️⃣ സന്നദ്ധപ്രവർത്തകനാകുക\n"
            "4️⃣ സംഭാവന ട്രാക്ക് ചെയ്യുക\n"
            "5️⃣ ഡെലിവറി ട്രാക്ക് ചെയ്യുക\n"
            "6️⃣ സഹായം\n\n"
            "നിങ്ങളുടെ ആവശ്യം ടൈപ്പ് ചെയ്യുകയോ വോയ്സ് മെസ്സേജ് അയക്കുകയോ ചെയ്യാം. 🎤\n\n"
            "🌐 കൂടുതൽ വിവരങ്ങൾക്ക്: https://foodrescue-ai-ten.vercel.app/"
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
        ),
        "ml": (
            "👋 *വീണ്ടും സ്വാഗതം!*\n\n"
            "ഇന്ന് ഞാൻ നിങ്ങളെ എങ്ങനെ സഹായിക്കണം?\n\n"
            "1️⃣ ഭക്ഷണം ദാനം ചെയ്യുക\n"
            "2️⃣ ഭക്ഷണം കണ്ടെത്തുക\n"
            "3️⃣ സന്നദ്ധപ്രവർത്തനം\n"
            "4️⃣ സ്റ്റാറ്റസ് പരിശോധിക്കുക\n"
            "5️⃣ ഭാഷ & സഹായം"
        )
    },

    # 3. Language Selection Confirmation
    "language_selected": {
        "en": "🌐 Language set to *English*. How can I assist your food rescue coordination today?",
        "si": "🌐 භාෂාව *සිංහල* ලෙස තෝරාගන්නා ලදී. අද ඔබට අවශ්‍ය ආහාර සහනාධාරය කුමක්ද?",
        "ta": "🌐 மொழி *தமிழ்* ஆக அமைக்கப்பட்டது. இன்று உங்களுக்கு என்ன உதவி தேவை?",
        "ml": "🌐 ഭാഷ *മലയാളം* ആയി തിരഞ്ഞെടുത്തു. ഇന്ന് ഞാൻ എങ്ങനെ സഹായിക്കണം?"
    },

    # 4. Location Prompt
    "request_location": {
        "en": (
            "📍 *Please share your location using WhatsApp*:\n\n"
            "Tap: 📎 (attachment) → *Location* → *Send Your Current Location*\n\n"
            "🔒 _Your exact coordinates will only be shared securely with your assigned courier._"
        ),
        "si": (
            "📍 *කරුණාකර WhatsApp මඟින් ඔබගේ ස්ථානය එවන්න*:\n\n"
            "📎 (attachment) → *Location* → *Send Your Current Location* තෝරන්න.\n\n"
            "🔒 _ඔබගේ නිශ්චිත ස්ථානය පැමිණෙන කුරියර්වරයාට පමණක් ආරක්ෂිතව ලබා දේ._"
        ),
        "ta": (
            "📍 *தயவுசெய்து WhatsApp மூலம் உங்கள் இருப்பிடத்தை (Location) பகிரவும்*:\n\n"
            "📎 → *Location* → *Send Your Current Location* ஐ அழுத்தவும்.\n\n"
            "🔒 _உங்கள் இருப்பிடம் நியமிக்கப்பட்ட தன்னார்வலருக்கு மட்டுமே பாதுகாப்பாக பகிரப்படும்._"
        ),
        "ml": (
            "📍 *ദയവായി WhatsApp വഴി ലൊക്കേഷൻ അയക്കുക*:\n\n"
            "📎 → *Location* → *Send Your Current Location* ക്ലിക്ക് ചെയ്യുക.\n\n"
            "🔒 _നിങ്ങളുടെ കൃത്യമായ സ്ഥലം ചുമതലപ്പെടുത്തിയ ആൾക്ക് മാത്രമേ ലഭ്യമാക്കൂ._"
        )
    },

    # 5. Missing Info Extraction Prompt
    "missing_location": {
        "en": (
            "Thanks! I have noted:\n"
            "• 🍱 *Food*: {food_type}\n"
            "• 📦 *Quantity*: {quantity} {unit}\n"
            "• ⏰ *Available until*: {deadline}\n\n"
            "I still need your pickup location.\n\n"
            "📍 *Please share your location using WhatsApp Location* (📎 → Location)."
        ),
        "si": (
            "ස්තූතියි! මා සටහන් කරගත්තා:\n"
            "• 🍱 *ආහාර*: {food_type}\n"
            "• 📦 *ප්‍රමාණය*: {quantity} {unit}\n"
            "• ⏰ *වේලාව*: {deadline}\n\n"
            "ආහාර ලබාගන්නා ස්ථානය අවශ්‍යයි.\n\n"
            "📍 *කරුණාකර WhatsApp Location මඟින් ස්ථානය එවන්න* (📎 → Location)."
        ),
        "ta": (
            "நன்றி! விபரங்கள் பதிவு செய்யப்பட்டன:\n"
            "• 🍱 *உணவு*: {food_type}\n"
            "• 📦 *அளவு*: {quantity} {unit}\n"
            "• ⏰ *நேரம்*: {deadline}\n\n"
            "உணவை பெற்றுக்கொள்ளும் இடம் தேவை.\n\n"
            "📍 *தயவுசெய்து WhatsApp Location ஐ பகிரவும்* (📎 → Location)."
        ),
        "ml": (
            "നന്ദി! വിവരങ്ങൾ രേഖപ്പെടുത്തി:\n"
            "• 🍱 *ഭക്ഷണം*: {food_type}\n"
            "• 📦 *അളവ്*: {quantity} {unit}\n"
            "• ⏰ *സമയം*: {deadline}\n\n"
            "ലൊക്കേഷൻ ആവശ്യമാണ്.\n\n"
            "📍 *ദയവായി WhatsApp ലൊക്കേഷൻ പങ്കിടുക* (📎 → Location)."
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
        ),
        "ml": (
            "🎉 *നിങ്ങൾ ഇപ്പോൾ AVAILABLE ആണ്.*\n\n"
            "സമീപത്തുള്ള ഭക്ഷണ ശേഖരണങ്ങൾ ഉടൻ അറിയിക്കും! 🚚"
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
        ),
        "ml": (
            "🍱 *ഭക്ഷണം ശേഖരിച്ചതായി സ്ഥിരീകരിച്ചു!*\n\n"
            "**അടുത്ത ഘട്ടം**: ഭക്ഷണം എത്തിക്കേണ്ട സ്ഥലം:\n"
            "• 🏢 {dest_org} ({dest_loc})\n"
            "• 📍 {map_link}\n\n"
            "ഡെലിവറി ചെയ്ത ശേഷം *'Delivered'* എന്ന് മറുപടി നൽകുക."
        )
    },

    # 8. Delivery Completed Celebration
    "delivery_completed": {
        "en": (
            "🎉 *Delivery Completed!*\n\n"
            "• **Task ID**: `{task_id}`\n"
            "• **Status**: `DELIVERED` / `COMPLETED`\n\n"
            "Thank you for helping rescue and deliver surplus meals to people in need! ❤️\n\n"
            "💰 **Transport Support**: Estimated reimbursement of **LKR {reimb_amount}** recorded in accounting ledger.\n\n"
            "You are now marked as **AVAILABLE** for your next rescue."
        ),
        "si": (
            "🎉 *බෙදාහැරීම සාර්ථකව අවසන් විය!*\n\n"
            "අවශ්‍යතා ඇති අයට ආහාර ලබාදීමට කළ සේවයට ඔබට බෙහෙවින් ස්තූතියි! ❤️\n\n"
            "💰 **ගමන් වියදම් සහනාධාරය**: රු. **{reimb_amount}** ගිණුම් වාර්තාවට ඇතුළත් විය.\n\n"
            "ඔබ ඊළඟ බෙදාහැරීම සඳහා නැවතත් **AVAILABLE** ලෙස සටහන් විය."
        ),
        "ta": (
            "🎉 *உணவு விநியோகம் வெற்றிகரமாக முடிந்தது!*\n\n"
            "தேவைப்படுவோருக்கு உணவளிக்க உதவியதற்கு மிக்க நன்றி! ❤️\n\n"
            "💰 **பயண உதவித்தொகை**: ரூ. **{reimb_amount}** பதிவேட்டில் பதிவு செய்யப்பட்டது.\n\n"
            "அடுத்த உதவிக்கு நீங்கள் இப்போது **AVAILABLE** ஆக உள்ளீர்கள்."
        ),
        "ml": (
            "🎉 *ഡെലിവറി വിജയകരമായി പൂർത്തിയായി!*\n\n"
            "സഹായത്തിന് വളരെ നന്ദി! ❤️\n\n"
            "💰 **യാത്രാ സഹായം**: LKR **{reimb_amount}** രേഖപ്പെടുത്തി."
        )
    },

    # 9. Error Recovery
    "error_recovery": {
        "en": (
            "I'm sorry, I'm having trouble processing that right now.\n\n"
            "Please try again in a moment or reply with:\n"
            "1 - Donate food\n"
            "2 - Find food\n"
            "3 - Volunteer\n"
            "4 - Help"
        ),
        "si": (
            "සමාවන්න, එම ඉල්ලීම සැකසීමේදී සුළු ගැටලුවක් ඇති විය.\n\n"
            "කරුණාකර මොහොතකින් නැවත උත්සාහ කරන්න හෝ පහත විකල්පයක් තෝරන්න:\n"
            "1 - ආහාර පරිත්‍යාග\n"
            "2 - ආහාර ඉල්ලුම්\n"
            "3 - ස්වේච්ඡා සේවය\n"
            "4 - උපකාර"
        ),
        "ta": (
            "மன்னிக்கவும், அந்த கோரிக்கையை செயலாக்குவதில் சிக்கல் ஏற்பட்டது.\n\n"
            "தயவுசெய்து மீண்டும் முயற்சிக்கவும் அல்லது தேர்வு செய்யவும்:\n"
            "1 - உணவு தானம்\n"
            "2 - உணவு பெற\n"
            "3 - தன்னார்வலர்\n"
            "4 - உதவி"
        ),
        "ml": (
            "ക്ഷമിക്കണം, ഇപ്പോൾ പ്രോസസ്സ് ചെയ്യാൻ സാധിച്ചില്ല.\n\n"
            "ദയവായി വീണ്ടും ശ്രമിക്കുക."
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
