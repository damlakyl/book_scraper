import requests, aiohttp, asyncio, os, pathlib, logging
from bs4 import BeautifulSoup
from pathlib import Path
from tqdm import tqdm
from urllib.parse import urljoin, urlparse


BASE_URL = "https://books.toscrape.com/"
CACHE_DIR = "html_cache"

logging.basicConfig(filename='scraper.log', 
                    level=logging.DEBUG, 
                    format='%(asctime)s - %(levelname)s - %(message)s')  

def parse_url(url): 
    return urlparse(url).path.removeprefix("https://books.toscrape.com").removeprefix("/").removesuffix('/index.html')

async def fetch_html(session, url):
    cache_filename = url.replace("/", "_").replace(":", "") + ".html" 
    cache_filepath = os.path.join(CACHE_DIR, cache_filename)
    if not os.path.exists(CACHE_DIR): # create only once
        pathlib.Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    try:
        # Attempt to load from cache
        with open(cache_filepath, "r") as f:
             return f.read()
    except FileNotFoundError:
        html = await (await session.get(url)).text() 
        # Ensure cache directory exists BEFORE storing 
        os.makedirs(CACHE_DIR, exist_ok=True)  
        with open(cache_filepath, "w") as f:
            f.write(html)
        return html 


async def download_book(session, book_url, pbar):
    html = await fetch_html(session, book_url)
    folder_path = Path("books_data") / parse_url(book_url)
    if not os.path.exists(folder_path): 
        pathlib.Path(folder_path).mkdir(parents=True, exist_ok=True)
    with open(folder_path / "index.html", "w") as f:
        f.write(html)
    await extract_resources_and_download(session, book_url, html)
    pbar.update(1)

async def extract_resources_and_download(session, base_url, html, book=False):
    soup = BeautifulSoup(html, "lxml")
    image_tags = [urljoin(base_url, img["src"]) for img in soup.find_all("img")]
    css_links = [urljoin(base_url, link["href"]) for link in soup.find_all("link", rel="stylesheet")]
    js_links = [urljoin(base_url, script["src"]) for script in soup.find_all("script") if script.has_attr('src')]
    await asyncio.gather(
        *[download_resource(session, img) for img in image_tags],
        *[download_resource(session, css) for css in css_links],
        *[download_resource(session, js) for js in js_links]
    )

async def download_resource(session, url, folder=None):
    filename = urlparse(url).path.removeprefix("https://books.toscrape.com").removeprefix("/")
    save_path = Path("books_data") / filename if not folder else folder
    async with session.get(url) as response:
        if response.ok:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(await response.content.read())
        else:
            raise Exception(f"Error downloading {url}: {response.status}")

async def process_category(session, category_url, pbar): # Accept the main pbar
    output_folder = Path("books_data") / parse_url(category_url)
    if not os.path.exists(output_folder): 
        pathlib.Path(output_folder).mkdir(parents=True, exist_ok=True)

    while category_url:
        html = await fetch_html(session, category_url)
        soup = BeautifulSoup(html, "lxml")
        
        # Save HTML file
        with open(os.path.join(output_folder, "index.html"), "w") as f:
            f.write(html)
        await extract_resources_and_download(session, category_url, html)

        for book_element in soup.select("article.product_pod h3 a"):
            relative_book_url = book_element["href"]
            absolute_book_url = urljoin(category_url, relative_book_url)
            await download_book(session, absolute_book_url, pbar)

        # Find next page
        next_page = soup.select_one("li.next a")
        if next_page: 
            category_url = BASE_URL + "catalogue/" + next_page["href"]
        else:
            category_url = None 

async def pre_crawl_and_calculate_downloads(session):
    total_books = 0
    base_html = await fetch_html(session, BASE_URL)
    base_soup = BeautifulSoup(base_html, "lxml")
    category_list_html = base_soup.select_one(".nav-list")
    category_list = category_list_html.find_all("li", recursive=False)
    with tqdm(desc="Pre-Crawling") as pbar_sub:
        total_books += await analyze_and_count(session, BASE_URL)
        for category_item in category_list:  
            category_link = category_item.find("a")["href"]
            category_url = urljoin(BASE_URL, category_link)
            total_books += await analyze_and_count(session, category_url)
            subcategories = category_item.select("ul li a")
            pbar_sub.total = len(subcategories)
            for subcategory_link in subcategories:
                subcategory_url = urljoin(BASE_URL, subcategory_link["href"])
                total_books += await analyze_and_count(session, subcategory_url)
                pbar_sub.update(1)
            
    return total_books

async def analyze_and_count(session, category_url):
    category_html = await fetch_html(session, category_url)
    category_soup = BeautifulSoup(category_html, "lxml")
    num_page = await find_num_pages(category_soup)
    books = category_soup.select("ol.row li article.product_pod")
    total_books = len(books) * num_page
    return total_books

async def find_num_pages(soup):
    page_info_element = soup.find('li', class_="current")
    if page_info_element: 
        page_info_text = page_info_element.text.strip()  
        words = page_info_text.split()
        index_of_word_of = words.index("of")
        if index_of_word_of != -1:
            num_pages_str = words[index_of_word_of + 1]
            return int(num_pages_str)
    else:
        return 1
    
async def scrape_and_download():
    async with aiohttp.ClientSession() as session:
        total_files = await pre_crawl_and_calculate_downloads(session)
        with tqdm(total=total_files, desc="Website Download Progress") as pbar:  
            html = await fetch_html(session, BASE_URL)
            base_output_folder = Path("books_data")
            base_output_folder.mkdir(exist_ok=True)

            with open(base_output_folder / "index.html", "w") as f:
                f.write(html)

            await extract_resources_and_download(session, BASE_URL, html)

            html = await fetch_html(session, BASE_URL)
            soup = BeautifulSoup(html, "lxml")
            categories = [BASE_URL + link["href"] for link in soup.select(".nav-list ul a")]

            await asyncio.gather(*[process_category(session, category_url, pbar) for category_url in categories]) # Pass the pbar


if __name__ == "__main__":
    asyncio.run(scrape_and_download()) 
