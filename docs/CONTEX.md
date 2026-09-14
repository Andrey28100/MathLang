# MathLang — контекст проекта для AI-агента разработчика

> Этот файл — компактный рабочий контекст для агента, который изменяет MathLang.
> Он синтезирует `README.md`, `IMPLEMENTATION.md`, `SPECIFICATION.md`, `ROADMAP.md`,
> `LOGIC.md`, `ITERATION.md`, `CALCULUS.md`, `THEORIES.md`, `NUMERIC.md` и `IDE.md`.
> Это не замена исходным документам и не самостоятельный источник истины.

## 0. Как пользоваться этим файлом

Перед изменением кода:

1. Определи, относится ли задача к уже работающей семантике или к целевой архитектуре.
2. Для фактического поведения сначала сверяйся с кодом и тестами, затем с `IMPLEMENTATION.md` и профильным документом.
3. `SPECIFICATION.md` используй как архитектурную цель, а не как доказательство того, что функция уже реализована.
4. `ROADMAP.md` трактуй как план **оставшейся** работы с учётом уже реализованных частей.
5. Не расширяй trusted boundary ради удобства реализации.
6. Любое изменение семантики должно иметь regression tests и, если оно затрагивает переносимый IR, явное решение по versioning/совместимости.

### Приоритет источников при конфликте

Для вопроса «что работает сейчас?»:

```text
реальный код + tests/
    > IMPLEMENTATION.md
    > профильный документ текущей подсистемы
      (LOGIC / ITERATION / CALCULUS / THEORIES / NUMERIC / IDE)
    > README.md
    > актуализированный ROADMAP.md
    > SPECIFICATION.md как целевая архитектура
```

Ключевой факт: версия реализации — **0.9.2**. `IMPLEMENTATION.md` прямо фиксирует,
что он описывает фактический код, а при расхождении со старым roadmap или
архитектурным черновиком источником истины являются реализация и тесты.

---

# 1. Что такое MathLang

MathLang — прототип математического языка на Python 3.11+, находящийся между
символьной CAS и proof assistant.

Его цель — не захардкодить максимальное число математических объектов, а дать
общий механизм, через который пользователь определяет новые структуры с помощью:

- типов;
- операций;
- генераторов;
- relations;
- rewrite rules;
- normalizer'ов;
- theories и axioms;
- proofs и проверяемых certificates;
- contexts/assumptions.

Концептуально:

```text
Language
=
Terms
+ Types
+ Theories
+ Rewriting
+ Normalization
+ Proofs
```

Основная архитектурная идея: конкретная математика по возможности должна жить в
библиотеках и общих механизмах, а не в специальных ветках parser/runtime.

---

# 2. Главные архитектурные инварианты

Эти правила нельзя нарушать локальным «быстрым исправлением».

## 2.1. Синтаксис, математический IR и Typed IR разделены

Основной путь:

```text
source
  ↓
lexer
  ↓
parser → source AST
  ↓
resolver / Session
  ↓
immutable Term DAG
  ├─ Elaborator → Typed IR
  ├─ scalar normalizer
  ├─ algebra normalizer
  ├─ calculus
  ├─ logic / assumptions
  ├─ rewriting
  ├─ proof search / proof checker
  ├─ iteration engine
  └─ numeric backend
```

- AST хранит синтаксис и source spans.
- `Term` — математический объект без source span.
- `TermFactory` hash-cons'ит одинаковые структуры и строит общий immutable DAG.
- `Typed IR` — отдельный результат elaboration; его нельзя смешивать с основным
  вычислительным `Term` DAG.

Не помещай source-specific состояние в математический `Term` и не заставляй
runtime зависеть от IDE-представления.

## 2.2. Exact semantics по умолчанию

MathLang — точный символьный язык.

```text
0.125
```

означает точное `1/8`, а не binary float.

`sqrt(2)`, `exp(1)` и `sin(1)` не обязаны автоматически становиться числами с
плавающей точкой. Приближение выполняется только явным `numeric`.

## 2.3. Хранение выражения ≠ simplify ≠ normalize ≠ numeric

Пример:

```text
2*x + 3*x              // хранится как сумма
2*x + 3*x |> simplify // 5*x
(x+1)^3 |> normalize  // x^3 + 3*x^2 + 3*x + 1
sqrt(2) |> numeric    // ≈1.4142135623730950488
```

- `simplify` делает локальные/безопасные упрощения и учитывает assumptions.
- `normalize` строит каноническую форму для поддерживаемого математического класса.
- `numeric` выполняет явное приближённое вычисление.
- Нельзя добавлять скрытый floating-point evaluation в `simplify`, `normalize`
  или calculus.

## 2.4. Unknown не является True

Во всех логических и proof-подсистемах:

```text
True | False | Unknown
```

`Unknown` — отсутствие установленного ответа, а не «скорее истинно».
Нельзя использовать truthiness Python для `Unknown` или symbolic predicate.

## 2.5. Rewrite rule не является axiom

Пользовательское правило переписывания — вычислительное преобразование.
Proof checker не должен автоматически доверять ему как математической аксиоме.

## 2.6. Поиск доказательства и проверка доказательства должны быть разделены

Целевая модель:

```text
ProofSearch
    -> Proof
    -> ProofChecker
```

`ProofSearch` может быть эвристическим. `ProofChecker` должен оставаться маленьким,
строгим и независимо проверять certificate.

## 2.7. Семантика и оптимизированное представление разделены

Специализированный backend допустим ради производительности, но не должен менять
математическую семантику. Например, матрица в будущем может семантически быть
общей алгебраической структурой, а храниться плотным/разреженным массивом.

## 2.8. Новая математическая сущность не должна автоматически становиться новым special case ядра

Перед добавлением специального класса/ветки спроси, можно ли выразить объект через:

```text
Type
Theory
Operation
Relation
Rewrite
Normalizer
Proof
Context
```

Это один из центральных принципов `SPECIFICATION.md` и `ROADMAP.md`.

## 2.9. Сначала корректная математическая модель, затем красивый синтаксис

Не усложняй parser ради конструкции, для которой ещё нет корректной внутренней
семантики/IR.

---

# 3. Текущее состояние 0.9.2

Уже реализованы:

- lexer/parser для выражений, программ, блоков, lambda, pipeline, `where`,
  declarations, algebra, rules, logic, calculus, theories и modules;
- immutable symbolic `Term` DAG;
- точная арифметика через `Fraction`;
- `simplify` и scalar `normalize`;
- высокоточный explicit `numeric`;
- rewrite rules и стратегии;
- scalar type tower и отдельный Typed IR;
- predicates, assumptions и three-valued logic;
- finite-dimensional associative quotient algebras with identity;
- algebra coordinates, inversion, division и negative integer powers;
- analytic lift для части nilpotent/quadratic cases;
- proof certificates для поддерживаемых задач;
- derivative, antiderivative, definite integrate, Taylor series, finite limits;
- finite iteration, sum/product/all/any/factorial;
- modules, namespaces и standard library;
- versioned data-only IR serialization;
- generic theories, axioms, implementations и multiple inheritance;
- desktop IDE с diagnostics, completion, preview, plots, Types, Assumptions и
  Properties.

Важно: старые документы до синхронизации 0.9.2 ошибочно считали часть algebra
functional-calculus задач будущими. Уже существуют:

- координаты конечномерных алгебр;
- inversion/division/negative powers;
- общий nilpotent Taylor lift;
- частичная Euler-type reduction из relation вида `j^2=-c`;
- `mathlang/analytic_lift.py`;
- explicit real `numeric` backend.

---

# 4. Имена, symbols, scopes и функции

Поддерживаются категории объявлений:

```text
const c = 2
parameter a : Real
variable x : Real
unknown y : Real
```

Функции:

```text
f = c*x + a
square(t) = t^2

function g(x:Real):Real {
    const y = x*x
    return y + 1
}

h = (x:Real, y:Real) => x+y
```

Различай:

- source name;
- identity символа;
- lexical scope;
- mathematical term;
- type annotation.

Подстановка сравнивает symbols по identity и должна избегать capture.
Функции — first-class values; поддерживаются higher-order calls и closures.

Pipeline:

```text
value |> f
value |> f(a, b)
```

эквивалентен:

```text
f(value)
f(value, a, b)
```

Нельзя «оптимизировать» substitution только по текстовому имени символа.

---

# 5. Типы и Typed IR

Скалярная башня:

```text
Nat → Integer → Rational → Real → Complex
```

Также уже существуют типовые формы для:

- `Function<...>`;
- `Vector<T,n>`;
- `Matrix<T,m,n>`;
- nominal algebra types;
- `Predicate`;
- `Series<Real>`.

Elaborator строит отдельный Typed IR и вставляет явные:

```text
Embed<Source, Target>
```

для безопасных вложений.

Проверки dimensional/type errors должны происходить до вычисления там, где
типовая информация достаточна.

Текущая граница: тип каждого узла ещё не всегда известен заранее. Некоторые
неаннотированные определения и отложенные операции могут временно сохранять
unknown type. Не выдавай это за dependent type system.

Nominal algebra types несовместимы друг с другом, даже если их представления
похожи. Разрешённые scalar embeds в algebra должны оставаться явными в Typed IR.

---

# 6. Scalar simplification и domain safety

`simplify` не обязан раскрывать все степени/произведения; `normalize` строит
полиномиальную форму только в поддерживаемых случаях.

Потенциально частичная операция не сокращается без доказанной области определения:

```text
variable x : Real
simplify(x/x)        // x/x
assume x != 0
simplify(x/x)        // 1
```

Точное `sqrt(q)` для положительного рационального `q` канонизируется совместимо
с `q^(1/2)` без перехода к float.

Не добавляй simplification, которое уничтожает domain conditions.

---

# 7. Rewrite system

Пример:

```text
rule double {
    t+t -> 2*t
}
```

Поддерживаются:

- literal/unary/binary/call patterns;
- wildcards;
- `when` conditions;
- `once`, `bottom_up`, `top_down`, recursive repetition;
- лимиты проходов, rewrite steps и размера результата.

Assumption-aware conditional rewrite применяется только когда условие доказано как
`True`. `Unknown` не разрешает правило.

User rewrite никогда автоматически не становится trusted theorem.

---

# 8. Logic, predicates и assumptions

`Predicate` — отдельный математический тип и часть immutable `Term` DAG.

Поддерживаются:

```text
a == b     // математическое равенство
a != b
a === b    // структурное совпадение term + identities
x < y
x <= y
x > y
x >= y
p and q
p or q
not p
query(p)
domain(expr)
assume p
assuming { ... } { ... }
```

## 8.1. `==` и `===` различны

- `==` требует математически совместимых типов и может использовать normalizer/query.
- `===` сравнивает структуру/identities без математических преобразований.
- `Unknown == Unknown` даёт `Unknown`.
- `Unknown === Unknown` может дать `True` как структурное совпадение.

## 8.2. Контекст

`Context` содержит immutable `AssumptionSet`.

Child context наследует snapshot, но локальные assumptions не изменяют parent.
В REPL top-level `assume` живёт до конца session.

При ошибке текущий ввод должен откатить связанные изменения атомарно.

Нельзя принять как assumption:

- `False`;
- чистый `Unknown`;
- известное противоречие;
- заведомо undefined predicate.

Проверка согласованности ограничена поддерживаемым inference fragment и не является
общим SMT solver.

## 8.3. Текущий inference fragment

Поддерживается, в частности:

- exact rational comparisons;
- structural identity;
- equality через известные scalar/algebra normal forms;
- принятые conditions, conjunctions, negations, reversed comparisons;
- простые bounds одной переменной;
- nonnegativity для Nat и некоторых even powers;
- domain conditions основных scalar operations.

Не реализованы общие:

- equation/inequality solving;
- произвольная transitive closure отношений;
- case split;
- automatic substitution всех assumed equalities.

## 8.4. `domain(expr)`

Ключевые real-domain rules:

- `a/b` требует `b != 0`;
- nonpositive integer power требует nonzero base;
- `sqrt(a)` над Real требует `a >= 0`;
- `log(a)` над Real требует `a > 0`;
- `tan(a)` требует `cos(a) != 0`;
- общая real power консервативна.

Для partial expressions mathematical equality требует установленной definedness.
Structural equality её не требует.

## 8.5. Важная trust boundary

`Context(AssumptionSet(...))` как низкоуровневый контейнер не является проверкой
согласованности. Для проверяемых локальных контекстов используй normal API
`.assuming()` / `Session`.

Текущий `prove` не принимает непустой assumption context, потому что его portable
certificate пока не фиксирует assumptions. Это задача общей proof system 0.10.

---

# 9. Конечные итерации

Поддерживаются:

```text
iterate(f, initial, count)
sum(f, lower, upper)
product(f, lower, upper)
all(f, lower, upper)
any(f, lower, upper)
factorial(n)
```

Также block syntax:

```text
iterate(1, 6) {
    (value:Nat, index:Nat) => value*index
}
```

и binder form:

```text
k:Integer
sum(k^2, k, 1, 10)
```

## 9.1. Semantics

- `iterate(..., count=0)` возвращает initial term без вызова тела.
- Empty range: `sum=0`, `product=1`, `all=True`, `any=False`.
- Type/signature checks происходят даже для нулевого числа шагов.
- Каждый выполненный шаг использует существующее exact scalar/algebra kernel.
- В некоммутативном `product` порядок множителей сохраняется.
- State type должен быть стабильным; safe widening допускается, silent shape change — нет.
- `all` short-circuits on `False`; `any` short-circuits on `True`.
- `Unknown` не превращается в deciding truth value.

Обычные `and/or` внутри тела не обязаны иметь программное short-circuit поведение,
аналогичное folds.

## 9.2. Symbolic bounds

Если finite bound имеет допустимый тип, но значение неизвестно, call может
оставаться symbolic `FunctionCall` до substitution.

Не выводятся автоматически closed forms типа `n*(n+1)/2`.

## 9.3. Resource limits

По умолчанию `Limits.max_iterations = 10000`.
Budget общий для nested iterations одного kernel call и не сбрасывается внутри
factorial или nested fold.

Также действуют `max_steps`, `max_nodes`, `max_integer_bits`.

Budget/domain errors не превращаются в `Unknown` или partial approximate result.

---

# 10. Calculus

Основные операции:

```text
derivative(expr, x)
derivative(expr, x, order=n)
antiderivative(expr, x)
integrate(expr, x, a, b)
series(expr, x=point, order=n)
limit(expr, x -> point)
```

Calculus requests представлены собственными IR nodes и могут участвовать в pipeline.

## 10.1. Antiderivative vs definite integral

С 0.8.2:

- `antiderivative(expr,x)` — одна первообразная, без произвольной `+C`;
- `integrate(expr,x,a,b)` — определённый интеграл.

Старое `integrate(expr,x)` больше не означает первообразную; диагностика должна
подсказывать migration.

## 10.2. Definite integration

Текущий backend точный, не numerical quadrature:

1. проверяет regularity на всём closed interval;
2. строит поддерживаемую antiderivative;
3. применяет Newton–Leibniz.

Поддерживается ограниченный класс polynomial/affine elementary expressions.
При неизвестной regularity интеграл отклоняется, даже если математически он может
существовать.

Не скрывай singularity множителем `0`: domain исходного integrand всё равно важен.

## 10.3. TaylorSeries

```text
series(expr, x=a, order=n)
```

хранит коэффициенты powers `0..n-1` и remainder `O((x-a)^n)`.

Остаток — часть семантики. Нельзя неявно превращать series в polynomial.
Явное отбрасывание:

```text
polynomial(S)
```

`integrate(S,...)` обычно запрещён, если неизвестный remainder мешает точному ответу.

## 10.4. Symbolic finite sums in calculus

Для `sum` с symbolic finite bounds поддерживается termwise derivative,
antiderivative, definite integrate и limit, если bounds независимы от analysis variable.

После substitution целого index calculus выполняется на term с соблюдением обычных
type/domain/budget checks.

Не реализованы general linearity over arbitrary unresolved folds, symbolic product
calculus, infinite series convergence и interchange of limits/sums.

## 10.5. Explicit numeric after exact calculus

После получения closed exact real expression разрешено:

```text
integrate(exp(x), x, 0, 1) |> numeric(30)
```

`numeric` не меняет calculus semantics и не подменяет remainder числом.

---

# 11. Numeric backend 0.9.2

Синтаксис:

```text
numeric(expression)
numeric(expression, digits)
expression |> numeric
expression |> numeric(digits)
```

Default precision: 20 significant digits. Допустимо 1–500.

Поддерживаются closed real scalar expressions из:

- exact rationals;
- `+ - * /`;
- integer/real powers внутри поддерживаемой real domain;
- `sqrt`, `exp`, `log`, `sin`, `cos`, `tan`, `abs`.

Backend не использует binary `float`; основа — `decimal.Decimal` с guard digits.
Тригонометрия использует reduction с high-precision π и series evaluation.

## 11.1. `ApproxNumber` обязателен

Approximate result не может быть обычным `Number`, потому что source decimal в
MathLang exact.

```text
≈1.4142135623730950488
```

— `ApproxNumber`, static type `Real`, сериализуется в IR 7.

Exact `simplify`/`normalize` не должны начать выполнять hidden inexact arithmetic
только потому, что term содержит `ApproxNumber`.

## 11.2. Current numeric limits

`numeric` намеренно отказывается от:

- unresolved/open symbols;
- invalid real domains;
- unsupported user-function calls, не раскрытых символически;
- user algebra elements;
- complex approximate values;
- invalid precision.

Нет interval/ball certificate; `≈` означает approximation при рабочей точности,
но не строгую математическую error bound.

---

# 12. Конечномерные алгебры

Пример:

```text
algebra D over Real {
    generators {eps}
    relations {eps^2 = 0}
    derive basis
}
```

Текущий Algebra Engine строит quotient свободной **ассоциативной** алгебры с
центральными scalars и identity.

Поддерживаются:

- multiple generators;
- rational polynomial relations;
- oriented reductions;
- overlap/critical-pair checks;
- `confluence=known` только после успешной проверки;
- explicit basis и `derive basis`;
- basis coordinates;
- exact multiplication in coordinates;
- symbolic central scalar coefficients.

Arbitrary nonassociative backend не реализован.

## 12.1. Coordinates, inversion, division

Это уже реализовано, не будущая F1-задача.

`AlgebraNormalizer` предоставляет вычислительный слой уровня:

```python
coordinates(term)
from_coordinates(coords)
invertibility(term)
function_domain(name, term)
```

Для finite certified basis строится matrix левого умножения.
Determinant/adjugate вычисляются exact методом без heuristic symbolic pivots.

На этой базе работают:

- inverse;
- division `p/q = p*q^-1`;
- negative integer powers;
- invertibility/domain conditions;
- noncommutative multiplication order;
- проверка обеих сторон найденного inverse.

## 12.2. Scalar coefficients

`RationalCoefficients` хранит rational functions центральных scalar parameters.
Не сокращай denominator без доказательства nonzero condition.

Scalar power вроде `2^(1/2)` должна оставаться scalar coefficient, а не
интерпретироваться как power algebra element.

---

# 13. Analytic lift над алгебрами

`mathlang/analytic_lift.py` уже реализует существенную часть старых F2/F3/F4.

## 13.1. Nilpotent Taylor lift

Если algebra argument представим как:

```text
a + n
```

и normalizer доказывает `n^m=0`, функция строится конечным Taylor expansion.

Поддержаны `exp`, `sin`, `cos`; для допустимых real centers также часть `log` и `sqrt`.
Nilpotency index выводится из relations, а не имени алгебры.

Механизм должен оставаться generic: не добавляй special branch «если Dual».

## 13.2. Quadratic relations / Euler-type reduction

Relation вида:

```text
j^2 = -1
```

может приводить `exp(j*x)` к выражению через `cos` и `sin` без проверки имени `j`.
Масштабированные cases вроде `r^2=-2` также частично поддержаны.

## 13.3. Чего ещё нет

Нет общего functional calculus по minimal polynomial.
Не выдавай текущие специальные exact recognizers за общий algorithm.

---

# 14. Proof objects

Для поддерживаемых задач `prove` возвращает `ProofResult`, не boolean.

Статусы:

```text
proved
disproved
unknown
```

Успешный результат содержит proof certificate.
При deserialization certificate проверяется независимо: normal forms и algebra
presentation пересчитываются.

Уже реализованы:

- equality proof через normal forms;
- finite-basis associativity/commutativity checks;
- concrete counterexamples;
- persisted proof DAG + independent checking.

Пока не реализованы:

- общий tactic language;
- general `proof { ... }` blocks;
- trusted use arbitrary user axioms;
- conditional proof certificates с local assumption context;
- dependent proof terms.

---

# 15. Theory system 0.9.0–0.9.1

Пример:

```text
theory Monoid<T> {
    operation (*) : T x T -> T
    const identity:T
    axiom associative {
        forall a,b,c:T: (a*b)*c = a*(b*c)
    }
}

implementation Addition implements Monoid<Real> {
    operation (*) = (a:Real,b:Real)=>a+b
    const identity = 0
}
```

И наследование:

```text
theory Child<T> extends Parent<T>, Other<T> { ... }
```

## 15.1. Теории — library-level mathematical contracts

`Semigroup`, `Monoid`, `Group`, `Ring`, `Field` определены в MathLang standard
library, а не в Python kernel. Это обязательный архитектурный образец.

Theory поддерживает 1–8 type parameters, operations, constants и typed `forall`
axioms.

Одна operator notation пока не перегружается по нескольким signatures.

## 15.2. Implementation obligations

Implementation должна связать каждый required member ровно один раз.

Для каждой operation создаётся totality obligation `_total_name`: одной type
signature недостаточно, тело должно быть определено на всём заявленном domain.

Например `(x:Real)=>1/x` не является total `Real -> Real`.

Property statuses:

```text
proved
  exact supported proof exists

disproved
  exact counterexample stored

unknown
  engine could not decide

assumed
  user explicitly accepted axiom; no proof
```

`Implementation.valid`:

- `True` только если все obligations `proved`;
- `False`, если есть `disproved`;
- `Unknown`, если нет disproved, но есть `unknown` или `assumed`.

Assumed property не становится global assumption и не становится rewrite rule.

## 15.3. Supported axiom proof fragment

Exact proving работает для ограниченного polynomial fragment и для finite-basis
registered algebras через generic symbolic coordinates + `AlgebraNormalizer` +
`ProofChecker`.

Counterexample search конечный и точный; отсутствие найденного counterexample
никогда не является proof.

## 15.4. Inheritance

Multiple inheritance specialization подставляет type parameters в operations,
constants и bound-variable types axioms.

Merge допускается только при точном совпадении специализированного contract
с учётом alpha-equivalence bound names там, где это предусмотрено.

Конфликты signatures/axioms должны диагностироваться, а не тихо переопределяться.

Нет:

- operation renaming;
- overloads;
- local override inherited member;
- automatic casts между `Implementation` objects.

Cycles/forward references отклоняются. `Limits.max_theory_depth` по умолчанию 32.

## 15.5. Trust boundary

`assume axiom` внутри implementation не может скрыть уже установленное disproof.
Totality нельзя принять этим же синтаксисом.

При loading checker заново восстанавливает goals из theory и сверяет certificate /
counterexample. Он не запускает ProofSearch.

Текущий syntax `algebra A implements Ring<A>` из спецификации **ещё не является**
реализованным общим механизмом; используется отдельный `implementation Name implements ...`.

---

# 16. Standalone `forall`

Поддерживается:

```text
P = forall x:Real: x^2 >= 0
query(P)
```

Bound variables локальны и требуют type annotations. Substitution не должна
захватывать их identities.

Текущий engine сначала пытается symbolic proof, затем exact finite search for
disproof в ограниченном фрагменте.

Нет general `exists`, arbitrary axiom instantiation и general quantified theorem proving.

---

# 17. Modules, namespaces и atomic rollback

Поддерживаются:

```text
module name
import foo
import foo {A, B}
import foo as bar
namespace N { ... }
with N { ... }
use N
```

Module загружается в isolated environment; cache принадлежит `Session`.

Критический инвариант: неудачный program input должен атомарно откатывать
соответствующие изменения, включая definitions, module cache, algebra registry и
assumption context.

Не добавляй partially committed runtime state после exception.

Standard library содержит core/analysis/theories и algebra examples вроде
Complex, Dual, Quaternion.

---

# 18. Serialization

Формат: data-only JSON DAG `mathlang-ir`. Python executable code не сериализуется.

Current version: **7**.

Compatibility:

- reader поддерживает IR 1–6;
- v4 различает `antiderivative` и definite `integrate`;
- v5 добавил theory/forall;
- v6 добавил theory parents;
- v7 добавил `ApproxNumber`.

Loader должен проверять:

- tags и field types;
- builtin identities;
- graph references;
- resource limits;
- algebra presentations;
- proof certificates;
- theory inheritance/obligations.

Новый IR node или изменение persisted semantics требует осознанного решения:
можно ли сохранить текущую версию, нужна ли миграция, как старый reader должен
реагировать.

---

# 19. IDE

IDE находится в `mathlang.ide` и является presentation layer поверх существующего
parser/resolver/evaluator/renderer. Он **не** должен создавать второй frontend или
вторую семантику языка.

Базовая архитектура:

```text
PySide6 UI
  ├─ editor / project tree / Problems / Output / REPL
  ├─ LaTeX preview
  └─ Plot viewer
           │
           ▼
mathlang.ide.LanguageService
  ├─ syntax_diagnostics() -> parser
  ├─ semantic_diagnostics() -> disposable Session
  ├─ execute()/execute_repl() -> Session
  ├─ inspect_expression() -> Session.typed_ir()
  ├─ completions() -> syntax declarations / runtime names
  ├─ assumptions() -> current Session context
  ├─ format_latex() -> immutable Term DAG
  └─ plot() -> PlotSpec
           │
           ▼
existing mathlang frontend + kernel
```

## 19.1. IDE invariants

- Semantic diagnostics editor buffer должны использовать disposable Session и
  не мутировать REPL/runtime state.
- IDE не повторяет mathematics semantics; использует те же parser, Session,
  type/proof/renderer APIs.
- Plotting не использует Python `eval`.
- Non-Term proof/text/error output не нужно насильно превращать в LaTeX.
- Syntax/semantic analysis не должна менять Assumptions/Properties runtime panels.

## 19.2. Stability history worth preserving

Удалены short-lived `QRunnable`/`QObject` semantic workers, вызывавшие Qt lifetime
race при закрытии tabs. Текущий semantic pass на GUI boundary синхронный после
debounce; если analysis станет тяжёлым, предпочтительное направление — persistent
isolated subprocess, а не возврат к хрупким short-lived Qt workers.

Math preview использует `matplotlib.mathtext.math_to_image()` без переключения
global Matplotlib backend.

## 19.3. Current IDE capabilities

- dark project/editor UI;
- tabs, line numbers, highlighting;
- diagnostics + Problems;
- completion;
- Run file / Run selection / REPL;
- Types pane;
- Assumptions pane;
- Properties pane;
- scalar plots via frontend-neutral `PlotSpec`;
- MathText preview;
- Tectonic LaTeX-to-PDF compile (`--untrusted`) + embedded PDF;
- scrollable preview canvas;
- preview zoom 25–400%, pan, fit/reset;
- editor font zoom.

## 19.4. Deliberate IDE limitations

- parser/front-end analysis currently tends to report one first error per pass;
- completion не знает все local/import members;
- hover и go-to-definition future work;
- LaTeX preview only for supported mathematical Terms;
- scalar plot sampler ограничен безопасным subset;
- Tectonic не bundled.

---

# 20. Resource limits и termination safety

MathLang намеренно использует budgets, потому что symbolic rewriting,
normalization, quantifiers и iteration могут взрываться.

Существуют/используются ограничения типа:

- `max_iterations`;
- `max_steps`;
- `max_nodes`;
- `max_integer_bits`;
- `max_quantifier_checks`;
- `max_theory_depth`.

При добавлении recursive/expansive алгоритма:

1. используй общий `Limits`/budget contract;
2. не создавай локальный бесконечный обход без cycle/budget protection;
3. budget exhaustion — diagnostic/error, а не доказательство `False`, `True` или
   «примерный» математический результат.

---

# 21. Что сейчас принципиально НЕ реализовано

Не предполагай наличие следующих возможностей только потому, что они описаны в
`SPECIFICATION.md` или roadmap:

- general dependent type theory;
- arbitrary theorem prover / tactic language;
- general proof blocks;
- general existential quantifier;
- general equation solver;
- generic Groebner basis completion;
- arbitrary nonassociative algebra backend;
- full Matrix/Vector runtime arithmetic;
- general minimal-polynomial functional calculus;
- formal infinite power-series proof engine;
- automatic convergence proofs;
- complex `numeric` backend;
- interval/ball arithmetic и certified numeric error bounds;
- improper/general contour integration;
- Laurent/residue engine;
- multivariable gradient/jacobian/hessian;
- fully assumption-aware calculus branch selection;
- arbitrary user-defined operators/overload resolution as specified for 0.12;
- parameterized/indexed Clifford-like algebra families as specified for 0.11.

Не смешивай эти отсутствующие generic capabilities с уже работающими частными
finite-dimensional algebra/calculus mechanisms.

---

# 22. Ближайшая архитектурная работа

Roadmap после 0.9.2 задаёт следующую последовательность.

## 22.1. Завершение 0.9

Оставшиеся направления theory/properties включают, в частности:

- интеграцию `implements` с algebra declaration в целевой модели;
- более общий property/traits registry;
- подготовку properties к безопасному использованию proof engine.

## 22.2. 0.10 — general proof system

Цель — общий проверяемый proof language:

- `theorem`;
- `proof { ... }`;
- Goal / Proof / ProofStep;
- axiom/theorem application;
- rewrite/normalization steps;
- symmetry/transitivity/reflexivity;
- local assumptions;
- unified finite-basis proofs;
- explicit dependency list axioms/assumptions;
- serialized proof tree;
- independent strict checker.

Главное архитектурное требование: не расширять ProofChecker эвристикой поиска.

## 22.3. 0.11 — parameterized/indexed algebras

Цель — expressive generic algebra families, например Clifford(p,q), через indexed
generators и conditional relations без special runtime class.

## 22.4. 0.12 — user operations/operators и advanced functions

Нужны generic operator signatures, overloading via Typed IR, custom infix/prefix
operators, precedence, named/default args, generic functions.

## 22.5. 0.13 — algebraic standard library

Переносить Semigroup/Monoid/Group/Ring/Field/Complex/Quaternion/Clifford и т.п. в
обычные MathLang modules настолько, насколько позволяет performance.

## 22.6. 0.14 — real Vector/Matrix values

Типы уже есть, но runtime value layer надо довести до constructors, indexing,
linear algebra и exact coordinate solving.

## 22.7. 0.15 — advanced calculus

Partial derivatives, gradient/jacobian/hessian, expanded integrals/limits, Laurent,
complex functions, residues, contour API, assumption-aware calculus, more general
functional calculus.

Экспериментальные psi-algebra AD / residues / composition operators должны идти как
modules/backends, пока не доказана необходимость special kernel integration.

## 22.8. 0.16 — advanced normalizers

Планируются расширения canonical polynomial normalizer, commutative Groebner,
limited Knuth–Bendix, noncommutative Groebner, Groebner–Shirshov для отдельных
категорий.

Normalizer должен публиковать metadata вроде:

```text
termination: known / unknown
confluence: known / unknown
```

Heuristic normalization не должно автоматически становиться equality proof.

## 22.9. 0.17+ — rendering, IDE, infra, stabilization

Направления:

- unified renderer API;
- hover/go-to-definition/outline/quick fixes;
- AST/Typed IR/proof/rewrite viewers;
- algebra/basis/multiplication-table explorer;
- notebook-like cells;
- LSP;
- formatter/linter/docs generator;
- incremental compilation/elaboration;
- caches/profiling/benchmarks;
- stable semantic/module/IR versioning.

---

# 23. Test contract

`tests/` — основной executable contract.

На момент `IMPLEMENTATION.md` 0.9.2 зафиксировано:

- **423 теста**;
- **27 test modules**;
- все 27 модулей проходят при независимом запуске.

Полный запуск:

```powershell
python -m unittest discover -s tests
```

IDE-specific tests:

```powershell
python -m unittest tests.test_ide_editor tests.test_ide_service -v
```

Связанные профильные suites, упомянутые документацией:

- `tests/test_logic.py`;
- `tests/test_iteration.py`;
- `tests/test_analysis_extensions.py`;
- `tests/test_theories.py`;
- `tests/test_theory_inheritance.py`;
- `tests/test_numeric.py`.

При изменении subsystems обновляй/добавляй tests для:

- success path;
- invalid type/domain;
- Unknown vs False/True;
- rollback after failure;
- serialization round-trip, если persisted objects меняются;
- old IR compatibility, если затронут reader;
- resource limits;
- IDE/CLI/REPL consistency, если меняется frontend-visible behavior.

Не делай вывод «реализация корректна» только по одному ручному примеру.

---

# 24. Рабочий протокол AI-агента

## Шаг 1. Классифицируй задачу

Определи слой:

```text
syntax/parser
resolution/session
Term DAG
Typed IR / elaboration
scalar simplify/normalize
algebra normalizer
logic/context
calculus
iteration
proof/theory
serialization/modules
IDE/presentation
```

Не чинить symptom в IDE, если ошибка находится в kernel semantics.

## Шаг 2. Найди существующий contract

Проверь:

- relevant tests;
- `IMPLEMENTATION.md`;
- профильный markdown;
- related examples;
- roadmap only after current behavior understood.

## Шаг 3. Сохрани invariants

Проверь, что изменение не:

- смешивает AST и Term;
- смешивает Term и Typed IR;
- вводит float в exact path;
- превращает Unknown в True;
- доверяет rewrite как axiom;
- обходит independent proof checking;
- мутирует runtime из IDE diagnostics;
- теряет symbol identity/capture safety;
- нарушает atomic rollback;
- создаёт unlimited recursion;
- ломает IR compatibility молча.

## Шаг 4. Реализуй на минимально правильном уровне

Предпочитай generic kernel abstraction существующему/планируемому архитектурному
интерфейсу. Не добавляй special case по имени `Complex`, `Dual`, `Quaternion`,
`Clifford`, если свойство выводится из type/relation/theory.

## Шаг 5. Добавь tests до/вместе с кодом

Минимум:

- основной case;
- boundary case;
- incorrect/domain case;
- interaction with type/assumption/serialization при необходимости.

## Шаг 6. Проверяй точность claims

Если engine может только не найти counterexample, статус остаётся `Unknown`.
Если normalizer не доказал confluence/canonical form, не превращай совпадение
эвристических форм в proof.

## Шаг 7. Обнови docs только после поведения

При изменении фактической реализации:

1. обнови tests;
2. обнови `IMPLEMENTATION.md` / профильный doc;
3. при необходимости скорректируй `ROADMAP.md`;
4. `SPECIFICATION.md` меняй только если меняется целевая архитектура, а не просто
   состояние реализации.

---

# 25. Частые ошибочные подходы

Не делай следующее:

### 25.1. «В спецификации написано — значит уже работает»

Нет. Specification 0.1 — целевая модель.

### 25.2. «Можно заменить exact decimal на float внутри runtime»

Нет. Exact literal semantics принципиальна; approximation — `ApproxNumber`.

### 25.3. «Unknown удобно трактовать как falsey»

Нет. Это математически другой статус; Python bool conversion intentionally rejected.

### 25.4. «User rewrite можно использовать в proof checker»

Нет, пока для него нет отдельного trusted/proved justification.

### 25.5. «IDE может вычислять по-своему»

Нет. IDE — thin presentation layer над тем же language service/kernel.

### 25.6. «Добавим специальный runtime class для новой алгебры»

Только если generic abstraction недостаточна и есть обоснованная performance
representation с той же semantics. По умолчанию — theory/relation/normalizer/library.

### 25.7. «Finite testing доказывает forall»

Нет. Finite search используется для counterexamples; отсутствие witness не proof.

### 25.8. «TaylorSeries можно автоматически заменить polynomial»

Нет. Remainder semantic; discard только явно через `polynomial`.

### 25.9. «Если integral mathematically exists, backend обязан его принять»

Нет. Backend консервативен и принимает только те cases, для которых может
установить необходимые domain/regularity facts.

---

# 26. Known migrations / compatibility traps

## 26.1. Integration API

С 0.8.2:

```text
antiderivative(expr,x)
integrate(expr,x,a,b)
```

Старый two-argument `integrate(expr,x)` должен получать migration diagnostic.

## 26.2. IR versions

При чтении старых formats:

- v4 introduces definite integration distinction;
- v5 theory/forall;
- v6 theory inheritance;
- v7 ApproxNumber.

Не ломай old-reader/new-reader semantics молча.

## 26.3. Roadmap F1/F2/F3 claims

Не возвращай устаревшее утверждение, что inversion или nilpotent Taylor lift ещё
не начаты. В 0.9.2 они уже существуют в существенном объёме.

---

# 27. Target 1.0

1.0 означает не «вся математика готова», а стабилизацию основного архитектурного
контракта.

Желательная граница:

- Lexer / Parser / AST;
- name resolution;
- Elaborator + Typed IR;
- immutable symbolic DAG;
- substitutions/patterns/rewriting;
- assumptions + three-valued logic;
- theories/axioms/properties;
- checkable theorem/proof objects;
- generic Algebra Engine;
- parameterized/indexed generators;
- standard algebraic theories;
- Vector/Matrix/Polynomial;
- basic + multidimensional calculus;
- modules + versioned serialization;
- unified renderer API;
- CLI/REPL/IDE;
- stable proof-checking trust boundary.

---

# 28. Карта исходных документов

| Файл | Роль |
| --- | --- |
| `README.md` | Краткое описание проекта, версии и реализованных вех. |
| `IMPLEMENTATION.md` | Главный текстовый источник фактического состояния 0.9.2 и текущих ограничений. |
| `SPECIFICATION.md` | Целевая архитектура/язык 0.1; не считать все описанные функции реализованными. |
| `ROADMAP.md` | Оставшаяся последовательность развития и критерии готовности следующих этапов. |
| `LOGIC.md` | Контракт Predicate/TruthValue/Context/assumptions/domain и границы inference. |
| `ITERATION.md` | Semantics finite iteration/folds/factorial, symbolic bounds и budgets. |
| `CALCULUS.md` | Contract antiderivative/integrate/series/symbolic sums и migration 0.8.2. |
| `THEORIES.md` | Theory/implementation/axiom obligations/inheritance/trust boundary 0.9.1. |
| `NUMERIC.md` | Exact-vs-approx contract, `ApproxNumber`, precision и real numeric domain 0.9.2. |
| `IDE.md` | Architecture/stability contract desktop IDE и LanguageService. |

---

# 29. Краткая памятка перед коммитом

Проверь все применимые пункты:

- [ ] Новое поведение соответствует уже существующей семантике или явно меняет её.
- [ ] Нет скрытого float/inexact path.
- [ ] `Unknown` не потерян и не coerced в boolean.
- [ ] Domain guards сохранены.
- [ ] Symbol identities/capture safety сохранены.
- [ ] Typed IR всё ещё отделён от Term DAG.
- [ ] Rewrite не стал trusted axiom.
- [ ] Proof checker не доверяет поиску/serialized status без проверки.
- [ ] Atomic rollback не нарушен.
- [ ] Новый recursive algorithm использует budgets.
- [ ] Serialization совместимость рассмотрена.
- [ ] IDE не дублирует semantics kernel.
- [ ] Добавлены tests для success + failure/boundary.
- [ ] Документация фактического состояния обновлена.

---

# 30. Одно предложение, которое лучше всего описывает архитектуру

**MathLang должен позволять определять математическую структуру один раз как
типизированный набор операций, relations, properties и proofs, а затем использовать
тот же объект для точных символьных вычислений, анализа, проверки утверждений и
визуализации — без специальных семантических веток для каждой конкретной области
математики.**
