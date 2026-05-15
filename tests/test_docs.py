"""Documentation hygiene tests."""

import importlib.util
from pathlib import Path

CHECK_SCRIPT = Path("scripts/check-docs-hygiene.py")


def test_docs_do_not_contain_local_user_home_paths():
    spec = importlib.util.spec_from_file_location("check_docs_hygiene", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    check_docs_hygiene = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check_docs_hygiene)

    paths = [Path("README.md"), *Path("docs").glob("*.md")]

    assert check_docs_hygiene.find_local_user_home_paths(paths) == []
