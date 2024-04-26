import requests, aiohttp, asyncio, os, re, pathlib
from bs4 import BeautifulSoup
from pathlib import Path
from tqdm import tqdm
from urllib.parse import urljoin, urlparse
import logging 
logging.basicConfig(level=logging.DEBUG)


BASE_URL = "https://books.toscrape.com/"
CACHE_DIR = "html_cache"

logging.basicConfig(filename='scraper.log', 
                    level=logging.DEBUG, 
                    format='%(asctime)s - %(levelname)s - %(message)s')  


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


async def download_book(session, book_url, progress_tracker):
    html = await fetch_html(session, book_url)
    folder_path = Path("books_data") / urlparse(book_url).path.removeprefix("https://books.toscrape.com").removeprefix("/").removesuffix('/index.html')
    if not os.path.exists(folder_path): 
        pathlib.Path(folder_path).mkdir(parents=True, exist_ok=True)
    with open(folder_path / "index.html", "w") as f:
        f.write(html)
    await extract_resources_and_download(session, book_url, html, progress_tracker)

async def extract_resources_and_download(session, base_url, html, progress_tracker, book=False):
    soup = BeautifulSoup(html, "html.parser")
    image_tags = [urljoin(base_url, img["src"]) for img in soup.find_all("img")]
    css_links = [urljoin(base_url, link["href"]) for link in soup.find_all("link", rel="stylesheet")]
    js_links = [urljoin(base_url, script["src"]) for script in soup.find_all("script") if script.has_attr('src')]
    total_resources = len(image_tags) + len(css_links) + len(js_links)  
    progress_tracker["files_downloaded"] += total_resources 
    await asyncio.gather(
        *[download_resource(session, url, progress_tracker) for url in image_tags],
        *[download_resource(session, url, progress_tracker) for url in css_links],
        *[download_resource(session, url, progress_tracker) for url in js_links]
    )

async def download_resource(session, url, progress_tracker, folder=None):
    filename = urlparse(url).path.removeprefix("https://books.toscrape.com").removeprefix("/")
    save_path = Path("books_data") / filename if not folder else folder
    async with session.get(url) as response:
        if response.ok:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(await response.content.read())
        else:
            raise Exception(f"Error downloading {url}: {response.status}")
    progress_tracker["files_downloaded"] += 1  

async def process_category(session, category_url, progress_tracker, pbar): # Accept the main pbar
    output_folder = Path("books_data") / urlparse(category_url).path.removeprefix("https://books.toscrape.com").removeprefix("/").removesuffix('/index.html')
    if not os.path.exists(output_folder): 
        pathlib.Path(output_folder).mkdir(parents=True, exist_ok=True)

    while category_url:
        html = await fetch_html(session, category_url)
        soup = BeautifulSoup(html, "html.parser")
        
        # Save HTML file
        with open(os.path.join(output_folder, "index.html"), "w") as f:
            f.write(html)
        await extract_resources_and_download(session, category_url, html, progress_tracker)

        for book_element in soup.select("article.product_pod h3 a"):
            relative_book_url = book_element["href"]
            absolute_book_url = urljoin(category_url, relative_book_url)
            await download_book(session, absolute_book_url, progress_tracker)
            pbar.update(1) 

        # Find next page
        next_page = soup.select_one("li.next a")
        if next_page: 
            category_url = BASE_URL + "catalogue/" + next_page["href"]
        else:
            category_url = None 

async def pre_crawl_and_calculate_downloads(session):
    num_categories = 0  
    total_books = 0
    total_files = 0  
    total_subcategories = 0
    num_categories_processed = 0 

    base_html = await fetch_html(session, BASE_URL)
    base_soup = BeautifulSoup(base_html, "html.parser")
    category_list = base_soup.select_one(".nav-list")

    with tqdm(desc="Pre-Crawling") as pbar:  # Initialize the progress bar without a total for now
        pbar.update(1)
        for category_item in category_list.find_all("li", recursive=False):  
            num_categories += 1  

            category_link = category_item.find("a")["href"]
            category_url = urljoin(BASE_URL, category_link)

            category_book_count, estimated_resources_per_book = await analyze_and_count(session, category_url, total_books, pbar, num_categories=num_categories)
            total_books += category_book_count  

            category_total_files = (num_categories * category_book_count * estimated_resources_per_book) + 1 
            total_files += category_total_files 

            # Process subcategories
            subcategories = category_item.select("ul li a")
            num_subcategories = len(subcategories)
            total_subcategories += num_subcategories
            num_categories_processed += 1 

            for subcategory_link in subcategories:
                subcategory_url = urljoin(BASE_URL, subcategory_link["href"])

                subcategory_book_count, estimated_resources_per_book = await analyze_and_count(session, subcategory_url, total_books, pbar, num_categories=num_categories)
                total_books += subcategory_book_count

                subcategory_total_files = (num_categories * subcategory_book_count * estimated_resources_per_book) + 1
                total_files += subcategory_total_files
                num_categories += 1  
                pbar.update(1) 

            # Calculate average subcategories and update progress bar total
            if num_categories_processed > 0:
                average_subcategories_per_category = total_subcategories / num_categories_processed
            else:
                average_subcategories_per_category = 0  

            total_iterations = len(category_list.find_all("li", recursive=False)) + (len(category_list.find_all("li", recursive=False)) * average_subcategories_per_category)
            pbar.total = total_iterations  # Update the total after calculations
    print(total_files)
    return total_files


async def analyze_and_count(session, category_url, total_books, pbar, num_categories=0):
    sample_size = 3  
    total_resources = 0  

    while category_url:  
        category_html = await fetch_html(session, category_url)
        category_soup = BeautifulSoup(category_html, "html.parser")

        books = category_soup.select("ol.row li article.product_pod")
        total_books += len(books)

        for book_element in books[:sample_size]:
            book_link_element = book_element.find("div", class_="image_container").find("a")
            book_link = book_link_element["href"]
            book_url = urljoin(category_url, book_link) 

            book_html = await fetch_html(session, book_url)
            book_soup = BeautifulSoup(book_html, "html.parser")

            # Count CSS 
            total_resources += len(book_soup.find_all("link", rel="stylesheet"))

            # Count JavaScript (adjust if needed)
            total_resources += len(book_soup.find_all("script", src=True)) 

        estimated_resources_per_book = total_resources / sample_size

        # Find the "next page" link
        next_page = category_soup.select_one("li.next a") 
        if next_page: 
            category_url = BASE_URL + next_page["href"]
        else:
            category_url = None 
            break  # Exit the loop to avoid 404 errors
    return total_books, estimated_resources_per_book


async def scrape_and_download():
    async with aiohttp.ClientSession() as session:
        progress_tracker = {"files_downloaded": 0}
        total_files = 12277
        with tqdm(total=total_files, desc="Website Download Progress") as pbar:  
            html = await fetch_html(session, BASE_URL)
            base_output_folder = Path("books_data")
            base_output_folder.mkdir(exist_ok=True)

            with open(base_output_folder / "index.html", "w") as f:
                f.write(html)

            await extract_resources_and_download(session, BASE_URL, html, progress_tracker)

            html = await fetch_html(session, BASE_URL)
            soup = BeautifulSoup(html, "html.parser")
            categories = [BASE_URL + link["href"] for link in soup.select(".nav-list ul a")]

            await asyncio.gather(*[process_category(session, category_url, progress_tracker, pbar) for category_url in categories]) # Pass the pbar


if __name__ == "__main__":
    asyncio.run(scrape_and_download()) 
