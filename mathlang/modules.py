"""Isolated source modules and immutable namespaces; no Python code loading."""

from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from .environment import Definition, Environment, builtin_environment
from .normalization import Limits
from .terms import RuleSet, Symbol, SymbolKind, Term, Type
from .symbols import valid_qualified_name


class ModuleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Namespace(Term):
    name: str
    definitions: tuple[Definition, ...] = ()
    rules: tuple[RuleSet, ...] = ()
    is_module: bool = False
    is_package: bool = False
    dependencies: tuple["Namespace", ...] = ()
    __hash__ = Term.__hash__

    def definition(self, name: str) -> Definition | None:
        return next((d for d in self.definitions if d.symbol.name == name), None)

    def member(self, name: str) -> Term | None:
        definition = self.definition(name)
        return None if definition is None else definition.term


def namespace_definition(name: str, namespace: Namespace) -> Definition:
    return Definition(Symbol(name, SymbolKind.NAMESPACE, Type("Namespace")), namespace)


def bind_import(environment: Environment, name: str, definition: Definition) -> None:
    """Imports never replace user definitions; repeated imports are idempotent."""
    previous = environment.definitions.get(name)
    if previous is not None:
        if previous.term is definition.term:
            return
        raise ModuleError(f"Import conflicts with existing name {name!r}")
    environment.define(definition if name == definition.symbol.name else
                       Definition(replace(definition.symbol, name=name), definition.term))


def bind_module(environment: Environment, path: str, module: Namespace) -> None:
    parts = path.split(".")
    if not valid_qualified_name(path):
        raise ModuleError(f"Invalid module binding {path!r}")

    def merge(existing: Definition | None, index: int) -> Definition:
        name = parts[index]
        if index == len(parts) - 1:
            if existing is not None:
                if existing.term is module:
                    return existing
                previous = existing.term
                if isinstance(previous, Namespace) and previous.name == module.name:
                    extra = tuple(d for d in previous.definitions if module.definition(d.symbol.name) is None)
                    same_members = all(previous.member(d.symbol.name) is d.term for d in module.definitions)
                    package_children = all(isinstance(d.term, Namespace) and d.term.name.startswith(module.name + '.') for d in extra)
                    if previous.is_module and same_members and package_children:
                        return existing
                    if previous.is_package and package_children:
                        for d in previous.definitions:
                            member = module.member(d.symbol.name)
                            if member is not None and member is not d.term:
                                raise ModuleError(f"Import conflicts with package member {d.symbol.name!r}")
                        return namespace_definition(name, replace(module, definitions=module.definitions + extra))
                raise ModuleError(f"Import conflicts with existing name {path!r}")
            return namespace_definition(name, module)
        if existing is not None and not isinstance(existing.term, Namespace):
            raise ModuleError(f"Import prefix {name!r} is not a namespace")
        parent = Namespace(".".join(parts[:index+1]), is_package=True) if existing is None else existing.term
        child = merge(parent.definition(parts[index+1]), index+1)
        definitions = tuple(d for d in parent.definitions if d.symbol.name != parts[index+1]) + (child,)
        return namespace_definition(name, replace(parent, definitions=definitions,
                                                   is_module=False, is_package=True))

    definition = merge(environment.definitions.get(parts[0]), 0)
    # The merge only extends package namespaces; ordinary definitions are checked above.
    environment._definitions[parts[0]] = definition


class ModuleLoader:
    def __init__(self, paths=(), *, limits: Limits | None = None):
        self.paths = tuple(dict.fromkeys(Path(p).resolve() for p in paths)) or (Path.cwd(),)
        self.limits = Limits() if limits is None else limits
        self.cache: dict[str, Namespace] = {}
        self.loading: list[str] = []

    @contextmanager
    def transaction(self):
        snapshot = self.cache.copy()
        try:
            yield
        except BaseException:
            self.cache.clear()
            self.cache.update(snapshot)
            raise

    def locate(self, name: str) -> Path:
        parts = name.split(".")
        if not valid_qualified_name(name):
            raise ModuleError(f"Invalid module name {name!r}")
        roots = (Path(__file__).parent / "stdlib",) if parts[0] == "std" else self.paths
        relative = parts[1:] if parts[0] == "std" else parts
        if not relative:
            raise ModuleError("Import a standard library module, such as std.core")
        for root in roots:
            for suffix in (".math", ".mathir"):
                candidate = root.joinpath(*relative).with_suffix(suffix)
                if candidate.is_file():
                    return candidate
        raise ModuleError(f"Module {name!r} was not found in the module search paths")

    def load(self, name: str, kernel) -> Namespace:
        if name in self.cache:
            return self.cache[name]
        snapshot = kernel.algebras.copy()
        try:
            with self.transaction():
                return self._load(name, kernel)
        except BaseException:
            kernel.algebras.clear()
            kernel.algebras.update(snapshot)
            raise

    def _load(self, name: str, kernel) -> Namespace:
        if name in self.loading:
            raise ModuleError("Cyclic import: " + " -> ".join((*self.loading, name)))
        if len(self.loading) >= self.limits.max_import_depth:
            raise ModuleError("Import depth limit exceeded")
        if len(self.cache) + len(self.loading) >= self.limits.max_modules:
            raise ModuleError("Module count limit exceeded")
        path = self.locate(name)
        self.loading.append(name)
        try:
            if path.suffix == ".mathir":
                from .serialization import load_ir, register_algebras
                module = load_ir(path, limits=self.limits, factory=kernel.factory)
                if not isinstance(module, Namespace) or not module.is_module or module.name != name:
                    raise ModuleError(f"Compiled file must contain module {name!r}")
                register_algebras(module, kernel)
                self.register(module)
            else:
                with path.open("rb") as stream:
                    raw = stream.read(self.limits.max_module_bytes + 1)
                if len(raw) > self.limits.max_module_bytes:
                    raise ModuleError("Module source size limit exceeded")
                module = self.compile(raw.decode("utf-8-sig"), name, kernel)
            self.cache[name] = module
            return module
        except (ValueError, OSError, UnicodeError) as error:
            raise ModuleError(f"While importing {name!r} from {path}:\n{error}") from None
        finally:
            self.loading.pop()

    def compile(self, source: str, name: str, kernel) -> Namespace:
        from .session import Session
        session = Session(builtin_environment().child(), module_loader=self, _kernel=kernel)
        session.execute(source, module_name=name)
        return Namespace(name, tuple(session.environment.definitions.values()),
                         session.environment.local_rule_sets, is_module=True,
                         dependencies=tuple(session.environment.imported_modules.values()))

    def register(self, module: Namespace):
        from .serialization import objects
        for item in objects(module):
            if isinstance(item, Namespace) and item.is_module:
                previous = self.cache.get(item.name)
                if previous is not None and previous != item:
                    raise ModuleError(f"Compiled dependency {item.name!r} conflicts with the loaded module; recompile together")
                if previous is None:
                    if len(self.cache) >= self.limits.max_modules:
                        raise ModuleError("Module count limit exceeded")
                    self.cache[item.name] = item
