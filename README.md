# YouTube Playlist Audio Pro Download

Application Python locale avec interface Web pour analyser et télécharger des vidéos, des playlists et des pistes audio avec `yt-dlp`.

## Fonctionnalités

- Analyse d'une URL de vidéo, de playlist ou de chaîne compatible avec `yt-dlp`.
- Affichage des vidéos sous forme de cartes avec miniature, titre, chaîne et durée.
- Sélection individuelle ou groupée des éléments à télécharger.
- Téléchargement dans le format audio original, MP3 ou M4A.
- Téléchargement vidéo en qualité maximale ou en MP4 avec une résolution choisie.
- Affichage de la progression et des erreurs dans le journal de l'application.
- Interface accessible uniquement en local sur `127.0.0.1`.

## Installation sous Windows 10 et 11

1. Installer **Python 3.11 ou une version supérieure** depuis https://www.python.org/downloads/ en cochant l'option « Add Python to PATH ».
2. Télécharger ou extraire entièrement le projet.
3. Ouvrir le dossier du projet.
4. Double-cliquer sur **`OUVRIR_WINDOWS.cmd`**.
5. Au premier démarrage, patienter pendant la création de `.venv` et l'installation des dépendances.
6. Garder la fenêtre de commande ouverte pendant l'utilisation.

L'interface s'ouvre automatiquement dans le navigateur. En cas de problème au démarrage, consulter `diagnostic_demarrage.txt`.

## Outils recommandés

FFmpeg est nécessaire pour certaines conversions audio et pour obtenir les meilleures qualités vidéo. Deno peut être nécessaire pour certaines vidéos YouTube.

```powershell
winget install Gyan.FFmpeg
winget install DenoLand.Deno
```

Relancer l'application après l'installation.

## Utilisation

1. Coller l'URL d'une vidéo, d'une playlist ou d'une chaîne compatible.
2. Cliquer sur **Analyser et afficher les vidéos**.
3. Sélectionner les éléments à télécharger.
4. Choisir le format audio ou vidéo souhaité.
5. Sélectionner un dossier de destination existant.
6. Lancer le téléchargement et suivre sa progression dans le journal.

Pour plusieurs liens individuels, coller entre 2 et 30 URL. L'option **Tous les liens collés** concerne uniquement les URL saisies.

## Formats disponibles

- Audio original
- MP3
- M4A
- Vidéo en qualité maximale
- MP4 avec une résolution comprise entre 360p et 2160p, selon les formats disponibles

## Sécurité et limites

- L'application fonctionne localement et n'expose pas son interface sur le réseau.
- Les connexions externes utilisent HTTPS lorsque le site le permet.
- L'application ne contourne pas les DRM, les paywalls ou les contrôles d'accès.
- La compatibilité dépend des sites et des extracteurs pris en charge par `yt-dlp`.
- Télécharger uniquement les contenus dont l'accès et la copie sont autorisés.

## Dépannage

- **URL non prise en charge** : vérifier que l'adresse est correcte et que le site figure parmi les plateformes compatibles avec `yt-dlp`.
- **Accès refusé ou erreur 403** : le site bloque la lecture automatique de la page.
- **FFmpeg introuvable** : installer FFmpeg avec la commande indiquée plus haut, puis relancer l'application.
- **L'interface ne s'ouvre pas** : consulter `diagnostic_demarrage.txt` et vérifier que la fenêtre de commande reste ouverte.

## Tests locaux

```bash
python -m unittest -v tests.py
```

## Ressources

- https://github.com/yt-dlp/yt-dlp
- https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md
