"""Check a specification ZIP offline without extracting or executing its contents."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import hashlib
import io
import re
import stat
import struct
import time
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from validate_contract import InputError, Parser, emit, parse_json, validate_value
from contract_io import canonical_relative_path as canonical_path, path_identity, read_regular_file

DEFAULT_MAX_UNCOMPRESSED = 32 * 1024 * 1024
MAX_ENTRIES = 4096
MAX_DIRECTORY_BYTES = 4 * 1024 * 1024


class IntegrityError(InputError):
    pass


def digest(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise InputError("a SHA-256 digest must contain exactly 64 hexadecimal characters")
    return value.lower()


def checksum_digest(checksum: Path, bundle_name: str) -> str:
    payload = read_regular_file(checksum, 64 * 1024)
    if payload.startswith(b"\xef\xbb\xbf"):
        raise InputError("checksum files must not contain a UTF-8 BOM")
    try:
        lines = [line.strip() for line in payload.decode("utf-8").splitlines() if line.strip()]
    except UnicodeError as exc:
        raise InputError("checksum files must use UTF-8") from exc
    if len(lines) == 1 and re.fullmatch(r"[0-9a-fA-F]{64}", lines[0]):
        return digest(lines[0])
    matches = []
    for line in lines:
        match = re.fullmatch(r"([0-9a-fA-F]{64})[ \t]+\*?(.+)", line)
        if not match:
            raise InputError("malformed checksum record")
        if match.group(2) == bundle_name:
            matches.append(digest(match.group(1)))
    if len(matches) != 1:
        raise InputError("checksum file must identify the selected bundle exactly once")
    return matches[0]


def bounded_directory(payload: bytes) -> None:
    """Bound the central directory before ZipFile allocates its entry objects."""
    tail = payload[-(65535 + 22):]
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or len(tail) - position < 22:
        raise InputError("ZIP end-of-directory record is missing")
    _, disk, directory_disk, disk_entries, entries, size, offset, comment = struct.unpack_from("<4s4H2LH", tail, position)
    absolute_position = len(payload) - len(tail) + position
    if position + 22 + comment != len(tail):
        raise InputError("ZIP has an invalid comment or trailing bytes")
    if disk or directory_disk or disk_entries != entries:
        raise InputError("multipart ZIP archives are not supported")
    if entries == 65535 or size == 0xFFFFFFFF or offset == 0xFFFFFFFF:
        raise InputError("ZIP64 archives are outside the bounded specification format")
    if entries > MAX_ENTRIES or size > MAX_DIRECTORY_BYTES or offset + size != absolute_position:
        raise InputError("ZIP directory exceeds its limits or is inconsistent")
    if entries and not payload.startswith(b"PK\x03\x04"):
        raise InputError("prefixed ZIP archives are not supported")


@dataclass
class VerifiedBundle:
    manifest: dict
    files: dict[str, bytes]
    sha256: str
    expected_digest_matched: bool
    limitations: list[str]

    def summary(self) -> dict:
        return {
            "scope": "specification_bundle_integrity", "passed": True,
            "version": self.manifest["version"], "spec_version": self.manifest["spec_version"],
            "source_commit": self.manifest["source_commit"], "bundle_sha256": self.sha256,
            "expected_digest_matched": self.expected_digest_matched, "origin_authenticated": False,
            "component_count": len(self.manifest["components"]),
            "uncompressed_bytes": sum(len(payload) for payload in self.files.values()),
            "limitations": self.limitations,
        }


def verify_bundle(bundle: Path, expected_sha256: str | None = None, max_uncompressed: int = DEFAULT_MAX_UNCOMPRESSED) -> VerifiedBundle:
    if max_uncompressed <= 0:
        raise InputError("--max-uncompressed must be positive")
    expected = digest(expected_sha256) if expected_sha256 is not None else None
    payload = read_regular_file(bundle, max_uncompressed + MAX_DIRECTORY_BYTES + 65557)
    archive_hash = hashlib.sha256(payload).hexdigest()
    if expected is not None and archive_hash != expected:
        raise IntegrityError("bundle SHA-256 does not match the supplied expectation")
    bounded_directory(payload)
    files: dict[str, bytes] = {}
    entries: dict[str, tuple[str, bool]] = {}
    declared_size = 0
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if len(archive.infolist()) > MAX_ENTRIES:
                raise InputError("ZIP contains too many entries")
            for entry in archive.infolist():
                if entry.orig_filename != entry.filename:
                    raise InputError("ZIP entry names cannot contain truncated control characters")
                path = canonical_path(entry.filename[:-1] if entry.is_dir() else entry.filename)
                identity = path_identity(path)
                if identity in entries:
                    raise InputError(f"duplicate or colliding ZIP entry: {path}")
                entries[identity] = (path, entry.is_dir())
                mode = stat.S_IFMT(entry.external_attr >> 16)
                if mode not in {0, stat.S_IFREG, stat.S_IFDIR} or entry.external_attr & 0x400:
                    raise InputError(f"ZIP links, reparse points and special files are not permitted: {path}")
                if (mode == stat.S_IFDIR and not entry.is_dir()) or (mode == stat.S_IFREG and entry.is_dir()):
                    raise InputError(f"ZIP entry type conflicts with its name: {path}")
                if entry.flag_bits & 1 or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise InputError("encrypted or unsupported ZIP compression is not permitted")
                declared_size += entry.file_size
                if declared_size > max_uncompressed:
                    raise InputError("ZIP uncompressed content exceeds the declared limit")
                if entry.is_dir():
                    if entry.file_size:
                        raise InputError("ZIP directories must not contain data")
                    continue
                with archive.open(entry) as stream:
                    content = stream.read(entry.file_size + 1)
                if len(content) != entry.file_size:
                    raise InputError(f"ZIP entry size is inconsistent: {path}")
                files[path] = content
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as exc:
        raise InputError(f"invalid specification ZIP: {exc}") from exc
    for identity, (path, _) in entries.items():
        for parent in PurePosixPath(path).parents:
            if parent.as_posix() == ".":
                continue
            declared_parent = entries.get(path_identity(parent.as_posix()))
            if declared_parent and not declared_parent[1]:
                raise InputError(f"ZIP file is also used as a directory: {declared_parent[0]}")
    if "manifest.json" not in files:
        raise InputError("specification ZIP is missing manifest.json")
    manifest = parse_json(files["manifest.json"])
    errors = validate_value("release-manifest", manifest)
    if errors:
        raise InputError("invalid bundle manifest: " + "; ".join(errors[:10]))
    if manifest["artifact_kind"] != "specification":
        raise InputError("this verifier accepts specification bundles, not CLI product packages")
    if manifest["version"] != manifest["spec_version"]:
        raise InputError("specification version and package version differ")
    expected_paths = {canonical_path(component["path"]) for component in manifest["components"]}
    if set(files) != expected_paths | {"manifest.json"}:
        raise InputError("ZIP regular-file inventory differs from the manifest component inventory")
    for component in manifest["components"]:
        if component["version"] != manifest["version"]:
            raise InputError(f"specification component version differs: {component['path']}")
        if hashlib.sha256(files[component["path"]]).hexdigest() != component["sha256"]:
            raise IntegrityError(f"component SHA-256 differs: {component['path']}")
    if "VERSION" in files:
        try:
            package_version = files["VERSION"].decode("utf-8").strip()
        except UnicodeError as exc:
            raise InputError("VERSION must use UTF-8") from exc
        if package_version != manifest["version"]:
            raise InputError("VERSION content differs from the manifest version")
    limitations = ["Hashes and manifest consistency do not authenticate publisher identity or prove the source commit's provenance.", "This check does not run applications, devices, CLI product commands or SkillHub installation."]
    if expected is None:
        limitations.insert(0, "No independent expected digest was supplied; only internal bundle consistency was checked.")
    return VerifiedBundle(manifest, files, archive_hash, expected is not None, limitations)


def main(argv: list[str] | None = None) -> int:
    started = time.monotonic()
    parser = Parser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    expectations = parser.add_mutually_exclusive_group()
    expectations.add_argument("--checksum", type=Path)
    expectations.add_argument("--expected-sha256")
    parser.add_argument("--max-uncompressed", type=int, default=DEFAULT_MAX_UNCOMPRESSED)
    try:
        args = parser.parse_args(argv)
        expected = checksum_digest(args.checksum, args.bundle.name) if args.checksum else args.expected_sha256
        checked = verify_bundle(args.bundle, expected, args.max_uncompressed)
        emit(True, started, data=checked.summary())
        return 0
    except IntegrityError as exc:
        emit(False, started, code="E_INTEGRITY", message=str(exc))
        return 2
    except (InputError, ValueError, KeyError, TypeError, RecursionError) as exc:
        emit(False, started, code="E_VALIDATION", message=str(exc))
        return 2
    except OSError as exc:
        emit(False, started, code="E_IO", message=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
