# Media Select Pro V7 — Sélection audio et vidéo multi-sites

Application Python locale avec interface Web sur `127.0.0.1`. Elle conserve les fonctionnalités de la V6 et corrige un défaut : les **pages de profil et d'accueil ne sont pas automatiquement des URL vidéo valables pour yt-dlp**.

## Deux correctifs de découverte

**Eporner — page de profil publique**

Colle `https://www.eporner.com/profile/Jessy18/`. La V7 tente de lire la page « Uploaded videos » du profil et affiche les liens vidéo publics trouvés. Elle n'envoie **jamais** l'URL de profil à yt-dlp pour la télécharger. Si l'onglet ne fonctionne pas dans le navigateur, essaie directement `https://www.eporner.com/profile/Jessy18/uploaded-videos/`.

**Djatoya — page d'accueil publique**

Colle `https://djatoya.com/`. La V7 cherche les liens publics vers les fiches de vidéos, par exemple celles de la forme `/video/12345/titre/`. Elle permet de choisir parmi les liens trouvés. **Important : la découverte de liens n'est pas une preuve que la vidéo est extractible.** Djatoya n'a pas d'extracteur dédié répertorié dans la liste officielle de yt-dlp. Un lien vidéo Djatoya peut encore afficher `Unsupported URL` ; le logiciel montre alors l'erreur dans le journal, sans prétendre avoir téléchargé le contenu.

Pour les autres sites, le fonctionnement habituel de `yt-dlp` est conservé : une URL de vidéo, de playlist ou de chaîne compatible. Il n'existe pas de prise en charge garantie de tous les sites, et les DRM ne sont pas contournés.

## Installation (Windows 10/11)

1. Installer **Python 3.11 ou supérieur** depuis https://www.python.org/downloads/ (cocher « Add Python to PATH »).
2. Extraire entièrement le fichier ZIP.
3. Dans le dossier `Media_Select_Pro_V7`, double-cliquer sur **`OUVRIR_WINDOWS.cmd`**.
4. Le premier démarrage crée `.venv` et installe `yt-dlp[default]` via Internet.
5. Garder la fenêtre noire ouverte. L'interface Web s'ouvre dans ton navigateur.

Pour les conversions MP3/M4A et les vidéos de meilleure qualité, installer FFmpeg ; pour YouTube, installer Deno peut être nécessaire :

```powershell
winget install Gyan.FFmpeg
winget install DenoLand.Deno
```

Relancer le programme après installation. Le script de lancement garde la fenêtre ouverte et écrit `diagnostic_demarrage.txt` en cas de problème.

## Utilisation pour un profil ou une page d'accueil

1. Coller **l'URL de la page** et cliquer **Analyser et afficher les vidéos**.
2. Examiner les titres présentés ; les 5 premiers sont sélectionnés par défaut.
3. Choisir quelques vidéos, « Tout cocher », ou « Toutes les vidéos de cette page ».
4. Si le site expose une page suivante, le bouton **Afficher la page suivante du site** permet de passer à celle-ci. La sélection précédente n'est pas conservée lors du changement de page.
5. Choisir audio original, MP3, M4A, vidéo qualité maximale ou MP4 avec plafond 360p–2160p selon les formats disponibles.
6. Sélectionner un dossier qui existe déjà et lancer le téléchargement.
7. Consulter le **journal** : il montre les erreurs d'extraction et ne promet pas qu'une vidéo a été téléchargée si la liste a simplement été trouvée.

### Différence importante : « tout »

- **Page publique découverte** (Eporner/Djatoya) : « Tout » veut dire **tous les liens détectés et affichés sur cette page**, plafonnés à 100 par page. Ce n'est pas l'intégralité d'un profil comptant des milliers de vidéos. Utiliser la navigation par pages.
- **Playlist native reconnue par yt-dlp** : « Toute la playlist » peut inclure plus d'éléments que l'aperçu de 250, selon le site.
- **Plusieurs URL collées** (2 à 30 liens individuels) : « Tous les liens collés » concerne uniquement ces URL.

Les URL découvertes sont transmises au téléchargeur **par petits lots de 8 maximum**, sans jamais télécharger la page catalogue elle-même. Les sites peuvent changer leur structure et bloquer la lecture automatique des listes.

## Sécurité, limites et précision

- La découverte HTML est limitée explicitement à Eporner (pages de profil) et Djatoya (pages publiques). Les URL en dehors de ces domaines ne sont pas suivies pendant la découverte.
- Connexions HTTPS, refus des adresses IP locales/privées, limitation de la taille des pages et des redirections externes.
- Aucune utilisation de cookies privés, aucune authentification automatique et aucun contournement de DRM/paywall/contrôle d'accès.
- La version actuelle ne dispose pas d'un extracteur spécifique pour les lecteurs internes de Djatoya. Pour être pleinement compatible avec ces lecteurs, une analyse technique de pages vidéo publiques et de leurs flux serait encore nécessaire. **Le fonctionnement des téléchargements Djatoya n'est pas validé.**
- Ne télécharger que des contenus dont l'accès et la copie sont autorisés. Pour des contenus intimes, s'assurer du consentement des personnes concernées ; ne pas télécharger ni partager de contenus privés ou diffusés sans consentement.
- Aucun téléchargement réel de ces sites n'a été possible dans notre environnement de tests. Les tests automatisés utilisent des pages HTML simulées et les URL publiques vérifiées dans leur structure.

## Dépannage

- **« Aucun lien vidéo détecté »** : la page peut demander JavaScript, être vide ou avoir changé ; essayer une autre page publique ou coller des liens vidéo individuels.
- **« Unsupported URL » sur une vidéo Djatoya** : la liste a été découverte mais yt-dlp n'a pas pu extraire le lecteur. Ce n'est pas un échec de sélection.
- **« Unsupported URL » sur un profil Eporner** : vérifier que tu as lancé la V7 et non l'ancien lanceur V6, puis utiliser l'adresse `/uploaded-videos/`.
- **Accès refusé / 403** : le site bloque la lecture automatique. Le logiciel n'essaie pas de contourner cette restriction.
- **Pas de FFmpeg** : installer les outils ci-dessus et rouvrir l'application.

## Tests locaux

```bash
python -m unittest -v tests.py
```

Ressources : https://github.com/yt-dlp/yt-dlp , https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md
