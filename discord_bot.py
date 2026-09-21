import os
import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks
from datetime import time, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# Загрузка переменных окружения
TOKEN = os.getenv("DISCORD_TOKEN")
VPS_1_IP = os.getenv("VPS_1_IP")
API_PORT = os.getenv("API_PORT", "4443")
API_SECRET_KEY = os.getenv("API_SECRET_KEY")

if not TOKEN or not VPS_1_IP or not API_SECRET_KEY:
    raise RuntimeError("Ошибка: Заполните переменные DISCORD_TOKEN, VPS_1_IP и API_SECRET_KEY в .env!")

API_URL = f"http://{VPS_1_IP}:{API_PORT}/online/327"

# Московский часовой пояс (UTC+3)
MSK_TZ = timezone(timedelta(hours=3))

# Расписание: опрос каждые 5 минут, начиная с 01-й и 06-й минут часа
# (01, 06, 11, 16, 21, 26, 31, 36, 41, 46, 51, 56)
SCHEDULE_TIMES = [
    time(hour=h, minute=m, tzinfo=MSK_TZ)
    for h in range(24)
    for m in range(1, 60, 5)
]

class EventBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Синхронизация слэш-команд с серверами Discord
        await self.tree.sync()
        print("[Система] Слэш-команды успешно синхронизированы!")

bot = EventBot()

# Хранилище сессий: {channel_id: {"server_id": int, "players": set()}}
active_events = {}

async def poll_server(channel_id: int):
    """Делает асинхронный HTTP-запрос к API на VPS №1 и обновляет список игроков."""
    if channel_id not in active_events:
        return

    event_data = active_events[channel_id]
    server_id = event_data["server_id"]
    headers = {"X-API-Key": API_SECRET_KEY}
    timeout = aiohttp.ClientTimeout(total=10)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            params = {"server": server_id}
            async with session.get(API_URL, params=params, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    players = data.get("players", [])
                    
                    # Множество (set) гарантирует отсутствие дублей
                    for player_nick in players:
                        event_data["players"].add(player_nick)

                    print(f"[Опрос] Канал {channel_id} | Сервер {server_id}: "
                          f"найдено {len(players)} чел. Всего за ивент: {len(event_data['players'])}")
                
                elif resp.status == 403:
                    print("[Ошибка 403] Неверный API_SECRET_KEY! Проверьте .env файл.")
                else:
                    print(f"[Ошибка API] Сервер {server_id} вернул HTTP-код {resp.status}")

    except aiohttp.ClientConnectorError:
        print(f"[Сетевая ошибка] Не удалось достучаться до {API_URL}. Проверьте фаервол UFW на VPS №1.")
    except Exception as e:
        print(f"[Ошибка мониторинга]: {e}")

# Фоновый планировщик строго по расписанию (01 и 06 минуты)
@tasks.loop(time=SCHEDULE_TIMES)
async def monitor_loop():
    if not active_events:
        return

    print("[Расписание] Наступило время опроса по графику. Проверяем сервера...")
    for channel_id in list(active_events.keys()):
        await poll_server(channel_id)

@bot.event
async def on_ready():
    print("=" * 40)
    print(f"Бот успешно запущен: {bot.user.name} (ID: {bot.user.id})")
    print("Статус: ОНЛАЙН")
    print("=" * 40)

# ==================== СЛЭШ-КОМАНДЫ ====================

@bot.tree.command(name="eventstart", description="Начать сбор онлайна для ивента")
@app_commands.describe(server_num="Номер игрового сервера")
@app_commands.choices(server_num=[
    app_commands.Choice(name="Сервер 1", value=1),
    app_commands.Choice(name="Сервер 2", value=2)
])
async def eventstart(interaction: discord.Interaction, server_num: app_commands.Choice[int]):
    channel_id = interaction.channel_id
    server_id = server_num.value

    # Защита от запуска в одной и той же ветке
    if channel_id in active_events:
        await interaction.response.send_message(
            "⚠️ В этой ветке **уже идет** мониторинг! Сначала завершите его командой `/eventend`.",
            ephemeral=True
        )
        return

    # Создаем запись в ОЗУ
    active_events[channel_id] = {
        "server_id": server_id,
        "players": set()
    }

    # Мгновенно отвечаем в Discord, чтобы избежать таймаута интеракции
    await interaction.response.send_message(
        f"🟢 Мониторинг **Сервера #{server_id}** запущен в этой ветке!\n"
        f"⏳ Делаю первый опрос базы данных..."
    )

    # 1. Первый мгновенный опрос сервера
    await poll_server(channel_id)

    # 2. Запускаем фоновый цикл по расписанию, если он еще не крутится
    if not monitor_loop.is_running():
        monitor_loop.start()


@bot.tree.command(name="eventend", description="Завершить ивент и получить список игроков")
async def eventend(interaction: discord.Interaction):
    channel_id = interaction.channel_id

    if channel_id not in active_events:
        await interaction.response.send_message(
            "❌ В этой ветке нет активного ивента! Запустите его командой `/eventstart`.",
            ephemeral=True
        )
        return

    event_info = active_events[channel_id]
    server_id = event_info["server_id"]
    players = event_info["players"]

    # Очищаем память сразу же
    del active_events[channel_id]

    if not players:
        await interaction.response.send_message(
            f"ℹ️ За время ивента на **Сервере #{server_id}** бойцы 327 не зафиксированы."
        )
        return

    # Сортировка по алфавиту и создание нумерованных строк
    sorted_players = sorted(list(players))
    numbered_lines = [f"{i}. {nick}" for i, nick in enumerate(sorted_players, start=1)]

    # Отправляем шапку сообщения
    await interaction.response.send_message(
        f"📋 **Итоги ивента (Сервер #{server_id})**\nВсего бойцов: **{len(players)}** чел."
    )

    # Дробим список на блоки до 1900 символов внутри ``` для удобного копирования
    chunk = ""
    for line in numbered_lines:
        if len(chunk) + len(line) + 1 > 1900:
            await interaction.followup.send(f"```{chunk.strip()}```")
            chunk = ""
        chunk += line + "\n"

    # Отправляем остаток
    if chunk:
        await interaction.followup.send(f"```{chunk.strip()}```")

if __name__ == "__main__":
    bot.run(TOKEN)