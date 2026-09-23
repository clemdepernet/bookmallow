<p align="center"><img src="bookmallow/static/logo.svg" width="96" alt=""></p>
<h1 align="center">Bookmallow</h1>
<p align="center">Tes vidéos YouTube en audiobooks MP3, en douceur. · Your YouTube videos as audiobook MP3s, gently.</p>
<p align="center"><img src="docs/screenshot.png" width="720" alt="Bookmallow screenshot"></p>

---

## 🇫🇷 Français

Bookmallow est un petit conteneur auto-hébergé : tu colles un lien YouTube, il te rend un MP3 « audiobook », depuis une interface pastel accessible depuis ton téléphone. Il est conçu pour un Raspberry Pi et pour les vidéos **très** longues (10 h, 17 h…) : l'audio est converti **en streaming**, sans jamais stocker la vidéo ni l'audio brut sur le disque.

### Pourquoi

- **Zéro fichier intermédiaire** : `yt-dlp` envoie l'audio directement à `ffmpeg`. Une vidéo de 10 h pèse ~290 Mo en 64 kbps mono, au lieu de 1,5 Go de pic avec un téléchargement classique.
- **File d'attente** : une conversion à la fois, progression en direct, annulation, reprise après redémarrage.
- **Rétention** : Bookmallow ne garde que les `MAX_FILES` derniers fichiers (6 par défaut). L'interface le rappelle et marque le prochain fichier qui disparaîtra.
- **Pour partager** : mot de passe optionnel, interface FR/EN, aucune ressource externe.

### Démarrer en 3 commandes

```bash
mkdir bookmallow && cd bookmallow
curl -fsSLO https://raw.githubusercontent.com/clemdepernet/bookmallow/main/docker-compose.yml
docker compose up -d
```

Ouvre `http://<ton-serveur>:7843`. Les MP3 arrivent dans `./data`.

### Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `MAX_FILES` | `6` | Nombre de MP3 conservés ; les plus anciens sont supprimés |
| `DEFAULT_QUALITY` | `64` | `64` (voix, mono, ~29 Mo/h), `128` (~58 Mo/h) ou `192` (~86 Mo/h) |
| `APP_PASSWORD` | vide | Mot de passe partagé ; vide = pas de connexion |
| `DEFAULT_LANG` | `fr` | `fr` ou `en` (chaque personne peut basculer) |
| `MIN_FREE_MB` | `500` | Espace disque à toujours garder libre |
| `MAX_DURATION_HOURS` | `0` | `0` = aucune limite de durée |
| `PUID` / `PGID` | `1000` | Propriétaire des fichiers dans `./data` |
| `TZ` | `UTC` | Fuseau horaire des logs |
| `YTDLP_AUTO_UPDATE` | `0` | `1` = met yt-dlp à jour à chaque démarrage |
| `FORCE_HTTPS` | `0` | `1` derrière un reverse proxy HTTPS (cookie `Secure`) |
| `SECRET_KEY` | générée | Clé des sessions, persistée dans `/data/.secret` |

### Partager avec ses amies

Mets un `APP_PASSWORD`, puis expose le port 7843 avec ton reverse proxy habituel (Nginx Proxy Manager, Caddy, Traefik) ou un tunnel Cloudflare. Bookmallow n'accepte que des liens YouTube et ne convertit qu'une vidéo à la fois : même partagé, il reste sage avec ton Pi.

### YouTube change souvent

`yt-dlp` doit suivre YouTube de près. L'image est reconstruite **chaque lundi** avec la dernière version : un `docker compose pull && docker compose up -d` suffit. En dépannage rapide, `YTDLP_AUTO_UPDATE=1` met yt-dlp à jour au démarrage du conteneur.

### Construire soi-même

```bash
git clone https://github.com/clemdepernet/bookmallow.git && cd bookmallow
docker build --target test .        # lance la suite de tests dans l'image
docker compose up -d --build        # après avoir décommenté `build: .`
```

---

## 🇬🇧 English

Bookmallow is a tiny self-hosted container: paste a YouTube link, get an audiobook-style MP3 from a pastel web UI that works on your phone. It is built for a Raspberry Pi and for **very** long videos (10 h, 17 h…): audio is converted **while streaming**, the video or raw audio is never written to disk.

### Why

- **No intermediate file**: `yt-dlp` pipes audio straight into `ffmpeg`. A 10-hour video is ~290 MB at 64 kbps mono instead of a 1.5 GB peak with a classic download-then-convert.
- **Queue**: one conversion at a time, live progress, cancel, recovery after a restart.
- **Retention**: only the newest `MAX_FILES` files are kept (6 by default). The UI says so and marks the next file to go.
- **Made to share**: optional password, FR/EN interface, no external resources.

### Quick start

```bash
mkdir bookmallow && cd bookmallow
curl -fsSLO https://raw.githubusercontent.com/clemdepernet/bookmallow/main/docker-compose.yml
docker compose up -d
```

Open `http://<your-server>:7843`. MP3s land in `./data`.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `MAX_FILES` | `6` | MP3s kept; older ones are deleted |
| `DEFAULT_QUALITY` | `64` | `64` (voice, mono, ~29 MB/h), `128` (~58 MB/h) or `192` (~86 MB/h) |
| `APP_PASSWORD` | empty | Shared password; empty = no login |
| `DEFAULT_LANG` | `fr` | `fr` or `en` (each visitor can switch) |
| `MIN_FREE_MB` | `500` | Disk space to always keep free |
| `MAX_DURATION_HOURS` | `0` | `0` = no duration limit |
| `PUID` / `PGID` | `1000` | Owner of the files in `./data` |
| `TZ` | `UTC` | Log timezone |
| `YTDLP_AUTO_UPDATE` | `0` | `1` = upgrade yt-dlp at every start |
| `FORCE_HTTPS` | `0` | `1` behind an HTTPS reverse proxy (`Secure` cookie) |
| `SECRET_KEY` | generated | Session key, persisted in `/data/.secret` |

### Sharing with friends

Set `APP_PASSWORD`, then expose port 7843 through your usual reverse proxy (Nginx Proxy Manager, Caddy, Traefik) or a Cloudflare tunnel. Bookmallow only accepts YouTube links and converts one video at a time, so it stays gentle with your Pi even when shared.

### YouTube changes often

`yt-dlp` has to keep up with YouTube. The image is rebuilt **every Monday** with the latest release: `docker compose pull && docker compose up -d` is all you need. As a quick fix, `YTDLP_AUTO_UPDATE=1` upgrades yt-dlp when the container starts.

### Build it yourself

```bash
git clone https://github.com/clemdepernet/bookmallow.git && cd bookmallow
docker build --target test .        # runs the test suite inside the image
docker compose up -d --build        # after uncommenting `build: .`
```

---

## Credits

Bookmallow started as a fork of [TheFatPanda-Dev/youtube-to-mp3-docker](https://github.com/TheFatPanda-Dev/youtube-to-mp3-docker) (MIT). Thank you! The backend was rewritten around streaming conversion, a queue and retention; the pastel UI is new.

Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp), [ffmpeg](https://ffmpeg.org), [Flask](https://flask.palletsprojects.com) and [deno](https://deno.com). MIT license.
