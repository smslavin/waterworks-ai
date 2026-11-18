"""model_params: per-generation request params and visible text (gh-72).

On Opus 5.5 / Sonnet 5.5 the notes a model writes between tool calls come
back in thinking blocks, empty under the default display. Outside thinking
mode the loops now ask for display="updates" and stream those notes as text.
"""

import asyncio
from types import SimpleNamespace as NS

import model_params


def _delta(kind, text):
    field = "thinking" if kind == "thinking_delta" else "text"
    return NS(type="content_block_delta", delta=NS(type=kind, **{field: text}))


STOP = NS(type="content_block_stop")


class _Stream:
    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        async def gen():
            for event in self._events:
                yield event

        return gen()


def _visible(events):
    async def collect():
        return [t async for t in model_params.visible_text(_Stream(events))]

    return "".join(asyncio.run(collect()))


def test_progress_notes_are_shown_and_separated_from_the_answer():
    text = _visible(
        [
            _delta("thinking_delta", "Residual is 3.9 mg/L, "),
            _delta("thinking_delta", "checking dose next."),
            STOP,
            _delta("text_delta", "Dose is high."),
            STOP,
        ]
    )
    assert text == "Residual is 3.9 mg/L, checking dose next.\n\nDose is high."


def test_empty_thinking_blocks_add_nothing():
    # Hidden reasoning arrives as an empty thinking block plus a signature.
    text = _visible(
        [
            _delta("thinking_delta", ""),
            NS(type="content_block_delta", delta=NS(type="signature_delta")),
            STOP,
            _delta("text_delta", "Answer."),
            STOP,
        ]
    )
    assert text == "Answer."


def test_5x_models_ask_for_progress_notes_outside_thinking_mode():
    params = model_params.request_params("claude-sonnet-5-5", effort="medium")
    assert params["thinking"] == {"type": "adaptive", "display": "updates"}
    assert model_params.UPDATES_BETA in params["betas"]
    assert model_params.FALLBACK_BETA in params["betas"]


def test_thinking_mode_keeps_summarized_reasoning_without_the_updates_beta():
    params = model_params.request_params(
        "claude-opus-5-5", effort="high", show_thinking=True
    )
    assert params["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert params["betas"] == [model_params.FALLBACK_BETA]


def test_haiku_gets_no_generation_specific_params():
    assert model_params.request_params("claude-haiku-4-5", effort="low") == {}
