import requests, aiohttp, asyncio, os, re, pathlib
from bs4 import BeautifulSoup
from pathlib import Path
from tqdm import tqdm
from urllib.parse import urljoin 
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
        # Fetch from the website if not found in the cache 
        html = await (await session.get(url)).text() 

        # Ensure cache directory exists BEFORE storing 
        os.makedirs(CACHE_DIR, exist_ok=True)  
        with open(cache_filepath, "w") as f:
            f.write(html)

        return html 

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

async def download_resource(session, url, folder, progress_tracker):
    filename = url.split("/")[-1]
    save_path = folder / filename
    async with session.get(url) as response:
        if response.ok:
            with save_path.open("wb") as f:
                f.write(await response.content.read())
        else:
            raise Exception(f"Error downloading {url}: {response.status}")
    progress_tracker["files_downloaded"] += 1  

async def process_category(session, category_url, progress_tracker, pbar): # Accept the main pbar
    output_folder = Path("books_data") / "catalogue" / "category" / category_url.split("/")[-2]
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

        for book_element in soup.select("article.product_pod h3 a"):
            relative_book_url = book_element["href"]
            absolute_book_url = urljoin(category_url, relative_book_url)
            book_data = await extract_book_data(session, absolute_book_url) 

            await download_resource(session, book_data["image_url"], images_folder, progress_tracker)
            await asyncio.gather(
                *[download_resource(session, url, css_folder, progress_tracker) for url in book_data["css_urls"]],
                *[download_resource(session, url, js_folder, progress_tracker) for url in book_data["js_urls"]]
            )
            pbar.update(1) 
            logging.info(f"Files downloaded: {progress_tracker['files_downloaded']}, Current total: {pbar.n}")

        # Find next page
        next_page = soup.select_one("li.next a")
        if next_page: 
            category_url = BASE_URL + "catalogue/" + next_page["href"]
        else:
            category_url = None 

async def extract_resources_and_download(session, base_url, html, output_folder, progress_tracker):
    soup = BeautifulSoup(html, "html.parser")

    css_links = [urljoin(base_url, link["href"]) for link in soup.find_all("link", rel="stylesheet")]
    js_links = [urljoin(base_url, script["src"]) for script in soup.find_all("script") if script.has_attr('src')]

    await asyncio.gather(
        *[download_resource(session, url, output_folder, progress_tracker) for url in css_links],
        *[download_resource(session, url, output_folder, progress_tracker) for url in js_links]
    )

async def pre_crawl_and_calculate_downloads(session):
    num_categories = 0 
    total_books = 0

    # Discover categories
    base_html = await fetch_html(session, BASE_URL)
    base_soup = BeautifulSoup(base_html, "html.parser")
    category_list = base_soup.select_one(".nav-list")


    with tqdm(total=len(category_list.find_all("li", recursive=False)) + num_categories, desc="Pre-Crawling") as pbar:  # Progress bar for pre-crawling
        for category_item in category_list.find_all("li", recursive=False):  
            num_categories += 1  
            category_link = category_item.find("a")["href"]
            category_url = urljoin(BASE_URL, category_link)

            # Count books and analyze in this main category 
            total_files = await analyze_and_count(session, category_url, total_books, pbar, num_categories=num_categories) 

            # Process subcategories
            subcategories = category_item.select("ul li a")
            for subcategory_link in subcategories:
                subcategory_url = urljoin(BASE_URL, subcategory_link["href"])
                total_files = await analyze_and_count(session, subcategory_url, total_books, pbar, num_categories=num_categories)
                num_categories += 1  # Increment for subcategory
                pbar.update(1)   # Update pre-crawl progress
                logging.info(f"Updated values: total_files: {total_files}, num_categories: {num_categories}")
        logging.info(f"Initial total_files estimation: {total_files}")
        return total_files


async def analyze_and_count(session, category_url, total_books, pbar, num_categories=0):
    sample_size = 3  # Analyze 3 sample books
    sample_css = 0

    while category_url:  
        category_html = await fetch_html(session, category_url)
        category_soup = BeautifulSoup(category_html, "html.parser")

        # Count books in the category 
        books = category_soup.select("ol.row li article.product_pod")
        total_books += len(books)

        # Analyze multiple sample book pages for a more accurate average
        for book_element in books[:sample_size]:
            book_link_element = book_element.find("div", class_="image_container").find("a")
            book_link = book_link_element["href"]
            book_url = urljoin(category_url, book_link) 

            book_html = await fetch_html(session, book_url)
            book_soup = BeautifulSoup(book_html, "html.parser")
            sample_css += len(book_soup.find_all("link", rel="stylesheet"))


        # Explore Metadata for Estimation (Optional)
        metadata_tag = category_soup.find("meta", attrs={"name": "estimated-resources"})
        if metadata_tag:
            estimated_resources_per_book = int(metadata_tag["content"]) 
        else:
        # Fallback to CSS-based estimation if metadata is not found
            estimated_resources_per_book = sample_css / sample_size

        logging.info(f"category: {category_url}, total books: {total_books}, estimated resources: {estimated_resources_per_book}")

        total_files = (num_categories * total_books * estimated_resources_per_book) + 1 
        pbar.total = total_files 
        logging.info(f"Calculated total_files for category {category_url}: {total_files}") 

        # Find the "next page" link
        next_page = category_soup.select_one("li.next a") 
        if next_page: 
            category_url = BASE_URL + "catalogue/" + next_page["href"]
        else:
            category_url = None 
            break  # Exit the loop to avoid 404 errors
    return total_files


async def scrape_and_download():
    async with aiohttp.ClientSession() as session:
        total_files = await pre_crawl_and_calculate_downloads(session) 
        progress_tracker = {"files_downloaded": 0}

        with tqdm(total=total_files, desc="Website Download Progress") as pbar:  
            html = await fetch_html(session, BASE_URL)
            base_output_folder = Path("books_data")
            base_output_folder.mkdir(exist_ok=True)

            with open(base_output_folder / "index.html", "w") as f:
                f.write(html)

            await extract_resources_and_download(session, BASE_URL, html, base_output_folder, progress_tracker)

            html = await fetch_html(session, BASE_URL)
            soup = BeautifulSoup(html, "html.parser")
            categories = [BASE_URL + link["href"] for link in soup.select(".nav-list ul a")]

            await asyncio.gather(*[process_category(session, category_url, progress_tracker, pbar) for category_url in categories]) # Pass the pbar


if __name__ == "__main__":
    asyncio.run(scrape_and_download()) 
