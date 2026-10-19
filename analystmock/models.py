from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Topic = Literal["SQL", "Статистика", "A/B-тесты", "Продуктовые метрики"]
TOPICS = ("SQL", "Статистика", "A/B-тесты", "Продуктовые метрики")


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: Topic
    prompt: str = Field(min_length=20, max_length=1800)
    reference_answer: str = Field(min_length=20, max_length=1800)
    criteria: list[str] = Field(min_length=2, max_length=5)


class Quiz(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[Question] = Field(min_length=3, max_length=3)


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correctness: int = Field(ge=0, le=5)
    completeness: int = Field(ge=0, le=3)
    clarity: int = Field(ge=0, le=2)
    strengths: list[str] = Field(max_length=3)
    errors: list[str] = Field(max_length=3)
    improvement: str = Field(min_length=1, max_length=600)
    sample_answer: str = Field(min_length=1, max_length=1800)
    uncertain: bool
    uncertainty_reason: str = Field(max_length=400)
    mode: Literal['ai', 'self_check'] = 'ai'

    @property
    def score(self) -> int:
        return self.correctness + self.completeness + self.clarity
