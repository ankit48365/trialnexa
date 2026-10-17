"""Lexical source representations; never normalize or convert stored values."""

import re
import unicodedata
from datetime import date, datetime

INTEGER = re.compile(r"[+-]?[0-9]+\Z")
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
MONTHS = {
    month.casefold(): index
    for index, month in enumerate(
        (
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ),
        start=1,
    )
}


def header_tokens(value: str) -> tuple[str, ...]:
    """Nonclinical tokens, used only for identifier/date structural hints."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    text = unicodedata.normalize("NFKC", text).casefold()
    return tuple(re.findall(r"[^\W_]+", text))


def observe_date(value: str) -> tuple[str | None, tuple[str, ...]]:
    """List possible formats without choosing between US/EU slash-date locales."""
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            date.fromisoformat(value)
            return "date", ("YYYY-MM-DD",)
        except ValueError:
            return "invalid_date", ()
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}.*", value):
        try:
            datetime.fromisoformat(value)
            return "datetime", ("ISO 8601 datetime",)
        except ValueError:
            return "invalid_date", ()
    match = re.fullmatch(r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})", value)
    if match:
        first, second, year = map(int, match.groups())
        formats = []
        for month, day, label in (
            (first, second, "MM/DD/YYYY"),
            (second, first, "DD/MM/YYYY"),
        ):
            try:
                date(year, month, day)
                formats.append(label)
            except ValueError:
                pass
        return ("date" if formats else "invalid_date"), tuple(formats)
    match = re.fullmatch(r"([0-9]{1,2})-([A-Za-z]{3})-([0-9]{4})", value)
    if match:
        day, month, year = match.groups()
        try:
            date(int(year), MONTHS[month.casefold()], int(day))
            return "date", ("DD-Mon-YYYY",)
        except (ValueError, KeyError):
            return "invalid_date", ()
    return None, ()


def representation(value: str) -> tuple[str, tuple[str, ...]]:
    """Infer syntax from the raw string, including any surrounding whitespace."""
    if INTEGER.fullmatch(value):
        return "integer", ()
    if NUMBER.fullmatch(value):
        return "decimal", ()
    if value.casefold() in {"true", "false", "yes", "no"}:
        return "boolean", ()
    kind, formats = observe_date(value)
    return (kind, formats) if kind else ("string", ())
