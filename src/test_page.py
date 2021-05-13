# Based on https://medium.com/z1digitalstudio/pyppeteer-the-snake-charmer-f3d1843ddb19
# import pprint
import asyncio
import pytest
from process_url import (
    Page,
    AdBlock,
)

testing_url = "http://www.google.com"


@pytest.mark.asyncio
async def test_load():
    # If hangs check https://github.com/pyppeteer/pyppeteer/issues/111
    page = Page()
    await page.load_page(None, testing_url)
    page_content = page.content
    assert "google" in page_content, f"Not 'google' {page_content}"


def test_ad_block():
    ad_block = AdBlock(["./ads-servers.txt", "./ads-servers.he.txt"])
    assert ad_block.is_ad("js.nagich.co.il")
    assert ad_block.is_ad("ad.a8.net")
    assert not ad_block.is_ad("123sad4.co.il")
    assert ad_block.is_ad("taboola.com")
    assert ad_block.is_ad("ad-delivery.net")
    assert ad_block.is_ad("www.googletagmanager.com")


def test_get_tld():
    assert AdBlock._get_tld("js.nagich.co.il", 2) == "co.il"
    assert AdBlock._get_tld("js.nagich.co.il", 3) == "nagich.co.il"
    assert AdBlock._get_tld("il", 2) == "il"


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(Page().load_page(testing_url))
