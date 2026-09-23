"""Which business the bot is selling today.

One voice pipeline, several businesses. Everything that is specific to a business
— its facts, its prices, its script — lives in `domains/<name>/`, and everything
that is not — the transport, the failover, the logging, the STT and TTS services —
lives in `voicebot/`. This module is the seam between them.

    DOMAIN=insurance   (default, and the only domain on this branch)

Adding a business means adding a folder, not editing the pipeline. See
`domains/README.md` for exactly what a folder has to contain.
"""

import importlib
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
DOMAINS_DIR = _ROOT / "domains"

# Load the bot's .env HERE, so every entry point agrees on which domain is
# active: bot.py, the prompt and guard self-checks, and anything else that
# imports this module. Previously only bot.py loaded it — and it did so AFTER
# importing this module, so DOMAIN=insurance sat in .env while every call ran
# car_spa, and the standalone guard check read the wrong context.json.
# An already-set shell variable still wins, so `DOMAIN=car_spa python ...` works.
_ENV_FILE = _ROOT / "voicebot" / "server" / ".env"
if _ENV_FILE.is_file():
    try:
        from dotenv import load_dotenv

        load_dotenv(_ENV_FILE, override=False)
    except ImportError:  # dotenv is optional for the pure-python self-checks
        pass

#: The business this process is running. Read once, at import.
ACTIVE = os.getenv("DOMAIN") or "insurance"

DOMAIN_DIR = DOMAINS_DIR / ACTIVE

#: The facts the bot is allowed to state. Guardrails check against this file and
#: the prompt is built from it, so it is the single source of truth for a domain.
CONTEXT_FILE = DOMAIN_DIR / "context.json"

#: Source documents the context was built from. Not read at runtime — the bot
#: never sees them — but kept beside the domain so the numbers can be re-checked.
KNOWLEDGE_DIR = DOMAIN_DIR / "knowledge"


def _fail(reason: str) -> "NoReturn":  # noqa: F821
    available = sorted(
        p.name
        for p in (DOMAINS_DIR.iterdir() if DOMAINS_DIR.exists() else ())
        if p.is_dir() and not p.name.startswith(("_", "."))
    )
    raise RuntimeError(
        f"DOMAIN={ACTIVE!r}: {reason}\n"
        f"  looked in: {DOMAIN_DIR}\n"
        f"  available: {', '.join(available) or 'none'}\n"
        f"  a domain needs context.json, prompt.py and guard.py — see domains/README.md"
    )


if not DOMAIN_DIR.is_dir():
    _fail("no such domain folder")
if not CONTEXT_FILE.is_file():
    _fail("missing context.json")


def build_call_card(body):
    """This session's per-case card, or None if the domain has no such notion.

    The dialer prefetches one row before the phone rings and hands it over as the
    Pipecat runner body. A domain that does not use one (the car spa) just has no
    call_card module, and everything downstream treats that the same as a failed
    fetch: no card, full generic prompt, bot still works.
    """
    try:
        module = importlib.import_module(f"domains.{ACTIVE}.call_card")
    except ModuleNotFoundError:
        return None
    return module.from_body(body)


def build_guard(card=None):
    """The active domain's deterministic output guard.

    Required. There used to be a fallback to the car spa's PriceGuard, which
    checks car wash prices and slot times and passes almost anything else — a
    new domain that forgot guard.py would have shipped effectively unguarded.
    Every domain now ships its own, so a missing one fails at startup instead.
    """
    try:
        module = importlib.import_module(f"domains.{ACTIVE}.guard")
    except ModuleNotFoundError as e:
        if e.name != f"domains.{ACTIVE}.guard":
            raise
        _fail("missing guard.py")
    if hasattr(module, "build_guard"):
        return module.build_guard(card)
    try:
        return module.GUARD(card=card)
    except TypeError:
        # A domain whose guard predates call cards.
        return module.GUARD()


def build_tools() -> list:
    """The active domain's own LLM tools, if it has any (domains/<name>/tools.py).

    bot.py adds the shared ones — escalate_to_human and end_call — beside these.
    A domain with no tools.py simply has none of its own.
    """
    try:
        module = importlib.import_module(f"domains.{ACTIVE}.tools")
    except ModuleNotFoundError as e:
        if e.name != f"domains.{ACTIVE}.tools":
            raise
        return []
    return list(module.TOOLS)


def build_system_prompt(mode: str = "outbound", card=None) -> str:
    """The active domain's system prompt, for "outbound" or "inbound".

    Imported lazily so that a broken or half-finished domain fails here, with the
    message above, instead of at some unrelated import site.
    """
    try:
        module = importlib.import_module(f"domains.{ACTIVE}.prompt")
    except ModuleNotFoundError:
        _fail("missing prompt.py")
    try:
        return module.build_system_prompt(mode, card)
    except TypeError:
        return module.build_system_prompt(mode)


def build_opening_line(mode: str = "outbound", card=None) -> str | None:
    """The literal greeting text, if the domain's prompt has a fixed one.

    None means there is no fixed script for this mode (or the domain's
    prompt.py predates this, or has no such notion at all) — the caller
    should fall back to the slower LLM-driven greeting. Never raises: a
    domain without opening_line() just means "no fast path", not a startup
    failure the way a missing prompt.py is.
    """
    try:
        module = importlib.import_module(f"domains.{ACTIVE}.prompt")
    except ModuleNotFoundError:
        return None
    if not hasattr(module, "opening_line"):
        return None
    return module.opening_line(mode, card)
