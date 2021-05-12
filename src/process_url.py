import asyncio
from pyppeteer import (
    launch,
    errors,
)
import easyargs
import logging
import json
from dataclasses import dataclass
from dataclasses_json import dataclass_json
from pprint import PrettyPrinter
from datetime import datetime
from urllib.parse import urlparse
from tempfile import mkdtemp
from contextlib import contextmanager
from shutil import rmtree
from os import path
from base64 import b64encode
from time import sleep

pretty_printer = PrettyPrinter(indent=4)


@contextmanager
def defer_close(thing):
    try:
        yield thing
    finally:
        thing.close()


@contextmanager
def tmpdir():
    try:
        temp_dir = mkdtemp(suffix="images")
        yield temp_dir
    finally:
        rmtree(temp_dir)


class AdBlock:
    def __init__(self, filenames):
        self.hosts = set()
        for filename in filenames:
            self._load(filename)

    def _load(self, filename):
        with open(filename) as f:
            for line in f:
                columns = line.split()
                if len(columns) < 2:
                    continue
                if columns[0] != "0.0.0.0":
                    continue
                self.hosts.add(columns[1])

    @staticmethod
    def _get_tld(hostname, count=2):
        words = hostname.split(".")
        if len(words) > count:
            words = words[-count:]
            return ".".join(words)
        return hostname

    def is_ad(self, hostname):
        return (
            hostname in self.hosts
            or AdBlock._get_tld(hostname, 2) in self.hosts
            or AdBlock._get_tld(hostname, 3) in self.hosts
        )


class AdBlockDummy:
    def is_ad(self, _):
        return False


async def get_browser():
    browser = await launch(
        {
            "headless": True,
            "args": ["--no-sandbox"],
            "executablePath": "/usr/bin/google-chrome-stable",
            "logLevel": logging.ERROR,
        }
    )
    return browser


@dataclass_json
@dataclass
class RequestInfo:
    url: str = None
    host: str = None
    method: str = None
    status: int = None
    ts_request: datetime = None
    ts_response: datetime = None
    elapsed: float = 0.0
    is_ad: bool = False


class EventHandler:
    def __init__(self, ad_block):
        self.requests_info = {}
        self.redirects = []
        self.ad_block = ad_block

    def _process_request(self, r):
        if not hasattr(r, "url"):
            logging.error(f"request is missing url {r.__dir__()}")
            return True

        url = r.url

        if not hasattr(r, "_requestId"):
            logging.error(f"requestID is None for {url} {r.__dir__()}")
            return True

        request_id = r._requestId
        if request_id in self.requests_info:
            logging.error(
                f"requestID {request_id} is already in self.requests_info for {url}: {self.requests_info[request_id]}"
            )

        parsed_url = urlparse(url)
        is_ad = self.ad_block.is_ad(parsed_url.netloc)

        requests_info = RequestInfo(
            method=r.method,
            url=url,
            host=parsed_url.netloc,
            ts_request=datetime.now(),
            is_ad=is_ad,
        )
        self.requests_info[request_id] = requests_info

        if is_ad:
            return False

        return True

    def _process_response(self, r):
        if not hasattr(r, "url"):
            logging.error(f"response is missing url {r.__dir__()}")
            return

        url = r.url
        if not r.request:
            logging.error(f"request is missing in the response for {url}")
            return

        if not hasattr(r.request, "_requestId"):
            logging.error(f"requestID is missing in response for {url}")
            return
        request_id = r.request._requestId

        if request_id not in self.requests_info:
            logging.error(
                f"requestID {request_id} is missing in map of requests for {url}"
            )
            return

        request_info = self.requests_info[request_id]
        if request_info.is_ad:
            logging.debug(f"got response for an ad {url}")

        request_info.status = r.status
        request_info.ts_response = datetime.now()
        request_info.elapsed = (
            request_info.ts_response - request_info.ts_request
        ).total_seconds()
        self.requests_info[request_id] = request_info

    async def request_interception(self, r):
        # https://github.com/pyppeteer/pyppeteer/issues/198
        r.__setattr__("_allowInterception", True)
        keep_going = self._process_request(r)
        if keep_going:
            return await r.continue_()

        logging.debug(f"aborted ad {r.url}")
        return await r.abort()

    async def response_interception(self, r):
        r.__setattr__("_allowInterception", True)
        self._process_response(r)
        return

    async def request_will_be_sent(self, e):
        if "type" not in e:
            logging.error(f"request type is missing in {e}")
            return
        if "documentURL" not in e:
            logging.error(f"documentURL is missing in {e}")
            return

        request_type = e["type"]
        if request_type != "Document":
            return

        logging.debug(f"Redirect {pretty_printer.pformat(e)}")
        self.redirects.append(e["documentURL"])


class Page:
    def __init__(self, timeout=600.0, keep_alive=False, ad_block=AdBlockDummy()):
        self.timeout, self.ad_block, self.keep_alive = timeout, ad_block, keep_alive
        # Add stop page https://github.com/puppeteer/puppeteer/issues/3238
        self.event_handler = EventHandler(ad_block)
        self.content, self.screenshot, self.browser = None, None, None

    # https://stackoverflow.com/questions/48986851/puppeteer-get-request-redirects
    async def _get_page(self):
        page = await self.browser.newPage()
        page.timeout = int(self.timeout * 1000)
        # https://github.com/pyppeteer/pyppeteer/issues/198
        # await page.setRequestInterception(True)
        page.on(
            "request",
            lambda r: asyncio.ensure_future(self.event_handler.request_interception(r)),
        )

        page.on(
            "response",
            lambda r: asyncio.ensure_future(
                self.event_handler.response_interception(r)
            ),
        )

        client = await page.target.createCDPSession()
        await client.send("Network.enable")
        client.on(
            "Network.requestWillBeSent",
            lambda e: asyncio.ensure_future(self.event_handler.request_will_be_sent(e)),
        )
        return page

    async def _take_screenshot(self, page, url):
        with tmpdir() as temp_dir:
            filename = path.join(temp_dir, "image.png")
            try:
                await page.screenshot({"path": filename, "fullPage": True})
            except errors.NetworkError:
                logging.exception(f"Failed to get screenshot for {url}")
                return None

            with open(filename, mode="r+b") as f:
                data = f.read()
                return b64encode(data).decode("utf-8")

    async def load_page(self, request_id, url):
        self.browser = await get_browser()
        page = await self._get_page()
        try:
            # page.timeout() accepts milliseconds
            await page.goto(url, {"timeout": int(self.timeout * 1000)})
        except errors.TimeoutError:
            logging.exception(f"Failed to load {url}")

        self.screenshot = await self._take_screenshot(page, url)

        try:
            self.content = await page.content()
        except errors.NetworkError:
            logging.exception(f"Failed to get content for {url}")

        while self.keep_alive:
            sleep(1.0)

        await page.close()
        await self.browser.close()

        return


@easyargs
def main(url="http://www.google.com", request_id=None, timeout=5.0, keep_alive=False):
    ts_start = datetime.now()
    ad_block = AdBlock(["./ads-servers.txt", "./ads-servers.he.txt"])
    logging.basicConfig(level=logging.INFO)

    logging.info(f"Starting Chrome for {url}")
    loop = asyncio.get_event_loop()
    page = Page(timeout=timeout, keep_alive=keep_alive, ad_block=ad_block)
    loop.run_until_complete(page.load_page(request_id, url))
    requests_info = page.event_handler.requests_info
    serializable_requests = []
    slow_responses = set()
    ads = set()
    info = {}
    for _, request in requests_info.items():
        if request.ts_request:
            request.ts_request = request.ts_request.strftime("%m/%d/%Y %H:%M:%S.%f")
        if request.ts_response:
            request.ts_response = request.ts_response.strftime("%m/%d/%Y %H:%M:%S.%f")
        if request.elapsed > 5.0:
            slow_responses.add(f"0.0.0.0 {request.host}")
        if request.is_ad:
            ads.add(request.url)
        d = request.to_dict()
        serializable_requests.append(d)

    info["requests"] = serializable_requests
    info["redirects"] = page.event_handler.redirects
    info["slow_responses"] = list(slow_responses)
    info["ads"] = list(ads)

    # Try https://codebeautify.org/base64-to-image-converter
    if page.screenshot:
        info["screenshot"] = page.screenshot

    # Try https://www.base64decode.org/
    if page.content:
        info["content"] = b64encode(page.content.encode("utf-8")).decode("utf-8")

    info["elapsed"] = (datetime.now() - ts_start).total_seconds()
    json_info = json.dumps(info, indent=2)
    print(f"{json_info}")
    while keep_alive:
        sleep(1.0)


if __name__ == "__main__":
    main()
