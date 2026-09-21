import os
import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
VPS_1_IP = os.getenv("VPS_1_IP")
API_PORT = os.getenv("API_PORT", "4443")
API_SECRET_KEY = os.getenv("API_SECRET_KEY")

if not TOKEN or not VPS_1_IP or not API_SECRET_KEY:
    raise RuntimeError("Ошибка: Заполните переменные DISCORD_TOKEN, VPS_1_IP и API_SECRET_KEY в .env!")

API_URL = f"http://{VPS_1_IP}:{API_PORT}/online/327"

class EventBot(discord.Client):
    def __init__(self):
        # Намерения: для слэш-команд достаточно дефолтных
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Регистрация слэш-команд в Discord при старте
        await self.tree.sync()
        print("[Система] Слэш-команды успешно синхронизированы!")

bot = EventBot()

# Хранилище сессий ивентов: {channel_id: {"server_id": int, "players": set()}}
active_events = {}

@tasks.loop(minutes=5.0)
async def monitor_loop():
    """Каждые 5 минут опрашивает API на VPS №1."""
    if not active_events:
        monitor_loop.stop()
        print("[Мониторинг] Нет активных событий. Фоновый цикл остановлен.")
        return

    headers = {"X-API-Key": API_SECRET_KEY}
    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for channel_id, event_data in list(active_events.items()):
            server_id = event_data["server_id"]
            try:
                params = {"server": server_id}
                async with session.get(API_URL, params=params, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        players = data.get("players", [])
                        
                        # Добавляем в set() — дубли исключаются автоматически
                        for player_nick in players:
                            event_data["players"].add(player_nick)

                        print(f"[Успех] Канал {channel_id}: Сервер {server_id} опрошен. "
                              f"Онлайн сейчас: {len(players)}. Всего уникальных за ивент: {len(event_data['players'])}")
                    
                    elif resp.status == 403:
                        print("[Ошибка 403] Неверный API_SECRET_KEY! Проверьте .env.")
                    else:
                        print(f"[Ошибка API] Сервер {server_id} ответил со статусом: {resp.status}")

            except aiohttp.ClientConnectorError:
                print(f"[Сетевая ошибка] Не удалось подключиться к {API_URL}. Проверьте фаервол UFW на VPS №1.")
            except Exception as e:
                print(f"[Ошибка мониторинга]: {e}")

@bot.event
async def on_ready():
    print("=" * 40)
    print(f"Бот успешно запущен: {bot.user.name} (ID: {bot.user.id})")
    print("Статус: ОНЛАЙН")
    print("=" * 40)

# ==================== СЛЭШ-КОМАНДЫ ====================

@bot.tree.command(name="eventstart", description="Начать сбор онлайна для ивента")
@app_commands.describe(server_num="Номер сервера (1 или 2)")
@app_commands.choices(server_num=[
    app_commands.Choice(name="Сервер 1", value=1),
    app_commands.Choice(name="Сервер 2", value=2)
])
async def eventstart(interaction: discord.Interaction, server_num: app_commands.Choice[int]):
    channel_id = interaction.channel_id
    server_id = server_num.value

    # Защита от двойного запуска в одном канале
    if channel_id in active_events:
        await interaction.response.send_message(
            "⚠️ В этой ветке **уже идет** сбор онлайна! Завершите его командой `/eventend`.",
            ephemeral=True
        )
        return

    # Инициализация хранилища (set гарантирует уникальность)
    active_events[channel_id] = {
        "server_id": server_id,
        "players": set()
    }

    await interaction.response.send_message(
        f"🟢 Мониторинг **Сервера #{server_id}** запущен в этой ветке!\n"
        f"Опрос базы данных происходит раз в 5 минут. По окончании введите `/eventend`."
    )

    # Запуск цикла, если он спал
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

    if players:
        # Сортировка по алфавиту
        sorted_players = sorted(list(players))
        
        # Нумерованный список
        player_list_str = "\n".join(f"{i}. {nick}" for i, nick in enumerate(sorted_players, start=1))

        # Защита от лимита сообщений Discord (макс 2000 символов)
        if len(player_list_str) > 1900:
            msg = f"📋 **Итоги ивента (Сервер #{server_id})**\n" \
                  f"Всего бойцов: **{len(players)}**\n" \
                  f"```{player_list_str[:1800]}...\n(список обрезан из-за лимита символов)```"
        else:
            msg = f"📋 **Итоги ивента (Сервер #{server_id})**\n" \
                  f"Всего бойцов: **{len(players)}**\n" \
                  f"```{player_list_str}```"
    else:
        msg = f"ℹ️ За время ивента на **Сервере #{server_id}** никто из 327 не зафиксирован."

    await interaction.response.send_message(msg)

    # Очистка памяти для этого канала
    del active_events[channel_id]

if __name__ == "__main__":
    bot.run(TOKEN)