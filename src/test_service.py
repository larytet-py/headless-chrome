import pytest
from service import main
from requests import post
import traceback


@pytest.hookimpl(tryfirst=True)
def pytest_keyboard_interrupt(excinfo):
    traceback.format_exc()


def setup_module(module):
    module.http_server_thread, module.http_server = main()


def teardown_module(module):
    print(
        "Tearing down ...",
    )
    module.http_server.shutdown()
    module.http_server_thread.join()
    print("completed")


def test_post():
    url = "http://0.0.0.0:8081/fetch?ur=http%3A%2F%2Fgoogle.com&transaction_id=1"
    request_result = post(url)
    assert (
        request_result.status_code == 200
    ), f"Got response for {url} {request_result.status_code} {request_result.text}"

    url = "http://0.0.0.0:8081/futch?ur=http%3A%2F%2Fgoogle.com&transaction_id=2"
    request_result = post(url)
    assert (
        request_result.status_code == 400
    ), f"Got response for {url} {request_result.status_code} {request_result.text}"
