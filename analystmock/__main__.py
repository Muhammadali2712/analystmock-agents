import argparse
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from analystmock.ai import OllamaTrainer, OpenAITrainer
from analystmock.bot import create_router
from analystmock.config import load_settings
from analystmock.db import Store
from analystmock.service import TrainingService
from analystmock.sql_bank import make_sql_quiz


async def run(settings) -> None:
    bot = Bot(settings.telegram_token)
    store = Store(settings.database_path)
    trainer = None
    try:
        if settings.provider == "ollama":
            trainer = OllamaTrainer(settings.model, settings.ollama_url)
        elif settings.openai_api_key:
            trainer = OpenAITrainer(settings.openai_api_key, settings.model)
        dispatcher = Dispatcher()
        local_sql = settings.provider == "ollama"
        service = TrainingService(
            store,
            trainer,
            settings.daily_request_limit,
            {"SQL": make_sql_quiz},
            self_check_topics=frozenset(),
            available_topics=None,
        )
        dispatcher.include_router(create_router(settings, service))
        webhook = await bot.get_webhook_info()
        if webhook.url:
            raise RuntimeError(
                "У этого бота уже настроен webhook. Используй новый бот для проекта "
                "или отключи старое подключение перед запуском."
            )
        await bot.set_my_commands([
            BotCommand(command="start", description="Меню или продолжение тренировки"),
            BotCommand(command="progress", description="Мой прогресс"),
            BotCommand(command="history", description="История тренировок"),
            BotCommand(command="review", description="Последний разбор"),
            BotCommand(command="flag", description="Отметить ошибку в последнем разборе"),
            BotCommand(command="cancel", description="Завершить тренировку"),
            BotCommand(command="me", description="Мой Telegram ID"),
            BotCommand(command="help", description="Как пользоваться ботом"),
        ])
        logging.info(
            "AnalystMock started. Provider: %s. Allowed participants: %d",
            settings.provider,
            len(settings.allowed_user_ids),
        )
        await dispatcher.start_polling(bot, allowed_updates=["message"], close_bot_session=False)
    finally:
        store.close()
        if trainer:
            await trainer.close()
        await bot.session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="AnalystMock Telegram bot")
    parser.add_argument("--check", action="store_true", help="Проверить настройки без сетевых запросов")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    try:
        settings = load_settings()
        if arguments.check:
            print("Telegram-токен:", "задан" if settings.telegram_token else "не задан")
            print("AI-провайдер:", settings.provider)
            print("Ключ OpenAI:", "задан" if settings.openai_api_key else "не задан")
            print("Участников с доступом:", len(settings.allowed_user_ids))
            print("Модель:", settings.model)
            print("Лимит AI-запросов на участника в сутки:", settings.daily_request_limit)
            print("Ollama URL:", settings.ollama_url)
            print("Проверка локальная. Доступ к Telegram и AI-провайдеру не проверялся.")
            return
        if not settings.telegram_token:
            raise ValueError("Добавь TELEGRAM_BOT_TOKEN в .env. Образец настроек: .env.example.")
        asyncio.run(run(settings))
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from None
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        raise SystemExit(
            f"Не удалось запустить бот ({type(exc).__name__}). "
            "Проверь токен, соединение и что не запущена вторая копия бота."
        ) from None


if __name__ == "__main__":
    main()
