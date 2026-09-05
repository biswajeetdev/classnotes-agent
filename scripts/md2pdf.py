#!/usr/bin/env python3
"""Markdown lecture notes -> PDF, via Chrome headless. No third-party deps.

    md2pdf.py <in.md> <out.pdf> [title]

pandoc/wkhtmltopdf are not installed and both are heavy; Chrome is already here and
renders the tables and Devanagari these notes contain correctly.
"""
import html, os, re, subprocess, sys, tempfile

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font: 10.5pt/1.55 -apple-system, "Helvetica Neue", sans-serif; color:#1a1a1a; }
h1 { font-size:19pt; margin:0 0 2mm; color:#111; border-bottom:2px solid #333; padding-bottom:2mm; }
h2 { font-size:13.5pt; margin:7mm 0 2mm; color:#1a3a6b; border-bottom:1px solid #ccd; padding-bottom:1mm; }
h3 { font-size:11.5pt; margin:5mm 0 1.5mm; color:#333; }
h4 { font-size:10.5pt; margin:4mm 0 1mm; }
table { border-collapse:collapse; width:100%; margin:3mm 0; font-size:9.5pt; }
th,td { border:1px solid #bbb; padding:1.6mm 2.4mm; text-align:left; vertical-align:top; }
th { background:#eef1f6; font-weight:600; }
code { background:#f2f2f4; padding:0.4mm 1.2mm; border-radius:2px; font-size:9.5pt; }
blockquote { border-left:3px solid #bbb; margin:3mm 0; padding:0 0 0 4mm; color:#444; }
li { margin:0.8mm 0; }
hr { border:none; border-top:1px solid #ddd; margin:5mm 0; }
a { color:#1a3a6b; text-decoration:none; }
strong { color:#000; }
"""

def inline(t):
    t = html.escape(t)
    t = re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
    t = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', t)
    t = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<em>\1</em>', t)
    t = re.sub(r'~~([^~]+)~~', r'<del>\1</del>', t)
    t = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', t)
    return t

def convert(md):
    out, lines, i = [], md.split("\n"), 0
    listtype = None
    def closelist():
        nonlocal listtype
        if listtype: out.append(f"</{listtype}>"); listtype = None
    while i < len(lines):
        ln = lines[i]
        if re.match(r'^\s*\|.*\|\s*$', ln) and i+1 < len(lines) and re.match(r'^\s*\|[\s:|-]+\|\s*$', lines[i+1]):
            closelist()
            hdr = [c.strip() for c in ln.strip().strip('|').split('|')]
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in hdr) + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and re.match(r'^\s*\|.*\|\s*$', lines[i]):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
            out.append("</tbody></table>"); continue
        m = re.match(r'^(#{1,4})\s+(.*)', ln)
        if m:
            closelist(); lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>"); i += 1; continue
        if re.match(r'^\s*[-*]\s+', ln):
            if listtype != "ul": closelist(); out.append("<ul>"); listtype = "ul"
            out.append(f"<li>{inline(re.sub(r'^\s*[-*]\s+','',ln))}</li>"); i += 1; continue
        if re.match(r'^\s*\d+\.\s+', ln):
            if listtype != "ol": closelist(); out.append("<ol>"); listtype = "ol"
            out.append(f"<li>{inline(re.sub(r'^\s*\d+\.\s+','',ln))}</li>"); i += 1; continue
        if re.match(r'^\s*>\s?', ln):
            closelist(); out.append(f"<blockquote>{inline(re.sub(r'^\s*>\s?','',ln))}</blockquote>"); i += 1; continue
        if re.match(r'^\s*(---+|\*\*\*+)\s*$', ln):
            closelist(); out.append("<hr>"); i += 1; continue
        if ln.strip() == "": closelist(); i += 1; continue
        closelist(); out.append(f"<p>{inline(ln)}</p>"); i += 1
    closelist()
    return "\n".join(out)

def main():
    src, dst = sys.argv[1], sys.argv[2]
    title = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(src)
    body = convert(open(src, encoding="utf-8").read())
    page = f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style>{body}"
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(page); tmp = f.name
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    r = subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={os.path.abspath(dst)}", f"file://{tmp}"],
                       capture_output=True, text=True)
    os.unlink(tmp)
    if not os.path.exists(dst):
        print("FAILED:", r.stderr[-400:], file=sys.stderr); sys.exit(1)
    print(f"  {os.path.getsize(dst)//1024} KB  {dst}")

if __name__ == "__main__":
    main()
