"""Browser regression for the HTML replica; all application APIs are mocked."""
import asyncio
import json
import os
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from urllib.parse import unquote, urlparse

from playwright.async_api import async_playwright, expect

BASE = os.getenv("BASE_URL", "http://127.0.0.1:18289").rstrip("/") + "/workspace"
OUT = Path(os.getenv("OUTPUT_DIR", str(Path(__file__).parent / "qa")))
USER = {"id": 9000, "username": "researcher", "email": "researcher@example.test"}
WEIGHTS = "Database\tDescription\tType\tSource\tNumber\tInverse Weight\nDemo\tUser data\t\tuploaded\t12\t0.02\nRef\tBarrier heights\tBH\tReference\t38\t0.208536487179584\n"
PREFIX = "The program starts running!\nengine: pyscf CF22D | preset=cc-pvqz | basis=cc-pvqz | ecp=none | grid level=6 | threads=128\nFound 12 structures in dataset 'Demo'.\nBasis preflight completed for preset 'cc-pvqz'.\nInitial density calculation\n[6/12] Li4 done (2.7 min)\n"
BRANCHES = [
    ("1", "ae", ["sto-3g"]),
    ("2", "ae", ["6-31g(d)", "def2-svp"]),
    ("2", "ecp", ["lanl2dz-ecp", "def2-svp-ecp"]),
    ("3", "ae", ["def2-tzvp", "def2-tzvpd", "cc-pvtz"]),
    ("3", "ecp", ["def2-tzvp-ecp"]),
    ("4", "ae", ["def2-qzvp", "aug-pc-3", "aug-cc-pvqz", "cc-pvqz", "def2-qzvpp", "def2-qzvppd"]),
    ("4", "ecp", ["def2-qzvp-ecp", "def2-qzvppd-ecp", "aug-cc-pwcvqz-pp"]),
    ("5", "ae", ["aug-pc-4", "aug-cc-pcv5z", "d-aug-cc-pv5z"]),
]


class Api:
    def __init__(self):
        self.short = False
        self.jobs = ["demo_failed", "demo_done"]
        self.runs = ["weight_0"]
        self.submits = []
        self.uploads = []
        self.logins = []
        self.unexpected = []
        self.release = asyncio.Event()
        self.release.set()

    async def route(self, route):
        request = route.request
        path = unquote(urlparse(request.url).path)
        if not path.startswith("/api_dft/"):
            if request.method not in ("GET", "HEAD"):
                self.unexpected.append(request.url)
                await route.abort()
            else:
                await route.continue_()
            return
        if path.endswith("/me"):
            await route.fulfill(json={"success": True, "user": USER})
        elif path.endswith("/login") or path.endswith("/register"):
            self.logins.append(request.post_data_json)
            await self.release.wait()
            await route.fulfill(json={"success": True, "token": "test-session", "user": USER})
        elif path.endswith("/file_list"):
            body = request.post_data_json
            folder = body["file_dir"].rstrip("/")
            if body["file_or_folder"] == "folder":
                names = self.jobs if folder == "Work/researcher" else self.runs
                rows = [{"name": name, "status": "Failed" if "failed" in folder + name else "Success", "time_modify": 1790860000 - index, "total_mue": "Total MUE: 0.00"} for index, name in enumerate(names)]
            else:
                names = ["basis.txt"] if folder.endswith("/input") else ["process.log"] if "/output/" not in folder else ["process.log", "Mue", "Parameters", "weight.csv", "SinglePointResults.json"]
                rows = [{"name": name} for name in names]
            await route.fulfill(json={"result": rows})
        elif path.endswith("/upload"):
            raw = ("Content-Type: " + request.headers["content-type"] + "\r\n\r\n").encode() + request.post_data_buffer
            mime = BytesParser(policy=default).parsebytes(raw)
            fields = [{"name": part.get_param("name", header="content-disposition"), "filename": part.get_filename(), "body": part.get_payload(decode=True).decode("utf8", "replace")} for part in mime.iter_parts()]
            self.uploads.append(fields)
            await self.release.wait()
            await route.fulfill(json={"result": "file upload success"})
        elif path.endswith("/submit"):
            body = request.post_data_json
            self.submits.append(body)
            if body["mode"] == "new":
                self.jobs.insert(0, body["work_dir"].rstrip("/").split("/")[-1])
            if body["mode"] == "optim":
                self.runs.append(body["weightFile"])
            await route.fulfill(json={"result": "work submit success"})
        elif path.endswith("/submit_count.txt"):
            await route.fulfill(content_type="text/plain", body="54")
        elif path.endswith("/basis.txt"):
            await route.fulfill(content_type="text/plain", body="cc-pvqz\n")
        elif path.endswith("/Mue"):
            await route.fulfill(content_type="text/plain", body="Database\tMUE\nDemo\t0.0\nRef\t1.24\nTotal MUE: 0.00")
        elif path.endswith("/Parameters"):
            await route.fulfill(content_type="text/plain", body="Parameters\n" + "0.462806\n" * 60)
        elif path.endswith("/weight.csv"):
            await route.fulfill(content_type="text/plain", body=WEIGHTS)
        elif path.endswith("/process.log"):
            log = "Short output\n" if self.short else PREFIX + ("[6/12] Li4 done. " + "details " * 30 + "\n") * 1500 + "[Error] SCF not converged for Li5\n"
            if "demo_done" in path:
                log = PREFIX + "[12/12] Last done\nParameters optimization finished\nSUCCESS!"
            await route.fulfill(content_type="text/plain", body=log)
        elif path.endswith("/SinglePointResults.json"):
            await route.fulfill(json={"targetRows": [], "summaryRows": [{"name": "Demo", "mue": 0.0}], "userTargetRows": [{"system": "H2", "reference": 1.0, "calculated": 1.2, "unbiasedError": 0.2}]})
        else:
            self.unexpected.append(f"{request.method} {path}")
            await route.fulfill(status=404, json={"message": "No fixture"})


async def wait_for(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("Expected API request was not observed")


async def fit(page):
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), "Horizontal page overflow"
    for item in await page.locator("dialog[open], .ws-grid, .detail").all():
        box = await item.bounding_box()
        if box:
            assert box["x"] >= -1 and box["x"] + box["width"] <= page.viewport_size["width"] + 1, box


async def capture(page, name, selector=None):
    if selector:
        await page.locator(selector).evaluate("e => e.scrollIntoView({block:'start',behavior:'instant'})")
    await page.screenshot(path=str(OUT / (name + ".png")))


async def run():
    OUT.mkdir(parents=True, exist_ok=True)
    reports = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for width, height in [(1440, 1000), (729, 977), (390, 844), (320, 800)]:
            context = await browser.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce")
            await context.add_init_script("localStorage.setItem('auth_token','test-session');localStorage.setItem('dfthub.theme','\"light\"')")
            api = Api()
            await context.route("**/*", api.route)
            page = await context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" and "fonts.googleapis" not in message.location.get("url", "") else None)
            await page.goto(BASE + "/", wait_until="networkidle")
            await expect(page.locator(".d-title h3")).to_have_text("demo_failed")
            await expect(page.get_by_role("tabpanel")).to_have_attribute("aria-busy", "false")
            await capture(page, f"{width}-top")
            await fit(page)
            await capture(page, f"{width}-workspace", "#workspace")

            await page.get_by_role("tab", name="Log", exact=True).click()
            await page.get_by_role("button", name="Full output", exact=True).click()
            box = page.locator("div.console")
            initial_height = (await box.bounding_box())["height"]
            assert await box.evaluate("e=>e.scrollHeight>e.clientHeight")
            await capture(page, f"{width}-log", "#detail")
            api.short = True
            await page.get_by_role("button", name="Refresh", exact=True).click()
            await expect(box).to_contain_text("Short output")
            assert abs((await box.bounding_box())["height"] - initial_height) <= 1

            await page.get_by_role("tab", name="Weights", exact=True).click()
            weight_input = page.get_by_role("textbox", name="Inverse weight for Demo", exact=True)
            await expect(weight_input).to_have_value("0.02")
            await weight_input.fill("0.01")
            await expect(page.get_by_role("region", name="Unsaved weight changes")).to_be_visible()
            await page.get_by_role("button", name="Discard", exact=True).click()
            await expect(weight_input).to_have_value("0.02")
            if width == 1440:
                await weight_input.fill("0.01")
                await page.get_by_role("button", name="Review & resubmit").click()
                await expect(page.get_by_role("dialog", name="Resubmit with new weights")).to_be_visible()
                await capture(page, "review-sheet")
                await page.get_by_role("dialog", name="Resubmit with new weights").get_by_role("button", name="Resubmit", exact=False).last.click()
                await wait_for(lambda: len(api.submits) == 1)
                assert api.submits[-1]["mode"] == "optim"
                weight_file = next(part["body"] for part in api.uploads[-1] if part["filename"] == "weight.csv")
                assert "Demo\tUser data\t\tuploaded\t12\t0.01" in weight_file
                assert "0.208536487179584" in weight_file
            await page.get_by_role("tab", name="Self-consistent results", exact=True).click()
            await expect(page.get_by_role("table", name="Single-point energies", exact=True)).to_be_visible()
            await fit(page)

            await page.locator(".nav").get_by_role("button", name="New job", exact=True).click()
            dialog = page.get_by_role("dialog", name="New job", exact=True)
            await dialog.locator(".advanced-settings > summary").click()
            await expect(dialog).to_be_visible()
            await expect(dialog.get_by_role("button", name="Submit job", exact=True)).to_be_disabled()
            await dialog.locator("#fTgz").set_input_files({"name": "Demo.tgz", "mimeType": "application/gzip", "buffer": b"test"})
            await expect(dialog.locator("#dropTgz")).to_have_class("drop has")
            await dialog.get_by_role("button", name="Remove geometry file").click()
            await expect(dialog.locator("#dropTgz")).to_have_class("drop")
            await dialog.locator("#fTgz").set_input_files({"name": "Demo.tgz", "mimeType": "application/gzip", "buffer": b"test"})
            await dialog.locator("#fRef").set_input_files({"name": "Demo.ref", "mimeType": "text/plain", "buffer": b"0.0"})
            await dialog.locator("#fW").fill("0")
            await expect(dialog.get_by_role("button", name="Submit job", exact=True)).to_be_disabled()
            await dialog.locator("#fW").fill("0.02")
            if width == 1440:
                for level, core, names in BRANCHES:
                    await dialog.locator(f'#fZeta [data-v="{level}"]').click()
                    await dialog.locator(f'#fEcp [data-v="{core}"]').click()
                    await dialog.locator("#fBasis").click()
                    await expect(dialog.locator("[data-basis]")).to_have_count(len(names))
                    await page.keyboard.press("Escape")
                    await expect(dialog).to_be_visible()
                    for name in names:
                        await dialog.locator("#fBasis").click()
                        await dialog.locator(f'[data-basis="{name}"]').click()
                        await expect(dialog.locator("[data-basis]")).to_have_count(0)
            await dialog.locator('#fZeta [data-v="4"]').click()
            await dialog.locator('#fEcp [data-v="ae"]').click()
            await dialog.locator("#fBasis").click()
            await dialog.locator('[data-basis="cc-pvqz"]').click()
            await capture(page, f"{width}-new-job")
            await fit(page)
            if width == 1440:
                before = len(api.submits)
                api.release.clear()
                await dialog.get_by_role("button", name="Submit job", exact=True).click()
                await wait_for(lambda: len(api.uploads) == 2)
                await expect(dialog.get_by_role("button", name="Uploading…", exact=True)).to_be_disabled()
                await dialog.locator("form").evaluate("e => e.requestSubmit()")
                await asyncio.sleep(0.1)
                assert len(api.uploads) == 2
                api.release.set()
                await wait_for(lambda: len(api.submits) == before + 1)
                await expect(dialog).not_to_be_visible()
                assert api.submits[-1]["basis"] == "cc-pvqz"
                init_file = next(part["body"] for part in api.uploads[-1] if part["filename"] == "init_weight.csv")
                assert init_file.splitlines()[-1].split(",", 1)[0] == "Demo", init_file
            else:
                await dialog.get_by_role("button", name="Cancel", exact=True).click()
            await page.get_by_role("button", name="Open account menu").click()
            await page.get_by_role("menuitem", name="Appearance:", exact=False).click()
            await expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            await page.keyboard.press("Escape")
            await capture(page, f"{width}-dark", "#workspace")
            assert not errors, errors
            assert not api.unexpected, api.unexpected
            reports.append({"viewport": f"{width}x{height}", "console_height": initial_height, "errors": errors, "submits": len(api.submits)})
            print("PASS", width, flush=True)
            await context.close()

        context = await browser.new_context(viewport={"width": 729, "height": 977})
        api = Api()
        await context.route("**/*", api.route)
        page = await context.new_page()
        await page.goto(BASE, wait_until="networkidle")
        await page.get_by_role("button", name="Sign in", exact=True).click()
        auth = page.get_by_role("dialog", name="Sign in to DFThub")
        await auth.locator("#authEmail").fill(USER["email"])
        await auth.locator("#authPassword").fill("test-password")
        await auth.locator("#authPassword").press("Enter")
        await expect(auth).not_to_be_visible()
        await expect(page.locator(".d-title h3")).to_have_text("demo_failed")
        assert len(api.logins) == 1
        await context.close()
        await browser.close()
    (OUT / "report.json").write_text(json.dumps({"mocked_api": True, "views": reports, "auth": "passed"}, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
