"""Static configuration: theme tokens, language/model tables, and derived paths.

Moved verbatim from subgen.py (module-level constants) — no behavior changes.
"""
from .paths import PROJECT_DIR, DATA_DIR, ASSETS_DIR, MODELS_DIR, _load_app_version

# ── Constants (Linear Dark Design System Tokens)
APP_NAME     = "SubTranscribe"
APP_VER      = _load_app_version()
GITHUB_REPO  = "mdakashhossain1/SubTranscribe-Studio"

DARK_BG      = "#090D16"  # Deep space dark canvas
PANEL_BG     = "#131825"  # Card / panel container surface
CARD_BG      = "#131825"  # Studio card background
INPUT_BG     = "#0D111A"  # Dark inset field background
BORDER_COLOR = "#263048"  # Subtle crisp border outline
ACCENT       = "#6366F1"  # Indigo primary action accent
ACCENT_HOVER = "#4F46E5"  # Indigo hover accent
ACCENT_CYAN  = "#06B6D4"  # Cyan secondary accent & telemetry bar
TEXT_MAIN    = "#F8FAFC"  # High contrast crisp text
TEXT_SUB     = "#94A3B8"  # Muted slate secondary text
SUCCESS      = "#10B981"  # Emerald success & active GPU status
WARNING      = "#F59E0B"  # Amber warning status
ERROR_C      = "#EF4444"  # Rose Red error state
# NOTE: subgen.py referenced an undefined `ACCENT2` for the non-CUDA/no-GPU
# device-label color (subgen.py:1080/1083) — a pre-existing NameError that
# crashed the app at startup for any CPU-only or non-whisper.cpp GPU machine.
# ACCENT_CYAN matches the "teal" comment at that call site and is used here.
ACCENT2 = ACCENT_CYAN

LANGUAGE_MAP = {
    "Auto Detect":                      None,
    "English":                          "en",
    "हिन्दी (Hindi)":                   "hi",
    "বাংলা (Bengali)":                  "bn",
    "ગુજરાતી (Gujarati)":               "gu",
    "मराठी (Marathi)":                  "mr",
    "தமிழ் (Tamil)":                    "ta",
    "తెలుగు (Telugu)":                   "te",
    "ಕನ್ನಡ (Kannada)":                  "kn",
    "മലയാളം (Malayalam)":              "ml",
    "ਪੰਜਾਬੀ (Punjabi)":                 "pa",
    "ଓଡ଼ିଆ (Odia)":                     "or",
    "অসমীয়া (Assamese)":               "as",
    "नेपाली (Nepali)":                  "ne",
    "اردو (Urdu)":                      "ur",
    "العربية (Arabic)":                 "ar",
    "فارسی (Persian)":                  "fa",
    "Русский (Russian)":                "ru",
    "Українська (Ukrainian)":           "uk",
    "Deutsch (German)":                 "de",
    "Français (French)":                "fr",
    "Español (Spanish)":                "es",
    "Português (Portuguese)":           "pt",
    "Italiano (Italian)":               "it",
    "Nederlands (Dutch)":               "nl",
    "Polski (Polish)":                  "pl",
    "Türkçe (Turkish)":                 "tr",
    "Ελληνικά (Greek)":                 "el",
    "Čeština (Czech)":                  "cs",
    "Magyar (Hungarian)":               "hu",
    "Română (Romanian)":                "ro",
    "Svenska (Swedish)":                "sv",
    "Dansk (Danish)":                   "da",
    "Suomi (Finnish)":                  "fi",
    "Norsk (Norwegian)":                "no",
    "Bahasa Indonesia (Indonesian)":    "id",
    "Bahasa Melayu (Malay)":            "ms",
    "Tiếng Việt (Vietnamese)":          "vi",
    "ไทย (Thai)":                       "th",
    "Tagalog (Filipino)":               "tl",
    "עברית (Hebrew)":                   "iw",
    "日本語 (Japanese)":                 "ja",
    "中文 (Chinese)":                    "zh-CN",
    "한국어 (Korean)":                   "ko",
    "Indian English (Hinglish - रोमन हिन्दी)": "hinglish",
    "Indian English (भारतीय अंग्रेज़ी)": "hinglish",
}

# ── Per-language font table for ASS subtitles
# Maps GoogleTranslate language codes → (font_name, supports_italic)
# Indic and Arabic scripts have full support in Nirmala UI / Arial Unicode MS on Windows.
LANG_FONT_MAP = {
    # Latin / Romanized scripts
    "en":       ("Arial",                True),
    "hinglish": ("Arial",                True),
    "es":       ("Arial",                True),
    "fr":       ("Arial",                True),
    "de":       ("Arial",                True),
    "it":       ("Arial",                True),
    "pt":       ("Arial",                True),
    "ru":       ("Arial",                True),
    "uk":       ("Arial",                True),
    "tr":       ("Arial",                True),
    "nl":       ("Arial",                True),
    "pl":       ("Arial",                True),
    "el":       ("Arial",                True),
    "cs":       ("Arial",                True),
    "hu":       ("Arial",                True),
    "ro":       ("Arial",                True),
    "sv":       ("Arial",                True),
    "da":       ("Arial",                True),
    "fi":       ("Arial",                True),
    "no":       ("Arial",                True),
    "id":       ("Arial",                True),
    "ms":       ("Arial",                True),
    "vi":       ("Arial",                True),
    "tl":       ("Arial",                True),
    # Indic languages (Nirmala UI has full Windows native support & italic)
    "hi":    ("Nirmala UI",           True),
    "mr":    ("Nirmala UI",           True),
    "bn":    ("Nirmala UI",           True),
    "gu":    ("Nirmala UI",           True),
    "ta":    ("Nirmala UI",           True),
    "te":    ("Nirmala UI",           True),
    "kn":    ("Nirmala UI",           True),
    "ml":    ("Nirmala UI",           True),
    "pa":    ("Nirmala UI",           True),
    "or":    ("Nirmala UI",           True),
    "as":    ("Nirmala UI",           True),
    "ne":    ("Nirmala UI",           True),
    # Arabic / Urdu / Persian
    "ar":    ("Arial Unicode MS",     True),
    "ur":    ("Arial Unicode MS",     True),
    "fa":    ("Arial Unicode MS",     True),
    "he":    ("Arial",                True),
    "iw":    ("Arial",                True),
    "th":    ("Leelawadee UI",        True),
    # CJK
    "zh-CN": ("Microsoft YaHei",      False),
    "ja":    ("MS Gothic",            False),
    "ko":    ("Malgun Gothic",        False),
}
_DEFAULT_FONT = ("Arial", True)   # fallback for unknown codes

WHISPER_LANG_MAP = {
    "Auto Detect":                      None,
    "English":                          "en",
    "हिन्दी (Hindi)":                   "hi",
    "বাংলা (Bengali)":                  "bn",
    "ગુજરાતી (Gujarati)":               "gu",
    "मराठी (Marathi)":                  "mr",
    "தமிழ் (Tamil)":                    "ta",
    "తెలుగు (Telugu)":                   "te",
    "ಕನ್ನಡ (Kannada)":                  "kn",
    "മലയാളം (Malayalam)":              "ml",
    "ਪੰਜਾਬੀ (Punjabi)":                 "pa",
    "ଓଡ଼ିଆ (Odia)":                     "or",
    "অসমীয়া (Assamese)":               "as",
    "नेपाली (Nepali)":                  "ne",
    "اردو (Urdu)":                      "ur",
    "العربية (Arabic)":                 "ar",
    "فارسی (Persian)":                  "fa",
    "Русский (Russian)":                "ru",
    "Українська (Ukrainian)":           "uk",
    "Deutsch (German)":                 "de",
    "Français (French)":                "fr",
    "Español (Spanish)":                "es",
    "Português (Portuguese)":           "pt",
    "Italiano (Italian)":               "it",
    "Nederlands (Dutch)":               "nl",
    "Polski (Polish)":                  "pl",
    "Türkçe (Turkish)":                 "tr",
    "Ελληνικά (Greek)":                 "el",
    "Čeština (Czech)":                  "cs",
    "Magyar (Hungarian)":               "hu",
    "Română (Romanian)":                "ro",
    "Svenska (Swedish)":                "sv",
    "Dansk (Danish)":                   "da",
    "Suomi (Finnish)":                  "fi",
    "Norsk (Norwegian)":                "no",
    "Bahasa Indonesia (Indonesian)":    "id",
    "Bahasa Melayu (Malay)":            "ms",
    "Tiếng Việt (Vietnamese)":          "vi",
    "ไทย (Thai)":                       "th",
    "Tagalog (Filipino)":               "tl",
    "עברית (Hebrew)":                   "he",
    "日本語 (Japanese)":                 "ja",
    "中文 (Chinese)":                    "zh",
    "한국어 (Korean)":                   "ko",
    "Indian English (Hinglish - रोमन हिन्दी)": "hi",
    "Indian English (भारतीय अंग्रेज़ी)": "hi",
}

FLAG_ICON_MAP = {
    "Auto Detect":                      "un.png",
    "None":                             "un.png",
    "English":                          "gb.png",
    "हिन्दी (Hindi)":                   "in.png",
    "বাংলা (Bengali)":                  "bd.png",
    "ગુજરાતી (Gujarati)":               "in.png",
    "मराठी (Marathi)":                  "in.png",
    "தமிழ் (Tamil)":                    "in.png",
    "తెలుగు (Telugu)":                   "in.png",
    "ಕನ್ನಡ (Kannada)":                  "in.png",
    "മലയാളം (Malayalam)":              "in.png",
    "ਪੰਜਾਬੀ (Punjabi)":                 "in.png",
    "ଓଡ଼ିଆ (Odia)":                     "in.png",
    "অসমীয়া (Assamese)":               "in.png",
    "नेपाली (Nepali)":                  "np.png",
    "اردو (Urdu)":                      "pk.png",
    "العربية (Arabic)":                 "sa.png",
    "فارسی (Persian)":                  "ir.png",
    "Русский (Russian)":                "ru.png",
    "Українська (Ukrainian)":           "ua.png",
    "Deutsch (German)":                 "de.png",
    "Français (French)":                "fr.png",
    "Español (Spanish)":                "es.png",
    "Português (Portuguese)":           "br.png",
    "Italiano (Italian)":               "it.png",
    "Nederlands (Dutch)":               "nl.png",
    "Polski (Polish)":                  "pl.png",
    "Türkçe (Turkish)":                 "tr.png",
    "Ελληνικά (Greek)":                 "gr.png",
    "Čeština (Czech)":                  "cz.png",
    "Magyar (Hungarian)":               "hu.png",
    "Română (Romanian)":                "ro.png",
    "Svenska (Swedish)":                "se.png",
    "Dansk (Danish)":                   "dk.png",
    "Suomi (Finnish)":                  "fi.png",
    "Norsk (Norwegian)":                "no.png",
    "Bahasa Indonesia (Indonesian)":    "id.png",
    "Bahasa Melayu (Malay)":            "my.png",
    "Tiếng Việt (Vietnamese)":          "vn.png",
    "ไทย (Thai)":                       "th.png",
    "Tagalog (Filipino)":               "ph.png",
    "עברית (Hebrew)":                   "il.png",
    "日本語 (Japanese)":                 "jp.png",
    "中文 (Chinese)":                    "cn.png",
    "한국어 (Korean)":                   "kr.png",
    "Indian English (Hinglish - रोमन हिन्दी)": "in.png",
    "Indian English (भारतीय अंग्रेज़ी)": "in.png",
}

# ── GPU-optimised models (ordered: best accuracy → fastest)
# All run on GPU (float16). Falls back to CPU (int8) automatically.
MODEL_SIZES = [
    "large-v3",           # Best accuracy — fits your 12 GB VRAM perfectly
    "large-v3-turbo",     # 8x faster than large-v3, ~95% same accuracy
    "distil-large-v3",    # Distilled large-v3 — ultra-fast + very accurate
    "large-v2",           # Previous generation large model
    "medium",             # Good balance — ~3 GB VRAM
    "small",              # Lightweight — ~1 GB VRAM
    "base",               # Very fast — ~500 MB VRAM
    "tiny",               # Fastest — ~250 MB VRAM (lowest accuracy)
]
OUTPUT_FORMATS = ["SRT", "VTT", "ASS", "TXT"]

# ── HuggingFace repo IDs used by faster-whisper
MODEL_REPOS = {
    "tiny":            "Systran/faster-whisper-tiny",
    "base":            "Systran/faster-whisper-base",
    "small":           "Systran/faster-whisper-small",
    "medium":          "Systran/faster-whisper-medium",
    "large-v2":        "Systran/faster-whisper-large-v2",
    "large-v3":        "Systran/faster-whisper-large-v3",
    "large-v3-turbo":  "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
}

# Approximate download sizes in MB
MODEL_SIZES_MB = {
    "tiny": 75, "base": 145, "small": 484, "medium": 1500,
    "large-v2": 3100, "large-v3": 3100,
    "large-v3-turbo": 809, "distil-large-v3": 756,
}

# ── GGML model files used by whisper.cpp (Vulkan GPU path, for non-NVIDIA GPUs)
GGML_MODEL_FILES = {
    "tiny":            ("ggerganov/whisper.cpp", "ggml-tiny.bin"),
    "base":            ("ggerganov/whisper.cpp", "ggml-base.bin"),
    "small":           ("ggerganov/whisper.cpp", "ggml-small.bin"),
    "medium":          ("ggerganov/whisper.cpp", "ggml-medium.bin"),
    "large-v2":        ("ggerganov/whisper.cpp", "ggml-large-v2.bin"),
    "large-v3":        ("ggerganov/whisper.cpp", "ggml-large-v3.bin"),
    "large-v3-turbo":  ("ggerganov/whisper.cpp", "ggml-large-v3-turbo.bin"),
    "distil-large-v3": ("distil-whisper/distil-large-v3-ggml", "ggml-distil-large-v3.bin"),
}
GGML_MODEL_SIZES_MB = {
    "tiny": 74, "base": 141, "small": 465, "medium": 1463,
    "large-v2": 2951, "large-v3": 2952,
    "large-v3-turbo": 1549, "distil-large-v3": 1449,
}

# Approximate VRAM/RAM needed to comfortably run each model
MODEL_VRAM_MB = {
    "tiny": 250, "base": 500, "small": 1000, "medium": 3000,
    "large-v2": 10000, "large-v3": 12000,
    "large-v3-turbo": 6000, "distil-large-v3": 4000,
}

# ── Project-local model directory (ALL downloads go here, never to cache)
# Works both as .py script AND as PyInstaller .exe — MODELS_DIR is already
# resolved frozen-aware in paths.py (dev: subtranscribe/models, frozen: AppData).
MODELS_DIR.mkdir(parents=True, exist_ok=True)  # create on first run

GGML_MODELS_DIR = MODELS_DIR / "ggml"
GGML_MODELS_DIR.mkdir(parents=True, exist_ok=True)
WHISPERCPP_EXE = PROJECT_DIR / "bin" / "whispercpp" / "whisper-cli.exe"

ICON_PATH = ASSETS_DIR / "subgen.ico"
LOGO_PATH = ASSETS_DIR / "logo.png"
FONTS_DIR = ASSETS_DIR / "fonts"
BS_ICONS_DIR = ASSETS_DIR / "bs-icons" / "bootstrap-icons-1.11.3"
FLAGS_DIR = ASSETS_DIR / "flags"
