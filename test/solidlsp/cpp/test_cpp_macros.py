# SPDX-License-Identifier: MIT

import json
import shutil
from pathlib import Path

import pytest

from solidlsp.ls_config import LanguageServerId
from solidlsp.lsp_protocol_handler.lsp_types import SymbolKind
from test.conftest import start_ls_context


@pytest.mark.cpp
@pytest.mark.skipif(shutil.which("clangd") is None, reason="clangd is not installed")
@pytest.mark.parametrize("enabled", [False, True])
def test_macro_declarations_follow_active_definitions(tmp_path: Path, enabled: bool) -> None:
    header = "#if ENABLED\n#define ELEMENTS 8\n#else\n#define ELEMENTS 4\n#endif\n#define APPLY(x) \\\n    ((x) + ELEMENTS)\n"
    source = '#include "macros.h"\nint helper(void) { return 1; }\nint run(void) {\n#define LOCAL_WORDS 2\n    return APPLY(ELEMENTS) + LOCAL_WORDS + helper();\n}\n'
    (tmp_path / "macros.h").write_text(header)
    (tmp_path / "main.c").write_text(source)
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "file": str(tmp_path / "main.c"),
                    "arguments": ["clang", f"-DENABLED={int(enabled)}", "-c", str(tmp_path / "main.c")],
                }
            ]
        )
    )
    with start_ls_context(
        LanguageServerId.CPP,
        repo_path=str(tmp_path),
        solidlsp_dir=tmp_path / "state",
        ls_specific_settings={LanguageServerId.CPP: {"ls_path": shutil.which("clangd")}},
    ) as ls:
        for name, path, definition_line, body in [
            ("ELEMENTS", "macros.h", 1 if enabled else 3, f"#define ELEMENTS {8 if enabled else 4}"),
            ("APPLY", "macros.h", 5, "#define APPLY(x) \\\n    ((x) + ELEMENTS)"),
            ("LOCAL_WORDS", "main.c", 3, "#define LOCAL_WORDS 2"),
        ]:
            symbol = ls.request_defining_symbol("main.c", 4, source.splitlines()[4].index(name), include_body=True, prefer_declaration=True)
            assert symbol is not None
            assert symbol["name"] == name
            assert symbol["kind"] == SymbolKind.Constant
            assert symbol["location"]["relativePath"] == path
            assert symbol["selectionRange"]["start"]["line"] == definition_line
            assert symbol["body"].get_text() == body
            position = symbol["selectionRange"]["start"]
            hover = ls.request_hover(path, position["line"], position["character"])
            assert hover is not None and name in str(hover["contents"])

        function = ls.request_defining_symbol("main.c", 4, source.splitlines()[4].index("helper"))
        assert function is not None
        assert function["name"] == "helper"
        assert function["kind"] == SymbolKind.Function
