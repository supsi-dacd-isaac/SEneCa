"""Compile versioned gettext catalogs: python scripts/compile_translations.py."""
from pathlib import Path
from babel.messages.pofile import read_po
from babel.messages.mofile import write_mo

ROOT = Path(__file__).resolve().parents[1]


def main():
    for source in sorted((ROOT / 'locales').glob('*/LC_MESSAGES/*.po')):
        with source.open('rb') as stream:
            catalog = read_po(stream)
        # tr() uses str.format only. Babel mistakes literal percent units
        # such as "% del costo" for old-style Python formatting.
        for message in catalog:
            message.flags.discard("python-format")
        errors = list(catalog.check())
        if errors:
            raise ValueError(f'Invalid translation catalog {source}: {errors}')
        with source.with_suffix('.mo').open('wb') as stream:
            write_mo(stream, catalog)
        print(source.relative_to(ROOT))


if __name__ == '__main__':
    main()
