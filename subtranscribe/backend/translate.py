"""Translation/romanization. transliterate_to_roman is moved verbatim from
subgen.py. resolve_translate_fn is mechanically extracted from the inline
GoogleTranslator setup inside SubGenApp._pipeline's `on_seg` closure
(subgen.py:4193-4200) — identical branching/behavior, just named and
importable instead of a closure captured at every pipeline run."""
import json
import urllib.parse
import urllib.request

from ..config import LANGUAGE_MAP

try:
    from deep_translator import GoogleTranslator
    HAS_TRANSLATOR = True
except ImportError:
    HAS_TRANSLATOR = False


def transliterate_to_roman(text, src="hi"):
    """
    Transliterates native Indic/Devanagari text into natural conversational Roman English (Hinglish/Banglish/etc.).
    E.g. 'हेलो हेलो एवरीवन वेलकम बैक' -> 'Hello hello everyone welcome back'
    """
    if not text or not text.strip():
        return text
    src_code = src if src and src not in ("auto", "None", "hinglish") else "hi"
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={src_code}&tl=en&dt=rm&dt=t&q={urllib.parse.quote(text)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            romanized = []
            if data and data[0]:
                for item in data[0]:
                    if len(item) > 3 and item[3]:
                        romanized.append(item[3])
                    elif len(item) > 2 and item[2]:
                        romanized.append(item[2])
            if romanized:
                res = " ".join(romanized).strip()
                if res:
                    return res[0].upper() + res[1:] if len(res) > 1 else res.upper()
    except Exception:
        pass
    # Fallback to indic_transliteration if installed
    try:
        from indic_transliteration import sanscript
        from indic_transliteration.sanscript import transliterate
        return transliterate(text, sanscript.DEVANAGARI, sanscript.ITRANS)
    except Exception:
        return text


def resolve_translate_fn(source_lang_code, target_name):
    """Build the per-run translate callable used by the transcription pipeline.

    source_lang_code: WHISPER_LANG_MAP code for the detected/selected source
                       language (e.g. "hi"), or None for auto-detect.
    target_name: the display name selected in the "Translate To" picker
                 (a LANGUAGE_MAP key, e.g. "Deutsch (German)" or "None").

    Returns a `text -> text` callable, or None if no translation is requested.
    """
    tgt = LANGUAGE_MAP.get(target_name)
    if tgt == "hinglish":
        return lambda text: transliterate_to_roman(text, src=source_lang_code or "hi")
    elif tgt and HAS_TRANSLATOR:
        gt = GoogleTranslator(source="auto", target=tgt)
        return lambda text: (gt.translate(text) or text)
    return None
