from random import sample

from analystmock.models import Question, Quiz

SOURCES = (
    "https://www.postgresql.org/docs/current/functions-aggregate.html",
    "https://www.postgresql.org/docs/current/queries-table-expressions.html",
    "https://www.postgresql.org/docs/current/functions-window.html",
)

SQL_QUESTIONS = [
    Question(
        topic="SQL",
        prompt="PostgreSQL. В таблице t столбец value содержит пять значений: 10, 10, NULL, 20, NULL. Что вернут COUNT(*), COUNT(value) и COUNT(DISTINCT value)? Объясни разницу.",
        reference_answer="COUNT(*) = 5: все строки. COUNT(value) = 3: строки, где value не NULL. COUNT(DISTINCT value) = 2: разные значения без NULL, то есть 10 и 20.",
        criteria=["Верны результаты 5, 3, 2", "Объяснено исключение NULL и устранение повторов"],
    ),
    Question(
        topic="SQL",
        prompt="PostgreSQL. orders(id PRIMARY KEY, user_id INTEGER NOT NULL, amount NUMERIC NOT NULL, status TEXT NOT NULL). Одна строка - один заказ. Выведи user_id и сумму оплаченных заказов для пользователей, у которых она строго больше 1000. Оплаченный заказ имеет status = 'paid'.",
        reference_answer="SELECT user_id, SUM(amount) AS revenue FROM orders WHERE status = 'paid' GROUP BY user_id HAVING SUM(amount) > 1000;",
        criteria=["Суммируются только оплаченные заказы", "Сумма считается отдельно для каждого пользователя", "Порог строго больше 1000 применяется к сумме"],
    ),
    Question(
        topic="SQL",
        prompt="PostgreSQL. users(id PRIMARY KEY) и orders(id PRIMARY KEY, user_id INTEGER NOT NULL). Выведи каждого пользователя и число его заказов. Для пользователя без заказов должно быть 0.",
        reference_answer="SELECT u.id, COUNT(o.id) AS orders_count FROM users u LEFT JOIN orders o ON o.user_id = u.id GROUP BY u.id; COUNT(o.id) не считает NULL у пользователя без заказов.",
        criteria=["Сохранены пользователи без заказов", "У них число заказов равно 0", "По одной строке результата на пользователя"],
    ),
    Question(
        topic="SQL",
        prompt="PostgreSQL. users(id PRIMARY KEY), orders(id PRIMARY KEY, user_id INTEGER NOT NULL, status TEXT NOT NULL). Нужно показать всех пользователей с их оплаченными заказами, а при отсутствии таких заказов - строку с NULL вместо заказа. Почему запрос теряет часть пользователей? Исправь: SELECT u.id, o.id FROM users u LEFT JOIN orders o ON o.user_id = u.id WHERE o.status = 'paid';",
        reference_answer="WHERE o.status = 'paid' отбрасывает строки с NULL после соединения. Фильтр нужно перенести в ON: SELECT u.id, o.id FROM users u LEFT JOIN orders o ON o.user_id = u.id AND o.status = 'paid';",
        criteria=["Объяснено действие WHERE после соединения", "Сохранены в том числе пользователи только с неоплаченными заказами", "В результате отсутствуют неоплаченные заказы"],
    ),
    Question(
        topic="SQL",
        prompt="PostgreSQL. orders(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, created_at TIMESTAMP NOT NULL). Выведи user_id, id и created_at самого позднего заказа каждого пользователя. Если время совпадает, выбери заказ с большим id.",
        reference_answer="SELECT user_id, id, created_at FROM (SELECT user_id, id, created_at, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC, id DESC) AS rn FROM orders) t WHERE rn = 1; Корректен также DISTINCT ON с подходящим ORDER BY.",
        criteria=["Один заказ для каждого пользователя", "Выбрано максимальное время created_at", "При равном времени выбран больший id"],
    ),
    Question(
        topic="SQL",
        prompt="PostgreSQL. orders(id PRIMARY KEY, user_id INTEGER NOT NULL, created_at TIMESTAMP NOT NULL, status TEXT NOT NULL). Посчитай число уникальных пользователей с хотя бы одним оплаченным заказом в сентябре 2026 года. status = 'paid', все даты в одной временной зоне.",
        reference_answer="SELECT COUNT(DISTINCT user_id) FROM orders WHERE status = 'paid' AND created_at >= '2026-09-01' AND created_at < '2026-10-01';",
        criteria=["Пользователи не дублируются", "Учитываются только оплаченные заказы", "Включён весь сентябрь, октябрь исключён"],
    ),
]


def make_sql_quiz(recent):
    used = {text.strip().casefold() for text in recent}
    fresh = [q for q in SQL_QUESTIONS if q.prompt.strip().casefold() not in used]
    seen = [q for q in SQL_QUESTIONS if q.prompt.strip().casefold() in used]
    selected = sample(fresh, min(3, len(fresh)))
    selected += sample(seen, 3 - len(selected))
    return Quiz(questions=[q.model_copy(deep=True) for q in selected])
