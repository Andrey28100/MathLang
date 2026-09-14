"""Versioned, data-only DAG serialization with explicit types and validation."""

from dataclasses import fields, is_dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from fractions import Fraction
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import typing
from uuid import UUID

from . import terms as ir
from . import rewriting as rw
from .algebra import AlgebraDefinition, Relation, WordReduction, compile_algebra, word_term
from .environment import Definition, builtin_environment
from .modules import Namespace
from .normalization import Limits
from .proof import EqualityGoal, PropertyGoal, Proof, ProofResult, check_proof
from .theories import (Theory, TheoryParent, TheoryOperation, Axiom, Implementation, PropertyResult,
                       validate_theory, validate_property, validate_implementation)
from .symbols import valid_name, valid_qualified_name


class SerializationError(ValueError):
    pass


FORMAT = "mathlang-ir"
VERSION = 7
_CLASSES = (
    ir.Truth, ir.Comparison, ir.Logical, ir.Defined, ir.ForAll,
    Theory, TheoryParent, TheoryOperation, Axiom, Implementation, PropertyResult,
    ir.Type, ir.Number, ir.ApproxNumber, ir.Symbol, ir.Unary, ir.Binary, ir.FunctionCall, ir.Function,
    ir.Substitution, ir.RuleSet, ir.RewriteRequest, ir.Approach, ir.CalculusOperator,
    ir.CalculusRequest, ir.TaylorSeries, Definition, Namespace,
    rw.Wildcard, rw.LiteralPattern, rw.UnaryPattern, rw.BinaryPattern, rw.CallPattern,
    rw.RuleCondition, rw.RewriteRule, Relation, WordReduction, AlgebraDefinition,
    EqualityGoal, PropertyGoal, Proof, ProofResult,
)
_TYPES = {cls.__name__: cls for cls in _CLASSES}


def objects(root):
    """Visit dataclass records once, including opaque namespaces and proofs."""
    seen, stack = set(), [root]
    while stack:
        value = stack.pop()
        if isinstance(value, tuple):
            stack.extend(reversed(value))
        elif is_dataclass(value) and not isinstance(value, type) and id(value) not in seen:
            seen.add(id(value))
            yield value
            stack.extend(getattr(value, f.name) for f in reversed(fields(value)) if f.init)


def _fields(value):
    return {f.name: getattr(value, f.name) for f in fields(value) if f.init}


def dumps_ir(value: ir.Term | Proof, *, limits: Limits | None = None) -> str:
    limits = Limits() if limits is None else limits
    if not isinstance(value, (ir.Term, Proof)):
        raise SerializationError("IR root must be a mathematical term, module or proof")
    records, indices, visiting = [], {}, set()

    def encode(item):
        if isinstance(item, Enum):
            if type(item) is ir.TruthValue:
                return {'truth': item.value}
            if type(item) is not ir.SymbolKind:
                raise SerializationError("Unsupported IR enum")
            return {"kind": item.value}
        if item is None or type(item) in (bool, str):
            return item
        if type(item) is int:
            if item.bit_length() > limits.max_integer_bits:
                raise SerializationError("IR integer size limit exceeded")
            return item
        if isinstance(item, Fraction):
            if max(item.numerator.bit_length(), item.denominator.bit_length()) > limits.max_integer_bits:
                raise SerializationError("IR exact number size limit exceeded")
            return {"rational": [str(item.numerator), str(item.denominator)]}
        if isinstance(item, UUID):
            return {"uuid": str(item)}
        if isinstance(item, tuple):
            return {"tuple": [encode(x) for x in item]}
        if type(item) not in _CLASSES or id(item) not in indices:
            raise SerializationError(f"Unsupported IR record {type(item).__name__}")
        return {"ref": indices[id(item)]}

    # Explicit post-order traversal preserves sharing without recursive DAG walking.
    stack = [(value, False)]
    try:
        while stack:
            item, ready = stack.pop()
            if isinstance(item, tuple):
                stack.extend((x, False) for x in reversed(item))
                continue
            if not is_dataclass(item) or isinstance(item, type):
                continue
            if id(item) in indices:
                continue
            if type(item) not in _CLASSES:
                raise SerializationError(f"Unsupported IR record {type(item).__name__}")
            if ready:
                record = {"tag": type(item).__name__, "fields": {k: encode(v) for k, v in _fields(item).items()}}
                indices[id(item)] = len(records)
                records.append(record)
                visiting.remove(id(item))
                if len(records) > limits.max_nodes:
                    raise SerializationError("IR record count limit exceeded")
            else:
                if id(item) in visiting:
                    raise SerializationError("Cyclic IR graphs are not supported")
                visiting.add(id(item))
                stack.append((item, True))
                stack.extend((v, False) for v in reversed(tuple(_fields(item).values())))
        text = json.dumps({"format": FORMAT, "version": VERSION, "nodes": records,
                           "root": encode(value)}, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > limits.max_ir_bytes:
            raise SerializationError("IR file size limit exceeded")
        return text
    except (RecursionError, TypeError) as error:
        raise SerializationError(f"Cannot serialize IR: {error}") from None


def _matches(value, annotation):
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        return any(_matches(value, arg) for arg in args)
    if origin is tuple:
        return (isinstance(value, tuple) and
                (all(_matches(v, args[0]) for v in value) if len(args) == 2 and args[1] is Ellipsis
                 else len(value) == len(args) and all(_matches(v, a) for v, a in zip(value, args))))
    if annotation is typing.Any:
        return True
    if annotation in (int, bool, str):
        return type(value) is annotation
    return isinstance(value, annotation)


def loads_ir(text: str, *, limits: Limits | None = None, factory: ir.TermFactory | None = None):
    limits = Limits() if limits is None else limits
    factory = ir.TermFactory() if factory is None else factory
    if len(text.encode("utf-8")) > limits.max_ir_bytes:
        raise SerializationError("IR file size limit exceeded")
    decoded, annotations = [], {}

    def integer(text):
        value = int(text)
        if value.bit_length() > limits.max_integer_bits:
            raise SerializationError("IR integer size limit exceeded")
        return value

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SerializationError(f"Duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_inexact(_):
        raise SerializationError("IR numbers must be exact")

    def decode(item):
        if item is None or type(item) in (str, int, bool):
            return item
        if not isinstance(item, dict) or len(item) != 1:
            raise SerializationError("Invalid IR field encoding")
        key, value = next(iter(item.items()))
        if key == "ref" and type(value) is int and 0 <= value < len(decoded):
            return decoded[value]
        if key == "tuple" and isinstance(value, list):
            return tuple(decode(x) for x in value)
        if key == "kind" and isinstance(value, str):
            return ir.SymbolKind(value)
        if key == 'truth' and isinstance(value, str):
            return ir.TruthValue(value)
        if key == "uuid" and isinstance(value, str):
            return UUID(value)
        if key == "rational" and isinstance(value, list) and len(value) == 2 and all(isinstance(v, str) for v in value):
            numerator, denominator = map(integer, value)
            if denominator <= 0:
                raise SerializationError("An IR rational denominator must be positive")
            return Fraction(numerator, denominator)
        raise SerializationError("Invalid IR field, reference or unsupported forward reference")

    try:
        document = json.loads(text, object_pairs_hook=unique_object, parse_int=integer,
                              parse_float=reject_inexact, parse_constant=reject_inexact)
        if (not isinstance(document, dict) or set(document) != {"format", "version", "nodes", "root"}
                or document["format"] != FORMAT or type(document["version"]) is not int or document["version"] not in (1, 2, 3, 4, 5, 6, VERSION)):
            raise SerializationError("Unsupported IR format or version")
        records = document["nodes"]
        if not isinstance(records, list) or len(records) > limits.max_nodes:
            raise SerializationError("IR record count limit exceeded or invalid node table")
        for record in records:
            if not isinstance(record, dict) or set(record) != {"tag", "fields"} or not isinstance(record['tag'], str):
                raise SerializationError("Invalid IR record")
            cls = _TYPES.get(record["tag"])
            if cls is None:
                raise SerializationError(f"Unknown IR tag {record['tag']!r}")
            if document['version'] < 5 and cls in (ir.ForAll, Theory, TheoryOperation, Axiom, Implementation, PropertyResult):
                raise SerializationError('Theory and quantifier records require IR version 5')
            if document['version'] < 6 and cls is TheoryParent:
                raise SerializationError('Theory inheritance records require IR version 6')
            if document['version'] < 7 and cls is ir.ApproxNumber:
                raise SerializationError('Approximate numeric records require IR version 7')
            payload = record["fields"]
            if document['version'] == 5 and cls is Theory and isinstance(payload, dict):
                if set(payload) != {'name', 'parameters', 'operations', 'constants', 'axioms'}:
                    raise SerializationError('Invalid legacy theory fields')
                payload = dict(payload, parents={'tuple': []})
            if document['version'] <= 3 and cls is ir.CalculusOperator and isinstance(payload, dict):
                if set(payload) != {'operation', 'variable', 'order', 'point'}:
                    raise SerializationError('Invalid legacy calculus operator fields')
                payload = dict(payload, upper=None)
                if payload['operation'] == 'integrate':
                    payload['operation'] = 'antiderivative'
            if document['version'] == 1 and cls is ir.Function and isinstance(payload, dict):
                if set(payload) != {'parameters', 'body'}:
                    raise SerializationError('Invalid fields for version 1 Function')
                payload = dict(payload, return_type=None)
            expected = tuple(f.name for f in fields(cls) if f.init)
            if not isinstance(payload, dict) or set(payload) != set(expected):
                raise SerializationError(f"Invalid fields for IR {cls.__name__}")
            values = {key: decode(payload[key]) for key in expected}
            if cls not in annotations:
                scope = vars(sys.modules[cls.__module__]) | _TYPES
                annotations[cls] = typing.get_type_hints(cls, globalns=scope)
            for key, value in values.items():
                if not _matches(value, annotations[cls][key]):
                    raise SerializationError(f"Invalid type of {cls.__name__}.{key}")
            instance = (factory._intern(cls, *values.values()) if issubclass(cls, ir.Term)
                        else cls(**values))
            if (document['version'] <= 3 and isinstance(instance, ir.Symbol)
                    and instance == ir.builtin_symbol('integrate')):
                instance = ir.builtin_symbol('antiderivative')
            decoded.append(instance)
        root = decode(document["root"])
        if not isinstance(root, (ir.Term, Proof)):
            raise SerializationError("Invalid IR root")
        _validate(decoded, limits, factory)
        return root
    except SerializationError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, RecursionError, OverflowError) as error:
        raise SerializationError(f"Invalid IR: {error}") from None


def _presentation(algebra):
    return (algebra.name, algebra.scalar_domain, algebra.type, algebra.generators,
            algebra.relations, algebra.reductions, algebra.basis, algebra.bilinear, algebra.confluence, algebra.conflict)


def _validate(records, limits, factory):
    symbols, algebras, checked = {}, {}, set()
    builtin_names = builtin_environment().definitions
    for node in records:
        if isinstance(node, ir.ApproxNumber):
            try:
                numeric_value = Decimal(node.text)
            except InvalidOperation:
                raise SerializationError("Invalid approximate numeric value") from None
            if not numeric_value.is_finite() or not (1 <= node.digits <= 500):
                raise SerializationError("Invalid approximate numeric value")
        if isinstance(node, ir.Symbol):
            if not valid_name(node.name):
                raise SerializationError("Invalid symbol name")
            previous = symbols.setdefault(node.identity, node)
            # Import aliases are represented by definitions pointing to original symbols.
            if previous.kind != node.kind or previous.annotation != node.annotation:
                raise SerializationError("Conflicting symbol identities")
            if node.kind == ir.SymbolKind.BUILTIN and (node.name not in builtin_names or node != ir.builtin_symbol(node.name)):
                raise SerializationError("Invalid builtin identity")
        if isinstance(node, (ir.Unary, rw.UnaryPattern)) and node.op not in ('+', '-'):
            raise SerializationError("Invalid unary operation")
        if isinstance(node, (ir.Binary, rw.BinaryPattern)) and node.op not in ('+', '-', '*', '/', '^'):
            raise SerializationError("Invalid binary operation")
        if isinstance(node, ir.Function):
            if len(set(p.name for p in node.parameters)) != len(node.parameters) or len(set(node.parameters)) != len(node.parameters):
                raise SerializationError("Function parameters must be distinct")
        if isinstance(node, ir.Substitution) and len({s.identity for s, _ in node.replacements}) != len(node.replacements):
            raise SerializationError("Duplicate substitution targets")
        if isinstance(node, ir.RewriteRequest) and node.strategy not in ('once', 'bottom_up', 'top_down'):
            raise SerializationError("Invalid rewrite strategy")
        if isinstance(node, ir.CalculusOperator):
            if node.operation not in ('derivative', 'antiderivative', 'integrate', 'series', 'limit'):
                raise SerializationError("Invalid calculus operation")
            if (node.operation == 'integrate' and (node.point is None or node.upper is None)
                    or node.operation != 'integrate' and node.upper is not None):
                raise SerializationError('Invalid integration bounds')
        if isinstance(node, ir.TaylorSeries):
            if len(node.coefficients) > limits.max_calculus_order + 1 or any(node.variable in ir.free_symbols(c) for c in (*node.coefficients, node.point)):
                raise SerializationError("Invalid Taylor series coordinate or order")
        if isinstance(node, Namespace):
            names = [d.symbol.name for d in node.definitions]
            if not valid_qualified_name(node.name) or len(names) != len(set(names)):
                raise SerializationError("Invalid namespace name or duplicate members")
            if node.is_module and node.is_package:
                raise SerializationError("A package view cannot also be a compiled module")
        if isinstance(node, Definition) and node.symbol.kind == ir.SymbolKind.RULE and not isinstance(node.value, ir.RuleSet):
            raise SerializationError("Rule definitions must contain rules")
        if isinstance(node, AlgebraDefinition):
            previous = algebras.setdefault(node.type.identity, node)
            if _presentation(previous) != _presentation(node):
                raise SerializationError("Conflicting algebra identities")
            if node.type.identity not in checked:
                basis = None if node.basis is None else tuple(word_term(node, w, factory) for w in node.basis)
                rebuilt = compile_algebra(node.name, node.scalar_domain, node.type, node.generators,
                                          node.relations, basis, bilinear=node.bilinear, limits=limits)
                if _presentation(rebuilt) != _presentation(node):
                    raise SerializationError("Compiled algebra does not match its defining relations")
                checked.add(node.type.identity)
            properties = {'associativity_proof': 'associative', 'commutativity_proof': 'commutative'}
            if len(dict(node.properties)) != len(node.properties):
                raise SerializationError("Duplicate algebra properties")
            for name, result in node.properties:
                if (name not in properties or not isinstance(result, ProofResult) or result.status != 'proved'
                        or result.goal != PropertyGoal(properties[name]) or result.proof is None
                        or result.proof.algebra is None or _presentation(result.proof.algebra) != _presentation(node)):
                    raise SerializationError("Algebra property needs a matching certificate for this algebra")
        if isinstance(node, Proof) and not check_proof(node, limits=limits):
            raise SerializationError("Proof certificate failed independent verification")
        if isinstance(node, ProofResult):
            if node.status not in ('proved', 'disproved', 'unknown'):
                raise SerializationError("Invalid proof status")
            if node.status == 'proved' and (node.proof is None or node.proof.goal != node.goal
                                           or not check_proof(node.proof, node.goal, limits=limits)):
                raise SerializationError("A proved result needs a valid matching certificate")
            if node.status != 'proved' and node.proof is not None:
                raise SerializationError("An unproved result cannot carry a proof certificate")
            if node.status == 'proved':
                proof = node.proof
                if (node.method != proof.method or node.left_normal != proof.left_normal
                        or node.right_normal != proof.right_normal or node.counterexample is not None
                        or node.checks != len(proof.children)):
                    raise SerializationError("Proof result metadata does not match its certificate")
    from .elaboration import Elaborator
    checker = Elaborator(limits, algebras)
    for node in records:
        if isinstance(node, Theory):
            validate_theory(node, limits)
        if isinstance(node, PropertyResult):
            validate_property(node, factory, limits, algebras)
        if isinstance(node, Implementation):
            validate_implementation(node, factory, limits, algebras)
        if isinstance(node, ir.Term):
            checker.infer(node)
        if isinstance(node, Definition) and node.value is not None and node.symbol.annotation is not None:
            # Namespace/algebra labels describe their roles, not mathematical value types.
            if node.symbol.kind in (ir.SymbolKind.CONSTANT, ir.SymbolKind.VARIABLE, ir.SymbolKind.PARAMETER):
                checker.require(node.value, node.symbol.annotation, f'Definition {node.symbol.name!r}')


def register_algebras(root, kernel):
    registry = kernel.algebras.copy()
    for node in objects(root):
        if isinstance(node, AlgebraDefinition):
            previous = registry.get(node.type.identity)
            if previous is not None and _presentation(previous) != _presentation(node):
                raise SerializationError("Loaded algebra conflicts with a live algebra identity")
            if previous is None or len(node.properties) > len(previous.properties):
                registry[node.type.identity] = node
    kernel.algebras.clear()
    kernel.algebras.update(registry)


def save_ir(value, path, *, limits: Limits | None = None):
    data = dumps_ir(value, limits=limits)
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         prefix=target.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_ir(path, *, limits: Limits | None = None, factory: ir.TermFactory | None = None):
    limits = Limits() if limits is None else limits
    with Path(path).open('rb') as stream:
        data = stream.read(limits.max_ir_bytes + 1)
    if len(data) > limits.max_ir_bytes:
        raise SerializationError("IR file size limit exceeded")
    try:
        text = data.decode('utf-8')
    except UnicodeError as error:
        raise SerializationError(f"IR must use UTF-8: {error}") from None
    return loads_ir(text, limits=limits, factory=factory)
