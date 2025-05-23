from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, CallbackQuery, InlineKeyboardButton, \
    InlineKeyboardMarkup, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram_calendar import SimpleCalendar, SimpleCalendarCallback
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
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
    select_hour = State()
    select_minute = State()
    delete_task = State()
    choose_input_method = State()
    manual_datetime_input = State()


def build_hour_keyboard():
    buttons = [
        InlineKeyboardButton(text=f"{h:02d}:00", callback_data=f"hour_{h}")
        for h in range(24)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        buttons[i:i + 4] for i in range(0, len(buttons), 4)
    ])


def build_minute_keyboard():
    buttons = [
        InlineKeyboardButton(text=f"{m:02d} мин", callback_data=f"min_{m}")
        for m in range(0, 60, 5)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        buttons[i:i + 4] for i in range(0, len(buttons), 4)
    ])


async def send_reminder(user_id: int, task_text: str, task_id: int):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑 Удалить задачу", callback_data=f"reminder_delete:{task_id}")
        ]
    ])

    message_text = (
        f"🔔 <b>Напоминание о задаче</b>\n\n"
        f"📌 <i>{task_text}</i>\n\n"
    )

    await bot.send_message(
        chat_id=user_id,
        text=message_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("reminder_delete:"))
async def handle_delete_reminder(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    user_id = str(callback.message.chat.id)
    tasks[user_id] = [task for task in tasks[user_id] if task["id"] != task_id]
    await callback.answer("Задача удалена ✅")
    await callback.message.edit_reply_markup(reply_markup=None)


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


@dp.message(F.text == "Добавить задачу ➕")
async def process_answer_task(message: Message, state: FSMContext):
    await state.set_state(DialogState.add_task_text)
    await message.answer("📝 Напиши текст задачи, о которой нужно напомнить:")


@dp.message(DialogState.add_task_text)
async def process_answer_task_time(message: Message, state: FSMContext):
    await state.update_data(task_text=message.text)
    await state.set_state(DialogState.choose_input_method)

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📆 Выбрать дату из календаря")],
            [KeyboardButton(text="⌨️ Ввести вручную")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await message.answer("Как хочешь задать дату и время напоминания?", reply_markup=keyboard)


@dp.message(DialogState.choose_input_method)
async def choose_input_method(message: Message, state: FSMContext):
    await message.answer("✅ Выбор подтверждён", reply_markup=ReplyKeyboardRemove())
    if message.text == "📆 Выбрать дату из календаря":
        await state.set_state(DialogState.add_task_time)
        calendar = SimpleCalendar(locale="ru_RU.utf8")
        await message.answer("📆 Выберите дату:", reply_markup=await calendar.start_calendar())

    elif message.text == "⌨️ Ввести вручную":
        await state.set_state(DialogState.manual_datetime_input)
        await message.answer(
            "✍️ Введите дату и время в формате: <b>ДД.ММ.ГГГГ ЧЧ:ММ</b>\n"
            "Например: <code>12.04.2025 15:30</code>",
            parse_mode="HTML"
        )

    else:
        await message.answer("⚠️ Пожалуйста, выбери один из предложенных вариантов.")


@dp.message(DialogState.manual_datetime_input)
async def process_manual_datetime_input(message: Message, state: FSMContext):
    try:
        user_input = message.text.strip()
        task_datetime = datetime.strptime(user_input, "%d.%m.%Y %H:%M")
        if task_datetime < datetime.now():
            await message.answer("❌ Время должно быть в будущем! Попробуй ещё раз.")
            return

        data = await state.get_data()
        task_text = data["task_text"]
        user_id = str(message.chat.id)

        new_task = {
            "id": len(tasks.get(user_id, [])) + 1,
            "text": task_text,
            "time": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "task_time": task_datetime.strftime("%d.%m.%Y %H:%M")
        }

        if user_id not in tasks:
            tasks[user_id] = []
        tasks[user_id].append(new_task)

        scheduler.add_job(
            send_reminder,
            trigger=DateTrigger(task_datetime),
            args=(user_id, new_task["text"], new_task["id"]),
            id=f"reminder_{user_id}_{new_task['id']}"
        )

        await state.clear()
        await message.answer(
            f"✅ Задача успешно добавлена!\n\n"
            f"📌 Текст: {new_task['text']}\n"
            f"⏰ Напоминание: {new_task['task_time']}",
            reply_markup=kb_builder.as_markup(resize_keyboard=True, one_time_keyboard=False)
        )

    except ValueError:
        await message.answer("⚠️ Неверный формат. Введите дату и время как в примере: <code>12.04.2025 15:30</code>",
                             parse_mode="HTML")


@dp.callback_query(SimpleCalendarCallback.filter(), DialogState.add_task_time)
async def process_simple_calendar(callback_query: CallbackQuery, callback_data: dict, state: FSMContext):
    safe_locale = "ru_RU.utf8"
    calendar = SimpleCalendar(locale=safe_locale, show_alerts=True)
    calendar.set_dates_range(datetime(2022, 1, 1), datetime(2025, 12, 31))

    selected, date = await calendar.process_selection(callback_query, callback_data)

    if selected:
        await state.update_data(task_date=date)
        await state.set_state(DialogState.select_hour)
        await callback_query.message.answer("🕐 Выберите час:", reply_markup=build_hour_keyboard())


@dp.callback_query(F.data.startswith("hour_"), DialogState.select_hour)
async def process_select_hour(callback: CallbackQuery, state: FSMContext):
    hour = int(callback.data.split("_")[1])
    await state.update_data(hour=hour)
    await state.set_state(DialogState.select_minute)
    await callback.message.answer("🕑 Выберите минуты:", reply_markup=build_minute_keyboard())


@dp.callback_query(F.data.startswith("min_"), DialogState.select_minute)
async def process_select_minute(callback: CallbackQuery, state: FSMContext):
    minute = int(callback.data.split("_")[1])
    data = await state.get_data()
    task_text = data["task_text"]
    task_date = data["task_date"]
    hour = data["hour"]

    task_datetime = datetime(
        year=task_date.year,
        month=task_date.month,
        day=task_date.day,
        hour=hour,
        minute=minute
    )

    user_id = str(callback.message.chat.id)
    current_time = datetime.now()

    if task_datetime < current_time:
        await callback.message.answer("❌ Время должно быть в будущем!")
        return

    new_task = {
        "id": len(tasks.get(user_id, [])) + 1,
        "text": task_text,
        "time": current_time.strftime("%d.%m.%Y %H:%M"),
        "task_time": task_datetime.strftime("%d.%m.%Y %H:%M")
    }

    if user_id not in tasks:
        tasks[user_id] = []
    tasks[user_id].append(new_task)

    scheduler.add_job(
        send_reminder,
        trigger=DateTrigger(task_datetime),
        args=(user_id, new_task["text"], new_task["id"]),
        id=f"reminder_{user_id}_{new_task['id']}"
    )

    await state.clear()
    await callback.message.answer(
        f"✅ Задача успешно добавлена!\n\n"
        f"📌 Текст: {new_task['text']}\n"
        f"⏰ Напоминание: {new_task['task_time']}",
        reply_markup=kb_builder.as_markup(resize_keyboard=True, one_time_keyboard=False)
    )

    await callback.answer(
        reply_markup=kb_builder.as_markup(
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder='Выберите действие'
        )
    )


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


@dp.message()
async def other_message(message: Message):
    await message.answer(
        text="Выбери действие в меню ниже 👇",
        reply_markup=kb_builder.as_markup(
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder='Выберите действие'
        )
    )


if __name__ == '__main__':
    dp.startup.register(on_startup)
    dp.run_polling(bot)
