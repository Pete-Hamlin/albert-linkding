from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from time import perf_counter_ns
from urllib import parse

import requests
from albert import *

md_iid = "3.0"
md_version = "3.4"
md_name = "Linkding"
md_description = "Manage saved bookmarks via a linkding instance"
md_license = "MIT"
md_url = "https://github.com/Pete-Hamlin/albert-python"
md_authors = ["@Pete-Hamlin"]
md_lib_dependencies = ["requests"]


class LinkFetcherThread(Thread):
    def __init__(self, callback, cache_length, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.__stop_event = Event()
        self.__callback = callback
        self.__cache_length = cache_length * 60

    def run(self):
        self.__callback()
        while True:
            self.__stop_event.wait(self.__cache_length)
            if self.__stop_event.is_set():
                return
            self.__callback()

    def stop(self):
        self.__stop_event.set()


class Plugin(PluginInstance, IndexQueryHandler):
    iconUrls = [f"file:{Path(__file__).parent}/linkding.png"]
    limit = 250
    user_agent = "org.albert.linkding"

    def __init__(self):
        PluginInstance.__init__(self)
        IndexQueryHandler.__init__(self)

        self._index_items = []

        self._instance_url = self.readConfig("instance_url", str) or "http://localhost:9090"
        self._api_key = self.readConfig("api_key", str) or ""
        self._cache_length = self.readConfig("cache_length", int) or 15

        self._thread = LinkFetcherThread(callback=self.fetchIndexItems, cache_length=self._cache_length)
        self._thread.start()

    def __del__(self):
        self._thread.stop()
        self._thread.join()

    def defaultTrigger(self):
        return "ld "

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
    def cache_length(self):
        return self._cache_length

    @cache_length.setter
    def cache_length(self, value):
        value = 1 if value < 1 else value
        self._cache_length = value
        self.cache_timeout = datetime.now()
        self.writeConfig("cache_length", value)

        if self._thread.is_alive():
            self._thread.stop()
            self._thread.join()
        self._thread = LinkFetcherThread(callback=self.fetchIndexItems, cache_length=self._cache_length)
        self._thread.start()

    def configWidget(self):
        return [
            {"type": "lineedit", "property": "instance_url", "label": "URL"},
            {
                "type": "lineedit",
                "property": "api_key",
                "label": "API key",
                "widget_properties": {"echoMode": "Password"},
            },
            {"type": "spinbox", "property": "cache_length", "label": "Cache length (minutes)"},
        ]

    def updateIndexItems(self):
        self.setIndexItems(self._index_items)

    def fetchIndexItems(self):
        start = perf_counter_ns()
        data = self._fetch_results()
        for link in data:
            filter = self._create_filters(link)
            item = self._gen_item(link)
            self._index_items.append(IndexItem(item=item, string=filter))
        self.updateIndexItems()
        info("Indexed {} links [{:d} ms]".format(len(self._index_items), (int(perf_counter_ns() - start) // 1000000)))
        self._index_items = []


    def handleTriggerQuery(self, query):
        stripped = query.string.strip()
        if stripped:
            TriggerQueryHandler.handleTriggerQuery(self, query)
        else:
            query.add(
                StandardItem( text=md_name, subtext="Search for an article saved in Linkding", iconUrls=self.iconUrls)
            )
        query.add(
            StandardItem(
                text="Refresh cache index",
                subtext="Refresh indexed links",
                iconUrls=["xdg:view-refresh"],
                actions=[Action("refresh", "Refresh Linkding index", lambda: self.fetchIndexItems())],
            )
        )


    def _create_filters(self, item: dict):
        return ",".join([item["url"], item["title"], ",".join(tag for tag in item["tag_names"])])

    def _gen_item(self, link: dict):
        return StandardItem(
            id=str(self.id),
            text=link["title"] or link["url"],
            subtext="{}: {}".format(",".join(tag for tag in link["tag_names"]), link["url"]),
            iconUrls=self.iconUrls,
            actions=[
                Action("open", "Open link", lambda u=link["url"]: openUrl(u)),
                Action("copy", "Copy URL to clipboard", lambda u=link["url"]: setClipboardText(u)),
                Action("archive", "Archive link", lambda u=link["id"]: self._archive_link(u)),
                Action("delete", "Delete link", lambda u=link["id"]: self._archive_link(u)),
            ],
        )

    def _fetch_results(self):
        params = {"limit": self.limit}
        headers = {"User-Agent": self.user_agent, "Authorization": f"Token {self._api_key}"}
        url = f"{self._instance_url}/api/bookmarks/?{parse.urlencode(params)}"
        return (link for link_list in self._get_links(url, headers) for link in link_list)

    def _get_links(self, url: str | None, headers: dict):
        while url:
            response = requests.get(url, headers=headers, timeout=5)
            if response.ok:
                result = response.json()
                url = result["next"]
                yield result["results"]
            else:
                warning(f"Got response {response.status_code} querying {url}")
                url = None

    def _delete_link(self, link_id: str):
        url = f"{self._instance_url}/api/bookmarks/{link_id}"
        headers = {"User-Agent": self.user_agent, "Authorization": f"Token {self._api_key}"}
        debug("About to DELETE {}".format(url))
        response = requests.delete(url, headers=headers)
        if response.ok:
            self.fetchIndexItems()
        else:
            warning("Got response {}".format(response))

    def _archive_link(self, link_id: str):
        url = f"{self._instance_url}/api/bookmarks/{link_id}/archive/"
        headers = {"User-Agent": self.user_agent, "Authorization": f"Token {self._api_key}"}
        debug("About to POST {}".format(url))
        response = requests.post(url, headers=headers)
        if response.ok:
            self.fetchIndexItems()
        else:
            warning("Got response {}".format(response))
