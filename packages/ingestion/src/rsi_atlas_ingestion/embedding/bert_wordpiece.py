"""Stdlib BERT WordPiece tokenizer for pinned MiniLM (no tokenizers/transformers)."""

from __future__ import annotations

import unicodedata
from pathlib import Path


class BertWordPieceTokenizer:
    """Uncased BERT WordPiece matching HuggingFace BertTokenizer for MiniLM.

    ponytail: ceiling=BERT Basic+WordPiece only (no SentencePiece); upgrade=tokenizers crate
    if a non-BERT artifact is pinned.
    """

    def __init__(self, vocab_path: Path, *, max_seq_length: int = 256) -> None:
        if max_seq_length < 3:
            raise ValueError("max_seq_length must be >= 3")
        lines = vocab_path.read_text(encoding="utf-8").splitlines()
        self._vocab = {token: index for index, token in enumerate(lines)}
        for required in ("[PAD]", "[UNK]", "[CLS]", "[SEP]"):
            if required not in self._vocab:
                raise ValueError(f"vocab missing required token: {required}")
        self._unk_id = self._vocab["[UNK]"]
        self._cls_id = self._vocab["[CLS]"]
        self._sep_id = self._vocab["[SEP]"]
        self._max_seq_length = max_seq_length

    def encode(self, text: str) -> tuple[list[int], list[int], list[int]]:
        """Return (input_ids, attention_mask, token_type_ids) without padding."""
        pieces: list[int] = []
        for token in _basic_tokenize(text):
            pieces.extend(self._wordpiece_ids(token))
        max_pieces = self._max_seq_length - 2
        pieces = pieces[:max_pieces]
        input_ids = [self._cls_id, *pieces, self._sep_id]
        attention_mask = [1] * len(input_ids)
        token_type_ids = [0] * len(input_ids)
        return input_ids, attention_mask, token_type_ids

    def _wordpiece_ids(self, token: str) -> list[int]:
        if token in self._vocab:
            return [self._vocab[token]]
        chars = list(token)
        if not chars:
            return [self._unk_id]
        start = 0
        ids: list[int] = []
        while start < len(chars):
            end = len(chars)
            cur: str | None = None
            while start < end:
                substr = "".join(chars[start:end])
                if start > 0:
                    substr = f"##{substr}"
                if substr in self._vocab:
                    cur = substr
                    break
                end -= 1
            if cur is None:
                return [self._unk_id]
            ids.append(self._vocab[cur])
            start = end
        return ids


def _basic_tokenize(text: str) -> list[str]:
    cleaned = _clean_text(text).lower()
    cleaned = _strip_accents(cleaned)
    cleaned = _tokenize_chinese_chars(cleaned)
    output: list[str] = []
    for token in cleaned.split():
        output.extend(_split_on_punctuation(token))
    return output


def _clean_text(text: str) -> str:
    chars: list[str] = []
    for char in text:
        code = ord(char)
        if code == 0 or code == 0xFFFD or _is_control(char):
            continue
        if _is_whitespace(char):
            chars.append(" ")
        else:
            chars.append(char)
    return "".join(chars)


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _tokenize_chinese_chars(text: str) -> str:
    chars: list[str] = []
    for char in text:
        if _is_chinese_char(ord(char)):
            chars.append(" ")
            chars.append(char)
            chars.append(" ")
        else:
            chars.append(char)
    return "".join(chars)


def _split_on_punctuation(token: str) -> list[str]:
    chars = list(token)
    start_new = True
    output: list[list[str]] = []
    for char in chars:
        if _is_punctuation(char):
            output.append([char])
            start_new = True
        else:
            if start_new:
                output.append([])
            start_new = False
            output[-1].append(char)
    return ["".join(part) for part in output]


def _is_whitespace(char: str) -> bool:
    if char in {" ", "\t", "\n", "\r"}:
        return True
    return unicodedata.category(char) == "Zs"


def _is_control(char: str) -> bool:
    if char in {"\t", "\n", "\r"}:
        return False
    category = unicodedata.category(char)
    return category.startswith("C")


def _is_punctuation(char: str) -> bool:
    code = ord(char)
    if (
        33 <= code <= 47
        or 58 <= code <= 64
        or 91 <= code <= 96
        or 123 <= code <= 126
    ):
        return True
    return unicodedata.category(char).startswith("P")


def _is_chinese_char(code: int) -> bool:
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
        or 0x2B740 <= code <= 0x2B81F
        or 0x2B820 <= code <= 0x2CEAF
        or 0xF900 <= code <= 0xFAFF
        or 0x2F800 <= code <= 0x2FA1F
    )


__all__ = ["BertWordPieceTokenizer"]
