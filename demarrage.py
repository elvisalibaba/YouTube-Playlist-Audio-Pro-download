"""Installation locale des dépendances et démarrage, diagnostic visible sur Windows."""
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

BASE = Path(__file__).resolve().parent
VENV = BASE / ".venv"
LOG = BASE / "diagnostic_demarrage.txt"


def report(message):
    print(message, flush=True)
    with LOG.open("a", encoding="utf-8") as fd:
        fd.write(message + "\n")


def main():
    LOG.write_text("Media Select Pro V7 - diagnostic\n", encoding="utf-8")
    if sys.version_info < (3, 11):
        report("ERREUR : Python 3.11 ou supérieur est nécessaire.")
        return 1
    python = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        report("Création de l'environnement Python local…")
        venv.EnvBuilder(with_pip=True).create(VENV)
    test = subprocess.run([str(python), "-c", "import yt_dlp"], capture_output=True)
    if test.returncode:
        report("Installation de yt-dlp et de ses dépendances… (Internet nécessaire au premier lancement)")
        with LOG.open("a", encoding="utf-8") as log:
            proc = subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "yt-dlp[default]"],
                                  stdout=log, stderr=subprocess.STDOUT)
        if proc.returncode:
            report("ERREUR : installation impossible. Voir diagnostic_demarrage.txt.")
            return 2
    report("yt-dlp : OK")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        report("ATTENTION : FFmpeg/FFprobe absent. Installer avec winget install Gyan.FFmpeg")
    else:
        report("FFmpeg : OK")
    if not shutil.which("deno"):
        report("Conseil : installer Deno pour le support YouTube : winget install DenoLand.Deno")
    report("Démarrage de l'interface locale...")
    return subprocess.call([str(python), str(BASE / "serveur.py")])

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        report(f"ÉCHEC : {exc}")
        sys.exit(1)
