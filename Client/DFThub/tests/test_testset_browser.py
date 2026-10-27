import asyncio
import os
from urllib.parse import unquote, urlparse
from playwright.async_api import async_playwright, expect

BASE = os.getenv("BASE_URL", "http://127.0.0.1:18289").rstrip("/")


async def main():
    uploads = []
    submits = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1366, "height": 977})
        await context.add_init_script("localStorage.setItem('auth_token','test');localStorage.setItem('dfthub.theme','\"light\"')")

        async def route(request):
            path = unquote(urlparse(request.request.url).path)
            if path.endswith("/me"):
                return await request.fulfill(json={"success": True, "user": {"id": 1, "username": "researcher", "email": "r@example.test"}})
            if path.endswith("/submit_count.txt"):
                return await request.fulfill(content_type="text/plain", body="1")
            if path.endswith("/file_list"):
                body = request.request.post_data_json
                folder = body["file_dir"].rstrip("/")
                if body["file_or_folder"] == "folder":
                    names = ["demo"] if folder == "Work/researcher" else ["weight_0"] if folder.endswith("/output") else []
                else:
                    names = ["basis.txt", "Demo.tgz", "Demo.ref"] if folder.endswith("/input") else ["process.log"]
                return await request.fulfill(json={"result": [{"name": name, "status": "Success", "time_modify": 1790930000} for name in names]})
            if path.endswith("/upload"):
                uploads.append(request.request.post_data_buffer)
                return await request.fulfill(json={"result": "file upload success"})
            if path.endswith("/submit"):
                submits.append(request.request.post_data_json)
                return await request.fulfill(json={"result": "work submit success"})
            if "/download/" in path:
                return await request.fulfill(content_type="text/plain", body="SUCCESS!\n")
            return await request.continue_()

        await context.route("**/api_dft/**", route)
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto(BASE + "/workspace/", wait_until="networkidle")
        await page.get_by_role("button", name="New job", exact=True).first.click()
        dialog = page.get_by_role("dialog", name="New job", exact=True)
        await dialog.locator("#fTgz").set_input_files({"name": "Demo.tgz", "mimeType": "application/gzip", "buffer": b"train"})
        await dialog.locator("#fRef").set_input_files({"name": "Demo.ref", "mimeType": "text/plain", "buffer": b"train"})
        await dialog.locator("#fTestTgz").set_input_files({"name": "Test.tgz", "mimeType": "application/gzip", "buffer": b"test"})
        await expect(dialog.get_by_role("button", name="Submit job", exact=True)).to_be_disabled()
        await dialog.locator("#fTestRef").set_input_files({"name": "Test.ref", "mimeType": "text/plain", "buffer": b"test"})
        await expect(dialog.get_by_role("button", name="Submit job", exact=True)).to_be_enabled()
        await dialog.get_by_role("button", name="Submit job", exact=True).click()
        await expect(dialog).not_to_be_visible()
        assert submits and submits[-1]["mode"] == "new"
        body = uploads[-1].decode("utf-8", "replace")
        assert "test_Test.tgz" in body and "test_Test.ref" in body and "test_manifest.json" in body
        assert not errors, errors
        print("PASS optional test-set pair validation, upload manifest and new-job submission")
        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
