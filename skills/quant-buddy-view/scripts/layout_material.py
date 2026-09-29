"""Extract inert section shapes; layout borrowing never copies source runtime."""
import html
import re
from html.parser import HTMLParser


class LayoutParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = []
        self.heading = None

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag == self.skip[-1]: self.skip.append(tag)
            return
        if tag in ('script', 'style', 'iframe', 'object', 'svg', 'template'):
            self.skip.append(tag)
            return
        if tag not in ('section', 'h1', 'h2', 'h3', 'h4'):
            return
        values = dict(attrs)
        classes = [x for x in values.get('class', '').split() if re.fullmatch(r'[A-Za-z_][\w-]*', x)]
        attr = ' class="' + html.escape(' '.join(classes), quote=True) + '"' if classes else ''
        self.out.append('<' + tag + attr + '>')
        if tag != 'section': self.heading = tag

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]: self.skip.pop()
            return
        if tag in ('section', 'h1', 'h2', 'h3', 'h4'):
            self.out.append('</' + tag + '>')
            if tag == self.heading: self.heading = None

    def handle_data(self, value):
        if not self.skip and self.heading:
            self.out.append(html.escape(value))


def extract(source):
    parser = LayoutParser()
    parser.feed(source)
    material = ''.join(parser.out)
    # Only presentation CSS; no URLs, variables, bindings or executable content.
    allowed = {'color', 'background-color', 'border', 'border-color', 'border-radius',
        'padding', 'margin', 'gap', 'font-family', 'font-size', 'font-weight', 'line-height',
        'box-shadow', 'display', 'grid-template-columns', 'max-width', 'width', 'min-width'}
    sheets = []
    for sheet in re.findall(r'<style[^>]*>(.*?)</style>', source, re.S | re.I):
        for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', sheet):
            if not re.fullmatch(r'\.[A-Za-z_][\w-]*', selector.strip()): continue
            declarations = []
            for part in body.split(';'):
                key, sep, value = part.partition(':')
                if (sep and key.strip().lower() in allowed
                        and not re.search(r'url\s*\(|expression|@|[<>\\]|signature|Bearer|__QBV_|var\s*\(', value, re.I)):
                    declarations.append(key.strip() + ':' + value.strip())
            if declarations: sheets.append(selector.strip() + '{' + ';'.join(declarations) + '}')
    return material + '<style>' + ''.join(sheets) + '</style>'
