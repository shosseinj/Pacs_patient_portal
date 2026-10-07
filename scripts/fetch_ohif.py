"""Fetch the pinned OHIF assets for local development without Docker."""

import hashlib
import shutil
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

import httpx

ROOT = Path(__file__).resolve().parent.parent / 'data/runtime'
REPO = 'ohif/app'
DIGEST = 'sha256:dee5c696c712082fdd4321b6f5ad94846dc97df5d970548ca0e1d5289667b047'
CACHE = ROOT / 'image-layers'
DEST = ROOT / 'ohif'
CACHE.mkdir(exist_ok=True)
DEST.mkdir(exist_ok=True)
with httpx.Client(timeout=60, follow_redirects=True) as client:
    response = client.get('https://auth.docker.io/token', params={'service': 'registry.docker.io', 'scope': f'repository:{REPO}:pull'})
    response.raise_for_status()
    headers = {
        'Authorization': 'Bearer ' + response.json()['token'],
        'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json',
    }
    response = client.get(f'https://registry-1.docker.io/v2/{REPO}/manifests/{DIGEST}', headers=headers)
    response.raise_for_status()
    manifest = response.json()
    if 'manifests' in manifest:
        digest = next(entry['digest'] for entry in manifest['manifests'] if entry.get('platform', {}).get('architecture') == 'amd64' and entry['platform']['os'] == 'linux')
        response = client.get(f'https://registry-1.docker.io/v2/{REPO}/manifests/{digest}', headers=headers)
        response.raise_for_status()
        manifest = response.json()

    def download(layer):
        digest = layer['digest'].split(':', 1)[1]
        path = CACHE / (digest + '.tar.gz')
        if path.exists():
            with path.open('rb') as cached:
                if hashlib.file_digest(cached, 'sha256').hexdigest() == digest:
                    return path
        temporary = path.with_suffix('.part')
        checksum = hashlib.sha256()
        with client.stream('GET', f'https://registry-1.docker.io/v2/{REPO}/blobs/{layer["digest"]}', headers={'Authorization': headers['Authorization']}) as response:
            response.raise_for_status()
            with temporary.open('wb') as out:
                for chunk in response.iter_bytes(1024 * 1024):
                    out.write(chunk)
                    checksum.update(chunk)
        if checksum.hexdigest() != digest:
            temporary.unlink()
            raise ValueError('Image layer checksum mismatch')
        temporary.rename(path)
        print(f'Downloaded verified layer ({layer["size"] / 1024 / 1024:.1f} MB)', flush=True)
        return path

    with ThreadPoolExecutor(max_workers=3) as pool:
        paths = list(pool.map(download, manifest['layers']))

prefix = PurePosixPath('usr/share/nginx/html')
count = 0
for path in paths:
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or not name.is_relative_to(prefix):
                continue
            relative = name.relative_to(prefix)
            target = DEST / str(relative)
            if relative.name.startswith('.wh.'):
                deleted = target.with_name(relative.name[4:])
                if deleted.is_dir():
                    shutil.rmtree(deleted)
                elif deleted.exists():
                    deleted.unlink()
            elif member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open('wb') as out:
                    shutil.copyfileobj(source, out, 1024 * 1024)
                count += 1
(DEST / '.ready').write_text(DIGEST + '\n')
print(f'Extracted {count} OHIF asset files into {DEST}', flush=True)
