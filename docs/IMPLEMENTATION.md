# Состояние реализации MathLang

Версия реализации: **0.9.2**.

Этот документ описывает **фактически работающий код**, а не только целевую
архитектуру из исходной спецификации 0.1. Если формулировка здесь расходится с
архитектурным черновиком или старым roadmap, текущим источником истины является
реализация и тесты репозитория.

## 1. Общая архитектура

Основной путь выполнения:

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

Исходный AST и математический IR разделены. AST хранит синтаксис и позиции в
исходнике; `Term` — математические объекты без source span. `TermFactory`
hash-cons'ит одинаковые структуры и строит общий DAG.

Обычная арифметика не вычисляется автоматически до нормальной формы. MathLang
различает хранение выражения и явное преобразование:

```text
2*x + 3*x            // сохраняется как сумма
2*x + 3*x |> simplify // 5*x
(x+1)^3 |> normalize  // x^3 + 3*x^2 + 3*x + 1
sqrt(2) |> numeric    // ≈1.4142135623730950488
```

## 2. Реализованные подсистемы

| Подсистема | Текущее состояние |
| --- | --- |
| Lexer / parser | Реализованы выражения, программы, блоки, lambda, pipeline, `where`, declarations, algebras, rules, logic, calculus, theories, modules. |
| Symbolic IR | Неизменяемый DAG: числа, символы, операции, вызовы, функции, substitutions, predicates, calculus requests, Taylor series и др. |
| Точная арифметика | `Fraction`; десятичные литералы являются точными рациональными числами. |
| `simplify` | Нейтральные элементы, точная арифметика, сбор подобных членов/множителей, часть функциональных тождеств и assumption-aware сокращения. |
| `normalize` | Полиномиальная нормальная форма для поддерживаемых скаляров и отдельный backend фактор-алгебр. |
| `numeric` | Явное высокоточное численное вычисление закрытых вещественных выражений; отдельный `ApproxNumber`. |
| Rewrite rules | Шаблоны, wildcards, условия, стратегии обхода, repeat и лимиты. |
| Типизация | Scalar tower, `Function`, `Vector`, `Matrix`, nominal algebra types, отдельный Typed IR и явные `Embed`. |
| Логика | `Predicate`, сравнения, `True/False/Unknown`, `and/or/not`, assumptions, `query`, `domain`, `forall`. |
| Алгебры | Конечномерные ассоциативные фактор-алгебры с единицей, relations, basis/derive basis, confluence check. |
| Обращение в алгебрах | Координаты, матрица умножения, determinant/adjugate, inverse, division, negative integer powers. |
| Функции над алгебрами | Точный analytic lift для поддерживаемых нильпотентных/квадратичных случаев: `exp`, `sin`, `cos`, частично `log`, `sqrt`. |
| Proof system | Проверяемые сертификаты равенства и конечномерных свойств; `proved/disproved/unknown`. |
| Calculus | derivative, antiderivative, definite integrate, Taylor series, finite limits. |
| Iterations | iterate, finite sum/product/all/any, factorial, общий бюджет вложенных итераций. |
| Modules | module/import, aliases, selective imports, namespaces, package views. |
| Serialization | Версионированный data-only DAG IR; текущая версия 7, чтение версий 1–6. |
| Theories | Generic theories, operations, constants, axioms, typed forall, implementations, multiple inheritance via `extends`. |
| IDE | Editor, diagnostics, completion, Typed IR, preview, plots, assumptions/properties panels. |

## 3. Выражения, память и функции

Поддерживаются:

```text
const c = 2
parameter a : Real
variable x : Real
unknown y : Real

f = c*x + a
square(t) = t^2
function g(x:Real):Real {
    const y = x*x
    return y + 1
}

h = (x:Real, y:Real) => x+y
```

Различаются:

- исходное имя;
- identity символа;
- lexical scope;
- mathematical term;
- type annotation.

Подстановка сравнивает символы по identity и избегает захвата параметров.
Функции — значения первого класса, допускаются higher-order вызовы и замыкания.

Pipeline:

```text
value |> f
value |> f(a, b)
```

эквивалентен соответственно `f(value)` и `f(value,a,b)`.

## 4. Скалярная нормализация

Скалярная башня:

```text
Nat → Integer → Rational → Real → Complex
```

`Number` всегда точен. Например:

```text
0.125
```

хранится как `1/8`.

`simplify` не обязан раскрывать произведения и степени, тогда как `normalize`
строит полиномиальную форму. Потенциально частичные операции не сокращаются без
доказательства области определения.

```text
variable x : Real

simplify(x/x)        // x/x
assume x != 0
simplify(x/x)        // 1
```

Точное равенство `sqrt(q)` и `q^(1/2)` для положительных рациональных `q`
канонизируется без перехода к floating point.

## 5. Численное вычисление 0.9.2

`numeric` — новый явный backend приближённого вычисления:

```text
sqrt(2) |> numeric
sqrt(2) |> numeric(50)
exp(1) |> numeric(40)
```

По умолчанию используется 20 значащих цифр; допустимо 1–500.

Поддерживаются закрытые вещественные выражения из:

- рациональных чисел;
- `+ - * / ^`;
- `sqrt`, `exp`, `log`, `sin`, `cos`, `tan`, `abs`.

Ядро использует `decimal.Decimal`, а не `float`. Для тригонометрии π считается
алгоритмом Гаусса—Лежандра, затем используются степенные ряды.

Результат имеет отдельный IR-тип `ApproxNumber` и выводится с `≈`:

```text
≈1.4142135623730950488
```

Это принципиально: source literal `1.414...` в MathLang является **точным
рациональным** числом, поэтому приближение нельзя представлять обычным
`Number`.

`ApproxNumber` статически имеет тип `Real`, сериализуется в IR 7 и может быть
сохранён в окружении. Точные normalizer'ы не начинают автоматически выполнять
inexact arithmetic над ним.

Подробнее: [NUMERIC.md](NUMERIC.md).

## 6. Rewrite system

Пользовательские rules отделены от математических аксиом:

```text
rule double {
    t+t -> 2*t
}
```

Поддерживаются:

- literal, unary, binary и call patterns;
- wildcards;
- `when` conditions;
- `once`, `bottom_up`, `top_down`, recursive repetition;
- ограничения на количество проходов, rewrite steps и размер результата.

Rule не становится автоматически теоремой. Proof checker не доверяет
пользовательскому rewrite как аксиоме.

## 7. Конечномерные алгебры

Поддерживается конструкция вида:

```text
algebra D over Real {
    generators {eps}
    relations {eps^2 = 0}
    derive basis
}
```

Backend строит фактор свободной ассоциативной алгебры с центральными
скалярами.

Реализованы:

- несколько generators;
- rational polynomial relations;
- ориентация reductions;
- critical-pair / overlap checks;
- `confluence=known` только после успешной проверки;
- explicit basis и `derive basis`;
- координатное представление элемента;
- exact multiplication in basis coordinates;
- scalar symbolic coefficients.

Текущий backend предполагает ассоциативность и единицу. Неассоциативные
алгебры требуют отдельного normalizer'а.

### 7.1. Координаты и обращение

Ранее roadmap относил эту возможность к F1, но она **уже реализована**.

`AlgebraNormalizer` предоставляет:

```python
coordinates(term)
from_coordinates(coords)
invertibility(term)
function_domain(name, term)
```

Для конечного сертифицированного базиса строится матрица левого умножения.
Determinant и adjugate вычисляются recurrence Faddeev–LeVerrier, что не требует
угадывать символические pivots.

Отсюда реализованы:

- `q^-1`;
- `p/q = p*q^-1`;
- отрицательные целые степени;
- условия обратимости через `domain`;
- некоммутативный порядок множителей;
- проверка обеих сторон найденного inverse.

Пример для dual algebra:

```text
assume c != 0
normalize((a+b*D.eps)/(c+d*D.eps))
```

даёт формулу, эквивалентную

```text
a/c + (b*c-a*d)/c^2*D.eps
```

Механизм не привязан к dual numbers. Тестируется, например, алгебра `n^4=0`,
где обращается `1+n+n^2`, а также quaternion division.

### 7.2. Scalar coefficients

Коэффициенты элемента алгебры проходят отдельный `RationalCoefficients`
backend. Он хранит рациональные функции от центральных скалярных параметров и
не сокращает знаменатель без доказательства его ненулевости.

Скалярные степени, включая `2^(1/2)`, остаются коэффициентами алгебры и не
ошибочно интерпретируются как функциональная степень самого algebra element.

## 8. Analytic lift над алгебрами

`mathlang/analytic_lift.py` реализует часть того, что старый roadmap называл F2
и F3.

### 8.1. Нильпотентные расширения

Если аргумент представим как

```text
a + n
```

и normalizer доказывает `n^m=0`, аналитическая функция вычисляется конечной
Taylor-формулой.

Для `eps^2=0`:

```text
exp(a+b*eps)  = exp(a) + b*exp(a)*eps
sin(a+b*eps)  = sin(a) + b*cos(a)*eps
cos(a+b*eps)  = cos(a) - b*sin(a)*eps
```

Индекс нильпотентности не захардкожен; поддерживаются более высокие степени и
несколько некоммутирующих nilpotent generators, если конечность разложения
можно подтвердить.

### 8.2. `log` и `sqrt`

Для real scalar part используются branch/domain guards. Например при
доказанном `a>0`:

```text
log(a+b*eps)
sqrt(a+b*eps)
```

получают конечные точные формулы.

### 8.3. Квадратичные relations и Euler-type formulas

Распознавание не зависит от имени генератора.

Если пользователь определит:

```text
algebra C over Real {
    generator j
    relation j^2 = -1
    derive basis
}
```

то `exp(j*x)` сводится к выражению через `cos(x)` и `sin(x)`.

Поддерживается и масштабированный случай вроде `r^2=-2`, где возникают
`cos(sqrt(2)*x)` и `sin(sqrt(2)*x)/sqrt(2)`.

Это уже частичная реализация старых F2/F3/F4; однако **общего** functional
calculus по минимальному многочлену пока нет.

## 9. Логика и assumptions

Реализован отдельный `Predicate` IR:

```text
x == y
x === y
x != 0
x >= 0
P and Q
not P
```

Значение запроса:

```text
True | False | Unknown
```

`Unknown` никогда не трактуется как `True`.

Контекст:

```text
assume x >= 0

assuming {
    y != 0
} {
    ...
}
```

`domain(expr)` строит утверждение об определённости. Query engine знает часть
скалярных областей, bounds, algebra invertibility и guards analytic lift.

Общего SMT/CAS inequality solver нет.

## 10. Типизация и Typed IR

`Elaborator` работает отдельно от вычислительного DAG.

Реализованы:

- scalar tower;
- `Function<...>`;
- `Vector<T,n>`;
- `Matrix<T,m,n>`;
- nominal algebra types;
- contextual specialization functions;
- explicit `Embed<Source,Target>` в Typed IR;
- проверки function arguments / returns;
- dimensional errors до вычисления.

Неаннотированные функции могут временно иметь неизвестный тип; это намеренная
граница текущей реализации, а не полноценная dependent type system.

## 11. Calculus

Реализованы:

```text
derivative(expr, x)
derivative(expr, x, order=n)
antiderivative(expr, x)
integrate(expr, x, a, b)
series(expr, x=point, order=n)
limit(expr, x -> point)
```

Calculus requests являются отдельными IR-узлами и могут использоваться через
pipeline.

Derivative поддерживает арифметику и основные elementary functions.
Antiderivative реализован для поддерживаемых polynomial/affine elementary
классов. Definite integration проверяет regularity на интервале и применяет
Ньютон—Лейбниц там, где backend может доказать корректность.

Taylor series — отдельный `TaylorSeries`, который хранит остаток `O(...)`.
Чтобы намеренно отбросить остаток, нужен:

```text
series(...) |> polynomial
```

После получения закрытого точного результата можно явно вызвать `numeric`.

Не реализованы в общем виде:

- improper integrals;
- infinite/one-sided limits;
- Laurent series;
- general symbolic integration;
- multivariable gradient/jacobian/hessian;
- complex contour calculus.

## 12. Конечные итерации

Поддерживаются:

```text
iterate
sum
product
all
any
factorial
```

Есть lambda/binder form и общий `max_iterations` budget, включая вложенные
итерации. Символические finite sums могут сохраняться отложенно, когда
вычисление невозможно или не требуется.

Бесконечные свёртки и общий convergence prover не реализованы.

## 13. Proof objects

`prove` для поддерживаемых задач возвращает `ProofResult`, а не boolean.

Статусы:

```text
proved
disproved
unknown
```

Успешный result содержит proof certificate. При загрузке сертификат
проверяется независимо: нормальные формы и algebra presentation пересчитываются.

Реализованы:

- equality proofs через нормальные формы;
- finite-basis associativity/commutativity checks;
- concrete counterexamples;
- сохранение и независимая проверка proof DAG.

Не реализованы:

- общий tactic language;
- proof blocks;
- использование произвольных пользовательских axioms как trusted rules;
- conditional proof certificates с локальным assumption context;
- dependent proof terms.

## 14. Theory system

Реализован DSL:

```text
theory Monoid<T> {
    operation (*) : T x T -> T
    const identity : T
    axiom associative { ... }
}

implementation Add implements Monoid<Real> {
    ...
}
```

0.9.1 добавила:

```text
theory Child<T> extends Parent<T>, Other<T> { ... }
```

Реализованы:

- generic type parameters;
- named/operator operations;
- constants;
- typed `forall`;
- axioms;
- implementations;
- `assume` для недоказанного obligation;
- statuses `proved/disproved/unknown/assumed`;
- multiple inheritance;
- merge совместимых parent contracts;
- conflict diagnostics;
- preservation of parent specialization in IR.

Theory system пока не является полноценной системой зависимых типов.

## 15. Modules и standard library

Реализованы:

```text
module name
import foo
import foo {A, B}
import foo as bar
namespace N { ... }
with N { ... }
use N
```

Модуль загружается в изолированном окружении. Cache принадлежит `Session`.
Ошибки программы откатывают definitions, module cache, algebra registry и
контекст assumptions атомарно.

Стандартная библиотека содержит core, analysis, theories и примеры алгебр
(Complex, Dual, Quaternion и др.).

## 16. Serialization

Формат — data-only JSON DAG `mathlang-ir`; Python code не сериализуется.

Текущая версия: **7**.

Совместимость:

- читаются IR 1–6;
- v4 различает antiderivative/definite integrate;
- v5 содержит theory/forall;
- v6 содержит theory parents;
- v7 добавляет `ApproxNumber`.

При загрузке проверяются:

- tags и типы полей;
- identities builtins;
- graph references;
- resource limits;
- algebra presentations;
- proof certificates;
- theory inheritance and obligations.

## 17. IDE

IDE не является частью trusted mathematical kernel, но использует тот же parser,
Session и renderer.

Реализованы:

- syntax highlighting;
- completion;
- diagnostics;
- run buffer/file;
- mathematical preview;
- zoom/pan preview infrastructure;
- plot для поддерживаемых вещественных выражений;
- Typed IR view;
- Assumptions panel;
- Properties panel;
- theory inheritance display.

0.9.2 добавляет `numeric` в builtin highlighting и `ApproxNumber` в LaTeX
preview как `\approx`.

## 18. Что в старой документации было неверно

До 0.9.2 `IMPLEMENTATION.md` и `ROADMAP.md` заметно отставали от кода.
Исправлены следующие утверждения:

1. **F1 не является будущей задачей.** Координаты, inversion, division и
   negative powers уже реализованы.
2. **F2 уже частично/существенно реализован.** Есть общий nilpotent Taylor lift,
   не привязанный к Dual по имени.
3. **Euler-type reduction уже реализована частично.** Она выводится из relation
   `j^2=-c`, а не из имени `i`.
4. Реальный код содержит `analytic_lift.py`, которого старая сводка почти не
   учитывала.
5. Количество тестов в старом документе было зафиксировано на 389 и больше не
   отражало tree.
6. Real теперь имеет **явный** approximate backend через `numeric`; при этом
   exact symbolic semantics не изменена.

## 19. Основные границы текущего языка

Пока нет:

- general dependent type theory;
- arbitrary theorem prover / tactics;
- existential quantifier as a general proof mechanism;
- general equation solver;
- generic Groebner basis completion;
- arbitrary nonassociative algebra backend;
- general matrix/vector runtime arithmetic;
- general functional calculus from minimal polynomials;
- formal infinite power-series proof engine;
- automatic convergence proofs;
- general complex numerical backend for `numeric`;
- interval/ball arithmetic and certified numerical error bounds;
- Laurent/residue/contour integration engine.

Эти пункты не следует смешивать с уже работающими конечномерными algebra и
calculus capabilities.

## 20. Проверка реализации

Основным executable contract остаётся каталог `tests/`. В текущем tree
обнаруживается **423 теста в 27 test-модулях**. Все 27 модулей проходят при
независимом запуске; это также позволяет локализовать долгие GUI/CLI проверки в
ограниченной среде.

Обычная команда полного запуска:

```powershell
python -m unittest discover -s tests
```

Новые проверки 0.9.2 находятся в `tests/test_numeric.py` и покрывают:

- default precision;
- explicit precision;
- `sqrt`, `exp`, `sin`, `cos`, `tan`;
- pipeline после substitution/calculus;
- ошибки domain/open expressions;
- хранение `ApproxNumber`;
- serialization round-trip.

Roadmap теперь должен трактоваться как список **оставшихся** архитектурных
задач, а не как описание отсутствующего функционала, который уже существует в
исходниках.
