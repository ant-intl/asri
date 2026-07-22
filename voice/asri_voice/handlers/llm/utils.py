import base64
import io
import re

import requests
from PIL import Image

# XML structural tags used by chatbot's interleaved prompt format.
# These tags are NOT meant to be spoken by TTS — strip them, keeping content.
_XML_STRUCTURAL_TAGS = re.compile(r'</?(?:answer|tool_call|think)>', re.IGNORECASE)


def strip_xml_tags(text: str) -> str:
    """Remove XML structural tags (<answer>, </answer>,  (content kept for answer/tool_call).

    Note:  <!—- … !—> blocks (with content) are handled separately by
    handler-specific logic (e.g. qwen3omni _THINK_TAG_RE).  This function
    only removes stray opening/closing tags that survive chunking.
    """
    return _XML_STRUCTURAL_TAGS.sub('', text)


# Split at sentence-ending AND clause-level punctuation (Chinese commas, colons, etc.)
# The LLM handler uses an accumulation threshold to avoid sending tiny fragments to TTS.
_SENT_END = re.compile(r'([。！？；，]+|[.!?;,]+(?:\s|$))')


def split_sentences(text: str) -> list[str]:
    """Split text into clauses at Chinese and Western punctuation.

    Returns a list where all but the last element are complete clauses.
    The last element is the remaining (potentially incomplete) fragment.
    """
    parts = _SENT_END.split(text)
    sentences = []
    i = 0
    while i < len(parts):
        seg = parts[i]
        # Attach the delimiter to the preceding segment
        if i + 1 < len(parts):
            seg += parts[i + 1]
            i += 2
        else:
            i += 1
        if seg:
            if sentences and not _SENT_END.search(sentences[-1]):
                # Previous segment had no delimiter — merge
                sentences[-1] += seg
            else:
                sentences.append(seg)
    return sentences if sentences else [text]


SPEECHABLE_PATTERN = re.compile(
    r"[^\w\s.,!?;:'\"\-()\/\\@#%&*+=$€£¥₹₽¢\[\]{}<>~`^|…—–\n\r\t"
    r"，。！？；：、""''（）【】《》～·\u3001-\u3003\u3008-\u3011\u3014-\u301F\uFF01-\uFF0F\uFF1A-\uFF20]",
    flags=re.UNICODE,
)


def remove_unspeechable(text: str) -> str:
    """Keep only speechable characters: letters, digits, punctuation, whitespace.
    support unicode characters (english, arabic, chinese, japanese, korean, etc.)
    """
    return SPEECHABLE_PATTERN.sub('', text)


_MD_BOLD = re.compile(r'\*\*(.+?)\*\*')
_MD_ITALIC = re.compile(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)')
_MD_HEADING = re.compile(r'^#{1,6}\s+', re.MULTILINE)
_MD_BULLET = re.compile(r'^\s*[-*+]\s+', re.MULTILINE)
_MD_NUMBERED = re.compile(r'^\s*\d+[\.\)]\s+', re.MULTILINE)
_MD_CODE = re.compile(r'`(.+?)`')
_MD_BLOCKQUOTE = re.compile(r'^>\s+', re.MULTILINE)
_MD_HR = re.compile(r'^---+\s*$', re.MULTILINE)
_MD_LINK = re.compile(r'\[([^\]]+)\]\([^)]+\)')
_MD_TAG = re.compile(r'\{[a-zA-Z]+\}')
_MD_STAR = re.compile(r'\*+')  # catch any leftover * sequences


_STRIP_WITH_GROUP = [_MD_BOLD, _MD_ITALIC, _MD_CODE, _MD_LINK]
_STRIP_EMPTY = [_MD_HEADING, _MD_BULLET, _MD_NUMBERED, _MD_BLOCKQUOTE, _MD_HR, _MD_TAG, _MD_STAR]


# Bracket symbols sound unnatural in speech. Strip the symbols but keep
# the content, so "RM199（一次性购买）" becomes "RM199一次性购买".
_BRACKETS_SYMBOLS = re.compile(r'[\(\)\[\]（）【】《》「」『』]')


def strip_brackets(text: str) -> str:
    """Remove bracket/parenthesis symbols, keeping enclosed content."""
    return _BRACKETS_SYMBOLS.sub('', text)


# Repeated punctuation like "！！！" or "??" sounds broken in TTS.
# Dedup to a single character.
_DEDUP_PUNCT = re.compile(r'([。！？；：、，.!?;,：])\1+')


def dedup_repeated_punctuation(text: str) -> str:
    """Collapse repeated punctuation: '！！！' -> '！', '??' -> '?'."""
    return _DEDUP_PUNCT.sub(r'\1', text)


# Characters that suggest a sentence ending when no final punctuation exists.
_SENTENCE_END_PUNCT = frozenset('。！？.!?')
_CJK_RANGES = (
    ('\u4e00', '\u9fff'),
    ('\u3400', '\u4dbf'),
)


def _is_cjk(ch: str) -> bool:
    return any(lo <= ch <= hi for lo, hi in _CJK_RANGES)


def append_trailing_punctuation(text: str) -> str:
    """Append '。' if text ends with a CJK char but no sentence-ending punctuation."""
    if not text:
        return text
    last = text[-1]
    if _is_cjk(last) and last not in _SENTENCE_END_PUNCT:
        return text + '。'
    return text


def strip_markdown(text: str) -> str:
    """Remove Markdown formatting symbols so TTS reads naturally."""
    for pat in _STRIP_WITH_GROUP:
        text = pat.sub(r'\1', text)
    for pat in _STRIP_EMPTY:
        text = pat.sub('', text)
    return text


def clean_text(text: str) -> str:
    """Apply all text cleaning: xml tags + markdown + brackets + dedup + trailing punct."""
    text = strip_xml_tags(text)
    text = strip_markdown(text)
    # \n after punctuation (skipping whitespace) → remove; otherwise → replace with ，
    _punct = frozenset('。！？：；，、,.!?;:')
    def _nl_repl(m):
        if m.start() == 0:
            return ''
        i = m.start() - 1
        while i >= 0 and text[i] in ' \t\r':
            i -= 1
        return '' if i >= 0 and text[i] in _punct else '，'
    text = re.sub(r'\n+', _nl_repl, text)
    text = text.lstrip('，')
    text = strip_brackets(text)
    text = dedup_repeated_punctuation(text)
    text = append_trailing_punctuation(text)
    return text


def image_url_to_pil(image_url: str) -> Image.Image:
    """Convert an image URL or base64 data URI to a PIL Image.

    Accepts:
    - 'data:image/...;base64,<b64>' data URIs
    - 'https://...`` or ``http://...' URLs (fetched with a 10s timeout)
    """
    if image_url.startswith("data:"):
        _, b64_data = image_url.split(",", 1)
        return Image.open(io.BytesIO(base64.b64decode(b64_data)))
    resp = requests.get(image_url, timeout=10)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content))
