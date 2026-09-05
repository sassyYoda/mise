"""
Parser failure taxonomy (D-37, D-39).
One `except ParseError` covers both cases: a malformed payload and an unregistered source.
Named symbols: ParseError, UnsupportedSourceError
"""
from __future__ import annotations


class ParseError(Exception):
    """
    A raw payload could not be normalised. The caller marks the restaurant UNKNOWN,
    removes nothing and emits nothing (D-39).

    Messages name the defect only and never carry the payload body, so they are safe to log.
    """


class UnsupportedSourceError(ParseError):
    """No parser is registered for this source (`resy` until Phase 3 registers one) (D-37)."""
