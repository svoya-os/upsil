# Учебник UpsiL

[Спецификация](spec.md) · [README](../README.md)

Этот учебник — практический: за час вы напишете несколько небольших программ, от
«Привет, мир» до поиска по своим заметкам с локальной моделью. Нужен Python 3.10 или новее.
Локальная модель нужна только для разделов 10–11; в СОС она запускается одной командой.

Все примеры из учебника проверяются автоматически: код компилируется, а показанный вывод —
настоящий.

## 1. Установка

```sh
uv tool install git+https://github.com/svoya-os/upsil    # или: pipx install git+https://github.com/svoya-os/upsil
upsil version
```

Когда пакет появится на PyPI, хватит `uv tool install upsil`. Для блоков `model` нужен ещё
PyTorch: `uv tool install 'upsil[nn]'`.

## 2. Первая программа

Создайте файл `hello.upl`:

```upsil
val name = "мир"
print("Привет, {name}!")
```
```output
Привет, мир!
```

и запустите его: `upsil run hello.upl` (или короче: `upsil hello.upl`). Фигурные скобки в
строке вставляют значение выражения; внутри может быть любое выражение: `"{2 + 2}"`.

Попробовать язык без файла можно в интерактивном режиме `upsil repl`: он сразу показывает
значение каждого выражения. Выход — Ctrl-D.

## 3. Переменные и значения

`val` — значение, которое не меняется; `var` — переменная, которую можно менять. Лучше
начинать с `val` и переходить на `var`, только когда значение правда меняется.

```upsil
val city = "Казань"
var visits = 1
visits += 1
val price = 99.5
val ok = visits > 1 and price < 100
print("{city}: {visits} визита, {price} ₽, всё в порядке: {ok}")
print("пусто: {null}, пи ≈ {3.14159:.2f}, в скобках: \{нет интерполяции\}")
```
```output
Казань: 2 визита, 99.5 ₽, всё в порядке: true
пусто: null, пи ≈ 3.14, в скобках: {нет интерполяции}
```

Значения: числа (`1`, `2.5`), строки (`"..."`), `true` и `false`, `null` («ничего»),
списки `[1, 2]` и словари `{"ключ": "значение"}`. Тип можно подписать — `val n: int = 5`,
но во время выполнения он не проверяется; `upsil check` найдёт только очевидные ошибки
вроде `val n: int = "пять"`.

Инструкция заканчивается переводом строки. Длинное выражение можно перенести, оставив в
конце строки оператор или запятую, или перенести внутри скобок.

## 4. Условия и циклы

```upsil
for (i in 1..=15) {
    if i % 15 == 0 {
        print("FizzBuzz", end = " ")
    } else if i % 3 == 0 {
        print("Fizz", end = " ")
    } else if i % 5 == 0 {
        print("Buzz", end = " ")
    } else {
        print(i, end = " ")
    }
}
print()
```
```output
1 2 Fizz 4 Buzz Fizz 7 8 Fizz Buzz 11 Fizz 13 14 FizzBuzz 
```

`1..=15` — числа от 1 до 15 включительно, `0..n` — от 0 до `n - 1`. Цикл `while`
повторяет блок, пока условие истинно; `break` прерывает цикл, `continue` переходит к
следующему шагу:

```upsil
var n = 27
var steps = 0
while n != 1 {
    if n % 2 == 0 {
        n = div(n, 2)
    } else {
        n = 3 * n + 1
    }
    steps += 1
}
print("шагов до единицы: {steps}")
```
```output
шагов до единицы: 111
```

Обратите внимание: `/` всегда делит дробно (`7 / 2` — это `3.5`), а целочисленное деление
записывается как `div(7, 2)`, потому что `//` в UpsiL начинает комментарий.

## 5. Функции

```upsil
fun greet(name, greeting = "Привет") {
    return "{greeting}, {name}!"
}

fun factorial(n: int) -> int {
    if n <= 1 {
        return 1
    }
    return n * factorial(n - 1)
}

print(greet("Аня"))
print(greet("Боря", greeting = "Здравствуй"))
print("10! = {factorial(10)}")
```
```output
Привет, Аня!
Здравствуй, Боря!
10! = 3628800
```

Параметры, как и `val`, менять нельзя. Значение по умолчанию вычисляется при каждом
вызове, поэтому `fun add(x, xs = [])` каждый раз получает новый пустой список.
Компилятор проверяет вызовы: если забыть аргумент, программа даже не запустится (раздел 8).

Функция может вернуть несколько значений — их удобно сразу разложить по переменным. А для
коротких функций «на месте» есть лямбды: `x => x * 2`. Значение по условию записывается
как `if (условие) a else b`:

```upsil
fun stats(xs) {
    return min(xs), max(xs), sum(xs) / len(xs)
}
val (lo, hi, mean) = stats([3, 7, 5])
print("от {lo} до {hi}, в среднем {mean}")

val names = ["Вика", "Ян", "Александра"]
print(sorted(names, key = n => len(n)))
print(if (mean > 4) "выше четырёх" else "не выше четырёх")
```
```output
от 3 до 7, в среднем 5.0
["Ян", "Вика", "Александра"]
выше четырёх
```

## 6. Списки и словари

Посчитаем, сколько раз встречается каждое слово:

```upsil
val text = "мама мыла раму мама мыла пол"
val counts = {}
for (word in text.split()) {
    counts[word] = counts.get(word, 0) + 1
}
for (word, n) in sorted(counts.items()) {
    print("{word}: {n}")
}
print("всего слов: {len(text.split())}, разных: {len(counts)}")
```
```output
мама: 2
мыла: 2
пол: 1
раму: 1
всего слов: 6, разных: 4
```

`val counts` нельзя присвоить заново, но менять содержимое словаря можно. У списков и
словарей те же методы, что в Python: `append`, `pop`, `sort`, `get`, `keys`, `items`…
Срезы: `xs[1:3]`, `xs[-1]`, `xs[::2]`.

Новый список из старого удобно собирать генератором — `[что for x in откуда if условие]`,
словарь — так же в фигурных скобках:

```upsil
val words = "мама мыла раму мама мыла пол".split()
print([w.upper() for w in words if len(w) > 3])
print({w: words.count(w) for w in ["мама", "пол"]})
print(sum(len(w) for w in words))
```
```output
["МАМА", "МЫЛА", "РАМУ", "МАМА", "МЫЛА"]
{"мама": 2, "пол": 1}
23
```

## 7. Классы

```upsil
class Todo {
    val title: str
    var done = false

    fun mark() {
        done = true
    }

    fun line() {
        if done {
            return "[x] {title}"
        }
        return "[ ] {title}"
    }
}

val todos = [Todo("купить хлеб"), Todo("написать отчёт")]
todos[0].mark()
for (t in todos) {
    print(t.line())
}
print(todos[1])
```
```output
[x] купить хлеб
[ ] написать отчёт
Todo(title="написать отчёт", done=false)
```

Поля без значения (`title`) становятся параметрами конструктора: `Todo("купить хлеб")`.
Внутри методов поля доступны просто по имени.

## 8. Ошибки и как их читать

Многие ошибки UpsiL находит до запуска. Сообщение показывает файл, строку и столбец:

```upsil-error
fun area(w, h) {
    return w * h
}
print(area(3))
```
```output
example.upl:4:7: ошибка: в вызове area() не хватает аргумента 'h'
  4 | print(area(3))
    |       ^^^^^^^
```

Проверить файл, не запуская его: `upsil check файл.upl`. Ошибки во время выполнения
показываются по строкам программы UpsiL, без внутренностей Python:

```upsil
val prices = {"хлеб": 50}
print(prices["молоко"])
```
```output
Ошибка выполнения (последний вызов — внизу):
  example.upl:2, в <программа>
    print(prices["молоко"])
          ^^^^^^^^^^^^^^^^
KeyError: 'молоко' — в словаре нет такого ключа
```

Язык сообщений берётся из `LANG`; английский можно включить так: `UPSIL_LANG=en upsil run ...`.
Код выхода: 0 — всё хорошо, 1 — ошибка выполнения, 2 — ошибка компиляции.

Ошибку можно поймать и продолжить работу: `try { ... } catch (e) { ... }`. Тип ошибки
указывается после двоеточия, а свою ошибку бросает `throw`:

```upsil
fun price(item) {
    val prices = {"хлеб": 50, "молоко": 90}
    if not (item in prices) {
        throw "нет цены для «{item}»"
    }
    return prices[item]
}
var total = 0
for (item in ["хлеб", "икра", "молоко"]) {
    try {
        total += price(item)
    } catch (e) {
        print("пропускаю:", e)
    }
}
print("итого {total}")
try {
    print(int("сто"))
} catch (e: ValueError) {
    print("это не число")
}
```
```output
пропускаю: нет цены для «икра»
итого 140
это не число
```

## 9. Файлы и аргументы

Скрипт `count.upl` считает строки в файлах, имена которых переданы в командной строке
(`upsil run count.upl a.txt b.txt`):

```upsil
import fs
import sys

if len(sys.args) == 0 {
    print("использование: upsil run count.upl ФАЙЛ...")
    sys.exit(64)
}
var total = 0
for (path in sys.args) {
    val n = len(fs.lines(path))
    total += n
    print("{n:>6}  {path}")
}
print("{total:>6}  всего")
```

Модули подключаются через `import`: `fs` (файлы), `sys` (аргументы, переменные окружения,
выход), `json`, `http`, `time`, `math`, `random` и модули для ИИ — `llm`, `rag`, `nn`,
`ui`. Их описание — в [спецификации](spec.md#12-модули).

## 10. Локальная модель

UpsiL разговаривает с любым сервером, у которого API как у OpenAI. В СОС такой сервер —
llama.cpp — запускается командой

```sh
sos models serve            # API на http://127.0.0.1:8080/v1
sos models serve --status   # работает ли
sos models suggest          # какая модель подойдёт видеокарте
```

и UpsiL находит его сам. На другом компьютере укажите адрес: `UPSIL_LLM_URL=http://host:8000/v1`
(для облачных сервисов ещё ключ `UPSIL_LLM_KEY`), или запишите его в
`~/.config/upsil/config.toml` (раздел 9.1 спецификации).

Главная конструкция — оператор промпта `[модель] => "текст"`:

```upsil
import llm

llm m = llm.Model()
val topic = "резервные копии"
val answer = [m] => "Объясни в двух предложениях, зачем нужны {topic}."
print(answer)
```

`llm m = llm.Model()` объявляет модель (без имени берётся модель из настроек или первая на
сервере; можно указать явно: `llm.Model("qwen3.5-4b")`). Системный промпт задаёт роль
модели, а `-> json` просит ответ в JSON и сразу превращает его в словарь:

```upsil
import llm

llm m = llm.Model()
val review = "Доставили быстро, но коробка помята."
val mood = [m, system: "Отвечай одним словом: хорошо, плохо или нейтрально."] => review
val parsed = [m] => """
    Разбери отзыв и верни JSON с полями "плюсы" и "минусы" (списки строк).
    Отзыв: {review}
    """ -> json
print(mood)
print(parsed["плюсы"], parsed["минусы"])
```

Модели иногда отвечают не тем, что просили. Опишите форму ответа — `-> json(форма)` — и
UpsiL проверит его: если что-то не так, объяснит модели ошибку и переспросит, а если и это
не поможет, остановится с ошибкой `llm.FormatError`, которую можно поймать. `m.ask_all`
задаёт много вопросов сразу и возвращает ответы в том же порядке:

```upsil
import llm

llm m = llm.Model(temperature = 0.0)
val shape = {"label": ["pos", "neg", "neu"], "score": float}
try {
    val one = [m] => "Оцени тональность: «Доставили быстро»" -> json(shape)
    print(one["label"], one["score"])
} catch (e: llm.FormatError) {
    print("модель ответила не по форме:", e.reply)
}
val many = m.ask_all(["Оцени тональность: «{t}»" for t in ["Супер!", "Сломалось"]],
                     schema = shape, errors = "null")
print(many)
```

Форма — обычное значение: `str`, `int`, `float`, `bool`, список `[T]`, выбор из вариантов
`["a", "b"]`, объект `{"поле": T}` (необязательное поле — `"поле?"`). Полная программа
разметки отзывов с записью в CSV — [examples/reviews.upl](../examples/reviews.upl);
сравнение нескольких промптов — [examples/prompt_eval.upl](../examples/prompt_eval.upl).

Длинные ответы удобно печатать по мере генерации, а для диалога — хранить историю
сообщений:

```upsil
import llm

llm m = llm.Model()
val history = [{"role": "system", "content": "Отвечай кратко."}]
for (question in ["Что такое RAG?", "А зачем он нужен?"]) {
    history.append({"role": "user", "content": question})
    var reply = ""
    for (piece in m.stream(history)) {
        print(piece, end = "")
        reply += piece
    }
    print()
    history.append({"role": "assistant", "content": reply})
}
```

Готовый чат в терминале — [examples/chat.upl](../examples/chat.upl), в окне —
[examples/neurochat.upl](../examples/neurochat.upl).

Если сервер не запущен, программа остановится с понятным сообщением:
`ошибка: Локальная модель не отвечает (127.0.0.1:8080). В СОС: sos models serve`.

## 11. Поиск по заметкам

Модели не знают ваших заметок, но их можно найти и передать модели вместе с вопросом. Так
работает RAG (retrieval-augmented generation):

```upsil
import llm
import rag

vector_store db = rag.VectorStore()
val chunks = db.add_dir("examples/notes", glob = "*.md")
print("фрагментов: {chunks}")

llm m = llm.Model()
val question = "Как проверить резервную копию?"
val context = db.context(question, k = 3)
print([m, system: "Отвечай только по заметкам."] => "Заметки:\n{context}\n\nВопрос: {question}")
db.save("notes.index.json")
```

`db.search(вопрос, k = 3)` возвращает найденные фрагменты с оценкой (`hit.score`) и
источником (`hit.meta["source"]`), а `db.context` — их тексты одной строкой. Если сервер
умеет считать эмбеддинги, поиск смысловой; если нет, UpsiL один раз предупредит об этом и
будет искать по словам. Полная программа —
[examples/rag_notes.upl](../examples/rag_notes.upl).

## 12. Нейросети

Блок `model` описывает нейросеть PyTorch: поля — слои, `forward` — вычисление.

```upsil
import nn

model TinyNet {
    val l1 = nn.Linear(2, 8)
    val l2 = nn.Linear(8, 1)

    graph forward(x) {
        return nn.sigmoid(l2(nn.relu(l1(x))))
    }
}
```

`nn.X` — это `torch.nn.X`, `torch.nn.functional.X` или `torch.X`. Обучение сети на задаче
XOR шаг за шагом — [examples/neural_net.upl](../examples/neural_net.upl). Без PyTorch
программа сообщит, как его установить.

Обычный цикл обучения — эпохи, мини-пакеты, оптимизатор, проверка на отложенных данных —
уже написан: `nn.fit`. Он печатает строку прогресса и возвращает историю, а `nn.accuracy`
считает долю верных ответов:

```upsil
import nn

val x = nn.randn(200, 2)
val y = (x[:, 0] * x[:, 1] > 0).long()     // класс 1, если точка в I или III четверти
model Quadrants {
    val net = nn.Sequential(nn.Linear(2, 16), nn.ReLU(), nn.Linear(16, 2))
    graph forward(x) { return net(x) }
}
val m = Quadrants()
val history = nn.fit(m, x[:160], y[:160], epochs = 50, lr = 0.02, val = (x[160:], y[160:]), every = 25)
print("точность: {nn.accuracy(m, x[160:], y[160:]):.0%}")
with nn.no_grad() {
    print(m(nn.tensor([[1.0, 1.0], [-1.0, 1.0]])).argmax(dim = 1))
}
```

`with nn.no_grad() { ... }` считает без градиентов — так быстрее и экономнее по памяти,
когда модель уже обучена. Пример с двумя спиралями — [examples/spirals.upl](../examples/spirals.upl).

## 13. Библиотеки Python

Любую библиотеку Python можно подключить явно:

```upsil
import py "statistics" as stats
import py "pathlib"

val marks = [5, 4, 4, 5, 3]
print("среднее {stats.mean(marks)}, медиана {stats.median(marks)}")
print(pathlib.Path("отчёт.pdf").suffix)
```
```output
среднее 4.2, медиана 4
.pdf
```

## 14. Тесты

Проверки пишутся в файлах `test_*.upl`: каждая функция `test_...` — отдельный тест, а
`assert условие, "сообщение"` останавливает тест, если условие ложно. Код, который
проверяют, подключается через `import "файл.upl"`:

```text
text.upl:
fun shout(s) { return s.upper() + "!" }

tests/test_text.upl:
import "../text.upl"
fun test_shout() {
    assert text.shout("ай") == "АЙ!", "должно быть громко"
}
```

`upsil test` найдёт такие файлы в текущей папке и подпапках, запустит тесты и покажет,
какие не прошли и на какой строке.

## 15. Что под капотом

UpsiL превращает программу в Python. Посмотреть, во что именно:

```sh
upsil build hello.upl               # на экран
upsil build hello.upl -o hello.py   # в файл
```

Получается обычный читаемый Python; для запуска ему нужен установленный пакет `upsil`.

## 16. Подсветка в редакторах

- **VS Code**: папка `vscode-upsil` — расширение; собрать и поставить:
  `cd vscode-upsil && npx @vscode/vsce package && code --install-extension upsil-lang-1.2.0.vsix`.
- **GNOME Text Editor, gedit**:
  `mkdir -p ~/.local/share/gtksourceview-5/language-specs && cp editor/upsil.lang ~/.local/share/gtksourceview-5/language-specs/`
  (для gedit до версии 41 — папка `gtksourceview-4`).
- **Kate, KWrite**:
  `mkdir -p ~/.local/share/org.kde.syntax-highlighting/syntax && cp editor/upsil.xml ~/.local/share/org.kde.syntax-highlighting/syntax/`.

## Что дальше

- [Спецификация](spec.md) — точные правила языка и описание всех модулей.
- [examples/](../examples) — готовые программы.
- Ошибки и предложения — в [issues](https://github.com/svoya-os/upsil/issues).
