#!/usr/bin/env python3

import re
import requests
import urllib.parse

from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)


def log_fail(*args, **kwargs):
    print(*args, **kwargs)
    raise RuntimeError(*args, **kwargs)


class Config:
    def __init__(self, host='https://localhost', username='admin', password='admin'):
        self._host = host
        self._user = username
        self._pass = password
        self._session = None
        self._csrf_token = None

        self.URLS = {
            'login': '/api/gateway/v1/login/',
            'controller_me': '/api/controller/v2/me/',
            'eda_server_me': '/api/eda/eda/v1/users/me/',
        }

        self._session = requests.Session()
        self._session.verify = False

    def get_session(self) -> requests.sessions.Session:
        return self._session

    def _get_csrf_token(self):
        res = self.get('login')
        assert res.status_code == 200, "Failed to get login which would give us the csrf"
        m = re.search('csrfToken: \"(.*?)\"', res.text)
        token = m.group(1)
        # self._session.cookies.set('csrftoken', token)
        self._csrf_token = token

    def login(self) -> bool:
        self._get_csrf_token()
        d = {
            'username': self._user,
            'password': self._pass,
            'csrfmiddlewaretoken': self._csrf_token,
        }
        """
        Login using form .. this is not ideal but I could not get
        JSON logging in to work w/ csrf. I tried putting the csrf in the cookies, that didn't work.
        """
        res = self.post('login', data=d, allow_redirects=False)
        assert res.status_code == 302, f"Logging in failed {res.status_code} {res.headers} {res.text}"
        return True

    def _url(self, path):
        return urllib.parse.urljoin(self._host, self.URLS[path])

    def get(self, path, *args, **kwargs):
        url = self._url(path)
        self._session.headers.update({'referer': url})
        return self._session.get(url, *args, **kwargs)

    def post(self, path, *args, **kwargs):
        url = self._url(path)
        self._session.headers.update({'referer': url})
        return self._session.post(url, *args, **kwargs)


def test_gateway_login(conf: Config):
    res = conf.login()
    assert res == True
    print("Success test_gateway_login")


def test_controller_authed(conf: Config):
    res = conf.get('controller_me')
    assert res.status_code == 200, f"Got status code {res.status_code}"
    print("Success test_controller_authed")


def test_eda_server_authed(conf: Config):
    res = conf.get('eda_server_me')
    assert res.status_code == 200, f"Got status code {res.status_code} {res.content}"
    print("Success test_eda_server_authed")


def run():
    conf = Config()
    test_gateway_login(conf)
    test_controller_authed(conf)
    test_eda_server_authed(conf)


if __name__ == "__main__":
    run()
