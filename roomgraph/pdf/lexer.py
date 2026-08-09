"""Tokenizer and object parser for PDF syntax.

The same grammar covers both the file body (indirect objects) and content
streams, so one lexer serves both. Only what clean CAD exports actually emit is
supported -- no encryption, no cross-reference streams beyond the common case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

WHITESPACE = b"\x00\t\n\x0c\r "
DELIMITERS = b"()<>[]{}/%"


@dataclass(frozen=True)
class Name:
    value: str

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"/{self.value}"


@dataclass(frozen=True)
class Ref:
    num: int
    gen: int


@dataclass(frozen=True)
class Keyword:
    value: str

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return self.value


@dataclass
class Stream:
    dict: dict[str, Any]
    raw: bytes


class Lexer:
    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    # -- low level ---------------------------------------------------------
    def at_end(self) -> bool:
        return self.pos >= len(self.data)

    def skip_ws(self) -> None:
        d, n = self.data, len(self.data)
        while self.pos < n:
            c = d[self.pos]
            if c in WHITESPACE:
                self.pos += 1
            elif c == 0x25:  # '%' comment runs to end of line
                while self.pos < n and d[self.pos] not in b"\r\n":
                    self.pos += 1
            else:
                return

    def _read_regular(self) -> bytes:
        start = self.pos
        d, n = self.data, len(self.data)
        while self.pos < n and d[self.pos] not in WHITESPACE and d[self.pos] not in DELIMITERS:
            self.pos += 1
        return d[start : self.pos]

    def _read_name(self) -> Name:
        self.pos += 1  # skip '/'
        raw = self._read_regular()
        out = bytearray()
        i = 0
        while i < len(raw):
            if raw[i] == 0x23 and i + 2 < len(raw):  # '#' hex escape
                try:
                    out.append(int(raw[i + 1 : i + 3], 16))
                    i += 3
                    continue
                except ValueError:
                    pass
            out.append(raw[i])
            i += 1
        return Name(out.decode("latin-1"))

    def _read_literal_string(self) -> bytes:
        self.pos += 1  # skip '('
        depth = 1
        out = bytearray()
        d, n = self.data, len(self.data)
        while self.pos < n:
            c = d[self.pos]
            if c == 0x5C:  # backslash
                self.pos += 1
                if self.pos >= n:
                    break
                e = d[self.pos]
                mapping = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
                if e in mapping:
                    out.append(mapping[e])
                    self.pos += 1
                elif 0x30 <= e <= 0x37:  # octal
                    oct_digits = bytearray()
                    while self.pos < n and len(oct_digits) < 3 and 0x30 <= d[self.pos] <= 0x37:
                        oct_digits.append(d[self.pos])
                        self.pos += 1
                    out.append(int(oct_digits, 8) & 0xFF)
                elif e in b"\r\n":  # line continuation
                    self.pos += 1
                    if self.pos < n and d[self.pos] == 0x0A and e == 0x0D:
                        self.pos += 1
                else:
                    out.append(e)
                    self.pos += 1
                continue
            if c == 0x28:
                depth += 1
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    break
            out.append(c)
            self.pos += 1
        return bytes(out)

    def _read_hex_string(self) -> bytes:
        self.pos += 1  # skip '<'
        digits = bytearray()
        d, n = self.data, len(self.data)
        while self.pos < n and d[self.pos] != 0x3E:
            c = d[self.pos]
            if c not in WHITESPACE:
                digits.append(c)
            self.pos += 1
        self.pos += 1  # skip '>'
        if len(digits) % 2:
            digits.append(0x30)
        try:
            return bytes.fromhex(digits.decode("latin-1"))
        except ValueError:
            return b""

    # -- token stream ------------------------------------------------------
    def next_token(self) -> Any:
        """Returns a python value, Name, Keyword, or None at end of input."""
        self.skip_ws()
        if self.at_end():
            return None
        d = self.data
        c = d[self.pos]

        if c == 0x2F:
            return self._read_name()
        if c == 0x28:
            return self._read_literal_string()
        if c == 0x3C:
            if self.pos + 1 < len(d) and d[self.pos + 1] == 0x3C:
                self.pos += 2
                return Keyword("<<")
            return self._read_hex_string()
        if c == 0x3E and self.pos + 1 < len(d) and d[self.pos + 1] == 0x3E:
            self.pos += 2
            return Keyword(">>")
        if c in b"[]{}":
            self.pos += 1
            return Keyword(chr(c))
        if c == 0x29:  # stray ')'
            self.pos += 1
            return Keyword(")")

        raw = self._read_regular()
        if not raw:
            self.pos += 1
            return Keyword(chr(c))
        text = raw.decode("latin-1")
        if text in ("true", "false"):
            return text == "true"
        if text == "null":
            return Keyword("null")  # _parse_from turns this into None
        try:
            if any(ch in text for ch in ".eE") and text not in ("e", "E"):
                return float(text)
            return int(text)
        except ValueError:
            pass
        try:
            return float(text.replace("--", "-"))
        except ValueError:
            return Keyword(text)

    # -- object parser -----------------------------------------------------
    def parse_object(self) -> Any:
        """Parse one complete object: arrays, dicts and `num gen R` references."""
        return self._parse_from(self.next_token())

    def _parse_from(self, tok: Any) -> Any:
        if isinstance(tok, Keyword):
            if tok.value == "<<":
                return self._parse_dict()
            if tok.value == "[":
                return self._parse_array()
            if tok.value == "null":
                return None
        if isinstance(tok, int):
            # Possible "num gen R" reference; look ahead without committing.
            save = self.pos
            t2 = self.next_token()
            if isinstance(t2, int):
                t3 = self.next_token()
                if isinstance(t3, Keyword) and t3.value == "R":
                    return Ref(tok, t2)
            self.pos = save
        return tok

    def _parse_array(self) -> list[Any]:
        out: list[Any] = []
        while True:
            tok = self.next_token()
            if tok is None:
                break
            if isinstance(tok, Keyword) and tok.value == "]":
                break
            out.append(self._parse_from(tok))
        return out

    def _parse_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        while True:
            tok = self.next_token()
            if tok is None:
                break
            if isinstance(tok, Keyword) and tok.value == ">>":
                break
            if not isinstance(tok, Name):
                continue  # malformed key; skip defensively
            out[tok.value] = self._parse_from(self.next_token())
        return out
