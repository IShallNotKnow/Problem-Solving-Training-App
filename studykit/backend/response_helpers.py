import unicodedata
import re
import json

from openai import BadRequestError
from pydantic import ValidationError
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenAI response helpers
# ---------------------------------------------------------------------------


def _parse_tool_call(message) -> dict:
    """Extract and JSON-parse the first tool call from an OpenAI chat completion."""
    tool_calls = message.choices[0].message.tool_calls
    if not tool_calls:
        raise ValueError("Model did not return a tool call.")
    return json.loads(tool_calls[0].function.arguments)


def log_invalid_prompt(exc: BadRequestError, call_site: str, messages: list) -> bool:
    """Log actionable detail when OpenAI rejects a prompt as policy-violating.

    `invalid_prompt` is raised by the input safety classifier, not by our schema, so
    the useful signal is *which* call and *what text* went in. We log a per-block
    fingerprint (length + a short excerpt) so the offending upload can be traced
    without dumping full documents into the logs.
    """
    code = (exc.body or {}).get("error", {}).get("code") if isinstance(exc.body, dict) else None
    if code != "invalid_prompt":
        return False

    logger.error(
        f"[{call_site}] OpenAI rejected the prompt as policy-violating (invalid_prompt). "
        f"This is the input classifier, not a schema error."
    )
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        for i, b in enumerate(blocks):
            if b.get("type") == "image_url":
                logger.error(
                    f"  [{role}][{i}] image block (~{len(b['image_url']['url'])} b64 chars)"
                )
                continue
            text = b.get("text") or ""
            excerpt = text[:300].replace("\n", " ")
            logger.error(f"  [{role}][{i}] text {len(text)} chars | starts: {excerpt!r}")
    return True


def _summarize_validation_error(exc: Exception) -> str:
    """Condense a pydantic ValidationError into a short, model-actionable string."""
    if isinstance(exc, ValidationError):
        parts = []
        for err in exc.errors()[:4]:
            loc = ".".join(str(p) for p in err.get("loc", ())) or "question"
            parts.append(f"{loc}: {err.get('msg', 'invalid')}")
        return "; ".join(parts)
    return str(exc)


def _parse_text(message) -> str:
    """Extract text content from an OpenAI chat completion."""
    return message.choices[0].message.content


def _normalize_topic_key(topic: str) -> str:
    # replace control characters — DEL is the known apostrophe mangling,
    # map the whole C0/C1 range defensively
    topic = re.sub(
        r"[\x00-\x1f\x7f\x80-\x9f]",
        lambda m: {
            "\x7f": "'",  # DEL → apostrophe
            "\x91": "'",  # Windows-1252 left single quote
            "\x92": "'",  # Windows-1252 right single quote
            "\x93": '"',  # Windows-1252 left double quote
            "\x94": '"',  # Windows-1252 right double quote
            "\x96": "-",  # Windows-1252 en dash
            "\x97": "-",  # Windows-1252 em dash
        }.get(m.group(), ""),
        topic,
    )

    # NFKC handles ligatures, fullwidth variants, etc.
    topic = unicodedata.normalize("NFKC", topic)

    # Unicode smart quotes — NFKC doesn't collapse these to ASCII
    topic = topic.translate(
        str.maketrans(
            {
                "\u2018": "'",
                "\u2019": "'",
                "\u201c": '"',
                "\u201d": '"',
                "\u2013": "-",
                "\u2014": "-",
            }
        )
    )

    return topic.strip()