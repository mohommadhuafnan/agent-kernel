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
    """Check if the user is explicitly selecting or requesting a language change.
    Handles:
    - Keywords & codes: 'sinhala', 'tamil', 'english', 'malayalam', 'si', 'ta', 'en', 'ml', 'L1'..'L4'
    - Natural language phrases:
        'change language to tamil', 'tamil please', 'தமிழ்', 'தமிழில் பேசுங்கள்', 'speak in tamil'
        'change language to sinhala', 'sinhala please', 'සිංහල', 'සිංහලෙන් කතා කරන්න', 'speak in sinhala'
        'change language to english', 'english please', 'speak in english'
        'change language to malayalam', 'malayalam please', 'മലയാളം'
    - Plain digits 1-4 if in_language_menu is True.
    """
    if not text:
        return None
    clean = text.strip().lower()
    
    if in_language_menu:
        if clean in ["1", "l1", "si"]:
            return "si"
        elif clean in ["2", "l2", "ta"]:
            return "ta"
        elif clean in ["3", "l3", "en"]:
            return "en"
        elif clean in ["4", "l4", "ml"]:
            return "ml"

    # Exact codes or explicit change phrases
    if clean in ["tamil", "ta", "l2"] or any(p in clean for p in ["தமிழ்", "தமிழில்", "தமிழுக்கு", "change language to tamil", "speak in tamil", "tamil please", "change to tamil"]):
        return "ta"

    if clean in ["sinhala", "si", "l1"] or any(p in clean for p in ["සිංහල", "සිංහලෙන්", "change language to sinhala", "speak in sinhala", "sinhala please", "change to sinhala"]):
        return "si"

    if clean in ["malayalam", "ml", "l4"] or any(p in clean for p in ["മലയാളം", "change language to malayalam", "speak in malayalam", "malayalam please", "change to malayalam"]):
        return "ml"

    if clean in ["english", "en", "l3"] or any(p in clean for p in ["speak in english", "english please", "change language to english", "change to english"]):
        return "en"

    # Safe regex for standalone language names or commands
    if re.search(r'\b(tamil)\b', clean) and (len(clean) <= 10 or any(w in clean for w in ["language", "speak", "switch", "change", "please", "in", "to"])):
        return "ta"
    if re.search(r'\b(sinhala)\b', clean) and (len(clean) <= 10 or any(w in clean for w in ["language", "speak", "switch", "change", "please", "in", "to"])):
        return "si"
    if re.search(r'\b(malayalam)\b', clean) and (len(clean) <= 10 or any(w in clean for w in ["language", "speak", "switch", "change", "please", "in", "to"])):
        return "ml"
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

    # 9. Slot Prompts
    "slot_ask_quantity": {
        "en": "Great! 👍 I noted {food_type}.\n\n📦 *How many meals / portions do you have available?*",
        "si": "ඉතා හොඳයි! 👍 මා {food_type} සටහන් කරගත්තා.\n\n📦 *ඔබ සතුව ආහාර පාර්සල් / ප්‍රමාණය කොපමණ තිබේද?*",
        "ta": "சிறப்பு! 👍 {food_type} விபரம் பதிவு செய்யப்பட்டது.\n\n📦 *உங்களிடம் எத்தனை உணவுப் பொதிகள் / அளவுகள் உள்ளன?*",
        "ml": "നല്ലത്! 👍 {food_type} രേഖപ്പെടുത്തി.\n\n📦 *എത്ര ഭക്ഷണ പൊതികൾ ലഭ്യമാണ്?*"
    },

    "slot_ask_location": {
        "en": "📍 *Where can the food be collected?* (Please enter your address/city or share your WhatsApp Location)",
        "si": "📍 *ආහාර ලබාගත හැකි ස්ථානය කොහේද?* (ලිපිනය/නගරය ලියන්න හෝ WhatsApp Location එවන්න)",
        "ta": "📍 *உணவை பெற்றுக்கொள்ள வேண்டிய இடம் எது?* (முகவரி/நகரத்தை எழுதவும் அல்லது WhatsApp Location பகிரவும்)",
        "ml": "📍 *ഭക്ഷണം ശേഖരിക്കേണ്ട സ്ഥലം എവിടെയാണ്?*"
    },

    "slot_ask_deadline": {
        "en": "⏰ *What time will the food be available until for pickup?* (e.g. 'Before 8 PM', 'By 6:30 PM')",
        "si": "⏰ *ආහාර ලබාගත යුතු අවසන් වේලාව කවදාද?* (උදා. 'රාත්‍රී 8 ට පෙර')",
        "ta": "⏰ *உணவை எத்தனை மணிக்குள் பெற்றுக்கொள்ள வேண்டும்?* (எ.கா. 'இரவு 8 மணிக்கு முன்')",
        "ml": "⏰ *ഏത് സമയം വരെ ഭക്ഷണം ശേഖരിക്കാം?*"
    },

    "donation_summary_confirm": {
        "en": (
            "📦 *Please confirm your donation details*:\n\n"
            "• 🍱 *Food*: {quantity} {unit} of {food_type} ({dietary})\n"
            "• 📍 *Pickup Location*: {location}\n"
            "• ⏰ *Available*: {deadline}\n\n"
            "Reply **Confirm** to create the donation, or tell me what you want to change."
        ),
        "si": (
            "📦 *කරුණාකර ඔබගේ පරිත්‍යාග විස්තර තහවුරු කරන්න*:\n\n"
            "• 🍱 *ආහාර*: {food_type} {quantity} {unit} ({dietary})\n"
            "• 📍 *ස්ථානය*: {location}\n"
            "• ⏰ *වේලාව*: {deadline}\n\n"
            "පරිත්‍යාගය නිර්මාණය කිරීමට **Confirm** (තහවුරුයි) ලෙස පිළිතුරු දෙන්න හෝ වෙනස් කිරීමට අවශ්‍ය දේ ලියන්න."
        ),
        "ta": (
            "📦 *தயவுசெய்து உங்கள் நன்கொடை விபரங்களை உறுதிப்படுத்தவும்*:\n\n"
            "• 🍱 *உணவு*: {quantity} {unit} {food_type} ({dietary})\n"
            "• 📍 *இடம்*: {location}\n"
            "• ⏰ *நேரம்*: {deadline}\n\n"
            "நன்கொடையை உருவாக்க **Confirm** (உறுதி) என்று பதிலளிக்கவும், அல்லது மாற்ற வேண்டியதை கூறவும்."
        ),
        "ml": (
            "📦 *വിവരങ്ങൾ സ്ഥിരീകരിക്കുക*:\n\n"
            "• 🍱 {quantity} {unit} {food_type} ({dietary})\n"
            "• 📍 {location}\n"
            "• ⏰ {deadline}\n\n"
            "സ്ഥിരീകരിക്കാൻ **Confirm** എന്ന് ടൈപ്പ് ചെയ്യുക."
        )
    },

    "donation_created_card": {
        "en": (
            "✅ *Donation Created & Matched!*\n\n"
            "• **Donation ID**: `{donation_id}`\n"
            "• 🍱 **Food**: {quantity} {unit} of {food_type} ({dietary})\n"
            "• 📍 **Collect from**: {pickup_loc} (Deadline: {deadline})\n"
            "• 🏢 **Recipient**: {org_name} ({deliv_loc})\n"
            "• 🚚 **Assigned Volunteer**: {vol_name}\n"
            "• 📦 **Status**: `PICKUP_ASSIGNED`\n\n"
            "Thank you for rescuing surplus food! ❤️"
        ),
        "si": (
            "✅ *පරිත්‍යාගය සාර්ථකව නිර්මාණය විය!*\n\n"
            "• **Donation ID**: `{donation_id}`\n"
            "• 🍱 **ආහාර**: {food_type} {quantity} {unit} ({dietary})\n"
            "• 📍 **ස්ථානය**: {pickup_loc}\n"
            "• 🏢 **භාරගන්නා ආයතනය**: {org_name}\n"
            "• 🚚 **ස්වේච්ඡා කුරියර්**: {vol_name}\n"
            "• 📦 **තත්ත්වය**: `PICKUP_ASSIGNED`\n\n"
            "ආහාර අපතේ යාම වැළැක්වීමට කළ සහායට ස්තූතියි! ❤️"
        ),
        "ta": (
            "✅ *நன்கொடை வெற்றிகரமாக உருவாக்கப்பட்டு இணைக்கப்பட்டது!*\n\n"
            "• **Donation ID**: `{donation_id}`\n"
            "• 🍱 **உணவு**: {quantity} {unit} {food_type} ({dietary})\n"
            "• 📍 **இடம்**: {pickup_loc}\n"
            "• 🏢 **பெறுநர்**: {org_name}\n"
            "• 🚚 **தன்னார்வலர்**: {vol_name}\n"
            "• 📦 **நிலை**: `PICKUP_ASSIGNED`\n\n"
            "உணவை வீணாக்காமல் பகிர்ந்தளித்தமைக்கு மிக்க நன்றி! ❤️"
        ),
        "ml": (
            "✅ *സംഭാവന വിജയകരമായി പൂർത്തിയായി!*\n\n"
            "• **Donation ID**: `{donation_id}`\n"
            "• 🍱 {quantity} {unit} {food_type} ({dietary})\n"
            "• 📍 {pickup_loc}\n"
            "• 🏢 {org_name}\n"
            "• 🚚 {vol_name}\n"
            "• 📦 `PICKUP_ASSIGNED`"
        )
    },

    "response_mode_updated": {
        "en": "🎙️ Response mode preference updated to *{mode}*.",
        "si": "🎙️ ප්‍රතිචාර මාදිලිය *{mode}* ලෙස යාවත්කාලීන විය.",
        "ta": "🎙️ பதில் பயன்முறை *{mode}* ஆக மாற்றப்பட்டது.",
        "ml": "🎙️ *{mode}* ആയി തിരഞ്ഞെടുത്തു."
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
            "👋 *නැවතත් සාදරයෙන් පිළිගනිමු {name}!*\n\n"
            "අද ඔබට කළ යුතු දේ කුමක්ද?\n"
            "1️⃣ තවත් ආහාර පරිත්‍යාග කරන්න\n"
            "2️⃣ මගේ පරිත්‍යාග තත්ත්වය පරීක්ෂා කරන්න\n"
            "3️⃣ තොරතුරු යාවත්කාලීන කරන්න\n"
            "4️⃣ උපකාර සහ භාෂාව"
        ),
        "ta": (
            "👋 *மீண்டும் நல்வரவு {name}!*\n\n"
            "இன்று நீங்கள் என்ன செய்ய விரும்புகிறீர்கள்?\n"
            "1️⃣ மேலும் உணவு தானம் செய்ய\n"
            "2️⃣ நன்கொடை நிலையை அறிய\n"
            "3️⃣ விபரங்களை மாற்ற\n"
            "4️⃣ உதவி மற்றும் மொழி"
        ),
        "ml": (
            "👋 *സ്വാഗതം {name}!*\n\n"
            "1️⃣ ഭക്ഷണം ദാനം ചെയ്യുക\n"
            "2️⃣ സ്റ്റാറ്റസ് പരിശോധിക്കുക\n"
            "3️⃣ സഹായം"
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
        ),
        "ml": (
            "ക്ഷമിക്കണം, ഇപ്പോൾ പ്രോസസ്സ് ചെയ്യാൻ സാധിച്ചില്ല.\n\n"
            "ദയവായി വീണ്ടും ശ്രമിക്കുക. 🙏"
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
