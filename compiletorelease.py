import subprocess
import sys
import os

def compile_with_nuitka(source_file):
    if not os.path.isfile(source_file):
        print(f"File '{source_file}' does not exist.")
        return

    print(f"Starting compilation of {source_file} with Nuitka...")

    command = [
        "python", "-m", "nuitka",
        "--standalone",
        "--mingw64",
        "--onefile",
        "--output-dir=output",
        "--nofollow-imports",   # Opcja dla szybszej kompilacji
        "--disable-console",    # Opcja, aby nie otwierać konsoli
        source_file
    ]

    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"Compilation successful: {result.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"Error during compilation: {e.stderr}")

    print(f"Finished compilation of {source_file}. Output can be found in the 'output' directory.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python compile_script.py <source_file.py>")
    else:
        source_file = sys.argv[1]
        compile_with_nuitka(source_file)
