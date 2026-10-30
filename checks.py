"""Plain-code checks for "Allow with conditions" (MVP).

Every check is deterministic: no model calls. Each check takes an outgoing
action plus the context the system recorded (seller settings, thread state,
saved profile, form text) and returns a list of reasons to hold. An empty
list means the action may go out.

The model never sees or edits these rules, and buyer messages cannot change
them, so prompt injection has nothing to target here.
"""

import re
import unicodedata

# Phrases that claim the seller is somewhere or available. Fixed list in the
# MVP; a classifier can extend it later, but may only ADD holds.
PRESENCE_PHRASES = [
    "i'm home", "im home", "i am home",
    "i'm here", "im here", "i am here",
    "i'm outside", "i'm downstairs", "coming down",
    "come by now", "i'll be there", "i will be there",
    "be right there",
]

# Action types the system has classified as leaving the account. These are
# checked. Anything unclassified is treated as permanent and held.
KNOWN_ACTIONS = {"send_message", "agree_price", "submit_form"}

# Internal, reversible actions that never leave the account. Per the design,
# these run freely and are not checked. A record can also mark itself with
# "leaves_account": false.
INTERNAL_ACTIONS = {
    "read", "draft", "save_note", "set_reminder", "update_tracker",
    "log_record", "tracking_update", "reminder", "record",
}


def is_internal(action):
    return action.get("leaves_account") is False or action.get("type") in INTERNAL_ACTIONS

MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").lower().replace("’", "'")).strip()


def check_known_action(action, ctx):
    if action.get("type") not in KNOWN_ACTIONS:
        return [f"unknown action type '{action.get('type')}', treated as permanent"]
    return []


def check_address(action, ctx):
    """Locked: the seller's saved address never goes out without a yes."""
    addr = _norm(ctx.get("seller", {}).get("address"))
    if addr and addr in _norm(action.get("text")):
        return ["contains the seller's home address (locked)"]
    return []


def check_presence(action, ctx):
    """Locked: no claim that the seller is home or on the way unless confirmed."""
    if ctx.get("seller", {}).get("confirmed_available_today"):
        return []
    text = _norm(action.get("text"))
    hits = [p for p in PRESENCE_PHRASES if p in text]
    if hits:
        return [f"claims the seller is present or available ('{hits[0]}') without confirmation (locked)"]
    return []


def check_pending_pickup(action, ctx):
    """Context rule: any reply in a thread with a pending pickup waits for the seller,
    whatever the wording, until the seller confirms."""
    thread = ctx.get("thread", {})
    if (action.get("type") == "send_message" and thread.get("pending_pickup")
            and not ctx.get("seller", {}).get("confirmed_available_today")):
        return ["reply in a thread with a pending pickup, seller hasn't confirmed"]
    return []


def check_price_floor(action, ctx):
    floor = ctx.get("seller", {}).get("floor")
    if floor is None:
        return []
    prices = []
    if action.get("type") == "agree_price" and action.get("price") is not None:
        prices.append(float(action["price"]))
    # Any dollar amount below the floor in an outgoing message is held. This can
    # over-hold ("I can't do $50"), which fails safe.
    for m in MONEY.findall(action.get("text") or ""):
        prices.append(float(m.replace(",", "")))
    low = [p for p in prices if p < floor]
    if low:
        return [f"price ${min(low):g} is below the floor ${floor:g}"]
    return []


def check_saved_answers(action, ctx):
    """Form fields must match the user's saved, verified answers."""
    if action.get("type") != "submit_form":
        return []
    profile = ctx.get("profile", {})
    reasons = []
    for field, value in (action.get("fields") or {}).items():
        if field in profile and _norm(str(value)) != _norm(str(profile[field])):
            reasons.append(f"field '{field}' is '{value}' but saved answer is '{profile[field]}'")
    return reasons


def check_banned_chars(action, ctx):
    banned = ctx.get("rules", {}).get("banned_chars", [])
    texts = [action.get("text") or ""] + [str(v) for v in (action.get("fields") or {}).values()]
    found = sorted({c for c in banned for t in texts if c in t})
    if found:
        names = ", ".join(unicodedata.name(c, hex(ord(c))).lower() for c in found)
        return [f"contains a character the user banned ({names})"]
    return []


def check_sources(action, ctx):
    """Every claim must point at a source the system recorded. Claims come from
    the system's own log; a claim with no source is held."""
    missing = [c["text"] for c in action.get("claims", []) if not c.get("source")]
    if missing:
        return [f"claim with no source: '{missing[0]}'"]
    return []


CHECKS = [
    check_known_action,
    check_address,
    check_presence,
    check_pending_pickup,
    check_price_floor,
    check_saved_answers,
    check_banned_chars,
    check_sources,
]


def evaluate(record):
    """Return ('hold', reasons) or ('send', [])."""
    action, ctx = record["action"], record.get("context", {})
    if is_internal(action):
        return ("send", [])
    reasons = [r for check in CHECKS for r in check(action, ctx)]
    return ("hold", reasons) if reasons else ("send", [])
