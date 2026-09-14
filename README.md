# mathlang — математический язык для символьных вычислений и доказательств

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-0.9.2-green.svg)](pyproject.toml)

**mathlang** — это прототип математического языка программирования на Python, предназначенный для символьных вычислений, формальных доказательств и интерактивного исследования математики.

## ✨ Возможности

### Ядро языка
- **Символьные выражения** — хранение и манипулирование математическими формулами
- **Точная арифметика** — рациональные числа, алгебраические расширения
- **Упрощение и нормализация** — полиномиальная нормализация, правила переписывания
- **Подстановка** — замена переменных и выражений

### Алгебра
- **Пользовательские фактор-алгебры** — определение алгебр через образующие и соотношения
- **Пространства имён** — изолированные контексты вычислений
- **Проверка базиса** — автоматический вывод базиса алгебры
- **Доказательства** — проверка ассоциативности, коммутативности умножения

### Математический анализ
- **Производные** — символьное дифференцирование
- **Интегралы** — антипроизводные и определённое интегрирование
- **Ряды Тейлора** — разложение функций в ряды
- **Пределы** — конечные пределы и подходы

### Логика и теории
- **Трёхзначная логика** — истина, ложь, неизвестно
- **Предикаты** — утверждения с условиями
- **Локальные предположения** — контекстные допущения
- **Теории** — аксиомы, свойства, наследование через `extends`
- **Проверка реализаций** — верификация выполнения аксиом

### Типизация
- **Статическая типизация** — объявление типов переменных и функций
- **Typed IR** — типизированное промежуточное представление с явными вложениями
- **Типизированные функции и замыкания** — лямбда-выражения с типами

### Итерации
- **Конечные итерации** — блоки `iterate(1,n) { ... }`
- **Индексные суммы и произведения** — суммирование по диапазону
- **Типизированный индекс шага** — контроль типа счётчика

### Численные вычисления
- **Высокоточное вычисление** — блок `numeric` для численной оценки

### Инструменты
- **Интерактивная сессия** — REPL для экспериментов
- **Модули** — система пространств имён и импорта
- **IDE** — графический интерфейс на PySide6 с панелью Properties
- **Сохранение объектов** — сериализация математических структур

## 📦 Установка

```bash
# Установка из исходников
pip install -e .

# Установка с поддержкой IDE
pip install -e ".[ide]"
```

### Требования
- Python 3.11+
- Для IDE: PySide6 >= 6.8, matplotlib >= 3.8

## 🚀 Быстрый старт

### Запуск REPL
```bash
mathlang
```

### Выполнение файла
```bash
mathlang examples/algebras.math
```

### Запуск IDE
```bash
mathlang-ide
```

### Примеры кода

**Комплексные числа через алгебру:**
```
algebra Complex over Real {
    generators {i}
    relations {i^2 = -1}
    basis {1, i}
    multiplication bilinear
}

with Complex {
    z = (1+i)^2
    print(z |> normalize)  // 2*i
    prove (1+i)^4 = -4
}
```

**Дуальные числа:**
```
algebra Dual over Real {
    generators {ε}
    relations {ε^2 = 0}
    derive basis
}

parameter a : Real
parameter b : Real
with Dual {
    print(normalize((a+b*ε)^3))  // a^3 + 3*a^2*b*ε
}
```

**Алгебра Вейля:**
```
algebra Weyl over Rational {
    generators {x, y}
    relations {x*y - y*x = 1}
}

with Weyl {
    print(normalize(y*x^3))  // x^3*y - 3*x^2
}
```

**Производные и интегралы:**
```
// Дифференцирование
derivative(x^2, x)  // 2*x

// Интегрирование
integrate(x^2, x)   // x^3/3

// Ряд Тейлора
series(sin(x), x, 0, 5)  // x - x^3/6 + x^5/120
```

**Логика и предикаты:**
```
assume x > 0
simplify(sqrt(x^2))  // x (при условии x > 0)
```

**Теории и наследование:**
```
theory Group {
    operation * : Self × Self → Self
    axiom associativity: ∀a,b,c. (a*b)*c = a*(b*c)
    axiom identity: ∃e. ∀a. e*a = a ∧ a*e = a
    axiom inverse: ∀a. ∃b. a*b = e ∧ b*a = e
}

theory AbelianGroup extends Group {
    axiom commutativity: ∀a,b. a*b = b*a
}
```

## 📁 Структура проекта

```
mathlang/
├── mathlang/           # Исходный код ядра
│   ├── algebra.py      # Фактор-алгебры и соотношения
│   ├── analysis.py     # Производные, интегралы, ряды
│   ├── ast.py          # Абстрактное синтаксическое дерево
│   ├── environment.py  # Окружение объявлений
│   ├── iteration.py    # Итерации и индексные конструкции
│   ├── kernel.py       # Ядро языка
│   ├── lexer.py        # Лексический анализ
│   ├── logic.py        # Трёхзначная логика и предикаты
│   ├── modules.py      # Система модулей
│   ├── normalization.py# Упрощение и нормализация
│   ├── parser.py       # Синтаксический разбор
│   ├── proof.py        # Доказательства равенств
│   ├── rewriting.py    # Правила переписывания
│   ├── session.py      # Интерактивная сессия
│   ├── symbols.py      # Символы и алиасы
│   ├── terms.py        # Термы и выражения
│   ├── theories.py     # Теории и аксиомы
│   ├── typed_ir.py     # Типизированное представление
│   ├── ide/            # Графический интерфейс
│   └── stdlib/         # Стандартная библиотека (.math файлы)
├── examples/           # Примеры использования
│   ├── algebras.math
│   ├── analysis.math
│   ├── iteration.math
│   ├── logic.math
│   ├── theories.math
│   └── ...
├── tests/              # Набор тестов
├── docs/               # Документация
│   ├── CALCULUS.md     # Математический анализ
│   ├── IMPLEMENTATION.md# Детали реализации
│   ├── LOGIC.md        # Логическая система
│   ├── SPECIFICATION.md# Спецификация языка
│   └── ROADMAP.md      # План развития
└── pyproject.toml      # Конфигурация проекта
```

## 🧪 Тестирование

```bash
# Запустить все тесты
pytest

# Запустить конкретный тест
pytest tests/test_algebra.py
pytest tests/test_analysis.py
pytest tests/test_logic.py
pytest tests/test_theories.py
```

## 📚 Документация

Подробная документация доступна в директории [`docs/`](docs/):

- **[SPECIFICATION.md](docs/SPECIFICATION.md)** — полная спецификация языка
- **[CALCULUS.md](docs/CALCULUS.md)** — дифференцирование, интегрирование, ряды
- **[LOGIC.md](docs/LOGIC.md)** — логическая система и предикаты
- **[IMPLEMENTATION.md](docs/IMPLEMENTATION.md)** — детали реализации
- **[THEORIES.md](docs/THEORIES.md)** — система теорий и аксиом
- **[ITERATION.md](docs/ITERATION.md)** — итерации и циклы
- **[NUMERIC.md](docs/NUMERIC.md)** — численные вычисления
- **[ROADMAP.md](docs/ROADMAP.md)** — план развития

## 📝 Примеры

Все примеры находятся в директории [`examples/`](examples/):

| Файл | Описание |
|------|----------|
| `algebras.math` | Комплексные, дуальные числа, алгебра Вейля |
| `analysis.math` | Производные и интегралы |
| `iteration.math` | Итерации и суммирование |
| `logic.math` | Логические операции и предикаты |
| `theories.math` | Определение теорий и аксиом |
| `theory_inheritance.math` | Наследование теорий |
| `quaternions.math` | Кватернионы как фактор-алгебра |
| `mandelbrot.math` | Множество Мандельброта |
| `series_calculus.math` | Ряды Тейлора |

## 🔧 API для Python

```python
from mathlang import Session, parse_expression, normalize

# Создание сессии
session = Session()

# Разбор и вычисление
expr = parse_expression("(1+i)^2")
result = session.evaluate(expr)
print(result)

# Нормализация
normalized = normalize(expr)
print(normalized)

# Доказательство
from mathlang import prove
proof = prove(session, "∀x. x + 0 = x")
print(proof.result)  # True/False/Unknown
```

## 📄 Лицензия

Прототип математического языка, версия 0.9.2

---

**Вклад в проект приветствуется!** Создавайте issues для предложений и pull requests для улучшений.
