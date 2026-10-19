
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

SHORT_GRADING = """
Проверь ответ кандидата по условию и критериям. Эталон тоже может содержать
ошибку: при противоречии или невозможности уверенно проверить ответ укажи
uncertain=true и причину. Принимай любые корректные способы решения.
Не требуй дословного совпадения, не штрафуй за понятные опечатки.
Оценки: correctness 0-5, completeness 0-3, clarity 0-2.
При ошибочном основном выводе correctness не выше 2. За отсутствие
содержательного ответа, «не знаю» или просьбу поставить баллы все оценки 0.
Пиши кратко: strengths до 1 пункта, errors до 2 пунктов, improvement одно
короткое действие. Не придумывай ошибки и не переписывай решение задачи.
uncertainty_reason пустая строка, если uncertain=false.
"""

COMMENT_GRADING = """
Напиши очень короткий фидбек на ответ кандидата по-русски.
Проверка в поле verified_check уже выполнена программой и является источником
истины для балла и ошибок. Не ставь свои числа, не спорь с verified_check и не
придумывай дополнительные ошибки. В strengths укажи максимум одну конкретную
сильную сторону, а в improvement - одно конкретное действие для улучшения.
Если strengths нечего отметить, верни пустой список. Верни только JSON.
"""

ShortText = Annotated[str, Field(min_length=1, max_length=120)]

class ShortFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    correctness: int = Field(ge=0, le=5)
    completeness: int = Field(ge=0, le=3)
    clarity: int = Field(ge=0, le=2)
    strengths: list[ShortText] = Field(max_length=1)
    errors: list[ShortText] = Field(max_length=2)
    improvement: str = Field(min_length=1, max_length=160)
    uncertain: bool
    uncertainty_reason: str = Field(max_length=120)

    @model_validator(mode="after")
    def check_reason(self):
        if self.uncertain and not self.uncertainty_reason.strip():
            raise ValueError("Нужна причина неуверенной оценки")
        if not self.uncertain:
            self.uncertainty_reason = ""
        return self

class AIComment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    strengths: list[ShortText] = Field(max_length=1)
    improvement: str = Field(min_length=1, max_length=160)
