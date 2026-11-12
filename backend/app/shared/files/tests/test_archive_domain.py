"""Archive entry names (WP-046a S2, lane B's rules). Pure."""

from app.shared.files.domain.archive import manifest_text, safe_entry_name


def test_entry_names_never_make_paths_or_hide() -> None:
    cases = {
        "../../etc/passwd": "passwd",
        "C:\\Windows\\win.ini": "win.ini",
        ".bashrc": "bashrc",
        "re\x00port\x1f.pdf": "report.pdf",
        "   ": "file",
        "a/b/..": "file",
    }
    for raw, expected in cases.items():
        assert safe_entry_name(raw, taken=set()) == expected, raw


def test_collisions_are_numbered_ignoring_case_and_the_manifest_name_is_kept() -> None:
    taken: set[str] = set()
    assert safe_entry_name("Report.pdf", taken=taken) == "Report.pdf"
    assert safe_entry_name("report.pdf", taken=taken) == "report (2).pdf"
    assert safe_entry_name("REPORT.PDF", taken=taken) == "REPORT (3).PDF"
    assert safe_entry_name("manifest.txt", taken=taken) == "file-manifest.txt"


def test_long_names_keep_their_extension_and_nfc_is_applied() -> None:
    taken: set[str] = set()
    name = safe_entry_name("x" * 300 + ".docx", taken=taken, max_len=50)
    assert len(name) <= 50
    assert name.endswith(".docx")
    decomposed = "e\u0301te\u0301.txt"  # é written as e + combining accent
    assert safe_entry_name(decomposed, taken=taken) == "\u00e9t\u00e9.txt"


def test_the_manifest_names_files_by_id_and_reason_only() -> None:
    text = manifest_text([("a1", "file_state.infected"), ("b2", "not_found")], "Left out")
    assert text == "Left out\n\na1\tfile_state.infected\nb2\tnot_found\n"
