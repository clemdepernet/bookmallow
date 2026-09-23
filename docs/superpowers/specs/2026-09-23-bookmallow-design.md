# Bookmallow — design v1

Date : 2026-09-23
Statut : validé avec Clem (retention 6 fichiers, 64 kbps mono par défaut, mot de passe partagé, un MP3 par vidéo, playlists prises en charge).

## 1. But

Bookmallow est un conteneur Docker auto-hébergeable qui transforme une vidéo YouTube en
fichier MP3 « audiobook » depuis une petite interface web pastel. Il est pensé pour tourner
sur une machine modeste (Raspberry Pi 5, 8 Go de RAM, disque partagé avec une stack média)
et traiter des vidéos très longues (8 à 10 heures) sans saturer le disque.

Il est dérivé de [TheFatPanda-Dev/youtube-to-mp3-docker](https://github.com/TheFatPanda-Dev/youtube-to-mp3-docker)
(MIT). L'historique git du dépôt d'origine est conservé ; le README le remercie.

### Ce que l'original ne fait pas et que Bookmallow doit faire

| Manque dans l'original | Réponse de Bookmallow |
|---|---|
| Chaque requête lance un thread sans limite | File d'attente, un seul job actif à la fois |
| Téléchargement de l'audio brut sur disque puis conversion (≈ 1,5 Go de pic pour 10 h) | Conversion en streaming : yt-dlp → tube → ffmpeg, seul le MP3 final touche le disque |
| 192 kbps stéréo imposé (≈ 86 Mo/h) | 64 kbps mono par défaut (≈ 29 Mo/h), sélecteur 64 / 128 / 192 |
| Fichiers conservés indéfiniment | `MAX_FILES` (6 par défaut) : les plus anciens sont supprimés, l'interface prévient |
| Aucune authentification | `APP_PASSWORD` optionnel, cookie de session |
| État perdu au redémarrage | État persisté dans `state.json` à côté des MP3 |
| Image lourde (Node, npm inutiles), `COPY static/` cassé | Image slim : Python 3.12 + ffmpeg uniquement, multi-arch arm64/amd64 |
| Interface violette générique | Interface « girly » : rose poudré, lilas, crème, FR/EN |

## 2. Hors périmètre v1

- Comptes utilisateurs individuels (une seule « famille » d'utilisatrices partage le mot de passe).
- Découpage en chapitres ou en tranches ; un seul MP3 par vidéo. Les chapitres YouTube sont
  écrits en métadonnées ID3 quand ffmpeg le permet.
- Autres sites que YouTube (l'URL doit pointer vers `youtube.com`, `youtu.be`, `music.youtube.com`).
- Notifications push ou e-mail. « Prévenir » = l'interface l'affiche clairement.
- Conversions en parallèle. Un job à la fois, c'est voulu pour le Pi.

## 3. Architecture

Un seul conteneur, un seul processus serveur, un seul volume.

```
navigateur ──HTTP──▶ Flask (gunicorn 1 worker, threads)
                       │
                       ├── routes web  : /  /login  /logout
                       ├── API JSON    : /api/state  /api/jobs  /api/jobs/<id>  /api/files/<name>
                       │
                       ├── JobQueue (thread worker unique)
                       │     └── Converter : yt-dlp -o - | ffmpeg -i pipe:0 … out.mp3
                       │
                       ├── Retention   : prune() après chaque job terminé
                       └── State       : /data/state.json  (jobs + fichiers)

volume /data ── *.mp3 + state.json
```

**Pourquoi un seul worker gunicorn** : la file et l'état vivent en mémoire du processus ;
plusieurs workers verraient chacun leur propre file. `--workers 1 --threads 8` suffit
largement pour quelques utilisatrices.

## 4. Modules (Python, package `bookmallow/`)

| Module | Rôle | Dépend de |
|---|---|---|
| `config.py` | Lit les variables d'environnement, valeurs par défaut, validation | — |
| `urls.py` | Valide/normalise une URL YouTube, détecte une playlist, extrait l'id vidéo | — |
| `metadata.py` | `yt-dlp -J` → titre, durée, miniature, chaîne, chapitres, liste des vidéos d'une playlist | `urls` |
| `converter.py` | Lance le pipeline yt-dlp → ffmpeg, parse la progression ffmpeg, permet l'annulation | `config` |
| `jobs.py` | Modèle `Job` (dataclass), états, sérialisation | — |
| `jobqueue.py` | `JobQueue` : file FIFO, worker unique, transitions d'état, callbacks | `jobs`, `converter`, `metadata`, `retention`, `state` |
| `retention.py` | `prune(directory, max_files)` renvoie les fichiers supprimés ; `next_to_go()` | — |
| `state.py` | Charge/sauvegarde `state.json` de façon atomique (écriture tmp + rename) | `jobs` |
| `names.py` | Nom de fichier sûr à partir d'un titre (`Title [videoId].mp3`), troncature, dédoublonnage | — |
| `auth.py` | Décorateur `login_required`, comparaison en temps constant, cookie de session | `config` |
| `app.py` | Crée l'app Flask, routes, injection des dépendances | tout |
| `templates/index.html`, `templates/login.html`, `static/` | Interface (HTML + CSS + JS vanilla, aucune dépendance CDN) | — |

Chaque module est testable seul ; `converter` et `metadata` sont les seuls à lancer des
processus externes et exposent un point d'injection (`runner`) pour les tests.

## 5. Modèle de données

### Job

```
id            str   uuid4 court (8 hex)
url           str   URL normalisée https://www.youtube.com/watch?v=<id>
video_id      str
title         str | None      renseigné après metadata
duration      int | None      secondes
thumbnail     str | None      URL de la miniature YouTube (non stockée localement)
channel       str | None
quality       "64" | "128" | "192"
status        queued | fetching | converting | done | failed | cancelled
progress      float 0..100    (converting uniquement, calculée depuis ffmpeg out_time / duration)
error         str | None      message court lisible
filename      str | None      nom du MP3 final dans /data
size_bytes    int | None
created_at    ISO 8601 UTC
started_at    ISO 8601 UTC | None
finished_at   ISO 8601 UTC | None
```

### state.json

```json
{ "version": 1, "jobs": [ Job, ... ] }
```

Les fichiers ne sont pas dupliqués dans l'état : la liste des MP3 est relue depuis le disque
à chaque `/api/state` et croisée avec les jobs `done` pour retrouver titre et miniature. Un
MP3 déposé à la main dans le volume apparaît donc aussi (sans miniature).

On garde au maximum 50 jobs dans l'état (les plus anciens terminés/échoués sortent).

## 6. Flux principaux

### 6.1 Soumission d'une URL

1. `POST /api/jobs {url, quality}`.
2. `urls.normalize()` : refuse tout ce qui n'est pas YouTube (400 avec message clair).
3. Si l'URL est une playlist et que la requête ne contient pas `expand_playlist: true` :
   `metadata.playlist_entries()` (extract_flat) → réponse `{playlist: {title, count, entries[:MAX_FILES]}}`,
   l'interface demande confirmation. Le nombre de vidéos mises en file est plafonné à `MAX_FILES`
   et l'interface le dit (« seules les 6 dernières converties seront conservées »).
4. Sinon : création du/des `Job(status=queued)`, ajout à la file, sauvegarde de l'état,
   réponse `201 {jobs: [...]}`.
5. Refus `409` si un job `queued`/`fetching`/`converting` existe déjà pour le même `video_id`.

### 6.2 Worker

```
loop:
  job = queue.get()                          # bloquant
  job.status = fetching   ; save
  meta = metadata.fetch(job.url)             # yt-dlp -J, timeout 60 s
  job.title, duration, thumbnail, channel = meta ; save
  guard_disk(duration, quality)              # cf. 6.4 ; failed si insuffisant
  job.status = converting ; save
  converter.run(job, on_progress)            # cf. 6.3
  job.status = done ; filename ; size ; save
  deleted = retention.prune(DATA_DIR, MAX_FILES)
  log deleted ; save
```

Toute exception → `status=failed`, `error` court (« Vidéo privée », « Réservée aux adultes »,
« Géobloquée », « yt-dlp : <dernière ligne stderr> »), fichier partiel supprimé.

### 6.3 Conversion en streaming

```
yt-dlp  --no-playlist -f "bestaudio[acodec=opus]/bestaudio/best" --no-part -o - <url>
   │ stdout
   ▼
ffmpeg  -nostdin -hide_banner -loglevel error
        -i pipe:0 -vn
        -ac 1 -b:a 64k               (ou -ac 2 -b:a 128k / 192k)
        -codec:a libmp3lame
        -metadata title=… -metadata artist=<channel> -metadata comment=<url>
        -id3v2_version 3
        -progress pipe:1 -nostats
        -f mp3 /data/<name>.part.mp3
```

- Le fichier est écrit sous `<name>.part.mp3` puis renommé en `<name>.mp3` à la fin ; la
  rétention ignore les `.part.mp3` et le démarrage les supprime.
- La progression est lue sur stdout de ffmpeg : lignes `out_time_us=<µs>` → `progress = out_time / duration * 100`,
  bornée à 99,9 jusqu'au code de retour 0.
- Les deux processus sont dans un même groupe de processus (`start_new_session=True`) pour que
  l'annulation les tue ensemble (`SIGTERM` puis `SIGKILL` après 5 s).
- Le stderr de yt-dlp est lu dans un thread pour éviter tout blocage de tube ; les 20 dernières
  lignes sont conservées pour le message d'erreur.
- Code de retour non nul de l'un ou l'autre → échec.

### 6.4 Garde-fou disque

Taille estimée = `duration_s × bitrate_kbps × 1000 / 8 × 1.1`. Si `shutil.disk_usage(DATA_DIR).free`
moins la taille estimée est inférieur à `MIN_FREE_MB` (défaut 500 Mo), le job échoue avec
« Pas assez d'espace disque » avant de télécharger quoi que ce soit.

### 6.5 Rétention

- Après chaque job `done` : trier les `*.mp3` de `/data` par mtime, supprimer tout au-delà de
  `MAX_FILES`. Les jobs `done` dont le fichier n'existe plus reçoivent `filename=None` et un
  indicateur `expired=true` dans la réponse API, pour que la carte affiche « fichier supprimé
  pour faire de la place ».
- `/api/state` renvoie `retention: {max_files, count, next_to_go: <filename|null>}`.
- Interface : bandeau permanent « Bookmallow garde les 6 derniers fichiers. Télécharge le tien
  vite ! » ; badge « prochain à disparaître » sur le plus ancien ; carte grisée « supprimé » pour
  les jobs expirés.

### 6.6 Téléchargement

`GET /api/files/<name>` : `name` doit correspondre exactement à un fichier de `/data` (comparaison
sur `os.listdir`, jamais de jointure de chemin fournie par le client), `send_file(as_attachment=True)`
avec `Content-Length` et support des requêtes `Range` (téléchargement reprenable, utile sur 300 Mo).

`DELETE /api/files/<name>` : suppression manuelle depuis la page (bouton corbeille).

### 6.7 Annulation

`DELETE /api/jobs/<id>` : `queued` → `cancelled` immédiatement ; `fetching`/`converting` →
signal au converter, le worker constate et pose `cancelled`, supprime le `.part.mp3`.

### 6.8 Démarrage

1. Charger `state.json` (absent ou corrompu → état vide, avertissement dans les logs).
2. Jobs `fetching`/`converting` → `failed` « interrompu par un redémarrage ».
3. Jobs `queued` → remis dans la file dans l'ordre de `created_at`.
4. Supprimer les `*.part.mp3`.
5. `retention.prune()`.

## 7. API

| Méthode | Route | Auth | Réponse |
|---|---|---|---|
| GET | `/` | oui | page principale |
| GET/POST | `/login` | non | formulaire ; POST pose le cookie ou 401 |
| POST | `/logout` | oui | 302 vers /login |
| GET | `/api/state` | oui | `{jobs, files, retention, config:{max_files, qualities, default_quality, lang}}` |
| POST | `/api/jobs` | oui | 201 `{jobs}` / 200 `{playlist}` / 400 / 409 |
| DELETE | `/api/jobs/<id>` | oui | 204 / 404 |
| GET | `/api/files/<name>` | oui | fichier |
| DELETE | `/api/files/<name>` | oui | 204 / 404 |
| GET | `/healthz` | non | `{"ok": true}` (healthcheck Docker) |

L'interface interroge `/api/state` toutes les 2 s quand un job est actif, toutes les 10 s sinon.
Pas de WebSocket : plus simple derrière Nginx Proxy Manager et Cloudflare.

## 8. Authentification

- `APP_PASSWORD` vide (défaut) → toutes les routes ouvertes, aucun formulaire.
- Défini → `/login` compare avec `hmac.compare_digest`, pose `session["ok"]=True` (cookie signé
  par Flask, `SECRET_KEY` lu de `SECRET_KEY` ou généré et persisté dans `/data/.secret`).
- Cookie `HttpOnly`, `SameSite=Lax`, `Secure` si `FORCE_HTTPS=1`.
- Pas de limitation de tentatives en v1 (Cloudflare Access ou NPM peuvent l'ajouter) ; documenté.

## 9. Configuration (variables d'environnement)

| Variable | Défaut | Rôle |
|---|---|---|
| `DATA_DIR` | `/data` | volume des MP3 et de `state.json` |
| `MAX_FILES` | `6` | nombre de MP3 conservés |
| `DEFAULT_QUALITY` | `64` | `64`, `128` ou `192` |
| `APP_PASSWORD` | vide | mot de passe partagé, vide = désactivé |
| `SECRET_KEY` | généré | clé de signature des sessions |
| `MIN_FREE_MB` | `500` | marge d'espace disque à garder |
| `MAX_DURATION_HOURS` | `0` | `0` = aucune limite (un livre de 17 h passe) ; une valeur > 0 refuse les vidéos plus longues, utile pour un hébergement public |
| `DEFAULT_LANG` | `fr` | `fr` ou `en`, l'utilisatrice peut basculer (stocké en localStorage) |
| `TZ` | `UTC` | affichage des dates dans les logs |
| `PUID` / `PGID` | `1000` | propriétaire des fichiers écrits dans le volume (entrypoint) |

## 10. Interface

Une page, mobile d'abord, sans framework ni CDN (fonctionne hors ligne sur le LAN).

- **En-tête** : logo Bookmallow (un marshmallow rose avec un casque, SVG inline), sous-titre
  « Tes vidéos YouTube en audiobooks », bascule FR/EN, bouton déconnexion si mot de passe.
- **Carte de saisie** : champ URL large, sélecteur de qualité (trois pastilles : « Voix 64k »,
  « Équilibré 128k », « Musique 192k »), bouton « Transformer ✨ ». Collage automatique lance la
  détection playlist.
- **Bandeau rétention** : pastel lilas, toujours visible, texte adapté à `MAX_FILES`.
- **File d'attente** : cartes avec miniature, titre, durée, chaîne, état (pastille colorée), barre
  de progression arrondie animée, bouton annuler. Un job `failed` montre l'erreur en clair.
- **Bibliothèque** : cartes des MP3 disponibles, taille, date, bouton « Télécharger 💾 », corbeille,
  badge « prochain à disparaître » sur le plus ancien.
- **Modale playlist** : titre, nombre de vidéos, liste cochable plafonnée, rappel de la rétention.
- **Palette** : fond crème `#FFF7F9`, rose poudré `#F8C8D8`, rose vif `#E75A8C` (accent), lilas
  `#C9B6F2`, menthe `#BDEBD5` (succès), corail `#F49A8B` (erreur), texte prune `#4A2A3C`.
  Typo système arrondie (`ui-rounded`, `Nunito` si présente localement, sinon sans-serif).
- **Accessibilité** : contraste AA sur les textes, focus visibles, `aria-live` sur la file.

## 11. Gestion des erreurs

| Situation | Comportement |
|---|---|
| URL non YouTube | 400, message « Bookmallow n'accepte que les liens YouTube » |
| Vidéo privée / supprimée / âge / géo | job `failed`, message traduit à partir du stderr yt-dlp |
| Durée > `MAX_DURATION_HOURS` (si > 0) | job `failed` avant conversion |
| Disque insuffisant | job `failed` avant conversion |
| ffmpeg ou yt-dlp code ≠ 0 | job `failed`, `.part.mp3` supprimé, 20 dernières lignes stderr dans les logs |
| Redémarrage pendant une conversion | job `failed` « interrompu », `.part.mp3` supprimé |
| `state.json` corrompu | état vide, sauvegarde du fichier corrompu en `.bad` |
| yt-dlp obsolète (YouTube change) | documenté : `docker compose pull` ; l'image est reconstruite chaque semaine par CI |

## 12. Tests

`pytest` dans `tests/`, exécuté dans le conteneur de build (`docker build --target test`) et
en CI.

- `test_urls.py` : normalisation, refus des hôtes non YouTube, détection playlist, extraction d'id.
- `test_names.py` : caractères interdits, troncature, dédoublonnage `(2)`.
- `test_retention.py` : garde N fichiers par mtime, ignore `.part.mp3`, `next_to_go`.
- `test_state.py` : écriture atomique, rechargement, fichier corrompu.
- `test_converter.py` : construction des commandes selon la qualité, parseur `out_time_us`,
  annulation, échec sur code de retour (processus simulés par un `runner` injecté).
- `test_jobqueue.py` : ordre FIFO, un seul job actif, transitions d'état, 409 sur doublon, reprise
  au démarrage.
- `test_app.py` : routes avec le client de test Flask, auth activée/désactivée, téléchargement
  sécurisé (nom inexistant → 404, traversée impossible).
- Manuel avant release : une vidéo de 2 minutes puis une de plusieurs heures sur le Pi,
  vérification de la taille du MP3 et de l'espace disque pendant la conversion.

## 13. Packaging et publication

- `Dockerfile` multi-étapes : `base` (python:3.12-slim + ffmpeg), `test` (pytest), `runtime`
  (gunicorn). `yt-dlp` épinglé dans `requirements.txt` et mis à jour par Dependabot.
- `entrypoint.sh` : `chown` du volume vers `PUID:PGID`, puis `gosu`.
- `docker-compose.yml` d'exemple : image `ghcr.io/clemdepernet/bookmallow:latest`, port `7843`,
  volume `./data:/data`, variables commentées.
- GitHub Actions : `ci.yml` (tests sur push/PR), `release.yml` (build multi-arch et push ghcr.io
  sur tag `v*` et hebdomadaire pour rafraîchir yt-dlp).
- `README.md` bilingue (FR puis EN), capture d'écran, « pourquoi », démarrage en 3 commandes,
  tableau des variables, section « exposer à ses amies » (NPM, Cloudflare), remerciements.
- `LICENSE` MIT conservée avec ajout de la ligne de copyright de Clem.
- `CHANGELOG.md`, `CONTRIBUTING.md` allégé.
- Modèle de post pour r/selfhosted dans `docs/reddit-post.md`.

## 14. Déploiement chez Clem

Dossier `~/bookmallow-stack/` séparé de `~/media-stack` (projet Compose indépendant, ajouté à
`stacks.sh`), port hôte `7843` (libre), `TZ=Asia/Kuala_Lumpur`, `PUID/PGID=1000`, volume
`./data`. Exposition éventuelle via Nginx Proxy Manager déjà en place.
