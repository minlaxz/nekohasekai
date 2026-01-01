from typing import NotRequired, TypedDict


class ClashAPI(TypedDict):
    external_controller: str
    external_ui: NotRequired[str]
    external_ui_download_url: NotRequired[str]
    external_ui_download_detour: NotRequired[str]


class CacheFile(TypedDict):
    enabled: bool
    path: str


class Experimental(TypedDict):
    clash_api: ClashAPI
    cache_file: CacheFile
