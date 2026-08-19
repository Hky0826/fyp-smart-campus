"""Canned response translations for supported languages.

Initial greetings remain English by design. All other canned/system messages
(capabilities, auth prompts, out-of-scope notices, no-access, errors, and
navigation prompts) follow the user's detected language.

To add a new language: add a new key to each message dictionary matching
the ISO 639-1 code.
"""

from __future__ import annotations

from typing import Any

_TRANSLATIONS: dict[str, dict[str, str]] = {
    # ── Capabilities ──
    "capability_summary_base": {
        "en": "I can help answer questions about admissions, programmes and courses, fees and scholarships, student life, contact information, faqs, international students, faculties and schools, academic policies, and news and events available in the university documents.",
        "zh": "我可以帮您解答有关招生、课程与专业、学费与奖学金、校园生活、联系方式、常见问题、国际学生、院系与学院、学术政策以及新闻和活动的大学文档信息。",
        "ms": "Saya boleh membantu menjawab soalan mengenai kemasukan, program dan kursus, yuran dan biasiswa, kehidupan pelajar, maklumat hubungan, soalan lazim, pelajar antarabangsa, fakulti dan sekolah, dasar akademik, serta berita dan acara yang terdapat dalam dokumen universiti.",
        "ta": "பல்கலைக்கழக ஆவணங்களில் கிடைக்கும் சேர்க்கை, திட்டங்கள் மற்றும் படிப்புகள், கட்டணங்கள் மற்றும் உதவித்தொகைகள், மாணவர் வாழ்க்கை, தொடர்புத் தகவல், அடிக்கடி கேட்கப்படும் கேள்விகள், சர்வதேச மாணவர்கள், பீடங்கள் மற்றும் பள்ளிகள், கல்வி கொள்கைகள் மற்றும் செய்திகள் பற்றிய கேள்விகளுக்கு என்னால் உதவ முடியும்.",
        "hi": "मैं विश्वविद्यालय के दस्तावेज़ों में उपलब्ध प्रवेश, कार्यक्रम और पाठ्यक्रम, शुल्क और छात्रवृत्ति, छात्र जीवन, संपर्क जानकारी, सामान्य प्रश्न, अंतर्राष्ट्रीय छात्र, संकाय और स्कूल, शैक्षणिक नीतियां, और समाचार और घटनाओं के बारे में प्रश्नों के उत्तर देने में मदद कर सकता हूँ।",
    },
    "capability_personal_auth": {
        "en": " I can also show your own profile, current courses, timetable, next class, and appointments.",
        "zh": " 我还可以显示您自己的个人资料、当前课程、课程表、下一节课和预约信息。",
        "ms": " Saya juga boleh menunjukkan profil anda sendiri, kursus semasa, jadual waktu, kelas seterusnya, dan temu janji.",
        "ta": " உங்கள் சொந்த சுயவிவரம், தற்போதைய படிப்புகள், கால அட்டவணை, அடுத்த வகுப்பு மற்றும் சந்திப்புகளையும் என்னால் காட்ட முடியும்.",
        "hi": " मैं आपका अपना प्रोफ़ाइल, वर्तमान पाठ्यक्रम, समय सारिणी, अगली कक्षा और नियुक्तियाँ भी दिखा सकता हूँ।",
    },
    "capability_personal_unauth": {
        "en": " Personal profile, course, timetable, and appointment questions require face authentication.",
        "zh": " 查询个人资料、课程、课表和预约等个人信息需要进行面部认证。",
        "ms": " Soalan profil peribadi, kursus, jadual waktu, dan temu janji memerlukan pengesahan wajah.",
        "ta": " தனிப்பட்ட சுயவிவரம், படிப்பு, கால அட்டவணை மற்றும் சந்திப்பு வினவல்களுக்கு முக அங்கீகாரம் தேவை.",
        "hi": " व्यक्तिगत प्रोफ़ाइल, पाठ्यक्रम, समय सारिणी और नियुक्ति संबंधी प्रश्नों के लिए चेहरा प्रमाणीकरण आवश्यक है।",
    },

    # ── Authentication required ──
    "auth_required": {
        "en": "This question may require access above visitor level. Please scan your face so I can confirm whether you have permission to answer it.",
        "zh": "此问题可能需要高于访客级别的权限。请进行面部扫描，以便我确认您是否有权限查看该信息。",
        "ms": "Soalan ini mungkin memerlukan akses melebihi tahap pelawat. Sila imbas wajah anda supaya saya dapat mengesahkan sama ada anda mempunyai kebenaran untuk mengaksesnya.",
        "ta": "இந்த கேள்விக்கு பார்வையாளர் நிலைக்கு மேலான அணுகல் தேவைப்படலாம். உங்களிடம் அனுமதி உள்ளதா என்பதை உறுதிப்படுத்த உங்கள் முகத்தை ஸ்கேன் செய்யவும்.",
        "hi": "इस प्रश्न के लिए आगंतुक स्तर से ऊपर की पहुँच आवश्यक हो सकती है। कृपया अपना चेहरा स्कैन करें ताकि मैं पुष्टि कर सकूँ कि आपके पास अनुमति है।",
    },
    "auth_required_status": {
        "en": "Authentication required: please scan your face to check protected document access.",
        "zh": "需要身份验证：请扫描您的面部以检查受保护的文档访问权限。",
        "ms": "Pengesahan diperlukan: sila imbas wajah anda untuk menyemak akses dokumen yang dilindungi.",
        "ta": "அங்கீகாரம் தேவை: பாதுகாக்கப்பட்ட ஆவண அணுகலைச் சரிபார்க்க உங்கள் முகத்தை ஸ்கேன் செய்யவும்.",
        "hi": "प्रमाणीकरण आवश्यक है: कृपया संरक्षित दस्तावेज़ पहुँच की जाँच के लिए अपना चेहरा स्कैन करें।",
    },
    "auth_required_personal": {
        "en": "Please scan your face so I can confirm your identity before accessing your personal campus information.",
        "zh": "在访问您的个人校园信息之前，请扫描您的面部以确认您的身份。",
        "ms": "Sila imbas wajah anda supaya saya dapat mengesahkan identiti anda sebelum mengakses maklumat kampus peribadi anda.",
        "ta": "உங்கள் தனிப்பட்ட வளாகத் தகவலை அணுகுவதற்கு முன் உங்கள் அடையாளத்தை உறுதிப்படுத்த உங்கள் முகத்தை ஸ்கேன் செய்யவும்.",
        "hi": "अपनी व्यक्तिगत कैंपस जानकारी तक पहुँचने से पहले कृपया अपनी पहचान की पुष्टि के लिए अपना चेहरा स्कैन करें।",
    },

    # ── Blocked / Safety policy ──
    "blocked": {
        "en": "I'm not able to process that request. Please ask a straightforward question about campus services or documents.",
        "zh": "我无法处理该请求。请提出有关校园服务或文件的简单问题。",
        "ms": "Saya tidak dapat memproses permintaan itu. Sila kemukakan soalan langsung mengenai perkhidmatan atau dokumen kampus.",
        "ta": "அந்தக் கோரிக்கையை என்னால் செயல்படுத்த முடியாது. வளாகச் சேவைகள் அல்லது ஆவணங்கள் பற்றிய நேரடியான கேள்வியைக் கேளுங்கள்.",
        "hi": "मैं उस अनुरोध को संसाधित नहीं कर सकता। कृपया कैंपस सेवाओं या दस्तावेज़ों के बारे में सीधा प्रश्न पूछें।",
    },
    "blocked_status": {
        "en": "Request blocked: potentially unsafe query pattern detected.",
        "zh": "请求已被拦截：检测到可能不安全的查询模式。",
        "ms": "Permintaan disekat: corak pertanyaan yang berpotensi tidak selamat dikesan.",
        "ta": "கோரிக்கை தடுக்கப்பட்டது: பாதுகாப்பற்ற வினவல் முறை கண்டறியப்பட்டது.",
        "hi": "अनुरोध अवरुद्ध: संभावित रूप से असुरक्षित क्वेरी पैटर्न का पता चला।",
    },

    # ── Out of scope ──
    "out_of_scope": {
        "en": "I'm designed to answer questions based on the university information I have. I may not have reliable information about outside topics.",
        "zh": "我旨在根据所拥有的大学信息回答问题。对于校外话题，我可能没有可靠的信息。",
        "ms": "Saya direka untuk menjawab soalan berdasarkan maklumat universiti yang saya ada. Saya mungkin tidak mempunyai maklumat yang boleh dipercayai tentang topik luar.",
        "ta": "என்னிடம் உள்ள பல்கலைக்கழக தகவல்களின் அடிப்படையில் கேள்விகளுக்கு பதிலளிக்க நான் வடிவமைக்கப்பட்டுள்ளேன். வெளிப்புற தலைப்புகள் பற்றி என்னிடம் நம்பகமான தகவல் இல்லாமல் இருக்கலாம்.",
        "hi": "मुझे उपलब्ध विश्वविद्यालय की जानकारी के आधार पर प्रश्नों के उत्तर देने के लिए डिज़ाइन किया गया है। बाहरी विषयों के बारे में मेरे पास विश्वसनीय जानकारी नहीं हो सकती है।",
    },
    "out_of_scope_status": {
        "en": "Request is outside the supported university assistant scope.",
        "zh": "请求超出了大学助手的支持范围。",
        "ms": "Permintaan berada di luar skop pembantu universiti yang disokong.",
        "ta": "கோரிக்கை ஆதரிக்கப்படும் பல்கலைக்கழக உதவியாளர் எல்லைக்கு வெளியே உள்ளது.",
        "hi": "अनुरोध समर्थित विश्वविद्यालय सहायक के दायरे से बाहर है।",
    },

    # ── No access / No documents found ──
    "no_access": {
        "en": "I'm sorry, but I don't have any documents available that match your question based on your current access level. Please contact the campus administrator if you believe you should have access to this information.",
        "zh": "抱歉，根据您当前的访问级别，我没有找到与您的问题匹配的可用文档。如果您认为自己应该具有访问权限，请联系校园管理员。",
        "ms": "Maaf, saya tidak mempunyai sebarang dokumen yang sepadan dengan soalan anda berdasarkan tahap akses semasa anda. Sila hubungi pentadbir kampus jika anda percaya anda sepatutnya mempunyai akses kepada maklumat ini.",
        "ta": "மன்னிக்கவும், உங்கள் தற்போதைய அணுகல் நிலையின் அடிப்படையில் உங்கள் கேள்விக்கு பொருந்தும் ஆவணங்கள் எதுவும் என்னிடம் இல்லை. இந்தத் தகவலுக்கான அணுகல் உங்களுக்கு இருக்க வேண்டும் என நீங்கள் நம்பினால் வளாக நிர்வாகியைத் தொடர்பு கொள்ளவும்.",
        "hi": "क्षमा करें, आपके वर्तमान एक्सेस स्तर के आधार पर आपके प्रश्न से मेल खाने वाला कोई दस्तावेज़ उपलब्ध नहीं है। यदि आपको लगता है कि आपके पास इस जानकारी तक पहुँच होनी चाहिए तो कृपया कैंपस प्रशासक से संपर्क करें।",
    },
    "no_access_status": {
        "en": "No relevant documents found for your access level.",
        "zh": "未找到适合您访问级别的相关文档。",
        "ms": "Tiada dokumen berkaitan ditemui untuk tahap akses anda.",
        "ta": "உங்கள் அணுகல் நிலைக்கு பொருத்தமான ஆவணங்கள் எதுவும் கிடைக்கவில்லை.",
        "hi": "आपके एक्सेस स्तर के लिए कोई प्रासंगिक दस्तावेज़ नहीं मिले।",
    },

    # ── Clarification / Unclear ──
    "unclear_general": {
        "en": "Could you please ask a question about campus services or documents?",
        "zh": "请问您想咨询有关校园服务或文档的什么问题？",
        "ms": "Bolehkah anda mengemukakan soalan mengenai perkhidmatan atau dokumen kampus?",
        "ta": "வளாகச் சேவைகள் அல்லது ஆவணங்கள் பற்றிய கேள்வியைக் கேட்க முடியுமா?",
        "hi": "क्या आप कैंपस सेवाओं या दस्तावेज़ों के बारे में कोई प्रश्न पूछ सकते हैं?",
    },
    "unclear_specify": {
        "en": "Could you please specify what information about {topic} you are looking for?",
        "zh": "请问您具体想了解关于 {topic} 的哪些信息？",
        "ms": "Bolehkah anda nyatakan maklumat apa tentang {topic} yang anda cari?",
        "ta": "{topic} பற்றிய எந்த குறிப்பிட்ட தகவலைத் தேடுகிறீர்கள் என்பதை விளக்க முடியுமா?",
        "hi": "क्या आप बता सकते हैं कि आप {topic} के बारे में क्या जानकारी खोज रहे हैं?",
    },

    # ── Personal boundary / unsupported ──
    "unsupported_personal": {
        "en": "I can only provide your own personal campus information through supported personal services.",
        "zh": "我只能通过支持的个人服务为您提供您自己的校园信息。",
        "ms": "Saya hanya boleh memberikan maklumat kampus peribadi anda sendiri melalui perkhidmatan peribadi yang disokong.",
        "ta": "ஆதரிக்கப்படும் தனிப்பட்ட சேவைகள் மூலம் மட்டுமே உங்கள் சொந்த வளாகத் தகவலை வழங்க முடியும்.",
        "hi": "मैं केवल समर्थित व्यक्तिगत सेवाओं के माध्यम से आपकी अपनी कैंपस जानकारी प्रदान कर सकता हूँ।",
    },

    # ── Navigation Confirmations & Errors ──
    "nav_confirm_question": {
        "en": "Did you mean {label}? Is that the place you want to go?",
        "zh": "您是指 {label} 吗？您想去那里吗？",
        "ms": "Adakah anda maksudkan {label}? Adakah itu tempat yang anda ingin pergi?",
        "ta": "{label} என்று நீங்கள் குறிப்பிடுகிறீர்களா? நீங்கள் அங்கு செல்ல விரும்புகிறீர்களா?",
        "hi": "क्या आपका मतलब {label} है? क्या आप वहाँ जाना चाहते हैं?",
    },
    "nav_cannot_confirm": {
        "en": "I could not confirm that destination.",
        "zh": "我无法确认该目的地。",
        "ms": "Saya tidak dapat mengesahkan destinasi tersebut.",
        "ta": "அந்த இலக்கை என்னால் உறுதிப்படுத்த முடியவில்லை.",
        "hi": "मैं उस गंतव्य की पुष्टि नहीं कर सका।",
    },
    "nav_specify_destination": {
        "en": "Please tell me the unique destination you want to reach.",
        "zh": "请告诉我您想要前往的具体目的地。",
        "ms": "Sila beritahu saya destinasi khusus yang ingin anda tuju.",
        "ta": "நீங்கள் அடைய விரும்பும் குறிப்பிட்ட இலக்கைக் கூறுங்கள்.",
        "hi": "कृपया मुझे वह विशिष्ट गंतव्य बताएं जहाँ आप पहुँचना चाहते हैं।",
    },

    # ── System / Service Errors ──
    "search_unavailable": {
        "en": "The search service is temporarily unavailable. Please try again later.",
        "zh": "搜索服务暂时不可用，请稍后再试。",
        "ms": "Perkhidmatan carian tidak tersedia buat sementara waktu. Sila cuba lagi sebentar lagi.",
        "ta": "தேடல் சேவை தற்காலிகமாக கிடைக்கவில்லை. பின்னர் மீண்டும் முயற்சிக்கவும்.",
        "hi": "खोज सेवा अस्थायी रूप से अनुपलब्ध है। कृपया बाद में पुनः प्रयास करें।",
    },
    "answer_unavailable": {
        "en": "The answer service is temporarily unavailable. Please try again later.",
        "zh": "问答服务暂时不可用，请稍后再试。",
        "ms": "Perkhidmatan jawapan tidak tersedia buat sementara waktu. Sila cuba lagi sebentar lagi.",
        "ta": "பதில் சேவை தற்காலிகமாக கிடைக்கவில்லை. பின்னர் மீண்டும் முயற்சிக்கவும்.",
        "hi": "उत्तर सेवा अस्थायी रूप से अनुपलब्ध है। कृपया बाद में पुनः प्रयास करें।",
    },
    "cannot_process": {
        "en": "I'm sorry, I could not process your query.",
        "zh": "抱歉，我无法处理您的请求。",
        "ms": "Maaf, saya tidak dapat memproses pertanyaan anda.",
        "ta": "மன்னிக்கவும், உங்கள் வினவலை என்னால் செயல்படுத்த முடியவில்லை.",
        "hi": "क्षमा करें, मैं आपके प्रश्न को संसाधित नहीं कर सका।",
    },
}


def get_translated(key: str, lang: str = "en", **kwargs: Any) -> str:
    """Look up a translated message by key and language code.

    Falls back to English if the translation or key is missing.
    Supports str.format() placeholders through keyword arguments.
    """
    entry = _TRANSLATIONS.get(key, {})
    normalized_lang = (lang or "en").lower().split("-")[0]
    template = entry.get(normalized_lang) or entry.get("en", "")
    if kwargs and template:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template


def get_capabilities_translated(*, authenticated: bool = False, personalisation_enabled: bool = False, lang: str = "en") -> str:
    """Return multilingual capabilities summary."""
    base = get_translated("capability_summary_base", lang)
    if not personalisation_enabled:
        return base
    if authenticated:
        return base + get_translated("capability_personal_auth", lang)
    return base + get_translated("capability_personal_unauth", lang)
