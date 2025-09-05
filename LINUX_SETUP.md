# TCE Launcher - Linux Setup Guide

This guide helps you set up TCE Launcher on Linux systems.

## System Requirements

- Python 3.8+ 
- Linux distribution with GUI desktop environment
- Audio system (PulseAudio or ALSA)

## Dependencies Installation

### Ubuntu/Debian:
```bash
sudo apt update
sudo apt install python3-pip python3-wxgtk4.0 python3-pygame
sudo apt install pulseaudio-utils alsa-utils  # Audio control
sudo apt install pavucontrol                  # Volume mixer (optional)
sudo apt install network-manager              # Network management
sudo apt install gnome-control-center         # Settings (GNOME)
```

### Fedora/RHEL/CentOS:
```bash
sudo dnf install python3-pip python3-wxpython4 python3-pygame
sudo dnf install pulseaudio-utils alsa-utils  # Audio control  
sudo dnf install pavucontrol                  # Volume mixer (optional)
sudo dnf install NetworkManager NetworkManager-gnome
sudo dnf install gnome-control-center         # Settings (GNOME)
```

### Arch Linux:
```bash
sudo pacman -S python-pip python-wxpython python-pygame
sudo pacman -S pulseaudio-alsa alsa-utils     # Audio control
sudo pacman -S pavucontrol                    # Volume mixer (optional)
sudo pacman -S networkmanager network-manager-applet
sudo pacman -S gnome-control-center           # Settings (GNOME)
```

### KDE Plasma Users:
Replace `gnome-control-center` with:
```bash
# For KDE Plasma 5
sudo apt install systemsettings  # Debian/Ubuntu
sudo dnf install systemsettings5 # Fedora
sudo pacman -S systemsettings5   # Arch

# For older KDE
sudo apt install systemsettings-kde4
```

## Python Dependencies
```bash
pip3 install -r requirements.txt
```

## Audio System Setup

### PulseAudio (Recommended):
```bash
# Check if PulseAudio is running
pulseaudio --check

# Start PulseAudio if needed
pulseaudio --start

# Test volume control
pactl get-sink-volume @DEFAULT_SINK@
```

### ALSA (Alternative):
```bash
# Test ALSA mixer
amixer get Master

# If no sound cards detected
sudo modprobe snd-dummy
```

## Screen Reader Support

### Orca (GNOME):
```bash
sudo apt install orca          # Ubuntu/Debian
sudo dnf install orca          # Fedora
sudo pacman -S orca            # Arch

# Enable Orca
gsettings set org.gnome.desktop.a11y.applications screen-reader-enabled true
```

### Speech Dispatcher:
```bash
sudo apt install speech-dispatcher espeak-ng
sudo systemctl enable --now speech-dispatcher
```

## Network Management

Ensure NetworkManager is running:
```bash
sudo systemctl enable --now NetworkManager
```

For WiFi control, install a GUI:
```bash
# GNOME
sudo apt install network-manager-gnome

# KDE  
sudo apt install plasma-nm

# Generic
sudo apt install nm-connection-editor
```

## Running TCE Launcher

1. Navigate to TCE Launcher directory:
```bash
cd "/path/to/TCE Launcher"
```

2. Run the application:
```bash
python3 main.py
```

## Troubleshooting

### Audio Issues:
```bash
# Check audio devices
aplay -l

# Test pygame mixer
python3 -c "import pygame.mixer; pygame.mixer.init(); print('Audio OK')"
```

### wxPython Issues:
```bash
# Install wxPython from wheel if pip fails
pip3 install -U -f https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-20.04 wxPython
```

### Permission Issues:
```bash
# Add user to audio group
sudo usermod -a -G audio $USER

# Logout and login again
```

### Network Detection:
```bash
# Test network commands
nmcli device status
iwconfig
ip route show default
```

## Desktop Integration

Create a desktop entry:
```bash
cat > ~/.local/share/applications/tce-launcher.desktop << EOF
[Desktop Entry]
Name=TCE Launcher
Comment=Accessible desktop environment
Exec=python3 "/path/to/TCE Launcher/main.py"
Icon=/path/to/TCE Launcher/icon.png
Terminal=false
Type=Application
Categories=Accessibility;Utility;
EOF
```

## Known Linux-Specific Features

✅ **Working:**
- Battery status monitoring (`/sys/class/power_supply/`)
- Volume control (PulseAudio/ALSA)
- Network status (NetworkManager/iwconfig)
- System settings integration
- Audio playback (pygame)
- Screen reader support (accessible-output3)

⚠️ **Limited:**
- Some desktop environments may have different settings applications
- Audio system detection depends on installed components
- Screen reader integration varies by desktop environment

🚫 **Not Available:**
- Windows-specific COM functionality
- Windows-specific screen readers (NVDA/JAWS)
- Windows registry access

## Performance Tips

1. **Audio Latency:**
```bash
# Reduce PulseAudio latency
echo "default-sample-rate = 48000" >> ~/.pulse/daemon.conf
echo "default-fragment-size-msec = 25" >> ~/.pulse/daemon.conf
```

2. **Memory Usage:**
```bash
# Monitor memory usage
ps aux | grep python3
```

3. **Startup Optimization:**
- Add TCE Launcher to autostart applications in your desktop environment
- Use `python3 -O main.py` for optimized bytecode

## Support

If you encounter Linux-specific issues:
1. Check system logs: `journalctl -f`  
2. Test audio: `speaker-test -c2`
3. Verify wxPython: `python3 -c "import wx; print(wx.version())"`
4. Check permissions: `groups $USER`

For more help, create an issue on the GitHub repository with:
- Linux distribution and version (`lsb_release -a`)
- Desktop environment (`echo $XDG_CURRENT_DESKTOP`)
- Python version (`python3 --version`)
- Error logs and terminal output