# Titan Game Creation Guide

## Introduction

Titan games are a special category of applications designed for entertainment. The game system is similar to the application system, but games are displayed in a separate "Games" category in the invisible interface. They can be Python games, compiled executables, or other types of programs.

## Game System Architecture

### Game Location
All games are located in the `data/games/` directory. Each game is a separate directory containing:
- `__game.tce` - game configuration file (required)
- `main.py` - main game file (or other file specified in openfile)
- additional game files, resources, graphics, sounds, etc.

### Game Launch Process

1. **Compilation** - .py files are automatically compiled to .pyc
2. **Launch** - game runs in separate process
3. **Working directory** - game runs in its directory (access to resources)
4. **Isolation** - each game runs independently

## Configuration File Structure

### __game.tce
File in key=value format:

```
name_pl=Nazwa gry po polsku
name_en=Game name in English
openfile=main.py
author=Game Author
version=1.0
genre=Arcade
description_pl=Opis gry po polsku
description_en=Game description in English
```

**Required parameters:**
- `openfile` - name of file to execute

**Optional parameters:**
- `name_pl` - name in Polish
- `name_en` - name in English  
- `name` - default name (if no translations)
- `author` - game author
- `version` - game version
- `genre` - game genre (Arcade, RPG, Strategy, etc.)
- `description_pl` - description in Polish
- `description_en` - description in English

## Python Game Implementation

### Basic main.py structure for games

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pygame
import sys
import os
import random

# Initialize pygame
pygame.init()

class SimpleGame:
    def __init__(self):
        self.width = 800
        self.height = 600
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("My Game")
        
        # Colors
        self.BLACK = (0, 0, 0)
        self.WHITE = (255, 255, 255)
        self.RED = (255, 0, 0)
        self.GREEN = (0, 255, 0)
        self.BLUE = (0, 0, 255)
        
        # Game clock
        self.clock = pygame.time.Clock()
        self.running = True
        
        # Game state
        self.player_x = self.width // 2
        self.player_y = self.height // 2
        self.player_speed = 5
        
    def handle_events(self):
        """Handle events"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                    
    def update(self):
        """Update game logic"""
        keys = pygame.key.get_pressed()
        
        # Player controls
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            self.player_x -= self.player_speed
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            self.player_x += self.player_speed
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            self.player_y -= self.player_speed
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            self.player_y += self.player_speed
            
        # Keep player within screen bounds
        self.player_x = max(25, min(self.width - 25, self.player_x))
        self.player_y = max(25, min(self.height - 25, self.player_y))
        
    def draw(self):
        """Draw the game"""
        self.screen.fill(self.BLACK)
        
        # Draw player
        pygame.draw.circle(self.screen, self.BLUE, (self.player_x, self.player_y), 25)
        
        # Instructions
        font = pygame.font.Font(None, 36)
        text = font.render("Use arrows or WASD to move", True, self.WHITE)
        self.screen.blit(text, (10, 10))
        
        text2 = font.render("ESC - exit", True, self.WHITE)
        self.screen.blit(text2, (10, 50))
        
        pygame.display.flip()
        
    def run(self):
        """Main game loop"""
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

### Game with sounds and graphics

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
        
        # Colors
        self.BLACK = (0, 0, 0)
        self.WHITE = (255, 255, 255)
        self.RED = (255, 0, 0)
        self.YELLOW = (255, 255, 0)
        
        self.clock = pygame.time.Clock()
        self.running = True
        
        # Load resources
        self.load_resources()
        
        # Initialize game objects
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
        """Load graphics and sounds"""
        try:
            # Check if resource files exist
            self.player_image = None
            self.enemy_image = None
            self.bullet_sound = None
            self.explosion_sound = None
            
            # You can add loading of actual files:
            # self.player_image = pygame.image.load("resources/player.png")
            # self.bullet_sound = pygame.mixer.Sound("resources/shot.wav")
            
        except Exception as e:
            print(f"Resource loading error: {e}")
            
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
        """Player shot"""
        bullet = {
            'x': self.player['x'],
            'y': self.player['y'] - 10,
            'speed': 10
        }
        self.bullets.append(bullet)
        
        # Play shot sound (if loaded)
        if self.bullet_sound:
            self.bullet_sound.play()
            
    def spawn_enemy(self):
        """Create enemy"""
        enemy = {
            'x': random.randint(20, self.width - 20),
            'y': -20,
            'speed': random.randint(2, 5)
        }
        self.enemies.append(enemy)
        
    def update(self):
        keys = pygame.key.get_pressed()
        
        # Player controls
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            self.player['x'] -= self.player['speed']
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            self.player['x'] += self.player['speed']
            
        # Keep player within bounds
        self.player['x'] = max(20, min(self.width - 20, self.player['x']))
        
        # Update bullets
        for bullet in self.bullets[:]:
            bullet['y'] -= bullet['speed']
            if bullet['y'] < 0:
                self.bullets.remove(bullet)
                
        # Update enemies
        for enemy in self.enemies[:]:
            enemy['y'] += enemy['speed']
            if enemy['y'] > self.height:
                self.enemies.remove(enemy)
                
        # Check bullet-enemy collisions
        for bullet in self.bullets[:]:
            for enemy in self.enemies[:]:
                if (abs(bullet['x'] - enemy['x']) < 20 and 
                    abs(bullet['y'] - enemy['y']) < 20):
                    self.bullets.remove(bullet)
                    self.enemies.remove(enemy)
                    self.score += 10
                    break
                    
        # Check player-enemy collisions
        for enemy in self.enemies:
            if (abs(self.player['x'] - enemy['x']) < 30 and 
                abs(self.player['y'] - enemy['y']) < 30):
                self.game_over()
                
        # Spawn enemies
        self.enemy_spawn_timer += 1
        if self.enemy_spawn_timer > 60:  # Every second
            self.spawn_enemy()
            self.enemy_spawn_timer = 0
            
    def draw(self):
        self.screen.fill(self.BLACK)
        
        # Draw player
        pygame.draw.rect(self.screen, self.WHITE, 
                        (self.player['x'] - 15, self.player['y'] - 10, 30, 20))
        
        # Draw bullets
        for bullet in self.bullets:
            pygame.draw.circle(self.screen, self.YELLOW, 
                             (bullet['x'], bullet['y']), 3)
            
        # Draw enemies
        for enemy in self.enemies:
            pygame.draw.rect(self.screen, self.RED, 
                           (enemy['x'] - 10, enemy['y'] - 10, 20, 20))
            
        # Display score
        score_text = self.font.render(f"Score: {self.score}", True, self.WHITE)
        self.screen.blit(score_text, (10, 10))
        
        # Instructions
        instructions = [
            "Arrows/WASD - move",
            "SPACE - shoot",
            "ESC - exit"
        ]
        
        font_small = pygame.font.Font(None, 24)
        for i, instruction in enumerate(instructions):
            text = font_small.render(instruction, True, self.WHITE)
            self.screen.blit(text, (10, self.height - 80 + i * 25))
        
        pygame.display.flip()
        
    def game_over(self):
        """Game over"""
        self.screen.fill(self.BLACK)
        
        game_over_text = pygame.font.Font(None, 72).render("GAME OVER", True, self.RED)
        score_text = self.font.render(f"Final Score: {self.score}", True, self.WHITE)
        restart_text = pygame.font.Font(None, 24).render("Press ESC to exit", True, self.WHITE)
        
        # Center texts
        game_over_rect = game_over_text.get_rect(center=(self.width//2, self.height//2 - 50))
        score_rect = score_text.get_rect(center=(self.width//2, self.height//2))
        restart_rect = restart_text.get_rect(center=(self.width//2, self.height//2 + 50))
        
        self.screen.blit(game_over_text, game_over_rect)
        self.screen.blit(score_text, score_rect)
        self.screen.blit(restart_text, restart_rect)
        
        pygame.display.flip()
        
        # Wait for ESC
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

## Text Games

You can also create text/console games:

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
        print("=== GUESS THE NUMBER ===")
        print(f"I'm thinking of a number from 1 to 100.")
        print(f"You have {self.max_attempts} attempts to guess it!")
        print()
        
        while self.attempts < self.max_attempts:
            try:
                guess = int(input(f"Attempt {self.attempts + 1}: Your number: "))
                self.attempts += 1
                
                if guess == self.number:
                    print(f"🎉 Congratulations! You guessed it in {self.attempts} attempts!")
                    break
                elif guess < self.number:
                    print("Too low!")
                else:
                    print("Too high!")
                    
                remaining = self.max_attempts - self.attempts
                if remaining > 0:
                    print(f"Attempts remaining: {remaining}")
                print()
                
            except ValueError:
                print("Please enter a whole number!")
                continue
                
        if self.attempts >= self.max_attempts and guess != self.number:
            print(f"💀 You lost! The number was: {self.number}")
            
        print("\nPress Enter to finish...")
        input()

class TicTacToe:
    def __init__(self):
        self.board = [' '] * 9
        self.current_player = 'X'
        
    def clear_screen(self):
        os.system('cls' if os.name == 'nt' else 'clear')
        
    def draw_board(self):
        print("\n=== TIC TAC TOE ===")
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
        # Check rows, columns and diagonals
        winning_combinations = [
            [0, 1, 2], [3, 4, 5], [6, 7, 8],  # rows
            [0, 3, 6], [1, 4, 7], [2, 5, 8],  # columns
            [0, 4, 8], [2, 4, 6]              # diagonals
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
                print(f"🎉 Player {winner} wins!")
                break
                
            if self.is_board_full():
                print("🤝 It's a tie!")
                break
                
            try:
                position = int(input(f"Player {self.current_player}, choose position (1-9): "))
                if 1 <= position <= 9:
                    if self.make_move(position):
                        self.switch_player()
                    else:
                        print("That position is already taken!")
                        input("Press Enter to continue...")
                else:
                    print("Choose position from 1 to 9!")
                    input("Press Enter to continue...")
            except ValueError:
                print("Please enter a number!")
                input("Press Enter to continue...")
                
        print("\nPress Enter to finish...")
        input()

def main():
    print("Choose a game:")
    print("1. Guess the Number")
    print("2. Tic Tac Toe")
    print("0. Exit")
    
    choice = input("Your choice: ")
    
    if choice == '1':
        game = GuessTheNumber()
        game.play()
    elif choice == '2':
        game = TicTacToe()
        game.play()
    elif choice == '0':
        print("Goodbye!")
    else:
        print("Invalid choice!")

if __name__ == '__main__':
    main()
```

## Game Resources

### Directory structure for games with resources

```
data/games/my_game/
├── __game.tce          # Game configuration (required)
├── main.py             # Main game file
├── resources/          # Game resources
│   ├── images/         # Graphics
│   │   ├── player.png
│   │   ├── enemy.png
│   │   └── background.jpg
│   ├── sounds/         # Sounds
│   │   ├── shoot.wav
│   │   ├── explosion.wav
│   │   └── music.ogg
│   ├── fonts/          # Fonts
│   │   └── game_font.ttf
│   └── data/           # Game data
│       ├── levels.json
│       └── highscores.txt
├── modules/            # Additional modules
│   ├── player.py
│   ├── enemy.py
│   └── game_state.py
└── config/             # Configuration
    └── settings.ini
```

### Loading resources from game directory

```python
import os
import pygame

def load_game_resources():
    """Function to load resources from game directory"""
    game_dir = os.path.dirname(__file__)
    resources_dir = os.path.join(game_dir, 'resources')
    
    resources = {}
    
    # Load images
    images_dir = os.path.join(resources_dir, 'images')
    if os.path.exists(images_dir):
        for file in os.listdir(images_dir):
            if file.endswith(('.png', '.jpg', '.jpeg', '.gif')):
                name = os.path.splitext(file)[0]
                resources[f'image_{name}'] = pygame.image.load(
                    os.path.join(images_dir, file)
                )
    
    # Load sounds
    sounds_dir = os.path.join(resources_dir, 'sounds')
    if os.path.exists(sounds_dir):
        for file in os.listdir(sounds_dir):
            if file.endswith(('.wav', '.ogg', '.mp3')):
                name = os.path.splitext(file)[0]
                resources[f'sound_{name}'] = pygame.mixer.Sound(
                    os.path.join(sounds_dir, file)
                )
    
    return resources

# Use in game
resources = load_game_resources()
player_image = resources.get('image_player')
shoot_sound = resources.get('sound_shoot')
```

## Saving Game State

```python
import json
import os

class GameSave:
    def __init__(self, game_name):
        self.game_dir = os.path.dirname(__file__)
        self.save_file = os.path.join(self.game_dir, f"{game_name}_save.json")
        
    def save_game(self, game_data):
        """Save game state"""
        try:
            with open(self.save_file, 'w', encoding='utf-8') as f:
                json.dump(game_data, f, indent=2)
            return True
        except Exception as e:
            print(f"Save error: {e}")
            return False
            
    def load_game(self):
        """Load game state"""
        try:
            if os.path.exists(self.save_file):
                with open(self.save_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Load error: {e}")
        return None
        
    def save_exists(self):
        """Check if save exists"""
        return os.path.exists(self.save_file)

# Use in game
class RPGGame:
    def __init__(self):
        self.save_manager = GameSave("my_rpg")
        self.player_data = {
            'name': 'Player',
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

## Testing Games

1. Create directory in `data/games/game_name/`
2. Add `__game.tce` and main game file
3. Start Titan
4. Check if game appears in "Games" category
5. Test launch and gameplay

## Important Guidelines for Games

1. **Always add __game.tce file** - without it game won't be visible
2. **Optimize performance** - games should run smoothly (60 FPS)
3. **Add instructions** - explain controls and rules
4. **Handle ESC** - always allow player to exit the game
5. **Manage resources** - load images and sounds at startup
6. **Save state** - allow players to save progress
7. **Test on different computers** - check performance
8. **Add menu** - start screen, options, high scores
9. **Handle errors** - game shouldn't crash
10. **Document** - describe game in configuration file

## Popular Libraries for Python Games

- **pygame** - 2D games, sprites, sound
- **pyglet** - OpenGL, 3D graphics
- **arcade** - modern 2D games
- **kivy** - mobile games, touch interface
- **panda3d** - 3D games
- **tkinter** - simple text/puzzle games

## Directory Structure

```
data/games/my_game/
├── __game.tce          # Game configuration (required)
├── main.py             # Main game file
├── resources/          # Game resources (optional)
├── modules/            # Game modules (optional)
├── saves/              # Game saves (optional)
├── config/             # Settings (optional)
└── docs/               # Documentation (optional)
```

Titan games offer a platform for creating diverse games - from simple text games to advanced 2D/3D games with graphics and sound. The system automatically manages game launching and isolation.