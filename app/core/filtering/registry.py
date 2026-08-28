"""
app/core/filtering/registry.py

Phase 1, Track B, task 4: a small registration mechanism so a new filter
operation -- built-in or a project's custom one (source doc §4/§6) -- can
be added by defining one class and decorating it, instead of editing a
big if/elif chain somewhere in the config loader or query path.

This is what lets task 3's YAML config loader stay generic:

    filter_cls = get_filter_class(field_config.operation)
    filter_instance = filter_cls(field_type=field_config.type, item_type=field_config.item_type)

...for ANY operation, built-in or custom, without that code ever naming a
concrete class. A project adding a new operation (source doc §9:
metadata-driven, domain-agnostic filtering) is a new class with one
`@register_filter("...")` decorator, not a change to core.
"""
from __future__ import annotations

from typing import Type

from app.core.filtering.base import Filter, FilterError

_FILTER_REGISTRY: dict[str, Type[Filter]] = {}


def register_filter(operation: str):
    """Class decorator: register a Filter subclass under `operation`.

    The class must declare `operation = "<same string>"` itself --
    the decorator checks the two match rather than setting the attribute
    for the class, so a class's `operation` is always visible right there
    in its own definition, not assigned invisibly by a decorator
    somewhere else.

    Raises at class-definition time (import time), not later at query
    time, if:
      - the class's own `operation` doesn't match the decorator argument, or
      - a DIFFERENT class is already registered under this operation name.
    Two filter classes silently fighting over one operation name is
    exactly the kind of bug that should surface immediately, not manifest
    as "the wrong filter ran" deep inside a search request.
    """

    def decorator(cls: Type[Filter]) -> Type[Filter]:
        declared = getattr(cls, "operation", None)
        if declared != operation:
            raise ValueError(
                f"@register_filter('{operation}') applied to {cls.__name__}, but "
                f"{cls.__name__}.operation is {declared!r} -- they must match."
            )
        existing = _FILTER_REGISTRY.get(operation)
        if existing is not None and existing is not cls:
            raise ValueError(
                f"filter operation '{operation}' is already registered to "
                f"{existing.__name__} -- cannot also register {cls.__name__}. "
                "Two filter classes cannot share one operation name."
            )
        _FILTER_REGISTRY[operation] = cls
        return cls

    return decorator


def get_filter_class(operation: str) -> Type[Filter]:
    """The lookup task 3's config loader uses to turn a declared
    `operation` string into the right Filter class."""
    try:
        return _FILTER_REGISTRY[operation]
    except KeyError:
        raise FilterError(
            f"no filter is registered for operation '{operation}' "
            f"(registered operations: {sorted(_FILTER_REGISTRY)})"
        ) from None


def list_registered_operations() -> list[str]:
    return sorted(_FILTER_REGISTRY)