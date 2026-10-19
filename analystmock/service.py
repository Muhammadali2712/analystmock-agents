from analystmock.ai import AIUnavailable
from analystmock.db import Store
from analystmock.models import TOPICS, Feedback


class UserNotice(Exception):
    pass


class TrainingService:
    def __init__(self, store: Store, trainer, daily_limit: int = 40, question_banks=None,
                 self_check_topics: frozenset[str] = frozenset(),
                 available_topics: frozenset[str] | None = None):
        self.store = store
        self.trainer = trainer
        self.daily_limit = daily_limit
        self.question_banks = question_banks or {}
        self.self_check_topics = self_check_topics
        self.available_topics = available_topics

    def _reserve(self, user_id: int) -> None:
        if self.trainer is None:
            raise UserNotice("AI пока не подключён. Проверь настройки AI_PROVIDER и перезапусти бота.")
        if not self.store.reserve_request(user_id, self.daily_limit):
            raise UserNotice("На сегодня лимит AI-запросов исчерпан. Он обновится в 03:00 по Москве.")

    async def start(self, user_id: int, topic: str, vacancy: str = ""):
        if self.store.active(user_id):
            raise UserNotice("У тебя уже есть тренировка. Продолжи её или заверши командой /cancel.")
        if topic not in (*TOPICS, "Смешанная тренировка", "По вакансии"):
            raise UserNotice("Выбери тему кнопкой в меню.")
        if self.available_topics is not None and topic not in self.available_topics:
            raise UserNotice("Сейчас доступна тренировка по SQL с самопроверкой. Выбери SQL в меню.")
        if topic == "По вакансии":
            text = vacancy.strip()
            if len(text) < 60 or len(text) > 4000 or (text.startswith(("http://", "https://")) and " " not in text):
                raise UserNotice("Пришли текст требований и обязанностей из вакансии, от 60 до 4000 символов.")
        if topic in self.question_banks:
            quiz = self.question_banks[topic](self.store.recent_questions(user_id))
        else:
            self._reserve(user_id)
            quiz = await self.trainer.generate(topic, vacancy, self.store.recent_questions(user_id))
        if topic in TOPICS and any(question.topic != topic for question in quiz.questions):
            raise AIUnavailable("AI выбрал другую тему. Попробуй запустить тренировку ещё раз.")
        prompts = [question.prompt.strip().casefold() for question in quiz.questions]
        if len(set(prompts)) != len(prompts):
            raise AIUnavailable("AI повторил вопросы. Попробуй запустить тренировку ещё раз.")
        return self.store.create(user_id, topic, quiz)

    async def answer(self, user_id: int, message_id: int, text: str):
        if self.store.processed(user_id, message_id):
            raise UserNotice("Этот ответ уже сохранён. Нажми /start, чтобы продолжить.")
        session = self.store.active(user_id)
        if session is None:
            raise UserNotice("Сначала выбери тренировку в меню.")
        if session.awaiting_next:
            raise UserNotice("Ответ уже разобран. Нажми «Следующий вопрос».")
        if not 1 <= len(text.strip()) <= 4000:
            raise UserNotice("Пришли ответ текстом, от 1 до 4000 символов.")
        if session.label in self.self_check_topics:
            question = session.question
            feedback = Feedback(
                correctness=0,
                completeness=0,
                clarity=0,
                strengths=[],
                errors=[],
                improvement="\n".join("• " + criterion for criterion in question.criteria),
                sample_answer=question.reference_answer,
                uncertain=True,
                uncertainty_reason="Сверь ответ с критериями и примером самостоятельно.",
                mode="self_check",
            )
        else:
            self._reserve(user_id)
            feedback = await self.trainer.grade(session.question, text.strip())
        self.store.save_answer(session, message_id, text.strip(), feedback)
        return feedback, self.store.active(user_id)
