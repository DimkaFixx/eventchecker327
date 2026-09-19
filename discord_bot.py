import discord
from discord.ext import commands, tasks
from parser import Parser
import asyncio
from dotenv import load_dotenv
import os

load_dotenv()

TOKEN = os.getenv('BOT_TOKEN')

# Настройки IP и портов серверов
SERVERS = {
    1: {"host": os.getenv('S1_IP'), "port": int(os.getenv('S1_PORT'))},
    2: {"host": os.getenv('S2_IP'), "port": int(os.getenv('S2_PORT'))}
}

JEDI_PREFIXES = os.getenv('JEDI_PREFIXES').split(',') 



intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

# Хранилище: {channel_id: {"server_id": id, "players": set()}}
active_events = {}

@tasks.loop(minutes=5.0)
async def monitor_loop():
    if not active_events:
        monitor_loop.stop()
        return

    for channel_id, data in list(active_events.items()):
        server_id = data["server_id"]
        server_cfg = SERVERS[server_id]
        
        parser = Parser(
            host=server_cfg["host"], 
            port=server_cfg["port"],
            jedi_prefixes=JEDI_PREFIXES,
        )
        try:
            # Запускаем тяжелый сетевой парсер в ОТДЕЛЬНОМ потоке,
            # чтобы он не блокировал Discord
            players = await asyncio.to_thread(parser.parse_players)
            
            for p in players:
                if p.bat == "327" and p.name:
                    data["players"].add(p.name)
        except Exception as e:
            print(f"[Ошибка мониторинга сервера {server_id}]: {e}")

@bot.command()
async def eventstart(ctx, server_num: int):
    if server_num not in SERVERS:
        await ctx.send("Неверный номер сервера. Доступны: 1 или 2.")
        return
    
    if ctx.channel.id in active_events:
        await ctx.send("В этой ветке уже идет мониторинг!")
        return

    # Инициализация множества (set) для исключения дублей
    active_events[ctx.channel.id] = {"server_id": server_num, "players": set()}
    await ctx.send(f"Мониторинг сервера #{server_num} запущен каждые 5 минут.")
    
    if not monitor_loop.is_running():
        monitor_loop.start()

@bot.command()
async def eventend(ctx):
    if ctx.channel.id not in active_events:
        await ctx.send("В этой ветке нет активного события.")
        return
    
    players = active_events[ctx.channel.id]["players"]
    
    if players:
        # Сортируем список по алфавиту для красоты
        result = "\n".join(sorted(players))
        await ctx.send(f"**Список 327 на ивенте:**\n```{result}```")
    else:
        await ctx.send("За время ивента игроки из 327 не были замечены.")
    
    # Полное удаление данных из оперативной памяти
    del active_events[ctx.channel.id]

bot.run(TOKEN)