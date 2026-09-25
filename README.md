# UpsiL

**Небольшой язык для ИИ-скриптов.** Синтаксис в духе Kotlin, локальные языковые модели,
поиск по своим документам и нейросети PyTorch — а под капотом читаемый Python.

[English](README.en.md) · [Учебник](docs/tutorial.md) · [Спецификация](docs/spec.md) ·
[Примеры](examples) · [Изменения](CHANGELOG.md)

```upsil
import llm
import rag

llm m = llm.Model()                              // локальная модель: sos models serve
vector_store notes = rag.VectorStore()
notes.add_dir("examples/notes")                  // проиндексировать папку заметок

val question = "Как проверить резервную копию?"
print([m] => "Ответь по заметкам:\n{notes.context(question)}\n\nВопрос: {question}")
```

> **Статус: v0.3 — ранняя версия.** Язык небольшой и честный: всё, что описано в
> документации, работает и проверяется тестами, в том числе примеры кода из самой
> документации. Версия 0.3 выросла из работы на самом языке: на нём написали обучение
> нейросети, разметку отзывов моделью, сравнение промптов и разбор журналов — и добавили
> то, чего не хватало ([что было неудобно и что исправлено](docs/dogfood.md)). Чего пока
> нет — в разделе [«Чего нет в v0.3»](docs/spec.md#14-чего-нет-в-v03).

## Что это

- **Язык**: `fun`, `val`/`var`, `if`/`else if`, `while`, `for (i in 0..n)`, классы, строки с
  интерполяцией `"Привет, {name}"`, многострочные и сырые (`r"\d+"`) строки, лямбды
  `x => x * 2`, генераторы `[x * x for x in xs if x > 0]`, `if (c) a else b`, кортежи и
  распаковка `val (lo, hi) = ...`, ошибки `try`/`catch`/`finally`/`throw`, `with`, `assert`,
  импорт своих файлов `import "helpers.upl"`, тесты `upsil test`, понятные сообщения об
  ошибках на русском или английском с номером строки и столбца.
- **ИИ-ресурсы в языке**: `llm m = llm.Model()` — модель, `[m] => "..."` — вопрос модели,
  `-> json(форма)` — ответ в виде проверенных данных (не та форма — модель переспросят),
  `m.ask_all([...])` — много вопросов параллельно, `vector_store db = rag.VectorStore()` —
  поиск по документам, `model Net { ... }` — нейросеть PyTorch, `nn.fit(...)` — обучение с
  проверкой и строкой прогресса.
- **Компилятор в Python**: программа проверяется целиком до запуска (неизвестные имена,
  изменение `val`, `break` вне цикла, неверное число аргументов…), превращается в дерево
  Python и выполняется; `upsil build` покажет получившийся код. Любую библиотеку Python можно
  подключить: `import py "numpy" as np`.
- **Без зависимостей**: нужен только Python 3.10+. PyTorch — по желанию, для блоков `model`.

## Установка

```sh
uv tool install git+https://github.com/svoya-os/upsil
# или
pipx install git+https://github.com/svoya-os/upsil
```

Когда пакет появится на PyPI, хватит `uv tool install upsil` (или `pipx install upsil`).
С PyTorch: `uv tool install 'upsil[nn]'`. Проверка: `upsil version`.

## Пять минут

Переменные, строки, функции:

```upsil
val name = "UpsiL"          // val не меняется
var count = 0               // var меняется

fun greet(who, punct = "!") {
    return "Привет, {who}{punct}"
}

count += 1
print(greet(name), count)
print(greet("мир", punct = "?"))
```
```output
Привет, UpsiL! 1
Привет, мир?
```

Циклы, списки, словари:

```upsil
val prices = {"хлеб": 50, "молоко": 90}
var total = 0
for (item, price) in prices.items() {
    total += price
}
val squares = [i * i for i in 1..=5]
print("итого {total} ₽, квадраты {squares}, чётные {squares[1::2]}")
```
```output
итого 140 ₽, квадраты [1, 4, 9, 16, 25], чётные [4, 16]
```

Классы:

```upsil
class Account {
    val owner: str
    var balance = 0

    fun deposit(amount) {
        if amount <= 0 {
            error("сумма должна быть больше нуля")
        }
        balance += amount
    }
}

val acc = Account("Аня")
acc.deposit(100)
print(acc)
```
```output
Account(owner="Аня", balance=100)
```

Ошибки видны до запуска:

```upsil-error
val limit = 3
limit = 4
```
```output
example.upl:2:1: ошибка: нельзя изменить val 'limit' (объявлено в строке 1); объявите через var
  2 | limit = 4
    | ^^^^^
```

Команды:

```sh
upsil run hello.upl          # запустить (или просто: upsil hello.upl)
upsil check hello.upl        # проверить, не запуская
upsil test                   # запустить тесты: fun test_...() в файлах test_*.upl
upsil build hello.upl        # показать получившийся Python
upsil repl                   # интерактивный режим
```

## ИИ в языке

```upsil
import llm

llm m = llm.Model()                                   // модель по умолчанию
val text = "UpsiL компилируется в Python и работает с локальными моделями."

val summary = [m] => "Перескажи в пяти словах: {text}"
val strict = [m, system: "Отвечай только «да» или «нет»"] => "Python — язык программирования?"
val facts = [m] => "Выдели язык и цель: {text}" -> json({"язык": str, "цель": str})

print(summary, strict, facts["язык"])
for (piece in m.stream("Напиши хайку про компиляторы")) {
    print(piece, end = "")                            // ответ по мере генерации
}
```

- `[m] => текст` возвращает ответ модели строкой; `system:` задаёт роль; `-> json` возвращает
  словарь или список, `-> json(форма)` ещё и проверяет его, а если модель ответила не по
  форме — объясняет ей ошибку и переспрашивает; не помогло — `llm.FormatError`, которую ловит
  `catch`. Значения, подставленные в промпт через `{...}`, передаются как текст и никогда не
  выполняются.
- `m.ask_all(вопросы, schema = форма, errors = "null")` задаёт много вопросов параллельно и
  не останавливается из-за одного плохого ответа.
- `rag.VectorStore()` ищет по смыслу, если сервер умеет считать эмбеддинги, а иначе
  предупреждает об этом и ищет по словам (BM25). Индекс сохраняется в JSON.
- `model` превращается в `torch.nn.Module`; слои объявляются полями, `forward` — методом.
  `nn.fit(net, x, y, epochs = 60, val = (x_test, y_test))` обучает, `nn.accuracy` считает
  точность, `with nn.no_grad() { ... }` — вычисления без градиентов.

Подробнее — в [учебнике](docs/tutorial.md#10-локальная-модель) и
[спецификации](docs/spec.md#9-ии-модели-промпты-поиск).

## UpsiL в СОС

UpsiL развивается как модуль [СОС](https://github.com/svoya-os) — Linux-дистрибутива для
работы с ИИ — и по умолчанию работает с его локальным сервером моделей:

- `sos models serve` запускает llama.cpp в режиме роутера с API, совместимым с OpenAI, на
  `http://127.0.0.1:8080/v1` — это адрес UpsiL по умолчанию; модели лежат в `/srv/ai`;
- `sos models suggest` подскажет модель под вашу видеокарту;
- если сервер не запущен, UpsiL так и скажет:
  `Локальная модель не отвечает (127.0.0.1:8080). В СОС: sos models serve`;
- тот же сервер использует ассистент Джексон, так что модели скачиваются один раз.

В СОС UpsiL ставится пакетом `upsil`: команда `upsil`, подсветка в GNOME Text Editor и Kate,
документация и примеры в `/usr/share/doc/upsil`. Кроме того:

- `sos run программа.upl` показывает заголовок окружения, а прогресс (`sys.progress`, `nn.fit`,
  `m.ask_all`) — на панели СОС; если в папке проекта есть `.venv` (например, после
  `uv add torch`), программа запускается в нём;
- `sos new имя --template upsil` создаёт проект: `main.upl`, файл с вопросами к модели и тесты
  для `upsil test`;
- Джексон знает язык: с пакетом ставится навык [skills/upsil/SKILL.md](skills/upsil/SKILL.md),
  и на просьбу «напиши на упсиле…» он пишет код по правилам 0.3.

Вне СОС подойдёт любой сервер с API OpenAI (llama.cpp, Ollama, vLLM, LM Studio или облако):
укажите `UPSIL_LLM_URL` (и `UPSIL_LLM_KEY`, если нужен ключ) или запишите их в
`~/.config/upsil/config.toml`.

## Редакторы

- VS Code — расширение в [vscode-upsil](vscode-upsil);
- GNOME Text Editor и gedit — [editor/upsil.lang](editor/upsil.lang);
- Kate и KWrite — [editor/upsil.xml](editor/upsil.xml);
- ИИ-ассистенты — навык [skills/upsil/SKILL.md](skills/upsil/SKILL.md) в формате Agent Skills
  (шпаргалка по языку для модели): Джексон в СОС получает его с пакетом, другим агентам
  (например, Claude Code) достаточно скопировать папку `skills/upsil` в их каталог навыков.

Все три грамматики собираются из одного списка ключевых слов скриптом
[tools/gen_syntax.py](tools/gen_syntax.py). Как установить — в
[учебнике](docs/tutorial.md#16-подсветка-в-редакторах).

## Что нового в 0.3

Версию 0.3 проверили делом: на UpsiL написали четыре настоящие программы — классификатор на
PyTorch, разметку отзывов моделью, сравнение промптов, вопросы к заметкам — и записали, что
мешало ([docs/dogfood.md](docs/dogfood.md)). Один кривой ответ модели ронял всю разметку — теперь
есть `try`/`catch`, форма ответа и повторный вопрос. `torch.no_grad()` нельзя было
использовать — теперь есть `with`. Столбцы данных собирались циклами — теперь генераторы
списков. Сортировка и шаблоны промптов требовали отдельных функций — теперь лямбды. Цикл
обучения писался руками — теперь `nn.fit`. Плюс кортежи и распаковка, `if`-выражение, сырые
строки для регулярных выражений, модули `csv` и `re`, импорт своих файлов и `upsil test`.
Подробности — в [CHANGELOG.md](CHANGELOG.md).

Версия 0.2 была переписана с нуля после аудита 0.1, где многое было фасадом; LLVM-прототип
0.1 сохранён в истории git.

## Разработка

```sh
python3 -m unittest discover -s tests -v   # все тесты, без сети и без PyTorch
python3 tools/gen_syntax.py                 # пересобрать грамматики редакторов
python3 -m upsil run examples/hello.upl     # запуск из исходников
```

Тесты используют только стандартную библиотеку; модели заменяет маленький сервер с API
OpenAI, который тесты запускают сами, а PyTorch — `tests/microtorch.py`, небольшой
автоградиент на numpy: нейросети из примеров действительно обучаются в тестах. Запустить
программу с ним: `python3 tests/run_microtorch.py examples/spirals.upl`.

## Лицензия

[Apache-2.0](LICENSE). Автор — Maksim Segen; участники проекта UpsiL перечислены в истории git.
