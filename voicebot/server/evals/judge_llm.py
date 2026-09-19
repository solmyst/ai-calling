"""The eval judge, pointed at Park+'s own LLM.

Pipecat's default judge is a local Ollama (`gemma4:12b`). Without one running,
every assertion fails with `judge call failed: NotFoundError`, and pulling it is
a 7.6 GB download.

Park+ already runs an OpenAI-compatible model with no quota and no bill, so the
judge uses that instead. It is also the same model the bot answers with, which is
worth being aware of: a judge marking its own homework is lenient about its own
habits. That is acceptable here because the assertions are about FACTS the
guardrails enforce — was a rupee figure said, was the car asked for — not about
style. Point `PARKPLUS_LLM_URL` elsewhere, or set a `factory` on a different
provider, if a judgement ever needs to be adversarial.
"""

import os

from pipecat.services.openai.llm import OpenAILLMService


def make_judge(config):
    """Build the judge LLM from a scenario's `judge.eval.factory` block.

    Prefers Bifrost when BIFROST_VK is set. The Park+ vLLM works as a judge but
    was observed answering `continue` on turns its own reasoning had already
    decided — "the bot still needs the car's brand and model before giving any
    price" is the pass condition for that assertion, returned as a non-verdict.
    A judge that cannot commit fails good turns, which is worse than no judge.
    """
    # JUDGE_BACKEND=parkplus forces the judge off Bifrost. Not a style
    # preference: Bifrost's virtual key is budget-capped, and when it runs out
    # every scenario fails with "judge call failed: APIStatusError" while the
    # BOT is perfectly healthy on its own Park+ fallback. That reads exactly
    # like a broken bot and is not, so it needs to be one env var to rule out.
    vk = os.getenv("BIFROST_VK")
    if vk and os.getenv("JUDGE_BACKEND", "bifrost").lower() != "parkplus":
        return OpenAILLMService(
            api_key="not-needed",
            base_url=os.getenv("BIFROST_URL") or "https://bifrost.parkplus.io/v1",
            default_headers={"x-bf-vk": vk},
            settings=OpenAILLMService.Settings(
                model=config.get("model") or "gemini/gemini-3.6-flash",
                extra={"reasoning_effort": "none"},
            ),
        )
    return OpenAILLMService(
        # The server ignores the key, but the OpenAI client requires a string.
        api_key=os.getenv("PARKPLUS_LLM_API_KEY") or "not-needed",
        base_url=os.getenv("PARKPLUS_LLM_URL") or "https://llm.parkplus.io/v1",
        settings=OpenAILLMService.Settings(
            model=config.get("model")
            or os.getenv("PARKPLUS_LLM_MODEL")
            or "ulkaa/Ornith-1.5-35B-A3B-AWQ-INT4",
            # Without this the model writes its reasoning into the response body
            # — "The user is asking about..." — and the judge's yes/no parse then
            # reads the thinking instead of the verdict.
            extra={"reasoning_effort": "none"},
        ),
    )


#: The simulated caller's LLM, for a scenario's `simulator:` block.
#:
#: Same wiring as the judge — Park+'s Bifrost gateway, no extra key, no local
#: Ollama download — under a name that reads correctly where it is used. Without
#: a factory the harness builds a bare OpenAI client and every simulation dies
#: with "Missing credentials ... set the OPENAI_API_KEY environment variable".
make_caller = make_judge
