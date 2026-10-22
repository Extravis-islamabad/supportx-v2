"""Custom import-linter contract for module boundaries (architecture.md §6.1).

The built-in contract types cannot say "only the same module may import its internals" for an
open-ended set of modules, so this contract does it generically: any import from one module into
another module's non-public submodule is a violation.
"""

from dataclasses import dataclass

import grimp
from importlinter import Contract, ContractCheck, fields, output


@dataclass(frozen=True)
class IllegalImport:
    """One import that crosses a module boundary into internals."""

    importer: str
    imported: str
    line_numbers: tuple[int, ...]


def owning_module(name: str, container: str) -> str | None:
    """Return the top-level module under `container` that `name` belongs to, if any."""
    prefix = f"{container}."
    if not name.startswith(prefix):
        return None
    return f"{container}.{name[len(prefix) :].split('.', 1)[0]}"


def is_public(imported: str, module: str, public_submodules: set[str]) -> bool:
    """Whether `imported` is part of `module`'s public surface."""
    return imported == module or imported in {f"{module}.{sub}" for sub in public_submodules}


class ModuleBoundariesContract(Contract):
    """Modules under `container` may only import each other's public surface.

    Configuration options:
        - container:          Package holding the domain modules (e.g. app.modules).
        - public_submodules:  Submodules other modules may import besides the package root.
    """

    container = fields.StringField()
    public_submodules = fields.ListField(subfield=fields.StringField())

    def check(self, graph: grimp.ImportGraph, verbose: bool) -> ContractCheck:  # noqa: ARG002, FBT001 - signature fixed by import-linter
        """Collect every import from one module into another module's internals."""
        container: str = self.container  # type: ignore[assignment] # populated by import-linter fields
        public: set[str] = set(self.public_submodules)  # type: ignore[call-overload] # same
        illegal: list[IllegalImport] = []

        for module in sorted(graph.find_children(container)):
            targets = {module} | graph.find_descendants(module)
            for imported in sorted(targets):
                if is_public(imported, module, public):
                    continue
                for importer in sorted(graph.find_modules_that_directly_import(imported)):
                    importer_module = owning_module(importer, container)
                    if importer_module is None or importer_module == module:
                        continue
                    details = graph.get_import_details(importer=importer, imported=imported)
                    illegal.append(
                        IllegalImport(
                            importer=importer,
                            imported=imported,
                            line_numbers=tuple(d["line_number"] for d in details),
                        ),
                    )

        return ContractCheck(kept=not illegal, metadata={"illegal_imports": illegal})

    def render_broken_contract(self, check: ContractCheck) -> None:
        """Print each illegal import with a hint on how to fix it."""
        illegal: list[IllegalImport] = check.metadata["illegal_imports"]
        for item in illegal:
            lines = ", ".join(map(str, item.line_numbers))
            output.print_error(f"- {item.importer} -> {item.imported} (l.{lines})", bold=False)
        output.new_line()
        output.print(
            "Import only the other module's package root or its events module; "
            "see backend/app/modules/README.md.",
        )
