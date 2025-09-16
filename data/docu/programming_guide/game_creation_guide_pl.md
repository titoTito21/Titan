# Przewodnik tworzenia gier Titan

## Wprowadzenie

Gry Titan to specjalna kategoria aplikacji przeznaczona dla rozrywki. System gier jest podobny do systemu aplikacji, ale gry są wyświetlane w osobnej kategorii "Gry" w niewidzialnym interfejsie. Mogą to być gry w Pythonie, skompilowane pliki wykonywalne lub inne typy programów.

## Architektura systemu gier

### Lokalizacja gier
Wszystkie gry znajdują się w katalogu `data/games/`. Każda gra to osobny katalog zawierający:
- `__game.tce` - plik konfiguracyjny gry (wymagany)
- `main.py` - główny plik gry (lub inny plik określony w openfile)
- dodatkowe pliki gry, zasoby, grafiki, dźwięki itp.

### Proces uruchamiania gier

1. **Kompilacja** - pliki .py są automatycznie kompilowane do .pyc
2. **Uruchomienie** - gra uruchamiana w osobnym procesie
3. **Katalog roboczy** - gra działa w swoim katalogu (dostęp do zasobów)
4. **Izolacja** - każda gra działa niezależnie

## Struktura pliku konfiguracyjnego

### __game.tce
Plik w formacie klucz=wartość:

```
name_pl=Nazwa gry po polsku
name_en=Game name in English
openfile=main.py
author=Autor gry
version=1.0
genre=Arcade
description_pl=Opis gry po polsku
description_en=Game description in English
```

**Wymagane parametry:**
- `openfile` - nazwa pliku do uruchomienia

**Opcjonalne parametry:**
- `name_pl` - nazwa po polsku
- `name_en` - nazwa po angielsku  
- `name` - nazwa domyślna (jeśli brak tłumaczeń)
- `author` - autor gry
- `version` - wersja gry
- `genre` - gatunek gry (Arcade, RPG, Strategy, etc.)
- `description_pl` - opis po polsku
- `description_en` - opis po angielsku

## Implementacja gier Python

### Podstawowa struktura main.py dla gry

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pygame
import sys
import os
import random

# Inicjalizacja pygame
pygame.init()

class SimpleGame:
    def __init__(self):
        self.width = 800
        self.height = 600
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Moja gra")
        
        # Kolory
        self.BLACK = (0, 0, 0)
        self.WHITE = (255, 255, 255)
        self.RED = (255, 0, 0)
        self.GREEN = (0, 255, 0)
        self.BLUE = (0, 0, 255)
        
        # Zegar gry
        self.clock = pygame.time.Clock()
        self.running = True
        
        # Stan gry
        self.player_x = self.width // 2
        self.player_y = self.height // 2
        self.player_speed = 5
        
    def handle_events(self):
        """Obsługa zdarzeń"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                    
    def update(self):
        """Aktualizacja logiki gry"""
        keys = pygame.key.get_pressed()
        
        # Sterowanie graczem
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            self.player_x -= self.player_speed
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            self.player_x += self.player_speed
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            self.player_y -= self.player_speed
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            self.player_y += self.player_speed
            
        # Utrzymuj gracza w granicach ekranu
        self.player_x = max(25, min(self.width - 25, self.player_x))
        self.player_y = max(25, min(self.height - 25, self.player_y))
        
    def draw(self):
        """Rysowanie gry"""
        self.screen.fill(self.BLACK)
        
        # Narysuj gracza
        pygame.draw.circle(self.screen, self.BLUE, (self.player_x, self.player_y), 25)
        
        # Instrukcje
        font = pygame.font.Font(None, 36)
        text = font.render("Użyj strzałek lub WASD do poruszania", True, self.WHITE)
        self.screen.blit(text, (10, 10))
        
        text2 = font.render("ESC - wyjście", True, self.WHITE)
        self.screen.blit(text2, (10, 50))
        
        pygame.display.flip()
        
    def run(self):
        """Główna pętla gry"""
        while self.running:
            self.handle_events()
            self.update()
            self.draw()
            self.clock.tick(60)  # 60 FPS
            
        pygame.quit()

if __name__ == '__main__':
    game = SimpleGame()
    game.run()
```

### Gra z dźwiękami i grafikami

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pygame
import os
import random

pygame.init()
pygame.mixer.init()

class SpaceShooter:
    def __init__(self):
        self.width = 800
        self.height = 600
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Space Shooter")
        
        # Kolory
        self.BLACK = (0, 0, 0)
        self.WHITE = (255, 255, 255)
        self.RED = (255, 0, 0)
        self.YELLOW = (255, 255, 0)
        
        self.clock = pygame.time.Clock()
        self.running = True
        
        # Ładowanie zasobów
        self.load_resources()
        
        # Inicjalizacja obiektów gry
        self.player = {
            'x': self.width // 2,
            'y': self.height - 50,
            'speed': 7
        }
        
        self.bullets = []
        self.enemies = []
        self.enemy_spawn_timer = 0
        
        self.score = 0
        self.font = pygame.font.Font(None, 36)
        
    def load_resources(self):
        """Ładowanie grafik i dźwięków"""
        try:
            # Sprawdź czy istnieją pliki zasobów
            self.player_image = None
            self.enemy_image = None
            self.bullet_sound = None
            self.explosion_sound = None
            
            # Możesz dodać ładowanie rzeczywistych plików:
            # self.player_image = pygame.image.load("resources/player.png")
            # self.bullet_sound = pygame.mixer.Sound("resources/shot.wav")
            
        except Exception as e:
            print(f"Błąd ładowania zasobów: {e}")
            
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_SPACE:
                    self.shoot()
                    
    def shoot(self):
        """Strzał gracza"""
        bullet = {
            'x': self.player['x'],
            'y': self.player['y'] - 10,
            'speed': 10
        }
        self.bullets.append(bullet)
        
        # Odtwórz dźwięk strzału (jeśli załadowany)
        if self.bullet_sound:
            self.bullet_sound.play()
            
    def spawn_enemy(self):
        """Stwórz przeciwnika"""
        enemy = {
            'x': random.randint(20, self.width - 20),
            'y': -20,
            'speed': random.randint(2, 5)
        }
        self.enemies.append(enemy)
        
    def update(self):
        keys = pygame.key.get_pressed()
        
        # Sterowanie graczem
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            self.player['x'] -= self.player['speed']
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            self.player['x'] += self.player['speed']
            
        # Utrzymaj gracza w granicach
        self.player['x'] = max(20, min(self.width - 20, self.player['x']))
        
        # Aktualizuj pociski
        for bullet in self.bullets[:]:
            bullet['y'] -= bullet['speed']
            if bullet['y'] < 0:
                self.bullets.remove(bullet)
                
        # Aktualizuj przeciwników
        for enemy in self.enemies[:]:
            enemy['y'] += enemy['speed']
            if enemy['y'] > self.height:
                self.enemies.remove(enemy)
                
        # Sprawdź kolizje pocisk-przeciwnik
        for bullet in self.bullets[:]:
            for enemy in self.enemies[:]:
                if (abs(bullet['x'] - enemy['x']) < 20 and 
                    abs(bullet['y'] - enemy['y']) < 20):
                    self.bullets.remove(bullet)
                    self.enemies.remove(enemy)
                    self.score += 10
                    break
                    
        # Sprawdź kolizje gracz-przeciwnik
        for enemy in self.enemies:
            if (abs(self.player['x'] - enemy['x']) < 30 and 
                abs(self.player['y'] - enemy['y']) < 30):
                self.game_over()
                
        # Spawn przeciwników
        self.enemy_spawn_timer += 1
        if self.enemy_spawn_timer > 60:  # Co sekundę
            self.spawn_enemy()
            self.enemy_spawn_timer = 0
            
    def draw(self):
        self.screen.fill(self.BLACK)
        
        # Narysuj gracza
        pygame.draw.rect(self.screen, self.WHITE, 
                        (self.player['x'] - 15, self.player['y'] - 10, 30, 20))
        
        # Narysuj pociski
        for bullet in self.bullets:
            pygame.draw.circle(self.screen, self.YELLOW, 
                             (bullet['x'], bullet['y']), 3)
            
        # Narysuj przeciwników
        for enemy in self.enemies:
            pygame.draw.rect(self.screen, self.RED, 
                           (enemy['x'] - 10, enemy['y'] - 10, 20, 20))
            
        # Wyświetl wynik
        score_text = self.font.render(f"Wynik: {self.score}", True, self.WHITE)
        self.screen.blit(score_text, (10, 10))
        
        # Instrukcje
        instructions = [
            "Strzałki/WASD - ruch",
            "SPACJA - strzał",
            "ESC - wyjście"
        ]
        
        font_small = pygame.font.Font(None, 24)
        for i, instruction in enumerate(instructions):
            text = font_small.render(instruction, True, self.WHITE)
            self.screen.blit(text, (10, self.height - 80 + i * 25))
        
        pygame.display.flip()
        
    def game_over(self):
        """Koniec gry"""
        self.screen.fill(self.BLACK)
        
        game_over_text = pygame.font.Font(None, 72).render("GAME OVER", True, self.RED)
        score_text = self.font.render(f"Końcowy wynik: {self.score}", True, self.WHITE)
        restart_text = pygame.font.Font(None, 24).render("Naciśnij ESC aby wyjść", True, self.WHITE)
        
        # Wyśrodkuj teksty
        game_over_rect = game_over_text.get_rect(center=(self.width//2, self.height//2 - 50))
        score_rect = score_text.get_rect(center=(self.width//2, self.height//2))
        restart_rect = restart_text.get_rect(center=(self.width//2, self.height//2 + 50))
        
        self.screen.blit(game_over_text, game_over_rect)
        self.screen.blit(score_text, score_rect)
        self.screen.blit(restart_text, restart_rect)
        
        pygame.display.flip()
        
        # Czekaj na ESC
        waiting = True
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                    waiting = False
                    self.running = False
                    
    def run(self):
        while self.running:
            self.handle_events()
            self.update()
            self.draw()
            self.clock.tick(60)
            
        pygame.quit()

if __name__ == '__main__':
    game = SpaceShooter()
    game.run()
```

## Gry tekstowe

Możesz też tworzyć gry tekstowe/konsolowe:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import random
import os

class GuessTheNumber:
    def __init__(self):
        self.number = random.randint(1, 100)
        self.attempts = 0
        self.max_attempts = 10
        
    def clear_screen(self):
        os.system('cls' if os.name == 'nt' else 'clear')
        
    def play(self):
        self.clear_screen()
        print("=== ZGADNIJ LICZBĘ ===")
        print(f"Pomyślałem liczbę od 1 do 100.")
        print(f"Masz {self.max_attempts} prób na odgadnięcie!")
        print()
        
        while self.attempts < self.max_attempts:
            try:
                guess = int(input(f"Próba {self.attempts + 1}: Twoja liczba: "))
                self.attempts += 1
                
                if guess == self.number:
                    print(f"🎉 Brawo! Odgadłeś w {self.attempts} próbach!")
                    break
                elif guess < self.number:
                    print("Za mało!")
                else:
                    print("Za dużo!")
                    
                remaining = self.max_attempts - self.attempts
                if remaining > 0:
                    print(f"Pozostało prób: {remaining}")
                print()
                
            except ValueError:
                print("Proszę wpisać liczbę całkowitą!")
                continue
                
        if self.attempts >= self.max_attempts and guess != self.number:
            print(f"💀 Przegrałeś! Liczba to: {self.number}")
            
        print("\nNaciśnij Enter aby zakończyć...")
        input()

class TicTacToe:
    def __init__(self):
        self.board = [' '] * 9
        self.current_player = 'X'
        
    def clear_screen(self):
        os.system('cls' if os.name == 'nt' else 'clear')
        
    def draw_board(self):
        print("\n=== KÓŁKO I KRZYŻYK ===")
        print()
        print(" 1 | 2 | 3     {} | {} | {} ".format(self.board[0], self.board[1], self.board[2]))
        print("-----------   -----------")
        print(" 4 | 5 | 6     {} | {} | {} ".format(self.board[3], self.board[4], self.board[5]))
        print("-----------   -----------")
        print(" 7 | 8 | 9     {} | {} | {} ".format(self.board[6], self.board[7], self.board[8]))
        print()
        
    def make_move(self, position):
        if self.board[position - 1] == ' ':
            self.board[position - 1] = self.current_player
            return True
        return False
        
    def check_winner(self):
        # Sprawdź wiersze, kolumny i przekątne
        winning_combinations = [
            [0, 1, 2], [3, 4, 5], [6, 7, 8],  # wiersze
            [0, 3, 6], [1, 4, 7], [2, 5, 8],  # kolumny
            [0, 4, 8], [2, 4, 6]              # przekątne
        ]
        
        for combo in winning_combinations:
            if (self.board[combo[0]] == self.board[combo[1]] == self.board[combo[2]] != ' '):
                return self.board[combo[0]]
        return None
        
    def is_board_full(self):
        return ' ' not in self.board
        
    def switch_player(self):
        self.current_player = 'O' if self.current_player == 'X' else 'X'
        
    def play(self):
        while True:
            self.clear_screen()
            self.draw_board()
            
            winner = self.check_winner()
            if winner:
                print(f"🎉 Gracz {winner} wygrał!")
                break
                
            if self.is_board_full():
                print("🤝 Remis!")
                break
                
            try:
                position = int(input(f"Gracz {self.current_player}, wybierz pozycję (1-9): "))
                if 1 <= position <= 9:
                    if self.make_move(position):
                        self.switch_player()
                    else:
                        print("Ta pozycja jest już zajęta!")
                        input("Naciśnij Enter aby kontynuować...")
                else:
                    print("Wybierz pozycję od 1 do 9!")
                    input("Naciśnij Enter aby kontynuować...")
            except ValueError:
                print("Proszę wpisać liczbę!")
                input("Naciśnij Enter aby kontynuować...")
                
        print("\nNaciśnij Enter aby zakończyć...")
        input()

def main():
    print("Wybierz grę:")
    print("1. Zgadnij liczbę")
    print("2. Kółko i krzyżyk")
    print("0. Wyjście")
    
    choice = input("Twój wybór: ")
    
    if choice == '1':
        game = GuessTheNumber()
        game.play()
    elif choice == '2':
        game = TicTacToe()
        game.play()
    elif choice == '0':
        print("Do widzenia!")
    else:
        print("Nieprawidłowy wybór!")

if __name__ == '__main__':
    main()
```

## Zasoby gier

### Struktura katalogów dla gier z zasobami

```
data/games/moja_gra/
├── __game.tce          # Konfiguracja gry (wymagane)
├── main.py             # Główny plik gry
├── resources/          # Zasoby gry
│   ├── images/         # Grafiki
│   │   ├── player.png
│   │   ├── enemy.png
│   │   └── background.jpg
│   ├── sounds/         # Dźwięki
│   │   ├── shoot.wav
│   │   ├── explosion.wav
│   │   └── music.ogg
│   ├── fonts/          # Czcionki
│   │   └── game_font.ttf
│   └── data/           # Dane gry
│       ├── levels.json
│       └── highscores.txt
├── modules/            # Dodatkowe moduły
│   ├── player.py
│   ├── enemy.py
│   └── game_state.py
└── config/             # Konfiguracja
    └── settings.ini
```

### Ładowanie zasobów z katalogu gry

```python
import os
import pygame

def load_game_resources():
    """Funkcja do ładowania zasobów z katalogu gry"""
    game_dir = os.path.dirname(__file__)
    resources_dir = os.path.join(game_dir, 'resources')
    
    resources = {}
    
    # Ładowanie obrazków
    images_dir = os.path.join(resources_dir, 'images')
    if os.path.exists(images_dir):
        for file in os.listdir(images_dir):
            if file.endswith(('.png', '.jpg', '.jpeg', '.gif')):
                name = os.path.splitext(file)[0]
                resources[f'image_{name}'] = pygame.image.load(
                    os.path.join(images_dir, file)
                )
    
    # Ładowanie dźwięków
    sounds_dir = os.path.join(resources_dir, 'sounds')
    if os.path.exists(sounds_dir):
        for file in os.listdir(sounds_dir):
            if file.endswith(('.wav', '.ogg', '.mp3')):
                name = os.path.splitext(file)[0]
                resources[f'sound_{name}'] = pygame.mixer.Sound(
                    os.path.join(sounds_dir, file)
                )
    
    return resources

# Użycie w grze
resources = load_game_resources()
player_image = resources.get('image_player')
shoot_sound = resources.get('sound_shoot')
```

## Zapisywanie stanu gry

```python
import json
import os

class GameSave:
    def __init__(self, game_name):
        self.game_dir = os.path.dirname(__file__)
        self.save_file = os.path.join(self.game_dir, f"{game_name}_save.json")
        
    def save_game(self, game_data):
        """Zapisz stan gry"""
        try:
            with open(self.save_file, 'w', encoding='utf-8') as f:
                json.dump(game_data, f, indent=2)
            return True
        except Exception as e:
            print(f"Błąd zapisywania: {e}")
            return False
            
    def load_game(self):
        """Wczytaj stan gry"""
        try:
            if os.path.exists(self.save_file):
                with open(self.save_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Błąd wczytywania: {e}")
        return None
        
    def save_exists(self):
        """Sprawdź czy istnieje zapis"""
        return os.path.exists(self.save_file)

# Użycie w grze
class RPGGame:
    def __init__(self):
        self.save_manager = GameSave("my_rpg")
        self.player_data = {
            'name': 'Gracz',
            'level': 1,
            'hp': 100,
            'exp': 0,
            'inventory': [],
            'position': {'x': 0, 'y': 0}
        }
        
    def save_game(self):
        game_state = {
            'player': self.player_data,
            'timestamp': time.time()
        }
        return self.save_manager.save_game(game_state)
        
    def load_game(self):
        data = self.save_manager.load_game()
        if data:
            self.player_data = data.get('player', self.player_data)
            return True
        return False
```

## Testowanie gier

1. Utwórz katalog w `data/games/nazwa_gry/`
2. Dodaj `__game.tce` i główny plik gry
3. Uruchom Titan
4. Sprawdź czy gra pojawia się w kategorii "Gry"
5. Przetestuj uruchamianie i gameplay

## Najważniejsze wskazówki dla gier

1. **Zawsze dodaj plik __game.tce** - bez niego gra nie będzie widoczna
2. **Optymalizuj wydajność** - gry powinny działać płynnie (60 FPS)
3. **Dodaj instrukcje** - wyjaśnij sterowanie i zasady
4. **Obsługuj ESC** - zawsze pozwól graczowi wyjść z gry
5. **Zarządzaj zasobami** - ładuj obrazki i dźwięki przy starcie
6. **Zapisuj stan** - pozwól graczom zapisywać postępy
7. **Testuj na różnych komputerach** - sprawdź wydajność
8. **Dodaj menu** - ekran startowy, opcje, high scores
9. **Obsługuj błędy** - gra nie powinna crashować
10. **Dokumentuj** - opisz grę w pliku konfiguracyjnym

## Popularne biblioteki dla gier Python

- **pygame** - 2D gry, sprite'y, dźwięk
- **pyglet** - OpenGL, 3D grafika
- **arcade** - nowoczesne 2D gry
- **kivy** - gry mobilne, touch interface
- **panda3d** - gry 3D
- **tkinter** - proste gry tekstowe/puzzle

## Struktura katalogów

```
data/games/my_game/
├── __game.tce          # Konfiguracja gry (wymagane)
├── main.py             # Główny plik gry
├── resources/          # Zasoby gry (opcjonalnie)
├── modules/            # Moduły gry (opcjonalnie)
├── saves/              # Zapisy gry (opcjonalnie)
├── config/             # Ustawienia (opcjonalnie)
└── docs/               # Dokumentacja (opcjonalnie)
```

Gry Titan oferują platformę do tworzenia różnorodnych gier - od prostych gier tekstowych po zaawansowane gry 2D/3D z grafiką i dźwiękiem. System automatycznie zarządza uruchamianiem i izolacją gier.