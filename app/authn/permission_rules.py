"""Shared permission decisions and the evidence used to explain them."""

from collections.abc import Iterable
from dataclasses import dataclass, replace

from app.i18n import Message


@dataclass(frozen=True)
class PermissionRule:
    permission: str
    effect: str
    scope_kind: str
    scope_id: str
    scope_name: str
    principal_kind: str
    principal_id: str
    principal_name: str
    priority: tuple[int, int]
    protected: bool = False
    inherited_via: tuple[str, ...] = ()


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    rules: tuple[PermissionRule, ...] = ()
    winning: tuple[PermissionRule, ...] = ()
    superseded_by: str | None = None


def decide(
    rules: Iterable[PermissionRule], permissions: Iterable[str]
) -> dict[str, PermissionDecision]:
    indexed: dict[str, list[PermissionRule]] = {}
    for rule in rules:
        indexed.setdefault(rule.permission, []).append(rule)
    result = {}
    for permission in sorted(permissions):
        candidates = tuple(indexed.get(permission, ()))
        priority = max((rule.priority for rule in candidates), default=(-2, -2))
        winners = tuple(rule for rule in candidates if rule.priority == priority)
        result[permission] = PermissionDecision(
            bool(winners) and all(rule.effect == "allow" for rule in winners),
            candidates,
            winners,
        )
    # One submission mode. More-specific mode grants win; equally specific old
    # grants prefer direct submission, matching the label editor's prior behavior.
    request, direct = "printer.submit_requests", "printer.submit_directly"
    if all(
        result.get(key, PermissionDecision(False)).allowed for key in (request, direct)
    ) and not all(any(rule.protected for rule in result[key].winning) for key in (request, direct)):
        preferred = (
            request
            if result[request].winning[0].priority > result[direct].winning[0].priority
            else direct
        )
        suppressed = direct if preferred == request else request
        result[suppressed] = replace(result[suppressed], allowed=False, superseded_by=preferred)
    return result


def validate_submission_modes(permissions: Iterable[str]) -> None:
    if {"printer.submit_requests", "printer.submit_directly"} <= set(permissions):
        raise ValueError(Message("authValidation.chooseEitherSubmitRequestsOrSubmitDirectly"))
