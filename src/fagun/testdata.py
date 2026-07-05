"""Comprehensive, labelled test-data catalog for input/form fuzzing.

Every value is tagged with a *category* so results stay traceable — a finding
can always name the exact case that produced it (no fake / no guesswork):

- ``valid``       — well-formed values the field should accept.
- ``invalid``     — malformed values the field should reject.
- ``edge``        — legal but extreme (empty, min, max, whitespace, unicode).
- ``boundary``    — one step over a documented limit (off-by-one, length+1).
- ``outofbox``    — unexpected shapes: emoji, RTL, homoglyphs, null bytes,
                    scientific notation, leading zeros, format strings.
- ``injection``   — security payloads (XSS, SQLi, template, command, path…).
                    Used only to *observe reflection/handling* — never to attack
                    third parties.

Use :func:`cases_for` to get the right set for an input's ``type``/``name``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

CATEGORIES = ("valid", "invalid", "edge", "boundary", "outofbox", "injection")


@dataclass(frozen=True)
class TestCase:
    value: str
    category: str
    label: str  # human/traceable description, e.g. "email: missing @"
    expect: str = ""  # "accept" | "reject" | "" (observe only)


# --------------------------------------------------------------- shared payloads
# Non-destructive observation payloads. A unique marker lets us prove reflection.
XSS = [
    ('<script>fagunX()</script>', "XSS: script tag"),
    ('"><img src=x onerror=fagunX>', "XSS: img onerror breakout"),
    ("'><svg/onload=fagunX>", "XSS: svg onload"),
    ("javascript:fagunX//", "XSS: javascript URI"),
    ("{{7*7}}", "SSTI: mustache/jinja 7*7"),
    ("${7*7}", "SSTI: EL/JSP ${}"),
    ("#{7*7}", "SSTI: ruby/asp #{}"),
    ("<%= 7*7 %>", "SSTI: ERB"),
]
SQLI = [
    ("'", "SQLi: single quote"),
    ("' OR '1'='1", "SQLi: classic OR tautology"),
    ('" OR "1"="1', "SQLi: double-quote tautology"),
    ("1' ORDER BY 1--", "SQLi: order-by probe"),
    ("'; WAITFOR DELAY '0:0:0'--", "SQLi: time-based (0 delay, safe)"),
    ("1)) OR ((1=1", "SQLi: paren breakout"),
]
NOSQLI = [
    ('{"$gt":""}', "NoSQLi: $gt operator"),
    ("[$ne]=1", "NoSQLi: $ne array"),
]
CMDI = [
    ("; echo fagunCMD", "CMDi: semicolon chain"),
    ("| echo fagunCMD", "CMDi: pipe"),
    ("$(echo fagunCMD)", "CMDi: subshell"),
    ("`echo fagunCMD`", "CMDi: backtick"),
    ("&& echo fagunCMD", "CMDi: and-chain"),
]
PATH = [
    ("../../../../etc/passwd", "Path: unix traversal"),
    ("..\\..\\..\\windows\\win.ini", "Path: windows traversal"),
    ("%2e%2e%2f%2e%2e%2fetc%2fpasswd", "Path: url-encoded traversal"),
    ("file:///etc/passwd", "Path: file:// scheme"),
]
CRLF = [
    ("test%0d%0aSet-Cookie:fagun=1", "CRLF: header injection"),
    ("test\r\nX-Fagun: 1", "CRLF: raw newline"),
]
LDAP_XML = [
    ("*)(uid=*", "LDAPi: wildcard"),
    ("<?xml version='1.0'?><!DOCTYPE r [<!ENTITY x 'y'>]>", "XXE: doctype probe"),
]
INJECTION = XSS + SQLI + NOSQLI + CMDI + PATH + CRLF + LDAP_XML

# ------------------------------------------------------------------- edge values
_LONG = "A" * 5000
_UNICODE = "Ωðßüñ日本語한국어😀🚀"
_RTL = "‮abc"  # right-to-left override
_HOMOGLYPH = "аdmin"  # cyrillic 'а'
_WS_ONLY = "   \t  "
_NULL = "a\x00b"
_FMT = "%s%n%x%d {0} {{}}"
_EMOJI = "😀" * 50


def _generic(name: str) -> list[TestCase]:
    return [
        TestCase("", "edge", f"{name}: empty string", "reject"),
        TestCase(" ", "edge", f"{name}: single space"),
        TestCase(_WS_ONLY, "edge", f"{name}: whitespace only"),
        TestCase("normal input", "valid", f"{name}: plain text", "accept"),
        TestCase(_UNICODE, "outofbox", f"{name}: multilingual unicode"),
        TestCase(_EMOJI, "outofbox", f"{name}: emoji flood"),
        TestCase(_RTL, "outofbox", f"{name}: RTL override char"),
        TestCase(_HOMOGLYPH, "outofbox", f"{name}: cyrillic homoglyph"),
        TestCase(_NULL, "outofbox", f"{name}: embedded null byte"),
        TestCase(_FMT, "outofbox", f"{name}: format-string tokens"),
        TestCase(_LONG, "boundary", f"{name}: 5000-char overflow"),
        TestCase("a", "boundary", f"{name}: single char (min)"),
    ]


def _email() -> list[TestCase]:
    return [
        TestCase("user@example.com", "valid", "email: standard", "accept"),
        TestCase("first.last+tag@sub.example.co.uk", "valid", "email: tagged/subdomain", "accept"),
        TestCase("u@e.io", "edge", "email: shortest legal", "accept"),
        TestCase("plainaddress", "invalid", "email: missing @", "reject"),
        TestCase("@no-local.com", "invalid", "email: no local part", "reject"),
        TestCase("no-at-sign.com", "invalid", "email: no @", "reject"),
        TestCase("a@b", "invalid", "email: no TLD", "reject"),
        TestCase("spaces in@mail.com", "invalid", "email: space in local", "reject"),
        TestCase("two@@example.com", "invalid", "email: double @", "reject"),
        TestCase("a" * 250 + "@x.com", "boundary", "email: >254 chars", "reject"),
        TestCase('"><img src=x onerror=fagunX>@x.com', "injection", "email: XSS in local"),
        TestCase("user@example.com'--", "injection", "email: SQLi suffix"),
        TestCase("用户@例子.测试", "outofbox", "email: IDN unicode"),
    ]


def _number() -> list[TestCase]:
    return [
        TestCase("42", "valid", "number: positive int", "accept"),
        TestCase("0", "edge", "number: zero"),
        TestCase("-1", "edge", "number: negative"),
        TestCase("3.14159", "valid", "number: decimal", "accept"),
        TestCase("1e309", "outofbox", "number: overflow (Infinity)"),
        TestCase("-0", "outofbox", "number: negative zero"),
        TestCase("007", "outofbox", "number: leading zeros"),
        TestCase("1,000", "invalid", "number: thousands comma", "reject"),
        TestCase("NaN", "invalid", "number: NaN literal", "reject"),
        TestCase("abc", "invalid", "number: letters", "reject"),
        TestCase("9" * 400, "boundary", "number: 400-digit"),
        TestCase("2147483648", "boundary", "number: int32 max +1"),
        TestCase("0x1F", "outofbox", "number: hex literal"),
        TestCase("' OR 1=1--", "injection", "number: SQLi"),
    ]


def _tel() -> list[TestCase]:
    return [
        TestCase("+1 (555) 123-4567", "valid", "tel: US formatted", "accept"),
        TestCase("+8801712345678", "valid", "tel: BD international", "accept"),
        TestCase("5551234567", "valid", "tel: digits only", "accept"),
        TestCase("123", "edge", "tel: too short"),
        TestCase("phone", "invalid", "tel: letters", "reject"),
        TestCase("+" + "9" * 60, "boundary", "tel: 60-digit"),
        TestCase("555-CALL-NOW", "invalid", "tel: vanity letters", "reject"),
        TestCase("'; DROP TABLE--", "injection", "tel: SQLi"),
    ]


def _url() -> list[TestCase]:
    return [
        TestCase("https://example.com/path?q=1", "valid", "url: https", "accept"),
        TestCase("http://a.co", "valid", "url: http short", "accept"),
        TestCase("ftp://files.example.com", "edge", "url: ftp scheme"),
        TestCase("javascript:alert(1)", "injection", "url: javascript scheme"),
        TestCase("data:text/html,<script>fagunX</script>", "injection", "url: data URI XSS"),
        TestCase("//evil.example", "injection", "url: protocol-relative (open-redirect)"),
        TestCase("not a url", "invalid", "url: plain text", "reject"),
        TestCase("http://" + "a" * 3000 + ".com", "boundary", "url: 3000-char host"),
        TestCase("http://127.0.0.1:22/", "outofbox", "url: SSRF localhost:22"),
        TestCase("http://169.254.169.254/", "outofbox", "url: SSRF cloud metadata"),
    ]


def _date() -> list[TestCase]:
    return [
        TestCase("2024-02-29", "valid", "date: valid leap day", "accept"),
        TestCase("2023-02-29", "invalid", "date: non-leap Feb 29", "reject"),
        TestCase("2024-13-01", "invalid", "date: month 13", "reject"),
        TestCase("2024-00-10", "invalid", "date: month 00", "reject"),
        TestCase("0000-01-01", "edge", "date: year 0"),
        TestCase("9999-12-31", "boundary", "date: max year"),
        TestCase("2024-04-31", "invalid", "date: April 31", "reject"),
        TestCase("31/12/2024", "outofbox", "date: DD/MM/YYYY format"),
    ]


def _password() -> list[TestCase]:
    return [
        TestCase("Str0ng!Passw0rd#2024", "valid", "pw: strong", "accept"),
        TestCase("123456", "invalid", "pw: top-breached", "reject"),
        TestCase("password", "invalid", "pw: dictionary word", "reject"),
        TestCase("a", "edge", "pw: 1 char"),
        TestCase("A1!", "boundary", "pw: 3 chars"),
        TestCase(" " * 8, "edge", "pw: spaces only"),
        TestCase("P@ss" + "w" * 5000, "boundary", "pw: 5000-char"),
        TestCase(_UNICODE + "1!", "outofbox", "pw: unicode"),
        TestCase("' OR '1'='1", "injection", "pw: SQLi auth-bypass string"),
    ]


def _select(name: str = "select") -> list[TestCase]:
    """Option-tampering cases for <select> elements."""
    return [
        TestCase("", "edge", f"{name}: empty value"),
        TestCase("0", "boundary", f"{name}: numeric zero (often invalid option)"),
        TestCase("-1", "boundary", f"{name}: negative (sentinel)"),
        TestCase("99999", "boundary", f"{name}: out-of-range id"),
        TestCase("' OR '1'='1", "injection", f"{name}: SQLi option tamper"),
        TestCase("<script>fagunX()</script>", "injection", f"{name}: XSS option tamper"),
        TestCase("../admin", "injection", f"{name}: path option tamper"),
        TestCase(_LONG[:50], "outofbox", f"{name}: long option value"),
        TestCase(_UNICODE, "outofbox", f"{name}: unicode option"),
    ]


def _checkbox(name: str = "checkbox") -> list[TestCase]:
    """Checkbox/radio value cases — tests both on/off and unexpected values."""
    return [
        TestCase("true", "valid", f"{name}: true"),
        TestCase("false", "edge", f"{name}: false"),
        TestCase("1", "valid", f"{name}: 1"),
        TestCase("0", "edge", f"{name}: 0"),
        TestCase("on", "valid", f"{name}: on"),
        TestCase("off", "edge", f"{name}: off"),
        TestCase("yes", "outofbox", f"{name}: yes string"),
        TestCase("' OR '1'='1", "injection", f"{name}: SQLi"),
    ]


_FIELD_BUILDERS = {
    "email": _email,
    "number": _number,
    "range": _number,
    "tel": _tel,
    "url": _url,
    "date": _date,
    "datetime-local": _date,
    "month": _date,
    "password": _password,
    "select-one": _select,
    "select-multiple": _select,
    "checkbox": _checkbox,
    "radio": _checkbox,
}


def cases_for(field_type: str, name: str = "", include: Iterable[str] = CATEGORIES) -> list[TestCase]:
    """Return the labelled test cases appropriate for an input field.

    ``field_type`` is the HTML input ``type``; ``name`` refines heuristics
    (e.g. a text field named "email"). ``include`` filters by category.
    """
    ft = (field_type or "text").lower()
    nm = (name or "").lower()
    # Normalise browser-reported types for select elements
    if ft in ("select", "select-one", "select-multiple"):
        ft = "select-one"
    builder = _FIELD_BUILDERS.get(ft)
    if builder is None:
        # Heuristic: infer intent from the field name for generic text inputs.
        for kw, b in (("email", _email), ("mail", _email), ("phone", _tel),
                      ("tel", _tel), ("url", _url), ("website", _url),
                      ("date", _date), ("dob", _date), ("pass", _password),
                      ("amount", _number), ("qty", _number), ("age", _number)):
            if kw in nm:
                builder = b
                break
    base = builder() if builder else _generic(ft)
    # Every field also gets the injection battery (observe-only) unless excluded.
    inj = [TestCase(v, "injection", lbl) for v, lbl in INJECTION]
    all_cases = base + inj
    inc = set(include)
    return [c for c in all_cases if c.category in inc]


def summary() -> dict[str, int]:
    """Count of built-in cases per category across all field types (for docs/tests)."""
    counts = {c: 0 for c in CATEGORIES}
    for b in list(_FIELD_BUILDERS.values()) + [lambda: _generic("text")]:
        for c in b():
            counts[c.category] = counts.get(c.category, 0) + 1
    counts["injection"] += len(INJECTION)
    return counts
