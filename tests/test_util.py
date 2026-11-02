import pytest

from shorts.config import InputConfig
from shorts.ingest import IngestError, scan_folder
from shorts.util import file_sha256, slugify


def test_slugify():
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("???") == "clip"
    assert len(slugify("word " * 30, max_length=20)) <= 20


def test_file_sha256_stable_and_content_sensitive(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    assert file_sha256(a) == file_sha256(b)
    b.write_bytes(b"different")
    assert file_sha256(a) != file_sha256(b)


def test_scan_folder_filters_by_extension(tmp_path):
    for name in ("a.mp4", "b.MOV", "notes.txt"):
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "sub").mkdir()
    assert [p.name for p in scan_folder(tmp_path, InputConfig())] == ["a.mp4", "b.MOV"]


def test_scan_folder_rejects_non_directory(tmp_path):
    with pytest.raises(IngestError):
        scan_folder(tmp_path / "missing", InputConfig())
