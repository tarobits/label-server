"""Keep synchronous request transactions within one worker invocation."""

import inspect
from collections.abc import Callable, Generator
from contextlib import contextmanager
from functools import wraps
from typing import Any, cast, get_args

from fastapi import APIRouter, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import ResponseValidationError
from fastapi.params import Depends
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

Transaction = Callable[[Request], Generator[Session, None, None]]


def transaction_dependency(function: Transaction) -> Transaction:
    """Mark a session provider for execution around the endpoint, not across workers."""
    setattr(function, "__request_transaction__", True)
    return function


def transaction_endpoint(
    endpoint: Callable[..., Any], validate_response: Callable[[Any], None]
) -> Callable[..., Any]:
    signature = inspect.signature(endpoint, eval_str=True)
    transactions: list[tuple[str, Transaction]] = []
    for parameter in signature.parameters.values():
        dependencies = [parameter.default, *get_args(parameter.annotation)]
        for dependency in dependencies:
            if isinstance(dependency, Depends) and getattr(
                dependency.dependency, "__request_transaction__", False
            ):
                transactions.append((parameter.name, cast(Transaction, dependency.dependency)))
    if not transactions:
        return endpoint
    if len(transactions) != 1 or inspect.iscoroutinefunction(endpoint):
        raise TypeError("Transactional endpoints must be synchronous with one session provider")
    session_name, provider = transactions[0]
    parameters = [p for p in signature.parameters.values() if p.name != session_name]
    request_name = next((p.name for p in parameters if p.annotation is Request), None)
    injected_request = request_name is None
    if injected_request:
        request_name = "transaction_request"
        if request_name in signature.parameters:
            raise TypeError("Reserved transaction request parameter")
        parameters.append(
            inspect.Parameter(request_name, inspect.Parameter.KEYWORD_ONLY, annotation=Request)
        )
    assert request_name is not None
    public_signature = signature.replace(parameters=parameters)

    @wraps(endpoint)
    def execute(*args: Any, **kwargs: Any) -> Any:
        arguments = public_signature.bind(*args, **kwargs).arguments
        request = arguments[request_name]
        if injected_request:
            del arguments[request_name]
        # No worker handoff while holding a transaction lock. Cleanup also runs
        # here on endpoint errors, before the worker returns to the shared pool.
        with contextmanager(provider)(request) as session:
            arguments[session_name] = session
            result = endpoint(**arguments)
            validate_response(result)
            return result

    setattr(execute, "__signature__", public_signature)
    return execute


class TransactionRouter(APIRouter):
    def add_api_route(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        def validate_response(result: Any) -> None:
            if isinstance(result, Response):
                return
            # Check the route's actual response contract before committing. FastAPI
            # still constructs the response (including headers/background tasks).
            field = route.response_field
            if field is None:
                jsonable_encoder(result)
                return
            value, errors = field.validate(result, {}, loc=("response",))
            if errors:
                raise ResponseValidationError(errors=errors, body=result)
            field.serialize(
                value,
                include=route.response_model_include,
                exclude=route.response_model_exclude,
                by_alias=route.response_model_by_alias,
                exclude_unset=route.response_model_exclude_unset,
                exclude_defaults=route.response_model_exclude_defaults,
                exclude_none=route.response_model_exclude_none,
            )

        super().add_api_route(path, transaction_endpoint(endpoint, validate_response), **kwargs)
        registered = self.routes[-1]
        assert isinstance(registered, APIRoute)
        route: APIRoute = registered
