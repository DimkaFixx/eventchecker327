import a2s
import socket
import re

class Player:
    def __init__(self, player_full_nick, duration):
        self.player_full_nick = player_full_nick
        self.duration_seconds = duration
        self.name = None
        self.bat = None
    
    def __str__(self):
        return f"Player(name={self.player_full_nick}, {self.duration_seconds}, {self.bat}, {self.name})"

class Parser:
    def __init__(self, host, port, jedi_prefixes):
        self.host = host
        self.port = port
        self.jedi_prefixes = jedi_prefixes

    def get_data(self):
        print(f"Attempting to retrieve player data from server... {a2s.info((self.host, self.port), timeout=100)}")
        return a2s.players((self.host, self.port), timeout=100)

    def parse_players(self):
        data = self.get_data()

        players = []
        for player in data:
            player_object = Player(player_full_nick=player.name, duration=player.duration)
            try:
                bat, formatted_nick = self.find_bat_for_players(player_object)
                player_object.bat = bat
                player_object.name = formatted_nick
                players.append(player_object)
            except Exception as e:
                print(f"Error occurred while processing player {player.name}, skipping: {e}")
        return players
    
    # -----------------------------------------------------------------------------

    def find_bat_for_players(self, player):

        player_nickname = player_nickname_for_return = str(player.player_full_nick)

        #Отсекаем CR, CT
        if not "[" in player_nickname:
            return None, player_nickname_for_return
        
        # Проверяем на джедая 
        jedi = False
        for jedi_prefix in self.jedi_prefixes:
            if player_nickname.startswith(f"[{jedi_prefix}"):
                jedi = True
                break
        
        # Если джедай, то находим его подразделение
        if jedi:
            bat = player_nickname.split("|")[-1].replace(" ", "") if "|" in player_nickname else "Jedi"
            return bat, player_nickname_for_return

        if player_nickname.startswith("[RC") and "|" in player_nickname:
            squad = player_nickname.split("|")[-1].replace(" ", "") if "|" in player_nickname else None
            if squad == "Acklay":
                return "327", player_nickname_for_return

        # Убираем спецуху, только у джедаев там батальон (ну и Acklay)
        player_nickname = player_nickname.split("|")[0] if "|" in player_nickname else player_nickname
        
        
        # Если не джедай, то проверяем на C-3 (удобно просто)
        if player_nickname.startswith("[C-3"):
            return "C-3", player_nickname_for_return
        
        # Также проверяем на RC
        if player_nickname.startswith("[RC"):
            return "RC", player_nickname_for_return
        
        # Далее проверям на БСО, сразу будем брать легионеров или отрядников, будем брать только нужных нам отрядников, остальные в None
        if "-" in player_nickname.split("]")[0]:
            bat = player_nickname.split("]")[0] 
            bat = bat.split("-")[1] if "-" in bat else bat
            return bat, player_nickname_for_return
        
        #Остались вроде как только тупо [<БАТ>]
        bat = player_nickname.split("]")[0].replace("[", "") if "]" in player_nickname else None
        return bat, player_nickname_for_return
