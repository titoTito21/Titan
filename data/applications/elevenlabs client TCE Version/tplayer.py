import pygame
import shutil
import threading
import os
import wx

class TPlayer:
    def __init__(self, audio_file):
        try:
            pygame.init()
            pygame.mixer.init()
            self.audio_file = audio_file
            self.is_playing = False
            self.is_paused = False
            self.music_length = 0
            self.screen = pygame.display.set_mode((400, 300))
            pygame.display.set_caption("TPlayer - Audio Player")
            self.font = pygame.font.Font(None, 36)
            self.small_font = pygame.font.Font(None, 24)
            self.load_file(audio_file)
        except Exception as e:
            print(f"Error initializing TPlayer: {e}")
            raise

    def load_file(self, audio_file):
        try:
            self.audio_file = audio_file
            pygame.mixer.music.load(audio_file)
            # Get audio length
            try:
                sound = pygame.mixer.Sound(audio_file)
                self.music_length = sound.get_length()
            except:
                self.music_length = 0
            self.play_audio()
        except Exception as e:
            print(f"Error loading audio file: {e}")
            raise

    def play_audio(self):
        try:
            pygame.mixer.music.play()
            self.is_playing = True
            self.is_paused = False
        except Exception as e:
            print(f"Error playing audio: {e}")

    def play_pause(self):
        try:
            if not self.is_playing:
                self.play_audio()
            elif self.is_paused:
                pygame.mixer.music.unpause()
                self.is_paused = False
            else:
                pygame.mixer.music.pause()
                self.is_paused = True
        except Exception as e:
            print(f"Error in play/pause: {e}")

    def rewind(self):
        try:
            # Rewind 5 seconds
            pygame.mixer.music.rewind()
        except Exception as e:
            print(f"Error rewinding: {e}")

    def forward(self):
        try:
            # Stop and replay (pygame.mixer.music doesn't support forward)
            current_pos = pygame.mixer.music.get_pos() / 1000.0
            new_pos = min(self.music_length, current_pos + 5.0)
            if new_pos < self.music_length:
                pygame.mixer.music.play(start=new_pos)
        except Exception as e:
            print(f"Error forwarding: {e}")

    def save_file(self):
        try:
            # Use wxPython file dialog
            app = wx.App(False)
            with wx.FileDialog(None, "Save audio file",
                              wildcard="MP3 files (*.mp3)|*.mp3|All files (*.*)|*.*",
                              style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
                if fileDialog.ShowModal() == wx.ID_OK:
                    save_path = fileDialog.GetPath()
                    threading.Thread(target=self._save_file_thread, args=(save_path,)).start()
            app.Destroy()
        except Exception as e:
            print(f"Error saving file: {e}")

    def _save_file_thread(self, save_path):
        try:
            shutil.copy(self.audio_file, save_path)
            # Show success message
            app = wx.App(False)
            wx.MessageBox("File saved successfully.", "Success", wx.OK | wx.ICON_INFORMATION)
            app.Destroy()
        except Exception as e:
            # Show error message
            app = wx.App(False)
            wx.MessageBox(f"Failed to save file: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)
            app.Destroy()

    def get_status_text(self):
        """Get current playback status"""
        if self.is_paused:
            return "PAUSED"
        elif self.is_playing:
            return "PLAYING"
        else:
            return "STOPPED"

    def get_position(self):
        """Get current playback position"""
        if pygame.mixer.music.get_busy():
            pos = pygame.mixer.music.get_pos() / 1000.0
            return pos
        return 0

    def format_time(self, seconds):
        """Format seconds to MM:SS"""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"

    def display_instructions(self):
        try:
            self.screen.fill((20, 20, 30))  # Dark blue background

            # Title
            title = self.font.render("TPlayer - Audio Player", True, (255, 255, 100))
            self.screen.blit(title, (50, 20))

            # Status
            status_text = f"Status: {self.get_status_text()}"
            status = self.small_font.render(status_text, True, (100, 255, 100))
            self.screen.blit(status, (50, 70))

            # Position / Duration
            current_pos = self.get_position()
            time_text = f"Time: {self.format_time(current_pos)} / {self.format_time(self.music_length)}"
            time = self.small_font.render(time_text, True, (200, 200, 200))
            self.screen.blit(time, (50, 100))

            # File name
            filename = os.path.basename(self.audio_file)
            if len(filename) > 30:
                filename = filename[:27] + "..."
            file_text = self.small_font.render(f"File: {filename}", True, (200, 200, 200))
            self.screen.blit(file_text, (50, 130))

            # Instructions
            instructions = [
                "Controls:",
                "SPACE - Play/Pause",
                "LEFT  - Rewind",
                "RIGHT - Forward",
                "S     - Save file",
                "ESC   - Exit"
            ]
            y_offset = 170
            for i, line in enumerate(instructions):
                if i == 0:
                    text = self.small_font.render(line, True, (255, 200, 100))
                else:
                    text = self.small_font.render(line, True, (180, 180, 180))
                self.screen.blit(text, (50, y_offset + i * 25))

            pygame.display.flip()
        except Exception as e:
            print(f"Error displaying instructions: {e}")

    def run(self):
        try:
            running = True
            clock = pygame.time.Clock()

            while running:
                # Check if music has ended
                if self.is_playing and not pygame.mixer.music.get_busy():
                    self.is_playing = False

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

                clock.tick(30)  # 30 FPS

            pygame.mixer.music.stop()
            pygame.quit()
        except Exception as e:
            print(f"Error in run loop: {e}")
            pygame.quit()

if __name__ == "__main__":
    audio_file = "path_to_audio_file.mp3"  # Replace with the actual path to the audio file
    player = TPlayer(audio_file)
    player.run()
