"""Explicitly fetch Apple's published FCPXML 1.7 DTD into a new runtime directory."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen
import argparse
import hashlib

try:
    from .probe_manifest import check_output_directory
except ImportError:
    from probe_manifest import check_output_directory

URL = 'https://developer.apple.com/library/archive/documentation/Miscellaneous/Conceptual/LegacyDTDsFinalCutPro/FCPXMLDTDv1.7/FCPXMLDTDv1.7.html'
DTD_SHA256 = '89b8eddaedc75ee941bd1aef9cb7e237324174c5b2db84e70fdfc45d780204dd'


class PublishedCode(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.parts = []

    def handle_starttag(self, tag, attributes):
        if tag == 'pre':
            self.inside = True

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)


def fetch(output: Path) -> Path:
    output = check_output_directory(output)
    with urlopen(URL, timeout=30) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Published page exceeds size limit')
    parser = PublishedCode()
    parser.feed(raw.decode('utf-8'))
    dtd = (''.join(parser.parts).strip() + '\n').encode('utf-8')
    if hashlib.sha256(dtd).hexdigest() != DTD_SHA256:
        raise ValueError('Published DTD differs from the reviewed FCPXML 1.7 checksum')
    output.mkdir(parents=True, exist_ok=False)
    path = output / 'FCPXMLv1_7.dtd'
    path.write_bytes(dtd)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    print(fetch(parser.parse_args().output_dir))
