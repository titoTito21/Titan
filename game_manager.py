import os
import subprocess
import threading
import py_compile

GAME_DIR = os.path.join(os.path.dirname(__file__), 'data/games')

def get_games():
    games = []
    for game_folder in os.listdir(GAME_DIR):
        game_path = os.path.join(GAME_DIR, game_folder)
        if os.path.isdir(game_path):
            game_info = read_game_info(game_path)
            if game_info:
                games.append(game_info)
    return games

def read_game_info(game_path):
    game_info_path = os.path.join(game_path, '__game.tce')
    if not os.path.exists(game_info_path):
        return None
    
    game_info = {}
    with open(game_info_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for line in lines:
            line = line.strip()
            if not line or '=' not in line:
                continue
            key, value = line.split('=', 1)
            game_info[key.strip()] = value.strip().strip('"')
    
    game_info['path'] = game_path
    return game_info

def compile_python_file(py_file):
    pyc_file = py_file + 'c'
    py_compile.compile(py_file, cfile=pyc_file)
    return pyc_file

def open_game(game_info):
    def run_game():
        game_file = os.path.join(game_info['path'], game_info['openfile'])
        if game_file.endswith('.py'):
            pyc_file = game_file + 'c'
            if os.path.exists(pyc_file):
                subprocess.run(['python', pyc_file], cwd=game_info['path'])
            else:
                compiled_file = compile_python_file(game_file)
                subprocess.run(['python', compiled_file], cwd=game_info['path'])
        elif game_file.endswith('.pyc'):
            subprocess.run(['python', game_file], cwd=game_info['path'])
        elif game_file.endswith('.exe'):
            subprocess.run([game_file], cwd=game_info['path'])
    
    threading.Thread(target=run_game).start()
