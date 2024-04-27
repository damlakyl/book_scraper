import aiohttp, asyncio, os, pathlib, logging
from bs4 import BeautifulSoup
from pathlib import Path
from tqdm import tqdm
from urllib.parse import urljoin, urlparse

# Base URL of the website to scrape
BASE_URL = "https://books.toscrape.com/"
# Base folder to save scraped data
BASE_FOLDER = Path("books_data")
# Configure logging
logging.basicConfig(filename='scraper.log', 
                    level=logging.DEBUG, 
                    format='%(asctime)s - %(levelname)s - %(message)s')  

# Function to fetch URL content with retries
async def fetch_with_retry(session, url, retries=3, delay=1):
    for attempt in range(retries):
        try:
            async with session.get(url) as response:
                return await response.text()
        except aiohttp.ClientOSError as e:
            if attempt < retries - 1:
                print(f"Connection error, retrying... (Attempt {attempt + 1}/{retries})")
                await asyncio.sleep(delay)
            else:
                raise e
# Function to parse URL and extract path           
def parse_url(url): 
    return urlparse(url).path.removeprefix("https://books.toscrape.com").removeprefix("https://example.com").removeprefix("/")

# Function to get file path and create necessary folders
def get_and_create_file(url):
    output_file = BASE_FOLDER / parse_url(url)
    file_extension = pathlib.Path(url).suffix
    output_folder = os.path.dirname(output_file) if file_extension == ".html" else output_file
    if not os.path.exists(output_folder): 
        pathlib.Path(output_folder).mkdir(parents=True, exist_ok=True)
    return output_file

# Function to extract resources (images, CSS, JS) from HTML and download them
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

# Function to estimate total number of books to download
async def pre_crawl_and_calculate_downloads(soup):
    page_info_element = soup.find('li', class_="current")
    if page_info_element: 
        page_info_text = page_info_element.text.strip()  
        words = page_info_text.split()
        index_of_word_of = words.index("of")
        if index_of_word_of != -1:
            num_pages_str = words[index_of_word_of + 1]
            num_page = int(num_pages_str)
    else:
        num_page = 1
    books = soup.select("ol.row li article.product_pod")
    total_books = len(books) * num_page
    return total_books

# Function to process each category
async def process_category(session, category_url, pbar): # Accept the main pbar
    while category_url:
        html = await (await session.get(category_url)).text() 
        soup = BeautifulSoup(html, "lxml")
        file_path = get_and_create_file(category_url)
        category_base = category_url[:category_url.rfind("/")]
        if pathlib.Path(file_path).suffix == ".html":
            with open(file_path, "w") as f:
                f.write(html)
        # Save HTML file
        await extract_resources_and_download(session, category_url, html)

        for book_element in soup.select("article.product_pod h3 a"):
            book_url = urljoin(category_url, book_element["href"])
            await download_book(session, book_url, pbar)

        # Find next page
        next_page = soup.select_one("li.next a")
        if next_page: 
            category_url = category_base + "/" +  next_page["href"]
        else:
            category_url = None

# Function to download a book
async def download_book(session, book_url, pbar):
    html = await (await session.get(book_url)).text() 
    file_path = BASE_FOLDER / parse_url(book_url)
    file_extension = pathlib.Path(file_path).suffix
    
    if file_extension == ".html":
        folder_path = os.path.dirname(file_path)
        if not os.path.exists(folder_path): 
            pathlib.Path(folder_path).mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            f.write(html)
    else:
        if not os.path.exists(folder_path): 
            pathlib.Path(folder_path).mkdir(parents=True, exist_ok=True)
    await extract_resources_and_download(session, book_url, html)
    pbar.update(1)   

# Function to download a resource (image, CSS, JS)
async def download_resource(session, url, folder=None):
    filename = parse_url(url)
    save_path = BASE_FOLDER / filename if not folder else folder
    try:
        async with session.get(url) as response:
            if response.ok:
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(await response.content.read())
            else:
                raise Exception(f"Error downloading {url}: {response.status}")
    except aiohttp.ClientOSError as e:
        print(f"Error downloading {url}: {e}")
        # Retry the request
        await fetch_with_retry(session, url)

# Main function to initiate scraping and downloading
async def scrape_and_download():
    async with aiohttp.ClientSession() as session:
        html = await (await session.get(BASE_URL)).text()
        soup = BeautifulSoup(html, "lxml")
        total_files = await pre_crawl_and_calculate_downloads(soup)
        with tqdm(total=total_files, desc="Website Download Progress") as pbar:  
            BASE_FOLDER.mkdir(exist_ok=True)
            with open(BASE_FOLDER / "index.html", "w") as f:
                f.write(html)

            await extract_resources_and_download(session, BASE_URL, html)
            categories = [BASE_URL + link["href"] for link in soup.select(".nav-list ul a")]

            await asyncio.gather(*[process_category(session, category_url, pbar) for category_url in categories])


if __name__ == "__main__":
    asyncio.run(scrape_and_download()) 
