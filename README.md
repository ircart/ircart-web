# IRCart

IRCart is the central hub for IRC formatted ASCII & ANSI art. It serves the [ircart](https://git.supernets.org/ircart/ircart) repository as a browsable, rateable gallery at [ircart.supernets.org](https://ircart.supernets.org), where every piece can be copied straight back into IRC, a terminal or a web page.

## Features
- Gallery of every art file with search, a directory filter, sorting *(name, newest, top rated, size)* & infinite scroll
- Accurate previews rendered from the mIRC color codes *(all 99 colors, bold, italic, underline, reverse)*
- Copy any piece as IRC *(original file)*, ANSI truecolor, ANSI 256 or a self-contained HTML snippet
- Accounts with just a username & password
- Comments, 1-5 star ratings & reports for broken art, wrong directories, wrong names or wrong authors
- Uploads saved into the repository under `uploads/<account>/<name>.txt` *(10,000 lines & 3 MB max)*
- Author tags with author pages that link to a matching account
- Profiles with a profile picture, uploads, credited art & comments
- Self-hosted image captcha plus a browser proof-of-work on register, login, comments, reports & uploads
- Admin tools: reports, same-name files, near duplicates *(95% or more alike)*, move/rename/delete with name clash protection & a git pull button
- Search engine friendly: per page titles & descriptions, server rendered content, structured data, `robots.txt` & `sitemap.xml`
- Mobile friendly & installable as an app

## Setup
IRCart runs in docker. On the server, clone this repository & run the setup script as the user that owns the directory:

```shell
./setup.sh
```

It clones the art repository into `art/`, creates `.env` with a random admin password *(printed once)* & builds/starts the container on `127.0.0.1:9009`. Run it again after updating the code to rebuild.

nginx terminates TLS & reverse proxies the domain to `127.0.0.1:9009`. Allow uploads up to 4 MB with `client_max_body_size 4m;`.

The container runs as uid 1001, so `art/` & `data/` must be owned by that user.

## Configuration
Settings live in `.env` *(see `.env.example`)*:

| Setting          | Description                                                                       |
| ---------------- | --------------------------------------------------------------------------------- |
| `ADMIN_USER`     | Admin account name, created or updated on every start                             |
| `ADMIN_PASS`     | Admin account password                                                            |
| `SECRET_KEY`     | Signs login sessions *(64 random hex characters)*                                 |
| `SITE_URL`       | Public address used in canonical links, the sitemap & social previews             |
| `SECURE_COOKIES` | `1` when served over https                                                        |
| `REPO`           | Checkout of ircart/ircart *(outside of docker only, the art is in `REPO/ircart`)* |
| `DATA`           | Database, avatars & index cache directory *(outside of docker only)*              |
| `PORT`           | Port for `python3 app.py` *(outside of docker only)*                              |

## Running locally
```shell
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill it in & uncomment REPO
venv/bin/gunicorn -w 1 --threads 8 -b 0.0.0.0:20008 app:app
```

Use a single gunicorn worker. The art index & background scans live in memory, threads handle concurrency.

## Pulling new art
Art is pulled from git with the *Pull latest art from git* button on the admin page. The pull is refused while the art checkout has uncommitted changes *(uploads or admin moves)*, those need to be committed & pushed from the server first.

## Files
| File                   | Description                                                       |
| ---------------------- | ----------------------------------------------------------------- |
| `app.py`               | Flask app: pages, API, accounts, uploads, admin & SEO             |
| `art.py`               | IRC color parsing, HTML/ANSI rendering, indexing & duplicate scan |
| `captcha.py`           | Image captcha & proof-of-work                                     |
| `db.py`                | SQLite schema & helpers                                           |
| `templates/index.html` | Page shell                                                        |
| `static/utils.js`      | Front end                                                         |
| `static/style.css`     | Styles *(`palette.css` holds the 99 IRC colors)*                  |
| `fonts/`               | Captcha fonts                                                     |
| `setup.sh`             | Clone, configure & start the container                            |
