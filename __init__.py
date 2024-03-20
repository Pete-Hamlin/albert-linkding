import json
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from time import sleep
from urllib import parse

import requests
from albert import *

md_iid = "2.1"
md_version = "2.0"
md_name = "Linkding"
md_description = "Manage saved bookmarks via a linkding instance"
md_license = "MIT"
md_url = "https://github.com/Pete-Hamlin/albert-python"
md_maintainers = ["@Pete-Hamlin"]
md_lib_dependencies = ["requests"]


class Plugin(PluginInstance, GlobalQueryHandler, TriggerQueryHandler):
    iconUrls = [f"file:{Path(__file__).parent}/linkding.png"]
    limit = 50
    user_agent = "org.albert.linkding"

    def __init__(self):
        TriggerQueryHandler.__init__(
            self,
            id=md_id,
            name=md_name,
            description=md_description,
            synopsis="<article-name>",
            defaultTrigger="ld ",
        )
        GlobalQueryHandler.__init__(self, id=md_id, name=md_name, description=md_description, defaultTrigger="ld ")
        PluginInstance.__init__(self, extensions=[self])

        self._instance_url = self.readConfig("instance_url", str) or "http://localhost:9090"
        self._api_key = self.readConfig("api_key", str) or ""
        self._cache_results = self.readConfig("cache_results", bool) or True
        self._cache_length = self.readConfig("cache_length", int) or 60
        self._auto_cache = self.readConfig("auto_cache", bool) or False

        self.cache_timeout = datetime.now()
        self.cache_file = self.cacheLocation / "linkding.json"
        self.cache_thread = Thread(target=self.cache_routine, daemon=True)
        self.thread_stop = Event()

        if not self._auto_cache:
            self.thread_stop.set()

        self.cache_thread.start()

    @property
    def instance_url(self):
        return self._instance_url

    @instance_url.setter
    def instance_url(self, value):
        self._instance_url = value
        self.writeConfig("instance_url", value)

    @property
    def api_key(self):
        return self._api_key

    @api_key.setter
    def api_key(self, value):
        self._api_key = value
        self.writeConfig("api_key", value)

    @property
    def cache_results(self):
        return self._cache_results

    @cache_results.setter
    def cache_results(self, value):
        self._cache_results = value
        if not self._cache_results:
            # Cleanup cache file
            self.cache_file.unlink(missing_ok=True)
        self.writeConfig("cache_results", value)

    @property
    def cache_length(self):
        return self._cache_length

    @cache_length.setter
    def cache_length(self, value):
        self._cache_length = value
        self.cache_timeout = datetime.now()
        self.writeConfig("cache_length", value)

    @property
    def auto_cache(self):
        return self._auto_cache

    @auto_cache.setter
    def auto_cache(self, value):
        self._auto_cache = value
        if self._auto_cache and self._cache_results:
            self.thread_stop.clear()
        else:
            self.thread_stop.set()
        self.writeConfig("auto_cache", value)

    def configWidget(self):
        return [
            {"type": "lineedit", "property": "instance_url", "label": "URL"},
            {
                "type": "lineedit",
                "property": "api_key",
                "label": "API key",
                "widget_properties": {"echoMode": "Password"},
            },
            {"type": "checkbox", "property": "cache_results", "label": "Cache results locally"},
            {"type": "spinbox", "property": "cache_length", "label": "Cache length (minutes)"},
            {"type": "checkbox", "property": "auto_cache", "label": "Periodically cache articles"},
        ]

    def handleTriggerQuery(self, query):
        stripped = query.string.strip()
        if stripped:
            # avoid spamming server
            for _ in range(50):
                sleep(0.01)
                if not query.isValid:
                    return

            data = self.get_results()
            articles = (item for item in data if stripped in self.create_filters(item))
            items = [item for item in self.gen_items(articles)]
            query.add(items)
        else:
            query.add(
                StandardItem(
                    id=md_id, text=md_name, subtext="Search for an article saved via Linkding", iconUrls=self.iconUrls
                )
            )
            if self._cache_results:
                query.add(
                    StandardItem(
                        id=md_id,
                        text="Refresh cache",
                        subtext="Refresh cached articles",
                        iconUrls=["xdg:view-refresh"],
                        actions=[Action("refresh", "Refresh article cache", lambda: self.refresh_cache())],
                    )
                )

    def handleGlobalQuery(self, query):
        stripped = query.string.strip()
        if stripped and self.cache_file.is_file():
            # If we have results cached display these, otherwise disregard (we don't want to make fetch requests in the global query)
            data = (item for item in self.read_cache())
            articles = (item for item in data if stripped in self.create_filters(item))
            items = [RankItem(item=item, score=0) for item in self.gen_items(articles)]
            return items

    def create_filters(self, item: dict):
        # TODO: Add filter options?
        return ",".join([item["url"], item["title"], ",".join(tag for tag in item["tag_names"])])

    def gen_items(self, articles: object):
        for article in articles:
            yield StandardItem(
                id=md_id,
                text=article["title"] or article["url"],
                subtext="{}: {}".format(",".join(tag for tag in article["tag_names"]), article["url"]),
                iconUrls=self.iconUrls,
                actions=[
                    Action("open", "Open article", lambda u=article["url"]: openUrl(u)),
                    Action("copy", "Copy URL to clipboard", lambda u=article["url"]: setClipboardText(u)),
                    Action("archive", "Archive article", lambda u=article["id"]: self.archive_link(u)),
                    Action("delete", "Delete article", lambda u=article["id"]: self.archive_link(u)),
                ],
            )

    def get_results(self):
        if self._cache_results:
            return self._get_cached_results()
        return self.fetch_results()

    def fetch_results(self):
        params = {"limit": self.limit}
        headers = {"User-Agent": self.user_agent, "Authorization": f"Token {self._api_key}"}
        url = f"{self._instance_url}/api/bookmarks/?{parse.urlencode(params)}"
        return (article for article_list in self.get_articles(url, headers) for article in article_list)

    def get_articles(self, url: str, headers: dict):
        while url:
            response = requests.get(url, headers=headers, timeout=5)
            if response.ok:
                result = response.json()
                url = result["next"]
                yield result["results"]
            else:
                warning(f"Got response {response.status_code} querying {url}")

    def _get_cached_results(self):
        if self.cache_file.is_file() and self.cache_timeout >= datetime.now():
            debug("Cache hit")
            results = self.read_cache()
            return (item for item in results)
        # Cache miss
        debug("Cache miss")
        return self.refresh_cache()

    def cache_routine(self):
        while True:
            if not self.thread_stop.is_set():
                self.refresh_cache()
            sleep(3600)

    def refresh_cache(self):
        results = self.fetch_results()
        self.cache_timeout = datetime.now() + timedelta(minutes=self._cache_length)
        return self.write_cache([item for item in results])

    def delete_link(self, link_id: str):
        url = f"{self._instance_url}/api/bookmarks/{link_id}"
        headers = {"User-Agent": self.user_agent, "Authorization": f"Token {self._api_key}"}
        debug("About to DELETE {}".format(url))
        response = requests.delete(url, headers=headers)
        if response.ok:
            self.refresh_cache()
        else:
            warning("Got response {}".format(response))

    def archive_link(self, link_id: str):
        url = f"{self._instance_url}/api/bookmarks/{link_id}/archive/"
        headers = {"User-Agent": self.user_agent, "Authorization": f"Token {self._api_key}"}
        debug("About to POST {}".format(url))
        response = requests.post(url, headers=headers)
        if response.ok:
            self.refresh_cache()
        else:
            warning("Got response {}".format(response))

    def read_cache(self):
        with self.cache_file.open("r") as cache:
            return json.load(cache)

    def write_cache(self, data: list[dict]):
        with self.cache_file.open("w") as cache:
            cache.write(json.dumps(data))
        return (item for item in data)
