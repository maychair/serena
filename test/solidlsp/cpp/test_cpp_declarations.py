# SPDX-License-Identifier: MIT

import json
import shutil
from pathlib import Path

import pytest

from solidlsp.ls_config import LanguageServerId
from test.conftest import start_ls_context


@pytest.mark.cpp
@pytest.mark.skipif(shutil.which("clangd") is None, reason="clangd is not installed")
def test_sdk_declaration_is_distinct_from_indexed_host_definition(tmp_path: Path) -> None:
    sdk = tmp_path / "sdk"
    checkout = tmp_path / "checkout"
    sdk.mkdir()
    checkout.mkdir()
    (sdk / "sdk.h").write_text("int primitive(int value);\n")
    (checkout / "kernel.c").write_text('#include "sdk.h"\nint run(void) { return primitive(1); }\n')
    (checkout / "host.c").write_text("int primitive(int value) { return value; }\n")
    (checkout / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(checkout),
                    "file": str(checkout / name),
                    "arguments": ["clang", f"-I{sdk}", "-c", str(checkout / name)],
                }
                for name in ("kernel.c", "host.c")
            ]
        )
    )
    with start_ls_context(
        LanguageServerId.CPP,
        repo_path=str(checkout),
        additional_workspace_folders=[str(sdk)],
        solidlsp_dir=tmp_path / "state",
        ls_specific_settings={LanguageServerId.CPP: {"ls_path": shutil.which("clangd")}},
    ) as ls:
        ls.request_document_symbols("host.c")
        declaration = ls.request_defining_symbol("kernel.c", 1, 23, prefer_declaration=True, include_body=True)
        assert declaration is not None
        assert declaration["location"]["absolutePath"] == str(sdk / "sdk.h")
        assert declaration["body"].get_text() == "int primitive(int value)"
        definition = ls.request_defining_symbol("kernel.c", 1, 23)
        assert definition is not None
        assert definition["location"]["relativePath"] == "host.c"
