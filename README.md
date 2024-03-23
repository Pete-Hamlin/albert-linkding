# Albert Obsidian

A python plugin to allow [albert](https://github.com/albertlauncher/albert) to interact with a [linkding](https://github.com/sissbruecker/linkding) instance.
Currently supports the following features
- Trigger query search of links (default `ld`) by URL/name/tags
- Global query results from vault notes via URL/name/tags
- Queries support:
    - Opening of links in browser
    - Copying link URLs
    - Archiving link
    - Deleting link
- An indexer that re-indexes on a configurable interval (default: `15` minutes)
- Some [basic settings](#settings) to customise behaviour

## Install

Run the follow from a terminal:

```shell
git clone https://github.com/Pete-Hamlin/albert-linkding.git $HOME/.local/share/albert/python/plugins/linkding
```

Then enable the plugin from the albert settings panel (you **must** enable the python plugin for this plugin to be visible/loadable)

## Settings

- `instance_url`: URL where your linkding instance is hosted - default `http://localhost:9090`
- `api_key`: A valid API token for the linkding API. The application automatically generates an API token for each user, which can be accessed through the Settings page. - default `None`
- `cache_length`: The length of time to wait between refreshing the index of links (in minutes). - default `15`
