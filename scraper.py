
from bs4 import BeautifulSoup
import aiohttp
import asyncio
from pathlib import Path
import os
from tqdm import tqdm
from urllib.parse import urljoin 

BASE_URL = "https://books.toscrape.com/"

async def fetch_html(session, url):
    async with session.get(url) as response:
        if response.ok:
            return await response.text()
        else:
            raise Exception(f"Error fetching {url}: {response.status}")

async def extract_book_data(session, book_url):
    html = await fetch_html(session, book_url)
    soup = BeautifulSoup(html, "html.parser")

    title = soup.find("h1").text
    price = soup.find(class_="price_color").text
    image_url = urljoin(book_url, soup.find("img")["src"]) 

    css_links = [urljoin(book_url, link["href"]) for link in soup.find_all("link", rel="stylesheet")]
    js_links = [urljoin(book_url, script["src"]) for script in soup.find_all("script") if script.has_attr('src')]

    return {
        "title": title,
        "price": price,
        "image_url": image_url,
        "css_urls": css_links,
        "js_urls": js_links,
    }

async def download_resource(session, url, folder):
    filename = url.split("/")[-1]
    save_path = folder / filename
    async with session.get(url) as response:
        if response.ok:
            with save_path.open("wb") as f:
                f.write(await response.content.read())
        else:
            raise Exception(f"Error downloading {url}: {response.status}")

async def process_category(session, category_url):
    output_folder = Path("books_data") / category_url.split("/")[-2]
    output_folder.mkdir(parents=True, exist_ok=True)

    css_folder = output_folder / "css"
    js_folder = output_folder / "js"
    images_folder = output_folder / "images"
    css_folder.mkdir(exist_ok=True)
    js_folder.mkdir(exist_ok=True)
    images_folder.mkdir(exist_ok=True)

    while category_url:
        html = await fetch_html(session, category_url)
        soup = BeautifulSoup(html, "html.parser")
        
        # Save HTML file
        with open(os.path.join(output_folder, "index.html"), "w") as f:
            f.write(html)

        for book_element in tqdm(soup.select("article.product_pod h3 a"), desc="Books"):
            relative_book_url = book_element["href"]
            absolute_book_url = urljoin(category_url, relative_book_url)
            book_data = await extract_book_data(session, absolute_book_url) 

            await download_resource(session, book_data["image_url"], images_folder)
            await asyncio.gather(
                *[download_resource(session, url, css_folder) for url in book_data["css_urls"]],
                *[download_resource(session, url, js_folder) for url in book_data["js_urls"]]
            )

        # Find next page
        next_page_link = soup.select_one("li.next a") 
        if next_page_link and 'href' in next_page_link.attrs:  # Check for 'href' existence
            category_url = BASE_URL + "catalogue/" + next_page_link["href"] 
        else:
            category_url = None 

async def scrape_and_download():
    async with aiohttp.ClientSession() as session:
        html = await fetch_html(session, BASE_URL)
        soup = BeautifulSoup(html, "html.parser")

        categories = [BASE_URL + link["href"] for link in soup.select(".nav-list ul a")]
        await asyncio.gather(*[process_category(session, category_url) for category_url in categories])


if __name__ == "__main__":
    asyncio.run(scrape_and_download()) 
