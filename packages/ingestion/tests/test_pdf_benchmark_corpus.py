from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from json import loads
from pathlib import Path
from re import DOTALL, finditer, search
from subprocess import run
from sys import executable
from typing import Any
from zlib import compress, decompress, decompressobj

import pytest

ROOT = Path(__file__).parents[3]
CORPUS = ROOT / "packages/ingestion/benchmarks/pdf"
MANIFEST = CORPUS / "manifest.json"
GENERATOR = ROOT / "script/build_pdf_benchmark_fixtures.py"

EXPECTED_PARTITIONS = {"development", "calibration", "validation", "adversarial"}
EXPECTED_FAMILIES = {
    "audit",
    "governance",
    "legal_regulatory",
    "market_report",
    "technical_paper",
    "tokenomics",
    "whitepaper",
}
EXPECTED_FEATURES = {
    "active_javascript",
    "attachment",
    "decompression_boundary",
    "encrypted",
    "figure_caption",
    "image_only",
    "long_document",
    "malformed_trailer",
    "mixed_font",
    "multi_column",
    "over_page_limit",
    "parser_disagreement",
    "rotated_crop_box",
    "single_column",
    "table",
    "uri_action",
}
ALLOWED_ROUTES = {"accept", "awaiting_password", "reject", "review"}
TOKEN_CATEGORIES = {
    "bitcoin_identifiers",
    "currencies",
    "dates",
    "evm_addresses",
    "finding_ids",
    "percentages",
    "solana_addresses",
    "symbols",
}
URI_SCHEME_PATTERN = rb"[A-Za-z][A-Za-z0-9+.-]*:[^\x00-\x20<>()\[\]{}'\"]+"


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return loads(MANIFEST.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class _PDFName(str):
    pass


@dataclass(frozen=True)
class _PDFReference:
    object_number: int
    generation: int


@dataclass(frozen=True)
class _PDFStream:
    reference: _PDFReference | None
    dictionary: dict[str, object]
    payload: bytes
    direct_length: bool


@dataclass(frozen=True)
class _PDFIndirectObject:
    reference: _PDFReference
    value: object


def _decode_pdf_text(raw: bytes) -> str:
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le")
    return raw.decode("latin-1")


def _decode_bounded_stream(stream: _PDFStream) -> bytes:
    if not stream.direct_length:
        raise ValueError("designated stream must have a direct bounded Length")
    if len(stream.payload) > 1_048_576:
        raise ValueError("designated compressed stream exceeds byte limit")
    filters = stream.dictionary.get("Filter")
    if filters is None:
        decoded = stream.payload
    elif filters == _PDFName("FlateDecode") or filters == [_PDFName("FlateDecode")]:
        maximum_output = min(1_048_576, len(stream.payload) * 1_000)
        decoder = decompressobj()
        decoded = decoder.decompress(stream.payload, maximum_output + 1)
        if len(decoded) > maximum_output or decoder.unconsumed_tail:
            raise ValueError("designated stream exceeds decoded-byte or ratio limit")
        if not decoder.eof:
            raise ValueError("designated Flate stream is incomplete")
        if decoder.unused_data:
            raise ValueError("designated Flate stream has concatenated trailing data")
    else:
        raise ValueError("unsupported designated-stream filter")
    if len(decoded) > 1_048_576:
        raise ValueError("designated decoded stream exceeds byte limit")
    return decoded


class _PDFParser:
    """Small grammar-aware corpus auditor; it never renders or executes PDF content."""

    _WHITESPACE = b"\x00\t\n\x0c\r "
    _DELIMITERS = b"()<>[]{}/%"

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.cursor = 0
        self.buffer: list[tuple[str, object]] = []

    def _skip_space_and_comments(self) -> None:
        while self.cursor < len(self.payload):
            if self.payload[self.cursor] in self._WHITESPACE:
                self.cursor += 1
            elif self.payload[self.cursor] == ord("%"):
                while self.cursor < len(self.payload) and self.payload[self.cursor] not in b"\r\n":
                    self.cursor += 1
            else:
                return

    def _literal_string(self) -> str:
        self.cursor += 1
        depth = 1
        decoded = bytearray()
        while self.cursor < len(self.payload) and depth:
            byte = self.payload[self.cursor]
            self.cursor += 1
            if byte == ord("\\") and self.cursor < len(self.payload):
                escaped = self.payload[self.cursor]
                self.cursor += 1
                if escaped in b"nrtbf":
                    decoded.extend(
                        {
                            ord("n"): b"\n",
                            ord("r"): b"\r",
                            ord("t"): b"\t",
                            ord("b"): b"\b",
                            ord("f"): b"\f",
                        }[escaped]
                    )
                elif ord("0") <= escaped <= ord("7"):
                    digits = bytearray((escaped,))
                    while (
                        len(digits) < 3
                        and self.cursor < len(self.payload)
                        and ord("0") <= self.payload[self.cursor] <= ord("7")
                    ):
                        digits.append(self.payload[self.cursor])
                        self.cursor += 1
                    decoded.append(int(digits, 8))
                elif escaped not in b"\r\n":
                    decoded.append(escaped)
                elif (
                    escaped == ord("\r")
                    and self.cursor < len(self.payload)
                    and self.payload[self.cursor] == ord("\n")
                ):
                    self.cursor += 1
            elif byte == ord("("):
                depth += 1
                decoded.append(byte)
            elif byte == ord(")"):
                depth -= 1
                if depth:
                    decoded.append(byte)
            else:
                decoded.append(byte)
        if depth:
            raise ValueError("unterminated PDF literal string")
        return _decode_pdf_text(bytes(decoded))

    def _hex_string(self) -> str:
        self.cursor += 1
        start = self.cursor
        while self.cursor < len(self.payload) and self.payload[self.cursor] != ord(">"):
            self.cursor += 1
        if self.cursor >= len(self.payload):
            raise ValueError("unterminated PDF hexadecimal string")
        compact = b"".join(self.payload[start : self.cursor].split())
        self.cursor += 1
        if len(compact) % 2:
            compact += b"0"
        return _decode_pdf_text(bytes.fromhex(compact.decode("ascii")))

    def _name(self) -> _PDFName:
        self.cursor += 1
        raw = bytearray()
        while (
            self.cursor < len(self.payload)
            and self.payload[self.cursor] not in self._WHITESPACE + self._DELIMITERS
        ):
            if self.payload[self.cursor] == ord("#") and self.cursor + 2 < len(self.payload):
                escaped = self.payload[self.cursor + 1 : self.cursor + 3]
                try:
                    raw.append(int(escaped, 16))
                except ValueError:
                    raw.append(self.payload[self.cursor])
                    self.cursor += 1
                else:
                    self.cursor += 3
            else:
                raw.append(self.payload[self.cursor])
                self.cursor += 1
        return _PDFName(raw.decode("latin-1"))

    def _lex(self) -> tuple[str, object] | None:
        self._skip_space_and_comments()
        if self.cursor >= len(self.payload):
            return None
        if self.payload.startswith(b"<<", self.cursor):
            self.cursor += 2
            return ("dict_start", "<<")
        if self.payload.startswith(b">>", self.cursor):
            self.cursor += 2
            return ("dict_end", ">>")
        byte = self.payload[self.cursor]
        if byte == ord("["):
            self.cursor += 1
            return ("array_start", "[")
        if byte == ord("]"):
            self.cursor += 1
            return ("array_end", "]")
        if byte == ord("("):
            return ("string", self._literal_string())
        if byte == ord("<"):
            return ("string", self._hex_string())
        if byte == ord("/"):
            return ("name", self._name())
        start = self.cursor
        while (
            self.cursor < len(self.payload)
            and self.payload[self.cursor] not in self._WHITESPACE + self._DELIMITERS
        ):
            self.cursor += 1
        if start == self.cursor:
            self.cursor += 1
            return ("delimiter", chr(byte))
        raw = self.payload[start : self.cursor]
        try:
            return ("number", int(raw))
        except ValueError:
            try:
                return ("number", float(raw))
            except ValueError:
                return ("keyword", raw.decode("latin-1"))

    def _peek(self, offset: int = 0) -> tuple[str, object] | None:
        while len(self.buffer) <= offset:
            token = self._lex()
            if token is None:
                return None
            self.buffer.append(token)
        return self.buffer[offset]

    def _take(self) -> tuple[str, object] | None:
        token = self._peek()
        return self.buffer.pop(0) if token is not None else None

    def _value(self) -> object:
        token = self._take()
        if token is None:
            raise ValueError("unexpected end of PDF object")
        kind, value = token
        if kind == "dict_start":
            result: dict[str, object] = {}
            while self._peek() != ("dict_end", ">>"):
                key = self._take()
                if key is None or key[0] != "name":
                    raise ValueError("PDF dictionary key is not a name")
                key_name = str(key[1])
                if key_name in result:
                    raise ValueError(f"duplicate PDF dictionary key: {key_name}")
                result[key_name] = self._value()
            self._take()
            return result
        if kind == "array_start":
            result_list = []
            while self._peek() != ("array_end", "]"):
                result_list.append(self._value())
            self._take()
            return result_list
        if kind == "number" and isinstance(value, int):
            generation = self._peek()
            reference = self._peek(1)
            if (
                generation is not None
                and generation[0] == "number"
                and isinstance(generation[1], int)
                and reference == ("keyword", "R")
            ):
                self._take()
                self._take()
                return _PDFReference(value, generation[1])
        return value

    def parse_all(self) -> list[object]:
        values: list[object] = []
        last_dictionary: dict[str, object] | None = None
        current_reference: _PDFReference | None = None
        current_value: object | None = None
        while self._peek() is not None:
            if self._peek() == ("keyword", "stream"):
                self._take()
                if self.buffer:
                    raise ValueError("unexpected buffered token before PDF stream")
                if self.payload.startswith(b"\r\n", self.cursor):
                    self.cursor += 2
                elif self.cursor < len(self.payload) and self.payload[self.cursor] in b"\r\n":
                    self.cursor += 1
                length = last_dictionary.get("Length") if last_dictionary else None
                if isinstance(length, int):
                    stream_payload = self.payload[self.cursor : self.cursor + length]
                    self.cursor += length
                else:
                    end = self.payload.find(b"endstream", self.cursor)
                    if end < 0:
                        raise ValueError("unterminated PDF stream")
                    stream_payload = self.payload[self.cursor : end].rstrip(b"\r\n")
                    self.cursor = end
                if last_dictionary is None:
                    raise ValueError("PDF stream has no dictionary")
                stream = _PDFStream(
                    reference=current_reference,
                    dictionary=last_dictionary,
                    payload=stream_payload,
                    direct_length=isinstance(length, int),
                )
                values.append(stream)
                current_value = stream
                if last_dictionary.get("Type") == _PDFName("ObjStm"):
                    decoded = _decode_bounded_stream(stream)
                    count = last_dictionary.get("N")
                    first = last_dictionary.get("First")
                    if not isinstance(count, int) or not isinstance(first, int):
                        raise ValueError("object stream requires direct N and First")
                    header = _PDFParser(decoded[:first]).parse_all()
                    if len(header) != count * 2 or not all(
                        isinstance(item, int) for item in header
                    ):
                        raise ValueError("malformed object-stream index")
                    numbers = [int(item) for item in header]
                    for index in range(count):
                        object_number = numbers[index * 2]
                        offset = numbers[index * 2 + 1]
                        next_offset = (
                            numbers[(index + 1) * 2 + 1]
                            if index + 1 < count
                            else len(decoded) - first
                        )
                        embedded_values = _PDFParser(
                            decoded[first + offset : first + next_offset]
                        ).parse_all()
                        if len(embedded_values) != 1:
                            raise ValueError("object stream entry must contain one object")
                        values.append(
                            _PDFIndirectObject(_PDFReference(object_number, 0), embedded_values[0])
                        )
                continue
            value = self._value()
            values.append(value)
            if isinstance(value, dict):
                last_dictionary = value
            if value == "obj" and len(values) >= 3:
                object_number, generation = values[-3:-1]
                if not isinstance(object_number, int) or not isinstance(generation, int):
                    raise ValueError("malformed indirect-object header")
                current_reference = _PDFReference(object_number, generation)
                current_value = None
            elif value == "endobj":
                if current_reference is None or current_value is None:
                    raise ValueError("malformed indirect-object terminator")
                values.append(_PDFIndirectObject(current_reference, current_value))
                current_reference = None
                current_value = None
            elif current_reference is not None and value != "endstream":
                current_value = value
        return values


def _walk_pdf_values(values: list[object]) -> tuple[list[dict[str, object]], list[str]]:
    dictionaries: list[dict[str, object]] = []
    strings: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, _PDFIndirectObject):
            visit(value.value)
        elif isinstance(value, dict):
            dictionaries.append(value)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)
        elif isinstance(value, str) and not isinstance(value, _PDFName):
            strings.append(value)

    for value in values:
        visit(value)
    return dictionaries, strings


def _indirect_objects(values: list[object]) -> dict[_PDFReference, object]:
    objects: dict[_PDFReference, object] = {}
    for value in values:
        if isinstance(value, _PDFIndirectObject):
            if value.reference in objects:
                raise ValueError(f"duplicate indirect PDF object: {value.reference}")
            objects[value.reference] = value.value
    return objects


def _target(value: object) -> str:
    if isinstance(value, _PDFReference):
        return f"indirect:{value.object_number}:{value.generation}"
    if isinstance(value, _PDFName):
        return f"/{value}"
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return _target(value[0])
    return "unresolved"


def _resource_kind(locator: str) -> str | None:
    if locator.startswith(("indirect:", "inline:")):
        return None
    if locator.startswith("\\\\"):
        return "unc"
    if search(URI_SCHEME_PATTERN, locator.encode("utf-8")):
        return "uri"
    return None


def _collect_text_resources(value: str, resources: set[tuple[str, str]]) -> None:
    encoded = value.encode("utf-8")
    for match in finditer(URI_SCHEME_PATTERN, encoded):
        resources.add(("uri", match.group().decode("utf-8")))
    for match in finditer(rb"\\\\[^\x00-\x20<>()\[\]{}'\"]+", encoded):
        resources.add(("unc", match.group().decode("utf-8")))


def _structural_inventory(payload: bytes) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    values = _PDFParser(payload).parse_all()
    dictionaries, strings = _walk_pdf_values(values)
    indirect_objects = _indirect_objects(values)
    capabilities: set[tuple[str, str, str]] = set()
    resources: set[tuple[str, str]] = set()
    encrypted = any("Encrypt" in dictionary for dictionary in dictionaries)

    for value in strings:
        _collect_text_resources(value, resources)

    def resolve(value: object) -> object:
        if isinstance(value, _PDFReference):
            if value not in indirect_objects:
                raise ValueError(f"unresolved designated PDF reference: {value}")
            return indirect_objects[value]
        return value

    def inspect_stream(value: object) -> None:
        resolved = resolve(value)
        if not isinstance(resolved, _PDFStream):
            raise ValueError("designated PDF stream reference did not resolve to a stream")
        if encrypted:
            raise ValueError("encrypted designated stream cannot be audited without decryption")
        _collect_text_resources(_decode_pdf_text(_decode_bounded_stream(resolved)), resources)

    for dictionary in dictionaries:
        action_type = dictionary.get("S")
        if isinstance(action_type, _PDFName):
            if action_type == _PDFName("JavaScript"):
                javascript = dictionary.get("JS")
                if isinstance(javascript, str) and not isinstance(javascript, _PDFName):
                    target = "inline:test-fixture"
                    _collect_text_resources(javascript, resources)
                elif isinstance(javascript, _PDFReference):
                    target = _target(javascript)
                    inspect_stream(javascript)
                else:
                    raise ValueError("JavaScript action requires an auditable string or stream")
            else:
                target_value = next(
                    (
                        dictionary[key]
                        for key in ("URI", "F", "UF", "D", "R", "N")
                        if key in dictionary
                    ),
                    None,
                )
                resolved_target = (
                    resolve(target_value)
                    if isinstance(target_value, _PDFReference)
                    and action_type != _PDFName("Rendition")
                    else target_value
                )
                if isinstance(resolved_target, dict):
                    target = _target(resolved_target.get("UF", resolved_target.get("F")))
                elif isinstance(resolved_target, _PDFStream):
                    target = _target(target_value)
                    inspect_stream(target_value)
                else:
                    target = _target(resolved_target)
            capabilities.add(("action", target, str(action_type)))
            kind = None if action_type == _PDFName("JavaScript") else _resource_kind(target)
            if kind is not None:
                resources.add((kind, target))
            elif target != "unresolved" and action_type not in {
                _PDFName("JavaScript"),
                _PDFName("Rendition"),
            }:
                resources.add(("file_spec", target))

        is_filespec = dictionary.get("Type") == _PDFName("Filespec") or (
            "S" not in dictionary
            and isinstance(dictionary.get("UF", dictionary.get("F")), str)
            and not isinstance(dictionary.get("UF", dictionary.get("F")), _PDFName)
        )
        if is_filespec:
            file_value = dictionary.get("UF", dictionary.get("F"))
            resolved_file = (
                resolve(file_value) if isinstance(file_value, _PDFReference) else file_value
            )
            if isinstance(resolved_file, _PDFStream):
                target = _target(file_value)
                inspect_stream(file_value)
            else:
                target = _target(resolved_file)
            if "EF" in dictionary:
                capabilities.add(("embedded_file", target, "Filespec"))
                embedded_files = resolve(dictionary["EF"])
                if not isinstance(embedded_files, dict):
                    raise ValueError("embedded-file map is not a dictionary")
                stream_references = [
                    embedded_files[key] for key in ("F", "UF") if key in embedded_files
                ]
                if not stream_references:
                    raise ValueError("embedded-file map has no stream reference")
                for stream_reference in stream_references:
                    inspect_stream(stream_reference)
            else:
                capabilities.add(("external_file_spec", target, "Filespec"))
                resources.add(("file_spec", target))

    return [
        {"kind": kind, "target": target, "type": capability_type}
        for kind, target, capability_type in sorted(capabilities)
    ], [{"kind": kind, "locator": locator} for kind, locator in sorted(resources)]


@pytest.mark.parametrize(
    ("payload", "expected_capability", "expected_resource"),
    [
        (
            b"<< /S /URI /URI <6d61696c746f3a726576696577406578616d706c652e696e76616c6964> >>",
            {"kind": "action", "target": "mailto:review@example.invalid", "type": "URI"},
            {"kind": "uri", "locator": "mailto:review@example.invalid"},
        ),
        (
            rb"<< /S /Launch /F (\\\\server\\share\\payload.pdf) >>",
            {"kind": "action", "target": r"\\server\share\payload.pdf", "type": "Launch"},
            {"kind": "unc", "locator": r"\\server\share\payload.pdf"},
        ),
        (
            b"<< /S /GoToR /F (ftp://example.invalid/payload.pdf) >>",
            {"kind": "action", "target": "ftp://example.invalid/payload.pdf", "type": "GoToR"},
            {"kind": "uri", "locator": "ftp://example.invalid/payload.pdf"},
        ),
        (
            b"<< /S /SubmitForm /F (atlas+local:payload) >>",
            {"kind": "action", "target": "atlas+local:payload", "type": "SubmitForm"},
            {"kind": "uri", "locator": "atlas+local:payload"},
        ),
        (
            rb"<< /S /ImportData /F (file\072///tmp/payload.fdf) >>",
            {"kind": "action", "target": "file:///tmp/payload.fdf", "type": "ImportData"},
            {"kind": "uri", "locator": "file:///tmp/payload.fdf"},
        ),
        (
            b"<< /Type /Filespec /F <7061796c6f61642e706466> >>",
            {"kind": "external_file_spec", "target": "payload.pdf", "type": "Filespec"},
            {"kind": "file_spec", "locator": "payload.pdf"},
        ),
        (
            b"<< /S /Rendition /R 1 0 R >>",
            {"kind": "action", "target": "indirect:1:0", "type": "Rendition"},
            None,
        ),
        (
            b"<< /S%comment\n/Launch /F (relative.pdf) >>",
            {"kind": "action", "target": "relative.pdf", "type": "Launch"},
            {"kind": "file_spec", "locator": "relative.pdf"},
        ),
        (
            b"<< /S /Lau#6ech /F (escaped-name.pdf) >>",
            {"kind": "action", "target": "escaped-name.pdf", "type": "Launch"},
            {"kind": "file_spec", "locator": "escaped-name.pdf"},
        ),
        (
            b"<< /Type\n/Filespec /F (newline.pdf) >>",
            {"kind": "external_file_spec", "target": "newline.pdf", "type": "Filespec"},
            {"kind": "file_spec", "locator": "newline.pdf"},
        ),
        (
            b"<< /F (optional-type.pdf) >>",
            {"kind": "external_file_spec", "target": "optional-type.pdf", "type": "Filespec"},
            {"kind": "file_spec", "locator": "optional-type.pdf"},
        ),
        (
            b"<< /S /URI /URI "
            b"<feff00680074007400700073003a002f002f006500780061006d0070006c0065002e0069006e"
            b"00760061006c00690064002f00750074006600310036> >>",
            {"kind": "action", "target": "https://example.invalid/utf16", "type": "URI"},
            {"kind": "uri", "locator": "https://example.invalid/utf16"},
        ),
    ],
)
def test_structural_inventory_decodes_actions_file_specs_and_locators(
    payload: bytes,
    expected_capability: dict[str, str],
    expected_resource: dict[str, str] | None,
) -> None:
    expected_resources = [] if expected_resource is None else [expected_resource]
    assert _structural_inventory(payload) == ([expected_capability], expected_resources)


def test_structural_inventory_walks_flate_encoded_object_streams() -> None:
    embedded = b"7 0 << /S /Launch /F (object-stream.pdf) >>"
    compressed = compress(embedded, level=9)
    for filter_syntax in (b"/FlateDecode", b"[/FlateDecode]"):
        payload = (
            b"1 0 obj\n<< /Type /ObjStm /N 1 /First 4 /Filter "
            + filter_syntax
            + b" /Length "
            + str(len(compressed)).encode("ascii")
            + b" >>\nstream\n"
            + compressed
            + b"\nendstream\nendobj\n"
        )
        assert _structural_inventory(payload) == (
            [{"kind": "action", "target": "object-stream.pdf", "type": "Launch"}],
            [{"kind": "file_spec", "locator": "object-stream.pdf"}],
        )


def _javascript_stream_document(stream_payload: bytes, *, flate: bool = True) -> bytes:
    filter_entry = b"/Filter /FlateDecode " if flate else b""
    return (
        b"1 0 obj\n<< /S /JavaScript /JS 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< "
        + filter_entry
        + b"/Length "
        + str(len(stream_payload)).encode("ascii")
        + b" >>\nstream\n"
        + stream_payload
        + b"\nendstream\nendobj\n"
    )


@pytest.mark.parametrize("compressed", [False, True])
def test_structural_inventory_resolves_indirect_javascript_streams(compressed: bool) -> None:
    script = b"fetch('https://hidden.invalid/x')"
    stream_payload = compress(script, level=9) if compressed else script
    payload = _javascript_stream_document(stream_payload, flate=compressed)
    assert _structural_inventory(payload) == (
        [{"kind": "action", "target": "indirect:2:0", "type": "JavaScript"}],
        [{"kind": "uri", "locator": "https://hidden.invalid/x"}],
    )


def test_structural_inventory_fails_closed_on_unauditable_javascript_streams() -> None:
    script = b"https://hidden.invalid/x"
    indirect_length = (
        b"1 0 obj\n<< /S /JavaScript /JS 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Length 3 0 R >>\nstream\n"
        + script
        + b"\nendstream\nendobj\n3 0 obj\n"
        + str(len(script)).encode("ascii")
        + b"\nendobj\n"
    )
    with pytest.raises(ValueError, match="direct bounded Length"):
        _structural_inventory(indirect_length)

    unsupported_filter = (
        b"1 0 obj\n<< /S /JavaScript /JS 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Filter /LZWDecode /Length "
        + str(len(script)).encode("ascii")
        + b" >>\nstream\n"
        + script
        + b"\nendstream\nendobj\n"
    )
    with pytest.raises(ValueError, match="unsupported designated-stream filter"):
        _structural_inventory(unsupported_filter)

    encrypted = (
        b"1 0 obj\n<< /S /JavaScript /JS 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Length "
        + str(len(script)).encode("ascii")
        + b" >>\nstream\n"
        + script
        + b"\nendstream\nendobj\ntrailer\n<< /Encrypt 9 0 R >>\n"
    )
    with pytest.raises(ValueError, match="encrypted designated stream"):
        _structural_inventory(encrypted)


def test_structural_inventory_bounds_flate_output_before_materializing_it() -> None:
    oversized = compress(b"A" * 1_048_577, level=9)
    with pytest.raises(ValueError, match="decoded-byte or ratio limit"):
        _structural_inventory(_javascript_stream_document(oversized))

    complete = compress(b"https://hidden.invalid/x", level=9)
    with pytest.raises(ValueError, match="incomplete"):
        _structural_inventory(_javascript_stream_document(complete[:-2]))
    with pytest.raises(ValueError, match="concatenated trailing data"):
        _structural_inventory(_javascript_stream_document(complete + compress(b"extra")))


def test_structural_inventory_inspects_embedded_file_streams() -> None:
    attachment = b"source=https://attachment.invalid/payload"
    payload = (
        b"1 0 obj\n<< /Type /EmbeddedFile /Length "
        + str(len(attachment)).encode("ascii")
        + b" >>\nstream\n"
        + attachment
        + b"\nendstream\nendobj\n"
        b"2 0 obj\n<< /Type /Filespec /F (payload.txt) /EF << /F 1 0 R >> >>\nendobj\n"
    )
    assert _structural_inventory(payload) == (
        [{"kind": "embedded_file", "target": "payload.txt", "type": "Filespec"}],
        [{"kind": "uri", "locator": "https://attachment.invalid/payload"}],
    )


def test_structural_inventory_fails_closed_on_ambiguous_security_objects() -> None:
    with pytest.raises(ValueError, match="duplicate PDF dictionary key"):
        _structural_inventory(b"<< /S /URI /S /JavaScript /URI (https://example.invalid) >>")

    compressed = compress(b"7 0 << /S /Launch /F (hidden.pdf) >>", level=9)
    unsupported = (
        b"1 0 obj\n<< /Type /ObjStm /N 1 /First 4 /Filter /UnknownDecode /Length "
        + str(len(compressed)).encode("ascii")
        + b" >>\nstream\n"
        + compressed
        + b"\nendstream\nendobj\n"
    )
    with pytest.raises(ValueError, match="unsupported designated-stream filter"):
        _structural_inventory(unsupported)


def test_manifest_has_exact_versioned_top_level_contract(manifest: dict[str, Any]) -> None:
    assert set(manifest) == {
        "candidates",
        "fixtures",
        "performance_protocol",
        "qualification",
        "schema_version",
    }
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["qualification"] == {
        "production": "blocked_sealed_holdout_missing",
        "tier0_development": "unqualified",
        "tier1_development": "unqualified",
    }


def test_manifest_freezes_all_partitions_families_and_required_features(
    manifest: dict[str, Any],
) -> None:
    fixtures = manifest["fixtures"]
    assert {fixture["partition"] for fixture in fixtures} == EXPECTED_PARTITIONS
    assert {fixture["document_family"] for fixture in fixtures} >= EXPECTED_FAMILIES
    observed_features = {feature for fixture in fixtures for feature in fixture["features"]}
    assert observed_features >= EXPECTED_FEATURES

    names = [fixture["fixture"] for fixture in fixtures]
    assert len(names) == len(set(names))
    assert names == sorted(names)


def test_every_fixture_and_golden_is_pinned_licensed_and_bounded(
    manifest: dict[str, Any],
) -> None:
    for fixture in manifest["fixtures"]:
        assert set(fixture) == {
            "declared_external_resources",
            "declared_pdf_capabilities",
            "document_family",
            "expected_page_count",
            "expected_preflight_route",
            "features",
            "fixture",
            "golden",
            "golden_sha256",
            "license",
            "maximum_fixture_bytes",
            "partition",
            "provenance",
            "resource_limits",
            "sha256",
            "size_bytes",
        }
        assert fixture["partition"] in EXPECTED_PARTITIONS
        assert fixture["expected_preflight_route"] in ALLOWED_ROUTES
        assert fixture["license"] in {"CC0-1.0", "LicenseRef-RSI-Atlas-Test-Fixture"}
        assert fixture["provenance"].startswith("deterministic-local-generator:")
        assert fixture["maximum_fixture_bytes"] <= 8_388_608
        assert fixture["declared_external_resources"] == sorted(
            fixture["declared_external_resources"], key=lambda item: (item["kind"], item["locator"])
        )
        assert fixture["declared_pdf_capabilities"] == sorted(
            fixture["declared_pdf_capabilities"],
            key=lambda item: (item["kind"], item["target"], item["type"]),
        )

        pdf = CORPUS / "fixtures" / fixture["fixture"]
        golden = CORPUS / "golden" / fixture["golden"]
        assert pdf.is_file()
        assert golden.is_file()
        assert pdf.read_bytes().startswith(b"%PDF-")
        assert pdf.stat().st_size == fixture["size_bytes"]
        assert 0 < pdf.stat().st_size <= fixture["maximum_fixture_bytes"]
        assert _sha256(pdf) == fixture["sha256"]
        assert _sha256(golden) == fixture["golden_sha256"]


def test_goldens_freeze_page_text_region_token_and_route_evidence(
    manifest: dict[str, Any],
) -> None:
    for fixture in manifest["fixtures"]:
        golden_path = CORPUS / "golden" / fixture["golden"]
        golden = loads(golden_path.read_text(encoding="utf-8"))
        assert set(golden) == {
            "bounding_region_semantics",
            "expected_bounding_regions",
            "expected_page_count",
            "expected_preflight_route",
            "expected_raw_strings",
            "expected_tokens",
            "fixture",
            "schema_version",
        }
        assert golden["schema_version"] == "1.0.0"
        assert golden["fixture"] == fixture["fixture"]
        assert golden["expected_page_count"] == fixture["expected_page_count"]
        assert golden["expected_preflight_route"] == fixture["expected_preflight_route"]
        assert golden["bounding_region_semantics"] == {
            "coordinate_system": "pdf_bottom_left_points",
            "relation": "observed_glyph_box_must_be_contained",
            "tolerance_points": "1.000000",
        }
        assert golden["expected_raw_strings"] == sorted(set(golden["expected_raw_strings"]))
        assert set(golden["expected_tokens"]) == TOKEN_CATEGORIES
        for values in golden["expected_tokens"].values():
            assert values == sorted(set(values))
            for value in values:
                assert any(value in raw_string for raw_string in golden["expected_raw_strings"])

        page_count = golden["expected_page_count"]
        for region in golden["expected_bounding_regions"]:
            assert set(region) == {"bottom", "left", "page", "right", "text", "top"}
            assert page_count is not None
            assert 1 <= region["page"] <= page_count
            coordinates = [DecimalString(region[key]) for key in ("left", "bottom", "right", "top")]
            assert coordinates[0] < coordinates[2]
            assert coordinates[1] < coordinates[3]

    technical = loads(
        (CORPUS / "golden/crypto_technical_three_page.json").read_text(encoding="utf-8")
    )["expected_tokens"]
    assert technical["evm_addresses"] == ["0x1111111111111111111111111111111111111111"]
    assert technical["solana_addresses"] == ["11111111111111111111111111111111"]
    assert technical["bitcoin_identifiers"] == ["a" * 64]
    assert technical["dates"] == ["2026-09-01"]
    assert technical["finding_ids"] == ["RSI-ATLAS-001"]
    assert technical["percentages"] == [
        "10 percent",
        "20 percent",
        "25 percent",
        "45 percent",
    ]
    assert technical["currencies"] == ["USD"]
    assert technical["symbols"] == ["RSI"]


def test_declared_visible_raw_strings_and_structural_resource_inventory_are_exact(
    manifest: dict[str, Any],
) -> None:
    for fixture in manifest["fixtures"]:
        pdf_bytes = (CORPUS / "fixtures" / fixture["fixture"]).read_bytes()
        golden = loads((CORPUS / "golden" / fixture["golden"]).read_text(encoding="utf-8"))
        for expected in golden["expected_raw_strings"]:
            assert expected.encode("ascii") in pdf_bytes, (fixture["fixture"], expected)

        capabilities, resources = _structural_inventory(pdf_bytes)
        assert capabilities == fixture["declared_pdf_capabilities"], fixture["fixture"]
        assert resources == fixture["declared_external_resources"], fixture["fixture"]


def test_fixture_structures_match_declared_page_and_safety_features(
    manifest: dict[str, Any],
) -> None:
    required_markers = {
        "active_javascript": b"/JavaScript",
        "attachment": b"/EmbeddedFiles",
        "decompression_boundary": b"/FlateDecode",
        "encrypted": b"/Encrypt",
        "image_only": b"/Subtype /Image",
        "uri_action": b"/S /URI",
    }
    for fixture in manifest["fixtures"]:
        pdf_bytes = (CORPUS / "fixtures" / fixture["fixture"]).read_bytes()
        expected_page_count = fixture["expected_page_count"]
        page_objects = len(list(finditer(rb"/Type\s*/Page(?!s)", pdf_bytes)))
        assert page_objects == expected_page_count
        for feature in fixture["features"]:
            marker = required_markers.get(feature)
            if marker is not None:
                assert marker in pdf_bytes, (fixture["fixture"], feature)
        if "malformed_trailer" in fixture["features"]:
            assert not pdf_bytes.rstrip().endswith(b"%%EOF")
            assert b"/Root 9999 0 R" in pdf_bytes
            assert search(rb"startxref\s+1\s+%%BROKEN", pdf_bytes) is not None
        else:
            assert pdf_bytes.rstrip().endswith(b"%%EOF")

        if "decompression_boundary" in fixture["features"]:
            assert b"/XObject << /Bomb" in pdf_bytes
            assert b"q /Bomb Do Q" in pdf_bytes
            stream = search(
                rb"/Subtype /Form.*?/Filter /FlateDecode.*?stream\n(.*?)\nendstream",
                pdf_bytes,
                flags=DOTALL,
            )
            assert stream is not None
            compressed_payload = stream.group(1)
            decoded_payload = decompress(compressed_payload)
            assert fixture["resource_limits"] == [
                {
                    "accounting_scope": "referenced_form_xobject_decoded_stream",
                    "compressed_bytes": len(compressed_payload),
                    "compression_ratio": f"{len(decoded_payload) / len(compressed_payload):.6f}",
                    "decoded_bytes": 4_000_004,
                    "expected_outcome": "reject",
                    "limit_bytes": 1_000_000,
                    "limit_name": "decoded_stream_bytes",
                }
            ]
            assert len(decoded_payload) > fixture["resource_limits"][0]["limit_bytes"]
        else:
            assert fixture["resource_limits"] == []


def test_candidates_are_explicitly_unavailable_until_dependency_gate(
    manifest: dict[str, Any],
) -> None:
    assert manifest["candidates"] == [
        {
            "configuration_hash": None,
            "name": "docling",
            "qualification": "unqualified",
            "status": "unavailable",
            "tier": 1,
            "version": "2.113.0",
        },
        {
            "configuration_hash": None,
            "name": "pdfminer.six",
            "qualification": "unqualified",
            "status": "unavailable",
            "tier": 0,
            "version": "20260107",
        },
        {
            "configuration_hash": None,
            "name": "pypdf",
            "qualification": "unqualified",
            "status": "unavailable",
            "tier": 0,
            "version": "6.14.2",
        },
    ]


def test_performance_protocol_is_executable_and_qualification_ready(
    manifest: dict[str, Any],
) -> None:
    protocol = manifest["performance_protocol"]
    assert set(protocol) == {
        "cold_process",
        "metrics",
        "pass_fail_rules",
        "reference_environment",
        "result_record_schema",
        "size_classes",
        "timeout_seconds_per_run",
        "warm_process",
    }
    assert protocol["cold_process"] == {
        "filesystem_cache": "not_flushed_record_observed_state",
        "measured_runs_per_fixture": 30,
        "semantics": "new_interpreter_and_parser_instance_per_run",
        "warmup_iterations": 0,
    }
    assert protocol["warm_process"] == {
        "filesystem_cache": "shared_and_recorded",
        "measured_runs_per_fixture": 30,
        "semantics": "one_interpreter_one_parser_instance_no_result_cache",
        "warmup_iterations": 3,
    }
    assert protocol["timeout_seconds_per_run"] == 30
    assert protocol["pass_fail_rules"] == {
        "allowed_failure_count": 0,
        "allowed_timeout_count": 0,
        "all_class_ceilings_required": True,
    }
    assert protocol["reference_environment"] == {
        "hardware": "MacBook Pro Mac15,10; Apple M3 Max 14-core; 36 GB unified memory",
        "operating_system": "macOS 27.0",
        "runtime": "CPython 3.12.13 arm64",
    }
    assert protocol["metrics"] == [
        "failure_count",
        "p50_ms",
        "p95_ms",
        "peak_rss_bytes",
        "timeout_count",
    ]
    assert protocol["result_record_schema"] == {
        "required_fields": [
            "benchmark_schema_version",
            "candidate_configuration_hash",
            "candidate_name",
            "candidate_version",
            "execution_mode",
            "failure_count",
            "filesystem_cache_state",
            "fixture",
            "hardware",
            "measured_runs",
            "operating_system",
            "p50_ms",
            "p95_ms",
            "peak_rss_bytes",
            "runtime",
            "size_class",
            "timeout_count",
            "warmup_iterations",
        ],
        "schema_version": "1.0.0",
    }

    fixtures = {fixture["fixture"]: fixture for fixture in manifest["fixtures"]}
    classes = protocol["size_classes"]
    assert [size_class["name"] for size_class in classes] == ["small", "medium", "long"]
    assert len({name for size_class in classes for name in size_class["fixtures"]}) == sum(
        len(size_class["fixtures"]) for size_class in classes
    )
    for size_class in classes:
        assert size_class["fixtures"]
        assert size_class["p95_ceiling_ms"] > 0
        assert size_class["peak_rss_ceiling_bytes"] > 0
        for name in size_class["fixtures"]:
            fixture = fixtures[name]
            assert fixture["expected_preflight_route"] == "accept"
            assert (
                size_class["minimum_bytes"] <= fixture["size_bytes"] <= size_class["maximum_bytes"]
            )
            assert (
                size_class["minimum_pages"]
                <= fixture["expected_page_count"]
                <= size_class["maximum_pages"]
            )


def test_generator_reproduces_every_committed_fixture() -> None:
    completed = run(
        [executable, str(GENERATOR), "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


class DecimalString:
    def __init__(self, value: object) -> None:
        assert isinstance(value, str)
        whole, separator, fraction = value.partition(".")
        assert separator == "."
        assert whole.lstrip("-").isdigit()
        assert len(fraction) == 6 and fraction.isdigit()
        self.value = int(whole) * 1_000_000 + (-1 if whole.startswith("-") else 1) * int(fraction)

    def __lt__(self, other: object) -> bool:
        assert isinstance(other, DecimalString)
        return self.value < other.value
