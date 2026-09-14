"""Tokenize the expression subset of mathlang."""

from dataclasses import dataclass
from enum import Enum

from .source import ParseError, SourceSpan
from .symbols import SYSTEM_IDENTIFIERS


class TokenKind(Enum):
    NUMBER = "number"
    IDENTIFIER = "identifier"
    PLUS = "+"
    MINUS = "-"
    STAR = "*"
    CROSS = "×"
    SLASH = "/"
    CARET = "^"
    LPAREN = "("
    RPAREN = ")"
    COMMA = ","
    EQUAL = "="
    COLON = ":"
    LESS = "<"
    GREATER = ">"
    SEMICOLON = ";"
    NEWLINE = "newline"
    PIPELINE = "|>"
    ARROW = "->"
    FATARROW = "=>"
    EQEQ = "=="
    STRUCTURAL = "==="
    NOTEQUAL = "!="
    LESSEQUAL = "<="
    GREATEREQUAL = ">="
    LBRACE = "{"
    RBRACE = "}"
    DOT = "."
    EOF = "end of input"


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    text: str
    span: SourceSpan


_PUNCTUATION = {kind.value: kind for kind in TokenKind if len(kind.value) == 1}
_DOUBLE_PUNCTUATION = {kind.value: kind for kind in TokenKind if len(kind.value) == 2}


def tokenize(source: str, *, keep_newlines: bool = False) -> list[Token]:
    tokens: list[Token] = []
    offset, line, column = 0, 1, 1

    def advance() -> None:
        nonlocal offset, line, column
        if source[offset] == "\n":
            line += 1
            column = 1
        else:
            column += 1
        offset += 1

    def newline() -> None:
        if keep_newlines:
            tokens.append(Token(
                TokenKind.NEWLINE, "\n", SourceSpan(offset, offset + 1, line, column),
            ))

    while offset < len(source):
        char = source[offset]
        if char.isspace():
            if char == "\n":
                newline()
            advance()
            continue

        start, start_line, start_column = offset, line, column
        if source.startswith("//", offset):
            while offset < len(source) and source[offset] != "\n":
                advance()
            continue
        if source.startswith("/*", offset):
            advance()
            advance()
            while offset < len(source) and not source.startswith("*/", offset):
                if source[offset] == "\n":
                    newline()
                advance()
            if offset == len(source):
                raise ParseError(
                    "Unterminated block comment", source,
                    SourceSpan(start, offset, start_line, start_column),
                )
            advance()
            advance()
            continue

        if source.startswith('===', offset):
            kind = TokenKind.STRUCTURAL
            advance()
            advance()
            advance()
        elif source[offset:offset+2] in _DOUBLE_PUNCTUATION:
            kind = _DOUBLE_PUNCTUATION[source[offset:offset+2]]
            advance()
            advance()
        elif char in "0123456789":
            kind = TokenKind.NUMBER
            while offset < len(source) and source[offset] in "0123456789":
                advance()
            if (offset + 1 < len(source) and source[offset] == "."
                    and source[offset + 1] in "0123456789"):
                advance()
                while offset < len(source) and source[offset] in "0123456789":
                    advance()
        elif char == '$':
            kind = TokenKind.IDENTIFIER
            advance()
            if offset == len(source) or not source[offset].isidentifier():
                raise ParseError("Expected an identifier immediately after '$'", source,
                                 SourceSpan(start, offset, start_line, start_column))
            advance()
            while offset < len(source) and ("a" + source[offset]).isidentifier():
                advance()
        elif char in SYSTEM_IDENTIFIERS:
            kind = TokenKind.IDENTIFIER
            advance()
        elif char.isidentifier():
            kind = TokenKind.IDENTIFIER
            advance()
            # Prefixing with a letter also recognizes combining marks and digits.
            while offset < len(source) and ("a" + source[offset]).isidentifier():
                advance()
        elif char in _PUNCTUATION:
            kind = _PUNCTUATION[char]
            advance()
        else:
            raise ParseError(
                f"Unexpected character {char!r}", source,
                SourceSpan(offset, offset + 1, line, column),
            )

        tokens.append(Token(
            kind, source[start:offset],
            SourceSpan(start, offset, start_line, start_column),
        ))

    tokens.append(Token(TokenKind.EOF, "", SourceSpan(offset, offset, line, column)))
    return tokens
