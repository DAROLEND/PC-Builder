"""Read a Nuxt 2 page state (``window.__NUXT__``) *without executing it*.

Nuxt 2 serialises the server-side state as a self-calling function whose
parameters stand for repeated values::

    window.__NUXT__=(function(a,b,c){a.x="y";return {title:c,price:b,items:[a]}}
                     ({},19299,"Ryzen 5 5500"));

That is data, not logic, so instead of running someone else's JavaScript this
module parses the small subset of syntax the serialiser emits: literals,
object and array literals, parameter references, ``void 0``, ``Array(n)``,
``Object.create(null)``, ``new Date(n)`` and simple ``x.key=value`` /
``x[0]=value`` assignments before ``return``. Anything else raises
:class:`NuxtStateError`, and callers treat that as "no extra data" — a changed
page can make us learn less, never run foreign code.
"""

from __future__ import annotations

import re
from typing import Any

MAX_SOURCE = 4 * 1024 * 1024  # the state of a product page is ~250 KB
MAX_ARRAY = 10_000  # Array(n) placeholders are small; refuse absurd sizes


class NuxtStateError(ValueError):
    pass


_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<number>-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<name>[A-Za-z_$][\w$]*)
  | (?P<punct>[{}\[\]():,;.=])
    """,
    re.VERBOSE,
)
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
_LITERALS = {"true": True, "false": False, "null": None}


def _unquote(raw: str) -> str:
    body, out, i = raw[1:-1], [], 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt == "u":
            out.append(chr(int(body[i + 2 : i + 6], 16)))
            i += 6
        elif nxt == "x":
            out.append(chr(int(body[i + 2 : i + 4], 16)))
            i += 4
        else:
            out.append(_ESCAPES.get(nxt, nxt))
            i += 2
    return "".join(out)


def _tokenize(source: str) -> list[tuple[str, str]]:
    tokens, pos = [], 0
    while pos < len(source):
        match = _TOKEN.match(source, pos)
        if not match:
            raise NuxtStateError(f"unexpected character {source[pos]!r} at {pos}")
        kind = match.lastgroup
        if kind != "ws":
            tokens.append((kind, match.group()))
        pos = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.tokens = tokens
        self.pos = 0
        self.scope: dict[str, Any] = {}

    # --- token helpers
    def peek(self, offset: int = 0) -> tuple[str, str]:
        index = self.pos + offset
        return self.tokens[index] if index < len(self.tokens) else ("eof", "")

    def take(self, value: str | None = None, kind: str | None = None) -> str:
        tok_kind, tok_value = self.peek()
        if (value is not None and tok_value != value) or (kind is not None and tok_kind != kind):
            raise NuxtStateError(f"expected {value or kind}, got {tok_value!r} at token {self.pos}")
        self.pos += 1
        return tok_value

    def accept(self, value: str) -> bool:
        if self.peek()[1] == value and self.peek()[0] in ("punct", "name"):
            self.pos += 1
            return True
        return False

    # --- grammar
    def program(self) -> Any:
        # window.__NUXT__=(function(a,b,...){ statements return expr }(args));
        for expected in ("window", ".", "__NUXT__", "=", "(", "function", "("):
            self.take(expected)
        params = []
        while not self.accept(")"):
            params.append(self.take(kind="name"))
            self.accept(",")
        self.take("{")
        body_start = self.pos
        # Arguments come after the body; skip to them first, then come back.
        depth = 1
        while depth:
            kind, value = self.peek()
            if kind == "eof":
                raise NuxtStateError("unterminated function body")
            if kind == "punct" and value in "{[(":
                depth += 1
            elif kind == "punct" and value in "}])":
                depth -= 1
            self.pos += 1
        body_end = self.pos - 1  # index of the closing "}"
        self.take("(")
        args = []
        while not self.accept(")"):
            args.append(self.expr())
            self.accept(",")
        if len(args) > len(params):
            raise NuxtStateError("more arguments than parameters")
        self.scope = dict(zip(params, args + [None] * (len(params) - len(args)), strict=True))

        after_args = self.pos
        self.pos = body_start
        while self.peek()[1] != "return":
            self.statement()
        self.take("return")
        result = self.expr()
        self.accept(";")
        if self.pos != body_end:
            raise NuxtStateError("unexpected code after return")
        self.pos = after_args
        return result

    def statement(self) -> None:
        target = self.scope_ref(self.take(kind="name"))
        keys = [self.member()]
        while self.peek()[1] in (".", "["):
            target = _get(target, keys[-1])
            keys.append(self.member())
        self.take("=")
        _set(target, keys[-1], self.expr())
        self.take(";")

    def member(self) -> str | int:
        if self.accept("."):
            return self.take(kind="name")
        self.take("[")
        key = self.expr()
        self.take("]")
        return key

    def scope_ref(self, name: str) -> Any:
        if name not in self.scope:
            raise NuxtStateError(f"unknown identifier {name!r}")
        return self.scope[name]

    def expr(self) -> Any:
        kind, value = self.peek()
        if kind == "string":
            self.pos += 1
            return _unquote(value)
        if kind == "number":
            self.pos += 1
            number = float(value)
            return int(number) if number.is_integer() and "." not in value else number
        if value == "{":
            return self.object()
        if value == "[":
            return self.array()
        if kind == "name":
            self.pos += 1
            if value in _LITERALS:
                return _LITERALS[value]
            if value == "void":
                self.take("0")
                return None
            if value == "Array" and self.peek()[1] == "(":
                self.take("(")
                size = self.expr()
                self.take(")")
                if not isinstance(size, int) or not 0 <= size <= MAX_ARRAY:
                    raise NuxtStateError(f"bad Array size {size!r}")
                return [None] * size
            if value == "Object" and self.peek()[1] == ".":
                for expected in (".", "create", "(", "null", ")"):
                    self.take(expected)
                return {}
            if value == "new" and self.peek()[1] == "Date":
                self.pos += 1
                self.take("(")
                stamp = self.expr()
                self.take(")")
                return stamp
            return self.scope_ref(value)
        raise NuxtStateError(f"unsupported syntax {value!r} at token {self.pos}")

    def object(self) -> dict:
        self.take("{")
        result: dict[str, Any] = {}
        while not self.accept("}"):
            kind, key = self.peek()
            if kind not in ("name", "string", "number"):
                raise NuxtStateError(f"bad object key {key!r}")
            self.pos += 1
            key = _unquote(key) if kind == "string" else key
            self.take(":")
            result[key] = self.expr()
            self.accept(",")
        return result

    def array(self) -> list:
        self.take("[")
        result = []
        while not self.accept("]"):
            result.append(self.expr())
            self.accept(",")
        return result


def _get(target: Any, key: str | int) -> Any:
    try:
        return target[key]
    except (KeyError, IndexError, TypeError) as exc:
        raise NuxtStateError(f"cannot read {key!r}") from exc


def _set(target: Any, key: str | int, value: Any) -> None:
    try:
        target[key] = value
    except (IndexError, TypeError) as exc:
        raise NuxtStateError(f"cannot assign {key!r}") from exc


def extract_nuxt_state(html: str) -> Any:
    """The parsed ``window.__NUXT__`` of a page. Raises NuxtStateError."""
    start = html.find("window.__NUXT__")
    if start < 0:
        raise NuxtStateError("no __NUXT__ state on the page")
    end = html.find("</script>", start)
    source = html[start : end if end > 0 else None].strip()
    if len(source) > MAX_SOURCE:
        raise NuxtStateError("state is too large")
    try:
        return _Parser(_tokenize(source)).program()
    except NuxtStateError:
        raise
    except (ValueError, TypeError, IndexError, RecursionError) as exc:
        raise NuxtStateError(f"malformed state: {exc!r}") from exc
