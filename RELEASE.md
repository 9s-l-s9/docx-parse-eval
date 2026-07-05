# Release

Maintainer notes for publishing `docx-parse-eval`.

## Build And Check

```sh
python3 -m pip install --upgrade build twine
python3 -m build
python3 -m twine check dist/*
```

## Credentials

Twine can read credentials from `~/.pypirc`. With a PyPI API token, use
`__token__` as the username and the token as the password.

An ignored local `.env` also works for one-off shell sessions:

```sh
set -a
. ./.env
set +a
```

`.env.example` documents the expected variable names.

## Upload

Try TestPyPI first:

```sh
python3 -m twine upload --repository testpypi dist/*
```

Then publish to PyPI:

```sh
python3 -m twine upload dist/*
```
