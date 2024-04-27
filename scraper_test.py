import pytest, aiohttp, asyncio, os, pathlib
from asynctest import MagicMock, Mock
from unittest.mock import AsyncMock, patch
from bs4 import BeautifulSoup
from scraper import (
    fetch_with_retry, 
    extract_resources_and_download, 
    pre_crawl_and_calculate_downloads, 
    download_book,
    download_resource,
    process_category,
    parse_url,
    get_and_create_file
)


@pytest.mark.asyncio
async def test_successful_fetch():
    session_mock = MagicMock()
    response_mock = MagicMock()
    response_mock.text.return_value = asyncio.Future()
    response_mock.text.return_value.set_result("Mocked response")
    session_mock.get.return_value.__aenter__.return_value = response_mock

    url = "http://example.com"
    content = await fetch_with_retry(session_mock, url)
    
    session_mock.get.assert_called_once_with(url)
    response_mock.text.assert_called_once()
    assert content == "Mocked response"

@pytest.mark.asyncio
async def test_fetch_with_retry_retry():
    session = Mock()
    session.get = Mock(side_effect=[Exception] * 3 + [Mock()])
    url = "http://example.com"
    with pytest.raises(Exception):
        await fetch_with_retry(session, url)

def test_parse_url():
    url = "https://books.toscrape.com/some-page.html"
    assert parse_url(url) == "some-page.html"

def test_get_and_create_file():
    url = "https://books.toscrape.com/some-page.html"
    output_file = get_and_create_file(url)
    assert output_file == pathlib.Path("books_data/some-page.html")

def test_html_parsing():
    html = "<html><body><h1>Hello World</h1></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    assert soup.find("h1").text == "Hello World"

@pytest.mark.asyncio
async def test_pre_crawling_and_count_logic():

    total_books = await pre_crawl_and_calculate_downloads(BeautifulSoup('''
        <li class="current">Page 1 of 3</li>
        <ol class="row">
            <li class="col-xs-6 col-sm-4 col-md-3 col-lg-3">
                <article class="product_pod">
                    <div class="image_container">
                        <h3><a href="../../../its-only-the-himalayas_981/index.html" title="It's Only the Himalayas">It's Only the Himalayas</a></h3>
            </div></article></li>
                    
            <li class="col-xs-6 col-sm-4 col-md-3 col-lg-3">
                <article class="product_pod">
                    <div class="image_container">
                        <a href="../../../full-moon-over-noahs-ark-an-odyssey-to-mount-ararat-and-beyond_811/index.html"><img src="../../../../media/cache/57/77/57770cac1628f4407636635f4b85e88c.jpg" alt="Full Moon over Noah’s Ark: An Odyssey to Mount Ararat and Beyond" class="thumbnail"></a></div>       
                        <p class="star-rating Four"><i class="icon-star"></i><i class="icon-star"></i><i class="icon-star"></i><i class="icon-star"></i><i class="icon-star"></i></p><h3>
                        <a href="../../../full-moon-over-noahs-ark-an-odyssey-to-mount-ararat-and-beyond_811/index.html" title="Full Moon over Noah’s Ark: An Odyssey to Mount Ararat and Beyond">Full Moon over Noah’s ...</a></h3>
            </div></article></li>
            
            <li class="col-xs-6 col-sm-4 col-md-3 col-lg-3">
                <article class="product_pod">
                    <div class="image_container">             
                        <a href="../../../1000-places-to-see-before-you-die_1/index.html"><img src="../../../../media/cache/d7/0f/d70f7edd92705c45a82118c3ff6c299d.jpg" alt="1,000 Places to See Before You Die" class="thumbnail"></a></div>
                        <p class="star-rating Five"><i class="icon-star"></i><i class="icon-star"></i><i class="icon-star"></i><i class="icon-star"></i><i class="icon-star"></i></p>
                        <h3><a href="../../../1000-places-to-see-before-you-die_1/index.html" title="1,000 Places to See Before You Die">1,000 Places to See ...</a></h3>
        </div></article></li></ol> ''', "html.parser"))
    assert total_books == 9

@pytest.mark.asyncio
async def test_download_resource():
    session = aiohttp.ClientSession()
    url = "https://books.toscrape.com/media/cache/6d/41/6d418a73cc7d4ecfd75ca11d854041db.jpg"
    folder = "books_data/media/cache/6d/41/6d418a73cc7d4ecfd75ca11d854041db.jpg"

    # Test downloading a resource
    await download_resource(session, url)
    assert os.path.exists(folder)

    # Clean up
    os.remove(folder)
    await session.close()
    

@pytest.mark.asyncio
async def test_extract_resources_and_download():
    mock_session = AsyncMock()

    base_url = "http://example.com"
    html = """
    <html><head>
        <link rel="stylesheet" href="styles.css">
        <script src="script.js"></script>
    </head>
        <body>
            <img src="image.jpg">
        </body>
    </html>
    """

    # Patching download_resource to avoid actual network calls
    with patch("scraper.download_resource", new_callable=AsyncMock) as mock_download_resource:
        await extract_resources_and_download(mock_session, base_url, html)
        # Check if BeautifulSoup is called with the correct HTML
        mock_download_resource.assert_any_call(mock_session, base_url + "/image.jpg")
        mock_download_resource.assert_any_call(mock_session, base_url + "/styles.css")
        mock_download_resource.assert_any_call(mock_session, base_url + "/script.js")

@pytest.mark.asyncio
async def test_download_book(tmp_path):
    session_mock = MagicMock()
    pbar_mock = MagicMock()

    # Mock the session.get method to return HTML content
    mock_get = AsyncMock()
    mock_get.return_value.text.return_value = "<html><body>Mock HTML content</body></html>"
    session_mock.get = mock_get

    # Mock extract_resources_and_download function
    async def mock_extract_resources_and_download(*args, **kwargs):
        pass

    await download_book(session_mock, "http://example.com/book.html", pbar_mock)
    mock_get.assert_called_once_with("http://example.com/book.html")

    # Assert that HTML content was written to a file
    file_path = pathlib.Path("books_data/book.html")
    assert file_path.exists()
    assert file_path.read_text() == "<html><body>Mock HTML content</body></html>"

    # Assert that pbar.update was called once
    pbar_mock.update.assert_called_once_with(1)
    
@pytest.mark.asyncio
async def test_process_category():
    expected_book_page_urls = [
        "http://example.com/book_page_1.html",
        "http://example.com/book_page_2.html",
        ]
    
    category_html = '''<html><body>Category Page HTML
                <ol class="row">
                <li class="col-xs-6 col-sm-4 col-md-3 col-lg-3"><article class="product_pod">
        <h3><a href="book_page_1.html" title="Book1">Book1</a></h3>
        </div></article></li>           
        <li class="col-xs-6 col-sm-4 col-md-3 col-lg-3">
        <article class="product_pod">
        <h3><a href="book_page_2.html" title="Book2">Book2</a></h3>
        </div></article></li></ol> </body></html>'''
    
    async with aiohttp.ClientSession() as session:
        pbar_mock = MagicMock()

        # Mock the session.get method to return HTML content for category and book pages
        async def mock_get(*args, **kwargs):
            url = args[0]
            if "category_page" in url:
                return AsyncMock(text=AsyncMock(return_value=category_html))
            elif "book_page" in url:
                return AsyncMock(text=AsyncMock(return_value="<html><body>Book Page HTML</body></html>"))
            else:
                return AsyncMock(text=AsyncMock(return_value="<html><body>Other Page HTML</body></html>"))

        # Patch the session.get method to use the mocked function
        with patch.object(session, 'get', side_effect=mock_get) as mocked_get:
            with patch("scraper.extract_resources_and_download") as mocked_extract_resources_and_download:
                await process_category(session, "http://example.com/category_page.html", pbar_mock)
                mocked_get.assert_any_call("http://example.com/category_page.html")

                # Assert that HTML content was written to a file for the category page
                category_file_path = "books_data/category_page.html"
                assert pathlib.Path(category_file_path).exists()
                assert pathlib.Path(category_file_path).read_text() == category_html

                # Assert that extract_resources_and_download was called with the correct arguments for the category page
                mocked_extract_resources_and_download.assert_any_call(session, "http://example.com/category_page.html", category_html)
                
                expected_book_page_urls = [
                    "http://example.com/book_page_1.html",
                    "http://example.com/book_page_2.html",
                    ]
                [mocked_get.assert_any_call(url) for url in expected_book_page_urls]

                # Assert that HTML content was written to a file for the book pages
                book_file_path_1 = "books_data/book_page_1.html"
                book_file_path_2 = "books_data/book_page_2.html"
                assert pathlib.Path(book_file_path_1).exists()
                assert pathlib.Path(book_file_path_1).read_text() == "<html><body>Book Page HTML</body></html>"
                assert pathlib.Path(book_file_path_2).exists()
                assert pathlib.Path(book_file_path_2).read_text() == "<html><body>Book Page HTML</body></html>"

                # Assert that extract_resources_and_download was called with the correct arguments for the book pages
                [mocked_extract_resources_and_download.assert_any_call(session, url, "<html><body>Book Page HTML</body></html>") for url in expected_book_page_urls]
                
                # Assert that pbar.update was called for each book
                assert pbar_mock.update.call_count == 2