import os, sys
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import pathlib

ROOT_URL = "https://books.toscrape.com/"

    
def save(soup, pagefolder, session, url, tag, inner):
    for res in soup.findAll(tag):
        if res.has_attr(inner):
            try:
                filename = os.path.basename(res[inner])
                fileurl = urljoin(url, res.get(inner))
                filepath = os.path.join(pagefolder, filename)
                print("filename: " + filename + " fileurl " + fileurl + " filepath " + filepath)
                if not os.path.isfile(filepath): # was not downloaded
                    with open(filepath, 'wb') as file:
                        filebin = session.get(fileurl)
                        file.write(filebin.content)
            except Exception as exc:
                print(exc, file=sys.stderr)

def download_page(url, pagepath, visited_pages):
    if url in visited_pages:
        return
    visited_pages.add(url)
    session = requests.Session()
    response = session.get(url)
    soup = BeautifulSoup(response.content, "html.parser")
    path, _ = os.path.splitext(pagepath)
    if not os.path.exists(path):
        pathlib.Path(path).mkdir(parents=True, exist_ok=True)
    with open(path+'.html', 'wb') as file:
        file.write(soup.prettify('utf-8'))
    tags_inner = {'img': 'src', 'link': 'href', 'script': 'src'}
    for tag, inner in tags_inner.items():
        save(soup, path, session, url, tag, inner)
    
    for a_tag in soup.find_all('a', href=True):
        href = urljoin(url, a_tag['href'])
        if (urlparse(href).netloc == urlparse(url).netloc) & (a_tag['href'] != "index.html"):
            download_page( href, "books/"+url.removeprefix(ROOT_URL), visited_pages) 


visited_pages = set()
download_page(ROOT_URL, "", visited_pages)
