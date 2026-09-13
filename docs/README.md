# Optional reference documentation

The [main README](../README.md) covers installation, labelling, saved data and
reliability. You do not need the documents below to get started.

| Reference | Use it when you need… |
| --- | --- |
| [Annotation guide](ANNOTATION_GUIDE.md) | More detail about controls, body zones and coding conventions. |
| [Data format](DATA_FORMAT.md) | Exact CSV columns, file details, and Python/R reading examples for your own analysis. |
| [Architecture](../ARCHITECTURE.md) | How the code is organised, built and tested. |

## Run from source (developers)

Requires Python 3.12 with Tk support and [uv](https://docs.astral.sh/uv/).
On Debian/Ubuntu, a distribution-provided Python needs its matching Tk package
(for example, `python3.12-tk` where available).

```bash
git clone https://github.com/Humanoids-CTU/tiny-touch.git
cd tiny-touch
uv venv --python 3.12
uv pip install -r requirements.txt
uv run python src/main.py
```

Build with `uv run pyinstaller TinyTouch.spec`; the executable is written to
`dist/`. Run the non-GUI tests with `uv run pytest`, and GUI tests with
`uv run pytest -m gui` when a display is available.
