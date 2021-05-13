from urllib.parse import urlparse, parse_qs
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Semaphore, Thread
from time import time, sleep
from os import environ
from dataclasses import dataclass
from contextlib import contextmanager


@dataclass
class Statistics:
    timer_1s: int = 0
    acquire_latency: float = 0
    acquire_latency_max: float = 0
    acquire_failed: int = 0
    resp_200: int = 0
    resp_400: int = 0
    acquire_pending_max: int = 0
    acquire_pending: int = 0
    unknow_post: int = 0


_statistics = Statistics()


class LoggerAdapter(logging.LoggerAdapter):
    def __init__(self, logger, transaction_id):
        super(LoggerAdapter, self).__init__(logger, {})
        self._transaction_id = transaction_id

    def process(self, msg, kwargs):
        return "[%s] %s" % (self._transaction_id, msg), kwargs


def _get_url_parameter(parameters, name, default=""):
    return parameters.get(name, [default])[0]


class HeadlessnessServer(BaseHTTPRequestHandler):
    def __init__(self, logger):
        self.logger = logger

    def __call__(self, *args, **kwargs):
        """
        See https://stackoverflow.com/questions/21631799/how-can-i-pass-parameters-to-a-requesthandler
        """
        super().__init__(*args, **kwargs)

    # default process at most 1 query
    _throttle_max, _throttle = 1, Semaphore(1)

    def _400(self, msg):
        try:
            self.send_response(400)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(msg.encode("utf-8"))
            _statistics.resp_400 += 1
        except Exception as e:
            self._logger.error(f"Faied to write to remote {e}")

    def _200(self, msg):
        try:
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(msg.encode("utf-8"))
            _statistics.resp_200 += 1
        except Exception as e:
            self._logger.error(f"Faied to write to remote {e}")

    @contextmanager
    def _check_throttle(self):
        time_start = time()
        if not HeadlessnessServer._throttle.acquire(blocking=True, timeout=40.0):
            _statistics.acquire_failed += 1
            err_msg = "Too many requests"
            self._logger.error(err_msg)
            self._400(err_msg)
            return False

        elapsed_time = time() - time_start
        _statistics.acquire_latency = elapsed_time
        _statistics.acquire_latency_max = max(
            _statistics.acquire_latency_max, _statistics.acquire_latency_max
        )
        _statistics.acquire_pending = (
            HeadlessnessServer._throttle_max - HeadlessnessServer._throttle._value
        )
        _statistics.acquire_pending_max = max(
            _statistics.acquire_pending_max, _statistics.acquire_pending
        )
        yield True
        HeadlessnessServer._throttle.release()

    def _process_post(self, parsed_url):
        if parsed_url.path not in ["/fetch"]:
            _statistics.unknow_post += 1
            err_msg = f"Unknown post {parsed_url.path}"
            self._logger.error(err_msg)
            self._400(err_msg)
            return
        self._200("Ok")

    def do_POST(self):
        parsed_url = urlparse(self.path)
        parameters = parse_qs(parsed_url.query)

        _transaction_id = _get_url_parameter(parameters, "transaction_id")
        self._logger = LoggerAdapter(self.logger, _transaction_id)
        self._logger.debug(
            "POST request, path %s, headers %s", str(self.path), str(self.headers)
        )
        with self._check_throttle() as ok:
            if not ok:
                return
            self._process_post(parsed_url)


def shutdown():
    global is_running
    is_running = False


def main():
    logger = logging.getLogger("headlessness")
    logger_format = "%(levelname)s:%(filename)s:%(lineno)d:%(message)s"
    logging.basicConfig(format=logger_format)
    loglevel = environ.get("LOG_LEVEL", "INFO").upper()
    logger.setLevel(loglevel)
    logger.debug("I am using debug log level")

    http_port = int(environ.get("PORT", 8081))
    http_interface = environ.get("INTERFACE", "0.0.0.0")
    http_server = ThreadingHTTPServer(
        (http_interface, http_port), HeadlessnessServer(logger)
    )
    http_server_thread = Thread(target=http_server.serve_forever)
    http_server_thread.start()
    return http_server_thread, http_server


if __name__ == "__main__":
    is_running = True
    http_server_thread, http_server = main()
    while is_running:
        sleep(1.0)
        _statistics.timer_1s += 1
    http_server.shutdown()
    http_server_thread.join()
