"""Locations in the original source, measured in Unicode characters."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """A half-open offset range; line and column are one-based."""

    start: int
    end: int
    line: int
    column: int

    def through(self, other: "SourceSpan") -> "SourceSpan":
        return SourceSpan(self.start, other.end, self.line, self.column)


class LanguageError(ValueError):
    """A language error with its position in the source."""

    def __init__(self, message: str, source: str, span: SourceSpan) -> None:
        self.message = message
        self.source = source
        self.span = span
        super().__init__(message)

    def __str__(self) -> str:
        line_start = self.source.rfind("\n", 0, self.span.start) + 1
        line_end = self.source.find("\n", self.span.start)
        if line_end == -1:
            line_end = len(self.source)
        line = self.source[line_start:line_end].rstrip("\r").expandtabs(4)
        prefix = self.source[line_start:self.span.start].expandtabs(4)
        return (
            f"{self.message} (line {self.span.line}, column {self.span.column})\n"
            f"{line}\n{' ' * len(prefix)}^"
        )


class ParseError(LanguageError):
    """A lexical or syntax error."""


class DefinitionError(LanguageError):
    """An invalid definition or expression operation."""
