# SPDX-License-Identifier: GPL-3.0-or-later

"""Reference queries for declarations in configured dependency workspaces."""

import json
import shutil
from pathlib import Path

import pytest

from serena.agent import SerenaAgent
from serena.repl.api.lsp_api import LspApi
from serena.tools import FindReferencingSymbolsTool
from test.conftest import create_default_serena_config


@pytest.mark.cpp
@pytest.mark.skipif(shutil.which("clangd") is None, reason="clangd is not installed")
def test_external_sdk_references(tmp_path: Path) -> None:
    root = tmp_path / "project"
    sdk = tmp_path / "sdk"
    root.mkdir()
    sdk.mkdir()
    (sdk / "sdk.h").write_text("#define SDK_VALUE 7\nint primitive(int value);\n")
    (root / "main.c").write_text('#include "sdk.h"\nint run(void) {\n  return primitive(SDK_VALUE);\n}\n')
    (root / "compile_commands.json").write_text(
        json.dumps([{"directory": str(root), "file": str(root / "main.c"), "arguments": ["clang", f"-I{sdk}", "-c", str(root / "main.c")]}])
    )
    (root / ".serena").mkdir()
    (root / ".serena/project.yml").write_text(
        json.dumps(
            {
                "project_name": "sdk-references",
                "language_servers": ["cpp"],
                "ls_additional_workspace_folders": [str(sdk)],
                "ls_specific_settings": {"cpp": {"ls_path": shutil.which("clangd")}},
            }
        )
    )
    config = create_default_serena_config()
    config.trusted_project_path_patterns = [str(root)]
    agent = SerenaAgent(project=str(root), serena_config=config)
    try:
        api = LspApi(agent)
        agent.execute_task(lambda: None)
        for name in ("primitive", "SDK_VALUE"):
            declaration = api.find_declaration("main.c", rf"({name})")
            assert "../sdk/sdk.h" in declaration.represent()
            references = (
                api.find_referencing_symbols(name, "../sdk/sdk.h")
                if name == "primitive"
                else agent.get_tool(FindReferencingSymbolsTool).apply(relative_path="main.c", regex=rf"({name})")
            )
            rendered = references if isinstance(references, str) else references.represent()
            assert "run" in rendered
            assert "main.c" in rendered
            compact = agent.get_tool(FindReferencingSymbolsTool).apply(relative_path="main.c", regex=rf"({name})", include_context=False)
            callers = json.loads(compact)["main.c"]["Function"]
            assert any(caller["name_path"] == "run" and caller["reference_line"] == 2 for caller in callers)
            assert len(compact) < len(rendered)
        outside = tmp_path / "outside.h"
        outside.write_text("int unrelated(void);\n")
        with pytest.raises(ValueError, match="outside the project root"):
            api.find_referencing_symbols("unrelated", "../outside.h")
    finally:
        agent.on_shutdown()


@pytest.mark.python
def test_external_python_dependency_references(tmp_path: Path) -> None:
    root = tmp_path / "project"
    dependency = tmp_path / "dependency"
    root.mkdir()
    dependency.mkdir()
    (dependency / "library.py").write_text("class SDKValue:\n    pass\n")
    (root / "main.py").write_text("from library import SDKValue\ndef run():\n    return SDKValue()\n")
    (root / "pyrightconfig.json").write_text(json.dumps({"extraPaths": [str(dependency)]}))
    (root / ".serena").mkdir()
    (root / ".serena/project.yml").write_text(
        json.dumps(
            {
                "project_name": "python-dependency-references",
                "language_servers": ["python"],
                "ls_additional_workspace_folders": [str(dependency)],
            }
        )
    )
    config = create_default_serena_config()
    agent = SerenaAgent(project=str(root), serena_config=config)
    try:
        agent.execute_task(lambda: None)
        api = LspApi(agent)
        declaration = api.find_declaration("main.py", r"return (SDKValue)\(\)", containing_symbol_name_path="run")
        assert "../dependency/library.py" in declaration.represent()
        occurrence_references = api.find_referencing_symbols(relative_path="main.py", regex=r"return (SDKValue)\(\)")
        assert "run" in occurrence_references.represent()
    finally:
        agent.on_shutdown()


@pytest.mark.cpp
@pytest.mark.skipif(shutil.which("clangd") is None, reason="clangd is not installed")
def test_generated_header_declaration_without_standalone_document_symbol(tmp_path: Path) -> None:
    root = tmp_path / "project"
    generated = tmp_path / "dependency" / "build"
    root.mkdir()
    generated.mkdir(parents=True)
    (root / ".gitignore").write_text("build/\n")
    header = generated / "Types.h.inc"
    header.write_text("#ifdef GET_CLASSES\nstruct Value { int stride() const; };\n#endif\n")
    (root / "main.cpp").write_text('#define GET_CLASSES\n#include "Types.h.inc"\nint run(Value value) { return value.stride(); }\n')
    (root / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(root),
                    "file": str(root / "main.cpp"),
                    "arguments": ["clang++", f"-I{generated}", "-c", str(root / "main.cpp")],
                }
            ]
        )
    )
    (root / ".serena").mkdir()
    (root / ".serena/project.yml").write_text(
        json.dumps(
            {
                "project_name": "generated-declaration",
                "language_servers": ["cpp"],
                "ls_additional_workspace_folders": [str(generated)],
                "ls_specific_settings": {"cpp": {"ls_path": shutil.which("clangd")}},
            }
        )
    )
    config = create_default_serena_config()
    config.trusted_project_path_patterns = [str(root)]
    agent = SerenaAgent(project=str(root), serena_config=config)
    try:
        agent.execute_task(lambda: None)
        api = LspApi(agent)
        result = json.loads(api.find_declaration("main.cpp", r"value\.(stride)\(\)", include_info=True, include_body=True).represent())
        assert result["declaration_location"]["absolutePath"] == str(header)
        assert result["declaration_location"]["range"]["start"]["line"] == 1
        assert result["symbol_details_available"] is False
        assert result["body_available"] is False
        assert "int stride() const" in str(result["info"])
        references = api.find_referencing_symbols(relative_path="main.cpp", regex=r"value\.(stride)\(\)", include_context=False)
        callers = json.loads(references.represent())["main.cpp"]
        assert any(reference["reference_line"] == 2 for group in callers.values() for reference in group)
    finally:
        agent.on_shutdown()
