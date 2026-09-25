# SPDX-License-Identifier: Apache-2.0
"""Decisions: typed answers with probabilities instead of text (``-> choice``, ``-> yes``, ``-> score``).

A decision asks a model to pick one of a few answers and returns how likely each one is. On an
OpenAI-compatible server (llama.cpp, vLLM, Ollama, OpenAI) the options are labelled A, B, C…,
the model writes exactly one token, and the probabilities of the letters come from the server's
``logprobs``: one forward pass, no generated text. The same questions can go to a server that
speaks the ``/v1/systemone`` protocol (Jev by TypeSafe, or open servers such as Kev) through
``llm.SystemOne``.
"""

from __future__ import annotations

import math
import string
from typing import Any, Dict, List, Optional, Tuple

from ..errors import UpsilError

LETTERS = string.ascii_uppercase
MAX_OPTIONS = len(LETTERS)
MIN_MASS = 0.5          # at least half of the first token's probability must be on option letters

SYSTEM_INSTRUCTION = ("You make one decision. Read the text and the question, then reply with the letter "
                      "of exactly one option and nothing else.")


def _show(value: Any) -> str:
    from .prelude import show
    return show(value)


class Question:
    """A question for ``m.decide(state, {...})``: ``llm.Yes(q)``, ``llm.Choice(q, options)``,
    ``llm.Score(q, levels)``."""

    __slots__ = ("kind", "text", "options", "descriptions")

    def __init__(self, kind: str, text: Any, options: Any = None):
        self.kind = kind
        self.text = _show(text)
        if kind == "yes":
            self.options: List[Any] = [True, False]
            self.descriptions: List[Optional[str]] = [None, None]
        else:
            self.options, self.descriptions = normalize_options(kind, options)

    def __repr__(self) -> str:
        if self.kind == "yes":
            return f"llm.Yes({self.text!r})"
        name = "Choice" if self.kind == "choice" else "Score"
        return f"llm.{name}({self.text!r}, {self.options!r})"


def Yes(text: Any) -> Question:
    """A yes/no question; its answer is the probability of «yes» (0.0–1.0)."""
    return Question("yes", text)


def Choice(text: Any, options: Any) -> Question:
    """Pick one option: a list ``["billing", "tech"]`` or ``{"billing": "money, invoices", ...}``."""
    return Question("choice", text, options)


def Score(text: Any, levels: Any) -> Question:
    """A place on an ordered scale: ``0..=3``, ``1..=5`` or ``["low", "medium", "high"]``."""
    return Question("score", text, levels)


def normalize_options(kind: str, options: Any) -> Tuple[List[Any], List[Optional[str]]]:
    """Options as (values, descriptions); checks the count and duplicates."""
    what_en, what_ru = ("options", "варианты") if kind == "choice" else ("levels", "уровни")
    if isinstance(options, range):
        options = list(options)
    if isinstance(options, dict):
        values = list(options.keys())
        descriptions = [None if d is None else _show(d) for d in options.values()]
    elif isinstance(options, (list, tuple)):
        values = list(options)
        descriptions = [None] * len(values)
    else:
        raise UpsilError(f"-> {kind}: the {what_en} are a list or a dict, not {_show(options)}",
                         f"-> {kind}: {what_ru} — это список или словарь, а не {_show(options)}")
    low = 2
    high = MAX_OPTIONS if kind == "choice" else 10
    if not low <= len(values) <= high:
        raise UpsilError(f"-> {kind}: from {low} to {high} {what_en}, got {len(values)}",
                         f"-> {kind}: нужно от {low} до {high} вариантов, а их {len(values)}")
    seen = set()
    for v in values:
        if not isinstance(v, (str, int, float, bool)):
            raise UpsilError(f"-> {kind}: an option is a string or a number, not {_show(v)}",
                             f"-> {kind}: вариант — строка или число, а не {_show(v)}")
        key = _show(v)
        if key in seen:
            raise UpsilError(f"-> {kind}: {_show(v)} is listed twice", f"-> {kind}: {_show(v)} указан дважды")
        seen.add(key)
    return values, descriptions


class Decision:
    """The answer to ``-> choice(...)`` / ``-> score(...)``.

    ``value`` is the likeliest option and ``p`` its probability; ``probs`` holds every option's
    probability (a record in the options' order). For a scale, ``mean`` is the expected level
    (for levels given as words, the expected position 0, 1, 2…). A decision equals its value:
    ``if team == "billing" and team.p > 0.8 { ... }``."""

    __slots__ = ("kind", "options", "probs", "value", "p", "mean")

    def __init__(self, kind: str, options: List[Any], probabilities: List[float]):
        from .prelude import Record
        self.kind = kind
        self.options = list(options)
        best = max(range(len(options)), key=lambda i: probabilities[i])
        self.value = options[best]
        self.p = probabilities[best]
        self.probs = Record((o, round(p, 6)) for o, p in zip(options, probabilities))
        self.mean: Optional[float] = None
        if kind == "score":
            numeric = all(isinstance(o, (int, float)) and not isinstance(o, bool) for o in options)
            positions = options if numeric else list(range(len(options)))
            self.mean = sum(float(x) * p for x, p in zip(positions, probabilities))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Decision):
            return self.value == other.value and self.probs == other.probs
        return bool(self.value == other)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(self.value)

    def __str__(self) -> str:
        return f"{_show(self.value)} ({round(self.p * 100)}%)"

    __repr__ = __str__


# ---------------------------------------------------------------------- the logprobs method

def build_messages(question: Question, state: Optional[str], system: Optional[str]) -> List[Dict[str, str]]:
    """System instruction + [state] + question + lettered options; the state comes first so that a
    server with a prompt cache (llama.cpp) reuses it across the questions of one ``decide``."""
    lines: List[str] = []
    if state is not None:
        lines += [state, ""]
    lines.append(question.text if state is None else f"Question: {question.text}")
    lines.append("")
    if question.kind == "score":
        lines.append("Options (from the lowest to the highest):")
    else:
        lines.append("Options:")
    labels = ["Yes", "No"] if question.kind == "yes" else [_show(o) for o in question.options]
    for letter, label, desc in zip(LETTERS, labels, question.descriptions):
        lines.append(f"{letter}. {label}" + (f": {desc}" if desc else ""))
    lines.append("")
    lines.append("Answer with one letter: " + ", ".join(LETTERS[:len(labels)]) + ".")
    sys_text = SYSTEM_INSTRUCTION if not system else f"{system}\n\n{SYSTEM_INSTRUCTION}"
    return [{"role": "system", "content": sys_text}, {"role": "user", "content": "\n".join(lines)}]


def _letter(token: str, count: int) -> Optional[str]:
    t = token.strip().strip(".):*").strip().upper()
    if len(t) == 1 and t in LETTERS[:count]:
        return t
    return None


def letter_probabilities(data: Any, count: int) -> Tuple[List[float], str]:
    """Probabilities of the option letters from a chat completion with ``logprobs``; also the likeliest
    first token (for error messages)."""
    from .llm import FormatError, LLMError
    try:
        first = data["choices"][0]["logprobs"]["content"][0]
        tops = first.get("top_logprobs") or [{"token": first.get("token"), "logprob": first.get("logprob")}]
    except (KeyError, IndexError, TypeError):
        raise LLMError(
            "The model server does not return probabilities (logprobs), which decisions need. "
            "It works with llama.cpp (sos models serve), vLLM, Ollama and OpenAI; or use llm.SystemOne",
            "Сервер модели не отдаёт вероятности (logprobs), а для решений они нужны. Подойдут llama.cpp "
            "(sos models serve), vLLM, Ollama и OpenAI; или llm.SystemOne") from None
    mass = [0.0] * count
    likeliest, best = "", -math.inf
    for item in tops:
        if not isinstance(item, dict):
            continue
        token = str(item.get("token") or "")
        try:
            lp = float(item.get("logprob"))
        except (TypeError, ValueError):
            continue
        if lp > best:
            likeliest, best = token, lp
        letter = _letter(token, count)
        if letter is not None:
            mass[LETTERS.index(letter)] += math.exp(lp)
    total = sum(mass)
    if total < MIN_MASS:
        shown = likeliest.strip() or likeliest
        raise FormatError(
            f"The model does not answer with an option letter (its likeliest first token is {shown!r}). "
            f"Reasoning models think before answering: for decisions use a model without that mode",
            f"Модель не отвечает буквой варианта (её самый вероятный первый токен — {shown!r}). "
            f"Модели с размышлениями думают перед ответом: для решений возьмите модель без этого режима",
            reply=likeliest)
    return [m / total for m in mass], likeliest


def result(question: Question, probabilities: List[float]) -> Any:
    """``-> yes`` gives the probability of yes; the others a Decision."""
    if question.kind == "yes":
        return round(probabilities[0], 6)
    return Decision(question.kind, question.options, probabilities)


# ---------------------------------------------------------------------- the /v1/systemone protocol

def systemone_question(question: Question, system: Optional[str]) -> Dict[str, Any]:
    text = question.text if not system else f"{system}\n\n{question.text}"
    if question.kind == "yes":
        return {"type": "noul", "instructions": text}
    if question.kind == "choice":
        return {"type": "choice", "instructions": text,
                "criteria": {_show(o): (d or _show(o)) for o, d in zip(question.options, question.descriptions)}}
    return {"type": "score", "instructions": text,
            "criteria": [(f"{_show(o)}: {d}" if d else _show(o)) for o, d in zip(question.options, question.descriptions)]}


def systemone_result(question: Question, answer: Any) -> Any:
    from .llm import LLMError
    try:
        if question.kind == "yes":
            return round(float(answer["noul"]), 6)
        probs = answer["probabilities"]
        if question.kind == "choice":
            ps = [float(probs.get(_show(o), 0.0)) for o in question.options]
        else:
            ps = [float(probs.get(str(i), 0.0)) for i in range(len(question.options))]
    except (KeyError, TypeError, ValueError, AttributeError):
        raise LLMError(f"Unexpected /v1/systemone answer: {_show(answer)}",
                       f"Неожиданный ответ /v1/systemone: {_show(answer)}") from None
    total = sum(ps)
    if total <= 0:
        raise LLMError(f"The /v1/systemone answer has no probabilities: {_show(answer)}",
                       f"В ответе /v1/systemone нет вероятностей: {_show(answer)}")
    return Decision(question.kind, question.options, [p / total for p in ps])
