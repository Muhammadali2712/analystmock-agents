import asyncio
import logging

from aiogram import BaseMiddleware, Router
from aiogram.enums import ChatAction, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.utils.chat_action import ChatActionSender

from analystmock.ai import AIUnavailable
from analystmock.models import TOPICS, Feedback
from analystmock.service import TrainingService, UserNotice

logger = logging.getLogger(__name__)


def keyboard(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text) for text in row] for row in rows],
        resize_keyboard=True,
    )


MAIN = keyboard([
    ["Быстрая тренировка", "По теме"],
    ["По вакансии", "Мой прогресс"],
    ["История", "Последний разбор"],
])
SQL_MAIN = keyboard([["SQL", "Мой прогресс"], ["История", "Последний разбор"]])
SQL_NEXT_MENU = keyboard([["Следующий вопрос"], ["Последний разбор"], ["Завершить тренировку"]])
TOPIC_MENU = keyboard([["SQL", "Статистика"], ["A/B-тесты", "Продуктовые метрики"], ["Назад"]])
ANSWER_MENU = keyboard([["Мой прогресс", "История"], ["Завершить тренировку"]])
NEXT_MENU = keyboard([["Следующий вопрос"], ["Ошибка в разборе", "Последний разбор"], ["Завершить тренировку"]])

HELP = (
    "AnalystMock помогает готовиться к собеседованиям на Product Analyst.\n\n"
    "Выбери тему, смешанную тренировку или пришли текст вакансии. "
    "В каждой тренировке 3 вопроса. Отвечай одним текстовым сообщением.\n\n"
    "Оценка: правильность 0-5, полнота 0-3, понятность 0-2. "
    "AI может ошибаться. Если сомневаешься в разборе, нажми «Ошибка в разборе» "
    "или /flag. Спорные оценки не входят в средние баллы.\n\n"
    "/start - меню или продолжение\n"
    "/next - следующий вопрос\n"
    "/progress - результаты\n"
    "/history - последние тренировки\n"
    "/review - последний разбор\n"
    "/flag - отметить последний разбор как спорный\n"
    "/cancel - завершить текущую тренировку\n"
    "/me - твой Telegram ID\n\n"
    "Провайдер AI выбирается в .env. В режиме Ollama ответы обрабатываются локально "
    "на компьютере, где запущен бот. В режиме OpenAI данные отправляются в OpenAI. "
    "Не присылай пароли и конфиденциальные рабочие данные."
)


def split_text(text: str) -> list[str]:
    parts = []
    while len(text) > 1600:
        position = text.rfind("\n", 0, 1600)
        if position < 800:
            position = 1600
        parts.append(text[:position])
        text = text[position:].lstrip("\n")
    if text:
        parts.append(text)
    return parts


async def send(message: Message, text: str, markup=None) -> None:
    parts = split_text(text)
    for index, part in enumerate(parts):
        await message.answer(part, reply_markup=markup if index == len(parts) - 1 else None)


def feedback_text(feedback: Feedback) -> str:
    if feedback.mode == "self_check":
        return (
            "Самопроверка: баллы не начисляются. Сверь свой ответ с критериями.\n\n"
            "Критерии:\n" + feedback.improvement + "\n\n"
            "Пример ответа:\n" + feedback.sample_answer
        )
    if feedback.uncertain:
        heading = "Разбор требует проверки. В статистику оценка не включена."
    else:
        heading = (
            f"Оценка AI: {feedback.score}/10\n"
            f"Правильность: {feedback.correctness}/5 · Полнота: {feedback.completeness}/3 · "
            f"Понятность: {feedback.clarity}/2"
        )
    sections = [heading]
    if feedback.strengths:
        sections.append("Что получилось:\n" + "\n".join(f"• {item}" for item in feedback.strengths))
    if feedback.errors:
        sections.append("Что исправить:\n" + "\n".join(f"• {item}" for item in feedback.errors))
    if feedback.uncertain:
        sections.append("Причина сомнения: " + feedback.uncertainty_reason)
    sections.append("Что повторить:\n" + feedback.improvement)
    sections.append("Пример ответа:\n" + feedback.sample_answer)
    return "\n\n".join(sections)


def current_menu(service: TrainingService, user_id: int):
    session = service.store.active(user_id)
    if session:
        if session.awaiting_next and session.label in service.self_check_topics:
            return SQL_NEXT_MENU
        return NEXT_MENU if session.awaiting_next else ANSWER_MENU
    if service.store.waiting_for_vacancy(user_id):
        return keyboard([["Назад"]])
    return SQL_MAIN if service.available_topics == frozenset({"SQL"}) else MAIN


class AccessMiddleware(BaseMiddleware):
    def __init__(self, allowed: frozenset[int], service: TrainingService):
        self.allowed = allowed
        self.service = service
        self.locks = {user_id: asyncio.Lock() for user_id in allowed}

    async def __call__(self, handler, event: Message, data):
        if event.chat.type != ChatType.PRIVATE or event.from_user is None:
            return
        user_id = event.from_user.id
        command = (event.text or "").split(maxsplit=1)
        if command and command[0].split("@")[0] == "/me":
            await event.answer(f"Твой Telegram ID: {user_id}")
            return
        if user_id not in self.allowed:
            await event.answer(
                "Сейчас бот доступен только участникам закрытого теста.\n"
                f"Твой Telegram ID: {user_id}. Передай его создателю бота для настройки доступа."
            )
            return
        async with self.locks[user_id]:
            try:
                return await handler(event, data)
            except (UserNotice, AIUnavailable) as exc:
                await send(event, str(exc), current_menu(self.service, user_id))
            except TelegramAPIError as exc:
                logger.warning("Telegram delivery failed: %s", type(exc).__name__)
            except Exception as exc:
                logger.error("Handler failed: %s", type(exc).__name__)
                await event.answer("Не получилось обработать сообщение. Нажми /start, чтобы продолжить.")


async def show_question(message: Message, session) -> None:
    await send(
        message,
        f"Вопрос {session.position + 1}/3 · {session.question.topic}\n\n"
        f"{session.question.prompt}\n\nОтправь ответ одним сообщением.",
        ANSWER_MENU,
    )


async def show_progress(message: Message, service: TrainingService, user_id: int) -> None:
    stats = service.store.statistics(user_id)
    lines = [
        "Твой прогресс",
        f"Завершено тренировок: {stats['completed']}",
        f"Разобрано ответов: {stats['answers']}",
        f"Ответов без автоматической оценки: {stats['uncertain']}",
        f"Отмечено тобой как спорные: {stats['flagged']}",
    ]
    if stats["topics"]:
        lines.append("\nСредний балл по темам:")
        for row in stats["topics"]:
            lines.append(f"{row['topic']}: {row['average']:.1f}/10 ({row['count']} ответов)")
        weakest = stats["topics"][0]
        lines.append(f"\nСамый низкий средний балл пока по теме «{weakest['topic']}». Её можно повторить в меню.")
    if len(stats["scores"]) == 10:
        scores = stats["scores"]
        lines.append(
            f"\nПоследние 5 ответов: {sum(scores[:5]) / 5:.1f}/10. "
            f"Предыдущие 5: {sum(scores[5:]) / 5:.1f}/10."
        )
    if stats["topics"]:
        lines.append("\nЭто оценки AI на разных заданиях, а не объективная оценка готовности к интервью.")
    elif service.self_check_topics:
        lines.append("\nОтветы с самопроверкой сохраняются без баллов.")
    await send(message, "\n".join(lines), current_menu(service, user_id))


def create_router(settings, service: TrainingService) -> Router:
    router = Router()
    router.message.outer_middleware(AccessMiddleware(settings.allowed_user_ids, service))

    @router.message()
    async def handle(message: Message):
        user_id = message.from_user.id
        text = (message.text or "").strip()
        command = text.split(maxsplit=1)[0].split("@")[0] if text else ""
        store = service.store

        if not text:
            await message.answer("Пока принимаю только текст. Пришли ответ одним сообщением.")
            return

        if command == "/start" or text == "Назад":
            session = store.active(user_id)
            if session and session.awaiting_next:
                await send(message, feedback_text(store.latest_feedback(user_id)), current_menu(service, user_id))
            elif session:
                await show_question(message, session)
            else:
                store.set_vacancy_mode(user_id, False)
                intro = (
                    "Привет! Я AnalystMock. Задам 3 вопроса по SQL, а после каждого ответа "
                    "покажу критерии и пример решения. Выбери SQL, чтобы начать. Правила: /help."
                    if service.available_topics == frozenset({"SQL"})
                    else "Привет! Я AnalystMock. Помогу потренироваться перед собеседованием "
                         "на Product Analyst: задам 3 вопроса и разберу твои ответы.\n\n"
                         "Выбери, с чего начнём. Правила и информация об обработке ответов: /help."
                )
                await send(message, intro, current_menu(service, user_id))
            return

        if command == "/help":
            if service.available_topics == frozenset({"SQL"}):
                help_text = (
                    "Сейчас доступны три SQL-вопроса за тренировку. Ответь одним сообщением, "
                    "затем сравни ответ с критериями и примером. Автоматических баллов нет.\n\n"
                    "/start - меню, /next - следующий вопрос, /progress - прогресс, "
                    "/history - история, /review - последний разбор, "
                    "/cancel - остановить тренировку, /me - твой Telegram ID."
                )
            else:
                help_text = HELP
            await send(message, help_text, current_menu(service, user_id))
            return

        if command == "/cancel" or text == "Завершить тренировку":
            store.cancel(user_id)
            await send(message, "Тренировка остановлена. Ответы сохранены.", current_menu(service, user_id))
            return

        if command == "/progress" or text == "Мой прогресс":
            await show_progress(message, service, user_id)
            return

        if command == "/history" or text == "История":
            rows = store.history(user_id)
            labels = {"active": "в процессе", "completed": "завершена", "cancelled": "остановлена"}
            lines = ["Последние тренировки (время UTC):"]
            for row in rows:
                score = f"{row['average']:.1f}/10" if row["average"] is not None else "нет оценки"
                lines.append(
                    f"{row['created_at']} · {row['label']}\n"
                    f"{labels[row['status']]} · ответов {row['answered']}/3 · {score}"
                )
            await send(message, "\n\n".join(lines) if rows else "Тренировок пока нет.", current_menu(service, user_id))
            return

        if command == "/review" or text == "Последний разбор":
            feedback = store.latest_feedback(user_id)
            await send(message, feedback_text(feedback) if feedback else "Разборов пока нет.", current_menu(service, user_id))
            return

        if command == "/flag" or text == "Ошибка в разборе":
            latest = store.latest_feedback(user_id)
            if latest is not None and latest.mode == "self_check":
                await message.answer("В самопроверке нет AI-оценки. Ответ уже сохранён без баллов.")
                return
            marked = store.flag_latest(user_id)
            await message.answer(
                "Отметил последний разбор как спорный и исключил его из средних баллов. "
                "Сверьте его с учебными материалами."
                if marked else "Пока нет разбора, который можно отметить."
            )
            return

        if command == "/next" or text == "Следующий вопрос":
            session = store.next_question(user_id)
            if session:
                await show_question(message, session)
            else:
                await send(message, "Выбери новую тренировку.", current_menu(service, user_id))
            return

        if text.startswith("/"):
            await message.answer("Не знаю эту команду. Список команд: /help.")
            return

        if store.active(user_id):
            if text in ("По теме", "По вакансии", "Быстрая тренировка"):
                raise UserNotice("Сначала закончи текущую тренировку или нажми /cancel.")
            if store.active(user_id).label not in service.self_check_topics:
                await message.answer("Разбираю ответ…")
            async with ChatActionSender(bot=message.bot, chat_id=message.chat.id, action=ChatAction.TYPING):
                feedback, active = await service.answer(user_id, message.message_id, text)
            await send(message, feedback_text(feedback), current_menu(service, user_id))
            if active is None:
                message_text = (
                    "Тренировка завершена. Прогресс сохранён без баллов."
                    if feedback.mode == "self_check"
                    else "Тренировка завершена. Результаты сохранены в «Мой прогресс». "
                         "Если последний разбор ошибочен, отметь его командой /flag."
                )
                await send(message, message_text, current_menu(service, user_id))
            return

        if text == "По теме":
            store.set_vacancy_mode(user_id, False)
            menu = keyboard([["SQL"], ["Назад"]]) if service.available_topics == frozenset({"SQL"}) else TOPIC_MENU
            await send(message, "Выбери тему:", menu)
            return

        if text == "По вакансии":
            if service.available_topics == frozenset({"SQL"}):
                raise UserNotice("Сейчас доступна только тренировка по SQL. Выбери SQL в меню.")
            store.set_vacancy_mode(user_id, True)
            await send(
                message,
                "Пришли одним сообщением текст обязанностей и требований из вакансии, "
                "от 60 до 4000 символов. Если у тебя ссылка, скопируй текст со страницы. "
                "Чтобы вернуться, нажми «Назад».",
                keyboard([["Назад"]]),
            )
            return

        vacancy = ""
        if text in TOPICS:
            topic = text
        elif text == "Быстрая тренировка":
            topic = "Смешанная тренировка"
        elif store.waiting_for_vacancy(user_id):
            topic, vacancy = "По вакансии", text
        else:
            await send(message, "Выбери тренировку в меню.", current_menu(service, user_id))
            return

        if service.available_topics is not None and topic not in service.available_topics:
            raise UserNotice("Сейчас доступна тренировка по SQL с самопроверкой. Выбери SQL в меню.")
        await message.answer("Готовлю вопросы…")
        async with ChatActionSender(bot=message.bot, chat_id=message.chat.id, action=ChatAction.TYPING):
            session = await service.start(user_id, topic, vacancy)
        await show_question(message, session)

    return router
