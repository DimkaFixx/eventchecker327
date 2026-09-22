import os
import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, time, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
VPS_1_IP = os.getenv("VPS_1_IP")
API_PORT = os.getenv("API_PORT", "4443")
API_SECRET_KEY = os.getenv("API_SECRET_KEY")

if not TOKEN or not VPS_1_IP or not API_SECRET_KEY:
    raise RuntimeError("Ошибка: Заполните переменные DISCORD_TOKEN, VPS_1_IP и API_SECRET_KEY в .env!")

API_URL = f"http://{VPS_1_IP}:{API_PORT}/online/327"

# Московский часовой пояс (UTC+3)
MSK_TZ = timezone(timedelta(hours=3))

# Расписание: опрос каждые 5 минут в 01 и 06 минуты часа
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
        await self.tree.sync()
        print("[Система] Слэш-команды успешно синхронизированы!")

bot = EventBot()

# Хранилище: {channel_id: {"server_id": int, "players": set(), "start_time": datetime}}
active_events = {}

async def poll_server(channel_id: int):
    """Делает асинхронный HTTP-запрос к API на VPS №1."""
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
                    
                    for player_nick in players:
                        event_data["players"].add(player_nick)

                    print(f"[Опрос] Канал {channel_id} | Сервер {server_id}: "
                          f"найдено {len(players)} чел. Всего за ивент: {len(event_data['players'])}")
                
                elif resp.status == 403:
                    print("[Ошибка 403] Неверный API_SECRET_KEY!")
                else:
                    print(f"[Ошибка API] Сервер {server_id} вернул HTTP-код {resp.status}")

    except aiohttp.ClientConnectorError:
        print(f"[Сетевая ошибка] Не удалось подключиться к {API_URL}.")
    except Exception as e:
        print(f"[Ошибка мониторинга]: {e}")

@tasks.loop(time=SCHEDULE_TIMES)
async def monitor_loop():
    if not active_events:
        return

    print("[Расписание] Наступило время планового опроса. Проверяем...")
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

    if channel_id in active_events:
        await interaction.response.send_message(
            "⚠️ В этой ветке **уже идет** мониторинг! Сначала завершите его командой `/eventend`.",
            ephemeral=True
        )
        return

    now_msk = datetime.now(MSK_TZ)

    # Сохраняем время старта
    active_events[channel_id] = {
        "server_id": server_id,
        "players": set(),
        "start_time": now_msk
    }

    start_str = now_msk.strftime("%H:%M")
    await interaction.response.send_message(
        f"🟢 Мониторинг **Сервера #{server_id}** запущен в **{start_str} (МСК)**!\n"
        f"⏳ Делаю первый опрос базы данных..."
    )

    # Первый мгновенный опрос
    await poll_server(channel_id)

    # Запуск планировщика
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
    start_time = event_info["start_time"]
    end_time = datetime.now(MSK_TZ)

    # Очищаем память
    del active_events[channel_id]

    time_range_str = f"{start_time.strftime('%H:%M')} – {end_time.strftime('%H:%M')} (МСК)"

    if not players:
        await interaction.response.send_message(
            f"ℹ️ Ивент завершен.\n"
            f"⏰ Время проведения: **{time_range_str}**\n"
            f"За это время на **Сервере #{server_id}** никто из 327 не зафиксирован."
        )
        return

    # Сортировка по алфавиту и нумерация
    sorted_players = sorted(list(players))
    numbered_lines = [f"{i}. {nick}" for i, nick in enumerate(sorted_players, start=1)]
    player_list_str = "\n".join(numbered_lines)

    # Шапка сообщения
    header = (
        f"📋 **Итоги ивента (Сервер #{server_id})**\n"
        f"⏰ Время проведения: **{time_range_str}**\n"
        f"👥 Всего бойцов: **{len(players)}** чел.\n"
    )

    # Если всё вместе влезает в лимит одного сообщения (до 2000 символов)
    full_message = f"{header}```{player_list_str}```"
    
    if len(full_message) <= 2000:
        await interaction.response.send_message(full_message)
    else:
        # Если список гигантский и превышает лимит Discord — аккуратно разбиваем
        await interaction.response.send_message(header)
        chunk = ""
        for line in numbered_lines:
            if len(chunk) + len(line) + 1 > 1900:
                await interaction.followup.send(f"```{chunk.strip()}```")
                chunk = ""
            chunk += line + "\n"
        if chunk:
            await interaction.followup.send(f"```{chunk.strip()}```")

if __name__ == "__main__":
    bot.run(TOKEN)