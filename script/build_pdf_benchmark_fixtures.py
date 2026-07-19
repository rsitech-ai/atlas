#!/usr/bin/env python3
"""Build the deterministic, dependency-free RSI Atlas PDF benchmark corpus."""

from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import dataclass
from hashlib import md5, sha256
from json import dumps
from pathlib import Path
from re import search, sub
from struct import pack
from typing import Literal
from zlib import compress

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "packages/ingestion/benchmarks/pdf"
FIXTURES = CORPUS / "fixtures"
GOLDEN = CORPUS / "golden"
INSPECTION_REPORT = ROOT / ".superpowers/sdd/phase-2b-pdf-corpus-inspection.json"
GENERATOR_VERSION = "rsi-atlas-pdf-corpus-1"
DECOMPRESSION_DECODED_BYTES = 4_000_004
DECOMPRESSION_LIMIT_BYTES = 1_000_000
TOKEN_CATEGORIES = (
    "bitcoin_identifiers",
    "currencies",
    "dates",
    "evm_addresses",
    "finding_ids",
    "percentages",
    "solana_addresses",
    "symbols",
)
PDF_PASSWORD_PADDING = bytes.fromhex(
    "28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a"
)


@dataclass(frozen=True)
class TextBlock:
    text: str
    left: int
    bottom: int
    right: int
    top: int
    font: Literal["F1", "F2", "F3"] = "F1"
    size: int = 12


@dataclass(frozen=True)
class PageSpec:
    blocks: tuple[TextBlock, ...] = ()
    media_box: tuple[int, int, int, int] = (0, 0, 612, 792)
    crop_box: tuple[int, int, int, int] = (0, 0, 612, 792)
    rotation: int = 0
    image_only: bool = False
    figure: bool = False
    table_grid: bool = False


@dataclass(frozen=True)
class FixtureSpec:
    fixture: str
    partition: Literal["development", "calibration", "validation", "adversarial"]
    document_family: str
    features: tuple[str, ...]
    route: Literal["accept", "awaiting_password", "reject", "review"]
    pages: tuple[PageSpec, ...]
    kind: str = "standard"
    expected_tokens: tuple[tuple[str, tuple[str, ...]], ...] = ()
    declared_pdf_capabilities: tuple[tuple[str, str, str], ...] = ()
    declared_external_resources: tuple[tuple[str, str], ...] = ()
    expected_page_count: int | None = None


class PDFWriter:
    def __init__(self) -> None:
        self.objects: list[bytes | None] = []

    def reserve(self) -> int:
        self.objects.append(None)
        return len(self.objects)

    def add(self, value: bytes) -> int:
        self.objects.append(value)
        return len(self.objects)

    def set(self, object_number: int, value: bytes) -> None:
        self.objects[object_number - 1] = value

    def build(self, *, root: int, trailer_extra: bytes = b"") -> bytes:
        if any(value is None for value in self.objects):
            raise ValueError("PDF writer contains an unresolved object")
        output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, value in enumerate(self.objects, start=1):
            assert value is not None
            offsets.append(len(output))
            output.extend(f"{number} 0 obj\n".encode())
            output.extend(value)
            output.extend(b"\nendobj\n")
        xref_offset = len(output)
        output.extend(f"xref\n0 {len(self.objects) + 1}\n".encode())
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode())
        output.extend(f"trailer\n<< /Size {len(self.objects) + 1} /Root {root} 0 R ".encode())
        output.extend(trailer_extra)
        output.extend(f">>\nstartxref\n{xref_offset}\n%%EOF\n".encode())
        return bytes(output)


def _pdf_string(value: str) -> bytes:
    if not value.isascii():
        raise ValueError("fixture text must remain ASCII for raw evidence checks")
    escaped = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"({escaped})".encode("ascii")


def _stream(payload: bytes, *, dictionary: bytes = b"") -> bytes:
    return (
        b"<< /Length "
        + str(len(payload)).encode()
        + b" "
        + dictionary
        + b">>\nstream\n"
        + payload
        + b"\nendstream"
    )


def _content_stream(page: PageSpec) -> bytes:
    if page.image_only:
        return b"q 300 0 0 300 72 360 cm /Im0 Do Q\n"
    commands = bytearray()
    if page.figure:
        commands.extend(
            b"0.10 0.35 0.80 rg 90 220 65 210 re f "
            b"0.15 0.65 0.35 rg 175 220 65 150 re f "
            b"0.95 0.55 0.10 rg 260 220 65 260 re f "
            b"0 G 1 w 72 200 m 360 200 l S\n"
        )
    if page.table_grid:
        commands.extend(
            b"0 G 0.5 w 54 610 390 110 re S "
            b"54 642 m 444 642 l S 54 678 m 444 678 l S "
            b"250 610 m 250 720 l S\n"
        )
    for block in page.blocks:
        commands.extend(
            b"BT /"
            + block.font.encode()
            + f" {block.size} Tf {block.left} {block.bottom} Td ".encode()
            + _pdf_string(block.text)
            + b" Tj ET\n"
        )
    return bytes(commands)


def _standard_pdf(
    spec: FixtureSpec,
    *,
    attachment: bool = False,
    javascript: bool = False,
    uri: str | None = None,
    decompression_boundary: bool = False,
) -> bytes:
    writer = PDFWriter()
    catalog_id = writer.reserve()
    pages_id = writer.reserve()
    font_helvetica = writer.add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_courier = writer.add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    font_times = writer.add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >>")
    image_id: int | None = None
    if any(page.image_only for page in spec.pages):
        pixels = bytes((220, 30, 30, 30, 150, 60, 20, 60, 220, 245, 190, 30))
        image_id = writer.add(
            _stream(
                pixels,
                dictionary=(
                    b"/Type /XObject /Subtype /Image /Width 2 /Height 2 "
                    b"/ColorSpace /DeviceRGB /BitsPerComponent 8 "
                ),
            )
        )

    catalog_extra = bytearray()
    if attachment:
        embedded_payload = b"RSI Atlas inert attachment fixture\n"
        embedded_id = writer.add(_stream(embedded_payload, dictionary=b"/Type /EmbeddedFile "))
        filespec_id = writer.add(
            b"<< /Type /Filespec /F (fixture.txt) /UF (fixture.txt) /EF << /F "
            + f"{embedded_id} 0 R".encode()
            + b" >> >>"
        )
        catalog_extra.extend(
            b"/Names << /EmbeddedFiles << /Names [(fixture.txt) "
            + f"{filespec_id} 0 R".encode()
            + b"] >> >> "
        )
    if javascript:
        action_id = writer.add(b"<< /S /JavaScript /JS (app.alert\\(fixture\\)) >>")
        catalog_extra.extend(f"/OpenAction {action_id} 0 R ".encode())
    decompression_form_id: int | None = None
    if decompression_boundary:
        expanded = b"q\n" + (b" " * 4_000_000) + b"Q\n"
        compressed = compress(expanded, level=9)
        decompression_form_id = writer.add(
            _stream(
                compressed,
                dictionary=(b"/Type /XObject /Subtype /Form /BBox [0 0 1 1] /Filter /FlateDecode "),
            )
        )

    page_ids: list[int] = []
    for index, page in enumerate(spec.pages):
        content = _content_stream(page)
        if decompression_form_id is not None and index == 0:
            content += b"q /Bomb Do Q\n"
        content_id = writer.add(_stream(content))
        annotation_id: int | None = None
        if uri is not None and index == 0:
            annotation_id = writer.add(
                b"<< /Type /Annot /Subtype /Link /Rect [72 680 420 710] "
                b"/A << /S /URI /URI " + _pdf_string(uri) + b" >> >>"
            )
        resources = (
            b"/Resources << /Font << "
            + f"/F1 {font_helvetica} 0 R /F2 {font_courier} 0 R /F3 {font_times} 0 R".encode()
            + b" >> "
        )
        if image_id is not None and page.image_only:
            resources += f"/XObject << /Im0 {image_id} 0 R >> ".encode()
        if decompression_form_id is not None and index == 0:
            resources += f"/XObject << /Bomb {decompression_form_id} 0 R >> ".encode()
        resources += b">> "
        media = " ".join(str(value) for value in page.media_box)
        crop = " ".join(str(value) for value in page.crop_box)
        page_object = bytearray(
            b"<< /Type /Page "
            + f"/Parent {pages_id} 0 R /MediaBox [{media}] /CropBox [{crop}] ".encode()
            + f"/Rotate {page.rotation} /Contents {content_id} 0 R ".encode()
            + resources
        )
        if annotation_id is not None:
            page_object.extend(f"/Annots [{annotation_id} 0 R] ".encode())
        page_object.extend(b">>")
        page_ids.append(writer.add(bytes(page_object)))

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    writer.set(pages_id, f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode())
    writer.set(
        catalog_id,
        b"<< /Type /Catalog /Pages " + f"{pages_id} 0 R ".encode() + bytes(catalog_extra) + b">>",
    )
    return writer.build(root=catalog_id)


def _over_page_limit_pdf() -> bytes:
    writer = PDFWriter()
    catalog_id = writer.reserve()
    pages_id = writer.reserve()
    font_id = writer.add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    content_id = writer.add(_stream(b"BT /F1 10 Tf 72 720 Td (Over page limit fixture) Tj ET\n"))
    page_ids = []
    for _ in range(2_001):
        page_ids.append(
            writer.add(
                b"<< /Type /Page "
                + f"/Parent {pages_id} 0 R /MediaBox [0 0 612 792] ".encode()
                + f"/Resources << /Font << /F1 {font_id} 0 R >> >> ".encode()
                + f"/Contents {content_id} 0 R >>".encode()
            )
        )
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    writer.set(pages_id, f"<< /Type /Pages /Count 2001 /Kids [{kids}] >>".encode())
    writer.set(catalog_id, f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    return writer.build(root=catalog_id)


def _password_bytes(password: str) -> bytes:
    raw = password.encode("latin-1")[:32]
    return (raw + PDF_PASSWORD_PADDING)[:32]


def _rc4(key: bytes, payload: bytes) -> bytes:
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) % 256
        state[i], state[j] = state[j], state[i]
    output = bytearray()
    i = 0
    j = 0
    for byte in payload:
        i = (i + 1) % 256
        j = (j + state[i]) % 256
        state[i], state[j] = state[j], state[i]
        output.append(byte ^ state[(state[i] + state[j]) % 256])
    return bytes(output)


def _object_key(file_key: bytes, object_number: int) -> bytes:
    seed = file_key + object_number.to_bytes(3, "little") + b"\x00\x00"
    return md5(seed).digest()[: min(len(file_key) + 5, 16)]


def _encrypted_pdf() -> bytes:
    writer = PDFWriter()
    catalog_id = writer.reserve()
    pages_id = writer.reserve()
    font_id = writer.add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    content_id = writer.reserve()
    page_id = writer.reserve()
    encrypt_id = writer.reserve()
    file_id = sha256(b"rsi-atlas-encrypted-fixture-v1").digest()[:16]
    permissions = -4
    owner_key = md5(_password_bytes("owner")).digest()[:5]
    owner_entry = _rc4(owner_key, _password_bytes("atlas"))
    file_key = md5(
        _password_bytes("atlas") + owner_entry + pack("<i", permissions) + file_id
    ).digest()[:5]
    user_entry = _rc4(file_key, PDF_PASSWORD_PADDING)
    plain_content = b"BT /F1 12 Tf 72 720 Td (Encrypted fixture) Tj ET\n"
    encrypted_content = _rc4(_object_key(file_key, content_id), plain_content)
    writer.set(content_id, _stream(encrypted_content))
    writer.set(
        page_id,
        b"<< /Type /Page "
        + f"/Parent {pages_id} 0 R /MediaBox [0 0 612 792] ".encode()
        + f"/Resources << /Font << /F1 {font_id} 0 R >> >> ".encode()
        + f"/Contents {content_id} 0 R >>".encode(),
    )
    writer.set(pages_id, f"<< /Type /Pages /Count 1 /Kids [{page_id} 0 R] >>".encode())
    writer.set(catalog_id, f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    writer.set(
        encrypt_id,
        b"<< /Filter /Standard /V 1 /R 2 /Length 40 "
        + b"/O <"
        + owner_entry.hex().encode()
        + b"> /U <"
        + user_entry.hex().encode()
        + b"> "
        + f"/P {permissions} >>".encode(),
    )
    trailer = f"/Encrypt {encrypt_id} 0 R /ID [<{file_id.hex()}><{file_id.hex()}>] ".encode()
    return writer.build(root=catalog_id, trailer_extra=trailer)


def _blocks(*values: tuple[str, int, int, int, int, str, int]) -> tuple[TextBlock, ...]:
    return tuple(
        TextBlock(text, left, bottom, right, top, font=font, size=size)
        for text, left, bottom, right, top, font, size in values
    )


def _specs() -> tuple[FixtureSpec, ...]:
    technical_pages = (
        PageSpec(
            blocks=_blocks(
                ("RSI Atlas Protocol Technical Paper", 54, 740, 400, 762, "F3", 18),
                (
                    "EVM address 0x1111111111111111111111111111111111111111",
                    54,
                    690,
                    292,
                    704,
                    "F2",
                    8,
                ),
                ("Solana address 11111111111111111111111111111111", 320, 690, 558, 704, "F2", 8),
                (
                    "Bitcoin txid aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    54,
                    650,
                    558,
                    664,
                    "F2",
                    8,
                ),
                ("Footer page 1", 260, 30, 350, 42, "F1", 8),
            )
        ),
        PageSpec(
            blocks=_blocks(
                ("Token Allocation", 54, 740, 240, 758, "F3", 16),
                ("Community 45 percent", 54, 690, 250, 706, "F1", 11),
                ("Treasury 25 percent", 260, 690, 440, 706, "F1", 11),
                ("Contributors 20 percent", 54, 650, 250, 666, "F1", 11),
                ("Liquidity 10 percent", 260, 650, 440, 666, "F1", 11),
                ("Footer page 2", 260, 30, 350, 42, "F1", 8),
            ),
            table_grid=True,
        ),
        PageSpec(
            blocks=_blocks(
                ("Vesting and Audit", 54, 740, 260, 758, "F3", 16),
                ("Vesting starts 2026-09-01", 54, 690, 260, 706, "F1", 11),
                ("Finding RSI-ATLAS-001", 320, 690, 520, 706, "F2", 10),
                ("Symbol RSI USD 1.25", 54, 650, 240, 666, "F1", 11),
                ("Footer page 3", 260, 30, 350, 42, "F1", 8),
            )
        ),
    )
    return tuple(
        sorted(
            (
                FixtureSpec(
                    "active_javascript.pdf",
                    "adversarial",
                    "unknown",
                    ("active_javascript",),
                    "reject",
                    (
                        PageSpec(
                            blocks=_blocks(("Active action fixture", 72, 720, 260, 736, "F1", 12))
                        ),
                    ),
                    kind="javascript",
                    declared_pdf_capabilities=(("action", "JavaScript", "inline:test-fixture"),),
                ),
                FixtureSpec(
                    "audit_mixed_font.pdf",
                    "calibration",
                    "audit",
                    ("mixed_font", "single_column"),
                    "accept",
                    (
                        PageSpec(
                            blocks=_blocks(
                                ("SECURITY AUDIT REPORT", 72, 740, 340, 760, "F3", 17),
                                ("Finding AUD-2026-004 High", 72, 690, 330, 706, "F2", 11),
                                (
                                    "Recommendation apply access control",
                                    72,
                                    650,
                                    390,
                                    666,
                                    "F1",
                                    11,
                                ),
                            )
                        ),
                    ),
                    expected_tokens=(("finding_ids", ("AUD-2026-004",)),),
                ),
                FixtureSpec(
                    "crypto_technical_three_page.pdf",
                    "development",
                    "technical_paper",
                    ("mixed_font", "multi_column", "table"),
                    "accept",
                    technical_pages,
                    expected_tokens=(
                        (
                            "bitcoin_identifiers",
                            ("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
                        ),
                        ("currencies", ("USD",)),
                        ("dates", ("2026-09-01",)),
                        ("evm_addresses", ("0x1111111111111111111111111111111111111111",)),
                        ("finding_ids", ("RSI-ATLAS-001",)),
                        (
                            "percentages",
                            ("10 percent", "20 percent", "25 percent", "45 percent"),
                        ),
                        ("solana_addresses", ("11111111111111111111111111111111",)),
                        ("symbols", ("RSI",)),
                    ),
                ),
                FixtureSpec(
                    "decompression_boundary.pdf",
                    "adversarial",
                    "unknown",
                    ("decompression_boundary",),
                    "reject",
                    (
                        PageSpec(
                            blocks=_blocks(
                                ("Decompression boundary fixture", 72, 720, 340, 736, "F1", 12)
                            )
                        ),
                    ),
                    kind="decompression",
                ),
                FixtureSpec(
                    "embedded_attachment.pdf",
                    "adversarial",
                    "unknown",
                    ("attachment",),
                    "reject",
                    (
                        PageSpec(
                            blocks=_blocks(
                                ("Embedded attachment fixture", 72, 720, 330, 736, "F1", 12)
                            )
                        ),
                    ),
                    kind="attachment",
                    declared_pdf_capabilities=(("embedded_file", "Filespec", "fixture.txt"),),
                ),
                FixtureSpec(
                    "encrypted_password.pdf",
                    "adversarial",
                    "unknown",
                    ("encrypted",),
                    "awaiting_password",
                    (PageSpec(),),
                    kind="encrypted",
                ),
                FixtureSpec(
                    "governance_multicolumn.pdf",
                    "calibration",
                    "governance",
                    ("multi_column",),
                    "accept",
                    (
                        PageSpec(
                            blocks=_blocks(
                                ("Governance Proposal 42", 54, 740, 280, 758, "F3", 16),
                                ("FOR quorum 1200000 RSI", 54, 690, 280, 706, "F1", 11),
                                ("AGAINST quorum 300000 RSI", 320, 690, 560, 706, "F1", 11),
                            )
                        ),
                    ),
                    expected_tokens=(("symbols", ("RSI",)),),
                ),
                FixtureSpec(
                    "image_only.pdf",
                    "adversarial",
                    "unknown",
                    ("image_only",),
                    "review",
                    (PageSpec(image_only=True),),
                ),
                FixtureSpec(
                    "legal_disclosure.pdf",
                    "validation",
                    "legal_regulatory",
                    ("single_column",),
                    "accept",
                    (
                        PageSpec(
                            blocks=_blocks(
                                ("DIGITAL ASSET RISK DISCLOSURE", 72, 740, 430, 760, "F3", 16),
                                ("Loss of principal is possible", 72, 690, 340, 706, "F1", 11),
                                ("Effective date 2026-07-19", 72, 650, 320, 666, "F1", 11),
                            )
                        ),
                    ),
                    expected_tokens=(("dates", ("2026-07-19",)),),
                ),
                FixtureSpec(
                    "long_whitepaper_120_pages.pdf",
                    "calibration",
                    "whitepaper",
                    ("long_document", "single_column"),
                    "accept",
                    tuple(
                        PageSpec(
                            blocks=_blocks(
                                (f"Long Whitepaper page {page}", 72, 740, 340, 758, "F3", 15),
                                (f"Protocol evidence section {page}", 72, 690, 360, 706, "F1", 11),
                            )
                        )
                        for page in range(1, 121)
                    ),
                ),
                FixtureSpec(
                    "malformed_trailer.pdf",
                    "adversarial",
                    "unknown",
                    ("malformed_trailer",),
                    "reject",
                    (
                        PageSpec(
                            blocks=_blocks(
                                ("Malformed trailer fixture", 72, 720, 310, 736, "F1", 12)
                            )
                        ),
                    ),
                    kind="malformed",
                ),
                FixtureSpec(
                    "market_report_figure.pdf",
                    "calibration",
                    "market_report",
                    ("figure_caption", "long_document"),
                    "accept",
                    tuple(
                        PageSpec(
                            blocks=_blocks(
                                (f"Market Report page {page}", 72, 740, 300, 758, "F3", 15),
                                (f"BTC volume index {1000 + page}", 72, 690, 300, 706, "F1", 11),
                                ("Figure 1 weekly liquidity", 72, 120, 300, 136, "F1", 10),
                            ),
                            figure=True,
                        )
                        for page in range(1, 13)
                    ),
                ),
                FixtureSpec(
                    "over_page_limit.pdf",
                    "adversarial",
                    "unknown",
                    ("long_document", "over_page_limit"),
                    "reject",
                    (
                        PageSpec(
                            blocks=_blocks(("Over page limit fixture", 72, 720, 300, 736, "F1", 10))
                        ),
                    ),
                    kind="over_page",
                    expected_page_count=2001,
                ),
                FixtureSpec(
                    "parser_disagreement.pdf",
                    "adversarial",
                    "unknown",
                    ("parser_disagreement", "multi_column"),
                    "review",
                    (
                        PageSpec(
                            blocks=_blocks(
                                ("LEFT ORDER A", 72, 700, 260, 716, "F1", 12),
                                ("RIGHT ORDER B", 320, 700, 520, 716, "F1", 12),
                                ("OVERLAP ORDER C", 200, 700, 410, 716, "F2", 12),
                            )
                        ),
                    ),
                ),
                FixtureSpec(
                    "rotated_crop_box.pdf",
                    "development",
                    "technical_paper",
                    ("rotated_crop_box",),
                    "accept",
                    (
                        PageSpec(
                            blocks=_blocks(("Rotated crop evidence", 0, 650, 220, 668, "F1", 12)),
                            media_box=(-100, -50, 500, 750),
                            crop_box=(-50, -25, 450, 725),
                            rotation=90,
                        ),
                    ),
                ),
                FixtureSpec(
                    "tokenomics_table.pdf",
                    "development",
                    "tokenomics",
                    ("table", "single_column"),
                    "accept",
                    (
                        PageSpec(
                            blocks=_blocks(
                                ("TOKENOMICS", 72, 740, 250, 758, "F3", 16),
                                ("Category Allocation Unlock", 72, 690, 360, 706, "F2", 10),
                                ("Community 45 percent 2026-09-01", 72, 650, 390, 666, "F1", 11),
                                ("Treasury 25 percent 2027-01-01", 72, 620, 390, 636, "F1", 11),
                            ),
                            table_grid=True,
                        ),
                    ),
                    expected_tokens=(
                        ("dates", ("2026-09-01", "2027-01-01")),
                        ("percentages", ("25 percent", "45 percent")),
                    ),
                ),
                FixtureSpec(
                    "uri_action.pdf",
                    "adversarial",
                    "unknown",
                    ("uri_action",),
                    "reject",
                    (
                        PageSpec(
                            blocks=_blocks(
                                ("External governance reference", 72, 720, 350, 736, "F1", 12)
                            )
                        ),
                    ),
                    kind="uri",
                    declared_pdf_capabilities=(
                        ("action", "URI", "https://example.invalid/governance"),
                    ),
                    declared_external_resources=(("uri", "https://example.invalid/governance"),),
                ),
                FixtureSpec(
                    "whitepaper_single_column.pdf",
                    "development",
                    "whitepaper",
                    ("single_column",),
                    "accept",
                    (
                        PageSpec(
                            blocks=_blocks(
                                ("RSI NETWORK WHITEPAPER", 72, 740, 370, 760, "F3", 17),
                                ("A local first evidence protocol", 72, 690, 360, 706, "F1", 11),
                                ("Supply cap 100000000 RSI", 72, 650, 330, 666, "F2", 10),
                            )
                        ),
                    ),
                    expected_tokens=(("symbols", ("RSI",)),),
                ),
            ),
            key=lambda item: item.fixture,
        )
    )


def _build_pdf(spec: FixtureSpec) -> bytes:
    if spec.kind == "encrypted":
        return _encrypted_pdf()
    if spec.kind == "over_page":
        return _over_page_limit_pdf()
    pdf = _standard_pdf(
        spec,
        attachment=spec.kind == "attachment",
        javascript=spec.kind == "javascript",
        uri=(spec.declared_external_resources[0][1] if spec.kind == "uri" else None),
        decompression_boundary=spec.kind == "decompression",
    )
    if spec.kind == "malformed":
        pdf = pdf.replace(b"/Root 1 0 R ", b"/Root 9999 0 R ", 1)
        pdf = sub(rb"startxref\n[0-9]+", b"startxref\n1", pdf, count=1)
        return pdf.removesuffix(b"%%EOF\n") + b"%%BROKEN\n"
    return pdf


def _region(block: TextBlock, page_number: int) -> dict[str, object]:
    right = max(block.right, block.left + len(block.text) * block.size * 0.75) + 2
    return {
        "bottom": f"{block.bottom - 8:.6f}",
        "left": f"{block.left - 2:.6f}",
        "page": page_number,
        "right": f"{right:.6f}",
        "text": block.text,
        "top": f"{block.top + 4:.6f}",
    }


def _golden(spec: FixtureSpec) -> dict[str, object]:
    raw_strings = sorted(
        {block.text for page in spec.pages for block in page.blocks if spec.kind != "encrypted"}
    )
    declared_tokens = dict(spec.expected_tokens)
    tokens = {
        category: sorted(set(declared_tokens.get(category, ()))) for category in TOKEN_CATEGORIES
    }
    page_count = spec.expected_page_count
    if page_count is None:
        page_count = len(spec.pages)
    return {
        "bounding_region_semantics": {
            "coordinate_system": "pdf_bottom_left_points",
            "relation": "observed_glyph_box_must_be_contained",
            "tolerance_points": "1.000000",
        },
        "expected_bounding_regions": [
            _region(block, page_number)
            for page_number, page in enumerate(spec.pages, start=1)
            for block in page.blocks
            if spec.kind != "encrypted"
        ],
        "expected_page_count": page_count,
        "expected_preflight_route": spec.route,
        "expected_raw_strings": raw_strings,
        "expected_tokens": tokens,
        "fixture": spec.fixture,
        "schema_version": "1.0.0",
    }


def _json_bytes(value: object) -> bytes:
    return (dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def _corpus_files() -> dict[Path, bytes]:
    files: dict[Path, bytes] = {}
    manifest_fixtures = []
    for spec in _specs():
        pdf = _build_pdf(spec)
        golden_name = spec.fixture.removesuffix(".pdf") + ".json"
        golden_bytes = _json_bytes(_golden(spec))
        files[Path("fixtures") / spec.fixture] = pdf
        files[Path("golden") / golden_name] = golden_bytes
        resource_limits: list[dict[str, object]] = []
        if spec.kind == "decompression":
            compressed_bytes = len(compress(b"q\n" + (b" " * 4_000_000) + b"Q\n", level=9))
            resource_limits.append(
                {
                    "accounting_scope": "referenced_form_xobject_decoded_stream",
                    "compressed_bytes": compressed_bytes,
                    "compression_ratio": f"{DECOMPRESSION_DECODED_BYTES / compressed_bytes:.6f}",
                    "decoded_bytes": DECOMPRESSION_DECODED_BYTES,
                    "expected_outcome": "reject",
                    "limit_bytes": DECOMPRESSION_LIMIT_BYTES,
                    "limit_name": "decoded_stream_bytes",
                }
            )
        manifest_fixtures.append(
            {
                "declared_external_resources": [
                    {"kind": kind, "locator": locator}
                    for kind, locator in spec.declared_external_resources
                ],
                "declared_pdf_capabilities": [
                    {"kind": kind, "target": target, "type": capability_type}
                    for kind, capability_type, target in spec.declared_pdf_capabilities
                ],
                "document_family": spec.document_family,
                "expected_page_count": _golden(spec)["expected_page_count"],
                "expected_preflight_route": spec.route,
                "features": sorted(spec.features),
                "fixture": spec.fixture,
                "golden": golden_name,
                "golden_sha256": sha256(golden_bytes).hexdigest(),
                "license": "CC0-1.0",
                "maximum_fixture_bytes": 8_388_608,
                "partition": spec.partition,
                "provenance": f"deterministic-local-generator:{GENERATOR_VERSION}",
                "resource_limits": resource_limits,
                "sha256": sha256(pdf).hexdigest(),
                "size_bytes": len(pdf),
            }
        )
    manifest = {
        "candidates": [
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
        ],
        "fixtures": manifest_fixtures,
        "performance_protocol": {
            "cold_process": {
                "filesystem_cache": "not_flushed_record_observed_state",
                "measured_runs_per_fixture": 30,
                "semantics": "new_interpreter_and_parser_instance_per_run",
                "warmup_iterations": 0,
            },
            "metrics": [
                "failure_count",
                "p50_ms",
                "p95_ms",
                "peak_rss_bytes",
                "timeout_count",
            ],
            "pass_fail_rules": {
                "allowed_failure_count": 0,
                "allowed_timeout_count": 0,
                "all_class_ceilings_required": True,
            },
            "reference_environment": {
                "hardware": "MacBook Pro Mac15,10; Apple M3 Max 14-core; 36 GB unified memory",
                "operating_system": "macOS 27.0",
                "runtime": "CPython 3.12.13 arm64",
            },
            "result_record_schema": {
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
            },
            "size_classes": [
                {
                    "fixtures": [
                        "crypto_technical_three_page.pdf",
                        "tokenomics_table.pdf",
                        "whitepaper_single_column.pdf",
                    ],
                    "maximum_bytes": 65_536,
                    "maximum_pages": 3,
                    "minimum_bytes": 1,
                    "minimum_pages": 1,
                    "name": "small",
                    "p95_ceiling_ms": 750,
                    "peak_rss_ceiling_bytes": 268_435_456,
                },
                {
                    "fixtures": ["market_report_figure.pdf"],
                    "maximum_bytes": 1_048_576,
                    "maximum_pages": 50,
                    "minimum_bytes": 1,
                    "minimum_pages": 4,
                    "name": "medium",
                    "p95_ceiling_ms": 2_000,
                    "peak_rss_ceiling_bytes": 536_870_912,
                },
                {
                    "fixtures": ["long_whitepaper_120_pages.pdf"],
                    "maximum_bytes": 8_388_608,
                    "maximum_pages": 2_000,
                    "minimum_bytes": 1,
                    "minimum_pages": 51,
                    "name": "long",
                    "p95_ceiling_ms": 10_000,
                    "peak_rss_ceiling_bytes": 1_073_741_824,
                },
            ],
            "timeout_seconds_per_run": 30,
            "warm_process": {
                "filesystem_cache": "shared_and_recorded",
                "measured_runs_per_fixture": 30,
                "semantics": "one_interpreter_one_parser_instance_no_result_cache",
                "warmup_iterations": 3,
            },
        },
        "qualification": {
            "production": "blocked_sealed_holdout_missing",
            "tier0_development": "unqualified",
            "tier1_development": "unqualified",
        },
        "schema_version": "1.0.0",
    }
    files[Path("manifest.json")] = _json_bytes(manifest)
    return files


def _write(files: dict[Path, bytes]) -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for relative, payload in files.items():
        target = CORPUS / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return 0


def _check(files: dict[Path, bytes]) -> int:
    failures = []
    for relative, expected in files.items():
        target = CORPUS / relative
        if not target.is_file():
            failures.append(f"missing {relative}")
        elif target.read_bytes() != expected:
            failures.append(f"drifted {relative}")
    expected_paths = set(files)
    for directory in (FIXTURES, GOLDEN):
        if directory.is_dir():
            for path in directory.iterdir():
                relative = path.relative_to(CORPUS)
                if path.is_file() and relative not in expected_paths:
                    failures.append(f"unexpected {relative}")
    if failures:
        print("\n".join(sorted(failures)))
        return 1
    print(f"verified {len(files)} deterministic corpus files")
    return 0


def _observed_box(page: object, expected: str) -> dict[str, str]:
    chars = page.chars  # type: ignore[attr-defined]
    joined = "".join(str(char["text"]) for char in chars)
    start = joined.find(expected)
    if start < 0:
        raise ValueError(f"independent extractor did not find {expected!r}")
    selected = chars[start : start + len(expected)]
    if "".join(str(char["text"]) for char in selected) != expected:
        raise ValueError(f"independent extractor returned non-contiguous text for {expected!r}")
    return {
        "bottom": f"{min(float(char['y0']) for char in selected):.6f}",
        "left": f"{min(float(char['x0']) for char in selected):.6f}",
        "right": f"{max(float(char['x1']) for char in selected):.6f}",
        "top": f"{max(float(char['y1']) for char in selected):.6f}",
    }


def _observe() -> int:
    """Write ignored evidence produced by parser libraries independent of this PDF writer."""
    try:
        import pdfminer
        import pdfplumber
        import pypdf
    except ImportError as error:
        print(f"observation runtime is missing an independent parser: {error}")
        return 2

    observations: list[dict[str, object]] = []
    for spec in _specs():
        path = FIXTURES / spec.fixture
        pdf_bytes = path.read_bytes()
        observation: dict[str, object] = {
            "fixture": spec.fixture,
            "fixture_sha256": sha256(pdf_bytes).hexdigest(),
        }
        if spec.kind == "malformed":
            try:
                pypdf.PdfReader(path, strict=True)
            except Exception as error:  # independent parser failure is the evidence under test
                observation["strict_parser"] = {
                    "error_type": type(error).__name__,
                    "outcome": "rejected",
                }
            else:
                raise ValueError("strict pypdf unexpectedly accepted malformed_trailer.pdf")
            observations.append(observation)
            continue
        if spec.kind == "encrypted":
            reader = pypdf.PdfReader(path, strict=True)
            observation["encryption"] = {
                "is_encrypted": reader.is_encrypted,
                "right_password_result": reader.decrypt("atlas"),
                "wrong_password_result": pypdf.PdfReader(path, strict=True).decrypt("wrong"),
            }
            observation["observed_page_count"] = len(reader.pages)
            observations.append(observation)
            continue

        with pdfplumber.open(path) as parsed:
            observation["observed_page_count"] = len(parsed.pages)
            if len(parsed.pages) != _golden(spec)["expected_page_count"]:
                raise ValueError(f"independent page count mismatch for {spec.fixture}")
            observed_regions = []
            observed_text_by_page = []
            for page_number, page_spec in enumerate(spec.pages, start=1):
                page = parsed.pages[page_number - 1]
                extracted_text = page.extract_text() or ""
                observed_text_by_page.append(
                    {"page": page_number, "text": extracted_text, "rotation": page.rotation}
                )
                for block in page_spec.blocks:
                    observed_box = _observed_box(page, block.text)
                    extractor_box: dict[str, str] | None = None
                    if page.rotation == 90:
                        extractor_box = observed_box
                        media_right = page_spec.media_box[2]
                        observed_box = {
                            "bottom": extractor_box["left"],
                            "left": f"{media_right - float(extractor_box['top']):.6f}",
                            "right": f"{media_right - float(extractor_box['bottom']):.6f}",
                            "top": extractor_box["right"],
                        }
                    observed_regions.append(
                        {
                            **observed_box,
                            "coordinate_system": "pdf_bottom_left_points",
                            "extractor_box": extractor_box,
                            "extractor_coordinate_system": (
                                None if extractor_box is None else "pdfplumber_rotated_page_points"
                            ),
                            "page": page_number,
                            "text": block.text,
                        }
                    )
            observation["observed_regions"] = observed_regions
            observation["observed_text_by_page"] = observed_text_by_page

        if "rotated_crop_box" in spec.features:
            reader = pypdf.PdfReader(path, strict=True)
            observed_geometry = []
            for page_number, (page_spec, page) in enumerate(
                zip(spec.pages, reader.pages, strict=True), start=1
            ):
                media_box = tuple(int(value) for value in page.mediabox)
                crop_box = tuple(int(value) for value in page.cropbox)
                rotation = int(page.get("/Rotate", 0))
                if (
                    media_box != page_spec.media_box
                    or crop_box != page_spec.crop_box
                    or rotation != page_spec.rotation
                ):
                    raise ValueError(f"independent page geometry mismatch for {spec.fixture}")
                observed_geometry.append(
                    {
                        "crop_box": list(crop_box),
                        "media_box": list(media_box),
                        "page": page_number,
                        "rotation": rotation,
                    }
                )
            observation["observed_page_geometry"] = observed_geometry

        expected_regions = _golden(spec)["expected_bounding_regions"]
        for expected_region, observed_region in zip(  # type: ignore[arg-type]
            expected_regions,
            observation["observed_regions"],
            strict=True,  # type: ignore[arg-type]
        ):
            if observed_region["coordinate_system"] == "pdf_bottom_left_points":
                tolerance = 1.0
                if not (
                    float(observed_region["left"]) - tolerance >= float(expected_region["left"])
                    and float(observed_region["bottom"]) - tolerance
                    >= float(expected_region["bottom"])
                    and float(observed_region["right"]) + tolerance
                    <= float(expected_region["right"])
                    and float(observed_region["top"]) + tolerance <= float(expected_region["top"])
                ):
                    raise ValueError(
                        f"independent glyph box escaped its envelope for {spec.fixture}: "
                        f"{observed_region['text']}"
                    )

        token_text = "\n".join(
            str(item["text"])
            for item in observation["observed_text_by_page"]  # type: ignore[index]
        )
        observation["observed_tokens"] = {
            category: [token for token in values if token in token_text]
            for category, values in _golden(spec)["expected_tokens"].items()  # type: ignore[union-attr]
        }
        if observation["observed_tokens"] != _golden(spec)["expected_tokens"]:
            raise ValueError(f"independent token evidence mismatch for {spec.fixture}")
        if (
            spec.kind == "standard"
            and any(page.image_only for page in spec.pages)
            and any(item["text"] for item in observation["observed_text_by_page"])  # type: ignore[index]
        ):
            raise ValueError("image-only fixture unexpectedly exposed extractable text")
        if spec.kind == "decompression":
            stream_match = search(
                rb"/Subtype /Form.*?/Filter /FlateDecode.*?stream\n(.*?)\nendstream",
                pdf_bytes,
                flags=16,
            )
            if stream_match is None:
                raise ValueError("referenced decompression Form XObject was not found")
            from zlib import decompress

            compressed_payload = stream_match.group(1)
            decoded_payload = decompress(compressed_payload)
            observation["decoded_stream"] = {
                "compressed_bytes": len(compressed_payload),
                "decoded_bytes": len(decoded_payload),
                "referenced_from_page_resources": b"/XObject << /Bomb" in pdf_bytes,
            }
        observations.append(observation)

    report = {
        "evidence_scope": "ignored_local_review_evidence_not_qualification_input",
        "fixtures": observations,
        "independent_tools": {
            "pdfminer.six": pdfminer.__version__,
            "pdfplumber": pdfplumber.__version__,
            "pypdf": pypdf.__version__,
            "poppler_pdfinfo": "26.05.0",
            "poppler_pdftoppm": "26.05.0",
        },
        "schema_version": "1.0.0",
        "verification_outcome": "passed",
        "visual_inspection": {
            "rendered_page_count": None,
            "status": "pending_manual_review",
        },
    }
    INSPECTION_REPORT.parent.mkdir(parents=True, exist_ok=True)
    INSPECTION_REPORT.write_bytes(_json_bytes(report))
    print(f"wrote independent observation evidence to {INSPECTION_REPORT}")
    return 0


def main() -> int:
    parser = ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--observe", action="store_true")
    arguments = parser.parse_args()
    if arguments.observe:
        return _observe()
    files = _corpus_files()
    return _write(files) if arguments.write else _check(files)


if __name__ == "__main__":
    raise SystemExit(main())
