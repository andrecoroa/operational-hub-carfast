"""Transversal post-action decision contract; no route uses it without a gate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.return_context import resolve_return_context


class PostAction(StrEnum):
    SAVE = "save"
    SAVE_AND_CLOSE = "save_and_close"
    FINISH = "finish"
    CANCEL = "cancel"
    BACK = "back"


@dataclass(frozen=True, slots=True)
class PostActionDecision:
    destination: str
    persist: bool
    source: str


def decide_post_action(
    action: PostAction,
    *,
    current_path: str,
    logical_fallback: str,
    secret: str,
    return_token: str | None = None,
    allowed_prefixes: tuple[str, ...] = ("/v2-clean",),
    enabled: bool = False,
) -> PostActionDecision:
    """Return a safe destination while retaining legacy behaviour when disabled."""

    persist = action not in {PostAction.CANCEL, PostAction.BACK}
    if not enabled:
        return PostActionDecision(current_path, persist, "legacy")
    if action is PostAction.SAVE:
        return PostActionDecision(current_path, True, "current")
    context = (
        resolve_return_context(secret, return_token, allowed_prefixes=allowed_prefixes)
        if return_token
        else None
    )
    return PostActionDecision(
        context.url if context else logical_fallback,
        persist,
        "return_context" if context else "logical_fallback",
    )
