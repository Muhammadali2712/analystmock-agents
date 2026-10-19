
from __future__ import annotations
import re
from dataclasses import dataclass
from analystmock.models import Question

@dataclass(frozen=True)
class SQLCheck:
    recognized: bool
    correctness: int
    completeness: int
    clarity: int
    strengths: list[str]
    errors: list[str]
    improvement: str

    def payload(self) -> dict:
        return self.__dict__.copy()

def norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("ё", "е")).strip()

def clarity(answer: str) -> int:
    text = norm(answer)
    return 0 if len(text) < 12 else 2 if len(text) >= 35 else 1

def unknown() -> SQLCheck:
    return SQLCheck(False, 0, 0, 0, [], [
        "Не удалось автоматически распознать критерии этого SQL-вопроса."
    ], "Сравни ответ с условием и эталонным решением.")

def q1(answer: str) -> SQLCheck:
    t = norm(answer)
    a = bool(re.search(r"count\s*\(\s*\*\s*\).{0,40}\b5\b", t))
    b = bool(re.search(r"count\s*\(\s*value\s*\).{0,40}\b3\b", t))
    c = bool(re.search(r"count\s*\(\s*distinct\s+value\s*\).{0,40}\b2\b", t))
    nulls = "null" in t and any(x in t for x in ("не учиты", "исключ", "пропуска", "игнор"))
    distinct = "distinct" in t and any(x in t for x in ("повтор", "уникаль", "разн", "дублик"))
    hit = sum((a, b, c))
    errors = []
    if hit < 3:
        errors.append("Проверь результаты COUNT(*): 5, COUNT(value): 3, COUNT(DISTINCT value): 2.")
    if not nulls:
        errors.append("Объясни, что NULL не учитывается.")
    if not distinct:
        errors.append("Укажи, что DISTINCT убирает повтор значения 10.")
    strengths = ["Верно разобраны все три вида COUNT."] if hit == 3 else []
    if nulls and distinct:
        strengths.append("Учтены NULL и повторяющееся значение.")
    return SQLCheck(True, {0:0,1:2,2:3,3:5}[hit],
                    min(3, int(hit == 3) + int(nulls) + int(distinct)),
                    clarity(answer), strengths, errors[:3],
                    "Повтори различия COUNT(*), COUNT(column) и COUNT(DISTINCT column).")

def q2(answer: str) -> SQLCheck:
    t = norm(answer)
    checks = [
        bool(re.search(r"sum\s*\(\s*amount\s*\)", t)),
        "status" in t and "paid" in t,
        "group by" in t and "user_id" in t,
        "having" in t and "1000" in t and ">" in t,
    ]
    hit = sum(checks)
    errors = []
    if not checks[0]: errors.append("Посчитай SUM(amount).")
    if not checks[1]: errors.append("Оставь только status = 'paid'.")
    if not checks[2]: errors.append("Сгруппируй результат по user_id.")
    if not checks[3]: errors.append("Фильтр суммы больше 1000 должен быть в HAVING.")
    return SQLCheck(True, {0:0,1:1,2:2,3:4,4:5}[hit],
                    min(3, sum(checks[1:])), clarity(answer),
                    ["Выбрана правильная структура агрегации по пользователю."] if hit >= 3 else [],
                    errors[:3], "Повтори связку WHERE - GROUP BY - HAVING.")

def q3(answer: str) -> SQLCheck:
    t = norm(answer)
    checks = [
        "left join" in t,
        bool(re.search(r"count\s*\(\s*(?:o\.)?id\s*\)", t)),
        "group by" in t,
        "0" in t or "без заказ" in t or "null" in t,
    ]
    hit = sum(checks)
    errors = []
    if not checks[0]: errors.append("Используй LEFT JOIN.")
    if not checks[1]: errors.append("Считай COUNT(o.id), а не COUNT(*).")
    if not checks[2]: errors.append("Сгруппируй строки по пользователю.")
    if not checks[3]: errors.append("Объясни результат 0 для пользователя без заказов.")
    return SQLCheck(True, {0:0,1:1,2:3,3:4,4:5}[hit],
                    min(3, int(checks[0]) + int(checks[1]) + int(checks[3])),
                    clarity(answer),
                    ["Сохранены пользователи без заказов через LEFT JOIN."] if checks[0] and checks[1] else [],
                    errors[:3], "Повтори разницу COUNT(*) и COUNT(id) при LEFT JOIN.")

def q4(answer: str) -> SQLCheck:
    t = norm(answer)
    left = "left join" in t
    on_paid = bool(re.search(r"\bon\b(?:(?!\bwhere\b).){0,180}(?:status|статус).{0,180}paid", t)) or (
        "on" in t and "paid" in t and any(x in t for x in ("перенес", "перенос", "услови"))
    )
    nulls = "null" in t or "без заказ" in t or "всех пользов" in t
    explains = "where" in t and any(x in t for x in ("отбрасы", "теря", "исключ", "null"))
    errors = []
    if not explains: errors.append("Объясни, что WHERE по правой таблице отбрасывает NULL.")
    if not on_paid: errors.append("Перенеси status = 'paid' из WHERE в ON.")
    if not nulls: errors.append("Укажи, что пользователи без оплаченных заказов сохраняются.")
    return SQLCheck(True, 5 if left and on_paid else 3 if left else 0,
                    min(3, int(explains) + int(on_paid) + int(nulls)),
                    clarity(answer),
                    ["Фильтр оплаченных заказов перенесён в ON."] if on_paid else [],
                    errors[:3], "Повтори, где ставить фильтр правой таблицы при LEFT JOIN.")

def q5(answer: str) -> SQLCheck:
    t = norm(answer)
    checks = [
        "row_number" in t or "distinct on" in t,
        "partition by" in t and "user_id" in t,
        "created_at" in t and "desc" in t,
        bool(re.search(r"id\s+desc", t)) or ("больш" in t and "id" in t),
        "rn = 1" in t or "rn=1" in t or "distinct on" in t,
    ]
    hit = sum(checks)
    errors = []
    if not checks[0]: errors.append("Используй ROW_NUMBER() или DISTINCT ON.")
    if not checks[1]: errors.append("Раздели строки по user_id.")
    if not checks[2]: errors.append("Сортируй по created_at DESC.")
    if not checks[3]: errors.append("При одинаковом времени выбери больший id.")
    if not checks[4]: errors.append("Оставь только первую строку каждого пользователя.")
    return SQLCheck(True, {0:0,1:1,2:2,3:3,4:4,5:5}[hit],
                    min(3, int(checks[1]) + int(checks[2]) + int(checks[3] and checks[4])),
                    clarity(answer),
                    ["Задана сортировка по времени и tie-break по id."] if checks[2] and checks[3] else [],
                    errors[:3], "Повтори оконную функцию и правило tie-break.")

def q6(answer: str) -> SQLCheck:
    t = norm(answer)
    checks = [
        bool(re.search(r"count\s*\(\s*distinct\s+user_id\s*\)", t)),
        "status" in t and "paid" in t,
        "2026-09-01" in t,
        "2026-10-01" in t,
    ]
    hit = sum(checks)
    errors = []
    if not checks[0]: errors.append("Используй COUNT(DISTINCT user_id).")
    if not checks[1]: errors.append("Оставь только status = 'paid'.")
    if not checks[2]: errors.append("Начни период с 2026-09-01 включительно.")
    if not checks[3]: errors.append("Исключи 2026-10-01.")
    return SQLCheck(True, {0:0,1:1,2:3,3:4,4:5}[hit],
                    min(3, int(checks[0]) + int(checks[1]) + int(checks[2] and checks[3])),
                    clarity(answer),
                    ["Учтены уникальные пользователи и границы сентября."] if all(checks) else [],
                    errors[:3], "Повтори фильтрацию периода через две границы дат.")

def grade_sql(question: Question, answer: str) -> SQLCheck:
    p = norm(question.prompt)
    if "count(*)" in p and "count(value)" in p: return q1(answer)
    if "строго больше 1000" in p: return q2(answer)
    if "пользователя без заказов должно быть 0" in p: return q3(answer)
    if "почему запрос теряет часть пользователей" in p: return q4(answer)
    if "самого позднего заказа каждого пользователя" in p: return q5(answer)
    if "сентябре 2026 года" in p: return q6(answer)
    return unknown()
