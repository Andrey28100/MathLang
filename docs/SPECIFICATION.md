# Спецификация математического языка

**Статус:** черновая архитектурная спецификация  
**Версия:** 0.1

---

# 1. Назначение языка

Язык предназначен для символьной математики, определения математических структур и вычислений внутри пользовательских алгебраических теорий.

Основная идея языка состоит не в том, чтобы заранее встроить как можно больше математических объектов, а в том, чтобы предоставить универсальный механизм определения новых объектов через:

- типы;
- операции;
- генераторы;
- отношения;
- аксиомы;
- правила переписывания;
- нормальные формы;
- доказательства.

На основе этого механизма стандартная библиотека может реализовывать:

- натуральные, целые, рациональные, вещественные и комплексные числа;
- многочлены;
- матрицы;
- векторы;
- кватернионы;
- алгебры Клиффорда;
- тензоры;
- конечные поля;
- группы, кольца, поля и алгебры;
- функциональные пространства;
- операторы математического анализа;
- пользовательские алгебраические конструкции.

Язык должен находиться между классическими CAS и proof assistant:

\[
\boxed{
\text{Symbolic CAS}
+
\text{Algebra definitions}
+
\text{Proof system}
}
\]

---

# 2. Основные принципы

## 2.1. Математические объекты являются объектами языка

Матрица, функция, алгебра, оператор, теорема и доказательство должны иметь собственные типы и внутренние представления.

Например:

```text
x : Real
A : Matrix<Real, 3, 3>
f : Function<Real, Real>
H : Algebra
T : Theorem
```

---

## 2.2. Пользователь может определять новые математические структуры

Например:

```text
algebra Complex over Real {
    generator i

    relation {
        i^2 = -1
    }
}
```

Ядро языка не обязано знать специальный класс `ComplexNumber`.

Вместо этого комплексные числа могут рассматриваться как фактор-алгебра

\[
\mathbb R[i]/(i^2+1).
\]

---

## 2.3. Символьное вычисление основано на нормализации

Центральная операция:

```text
normalize(expr)
```

или

```text
expr |> normalize
```

Для каждого математического пространства может существовать собственный алгоритм нормализации.

Например:

```text
with Complex {
    normalize((1 + i)^2)
}
```

даёт

```text
2i
```

---

## 2.4. Вычисление и доказательство связаны

Если две стороны равенства приводятся к одной нормальной форме, это может использоваться как доказательство.

```text
prove (i + i)^2 = -4
```

Система может получить:

```text
Proof succeeded.

Method:
    normalization

Left normal form:
    -4

Right normal form:
    -4
```

---

# 3. Уровни реализации языка

Исходный код проходит следующие стадии:

```text
Source
   ↓
Lexer
   ↓
Parser
   ↓
AST
   ↓
Name Resolution
   ↓
Elaboration
   ↓
Typed IR
   ↓
Symbolic Kernel
   ↓
Normalization / Evaluation / Proof
```

Необходимо принципиально отделять синтаксическое дерево от внутреннего математического представления.

---

# 4. Лексическая структура

## 4.1. Идентификаторы

Разрешены обычные идентификаторы:

```text
x
matrix
Complex
quaternion_norm
```

и Unicode:

```text
α
β
ε
ψ
Δ
```

Также редактор языка может поддерживать LaTeX-подобный ввод:

```text
\alpha
```

с автоматическим преобразованием в:

```text
α
```

---

## 4.2. Математические сокращения

Дополнительно допускается:

```text
$alpha
$beta
$epsilon
$infty
$partial
```

Редактор может визуально представлять их как

\[
\alpha,\beta,\varepsilon,\infty,\partial.
\]

На уровне AST это обычные идентификаторы или системные символы.

---

## 4.3. Комментарии

```text
// однострочный комментарий
```

и

```text
/*
    многострочный
    комментарий
*/
```

---

# 5. Система символов

Язык различает несколько категорий символических величин.

## Константа

```text
const c = 2
```

Объект считается известным и неизменяемым.

---

## Параметр

```text
parameter a : Real
```

Параметр является фиксированной, но символически неизвестной величиной.

Например:

```text
parameter a : Real
variable x : Real

f(x) = exp(a*x)
```

При дифференцировании по `x` значение `a` считается постоянным.

---

## Переменная

```text
variable x : Real
```

Переменная является аргументом математического выражения.

---

## Неизвестная

```text
unknown x : Real
```

Неизвестная предназначена для решения уравнений и систем.

```text
solve {
    x^2 - 2 = 0
}
```

---

# 6. Типовая система

Язык должен иметь строгую математическую типизацию.

Примеры:

```text
n : Nat
z : Integer
q : Rational
x : Real
c : Complex
```

Составные типы:

```text
Vector<Real, 3>
Matrix<Real, 3, 3>
Function<Real, Real>
Polynomial<Real, x>
```

---

# 7. Автоматические вложения

Допускаются безопасные математические вложения:

\[
\mathbb N
\hookrightarrow
\mathbb Z
\hookrightarrow
\mathbb Q
\hookrightarrow
\mathbb R
\hookrightarrow
\mathbb C.
\]

Поэтому:

```text
1 + complex_value
```

является корректным выражением.

Но выражение

```text
matrix + quaternion
```

должно быть ошибкой, если соответствующее преобразование явно не определено.

---

# 8. Функции

Обычное определение:

```text
function f(x : Real) : Real {
    return x^2 + 1
}
```

Сокращённая математическая форма:

```text
f(x) = x^2 + 1
```

Lambda-выражение:

```text
f = x => x^2 + 1
```

---

# 9. Функции как объекты первого класса

Функции можно передавать другим функциям:

```text
D = derivative(x)

f = x => x^2
g = D(f)
```

Оператор производной имеет тип примерно

\[
D:
\operatorname{Function}(R,R)
\to
\operatorname{Function}(R,R).
\]

---

# 10. Pipeline

Для последовательного применения математических преобразований используется оператор:

```text
|>
```

Например:

```text
sin(x)
    |> derivative(x)
    |> substitute(x = 0)
    |> simplify
```

или:

```text
exp(x)
    |> series(x = 0, order = 8)
    |> integrate(x)
    |> simplify
```

Pipeline:

```text
value |> f(args)
```

эквивалентен:

```text
f(value, args)
```

если функция поддерживает pipeline-вызов.

---

# 11. Математический анализ

Базовая стандартная библиотека должна предоставлять:

```text
derivative(expr, x)
derivative(expr, x, order = n)

integrate(expr, x)

limit(expr, x -> a)

series(expr, x = a, order = n)

gradient(expr, vars)

jacobian(expr, vars)

hessian(expr, vars)
```

Сокращённая запись может поддерживаться отдельно:

```text
D[x] f
D[x, 2] f

Int[x] f

Lim[x -> 0] f

Series[x -> 0, 10] f
```

---

# 12. Подстановка

Подстановка является фундаментальной операцией языка.

```text
substitute(expr, x = 2)
```

Сокращение:

```text
expr where x = 2
```

Несколько подстановок:

```text
expr where {
    x = t^2
    a = sin(t)
}
```

---

# 13. Теории

`theory` описывает абстрактную математическую структуру.

Например:

```text
theory Semigroup<T> {
    operation (*) : T × T -> T

    axiom associative {
        forall a, b, c : T:
            (a*b)*c = a*(b*c)
    }
}
```

---

# 14. Кольцо

```text
theory Ring<T> {
    operation (+) : T × T -> T
    operation (*) : T × T -> T
    operation (-) : T -> T

    const zero : T
    const one : T

    axiom add_associative
    axiom add_commutative

    axiom mul_associative

    axiom distributive

    axiom additive_identity
    axiom additive_inverse
}
```

Конкретная структура может объявлять:

```text
algebra A implements Ring<A> {
    ...
}
```

---

# 15. Алгебры

Основной синтаксис:

```text
algebra Name over ScalarDomain {
    ...
}
```

Пример:

```text
algebra Complex over Real {
    generator i

    relation {
        i^2 = -1
    }

    basis {
        1,
        i
    }

    multiplication bilinear
}
```

---

# 16. Генераторы

Одиночный генератор:

```text
generator i
```

Несколько:

```text
generators i, j, k
```

Параметрическое семейство:

```text
generator e[i] for i in 1..n
```

Многомерное семейство:

```text
generator E[i, j]
    for i in 1..n
    for j in 1..n
```

---

# 17. Relations

`relation` определяет отношения, по которым строится алгебра.

```text
relation {
    i^2 = -1
}
```

Несколько отношений:

```text
relation {
    i^2 = -1
    j^2 = -1

    i*j = k
    j*i = -k
}
```

Условные отношения:

```text
relation {
    e[i] * e[j] = -e[j] * e[i]
        when i != j
}
```

Relation концептуально является математическим равенством, а не направленным правилом замены.

---

# 18. Rewrite rules

Для явного задания направления преобразования существует отдельная конструкция:

```text
rewrite {
    sin(0) -> 0
    x + 0 -> x
}
```

Это отличается от:

```text
relation x + 0 = x
```

`relation` является математическим отношением.

`rewrite` является вычислительным правилом.

---

# 19. Базис

Явное определение:

```text
basis {
    1,
    i,
    j,
    k
}
```

Запрос автоматического построения:

```text
derive basis
```

Проверяемое утверждение:

```text
assert basis {
    1,
    i,
    j,
    k
}
```

---

# 20. Билинейность

Для алгебр особенно важна конструкция:

```text
multiplication bilinear
```

Она сообщает системе:

\[
(a+b)c=ac+bc,
\]

\[
a(b+c)=ab+ac,
\]

\[
(\lambda a)b=\lambda(ab),
\]

\[
a(\lambda b)=\lambda(ab).
\]

Билинейность используется как нормализатором, так и системой доказательств.

---

# 21. Комплексные числа

```text
algebra Complex over Real {
    generator i

    relation {
        i^2 = -1
    }

    basis {
        1,
        i
    }

    multiplication bilinear
}
```

Использование:

```text
with Complex {
    x = (1 + i)^2

    print(x)
    print(normalize(x))
}
```

Результат:

```text
(1 + i)^2
2i
```

---

# 22. Кватернионы

```text
algebra Quaternion over Real {
    generators i, j, k

    relation {
        i^2 = -1
        j^2 = -1
        k^2 = -1

        i*j = k
        j*k = i
        k*i = j

        j*i = -k
        k*j = -i
        i*k = -j
    }

    basis {
        1,
        i,
        j,
        k
    }

    multiplication bilinear

    prove multiplication associative
}
```

---

# 23. Автоматическое доказательство ассоциативности

Если известны:

1. конечный базис;
2. билинейность умножения;

то система может свести

\[
(ab)c=a(bc)
\]

к проверке базисных элементов:

\[
(e_i e_j)e_k=e_i(e_j e_k).
\]

Для базиса размерности \(n\) требуется не более

\[
n^3
\]

базисных проверок.

Для кватернионов:

\[
4^3=64.
\]

---

# 24. Алгебра Клиффорда

```text
algebra Clifford(p : Nat, q : Nat) over Real {
    generator e[i] for i in 1..p+q

    relation {
        e[i] * e[j] =
            -e[j] * e[i]
            when i != j

        e[i]^2 = 1
            when i <= p

        e[i]^2 = -1
            when i > p
    }

    multiplication bilinear

    derive basis
}
```

Нормализатор должен приводить произведения генераторов к упорядоченной форме:

\[
e_{i_1}e_{i_2}\cdots e_{i_k},
\qquad
i_1<i_2<\ldots<i_k.
\]

---

# 25. Матричная алгебра

Можно определить матрицы через матричные единицы.

```text
algebra MatrixAlgebra(n : Nat, K : Field) over K {
    generator E[i, j]
        for i in 1..n
        for j in 1..n

    relation {
        E[i,j] * E[k,l]
            =
        delta(j,k) * E[i,l]
    }

    multiplication bilinear
}
```

Матрица

\[
A=(a_{ij})
\]

представляется как

\[
A=\sum_{i,j}a_{ij}E_{ij}.
\]

В практической реализации стандартная библиотека может использовать более эффективное внутреннее представление.

---

# 26. Контексты

Для выполнения выражений внутри структуры используется:

```text
with Complex {
    print(i * (i + i))
}
```

или:

```text
with Quaternion {
    print(i*j)
}
```

`with` временно изменяет namespace и правила нормализации.

---

# 27. Модули

Файл может объявлять модуль:

```text
module geometry
```

Другой файл:

```text
import geometry
```

Допускается выборочный импорт:

```text
import geometry {
    Vector
    Matrix
    dot
}
```

Алиасы:

```text
import linear_algebra as la
```

---

# 28. Environment

Компилятор поддерживает структуру окружений.

Пример:

```text
GlobalEnvironment
    Builtins
    StandardLibrary
    ImportedModules
    CurrentModule
    LocalScope
```

Environment содержит декларации, а не состояние выполнения программы.

---

# 29. Области видимости

Пример:

```text
parameter a : Real

function f(x : Real) {
    variable t : Real

    ...
}
```

`t` существует только внутри `f`.

---

# 30. Namespace

Алгебры, теории и модули являются пространствами имён.

```text
Complex.i
Quaternion.i
```

Поэтому одинаковые имена генераторов не конфликтуют.

---

# 31. AST

Parser строит только синтаксическую структуру.

Например:

```text
i * (i + i)
```

может стать:

```text
BinaryExpr(
    op = "*",
    left = Identifier("i"),
    right = BinaryExpr(
        op = "+",
        left = Identifier("i"),
        right = Identifier("i")
    )
)
```

AST ещё не знает, что `i` является генератором комплексной алгебры.

---

# 32. Elaboration

После parsing выполняется elaboration.

Elaborator:

- разрешает имена;
- определяет типы;
- вставляет неявные преобразования;
- разрешает перегрузку операторов;
- связывает символы с математическими структурами.

AST:

```text
Identifier("i")
```

становится IR:

```text
AlgebraGenerator(
    algebra = Complex,
    id = Complex.i
)
```

---

# 33. Typed IR

После elaboration любое выражение должно иметь известный математический тип.

Пример:

```text
Add(
    RealLiteral(1),
    ComplexGenerator(i)
)
```

может быть преобразован в:

```text
Add(
    Embed<Real, Complex>(1),
    ComplexGenerator(i)
)
```

с типом:

```text
Complex
```

---

# 34. Внутреннее представление выражений

Рекомендуется использовать immutable DAG.

Например:

\[
(x+1)^2+\sin(x+1)
\]

хранится как:

```text
t1 = Add(x, 1)

t2 = Pow(t1, 2)
t3 = Sin(t1)

result = Add(t2, t3)
```

Один узел `x + 1` используется два раза.

---

# 35. Hash-consing

Каждый immutable-терм может иметь structural hash.

Тогда два одинаковых выражения:

```text
x + 1
```

могут физически ссылаться на один объект.

Это позволяет эффективно выполнять:

- equality checks;
- memoization;
- simplification;
- rewriting;
- caching.

---

# 36. Symbolic Kernel

Ядро должно отвечать только за фундаментальные операции:

```text
Term
Type
Symbol
Substitution
Pattern
Matcher
RewriteRule
Normalizer
Assumption
Proof
```

Математический анализ и конкретные алгебры располагаются выше этого уровня.

---

# 37. Нормальные формы

Каждый математический домен может зарегистрировать свой normalizer.

Примеры:

```text
PolynomialNormalizer
RationalFunctionNormalizer
ComplexNormalizer
QuaternionNormalizer
CliffordNormalizer
MatrixNormalizer
```

Вызов:

```text
normalize(expr)
```

диспетчеризируется по типу выражения.

---

# 38. Simplify и Normalize

Эти операции следует различать.

`normalize` стремится получить каноническую форму.

```text
normalize((i + 1)^2)
```

может вернуть:

```text
2i
```

`simplify` пытается сделать выражение удобнее:

```text
simplify(sin(x)^2 + cos(x)^2)
```

может вернуть:

```text
1
```

Не каждое упрощение является переходом к единственной канонической форме.

---

# 39. Равенство

Следует различать несколько типов равенства.

Структурное:

```text
a === b
```

проверяет идентичность термов.

Математическое:

```text
a == b
```

пытается определить математическую эквивалентность.

Например:

```text
x + x === 2*x
```

может быть `false`.

Но:

```text
x + x == 2*x
```

может быть `true`.

---

# 40. Трёхзначная логика доказуемости

Для символических утверждений полезно использовать:

```text
True
False
Unknown
```

Например:

```text
parameter x : Real

x > 0
```

даёт:

```text
Unknown
```

После:

```text
assume x > 0
```

получаем:

```text
True
```

---

# 41. Assumptions

```text
assume x > 0
assume n : Integer
assume n != 0
```

Допускаются блоки:

```text
assuming {
    x > 0
    y > 0
} {
    simplify(sqrt(x^2))
}
```

Результат:

```text
x
```

---

# 42. Axiom

Аксиома считается истинной без доказательства.

```text
axiom commutativity {
    forall a, b:
        a*b = b*a
}
```

Использование аксиом должно фиксироваться в proof object.

---

# 43. Theorem

```text
theorem square_nonnegative {
    forall x : Real:
        x^2 >= 0
}
```

С доказательством:

```text
theorem square_nonnegative {
    forall x : Real:
        x^2 >= 0

    proof {
        ...
    }
}
```

---

# 44. Prove

Интерактивный запрос:

```text
prove (i + j)^2 = -2
```

Результат должен быть объектом `ProofResult`, а не простым boolean.

Пример:

```text
ProofResult {
    status: proved

    theorem:
        (i + j)^2 = -2

    method:
        normalization
}
```

---

# 45. Proof Object

Доказательство хранится как дерево.

Например:

```text
Proof {
    goal: (i + j)^2 = -2

    steps: [
        expand_bilinearity,
        rewrite(i*i, -1),
        rewrite(i*j, k),
        rewrite(j*i, -k),
        rewrite(j*j, -1),
        collect_terms
    ]
}
```

---

# 46. Проверяемые доказательства

Желательно разделить:

```text
ProofSearch
```

и

```text
ProofChecker
```

`ProofSearch` может быть сложным и эвристическим.

`ProofChecker` должен быть маленьким и строгим.

Тогда найденное доказательство можно независимо проверить.

---

# 47. Pattern Matching

Язык должен иметь внутреннюю систему шаблонов.

Например:

```text
pattern x + 0
```

может соответствовать:

```text
a + 0
sin(t) + 0
matrix + 0
```

---

# 48. Пользовательские правила

```text
rule double_angle {
    sin(2*x)
        -> 2*sin(x)*cos(x)
}
```

Условные правила:

```text
rule sqrt_square {
    sqrt(x^2)
        -> x
    when x >= 0
}
```

---

# 49. Стратегии переписывания

В будущем:

```text
rewrite expr using rule
```

```text
rewrite expr using ruleset
```

```text
rewrite expr recursively
```

```text
rewrite expr bottom_up
```

```text
rewrite expr top_down
```

---

# 50. Проблема завершимости

Язык не должен предполагать, что произвольная система правил всегда имеет единственную нормальную форму.

Следует отслеживать:

```text
termination: known / unknown
confluence: known / unknown
```

Если система потенциально зацикливается, нормализатор должен иметь защиту.

---

# 51. Gröbner-подобные backend'ы

В дальнейшем различные классы алгебр могут использовать специальные алгоритмы.

Коммутативные полиномиальные алгебры:

```text
GroebnerBasisNormalizer
```

Некоммутативные алгебры:

```text
NoncommutativeGroebnerNormalizer
```

или методы Gröbner–Shirshov.

Системы переписывания:

```text
KnuthBendixCompletion
```

---

# 52. Traits / Properties

Математические свойства должны быть доступны системе как декларации.

Например:

```text
property addition.commutative
property multiplication.associative
property multiplication.commutative
property multiplication.bilinear
```

---

# 53. Проверенные и предполагаемые свойства

Полезно различать:

```text
assume multiplication associative
```

и:

```text
prove multiplication associative
```

После второго система хранит подтверждённый theorem.

---

# 54. Метаданные свойства

Пример:

```text
property multiplication.associative {
    status = proved
    proof = Quaternion.associativity_proof
}
```

Это позволяет другим алгоритмам безопасно использовать ассоциативность.

---

# 55. Перегрузка операторов

Операторы не должны быть жёстко привязаны к встроенным числам.

Например:

```text
operation (*) : H × H -> H
```

Для матриц:

```text
operation (*) :
    Matrix<K,m,n> × Matrix<K,n,p>
    ->
    Matrix<K,m,p>
```

---

# 56. Пользовательские операторы

В дальнейшем можно разрешить:

```text
operator infix "∘" precedence 70
```

с реализацией:

```text
operation (∘)(f, g) = compose(f, g)
```

---

# 57. Композиционная алгебра функций

Пример пользовательской структуры:

```text
theory CompositionAlgebra<F> {
    operation (∘) : F × F -> F

    identity I

    axiom identity {
        forall f:
            f ∘ I = f
            I ∘ f = f
    }

    axiom associative {
        forall f, g, h:
            (f ∘ g) ∘ h =
            f ∘ (g ∘ h)
    }
}
```

Композиционные степени:

```text
f ^∘ 2
```

или альтернативный синтаксис:

```text
compose_power(f, 2)
```

---

# 58. Вывод

```text
print(expr)
```

Для математических объектов должны поддерживаться разные renderers:

```text
print(expr)
print(expr, format = plain)
print(expr, format = unicode)
print(expr, format = latex)
```

---

# 59. Pretty Printer

Внутренний терм:

```text
Mul(
    Rational(1,2),
    Pow(x, 2)
)
```

может выводиться как:

```text
x² / 2
```

или LaTeX:

```latex
\frac{x^2}{2}
```

---

# 60. REPL

Язык должен иметь интерактивную оболочку.

Например:

```text
>>> parameter x : Real

>>> f = sin(x)^2 + cos(x)^2

>>> simplify(f)
1
```

Алгебры:

```text
>>> use Quaternion

>>> i*j
k

>>> j*i
-k
```

---

# 61. Диагностика ошибок

Ошибки должны быть математически информативными.

Плохо:

```text
Type mismatch.
```

Лучше:

```text
Cannot multiply:

    Matrix<Real, 3, 2>
by
    Matrix<Real, 4, 4>

Matrix multiplication requires:
    left.columns = right.rows

Found:
    2 != 4
```

---

# 62. Ошибки нормализации

Например:

```text
Cannot derive a canonical normal form.

Reason:
    rewrite system is not known to be confluent.

Conflicting reductions:

    a*b*c
      -> ...
      -> X

and

    a*b*c
      -> ...
      -> Y
```

---

# 63. Стандартная библиотека

Предварительная структура:

```text
std.core
std.logic
std.numbers

std.algebra
std.algebra.groups
std.algebra.rings
std.algebra.fields

std.linear
std.matrix

std.polynomial

std.complex
std.quaternion
std.clifford

std.analysis
std.analysis.calculus
std.analysis.series

std.proof
```

---

# 64. Архитектура реализации

Рекомендуемая структура проекта:

```text
lexer/
parser/

ast/

resolver/
types/
elaborator/

ir/

kernel/
    terms/
    symbols/
    substitution/
    matching/
    rewriting/
    assumptions/

normalization/

algebra/

analysis/

proof/
    search/
    checker/

modules/

stdlib/

renderer/

repl/
```

---

# 65. Главные внутренние интерфейсы

Концептуально:

```text
interface Term

interface Type

interface Normalizer {
    normalize(term, context) -> Term
}

interface Simplifier {
    simplify(term, context) -> Term
}

interface ProofStrategy {
    prove(goal, context) -> ProofResult
}
```

---

# 66. Algebra Definition IR

После elaboration:

```text
AlgebraDefinition {
    name

    scalar_domain

    parameters

    generators

    relations

    axioms

    basis

    properties

    normalizer
}
```

---

# 67. Relation IR

```text
Relation {
    lhs : Term
    rhs : Term
    conditions : [Predicate]
}
```

Например:

```text
e[i] * e[j] = -e[j] * e[i]
when i != j
```

---

# 68. Rewrite IR

```text
RewriteRule {
    pattern
    replacement
    condition
    priority
}
```

---

# 69. Context

```text
Context {
    environment
    assumptions
    active_theories
    active_algebras
    rewrite_rules
}
```

---

# 70. Первая реализация

Для первого прототипа не следует пытаться реализовать весь язык.

Минимальное ядро должно поддерживать:

```text
integer/rational literals

symbols

+
-
*
/
^

functions

variables
parameters

algebra
generator
relation
basis

with

normalize
simplify

prove equality
```

---

# 71. MVP 1 — Expression Engine

Первый этап:

```text
2*x + 3*x
```

должен превращаться в:

```text
5*x
```

Необходимы:

```text
AST
IR
Symbol
Add
Mul
Pow
FunctionCall
Substitution
```

---

# 72. MVP 2 — Rewrite Engine

Поддержать:

```text
rule {
    x + 0 -> x
}
```

Необходимы:

```text
Pattern
Wildcard
Matcher
RewriteRule
RewriteStrategy
```

---

# 73. MVP 3 — Algebra Engine

Поддержать:

```text
algebra Complex over Real {
    generator i
    relation i^2 = -1
    basis {1, i}
}
```

После чего:

```text
with Complex {
    normalize((1+i)^4)
}
```

должно вычисляться автоматически.

---

# 74. MVP 4 — Finite-dimensional proofs

Реализовать доказательства:

```text
prove multiplication associative
prove multiplication commutative
```

для конечномерных билинейных алгебр.

---

# 75. MVP 5 — Mathematical Analysis

Добавить:

```text
derivative
series
limit
integrate
```

Первой следует реализовывать производную, поскольку она в основном требует локальных правил переписывания.

---

# 76. MVP 6 — Module System

Реализовать:

```text
module
import
namespace
with
```

и сериализацию скомпилированного IR.

---

# 77. MVP 7 — Proof Objects

Каждое успешное доказательство должно возвращать проверяемый proof tree.

---

# 78. Полный пример программы

```text
module examples.quaternions

import std.algebra
import std.analysis

algebra H over Real {
    generators i, j, k

    relation {
        i^2 = -1
        j^2 = -1
        k^2 = -1

        i*j = k
        j*k = i
        k*i = j

        j*i = -k
        k*j = -i
        i*k = -j
    }

    basis {
        1,
        i,
        j,
        k
    }

    multiplication bilinear

    prove multiplication associative
}

with H {
    q = 1 + 2*i + 3*j + 4*k

    print(q*q)

    prove {
        (i + j)^2 = -2
    }
}
```

---

# 79. Пример с анализом

```text
module examples.analysis

parameter a : Real
variable x : Real

f(x) = exp(a*x) * sin(x)

df =
    f
    |> derivative(x)
    |> simplify

print(df)

taylor =
    f
    |> series(x = 0, order = 6)

print(taylor)
```

---

# 80. Пример собственной математической структуры

```text
theory Monoid<T> {
    operation (*) : T × T -> T

    const identity : T

    axiom associative {
        forall a, b, c : T:
            (a*b)*c = a*(b*c)
    }

    axiom identity_rule {
        forall a : T:
            identity*a = a
            a*identity = a
    }
}
```

Пользовательские структуры затем могут реализовывать эту теорию.

---

# 81. Главная архитектурная граница

Ядро языка не должно знать о:

```text
Quaternion
CliffordAlgebra
Complex
Matrix
Polynomial
```

как о специальных синтаксических объектах.

Ядро должно знать только:

```text
Term
Symbol
Type
Operation
Theory
Relation
Rewrite
Normalizer
Proof
Context
```

Конкретная математика должна по возможности реализовываться поверх этого интерфейса.

---

# 82. Исключение для производительности

Стандартная библиотека может иметь оптимизированные backend'ы.

Например, пользовательская:

```text
MatrixAlgebra
```

семантически определяется через общую систему алгебр, но runtime может использовать специализированное хранение массивов.

То есть необходимо разделять:

\[
\text{семантику}
\]

и

\[
\text{представление}.
\]

Два объекта могут иметь одинаковую математическую семантику, но разное внутреннее представление.

---

# 83. Главная концепция языка

Минимальное математическое ядро можно выразить формулой:

\[
\boxed{
\text{Language}
=
\text{Terms}
+
\text{Types}
+
\text{Theories}
+
\text{Rewriting}
+
\text{Normalization}
+
\text{Proofs}
}
\]

Все остальные возможности должны по возможности строиться как библиотеки поверх этого ядра.

---

# 84. Приоритеты разработки

Наиболее важный принцип при реализации:

**сначала корректная внутренняя математическая модель, затем удобный синтаксис.**

Лучше сначала иметь:

```text
AlgebraDefinition(...)
```

которое работает правильно,

и только затем добавить красивую запись:

```text
algebra H over Real {
    ...
}
```

То же относится к математическим символам, Unicode, pipeline и сокращённому синтаксису.

---

# 85. Целевая модель языка

В завершённом виде язык должен позволять написать математическое определение почти так же, как оно записывается в статье:

```text
algebra A over K {
    generators x, y

    relation {
        x*y - y*x = 1
    }
}
```

после чего непосредственно выполнять:

```text
with A {
    normalize(y*x^3)

    prove {
        y*x^3 =
        x^3*y - 3*x^2
    }
}
```

Таким образом, один и тот же объект используется одновременно для:

- математического определения;
- символьных вычислений;
- исследования структуры;
- проверки утверждений;
- автоматического доказательства теорем.

Это является основной идеей языка.