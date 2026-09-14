"""Mathematical identifier spellings, independent of symbol binding and scope."""

_GREEK = dict(zip(
    'alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega'.split(),
    'αβγδεζηθικλμνξοπρστυφχψω',
))
MATH_ALIASES = {'$' + name: value for name, value in _GREEK.items()}
MATH_ALIASES.update({'$' + name.title(): value.upper() for name, value in _GREEK.items()})
MATH_ALIASES.update({'$varepsilon': 'ϵ', '$vartheta': 'ϑ', '$varphi': 'ϕ',
                     '$varrho': 'ϱ', '$varsigma': 'ς', '$infty': '∞', '$partial': '∂'})
SYSTEM_IDENTIFIERS = frozenset({'∞', '∂'})


def canonical_name(name: str) -> str:
    return MATH_ALIASES.get(name, name)


def valid_name(name: str) -> bool:
    return (name.isidentifier() or name in SYSTEM_IDENTIFIERS
            or name.startswith('$') and name[1:].isidentifier())


def valid_qualified_name(name: str) -> bool:
    return bool(name) and all(valid_name(part) for part in name.split('.'))
