"""Convert Leipzig's bibliographic benchmark ZIP to one UTF-8 application input.

Usage: py -3.13 prepare_bibliographic_dataset.py path/to/DBLP-Scholar.zip
Keeps the original ZIP unchanged. Requires only the Python standard library.
"""
import csv
import io
import json
from pathlib import Path
import sys
import zipfile


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: py -3.13 prepare_bibliographic_dataset.py "path/to/DBLP-Scholar.zip"')
    archive = Path(sys.argv[1]).resolve(strict=True)
    output = archive.with_name(archive.stem + '_prepared')
    sources = []
    mappings = []
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.namelist():
            if not member.lower().endswith('.csv') or member.startswith('__MACOSX/'):
                continue
            raw = bundle.read(member)
            try:
                decoded = raw.decode('utf-8-sig')
                encoding = 'utf-8-sig'
            except UnicodeDecodeError:
                decoded = raw.decode('cp1252')
                encoding = 'cp1252'
            reader = csv.DictReader(io.StringIO(decoded, newline=''))
            fields = {field.strip().lower(): field for field in reader.fieldnames or []}
            if 'title' not in fields:
                mappings.append({'file': member, 'rows': sum(1 for _ in reader)})
                continue
            records = []
            source = Path(member).stem
            for number, row in enumerate(reader, 1):
                if None in row:
                    raise ValueError(f'Malformed CSV row in {member}: {number}')
                original_id = row.get(fields.get('id'), '') or str(number)
                record = dict(row)
                record.update(source=source, original_id=original_id,
                              record_key=f'{source}:{original_id}')
                records.append(record)
            sources.append((member, encoding, records))
    if len(sources) != 2:
        raise ValueError(f'Expected two title-bearing source CSVs; found {len(sources)}')
    output.mkdir(exist_ok=False)
    columns = list(dict.fromkeys(key for _, _, rows in sources for row in rows for key in row))
    with (output / 'bibliographic_records.csv').open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for _, _, records in sources:
            writer.writerows(records)
    manifest = {'archive': str(archive), 'sources': [
        {'file': name, 'decoded_as': encoding, 'records': len(rows)}
        for name, encoding, rows in sources], 'total_records': sum(len(rows) for _, _, rows in sources),
        'reference_mappings_in_original_zip': mappings,
        'note': 'Reference mappings are withheld from app input. Preserve source and original_id when assessing cross-source matches. This converter does not evaluate matching accuracy.'}
    (output / 'preparation.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))
    print('Open in Twin Finder:', output / 'bibliographic_records.csv')


if __name__ == '__main__':
    main()
