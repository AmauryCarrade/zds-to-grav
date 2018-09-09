# zds-to-grav

Converts an article or an opinion from [Zeste de Savoir](https://zestedesavoir.com) to [Grav](https://getgrav.org).

Accepts either an URL to a ZdS article/optinion, or an exported archive.

## Installation

Requires Python 3.6 or newer.

```bash
(sudo) pip install zds_to_grav
```

## Usage

```bash
zds-to-grav --help
```

Typical use: from the directory you want to put the exported grav article directory into:

```bash
zds-to-grav https://zestedesavoir.com/articles/42/le-point-sur-les-exoplanetes/
```

See options in `--help` to specify explicit slug, article type, lang, or destination directory.

## Development & tests

Installation for development (requires `pipenv`: `sudo pip install pipenv`):

```bash
pipenv install
```

Unit tested using `doctest`. From the project directory, within a virtualenv:

```bash
python zds_to_grav.py --test
```

No output means everything is good.
