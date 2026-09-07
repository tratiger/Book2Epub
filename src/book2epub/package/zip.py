"""Deterministic OCF ZIP archiver conforming strictly to EPUB 3.3 rules."""

import logging
import zipfile
from pathlib import Path

from book2epub.errors import PackagingError

logger = logging.getLogger(__name__)

MIMETYPE_BYTES = b"application/epub+zip"


def create_epub_zip(
    staging_dir: Path,
    target_epub_path: Path,
    reproducible: bool = False,
) -> Path:
    """
    Package an unpacked EPUB staging directory into an EPUB 3.3 ZIP archive.

    Enforces:
    1. allowZip64=True
    2. 'mimetype' is written first with ZIP_STORED (uncompressed)
    3. Remaining files written in deterministic lexical path order with ZIP_DEFLATED
    4. UTF-8 filenames, POSIX forward slashes only (no Windows backslashes)
    5. Reopens archive and verifies namelist()[0] == 'mimetype' with ZIP_STORED
    6. Writes to temporary file and atomically replaces target on success
    """
    if not staging_dir.is_dir():
        raise PackagingError(f"Staging directory does not exist: {staging_dir}")

    mimetype_file = staging_dir / "mimetype"
    if not mimetype_file.is_file():
        raise PackagingError(f"Missing required root mimetype file in staging: {staging_dir}")

    # Ensure target parent directory exists
    target_epub_path.parent.mkdir(parents=True, exist_ok=True)
    temp_epub_path = target_epub_path.with_suffix(".epub.tmp")
    fixed_time = (1980, 1, 1, 0, 0, 0)

    try:
        with zipfile.ZipFile(
            temp_epub_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            allowZip64=True,
        ) as zf:
            # 1. Write mimetype FIRST, uncompressed (ZIP_STORED)
            mimetype_content = mimetype_file.read_bytes()
            if mimetype_content.strip() != MIMETYPE_BYTES:
                raise PackagingError(f"Invalid mimetype: expected {MIMETYPE_BYTES!r}")

            # Write exact 20 bytes with ZIP_STORED
            mimetype_info = zipfile.ZipInfo(filename="mimetype")
            mimetype_info.compress_type = zipfile.ZIP_STORED
            mimetype_info.flag_bits |= 0x800  # UTF-8 flag
            if reproducible:
                mimetype_info.date_time = fixed_time
            zf.writestr(mimetype_info, MIMETYPE_BYTES)

            # 2. Collect all other files in deterministic lexical path order
            all_files: list[tuple[str, Path]] = []
            for file_path in staging_dir.rglob("*"):
                if file_path.is_file():
                    rel = file_path.relative_to(staging_dir)
                    posix_name = rel.as_posix()
                    if posix_name != "mimetype":
                        all_files.append((posix_name, file_path))

            all_files.sort(key=lambda x: x[0])

            # 3. Write remaining files with ZIP_DEFLATED
            for posix_name, file_path in all_files:
                zinfo = zipfile.ZipInfo(filename=posix_name)
                zinfo.compress_type = zipfile.ZIP_DEFLATED
                zinfo.flag_bits |= 0x800  # UTF-8 flag
                if reproducible:
                    zinfo.date_time = fixed_time
                zf.writestr(zinfo, file_path.read_bytes())

        # 4. Reopen and verify integrity
        with zipfile.ZipFile(temp_epub_path, mode="r") as verify_zf:
            names = verify_zf.namelist()
            if not names or names[0] != "mimetype":
                first_name = names[0] if names else "empty"
                raise PackagingError(f"First file in EPUB must be 'mimetype', found: {first_name}")

            first_info = verify_zf.getinfo("mimetype")
            if first_info.compress_type != zipfile.ZIP_STORED:
                raise PackagingError("EPUB root 'mimetype' entry must be uncompressed (ZIP_STORED)")

            # Check that no backslashes exist in archive paths
            for name in names:
                if "\\" in name:
                    raise PackagingError(f"Found Windows backslash in EPUB archive entry: {name}")

        # 5. Atomically replace target path
        temp_epub_path.replace(target_epub_path)
        return target_epub_path

    except Exception:
        if temp_epub_path.exists():
            temp_epub_path.unlink()
        raise
