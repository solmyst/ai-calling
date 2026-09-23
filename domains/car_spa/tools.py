"""The car spa's own LLM tools.

bot.py registers these beside the shared ones (escalate_to_human, end_call)
through domain.build_tools(). They lived in bot.py until 2026-09-23, which
meant every domain was handed them — the insurance bot on Gemini was offered a
car wash booking tool on every turn.
"""

import datetime
import json
from pathlib import Path

from loguru import logger
from pipecat.services.llm_service import FunctionCallParams

# Same file as before the move, so existing lead exports keep working.
BOOKING_LOG = Path(__file__).resolve().parents[2] / "voicebot" / "server" / "booking_requests.jsonl"


async def record_booking_request(
    params: FunctionCallParams,
    service: str,
    car: str,
    area: str,
    slot_preference: str,
    phone: str,
):
    """Note the booking request for the team to confirm. Call once you have all
    five. Records only — it does NOT book or confirm.

    Args:
        service: Full Car Spa Premium, Full Car Spa Basic or Exterior Only.
        car: Brand and model, e.g. "Hyundai Creta".
        area: Area or pincode in Gurugram.
        slot_preference: Day and time, in the customer's own words.
        phone: Callback number as given.
    """
    # The docstring above IS the tool schema and is re-sent on every turn, so it
    # carries only what the parameter names do not already say. Notes like this
    # one belong here, in a comment, where the model is never charged for them.
    request = {
        "ts": datetime.datetime.now().isoformat(),
        "service": service,
        "car": car,
        "area": area,
        "slot_preference": slot_preference,
        "phone": phone,
    }
    with BOOKING_LOG.open("a") as f:
        f.write(json.dumps(request, ensure_ascii=False) + "\n")
    logger.info(f"Booking request recorded: {request}")
    # The only status this tool can ever return. There is deliberately no
    # confirm_booking tool and no fee-waiver tool, so "your booking is confirmed"
    # and "I've waived the fee" are not things the model is able to transact —
    # the guardrail is the tool surface, not just the prompt.
    await params.result_callback(
        {
            "status": "pending_confirmation",
            "say": "Request noted. Tell the customer the team will confirm shortly. "
            "Do NOT say it is confirmed or that the slot is available.",
        }
    )


#: What domain.build_tools() hands to bot.py.
TOOLS = [record_booking_request]
