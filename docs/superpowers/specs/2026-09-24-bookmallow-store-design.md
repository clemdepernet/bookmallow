# Bookmallow — Magasin de livres audio (v1.1) — design

Date : 2026-09-24
Statut : validé avec Clem (sources libres + Prowlarr, onglet dans Bookmallow, livraison en M4B, rétention partagée, code dans le dépôt public avec volet torrent optionnel).
Prérequis : Bookmallow v1.0.0 (spec `2026-09-23-bookmallow-design.md`).

## 1. But

Ajouter à Bookmallow un onglet « Magasin » : chercher un livre audio en français ou en anglais, l'acquérir, l'assembler en **un seul fichier M4B** (chapitres, couverture), le déposer dans la bibliothèque existante où il suit la même rétention (`MAX_FILES`), et le télécharger sur le téléphone depuis la page.

Deux familles de sources :
- **Libres** : LibriVox (catalogue principal, API JSON) et Internet Archive (complément). Téléchargement HTTP direct, sans fichier intermédiaire.
- **Torrent, via la stack existante de Clem** : Prowlarr (recherche, catégorie Audiobooks) et qBittorrent (téléchargement). Activé seulement si les variables d'environnement correspondantes sont renseignées.

## 2. Hors périmètre

- Bibliothèque persistante ou catalogue personnel : les livres suivent la rétention à `MAX_FILES` comme les MP3 YouTube.
- Lecture en ligne (streaming) dans la page.
- Autres clients torrent que qBittorrent, autres agrégateurs que Prowlarr.
- Sources payantes ou nécessitant un compte (Audible, Kobo…).
- Téléchargement de plusieurs livres en parallèle : un job à la fois, file commune.

## 3. Architecture

```
Onglet Magasin ──GET /api/store/search──▶ store/search.py ──▶ providers/librivox.py  (HTTPS)
                                                         ├──▶ providers/archive.py   (HTTPS)
                                                         └──▶ providers/prowlarr.py  (HTTP, X-Api-Key)   [si configuré]
                ──POST /api/store/jobs───▶ JobQueue (job.kind = "book")
                                              │
                                              ├── kind=book, source=librivox|archive ──▶ store/assemble.py
                                              │        ffmpeg -f concat (URLs) → AAC 64k → Titre.part.m4b → .m4b
                                              │
                                              └── kind=book, source=prowlarr ──▶ store/torrent.py
                                                       qBittorrent add → poll → fichiers finis (/incoming) → assemble.py → delete torrent+files
                                              │
                                              └── retention.prune (mp3 + m4b), state.json
```

La file, l'état, la rétention, l'authentification et la bibliothèque sont ceux de la v1, étendus : `retention.list_audio` remplace `list_mp3` (extensions `.mp3`, `.m4b`), `Job` gagne des champs.

## 4. Modules

| Module | Rôle | Dépend de |
|---|---|---|
| `store/__init__.py` | expose `providers_available(config)` | `config` |
| `store/models.py` | `SearchResult`, `BookPlan` (liste de pistes + chapitres + couverture), `Track` | — |
| `store/http.py` | `get_json(url, params, headers, timeout)` injectable (urllib), gestion erreurs → `StoreError` | — |
| `store/providers/librivox.py` | `search(q, lang, limit)` → `SearchResult[]` ; `plan(book_id)` → `BookPlan` (sections, `listen_url`, `playtime`, couverture) | `http` |
| `store/providers/archive.py` | `search(q, lang, limit)` via `advancedsearch.php` sur `collection:(librivoxaudio OR audio_bookspoetry)` ; `plan(identifier)` via `/metadata/<id>` (fichiers `.mp3` triés par `track`/nom, `length`, image de couverture) | `http` |
| `store/providers/prowlarr.py` | `search(q, limit)` → `SearchResult[]` (`/api/v1/search?query=&categories=3030&type=search`) | `http` |
| `store/qbittorrent.py` | `QbtClient(url, user, password)` : `login()`, `add(magnet_or_url, category, tags) -> hash`, `info(hash) -> TorrentInfo(progress, state, content_path, size)`, `delete(hash, delete_files=True)` | `http` |
| `store/search.py` | `unified_search(q, lang, config, providers) -> list[SearchResult]` : appels parallèles (threads), fusion, dédoublonnage (LibriVox prioritaire sur Archive pour un même identifiant IA), cache TTL 600 s, un appel Prowlarr à la fois (verrou) | providers |
| `store/assemble.py` | `AssembleRequest(tracks, out_path, title, author, chapters, cover_url_or_path, bitrate, copy_if_aac)` ; `concat_list(tracks) -> str` ; `ffmetadata(chapters) -> str` ; `ffmpeg_command(req, list_path, meta_path, cover_path)` ; `Assembly(req, on_progress, popen).run()/cancel()` (réutilise le parseur de progression et `_terminate` de `converter.py`, factorisés dans `procutil.py`) | `converter` |
| `store/torrent.py` | `TorrentAcquisition(client, result, config, on_progress)`: ajoute, attend (poll toutes les 5 s, stall après `TORRENT_STALL_HOURS`), traduit `content_path` via `QBT_PATH_MAP`, liste les pistes audio (`.mp3 .m4a .m4b .aac .ogg .opus .flac`, tri naturel, dossiers récursifs), renvoie un `BookPlan` local ; `cleanup()` supprime torrent + fichiers | `qbittorrent`, `models` |
| `jobqueue.py` (modifié) | `_process` route selon `job.kind` ; `submit_book(result, quality)` ; progression torrent (0–50 %) puis assemblage (50–100 %) | `store.*` |
| `app.py` (modifié) | routes `/api/store/*`, `build_state` expose `store` (fournisseurs actifs), `files` gagne `kind` | `store.search`, `jobqueue` |
| `static/app.js`, `templates/index.html`, `static/style.css` (modifiés) | onglets, recherche, cartes résultats, pastilles livre | — |

## 5. Modèle de données

### Job (champs ajoutés, défauts pour compatibilité avec state.json v1)

```
kind        "youtube" | "book"        défaut "youtube"
source      None | "librivox" | "archive" | "prowlarr"
source_id   None | str               id LibriVox, identifiant IA, ou guid Prowlarr
author      None | str
language    None | str               "fr" | "en" | code ISO 639-1 sinon
torrent_hash None | str
cover       None | str               URL de couverture (affichage)
```
`title`, `duration`, `thumbnail` (= cover), `progress`, `filename`, `error*` sont réutilisés. `state.json` reste en version 1 : les nouveaux champs ont des défauts, `from_dict` ignore l'inconnu.

### SearchResult

```
source      "librivox" | "archive" | "prowlarr"
source_id   str
title       str
author      str | None
language    str | None        code à deux lettres si connu
duration    int | None        secondes
size_bytes  int | None        torrents
seeders     int | None        torrents
cover       str | None        URL
url         str | None        page d'origine (LibriVox, IA, indexeur)
download    str | None        magnet ou URL .torrent (prowlarr uniquement, jamais renvoyé au client : conservé dans le cache côté serveur, référencé par source_id)
```

### BookPlan

```
title, author, language, cover (URL ou chemin local), duration
tracks: [Track(url_or_path, duration: float | None, title: str)]
```

## 6. Flux

### 6.1 Recherche

1. `GET /api/store/search?q=<texte>&lang=fr|en|all` (auth requise). `q` de 2 à 100 caractères, sinon 400.
2. `unified_search` : lance en parallèle LibriVox (`title=^q` puis `author=^q` si moins de 5 résultats, `extended=1`, `limit=25`, filtre `language` = French/English selon `lang`), Internet Archive (`q=(collection:librivoxaudio OR collection:audio_bookspoetry) AND (title:(q) OR creator:(q))` + `language:(fre OR french)` / `(eng OR english)` selon `lang`, `rows=25`) et Prowlarr si configuré (`query=q`, `categories=3030`, `type=search`, `limit=30`).
3. Fusion : LibriVox d'abord, Archive sans les identifiants déjà vus (l'identifiant IA d'un livre LibriVox est dans `url_iarchive`), Prowlarr ensuite trié par `seeders` décroissant. Maximum 60 résultats. Réponse `{results: [...], providers: {librivox: "ok"|"error", archive: ..., prowlarr: "ok"|"error"|"disabled"}}` : un fournisseur en panne n'empêche pas les autres.
4. Cache mémoire `(q, lang)` → résultats, TTL 600 s, 200 entrées max. Les champs `download` (magnet) restent côté serveur.

### 6.2 Soumission

`POST /api/store/jobs {source, source_id, quality?}` → recherche l'entrée dans le cache (ou re-résout : LibriVox `?id=`, Archive `/metadata/`, Prowlarr par nouvelle recherche `q` fourni en option) → `Job(kind="book", ...)` → 201, ou 409 si un job actif a le même `source_id`, 404 si introuvable, 400 si `source` inconnue ou fournisseur désactivé.

### 6.3 Acquisition libre (librivox / archive)

1. `provider.plan(source_id)` → `BookPlan` (pistes = URL `listen_url` LibriVox ou `https://archive.org/download/<id>/<name>` IA, durées connues).
2. Garde-fou disque : taille estimée = `duration × 64 kbps × 1,1` (M4B) — refus `no_space` comme en v1.
3. Assemblage : fichier liste concat (`file 'https://…'` par piste) et fichier ffmetadata (titre, artiste, album, `[CHAPTER]` cumulés depuis les durées ; si une durée manque, pas de chapitres) écrits dans `/data/.work/<job_id>/` ; couverture téléchargée dans le même dossier si présente ; commande :
   ```
   ffmpeg -nostdin -hide_banner -loglevel error
     -protocol_whitelist file,http,https,tcp,tls -f concat -safe 0 -i list.txt
     -i meta.ffm [-i cover.jpg]
     -map 0:a -map_metadata 1 -map_chapters 1 [-map 2:v -c:v copy -disposition:v attached_pic]
     -c:a aac -b:a 64k -ac 1 -movflags +faststart
     -progress pipe:1 -nostats -y -f ipod /data/<Titre> [<Auteur>].part.m4b
   ```
   Progression = `out_time_us / duration`. Fin : renommage en `.m4b`, suppression du dossier de travail. Échec ou annulation : suppression du `.part.m4b` et du dossier de travail (mêmes règles qu'en v1 ; `remove_partials` couvre déjà `*.part.*`, `/data/.work` est nettoyé au démarrage).
4. Job `done`, `retention.prune`.

### 6.4 Acquisition torrent (prowlarr)

1. `QbtClient.login()` ; `add(download, category=QBT_CATEGORY, tags=["bookmallow", job.id])` → hash (lu via `torrents/info?category=…` après ajout, apparié par nom ou par tag). Sans hash après 30 s : échec `torrent_add`.
2. Attente : `info(hash)` toutes les 5 s ; progression job = `progress × 50`. États `error`/`missingFiles` → échec `torrent_error`. Aucun octet reçu pendant `TORRENT_STALL_HOURS` (défaut 12) → échec `torrent_stalled` et `cleanup()`. Annulation → `cleanup()` (supprime torrent et fichiers) puis `cancelled`.
3. Fini : `content_path` traduit avec `QBT_PATH_MAP` (`/downloads:/incoming`). Pistes audio listées récursivement, tri naturel (`01`, `02`… ou `Chapter 1`, `Chapter 10`), durées lues avec `ffprobe -show_entries format=duration` (une par piste, rapide). Aucune piste → échec `no_audio`. Une seule piste déjà `.m4b` → copie directe vers `/data` (pas de réencodage).
4. Assemblage comme en 6.3 mais depuis des chemins locaux ; `copy_if_aac` : si toutes les pistes sont AAC (`ffprobe codec_name=aac`), `-c:a copy`, sinon réencodage 64 kbps mono. Progression 50–100 %.
5. `cleanup()` : `torrents/delete?hashes=<hash>&deleteFiles=true`. Job `done`, `prune`.

### 6.5 Rétention et bibliothèque

- `retention.list_audio(directory)` : `*.mp3` et `*.m4b` hors `.part.*`, tri mtime décroissant ; `prune`, `next_to_go` s'appuient dessus. `MAX_FILES` reste unique et partagé.
- `build_state.files[*]` gagne `kind` (`"book"` si `.m4b` ou job `kind=book`), `author`, `language`.
- Téléchargement : `resolve_file` accepte `.mp3` et `.m4b` ; `send_from_directory` envoie `audio/mp4` pour `.m4b`.

### 6.6 Démarrage

Comme en v1 plus : suppression de `/data/.work/*` ; les jobs `kind=book` interrompus avec `torrent_hash` déclenchent `cleanup()` (best effort, erreurs loguées) pour ne pas laisser de torrent orphelin.

## 7. API

| Méthode | Route | Réponse |
|---|---|---|
| GET | `/api/store/search?q=&lang=` | 200 `{results, providers}` ; 400 `q` invalide ; 503 si aucun fournisseur actif |
| POST | `/api/store/jobs` | 201 `{jobs:[job]}` ; 400 ; 404 ; 409 `{error: duplicate, jobs}` |
| GET | `/api/state` | inchangé + `store: {enabled, providers: {librivox, archive, prowlarr}}`, `files[*].kind/author/language`, `jobs[*].kind/source/author/language/cover` |
| DELETE | `/api/jobs/<id>` | inchangé (annule aussi un torrent en cours) |

## 8. Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `STORE_ENABLED` | `1` | `0` masque l'onglet et désactive les routes `/api/store/*` |
| `STORE_LIBRIVOX` | `1` | fournisseur LibriVox |
| `STORE_ARCHIVE` | `1` | fournisseur Internet Archive |
| `PROWLARR_URL` | vide | ex. `http://prowlarr:9696` ; vide = volet torrent désactivé |
| `PROWLARR_API_KEY` | vide | clé API Prowlarr |
| `QBT_URL` | vide | ex. `http://qbittorrent:8080` |
| `QBT_USER` / `QBT_PASSWORD` | vide | identifiants WebUI |
| `QBT_CATEGORY` | `bookmallow` | catégorie qBittorrent (créée si absente) |
| `QBT_PATH_MAP` | `/downloads:/incoming` | `chemin vu par qBittorrent:chemin vu par Bookmallow` |
| `TORRENT_STALL_HOURS` | `12` | délai sans progression avant échec |
| `BOOK_BITRATE` | `64k` | débit AAC du M4B |
| `STORE_TIMEOUT_S` | `20` | délai des appels aux API de recherche |

Le volet torrent est actif si `PROWLARR_URL`, `PROWLARR_API_KEY`, `QBT_URL` sont renseignés ; une configuration partielle est signalée dans les logs au démarrage et le fournisseur reste `disabled`.

### Déploiement chez Clem (`~/bookmallow-stack`)

- Réseau : la stack rejoint `media-stack_medianet` (réseau externe) pour joindre `prowlarr:9696` et `qbittorrent:8080` par nom.
- Volume : `/mnt/ssd/jellyfin/media/downloads:/incoming:ro`.
- qBittorrent : catégorie `bookmallow` avec chemin de sauvegarde par défaut (les fichiers arrivent sous `/downloads/bookmallow/`).
- `.env` : `PROWLARR_API_KEY`, `QBT_USER`, `QBT_PASSWORD` (jamais commités).

## 9. Interface

- **Onglets** en haut de la carte principale : « ✨ Convertir » (v1) et « 📚 Magasin ». Mémorisés dans `localStorage` (`bookmallow.tab`). Onglet Magasin absent si `store.enabled` est faux.
- **Magasin** : champ de recherche, pastilles « Français / English / Toutes » (défaut selon `DEFAULT_LANG`), bouton « Chercher 🔍 ». Résultats en grille de cartes : couverture (ou icône livre), titre, auteur, durée ou taille, badge « Libre » (LibriVox / Archive) ou « Torrent · N sources », bouton « Ajouter à la file ». Message doux si aucun résultat ; bandeau discret si un fournisseur est en panne.
- **File** : cartes `kind=book` avec icône livre, auteur, source ; libellés d'état supplémentaires « Téléchargement du torrent… » et « Assemblage du M4B… ».
- **Bibliothèque** : pastille « Livre » sur les M4B, auteur affiché, bouton « Télécharger » identique.
- **i18n** : toutes les nouvelles chaînes en FR et EN, parité vérifiée par le test existant.
- **CSP** : `img-src` étendu à `https://archive.org https://*.archive.org https://librivox.org https://*.librivox.org` et aux hôtes d'images renvoyés par Prowlarr sont ignorés (pas d'image pour les torrents).

## 10. Erreurs

| Code | Situation | Message UI (FR) |
|---|---|---|
| `store_disabled` | fournisseur désactivé | « Cette source n'est pas activée sur ce serveur » |
| `not_found` | livre introuvable à la résolution | « Livre introuvable » |
| `provider_error` | API LibriVox/Archive/Prowlarr en erreur | « La source ne répond pas » |
| `no_tracks` / `no_audio` | plan sans pistes / torrent sans audio | « Aucune piste audio trouvée » |
| `torrent_add` | qBittorrent refuse l'ajout | « qBittorrent a refusé le torrent » |
| `torrent_error` | état d'erreur qBittorrent | « Erreur de téléchargement du torrent » |
| `torrent_stalled` | aucune progression pendant `TORRENT_STALL_HOURS` | « Torrent sans source, abandonné » |
| `qbt_auth` | login qBittorrent refusé | « Connexion à qBittorrent refusée » |
| `ffmpeg`, `no_space`, `interrupted`, `internal` | comme en v1 | inchangés |

## 11. Tests

- `test_store_librivox.py`, `test_store_archive.py`, `test_store_prowlarr.py` : parsing des réponses réelles enregistrées (fixtures JSON), filtres de langue, gestion d'erreurs HTTP.
- `test_store_search.py` : fusion, dédoublonnage, cache, fournisseur en panne.
- `test_store_qbittorrent.py` : client contre un faux serveur HTTP en mémoire (login, add, info, delete).
- `test_store_assemble.py` : liste concat, ffmetadata chapitres, commande ffmpeg (copie vs réencodage, couverture), progression, nettoyage du dossier de travail.
- `test_store_torrent.py` : machine à états (attente, stall, erreur, annulation), traduction de chemins, tri naturel des pistes.
- `test_jobqueue.py` : routage `kind=book`, progression 0–50/50–100, recover avec nettoyage torrent.
- `test_app.py` : routes `/api/store/*`, `build_state` étendu, téléchargement `.m4b`.
- `test_retention.py` : `list_audio` avec `.m4b`.
- Manuel : un livre LibriVox FR court, un EN court, un torrent choisi par Clem ; vérification des chapitres dans une app de lecture.

## 12. Livraison

Version `1.1.0`, `CHANGELOG`, README (section « Magasin » FR/EN, variables, exemple compose avec réseau externe et volume `/incoming`), capture d'écran de l'onglet, tag `v1.1.0`, déploiement dans `~/bookmallow-stack`.
