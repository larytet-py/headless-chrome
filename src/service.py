from urllib.parse import urlparse, parse_qs
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Semaphore
from time import time
from os.environ import environ


class Statistics:
    def __init__(self):
        self.acquire_latency = 0.0
        self.acquire_latency_max = 0.0
        self.acquire_failed = 0
        self.resp_400 = 0
        self.acquire_pending_max = 0
        self.acquire_pending = 0


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

    def _400(self):
        self.send_response(400)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        _statistics.resp_400 += 1

    def _check_throttle(self):
        time_start = time()
        if not HeadlessnessServer._throttle.acquire(blocking=True, timeout=40.0):
            _statistics.acquire_failed += 1
            err_msg = "Too many requests"
            self._logger.error(err_msg)
            try:
                self._400()
                self.wfile.write(err_msg.encode("utf-8"))
            except Exception as e:
                self._logger.error(f"Faied to write to remote {e}")
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
        return True

    def do_POST(self):
        parsed_url = urlparse(self.path)
        parameters = parse_qs(parsed_url.query)

        _transaction_id = _get_url_parameter(parameters, "transaction_id")
        self._logger = LoggerAdapter(self.logger, _transaction_id)
        self._logger.debug(
            "POST request, path %s, headers %s", str(self.path), str(self.headers)
        )
        if not self._check_throttle():
            return


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
    http_server.serve_forever()


if __name__ == "__main__":
    main()
