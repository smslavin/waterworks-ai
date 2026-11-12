"""Request settings that differ by Claude model generation.

Claude Opus 5.5 and Sonnet 5.5 always think (adaptive thinking; disabling it
is a 400), count that thinking against `max_tokens`, return its text only when
`display` asks for it, and can decline a request with `stop_reason: "refusal"`.
Haiku 4.5 does none of this and rejects `effort` outright, so every
generation-specific parameter is added only for the 5.x models.

Callers send these through `client.beta.messages` — server-side refusal
fallback (`fallbacks: "default"`) is a beta parameter. With no betas (Haiku)
the beta endpoint behaves like the regular one.
"""

from __future__ import annotations

ADAPTIVE_MODEL_PREFIXES = ("claude-opus-5", "claude-sonnet-5", "claude-fable-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Thinking counts toward max_tokens; a limit sized for a no-thinking reply
# cuts replies off. Every caller streams, so a large limit can't time out.
ADAPTIVE_MAX_TOKENS = 32000


def is_adaptive(model: str) -> bool:
    return model.startswith(ADAPTIVE_MODEL_PREFIXES)


def request_params(model: str, *, effort: str, show_thinking: bool = False) -> dict:
    """Extra Messages API params for `model`; empty for pre-5.x models.

    `effort` is set explicitly because Opus 5.5 defaults to `medium` and
    Sonnet 5.5 to `high`. `show_thinking` returns a readable summary of the
    reasoning (the default display leaves thinking text empty).
    """
    if not is_adaptive(model):
        return {}
    params = {
        "max_tokens": ADAPTIVE_MAX_TOKENS,
        "output_config": {"effort": effort},
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
    }
    if show_thinking:
        params["thinking"] = {"type": "adaptive", "display": "summarized"}
    return params


def assistant_turn(content) -> list[dict]:
    """The assistant message to send back in a tool loop: every block as the
    API returned it. Thinking blocks must come back unchanged, or the model
    loses its reasoning between tool calls; the 5.x models also check that
    replayed blocks match the conversation that produced them."""
    return [block.to_dict() for block in content]


def refusal_message(final) -> str | None:
    """A user-facing error for a declined request, or None."""
    if final.stop_reason != "refusal":
        return None
    details = getattr(final, "stop_details", None)
    category = getattr(details, "category", None)
    return "The model declined this request" + (
        f" (safety category: {category})." if category else "."
    )
