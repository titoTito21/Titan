# Create Game Wizard

Interactive wizard to create a new game for TCE Launcher.

## Process:

1. **Ask for Game Details:**
   - Game name (Polish)
   - Game name (English)
   - Short name (lowercase, no spaces, for directory)
   - Description (optional)
   - Game type (text-based, audio-based, simple graphics)
   - Controls/input method
   - Main file name (default: {shortname}.py)

2. **Create Game Structure:**
   - Create directory: `data/games/{shortname}/`
   - Create main Python file: `data/games/{shortname}/{mainfile}`
   - Create config file: `data/games/{shortname}/__game.tce`
   - Create assets directory: `data/games/{shortname}/sfx/` (for sound effects)

3. **Generate Game Template:**
   ```python
   import wx
   import os
   import sys
   import pygame
   import random

   # Add TCE root to path for imports
   GAME_DIR = os.path.dirname(os.path.abspath(__file__))
   TCE_ROOT = os.path.abspath(os.path.join(GAME_DIR, '..', '..', '..'))
   if TCE_ROOT not in sys.path:
       sys.path.insert(0, TCE_ROOT)

   # Optional: Translation support
   # from src.titan_core.translation import set_language
   # from src.settings.settings import get_setting
   # _ = set_language(get_setting('language', 'pl'))

   class {GameName}Frame(wx.Frame):
       def __init__(self, *args, **kwargs):
           super({GameName}Frame, self).__init__(*args, **kwargs)
           self.InitUI()
           self.init_game()

       def InitUI(self):
           """Initialize user interface"""
           panel = wx.Panel(self)
           vbox = wx.BoxSizer(wx.VERTICAL)

           # Game display area (text or simple graphics)
           self.display = wx.TextCtrl(
               panel,
               style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP
           )
           vbox.Add(self.display, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

           # Input area
           self.input = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
           self.input.Bind(wx.EVT_TEXT_ENTER, self.on_input)
           vbox.Add(self.input, flag=wx.EXPAND | wx.ALL, border=5)

           panel.SetSizer(vbox)
           self.SetSize((800, 600))
           self.SetTitle("{Game Name}")
           self.Centre()

           # Bind keyboard events
           self.Bind(wx.EVT_KEY_DOWN, self.on_key_press)

       def init_game(self):
           """Initialize game state"""
           # Initialize pygame for audio (optional)
           try:
               if not pygame.mixer.get_init():
                   pygame.mixer.init()
               self.sound_enabled = True
           except:
               self.sound_enabled = False

           # Game state variables
           self.score = 0
           self.game_over = False

           # Start game
           self.start_game()

       def start_game(self):
           """Start or restart the game"""
           self.score = 0
           self.game_over = False
           self.display.SetValue("Welcome to {Game Name}!\n\n")
           self.play_sound("start")

       def on_input(self, event):
           """Handle text input from player"""
           if self.game_over:
               return

           user_input = self.input.GetValue().strip().lower()
           self.input.Clear()

           # Process game input
           self.process_command(user_input)

       def on_key_press(self, event):
           """Handle keyboard input"""
           key = event.GetKeyCode()

           if key == wx.WXK_ESCAPE:
               self.Close()
           elif key == wx.WXK_F1:
               self.show_help()
           # Add more key handlers

           event.Skip()

       def process_command(self, command):
           """Process player commands"""
           # Add your game logic here
           pass

       def play_sound(self, sound_name):
           """Play sound effect"""
           if not self.sound_enabled:
               return

           try:
               sound_path = os.path.join(
                   os.path.dirname(__file__),
                   'sfx',
                   f'{sound_name}.wav'
               )
               if os.path.exists(sound_path):
                   sound = pygame.mixer.Sound(sound_path)
                   sound.play()
           except Exception as e:
               print(f"Error playing sound: {e}")

       def show_help(self):
           """Show game help"""
           help_text = "Game Help:\n"
           help_text += "- Type commands and press Enter\n"
           help_text += "- Press F1 for help\n"
           help_text += "- Press Escape to exit\n"
           wx.MessageBox(help_text, "Help", wx.OK | wx.ICON_INFORMATION)

       def game_over_screen(self):
           """Display game over screen"""
           self.game_over = True
           self.display.AppendText(f"\n\nGame Over!\nFinal Score: {self.score}\n")
           self.play_sound("game_over")

   if __name__ == "__main__":
       app = wx.App(False)
       frame = {GameName}Frame(None)
       frame.Show()
       app.MainLoop()
   ```

4. **Create Config File (`__game.tce` format):**
   ```
   name_pl="{Polish name}"
   name_en="{English name}"
   description="{Description or empty}"
   openfile="{mainfile}"
   shortname="{shortname}"
   ```

   **IMPORTANT**:
   - Use double quotes around values
   - One key=value pair per line
   - File can be named `__game.tce` (lowercase) or `__game.TCE` (uppercase) — both supported
   - Same key=value format as `__app.TCE`

5. **Create Sound Effects Directory:**
   ```
   data/games/{shortname}/sfx/
   ├── start.wav        # Game start sound
   ├── correct.wav      # Correct answer/action
   ├── wrong.wav        # Wrong answer/error
   ├── game_over.wav    # Game over sound
   ├── win.wav          # Victory sound
   └── menu.wav         # Menu navigation
   ```

6. **Audio-Based Game Template** (for accessible games):
   ```python
   import pygame
   import accessible_output3.outputs.auto

   speaker = accessible_output3.outputs.auto.Auto()

   class AudioGame:
       def __init__(self):
           if not pygame.mixer.get_init():
               pygame.mixer.init()
           self.running = True
           self.score = 0

       def speak(self, text):
           """Speak text using screen reader"""
           speaker.speak(text)

       def play_sound(self, sound_file):
           """Play spatial audio effect"""
           sound = pygame.mixer.Sound(sound_file)
           sound.play()

       def play_music(self, music_file):
           """Play background music"""
           pygame.mixer.music.load(music_file)
           pygame.mixer.music.play(-1)  # Loop

       def run(self):
           """Main game loop"""
           self.speak("Game started")

           while self.running:
               # Game logic here
               pass

       def cleanup(self):
           """Cleanup on exit"""
           pygame.mixer.quit()

   if __name__ == "__main__":
       game = AudioGame()
       try:
           game.run()
       finally:
           game.cleanup()
   ```

7. **Verify Installation:**
   - Restart TCE Launcher or refresh games list
   - Check if game appears in games list
   - Test launching the game
   - Test game controls and audio
   - Verify proper cleanup on exit

## Key Notes from game_manager.py:
- Titan-Games are in `data/games/`, but game_manager also detects Steam and Battle.net games
- Titan-Games use `.py`/`.pyc`/`.pyd`/`.exe` files like applications
- Steam games launch via `steam://rungameid/{app_id}` protocol
- Battle.net games detected from Windows registry

## Game Types:

### Text Adventure
- Story-based with text choices
- Simple input/output
- No real-time action

### Audio Game
- Uses spatial audio and sound cues
- Keyboard controls
- Accessible for blind players

### Puzzle Game
- Logic or word puzzles
- Turn-based
- Score tracking

### Card Game
- Solitaire, blackjack, etc.
- Mouse or keyboard controls
- Sound effects

### Simple Arcade
- Real-time action
- Keyboard controls
- Audio feedback

## Accessibility Tips:

1. **Always provide audio feedback** - sounds and/or TTS
2. **Clear instructions** - help system (F1 key)
3. **Keyboard-only controls** - no mouse required
4. **Pause/resume** - for accessible games
5. **Score announcements** - TTS for current score
6. **Sound cues** - spatial audio for game events

## Reference Structure:

```
data/games/{shortname}/
├── __game.tce          # Game config
├── {shortname}.py      # Main game file
├── sfx/                # Sound effects directory
│   ├── start.wav
│   ├── correct.wav
│   ├── wrong.wav
│   └── game_over.wav
└── data/               # Optional: game data files
    ├── levels/
    ├── saves/
    └── config.json
```

## Testing Checklist:

- [ ] Game appears in games list
- [ ] Game launches without errors
- [ ] Controls work as expected
- [ ] Audio plays correctly
- [ ] TTS announcements work (if applicable)
- [ ] Game can be paused/resumed
- [ ] Game exits cleanly (no hanging processes)
- [ ] Score is tracked correctly
- [ ] Help system is accessible (F1)
- [ ] Game is playable without vision (if accessible game)

## Complete Code Examples

### Example 1: Number Guessing Game (Text-Based)

A simple accessible number guessing game. The player guesses a random number between 1 and 100, receiving "Higher"/"Lower" feedback via the display area and TTS. Score is tracked by the number of attempts. Press F2 to start a new game.

**File: `data/games/numguess/__game.tce`**

```
name_pl="Zgadnij Liczbę"
name_en="Number Guessing Game"
description="Guess the random number between 1 and 100"
openfile="numguess.py"
shortname="numguess"
```

**File: `data/games/numguess/numguess.py`**

```python
import wx
import os
import sys
import random

# Add TCE root to path for imports
GAME_DIR = os.path.dirname(os.path.abspath(__file__))
TCE_ROOT = os.path.abspath(os.path.join(GAME_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

# Initialize pygame for sound effects
import pygame
if not pygame.mixer.get_init():
    pygame.mixer.init()

# TTS via accessible_output3
try:
    import accessible_output3.outputs.auto
    speaker = accessible_output3.outputs.auto.Auto()
except ImportError:
    speaker = None


def speak(text):
    """Speak text using screen reader or TTS."""
    if speaker:
        speaker.speak(text)


def play_sound(sound_name):
    """Play a sound file from the sfx directory."""
    try:
        sound_path = os.path.join(GAME_DIR, 'sfx', f'{sound_name}.wav')
        if os.path.exists(sound_path):
            sound = pygame.mixer.Sound(sound_path)
            sound.play()
    except Exception as e:
        print(f"Error playing sound: {e}")


class NumberGuessFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.SetTitle("Number Guessing Game")
        self.SetSize((600, 400))
        self.Centre()

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Display area (read-only)
        self.display = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP
        )
        vbox.Add(self.display, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        # Input row
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        label = wx.StaticText(panel, label="Your guess:")
        hbox.Add(label, flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)

        self.input = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.input.Bind(wx.EVT_TEXT_ENTER, self.on_guess)
        hbox.Add(self.input, proportion=1, flag=wx.EXPAND)

        self.guess_btn = wx.Button(panel, label="Guess")
        self.guess_btn.Bind(wx.EVT_BUTTON, self.on_guess)
        hbox.Add(self.guess_btn, flag=wx.LEFT, border=5)

        vbox.Add(hbox, flag=wx.EXPAND | wx.ALL, border=5)

        # New Game button
        self.new_game_btn = wx.Button(panel, label="New Game (F2)")
        self.new_game_btn.Bind(wx.EVT_BUTTON, self.on_new_game)
        vbox.Add(self.new_game_btn, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=5)

        panel.SetSizer(vbox)

        # Keyboard shortcuts
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_NORMAL, wx.WXK_F2, self.new_game_btn.GetId()),
            (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, wx.ID_EXIT),
        ])
        self.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_new_game, id=self.new_game_btn.GetId())
        self.Bind(wx.EVT_MENU, self.on_exit, id=wx.ID_EXIT)

        # Start the first game
        self.start_game()
        self.input.SetFocus()

    def start_game(self):
        """Initialize a new round."""
        self.target = random.randint(1, 100)
        self.attempts = 0
        self.game_over = False
        self.display.SetValue(
            "Number Guessing Game\n"
            "====================\n\n"
            "I am thinking of a number between 1 and 100.\n"
            "Type your guess and press Enter.\n\n"
            "Controls:\n"
            "  Enter - Submit guess\n"
            "  F2    - New game\n"
            "  Escape - Exit\n\n"
        )
        play_sound("start")
        speak("New game. I am thinking of a number between 1 and 100. Type your guess.")

    def on_guess(self, event):
        """Handle a guess from the player."""
        if self.game_over:
            speak("Game over. Press F2 to start a new game.")
            return

        text = self.input.GetValue().strip()
        self.input.Clear()
        self.input.SetFocus()

        if not text.isdigit():
            msg = "Please enter a valid number between 1 and 100."
            self.display.AppendText(msg + "\n")
            speak(msg)
            play_sound("wrong")
            return

        guess = int(text)
        if guess < 1 or guess > 100:
            msg = "Out of range. Please enter a number between 1 and 100."
            self.display.AppendText(msg + "\n")
            speak(msg)
            play_sound("wrong")
            return

        self.attempts += 1

        if guess < self.target:
            msg = f"You guessed {guess}. Higher!"
            self.display.AppendText(msg + "\n")
            speak(msg)
            play_sound("wrong")
        elif guess > self.target:
            msg = f"You guessed {guess}. Lower!"
            self.display.AppendText(msg + "\n")
            speak(msg)
            play_sound("wrong")
        else:
            # Correct guess
            self.game_over = True
            msg = (
                f"Correct! The number was {self.target}. "
                f"You got it in {self.attempts} attempt{'s' if self.attempts != 1 else ''}!"
            )
            self.display.AppendText("\n" + msg + "\n")
            self.display.AppendText("Press F2 to play again.\n")
            speak(msg)
            play_sound("correct")

    def on_new_game(self, event):
        """Start a new game."""
        self.start_game()
        self.input.SetFocus()

    def on_exit(self, event):
        """Exit the game."""
        self.Close()


if __name__ == "__main__":
    app = wx.App(False)
    frame = NumberGuessFrame(None)
    frame.Show()
    app.MainLoop()
```

**Sound effects directory: `data/games/numguess/sfx/`**

Place the following `.wav` files in the `sfx/` folder:
- `start.wav` - played when a new game begins
- `correct.wav` - played when the player guesses correctly
- `wrong.wav` - played on an incorrect guess or invalid input

---

### Example 2: Audio Quiz Game

An accessible multiple-choice quiz game. Questions are displayed and read aloud via TTS. The player answers using keys 1-4 or A-D. Sound effects indicate correct and wrong answers. Score is shown at the end.

**File: `data/games/audioquiz/__game.tce`**

```
name_pl="Quiz Audio"
name_en="Audio Quiz Game"
description="Answer multiple-choice questions with audio feedback"
openfile="audioquiz.py"
shortname="audioquiz"
```

**File: `data/games/audioquiz/audioquiz.py`**

```python
import wx
import os
import sys
import random

# Add TCE root to path for imports
GAME_DIR = os.path.dirname(os.path.abspath(__file__))
TCE_ROOT = os.path.abspath(os.path.join(GAME_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

# Initialize pygame for sound effects
import pygame
if not pygame.mixer.get_init():
    pygame.mixer.init()

# TTS via accessible_output3
try:
    import accessible_output3.outputs.auto
    speaker = accessible_output3.outputs.auto.Auto()
except ImportError:
    speaker = None


def speak(text):
    """Speak text using screen reader or TTS."""
    if speaker:
        speaker.speak(text)


def play_sound(sound_name):
    """Play a sound file from the sfx directory."""
    try:
        sound_path = os.path.join(GAME_DIR, 'sfx', f'{sound_name}.wav')
        if os.path.exists(sound_path):
            sound = pygame.mixer.Sound(sound_path)
            sound.play()
    except Exception as e:
        print(f"Error playing sound: {e}")


# Question bank: list of dicts with "question", "choices" (list of 4), and "answer" (0-3 index)
QUESTIONS = [
    {
        "question": "What is the capital of France?",
        "choices": ["Berlin", "Paris", "Madrid", "Rome"],
        "answer": 1,
    },
    {
        "question": "Which planet is closest to the Sun?",
        "choices": ["Venus", "Earth", "Mercury", "Mars"],
        "answer": 2,
    },
    {
        "question": "What is 7 multiplied by 8?",
        "choices": ["48", "54", "56", "64"],
        "answer": 2,
    },
    {
        "question": "Which element has the chemical symbol O?",
        "choices": ["Gold", "Oxygen", "Osmium", "Oganesson"],
        "answer": 1,
    },
    {
        "question": "In which year did World War II end?",
        "choices": ["1943", "1944", "1945", "1946"],
        "answer": 2,
    },
    {
        "question": "What is the largest ocean on Earth?",
        "choices": ["Atlantic", "Indian", "Arctic", "Pacific"],
        "answer": 3,
    },
    {
        "question": "How many continents are there?",
        "choices": ["5", "6", "7", "8"],
        "answer": 2,
    },
    {
        "question": "Which gas do plants absorb from the atmosphere?",
        "choices": ["Oxygen", "Nitrogen", "Carbon Dioxide", "Hydrogen"],
        "answer": 2,
    },
    {
        "question": "What is the speed of light approximately in km per second?",
        "choices": ["150,000", "300,000", "450,000", "600,000"],
        "answer": 1,
    },
    {
        "question": "Who wrote Romeo and Juliet?",
        "choices": ["Charles Dickens", "William Shakespeare", "Mark Twain", "Jane Austen"],
        "answer": 1,
    },
]


class AudioQuizFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.SetTitle("Audio Quiz Game")
        self.SetSize((700, 500))
        self.Centre()

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Question display (read-only)
        self.display = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP
        )
        vbox.Add(self.display, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        # Answer buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_a = wx.Button(panel, label="A")
        self.btn_b = wx.Button(panel, label="B")
        self.btn_c = wx.Button(panel, label="C")
        self.btn_d = wx.Button(panel, label="D")

        self.btn_a.Bind(wx.EVT_BUTTON, lambda e: self.on_answer(0))
        self.btn_b.Bind(wx.EVT_BUTTON, lambda e: self.on_answer(1))
        self.btn_c.Bind(wx.EVT_BUTTON, lambda e: self.on_answer(2))
        self.btn_d.Bind(wx.EVT_BUTTON, lambda e: self.on_answer(3))

        for btn in (self.btn_a, self.btn_b, self.btn_c, self.btn_d):
            btn_sizer.Add(btn, proportion=1, flag=wx.EXPAND | wx.ALL, border=3)

        vbox.Add(btn_sizer, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=5)

        # New Game button
        self.new_game_btn = wx.Button(panel, label="New Game (F2)")
        self.new_game_btn.Bind(wx.EVT_BUTTON, self.on_new_game)
        vbox.Add(self.new_game_btn, flag=wx.EXPAND | wx.ALL, border=5)

        panel.SetSizer(vbox)

        # Keyboard shortcuts: F2 = new game, Escape = exit
        id_new = wx.NewIdRef()
        id_exit = wx.NewIdRef()
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_NORMAL, wx.WXK_F2, id_new),
            (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, id_exit),
        ])
        self.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_new_game, id=id_new)
        self.Bind(wx.EVT_MENU, self.on_exit, id=id_exit)

        # Bind key presses on the panel for 1-4 and A-D answer keys
        panel.Bind(wx.EVT_CHAR_HOOK, self.on_key)

        # Start the first game
        self.start_game()

    def start_game(self):
        """Initialize a new quiz session."""
        self.questions = random.sample(QUESTIONS, min(len(QUESTIONS), 10))
        self.current_index = 0
        self.score = 0
        self.total = len(self.questions)
        self.game_over = False
        self.waiting_for_answer = False

        play_sound("start")
        speak("New quiz game. Answer the questions using keys 1 through 4, or A through D.")
        self.show_question()

    def show_question(self):
        """Display the current question and read it aloud."""
        if self.current_index >= self.total:
            self.end_game()
            return

        q = self.questions[self.current_index]
        number = self.current_index + 1
        letters = ["A", "B", "C", "D"]

        text = f"Question {number} of {self.total}\n"
        text += "=" * 40 + "\n\n"
        text += q["question"] + "\n\n"
        for i, choice in enumerate(q["choices"]):
            text += f"  {letters[i]}. {choice}\n"
        text += f"\nScore: {self.score} / {self.total}\n"

        self.display.SetValue(text)

        # Update button labels with the answer text
        for i, btn in enumerate((self.btn_a, self.btn_b, self.btn_c, self.btn_d)):
            btn.SetLabel(f"{letters[i]}. {q['choices'][i]}")
            btn.Enable(True)

        # Read question aloud
        tts_text = f"Question {number}. {q['question']}. "
        for i, choice in enumerate(q["choices"]):
            tts_text += f"{letters[i]}: {choice}. "
        speak(tts_text)
        self.waiting_for_answer = True

    def on_answer(self, choice_index):
        """Handle the player selecting an answer (0-3)."""
        if self.game_over or not self.waiting_for_answer:
            return

        self.waiting_for_answer = False
        q = self.questions[self.current_index]
        correct_index = q["answer"]
        letters = ["A", "B", "C", "D"]

        if choice_index == correct_index:
            self.score += 1
            msg = f"Correct! The answer is {letters[correct_index]}: {q['choices'][correct_index]}."
            play_sound("correct")
            speak(msg)
        else:
            msg = (
                f"Wrong. You chose {letters[choice_index]}: {q['choices'][choice_index]}. "
                f"The correct answer is {letters[correct_index]}: {q['choices'][correct_index]}."
            )
            play_sound("wrong")
            speak(msg)

        self.display.AppendText("\n" + msg + "\n")

        # Disable buttons briefly, then move to next question
        for btn in (self.btn_a, self.btn_b, self.btn_c, self.btn_d):
            btn.Enable(False)

        self.current_index += 1
        wx.CallLater(2000, self.show_question)

    def end_game(self):
        """Display the final score."""
        self.game_over = True
        percentage = int((self.score / self.total) * 100) if self.total > 0 else 0

        text = "Quiz Complete!\n"
        text += "=" * 40 + "\n\n"
        text += f"Final Score: {self.score} out of {self.total} ({percentage}%)\n\n"
        if percentage == 100:
            text += "Perfect score! Outstanding!\n"
        elif percentage >= 70:
            text += "Great job!\n"
        elif percentage >= 50:
            text += "Not bad, keep practicing!\n"
        else:
            text += "Better luck next time!\n"
        text += "\nPress F2 to play again or Escape to exit.\n"

        self.display.SetValue(text)

        for btn in (self.btn_a, self.btn_b, self.btn_c, self.btn_d):
            btn.Enable(False)

        play_sound("game_over")
        speak(
            f"Quiz complete. Your score is {self.score} out of {self.total}, "
            f"{percentage} percent. Press F2 to play again."
        )

    def on_key(self, event):
        """Handle keyboard shortcuts for answering."""
        if self.game_over or not self.waiting_for_answer:
            event.Skip()
            return

        key = event.GetKeyCode()
        uchar = event.GetUnicodeKey()

        # Number keys 1-4
        if key in (ord('1'), wx.WXK_NUMPAD1):
            self.on_answer(0)
            return
        elif key in (ord('2'), wx.WXK_NUMPAD2):
            self.on_answer(1)
            return
        elif key in (ord('3'), wx.WXK_NUMPAD3):
            self.on_answer(2)
            return
        elif key in (ord('4'), wx.WXK_NUMPAD4):
            self.on_answer(3)
            return

        # Letter keys A-D (case-insensitive via unicode char)
        if uchar != wx.WXK_NONE:
            ch = chr(uchar).upper()
            if ch == 'A':
                self.on_answer(0)
                return
            elif ch == 'B':
                self.on_answer(1)
                return
            elif ch == 'C':
                self.on_answer(2)
                return
            elif ch == 'D':
                self.on_answer(3)
                return

        event.Skip()

    def on_new_game(self, event):
        """Start a new quiz."""
        self.start_game()

    def on_exit(self, event):
        """Exit the game."""
        self.Close()


if __name__ == "__main__":
    app = wx.App(False)
    frame = AudioQuizFrame(None)
    frame.Show()
    app.MainLoop()
```

**Sound effects directory: `data/games/audioquiz/sfx/`**

Place the following `.wav` files in the `sfx/` folder:
- `start.wav` - played when a new quiz begins
- `correct.wav` - played when the player answers correctly
- `wrong.wav` - played when the player answers incorrectly
- `game_over.wav` - played when the quiz is complete and the final score is shown

---

## Action:

Ask the user for game details and create a complete, playable game following TCE Launcher conventions.
