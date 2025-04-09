from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from config import Config, load_config

config: Config = load_config()
BOT_TOKEN: str = config.tg_bot.token

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

scheduler = AsyncIOScheduler()

button_add = KeyboardButton(text='Добавить задачу ➕')
button_delete = KeyboardButton(text='Удалить задачу ❌')
button_list = KeyboardButton(text='Мои задачи 📋')

kb_builder = ReplyKeyboardBuilder()
kb_builder.row(button_add, button_delete, button_list, width=2)

tasks = {}


class DialogState(StatesGroup):
    add_task_text = State()
    add_task_time = State()
    delete_task = State()


async def send_reminder(user_id: int, task_text: str):
    await bot.send_message(
        chat_id=user_id,
        text=f"🔔 Напоминание!\n\nЗадача: {task_text}"
    )


async def on_startup():
    scheduler.start()


@dp.message(CommandStart())
async def process_command_start(message: Message):
    welcome_text = (
        "👋 Привет! Я твой персональный помощник для управления задачами.\n\n"
        "📌 Вот что я умею:\n"
        "• Добавлять задачи с напоминаниями\n"
        "• Показывать список активных задач\n"
        "• Удалять выполненные задачи\n\n"
        "Выбери действие в меню ниже 👇"
    )
    await message.answer(
        text=welcome_text,
        reply_markup=kb_builder.as_markup(
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder='Выберите действие'
        )
    )


@dp.message(F.text == 'Добавить задачу ➕')
async def process_answer_task(message: Message, state: FSMContext):
    await state.set_state(DialogState.add_task_text)
    await message.answer('📝 Напиши текст задачи, о которой нужно напомнить:')


@dp.message(DialogState.add_task_text)
async def process_answer_task_time(message: Message, state: FSMContext):
    await state.update_data(task_text=message.text)
    await state.set_state(DialogState.add_task_time)
    await message.answer("⏳Теперь укажи время напоминания в формате:\n"
                         "ДД.ММ.ГГГГ ЧЧ:ММ")


@dp.message(DialogState.add_task_time)
async def process_add_task_time(message: Message, state: FSMContext):
    user_id = str(message.chat.id)
    data = await state.get_data()
    current_time = datetime.now() + timedelta(hours=3)
    try:
        task_time = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer(
            "❌ Неверный формат времени!\n"
            "Пожалуйста, введите дату в формате ДД.ММ.ГГГГ ЧЧ:ММ\n")
        return

    if user_id not in tasks:
        tasks[user_id] = []
    new_task = {
        "id": len(tasks[user_id]) + 1,
        "text": data['task_text'],
        "time": current_time.strftime("%d.%m.%Y %H:%M"),
        "task_time": task_time.strftime("%d.%m.%Y %H:%M")
    }
    scheduler.add_job(
        send_reminder,
        trigger=DateTrigger(task_time - timedelta(hours=3)),
        args=(user_id, new_task['text']),
        id=f"reminder_{user_id}_{new_task['id']}"
    )
    print(task_time - timedelta(hours=3))
    tasks[str(user_id)].append(new_task)
    await state.clear()
    await message.answer(f"✅ Задача успешно добавлена!\n\n"
                         f"📌 Текст: {new_task['text']}\n"
                         f"⏰ Напоминание: {new_task['task_time']}")


@dp.message(F.text == 'Удалить задачу ❌')
async def process_answer_delete(message: Message, state: FSMContext):
    await message.answer('Ведите номер задачи которую нужно удалить')
    await state.set_state(DialogState.delete_task)


@dp.message(DialogState.delete_task)
async def process_delete_task(message: Message, state: FSMContext):
    user_id = str(message.chat.id)
    try:
        task_id = int(message.text)
    except ValueError:
        await message.answer("❌ Некорректный номер задачи. Введите число.")
        return
    if user_id not in tasks or not tasks[user_id]:
        await message.answer("📭 Список задач пуст")
        await state.clear()
        return
    initial_count = len(tasks[user_id])
    tasks[user_id] = [task for task in tasks[user_id] if task["id"] != task_id]
    if len(tasks[user_id]) < initial_count:
        await message.answer(f'✅ Задача №{task_id} успешно удалена')
    else:
        await message.answer(f"⚠️ Задача №{task_id} не найдена")
    await state.clear()


@dp.message(F.text == 'Мои задачи 📋')
async def process_list_command(message: Message):
    user_id = str(message.chat.id)
    user_tasks = tasks.get(user_id, [])
    if not user_tasks:
        await message.answer('📭 У вас пока нет активных задач')
        return
    for task in user_tasks:
        await message.answer(f'Задача № {task["id"]}\n\n'
                             f'📝Задача: {task["text"]}\n'
                             f'⏳Создана: {task["time"]}\n'
                             f'⏰Напоминание: {task["task_time"]}')


if __name__ == '__main__':
    dp.startup.register(on_startup)
    dp.run_polling(bot)
