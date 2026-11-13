from flask import abort, redirect, request, send_from_directory
from .paths import PACKAGE, initialize_data


def create_app():
    initialize_data()
    from .api.app import appx
    if "dfthub_pages" in appx.view_functions:
        return appx
    static = PACKAGE / "static"

    @appx.get("/")
    @appx.get("/<path:path>")
    def dfthub_pages(path=""):
        if path.startswith("api_dft/"):
            abort(404)
        query = "?" + request.query_string.decode() if request.query_string else ""
        if path in {"dfthub", "dfthub/"}:
            return redirect("/" + query, 308)
        if path in {"workspace", "analyze", "guide", "energy"}:
            return redirect("/" + path + "/" + query, 308)
        if path in {"", "workspace/", "analyze/", "guide/", "energy/"}:
            return send_from_directory(static, path + "index.html")
        target = (static / path).resolve()
        if target.is_relative_to(static) and target.is_file():
            return send_from_directory(static, path)
        return send_from_directory(static, "404.html"), 404
    return appx
