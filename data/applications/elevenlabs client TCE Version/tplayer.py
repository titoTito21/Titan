import pygame
import shutil
import threading

class TPlayer:
    def __init__(self, audio_file):
        pygame.init()
        pygame.mixer.init()
        self.audio_file = audio_file
        self.is_playing = False
        self.is_paused = False
        self.screen = pygame.display.set_mode((400, 300))
        pygame.display.set_caption("TPlayer")
        self.font = pygame.font.Font(None, 36)
        self.load_file(audio_file)

    def load_file(self, audio_file):
        self.audio_file = audio_file
        pygame.mixer.music.load(audio_file)
        self.play_audio()

    def play_audio(self):
        pygame.mixer.music.play()
        self.is_playing = True
        self.is_paused = False

    def play_pause(self):
        if not self.is_playing:
            self.play_audio()
        elif self.is_paused:
            pygame.mixer.music.unpause()
            self.is_paused = False
        else:
            pygame.mixer.music.pause()
            self.is_paused = True

    def rewind(self):
        pos = pygame.mixer.music.get_pos() / 1000
        new_pos = max(0, pos - 0.05 * pygame.mixer.Sound(self.audio_file).get_length())
        pygame.mixer.music.play(start=new_pos)

    def forward(self):
        pos = pygame.mixer.music.get_pos() / 1000
        new_pos = min(pygame.mixer.Sound(self.audio_file).get_length(), pos + 0.05 * pygame.mixer.Sound(self.audio_file).get_length())
        pygame.mixer.music.play(start=new_pos)

    def save_file(self):
        save_path = input("Enter the path to save the file: ")
        threading.Thread(target=self._save_file_thread, args=(save_path,)).start()

    def _save_file_thread(self, save_path):
        try:
            shutil.copy(self.audio_file, save_path)
            print("File saved successfully.")
        except IOError:
            print("Failed to save file.")

    def display_instructions(self):
        self.screen.fill((0, 0, 0))
        instructions = [
            "TPlayer",
            "Press S to save the file.",
            "Press SPACE to play/pause.",
            "Press LEFT/RIGHT to rewind/forward.",
            "Press ESC to exit."
        ]
        for i, line in enumerate(instructions):
            text = self.font.render(line, True, (255, 255, 255))
            self.screen.blit(text, (20, 20 + i * 40))
        pygame.display.flip()

    def run(self):
        running = True
        while running:
            self.display_instructions()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_s:
                        self.save_file()
                    elif event.key == pygame.K_SPACE:
                        self.play_pause()
                    elif event.key == pygame.K_LEFT:
                        self.rewind()
                    elif event.key == pygame.K_RIGHT:
                        self.forward()
                    elif event.key == pygame.K_ESCAPE:
                        running = False

        pygame.quit()

if __name__ == "__main__":
    audio_file = "path_to_audio_file.mp3"  # Replace with the actual path to the audio file
    player = TPlayer(audio_file)
    player.run()
